# -*- coding: utf-8 -*-
"""Persona theta overwrite tests: save path and startup write."""
import ast
import tempfile
import types
import unittest
from pathlib import Path

from biocore_model import ui_settings

MAIN = Path(__file__).resolve().parents[2] / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")


def _load_methods():
    tree = ast.parse(SOURCE)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "BioCorePlugin")
    wanted = ("_apply_autonomy_params", "_write_autonomy_theta_once")
    ns = {}
    fns = {}
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            clone = ast.FunctionDef(name=node.name, args=node.args, body=node.body,
                                    decorator_list=[], returns=node.returns,
                                    type_comment=None, lineno=node.lineno,
                                    col_offset=node.col_offset,
                                    end_lineno=node.end_lineno,
                                    end_col_offset=node.end_col_offset)
            exec(compile(ast.Module(body=[clone], type_ignores=[]), "<theta>", "exec"),
                 ns)
            fns[node.name] = ns[node.name]
    return fns


FNS = _load_methods()


class FakePlugin:
    def __init__(self, data_dir):
        self.data_dir = str(data_dir)
        self.autonomy_params = {"theta": 0.5239, "cooldown_s": 1625,
                                "daily_cap": 3}
        self._autonomy_theta_written = False
        self._apply_autonomy_params = types.MethodType(
            FNS["_apply_autonomy_params"], self)
        self._write_autonomy_theta_once = types.MethodType(
            FNS["_write_autonomy_theta_once"], self)

    def _autonomy_params(self):
        return dict(self.autonomy_params)


class ParamsMergeTest(unittest.TestCase):
    def test_theta_overwrites_stale_value(self):
        plugin = FakePlugin(tempfile.gettempdir())
        out = plugin._apply_autonomy_params({"theta": 0.55}, {"theta": 0.5239})
        self.assertAlmostEqual(out["theta"], 0.5239, places=4)

    def test_cooldown_and_cap_overwrite_only_when_present(self):
        plugin = FakePlugin(tempfile.gettempdir())
        out = plugin._apply_autonomy_params(
            {"theta": 0.55, "cooldown_seconds": 1800, "daily_cap": 5, "V": 0.1},
            {"theta": 0.52, "cooldown_s": 1625, "daily_cap": 3})
        self.assertEqual(out["cooldown_seconds"], 1625)
        self.assertEqual(out["daily_cap"], 3)
        self.assertEqual(out["V"], 0.1)
        lean = plugin._apply_autonomy_params({"theta": 0.55}, {"theta": 0.52})
        self.assertNotIn("cooldown_seconds", lean)
        self.assertNotIn("daily_cap", lean)

    def test_params_unavailable_keeps_old_theta(self):
        plugin = FakePlugin(tempfile.gettempdir())
        out = plugin._apply_autonomy_params({"theta": 0.55}, {})
        self.assertAlmostEqual(out["theta"], 0.55, places=4)


class StartupWriteTest(unittest.TestCase):
    def test_startup_write_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = FakePlugin(tmp)
            ui_settings.save(plugin, {"autonomy": {"accumulator": {
                "theta": 0.55, "V": 0.15, "cooldown_seconds": 1800,
                "daily_cap": 5}}})
            plugin._write_autonomy_theta_once()
            saved = ((ui_settings.load(plugin).get("autonomy") or {})
                     .get("accumulator") or {})
            self.assertAlmostEqual(saved["theta"], 0.5239, places=4)
            self.assertEqual(saved["cooldown_seconds"], 1625)
            self.assertEqual(saved["daily_cap"], 3)
            self.assertEqual(saved["V"], 0.15)
            # Second call is a no-op (startup write once).
            plugin.autonomy_params = {"theta": 0.9, "cooldown_s": 9999,
                                      "daily_cap": 8}
            plugin._write_autonomy_theta_once()
            again = ((ui_settings.load(plugin).get("autonomy") or {})
                     .get("accumulator") or {})
            self.assertAlmostEqual(again["theta"], 0.5239, places=4)

    def test_save_path_overwrites_after_one_tick(self):
        plugin = FakePlugin(tempfile.gettempdir())
        payload = {"theta": 0.55, "V": 0.1}
        out = plugin._apply_autonomy_params(payload, plugin._autonomy_params())
        self.assertAlmostEqual(out["theta"], 0.5239, places=4)


class WiringStaticTest(unittest.TestCase):
    def test_log_has_theta_and_save_uses_params(self):
        self.assertIn("autonomy tick engine=module V=%.3f theta=%.3f", SOURCE)
        self.assertIn("self._apply_autonomy_params(payload, params)", SOURCE)
        self.assertIn("_write_autonomy_theta_once()", SOURCE)


if __name__ == "__main__":
    unittest.main()
