# -*- coding: utf-8 -*-
"""Attachment styles as behaviour, not labels.

Three styles shape how she behaves when a bond is at stake:

- secure    asks when it matters, backs off when it is respected
- anxious   reaches first, asks more, does not retreat
- avoidant  keeps distance, retreats early, says less

The output is a small parameter set (initiative, seeking, withdrawal speed and
what she does after being ignored) plus a bounded tone hint. Mixed styles are
supported by passing weights.

Pure functions only: no IO, no host imports, no LLM calls.
"""
from __future__ import annotations

STYLES = ("secure", "anxious", "avoidant")
LABELS = {"secure": "安全型", "anxious": "焦虑型", "avoidant": "回避型"}

BASE = {
    "secure": {"initiative": 0.60, "seeking": 0.40, "withdrawal": 0.30},
    "anxious": {"initiative": 0.80, "seeking": 0.80, "withdrawal": 0.20},
    "avoidant": {"initiative": 0.30, "seeking": 0.15, "withdrawal": 0.80},
}

IGNORED = {
    "secure": "等一会儿再问一次，不追问",
    "anxious": "再发一条，确认是不是生气",
    "avoidant": "退回去，先不说了",
}

TONE = {
    "secure": "正常问，被拒绝也不受伤",
    "anxious": "想确认对方还在，但别连发太多",
    "avoidant": "少说两句，等对方先动",
}


def _num(value, default=0.0):
    try:
        num = float(value)
    except Exception:
        return default
    if num != num:
        return default
    return num


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _num(value, low)))


def _weights(style):
    """Accept a style name or a weights dict; fall back to secure."""
    if isinstance(style, dict):
        total = sum(max(0.0, _num(v)) for v in style.values())
        if total <= 0:
            return {"secure": 1.0}
        return {name: max(0.0, _num(value)) / total
                for name, value in style.items() if name in STYLES and _num(value) > 0}
    name = str(style or "secure")
    if name not in STYLES:
        name = "secure"
    return {name: 1.0}


def style_of(weights):
    if not weights:
        return "secure"
    return max(weights.items(), key=lambda row: row[1])[0]


def evaluate(style="secure", context=None, flags=None):
    """Parameters for this turn, blended across mixed styles."""
    flags = flags if isinstance(flags, dict) else {}
    enabled = bool(flags.get("enabled", True))
    context = context if isinstance(context, dict) else {}
    weights = _weights(style)
    primary = style_of(weights)

    blended = {key: 0.0 for key in ("initiative", "seeking", "withdrawal")}
    for name, weight in weights.items():
        for key in blended:
            blended[key] += BASE[name][key] * weight

    closeness = _clamp(context.get("closeness", 0.5))
    stress = _clamp(context.get("stress", 0.3))
    ignored = bool(context.get("ignored", False))

    # A settled bond lifts initiative a little; stress pulls everyone back.
    initiative = blended["initiative"] + 0.15 * (closeness - 0.5) - 0.20 * stress
    seeking = blended["seeking"] + 0.10 * (closeness - 0.5) - 0.10 * stress
    withdrawal = blended["withdrawal"] + 0.25 * stress - 0.10 * (closeness - 0.5)

    result = {
        "enabled": enabled,
        "style": primary,
        "label": LABELS.get(primary, ""),
        "mix": {name: round(weight, 3) for name, weight in weights.items()},
        "initiative": round(_clamp(initiative), 3),
        "seeking": round(_clamp(seeking), 3),
        "withdrawal": round(_clamp(withdrawal), 3),
        "on_ignored": IGNORED.get(primary, IGNORED["secure"]),
        "tone": TONE.get(primary, ""),
    }
    if not enabled:
        result.update({"style": "secure", "label": LABELS["secure"],
                       "initiative": 0.6, "seeking": 0.4, "withdrawal": 0.3,
                       "on_ignored": IGNORED["secure"], "tone": ""})
    elif ignored:
        # Being ignored is the moment attachment style shows most clearly.
        result["initiative"] = round(_clamp(result["initiative"] * 0.6), 3)
        result["seeking"] = round(_clamp(result["seeking"] * (1.3 if primary == "anxious" else 0.7)), 3)
        result["withdrawal"] = round(_clamp(result["withdrawal"] + (0.2 if primary == "avoidant" else 0.0)), 3)
    return result


def directives(result):
    """Bounded hints for the expression layer (no prompt text)."""
    if not isinstance(result, dict) or not result.get("enabled", True):
        return {"tone": "", "length_scale": 1.0, "proactive": 0.5}
    scale = 1.0
    if _num(result.get("withdrawal"), 0.5) >= 0.6:
        scale = 0.8
    elif _num(result.get("initiative"), 0.5) >= 0.7:
        scale = 1.05
    return {"tone": result.get("tone") or "",
            "length_scale": scale,
            "proactive": round(_clamp(result.get("initiative"), 0.5), 3)}
