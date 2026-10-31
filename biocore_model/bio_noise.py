# -*- coding: utf-8 -*-
"""L0 noise mixin: discrete noise ticks and prior blending.

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
        NOISE_CLAMP,
    )
except Exception:  # pragma: no cover
    from bio_const import (
        NOISE_CLAMP,
    )


class NoiseMixin:
    """Copied verbatim from BioCore; originals stay as _orig_*."""

    def integrate_noise(self, source: str = "", **deltas) -> dict:
        """L1 task-15: decayed addition into the 5-channel noise integrator.

        Only active when the plugin enabled proactive autonomy
        (core.autonomy_enabled). Default OFF is a pure no-op, so the legacy
        noise trajectory is unchanged. Channels decay 0.98 per integration and
        are clamped to ±NOISE_CLAMP. This is an L1 state update: callers only
        hand in module deltas; no caller reads it to bypass L1 decisions.
        """
        if not getattr(self, "autonomy_enabled", False):
            return {}
        # Accumulator only: modules add small deltas; the single tick applies
        # decay + RNG + the accumulated injections (P0-2 unified noise model).
        if not isinstance(getattr(self, "_noise_accum", None), dict):
            self._noise_accum = {}
        out = {}
        try:
            for key in ("stress", "energy", "social", "attention", "valence"):
                try:
                    add = float(deltas.get(key, 0.0) or 0.0)
                except Exception:
                    add = 0.0
                add = max(-0.02, min(0.02, add))
                current = float(self._noise_accum.get(key, 0.0) or 0.0)
                value = _clip(current + add, -NOISE_CLAMP, NOISE_CLAMP)
                self._noise_accum[key] = round(value, 4)
                out[key] = round(value, 4)
            self._last_noise_source = {"source": str(source or "")[:40],
                                       "ts": round(time.time(), 3)}
        except Exception:
            pass
        return out


    def noise_tick(self, now=None) -> dict:
        """L1 task-15 P0-2: single noise update point.

        noise = clip(0.82*noise + gauss(0,0.045) + accumulated module deltas,
                     ±NOISE_CLAMP). Only called by the autonomy tick; legacy
        per-observe noise updates are skipped while autonomy is enabled.
        """
        if not (getattr(self, "autonomy_enabled", False)
                or getattr(self, "autonomy_loop_enabled", False)):
            return {}
        out = {}
        try:
            accum = self._noise_accum if isinstance(getattr(self, "_noise_accum", None), dict) else {}
            for key in ("stress", "energy", "social", "attention", "valence"):
                old = float(self.noise.get(key, 0.0) or 0.0)
                try:
                    gauss = float(self._rng.gauss(0, 0.045))
                except Exception:
                    gauss = 0.0
                try:
                    add = float(accum.get(key, 0.0) or 0.0)
                except Exception:
                    add = 0.0
                value = _clip(0.82 * old + gauss + add, -NOISE_CLAMP, NOISE_CLAMP)
                self.noise[key] = round(value, 4)
                out[key] = round(value, 4)
            self._noise_accum = {}
        except Exception:
            pass
        return out


    @staticmethod
    def _loop_num(value, default: float = 0.0, lo: float = 0.0,
                  hi: float = 1.0) -> float:
        """Finite, bounded float for loop inputs (NaN/Inf -> default)."""
        try:
            num = float(value)
        except Exception:
            return default
        if num != num or num in (float("inf"), float("-inf")):
            return default
        return max(lo, min(hi, num))


    def blend_prior(self, new_value, prior, anchor=None) -> float:
        """Tversky 1974 / Nickerson 1998 anchor-weighted update."""
        try:
            new = float(new_value)
            old = float(prior)
        except Exception:
            return _clip(new_value)
        try:
            a = float(anchor if anchor is not None else self.anchor_weight)
        except Exception:
            a = 0.25
        a = max(0.0, min(0.9, a))
        return _clip((1.0 - a) * new + a * old, -1.0, 1.0)
