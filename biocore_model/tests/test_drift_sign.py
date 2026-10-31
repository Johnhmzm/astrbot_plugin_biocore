# -*- coding: utf-8 -*-
"""Drift sign/monotonicity: silence must eventually drive proactivity."""
import math
import unittest

from biocore_model import autonomy_model as am

LEAK = 0.15
THETA = 0.55
NOW = 1_000_000.0


class CalmCore:
    """Calm, close, no open loops: only silence can move the drive."""
    v = 0.0
    a = 0.45
    d = 0.55
    social = 0.6
    stress = 0.1
    energy = 0.5
    allostatic_load = 0.0
    boredom = 0.0
    homeostasis = {"L_int": 0.05}
    labels = {"emotion": "neutral", "intensity": 0.0}
    open_loops = []
    open_loops_due = 0

    def snapshot(self):
        return {"v": self.v, "a": self.a, "d": self.d, "social": self.social,
                "stress": self.stress, "energy": self.energy,
                "allostatic_load": self.allostatic_load, "boredom": self.boredom,
                "homeostasis": dict(self.homeostasis),
                "open_loops": [], "open_loops_due": 0}


REL = {"state": {"closeness": 0.75, "conflict": 0.2, "repair": 0.2},
       "attachment": {"safe": 0.6}}


def drift_at(hours, core=None):
    parts = am.parts_from_state(core or CalmCore(), REL, now=NOW,
                                acc={"last_user_msg_ts": NOW - hours * 3600.0})
    return am.drift_value(parts), parts


def ticks_to_theta(drift, leak=LEAK, theta=THETA):
    """Autonomy ticks (60s) from V=0 to theta under constant drift."""
    if drift <= theta * leak:
        return None
    return math.log(1.0 - theta * leak / drift) / math.log(1.0 - leak)


class DriftMonotonicTest(unittest.TestCase):
    def test_two_six_twentyfour_increasing(self):
        d2, _ = drift_at(2)
        d6, _ = drift_at(6)
        d24, _ = drift_at(24)
        self.assertLess(d2, d6)
        self.assertLess(d6, d24)
        self.assertGreater(d2, 0.0)

    def test_silence_crosses_threshold_by_two_hours(self):
        d2, parts = drift_at(2)
        self.assertGreater(d2, THETA * LEAK)
        self.assertGreater(parts["lonely"], 0.5)
        self.assertGreater(parts["social_gap"], 0.0)

    def test_zero_silence_stays_below_threshold(self):
        d0, _ = drift_at(0)
        self.assertLess(d0, THETA * LEAK)

    def test_time_to_threshold_is_finite(self):
        d2, _ = drift_at(2)
        ticks = ticks_to_theta(d2)
        self.assertIsNotNone(ticks)
        self.assertGreater(ticks, 0.0)
        self.assertLess(ticks, 60.0)  # under one hour at 60s ticks

    def test_drift_never_negative(self):
        for hours in (0, 1, 2, 6, 12, 24, 48):
            drift, parts = drift_at(hours)
            self.assertGreaterEqual(drift, 0.0)
            self.assertLessEqual(drift, 1.0)


if __name__ == "__main__":
    unittest.main()
