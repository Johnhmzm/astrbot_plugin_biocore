# -*- coding: utf-8 -*-
"""Appraisal (Lazarus/Scherer), action tendencies (Frijda), curiosity gap."""
from __future__ import annotations

try:
    from . import bio_appraisal as _bio_appraisal
except Exception:  # pragma: no cover
    from biocore_model import bio_appraisal as _bio_appraisal

# ARCH-1: appraisal math lives in L0 bio_appraisal; these are compat wrappers.

DIMS = ("relevance", "goal_congruence", "ego_involvement", "coping_potential", "norm_compatibility")


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def appraisal(goal_congruence=0.0, ego_involvement=0.5, coping_potential=0.5,
              norm_compatibility=0.5, relevance=0.5):
    """Compat wrapper -> L0 bio_appraisal.appraisal (ARCH-1)."""
    return _bio_appraisal.appraisal(goal_congruence, ego_involvement,
                                    coping_potential, norm_compatibility, relevance)


def appraise(goal_congruence=0.0, ego_involvement=0.5, coping_potential=0.5,
             norm_compatibility=0.5, relevance=0.5):
    """Compat wrapper -> L0 bio_appraisal.appraise (ARCH-1)."""
    return _bio_appraisal.appraise(goal_congruence, ego_involvement, coping_potential,
                                   norm_compatibility, relevance)


ACTION = {
    "anxiety": {"drive_delta": 0.03, "max_chars_mult": 0.8, "repair_delta": 0.0,
                "tone": "追问、确认、短句", "prompt": "想追问、确认一下"},
    "sadness": {"drive_delta": -0.04, "max_chars_mult": 0.9, "repair_delta": 0.0,
                "tone": "简短、少问、退缩", "prompt": "想安静一点"},
    "anger": {"drive_delta": 0.02, "max_chars_mult": 1.0, "repair_delta": 0.0,
              "tone": "直接质问、少修饰", "prompt": "想直接问清楚"},
    "joy": {"drive_delta": 0.03, "max_chars_mult": 1.2, "repair_delta": 0.0,
            "tone": "分享、主动靠近", "prompt": "想分享、靠近一点"},
    "guilt": {"drive_delta": 0.0, "max_chars_mult": 1.0, "repair_delta": 0.05,
              "tone": "修复、道歉", "prompt": "想修复一下"},
    "neutral": {"drive_delta": 0.0, "max_chars_mult": 1.0, "repair_delta": 0.0,
                "tone": "", "prompt": ""},
}


def action_for(emotion):
    data = dict(ACTION.get(emotion if emotion in ACTION else "neutral"))
    data["emotion"] = emotion if emotion in ACTION else "neutral"
    return data


def curiosity_update(current_gap=0.0, new_topic=False, answered=True, hours=0.0):
    gap = clamp(current_gap)
    if new_topic and not answered:
        gap = clamp(gap + 0.3)
    elif answered:
        gap = clamp(gap * 0.7)
    gap = clamp(gap - 0.05 * max(0.0, float(hours)))
    return round(gap, 4)


def curiosity_effects(gap):
    gap = clamp(gap)
    return {"question_probability_bonus": round(0.3 * gap, 3),
            "drive_delta": round(0.02 * gap, 3)}


def prompt_line(emotion_action=None, curiosity_gap=0.0):
    parts = []
    action = emotion_action or {}
    if action.get("prompt"):
        parts.append("你现在想：" + str(action["prompt"]))
    if curiosity_gap >= 0.3:
        parts.append("你对对方刚提到的事有点好奇")
    return "；".join(parts)
