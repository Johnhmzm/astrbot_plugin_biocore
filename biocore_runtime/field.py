# -*- coding: utf-8 -*-
"""task-228: the six coupled fields live in exactly one place.

WHY
---
Five learners (mood_recall / affect_encoding / memory_feedback /
preference_drift / consolidation) all reason about the same six quantities:
valence, arousal, stress, social drive, trust, closeness. Before this module
each of them kept its own copy (engine.affect, the session state file, the
relationship sidecar), so two learners could pull the same number in opposite
directions within one turn and the last writer silently won.

CONTRACT
--------
* `FIELDS` is the whole vocabulary: {"v", "a", "stress", "social", "trust",
  "closeness"}. Nothing outside this module declares a range, a default or a
  per-turn cap for those six.
* turn_start: `from_state()` derives the field from the persisted session state
  plus the relationship sidecar, `load()/reconcile()` decide whether the
  persisted <store>/field.json is still valid, and `doc()/save()` persist it.
  Learners are handed `Field.read()` -- a plain copy, so mutating it changes
  nothing.
* turn_end: deltas are proposed, arbitrated by biocore_runtime.arbiter, and the
  winning deltas are written back once via `to_state()`.
* Switch `field_arbiter` (env BIOCORE_FIELD_ARBITER) defaults ON. When it is
  off nothing here runs: no field.json is created, no delta is arbitrated and
  the host keeps its old direct-write behaviour.

<store>/sessions/<sid>/field.json is the authoritative record of the six
values for one conversation:

    {"schema": 1, "session_id": "s1", "version": 7, "updated_ts": 1700.0,
     "values": {"v": 0.2, ...}, "source": "state|field",
     "arbiter": {"applied": 3, "rejected": 1, "conflicts": 2, ...}}

The file is also the arbiter ledger (counters + recent txids), so idempotency
survives across CLI calls -- every DSH turn is a fresh Python process.
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

SCHEMA = 1

# The whole field vocabulary. Order is the documented /state order.
FIELDS = ("v", "a", "stress", "social", "trust", "closeness")

RANGES = {
    "v": (-1.0, 1.0),
    "a": (0.0, 1.0),
    "stress": (0.0, 1.0),
    "social": (0.0, 1.0),
    "trust": (0.0, 1.0),
    "closeness": (0.0, 1.0),
}

DEFAULTS = {
    "v": 0.0,
    "a": 0.5,
    "stress": 0.5,
    "social": 0.5,
    "trust": 0.5,
    "closeness": 0.5,
}

# Per-apply step cap: one turn can move a field at most this far. trust and
# closeness reuse the relationship sidecar's cap so the two write paths agree.
MAX_STEP = {
    "v": 0.10,
    "a": 0.10,
    "stress": 0.08,
    "social": 0.08,
    "trust": 0.02,
    "closeness": 0.02,
}

# Below this a value or a delta counts as "the same".
NOISE_EPS = 1e-4

# trust/closeness are relationship-level, not affect-level.
RELATION_FIELDS = ("trust", "closeness")
AFFECT_FIELDS = ("v", "a", "stress", "social")

ALIASES = {"valence": "v", "arousal": "a", "stress_level": "stress"}

FIELD_FILE = "field.json"
FIELD_ENV = "BIOCORE_FIELD_ARBITER"
FIELD_FLAG = "field_arbiter"


# ---------------------------------------------------------------- helpers
def _num(value, default=None):
    try:
        number = float(value)
    except Exception:
        return default
    if not math.isfinite(number):
        return default
    return number


def clamp(name, value):
    """Coerce one value into the field's range; bad input -> None."""
    low, high = RANGES[name]
    number = _num(value)
    if number is None:
        return None
    return round(max(low, min(high, number)), 6)


# Public alias for sibling modules (arbiter) -- same coercion, same guards.
num = _num


def _truthy(raw, default):
    if raw is None:
        return bool(default)
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("1", "true", "on", "yes"):
        return True
    if text in ("0", "false", "off", "no", "disabled"):
        return False
    return bool(default)


def _root(store):
    if isinstance(store, dict):
        raw = store.get("root") or store.get("store") or store.get("path")
    else:
        raw = store
    text = str(raw or "").strip()
    return Path(text) if text else None


def flags_file(store):
    """<store>/flags.json, else <store>/../flags.json; None when absent."""
    root = _root(store)
    if root is None:
        return None
    for candidate in (root / "flags.json", root.parent / "flags.json"):
        try:
            if candidate.exists():
                return candidate
        except Exception:
            continue
    return None


def store_flags(store):
    path = flags_file(store)
    if path is None:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def enabled(flags=None, env=None, store=None):
    """Explicit payload > flags.json > env > default ON.

    `field_arbiter: False` (or BIOCORE_FIELD_ARBITER=0) restores the old direct
    write path everywhere; the default is True.
    """
    data = flags if isinstance(flags, dict) else {}
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    for source in (data, switches):
        if isinstance(source.get(FIELD_FLAG), bool):
            return source[FIELD_FLAG]
    file_flags = store_flags(store) if store is not None else {}
    if isinstance(file_flags.get(FIELD_FLAG), bool):
        return file_flags[FIELD_FLAG]
    environ = env if hasattr(env, "get") else None
    if environ is not None and FIELD_ENV in environ:
        return _truthy(environ.get(FIELD_ENV), True)
    return True


def canonical(name):
    text = str(name or "").strip().lower()
    return ALIASES.get(text, text)


# ---------------------------------------------------------------- values
class Field(object):
    """The six coupled values plus the bookkeeping the arbiter needs."""

    __slots__ = ("values", "version", "ts", "session_id", "source")

    def __init__(self, values=None, version=0, ts=0.0, session_id="", source="state"):
        self.values = dict(DEFAULTS)
        self.version = max(0, int(_num(version, 0) or 0))
        self.ts = float(_num(ts, 0.0) or 0.0)
        self.session_id = str(session_id or "")
        self.source = str(source or "state")
        data = values if isinstance(values, dict) else {}
        for name in FIELDS:
            if name in data:
                value = clamp(name, data.get(name))
                if value is not None:
                    self.values[name] = value

    # -- read ---------------------------------------------------------
    def get(self, name, default=None):
        key = canonical(name)
        if key not in RANGES:
            return DEFAULTS.get(key, default)
        return self.values.get(key, DEFAULTS[key])

    def read(self):
        """Plain copy handed to learners: mutating it changes nothing."""
        return {name: self.values[name] for name in FIELDS}

    def as_dict(self):
        return {"values": self.read(), "version": self.version,
                "ts": round(self.ts, 3), "session_id": self.session_id,
                "source": self.source}

    # -- write (arbiter only) ----------------------------------------
    def set(self, name, value):
        key = canonical(name)
        if key not in RANGES:
            return False
        number = clamp(key, value)
        if number is None:
            return False
        if abs(number - self.values[key]) <= NOISE_EPS:
            self.values[key] = number
            return False
        self.values[key] = number
        return True

    def copy(self):
        return Field(self.read(), version=self.version, ts=self.ts,
                     session_id=self.session_id, source=self.source)


# ---------------------------------------------------------------- derive
def _present_keys(state):
    state = state if isinstance(state, dict) else {}
    core = state.get("core") if isinstance(state.get("core"), dict) else {}
    out = set(state) | set(core)
    return out


def present(state):
    """Names the given state actually carries (aliases resolved)."""
    keys = _present_keys(state)
    found = set()
    for name in FIELDS:
        if name in keys:
            found.add(name)
    for alias, name in ALIASES.items():
        if alias in keys:
            found.add(name)
    rel = state.get("relationship") if isinstance(state, dict) else None
    if isinstance(rel, dict):
        for name in RELATION_FIELDS:
            if name in rel:
                found.add(name)
    return found


def _pick(state, name):
    state = state if isinstance(state, dict) else {}
    core = state.get("core") if isinstance(state.get("core"), dict) else {}
    if name in RELATION_FIELDS:
        rel = state.get("relationship")
        if isinstance(rel, dict) and name in rel:
            return rel.get(name)
        return state.get(name)
    for source in (core, state):
        if name in source and source.get(name) is not None:
            return source.get(name)
    for alias, target in ALIASES.items():
        if target != name:
            continue
        for source in (core, state):
            if alias in source and source.get(alias) is not None:
                return source.get(alias)
    return None


def from_state(state, relationship=None, now=None):
    """Derive the field from one session state (+ optional relationship dict)."""
    state = state if isinstance(state, dict) else {}
    merged = dict(state)
    if isinstance(relationship, dict) and relationship:
        rel = dict(state.get("relationship")) if isinstance(
            state.get("relationship"), dict) else {}
        rel.update(relationship)
        merged["relationship"] = rel
    values = {}
    for name in FIELDS:
        raw = _pick(merged, name)
        value = clamp(name, raw) if raw is not None else None
        values[name] = DEFAULTS[name] if value is None else value
    return Field(values, version=0, ts=_num(now, time.time()), source="state")


def to_state(state, field_value):
    """Project the field back into one session state (v/a/stress/social only).

    trust/closeness are written only when the session already owns a
    relationship dict -- the shared sidecar stays the owner of those two and
    the existing capped fold-back path applies the delta.
    """
    state = dict(state) if isinstance(state, dict) else {}
    field_value = field_value if isinstance(field_value, Field) else Field()
    core = dict(state.get("core")) if isinstance(state.get("core"), dict) else {}
    for name in AFFECT_FIELDS:
        core[name] = field_value.get(name)
    state["core"] = core
    if isinstance(state.get("relationship"), dict):
        rel = dict(state["relationship"])
        for name in RELATION_FIELDS:
            rel[name] = field_value.get(name)
        state["relationship"] = rel
    state["field_version"] = int(field_value.version)
    state["field_updated_ts"] = round(float(field_value.ts), 3)
    return state


# ---------------------------------------------------------------- persist
def path(store, session_id=None):
    """<store>/sessions/<sid>/field.json, or <store>/field.json without a session.

    One field per conversation: the six values are turn-level affect/trust, so a
    shared store must not let session A's turn rewrite session B's field.
    """
    root = _root(store)
    if root is None:
        return None
    sid = str(session_id or "").strip()
    if sid:
        return root / "sessions" / sid / FIELD_FILE
    return root / FIELD_FILE


def load(store, session_id=None):
    """Read one field file; missing or broken -> {} (never invents values)."""
    target = path(store, session_id)
    if target is None or not Path(target).exists():
        return {}
    try:
        doc = json.loads(Path(target).read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(doc, dict):
        return {}
    values = doc.get("values") if isinstance(doc.get("values"), dict) else {}
    if not values:
        return {}
    out = dict(doc)
    out["values"] = values
    out["version"] = max(0, int(_num(doc.get("version"), 0) or 0))
    out["updated_ts"] = float(_num(doc.get("updated_ts"), 0.0) or 0.0)
    out["session_id"] = str(doc.get("session_id") or "")
    out["arbiter"] = doc.get("arbiter") if isinstance(doc.get("arbiter"), dict) else {}
    return out


def save(store, doc, session_id=None):
    """Atomic write; a failure is reported, never raised."""
    target = path(store, session_id)
    if target is None:
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, target)
        return True
    except Exception:
        return False


def from_doc(doc):
    doc = doc if isinstance(doc, dict) else {}
    values = doc.get("values") if isinstance(doc.get("values"), dict) else {}
    return Field(values, version=doc.get("version", 0),
                 ts=doc.get("updated_ts", 0.0),
                 session_id=doc.get("session_id", ""),
                 source=doc.get("source", "field"))


def doc(field_value, arbiter_state=None, now=None):
    field_value = field_value if isinstance(field_value, Field) else Field()
    stamp = _num(now, time.time())
    if not field_value.ts:
        field_value.ts = stamp
    out = {
        "schema": SCHEMA,
        "session_id": field_value.session_id,
        "version": int(field_value.version),
        "updated_ts": round(float(field_value.ts or stamp), 3),
        "source": field_value.source,
        "values": field_value.read(),
    }
    if isinstance(arbiter_state, dict):
        out["arbiter"] = arbiter_state
    return out


def reconcile(stored, derived, eps=NOISE_EPS, adopt=None):
    """Turn-start reconciliation: returns (Field, reconciled: bool).

    * no stored field            -> the state wins (reconciled=True, source=state)
    * stored == state-derived    -> the field wins (reconciled=False, source=field)
    * stored != state-derived    -> the host wrote the state outside the arbiter,
                                    so the state wins and the version is bumped

    `adopt` narrows which names may be taken from the state. The body owns
    v/a/stress/social (core_state), while trust/closeness stay proposals so the
    relationship cap still applies -- see pipeline.field_turn_end.
    """
    names = tuple(adopt) if adopt else FIELDS
    if not isinstance(stored, Field):
        derived.source = "state"
        return derived, True
    drifted = [name for name in names
               if abs(float(derived.get(name)) - float(stored.get(name))) > eps]
    if not drifted:
        stored.source = "field"
        return stored, False
    merged = stored.copy()
    for name in names:
        merged.set(name, derived.get(name))
    merged.version = int(stored.version) + 1
    merged.ts = float(derived.ts or stored.ts)
    merged.source = "state"
    return merged, True
