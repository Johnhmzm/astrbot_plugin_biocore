# -*- coding: utf-8 -*-
"""BIO-1: state self-esteem as a pure biological-layer module.

No IO, no globals: state in -> new state out. main.py only calls these.
"""
from __future__ import annotations

BASELINE = 0.55
REGRESS = 0.05
EVENT_DELTAS = {"praised": 0.06, "replied": 0.06, "ignored": -0.05, "insulted": -0.05}


def clamp(value):
    return max(0.0, min(1.0, float(value)))


def initial(now=0.0):
    return {"value": BASELINE, "baseline": BASELINE,
            "last_event": "", "last_event_ts": float(now), "last_decay_ts": float(now)}


def update(state, event_type, now):
    data = dict(state or initial(now))
    delta = EVENT_DELTAS.get(str(event_type or ""), 0.0)
    data["value"] = round(clamp(float(data.get("value", BASELINE)) + delta), 4)
    data["last_event"] = str(event_type or "")
    data["last_event_ts"] = float(now)
    return data


def decay(state, now):
    data = dict(state or initial(now))
    last = float(data.get("last_decay_ts", 0.0) or 0.0)
    if last > 0 and float(now) <= last:
        return data
    value = float(data.get("value", BASELINE))
    data["value"] = round(clamp(value + (BASELINE - value) * REGRESS), 4)
    data["last_decay_ts"] = float(now)
    return data


def confidence_delta(value):
    return round(-0.5 * (BASELINE - clamp(value)), 4)


def view(state):
    data = dict(state or initial())
    value = round(clamp(float(data.get("value", BASELINE))), 3)
    return {"value": value, "baseline": BASELINE, "last_event": str(data.get("last_event") or ""),
            "confidence_delta": confidence_delta(value)}
