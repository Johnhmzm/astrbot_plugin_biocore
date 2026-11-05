# -*- coding: utf-8 -*-
"""task-229 (P0-2): three time scales -- seconds / minutes / hours.

The same affect is read at three speeds, and each speed has its own decay and
its own learning rate:

    fast    seconds   the per-turn v/a: quick to move, quick to forget
    medium  minutes   the session mood: smoothed, decays toward the slow layer
    slow    hours     the relationship / baseline: almost still, and it only
                      accepts a change after the same direction repeats >= 3
                      times in a row (REPEAT["slow"])

Everything is a plain dict in the session state under "timescales":

    {"schema": 1, "ts": <epoch>, "updated_ts": <epoch>,
     "fast":   {"v": 0.0, "a": 0.5, "turns": 0},
     "medium": {"mood": 0.0, "arousal": 0.5, "turns": 0},
     "slow":   {"baseline": 0.0, "trust": 0.5, "streak": 0, "direction": 0,
                "pending": 0.0, "commits": 0, "rejects": 0}}

Contract
  step(model, sample, dt_seconds, now) -> (model, report)
      pure: the caller passes the numbers the turn produced; nothing is read
      from disk and nothing outside "timescales" is touched.
  The slow layer never moves on one sample: it accumulates a streak, and only
  the third consecutive same-direction sample is written (commit). A flip
  resets the streak and counts as a reject.
"""
from __future__ import annotations

import math
import time

SCHEMA = 1
SWITCH_KEY = "timescales"
ENV_KEY = "BIOCORE_TIMESCALES"

# Decay half-lives (seconds) and per-sample learning rates. [engineering]
# The three-layer split is an engineering choice; 180/1800/21600s, the learning
# rates and the step caps have no paper behind them (see PAPER-MAP.md).
DECAY_SECONDS = {"fast": 180.0, "medium": 1800.0, "slow": 6 * 3600.0}
LEARN = {"fast": 0.60, "medium": 0.25, "slow": 0.10}  # [engineering]
# How many consecutive same-direction samples a layer needs before it writes.
REPEAT = {"fast": 1, "medium": 2, "slow": 3}  # [engineering]
# Below this a change is noise (same floor as the field arbiter).
NOISE = 1e-4  # [engineering]
SLOW_STEP_CAP = 0.05      # [engineering]
MEDIUM_STEP_CAP = 0.12    # [engineering]
FAST_STEP_CAP = 0.35      # [engineering]

DEFAULTS = {
    "fast": {"v": 0.0, "a": 0.5, "turns": 0},
    "medium": {"mood": 0.0, "arousal": 0.5, "turns": 0},
    "slow": {"baseline": 0.0, "trust": 0.5, "streak": 0,
             "direction": 0, "pending": 0.0, "commits": 0, "rejects": 0},
}


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return float(default)
    if not math.isfinite(number):
        return float(default)
    return number


def _clamp(value, low, high):
    return max(low, min(high, _num(value, low)))


def _truthy(raw, default):
    if raw is None:
        return bool(default)
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("1", "true", "on", "yes"):
        return True
    if text in ("0", "false", "off", "no"):
        return False
    return bool(default)


def enabled(payload=None, env=None):
    data = payload if isinstance(payload, dict) else {}
    if isinstance(data.get(SWITCH_KEY), bool):
        return data[SWITCH_KEY]
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    if isinstance(switches.get(SWITCH_KEY), bool):
        return switches[SWITCH_KEY]
    environ = env if hasattr(env, "get") else None
    if environ is not None and ENV_KEY in environ:
        return _truthy(environ.get(ENV_KEY), True)
    return True


def initial(now=None):
    stamp = _num(now, time.time())
    model = {"schema": SCHEMA, "ts": round(stamp, 3),
             "updated_ts": round(stamp, 3)}
    for name in ("fast", "medium", "slow"):
        model[name] = dict(DEFAULTS[name])
    return model


def load(state):
    """Read (and repair) the timescales block of one session state."""
    state = state if isinstance(state, dict) else {}
    stored = state.get("timescales") if isinstance(state.get("timescales"), dict) else {}
    model = initial(stored.get("updated_ts") or stored.get("ts") or 0.0)
    for name in ("fast", "medium", "slow"):
        block = stored.get(name) if isinstance(stored.get(name), dict) else {}
        for key, default in DEFAULTS[name].items():
            if key in block:
                model[name][key] = (_num(block.get(key), default)
                                    if isinstance(default, (int, float))
                                    else block.get(key))
    if stored:
        model["ts"] = round(_num(stored.get("ts"), model["ts"]), 3)
        model["updated_ts"] = round(_num(stored.get("updated_ts"),
                                         model["updated_ts"]), 3)
    return model


def decay(value, dt_seconds, layer):
    """Exponential decay toward the layer's resting point (0 or 0.5)."""
    half = DECAY_SECONDS.get(layer, 180.0)
    dt = max(0.0, _num(dt_seconds, 0.0))
    if half <= 0:
        return value
    factor = 0.5 ** (dt / half)
    return value * factor


def _direction(delta, noise=NOISE):
    if abs(delta) <= noise:
        return 0
    return 1 if delta > 0 else -1


def _bounded_step(delta, cap):
    return max(-cap, min(cap, _num(delta, 0.0)))


def step(model, sample, dt_seconds=0.0, now=None):
    """Advance the three layers with one sample; returns (model, report).

    sample: {"v": float, "a": float, "trust": float (optional)}
    """
    model = load({"timescales": model}) if isinstance(model, dict) else initial(now)
    data = sample if isinstance(sample, dict) else {}
    stamp = _num(now if now is not None else data.get("now"), time.time())
    target_v = _clamp(data.get("v", 0.0), -1.0, 1.0)
    target_a = _clamp(data.get("a", 0.5), 0.0, 1.0)
    report = {"ts": round(stamp, 3), "dt": round(max(0.0, _num(dt_seconds)), 3),
              "fast": {}, "medium": {}, "slow": {}}

    # -- fast: seconds -------------------------------------------------
    fast = model["fast"]
    before = _num(fast.get("v"), 0.0)
    decayed = decay(before, dt_seconds, "fast")
    moved = _bounded_step(LEARN["fast"] * (target_v - decayed), FAST_STEP_CAP)
    fast["v"] = round(_clamp(decayed + moved, -1.0, 1.0), 6)
    fast["a"] = round(_clamp(_num(fast.get("a"), 0.5)
                             + _bounded_step(LEARN["fast"] * (target_a
                                                              - _num(fast.get("a"), 0.5)),
                                             FAST_STEP_CAP), 0.0, 1.0), 6)
    fast["turns"] = int(_num(fast.get("turns"), 0)) + 1
    report["fast"] = {"before": round(before, 6), "after": fast["v"],
                      "delta": round(fast["v"] - before, 6)}

    # -- medium: minutes (decays toward the slow baseline) --------------
    medium = model["medium"]
    slow = model["slow"]
    baseline = _num(slow.get("baseline"), 0.0)
    before_mood = _num(medium.get("mood"), 0.0)
    decayed_mood = baseline + (before_mood - baseline) * (
        0.5 ** (max(0.0, _num(dt_seconds)) / DECAY_SECONDS["medium"]))
    moved_mood = _bounded_step(LEARN["medium"] * (target_v - decayed_mood),
                               MEDIUM_STEP_CAP)
    medium["mood"] = round(_clamp(decayed_mood + moved_mood, -1.0, 1.0), 6)
    medium["arousal"] = round(_clamp(
        0.5 * _num(medium.get("arousal"), 0.5) + 0.5 * target_a, 0.0, 1.0), 6)
    medium["turns"] = int(_num(medium.get("turns"), 0)) + 1
    report["medium"] = {"before": round(before_mood, 6), "after": medium["mood"],
                        "delta": round(medium["mood"] - before_mood, 6),
                        "turns": medium["turns"]}

    # -- slow: hours, and only after REPEAT consecutive same-direction ---
    gap = target_v - baseline
    direction = _direction(gap)
    streak = int(_num(slow.get("streak"), 0))
    previous_direction = int(_num(slow.get("direction"), 0))
    if direction == 0:
        streak = 0
    elif direction == previous_direction:
        streak += 1
    else:
        if streak > 0:
            slow["rejects"] = int(_num(slow.get("rejects"), 0)) + 1
        streak = 1
    slow["streak"] = streak
    slow["direction"] = direction
    slow["pending"] = round(gap, 6)
    committed = 0.0
    if direction != 0 and streak >= REPEAT["slow"]:
        want = _bounded_step(LEARN["slow"] * gap, SLOW_STEP_CAP)
        before_slow = _num(slow.get("baseline"), 0.0)
        slow["baseline"] = round(_clamp(before_slow + want, -1.0, 1.0), 6)
        committed = round(slow["baseline"] - before_slow, 6)
        slow["commits"] = int(_num(slow.get("commits"), 0)) + 1
        slow["streak"] = 0
        slow["direction"] = 0
    trust_target = data.get("trust")
    if trust_target is not None:
        slow["trust"] = round(_clamp(_num(slow.get("trust"), 0.5), 0.0, 1.0), 6)
    report["slow"] = {"direction": direction, "streak": slow["streak"],
                      "committed": committed,
                      "baseline": slow["baseline"],
                      "repeats_needed": REPEAT["slow"]}

    model["ts"] = round(model.get("ts") or stamp, 3)
    model["updated_ts"] = round(stamp, 3)
    return model, report


def project(model):
    """The /state projection: three layers, no prompt text."""
    model = model if isinstance(model, dict) else initial()
    fast = model.get("fast") if isinstance(model.get("fast"), dict) else {}
    medium = model.get("medium") if isinstance(model.get("medium"), dict) else {}
    slow = model.get("slow") if isinstance(model.get("slow"), dict) else {}
    return {
        "enabled": True,
        "ts": _num(model.get("updated_ts"), 0.0),
        "fast": {"v": round(_num(fast.get("v")), 4),
                 "a": round(_num(fast.get("a"), 0.5), 4),
                 "turns": int(_num(fast.get("turns"), 0)),
                 "decay_seconds": DECAY_SECONDS["fast"]},
        "medium": {"mood": round(_num(medium.get("mood")), 4),
                   "arousal": round(_num(medium.get("arousal"), 0.5), 4),
                   "turns": int(_num(medium.get("turns"), 0)),
                   "decay_seconds": DECAY_SECONDS["medium"]},
        "slow": {"baseline": round(_num(slow.get("baseline")), 4),
                 "trust": round(_num(slow.get("trust"), 0.5), 4),
                 "streak": int(_num(slow.get("streak"), 0)),
                 "direction": int(_num(slow.get("direction"), 0)),
                 "commits": int(_num(slow.get("commits"), 0)),
                 "rejects": int(_num(slow.get("rejects"), 0)),
                 "decay_seconds": DECAY_SECONDS["slow"],
                 "repeats_needed": REPEAT["slow"]},
    }


def summary(state, enabled_override=None):
    if isinstance(enabled_override, bool) and not enabled_override:
        return {"enabled": False, "reason": "disabled"}
    model = load(state)
    row = project(model)
    row["enabled"] = True
    return row
