# -*- coding: utf-8 -*-
"""task-181 话题主导权单测：让出/接住/另起/收尾、主导度、关闭、畸形输入。

只依赖 biocore_model.topic_control 的纯函数；不导入 main.py。
"""
import unittest

from biocore_model import topic_control as tc

CATCH_TURNS = [{"by": "you", "kind": "initiate"},
               {"by": "me", "kind": "keep"}]
YIELD_TURNS = [{"by": "me", "kind": "initiate"},
               {"by": "me", "kind": "switch"},
               {"by": "me", "kind": "keep"}]
STALE_TURNS = [{"by": "you", "kind": "keep"},
               {"by": "me", "kind": "keep"},
               {"by": "you", "kind": "keep"},
               {"by": "me", "kind": "keep"}]
CLOSE_TURNS = [{"by": "you", "kind": "initiate"},
               {"by": "you", "kind": "close"}]


class ContractTest(unittest.TestCase):
    def test_result_keys(self):
        out = tc.topic_control(CATCH_TURNS)
        for key in ("enabled", "holder", "dominance", "tendency", "reason",
                    "counts", "window", "last_by", "scores"):
            self.assertIn(key, out)

    def test_constants(self):
        self.assertEqual(tc.HOLDERS, ("me", "you", "shared"))
        self.assertEqual(tc.TENDENCIES, ("让出", "接住", "另起", "收尾"))
        self.assertEqual(tc.KINDS, ("initiate", "switch", "close", "keep"))
        self.assertEqual(set(tc.REASONS), set(tc.TENDENCIES))

    def test_values_bounded(self):
        for turns in (CATCH_TURNS, YIELD_TURNS, STALE_TURNS, CLOSE_TURNS, []):
            out = tc.topic_control(turns)
            self.assertGreaterEqual(out["dominance"], 0.0)
            self.assertLessEqual(out["dominance"], 1.0)
            self.assertIn(out["holder"], tc.HOLDERS)
            self.assertIn(out["tendency"], tc.TENDENCIES)
            for value in out["scores"].values():
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)


class TendencyTest(unittest.TestCase):
    def test_catch_your_topic(self):
        out = tc.topic_control(CATCH_TURNS, state={"energy": 0.6},
                               relationship={"closeness": 0.6})
        self.assertEqual(out["tendency"], "接住")
        self.assertEqual(out["holder"], "you")

    def test_yield_when_she_has_been_steering(self):
        out = tc.topic_control(YIELD_TURNS, state={"energy": 0.3},
                               relationship={"closeness": 0.7})
        self.assertEqual(out["tendency"], "让出")
        self.assertEqual(out["holder"], "me")

    def test_start_when_topic_is_stale(self):
        out = tc.topic_control(STALE_TURNS, state={"energy": 0.8},
                               relationship={"closeness": 0.3})
        self.assertEqual(out["tendency"], "另起")
        self.assertTrue(tc.metrics(STALE_TURNS)["stale"])

    def test_close_when_topic_is_wrapping_up(self):
        out = tc.topic_control(CLOSE_TURNS, state={"energy": 0.3},
                               relationship={"conflict": 0.2}, hour=23)
        self.assertEqual(out["tendency"], "收尾")
        self.assertTrue(tc.metrics(CLOSE_TURNS)["closing"])

    def test_closing_flag_forces_close(self):
        out = tc.topic_control([{"by": "you", "kind": "keep"}],
                               state={"energy": 0.2},
                               flags={"closing": True})
        self.assertEqual(out["tendency"], "收尾")

    def test_empty_history_defaults_to_catch(self):
        out = tc.topic_control([])
        self.assertEqual(out["tendency"], "接住")
        self.assertEqual(out["holder"], "shared")
        self.assertEqual(out["dominance"], 0.5)


class HolderTest(unittest.TestCase):
    def test_holder_me(self):
        out = tc.topic_control([{"by": "me", "kind": "initiate"}])
        self.assertEqual(out["holder"], "me")
        self.assertEqual(out["dominance"], 1.0)

    def test_holder_you(self):
        out = tc.topic_control([{"by": "you", "kind": "switch"}])
        self.assertEqual(out["holder"], "you")
        self.assertEqual(out["dominance"], 0.0)

    def test_holder_shared(self):
        out = tc.topic_control([{"by": "me", "kind": "initiate"},
                                {"by": "you", "kind": "initiate"}])
        self.assertEqual(out["holder"], "shared")

    def test_recency_weights(self):
        turns = [{"by": "you", "kind": "initiate"},
                 {"by": "me", "kind": "switch"}]
        row = tc.metrics(turns)
        self.assertGreater(row["dominance"], 0.5)
        self.assertLess(row["dominance"], 1.0)
        self.assertGreater(row["my_control"], 0.0)
        self.assertGreater(row["your_control"], 0.0)

    def test_window_limits_history(self):
        turns = [{"by": "me", "kind": "initiate"},
                 {"by": "me", "kind": "initiate"},
                 {"by": "me", "kind": "initiate"},
                 {"by": "you", "kind": "initiate"}]
        wide = tc.metrics(turns, window=4)
        narrow = tc.metrics(turns, window=2)
        self.assertEqual(narrow["count"], 2)
        self.assertEqual(narrow["holder"], "shared")
        self.assertEqual(wide["holder"], "me")

    def test_counts_consistent(self):
        out = tc.topic_control(YIELD_TURNS)
        counts = out["counts"]
        self.assertGreaterEqual(counts["my_control"], 0.0)
        self.assertGreaterEqual(counts["your_control"], 0.0)
        self.assertGreaterEqual(counts["engaged"], 0.0)
        self.assertLessEqual(counts["engaged"], 1.0)


class EnergyTest(unittest.TestCase):
    def test_energy_raises_start_score(self):
        low = tc.topic_control(STALE_TURNS, state={"energy": 0.0})
        high = tc.topic_control(STALE_TURNS, state={"energy": 1.0})
        self.assertGreater(high["scores"]["另起"], low["scores"]["另起"])

    def test_low_energy_raises_close_score(self):
        low = tc.topic_control(CLOSE_TURNS, state={"energy": 0.1})
        high = tc.topic_control(CLOSE_TURNS, state={"energy": 0.9})
        self.assertGreater(low["scores"]["收尾"], high["scores"]["收尾"])

    def test_low_energy_with_closing_stops_keeping_topic(self):
        out = tc.topic_control(YIELD_TURNS, state={"energy": 0.1},
                               flags={"closing": True})
        self.assertIn(out["tendency"], ("让出", "收尾"))


class SwitchTest(unittest.TestCase):
    def test_disabled_is_neutral(self):
        out = tc.topic_control(CATCH_TURNS, flags={"enabled": False})
        self.assertFalse(out["enabled"])
        self.assertEqual(out["holder"], "shared")
        self.assertEqual(out["dominance"], 0.5)
        self.assertEqual(out["tendency"], "接住")
        self.assertIn("关闭", out["reason"])

    def test_directives_mapping(self):
        out = tc.directives(tc.topic_control(YIELD_TURNS))
        self.assertEqual(out["tendency"], "让出")
        self.assertEqual(out["holder"], "me")
        self.assertLessEqual(out["initiative"], 0.2)
        self.assertTrue(out["tone"])
        neutral = tc.directives(tc.topic_control(flags={"enabled": False}))
        self.assertEqual(neutral["tendency"], "接住")
        self.assertEqual(neutral["tone"], "")


class RobustnessTest(unittest.TestCase):
    def test_odd_inputs(self):
        for turns in (None, "x", 3, [], [{"by": "what", "kind": "??"}],
                      ["bad"], "me:initiate", {"turns": CATCH_TURNS}):
            out = tc.topic_control(turns)
            self.assertIn(out["tendency"], tc.TENDENCIES)
            self.assertIn(out["holder"], tc.HOLDERS)
            self.assertTrue(out["reason"])

    def test_string_turns_are_parsed(self):
        row = tc.metrics(["me:initiate", "me:switch"])
        self.assertEqual(row["holder"], "me")
        self.assertEqual(row["dominance"], 1.0)

    def test_aliases(self):
        row = tc.metrics([{"by": "her", "kind": "new"},
                          {"by": "user", "kind": "change"}])
        self.assertGreater(row["my_control"], 0.0)
        self.assertGreater(row["your_control"], 0.0)

    def test_deterministic(self):
        first = tc.topic_control(YIELD_TURNS, state={"energy": 0.3})
        second = tc.topic_control(YIELD_TURNS, state={"energy": 0.3})
        self.assertEqual(first, second)

    def test_bad_hour_and_state(self):
        out = tc.topic_control(CATCH_TURNS, state="x", relationship="y",
                               hour="zzz")
        self.assertIn(out["tendency"], tc.TENDENCIES)


if __name__ == "__main__":
    unittest.main()
