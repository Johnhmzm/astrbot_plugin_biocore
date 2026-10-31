# -*- coding: utf-8 -*-
"""Interoception core + regulation loop tests (formulas, bands, actions)."""
import math
import unittest

from biocore_model import intero_core as ic
from biocore_model import regulation_loop as rl

STATE = {"stress": 0.5, "arousal": 0.6, "sleep_debt": 0.4, "conflict": 0.2,
         "v": 0.2, "social": 0.6, "trust": 0.7, "closeness": 0.5,
         "sadness": 0.3, "allostatic_load": 0.2, "energy": 0.4,
         "loneliness": 0.5, "noise": 0.3}

GOOD = {"tension": 0.30, "warmth": 0.60, "heaviness": 0.30, "clarity": 0.70}
SHUT = {"tension": 0.10, "warmth": 0.05, "heaviness": 0.05, "clarity": 0.05}
OPEN = {"tension": 0.95, "warmth": 0.95, "heaviness": 0.95, "clarity": 0.95}


class FormulaTest(unittest.TestCase):
    def test_four_dimensions_exact(self):
        out = ic.target(STATE)
        self.assertAlmostEqual(out["tension"], 0.475, places=4)
        self.assertAlmostEqual(out["warmth"], 0.605, places=4)
        self.assertAlmostEqual(out["heaviness"], 0.35, places=4)
        self.assertAlmostEqual(out["clarity"], 0.70, places=4)

    def test_formula_matches_spec(self):
        x = ic.inputs(STATE)
        expect_tension = (0.45 * x["stress"] + 0.25 * x["arousal"]
                          + 0.20 * x["sleep_debt"] + 0.10 * x["conflict"])
        expect_warmth = (0.40 * ((x["v"] + 1.0) / 2.0) + 0.25 * x["social"]
                         + 0.20 * x["trust"] + 0.15 * x["closeness"])
        expect_heavy = (0.40 * x["sadness"] + 0.30 * x["allostatic_load"]
                        + 0.20 * (1.0 - x["energy"]) + 0.10 * x["loneliness"])
        expect_clarity = (0.40 * (1.0 - x["noise"]) + 0.30 * (1.0 - x["sleep_debt"])
                          + 0.30 * (1.0 - abs(x["arousal"] - 0.5) * 2.0))
        out = ic.target(STATE)
        self.assertAlmostEqual(out["tension"], round(expect_tension, 4))
        self.assertAlmostEqual(out["warmth"], round(expect_warmth, 4))
        self.assertAlmostEqual(out["heaviness"], round(expect_heavy, 4))
        self.assertAlmostEqual(out["clarity"], round(expect_clarity, 4))

    def test_clamped_boundaries(self):
        out = ic.target({"stress": 5, "arousal": -3, "sleep_debt": -2,
                         "conflict": 9, "v": -9, "social": 9, "trust": -4,
                         "closeness": 9, "sadness": 9, "allostatic_load": -1,
                         "energy": -9, "loneliness": 9, "noise": 9})
        for dim in ic.DIMS:
            self.assertGreaterEqual(out[dim], 0.0)
            self.assertLessEqual(out[dim], 1.0)

    def test_defaults_on_empty_state(self):
        out = ic.target({})
        self.assertAlmostEqual(out["tension"], 0.125, places=4)
        self.assertAlmostEqual(out["warmth"], 0.50, places=4)
        self.assertAlmostEqual(out["heaviness"], 0.09, places=4)
        self.assertAlmostEqual(out["clarity"], 1.00, places=4)

    def test_arousal_alias_and_label_fallbacks(self):
        self.assertAlmostEqual(ic.inputs({"a": 0.9})["arousal"], 0.9)
        sad = ic.inputs({"labels": {"emotion": "sadness"}, "intensity": 0.8})
        self.assertAlmostEqual(sad["sadness"], 0.8)
        lone = ic.inputs({"labels": {"emotion": "loneliness"}, "intensity": 0.6})
        self.assertAlmostEqual(lone["loneliness"], 0.6)

    def test_noise_dict_is_averaged(self):
        self.assertAlmostEqual(ic.inputs({"noise": {"a": 0.2, "b": -0.4}})["noise"], 0.3)


class UpdateTest(unittest.TestCase):
    def test_ema_moves_toward_target(self):
        prev = dict(GOOD)
        new = ic.update(prev, STATE, dt_hours=1.0, rate=0.25)
        alpha = 1.0 - math.exp(-0.25)
        goal = ic.target(STATE)
        for dim in ic.DIMS:
            expect = round(prev[dim] + alpha * (goal[dim] - prev[dim]), 4)
            self.assertAlmostEqual(new[dim], expect, places=4)

    def test_zero_dt_is_identity(self):
        prev = {"tension": 0.1, "warmth": 0.7, "heaviness": 0.2, "clarity": 0.9}
        out = ic.update(prev, STATE, dt_hours=0.0)
        for dim in ic.DIMS:
            self.assertAlmostEqual(out[dim], prev[dim])

    def test_same_now_is_idempotent(self):
        prev = {"tension": 0.1, "warmth": 0.7, "heaviness": 0.2,
                "clarity": 0.9, "ts": 1000.0}
        out = ic.update(prev, STATE, dt_hours=1.0, now=1000.0)
        for dim in ic.DIMS:
            self.assertAlmostEqual(out[dim], prev[dim])
        self.assertEqual(out["ts"], 1000.0)

    def test_dt_derived_from_now_and_ts(self):
        prev = {"tension": 0.1, "warmth": 0.7, "heaviness": 0.2,
                "clarity": 0.9, "ts": 0.0}
        a = ic.update(prev, STATE, dt_hours=1.0)
        b = ic.update(prev, STATE, now=3600.0)
        for dim in ic.DIMS:
            self.assertAlmostEqual(a[dim], b[dim])

    def test_converges_after_many_steps(self):
        cur = {"tension": 0.0, "warmth": 0.0, "heaviness": 0.0, "clarity": 0.0}
        goal = ic.target(STATE)
        for _ in range(200):
            cur = ic.update(cur, STATE, dt_hours=1.0, rate=0.25)
        for dim in ic.DIMS:
            self.assertAlmostEqual(cur[dim], goal[dim], places=2)


class DiscomfortTest(unittest.TestCase):
    def test_inside_band_is_zero(self):
        self.assertEqual(ic.discomfort(GOOD)["total"], 0.0)
        self.assertEqual(ic.discomfort(GOOD)["parts"], dict.fromkeys(ic.DIMS, 0.0))

    def test_outside_band_positive_and_bounded(self):
        shut = ic.discomfort(SHUT)
        self.assertGreater(shut["total"], 0.0)
        self.assertLessEqual(shut["total"], 1.0)
        self.assertGreater(shut["parts"]["tension"], 0.0)
        self.assertGreater(shut["parts"]["warmth"], 0.0)

    def test_extremes_are_bounded_and_high(self):
        self.assertGreater(ic.discomfort(OPEN)["total"], 0.6)
        worst = {"tension": 1.0, "warmth": 0.0, "heaviness": 1.0, "clarity": 0.0}
        self.assertAlmostEqual(ic.discomfort(worst)["total"], 1.0, places=2)

    def test_setpoint_override(self):
        override = {"comfort": {"tension": 0.90}, "band": {"tension": 0.05}}
        flat = ic.discomfort(GOOD)
        moved = ic.discomfort(GOOD, override)
        self.assertGreater(moved["total"], flat["total"])

    def test_view_shape(self):
        out = ic.view(SHUT)
        for dim in ic.DIMS:
            self.assertIn(dim, out)
        self.assertIn("discomfort", out)
        self.assertAlmostEqual(out["discomfort"], ic.discomfort(SHUT)["total"])


class ChooseActionTest(unittest.TestCase):
    def _pick(self, intero, context=None):
        out = rl.choose_action(intero, context)
        self.assertIn(out["action"], rl.ACTIONS)
        self.assertTrue(out["reason"])
        self.assertGreaterEqual(out["expected_gain"], 0.0)
        self.assertLessEqual(out["expected_gain"], 1.0)
        return out["action"]

    def test_conflict_plus_tension_repairs(self):
        self.assertEqual(self._pick({"tension": 0.80, "warmth": 0.40,
                                     "heaviness": 0.20, "clarity": 0.70},
                                    {"conflict": 0.6}), "repair")

    def test_tense_but_warm_approaches(self):
        self.assertEqual(self._pick({"tension": 0.70, "warmth": 0.50,
                                     "heaviness": 0.20, "clarity": 0.70},
                                    {"conflict": 0.0}), "approach")

    def test_heavy_exhausted_rests(self):
        self.assertEqual(self._pick({"tension": 0.30, "warmth": 0.50,
                                     "heaviness": 0.80, "clarity": 0.60},
                                    {"energy": 0.10}), "rest")

    def test_heavy_low_energy_withdraws(self):
        self.assertEqual(self._pick({"tension": 0.30, "warmth": 0.50,
                                     "heaviness": 0.80, "clarity": 0.60},
                                    {"energy": 0.30}), "withdraw")

    def test_unclear_asks(self):
        self.assertEqual(self._pick({"tension": 0.30, "warmth": 0.55,
                                     "heaviness": 0.20, "clarity": 0.20},
                                    {"conflict": 0.4}), "question")

    def test_cold_no_conflict_shares(self):
        self.assertEqual(self._pick({"tension": 0.30, "warmth": 0.20,
                                     "heaviness": 0.20, "clarity": 0.80},
                                    {"conflict": 0.0}), "share")

    def test_unclear_cold_shares(self):
        self.assertEqual(self._pick({"tension": 0.30, "warmth": 0.40,
                                     "heaviness": 0.20, "clarity": 0.20},
                                    {"conflict": 0.0}), "share")

    def test_warm_defaults_to_approach(self):
        self.assertEqual(self._pick({"tension": 0.20, "warmth": 0.85,
                                     "heaviness": 0.10, "clarity": 0.90}), "approach")


class OutcomeEfficacyTest(unittest.TestCase):
    def test_outcome_improved(self):
        out = rl.outcome(SHUT, GOOD, "repair")
        self.assertLess(out["delta_discomfort"], 0)
        self.assertTrue(out["success"])
        self.assertEqual(out["action"], "repair")

    def test_outcome_worse(self):
        out = rl.outcome(GOOD, SHUT, "share")
        self.assertGreater(out["delta_discomfort"], 0)
        self.assertFalse(out["success"])

    def test_outcome_accepts_discomfort_dicts(self):
        before = ic.discomfort(SHUT)
        after = ic.discomfort(GOOD)
        out = rl.outcome(before, after, "rest")
        self.assertTrue(out["success"])

    def test_efficacy_prior_and_ewma(self):
        self.assertAlmostEqual(rl.efficacy([], "approach"), 0.5)
        self.assertAlmostEqual(rl.efficacy([("approach", True)], "approach"), 0.625)
        self.assertAlmostEqual(
            rl.efficacy([("approach", True), ("approach", False)], "approach"), 0.4688)
        self.assertAlmostEqual(rl.efficacy([("share", False)], "approach"), 0.5)

    def test_efficacy_dict_rows_and_bounds(self):
        rows = [{"action": "rest", "success": True} for _ in range(20)]
        self.assertGreater(rl.efficacy(rows, "rest"), 0.9)
        self.assertLessEqual(rl.efficacy(rows, "rest"), 1.0)
        self.assertEqual(rl.sample("rest", True)["action"], "rest")


if __name__ == "__main__":
    unittest.main()
