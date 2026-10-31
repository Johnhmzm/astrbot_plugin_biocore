# -*- coding: utf-8 -*-
"""L0 bio utility mixin: pure text/vector helpers extracted from BioCore.

Behaviour is copied verbatim from main.py; no logic changes.
"""
from __future__ import annotations

import re


def _clip(value, low=-1.0, high=1.0):
    try:
        v = float(value)
    except Exception:
        v = 0.0
    return max(low, min(high, v))


class UtilMixin:
    """Stateless helpers. BioCore inherits this mixin."""
    @staticmethod
    def _word_hit(text: str, word: str) -> bool:
        idx = text.find(word)
        while idx >= 0:
            prefix = text[max(0, idx - 2):idx]
            if not prefix.endswith(("不", "没", "别", "无")):
                return True
            idx = text.find(word, idx + len(word))
        return False


    @staticmethod
    def _cosine_static(a, b) -> float:
        try:
            aa = [float(x) for x in (a or [])]
            bb = [float(x) for x in (b or [])]
            if not aa or not bb:
                return 0.0
            return sum(x * y for x, y in zip(aa, bb))
        except Exception:
            return 0.0


    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        a = str(a or "")
        b = str(b or "")
        if not a or not b:
            return 0.0
        def grams(x):
            x = re.sub(r"\s+", "", x)
            return {x[i:i + 2] for i in range(max(0, len(x) - 1))}
        ga, gb = grams(a), grams(b)
        if not ga or not gb:
            return 0.0
        return len(ga & gb) / float(len(ga | gb))


    def _intensity(self) -> float:
        """Normalized current emotional intensity (0..1)."""
        v = abs(float(getattr(self, "v", 0.0)))
        a = float(getattr(self, "a", 0.5))
        d = abs(float(getattr(self, "d", 0.5)) - 0.5) * 2.0
        soc = abs(float(getattr(self, "social", 0.5)) - 0.5) * 2.0
        stress = float(getattr(self, "stress", 0.0))
        return max(0.0, min(1.0, 0.30 * v + 0.30 * a + 0.20 * stress + 0.10 * d + 0.10 * soc))


    def _derive(self) -> None:
        """Derive stress/energy from v, a, dominance, social (they are not independent)."""
        v = float(getattr(self, "v", 0.0))
        a = float(getattr(self, "a", 0.5))
        d = float(getattr(self, "d", 0.55))
        soc = float(getattr(self, "social", 0.55))
        self.stress = _clip(0.45 * max(0.0, -v) * a + 0.35 * (1.0 - d) + 0.20 * (1.0 - soc), 0, 1)
        _offset = 0.0
        try:
            _offset = _clip(float(getattr(self, "_metabolic_energy_offset", 0.0)), 0.0, 0.20)
        except Exception:
            _offset = 0.0
        self.energy = _clip(0.45 * a + 0.25 * max(0.0, v) + 0.20 * d + 0.10 * soc - _offset, 0, 1)

