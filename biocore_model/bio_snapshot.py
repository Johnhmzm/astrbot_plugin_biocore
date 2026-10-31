# -*- coding: utf-8 -*-
"""L0 snapshot mixin: load_state + snapshot extracted verbatim from BioCore."""
from __future__ import annotations

import math

try:
    from .bio_util import _clip
except Exception:  # pragma: no cover
    from bio_util import _clip

try:
    from .bio_const import PLUTCHIK_WHEEL
except Exception:  # pragma: no cover
    from bio_const import PLUTCHIK_WHEEL

try:
    from .. import homeostasis
except Exception:  # pragma: no cover
    import homeostasis


class SnapshotMixin:
    """Copied verbatim from BioCore; originals stay as _orig_* after the rename."""

    def load_state(self, d: dict) -> None:
        if not isinstance(d, dict):
            return
        for key in ("v", "a", "d", "stress", "energy", "trust", "social"):
            if key in d:
                try:
                    lo = -1 if key in ("v", "d") else 0
                    hi = 1.0
                    setattr(self, key, _clip(d[key], lo, hi))
                except Exception:
                    pass
        self._derive()
        try:
            self.ticks = max(0, int(d.get("ticks", self.ticks) or 0))
        except Exception:
            pass
        def _num_map(raw, defaults, lo=-1.0, hi=1.0):
            out = dict(defaults)
            if not isinstance(raw, dict):
                return out
            for key, default in defaults.items():
                if key not in raw:
                    continue
                try:
                    value = float(raw.get(key))
                    if not math.isfinite(value):
                        continue
                    out[key] = max(lo, min(hi, value))
                except Exception:
                    continue
            return out

        self.noise = _num_map(d.get("noise"),
                              {"stress": 0.0, "energy": 0.0, "social": 0.0,
                               "attention": 0.0, "valence": 0.0}, -0.3, 0.3)
        self.reflection = _num_map(d.get("reflection"),
                                   {"v": 0.0, "a": 0.0, "d": 0.0, "social": 0.0}, -1.0, 1.0)
        self.momentum = _num_map(d.get("momentum"),
                                 {"v": 0.0, "a": 0.0, "d": 0.0, "social": 0.0}, -1.0, 1.0)
        self.appraisal = _num_map(d.get("appraisal"),
                                  {"novelty": 0.0, "goal_relevance": 0.0,
                                   "coping": 0.5, "agency": 0.5}, 0.0, 1.0)
        self.opponent = _num_map(d.get("opponent"),
                                 {"v": 0.0, "a": 0.0, "d": 0.0, "social": 0.0}, -1.0, 1.0)
        # Labels are display/decision proxies: whitelist known values only.
        _allowed_labels = {
            "emotion": {"joy", "sadness", "anger", "fear", "loneliness", "neutral"},
            "intent": {"approach", "hold", "withdraw"},
            "expression": {"open", "normal", "short"},
            "need": {"share", "space", "vent", "be_heard", "talk"},
            "energy": {"low", "normal", "high"},
            "stress": {"calm", "tense", "overloaded"},
        }
        safe_labels = {}
        raw_labels = d.get("labels") if isinstance(d.get("labels"), dict) else {}
        for key, allowed in _allowed_labels.items():
            value = str(raw_labels.get(key) or "").strip()
            if value in allowed:
                safe_labels[key] = value
        self.labels = {**{"emotion": "neutral", "intent": "hold",
                          "expression": "normal", "need": "talk",
                          "energy": "normal", "stress": "calm"}, **safe_labels}
        if isinstance(d.get("ripple"), dict):
            self.ripple = _num_map(d["ripple"], self.ripple, 0.0, 1.0)
        if isinstance(d.get("spiking"), dict):
            self.spiking = _num_map(d["spiking"], self.spiking, 0.0, 10.0)
        if isinstance(d.get("stimuli"), list):
            self.stimuli = [x for x in d["stimuli"] if isinstance(x, dict)][-40:]
        if isinstance(d.get("history"), list):
            self.history = [x for x in d["history"] if isinstance(x, dict)][-80:]
        if isinstance(d.get("open_loops"), list):
            self.open_loops = [x for x in d["open_loops"] if isinstance(x, dict)][-20:]
        if isinstance(d.get("coping_history"), list):
            self.coping_history = [float(x) for x in d["coping_history"] if isinstance(x, (int, float))][-40:]
        if isinstance(d.get("event_anchors"), list):
            self.event_anchors = [x for x in d["event_anchors"] if isinstance(x, dict)][-20:]
        if isinstance(d.get("autobiography"), list):
            self.autobiography = [x for x in d["autobiography"] if isinstance(x, dict)][-80:]
        if isinstance(d.get("regulation_stats"), dict):
            self.regulation_stats = {str(k): dict(v) for k, v in d["regulation_stats"].items() if isinstance(v, dict)}
        try:
            self.attention = _clip(d.get("attention", 0.5), 0, 1)
        except Exception:
            self.attention = 0.5
        for _key in ("circadian_alertness", "allostatic_load"):
            if _key in d:
                try:
                    setattr(self, _key, _clip(d[_key], 0, 1))
                except Exception:
                    pass
        try:
            self.homeostasis = homeostasis.normalize_state(d.get("homeostasis"))
        except Exception:
            self.homeostasis = homeostasis.default_state()
        # BUG-01: restore the remaining bounded biological fields.
        for _key in ("novelty_need", "boredom", "boundary_pressure", "refusal_readiness"):
            if _key in d:
                try:
                    setattr(self, _key, _clip(d[_key], 0.0, 1.0))
                except Exception:
                    pass
        raw_inter = d.get("interpersonal") if isinstance(d.get("interpersonal"), dict) else {}
        self.interpersonal = {
            "other_valence_est": round(_clip(raw_inter.get("other_valence_est", 0.0), -1.0, 1.0), 6),
            "coupling": round(_clip(raw_inter.get("coupling", 0.0), 0.0, 1.0), 6),
            "dampening": round(_clip(raw_inter.get("dampening", 1.0), 0.0, 1.0), 6),
        }
        digests = d.get("daily_digests")
        if isinstance(digests, list):
            safe_digests = []
            for item in digests[-30:]:
                if not isinstance(item, dict):
                    continue
                try:
                    safe_digests.append({
                        "date": str(item.get("date") or "")[:10],
                        "event_ids": [str(x)[:80] for x in (item.get("event_ids") or [])[:50] if str(x)],
                        "mean_v": round(_clip(item.get("mean_v", 0.0), -1.0, 1.0), 4),
                        "mean_a": round(_clip(item.get("mean_a", 0.0), 0.0, 1.0), 4),
                        "mean_stress": round(_clip(item.get("mean_stress", 0.0), 0.0, 1.0), 4),
                        "dominant_emotion": str(item.get("dominant_emotion") or "neutral")[:20],
                        "interaction_count": max(0, int(item.get("interaction_count", 0) or 0)),
                    })
                except Exception:
                    continue
            self.daily_digests = safe_digests[-30:]
        self.goal_focus = str(d.get("goal_focus") or "")[:40]
        if isinstance(d.get("meta_emotion"), str):
            self.meta_emotion = d["meta_emotion"]
        if isinstance(d.get("goals"), list):
            self.goals = [dict(g) for g in d["goals"] if isinstance(g, dict)][:8]
        if isinstance(d.get("goal_conflict"), list):
            self.goal_conflict = [str(x) for x in d["goal_conflict"]][:6]
        if isinstance(d.get("goal_scores"), dict):
            self.goal_scores = {str(k): _clip(v, 0, 1) for k, v in d["goal_scores"].items()
                                if isinstance(v, (int, float))}
        for _g in self.goals:
            if not isinstance(_g, dict):
                continue
            _g.setdefault("priority", 0.5)
            _g.setdefault("last_update", 0.0)
        if isinstance(d.get("self_timeline"), dict):
            self.self_timeline = d["self_timeline"]
        if isinstance(d.get("reflection_tree"), dict):
            self.reflection_tree = d["reflection_tree"]
        elif isinstance(d.get("reflection_tree"), list):
            self.reflection_tree = {"roots": [x for x in d["reflection_tree"] if isinstance(x, dict)][-10:], "count": len(d["reflection_tree"])}
        if isinstance(d.get("sec"), dict):
            self.sec = dict(d["sec"])
        self.core_self = str(d.get("core_self") or "")
        self.narrative_self = str(d.get("narrative_self") or "")
        self.last_tick = __import__("time").time()
        for key in ("echo", "echo_trace"):
            if key in d:
                try:
                    setattr(self, key, _clip(d[key]))
                except Exception:
                    pass
        # Task-15: restore autonomy counters/history only; enabled is owned by
        # plugin config. Old states without the key keep {"enabled": False}.
        _raw_auto = d.get("proactive_autonomy")
        if isinstance(_raw_auto, dict):
            _safe_auto = {"enabled": bool(_raw_auto.get("enabled", False))}
            for _k in ("threshold", "max_chars", "impulse", "chaos",
                       "impulse_ema", "ready", "gain", "noise_seed",
                       "last_sent_ts", "sent_count", "sent_day", "updated_ts"):
                if _k in _raw_auto:
                    _safe_auto[_k] = _raw_auto[_k]
            self._proactive_autonomy = _safe_auto
            try:
                self._noise_seed = max(0, int(_raw_auto.get("noise_seed", 0) or 0))
            except Exception:
                self._noise_seed = 0
        # Task-28: restore the autonomy-loop state if present; "enabled" is
        # owned by plugin config and unknown/extra keys are ignored.
        _raw_loop = d.get("autonomy_loop")
        if isinstance(_raw_loop, dict):
            self.autonomy_loop = {}  # legacy loop removed (L4 engine owns ticks)
        # task-43 L1 scalars (bounded restore; unknown/NaN -> defaults).
        self.conflict_ema = _clip(d.get("conflict_ema", 0.0) or 0.0, 0.0, 1.0)
        self.rumination_ema = _clip(d.get("rumination_ema", 0.0) or 0.0, 0.0, 1.0)
        self.anchor_weight = _clip(d.get("anchor_weight", 0.25) or 0.25, 0.0, 0.9)
        try:
            self._neg_repeat = max(0, int(d.get("_neg_repeat", 0) or 0))
        except Exception:
            self._neg_repeat = 0
        self._last_neg_topic = str(d.get("_last_neg_topic") or "")[:80]


    def snapshot(self) -> dict:
        self._decay_to_now()
        out = {"v": round(self.v, 4), "a": round(self.a, 4),
                "d": round(self.d, 4), "social": round(self.social, 4),
                "stress": round(self.stress, 4), "energy": round(self.energy, 4),
                "trust": round(self.trust, 4), "ticks": self.ticks,
                "noise": {k: round(float(v), 3) for k, v in self.noise.items()},
                "echo": round(self.echo, 4), "echo_trace": round(self.echo_trace, 4),
                "ripple": dict(self.ripple), "spiking": dict(self.spiking),
                "reflection": dict(self.reflection),
                "momentum": dict(self.momentum),
                "appraisal": dict(self.appraisal),
                "stimuli": list(self.stimuli)[-8:],
                "history": list(self.history)[-80:],
                "open_loops": [dict(x) for x in (getattr(self, "open_loops", []) or [])[-20:]
                               if isinstance(x, dict)],
                "open_loops_due": sum(1 for _loop in (getattr(self, "open_loops", []) or [])
                                      if isinstance(_loop, dict)
                                      and _loop.get("status") == "open"
                                      and str(_loop.get("due_hint") or "") in ("soon", "tomorrow")),
                "goal_focus": self.goal_focus,
                "coping": round(float((self.appraisal or {}).get("coping", 0.5)), 3),
                "event_anchors": list(self.event_anchors)[-5:],
                "opponent": dict(self.opponent),
                "autobiography": list(self.autobiography)[-8:],
                "regulation_stats": dict(self.regulation_stats),
                "attention": round(float(self.attention), 3),
                "novelty_need": round(float(getattr(self, "novelty_need", 0.5)), 3),
                "boredom": round(float(getattr(self, "boredom", 0.0)), 3),
                "circadian_alertness": round(float(getattr(self, "circadian_alertness", 0.5)), 3),
                "allostatic_load": round(float(getattr(self, "allostatic_load", 0.0)), 3),
                "homeostasis": dict(getattr(self, "homeostasis", {}) or {}),
                "boundary_pressure": round(float(getattr(self, "boundary_pressure", 0.0)), 3),
                "refusal_readiness": round(float(getattr(self, "refusal_readiness", 0.0)), 3),
                "conflict_ema": round(float(getattr(self, "conflict_ema", 0.0) or 0.0), 4),
                "rumination_ema": round(float(getattr(self, "rumination_ema", 0.0) or 0.0), 4),
                "anchor_weight": round(float(getattr(self, "anchor_weight", 0.25) or 0.25), 4),
                "rumination_suppress": bool(getattr(self, "rumination_suppress", False)),
                "user_trust_seeded": bool(getattr(self, "_user_trust_seeded", False)),
                "user_trust_seed_delta": round(
                    float(getattr(self, "_user_trust_seed_delta", 0.0) or 0.0), 4),
                "interpersonal": {k: round(float(v), 4) for k, v in (getattr(self, "interpersonal", {}) or {}).items()},
                "daily_digests": [dict(x) for x in (getattr(self, "daily_digests", []) or [])[-30:]],
                "meta_emotion": self.meta_emotion,
                "goals": [{"key": g.get("key"), "name": g.get("name"), "horizon": g.get("horizon"),
                           "progress": round(float(g.get("progress", 0) or 0), 3),
                           "priority": round(float(g.get("priority", 0.5) or 0.5), 3),
                           "last_update": round(float(g.get("last_update", 0.0) or 0.0), 3)}
                          for g in self.goals],
                "goal_conflict": list(self.goal_conflict),
                "goal_scores": dict(getattr(self, "goal_scores", {}) or {}),
                "self_timeline": dict(self.self_timeline),
                "reflection_tree": self._reflection_tree_view(),
                "spectrum_probs": self._spectrum_probs(),
                "sec": dict(self.sec),
                "core_self": self.core_self,
                "narrative_self": self.narrative_self,
                "plutchik": PLUTCHIK_WHEEL,
                "compound": self.compound,
                "regulation": self.regulation,
                "spectrum": self._spectrum(),
                "spectrum_calibration": dict(getattr(self, "_spectrum_calibration_meta", {}) or {}),
                "labels": dict(getattr(self, "labels", {}) or {}),
                # Task-15: exactly one new top-level field; default OFF keeps
                # the minimal marker and computes no readiness.
                "learning": dict(self._learning),
                "proactive_autonomy": (dict(self._proactive_autonomy)
                                       if getattr(self, "autonomy_enabled", False)
                                       and isinstance(getattr(self, "_proactive_autonomy", None), dict)
                                       else {"enabled": False})}
        # Task-28: persisted ONLY while the loop is enabled. Default OFF is a
        # true no-op: the state file stays byte-identical (key absent entirely).
        if (getattr(self, "autonomy_loop_enabled", False)
                and isinstance(getattr(self, "autonomy_loop", None), dict)):
            out["autonomy_loop"] = {}
        # task-36: opt-in read-only reply-consistency projection; default OFF
        # keeps the state file byte-identical to 1.2.99.
        if (getattr(self, "reply_consistency_enabled", False)
                and isinstance(getattr(self, "reply_consistency", None), dict)):
            out["reply_consistency"] = dict(self.reply_consistency)
        # 1.3.1: opt-in read-only projections (default OFF keeps the state file
        # byte-identical to 1.3.0). thought_note is NEVER persisted.
        if (getattr(self, "think_selfcheck_trace_enabled", False)
                and isinstance(getattr(self, "reverse_check", None), dict)):
            out["reverse_check"] = dict(self.reverse_check)
        if (getattr(self, "token_budget_enabled", False)
                and isinstance(getattr(self, "token_usage", None), dict)):
            out["token_usage"] = dict(self.token_usage)
        if (getattr(self, "path_monitor_enabled", False)
                and isinstance(getattr(self, "path_monitor", None), dict)):
            out["path_monitor"] = dict(self.path_monitor)
        if (getattr(self, "sycophancy_check_enabled", False)
                and isinstance(getattr(self, "sycophancy_check", None), dict)):
            out["sycophancy_check"] = dict(self.sycophancy_check)
        if any(getattr(self, k, False) for k in (
                "learning_bandit_enabled", "learning_relationship_enabled",
                "learning_worthiness_enabled")) and isinstance(
                getattr(self, "learning_state", None), dict):
            out["learning_state"] = dict(self.learning_state)
        if (getattr(self, "relationship_chain_enabled", False)
                or getattr(self, "gottman_enabled", False)) and isinstance(
                getattr(self, "relationship_dynamics", None), dict):
            out["relationship_dynamics"] = dict(self.relationship_dynamics)
        if (getattr(self, "big5_effect_enabled", False)
                and isinstance(getattr(self, "big5_effect", None), dict)):
            out["big5_effect"] = dict(self.big5_effect)
        if (getattr(self, "injection_trace_enabled", False)
                and isinstance(getattr(self, "injection_trace", None), dict)):
            out["injection_trace"] = dict(self.injection_trace)
        return out
