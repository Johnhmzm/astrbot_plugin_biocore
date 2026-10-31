# -*- coding: utf-8 -*-
"""L0 emotion mixin #2: label inference, model-output apply, regulation helpers.

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
        REGULATION_STATS_HALF_LIFE_DAYS,
    )
except Exception:  # pragma: no cover
    from bio_const import (
        REGULATION_STATS_HALF_LIFE_DAYS,
    )

try:
    from .. import memory_meta
except Exception:  # pragma: no cover
    import memory_meta  # type: ignore


class Emotion2Mixin:
    """Copied verbatim from BioCore; originals stay as _orig_*."""

    def infer_labels(self, force: bool = False) -> None:
        """Derive labels from the biological state when the model omits them."""
        v = float(getattr(self, "v", 0.0))
        a = float(getattr(self, "a", 0.5))
        d = float(getattr(self, "d", 0.55))
        soc = float(getattr(self, "social", 0.55))
        stress = float(getattr(self, "stress", 0.0))
        energy = float(getattr(self, "energy", 0.8))
        trust = float(getattr(self, "trust", 0.5))
        inferred = {}
        if soc <= 0.47 and v <= 0.00:
            inferred["emotion"] = "loneliness"
        elif v >= 0.16 and a >= 0.40 and d >= 0.35:
            inferred["emotion"] = "joy"
        elif v <= -0.20 and a < 0.55:
            inferred["emotion"] = "sadness"
        elif v <= -0.12 and a >= 0.55 and d >= 0.50:
            inferred["emotion"] = "anger"
        elif v <= -0.08 and a >= 0.50 and d < 0.50:
            inferred["emotion"] = "fear"
        else:
            inferred["emotion"] = "neutral"
        if v >= 0.25 and soc >= 0.35:
            inferred["intent"] = "approach"
        elif v <= -0.25 or soc <= 0.30:
            inferred["intent"] = "withdraw"
        else:
            inferred["intent"] = "hold"
        if energy >= 0.68 and v >= 0.15:
            inferred["expression"] = "open"
        elif energy <= 0.35:
            inferred["expression"] = "short"
        else:
            inferred["expression"] = "normal"
        if soc <= 0.30:
            inferred["need"] = "space"
        elif stress >= 0.65:
            inferred["need"] = "vent" if trust >= 0.40 else "space"
        elif trust >= 0.60:
            inferred["need"] = "be_heard" if v <= 0.0 else "share"
        elif v <= -0.30:
            inferred["need"] = "space"
        else:
            inferred["need"] = "talk"
        inferred["energy"] = "high" if energy >= 0.70 else ("low" if energy <= 0.35 else "normal")
        inferred["stress"] = "overloaded" if stress >= 0.70 else ("tense" if stress >= 0.35 else "calm")
        for key, value in inferred.items():
            if force or not self.labels.get(key):
                self.labels[key] = value
        self.compound = self._compound_emotion()
        self.regulation = self._choose_regulation()
        self._apply_regulation()


    def apply_affect(self, meta: dict) -> None:
        if not isinstance(meta, dict):
            return
        def delta(key, lo=-0.30, hi=0.30):
            try:
                return _clip(meta.get(key, 0.0), lo, hi)
            except Exception:
                return 0.0
        self.v = _clip(self.v + delta("valence_delta"), -1, 1)
        self.a = _clip(self.a + delta("arousal_delta"), 0, 1)
        self.d = _clip(self.d + delta("dominance_delta"), -1, 1)
        self.social = _clip(self.social + delta("social_delta"), 0, 1)
        # Backward compatibility with old tags that only sent stress/energy.
        if "dominance_delta" not in meta and "stress_delta" in meta:
            self.d = _clip(self.d - delta("stress_delta") * 0.5, -1, 1)
        if "social_delta" not in meta and "stress_delta" in meta:
            self.social = _clip(self.social - max(0.0, delta("stress_delta")) * 0.4, 0, 1)
        self.trust = _clip(self.trust + delta("trust_delta"), 0, 1)
        self.momentum["v"] = _clip(0.75 * float(self.momentum.get("v", 0.0)) + 0.25 * delta("valence_delta"), -1, 1)
        self.momentum["a"] = _clip(0.75 * float(self.momentum.get("a", 0.0)) + 0.25 * delta("arousal_delta"), -1, 1)
        self.momentum["d"] = _clip(0.75 * float(self.momentum.get("d", 0.0)) + 0.25 * delta("dominance_delta"), -1, 1)
        self.momentum["social"] = _clip(0.75 * float(self.momentum.get("social", 0.0)) + 0.25 * delta("social_delta"), -1, 1)
        self.v = _clip(self.v + 0.12 * self.momentum["v"], -1, 1)
        self.a = _clip(self.a + 0.12 * self.momentum["a"], 0, 1)
        self.d = _clip(self.d + 0.12 * self.momentum["d"], -1, 1)
        self.social = _clip(self.social + 0.12 * self.momentum["social"], 0, 1)
        for _k in ("novelty", "goal_relevance", "coping", "agency"):
            if _k + "_delta" in meta:
                self.appraisal[_k] = _clip(float(self.appraisal.get(_k, 0.0)) + delta(_k + "_delta"), 0, 1)
        self._derive()
        allowed = {
            "emotion": {"joy", "sadness", "anger", "fear", "loneliness", "neutral"},
            "intent": {"approach", "hold", "withdraw"},
            "expression": {"open", "normal", "short"},
            "need": {"share", "space", "vent", "be_heard", "talk"},
            "energy": {"low", "normal", "high"},
            "stress": {"calm", "tense", "overloaded"},
        }
        for key, values in allowed.items():
            value = str(meta.get(key) or "").strip()
            if value in values:
                self.labels[key] = value
        # task-39 §9.3: optional soft-bounded negative feedback replacing the
        # final hard clamp. Default OFF => bit-identical to the legacy _clip path.
        if getattr(self, "soft_bound_enabled", False):
            try:
                _prof = self.profile if isinstance(self.profile, dict) else {}
                _k = float(getattr(self, "soft_bound_k", 0.10) or 0.10)
                _mf = float(getattr(self, "soft_bound_m_frac", 0.08) or 0.08)
                _lam = float(getattr(self, "soft_bound_lam", 0.10) or 0.10)
                _bv = float(_prof.get("baseline_v", 0.05) or 0.05)
                _ba = float(_prof.get("baseline_a", 0.40) or 0.40)
                self.v = memory_meta.soft_bounded(self.v, _bv, -1.0, 1.0, _k, _mf, _lam)
                self.a = memory_meta.soft_bounded(self.a, _ba, 0.0, 1.0, _k, _mf, _lam)
                self.d = memory_meta.soft_bounded(self.d, 0.5, -1.0, 1.0, _k, _mf, _lam)
                self.social = memory_meta.soft_bounded(self.social, 0.5, 0.0, 1.0, _k, _mf, _lam)
                self.trust = memory_meta.soft_bounded(self.trust, 0.5, 0.0, 1.0, _k, _mf, _lam)
            except Exception:
                pass
        self._derive()
        self.infer_labels(force=False)
        self.ticks += 1
        self.noise["valence"] = _clip(0.7 * self.noise["valence"] + 0.3 * delta("valence_delta"), -0.3, 0.3)
        self.noise["stress"] = _clip(0.8 * self.noise["stress"] + 0.2 * delta("stress_delta"), -0.3, 0.3)
        self.echo_trace = _clip(0.88 * self.echo_trace + 0.12 * (self.v - self.stress * 0.5), -1, 1)
        self.echo = _clip(0.7 * self.echo + 0.3 * self.echo_trace, -1, 1)
        upper = _clip(0.6 * max(0.0, self.v) + 0.2 * self.trust, 0, 1)
        lower = _clip(0.6 * max(0.0, -self.v) + 0.3 * self.stress, 0, 1)
        self.ripple = {"upper": round(upper, 3), "lower": round(lower, 3),
                       "overlap": round(min(upper, lower), 3), "energy": round((upper + lower) / 2, 3)}
        self.spiking = {"rate": round(0.02 + self.energy * 0.08, 3),
                        "variance": round(0.01 + self.stress * 0.05, 4),
                        "ei": round(0.2 + self.trust * 0.3, 3)}


    def _regulation_rate(self, strategy: str, now: float = None) -> float:
        """G4: recency-weighted success rate for one regulation strategy.

        Raw uses/success/cost stay cumulative; the score is multiplied by an
        exponential recency weight derived from last_update (half-life
        REGULATION_STATS_HALF_LIFE_DAYS). Read-only: stats are never rewritten
        here, and legacy stats without last_update keep their old score.
        """
        try:
            st = (getattr(self, "regulation_stats", None) or {}).get(strategy) or {}
            uses = int(st.get("uses", 0) or 0)
            if uses <= 0:
                return 0.0
            success = float(st.get("success", 0) or 0)
            cost = float(st.get("cost", 0) or 0)
            score = success / uses - 0.05 * (cost / uses)
            last = st.get("last_update")
            if last is None:
                return score
            current = float(now if now is not None else time.time())
            elapsed_days = max(0.0, current - float(last)) / 86400.0
            return score * (0.5 ** (elapsed_days / REGULATION_STATS_HALF_LIFE_DAYS))
        except Exception:
            return 0.0


    def feedback(self, reply: str) -> None:
        r = str(reply or "")
        warm = 0.008 * sum(1 for w in ("谢谢", "在", "陪", "懂", "一起", "抱") if w in r)
        self.trust = _clip(self.trust + warm, 0, 1)
        self.social = _clip(self.social + warm * 0.5, 0, 1)
        self._derive()
        self.echo_trace = _clip(0.9 * self.echo_trace + 0.1 * warm, -1, 1)


    def record_reply(self, text: str = "", meta=None) -> None:
        try:
            emo = str((self.labels or {}).get("emotion") or "neutral")
            self.history.append({
                "ts": __import__("time").time(),
                "emotion": emo,
                "compound": str(self.compound or ""),
                "intensity": round(float(self._intensity()), 3),
                "v": round(float(self.v), 3),
                "a": round(float(self.a), 3),
                "d": round(float(self.d), 3),
                "social": round(float(self.social), 3),
                "text": str(text or "")[:80],
            })
            if len(self.history) > 80:
                self.history = self.history[-80:]
        except Exception:
            pass
