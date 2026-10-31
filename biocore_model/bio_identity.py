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
    def detect_identity_threat(text) -> bool:
        """Swann 1987 proxy: deterministic self/role/narrative conflict cues."""
        value = str(text or "")
        cues = ("你不是她", "你不是你", "不配", "工具", "废物", "假的", "装的",
                "人设", "角色", "根本不懂", "不是真的", "换个人", "你变了")
        return any(cue in value for cue in cues)


    def apply_identity_threat(self, text) -> bool:
        """task-43 (default OFF): identity threat -> bounded stress bump (<=0.08)."""
        if not getattr(self, "identity_threat_stress_enabled", False):
            return False
        if not self.detect_identity_threat(text):
            return False
        self.stress = _clip(float(getattr(self, "stress", 0.0)) + 0.06, 0.0, 1.0)
        return True


    def feedback_user(self, text: str) -> None:
        t = str(text or "")
        cold_words = ("废物", "垃圾", "讨厌", "滚", "闭嘴", "没用", "蠢", "去死", "别烦", "傻子")
        warm_words = ("谢谢", "喜欢", "陪", "辛苦", "厉害", "可爱", "抱")
        cold = sum(1 for w in cold_words if self._word_hit(t, w))
        warm = sum(1 for w in warm_words if self._word_hit(t, w))
        if cold:
            self.trust = _clip(self.trust - 0.055 * cold, 0, 1)
            self.v = _clip(self.v - 0.035 * cold, -1, 1)
            self.stress = _clip(self.stress + 0.035 * cold, 0, 1)
            self.echo_trace = _clip(self.echo_trace - 0.03 * cold, -1, 1)
        if warm:
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
