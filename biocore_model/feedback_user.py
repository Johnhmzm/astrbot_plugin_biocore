# -*- coding: utf-8 -*-
"""FB-2: user behaviour -> bounded state deltas (feedback channel). Pure."""
from __future__ import annotations

import hashlib
import json

CAPS = {"v": 0.02, "social": 0.03, "stress": 0.02, "social_pain": 0.10,
        "self_esteem": 0.05, "mood_valence": 0.02}
EVENTS = {
    "reply": {"v": 0.02, "social": 0.03, "stress": -0.02, "social_pain": -0.10},
    "praise": {"v": 0.02, "self_esteem": 0.04, "social": 0.03},
    "insult": {"self_esteem": -0.05, "social_pain": 0.08, "stress": 0.03},
    "reject": {"social_pain": 0.10, "v": -0.03},
    # Classifier kinds (empty base if a dedicated extra event carries the delta).
    "neutral": {},
    "sad": {},
    "affectionate": {},
    # Empathic burden: hearing the user say they are sad costs a little state.
    "sad_empathy": {"stress": 0.02, "social_pain": 0.01, "v": -0.005},
    # Warm signal: social up, stress down.
    "affection": {"social": 0.03, "stress": -0.01},
}
RANGES = {"v": (-1.0, 1.0), "social": (0.0, 1.0), "stress": (0.0, 1.0),
          "social_pain": (0.0, 1.0), "self_esteem": (0.0, 1.0), "mood_valence": (-1.0, 1.0)}


def _hash(value):
    try:
        body = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        body = str(value)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _apply(state, event, now, audit, seen, key, caps=None):
    caps = caps or CAPS
    for field, delta in event.items():
        old = _num(state.get(field))
        cap = float(caps.get(field, 0.10))
        delta = max(-cap, min(cap, float(delta)))
        low, high = RANGES.get(field, (0.0, 1.0))
        new = max(low, min(high, old + delta))
        event[field] = round(new - old, 4)
        audit.append({"field": field, "old": round(old, 4), "new": round(new, 4),
                      "source": "user", "reason": "user behaviour"})
    return event


def on_message(state, msg_meta, now, seen=None):
    state = state if isinstance(state, dict) else {}
    meta = msg_meta if isinstance(msg_meta, dict) else {}
    kind = str(meta.get("kind") or "reply")
    if kind not in EVENTS:
        return {"deltas": {}, "audit": [], "idempotent": False, "rejected": [kind]}
    digest = _hash({"kind": kind, "id": meta.get("id"), "ts": meta.get("ts")})
    seen = seen if isinstance(seen, dict) else {}
    if seen.get(digest) is not None:
        return {"deltas": {}, "audit": [], "idempotent": True, "rejected": []}
    audit = []
    deltas = _apply(dict(state), dict(EVENTS[kind]), now, audit, seen, digest)
    seen[digest] = float(now)
    return {"deltas": deltas, "audit": audit, "idempotent": False, "rejected": []}


def on_silence(state, silence_hours, now, seen=None):
    state = state if isinstance(state, dict) else {}
    try:
        hours = max(0.0, float(silence_hours or 0.0))
    except Exception:
        hours = 0.0
    bucket = int(float(now) // 3600)
    seen = seen if isinstance(seen, dict) else {}
    key = "silence:" + str(bucket)
    if seen.get(key) is not None:
        return {"deltas": {}, "audit": [], "idempotent": True}
    social_pain = min(0.10, 0.01 * hours)
    mood = max(-0.02, -0.005 * hours)
    audit = []
    deltas = {"social_pain": round(social_pain, 4), "mood_valence": round(mood, 4)}
    for field, value in (("social_pain", social_pain), ("mood_valence", mood)):
        audit.append({"field": field, "old": round(_num(state.get(field)), 4),
                      "new": round(_num(state.get(field)) + value, 4),
                      "source": "user", "reason": "silence accumulation"})
    seen[key] = float(now)
    return {"deltas": deltas, "audit": audit, "idempotent": False}
