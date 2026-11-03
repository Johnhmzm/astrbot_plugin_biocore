# -*- coding: utf-8 -*-
import unittest

from biocore_model import affective_labor as al

NOW = 1_700_000_000
EXPRESSED = {"v": 0.6, "a": 0.4, "d": 0.5, "social": 0.5}
FELT = {"v": -0.6, "a": 0.4, "d": 0.5, "social": 0.5}


class AffectiveLaborGapTest(unittest.TestCase):
    def test_identical_state_has_no_gap(self):
        self.assertEqual(al.deviation(FELT, dict(FELT)), 0.0)

    def test_opposite_valence_is_full_gap(self):
        self.assertAlmostEqual(al.deviation({"v": -1.0}, {"v": 1.0}), 1.0)

    def test_single_dim_half_gap(self):
        self.assertAlmostEqual(al.deviation({"v": 0.0}, {"v": 1.0}), 0.5)

    def test_gap_is_weighted_across_present_dims(self):
        gap = al.deviation({"v": 0.0, "a": 0.5}, {"v": 1.0, "a": 0.5})
        self.assertAlmostEqual(gap, 0.3)

    def test_missing_dims_do_not_dilute(self):
        gap = al.deviation({"v": 0.0}, {"v": 1.0, "a": 0.0})
        self.assertAlmostEqual(gap, 0.5)

    def test_bad_inputs_are_zero_gap(self):
        self.assertEqual(al.deviation(None, None), 0.0)
        self.assertEqual(al.deviation({"v": "x"}, {"v": 1.0}), 0.0)


class AffectiveLaborCostTest(unittest.TestCase):
    def test_more_suppression_costs_more(self):
        honest = al.masking({"v": 0.6}, {"v": -0.6}, honesty=1.0)
        half = al.masking({"v": 0.6}, {"v": -0.6}, honesty=0.5)
        hidden = al.masking({"v": 0.6}, {"v": -0.6}, honesty=0.0)
        self.assertEqual(honest, 0.0)
        self.assertGreater(half, honest)
        self.assertGreater(hidden, half)

    def test_energy_cost_is_monotonic(self):
        self.assertGreater(al.energy_cost(0.8), al.energy_cost(0.2))
        self.assertAlmostEqual(al.energy_cost(0.5), al.MASK_COST * 0.5)

    def test_honest_turn_is_free(self):
        self.assertEqual(al.turn_cost(EXPRESSED, FELT, honesty=1.0), 0.0)

    def test_dishonest_turn_costs_energy(self):
        self.assertGreater(al.turn_cost(EXPRESSED, FELT, honesty=0.0), 0.0)


class AffectiveLaborLoadTest(unittest.TestCase):
    def test_one_hidden_turn_accumulates_load(self):
        state = al.update(al.initial(NOW - 7200), {"v": 0.0}, {"v": 1.0},
                          honesty=0.0, now=NOW)
        self.assertAlmostEqual(state["load"], al.energy_cost(0.5))
        self.assertEqual(state["turns"], 1)

    def test_same_turn_is_idempotent(self):
        once = al.update(al.initial(NOW - 10), {"v": 0.0}, {"v": 1.0}, now=NOW)
        twice = al.update(once, {"v": 0.0}, {"v": 1.0}, now=NOW)
        self.assertEqual(twice["load"], once["load"])
        self.assertEqual(twice["turns"], once["turns"])

    def test_load_recovers_over_time(self):
        state = dict(al.initial(NOW), load=0.80)
        rested = al.update(state, {"v": 0.5}, {"v": 0.5},
                           now=NOW + 10 * 3600)
        self.assertAlmostEqual(rested["load"], 0.50)

    def test_load_is_capped_at_one(self):
        state = dict(al.initial(NOW - 10), load=0.99)
        loaded = al.update(state, {"v": 0.6}, {"v": -0.6}, now=NOW)
        self.assertLessEqual(loaded["load"], 1.0)

    def test_breakdown_counter_on_threshold_crossing(self):
        state = dict(al.initial(NOW - 10), load=0.80, turns=1)
        broken = al.update(state, {"v": 0.6}, {"v": -0.6}, now=NOW)
        self.assertEqual(broken["breakdowns"], 1)
        self.assertTrue(al.collapsed(broken))

    def test_risk_and_headroom(self):
        state = dict(al.initial(NOW), load=0.425)
        self.assertAlmostEqual(al.risk(state), 0.5)
        self.assertAlmostEqual(al.headroom(state), 0.425)
        self.assertFalse(al.collapsed(state))
        heavy = dict(al.initial(NOW), load=0.90)
        self.assertTrue(al.collapsed(heavy))
        self.assertEqual(al.headroom(heavy), 0.0)

    def test_view_fields(self):
        state = al.update(al.initial(NOW - 10), EXPRESSED, FELT, now=NOW)
        panel = al.view(state)
        for key in ("load", "threshold", "risk", "headroom", "collapsed",
                    "last_cost", "last_masking", "turns", "breakdowns"):
            self.assertIn(key, panel)


if __name__ == "__main__":
    unittest.main()
