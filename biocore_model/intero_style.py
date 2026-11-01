# -*- coding: utf-8 -*-
"""P1-2 interoception -> expression style (length / tone / initiative).

The four interoceptive channels (tension / warmth / heaviness / clarity, 0..1)
are felt states, not prompt text. This module is the deterministic bridge that
turns them into expression knobs the interpretation layer may use:

- length: a reply target/cap multiplier (tense, heavy or unclear -> shorter);
- tone: one short directive for the dominant felt state (or "" when calm);
- initiative: 0..1 scalar for how forward the next expression should be.

Pure functions only: no IO, no main import, no prompt text.
"""
from __future__ import annotations

CHANNELS = ("tension", "warmth", "heaviness", "clarity")
DEFAULT_INITIATIVE = 0.5
MIN_TARGET = 4
MIN_CAP = 8
MAX_CAP = 120
TONE_THRESHOLD = 0.55

TONE_LINES = {
    "tension": "先接住情绪，句子短一点",
    "heaviness": "慢一点说，别堆太多话",
    "warmth": "语气可以亲近一点",
    "clarity": "没听清就先用一句确认",
}


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return float(default)
    if number != number:
        return float(default)
    return number


def _clamp(value, low, high):
    return max(low, min(high, _num(value, 0.0)))


def _has_data(intero):
    return isinstance(intero, dict) and any(name in intero for name in CHANNELS)


def levels(intero):
    """Clamped 0..1 intero channel dict (unknown channels = 0)."""
    data = intero if isinstance(intero, dict) else {}
    return {name: round(_clamp(data.get(name, 0.0), 0.0, 1.0), 4)
            for name in CHANNELS}


def tone(intero):
    """Dominant felt-state directive, "" when nothing stands out.

    Low clarity is a special case: not hearing the other side well is a
    directive of its own (ask one clarifying question) even when it is not the
    numerically highest channel.
    """
    if not _has_data(intero):
        return ""
    felt = levels(intero)
    if felt["clarity"] < TONE_THRESHOLD * 0.5:
        return TONE_LINES["clarity"]
    ranked = sorted(felt.items(), key=lambda item: item[1], reverse=True)
    name, value = ranked[0]
    if value < TONE_THRESHOLD:
        return ""
    if name == "clarity":
        return ""
    return TONE_LINES.get(name, "")


def length_factor(intero):
    """Multiplier for reply length: warmth lengthens, tension/heaviness shortens."""
    if not _has_data(intero):
        return 1.0
    felt = levels(intero)
    factor = (1.0
              - 0.50 * felt["tension"]
              - 0.40 * felt["heaviness"]
              + 0.40 * felt["warmth"]
              + 0.25 * (felt["clarity"] - 0.5))
    return round(_clamp(factor, 0.4, 1.6), 3)


def initiative(intero):
    """How forward the next expression should be (0..1)."""
    if not _has_data(intero):
        return DEFAULT_INITIATIVE
    felt = levels(intero)
    value = (DEFAULT_INITIATIVE
             + 0.45 * felt["warmth"]
             - 0.35 * felt["heaviness"]
             - 0.30 * felt["tension"]
             + 0.10 * felt["clarity"])
    return round(_clamp(value, 0.0, 1.0), 3)


def style(intero, target=10, cap=30):
    """Reply knobs for one interoceptive state (bounded, deterministic)."""
    base_target = max(MIN_TARGET, int(_num(target, 10)))
    base_cap = max(MIN_CAP, int(_num(cap, 30)))
    factor = length_factor(intero)
    new_target = max(MIN_TARGET, int(round(base_target * factor)))
    new_cap = max(new_target, max(MIN_CAP, int(round(base_cap * factor))))
    new_cap = min(MAX_CAP, new_cap)
    directive = tone(intero)
    return {"target": new_target, "cap": new_cap,
            "tone": directive, "initiative": initiative(intero),
            "factor": factor,
            "applied": bool(directive) or abs(factor - 1.0) > 1e-9,
            "levels": levels(intero)}
