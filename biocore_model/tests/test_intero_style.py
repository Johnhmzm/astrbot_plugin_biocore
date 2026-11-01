# -*- coding: utf-8 -*-
"""P1-2 interoception -> expression style tests (intero_style.py + wiring)."""
import ast
import types
import unittest
from pathlib import Path

from biocore_model import intero_style as ist

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")

# three clearly different felt states
TENSE = {"tension": 0.9, "warmth": 0.15, "heaviness": 0.85, "clarity": 0.3}
WARM = {"tension": 0.1, "warmth": 0.9, "heaviness": 0.1, "clarity": 0.8}
FUZZY = {"tension": 0.45, "warmth": 0.5, "heaviness": 0.3, "clarity": 0.12}


class LevelsTest(unittest.TestCase):
    def test_levels_clamped(self):
        self.assertEqual(ist.levels({"tension": 5, "warmth": -1}),
                         {"tension": 1.0, "warmth": 0.0,
                          "heaviness": 0.0, "clarity": 0.0})

    def test_invalid_intero_is_neutral(self):
        out = ist.style(None)
        self.assertEqual(out["tone"], "")
        self.assertEqual(out["target"], 10)
        self.assertEqual(out["cap"], 30)
        self.assertEqual(ist.initiative(None), 0.5)


class StyleDifferenceTest(unittest.TestCase):
    def test_three_profiles_are_distinguishable(self):
        tense = ist.style(TENSE)
        warm = ist.style(WARM)
        fuzzy = ist.style(FUZZY)
        # length: tense/fuzzy shorter, warm longer
        self.assertLess(tense["cap"], warm["cap"])
        self.assertLess(fuzzy["cap"], warm["cap"])
        self.assertLess(tense["target"], warm["target"])
        # tone: each profile gets its own directive
        self.assertIn("情绪", tense["tone"])
        self.assertIn("亲近", warm["tone"])
        self.assertIn("确认", fuzzy["tone"])
        self.assertEqual(len({tense["tone"], warm["tone"], fuzzy["tone"]}), 3)
        # length factor monotone: tense < fuzzy < warm
        self.assertLess(tense["factor"], fuzzy["factor"])
        self.assertLess(fuzzy["factor"], warm["factor"])

    def test_initiative_ordering(self):
        tense = ist.initiative(TENSE)
        fuzzy = ist.initiative(FUZZY)
        warm = ist.initiative(WARM)
        self.assertLess(tense, fuzzy)
        self.assertLess(fuzzy, warm)
        self.assertGreaterEqual(tense, 0.0)
        self.assertLessEqual(warm, 1.0)

    def test_tension_and_heaviness_shorten(self):
        self.assertLess(ist.length_factor(TENSE), 1.0)
        only_tense = ist.style({"tension": 1.0}, target=10, cap=30)
        self.assertLess(only_tense["cap"], 30)
        only_heavy = ist.style({"heaviness": 1.0}, target=10, cap=30)
        self.assertLess(only_heavy["cap"], 30)

    def test_warmth_lengthens(self):
        warm = ist.style(WARM, target=10, cap=30)
        self.assertGreater(warm["cap"], 30)
        self.assertGreater(warm["target"], 10)

    def test_low_clarity_asks_to_confirm(self):
        self.assertIn("确认", ist.tone({"clarity": 0.1}))
        self.assertEqual(ist.tone({"clarity": 0.9}), "")

    def test_bounds_and_floor(self):
        out = ist.style(TENSE, target=1, cap=1)
        self.assertGreaterEqual(out["target"], ist.MIN_TARGET)
        self.assertGreaterEqual(out["cap"], out["target"])
        self.assertLessEqual(out["cap"], ist.MAX_CAP)
        tiny = ist.style({"tension": 1.0, "heaviness": 1.0}, target=10,
                         cap=30)
        self.assertGreaterEqual(tiny["cap"], ist.MIN_CAP)

    def test_deterministic(self):
        self.assertEqual(ist.style(WARM), ist.style(dict(WARM)))


def _load_intero_helper():
    tree = ast.parse(SOURCE)
    node = next(item for item in tree.body
                if isinstance(item, ast.FunctionDef)
                and item.name == "_intero_style")
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
                 "<_intero_style>", "exec"), ns)
    return ns[node.name]


HELPER = _load_intero_helper()


class FakeCore:
    def __init__(self, intero):
        self.intero = intero


class WiringTest(unittest.TestCase):
    def test_main_wiring_markers(self):
        self.assertIn("def _intero_style(core, target, cap)", SOURCE)
        self.assertIn("_intero_style(", SOURCE)
        self.assertIn("intero_style as _intero", SOURCE)
        self.assertIn("expression_style", SOURCE)
        self.assertGreaterEqual(SOURCE.count("_istyle = _intero_style("), 2)

    def test_helper_applies_and_exposes_style(self):
        core = FakeCore(TENSE)
        out = HELPER(core, 10, 30)
        self.assertEqual(out["tone"], ist.style(TENSE)["tone"])
        self.assertLess(out["cap"], 30)
        self.assertEqual(core.expression_style["tone"], out["tone"])

    def test_helper_failure_is_identity(self):
        class BoomCore:
            @property
            def intero(self):
                raise RuntimeError("boom")

        core = BoomCore()
        out = HELPER(core, 12, 32)
        self.assertEqual(out["target"], 12)
        self.assertEqual(out["cap"], 32)
        self.assertEqual(out["tone"], "")


if __name__ == "__main__":
    unittest.main()
