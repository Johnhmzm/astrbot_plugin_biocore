# -*- coding: utf-8 -*-
"""task-230: indicative priority driven by surprise (predictive processing).

Friston 2010 (free energy): a signal that departs from the expectation carries
more information, so it should be encoded and consolidated before the rest.

Surprise
    |field - setpoint| / scale(axis), per axis, clamped to 0..1. The setpoint
    is the neutral line the field itself declares (field.DEFAULTS), the scale is
    that axis' own span, so the six axes stay comparable without being summed
    into one state number.

Priority (per candidate)
    score = surprise x importance x relation x predictable

    surprise     how far this candidate's stored affect sits from the current
                 expectation (the live field)
    importance   the entry's own importance (memory layer)
    relation     the relationship context at read time (trust / closeness)
    predictable  repeated content with no change is damped (0.3 .. 1.0), so
                 the tenth identical message is not what gets rehearsed

The switch surprise_priority is ON by default; with it off the caller keeps the
old newest-first ordering and the recall scores are untouched.
"""
from __future__ import annotations

import math

try:
    from . import field as _field
except Exception:  # pragma: no cover
    try:
        from biocore_runtime import field as _field
    except Exception:
        _field = None

SWITCH_KEY = "surprise_priority"
ENV_KEY = "BIOCORE_SURPRISE_PRIORITY"
SCHEMA = 1
AXES = ("v", "a", "stress", "social", "trust", "closeness")
SURPRISE_FLOOR = 0.35      # below this the field is "as expected"
PREDICTABLE_FLOOR = 0.3    # the lowest multiplier repeated content can reach
RANK_LIMIT = 10

RANGES = (dict(_field.RANGES) if _field is not None else
          {"v": (-1.0, 1.0), "a": (0.0, 1.0), "stress": (0.0, 1.0),
           "social": (0.0, 1.0), "trust": (0.0, 1.0), "closeness": (0.0, 1.0)})
SETPOINTS = (dict(_field.DEFAULTS) if _field is not None else
             {"v": 0.0, "a": 0.5, "stress": 0.5, "social": 0.5,
              "trust": 0.5, "closeness": 0.5})


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return float(default)
    if not math.isfinite(number):
        return float(default)
    return number


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _num(value, low)))


def enabled(flags=None, env=None):
    """surprise_priority: explicit flag > nested switches > env > default ON."""
    data = flags if isinstance(flags, dict) else {}
    if isinstance(data.get(SWITCH_KEY), bool):
        return data[SWITCH_KEY]
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    if isinstance(switches.get(SWITCH_KEY), bool):
        return switches[SWITCH_KEY]
    environ = env if hasattr(env, "get") else None
    if environ is not None and ENV_KEY in environ:
        raw = str(environ.get(ENV_KEY) or "").strip().lower()
        if raw in ("0", "false", "off", "no"):
            return False
    return True


def scale_of(axis):
    low, high = RANGES.get(axis, (-1.0, 1.0))
    return max(1e-6, high - low)


def axis_surprise(axis, value):
    """|value - setpoint| / scale, clamped to 0..1."""
    setpoint = _num(SETPOINTS.get(axis, 0.0))
    return round(_clamp(abs(_num(value, setpoint) - setpoint)
                        / scale_of(axis)), 6)


def field_values(core=None, relationship=None):
    """The six field numbers from a state's core plus the relationship."""
    core = core if isinstance(core, dict) else {}
    rel = relationship if isinstance(relationship, dict) else {}
    out = {}
    for axis in AXES:
        if axis in ("trust", "closeness"):
            out[axis] = rel.get(axis, core.get(axis, SETPOINTS[axis]))
        else:
            out[axis] = core.get(axis, SETPOINTS[axis])
    return {axis: _num(value, SETPOINTS[axis]) for axis, value in out.items()}


def field_surprise(values=None):
    """Per-axis surprise plus the mean; axes are never summed into a state."""
    data = values if isinstance(values, dict) else {}
    axes = {axis: axis_surprise(axis, data.get(axis, SETPOINTS[axis]))
            for axis in AXES}
    top = sorted(axes.items(), key=lambda row: -row[1])[:3]
    return {"axes": axes,
            "value": round(sum(axes.values()) / max(1, len(axes)), 4),
            "top": [{"axis": axis, "surprise": value} for axis, value in top]}


def entry_surprise(entry, values=None):
    """How unexpected this entry's own affect is against the live field."""
    entry = entry if isinstance(entry, dict) else {}
    field = values if isinstance(values, dict) else {}
    affect = entry.get("affect") if isinstance(entry.get("affect"), dict) else {}
    pairs = []
    for axis in ("v", "a"):
        raw = affect.get(axis, entry.get(axis))
        if raw is None:
            continue
        expected = field.get(axis, SETPOINTS[axis])
        pairs.append(_clamp(abs(_num(raw, expected) - _num(expected))
                            / scale_of(axis)))
    if not pairs:
        return 0.0
    return round(sum(pairs) / len(pairs), 6)


def predictable(entry):
    """Repeated, unchanged content is less worth rehearsing (1.0 = not damped)."""
    entry = entry if isinstance(entry, dict) else {}
    hits = max(1, int(_num(entry.get("hits"), 1)))
    recalls = max(0, int(_num(entry.get("retrieval_count"), 0)))
    repeat = min(1.0, (hits - 1) * 0.25 + recalls * 0.10)
    if repeat <= 0:
        return 1.0
    return round(max(PREDICTABLE_FLOOR, 1.0 - 0.7 * repeat), 4)


def relation_factor(relationship=None):
    """Relationship context in 0.25..1.0 (trust/closeness, not a sum of axes)."""
    rel = relationship if isinstance(relationship, dict) else {}
    trust = _clamp(rel.get("trust", 0.5))
    closeness = _clamp(rel.get("closeness", 0.5))
    return round(_clamp(0.25 + 0.5 * closeness + 0.25 * trust), 4)


def score_entry(entry, values=None, relationship=None):
    """One candidate line: every factor kept, plus the product."""
    entry = entry if isinstance(entry, dict) else {}
    surprise = entry_surprise(entry, values)
    importance = _clamp(entry.get("importance", 0.5))
    relation = relation_factor(relationship)
    damp = predictable(entry)
    return {"id": str(entry.get("id") or ""),
            "text": str(entry.get("text") or "")[:60],
            "ts": round(_num(entry.get("ts"), 0.0), 3),
            "surprise": surprise,
            "importance": round(importance, 4),
            "relation": relation,
            "predictable": damp,
            "score": round(surprise * importance * relation * damp, 6)}


def rank(entries, values=None, relationship=None, limit=RANK_LIMIT,
         enabled_override=None):
    """Top candidates by indicative priority (or the old newest-first order)."""
    rows = [row for row in (entries or []) if isinstance(row, dict)]
    if enabled_override is False:
        old = sorted(rows, key=lambda row: -_num(row.get("ts"), 0.0))
        return [{"id": str(row.get("id") or ""),
                 "text": str(row.get("text") or "")[:60],
                 "ts": round(_num(row.get("ts"), 0.0), 3),
                 "score": 0.0, "legacy": True}
                for row in old[:max(1, int(limit))]]
    scored = [score_entry(row, values, relationship) for row in rows]
    scored.sort(key=lambda row: (-row["score"], -row["ts"]))
    return scored[:max(1, int(limit))]


def recall_weight(entry, values=None):
    """Multiplier for one recall candidate (1.0 when nothing is surprising).

    Only content that is itself far from the current expectation is lifted, so
    a surprising field does not boost every memory equally.
    """
    surprise = entry_surprise(entry, values)
    if surprise < SURPRISE_FLOOR:
        return 1.0
    return round(min(2.0, 1.0 + 0.6 * (surprise - SURPRISE_FLOOR)), 4)


def summary(entries, values=None, relationship=None, limit=RANK_LIMIT,
            enabled_override=None):
    """Read-only /state block: the top rows plus the live field surprise."""
    on = True if enabled_override is None else bool(enabled_override)
    field_row = field_surprise(values)
    return {"schema": SCHEMA, "enabled": on,
            "field_surprise": field_row,
            "top": rank(entries, values, relationship, limit,
                        enabled_override=on)}
