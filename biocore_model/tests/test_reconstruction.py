# -*- coding: utf-8 -*-
"""Memory reconstruction: bounded drift, direction, conservation."""
import unittest

from biocore_model import reconstruction as rc

ENTRY = {"text": "那天一起看了海", "importance": 0.5, "valence": 0.2}


class MagnitudeTest(unittest.TestCase):
    def test_zero_recalls_no_drift(self):
        self.assertEqual(rc.magnitude(0), 0.0)

    def test_grows_with_recalls(self):
        self.assertGreater(rc.magnitude(5), rc.magnitude(1))

    def test_capped(self):
        self.assertLessEqual(rc.magnitude(10 ** 6), rc.DRIFT_CAP)


class DirectionTest(unittest.TestCase):
    def test_warm_mood_positive(self):
        self.assertEqual(rc.direction(0.6), 1)

    def test_low_mood_negative(self):
        self.assertEqual(rc.direction(-0.5), -1)

    def test_neutral(self):
        self.assertEqual(rc.direction(0.0), 0)


class DriftTest(unittest.TestCase):
    def test_no_recall_no_change(self):
        out = rc.drift(ENTRY, mood=0.8, recalls=0)
        self.assertEqual(out["delta"], 0.0)

    def test_warm_mood_moves_positive(self):
        out = rc.drift(ENTRY, mood=0.8, recalls=3)
        self.assertGreater(out["delta"], 0.0)

    def test_low_mood_moves_negative(self):
        out = rc.drift(ENTRY, mood=-0.8, recalls=3)
        self.assertLess(out["delta"], 0.0)

    def test_neutral_mood_no_change(self):
        out = rc.drift(ENTRY, mood=0.0, recalls=3)
        self.assertEqual(out["delta"], 0.0)

    def test_important_memory_never_drifts(self):
        row = dict(ENTRY, importance=0.95)
        out = rc.drift(row, mood=0.9, recalls=20)
        self.assertEqual(out["delta"], 0.0)
        self.assertEqual(out["reason"], "重要记忆不漂")

    def test_empty_text_no_change(self):
        out = rc.drift({"importance": 0.3}, mood=0.9, recalls=3)
        self.assertEqual(out["delta"], 0.0)

    def test_cap_respected(self):
        out = rc.drift(ENTRY, mood=1.0, recalls=1000, prior_drift=0.10)
        self.assertLessEqual(abs(out["total"]), rc.DRIFT_CAP)
        self.assertTrue(out["capped"])

    def test_conservation_positive_side(self):
        out = rc.drift(ENTRY, mood=1.0, recalls=50, prior_drift=0.10)
        self.assertAlmostEqual(out["total"], rc.DRIFT_CAP, places=3)

    def test_conservation_negative_side(self):
        out = rc.drift(ENTRY, mood=-1.0, recalls=50, prior_drift=-0.10)
        self.assertAlmostEqual(out["total"], -rc.DRIFT_CAP, places=3)

    def test_disabled(self):
        out = rc.drift(ENTRY, mood=0.9, recalls=5, flags={"enabled": False})
        self.assertEqual(out["delta"], 0.0)
        self.assertFalse(out["enabled"])

    def test_malformed_entry(self):
        out = rc.drift("nope", mood="x", recalls="y")
        self.assertEqual(out["delta"], 0.0)

    def test_bounded_without_prior(self):
        out = rc.drift(ENTRY, mood=-1.0, recalls=5)
        self.assertGreaterEqual(out["total"], -rc.DRIFT_CAP)


class HintTest(unittest.TestCase):
    def test_no_hint_when_tiny(self):
        self.assertEqual(rc.text_hint({"enabled": True, "total": 0.0}), "")

    def test_warm_hint(self):
        self.assertIn("暖", rc.text_hint({"enabled": True, "total": 0.05}))

    def test_cold_hint(self):
        self.assertIn("凉", rc.text_hint({"enabled": True, "total": -0.05}))

    def test_disabled_hint(self):
        self.assertEqual(rc.text_hint({"enabled": False, "total": 0.05}), "")


class ConserveTest(unittest.TestCase):
    def test_within_cap_untouched(self):
        out = rc.conserve([{"drift": 0.03}, {"drift": -0.02}])
        self.assertEqual(out["scale"], 1.0)

    def test_scales_down(self):
        out = rc.conserve([{"drift": 0.3}, {"drift": 0.3}])
        self.assertLessEqual(abs(out["total"]), rc.DRIFT_CAP)


if __name__ == "__main__":
    unittest.main()
