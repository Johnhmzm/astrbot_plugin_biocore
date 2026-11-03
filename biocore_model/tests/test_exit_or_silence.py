# -*- coding: utf-8 -*-
"""task-161 沉默/退出单测：四种动作、概率分布、抽样、关闭、输入健壮性。

只依赖 biocore_model.exit_or_silence 的纯函数；不导入 main.py，不新增
LLM 调用。
"""
import unittest

from biocore_model import exit_or_silence as es

CALM = {"closeness": 0.5, "trust": 0.5, "conflict": 0.0}


def decide(**kwargs):
    return es.exit_or_silence(**kwargs)


class ContractTest(unittest.TestCase):
    def test_actions(self):
        self.assertEqual(es.ACTIONS,
                         ("respond", "delay", "silent", "end_topic"))

    def test_result_keys(self):
        out = decide()
        for key in ("enabled", "action", "probability", "distribution",
                    "delay_seconds", "reason", "roll"):
            self.assertIn(key, out)

    def test_distribution_is_probability(self):
        for state in (None, {"energy": 0.1, "stress": 0.9},
                      {"energy": 0.9, "stress": 0.1, "valence": -0.8}):
            out = decide(state=state)
            self.assertAlmostEqual(sum(out["distribution"].values()), 1.0,
                                   places=2)
            for action, value in out["distribution"].items():
                self.assertIn(action, es.ACTIONS)
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)
            self.assertEqual(out["probability"],
                             out["distribution"][out["action"]])

    def test_reason_present(self):
        for state in (None, {"energy": 0.1, "stress": 0.9},
                      {"energy": 0.9, "stress": 0.1}):
            self.assertTrue(decide(state=state)["reason"])


class ActionTest(unittest.TestCase):
    def test_rested_and_comfortable_responds(self):
        out = decide(state={"energy": 0.7, "stress": 0.2, "valence": 0.2},
                     relationship=CALM, topic={"intensity": 0.35})
        self.assertEqual(out["action"], "respond")
        self.assertEqual(out["delay_seconds"], 0)

    def test_exhausted_and_tense_goes_silent(self):
        out = decide(state={"energy": 0.0, "stress": 1.0, "valence": -1.0},
                     relationship=CALM)
        self.assertEqual(out["action"], "silent")
        self.assertEqual(out["delay_seconds"], 0)

    def test_heavy_topic_ends_topic(self):
        out = decide(state={"energy": 0.5, "stress": 0.5, "valence": -0.4},
                     relationship={"closeness": 0.3, "trust": 0.2,
                                   "conflict": 0.5},
                     topic={"intensity": 1.0})
        self.assertEqual(out["action"], "end_topic")

    def test_one_foot_out_the_door_delays(self):
        out = decide(state={"energy": 0.4, "stress": 0.9, "valence": 0.0},
                     relationship={"closeness": 0.6, "trust": 0.6},
                     topic={"intensity": 0.5})
        self.assertEqual(out["action"], "delay")
        self.assertGreaterEqual(out["delay_seconds"], es.DELAY_MIN_S)
        self.assertLessEqual(out["delay_seconds"], es.DELAY_MAX_S)

    def test_conflict_does_not_force_respond(self):
        out = decide(state={"energy": 0.6, "stress": 0.4, "valence": -0.3},
                     relationship={"conflict": 0.8},
                     topic={"intensity": 0.5})
        self.assertIn(out["action"], ("delay", "silent", "end_topic"))
        self.assertLess(out["distribution"]["respond"], 0.30)

    def test_close_relationship_raises_respond_probability(self):
        near = decide(state={"energy": 0.6, "stress": 0.3},
                       relationship={"closeness": 0.95, "trust": 0.9},
                       topic={"intensity": 0.3})
        far = decide(state={"energy": 0.6, "stress": 0.3},
                      relationship={"closeness": 0.1, "trust": 0.1},
                      topic={"intensity": 0.3})
        self.assertGreater(near["distribution"]["respond"],
                           far["distribution"]["respond"])


class TopicIntensityTest(unittest.TestCase):
    def test_higher_intensity_raises_end_topic(self):
        low = decide(state={"energy": 0.6, "stress": 0.3},
                     topic={"intensity": 0.2})
        high = decide(state={"energy": 0.6, "stress": 0.3},
                      topic={"intensity": 1.0})
        self.assertGreater(high["distribution"]["end_topic"],
                           low["distribution"]["end_topic"])

    def test_heavy_kind_counts_as_heavy_topic(self):
        plain = decide(topic={"intensity": 0.1})
        heavy = decide(topic={"kind": "conflict", "intensity": 0.1})
        self.assertGreater(heavy["distribution"]["end_topic"],
                           plain["distribution"]["end_topic"])

    def test_numeric_topic_is_accepted(self):
        out = decide(topic=0.9)
        self.assertIn(out["action"], es.ACTIONS)


class SamplingTest(unittest.TestCase):
    def test_roll_zero_is_respond(self):
        out = decide(state={"energy": 0.1, "stress": 0.9}, roll=0.0)
        self.assertEqual(out["action"], "respond")

    def test_high_roll_reaches_last_action(self):
        out = decide(state={"energy": 0.1, "stress": 0.9}, roll=0.9999)
        self.assertEqual(out["action"], "end_topic")

    def test_roll_reports_action_probability(self):
        out = decide(state={"energy": 0.1, "stress": 0.9}, roll=0.9)
        self.assertEqual(out["probability"],
                         out["distribution"][out["action"]])
        self.assertIsNotNone(out["roll"])

    def test_roll_is_clamped(self):
        for roll in (-1.0, 2.0):
            out = decide(roll=roll)
            self.assertIn(out["action"], es.ACTIONS)


class SwitchTest(unittest.TestCase):
    def test_disabled_always_responds(self):
        out = decide(state={"energy": 0.0, "stress": 1.0},
                     flags={"enabled": False})
        self.assertFalse(out["enabled"])
        self.assertEqual(out["action"], "respond")
        self.assertEqual(out["probability"], 1.0)
        self.assertEqual(out["distribution"]["respond"], 1.0)
        self.assertIn("关闭", out["reason"])

    def test_disabled_directives_send(self):
        out = es.directives(decide(state={"energy": 0.0},
                                  flags={"enabled": False}))
        self.assertTrue(out["send"])
        self.assertEqual(out["action"], "respond")


class HelpersTest(unittest.TestCase):
    def test_should_reply_matches_action(self):
        silent = decide(state={"energy": 0.0, "stress": 1.0,
                              "valence": -1.0})
        self.assertEqual(silent["action"], "silent")
        self.assertFalse(es.should_reply(silent))
        self.assertTrue(es.should_reply(decide()))
        self.assertTrue(es.should_reply(None))

    def test_directives_map_actions(self):
        self.assertFalse(es.directives(decide(
            state={"energy": 0.0, "stress": 1.0, "valence": -1.0}))["send"])
        delay = decide(state={"energy": 0.4, "stress": 0.9},
                       relationship={"closeness": 0.6, "trust": 0.6},
                       topic={"intensity": 0.5})
        self.assertEqual(delay["action"], "delay")
        directive = es.directives(delay)
        self.assertTrue(directive["send"])
        self.assertEqual(directive["delay_seconds"], delay["delay_seconds"])
        self.assertGreater(directive["delay_seconds"], 0)

    def test_directives_bounded(self):
        for state in (None, {"energy": 0.1, "stress": 0.9},
                      {"energy": 0.9, "valence": -0.9}):
            out = es.directives(decide(state=state))
            self.assertGreaterEqual(out["length_scale"], 0.0)
            self.assertLessEqual(out["length_scale"], 1.0)
            self.assertIn("tone", out)

    def test_delay_seconds_only_for_delay(self):
        out = decide(state={"energy": 0.0, "stress": 1.0,
                     "valence": -1.0})
        self.assertEqual(out["action"], "silent")
        self.assertEqual(out["delay_seconds"], 0)
        self.assertEqual(decide()["delay_seconds"], 0)


class RobustnessTest(unittest.TestCase):
    def test_none_and_odd_inputs(self):
        for state in (None, {}, "x", 3, []):
            out = decide(state=state)
            self.assertIn(out["action"], es.ACTIONS)
        self.assertEqual(decide()["action"], "respond")

    def test_nan_values_are_safe(self):
        out = decide(state={"energy": float("nan"),
                            "stress": None, "valence": "x"})
        self.assertIn(out["action"], es.ACTIONS)
        self.assertTrue(out["reason"])

    def test_relationship_defaults_from_state(self):
        out = decide(state={"closeness": 0.1, "trust": 0.1},
                     relationship={})
        self.assertEqual(out["action"], "respond")


if __name__ == "__main__":
    unittest.main()
