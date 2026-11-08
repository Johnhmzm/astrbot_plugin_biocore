# -*- coding: utf-8 -*-
"""SQLite store: the structured half of a session (entries, events, claims, journal).

JSON stays the export/compat format; this module is the working store. Opening a
store that only has JSON imports it once, so old installs keep working.
"""
from __future__ import annotations

import json
import os
import sqlite3
import struct
import time
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS entries (
  id TEXT PRIMARY KEY, turn INTEGER, ts REAL, role TEXT, text TEXT,
  vector BLOB, hits INTEGER DEFAULT 1, importance REAL DEFAULT 0.2,
  deleted INTEGER DEFAULT 0, raw TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, start INTEGER, end INTEGER, overview TEXT,
  text TEXT, closed_ts REAL, payload TEXT, centroid BLOB
);
CREATE TABLE IF NOT EXISTS claims (
  id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT, subject TEXT, attr TEXT,
  value TEXT, canon TEXT, status TEXT, source TEXT, confidence REAL,
  entity TEXT, thread TEXT, turn INTEGER, event_id TEXT
);
CREATE TABLE IF NOT EXISTS event_state (
  session TEXT PRIMARY KEY, seen INTEGER, global_state TEXT, open_buf TEXT, updated REAL
);
CREATE TABLE IF NOT EXISTS journal (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, payload TEXT
);
CREATE TABLE IF NOT EXISTS meta (
  k TEXT PRIMARY KEY, v TEXT
);
CREATE INDEX IF NOT EXISTS idx_claims_key ON claims(key);
CREATE INDEX IF NOT EXISTS idx_claims_thread ON claims(thread);
CREATE INDEX IF NOT EXISTS idx_journal_kind ON journal(kind);
CREATE INDEX IF NOT EXISTS idx_entries_turn ON entries(turn);
'''


def pack_vector(vec):
    if not vec:
        return None
    try:
        return struct.pack('<%df' % len(vec), *[float(x) for x in vec])
    except Exception:
        return None


def unpack_vector(blob):
    if not blob:
        return []
    try:
        return list(struct.unpack('<%df' % (len(blob) // 4), blob))
    except Exception:
        return []


def db_path(root, session_id):
    return Path(root) / 'sessions' / str(session_id) / 'memory.db'


def connect(root, session_id):
    """A fresh connection per call; the caller owns it and closes it.

    Pooling was tried and removed: a held handle makes the temporary store
    directory undeletable on Windows (WinError 32), which breaks every test that
    cleans up a store. The per-turn memos key on PRAGMA data_version, so they do
    not need a long-lived connection to stay coherent.
    """
    path = db_path(root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:
        return default


def import_session(root, session_id, force=False, events_path=None):
    """Load sessions/<sid>/memory.json, events/<sid>.json, journal/<sid>.jsonl.

    events_path lets the caller keep its own event-file rule: the pipeline puts
    events under <dataDir>/events even when the store root is <dataDir>/memory.
    """
    root = Path(root)
    conn = connect(root, session_id)
    done = conn.execute('SELECT COUNT(*) FROM entries').fetchone()[0]
    if done and not force:
        return conn, {'imported': False, 'entries': done}
    memory = _read_json(root / 'sessions' / session_id / 'memory.json', {})
    rows = memory.get('entries') if isinstance(memory, dict) else memory
    count = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        conn.execute(
            'INSERT OR REPLACE INTO entries (id,turn,ts,role,text,vector,hits,importance,deleted,raw)'
            ' VALUES (?,?,?,?,?,?,?,?,?,?)',
            (str(row.get('id') or ''), int(row.get('turn') or 0), float(row.get('ts') or 0.0),
             str(row.get('role') or 'user'), str(row.get('text') or ''),
             pack_vector(row.get('vector')), int(row.get('hits') or 1),
             float(row.get('importance') or 0.2), 1 if row.get('deleted') else 0,
             json.dumps(row, ensure_ascii=False)))
        count += 1
    event_file = Path(events_path) if events_path is not None \
        else root / 'events' / (session_id + '.json')
    events = _read_json(event_file, {})
    for ev in (events.get('events') if isinstance(events, dict) else events) or []:
        if not isinstance(ev, dict):
            continue
        eid = str(ev.get('event_id') or '')
        conn.execute(
            'INSERT OR REPLACE INTO events (id,start,end,overview,text,closed_ts,payload)'
            ' VALUES (?,?,?,?,?,?,?)',
            (eid, int(ev.get('start') or 0), int(ev.get('end') or 0),
             str(ev.get('overview') or ''), str(ev.get('text') or ''),
             float(ev.get('closed_ts') or 0.0), json.dumps(ev, ensure_ascii=False)))
        for claim in ev.get('claims') or []:
            if not isinstance(claim, dict):
                continue
            subject = str(claim.get('subject') or '')
            attr = str(claim.get('attr') or '')
            conn.execute(
                'INSERT INTO claims (key,subject,attr,value,canon,status,source,confidence,entity,thread,turn,event_id)'
                ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                ('%s·%s' % (subject, attr), subject, attr, str(claim.get('value') or ''),
                 str(claim.get('canon') or claim.get('value') or ''), str(claim.get('status') or 'current'),
                 str(claim.get('source') or 'unknown'), float(claim.get('confidence') or 0.0),
                 str(claim.get('entity') or ''), str(claim.get('thread') or ''),
                 int(claim.get('turn') or 0), eid))
    try:   # the event rows are the only place these vectors existed
        harvested = harvest_event_vectors(
            (events.get('events') if isinstance(events, dict) else events) or [])
        for entry_id, vector in harvested.items():
            blob = pack_vector(vector)
            if blob:
                conn.execute('UPDATE entries SET vector=? WHERE id=? AND vector IS NULL',
                             (blob, entry_id))
    except Exception:
        pass
    journal = root / 'journal' / (session_id + '.jsonl')
    if journal.exists():
        for line in journal.read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            conn.execute('INSERT INTO journal (ts,kind,payload) VALUES (?,?,?)',
                         (float(row.get('ts') or 0.0), str(row.get('kind') or ''),
                          json.dumps(row, ensure_ascii=False)))
    conn.commit()
    return conn, {'imported': True, 'entries': count}


def export_session(conn, root, session_id):
    """Write the JSON files back so old readers keep working."""
    root = Path(root)
    rows = conn.execute('SELECT raw FROM entries ORDER BY turn').fetchall()
    entries = []
    for (raw,) in rows:
        try:
            entries.append(json.loads(raw))
        except Exception:
            continue
    path = root / 'sessions' / session_id / 'memory.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'entries': entries}, ensure_ascii=False), encoding='utf-8')
    return len(entries)


def harvest_event_vectors(events, open_buf=None):
    """Per-entry vectors carried by event rows: {entry_id: [floats]}.

    In the event-layer mode the only copy of a row's vector lives in the event
    that quotes it, so migrating to sqlite has to lift them into entries.vector
    or the two-stage recall loses its coordinates.
    """
    out = {}
    rows = list(events or []) + list(open_buf or [])
    for ev in rows:
        if not isinstance(ev, dict):
            continue
        for item in ev.get("entries") or []:
            if not isinstance(item, dict):
                continue
            entry_id = str(item.get("id") or "")
            vector = item.get("vector")
            if entry_id and isinstance(vector, (list, tuple)) and vector:
                out[entry_id] = list(vector)
    return out


def update_entry_vectors(root, session_id, vectors):
    """Write per-entry vectors into entries.vector (BLOB); unknown ids are skipped."""
    if not vectors:
        return 0
    root = Path(root)
    conn = connect(root, session_id)
    try:
        written = 0
        for entry_id, vector in vectors.items():
            blob = pack_vector(vector)
            if not blob:
                continue
            cur = conn.execute('UPDATE entries SET vector=? WHERE id=? AND vector IS NULL',
                               (blob, str(entry_id)))
            written += cur.rowcount or 0
        conn.commit()
        return written
    finally:
        conn.close()


def read_entry_vectors(root, session_id):
    """{entry_id: vector} for every row that has one (the recall coordinates)."""
    root = Path(root)
    conn = connect(root, session_id)
    try:
        out = {}
        for entry_id, blob in conn.execute(
                'SELECT id, vector FROM entries WHERE vector IS NOT NULL').fetchall():
            vector = unpack_vector(blob)
            if vector:
                out[str(entry_id)] = vector
        return out
    finally:
        conn.close()


def read_doc(root, session_id):
    """The session document as the JSON file used to hold it.

    Insert order is rowid order, which is exactly the order the old file kept,
    so an export round-trips byte for byte.
    """
    root = Path(root)
    conn = connect(root, session_id)
    try:
        meta = {}
        try:
            for key, value in conn.execute('SELECT k, v FROM meta').fetchall():
                meta[str(key)] = value
        except Exception:
            meta = {}
        entries = []
        for (raw,) in conn.execute('SELECT raw FROM entries ORDER BY rowid').fetchall():
            if not raw:
                continue
            try:
                entries.append(json.loads(raw))
            except Exception:
                continue
        try:
            schema_version = int(meta.get('schema_version') or 1)
        except Exception:
            schema_version = 1
        return {'schema_version': schema_version,
                'session_id': str(meta.get('session_id') or session_id),
                'entries': entries}
    finally:
        conn.close()


def read_entry_rows(root, session_id):
    """id -> raw JSON, in insertion order (the diff baseline for incremental writes)."""
    root = Path(root)
    conn = connect(root, session_id)
    try:
        rows = conn.execute('SELECT id, raw FROM entries ORDER BY rowid').fetchall()
        return [(str(rid or ''), raw or '') for rid, raw in rows]
    finally:
        conn.close()


def write_doc(root, session_id, doc, changed=None, deleted=None, stamp_meta=True):
    """Upsert only the entries that changed; never rewrite the whole table.

    changed: iterable of entry dicts (or None to mean "everything in doc")
    deleted: iterable of ids to drop
    """
    root = Path(root)
    conn = connect(root, session_id)
    try:
        if stamp_meta:
            for key, value in (('schema_version', doc.get('schema_version', 1)),
                               ('session_id', doc.get('session_id', session_id))):
                conn.execute('INSERT INTO meta (k, v) VALUES (?, ?)'
                             ' ON CONFLICT(k) DO UPDATE SET v=excluded.v',
                             (key, str(value)))
        rows = doc.get('entries') if isinstance(doc.get('entries'), list) else []
        if changed is None:
            changed = rows
        for row in changed:
            if not isinstance(row, dict):
                continue
            conn.execute(
                'INSERT INTO entries (id,turn,ts,role,text,vector,hits,importance,deleted,raw)'
                ' VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET'
                ' turn=excluded.turn, ts=excluded.ts, role=excluded.role, text=excluded.text,'
                ' vector=excluded.vector, hits=excluded.hits, importance=excluded.importance,'
                ' deleted=excluded.deleted, raw=excluded.raw',
                (str(row.get('id') or ''), int(row.get('turn') or 0),
                 float(row.get('ts') or 0.0), str(row.get('role') or 'user'),
                 str(row.get('text') or ''), pack_vector(row.get('vector')),
                 int(row.get('hits') or 1), float(row.get('importance') or 0.2),
                 1 if row.get('deleted') else 0,
                 json.dumps(row, ensure_ascii=False)))
        for entry_id in deleted or []:
            conn.execute('DELETE FROM entries WHERE id=?', (str(entry_id),))
        conn.commit()
        return True
    finally:
        conn.close()


def export_doc_json(root, session_id, path=None):
    """Write the session document back out as JSON (export/debug only)."""
    doc = read_doc(root, session_id)
    if path is None:
        path = Path(root) / 'sessions' / session_id / 'memory.json'
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)
    return path


def export_events_json(root, session_id, path=None):
    """The event table as the old events/<sid>.json payload (export/debug only)."""
    state = load_event_state(root, session_id) or {'seen': 0, 'events': [], 'state': {}, 'open': []}
    payload = {'seen': int(state.get('seen') or 0), 'events': state.get('events') or [],
               'state': state.get('state') or {}, 'open': state.get('open') or []}
    if path is None:
        path = Path(root) / 'events' / (session_id + '.json')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)
    return path


def claims_by_thread(conn, thread=None, limit=50):
    if thread:
        rows = conn.execute('SELECT key,value,status,confidence,thread,turn FROM claims'
                            ' WHERE thread=? ORDER BY turn DESC LIMIT ?', (thread, limit)).fetchall()
    else:
        rows = conn.execute('SELECT key,value,status,confidence,thread,turn FROM claims'
                            ' ORDER BY turn DESC LIMIT ?', (limit,)).fetchall()
    return [{'key': r[0], 'value': r[1], 'status': r[2], 'confidence': r[3],
             'thread': r[4], 'turn': r[5]} for r in rows]


def journal_tail(conn, limit=50, kind=None):
    if kind:
        rows = conn.execute('SELECT ts,kind,payload FROM journal WHERE kind=?'
                            ' ORDER BY id DESC LIMIT ?', (kind, limit)).fetchall()
    else:
        rows = conn.execute('SELECT ts,kind,payload FROM journal ORDER BY id DESC LIMIT ?',
                            (limit,)).fetchall()
    out = []
    for ts, kind_, payload in rows:
        try:
            out.append(json.loads(payload))
        except Exception:
            out.append({'ts': ts, 'kind': kind_})
    return out


def backfill_vectors(root, session_id, events_path=None):
    """One-time: lift per-entry vectors out of the legacy event file.

    Databases written before the cutover stored event payloads without vectors,
    so a run that finds rows lacking coordinates repairs them from the JSON the
    events were originally built from. Idempotent: a fully populated table is a
    single COUNT.
    """
    root = Path(root)
    conn = connect(root, session_id)
    try:
        done = conn.execute(
            "SELECT v FROM meta WHERE k='vector_backfill'").fetchone()
        if done is not None:
            return 0          # one-shot: new rows get their vector from the save path
        missing = conn.execute(
            'SELECT COUNT(*) FROM entries WHERE vector IS NULL').fetchone()[0]
        if not missing:
            conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('vector_backfill','1')")
            conn.commit()
            return 0
        event_file = Path(events_path) if events_path is not None \
            else root / 'events' / (session_id + '.json')
        legacy = _read_json(event_file, {})
        rows = legacy.get('events') if isinstance(legacy, dict) else legacy
        vectors = harvest_event_vectors(rows or [])
        written = 0
        for entry_id, vector in vectors.items():
            blob = pack_vector(vector)
            if not blob:
                continue
            cur = conn.execute(
                'UPDATE entries SET vector=? WHERE id=? AND vector IS NULL',
                (blob, str(entry_id)))
            written += cur.rowcount or 0
        conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('vector_backfill','1')")
        conn.commit()
        return written
    except Exception:
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def open_or_import(root, session_id, events_path=None):
    """Never break an old install: import JSON when the db is missing."""
    root = Path(root)
    fresh = not db_path(root, session_id).exists()
    conn, info = import_session(root, session_id, force=False, events_path=events_path)
    # the caller owns the connection (legacy contract): never close it here
    info['vectors'] = backfill_vectors(root, session_id, events_path=events_path)
    info['fresh'] = fresh
    return conn, info


def _ensure_events_centroid(conn):
    """Old databases predate the centroid column; add it in place."""
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
        if "centroid" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN centroid BLOB")
    except Exception:
        pass


def pack_vector(vector):
    """float32 BLOB: an event centroid costs 4 KB instead of ~20 KB of JSON text."""
    try:
        import struct
        rows = [float(x) for x in (vector or [])]
        if not rows:
            return None
        return struct.pack("<%df" % len(rows), *rows)
    except Exception:
        return None


def unpack_vector(blob):
    try:
        import struct
        if not blob:
            return []
        return list(struct.unpack("<%df" % (len(blob) // 4), blob))
    except Exception:
        return []


def _event_payload(ev):
    """The event row minus the per-entry vectors, which hydrate from the cache."""
    out = dict(ev or {})
    rows = []
    for item in ev.get("entries") or []:
        if not isinstance(item, dict):
            continue
        rows.append({key: item.get(key) for key in
                     ("id", "turn", "ts", "role", "text")})
    out["entries"] = rows
    out.pop("vector", None)
    return out


def save_event_state(root, session_id, seen, events, global_state, open_buf):
    """Incrementally upsert the session's events; no whole-table rewrite."""
    conn = connect(root, session_id)
    try:
        _ensure_events_centroid(conn)
        live = {str(ev.get("event_id") or "") for ev in (events or [])
                if isinstance(ev, dict)}
        # cheap fingerprint of what is already on disk: one small SELECT, then
        # only the rows that actually changed are written (a closed event never
        # changes again, so a turn that closes one event writes one row)
        existing = {}
        try:
            for row in conn.execute(
                    "SELECT id, start, end, overview, length(text) FROM events").fetchall():
                existing[str(row[0])] = (int(row[1] or 0), int(row[2] or 0),
                                         str(row[3] or ""), int(row[4] or 0))
        except Exception:
            existing = {}
        for (eid,) in conn.execute("SELECT id FROM events").fetchall():
            if str(eid) not in live:
                conn.execute("DELETE FROM events WHERE id=?", (eid,))
        for ev in events or []:
            if not isinstance(ev, dict):
                continue
            key = (str(ev.get("event_id") or ""), int(ev.get("start") or 0),
                   int(ev.get("end") or 0), str(ev.get("overview") or ""),
                   len(str(ev.get("text") or "")))
            if existing.get(key[0]) == key[1:]:
                continue
            conn.execute(
                "INSERT INTO events (id,start,end,overview,text,closed_ts,payload,centroid)"
                " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET"
                " start=excluded.start, end=excluded.end, overview=excluded.overview,"
                " text=excluded.text, closed_ts=excluded.closed_ts,"
                " payload=excluded.payload, centroid=excluded.centroid",
                (str(ev.get("event_id") or ""), int(ev.get("start") or 0),
                 int(ev.get("end") or 0), str(ev.get("overview") or ""),
                 str(ev.get("text") or ""), float(ev.get("closed_ts") or 0.0),
                 json.dumps(_event_payload(ev), ensure_ascii=False),
                 pack_vector(ev.get("vector"))))
        conn.execute(
            "INSERT INTO event_state (session,seen,global_state,open_buf,updated)"
            " VALUES (?,?,?,?,?) ON CONFLICT(session) DO UPDATE SET"
            " seen=excluded.seen, global_state=excluded.global_state,"
            " open_buf=excluded.open_buf, updated=excluded.updated",
            (session_id, int(seen or 0), json.dumps(global_state or {}, ensure_ascii=False),
             json.dumps(open_buf or [], ensure_ascii=False), time.time()))
        conn.commit()
        return True
    finally:
        conn.close()


def load_event_state(root, session_id):
    """Read back what save_event_state wrote; None when the session is new."""
    import os as _os
    if not db_path(root, session_id).exists() and not _os.environ.get("BIOCORE_SQL_FIRST"):
        return None
    conn = connect(root, session_id)
    try:
        row = conn.execute("SELECT seen, global_state, open_buf FROM event_state WHERE session=?",
                           (session_id,)).fetchone()
        events = []
        try:
            rows = conn.execute(
                "SELECT payload, centroid FROM events ORDER BY start").fetchall()
        except Exception:
            rows = [(p, None) for (p,) in conn.execute(
                "SELECT payload FROM events ORDER BY start").fetchall()]
        for payload, centroid in rows:
            try:
                ev = json.loads(payload)
            except Exception:
                continue
            if centroid:
                ev["vector"] = unpack_vector(centroid)
            events.append(ev)
        if row is None and not events:
            return None
        seen = int((row or [0])[0] or 0)
        try:
            state = json.loads((row or [0, "{}"])[1] or "{}")
        except Exception:
            state = {}
        try:
            open_buf = json.loads((row or [0, "{}", "[]"])[2] or "[]")
        except Exception:
            open_buf = []
        return {"seen": seen, "events": events, "state": state, "open": open_buf}
    finally:
        conn.close()
