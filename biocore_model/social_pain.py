# -*- coding: utf-8 -*-
"""BIO-2: relational social pain (Eisenberger 2003/2012). Pure functions."""
from __future__ import annotations

BASE = 0.0
EVENT_DELTAS = {"ignored": 0.05, "rejected": 0.10, "excluded": 0.15,
                "replied": -0.10, "comforted": -0.15}
DECAY_PER_HOUR = 0.02


def clamp(value):
    return max(0.0, min(1.0, float(value)))


def initial(now=0.0):
    return {"value": BASE, "last_event": "", "last_event_ts": float(now),
            "last_decay_ts": float(now), "last_value": BASE}


def update(state, event_type, now):
    data = dict(state or initial(now))
    if float(now) <= float(data.get("last_event_ts", 0.0) or 0.0) and data.get("last_event"):
        return data
    previous = float(data.get("value", BASE))
    delta = EVENT_DELTAS.get(str(event_type or ""), 0.0)
    data["last_value"] = round(previous, 4)
    data["value"] = round(clamp(previous + delta), 4)
    data["last_event"] = str(event_type or "")
    data["last_event_ts"] = float(now)
    return data


def decay(state, now):
    data = dict(state or initial(now))
    last = float(data.get("last_decay_ts", 0.0) or 0.0)
    if last > 0 and float(now) <= last:
        return data
    hours = max(0.0, (float(now) - last) / 3600.0) if last > 0 else 0.0
    value = float(data.get("value", BASE))
    data["last_value"] = round(value, 4)
    data["value"] = round(clamp(value - DECAY_PER_HOUR * hours), 4)
    data["last_decay_ts"] = float(now)
    return data


def trend(state):
    data = dict(state or initial())
    value = float(data.get("value", BASE))
    previous = float(data.get("last_value", value))
    if value > previous + 1e-6:
        return "rising"
    if value < previous - 1e-6:
        return "falling"
    return "flat"


def drive_delta(value):
    return round(0.5 * clamp(value), 4)


def gate_cost(value):
    return round(0.05 * clamp(value), 4)


def view(state):
    data = dict(state or initial())
    return {"value": round(clamp(float(data.get("value", BASE))), 3),
            "last_event": str(data.get("last_event") or ""),
            "trend": trend(data)}
