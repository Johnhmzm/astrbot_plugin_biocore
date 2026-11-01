# -*- coding: utf-8 -*-
"""P0-2: one message cannot move the biological state by more than a budget.

The inline state tag / emotion probe rate 7 appraisal dimensions per message.
appraisal.appraise() maps them to affect deltas and caps every output channel
separately, but the *sum* over all channels can still reach ~0.65 in one turn.
This module enforces one per-message budget on the total absolute delta and
scales every channel by the same factor, so direction and the ratios between
channels are preserved.

Pure functions only: no filesystem, no clock, no imports from main.py.
"""
from __future__ import annotations

DEFAULT_LIMIT = 0.2
MIN_LIMIT = 0.01
MAX_LIMIT = 1.0
DECIMALS = 4


def _num(value):
    """Finite float or None (NaN/inf/strings/bools are rejected)."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except Exception:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def clean_limit(limit, default=DEFAULT_LIMIT):
    """Valid budget limit, clamped to [MIN_LIMIT, MAX_LIMIT]."""
    number = _num(limit)
    if number is None or number <= 0:
        number = float(default)
    if number <= 0:
        number = DEFAULT_LIMIT
    return max(MIN_LIMIT, min(MAX_LIMIT, number))


def total(deltas):
    """Sum of absolute deltas (non-numeric values ignored)."""
    if not isinstance(deltas, dict):
        return 0.0
    numbers = [_num(value) for value in deltas.values()]
    return round(sum(abs(number) for number in numbers
                     if number is not None), DECIMALS)


def sanitize(deltas):
    """Numeric-only copy; non-numeric channels are dropped."""
    if not isinstance(deltas, dict):
        return {}
    out = {}
    for key, value in deltas.items():
        number = _num(value)
        if number is None:
            continue
        out[str(key)] = round(number, DECIMALS)
    return out


def budget(deltas, limit=DEFAULT_LIMIT, enabled=True):
    """Scale one message's deltas so sum(|delta|) <= limit.

    Returns (scaled_deltas, report) where report carries the raw/scaled totals,
    the applied factor and whether scaling happened. Disabled or in-budget
    input is returned sanitized but numerically unchanged.
    """
    clean = sanitize(deltas)
    cap = clean_limit(limit)
    report = {"enabled": bool(enabled), "limit": cap,
              "raw_total": total(clean), "scaled_total": total(clean),
              "factor": 1.0, "scaled": False}
    if not clean:
        return {}, report
    if not enabled:
        return clean, report
    raw = report["raw_total"]
    if raw <= cap + 1e-9 or raw <= 0:
        return clean, report
    # Scale in integer units of 1e-DECIMALS so the budget holds exactly after
    # rounding (per-channel rounding could otherwise overshoot by a few ulps).
    unit = 10 ** DECIMALS
    units = {key: int(round(value * unit)) for key, value in clean.items()}
    raw_units = sum(abs(value) for value in units.values())
    cap_units = int(cap * unit)
    if raw_units <= cap_units:
        return clean, report
    scaled = {}
    for key, value in units.items():
        scaled[key] = round(int(value * cap_units / raw_units) / unit, DECIMALS)
    report["factor"] = round(float(cap_units) / float(raw_units), DECIMALS)
    report["scaled"] = True
    report["scaled_total"] = total(scaled)
    return scaled, report
