# -*- coding: utf-8 -*-
import unittest

from biocore_model import self_interest as si

LONELY = {
    "needs": {"belonging": 0.10, "self_esteem": 0.50,
              "control": 0.50, "meaningful_existence": 0.50},
    "energy": 0.70, "closeness": 0.60,
    "values": {"closeness": 0.70}, "self_weight": 0.90,
}
TIRED = {"energy": 0.05, "stress": 0.50, "self_weight": 0.90,
         "values": {"autonomy": 0.80}}
BOUNDARY = {"needs": {"control": 0.10}, "stress": 0.90, "closeness": 0.15,
            "values": {"autonomy": 0.80, "honesty": 0.70},
            "self_weight": 0.90}
WARM = {"closeness": 0.95, "trust": 0.90,
        "needs": {"belonging": 0.80, "self_esteem": 0.80,
                  "control": 0.80, "meaningful_existence": 0.80},
        "values": {"honesty": 0.10, "autonomy": 0.10, "closeness": 0.90},
        "self_weight": 0.10, "other_stress": 0.10, "other_energy": 0.80}
HONEST = {"values": {"honesty": 0.95, "autonomy": 0.85}, "stress": 0.40,
          "closeness": 0.60, "needs": {"self_esteem": 0.30},
          "self_weight": 0.60, "other_stress": 0.30}


class SelfInterestChoiceTest(unittest.TestCase):
    def test_lonely_picks_company(self):
        out = si.assess(LONELY)
        self.assertEqual(out["chosen"], "要你陪")
        row = [r for r in out["options"] if r["action"] == "要你陪"][0]
        self.assertGreater(row["self_gain"], row["other_gain"])

    def test_tired_picks_rest(self):
        out = si.assess(TIRED)
        self.assertEqual(out["chosen"], "自己待着")

    def test_tension_picks_refusal(self):
        out = si.assess(BOUNDARY)
        self.assertEqual(out["chosen"], "拒绝话题")

    def test_warm_low_self_weight_picks_comply(self):
        out = si.assess(WARM)
        self.assertEqual(out["chosen"], "顺着你")
        row = [r for r in out["options"] if r["action"] == "顺着你"][0]
        self.assertGreater(row["other_gain"], row["self_gain"])

    def test_honest_value_picks_truth(self):
        out = si.assess(HONEST)
        self.assertEqual(out["chosen"], "说真话")

    def test_all_five_actions_are_scored(self):
        out = si.assess({})
        self.assertEqual([row["action"] for row in out["options"]],
                         list(si.ACTIONS))

    def test_exactly_one_option_is_chosen(self):
        for context in (LONELY, TIRED, BOUNDARY, WARM, HONEST, {}):
            out = si.assess(context)
            self.assertEqual(sum(1 for row in out["options"]
                                 if row["chosen"]), 1)
            self.assertEqual(out["chosen"],
                             [row["action"] for row in out["options"]
                              if row["chosen"]][0])

    def test_reason_matches_chosen_option(self):
        out = si.assess(TIRED)
        chosen = [row for row in out["options"] if row["chosen"]][0]
        self.assertEqual(out["reason"], chosen["reason"])
        self.assertTrue(out["reason"])


class SelfInterestWeightTest(unittest.TestCase):
    def test_explicit_self_weight_changes_choice(self):
        selfish = si.assess(dict(LONELY, self_weight=0.90))
        generous = si.assess(dict(LONELY, self_weight=0.10))
        self.assertEqual(selfish["chosen"], "要你陪")
        self.assertEqual(generous["chosen"], "顺着你")
        self.assertGreater(selfish["self_weight"], generous["self_weight"])

    def test_computed_weight_rises_with_own_gaps(self):
        drained = si.self_weight({"needs": {"belonging": 0.10},
                                  "closeness": 0.20, "trust": 0.20,
                                  "stress": 0.80})
        full = si.self_weight({
            "needs": {"belonging": 0.90, "self_esteem": 0.90,
                      "control": 0.90, "meaningful_existence": 0.90},
            "closeness": 0.90, "trust": 0.90, "stress": 0.10})
        self.assertGreater(drained, full)

    def test_weight_is_bounded(self):
        for value in (-5, 0, 0.5, 1, 5):
            out = si.assess(dict(LONELY, self_weight=value))
            self.assertGreaterEqual(out["self_weight"], si.SELF_WEIGHT_MIN)
            self.assertLessEqual(out["self_weight"], si.SELF_WEIGHT_MAX)

    def test_config_weight_override(self):
        out = si.assess({}, config={"self_weight": 0.80})
        self.assertAlmostEqual(out["self_weight"], 0.80)


class SelfInterestPayoffTest(unittest.TestCase):
    def test_payoffs_and_cost_are_bounded(self):
        for context in (LONELY, TIRED, BOUNDARY, WARM, HONEST, {}):
            out = si.assess(context)
            for row in out["options"]:
                self.assertGreaterEqual(row["self_gain"], -1.0)
                self.assertLessEqual(row["self_gain"], 1.0)
                self.assertGreaterEqual(row["other_gain"], -1.0)
                self.assertLessEqual(row["other_gain"], 1.0)
                self.assertGreaterEqual(row["cost"], 0.0)
                self.assertLessEqual(row["cost"], 1.0)

    def test_comply_costs_more_affective_labour_than_refusal(self):
        table = si.action_scores(dict(HONEST, values={"honesty": 0.95,
                                                      "autonomy": 0.95}))
        self.assertGreater(table["顺着你"]["cost"], table["拒绝话题"]["cost"])

    def test_belonging_gap_raises_company_gain(self):
        low = si.action_scores({"needs": {"belonging": 0.10}})
        high = si.action_scores({"needs": {"belonging": 0.90}})
        self.assertGreater(low["要你陪"]["self_gain"],
                           high["要你陪"]["self_gain"])

    def test_fatigue_raises_rest_gain(self):
        rested = si.action_scores({"energy": 0.90})
        tired = si.action_scores({"energy": 0.10})
        self.assertGreater(tired["自己待着"]["self_gain"],
                           rested["自己待着"]["self_gain"])

    def test_honesty_value_raises_truth_gain(self):
        low = si.action_scores({"values": {"honesty": 0.10}})
        high = si.action_scores({"values": {"honesty": 0.90}})
        self.assertGreater(high["说真话"]["self_gain"],
                           low["说真话"]["self_gain"])
        self.assertGreater(low["顺着你"]["self_gain"],
                          high["顺着你"]["self_gain"])

    def test_other_stress_lowers_company_gain(self):
        calm = si.action_scores({"other_stress": 0.10})
        stressed = si.action_scores({"other_stress": 0.90})
        self.assertGreater(calm["要你陪"]["other_gain"],
                           stressed["要你陪"]["other_gain"])

    def test_refusal_hurts_the_other_side(self):
        table = si.action_scores({"closeness": 0.80})
        self.assertLess(table["拒绝话题"]["other_gain"], 0.0)


class SelfInterestSwitchAndRobustnessTest(unittest.TestCase):
    def test_disabled_switch(self):
        for config in (False, {"enabled": False}):
            out = si.assess(LONELY, config=config)
            self.assertFalse(out["enabled"])
            self.assertEqual(out["options"], [])
            self.assertEqual(out["chosen"], "")
            self.assertTrue(out["reason"])

    def test_malformed_inputs_do_not_crash(self):
        for context in (None, "bad", [], {"needs": "bad", "values": [],
                                          "energy": "x", "self_weight": "x"}):
            out = si.assess(context)
            self.assertIn("options", out)
            self.assertEqual(len(out["options"]), len(si.ACTIONS))
            self.assertIn(out["chosen"], si.ACTIONS)

    def test_deterministic(self):
        first = si.assess(HONEST)
        second = si.assess(dict(HONEST))
        self.assertEqual(first, second)

    def test_view_fields(self):
        panel = si.view(si.assess(TIRED))
        for key in ("enabled", "self_weight", "options", "chosen", "reason"):
            self.assertIn(key, panel)
        self.assertEqual(len(panel["options"]), len(si.ACTIONS))
        for row in panel["options"]:
            for key in ("action", "self_gain", "other_gain", "cost", "chosen"):
                self.assertIn(key, row)


if __name__ == "__main__":
    unittest.main()
