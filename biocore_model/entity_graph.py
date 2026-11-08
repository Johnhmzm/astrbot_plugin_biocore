# -*- coding: utf-8 -*-
"""Full entity graph memory: nodes + typed, timestamped edges (task-134).

Storage contract: one JSON document {"schema": 3, "entities": [...],
"edges": [...]}. Core operations are pure graph transforms; only
load_graph/save_graph touch the filesystem (atomic replace, corrupt recovery).
No tag approximations: entities are matched by normalized name or an explicit
alias, and edges carry rel/ts/confidence/source_entry for time reasoning and
two-hop retrieval.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

from . import entity_resolve as _er

SCHEMA_VERSION = 3
ENTITY_TYPES = ("person", "place", "event", "topic")
DEFAULT_TYPE = "topic"
MAX_ALIASES = 12
MAX_SOURCES = 8


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return default
    return number if number == number else default


def _norm(text):
    return "".join(ch for ch in str(text or "").lower()
                   if ch.isalnum())


def _clean_text(text):
    return " ".join(str(text or "").split()).strip()


def _id(prefix, *parts):
    raw = "|".join(str(part) for part in parts)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def empty_graph():
    return {"schema": SCHEMA_VERSION, "entities": [], "edges": []}


def normalize_graph(raw):
    """Sanitize a stored document into a valid graph (never raises)."""
    graph = empty_graph()
    if not isinstance(raw, dict):
        return graph
    entities = raw.get("entities")
    if isinstance(entities, list):
        seen = set()
        for item in entities:
            if not isinstance(item, dict):
                continue
            name = _clean_text(item.get("name"))
            norm = _norm(name)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            kind = str(item.get("type") or DEFAULT_TYPE).strip().lower()
            aliases = []
            for alias in (item.get("aliases") or []):
                text = _clean_text(alias)
                if text and _norm(text) != norm and text not in aliases:
                    aliases.append(text)
            graph["entities"].append({
                "id": str(item.get("id") or _id("e_", norm)),
                "name": name,
                "type": kind if kind in ENTITY_TYPES else DEFAULT_TYPE,
                "aliases": aliases[:MAX_ALIASES],
                "first_seen": _num(item.get("first_seen"), 0.0),
                "last_seen": _num(item.get("last_seen"), 0.0),
                "sources": [str(x) for x in (item.get("sources") or [])
                            if str(x)][:MAX_SOURCES],
            })
    edges = raw.get("edges")
    if isinstance(edges, list):
        known = {row["id"] for row in graph["entities"]}
        seen = set()
        for item in edges:
            if not isinstance(item, dict):
                continue
            src = str(item.get("src") or "").strip()
            dst = str(item.get("dst") or "").strip()
            rel = str(item.get("rel") or "").strip().lower()
            if not src or not dst or not rel or src not in known or dst not in known:
                continue
            ts = _num(item.get("ts"), 0.0)
            edge_id = str(item.get("id") or _id("r_", src, rel, dst, ts))
            if edge_id in seen:
                continue
            seen.add(edge_id)
            graph["edges"].append({
                "id": edge_id,
                "src": src,
                "rel": rel,
                "dst": dst,
                "ts": ts,
                "confidence": max(0.0, min(1.0, _num(item.get("confidence"), 1.0))),
                "source_entry": str(item.get("source_entry") or ""),
            })
    graph["schema"] = SCHEMA_VERSION
    return graph


def _matches(entity, key):
    norm = _norm(key)
    if not norm:
        return False
    return _norm(entity.get("name")) == norm or any(
        _norm(alias) == norm for alias in (entity.get("aliases") or []))


def find_entity(graph, name):
    """Return the entity matched by name or alias, or None."""
    for entity in (graph or {}).get("entities") or []:
        if isinstance(entity, dict) and _matches(entity, name):
            return entity
    return None


def resolve_name(graph, name):
    entity = find_entity(graph, name)
    if entity is not None:
        return entity["id"]
    key = _clean_text(name)
    return _id("e_", _norm(key)) if key else ""


def upsert_entity(graph, name, type=None, aliases=None, now=None, entry_id="",
                  inplace=False):
    """Add or merge one entity; returns (graph_or_store, entity_id).

    A caller that already owns a normalized graph passes inplace=True: copying
    the whole graph on every upsert made graph building O(n^2) with a deepcopy
    per call (the 12 s injection).
    """
    if isinstance(graph, GraphStore):
        return graph.upsert_entity(name, type=type, aliases=aliases, now=now,
                                   entry_id=entry_id)
    out = graph if inplace else normalize_graph(copy.deepcopy(graph))
    key = _clean_text(name)
    norm = _norm(key)
    if not norm:
        return out, ""
    stamp = _num(now, 0.0)
    extra_aliases = [_clean_text(x) for x in (aliases or []) if _clean_text(x)]
    entity = find_entity(out, key)
    if entity is None:
        # P0-1: fold an alias / near-identical spelling into the existing node.
        hit = _er.match(out["entities"], key, extra_aliases)
        if hit is not None:
            entity = next((row for row in out["entities"]
                           if row.get("id") == hit["id"]), None)
            if (entity is not None
                    and _norm(key) != _norm(entity.get("name"))):
                extra_aliases.append(key)
    if entity is None:
        entity = {
            "id": _id("e_", norm),
            "name": key,
            "type": (str(type).strip().lower() if type else DEFAULT_TYPE),
            "aliases": [],
            "first_seen": stamp,
            "last_seen": stamp,
            "sources": [],
        }
        if entity["type"] not in ENTITY_TYPES:
            entity["type"] = DEFAULT_TYPE
        out["entities"].append(entity)
    else:
        if type:
            kind = str(type).strip().lower()
            if kind in ENTITY_TYPES:
                entity["type"] = kind
        entity["last_seen"] = max(_num(entity.get("last_seen"), 0.0), stamp)
        entity["first_seen"] = min(
            _num(entity.get("first_seen"), stamp) or stamp, stamp or 0.0)
    name_norm = _norm(entity.get("name"))
    aliases_now = [text for text in (entity.get("aliases") or [])
                   if _norm(text) != name_norm]
    for alias in extra_aliases:
        text = _clean_text(alias)
        if not text or _norm(text) == name_norm or text in aliases_now:
            continue
        aliases_now.append(text)
    entity["aliases"] = aliases_now[:MAX_ALIASES]
    if entry_id:
        sources = list(entity.get("sources") or [])
        if entry_id not in sources:
            sources.append(str(entry_id))
        entity["sources"] = sources[-MAX_SOURCES:]
    return out, entity["id"]


def upsert_edge(graph, src, rel, dst, ts=None, confidence=1.0, source_entry="",
                src_type=None, dst_type=None, now=None, inplace=False):
    """Add one typed, timestamped edge (auto-creating entities); returns graph/id."""
    if isinstance(graph, GraphStore):
        return graph.upsert_edge(src, rel, dst, ts=ts, confidence=confidence,
                                 source_entry=source_entry, src_type=src_type,
                                 dst_type=dst_type, now=now)
    out = graph if inplace else normalize_graph(copy.deepcopy(graph))
    source = _clean_text(src)
    target = _clean_text(dst)
    relation = str(rel or "").strip().lower()
    if not source or not target or not relation:
        return out, ""
    out, src_id = upsert_entity(out, source, type=src_type, now=now,
                                entry_id=source_entry, inplace=True)
    out, dst_id = upsert_entity(out, target, type=dst_type, now=now,
                                entry_id=source_entry, inplace=True)
    if not src_id or not dst_id or src_id == dst_id:
        # P0-1: both spellings resolved to one node -> a self-loop is noise.
        return out, ""
    stamp = _num(ts, _num(now, 0.0))
    confidence = max(0.0, min(1.0, _num(confidence, 1.0)))
    edge_id = _id("r_", src_id, relation, dst_id, stamp)
    for edge in out["edges"]:
        if edge.get("id") == edge_id:
            edge["confidence"] = max(float(edge.get("confidence", 0.0) or 0.0),
                                     confidence)
            if source_entry:
                edge["source_entry"] = str(source_entry)
            return out, edge_id
    out["edges"].append({
        "id": edge_id,
        "src": src_id,
        "rel": relation,
        "dst": dst_id,
        "ts": stamp,
        "confidence": confidence,
        "source_entry": str(source_entry or ""),
    })
    return out, edge_id


def _merge_report(keep_id, drop_id):
    return {"ok": False, "keep_id": str(keep_id or ""),
            "drop_id": str(drop_id or ""), "aliases": 0, "sources": 0,
            "edges_rewired": 0, "edges_dropped": 0, "error": ""}


def find_similar(graph, name, aliases=(), threshold=None):
    """Best {"id","name","score","via"} for a name/alias, or None (P0-1)."""
    if isinstance(graph, GraphStore):
        return graph.find_similar(name, aliases=aliases, threshold=threshold)
    clean = normalize_graph(copy.deepcopy(graph))
    limit = _er.SIMILARITY_THRESHOLD if threshold is None else threshold
    return _er.match(clean["entities"], name, aliases, limit)


def merge_entities(graph, keep_id, drop_id):
    """Merge drop_id into keep_id; returns (graph_or_store, report).

    Fields are unioned (aliases/sources/first/last/type) and every edge that
    pointed at the dropped node is rewired to the kept one. Edges that become a
    self-loop are dropped; edges that collapse onto an existing row are folded.
    """
    if isinstance(graph, GraphStore):
        return graph, graph.merge_entities(keep_id, drop_id)
    out = normalize_graph(copy.deepcopy(graph))
    report = _merge_report(keep_id, drop_id)
    if not report["keep_id"] or not report["drop_id"]:
        report["error"] = "keep_id/drop_id required"
        return out, report
    if report["keep_id"] == report["drop_id"]:
        report["error"] = "same entity"
        return out, report
    keep = next((row for row in out["entities"]
                 if row["id"] == report["keep_id"]), None)
    drop = next((row for row in out["entities"]
                 if row["id"] == report["drop_id"]), None)
    if keep is None or drop is None:
        report["error"] = "entity not found"
        return out, report
    keep["aliases"] = _er.merged_aliases(
        keep["name"], keep["aliases"], drop["name"], drop["aliases"])
    keep["sources"] = _er.merged_sources(keep["sources"], drop["sources"])
    keep["type"] = _er.merged_type(keep["type"], drop["type"])
    keep["first_seen"], keep["last_seen"] = _er.merged_span(
        keep.get("first_seen"), keep.get("last_seen"),
        drop.get("first_seen"), drop.get("last_seen"))
    out["entities"] = [row for row in out["entities"]
                       if row["id"] != report["drop_id"]]
    out["edges"], stats = _er.rewrite_edges(
        out["edges"], report["keep_id"], report["drop_id"],
        make_id=lambda src, rel, dst, ts: _id("r_", src, rel, dst, ts))
    report.update({"ok": True, "aliases": len(keep["aliases"]),
                   "sources": len(keep["sources"]),
                   "edges_rewired": stats["rewired"],
                   "edges_dropped": stats["dropped"]})
    return out, report


def _window_start(window_days, now):
    if window_days is None:
        return None
    days = _num(window_days, 0.0)
    if days <= 0:
        return None
    base = _num(now, 0.0)
    if base <= 0:
        latest = 0.0
        return None
    return base - days * 86400.0


def neighbors(graph, entity, hops=2, window_days=None, now=None, limit=80):
    """Neighbours around an entity/alias (dict = in-memory, GraphStore = CTE)."""
    if isinstance(graph, GraphStore):
        return graph.neighbors(entity, hops=hops, window_days=window_days,
                               now=now, limit=limit)
    clean = normalize_graph(graph)
    start = find_entity(clean, entity)
    result = {"entities": [], "edges": []}
    if start is None:
        return result
    try:
        depth_limit = max(1, min(4, int(hops)))
    except Exception:
        depth_limit = 2
    try:
        row_limit = max(1, min(500, int(limit)))
    except Exception:
        row_limit = 80
    start_ts = _window_start(window_days, now)
    by_id = {row["id"]: row for row in clean["entities"]}
    visited = {start["id"]}
    frontier = [start["id"]]
    used_edge_ids = set()
    for _depth in range(depth_limit):
        next_frontier = []
        for node_id in frontier:
            for edge in clean["edges"]:
                if edge["src"] != node_id and edge["dst"] != node_id:
                    continue
                if start_ts is not None and _num(edge.get("ts"), 0.0) < start_ts:
                    continue
                other = edge["dst"] if edge["src"] == node_id else edge["src"]
                if other not in visited:
                    visited.add(other)
                    next_frontier.append(other)
                if edge["id"] not in used_edge_ids:
                    used_edge_ids.add(edge["id"])
                    result["edges"].append(dict(edge))
        frontier = next_frontier
        if not frontier:
            break
    result["entities"] = [dict(by_id[eid]) for eid in visited
                          if eid in by_id][:row_limit]
    result["edges"].sort(key=lambda row: (-_num(row.get("ts"), 0.0),
                                         -_num(row.get("confidence"), 0.0)))
    result["edges"] = result["edges"][:row_limit]
    return result


def search(graph, text, limit=8):
    """Entities whose name or alias appears in *text* (longest match first)."""
    if isinstance(graph, GraphStore):
        return graph.search(text, limit=limit)
    clean = normalize_graph(graph)
    haystack = _norm(text)
    hits = []
    if not haystack:
        return hits
    for entity in clean["entities"]:
        names = [entity.get("name")] + list(entity.get("aliases") or [])
        best = 0
        for name in names:
            norm = _norm(name)
            if norm and norm in haystack:
                best = max(best, len(norm))
        if best:
            hits.append((best, entity))
    hits.sort(key=lambda row: row[0], reverse=True)
    return [dict(entity) for _score, entity in hits[:max(1, int(limit or 8))]]


def stats(graph):
    """Bounded counts used by the panel and health checks."""
    if isinstance(graph, GraphStore):
        return graph.stats()
    clean = normalize_graph(graph)
    types = {}
    aliases = 0
    for entity in clean["entities"]:
        kind = str(entity.get("type") or DEFAULT_TYPE)
        types[kind] = int(types.get(kind, 0)) + 1
        aliases += len(entity.get("aliases") or [])
    latest = max([_num(edge.get("ts"), 0.0) for edge in clean["edges"]] or [0.0])
    return {"schema": clean["schema"],
            "entities": len(clean["entities"]),
            "edges": len(clean["edges"]),
            "types": types,
            "aliases": aliases,
            "latest_ts": latest}


def load_graph(path):
    """Read a graph document; corrupt files are backed up and recovered empty."""
    target = Path(path)
    if not target.is_file():
        return empty_graph()
    try:
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
        return normalize_graph(raw)
    except Exception:
        try:
            shutil.copyfile(target, target.with_name(target.name + ".corrupt.bak"))
        except Exception:
            pass
        return empty_graph()


def save_graph(path, graph):
    """Atomic write of the graph document (tmp + os.replace)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = normalize_graph(graph)
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, target)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return target



# ---------------------------------------------------------------------------
# SQLite storage layer (task-134 addendum). The public functions above accept
# a GraphStore and delegate to it; the JSON helpers below stay the
# export/backup format only.
# ---------------------------------------------------------------------------

SQLITE_FILE = "graph.sqlite3"
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS entities(
    id TEXT PRIMARY KEY, name TEXT, type TEXT, aliases TEXT,
    first_seen REAL, last_seen REAL, sources TEXT);
CREATE TABLE IF NOT EXISTS edges(
    id TEXT PRIMARY KEY, src TEXT, rel TEXT, dst TEXT, ts REAL,
    confidence REAL, source_entry TEXT);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
CREATE INDEX IF NOT EXISTS idx_edges_ts ON edges(ts);
CREATE INDEX IF NOT EXISTS idx_edges_rel ON edges(rel);
"""


def _row_entity(row):
    def _json_list(raw):
        try:
            value = json.loads(raw or "[]")
        except Exception:
            return []
        return [str(x) for x in value if str(x)] if isinstance(value, list) else []

    return {"id": row[0], "name": row[1], "type": row[2] or DEFAULT_TYPE,
            "aliases": _json_list(row[3]),
            "first_seen": _num(row[4], 0.0), "last_seen": _num(row[5], 0.0),
            "sources": _json_list(row[6])}


def _row_edge(row):
    return {"id": row[0], "src": row[1], "rel": row[2], "dst": row[3],
            "ts": _num(row[4], 0.0),
            "confidence": _num(row[5], 1.0),
            "source_entry": row[6] or ""}


_ENTITY_COLS = "id, name, type, aliases, first_seen, last_seen, sources"
_EDGE_COLS = "id, src, rel, dst, ts, confidence, source_entry"


class GraphStore:
    """Thin SQLite wrapper. One connection, WAL, explicit transactions."""

    def __init__(self, path, recover=True, similarity_threshold=None):
        self.path = Path(path)
        self._conn = None
        # P0-1: <=0 disables the similarity fallback (exact name/alias only).
        self.similarity_threshold = (
            _er.SIMILARITY_THRESHOLD if similarity_threshold is None
            else float(similarity_threshold))
        self._open(recover=recover)

    # -- connection / schema ------------------------------------------------
    def _open(self, recover=True):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(str(self.path), timeout=5.0)
            self._configure()
            self._ensure_schema()
        except sqlite3.DatabaseError:
            if not recover:
                raise
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            self._recover_corrupt()
            self._conn = sqlite3.connect(str(self.path), timeout=5.0)
            self._configure()
            self._ensure_schema()

    def _configure(self):
        cur = self._conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=5000")

    def _ensure_schema(self):
        with self._conn:
            self._conn.executescript(_SCHEMA_SQL)

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
        """Fold the WAL back into the main file before copying it."""
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return True
        except Exception:
            return False

    # -- entity / edge writes ----------------------------------------------
    def _find_entity(self, name):
        norm = _norm(name)
        if not norm:
            return None
        cur = self._conn.execute(
            "SELECT " + _ENTITY_COLS + " FROM entities "
            "WHERE lower(replace(name,' ',''))=? OR aliases LIKE ? LIMIT 1",
            (norm, "%" + str(name) + "%"))
        row = cur.fetchone()
        return _row_entity(row) if row else None

    def _row_by_id(self, entity_id):
        row = self._conn.execute(
            "SELECT " + _ENTITY_COLS + " FROM entities WHERE id=?",
            (str(entity_id or ""),)).fetchone()
        return _row_entity(row) if row else None

    def find_similar(self, name, aliases=(), threshold=None):
        """Best {"id","name","score","via"} match, bounded scan (P0-1)."""
        limit = (self.similarity_threshold if threshold is None
                 else float(threshold))
        if not limit or limit <= 0:
            return None
        rows = [_row_entity(row) for row in self._conn.execute(
            "SELECT " + _ENTITY_COLS + " FROM entities "
            "ORDER BY last_seen DESC LIMIT ?", (_er.SCAN_LIMIT,)).fetchall()]
        return _er.match(rows, name, aliases, limit)

    def upsert_entity(self, name, type=None, aliases=None, now=None, entry_id=""):
        key = _clean_text(name)
        norm = _norm(key)
        if not norm:
            return self, ""
        stamp = _num(now, 0.0)
        with self._conn:
            entity = self._find_entity(key)
            if entity is None:
                # P0-1: fold a near-identical spelling into the existing node.
                hit = self.find_similar(key, aliases or ())
                if hit is not None:
                    entity = self._row_by_id(hit["id"])
            entity_name = _clean_text(entity.get("name")) if entity else key
            name_norm = _norm(entity_name)
            if entity is not None and _norm(key) != name_norm:
                # Keep the spelling this message used as an alias.
                aliases = list(aliases or []) + [key]
            aliases_now = [text for text in
                           (_clean_text(alias) for alias in
                            (entity.get("aliases") if entity else []))
                           if text and _norm(text) != name_norm]
            for alias in (aliases or []):
                text = _clean_text(alias)
                if text and _norm(text) != name_norm and text not in aliases_now:
                    aliases_now.append(text)
            aliases_now = aliases_now[:MAX_ALIASES]
            sources = list(entity.get("sources") or []) if entity else []
            if entry_id and str(entry_id) not in sources:
                sources.append(str(entry_id))
            if entity is None:
                eid = _id("e_", norm)
                kind = str(type).strip().lower() if type else DEFAULT_TYPE
                if kind not in ENTITY_TYPES:
                    kind = DEFAULT_TYPE
                self._conn.execute(
                    "INSERT OR REPLACE INTO entities(" + _ENTITY_COLS + ") "
                    "VALUES(?,?,?,?,?,?,?)",
                    (eid, key, kind, json.dumps(aliases_now, ensure_ascii=False),
                     stamp, stamp, json.dumps(sources, ensure_ascii=False)))
                return self, eid
            eid = str(entity["id"])
            kind = str(entity.get("type") or DEFAULT_TYPE)
            if type:
                candidate = str(type).strip().lower()
                if candidate in ENTITY_TYPES:
                    kind = candidate
            first_seen = _num(entity.get("first_seen"), stamp)
            if not first_seen:
                first_seen = stamp
            self._conn.execute(
                "UPDATE entities SET name=?, type=?, aliases=?, first_seen=?, "
                "last_seen=?, sources=? WHERE id=?",
                (entity.get("name") or key, kind,
                 json.dumps(aliases_now, ensure_ascii=False),
                 min(first_seen, stamp or first_seen),
                 max(_num(entity.get("last_seen"), 0.0), stamp),
                 json.dumps(sources, ensure_ascii=False), eid))
            return self, eid

    def upsert_edge(self, src, rel, dst, ts=None, confidence=1.0,
                    source_entry="", src_type=None, dst_type=None, now=None):
        source = _clean_text(src)
        target = _clean_text(dst)
        relation = str(rel or "").strip().lower()
        if not source or not target or not relation:
            return self, ""
        _, src_id = self.upsert_entity(source, type=src_type, now=now,
                                       entry_id=source_entry)
        _, dst_id = self.upsert_entity(target, type=dst_type, now=now,
                                       entry_id=source_entry)
        if not src_id or not dst_id or src_id == dst_id:
            # P0-1: both spellings resolved to one node -> a self-loop is noise.
            return self, ""
        stamp = _num(ts, _num(now, 0.0))
        score = max(0.0, min(1.0, _num(confidence, 1.0)))
        edge_id = _id("r_", src_id, relation, dst_id, stamp)
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO edges(" + _EDGE_COLS + ") "
                "VALUES(?,?,?,?,?,?,?)",
                (edge_id, src_id, relation, dst_id, stamp, score,
                 str(source_entry or "")))
            self._conn.execute(
                "UPDATE edges SET confidence=MAX(confidence,?), "
                "source_entry=CASE WHEN ?<>'' THEN ? ELSE source_entry END "
                "WHERE id=?",
                (score, str(source_entry or ""), str(source_entry or ""), edge_id))
        return self, edge_id

    def merge_entities(self, keep_id, drop_id):
        """Merge one entity into another (aliases/sources/time + edge rewire)."""
        report = _merge_report(keep_id, drop_id)
        if not report["keep_id"] or not report["drop_id"]:
            report["error"] = "keep_id/drop_id required"
            return report
        if report["keep_id"] == report["drop_id"]:
            report["error"] = "same entity"
            return report
        keep = self._row_by_id(report["keep_id"])
        drop = self._row_by_id(report["drop_id"])
        if keep is None or drop is None:
            report["error"] = "entity not found"
            return report
        aliases = _er.merged_aliases(keep["name"], keep["aliases"],
                                     drop["name"], drop["aliases"])
        sources = _er.merged_sources(keep["sources"], drop["sources"])
        kind = _er.merged_type(keep["type"], drop["type"])
        first_seen, last_seen = _er.merged_span(
            keep.get("first_seen"), keep.get("last_seen"),
            drop.get("first_seen"), drop.get("last_seen"))
        with self._conn:
            rewired, dropped = self._rewire_edges(keep["id"], drop["id"])
            self._conn.execute(
                "UPDATE entities SET aliases=?, type=?, first_seen=?, "
                "last_seen=?, sources=? WHERE id=?",
                (json.dumps(aliases, ensure_ascii=False), kind, first_seen,
                 last_seen, json.dumps(sources, ensure_ascii=False),
                 keep["id"]))
            self._conn.execute("DELETE FROM entities WHERE id=?", (drop["id"],))
        report.update({"ok": True, "aliases": len(aliases),
                       "sources": len(sources), "edges_rewired": rewired,
                       "edges_dropped": dropped})
        return report

    def _rewire_edges(self, keep_id, drop_id):
        """Move drop_id edge endpoints onto keep_id; returns (rewired, dropped)."""
        rows = self._conn.execute(
            "SELECT " + _EDGE_COLS + " FROM edges WHERE src=? OR dst=?",
            (drop_id, drop_id)).fetchall()
        rewired = 0
        dropped = 0
        for row in rows:
            edge = _row_edge(row)
            src = keep_id if edge["src"] == drop_id else edge["src"]
            dst = keep_id if edge["dst"] == drop_id else edge["dst"]
            changed = src != edge["src"] or dst != edge["dst"]
            if changed and src == dst:
                self._conn.execute("DELETE FROM edges WHERE id=?",
                                   (edge["id"],))
                dropped += 1
                continue
            if not changed:
                continue
            rewired += 1
            new_id = _id("r_", src, edge["rel"], dst, edge["ts"])
            existing = self._conn.execute(
                "SELECT id FROM edges WHERE id=?", (new_id,)).fetchone()
            if existing is None:
                self._conn.execute(
                    "INSERT INTO edges(" + _EDGE_COLS + ") "
                    "VALUES(?,?,?,?,?,?,?)",
                    (new_id, src, edge["rel"], dst, edge["ts"],
                     edge["confidence"], edge["source_entry"]))
            else:
                self._conn.execute(
                    "UPDATE edges SET confidence=MAX(confidence,?), "
                    "source_entry=CASE WHEN ?<>'' THEN ? ELSE source_entry END "
                    "WHERE id=?",
                    (edge["confidence"], edge["source_entry"],
                     edge["source_entry"], new_id))
                dropped += 1
            self._conn.execute("DELETE FROM edges WHERE id=?", (edge["id"],))
        return rewired, dropped

    # -- queries ------------------------------------------------------------
    def neighbors(self, entity, hops=2, window_days=None, now=None, limit=80):
        start = self._find_entity(entity)
        if start is None:
            return {"entities": [], "edges": []}
        try:
            depth_limit = max(1, min(4, int(hops)))
        except Exception:
            depth_limit = 2
        try:
            row_limit = max(1, min(500, int(limit)))
        except Exception:
            row_limit = 80
        window = _window_start(window_days, now)
        params = [str(start["id"]), depth_limit]
        window_sql = "? IS NULL OR e.ts >= ?"
        params_sql = (None, window) if window is None else (1, window)
        sql = ("WITH RECURSIVE reach(id, depth) AS ("
               "SELECT ?, 0 "
               "UNION "
               "SELECT CASE WHEN e.src = reach.id THEN e.dst ELSE e.src END,"
               " reach.depth + 1 "
               "FROM edges e JOIN reach "
               "ON (e.src = reach.id OR e.dst = reach.id) "
               "WHERE reach.depth < ? AND (" + window_sql + ")) "
               "SELECT id FROM reach")
        rows = self._conn.execute(sql, params + list(params_sql)).fetchall()
        ids = [str(row[0]) for row in rows]
        if not ids:
            return {"entities": [], "edges": []}
        qmarks = ",".join("?" for _ in ids)
        entities = [_row_entity(row) for row in self._conn.execute(
            "SELECT " + _ENTITY_COLS + " FROM entities WHERE id IN (" + qmarks + ") LIMIT ?",
            ids + [row_limit]).fetchall()]
        edge_rows = self._conn.execute(
            "SELECT " + _EDGE_COLS + " FROM edges "
            "WHERE src IN (" + qmarks + ") AND dst IN (" + qmarks + ") "
            "AND (? IS NULL OR ts >= ?) "
            "ORDER BY ts DESC, confidence DESC LIMIT ?",
            ids + ids + [window, window, row_limit]).fetchall()
        return {"entities": entities,
                "edges": [_row_edge(row) for row in edge_rows]}

    def search(self, text, limit=8):
        haystack = _clean_text(text)
        if not haystack:
            return []
        try:
            cap = max(1, int(limit or 8))
        except Exception:
            cap = 8
        try:
            rows = self._conn.execute(
                "SELECT " + _ENTITY_COLS + ", length(name) AS ln FROM entities "
                "WHERE ? LIKE '%' || name || '%' OR EXISTS("
                "SELECT 1 FROM json_each(entities.aliases) "
                "WHERE ? LIKE '%' || json_each.value || '%') "
                "ORDER BY ln DESC LIMIT ?", (haystack, haystack, cap)).fetchall()
        except sqlite3.DatabaseError:
            rows = []
        if rows:
            return [_row_entity(row[:7]) for row in rows]
        # Fallback for SQLite builds without JSON1: bounded LIKE scan.
        out = []
        for row in self._conn.execute(
                "SELECT " + _ENTITY_COLS + " FROM entities LIMIT 500").fetchall():
            entity = _row_entity(row)
            for name in [entity["name"]] + list(entity["aliases"]):
                if _norm(name) and _norm(name) in _norm(haystack):
                    out.append((len(_norm(name)), entity))
                    break
        out.sort(key=lambda item: item[0], reverse=True)
        return [entity for _length, entity in out[:cap]]

    def stats(self):
        entities = int(self._conn.execute(
            "SELECT COUNT(*) FROM entities").fetchone()[0] or 0)
        edges = int(self._conn.execute(
            "SELECT COUNT(*) FROM edges").fetchone()[0] or 0)
        types = {str(kind): int(count) for kind, count in self._conn.execute(
            "SELECT type, COUNT(*) FROM entities GROUP BY type").fetchall()}
        try:
            aliases = int(self._conn.execute(
                "SELECT COALESCE(SUM(json_array_length(aliases)),0) FROM entities"
            ).fetchone()[0] or 0)
        except sqlite3.DatabaseError:
            aliases = 0
        latest = _num(self._conn.execute(
            "SELECT COALESCE(MAX(ts),0) FROM edges").fetchone()[0], 0.0)
        return {"schema": SCHEMA_VERSION, "entities": entities, "edges": edges,
                "types": types, "aliases": aliases, "latest_ts": latest}

    # -- JSON export / import ----------------------------------------------
    def export_json(self, path=None):
        target = Path(path) if path else self.path.with_name("graph.json")
        graph = {"schema": SCHEMA_VERSION,
                 "entities": [_row_entity(row) for row in self._conn.execute(
                     "SELECT " + _ENTITY_COLS + " FROM entities ORDER BY name")],
                 "edges": [_row_edge(row) for row in self._conn.execute(
                     "SELECT " + _EDGE_COLS + " FROM edges ORDER BY ts")]}
        save_graph(target, graph)
        return target

    def import_json(self, path):
        data = load_graph(path)
        imported = {"entities": 0, "edges": 0}
        if not data["entities"] and not data["edges"]:
            return imported
        with self._conn:
            for entity in data["entities"]:
                self._conn.execute(
                    "INSERT OR IGNORE INTO entities(" + _ENTITY_COLS + ") "
                    "VALUES(?,?,?,?,?,?,?)",
                    (entity["id"], entity["name"], entity["type"],
                     json.dumps(entity["aliases"], ensure_ascii=False),
                     entity["first_seen"], entity["last_seen"],
                     json.dumps(entity["sources"], ensure_ascii=False)))
                imported["entities"] += 1
            for edge in data["edges"]:
                self._conn.execute(
                    "INSERT OR IGNORE INTO edges(" + _EDGE_COLS + ") "
                    "VALUES(?,?,?,?,?,?,?)",
                    (edge["id"], edge["src"], edge["rel"], edge["dst"],
                     edge["ts"], edge["confidence"], edge["source_entry"]))
                imported["edges"] += 1
        return imported


def open_store(path, recover=True, similarity_threshold=None):
    return GraphStore(path, recover=recover,
                      similarity_threshold=similarity_threshold)


def checkpoint(path):
    """Fold WAL into the SQLite file; safe no-op when the file is absent/broken."""
    target = Path(path)
    if not target.is_file():
        return False
    try:
        conn = sqlite3.connect(str(target), timeout=5.0)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
        return True
    except Exception:
        return False


def export_json(store, path=None):
    if isinstance(store, GraphStore):
        return store.export_json(path)
    target = Path(path)
    save_graph(target, store)
    return target


def import_json(store, path):
    if isinstance(store, GraphStore):
        return store.import_json(path)
    data = load_graph(path)
    graph = normalize_graph(store)
    entity_sources = {entity["id"]: entity for entity in graph["entities"]}
    merged = {row["id"]: row for row in graph["entities"]}
    for entity in data["entities"]:
        merged.setdefault(entity["id"], entity)
    edges = {row["id"]: row for row in graph["edges"]}
    for edge in data["edges"]:
        edges.setdefault(edge["id"], edge)
    target = {"schema": SCHEMA_VERSION, "entities": list(merged.values()),
              "edges": list(edges.values())}
    return target
