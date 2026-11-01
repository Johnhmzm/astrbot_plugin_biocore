# -*- coding: utf-8 -*-
"""L0 goal mixin: goal signature / evidence / conflict helpers."""
from __future__ import annotations

try:
    from .. import memory_meta
except Exception:  # pragma: no cover
    try:
        import memory_meta  # type: ignore
    except Exception:
        class _Missing:
            def __getattr__(self, name):
                raise AttributeError(name)
        memory_meta = _Missing()  # type: ignore


class GoalMixin:
    """Goal helpers copied verbatim from BioCore."""
    def _goal_signature(self, g: dict) -> str:
        try:
            return "、".join([str(g.get("name") or "")] + [str(x) for x in (g.get("keywords") or ())[:6]])
        except Exception:
            return str(g.get("name") or "")


    def _goal_relevance_from_dims(self, dims) -> float:
        """item-6: numeric goal relevance from probe dims (goal/involve/hit)."""
        d = dims if isinstance(dims, dict) else {}

        def _n(key, default=0.0):
            try:
                return float(d.get(key, default) or default)
            except Exception:
                return default

        return round(max(0.0, min(1.0,
                                  0.45 * _n("involve") + 0.35 * abs(_n("goal"))
                                  + 0.20 * _n("hit"))), 3)

    def _goal_evidence(self, g: dict, local_text: str, context_text: str,
                       dims=None) -> float:
        """item-6: evidence from probe dims; text similarity only, no keyword scan."""
        try:
            if dims:
                base = self._goal_relevance_from_dims(dims)
                try:
                    pri = max(0.0, min(1.0, float(g.get("priority", 0.5) or 0.5)))
                except Exception:
                    pri = 0.5
                return round(max(0.0, min(1.0, base * (0.6 + 0.4 * pri))), 3)
            name = str(g.get("name") or "")
            if not name:
                return 0.0
            text = str(local_text or "") or str(context_text or "")
            return round(max(0.0, min(1.0,
                                       self._text_similarity(text, name) * 0.75)), 3)
        except Exception:
            return 0.0

    def _resolve_goal_conflict(self, scores=None) -> None:
        """Pick a focus among active goals: high priority and low progress win."""
        scores = scores if isinstance(scores, dict) else dict(getattr(self, "goal_scores", {}) or {})
        cand = []
        for g in getattr(self, "goals", []) or []:
            if not isinstance(g, dict):
                continue
            key = str(g.get("key") or "")
            rel = float(scores.get(key, 0.0) or 0.0)
            if rel < 0.25:
                continue
            try:
                pri = float(g.get("priority", 0.5) or 0.5)
                prog = max(0.0, min(1.0, float(g.get("progress", 0.0) or 0.0)))
            except Exception:
                pri, prog = 0.5, 0.0
            cand.append((pri * (1.0 - prog), rel, g))
        if not cand:
            self.goal_focus = ""
            self.goal_conflict = []
            return
        cand.sort(key=lambda x: (x[0], x[1]), reverse=True)
        self.goal_focus = str(cand[0][2].get("name") or "")
        self.goal_conflict = [str(x[2].get("name") or "") for x in cand[1:]][:4]


    def bind_goal_context(self, memory_text: str = "", self_model=None,
                          recent=None, text: str = "", dims=None) -> None:
        """Fuse retrieved memory / self narrative / recent turns into goal relevance."""
        try:
            ctx_parts = [str(memory_text or "")]
            if isinstance(self_model, dict):
                ctx_parts.append(str(self_model.get("narrative") or ""))
                ctx_parts.append("、".join(str(x) for x in (self_model.get("consistency") or [])[:5]))
            if isinstance(recent, (list, tuple)):
                ctx_parts.extend(str(x)[:200] for x in recent[:8])
            ctx = "\n".join([p for p in ctx_parts if p])
            if not ctx.strip():
                return
            base = dict(getattr(self, "goal_scores", {}) or {})
            for g in getattr(self, "goals", []) or []:
                if not isinstance(g, dict):
                    continue
                key = str(g.get("key") or "")
                rel = self._goal_evidence(g, str(text or ""), ctx, dims=dims)
                base[key] = round(max(float(base.get(key, 0.0) or 0.0), rel), 3)
            self.goal_scores = base
            if base:
                self.appraisal["goal_relevance"] = round(min(1.0, max(base.values())), 3)
            self._resolve_goal_conflict(base)
        except Exception:
            pass

    def _update_goals(self, text: str, context: str = "", dims=None) -> None:
        """item-6: goal scores from probe dims (goal/involve/hit); no word tables."""
        t = str(text or "")
        ctx = str(context or "")
        scores = {}
        for item in getattr(self, "goals", []) or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "")
            scores[key] = round(self._goal_evidence(item, t, ctx, dims=dims), 3)
        self.goal_scores = scores
        # Deterministic priority learning: repeated evidence raises a goal,
        # neglect decays it slowly (bounded EMA; no LLM involved).
        try:
            for item in getattr(self, "goals", []) or []:
                if not isinstance(item, dict):
                    continue
                _key = str(item.get("key") or "")
                _rel = float(scores.get(_key, 0.0) or 0.0)
                memory_meta.update_goal_priority(
                    item, hit=(_rel > 0.05), relevance=_rel)
        except Exception:
            pass
        best = max(scores.values()) if scores else 0.0
        self.appraisal["goal_relevance"] = round(best, 3)
        self._resolve_goal_conflict(scores)
        d = dims if isinstance(dims, dict) else {}

        def _n(key, default=0.0):
            try:
                return float(d.get(key, default) or default)
            except Exception:
                return default

        norm = 0.5 + 0.25 * _n("goal") - 0.25 * _n("blame") - 0.15 * _n("hit")
        self.appraisal["norm_compatibility"] = round(max(0.0, min(1.0, norm)), 3)
        self.appraisal["expectedness"] = round(
            1.0 - float(self.appraisal.get("novelty", 0.0) or 0.0), 3)
        self.appraisal["urgency"] = round(float(getattr(self, "a", 0.5)), 3)

    def _advance_goals(self, v_delta: float = 0.0, social_delta: float = 0.0) -> None:
        """Goal progress follows the interaction outcome, not a fixed step."""
        focus_key = ""
        focus_name = str(getattr(self, "goal_focus", "") or "")
        if not focus_name:
            return
        for g in getattr(self, "goals", []) or []:
            if str(g.get("name") or "") == focus_name:
                focus_key = str(g.get("key") or "")
                break
        if not focus_key:
            return
        try:
            rel = float((getattr(self, "goal_scores", {}) or {}).get(focus_key, 0.0) or 0.0)
            if rel <= 0.0:
                return
            gain = (0.004 * rel
                    + 0.060 * max(0.0, float(v_delta))
                    + 0.040 * max(0.0, float(social_delta))
                    - 0.060 * max(0.0, -float(v_delta)))
            # Stage-2 C9: appraisal/emotion now feeds goal progress (real loop),
            # gated by bio_feedback_loops; default OFF keeps 1.2.98 unchanged.
            if getattr(self, "bio_feedback_loops", False):
                try:
                    _coping = float((getattr(self, "appraisal", {}) or {}).get("coping", 0.5) or 0.5)
                    _goal_rel = float((getattr(self, "appraisal", {}) or {}).get("goal_relevance", 0.5) or 0.5)
                    gain += 0.02 * ((_coping - 0.5) + (_goal_rel - 0.5))
                except Exception:
                    pass
            gain = max(-0.06, min(0.08, gain))
            for g in self.goals:
                if str(g.get("key") or "") != focus_key:
                    continue
                g["progress"] = round(max(0.0, min(1.0, float(g.get("progress", 0.0) or 0.0) + gain)), 4)
                g["last_update"] = round(__import__("time").time(), 3)
                try:
                    memory_meta.update_goal_priority(
                        g, hit=(gain >= 0.0), relevance=min(1.0, rel + max(0.0, gain)))
                except Exception:
                    pass
                break
        except Exception:
            pass


    def update_open_loops(self, text: str, now=None) -> None:
        """Deterministic prospective-memory (open loops) update from one message."""
        try:
            stamp = float(now if now is not None else __import__("time").time())
            loops = [x for x in (getattr(self, "open_loops", []) or []) if isinstance(x, dict)]
            memory_meta.resolve_open_loops(loops, text, stamp)
            for new_loop in memory_meta.detect_open_loops(text, stamp):
                merged = False
                for existing in loops:
                    if str(existing.get("status") or "open") != "open":
                        continue
                    if memory_meta.text_similarity(
                            existing.get("text", ""), new_loop.get("text", "")) >= memory_meta.OPEN_LOOP_MERGE_SIMILARITY:
                        existing["last_mentioned_ts"] = stamp
                        existing["mentioned"] = int(existing.get("mentioned", 1) or 1) + 1
                        merged = True
                        break
                if not merged:
                    loops.append(new_loop)
            self.open_loops = loops[-int(memory_meta.OPEN_LOOP_MAX):]
        except Exception:
            pass

