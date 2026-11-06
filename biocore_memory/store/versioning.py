# -*- coding: utf-8 -*-
"""Version resolution for explicitly attributed facts (write path + filter).

arXiv 2610.36308 (2026), "When Retrieval Is Not Enough": the evidence is
already inside the recall set and still loses to an older version, so what is
missing is resolution, not recall.

Write path
    A new value for a stored (subject, attribute) key marks the older entry
    status='superseded' and records superseded_by / superseded_at. The text is
    never edited and nothing is deleted.
    Two different values for one key written in the SAME turn cannot be
    ordered, so both stay visible and are marked status='disputed'; the pair is
    reported as a conflict (/state.memory_conflicts).
    A write whose ts is OLDER than the stored value (import, replay) is itself
    superseded by the stored one.

Read path
    status='superseded' is hidden unless include_superseded=True, which is the
    "她以前说过…吗" question. Disputed entries stay visible.

Switch
    memory_versioning (default ON). With it OFF nothing is read, nothing is
    marked and nothing is filtered: the old behaviour, byte for byte.

Keys are NEVER guessed from the text. There are exactly two explicit paths:
    1. metadata = {"subject": "user", "attribute": "city", "fact_value": "杭州"}
    2. the entry itself carries "attribute" plus "fact_value"/"attribute_value"
An entry with neither is stored exactly as before: no key, no status, no
filtering. The caller decides what an attribute is.

No host imports, no prompt text, no LLM call.
"""
from __future__ import annotations

import os
import re

SWITCH_KEY = "memory_versioning"
ENV_KEY = "BIOCORE_MEMORY_VERSIONING"

ACTIVE = "active"
SUPERSEDED = "superseded"
DISPUTED = "disputed"
STATUSES = (ACTIVE, SUPERSEDED, DISPUTED)

RECENT_LIMIT = 5
CONFLICT_LIMIT = 5

_TRUE = ("1", "true", "on", "yes")
_FALSE = ("0", "false", "off", "no")

_DIGITS = str.maketrans("０１２３４５６７８９：／", "0123456789:/")
_WS = re.compile(r"\s+")


def enabled(flags=None, env=None):
    """memory_versioning: explicit flag > nested switches > env > default ON."""
    data = flags if isinstance(flags, dict) else {}
    if isinstance(data.get(SWITCH_KEY), bool):
        return data[SWITCH_KEY]
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    if isinstance(switches.get(SWITCH_KEY), bool):
        return switches[SWITCH_KEY]
    environ = env if hasattr(env, "get") else None
    if environ is not None and ENV_KEY in environ:
        raw = str(environ.get(ENV_KEY)).strip().lower()
        if raw in _TRUE:
            return True
        if raw in _FALSE:
            return False
    return True


# ------------------------------------------------------------ explicit keys
def normalize_value(value):
    """Whitespace and full-width digits only; the value itself is untouched."""
    return _WS.sub("", str(value or "").translate(_DIGITS))


def key_of(entry):
    """(subject, attribute, value) from explicit annotations; None otherwise.

    Nothing is inferred from the text: without an annotation there is no key,
    so the entry is never compared with, or marked against, any other one.
    """
    entry = entry if isinstance(entry, dict) else {}
    blocks = []
    meta = entry.get("metadata")
    if isinstance(meta, dict):
        blocks.append(meta)
    blocks.append(entry)
    subject = attribute = value = ""
    for block in blocks:
        if not subject:
            subject = str(block.get("subject") or "").strip()
        if not attribute:
            attribute = str(block.get("attribute") or "").strip()
        if not value:
            value = str(block.get("fact_value")
                        or block.get("attribute_value") or "").strip()
    if not attribute or not value:
        return None
    if not subject:
        subject = ("user" if str(entry.get("role") or "user") == "user"
                   else "assistant")
    return {"subject": subject[:24], "attribute": attribute[:24],
            "value": normalize_value(value)[:32]}


def status_of(entry):
    if not isinstance(entry, dict):
        return ACTIVE
    status = str(entry.get("status") or ACTIVE).strip().lower()
    return status if status in STATUSES else ACTIVE


def is_superseded(entry):
    return status_of(entry) == SUPERSEDED


def is_disputed(entry):
    return status_of(entry) == DISPUTED


def visible(entries, include_superseded=False):
    """Entries recall may return: superseded ones only on request."""
    rows = [entry for entry in (entries or []) if isinstance(entry, dict)]
    if include_superseded:
        return rows
    return [entry for entry in rows if not is_superseded(entry)]


# --------------------------------------------------------------- write path
def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return float(default)
    return number if number == number else float(default)


def _stamp(entry):
    return round(_num(entry.get("ts"), 0.0), 3)


def _turn_of(entry):
    meta = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    for key in ("turn_id", "turn", "round"):
        value = entry.get(key)
        if value is None:
            value = meta.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _same_turn(entry, other):
    mine, theirs = _turn_of(entry), _turn_of(other)
    if mine and theirs:
        return mine == theirs
    # no turn id: the write stamp is the turn (one turn writes one ts)
    return _stamp(entry) == _stamp(other)


def _mark_superseded(entry, by_id, at):
    entry["status"] = SUPERSEDED
    entry["superseded_by"] = str(by_id or "")
    entry["superseded_at"] = round(_num(at, 0.0), 3)
    return entry


def _mark_disputed(entry, other_id, at):
    entry["status"] = DISPUTED
    partners = [str(x) for x in (entry.get("disputed_with") or []) if str(x)]
    if other_id and str(other_id) not in partners:
        partners.append(str(other_id))
    entry["disputed_with"] = partners[:8]
    entry.setdefault("disputed_at", round(_num(at, 0.0), 3))
    return entry


def apply(entry, entries, now=None):
    """Resolve one NEW entry against the stored ones; returns a report dict."""
    report = {"key": None, "superseded": [], "disputed": [], "conflict": None}
    if not isinstance(entry, dict):
        return report
    key = key_of(entry)
    if not key:
        return report
    entry["version_key"] = key
    report["key"] = key
    if not entry.get("status"):
        entry["status"] = ACTIVE
    scope = str(entry.get("scope") or "default")
    stamp = _num(now, _stamp(entry))
    subject, attribute, value = key["subject"], key["attribute"], key["value"]
    for other in list(entries or []):
        if not isinstance(other, dict) or other is entry:
            continue
        if other.get("deleted") or other.get("archived"):
            continue
        if str(other.get("scope") or "default") != scope:
            continue
        other_key = other.get("version_key")
        if not isinstance(other_key, dict):
            other_key = key_of(other)
            if isinstance(other_key, dict):
                other["version_key"] = other_key
        if not isinstance(other_key, dict):
            continue
        if (str(other_key.get("subject")) != subject
                or str(other_key.get("attribute")) != attribute):
            continue
        if normalize_value(other_key.get("value")) == value:
            continue          # same value: nothing to resolve
        other_status = status_of(other)
        if other_status == SUPERSEDED:
            continue          # already history
        if _same_turn(entry, other):
            _mark_disputed(other, entry.get("id"), stamp)
            _mark_disputed(entry, other.get("id"), stamp)
            report["disputed"].append(str(other.get("id") or ""))
            report["conflict"] = {
                "subject": subject, "attribute": attribute,
                "values": [normalize_value(other_key.get("value")), value],
                "ids": [str(other.get("id") or ""), str(entry.get("id") or "")],
                "ts": round(stamp, 3), "reason": "same_turn"}
            continue
        if _stamp(other) <= _stamp(entry):
            _mark_superseded(other, entry.get("id"), stamp)
            report["superseded"].append(str(other.get("id") or ""))
        else:
            _mark_superseded(entry, other.get("id"), stamp)
            report["superseded"].append(str(entry.get("id") or ""))
    return report


# ---------------------------------------------------------------- read path
def summary(entries, recent_limit=RECENT_LIMIT):
    """/state.memory_versions: counts plus the last few status changes."""
    rows = [entry for entry in (entries or []) if isinstance(entry, dict)]
    active = superseded = disputed = 0
    changed = []
    for entry in rows:
        status = status_of(entry)
        if status == SUPERSEDED:
            superseded += 1
        elif status == DISPUTED:
            disputed += 1
        else:
            active += 1
            continue
        key = entry.get("version_key")
        key = key if isinstance(key, dict) else {}
        changed.append({
            "id": str(entry.get("id") or ""),
            "status": status,
            "attribute": str(key.get("attribute") or "")[:24],
            "value": str(key.get("value") or "")[:32],
            "ts": round(_num(entry.get("ts"), 0.0), 3),
            "superseded_by": str(entry.get("superseded_by") or ""),
        })
    changed.sort(key=lambda row: (-row["ts"], row["id"]))
    return {"active": active, "superseded": superseded, "disputed": disputed,
            "recent": changed[:max(0, int(recent_limit or 0))]}


def conflicts(entries, limit=CONFLICT_LIMIT):
    """/state.memory_conflicts: keys whose same-turn values disagree."""
    groups = {}
    for entry in (entries or []):
        if not isinstance(entry, dict) or not is_disputed(entry):
            continue
        key = entry.get("version_key")
        key = key if isinstance(key, dict) else key_of(entry)
        if not isinstance(key, dict):
            continue
        name = (str(key.get("subject") or ""), str(key.get("attribute") or ""))
        row = groups.setdefault(name, {"subject": name[0], "attribute": name[1],
                                       "values": [], "ids": [], "ts": 0.0})
        value = str(key.get("value") or "")[:32]
        if value and value not in row["values"]:
            row["values"].append(value)
        entry_id = str(entry.get("id") or "")
        if entry_id and entry_id not in row["ids"]:
            row["ids"].append(entry_id)
        row["ts"] = max(row["ts"], round(_num(entry.get("ts"), 0.0), 3))
    rows = [row for row in groups.values() if len(row["values"]) > 1]
    rows.sort(key=lambda row: (-row["ts"], row["attribute"]))
    return rows[:max(0, int(limit or 0))]
