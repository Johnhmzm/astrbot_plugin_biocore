# -*- coding: utf-8 -*-
"""Value ordering: ten dimensions, loss aversion, sunk cost, status quo."""
import unittest

from biocore_model import value_order as vo

class DefaultsTest(unittest.TestCase):
    def test_ten_dimensions(self):
        table = vo.defaults()
        self.assertEqual(len(table), 10)
        self.assertEqual(set(table), set(vo.DIMENSIONS))

    def test_normalize_fills_and_clamps(self):
        table = vo.normalize({"security": 9, "benevolence": -3})
        self.assertEqual(table["security"], vo.WEIGHT_CEIL)
        self.assertEqual(table["benevolence"], vo.WEIGHT_FLOOR)
        self.assertNotIn("honesty", table)
        self.assertIn("universalism", table)

class UpdateTest(unittest.TestCase):
    def test_update_moves_slowly(self):
        before = vo.defaults()
        after = vo.update(before, {"benevolence": 0.15})
        self.assertLess(after["benevolence"] - before["benevolence"], 0.02)
        self.assertGreater(after["benevolence"], before["benevolence"])

    def test_update_bounded(self):
        table = vo.defaults()
        for _ in range(200):
            table = vo.update(table, {"power": 5.0})
        self.assertLessEqual(table["power"], vo.WEIGHT_CEIL)
        self.assertGreaterEqual(table["power"], vo.WEIGHT_FLOOR)

    def test_unknown_dimension_ignored(self):
        table = vo.update(vo.defaults(), {"flying": 1.0})
        self.assertEqual(set(table), set(vo.DIMENSIONS))

class LossAversionTest(unittest.TestCase):
    def test_loss_counts_double(self):
        table = vo.defaults()
        gain = vo.rank([{"name": "gain", "gains": {"benevolence": 0.5}}],
                       table)["ranked"][0]["score"]
        loss = vo.rank([{"name": "loss", "losses": {"benevolence": 0.5}}],
                       table)["ranked"][0]["score"]
        self.assertAlmostEqual(loss, -vo.LOSS_MULTIPLIER * gain, places=4)

class SunkCostTest(unittest.TestCase):
    def test_grows_with_age(self):
        young = vo.sunk_cost(10)
        old = vo.sunk_cost(730)
        self.assertGreater(old, young)
        self.assertLessEqual(old, vo.SUNK_COST_CAP)

    def test_capped(self):
        self.assertEqual(vo.sunk_cost(100000), vo.SUNK_COST_CAP)

class StatusQuoTest(unittest.TestCase):
    def test_threshold_in_range(self):
        value = vo.status_quo_threshold(vo.defaults(), 365)
        self.assertGreaterEqual(value, 0.05)
        self.assertLessEqual(value, vo.STATUS_QUO_CAP)

    def test_small_gain_keeps_status_quo(self):
        options = [
            {"name": "保持现状", "keeps_status_quo": True},
            {"name": "小改变", "gains": {"stimulation": 0.02}},
        ]
        out = vo.rank(options, vo.defaults(), {"investment": 0.8,
                                               "relationship_age_days": 365})
        self.assertEqual(out["chosen"], "保持现状")

    def test_big_gain_wins(self):
        options = [
            {"name": "保持现状", "keeps_status_quo": True},
            {"name": "大改变", "gains": {"security": 1.0, "benevolence": 1.0}},
        ]
        out = vo.rank(options, vo.defaults(), {"investment": 0.2,
                                               "relationship_age_days": 30})
        self.assertEqual(out["chosen"], "大改变")

class NecessityTest(unittest.TestCase):
    def test_priority_order(self):
        rows = vo.necessity_priority(vo.defaults())
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["need"], "被需要")
        self.assertGreaterEqual(rows[0]["value"], rows[-1]["value"])

    def test_custom_table_reorders(self):
        table = vo.defaults()
        table["security"] = 1.0
        table["benevolence"] = 0.2
        rows = vo.necessity_priority(table)
        self.assertEqual(rows[0]["need"], "安全感")

class FallbackTest(unittest.TestCase):
    def test_disabled_keeps_ranking(self):
        out = vo.rank([{"name": "a", "gains": {"security": 0.3}}],
                      vo.defaults(), {}, flags={"enabled": False})
        self.assertFalse(out["enabled"])
        self.assertEqual(out["chosen"], "a")

    def test_empty_options(self):
        out = vo.rank([], vo.defaults(), {})
        self.assertIsNone(out["chosen"])
        self.assertEqual(out["ranked"], [])

    def test_malformed(self):
        out = vo.rank([None, "x", {"name": "ok"}], "bad", "bad")
        self.assertEqual(len(out["ranked"]), 3)

class DirectiveTest(unittest.TestCase):
    def test_directive(self):
        out = vo.directives({"enabled": True, "chosen": "保持现状"})
        self.assertEqual(out["chosen"], "保持现状")

if __name__ == "__main__":
    unittest.main()
