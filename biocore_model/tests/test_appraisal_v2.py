# -*- coding: utf-8 -*-
"""task-243: appraisal_v2 -- v is goal + explicit valence, blame/hit go home.

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_appraisal_v2.py"
"""
import os
import unittest
from unittest import mock

from biocore_model import appraisal as ap


def dims(**kw):
    base = {"goal": 0.0, "blame": 0.0, "control": 0.5, "certainty": 0.5,
            "novelty": 0.0, "involve": 0.5, "hit": 0.0}
    base.update(kw)
    return base


class AppraisalV2Test(unittest.TestCase):
    """v2 destination table: one home per dimension."""

    def test_v_only_follows_goal(self):
        plain = ap.appraise(dims(goal=0.4), 1.0, v2=True)
        noisy = ap.appraise(dims(goal=0.4, blame=0.9, hit=0.9), 1.0, v2=True)
        self.assertAlmostEqual(plain.get("v", 0.0), noisy.get("v", 0.0),
                               places=6)

    def test_explicit_valence_signal_enters_v(self):
        quiet = ap.appraise(dims(goal=0.1), 1.0, v2=True)
        warm = ap.appraise(dims(goal=0.1, valence=0.6), 1.0, v2=True)
        self.assertGreater(warm["v"], quiet["v"])
        self.assertAlmostEqual(warm["v"], ap.CAPS["v"], places=4)  # capped
        self.assertNotIn("v", quiet) if abs(quiet.get("v", 0.0)) <= 1e-9 else None

    def test_blame_goes_to_trust_and_conflict(self):
        base = ap.appraise(dims(blame=0.0), 1.0, v2=True)
        blamed = ap.appraise(dims(blame=0.8), 1.0, v2=True)
        self.assertLess(blamed["trust"], base.get("trust", 0.0))
        self.assertGreater(blamed["conflict"], 0.0)
        self.assertAlmostEqual(blamed.get("v", 0.0), base.get("v", 0.0),
                               places=6)

    def test_hit_goes_to_stress_and_self_esteem(self):
        base = ap.appraise(dims(hit=0.0), 1.0, v2=True)
        hurt = ap.appraise(dims(hit=0.8), 1.0, v2=True)
        self.assertGreater(hurt["stress"], base.get("stress", 0.0))
        self.assertLess(hurt["self_esteem"], base.get("self_esteem", 0.0))
        self.assertAlmostEqual(hurt.get("v", 0.0), base.get("v", 0.0),
                               places=6)

    def test_control_only_moves_dominance(self):
        low = ap.appraise(dims(control=0.0), 1.0, v2=True)
        high = ap.appraise(dims(control=1.0), 1.0, v2=True)
        self.assertGreater(high.get("d", 0.0), low.get("d", 0.0))
        self.assertAlmostEqual(high.get("v", 0.0), low.get("v", 0.0), places=6)

    def test_novelty_and_involve_keep_their_own_lines(self):
        novelty = ap.appraise(dims(novelty=1.0), 1.0, v2=True)
        involve = ap.appraise(dims(involve=1.0), 1.0, v2=True)
        self.assertGreater(novelty.get("a", 0.0), 0.0)
        self.assertGreater(involve.get("social", 0.0), 0.0)
        self.assertAlmostEqual(novelty.get("v", 0.0), involve.get("v", 0.0),
                               places=6)

    def test_switch_off_restores_the_old_mapping(self):
        data = dims(goal=0.4, blame=0.8, hit=0.8, novelty=0.5, involve=0.8)
        old = ap.appraise(data, 1.0, v2=False)
        values = {name: data[name] for name in ap.DIMS}
        gain = 1.0 + ap.INVOLVE_GAIN * values["involve"]
        expected = 0.0
        for name in ap.DIMS:
            expected += ap.WEIGHTS[name]["v"] * values[name]
        expected = max(-ap.CAPS["v"], min(ap.CAPS["v"], expected * gain))
        self.assertAlmostEqual(old["v"], round(expected, 4), places=4)
        self.assertNotIn("conflict", old)
        detail = ap.appraise_detail(data, 1.0, v2=False)
        self.assertEqual(detail["mapping"], "v1")

    def test_components_keep_one_row_per_dimension(self):
        detail = ap.appraise_detail(dims(goal=0.4, blame=0.8, hit=0.8,
                                         control=0.7, novelty=0.6,
                                         involve=0.6, certainty=0.4), 1.0,
                                    v2=True)
        self.assertEqual(detail["mapping"], "v2")
        self.assertEqual(sorted(detail["components"]["v"]["rows"]), ["goal"])
        self.assertIn("blame", detail["components"]["trust"]["rows"])
        self.assertIn("blame", detail["components"]["conflict"]["rows"])
        self.assertIn("hit", detail["components"]["stress"]["rows"])
        self.assertIn("hit", detail["components"]["self_esteem"]["rows"])
        self.assertIn("control", detail["components"]["d"]["rows"])
        self.assertIn("novelty", detail["components"]["a"]["rows"])
        self.assertIn("involve", detail["components"]["social"]["rows"])
        self.assertGreater(detail["components"]["v"]["capped"], 0.0)

    def test_default_is_on_and_the_flag_can_turn_it_off(self):
        self.assertTrue(ap.enabled({}))
        self.assertFalse(ap.enabled({"appraisal_v2": False}))
        self.assertFalse(ap.enabled({"switches": {"appraisal_v2": False}}))
        with mock.patch.dict(os.environ, {"BIOCORE_APPRAISAL_V2": "0"}):
            self.assertFalse(ap.enabled({}))

    def test_caps_still_apply(self):
        out = ap.appraise(dims(goal=1.0), 1.0, v2=True)
        self.assertLessEqual(abs(out["v"]), ap.CAPS["v"] + 1e-9)


class LegacyVTest(unittest.TestCase):
    """v2 also records what the old mapping would have said -- read-only."""

    def payload(self):
        # old v = 0.24 - 0.225 - 0.18 = -0.165 -> -0.1155 at confidence 0.7
        return dims(goal=0.4, blame=0.9, hit=0.9)

    def test_both_values_are_recorded(self):
        out = ap.appraise_with_legacy(self.payload(), 0.7, v2=True)
        self.assertGreater(out["v"], 0.0)
        self.assertLess(out["v_legacy"], 0.0)      # the old v was dragged down
        self.assertEqual(out["v"], out["deltas"]["v"])
        self.assertEqual(out["v_legacy"],
                         ap.legacy_v(self.payload(), 0.7))

    def test_mapping_label_is_honest(self):
        self.assertEqual(
            ap.appraise_with_legacy(self.payload(), 0.7, v2=True)["mapping"],
            "v2")
        self.assertEqual(
            ap.appraise_with_legacy(self.payload(), 0.7, v2=False)["mapping"],
            "v1")

    def test_legacy_is_empty_when_v2_is_off(self):
        out = ap.appraise_with_legacy(self.payload(), 0.7, v2=False)
        self.assertIsNone(out["v_legacy"])
        self.assertEqual(out["v"], ap.legacy_v(self.payload(), 0.7))


if __name__ == "__main__":
    unittest.main()
