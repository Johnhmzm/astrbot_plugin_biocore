# -*- coding: utf-8 -*-
import unittest

from biocore_model import self_verification as sv

NOW = 1_700_000_000


class SelfVerificationUrgeTest(unittest.TestCase):
    def test_accurate_description_has_no_urge(self):
        self.assertEqual(sv.correction_urge(False, 0.9, 0.9, 0.9), 0.0)

    def test_misunderstood_is_higher_than_accurate(self):
        pair = sv.compare(clarity=0.7, relation=0.7, severity=0.7)
        self.assertGreater(pair["misunderstood"], pair["accurate"])
        self.assertGreater(pair["delta"], 0.10)

    def test_higher_clarity_raises_urge(self):
        low = sv.correction_urge(True, clarity=0.1, relation=0.6)
        high = sv.correction_urge(True, clarity=0.9, relation=0.6)
        self.assertGreater(high, low)

    def test_higher_relation_raises_urge(self):
        low = sv.correction_urge(True, clarity=0.6, relation=0.1)
        high = sv.correction_urge(True, clarity=0.6, relation=0.9)
        self.assertGreater(high, low)

    def test_urge_stays_in_unit_interval(self):
        low = sv.correction_urge(True, clarity=-5, relation=-5, severity=-5)
        high = sv.correction_urge(True, clarity=5, relation=5, severity=5)
        self.assertGreaterEqual(low, 0.0)
        self.assertLessEqual(high, 1.0)

    def test_clarity_factor_floor_and_ceiling(self):
        self.assertAlmostEqual(sv.clarity_factor(0.0), sv.CLARITY_FLOOR)
        self.assertAlmostEqual(sv.clarity_factor(1.0), 1.0)

    def test_relation_factor_floor_and_ceiling(self):
        self.assertAlmostEqual(sv.relation_factor(0.0), sv.RELATION_FLOOR)
        self.assertAlmostEqual(sv.relation_factor(1.0), 1.0)


class SelfVerificationMisreadTest(unittest.TestCase):
    def test_identical_self_image_is_zero_gap(self):
        image = {"warmth": 0.8, "honesty": 0.9}
        self.assertEqual(sv.misread_level(image, dict(image)), 0.0)

    def test_different_self_image_opens_gap(self):
        level = sv.misread_level({"warmth": 0.8, "honesty": 0.9},
                                 {"warmth": 0.2, "honesty": 0.9})
        self.assertAlmostEqual(level, 0.3)

    def test_missing_traits_are_not_total_misread(self):
        level = sv.misread_level({"warmth": 0.8, "honesty": 0.9},
                                 {"warmth": 0.2})
        self.assertAlmostEqual(level, 0.6)

    def test_bad_inputs_do_not_crash(self):
        self.assertEqual(sv.misread_level(None, None), 0.0)
        self.assertEqual(sv.misread_level({"warmth": 0.5}, "nope"), 0.0)
        self.assertEqual(sv.correction_urge(None, None, None, None), 0.0)


class SelfVerificationStateTest(unittest.TestCase):
    def test_initial_defaults(self):
        state = sv.initial(NOW)
        self.assertEqual(state["urge"], 0.0)
        self.assertEqual(state["misread_count"], 0)

    def test_observe_counts_misreads(self):
        state = sv.observe(sv.initial(NOW - 10), True,
                           clarity=0.7, relation=0.7, now=NOW)
        self.assertEqual(state["misread_count"], 1)
        self.assertEqual(state["last_event"], "misunderstood")
        self.assertGreater(state["urge"], 0.0)

    def test_observe_accurate_does_not_count(self):
        state = sv.observe(sv.initial(NOW - 10), False,
                           clarity=0.7, relation=0.7, now=NOW)
        self.assertEqual(state["misread_count"], 0)
        self.assertEqual(state["urge"], 0.0)
        self.assertEqual(state["last_event"], "seen_accurately")

    def test_same_turn_is_idempotent(self):
        once = sv.observe(sv.initial(NOW - 10), True, now=NOW)
        twice = sv.observe(once, True, now=NOW)
        self.assertEqual(twice["urge"], once["urge"])
        self.assertEqual(twice["misread_count"], once["misread_count"])

    def test_decay_fades_urge(self):
        state = sv.observe(sv.initial(NOW - 10), True,
                           clarity=0.9, relation=0.9, severity=1.0, now=NOW)
        faded = sv.decay(state, NOW + int(sv.DECAY_HALF_LIFE_HOURS * 3600))
        self.assertLess(faded["urge"], state["urge"])

    def test_intent_threshold_switches(self):
        state = dict(sv.initial(NOW), urge=0.10)
        self.assertFalse(sv.intent(state)["want_correct"])
        self.assertEqual(sv.intent(state)["strength"], "none")
        state = dict(sv.initial(NOW), urge=0.80)
        self.assertTrue(sv.intent(state)["want_correct"])
        self.assertEqual(sv.intent(state)["strength"], "strong")

    def test_view_fields(self):
        state = sv.observe(sv.initial(NOW - 10), True, now=NOW)
        panel = sv.view(state)
        for key in ("urge", "want_correct", "strength", "peak",
                    "misread_count", "last_event"):
            self.assertIn(key, panel)


if __name__ == "__main__":
    unittest.main()
