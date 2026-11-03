# -*- coding: utf-8 -*-
"""Memory reconstruction: a recalled memory is never quite the same memory.

Each recall adds a small drift to the memory's colouring:

- direction comes from the current mood (warm mood tints warm, low mood cools)
- magnitude grows with how often it has been recalled, slowly and with a cap
- important memories do not drift at all
- the accumulated drift is conserved: it can never exceed the cap, and the
  amount removed from one end is bounded the same way

The module returns a number, not rewritten prose; the expression layer decides
whether to colour the sentence, and the caller stores the running total.

Pure functions only: no IO, no host imports, no LLM calls.
"""
from __future__ import annotations

import math

DRIFT_CAP = 0.12
BASE_PER_RECALL = 0.02
IMPORTANT = 0.80
TEMPERATURE = 0.0


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


def _entry(entry):
    entry = entry if isinstance(entry, dict) else {}
    return {
        "text": str(entry.get("text") or "").strip()[:80],
        "importance": _clamp(entry.get("importance", 0.5)),
        "valence": max(-1.0, min(1.0, _num(entry.get("valence"), 0.0))),
    }


def magnitude(recalls, cap=DRIFT_CAP):
    """How far one recall can move a memory, growing slowly with repetition."""
    count = max(0, int(_num(recalls, 0)))
    if count <= 0:
        return 0.0
    raw = BASE_PER_RECALL * math.log1p(count)
    return round(min(max(0.0, _num(cap, DRIFT_CAP)), raw), 4)


def direction(mood):
    """+1 for a warm mood, -1 for a low one, 0 when neutral."""
    value = max(-1.0, min(1.0, _num(mood, 0.0)))
    if value > 0.10:
        return 1
    if value < -0.10:
        return -1
    return 0


def drift(entry, mood=0.0, recalls=1, prior_drift=0.0, flags=None):
    """One recall step. Returns the delta to add, plus bounds information."""
    flags = flags if isinstance(flags, dict) else {}
    enabled = bool(flags.get("enabled", True))
    row = _entry(entry)
    cap = max(0.0, _num(flags.get("cap"), DRIFT_CAP))
    prior = max(-cap, min(cap, _num(prior_drift, 0.0)))

    if not enabled:
        return {"enabled": False, "delta": 0.0, "total": prior, "capped": False,
                "direction": 0, "reason": "重构关闭"}
    if not row["text"]:
        return {"enabled": True, "delta": 0.0, "total": prior, "capped": False,
                "direction": 0, "reason": "没有可重构的内容"}
    if row["importance"] >= IMPORTANT:
        return {"enabled": True, "delta": 0.0, "total": prior, "capped": False,
                "direction": 0, "reason": "重要记忆不漂"}

    sign = direction(mood)
    if sign == 0:
        return {"enabled": True, "delta": 0.0, "total": prior, "capped": False,
                "direction": 0, "reason": "情绪平静，不偏移"}

    step = magnitude(recalls, cap) * sign
    # Conservation: the running total may not pass the cap in either direction.
    proposed = prior + step
    capped = False
    if proposed > cap:
        proposed, capped = cap, True
    elif proposed < -cap:
        proposed, capped = -cap, True
    delta = round(proposed - prior, 4)
    return {
        "enabled": True,
        "delta": delta,
        "total": round(proposed, 4),
        "capped": capped,
        "direction": sign,
        "reason": ("回忆让它偏暖一点" if sign > 0 else "回忆让它偏冷一点"),
    }


def text_hint(result):
    """A short line the expression layer may use; empty when nothing shifted."""
    if not isinstance(result, dict) or not result.get("enabled", True):
        return ""
    total = _num(result.get("total"), 0.0)
    if abs(total) < 0.02:
        return ""
    return "想起这件事时，比当时%s一点" % ("暖" if total > 0 else "凉")


def conserve(entries, cap=DRIFT_CAP):
    """Rescale stored drifts so their total stays inside the cap."""
    cap = max(0.0, _num(cap, DRIFT_CAP))
    rows = entries if isinstance(entries, (list, tuple)) else []
    total = sum(_num(row.get("drift"), 0.0) for row in rows if isinstance(row, dict))
    if total == 0:
        return {"total": 0.0, "scale": 1.0}
    limit = cap
    if abs(total) <= limit:
        return {"total": round(total, 4), "scale": 1.0}
    scale = limit / abs(total)
    return {"total": round(total * scale, 4), "scale": round(scale, 4)}
