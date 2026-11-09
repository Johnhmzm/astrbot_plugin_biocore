# -*- coding: utf-8 -*-
"""task-234 (batch A1): the 12 perception/appraisal modules wired into one turn.

Batch A of docs/COVERAGE-BATCHES.md is "感知/评估". This module owns the first
twelve of them and nothing else:

    affective_labor  appraisal  appraisal_action  attachment_behavior
    attachment_regulation  attachment_state  attribution  autonomic
    compassion_fatigue  criticality  defense_mechanisms  emotion_geometry

One switch turns the whole batch on or off: "perception_batch"
(env BIOCORE_PERCEPTION_BATCH). It is ON by default; with it off nothing here
runs -- no module call, no sidecar file, no /state key, no writeback -- and the
turn behaves exactly like it did before this module existed.

Turn shape
----------
turn_start  snapshot(): read only. Takes the session state + relationship and
            produces one deterministic snapshot: affect (the six coupled
            values), emotion (label/probs), appraisal (dims -> bounded deltas),
            attachment (style/activation/mode/regulation), needs (four needs +
            behavioural bias), plus the small reads of labor, empathy, defense,
            attribution, criticality and the autonomic rhythm.
turn_end    writeback(): the only writer. Appraisal dims become bounded deltas
            and land in three places:
              * the six coupled fields (v/a/stress/social/trust) are returned as
                PROPOSALS for biocore_runtime.arbiter -- one write path, one cap
                per turn (task-228); d / self_esteem are applied here because
                they are outside the field;
              * needs: appraisal.needs_deltas + needs_events events, capped;
              * attachment: threat / decay on the activation, capped.
            Replaying the same turn is a no-op (idempotent per timestamp).

Every module call is guarded: a missing or broken module reports
{"enabled": false, "reason": ...} and the turn continues. No LLM, no network,
one sidecar file (<dataDir>/perception.json, latest + short history).
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import time
from pathlib import Path

import biocore_model as _bm

try:  # the 12-axis model (conflict lives there, not in the field)
    from . import dimensions as _dimensions
except Exception:  # pragma: no cover
    try:
        from biocore_runtime import dimensions as _dimensions
    except Exception:
        _dimensions = None

SCHEMA = 1
PERCEPTION_FILE = "perception.json"
HISTORY_LIMIT = 30
SWITCH_KEY = "perception_batch"
ENV_KEY = "BIOCORE_PERCEPTION_BATCH"

# Batch A of docs/COVERAGE-BATCHES.md, in the order the doc lists it.
MODULES_A1 = ("affective_labor", "appraisal", "appraisal_action",
              "attachment_behavior", "attachment_regulation",
              "attachment_state", "attribution", "autonomic",
              "compassion_fatigue", "criticality", "defense_mechanisms",
              "emotion_geometry")
MODULES_A2 = ("envy", "frustration_curve", "needs_esteem", "needs_events",
              "needs_sleep", "regulation_loop", "regulation_strategies",
              "situation", "sleep_circadian", "social_theory",
              "waiting_sense")
MODULES = MODULES_A1 + MODULES_A2

# The six coupled values are owned by biocore_runtime.field / .arbiter; these
# are the two appraisal outputs that live outside the field.
OWN_CAPS = {"d": 0.10, "self_esteem": 0.05}
FIELD_CAPS = {"v": 0.10, "a": 0.10, "stress": 0.08, "social": 0.08,
              "trust": 0.02}
NEED_CAPS = {"belonging": 0.05, "self_esteem": 0.05, "control": 0.05,
             "meaningful_existence": 0.04}
NEED_DEFAULT = 0.6
SELF_ESTEEM_BASE = 0.55
ATTACH_CAP = 0.15
# Share of the negative pressure a chosen regulation strategy can absorb.
# Gross 1998, JPSP 74(1):224-237: antecedent-focused reappraisal works through
# the meaning of the event and absorbs more; response-focused suppression only
# covers the expression and absorbs less. The remaining strategies stay at the
# old 0.5 [engineering].
REG_ABSORB = 0.5
REG_ABSORB_BY_STRATEGY = {"cognitive_reappraisal": 0.6,
                          "response_modulation": 0.3}
# One damping factor used to hit EVERY dimension, which quietly acted like a
# global regulator. Gross 1998 says the strategies differ in what they touch:
# reappraisal works on the meaning (valence/stress), suppression covers the
# expression (arousal/stress) and barely reaches valence or trust. The table is
# strategy x dimension; the numbers are [engineering], the direction is the
# paper's.
REG_DIM_GAIN = {
    "cognitive_reappraisal": {"v": 1.0, "a": 0.8, "stress": 1.0,
                              "social": 0.5, "trust": 0.3},
    "response_modulation": {"v": 0.3, "a": 1.0, "stress": 0.7,
                            "social": 0.2, "trust": 0.2},
}
REG_DIM_DEFAULT = 0.5      # [engineering] dimensions a strategy never names
NEUTRAL_DIMS = {"goal": 0.0, "blame": 0.0, "control": 0.5, "certainty": 0.5,
                "novelty": 0.0, "involve": 0.5, "hit": 0.0}


# ---------------------------------------------------------------- helpers
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


def enabled(overrides=None, store=None, env=None):
    """Explicit payload > flags.json > core_config switches > env > default ON.

    The pipeline passes its already-merged switch table, so the usual entry is
    enabled(overrides={"perception_batch": bool}).
    """
    data = overrides if isinstance(overrides, dict) else {}
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    for source in (data, switches):
        if isinstance(source.get(SWITCH_KEY), bool):
            return source[SWITCH_KEY]
    root = _data_dir(store)
    if root is not None:
        for candidate in (root / "flags.json", root.parent / "flags.json"):
            flags = _read(candidate)
            if isinstance(flags.get(SWITCH_KEY), bool):
                return flags[SWITCH_KEY]
        config = _read(root / "core_config.json")
        cfg_switches = config.get("switches") if isinstance(
            config.get("switches"), dict) else {}
        if isinstance(cfg_switches.get(SWITCH_KEY), bool):
            return cfg_switches[SWITCH_KEY]
    environ = env if hasattr(env, "get") else None
    if environ is not None and ENV_KEY in environ:
        return _truthy(environ.get(ENV_KEY), True)
    return True


# ---------------------------------------------------------------- module access
def _mod(name):
    module = getattr(_bm, name, None)
    if module is not None:
        return module
    try:
        return importlib.import_module("biocore_model." + name)
    except Exception:
        try:
            return importlib.import_module("." + name, package="biocore_model")
        except Exception:
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


# ---------------------------------------------------------------- inputs
def needs_of(state):
    """The four needs as stored (missing keys -> the 0.6 baseline)."""
    state = state if isinstance(state, dict) else {}
    raw = state.get("needs") if isinstance(state.get("needs"), dict) else {}
    core = state.get("core") if isinstance(state.get("core"), dict) else {}
    if not raw and isinstance(core.get("needs"), dict):
        raw = core.get("needs")
    return {key: round(_clamp(raw.get(key, NEED_DEFAULT), 0.0, 1.0), 4)
            for key in NEED_CAPS}


def behaviour_bias(needs):
    """Deficits/surpluses -> 0..1 behavioural bias.

    Same four keys and the same weights as biocore_model.needs_events
    .behavior_bias, so the fallback and the module never disagree.
    """
    state = needs if isinstance(needs, dict) else {}
    values = {key: _clamp(state.get(key, NEED_DEFAULT), 0.0, 1.0)
              for key in NEED_CAPS}

    def deficit(key):
        return max(0.0, NEED_DEFAULT - values[key])

    def surplus(key):
        return max(0.0, values[key] - NEED_DEFAULT)

    # Each action reads exactly one need (same split as needs_events); a deficit
    # in another need never leaks in.
    return {
        "seek_contact": round(_clamp(3.0 * deficit("belonging"), 0.0, 1.0), 3),
        "self_assert": round(_clamp(2.0 * surplus("self_esteem"), 0.0, 1.0), 3),
        "ask_clarify": round(_clamp(2.0 * deficit("control"), 0.0, 1.0), 3),
        "share_meaning": round(_clamp(2.5 * surplus("meaningful_existence"),
                                      0.0, 1.0), 3),
    }


def need_bias_rows(needs, baseline=NEED_DEFAULT):
    """Fallback twin of needs_events.need_biases: one row per need."""
    values = {key: _clamp((needs or {}).get(key, baseline), 0.0, 1.0)
              for key in NEED_CAPS}
    base = _clamp(baseline, 0.0, 1.0)
    rows = {}
    for key in NEED_CAPS:
        deficit = max(0.0, base - values[key])
        surplus = max(0.0, values[key] - base)
        rows[key] = {"value": round(values[key], 4),
                     "deficit": round(deficit, 4),
                     "surplus": round(surplus, 4),
                     "bias": round(surplus - deficit, 4)}
    return rows


def _split_state(state):
    state = state if isinstance(state, dict) else {}
    core = state.get("core") if isinstance(state.get("core"), dict) else {}
    relationship = state.get("relationship") if isinstance(
        state.get("relationship"), dict) else {}
    return state, core, relationship


def affect_of(state, relationship=None):
    """The six coupled values as this module reads them."""
    _, core, rel = _split_state(state)
    rel = relationship if isinstance(relationship, dict) and relationship else rel
    return {
        "v": _clamp(_first(core, state, "v", 0.0), -1.0, 1.0),
        "a": _clamp(_first(core, state, "a", 0.5), 0.0, 1.0),
        "stress": _clamp(_first(core, state, "stress", 0.2), 0.0, 1.0),
        "social": _clamp(_first(core, state, "social", 0.55), 0.0, 1.0),
        "trust": _clamp(rel.get("trust", 0.5), 0.0, 1.0),
        "closeness": _clamp(rel.get("closeness", 0.5), 0.0, 1.0),
    }


def _first(core, state, key, default):
    for source in (core, state):
        if isinstance(source, dict) and source.get(key) is not None:
            return source.get(key)
    if key == "v":
        for source in (core, state):
            if source.get("valence") is not None:
                return source.get("valence")
    if key == "a":
        for source in (core, state):
            if source.get("arousal") is not None:
                return source.get("arousal")
    return default


def dims_of(payload):
    """Appraisal dims from {"dims": ...} / {"appraisal": {"dims": ...}}."""
    data = payload if isinstance(payload, dict) else {}
    raw = data.get("dims")
    if not isinstance(raw, dict):
        block = data.get("appraisal")
        if isinstance(block, dict):
            raw = block.get("dims") if isinstance(block.get("dims"), dict) else block
    if not isinstance(raw, dict):
        return {}
    out = {}
    for name in ("goal", "blame", "control", "certainty", "novelty",
                 "involve", "hit"):
        if name in raw:
            low = -1.0 if name == "goal" else 0.0
            out[name] = round(_clamp(raw.get(name), low, 1.0), 4)
    return out


# ---------------------------------------------------------------- snapshot
def snapshot(store, session_id="s1", payload=None, state=None, now=None,
             enabled_override=None):
    """turn_start: one deterministic read of the twelve modules."""
    data = payload if isinstance(payload, dict) else {}
    stamp = round(float(now if now is not None else time.time()), 3)
    if not _switch(enabled_override, data, store):
        return {"enabled": False, "reason": "disabled", "ts": stamp,
                "session_id": str(session_id)}

    state, core, rel = _split_state(state if state is not None else data.get("state"))
    affect = affect_of(state, rel)
    v, a, stress = affect["v"], affect["a"], affect["stress"]
    social = affect["social"]
    user_text = str(data.get("user_text") or "")
    dims = dims_of(data)

    out = {"schema": SCHEMA, "enabled": True, "ts": stamp,
           "session_id": str(session_id), "affect": affect,
           "modules": {name: False for name in MODULES}}
    # the substrate body (mindbase), when the host supplies it: rendered by
    # expr_state._section_body, not as a separate line in the memory block
    body_state = data.get("body_state")
    if isinstance(body_state, dict) and body_state:
        out["body"] = dict(body_state)

    # 1) emotion_geometry: the continuous point -> soft label distribution
    geo = _call("emotion_geometry", "classify",
                {"v": v, "a": a, "d": _num(core.get("d"), 0.0),
                 "social": social, "stress": stress})
    geo_value = _value(geo, {}) or {}
    probs = geo_value.get("probs") if isinstance(geo_value.get("probs"), dict) else {}
    top = sorted(probs.items(), key=lambda row: -abs(_num(row[1]))) if probs else []
    out["emotion"] = {
        "label": str(geo_value.get("label") or ""),
        "confidence": round(_num(geo_value.get("confidence"), 0.0), 4),
        # raw per-emotion closeness; the softmax below is a display label only
        "scores": dict(geo_value.get("scores") or {}),
        "scores_are_raw": True,
        "top": [{"label": str(name), "prob": round(_num(prob), 4)}
                for name, prob in top[:3]],
        "enabled": bool(geo.get("enabled")),
    }
    out["modules"]["emotion_geometry"] = bool(geo.get("enabled"))

    # 2) appraisal + 3) appraisal_action: dims -> bounded deltas, action read
    deltas = {}
    legacy = {"v": 0.0, "v_legacy": None, "mapping": "v1"}
    if dims:
        legacy = _value(_call("appraisal", "appraise_with_legacy", dims,
                              _num(data.get("confidence"), 0.5),
                              v2=appraisal_v2(data)), {}) or legacy
        deltas = (legacy.get("deltas")
                  if isinstance(legacy, dict) else {}) or {}
    out["appraisal"] = {
        "dims": dict(dims) or dict(NEUTRAL_DIMS),
        "source": "payload" if dims else "none",
        "v": round(_num(legacy.get("v"), 0.0), 4),
        "v_legacy": (None if legacy.get("v_legacy") is None
                     else round(_num(legacy.get("v_legacy"), 0.0), 4)),
        "mapping": str(legacy.get("mapping") or "v1"),
        "deltas": {key: round(_num(value), 4) for key, value in
                   (deltas or {}).items()},
        "needs_deltas": (_value(_call("appraisal", "needs_deltas", dims), {}) or {})
        if dims else {},
        "enabled": bool(_mod("appraisal") is not None),
    }
    out["modules"]["appraisal"] = bool(_mod("appraisal") is not None)
    action = _value(_call("appraisal_action", "action_for",
                          str((out["emotion"] or {}).get("label") or "neutral")), {}) or {}
    out["action"] = {"kind": str(action.get("action") or action.get("kind") or ""),
                     "label": str(action.get("label") or ""),
                     "enabled": bool(_mod("appraisal_action") is not None)}
    out["modules"]["appraisal_action"] = bool(_mod("appraisal_action") is not None)

    # 4) attachment_state / 5) attachment_behavior / 6) attachment_regulation
    attach_state = state.get("attachment") if isinstance(state.get("attachment"), dict) else {}
    style = str(rel.get("attachment_style")
                or attach_state.get("style") or "secure")
    activation = _clamp(attach_state.get("activation", 0.0), 0.0, 1.0)
    attach_view = _value(_call("attachment_state", "view",
                               {"activation": activation}, style), {}) or {}
    behavior = _value(_call("attachment_behavior", "evaluate", style,
                            {"closeness": affect["closeness"],
                             "stress": stress,
                             "ignored": bool(data.get("ignored"))}), {}) or {}
    directives = _value(_call("attachment_behavior", "directives", behavior), {}) or {}
    strategy = str(_value(_call("attachment_regulation", "choose_strategy",
                                style, _num(core.get("energy"), 0.6), v), "reappraise"))
    effort = round(abs(min(0.0, v)) + stress * 0.5, 4)
    regulation = _value(_call("attachment_regulation", "regulate",
                              strategy, stress, effort), {}) or {}
    out["attachment"] = {
        "style": str(attach_view.get("style") or style),
        "activation": round(_num(attach_view.get("activation"), activation), 4),
        "mode": str(attach_view.get("mode") or ""),
        "drive_mult": round(_num(attach_view.get("drive_mult"), 1.0), 4),
        "initiative": round(_num(behavior.get("initiative"), 0.5), 4),
        "seeking": round(_num(behavior.get("seeking"), 0.4), 4),
        "withdrawal": round(_num(behavior.get("withdrawal"), 0.3), 4),
        "tone": str(directives.get("tone") or ""),
        "length_scale": round(_num(directives.get("length_scale"), 1.0), 4),
        "strategy": strategy,
        "suppressed": bool(regulation.get("suppressed")),
        "enabled": bool(_mod("attachment_state") is not None),
    }
    out["modules"]["attachment_state"] = bool(_mod("attachment_state") is not None)
    out["modules"]["attachment_behavior"] = bool(_mod("attachment_behavior") is not None)
    out["modules"]["attachment_regulation"] = bool(
        _mod("attachment_regulation") is not None)

    # 7) attribution (rule-based; ambiguous text stays neutral)
    attribution = _value(_call("attribution", "infer", {"text": user_text}), {}) or {}
    out["attribution"] = {"locus": str(attribution.get("locus") or "neutral"),
                          "stability": str(attribution.get("stability") or "neutral"),
                          "controllability": str(
                              attribution.get("controllability") or "neutral"),
                          "emotion_hint": str(attribution.get("emotion_hint")
                                              or "neutral"),
                          "enabled": bool(attribution)}
    out["modules"]["attribution"] = bool(attribution)

    # 8) needs: the four needs as stored (needs_events itself is batch A2)
    out["needs"] = needs_of(state)
    out["needs_bias"] = behaviour_bias(out["needs"])

    # 9) affective_labor (read of the accumulated load)
    labor_state = state.get("affective_labor") if isinstance(
        state.get("affective_labor"), dict) else {}
    risk = _value(_call("affective_labor", "risk", labor_state), 0.0)
    headroom = _value(_call("affective_labor", "headroom", labor_state), 0.0)
    out["labor"] = {"risk": round(_num(risk), 4),
                    "headroom": round(_num(headroom), 4),
                    "load": round(_num(labor_state.get("load"), 0.0), 4),
                    "components": dict(labor_state.get("components") or {}),
                    "enabled": bool(_mod("affective_labor") is not None)}
    out["modules"]["affective_labor"] = bool(_mod("affective_labor") is not None)

    # 10) compassion_fatigue: how much comfort is left
    fatigue = _value(_call("compassion_fatigue", "fatigue",
                           int(_num(state.get("comfort_streak"), 0)),
                           max(0.0, -v), 0.0), {}) or {}
    out["empathy"] = {"fatigue": round(_num(fatigue.get("fatigue"), 0.0), 4),
                      "empathy": round(_num(fatigue.get("empathy"), 1.0), 4),
                      "enabled": bool(fatigue)}
    out["modules"]["compassion_fatigue"] = bool(fatigue)

    # 11) defense_mechanisms (only meaningful for a negative moment)
    defense = _value(_call("defense_mechanisms", "assess",
                           {"kind": "message", "valence": v,
                            "intensity": abs(v), "text": user_text[:60]},
                           {"valence": v, "arousal": a, "stress": stress}), {}) or {}
    out["defense"] = {"mechanism": str(defense.get("mechanism") or "none"),
                      "strength": round(_num(defense.get("strength"), 0.0), 4),
                      "cost": round(_num(defense.get("cost"), 0.0), 4),
                      "enabled": bool(defense)}
    out["modules"]["defense_mechanisms"] = bool(defense)

    # 12) criticality + autonomic: the slow/erratic body rhythm
    seed = hashlib.sha1(str(session_id).encode("utf-8")).hexdigest()[:8]
    burst = _value(_call("criticality", "burst_value", seed,
                         int(stamp // 60)), 0.0)
    out["criticality"] = {"burst": round(_num(burst), 4),
                          "enabled": _mod("criticality") is not None}
    out["modules"]["criticality"] = _mod("criticality") is not None
    threshold = _value(_call("autonomic", "threshold", 0.35, stamp), 0.35)
    wave = _value(_call("autonomic", "wave", stamp), 0.0)
    out["autonomic"] = {"threshold": round(_num(threshold, 0.35), 4),
                        "wave": round(_num(wave), 4),
                        "enabled": _mod("autonomic") is not None}
    out["modules"]["autonomic"] = _mod("autonomic") is not None

    # ================= batch A2: the remaining eleven ==================
    # 13) needs_events: the four needs + the deficits that bias behaviour
    raw_needs = state.get("needs") if isinstance(state.get("needs"), dict) else {}
    if not raw_needs and isinstance(core.get("needs"), dict):
        raw_needs = core.get("needs")
    needs = _value(_call("needs_events", "needs_state", raw_needs), {}) or {}
    bias = _value(_call("needs_events", "behavior_bias", needs), {}) or {}
    out["needs"] = ({key: round(_num(needs.get(key), NEED_DEFAULT), 4)
                     for key in NEED_CAPS} if needs else needs_of(state))
    out["needs_bias"] = ({str(key): round(_num(value), 4)
                          for key, value in bias.items()} if bias
                         else behaviour_bias(out["needs"]))
    # one line per need: each keeps its own deficit/surplus/bias
    rows = _value(_call("needs_events", "need_biases", out["needs"]), {}) or {}
    out["needs_bias_rows"] = ({str(key): dict(row)
                               for key, row in rows.items()
                               if isinstance(row, dict)}
                              if rows else need_bias_rows(out["needs"]))
    out["modules"]["needs_events"] = bool(needs)

    # 14) needs_esteem: state self-esteem + the dominant need's tendency
    esteem = _clamp(_num((state.get("appraisal") or {}).get("self_esteem"),
                         SELF_ESTEEM_BASE), 0.0, 1.0)
    dominant = str(_value(_call("needs_esteem", "dominant", out["needs"]), "") or "")
    tendency = _value(_call("needs_esteem", "behaviour", out["needs"]), {}) or {}
    out["esteem"] = {"self_esteem": round(esteem, 4), "dominant": dominant,
                     "tone": str(tendency.get("tone") or ""),
                     "confidence_delta": round(
                         _num(tendency.get("confidence_delta"), 0.0), 4),
                     "enabled": bool(tendency)}
    out["modules"]["needs_esteem"] = bool(tendency)

    # 15) needs_sleep: sleep debt and what it costs
    sleep_doc = state.get("sleep") if isinstance(state.get("sleep"), dict) else {}
    debt = _clamp(_num(sleep_doc.get("debt_hours"), 0.0), 0.0, 24.0)
    debt_view = _value(_call("needs_sleep", "view", out["needs"], debt), {}) or {}
    out["sleep_debt"] = {
        "debt": round(_num(debt_view.get("sleep_debt"), debt), 3),
        "energy_penalty": round(_num(debt_view.get("energy_penalty"), 0.0), 4),
        "irritability": round(_num(debt_view.get("irritability"), 0.0), 4),
        "enabled": bool(debt_view)}
    out["modules"]["needs_sleep"] = bool(debt_view)

    # 16) sleep_circadian: where the body is in the day
    rhythm = _value(_call("sleep_circadian", "sleep_state", stamp), {}) or {}
    out["sleep"] = {"sleeping": bool(rhythm.get("sleeping")),
                    "circadian": round(_num(rhythm.get("circadian"), 0.5), 4),
                    "hour": round(_num(rhythm.get("hour"), 0.0), 3),
                    "quality": round(_num(rhythm.get("sleep_quality"), 0.7), 4),
                    "enabled": bool(rhythm)}
    out["modules"]["sleep_circadian"] = bool(rhythm)

    # 17) frustration_curve: the Amsel curve behind repeated attempts
    attempts = max(0, int(_num(state.get("frustration_n"), 0)))
    out["frustration"] = {
        "n": attempts,
        "phase": str(_value(_call("frustration_curve", "phase", attempts), "")
                     or ""),
        "drive_mult": round(_num(_value(_call(
            "frustration_curve", "frustration_mult", attempts), 1.0), 1.0), 4),
        "enabled": _mod("frustration_curve") is not None}
    out["modules"]["frustration_curve"] = _mod("frustration_curve") is not None

    # 18) envy: the third person (only when the host names one)
    envy_input = data.get("envy") if isinstance(data.get("envy"), dict) else {}
    signals = {"closeness": affect["closeness"], "fairness": 0.5,
               "third_party": 0.0, "self_evaluation": esteem, "stage": 0.5}
    for key, value in envy_input.items():
        if key in signals:
            signals[key] = value
    envy = _value(_call("envy", "assess", signals), {}) or {}
    out["envy"] = {"kind": str(envy.get("kind") or ""),
                   "intensity": round(_num(envy.get("intensity"), 0.0), 4),
                   "behavior": str(envy.get("behavior") or ""),
                   "components": dict(envy.get("components") or {}),
                   "enabled": bool(envy)}
    out["modules"]["envy"] = bool(envy)

    # 19) regulation_strategies + 20) regulation_loop
    intero = state.get("intero") if isinstance(state.get("intero"), dict) else {}
    if not intero and isinstance(core.get("intero"), dict):
        intero = core["intero"]
    event = {"kind": "message", "intensity": abs(v), "when": "after",
             "valence": v, "controllable": _num(
                 (dims or {}).get("control"), 0.5)}
    regulation = _value(_call("regulation_strategies", "evaluate",
                              {"valence": v, "arousal": a, "stress": stress,
                               "energy": _num(core.get("energy"), 0.6)},
                              event, rel), {}) or {}
    loop = _value(_call("regulation_loop", "choose_action", intero,
                        {"stress": stress, "valence": v}), {}) or {}
    out["regulation"] = {
        "strategy": str(regulation.get("strategy") or ""),
        "label": str(regulation.get("label") or ""),
        "effect": round(_num(regulation.get("effect"), 0.0), 4),
        "cost": round(_num(regulation.get("cost"), 0.0), 4),
        "fit": round(_num(regulation.get("fit"), 0.0), 4),
        "score_parts": dict(regulation.get("score_parts") or {}),
        "action": str(loop.get("action") or loop.get("kind") or ""),
        "enabled": bool(regulation) or bool(loop)}
    out["modules"]["regulation_strategies"] = bool(regulation)
    out["modules"]["regulation_loop"] = bool(loop)

    # 21) situation: at most three lines, never parsed back
    history = data.get("history")
    if not isinstance(history, list) or not history:
        history = [{"role": "user", "text": user_text[:80], "ts": stamp}]
    lines_raw = _value(_call("situation", "summarize",
                             history, {"v": v, "a": a,
                                       "stress": stress}, rel,
                             None, stamp, data.get("situation")), "")
    lines = [row.strip() for row in str(lines_raw or "").splitlines()
             if row.strip()][:3]
    out["situation"] = {"lines": lines, "chars": len("".join(lines)),
                        "enabled": bool(lines)}
    out["modules"]["situation"] = bool(lines)

    # 22) social_theory: share / ask tendencies + the mood hint
    hint = _value(_call("social_theory", "mood_hint_from_dims", dims or {}, v), "")
    share = _value(_call("social_theory", "share_probability",
                         affect["closeness"]), 0.0)
    ask = _value(_call("social_theory", "question_probability",
                       affect["closeness"]), 0.0)
    out["social"] = {"mood_hint": str(hint or ""),
                     "share_probability": round(_num(share, 0.0), 4),
                     "question_probability": round(_num(ask, 0.0), 4),
                     "enabled": _mod("social_theory") is not None}
    out["modules"]["social_theory"] = _mod("social_theory") is not None

    # 23) waiting_sense: what the silence feels like
    last_human = _num(state.get("last_human_ts"), 0.0)
    gap = max(0.0, stamp - last_human) if last_human > 0 else 0.0
    waiting = _value(_call("waiting_sense", "waiting_sense", gap,
                           {"valence": v, "arousal": a}, rel,
                           bool(data.get("awaiting_reply", True)), None),
                     {}) or {}
    out["waiting"] = {"gap_seconds": round(gap, 1),
                      "sense": round(_num(waiting.get("waiting"), 0.0), 4),
                      "feeling": str(waiting.get("feeling") or ""),
                      "night": bool(waiting.get("night")),
                      "enabled": bool(waiting)}
    out["modules"]["waiting_sense"] = bool(waiting)

    out["counts"] = {"modules": len(MODULES),
                     "a1": len(MODULES_A1), "a2": len(MODULES_A2),
                     "enabled": sum(1 for flag in out["modules"].values() if flag)}
    _record(store, session_id, out)
    return out


def _switch(enabled_override, payload, store):
    if isinstance(enabled_override, bool):
        return enabled_override
    return enabled(overrides=payload, store=store)


# ---------------------------------------------------------------- writeback
CONFLICT_CAP = 0.15        # per turn, same as the field write caps
CONFLICT_DEFAULT = 0.10   # a bare repair_failed / hostility with no blame dims
CONFLICT_WRITERS = ("appraisal_blame", "blame", "repair_failed",
                    "explicit_hostility", "relational_conflict",
                    "relationship_conflict", "confrontation")


def conflict_from_appraisal(data, dims, appraisal_deltas):
    """(event, delta) for the dimensions conflict axis, capped per turn.

    Only a relationship event may write it: blame from the appraisal, a failed
    repair or an explicit hostility. A task disagreement is refused outright
    (De Dreu & Weingart 2003), and nothing here touches trust or closeness.
    """
    data = data if isinstance(data, dict) else {}
    named = str(data.get("conflict_event") or "").strip().lower()
    if named and _dimensions is not None and not _dimensions.is_conflict_event(named):
        return "", 0.0
    event = named
    if not event:
        if _num((dims or {}).get("blame"), 0.0) >= 0.4:
            event = "appraisal_blame"
        elif data.get("repair_failed"):
            event = "repair_failed"
    if event not in CONFLICT_WRITERS:
        return "", 0.0
    raw = abs(_num((appraisal_deltas or {}).get("conflict"), 0.0))
    if raw <= 1e-9:     # v1 has no conflict row: fall back to the blame weight
        raw = abs(_num((dims or {}).get("blame"), 0.0)) * 0.6
    if raw <= 1e-9:     # a bare relational event (failed repair, hostility)
        raw = CONFLICT_DEFAULT
    return event, round(min(CONFLICT_CAP, raw), 6)


def appraisal_v2(payload=None):
    """appraisal_v2: payload flag > BIOCORE_APPRAISAL_V2 > default ON."""
    data = payload if isinstance(payload, dict) else {}
    if isinstance(data.get("appraisal_v2"), bool):
        return data["appraisal_v2"]
    raw = str(os.environ.get("BIOCORE_APPRAISAL_V2") or "").strip().lower()
    return raw not in ("0", "false", "off", "no")


def absorb_rate(strategy):
    """Gross 1998: reappraisal 0.6 / suppression 0.3 / everything else 0.5."""
    key = str(strategy or "").strip()
    return REG_ABSORB_BY_STRATEGY.get(key, REG_ABSORB)


def absorb_factor(strategy, effect):
    """Bounded share of one turn's negative pressure this strategy takes away."""
    return round(absorb_rate(strategy) * _clamp(_num(effect, 0.0), 0.0, 1.0), 4)


def dim_absorb(strategy, dim, effect):
    """How much this strategy takes off ONE dimension (strategy x dimension).

    There is no single keep factor any more: valence, arousal, stress, social
    and trust each get their own share, so damping one axis never implies
    damping another.
    """
    key = str(strategy or "").strip()
    gain = REG_DIM_GAIN.get(key, {}).get(str(dim), REG_DIM_DEFAULT)
    return round(_clamp(absorb_rate(key) * _clamp(gain, 0.0, 1.0)
                        * _clamp(_num(effect, 0.0), 0.0, 1.0), 0.0, 1.0), 4)


def writeback(store, session_id="s1", payload=None, state=None, now=None,
              enabled_override=None, own_field=False):
    """turn_end: appraisal -> deltas, needs -> bounded, attachment -> bounded.

    Returns the bounded field proposals under "field_deltas" so the caller can
    hand them to biocore_runtime.arbiter (one write path, one cap per turn).
    own_field=True applies them here instead (used when the field layer is off).
    """
    data = payload if isinstance(payload, dict) else {}
    stamp = round(float(now if now is not None else time.time()), 3)
    if not _switch(enabled_override, data, store):
        return {"enabled": False, "reason": "disabled", "ts": stamp,
                "applied": {}, "field_deltas": {}}

    state, core, rel = _split_state(state if state is not None else data.get("state"))
    marker = state.get("perception") if isinstance(state.get("perception"), dict) else {}
    if _num(marker.get("ts"), 0.0) >= stamp:
        return {"enabled": True, "reason": "duplicate", "ts": stamp,
                "applied": {}, "field_deltas": {}, "duplicate": True}

    dims = dims_of(data)
    confidence = _clamp(data.get("confidence", 0.5), 0.0, 1.0)
    appraisal_deltas = {}
    if dims:
        appraisal_deltas = _value(_call("appraisal", "appraise", dims,
                                        confidence,
                                        v2=appraisal_v2(data)), {}) or {}

    # -- dimensions: appraisal blame (or a failed repair) raises conflict;
    # task disagreement never does, and trust/closeness are never derived.
    conflict_event, conflict_delta = conflict_from_appraisal(
        data, dims, appraisal_deltas)
    dimension_conflict = {"event": conflict_event, "delta": conflict_delta,
                          "applied": False}
    if (conflict_delta > 0 and _dimensions is not None
            and _dimensions.conflict_enabled(data, env=os.environ)):
        model = _dimensions.load(state)
        model = _dimensions.raise_conflict(model, conflict_event,
                                           conflict_delta,
                                           source="appraisal", now=stamp)
        state["dimensions"] = model
        dimension_conflict["applied"] = True
        dimension_conflict["value"] = round(
            max(model["dims"]["conflict"]["explicit"],
                model["dims"]["conflict"]["implicit"]), 4)

    field_deltas = {}
    own_deltas = {}
    for name, raw in appraisal_deltas.items():
        number = _num(raw)
        if abs(number) <= 1e-6:
            continue
        if name in FIELD_CAPS:
            value = round(_clamp(number, -FIELD_CAPS[name], FIELD_CAPS[name]), 6)
            if abs(value) > 1e-6:
                field_deltas[name] = value
        elif name in OWN_CAPS:
            own_deltas[name] = round(_clamp(number, -OWN_CAPS[name],
                                            OWN_CAPS[name]), 6)

    # -- regulation_strategies: a chosen strategy absorbs part of the pressure
    # before it is applied, so it never fights the appraisal delta in the
    # arbiter (one number, not two competing ones).
    affect_now = affect_of(state, rel)
    event = {"kind": "message", "intensity": abs(affect_now["v"]),
             "when": "after", "valence": affect_now["v"],
             "controllable": _num((dims or {}).get("control"), 0.5)}
    regulation = _value(_call("regulation_strategies", "evaluate",
                              {"valence": affect_now["v"],
                               "arousal": affect_now["a"],
                               "stress": affect_now["stress"],
                               "energy": _num(core.get("energy"), 0.6)},
                              event, rel), {}) or {}
    strategy_name = regulation.get("strategy")
    effect = regulation.get("effect")
    absorb = absorb_factor(strategy_name, effect)
    per_dim = {}
    if absorb > 1e-4:
        for name in list(field_deltas):
            value = field_deltas[name]
            if not ((name in ("v", "social", "trust") and value < 0) or
                    (name in ("stress", "a") and value > 0)):
                continue
            share = dim_absorb(strategy_name, name, effect)
            per_dim[name] = share
            if share > 1e-4:
                field_deltas[name] = round(value * (1.0 - share), 6)

    # -- needs: dims-driven deltas + needs_events events, both capped
    raw_needs = state.get("needs") if isinstance(state.get("needs"), dict) else {}
    if not raw_needs and isinstance(core.get("needs"), dict):
        raw_needs = core.get("needs")
    needs_before = {key: round(_clamp(raw_needs.get(key, NEED_DEFAULT), 0.0, 1.0), 4)
                    for key in NEED_CAPS}
    needs_after = dict(needs_before)
    dim_needs = _value(_call("appraisal", "needs_deltas", dims), {}) if dims else {}
    for key, raw in (dim_needs or {}).items():
        if key not in NEED_CAPS:
            continue
        cap = NEED_CAPS[key]
        needs_after[key] = round(_clamp(needs_after[key]
                                        + _clamp(raw, -cap, cap), 0.0, 1.0), 4)
    events = _value(_call("needs_events", "events_from_dims", dims), []) if dims else []
    applied_events = []
    if isinstance(events, list) and events:
        result = _value(_call("needs_events", "apply", needs_after, events), None)
        if isinstance(result, tuple) and len(result) == 2:
            updated, report = result
            if isinstance(updated, dict):
                needs_after = {key: round(_clamp(updated.get(key), 0.0, 1.0), 4)
                               for key in NEED_CAPS}
            if isinstance(report, dict):
                applied_events = list(report.get("events") or [])
    for key in NEED_CAPS:  # the batch owns one bounded move per need per turn
        cap = NEED_CAPS[key]
        moved = _clamp(needs_after[key] - needs_before[key], -cap, cap)
        needs_after[key] = round(_clamp(needs_before[key] + moved, 0.0, 1.0), 4)
    needs_delta = {key: round(needs_after[key] - needs_before[key], 4)
                   for key in NEED_CAPS
                   if abs(needs_after[key] - needs_before[key]) > 1e-6}

    # -- attachment: threat signal -> activation, capped, then view
    attach_state = state.get("attachment") if isinstance(state.get("attachment"), dict) else {}
    style = str(rel.get("attachment_style") or attach_state.get("style") or "secure")
    before = _clamp(attach_state.get("activation", 0.0), 0.0, 1.0)
    signal = data.get("attachment_signal")
    if signal is None:
        signal = max(0.0, -affect_of(state, rel)["v"]) * 0.5 \
            + _clamp(rel.get("conflict", 0.0), 0.0, 1.0) * 0.5
    raised = _value(_call("attachment_state", "threat", before, _clamp(signal, 0.0, 1.0)), before)
    replied = bool(str(data.get("assistant_text") or "").strip())
    hours = max(0.0, _num(data.get("hours"), 0.0))
    decayed = _value(_call("attachment_state", "decay", _num(raised, before), replied,
                           hours), _num(raised, before))
    after = round(_clamp(_num(decayed, before), 0.0, 1.0), 4)
    delta = round(_clamp(after - before, -ATTACH_CAP, ATTACH_CAP), 4)
    after = round(max(0.0, min(1.0, before + delta)), 4)
    view = _value(_call("attachment_state", "view", {"activation": after}, style), {}) or {}
    attachment = {"style": str(view.get("style") or style),
                  "activation": after,
                  "mode": str(view.get("mode") or ""),
                  "before": round(before, 4),
                  "delta": delta,
                  "enabled": bool(view)}

    # -- apply the non-field writes; the six field values stay proposals so the
    # caller can fold them into core_state / the arbiter exactly once.
    if own_field:
        field_deltas_note = "own"
    else:
        field_deltas_note = "arbiter"
    previous_appraisal = state.get("appraisal") if isinstance(
        state.get("appraisal"), dict) else {}
    # -- needs_esteem: state self-esteem moves on the event, not on a raw delta
    esteem_before = _clamp(_num(previous_appraisal.get("self_esteem"),
                                SELF_ESTEEM_BASE), 0.0, 1.0)
    dims_now = dims or {}
    esteem_after = _value(_call(
        "needs_esteem", "self_esteem_update", esteem_before,
        bool(str(data.get("assistant_text") or "").strip()),
        _num(dims_now.get("goal"), 0.0) >= 0.4,
        _num(dims_now.get("hit"), 0.0) >= 0.6,
        _num(dims_now.get("hit"), 0.0) >= 0.8), esteem_before)
    esteem_after = round(_clamp(_num(esteem_after, esteem_before), 0.0, 1.0), 4)
    appraisal_state = {
        "d": round(_clamp(_num(previous_appraisal.get("d"), 0.0)
                          + _num(own_deltas.get("d")), -1.0, 1.0), 4),
        "self_esteem": esteem_after,
        "esteem_delta": round(esteem_after - esteem_before, 4),
        "dims": dict(dims),
        "deltas": {key: round(_num(value), 4)
                   for key, value in appraisal_deltas.items()},
        "updated_ts": stamp,
    }
    state["appraisal"] = appraisal_state

    # -- needs_sleep: only the host can move the debt (slept_hours / dt_hours)
    sleep_doc = state.get("sleep") if isinstance(state.get("sleep"), dict) else {}
    debt_before = _clamp(_num(sleep_doc.get("debt_hours"), 0.0), 0.0, 24.0)
    debt_after = debt_before
    slept_hours = data.get("slept_hours")
    idle_hours = data.get("dt_hours", data.get("hours"))
    if slept_hours is not None or idle_hours is not None:
        step = _value(_call("needs_sleep", "sleep_debt_step", debt_before,
                            _num(slept_hours, 0.0), _num(idle_hours, 0.0),
                            stamp, sleep_doc), {}) or {}
        debt_after = round(_clamp(_num(step.get("debt"), debt_before), 0.0, 24.0), 3)
        sleep_doc = {"debt_hours": debt_after, "last_debt_ts": stamp,
                     "updated_ts": stamp}
        state["sleep"] = sleep_doc
    sleep_info = {"debt": debt_after, "before": debt_before,
                  "delta": round(debt_after - debt_before, 3),
                  "energy_penalty": round(_clamp(_num(_value(_call(
                      "needs_sleep", "energy_penalty", debt_after), 0.0)), 0.0, 1.0), 4),
                  "irritability": round(_clamp(_num(_value(_call(
                      "needs_sleep", "irritability", debt_after), 0.0)), 0.0, 1.0), 4)}
    state["needs"] = needs_after
    state["attachment"] = {"style": attachment["style"],
                           "activation": after,
                           "mode": attachment["mode"],
                           "updated_ts": stamp}
    state["perception"] = {"ts": stamp, "applied": True,
                           "modules": len(MODULES)}
    core = state.get("core") if isinstance(state.get("core"), dict) else {}
    core["needs"] = dict(needs_after)
    state["core"] = core

    result = {"schema": SCHEMA, "enabled": True, "reason": "ok", "ts": stamp,
              "session_id": str(session_id),
              "appraisal": {"dims": dict(dims),
                            "deltas": {key: round(_num(value), 4)
                                       for key, value in appraisal_deltas.items()}},
              "applied": {"field": dict(field_deltas),
                          "own": dict(own_deltas)},
              "field_deltas": {"appraisal": dict(field_deltas)},
              "field_route": field_deltas_note,
              "own_deltas": dict(own_deltas),
              "d": appraisal_state["d"],
              "self_esteem": appraisal_state["self_esteem"],
              "needs": {"before": needs_before, "after": needs_after,
                        "delta": needs_delta, "events": applied_events},
              "regulation": {"strategy": str(regulation.get("strategy") or ""),
                             "effect": round(_num(regulation.get("effect"), 0.0), 4),
                             "absorbed": absorb,
                             "per_dim": dict(per_dim)},
              "dimension_conflict": dimension_conflict,
              "esteem": {"before": round(esteem_before, 4),
                         "after": esteem_after},
              "sleep": sleep_info,
              "attachment": attachment,
              "_state": state}
    _record(store, session_id, {key: result[key] for key in
                                ("ts", "session_id", "appraisal", "applied",
                                 "needs", "attachment", "regulation",
                                 "esteem", "sleep", "field_deltas")},
            key="last_writeback")
    return result


# ---------------------------------------------------------------- sidecar
def path(store):
    root = _data_dir(store)
    return (root / PERCEPTION_FILE) if root is not None else None


def _record(store, session_id, row, key="latest"):
    target = path(store)
    if target is None:
        return False
    doc = _read(target)
    history = [item for item in (doc.get("history") or [])
               if isinstance(item, dict)]
    history.append(row)
    doc.update({"schema": SCHEMA, "ts": row.get("ts"),
                "session_id": str(session_id),
                "history": history[-HISTORY_LIMIT:]})
    doc[key] = row
    return _write(target, doc)


def summary(store, session_id=None, enabled_override=None):
    """/state projection: the last snapshot, never recomputes."""
    if not _switch(enabled_override, {}, store):
        return {"enabled": False, "reason": "disabled"}
    doc = _read(path(store))
    latest = doc.get("latest") if isinstance(doc.get("latest"), dict) else {}
    if not latest:
        return {"enabled": False, "reason": "no_snapshot", "emotion": {},
                "affect": {}, "attachment": {}, "needs": {},
                "regulation": {}, "sleep": {}, "situation": {},
                "waiting": {}, "esteem": {}, "a2": {},
                "modules": {name: False for name in MODULES}}
    writeback = doc.get("last_writeback") if isinstance(
        doc.get("last_writeback"), dict) else {}
    # The writeback row is newer than the read snapshot: prefer it for the two
    # blocks this batch owns, and keep the snapshot's richer attachment read.
    attachment = dict(latest.get("attachment") or {})
    written = writeback.get("attachment") if isinstance(
        writeback.get("attachment"), dict) else {}
    for key in ("style", "activation", "mode"):
        if written.get(key) not in (None, ""):
            attachment[key] = written[key]
    written_needs = (writeback.get("needs") or {}).get("after")         if isinstance(writeback.get("needs"), dict) else None
    return {
        "enabled": True,
        "ts": writeback.get("ts") or latest.get("ts"),
        "session_id": latest.get("session_id"),
        "emotion": latest.get("emotion") or {},
        "affect": latest.get("affect") or {},
        "attachment": attachment,
        "needs": written_needs if isinstance(written_needs, dict)
        else (latest.get("needs") or {}),
        "appraisal": latest.get("appraisal") or {},
        # --- batch A2 -------------------------------------------------
        "regulation": latest.get("regulation") or {},
        "sleep": {**(latest.get("sleep") or {}),
                  **(latest.get("sleep_debt") or {}),
                  **((writeback.get("sleep") or {})
                     if isinstance(writeback.get("sleep"), dict) else {})},
        "situation": latest.get("situation") or {},
        "waiting": latest.get("waiting") or {},
        "esteem": {**(latest.get("esteem") or {}),
                   "self_esteem": (writeback.get("esteem") or {}).get(
                       "after", (latest.get("esteem") or {}).get("self_esteem"))},
        "a2": {key: latest.get(key) or {} for key in
               ("envy", "frustration", "social")},
        "modules": latest.get("modules") or {},
        "counts": latest.get("counts") or {},
        "writeback": writeback,
    }
