# -*- coding: utf-8 -*-
"""HUMAN-4 mind wandering: sample what the mind drifts to.

When no external task is active the internal stream drifts toward open loops
and ruminated topics. Sampling is deterministic for a given (seed, now) and
biased by each candidate's tension and the current rumination level.

Literature
  Mason 2007 (default-mode mind wandering), Christoff 2016 (spontaneous
  thought), Smallwood & Schooler 2015 (wandering and meta-awareness),
  Nolen-Hoeksema 1991 (rumination recurrence), Carver & Scheier 1998 (open
  goals keep pulling attention), Powers 1973 (control error pulls focus),
  Gross 1998 (strategies alter where attention lands), Anderson 2007 (base
  level activation), Cowan 2001 (focus capacity).

Constraints: pure functions, stdlib only, no IO, no main import, time injected;
the candidate list is never mutated.
"""
from __future__ import annotations

import hashlib

BASE_WEIGHT = 1.0
RUMINATION_GAIN = 1.5
DEFAULT_LIMIT = 1


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _unit(seed, now, salt=""):
    key = ("%s|%s|%s" % (seed, now, salt)).encode("utf-8")
    digest = hashlib.sha256(key).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def _clamped(value, lo, hi):
    try:
        return max(lo, min(hi, float(value)))
    except Exception:
        return lo


def weights(loops, rumination=0.0):
    """Per-candidate weight: base + gain*rumination*(0.5 + tension)."""
    rum = _clamped(rumination, 0.0, 1.0)
    out = []
    for item in loops or []:
        row = item if isinstance(item, dict) else {"topic": str(item)}
        tension = _clamped(row.get("tension", 0.0), 0.0, 1.0)
        weight = BASE_WEIGHT + RUMINATION_GAIN * rum * (0.5 + tension)
        out.append(round(weight, 4))
    return out


def choose(loops, rumination=0.0, seed=0, now=0.0):
    """Weighted deterministic sample; returns {topic, index, weight, total} or None."""
    rows = [row if isinstance(row, dict) else {"topic": str(row)} for row in (loops or [])]
    ws = weights(rows, rumination)
    total = sum(ws)
    if not rows or total <= 0.0:
        return None
    point = _unit(seed, now, "wander") * total
    cursor = 0.0
    picked_index = len(rows) - 1
    for index, weight in enumerate(ws):
        cursor += weight
        if point <= cursor:
            picked_index = index
            break
    row = rows[picked_index]
    return {"topic": str(row.get("topic") or ""), "index": picked_index,
            "weight": ws[picked_index], "total": round(total, 4),
            "tension": _clamped(row.get("tension", 0.0), 0.0, 1.0)}


def wander(loops, rumination=0.0, seed=0, now=0.0, limit=DEFAULT_LIMIT):
    """Draw up to limit distinct topics (first is the strongest pull)."""
    rows = [row if isinstance(row, dict) else {"topic": str(row)} for row in (loops or [])]
    out = []
    remaining = list(range(len(rows)))
    count = max(0, int(limit))
    for draw in range(min(count, len(rows))):
        ws = weights([rows[index] for index in remaining], rumination)
        total = sum(ws)
        if total <= 0.0:
            break
        point = _unit(seed, now, "wander:%d" % draw) * total
        cursor = 0.0
        pick_at = len(remaining) - 1
        for offset, weight in enumerate(ws):
            cursor += weight
            if point <= cursor:
                pick_at = offset
                break
        index = remaining.pop(pick_at)
        out.append({"topic": str(rows[index].get("topic") or ""), "index": index,
                    "weight": round(ws[pick_at], 4)})
    return out


def seeded(seed, now=0):
    """Convenience: which of three fixed candidates a seed drifts to."""
    loops = [{"topic": "work", "tension": 0.2},
             {"topic": "friend", "tension": 0.6},
             {"topic": "rest", "tension": 0.1}]
    return choose(loops, rumination=0.0, seed=seed, now=now)
