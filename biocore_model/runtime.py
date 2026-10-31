# -*- coding: utf-8 -*-
"""PIPE-2 runtime: assemble the default reply pipeline and expose run_reply.

The runtime is the only place that knows the stage order, the default switches
and the per-stage fallbacks. It never imports main and never writes files; the
caller injects everything through ctx (event/core/memory/llm/now/meta).

Wiring contract (main.py on_llm_request inserts 5 lines):
    from .biocore_model import runtime as _bc_reply_runtime
    _bc_reply_runtime.run_reply(_bc_reply_runtime.make_request_ctx(...))
If anything (including PipelineAbort) escapes a stage, run_reply contains it and
records meta.pipeline_error instead of raising, so the caller's original logic
always keeps working.
"""
from __future__ import annotations

import time

from . import expr_state as _expr_state
from . import expr_template as _expr_template
from . import prompt_rules as _prompt_rules
from . import schema as _schema
from . import stages as _stages
from .pipeline import Pipeline, PipelineAbort

SCHEMA = "bc.pipeline.v1"
MODES = ("shadow", "active")
MODE_DEFAULT = "shadow"
REQUIRED_STAGES = ("perceive", "decide", "present")
DEFAULT_SWITCHES = {
    "memory": True,
    "bio": True,
    "decide": True,
    "expr_state": True,
    "expr_tone": True,
    "expr_intent": True,
    "think": True,
    "parse": True,
    "feedback": True,
    "present": True,
}
_PIPELINE = None
_SWITCHES = {}
_MODE = MODE_DEFAULT


def get_mode():
    """Current pipeline mode (shadow by default, active after apply_mode)."""
    return _MODE


def apply_mode(mode):
    """Switch shadow|active in-process; behaviour changes without a restart."""
    global _MODE
    value = str(mode or "").strip().lower()
    if value not in MODES:
        raise ValueError("mode must be shadow|active")
    _MODE = value
    return _MODE


def reset_mode():
    """Test/config-reload helper: back to the safe shadow default."""
    global _MODE
    _MODE = MODE_DEFAULT
    return _MODE


def build_default_pipeline(switches=None, clock=None, **stage_opts):
    """Assemble stages in mainline order with per-stage fallbacks and switches."""
    pipeline = Pipeline(clock=clock)
    for stage in _stages.build_stages(**stage_opts):
        pipeline.register(stage)
    merged = dict(DEFAULT_SWITCHES)
    merged.update(switches or {})
    for name, enabled in merged.items():
        if name in REQUIRED_STAGES or enabled:
            continue
        try:
            pipeline.disable(name)
        except (KeyError, ValueError):
            continue
    return pipeline


def apply_switches(switches=None):
    """Merge persisted stage switches and rebuild the singleton on next use."""
    global _PIPELINE
    merged = dict(DEFAULT_SWITCHES)
    for name, value in (switches or {}).items():
        if isinstance(value, bool):
            merged[str(name)] = value
    _SWITCHES.clear()
    _SWITCHES.update(merged)
    _PIPELINE = None
    return dict(_SWITCHES)


def get_switches():
    """Effective stage switches (defaults unless apply_switches was called)."""
    merged = dict(DEFAULT_SWITCHES)
    merged.update(_SWITCHES)
    return merged


def get_pipeline(rebuild=False):
    """Process-wide default pipeline (lazy singleton)."""
    global _PIPELINE
    if rebuild or _PIPELINE is None:
        _PIPELINE = build_default_pipeline(switches=dict(_SWITCHES))
    return _PIPELINE


def reset_pipeline():
    """Drop the singleton (tests / config reload)."""
    global _PIPELINE
    _PIPELINE = None


def set_enabled(name, enabled):
    """Runtime-level switch; the mainline required stages are locked on."""
    if name in REQUIRED_STAGES and not enabled:
        raise ValueError("required stage cannot be disabled: " + str(name))
    return get_pipeline().set_enabled(name, enabled)


def get_status():
    return get_pipeline().get_status()


def _umo_of(event):
    for attr in ("unified_msg_origin", "umo"):
        try:
            value = getattr(event, attr, None)
            value = value() if callable(value) else value
        except Exception:
            value = None
        if value:
            return str(value)
    return ""


def _sender_of(event):
    for attr in ("get_sender_id", "sender_id", "user_id"):
        try:
            value = getattr(event, attr, None)
            value = value() if callable(value) else value
        except Exception:
            value = None
        if value:
            return str(value)
    return ""


def make_request_ctx(plugin=None, event=None, core=None, text="", user=None,
                     memory=None, req=None, now=None, meta=None):
    """Build the ctx handed to run_reply from on_llm_request values.

    Side effects are off by default (write_core/observe False): the request hook
    only *shadow-runs* the mainline, so behaviour of the original prompt path is
    untouched. Tests and future phases can flip them through meta.
    """
    state = None
    getter = getattr(core, "snapshot", None)
    if callable(getter):
        try:
            state = getter()
        except Exception:
            state = None
    base_meta = {
        "now": float(now) if now is not None else time.time(),
        "shadow": get_mode() != "active",
        "write_core": False,
        "observe": False,
        "observe_core": False,
        "pipeline_mode": get_mode(),
        "source": "llm",
        "memory_limit": 4,
        "pipeline": SCHEMA,
    }
    if isinstance(meta, dict):
        base_meta.update(meta)
    ctx = {
        "event": event,
        "user": user if user is not None else _sender_of(event),
        "umo": _umo_of(event),
        "core": core,
        "state": state,
        "memory": memory if isinstance(memory, list) else [],
        "decision": None,
        "intent": None,
        "tone": None,
        "prompt": "",
        "llm_raw": "",
        "parsed": None,
        "deltas": {},
        "reply": "",
        "meta": base_meta,
        "text": str(text or ""),
        "req": req,
        "plugin": plugin,
    }
    return ctx


def reply_text(ctx):
    """Final legal reply from a finished ctx ('' when the mainline had none)."""
    if not isinstance(ctx, dict):
        return ""
    value = ctx.get("reply")
    return value if isinstance(value, str) else ""


def run_prompt(ctx=None, pipeline=None):
    """Active-mode prompt assembly: {prompt_system, prompt_user, trace} or None.

    Prompt-only: no llm and no reply are required. Returns None when the
    mainline failed or produced nothing usable, so the caller can fall back to
    its original prompt assembly path.
    """
    ctx = enrich_ctx(ctx if isinstance(ctx, dict) else {})
    meta = dict(ctx.get("meta") or {})
    if meta.get("observe_core"):
        meta["observe"] = True
    ctx["meta"] = meta
    out = _execute_reply(ctx, pipeline=pipeline)
    meta = out.get("meta") if isinstance(out.get("meta"), dict) else {}
    trace = out.get("trace") if isinstance(out.get("trace"), dict) else {}
    if meta.get("pipeline_error"):
        return None
    state_text = str(out.get("state_text") or "").strip()
    text = str(out.get("text") or "").strip()
    if not state_text and not text:
        return None
    tone_text = str((out.get("tone") or {}).get("text") or "").strip()
    _out_intent = out.get("intent")
    _out_intent_ok = isinstance(_out_intent, dict) and bool(
        _out_intent.get("text_hint") or _out_intent.get("kind"))
    intent = _out_intent if _out_intent_ok else ctx.get("intent")
    intent_text = ""
    if isinstance(intent, dict):
        intent_text = str(intent.get("text_hint") or intent.get("kind") or "")
    elif intent:
        intent_text = str(intent)
    relationship_text = str(ctx.get("relationship_text") or "")
    if relationship_text and "关系" in state_text:
        relationship_text = ""  # state_block already carries the relationship section
    gap_text = str(ctx.get("gap_text") or "")
    opts = meta.get("template_opts") if isinstance(meta.get("template_opts"), dict) else {}
    try:
        built = _expr_template.build_reply(
            snapshot=out.get("state") if isinstance(out.get("state"), dict) else {},
            state_ctx={"state_block": state_text,
                       "relationship": relationship_text, "gap": gap_text,
                       "recent_proactive": str(ctx.get("recent_proactive") or ""),
                       "numeric_legend": str(ctx.get("numeric_legend") or "")},
            intent=intent, tone=tone_text, guard=None, opts=opts)
    except Exception:
        built = None
    system = str((built or {}).get("system") or "").strip()
    user = str((built or {}).get("user") or "").strip()
    if not user:
        user = "\n".join(part for part in (state_text, relationship_text, gap_text,
                                           intent_text, tone_text) if part).strip()
    if not system:
        system = "\n".join(part for part in (opts.get("persona"), opts.get("speak_style")) if part).strip()
    if not user and not system:
        return None
    return {"prompt_system": system, "prompt_user": user, "trace": trace,
            "order": (built or {}).get("order") or []}


def run_reply(ctx=None, pipeline=None):
    """Mode router: active returns the prompt payload, shadow returns the ctx.

    Active mode: {prompt_system, prompt_user, trace} (None-like empty dict when
    the mainline cannot produce a prompt, so callers can fall back). Shadow mode
    returns the pipeline ctx exactly as before.
    """
    if get_mode() == "active":
        payload = run_prompt(ctx, pipeline=pipeline)
        return payload if isinstance(payload, dict) else {}
    return _execute_reply(ctx, pipeline=pipeline)


def _acc_of(plugin=None):
    """Autonomy accumulator (ui_settings.autonomy.accumulator) or {}."""
    try:
        try:
            from . import ui_settings as _ui
        except Exception:  # pragma: no cover
            import ui_settings as _ui  # type: ignore
        data = _ui.load(plugin) if plugin is not None else _ui.load(None)
        section = data.get("autonomy") if isinstance(data, dict) else None
        acc = section.get("accumulator") if isinstance(section, dict) else None
        return dict(acc) if isinstance(acc, dict) else {}
    except Exception:
        return {}


def enrich_ctx(ctx=None):
    """Merge bio-mixin exposed state into ctx without overwriting caller fields.

    Adds: state (core.snapshot), relationship (plugin._relationship_of, also
    mirrored into meta for expr_state), motive / silence (autonomy accumulator
    views) and intent / tone (accumulator values). Never raises.
    """
    ctx = ctx if isinstance(ctx, dict) else {}
    meta = ctx.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    core = ctx.get("core")
    if not isinstance(ctx.get("state"), dict):
        getter = getattr(core, "snapshot", None)
        if callable(getter):
            try:
                state = getter()
                if isinstance(state, dict):
                    ctx["state"] = state
            except Exception:
                pass
    # Compact numeric legend for the system prompt: only significant deviations.
    if not ctx.get("numeric_legend"):
        try:
            state = ctx.get("state") if isinstance(ctx.get("state"), dict) else {}
            legend = _schema.numeric_legend(state) if state else ""
            if legend:
                ctx["numeric_legend"] = legend
        except Exception:
            pass
    plugin = ctx.get("plugin")
    if not ctx.get("recent_proactive"):
        try:
            _rows = getattr(plugin, "_recent_proactive", None)
            if not _rows and callable(getattr(plugin, "_load_recent_proactive", None)):
                _rows = plugin._load_recent_proactive()
            _texts = [str(x).strip() for x in (_rows or [])[-2:] if str(x).strip()]
            if _texts:
                ctx["recent_proactive"] = "我刚说过：" + "；".join(_texts)
        except Exception:
            pass
    if not isinstance(ctx.get("relationship"), dict):
        getter = getattr(plugin, "_relationship_of", None)
        if callable(getter):
            try:
                user = ctx.get("user")
                rel = getter(user if isinstance(user, dict) else {})
                if isinstance(rel, dict):
                    ctx["relationship"] = rel
            except Exception:
                pass
    if isinstance(ctx.get("relationship"), dict) and "relationship" not in meta:
        meta["relationship"] = ctx["relationship"]
    acc = _acc_of(plugin)
    if acc:
        if ctx.get("intent") is None and acc.get("intent") is not None:
            ctx["intent"] = acc.get("intent")
        if ctx.get("tone") is None and acc.get("tone") is not None:
            ctx["tone"] = acc.get("tone")
        try:
            try:
                from . import autonomy_tick as _tick
            except Exception:  # pragma: no cover
                import autonomy_tick as _tick  # type: ignore
        except Exception:
            _tick = None
        if not isinstance(ctx.get("motive"), dict):
            motive = acc.get("motive")
            if not isinstance(motive, dict) and _tick is not None:
                try:
                    state = ctx.get("state") if isinstance(ctx.get("state"), dict) else {}
                    parts = state.get("parts") if isinstance(state.get("parts"), dict) else {}
                    motive = _tick._compute_motive(acc, parts)
                except Exception:
                    motive = None
            if isinstance(motive, dict):
                ctx["motive"] = motive
        if not isinstance(ctx.get("silence"), dict):
            silence = acc.get("silence")
            if not isinstance(silence, dict) and _tick is not None:
                try:
                    now = meta.get("now")
                    silence = _tick._compute_silence(acc, float(now) if now is not None else time.time())
                except Exception:
                    silence = None
            if isinstance(silence, dict):
                ctx["silence"] = silence
    # L3 prompt layers (persona / speak style / protocol) for active prompts.
    # Precedence: explicit ctx key > caller meta.template_opts > plugin/default.
    base_opts = meta.get("template_opts") if isinstance(meta.get("template_opts"), dict) else {}
    persona = ctx.get("persona")
    if persona is None:
        persona = base_opts.get("persona") or getattr(plugin, "persona_text", "")
    if persona:
        ctx["persona"] = str(persona)
    speak_style = ctx.get("speak_style") or base_opts.get("speak_style")
    if not speak_style:
        try:
            speak_style = _prompt_rules.render_length_rule(10, 30)
        except Exception:
            speak_style = ""
    if speak_style:
        ctx["speak_style"] = str(speak_style)
    if not ctx.get("output_protocol"):
        ctx["output_protocol"] = (base_opts.get("output_protocol")
                                  or _expr_template.PROMPT_OUTPUT_PROTOCOL)
    relationship_text = str(ctx.get("relationship_text") or "")
    if not relationship_text:
        try:
            relationship_text = str(_expr_state._section_relationship(ctx.get("relationship")) or "")
        except Exception:
            relationship_text = ""
        if relationship_text:
            ctx["relationship_text"] = relationship_text
    gap_text = str(ctx.get("gap_text") or "")
    if not gap_text:
        silence = ctx.get("silence") if isinstance(ctx.get("silence"), dict) else {}
        try:
            hours = float(silence.get("hours", 0.0) or 0.0)
        except Exception:
            hours = 0.0
        if hours > 0:
            gap_text = "间隔：已 %.1f 小时没说话" % hours
            ctx["gap_text"] = gap_text
    opts = dict(base_opts)
    for key in ("persona", "speak_style", "output_protocol"):
        if ctx.get(key) and not opts.get(key):
            opts[key] = ctx[key]
    meta["template_opts"] = opts
    ctx["meta"] = meta
    return ctx


def run_active(ctx=None, pipeline=None):
    """Active-mode entry: enrich ctx, run the mainline, return the prompt payload.

    Returns {prompt_system, prompt_user, trace, order} on success; an empty dict
    on any failure (pipeline error / exception / empty prompt) so the caller can
    always fall back to its original prompt assembly. Shadow mode is untouched:
    this function only exists for callers that explicitly want active mode.
    """
    ctx = enrich_ctx(ctx if isinstance(ctx, dict) else {})
    meta = ctx.get("meta") if isinstance(ctx.get("meta"), dict) else {}
    meta["pipeline_mode"] = "active"
    meta["shadow"] = False
    ctx["meta"] = meta
    try:
        payload = run_prompt(ctx, pipeline=pipeline)
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        return {}
    system = str(payload.get("prompt_system") or "").strip()
    user = str(payload.get("prompt_user") or "").strip()
    if not system and not user:
        return {}
    trace = payload.get("trace") if isinstance(payload.get("trace"), dict) else {}
    trace = dict(trace)
    trace["runtime"] = {"schema": SCHEMA, "mode": "active",
                        "switches": dict(get_switches())}
    return {"prompt_system": system, "prompt_user": user,
            "trace": trace, "order": list(payload.get("order") or [])}


def _execute_reply(ctx=None, pipeline=None):
    """Run the reply mainline; never raises, always returns a ctx dict."""
    ctx = ctx if isinstance(ctx, dict) else {}
    active = pipeline if isinstance(pipeline, Pipeline) else get_pipeline()
    try:
        return active.run(ctx)
    except PipelineAbort as exc:
        meta = dict(ctx.get("meta") or {})
        meta["pipeline_error"] = {"kind": "abort", "stage": exc.stage_name,
                                  "note": exc.note}
        ctx["meta"] = meta
        return ctx
    except Exception as exc:  # contained: the caller keeps its original logic
        meta = dict(ctx.get("meta") or {})
        meta["pipeline_error"] = {"kind": "exception",
                                  "type": type(exc).__name__,
                                  "note": str(exc)[:120]}
        ctx["meta"] = meta
        return ctx
