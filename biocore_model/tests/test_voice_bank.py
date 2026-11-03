# -*- coding: utf-8 -*-
"""Voice bank: loading, state matching, cooldown, picking."""
import random
import unittest

from biocore_model import voice_bank as vb

NOW = 1790000000.0

BANK = [
    {"phrase": "少来。", "when": {"v_min": 0.0, "v_max": 1.0, "stages": ["close"]},
     "weight": 2.0, "cooldown_s": 3600},
    {"phrase": "有点累。", "when": {"v_min": -1.0, "v_max": 0.0,
                                "tension_min": 0.5}, "weight": 3.0},
    {"phrase": "怎么了？", "when": {"v_min": -1.0, "v_max": 0.3},
     "weight": 1.0, "cooldown_s": 60},
]

class LoadTest(unittest.TestCase):
    def test_drops_malformed_and_duplicates(self):
        rows = vb.load([None, "x", {"phrase": ""}, {"phrase": "嗯"},
                       {"phrase": "嗯"}, {"phrase": "y" * 80}])
        self.assertEqual([row["phrase"] for row in rows], ["嗯"])

    def test_normalizes_stage_string_and_range(self):
        row = vb.load([{"phrase": "好", "when": {"stages": "close",
                                      "v_min": 0.8, "v_max": 0.2}}])[0]
        self.assertEqual(row["when"]["stages"], ["close"])
        self.assertEqual(row["when"]["v_min"], 0.2)
        self.assertEqual(row["when"]["v_max"], 0.8)

    def test_defaults_filled(self):
        row = vb.load([{"phrase": "嗯"}])[0]
        self.assertEqual(row["weight"], 1.0)
        self.assertEqual(row["cooldown_s"], vb.DEFAULT_COOLDOWN_S)
        self.assertEqual(len(row["when"]["stages"]), len(vb.STAGES))

class MatchTest(unittest.TestCase):
    def test_v_range(self):
        row = vb.load(BANK)[0]
        self.assertTrue(vb.matches(row, {"v": 0.5}, "close"))
        self.assertFalse(vb.matches(row, {"v": -0.5}, "close"))

    def test_stage(self):
        row = vb.load(BANK)[0]
        self.assertFalse(vb.matches(row, {"v": 0.5}, "stranger"))

    def test_tension_band(self):
        row = vb.load(BANK)[1]
        self.assertTrue(vb.matches(row, {"v": -0.2, "tension": 0.7}, "normal"))
        self.assertFalse(vb.matches(row, {"v": -0.2, "tension": 0.2}, "normal"))

class CooldownTest(unittest.TestCase):
    def test_cooldown_blocks(self):
        out = vb.pick({"v": -0.2}, {"stage": "normal"},
                      {"怎么了？": NOW - 10}, NOW, BANK)
        self.assertNotIn("怎么了？", out)

    def test_cooldown_expires(self):
        out = vb.pick({"v": -0.2}, {"stage": "normal"},
                      {"怎么了？": NOW - 120}, NOW, BANK)
        self.assertIn("怎么了？", out)

class PickTest(unittest.TestCase):
    def test_empty_bank(self):
        self.assertEqual(vb.pick({}, {}, {}, NOW, []), [])
        self.assertEqual(vb.pick({}, {}, {}, NOW), [])

    def test_at_most_two_and_deterministic(self):
        out = vb.pick({"v": -0.2, "tension": 0.8}, {"stage": "normal"},
                      {}, NOW, BANK)
        self.assertLessEqual(len(out), 2)
        self.assertEqual(out[0], "有点累。")

    def test_rng_picks_within_candidates(self):
        rng = random.Random(7)
        out = vb.pick({"v": -0.2, "tension": 0.8}, {"stage": "normal"},
                      {}, NOW, BANK, rng=rng)
        self.assertTrue(set(out).issubset({"有点累。", "怎么了？"}))
        self.assertEqual(len(out), len(set(out)))

    def test_mark_used_stamps(self):
        used = vb.mark_used({}, ["嗯"], NOW)
        self.assertEqual(used["嗯"], NOW)
        used = vb.mark_used(used, ["啊"], NOW + 5)
        self.assertEqual(used["啊"], NOW + 5)
        self.assertEqual(used["嗯"], NOW)

    def test_available_sorted_by_weight(self):
        rows = vb.available(BANK, {"v": -0.2, "tension": 0.8},
                             {"stage": "normal"}, {}, NOW)
        weights = [row["weight"] for row in rows]
        self.assertEqual(weights, sorted(weights, reverse=True))

class StatsTest(unittest.TestCase):
    def test_counts(self):
        out = vb.stats(BANK)
        self.assertEqual(out["total"], 3)
        # Entries without an explicit stage list apply to every stage.
        self.assertEqual(out["by_stage"]["close"], 3)
        self.assertEqual(out["by_stage"]["normal"], 2)
        self.assertEqual(out["by_stage"]["stranger"], 2)

if __name__ == "__main__":
    unittest.main()
