# -*- coding: utf-8 -*-
"""Emotion in a continuous numeric space (constructivist / prototype geometry).

Labels are read-only descriptions of a point in affect space, not inputs to the
biological state. Distances to prototypes become a probability distribution;
mixed points stay mixed instead of being forced into one label.

Literature
  Russell 1980 (circumplex: valence x arousal), Mehrabian & Russell 1974 (PAD),
  Barrett 2017 (constructed emotion = core affect + conceptual categorization),
  Cowen & Keltner 2017 (semantic space of emotion), Smith & Ellsworth 1985
  (appraisal dimensions).
"""
from __future__ import annotations

import math

PROTOTYPES = {
    "sadness": {"v": -0.6, "a": -0.3, "d": -0.4, "social": -0.2, "stress": 0.4},
    "anger": {"v": -0.5, "a": 0.6, "d": 0.6, "social": -0.1, "stress": 0.6},
    "fear": {"v": -0.5, "a": 0.7, "d": -0.6, "social": -0.2, "stress": 0.7},
    "joy": {"v": 0.7, "a": 0.4, "d": 0.5, "social": 0.3, "stress": -0.2},
    "loneliness": {"v": -0.5, "a": -0.4, "d": -0.3, "social": -0.7, "stress": 0.2},
    "trust": {"v": 0.4, "a": 0.1, "d": 0.2, "social": 0.5, "trust": 0.7},
}
WEIGHTS = {"v": 0.35, "a": 0.25, "d": 0.15, "social": 0.15,
           "stress": 0.10, "trust": 0.15}
CORE_DIMS = ("v", "a", "d", "social", "stress", "trust")
LABELS = tuple(PROTOTYPES)
EPS = 1e-9


def _num(value, default=None):
    try:
        return float(value)
    except Exception:
        return default


def _to_pad(state):
    """Core state (v -1..1; others mostly 0..1) -> PAD-like prototype space."""
    state = state if isinstance(state, dict) else {}
    out = {}
    for name in CORE_DIMS:
        value = _num(state.get(name))
        if value is None:
            continue
        if name == "v":
            out[name] = max(-1.0, min(1.0, value))
        else:
            out[name] = max(-1.0, min(1.0, 2.0 * value - 1.0))
    return out


def _distance(point, prototype):
    total = 0.0
    weight_sum = 0.0
    for name in CORE_DIMS:
        if name not in prototype:
            continue
        weight = WEIGHTS[name]
        weight_sum += weight
        expected = float(prototype[name])
        if name in point:
            diff = point[name] - expected
        else:
            diff = 0.0 - expected  # missing -> neutral 0
        total += weight * diff * diff
    if weight_sum <= 0:
        return 1.0
    return math.sqrt(total / weight_sum)


def classify(state, temperature=0.25):
    """Softmax over prototype distances; returns label/probs/confidence/top2."""
    point = _to_pad(state)
    present_weight = sum(WEIGHTS[name] for name in CORE_DIMS if name in point)
    total_weight = sum(WEIGHTS.values())
    temp = max(0.01, float(temperature or 0.25))
    distances = {label: _distance(point, proto) for label, proto in PROTOTYPES.items()}
    logits = {label: -dist / temp for label, dist in distances.items()}
    peak = max(logits.values()) if logits else 0.0
    exps = {label: math.exp(value - peak) for label, value in logits.items()}
    norm = sum(exps.values()) or 1.0
    probs = {label: exps[label] / norm for label in LABELS}
    ranked = sorted(probs.items(), key=lambda item: item[1], reverse=True)
    label, top1 = ranked[0]
    top2 = [{"label": name, "prob": round(prob, 4)} for name, prob in ranked[1:3]]
    confidence = top1 - ranked[1][1] if len(ranked) > 1 else top1
    coverage = present_weight / total_weight if total_weight > 0 else 1.0
    # Missing dimensions always reduce confidence; neutral fill is not evidence.
    confidence *= max(0.0, min(1.0, coverage))
    return {"label": label,
            "probs": {name: round(prob, 4) for name, prob in probs.items()},
            "confidence": round(max(0.0, min(1.0, confidence)), 4),
            "top2": top2,
            "temperature": round(temp, 3)}


def top_probs(distribution, limit=3):
    probs = (distribution or {}).get("probs") or {}
    rows = sorted(probs.items(), key=lambda item: item[1], reverse=True)
    return [{"label": name, "prob": prob} for name, prob in rows[:max(0, int(limit))]]


def entropy(probs):
    values = [float(v) for v in (probs or {}).values() if float(v) > EPS]
    return round(-sum(p * math.log(p) for p in values), 4)
