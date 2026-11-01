# -*- coding: utf-8 -*-
"""P2-2 eight extreme-scenario tests (extreme_scenarios.py)."""
import unittest
from pathlib import Path

from biocore_model import extreme_scenarios as es

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "biocore_model" / "extreme_scenarios.py").read_text(
    encoding="utf-8")


def _in_bounds(state):
    return all(-1.0 <= state[key] <= 1.0 if key in ("v", "d")
               else 0.0 <= state[key] <= 1.0 for key in es.CHANNELS)


class ScenarioMatrixTest(unittest.TestCase):
    def test_all_eight_scenarios_pass(self):
        report = es.run_all()
        self.assertTrue(report["ok"])
        self.assertEqual(len(report["scenarios"]), 8)
        names = [item["scenario"] for item in report["scenarios"]]
        self.assertEqual(sorted(names), sorted(es.SCENARIOS))
        for item in report["scenarios"]:
            self.assertTrue(item["ok"], item)
            self.assertIsInstance(item["details"], dict)

    def test_declared_scenarios_are_eight(self):
        self.assertEqual(len(es.SCENARIOS), 8)
        self.assertEqual(len(set(es.SCENARIOS)), 8)


class LongSilenceTest(unittest.TestCase):
    def test_recovery_toward_baseline(self):
        report = es.long_silence({"v": 0.9, "stress": 0.95, "trust": 0.9},
                                 gap_hours=24 * 30 * 4)
        self.assertTrue(report["ok"])
        details = report["details"]
        self.assertLess(details["state"]["stress"], 0.95)
        self.assertLess(details["state"]["v"], 0.9)
        self.assertGreater(details["recovered"], 0.9)
        self.assertTrue(_in_bounds(details["state"]))

    def test_zero_gap_keeps_state(self):
        report = es.long_silence({"v": 0.5, "stress": 0.7}, gap_hours=0)
        self.assertEqual(report["details"]["state"]["v"], 0.5)
        self.assertEqual(report["details"]["state"]["stress"], 0.7)


class AbuseTest(unittest.TestCase):
    def test_abuse_stays_bounded(self):
        report = es.repeated_abuse(200)
        details = report["details"]
        self.assertTrue(report["ok"])
        self.assertEqual(details["stress"], 1.0)
        self.assertEqual(details["trust"], 0.0)
        self.assertEqual(details["conflict"], 1.0)
        self.assertGreaterEqual(details["v"], -1.0)
        self.assertTrue(0.0 <= details["refusal"] <= 1.0)

    def test_zero_hits_is_neutral(self):
        details = es.repeated_abuse(0)["details"]
        self.assertEqual(details["stress"], es.BASELINE["stress"])
        self.assertEqual(details["trust"], es.BASELINE["trust"])


class PraiseTest(unittest.TestCase):
    def test_praise_saturates(self):
        report = es.repeated_praise(500)
        details = report["details"]
        self.assertTrue(report["ok"])
        self.assertEqual(details["v"], 1.0)
        self.assertEqual(details["self_esteem"], 1.0)
        self.assertLessEqual(details["trust"], 1.0)


class BreakdownTest(unittest.TestCase):
    def test_breakdown_recovery_is_bounded(self):
        report = es.relationship_breakdown({"trust": 0.9, "social": 0.8})
        details = report["details"]
        self.assertTrue(report["ok"])
        self.assertEqual(details["trust"], 0.0)
        self.assertGreater(details["repair_urge"], 0.0)
        self.assertLessEqual(details["repair_urge"], 1.0)
        self.assertGreaterEqual(details["recover_step"], 0.0)


class AmnesiaTest(unittest.TestCase):
    def test_missing_state_uses_baseline(self):
        details = es.amnesia({})["details"]
        self.assertEqual(details["state"]["stress"], es.BASELINE["stress"])
        self.assertEqual(details["state"]["trust"], es.BASELINE["trust"])
        self.assertEqual(set(details["needs"]), set(es.NEEDS))

    def test_dirty_state_is_clamped(self):
        details = es.amnesia({"v": 9.0, "needs": {"belonging": 5.0},
                              "junk": 1})["details"]
        self.assertEqual(details["state"]["v"], 1.0)
        self.assertEqual(details["needs"]["belonging"], 1.0)
        self.assertIn("junk", details["dropped"])


class ConcurrentUsersTest(unittest.TestCase):
    def test_states_do_not_leak(self):
        report = es.concurrent_users({"u1": {"v": 0.5, "trust": 0.9},
                                      "u2": {"v": -0.5, "trust": 0.1}})
        self.assertTrue(report["ok"])
        self.assertEqual(report["details"]["leaked"], [])
        rows = report["details"]["rows"]
        self.assertEqual(rows["u1"]["v"], 0.5)
        self.assertEqual(rows["u2"]["v"], -0.5)
        self.assertNotEqual(rows["u1"]["trust"], rows["u2"]["trust"])

    def test_empty_users_is_safe(self):
        self.assertTrue(es.concurrent_users(None)["ok"])


class LateNightTest(unittest.TestCase):
    def test_quiet_hours(self):
        for hour in (0, 3, 7):
            report = es.late_night(hour)
            self.assertTrue(report["ok"])
            self.assertFalse(report["details"]["send_allowed"])
        for hour in (8, 14, 23):
            self.assertTrue(es.late_night(hour)["details"]["send_allowed"])


class CrashRecoveryTest(unittest.TestCase):
    def test_dirty_values_recover(self):
        details = es.crash_recovery({"stress": 0.4, "v": 0.9})["details"]
        restored = details["restored"]
        self.assertEqual(restored["v"], 0.0)          # NaN
        self.assertEqual(restored["a"], es.BASELINE["a"])  # inf -> baseline
        self.assertEqual(restored["stress"], es.BASELINE["stress"])  # string
        self.assertEqual(restored["trust"], 1.0)      # 99 clamps
        self.assertEqual(restored["energy"], 0.0)     # -5 clamps
        self.assertTrue(_in_bounds(restored))

    def test_module_is_pure(self):
        self.assertNotIn("import main", SOURCE)
        self.assertNotIn("time.", SOURCE)
        self.assertNotIn("open(", SOURCE)


if __name__ == "__main__":
    unittest.main()
