# -*- coding: utf-8 -*-
"""L6 provenance: source hash tags + verifiable tombstone hash chain."""
from __future__ import annotations

import hashlib
import json

from ..core.util import now_ts

PROVENANCE_ENABLED = False
DELETED_TEXT = "（已删除）"


def _digest(text):
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def source_tag(text, source, ts=None):
    """Return {hash, source, ts} for a provenance-tagged entry (L6)."""
    return {"hash": _digest(text), "source": str(source or "")[:80],
            "ts": now_ts(ts)}


def verify(entry):
    """Verify an entry's provenance hash against its current text."""
    if not isinstance(entry, dict):
        return False
    tag = entry.get("provenance")
    if not isinstance(tag, dict):
        return False
    expected = tag.get("hash")
    return bool(expected) and expected == _digest(entry.get("text"))


def _tomb_payload(tomb):
    row = tomb if isinstance(tomb, dict) else {}
    return json.dumps({"id": str(row.get("id") or ""),
                       "ts": float(row.get("ts") or 0.0),
                       "reason": str(row.get("reason") or ""),
                       "text": str(row.get("text") or DELETED_TEXT),
                       "prev_hash": str(row.get("prev_hash") or "")},
                      ensure_ascii=False, sort_keys=True)


def make_tombstone(entry, prev_hash="", now=None, reason="deleted"):
    """Build a tombstone with prev_hash/hash fields (chain link)."""
    e = entry if isinstance(entry, dict) else {}
    tomb = {"id": str(e.get("id") or ""), "ts": now_ts(now),
            "reason": str(reason or "deleted")[:40], "text": DELETED_TEXT,
            "prev_hash": str(prev_hash or "")}
    tomb["hash"] = _digest(_tomb_payload(tomb))
    return tomb


def append_tombstone(tombstones, entry, now=None, reason="deleted"):
    """Append a hash-chained tombstone; returns the updated list."""
    rows = tombstones if isinstance(tombstones, list) else []
    prev = rows[-1].get("hash") if rows and isinstance(rows[-1], dict) else ""
    rows.append(make_tombstone(entry, prev_hash=prev, now=now, reason=reason))
    return rows


def verify_tombstone_chain(tombstones):
    """Verify prev_hash links and each tombstone hash; True when intact."""
    rows = [x for x in (tombstones or []) if isinstance(x, dict)]
    prev = ""
    for row in rows:
        if str(row.get("prev_hash") or "") != prev:
            return False
        if row.get("hash") != _digest(_tomb_payload(row)):
            return False
        prev = str(row.get("hash") or "")
    return True
