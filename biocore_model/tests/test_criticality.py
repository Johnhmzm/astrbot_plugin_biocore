# -*- coding: utf-8 -*-
"""HUMAN-5 criticality tests: deterministic power-law avalanches."""
import unittest

from biocore_model import criticality as cr


class SizeTest(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(cr.size(5, 9), cr.size(5, 9))

    def test_bounds_and_cap(self):
        for tick in range(100):
            value = cr.size(2, tick)
            self.assertGreaterEqual(value, cr.MIN_SIZE)
            self.assertLessEqual(value, cr.MAX_SIZE)
        self.assertLessEqual(max(cr.batch(2, 50, max_size=5)), 5)

    def test_min_size_respected(self):
        self.assertGreaterEqual(cr.size(2, 0, max_size=3, min_size=2), 2)

    def test_mostly_small(self):
        stats = cr.summary(cr.batch(11, 500))
        self.assertGreater(stats["small_fraction"], 0.85)

    def test_heavy_tail_exists(self):
        stats = cr.summary(cr.batch(11, 2000))
        self.assertGreater(stats["max"], cr.HEAVY_CUTOFF)


class BatchSummaryTest(unittest.TestCase):
    def test_batch_reproducible(self):
        self.assertEqual(cr.batch(3, 20), cr.batch(3, 20))
        self.assertEqual(len(cr.batch(3, 20)), 20)

    def test_summary_fields(self):
        stats = cr.summary([1, 2, 3, 100])
        for key in ("n", "mean", "max", "small_fraction", "heavy_fraction"):
            self.assertIn(key, stats)
        self.assertEqual(stats["n"], 4)
        self.assertEqual(stats["max"], 100)

    def test_empty_summary(self):
        stats = cr.summary([])
        self.assertEqual(stats["n"], 0)

    def test_alpha_changes_distribution(self):
        shallow = cr.summary(cr.batch(7, 500, alpha=1.5))["mean"]
        steep = cr.summary(cr.batch(7, 500, alpha=2.5))["mean"]
        self.assertLess(steep, shallow)

    def test_event_and_burst(self):
        self.assertFalse(cr.is_event(1, 1, p=0.0))
        self.assertTrue(cr.is_event(1, 1, p=1.0))
        value = cr.burst_value(1, 1, alpha=1.5)
        self.assertGreaterEqual(value, -1.0)
        self.assertLessEqual(value, 1.0)


if __name__ == "__main__":
    unittest.main()
