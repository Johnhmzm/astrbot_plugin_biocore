# -*- coding: utf-8 -*-
"""Provider failover ordering + cooldown (pure, no IO, no host imports).

task-127: when the primary chat provider raises or times out, call the
configured fallback providers in order. A provider that just failed is cooled
down for COOLDOWN_SECONDS so one dead endpoint cannot slow every feature call.
The host keeps the mutable state dict on the plugin; this module only computes
the next candidate list and the updated state.
"""
from __future__ import annotations

COOLDOWN_SECONDS = 60.0
_RESERVED = ("current", "last_success_ts")


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _clean(provider):
    text = str(provider or "").strip()
    return text


def is_cooling(state, provider, now=0.0, cooldown=COOLDOWN_SECONDS):
    """True when *provider* failed less than ``cooldown`` seconds before now."""
    pid = _clean(provider)
    if not pid or pid in _RESERVED:
        return False
    if not isinstance(state, dict):
        return False
    last = _num(state.get(pid), 0.0)
    if last <= 0.0:
        return False
    current = _num(now, 0.0)
    if current <= 0.0:
        return False
    return (current - last) < max(0.0, _num(cooldown, COOLDOWN_SECONDS))


def candidates(primary, fallback_order=None, state=None, now=0.0,
               cooldown=COOLDOWN_SECONDS):
    """Ordered provider ids to try: primary first, then fallbacks (deduped).

    Providers still in their failure cooldown are skipped. An empty result
    means every candidate is cooling down; callers then give up.
    """
    ordered = []
    primary_id = _clean(primary)
    if primary_id:
        ordered.append(primary_id)
    if isinstance(fallback_order, (list, tuple)):
        for item in fallback_order:
            pid = _clean(item)
            if pid and pid not in _RESERVED and pid not in ordered:
                ordered.append(pid)
    return [pid for pid in ordered
            if not is_cooling(state, pid, now, cooldown)]


def mark_failure(state, provider, now=0.0):
    """Return a copy of state with the provider marked as failed at ``now``."""
    pid = _clean(provider)
    out = dict(state) if isinstance(state, dict) else {}
    if pid and pid not in _RESERVED:
        out[pid] = _num(now, 0.0)
    return out


def mark_success(state, provider, now=0.0):
    """Clear the cooldown and record the provider that actually answered."""
    pid = _clean(provider)
    out = dict(state) if isinstance(state, dict) else {}
    if pid and pid not in _RESERVED:
        out.pop(pid, None)
        out["current"] = pid
    out["last_success_ts"] = _num(now, 0.0)
    return out


def current(state):
    if not isinstance(state, dict):
        return ""
    value = state.get("current")
    return _clean(value) if value != "" else ""


def describe(state):
    value = current(state)
    failed = sorted(key for key in (state or {})
                    if key not in _RESERVED and _num((state or {}).get(key)) > 0)
    if value:
        return "current=%s failed=%s" % (value, ",".join(failed) or "-")
    return "failed=%s" % (",".join(failed) or "-")
