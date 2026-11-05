# -*- coding: utf-8 -*-
"""task-218: recall feedback into affect ("回忆回灌情绪").

A recalled memory already carries the affect it was encoded with (task-217,
entry["affect"]). Recall may feed a small share of that stored affect back
into the live affect state, so remembering a warm moment lifts the mood a
little and remembering a bad one pulls it down -- then stops.

Three guards, all from core/config.py:

  CAP       per-turn |delta| <= FEEDBACK_MAX_STEP, valence and arousal apart
  COOLDOWN  the same entry cannot feed twice inside FEEDBACK_COOLDOWN seconds
            (the caller owns the {entry_id: last_ts} map)
  FLOOR     at valence <= FEEDBACK_NEG_FLOOR a further negative pull is
            dropped to 0 and the caller is told (blocked_negative) to run a
            regulation strategy instead

Pure: no IO, no clock, no host import, never touches the store. The engine
passes the rows it actually injected (top-k), the current affect and now,
so one recall can be replayed exactly in a test.
"""
from __future__ import annotations

from ..core.config import (FEEDBACK_COOLDOWN, FEEDBACK_GAIN,
                           FEEDBACK_MAX_STEP, FEEDBACK_NEG_FLOOR)


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return default
    return number if number == number else default


def _clamp(value, low, high):
    return max(low, min(high, _num(value, low)))


def _pair(source):
    """(valence, arousal) from a dict, a 2-sequence or an object."""
    if isinstance(source, dict):
        v = source.get("v", source.get("valence", 0.0))
        a = source.get("a", source.get("arousal", 0.5))
    elif isinstance(source, (list, tuple)) and len(source) >= 2:
        v, a = source[0], source[1]
    else:
        v = getattr(source, "v", getattr(source, "valence", 0.0))
        a = getattr(source, "a", getattr(source, "arousal", 0.5))
    return _clamp(_num(v, 0.0), -1.0, 1.0), _clamp(_num(a, 0.5), 0.0, 1.0)


def _entry_of(row):
    if isinstance(row, dict):
        entry = row.get("entry")
        if isinstance(entry, dict):
            return entry
    return row if isinstance(row, dict) else {}


def stored_affect(entry):
    """(valence, arousal) stored at write time, or None when absent."""
    if not isinstance(entry, dict):
        return None
    affect = entry.get("affect")
    if not isinstance(affect, dict):
        return None
    if "valence" not in affect and "v" not in affect:
        return None
    raw_v = affect.get("valence", affect.get("v"))
    raw_a = affect.get("arousal", affect.get("a", 0.5))
    try:
        valid_v = float(raw_v)
        valid_a = float(raw_a)
    except Exception:
        return None
    if valid_v != valid_v or valid_a != valid_a:  # NaN
        return None
    return (_clamp(valid_v, -1.0, 1.0), _clamp(valid_a, 0.0, 1.0))


def key_of(entry):
    """Stable cooldown key: the entry id, else a text prefix."""
    entry = entry if isinstance(entry, dict) else {}
    entry_id = str(entry.get("id") or "").strip()
    if entry_id:
        return entry_id
    return "text:" + str(entry.get("text") or "")[:40]


def _weight(entry):
    return _clamp(entry.get("importance", 0.5) if isinstance(entry, dict) else 0.5,
                  0.0, 1.0)


def plan(rows, current, cooldowns=None, now=0.0, budget=None,
         gain=None, max_step=None, cooldown=None, neg_floor=None, split=True):
    """Decide the per-turn affect nudge for one recall batch.

    split=True (default): every recalled memory keeps its own proposal row
    (source id + v/a + weight); no averaged target is invented. The turn then
    takes the most trusted proposal (ties: the larger pull) instead of a mean.
    split=False restores the old weighted-average target exactly.

    rows       what this recall injected (row dicts or raw entries); trimmed
               to budget when given
    current    live affect: dict {v/a | valence/arousal}, (v, a) or object
    cooldowns  {entry key: last feedback ts}; read only, the caller updates it
    """
    cooldowns = cooldowns if isinstance(cooldowns, dict) else {}
    now = _num(now, 0.0)
    gain = _clamp(FEEDBACK_GAIN if gain is None else gain, 0.0, 1.0)
    max_step = max(0.0, _num(FEEDBACK_MAX_STEP if max_step is None else max_step,
                             FEEDBACK_MAX_STEP))
    cool = max(0.0, _num(FEEDBACK_COOLDOWN if cooldown is None else cooldown,
                         FEEDBACK_COOLDOWN))
    floor = _clamp(FEEDBACK_NEG_FLOOR if neg_floor is None else neg_floor,
                   -1.0, 1.0)
    before_v, before_a = _pair(current)

    batch = [row for row in (rows or []) if isinstance(row, dict)]
    if budget is not None:
        try:
            batch = batch[:max(1, int(budget))]
        except Exception:
            pass

    skipped = []
    eligible = []  # (key, (v, a), weight)
    for row in batch:
        entry = _entry_of(row)
        key = key_of(entry)
        pair = stored_affect(entry)
        if pair is None:
            skipped.append({"id": key, "reason": "no_affect"})
            continue
        last = cooldowns.get(key)
        if last is not None and now - _num(last, 0.0) < cool:
            skipped.append({"id": key, "reason": "cooldown"})
            continue
        eligible.append((key, pair, _weight(entry)))

    report = {
        "enabled": True,
        "before": [round(before_v, 4), round(before_a, 4)],
        "target": None,
        "delta": [0.0, 0.0],
        "after": [round(before_v, 4), round(before_a, 4)],
        "eligible": [key for key, _value, _weight_value in eligible],
        "applied": [],
        "skipped": skipped,
        "capped": False,
        "blocked_negative": False,
        "regulation": None,
        "proposals": [],
        "selected": "",
        "reason": "",
    }
    if not eligible:
        report["reason"] = "no_eligible_memory"
        return report

    total_w = sum(weight for _key, _value, weight in eligible)
    if total_w <= 0:
        total_w = float(len(eligible))
        weights = [1.0] * len(eligible)
    else:
        weights = [weight for _key, _value, weight in eligible]
    # Every recalled memory is a proposal with its own source id. Nothing is
    # averaged: the turn follows the most trusted proposal (ties -> the larger
    # pull), so a strong memory can never be diluted by a weak one.
    proposals = []
    for (key, pair, weight), mass in zip(eligible, weights):
        proposals.append({"id": str(key),
                          "v": round(_clamp(pair[0], -1.0, 1.0), 4),
                          "a": round(_clamp(pair[1], 0.0, 1.0), 4),
                          "weight": round(_num(mass, 1.0), 4),
                          "delta_v": round(_clamp(
                              (pair[0] - before_v) * gain, -max_step, max_step), 6),
                          "delta_a": round(_clamp(
                              (pair[1] - before_a) * gain, -max_step, max_step), 6)})
    report["proposals"] = proposals
    if not split and proposals:
        target_v = sum(row["v"] * row["weight"] for row in proposals) / max(
            1e-9, sum(row["weight"] for row in proposals))
        target_a = sum(row["a"] * row["weight"] for row in proposals) / max(
            1e-9, sum(row["weight"] for row in proposals))
        report["selected"] = ""
    else:
        winner = max(proposals,
                     key=lambda row: (row["weight"],
                                      abs(row["delta_v"]) + abs(row["delta_a"])))
        target_v, target_a = winner["v"], winner["a"]
        report["selected"] = str(winner["id"])
    target_v = _clamp(target_v, -1.0, 1.0)
    target_a = _clamp(target_a, 0.0, 1.0)

    raw_v = (target_v - before_v) * gain
    raw_a = (target_a - before_a) * gain
    delta_v = max(-max_step, min(max_step, raw_v))
    delta_a = max(-max_step, min(max_step, raw_a))
    report["capped"] = bool(abs(raw_v) > max_step + 1e-12
                            or abs(raw_a) > max_step + 1e-12)

    if delta_v < 0 and before_v <= floor:
        # Already low: do not push further down; regulation takes over.
        delta_v = 0.0
        report["blocked_negative"] = True
        report["reason"] = "negative_floor"

    report["target"] = [round(target_v, 4), round(target_a, 4)]
    report["delta"] = [round(delta_v, 6), round(delta_a, 6)]
    report["after"] = [round(_clamp(before_v + delta_v, -1.0, 1.0), 4),
                       round(_clamp(before_a + delta_a, 0.0, 1.0), 4)]
    if delta_v or delta_a:
        report["applied"] = list(report["eligible"])
        report["reason"] = report["reason"] or "ok"
    else:
        report["reason"] = report["reason"] or "no_change"
    return report


def enabled(flags=None, env=None):
    """Flag or env switch; both default off (old behaviour)."""
    flags = flags if isinstance(flags, dict) else {}
    if flags.get("memory_feedback") is True:
        return True
    raw = env.get("BIOCORE_MEMORY_FEEDBACK") if hasattr(env, "get") else None
    return str(raw or "").strip().lower() in ("1", "true", "on", "yes")
