# -*- coding: utf-8 -*-
"""HUMAN-2 noise bank: common + channel-specific + reproducible event bursts.

Every draw is a pure hash of (seed, tick, salt), so replaying the same seed and
tick reproduces the exact noise without storing RNG state. Bursts are rare
deterministic events (avalanche-like sensory spikes) layered on top.

Literature
  Fields 2007 (neural noise shapes behaviour), Faisal 2008 (noise in the
  nervous system), Wiesenfeld & Moss 1995 (stochastic resonance), Beggs & Plenz
  2003 (neuronal avalanches), Carver & Scheier 1998 (control loop needs a
  stable signal), Seth 2013 (prediction error is noisy).

Constraints: pure functions, stdlib only, no IO, no main import, time is the
injected tick/now; the same inputs are byte-reproducible.
"""
from __future__ import annotations

import hashlib
import math

COMMON_SIGMA = 0.12
CHANNEL_SIGMA = 0.08
BURST_P = 0.02
BURST_GAIN = 6.0
CLAMP = 3.0


def _unit(seed, tick, salt=""):
    """Deterministic uniform [0, 1) from seed/tick/salt (stdlib only)."""
    key = ("%s|%s|%s" % (seed, tick, salt)).encode("utf-8")
    digest = hashlib.sha256(key).digest()
    value = int.from_bytes(digest[:8], "big")
    return value / float(1 << 64)


def _gauss(seed, tick, salt=""):
    """Box-Muller pair from two independent deterministic uniforms."""
    u1 = max(1e-9, _unit(seed, tick, salt + ":a"))
    u2 = _unit(seed, tick, salt + ":b")
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def _clamp(value, lo=-CLAMP, hi=CLAMP):
    try:
        return max(lo, min(hi, float(value)))
    except Exception:
        return 0.0


def common(seed, tick, sigma=COMMON_SIGMA):
    """Shared sensory noise for one tick (same for every channel)."""
    return round(_clamp(_gauss(seed, tick, "common") * max(0.0, _num(sigma, COMMON_SIGMA))), 4)


def channel(seed, tick, name, sigma=CHANNEL_SIGMA):
    """Channel-specific noise (independent across channels)."""
    return round(_clamp(_gauss(seed, tick, "ch:" + str(name))
                        * max(0.0, _num(sigma, CHANNEL_SIGMA))), 4)


def burst(seed, tick, p=BURST_P, gain=BURST_GAIN):
    """Rare deterministic spike: {hit, value, magnitude}."""
    chance = _clamp(p, 0.0, 1.0)
    hit = _unit(seed, tick, "burst") < chance
    if not hit:
        return {"hit": False, "value": 0.0, "magnitude": 0.0}
    magnitude = _clamp(_unit(seed, tick, "burst:mag") * max(0.0, _num(gain, BURST_GAIN)))
    sign = 1.0 if _unit(seed, tick, "burst:sign") >= 0.5 else -1.0
    return {"hit": True, "value": round(sign * magnitude, 4),
            "magnitude": round(magnitude, 4)}


def value(seed, tick, name="", p=BURST_P, sigma=COMMON_SIGMA, channel_sigma=CHANNEL_SIGMA):
    """Combined noise = common + channel + burst, clamped to +/-3."""
    spike = burst(seed, tick, p=p)
    total = (common(seed, tick, sigma=sigma)
             + (channel(seed, tick, name, sigma=channel_sigma) if name else 0.0)
             + spike["value"])
    return {"value": round(_clamp(total), 4), "burst": bool(spike["hit"]),
            "common": common(seed, tick, sigma=sigma),
            "channel": (channel(seed, tick, name, sigma=channel_sigma) if name else 0.0)}


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def sample_window(seed, start_tick, count=10, name=""):
    """Vector of values for ticks start_tick..start_tick+count-1 (tests/debug)."""
    return [value(seed, int(start_tick) + index, name=name)
            for index in range(max(0, int(count)))]
