# -*- coding: utf-8 -*-
"""Persona-derived autonomy rhythm (theta/tau/cooldown) tests."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

import interpretation
from biocore_model import autonomy_model as am
from biocore_model import autonomy_params as ap

MAIN = Path(__file__).resolve().parents[2] / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")
NOW = 1_000_000.0
REAL = {"O": 0.82, "C": 0.38, "E": 0.93, "A": 0.70, "N": 0.52,
        "recovery_rate": 0.78, "social_baseline": 0.88}
REL = {"state": {"closeness": 0.5, "conflict": 0.3, "repair": 0.2},
       "attachment": {"safe": 0.6}, "attachment_style": "secure"}


class CalmCore:
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


class MonotonicTest(unittest.TestCase):
    def test_extraversion_up_theta_down(self):
        low = ap.from_profile(dict(REAL, E=0.2), REL)
        high = ap.from_profile(dict(REAL, E=0.95), REL)
        self.assertLess(high["theta"], low["theta"])

    def test_closeness_up_theta_and_tau_down(self):
        far = {"state": {"closeness": 0.2}}
        near = {"state": {"closeness": 0.9}}
        a = ap.from_profile(REAL, far)
        b = ap.from_profile(REAL, near)
        self.assertLess(b["theta"], a["theta"])
        self.assertLess(b["tau_hours"], a["tau_hours"])

    def test_avoidance_up_theta_and_cooldown_up(self):
        secure = ap.from_profile(REAL, {"attachment_style": "secure"})
        avoid = ap.from_profile(REAL, {"attachment_style": "avoidant"})
        self.assertGreater(avoid["theta"], secure["theta"])
        self.assertGreater(avoid["cooldown_s"], secure["cooldown_s"])

    def test_ignore_rate_up_cooldown_up(self):
        calm = ap.from_profile(REAL, REL, ignore_rate=0.0)
        ignored = ap.from_profile(REAL, REL, ignore_rate=0.9)
        self.assertGreater(ignored["cooldown_s"], calm["cooldown_s"])


class RealProfileTest(unittest.TestCase):
    def test_real_profile_values(self):
        params = ap.from_profile(REAL, REL, responsiveness=0.5, ignore_rate=0.0)
        self.assertAlmostEqual(params["theta"], 0.5239, places=3)
        self.assertAlmostEqual(params["tau_hours"], 16.0, places=1)
        self.assertEqual(params["cooldown_s"], 1625)
        self.assertAlmostEqual(params["silence_tau_hours"], 2.001, places=2)
        self.assertEqual(params["daily_cap"], 3)

    def test_flat_and_nested_profile_agree(self):
        flat = ap.from_profile(REAL, REL)
        nested = ap.from_profile({"big5": {"E": 0.93, "N": 0.52}}, REL)
        self.assertAlmostEqual(flat["theta"], nested["theta"], places=2)

    def test_override_applies_and_clamps(self):
        base = ap.from_profile(REAL, REL)
        out = ap.apply_overrides(base, {"theta": 0.9, "daily_cap": 99,
                                        "cooldown_s": 5})
        self.assertAlmostEqual(out["theta"], 0.9, places=3)
        self.assertLessEqual(out["daily_cap"], 12)
        self.assertGreaterEqual(out["cooldown_s"], 300)


class CadenceTest(unittest.TestCase):
    def _trigger_minutes(self):
        params = ap.from_profile(REAL, REL)
        acc = {"last_user_msg_ts": NOW}
        value = 0.0
        for minute in range(0, 300):
            parts = am.parts_from_state(
                CalmCore(), REL, now=NOW + minute * 60.0, acc=acc,
                params=params, social_baseline=REAL["social_baseline"])
            out = am.step(value, am.drift_value(parts), leak=0.15,
                          sigma=0.0, theta=params["theta"])
            value = out["V"]
            if out["fire"]:
                return minute
        return None

    def test_real_profile_cadence_60_to_120_minutes(self):
        minutes = self._trigger_minutes()
        self.assertIsNotNone(minutes)
        self.assertGreaterEqual(minutes, 60)
        self.assertLessEqual(minutes, 120)

    def test_params_change_parts_taus(self):
        fast = ap.from_profile(REAL, REL)
        slow = dict(fast, silence_tau_hours=8.0, social_tau_hours=36.0)
        acc = {"last_user_msg_ts": NOW - 2 * 3600}
        a = am.parts_from_state(CalmCore(), REL, now=NOW, acc=acc, params=fast,
                                social_baseline=REAL["social_baseline"])
        b = am.parts_from_state(CalmCore(), REL, now=NOW, acc=acc, params=slow,
                                social_baseline=REAL["social_baseline"])
        self.assertGreater(a["lonely"], b["lonely"])
        self.assertGreater(a["social_gap"], b["social_gap"])


class Big5FlatReadTest(unittest.TestCase):
    def _load_big5(self):
        tree = ast.parse(SOURCE)
        cls = next(n for n in tree.body
                   if isinstance(n, ast.ClassDef) and n.name == "BioCorePlugin")
        node = next(f for f in cls.body
                    if isinstance(f, ast.FunctionDef) and f.name == "_big5_effect")
        ns = {"interpretation": interpretation}
        clone = ast.FunctionDef(name=node.name, args=node.args, body=node.body,
                                decorator_list=[], returns=node.returns,
                                type_comment=None, lineno=node.lineno,
                                col_offset=node.col_offset,
                                end_lineno=node.end_lineno,
                                end_col_offset=node.end_col_offset)
        exec(compile(ast.Module(body=[clone], type_ignores=[]), "<big5>", "exec"), ns)
        return ns[node.name]

    def test_flat_ocean_keys_are_read(self):
        fn = self._load_big5()
        core = SimpleNamespace(profile=dict(REAL), a=0.5, v=0.0)
        out = fn(None, core)
        cue = 0.5
        self.assertEqual(out["extraversion"],
                         interpretation.big5_trait_effect(0.93, cue))
        self.assertEqual(out["neuroticism"],
                         interpretation.big5_trait_effect(0.52, cue))


class WiringStaticTest(unittest.TestCase):
    def test_main_uses_params_for_theta_cooldown_and_ui_override(self):
        self.assertIn("_autonomy_params()", SOURCE)
        self.assertIn("params.get(\"cooldown_s\"", SOURCE)
        self.assertIn("params.get(\"theta\"", SOURCE)
        self.assertIn("\"params\"", SOURCE)


if __name__ == "__main__":
    unittest.main()
