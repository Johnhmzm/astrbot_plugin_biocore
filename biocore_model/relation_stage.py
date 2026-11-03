# -*- coding: utf-8 -*-
"""Relationship stage: from 熟 to 亲近, with the action that fits each stage.

Four inputs move the stage: cumulative interaction, self-disclosure, conflict
repair, and time known. Conflict subtracts. A light social-comparison term
keeps the picture fair: if one side is investing much more, the stage moves
slower and the action becomes more tentative.

Stages and actions:

  陌生 -> 试探    熟悉 -> 靠近    亲近 -> 稳定    稳定 -> 守成

Pure functions only: no IO, no host imports, no LLM calls.
"""
from __future__ import annotations

import math

STAGES = ("陌生", "熟悉", "亲近", "稳定")
ACTIONS = {"陌生": "试探", "熟悉": "靠近", "亲近": "稳定", "稳定": "守成"}
THRESHOLDS = (0.30, 0.60, 0.85)
INTERACTION_FULL = 50.0
DISCLOSURE_FULL = 12.0
REPAIR_FULL = 3.0
AGE_FULL_DAYS = 180.0


def _num(value, default=0.0):
    try:
        num = float(value)
    except Exception:
        return default
    if num != num:
        return default
    return num


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _num(value, low)))


def _ratio_part(count, full):
    count = max(0.0, _num(count))
    full = max(1.0, _num(full, 1.0))
    return min(1.0, math.log1p(count) / math.log1p(full))


def comparison(fairness_inputs=None):
    """0.5 = balanced; >0.5 means he invests more than she does."""
    data = fairness_inputs if isinstance(fairness_inputs, dict) else {}
    his = max(0.0, _num(data.get("his_investment", 0.5)))
    hers = max(0.0, _num(data.get("hers_investment", 0.5)))
    total = his + hers
    if total <= 0:
        return {"his": 0.0, "hers": 0.0, "share": 0.5, "balance": 0.0}
    share = his / total
    return {"his": round(his, 3), "hers": round(hers, 3),
            "share": round(share, 3), "balance": round(abs(share - 0.5) * 2, 3)}


def progress(state=None):
    """Stage progress in 0-1 from the raw counters."""
    state = state if isinstance(state, dict) else {}
    if not any(_num(state.get(key)) > 0 for key in
               ("interactions", "disclosures", "repairs", "days_known")):
        return 0.0
    interactions = _ratio_part(state.get("interactions", 0), INTERACTION_FULL)
    disclosures = _ratio_part(state.get("disclosures", 0), DISCLOSURE_FULL)
    repairs = _ratio_part(state.get("repairs", 0), REPAIR_FULL)
    age = _ratio_part(state.get("days_known", 0), AGE_FULL_DAYS)
    conflict = _clamp(state.get("conflict", 0.0))
    share = comparison(state.get("social_comparison")).get("share", 0.5)
    fairness = 1.0 - abs(share - 0.5) * 2
    raw = (0.34 * interactions + 0.30 * disclosures + 0.14 * repairs
           + 0.12 * age + 0.10 * fairness - 0.30 * conflict)
    return round(_clamp(raw), 3)


def stage_of(value):
    if value < THRESHOLDS[0]:
        return STAGES[0]
    if value < THRESHOLDS[1]:
        return STAGES[1]
    if value < THRESHOLDS[2]:
        return STAGES[2]
    return STAGES[3]


def evaluate(state=None, flags=None):
    """Stage, action and the numbers behind them."""
    flags = flags if isinstance(flags, dict) else {}
    enabled = bool(flags.get("enabled", True))
    state = state if isinstance(state, dict) else {}
    value = progress(state)
    stage = stage_of(value)
    compare = comparison(state.get("social_comparison"))
    tentative = compare["balance"] >= 0.5
    action = ACTIONS[stage]
    if tentative and stage in ("熟悉", "亲近"):
        action = "放着"
    if not enabled:
        return {"enabled": False, "stage": STAGES[0], "action": ACTIONS[STAGES[0]],
                "progress": 0.0, "comparison": compare, "tentative": False}
    return {
        "enabled": True,
        "stage": stage,
        "action": action,
        "progress": value,
        "next_threshold": next((th for th in THRESHOLDS if value < th), 1.0),
        "comparison": compare,
        "tentative": tentative,
    }


def directives(result):
    """Bounded hints for the expression layer (no prompt text)."""
    if not isinstance(result, dict) or not result.get("enabled", True):
        return {"tone": "", "length_scale": 1.0, "stage": STAGES[0]}
    stage = result.get("stage") or STAGES[0]
    table = {
        "陌生": ("客气一点，别太熟", 0.9),
        "熟悉": ("可以多问一句", 1.0),
        "亲近": ("可以主动，话可以软", 1.05),
        "稳定": ("照旧就好", 1.0),
    }
    tone, scale = table.get(stage, table["陌生"])
    if result.get("tentative"):
        tone = tone + "；对方投入不对等，先别急着推进"
        scale = min(scale, 1.0)
    return {"tone": tone, "length_scale": scale, "stage": stage}
