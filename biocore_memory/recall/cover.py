# -*- coding: utf-8 -*-
"""Coverage select: pick k from the pool by spatial spread, not by rank.

The pool (and the rerank scores) is decided elsewhere; this module only decides
WHICH k of them go into the block. It is MMR (Carbonell & Goldstein 1998) with
the redundancy term replaced by the five-axis space distance:

    pick the best rel first;
    then score(i) = rel(i) + lambda * min_j dist_space(i, j),  j in picked.

    distance = 1 - similarity, so rewarding distance is penalising similarity:
    the larger lambda, the more spread out the chosen set becomes.

lambda = 0 degenerates to plain rank order; a larger lambda buys spread. Items
without coordinates contribute distance 0, so they never block a selection.
"""
from __future__ import annotations

from ..core.config import SPATIAL_COVER_LAMBDA, SPATIAL_COVER_POOL

SWITCH_KEY = "spatial_cover_select"
SWITCH_ENV = "BIOCORE_SPATIAL_COVER_SELECT"
LAMBDA_KEY = "spatial_cover_lambda"
POOL_KEY = "spatial_cover_pool"


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _id(entry):
    return str((entry or {}).get("id") or "")


def enabled(flags=None, env=None):
    """spatial_cover_select: flag > switches > env > default OFF."""
    data = flags if isinstance(flags, dict) else {}
    value = data.get(SWITCH_KEY)
    if value is None and isinstance(data.get("switches"), dict):
        value = data["switches"].get(SWITCH_KEY)
    if isinstance(value, bool):
        return value
    environ = env if hasattr(env, "get") else None
    if environ is not None and SWITCH_ENV in environ:
        raw = str(environ.get(SWITCH_ENV)).strip().lower()
        return raw in ("1", "true", "on", "yes")
    return False


def lam(flags=None):
    data = flags if isinstance(flags, dict) else {}
    value = data.get(LAMBDA_KEY)
    if value is None and isinstance(data.get("switches"), dict):
        value = data["switches"].get(LAMBDA_KEY)
    try:
        number = float(value)
    except Exception:
        number = float(SPATIAL_COVER_LAMBDA)
    return max(0.0, min(10.0, number))


def pool_depth(flags=None):
    data = flags if isinstance(flags, dict) else {}
    value = data.get(POOL_KEY)
    if value is None and isinstance(data.get("switches"), dict):
        value = data["switches"].get(POOL_KEY)
    try:
        number = int(value)
    except Exception:
        number = int(SPATIAL_COVER_POOL)
    return max(1, min(200, number))


def select(pool, rel, k, lam_value=SPATIAL_COVER_LAMBDA, dist_of=None):
    """MMR over the space distance; returns (picked entries, stats)."""
    pool = [entry for entry in (pool or []) if isinstance(entry, dict)]
    count = len(pool)
    ratio = _num(lam_value)
    stats = {"pool": count, "kept": 0, "lambda": round(ratio, 3),
             "avg_pairwise_dist": 0.0, "dropped_by_cover": 0}
    if count == 0 or int(k) <= 0:
        stats["dropped_by_cover"] = count
        return [], stats
    values = []
    for index, entry in enumerate(pool):
        value = rel[index] if isinstance(rel, (list, tuple)) and index < len(rel) else 0.0
        values.append(max(0.0, _num(value)))
    ceiling = max(values + [0.0]) or 1.0
    values = [value / ceiling for value in values]
    wanted = min(int(k), count)
    picked = []
    remaining = list(range(count))
    first = max(remaining, key=lambda index: (values[index], -index))
    picked.append(first)
    remaining.remove(first)
    distance = dist_of or (lambda left, right: 0.0)
    while len(picked) < wanted and remaining:
        best, best_value = None, None
        for index in remaining:
            nearest = min(distance(pool[index], pool[other]) for other in picked)
            value = values[index] + ratio * _num(nearest)
            key = (value, values[index], -index)
            if best is None or key > best_value:
                best, best_value = index, key
        picked.append(best)
        remaining.remove(best)
    pairs = []
    for left in range(len(picked)):
        for right in range(left + 1, len(picked)):
            pairs.append(_num(distance(pool[picked[left]], pool[picked[right]])))
    stats["kept"] = len(picked)
    stats["avg_pairwise_dist"] = (round(sum(pairs) / len(pairs), 6)
                                  if pairs else 0.0)
    stats["dropped_by_cover"] = count - len(picked)
    return [pool[index] for index in picked], stats


def order(entries):
    """Inject order: segment (by its first timestamp), then time inside."""
    rows = [entry for entry in (entries or []) if isinstance(entry, dict)]
    starts = {}
    for entry in rows:
        key = str(entry.get("event_id") or ("solo:" + _id(entry)))
        stamp = _num(entry.get("ts"), 0.0)
        if key not in starts or stamp < starts[key]:
            starts[key] = stamp
    return sorted(rows, key=lambda entry: (
        starts.get(str(entry.get("event_id") or ("solo:" + _id(entry))), 0.0),
        _num(entry.get("ts"), 0.0),
        _num(entry.get("event_index"), 0.0),
        _id(entry)))
