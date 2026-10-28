# -*- coding: utf-8 -*-
"""Deterministic slot-switch triggers (no IO, no LLM)."""
from __future__ import annotations

from ..core.util import clamp01

BOUNDARY_THRESHOLD = 0.50
CUE_SWITCH = 0.45
TIME_GAP_SECONDS = 30 * 60
PREEMPT_SALIENCE = 0.80
PREEMPT_CUE = 0.60
DEFAULT_TTL = 6 * 3600


def should_switch(ctx):
    """Return (switch: bool, reason: str); pure function over ctx values."""
    c = ctx if isinstance(ctx, dict) else {}
    boundary = clamp01(c.get("boundary_score", c.get("boundary", 0.0)))
    if boundary >= BOUNDARY_THRESHOLD:
        return True, "event_boundary"
    if "cue_cosine" in c and float(c.get("cue_cosine") or 0.0) < CUE_SWITCH:
        return True, "topic_switch"
    now = float(c.get("now") or 0.0)
    last_ts = float(c.get("last_ts") or 0.0)
    if now and last_ts and (now - last_ts) >= TIME_GAP_SECONDS:
        return True, "time_gap"
    sal = clamp01(c.get("salience", 0.0))
    cue = clamp01(c.get("cue", 0.0))
    if sal >= PREEMPT_SALIENCE and cue >= PREEMPT_CUE:
        used_ts = float(c.get("preempt_used_ts") or 0.0)
        ttl = float(c.get("ttl_seconds") or DEFAULT_TTL)
        if not used_ts or (now and now - used_ts >= ttl):
            return True, "preemption"
    capacity = c.get("capacity", c.get("capacity_slots"))
    slot_count = c.get("slot_count")
    total_chars = c.get("total_chars")
    budget_chars = c.get("budget_chars")
    if capacity is not None and slot_count is not None and int(slot_count) > int(capacity):
        return True, "capacity_overflow"
    if budget_chars is not None and total_chars is not None and int(total_chars) > int(budget_chars):
        return True, "capacity_overflow"
    return False, "none"
