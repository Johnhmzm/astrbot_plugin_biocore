# -*- coding: utf-8 -*-
"""Hot/warm/cold memory tiering (pure; default OFF)."""
from __future__ import annotations

import time

TIERING_ENABLED = False
HOT_BUDGET = 80
WARM_BUDGET = 200
TIER_UNLIMITED = 10 ** 9
HOT_AGE_SECONDS = 24 * 3600
WARM_AGE_SECONDS = 30 * 86400
HOT_IMPORTANCE = 0.80
HOT_HITS = 5


def _num(entry, keys, default=0.0):
    for key in keys:
        try:
            value = float(entry.get(key) or 0.0)
            return value
        except Exception:
            continue
    return default


def _age(entry, now):
    last = 0.0
    for key in ("last_recall", "last_access", "ts", "created_ts"):
        last = max(last, _num(entry, (key,), 0.0))
    if last <= 0:
        return float("inf")
    return max(0.0, float(now) - last)


def tier_of(entry, now=None):
    """Return 'hot' | 'warm' | 'cold'; disabled tiering is neutral ('warm')."""
    if not TIERING_ENABLED or not isinstance(entry, dict):
        return "warm"
    try:
        stamp = float(now if now is not None else time.time())
        age = _age(entry, stamp)
        importance = _num(entry, ("importance",), 0.5)
        hits = _num(entry, ("hits", "visits", "visit_count"), 0.0)
        if age <= HOT_AGE_SECONDS or importance >= HOT_IMPORTANCE or hits >= HOT_HITS:
            return "hot"
        if age <= WARM_AGE_SECONDS or hits >= 2:
            return "warm"
        return "cold"
    except Exception:
        return "warm"


def tier_budget(tier):
    """Capacity budget for a tier: hot 80, warm 200, cold unlimited."""
    value = str(tier or "").lower()
    if value == "hot":
        return HOT_BUDGET
    if value == "warm":
        return WARM_BUDGET
    return TIER_UNLIMITED
