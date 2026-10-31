# -*- coding: utf-8 -*-
"""L0 regulation loop: gap-driven action choice + outcome/efficacy learning.

Built on the interoception dimensions from biocore_model.intero_core. The loop
compares the current body state with comfort set-points (Powers 1973 perceptual
control; Carver & Scheier 1998 cybernetic control) and picks one of six
regulation actions (Gross 1998 strategy families).

Actions: approach / share / question / withdraw / repair / rest

Literature
  Craig 2009 (insula interoception), Barrett 2017 (constructed emotion),
  Seth 2013 (interoceptive prediction), Garfinkel 2015 (three dimensions),
  Sterling 2012 (allostasis), Carver & Scheier 1998 (control theory),
  Powers 1973 (perceptual control), Gross 1998 (regulation strategies).

Hard constraints: pure functions, stdlib only, no IO, no main import, time is
injected by the caller (none of these functions read the clock), and no core
state is mutated. All outputs are bounded JSON-able dicts.
"""
from __future__ import annotations

from . import intero_core as _intero

ACTIONS = ("approach", "share", "question", "withdraw", "repair", "rest")

# Gap thresholds (normalized 0..1). Tunable by callers through context.
TENSION_HIGH = 0.55
WARMTH_MID = (0.35, 0.65)
HEAVINESS_HIGH = 0.55
ENERGY_LOW = 0.35
ENERGY_VERY_LOW = 0.22
CLARITY_LOW = 0.45
WARMTH_LOW = 0.40
CONFLICT_HIGH = 0.30

# How much discomfort each action is expected to relieve (engineering prior).
GAIN_FACTOR = {
    "repair": 1.00, "approach": 0.90, "rest": 0.85,
    "share": 0.75, "question": 0.70, "withdraw": 0.60,
}

DEFAULT_ALPHA = 0.25
EFFICACY_PRIOR = 0.50


def _num(source, key, default=0.0):
    if not isinstance(source, dict):
        return float(default)
    try:
        value = source.get(key, default)
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _clamp(value, lo=0.0, hi=1.0):
    try:
        return max(lo, min(hi, float(value)))
    except Exception:
        return lo


def _intero_values(intero):
    return _intero.view(intero if isinstance(intero, dict) else {})


def _context(context=None):
    context = context if isinstance(context, dict) else {}
    conflict = _num(context, "conflict", _num(context, "relation_conflict", 0.0))
    return {
        "energy": _clamp(_num(context, "energy", 0.5)),
        "conflict": _clamp(conflict),
        "closeness": _clamp(_num(context, "closeness", 0.5)),
        "loneliness": _clamp(_num(context, "loneliness", 0.0)),
    }


def _gain(action, total):
    return round(_clamp((0.35 + 0.65 * total) * GAIN_FACTOR.get(action, 0.6)), 3)


def choose_action(intero, context=None):
    """Pick one regulation action from the interoceptive gaps.

    Rules are evaluated in priority order (first match wins):
      1. tension high + relationship conflict -> repair
      2. tension high + warmth mid            -> approach
      3. heaviness high + energy low          -> rest (very low) / withdraw
      4. clarity low                          -> question / share
      5. warmth low + no conflict             -> share
      6. fallback                             -> approach / share
    """
    body = _intero_values(intero)
    ctx = _context(context)
    tension = body["tension"]
    warmth = body["warmth"]
    heaviness = body["heaviness"]
    clarity = body["clarity"]
    total = float(body.get("discomfort", 0.0))
    conflict = ctx["conflict"]
    energy = ctx["energy"]
    action = "share"
    reason = "no clear gap: keep gentle contact"
    if tension >= TENSION_HIGH and conflict >= CONFLICT_HIGH:
        action, reason = "repair", "tension high + relationship conflict"
    elif tension >= TENSION_HIGH and WARMTH_MID[0] <= warmth <= WARMTH_MID[1]:
        action, reason = "approach", "tense but still warm enough to reach out"
    elif heaviness >= HEAVINESS_HIGH and energy <= ENERGY_LOW:
        if energy <= ENERGY_VERY_LOW:
            action, reason = "rest", "heavy and exhausted: recover first"
        else:
            action, reason = "withdraw", "heavy with low energy: step back"
    elif clarity <= CLARITY_LOW:
        if conflict >= CONFLICT_HIGH or warmth >= 0.50:
            action, reason = "question", "unclear: ask instead of guessing"
        else:
            action, reason = "share", "unclear: say it out to make sense"
    elif warmth <= WARMTH_LOW and conflict < CONFLICT_HIGH:
        action, reason = "share", "cold but no conflict: share to reconnect"
    elif warmth >= WARMTH_MID[1]:
        action, reason = "approach", "warm baseline: lean in"
    else:
        action, reason = "share", "neutral: keep the channel open"
    return {"action": action, "reason": reason,
            "expected_gain": _gain(action, total)}


def outcome(before, after, action=None):
    """Compare two interoceptive states: negative delta = discomfort relieved.

    before/after may be intero dim dicts or discomfort() results; only the
    scalar discomfort is compared. success means the gap shrank by >= 0.01.
    """
    def _total(value):
        if isinstance(value, dict) and "total" in value and len(value) <= 3:
            return _clamp(value.get("total"))
        return float(_intero.discomfort(value if isinstance(value, dict) else {}).get("total", 0.0))
    start = _total(before)
    end = _total(after)
    delta = round(end - start, 4)
    return {"action": str(action or ""), "delta_discomfort": delta,
            "success": bool(delta <= -0.01), "before": round(start, 4),
            "after": round(end, 4)}


def efficacy(history, action, alpha=DEFAULT_ALPHA, prior=EFFICACY_PRIOR):
    """EWMA success rate of one action over its history samples.

    history is a list of {"action": str, "success": bool|0..1} dicts, or of
    (action, success) tuples. Samples are folded in order; no samples returns
    the prior (0.5). Pure: the caller owns history storage.
    """
    action = str(action or "")
    a = _clamp(alpha if alpha is not None else DEFAULT_ALPHA)
    value = _clamp(prior if prior is not None else EFFICACY_PRIOR)
    for item in history or []:
        if isinstance(item, tuple) and len(item) >= 2:
            item_action, raw = item[0], item[1]
        elif isinstance(item, dict):
            item_action, raw = item.get("action"), item.get("success", item.get("ok"))
        else:
            continue
        if str(item_action or "") != action:
            continue
        if isinstance(raw, bool):
            sample = 1.0 if raw else 0.0
        else:
            sample = _clamp(raw)
        value = value + a * (sample - value)
    return round(_clamp(value), 4)


def sample(action, success, detail=None):
    """Build one history row (kept tiny so callers can persist any list)."""
    return {"action": str(action or ""), "success": bool(success),
            "detail": dict(detail or {})}
