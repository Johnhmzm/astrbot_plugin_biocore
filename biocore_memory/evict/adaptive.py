# -*- coding: utf-8 -*-
"""Adaptive forgetting rate (default OFF; pure function, no IO).

adaptive_score(base, load, importance) = base * (1 + 0.5*load) * (1 - 0.3*importance)
clamped to 0..1. load and importance are normalized to 0..1.
"""
from __future__ import annotations

ADAPTIVE_ENABLED = False


def _clamp(value):
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0


def adaptive_score(base, load=0.0, importance=0.0):
    """Return the bounded adaptive eviction score (higher = evict earlier)."""
    b = _clamp(base)
    l = _clamp(load)
    i = _clamp(importance)
    return round(_clamp(b * (1.0 + 0.5 * l) * (1.0 - 0.3 * i)), 6)


def _base_of(entry, base_scores):
    if isinstance(base_scores, dict):
        try:
            return float(base_scores.get(str(entry.get("id") or "")) or 0.0)
        except Exception:
            return 0.0
    for key in ("evict_score", "score", "base_score"):
        if key in entry:
            try:
                return float(entry.get(key) or 0.0)
            except Exception:
                return 0.0
    return 0.0


def _load_of(entry, load):
    if load is not None:
        return _clamp(load)
    for key in ("load", "pressure", "allostatic_load"):
        if key in entry:
            return _clamp(entry.get(key))
    return 0.0


def rank(entries, base_scores=None, load=None):
    """Return [(id, score)] ordered by adaptive score descending (evict-first)."""
    rows = [e for e in (entries or []) if isinstance(e, dict)]
    if not ADAPTIVE_ENABLED:
        out = [(str(e.get("id") or ""), _clamp(_base_of(e, base_scores))) for e in rows]
        out.sort(key=lambda x: (-x[1], x[0]))
        return out
    scored = []
    for entry in rows:
        score = adaptive_score(_base_of(entry, base_scores),
                               _load_of(entry, load), entry.get("importance", 0.0))
        scored.append((str(entry.get("id") or ""), score))
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored


def select(entries, budget, base_scores=None, load=None):
    """Return ids of the top-budget entries by adaptive eviction score."""
    try:
        limit = max(0, int(budget or 0))
    except Exception:
        limit = 0
    return [eid for eid, _score in rank(entries, base_scores, load)[:limit]]
