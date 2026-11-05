# -*- coding: utf-8 -*-
"""task-228: one write-back arbiter for the shared field.

All five learners submit *proposals* -- "I want field X to move by d" -- and
this module decides what the field actually becomes. The rules are deliberately
few and explainable:

1. Every proposal is KEPT per field. Nothing is summed and nothing is
   averaged: resolved[field]["proposals"] lists every learner, its delta and its
   weight, and the value is chosen by one named strategy for that field.
   Strategies: max_weight (default; the most trusted learner wins, ties broken
   by the larger magnitude), weighted_median (opt-in) and first (declaration
   order). The median is one strategy, not the definition of the field: on two
   opposite proposals it always lands on one side, which quietly normalizes.
2. Cap (single write): the winning delta is clipped to field.MAX_STEP[name] per
   apply, so no learner can move a field by a whole range in one turn.
3. Range: the new value is clipped into the field's range; whatever the cap
   and the range remove is reported back as a rejection, never silently.
4. Idempotency: a batch carrying a `txid` already applied is a no-op. The txid
   ledger lives in <store>/field.json, so a retried CLI call cannot double-write.

Counters (applied / rejected / conflicts / batches / duplicates) are persisted
with the field and exposed by /state.
"""
from __future__ import annotations

import math

try:  # package import (biocore_runtime.arbiter)
    from . import field as _field
except Exception:  # pragma: no cover - script mode
    from biocore_runtime import field as _field

# How much each learner is trusted when it disagrees with another one.
DEFAULT_WEIGHTS = {
    "mood_recall": 0.6,        # read-side: nudges affect only indirectly
    "affect_encoding": 0.8,
    "memory_feedback": 1.0,    # the strongest direct evidence
    "preference_drift": 0.7,
    "consolidation": 0.5,      # slow, conservative
    "state_sync": 1.0,         # host pushed a state the arbiter has not seen
}
DEFAULT_WEIGHT = 1.0

# Two proposals closer than this are not a conflict, they are agreement.
CONFLICT_EPS = 0.005
NOISE_EPS = _field.NOISE_EPS
TXID_KEEP = 32

COUNTERS = ("applied", "rejected", "conflicts", "batches", "duplicates")
STRATEGIES = ("max_weight", "weighted_median", "first")
# Most trusted learner wins; the median stays available but is never the default
# (it settles opposite proposals on one side = a hidden normalization).
DEFAULT_STRATEGY = "max_weight"
PROPOSAL_KEEP = 6      # proposals kept per field in the snapshot
FIELD_KEEP = 12        # fields kept in the snapshot


def weighted_median(pairs):
    """pairs: [(delta, weight), ...] -> the delta where cumulative weight
    first reaches half of the total. Deterministic, order-independent."""
    clean = []
    for delta, weight in pairs or []:
        value = _field._num(delta)
        mass = _field._num(weight, DEFAULT_WEIGHT)
        if value is None or mass is None or mass <= 0:
            continue
        clean.append((value, mass))
    if not clean:
        return 0.0
    clean.sort(key=lambda item: item[0])
    total = sum(mass for _, mass in clean)
    half = total / 2.0
    running = 0.0
    for value, mass in clean:
        running += mass
        if running >= half:
            return value
    return clean[-1][0]


def resolve(pairs, strategy=None):
    """(delta, strategy) for ONE field. The strategies never add proposals."""
    name = str(strategy or DEFAULT_STRATEGY).strip().lower()
    if name not in STRATEGIES:
        name = DEFAULT_STRATEGY
    rows = []
    for delta, weight in pairs or []:
        value = _field._num(delta)
        mass = _field._num(weight, DEFAULT_WEIGHT)
        if value is None or mass is None or mass <= 0:
            continue
        rows.append((value, mass))
    if not rows:
        return 0.0, name
    if name == "max_weight":
        best = max(rows, key=lambda row: (row[1], abs(row[0])))
        return best[0], name
    if name == "first":
        return rows[0][0], name
    return weighted_median(rows), "weighted_median"


def _looks_flat(mapping):
    for key in mapping:
        if _field.canonical(key) in _field.RANGES:
            return True
    return False


def iter_proposals(raw):
    """Normalise every accepted shape into [{"learner","field","delta","weight"}].

    Accepted:
      {"memory_feedback": {"v": 0.03, "a": -0.02}, "mood_recall": {"v": -0.01}}
      {"v": 0.03}                       (learner defaults to "unknown")
      [{"learner": "x", "field": "v", "delta": 0.02, "weight": 0.5}, ...]
    """
    items = []
    if isinstance(raw, dict):
        if _looks_flat(raw):
            for key, value in raw.items():
                items.append({"learner": "unknown", "field": key, "delta": value})
        else:
            for learner, mapping in raw.items():
                if not isinstance(mapping, dict):
                    continue
                for key, value in mapping.items():
                    items.append({"learner": str(learner), "field": key,
                                  "delta": value})
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, dict):
                items.append(dict(item))
    return items


class Arbiter(object):
    """Stateful write-back arbiter; counters survive through field.json."""

    def __init__(self, max_step=None, weights=None, state=None,
                 strategy=None):
        self.max_step = dict(_field.MAX_STEP)
        if isinstance(max_step, dict):
            for key, value in max_step.items():
                name = _field.canonical(key)
                number = _field._num(value)
                if name in self.max_step and number is not None and number > 0:
                    self.max_step[name] = number
        self.weights = dict(DEFAULT_WEIGHTS)
        if isinstance(weights, dict):
            for key, value in weights.items():
                name = str(key or "").strip().lower()
                number = _field._num(value)
                if name and number is not None and number > 0:
                    self.weights[name] = number
        state = state if isinstance(state, dict) else {}
        self.counters = {key: max(0, int(_field._num(state.get(key), 0) or 0))
                         for key in COUNTERS}
        txids = state.get("txids")
        self.txids = [str(item) for item in txids][-TXID_KEEP:] \
            if isinstance(txids, list) else []
        self.strategy = (str(strategy or "").strip().lower()
                         if str(strategy or "").strip().lower() in STRATEGIES
                         else DEFAULT_STRATEGY)
        self.proposals = {}      # last batch, per field, every proposal kept

    # -- reporting ----------------------------------------------------
    def stats(self):
        return {"applied": self.counters["applied"],
                "rejected": self.counters["rejected"],
                "conflicts": self.counters["conflicts"]}

    def snapshot(self):
        out = dict(self.counters)
        out["txids"] = list(self.txids)
        out["strategy"] = self.strategy
        out["proposals"] = {name: [dict(item) for item in rows]
                            for name, rows in self.proposals.items()}
        return out

    # -- resolution ---------------------------------------------------
    def _weight(self, learner, explicit=None):
        number = _field._num(explicit)
        if number is not None and number > 0:
            return number
        return self.weights.get(str(learner or "").strip().lower(),
                                DEFAULT_WEIGHT)

    def apply(self, field_value, proposals, txid=None, enabled=True, now=None,
              strategy=None):
        """Resolve proposals against the field; returns what was accepted.

        Every proposal stays visible in resolved[field]["proposals"]; the field
        value comes from the chosen strategy, never from a sum.
        """
        field_value = (field_value if isinstance(field_value, _field.Field)
                       else _field.Field())
        base = field_value.read()
        empty = {"applied": {}, "rejected": [], "conflicts": [], "resolved": {}}
        if not enabled:
            self.counters["batches"] += 1
            return {"ok": True, "enabled": False, "duplicate": False,
                    "field": base, "version": field_value.version,
                    "stats": self.stats(), **empty}

        token = str(txid or "").strip()
        if token and token in self.txids:
            self.counters["duplicates"] += 1
            return {"ok": True, "enabled": True, "duplicate": True,
                    "reason": "duplicate_txid", "field": base,
                    "version": field_value.version, "stats": self.stats(),
                    **empty}

        self.counters["batches"] += 1
        buckets = {}
        rejected = []
        for item in iter_proposals(proposals):
            name = _field.canonical(item.get("field") or item.get("name")
                                    or item.get("key"))
            learner = str(item.get("learner") or item.get("source")
                          or "unknown").strip().lower()[:32]
            if name not in _field.RANGES:
                rejected.append({"field": str(item.get("field") or ""),
                                 "learner": learner,
                                 "reason": "unknown_field"})
                continue
            delta = _field._num(item.get("delta", item.get("value")))
            if delta is None:
                rejected.append({"field": name, "learner": learner,
                                 "reason": "bad_delta"})
                continue
            if abs(delta) <= NOISE_EPS:
                rejected.append({"field": name, "learner": learner,
                                 "reason": "zero_delta"})
                continue
            weight = self._weight(learner, item.get("weight"))
            if weight <= 0:
                rejected.append({"field": name, "learner": learner,
                                 "reason": "bad_weight"})
                continue
            buckets.setdefault(name, []).append((delta, weight, learner))

        applied = {}
        conflicts = []
        resolved = {}
        self.proposals = {}
        for name, entries in buckets.items():
            values = [delta for delta, _, _ in entries]
            proposals = [{"learner": learner, "delta": round(delta, 6),
                          "weight": round(weight, 4)}
                         for delta, weight, learner in entries]
            self.proposals[name] = proposals[-PROPOSAL_KEEP:]
            chosen, used = resolve([(delta, weight)
                                    for delta, weight, _ in entries], strategy)
            if len(entries) >= 2 and (max(values) - min(values)) > CONFLICT_EPS:
                conflicts.append({
                    "field": name,
                    "learners": [learner for _, _, learner in entries],
                    "deltas": [round(delta, 6) for delta in values],
                    "strategy": used,
                    "winner": round(chosen, 6),
                })
            cap = float(self.max_step.get(name, 1.0))
            capped = max(-cap, min(cap, chosen))
            low, high = _field.RANGES[name]
            old = float(base.get(name, _field.DEFAULTS[name]))
            new = max(low, min(high, old + capped))
            actual = round(new - old, 6)
            resolved[name] = {"strategy": used,
                              "delta": round(chosen, 6),
                              "proposals": proposals,
                              "capped": round(capped, 6),
                              "applied": actual,
                              "from": round(old, 6),
                              "to": round(new, 6),
                              "learners": [learner for _, _, learner in entries]}
            if abs(actual) <= NOISE_EPS:
                rejected.append({"field": name,
                                 "learners": [learner for _, _, learner in entries],
                                 "reason": "no_effect",
                                 "delta": round(chosen, 6)})
                field_value.set(name, new)
                continue
            field_value.set(name, new)
            applied[name] = actual

        self.counters["applied"] += len(applied)
        self.counters["rejected"] += len(rejected)
        self.counters["conflicts"] += len(conflicts)
        if applied:
            field_value.version = int(field_value.version) + 1
            stamp = _field.num(now)
            if stamp:
                field_value.ts = float(stamp)
        if token:
            self.txids.append(token)
            self.txids = self.txids[-TXID_KEEP:]

        return {"ok": True, "enabled": True, "duplicate": False,
                "field": field_value.read(), "version": field_value.version,
                "applied": applied, "rejected": rejected,
                "conflicts": conflicts, "resolved": resolved,
                "proposals": {name: [dict(item) for item in rows]
                              for name, rows in self.proposals.items()},
                "strategy": str(strategy or self.strategy),
                "stats": self.stats()}
