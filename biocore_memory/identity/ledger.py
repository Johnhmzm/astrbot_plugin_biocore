# -*- coding: utf-8 -*-
"""Relationship ledger: write relation events as system memory entries.

Conflicts, repairs and milestones become role="system" entries with
source="relation_ledger" carrying kind / trust_delta / conflict_delta.
Writes are idempotent per (kind, day): the same kind of relationship change is
recorded at most once per day, so replays never duplicate the ledger.

Interface:
  append_entry(store, event, now=None, enabled=None)
      -> {"written": [id], "skipped": [...], "kind": str, "day": str}
      store: MemoryStore-like object (entries list + add()) or {"entries": []};
      event: {kind?, trust_delta?, conflict_delta?, ts?, day?, session?,
              scope?, text?, summary?}; a missing kind is inferred from the
              delta signs (conflict / repair / milestone).

The module is disabled by default (LEDGER_ENABLED=False): callers gate on
'enabled' before writing. No IO, no LLM, no host imports; the caller decides
when to store.save().
"""
from __future__ import annotations

import time

from ..core.util import clamp01, now_ts, sha12

enabled = False
LEDGER_ENABLED = enabled
SOURCE = "relation_ledger"
KINDS = ("conflict", "repair", "milestone")
MAX_DELTA = 1.0
TEXT_MAX = 200

_KIND_ALIASES = {
    "conflict": ("conflict", "clash", "rupture", "冲突", "矛盾", "争执"),
    "repair": ("repair", "reconcile", "apology", "修复", "和解", "道歉"),
    "milestone": ("milestone", "turning_point", "promise", "里程碑", "转折", "承诺"),
}
_LABELS = {"conflict": "冲突", "repair": "修复", "milestone": "里程碑"}


def _rows(store):
    try:
        rows = getattr(store, "entries", None)
        if isinstance(rows, list):
            return rows
    except Exception:
        pass
    if isinstance(store, dict):
        rows = store.get("entries")
        return rows if isinstance(rows, list) else []
    try:
        return list(store or [])
    except TypeError:
        return []


def _add(store, entry):
    try:
        fn = getattr(store, "add", None)
        if callable(fn):
            return fn(entry)
        if isinstance(store, dict):
            store.setdefault("entries", []).append(entry)
            return entry
        store.append(entry)
        return entry
    except Exception:
        return None


def _event_value(event, key, default=None):
    if isinstance(event, dict):
        if event.get(key) is not None:
            return event.get(key)
        metadata = event.get("metadata")
        if isinstance(metadata, dict) and metadata.get(key) is not None:
            return metadata.get(key)
        return default
    return getattr(event, key, default)


def _delta(value):
    try:
        value = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if value != value or value in (float("inf"), float("-inf")):
        return 0.0
    return round(max(-MAX_DELTA, min(MAX_DELTA, value)), 4)


def _day(ts):
    if ts <= 0.0:
        return "unknown"
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(ts))
    except (OverflowError, OSError, ValueError):
        return "unknown"


def _kind(event, trust_delta, conflict_delta):
    raw = str(_event_value(event, "kind", "") or "").strip().lower()
    for kind in KINDS:
        aliases = _KIND_ALIASES.get(kind, ())
        if raw == kind or raw in aliases or any(alias in raw for alias in aliases):
            return kind
    if conflict_delta > 0.0 or trust_delta < 0.0:
        return "conflict"
    if conflict_delta < 0.0 or trust_delta > 0.0:
        return "repair"
    return "milestone"


def _text(event, kind, trust_delta, conflict_delta):
    raw = _event_value(event, "text") or _event_value(event, "summary") or ""
    text = " ".join(str(raw or "").split())
    if not text:
        text = "关系账本 %s：trust %+0.2f / conflict %+0.2f" % (
            _LABELS.get(kind, kind), trust_delta, conflict_delta)
    return text[:TEXT_MAX]


def _existing(rows, kind, day):
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("source") or "") != SOURCE:
            continue
        metadata = entry.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        entry_kind = str(entry.get("kind") or metadata.get("kind") or "")
        entry_day = str(entry.get("day") or metadata.get("day") or "")
        if entry_kind == kind and entry_day == day:
            return entry
    return None


def append_entry(store, event, now=None, enabled=None):
    """Append one idempotent (kind, day) relationship-ledger entry."""
    result = {"written": [], "skipped": []}
    if enabled is False:
        result["skipped"].append({"reason": "disabled"})
        return result
    if store is None:
        result["skipped"].append({"reason": "invalid_store"})
        return result
    trust_delta = _delta(_event_value(event, "trust_delta", 0.0))
    conflict_delta = _delta(_event_value(event, "conflict_delta", 0.0))
    kind = _kind(event, trust_delta, conflict_delta)
    try:
        stamp = float(_event_value(event, "ts", 0.0) or 0.0)
    except (TypeError, ValueError):
        stamp = 0.0
    if stamp <= 0.0:
        stamp = now_ts(now)
    day = str(_event_value(event, "day") or "") or _day(stamp)
    rows = _rows(store)
    duplicate = _existing(rows, kind, day)
    if duplicate is not None:
        result["skipped"].append({"reason": "duplicate",
                                  "id": str(duplicate.get("id") or ""),
                                  "kind": kind, "day": day})
        return result
    importance = round(clamp01(0.5 + 0.2 * (abs(trust_delta)
                                            + abs(conflict_delta))), 4)
    entry = {"id": SOURCE + "_" + sha12(kind + "|" + day),
             "text": _text(event, kind, trust_delta, conflict_delta),
             "role": "system", "source": SOURCE, "ts": stamp,
             "importance": importance, "kind": kind,
             "trust_delta": trust_delta, "conflict_delta": conflict_delta,
             "day": day,
             "metadata": {"origin": SOURCE, "kind": kind, "day": day,
                          "trust_delta": trust_delta,
                          "conflict_delta": conflict_delta,
                          "event_id": str(_event_value(event, "id") or "")}}
    for key in ("session", "scope"):
        value = _event_value(event, key)
        if value:
            entry[key] = str(value)
    added = _add(store, entry)
    if not isinstance(added, dict):
        result["skipped"].append({"reason": "add_failed"})
        return result
    result["written"].append(str(added.get("id") or entry["id"]))
    result["kind"] = kind
    result["day"] = day
    return result


__all__ = ["enabled", "LEDGER_ENABLED", "append_entry", "SOURCE", "KINDS"]
