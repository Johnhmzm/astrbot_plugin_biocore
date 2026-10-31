# -*- coding: utf-8 -*-
"""HUMAN-1 multi-dimensional scheduler: time x entity x channel, lazy decay.

A tiny deterministic scheduler for internal impulses (open loops, memories,
proactive candidates). Each candidate carries a due time, an entity (who it is
about), a channel (where it should surface) and a base weight. Ranking is a
weighted sum of three normalized dimension scores multiplied by a lazily
decayed weight, so nothing needs a background sweep.

Literature
  Carver & Scheier 1998 (cybernetic control: priorities compete for action),
  Powers 1973 (perceptual control), Sterling 2012 (allostasis budget),
  Gross 1998 (strategy selection as scheduling), Anderson 2007 (ACT-R base
  level activation / decay), Cowan 2001 (working-memory focus limits).

Constraints: pure functions, stdlib only, no IO, no main import, time injected
through now=, caller items are never mutated.
"""
from __future__ import annotations

import math

DIMENSIONS = ("time", "entity", "channel")
WEIGHTS = {"time": 0.50, "entity": 0.30, "channel": 0.20}
DEFAULT_LIMIT = 5
ENTITY_MISS = 0.20
CHANNEL_MISS = 0.30
TAU_HOURS = 6.0
HALF_LIFE_HOURS = 12.0


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _clamp(value, lo=0.0, hi=1.0):
    try:
        return max(lo, min(hi, float(value)))
    except Exception:
        return lo


def time_score(item, now, tau_hours=TAU_HOURS):
    """1.0 at the due moment, decaying smoothly with distance in hours."""
    due = _num((item or {}).get("due_ts"), 0.0)
    tau = max(0.1, _num(tau_hours, TAU_HOURS))
    distance_h = abs(_num(now) - due) / 3600.0
    return round(_clamp(math.exp(-distance_h / tau)), 4)


def entity_score(item, entity=None):
    if entity is None:
        return 1.0
    return 1.0 if str((item or {}).get("entity") or "") == str(entity) else ENTITY_MISS


def channel_score(item, channel=None):
    if channel is None:
        return 1.0
    return 1.0 if str((item or {}).get("channel") or "") == str(channel) else CHANNEL_MISS


def lazy_decay(item, now, half_life_hours=HALF_LIFE_HOURS):
    """Return a copy with the weight decayed since last_ts (power half-life)."""
    row = dict(item or {})
    half = max(0.1, _num(half_life_hours, HALF_LIFE_HOURS))
    last = _num(row.get("last_ts"), 0.0)
    base = _clamp(row.get("weight", 1.0), 0.0, 10.0)
    if row.get("last_ts") is not None and _num(now) > last:
        hours = (_num(now) - last) / 3600.0
        base = base * (0.5 ** (hours / half))
    row["weight"] = round(_clamp(base, 0.0, 10.0), 4)
    row["last_ts"] = _num(now)
    return row


def score(item, now, entity=None, channel=None, weights=None):
    """Weighted three-dimension score for one candidate (0..1-ish)."""
    w = dict(WEIGHTS)
    if isinstance(weights, dict):
        for key in DIMENSIONS:
            if key in weights:
                w[key] = max(0.0, _num(weights[key], w[key]))
    total_w = sum(w.values()) or 1.0
    value = (w["time"] * time_score(item, now)
             + w["entity"] * entity_score(item, entity)
             + w["channel"] * channel_score(item, channel)) / total_w
    base = _num((item or {}).get("weight", 1.0), 1.0)
    return round(_clamp(value * max(0.0, base)), 4)


def rank(items, now, entity=None, channel=None, limit=DEFAULT_LIMIT, weights=None):
    """Sorted candidates: [{"score", "id", "item"}] highest first."""
    rows = []
    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or index)
        rows.append({"id": item_id, "score": score(item, now, entity, channel, weights),
                     "item": item})
    rows.sort(key=lambda row: (-row["score"], row["id"]))
    return rows[:max(0, int(limit if limit is not None else DEFAULT_LIMIT))]


def pick(items, now, entity=None, channel=None, weights=None):
    """Top candidate or None."""
    rows = rank(items, now, entity=entity, channel=channel, limit=1, weights=weights)
    return rows[0] if rows else None


def due(items, now, window_seconds=3600.0, entity=None, channel=None, limit=DEFAULT_LIMIT):
    """Only candidates whose due_ts is within the window (inclusive)."""
    rows = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        due_ts = _num(item.get("due_ts"), 0.0)
        if abs(_num(now) - due_ts) <= max(0.0, _num(window_seconds)):
            rows.append(item)
    return rank(rows, now, entity=entity, channel=channel, limit=limit)
