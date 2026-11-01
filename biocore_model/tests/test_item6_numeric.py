# -*- coding: utf-8 -*-
"""item-6: goal/identity scoring is numeric (probe dims), no word tables."""
import unittest
from pathlib import Path

from biocore_model.bio_goal import GoalMixin
from biocore_model.bio_identity import IdentityMixin

PKG = Path(__file__).resolve().parents[1]


class GoalDummy(GoalMixin):
    def __init__(self):
        self.goals = [
            {"key": "a", "name": "Goal A", "priority": 0.9, "progress": 0.0},
            {"key": "b", "name": "Goal B", "priority": 0.3, "progress": 0.0},
        ]
        self.appraisal = {}
        self.goal_scores = {}
        self.goal_focus = ""
        self.goal_conflict = []
        self.a = 0.5

    @staticmethod
    def _text_similarity(left, right):
        return 0.0


class IdentityDummy(IdentityMixin):
    def __init__(self):
        self.trust = 0.5
        self.v = 0.0
        self.stress = 0.1
        self.echo_trace = 0.0
        self.identity_threat_stress_enabled = False


class SourceAuditTest(unittest.TestCase):
    def test_bio_goal_has_no_positive_negative_word_table(self):
        source = (PKG / "bio_goal.py").read_text(encoding="utf-8")
        self.assertNotIn("_pos = sum", source)
        self.assertNotIn("_neg = sum", source)
        for word in ("谢谢", "废物", "闭嘴", "讨厌"):
            self.assertNotIn(word, source, word)

    def test_bio_identity_has_no_word_tables(self):
        source = (PKG / "bio_identity.py").read_text(encoding="utf-8")
        for word in ("你不是她", "不配", "cold_words", "warm_words",
                     "废物", "傻子"):
            self.assertNotIn(word, source, word)


class IdentityNumericTest(unittest.TestCase):
    def test_text_alone_is_not_a_threat(self):
        dummy = IdentityDummy()
        self.assertFalse(dummy.detect_identity_threat(
            "你不是她，你就是个工具废物"))

    def test_dims_blame_and_involve_are_a_threat(self):
        dummy = IdentityDummy()
        self.assertTrue(dummy.detect_identity_threat(
            dims={"blame": 0.8, "involve": 0.6}))

    def test_dims_hit_is_a_threat(self):
        self.assertTrue(IdentityDummy().detect_identity_threat(
            dims={"hit": 0.8}))

    def test_apply_is_default_off(self):
        dummy = IdentityDummy()
        self.assertFalse(dummy.apply_identity_threat(dims={"hit": 0.9}))
        self.assertAlmostEqual(dummy.stress, 0.1)

    def test_apply_enabled_bumps_stress(self):
        dummy = IdentityDummy()
        dummy.identity_threat_stress_enabled = True
        self.assertTrue(dummy.apply_identity_threat(dims={"hit": 0.9}))
        self.assertGreater(dummy.stress, 0.1)

    def test_feedback_user_numeric_cold_and_warm(self):
        cold = IdentityDummy()
        cold.feedback_user(cold=1.0)
        self.assertLess(cold.trust, 0.5)
        warm = IdentityDummy()
        warm.feedback_user(warm=1.0)
        self.assertGreater(warm.trust, 0.5)


class GoalNumericTest(unittest.TestCase):
    def test_goal_relevance_from_dims(self):
        dummy = GoalDummy()
        self.assertGreater(dummy._goal_relevance_from_dims(
            {"involve": 1.0}), 0.4)
        self.assertEqual(dummy._goal_relevance_from_dims({}), 0.0)

    def test_update_goals_uses_dims(self):
        dummy = GoalDummy()
        dummy._update_goals("随便什么字", dims={"involve": 1.0, "blame": 0.5})
        self.assertGreater(dummy.appraisal["goal_relevance"], 0.0)
        self.assertTrue(all(v > 0.0 for v in dummy.goal_scores.values()))
        self.assertLess(dummy.appraisal["norm_compatibility"], 0.5)

    def test_update_goals_ignores_text_words_without_dims(self):
        dummy = GoalDummy()
        dummy._update_goals("谢谢 喜欢 谢谢")
        self.assertEqual(dummy.appraisal["goal_relevance"], 0.0)

    def test_goal_evidence_dims_beats_text(self):
        dummy = GoalDummy()
        goal = dummy.goals[0]
        self.assertGreater(dummy._goal_evidence(goal, "", "",
                                               dims={"hit": 1.0}), 0.0)
        self.assertEqual(dummy._goal_evidence(goal, "谢谢 喜欢", ""), 0.0)


if __name__ == "__main__":
    unittest.main()
