# -*- coding: utf-8 -*-
"""Deterministic event-boundary detection (pure; default OFF).

Event segmentation (Zacks et al. 2007): a new event starts when the situation
model changes. Three deterministic signals approximate it:
  - semantic shift: 1 - character-bigram Jaccard between the two messages;
  - time gap:       dt / TIME_GAP_SECONDS (>= 30 min counts as 1.0);
  - topic shift:    1 - entity Jaccard (only when both sides have entities).
score = 0.5 * semantic + 0.3 * time + 0.2 * topic, bounded to 0..1.

Interface:
  boundary_score(prev_msg, cur_msg, dt=0.0) -> float in 0..1
  is_boundary(ctx) -> (bool, float)   # threshold defaults to 0.5

The module is disabled by default: callers gate on 'enabled' before switching
slots. No IO, no LLM, no host imports.
"""
from __future__ import annotations

import re

enabled = False
BOUNDARY_ENABLED = enabled

BOUNDARY_THRESHOLD = 0.5
TIME_GAP_SECONDS = 30 * 60.0
SEMANTIC_WEIGHT = 0.5
TIME_WEIGHT = 0.3
TOPIC_WEIGHT = 0.2
GRAM_SIZE = 2
MIN_CHARS = 2

_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def _clean(text):
    return _NON_WORD.sub("", str(text or "").lower())


def _grams(text):
    clean = _clean(text)
    if len(clean) < GRAM_SIZE:
        return {clean} if clean else set()
    return {clean[index:index + GRAM_SIZE]
            for index in range(len(clean) - GRAM_SIZE + 1)}


def _jaccard(left, right):
    if not left or not right:
        return 0.0
    union = len(left | right)
    return len(left & right) / union if union else 0.0


def _semantic_shift(prev_msg, cur_msg):
    left, right = _clean(prev_msg), _clean(cur_msg)
    if len(left) < MIN_CHARS or len(right) < MIN_CHARS:
        return 0.0
    return 1.0 - _jaccard(_grams(left), _grams(right))


def _time_shift(dt):
    try:
        value = float(dt or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if value <= 0.0:
        return 0.0
    return min(1.0, value / TIME_GAP_SECONDS)


def _entities(text):
    try:
        from ..index.entities import extract_entities
        return extract_entities(str(text or ""), limit=8)
    except Exception:
        return []


def _topic_shift(prev_msg, cur_msg):
    left = set(_entities(prev_msg))
    right = set(_entities(cur_msg))
    if not left or not right:
        return 0.0
    return 1.0 - _jaccard(left, right)


def boundary_score(prev_msg, cur_msg, dt=0.0):
    """Return a deterministic 0..1 boundary score for one transition."""
    if str(prev_msg or "") == "" or str(cur_msg or "") == "":
        return 0.0
    score = (SEMANTIC_WEIGHT * _semantic_shift(prev_msg, cur_msg)
             + TIME_WEIGHT * _time_shift(dt)
             + TOPIC_WEIGHT * _topic_shift(prev_msg, cur_msg))
    return round(max(0.0, min(1.0, score)), 4)


def is_boundary(ctx):
    """Return (is_boundary, score) for a context dict.

    Accepted keys: prev_msg / prev_text / message_prev, cur_msg / cur_text /
    text / message, dt / gap (seconds) or prev_ts + cur_ts, and threshold.
    """
    context = ctx if isinstance(ctx, dict) else {}
    prev_msg = context.get("prev_msg", context.get("prev_text",
                                                  context.get("message_prev", "")))
    cur_msg = context.get("cur_msg", context.get("cur_text",
                                                 context.get("text",
                                                             context.get("message", ""))))
    dt = context.get("dt", context.get("gap"))
    if dt is None:
        try:
            dt = (float(context.get("cur_ts") or 0.0)
                  - float(context.get("prev_ts") or 0.0))
        except (TypeError, ValueError):
            dt = 0.0
    limit = context.get("threshold", BOUNDARY_THRESHOLD)
    try:
        limit = max(0.0, min(1.0, float(limit)))
    except (TypeError, ValueError):
        limit = BOUNDARY_THRESHOLD
    score = boundary_score(prev_msg, cur_msg, dt)
    return score >= limit, score


__all__ = ["enabled", "BOUNDARY_ENABLED", "boundary_score", "is_boundary",
           "BOUNDARY_THRESHOLD", "TIME_GAP_SECONDS", "SEMANTIC_WEIGHT",
           "TIME_WEIGHT", "TOPIC_WEIGHT"]
