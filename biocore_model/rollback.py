# -*- coding: utf-8 -*-
"""One-turn rollback: snapshot / restore / bounded ring buffer (pure, no IO).

task-126: keep the last few turns of restorable numeric state so the user can
undo one turn from chat (numeric values, needs, relationship and recent turns).
Messages are never deleted here; withdrawing a sent message belongs to the
platform. This module performs no IO and never imports the host plugin.
"""
from __future__ import annotations

import copy

RING_LIMIT = 10
RECENT_LIMIT = 8

STATE_KEYS = (
    "v", "a", "d", "social", "stress", "energy", "trust",
    "echo", "echo_trace", "attention", "boredom", "novelty_need",
    "boundary_pressure", "refusal_readiness", "conflict_ema",
    "rumination_ema", "ticks",
)
NEEDS_KEYS = ("belonging", "self_esteem", "control", "meaningful_existence")


def _num(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _numeric_map(raw, keys=None):
    out = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        if keys is not None and key not in keys:
            continue
        number = _num(value)
        if number is not None:
            out[str(key)] = number
    return out


def snapshot(core_doc, recent_limit=RECENT_LIMIT):
    """Copy the restorable fields of one turn into a bounded snapshot.

    core_doc keys: state (numeric core snapshot), needs, relationship,
    recent_turns (list of turn dicts), memory_marker (ids/limits written this
    turn). Unknown keys and non-numeric values are dropped so the snapshot can
    be restored into a different core build.
    """
    doc = core_doc if isinstance(core_doc, dict) else {}
    try:
        limit = max(1, min(80, int(recent_limit)))
    except Exception:
        limit = RECENT_LIMIT
    recent = doc.get("recent_turns")
    recent = ([copy.deepcopy(x) for x in recent if isinstance(x, dict)][-limit:]
              if isinstance(recent, (list, tuple)) else [])
    relationship = doc.get("relationship")
    marker = doc.get("memory_marker")
    return {
        "state": _numeric_map(doc.get("state"), STATE_KEYS),
        "needs": _numeric_map(doc.get("needs"), NEEDS_KEYS),
        "relationship": copy.deepcopy(relationship)
        if isinstance(relationship, dict) else {},
        "recent_turns": recent,
        "memory_marker": copy.deepcopy(marker)
        if isinstance(marker, dict) else {},
    }


def restore(core_doc, snap):
    """Return a copy of core_doc with the snapshot fields applied.

    Missing/invalid snapshot fields leave the current doc untouched; the input
    doc and snapshot are never mutated.
    """
    out = copy.deepcopy(core_doc) if isinstance(core_doc, dict) else {}
    if not isinstance(snap, dict) or not snap:
        return out
    state = _numeric_map(snap.get("state"))
    if state:
        current = out.get("state") if isinstance(out.get("state"), dict) else {}
        merged = dict(current)
        merged.update(state)
        out["state"] = merged
    needs = _numeric_map(snap.get("needs"))
    if needs:
        out["needs"] = needs
    relationship = snap.get("relationship")
    if isinstance(relationship, dict):
        out["relationship"] = copy.deepcopy(relationship)
    recent = snap.get("recent_turns")
    if isinstance(recent, (list, tuple)):
        out["recent_turns"] = [copy.deepcopy(x) for x in recent
                              if isinstance(x, dict)]
    marker = snap.get("memory_marker")
    if isinstance(marker, dict):
        out["memory_marker"] = copy.deepcopy(marker)
    return out


def push(ring, snap, limit=RING_LIMIT):
    """Append one snapshot to a newest-last ring, keeping the last ``limit``."""
    try:
        cap = max(1, min(100, int(limit)))
    except Exception:
        cap = RING_LIMIT
    items = [copy.deepcopy(x) for x in (ring or []) if isinstance(x, dict)]
    if isinstance(snap, dict) and snap:
        items.append(copy.deepcopy(snap))
    return items[-cap:]


def pop(ring):
    """Remove and return the newest snapshot: (remaining_ring, snap_or_None)."""
    items = [copy.deepcopy(x) for x in (ring or []) if isinstance(x, dict)]
    if not items:
        return [], None
    latest = items.pop()
    return items, latest


def can_rollback(ring):
    return bool([x for x in (ring or []) if isinstance(x, dict)])


def describe(snap):
    """Short human summary for the /biocore rollback reply."""
    if not isinstance(snap, dict) or not snap:
        return "没有可回退的轮次"
    state = snap.get("state") if isinstance(snap.get("state"), dict) else {}
    recent = snap.get("recent_turns") if isinstance(snap.get("recent_turns"), list) else []
    parts = []
    if "v" in state:
        parts.append("v=%.2f" % float(state.get("v", 0.0)))
    if "stress" in state:
        parts.append("stress=%.2f" % float(state.get("stress", 0.0)))
    parts.append("最近 %d 轮" % len(recent))
    return "回退到 " + "，".join(parts)
