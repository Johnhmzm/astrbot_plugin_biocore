# -*- coding: utf-8 -*-
"""Metacognition: confidence bands, stance conflict, convergence."""
import unittest

from biocore_model import metacog as mc

class BandTest(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(mc.band(0.2), "low")
        self.assertEqual(mc.band(0.6), "mid")
        self.assertEqual(mc.band(0.9), "high")

    def test_bad_input_is_low(self):
        self.assertEqual(mc.band("x"), "low")
        self.assertEqual(mc.band(None), "low")

class GuardTest(unittest.TestCase):
    def test_hits_lower_confidence(self):
        out = mc.evaluate(confidence=0.8, guard_hits=1)
        self.assertAlmostEqual(out["confidence"], 0.7)
        self.assertTrue(out["uncertainty"])

    def test_penalty_capped(self):
        out = mc.evaluate(confidence=0.9, guard_hits=5)
        self.assertAlmostEqual(out["confidence"], 0.6)

    def test_accepts_list_and_dict(self):
        a = mc.evaluate(confidence=0.8, guard_hits=["len", "tone"])
        b = mc.evaluate(confidence=0.8, guard_hits={"len": 1, "tone": 1})
        self.assertEqual(a["confidence"], b["confidence"])

class ConflictTest(unittest.TestCase):
    def test_conflict_allows_correction(self):
        out = mc.evaluate(confidence=0.7, conflict=True)
        self.assertTrue(out["allow_self_correction"])

    def test_low_confidence_no_correction(self):
        out = mc.evaluate(confidence=0.2, conflict=True)
        self.assertFalse(out["allow_self_correction"])

    def test_conflict_dict_form(self):
        out = mc.evaluate(confidence=0.7, conflict={"conflicts_with_stance": True})
        self.assertTrue(out["allow_self_correction"])

class StreakTest(unittest.TestCase):
    def test_three_lows_converge(self):
        out = mc.evaluate(confidence=0.3, history={"low_flags": [True, True]})
        self.assertTrue(out["converge"])
        self.assertEqual(out["low_streak"], 3)

    def test_two_lows_no_converge(self):
        out = mc.evaluate(confidence=0.3, history=[True])
        self.assertFalse(out["converge"])

    def test_high_breaks_streak(self):
        out = mc.evaluate(confidence=0.9, history=[True, True, False])
        self.assertFalse(out["converge"])

    def test_remember_trims(self):
        history = {"low_flags": [True] * 8}
        out = mc.remember(history, {"band": "low"})
        self.assertEqual(len(out["low_flags"]), 8)
        self.assertTrue(out["low_flags"][-1])

class DisabledTest(unittest.TestCase):
    def test_off_is_neutral(self):
        out = mc.evaluate(confidence=0.2, guard_hits=3, conflict=True,
                          flags={"enabled": False})
        self.assertFalse(out["enabled"])
        self.assertFalse(out["uncertainty"])
        self.assertFalse(out["allow_self_correction"])
        self.assertFalse(out["converge"])
        self.assertEqual(out["confidence"], 0.2)

class MalformedTest(unittest.TestCase):
    def test_garbage_inputs(self):
        out = mc.evaluate(intent=None, confidence="x", guard_hits="?",
                          conflict=None, history="nope")
        self.assertIn("reason", out)
        self.assertGreaterEqual(out["confidence"], 0.0)
        self.assertLessEqual(out["confidence"], 1.0)

    def test_nan_confidence(self):
        out = mc.evaluate(confidence=float("nan"))
        self.assertEqual(out["band"], "low")

class DirectiveTest(unittest.TestCase):
    def test_low_confidence_shortens(self):
        out = mc.directives(mc.evaluate(confidence=0.2))
        self.assertLess(out["length_scale"], 1.0)
        self.assertIn("别承诺", out["tone"])

    def test_converge_shortens_more(self):
        result = mc.evaluate(confidence=0.2, history=[True, True])
        out = mc.directives(result)
        self.assertAlmostEqual(out["length_scale"], 0.7)

    def test_high_confidence_keeps_length(self):
        out = mc.directives(mc.evaluate(confidence=0.95))
        self.assertEqual(out["length_scale"], 1.0)

if __name__ == "__main__":
    unittest.main()
