# -*- coding: utf-8 -*-
"""Narrative-identity update after consolidation (pure; default OFF).

Narrative identity integrates past and present into a story (McAdams & McLean
2013). A narrative is rewritten only when one theme repeats across time:
>= MIN_ENTRIES same-theme memories spanning >= MIN_SPAN_DAYS days. Each update
appends the previous section to a bounded version chain, so the old narrative
is retained and rollback is possible.

Interface:
  theme_of(entry) -> str
  group_entries(entries) -> {theme: [entries]}
  theme_span_days(entries) -> float
  narrative_text(theme, entries) -> str
  narrative_candidate(entries) -> dict | None
  section(identity) -> {text, theme, version, history, entry_ids, ts}
  plan_update(identity, entries, now=None, enabled=None) -> dict
  apply_update(store, identity_id=None, entries=None, now=None, enabled=None)
  plan_rollback(identity, version=None, now=None, enabled=None) -> dict
  apply_rollback(store, identity_id=None, version=None, now=None, enabled=None)

Disabled by default (NARRATIVE_ENABLED=False): callers gate on 'enabled' or
pass enabled=True. No IO, no LLM, no host imports; apply_* only mutate the
given store and never call store.save().
"""
from __future__ import annotations

import time

from ..core.util import now_ts
from .writeback import is_identity

enabled = False
NARRATIVE_ENABLED = enabled
MIN_ENTRIES = 3
MIN_SPAN_DAYS = 7.0
MAX_VERSIONS = 20
MAX_NARRATIVE = 200
THEME_MAX = 24
SNIPPET_MAX = 40
SECONDS_PER_DAY = 86400.0
FIELD_TEXT = "identity_narrative"
FIELD_THEME = "identity_narrative_theme"
FIELD_VERSION = "identity_narrative_version"
FIELD_HISTORY = "identity_narrative_history"
FIELD_ENTRY_IDS = "identity_narrative_entry_ids"
FIELD_UPDATED_TS = "identity_narrative_updated_ts"


def _num(value, default=0.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return default if value != value else value


def _compact(value, limit=0):
    text = " ".join(str(value or "").split())
    return text[:limit] if limit else text


def _on(enabled):
    return NARRATIVE_ENABLED if enabled is None else bool(enabled)


def _row(entry):
    if isinstance(entry, dict):
        return entry
    if hasattr(entry, "to_dict"):
        try:
            row = entry.to_dict()
        except Exception:
            return None
        return row if isinstance(row, dict) else None
    return None


def _rows(entries):
    if isinstance(entries, dict):
        entries = entries.get("entries") or []
    rows, seen = [], set()
    try:
        items = list(entries or [])
    except TypeError:
        return []
    for entry in items:
        row = _row(entry)
        if row is not None and id(row) not in seen:
            seen.add(id(row))
            rows.append(row)
    return rows


def theme_of(entry):
    """Return the deterministic theme key of one entry ('' when unknown)."""
    row = _row(entry)
    if row is None:
        return ""
    candidates = [row]
    cue = row.get("cue_index")
    if isinstance(cue, dict):
        candidates.append(cue)
    if isinstance(row.get("metadata"), dict):
        candidates.append(row["metadata"])
    for source in candidates:
        for key in ("theme", "topic", "identity_theme", "event_name"):
            value = _compact(source.get(key), THEME_MAX)
            if value:
                return value
    for key in ("tags", "entities"):
        values = row.get(key)
        if isinstance(values, (list, tuple)) and values:
            first = values[0]
            if isinstance(first, dict):
                first = first.get("name") or first.get("text") or ""
            value = _compact(first, THEME_MAX)
            if value:
                return value
    return ""


def group_entries(entries):
    """Group entries by theme; each group is sorted by (ts, id)."""
    groups = {}
    for row in _rows(entries):
        theme = theme_of(row)
        if theme:
            groups.setdefault(theme, []).append(row)
    result = {}
    for theme in sorted(groups):
        rows = groups[theme]
        rows.sort(key=lambda e: (_num(e.get("ts"), 0.0), str(e.get("id") or "")))
        result[theme] = rows
    return result


def theme_span_days(entries):
    """Return max-ts minus min-ts in days (0.0 when fewer than two stamps)."""
    stamps = [_num(row.get("ts"), 0.0) for row in _rows(entries)]
    stamps = [stamp for stamp in stamps if stamp > 0.0]
    if len(stamps) < 2:
        return 0.0
    return round((max(stamps) - min(stamps)) / SECONDS_PER_DAY, 4)


def _day(ts):
    if ts <= 0.0:
        return ""
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(ts))
    except (OverflowError, OSError, ValueError):
        return ""


def narrative_text(theme, entries):
    """Build a bounded deterministic narrative sentence for one theme."""
    rows = sorted(_rows(entries),
                  key=lambda e: (_num(e.get("ts"), 0.0), str(e.get("id") or "")))
    if not rows:
        return ""
    snippets = []
    for row in (rows[0], rows[-1]):
        text = _compact(row.get("text"), SNIPPET_MAX)
        if text and text not in snippets:
            snippets.append(text)
    span = int(round(theme_span_days(rows)))
    first = _day(_num(rows[0].get("ts"), 0.0))
    last = _day(_num(rows[-1].get("ts"), 0.0))
    tail = "%d 条，跨度 %d 天" % (len(rows), span)
    if first and last:
        tail += "（%s → %s）" % (first, last)
    body = " → ".join(snippets) if snippets else "多次出现"
    return ("关于「%s」：%s；%s" % (theme, body, tail))[:MAX_NARRATIVE]


def narrative_candidate(entries):
    """Return the strongest theme meeting (>=3 entries, >=7 days) or None."""
    candidates = []
    groups = group_entries(entries)
    for theme in sorted(groups):
        rows = groups[theme]
        span = theme_span_days(rows)
        if len(rows) < MIN_ENTRIES or span < MIN_SPAN_DAYS:
            continue
        candidates.append({
            "theme": theme, "count": len(rows), "span_days": span,
            "entry_ids": [str(row.get("id") or "") for row in rows
                          if str(row.get("id") or "")],
            "first_ts": _num(rows[0].get("ts"), 0.0),
            "last_ts": _num(rows[-1].get("ts"), 0.0),
            "text": narrative_text(theme, rows)})
    if not candidates:
        return None
    candidates.sort(key=lambda c: (-c["count"], -c["span_days"], c["theme"]))
    return candidates[0]


def _history(row):
    raw = row.get(FIELD_HISTORY) if isinstance(row, dict) else None
    items = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        items.append({
            "version": int(max(0.0, _num(item.get("version"), 0.0))),
            "text": _compact(item.get("text"), MAX_NARRATIVE),
            "theme": _compact(item.get("theme"), THEME_MAX),
            "ts": _num(item.get("ts"), 0.0),
            "entry_ids": [str(x) for x in (item.get("entry_ids") or [])
                          if str(x)]})
    return items[-MAX_VERSIONS:]


def section(identity):
    """Return the normalized narrative section of an identity record/dict."""
    row = _row(identity) or {}
    return {"text": _compact(row.get(FIELD_TEXT) or row.get("narrative"),
                             MAX_NARRATIVE),
            "theme": _compact(row.get(FIELD_THEME), THEME_MAX),
            "version": int(max(0.0, _num(row.get(FIELD_VERSION), 0.0))),
            "history": _history(row),
            "entry_ids": [str(x) for x in (row.get(FIELD_ENTRY_IDS) or [])
                          if str(x)],
            "ts": _num(row.get(FIELD_UPDATED_TS), 0.0)}


def _next_version(current):
    versions = [current["version"]] + [item["version"]
                                       for item in current["history"]]
    return max(versions) + 1


def _supersede(current, now):
    history = list(current["history"])
    if current["text"]:
        history.append({"version": current["version"], "text": current["text"],
                        "theme": current["theme"], "ts": current["ts"],
                        "entry_ids": current["entry_ids"]})
    return history[-MAX_VERSIONS:]


def plan_update(identity, entries, now=None, enabled=None):
    """Return a pure update plan: {updated, allowed, reason, version, patch}."""
    result = {"updated": False, "allowed": False, "reason": "", "version": 0,
              "candidate": None, "patch": {}}
    if not _on(enabled):
        result["reason"] = "disabled"
        return result
    candidate = narrative_candidate(entries)
    if candidate is None:
        result["reason"] = "threshold_not_met"
        return result
    current = section(identity)
    if (current["theme"] == candidate["theme"]
            and current["text"] == candidate["text"]):
        result["reason"] = "unchanged"
        return result
    version = _next_version(current)
    result.update({
        "updated": True, "allowed": True, "reason": "updated",
        "version": version, "candidate": candidate,
        "patch": {FIELD_TEXT: candidate["text"], FIELD_THEME: candidate["theme"],
                  FIELD_VERSION: version,
                  FIELD_HISTORY: _supersede(current, now),
                  FIELD_ENTRY_IDS: candidate["entry_ids"],
                  FIELD_UPDATED_TS: round(now_ts(now), 3)}})
    return result


def plan_rollback(identity, version=None, now=None, enabled=None):
    """Return a pure rollback plan to a history version (latest by default)."""
    result = {"updated": False, "allowed": False, "reason": "", "version": 0,
              "patch": {}}
    if not _on(enabled):
        result["reason"] = "disabled"
        return result
    current = section(identity)
    if not current["history"]:
        result["reason"] = "no_history"
        return result
    target = current["history"][-1]
    if version is not None:
        wanted = int(_num(version, 0.0))
        target = None
        for item in reversed(current["history"]):
            if item["version"] == wanted:
                target = item
                break
        if target is None:
            result["reason"] = "version_not_found"
            return result
    result.update({
        "updated": True, "allowed": True, "reason": "rolled_back",
        "version": target["version"],
        "patch": {FIELD_TEXT: target["text"], FIELD_THEME: target["theme"],
                  FIELD_VERSION: target["version"],
                  FIELD_HISTORY: _supersede(current, now),
                  FIELD_ENTRY_IDS: target["entry_ids"],
                  FIELD_UPDATED_TS: round(now_ts(now), 3)}})
    return result


def _apply_plan(store, identity_id, planner, **kwargs):
    rows = getattr(store, "entries", None)
    if not isinstance(rows, list):
        rows = store.get("entries") if isinstance(store, dict) else []
    target = None
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if identity_id is not None:
            if str(row.get("id") or "") == str(identity_id):
                target = row
                break
        elif is_identity(row):
            target = row
            break
    if target is None:
        return {"updated": False, "allowed": False, "id": "",
                "reason": "missing_identity", "version": 0, "patch": {}}
    plan = planner(target, **kwargs)
    result = {"updated": plan["updated"], "allowed": plan["allowed"],
              "id": str(target.get("id") or ""), "reason": plan["reason"],
              "version": plan["version"], "patch": plan["patch"]}
    if plan["allowed"]:
        fn = getattr(store, "update", None)
        applied = None
        try:
            applied = fn(result["id"], **plan["patch"]) if callable(fn) else None
        except Exception:
            applied = None
        if not callable(fn):
            target.update(plan["patch"])
            applied = target
        if not isinstance(applied, dict):
            result.update({"updated": False, "allowed": False,
                           "reason": "update_failed"})
    return result


def apply_update(store, identity_id=None, entries=None, now=None, enabled=None):
    """Plan + apply one narrative update on the first/target identity record."""
    return _apply_plan(store, identity_id, plan_update, entries=entries,
                       now=now, enabled=enabled)


def apply_rollback(store, identity_id=None, version=None, now=None, enabled=None):
    """Plan + apply one narrative rollback on the target identity record."""
    return _apply_plan(store, identity_id, plan_rollback, version=version,
                       now=now, enabled=enabled)


__all__ = ["enabled", "NARRATIVE_ENABLED", "theme_of", "group_entries",
           "theme_span_days", "narrative_text", "narrative_candidate",
           "section", "plan_update", "apply_update", "plan_rollback",
           "apply_rollback", "MIN_ENTRIES", "MIN_SPAN_DAYS", "MAX_VERSIONS",
           "MAX_NARRATIVE"]
