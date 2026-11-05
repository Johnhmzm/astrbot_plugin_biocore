# -*- coding: utf-8 -*-
"""task-243: dimensions stay separate; every write carries a channel.

Rule
    v / a / stress / social / trust / closeness / needs.* are independent. This
    module never adds one dimension to another and never averages two sources
    into one number.

Channels
    explicit  what was said / asked for (appraisal, self-report, user text)
    implicit  what the body did (memory recall, host state sync, drift)
    Both are kept for every dimension. When the same dimension receives the two
    in opposite directions inside ONE write round (same evidence ts), ambivalence
    = min(|explicit delta|, |implicit delta|) and BOTH values stay. Nothing is
    averaged. The direction is read from the evidence written in that round, not
    from the level, so a bounded axis (0..1, e.g. trust) can be ambivalent too.

Projection
    project() regroups the eleven axes into four read-only channels and is the
    only view /state.dimensions shows:
        affect     v / a / dominance
        tension    stress
        relational social / trust / closeness
        needs      needs.belonging / needs.self_esteem / needs.control /
                   needs.meaningful_existence
    The grouping is a partition: every axis appears once, no axis is added to
    another, and project() hands back copies. Nothing is ever written back.

Behaviour
    decide() applies threshold + priority rules, in order. It never scores.

State
    {"schema":1, "ts":.., "dims": {name: {explicit, implicit, ambivalence,
     changed, evidence:[{source, channel, delta, ts}] }}, "hops": n}

Switch: dimensions_v2 (default ON). With it off the caller keeps the old
single-value path (arbiter median + summed deltas).
"""
from __future__ import annotations

import math
import time

SWITCH_KEY = "dimensions_v2"
ENV_KEY = "BIOCORE_DIMENSIONS_V2"
SCHEMA = 1
EVIDENCE_LIMIT = 12          # newest rows kept per axis; one round may write 4 sources
NOISE = 1e-4

DIMS = ("v", "a", "dominance", "stress", "social", "trust", "closeness",
        "conflict",
        "needs.belonging", "needs.self_esteem", "needs.control",
        "needs.meaningful_existence")
RANGES = {"v": (-1.0, 1.0), "a": (0.0, 1.0), "dominance": (0.0, 1.0),
          "stress": (0.0, 1.0),
          "social": (0.0, 1.0), "trust": (0.0, 1.0), "closeness": (0.0, 1.0),
          "conflict": (0.0, 1.0),
          "needs.belonging": (0.0, 1.0), "needs.self_esteem": (0.0, 1.0),
          "needs.control": (0.0, 1.0), "needs.meaningful_existence": (0.0, 1.0)}
# Per-dimension damping when the two channels disagree (replaces the single
# global regulation absorb of task-234).
DAMP = {"v": 0.45, "a": 0.35, "dominance": 0.35, "stress": 0.40,
        "social": 0.40,
        "trust": 0.50, "closeness": 0.50, "conflict": 0.45,
        "needs.belonging": 0.30, "needs.self_esteem": 0.30,
        "needs.control": 0.30, "needs.meaningful_existence": 0.30}
AMBIVALENCE_GATE = 0.15   # [engineering] product threshold, not a scale cut
EVIDENCE_ROUND = 3          # evidence ts precision: one write round = one ts

# Four read-only projection channels. A partition of DIMS: every axis appears
# exactly once, so no channel is ever a sum of axes.
CHANNEL_AXES = {
    "affect": ("v", "a", "dominance"),
    "tension": ("stress",),
    "relational": ("social", "trust", "closeness", "conflict"),
    "needs": ("needs.belonging", "needs.self_esteem", "needs.control",
              "needs.meaningful_existence"),
}
CHANNELS = tuple(CHANNEL_AXES)
# Names other modules already use for the same axis. Aliases never create a new
# axis and are never added together.
# Relationship conflict is its own axis (De Dreu & Weingart 2003: relationship
# and task conflict are different dimensions; Mayer et al. 1995: trust is not
# the absence of conflict; Aron et al. 1992: closeness is separate too). Only a
# RELATIONSHIP event may move it -- a task disagreement never does.
CONFLICT_SWITCH = "dimensions_conflict"
CONFLICT_ENV_KEY = "BIOCORE_DIMENSIONS_CONFLICT"
CONFLICT_EVENTS = ("appraisal_blame", "blame", "relational_conflict",
                   "relationship_conflict", "repair_failed", "confrontation",
                   "explicit_hostility")
TASK_EVENTS = ("task_disagreement", "task_conflict", "work_dispute",
               "misunderstanding", "opinion_difference")
ALIASES = {"d": "dominance", "dom": "dominance",
           "belonging": "needs.belonging",
           "self_esteem": "needs.self_esteem",
           "control": "needs.control",
           "meaningful_existence": "needs.meaningful_existence"}

# Threshold + priority rules, highest priority first. No weighted sums.
RULES = (
    {"id": "safety_first", "dim": "stress", "op": ">=", "value": 0.80,
     "priority": 90, "action": "cool_down"},
    {"id": "ambivalence_clarify", "dim": "ambivalence", "op": ">=",
     "value": 0.30, "priority": 80, "action": "clarify"},
    {"id": "withdraw_urge", "dim": "social", "op": "<=", "value": 0.25,
     "priority": 60, "action": "short_reply"},
    {"id": "approach_urge", "dim": "social", "op": ">=", "value": 0.70,
     "priority": 60, "action": "approach"},
    {"id": "esteem_low", "dim": "needs.self_esteem", "op": "<=", "value": 0.35,
     "priority": 55, "action": "less_assertive"},
    {"id": "trust_thin", "dim": "trust", "op": "<=", "value": 0.30,
     "priority": 50, "action": "confirm_before_assuming"},
)


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return default
    if not math.isfinite(number):
        return default
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


def axis_of(name):
    """Canonical axis name for an incoming key; empty string when unknown."""
    key = str(name or "").strip()
    if key in RANGES:
        return key
    return ALIASES.get(key, "")


def pick(mapping):
    """{name: delta} -> {axis: delta}. Unknown names are dropped, nothing merged.

    A key that hits the same axis twice (e.g. "d" and "dominance") keeps the last
    value; two keys are never added together.
    """
    out = {}
    data = mapping if isinstance(mapping, dict) else {}
    for key, value in data.items():
        axis = axis_of(key)
        if not axis:
            continue
        number = _num(value)
        if abs(number) <= NOISE:
            continue
        out[axis] = round(number, 6)
    return out


def _evidence(row):
    items = row.get("evidence") if isinstance(row.get("evidence"), list) else []
    return [item for item in items if isinstance(item, dict)]


def _round_ambivalence(row, ts):
    """Opposite directions in ONE write round -> min(|e|,|i|); never a mean.

    Both channels in the same round (same evidence ts) are compared pairwise;
    each pair keeps its own evidence row, so nothing is summed across sources.
    """
    stamp = round(_num(ts, 0.0), EVIDENCE_ROUND)
    rows = [item for item in _evidence(row)
            if round(_num(item.get("ts"), 0.0), EVIDENCE_ROUND) == stamp]
    explicit = [_num(item.get("delta"), 0.0) for item in rows
                if str(item.get("channel")) == "explicit"]
    implicit = [_num(item.get("delta"), 0.0) for item in rows
                if str(item.get("channel")) == "implicit"]
    best = 0.0
    for a in explicit:
        for b in implicit:
            best = max(best, ambivalence(a, b))
    return round(best, 6)


def enabled(flags=None, env=None):
    data = flags if isinstance(flags, dict) else {}
    if isinstance(data.get(SWITCH_KEY), bool):
        return data[SWITCH_KEY]
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    if isinstance(switches.get(SWITCH_KEY), bool):
        return switches[SWITCH_KEY]
    environ = env if hasattr(env, "get") else None
    if environ is not None and ENV_KEY in environ:
        return _truthy(environ.get(ENV_KEY), True)
    return True


def conflict_enabled(flags=None, env=None):
    """dimensions_conflict: explicit flag > nested switches > env > ON."""
    data = flags if isinstance(flags, dict) else {}
    if isinstance(data.get(CONFLICT_SWITCH), bool):
        return data[CONFLICT_SWITCH]
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    if isinstance(switches.get(CONFLICT_SWITCH), bool):
        return switches[CONFLICT_SWITCH]
    environ = env if hasattr(env, "get") else None
    if environ is not None and CONFLICT_ENV_KEY in environ:
        return _truthy(environ.get(CONFLICT_ENV_KEY), True)
    return True


def is_conflict_event(event):
    """A relationship event may raise conflict; a task disagreement never does."""
    key = str(event or "").strip().lower()
    if key in TASK_EVENTS:
        return False
    return key in CONFLICT_EVENTS


def raise_conflict(model, event, delta, channel="explicit", source="",
                   now=None, flags=None):
    """Relationship conflict only. Trust and closeness are never touched here.

    De Dreu & Weingart 2003 separates relationship conflict from task conflict,
    so this entry point refuses task events outright; Mayer et al. 1995 and
    Aron et al. 1992 keep trust and closeness independent axes, so nothing is
    derived from the conflict value.
    """
    if isinstance(model, dict) is False:
        model = initial(now)
    if not conflict_enabled(flags):
        return model
    if not is_conflict_event(event):
        return model
    value = abs(_num(delta))
    if value <= NOISE:
        return model
    return contribute(model, "conflict", channel, value,
                      source=str(source or event), now=now)


def initial(now=None):
    stamp = round(_num(now, time.time()), 3)
    return {"schema": SCHEMA, "ts": stamp, "hops": 0,
            "dims": {name: {"explicit": 0.0, "implicit": 0.0,
                            "ambivalence": 0.0, "changed": False,
                            "evidence": []} for name in DIMS}}


def load(state):
    state = state if isinstance(state, dict) else {}
    stored = state.get("dimensions") if isinstance(state.get("dimensions"), dict) else {}
    model = initial(stored.get("ts"))
    model["hops"] = int(_num(stored.get("hops"), 0))
    dims = stored.get("dims") if isinstance(stored.get("dims"), dict) else {}
    for name in DIMS:
        row = dims.get(name) if isinstance(dims.get(name), dict) else {}
        low, high = RANGES[name]
        for channel in ("explicit", "implicit"):
            # a missing channel is the neutral 0.0, never the range's low bound
            model["dims"][name][channel] = round(
                _clamp(_num(row.get(channel), 0.0), low, high), 6)
        model["dims"][name]["ambivalence"] = round(
            _clamp(row.get("ambivalence"), 0.0, 1.0), 6)
        model["dims"][name]["changed"] = bool(row.get("changed"))
        evidence = row.get("evidence")
        model["dims"][name]["evidence"] = [dict(item) for item in evidence
                                           if isinstance(item, dict)][-EVIDENCE_LIMIT:] \
            if isinstance(evidence, list) else []
    return model


def ambivalence(explicit_delta, implicit_delta):
    """Same dimension, opposite directions -> both magnitudes kept, no mean."""
    a = _num(explicit_delta)
    b = _num(implicit_delta)
    if a == 0 or b == 0 or (a > 0) == (b > 0):
        return 0.0
    return round(min(abs(a), abs(b)), 6)


def contribute(model, dim, channel, delta, source="", now=None, ts=None):
    """One piece of evidence on one dimension, on one channel."""
    name = str(dim)
    if name not in RANGES:
        return model
    channel = "implicit" if str(channel) == "implicit" else "explicit"
    model = model if isinstance(model, dict) else initial(now)
    row = model["dims"].setdefault(name, {"explicit": 0.0, "implicit": 0.0,
                                          "ambivalence": 0.0, "changed": False,
                                          "evidence": []})
    value = _num(delta)
    if abs(value) <= NOISE:
        return model
    low, high = RANGES[name]
    row[channel] = round(_clamp(_num(row.get(channel), 0.0) + value, low, high), 6)
    row["changed"] = True
    evidence = row.get("evidence") if isinstance(row.get("evidence"), list) else []
    stamp = round(_num(ts if ts is not None else now, 0.0), EVIDENCE_ROUND)
    evidence.append({"source": str(source)[:32], "channel": channel,
                     "delta": round(value, 6), "ts": stamp})
    row["evidence"] = evidence[-EVIDENCE_LIMIT:]
    # Both channels of one round stay as separate levels; ambivalence is read
    # from that round's signed deltas, never from a sum of the two levels.
    row["ambivalence"] = _round_ambivalence(row, stamp)
    return model


def damp(dim, amount=1.0):
    """Per-dimension damping factor for a write (1.0 = untouched)."""
    share = _clamp(DAMP.get(str(dim), 0.35), 0.0, 1.0)
    return round(max(0.0, 1.0 - share * _clamp(amount, 0.0, 1.0)), 6)


def decide(model, extra_actions=None):
    """Threshold + priority only: returns the ordered action list."""
    model = model if isinstance(model, dict) else initial()
    hits = []
    rows = model.get("dims") or {}
    for rule in RULES:
        dim = rule["dim"]
        if dim == "ambivalence":
            value = max([_num(row.get("ambivalence"), 0.0)
                         for row in rows.values()] or [0.0])
            if value <= 0:
                continue
        else:
            row = rows.get(dim) or {}
            if not row.get("changed"):
                # no evidence on this axis: a threshold has nothing to read
                continue
            values = [_num(row.get(channel), 0.0)
                      for channel in ("explicit", "implicit")]
            value = max(values) if rule["op"] == ">=" else min(values)
            if rule["dim"] == "stress":
                value = max(values)
        ok = value >= _num(rule["value"]) if rule["op"] == ">=" else \
            value <= _num(rule["value"])
        if ok:
            hits.append({"id": rule["id"], "dim": dim, "value": round(value, 4),
                         "threshold": _num(rule["value"]),
                         "action": rule["action"], "priority": rule["priority"]})
    for row in extra_actions or []:
        if isinstance(row, dict) and row.get("action"):
            hits.append(dict(row))
    hits.sort(key=lambda item: -_num(item.get("priority"), 0))
    return hits


def project(model, actions=None, conflict=None):
    """Read-only view: per-axis rows, then the four-channel projection.

    The projection only REGROUPS the eleven axes (see CHANNEL_AXES): every
    number is still one axis on one channel. Nothing is added across axes,
    averaged across sources or written back; the caller gets copies and the
    model passed in is never touched.
    """
    model = model if isinstance(model, dict) else initial()
    if conflict is None:
        conflict = True
    axes = tuple(name for name in DIMS
                 if conflict or name != "conflict")
    out = {"enabled": True, "schema": SCHEMA, "ts": _num(model.get("ts"), 0.0),
           "hops": int(_num(model.get("hops"), 0)), "dims": {},
           "projection": {}, "actions": list(actions or [])}
    for name in axes:
        row = (model.get("dims") or {}).get(name) or {}
        out["dims"][name] = {
            "explicit": round(_num(row.get("explicit"), 0.0), 4),
            "implicit": round(_num(row.get("implicit"), 0.0), 4),
            "ambivalence": round(_num(row.get("ambivalence"), 0.0), 4),
            "changed": bool(row.get("changed"))}
    for channel, channel_axes in CHANNEL_AXES.items():
        out["projection"][channel] = {axis: dict(out["dims"][axis])
                                      for axis in channel_axes
                                      if axis in out["dims"]}
    out["behavior"] = decide(model, actions)
    return out


def absorb(model, explicit=None, implicit=None, source="", now=None):
    """One write round: every axis keeps its own line, on its own channel.

    explicit / implicit are {name: delta} mappings. A delta is never added to
    another axis and never merged into the other channel; two writes on one axis
    in one call are two evidence rows. Both channels of a round share one
    timestamp so ambivalence reads them together.
    """
    out = model if isinstance(model, dict) else initial(now)
    stamp = now if now is not None else time.time()
    rows = 0
    for channel, mapping in (("explicit", explicit), ("implicit", implicit)):
        for axis, delta in pick(mapping).items():
            out = contribute(out, axis, channel, delta, source=source,
                             ts=stamp, now=stamp)
            rows += 1
    if rows:
        out["hops"] = int(_num(out.get("hops"), 0)) + 1
        out["ts"] = round(_num(stamp, time.time()), 3)
    return out


def summary(state, enabled_override=None):
    if enabled_override is False:
        return {"enabled": False, "reason": "disabled"}
    model = load(state)
    row = project(model)
    row["enabled"] = True
    return row
