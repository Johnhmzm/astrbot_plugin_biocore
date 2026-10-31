# -*- coding: utf-8 -*-
"""Ebbinghaus forgetting + reconsolidation + rumination content (GAP-B)."""
from __future__ import annotations

D = 0.5
TAU_HOURS = 24.0
THRESHOLD = 0.15
RECALL_BOOST = 0.25
CORE_AFTER_CALLS = 5
RUMINATION_P = 0.3
RUMINATION_DECAY_PER_HOUR = 0.9
RUMINATION_MAX_COUNT = 5
RUMINATION_MAX_HOURS = 72.0
RUMINATION_DRIVE_BONUS = 0.02


def strength(s0, hours, d=D, tau_hours=TAU_HOURS):
    try:
        base = max(0.0, min(1.0, float(s0)))
        elapsed = max(0.0, float(hours))
        d = max(0.05, float(d))
        tau = max(1.0, float(tau_hours))
    except Exception:
        return 0.0
    return round(base * (1.0 + elapsed / tau) ** (-d), 6)


def decayed(entry, now, d=D, tau_hours=TAU_HOURS):
    """Return a copy with strength decayed; core memories never decay."""
    entry = dict(entry or {})
    if entry.get("core_memory"):
        entry["strength"] = round(min(1.0, max(0.0, float(entry.get("strength", 1.0) or 1.0))), 6)
        entry["last_decay_ts"] = float(now)
        return entry
    last = float(entry.get("last_decay_ts", entry.get("last_touched", 0.0)) or 0.0)
    base = float(entry.get("strength", 1.0) or 1.0)
    hours = max(0.0, (float(now) - last) / 3600.0) if last > 0 else 0.0
    entry["strength"] = strength(base, hours, d, tau_hours)
    entry["last_decay_ts"] = float(now)
    return entry


def recall(entry, now):
    """Reconsolidation: recalled -> strength += boost, count++, core after 5."""
    entry = dict(entry or {})
    base = float(entry.get("strength", 1.0) or 1.0)
    entry["strength"] = round(min(1.0, base + RECALL_BOOST), 6)
    entry["recall_count"] = int(entry.get("recall_count", 0) or 0) + 1
    entry["last_touched"] = float(now)
    entry["last_decay_ts"] = float(now)
    if entry["recall_count"] > CORE_AFTER_CALLS:
        entry["core_memory"] = True
    return entry


def injectable(entry, threshold=THRESHOLD):
    entry = entry or {}
    if entry.get("core_memory"):
        return True
    return float(entry.get("strength", 0.0) or 0.0) >= float(threshold)


def memory_view(entries, limit=5):
    rows = []
    forgotten = 0
    for entry in entries or []:
        try:
            entry = entry if isinstance(entry, dict) else {}
        except Exception:
            continue
        if not injectable(entry):
            forgotten += 1
            continue
        rows.append({"id": str(entry.get("id", "")), "strength": round(float(entry.get("strength", 0.0) or 0.0), 4)})
    rows.sort(key=lambda row: row["strength"], reverse=True)
    return {"top": rows[:limit], "forgotten_count": forgotten}


def add_rumination(items, target_type, target_id, snippet, now, valence=0.0, conflict=False):
    items = list(items or [])
    if not conflict and abs(float(valence or 0.0)) <= 0.4:
        return items
    key = (str(target_type), str(target_id))
    for item in items:
        if (str(item.get("target_type")), str(item.get("target_id"))) == key:
            item.update({"count": int(item.get("count", 1) or 1) + 1, "last_ts": float(now)})
            return items
    items.append({"target_type": str(target_type), "target_id": str(target_id),
                  "text_snippet": str(snippet or "")[:60], "count": 1,
                  "first_ts": float(now), "last_ts": float(now)})
    return items


def tick_rumination(items, now, rng=None):
    """Per tick: maybe count++, decay by 0.9/hour, drop when saturated/old."""
    import random
    r = rng or random
    kept = []
    for item in items or []:
        item = dict(item or {})
        last = float(item.get("last_tick_ts", item.get("last_ts", now)) or now)
        if float(now) <= last:
            kept.append(item)
            continue
        hours = max(0.0, (float(now) - last) / 3600.0)
        factor = RUMINATION_DECAY_PER_HOUR ** hours
        try:
            item["intensity"] = round(float(item.get("intensity", 1.0) or 1.0) * factor, 4)
        except Exception:
            item["intensity"] = 1.0
        if r.random() < RUMINATION_P:
            item["count"] = int(item.get("count", 1) or 1) + 1
        item["last_tick_ts"] = float(now)
        age_hours = (float(now) - float(item.get("first_ts", now))) / 3600.0
        if item["count"] >= RUMINATION_MAX_COUNT or age_hours >= RUMINATION_MAX_HOURS:
            continue
        kept.append(item)
    return kept


def rumination_text(items):
    items = items or []
    if not items:
        return ""
    return "你还在想：" + str(items[0].get("text_snippet") or "")[:40]
