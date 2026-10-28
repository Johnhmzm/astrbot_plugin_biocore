# -*- coding: utf-8 -*-
"""Deterministic link graph for PPR multi-hop recall (pure; default OFF).

PPR needs a graph; this module derives one from memory entries:
  - same entities   (entity Jaccard; cue_index.entities or extracted from text);
  - same event      (equal event_id or event_name);
  - time proximity  (|ts_a - ts_b| <= 1 hour, graded);
  - similar tags    (tag Jaccard).
pair score = 1.0 * entities + 0.8 * event + 0.6 * time + 0.4 * tags; pairs
below MIN_LINK_SCORE are dropped. Each node keeps at most MAX_LINKS=8
neighbours, chosen symmetrically by descending score, so the result is stable
and can be fed to recall.ppr.expand_ppr as {id: [neighbour_ids]}.

The module is disabled by default: callers gate on 'enabled'.
No IO, no LLM, no host imports.
"""
from __future__ import annotations

from .entities import extract_entities

enabled = False
GRAPH_ENABLED = enabled

MAX_LINKS = 8
MAX_ITEMS = 8
TIME_WINDOW_SECONDS = 3600.0
MIN_LINK_SCORE = 0.5
W_ENTITY = 1.0
W_EVENT = 0.8
W_TIME = 0.6
W_TAG = 0.4


def _get(entry, key, default=None):
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


def _cue(entry):
    cue = _get(entry, "cue_index")
    return cue if isinstance(cue, dict) else {}


def _list(value, limit=MAX_ITEMS):
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, dict):
        raw = list(value.keys())
    elif isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        raw = []
    out, seen = [], set()
    for item in raw:
        if isinstance(item, dict):
            item = item.get("id") or item.get("name") or item.get("text") or ""
        text = " ".join(str(item or "").split())[:64]
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _entities(entry):
    values = _list(_get(entry, "entities"))
    if not values:
        values = _list(_cue(entry).get("entities"))
    metadata = _get(entry, "metadata")
    if not values and isinstance(metadata, dict):
        values = _list(metadata.get("entities"))
    if not values:
        values = extract_entities(str(_get(entry, "text", "") or ""))
    return values


def _event_key(entry):
    key = _get(entry, "event_id")
    if not key:
        key = _get(entry, "event_name")
    if not key:
        key = _cue(entry).get("event_name")
    return str(key or "").strip().lower()


def _tags(entry):
    values = _list(_get(entry, "tags"))
    metadata = _get(entry, "metadata")
    if not values and isinstance(metadata, dict):
        values = _list(metadata.get("tags"))
    return values


def _ts(entry):
    try:
        return max(0.0, float(_get(entry, "ts", 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _jaccard(left, right):
    a = {str(value).lower() for value in left if str(value)}
    b = {str(value).lower() for value in right if str(value)}
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _time_score(left, right):
    a, b = _ts(left), _ts(right)
    if a <= 0.0 or b <= 0.0:
        return 0.0
    delta = abs(a - b)
    if delta >= TIME_WINDOW_SECONDS:
        return 0.0
    return 1.0 - (delta / TIME_WINDOW_SECONDS)


def pair_score(left, right):
    """Return the raw deterministic link score for two entries (>= 0)."""
    if not isinstance(left, dict) or not isinstance(right, dict):
        return 0.0
    entity = _jaccard(_entities(left), _entities(right))
    key_left, key_right = _event_key(left), _event_key(right)
    event = 1.0 if key_left and key_left == key_right else 0.0
    tag = _jaccard(_tags(left), _tags(right))
    return round(W_ENTITY * entity + W_EVENT * event
                 + W_TIME * _time_score(left, right) + W_TAG * tag, 6)


def build_links(entries):
    """Return {id: [related_ids]} with <= MAX_LINKS links per entry."""
    try:
        items = list(entries or [])
    except TypeError:
        return {}
    rows, seen = [], set()
    for entry in items:
        if not isinstance(entry, dict) and hasattr(entry, "to_dict"):
            try:
                entry = entry.to_dict()
            except Exception:
                continue
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id") or entry.get("memory_id") or "")
        if not entry_id or entry_id in seen:
            continue
        seen.add(entry_id)
        rows.append((entry_id, entry))
    pairs = []
    for index, (left_id, left) in enumerate(rows):
        for right_id, right in rows[index + 1:]:
            score = pair_score(left, right)
            if score >= MIN_LINK_SCORE:
                pairs.append((score, left_id, right_id))
    pairs.sort(key=lambda row: (-row[0], row[1], row[2]))
    links = {entry_id: [] for entry_id, _ in rows}
    for score, left_id, right_id in pairs:
        if len(links[left_id]) >= MAX_LINKS or len(links[right_id]) >= MAX_LINKS:
            continue
        links[left_id].append(right_id)
        links[right_id].append(left_id)
    return {key: links[key] for key in sorted(links) if links[key]}


__all__ = ["enabled", "GRAPH_ENABLED", "build_links", "pair_score",
           "MAX_LINKS", "TIME_WINDOW_SECONDS", "MIN_LINK_SCORE"]
