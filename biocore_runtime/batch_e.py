# -*- coding: utf-8 -*-
"""task-239 (batch E): the thirty-two miscellaneous / adapter modules.

Batch E of docs/COVERAGE-BATCHES.md is "杂项/适配": configuration, diagnostics
and platform surfaces. Nothing here takes part in the turn's calculation, so the
hook only *reads* and reports -- one diagnostic row per turn.

    row = apply_turn(state, phase, payload)      # turn_start / turn_end diagnostics
    row = diagnose(state, payload)               # read-only convenience alias

PLATFORM ISOLATION
This module never imports a host, never touches the network and never writes a
file. The modules that read host configuration, import astrbot or expose adapter
routes are listed in PLATFORM and reported as {"available": true,
"used": false, "reason": "platform_isolation"} -- the adapter owns them, the
core only knows they exist. Everything else is called through its pure entry
point (no astrbot import: core_mode and emotion_probe are isolated for that
reason).

Modules
  archive_queue  bio_appraisal  bio_config  bio_const  bio_daily  bio_emotion
  bio_emotion2  bio_goal  bio_noise  bio_physiology2  bio_snapshot  bio_state
  bio_util  core_bridge  core_client  core_commands  core_mode  delta_budget
  diag_trace  emotion_probe  extreme_scenarios  learning_probe  mind_wander
  noise_bank  pipeline_api  plugin_config  plugin_routes  provider_fallback
  schema  source_monitoring  stages  ui_settings
"""
from __future__ import annotations

import importlib
import json
import math
import time

SCHEMA = 1
SWITCH_KEY = "batch_e"
ENV_KEY = "BIOCORE_BATCH_E"
LEGEND_CHARS = 240
DIFF_LIMIT = 12

MODULES = ("archive_queue", "bio_appraisal", "bio_config", "bio_const",
           "bio_daily", "bio_emotion", "bio_emotion2", "bio_goal",
           "bio_noise", "bio_physiology2", "bio_snapshot", "bio_state",
           "bio_util", "core_bridge", "core_client", "core_commands",
           "core_mode", "delta_budget", "diag_trace", "emotion_probe",
           "extreme_scenarios", "learning_probe", "mind_wander", "noise_bank",
           "pipeline_api", "plugin_config", "plugin_routes",
           "provider_fallback", "schema", "source_monitoring", "stages",
           "ui_settings")

# Host / storage / route surfaces: the adapter owns them, the core only reports
# that they exist. Calling them here would break the platform isolation rule.
PLATFORM = ("archive_queue", "bio_config", "bio_daily", "bio_emotion",
            "bio_emotion2", "bio_goal", "bio_noise", "bio_physiology2",
            "bio_snapshot", "bio_state", "bio_util", "core_bridge",
            "core_client", "core_mode", "emotion_probe", "pipeline_api",
            "plugin_config", "plugin_routes", "ui_settings")

USE_EXCESS_LIMIT = 1.2


# ---------------------------------------------------------------- helpers
def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return default
    if not math.isfinite(number):
        return default
    return number


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


def _mod(name):
    for path in ("biocore_model." + name, "biocore_memory." + name):
        try:
            return importlib.import_module(path)
        except Exception:
            continue
    return None


def _call(name, fn, *args, **kwargs):
    module = _mod(name)
    if module is None or not callable(getattr(module, fn, None)):
        return {"enabled": False, "reason": "module_missing", "value": None}
    try:
        return {"enabled": True, "reason": "ok",
                "value": getattr(module, fn)(*args, **kwargs)}
    except Exception as error:
        return {"enabled": False, "reason": type(error).__name__, "value": None}


def _value(result, fallback=None):
    if not isinstance(result, dict) or not result.get("enabled"):
        return fallback
    return result.get("value", fallback)


def _flat(state):
    state = state if isinstance(state, dict) else {}
    core = state.get("core") if isinstance(state.get("core"), dict) else {}
    flat = dict(core)
    rel = state.get("relationship") if isinstance(state.get("relationship"), dict) else {}
    for key in ("trust", "closeness", "conflict"):
        if key in rel and key not in flat:
            flat[key] = rel[key]
    needs = state.get("needs") if isinstance(state.get("needs"), dict) else core.get("needs")
    if isinstance(needs, dict):
        flat["needs"] = dict(needs)
    return flat


# ---------------------------------------------------------------- diagnostics
def _read_diagnostics(payload, state, now):
    flat = _flat(state)
    snapshot = _value(_call("diag_trace", "state_snapshot", flat), {}) or {}
    before = payload.get("before")
    diff = {}
    if isinstance(before, dict):
        diff = _value(_call("diag_trace", "diff_state", before, flat), {}) or {}
    rows = _value(_call("diag_trace", "build", before=before, after=flat,
                        intent=payload.get("intent")), (None, []))
    trace_rows = []
    if isinstance(rows, tuple) and len(rows) == 2 and isinstance(rows[1], list):
        trace_rows = rows[1]
    elif isinstance(rows, list):
        trace_rows = rows
    deltas = payload.get("deltas") if isinstance(payload.get("deltas"), dict) else {}
    sanitized = _value(_call("delta_budget", "sanitize", deltas), {}) or {}
    total = _num(_value(_call("delta_budget", "total", deltas), 0.0), 0.0)
    budgeted = _value(_call("delta_budget", "budget", deltas,
                            _num(payload.get("delta_limit"), USE_EXCESS_LIMIT)),
                      None)
    report = {}
    if isinstance(budgeted, tuple) and len(budgeted) == 2:
        budgeted, report = budgeted
    budgeted = budgeted if isinstance(budgeted, dict) else {}
    report = report if isinstance(report, dict) else {}
    budget_total = _num(report.get("scaled_total"),
                        _num(_value(_call("delta_budget", "total", budgeted),
                                    0.0), 0.0))
    legend = _value(_call("schema", "numeric_legend", flat,
                          payload.get("baselines")), "") or ""
    minutes = int(_num(payload.get("hour"), -1))
    alertness = _value(_call("bio_const", "circadian_alertness",
                             minutes if minutes >= 0 else None), None)
    return {"enabled": True, "reason": "ok", "value": {
        "snapshot": snapshot if isinstance(snapshot, dict) else {},
        "diff": diff if isinstance(diff, dict) else {},
        "diff_count": len(diff) if isinstance(diff, dict) else 0,
        "trace_rows": len(trace_rows) if isinstance(trace_rows, list) else 0,
        "deltas": {"count": len(sanitized) if isinstance(sanitized, dict) else 0,
                   "total": round(total, 4), "budget_total": round(budget_total, 4),
                   "factor": round(_num(report.get("factor"), 1.0), 4),
                   "limited": bool(budget_total + 1e-9 < total)},
        "legend_chars": min(LEGEND_CHARS, len(str(legend or ""))),
        "alertness": (round(_num(alertness), 4)
                      if alertness is not None else None)}}


def _read_config(payload, state, now):
    parsed = _value(_call("core_commands", "parse_args",
                          str(payload.get("command") or "")), {}) or {}
    fallback = _value(_call("provider_fallback", "describe",
                            payload.get("provider_state") or {}), {}) or {}
    candidates = _value(_call("provider_fallback", "candidates",
                              payload.get("provider") or "primary",
                              payload.get("fallback_order"), now), []) or []
    stages = _value(_call("stages", "build_stages"), {}) or {}
    stage_names = sorted(stages.keys()) if isinstance(stages, dict) else []
    return {"enabled": True, "reason": "ok", "value": {
        "mode": str(payload.get("mode") or state.get("mode") or ""),
        "command": parsed if isinstance(parsed, dict) else {},
        "provider": fallback if isinstance(fallback, dict) else {},
        "candidate_count": len(candidates) if isinstance(candidates, list) else 0,
        "stages": stage_names}}


def _read_monitoring(payload, state, now):
    result = _value(_call("source_monitoring", "monitor",
                          payload.get("memory_meta"),
                          {"valence": _num(_flat(state).get("v"), 0.0)},
                          payload.get("flags")), {}) or {}
    readout = _value(_call("source_monitoring", "readout", result), {}) or {}
    wander = _value(_call("mind_wander", "seeded",
                          payload.get("wander_seed") or str(payload.get("session_id") or "s1"),
                          int(_num(payload.get("wander_tick"), 0))), None)
    noise = _value(_call("noise_bank", "sample_window",
                         payload.get("noise_seed") or "s1", 0,
                         int(_num(payload.get("noise_count"), 4)),
                         str(payload.get("noise_channel") or "")), []) or []
    noise = [round(_num(item), 4) for item in noise] if isinstance(noise, list) else []
    return {"enabled": True, "reason": "ok", "value": {
        "source": readout if isinstance(readout, dict) else {},
        "wander": wander,
        "noise": noise,
        "noise_max": round(max([abs(x) for x in noise] or [0.0]), 4)}}


def _read_probe(payload, state, now):
    learning = _value(_call("learning_probe", "self_check"), {}) or {}
    scenarios = _value(_call("extreme_scenarios", "run_all"), {}) or {}
    rows = scenarios.get("scenarios") if isinstance(scenarios, dict) else scenarios
    names = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict):
            names.append(str(row.get("scenario") or row.get("name") or ""))
    if isinstance(scenarios, dict):
        names = [name for name in names if name]
    return {"enabled": True, "reason": "ok", "value": {
        "learning": learning if isinstance(learning, dict) else {},
        "scenarios": names}}


# ---------------------------------------------------------------- entry
def apply_turn(state, phase, payload=None, now=None, enabled_override=None):
    data = payload if isinstance(payload, dict) else {}
    session_state = state if isinstance(state, dict) else {}
    stamp = round(_num(now if now is not None else data.get("now"), time.time()), 3)
    phase = str(phase or "").strip().lower()
    result = {"schema": SCHEMA, "enabled": False, "phase": phase, "ts": stamp,
              "modules": {name: False for name in MODULES},
              "activity": {name: False for name in MODULES},
              "reads": {}, "state_deltas": {}, "skipped": [],
              "platform": {name: {"available": _mod(name) is not None,
                                  "used": False,
                                  "reason": "platform_isolation"}
                           for name in PLATFORM},
              "isolation": {"network": False, "host_imports": False,
                            "filesystem": False},
              "counts": {"modules": len(MODULES), "available": 0,
                         "active": 0, "platform": len(PLATFORM)}}
    if phase not in ("turn_start", "turn_end"):
        result["reason"] = "bad_phase"
        return result
    on = (enabled_override if isinstance(enabled_override, bool)
          else enabled(data))
    if not on:
        result["reason"] = "disabled"
        return result
    result["enabled"] = True
    result["reason"] = "ok"

    diagnostics = _read_diagnostics(data, session_state, stamp)
    config = _read_config(data, session_state, stamp)
    monitoring = _read_monitoring(data, session_state, stamp)
    probe = _read_probe(data, session_state, stamp)
    result["reads"] = {
        "diagnostics": diagnostics.get("value"),
        "config": config.get("value"),
        "monitoring": monitoring.get("value"),
        "probe": probe.get("value")}
    for name, read in (("diag_trace", diagnostics), ("delta_budget", diagnostics),
                       ("schema", diagnostics), ("bio_const", diagnostics),
                       ("core_commands", config), ("provider_fallback", config),
                       ("stages", config), ("source_monitoring", monitoring),
                       ("mind_wander", monitoring), ("noise_bank", monitoring),
                       ("learning_probe", probe), ("extreme_scenarios", probe)):
        result["activity"][name] = bool(read.get("enabled"))
        if not read.get("enabled"):
            result["skipped"].append({"module": name,
                                      "reason": read.get("reason")})
    for name in PLATFORM:
        result["skipped"].append({"module": name, "reason": "platform_isolation"})
    result["state_deltas"]["diagnostics"] = (
        diagnostics.get("value") or {}).get("snapshot") or {}
    result["state_deltas"]["diagnostic_row"] = {
        "phase": phase, "ts": stamp,
        "diff_count": (diagnostics.get("value") or {}).get("diff_count", 0),
        "budget_limited": (diagnostics.get("value") or {}).get("deltas", {}).get(
            "limited", False),
        "mode": (config.get("value") or {}).get("mode", ""),
        "alertness": (diagnostics.get("value") or {}).get("alertness")}
    result["modules"] = {name: _mod(name) is not None for name in MODULES}
    result["counts"] = {"modules": len(MODULES),
                        "available": sum(1 for flag in result["modules"].values()
                                         if flag),
                        "active": sum(1 for flag in result["activity"].values()
                                      if flag),
                        "platform": len(PLATFORM)}
    return result


def diagnose(state, payload=None, now=None):
    """Read-only convenience: the turn_start diagnostics row."""
    return apply_turn(state, "turn_start", payload, now=now)


# ---------------------------------------------------------------- CLI
def main(argv=None):  # pragma: no cover - manual debugging only
    import sys
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    payload = json.loads(raw) if raw.strip() else {}
    state = payload.pop("state", {})
    phase = payload.pop("phase", "turn_start")
    print(json.dumps(apply_turn(state, phase, payload),
                     ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
