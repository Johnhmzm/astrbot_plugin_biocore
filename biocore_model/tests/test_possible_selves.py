# -*- coding: utf-8 -*-
"""Possible selves: gaps, weights, one-line sentence."""
import unittest

from biocore_model import possible_selves as ps

SELVES = [
    {"name": "更会照顾人", "target": {"benevolence": 0.95}, "importance": 0.9},
    {"name": "更安定", "target": {"security": 0.95}, "importance": 0.5},
    {"name": "更会说", "target": {"power": 0.9}, "importance": 0.3},
]
CURRENT = {"benevolence": 0.5, "security": 0.9, "power": 0.85}


class GapTest(unittest.TestCase):
    def test_gap_positive(self):
        value = ps.gap({"benevolence": 0.9}, {"benevolence": 0.4})
        self.assertAlmostEqual(value, 0.5)

    def test_gap_zero_when_matching(self):
        self.assertEqual(ps.gap({"security": 0.5}, {"security": 0.5}), 0.0)

    def test_gap_bounded(self):
        self.assertLessEqual(ps.gap({"power": 1.0}, {"power": 0.0}), 1.0)

    def test_empty_target(self):
        self.assertEqual(ps.gap({}, {"power": 1.0}), 0.0)


class RankTest(unittest.TestCase):
    def test_sorted_by_weight(self):
        out = ps.rank(SELVES, CURRENT)
        weights = [item["weight"] for item in out["selves"]]
        self.assertEqual(weights, sorted(weights, reverse=True))

    def test_top_is_biggest_gap(self):
        out = ps.rank(SELVES, CURRENT)
        self.assertEqual(out["top"], "更会照顾人")

    def test_shares_sum_to_one(self):
        out = ps.rank(SELVES, CURRENT)
        self.assertAlmostEqual(sum(item["share"] for item in out["selves"]), 1.0, places=2)

    def test_importance_scales_weight(self):
        low = {"name": "a", "target": {"benevolence": 0.9}, "importance": 0.1}
        high = {"name": "b", "target": {"benevolence": 0.9}, "importance": 0.9}
        out = ps.rank([low, high], {"benevolence": 0.1})
        self.assertEqual(out["top"], "b")

    def test_sentence(self):
        out = ps.rank(SELVES, CURRENT)
        self.assertIn("她还想成为", out["sentence"])
        self.assertLessEqual(len(out["sentence"]), ps.SENTENCE_LIMIT)

    def test_caps_self_count(self):
        many = [{"name": "s%d" % i, "target": {"benevolence": 0.9}} for i in range(20)]
        self.assertLessEqual(len(ps.rank(many, CURRENT)["selves"]), ps.MAX_SELVES)


class FallbackTest(unittest.TestCase):
    def test_disabled(self):
        out = ps.rank(SELVES, CURRENT, flags={"enabled": False})
        self.assertFalse(out["enabled"])
        self.assertEqual(out["selves"], [])
        self.assertEqual(out["sentence"], "")

    def test_malformed(self):
        out = ps.rank([None, "x", {"name": ""}, {"name": "ok", "target": {}}], "bad")
        self.assertEqual(out["selves"], [])

    def test_no_current_uses_default(self):
        out = ps.rank([{"name": "a", "target": {"security": 1.0}}], None)
        self.assertGreater(out["selves"][0]["gap"], 0.0)


class DirectiveTest(unittest.TestCase):
    def test_pull_matches_top(self):
        result = ps.rank(SELVES, CURRENT)
        out = ps.directives(result)
        self.assertIn("更会照顾人", out["tone"])
        self.assertGreater(out["pull"], 0.0)

    def test_disabled(self):
        self.assertEqual(ps.directives({"enabled": False})["tone"], "")


if __name__ == "__main__":
    unittest.main()
