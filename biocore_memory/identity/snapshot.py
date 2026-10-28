# -*- coding: utf-8 -*-
"""Read-only identity snapshot."""
from __future__ import annotations
from .writeback import is_identity


def identity_snapshot(entries):
    rows = [e for e in (entries or []) if isinstance(e, dict) and is_identity(e)]
    rows.sort(key=lambda e: float(e.get("importance", 0.0) or 0.0), reverse=True)
    return {"count": len(rows),
            "ids": [str(e.get("id") or "") for e in rows[:20]],
            "texts": [str(e.get("text") or "")[:80] for e in rows[:5]],
            "version": 1}
