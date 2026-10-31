# -*- coding: utf-8 -*-
"""HUMAN-3 autonomic oscillation: 0.1-0.3 Hz rhythm modulating discomfort.

A slow bodily oscillation (heartbeat/breathing band) shifts the discomfort
threshold a little each turn, so regulation fires with a natural rhythm instead
of a perfect constant. Pure sine, phase driven by injected now; no state kept.

Literature
  Craig 2009 (interoceptive afferents are rhythmic), Seth 2013 (prediction and
  interoceptive inference), Garfinkel 2015 (interoceptive sensibility), Thayer &
  Lane 2009 (heart-rate variability and affect regulation), Sterling 2012
  (allostasis budgets fluctuate), Carver & Scheier 1998 (control gains),
  Powers 1973 (perceptual control), Gross 1998 (regulation timing).

Constraints: pure functions, stdlib only, no IO, no main import, time injected.
"""
from __future__ import annotations

import math

FREQ_MIN = 0.1
FREQ_MAX = 0.3
DEFAULT_FREQ = 0.2
BASE_THRESHOLD = 0.35
DEFAULT_AMPLITUDE = 0.05
THRESHOLD_MIN = 0.15
THRESHOLD_MAX = 0.60


def _clamp(value, lo, hi):
    try:
        return max(lo, min(hi, float(value)))
    except Exception:
        return lo


def frequency(freq=DEFAULT_FREQ):
    """Clamp to the physiological 0.1-0.3 Hz band."""
    return _clamp(DEFAULT_FREQ if freq is None else freq, FREQ_MIN, FREQ_MAX)


def period(freq=DEFAULT_FREQ):
    return round(1.0 / frequency(freq), 4)


def in_band(freq):
    try:
        value = float(freq)
    except Exception:
        return False
    return FREQ_MIN <= value <= FREQ_MAX


def phase(now, freq=DEFAULT_FREQ, phase0=0.0):
    return 2.0 * math.pi * frequency(freq) * float(now) + float(phase0)


def wave(now, freq=DEFAULT_FREQ, amplitude=1.0, phase0=0.0):
    """Sine wave in [-amplitude, +amplitude] (phase continuous in now)."""
    amp = _clamp(amplitude, 0.0, 1.0)
    return round(amp * math.sin(phase(now, freq, phase0)), 4)


def threshold(base=BASE_THRESHOLD, now=0.0, amplitude=DEFAULT_AMPLITUDE,
              freq=DEFAULT_FREQ, phase0=0.0, lo=THRESHOLD_MIN, hi=THRESHOLD_MAX):
    """Discomfort threshold = base + amplitude*sin(...), kept inside [lo, hi]."""
    delta = _clamp(amplitude, 0.0, (THRESHOLD_MAX - THRESHOLD_MIN) / 2.0) * math.sin(
        phase(now, freq, phase0))
    return round(_clamp(float(base) + delta, float(lo), float(hi)), 4)


def modulate(discomfort, now=0.0, base=BASE_THRESHOLD, amplitude=DEFAULT_AMPLITUDE,
             freq=DEFAULT_FREQ, phase0=0.0):
    """Compare discomfort with the oscillating threshold (read-only)."""
    thr = threshold(base=base, now=now, amplitude=amplitude, freq=freq, phase0=phase0)
    try:
        value = max(0.0, float(discomfort))
    except Exception:
        value = 0.0
    ratio = round(value / thr, 4) if thr > 0 else 0.0
    return {"discomfort": round(value, 4), "threshold": thr,
            "ratio": ratio, "triggered": bool(value > thr)}


def sample(now_start, seconds=10.0, step=0.5, **kwargs):
    """Sampled wave, deterministic (useful for traces/tests)."""
    out = []
    count = max(0, int(float(seconds) / max(0.05, float(step))))
    for index in range(count):
        out.append(wave(float(now_start) + index * float(step), **kwargs))
    return out
