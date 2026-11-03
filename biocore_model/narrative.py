# -*- coding: utf-8 -*-
"""Narrative: turning key events into an autobiography, with three checks.

Input is a stream of key events. Output is:

- entries: a few chapter-like lines (theme + what happened), newest first
- consistency: share of events whose sign agrees with their theme's tone
- contradiction: share of same-theme pairs that pull opposite ways
- repair: share of negative events followed by a positive one in time

The three numbers are what the panel shows: is her story coherent, where does
it contradict itself, and has she been able to come back from the bad parts.

Pure functions only: no IO, no host imports, no LLM calls.
"""
from __future__ import annotations

THEME_BY_KIND = {
    "rupture": "关系裂缝", "repair": "修复", "gift": "被善待",
    "loss": "失去", "becoming": "成长", "promise": "约定",
}
DEFAULT_THEME = "日常"
MAX_ENTRIES = 6
REPAIR_WINDOW_S = 7 * 24 * 3600.0


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


def _events(events):
    out = []
    for index, raw in enumerate(events or []):
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or raw.get("summary") or "").strip()
        if not text:
            continue
        kind = str(raw.get("kind") or "")
        out.append({
            "id": str(raw.get("id") or "e%d" % index),
            "ts": _num(raw.get("ts"), 0.0),
            "text": text[:80],
            "kind": kind,
            "theme": THEME_BY_KIND.get(kind, DEFAULT_THEME),
            "valence": max(-1.0, min(1.0, _num(raw.get("valence"), 0.0))),
            "importance": _clamp(raw.get("importance", 0.5)),
        })
    out.sort(key=lambda row: row["ts"])
    return out


def entries(events, limit=MAX_ENTRIES):
    """Compress the stream into chapter lines (newest first, deduped)."""
    rows = _events(events)
    limit = max(1, int(_num(limit, MAX_ENTRIES)))
    picked = []
    seen = set()
    ranked = sorted(rows, key=lambda r: (r["importance"], r["ts"]), reverse=True)
    for row in ranked:
        key = (row["theme"], row["text"][:24])
        if key in seen:
            continue
        seen.add(key)
        picked.append({"theme": row["theme"], "text": row["text"],
                       "ts": row["ts"], "valence": row["valence"]})
        if len(picked) >= limit:
            break
    picked.sort(key=lambda row: row["ts"], reverse=True)
    return picked


def _themes(rows):
    out = {}
    for row in rows:
        out.setdefault(row["theme"], []).append(row)
    return out


def consistency(events):
    """Weighted share of events agreeing with their theme tone (0-1)."""
    rows = _events(events)
    if not rows:
        return 0.0
    total = 0.0
    agree = 0.0
    for theme, group in _themes(rows).items():
        signed = sum(row["valence"] * row["importance"] for row in group)
        tone = 1.0 if signed >= 0 else -1.0
        for row in group:
            weight = row["importance"]
            total += weight
            if row["valence"] == 0 or (row["valence"] > 0) == (tone > 0):
                agree += weight
    if total <= 0:
        return 0.0
    return round(_clamp(agree / total), 3)


def contradiction(events):
    """Share of same-theme pairs pulling opposite ways (0-1)."""
    rows = _events(events)
    pairs = 0
    opposite = 0
    for theme, group in _themes(rows).items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if a["valence"] == 0 or b["valence"] == 0:
                    continue
                pairs += 1
                if (a["valence"] > 0) != (b["valence"] > 0):
                    opposite += 1
    if pairs <= 0:
        return 0.0
    return round(_clamp(opposite / pairs), 3)


def repair(events, window_s=REPAIR_WINDOW_S):
    """Share of negative events followed by a positive one in time."""
    rows = _events(events)
    window = max(0.0, _num(window_s, REPAIR_WINDOW_S))
    negatives = [row for row in rows if row["valence"] < 0]
    if not negatives:
        return 0.0
    healed = 0
    for row in negatives:
        later = [other for other in rows
                 if other["valence"] > 0
                 and (other["theme"] == row["theme"]
                      or other["kind"] == "repair")
                 and 0 <= other["ts"] - row["ts"] <= window]
        if later:
            healed += 1
    return round(_clamp(healed / len(negatives)), 3)


def summarize(events, flags=None):
    """Everything the panel needs for one narrative refresh."""
    flags = flags if isinstance(flags, dict) else {}
    enabled = bool(flags.get("enabled", True))
    rows = _events(events)
    return {
        "enabled": enabled,
        "entries": entries(rows) if enabled else [],
        "metrics": {
            "consistency": consistency(rows) if enabled else 0.0,
            "contradiction": contradiction(rows) if enabled else 0.0,
            "repair": repair(rows) if enabled else 0.0,
        },
        "events": len(rows),
    }


def directives(result, contradiction_high=0.4):
    """Bounded hint: a contradictory story invites one clarification."""
    if not isinstance(result, dict) or not result.get("enabled", True):
        return {"tone": "", "allow_clarify": False}
    metrics = result.get("metrics") or {}
    messy = _clamp(metrics.get("contradiction", 0.0)) >= contradiction_high
    return {"tone": ("可以补一句把话说圆" if messy else ""),
            "allow_clarify": bool(messy)}
