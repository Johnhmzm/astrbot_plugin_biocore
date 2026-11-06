# -*- coding: utf-8 -*-
"""Recall by event segment, not by entry (Zacks 2007; Hearst 1997 TextTiling).

A memory is written turn by turn, but what the user said was one *event*: the
plan, the place, the change. Retrieving single entries chops that event into
fragments and injects whichever fragment happened to score best. Here the unit
is the segment:

    segment    = one event_id (or one solo entry when there is no event_id)
    members    = sorted by ts / event_index
    score      = the best member score (the existing scoring channel)
    anchor     = the most recent member (the tie breaker)

Budget is counted in LINES: a segment is either kept whole or dropped whole;
the block never shows half an event.
"""
from __future__ import annotations


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _id(entry):
    return str((entry or {}).get("id") or "")


def _sort_key(entry):
    return (_num(entry.get("ts"), 0.0), int(_num(entry.get("event_index"), 0)),
            _id(entry))


def group(entries):
    """One segment per event_id; entries without one are solo segments."""
    buckets = {}
    order = []
    for entry in entries or []:
        if not isinstance(entry, dict) or entry.get("deleted"):
            continue
        event_id = str(entry.get("event_id") or "").strip()
        key = event_id or ("solo:" + _id(entry))
        if key not in buckets:
            buckets[key] = {"key": key, "event_id": event_id, "members": []}
            order.append(key)
        buckets[key]["members"].append(entry)
    segments = []
    for key in order:
        segment = buckets[key]
        segment["members"].sort(key=_sort_key)
        segments.append(segment)
    return segments


def anchor(segment):
    """The segment time anchor: its most recent member."""
    members = (segment or {}).get("members") or []
    if not members:
        return 0.0
    return max(_num(member.get("ts"), 0.0) for member in members)


def score(segment, score_of):
    """The segment score is its best member, not the sum or the mean."""
    best = 0.0
    for member in (segment or {}).get("members") or []:
        try:
            value = float(score_of(member) or 0.0)
        except Exception:
            value = 0.0
        if value > best:
            best = value
    return best


def rank(segments, score_of):
    """Ordered best-first: score desc, then the newest anchor, then key."""
    rows = []
    for segment in segments or []:
        rows.append({"segment": segment,
                     "score": round(score(segment, score_of), 9),
                     "anchor": round(anchor(segment), 6)})
    rows.sort(key=lambda row: (-row["score"], -row["anchor"],
                               row["segment"]["key"]))
    return rows


def fit(ranked, limit_lines, cost_of):
    """Keep whole segments while the line budget allows; drop the rest whole."""
    kept, dropped = [], 0
    lines = 0
    for row in ranked or []:
        members = row["segment"]["members"]
        if not members:
            continue
        if lines + len(members) > max(1, int(limit_lines)):
            dropped += 1
            continue
        kept.append(row)
        lines += len(members)
    return kept, dropped


def stats(kept, lines, dropped):
    lengths = [len(row["segment"]["members"]) for row in kept or []]
    return {"segments": len(lengths),
            "lines": int(lines),
            "dropped_segments": int(dropped),
            "avg_len": round(sum(lengths) / float(len(lengths)), 2) if lengths else 0.0}
