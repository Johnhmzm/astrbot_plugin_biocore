# -*- coding: utf-8 -*-
"""BIO-5: four needs (Williams 2007) + sleep debt (Borbély 1982). Pure functions."""
from __future__ import annotations

NEED_KEYS = ("belonging", "self_esteem", "control", "meaningful_existence")
BASE_NEED = 0.6
DEBT_BASE_HOURS = 0.0
DEBT_CAP = 24.0


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def defaults(now=0.0):
    return {key: BASE_NEED for key in NEED_KEYS} | {"last_tick_ts": float(now)}


def need_step(needs, events=None, dt=1.0, now=0.0):
    """Apply event/silence deltas once per tick (idempotent by now)."""
    data = dict(needs or defaults(now))
    last = float(data.get("last_tick_ts", 0.0) or 0.0)
    if last > 0 and float(now) <= last:
        return data
    events = events if isinstance(events, dict) else {}
    dt = max(0.0, min(6.0, float(dt or 0.0)))
    silence_hours = float(events.get("silence_hours", dt) or 0.0)
    data["belonging"] = round(clamp(float(data.get("belonging", BASE_NEED)) - 0.02 * min(silence_hours, 20.0)), 4)
    data["control"] = round(clamp(float(data.get("control", BASE_NEED)) - (0.03 * min(silence_hours, 10.0) if events.get("stalled") else 0.0)), 4)
    if silence_hours > 48.0:
        data["meaningful_existence"] = round(clamp(float(data.get("meaningful_existence", BASE_NEED)) - 0.02 * min(silence_hours - 48.0, 20.0)), 4)
    if events.get("responded"):
        for key in NEED_KEYS:
            data[key] = round(clamp(float(data.get(key, BASE_NEED)) + 0.03), 4)
    if events.get("praised"):
        data["self_esteem"] = round(clamp(float(data.get("self_esteem", BASE_NEED)) + 0.04), 4)
    if events.get("ignored"):
        data["self_esteem"] = round(clamp(float(data.get("self_esteem", BASE_NEED)) - 0.05), 4)
    data["last_tick_ts"] = float(now)
    return data


def sleep_debt_step(debt, slept_hours=0.0, dt=1.0, now=0.0, state=None):
    """Lack of sleep accumulates debt; sleeping repays it. Idempotent by now."""
    state = dict(state or {})
    if float(state.get("last_debt_ts", 0.0) or 0.0) >= float(now) and now:
        return {"debt": round(float(debt or 0.0), 3), "last_debt_ts": float(now)}
    value = max(0.0, float(debt or 0.0))
    slept = max(0.0, float(slept_hours or 0.0))
    dt = max(0.0, min(24.0, float(dt or 0.0)))
    if slept > 0:
        value = max(0.0, value - slept * 0.75)
    else:
        value = value + dt * 0.5
    return {"debt": round(min(DEBT_CAP, value), 3), "last_debt_ts": float(now)}


def energy_penalty(debt):
    return round(clamp(float(debt or 0.0) / DEBT_CAP), 3)


def irritability(debt):
    return round(min(1.0, float(debt or 0.0) / 12.0), 3)


def view(needs, debt=0.0):
    data = dict(needs or defaults())
    values = {key: round(clamp(float(data.get(key, BASE_NEED))), 3) for key in NEED_KEYS}
    dominant = min(NEED_KEYS, key=lambda key: values[key]) if min(values.values()) < BASE_NEED else ""
    return {"needs": values, "dominant": dominant,
            "sleep_debt": round(float(debt or 0.0), 3),
            "energy_penalty": energy_penalty(debt), "irritability": irritability(debt)}
