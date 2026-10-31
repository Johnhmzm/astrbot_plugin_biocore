# -*- coding: utf-8 -*-
"""Borbély 1982 two-process model: circadian rhythm + sleep/energy coupling."""
from __future__ import annotations

import math
import time

DEFAULT_SLEEP = "00:30"
DEFAULT_WAKE = "07:30"
CIRCADIAN_TROUGH = 4.0     # 03:00-05:00 low point
CIRCADIAN_PEAKS = (10.0, 20.0)


def _hhmm(value, fallback):
    try:
        text = str(value or fallback)
        hour, minute = text.split(":")
        return int(hour) % 24 + int(minute) / 60.0
    except Exception:
        hour, minute = str(fallback).split(":")
        return int(hour) + int(minute) / 60.0


def local_fraction(now_ts, tz_offset_hours=8.0):
    try:
        current = float(now_ts)
    except Exception:
        current = time.time()
    hours = (current / 3600.0 + float(tz_offset_hours)) % 24.0
    return hours


def circadian(hour):
    """Cosine rhythm: trough ~04:00, peaks ~10:00 and 20:00, range [0,1]."""
    try:
        h = float(hour) % 24.0
    except Exception:
        h = 12.0
    value = 0.5 + 0.5 * math.cos(2 * math.pi * (h - CIRCADIAN_PEAKS[0]) / 12.0)
    return max(0.0, min(1.0, value))


def in_sleep_window(hour, sleep_at=DEFAULT_SLEEP, wake_at=DEFAULT_WAKE):
    start = _hhmm(sleep_at, DEFAULT_SLEEP)
    end = _hhmm(wake_at, DEFAULT_WAKE)
    h = float(hour) % 24.0
    if start <= end:
        return start <= h < end
    return h >= start or h < end


def sleep_state(now_ts, sleep_at=DEFAULT_SLEEP, wake_at=DEFAULT_WAKE, tz_offset_hours=8.0):
    """Current sleep snapshot (deterministic; no persistent side effects)."""
    hour = local_fraction(now_ts, tz_offset_hours)
    sleeping = in_sleep_window(hour, sleep_at, wake_at)
    state = {"sleeping": bool(sleeping), "circadian": round(circadian(hour), 4),
             "hour": round(hour, 3), "sleep_at": str(sleep_at), "wake_at": str(wake_at),
             "asleep_since": 0.0, "wake_ts": 0.0, "sleep_quality": 0.7}
    return state


def quality_from_durations(sleep_hours, target=7.0):
    try:
        hours = max(0.0, float(sleep_hours))
    except Exception:
        hours = 0.0
    target = max(1.0, float(target or 7.0))
    return max(0.0, min(1.0, hours / target))


def next_day_energy(quality, base=1.0):
    """Short sleep lowers the next day's energy ceiling."""
    try:
        q = max(0.0, min(1.0, float(quality)))
    except Exception:
        q = 0.7
    ceiling = float(base) * (0.55 + 0.45 * q)
    return round(max(0.2, min(1.0, ceiling)), 4)


def energy_effects(energy):
    """Low energy: slightly lower drive, shorter sentences, more irritable."""
    try:
        e = max(0.0, min(1.0, float(energy)))
    except Exception:
        e = 0.7
    low = 1.0 - e
    return {"drive_mult": round(1.0 - 0.15 * low, 4),
            "max_chars_mult": round(1.0 - 0.25 * low, 4),
            "stress_delta": round(0.02 * low, 4)}


def settled_energy(current_energy, quality, dt_hours, now, last_applied_ts=0.0):
    """Apply one sleep-quality-coupled energy adjustment (idempotent per now)."""
    try:
        current = float(now)
        last = float(last_applied_ts or 0.0)
    except Exception:
        current, last = 0.0, 0.0
    if last > 0 and current <= last:
        return float(current_energy or 0.0), last
    ceiling = next_day_energy(quality)
    value = min(float(current_energy or 0.0), ceiling)
    return round(max(0.0, value), 4), current


def circadian_from_snapshot(snapshot):
    """ARCH-1: read L0 circadian_alertness when present (fallback keeps old math)."""
    data = snapshot if isinstance(snapshot, dict) else {}
    value = data.get("circadian_alertness", data.get("circadian"))
    if value is not None:
        try:
            return max(0.0, min(1.0, float(value)))
        except Exception:
            pass
    return None
