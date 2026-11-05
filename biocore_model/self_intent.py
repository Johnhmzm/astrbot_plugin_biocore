# -*- coding: utf-8 -*-
"""L2 self layer: decide what *she* wants this turn.

The biological layer computes the body (affect, needs, tension). The expression
layer only executes. Between them sits "what she wants right now": asking for
company, keeping to herself, turning a topic down, going along with him, or
saying the honest thing instead of the polite one.

Design follows docs/SELF-LAYER-DESIGN.md plus four points taken from the
literature:
  1. candidate actions are enumerated first (2-4 things she could do right
     now), then one (or two) is selected by drive x self_weight, instead of
     emitting bare weights (Desire-driven Autonomy, D2A 2024);
  2. every turn carries a one-line motivation (<= 20 chars) for logs/panels;
  3. satisfaction is current - expected, and the expectation dict drifts
     slowly with every call (ASVO 2026), not 1 - need;
  4. self-weight drifts between altruistic and self-oriented, computed from
     self satisfaction vs the probe's estimate of the other side's state
     (SVO / ASVO 2026).

Pure functions only: no IO, no clock, no host imports, no LLM calls, and no
prompt text. The module never imports main.py.
"""
from __future__ import annotations

import math

NEED_KEYS = ("belonging", "self_esteem", "control", "meaningful_existence")
# Deci & Ryan 2000, Psychological Inquiry 11(4):227-268: the basic needs have
# equal standing, so every slot weighs the same instead of .30/.25/.20/.25.
NEED_WEIGHTS = {"belonging": 0.25, "self_esteem": 0.25,
                "control": 0.25, "meaningful_existence": 0.25}
KINDS = ("要你陪", "自己待着", "拒绝话题", "顺着你", "说真话")

# Expectations start near the "just fine" line and drift with experience.
DEFAULT_EXPECTED = {
    "belonging": 0.55,
    "self_esteem": 0.55,
    "control": 0.60,
    "meaningful_existence": 0.55,
}
EXPECTED_RATE = 0.03          # per-call drift, never a jump
SELF_WEIGHT_FLOOR = 0.10
SELF_WEIGHT_CEIL = 0.90
MIN_WEIGHT = 0.15             # [engineering] intents below this are dropped
MAX_INTENTS = 2               # [engineering]
MAX_CANDIDATES = 4
SELF_HANDLE_URGE = 0.35       # below this she tends to handle it herself
OPEN_UP_URGE = 0.50           # above this she tends to ask / speak up
SILENCE_FULL_SECONDS = 6 * 3600.0


def _clamp(value, low=0.0, high=1.0):
    try:
        num = float(value)
    except Exception:
        return low
    if num != num:  # NaN
        return low
    if num < low:
        return low
    if num > high:
        return high
    return num


def _num(mapping, key, default=0.0):
    """Bounded float read; 0.0 is a legal value (never treated as missing)."""
    if not isinstance(mapping, dict) or key not in mapping:
        return float(default)
    try:
        num = float(mapping.get(key))
    except Exception:
        return float(default)
    if num != num or num in (float("inf"), float("-inf")):
        return float(default)
    return num


def expected_state(current_expected, needs):
    """Slow drift: the expectation follows experience, never jumps."""
    base = dict(DEFAULT_EXPECTED)
    if isinstance(current_expected, dict):
        for key in NEED_KEYS:
            base[key] = _clamp(_num(current_expected, key, base[key]))
    out = {}
    for key in NEED_KEYS:
        now = _clamp(_num(needs, key, base[key]))
        out[key] = round(_clamp(base[key] + EXPECTED_RATE * (now - base[key])), 4)
    return out


def satisfaction(needs, expected):
    """Per-need current - expected, plus the bounded mean."""
    per = {}
    for key in NEED_KEYS:
        diff = _clamp(_num(needs, key, 0.5)) - _clamp(_num(expected, key, 0.5))
        per[key] = round(max(-1.0, min(1.0, diff)), 4)
    mean = sum(per[key] for key in NEED_KEYS) / float(len(NEED_KEYS))
    return per, round(max(-1.0, min(1.0, mean)), 4)


def _other_satisfaction(other_estimate):
    """Estimate how the other side is doing, from the probe's dims only."""
    if not isinstance(other_estimate, dict) or not other_estimate:
        return 0.0
    valence = _num(other_estimate, "v", _num(other_estimate, "other_valence_est", 0.0))
    stress = _num(other_estimate, "stress", 0.0)
    hurt = max(_num(other_estimate, "hit", 0.0), _num(other_estimate, "blame", 0.0))
    value = 0.60 * valence - 0.30 * stress - 0.20 * hurt
    return round(max(-1.0, min(1.0, value)), 4)


def drive(needs):
    """Need-gap drive: weighted sum of (1 - need), in [0, 1]."""
    total = 0.0
    for key in NEED_KEYS:
        total += NEED_WEIGHTS[key] * (1.0 - _clamp(_num(needs, key, 0.6)))
    return round(_clamp(total), 4)


def self_weight(self_satisfaction, other_satisfaction, closeness, trust, stress):
    """SVO-style balance: f(closeness, trust, stress) + self vs other payoff."""
    base = (0.25
            + 0.35 * _clamp(closeness)
            + 0.20 * _clamp(trust)
            - 0.25 * _clamp(stress))
    balance = 0.15 * (float(self_satisfaction) - float(other_satisfaction))
    return round(max(SELF_WEIGHT_FLOOR, min(SELF_WEIGHT_CEIL, base + balance)), 4)


def gaps(needs, expected):
    """Normalized need deficits in [0, 1] (need gap + half expectation gap)."""
    out = {}
    for key in NEED_KEYS:
        raw = (1.0 - _clamp(_num(needs, key, 0.5))
               + 0.5 * (1.0 - _clamp(_num(expected, key, 0.5))))
        out[key] = round(_clamp(raw / 1.5), 4)
    return out


def silence_factor(silence_seconds):
    """0 at the last message, 1 after SILENCE_FULL_SECONDS (log-shaped)."""
    try:
        seconds = max(0.0, float(silence_seconds))
    except Exception:
        seconds = 0.0
    if seconds <= 0.0:
        return 0.0
    return round(_clamp(math.log1p(seconds) / math.log1p(SILENCE_FULL_SECONDS)), 4)


def _derive_needs(snapshot):
    """Fallback needs from the state snapshot when core.needs is unavailable."""
    social = _clamp(_num(snapshot, "social", 0.55))
    trust = _clamp(_num(snapshot, "trust", 0.55))
    stress = _clamp(_num(snapshot, "stress", 0.30))
    energy = _clamp(_num(snapshot, "energy", 0.55))
    boredom = _clamp(_num(snapshot, "boredom", 0.0))
    attention = _clamp(_num(snapshot, "attention", 0.50))
    return {
        "belonging": round(_clamp(0.50 + 0.40 * social - 0.20 * stress), 4),
        "self_esteem": round(_clamp(0.50 + 0.40 * trust - 0.20 * stress), 4),
        "control": round(_clamp(0.50 + 0.40 * (1.0 - stress)
                                + 0.20 * (energy - 0.5)), 4),
        "meaningful_existence": round(_clamp(0.50 + 0.30 * (1.0 - boredom)
                                             + 0.20 * attention), 4),
    }


def _needs_state(needs, snapshot):
    provided = isinstance(needs, dict) and any(key in needs for key in NEED_KEYS)
    derived = _derive_needs(snapshot)
    source = needs if provided else {}
    return {key: round(_clamp(_num(source, key, derived[key])), 4)
            for key in NEED_KEYS}


def candidates(context):
    """Enumerate 2-4 things she could do right now, scored by drive x weight."""
    context = context if isinstance(context, dict) else {}
    gap = context.get("gaps") if isinstance(context.get("gaps"), dict) else {}
    weight = _clamp(context.get("self_weight", 0.5))
    closeness = _clamp(context.get("closeness", 0.5))
    conflict = _clamp(context.get("conflict", 0.0))
    stress = _clamp(context.get("stress", 0.3))
    energy = _clamp(context.get("energy", 0.6))
    boundary = _clamp(context.get("boundary_pressure", 0.0))
    silence = silence_factor(context.get("silence_seconds", 0.0))
    drive_v = _clamp(context.get("drive", 0.4))
    urge = _clamp(context.get("urge", drive_v * weight))
    gap_belonging = _clamp(gap.get("belonging", 0.0))
    gap_esteem = _clamp(gap.get("self_esteem", 0.0))

    acquire = (0.55 * gap_belonging + 0.25 * closeness + 0.20 * silence)
    hold = (0.40 * (1.0 - energy) + 0.30 * stress
            + 0.30 * _clamp((urge - 0.20) / 0.50))
    refuse = (0.45 * conflict + 0.30 * boundary
              + 0.25 * stress * (1.0 - closeness))
    comply = ((1.0 - urge) * (0.55 + 0.45 * closeness)
              * (1.0 - 0.5 * conflict) * (0.55 + 0.45 * energy))
    honest = 0.40 * urge + 0.35 * gap_esteem + 0.25 * boundary

    # Drive x weight routes the two regimes from the design doc.
    if urge >= OPEN_UP_URGE:
        acquire += 0.10
        honest += 0.10
    elif urge <= SELF_HANDLE_URGE:
        hold += 0.10
        comply += 0.10
    # Refusal only becomes a candidate when the interaction is actually tense.
    if conflict < 0.30 and boundary < 0.25:
        refuse *= 0.50

    rows = [
        {"kind": "要你陪", "score": _clamp(acquire)},
        {"kind": "自己待着", "score": _clamp(hold)},
        {"kind": "拒绝话题", "score": _clamp(refuse)},
        {"kind": "顺着你", "score": _clamp(comply)},
        {"kind": "说真话", "score": _clamp(honest)},
    ]
    rows.sort(key=lambda row: row["score"], reverse=True)
    out = []
    for row in rows[:MAX_CANDIDATES]:
        out.append({"kind": row["kind"], "score": round(row["score"], 4)})
    return out


REASONS = {
    "要你陪": "有点空，想听你说两句",
    "自己待着": "现在累，想静一会儿",
    "拒绝话题": "这个话题不想聊",
    "顺着你": "还行，跟着他说",
    "说真话": "忍着不如说实话",
}


def _motivation(top_kind):
    if top_kind == "要你陪":
        return "想让他陪一会儿"
    if top_kind == "自己待着":
        return "想自己待会儿"
    if top_kind == "拒绝话题":
        return "这个话题先不接"
    if top_kind == "说真话":
        return "不想绕，想说真话"
    return "先顺着他"


def select(context, minimum=MIN_WEIGHT):
    """Pick at most two intents and normalize their weights to exactly 1."""
    rows = candidates(context)
    try:
        threshold = float(minimum)
    except Exception:
        threshold = MIN_WEIGHT
    picked = [row for row in rows if row["score"] >= threshold][:MAX_INTENTS]
    if not picked:
        picked = [{"kind": "顺着你", "score": 0.5}]
    total = sum(row["score"] for row in picked) or 1.0
    intents = []
    acc = 0.0
    for index, row in enumerate(picked):
        if index == len(picked) - 1:
            weight = round(max(0.0, 1.0 - acc), 3)
        else:
            weight = round(row["score"] / total, 3)
            acc += weight
        intents.append({"kind": row["kind"],
                        "weight": weight,
                        "reason": REASONS.get(row["kind"], "")})
    # Rounding can still leave 0.999/1.001 exactly for two intents; the last
    # weight above already absorbs it, this is a defensive final pass.
    diff = round(1.0 - sum(item["weight"] for item in intents), 3)
    if diff and intents:
        intents[-1]["weight"] = round(
            max(0.0, min(1.0, intents[-1]["weight"] + diff)), 3)
    return intents


def evaluate(snapshot=None, relationship=None, needs=None, other_estimate=None,
             expected=None, flags=None, silence_seconds=0.0):
    """One turn of the self layer.

    Returns a dict:
      intents        list of {kind, weight, reason}; weights sum to 1
      top            first intent kind
      motivation     <= 20 chars, for logs and panels
      self_weight    SVO-style balance in [0.1, 0.9]
      satisfaction   current - expected (bounded mean)
      expected       drifted expectations to pass back next call
      drive / urge   need-gap drive and drive x self_weight
      candidates     2-4 "things I could do now", highest score first
    """
    flags = flags if isinstance(flags, dict) else {}
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    relationship = relationship if isinstance(relationship, dict) else {}
    enabled = bool(flags.get("enabled", True))

    needs_state = _needs_state(needs, snapshot)
    exp = expected_state(expected, needs_state)
    per_need, sat = satisfaction(needs_state, exp)
    other_sat = _other_satisfaction(other_estimate)

    state = relationship.get("state") if isinstance(relationship.get("state"), dict) else relationship
    closeness = _clamp(_num(state, "closeness", _num(state, "intimacy", 0.5)))
    trust = _clamp(_num(state, "trust", _num(snapshot, "trust", 0.5)))
    conflict = _clamp(_num(state, "conflict", 0.0))
    stress = _clamp(_num(snapshot, "stress", 0.3))
    energy = _clamp(_num(snapshot, "energy", 0.6))
    boundary = _clamp(_num(snapshot, "boundary_pressure", 0.0))
    try:
        silence = max(0.0, float(silence_seconds))
    except Exception:
        silence = 0.0

    weight = self_weight(sat, other_sat, closeness, trust, stress)
    drive_v = drive(needs_state)
    urge = round(_clamp(drive_v * weight), 4)
    gap = gaps(needs_state, exp)

    context = {
        "needs": needs_state, "expected": exp, "gaps": gap,
        "self_weight": weight, "drive": drive_v, "urge": urge,
        "closeness": closeness, "trust": trust, "conflict": conflict,
        "stress": stress, "energy": energy, "boundary_pressure": boundary,
        "silence_seconds": silence,
    }
    intents = select(context)
    top = intents[0]["kind"] if intents else "顺着你"
    motivation = _motivation(top)[:20]
    if not enabled:
        intents = [{"kind": "顺着你", "weight": 1.0, "reason": "自我层关闭"}]
        top = "顺着你"
        motivation = "先顺着他"
    return {
        "enabled": enabled,
        "intents": intents,
        "top": top,
        "motivation": motivation,
        "self_weight": weight,
        "satisfaction": sat,
        "satisfaction_by_need": per_need,
        "self_satisfaction": sat,
        "other_satisfaction": other_sat,
        "expected": exp,
        "drive": drive_v,
        "urge": urge,
        "gaps": gap,
        "candidates": (candidates(context) if enabled else []),
        "silence_seconds": round(silence, 3),
    }


def directives(result):
    """Translate intents into bounded hints for the expression layer.

    These are numeric directives (length scale / initiative) the expression
    layer applies to its own length rules; no prompt text is produced here.
    """
    if not isinstance(result, dict) or not result.get("enabled", True):
        return {"length_scale": 1.0, "tone": "", "initiative": 0.0,
                "kind": "顺着你", "weight": 0.0}
    top = result.get("top") or "顺着你"
    weight = 0.0
    for item in result.get("intents") or []:
        if isinstance(item, dict) and item.get("kind") == top:
            weight = _clamp(item.get("weight", 0.0))
            break
    table = {
        "要你陪": {"length_scale": 1.15, "tone": "可以主动问一句", "initiative": 0.8},
        "自己待着": {"length_scale": 0.80, "tone": "话少一点", "initiative": 0.1},
        "拒绝话题": {"length_scale": 0.85, "tone": "这个不想聊就直说", "initiative": 0.2},
        "顺着你": {"length_scale": 1.0, "tone": "", "initiative": 0.4},
        "说真话": {"length_scale": 1.05, "tone": "说实话，不用绕", "initiative": 0.6},
    }
    base = dict(table.get(top, table["顺着你"]))
    base["kind"] = top
    base["weight"] = round(weight, 3)
    base["length_scale"] = round(float(base["length_scale"]), 3)
    base["initiative"] = round(
        float(base.get("initiative", 0.4)) * (0.5 + 0.5 * weight), 3)
    return base


def payload(result, pending_prompts=None, voice_phrases=None, metacog=None):
    """Bounded read-only projection for the dashboard (no IO, no prompt text)."""
    out = {
        "enabled": True,
        "top": "顺着你",
        "top_weight": 0.0,
        "self_weight": 0.5,
        "motivation": "",
        "intents": [],
        "pending_prompts": [],
        "voice_phrases": [],
        "metacog": {},
    }
    if isinstance(result, dict):
        out["enabled"] = bool(result.get("enabled", True))
        out["top"] = str(result.get("top") or "顺着你")[:8]
        out["self_weight"] = round(
            max(SELF_WEIGHT_FLOOR,
                min(SELF_WEIGHT_CEIL, _num(result, "self_weight", 0.5))), 3)
        out["motivation"] = str(result.get("motivation") or "")[:20]
        intents = []
        for item in (result.get("intents") or [])[:MAX_INTENTS]:
            if not isinstance(item, dict):
                continue
            intents.append({
                "kind": str(item.get("kind") or "")[:8],
                "weight": round(_clamp(_num(item, "weight", 0.0)), 3),
                "reason": str(item.get("reason") or "")[:40],
            })
        out["intents"] = intents
        out["top_weight"] = intents[0]["weight"] if intents else 0.0
    prompts = []
    for item in (pending_prompts or [])[:3] if isinstance(pending_prompts, (list, tuple)) else []:
        text = str(item or "").strip()[:60]
        if text:
            prompts.append(text)
    out["pending_prompts"] = prompts
    phrases = []
    for item in (voice_phrases or [])[:2] if isinstance(voice_phrases, (list, tuple)) else []:
        text = str(item or "").strip()[:20]
        if text:
            phrases.append(text)
    out["voice_phrases"] = phrases
    if isinstance(metacog, dict):
        out["metacog"] = {
            "band": str(metacog.get("band") or "")[:8],
            "confidence": round(_clamp(_num(metacog, "confidence", 0.6)), 3),
            "converge": bool(metacog.get("converge", False)),
            "allow_self_correction": bool(
                metacog.get("allow_self_correction", False)),
            "low_streak": int(max(0.0, _num(metacog, "low_streak", 0.0))),
            "reason": str(metacog.get("reason") or "")[:40],
        }
    return out
