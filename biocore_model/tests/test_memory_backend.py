# -*- coding: utf-8 -*-
"""task-146: user-selectable memory backend (json | sqlite | auto)."""
import ast
import json
import tempfile
import types
import unittest
from pathlib import Path

from biocore_model import memory_store as ms

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")
SCHEMA = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
DASH = ROOT / "pages" / "dashboard"
SRC_HTML = (DASH / "index.src.html").read_text(encoding="utf-8")
APP_JS = (DASH / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (DASH / "index.html").read_text(encoding="utf-8")

_HELPER_NAMES = ("_memory_store_module", "_memory_backend_attr",
                 "_json_entries_count", "_init_memory_backend",
                 "_memory_store_handle", "_memory_backend_switch")


def _load_helpers():
    tree = ast.parse(SOURCE)
    nodes = [item for item in tree.body
             if isinstance(item, ast.FunctionDef) and item.name in _HELPER_NAMES]
    log = []
    ns = {"json": json, "Path": Path,
          "logger": types.SimpleNamespace(
              info=lambda *a, **k: log.append(a),
              warning=lambda *a, **k: None,
              debug=lambda *a, **k: None)}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<mem_backend>",
                 "exec"), ns)
    return ns, log


def _load_save_method():
    """AST-load BioCorePlugin._memory_save_doc_for_session (+ its helpers)."""
    tree = ast.parse(SOURCE)
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == "BioCorePlugin")
    method = next(item for item in cls.body
                  if isinstance(item, ast.FunctionDef)
                  and item.name == "_memory_save_doc_for_session")
    clone = ast.FunctionDef(name=method.name, args=method.args, body=method.body,
                            decorator_list=[], returns=method.returns,
                            type_comment=None, lineno=method.lineno,
                            col_offset=method.col_offset,
                            end_lineno=method.end_lineno,
                            end_col_offset=method.end_col_offset)
    import time as _time
    ns = {"json": json, "Path": Path, "time": _time, "MEMORY_DIR": None,
          "logger": types.SimpleNamespace(
              info=lambda *a, **k: None, warning=lambda *a, **k: None,
              debug=lambda *a, **k: None)}
    for name in ("_memory_store_module", "_memory_store_handle",
                 "_json_entries_count"):
        node = next(item for item in tree.body
                    if isinstance(item, ast.FunctionDef) and item.name == name)
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<helper>",
                     "exec"), ns)
    exec(compile(ast.Module(body=[clone], type_ignores=[]), "<save>",
                 "exec"), ns)
    return ns["_memory_save_doc_for_session"], ns


HELPERS, LOG = _load_helpers()


class FakePlugin:
    def __init__(self, setting="auto"):
        self.memory_storage_backend = setting
        self._memory_backend = "json"
        self._memory_store_cache = None


def _doc(name="friend", count=2):
    return {"entries": [{"text": "%s-%d" % (name, i), "ts": float(i)}
                        for i in range(count)]}


def _write_json(memory_dir, name, doc):
    path = Path(memory_dir) / (name + ".json")
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


class NormalizeTest(unittest.TestCase):
    def test_values_and_default(self):
        self.assertEqual(ms.normalize_backend("json"), "json")
        self.assertEqual(ms.normalize_backend("SQLite "), "sqlite")
        self.assertEqual(ms.normalize_backend("auto"), "auto")
        self.assertEqual(ms.normalize_backend("nope"), "auto")
        self.assertEqual(ms.normalize_backend(None), "auto")

    def test_resolve_backend_auto(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ms.resolve_backend("auto", tmp), "json")
            _write_json(tmp, "friend", _doc())
            ms.ensure_store(tmp)
            self.assertEqual(ms.resolve_backend("auto", tmp), "sqlite")
            self.assertEqual(ms.resolve_backend("json", tmp), "json")
            self.assertEqual(ms.resolve_backend("sqlite", tmp), "sqlite")

    def test_healthy_check_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ms.SQLITE_FILE).write_bytes(b"garbage")
            self.assertFalse(ms.db_present_healthy(tmp))
            self.assertEqual(ms.resolve_backend("auto", tmp), "json")


class SwitchTest(unittest.TestCase):
    def test_json_to_sqlite_counts_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_json(tmp, "friend", _doc("friend", 3))
            report = ms.switch_backend("sqlite", tmp)
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["from"], "json")
            self.assertEqual(report["to"], "sqlite")
            self.assertEqual(report["state"], "imported")
            self.assertEqual(report["counts_after"]["entries"], 3)
            self.assertTrue(report["backup"]["dir"])
            self.assertTrue(Path(report["backup"]["dir"]).is_dir())
            self.assertEqual(ms.db_counts(tmp)["entries"], 3)

    def test_switch_idempotent_both_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_json(tmp, "friend", _doc("friend", 2))
            _write_json(tmp, "group", _doc("group", 1))
            first = ms.switch_backend("sqlite", tmp)
            second = ms.switch_backend("sqlite", tmp)
            self.assertEqual(first["counts_after"]["entries"], 3)
            self.assertEqual(second["counts_after"]["entries"], 3)
            self.assertEqual(second["state"], "noop")
            back1 = ms.switch_backend("json", tmp)
            self.assertTrue(back1["ok"], back1)
            self.assertEqual(back1["to"], "json")
            self.assertEqual(back1["counts_after"]["entries"], 3)
            back2 = ms.switch_backend("json", tmp)
            self.assertEqual(back2["counts_after"]["entries"], 3)
            self.assertEqual(ms.json_counts(tmp)["entries"], 3)

    def test_roundtrip_content_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_json(tmp, "friend", _doc("friend", 2))
            ms.switch_backend("sqlite", tmp)
            store = ms.open_store(tmp)
            try:
                before = [e["text"] for e in store.load_doc("friend")["entries"]]
            finally:
                store.close()
            ms.switch_backend("json", tmp)
            doc = json.loads((Path(tmp) / "friend.json").read_text(encoding="utf-8"))
            after = [e["text"] for e in doc["entries"]]
            self.assertEqual(before, after)

    def test_switch_failure_keeps_previous_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_json(tmp, "friend", _doc("friend", 2))
            plugin = FakePlugin("json")
            original = ms.switch_backend

            def boom(*args, **kwargs):
                raise RuntimeError("disk full")

            ms.switch_backend = boom
            try:
                report = HELPERS["_memory_backend_switch"](
                    plugin, "sqlite", tmp)
            finally:
                ms.switch_backend = original
            self.assertFalse(report["ok"])
            self.assertEqual(report["backend"], "json")
            self.assertTrue(report.get("fallback"))
            self.assertEqual(plugin._memory_backend, "json")


class InitHelperTest(unittest.TestCase):
    def test_json_setting_reads_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_json(tmp, "friend", _doc("friend", 3))
            plugin = FakePlugin("json")
            report = HELPERS["_init_memory_backend"](plugin, tmp)
            self.assertEqual(report["backend"], "json")
            self.assertEqual(report["entries"], 3)
            self.assertEqual(plugin._memory_backend, "json")
            self.assertIsNone(plugin._memory_store_cache)

    def test_sqlite_setting_imports_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_json(tmp, "friend", _doc("friend", 2))
            plugin = FakePlugin("sqlite")
            report = HELPERS["_init_memory_backend"](plugin, tmp)
            self.assertEqual(report["backend"], "sqlite")
            self.assertEqual(report["entries"], 2)
            self.assertIsNotNone(plugin._memory_store_cache)
            lines = [" ".join(str(part) for part in row) for row in LOG]
            try:
                self.assertTrue(any(
                    "memory backend=%s entries=%d" in line
                    and str(line).endswith("sqlite 2") for line in lines),
                    lines[-3:])
            finally:
                plugin._memory_store_cache.close()
                plugin._memory_store_cache = None

    def test_auto_setting_follows_db_presence(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_json(tmp, "friend", _doc("friend", 1))
            plugin = FakePlugin("auto")
            first = HELPERS["_init_memory_backend"](plugin, tmp)
            self.assertEqual(first["backend"], "json")
            self.assertEqual(first["entries"], 1)
            ms.switch_backend("sqlite", tmp)
            plugin2 = FakePlugin("auto")
            second = HELPERS["_init_memory_backend"](plugin2, tmp)
            self.assertEqual(second["backend"], "sqlite")
            self.assertEqual(second["entries"], 1)
            plugin2._memory_store_cache.close()

    def test_init_failure_falls_back_to_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_json(tmp, "friend", _doc("friend", 2))
            plugin = FakePlugin("sqlite")
            original = ms.ensure_backend

            def boom(*args, **kwargs):
                raise RuntimeError("no sqlite")

            ms.ensure_backend = boom
            try:
                report = HELPERS["_init_memory_backend"](plugin, tmp)
            finally:
                ms.ensure_backend = original
            self.assertEqual(report["backend"], "json")
            self.assertTrue(report["fallback"])
            self.assertEqual(plugin._memory_backend, "json")
            self.assertEqual(report["entries"], 2)


class FallbackConsistencyTest(unittest.TestCase):
    def test_sqlite_open_failure_recounts_json_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_json(tmp, "friend", _doc("friend", 3))
            plugin = FakePlugin("sqlite")
            original = ms.open_store

            def boom(*args, **kwargs):
                raise RuntimeError("db handle unavailable")

            ms.open_store = boom
            try:
                report = HELPERS["_init_memory_backend"](plugin, tmp)
            finally:
                ms.open_store = original
            self.assertEqual(report["backend"], "json")
            self.assertTrue(report["fallback"])
            self.assertEqual(report["entries"], 3)   # counted from JSON
            self.assertEqual(plugin._memory_backend, "json")

    def test_sqlite_write_failure_degrades_to_json(self):
        save, ns = _load_save_method()

        class BoomStore:
            def save_doc(self, session, doc):
                raise RuntimeError("disk full")

        with tempfile.TemporaryDirectory() as tmp:
            ns["MEMORY_DIR"] = Path(tmp)
            plugin = types.SimpleNamespace(
                _memory_backend="sqlite", _memory_store_cache=BoomStore())
            path = Path(tmp) / "friend.json"
            doc = {"entries": [{"text": "新写入", "ts": 1.0}]}
            save(plugin, path, doc)
            self.assertTrue(path.is_file())
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["entries"][0]["text"], "新写入")
            self.assertEqual(plugin._memory_backend, "json")
            self.assertIsNone(plugin._memory_store_cache)


class WiringTest(unittest.TestCase):
    def test_config_attr_and_startup_call(self):
        self.assertIn('self.config.get("memory_storage_backend", "auto")',
                      SOURCE)
        self.assertIn("_init_memory_backend(", SOURCE)
        self.assertIn("self._memory_backend = \"json\"", SOURCE)

    def test_handler_route_and_log_format(self):
        self.assertIn("async def page_memory_backend", SOURCE)
        self.assertIn("/astrbot_plugin_biocore/page/memory_backend", SOURCE)
        self.assertIn("[biocore] memory backend=%s entries=%d", SOURCE)
        self.assertIn("_memory_backend_switch(self, target, MEMORY_DIR", SOURCE)

    def test_storage_helpers_wired_into_memory_paths(self):
        for marker in ("_memory_store_handle(self, MEMORY_DIR)",
                       "store.save_doc(session, doc)",
                       "store.load_doc(safe)",
                       "store.load_doc(Path(path).stem)",
                       "store.stats()",
                       "store.all_docs()"):
            self.assertIn(marker, SOURCE)

    def test_status_payload_exposes_backend(self):
        self.assertIn('"memory_storage_backend":', SOURCE)
        self.assertIn('"memory_backend":', SOURCE)
        routes = (ROOT / "biocore_model" / "plugin_routes.py").read_text(
            encoding="utf-8")
        self.assertIn('"memory_storage_backend":', routes)

    def test_schema_entry(self):
        cfg = SCHEMA.get("memory_storage_backend") or {}
        self.assertEqual(cfg.get("type"), "string")
        self.assertEqual(cfg.get("default"), "auto")
        self.assertEqual(cfg.get("options"), ["json", "sqlite", "auto"])

    def test_panel_dropdown(self):
        self.assertIn('id="memoryStorageBackend"', SRC_HTML)
        for label in ("JSON 文件", "SQLite 数据库", "自动"):
            self.assertIn(label, SRC_HTML)
        self.assertIn("page/memory_backend", APP_JS)
        self.assertIn("renderMemoryBackend", APP_JS)
        # the inlined dashboard ships the same control
        self.assertIn('id="memoryStorageBackend"', INDEX_HTML)
        self.assertIn("MEM_BACKEND_LABELS", INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
