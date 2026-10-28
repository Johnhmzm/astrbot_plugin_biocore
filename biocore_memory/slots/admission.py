# -*- coding: utf-8 -*-
"""Slot admission: slot_score = salience * cue * goal (multiplicative)."""
from __future__ import annotations

from ..core.util import clamp01

THRESHOLD = 0.12
INDEX_ONLY = 0.05
FLOOR_SALIENCE = 0.15
FLOOR_CUE = 0.10
FLOOR_GOAL = 0.05


def _event_vector(entry):
    vector = entry.get("event_vector") if isinstance(entry, dict) else None
    if hasattr(vector, "as_dict"):
        try:
            vector = vector.as_dict()
        except Exception:
            vector = None
    return vector if isinstance(vector, dict) else {}


def salience(entry):
    e = entry if isinstance(entry, dict) else {}
    value = 0.5 * clamp01(e.get("importance"), 0.5)
    value += 0.3 * clamp01(_event_vector(e).get("intensity", e.get("event_intensity", 0.0)))
    value += 0.2 * abs(clamp01(e.get("valence", _event_vector(e).get("valence", 0.0)), 0.0))
    return clamp01(value)


def cue(entry, ctx=None):
    c = ctx if isinstance(ctx, dict) else {}
    for key in ("cue", "cue_score"):
        if key in c:
            return clamp01(c.get(key))
    e = entry if isinstance(entry, dict) else {}
    return clamp01(e.get("cue")) if "cue" in e else 0.0


def goal(entry):
    e = entry if isinstance(entry, dict) else {}
    return clamp01(0.6 * clamp01(e.get("goal_relevance", 0.0))
                   + 0.4 * clamp01(e.get("unresolved", 0.0)))


def slot_score(entry, ctx=None):
    s, c, g = salience(entry), cue(entry, ctx), goal(entry)
    if s < FLOOR_SALIENCE or c < FLOOR_CUE or g < FLOOR_GOAL:
        return 0.0
    return clamp01(s * c * g)


def admission(entry, ctx=None):
    score = slot_score(entry, ctx)
    if score < INDEX_ONLY:
        decision, reason = "index_only", "below_index_only"
    elif score < THRESHOLD:
        decision, reason = "reject", "below_threshold"
    else:
        decision, reason = "admit", "ok"
    return {"score": round(score, 6), "decision": decision, "reason": reason,
            "salience": round(salience(entry), 4),
            "cue": round(cue(entry, ctx), 4), "goal": round(goal(entry), 4)}
