# -*- coding: utf-8 -*-
"""Metacognition: how sure she is, and what she does about it.

The self layer decides what she wants; the expression layer writes it.
Between them, this module answers three questions:

- how sure is this turn (confidence band, guard hits lower it)
- may she correct herself (a stance conflict allows one correction)
- should she hold back (three low-confidence turns in a row means
  more words will not help)

Pure functions only: no IO, no host imports, no LLM calls.
"""
from __future__ import annotations

LOW = 0.45
HIGH = 0.75
GUARD_PENALTY = 0.10
GUARD_PENALTY_CAP = 0.30
LOW_STREAK = 3

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

def band(confidence):
    """low / mid / high, from a 0-1 confidence."""
    value = _clamp(confidence)
    if value < LOW:
        return "low"
    if value < HIGH:
        return "mid"
    return "high"

def _guard_hits(hits):
    """Accept a count, a list of rule names, or a dict {rule: count}."""
    if isinstance(hits, dict):
        total = 0
        for value in hits.values():
            total += max(0, int(_num(value, 0)));
        return total
    if isinstance(hits, (list, tuple, set)):
        return len([row for row in hits if row])
    return max(0, int(_num(hits, 0)));

def _low_flags(history):
    """Turn the recent-history blob into a list of bools (oldest first)."""
    out = []
    if isinstance(history, dict):
        rows = history.get("low_flags") or history.get("history") or []
    else:
        rows = history
    if not isinstance(rows, (list, tuple)):
        return out
    for row in rows:
        if isinstance(row, dict):
            out.append(bool(row.get("low")) or _clamp(row.get("confidence")) < LOW)
        else:
            out.append(bool(row))
    return out

def evaluate(intent=None, confidence=0.6, guard_hits=0, conflict=False,
             history=None, flags=None):
    """One turn of metacognition. See the module docstring for the contract."""
    flags = flags if isinstance(flags, dict) else {}
    enabled = bool(flags.get("enabled", True))
    base = _clamp(confidence, 0.0, 1.0)
    hits = _guard_hits(guard_hits)
    penalty = min(GUARD_PENALTY_CAP, GUARD_PENALTY * hits)
    adjusted = round(_clamp(base - penalty), 3)
    grade = band(adjusted)
    uncertain = grade == "low" or hits > 0
    conflict_on = bool(conflict)
    if isinstance(conflict, dict):
        conflict_on = bool(conflict.get("conflicts_with_stance"))
    allow_correction = bool(conflict_on and adjusted >= 0.30)

    flags_recent = _low_flags(history)
    recent_low = grade == "low"
    streak = 0
    for value in reversed(flags_recent + [recent_low]):
        if value:
            streak += 1
        else:
            break
    converge = streak >= LOW_STREAK

    if not enabled:
        return {
            "enabled": False,
            "confidence": round(base, 3),
            "band": grade,
            "uncertainty": False,
            "allow_self_correction": False,
            "converge": False,
            "low_streak": streak,
            "reason": "元认知关闭",
        }

    if converge:
        reason = "连着几轮都不确定，少说点更稳妥"
    elif allow_correction:
        reason = "跟他原来的看法有冲突，可以补一句修正"
    elif uncertain:
        reason = ("校验拦下过内容，先别承诺" if hits
                  else "这轮把握不大，别下结论")
    elif grade == "high":
        reason = "有把握，可以正常说"
    else:
        reason = "正常发挥"

    return {
        "enabled": True,
        "confidence": adjusted,
        "band": grade,
        "uncertainty": bool(uncertain),
        "allow_self_correction": allow_correction,
        "converge": bool(converge),
        "low_streak": streak,
        "reason": reason,
    }

def remember(history, result):
    """Append this turn to the history blob; keep the last 8 turns only."""
    flags_recent = _low_flags(history)
    low = bool((result or {}).get("band") == "low")
    flags_recent.append(low)
    return {"low_flags": flags_recent[-8:]}

def directives(result):
    """Bounded hints for the expression layer (no prompt text)."""
    if not isinstance(result, dict) or not result.get("enabled", True):
        return {"length_scale": 1.0, "tone": "", "confidence": 0.6}
    grade = result.get("band") or "mid"
    if result.get("converge"):
        return {"length_scale": 0.7, "tone": "话少一点，别下结论",
                "confidence": _clamp(result.get("confidence"))}
    if grade == "low":
        return {"length_scale": 0.8, "tone": "别承诺，别给建议",
                "confidence": _clamp(result.get("confidence"))}
    if result.get("allow_self_correction"):
        return {"length_scale": 1.0, "tone": "可以补一句修正",
                "confidence": _clamp(result.get("confidence"))}
    return {"length_scale": 1.0, "tone": "",
            "confidence": _clamp(result.get("confidence"))}
