# -*- coding: utf-8 -*-
"""Adaptive event boundaries: threshold, coverage, bisect point, merging."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.event import segment_adaptive as SA


def vec(*values):
    return list(values)


class ThresholdTest(unittest.TestCase):
    def test_quantile_and_median(self):
        self.assertEqual(SA.median([3, 1, 2]), 2)
        self.assertEqual(SA.median([1, 2, 3, 4]), 2.5)
        self.assertAlmostEqual(SA.quantile([0, 10], 0.2), 2.0)

    def test_threshold_is_clamped(self):
        high = SA.adaptive_threshold([0.99] * 20)
        low = SA.adaptive_threshold([0.01] * 20)
        self.assertLessEqual(high, SA.THR_MAX)
        self.assertGreaterEqual(low, SA.THR_MIN)

    def test_small_sample_uses_mean_minus_sigma(self):
        thr = SA.adaptive_threshold([0.30, 0.30, 0.30], small_n=5)
        self.assertAlmostEqual(thr, 0.30, places=6)

    def test_no_samples_is_none(self):
        self.assertIsNone(SA.adaptive_threshold([]))

    def test_threshold_follows_the_session(self):
        sims = [0.90] * 10 + [0.20] * 10
        thr = SA.adaptive_threshold(sims)
        self.assertGreaterEqual(thr, SA.THR_MIN)
        self.assertLess(thr, 0.5)


class BoundaryTest(unittest.TestCase):
    def test_adjacent_pairs_skipped_when_vector_missing(self):
        rows = [vec(1, 0), None, vec(0, 1)]
        self.assertEqual(len(SA.adjacent_similarities(rows)), 1)

    def test_largest_jump_finds_the_drop(self):
        rows = [vec(1, 0), vec(0.98, 0.02), vec(0, 1), vec(0.02, 0.98)]
        self.assertEqual(SA.largest_jump(rows), 2)

    def test_singletons_are_folded(self):
        parts = [[1, 2], [3], [4, 5]]
        merged = SA.merge_singletons(parts)
        self.assertEqual([len(part) for part in merged], [3, 2])

    def test_coverage_is_a_median(self):
        note = vec(1, 0)
        turns = [vec(1, 0), vec(0.9, 0.1), vec(0, 1)]
        self.assertAlmostEqual(SA.coverage(note, turns), 0.9938, places=3)


if __name__ == "__main__":
    unittest.main()
