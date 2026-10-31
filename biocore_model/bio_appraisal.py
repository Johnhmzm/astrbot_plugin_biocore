# -*- coding: utf-8 -*-
"""L0: appraisal + emotion differentiation (single source, ARCH-1)."""
from __future__ import annotations

DIMS = ("relevance", "goal_congruence", "ego_involvement", "coping_potential", "norm_compatibility")


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def appraisal(goal_congruence=0.0, ego_involvement=0.5, coping_potential=0.5,
              norm_compatibility=0.5, relevance=0.5):
    return {"relevance": round(clamp(relevance), 3),
            "goal_congruence": round(max(-1.0, min(1.0, float(goal_congruence))), 3),
            "ego_involvement": round(clamp(ego_involvement), 3),
            "coping_potential": round(clamp(coping_potential), 3),
            "norm_compatibility": round(clamp(norm_compatibility), 3)}


def appraise(goal_congruence=0.0, ego_involvement=0.5, coping_potential=0.5,
             norm_compatibility=0.5, relevance=0.5):
    data = appraisal(goal_congruence, ego_involvement, coping_potential, norm_compatibility, relevance)
    positive = data["goal_congruence"] >= 0
    high_ego = data["ego_involvement"] >= 0.5
    low_cope = data["coping_potential"] < 0.5
    low_norm = data["norm_compatibility"] < 0.5
    if positive and high_ego:
        emotion = "joy"
    elif positive:
        emotion = "neutral"
    elif high_ego and low_cope:
        emotion = "anxiety"
    elif high_ego and low_norm:
        emotion = "anger"
    else:
        emotion = "sadness"
    return {"appraisal": data, "emotion": emotion,
            "intensity": round(clamp(data["ego_involvement"] * clamp(data["relevance"])), 3)}


def from_snapshot(snapshot):
    data = snapshot if isinstance(snapshot, dict) else {}
    existing = data.get("appraisal") if isinstance(data.get("appraisal"), dict) else {}
    if existing and all(key in existing for key in DIMS):
        return dict(existing)
    return appraisal(data.get("goal_congruence", 0.0), data.get("ego_involvement", 0.5),
                     data.get("coping_potential", 0.5), data.get("norm_compatibility", 0.5),
                     data.get("relevance", 0.5))
