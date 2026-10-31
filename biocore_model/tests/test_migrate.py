# -*- coding: utf-8 -*-
"""Real old-layout migration test: 1.3.4 data -> 1.4.0, then idempotency."""
import ast
import json
import logging
import os
import tempfile
import time
import types
import unittest
from pathlib import Path

from biocore_model import migrate


class FakePlugin:
    def __init__(self, data_dir):
        self.data_dir = str(data_dir)

    def _autonomy_params(self):
        return {"theta": 0.5239, "cooldown_s": 1625, "daily_cap": 3,
                "tau_hours": 16.0}


def _old_layout(root):
    data = Path(root) / "plugins" / "astrbot_plugin_biocore" / "data"
    (data / "memory").mkdir(parents=True, exist_ok=True)
    (data / "states").mkdir(parents=True, exist_ok=True)
    (data / "ui_settings.json").write_text(json.dumps({
        "autonomy": {"enabled": True, "threshold": 0.7,
                     "accumulator": {"V": -0.16, "drift": 0.02,
                                     "last_tick_ts": 123.0}},
        "proactive_autonomy_threshold": 0.7,
        "proactive_autonomy_max_chars": 120,
        "schema": 1,
    }, ensure_ascii=False), encoding="utf-8")
    mem = data / "memory" / "s1.json"
    mem.write_text(json.dumps({"entries": [
        {"id": "m1", "text": "老记忆一"},
        {"id": "m2", "text": "老记忆二"},
        {"id": "m3", "text": "老记忆三"},
    ]}, ensure_ascii=False), encoding="utf-8")
    old = time.time() - 10 * 86400
    os.utime(mem, (old, old))
    (data / "states" / "u1.json").write_text(
        json.dumps({"umo": "user-x"}), encoding="utf-8")
    return data


def _load_methods(names, namespace=None):
    source = (Path(__file__).resolve().parents[2] / "main.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
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
            exec(compile(ast.Module(body=[clone], type_ignores=[]), "<mig>", "exec"), ns)
            fns[node.name] = ns[node.name]
    return fns

class MigrationTest(unittest.TestCase):
    def test_old_data_migrates_and_backfills(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _old_layout(tmp)
            plugin = FakePlugin(data)
            with self.assertLogs(migrate.logger, level="INFO") as logs:
                report = migrate.migrate(plugin)
            self.assertEqual(report["applied"],
                             ["settings", "accumulator", "memory"])
            auth = (Path(tmp) / "plugin_data" / "astrbot_plugin_biocore"
                    / "ui_settings.json")
            saved = json.loads(auth.read_text(encoding="utf-8"))
            self.assertEqual(saved.get("schema_version"), 2)
            acc = saved["autonomy"]["accumulator"]
            self.assertAlmostEqual(float(acc["theta"]), 0.5239, places=3)
            self.assertGreaterEqual(float(acc["V"]), 0.0)
            self.assertEqual(acc["cooldown_seconds"], 1625)
            self.assertEqual(acc["daily_cap"], 3)
            self.assertEqual(acc["last_umo"], "user-x")
            mem = json.loads((data / "memory" / "s1.json").read_text(
                encoding="utf-8"))
            self.assertEqual(len(mem["entries"]), 3)
            for entry in mem["entries"]:
                self.assertIn("storage_s", entry)
                self.assertIn("retrieval_s", entry)
                self.assertIn("access_count", entry)
                self.assertIn("arousal_at_encoding", entry)
                self.assertFalse(entry["hidden"])
                self.assertGreater(entry["storage_s"], 0.0)
            # Old 10-day file -> power-law retrieval below a fresh file.
            self.assertLess(mem["entries"][0]["retrieval_s"], 0.5)
            joined = "\n".join(logs.output)
            for token in ("migrate done:", "settings=", "accumulator=",
                          "memory=", "warnings="):
                self.assertIn(token, joined)

    def test_schema_version_survives_ui_settings_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _old_layout(tmp)
            plugin = FakePlugin(data)
            migrate.migrate(plugin)
            from biocore_model import ui_settings
            ui_settings.save(plugin, {"autonomy": {"send": True}})
            auth = (Path(tmp) / "plugin_data" / "astrbot_plugin_biocore"
                    / "ui_settings.json")
            saved = json.loads(auth.read_text(encoding="utf-8"))
            self.assertEqual(saved.get("schema_version"), 2)
            self.assertEqual(migrate.migrate(plugin)["applied"], [])

    def test_second_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _old_layout(tmp)
            plugin = FakePlugin(data)
            migrate.migrate(plugin)
            auth = (Path(tmp) / "plugin_data" / "astrbot_plugin_biocore"
                    / "ui_settings.json")
            mem = data / "memory" / "s1.json"
            before_settings = auth.read_bytes()
            before_mem = mem.read_bytes()
            report = migrate.migrate(plugin)
            self.assertEqual(report["applied"], [])
            self.assertEqual(auth.read_bytes(), before_settings)
            self.assertEqual(mem.read_bytes(), before_mem)

    def test_fresh_install_is_noop_and_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            fresh = Path(tmp) / "plugin_data" / "astrbot_plugin_biocore"
            fresh.mkdir(parents=True)
            plugin = FakePlugin(fresh)
            report = migrate.migrate(plugin)
            self.assertEqual(report["applied"], [])
            self.assertEqual(report["warnings"], [])
            auth = fresh / "ui_settings.json"
            self.assertTrue(auth.is_file())
            self.assertEqual(json.loads(auth.read_text(encoding="utf-8"))
                             .get("schema_version"), 2)


if __name__ == "__main__":
    unittest.main()

class HardeningTest(unittest.TestCase):
    def test_atomic_write_failure_leaves_no_tmp_or_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "x.json"
            target.write_text('{"old": 1}', encoding="utf-8")
            from unittest import mock
            with mock.patch.object(migrate.os, "replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    migrate._write(target, {"new": 2})
            self.assertEqual(target.read_text(encoding="utf-8"), '{"old": 1}')
            self.assertFalse((Path(tmp) / "x.json.tmp").exists())

    def test_backup_contains_three_classes_and_migrates(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _old_layout(tmp)
            plugin = FakePlugin(data)
            report = migrate.migrate(plugin)
            backup = Path(report["backup_dir"])
            self.assertTrue(backup.is_dir())
            self.assertTrue((backup / "settings" / "ui_settings.json").is_file())
            self.assertEqual(len(list((backup / "memory").glob("*.json"))), 1)
            self.assertEqual(len(list((backup / "states").glob("*.json"))), 1)
            self.assertIn("memory", report["applied"])

    def test_failed_migration_keeps_old_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _old_layout(tmp)
            old_legacy = (data / "ui_settings.json").read_bytes()
            plugin = FakePlugin(data)
            from unittest import mock
            with mock.patch.object(migrate, "_write", side_effect=OSError("disk")):
                report = migrate.migrate(plugin)
            self.assertTrue(report["warnings"])
            self.assertEqual((data / "ui_settings.json").read_bytes(), old_legacy)
            auth = Path(tmp) / "plugin_data" / "astrbot_plugin_biocore" / "ui_settings.json"
            self.assertFalse(auth.exists())

    def test_restore_brings_backup_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _old_layout(tmp)
            plugin = FakePlugin(data)
            report = migrate.migrate(plugin)
            backup = report["backup_dir"]
            auth = (Path(tmp) / "plugin_data" / "astrbot_plugin_biocore"
                    / "ui_settings.json")
            auth.write_text("{}", encoding="utf-8")
            mem = data / "memory" / "s1.json"
            mem.write_text("{}", encoding="utf-8")
            result = migrate.restore(backup, plugin)
            self.assertTrue(result["ok"])
            restored = json.loads(auth.read_text(encoding="utf-8"))
            self.assertIn("autonomy", restored)
            self.assertIn("entries", json.loads(mem.read_text(encoding="utf-8")))
            self.assertGreaterEqual(result["restored"]["states"], 1)

    def test_retry_path_runs_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _old_layout(tmp)
            plugin = FakePlugin(data)
            ns = {"time": time, "logger": types.SimpleNamespace(
                warning=lambda *a, **k: None, info=lambda *a, **k: None)}
            fns = _load_methods(("_migration_payload", "_ensure_migration_retry_once"),
                                namespace=ns)
            for name, fn in fns.items():
                setattr(plugin, name, types.MethodType(fn, plugin))
            plugin._migration_retry_done = False
            plugin._migration_report = {}
            payload = plugin._ensure_migration_retry_once()
            self.assertGreaterEqual(payload["schema_version"], 2)
            first = (data / "ui_settings.json").read_bytes()
            plugin._ensure_migration_retry_once()
            self.assertEqual((data / "ui_settings.json").read_bytes(), first)

