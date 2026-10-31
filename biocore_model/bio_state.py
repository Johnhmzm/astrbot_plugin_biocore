# -*- coding: utf-8 -*-
"""L0 state mixin: relationship context, appraisal intent, memory trace, refusal posture."""
from __future__ import annotations

try:
    from .bio_util import _clip
except Exception:  # pragma: no cover
    from bio_util import _clip

try:
    from .. import memory_meta, relationship_meta
except Exception:  # pragma: no cover
    try:
        import memory_meta  # type: ignore
        import relationship_meta  # type: ignore
    except Exception:
        memory_meta = None  # type: ignore
        relationship_meta = None  # type: ignore


class StateMixin:
    """Copied verbatim from BioCore; original kept as _orig_*."""
    def set_relationship_context(self, relationship=None) -> None:
        """Attach the last per-user relationship record for the slow C6 loop.

        The plugin refreshes this hook after persisting the user doc each turn;
        only conflict/closeness are consumed by homeostasis._drives.
        """
        self.relationship_context = relationship if isinstance(relationship, dict) else None


    def _update_coping(self, pre_stress: float) -> None:
        delta = float(getattr(self, "stress", 0.2)) - float(pre_stress)
        success = 0.5 - 0.8 * delta + 0.15 * (float(getattr(self, "social", 0.5)) - 0.5)
        success = max(0.0, min(1.0, success))
        self.coping_history = (list(getattr(self, "coping_history", [])) + [success])[-40:]
        if self.coping_history:
            self.appraisal["coping"] = round(sum(self.coping_history) / len(self.coping_history), 3)


    def remember_event(self, key: str, title: str, meaning: str = "", reflection: str = "",
                       embedding=None) -> None:
        key = str(key or "").strip()
        title = str(title or "").strip()
        if not key or not title:
            return
        self.event_anchors = [x for x in getattr(self, "event_anchors", [])
                              if x.get("key") != key][-19:]
        _anchor = {"key": key, "title": title, "ts": __import__("time").time()}
        if embedding:
            try:
                _anchor["embedding"] = [float(x) for x in embedding]
            except Exception:
                pass
        self.event_anchors.append(_anchor)
        self.autobiography = (list(getattr(self, "autobiography", [])) + [{
            "ts": __import__("time").time(), "key": key, "title": title,
            "meaning": str(meaning or "")[:400], "reflection": str(reflection or "")[:400],
        }])[-80:]
        try:
            self.self_timeline["past"] = [x.get("title") for x in self.autobiography[-8:]]
            self.self_timeline["present"] = str(reflection or meaning or title)[:300]
            self.self_timeline["future"] = [g.get("name") for g in (self.goals or []) if g.get("name")][:5]
            self.core_self = str(getattr(self, "core_self", "") or title)[:300]
            self.narrative_self = str(reflection or meaning or title)[:500]
        except Exception:
            pass


    def _update_meta_emotion(self) -> None:
        e = str((self.labels or {}).get("emotion") or "neutral")
        t = float(self.trust)
        soc = float(self.social)
        if e == "sadness" and t < 0.55:
            self.meta_emotion = "对难过的羞耻"
        elif e == "anger" and soc < 0.50:
            self.meta_emotion = "对生气的羞耻"
        elif e == "fear" and float(self.appraisal.get("coping", 0.5)) < 0.45:
            self.meta_emotion = "对害怕的焦虑"
        elif e == "loneliness" and t >= 0.55:
            self.meta_emotion = "对孤独的承认"
        else:
            self.meta_emotion = ""


    def intent(self) -> dict:
        labels = dict(getattr(self, "labels", {}) or {})
        return {
            "emotion": labels.get("emotion", "neutral"),
            "energy": labels.get("energy", "normal"),
            "stress": labels.get("stress", "calm"),
            "trust": round(self.trust, 2),
            "intent": labels.get("intent", "hold"),
            "expression": labels.get("expression", "normal"),
            "need": labels.get("need", "talk"),
            "dominance": round(self.d, 2),
            "social": round(self.social, 2),
            "compound": self.compound,
            "spectrum": self._spectrum(),
            "regulation": self.regulation,
        }


    def apply_memory_trace(self, v_delta: float = 0.0, stress_delta: float = 0.0) -> dict:
        """Single BioCore writer for L3 memory-trace nudges (bounded)."""
        try:
            dv = max(-0.05, min(0.05, float(v_delta or 0.0)))
        except Exception:
            dv = 0.0
        try:
            ds = max(-0.05, min(0.05, float(stress_delta or 0.0)))
        except Exception:
            ds = 0.0
        self.v = _clip(float(getattr(self, "v", 0.0)) + dv, -1.0, 1.0)
        self.stress = _clip(float(getattr(self, "stress", 0.0)) + ds, 0.0, 1.0)
        return {"v_delta": round(dv, 4), "stress_delta": round(ds, 4)}


    def refusal_posture(self, relationship=None) -> dict:
        """task-35 L1: deterministic refusal posture -> brevity posture.

        Reads boundary_pressure/trust/conflict only; returns a label used by L2
        rendering and the proactive gate. Never decides by itself whether a reply
        is sent here.
        """
        rel = relationship if isinstance(relationship, dict) else {}
        state = rel.get("state") if isinstance(rel.get("state"), dict) else {}
        try:
            protocol = relationship_meta.refusal_protocol({
                "boundary_pressure": float(getattr(self, "boundary_pressure", 0.0) or 0.0),
                "trust": float(state.get("trust", 0.5) or 0.5),
                "conflict": float(state.get("conflict", 0.0) or 0.0),
            })
        except Exception:
            protocol = {"mode": "comply"}
        mode = str(protocol.get("mode") or "comply")
        brevity = "short" if mode == "decline" else (
            "medium" if mode == "negotiate" else "normal")
        return {"mode": mode, "brevity": brevity}


    def update_conflict_ema(self, text, *, novelty=0.0, correction=False,
                            contradiction=False) -> dict:
        """Botvinick 2001 proxy: contradiction/correction/instruction conflict EMA."""
        value = str(text or "")
        cues = ("不对", "不是", "你错了", "矛盾", "但是", "可是", "然而",
                "说错", "纠正", "改口", "冲突", "说反")
        hits = sum(1 for cue in cues if cue in value)
        corr = 1.0 if (correction or any(w in value for w in ("不对", "你错了", "纠正", "改口"))) else 0.0
        contrad = 1.0 if (contradiction or any(w in value for w in ("矛盾", "不是这样", "说错了"))) else 0.0
        nov = _clip(novelty, 0.0, 1.0)
        delta = _clip(0.45 * min(1.0, hits / 2.0) + 0.30 * corr
                      + 0.15 * contrad + 0.10 * nov, 0.0, 1.0)
        self.conflict_ema = _clip(0.80 * float(getattr(self, "conflict_ema", 0.0)) + 0.20 * delta,
                                  0.0, 1.0)
        high = self.conflict_ema >= 0.60
        if high and getattr(self, "conflict_gate_enabled", False):
            state = getattr(self, "autonomy_loop", None)
            if isinstance(state, dict):
                try:
                    debt = float(state.get("effort_debt", 0.0) or 0.0)
                    state["effort_debt"] = round(_clip(debt + 0.02, 0.0, 0.60), 4)
                except Exception:
                    pass
        return {"conflict_ema": round(self.conflict_ema, 4),
                "delta": round(delta, 4), "high": bool(high)}


    def update_rumination_ema(self, text, *, emotion="neutral", intensity=0.0,
                              novelty=0.0) -> dict:
        """Nolen-Hoeksema 1991 proxy: repeated negative topic EMA (bounded)."""
        value = str(text or "")
        negative = (str(emotion or "") in ("sadness", "anger", "fear", "loneliness")
                    or any(w in value for w in ("难受", "难过", "烦", "焦虑", "委屈",
                                                "不想", "讨厌", "崩溃", "累")))
        topic = value[:40] if negative else ""
        repeat = False
        if negative and topic and self._last_neg_topic:
            repeat = memory_meta.text_similarity(topic, self._last_neg_topic) >= 0.5
        if negative:
            self._neg_repeat = (int(getattr(self, "_neg_repeat", 0) or 0) + 1
                                if repeat else 1)
            self._last_neg_topic = topic
            inc = 0.20 if repeat else 0.10
            add = inc * (0.5 + 0.5 * _clip(intensity, 0.0, 1.0))
            self.rumination_ema = _clip(float(getattr(self, "rumination_ema", 0.0)) + add,
                                        0.0, 1.0)
            # §6/LIT: 3 consecutive same-topic negative rounds -> suppression mark.
            if int(getattr(self, "_neg_repeat", 0) or 0) >= 3:
                self.rumination_suppress = True
        else:
            decay = 0.70 if _clip(novelty, 0.0, 1.0) >= 0.50 else 0.85
            self.rumination_ema = _clip(
                float(getattr(self, "rumination_ema", 0.0)) * decay, 0.0, 1.0)
            self._neg_repeat = 0
            self.rumination_suppress = False
        if (getattr(self, "rumination_effect_enabled", False)
                and self.rumination_ema > 0.0):
            shift = min(0.12, 0.12 * self.rumination_ema)
            self.v = _clip(self.v - shift, -1.0, 1.0)
        return {"rumination_ema": round(self.rumination_ema, 4),
                "repeat": bool(repeat), "repeat_count": int(self._neg_repeat)}


    def _decay_to_now(self) -> None:
        now = __import__("time").time()
        try:
            dt_min = max(0.0, (now - float(getattr(self, "last_tick", now))) / 60.0)
        except Exception:
            dt_min = 0.0
        self.last_tick = now
        if dt_min < 0.5:
            return
        def factor(halflife):
            try:
                hl = max(1.0, float(halflife))
            except Exception:
                hl = 120.0
            return 0.5 ** (dt_min / hl)
        _emo = str((getattr(self, "labels", {}) or {}).get("emotion") or "neutral")
        _ef = float((getattr(self, "emotion_decay_factors", {}) or {}).get(_emo, 1.0))
        # Batch4 B4: contextual recovery speed shortens the half-life only for
        # dimensions that are recovering toward baseline.
        _rec = self._recovery_speed()
        _v_rec = _rec if self.v < 0 else 1.0
        _a_rec = _rec if self.a > 0.40 else 1.0
        _soc_rec = _rec if self.social < 0.55 else 1.0
        self.v = _clip(self.v * factor(self.valence_decay_minutes * _ef / _v_rec), -1, 1)
        self.a = _clip(0.40 + (self.a - 0.40) * factor(
            self.arousal_decay_minutes * max(0.5, _ef) / _a_rec), 0, 1)
        self.d = _clip(0.55 + (self.d - 0.55) * factor(self.valence_decay_minutes * _ef), -1, 1)
        self.social = _clip(0.55 + (self.social - 0.55) * factor(
            self.social_decay_minutes * _ef / _soc_rec), 0, 1)
        self._derive()
        try:
            self._apply_circadian_effects()
            self._update_allostatic_load()
        except Exception:
            pass
        try:
            self._metabolic_energy_offset = _clip(
                float(getattr(self, "_metabolic_energy_offset", 0.0)) * 0.98, 0.0, 0.20)
        except Exception:
            self._metabolic_energy_offset = 0.0

