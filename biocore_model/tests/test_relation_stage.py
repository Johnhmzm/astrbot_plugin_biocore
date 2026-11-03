# -*- coding: utf-8 -*-
"""Relationship stage: progress, thresholds, actions, fairness."""
import unittest

from biocore_model import relation_stage as rs


def state(**kwargs):
    base = {"interactions": 0, "disclosures": 0, "repairs": 0,
            "days_known": 0, "conflict": 0.0}
    base.update(kwargs)
    return base


class ProgressTest(unittest.TestCase):
    def test_empty_is_zero(self):
        self.assertEqual(rs.progress({}), 0.0)

    def test_more_interactions_more_progress(self):
        low = rs.progress(state(interactions=2))
        high = rs.progress(state(interactions=40))
        self.assertGreater(high, low)

    def test_disclosure_moves_stage_fast(self):
        low = rs.progress(state(interactions=5))
        high = rs.progress(state(interactions=5, disclosures=10))
        self.assertGreater(high, low)

    def test_repairs_add(self):
        low = rs.progress(state(interactions=10, disclosures=4))
        high = rs.progress(state(interactions=10, disclosures=4, repairs=3))
        self.assertGreater(high, low)

    def test_conflict_subtracts(self):
        calm = rs.progress(state(interactions=20, disclosures=6))
        tense = rs.progress(state(interactions=20, disclosures=6, conflict=0.9))
        self.assertLess(tense, calm)

    def test_progress_bounded(self):
        value = rs.progress(state(interactions=9999, disclosures=9999, repairs=9999,
                                  days_known=9999))
        self.assertLessEqual(value, 1.0)
        self.assertGreaterEqual(value, 0.0)


class StageTest(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(rs.stage_of(0.1), "陌生")
        self.assertEqual(rs.stage_of(0.5), "熟悉")
        self.assertEqual(rs.stage_of(0.7), "亲近")
        self.assertEqual(rs.stage_of(0.9), "稳定")

    def test_actions_match_stages(self):
        for stage in rs.STAGES:
            self.assertIn(stage, rs.ACTIONS)

    def test_evaluate_basic(self):
        out = rs.evaluate(state(interactions=50, disclosures=12))
        self.assertIn(out["stage"], rs.STAGES)
        self.assertTrue(out["action"])


class FairnessTest(unittest.TestCase):
    def test_balanced(self):
        out = rs.comparison({"his_investment": 0.5, "hers_investment": 0.5})
        self.assertEqual(out["share"], 0.5)
        self.assertEqual(out["balance"], 0.0)

    def test_one_sided(self):
        out = rs.comparison({"his_investment": 0.9, "hers_investment": 0.1})
        self.assertGreater(out["balance"], 0.5)

    def test_one_sided_marks_tentative(self):
        out = rs.evaluate(state(interactions=50, disclosures=12,
                                social_comparison={"his_investment": 0.9,
                                                   "hers_investment": 0.1}))
        self.assertTrue(out["tentative"])

    def test_unfairness_slows_progress(self):
        fair = rs.progress(state(interactions=30, disclosures=8,
                                 social_comparison={"his_investment": 0.5,
                                                    "hers_investment": 0.5}))
        unfair = rs.progress(state(interactions=30, disclosures=8,
                                   social_comparison={"his_investment": 0.95,
                                                      "hers_investment": 0.05}))
        self.assertLess(unfair, fair)


class FallbackTest(unittest.TestCase):
    def test_disabled(self):
        out = rs.evaluate(state(interactions=100), flags={"enabled": False})
        self.assertFalse(out["enabled"])
        self.assertEqual(out["progress"], 0.0)

    def test_malformed(self):
        out = rs.evaluate("nope")
        self.assertIn(out["stage"], rs.STAGES)


class DirectiveTest(unittest.TestCase):
    def test_stage_tone(self):
        out = rs.directives({"enabled": True, "stage": "亲近"})
        self.assertIn("主动", out["tone"])

    def test_tentative_note(self):
        out = rs.directives({"enabled": True, "stage": "熟悉", "tentative": True})
        self.assertIn("不对等", out["tone"])

    def test_disabled(self):
        self.assertEqual(rs.directives({"enabled": False})["tone"], "")


if __name__ == "__main__":
    unittest.main()
