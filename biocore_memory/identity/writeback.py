# -*- coding: utf-8 -*-
"""Identity write-back gate: evidence>=3 same direction or major event,
single step <=0.02; all writes are version-chained by the store."""
from __future__ import annotations
from ..core.config import MAX_STEP, SAME_DIRECTION_MIN

IDENTITY_FIELDS = ("self_defining", "identity", "identity_relevant")
MAJOR_TRIGGERS = ("major_event", "重大事件", "重大", "crisis", "commitment")


def is_identity(entry):
    e = entry if isinstance(entry, dict) else {}
    return any(bool(e.get(k)) for k in IDENTITY_FIELDS)


def _sign(value):
    try:
        return 1 if float(value or 0) >= 0 else -1
    except Exception:
        return 1


def evidence_count(evidence, delta=0.0):
    """Count same-direction evidence items (dict direction or signed numbers)."""
    direction = _sign(delta)
    total = 0
    for item in evidence or []:
        if isinstance(item, dict):
            d = item.get("direction", item.get("delta", direction))
        else:
            d = direction
        if _sign(d) == direction:
            total += 1
    return total


def is_major_trigger(trigger):
    value = str(trigger or "").lower()
    return any(str(word).lower() in value for word in MAJOR_TRIGGERS)


def writeback_gate(direction_count=0, major_event=False, step=0.0):
    try:
        step = max(-MAX_STEP, min(MAX_STEP, float(step or 0.0)))
    except Exception:
        step = 0.0
    allowed = bool(major_event or int(direction_count or 0) >= SAME_DIRECTION_MIN)
    return allowed, step


def writeback_decision(state, direction=1, major_event=False, step=0.01):
    st = state if isinstance(state, dict) else {}
    streak = int(st.get("streak", 0) or 0)
    last_dir = int(st.get("last_dir", 0) or 0)
    d = _sign(direction)
    streak = streak + 1 if last_dir == d else 1
    allowed, clamped = writeback_gate(streak, major_event, step)
    new_state = {"streak": streak, "last_dir": d, "major_event": bool(major_event)}
    if not allowed:
        return False, 0.0, new_state, "need_more_same_direction"
    return True, clamped * d, new_state, "major_event" if major_event else "same_direction_3"
