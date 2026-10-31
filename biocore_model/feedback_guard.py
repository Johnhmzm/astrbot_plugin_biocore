# -*- coding: utf-8 -*-
"""FB-4: single gate for every feedback delta (LLM + user). Pure functions."""
from __future__ import annotations

import hashlib
import json

WHITELIST = ("v", "a", "stress", "social", "social_pain", "self_esteem",
             "trust", "closeness", "confidence")
NEED_KEYS = ("belonging", "self_esteem", "control", "meaningful_existence")
LIMITS = {
    "llm": {"v": 0.15, "a": 0.15, "stress": 0.10, "social": 0.05,
            "social_pain": 0.10, "self_esteem": 0.05, "trust": 0.05,
            "closeness": 0.05, "confidence": 0.10, "needs": 0.10},
    "user": {"v": 0.02, "a": 0.02, "stress": 0.02, "social": 0.03,
             "social_pain": 0.10, "self_esteem": 0.05, "trust": 0.02,
             "closeness": 0.02, "confidence": 0.02, "needs": 0.05},
}
TOTAL_CAPS = {"v": 0.20, "a": 0.20, "self_esteem": 0.08}
RANGES = {"v": (-1.0, 1.0)}


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _hash(deltas):
    try:
        body = json.dumps(deltas, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        body = str(deltas)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def limits_for(source, limits=None):
    source = str(source or "")
    if source in LIMITS:
        caps = dict(LIMITS[source])
    else:
        caps = {key: min(LIMITS["llm"].get(key, 0.05), LIMITS["user"].get(key, 0.05))
                for key in LIMITS["llm"]}
    caps.update(limits or {})
    return caps


def _expand(deltas):
    rows = []
    for field, value in (deltas or {}).items():
        if field == "needs" and isinstance(value, dict):
            for key, delta in value.items():
                rows.append(("needs." + str(key), _num(delta)))
        else:
            rows.append((str(field), _num(value)))
    return rows


def vet(deltas, state, source, now, limits=None, seen=None):
    state = state if isinstance(state, dict) else {}
    caps = limits_for(source, limits)
    seen = seen if isinstance(seen, dict) else {}
    digest = _hash(deltas)
    id_key = str(source) + ":" + str(digest) + ":" + str(now)
    if seen.get(id_key):
        return {"accepted": {}, "rejected": [], "audit": [], "idempotent": True}
    accepted = {}
    rejected = []
    audit = []
    needs = {}
    totals = {"v": 0.0, "a": 0.0, "self_esteem": 0.0}
    for field, delta in _expand(deltas):
        if field.startswith("needs."):
            name = field.split(".", 1)[1]
            if name not in NEED_KEYS:
                rejected.append({"field": field, "reason": "not whitelisted"})
                continue
            cap = float(caps.get("needs", 0.05))
            old = _num((state.get("needs") or {}).get(name), 0.6)
        elif field in WHITELIST:
            cap = float(caps.get(field, 0.05))
            old = _num(state.get(field))
        else:
            rejected.append({"field": field, "reason": "not whitelisted"})
            continue
        clipped = max(-cap, min(cap, delta))
        if len(rejected) > 50:
            break
        if field in totals:
            remaining = TOTAL_CAPS.get(field, cap) - abs(totals[field])
            clipped = max(-remaining, min(remaining, clipped)) if remaining > 0 else 0.0
            totals[field] += abs(clipped)
        low, high = RANGES.get(field, (0.0, 1.0))
        new = max(low, min(high, old + clipped))
        applied = round(new - old, 4)
        if abs(applied) < 1e-9:
            continue
        audit.append({"field": field, "old": round(old, 4), "new": round(new, 4),
                      "source": str(source), "reason": "feedback", "ts": float(now)})
        if field.startswith("needs."):
            needs[field.split(".", 1)[1]] = applied
        else:
            accepted[field] = applied
    if needs:
        accepted["needs"] = needs
    seen[id_key] = True
    if len(seen) > 200:
        for key in list(seen)[:-100]:
            seen.pop(key, None)
    return {"accepted": accepted, "rejected": rejected, "audit": audit,
            "idempotent": False}


def apply(state, accepted):
    state = dict(state or {})
    changed = []
    for field, delta in (accepted or {}).items():
        if field == "needs" and isinstance(delta, dict):
            needs = dict(state.get("needs") or {})
            for key, value in delta.items():
                needs[key] = round(max(0.0, min(1.0, _num(needs.get(key), 0.6) + _num(value))), 4)
            state["needs"] = needs
            changed.append("needs")
            continue
        low, high = RANGES.get(field, (0.0, 1.0))
        state[field] = round(max(low, min(high, _num(state.get(field)) + _num(delta))), 4)
        changed.append(str(field))
    return {"state": state, "changed": changed}
