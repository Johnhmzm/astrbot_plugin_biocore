# -*- coding: utf-8 -*-
"""0.6/0.4 fusion + 0.55/0.35 tiers."""
from __future__ import annotations
from ..core.config import (CUE_WEIGHT, HIGH_TIER, IMPORTANCE_WEIGHT, MID_TIER,
                           SEM_WEIGHT, TIME_BONUS)


def fuse(channels):
    c = channels if isinstance(channels, dict) else {}
    cue = float(c.get("cue", 0.0) or 0.0)
    sem = float(c.get("semantic", 0.0) or 0.0)
    time_score = float(c.get("time", 0.0) or 0.0)
    imp = float(c.get("importance", 0.0) or 0.0)
    score = (CUE_WEIGHT * cue + SEM_WEIGHT * sem
             + IMPORTANCE_WEIGHT * imp + TIME_BONUS * time_score)
    score = max(0.0, min(1.0, score))
    tier = "high" if score >= HIGH_TIER else "medium" if score >= MID_TIER else "low"
    return round(score, 6), tier