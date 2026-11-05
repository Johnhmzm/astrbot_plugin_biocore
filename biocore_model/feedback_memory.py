# -*- coding: utf-8 -*-
"""FB-3: event reconsolidation / memory decay wiring. Pure; no storage IO."""
from __future__ import annotations

import random

try:
    from . import memory_forgetting as _mf
except Exception:  # pragma: no cover
    from biocore_model import memory_forgetting as _mf

THRESHOLD = 0.15
BOOST = 0.25
CORE_AFTER = 5
D = 0.5
TAU_HOURS = 24.0
COOLDOWN_SECONDS = 3600.0   # [engineering] one boost per memory per hour


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def touch(entries, event_id, now, kind="recall"):
    items = [dict(entry or {}) for entry in (entries or [])]
    audit = []
    deltas = {}
    for entry in items:
        if str(entry.get("id")) != str(event_id):
            continue
        if float(entry.get("last_touch_ts", 0.0) or 0.0) >= float(now):
            return {"entries": items, "deltas": {}, "audit": [], "idempotent": True}
        old = _num(entry.get("strength"), 1.0)
        entry["strength"] = round(min(1.0, old + BOOST), 4)
        entry["recall_count"] = int(entry.get("recall_count", 0) or 0) + 1
        entry["last_touched"] = float(now)
        entry["last_decay_ts"] = float(now)
        entry["last_touch_ts"] = float(now)
        entry["last_touch_kind"] = str(kind)
        if entry["recall_count"] > CORE_AFTER:
            entry["core_memory"] = True
        deltas[str(event_id)] = {"strength": entry["strength"],
                                 "recall_count": entry["recall_count"]}
        audit.append({"field": "strength", "old": round(old, 4),
                      "new": entry["strength"], "source": "feedback_memory",
                      "reason": str(kind)})
        return {"entries": items, "deltas": deltas, "audit": audit, "idempotent": False}
    return {"entries": items, "deltas": {}, "audit": [], "idempotent": False}


def touch_batch(entries, event_ids, now, kind="recall", limit=None):
    """Touch several recalled memories: one row per entry, never one aggregate.

    Each entry keeps its own old/new/boost row; an entry already touched at or
    after `now` is skipped (cooldown), and `limit` caps how many may move in
    one turn. Returns {"entries", "rows", "deltas", "skipped"}.
    """
    items = [dict(entry or {}) for entry in (entries or [])]
    wanted = [str(item) for item in (event_ids or []) if str(item or "")]
    if limit is None:
        limit = len(wanted) or 0
    rows = []
    skipped = []
    moved = 0
    for target in wanted:
        if moved >= max(0, int(limit)):
            skipped.append({"id": target, "reason": "turn_cap"})
            continue
        found = None
        for entry in items:
            if str(entry.get("id")) == target:
                found = entry
                break
        if found is None:
            skipped.append({"id": target, "reason": "not_found"})
            continue
        last_touch = float(found.get("last_touch_ts", 0.0) or 0.0)
        if last_touch > 0 and float(now) - last_touch < COOLDOWN_SECONDS:
            skipped.append({"id": target, "reason": "cooldown"})
            continue
        old = _num(found.get("strength"), 1.0)
        found["strength"] = round(min(1.0, old + BOOST), 4)
        found["recall_count"] = int(found.get("recall_count", 0) or 0) + 1
        found["last_touched"] = float(now)
        found["last_decay_ts"] = float(now)
        found["last_touch_ts"] = float(now)
        found["last_touch_kind"] = str(kind)
        if found["recall_count"] > CORE_AFTER:
            found["core_memory"] = True
        rows.append({"id": target, "old": round(old, 4),
                     "new": found["strength"],
                     "boost": round(found["strength"] - old, 4),
                     "recall_count": found["recall_count"],
                     "source": "feedback_memory", "reason": str(kind)})
        moved += 1
    deltas = {row["id"]: {"strength": row["new"],
                          "recall_count": row["recall_count"]}
              for row in rows}
    return {"entries": items, "rows": rows, "deltas": deltas,
            "skipped": skipped, "idempotent": not rows}


def decay_all(entries, now, d=D, tau_hours=TAU_HOURS):
    items = []
    forgotten = []
    for entry in entries or []:
        entry = dict(entry or {})
        if entry.get("core_memory"):
            items.append(entry)
            continue
        last = _num(entry.get("last_decay_ts"), 0.0)
        hours = max(0.0, (float(now) - last) / 3600.0) if last > 0 else 0.0
        entry["strength"] = round(_mf.strength(_num(entry.get("strength"), 1.0), hours, d, tau_hours), 4)
        entry["last_decay_ts"] = float(now)
        if entry["strength"] < THRESHOLD:
            forgotten.append(str(entry.get("id")))
        items.append(entry)
    return {"entries": items, "forgotten_ids": forgotten}


def select_for_prompt(entries, limit=4, now=None, rng=None):
    r = rng or random
    eligible = []
    skipped = []
    for entry in entries or []:
        entry = dict(entry or {})
        strength = _num(entry.get("strength"), 0.0)
        if strength < THRESHOLD:
            skipped.append(str(entry.get("id")))
            continue
        eligible.append((entry, strength))
    selected = []
    pool = list(eligible)
    while pool and len(selected) < int(limit):
        total = sum(weight for _entry, weight in pool)
        roll = r.random() * total
        upto = 0.0
        chosen_index = len(pool) - 1
        for index, (_entry, weight) in enumerate(pool):
            upto += weight
            if roll <= upto:
                chosen_index = index
                break
        selected.append(pool.pop(chosen_index)[0])
    skipped.extend(str(entry.get("id")) for entry, _strength in pool)
    return {"selected": selected, "skipped": skipped}
