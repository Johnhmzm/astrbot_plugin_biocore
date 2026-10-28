# -*- coding: utf-8 -*-
"""Identity write orchestration (engine delegates here; store version-chained)."""
from __future__ import annotations
from ..core.config import MAX_STEP, SAME_DIRECTION_MIN
from ..core.util import clamp01, now_ts, sha12
from .writeback import (evidence_count, is_identity, is_major_trigger,
                        writeback_decision)


def _target(store, entry_id=None, trigger=None):
    if entry_id:
        return store.find(entry_id)
    identities = [e for e in store.entries if isinstance(e, dict) and is_identity(e)]
    if not identities:
        return None
    needle = str(trigger or "")
    for entry in identities:
        if needle and needle[:20] in str(entry.get("text") or ""):
            return entry
    return identities[0]


def _legacy(store, enabled, state, entry_id, direction=1, step=0.01, major_event=False):
    if not enabled:
        return {"allowed": False, "reason": "disabled", "applied": 0.0}
    entry = store.find(entry_id)
    if entry is None:
        return {"allowed": False, "reason": "missing", "applied": 0.0}
    if not is_identity(entry):
        return {"allowed": False, "reason": "not_identity", "applied": 0.0}
    allowed, applied, new_state, reason = writeback_decision(
        state.get(str(entry_id)), direction=direction,
        major_event=major_event, step=step if step is not None else 0.01)
    state[str(entry_id)] = new_state
    if not allowed:
        return {"allowed": False, "reason": reason, "applied": 0.0}
    current = clamp01(entry.get("identity_weight", 0.0))
    store.update(entry_id,
                 identity_weight=round(clamp01(current + applied), 4),
                 identity_writeback_ts=now_ts())
    return {"allowed": True, "reason": reason, "applied": round(applied, 4),
            "history": len(entry.get("previous_versions") or [])}


def write(store, enabled, state, trigger=None, evidence=None, delta=0.0,
          entry_id=None, direction=1, step=None, major_event=False, now=0.0):
    """New API trigger/evidence/delta, with legacy entry_id compatibility."""
    legacy = (evidence is None and entry_id is None and trigger is not None
              and store.find(trigger) is not None)
    if legacy:
        return _legacy(store, enabled, state, trigger, direction=direction,
                       step=step if step is not None else delta,
                       major_event=major_event)
    if not enabled:
        return {"allowed": False, "reason": "disabled", "applied": 0.0}
    evid = list(evidence or [])
    major = bool(major_event or is_major_trigger(trigger))
    target = _target(store, entry_id=entry_id, trigger=trigger)
    if target is None:
        if not (major or evidence_count(evid, delta) >= SAME_DIRECTION_MIN):
            return {"allowed": False, "reason": "need_more_same_direction",
                    "evidence_count": evidence_count(evid, delta), "applied": 0.0}
        text = str(trigger or "identity")[:120]
        target = store.add({"id": sha12(text + str(now)),
                            "text": text, "role": "system", "ts": now,
                            "self_defining": True, "importance": 0.8,
                            "memory_source": "identity_trigger"})
        if target is None:
            return {"allowed": False, "reason": "missing", "applied": 0.0}
    if not is_identity(target):
        return {"allowed": False, "reason": "not_identity", "applied": 0.0}
    stored = target.get("identity_evidence")
    combined = ([x for x in stored if isinstance(x, dict)]
                if isinstance(stored, list) else []) + [x for x in evid]
    count = evidence_count(combined, delta)
    if not (major or count >= SAME_DIRECTION_MIN):
        store.update(target.get("id"), identity_evidence=combined[-20:])
        return {"allowed": False, "reason": "need_more_same_direction",
                "evidence_count": count, "applied": 0.0,
                "target_id": str(target.get("id") or "")}
    try:
        amount = max(-MAX_STEP, min(MAX_STEP, float(delta or 0.0)))
    except Exception:
        amount = 0.0
    if amount == 0:
        amount = 0.01
    current = clamp01(target.get("identity_weight", 0.0))
    history = target.get("identity_history")
    history = list(history) if isinstance(history, list) else []
    history.append({"ts": now_ts(now), "trigger": str(trigger or "")[:80],
                    "evidence": combined[-20:], "delta": round(amount, 4)})
    store.update(target.get("id"),
                 identity_weight=round(clamp01(current + amount), 4),
                 identity_evidence=combined[-20:], identity_history=history[-20:],
                 identity_writeback_ts=now_ts(now))
    return {"allowed": True, "reason": "major_event" if major else "same_direction_3",
            "applied": round(amount, 4), "evidence_count": count,
            "target_id": str(target.get("id") or ""),
            "history": len(store.find(target.get("id")).get("previous_versions") or [])}
