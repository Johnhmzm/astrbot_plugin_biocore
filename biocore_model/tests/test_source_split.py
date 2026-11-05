# -*- coding: utf-8 -*-
"""task-243 step 3.3: each source keeps its own line (no fusion into one number).

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_source_split.py"
"""
import unittest

from biocore_memory.recall import feedback as fb
from biocore_model import affective_labor as labor
from biocore_model import appraisal as ap
from biocore_model import emotion_geometry as geo
from biocore_model import envy as ev
from biocore_model import feedback_memory as fm
from biocore_model import needs_events as ne
from biocore_model import regulation_strategies as reg
from biocore_model import self_esteem as se


NOW = 1700000000.0


class RecallFeedbackSplitTest(unittest.TestCase):
    """6/7: each recalled memory is a proposal with its own id."""

    def rows(self):
        return [{"id": "strong", "text": "我的猫叫团子",
                 "affect": {"v": 0.8, "a": 0.9}, "importance": 0.9},
                {"id": "weak", "text": "今天加班", "affect": {"v": -0.2, "a": 0.3},
                 "importance": 0.1}]

    def test_every_memory_keeps_its_own_proposal(self):
        out = fb.plan(self.rows(), {"v": 0.0, "a": 0.5}, now=NOW)
        self.assertEqual([row["id"] for row in out["proposals"]],
                         ["strong", "weak"])
        self.assertEqual([row["v"] for row in out["proposals"]], [0.8, -0.2])
        self.assertEqual(out["selected"], "strong")   # most trusted, not a mean
        self.assertAlmostEqual(out["target"][0], 0.8, places=4)

    def test_turning_split_off_restores_the_average(self):
        out = fb.plan(self.rows(), {"v": 0.0, "a": 0.5}, now=NOW, split=False)
        self.assertEqual(out["selected"], "")
        low = min(row["v"] for row in out["proposals"])
        high = max(row["v"] for row in out["proposals"])
        self.assertGreater(out["target"][0], low)
        self.assertLess(out["target"][0], high)

    def test_touch_batch_records_each_memory_and_respects_limits(self):
        rows = [{"id": "a", "strength": 0.5}, {"id": "b", "strength": 0.5}]
        first = fm.touch_batch(rows, ["a", "b"], NOW, limit=1)
        self.assertEqual([row["id"] for row in first["rows"]], ["a"])
        self.assertEqual(first["skipped"][0]["reason"], "turn_cap")
        again = fm.touch_batch(first["entries"], ["a"], NOW + 10)
        self.assertEqual(again["rows"], [])
        self.assertEqual(again["skipped"][0]["reason"], "cooldown")
        later = fm.touch_batch(first["entries"], ["a"],
                               NOW + fm.COOLDOWN_SECONDS + 1)
        self.assertEqual([row["id"] for row in later["rows"]], ["a"])


class AppraisalDetailTest(unittest.TestCase):
    """8: the 7 dims stay; v/a are visible derived readouts."""

    def test_components_show_where_v_came_from(self):
        dims = {"goal": 0.5, "blame": 0.4, "hit": 0.3, "control": 0.7}
        detail = ap.appraise_detail(dims, confidence=1.0, v2=False)
        self.assertEqual(detail["mapping"], "v1")
        self.assertEqual(detail["deltas"],
                         ap.appraise(dims, confidence=1.0, v2=False))
        rows = detail["components"]["v"]["rows"]
        self.assertIn("goal", rows)
        self.assertIn("blame", rows)     # v1 folds them in: that is the point
        self.assertIn("hit", rows)
        self.assertAlmostEqual(sum(rows.values()),
                               detail["components"]["v"]["total"], places=6)
        self.assertTrue(detail["derived"]["v"])
        # v2 keeps only goal in v; blame moves to trust, hit to stress
        v2 = ap.appraise_detail(dims, confidence=1.0, v2=True)
        self.assertEqual(sorted(v2["components"]["v"]["rows"]), ["goal"])
        self.assertIn("blame", v2["components"]["trust"]["rows"])


class EmotionScoresTest(unittest.TestCase):
    """9: raw scores stay; softmax is only a label."""

    def test_scores_and_probs_coexist(self):
        out = geo.classify({"v": -0.5, "a": 0.6, "social": 0.4, "stress": 0.7})
        self.assertEqual(sorted(out["scores"]), sorted(geo.LABELS))
        self.assertEqual(sorted(out["probs"]), sorted(geo.LABELS))
        self.assertAlmostEqual(sum(out["probs"].values()), 1.0, places=2)
        self.assertNotAlmostEqual(sum(out["scores"].values()), 1.0, places=4)
        self.assertTrue(out["label"])


class AffectiveLaborTest(unittest.TestCase):
    """11: exhaustion / depersonalization / accomplishment stay separate."""

    def test_components_are_three(self):
        state = labor.initial(NOW)
        state = labor.update(state, {"v": 0.2, "a": 0.5},
                             {"v": -0.6, "a": 0.7}, now=NOW + 60)
        components = state["components"]
        self.assertEqual(sorted(components), ["depersonalization",
                                              "emotional_exhaustion",
                                              "personal_accomplishment"])
        view = labor.view(state)
        self.assertEqual(view["components"], components)
        self.assertGreater(components["depersonalization"], 0.0)


class EnvySignalsTest(unittest.TestCase):
    """12: comparison / deprivation / self-threat are not one intensity."""

    def test_each_signal_stays_visible(self):
        out = ev.assess({"third_party": 0.8, "fairness": 0.2,
                         "self_evaluation": 0.3, "relation_stage": "close"})
        components = out["components"]
        self.assertEqual(sorted(components),
                         ["closeness", "comparison", "presence",
                          "relative_deprivation", "self_threat"])
        self.assertAlmostEqual(components["relative_deprivation"], 0.8, places=4)
        self.assertAlmostEqual(components["self_threat"], 0.7, places=4)
        self.assertGreater(out["intensity"], 0.0)   # kept as a display readout


class RegulationPartsTest(unittest.TestCase):
    """14: effect and cost are reported separately, never as a ratio."""

    def test_score_parts_keep_effect_and_cost(self):
        row = reg.profile("cognitive_reappraisal", {"valence": -0.3,
                                                    "arousal": 0.6,
                                                    "stress": 0.5,
                                                    "energy": 0.6})
        self.assertEqual(sorted(row["score_parts"]), ["cost", "effect", "fit"])
        self.assertAlmostEqual(row["score_parts"]["effect"], row["effect"])
        self.assertAlmostEqual(row["score_parts"]["cost"], row["cost"])
        self.assertTrue(row["score_is_display"])


class SelfEsteemEventsTest(unittest.TestCase):
    """16: one row per event; the value is only the aggregate."""

    def test_events_are_recorded_one_by_one(self):
        state = se.initial(NOW)
        state = se.update(state, "praised", NOW + 10)
        state = se.update(state, "ignored", NOW + 20)
        self.assertEqual([row["event"] for row in state["events"]],
                         ["praised", "ignored"])
        self.assertAlmostEqual(state["events"][1]["delta"], -0.05, places=4)
        view = se.view(state)
        self.assertEqual(len(view["events"]), 2)
        self.assertTrue(view["value_is_aggregate"])


class NeedsNoResidualTest(unittest.TestCase):
    """13: confirm the second step left no cross-need synthesis behind."""

    def test_control_deficit_never_reaches_self_assert(self):
        needs = {"belonging": 0.6, "self_esteem": 0.6, "control": 0.1,
                 "meaningful_existence": 0.6}
        self.assertAlmostEqual(ne.behavior_bias(needs)["self_assert"], 0.0,
                               places=4)
        rows = ne.need_biases(needs)
        self.assertAlmostEqual(rows["control"]["deficit"], 0.5, places=4)
        self.assertAlmostEqual(rows["self_esteem"]["deficit"], 0.0, places=4)


if __name__ == "__main__":
    unittest.main()
