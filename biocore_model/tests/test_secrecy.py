# -*- coding: utf-8 -*-
import unittest

from biocore_model import secrecy as sc

NOW = 1_700_000_000


class SecrecyDecisionTest(unittest.TestCase):
    def test_low_sensitivity_deep_relation_safe_setting_tells(self):
        out = sc.decide(0.10, 0.85, 0.90)
        self.assertEqual(out["action"], "tell")

    def test_high_sensitivity_shallow_relation_unsafe_setting_withholds(self):
        out = sc.decide(0.90, 0.15, 0.15)
        self.assertEqual(out["action"], "withhold")

    def test_high_sensitivity_close_relation_reframes(self):
        out = sc.decide(0.80, 0.85, 0.50)
        self.assertEqual(out["action"], "reframe")

    def test_action_always_known(self):
        for sentence in (None, -5, 5, "x"):
            out = sc.decide(sentence, sentence, sentence)
            self.assertIn(out["action"], sc.ACTIONS)

    def test_decision_is_deterministic(self):
        first = sc.decide(0.8, 0.85, 0.5)
        second = sc.decide(0.8, 0.85, 0.5)
        self.assertEqual(first, second)

    def test_safer_setting_raises_tell_score(self):
        unsafe = sc.tell_score(0.5, 0.5, 0.2)
        safe = sc.tell_score(0.5, 0.5, 0.9)
        self.assertGreater(safe, unsafe)

    def test_confidence_is_bounded(self):
        out = sc.decide(0.9, 0.1, 0.1)
        self.assertGreaterEqual(out["confidence"], 0.0)
        self.assertLessEqual(out["confidence"], 1.0)


class SecrecyCostTest(unittest.TestCase):
    def test_telling_has_no_hidden_cost(self):
        self.assertEqual(sc.hidden_cost("tell", 0.9, 0.9), 0.0)
        self.assertEqual(sc.decide(0.1, 0.9, 0.9)["pressure_add"], 0.0)

    def test_withholding_has_a_cost(self):
        self.assertGreater(sc.hidden_cost("withhold", 0.8, 0.5), 0.0)

    def test_reframe_costs_less_than_withholding(self):
        withheld = sc.hidden_cost("withhold", 0.8, 0.5)
        softened = sc.hidden_cost("reframe", 0.8, 0.5)
        self.assertGreater(withheld, softened)
        self.assertGreater(softened, 0.0)


class SecrecyPressureTest(unittest.TestCase):
    def test_pressure_accumulates_across_hidden_turns(self):
        first = sc.update(sc.initial(NOW - 3600), 0.9, 0.15, 0.15, now=NOW)
        second = sc.update(first, 0.9, 0.15, 0.15, now=NOW + 3600)
        self.assertGreater(first["pressure"], 0.0)
        self.assertGreater(second["pressure"], first["pressure"])
        self.assertEqual(second["withholds"], 2)

    def test_same_turn_is_idempotent(self):
        once = sc.update(sc.initial(NOW - 10), 0.9, 0.15, 0.15, now=NOW)
        twice = sc.update(once, 0.9, 0.15, 0.15, now=NOW)
        self.assertEqual(twice["pressure"], once["pressure"])
        self.assertEqual(twice["withholds"], once["withholds"])

    def test_telling_does_not_raise_withhold_count(self):
        state = sc.update(sc.initial(NOW - 10), 0.1, 0.9, 0.9, now=NOW)
        self.assertEqual(state["withholds"], 0)
        self.assertEqual(state["pressure"], 0.0)

    def test_pressure_is_capped_at_one(self):
        state = dict(sc.initial(NOW - 10), pressure=0.99)
        loaded = sc.update(state, 0.9, 0.15, 0.15, now=NOW)
        self.assertLessEqual(loaded["pressure"], 1.0)

    def test_pressure_decays_over_time(self):
        state = dict(sc.initial(NOW), pressure=0.50)
        rested = sc.update(state, 0.1, 0.9, 0.9, now=NOW + 10 * 3600)
        self.assertAlmostEqual(rested["pressure"], 0.30)

    def test_contained_flag(self):
        self.assertTrue(sc.contained(dict(sc.initial(NOW), pressure=0.30)))
        self.assertFalse(sc.contained(dict(sc.initial(NOW), pressure=0.70)))

    def test_view_fields(self):
        state = sc.update(sc.initial(NOW - 10), 0.9, 0.15, 0.15, now=NOW)
        panel = sc.view(state)
        for key in ("pressure", "contained", "withholds", "last_action",
                    "last_pressure_add"):
            self.assertIn(key, panel)

    def test_bad_inputs_do_not_crash(self):
        state = sc.update(None, None, None, None)
        self.assertIn(state["last_action"], sc.ACTIONS)
        self.assertEqual(sc.hidden_cost(None, None, None), 0.0)


if __name__ == "__main__":
    unittest.main()
