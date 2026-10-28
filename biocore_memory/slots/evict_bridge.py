# -*- coding: utf-8 -*-
"""Bridge slot eviction to existing evict 0.30/0.50 semantics."""
from __future__ import annotations

from ..core.util import clamp01

ARCHIVE_SCORE = 0.30
FLAG_SCORE = 0.50
STALE_SECONDS = 30 * 86400.0


def _rows(slots):
    rows = []
    if hasattr(slots, "slots"):
        for slot in slots.slots:
            for item in getattr(slot, "items", []) or []:
                entry = item if isinstance(item, dict) else {"text": str(item)}
                rows.append((entry, slot.slot_id))
    elif isinstance(slots, dict):
        raw = slots.get("slots")
        if isinstance(raw, dict):
            for sid, items in raw.items():
                for item in items or []:
                    entry = item if isinstance(item, dict) else {"text": str(item)}
                    rows.append((entry, sid))
    elif isinstance(slots, list):
        for entry in slots:
            rows.append((entry if isinstance(entry, dict) else {"text": str(entry)}, ""))
    return rows


def _eid(entry):
    return str(entry.get("id") or entry.get("memory_id") or "")


def pick_evictions(slots):
    """Return ids to evict when over capacity/char budget (empty otherwise)."""
    rows = _rows(slots)
    if not rows:
        return []
    capacity = getattr(slots, "capacity", None)
    if capacity is None and isinstance(slots, dict):
        capacity = slots.get("capacity", slots.get("capacity_slots"))
    try:
        capacity = int(capacity) if capacity is not None else 4
    except Exception:
        capacity = 4
    total_budget = getattr(slots, "budget_chars", None)
    if total_budget is None and isinstance(slots, dict):
        total_budget = slots.get("budget_chars", 360)
    try:
        total_budget = int(total_budget or 360)
    except Exception:
        total_budget = 360
    if hasattr(slots, "slots"):
        slot_count = len(slots.slots)
    elif isinstance(slots, dict):
        raw = slots.get("slots")
        slot_count = len(raw) if isinstance(raw, (list, dict)) else 0
    else:
        slot_count = len(rows)
    over_count = max(0, slot_count - capacity)
    total_chars = sum(len(str((e or {}).get("text") or "")) for e, _sid in rows)
    over_chars = max(0, total_chars - total_budget)
    if not over_count and not over_chars:
        return []
    need = max(over_count, 1 if over_chars else 0)
    now = float((slots.get("now") if isinstance(slots, dict) else getattr(slots, "now", 0.0)) or 0.0)

    def _score(entry):
        try:
            return clamp01(entry.get("slot_score", entry.get("score", 0.0)))
        except Exception:
            return 0.0

    def _rank(item):
        entry, _sid = item
        score = _score(entry)
        consequence = clamp01(entry.get("consequence", 0.5))
        try:
            age = max(0.0, now - float(entry.get("last_recall", entry.get("ts", 0.0)) or 0.0)) if now else 0.0
        except Exception:
            age = 0.0
        old_body = 1 if (entry.get("invalid_at") or entry.get("superseded")
                         or entry.get("previous_versions")) else 0
        if score < 0.12:
            bucket = 0
        elif consequence < FLAG_SCORE:
            bucket = 1
        elif age >= STALE_SECONDS:
            bucket = 2
        elif old_body:
            bucket = 3
        else:
            bucket = 4
        return (bucket, score, -age, _eid(entry))

    ranked = sorted(rows, key=_rank)
    out = []
    for entry, _sid in ranked:
        eid = _eid(entry)
        if eid and eid not in out:
            out.append(eid)
        if len(out) >= need:
            break
    return out
