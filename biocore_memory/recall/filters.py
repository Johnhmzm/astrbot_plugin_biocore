# -*- coding: utf-8 -*-
"""FAMA invalid-memory filtering (default OFF; pure, host-neutral).

Dual-temporal fields live in store/versions.py: valid_at/invalid_at. This
module only selects candidates; it never mutates or deletes entries.
"""
from __future__ import annotations

try:
    from ..store.versions import is_valid as _entry_is_valid
except Exception:  # pragma: no cover - degraded mode
    def _entry_is_valid(entry, at=None):
        return True

enabled = False
ENABLED = False
VALID_MODE = "now"
INVALID_MODE = "then"


def is_valid(entry, at=None):
    """True when the entry is valid at time at (default now)."""
    try:
        return bool(_entry_is_valid(entry, at))
    except Exception:
        return True


def filter_valid(entries, at=None, mode="now"):
    """Filter entries by validity.

    mode="now"  -> only currently valid entries (default);
    mode="then" -> only invalid/superseded entries (historical query);
    mode=None   -> no filtering (return all dict entries).
    """
    rows = [e for e in (entries or []) if isinstance(e, dict)]
    if mode is None:
        return rows
    want_valid = str(mode).lower() not in ("then", "invalid", "expired")
    return [e for e in rows if is_valid(e, at) == want_valid]
