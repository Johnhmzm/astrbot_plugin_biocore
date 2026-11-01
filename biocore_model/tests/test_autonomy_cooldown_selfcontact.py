# -*- coding: utf-8 -*-
"""Cooldown/daily-cap gating + post-send self-contact loneliness damping."""
import ast
import time
import types
import unittest
from pathlib import Path

from biocore_model import autonomy_model as am
from biocore_model import autonomy_tick as at

MAIN = Path(__file__).resolve().parents[2] / "main.py"
NOW = 1_800_000_000.0


def _load(name):
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "BioCorePlugin")
    node = next(f for f in cls.body
                if isinstance(f, ast.FunctionDef) and f.name == name)
    ns = {"time": time}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<a>", "exec"), ns)
    return ns[name]


class ParamsTest(unittest.TestCase):
    def test_apply_forces_cooldown_and_cap(self):
        fn = _load("_apply_autonomy_params")
        plugin = types.SimpleNamespace()
        out = fn(plugin, {}, {"theta": 0.52, "cooldown_s": 1625,
                              "daily_cap": 3})
        self.assertEqual(out["cooldown_seconds"], 1625)
        self.assertEqual(out["daily_cap"], 3)


class GateTest(unittest.TestCase):
    def test_cooldown_rejects_five_minutes(self):
        fn = _load("_autonomy_gate_limits")
        ok, why = fn(types.SimpleNamespace(), {"last_sent_ts": NOW - 300},
                     NOW, cooldown_seconds=1625)
        self.assertFalse(ok)
        self.assertEqual(why, "cooldown")

    def test_cooldown_allows_after_30_minutes(self):
        fn = _load("_autonomy_gate_limits")
        ok, why = fn(types.SimpleNamespace(), {"last_sent_ts": NOW - 2000},
                     NOW, cooldown_seconds=1625)
        self.assertTrue(ok, why)

    def test_daily_cap_blocks(self):
        fn = _load("_autonomy_gate_limits")
        day = time.strftime("%Y-%m-%d", time.localtime(NOW))
        ok, why = fn(types.SimpleNamespace(), {
            "sent_day": day, "sent_count": 3}, NOW, daily_cap=3)
        self.assertFalse(ok)
        self.assertEqual(why, "daily_cap")


class Core:
    def snapshot(self):
        return {"a": 0.4, "energy": 0.5, "stress": 0.2}

    labels = {"emotion": "neutral", "intensity": 0.0}


class PartsTest(unittest.TestCase):
    def test_self_contact_resets_gap(self):
        acc = {"last_user_msg_ts": NOW - 10 * 3600,
               "last_self_contact_ts": NOW - 100}
        parts = am.parts_from_state(Core(), {}, now=NOW, acc=acc,
                                    params={"silence_tau_hours": 2.0,
                                            "social_tau_hours": 18.0})
        self.assertLess(parts["lonely"], 0.2)

    def test_lonely_damped_within_30_minutes(self):
        base = am.parts_from_state(Core(), {}, now=NOW,
                                   acc={"last_user_msg_ts": NOW - 5 * 3600,
                                        "last_self_contact_ts": NOW - 3600},
                                   params={"silence_tau_hours": 2.0})
        damped = am.parts_from_state(Core(), {}, now=NOW,
                                     acc={"last_user_msg_ts": NOW - 5 * 3600,
                                          "last_self_contact_ts": NOW - 1},
                                     params={"silence_tau_hours": 2.0})
        self.assertLess(damped["lonely"], base["lonely"])


class SendBookkeepingTest(unittest.TestCase):
    def test_send_records_self_contact_and_sent_count(self):
        class Deps:
            def __init__(self):
                self.acc = {"V": 1.0, "theta": 0.55, "pending_fire": True}
                self.sent = []

            def load_acc(self):
                return dict(self.acc)

            def save_acc(self, acc):
                self.acc = dict(acc)

            def list_sessions(self):
                return [{"umo": "u1"}]

            def get_core(self, umo):
                return Core()

            def any_core(self):
                return Core()

            def snapshot(self, core):
                return {}

            def params(self):
                return {"theta": 0.55}

            def step(self, V, drift, theta):
                return {"V": V, "fire": True}

            def gate(self, core, acc, silence, now):
                return True, "fired"

            def build_text(self, core, acc):
                return "在。"

            def send_text(self, umo, text):
                self.sent.append(umo)
                return True

        deps = Deps()
        out = at.tick_once(deps, NOW)
        self.assertEqual(out["sent"], ["u1"])
        self.assertEqual(deps.acc["last_self_contact_ts"], NOW)
        self.assertEqual(deps.acc["V"], 0.0)
        self.assertEqual(deps.acc["sent_count"], 1)


if __name__ == "__main__":
    unittest.main()
