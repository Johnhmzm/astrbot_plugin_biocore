# -*- coding: utf-8 -*-
"""MemoryOS-style heat score (pure; default OFF)."""
from __future__ import annotations

import math
import time

from ..core.util import clamp01

HEAT_ENABLED = False
ALPHA = 1.0
BETA = 1.0
GAMMA = 1.0
TAU_HOURS = 24.0


def _num(entry, keys):
    for key in keys:
        try:
            value = float(entry.get(key) or 0.0)
            return max(0.0, value)
        except Exception:
            continue
    return 0.0


def _last_ts(entry):
    for key in ("last_recall", "last_access", "last_visit_time", "ts", "created_ts"):
        try:
            value = float(entry.get(key) or 0.0)
            if value > 0:
                return value
        except Exception:
            continue
    return 0.0


def heat(entry, now=None):
    """heat = alpha*visits + beta*interactions + gamma*recency, normalized 0..1."""
    if not HEAT_ENABLED or not isinstance(entry, dict):
        return 0.0
    try:
        stamp = float(now if now is not None else time.time())
        visits = _num(entry, ("visits", "visit_count", "N_visit", "hits"))
        interactions = _num(entry, ("interactions", "interaction_count", "L_interaction"))
        last = _last_ts(entry)
        age_hours = max(0.0, stamp - last) / 3600.0 if last else 0.0
        recency = 0.5 ** (age_hours / TAU_HOURS)
        v = visits / (1.0 + visits)
        i = interactions / (1.0 + interactions)
        total = ALPHA + BETA + GAMMA
        return clamp01((ALPHA * v + BETA * i + GAMMA * recency) / total, 0.0)
    except Exception:
        return 0.0
