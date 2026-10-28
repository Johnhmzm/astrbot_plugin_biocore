# -*- coding: utf-8 -*-
"""Retrieval-induced forgetting (RIF) inhibition (pure; default OFF).

Retrieving a target suppresses competing memories (Anderson, Bjork & Bjork
1994). Entries that lost the retrieval competition get a bounded inhibition
budget that decays with a 7-day half-life.

Interface:
  mark_inhibited(entries, selected_ids, increment=0.2, cap=1.0) -> [ids]
      Adds 'increment' to every entry whose id is not in selected_ids
      (in place, bounded by cap) and returns the touched ids in input order.
  decay(entry, days=7.0) -> float
      Inhibition value after 'days' of exponential decay (7-day half-life).
  filter_inhibited(entries, threshold=0.5, days=None) -> list
      Entries whose (optionally decayed) inhibition is below the threshold.

The module is disabled by default: callers gate on 'enabled' before applying
mutations. Helpers are deterministic and never touch the file system.
"""
from __future__ import annotations

import math

enabled = False
INHIBITION_ENABLED = enabled

INCREMENT = 0.2
MAX_INHIBITION = 1.0
HALF_LIFE_DAYS = 7.0
THRESHOLD = 0.5


def _num(value, default=0.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _clamp(value, low, high):
    return max(low, min(high, value))


def _entry_id(entry):
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("id") or entry.get("memory_id") or "")


def _value(entry):
    if not isinstance(entry, dict):
        return 0.0
    return _clamp(_num(entry.get("inhibition", 0.0), 0.0), 0.0, MAX_INHIBITION)


def _rows(entries):
    try:
        return list(entries or [])
    except TypeError:
        return []


def mark_inhibited(entries, selected_ids, increment=INCREMENT,
                   cap=MAX_INHIBITION):
    """Inhibit every unselected entry by 'increment' (bounded); return ids."""
    selected = {str(value) for value in (selected_ids or []) if str(value)}
    step = _clamp(_num(increment, INCREMENT), 0.0, MAX_INHIBITION)
    ceiling = _clamp(_num(cap, MAX_INHIBITION), 0.0, MAX_INHIBITION)
    touched = []
    for entry in _rows(entries):
        entry_id = _entry_id(entry)
        if not entry_id or entry_id in selected:
            continue
        old = _value(entry)
        new = min(ceiling, old + step)
        if new <= old:
            continue
        entry["inhibition"] = round(new, 4)
        touched.append(entry_id)
    return touched


def decay(entry, days=HALF_LIFE_DAYS):
    """Return the inhibition after 'days' of decay (7-day half-life)."""
    age = max(0.0, _num(days, HALF_LIFE_DAYS))
    return round(_value(entry) * math.pow(0.5, age / HALF_LIFE_DAYS), 4)


def filter_inhibited(entries, threshold=THRESHOLD, days=None):
    """Return entries with inhibition below 'threshold' (not suppressed)."""
    limit = _clamp(_num(threshold, THRESHOLD), 0.0, MAX_INHIBITION)
    kept = []
    for entry in _rows(entries):
        if not isinstance(entry, dict):
            continue
        value = _value(entry) if days is None else decay(entry, days)
        if value < limit:
            kept.append(entry)
    return kept


__all__ = ["enabled", "INHIBITION_ENABLED", "mark_inhibited", "decay",
           "filter_inhibited", "INCREMENT", "MAX_INHIBITION",
           "HALF_LIFE_DAYS", "THRESHOLD"]
