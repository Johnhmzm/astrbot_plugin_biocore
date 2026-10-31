# -*- coding: utf-8 -*-
"""PIPE-2 stage wrappers: existing biocore_model modules exposed as pipeline stages.

Rules (task-108):
- a stage only reads/writes ctx; it never imports main and never touches files
  or wall-clock time (time/rng/llm are injected through ctx.meta).
- biological writes always go through feedback_guard.vet + feedback_guard.apply;
  stages never assign core attributes directly.
- every stage is defensive: missing data marks meta.skipped and returns a valid
  patch instead of raising, so one missing input cannot abort the mainline.

Stage names: perceive / memory / bio / decide / expr_state / expr_tone /
expr_intent / think / parse / feedback / present.
"""
from __future__ import annotations

from . import attribution as _attrib
from . import emotion_geometry as _emotion_geometry
from . import expr_intent as _expr_intent
from . import expr_state as _expr_state
from . import expr_template as _expr_template
from . import expr_tone as _expr_tone
from . import feedback_guard as _guard
from . import feedback_memory as _fmem
from . import reply_split as _split
from . import sanitize as _sanitize
from . import schema as _schema
from .pipeline import Stage

STAGE_NAMES = (
    "perceive", "memory", "bio", "decide", "expr_state", "expr_tone",
    "expr_intent", "think", "parse", "feedback", "present",
)


# ---------------------------------------------------------------- helpers
def _meta(ctx):
    meta = ctx.get("meta")
    return dict(meta) if isinstance(meta, dict) else {}


def _now(ctx):
    meta = _meta(ctx)
    for key in ("now", "clock_ts"):
        try:
            if meta.get(key) is not None:
                return float(meta[key])
        except Exception:
            continue
    return 0.0


def _rng(ctx):
    return _meta(ctx).get("rng")


def _text(ctx):
    text = ctx.get("text")
    if text:
        return str(text)
    event = ctx.get("event")
    for attr in ("message_str", "message", "text"):
        value = getattr(event, attr, None)
        if isinstance(value, str) and value:
            return value
    req = ctx.get("req")
    value = getattr(req, "prompt", None)
    if isinstance(value, str) and value:
        return value
    return ""


def _event_attr(event, *names):
    for name in names:
        try:
            getter = getattr(event, name, None)
            value = getter() if callable(getter) else getter
        except Exception:
            value = None
        if value:
            return str(value)
    return None


def _snapshot(ctx):
    snapshot = ctx.get("state")
    if isinstance(snapshot, dict) and snapshot:
        return snapshot
    core = ctx.get("core")
    getter = getattr(core, "snapshot", None)
    if callable(getter):
        try:
            value = getter()
            if isinstance(value, dict):
                return value
        except Exception:
            return {}
    return {}


def _skip(meta, stage, reason):
    meta = dict(meta or {})
    rows = list(meta.get("skipped") or [])
    rows.append({"stage": str(stage), "reason": str(reason)})
    meta["skipped"] = rows
    return meta


def _patch_meta(ctx, meta, **extra):
    merged = dict(meta or {})
    merged.update(extra)
    return merged


# ---------------------------------------------------------------- stages
def perceive(**opts):
    """Normalise the incoming event/message into ctx.text/user/umo."""

    def run(ctx):
        text = _text(ctx)
        user = ctx.get("user")
        umo = ctx.get("umo")
        event = ctx.get("event")
        if user is None and event is not None:
            user = _event_attr(event, "get_sender_id", "sender_id", "user_id")
        if umo is None and event is not None:
            umo = _event_attr(event, "unified_msg_origin", "umo")
        meta = _meta(ctx)
        meta["perceive"] = {"chars": len(text), "has_text": bool(text)}
        if not text:
            meta = _skip(meta, "perceive", "empty_text")
        return {"text": text, "user": user, "umo": umo, "meta": meta}

    return Stage("perceive", run, required=True, timeout_ms=200, **opts)


def memory(**opts):
    """Select memories for the prompt (decay-aware) and optionally touch one."""

    def run(ctx):
        meta = _meta(ctx)
        entries = ctx.get("memory")
        if not isinstance(entries, list) or not entries:
            return {"memory_entries": [], "memory_selected": [], "memory_skipped": [],
                    "meta": _skip(meta, "memory", "no_entries")}
        now = _now(ctx)
        limit = int(meta.get("memory_limit") or 4)
        picked = _fmem.select_for_prompt(entries, limit=limit, now=now, rng=_rng(ctx))
        touched = entries
        touch_id = meta.get("touch_id")
        if touch_id:
            touched = (_fmem.touch(entries, touch_id, now).get("entries") or entries)
        selected = picked.get("selected") or []
        meta["memory"] = {"selected": len(selected), "limit": limit}
        return {"memory_entries": touched, "memory_selected": selected,
                "memory_skipped": picked.get("skipped") or [], "meta": meta}

    return Stage("memory", run, required=False, timeout_ms=300, **opts)


def bio(**opts):
    """Observe + attribution + social_pain, then apply deltas through the guard."""

    def run(ctx):
        meta = _meta(ctx)
        core = ctx.get("core")
        text = _text(ctx)
        now = _now(ctx)
        if meta.get("observe") and core is not None and text:
            observe = getattr(core, "observe", None)
            if callable(observe):
                try:
                    observe(text)
                except Exception:
                    meta = _skip(meta, "bio", "observe_failed")
        state = _snapshot(ctx)
        if not isinstance(state, dict) or not state:
            return {"bio_state": {}, "bio": {}, "meta": _skip(meta, "bio", "no_state")}
        state = dict(state)
        attribution = {}
        try:
            attribution = _attrib.infer(event=ctx.get("event"), conversation_hint=text) or {}
        except Exception:
            attribution = {}
        deltas = {}
        try:
            deltas.update(_attrib.apply(state, attribution, now) or {})
        except Exception:
            pass
        social_event = meta.get("social_event")
        if social_event:
            current = state.get("social_pain")
            if not isinstance(current, dict):
                current = _initial_social_pain(now)
            try:
                state["social_pain"] = _social_pain_update(current, social_event, now)
            except Exception:
                pass
        extra = ctx.get("deltas")
        if isinstance(extra, dict):
            for key, value in extra.items():
                deltas.setdefault(key, value)
        verdict = {"accepted": {}, "rejected": [], "audit": []}
        if deltas:
            try:
                verdict = _guard.vet(deltas, state, str(meta.get("source") or "llm"), now,
                                     seen=state.get("_seen"))
                accepted = verdict.get("accepted") or {}
                if accepted:
                    applied = _guard.apply(state, accepted)
                    state = applied.get("state") or state
            except Exception:
                verdict = {"accepted": {}, "rejected": [], "audit": []}
        if meta.get("write_core") and core is not None:
            load_state = getattr(core, "load_state", None)
            if callable(load_state):
                try:
                    load_state(state)
                except Exception:
                    meta = _skip(meta, "bio", "write_core_failed")
        meta["bio"] = {"attribution": attribution,
                       "accepted": sorted((verdict.get("accepted") or {}).keys()),
                       "rejected": verdict.get("rejected") or []}
        return {"state": state, "bio_state": state, "bio": meta["bio"], "meta": meta}

    return Stage("bio", run, required=False, timeout_ms=400, **opts)


def _initial_social_pain(now):
    try:
        from . import social_pain as module
        return module.initial(now)
    except Exception:
        return {"value": 0.0, "last_event": "", "last_event_ts": float(now),
                "last_decay_ts": float(now), "last_value": 0.0}


def _social_pain_update(state, event_type, now):
    from . import social_pain as module
    return module.update(state, event_type, now)


def decide(**opts):
    """Whether this turn needs a reply at all (read-only decision)."""

    def run(ctx):
        meta = _meta(ctx)
        current = ctx.get("decision")
        if isinstance(current, dict):
            return {}
        text = _text(ctx)
        reply = bool(text) and meta.get("force_skip_reply") is not True
        decision = {"reply": reply, "reason": "text" if text else "empty_text"}
        if not reply:
            meta = _skip(meta, "decide", "empty_text")
        return {"decision": decision, "meta": meta}

    return Stage("decide", run, required=True, timeout_ms=100, **opts)


def expr_state(**opts):
    """Render the expression-layer state block from the core snapshot."""

    def run(ctx):
        meta = _meta(ctx)
        snapshot = _snapshot(ctx)
        if not snapshot:
            return {"state_text": "", "meta": _skip(meta, "expr_state", "no_state")}
        budget = int(meta.get("state_budget") or 600)
        try:
            rendered = _expr_state.render_state_block(
                snapshot, relationship=meta.get("relationship"), now=_now(ctx),
                budget_chars=budget)
        except Exception:
            return {"state_text": "", "meta": _skip(meta, "expr_state", "render_failed")}
        text = str((rendered or {}).get("text") or "")
        meta["expr_state"] = {"chars": len(text),
                              "parts": (rendered or {}).get("parts_used") or []}
        if not text:
            meta = _skip(meta, "expr_state", "empty_block")
        return {"state_text": text, "meta": meta}

    return Stage("expr_state", run, required=False, timeout_ms=300, **opts)


def expr_tone(**opts):
    """Derive tone instructions from action tendency / emotion."""

    def run(ctx):
        meta = _meta(ctx)
        snapshot = _snapshot(ctx)
        try:
            intensity = float(snapshot.get("intensity") or 0.5)
        except Exception:
            intensity = 0.5
        emotion = str(snapshot.get("emotion") or "calm")
        self_esteem = snapshot.get("self_esteem")
        try:
            _dist = _emotion_geometry.classify(snapshot)
        except Exception:
            _dist = {}
        tone = _expr_tone.tone_block(
            meta.get("action_tendency") or "", emotion=emotion,
            intensity=intensity, self_esteem=self_esteem,
            regulation=snapshot.get("regulation"),
            probs=_dist.get("probs"))
        meta["expr_tone"] = {"tendency": tone.get("tendency"),
                             "chars_mult": tone.get("chars_mult"),
                             "mixed": bool(tone.get("mixed")),
                             "top1": tone.get("top1"), "top2": tone.get("top2"),
                             "dist": _dist.get("probs")}
        return {"tone": tone, "meta": meta}

    return Stage("expr_tone", run, required=False, timeout_ms=200, **opts)


def expr_intent(**opts):
    """Pick the intent for this turn from injected candidates."""

    def run(ctx):
        meta = _meta(ctx)
        candidates = meta.get("intent_candidates")
        if not isinstance(candidates, list) or not candidates:
            return {"intent": {"kind": "", "text_hint": "", "weight": 0.0,
                               "alternatives": []},
                    "meta": _skip(meta, "expr_intent", "no_candidates")}
        state = {"now": _now(ctx),
                 "recent_kinds": meta.get("recent_kinds") or [],
                 "bid_frequency": meta.get("bid_frequency", 1.0),
                 "responsiveness": meta.get("responsiveness", 0.5),
                 "attachment_mode": meta.get("attachment_mode")}
        intent = _expr_intent.pick_intent(candidates, state=state, rng=_rng(ctx))
        meta["expr_intent"] = {"kind": intent.get("kind"), "weight": intent.get("weight")}
        return {"intent": intent, "meta": meta}

    return Stage("expr_intent", run, required=False, timeout_ms=100, **opts)


def think(**opts):
    """Call the injected llm(ctx-or-prompt); no llm means a clean no-op."""

    def run(ctx):
        meta = _meta(ctx)
        llm = ctx.get("llm")
        if not callable(llm):
            llm = meta.get("llm")
        if not callable(llm):
            return {"llm_raw": str(ctx.get("llm_raw") or ""),
                    "meta": _skip(meta, "think", "no_llm")}
        prompt = ctx.get("prompt")
        if not prompt:
            relationship = ctx.get("relationship_text") or ""
            if not relationship:
                try:
                    relationship = str(_expr_state._section_relationship(
                        meta.get("relationship") or ctx.get("relationship")) or "")
                except Exception:
                    relationship = ""
            if relationship and "关系" in str(ctx.get("state_text") or ""):
                relationship = ""
            gap = str(ctx.get("gap_text") or meta.get("gap_text") or "")
            _legend = str(ctx.get("numeric_legend") or "")
            if not _legend:
                try:
                    _legend = _schema.numeric_legend(_snapshot(ctx))
                except Exception:
                    _legend = ""
            ctx_for_template = {"state_block": ctx.get("state_text") or "",
                                "relationship": relationship, "gap": gap,
                                "recent_proactive": str(ctx.get("recent_proactive") or ""),
                                "numeric_legend": _legend}
            try:
                prompt = _expr_template.build_reply(
                    snapshot=_snapshot(ctx), state_ctx=ctx_for_template,
                    intent=ctx.get("intent") or meta.get("intent"),
                    tone=ctx.get("tone"), guard=ctx.get("guard"),
                    opts=meta.get("template_opts") or {})
            except Exception:
                prompt = ctx.get("state_text") or ""
        meta["think"] = {"called": True}
        try:
            raw = llm(prompt)
        except Exception as exc:
            meta["think"]["error"] = type(exc).__name__
            meta = _skip(meta, "think", "llm_error")
            return {"llm_raw": "", "meta": meta}
        return {"prompt": prompt, "llm_raw": str(raw or ""), "meta": meta}

    return Stage("think", run, required=False, timeout_ms=20000, **opts)


def _parse_response():
    for module_name in ("..interpretation", "interpretation"):
        try:
            module = __import__(module_name, fromlist=["parse_response"])
        except Exception:
            continue
        getter = getattr(module, "parse_response", None)
        if callable(getter):
            return getter
    return None


def parse(**opts):
    """Split hidden protocol from the visible reply (interpretation layer)."""

    def run(ctx):
        meta = _meta(ctx)
        raw = str(ctx.get("llm_raw") or "")
        if not raw:
            return {"reply": str(ctx.get("reply") or ""),
                    "meta": _skip(meta, "parse", "no_llm_raw")}
        parser = _parse_response()
        if parser is None:
            meta = _skip(meta, "parse", "interpretation_unavailable")
            return {"reply": raw, "meta": meta}
        try:
            visible, update = parser(raw)
        except Exception:
            return {"reply": raw, "meta": _skip(meta, "parse", "parse_failed")}
        meta["parse"] = {"has_update": bool(update)}
        return {"reply": str(visible or ""), "parsed": update, "meta": meta}

    return Stage("parse", run, required=False, timeout_ms=300, **opts)


def feedback(**opts):
    """Gate every biological delta through feedback_guard.vet + apply."""

    def run(ctx):
        meta = _meta(ctx)
        deltas = ctx.get("parsed")
        if not isinstance(deltas, dict) or not deltas:
            deltas = meta.get("feedback_deltas")
        if not isinstance(deltas, dict) or not deltas:
            return {"feedback": {"accepted": {}, "rejected": [], "reason": "no_deltas"},
                    "meta": _skip(meta, "feedback", "no_deltas")}
        state = ctx.get("bio_state")
        if not isinstance(state, dict):
            state = ctx.get("state")
        state = dict(state) if isinstance(state, dict) else {}
        source = str(meta.get("feedback_source") or "llm")
        seen = meta.get("feedback_seen")
        verdict = _guard.vet(deltas, state, source, _now(ctx),
                             seen=seen if isinstance(seen, dict) else None)
        accepted = verdict.get("accepted") or {}
        applied = _guard.apply(state, accepted) if accepted else {"state": state,
                                                                  "changed": []}
        meta["feedback"] = {"accepted": sorted(accepted.keys()),
                            "rejected": len(verdict.get("rejected") or []),
                            "idempotent": bool(verdict.get("idempotent"))}
        return {"feedback": verdict, "deltas": accepted,
                "bio_state": applied.get("state") or state,
                "state": applied.get("state") or state, "meta": meta}

    return Stage("feedback", run, required=False, timeout_ms=200, **opts)


def present(**opts):
    """Sanitize the final reply and split it into legal segments."""

    def run(ctx):
        meta = _meta(ctx)
        raw = str(ctx.get("reply") or "")
        if not raw:
            return {"reply": "", "segments": [],
                    "meta": _skip(meta, "present", "no_reply")}
        cleaned = _sanitize.clean(raw)
        if not isinstance(cleaned, str):
            cleaned = str(cleaned or "")
        try:
            segments = _split.split_reply(cleaned, meta.get("split_cfg"))
        except Exception:
            segments = [cleaned]
        if not segments:
            segments = [cleaned]
        meta["present"] = {"sanitized": cleaned != raw, "segments": len(segments)}
        return {"reply": cleaned, "segments": segments, "meta": meta}

    return Stage("present", run, required=True, timeout_ms=300, **opts)


def build_stages(**opts):
    """All stage wrappers in mainline order (factory, not the runtime default)."""
    return [perceive(**opts), memory(**opts), bio(**opts), decide(**opts),
            expr_state(**opts), expr_tone(**opts), expr_intent(**opts),
            think(**opts), parse(**opts), feedback(**opts), present(**opts)]
