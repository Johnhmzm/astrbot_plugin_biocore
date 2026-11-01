# -*- coding: utf-8 -*-
"""Graph recall -> "你知道的" prompt block + panel data (task-136).

Read-only: match entity names/aliases in the current message, walk 1-2 hops
in the SQLite entity graph, rank edges by recency and confidence, and render
at most five lines. A time window ("上周"/"昨天"/"三天前") restricts edges to
that window. panel_data() feeds the Graph dashboard page.
"""
from __future__ import annotations

import json
import time

from . import entity_graph as _eg
from . import graph_extract as _gx

MAX_LINES = 5
MAX_ENTITIES = 3
MAX_EDGES = 200

WINDOW_WORDS = {
    "上周": 7, "上星期": 7, "上礼拜": 7, "最近一周": 7, "这周": 7,
    "本周": 7, "这星期": 7, "昨天": 1, "昨日": 1, "前天": 2,
    "三天内": 3, "最近三天": 3, "上个月": 30, "上月": 30,
}


def detect_window(text, now=None):
    """Return (window_days, label) for a relative time phrase, else (None, "")."""
    del now
    value = " ".join(str(text or "").split())
    for word, days in WINDOW_WORDS.items():
        if word in value:
            return int(days), word
    return None, ""


def _fmt_ts(ts):
    number = float(ts or 0.0)
    if number <= 0:
        return ""
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(number))
    except Exception:
        return ""


def _rel_score(edge, now):
    try:
        confidence = float(edge.get("confidence", 0.0) or 0.0)
    except Exception:
        confidence = 0.0
    try:
        ts = float(edge.get("ts", 0.0) or 0.0)
    except Exception:
        ts = 0.0
    if ts <= 0 or now <= 0:
        recency = 0.0
    else:
        age_days = max(0.0, (now - ts) / 86400.0)
        recency = 1.0 / (1.0 + age_days / 7.0)
    return round(0.65 * confidence + 0.35 * recency, 4)


def _name_of(by_id, entity_id):
    row = by_id.get(entity_id)
    if isinstance(row, dict):
        return str(row.get("name") or "")
    return ""


def recall(store, text, now=None, hops=2, limit=MAX_LINES,
           window_days=None, window_label=""):
    """Rank graph edges around matched entities -> list of prompt rows."""
    del window_label
    stamp = float(now if now is not None else time.time())
    entities = _eg.search(store, text, limit=MAX_ENTITIES)
    if not entities:
        return []
    try:
        cap = max(1, min(MAX_LINES, int(limit)))
    except Exception:
        cap = MAX_LINES
    if window_days is None:
        window_days, _label = detect_window(text, stamp)
    by_id = {entity["id"]: entity for entity in entities}
    candidate_edges = []
    seen_edges = set()
    for entity in entities:
        walked = _eg.neighbors(store, entity["name"], hops=hops,
                               window_days=window_days, now=stamp)
        for row in walked.get("entities") or []:
            by_id.setdefault(row["id"], row)
        for edge in walked.get("edges") or []:
            eid = str(edge.get("id") or "")
            if not eid or eid in seen_edges:
                continue
            seen_edges.add(eid)
            candidate_edges.append(edge)
    rows = []
    for edge in candidate_edges[:MAX_EDGES]:
        src_name = _name_of(by_id, edge.get("src"))
        dst_name = _name_of(by_id, edge.get("dst"))
        if not src_name or not dst_name:
            continue
        relation = str(edge.get("rel") or "")
        line = "%s —%s→ %s" % (src_name, _gx.rel_label(relation), dst_name)
        when = _fmt_ts(edge.get("ts"))
        if when:
            line += "（%s）" % when
        source_entity = by_id.get(edge.get("src")) or {}
        target_entity = by_id.get(edge.get("dst")) or {}
        rows.append({"edge_id": edge.get("id"), "line": line,
                     "src": src_name, "dst": dst_name, "rel": relation,
                     "rel_label": _gx.rel_label(relation),
                     "ts": float(edge.get("ts", 0.0) or 0.0),
                     "confidence": float(edge.get("confidence", 0.0) or 0.0),
                     "score": _rel_score(edge, stamp),
                     "src_type": source_entity.get("type"),
                     "dst_type": target_entity.get("type"),
                     "source_entry": str(edge.get("source_entry") or "")})
    rows.sort(key=lambda row: (row["score"], row["ts"]), reverse=True)
    return rows[:cap]


def render(store, text, now=None, limit=MAX_LINES):
    """Return the "你知道的" block (<=5 lines) or an empty string."""
    try:
        rows = recall(store, text, now=now, limit=limit)
    except Exception:
        return ""
    if not rows:
        return ""
    lines = ["你知道的："]
    for row in rows:
        lines.append("- " + str(row["line"]))
    return "\n".join(lines[:max(1, min(MAX_LINES, int(limit))) + 1])


def _row_entity_public(row):
    def _json_list(raw):
        try:
            value = json.loads(raw or "[]")
        except Exception:
            return []
        return [str(x) for x in value if str(x)] if isinstance(value, list) else []

    kind = str(row[2] or "topic")
    return {"id": row[0], "name": row[1], "type": kind,
            "type_label": _gx.type_label(kind),
            "aliases": _json_list(row[3]),
            "first_seen": float(row[4] or 0.0),
            "last_seen": float(row[5] or 0.0),
            "sources": _json_list(row[6])}


def timeline(store, entity, now=None, window_days=None, limit=12):
    """Edges touching one entity, newest first (panel detail / time view)."""
    stamp = float(now if now is not None else time.time())
    try:
        cap = max(1, min(50, int(limit)))
    except Exception:
        cap = 12
    walked = _eg.neighbors(store, entity, hops=1, window_days=window_days,
                           now=stamp)
    by_id = {row["id"]: row for row in walked.get("entities") or []}
    rows = []
    for edge in walked.get("edges") or []:
        src_name = _name_of(by_id, edge.get("src"))
        dst_name = _name_of(by_id, edge.get("dst"))
        rows.append({"edge_id": edge.get("id"),
                     "text": "%s —%s→ %s" % (
                         src_name, _gx.rel_label(edge.get("rel")), dst_name),
                     "when": _fmt_ts(edge.get("ts")),
                     "ts": float(edge.get("ts", 0.0) or 0.0),
                     "confidence": float(edge.get("confidence", 0.0) or 0.0)})
    rows.sort(key=lambda row: row["ts"], reverse=True)
    return rows[:cap]


def panel_data(store, now=None, limit_entities=100, limit_edges=400):
    """Flat entity/edge snapshot consumed by the dashboard Graph page."""
    stamp = float(now if now is not None else time.time())
    try:
        entity_cap = max(1, min(500, int(limit_entities)))
        edge_cap = max(1, min(2000, int(limit_edges)))
    except Exception:
        entity_cap, edge_cap = 100, 400
    entities = [_row_entity_public(row) for row in store._conn.execute(
        "SELECT id, name, type, aliases, first_seen, last_seen, sources "
        "FROM entities ORDER BY last_seen DESC LIMIT ?",
        (entity_cap,)).fetchall()]
    by_id = {row["id"]: row for row in entities}
    edges = []
    for row in store._conn.execute(
            "SELECT id, src, rel, dst, ts, confidence, source_entry "
            "FROM edges ORDER BY ts DESC LIMIT ?", (edge_cap,)).fetchall():
        edges.append({"id": row[0], "src": row[1], "dst": row[3],
                      "src_name": (by_id.get(row[1]) or {}).get("name", ""),
                      "dst_name": (by_id.get(row[3]) or {}).get("name", ""),
                      "rel": row[2], "rel_label": _gx.rel_label(row[2]),
                      "ts": float(row[4] or 0.0),
                      "when": _fmt_ts(row[4]),
                      "confidence": float(row[5] or 0.0),
                      "source_entry": row[6] or ""})
    try:
        stats = _eg.stats(store)
    except Exception:
        stats = {"entities": len(entities), "edges": len(edges)}
    return {"stats": stats, "entities": entities, "edges": edges,
            "now": stamp}


def source_entries(edges):
    """Collect source entry ids for the panel's "related entries" column."""
    seen = []
    for edge in edges or []:
        value = str((edge or {}).get("source_entry") or "")
        if value and value not in seen:
            seen.append(value)
    return seen
