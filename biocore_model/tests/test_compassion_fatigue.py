# -*- coding: utf-8 -*-
"""Compassion fatigue: decay, floor, recovery."""
import unittest

from biocore_model import compassion_fatigue as cf


class DecayTest(unittest.TestCase):
    def test_baseline_full_empathy(self):
        out = cf.fatigue(0, 0.0, 0.0)
        self.assertEqual(out["empathy"], 1.0)
        self.assertEqual(out["fatigue"], 0.0)

    def test_consecutive_comfort_lowers(self):
        one = cf.fatigue(1, 0.0, 0.0)
        five = cf.fatigue(5, 0.0, 0.0)
        self.assertLess(five["empathy"], one["empathy"])

    def test_negative_density_lowers(self):
        calm = cf.fatigue(2, 0.0, 0.0)
        heavy = cf.fatigue(2, 0.9, 0.0)
        self.assertLess(heavy["empathy"], calm["empathy"])

    def test_empathy_never_below_floor(self):
        out = cf.fatigue(999, 1.0, 0.0)
        self.assertGreaterEqual(out["empathy"], cf.EMPATHY_FLOOR)
        self.assertEqual(out["band"], "low")

    def test_fatigue_bounded(self):
        out = cf.fatigue(999, 1.0, 0.0)
        self.assertLessEqual(out["fatigue"], 1.0)
        self.assertGreaterEqual(out["fatigue"], 0.0)


class RecoveryTest(unittest.TestCase):
    def test_idle_restores(self):
        tired = cf.fatigue(6, 0.8, 0.0)
        rested = cf.fatigue(6, 0.8, 12.0)
        self.assertGreater(rested["empathy"], tired["empathy"])

    def test_recovery_reported(self):
        out = cf.fatigue(4, 0.5, 6.0)
        self.assertGreater(out["recovery"], 0.0)

    def test_full_rest_clears(self):
        out = cf.fatigue(4, 0.5, 200.0)
        self.assertGreater(out["empathy"], 0.95)


class BandTest(unittest.TestCase):
    def test_bands_present(self):
        for count, density in ((0, 0.0), (3, 0.4), (10, 1.0)):
            out = cf.fatigue(count, density, 0.0)
            self.assertIn(out["band"], ("high", "mid", "low"))
            self.assertTrue(out["advice"])

    def test_low_band_advice(self):
        out = cf.fatigue(20, 1.0, 0.0)
        self.assertEqual(out["advice"], cf.ADVICE["low"])


class FallbackTest(unittest.TestCase):
    def test_disabled(self):
        out = cf.fatigue(10, 1.0, 0.0, flags={"enabled": False})
        self.assertFalse(out["enabled"])
        self.assertEqual(out["empathy"], 1.0)

    def test_malformed(self):
        out = cf.fatigue("x", "y", "z")
        self.assertGreaterEqual(out["empathy"], cf.EMPATHY_FLOOR)


class DirectiveTest(unittest.TestCase):
    def test_low_empathy_shortens(self):
        out = cf.directives(cf.fatigue(20, 1.0, 0.0))
        self.assertLess(out["length_scale"], 1.0)
        self.assertTrue(out["tone"])

    def test_disabled(self):
        self.assertEqual(cf.directives({"enabled": False})["tone"], "")


if __name__ == "__main__":
    unittest.main()
