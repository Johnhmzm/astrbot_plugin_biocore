# -*- coding: utf-8 -*-
"""L0 autonomy readiness mixin: deterministic noise -> autonomy_state().

Copied verbatim from BioCore; originals stay as _orig_* after the rename.
"""
from __future__ import annotations

import time

try:
    from .bio_util import _clip
except Exception:  # pragma: no cover
    from bio_util import _clip

try:
    from .bio_const import (
        AUTONOMY_COOLDOWN_SECONDS,
        AUTONOMY_DAILY_CAP,
        AUTONOMY_ENTER,
        AUTONOMY_EXIT,
        AUTONOMY_MAX_CHARS_MAX,
        AUTONOMY_MAX_CHARS_MIN,
        AUTONOMY_QUIET_END_HOUR,
        AUTONOMY_QUIET_START_HOUR,
        AUTONOMY_THRESHOLD_MAX,
        AUTONOMY_THRESHOLD_MIN,
        AUTONOMY_WEIGHTS,
        NOISE_CLAMP,
    )
except Exception:  # pragma: no cover
    from bio_const import (
        AUTONOMY_COOLDOWN_SECONDS,
        AUTONOMY_DAILY_CAP,
        AUTONOMY_ENTER,
        AUTONOMY_EXIT,
        AUTONOMY_MAX_CHARS_MAX,
        AUTONOMY_MAX_CHARS_MIN,
        AUTONOMY_QUIET_END_HOUR,
        AUTONOMY_QUIET_START_HOUR,
        AUTONOMY_THRESHOLD_MAX,
        AUTONOMY_THRESHOLD_MIN,
        AUTONOMY_WEIGHTS,
        NOISE_CLAMP,
    )


class AutonomyStateMixin:
    """Copied verbatim from BioCore; originals stay as _orig_*."""

    def autonomy_state(self, relationship=None, now=None, persist: bool = True) -> dict:
        """L1 task-15: deterministic noise -> autonomy readiness.

        Inputs are all L1 state: 5 noise channels, echo_trace, stress_load
        (stress + allostatic), homeostasis drive deviation (L_int), persona
        autonomy_gain, and the relationship record passed in as data.
        Outputs are bounded: threshold ∈ [0.55, 0.90], max_chars ∈ [60, 240],
        impulse ∈ [0, 1]. P1-G11: threshold follows an EMA of past impulses plus
        a ready hysteresis band, not the current impulse alone. Default OFF
        returns {"enabled": False} without computing anything.
        """
        if not getattr(self, "autonomy_enabled", False):
            return {"enabled": False}
        try:
            current = float(now if now is not None else time.time())
        except Exception:
            current = time.time()
        try:
            noise = {k: float(self.noise.get(k, 0.0) or 0.0)
                     for k in ("stress", "energy", "social", "attention", "valence")}
        except Exception:
            noise = {}
        chaos = _clip(sum(abs(v) for v in noise.values()) / (5.0 * NOISE_CLAMP), 0.0, 1.0)
        # Stage-2: echo/ripple/spiking all feed the readiness input, not just
        # echo_trace. Bounded weighted mix (deterministic).
        try:
            _echo_raw = abs(float(getattr(self, "echo_trace", 0.0) or 0.0))
            _ripple = float((getattr(self, "ripple", {}) or {}).get("energy", 0.0) or 0.0)
            _spiking = float((getattr(self, "spiking", {}) or {}).get("rate", 0.0) or 0.0)
            echo = _clip(0.60 * _echo_raw + 0.20 * _ripple + 0.20 * min(1.0, _spiking), 0.0, 1.0)
        except Exception:
            echo = 0.0
        try:
            stress_load = _clip(
                0.6 * float(self.stress)
                + 0.4 * float(getattr(self, "allostatic_load", 0.0)), 0.0, 1.0)
        except Exception:
            stress_load = 0.0
        try:
            homeo = self.homeostasis if isinstance(self.homeostasis, dict) else {}
            drive_dev = _clip(float(homeo.get("L_int", 0.0) or 0.0), 0.0, 1.0)
        except Exception:
            drive_dev = 0.0
        rel = relationship if isinstance(relationship, dict) else {}
        rel_state = rel.get("state") if isinstance(rel.get("state"), dict) else {}
        try:
            trust = _clip(float(rel_state.get("trust", 0.5) or 0.5), 0.0, 1.0)
        except Exception:
            trust = 0.5
        try:
            closeness = _clip(float(rel_state.get("closeness", 0.5) or 0.5), 0.0, 1.0)
        except Exception:
            closeness = 0.5
        # Stage-2: attachment is an L1 input (not dashboard-only anymore).
        try:
            _attachment = rel.get("attachment") if isinstance(rel.get("attachment"), dict) else {}
            attachment_safe = _clip(float(_attachment.get("safe", 0.5) or 0.5), 0.0, 1.0)
        except Exception:
            attachment_safe = 0.5
        closeness_eff = _clip(0.70 * closeness + 0.30 * attachment_safe, 0.0, 1.0)
        try:
            gain = _clip(float((getattr(self, "profile", {}) or {}).get(
                "autonomy_gain", 1.0) or 0.0), 0.0, 1.5)
        except Exception:
            gain = 1.0
        w = AUTONOMY_WEIGHTS
        impulse = _clip(
            w["chaos"] * chaos + w["echo"] * echo + w["stress_load"] * stress_load
            + w["drive_dev"] * drive_dev + w["distrust"] * (1.0 - trust)
            + w["distance"] * (1.0 - closeness_eff), 0.0, 1.0)
        # P1-G10: autonomy_gain (persona profile) is now a real consumer.
        impulse = _clip(impulse * gain, 0.0, 1.0)
        prev = self._proactive_autonomy if isinstance(self._proactive_autonomy, dict) else {}
        try:
            prev_ema = float(prev.get("impulse_ema", impulse))
        except Exception:
            prev_ema = impulse
        impulse_ema = _clip(0.8 * prev_ema + 0.2 * impulse, 0.0, 1.0)
        # P1-G11: threshold uses the EMA (history), so it does not collapse to a
        # function of the current impulse; ready uses a small hysteresis band.
        target = _clip(0.82 - 0.30 * impulse_ema,
                       AUTONOMY_THRESHOLD_MIN, AUTONOMY_THRESHOLD_MAX)
        prev_ready = bool(prev.get("ready", False))
        # Explicit hysteresis: enter at 0.72, exit only below 0.60.
        if prev_ready:
            ready = impulse >= AUTONOMY_EXIT
        else:
            ready = impulse >= AUTONOMY_ENTER
        max_chars = int(round(_clip(60.0 + 180.0 * impulse,
                                    AUTONOMY_MAX_CHARS_MIN, AUTONOMY_MAX_CHARS_MAX)))
        result = {
            "enabled": True,
            "threshold": round(target, 4),
            "max_chars": max_chars,
            "impulse": round(impulse, 4),
            "impulse_ema": round(impulse_ema, 4),
            "ready": bool(ready),
            "chaos": round(chaos, 4),
            "gain": round(gain, 3),
            "noise_seed": int(getattr(self, "_noise_seed", 0) or 0),
            "sources": {
                "noise": {k: round(v, 4) for k, v in noise.items()},
                "echo_trace": round(echo, 4),
                "stress_load": round(stress_load, 4),
                "drive_dev": round(drive_dev, 4),
                "trust": round(trust, 4),
                "closeness": round(closeness, 4),
                "attachment_safe": round(attachment_safe, 4),
                "closeness_effective": round(closeness_eff, 4),
                "autonomy_gain": round(gain, 3),
            },
            "updated_ts": round(current, 3),
            "last_sent_ts": float(prev.get("last_sent_ts", 0.0) or 0.0),
            "sent_count": int(prev.get("sent_count", 0) or 0),
            "sent_day": str(prev.get("sent_day") or ""),
            "cooldown_seconds": AUTONOMY_COOLDOWN_SECONDS,
            "daily_cap": AUTONOMY_DAILY_CAP,
            "quiet_hours": [AUTONOMY_QUIET_START_HOUR, AUTONOMY_QUIET_END_HOUR],
        }
        if persist:
            self._proactive_autonomy = result
        return dict(result)
