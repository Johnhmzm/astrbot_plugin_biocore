# -*- coding: utf-8 -*-
"""P1-1 predictive coding: predict next-turn state, compare, derive surprise.

Predictive processing (Friston 2010) + reward-prediction error (Schultz 1997):
the biological layer keeps a simple linear forecast of its own next-turn
channels/emotion/needs; when the next turn actually happens the difference is
the prediction error. A large error means the world moved more than expected:
it raises surprise/attention and temporarily raises the learning rate.

Pure functions only (dicts in, dicts out): no IO, no clock, no main import, and
it never writes prompt text. The caller logs the numbers and may consume
attention_boost / learning_rate_scale in its own bounded ways.
"""
from __future__ import annotations

CHANNELS = ("v", "a", "d", "social", "stress", "energy", "trust")
NEED_KEYS = ("belonging", "self_esteem", "control", "meaningful_existence")
NEED_BASELINE = 0.6
SLOPE_CLAMP = 0.15
TREND_DAMPING = 0.5
NEED_DRIFT = 0.05
SURPRISE_SCALE = 0.25
MAX_HISTORY = 6
MAX_ROWS = 8


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return float(default)
    if number != number or number in (float("inf"), float("-inf")):
        return float(default)
    return number


def _clamp(value, low, high):
    return max(low, min(high, _num(value, 0.0)))


def _round(value, digits=4):
    return round(_num(value), digits)


def vector(state):
    """Numeric projection of one state snapshot (unknown channels = 0)."""
    data = state if isinstance(state, dict) else {}
    return {name: _round(_clamp(data.get(name, 0.0),
                                -1.0 if name in ("v", "d") else 0.0, 1.0))
            for name in CHANNELS}


def _needs(state):
    data = state if isinstance(state, dict) else {}
    needs = data.get("needs")
    needs = needs if isinstance(needs, dict) else {}
    out = {}
    for key in NEED_KEYS:
        if key in needs:
            out[key] = _round(_clamp(needs.get(key), 0.0, 1.0))
    return out


def _emotion(state):
    data = state if isinstance(state, dict) else {}
    label = str(data.get("emotion") or "").strip().lower()
    if label:
        return label
    labels = data.get("labels")
    if isinstance(labels, dict):
        return str(labels.get("emotion") or "neutral").strip().lower()
    return "neutral"


def _slope(history, name):
    """Damped per-turn slope from the last two vectors (0 when unavailable)."""
    if not isinstance(history, (list, tuple)) or len(history) < 2:
        return 0.0
    try:
        previous = history[-2] if isinstance(history[-2], dict) else {}
        latest = history[-1] if isinstance(history[-1], dict) else {}
        delta = _num(latest.get(name)) - _num(previous.get(name))
    except Exception:
        return 0.0
    return _clamp(delta * TREND_DAMPING, -SLOPE_CLAMP, SLOPE_CLAMP)


def predict(state, history=None):
    """One-step forecast: channels (damped trend), emotion label, needs drift."""
    snapshot = state if isinstance(state, dict) else {}
    current = vector(snapshot)
    forecast = {}
    for name in CHANNELS:
        low, high = (-1.0, 1.0) if name in ("v", "d") else (0.0, 1.0)
        forecast[name] = _round(_clamp(current[name] + _slope(history, name),
                                       low, high))
    needs_now = _needs(snapshot)
    needs_forecast = {
        key: _round(_clamp(value + NEED_DRIFT * (NEED_BASELINE - value),
                           0.0, 1.0))
        for key, value in needs_now.items()
    }
    confidence = _round(_clamp(0.35 + 0.1 * len(history or []), 0.1, 0.9), 3)
    return {"channels": forecast, "emotion": _emotion(snapshot),
            "needs": needs_forecast, "confidence": confidence}


def compare(prediction, actual):
    """Prediction error between the last forecast and the measured state."""
    predicted = prediction if isinstance(prediction, dict) else {}
    measured = actual if isinstance(actual, dict) else {}
    forecast = predicted.get("channels")
    forecast = forecast if isinstance(forecast, dict) else {}
    now = vector(measured)
    channels = {}
    errors = []
    for name in CHANNELS:
        expected = _round(_clamp(forecast.get(name, now[name]),
                                 -1.0 if name in ("v", "d") else 0.0, 1.0))
        error = _round(abs(now[name] - expected))
        channels[name] = {"predicted": expected, "actual": now[name],
                          "error": error}
        errors.append(error)
    error = _round(sum(errors) / float(len(errors))) if errors else 0.0
    emotion_hit = str(predicted.get("emotion") or "") == _emotion(measured)
    predicted_needs = predicted.get("needs")
    predicted_needs = predicted_needs if isinstance(predicted_needs, dict) else {}
    needs_now = _needs(measured)
    needs_errors = [abs(needs_now[key] - _num(predicted_needs.get(key,
                                                                 needs_now[key])))
                    for key in NEED_KEYS if key in needs_now]
    needs_error = (_round(sum(needs_errors) / float(len(needs_errors)))
                   if needs_errors else 0.0)
    return {"channels": channels, "error": error, "emotion_hit": bool(emotion_hit),
            "predicted_emotion": str(predicted.get("emotion") or ""),
            "actual_emotion": _emotion(measured),
            "needs_error": needs_error, "surprise": surprise(error)}


def surprise(error):
    """Map channel error to a 0..1 surprise scalar."""
    return _round(_clamp(_num(error) / SURPRISE_SCALE, 0.0, 1.0))


def attention_boost(value):
    """Surprise -> 0..1 attention boost (2x, saturating), monotone."""
    return _round(_clamp(2.0 * _clamp(value, 0.0, 1.0), 0.0, 1.0))


def learning_rate_scale(value, low=0.6, high=1.8):
    """Surprise -> multiplicative learning-rate scale in [low, high]."""
    base = _clamp(low, 0.01, 10.0)
    top = _clamp(high, base, 10.0)
    return _round(base + (top - base) * _clamp(value, 0.0, 1.0), 3)


def append_history(history, vector_state, limit=MAX_HISTORY):
    """Newest-last bounded history of vectors (never mutates the input)."""
    kept = []
    if isinstance(history, (list, tuple)):
        kept = [dict(row) for row in history if isinstance(row, dict)]
    if isinstance(vector_state, dict):
        kept.append(dict(vector_state))
    cap = max(1, min(MAX_ROWS * 2, int(_num(limit, MAX_HISTORY))))
    return kept[-cap:]


def summary(report):
    """Bounded row for logs/panel (no prompt text)."""
    data = report if isinstance(report, dict) else {}
    return {"surprise": _round(data.get("surprise"), 3),
            "error": _round(data.get("error"), 4),
            "emotion_hit": bool(data.get("emotion_hit")),
            "predicted_emotion": str(data.get("predicted_emotion") or "")[:16],
            "actual_emotion": str(data.get("actual_emotion") or "")[:16],
            "needs_error": _round(data.get("needs_error"), 4),
            "attention_boost": attention_boost(data.get("surprise")),
            "learning_rate_scale": learning_rate_scale(data.get("surprise"))}
