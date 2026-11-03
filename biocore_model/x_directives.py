# -*- coding: utf-8 -*-
"""Cross-layer directive bus: one shape for every module's hints.

Each layer (metacog, attributor, dissonance, value_order, narrative,
self_intent, attachment, possible_selves, compassion, relation_stage) produced
its own dict. The caller then needed six kinds of compatibility code.

This module owns the single canonical shape:

    {"length_scale": 0.5-1.5,   # 1.0 = normal
     "initiative": 0-1,         # how much she reaches out
     "tone": "...",             # one short tone instruction
     "allow_correction": bool,  # may she correct herself once
     "note": "...",             # short explanation for logs/panels
     "sources": [...]}          # which layers contributed

merge() combines many hints conservatively: length and initiative take the
minimum (the most restrained wins), tone is taken from the highest-priority
layer that has one, allow_correction is OR, notes are joined and deduped.

Adapters live here, not in the twelve modules: their behaviour is unchanged.

Pure functions only: no IO, no host imports, no LLM calls.
"""
from __future__ import annotations

LENGTH_MIN = 0.50
LENGTH_MAX = 1.50
DEFAULT_LENGTH = 1.0
DEFAULT_INITIATIVE = 0.5
NOTE_LIMIT = 120

# Listed most-authoritative first: the first layer with a tone wins.
SOURCE_PRIORITY = (
    "dissonance", "metacog", "attributor", "narrative", "compassion",
    "attachment", "relation_stage", "self_intent", "value_order",
    "possible_selves",
)
PRIORITY_INDEX = {name: index for index, name in enumerate(SOURCE_PRIORITY)}

def _num(value, default=0.0):
    try:
        num = float(value)
    except Exception:
        return default
    if num != num:
        return default
    return num

def _clamp(value, low, high):
    return max(low, min(high, _num(value, low)))

def _clean(text, limit=NOTE_LIMIT):
    raw = " ".join(str(text or "").split())
    return raw[:limit]

def normalize(raw, source=""):
    """Map any layer's directive dict onto the canonical shape."""
    data = raw if isinstance(raw, dict) else {}
    length = data.get("length_scale", data.get("length", DEFAULT_LENGTH))
    initiative = data.get("initiative", data.get("proactive",
                                                  DEFAULT_INITIATIVE))
    tone = _clean(data.get("tone") or "", 60)
    correction = bool(data.get("allow_correction")
                      or data.get("allow_self_correction")
                      or data.get("allow_clarify"))
    note = _clean(data.get("note") or data.get("reason") or "")
    return {
        "length_scale": round(_clamp(length, LENGTH_MIN, LENGTH_MAX), 3),
        "initiative": round(_clamp(initiative, 0.0, 1.0), 3),
        "tone": tone,
        "allow_correction": correction,
        "note": note,
        "sources": [str(source)] if source else [],
    }

def _rank(item):
    """Lower is more authoritative; unknown sources rank last."""
    names = item.get("sources") or []
    if not names:
        return len(SOURCE_PRIORITY)
    return min(PRIORITY_INDEX.get(name, len(SOURCE_PRIORITY)) for name in names)

def merge(items, source=""):
    """Combine many directives into one, taking the most restrained values."""
    rows = []
    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        if item.get("_x_normalized"):
            row = dict(item)
        else:
            label = source or (item.get("_source") if isinstance(item, dict) else "")
            row = normalize(item, label or "item%d" % index)
            row["_x_normalized"] = True
        rows.append(row)
    if not rows:
        return {"length_scale": DEFAULT_LENGTH, "initiative": DEFAULT_INITIATIVE,
                "tone": "", "allow_correction": False, "note": "", "sources": []}

    length = min(row["length_scale"] for row in rows)
    initiative = min(row["initiative"] for row in rows)
    tone = ""
    best = len(SOURCE_PRIORITY) + 1
    for row in rows:
        if not row.get("tone"):
            continue
        rank = _rank(row)
        if rank < best:
            best = rank
            tone = row["tone"]
    notes = []
    seen = set()
    for row in rows:
        text = row.get("note") or ""
        if text and text not in seen:
            seen.add(text)
            notes.append(text)
    sources = []
    for row in rows:
        for name in row.get("sources") or []:
            if name and name not in sources:
                sources.append(name)
    return {
        "length_scale": round(length, 3),
        "initiative": round(initiative, 3),
        "tone": tone,
        "allow_correction": any(row["allow_correction"] for row in rows),
        "note": _clean("；".join(notes)),
        "sources": sources,
    }

def merge_named(pairs):
    """Convenience: [(name, directive), ...] -> merged directive."""
    rows = []
    for name, raw in pairs or []:
        if not isinstance(raw, dict):
            continue
        row = normalize(raw, str(name))
        row["_x_normalized"] = True
        rows.append(row)
    return merge(rows)
