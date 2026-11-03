# -*- coding: utf-8 -*-
"""task-146: memory entries in SQLite (same pattern as the entity graph).

Storage contract:
- one SQLite file per plugin data dir: memory/memory.sqlite3
  (WAL, synchronous=NORMAL, busy_timeout=5000, explicit transactions);
- table entries: id PK + the task-146 columns, plus two additive columns
  (session, seq) that are required because one DB holds every session, and
  raw (the full entry JSON) so unknown/future fields roundtrip losslessly;
- table session_docs: per-session non-entry fields (tombstones / working_set /
  write_log / marker ...) as one JSON blob;
- table meta: schema_version + migration bookkeeping.

Compatibility rules (老用户升级不能丢数据):
- every save_doc() also writes the legacy JSON mirror (memory/<session>.json),
  so a downgrade to a JSON-only build still reads current data;
- ensure_store() imports legacy memory/*.json when the DB is empty, and
  merges when the JSON mirror is newer than the DB row (downgrade period);
- a corrupt DB is backed up to *.corrupt.bak and rebuilt from the JSON mirrors;
- a corrupt JSON file is skipped (never crashes startup);
- the whole memory/ directory is backed up before the first import;
- every entry point degrades to JSON mode instead of raising.

Dedupe (task-147, SillyTavern-style):
- every row carries text_hash = sha1(normalize(text)) (whitespace/punctuation
  removed, lower-cased); a UNIQUE(session, text_hash) index keeps one row per
  normalized sentence;
- a second semantic pass compares same-session vectors (latest 200 rows):
  cosine >= 0.95 merges as a paraphrase duplicate, 0.90-0.95 only logs;
- duplicate writes merge into the existing row (earliest ts, higher importance,
  summed hits/access_count) instead of inserting;
- existing DBs are migrated once (backup first) with a bounded dedupe pass.

IO lives here on purpose (storage layer); no import of main.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import shutil
import sqlite3
import time
from pathlib import Path

try:  # AstrBot host logger (offline tests get a null logger)
    from astrbot.api import logger
except Exception:  # pragma: no cover
    class _NullLogger:
        def _noop(self, *args, **kwargs):
            return None
        debug = info = warning = error = exception = critical = _noop
    logger = _NullLogger()

SQLITE_FILE = "memory.sqlite3"
SCHEMA_VERSION = 5
EXPORT_SUFFIX = ".export.json"
EXPORT_NAME = "memory_export.json"
JSON_SUFFIX = ".json"
TEXT_HASH_INDEX = "idx_entries_session_hash"
SEMANTIC_MERGE_THRESHOLD = 0.95
SEMANTIC_LOG_THRESHOLD = 0.90
SEMANTIC_SCAN_LIMIT = 200

_ENTRY_COLUMNS = (
    "id", "session", "seq", "text", "role", "ts", "importance", "vector",
    "storage_s", "retrieval_s", "access_count", "hits", "inhibition",
    "suppression_count", "memory_tier", "memory_source", "memory_confidence",
    "arousal_at_encoding", "hidden", "tags", "text_hash", "raw",
)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS entries(
    id TEXT PRIMARY KEY,
    session TEXT NOT NULL,
    seq INTEGER NOT NULL DEFAULT 0,
    text TEXT,
    role TEXT,
    ts REAL,
    importance REAL,
    vector BLOB,
    storage_s REAL,
    retrieval_s REAL,
    access_count INTEGER,
    hits INTEGER,
    inhibition REAL,
    suppression_count INTEGER,
    memory_tier TEXT,
    memory_source TEXT,
    memory_confidence REAL,
    arousal_at_encoding REAL,
    hidden INTEGER,
    tags TEXT,
    text_hash TEXT,
    raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_entries_session ON entries(session);
CREATE INDEX IF NOT EXISTS idx_entries_ts ON entries(ts);
CREATE INDEX IF NOT EXISTS idx_entries_importance ON entries(importance);
CREATE INDEX IF NOT EXISTS idx_entries_hidden ON entries(hidden);
CREATE INDEX IF NOT EXISTS idx_entries_tier ON entries(memory_tier);
CREATE TABLE IF NOT EXISTS session_docs(
    session TEXT PRIMARY KEY, doc TEXT, updated_at REAL);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


# ---------------------------------------------------------------- helpers
def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return float(default)
    if number != number or number in (float("inf"), float("-inf")):
        return float(default)
    return number


def _json_dump(value):
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return "null"


def _json_load(raw, default=None):
    try:
        value = json.loads(raw or "")
    except Exception:
        return default
    return value if value is not None else default


def normalize_text(text):
    """Dedupe normalization: lower-case + drop whitespace/punctuation."""
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def text_hash(text):
    """sha1 of the normalized text (stable across whitespace/punctuation)."""
    return hashlib.sha1(normalize_text(text).encode("utf-8")).hexdigest()


def cosine(left, right):
    """Cosine similarity of two equal-length vectors (0.0 on invalid input)."""
    if not isinstance(left, (list, tuple)) or not isinstance(right, (list, tuple)):
        return 0.0
    if not left or len(left) != len(right):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for first, second in zip(left, right):
        value_a = _num(first)
        value_b = _num(second)
        dot += value_a * value_b
        norm_a += value_a * value_a
        norm_b += value_b * value_b
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


def bigrams(text):
    """Character bigram set of the normalized text (cheap cosine prefilter)."""
    norm = normalize_text(text)
    if len(norm) < 2:
        return {norm} if norm else set()
    return {norm[index:index + 2] for index in range(len(norm) - 1)}


def prefilter_ok(left_bigrams, right_bigrams, threshold=0.55):
    """Jaccard bigram prefilter: only close texts are worth a cosine compare."""
    if not left_bigrams or not right_bigrams:
        return False
    inter = len(left_bigrams & right_bigrams)
    if not inter:
        return False
    union = len(left_bigrams) + len(right_bigrams) - inter
    return (inter / float(union)) >= threshold


def safe_session_name(session_key):
    raw = str(session_key or "default")
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in raw)[:80] or "default"


def entry_key(entry, session="", used=None):
    """Stable entry id; matches main._memory_entry_id_of for legacy entries.

    Collisions (identical text in different sessions / duplicate rows) get a
    deterministic suffix so the id primary key keeps every row.
    """
    used = used if isinstance(used, set) else set()
    base = str((entry or {}).get("id") or "").strip() if isinstance(entry, dict) else ""
    if not base:
        import hashlib
        text = str((entry or {}).get("text") or "").strip() if isinstance(entry, dict) else ""
        base = hashlib.sha256(text[:300].encode("utf-8")).hexdigest()[:12] if text else ""
    if not base:
        base = "m" + hashlib.sha256(
            (_json_dump(entry) + "|" + str(session)).encode("utf-8")).hexdigest()[:11]
    candidate = base
    index = 1
    while candidate in used:
        index += 1
        candidate = "%s-%d" % (base, index)
    used.add(candidate)
    return candidate


def encode_vector(vector):
    """list[float] -> BLOB (little-endian float64); None for empty/invalid."""
    if not isinstance(vector, (list, tuple)) or not vector:
        return None
    import array
    try:
        values = array.array("d", [_num(item) for item in vector])
    except Exception:
        return None
    if not values:
        return None
    return values.tobytes()


def decode_vector(blob):
    """BLOB -> list[float]; tolerant of legacy/text/null input."""
    if blob is None:
        return None
    if isinstance(blob, str):
        try:
            parsed = json.loads(blob)
            return parsed if isinstance(parsed, list) else None
        except Exception:
            return None
    try:
        import array
        values = array.array("d")
        values.frombytes(bytes(blob))
        return [float(item) for item in values]
    except Exception:
        return None


def _atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def _atomic_copy(src, dst):
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
        return True
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def _legacy_json_files(memory_dir):
    """memory/*.json docs, excluding our own exports."""
    out = []
    try:
        for path in sorted(Path(memory_dir).glob("*" + JSON_SUFFIX)):
            name = path.name
            if name == EXPORT_NAME or name.endswith(EXPORT_SUFFIX):
                continue
            if not path.is_file():
                continue
            out.append(path)
    except Exception:
        return []
    return out


# ---------------------------------------------------------------- store
class MemoryStore:
    """SQLite memory store with legacy-JSON mirrors (degrade to JSON mode)."""

    def __init__(self, memory_dir, json_dir=None):
        self.memory_dir = Path(memory_dir)
        self.json_dir = Path(json_dir) if json_dir else self.memory_dir
        self.path = self.memory_dir / SQLITE_FILE
        self._conn = None
        self.recovered = False
        self.migration_report = {"scanned": 0, "backfilled": 0,
                                 "merged_pairs": 0, "deleted_rows": 0,
                                 "backup": "", "ran": False}
        self._open()

    # -- connection -----------------------------------------------------
    def _connect(self):
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=5.0,
                               check_same_thread=False)
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=5000")
            conn.executescript(_SCHEMA_SQL)
        except Exception:
            # Windows keeps the file locked until the handle is closed; close it
            # before the corrupt-recovery path tries to replace the file.
            try:
                conn.close()
            except Exception:
                pass
            raise
        return conn

    def _open(self):
        try:
            self._conn = self._connect()
        except sqlite3.DatabaseError:
            self.recovered = True
            self._recover_corrupt()
            self._conn = self._connect()
        try:
            self._migrate_dedupe()
        except Exception as exc:
            logger.warning("[biocore] memory dedupe migration failed: %s", exc)
        self._set_meta("schema_version", str(SCHEMA_VERSION))

    # -- dedupe schema / one-time migration ---------------------------
    def _column_names(self):
        try:
            return {str(row[1]) for row in self._conn.execute(
                "PRAGMA table_info(entries)").fetchall()}
        except Exception:
            return set()

    def _has_index(self, name):
        try:
            return self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
                (str(name),)).fetchone() is not None
        except Exception:
            return False

    def _migrate_dedupe(self):
        """Add text_hash + unique(session,text_hash), dedupe existing rows once.

        Backup runs before any merge when the table already has rows; the whole
        step is idempotent (a second open sees the unique index and returns).
        """
        if "text_hash" not in self._column_names():
            self._conn.execute("ALTER TABLE entries ADD COLUMN text_hash TEXT")
            self._conn.commit()
        if self._has_index(TEXT_HASH_INDEX):
            return
        try:
            count = int(self._conn.execute(
                "SELECT COUNT(*) FROM entries").fetchone()[0] or 0)
        except Exception:
            count = 0
        if count:
            backup = _backup_memory_dir(self.memory_dir, None,
                                        label="pre-memory-dedupe")
            self.migration_report["backup"] = backup.get("dir", "")
        report = self._dedupe_existing()
        self.migration_report.update(report)
        self.migration_report["ran"] = True
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS %s ON entries(session, text_hash)"
            % TEXT_HASH_INDEX)
        self._conn.commit()
        self._set_meta("dedupe_migrated", "1")
        logger.info(
            "[biocore] memory dedupe migrated: merged=%d deleted=%d "
            "backfilled=%d backup=%s",
            int(report.get("merged_pairs", 0)),
            int(report.get("deleted_rows", 0)),
            int(report.get("backfilled", 0)),
            bool(self.migration_report.get("backup")))

    @staticmethod
    def _merge_views(base_entry, incoming):
        """Merge one duplicate write/view into the earliest row (SillyTavern-ish)."""
        merged = dict(base_entry)
        base_ts = _num(base_entry.get("ts"), 0.0)
        new_ts = _num(incoming.get("ts"), 0.0)
        if base_ts <= 0:
            merged["ts"] = new_ts
        elif new_ts > 0:
            merged["ts"] = min(base_ts, new_ts)
        merged["importance"] = max(_num(base_entry.get("importance"), 0.5),
                                   _num(incoming.get("importance"), 0.5))
        merged["hits"] = int(_num(base_entry.get("hits"), 0)) + int(
            _num(incoming.get("hits"), 0))
        merged["access_count"] = int(
            _num(base_entry.get("access_count"), 1)) + int(
            _num(incoming.get("access_count"), 1))
        for key, value in incoming.items():
            if key not in merged or merged.get(key) in (None, "", [], {}):
                merged[key] = value
        return merged

    def _dedupe_existing(self):
        """One-time exact+semantic merge over existing rows (idempotent)."""
        report = {"scanned": 0, "backfilled": 0, "merged_pairs": 0,
                  "deleted_rows": 0, "semantic_merged": 0}
        try:
            sessions = [str(row[0]) for row in self._conn.execute(
                "SELECT DISTINCT session FROM entries").fetchall()]
        except Exception:
            return report
        delete_ids = []
        for session in sessions:
            try:
                rows = self._conn.execute(
                    "SELECT " + ", ".join(_ENTRY_COLUMNS) + " FROM entries "
                    "WHERE session=? ORDER BY ts ASC, rowid ASC",
                    (session,)).fetchall()
            except Exception:
                continue
            kept = []
            by_hash = {}
            for row in rows:
                report["scanned"] += 1
                entry = self._row_entity(row)
                eid = str(entry.get("id") or "")
                thash = str(entry.get("text_hash") or "") or text_hash(
                    entry.get("text"))
                if thash != str(entry.get("text_hash") or ""):
                    report["backfilled"] += 1
                entry["text_hash"] = thash
                vector = entry.get("vector")
                grams = bigrams(entry.get("text"))
                match = by_hash.get(thash)
                if match is None and vector:
                    best = 0.0
                    for candidate in kept:
                        candidate_vector = candidate.get("vector")
                        if not candidate_vector:
                            continue
                        if not prefilter_ok(grams, candidate.get("_grams")):
                            continue
                        score = cosine(vector, candidate_vector)
                        if score >= SEMANTIC_MERGE_THRESHOLD and score > best:
                            best = score
                            match = candidate
                    if match is not None:
                        report["semantic_merged"] += 1
                if match is not None:
                    merged = self._merge_views(match, entry)
                    match.clear()
                    match.update(merged)
                    delete_ids.append(eid)
                    report["merged_pairs"] += 1
                    report["deleted_rows"] += 1
                    continue
                entry["_grams"] = grams
                by_hash.setdefault(thash, entry)
                kept.append(entry)
            # write merged/backfilled rows back
            for entry in kept:
                try:
                    self._conn.execute(
                        "UPDATE entries SET ts=?, importance=?, hits=?, "
                        "access_count=?, text_hash=?, raw=? WHERE id=?",
                        (_num(entry.get("ts"), 0.0),
                         _num(entry.get("importance"), 0.5),
                         int(_num(entry.get("hits"), 0)),
                         int(_num(entry.get("access_count"), 1)),
                         str(entry.get("text_hash") or ""),
                         _json_dump({k: v for k, v in entry.items()
                                     if k not in ("vector", "_grams")}),
                         str(entry.get("id") or "")))
                except Exception:
                    continue
        if delete_ids:
            try:
                with self._conn:
                    self._conn.executemany(
                        "DELETE FROM entries WHERE id=?",
                        [(eid,) for eid in delete_ids])
            except Exception as exc:
                logger.warning("[biocore] memory dedupe delete failed: %s", exc)
        return report

    def _recover_corrupt(self):
        try:
            if self.path.is_file():
                shutil.copyfile(self.path,
                                self.path.with_name(self.path.name + ".corrupt.bak"))
        except Exception:
            pass
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(self.path) + suffix).unlink(missing_ok=True)
            except Exception:
                pass

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def checkpoint(self):
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return True
        except Exception:
            return False

    # -- meta -----------------------------------------------------------
    def _set_meta(self, key, value):
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO meta(key, value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(key), str(value)))
        except Exception:
            pass

    def get_meta(self, key, default=None):
        try:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key=?", (str(key),)).fetchone()
            return row[0] if row else default
        except Exception:
            return default

    def schema_version(self):
        try:
            return int(self.get_meta("schema_version", SCHEMA_VERSION))
        except Exception:
            return SCHEMA_VERSION

    # -- entry rows -----------------------------------------------------
    def _used_ids(self):
        try:
            return {str(row[0]) for row in self._conn.execute(
                "SELECT id FROM entries").fetchall()}
        except Exception:
            return set()

    def _row_values(self, entry, session, seq, eid):
        hidden = 1 if entry.get("hidden") else 0
        # The vector lives in its own BLOB column; keeping it inside raw JSON
        # would duplicate ~8KB per 1024-dim entry and slow every load/save.
        raw_entry = dict(entry)
        raw_entry.pop("vector", None)
        tags = entry.get("tags")
        tags_text = None
        if isinstance(tags, (list, tuple)):
            tags_text = _json_dump([str(x) for x in tags if str(x)])
        elif tags not in (None, ""):
            tags_text = _json_dump([str(tags)])
        return (
            str(eid), safe_session_name(session), int(seq),
            str(entry.get("text") or ""), str(entry.get("role") or ""),
            _num(entry.get("ts"), 0.0),
            _num(entry.get("importance"), 0.5),
            encode_vector(entry.get("vector")),
            _num(entry.get("storage_s"), 0.45),
            _num(entry.get("retrieval_s"), 0.5),
            int(_num(entry.get("access_count"), 1)),
            int(_num(entry.get("hits"), 0)),
            _num(entry.get("inhibition"), 0.0),
            int(_num(entry.get("suppression_count"), 0)),
            str(entry.get("memory_tier") or "warm"),
            str(entry.get("memory_source") or "direct"),
            (None if entry.get("memory_confidence") is None
             else _num(entry.get("memory_confidence"), 0.0)),
            _num(entry.get("arousal_at_encoding"), 0.4),
            hidden, tags_text,
            str(entry.get("text_hash") or "") or text_hash(
                entry.get("text") or ""),
            _json_dump(raw_entry),
        )

    def _row_entity(self, row):
        cols = _ENTRY_COLUMNS
        raw = dict(zip(cols, row))
        entry = _json_load(raw.get("raw"), None)
        if not isinstance(entry, dict):
            entry = {}
        entry["id"] = str(raw.get("id") or "")
        entry["text"] = str(raw.get("text") or entry.get("text") or "")
        role = raw.get("role")
        if role is not None:
            entry["role"] = str(role)
        entry["ts"] = _num(raw.get("ts"), entry.get("ts", 0.0))
        entry["importance"] = _num(raw.get("importance"),
                                   entry.get("importance", 0.5))
        vector = decode_vector(raw.get("vector"))
        if vector is not None:
            entry["vector"] = vector
        for key in ("storage_s", "retrieval_s", "access_count", "hits",
                    "inhibition", "suppression_count", "memory_confidence",
                    "arousal_at_encoding"):
            value = raw.get(key)
            if value is not None:
                try:
                    entry[key] = float(value)
                except Exception:
                    pass
        entry["memory_tier"] = str(raw.get("memory_tier") or "warm")
        entry["memory_source"] = str(raw.get("memory_source") or "direct")
        entry["hidden"] = bool(raw.get("hidden"))
        # Keep the stored value: the dedupe migration counts/backfills blanks
        # itself, and fabricated hashes would hide the backfill count.
        entry["text_hash"] = str(raw.get("text_hash") or "")
        tags = _json_load(raw.get("tags"), None)
        if isinstance(tags, list) and tags:
            entry["tags"] = [str(x) for x in tags]
        elif "tags" in entry and not tags:
            entry.pop("tags", None)
        return entry

    def replace_session(self, session, doc):
        """Replace one session's rows + extras in a single transaction."""
        return self._write_session(session, doc, replace=True)

    def _semantic_candidates(self, session, limit=SEMANTIC_SCAN_LIMIT):
        """Latest N rows of the session (for the semantic dedupe pass)."""
        try:
            rows = self._conn.execute(
                "SELECT " + ", ".join(_ENTRY_COLUMNS) + " FROM entries "
                "WHERE session=? ORDER BY ts DESC LIMIT ?",
                (session, max(1, int(limit)))).fetchall()
        except Exception:
            return []
        return [self._row_entity(row) for row in rows]

    def _write_session(self, session, doc, replace=False):
        """Write one session's entries with exact + semantic dedupe.

        Duplicate writes merge into the existing row instead of inserting:
        earliest ts, higher importance, summed hits/access_count. A re-save of
        the same row id is authoritative (max counters, no inflation).
        """
        session = safe_session_name(session)
        doc = doc if isinstance(doc, dict) else {}
        entries = doc.get("entries") if isinstance(doc.get("entries"), list) else []
        extras = {key: value for key, value in doc.items() if key != "entries"}
        used = self._used_ids()
        db_by_id = {}
        db_by_hash = {}
        if not replace:
            try:
                rows = self._conn.execute(
                    "SELECT " + ", ".join(_ENTRY_COLUMNS) + " FROM entries "
                    "WHERE session=?", (session,)).fetchall()
            except Exception:
                rows = []
            for row in rows:
                entry = self._row_entity(row)
                entry_id = str(entry.get("id") or "")
                if not entry_id:
                    continue
                db_by_id[entry_id] = entry
                db_by_hash.setdefault(entry.get("text_hash") or text_hash(
                    entry.get("text")), entry)
        semantic = self._semantic_candidates(session) if not replace else []
        final = []
        final_ids = set()
        final_by_id = {}
        doc_hash = {}
        near = []
        merged_count = 0
        semantic_merged = 0
        for raw_entry in entries:
            if not isinstance(raw_entry, dict):
                continue
            entry = dict(raw_entry)
            thash = text_hash(entry.get("text"))
            match = None
            matched_by = ""
            if thash in doc_hash:
                match = doc_hash[thash]
                matched_by = "doc"
            elif thash in db_by_hash and str(
                    db_by_hash[thash].get("id") or "") not in final_ids:
                match = db_by_hash[thash]
                matched_by = "db"
            elif entry.get("vector"):
                grams = bigrams(entry.get("text"))
                best = 0.0
                best_row = None
                for candidate in semantic:
                    candidate_id = str(candidate.get("id") or "")
                    # an entry already appended in this save is the same row:
                    # compare against its merged view instead of skipping it.
                    candidate = final_by_id.get(candidate_id, candidate)
                    if not prefilter_ok(grams, bigrams(candidate.get("text"))):
                        continue
                    score = cosine(entry.get("vector"),
                                   candidate.get("vector"))
                    if score >= SEMANTIC_MERGE_THRESHOLD and score > best:
                        best = score
                        best_row = candidate
                if best_row is not None:
                    match = best_row
                    matched_by = "semantic"
                    semantic_merged += 1
                else:
                    near_score = 0.0
                    for candidate in semantic:
                        candidate = final_by_id.get(
                            str(candidate.get("id") or ""), candidate)
                        if not prefilter_ok(grams, bigrams(candidate.get("text"))):
                            continue
                        score = cosine(entry.get("vector"),
                                       candidate.get("vector"))
                        if SEMANTIC_LOG_THRESHOLD <= score < SEMANTIC_MERGE_THRESHOLD:
                            near_score = max(near_score, score)
                    if near_score:
                        near.append({"cosine": round(near_score, 4),
                                     "text": str(entry.get("text"))[:40],
                                     "kind": "near_merge"})
            if match is not None:
                same_id = (matched_by == "db" and entry.get("id")
                           and str(entry.get("id")) == str(match.get("id")))
                if matched_by == "doc":
                    merged = self._merge_views(match, entry)
                    match.clear()
                    match.update(merged)
                    merged_count += 1
                    continue
                if same_id:
                    merged = dict(match)
                    merged["ts"] = min(
                        _num(match.get("ts"), 0.0) or _num(entry.get("ts")),
                        _num(entry.get("ts"), 0.0) or _num(match.get("ts")))
                    merged["importance"] = max(
                        _num(match.get("importance"), 0.5),
                        _num(entry.get("importance"), 0.5))
                    merged["hits"] = max(int(_num(match.get("hits"))),
                                         int(_num(entry.get("hits"))))
                    merged["access_count"] = max(
                        int(_num(match.get("access_count"), 1)),
                        int(_num(entry.get("access_count"), 1)))
                else:
                    merged = self._merge_views(match, entry)
                    merged["id"] = str(match.get("id"))
                    merged["text_hash"] = (match.get("text_hash")
                                           or text_hash(match.get("text")))
                    merged_count += 1
                merged["text_hash"] = merged.get("text_hash") or thash
                if matched_by == "semantic" and str(
                        merged.get("id")) in final_ids:
                    target = final_by_id.get(str(merged.get("id")))
                    if target is not None:
                        target.clear()
                        target.update(merged)
                        doc_hash[merged["text_hash"]] = target
                        continue
                final.append(merged)
                final_ids.add(str(merged.get("id")))
                final_by_id[str(merged.get("id"))] = merged
                doc_hash[merged["text_hash"]] = merged
                continue
            new_entry = dict(entry)
            new_entry["id"] = entry_key(entry, session, used)
            new_entry["text_hash"] = thash
            final.append(new_entry)
            final_ids.add(new_entry["id"])
            final_by_id[new_entry["id"]] = new_entry
            doc_hash[thash] = new_entry
        sql = ("INSERT OR REPLACE INTO entries(" + ", ".join(_ENTRY_COLUMNS)
               + ") VALUES(" + ",".join("?" for _ in _ENTRY_COLUMNS) + ")")
        rows = [self._row_values(entry, session, seq, entry["id"])
                for seq, entry in enumerate(final)]
        with self._conn:
            if replace:
                self._conn.execute("DELETE FROM entries WHERE session=?",
                                   (session,))
            if rows:
                self._conn.executemany(sql, rows)
            if not replace and db_by_id:
                stale = [eid for eid in db_by_id if eid not in final_ids]
                if stale:
                    self._conn.executemany(
                        "DELETE FROM entries WHERE id=?",
                        [(eid,) for eid in stale])
            self._conn.execute(
                "INSERT INTO session_docs(session, doc, updated_at) "
                "VALUES(?,?,?) ON CONFLICT(session) DO UPDATE SET "
                "doc=excluded.doc, updated_at=excluded.updated_at",
                (session, _json_dump(extras), time.time()))
        doc["entries"] = final
        for item in near[:5]:
            logger.info(
                "[biocore] memory near-merge session=%s cosine=%.3f text=%s",
                session, float(item.get("cosine", 0.0)),
                str(item.get("text") or ""))
        return {"session": session, "entries": len(final),
                "merged": merged_count, "semantic_merged": semantic_merged,
                "near_merge": len(near)}

    def load_doc(self, session):
        """Doc for one session: entries (raw + vector BLOB) + stored extras."""
        session = safe_session_name(session)
        extras = {}
        try:
            row = self._conn.execute(
                "SELECT doc FROM session_docs WHERE session=?",
                (session,)).fetchone()
            if row:
                parsed = _json_load(row[0], None)
                if isinstance(parsed, dict):
                    extras = parsed
        except Exception:
            extras = {}
        try:
            rows = self._conn.execute(
                "SELECT " + ", ".join(_ENTRY_COLUMNS) + " FROM entries "
                "WHERE session=? ORDER BY seq ASC, ts ASC", (session,)).fetchall()
        except Exception:
            rows = []
        doc = dict(extras)
        doc["entries"] = [self._row_entity(row) for row in rows]
        return doc

    def get_entry(self, session, eid):
        try:
            row = self._conn.execute(
                "SELECT " + ", ".join(_ENTRY_COLUMNS) + " FROM entries "
                "WHERE session=? AND id=?",
                (safe_session_name(session), str(eid))).fetchone()
            return self._row_entity(row) if row else None
        except Exception:
            return None

    def delete_entry(self, session, eid):
        try:
            with self._conn:
                self._conn.execute(
                    "DELETE FROM entries WHERE session=? AND id=?",
                    (safe_session_name(session), str(eid)))
            return True
        except Exception:
            return False

    def list_sessions(self):
        try:
            rows = self._conn.execute(
                "SELECT session, updated_at FROM session_docs "
                "ORDER BY updated_at DESC").fetchall()
        except Exception:
            rows = []
        return [(str(row[0]), float(row[1] or 0.0)) for row in rows]

    def all_docs(self):
        out = []
        for session, updated_at in self.list_sessions():
            out.append((session, updated_at, self.load_doc(session)))
        return out

    def stats(self):
        try:
            entries = int(self._conn.execute(
                "SELECT COUNT(*) FROM entries").fetchone()[0] or 0)
            sessions = int(self._conn.execute(
                "SELECT COUNT(*) FROM session_docs").fetchone()[0] or 0)
        except Exception:
            entries, sessions = 0, 0
        return {"sessions": sessions, "entries": entries,
                "schema_version": self.schema_version()}

    def compact_raw(self):
        """Drop duplicated vector data from legacy raw JSON (idempotent).

        Rows written before the raw/-BLOB split still carry the full 1024-dim
        vector inside raw, which doubles storage and load cost. Rewriting them
        once keeps load/save fast without touching the vector BLOB column.
        """
        try:
            rows = self._conn.execute(
                "SELECT id, raw FROM entries WHERE raw LIKE ?",
                ('%"vector"%',)).fetchall()
        except Exception:
            return 0
        updated = 0
        try:
            with self._conn:
                for eid, raw in rows:
                    entry = _json_load(raw, None)
                    if not isinstance(entry, dict):
                        continue
                    entry.pop("vector", None)
                    self._conn.execute(
                        "UPDATE entries SET raw=? WHERE id=?",
                        (_json_dump(entry), eid))
                    updated += 1
        except Exception:
            return 0
        return updated

    # -- legacy JSON mirror --------------------------------------------
    def _mirror_path(self, session):
        return self.json_dir / (safe_session_name(session) + JSON_SUFFIX)

    def write_json_mirror(self, session, doc):
        """Dual-write: every store write also refreshes the legacy JSON file."""
        try:
            payload = dict(doc) if isinstance(doc, dict) else {"entries": []}
            payload.setdefault("schema_version", SCHEMA_VERSION)
            text = json.dumps(payload, ensure_ascii=False)
        except Exception:
            return False
        return _atomic_write(self._mirror_path(session), text)

    def mirror_all(self):
        count = 0
        for session, _updated_at, doc in self.all_docs():
            if self.write_json_mirror(session, doc):
                count += 1
        return count

    def save_doc(self, session, doc):
        """Write one session to SQLite (dedupe merge) + refresh JSON mirror."""
        session = safe_session_name(session)
        result = self._write_session(session, doc, replace=False)
        result["json_mirror"] = self.write_json_mirror(session, doc)
        return result

    def drop_session(self, session):
        session = safe_session_name(session)
        try:
            with self._conn:
                self._conn.execute("DELETE FROM entries WHERE session=?",
                                   (session,))
                self._conn.execute("DELETE FROM session_docs WHERE session=?",
                                   (session,))
            try:
                self._mirror_path(session).unlink(missing_ok=True)
            except Exception:
                pass
            return True
        except Exception:
            return False

    # -- legacy import / merge -----------------------------------------
    def import_legacy_docs(self, memory_dir=None):
        """Import memory/*.json docs; returns a bounded report."""
        source = Path(memory_dir or self.json_dir)
        report = {"files": 0, "imported_entries": 0, "skipped": [],
                  "sessions": []}
        for path in _legacy_json_files(source):
            session = safe_session_name(path.stem)
            try:
                raw = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception:
                report["skipped"].append(path.name)
                continue
            if not isinstance(raw, dict):
                report["skipped"].append(path.name)
                continue
            report["files"] += 1
            result = self.replace_session(session, raw)
            report["imported_entries"] += int(result.get("entries", 0))
            report["sessions"].append(session)
            try:
                self.write_json_mirror(session, raw)
            except Exception:
                pass
        return report

    def merge_legacy_docs(self, memory_dir=None):
        """DB + legacy JSON: newer JSON wins, otherwise keep DB (no duplicates)."""
        source = Path(memory_dir or self.json_dir)
        report = {"files": 0, "merged": [], "imported_entries": 0,
                  "skipped": []}
        db_updated = {session: updated for session, updated in self.list_sessions()}
        for path in _legacy_json_files(source):
            session = safe_session_name(path.stem)
            try:
                raw = json.loads(path.read_text(encoding="utf-8-sig"))
                mtime = path.stat().st_mtime
            except Exception:
                report["skipped"].append(path.name)
                continue
            if not isinstance(raw, dict):
                report["skipped"].append(path.name)
                continue
            report["files"] += 1
            db_ts = float(db_updated.get(session, 0.0) or 0.0)
            if session not in db_updated:
                result = self.replace_session(session, raw)
                report["merged"].append(session)
                report["imported_entries"] += int(result.get("entries", 0))
            elif mtime > db_ts + 1e-6:
                # downgrade period: the JSON mirror is newer than our last write
                result = self.replace_session(session, raw)
                report["merged"].append(session)
                report["imported_entries"] += int(result.get("entries", 0))
            # DB newer/equal: DB is authoritative, JSON is the stale mirror.
        return report

    # -- JSON export / import -----------------------------------------
    def export_json(self, path=None):
        # memory/ is scanned with glob("*.json") by legacy code; the export
        # must live outside that flat namespace (a subdir is not matched).
        target = (Path(path) if path
                  else self.memory_dir / "exports" / EXPORT_NAME)
        payload = {"schema_version": SCHEMA_VERSION,
                   "exported_at": time.time(), "sessions": {}}
        for session, _updated_at, doc in self.all_docs():
            payload["sessions"][session] = doc
        _atomic_write(target, json.dumps(payload, ensure_ascii=False))
        return target

    def import_json(self, path, replace=True):
        """Import a full export ({sessions:{...}} or a single doc)."""
        data = _json_load(Path(path).read_text(encoding="utf-8-sig"), None)
        report = {"sessions": 0, "entries": 0}
        if isinstance(data, dict) and isinstance(data.get("sessions"), dict):
            sessions = data["sessions"]
        elif isinstance(data, dict) and isinstance(data.get("entries"), list):
            sessions = {"import": data}
        else:
            return report
        for session, doc in sessions.items():
            if not isinstance(doc, dict):
                continue
            result = self.replace_session(safe_session_name(session), doc)
            self.write_json_mirror(safe_session_name(session), doc)
            report["sessions"] += 1
            report["entries"] += int(result.get("entries", 0))
        return report


# ---------------------------------------------------------------- module API
def open_store(memory_dir, json_dir=None):
    return MemoryStore(memory_dir, json_dir=json_dir)


def _backup_memory_dir(memory_dir, backup_root, label="pre-migration"):
    """Whole memory/ dir backup before the first import (task-146 rule 3)."""
    memory_dir = Path(memory_dir)
    root = Path(backup_root) if backup_root else memory_dir.parent / "backups"
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    target = root / (str(label) + "-" + stamp) / "memory"
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    try:
        # checkpoint first so the DB copy is self-contained
        if (memory_dir / SQLITE_FILE).is_file():
            try:
                # sqlite3.Connection.__exit__ only commits; Windows keeps the
                # file locked until close(), so closing() is required here.
                with contextlib.closing(
                        sqlite3.connect(str(memory_dir / SQLITE_FILE),
                                        timeout=5.0)) as conn:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
        for path in sorted(memory_dir.iterdir()):
            if not path.is_file():
                continue
            if path.name.endswith(".corrupt.bak"):
                continue
            if _atomic_copy(path, target / path.name):
                copied += 1
    except Exception:
        pass
    return {"dir": str(target) if copied else "", "files": copied}


def ensure_store(memory_dir, backup_root=None, label="pre-migration"):
    """Open/create the DB, import or merge legacy JSON, mirror JSON back.

    Never raises: returns {"ok": bool, "state": str, ...}. When ok is False the
    caller must keep working on JSON files (old behaviour).
    """
    memory_dir = Path(memory_dir)
    report = {"ok": False, "state": "failed", "db": str(memory_dir / SQLITE_FILE),
              "sessions": 0, "entries": 0, "imported_entries": 0,
              "backup": {"dir": "", "files": 0}, "recovered": False,
              "schema_version": SCHEMA_VERSION, "error": "", "skipped": []}
    try:
        memory_dir.mkdir(parents=True, exist_ok=True)
        store = MemoryStore(memory_dir, json_dir=memory_dir)
    except Exception as exc:
        report["error"] = "%s: %s" % (type(exc).__name__, exc)
        return report
    try:
        report["recovered"] = bool(store.recovered)
        report["compacted"] = int(store.compact_raw())
        migration = dict(getattr(store, "migration_report", {}) or {})
        report["migration"] = migration
        if migration.get("ran"):
            report["dedupe_backup"] = str(migration.get("backup") or "")
            # reflect the merged rows into the JSON mirrors (downgrade-safe)
            for session, _updated_at, doc in store.all_docs():
                store.write_json_mirror(session, doc)
        stats = store.stats()
        legacy = _legacy_json_files(memory_dir)
        # Rule 4: when both sides exist the configured backend wins; no
        # implicit merge. Only an empty DB imports the JSON docs (rule 1).
        need_import = stats["entries"] == 0 and bool(legacy)
        if need_import:
            report["backup"] = _backup_memory_dir(memory_dir, backup_root,
                                                  label=label)
            imported = store.import_legacy_docs(memory_dir)
            report["state"] = "imported"
            report["imported_entries"] = int(imported.get("imported_entries", 0))
            report["skipped"] = list(imported.get("skipped") or [])
            for session, _updated_at, doc in store.all_docs():
                store.write_json_mirror(session, doc)
        else:
            report["state"] = ("recovered" if store.recovered else "ok")
            report["both_present"] = bool(legacy) and stats["entries"] > 0
            # ensure every DB session has a JSON mirror (downgrade safety)
            for session, _updated_at, doc in store.all_docs():
                mirror = store._mirror_path(session)
                if not mirror.is_file():
                    store.write_json_mirror(session, doc)
        final = store.stats()
        report.update({"ok": True, "sessions": final["sessions"],
                       "entries": final["entries"],
                       "schema_version": store.schema_version()})
        store._set_meta("migrated_at", str(round(time.time(), 3)))
        store._set_meta("schema_version", str(SCHEMA_VERSION))
        return report
    except Exception as exc:
        report["error"] = "%s: %s" % (type(exc).__name__, exc)
        report["state"] = "failed"
        return report
    finally:
        try:
            store.close()
        except Exception:
            pass


# ---------------------------------------------------------------- backend switch
BACKENDS = ("json", "sqlite", "auto")
BACKEND_LABELS = {"json": "JSON 文件", "sqlite": "SQLite 数据库",
                  "auto": "自动"}


def normalize_backend(value, default="auto"):
    """json | sqlite | auto; unknown/empty -> default (never raises)."""
    text = str(value or "").strip().lower()
    return text if text in BACKENDS else default


def db_present_healthy(memory_dir):
    """True only when memory.sqlite3 exists and passes a cheap integrity check."""
    path = Path(memory_dir) / SQLITE_FILE
    if not path.is_file():
        return False
    conn = None
    try:
        conn = sqlite3.connect(str(path), timeout=2.0)
        row = conn.execute("PRAGMA quick_check").fetchone()
        if not row or str(row[0]).strip().lower() != "ok":
            return False
        tables = {str(item[0]) for item in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        return "entries" in tables
    except Exception:
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def json_counts(memory_dir):
    """Bounded count of legacy JSON docs/entries (never raises)."""
    sessions = 0
    entries = 0
    for path in _legacy_json_files(memory_dir):
        sessions += 1
        doc = _json_load(path.read_text(encoding="utf-8-sig"), None)
        if isinstance(doc, dict) and isinstance(doc.get("entries"), list):
            entries += len([e for e in doc["entries"] if isinstance(e, dict)])
    return {"sessions": sessions, "entries": entries}


def db_counts(memory_dir):
    """Entry/session counts of an existing healthy DB (empty when absent)."""
    if not db_present_healthy(memory_dir):
        return {"sessions": 0, "entries": 0}
    store = None
    try:
        store = MemoryStore(memory_dir, json_dir=memory_dir)
        return store.stats()
    except Exception:
        return {"sessions": 0, "entries": 0}
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass


def resolve_backend(setting, memory_dir):
    """Effective backend: explicit wins; auto = healthy DB -> sqlite else json."""
    norm = normalize_backend(setting)
    if norm == "json":
        return "json"
    if norm == "sqlite":
        return "sqlite"
    return "sqlite" if db_present_healthy(memory_dir) else "json"


def switch_backend(target, memory_dir, backup_root=None, json_dir=None):
    """Explicit backend switch with backup + idempotent migration.

    json -> sqlite : import legacy JSON docs into the DB (per-session replace).
    sqlite -> json : export every DB session to its legacy JSON mirror.
    Both directions are safe to repeat and never raise; when ok is False the
    caller must keep the previous backend (JSON stays usable).
    """
    memory_dir = Path(memory_dir)
    json_dir = Path(json_dir) if json_dir else memory_dir
    norm = normalize_backend(target)
    report = {"ok": False, "target": norm, "from": "", "to": "",
              "state": "", "counts_before": {}, "counts_after": {},
              "backup": {"dir": "", "files": 0}, "error": ""}
    store = None
    try:
        from_backend = ("sqlite" if db_present_healthy(memory_dir) else "json")
        report["from"] = from_backend
        report["counts_before"] = (db_counts(memory_dir) if from_backend == "sqlite"
                                   else json_counts(json_dir))
        if norm == "auto":
            norm = resolve_backend("auto", memory_dir)
            report["target"] = norm
        if norm not in ("json", "sqlite"):
            report["error"] = "unknown backend"
            return report
        if norm == from_backend:
            report.update({"ok": True, "to": from_backend, "state": "noop",
                           "counts_after": report["counts_before"]})
            return report
        report["backup"] = _backup_memory_dir(
            memory_dir, backup_root, label="pre-backend-switch")
        if norm == "sqlite":
            store = MemoryStore(memory_dir, json_dir=json_dir)
            imported = store.import_legacy_docs(json_dir)
            for session, _updated_at, doc in store.all_docs():
                store.write_json_mirror(session, doc)
            stats = store.stats()
            report.update({"ok": True, "to": "sqlite", "state": "imported",
                           "counts_after": stats,
                           "imported_entries": int(
                               imported.get("imported_entries", 0)),
                           "skipped": list(imported.get("skipped") or [])})
        else:
            store = MemoryStore(memory_dir, json_dir=json_dir)
            mirrored = store.mirror_all()
            stats = store.stats()
            after = json_counts(json_dir)
            report.update({"ok": True, "to": "json", "state": "exported",
                           "counts_after": after, "mirrored_sessions": mirrored,
                           "db_entries": stats["entries"]})
        return report
    except Exception as exc:
        report["error"] = "%s: %s" % (type(exc).__name__, exc)
        report["ok"] = False
        return report
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass


def ensure_backend(setting, memory_dir, backup_root=None, json_dir=None):
    """Startup resolution: never raises; returns the backend actually usable."""
    memory_dir = Path(memory_dir)
    json_dir = Path(json_dir) if json_dir else memory_dir
    setting = normalize_backend(setting)
    resolved = resolve_backend(setting, memory_dir)
    report = {"setting": setting, "backend": resolved, "resolved": resolved,
              "ok": True, "store_report": {}, "entries": 0, "sessions": 0,
              "fallback": False, "error": ""}
    try:
        if resolved == "sqlite":
            ensure = ensure_store(memory_dir, backup_root=backup_root,
                                  label="pre-memory-v4")
            report["store_report"] = ensure
            if not ensure.get("ok"):
                # startup must not fail: stay on JSON mode
                report.update({"backend": "json", "fallback": True,
                               "ok": True,
                               "error": ensure.get("error", "")})
                resolved = "json"
            else:
                report["entries"] = int(ensure.get("entries", 0))
                report["sessions"] = int(ensure.get("sessions", 0))
        if resolved == "json":
            counts = json_counts(json_dir)
            report["entries"] = counts["entries"]
            report["sessions"] = counts["sessions"]
        return report
    except Exception as exc:
        report.update({"backend": "json", "fallback": True,
                       "error": "%s: %s" % (type(exc).__name__, exc)})
        try:
            counts = json_counts(json_dir)
            report["entries"] = counts["entries"]
            report["sessions"] = counts["sessions"]
        except Exception:
            pass
        return report


def restore(backup_memory_dir, memory_dir, json_dir=None):
    """Restore SQLite from a JSON backup dir (task-146 rule 6).

    Copies the backed-up JSON docs into memory/ and rebuilds the DB from them;
    if the backup also has a memory.sqlite3 it is used as a starting point.
    Never raises: returns {"ok": bool, ...}.
    """
    backup = Path(backup_memory_dir)
    memory_dir = Path(memory_dir)
    json_dir = Path(json_dir) if json_dir else memory_dir
    report = {"ok": False, "restored_files": 0, "entries": 0, "error": ""}
    if not backup.is_dir():
        report["error"] = "backup dir missing"
        return report
    try:
        memory_dir.mkdir(parents=True, exist_ok=True)
        json_dir.mkdir(parents=True, exist_ok=True)
        restored = 0
        for path in sorted(backup.glob("*" + JSON_SUFFIX)):
            if path.name.endswith(EXPORT_SUFFIX):
                continue
            if _atomic_copy(path, json_dir / path.name):
                restored += 1
        db_backup = backup / SQLITE_FILE
        if db_backup.is_file():
            # preferred: the backed-up DB itself
            try:
                with contextlib.closing(
                        sqlite3.connect(str(memory_dir / SQLITE_FILE),
                                        timeout=5.0)) as conn:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            _atomic_copy(db_backup, memory_dir / SQLITE_FILE)
            for suffix in ("-wal", "-shm"):
                try:
                    Path(str(memory_dir / SQLITE_FILE) + suffix).unlink(
                        missing_ok=True)
                except Exception:
                    pass
        store = MemoryStore(memory_dir, json_dir=json_dir)
        try:
            if not db_backup.is_file():
                store.replace_session("__restore__", {"entries": []})
                with store._conn:
                    store._conn.execute("DELETE FROM entries")
                    store._conn.execute("DELETE FROM session_docs")
                imported = store.import_legacy_docs(json_dir)
                report["entries"] = int(imported.get("imported_entries", 0))
            else:
                report["entries"] = store.stats()["entries"]
            for session, _updated_at, doc in store.all_docs():
                store.write_json_mirror(session, doc)
        finally:
            store.close()
        report.update({"ok": True, "restored_files": restored})
        return report
    except Exception as exc:
        report["error"] = "%s: %s" % (type(exc).__name__, exc)
        return report
