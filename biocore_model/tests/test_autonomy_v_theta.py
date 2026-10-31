# -*- coding: utf-8 -*-
"""Regression tests: V floor (>= 0) and theta persistence in the accumulator."""
import unittest
from pathlib import Path

from biocore_model import autonomy_model as am
from biocore_model import autonomy_tick as at

MAIN = Path(__file__).resolve().parents[2] / "main.py"


class FakeDeps:
    def __init__(self, acc=None):
        self.acc = dict(acc or {})
        self.saved = []
        self.load_acc = lambda: dict(self.acc)
        self.save_acc = lambda value: self.saved.append(dict(value))
        self.list_sessions = lambda: []


class StepFloorTest(unittest.TestCase):
    def test_negative_drift_never_makes_v_negative(self):
        value = 0.0
        for _ in range(10):
            out = am.step(value, -0.5, xi=0.0)
            value = out["V"]
            self.assertGreaterEqual(value, 0.0)
            self.assertFalse(out["fire"])

    def test_existing_positive_v_floors_at_zero(self):
        out = am.step(0.10, -0.5, xi=0.0)
        self.assertEqual(out["V"], 0.0)
        self.assertGreaterEqual(out["V"], 0.0)

    def test_positive_drift_accumulates(self):
        first = am.step(0.0, 0.2, xi=0.0)["V"]
        second = am.step(first, 0.2, xi=0.0)["V"]
        self.assertGreater(second, first)

    def test_fire_resets_to_zero(self):
        out = am.step(0.70, 0.0, theta=0.55, xi=0.0)
        self.assertTrue(out["fire"])
        self.assertEqual(out["V"], 0.0)

    def test_v_raw_keeps_raw_value_for_debug(self):
        out = am.step(0.10, -0.5, xi=0.0)
        self.assertEqual(out["V"], 0.0)
        self.assertLess(out["V_raw"], 0.0)


class RecordThetaTest(unittest.TestCase):
    def test_record_adds_default_theta(self):
        deps = FakeDeps()
        at._record({}, deps, 1000.0, {})
        self.assertEqual(deps.saved[-1]["theta"], 0.55)
        self.assertEqual(deps.saved[-1]["V"], 0.0)
        self.assertEqual(deps.saved[-1]["last_tick_ts"], 1000.0)

    def test_record_preserves_existing_theta(self):
        deps = FakeDeps()
        at._record({"theta": 0.7, "V": -0.2}, deps, 2000.0, {})
        self.assertEqual(deps.saved[-1]["theta"], 0.7)
        self.assertEqual(deps.saved[-1]["V"], 0.0)

    def test_tick_once_writeback_has_theta(self):
        deps = FakeDeps()
        result = at.tick_once(deps, 3000.0)
        self.assertEqual(result["reason"], "no_session")
        self.assertEqual(deps.saved[-1]["theta"], 0.55)
        self.assertGreaterEqual(deps.saved[-1]["V"], 0.0)


class MainWritebackStaticTest(unittest.TestCase):
    def test_save_acc_guards_theta_and_v(self):
        source = MAIN.read_text(encoding="utf-8")
        self.assertIn('self._apply_autonomy_params(payload, params)', source)
        self.assertIn('max(0.0, float(payload.get("V", 0.0) or 0.0))', source)

    def test_satiety_writeback_keeps_theta(self):
        source = MAIN.read_text(encoding="utf-8")
        self.assertIn('"V": v_set, "theta": theta', source)


if __name__ == "__main__":
    unittest.main()
