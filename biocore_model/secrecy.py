# -*- coding: utf-8 -*-
"""P1 secrecy: knowing something and choosing whether to say it.

A secret is not just information; it is information plus a disclosure decision.
Three things decide that decision:

  * how sensitive the item is (raises the bar),
  * how deep the relationship is (lowers the bar, and makes a softened version
    possible),
  * how safe the current setting is (public / group / private).

The output is one of tell / withhold / reframe (say a softened, partial
version).  Withholding is not free: every suppressed item leaves a cumulative
pressure trace that the panel can read, and even a reframe costs a little
because part of the truth still has to be held back.

Pure functions only: numbers in, decision out.  No IO, no clock, no LLM, no
prompt text, and it never imports main.py.
"""
from __future__ import annotations

ACTIONS = ("tell", "withhold", "reframe")
HIDE_PRESSURE = 0.12
REFRAME_DISCOUNT = 0.50
PRESSURE_DECAY_PER_HOUR = 0.02
CONTAINED_PRESSURE = 0.60


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


def tell_score(sensitivity, relation, setting_safety):
    """Low sensitivity, close relationship and a safe setting favour telling."""
    s = _clamp01(sensitivity)
    r = _clamp01(relation)
    safe = _clamp01(setting_safety)
    return round(_clamp01((1.0 - 0.70 * s)
                          * (0.25 + 0.75 * r)
                          * (0.20 + 0.80 * safe)), 4)


def reframe_score(sensitivity, relation, setting_safety):
    """High sensitivity plus a close relationship favours a softened version."""
    s = _clamp01(sensitivity)
    r = _clamp01(relation)
    safe = _clamp01(setting_safety)
    return round(_clamp01(s * r * (0.55 + 0.45 * safe) * 0.90), 4)


def withhold_score(sensitivity, relation, setting_safety):
    """High sensitivity, shallow relationship and an unsafe setting withhold."""
    s = _clamp01(sensitivity)
    r = _clamp01(relation)
    safe = _clamp01(setting_safety)
    return round(_clamp01(s * (1.0 - 0.65 * r) * (1.0 - 0.60 * safe)), 4)


def hidden_cost(action, sensitivity, relation):
    """Pressure added by keeping this item hidden (reframe holds back less)."""
    action = str(action or "")
    if action == "tell":
        return 0.0
    base = HIDE_PRESSURE * _clamp01(sensitivity) * (0.40 + 0.60 * _clamp01(relation))
    if action == "reframe":
        base *= REFRAME_DISCOUNT
    return round(max(0.0, base), 4)


def decide(sensitivity, relation, setting_safety):
    """One disclosure decision with scores, confidence and its pressure price."""
    scores = {
        "tell": tell_score(sensitivity, relation, setting_safety),
        "reframe": reframe_score(sensitivity, relation, setting_safety),
        "withhold": withhold_score(sensitivity, relation, setting_safety),
    }
    ranked = sorted(ACTIONS, key=lambda name: (-scores[name], ACTIONS.index(name)))
    action = ranked[0]
    second = scores[ranked[1]] if len(ranked) > 1 else 0.0
    return {
        "action": action,
        "scores": scores,
        "confidence": round(max(0.0, scores[action] - second), 4),
        "pressure_add": hidden_cost(action, sensitivity, relation),
    }


def initial(now=0.0):
    return {
        "pressure": 0.0,
        "withholds": 0,
        "last_action": "",
        "last_pressure_add": 0.0,
        "last_ts": float(now),
    }


def update(secrecy_state, sensitivity, relation, setting_safety,
           now=0.0, decay_per_hour=PRESSURE_DECAY_PER_HOUR):
    """Apply one disclosure decision; stale turns are not double counted."""
    data = dict(secrecy_state or initial(now))
    last = float(data.get("last_ts", 0.0) or 0.0)
    if data.get("last_action") and float(now) <= last:
        return data
    hours = max(0.0, (float(now) - last) / 3600.0) if last > 0.0 else 0.0
    rate = _num(decay_per_hour, PRESSURE_DECAY_PER_HOUR)
    pressure = max(0.0, float(data.get("pressure", 0.0) or 0.0) - rate * hours)
    result = decide(sensitivity, relation, setting_safety)
    pressure = _clamp01(pressure + result["pressure_add"])
    data["pressure"] = round(pressure, 4)
    data["last_action"] = result["action"]
    data["last_pressure_add"] = result["pressure_add"]
    if result["action"] in ("withhold", "reframe"):
        data["withholds"] = int(data.get("withholds", 0) or 0) + 1
    data["last_ts"] = float(now)
    return data


def contained(secrecy_state):
    """True while the accumulated pressure is still held below the line."""
    data = secrecy_state if isinstance(secrecy_state, dict) else {}
    return _clamp01(data.get("pressure", 0.0)) < CONTAINED_PRESSURE


def view(secrecy_state):
    """Panel / debug read (no prompt text)."""
    data = secrecy_state if isinstance(secrecy_state, dict) else {}
    return {
        "pressure": round(_clamp01(data.get("pressure", 0.0)), 4),
        "contained": contained(data),
        "withholds": int(data.get("withholds", 0) or 0),
        "last_action": str(data.get("last_action") or ""),
        "last_pressure_add": round(
            _clamp01(data.get("last_pressure_add", 0.0)), 4),
    }
