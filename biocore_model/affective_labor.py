# -*- coding: utf-8 -*-
"""P1 affective labor: the price of saying what she does not feel.

Surface acting (Hochschild 1983; Grandey 2000) splits the displayed expression
from the felt state.  The gap between them is the labor: the wider the
deviation, and the more she suppresses it, the more energy one turn costs.
Costs do not vanish; they accumulate into a load with a breakdown threshold
that the panel can read long before the collapse happens.

Inputs are the expression she intends to wear and the state she actually feels
(same six core dimensions: v / a / d / social / trust / stress).  The honesty
knob says how much of the true state leaks into the expression: honesty 1.0
means she says it as it is (no labor), honesty 0.0 means she hides everything.

Pure functions only: state in, numbers out.  No IO, no clock, no LLM, no prompt
text, and it never imports main.py.
"""
from __future__ import annotations

DIMS = ("v", "a", "d", "social", "trust", "stress")
DIM_WEIGHTS = {
    "v": 0.30,
    "a": 0.20,
    "d": 0.15,
    "social": 0.15,
    "trust": 0.10,
    "stress": 0.10,
}
MASK_COST = 0.22  # [engineering] energy cost of surface acting, hand-tuned
LOAD_DECAY_PER_HOUR = 0.03
BREAKDOWN_THRESHOLD = 0.85


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


def _unit(dim, value):
    """Normalize one core dimension to 0..1; None when the input is missing."""
    try:
        num = float(value)
    except Exception:
        return None
    if num != num or num in (float("inf"), float("-inf")):
        return None
    if dim == "v":
        return max(0.0, min(1.0, (num + 1.0) / 2.0))
    return max(0.0, min(1.0, num))


def deviation(expressed, felt):
    """0..1 weighted gap between the expression and the felt state."""
    if not isinstance(expressed, dict) or not isinstance(felt, dict):
        return 0.0
    total = 0.0
    weight_sum = 0.0
    for dim in DIMS:
        if dim not in expressed or dim not in felt:
            continue
        left = _unit(dim, expressed.get(dim))
        right = _unit(dim, felt.get(dim))
        if left is None or right is None:
            continue
        total += DIM_WEIGHTS[dim] * abs(left - right)
        weight_sum += DIM_WEIGHTS[dim]
    if weight_sum <= 0.0:
        return 0.0
    return round(_clamp01(total / weight_sum), 4)


def masking(expressed, felt, honesty=0.0):
    """The part of the gap that is actively hidden; more hiding, more labor."""
    gap = deviation(expressed, felt)
    return round(_clamp01(gap * (1.0 - _clamp01(honesty))), 4)


def energy_cost(mask):
    """Per-turn energy cost of surface acting."""
    return round(MASK_COST * _clamp01(mask), 4)


def turn_cost(expressed, felt, honesty=0.0):
    """Convenience: one turn of surface acting -> energy cost."""
    return energy_cost(masking(expressed, felt, honesty))


def initial(now=0.0):
    return {
        "load": 0.0,
        "last_cost": 0.0,
        "last_masking": 0.0,
        "turns": 0,
        "breakdowns": 0,
        "last_ts": float(now),
    }


def update(labor_state, expressed, felt, honesty=0.0, now=0.0,
           recover_per_hour=LOAD_DECAY_PER_HOUR):
    """Accumulate one turn of labor; stale turns are not double counted."""
    data = dict(labor_state or initial(now))
    last = float(data.get("last_ts", 0.0) or 0.0)
    if int(data.get("turns", 0) or 0) > 0 and float(now) <= last:
        return data
    hours = max(0.0, (float(now) - last) / 3600.0) if last > 0.0 else 0.0
    rate = _num(recover_per_hour, LOAD_DECAY_PER_HOUR)
    load = max(0.0, float(data.get("load", 0.0) or 0.0) - rate * hours)
    mask = masking(expressed, felt, honesty)
    cost = energy_cost(mask)
    before = load
    load = _clamp01(load + cost)
    data["load"] = round(load, 4)
    data["last_cost"] = cost
    # Three components stay separate: a single "cost" hid which one moved.
    data["components"] = {
        "emotional_exhaustion": round(load, 4),
        "depersonalization": round(mask, 4),
        "personal_accomplishment": round(max(0.0, 1.0 - mask), 4),
    }
    data["last_masking"] = mask
    data["turns"] = int(data.get("turns", 0) or 0) + 1
    if load >= BREAKDOWN_THRESHOLD and before < BREAKDOWN_THRESHOLD:
        data["breakdowns"] = int(data.get("breakdowns", 0) or 0) + 1
    data["last_ts"] = float(now)
    return data


def risk(labor_state):
    """Load relative to the breakdown threshold, 0..1."""
    load = _clamp01((labor_state or {}).get("load", 0.0))
    return round(min(1.0, load / BREAKDOWN_THRESHOLD), 4)


def headroom(labor_state):
    """How much more labor fits before the breakdown threshold."""
    load = _clamp01((labor_state or {}).get("load", 0.0))
    return round(max(0.0, BREAKDOWN_THRESHOLD - load), 4)


def collapsed(labor_state):
    load = _clamp01((labor_state or {}).get("load", 0.0))
    return load >= BREAKDOWN_THRESHOLD


def view(labor_state):
    """Panel / debug read (no prompt text)."""
    data = labor_state if isinstance(labor_state, dict) else {}
    return {
        "load": round(_clamp01(data.get("load", 0.0)), 4),
        "threshold": BREAKDOWN_THRESHOLD,
        "risk": risk(data),
        "headroom": headroom(data),
        "collapsed": collapsed(data),
        "last_cost": round(_clamp01(data.get("last_cost", 0.0)), 4),
        "last_masking": round(_clamp01(data.get("last_masking", 0.0)), 4),
        "components": {
            "emotional_exhaustion": round(_clamp01(data.get("load", 0.0)), 4),
            "depersonalization": round(
                _clamp01(data.get("last_masking", 0.0)), 4),
            "personal_accomplishment": round(
                max(0.0, 1.0 - _clamp01(data.get("last_masking", 0.0))), 4),
        },
        "turns": int(data.get("turns", 0) or 0),
        "breakdowns": int(data.get("breakdowns", 0) or 0),
    }
