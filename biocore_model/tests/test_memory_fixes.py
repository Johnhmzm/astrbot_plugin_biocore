# -*- coding: utf-8 -*-
"""Memory fixes: _save_memory forget path, recall dedup, maintenance entries."""
import ast
import json
import tempfile
import types
import unittest
from pathlib import Path

import memory_meta
from biocore_model import bio_tick as bt

MAIN = Path(__file__).resolve().parents[2] / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")


def _load_methods(names, namespace=None):
    tree = ast.parse(SOURCE)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "BioCorePlugin")
    ns = dict(namespace or {})
    fns = {}
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            clone = ast.FunctionDef(name=node.name, args=node.args, body=node.body,
                                    decorator_list=[], returns=node.returns,
                                    type_comment=None, lineno=node.lineno,
                                    col_offset=node.col_offset,
                                    end_lineno=node.end_lineno,
                                    end_col_offset=node.end_col_offset)
            exec(compile(ast.Module(body=[clone], type_ignores=[]), "<mem>", "exec"), ns)
            fns[node.name] = ns[node.name]
    return fns


class SaveMemoryTest(unittest.TestCase):
    def test_save_memory_runs_forget(self):
        with tempfile.TemporaryDirectory() as tmp:
            fns = _load_methods(("_save_memory", "_memory_save_doc_for_session"), {
                "json": json, "time": __import__("time"), "Path": Path,
                "MEMORY_SCHEMA_VERSION": 2,
                "MEMORY_DIR": Path(tmp),
                "logger": types.SimpleNamespace(
                    warning=lambda *a, **k: None, info=lambda *a, **k: None),
            })
            plugin = types.SimpleNamespace(
                _memory_path=lambda event: Path(tmp) / "s1.json")
            plugin._save_memory = types.MethodType(fns["_save_memory"], plugin)
            plugin._memory_save_doc_for_session = types.MethodType(
                fns["_memory_save_doc_for_session"], plugin)
            doc = {"entries": [{"id": "stale", "retrieval_s": 0.001,
                                "last_access_ts": 1.0, "text": "old"}]}
            plugin._save_memory(None, doc)
            saved = json.loads((Path(tmp) / "s1.json").read_text(encoding="utf-8"))
            self.assertTrue(saved["entries"][0].get("hidden"))


class DedupTest(unittest.TestCase):
    def test_same_cluster_keeps_two(self):
        fns = _load_methods(("_dedup_memory_top",), {"memory_meta": memory_meta})
        plugin = types.SimpleNamespace()
        fn = types.MethodType(fns["_dedup_memory_top"], plugin)
        rows = [(0.9, {"text": "今天去海边玩"}),
                (0.8, {"text": "今天去海边玩"}),
                (0.7, {"text": "今天去海边玩"}),
                (0.6, {"text": "完全不同的内容"})]
        out = fn(rows)
        self.assertLessEqual(len(out), 3)
        self.assertEqual(len(out), 3)


class MaintenanceTest(unittest.TestCase):
    def test_entries_are_processed_and_returned(self):
        now = 2_000_000_000.0
        rows = [{"id": "a", "retrieval_s": 0.9, "last_access_ts": now},
                {"id": "b", "retrieval_s": 0.01, "last_access_ts": now}]
        out = bt.memory_maintenance(None, now, dt_hours=1.0, entries=rows)
        self.assertFalse(out.get("skipped"))
        self.assertIn("entries", out)
        self.assertEqual(len(out["entries"]), 2)


if __name__ == "__main__":
    unittest.main()
