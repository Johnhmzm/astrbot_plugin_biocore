# -*- coding: utf-8 -*-
"""Read-only eviction score (never deletes by itself)."""
from __future__ import annotations
from ..core.config import (EVICT_W_CONFIDENCE, EVICT_W_POSITION,
                           EVICT_W_REDUNDANCY, EVICT_W_SALIENCE,
                           EVICT_W_STALENESS)
from ..core.util import clamp01


def eviction_score(entry, now=0.0, position=0.5, redundancy=0.0):
    e = entry if isinstance(entry, dict) else {}
    salience = clamp01(e.get("importance"), 0.5)
    pos = clamp01(position, 0.5)
    red = clamp01(redundancy, 0.0)
    conf = clamp01(e.get("memory_confidence"), 0.5)
    try:
        age = max(0.0, float(now or 0.0) - float(e.get("last_recall", e.get("ts", 0.0)) or 0.0))
    except Exception:
        age = 0.0
    stale = min(1.0, age / 86400.0 / 30.0) if now else 0.0
    return round(EVICT_W_SALIENCE * salience + EVICT_W_POSITION * pos
                 + EVICT_W_REDUNDANCY * red
                 + EVICT_W_CONFIDENCE * conf + EVICT_W_STALENESS * stale, 4)
