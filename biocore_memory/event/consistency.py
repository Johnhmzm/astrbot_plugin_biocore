# -*- coding: utf-8 -*-
"""Old/new fact conflict detection (default OFF; no word list).

The predicate lexicon was removed: telling "likes" from "weighs" from "wants"
needs semantics the core does not have. The mechanism stays off and says so;
a caller that knows the fact slots can compare them itself.
"""
from __future__ import annotations

CONSISTENCY_ENABLED = False
DISABLED_REASON = "no_lexicon"


def detect_conflicts(entry, old_entries):
    """Always neutral: conflict detection would need a predicate lexicon."""
    return {"conflict": False, "uncertainty": 0.0, "target_ids": [],
            "details": [], "disabled_reason": DISABLED_REASON}


def annotate(entry, result):
    """Attach conflict metadata to a copy; never overwrites the old facts/text."""
    row = dict(entry) if isinstance(entry, dict) else {"text": str(entry or "")}
    if not isinstance(result, dict) or not result.get("conflict"):
        return row
    row["conflict"] = True
    row["uncertainty"] = float(result.get("uncertainty") or 0.0)
    row["conflict_with"] = list(result.get("target_ids") or [])
    return row
