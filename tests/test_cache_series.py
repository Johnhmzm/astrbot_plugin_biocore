# -*- coding: utf-8 -*-
"""Contract migration 1: cache stats + series are computed by the core."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from biocore_runtime import cache_stats, core_state, pipeline


class CacheCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "data"
        self.store = self.data_dir / "memory"
        (self.store / "sessions").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def event(self, **values):
        row = {"prompt_tokens": 100, "output_tokens": 20,
               "cache_read": 60, "cache_write": 40}
        row.update(values)
        return cache_stats.record_event(self.store, row,
                                        now=values.pop("ts", time.time()))

    def test_accumulates_events(self):
        now = time.time()
        cache_stats.record_event(self.store, {"prompt_tokens": 10,
            "output_tokens": 2, "cache_read": 4, "cache_write": 1}, now=now)
        cache_stats.record_event(self.store, {"prompt_tokens": 20,
            "output_tokens": 3, "cache_read": 6, "cache_write": 2}, now=now)
        out = cache_stats.compute(self.store, now=now)
        self.assertEqual(out["turns"], 2)
        self.assertEqual(out["prompt_tokens"], 30)
        self.assertEqual(out["output_tokens"], 5)
        self.assertEqual(out["cache_read"], 10)
        self.assertEqual(out["cache_write"], 3)
        self.assertEqual(out["source"], "usage_events")

    def test_hit_rate_ratio(self):
        now = time.time()
        cache_stats.record_event(self.store, {"prompt_tokens": 100,
            "output_tokens": 10, "cache_read": 75, "cache_write": 25}, now=now)
        self.assertAlmostEqual(cache_stats.compute(self.store, now=now)["hit_rate"],
                               0.75, places=4)

    def test_hit_rate_falls_back_to_prompt_tokens(self):
        now = time.time()
        cache_stats.record_event(self.store, {"prompt_tokens": 100,
            "output_tokens": 10, "cache_read": 50, "cache_write": 0}, now=now)
        self.assertAlmostEqual(cache_stats.compute(self.store, now=now)["hit_rate"],
                               0.5, places=4)

    def test_hit_rate_zero_when_empty(self):
        self.assertEqual(cache_stats.compute(self.store)["hit_rate"], 0.0)

    def test_hit_rate_is_clamped(self):
        now = time.time()
        cache_stats.record_event(self.store, {"prompt_tokens": 10,
            "output_tokens": 1, "cache_read": 50, "cache_write": 0}, now=now)
        rate = cache_stats.compute(self.store, now=now)["hit_rate"]
        self.assertGreaterEqual(rate, 0.0)
        self.assertLessEqual(rate, 1.0)

    def test_window_excludes_old_events(self):
        now = time.time()
        cache_stats.record_event(self.store, {"prompt_tokens": 10,
            "cache_read": 5}, now=now - 8 * 86400)
        cache_stats.record_event(self.store, {"prompt_tokens": 20,
            "cache_read": 10}, now=now)
        out = cache_stats.compute(self.store, now=now)
        self.assertEqual(out["turns"], 1)
        self.assertEqual(out["prompt_tokens"], 20)

    def test_legacy_file_is_read_only_fallback(self):
        now = time.time()
        (self.data_dir / "cache_stats.json").write_text(json.dumps({
            "turns": 4, "prompt_tokens": 400, "output_tokens": 40,
            "cache_read": 200, "cache_write": 200, "hit_rate": 0.5,
            "updated_at": now}), encoding="utf-8")
        out = cache_stats.compute(self.store, now=now)
        self.assertEqual(out["source"], "legacy_file")
        self.assertEqual(out["turns"], 4)
        self.assertEqual(out["hit_rate"], 0.5)

    def test_usage_event_action_appends(self):
        out = pipeline.dispatch("usage_event", {
            "store": str(self.store), "prompt_tokens": 30,
            "cache_read": 15, "cache_write": 5, "now": time.time()})
        self.assertTrue(out["ok"])
        self.assertEqual(out["cache"]["cache_read"], 15)

    def test_stats_action_includes_core_cache(self):
        cache_stats.record_event(self.store, {"prompt_tokens": 10,
            "cache_read": 5, "cache_write": 5}, now=time.time())
        out = pipeline.dispatch("stats", {"store": str(self.store)})
        self.assertIn("cache", out)
        self.assertEqual(out["cache"]["source"], "usage_events")
        self.assertEqual(out["cache"]["hit_rate"], 0.5)


class SeriesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "data"
        self.store = self.data_dir / "memory"
        (self.store / "sessions").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_series_arrays(self):
        out = pipeline.dispatch("series", {"store": str(self.store),
                                           "data_dir": str(self.data_dir)})
        self.assertTrue(out["ok"])
        for key in ("ts", "v", "tension", "warmth", "heaviness", "clarity"):
            self.assertIsInstance(out["series"][key], list)
            self.assertEqual(out["series"][key], [])

    def test_series_points_from_core_state(self):
        path = core_state.path_for(data_dir=str(self.data_dir))
        now = time.time()
        core_state.apply(path, absolute={"v": 0.2, "stress": 0.4}, now=now)
        core_state.apply(path, absolute={"v": 0.3, "stress": 0.2}, now=now + 60)
        out = pipeline.dispatch("series", {"store": str(self.store),
                                           "data_dir": str(self.data_dir),
                                           "limit": 24})
        self.assertTrue(out["points"])
        self.assertLessEqual(len(out["points"]), 24)
        self.assertEqual(len(out["series"]["ts"]), len(out["points"]))


if __name__ == "__main__":
    unittest.main()
