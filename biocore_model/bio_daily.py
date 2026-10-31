# -*- coding: utf-8 -*-
"""L0 daily/regulation mixin: daily digest, reply consistency, regulation."""
from __future__ import annotations

import time

try:
    from .bio_util import _clip
except Exception:  # pragma: no cover
    from bio_util import _clip

try:
    from .bio_const import (
        AFFECT_LABEL_COOLDOWN_SECONDS,
        AFFECT_LABEL_MIN_AROUSAL,
        AFFECT_LABEL_MIN_TOP_P,
        LEARNING_Q_WEIGHT,
        REGULATION_COST,
    )
except Exception:  # pragma: no cover
    from bio_const import (
        AFFECT_LABEL_COOLDOWN_SECONDS,
        AFFECT_LABEL_MIN_AROUSAL,
        AFFECT_LABEL_MIN_TOP_P,
        LEARNING_Q_WEIGHT,
        REGULATION_COST,
    )

try:
    from .. import memory_meta
except Exception:  # pragma: no cover
    import memory_meta  # type: ignore


class DailyMixin:
    """Copied verbatim from BioCore; originals stay as _orig_* after the rename."""

    def update_daily_digest(self, now=None, event_ids=None) -> dict:
        """Deterministic daily digest base; no narrative/LLM. Bounded to 30 days."""
        try:
            current = float(time.time() if now is None else now)
            date = time.strftime("%Y-%m-%d", time.localtime(current))
            accum = getattr(self, "_daily_accum", None)
            if not isinstance(accum, dict):
                accum = {"date": "", "n": 0, "v": 0.0, "a": 0.0, "stress": 0.0,
                         "emotions": {}, "ticks": 0, "event_ids": []}
            if accum.get("date") and accum.get("date") != date:
                if int(accum.get("n", 0) or 0) > 0:
                    emotions = accum.get("emotions") or {}
                    dominant = max(emotions.items(), key=lambda kv: kv[1])[0] if emotions else "neutral"
                    n = int(accum.get("n", 1) or 1)
                    self.daily_digests.append({
                        "date": str(accum.get("date")),
                        "event_ids": [str(x) for x in (accum.get("event_ids") or [])[-50:] if str(x)],
                        "mean_v": round(float(accum.get("v", 0.0) or 0.0) / n, 4),
                        "mean_a": round(float(accum.get("a", 0.0) or 0.0) / n, 4),
                        "mean_stress": round(float(accum.get("stress", 0.0) or 0.0) / n, 4),
                        "dominant_emotion": dominant,
                        "interaction_count": n,
                    })
                    self.daily_digests = self.daily_digests[-30:]
                accum = {"date": date, "n": 0, "v": 0.0, "a": 0.0, "stress": 0.0,
                         "emotions": {}, "ticks": 0, "event_ids": []}
            accum["date"] = date
            accum["n"] = int(accum.get("n", 0) or 0) + 1
            accum["v"] = float(accum.get("v", 0.0) or 0.0) + float(self.v)
            accum["a"] = float(accum.get("a", 0.0) or 0.0) + float(self.a)
            accum["stress"] = float(accum.get("stress", 0.0) or 0.0) + float(self.stress)
            _emo = str((self.labels or {}).get("emotion") or "neutral")
            emotions = accum.get("emotions") if isinstance(accum.get("emotions"), dict) else {}
            emotions[_emo] = int(emotions.get(_emo, 0) or 0) + 1
            accum["emotions"] = emotions
            accum["ticks"] = int(accum.get("ticks", 0) or 0) + 1
            if isinstance(event_ids, (list, tuple)):
                _eids = accum.get("event_ids") if isinstance(accum.get("event_ids"), list) else []
                for _eid in event_ids:
                    if str(_eid) and str(_eid) not in _eids:
                        _eids.append(str(_eid))
                accum["event_ids"] = _eids[-50:]
            self._daily_accum = accum
            return dict(accum)
        except Exception:
            return {}


    def evaluate_reply_consistency(self, text, now=None) -> dict:
        """task-36: deterministic reply/intent consistency (0..1, read-only).

        Heuristic checks only (length bands vs labels need/expression). It never
        rewrites the reply and is only stored when reply_consistency_enabled.
        """
        value = str(text or "").strip()
        checks = []
        score = 1.0
        try:
            labels = getattr(self, "labels", {}) or {}
            need = str(labels.get("need") or "talk")
            expression = str(labels.get("expression") or "normal")
            if not value:
                score = 0.0
                checks.append("empty")
            else:
                length = len(value)
                if length > 240:
                    score -= 0.20
                    checks.append("too_long")
                if length < 2:
                    score -= 0.30
                    checks.append("too_short")
                if need == "space" and length > 60:
                    score -= 0.20
                    checks.append("space_but_long")
                if need == "talk" and length < 4:
                    score -= 0.10
                    checks.append("talk_but_short")
                if expression == "normal" and value.count("！") >= 4:
                    score -= 0.10
                    checks.append("too_excited")
        except Exception:
            checks.append("error")
        try:
            stamp = float(now if now is not None else time.time())
        except Exception:
            stamp = time.time()
        return {"score": round(_clip(score, 0.0, 1.0), 4),
                "length": len(value), "checks": checks[:6],
                "ts": round(stamp, 3)}


    def _choose_regulation(self) -> str:
        stress = float(getattr(self, "stress", 0.0))
        trust = float(getattr(self, "trust", 0.5))
        soc = float(getattr(self, "social", 0.5))
        arousal = float(getattr(self, "a", 0.5))
        attention = float(getattr(self, "attention", 0.5))
        emo = str(self.labels.get("emotion") or "neutral")
        if stress >= 0.65:
            if trust >= 0.55:
                return "seek_comfort"
            if soc <= 0.30:
                return "avoid"
            return "reappraise"
        _cands = []
        if emo in ("anger", "fear"):
            _cands = (["suppress", "reappraise", "distraction"] if soc < 0.50
                      else ["reappraise", "express", "distraction"])
            if arousal >= 0.72:
                _cands = ["distraction"] + _cands
        elif emo == "sadness":
            _cands = ["express", "reappraise", "seek_comfort", "distraction"]
        elif emo == "loneliness":
            _cands = ["seek_comfort", "avoid", "express", "distraction"]
        elif stress >= 0.45 and arousal >= 0.70 and attention < 0.55:
            _cands = ["distraction", "reappraise"]
        # Batch4 B2: affect labeling (naming the emotion) is the 7th strategy.
        # Deterministic trigger: spectrum top1 >= 0.45 and arousal >= 0.50.
        if _cands and arousal >= AFFECT_LABEL_MIN_AROUSAL:
            try:
                _top_p = max((float(x.get("p", 0.0) or 0.0)
                              for x in self._spectrum_probs() if isinstance(x, dict)),
                             default=0.0)
            except Exception:
                _top_p = 0.0
            try:
                _label_stats = (getattr(self, "regulation_stats", {}) or {}).get(
                    "label_emotion") or {}
                _last_label = _label_stats.get("last_update")
                if _last_label is None:
                    _label_ready = True
                else:
                    _label_ready = (time.time() - float(_last_label)
                                    >= AFFECT_LABEL_COOLDOWN_SECONDS)
            except Exception:
                _label_ready = True
            if _top_p >= AFFECT_LABEL_MIN_TOP_P and _label_ready:
                _cands = ["label_emotion"] + _cands
        if _cands:
            if getattr(self, "regulation_stats", None):
                _qs = (getattr(self, "_learning", {}) or {}).get("params", {}).get("regulation_q", {}) if getattr(self, "bio_learning", False) else {}
                _cands.sort(key=lambda s: self._regulation_rate(s) + (LEARNING_Q_WEIGHT * float((_qs or {}).get(s, 0.0) or 0.0)), reverse=True)
            return _cands[0]
        return "none"


    def _record_regulation(self, strategy: str, pre_stress: float) -> None:
        """Persist uses / success / cumulative stress change / cost + last_update."""
        if not strategy or strategy == "none":
            return
        try:
            stats = self.regulation_stats
            st = stats.setdefault(strategy, {"uses": 0, "success": 0, "stress_delta": 0.0, "cost": 0.0})
            uses = int(st.get("uses", 0) or 0) + 1
            delta = float(getattr(self, "stress", 0.0)) - float(pre_stress)
            st["uses"] = uses
            st["stress_delta"] = round(float(st.get("stress_delta", 0.0) or 0.0) + delta, 5)
            st["cost"] = round(float(st.get("cost", 0.0) or 0.0) + float(REGULATION_COST.get(strategy, 0.003)), 5)
            st["last_update"] = round(time.time(), 3)
            if getattr(self, "bio_learning", False):
                try:
                    # Daw 2011 Q-learning; min-sample N=5 + step cap 0.02 (review BLOCK-05).
                    r = max(-1.0, min(1.0, (-delta) * 10.0
                                      - 0.05 * float(REGULATION_COST.get(strategy, 0.003))
                                      + 0.10 * float(getattr(self, "a", 0.5))))
                    qs = self._learning.setdefault("params", {}).setdefault("regulation_q", {})
                    evidence = self._learning.setdefault("evidence", {}).setdefault("regulation_q", {})
                    ev = evidence.get(strategy) if isinstance(evidence.get(strategy), dict) else {"n": 0, "sum_pe": 0.0}
                    old_q = float(qs.get(strategy, 0.0) or 0.0)
                    ev["n"] = int(ev.get("n", 0) or 0) + 1
                    ev["sum_pe"] = float(ev.get("sum_pe", 0.0) or 0.0) + (r - old_q)
                    evidence[strategy] = ev
                    if int(ev.get("n", 0)) >= 5:
                        alpha = memory_meta.nassar_alpha(float(ev["sum_pe"]) / int(ev["n"]))
                        delta_q = max(-0.02, min(0.02, alpha * float(ev["sum_pe"]) / int(ev["n"])))
                        new_q = max(-1.0, min(1.0, old_q + delta_q))
                        qs[strategy] = round(new_q, 5)
                        evidence[strategy] = {"n": 0, "sum_pe": 0.0}
                        self._learning["updates_count"] = int(self._learning.get("updates_count", 0) or 0) + 1
                        self._learning["last_update"] = round(time.time(), 3)
                        log = self._learning.get("log") if isinstance(self._learning.get("log"), list) else []
                        log.append({"ts": round(time.time(), 3), "param": "regulation_q." + str(strategy),
                                    "old": round(old_q, 5), "new": round(new_q, 5),
                                    "reason": "delta_stress", "samples": 5})
                        self._learning["log"] = log[-20:]
                except Exception:
                    pass
            if delta <= 0.0005:
                st["success"] = int(st.get("success", 0) or 0) + 1
        except Exception:
            pass


    def _apply_regulation(self) -> None:
        r = self.regulation
        _pre_stress = float(self.stress)
        if r == "seek_comfort":
            self.social = _clip(self.social + 0.03, 0, 1)
            self.stress = _clip(self.stress - 0.02, 0, 1)
        elif r == "reappraise":
            self.stress = _clip(self.stress - 0.04, 0, 1)
            self.v = _clip(self.v + 0.015, -1, 1)
        elif r == "suppress":
            self.stress = _clip(self.stress + 0.01, 0, 1)
            self.v = _clip(self.v - 0.005, -1, 1)
        elif r == "avoid":
            self.social = _clip(self.social - 0.03, 0, 1)
        elif r == "express":
            self.v = _clip(self.v + 0.01, -1, 1)
            self.stress = _clip(self.stress - 0.01, 0, 1)
        elif r == "label_emotion":
            # Batch4 B2: name the feeling; deliberately tiny effects (not a
            # comfort button): v toward 0, arousal/stress slightly down.
            self.v = _clip(self.v + 0.005, -1, 1)
            self.a = _clip(self.a - 0.01, 0, 1)
            self.stress = _clip(self.stress - 0.005, 0, 1)
        elif r == "distraction":
            # Brief relief: lower arousal/stress now, but attention and the
            # current goal pay for it because the concern is left unaddressed.
            self.a = _clip(self.a - 0.06, 0, 1)
            self.stress = _clip(self.stress - 0.035, 0, 1)
            self.attention = _clip(self.attention - 0.05, 0, 1)
            _focus = str(getattr(self, "goal_focus", "") or "")
            for g in self.goals:
                if str(g.get("name") or "") == _focus:
                    g["progress"] = round(max(0.0, float(g.get("progress", 0) or 0) - 0.005), 5)
                    break
        self._derive()
        self._record_regulation(r, _pre_stress)
