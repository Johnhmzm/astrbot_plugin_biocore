# -*- coding: utf-8 -*-
"""FB-1: LLM structured payload -> bounded state deltas (feedback channel).

Two payload shapes are accepted:
1) label/target path (legacy): keys are target values ("v": 0.8 means set v
   toward 0.8), converted to a bounded delta against the current state.
2) inferred path (interpretation layer): keys are already deltas
   (valence_delta/arousal_delta/dominance_delta/social_delta/trust_delta/
   stress_delta) plus confidence/source; each delta is scaled by confidence and
   dropped entirely when confidence < INFERRED_MIN_CONFIDENCE.
"""
from __future__ import annotations

import hashlib
import json

CAPS = {"v": 0.15, "a": 0.15, "stress": 0.10, "trust": 0.05,
        "closeness": 0.05, "confidence": 0.10}

# interpretation-layer inferred meta -> feedback delta field
INFERRED_MAP = {
    "valence_delta": "v",
    "arousal_delta": "a",
    "dominance_delta": "d",
    "social_delta": "social",
    "trust_delta": "trust",
    "stress_delta": "stress",
    "self_esteem_delta": "self_esteem",
}
INFERRED_CAPS = {"v": 0.15, "a": 0.15, "d": 0.10, "social": 0.05,
                 "trust": 0.05, "stress": 0.10, "self_esteem": 0.05}
INFERRED_MIN_CONFIDENCE = 0.4
RANGES = {"v": (-1.0, 1.0), "a": (0.0, 1.0), "stress": (0.0, 1.0),
          "trust": (0.0, 1.0), "closeness": (0.0, 1.0), "confidence": (0.0, 1.0)}
NEED_RANGE = (0.0, 1.0)


def payload_hash(payload):
    try:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        body = str(payload)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _num(value, default=None):
    try:
        return float(value)
    except Exception:
        return default


def _clamp(value, low, high):
    return max(low, min(high, float(value)))


def parse_inferred(payload, limits=None, now=None, seen=None):
    """Inferred meta (delta semantics) -> bounded deltas scaled by confidence.

    Returns empty deltas when confidence is missing or below
    INFERRED_MIN_CONFIDENCE (宁缺勿滥); unknown fields are left to
    feedback_guard's whitelist. Pure: never mutates the payload.
    """
    payload = payload if isinstance(payload, dict) else {}
    digest = payload_hash(payload)
    seen = seen if isinstance(seen, dict) else {}
    seen_key = "inferred:" + digest
    if now is not None and seen.get(seen_key) == float(now):
        return {"deltas": {}, "rejected": [], "audit": [], "hash": digest,
                "idempotent": True, "confidence": 0.0, "source": "inferred"}
    confidence = _num(payload.get("confidence"), 0.0)
    try:
        confidence = _clamp(float(confidence), 0.0, 1.0)
    except Exception:
        confidence = 0.0
    if confidence < INFERRED_MIN_CONFIDENCE:
        return {"deltas": {}, "rejected": [], "audit": [], "hash": digest,
                "idempotent": False, "confidence": confidence,
                "source": "inferred", "gate": "low_confidence"}
    caps = dict(INFERRED_CAPS)
    caps.update(limits or {})
    deltas = {}
    rejected = []
    audit = []
    for source_key, field in INFERRED_MAP.items():
        if source_key not in payload:
            continue
        raw = _num(payload.get(source_key))
        if raw is None:
            rejected.append(source_key)
            continue
        cap = float(caps.get(field, 0.15))
        value = max(-cap, min(cap, raw * confidence))
        if abs(value) < 1e-9:
            continue
        deltas[field] = round(value, 4)
        audit.append({"field": field, "delta": round(value, 4), "source": "llm",
                      "reason": "inferred meta",
                      "confidence": round(confidence, 4)})
    if now is not None:
        seen[seen_key] = float(now)
    return {"deltas": deltas, "rejected": rejected, "audit": audit,
            "hash": digest, "idempotent": False, "confidence": confidence,
            "source": "inferred"}


def parse_to_deltas(payload, limits=None, state=None, now=None, seen=None):
    """Pure: returns deltas + rejected + audit; never mutates core."""
    payload = payload if isinstance(payload, dict) else {}
    if any(str(key).endswith("_delta") for key in payload):
        return parse_inferred(payload, limits=limits, now=now, seen=seen)
    state = state if isinstance(state, dict) else {}
    caps = dict(CAPS); caps.update(limits or {})
    digest = payload_hash(payload)
    seen = seen if isinstance(seen, dict) else {}
    if now is not None and seen.get(digest) == float(now):
        return {"deltas": {}, "rejected": [], "audit": [], "hash": digest, "idempotent": True}
    rejected = []
    audit = []
    deltas = {}
    needs_delta = {}
    for field in ("v", "a", "stress", "trust", "closeness", "confidence"):
        if field not in payload:
            continue
        value = _num(payload.get(field))
        if value is None:
            rejected.append(field); continue
        old = _num(state.get(field), 0.0 if field != "a" else 0.5)
        delta = value - old
        cap = float(caps.get(field, 0.15))
        delta = max(-cap, min(cap, delta))
        low, high = RANGES[field]
        new = _clamp(old + delta, low, high)
        if abs(new - old) < 1e-9:
            continue
        deltas[field] = round(new - old, 4)
        audit.append({"field": field, "old": round(old, 4), "new": round(new, 4),
                      "source": "llm", "reason": "structured feedback"})
    needs = payload.get("needs")
    if isinstance(needs, dict):
        old_needs = state.get("needs") if isinstance(state.get("needs"), dict) else {}
        for key, value in needs.items():
            if key not in ("belonging", "self_esteem", "control", "meaningful_existence"):
                rejected.append("needs." + str(key)); continue
            num = _num(value)
            if num is None:
                rejected.append("needs." + str(key)); continue
            old = _num(old_needs.get(key), 0.6)
            delta = max(-0.10, min(0.10, num - old))
            new = _clamp(old + delta, *NEED_RANGE)
            needs_delta[key] = round(new - old, 4)
            audit.append({"field": "needs." + str(key), "old": round(old, 4),
                          "new": round(new, 4), "source": "llm", "reason": "structured feedback"})
    if needs_delta:
        deltas["needs"] = needs_delta
    known = {"v", "a", "stress", "trust", "closeness", "confidence", "needs"}
    for key in payload:
        if key not in known:
            rejected.append(str(key))
    if now is not None:
        seen[digest] = float(now)
    return {"deltas": deltas, "rejected": rejected, "audit": audit,
            "hash": digest, "idempotent": False}
