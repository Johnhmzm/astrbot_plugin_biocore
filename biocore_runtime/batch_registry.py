# -*- coding: utf-8 -*-
"""Batch integration: one registry for b / c / d / e, all ON, per-module monitor.

The four batch hooks (biocore_runtime.batch_b / batch_c / batch_d / batch_e)
have different return shapes -- b/d/e return {"modules", "activity",
"field_deltas", "state_deltas", "skipped"}, the older c returns a flat bundle
with dotted "deltas". This module normalises both, merges the safe parts into
the session state, hands the six-field proposals to the arbiter, and keeps one
monitor row per module:

    <dataDir>/batch_monitor.json
    {"schema": 1, "ts": ..., "batches": {"b": {"calls": n, ...}},
     "modules": {"b.entity_resolve": {"calls": n, "changed": n,
                                      "last_effect": 0.0, "errored": n,
                                      "last_ts": 0.0}}}

No IO besides that one file; never raises into the turn.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

try:  # one resolution strategy for every field (never a cross-source sum)
    from . import arbiter as _arbiter
except Exception:  # pragma: no cover
    try:
        from biocore_runtime import arbiter as _arbiter
    except Exception:
        _arbiter = None

MONITOR_FILE = "batch_monitor.json"
SCHEMA = 1
MODULE_LIMIT = 320

BATCHES = ("b", "c", "d", "e")

# State blocks a batch may write top-level. Everything else is namespaced under
# state["batches"][<batch>] so a batch can never clobber the body/core fields.
SAFE_KEYS = ("entity_graph", "graph_stats", "memory_tiers", "dual_scores",
             "memory_scores", "memory_strength", "co_recall", "policy_q",
             "predictor_forecast", "predictor_history", "prediction",
             "migrate_report", "identity_read", "autonomy", "autonomy_acc",
             "expression", "state_tag", "topic_control", "reply", "silence",
             "feedback", "diagnostics", "diagnostic_row", "memory_layers",
             "graph", "co_recall_pairs", "reconstruction", "narrative")

FIELD_NAMES = ("v", "a", "stress", "social", "trust", "closeness")
CAPS = {"v": 0.10, "a": 0.10, "stress": 0.08, "social": 0.08,
        "trust": 0.02, "closeness": 0.02}

# Which read slice belongs to which module. A module without a slice has no
# observable view of its own this turn (it reports zero change, not "changed").
READ_OWNERS = {
    "b": {"identity": ("bio_identity",), "graph": ("graph_recall",),
          "entities": ("entity_resolve",), "memory_tiers": ("layered_memory",),
          "dual": ("memory_dual",), "forgetting": ("memory_forgetting",),
          "store": ("memory_store",), "policy": ("policy_learning",),
          "forecast": ("predictor",), "scores": ("scoring",),
          "graph_stats": ("entity_graph",), "strength": ("feedback_memory",),
          "co_recall": ("co_recall",), "migrate": ("migrate_store",)},
    "d": {"autonomy": ("autonomy_check", "autonomy_loop", "autonomy_model",
                       "autonomy_params", "autonomy_reason", "autonomy_mode"),
          "expression": ("expr_intent", "expr_tone", "granularity",
                         "exit_or_silence", "reply_limit", "reply_split",
                         "expr_state", "prompt_rules", "expr_guard",
                         "state_tag", "topic_control", "expr_template"),
          "feedback": ("feedback_flow", "feedback_guard", "feedback_llm",
                       "feedback_user"),
          "schedule": ("scheduler", "voice_bank", "proactive_context")},
    "e": {"diagnostics": ("diag_trace", "delta_budget", "schema", "bio_const"),
          "config": ("core_commands", "provider_fallback", "stages"),
          "monitoring": ("source_monitoring", "mind_wander", "noise_bank"),
          "probe": ("learning_probe", "extreme_scenarios")},
}
VIEW_LIMIT = 24
EFFECT_LIMIT = 8

# Reasons that are normal skips, not failures.
BENIGN = {"module_missing", "platform_isolation", "disabled", "duplicate",
          "no_entries", "no_tag", "no_sample", "no_pairs", "no_choice",
          "no_context", "no_action", "no_store", "no_forecast",
          "nothing_to_resolve", "bad_phase", "unavailable", "no_snapshot",
          "convert_failed", "no_deltas", "dry_run", "no_change"}


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return default
    if not math.isfinite(number):
        return default
    return number


def _root(store):
    if isinstance(store, dict):
        raw = store.get("root") or store.get("store") or store.get("path")
    else:
        raw = store
    text = str(raw or "").strip()
    return Path(text) if text else None


def _data_dir(store):
    root = _root(store)
    return (root.parent if root.name == "memory" else root) if root else None


def _read(path):
    try:
        if path is None or not path.exists():
            return {}
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def _write(path, doc):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(path)
        return True
    except Exception:
        return False


def path(store):
    root = _data_dir(store)
    return (root / MONITOR_FILE) if root is not None else None


# ---------------------------------------------------------------- normalise
def modules_of(batch_name, output):
    """The module names one batch claims (declared list or c-style fields)."""
    if not isinstance(output, dict):
        return ()
    declared = output.get("modules")
    if isinstance(declared, dict):
        return tuple(declared.keys())
    fields = output.get("fields")
    if isinstance(fields, list):
        return tuple(str(item) for item in fields)
    return ()


def normalize(batch_name, output):
    """Both shapes -> {enabled, modules, activity, field_deltas,
    state_deltas, skipped, errored, raw_keys}."""
    name = str(batch_name or "")
    if not isinstance(output, dict):
        return {"enabled": False, "reason": "bad_output", "modules": {},
                "activity": {}, "field_deltas": {}, "state_deltas": {},
                "skipped": [], "errored": 0, "raw_keys": []}
    declared = output.get("modules")
    if isinstance(declared, dict):  # b / d / e
        modules = {str(key): bool(value) for key, value in declared.items()}
        activity = output.get("activity")
        activity = ({str(key): bool(value) for key, value in activity.items()}
                    if isinstance(activity, dict) else dict(modules))
        field_deltas = {key: _num(value) for key, value in
                        (output.get("field_deltas") or {}).items()
                        if key in FIELD_NAMES}
        state_deltas = dict(output.get("state_deltas") or {})
        skipped = [dict(row) for row in (output.get("skipped") or [])
                   if isinstance(row, dict)]
        enabled = bool(output.get("enabled", True))
    else:  # batch_c style: flat bundle + dotted deltas
        fields = [str(item) for item in (output.get("fields") or [])]
        modules = {field: bool(output.get("ok", True)) for field in fields}
        activity = dict(modules)
        field_deltas = {}
        for key, value in (output.get("deltas") or {}).items():
            head = str(key).split(".")[0]
            if head in FIELD_NAMES:
                field_deltas[head] = _num(value)
        state_deltas = {"bundle": output}
        skipped = []
        enabled = bool(output.get("ok", True))
    errored = 0
    for row in skipped:
        reason = str(row.get("reason") or "")
        if reason and reason not in BENIGN:
            errored += 1
    reads = output.get("reads")
    if not isinstance(reads, dict):
        reads = output if not isinstance(declared, dict) else {}
    return {"enabled": enabled, "reason": str(output.get("reason") or "ok"),
            "modules": modules, "activity": activity,
            "field_deltas": field_deltas, "state_deltas": state_deltas,
            "skipped": skipped, "errored": errored,
            "reads": reads if isinstance(reads, dict) else {},
            "raw_keys": sorted(str(key) for key in output.keys())}


# ---------------------------------------------------------------- monitor
def read_monitor(store):
    doc = _read(path(store))
    modules = doc.get("modules") if isinstance(doc.get("modules"), dict) else {}
    batches = doc.get("batches") if isinstance(doc.get("batches"), dict) else {}
    return {"schema": SCHEMA, "ts": _num(doc.get("ts"), 0.0),
            "batches": {str(key): dict(value) for key, value in batches.items()
                        if isinstance(value, dict)},
            "modules": {str(key): dict(value) for key, value in modules.items()
                        if isinstance(value, dict)},
            "totals": _totals_of(doc)}


def flatten(value, prefix="", out=None, limit=VIEW_LIMIT):
    """Numeric channels of one module view: nested containers -> dotted keys."""
    out = {} if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(value, dict):
        for key, item in value.items():
            if len(out) >= limit:
                break
            label = "%s.%s" % (prefix, key) if prefix else str(key)
            flatten(item, label, out, limit)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(list(value)[:4]):
            flatten(item, "%s[%d]" % (prefix, index), out, limit)
    elif isinstance(value, bool):
        out[prefix] = 1.0 if value else 0.0
    else:
        number = _num(value, None)
        if number is not None:
            out[prefix] = round(number, 6)
    return out


def module_view(batch, module, row):
    """The read slice one module owns (its own output, not the batch total)."""
    row = row if isinstance(row, dict) else {}
    reads = row.get("reads") if isinstance(row.get("reads"), dict) else {}
    view = {}
    for key, modules in (READ_OWNERS.get(str(batch)) or {}).items():
        if str(module) not in modules:
            continue
        value = reads.get(key)
        if value is None:
            continue
        view.update(flatten(value, str(key), view))
        if len(view) >= VIEW_LIMIT:
            break
    if str(batch) == "c":
        bundle = (row.get("state_deltas") or {}).get("bundle")
        bundle = bundle if isinstance(bundle, dict) else {}
        if module in bundle:
            view.update(flatten(bundle.get(module), str(module), view))
    return dict(list(view.items())[:VIEW_LIMIT])


def diff_view(before, after, eps=1e-6, limit=EFFECT_LIMIT):
    """{channel: delta} for the channels this module itself moved."""
    old = before if isinstance(before, dict) else {}
    new = after if isinstance(after, dict) else {}
    changed = {}
    for key in set(old) | set(new):
        delta = round(_num(new.get(key), 0.0) - _num(old.get(key), 0.0), 6)
        if abs(delta) > eps:
            changed[key] = delta
    if len(changed) > limit:
        ordered = sorted(changed.items(), key=lambda item: -abs(item[1]))
        changed = dict(ordered[:limit])
    return changed


def _totals_of(doc):
    totals = doc.get("totals") if isinstance(doc.get("totals"), dict) else {}
    return {"calls": int(_num(totals.get("calls"), 0)),
            "changed": int(_num(totals.get("changed"), 0)),
            "zero_change": int(_num(totals.get("zero_change"), 0)),
            "errored": int(_num(totals.get("errored"), 0)),
            "active": int(_num(totals.get("active"), 0))}


def _bump_monitor(store, snapshots, now, changed_batches):
    """One monitor row per module: calls / changed / zero_change / effect."""
    doc = read_monitor(store)
    stamp = round(_num(now, time.time()), 3)
    doc["ts"] = stamp
    totals = _totals_of(doc)
    errors_this_tick = 0
    for name, row in snapshots.items():
        batch_row = doc["batches"].setdefault(
            name, {"calls": 0, "changed": 0, "zero_change": 0, "errored": 0})
        batch_row["calls"] = int(_num(batch_row.get("calls"), 0)) + 1
        batch_row["last_ts"] = stamp
        batch_row.setdefault("zero_change", 0)
        activity = row.get("activity") if isinstance(row.get("activity"), dict) else {}
        errors = int(_num(row.get("errored"), 0))
        if errors:
            errors_this_tick += errors
            batch_row["errored"] = int(_num(batch_row.get("errored"), 0)) + errors
        for module in (row.get("modules") or {}):
            if not bool(activity.get(module)):
                continue  # declared but idle this phase: not a call, no row
            key = "%s.%s" % (name, module)
            slot = doc["modules"].setdefault(
                key, {"calls": 0, "changed": 0, "zero_change": 0,
                      "last_effect": {}, "errored": 0})
            slot["calls"] = int(_num(slot.get("calls"), 0)) + 1
            slot.setdefault("zero_change", 0)
            slot["last_ts"] = stamp
            view = module_view(name, module, row)
            before = slot.get("view") if isinstance(slot.get("view"), dict) else None
            effect = diff_view(before or {}, view)
            totals["calls"] += 1
            if before is None:
                # first snapshot: nothing to compare yet, so not a change
                slot["zero_change"] += 1
                totals["zero_change"] += 1
                batch_row["zero_change"] += 1
            elif effect:
                slot["changed"] = int(_num(slot.get("changed"), 0)) + 1
                slot["last_effect"] = effect
                totals["changed"] += 1
                batch_row["changed"] = int(_num(batch_row.get("changed"), 0)) + 1
            else:
                slot["zero_change"] += 1
                totals["zero_change"] += 1
                batch_row["zero_change"] += 1
            if view:
                slot["view"] = view
            if name in changed_batches and effect:
                slot["last_ts"] = stamp
            if errors:
                slot["errored"] = int(_num(slot.get("errored"), 0)) + errors
    totals["errored"] += errors_this_tick
    totals["active"] = len(doc["modules"])
    doc["totals"] = totals
    if len(doc["modules"]) > MODULE_LIMIT:
        ordered = sorted(doc["modules"].items(),
                         key=lambda item: -_num(item[1].get("last_ts"), 0.0))
        doc["modules"] = dict(ordered[:MODULE_LIMIT])
    _write(path(store), doc)
    return doc


# ---------------------------------------------------------------- tick
def resolve_field(proposals, strategy=None):
    """(delta, strategy) for one field: the four batches are NOT summed.

    Each batch keeps its own proposal row; the field value is chosen by the
    arbiter's strategy (weighted median by default) over those proposals.
    """
    rows = [(_num(row.get("delta"), 0.0), 1.0) for row in proposals or []
            if isinstance(row, dict)]
    if not rows:
        return 0.0, "none"
    if _arbiter is not None:
        return _arbiter.resolve(rows, strategy)
    best = max(rows, key=lambda item: abs(item[0]))
    return best[0], "max_magnitude"


def tick(store, session_id, phase, payload=None, state=None, now=None,
         switches=None, hooks=None):
    """Run every enabled batch once; returns normalized rows + per-field deltas.

    A field may be named by more than one batch: every proposal is kept in
    field_proposals{field: [{batch, delta}]} and the value comes from
    resolve_field(), never from adding the batches together.
    """
    data = payload if isinstance(payload, dict) else {}
    session_state = state if isinstance(state, dict) else {}
    stamp = round(_num(now if now is not None else data.get("now"),
                       time.time()), 3)
    hooks = hooks if isinstance(hooks, dict) else {}
    table = switches if isinstance(switches, dict) else {}
    rows = {}
    field_proposals = {}
    field_deltas = {}
    resolved = {}
    state_deltas = {}
    snapshots = {}
    changed_batches = set()
    skipped_batches = []
    for name in BATCHES:
        hook = hooks.get(name)
        if hook is None:
            skipped_batches.append({"batch": name, "reason": "unavailable"})
            continue
        if table and table.get("batch_" + name) is False:
            skipped_batches.append({"batch": name, "reason": "disabled"})
            continue
        try:
            output = hook.apply_turn(session_state, phase, data)
        except Exception as error:  # a broken batch never breaks a turn
            rows[name] = {"enabled": False, "reason": type(error).__name__,
                          "modules": {}, "activity": {}, "field_deltas": {},
                          "state_deltas": {}, "skipped": [], "errored": 1,
                          "raw_keys": []}
            snapshots[name] = rows[name]
            continue
        row = normalize(name, output)
        rows[name] = row
        snapshots[name] = row
        if row["field_deltas"] or row["state_deltas"]:
            changed_batches.add(name)
        for key, value in row["field_deltas"].items():
            if key in FIELD_NAMES:
                field_proposals.setdefault(key, []).append(
                    {"batch": name, "delta": round(_num(value), 6)})
        for key, value in row["state_deltas"].items():
            if key in SAFE_KEYS:
                state_deltas[key] = value
            else:
                bucket = state_deltas.setdefault("batches", {})
                if isinstance(bucket, dict):
                    bucket.setdefault(name, {})[str(key)] = value
    for key, proposals in field_proposals.items():
        chosen, strategy = resolve_field(proposals)
        capped = round(max(-CAPS[key], min(CAPS[key], chosen)), 6)
        field_deltas[key] = capped
        resolved[key] = {"strategy": strategy, "delta": round(chosen, 6),
                         "capped": capped, "proposals": proposals}
    monitor = _bump_monitor(store, snapshots, stamp, changed_batches)
    return {"enabled": True, "phase": str(phase), "ts": stamp,
            "batches": rows, "field_deltas": field_deltas,
            "field_proposals": field_proposals, "resolved": resolved,
            "state_deltas": state_deltas, "skipped": skipped_batches,
            "monitor": {"batches": monitor.get("batches", {}),
                        "modules": monitor.get("modules", {}),
                        "totals": _totals_of(monitor)},
            "counts": {"batches": len(rows),
                       "modules": sum(len(row.get("modules") or {})
                                      for row in rows.values()),
                       "changed": len(changed_batches)}}


def summary(store):
    """Read-only monitor projection for /state."""
    doc = read_monitor(store)
    totals = _totals_of(doc)
    totals["active"] = len(doc["modules"])
    return {"ts": doc["ts"], "batches": doc["batches"],
            "modules": doc["modules"], "totals": totals}
