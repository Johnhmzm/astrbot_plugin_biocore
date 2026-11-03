# -*- coding: utf-8 -*-
"""Attribution: four reaction types, bounds, fallbacks."""
import unittest

from biocore_model import attributor as ab

class LocusTest(unittest.TestCase):
    def test_blame_points_at_you(self):
        out = ab.attribute({"blame": 0.9, "goal": -0.5, "hit": 0.6,
                           "involve": 0.8}, {"who": "you"})
        self.assertEqual(out["locus"], "you")
        self.assertEqual(out["emotion"], "anger")

    def test_self_blame_points_at_me(self):
        out = ab.attribute({"blame": 0.5, "goal": -0.6, "hit": 0.8,
                           "involve": 0.9}, {"who": "me"})
        self.assertEqual(out["locus"], "me")
        self.assertEqual(out["emotion"], "guilt")

    def test_low_involvement_points_at_situation(self):
        out = ab.attribute({"blame": 0.05, "goal": -0.2, "hit": 0.2,
                           "involve": 0.05}, {"who": "situation"})
        self.assertEqual(out["locus"], "situation")

class EmotionTest(unittest.TestCase):
    def test_sympathy_when_other_is_hurt(self):
        out = ab.attribute({"blame": 0.05, "goal": -0.7, "hit": 0.9,
                           "involve": 0.2}, {"who": "situation"},
                          {"closeness": 0.8})
        self.assertIn(out["emotion"], ("sympathy", "helplessness"))

    def test_uncontrollable_self_is_helplessness(self):
        out = ab.attribute({"blame": 0.0, "goal": -0.5, "hit": 0.3,
                           "involve": 0.1}, {"who": "me"})
        self.assertIn(out["emotion"], ("helplessness", "guilt"))

class BoundsTest(unittest.TestCase):
    def test_scores_in_range(self):
        out = ab.attribute({"blame": 5, "goal": -9, "hit": 3,
                           "involve": -2})
        for value in out["scores"].values():
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)
        self.assertIn(out["locus"], ab.LOCI)
        self.assertIn(out["emotion"], ab.EMOTIONS)
        self.assertGreaterEqual(out["stability"], 0.0)
        self.assertLessEqual(out["stability"], 1.0)

    def test_confidence_not_negative(self):
        out = ab.attribute({})
        self.assertGreaterEqual(out["confidence"], 0.0)

class StabilityTest(unittest.TestCase):
    def test_conflict_raises_stability(self):
        low = ab.attribute({"blame": 0.4}, {}, {"conflict": 0.0})
        high = ab.attribute({"blame": 0.4}, {}, {"conflict": 0.9})
        self.assertGreater(high["stability"], low["stability"])

class ControllabilityTest(unittest.TestCase):
    def test_situation_is_less_controllable(self):
        a = ab.attribute({"blame": 0.6, "involve": 0.6}, {"who": "situation"})
        b = ab.attribute({"blame": 0.6, "involve": 0.6}, {"who": "you"})
        self.assertLess(a["controllability"], b["controllability"])

class FallbackTest(unittest.TestCase):
    def test_disabled_is_neutral(self):
        out = ab.attribute({"blame": 0.9}, {"who": "you"},
                           flags={"enabled": False})
        self.assertFalse(out["enabled"])
        self.assertEqual(out["emotion"], "neutral")
        self.assertEqual(out["locus"], "situation")

    def test_missing_fields_safe(self):
        out = ab.attribute(None, None, None)
        self.assertTrue(out["attribution_reason"])
        self.assertTrue(out["reaction"])

    def test_malformed_dims(self):
        out = ab.attribute({"blame": "x", "goal": float("nan")})
        self.assertIn(out["locus"], ab.LOCI)

class DirectiveTest(unittest.TestCase):
    def test_each_emotion_maps(self):
        cases = {"anger": "angry", "guilt": "guilty",
                 "helplessness": "helpless", "sympathy": "kind"}
        for emotion in cases:
            out = ab.directives({"enabled": True, "emotion": emotion,
                                 "confidence": 0.5})
            self.assertEqual(out["emotion"], emotion)
            self.assertGreaterEqual(out["length_scale"], 0.5)

    def test_disabled_directive(self):
        out = ab.directives({"enabled": False})
        self.assertEqual(out["tone"], "")

class ThreeReactionsTest(unittest.TestCase):
    def test_same_event_three_loci(self):
        event = {"text": "他失约了"}
        a = ab.attribute({"blame": 0.9, "goal": -0.6, "hit": 0.5,
                         "involve": 0.8}, dict(event, who="you"))
        b = ab.attribute({"blame": 0.5, "goal": -0.6, "hit": 0.8,
                         "involve": 0.9}, dict(event, who="me"))
        c = ab.attribute({"blame": 0.1, "goal": -0.6, "hit": 0.5,
                         "involve": 0.1}, dict(event, who="situation"))
        self.assertEqual(len({a["emotion"], b["emotion"], c["emotion"]}), 3)

if __name__ == "__main__":
    unittest.main()
