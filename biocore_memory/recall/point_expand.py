# -*- coding: utf-8 -*-
"""Point-expand: hit first, then grow the neighbourhood of the hit only.

Retrieval stays exactly the precise layer (embedding + lexical + rerank): the
top-k hits are the only source of candidates. What changes is the block around
them: each hit pulls its immediately adjacent memories from the SAME event
segment (+/- neighbour, default 1), so the answer arrives with its context
instead of a bare fragment. Entries without an event_id are never expanded --
there is no segment to grow into.

Ordering: segments by their best hit, inside a segment by event_index / ts.
Budget: tokens; when it runs out the expanded lines go first, hits stay.
"""
from __future__ import annotations

import re

from ..core.config import POINT_EXPAND_RADIUS, POINT_EXPAND_TOKENS

SWITCH_KEY = "point_expand"
SWITCH_ENV = "BIOCORE_POINT_EXPAND"
RADIUS_KEY = "point_expand_radius"
RADIUS_ENV = "BIOCORE_POINT_EXPAND_RADIUS"
TOKENS_KEY = "point_expand_tokens"
TOKENS_ENV = "BIOCORE_POINT_EXPAND_TOKENS"

_TOKEN = re.compile(r"[A-Za-z0-9]+|[^\sA-Za-z0-9]")


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _id(entry):
    return str((entry or {}).get("id") or "")


def _flag(flags, key):
    data = flags if isinstance(flags, dict) else {}
    if key in data:
        return data.get(key)
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    return switches.get(key)


def enabled(flags=None, env=None):
    """point_expand: flag > switches > env > default OFF."""
    data = _flag(flags, SWITCH_KEY)
    if isinstance(data, bool):
        return data
    environ = env if hasattr(env, "get") else None
    if environ is not None and SWITCH_ENV in environ:
        raw = str(environ.get(SWITCH_ENV)).strip().lower()
        if raw in ("1", "true", "on", "yes"):
            return True
        if raw in ("0", "false", "off", "no"):
            return False
    return False


def radius(flags=None, env=None):
    raw = _flag(flags, RADIUS_KEY)
    environ = env if hasattr(env, "get") else None
    if raw is None and environ is not None and RADIUS_ENV in environ:
        raw = environ.get(RADIUS_ENV)
    try:
        value = int(raw)
    except Exception:
        value = int(POINT_EXPAND_RADIUS)
    return max(0, min(3, value))


def token_budget(flags=None, env=None):
    raw = _flag(flags, TOKENS_KEY)
    environ = env if hasattr(env, "get") else None
    if raw is None and environ is not None and TOKENS_ENV in environ:
        raw = environ.get(TOKENS_ENV)
    try:
        value = int(raw)
    except Exception:
        value = int(POINT_EXPAND_TOKENS)
    return max(50, value)


def tokens(text):
    """Cheap token estimate: one per CJK/other char, one per 4 latin chars."""
    count = 0
    for match in _TOKEN.finditer(str(text or "")):
        piece = match.group(0)
        if piece.isascii() and piece.isalnum():
            count += (len(piece) + 3) // 4
        else:
            count += 1
    return count


def _sort_key(entry):
    return (_num(entry.get("ts"), 0.0), int(_num(entry.get("event_index"), 0)),
            _id(entry))


def by_event(entries):
    """event_id -> members, already in segment time order."""
    buckets = {}
    for entry in entries or []:
        if not isinstance(entry, dict) or entry.get("deleted"):
            continue
        event_id = str(entry.get("event_id") or "").strip()
        if not event_id:
            continue
        buckets.setdefault(event_id, []).append(entry)
    for event_id in buckets:
        buckets[event_id].sort(key=_sort_key)
    return buckets


def neighbours(hits, entries, radius_value=None):
    """The +/- neighbour of each hit inside its own event; never the whole段."""
    span = radius(radius_value) if radius_value is None else max(0, int(radius_value))
    buckets = by_event(entries)
    hit_ids = {_id(hit) for hit in hits or []}
    picked = []
    for hit in hits or []:
        event_id = str((hit or {}).get("event_id") or "").strip()
        if not event_id or span <= 0:
            continue
        members = buckets.get(event_id) or []
        ids = [_id(member) for member in members]
        try:
            at = ids.index(_id(hit))
        except ValueError:
            continue
        for offset in range(1, span + 1):
            for index in (at - offset, at + offset):
                if 0 <= index < len(members):
                    member = members[index]
                    if _id(member) not in hit_ids:
                        picked.append(member)
    seen = set()
    unique = []
    for entry in picked:
        if _id(entry) not in seen:
            seen.add(_id(entry))
            unique.append(entry)
    return unique


def order(rows):
    """rows: [{entry, score, hit}] -> segment best-first, time inside."""
    segments = {}
    for row in rows or []:
        entry = row.get("entry") or {}
        key = str(entry.get("event_id") or ("solo:" + _id(entry)))
        slot = segments.setdefault(key, {"key": key, "best": None, "rows": []})
        slot["rows"].append(row)
        score = _num(row.get("score"), 0.0)
        if row.get("hit") and (slot["best"] is None or score > slot["best"]):
            slot["best"] = score
    ordered = []
    for key in sorted(segments,
                      key=lambda name: (-(_num(segments[name]["best"], -1.0)),
                                        name)):
        slot = segments[key]
        slot["rows"].sort(key=lambda row: _sort_key(row.get("entry")))
        ordered.extend(slot["rows"])
    return ordered
