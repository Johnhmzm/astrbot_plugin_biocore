# -*- coding: utf-8 -*-
"""Entity co-occurrence boost (pure, deterministic; no IO, no LLM).

Module is disabled by default: callers MUST check `enabled` before consuming it.
Entry shapes accepted by build_cooccurrence:
  - {"entities": ["A", "B"]} (preferred), or {"entity": "A"}
  - a list/tuple/set of entity strings
  - a single entity string
Pairs are unordered and stored with the lexicographically smaller entity first.
"""
from __future__ import annotations

import math

enabled = False
ENTITY_BOOST_ENABLED = enabled

MAX_BOOST = 0.2
BOOST_SATURATION = 50.0
ENTITY_CHARS = 64


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _entities_from(entry) -> list:
    if isinstance(entry, dict):
        raw = entry.get("entities")
        if raw is None:
            raw = entry.get("entity")
    elif isinstance(entry, (list, tuple, set)):
        raw = entry
    elif isinstance(entry, str):
        raw = [entry]
    else:
        raw = []
    if isinstance(raw, str):
        raw = [raw]
    try:
        values = list(raw)
    except Exception:
        values = [raw]
    out = []
    seen = set()
    for value in values:
        if isinstance(value, dict):
            value = value.get("id") or value.get("name") or value.get("text") or ""
        text = _clean(value)[:ENTITY_CHARS]
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def build_cooccurrence(entries) -> dict:
    """Build {(entity_a, entity_b): count} over entries (deterministic)."""
    cooc = {}
    if entries is None:
        return cooc
    try:
        rows = list(entries)
    except Exception:
        rows = [entries]
    for entry in rows:
        entities = _entities_from(entry)
        for i in range(len(entities)):
            for j in range(i + 1, len(entities)):
                a, b = entities[i], entities[j]
                key = (a, b) if a <= b else (b, a)
                cooc[key] = int(cooc.get(key, 0) or 0) + 1
    return cooc


def boost(entity, cooc) -> float:
    """Return a bounded 0..0.2 boost for one entity, log-scaled by co-occurrence.

    total = sum of counts of all pairs containing entity; 0 => 0.0.
    value = min(0.2, 0.2 * log1p(total) / log1p(50)); deterministic and bounded.
    """
    name = _clean(entity)[:ENTITY_CHARS]
    if not name or not isinstance(cooc, dict):
        return 0.0
    total = 0
    for pair, count in cooc.items():
        try:
            a, b = pair
        except Exception:
            continue
        if str(a) != name and str(b) != name:
            continue
        try:
            total += max(0, int(count or 0))
        except Exception:
            continue
    if total <= 0:
        return 0.0
    value = MAX_BOOST * math.log1p(total) / math.log1p(BOOST_SATURATION)
    return round(max(0.0, min(MAX_BOOST, value)), 6)


__all__ = ["enabled", "ENTITY_BOOST_ENABLED", "build_cooccurrence", "boost",
           "MAX_BOOST", "BOOST_SATURATION"]
