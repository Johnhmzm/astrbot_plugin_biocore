# -*- coding: utf-8 -*-
"""Cue-index build/query (entities/place/time_coarse/event_name/id)."""
from __future__ import annotations
from .entities import cues, normalize_time

_INDEX_KEYS = ("entities", "place", "time_coarse", "event_name", "id")


def _entry_cues(entry) -> dict:
    """Resolve an entry's cues, preferring an existing cue_index field."""
    e = entry if isinstance(entry, dict) else {}
    existing = e.get("cue_index") if isinstance(e.get("cue_index"), dict) else {}
    if existing:
        out = {k: (list(existing.get(k) or []) if k in ("entities", "place")
                   else str(existing.get(k) or "")) for k in _INDEX_KEYS}
    else:
        text = " ".join(str(e.get(k) or "") for k in ("text", "title", "event", "event_name"))
        out = cues(text, ref_ts=e.get("ts") if isinstance(e.get("ts"), (int, float)) else None)
    out["id"] = str(e.get("id") or out.get("id") or "")
    if not out.get("event_name"):
        out["event_name"] = str(e.get("title") or "")[:20]
    return out


def build_index(entries) -> dict:
    """Build an inverted cue index from dict-like entries (deterministic)."""
    idx = {k: {} for k in _INDEX_KEYS}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        c = _entry_cues(entry)
        for key in _INDEX_KEYS:
            if key == "id":
                if c["id"]:
                    idx["id"][c["id"]] = c["id"]
                continue
            values = c[key] if isinstance(c[key], list) else ([c[key]] if c[key] else [])
            for token in values:
                idx[key].setdefault(str(token), [])
                if c["id"] and c["id"] not in idx[key][str(token)]:
                    idx[key][str(token)].append(c["id"])
    return idx


def cue_score(query, entry) -> float:
    """Deterministic 0..1 cue overlap between a query and an entry/cue dict."""
    q = cues(query) if isinstance(query, str) else (query if isinstance(query, dict) else {})
    e = _entry_cues(entry) if isinstance(entry, dict) and "cue_index" not in entry else entry
    def _overlap(a, b):
        sa, sb = set(a or []), set(b or [])
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / float(len(sa | sb))
    ent = _overlap(q.get("entities"), e.get("entities"))
    place = _overlap(q.get("place"), e.get("place"))
    qt = set(q.get("time_coarse") or q.get("time") or [])
    et = set(e.get("time_coarse") or e.get("time") or [])
    time = 1.0 if (qt and et and qt & et) else 0.0
    name = 1.0 if (q.get("entities") and e.get("event_name")
                   and q["entities"][0] in str(e.get("event_name"))) else 0.0
    return round(max(0.0, min(1.0, 0.45 * ent + 0.25 * place + 0.15 * time + 0.15 * name)), 4)


def query(index, text, limit=5) -> list:
    """Query an index and return <=limit entry ids ordered by cue score."""
    if not isinstance(index, dict):
        return []
    q = cues(text)
    candidates, scored = set(), []
    for key in ("entities", "place"):
        for token in q.get(key) or []:
            candidates.update(index.get(key, {}).get(str(token), []))
    if q.get("time_coarse"):
        candidates.update(index.get("time_coarse", {}).get(q["time_coarse"], []))
    for eid in candidates:
        entry = {"id": eid, "cue_index": {k: ([eid] if k == "id" else v)
                                          for k, v in index.items() if k != "id"}}
        scored.append((cue_score(q, entry), eid))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [eid for _s, eid in scored[:max(0, int(limit or 0))]]
