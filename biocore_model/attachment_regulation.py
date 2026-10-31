# -*- coding: utf-8 -*-
"""Attachment activation, emotion regulation, mood baseline (GAP-G)."""
from __future__ import annotations

MODES = {"anxious": {"drive": 1.2, "tone": "sharper", "mode": "hyperactivating"},
         "secure": {"drive": 1.05, "tone": "seek_comfort", "mode": "comfort"},
         "avoidant": {"drive": 0.7, "tone": "suppressed", "mode": "deactivating"}}
DECAY_PER_HOUR = 0.1
RESPONSE_DROP = 0.5
MOOD_RATE = 0.05

from . import attachment_state as _attach_bio
from . import mood as _mood_bio

try:
    from biocore_model import mood as _mood_bio
except Exception:
    pass


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def activation(style="secure", threat=0.0, current=0.0, responded=False, hours=0.0):
    """Deprecated wrapper: delegates to the biological layer (BIO-4)."""
    raised = _attach_bio.threat(current, threat)
    value = _attach_bio.decay(raised, responded, hours)
    style = style if style in MODES else "secure"
    return {"style": style, "activation": value,
            "mode": _attach_bio.mode(style, value),
            "drive_mult": _attach_bio.drive_multiplier(style),
            "tone": dict(MODES.get(style))["tone"]}


def choose_strategy(style, energy=1.0, valence=0.0):
    low_energy = clamp(energy) < 0.4
    if style == "avoidant":
        return "suppress"
    if low_energy or valence < -0.5:
        return "suppress"
    return "reappraise"


def regulate(strategy, stress=0.0, effort=0.0):
    strategy = strategy if strategy in ("reappraise", "suppress") else "reappraise"
    if strategy == "reappraise":
        return {"strategy": strategy, "negative_mult": 0.6, "stress_delta": 0.0,
                "suppressed": False, "effort": round(clamp(float(effort) + 0.1, 0.0, 10.0), 4)}
    return {"strategy": strategy, "negative_mult": 0.5, "stress_delta": 0.03,
            "suppressed": True, "effort": round(clamp(float(effort) + 0.15, 0.0, 10.0), 4)}


def mood_update(mood, valence=0.0, arousal=0.0, now=None):
    """Deprecated wrapper: delegates to the biological layer (BIO-4)."""
    return _mood_bio.mood_update(mood, valence, arousal, now=now)


def mood_ticks_to_zero(start=-0.5, rate=MOOD_RATE):
    """Ticks until |mood| drops below 0.05 (slow variable)."""
    import math
    if start == 0:
        return 0
    return int(math.ceil(math.log(0.05 / abs(start)) / math.log(1 - rate)))


def regulation_risk(effort, threshold=1.5):
    return bool(float(effort or 0.0) >= float(threshold))


def view(style, activation_value, mode, strategy, effort, suppressed, mood):
    return {"attachment": {"style": style, "activation": round(float(activation_value), 4), "mode": mode},
            "regulation": {"strategy": strategy, "effort": round(float(effort or 0.0), 3), "suppressed": bool(suppressed)},
            "mood": {"valence": round(float((mood or {}).get("valence", 0.0)), 3),
                     "arousal": round(float((mood or {}).get("arousal", 0.0)), 3)}}
