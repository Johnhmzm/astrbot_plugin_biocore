# -*- coding: utf-8 -*-
"""Retrieval-practice stability gain (pure; default OFF).

Testing effect: a successful retrieval makes a memory more durable, a failed
retrieval never strengthens it (Roediger & Karpicke 2006; Bjork & Bjork 2011).

Interface:
  boost(stability, success, factor=None, base=None, cap_mult=2.0) -> float
      success=True  -> stability * 1.1..1.2, capped at cap_mult * base;
      success=False -> stability unchanged (no gain, no penalty).
  update_stability(entry, success=None, now=None, enabled=None) -> dict
      Patch to merge into the entry; {} when the module is disabled (default).
      Keys: stability_days, stability_base, retrieval_practice_hits,
      last_review_ts, review_interval_days, next_review_ts.

The module is disabled by default (RETRIEVAL_PRACTICE_ENABLED=False): callers
gate on 'enabled' before applying the patch. Passing enabled=False forces a
no-op. No IO, no LLM, no host imports; never mutates its inputs.
"""
from __future__ import annotations

import math

from ..core.util import now_ts

enabled = False
RETRIEVAL_PRACTICE_ENABLED = enabled

MIN_FACTOR = 1.1
MAX_FACTOR = 1.2
CAP_MULT = 2.0
MIN_STABILITY = 0.1
MAX_STABILITY = 365.0
DEFAULT_STABILITY = 1.0
SECONDS_PER_DAY = 86400.0


def _num(value, default=0.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _stability(value):
    current = _num(value, DEFAULT_STABILITY)
    if current <= 0.0:
        current = DEFAULT_STABILITY
    return max(MIN_STABILITY, min(MAX_STABILITY, current))


def _gain_factor(current, base):
    ceiling = max(current, CAP_MULT * base)
    room = 1.0 - (current / ceiling if ceiling > 0.0 else 1.0)
    room = max(0.0, min(1.0, room))
    return MIN_FACTOR + (MAX_FACTOR - MIN_FACTOR) * room


def boost(stability, success, factor=None, base=None, cap_mult=CAP_MULT):
    """Return stability after one retrieval attempt (never decreases)."""
    current = _stability(stability)
    if not success:
        return round(current, 4)
    base_value = _stability(base if base is not None else current)
    multiplier = max(1.0, _num(cap_mult, CAP_MULT))
    ceiling = min(MAX_STABILITY, multiplier * base_value)
    if factor is None:
        factor = _gain_factor(current, base_value)
    else:
        factor = max(MIN_FACTOR, min(MAX_FACTOR, _num(factor, MAX_FACTOR)))
    return round(max(current, min(current * factor, ceiling)), 4)


def update_stability(entry, success=None, now=None, enabled=None):
    """Return the stability patch for a recalled entry (disabled -> {})."""
    if enabled is False or not isinstance(entry, dict):
        return {}
    if success is None:
        success = bool(entry.get("recall_success",
                                 entry.get("retrieval_success", True)))
    if not success:
        return {}
    current = entry.get("stability_days",
                        entry.get("stability", DEFAULT_STABILITY))
    base = entry.get("stability_base", current)
    new_value = boost(current, True, base=base)
    stamp = now_ts(now)
    hits = int(max(0.0, _num(entry.get("retrieval_practice_hits",
                                     entry.get("review_count", 0)), 0.0))) + 1
    patch = {"stability_days": new_value,
             "stability_base": round(_stability(base), 4),
             "retrieval_practice_hits": hits,
             "last_review_ts": round(stamp, 3),
             "review_interval_days": new_value}
    patch["next_review_ts"] = round(stamp + new_value * SECONDS_PER_DAY, 3)
    return patch


__all__ = ["enabled", "RETRIEVAL_PRACTICE_ENABLED", "boost",
           "update_stability", "MIN_FACTOR", "MAX_FACTOR", "CAP_MULT",
           "MAX_STABILITY"]
