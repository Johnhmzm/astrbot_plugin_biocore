# -*- coding: utf-8 -*-
"""L0 identity/relationship mixin: identity threat, user feedback, trust seed.

Copied verbatim from BioCore; originals stay as _orig_* after the rename.
"""
from __future__ import annotations

try:
    from .bio_util import _clip
except Exception:  # pragma: no cover
    from bio_util import _clip


class IdentityMixin:
    """Copied verbatim from BioCore; originals stay as _orig_*."""

    @staticmethod
    def _identity_dims(dims):
        data = dims if isinstance(dims, dict) else {}

        def _n(key, default=0.0):
            try:
                return float(data.get(key, default) or default)
            except Exception:
                return default

        return _n("goal"), _n("blame"), _n("hit"), _n("involve")

    def detect_identity_threat(self, text=None, dims=None) -> bool:
        """item-6: identity threat from probe dims (blame/hit), not word tables."""
        del text
        _goal, blame, hit, involve = self._identity_dims(dims)
        return bool((blame >= 0.6 and involve >= 0.4) or hit >= 0.7)

    def apply_identity_threat(self, text=None, dims=None) -> bool:
        """task-43 (default OFF): identity threat -> bounded stress bump (<=0.08)."""
        if not getattr(self, "identity_threat_stress_enabled", False):
            return False
        if not self.detect_identity_threat(dims=dims):
            return False
        self.stress = _clip(float(getattr(self, "stress", 0.0)) + 0.06, 0.0, 1.0)
        return True

    def feedback_user(self, text=None, *, dims=None, cold=None, warm=None) -> None:
        """item-6: numeric user feedback (dims blame/hit vs goal/involve)."""
        del text
        goal, blame, hit, involve = self._identity_dims(dims)
        if cold is None:
            cold = max(blame, hit)
        if warm is None:
            warm = max(goal, 0.5 * involve)
        cold = _clip(cold, 0.0, 1.0)
        warm = _clip(warm, 0.0, 1.0)
        if cold > 0.0:
            self.trust = _clip(self.trust - 0.055 * cold, 0, 1)
            self.v = _clip(self.v - 0.035 * cold, -1, 1)
            self.stress = _clip(self.stress + 0.035 * cold, 0, 1)
            self.echo_trace = _clip(self.echo_trace - 0.03 * cold, -1, 1)
        if warm > 0.0:
            self.trust = _clip(self.trust + 0.012 * warm, 0, 1)
            self.v = _clip(self.v + 0.02 * warm, -1, 1)
            self.stress = _clip(self.stress - 0.01 * warm, 0, 1)

    def seed_trust_from_user(self, user_trust, weight=0.2, max_delta=0.05) -> float:
        """G3: one-shot bounded trust seed from the user-level record.

        The caller decides *when* (cold start / context rebuild); this method
        only applies the bounded EMA step and marks the core as seeded. Trust
        stays in [0,1] and a single step moves it by at most max_delta.
        """
        try:
            target = _clip(float(user_trust), 0.0, 1.0)
            current = _clip(float(self.trust), 0.0, 1.0)
            delta = float(weight) * (target - current)
            limit = abs(float(max_delta))
            delta = max(-limit, min(limit, delta))
            self.trust = _clip(current + delta, 0.0, 1.0)
            self._user_trust_seeded = True
            self._user_trust_seed_delta = round(delta, 4)
            return round(float(self.trust), 4)
        except Exception:
            return float(getattr(self, "trust", 0.5))
