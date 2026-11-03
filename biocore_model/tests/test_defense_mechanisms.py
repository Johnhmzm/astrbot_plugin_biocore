# -*- coding: utf-8 -*-
import unittest

from biocore_model import defense_mechanisms as dm


class DefenseMechanismSelectionTest(unittest.TestCase):
    def test_denial_on_near_threat(self):
        out = dm.assess(
            {"kind": "failure", "valence": -0.9, "intensity": 0.9},
            state={"v": -0.7, "a": 0.7, "d": 0.2, "stress": 0.85},
            self_concept={"clarity": 0.15},
        )
        self.assertEqual(out["mechanism"], "denial")
        self.assertEqual(out["label"], "否认")
        self.assertGreaterEqual(out["strength"], 0.6)

    def test_rationalization_on_self_caused_failure(self):
        out = dm.assess(
            {"kind": "failure", "valence": -0.6, "intensity": 0.7,
             "self_caused": True},
            state={"v": -0.4, "a": 0.4, "d": 0.6, "stress": 0.3},
            self_concept={"clarity": 0.6, "competence": 0.85,
                          "honesty": 0.8},
        )
        self.assertEqual(out["mechanism"], "rationalization")
        self.assertGreater(out["strength"], 0.5)

    def test_projection_when_own_anger_lands_on_other(self):
        out = dm.assess(
            {"kind": "conflict", "valence": -0.5, "intensity": 0.7,
             "target": "peer"},
            state={"anger": 0.85, "fear": 0.2, "trust": 0.15,
                   "d": 0.5, "stress": 0.5},
            self_concept={"clarity": 0.5},
        )
        self.assertEqual(out["mechanism"], "projection")
        self.assertEqual(out["label"], "投射")

    def test_displacement_when_source_is_untouchable(self):
        out = dm.assess(
            {"kind": "criticism", "valence": -0.6, "intensity": 0.8,
             "target": "authority", "power_gap": 1.0},
            state={"anger": 0.8, "d": 0.1, "trust": 0.5, "stress": 0.5},
            self_concept={"clarity": 0.5},
        )
        self.assertEqual(out["mechanism"], "displacement")
        self.assertEqual(out["label"], "转移")

    def test_strongest_mechanism_wins(self):
        scores = dm.mechanism_scores(
            {"kind": "criticism", "valence": -0.6, "intensity": 0.8,
             "target": "authority", "power_gap": 1.0},
            state={"anger": 0.8, "d": 0.1, "trust": 0.5, "stress": 0.5},
            self_concept={"clarity": 0.5},
        )
        self.assertGreater(scores["displacement"], scores["projection"])
        out = dm.assess(
            {"kind": "criticism", "valence": -0.6, "intensity": 0.8,
             "target": "authority", "power_gap": 1.0},
            state={"anger": 0.8, "d": 0.1, "trust": 0.5, "stress": 0.5},
            self_concept={"clarity": 0.5},
        )
        self.assertEqual(out["mechanism"], "displacement")


class DefenseMechanismOutputTest(unittest.TestCase):
    CASES = (
        ({"kind": "failure", "valence": -0.9, "intensity": 0.9},
         {"v": -0.7, "a": 0.7, "d": 0.2, "stress": 0.85},
         {"clarity": 0.15}),
        ({"kind": "failure", "valence": -0.6, "intensity": 0.7,
          "self_caused": True}, {"stress": 0.3},
         {"clarity": 0.6, "competence": 0.85}),
        ({"kind": "conflict", "valence": -0.5, "intensity": 0.7,
          "target": "peer"},
         {"anger": 0.85, "trust": 0.15}, {"clarity": 0.5}),
        ({"kind": "criticism", "valence": -0.6, "intensity": 0.8,
          "target": "authority", "power_gap": 1.0},
         {"anger": 0.8, "d": 0.1}, {"clarity": 0.5}),
    )

    def test_strength_and_cost_are_bounded(self):
        for event, state, concept in self.CASES:
            out = dm.assess(event, state=state, self_concept=concept)
            self.assertGreaterEqual(out["strength"], 0.0)
            self.assertLessEqual(out["strength"], 1.0)
            self.assertGreaterEqual(out["cost"], 0.0)
            self.assertLessEqual(out["cost"], 1.0)

    def test_cost_scales_with_strength(self):
        for event, state, concept in self.CASES:
            out = dm.assess(event, state=state, self_concept=concept)
            base = dm.COST_BASE[out["mechanism"]]
            self.assertEqual(out["cost"], round(base * out["strength"], 4))

    def test_reason_and_self_talk_present_for_each(self):
        for event, state, concept in self.CASES:
            out = dm.assess(event, state=state, self_concept=concept)
            self.assertTrue(out["mechanism"])
            self.assertTrue(out["reason"])
            self.assertTrue(out["self_talk"])

    def test_mechanism_scores_cover_all_four(self):
        scores = dm.mechanism_scores({}, None, None)
        self.assertEqual(set(scores), set(dm.MECHANISMS))
        for value in scores.values():
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_deterministic(self):
        first = dm.assess(
            {"kind": "conflict", "valence": -0.5, "intensity": 0.7},
            state={"anger": 0.85, "trust": 0.15}, self_concept={"clarity": 0.5})
        second = dm.assess(
            {"kind": "conflict", "valence": -0.5, "intensity": 0.7},
            state={"anger": 0.85, "trust": 0.15}, self_concept={"clarity": 0.5})
        self.assertEqual(first, second)


class DefenseMechanismSwitchTest(unittest.TestCase):
    DENIAL_EVENT = {"kind": "failure", "valence": -0.9, "intensity": 0.9}
    DENIAL_STATE = {"v": -0.7, "a": 0.7, "d": 0.2, "stress": 0.85}
    DENIAL_CONCEPT = {"clarity": 0.15}

    def test_disabled_bool(self):
        out = dm.assess(self.DENIAL_EVENT, state=self.DENIAL_STATE,
                        self_concept=self.DENIAL_CONCEPT, config=False)
        self.assertFalse(out["enabled"])
        self.assertEqual(out["mechanism"], "")
        self.assertEqual(out["strength"], 0.0)
        self.assertEqual(out["cost"], 0.0)
        self.assertEqual(out["self_talk"], "")
        self.assertTrue(out["reason"])

    def test_disabled_config_dict(self):
        out = dm.assess(self.DENIAL_EVENT, state=self.DENIAL_STATE,
                        self_concept=self.DENIAL_CONCEPT,
                        config={"enabled": False})
        self.assertFalse(out["enabled"])
        self.assertEqual(out["mechanism"], "")

    def test_no_defense_when_nothing_negative(self):
        out = dm.assess({"kind": "praise", "valence": 0.8, "intensity": 0.9},
                        state={"v": 0.6, "a": 0.5}, self_concept={"clarity": 0.6})
        self.assertEqual(out["mechanism"], "")
        self.assertEqual(out["strength"], 0.0)
        self.assertEqual(out["self_talk"], "")
        self.assertTrue(out["reason"])

    def test_threshold_can_be_raised(self):
        out = dm.assess(self.DENIAL_EVENT, state=self.DENIAL_STATE,
                        self_concept=self.DENIAL_CONCEPT,
                        config={"threshold": 0.95})
        self.assertEqual(out["mechanism"], "")

    def test_malformed_inputs_do_not_crash(self):
        for event, state, concept in ((None, None, None),
                                      ("bad", "bad", "bad"),
                                      ({"valence": "x"}, {"stress": "x"}, [])):
            out = dm.assess(event, state=state, self_concept=concept)
            self.assertIn("mechanism", out)
            self.assertIn("scores", out)
            self.assertGreaterEqual(out["strength"], 0.0)
            self.assertLessEqual(out["strength"], 1.0)

    def test_view_fields(self):
        out = dm.assess(self.DENIAL_EVENT, state=self.DENIAL_STATE,
                        self_concept=self.DENIAL_CONCEPT)
        panel = dm.view(out)
        for key in ("enabled", "mechanism", "label", "strength", "cost",
                    "reason", "self_talk"):
            self.assertIn(key, panel)


if __name__ == "__main__":
    unittest.main()
