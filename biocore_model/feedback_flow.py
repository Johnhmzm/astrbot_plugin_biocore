# -*- coding: utf-8 -*-
"""FB-5 feedback wiring: three channels into feedback_guard (the single writer).

Routes:
    apply_llm(payload, core, now)        -> feedback_llm.parse_to_deltas -> guard.vet+apply
    apply_user(msg_meta, core, now)      -> feedback_user.on_message     -> guard.vet+apply
    apply_memory(entries, now, kind)     -> feedback_memory.touch / decay_all

Design rules (task):
- only calls the existing modules; validation lives in feedback_llm/feedback_user/
  feedback_guard, this file never re-implements caps or whitelists.
- feedback_guard.vet + feedback_guard.apply are the only state writer. This module
  never assigns core attributes; when the host core exposes load_state() the
  guard-produced state dict is handed to it (optional bridge), otherwise the
  caller keeps the returned summary.
- idempotent per (core, channel, payload/meta, now): a repeated call returns
  idempotent=True with empty deltas and an old==new summary.
- no main import, no file IO.
"""
from __future__ import annotations

import hashlib
import json

from . import feedback_guard as _guard
from . import feedback_llm as _llm
from . import feedback_memory as _memory
from . import feedback_user as _user

SUMMARY_FIELDS = ("v", "a", "stress", "self_esteem")
CHANNELS = ("llm", "user")
_FLOW_SEEN = {}   # (id(core), channel) -> {request_key: report}
_MOD_SEEN = {}    # (id(core), channel) -> dict passed to feedback_llm/user


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _core_key(core):
    return id(core) if core is not None else 0


def _bucket(store, core, channel):
    key = (_core_key(core), str(channel))
    return store.setdefault(key, {})


def _hash(value):
    try:
        body = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        body = str(value)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _state_of(core):
    """Read-only core state dict: dict core, or core.snapshot()."""
    if isinstance(core, dict):
        return dict(core)
    getter = getattr(core, "snapshot", None)
    if callable(getter):
        try:
            state = getter()
            if isinstance(state, dict):
                return dict(state)
        except Exception:
            pass
    state = getattr(core, "state", None)
    return dict(state) if isinstance(state, dict) else {}


def _summary(before, after):
    out = {}
    for field in SUMMARY_FIELDS:
        old = _num((before or {}).get(field))
        new = _num((after or {}).get(field))
        out[field] = {"old": round(old, 4), "new": round(new, 4),
                      "delta": round(new - old, 4)}
    return out


def _write_back(core, state):
    """Optional bridge: hand guard-produced state to core.load_state().

    Never assigns core.<field> directly; a dict core is simply updated in place
    so callers can use the returned summary without a host object.
    """
    if isinstance(core, dict):
        core.update(state)
        return True
    loader = getattr(core, "load_state", None)
    if callable(loader):
        try:
            loader(dict(state))
            return True
        except Exception:
            return False
    return False


def _empty_report(before):
    return {"deltas": {}, "rejected": [], "audit": [], "idempotent": True,
            "summary": _summary(before, before), "changed": []}


def _run_guard(state, candidate, source, now, guard_seen):
    if not isinstance(candidate, dict) or not candidate:
        return {"accepted": {}, "rejected": [], "audit": [], "idempotent": False}
    return _guard.vet(candidate, state, source, now, seen=guard_seen)


def reset_seen(core=None):
    """Test/config helper: clear per-core idempotency buckets."""
    if core is None:
        _FLOW_SEEN.clear()
        _MOD_SEEN.clear()
        return
    for store in (_FLOW_SEEN, _MOD_SEEN):
        for key in list(store):
            if key[0] == _core_key(core):
                store.pop(key, None)


# ------------------------------------------------------------------ llm
def apply_llm(payload, core, now, limits=None):
    """Parse hidden LLM feedback -> guard -> state summary (idempotent per now)."""
    state_before = _state_of(core)
    request_key = "llm:" + _hash({"payload": payload, "now": now})
    flow = _bucket(_FLOW_SEEN, core, "llm")
    if request_key in flow:
        return _empty_report(state_before)

    mod_seen = _bucket(_MOD_SEEN, core, "llm_parse")
    guard_seen = _bucket(_MOD_SEEN, core, "llm_guard")
    parsed = _llm.parse_to_deltas(payload, limits=limits, state=state_before,
                                  now=now, seen=mod_seen)
    verdict = _run_guard(state_before, parsed.get("deltas"), "llm", now, guard_seen)
    accepted = verdict.get("accepted") or {}
    applied = _guard.apply(state_before, accepted)
    after = applied.get("state") or dict(state_before)
    written = _write_back(core, after) if accepted else False
    flow[request_key] = True
    return {
        "deltas": accepted,
        "rejected": list(parsed.get("rejected") or []) + list(verdict.get("rejected") or []),
        "audit": list(parsed.get("audit") or []) + list(verdict.get("audit") or []),
        "idempotent": bool(parsed.get("idempotent")) or bool(verdict.get("idempotent")),
        "summary": _summary(state_before, after),
        "changed": list(applied.get("changed") or []),
        "hash": str(parsed.get("hash") or ""),
        "written": bool(written),
    }


# ----------------------------------------------------------------- user
def apply_user(msg_meta, core, now):
    """User behaviour event -> guard -> state summary (idempotent per event)."""
    state_before = _state_of(core)
    request_key = "user:" + _hash({"meta": msg_meta, "now": now})
    flow = _bucket(_FLOW_SEEN, core, "user")
    if request_key in flow:
        return _empty_report(state_before)

    mod_seen = _bucket(_MOD_SEEN, core, "user_event")
    guard_seen = _bucket(_MOD_SEEN, core, "user_guard")
    parsed = _user.on_message(state_before, msg_meta, now, seen=mod_seen)
    verdict = _run_guard(state_before, parsed.get("deltas"), "user", now, guard_seen)
    accepted = verdict.get("accepted") or {}
    applied = _guard.apply(state_before, accepted)
    after = applied.get("state") or dict(state_before)
    written = _write_back(core, after) if accepted else False
    flow[request_key] = True
    return {
        "deltas": accepted,
        "rejected": list(parsed.get("rejected") or []) + list(verdict.get("rejected") or []),
        "audit": list(parsed.get("audit") or []) + list(verdict.get("audit") or []),
        "idempotent": bool(parsed.get("idempotent")),
        "summary": _summary(state_before, after),
        "changed": list(applied.get("changed") or []),
        "written": bool(written),
    }


# --------------------------------------------------------------- memory
def apply_memory(entries, now, kind="recall"):
    """Memory reconsolidation/decay through feedback_memory (pure, returns copies).

    kind:
      "decay"          -> feedback_memory.decay_all  (forgotten ids reported)
      "recall:<id>"    -> feedback_memory.touch one entry
      "select:<limit>" -> feedback_memory.select_for_prompt
      anything else    -> no-op (entries returned as-is)
    """
    rows = [dict(entry or {}) for entry in (entries or [])
            if isinstance(entry, dict)]
    label = str(kind or "").strip()
    lowered = label.lower()
    if lowered in ("decay", "decay_all"):
        result = _memory.decay_all(rows, now)
        return {"entries": result.get("entries") or rows,
                "forgotten": list(result.get("forgotten_ids") or []),
                "kind": "decay", "changed": True, "idempotent": False}
    if lowered.startswith("recall:"):
        event_id = label.split(":", 1)[1].strip()
        result = _memory.touch(rows, event_id, now, kind="recall")
        touched = result.get("entries") or rows
        changed = bool(result.get("deltas"))
        return {"entries": touched, "forgotten": [], "kind": "recall",
                "changed": changed,
                "idempotent": bool(result.get("idempotent")),
                "event_id": event_id, "deltas": result.get("deltas") or {}}
    if lowered.startswith("select:"):
        try:
            limit = max(1, int(label.split(":", 1)[1]))
        except Exception:
            limit = 4
        selected = _memory.select_for_prompt(rows, limit=limit, now=now)
        picked = selected.get("selected") or []
        return {"entries": picked, "forgotten": list(selected.get("skipped") or []),
                "kind": "select", "limit": limit, "changed": bool(picked),
                "idempotent": False}
    return {"entries": rows, "forgotten": [], "kind": "noop",
            "changed": False, "idempotent": True}
