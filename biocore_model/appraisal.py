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
# [engineering] per-turn output caps, hand-tuned.
CAPS = {"v": 0.15, "a": 0.15, "d": 0.10, "social": 0.05,
        "trust": 0.05, "stress": 0.10, "self_esteem": 0.05}
# appraisal_v2 (default ON): v is goal + an explicit valence signal only.
# blame goes to trust/conflict, hit to stress/self_esteem, and control /
# certainty / novelty / involve each keep their own output line. The old 7x7
# mapping stays reachable with BIOCORE_APPRAISAL_V2=0 or flags["appraisal_v2"].
SWITCH_KEY = "appraisal_v2"
ENV_KEY = "BIOCORE_APPRAISAL_V2"
PROBE_MIN_CONFIDENCE = 0.4
WHY_MAX = 40
INVOLVE_GAIN = 0.5
# item-1/item-2 contract additions (same call, no extra request):
#   fact      - long-lived info about the user (<= 20 chars), optional
#   situation - intent strength (0..1 numbers, not labels)
FACT_MAX_CHARS = 20
SITUATION_KEYS = ("challenge", "praise", "hurt")

# 7 x 7 W matrix: WEIGHTS[dimension][output] = weight. [engineering] the
# dimension names follow Scherer 2001 / OCC, but no row below is fitted or
# transcribed from a paper (see PAPER-MAP.md).
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

# v2 destination table. Every dimension has exactly one home (goal and the
# explicit valence signal own v); nothing is folded into v a second time.
V2_WEIGHTS = {
    "v": {"goal": 0.60, "valence": 0.40},
    "a": {"novelty": 0.25, "involve": 0.10, "hit": 0.20},
    "d": {"control": 0.45, "goal": 0.20},
    "social": {"involve": 0.20, "hit": -0.30},
    "trust": {"goal": 0.15, "blame": -0.30},
    "conflict": {"blame": 0.35, "hit": 0.10},
    "stress": {"blame": 0.15, "hit": 0.30},
    "self_esteem": {"goal": 0.20, "hit": -0.30},
}
V2_OUTPUTS = ("v", "a", "d", "social", "trust", "conflict", "stress",
              "self_esteem")
V2_CAPS = dict(CAPS, conflict=0.15)


def enabled(flags=None, env=None):
    """appraisal_v2: explicit flag > nested switches > env > default ON."""
    import os
    data = flags if isinstance(flags, dict) else {}
    if isinstance(data.get(SWITCH_KEY), bool):
        return data[SWITCH_KEY]
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    if isinstance(switches.get(SWITCH_KEY), bool):
        return switches[SWITCH_KEY]
    environ = env if hasattr(env, "get") else os.environ
    raw = str(environ.get(ENV_KEY) or "").strip().lower()
    if raw in ("0", "false", "off", "no"):
        return False
    return True
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


def build_prompt(user_text, reply_text="") -> str:
    """One combined appraisal: dims + intent strength + optional durable fact."""
    return (
        "下面是对方说的话，和你的回复。\n"
        "用 JSON 描述：①对方这句话对你意味着什么 ②你回复时的内在状态"
        " ③这句话的意图强度。\n"
        '{"dims":{"goal":0.0,"blame":0.0,"control":0.5,"certainty":0.5,'
        '"novelty":0.3,"involve":0.5,"hit":0.0},"why":"≤20字","c":0.0-1.0,'
        '"situation":{"challenge":0.0,"praise":0.0,"hurt":0.0},'
        '"fact":"他姓王（可选）"}\n'
        "goal:-1受阻..+1达成；blame:0怪我..1怪对方；control:0无力..1可控；"
        "certainty:0意外..1意料之中；novelty:0熟悉..1新鲜；"
        "involve:0无关..1关乎我；hit:0无冲击..1被击中\n"
        "situation：这句话的意图强度（0..1 的分数，不是分类标签）："
        "challenge=在质疑/质问/追问，praise=在夸/肯定，hurt=在伤人/冒犯；没有就填 0。\n"
        "fact：只有当对方透露关于他自己的长期信息（姓名/称呼/家人/住址/工作/长期偏好）"
        "时才填，≤20 字；否则省略或留空。\n"
        "对方：" + str(user_text or "")[:400] +
        ("\n你：" + str(reply_text or "")[:400] if reply_text else "")
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
    situation = {}
    raw_situation = data.get("situation")
    if isinstance(raw_situation, dict):
        for name in SITUATION_KEYS:
            value = _num(raw_situation.get(name))
            if value is None:
                continue
            situation[name] = round(_clamp(value, 0.0, 1.0), 4)
    fact = " ".join(str(data.get("fact") or "").split()).strip()
    if len(fact) > FACT_MAX_CHARS:
        fact = fact[:FACT_MAX_CHARS]
    return {"dims": dims, "why": str(data.get("why") or "").strip()[:WHY_MAX],
            "confidence": round(_clamp(confidence, 0.0, 1.0), 3),
            "situation": situation, "fact": fact,
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


def _v2_values(dims):
    """Inputs for the v2 table: the 7 dims plus an optional explicit valence."""
    dims = dims if isinstance(dims, dict) else {}
    values = {}
    for name in DIMS:
        low = -1.0 if name == "goal" else 0.0
        values[name] = _clamp(dims.get(name, 0.0), low, 1.0)
    values["valence"] = _clamp(dims.get("valence", 0.0), -1.0, 1.0)
    return values


def _appraise_v2(dims, confidence=0.5, weights=None):
    """v2 mapping: (deltas, components). Nothing is added into v twice."""
    conf = _clamp(confidence, 0.0, 1.0)
    values = _v2_values(dims)
    table = {out: dict(row) for out, row in V2_WEIGHTS.items()}
    if isinstance(weights, dict):
        for key, value in weights.items():
            if "." not in key:
                continue
            dim, output = key.split(".", 1)
            number = _num(value)
            if dim in values and output in table and number is not None:
                table[output][dim] = number
    deltas = {}
    components = {}
    for output in V2_OUTPUTS:
        rows = {}
        total = 0.0
        for name, weight in (table.get(output) or {}).items():
            part = float(weight) * values.get(name, 0.0) * conf
            if abs(part) > 1e-9:
                rows[name] = round(part, 6)
            total += part
        cap = float(V2_CAPS.get(output, 0.2))
        capped = max(-cap, min(cap, total))
        components[output] = {"rows": rows, "total": round(total, 6),
                              "capped": round(capped, 6),
                              "dropped": round(total - capped, 6)}
        if abs(capped) > 1e-9:
            deltas[output] = round(capped, 4)
    return deltas, components


def appraise(dims, confidence=0.5, weights=None, v2=None):
    """W·x scaled by confidence, bounded by per-output caps.

    v2 (default ON) uses V2_WEIGHTS: v = goal + explicit valence only, blame
    and hit go to their own outputs. v2=False is the old 7x7 mapping, byte for
    byte.
    """
    if v2 is None:
        v2 = enabled()
    if v2:
        deltas, _components = _appraise_v2(dims, confidence, weights)
        return deltas
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


def appraise_detail(dims, confidence=0.5, weights=None, v2=None):
    """Same numbers as appraise(), plus where each one came from.

    components[output][dim] is that dim's own contribution, so v/a are visible
    derived readouts instead of a black box that quietly folds blame/hit in.
    Nothing is merged: the caller can show every source line.
    """
    if v2 is None:
        v2 = enabled()
    if v2:
        deltas, components = _appraise_v2(dims, confidence, weights)
        return {"deltas": deltas, "components": components,
                "mapping": "v2",
                "derived": {"v": True, "a": False}}
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
    gain = 1.0 + INVOLVE_GAIN * values["involve"]
    components = {}
    deltas = {}
    for output in OUTPUTS:
        rows = {}
        total = 0.0
        for name in DIMS:
            part = float(w[name].get(output, 0.0)) * values[name] * gain * conf
            if abs(part) > 1e-9:
                rows[name] = round(part, 6)
            total += part
        cap = float(CAPS[output])
        capped = max(-cap, min(cap, total))
        components[output] = {"rows": rows,
                              "total": round(total, 6),
                              "capped": round(capped, 6),
                              "dropped": round(total - capped, 6)}
        if abs(capped) > 1e-9:
            deltas[output] = round(capped, 4)
    return {"deltas": deltas, "components": components,
            "mapping": "v1", "derived": {key: True for key in ("v", "a")}}


def legacy_v(dims, confidence=0.5, weights=None):
    """The old 7x7 v (v1), kept for comparison only -- never written back."""
    out = appraise(dims, confidence=confidence, weights=weights, v2=False)
    return out.get("v")


def appraise_with_legacy(dims, confidence=0.5, weights=None, v2=None):
    """{deltas, v, v_legacy, mapping} for /state.appraisal.

    With v2 on, v_legacy is what the old mapping would have produced, so the
    two can be compared without changing anything. With v2 off there is no
    second mapping and v_legacy is None.
    """
    if v2 is None:
        v2 = enabled()
    deltas = appraise(dims, confidence=confidence, weights=weights, v2=v2)
    return {"deltas": deltas,
            "v": deltas.get("v", 0.0),
            "v_legacy": legacy_v(dims, confidence, weights) if v2 else None,
            "mapping": "v2" if v2 else "v1"}


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
