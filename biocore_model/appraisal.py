# -*- coding: utf-8 -*-
"""Model-rated appraisal dimensions -> bounded biological deltas.

Both model calls (reply self-reflection and user-message appraisal) emit the
same 7 dimensions. This module owns the prompt, parsing, the W matrix and the
bounded mapping into v/a/d/social/trust/stress/self_esteem.

W is a 7x7 matrix (dim x output); every cell is documented inline. The matrix
can be overridden by ui_settings.appraisal_weights (flat keys like "goal.v").

Monotonic guarantees (tested):
  goal up      -> v up; blame up -> self_esteem down & stress up
  hit up       -> social down & stress up; control up -> stress down
  involve up   -> amplifies the other dimensions (multiplicative gain)

Literature: Scherer 2001 (appraisal components), Lazarus 1991 (appraisal ->
emotion), Smith & Ellsworth 1985 (dimensions), Barrett 2017 (constructed
emotion), Carver & Scheier 1998 (goal/control loop), Bowlby 1969 (relational
hit), Gross 1998 (regulation cost).
"""
from __future__ import annotations

import asyncio
import json
import re

DIMS = ("goal", "blame", "control", "certainty", "novelty", "involve", "hit")
OUTPUTS = ("v", "a", "d", "social", "trust", "stress", "self_esteem")
CAPS = {"v": 0.15, "a": 0.15, "d": 0.10, "social": 0.05,
        "trust": 0.05, "stress": 0.10, "self_esteem": 0.05}
PROBE_MIN_CONFIDENCE = 0.4
WHY_MAX = 40
INVOLVE_GAIN = 0.5

# 7 x 7 W matrix: WEIGHTS[dimension][output] = weight.
# goal: -1 blocked .. +1 achieved -> better valence/trust, less stress.
# blame: 0 self .. 1 other -> conflict, lower self-esteem/trust, more stress.
# control: 0 powerless .. 1 in control -> dominance/self-esteem, less stress.
# certainty: 0 unexpected .. 1 expected -> calmer, slight dominance.
# novelty: 0 familiar .. 1 new -> arousal/unease.
# involve: 0 not about me .. 1 about me -> multiplies the other rows (gain),
#          plus a small direct social salience.
# hit: 0 no impact .. 1 relational/self-esteem hit -> pain, withdrawal, stress.
WEIGHTS = {
    "goal": {"v": 0.60, "a": 0.10, "d": 0.20, "social": 0.15,
             "trust": 0.15, "stress": -0.25, "self_esteem": 0.20},
    "blame": {"v": -0.25, "a": 0.20, "d": -0.15, "social": -0.15,
              "trust": -0.30, "stress": 0.30, "self_esteem": -0.35},
    "control": {"v": 0.10, "a": -0.15, "d": 0.45, "social": 0.05,
                "trust": 0.10, "stress": -0.20, "self_esteem": 0.15},
    "certainty": {"v": 0.0, "a": -0.15, "d": 0.05, "social": 0.0,
                  "trust": 0.0, "stress": -0.10, "self_esteem": 0.0},
    "novelty": {"v": 0.05, "a": 0.25, "d": -0.05, "social": 0.0,
                "trust": 0.0, "stress": 0.10, "self_esteem": 0.0},
    "involve": {"v": 0.10, "a": 0.10, "d": 0.0, "social": 0.20,
                "trust": 0.10, "stress": 0.10, "self_esteem": 0.05},
    "hit": {"v": -0.20, "a": 0.20, "d": -0.10, "social": -0.30,
            "trust": -0.25, "stress": 0.30, "self_esteem": -0.30},
}
DEFAULT_WEIGHTS = {"%s.%s" % (dim, out): weight
                   for dim, row in WEIGHTS.items() for out, weight in row.items()}
_FEEDBACK_FIELDS = {"v": "valence_delta", "a": "arousal_delta",
                    "d": "dominance_delta", "social": "social_delta",
                    "trust": "trust_delta", "stress": "stress_delta",
                    "self_esteem": "self_esteem_delta"}
_FENCE_RE = re.compile(r"\x60{3}(?:json)?\s*(.*?)\s*\x60{3}", re.S | re.I)


def _clamp(value, low, high):
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return low


def _num(value, default=None):
    try:
        return float(value)
    except Exception:
        return default


def _extract_json(raw):
    body = str(raw or "").strip()
    if not body:
        return None
    fence = _FENCE_RE.search(body)
    if fence:
        body = fence.group(1).strip()
    for match in re.findall(r"\{.*\}", body, re.S):
        try:
            data = json.loads(match)
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return None


def build_prompt(text, context="") -> str:
    return (
        "用数值评价下面这条消息对内部状态的影响，只输出 JSON：\n"
        '{"dims":{"goal":-0.6,"blame":0.8,"control":0.2,"certainty":0.5,'
        '"novelty":0.3,"involve":0.9,"hit":0.6},"why":"<=40字","c":0.8}\n'
        "goal:-1受阻..+1达成；blame:0怪我..1怪对方；control:0无力..1可控；"
        "certainty:0意外..1意料之中；novelty:0熟悉..1新鲜；"
        "involve:0无关..1关乎我；hit:0无冲击..1被击中\n"
        "消息：" + str(text or "")[:400] +
        ("\n上下文：" + str(context or "")[:300] if context else "")
    )


def parse(raw):
    """Parse model dims JSON -> {dims, why, confidence, source}; {} on failure."""
    data = _extract_json(raw)
    if not isinstance(data, dict):
        return {}
    confidence = _num(data.get("c", data.get("confidence")), 0.0)
    if confidence < PROBE_MIN_CONFIDENCE:
        return {}
    raw_dims = data.get("dims")
    if not isinstance(raw_dims, dict):
        return {}
    dims = {}
    for name in DIMS:
        if name not in raw_dims:
            continue
        value = _num(raw_dims.get(name))
        if value is None:
            continue
        low = -1.0 if name == "goal" else 0.0
        dims[name] = round(_clamp(value, low, 1.0), 4)
    if not dims:
        return {}
    return {"dims": dims, "why": str(data.get("why") or "").strip()[:WHY_MAX],
            "confidence": round(_clamp(confidence, 0.0, 1.0), 3),
            "source": "appraisal"}


async def probe(text, context, llm_call, timeout=None, core=None, now=None):
    """One model call for dims; {} on timeout/empty/garbage/error (never raises)."""
    try:
        call = llm_call(build_prompt(text, context))
        if timeout is None:
            raw = await call
        else:
            raw = await asyncio.wait_for(call, timeout=max(0.05, float(timeout)))
        if raw is None:
            return {}
        if not isinstance(raw, str):
            raw = str(getattr(raw, "completion_text", "") or "")
        return parse(raw)
    except asyncio.TimeoutError:
        return {}
    except Exception:
        return {}


def appraise(dims, confidence=0.5, weights=None):
    """W·x scaled by confidence, bounded by per-output caps."""
    dims = dims if isinstance(dims, dict) else {}
    conf = _clamp(confidence, 0.0, 1.0)
    w = {dim: dict(row) for dim, row in WEIGHTS.items()}
    if isinstance(weights, dict):
        for key, value in weights.items():
            if "." not in key:
                continue
            dim, output = key.split(".", 1)
            number = _num(value)
            if dim in w and output in w[dim] and number is not None:
                w[dim][output] = number
    values = {}
    for name in DIMS:
        low = -1.0 if name == "goal" else 0.0
        values[name] = _clamp(dims.get(name, 0.0), low, 1.0)
    # involve is a gain on the other rows (missing involve = 0 -> gain 1.0).
    gain = 1.0 + INVOLVE_GAIN * values["involve"]
    out = {}
    for output in OUTPUTS:
        total = 0.0
        for name in DIMS:
            total += float(w[name].get(output, 0.0)) * values[name]
        total = total * gain * conf
        cap = float(CAPS[output])
        total = max(-cap, min(cap, total))
        if abs(total) > 1e-9:
            out[output] = round(total, 4)
    return out


def appraise_dims(dims, weights=None):
    """Compatibility: full-confidence mapping (no confidence scaling)."""
    return appraise(dims, confidence=1.0, weights=weights)


def feedback_payload(deltas, confidence=1.0, source="appraisal"):
    """Biological deltas -> feedback_llm inferred payload (*_delta keys)."""
    if not isinstance(deltas, dict):
        return {}
    payload = {}
    for field, value in deltas.items():
        key = _FEEDBACK_FIELDS.get(field)
        number = _num(value)
        if not key or number is None:
            continue
        payload[key] = round(number, 4)
    if not payload:
        return {}
    payload["confidence"] = round(_clamp(confidence, 0.0, 1.0), 3)
    payload["source"] = source
    return payload


def needs_deltas(dims):
    """Dims -> bounded needs deltas (replaces keyword-driven needs updates)."""
    dims = dims if isinstance(dims, dict) else {}
    goal = _num(dims.get("goal"), 0.0) or 0.0
    blame = _num(dims.get("blame"), 0.0) or 0.0
    involve = _num(dims.get("involve"), 0.0) or 0.0
    hit = _num(dims.get("hit"), 0.0) or 0.0
    control = _num(dims.get("control"), 0.0) or 0.0
    out = {
        "belonging": round(_clamp(0.02 * involve - 0.02 * hit, -0.03, 0.03), 4),
        "self_esteem": round(_clamp(0.02 * goal - 0.03 * blame - 0.03 * hit,
                                    -0.05, 0.05), 4),
        "control": round(_clamp(0.02 * control + 0.01 * goal
                                - 0.02 * max(0.0, -goal), -0.04, 0.04), 4),
        "meaningful_existence": round(_clamp(0.01 * involve + 0.01 * goal,
                                             -0.02, 0.02), 4),
    }
    return {key: value for key, value in out.items() if abs(value) > 1e-9}
