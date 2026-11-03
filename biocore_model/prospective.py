# -*- coding: utf-8 -*-
"""Prospective memory: things she said she would ask about, and when.

Two kinds of commitments matter for a companion:

- her_promise  she said she would do/ask something ('明天问你结果')
- his_event    he mentioned something dated ('周五体检')

A commitment is a small dict; everything here is a pure function over a
list of them, so the caller owns storage and time:

  {'id': '...', 'kind': 'her_promise', 'text': '问他体检结果',
   'due_ts': 1790000000.0, 'created_ts': 1789990000.0,
   'status': 'pending', 'source': 'chat', 'meta': {}}

Status flow: pending -> done | dropped | overdue.
Overdue only kicks in after a grace period, so a due item is not
'failed' the same minute it comes due.

Reference: 'Memory That Looks Forward' (prospective memory retrieval) and
the auto-commit practice of turning 'remember to act' into guaranteed
execution.

Pure functions only: no IO, no host imports, no LLM calls.
"""
from __future__ import annotations

import hashlib
import re

KINDS = ("her_promise", "his_event")
STATUSES = ("pending", "done", "dropped", "overdue")
DEFAULT_GRACE_S = 6 * 3600.0
MAX_ITEMS = 200

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[，。！？、,.!?;；:：\"'“”‘’（）()\[\]【】]")

def normalize(text):
    """Normalize free text for deduplication."""
    raw = _PUNCT.sub("", str(text or ""))
    return _WS.sub("", raw).strip().lower()

def make_id(kind, text, due_ts=None):
    """Stable id: same kind + same text -> same commitment.

    The deadline is deliberately excluded so that rescheduling the same
    commitment ("体检改到下周") merges into the existing record instead of
    creating a twin.
    """
    base = "%s|%s" % (str(kind or ""), normalize(text))
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]

def _num(value, default=0.0):
    try:
        num = float(value)
    except Exception:
        return default
    if num != num:
        return default
    return num

def entry(kind, text, due_ts, now=None, source="chat", meta=None):
    """Build one commitment record (does not store it)."""
    due = _num(due_ts, 0.0)
    created = _num(now, 0.0)
    return {
        "id": make_id(kind, text, due),
        "kind": str(kind or "his_event"),
        "text": str(text or "")[:80],
        "due_ts": round(due, 3),
        "created_ts": round(created, 3),
        "status": "pending",
        "source": str(source or "chat")[:20],
        "meta": dict(meta) if isinstance(meta, dict) else {},
    }

def add(store, record):
    """Insert one record, deduplicating by id. Returns (store, changed)."""
    items = [dict(row) for row in (store or []) if isinstance(row, dict)]
    if not isinstance(record, dict) or not record.get("id"):
        return items, False
    for index, old in enumerate(items):
        if old.get("id") == record["id"]:
            if old.get("status") in ("done", "dropped"):
                return items, False
            merged = dict(old)
            merged["due_ts"] = max(_num(old.get("due_ts")),
                                   _num(record.get("due_ts")))
            merged["meta"] = {**(old.get("meta") or {}),
                              **(record.get("meta") or {})}
            items[index] = merged
            return items, True
    items.append(dict(record))
    if len(items) > MAX_ITEMS:
        items.sort(key=lambda row: (_num(row.get("due_ts")),
                                       _num(row.get("created_ts"))))
        items = items[-MAX_ITEMS:]
    return items, True

def _active(store):
    return [row for row in (store or []) if isinstance(row, dict)
            and row.get("status") in ("pending", "overdue")]

def due_now(store, now, window_s=0.0):
    """Commitments whose deadline is inside [now - window, now]."""
    now = _num(now)
    window = max(0.0, _num(window_s))
    rows = [row for row in _active(store)
            if now - window <= _num(row.get("due_ts")) <= now]
    rows.sort(key=lambda row: _num(row.get("due_ts")))
    return rows

def due_soon(store, now, ahead_s=24 * 3600.0):
    """Commitments coming due within the next ahead_s seconds."""
    now = _num(now)
    ahead = max(0.0, _num(ahead_s, 24 * 3600.0))
    rows = [row for row in _active(store)
            if now < _num(row.get("due_ts")) <= now + ahead]
    rows.sort(key=lambda row: _num(row.get("due_ts")))
    return rows

def mark_overdue(store, now, grace_s=DEFAULT_GRACE_S):
    """Flag pending items past deadline + grace. Returns (store, count)."""
    now = _num(now)
    grace = max(0.0, _num(grace_s, DEFAULT_GRACE_S))
    items = [dict(row) for row in (store or []) if isinstance(row, dict)]
    changed = 0
    for index, row in enumerate(items):
        if row.get("status") != "pending":
            continue
        if _num(row.get("due_ts")) + grace < now:
            row["status"] = "overdue"
            items[index] = row
            changed += 1
    return items, changed

def resolve(store, commitment_id, status="done", now=None):
    """Mark one commitment done/dropped. Returns (store, changed)."""
    if status not in ("done", "dropped"):
        return list(store or []), False
    items = [dict(row) for row in (store or []) if isinstance(row, dict)]
    for index, row in enumerate(items):
        if row.get("id") == commitment_id:
            row["status"] = status
            row["resolved_ts"] = round(_num(now), 3)
            items[index] = row
            return items, True
    return items, False

_HINTS = {
    "her_promise": "你答应过要问一句",
    "his_event": "他提过的事到了",
}

def build_hint(record, now=None):
    """One short line the interaction layer may turn into a question."""
    if not isinstance(record, dict):
        return ""
    kind = str(record.get("kind") or "his_event")
    text = str(record.get("text") or "").strip()
    if not text:
        return ""
    prefix = _HINTS.get(kind, "记着这件事")
    late = (_num(record.get("due_ts")) + DEFAULT_GRACE_S < _num(now or 0)
            or record.get("status") == "overdue")
    if late:
        return "%s：%s（还没问）" % (prefix, text)
    return "%s：%s" % (prefix, text)

def stats(store):
    """Counts by status and kind, for panels and logs."""
    items = [row for row in (store or []) if isinstance(row, dict)]
    by_status = {name: 0 for name in STATUSES}
    by_kind = {name: 0 for name in KINDS}
    for row in items:
        status = str(row.get("status") or "pending")
        if status in by_status:
            by_status[status] += 1
        kind = str(row.get("kind") or "his_event")
        if kind in by_kind:
            by_kind[kind] += 1
    return {"total": len(items), "by_status": by_status, "by_kind": by_kind}
