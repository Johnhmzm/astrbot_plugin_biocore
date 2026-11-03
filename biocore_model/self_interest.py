# -*- coding: utf-8 -*-
"""P1 self-interest accounting (task-147 core): every option has a her-side price.

Instead of only predicting the user, she runs her own small books.  For each
candidate action this module computes two payoff columns and one cost:

  * self_gain  - what the action does for HER: need gaps (belonging /
                 self-esteem / control / meaningful existence), interoception
                 (fatigue wants rest), and the value order she holds;
  * other_gain - what the action does for HIM, including how tired / stressed
                 he looks;
  * cost       - affective-labour and relational price of the action.

A single SVO-style self_weight decides how the two columns are combined.  The
winning option is chosen by
    utility = self_weight * self_gain + (1 - self_weight) * other_gain
              - COST_WEIGHT * cost
with a deterministic tie-break in ACTIONS order.

Literature: Rilling & Sanfey 2011 (SVO), Carver & Scheier 1998 (control),
Hochschild 1983 / Grandey 2000 (affective labour), Ryan & Deci 2000 (needs).
Pure functions only: no IO, no clock, no LLM, no prompt text, never imports
main.py.  The module can be switched off.
"""
from __future__ import annotations

ACTIONS = ("要你陪", "自己待着", "拒绝话题", "顺着你", "说真话")
NEED_KEYS = ("belonging", "self_esteem", "control", "meaningful_existence")
VALUE_KEYS = ("closeness", "honesty", "autonomy", "growth")
DEFAULT_NEEDS = {key: 0.5 for key in NEED_KEYS}
DEFAULT_VALUES = {key: 0.5 for key in VALUE_KEYS}
DEFAULT_CONFIG = {"enabled": True, "self_weight": None}
COST_WEIGHT = 0.60
SELF_WEIGHT_MIN = 0.10
SELF_WEIGHT_MAX = 0.90
REASONS = {
    "要你陪": "想有人陪一会儿",
    "自己待着": "累了，想安静一会儿",
    "拒绝话题": "这个话题不想接",
    "顺着你": "先顺着他，别起冲突",
    "说真话": "不想绕，想把真话说出来",
}


def _num(value, default=0.0):
    try:
        num = float(value)
    except Exception:
        return float(default)
    if num != num or num in (float("inf"), float("-inf")):
        return float(default)
    return num


def _clamp01(value, default=0.0):
    return max(0.0, min(1.0, _num(value, default)))


def _bounded(value, low, high, default=0.0):
    return max(low, min(high, _num(value, default)))


def _config(config):
    cfg = dict(DEFAULT_CONFIG)
    if isinstance(config, bool):
        cfg["enabled"] = config
        return cfg
    if isinstance(config, dict):
        cfg["enabled"] = bool(config.get("enabled", True))
        weight = config.get("self_weight")
        if weight is not None:
            cfg["self_weight"] = _bounded(
                weight, SELF_WEIGHT_MIN, SELF_WEIGHT_MAX, 0.5)
    return cfg


def _context(context):
    return context if isinstance(context, dict) else {}


def needs_state(context):
    context = _context(context)
    raw = context.get("needs") if isinstance(context.get("needs"), dict) else {}
    return {key: _clamp01(raw.get(key, DEFAULT_NEEDS[key]), DEFAULT_NEEDS[key])
            for key in NEED_KEYS}


def values_state(context):
    context = _context(context)
    raw = context.get("values") if isinstance(context.get("values"), dict) else {}
    return {key: _clamp01(raw.get(key, DEFAULT_VALUES[key]), DEFAULT_VALUES[key])
            for key in VALUE_KEYS}


def state_values(context):
    context = _context(context)
    energy = _clamp01(context.get("energy", 0.60), 0.60)
    return {
        "energy": energy,
        "fatigue": _clamp01(context.get("fatigue", 1.0 - energy),
                            1.0 - energy),
        "stress": _clamp01(context.get("stress", 0.30), 0.30),
        "closeness": _clamp01(context.get("closeness", 0.50), 0.50),
        "trust": _clamp01(context.get("trust", 0.50), 0.50),
        "other_stress": _clamp01(context.get("other_stress", 0.30), 0.30),
        "other_energy": _clamp01(context.get("other_energy", 0.60), 0.60),
    }


def self_weight(context):
    """SVO-style weight on her own payoff, 0.1..0.9 (explicit override wins)."""
    context = _context(context)
    explicit = context.get("self_weight")
    if explicit is not None:
        return round(_bounded(explicit, SELF_WEIGHT_MIN, SELF_WEIGHT_MAX,
                              0.5), 4)
    needs = needs_state(context)
    state = state_values(context)
    own_gap = sum(1.0 - needs[key] for key in NEED_KEYS) / float(
        len(NEED_KEYS))
    weight = (0.35 + 0.40 * own_gap
              - 0.20 * state["closeness"]
              - 0.10 * state["trust"]
              + 0.20 * state["stress"])
    return round(_bounded(weight, SELF_WEIGHT_MIN, SELF_WEIGHT_MAX, 0.5), 4)


def action_scores(context):
    """Raw two-column table for all candidate actions."""
    needs = needs_state(context)
    values = values_state(context)
    state = state_values(context)
    gb = 1.0 - needs["belonging"]
    ge = 1.0 - needs["self_esteem"]
    gc = 1.0 - needs["control"]
    gm = 1.0 - needs["meaningful_existence"]
    vc = values["closeness"]
    vh = values["honesty"]
    va = values["autonomy"]
    vg = values["growth"]
    fatigue = state["fatigue"]
    stress = state["stress"]
    closeness = state["closeness"]
    other_stress = state["other_stress"]
    other_fatigue = 1.0 - state["other_energy"]
    rows = {
        "要你陪": {
            "self_gain": (0.60 * gb + 0.20 * ge + 0.20 * vc
                          - 0.20 * fatigue),
            "other_gain": (0.25 * vc + 0.20 * closeness
                           - 0.35 * other_stress - 0.20 * other_fatigue),
            "cost": 0.10 + 0.20 * (1.0 - closeness),
        },
        "自己待着": {
            "self_gain": 0.50 * fatigue + 0.25 * gc + 0.25 * va,
            "other_gain": (0.30 * other_stress + 0.20 * other_fatigue
                           - 0.20 * closeness),
            "cost": 0.05 + 0.15 * (1.0 - fatigue),
        },
        "拒绝话题": {
            "self_gain": (0.45 * gc + 0.25 * va + 0.20 * stress
                          + 0.10 * ge),
            "other_gain": (0.15 * (1.0 - closeness) - 0.50 * closeness
                           - 0.20 * vc),
            "cost": (0.10 + 0.20 * closeness + 0.20 * stress
                     + 0.10 * vh),
        },
        "顺着你": {
            "self_gain": (0.25 * gb + 0.15 * ge - 0.35 * va
                          - 0.30 * vh - 0.20 * fatigue),
            "other_gain": (0.45 * closeness + 0.25 * vc
                           + 0.20 * (1.0 - other_stress)),
            "cost": (0.25 + 0.30 * vh + 0.20 * va
                     + 0.20 * fatigue),
        },
        "说真话": {
            "self_gain": (0.35 * vh + 0.25 * ge + 0.20 * va
                          + 0.15 * gm + 0.10 * vg - 0.20 * stress),
            "other_gain": (0.25 * vh + 0.15 * (1.0 - other_stress)
                           - 0.25 * (1.0 - closeness)
                           - 0.10 * other_fatigue),
            "cost": (0.15 * stress + 0.15 * (1.0 - closeness)
                     + 0.10 * (1.0 - vh)),
        },
    }
    out = {}
    for action in ACTIONS:
        row = rows[action]
        out[action] = {
            "action": action,
            "self_gain": round(_bounded(row["self_gain"], -1.0, 1.0), 4),
            "other_gain": round(_bounded(row["other_gain"], -1.0, 1.0), 4),
            "cost": round(_clamp01(row["cost"]), 4),
            "reason": REASONS[action],
        }
    return out


def assess(context, config=None):
    """One turn of self-interest accounting: options with two payoff columns."""
    cfg = _config(config)
    result = {
        "enabled": bool(cfg["enabled"]),
        "self_weight": 0.5,
        "options": [],
        "chosen": "",
        "reason": "",
    }
    if not result["enabled"]:
        result["reason"] = "关闭"
        return result
    weight = (cfg["self_weight"] if cfg["self_weight"] is not None
              else self_weight(context))
    table = action_scores(context)
    best_action = ""
    best_utility = None
    options = []
    for action in ACTIONS:
        row = dict(table[action])
        utility = (weight * row["self_gain"]
                   + (1.0 - weight) * row["other_gain"]
                   - COST_WEIGHT * row["cost"])
        row["utility"] = round(_bounded(utility, -2.0, 2.0), 4)
        row["chosen"] = False
        options.append(row)
        if best_utility is None or row["utility"] > best_utility + 1e-12:
            best_action = action
            best_utility = row["utility"]
    for row in options:
        if row["action"] == best_action:
            row["chosen"] = True
            result["chosen"] = best_action
            result["reason"] = row["reason"]
    result["self_weight"] = round(weight, 4)
    result["options"] = options
    return result


def view(result):
    """Panel-friendly subset of one assess() result (no prompt text)."""
    data = result if isinstance(result, dict) else {}
    options = []
    for row in data.get("options") or []:
        if not isinstance(row, dict):
            continue
        options.append({
            "action": str(row.get("action") or ""),
            "self_gain": round(_bounded(row.get("self_gain", 0.0),
                                        -1.0, 1.0), 4),
            "other_gain": round(_bounded(row.get("other_gain", 0.0),
                                         -1.0, 1.0), 4),
            "cost": round(_clamp01(row.get("cost", 0.0)), 4),
            "chosen": bool(row.get("chosen")),
        })
    return {
        "enabled": bool(data.get("enabled", False)),
        "self_weight": round(_bounded(data.get("self_weight", 0.5),
                                      SELF_WEIGHT_MIN, SELF_WEIGHT_MAX,
                                      0.5), 4),
        "options": options,
        "chosen": str(data.get("chosen") or ""),
        "reason": str(data.get("reason") or ""),
    }
