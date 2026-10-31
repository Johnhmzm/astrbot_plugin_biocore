# -*- coding: utf-8 -*-
"""L2 emotion probe: model-chosen feedback deltas for one reply.

Instead of asking for a label, the second tiny call asks the model what the
reply did to its internal state and why. The module owns the prompt, parsing and
ALL local protections (whitelist, per-item clamp, per-core rate limit, low
confidence drop). It never raises and never blocks the reply.

Contract:
    {"deltas": {"v": -0.3, "a": 0.1}, "why": "<=30 chars", "c": 0.0-1.0}

Failures (timeout/empty/garbage/low confidence) return {}.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time

logger = logging.getLogger(__name__)

PROBE_TIMEOUT = 3.0
PROBE_MIN_CONFIDENCE = 0.4
DELTA_FIELDS = ("v", "a", "d", "social", "trust", "stress", "self_esteem")
DELTA_CLAMP = 0.2
RATE_WINDOW_SECONDS = 60
RATE_BUDGET = 0.4
WHY_MAX_CHARS = 30
MAX_TEXT_CHARS = 160
MAX_USER_CHARS = 80

_INSTRUCTION = (
    "用JSON描述内部状态影响：\n"
    '{"deltas":{"v":-0.3},"why":"≤30字","c":0.0-1.0}\n'
    '字段：v/a/d/social/trust/stress/self_esteem；无影响{"deltas":{}}'
)
INSTRUCTION_HINT = _INSTRUCTION

_JSON_RE = re.compile(r"\{.*\}", re.S)
_FENCE_RE = re.compile(r"\x60{3}(?:json)?\s*(.*?)\s*\x60{3}", re.S | re.I)
_RATE_STATE = {}
_FEEDBACK_FIELDS = {
    "v": "valence_delta", "a": "arousal_delta", "d": "dominance_delta",
    "social": "social_delta", "trust": "trust_delta",
    "stress": "stress_delta", "self_esteem": "self_esteem_delta",
}


def _log_raw(raw):
    """Diagnostic only: never alters behaviour, never raises."""
    try:
        logger.info("[biocore] emotion probe raw=%r", str(raw or "")[:200])
    except Exception:
        pass


def _num(value, default=None):
    try:
        return float(value)
    except Exception:
        return default


def _clamp(value, low=0.0, high=1.0):
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return low


def reset_rate():
    """Clear the per-core rate window (tests / manual reset)."""
    _RATE_STATE.clear()


def build_prompt(text, last_user_msg="") -> str:
    return (_INSTRUCTION + "\n对方刚说：" + str(last_user_msg or "")[:MAX_USER_CHARS]
            + "\n回复：" + str(text or "")[:MAX_TEXT_CHARS])


def _parse_payload(raw):
    body = str(raw or "").strip()
    if not body:
        return None
    fence = _FENCE_RE.search(body)
    if fence:
        body = fence.group(1).strip()
    for candidate in _JSON_RE.findall(body):
        try:
            data = json.loads(candidate)
        except Exception:
            repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                data = json.loads(repaired)
            except Exception:
                continue
        if isinstance(data, dict):
            return data
    return None


def _rate_limit(core, now, deltas):
    """Same core / same minute: cumulative |delta| <= RATE_BUDGET, scale down."""
    stamp = _num(now, time.time())
    window = int(stamp // RATE_WINDOW_SECONDS)
    key = str(id(core)) if core is not None else "global"
    slot = _RATE_STATE.get(key)
    if not isinstance(slot, dict) or int(slot.get("window", -1)) != window:
        slot = {"window": window, "used": 0.0}
        _RATE_STATE[key] = slot
    used = _num(slot.get("used"), 0.0)
    remaining = max(0.0, RATE_BUDGET - used)
    total = sum(abs(v) for v in deltas.values())
    if total > remaining:
        scale = (remaining / total) if total > 0 else 0.0
        deltas = {key: round(value * scale, 4) for key, value in deltas.items()
                  if abs(value * scale) > 1e-9}
    slot["used"] = round(used + sum(abs(v) for v in deltas.values()), 4)
    return deltas


def parse(raw, core=None, now=None):
    """Parse one probe response with local protections; {} on any failure."""
    try:
        data = _parse_payload(raw)
        if not isinstance(data, dict):
            _log_raw(raw)
            return {}
        confidence = _num(data.get("c", data.get("confidence")), 0.0)
        if confidence < PROBE_MIN_CONFIDENCE:
            _log_raw(raw)
            return {}
        raw_deltas = data.get("deltas")
        deltas = {}
        if isinstance(raw_deltas, dict):
            for field, value in raw_deltas.items():
                if field not in DELTA_FIELDS:
                    continue
                number = _num(value)
                if number is None:
                    continue
                number = max(-DELTA_CLAMP, min(DELTA_CLAMP, number))
                if abs(number) < 1e-9:
                    continue
                deltas[field] = round(number, 4)
        if deltas:
            deltas = _rate_limit(core, now, deltas)
        why = str(data.get("why") or "").strip()[:WHY_MAX_CHARS]
        return {"deltas": deltas, "why": why,
                "confidence": round(_clamp(confidence), 3), "source": "probe"}
    except Exception:
        return {}


async def probe(text, last_user_msg, llm_call, timeout=None,
                core=None, now=None):
    """One tiny async probe; {} on timeout/empty/garbage/error (never raises).

    timeout=None means no probe-level deadline: the provider layer owns the
    only timeout (main passes an explicit provider timeout).
    """
    try:
        prompt = build_prompt(text, last_user_msg)
        _call = llm_call(prompt)
        if timeout is None:
            raw = await _call
        else:
            raw = await asyncio.wait_for(_call, timeout=max(0.05, float(timeout)))
        if raw is None:
            _log_raw(raw)
            return {}
        if not isinstance(raw, str):
            raw = str(getattr(raw, "completion_text", "") or "")
        return parse(raw, core=core, now=now)
    except asyncio.TimeoutError:
        return {}
    except Exception:
        return {}


def to_feedback_payload(result):
    """Probe result -> feedback_llm inferred payload (expanded *_delta keys)."""
    if not isinstance(result, dict):
        return {}
    deltas = result.get("deltas")
    if not isinstance(deltas, dict) or not deltas:
        return {}
    payload = {}
    for field, value in deltas.items():
        key = _FEEDBACK_FIELDS.get(field)
        if not key:
            continue
        number = _num(value)
        if number is None:
            continue
        payload[key] = round(number, 4)
    if not payload:
        return {}
    payload["confidence"] = round(_clamp(result.get("confidence", 0.0)), 3)
    payload["source"] = "probe"
    return payload
