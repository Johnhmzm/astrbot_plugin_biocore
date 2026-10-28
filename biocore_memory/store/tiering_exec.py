# -*- coding: utf-8 -*-
"""Hot/warm tier budget execution: mark over-budget rows archived (no delete).

Module is disabled by default: callers MUST check `enabled` before consuming it.
Uses the existing pure tier_of() helper; entries are never removed, only marked
with archived/archive_reason/archived_ts. Input order is preserved.
"""
from __future__ import annotations

import time

from .tiering import HOT_BUDGET, WARM_BUDGET, tier_of

enabled = False
TIERING_EXEC_ENABLED = enabled

ARCHIVE_REASON = "tier_budget"


def apply_tiers(entries, now=None) -> dict:
    """Mark entries above tier budgets; return {archived:[ids], kept:int}."""
    rows = entries if isinstance(entries, list) else []
    try:
        stamp = float(now if now is not None else time.time())
    except Exception:
        stamp = time.time()
    budgets = {"hot": HOT_BUDGET, "warm": WARM_BUDGET}
    counts = {}
    archived = []
    kept = 0
    for index, entry in enumerate(rows):
        if not isinstance(entry, dict):
            kept += 1
            continue
        if bool(entry.get("archived")):
            continue
        tier = tier_of(entry, stamp)
        counts[tier] = int(counts.get(tier, 0)) + 1
        budget = budgets.get(tier)
        if budget is not None and counts[tier] > budget:
            entry["archived"] = True
            entry["archive_reason"] = ARCHIVE_REASON
            entry["archived_ts"] = round(stamp, 3)
            archived.append(str(entry.get("id") or index))
        else:
            kept += 1
    return {"archived": archived, "kept": kept}


__all__ = ["enabled", "TIERING_EXEC_ENABLED", "apply_tiers", "ARCHIVE_REASON"]
