# -*- coding: utf-8 -*-
"""Debug-page regression tests: discomfort, needs progress, autonomy drift."""
import ast
import json
import types
import unittest
from pathlib import Path

from biocore_model import autonomy_model as am
from biocore_model import autonomy_tick as at
from biocore_model import bio_tick as bt
from biocore_model import intero_core as ic

MAIN = Path(__file__).resolve().parents[2] / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")


class FakeCore:
    def __init__(self, partial=False):
        self.v = -0.2
        self.a = 0.8
        self.d = 0.4
        self.social = 0.3
        self.stress = 0.7
        self.energy = 0.2
        self.labels = {"emotion": "sadness", "intensity": 0.8}
        self.allostatic_load = 0.5
        self.boredom = 0.4
        self.homeostasis = {"L_int": 0.3}
        self.open_loops = [{"status": "open"}, {"status": "open"}]
        self.open_loops_due = 2
        self.needs = None
        self.sleep_debt = 0.0
        self.last_debt_ts = 0.0
        self.last_bio_tick_ts = 0.0
        self._bio_tick_count = 0
        self.relationship_context = {"state": {"closeness": 0.3, "conflict": 0.6, "repair": 0.1}}
        self.tension = 0.55
        if partial:
            self.intero = {"tension": 0.55}
        else:
            self.intero = {"tension": 0.55, "warmth": 0.6, "heaviness": 0.3, "clarity": 0.7}

    def snapshot(self):
        return {"v": self.v, "a": self.a, "d": self.d, "social": self.social,
                "stress": self.stress, "energy": self.energy,
                "allostatic_load": self.allostatic_load, "boredom": self.boredom,
                "homeostasis": dict(self.homeostasis),
                "open_loops": list(self.open_loops),
                "open_loops_due": self.open_loops_due,
                "labels": dict(self.labels)}


class PartsDriftTest(unittest.TestCase):
    def test_parts_from_state_nonzero_drift(self):
        core = FakeCore()
        rel = {"state": {"closeness": 0.3, "conflict": 0.6, "repair": 0.1}}
        parts = am.parts_from_state(core, rel, now=10000.0,
                                    acc={"last_user_msg_ts": 10000.0 - 7200.0})
        self.assertGreater(parts["social_gap"], 0.0)
        self.assertGreater(parts["stress_load"], 0.0)
        drift = am.drift_value(parts)
        self.assertGreater(drift, 0.02)
        motive = at._compute_motive({}, parts)
        self.assertGreater(motive["drift"], 0.0)

    def test_v_accumulates_with_built_parts(self):
        core = FakeCore()
        parts = am.parts_from_state(core, core.relationship_context, now=10000.0,
                                    acc={"last_user_msg_ts": 10000.0 - 7200.0})
        drift = am.drift_value(parts)
        value = 0.0
        for _ in range(5):
            out = am.step(value, drift, theta=5.0, xi=0.0)
            value = out["V"]
        self.assertGreater(value, 0.02)

    def test_parts_missing_inputs_still_bounded(self):
        parts = am.parts_from_state(object(), {}, now=1.0, acc={})
        self.assertTrue(parts)
        for value in parts.values():
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)


class NeedsProgressTest(unittest.TestCase):
    def test_needs_move_over_ticks(self):
        core = FakeCore()
        first = bt.bio_tick(core, now=100000.0, dt_hours=1.0)
        start = dict(first["log"]["needs"])
        for index in range(5):
            out = bt.bio_tick(core, now=100000.0 + (index + 1) * 3600.0, dt_hours=1.0)
        end = dict(out["log"]["needs"])
        self.assertLess(end["belonging"], start["belonging"])
        self.assertNotEqual(end, start)


class DiscomfortTest(unittest.TestCase):
    def test_tension_055_is_positive(self):
        out = ic.discomfort({"tension": 0.55, "warmth": ic.COMFORT["warmth"],
                             "heaviness": ic.COMFORT["heaviness"],
                             "clarity": ic.COMFORT["clarity"]})
        self.assertGreater(out["total"], 0.0)

    def test_partial_intero_is_null_not_zero(self):
        self.assertIsNone(_page_debug_discomfort({"tension": 0.55}))
        self.assertIsNone(_page_debug_discomfort(None))
        self.assertGreater(_page_debug_discomfort(
            {"tension": 0.55, "warmth": 0.6, "heaviness": 0.3, "clarity": 0.7}), 0.0)


def _load_page_debug():
    tree = ast.parse(SOURCE)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "BioCorePlugin")
    node = next(f for f in cls.body
                if isinstance(f, ast.AsyncFunctionDef) and f.name == "page_debug")
    ns = {"_bc_blocks": types.SimpleNamespace(BLOCKS=[], _enabled_map=lambda plugin: {}),
          "PROFILE_PATH": Path("/p.json"), "DATA_DIR": Path("/d")}
    clone = ast.AsyncFunctionDef(name=node.name, args=node.args, body=node.body,
                                 decorator_list=[], returns=node.returns,
                                 type_comment=None, lineno=node.lineno,
                                 col_offset=node.col_offset, end_lineno=node.end_lineno,
                                 end_col_offset=node.end_col_offset)
    exec(compile(ast.Module(body=[clone], type_ignores=[]), "<page_debug>", "exec"), ns)
    return ns[node.name]


PAGE_DEBUG = _load_page_debug()


def _page_debug_discomfort(intero):
    try:
        if not isinstance(intero, dict):
            return None
        if any(dim not in intero for dim in ic.DIMS):
            return None
        return ic.discomfort(intero).get("total")
    except Exception:
        return None


class PageDebugTest(unittest.IsolatedAsyncioTestCase):
    async def test_page_debug_discomfort_uses_same_intero(self):
        plugin = types.SimpleNamespace(
            cores={"s": FakeCore()}, _life_tick_n=3,
            _bc_blocks=types.SimpleNamespace(BLOCKS=[], _enabled_map=lambda p: {}),
            _load_policy_q=lambda: {}, _policy_pending=None,
            data_dir="/tmp")
        out = await PAGE_DEBUG(plugin)
        self.assertGreater(out["data"]["bio"]["discomfort"], 0.0)

    async def test_partial_intero_returns_null(self):
        plugin = types.SimpleNamespace(
            cores={"s": FakeCore(partial=True)}, _life_tick_n=3,
            _load_policy_q=lambda: {}, _policy_pending=None, data_dir="/tmp")
        out = await PAGE_DEBUG(plugin)
        self.assertIsNone(out["data"]["bio"]["discomfort"])


class WiringStaticTest(unittest.TestCase):
    def test_needs_log_and_parts_wiring(self):
        self.assertIn("[biocore] needs tick %s", SOURCE)
        self.assertIn("_am.parts_from_state(", SOURCE)
        self.assertIn("if all(dim in intero for dim in _ic_debug.DIMS)", SOURCE)


if __name__ == "__main__":
    unittest.main()
