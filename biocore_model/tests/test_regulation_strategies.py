# -*- coding: utf-8 -*-
"""task-175 调节策略库单测：Gross 五策略命中、成本/效果、关系调制、关闭。

只依赖 biocore_model.regulation_strategies 的纯函数；不导入 main.py。
"""
import unittest

from biocore_model import regulation_strategies as rs

CALM = {"closeness": 0.5, "trust": 0.5, "conflict": 0.0}

SELECT_STATE = {"stress": 0.2, "energy": 0.7}
SELECT_EVENT = {"when": "before", "controllable": 0.9, "intensity": 0.4}

MODIFY_STATE = {"stress": 0.3, "energy": 0.6}
MODIFY_EVENT = {"when": "after", "controllable": 0.8, "intensity": 0.5}
MODIFY_REL = {"closeness": 0.7, "trust": 0.6}

ATTENTION_STATE = {"stress": 0.8, "energy": 0.2, "valence": -0.3}
ATTENTION_EVENT = {"when": "after", "controllable": 0.1, "intensity": 0.9}

REAPPRAISE_STATE = {"stress": 0.2, "energy": 0.8, "valence": 0.4}
REAPPRAISE_EVENT = {"when": "after", "controllable": 0.7, "intensity": 0.4}
REAPPRAISE_REL = {"closeness": 0.9, "trust": 0.9}

MODULATE_STATE = {"stress": 0.7, "energy": 0.4}
MODULATE_EVENT = {"when": "after", "controllable": 0.5, "intensity": 0.6,
                  "public": True}
MODULATE_REL = {"closeness": 0.2, "trust": 0.2, "conflict": 0.8}


class ContractTest(unittest.TestCase):
    def test_result_keys(self):
        out = rs.evaluate(SELECT_STATE, SELECT_EVENT, CALM)
        for key in ("enabled", "strategy", "label", "cost", "effect", "reason",
                    "self_talk", "coping_tier", "confidence", "fit", "scores",
                    "profiles"):
            self.assertIn(key, out)

    def test_five_strategies_and_labels(self):
        self.assertEqual(len(rs.STRATEGIES), 5)
        self.assertEqual(set(rs.LABELS), set(rs.STRATEGIES))
        self.assertEqual(rs.LABELS["situation_selection"], "情境选择")
        self.assertEqual(rs.LABELS["situation_modification"], "情境修正")
        self.assertEqual(rs.LABELS["attentional_deployment"], "注意部署")
        self.assertEqual(rs.LABELS["cognitive_reappraisal"], "认知重评")
        self.assertEqual(rs.LABELS["response_modulation"], "反应调节")

    def test_old_coping_tiers_coexist(self):
        self.assertEqual(rs.COPING_TIERS,
                         ("problem_focused", "emotion_focused", "avoidance"))
        self.assertEqual(set(rs.TIER_OF), set(rs.STRATEGIES))
        for tier in rs.TIER_OF.values():
            self.assertIn(tier, rs.COPING_TIERS)

    def test_values_bounded(self):
        for args in (
            (SELECT_STATE, SELECT_EVENT, CALM),
            (ATTENTION_STATE, ATTENTION_EVENT, CALM),
            (MODULATE_STATE, MODULATE_EVENT, MODULATE_REL),
        ):
            out = rs.evaluate(*args)
            for key in ("cost", "effect", "fit", "confidence"):
                self.assertGreaterEqual(out[key], 0.0)
                self.assertLessEqual(out[key], 1.0)
            self.assertEqual(set(out["scores"]), set(rs.STRATEGIES))

    def test_deterministic(self):
        first = rs.evaluate(MODULATE_STATE, MODULATE_EVENT, MODULATE_REL)
        second = rs.evaluate(MODULATE_STATE, MODULATE_EVENT, MODULATE_REL)
        self.assertEqual(first, second)


class FiveStrategiesTest(unittest.TestCase):
    def test_situation_selection(self):
        out = rs.evaluate(SELECT_STATE, SELECT_EVENT, CALM)
        self.assertEqual(out["strategy"], "situation_selection")
        self.assertEqual(out["coping_tier"], "problem_focused")

    def test_situation_modification(self):
        out = rs.evaluate(MODIFY_STATE, MODIFY_EVENT, MODIFY_REL)
        self.assertEqual(out["strategy"], "situation_modification")
        self.assertEqual(out["coping_tier"], "problem_focused")

    def test_attentional_deployment(self):
        out = rs.evaluate(ATTENTION_STATE, ATTENTION_EVENT, CALM)
        self.assertEqual(out["strategy"], "attentional_deployment")
        self.assertEqual(out["coping_tier"], "avoidance")

    def test_cognitive_reappraisal(self):
        out = rs.evaluate(REAPPRAISE_STATE, REAPPRAISE_EVENT, REAPPRAISE_REL)
        self.assertEqual(out["strategy"], "cognitive_reappraisal")
        self.assertEqual(out["coping_tier"], "emotion_focused")

    def test_response_modulation(self):
        out = rs.evaluate(MODULATE_STATE, MODULATE_EVENT, MODULATE_REL)
        self.assertEqual(out["strategy"], "response_modulation")
        self.assertEqual(out["coping_tier"], "emotion_focused")
        self.assertGreater(out["cost"], 0.6)


class CostEffectTest(unittest.TestCase):
    def test_suppression_costs_more_than_selection(self):
        selection = rs.profile("situation_selection", SELECT_STATE,
                               SELECT_EVENT, CALM)
        modulation = rs.profile("response_modulation", MODULATE_STATE,
                                MODULATE_EVENT, MODULATE_REL)
        self.assertGreater(modulation["cost"], selection["cost"])

    def test_suppression_costs_more_than_reappraisal(self):
        reappraisal = rs.profile("cognitive_reappraisal", MODULATE_STATE,
                                 MODULATE_EVENT, MODULATE_REL)
        modulation = rs.profile("response_modulation", MODULATE_STATE,
                                MODULATE_EVENT, MODULATE_REL)
        self.assertGreater(modulation["cost"], reappraisal["cost"])

    def test_reappraisal_costs_more_than_distraction(self):
        state = {"energy": 0.5, "stress": 0.5}
        event = {"intensity": 0.5}
        reappraisal = rs.profile("cognitive_reappraisal", state, event, CALM)
        attention = rs.profile("attentional_deployment", state, event, CALM)
        self.assertGreater(reappraisal["cost"], attention["cost"])

    def test_effect_rises_with_control(self):
        low = rs.profile("situation_selection", {}, {"controllable": 0.1})
        high = rs.profile("situation_selection", {}, {"controllable": 0.9})
        self.assertGreater(high["effect"], low["effect"])

    def test_profiles_cover_all_strategies(self):
        rows = rs.profiles(SELECT_STATE, SELECT_EVENT, CALM)
        self.assertEqual({row["strategy"] for row in rows},
                         set(rs.STRATEGIES))
        for first, second in zip(rows, rows[1:]):
            self.assertGreaterEqual(first["score"], second["score"])
        for row in rows:
            for key in ("cost", "effect", "fit", "score"):
                self.assertGreaterEqual(row[key], 0.0)
                self.assertLessEqual(row[key], 1.0)


class RelationshipTest(unittest.TestCase):
    def test_trust_raises_reappraisal_fit(self):
        near = rs.profile("cognitive_reappraisal", REAPPRAISE_STATE,
                          REAPPRAISE_EVENT, {"closeness": 0.9, "trust": 0.9})
        far = rs.profile("cognitive_reappraisal", REAPPRAISE_STATE,
                         REAPPRAISE_EVENT, {"closeness": 0.1, "trust": 0.1})
        self.assertGreater(near["fit"], far["fit"])

    def test_close_relationship_prefers_reappraisal(self):
        near = rs.evaluate(REAPPRAISE_STATE, REAPPRAISE_EVENT,
                           {"closeness": 0.9, "trust": 0.9})
        far = rs.evaluate(REAPPRAISE_STATE, REAPPRAISE_EVENT,
                          {"closeness": 0.1, "trust": 0.1})
        self.assertEqual(near["strategy"], "cognitive_reappraisal")
        self.assertNotEqual(far["strategy"], near["strategy"])

    def test_public_conflict_prefers_suppression(self):
        out = rs.evaluate(MODULATE_STATE, MODULATE_EVENT, MODULATE_REL)
        self.assertEqual(out["strategy"], "response_modulation")
        reappraisal_fit = out["scores"]["cognitive_reappraisal"]
        self.assertLess(reappraisal_fit, out["scores"]["response_modulation"])


class SwitchTest(unittest.TestCase):
    def test_disabled_returns_old_coping(self):
        out = rs.evaluate(SELECT_STATE, SELECT_EVENT, CALM,
                          flags={"enabled": False})
        self.assertFalse(out["enabled"])
        self.assertEqual(out["strategy"], "none")
        self.assertEqual(out["cost"], 0.0)
        self.assertEqual(out["effect"], 0.0)
        self.assertIsNone(out["scores"].get("situation_selection"))
        self.assertIn("关闭", out["reason"])

    def test_directives_disabled_is_neutral(self):
        out = rs.directives(rs.evaluate(flags={"enabled": False}))
        self.assertEqual(out["strategy"], "none")
        self.assertEqual(out["tone"], "")
        self.assertEqual(out["coping_tier"], "")


class SelfTalkTest(unittest.TestCase):
    def test_self_talk_exists_for_every_strategy(self):
        for strategy in rs.STRATEGIES:
            row = rs.profile(strategy)
            self.assertTrue(row["self_talk"])
            self.assertLessEqual(len(row["self_talk"]), 40)
            self.assertTrue(row["reason"])

    def test_directives_carry_strategy_and_tone(self):
        out = rs.directives(rs.evaluate(SELECT_STATE, SELECT_EVENT, CALM))
        self.assertEqual(out["strategy"], "situation_selection")
        self.assertIn(out["coping_tier"], rs.COPING_TIERS)
        self.assertTrue(out["tone"])
        self.assertGreaterEqual(out["cost"], 0.0)
        self.assertLessEqual(out["effect"], 1.0)


class RobustnessTest(unittest.TestCase):
    def test_odd_inputs_still_choose(self):
        for state in (None, {}, "x", 3, [], {"stress": float("nan")}):
            out = rs.evaluate(state=state)
            self.assertIn(out["strategy"], rs.STRATEGIES)
            self.assertTrue(out["reason"])
        for event in (None, "x", 3, [], {"controllable": "?"}):
            self.assertIn(rs.evaluate(SELECT_STATE, event)["strategy"],
                          rs.STRATEGIES)
        for relationship in (None, "x", 3, []):
            self.assertIn(rs.evaluate(relationship=relationship)["strategy"],
                          rs.STRATEGIES)

    def test_unknown_profile_is_neutral(self):
        out = rs.profile("nope")
        self.assertEqual(out["strategy"], "none")
        self.assertEqual(out["cost"], 0.0)
        self.assertEqual(out["score"], 0.0)

    def test_confidence_within_bounds(self):
        for args in ((SELECT_STATE, SELECT_EVENT, CALM),
                     (ATTENTION_STATE, ATTENTION_EVENT, CALM),
                     ({}, {}, {})):
            out = rs.evaluate(*args)
            self.assertGreaterEqual(out["confidence"], 0.0)
            self.assertLessEqual(out["confidence"], 1.0)


if __name__ == "__main__":
    unittest.main()
