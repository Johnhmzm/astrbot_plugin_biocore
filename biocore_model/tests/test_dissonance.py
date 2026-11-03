# -*- coding: utf-8 -*-
"""Cognitive dissonance: strength and relief choice."""
import unittest

from biocore_model import dissonance as ds

STANCES = [{"text": "不熬夜", "weight": 0.8, "age_days": 1},
           {"text": "不翻旧账", "weight": 0.5, "age_days": 90}]

class StrengthTest(unittest.TestCase):
    def test_no_stance_is_zero(self):
        out = ds.strength([], {"kind": "熬夜"})
        self.assertEqual(out["dissonance"], 0.0)

    def test_no_behaviour_is_zero(self):
        out = ds.strength(STANCES, {})
        self.assertEqual(out["dissonance"], 0.0)

    def test_matching_stance_creates_tension(self):
        out = ds.strength(STANCES, {"kind": "熬夜", "contradicts": ["不熬夜"]})
        self.assertGreater(out["dissonance"], 0.2)
        self.assertIn("不熬夜", out["matched"])

    def test_salience_scales(self):
        low = ds.strength(STANCES, {"kind": "熬夜", "contradicts": ["不熬夜"],
                                 "salience": 0.2})
        high = ds.strength(STANCES, {"kind": "熬夜", "contradicts": ["不熬夜"],
                                  "salience": 1.0})
        self.assertGreater(high["dissonance"], low["dissonance"])

    def test_justification_lowers(self):
        raw = ds.strength(STANCES, {"kind": "熬夜", "contradicts": ["不熬夜"]})
        justified = ds.strength(STANCES, {"kind": "熬夜", "contradicts": ["不熬夜"],
                                     "justification": 0.9})
        self.assertLess(justified["dissonance"], raw["dissonance"])

    def test_old_stance_binds_less(self):
        fresh = ds.strength([{"text": "不熬夜", "weight": 0.8, "age_days": 1}],
                            {"kind": "熬夜", "contradicts": ["不熬夜"]})
        old = ds.strength([{"text": "不熬夜", "weight": 0.8, "age_days": 365}],
                          {"kind": "熬夜", "contradicts": ["不熬夜"]})
        self.assertGreater(fresh["dissonance"], old["dissonance"])

class ReliefTest(unittest.TestCase):
    def test_low_is_silence(self):
        self.assertEqual(ds.choose_relief(0.1), "沉默")

    def test_high_fresh_is_admission(self):
        self.assertEqual(ds.choose_relief(0.8, freshness=0.9), "承认")

    def test_high_stale_is_backtrack(self):
        self.assertEqual(ds.choose_relief(0.8, freshness=0.2), "改口")

    def test_mid_with_justification_is_rationalisation(self):
        self.assertEqual(ds.choose_relief(0.4, justification=0.5), "合理化")

    def test_mid_fresh_is_rationalisation(self):
        self.assertEqual(ds.choose_relief(0.4, freshness=0.8), "合理化")

    def test_all_reliefs_are_known(self):
        for value in (0.0, 0.3, 0.5, 0.7, 1.0):
            self.assertIn(ds.choose_relief(value), ds.RELIEFS)

class BoundsTest(unittest.TestCase):
    def test_never_exceeds_one(self):
        out = ds.strength([{"text": "a", "weight": 1.0}],
                          {"kind": "x", "contradicts": ["a"],
                           "salience": 9, "justification": -3})
        self.assertLessEqual(out["dissonance"], 1.0)
        self.assertGreaterEqual(out["dissonance"], 0.0)

class FallbackTest(unittest.TestCase):
    def test_disabled(self):
        out = ds.strength(STANCES, {"kind": "熬夜", "contradicts": ["不熬夜"]},
                          flags={"enabled": False})
        self.assertEqual(out["dissonance"], 0.0)
        self.assertEqual(out["relief"], "沉默")

    def test_malformed(self):
        out = ds.strength("x", 3)
        self.assertEqual(out["dissonance"], 0.0)
        out = ds.strength([None, 5, {"stance": "不熬夜"}], {"kind": "熬夜"})
        self.assertIn(out["dissonance"], (0.0, out["dissonance"]))

class DirectiveTest(unittest.TestCase):
    def test_each_relief_has_hint(self):
        for relief in ds.RELIEFS:
            out = ds.directives({"enabled": True, "relief": relief})
            self.assertEqual(out["relief"], relief)
            self.assertGreaterEqual(out["length_scale"], 0.5)

    def test_disabled_directive(self):
        out = ds.directives({"enabled": False})
        self.assertEqual(out["tone"], "")

if __name__ == "__main__":
    unittest.main()
