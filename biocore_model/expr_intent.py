# -*- coding: utf-8 -*-
"""EXP-3: decide what she wants to say this time (expression layer, pure)."""
from __future__ import annotations

BASE = {"memory_due": 0.9, "open_loop": 0.7, "repair": 0.8, "gratitude": 0.6,
        "question": 0.5, "self_life": 0.5, "share_mood": 0.4, "comfort": 0.5}
REQUIRES_REAL_EVENT = ("memory_due", "gratitude")
MODES_DEACTIVATING = ("deactivating",)


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _valid(candidate, now=None):
    kind = str(candidate.get("kind") or "")
    if kind not in BASE:
        return False
    if kind in REQUIRES_REAL_EVENT and not candidate.get("event_ref") and not candidate.get("real", False):
        return False
    if _num(candidate.get("novelty", 1.0), 1.0) < 0.3:
        return False
    if kind == "memory_due":
        due = candidate.get("due_ts")
        if due is None:
            return False
        if now is not None and not (-86400 <= (float(due) - float(now)) <= 2 * 86400):
            return False
    return True


def pick_intent(candidates, state=None, rng=None):
    """Weighted intent picker; read-only, deterministic under a seeded rng."""
    import random
    state = dict(state or {})
    r = rng or random
    recent = [str(kind) for kind in (state.get("recent_kinds") or [])[-2:]]
    blocked = recent[0] if len(recent) == 2 and recent[0] == recent[1] else ""
    bid = _num(state.get("bid_frequency", 1.0), 1.0)
    responsiveness = _num(state.get("responsiveness", 0.5), 0.5)
    mode = str(state.get("attachment_mode") or "")
    now = state.get("now")
    rows = []
    for candidate in candidates or []:
        candidate = candidate if isinstance(candidate, dict) else {}
        kind = str(candidate.get("kind") or "")
        if kind == blocked or not _valid(candidate, now):
            continue
        weight = BASE[kind]
        weight *= _num(candidate.get("novelty", 1.0), 1.0)
        weight *= 0.6 + 0.4 * bid
        if kind == "self_life":
            weight *= 0.5 + 0.5 * responsiveness
        if kind == "question":
            weight *= 0.7 + 0.3 * responsiveness
        if mode in MODES_DEACTIVATING and kind in ("self_life", "question"):
            weight *= 0.5
        rows.append({"kind": kind, "text_hint": str(candidate.get("text_hint") or ""),
                     "weight": round(weight, 4)})
    if not rows:
        return {"kind": "", "text_hint": "", "weight": 0.0, "alternatives": []}
    total = sum(row["weight"] for row in rows)
    roll = r.random() * total
    upto = 0.0
    chosen = rows[-1]
    for row in rows:
        upto += row["weight"]
        if roll <= upto:
            chosen = row
            break
    alternatives = [row["kind"] for row in sorted(rows, key=lambda row: row["weight"], reverse=True)
                    if row["kind"] != chosen["kind"]]
    return {"kind": chosen["kind"], "text_hint": chosen["text_hint"],
            "weight": chosen["weight"], "alternatives": alternatives}
