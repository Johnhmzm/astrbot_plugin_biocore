# -*- coding: utf-8 -*-
"""Compassion fatigue: comfort has a price, and it recovers with rest.

Repeated comforting inside a stretch of negativity wears empathy down. The
decay is exponential and has a floor: she never becomes indifferent, she just
becomes quieter and less able to absorb.

  fatigue  = 1 - exp(-(0.22 * consecutive + 2.2 * negative_density))
  empathy  = max(floor, 1 - fatigue)
  recovery = fatigue * exp(-idle_hours / 6)

Pure functions only: no IO, no host imports, no LLM calls.
"""
from __future__ import annotations

import math

EMPATHY_FLOOR = 0.35
CONSECUTIVE_WEIGHT = 0.22
DENSITY_WEIGHT = 2.2
RECOVERY_TAU_HOURS = 6.0
ADVICE = {
    "high": "还能好好接着",
    "mid": "还能陪，但话少一点",
    "low": "先缓一缓，别硬接",
}


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


def fatigue(consecutive=0, negative_density=0.0, idle_hours=0.0, flags=None):
    """Fatigue after this stretch, before and after any recovery."""
    flags = flags if isinstance(flags, dict) else {}
    enabled = bool(flags.get("enabled", True))
    count = max(0, int(_num(consecutive, 0)))
    density = _clamp(negative_density)
    idle = max(0.0, _num(idle_hours, 0.0))
    tau = max(0.1, _num(flags.get("recovery_tau_hours"), RECOVERY_TAU_HOURS))
    floor = _clamp(flags.get("empathy_floor", EMPATHY_FLOOR))

    raw = 1.0 - math.exp(-(CONSECUTIVE_WEIGHT * count + DENSITY_WEIGHT * density))
    rested = raw * math.exp(-idle / tau)
    value = round(_clamp(rested), 3)
    empathy = round(max(floor, 1.0 - value), 3)
    if not enabled:
        return {"enabled": False, "fatigue": 0.0, "empathy": 1.0,
                "band": "high", "advice": ADVICE["high"], "recovery": 0.0}
    band = "high" if empathy >= 0.7 else ("mid" if empathy >= 0.5 else "low")
    return {
        "enabled": True,
        "fatigue": value,
        "raw_fatigue": round(_clamp(raw), 3),
        "empathy": empathy,
        "recovery": round(_clamp(raw - rested), 3),
        "band": band,
        "advice": ADVICE[band],
    }


def directives(result):
    """Bounded hints for the expression layer (no prompt text)."""
    if not isinstance(result, dict) or not result.get("enabled", True):
        return {"tone": "", "length_scale": 1.0, "empathy": 1.0}
    band = result.get("band") or "high"
    table = {
        "high": ("", 1.0),
        "mid": ("还在听，但别再说太多", 0.9),
        "low": ("先缓一下，短一点", 0.75),
    }
    tone, scale = table.get(band, table["high"])
    return {"tone": tone, "length_scale": scale,
            "empathy": round(_clamp(result.get("empathy"), 1.0), 3)}
