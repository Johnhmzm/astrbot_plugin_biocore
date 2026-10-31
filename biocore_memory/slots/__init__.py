# OWNER: legacy
# -*- coding: utf-8 -*-
"""Attention-window slots (default OFF; host-neutral, no astrbot/L1)."""
from .registry import (DEFAULT_BUDGET_CHARS, DEFAULT_SLOT_COUNT, FIXED_KINDS,
                       MAX_DYNAMIC, MAX_ITEMS, MAX_SLOTS, TOTAL_BUDGET_CHARS,
                       Slot, SlotRegistry)
from .admission import (FLOOR_CUE, FLOOR_GOAL, FLOOR_SALIENCE, INDEX_ONLY,
                        THRESHOLD, admission, goal, salience, slot_score)
from .switch import should_switch
from .evict_bridge import pick_evictions

__all__ = [
    "Slot", "SlotRegistry", "DEFAULT_SLOT_COUNT", "MAX_SLOTS", "MAX_DYNAMIC",
    "MAX_ITEMS", "DEFAULT_BUDGET_CHARS", "TOTAL_BUDGET_CHARS", "FIXED_KINDS",
    "slot_score", "admission", "salience", "goal", "THRESHOLD", "INDEX_ONLY",
    "FLOOR_SALIENCE", "FLOOR_CUE", "FLOOR_GOAL", "should_switch",
    "pick_evictions",
]
