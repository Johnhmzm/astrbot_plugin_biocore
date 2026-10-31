# -*- coding: utf-8 -*-
"""L0 emotion mixin: leaf emotion helpers extracted from BioCore."""
from __future__ import annotations

try:
    from .bio_util import _clip
except Exception:  # pragma: no cover
    from bio_util import _clip

try:
    from .bio_const import (
        EMOTION_SPECTRUM,
        LEX,
        RECOVERY_CONTEXT_MAX,
        RECOVERY_CONTEXT_MIN,
        SENSITIZATION_HALF_LIFE_HOURS,
        SENSITIZATION_HISTORY_MAX,
        SENSITIZATION_HISTORY_MAX_AGE,
        SENSITIZATION_MAX,
        SENSITIZATION_STEP,
        SENSITIZATION_STRONG_NEG_DV,
        SPECTRUM_FAMILY,
    )
except Exception:  # pragma: no cover
    from bio_const import (
        EMOTION_SPECTRUM,
        LEX,
        RECOVERY_CONTEXT_MAX,
        RECOVERY_CONTEXT_MIN,
        SENSITIZATION_HALF_LIFE_HOURS,
        SENSITIZATION_HISTORY_MAX,
        SENSITIZATION_HISTORY_MAX_AGE,
        SENSITIZATION_MAX,
        SENSITIZATION_STEP,
        SENSITIZATION_STRONG_NEG_DV,
        SPECTRUM_FAMILY,
    )

import math
import re
import time

try:
    from .. import homeostasis
except Exception:  # pragma: no cover
    import homeostasis


class EmotionMixin:
    """Emotion helpers that only use self state. BioCore inherits this."""
    def _compound_emotion(self) -> str:
        v = float(getattr(self, "v", 0.0))
        a = float(getattr(self, "a", 0.5))
        d = float(getattr(self, "d", 0.5))
        soc = float(getattr(self, "social", 0.5))
        trust = float(getattr(self, "trust", 0.5))
        w = {
            "joy": max(0.0, v) * max(0.2, a),
            "trust": trust * max(0.0, 1.0 - abs(v)),
            "sadness": max(0.0, -v) * (1.0 - a * 0.5),
            "anger": max(0.0, -v) * a * max(0.0, d - 0.5) * 2.0,
            "fear": max(0.0, -v) * a * max(0.0, 0.5 - d) * 2.0,
            "loneliness": max(0.0, -v) * max(0.0, 0.7 - soc),
            "surprise": max(0.0, float(self.appraisal.get("novelty", 0.0) or 0.0)) * max(0.2, a),
            "anticipation": max(0.0, float(self.appraisal.get("goal_relevance", 0.0) or 0.0)) * max(0.2, a),
            "disgust": max(0.0, -v) * max(0.0, 1.0 - a) * max(0.0, 0.6 - soc),
        }
        top = sorted(w.items(), key=lambda kv: kv[1], reverse=True)[:2]
        if len(top) < 2 or top[1][1] < 0.08:
            return ""
        pair = frozenset((top[0][0], top[1][0]))
        names = {
            frozenset(("joy", "trust")): "亲近",
            frozenset(("joy", "fear")): "不安的期待",
            frozenset(("joy", "sadness")): "苦甜参半",
            frozenset(("joy", "anger")): "复杂",
            frozenset(("joy", "loneliness")): "热闹中的空",
            frozenset(("trust", "fear")): "顺从的不安",
            frozenset(("trust", "sadness")): "失落",
            frozenset(("trust", "anger")): "失望的怒",
            frozenset(("trust", "loneliness")): "想念",
            frozenset(("fear", "sadness")): "无助",
            frozenset(("fear", "anger")): "戒备",
            frozenset(("fear", "loneliness")): "被抛下",
            frozenset(("sadness", "anger")): "委屈",
            frozenset(("sadness", "loneliness")): "空落",
            frozenset(("anger", "loneliness")): "被排斥的怒",
        }
        names.update({
            frozenset(("joy", "surprise")): "惊喜",
            frozenset(("trust", "surprise")): "敬畏",
            frozenset(("fear", "surprise")): "惊骇",
            frozenset(("sadness", "surprise")): "意外失落",
            frozenset(("disgust", "surprise")): "错愕",
            frozenset(("anger", "surprise")): "暴怒",
            frozenset(("anticipation", "surprise")): "期待",
            frozenset(("joy", "anticipation")): "乐观",
            frozenset(("trust", "anticipation")): "希望",
            frozenset(("fear", "anticipation")): "焦虑",
            frozenset(("sadness", "anticipation")): "悲观",
            frozenset(("disgust", "anticipation")): "蔑视",
            frozenset(("anger", "anticipation")): "攻击性",
            frozenset(("joy", "disgust")): "幸灾乐祸",
            frozenset(("trust", "disgust")): "矛盾",
            frozenset(("fear", "disgust")): "厌恶恐惧",
            frozenset(("sadness", "disgust")): "懊悔",
            frozenset(("joy", "sadness")): "苦甜参半",
            frozenset(("trust", "anger")): "失望的怒",
            frozenset(("surprise", "anticipation")): "警觉",
            frozenset(("disgust", "anger")): "轻蔑",
            frozenset(("disgust", "sadness")): "嫌恶",
            frozenset(("disgust", "fear")): "恶心",
            frozenset(("disgust", "trust")): "勉强接受",
            frozenset(("surprise", "joy")): "惊喜",
            frozenset(("surprise", "fear")): "惊骇",
            frozenset(("anticipation", "joy")): "乐观",
            frozenset(("anticipation", "fear")): "焦虑",
        })
        return names.get(pair, "混合")


    def _recovery_speed(self) -> float:
        """Batch4 B4: contextual recovery-speed multiplier, bounded [0.8, 1.2].

        speed = clamp(0.85 + 0.30*recovery_rate
                      + 0.05*(2*coping_success - 1)
                      + 0.05*(circadian_alertness - 0.5), 0.8, 1.2)
        Applied as HL/speed only to dimensions below baseline (v<0, a>0.40,
        social<0.55), so recovery is faster after rest/support and slower when
        recovery_rate is low. Deterministic, no LLM, no new stored field.
        """
        try:
            rate = _clip(float((getattr(self, "profile", {}) or {}).get(
                "recovery_rate", 0.62) or 0.62), 0.0, 1.0)
        except Exception:
            rate = 0.62
        success = 0.5
        try:
            stats = getattr(self, "regulation_stats", {}) or {}
            uses = sum(int(v.get("uses", 0) or 0) for v in stats.values()
                       if isinstance(v, dict))
            succ = sum(int(v.get("success", 0) or 0) for v in stats.values()
                       if isinstance(v, dict))
            if uses > 0:
                success = _clip(succ / uses, 0.0, 1.0)
        except Exception:
            success = 0.5
        try:
            alert = _clip(float(getattr(self, "circadian_alertness", 0.5) or 0.5), 0.0, 1.0)
        except Exception:
            alert = 0.5
        speed = (0.85 + 0.30 * rate + 0.05 * (2.0 * success - 1.0)
                 + 0.05 * (alert - 0.5))
        return max(RECOVERY_CONTEXT_MIN, min(RECOVERY_CONTEXT_MAX, speed))


    def _spectrum_probs(self) -> list:
        try:
            out = []
            for it in self._spectrum():
                dist = max(0.001, float(it.get("distance", 1.0)))
                out.append({"key": it.get("key"), "name": it.get("name"), "p": round(1.0 / dist, 4)})
            total = sum(x["p"] for x in out) or 1.0
            for x in out:
                x["p"] = round(x["p"] / total, 4)
            return out
        except Exception:
            return []


    def _spectrum(self) -> list:
        v = (float(getattr(self, "v", 0.0)) + 1.0) / 2.0
        a = float(getattr(self, "a", 0.5))
        d = (float(getattr(self, "d", 0.5)) + 1.0) / 2.0
        soc = float(getattr(self, "social", 0.5))
        out = []
        _emo_bias = {
            "sadness": {"disappointment": 0.42, "empathic_pain": 0.36, "guilt": 0.18},
            "anger": {"anger": 0.52, "contempt": 0.30, "disgust": 0.18},
            "fear": {"fear": 0.52, "anxiety": 0.42, "horror": 0.24},
            "loneliness": {"empathic_pain": 0.42, "disappointment": 0.36, "nostalgia": 0.24},
            "joy": {"joy": 0.52, "contentment": 0.36, "amusement": 0.24},
        }.get(str((self.labels or {}).get("emotion") or ""), {})
        _protos = {}
        try:
            _protos = self._calibrate_spectrum_prototypes()
        except Exception:
            _protos = {}
        for key, cn, sv, sa, sd, ss in EMOTION_SPECTRUM:
            _p = _protos.get(key)
            if _p:
                sv, sa, sd, ss = _p
            dv = v - ((sv + 1.0) / 2.0)
            dd = d - ((sd + 1.0) / 2.0)
            dist = (dv * dv * 1.2 + (a - sa) ** 2 + dd * dd + (soc - ss) ** 2) ** 0.5
            dist = max(0.0, dist - float(_emo_bias.get(key, 0.0)))
            out.append((round(dist, 3), key, cn))
        out.sort(key=lambda x: x[0])
        return [{"key": k, "name": n, "distance": dist} for dist, k, n in out[:3]]


    def _calibrate_spectrum_prototypes(self) -> dict:
        """Cowen & Keltner (2017) style prototype calibration.

        Each EMOTION_SPECTRUM anchor is mixed with the centroid of this core's
        own state history for the matching emotion family. Pure anchors are
        used until at least two observations exist, so a single turn cannot
        move the emotion map. Deterministic: no RNG, no LLM call.
        """
        anchors = {key: (sv, sa, sd, ss) for key, cn, sv, sa, sd, ss in EMOTION_SPECTRUM}
        sums = {}
        counts = {}
        hist = list(getattr(self, "history", []) or [])[-80:]
        cur_d = float(getattr(self, "d", 0.55))
        cur_soc = float(getattr(self, "social", 0.55))
        for h in hist:
            if not isinstance(h, dict):
                continue
            emo = str(h.get("emotion") or "").strip()
            keys = SPECTRUM_FAMILY.get(emo)
            if not keys:
                continue
            try:
                w = max(0.05, min(1.0, float(h.get("intensity", 0.5) or 0.5)))
            except Exception:
                w = 0.5
            try:
                hv = float(h.get("v", 0.0))
                ha = float(h.get("a", 0.5))
            except Exception:
                continue
            try:
                hd = float(h.get("d", cur_d))
            except Exception:
                hd = cur_d
            try:
                hs = float(h.get("social", cur_soc))
            except Exception:
                hs = cur_soc
            for key in keys:
                if key not in anchors:
                    continue
                acc = sums.setdefault(key, [0.0, 0.0, 0.0, 0.0, 0.0])
                acc[0] += hv * w
                acc[1] += ha * w
                acc[2] += hd * w
                acc[3] += hs * w
                acc[4] += w
                counts[key] = int(counts.get(key, 0) or 0) + 1
        out = {}
        for key, anchor in anchors.items():
            acc = sums.get(key)
            n = int(counts.get(key, 0) or 0)
            if acc and n >= 2 and acc[4] > 0:
                alpha = min(0.35, 0.06 * n)
                centroid = [acc[0] / acc[4], acc[1] / acc[4], acc[2] / acc[4], acc[3] / acc[4]]
                out[key] = tuple((1.0 - alpha) * anchor[i] + alpha * centroid[i] for i in range(4))
            else:
                out[key] = anchor
        self._spectrum_calibration_meta = {
            "samples": len(hist),
            "families": len({str(h.get("emotion") or "") for h in hist
                             if SPECTRUM_FAMILY.get(str(h.get("emotion") or ""))}),
            "calibrated": sum(1 for k in anchors if int(counts.get(k, 0) or 0) >= 2),
        }
        return out


    def observe(self, text: str, embedding=None) -> None:
        self._decay_to_now()
        self._query_embedding = embedding
        _pre_stress = float(self.stress)
        t = str(text or "")
        self._update_goals(t)
        _event_key = ""
        for _anchor in getattr(self, "event_anchors", []) or []:
            _sim = self._text_similarity(re.sub(r"\s+", "", t)[:120], str(_anchor.get("title", "")))
            if self._query_embedding and _anchor.get("embedding"):
                _sim = max(_sim, self._cosine_static(self._query_embedding, _anchor.get("embedding")))
            if _sim >= 0.55:
                _event_key = str(_anchor.get("key", ""))
                break
        v_delta, a_delta, d_delta, social_delta = 0.0, 0.0, 0.0, 0.0
        _hits = []
        for label, words in LEX.items():
            if not any(self._word_hit(t, w) for w in words):
                continue
            _hits.append(label)
            if label == "joy":
                v_delta += 0.12
                a_delta += 0.05
                d_delta += 0.04
                social_delta += 0.03
            elif label == "sadness":
                v_delta -= 0.14
                a_delta -= 0.03
                d_delta -= 0.05
            elif label == "loneliness":
                v_delta -= 0.12
                a_delta -= 0.03
                d_delta -= 0.04
                social_delta -= 0.16
            elif label == "anger":
                v_delta -= 0.12
                a_delta += 0.15
                d_delta += 0.10
                social_delta -= 0.05
            elif label == "fear":
                v_delta -= 0.16
                a_delta += 0.14
                d_delta -= 0.12
                social_delta -= 0.03
        # Short-term habituation: repeated equivalent emotional stimuli decay.
        _now = time.time()
        # B-T06: generic novelty history (also covers non-emotional repeated text).
        try:
            _novelty_text = re.sub(r"\s+", "", t)[:160]
            if _novelty_text:
                _hist = getattr(self, "_novelty_history", [])
                _seen_before = any(
                    self._text_similarity(_novelty_text, str(x)) >= 0.65
                    for x in _hist[-12:])
                if _seen_before:
                    self.boredom = _clip(self.boredom + 0.06 * (1.0 - self.boredom), 0.0, 1.0)
                    self.novelty_need = _clip(self.novelty_need + 0.03 * (1.0 - self.novelty_need), 0.0, 1.0)
                else:
                    self.boredom = _clip(self.boredom - 0.08, 0.0, 1.0)
                    self.novelty_need = _clip(0.94 * self.novelty_need + 0.06 * 0.5, 0.0, 1.0)
                self._novelty_history = (_hist + [_novelty_text])[-20:]
        except Exception:
            pass
        # Batch4 B5: information-gap curiosity proxy. Question/unknown cues raise
        # a bounded EMA that the homeostasis layer reads as extra curiosity.
        try:
            _question_cue = ("?" in t or "？" in t or any(
                w in t for w in ("什么", "谁", "为什么", "怎么", "哪", "多少", "吗", "如何")))
            self.info_gap = _clip(
                0.85 * float(getattr(self, "info_gap", 0.0))
                + 0.15 * (1.0 if _question_cue else 0.0), 0.0, 1.0)
        except Exception:
            self.info_gap = 0.0
        self.stimuli = [x for x in (getattr(self, "stimuli", []) or [])
                        if _now - float(x.get("ts", 0) or 0) <= float(getattr(self, "stimulus_decay_seconds", 300))]
        if _hits:
            _labels = tuple(sorted(set(_hits)))
            _norm = re.sub(r"\s+", "", t)[:120]
            _item = None
            for _cand in self.stimuli:
                if _event_key:
                    if str(_cand.get("event_key", "")) != _event_key:
                        continue
                    _item = _cand
                    break
                if tuple(_cand.get("labels") or ()) != _labels:
                    continue
                if self._text_similarity(_norm, str(_cand.get("text", ""))) >= 0.55:
                    _item = _cand
                    break
            if _item:
                _gap = max(0.0, _now - float(_item.get("ts", _now)))
                try:
                    _count = float(_item.get("n", 0) or 0) * math.exp(-_gap / max(30.0, float(getattr(self, "stimulus_decay_seconds", 300))))
                except Exception:
                    _count = 0.0
            else:
                _count = 0.0
            _hab = 1.0 / (1.0 + float(getattr(self, "stimulus_habituation", 0.75)) * _count)
            _novelty = float((getattr(self, "appraisal", {}) or {}).get("novelty", 0.0) or 0.0)
            _hab *= max(0.25, 1.0 - 0.6 * _novelty)
            # Batch4 B1: sensitization is the dual of habituation. Only strong
            # negative impulses (v_delta <= -0.12) repeated with >=0.55 text
            # similarity get a gain: 1 + 0.15 * sum(0.5 ** (age_h / 24h)),
            # capped at 1.25. Weak/neutral stimuli keep _sens = 1.0; the final
            # impulse is base * _hab * _sens (habituation still applies).
            _sens = 1.0
            try:
                _prior_sens = [x for x in (getattr(self, "_sensitization_history", []) or [])
                               if isinstance(x, dict)
                               and _now - float(x.get("ts", 0) or 0) <= SENSITIZATION_HISTORY_MAX_AGE]
                if v_delta <= SENSITIZATION_STRONG_NEG_DV:
                    _rep = 0.0
                    for _old in _prior_sens:
                        if self._text_similarity(_norm, str(_old.get("text", ""))) < 0.55:
                            continue
                        _age_h = max(0.0, _now - float(_old.get("ts", 0) or 0)) / 3600.0
                        _rep += 0.5 ** (_age_h / SENSITIZATION_HALF_LIFE_HOURS)
                    _sens = min(SENSITIZATION_MAX, 1.0 + SENSITIZATION_STEP * _rep)
                    _prior_sens.append({"text": _norm, "ts": _now})
                self._sensitization_history = _prior_sens[-SENSITIZATION_HISTORY_MAX:]
            except Exception:
                _sens = 1.0
            if _item:
                _item["n"] = _count + 1
                _item["ts"] = _now
            else:
                self.stimuli.append({"labels": _labels, "text": _norm, "n": 1, "ts": _now, "event_key": _event_key})
            v_delta *= _hab * _sens
            a_delta *= _hab * _sens
            d_delta *= _hab * _sens
            social_delta *= _hab * _sens
            if _item:
                # Repeated equivalent stimulus: boredom rises, novelty need rises.
                self.boredom = _clip(self.boredom + (0.05 + 0.03 * min(3.0, _count)) * (1.0 - self.boredom), 0.0, 1.0)
                self.novelty_need = _clip(self.novelty_need + 0.04 * (1.0 - self.novelty_need), 0.0, 1.0)
            else:
                # New stimulus: boredom falls, novelty need eases toward baseline.
                self.boredom = _clip(self.boredom - 0.08, 0.0, 1.0)
                self.novelty_need = _clip(0.92 * self.novelty_need + 0.08 * 0.5, 0.0, 1.0)
        # B-T07: boundary pressure/refusal readiness from explicit command cues.
        _text_b = str(t or "")
        _commands = sum(1 for w in ("必须", "立刻", "马上", "服从", "不许", "闭嘴", "滚", "废物", "没用", "就该") if w in _text_b)
        _polite = sum(1 for w in ("请", "可以", "愿意", "谢谢", "麻烦") if w in _text_b)
        self.boundary_pressure = _clip(0.86 * self.boundary_pressure + 0.14 * min(1.0, _commands) - 0.04 * min(1.0, _polite), 0.0, 1.0)
        self.refusal_readiness = _clip(
            0.78 * self.refusal_readiness + 0.30 * self.boundary_pressure * min(1.0, _commands)
            + 0.08 * self.stress - 0.05 * min(1.0, _polite), 0.0, 1.0)
        # B-T09: estimate other's valence from the stimulus response, couple with dampening.
        _other_v = _clip(v_delta * 2.5, -1.0, 1.0)
        _gain = _clip(float(getattr(self, "profile", {}).get("contagion_gain", 0.10) or 0.10), 0.0, 0.6)
        _reg = str(getattr(self, "regulation", "none") or "none").lower()
        _damp = 0.55 if _reg in ("reappraise", "reframe") else (0.75 if _reg in ("suppress", "suppression") else 1.0)
        _coupling = _clip(_gain * _damp * abs(_other_v), 0.0, 1.0)
        self.interpersonal = {"other_valence_est": round(_other_v, 4),
                              "coupling": round(_coupling, 4), "dampening": round(_damp, 3)}
        self.v = _clip(self.v + 0.05 * _coupling * _other_v, -1, 1)
        self.a = _clip(self.a + 0.02 * _coupling * abs(_other_v), 0, 1)
        self.v = _clip(0.7 * self.v + 0.3 * v_delta, -1, 1)
        self.a = _clip(0.8 * self.a + 0.2 * (0.4 + a_delta), 0, 1)
        self.d = _clip(0.8 * self.d + 0.2 * (0.55 + d_delta), -1, 1)
        self.social = _clip(0.8 * self.social + 0.2 * (0.55 + social_delta), 0, 1)
        # Affective inertia: recent impulses keep pushing in their direction.
        self.momentum["v"] = _clip(0.75 * float(self.momentum.get("v", 0.0)) + 0.25 * v_delta, -1, 1)
        self.momentum["a"] = _clip(0.75 * float(self.momentum.get("a", 0.0)) + 0.25 * a_delta, -1, 1)
        self.momentum["d"] = _clip(0.75 * float(self.momentum.get("d", 0.0)) + 0.25 * d_delta, -1, 1)
        self.momentum["social"] = _clip(0.75 * float(self.momentum.get("social", 0.0)) + 0.25 * social_delta, -1, 1)
        self.v = _clip(self.v + 0.16 * self.momentum["v"], -1, 1)
        self.a = _clip(self.a + 0.16 * self.momentum["a"], 0, 1)
        self.d = _clip(self.d + 0.16 * self.momentum["d"], -1, 1)
        self.social = _clip(self.social + 0.16 * self.momentum["social"], 0, 1)
        # Intensity raises noise amplitude, but a dimension already near its
        # ceiling receives less effective noise (saturation).
        _int = self._intensity()
        _amp = 0.010 + 0.055 * _int
        self.v = _clip(self.v + self._rng.gauss(0, _amp * (1.0 - 0.75 * abs(self.v))), -1, 1)
        self.a = _clip(self.a + self._rng.gauss(0, _amp * (1.0 - 0.55 * self.a)), 0, 1)
        self.d = _clip(self.d + self._rng.gauss(0, _amp * 0.6 * (1.0 - 0.65 * abs(self.d))), -1, 1)
        self.social = _clip(self.social + self._rng.gauss(0, _amp * 0.5 * (1.0 - 0.65 * self.social)), 0, 1)
        # Reflection buffer: impulse proportional to intensity, then decays;
        # feedback is attenuated when the destination is already high.
        _ref_gain = 0.10 + 0.25 * _int
        self.reflection["v"] = _clip(0.90 * float(self.reflection.get("v", 0.0)) + _ref_gain * v_delta, -1, 1)
        self.reflection["a"] = _clip(0.88 * float(self.reflection.get("a", 0.0)) + _ref_gain * a_delta, -1, 1)
        self.reflection["d"] = _clip(0.92 * float(self.reflection.get("d", 0.0)) + _ref_gain * 0.6 * d_delta, -1, 1)
        self.reflection["social"] = _clip(0.92 * float(self.reflection.get("social", 0.0)) + _ref_gain * 0.6 * social_delta, 0, 1)
        self.v = _clip(self.v + self.reflection["v"] * (1.0 - 0.7 * abs(self.v)), -1, 1)
        self.a = _clip(self.a + self.reflection["a"] * (1.0 - 0.5 * self.a), 0, 1)
        self.d = _clip(self.d + self.reflection["d"] * (1.0 - 0.6 * abs(self.d)), -1, 1)
        self.social = _clip(self.social + self.reflection["social"] * (1.0 - 0.6 * self.social), 0, 1)
        # Opponent process (Solomon & Corbit): the after-reaction builds in the
        # opposite direction and decays slowly, producing an affective rebound.
        _deltas = {"v": v_delta, "a": a_delta, "d": d_delta, "social": social_delta}
        for _k in ("v", "a", "d", "social"):
            _old = float(self.opponent.get(_k, 0.0))
            self.opponent[_k] = _clip(0.86 * _old - 0.22 * _deltas[_k], -1, 1)
        self.v = _clip(self.v + float(getattr(self, "opponent_gain", 0.10)) * self.opponent["v"], -1, 1)
        self.a = _clip(self.a + float(getattr(self, "opponent_gain", 0.10)) * self.opponent["a"], 0, 1)
        self.d = _clip(self.d + float(getattr(self, "opponent_gain", 0.10)) * self.opponent["d"], -1, 1)
        self.social = _clip(self.social + float(getattr(self, "opponent_gain", 0.10)) * self.opponent["social"], 0, 1)
        self._derive()
        self._update_coping(_pre_stress)
        # Stage-2 C8: goal progress writes back to appraisal/affect (real loop),
        # gated by bio_feedback_loops; default OFF is a pure 1.2.98 no-op.
        _progress_before = 0.0
        if getattr(self, "bio_feedback_loops", False):
            try:
                _focus = str(getattr(self, "goal_focus", "") or "")
                for _g in (getattr(self, "goals", []) or []):
                    if isinstance(_g, dict) and str(_g.get("name") or "") == _focus:
                        _progress_before = float(_g.get("progress", 0.0) or 0.0)
                        break
            except Exception:
                _progress_before = 0.0
        self._advance_goals(v_delta, social_delta)
        if getattr(self, "bio_feedback_loops", False):
            try:
                _focus = str(getattr(self, "goal_focus", "") or "")
                _progress_after = _progress_before
                for _g in (getattr(self, "goals", []) or []):
                    if isinstance(_g, dict) and str(_g.get("name") or "") == _focus:
                        _progress_after = float(_g.get("progress", 0.0) or 0.0)
                        break
                _pdelta = _progress_after - _progress_before
                if abs(_pdelta) > 1e-9:
                    _apr = self.appraisal if isinstance(self.appraisal, dict) else {}
                    _apr["coping"] = round(_clip(
                        float(_apr.get("coping", 0.5) or 0.5) + 0.30 * _pdelta,
                        0.0, 1.0), 3)
                    _apr["goal_relevance"] = round(_clip(
                        float(_apr.get("goal_relevance", 0.5) or 0.5)
                        + 0.20 * max(0.0, _pdelta), 0.0, 1.0), 3)
                    self.v = _clip(self.v + 0.20 * _pdelta, -1.0, 1.0)
                    self.stress = _clip(self.stress - 0.10 * max(0.0, _pdelta), 0.0, 1.0)
                    self.appraisal = _apr
            except Exception:
                pass
        self._update_attention(v_delta, a_delta)
        self._update_sec(v_delta, a_delta)
        self._update_meta_emotion()
        if not getattr(self, "autonomy_enabled", False):
            # Legacy noise update (1.2.98). When autonomy is enabled, the only
            # noise update point is noise_tick() driven by the background tick.
            for k in self.noise:
                self.noise[k] = _clip(0.82 * self.noise[k] + self._rng.gauss(0, 0.045), -0.3, 0.3)
            self.noise["valence"] = _clip(0.7 * self.noise["valence"] + 0.3 * v_delta, -0.3, 0.3)
            self.noise["stress"] = _clip(0.8 * self.noise["stress"] + 0.2 * (self.stress - 0.2), -0.3, 0.3)
        self.echo_trace = _clip(0.88 * self.echo_trace + 0.12 * (self.v - self.stress * 0.5), -1, 1)
        self.echo = _clip(0.7 * self.echo + 0.3 * self.echo_trace, -1, 1)
        upper = _clip(0.6 * max(0.0, self.v) + 0.2 * self.trust, 0, 1)
        lower = _clip(0.6 * max(0.0, -self.v) + 0.3 * self.stress, 0, 1)
        self.ripple = {"upper": round(upper, 3), "lower": round(lower, 3),
                       "overlap": round(min(upper, lower), 3), "energy": round((upper + lower) / 2, 3)}
        self.spiking = {"rate": round(0.02 + self.energy * 0.08, 3),
                        "variance": round(0.01 + self.stress * 0.05, 4),
                        "ei": round(0.2 + self.trust * 0.3, 3)}
        try:
            self.update_open_loops(t)
        except Exception:
            pass
        self.ticks += 1
        self.infer_labels(force=True)
        try:
            homeostasis.step(self, relationship=getattr(self, "relationship_context", None))
        except Exception:
            pass
        # Task-15: affect tick + homeostasis drive deviation feed L1 noise.
        try:
            self.integrate_noise(
                "emotion_tick",
                stress=0.004 * float(self.stress),
                energy=0.003 * (0.5 - float(self.energy)),
                social=0.003 * (0.5 - float(self.social)),
                valence=0.004 * float(self.v))
            _homeo = self.homeostasis if isinstance(self.homeostasis, dict) else {}
            _l_int = float(_homeo.get("L_int", 0.0) or 0.0)
            _drives = _homeo.get("drives") if isinstance(_homeo.get("drives"), dict) else {}
            _points = _homeo.get("set_points") if isinstance(_homeo.get("set_points"), dict) else {}
            self.integrate_noise(
                "homeostasis",
                energy=0.004 * _l_int,
                social=0.004 * abs(float(_drives.get("social", 0.5))
                                   - float(_points.get("social", 0.55))),
                attention=0.002 * _l_int)
        except Exception:
            pass
