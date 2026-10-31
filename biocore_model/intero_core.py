# -*- coding: utf-8 -*-
"""L0 interoception core: four non-verbal body dimensions in [0, 1].

These values are computed from body/affect state only -- never inferred from
text -- so the biological layer keeps owning "how the body feels" while the
interpretation layer owns language.

Dimensions
  tension   (绷紧): stress/arousal load, sleep debt, relationship conflict
  warmth    (暖)  : valence baseline, social saturation, trust, closeness
  heaviness (沉)  : sadness, allostatic load, low energy, loneliness
  clarity   (清)  : inverse noise, restedness, arousal near the middle

Literature
  Craig 2009 (insula interoception), Barrett 2017 (constructed emotion),
  Seth 2013 (interoceptive prediction), Garfinkel 2015 (three-dimensional
  interoception: accuracy/sensibility/awareness), Sterling 2012 (allostasis),
  Carver & Scheier 1998 (cybernetic control), Powers 1973 (perceptual
  control), Gross 1998 (emotion regulation strategies).

Hard constraints: pure functions, stdlib only, no IO, no main import, time is
injected (now=), and update() is idempotent for the same now. The core state
object is never mutated -- callers pass a dict and get a fresh dict back.
"""
from __future__ import annotations

import math

DIMS = ("tension", "warmth", "heaviness", "clarity")

# Set-points / comfort band (Gross 1998 regulation targets; Sterling 2012).
COMFORT = {"tension": 0.30, "warmth": 0.60, "heaviness": 0.30, "clarity": 0.70}
BAND = {"tension": 0.15, "warmth": 0.20, "heaviness": 0.15, "clarity": 0.20}
WEIGHTS = {"tension": 0.30, "warmth": 0.25, "heaviness": 0.25, "clarity": 0.20}

# Defaults keep the formulas total and monotone even on partial state dicts.
DEFAULTS = {
    "stress": 0.0, "arousal": 0.5, "sleep_debt": 0.0, "conflict": 0.0,
    "v": 0.0, "social": 0.5, "trust": 0.5, "closeness": 0.5,
    "sadness": 0.0, "allostatic_load": 0.0, "energy": 0.55,
    "loneliness": 0.0, "noise": 0.0,
}


def _clamp(value, lo=0.0, hi=1.0):
    try:
        return max(lo, min(hi, float(value)))
    except Exception:
        return lo


def _num(source, key, default=0.0):
    if not isinstance(source, dict):
        return float(default)
    try:
        value = source.get(key, default)
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _noise_value(source):
    """Noise may be a scalar or the core per-channel noise dict."""
    if not isinstance(source, dict):
        return 0.0
    value = source.get("noise", 0.0)
    if isinstance(value, dict) and value:
        try:
            return _clamp(sum(abs(float(v)) for v in value.values()) / len(value))
        except Exception:
            return 0.0
    return _clamp(value)


def _labels(source):
    if not isinstance(source, dict):
        return {}
    labels = source.get("labels")
    return labels if isinstance(labels, dict) else {}


def _emotion(source):
    labels = _labels(source)
    return str(labels.get("emotion") or source.get("emotion") or "neutral")


def inputs(state=None):
    """Extract the formula inputs from a core snapshot / state dict.

    Accepted keys (all optional): stress, arousal (alias a), sleep_debt,
    conflict, v, social, trust, closeness, sadness, allostatic_load, energy,
    loneliness, noise (scalar or per-channel dict), plus labels.emotion as a
    fallback for sadness/loneliness when those keys are absent.
    """
    state = state if isinstance(state, dict) else {}
    emotion = _emotion(state)
    arousal = _num(state, "arousal", _num(state, "a", DEFAULTS["arousal"]))
    sadness = _num(state, "sadness", 0.0)
    if not sadness and emotion == "sadness":
        sadness = _clamp(_num(state, "intensity", 0.5), 0.0, 1.0)
    loneliness = _num(state, "loneliness", 0.0)
    if not loneliness and emotion == "loneliness":
        loneliness = _clamp(_num(state, "intensity", 0.5), 0.0, 1.0)
    return {
        "stress": _clamp(_num(state, "stress", 0.0)),
        "arousal": _clamp(arousal),
        "sleep_debt": _clamp(_num(state, "sleep_debt", 0.0)),
        "conflict": _clamp(_num(state, "conflict", 0.0)),
        "v": _clamp(_num(state, "v", 0.0), -1.0, 1.0),
        "social": _clamp(_num(state, "social", 0.5)),
        "trust": _clamp(_num(state, "trust", 0.5)),
        "closeness": _clamp(_num(state, "closeness", 0.5)),
        "sadness": _clamp(sadness),
        "allostatic_load": _clamp(_num(state, "allostatic_load", 0.0)),
        "energy": _clamp(_num(state, "energy", 0.55)),
        "loneliness": _clamp(loneliness),
        "noise": _noise_value(state),
    }


def target(state=None):
    """The four dimension targets from the body state (no smoothing)."""
    x = inputs(state)
    tension = (0.45 * x["stress"] + 0.25 * x["arousal"]
               + 0.20 * x["sleep_debt"] + 0.10 * x["conflict"])
    warmth = (0.40 * ((x["v"] + 1.0) / 2.0) + 0.25 * x["social"]
              + 0.20 * x["trust"] + 0.15 * x["closeness"])
    heaviness = (0.40 * x["sadness"] + 0.30 * x["allostatic_load"]
                 + 0.20 * (1.0 - x["energy"]) + 0.10 * x["loneliness"])
    clarity = (0.40 * (1.0 - x["noise"]) + 0.30 * (1.0 - x["sleep_debt"])
               + 0.30 * (1.0 - abs(x["arousal"] - 0.5) * 2.0))
    return {"tension": round(_clamp(tension), 4),
            "warmth": round(_clamp(warmth), 4),
            "heaviness": round(_clamp(heaviness), 4),
            "clarity": round(_clamp(clarity), 4)}


def _values(intero):
    intero = intero if isinstance(intero, dict) else {}
    return {dim: round(_clamp(intero.get(dim, COMFORT[dim])), 4) for dim in DIMS}


def _alpha(dt_hours, rate):
    """Bounded EMA gain for one step: 1 - exp(-rate * dt)."""
    try:
        dt = max(0.0, float(dt_hours))
    except Exception:
        dt = 0.0
    try:
        r = max(0.0, min(1.0, float(rate)))
    except Exception:
        r = 0.25
    if dt <= 0.0 or r <= 0.0:
        return 0.0
    return 1.0 - math.exp(-r * dt)


def update(prev, state, dt_hours=None, rate=0.25, now=None):
    """EMA toward target(state); idempotent for the same now.

    dt_hours is the elapsed time since the previous update. When it is None and
    now plus prev["ts"] are available the delta is derived in hours. A zero
    delta (or an unchanged now) returns the previous values unchanged.
    """
    prev = prev if isinstance(prev, dict) else {}
    current = _values(prev)
    stamp = None
    if now is not None:
        try:
            stamp = float(now)
        except Exception:
            stamp = None
    if stamp is not None and prev.get("ts") is not None:
        try:
            if abs(float(prev.get("ts")) - stamp) < 1e-9:
                out = dict(current)
                out["ts"] = stamp
                return out
        except Exception:
            pass
    if dt_hours is None and stamp is not None and prev.get("ts") is not None:
        try:
            dt_hours = max(0.0, (stamp - float(prev.get("ts"))) / 3600.0)
        except Exception:
            dt_hours = 0.0
    alpha = _alpha(0.0 if dt_hours is None else dt_hours, rate)
    goal = target(state)
    out = {}
    for dim in DIMS:
        out[dim] = round(_clamp(current[dim] + alpha * (goal[dim] - current[dim])), 4)
    if stamp is not None:
        out["ts"] = stamp
    return out


def discomfort(intero, sp=None):
    """Band-relative weighted deviation: 0 inside every band, > 0 outside.

    sp may override set-points via {"comfort": {...}, "band": {...}} or
    directly {dim: value} (set-point override). Returns {total, parts} with
    total normalized to [0, 1] by the worst-case excess.
    """
    values = _values(intero)
    comfort = dict(COMFORT)
    band = dict(BAND)
    if isinstance(sp, dict):
        if isinstance(sp.get("comfort"), dict):
            comfort.update(sp["comfort"])
        if isinstance(sp.get("band"), dict):
            band.update(sp["band"])
        for dim in DIMS:
            if dim in sp and not isinstance(sp[dim], dict):
                comfort[dim] = sp[dim]
    parts = {}
    raw = 0.0
    worst = 0.0
    for dim in DIMS:
        center = _clamp(comfort.get(dim, COMFORT[dim]))
        half = _clamp(band.get(dim, BAND[dim]), 0.0, 1.0)
        excess = max(0.0, abs(values[dim] - center) - half)
        parts[dim] = round(excess, 4)
        weight = float(WEIGHTS[dim])
        raw += weight * excess
        worst += weight * max(center - half, (1.0 - center) - half, 0.0)
    total = 0.0 if worst <= 0.0 else _clamp(raw / worst)
    return {"total": round(total, 4), "parts": parts}


def view(intero):
    """Public read model: four dims + scalar discomfort."""
    values = _values(intero)
    values["discomfort"] = discomfort(values)["total"]
    return values
