# -*- coding: utf-8 -*-
"""P0-2: per-message total |dims delta| budget (delta_budget + main wiring)."""
import ast
import json
import types
import unittest
from pathlib import Path

from biocore_model import appraisal
from biocore_model import delta_budget as db

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")
SCHEMA = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))


def _load_budget_helper():
    tree = ast.parse(SOURCE)
    node = next(item for item in tree.body
                if isinstance(item, ast.FunctionDef)
                and item.name == "_budget_dims_deltas")
    clone = ast.FunctionDef(name=node.name, args=node.args, body=node.body,
                            decorator_list=[], returns=node.returns,
                            type_comment=None, lineno=node.lineno,
                            col_offset=node.col_offset,
                            end_lineno=node.end_lineno,
                            end_col_offset=node.end_col_offset)
    ns = {"logger": types.SimpleNamespace(
        info=lambda *a, **k: None, warning=lambda *a, **k: None,
        debug=lambda *a, **k: None)}
    exec(compile(ast.Module(body=[clone], type_ignores=[]),
                 "<_budget_dims_deltas>", "exec"), ns)
    return ns[node.name]


BUDGET_METHOD = _load_budget_helper()


class _FakePlugin:
    def __init__(self, limit=0.2, enabled=True):
        self.dims_delta_limit = limit
        self.dims_delta_limit_enabled = enabled


class BudgetTest(unittest.TestCase):
    def test_within_limit_unchanged(self):
        deltas = {"v": 0.10, "a": -0.05}
        scaled, report = db.budget(deltas)
        self.assertFalse(report["scaled"])
        self.assertEqual(scaled, deltas)
        self.assertAlmostEqual(report["raw_total"], 0.15)
        self.assertAlmostEqual(report["factor"], 1.0)

    def test_over_limit_scaled_proportionally(self):
        deltas = {"v": 0.6, "a": -0.3, "stress": 0.1}
        scaled, report = db.budget(deltas, limit=0.2)
        self.assertTrue(report["scaled"])
        self.assertAlmostEqual(report["raw_total"], 1.0)
        self.assertLessEqual(report["scaled_total"], 0.2 + 1e-6)
        self.assertAlmostEqual(report["factor"], 0.2)
        # direction and channel ratios are preserved
        self.assertGreater(scaled["v"], 0)
        self.assertLess(scaled["a"], 0)
        self.assertAlmostEqual(scaled["v"] / scaled["a"], deltas["v"] / deltas["a"])
        self.assertAlmostEqual(scaled["v"], 0.12, places=4)

    def test_zero_deltas_unchanged(self):
        scaled, report = db.budget({"v": 0.0, "a": 0.0})
        self.assertEqual(scaled, {"v": 0.0, "a": 0.0})
        self.assertFalse(report["scaled"])
        self.assertEqual(report["raw_total"], 0.0)

    def test_multi_field_sum_crosses_limit(self):
        deltas = {"v": 0.08, "a": 0.08, "d": 0.08, "social": 0.04}
        scaled, report = db.budget(deltas, limit=0.2)
        self.assertTrue(report["scaled"])
        self.assertAlmostEqual(report["raw_total"], 0.28)
        self.assertLessEqual(db.total(scaled), 0.2 + 1e-6)
        self.assertEqual(len(scaled), 4)

    def test_disabled_returns_unchanged(self):
        deltas = {"v": 0.6, "stress": 0.3}
        scaled, report = db.budget(deltas, limit=0.2, enabled=False)
        self.assertEqual(scaled, deltas)
        self.assertFalse(report["scaled"])
        self.assertFalse(report["enabled"])

    def test_custom_limit_respected(self):
        scaled, report = db.budget({"v": 0.5, "a": 0.5}, limit=0.5)
        self.assertTrue(report["scaled"])
        self.assertAlmostEqual(sum(abs(x) for x in scaled.values()), 0.5)

    def test_invalid_values_dropped(self):
        scaled, report = db.budget({"v": "abc", "a": None, "d": float("nan"),
                                    "stress": float("inf"), "trust": 0.05})
        self.assertEqual(scaled, {"trust": 0.05})
        self.assertFalse(report["scaled"])

    def test_invalid_limit_falls_back_to_default(self):
        self.assertAlmostEqual(db.clean_limit(0), db.DEFAULT_LIMIT)
        self.assertAlmostEqual(db.clean_limit("x"), db.DEFAULT_LIMIT)
        self.assertAlmostEqual(db.clean_limit(None), db.DEFAULT_LIMIT)
        self.assertAlmostEqual(db.clean_limit(5.0), db.MAX_LIMIT)
        self.assertAlmostEqual(db.clean_limit(0.0001), db.MIN_LIMIT)

    def test_negative_deltas_use_absolute_sum(self):
        scaled, report = db.budget({"v": -0.5, "a": -0.5}, limit=0.2)
        self.assertTrue(report["scaled"])
        self.assertAlmostEqual(report["raw_total"], 1.0)
        self.assertAlmostEqual(scaled["v"], -0.1, places=4)

    def test_real_appraise_output_is_bounded(self):
        # full-blown dims from the appraisal layer can exceed one message budget
        dims = {"goal": 1.0, "blame": 1.0, "hit": 1.0, "involve": 1.0,
                "control": 1.0, "novelty": 1.0, "certainty": 1.0}
        deltas = appraisal.appraise(dims, confidence=1.0)
        self.assertGreater(db.total(deltas), 0.2)
        scaled, report = db.budget(deltas)
        self.assertTrue(report["scaled"])
        self.assertLessEqual(db.total(scaled), 0.2 + 1e-6)


class MainWiringTest(unittest.TestCase):
    def test_config_attrs_and_call_sites(self):
        self.assertIn("dims_delta_limit_enabled", SOURCE)
        self.assertIn("dims_delta_limit", SOURCE)
        self.assertIn("def _budget_dims_deltas(plugin, deltas", SOURCE)
        self.assertEqual(SOURCE.count("_budget_dims_deltas(self, "), 2)
        self.assertIn('"user"', SOURCE)
        self.assertIn('"reply"', SOURCE)

    def test_schema_entries(self):
        for key in ("dims_delta_limit_enabled", "dims_delta_limit"):
            self.assertIn(key, SCHEMA)
        self.assertTrue(SCHEMA["dims_delta_limit_enabled"]["default"])
        self.assertAlmostEqual(SCHEMA["dims_delta_limit"]["default"], 0.2)
        self.assertEqual(SCHEMA["dims_delta_limit"]["type"], "float")

    def test_method_scales_with_plugin_config(self):
        scaled = BUDGET_METHOD(_FakePlugin(limit=0.2), {"v": 0.6, "a": 0.4},
                               "user")
        self.assertAlmostEqual(sum(abs(x) for x in scaled.values()), 0.2,
                               places=4)

    def test_method_honours_disabled_flag(self):
        deltas = {"v": 0.6, "a": 0.4}
        self.assertEqual(BUDGET_METHOD(_FakePlugin(enabled=False), deltas,
                                       "reply"), deltas)

    def test_method_without_config_uses_default(self):
        scaled = BUDGET_METHOD(types.SimpleNamespace(), {"v": 0.9}, "reply")
        self.assertAlmostEqual(scaled["v"], 0.2, places=4)


if __name__ == "__main__":
    unittest.main()
