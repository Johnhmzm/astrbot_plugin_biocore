# -*- coding: utf-8 -*-
"""task-219: repeated topics slowly drift value_order (preference drift)."""
import unittest

from biocore_memory.core import config as engine_config
from biocore_model import preference_drift as pd
from biocore_model import value_order as vo


def memory(text):
    return {"id": "m", "text": text, "role": "user", "ts": 1700000000.0}


class SwitchTest(unittest.TestCase):
    def test_flag_defaults_off(self):
        self.assertIs(engine_config.FLAGS.get("preference_drift"), False)

    def test_enabled_reads_flag_and_env(self):
        self.assertFalse(pd.enabled({}))
        self.assertTrue(pd.enabled({"preference_drift": True}))
        self.assertTrue(pd.enabled({}, {"BIOCORE_PREFERENCE_DRIFT": "1"}))
        self.assertFalse(pd.enabled({}, {"BIOCORE_PREFERENCE_DRIFT": "0"}))

    def test_disabled_leaves_weights_alone(self):
        before = vo.defaults()
        out = pd.step(before, {"安全": 50}, {}, enabled=False)
        self.assertEqual(out["reason"], "disabled")
        self.assertEqual(out["drifted"], {})
        self.assertEqual(out["weights"], vo.normalize(before))


class TopicTest(unittest.TestCase):
    def test_topics_extract_cjk_and_latin(self):
        found = pd.topics("今天陪我聊聊天 happy")
        self.assertIn("陪我", found)
        self.assertIn("happy", found)
        self.assertNotIn("今天", found)  # stopword

    def test_dimension_mapping(self):
        self.assertEqual(pd.dimension_of("安全"), "security")
        self.assertEqual(pd.dimension_of("陪我"), "benevolence")
        self.assertEqual(pd.dimension_of("开心"), "hedonism")
        self.assertEqual(pd.dimension_of("诚实"), "universalism")
        self.assertIsNone(pd.dimension_of("zzz"))

    def test_accumulate_counts_once_per_entry(self):
        counts = pd.accumulate({}, [memory("安全安全"), memory("注意安全"),
                                    memory("安全第一")])
        self.assertEqual(counts["安全"], 3)
        self.assertIn("陪我", pd.count_topics([memory("陪我聊天")]))

    def test_entries_are_not_mutated(self):
        entry = memory("陪我聊天")
        snapshot = dict(entry)
        pd.accumulate({}, [entry])
        self.assertEqual(entry, snapshot)


class DriftTest(unittest.TestCase):
    def test_below_threshold_does_nothing(self):
        out = pd.step(vo.defaults(), {"安全": 5}, {}, days=1)
        self.assertEqual(out["drifted"], {})
        self.assertEqual(out["weights"], vo.defaults())

    def test_repeated_topic_raises_dimension(self):
        counts = pd.count_topics([memory("注意安全") for _ in range(6)])
        self.assertEqual(counts["安全"], 6)
        out = pd.step(vo.defaults(), counts, {}, days=1)
        self.assertEqual(out["drifted"].get("security"), 0.01)
        self.assertAlmostEqual(out["weights"]["security"], 0.71, places=4)

    def test_daily_cap_is_respected(self):
        out = pd.step(vo.defaults(), {"安全": 50}, {}, days=1)
        self.assertLessEqual(out["drifted"]["security"], pd.DAILY_CAP)
        self.assertAlmostEqual(out["drifted"]["security"], 0.01, places=4)

    def test_replay_is_idempotent(self):
        counts = {"安全": 6}
        first = pd.step(vo.defaults(), counts, {}, days=1)
        second = pd.step(first["weights"], counts, first["counts"], days=1)
        self.assertEqual(second["drifted"], {})
        self.assertEqual(second["weights"], first["weights"])
        self.assertEqual(second["weights"]["security"], first["weights"]["security"])

    def test_multi_month_accumulation(self):
        weights = vo.defaults()
        counts = {}
        last = {}
        for day in range(1, 91):
            if day % 3 == 0:
                counts = pd.accumulate(counts, [memory("还是要注意安全")])
            out = pd.step(weights, counts, last, days=3)
            weights, last = out["weights"], out["counts"]
        # 30 mentions, first 5 under threshold, 25 steps x 0.002
        self.assertAlmostEqual(weights["security"], 0.75, places=3)


class BoundsTest(unittest.TestCase):
    def test_ceiling(self):
        weights = vo.defaults()
        counts = {}
        last = {}
        for day in range(1, 301):
            counts = pd.accumulate(counts, [memory("注意安全")])
            out = pd.step(weights, counts, last, days=1)
            weights, last = out["weights"], out["counts"]
        self.assertLessEqual(weights["security"], vo.WEIGHT_CEIL)
        self.assertGreaterEqual(weights["security"], vo.WEIGHT_FLOOR)

    def test_floor_via_normalize(self):
        out = pd.step({"security": -5.0}, {}, {}, days=1)
        self.assertGreaterEqual(out["weights"]["security"], vo.WEIGHT_FLOOR)

    def test_decay_returns_toward_default(self):
        table = vo.defaults()
        table["security"] = 0.90
        out = pd.step(table, {}, {}, days=30)
        self.assertIn("security", out["decayed"])
        self.assertAlmostEqual(out["weights"]["security"], 0.885, places=4)

    def test_decay_settles_at_default(self):
        table = vo.defaults()
        table["security"] = 0.90
        for _ in range(200):
            table = pd.step(table, {}, {}, days=30)["weights"]
        self.assertAlmostEqual(table["security"], vo.DEFAULTS["security"], places=3)


class DegradedTest(unittest.TestCase):
    def test_missing_value_order_skips(self):
        saved = pd._vo
        pd._vo = None
        try:
            out = pd.step({"security": 0.7}, {"安全": 9}, {}, days=1)
        finally:
            pd._vo = saved
        self.assertEqual(out["reason"], "value_order_unavailable")
        self.assertEqual(out["weights"], {"security": 0.7})


if __name__ == "__main__":
    unittest.main()
