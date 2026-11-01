# -*- coding: utf-8 -*-
"""P1-3 need-event hooks: events move needs, needs bias behaviour.

Until now the four needs (belonging / self_esteem / control /
meaningful_existence) only drifted back to baseline with time. This module adds
a deterministic event hook: structured events (judged by the model's dims, not
by a word table) add bounded per-event deltas, and the resulting deficits bias
the next expression (approach / assert / clarify / share).

Pure functions only: dicts in, dicts out; no IO, no clock, no main import, no
prompt text.
"""
from __future__ import annotations

NEED_KEYS = ("belonging", "self_esteem", "control", "meaningful_existence")
DEFAULT_NEEDS = {key: 0.6 for key in NEED_KEYS}
BASELINE = 0.6
MAX_EVENTS = 6
CAPS = {"belonging": 0.05, "self_esteem": 0.05, "control": 0.05,
        "meaningful_existence": 0.04}

EVENT_EFFECTS = {
    "praised": {"self_esteem": 0.05, "belonging": 0.02},
    "rejected": {"belonging": -0.05, "self_esteem": -0.04},
    "ignored": {"belonging": -0.04, "control": -0.02,
                "meaningful_existence": -0.03},
    "connected": {"belonging": 0.04, "meaningful_existence": 0.02},
    "achieved": {"self_esteem": 0.04, "control": 0.04,
                 "meaningful_existence": 0.02},
    "dismissed": {"self_esteem": -0.04, "control": -0.04},
    "criticized": {"self_esteem": -0.05, "belonging": -0.02},
    "abandoned": {"belonging": -0.05, "meaningful_existence": -0.03},
}
EVENT_KINDS = tuple(EVENT_EFFECTS)


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return float(default)
    if number != number:
        return float(default)
    return number


def _clamp(value, low, high):
    return max(low, min(high, _num(value, 0.0)))


def needs_state(needs):
    """Clamped need dict; missing needs use the 0.6 baseline."""
    data = needs if isinstance(needs, dict) else {}
    return {key: round(_clamp(data.get(key, BASELINE), 0.0, 1.0), 4)
            for key in NEED_KEYS}


def events_from_dims(dims):
    """Structured need events judged from the probe's numeric dims."""
    data = dims if isinstance(dims, dict) else {}

    def _d(key):
        return _clamp(data.get(key, 0.0), 0.0, 1.0)

    events = []
    goal, blame, hit = _d("goal"), _d("blame"), _d("hit")
    involve, control = _d("involve"), _d("control")
    if goal >= 0.4:
        events.append({"kind": "achieved", "strength": round(goal, 3)})
    if hit >= 0.6:
        events.append({"kind": "rejected", "strength": round(hit, 3)})
    elif blame >= 0.5:
        events.append({"kind": "criticized", "strength": round(blame, 3)})
    if involve >= 0.6:
        events.append({"kind": "connected", "strength": round(involve, 3)})
    if control >= 0.6:
        events.append({"kind": "achieved", "strength": round(control, 3)})
    return events[:MAX_EVENTS]


def apply(needs, events, scale=1.0):
    """Apply structured events to the needs; returns (needs, report)."""
    current = needs_state(needs)
    factor = _clamp(scale, 0.0, 4.0)
    deltas = {key: 0.0 for key in NEED_KEYS}
    applied = []
    for event in (events or [])[:MAX_EVENTS]:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("kind") or "").strip().lower()
        effects = EVENT_EFFECTS.get(kind)
        if not effects:
            continue
        strength = _clamp(event.get("strength", 1.0), 0.0, 1.0)
        if strength <= 0:
            continue
        for key, value in effects.items():
            if key not in deltas:
                continue
            cap = CAPS[key]
            deltas[key] = max(-cap, min(cap,
                                        deltas[key] + value * strength * factor))
        applied.append({"kind": kind, "strength": round(strength, 3)})
    after = {}
    for key in NEED_KEYS:
        after[key] = round(_clamp(current[key] + deltas[key], 0.0, 1.0), 4)
    return after, {"deltas": {k: round(v, 4) for k, v in deltas.items()},
                   "events": applied, "scale": round(factor, 3)}


def behavior_bias(needs, baseline=BASELINE):
    """Need deficits -> 0..1 behavioural biases (expression/inclination)."""
    state = needs_state(needs)
    base = _clamp(baseline, 0.0, 1.0)

    def deficit(key):
        return max(0.0, base - state[key])

    def surplus(key):
        return max(0.0, state[key] - base)

    return {
        "seek_contact": round(_clamp(3.0 * deficit("belonging"), 0.0, 1.0), 3),
        "self_assert": round(_clamp(2.0 * surplus("self_esteem")
                                    + 1.5 * deficit("control"), 0.0, 1.0), 3),
        "ask_clarify": round(_clamp(2.0 * deficit("control")
                                    + 1.0 * deficit("meaningful_existence"),
                                    0.0, 1.0), 3),
        "share_meaning": round(_clamp(2.5 * surplus("meaningful_existence"),
                                      0.0, 1.0), 3),
    }


def summary(needs):
    """Bounded row for logs/panel."""
    state = needs_state(needs)
    return {"needs": state, "behavior": behavior_bias(state)}
