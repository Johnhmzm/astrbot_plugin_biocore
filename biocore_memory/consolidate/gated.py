# -*- coding: utf-8 -*-
"""RecMem-style consolidation gate (pure, read-only, default OFF)."""
from __future__ import annotations

import time

GATED_ENABLED = False
WINDOW_SECONDS = 7 * 86400.0
MIN_TOPIC_REPEATS = 3
MIN_GAP_SECONDS = 6 * 3600.0
COSINE_MERGE = 0.80
MAX_ITEMS = 200


def _ts(entry):
    try:
        return float(entry.get("ts") or entry.get("created_ts") or 0.0)
    except Exception:
        return 0.0


def _tags(entry):
    raw = entry.get("tags")
    if not isinstance(raw, list):
        raw = (entry.get("metadata") or {}).get("tags") if isinstance(entry.get("metadata"), dict) else []
    return {str(x).strip().lower() for x in (raw or []) if str(x).strip()}


def _topic(entry):
    for key in ("topic", "event_key", "event_name", "thread"):
        value = str(entry.get(key) or "").strip().lower()
        if value:
            return value
    return ""


def _vector(entry):
    vec = entry.get("vector")
    if isinstance(vec, (list, tuple)) and vec:
        return list(vec)
    meta = entry.get("metadata")
    if isinstance(meta, dict):
        vec = meta.get("vector")
        if isinstance(vec, (list, tuple)) and vec:
            return list(vec)
    return []


def _cosine(a, b):
    try:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(float(x) * float(y) for x, y in zip(a, b))
        na = sum(float(x) ** 2 for x in a) ** 0.5
        nb = sum(float(y) ** 2 for y in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0
    except Exception:
        return 0.0


def _same_topic(a, b):
    ta, tb = _tags(a), _tags(b)
    if ta and tb and (ta & tb):
        return True
    topic_a, topic_b = _topic(a), _topic(b)
    if topic_a and topic_a == topic_b:
        return True
    return _cosine(_vector(a), _vector(b)) >= COSINE_MERGE


def _last_consolidated(entries):
    last = 0.0
    for entry in entries:
        for key in ("last_consolidated_ts", "consolidated_ts", "consolidate_ts"):
            try:
                last = max(last, float(entry.get(key) or 0.0))
            except Exception:
                continue
    return last


def should_consolidate(entries, now=None):
    """True only when >=3 same-topic items in 7d and last pass was >=6h ago."""
    if not GATED_ENABLED:
        return False
    try:
        rows = [e for e in (entries or []) if isinstance(e, dict)][:MAX_ITEMS]
        if len(rows) < MIN_TOPIC_REPEATS:
            return False
        stamp = float(now if now is not None else time.time())
        recent = [e for e in rows if 0.0 <= stamp - _ts(e) <= WINDOW_SECONDS]
        if len(recent) < MIN_TOPIC_REPEATS:
            return False
        last = _last_consolidated(recent)
        if last and stamp - last < MIN_GAP_SECONDS:
            return False
        for i, entry in enumerate(recent):
            same = 1 + sum(1 for j, other in enumerate(recent)
                           if j != i and _same_topic(entry, other))
            if same >= MIN_TOPIC_REPEATS:
                return True
        return False
    except Exception:
        return False
