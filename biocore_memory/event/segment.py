# -*- coding: utf-8 -*-
"""Event segmentation (Zacks 2007): a session is cut at change points.

Two adjacent memories of one session belong to the same event when any of
these holds: the gap is shorter than the event window, they share a topic tag,
or they are about the same people. The segment carries a deterministic id and
the entry keeps its own coordinates; a recall can widen a hit by its segment
neighbours when the host turns spatial_event_expand on.
"""
from __future__ import annotations

import hashlib
import os

from ..core.config import EVENT_WINDOW_SECONDS

WINDOW_KEY = "event_window"
WINDOW_ENV = "BIOCORE_EVENT_WINDOW"


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def window(flags=None, env=None):
    """Event window in seconds: flags > env > core/config.py."""
    data = flags if isinstance(flags, dict) else {}
    raw = data.get(WINDOW_KEY)
    if raw is None and isinstance(data.get("switches"), dict):
        raw = data["switches"].get(WINDOW_KEY)
    environ = env if hasattr(env, "get") else None
    if raw is None and environ is not None and WINDOW_ENV in environ:
        raw = environ.get(WINDOW_ENV)
    try:
        value = float(raw)
    except Exception:
        value = float(EVENT_WINDOW_SECONDS)
    return max(0.0, value)


def _scope(entry):
    return str(entry.get("scope") or entry.get("session_id") or "default")


def _topics(entry):
    values = []
    for key in ("tags", "concepts"):
        raw = entry.get(key)
        if isinstance(raw, str):
            raw = [raw]
        for item in raw or []:
            text = str(item or "").strip().lower()
            if text:
                values.append(text)
    return set(values)


def _participants(entry):
    raw = entry.get("participants")
    if isinstance(raw, str):
        raw = [raw]
    values = {str(item or "").strip() for item in (raw or []) if str(item or "").strip()}
    scope = str(entry.get("social_scope") or "").strip()
    if scope:
        values.add(scope)
    return values


def same_event(previous, entry, window_seconds=None):
    """True when two adjacent memories belong to one event segment."""
    if not isinstance(previous, dict) or not isinstance(entry, dict):
        return False
    span = window_seconds if window_seconds is not None else float(EVENT_WINDOW_SECONDS)
    gap = abs(_num(entry.get("ts")) - _num(previous.get("ts")))
    if gap < span:
        return True
    if _topics(previous) & _topics(entry):
        return True
    if _participants(previous) & _participants(entry):
        return True
    return False


def _new_id(scope, ts):
    body = "%s|%.3f" % (str(scope or "default"), _num(ts))
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]


def assign(entry, entries, now=None, window_seconds=None):
    """Give one new entry its segment; returns the report (never raises)."""
    if not isinstance(entry, dict):
        return None
    scope = _scope(entry)
    stamp = _num(entry.get("ts"), _num(now, 0.0))
    previous = None
    for other in entries or []:
        if not isinstance(other, dict) or other is entry:
            continue
        if other.get("deleted") or other.get("archived"):
            continue
        if _scope(other) != scope:
            continue
        if _num(other.get("ts")) > stamp:
            continue          # only the entry written before this one counts
        if previous is None or _num(other.get("ts")) > _num(previous.get("ts")):
            previous = other
    continued = previous is not None and same_event(previous, entry, window_seconds)
    if continued:
        event_id = str(previous.get("event_id") or "")
        if not event_id:
            event_id = _new_id(scope, _num(previous.get("ts"), stamp))
            previous["event_id"] = event_id
            previous.setdefault("event_index", 0)
        index = int(_num(previous.get("event_index"), 0)) + 1
    else:
        event_id = _new_id(scope, stamp)
        index = 0
    entry["event_id"] = event_id
    entry["event_index"] = index
    return {"event_id": event_id, "index": index, "continued": bool(continued)}


def expand(rows, entries, limit=2, per_hit=2):
    """Bring the neighbours of a hit's own event along (switch decides)."""
    rows = [row for row in (rows or []) if isinstance(row, dict)]
    if not rows:
        return rows
    by_event = {}
    for entry in entries or []:
        if not isinstance(entry, dict) or entry.get("deleted"):
            continue
        event_id = str(entry.get("event_id") or "")
        if not event_id:
            continue
        by_event.setdefault(event_id, []).append(entry)
    for bucket in by_event.values():
        bucket.sort(key=lambda item: _num(item.get("event_index")))
    present = {str((row.get("entry") or {}).get("id") or "") for row in rows}
    out = list(rows)
    added = 0
    cap = max(0, int(per_hit) * max(1, int(limit)))
    for row in rows[:max(1, int(limit))]:
        entry = row.get("entry") if isinstance(row.get("entry"), dict) else {}
        event_id = str(entry.get("event_id") or "")
        if not event_id:
            continue
        index = int(_num(entry.get("event_index"), 0))
        for neighbour in by_event.get(event_id, []):
            if added >= cap:
                break
            neighbour_id = str(neighbour.get("id") or "")
            if neighbour_id in present:
                continue
            if abs(int(_num(neighbour.get("event_index"), 0)) - index) > 1:
                continue
            out.append({"entry": neighbour, "score": 0.0,
                        "mode": "event_expand", "event_expand": True,
                        "tier": "low"})
            present.add(neighbour_id)
            added += 1
    return out
