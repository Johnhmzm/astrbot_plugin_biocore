# -*- coding: utf-8 -*-
"""Soft/hard delete tombstones (text is redacted)."""
from __future__ import annotations
from ..core.config import TOMBSTONE_LIMIT
from ..core.util import now_ts

DELETED_TEXT = "（已删除）"


def make_tombstone(entry, now=None, reason="deleted"):
    e = entry if isinstance(entry, dict) else {}
    return {"id": str(e.get("id") or ""),
            "ts": now_ts(now), "reason": str(reason)[:40],
            "text": DELETED_TEXT,
            "fields": {"role": e.get("role"),
                       "importance": e.get("importance")}}


def append_tombstone(tombstones, entry, now=None, reason="deleted"):
    rows = tombstones if isinstance(tombstones, list) else []
    rows.append(make_tombstone(entry, now, reason))
    del rows[:-TOMBSTONE_LIMIT]
    return rows
