# -*- coding: utf-8 -*-
"""Relationship stages (Hall 2019), contact frequency (Dunbar) and habituation."""
from __future__ import annotations

STAGES = (
    ("stranger", 0.0, 10.0, 8.0, 1),
    ("acquaintance", 10.0, 50.0, 14.0, 3),
    ("friend", 50.0, 90.0, 24.0, 5),
    ("close", 90.0, float("inf"), 36.0, 7),
)
NOVELTY_BASE = 0.85
NOVELTY_DISABLE = 0.3
DISABLE_HOURS = 24.0
WINDOW_DAYS = 7


def stage_for(hours_total):
    try:
        hours = max(0.0, float(hours_total or 0.0))
    except Exception:
        hours = 0.0
    for name, low, high, _tau, _daily in STAGES:
        if low <= hours < high:
            return name
    return "close"


def stage_config(hours_total):
    name = stage_for(hours_total)
    for row in STAGES:
        if row[0] == name:
            return {"stage": name, "hours_total": round(float(hours_total or 0.0), 2),
                    "tau_hours": row[3], "daily_cap": row[4],
                    "min_interval_hours": round(24.0 / (row[4] * 0.6), 2)}
    return {"stage": "stranger", "hours_total": 0.0, "tau_hours": 8.0,
            "daily_cap": 1, "min_interval_hours": 24.0}


def novelty(repeat_count):
    try:
        count = max(0, int(repeat_count or 0))
    except Exception:
        count = 0
    return round(NOVELTY_BASE ** count, 4)


def template_weight(template_id, usage, now, window_days=WINDOW_DAYS):
    row = dict((usage or {}).get(str(template_id)) or {})
    last = float(row.get("last_ts", 0.0) or 0.0)
    if last > 0 and (float(now) - last) > window_days * 86400:
        row["count"] = 0
    weight = novelty(row.get("count", 0))
    disabled = weight < NOVELTY_DISABLE and last > 0 and (float(now) - last) < DISABLE_HOURS * 3600
    return {"template_id": str(template_id), "count": int(row.get("count", 0) or 0),
            "weight": weight, "disabled": bool(disabled)}


def record_template(usage, template_id, now):
    usage = dict(usage or {})
    row = dict(usage.get(str(template_id)) or {"count": 0, "last_ts": 0.0})
    row["count"] = int(row.get("count", 0) or 0) + 1
    row["last_ts"] = float(now)
    usage[str(template_id)] = row
    return usage


def templates_view(usage, now):
    rows = []
    for template_id in (usage or {}):
        info = template_weight(template_id, usage, now)
        rows.append(info)
    rows.sort(key=lambda row: row["count"], reverse=True)
    disabled = [row["template_id"] for row in rows if row["disabled"]]
    return {"top_used": rows[:5], "disabled": disabled}


def pick_weighted(candidates, usage, now, rng=None):
    import random
    r = rng or random
    weighted = []
    for template in candidates or []:
        info = template_weight(template, usage, now)
        if info["disabled"]:
            continue
        weighted.append((template, max(0.01, info["weight"])))
    if not weighted:
        return None
    total = sum(weight for _template, weight in weighted)
    roll = r.random() * total
    upto = 0.0
    for template, weight in weighted:
        upto += weight
        if roll <= upto:
            return template
    return weighted[-1][0]
