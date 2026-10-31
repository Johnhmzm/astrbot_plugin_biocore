# -*- coding: utf-8 -*-
"""Global bio-state hydration: restart without cores still evolves intero/needs."""
import ast
import json
import tempfile
import types
import unittest
from pathlib import Path

from biocore_model import bio_tick as bt
from biocore_model import intero_core as ic
from biocore_model import ui_settings

MAIN = Path(__file__).resolve().parents[2] / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")


def _load_helpers(state_dir):
    tree = ast.parse(SOURCE)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "BioCorePlugin")
    wanted = ("_bio_state_key", "_make_global_bio_core", "_ensure_bio_core",
              "_persist_global_bio_state", "_bio_cores_for_tick")
    ns = {"types": types, "STATE_DIR": Path(state_dir)}
    fns = {}
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            clone = ast.FunctionDef(name=node.name, args=node.args, body=node.body,
                                    decorator_list=[], returns=node.returns,
                                    type_comment=None, lineno=node.lineno,
                                    col_offset=node.col_offset,
                                    end_lineno=node.end_lineno,
                                    end_col_offset=node.end_col_offset)
            exec(compile(ast.Module(body=[clone], type_ignores=[]), "<biohyd>", "exec"), ns)
            fns[node.name] = ns[node.name]
    return fns


class FakePlugin:
    def __init__(self, data_dir, state_dir):
        self.data_dir = str(data_dir)
        self.cores = {}
        self._global_bio_core = None
        self.core_calls = []
        self._fns = _load_helpers(state_dir)
        for name, fn in self._fns.items():
            setattr(self, name, types.MethodType(fn, self))

    def _core(self, event):
        key = str(getattr(event, "unified_msg_origin", ""))
        self.core_calls.append(key)
        dummy = types.SimpleNamespace(umo=key)
        return dummy


class HydrationTest(unittest.TestCase):
    def test_no_cores_creates_global_state_and_ticks(self):
        with tempfile.TemporaryDirectory() as data, tempfile.TemporaryDirectory() as states:
            plugin = FakePlugin(data, states)
            cores = plugin._bio_cores_for_tick()
            self.assertEqual(len(cores), 1)
            core = cores[0]
            now = 100000.0
            for index in range(5):
                bt.bio_tick(core, now + index * 10.0)
                plugin._persist_global_bio_state()
            saved = ui_settings.load(plugin).get("bio_state") or {}
            for dim in ic.DIMS:
                self.assertIn(dim, saved.get("intero") or {})
            self.assertGreater(saved.get("last_bio_tick_ts", 0.0), 0.0)
            self.assertIn("needs", saved)
            discomfort = ic.discomfort(saved["intero"])["total"]
            self.assertIsInstance(discomfort, float)

    def test_global_core_reused_between_ticks(self):
        with tempfile.TemporaryDirectory() as data, tempfile.TemporaryDirectory() as states:
            plugin = FakePlugin(data, states)
            first = plugin._ensure_bio_core()
            second = plugin._ensure_bio_core()
            self.assertIs(first, second)

    def test_hydrates_last_umo_first(self):
        with tempfile.TemporaryDirectory() as data, tempfile.TemporaryDirectory() as states:
            plugin = FakePlugin(data, states)
            ui_settings.save(plugin, {"autonomy": {"accumulator": {
                "last_umo": "platform:private:u1"}}})
            core = plugin._ensure_bio_core()
            self.assertEqual(plugin.core_calls[-1], "platform:private:u1")
            self.assertIn("platform:private:u1", plugin.cores)
            self.assertIs(core, plugin.cores["platform:private:u1"])

    def test_hydrates_newest_state_file_when_no_last_umo(self):
        with tempfile.TemporaryDirectory() as data, tempfile.TemporaryDirectory() as states:
            state = Path(states) / "platform_private_u2.json"
            state.write_text(json.dumps({"v": 0.1, "a": 0.4}), encoding="utf-8")
            plugin = FakePlugin(data, states)
            plugin._ensure_bio_core()
            self.assertEqual(plugin.core_calls[-1], "platform_private_u2")

    def test_existing_cores_win(self):
        with tempfile.TemporaryDirectory() as data, tempfile.TemporaryDirectory() as states:
            plugin = FakePlugin(data, states)
            existing = types.SimpleNamespace(umo="existing")
            plugin.cores = {"existing": existing}
            self.assertIs(plugin._ensure_bio_core(), existing)
            self.assertEqual(plugin._bio_cores_for_tick(), [existing])

    def test_page_debug_uses_global_fallback(self):
        # The source must call _ensure_bio_core when cores is empty.
        self.assertIn("core = self._ensure_bio_core()", SOURCE)
        self.assertIn("_bio_cores_for_tick()", SOURCE)
        self.assertIn("_persist_global_bio_state()", SOURCE)


if __name__ == "__main__":
    unittest.main()
