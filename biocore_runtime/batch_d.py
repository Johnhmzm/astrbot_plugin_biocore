# -*- coding: utf-8 -*-
"""task-238 (batch D): the twenty-nine motivation / expression modules.

Batch D of docs/COVERAGE-BATCHES.md is "动机/表达". One hook, two entry points,
no IO, no import from pipeline.py or engine.py -- the Lead wires it in later.

    deltas = apply_turn(state, phase, payload)   # turn_start / turn_end
    extra  = prompt_extra(state, payload)        # material for prompt_block

BOUNDARY
The biological layer never assembles an LLM prompt. These modules are allowed
to *decide* (intent, tone, length, initiative, avoid-list) and to produce short
bounded hints; prompt_extra hands that material to the interpretation layer,
which is the only place that turns it into prompt text. Nothing here renders a
final prompt, and proactive sending stays OFF unless the caller explicitly asks
for it (payload["proactive_allowed"] is True).

Modules
  autonomy_affect  autonomy_check  autonomy_loop  autonomy_mode  autonomy_model
  autonomy_params  autonomy_reason  bio_autonomy_state  exit_or_silence
  expr_guard  expr_intent  expr_state  expr_template  expr_tone
  feedback_flow  feedback_guard  feedback_llm  feedback_user  granularity
  intent_render  proactive_context  prompt_rules  reply_limit  reply_split
  scheduler  state_tag  template_expr  topic_control  voice_bank

Return of apply_turn
  {"enabled","phase","ts","modules","activity","reads","field_deltas",
   "state_deltas","skipped","counts","proactive_allowed"}

Return of prompt_extra
  {"enabled","tone","length","initiative","avoid","hints","budget_chars",
   "proactive_allowed","sources"}
"""
from __future__ import annotations

import collections
import importlib
import json
import math
import time

SCHEMA = 1
SWITCH_KEY = "batch_d"
ENV_KEY = "BIOCORE_BATCH_D"
HINT_LIMIT = 6
HINT_CHARS = 120
BUDGET_CHARS = 320

MODULES = ("autonomy_affect", "autonomy_check", "autonomy_loop",
           "autonomy_mode", "autonomy_model", "autonomy_params",
           "autonomy_reason", "bio_autonomy_state", "exit_or_silence",
           "expr_guard", "expr_intent", "expr_state", "expr_template",
           "expr_tone", "feedback_flow", "feedback_guard", "feedback_llm",
           "feedback_user", "granularity", "intent_render",
           "proactive_context", "prompt_rules", "reply_limit", "reply_split",
           "scheduler", "state_tag", "template_expr", "topic_control",
           "voice_bank")

CAPS = {"v": 0.10, "a": 0.10, "stress": 0.08, "social": 0.08,
        "trust": 0.02, "closeness": 0.02}
DEFAULT_LENGTH = {"target": 10, "max_chars": 30}


# ---------------------------------------------------------------- helpers
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


def _clip_text(text, limit=HINT_CHARS):
    row = " ".join(str(text or "").split())
    return row[:limit]


# feedback_flow keeps its idempotency buckets keyed by id(core). A fresh dict
# per turn would let CPython recycle an id and look like a retry, so the cores
# handed to it are retained (bounded) until the process forgets them.
_CORE_KEEP = collections.deque(maxlen=64)


def _retain(core):
    _CORE_KEEP.append(core)
    return core


def _hint(source, text):
    body = _clip_text(text)
    if not body:
        return None
    return {"source": source, "text": body, "chars": len(body)}


# ---------------------------------------------------------------- autonomy
def _read_autonomy(payload, state, now):
    """autonomy_params -> model parts -> compute -> check / mode / reason."""
    flat = _flat(state)
    profile = payload.get("persona_profile")
    profile = profile.get("fields") if isinstance(profile, dict) and isinstance(
        profile.get("fields"), dict) else (profile if isinstance(profile, dict) else {})
    relationship = state.get("relationship") if isinstance(
        state.get("relationship"), dict) else {}
    params = _value(_call("autonomy_params", "from_profile", profile,
                          relationship,
                          _num(payload.get("responsiveness"), 0.5),
                          _num(payload.get("ignore_rate"), 0.0)), {}) or {}
    acc = state.get("autonomy_acc") if isinstance(state.get("autonomy_acc"), dict) else {}
    parts = _value(_call("autonomy_model", "parts_from_state", flat, relationship,
                         now, acc, params or None), {}) or {}
    threshold = _num(params.get("theta"), _num(parts.get("theta"), 0.6))
    drive = _value(_call("autonomy_model", "compute", parts, threshold,
                         _clamp(relationship.get("closeness", 0.5), 0.0, 1.0),
                         None, int(_num(parts.get("unanswered"), 0)), False,
                         bool(payload.get("recent_user_active", False))), {}) or {}
    check = _value(_call("autonomy_check", "snapshot", state), {}) or {}
    reason = _value(_call("autonomy_check", "reason", state), "") or ""
    mode_profile = _value(_call("autonomy_mode", "normalize",
                               payload.get("autonomy_mode")
                               or state.get("autonomy_mode") or "drive"), "drive")
    if isinstance(mode_profile, dict):
        mode = str(mode_profile.get("mode") or mode_profile.get("name")
                   or mode_profile.get("label") or "drive")
    else:
        mode = str(mode_profile or "drive")
    reasons = _value(_call("autonomy_reason", "extract", parts,
                           str(payload.get("memory_title") or ""),
                           _num(payload.get("memory_due"), 0.0)), []) or []
    rate = _value(_call("autonomy_loop", "response_rate", acc), 0.0) or 0.0
    loop = _value(_call("autonomy_loop", "loop_view", acc), {}) or {}
    return {"enabled": True, "reason": "ok", "value": {
        "parts": parts, "drive": drive, "check": check,
        "reason": str(reason)[:32], "reasons": reasons if isinstance(reasons, list) else [],
        "mode": str(mode), "response_rate": round(_num(rate), 4),
        "loop": loop if isinstance(loop, dict) else {},
        "theta": round(threshold, 4)}}


class _Core(object):
    """autonomy_affect.apply mutates attributes, so give it a real object."""

    def __init__(self, values):
        data = values if isinstance(values, dict) else {}
        for key in ("v", "a", "stress", "energy", "social", "confidence"):
            setattr(self, key, _num(data.get(key), 0.0 if key != "a" else 0.5))
        self.confidence = _clamp(self.confidence, 0.0, 1.0)


def _write_autonomy(payload, state, now):
    """autonomy_affect.apply + autonomy_loop accounting."""
    flat = _flat(state)
    core = _Core(flat)
    acc = state.get("autonomy_acc") if isinstance(state.get("autonomy_acc"), dict) else {}
    silence_hours = _num(payload.get("silence_hours"), 0.0)
    applied = _value(_call("autonomy_affect", "apply", core, acc, now,
                           silence_hours, _num(payload.get("phase_weight"), 0.0),
                           _num(payload.get("self_blame"), 0.0)), None)
    deltas = {}
    if isinstance(applied, tuple) and len(applied) == 2:
        raw, acc = applied
        raw = raw if isinstance(raw, dict) else {}
        # valence/arousal -> v/a, lonely stays out of the six-field vocabulary
        for source, name in (("valence", "v"), ("arousal", "a"),
                             ("stress", "stress")):
            value = _num(raw.get(source), 0.0)
            if abs(value) > 1e-6:
                deltas[name] = value
    decided = payload.get("autonomy_decision")
    loop = None
    if isinstance(decided, dict):
        loop = _value(_call("autonomy_loop", "record_attempt", acc, now,
                            str(decided.get("code") or ""),
                            _num(decided.get("weight"), 0.0),
                            int(_num(payload.get("reply_chars"), 0))), None)
    replied = payload.get("user_replied")
    if replied is not None:
        loop = _value(_call("autonomy_loop", "on_user_reply", loop or acc, now,
                            bool(replied)), loop)
    return {"enabled": True, "reason": "ok", "value": {
        "deltas": {key: round(_num(value), 6) for key, value in deltas.items()
                   if key in CAPS},
        "acc": loop if isinstance(loop, dict) else acc,
        "silence_hours": round(silence_hours, 3)}}


# ---------------------------------------------------------------- expression
def _read_expression(payload, state, now):
    """intent / tone / granularity / exit-or-silence / reply limits."""
    flat = _flat(state)
    emotion = payload.get("emotion")
    candidates = payload.get("intents")
    if not isinstance(candidates, list) or not candidates:
        # expr_intent.BASE kinds; novelty 1.0 passes its own validity gate
        candidates = [{"kind": "comfort", "weight": 0.6, "novelty": 1.0},
                      {"kind": "share_mood", "weight": 0.4, "novelty": 1.0}]
    picked = _value(_call("expr_intent", "pick_intent", candidates, flat), None)
    intent = (str(picked.get("kind") or "") if isinstance(picked, dict)
              else str(picked or ""))
    tendency = _value(_call("intent_render", "tendency", intent), "") or ""
    tone = _value(_call("expr_tone", "tone_block", tendency or "reply", emotion,
                        _clamp(payload.get("intensity", abs(_num(flat.get("v")))),
                               0.0, 1.0),
                        _clamp(flat.get("self_esteem", 0.6), 0.0, 1.0),
                        payload.get("regulation")), {}) or {}
    granularity = _value(_call("granularity", "from_state", flat,
                               payload.get("granularity_context")), {}) or {}
    exit_result = _value(_call("exit_or_silence", "exit_or_silence", flat,
                              state.get("relationship"), payload.get("topic")), {}) or {}
    should = _value(_call("exit_or_silence", "should_reply", exit_result), True)
    token_body = payload.get("reply_limit")
    limits = (_value(_call("reply_limit", "normalize", token_body), {}) or {}
              if isinstance(token_body, dict) and "max_tokens" in token_body
              else {})
    config_limits = _value(_call("reply_limit", "read_from_config",
                                 payload.get("plugin_config") or {}), {}) or {}
    char_limits = {"target": int(_num(payload.get("length_target"), 10)),
                   "max_chars": int(_num(payload.get("length_max"), 30))}
    split_cfg = _value(_call("reply_split", "effective", payload.get("plugin")), {}) or {}
    state_block = _value(_call("expr_state", "render_state_block", flat,
                               state.get("relationship"), now,
                               int(_num(payload.get("state_block_budget"), 600))), "")
    if isinstance(state_block, dict):
        state_block = state_block.get("text") or ""
    rules = _value(_call("prompt_rules", "render_length_rule",
                         int(_num(limits.get("target"), DEFAULT_LENGTH["target"])),
                         int(_num(limits.get("max_chars"), DEFAULT_LENGTH["max_chars"]))), "")
    return {"enabled": True, "reason": "ok", "value": {
        "intent": str(intent), "tendency": str(tendency),
        "tone": tone if isinstance(tone, dict) else {"label": str(tone or "")},
        "granularity": granularity if isinstance(granularity, dict) else {},
        "exit": exit_result if isinstance(exit_result, dict) else {},
        "should_reply": bool(should),
        "limits": dict(limits if isinstance(limits, dict) else {},
                       **char_limits),
        "config_limits": config_limits if isinstance(config_limits, dict) else {},
        "split": split_cfg if isinstance(split_cfg, dict) else {},
        "state_block_chars": len(str(state_block or "")),
        "length_rule_chars": len(str(rules or ""))}}


def _write_expression(payload, state, now):
    """state_tag / reply_split / expr_guard / templates / topic control."""
    text = str(payload.get("assistant_text") or "")
    parsed = _value(_call("state_tag", "parse", text), {}) or {}
    visible = _value(_call("state_tag", "strip", text), text) or text
    block = _value(_call("expr_guard", "guard_block"), []) or []
    hits = []
    if isinstance(block, list):
        for word in block:
            token = str(word or "")
            if token and token in visible:
                hits.append(token)
    segments = _value(_call("reply_split", "split_reply", visible,
                            payload.get("split_config")), []) or []
    segments = [row for row in segments if isinstance(row, str)] if isinstance(
        segments, list) else []
    template = payload.get("reply_template")
    rendered = ""
    if isinstance(template, str) and template:
        rendered = str(_value(_call("template_expr", "render", template,
                                    payload.get("template_vars")), template) or "")
    turns = payload.get("recent_turns") if isinstance(payload.get("recent_turns"), list) else []
    topic = _value(_call("topic_control", "topic_control", turns, _flat(state),
                         state.get("relationship"), payload.get("hour")), {}) or {}
    directives = _value(_call("topic_control", "directives", topic), {}) or {}
    token_body = payload.get("reply_limit")
    token_limit = (_value(_call("reply_limit", "normalize", token_body), {}) or {}
                   if isinstance(token_body, dict) and "max_tokens" in token_body
                   else {})
    limits = dict(token_limit if isinstance(token_limit, dict) else {})
    limits.update({"target": int(_num(payload.get("length_target"), 10)),
                   "max_chars": int(_num(payload.get("length_max"), 30))})
    return {"enabled": True, "reason": "ok", "value": {
        "tag": parsed if isinstance(parsed, dict) else {},
        "limits": limits,
        "visible_chars": len(str(visible or "")),
        "guard_block_hits": hits[:8],
        "segments": len(segments),
        "segment_chars": [len(row) for row in segments[:4]],
        "template_chars": len(rendered),
        "topic": {"result": topic if isinstance(topic, dict) else {},
                  "avoid": directives.get("avoid") if isinstance(directives, dict) else [],
                  "hint_chars": len(str((directives or {}).get("hint") or ""))
                  if isinstance(directives, dict) else 0}}}


# ---------------------------------------------------------------- feedback
def _read_feedback(payload, state, now):
    limits = _value(_call("feedback_guard", "limits_for", "llm"), {}) or {}
    return {"enabled": True, "reason": "ok", "value": {
        "limits": limits if isinstance(limits, dict) else {},
        "seen": bool(state.get("feedback_seen"))}}


def _write_feedback(payload, state, now):
    core = _retain(_flat(state))
    summary = _value(_call("feedback_flow", "apply_llm",
                           payload.get("llm_feedback") or {}, core, now), {}) or {}
    deltas = summary.get("deltas") if isinstance(summary, dict) else {}
    deltas = deltas if isinstance(deltas, dict) else {}
    rejected = summary.get("rejected") if isinstance(summary, dict) else []
    parsed = _value(_call("feedback_llm", "parse_to_deltas",
                          payload.get("llm_feedback") or {}, None, core, now), {}) or {}
    user_meta = payload.get("user_meta") or {"responded": bool(payload.get("responded"))}
    user_summary = _value(_call("feedback_flow", "apply_user", user_meta, core, now), {}) or {}
    user_state = _value(_call("feedback_user", "on_message", core, user_meta, now), {}) or {}
    vet = _value(_call("feedback_guard", "vet", deltas, core, "llm", now), {}) or {}
    return {"enabled": True, "reason": "ok", "value": {
        "llm": summary if isinstance(summary, dict) else {},
        "parsed": parsed if isinstance(parsed, dict) else {},
        "user": user_summary if isinstance(user_summary, dict) else {},
        "user_state": user_state if isinstance(user_state, dict) else {},
        "vet": vet if isinstance(vet, dict) else {},
        "deltas": {key: round(_num(value), 6) for key, value in deltas.items()
                   if key in CAPS},
        "rejected": len(rejected) if isinstance(rejected, list) else 0}}


# ---------------------------------------------------------------- schedule
def _read_schedule(payload, state, now):
    items = payload.get("schedule_items")
    items = items if isinstance(items, list) else []
    due = _value(_call("scheduler", "due", items, now,
                       _num(payload.get("due_window"), 3600.0)), []) or []
    pick = _value(_call("scheduler", "pick", items, now), None)
    voice = _value(_call("voice_bank", "available",
                         payload.get("voice_entries") or [],
                         _flat(state), state.get("relationship"),
                         payload.get("recent_voice") or [], now), []) or []
    return {"enabled": True, "reason": "ok", "value": {
        "due": len(due) if isinstance(due, list) else 0,
        "pick": pick if isinstance(pick, dict) else None,
        "voice_available": len(voice) if isinstance(voice, list) else 0}}


# ---------------------------------------------------------------- entry
def apply_turn(state, phase, payload=None, now=None, enabled_override=None):
    data = payload if isinstance(payload, dict) else {}
    session_state = state if isinstance(state, dict) else {}
    stamp = round(_num(now if now is not None else data.get("now"), time.time()), 3)
    phase = str(phase or "").strip().lower()
    result = {"schema": SCHEMA, "enabled": False, "phase": phase, "ts": stamp,
              "modules": {name: False for name in MODULES},
              "activity": {name: False for name in MODULES},
              "reads": {}, "field_deltas": {}, "state_deltas": {},
              "skipped": [], "proactive_allowed": False,
              "counts": {"modules": len(MODULES), "available": 0, "active": 0}}
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
    if not isinstance(data.get("now"), (int, float)):
        data = dict(data, now=stamp)

    skipped = result["skipped"]
    if phase == "turn_start":
        autonomy = _read_autonomy(data, session_state, stamp)
        expression = _read_expression(data, session_state, stamp)
        feedback = _read_feedback(data, session_state, stamp)
        schedule = _read_schedule(data, session_state, stamp)
        result["reads"] = {
            "autonomy": autonomy.get("value"),
            "expression": expression.get("value"),
            "feedback": feedback.get("value"),
            "schedule": schedule.get("value"),
        }
        for name, read in (("autonomy_params", autonomy),
                           ("autonomy_model", autonomy),
                           ("autonomy_check", autonomy),
                           ("autonomy_reason", autonomy),
                           ("autonomy_loop", autonomy),
                           ("autonomy_mode", autonomy),
                           ("expr_intent", expression),
                           ("expr_tone", expression),
                           ("granularity", expression),
                           ("exit_or_silence", expression),
                           ("reply_limit", expression),
                           ("reply_split", expression),
                           ("expr_state", expression),
                           ("prompt_rules", expression),
                           ("feedback_guard", feedback),
                           ("scheduler", schedule),
                           ("voice_bank", schedule)):
            result["activity"][name] = bool(read.get("enabled"))
            if not read.get("enabled"):
                skipped.append({"module": name, "reason": read.get("reason")})
        if isinstance(expression.get("value"), dict):
            value = expression["value"]
            result["state_deltas"]["expression"] = {
                "intent": value.get("intent"),
                "tendency": value.get("tendency"),
                "tone": value.get("tone"),
                "should_reply": value.get("should_reply"),
                "limits": value.get("limits")}
            if value.get("should_reply") is False:
                result["state_deltas"]["silence"] = {"reason": "exit_or_silence",
                                                     "ts": stamp}
        if isinstance(autonomy.get("value"), dict):
            result["state_deltas"]["autonomy"] = {
                "mode": autonomy["value"].get("mode"),
                "reason": autonomy["value"].get("reason"),
                "drive": autonomy["value"].get("drive"),
                "theta": autonomy["value"].get("theta"),
                "response_rate": autonomy["value"].get("response_rate")}
        result["proactive_allowed"] = bool(data.get("proactive_allowed") is True
                                           and data.get("proactive_send") is True)

    if phase == "turn_end":
        autonomy = _write_autonomy(data, session_state, stamp)
        expression = _write_expression(data, session_state, stamp)
        feedback = _write_feedback(data, session_state, stamp)
        schedule = _read_schedule(data, session_state, stamp)
        result["reads"] = {
            "autonomy": autonomy.get("value"),
            "expression": expression.get("value"),
            "feedback": feedback.get("value"),
            "schedule": schedule.get("value"),
        }
        for name in ("autonomy_affect", "autonomy_loop", "state_tag",
                     "reply_split", "expr_guard", "template_expr",
                     "topic_control", "feedback_llm", "feedback_flow",
                     "feedback_user"):
            result["activity"][name] = bool(
                (autonomy if name.startswith("autonomy") else expression
                 if name in ("state_tag", "reply_split", "expr_guard",
                             "template_expr", "topic_control") else feedback
                 ).get("enabled"))
        result["activity"]["scheduler"] = bool(schedule.get("enabled"))
        result["activity"]["voice_bank"] = bool(schedule.get("enabled"))
        for name, read in (("autonomy_affect", autonomy),
                           ("autonomy_loop", autonomy),
                           ("state_tag", expression),
                           ("reply_split", expression),
                           ("expr_guard", expression),
                           ("topic_control", expression),
                           ("feedback_llm", feedback),
                           ("feedback_flow", feedback),
                           ("feedback_user", feedback)):
            if not read.get("enabled"):
                skipped.append({"module": name, "reason": read.get("reason")})
        auto_value = autonomy.get("value") or {}
        for name, delta in (auto_value.get("deltas") or {}).items():
            if name in CAPS and abs(_num(delta)) > 1e-6:
                result["field_deltas"][name] = round(
                    _clamp(delta, -CAPS[name], CAPS[name]), 6)
        if isinstance(auto_value.get("acc"), dict):
            result["state_deltas"]["autonomy_acc"] = auto_value["acc"]
        expression_value = expression.get("value") or {}
        if isinstance(expression_value.get("tag"), dict) and expression_value["tag"]:
            result["state_deltas"]["state_tag"] = expression_value["tag"]
        if isinstance(expression_value.get("topic"), dict):
            result["state_deltas"]["topic_control"] = expression_value["topic"]
        result["state_deltas"]["reply"] = {
            "chars": int(_num(expression_value.get("visible_chars"), 0)),
            "segments": int(_num(expression_value.get("segments"), 0)),
            "guard_hits": list(expression_value.get("guard_block_hits") or []),
            "template_chars": int(_num(expression_value.get("template_chars"), 0))}
        feedback_value = feedback.get("value") or {}
        if isinstance(feedback_value.get("deltas"), dict) and feedback_value["deltas"]:
            # feedback owns its own bounded deltas; keep them as proposals too
            for name, delta in feedback_value["deltas"].items():
                if name in CAPS and name not in result["field_deltas"]:
                    result["field_deltas"][name] = round(
                        _clamp(delta, -CAPS[name], CAPS[name]), 6)
        if isinstance(feedback_value.get("user_state"), dict) and feedback_value["user_state"]:
            result["state_deltas"]["feedback"] = {
                "llm_rejected": feedback_value.get("rejected", 0),
                "user": feedback_value.get("user_state")}

    result["modules"] = {name: _mod(name) is not None for name in MODULES}
    result["counts"] = {"modules": len(MODULES),
                        "available": sum(1 for flag in result["modules"].values()
                                         if flag),
                        "active": sum(1 for flag in result["activity"].values()
                                      if flag)}
    return result


# ---------------------------------------------------------------- prompt seam
def prompt_extra(state, payload=None):
    """Bounded material for prompt_block (the interpretation layer renders it).

    Never a prompt: a tone objective, a length target, an initiative number, an
    avoid-list and at most HINT_LIMIT short hints inside BUDGET_CHARS.
    """
    data = payload if isinstance(payload, dict) else {}
    session_state = state if isinstance(state, dict) else {}
    result = {"schema": SCHEMA, "enabled": False, "tone": {},
              "length": dict(DEFAULT_LENGTH), "initiative": 0.5,
              "avoid": [], "hints": [], "budget_chars": BUDGET_CHARS,
              "proactive_allowed": False, "sources": []}
    if not enabled(data):
        result["reason"] = "disabled"
        return result
    result["enabled"] = True
    result["reason"] = "ok"
    flat = _flat(session_state)
    now = _num(data.get("now"), time.time())

    tendency = str(data.get("tendency") or "reply")
    tone = _value(_call("expr_tone", "tone_block", tendency, data.get("emotion"),
                        _clamp(data.get("intensity", abs(_num(flat.get("v")))),
                               0.0, 1.0),
                        _clamp(flat.get("self_esteem", 0.6), 0.0, 1.0),
                        data.get("regulation")), {}) or {}
    result["tone"] = tone if isinstance(tone, dict) else {"label": str(tone or "")}
    result["sources"].append("expr_tone")

    result["length"] = {"target": int(_num(data.get("length_target"),
                                            DEFAULT_LENGTH["target"])),
                        "max_chars": int(_num(data.get("length_max"),
                                              DEFAULT_LENGTH["max_chars"]))}
    token_limit = _value(_call("reply_limit", "read_from_config",
                               data.get("plugin_config") or {}), {}) or {}
    if isinstance(token_limit, dict) and token_limit.get("max_tokens"):
        result["length"]["max_tokens"] = int(_num(token_limit.get("max_tokens"), 0))
    result["sources"].append("reply_limit")

    hints = []
    block = _value(_call("expr_state", "render_state_block", flat,
                         session_state.get("relationship"), now,
                         int(_num(data.get("state_block_budget"), 160))), "")
    if isinstance(block, dict):
        block = block.get("text") or ""
    if block:
        hints.append(_hint("expr_state", block))
    rules = _value(_call("prompt_rules", "render_length_rule",
                         int(result["length"]["target"]),
                         int(result["length"]["max_chars"])), "")
    if rules:
        hints.append(_hint("prompt_rules", rules))
    exit_result = _value(_call("exit_or_silence", "exit_or_silence", flat,
                              session_state.get("relationship"),
                              data.get("topic")), {}) or {}
    exit_directives = _value(_call("exit_or_silence", "directives",
                                   exit_result), {}) or {}
    if isinstance(exit_directives, dict):
        if exit_directives.get("tone"):
            hints.append(_hint("exit_or_silence", exit_directives["tone"]))
        result["initiative"] = round(_clamp(
            _num(exit_directives.get("initiative"), 0.5), 0.0, 1.0), 4)
        result["sources"].append("exit_or_silence")
    turns = data.get("recent_turns") if isinstance(data.get("recent_turns"), list) else []
    topic = _value(_call("topic_control", "topic_control", turns, flat,
                         session_state.get("relationship"), data.get("hour")), {}) or {}
    topic_directives = _value(_call("topic_control", "directives", topic), {}) or {}
    if isinstance(topic_directives, dict):
        avoid = topic_directives.get("avoid")
        result["avoid"] = [str(item) for item in avoid][:6] if isinstance(
            avoid, list) else []
        if topic_directives.get("hint"):
            hints.append(_hint("topic_control", topic_directives["hint"]))
        result["sources"].append("topic_control")
    # gap_text takes HOURS; the payload speaks seconds
    proactive = _value(_call("proactive_context", "gap_text",
                             _num(data.get("gap_seconds"), 0.0) / 3600.0), "")
    if proactive:
        hints.append(_hint("proactive_context", proactive))

    hints = [row for row in hints if row]
    result["hints"] = hints[:HINT_LIMIT]
    result["proactive_allowed"] = bool(data.get("proactive_allowed") is True
                                       and data.get("proactive_send") is True)
    return result


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
