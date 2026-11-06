# -*- coding: utf-8 -*-
"""Consequence-aware eviction (pure; default OFF; no word list).

Text is never scanned for promise/deadline/risk words: the caller states those
on the entry (promise / deadline / risk / consequence). Without them the score
is importance only, which is the old behaviour.
"""
from __future__ import annotations

from ..core.util import clamp01

CONSEQUENCE_ENABLED = False
DISABLED_REASON = "no_lexicon"


def _score(entry):
    e = entry if isinstance(entry, dict) else {}
    importance = clamp01(e.get("importance"), 0.5)
    promise = 0.30 if e.get("promise") else 0.0
    deadline = 0.25 if e.get("deadline") else 0.0
    risk = 0.20 if e.get("risk") else 0.0
    explicit = 0.25 * clamp01(e.get("consequence"), 0.0) if "consequence" in e else 0.0
    return clamp01(0.35 * importance + promise + deadline + risk + explicit, 0.0)


def consequence(entry):
    """0..1 consequence of forgetting an entry (higher = should keep)."""
    if not CONSEQUENCE_ENABLED or not isinstance(entry, dict):
        return 0.0
    try:
        return round(_score(entry), 4)
    except Exception:
        return 0.0


def select_by_consequence(entries, budget):
    """Return ids to evict first: lowest consequence, protected entries skipped."""
    if not CONSEQUENCE_ENABLED:
        return []
    try:
        limit = max(0, int(budget or 0))
    except Exception:
        limit = 0
    if not limit:
        return []
    rows = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("pin") or entry.get("pinned") or entry.get("self_defining") or entry.get("identity"):
            continue
        rows.append((_score(entry), str(entry.get("id") or entry.get("memory_id") or "")))
    rows.sort(key=lambda row: (row[0], row[1]))
    return [eid for _score_value, eid in rows if eid][:limit]
