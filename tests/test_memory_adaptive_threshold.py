# -*- coding: utf-8 -*-
"""The closing threshold is learned per session; the constant is only a clamp."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_runtime import pipeline as P  # noqa: E402


class AdaptiveThresholdTest(unittest.TestCase):
    def setUp(self):
        self._saved = P.EVENT_SIM_OVERRIDE
        P.EVENT_SIM_OVERRIDE = None

    def tearDown(self):
        P.EVENT_SIM_OVERRIDE = self._saved

    def test_a_tight_session_gets_a_higher_bar_than_a_split_one(self):
        tight = [0.70, 0.72, 0.68, 0.71, 0.69, 0.70, 0.71, 0.70, 0.69, 0.70]
        split = [0.90, 0.20, 0.88, 0.22, 0.91, 0.19, 0.89, 0.21, 0.90, 0.20]
        thr_tight = P._sim_threshold(tight, log=False)
        thr_split = P._sim_threshold(split, log=False)
        self.assertGreater(thr_tight, thr_split)

    def test_the_override_wins(self):
        P.EVENT_SIM_OVERRIDE = "0.42"
        self.assertAlmostEqual(P._sim_threshold([0.1, 0.2], log=False), 0.42)

    def test_extremes_stay_inside_the_clamp(self):
        self.assertLessEqual(P._sim_threshold([1.0] * 20, log=False), P.EVENT_SIM_MAX)
        self.assertGreaterEqual(P._sim_threshold([0.0] * 20, log=False), P.EVENT_SIM_MIN)

    def test_no_samples_falls_back_to_the_constant(self):
        self.assertAlmostEqual(P._sim_threshold([], log=False), P.EVENT_SIM_CLOSE)


if __name__ == "__main__":
    unittest.main()
