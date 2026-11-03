# -*- coding: utf-8 -*-
"""Cognitive dissonance: the discomfort of acting against what she said.

Given the stances she has stated and what she just did, this module
returns how much tension that creates (0-1) and which relief she leans
towards:

- 改口      the stance was weak or outdated, so she takes it back
- 合理化    she keeps both and explains the exception
- 沉默      too much friction, she says less
- 承认      she owns the gap out loud

Pure functions only: no IO, no host imports, no LLM calls.
"""
from __future__ import annotations

RELIEFS = ("改口", "合理化", "沉默", "承认")
HIGH = 0.60
LOW = 0.25

def _num(value, default=0.0):
    try:
        num = float(value)
    except Exception:
        return default
    if num != num:
        return default
    return num

def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _num(value, low)))

def _stances(stances):
    """Normalizer: accept a list of dicts/strings or a single dict."""
    if isinstance(stances, dict):
        rows = [stances]
    elif isinstance(stances, (list, tuple)):
        rows = list(stances)
    else:
        rows = []
    out = []
    for row in rows:
        if isinstance(row, str):
            row = {"text": row}
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or row.get("stance") or "").strip()
        if not text:
            continue
        out.append({
            "text": text[:80],
            "weight": _clamp(row.get("weight", 0.6)),
            "age_days": max(0.0, _num(row.get("age_days"), 0.0)),
        })
    return out

def _behavior(behavior):
    if isinstance(behavior, str):
        behavior = {"kind": behavior}
    if not isinstance(behavior, dict):
        behavior = {}
    contradicts = behavior.get("contradicts")
    if isinstance(contradicts, str):
        contradicts = [contradicts]
    return {
        "kind": str(behavior.get("kind") or ""),
        "contradicts": [str(x) for x in (contradicts or [])],
        "salience": _clamp(behavior.get("salience", 0.5)),
        "justification": _clamp(behavior.get("justification", 0.0)),
    }

def strength(stances=None, behavior=None, flags=None):
    """How much this behaviour contradicts her stated stances (0-1)."""
    flags = flags if isinstance(flags, dict) else {}
    enabled = bool(flags.get("enabled", True))
    rows = _stances(stances)
    act = _behavior(behavior)
    if not rows or not act["kind"]:
        return {"enabled": enabled, "dissonance": 0.0, "relief": "沉默",
                "matched": [], "reason": "没有冲突"}

    hits = [row for row in rows
            if row["text"] in act["contradicts"]
            or any(tag and tag in row["text"] for tag in act["contradicts"])]
    if act["contradicts"] and not hits:
        # No stance text matched, but the caller says it contradicts one:
        # treat the oldest (most established) stance as the reference.
        hits = [max(rows, key=lambda row: row["age_days"])]

    if not hits:
        return {"enabled": enabled, "dissonance": 0.0, "relief": "沉默",
                "matched": [], "reason": "没有冲突"}

    weight = max(row["weight"] for row in hits)
    staleness = max(row["age_days"] for row in hits)
    # Old stances are easier to let go; fresh ones bind harder.
    freshness = 1.0 / (1.0 + staleness / 30.0)
    raw = weight * freshness * act["salience"] * (1.0 - act["justification"])
    value = round(_clamp(raw), 3)
    relief = choose_relief(value, weight=weight, freshness=freshness,
                           justification=act["justification"])
    reason = ("跟%s冲突" % hits[0]["text"]) if hits else "跟既有立场冲突"
    return {
        "enabled": enabled,
        "dissonance": value if enabled else 0.0,
        "relief": relief if enabled else "沉默",
        "matched": [row["text"] for row in hits],
        "reason": reason,
    }

def choose_relief(value, weight=0.6, freshness=1.0, justification=0.0):
    """Pick one relief that fits the size and shape of the tension."""
    value = _clamp(value)
    if value < LOW:
        return "沉默"
    if value >= HIGH:
        return "承认" if freshness >= 0.5 else "改口"
    if justification >= 0.4:
        return "合理化"
    return "合理化" if freshness >= 0.5 else "改口"

def directives(result):
    """Bounded hint for the expression layer (no prompt text)."""
    if not isinstance(result, dict) or not result.get("enabled", True):
        return {"tone": "", "length_scale": 1.0, "relief": "沉默"}
    relief = result.get("relief") or "沉默"
    table = {
        "承认": ("可以先认一句", 0.9),
        "合理化": ("补一句解释，别绕太久", 1.0),
        "改口": ("把话说回去，重新讲一句", 0.9),
        "沉默": ("少说两句", 0.7),
    }
    tone, scale = table.get(relief, ("", 1.0))
    return {"tone": tone, "length_scale": scale, "relief": relief}
