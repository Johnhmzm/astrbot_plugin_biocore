# -*- coding: utf-8 -*-
"""HUMAN-5 criticality: power-law avalanches (many small, few large).

Internal events follow a heavy-tailed distribution: most ticks produce a tiny
perturbation, rare ticks produce a large cascade. Deterministic per (seed,
tick) so replay is exact; capped to keep the biological state bounded.

Literature
  Beggs & Plenz 2003 (neuronal avalanches; exponent family 1.5-2.0),
  Bak 1987 (self-organized criticality), Chialvo 2010 (brain criticality),
  Shew & Plenz 2013 (critical dynamics and behaviour), Carver & Scheier 1998
  (control errors propagate), Sterling 2012 (allostatic bursts), Seth 2013
  (prediction errors are heavy-tailed), Gross 1998 (regulation after spikes).

Constraints: pure functions, stdlib only, no IO, no main import, tick injected.
"""
from __future__ import annotations

import hashlib

ALPHA = 2.0
MIN_SIZE = 1
MAX_SIZE = 512
SMALL_CUTOFF = 10
HEAVY_CUTOFF = 50


def _clamp(value, lo, hi):
    try:
        return max(lo, min(hi, float(value)))
    except Exception:
        return lo


def _unit(seed, tick, salt=""):
    key = ("%s|%s|%s" % (seed, tick, salt)).encode("utf-8")
    digest = hashlib.sha256(key).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def size(seed, tick=0, alpha=ALPHA, max_size=MAX_SIZE, min_size=MIN_SIZE):
    """Power-law avalanche size in [min_size, max_size] (Pareto tail)."""
    a = _clamp(alpha, 1.05, 4.0)
    top = int(_clamp(max_size, 1, 100000))
    bottom = int(_clamp(min_size, 1, top))
    u = max(1e-9, min(1.0 - 1e-9, _unit(seed, tick, "avalanche")))
    raw = (1.0 - u) ** (-1.0 / (a - 1.0))
    return int(_clamp(round(raw), bottom, top))


def is_event(seed, tick=0, p=0.55):
    """Whether this tick starts an avalanche at all (deterministic)."""
    return _unit(seed, tick, "event") < _clamp(p, 0.0, 1.0)


def batch(seed, count=100, alpha=ALPHA, max_size=MAX_SIZE):
    """Sizes for count consecutive ticks (deterministic)."""
    return [size(seed, int(index), alpha=alpha, max_size=max_size)
            for index in range(max(0, int(count)))]


def summary(sizes):
    """n / mean / max / small_fraction / heavy_fraction for a size list."""
    rows = [max(1, int(item)) for item in (sizes or []) if item is not None]
    if not rows:
        return {"n": 0, "mean": 0.0, "max": 0, "small_fraction": 0.0,
                "heavy_fraction": 0.0}
    count = len(rows)
    return {"n": count,
            "mean": round(sum(rows) / float(count), 3),
            "max": max(rows),
            "small_fraction": round(sum(1 for x in rows if x <= SMALL_CUTOFF) / float(count), 4),
            "heavy_fraction": round(sum(1 for x in rows if x > HEAVY_CUTOFF) / float(count), 4)}


def burst_value(seed, tick=0, alpha=ALPHA):
    """Signed avalanche impulse for the noise bank (0 when no event)."""
    if not is_event(seed, tick):
        return 0.0
    sign = 1.0 if _unit(seed, tick, "sign") >= 0.5 else -1.0
    return round(sign * min(MAX_SIZE, size(seed, tick, alpha=alpha)) / float(MAX_SIZE), 4)
