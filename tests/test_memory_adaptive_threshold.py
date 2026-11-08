# -*- coding: utf-8 -*-
"""The closing threshold is learned per session: mean - 1 sigma, clamped.

A stable conversation must keep its events; a conversation with a real topic
drop must split there. A low quantile gets that backwards, so the estimator is
the mean minus one sigma -- it sits *below* the body of a stable session and
*between* the peaks of a split one.
"""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_runtime import pipeline as P  # noqa: E402


def closes(sims, thr):
    """How many turns a plain 'close when sim < thr' rule would cut."""
    return sum(1 for value in sims if value < thr)


class AdaptiveThresholdTest(unittest.TestCase):
    def setUp(self):
        self._saved = P.EVENT_SIM_OVERRIDE
        P.EVENT_SIM_OVERRIDE = None

    def tearDown(self):
        P.EVENT_SIM_OVERRIDE = self._saved

    def test_a_stable_session_keeps_its_events(self):
        tight = [0.79, 0.81, 0.80, 0.78, 0.82, 0.79, 0.80, 0.81, 0.80, 0.80]
        thr = P._sim_threshold(tight, log=False)
        self.assertAlmostEqual(thr, 0.80 - 0.02, delta=0.05)   # near mean - sigma
        self.assertEqual(closes(tight, thr), 0)                 # nothing splits

    def test_a_split_session_is_cut_between_the_peaks(self):
        split = [0.90, 0.20, 0.88, 0.22, 0.91, 0.19, 0.89, 0.21, 0.90, 0.20]
        thr = P._sim_threshold(split, log=False)
        self.assertGreater(thr, 0.20)
        self.assertLess(thr, 0.90)                              # between the peaks
        self.assertGreaterEqual(closes(split, thr), 4)          # the drops split

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
