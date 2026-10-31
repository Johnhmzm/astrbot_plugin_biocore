# -*- coding: utf-8 -*-
"""BIO-4: attachment activation as a biological-layer mechanism. Pure functions."""
from __future__ import annotations

MODES = {"anxious": "hyperactivating", "secure": "comfort", "avoidant": "deactivating"}
RESPONSE_FACTOR = 0.5
DECAY_PER_HOUR = 0.1


def clamp(value):
    return max(0.0, min(1.0, float(value)))


def threat(activation, signal, dt=0.0):
    return round(clamp(clamp(activation) + clamp(signal) * 0.5), 4)


def mode(style, activation):
    return MODES.get(style if style in MODES else "secure")


def decay(activation, replied, dt=0.0):
    value = clamp(activation)
    if replied:
        value *= (1.0 - RESPONSE_FACTOR)
    else:
        value *= max(0.0, 1.0 - DECAY_PER_HOUR * max(0.0, float(dt)))
    return round(clamp(value), 4)


def drive_multiplier(style):
    return {"anxious": 1.2, "secure": 1.05, "avoidant": 0.7}.get(
        style if style in MODES else "secure", 1.0)


def view(state, style="secure"):
    data = dict(state or {})
    value = round(clamp(data.get("activation", 0.0)), 3)
    return {"style": style if style in MODES else "secure",
            "activation": value, "mode": mode(style, value),
            "drive_mult": drive_multiplier(style)}
