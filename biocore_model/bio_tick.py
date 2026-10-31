# -*- coding: utf-8 -*-
"""L0 life-maintenance tick: pure state evolution, no model calls, no IO.

One tick advances the internal life process only -- emotion decay, interoceptive
update, needs/sleep debt, circadian alertness + allostatic load, discomfort and
a pending internal intent. Sending, prompting and memory retrieval stay outside
this module; a caller-owned 60s loop drives it (see the wiring snippet).

Literature
  Craig 2009 (insula interoception), Barrett 2017 (constructed emotion),
  Seth 2013 (interoceptive prediction), Garfinkel 2015 (three dimensions),
  Sterling 2012 (allostasis), Carver & Scheier 1998 (cybernetic control),
  Powers 1973 (perceptual control), Gross 1998 (regulation strategies).

Hard constraints: pure functions, stdlib only, no main import, no network, no
model call; the clock is injected (now / dt_hours); repeated calls with the same
now only take effect once (last_bio_tick_ts); dt is capped at 6 hours; the core
object is the caller's and is mutated only through plain attribute writes.
"""
from __future__ import annotations

import os
import time

from . import intero_core as _intero
from . import memory_dual as _memory_dual
from . import needs_sleep as _needs_sleep
from . import regulation_loop as _regulation
from . import sleep_circadian as _sleep

DT_CAP_HOURS = 6.0
DISCOMFORT_TRIGGER = 0.35
LOG_EVERY = 10
LOG_ENV = "BIOCORE_BIO_TICK_LOG"
DEFAULT_VALENCE_DECAY_MINUTES = 120.0
DEFAULT_AROUSAL_DECAY_MINUTES = 30.0
DEFAULT_SOCIAL_DECAY_MINUTES = 180.0


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _clip(value, lo=0.0, hi=1.0):
    try:
        return max(lo, min(hi, float(value)))
    except Exception:
        return lo


def _get(core, name, default=None):
    try:
        return getattr(core, name, default)
    except Exception:
        return default


def _put(core, name, value):
    try:
        setattr(core, name, value)
        return True
    except Exception:
        return False


def _snapshot(core):
    getter = getattr(core, "snapshot", None)
    if callable(getter):
        try:
            value = getter()
            if isinstance(value, dict):
                return dict(value)
        except Exception:
            pass
    return {}


def _half_life_factor(minutes, half_life):
    try:
        hl = max(1.0, float(half_life))
    except Exception:
        hl = 120.0
    return 0.5 ** (max(0.0, float(minutes)) / hl)


def _derive(core):
    """Recompute stress/energy from v/a/d/social (same equations as BioCore)."""
    if callable(getattr(core, "_derive", None)):
        try:
            core._derive()
            return True
        except Exception:
            pass
    v = _num(_get(core, "v", 0.0))
    a = _num(_get(core, "a", 0.5))
    d = _num(_get(core, "d", 0.55))
    soc = _num(_get(core, "social", 0.55))
    offset = _clip(_num(_get(core, "_metabolic_energy_offset", 0.0)), 0.0, 0.20)
    _put(core, "stress", _clip(0.45 * max(0.0, -v) * a + 0.35 * (1.0 - d)
                               + 0.20 * (1.0 - soc), 0.0, 1.0))
    _put(core, "energy", _clip(0.45 * a + 0.25 * max(0.0, v) + 0.20 * d
                               + 0.10 * soc - offset, 0.0, 1.0))
    return True


def _effective_dt(core, now, dt_hours):
    if dt_hours is None:
        last = _num(_get(core, "last_bio_tick_ts", 0.0))
        dt_hours = (now - last) / 3600.0 if last else 0.0
    dt = max(0.0, _num(dt_hours))
    return min(DT_CAP_HOURS, dt)


def _decay(core, dt_hours):
    """Emotion decay toward baselines using the core's own half-lives."""
    if dt_hours <= 0.0:
        return False
    minutes = dt_hours * 60.0
    if minutes < 0.05:  # < 3s: duplicate/near-zero tick, no-op
        return False
    emotion = str((_get(core, "labels", {}) or {}).get("emotion") or "neutral")
    factors = _get(core, "emotion_decay_factors", {}) or {}
    try:
        emo_factor = max(0.2, min(2.0, float(factors.get(emotion, 1.0))))
    except Exception:
        emo_factor = 1.0
    recovery = 1.0
    getter = getattr(core, "_recovery_speed", None)
    if callable(getter):
        try:
            recovery = max(0.8, min(1.2, float(getter())))
        except Exception:
            recovery = 1.0
    v = _num(_get(core, "v", 0.0))
    a = _num(_get(core, "a", 0.5))
    d = _num(_get(core, "d", 0.55))
    soc = _num(_get(core, "social", 0.55))
    v_hl = _num(_get(core, "valence_decay_minutes", DEFAULT_VALENCE_DECAY_MINUTES),
                DEFAULT_VALENCE_DECAY_MINUTES)
    a_hl = _num(_get(core, "arousal_decay_minutes", DEFAULT_AROUSAL_DECAY_MINUTES),
                DEFAULT_AROUSAL_DECAY_MINUTES)
    s_hl = _num(_get(core, "social_decay_minutes", DEFAULT_SOCIAL_DECAY_MINUTES),
                DEFAULT_SOCIAL_DECAY_MINUTES)
    v_rec = recovery if v < 0 else 1.0
    a_rec = recovery if a > 0.40 else 1.0
    s_rec = recovery if soc < 0.55 else 1.0
    _put(core, "v", _clip(v * _half_life_factor(minutes, v_hl * emo_factor / v_rec), -1, 1))
    _put(core, "a", _clip(0.40 + (a - 0.40) * _half_life_factor(
        minutes, a_hl * max(0.5, emo_factor) / a_rec), 0, 1))
    _put(core, "d", _clip(0.55 + (d - 0.55) * _half_life_factor(
        minutes, v_hl * emo_factor), -1, 1))
    _put(core, "social", _clip(0.55 + (soc - 0.55) * _half_life_factor(
        minutes, s_hl * emo_factor / s_rec), 0, 1))
    _derive(core)
    return True


def _physiology(core, now, dt_hours):
    """Circadian alertness + allostatic load (Sterling 2012)."""
    hour = time.localtime(float(now)).tm_hour
    alert = _sleep.circadian(hour)
    _put(core, "circadian_alertness", alert)
    stress = _num(_get(core, "stress", 0.0))
    load = _num(_get(core, "allostatic_load", 0.0))
    # Rate is per 0.25h, scaled by dt: 10s ticks keep the same hourly drift as
    # 60s ticks instead of applying the 0.25h step 6x more often.
    rate = 1.0 if dt_hours <= 0 else max(0.004, float(dt_hours) / 0.25)
    if stress > 0.55:
        load = _clip(load + rate * 0.01 * (stress - 0.55) * (1.0 - load), 0.0, 1.0)
    else:
        load = _clip(load - rate * 0.004 * (0.55 - stress), 0.0, 1.0)
    _put(core, "allostatic_load", load)
    if load > 0:
        _put(core, "stress", _clip(stress + 0.005 * load, 0.0, 1.0))
    return {"circadian_alertness": alert, "allostatic_load": round(load, 4)}


def _needs(core, now, dt_hours):
    """Needs pyramid + sleep-debt step (both idempotent by their own timestamps)."""
    needs = _get(core, "needs", None)
    try:
        needs = _needs_sleep.need_step(needs if isinstance(needs, dict) else None,
                                 events={}, dt=dt_hours, now=float(now))
        _put(core, "needs", needs)
    except Exception:
        needs = {}
    debt = _num(_get(core, "sleep_debt", 0.0))
    try:
        stepped = _needs_sleep.sleep_debt_step(debt, slept_hours=0.0, dt=dt_hours,
                                         now=float(now),
                                         state={"last_debt_ts": _num(
                                             _get(core, "last_debt_ts", 0.0))})
        debt = float(stepped.get("debt", debt))
        _put(core, "sleep_debt", debt)
        _put(core, "last_debt_ts", float(stepped.get("last_debt_ts", now)))
    except Exception:
        pass
    return {"needs": needs, "sleep_debt": round(float(debt), 3)}


def _context(core):
    conflict = _num(_get(core, "conflict_ema", 0.0))
    relationship = _get(core, "relationship_context", None)
    if isinstance(relationship, dict):
        rel = relationship.get("state") if isinstance(relationship.get("state"), dict) else {}
        conflict = max(conflict, _num(rel.get("conflict", 0.0)))
        closeness = _num(rel.get("closeness", 0.5))
    else:
        closeness = 0.5
    return {"energy": _num(_get(core, "energy", 0.5)),
            "conflict": _clip(conflict), "closeness": _clip(closeness, 0.0, 1.0)}


def bio_tick(core, now, dt_hours=None):
    """Advance one internal life tick; idempotent for the same now.

    Returns {changed, intero, discomfort, action, pending_intent, log,
    idempotent, dt_hours}. No sending, no model call, no file IO.
    """
    now = _num(now)
    last = _num(_get(core, "last_bio_tick_ts", 0.0))
    previous = _get(core, "intero", None)
    previous_view = _intero.view(previous if isinstance(previous, dict) else {})
    if last and now <= last:
        return {"changed": False, "idempotent": True, "intero": previous_view,
                "discomfort": previous_view.get("discomfort", 0.0),
                "action": _get(core, "pending_intent", None),
                "pending_intent": _get(core, "pending_intent", None),
                "dt_hours": 0.0,
                "log": {"emit": False, "reason": "same_now", "count": _num(
                    _get(core, "_bio_tick_count", 0))}}
    dt = _effective_dt(core, now, dt_hours)
    changed = False
    changed = _decay(core, dt) or changed
    needs_info = _needs(core, now, dt)
    physiology = _physiology(core, now, dt)
    changed = True
    state = _snapshot(core)
    state.update({"stress": _num(_get(core, "stress", 0.0)),
                  "arousal": _num(_get(core, "a", 0.5)),
                  "energy": _num(_get(core, "energy", 0.55)),
                  "sleep_debt": _num(_get(core, "sleep_debt", 0.0)),
                  "allostatic_load": _num(_get(core, "allostatic_load", 0.0)),
                  "conflict": _context(core)["conflict"]})
    intero = _intero.update(previous if isinstance(previous, dict) else None,
                            state, dt, now=now)
    _put(core, "intero", intero)
    measured = _intero.discomfort(intero)
    total = float(measured.get("total", 0.0))
    action = None
    if total > DISCOMFORT_TRIGGER:
        chosen = _regulation.choose_action(intero, _context(core))
        action = {"action": chosen.get("action"), "reason": chosen.get("reason"),
                  "expected_gain": chosen.get("expected_gain"), "ts": round(now, 3),
                  "discomfort": float(total), "source": "bio_tick"}
        _put(core, "pending_intent", action)
        changed = True
    _put(core, "last_bio_tick_ts", now)
    count = int(_num(_get(core, "_bio_tick_count", 0))) + 1
    _put(core, "_bio_tick_count", count)
    _log_all = str(os.getenv(LOG_ENV, "") or "").strip().lower() in ("1", "true", "yes", "on")
    log = {"emit": bool(_log_all or count == 1 or count % LOG_EVERY == 0), "count": count,
           "dt_hours": round(dt, 3), "intero": dict(intero),
           "discomfort": float(total),
           "action": (action or {}).get("action"),
           "physiology": physiology,
           "needs": needs_info.get("needs"),
           "sleep_debt": needs_info.get("sleep_debt")}
    return {"changed": bool(changed), "idempotent": False, "intero": intero,
            "discomfort": total, "action": action,
            "pending_intent": _get(core, "pending_intent", None),
            "dt_hours": dt, "log": log}


def memory_maintenance(core, now, dt_hours=None, entries=None):
    """Hourly memory decay + soft forgetting (memory_dual), never deletes.

    Throttled by last_memory_maint_ts (>= 1 hour). Entries come from the
    caller (list of dicts with retrieval_s); when absent the tick is a no-op.
    """
    now = _num(now)
    last = _num(_get(core, "last_memory_maint_ts", 0.0))
    if last and (now - last) < 3600.0:
        return {"skipped": True, "reason": "throttled", "decayed": 0, "forgotten": 0}
    dt = _effective_dt(core, now, dt_hours)
    rows = entries if isinstance(entries, list) else _get(core, "memory_entries", None)
    if not isinstance(rows, list):
        _put(core, "last_memory_maint_ts", now)
        return {"skipped": True, "reason": "no_entries", "decayed": 0, "forgotten": 0}
    threshold = _num(_get(_memory_dual, "FORGET_THRESHOLD", 0.15), 0.15)
    out = []
    forgotten = 0
    for row in rows:
        entry = dict(row) if isinstance(row, dict) else {}
        before = _num(entry.get("retrieval_s", 0.0))
        after = _memory_dual.decay(before, dt)
        entry["retrieval_s"] = round(after, 4)
        if after < threshold and not entry.get("hidden"):
            entry["hidden"] = True
            entry["hidden_ts"] = round(now, 3)
            entry["hidden_reason"] = "retrieval_below_threshold"
            forgotten += 1
        out.append(entry)
    _put(core, "memory_entries", out)
    _put(core, "last_memory_maint_ts", now)
    return {"skipped": False, "reason": "", "decayed": len(out),
            "forgotten": forgotten, "dt_hours": dt, "entries": out}
