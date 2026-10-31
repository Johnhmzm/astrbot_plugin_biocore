# -*- coding: utf-8 -*-
"""L0 physiology mixin #2: circadian/rest, allostatic load, reflection tree.

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
        REFLECTION_TREE_TTL_DAYS,
        circadian_alertness,
    )
except Exception:  # pragma: no cover
    from bio_const import (
        REFLECTION_TREE_TTL_DAYS,
        circadian_alertness,
    )


class Physiology2Mixin:
    """Copied verbatim from BioCore; originals stay as _orig_*."""

    def _apply_circadian_effects(self, alert=None, now=None) -> float:
        """Small attention/energy modulation from local-hour alertness."""
        try:
            if alert is None:
                current = time.localtime(time.time() if now is None else now)
                alert = circadian_alertness(current.tm_hour + current.tm_min / 60.0)
            alert = max(0.0, min(1.0, float(alert)))
            self.circadian_alertness = round(alert, 3)
            delta = 0.01 * (alert - 0.5)
            self.energy = _clip(self.energy + delta, 0.0, 1.0)
            self.attention = _clip(self.attention + delta * 0.5, 0.0, 1.0)
            return alert
        except Exception:
            return 0.5


    def _update_allostatic_load(self) -> float:
        """Slow allostatic accumulation/recovery; bounded, tiny stress offset."""
        try:
            stress = _clip(self.stress, 0.0, 1.0)
            if stress > 0.55:
                self.allostatic_load = _clip(
                    self.allostatic_load + 0.01 * (stress - 0.55) * (1.0 - self.allostatic_load), 0.0, 1.0)
            else:
                self.allostatic_load = _clip(
                    self.allostatic_load - 0.004 * (0.55 - stress), 0.0, 1.0)
            if self.allostatic_load > 0:
                self.stress = _clip(self.stress + 0.005 * self.allostatic_load, 0.0, 1.0)
            return float(self.allostatic_load)
        except Exception:
            return 0.0


    def _reflection_tree_view(self) -> dict:
        """G15: read-only reflection tree with old nodes softly forgotten.

        Nodes carry their creation ts; nodes older than REFLECTION_TREE_TTL_DAYS
        are hidden from snapshots/dashboard without deleting stored history.
        """
        try:
            tree = self.reflection_tree if isinstance(self.reflection_tree, dict) else {}
            cutoff = time.time() - REFLECTION_TREE_TTL_DAYS * 86400.0

            def _alive(node):
                try:
                    ts = float(node.get("ts", 0) or 0)
                except Exception:
                    ts = 0.0
                return ts <= 0 or ts >= cutoff

            roots = []
            for node in (tree.get("roots") or [])[:10]:
                if not isinstance(node, dict) or not _alive(node):
                    continue
                item = dict(node)
                item["children"] = [dict(child) for child in
                                    (node.get("children") or [])[-10:]
                                    if isinstance(child, dict) and _alive(child)]
                roots.append(item)
            stored_roots = [node for node in (tree.get("roots") or [])
                            if isinstance(node, dict)]
            stored_total = sum(
                1 + len([c for c in (node.get("children") or []) if isinstance(c, dict)])
                for node in stored_roots)
            visible_total = sum(1 + len(item.get("children") or []) for item in roots)
            return {"roots": roots[-10:], "count": int(tree.get("count", 0) or 0),
                    "hidden_count": max(0, stored_total - visible_total)}
        except Exception:
            return {"roots": [], "count": 0, "hidden_count": 0}


    def _update_sec(self, v_delta: float, a_delta: float) -> None:
        self.sec = {
            "relevance": round(max(0.0, min(1.0, float(self.appraisal.get("goal_relevance", 0.0) or 0.0) * 0.7 + float(self.appraisal.get("novelty", 0.0) or 0.0) * 0.3)), 3),
            "implication": round(max(0.0, min(1.0, abs(float(v_delta)) * 2.0 + float(self.stress))), 3),
            "coping_potential": round(max(0.0, min(1.0, float(self.appraisal.get("coping", 0.5) or 0.5))), 3),
            "normative": round(max(0.0, min(1.0, float(self.appraisal.get("norm_compatibility", 0.5) or 0.5))), 3),
        }


    def _update_attention(self, v_delta: float, a_delta: float) -> None:
        novelty = float(self.appraisal.get("novelty", 0.0) or 0.0)
        goal = float(self.appraisal.get("goal_relevance", 0.0) or 0.0)
        salience = abs(float(v_delta)) * 1.8 + abs(float(a_delta)) * 1.2 + novelty * 0.4 + goal * 0.5
        self.attention = _clip(0.82 * float(self.attention) + 0.18 * _clip(salience, 0, 1), 0, 1)
