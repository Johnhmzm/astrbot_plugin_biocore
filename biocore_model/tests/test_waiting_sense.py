# -*- coding: utf-8 -*-
"""task-180 等待感单测：对数饱和、夜间放大、亲近放大、四种感受、关闭。

只依赖 biocore_model.waiting_sense 的纯函数；不导入 main.py。
"""
import unittest

from biocore_model import waiting_sense as ws

CALM = {"gap_seconds": 300, "hour": 14}
FOND = {"gap_seconds": 4 * 3600, "relationship": "friend", "hour": 14}
ANXIOUS = {"gap_seconds": 8 * 3600,
           "last_emotion": {"label": "sad", "valence": -0.6, "arousal": 0.3},
           "relationship": "stranger", "hour": 23}
SULKY = {"gap_seconds": 8 * 3600,
         "last_emotion": {"label": "anger", "valence": -0.7,
                          "arousal": 0.85},
         "relationship": {"stage": "close", "closeness": 0.9}, "hour": 14}


class ContractTest(unittest.TestCase):
    def test_result_keys(self):
        out = ws.waiting_sense(**FOND)
        for key in ("enabled", "waiting", "feeling", "thought", "threshold_hit",
                    "gap_seconds", "gap_hours", "saturation", "closeness",
                    "night", "factors", "reason"):
            self.assertIn(key, out)

    def test_feelings_and_thoughts(self):
        self.assertEqual(set(ws.FEELINGS), {"平静", "惦记", "不安", "赌气"})
        self.assertEqual(set(ws.THOUGHTS), set(ws.FEELINGS))

    def test_values_bounded(self):
        for args in (CALM, FOND, ANXIOUS, SULKY):
            out = ws.waiting_sense(**args)
            self.assertGreaterEqual(out["waiting"], 0.0)
            self.assertLessEqual(out["waiting"], 1.0)
            self.assertGreaterEqual(out["saturation"], 0.0)
            self.assertLessEqual(out["saturation"], 1.0)
            self.assertGreaterEqual(out["closeness"], 0.0)
            self.assertLessEqual(out["closeness"], 1.0)

    def test_flags_and_reason_present(self):
        for args in (CALM, FOND, ANXIOUS, SULKY):
            out = ws.waiting_sense(**args)
            self.assertTrue(out["reason"])
            self.assertTrue(out["thought"])


class FeelingTest(unittest.TestCase):
    def test_short_gap_is_calm(self):
        out = ws.waiting_sense(**CALM)
        self.assertEqual(out["feeling"], "平静")
        self.assertLess(out["waiting"], 0.22)
        self.assertFalse(out["threshold_hit"])

    def test_moderate_gap_is_fond(self):
        self.assertEqual(ws.waiting_sense(**FOND)["feeling"], "惦记")

    def test_long_gap_with_sad_mood_is_anxious(self):
        out = ws.waiting_sense(**ANXIOUS)
        self.assertEqual(out["feeling"], "不安")
        self.assertGreaterEqual(out["waiting"], 0.55)
        self.assertTrue(out["threshold_hit"])

    def test_long_gap_with_anger_and_closeness_is_sulky(self):
        out = ws.waiting_sense(**SULKY)
        self.assertEqual(out["feeling"], "赌气")

    def test_distant_negative_mood_is_not_sulky(self):
        out = ws.waiting_sense(gap_seconds=8 * 3600, relationship="stranger",
                               last_emotion={"label": "anger",
                                             "valence": -0.7,
                                             "arousal": 0.85})
        self.assertEqual(out["feeling"], "不安")

    def test_not_waiting_stays_calm(self):
        out = ws.waiting_sense(gap_seconds=8 * 3600, awaiting_reply=False,
                               last_emotion={"label": "anger"}, hour=23)
        self.assertEqual(out["feeling"], "平静")
        self.assertLess(out["waiting"], 0.22)
        self.assertFalse(out["threshold_hit"])

    def test_thoughts_are_short_and_distinct(self):
        scenarios = (CALM, FOND, ANXIOUS, SULKY)
        thoughts = set()
        for args in scenarios:
            out = ws.waiting_sense(**args)
            self.assertTrue(out["thought"])
            self.assertLessEqual(len(out["thought"]), 24)
            thoughts.add(out["thought"])
        self.assertEqual(len(thoughts), len(scenarios))


class SaturationTest(unittest.TestCase):
    def test_log_saturation_monotone(self):
        values = [ws.saturation(hours * 3600)
                  for hours in (1, 2, 3, 4, 8, 24, 72)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(ws.saturation(0), 0.0)

    def test_equal_windows_shrink(self):
        first = ws.saturation(2 * 3600) - ws.saturation(1 * 3600)
        second = ws.saturation(3 * 3600) - ws.saturation(2 * 3600)
        self.assertGreater(first, second)
        self.assertGreater(first, 0.0)

    def test_seven_days_saturates(self):
        self.assertAlmostEqual(ws.saturation(7 * 24 * 3600), 1.0, places=3)
        self.assertLessEqual(ws.saturation(30 * 24 * 3600), 1.0)

    def test_waiting_rises_with_gap(self):
        values = [ws.waiting_sense(gap_seconds=h * 3600)["waiting"]
                  for h in (1, 2, 4, 8, 24)]
        self.assertEqual(values, sorted(values))

    def test_waiting_factor_product(self):
        out = ws.waiting_sense(**FOND)
        factors = out["factors"]
        expected = (factors["saturation"] * factors["closeness"]
                    * factors["night"] * factors["mood"]
                    * factors["expectation"])
        self.assertAlmostEqual(out["waiting"], min(1.0, expected), places=2)


class AmplificationTest(unittest.TestCase):
    def test_night_amplifies(self):
        day = ws.waiting_sense(gap_seconds=4 * 3600, relationship="friend",
                               hour=14)
        night = ws.waiting_sense(gap_seconds=4 * 3600, relationship="friend",
                                 hour=23)
        self.assertFalse(day["night"])
        self.assertTrue(night["night"])
        self.assertGreater(night["waiting"], day["waiting"])

    def test_closeness_amplifies(self):
        far = ws.waiting_sense(gap_seconds=4 * 3600, relationship="stranger",
                               hour=14)
        near = ws.waiting_sense(gap_seconds=4 * 3600,
                                relationship={"closeness": 0.95}, hour=14)
        self.assertGreater(near["waiting"], far["waiting"])

    def test_stage_strings_map_to_closeness(self):
        friend = ws.waiting_sense(gap_seconds=4 * 3600, relationship="friend",
                                  hour=14)
        close = ws.waiting_sense(gap_seconds=4 * 3600, relationship="close",
                                 hour=14)
        self.assertGreater(close["closeness"], friend["closeness"])
        self.assertGreater(close["waiting"], friend["waiting"])

    def test_negative_last_emotion_amplifies(self):
        neutral = ws.waiting_sense(gap_seconds=4 * 3600,
                                   relationship="friend", hour=14)
        negative = ws.waiting_sense(
            gap_seconds=4 * 3600, relationship="friend", hour=14,
            last_emotion={"valence": -0.8, "arousal": 0.8})
        self.assertGreater(negative["waiting"], neutral["waiting"])


class ThresholdTest(unittest.TestCase):
    def test_threshold_hit_on_long_gap(self):
        self.assertTrue(ws.waiting_sense(gap_seconds=8 * 3600)["threshold_hit"])

    def test_custom_threshold_can_suppress(self):
        out = ws.waiting_sense(**FOND, flags={"threshold": 0.99})
        self.assertFalse(out["threshold_hit"])
        self.assertGreater(out["waiting"], 0.5)

    def test_threshold_seconds_rule(self):
        out = ws.waiting_sense(gap_seconds=6 * 3600 + 1,
                               flags={"threshold": 0.99})
        self.assertTrue(out["threshold_hit"])

    def test_not_waiting_has_no_gap_alert(self):
        out = ws.waiting_sense(gap_seconds=8 * 3600, awaiting_reply=False)
        self.assertFalse(out["threshold_hit"])


class SwitchAndRobustnessTest(unittest.TestCase):
    def test_disabled_is_neutral(self):
        out = ws.waiting_sense(gap_seconds=8 * 3600,
                               flags={"enabled": False})
        self.assertFalse(out["enabled"])
        self.assertEqual(out["waiting"], 0.0)
        self.assertEqual(out["feeling"], "平静")
        self.assertFalse(out["threshold_hit"])
        self.assertIn("关闭", out["reason"])

    def test_odd_gaps(self):
        for gap in (None, "x", [], 3, float("nan"), -100):
            out = ws.waiting_sense(gap_seconds=gap)
            self.assertEqual(out["enabled"], True)
            self.assertGreaterEqual(out["waiting"], 0.0)
            self.assertLessEqual(out["waiting"], 1.0)

    def test_odd_emotions_and_relationships(self):
        for emotion in (None, "anger", "sad", "happy", "weird", 3, []):
            out = ws.waiting_sense(gap_seconds=4 * 3600, last_emotion=emotion)
            self.assertIn(out["feeling"], ws.FEELINGS)
        for rel in (None, "x", 3, [], {"stage": "friend"},
                    {"closeness": -5}):
            out = ws.waiting_sense(gap_seconds=4 * 3600, relationship=rel)
            self.assertGreaterEqual(out["closeness"], 0.0)
            self.assertLessEqual(out["closeness"], 1.0)

    def test_hour_and_night(self):
        self.assertFalse(ws.waiting_sense(gap_seconds=3600, hour=None)["night"])
        self.assertTrue(ws.waiting_sense(gap_seconds=3600, hour=2)["night"])
        self.assertTrue(ws.waiting_sense(gap_seconds=3600, hour=23)["night"])
        self.assertFalse(ws.waiting_sense(gap_seconds=3600, hour=12)["night"])
        self.assertEqual(ws.night_factor(None), 1.0)
        self.assertGreater(ws.night_factor(23), 1.0)


if __name__ == "__main__":
    unittest.main()
