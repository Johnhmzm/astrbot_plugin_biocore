# -*- coding: utf-8 -*-
"""Williams 2007 four needs + Leary 1995 state self-esteem (GAP-C)."""
from __future__ import annotations

try:
    from . import needs_sleep as _bio
except Exception:  # pragma: no cover
    from biocore_model import needs_sleep as _bio

NEED_KEYS = ("belonging", "self_esteem", "control", "meaningful_existence")
BASE_NEED = 0.6
BASE_ESTEEM = 0.55
REGRESS_RATE = 0.05


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def defaults():
    """Deprecated wrapper: delegates to the biological layer (BIO-5)."""
    data = _bio.defaults(0.0)
    return {key: BASE_NEED for key in NEED_KEYS}


def silence_effects(hours, phases_stalled=False):
    try:
        h = max(0.0, float(hours))
    except Exception:
        h = 0.0
    belonging = max(-0.4, -0.02 * h)
    control = max(-0.3, -0.03 * h) if phases_stalled else 0.0
    meaning = -0.02 * h if h > 48.0 else 0.0
    return {"belonging": belonging, "self_esteem": 0.0,
            "control": control, "meaningful_existence": meaning}


def apply_silence(needs, hours, stalled=False):
    """Deprecated wrapper: delegates to needs_sleep.need_step."""
    data = _bio.need_step(dict(needs or defaults()), {"silence_hours": float(hours), "stalled": bool(stalled)}, dt=0.0, now=0.0)
    return {key: data[key] for key in NEED_KEYS}


def on_ignored(needs, rejected=False):
    data = _bio.need_step(dict(needs or defaults()), {"ignored": True}, dt=0.0, now=0.0)
    if rejected:
        data["belonging"] = round(clamp(float(data.get("belonging", BASE_NEED)) - 0.02), 4)
    else:
        # BIO-5 delegation keeps the historical mild-ignore value (-0.02 net).
        data["self_esteem"] = round(clamp(float(data.get("self_esteem", BASE_NEED)) + 0.03), 4)
    return {key: data[key] for key in NEED_KEYS}


def on_responded(needs):
    data = _bio.need_step(dict(needs or defaults()), {"responded": True}, dt=0.0, now=0.0)
    return {key: data[key] for key in NEED_KEYS}


def on_praised(needs):
    data = _bio.need_step(dict(needs or defaults()), {"praised": True}, dt=0.0, now=0.0)
    return {key: data[key] for key in NEED_KEYS}


def dominant(needs):
    data = needs or defaults()
    key = min(NEED_KEYS, key=lambda name: float(data.get(name, BASE_NEED)))
    return key if float(data.get(key, BASE_NEED)) < BASE_NEED else ""


BEHAVIOUR = {
    "belonging": {"drive_delta": 0.03, "arousal_delta": 0.0, "blame_mult": 1.0,
                  "confidence_delta": 0.0, "tone": "靠近、亲昵"},
    "self_esteem": {"drive_delta": 0.0, "arousal_delta": 0.0, "blame_mult": 1.3,
                    "confidence_delta": -0.05, "tone": "犹豫、少说话"},
    "control": {"drive_delta": 0.0, "arousal_delta": 0.05, "blame_mult": 1.0,
                "confidence_delta": 0.0, "tone": "追问式短句"},
    "meaningful_existence": {"drive_delta": -0.05, "arousal_delta": 0.0, "blame_mult": 1.0,
                             "confidence_delta": -0.02, "tone": "更少更淡"},
    "": {"drive_delta": 0.0, "arousal_delta": 0.0, "blame_mult": 1.0,
         "confidence_delta": 0.0, "tone": ""},
}


def behaviour(needs):
    key = dominant(needs)
    data = dict(BEHAVIOUR.get(key, BEHAVIOUR[""]))
    data["dominant"] = key
    return data


def self_esteem_update(current, responded=False, praised=False, ignored=False, rejected=False):
    try:
        value = float(current if current is not None else BASE_ESTEEM)
    except Exception:
        value = BASE_ESTEEM
    if responded or praised:
        value += 0.06
    if ignored or rejected:
        value -= 0.05
    value += (BASE_ESTEEM - value) * REGRESS_RATE
    return round(clamp(value), 4)


def confidence_from_esteem(esteem, base=1.0):
    try:
        value = clamp(esteem)
    except Exception:
        value = BASE_ESTEEM
    return round(clamp(base - 0.5 * (BASE_ESTEEM - value)), 4)


def view(needs, esteem):
    data = dict(needs or defaults())
    dominant_key = dominant(data)
    return {key: round(float(data.get(key, BASE_NEED)), 3) for key in NEED_KEYS} | {
        "dominant": dominant_key, "self_esteem": round(float(esteem or BASE_ESTEEM), 3)}
