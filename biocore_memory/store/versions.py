# -*- coding: utf-8 -*-
"""Version chain + dual-temporal helpers (store mechanism only)."""
from __future__ import annotations
from ..core.config import MAX_VERSIONS
from ..core.util import now_ts

DUAL_TEMPORAL_ENABLED = False


def record_version(entry, fields=None, limit=MAX_VERSIONS, dual_temporal=False):
    if not isinstance(entry, dict):
        return []
    fields = fields or ("text", "importance", "pin", "memory_source",
                        "memory_confidence", "identity_weight",
                        "valid_at", "invalid_at")
    if dual_temporal:
        entry.setdefault("valid_at", now_ts())
    snap = {k: entry.get(k) for k in fields if k in entry}
    history = entry.get("previous_versions")
    history = history if isinstance(history, list) else []
    entry["previous_versions"] = ([{"ts": now_ts(), "fields": snap}]
                                  + [x for x in history if isinstance(x, dict)])[:limit]
    return entry["previous_versions"]


def mark_invalid(entry_id, at=None):
    """Mark a fact/version invalid without deleting it (dual-temporal L7).

    Accepts a mutable entry dict (mutated in place, returned) or an id string
    (returns a patch dict for the caller/engine to apply). Default OFF: callers
    must gate this behind DUAL_TEMPORAL_ENABLED or a config switch.
    """
    stamp = now_ts(at)
    if isinstance(entry_id, dict):
        entry_id.setdefault("valid_at", stamp)
        entry_id["invalid_at"] = stamp
        return entry_id
    return {"id": str(entry_id or ""), "invalid_at": stamp}


def is_valid(entry, at=None):
    """True when the entry is valid at the supplied time (default: now)."""
    if not isinstance(entry, dict):
        return False
    stamp = now_ts(at)
    try:
        valid_at = float(entry.get("valid_at") or 0.0)
        invalid_at = float(entry.get("invalid_at") or 0.0)
    except Exception:
        return True
    if valid_at and stamp < valid_at:
        return False
    if invalid_at and stamp >= invalid_at:
        return False
    return True


def rollback(entry, index=0):
    if not isinstance(entry, dict):
        return None
    history = entry.get("previous_versions")
    if not isinstance(history, list) or len(history) <= index:
        return None
    snap = history[index].get("fields") if isinstance(history[index], dict) else None
    if not isinstance(snap, dict):
        return None
    entry.update(snap)
    entry["previous_versions"] = history[index + 1:]
    return entry
