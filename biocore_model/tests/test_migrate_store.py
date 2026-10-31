# -*- coding: utf-8 -*-
"""Offline tests for biocore_model.migrate_store (temp dirs only)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from biocore_model import migrate_store


def entry(**overrides):
    value = {"id": "abc123", "text": "hello memory", "ts": 1700000000.0, "role": "user",
             "importance": 0.8, "pin": True, "scope": "default", "tags": ["plan"]}
    value.update(overrides)
    return value


class ConvertTest(unittest.TestCase):
    def test_normal_mapping(self):
        core, report = migrate_store.convert([entry()])
        self.assertEqual(report["converted"], 1)
        self.assertEqual(core[0]["id"], "abc123")
        self.assertEqual(core[0]["text"], "hello memory")
        self.assertEqual(core[0]["ts"], 1700000000.0)
        self.assertEqual(core[0]["role"], "user")
        self.assertEqual(core[0]["importance"], 0.8)
        self.assertTrue(core[0]["pin"])
        self.assertEqual(core[0]["tags"], ["plan"])
        self.assertEqual(core[0]["client_scope"], "global")

    def test_defaults_for_missing_optional_fields(self):
        core, _ = migrate_store.convert([{"id": "x", "text": "only text"}])
        self.assertEqual(core[0]["role"], "user")
        self.assertEqual(core[0]["tags"], [])
        self.assertEqual(core[0]["importance"], 0.5)
        self.assertFalse(core[0]["pin"])
        self.assertEqual(core[0]["client_scope"], "global")

    def test_unknown_fields_are_reported_not_dropped_silently(self):
        core, report = migrate_store.convert([entry(vector=[0.1, 0.2], sender_id="42", memory_tier="hot")])
        self.assertEqual(report.get("unmapped_fields", {}).get("vector", 0), 0)
        self.assertEqual(report["vectors_migrated"], 1)
        self.assertEqual(report["unmapped_fields"]["sender_id"], 1)
        self.assertEqual(report["unmapped_fields"]["memory_tier"], 1)
        self.assertIn("vector", core[0])

    def test_missing_text_is_skipped_and_counted(self):
        core, report = migrate_store.convert([{"id": "a", "text": ""}, {"id": "b", "text": "ok"}])
        self.assertEqual(report["converted"], 1)
        self.assertEqual(report["skipped"], 1)
        self.assertEqual(report["missing_required"]["text"], 1)
        self.assertEqual(core[0]["id"], "b")

    def test_empty_and_non_dict_entries(self):
        core, report = migrate_store.convert([])
        self.assertEqual((report["converted"], report["skipped"]), (0, 0))
        core, report = migrate_store.convert([None, "nope", entry()])
        self.assertEqual(report["converted"], 1)
        self.assertEqual(report["skipped"], 2)

    def test_generated_id_is_deterministic(self):
        row = {"text": "no id here", "ts": 1700000001.0, "role": "user"}
        first, report = migrate_store.convert([row])
        second, _ = migrate_store.convert([row])
        self.assertEqual(first[0]["id"], second[0]["id"])
        self.assertEqual(len(first[0]["id"]), 12)
        self.assertEqual(report["generated_ids"], 1)

    def test_scope_mapping(self):
        core, _ = migrate_store.convert([entry(scope="session:dsh-1"), dict(entry(), id="b", scope="default")])
        self.assertEqual(core[0]["client_scope"], "session:dsh-1")
        self.assertEqual(core[1]["client_scope"], "global")

    def test_valid_at_is_carried(self):
        core, _ = migrate_store.convert([entry(valid_at=1700000000.0)])
        self.assertEqual(core[0]["valid_at"], 1700000000.0)

    def test_convert_is_idempotent(self):
        rows = [entry(), entry(id="b", text="second")]
        first, report_first = migrate_store.convert(rows)
        second, report_second = migrate_store.convert(rows)
        self.assertEqual(first, second)
        self.assertEqual(report_first, report_second)


class SourceAndRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store_file = self.root / "memory.json"
        self.store_file.write_text(json.dumps({"entries": [entry()]}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_detect_source_via_env(self):
        with mock.patch.dict(os.environ, {migrate_store.SOURCE_ENV: str(self.store_file)}):
            self.assertEqual(migrate_store.detect_source(), str(self.store_file))

    def test_detect_source_from_launcher_layout(self):
        plugin = self.root / "instances" / "inst1" / "core" / "data" / "plugin_data" / "astrbot_plugin_biocore_standalone"
        memory = plugin / "memory"
        memory.mkdir(parents=True)
        (memory / "a.json").write_text(json.dumps({"entries": [entry()]}), encoding="utf-8")
        with mock.patch.dict(os.environ, {migrate_store.SOURCE_ENV: ""}):
            found = migrate_store.detect_source(candidates=[self.root / "instances"])
        self.assertEqual(found, str(memory))

    def test_detect_source_missing_returns_none(self):
        empty = self.root / "nothing"
        empty.mkdir()
        with mock.patch.dict(os.environ, {migrate_store.SOURCE_ENV: ""}):
            self.assertIsNone(migrate_store.detect_source(candidates=[empty]))

    def test_corrupt_source_reports_and_skips(self):
        corrupt = self.root / "bad.json"
        corrupt.write_text("{ not json", encoding="utf-8")
        result = migrate_store.run(src=str(corrupt))
        self.assertEqual(result["corrupt_files"], 1)
        self.assertEqual(result["error"], "corrupt_source")
        self.assertFalse(result["applied"])

    def test_dry_run_does_not_write(self):
        dst = self.root / "out" / "memory.json"
        result = migrate_store.run(src=str(self.store_file), dst=str(dst), apply=False)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["applied"])
        self.assertFalse(dst.exists())
        self.assertEqual(result["converted"], 1)

    def test_apply_writes_atomically(self):
        dst = self.root / "out" / "memory.json"
        result = migrate_store.run(src=str(self.store_file), dst=str(dst), apply=True)
        self.assertTrue(result["applied"])
        doc = json.loads(dst.read_text(encoding="utf-8"))
        self.assertEqual(len(doc["entries"]), 1)
        self.assertEqual(doc["schema_version"], 1)
        self.assertEqual(list(dst.parent.glob("*.tmp")), [])

    def test_target_non_empty_requires_force(self):
        dst = self.root / "out" / "memory.json"
        dst.parent.mkdir(parents=True)
        dst.write_text(json.dumps({"entries": [{"id": "keep"}]}), encoding="utf-8")
        blocked = migrate_store.run(src=str(self.store_file), dst=str(dst), apply=True)
        self.assertEqual(blocked["error"], "target_not_empty")
        self.assertFalse(blocked["applied"])
        self.assertIn("keep", dst.read_text(encoding="utf-8"))
        forced = migrate_store.run(src=str(self.store_file), dst=str(dst), apply=True, force=True)
        self.assertTrue(forced["applied"])
        self.assertEqual(len(json.loads(dst.read_text(encoding="utf-8"))["entries"]), 1)

    def test_source_not_found_reports_error(self):
        with mock.patch.dict(os.environ, {migrate_store.SOURCE_ENV: ""}):
            result = migrate_store.run(src=str(self.root / "missing" / "memory.json"))
        self.assertEqual(result["error"], "source_not_found")
        self.assertFalse(result["ok"])

    def test_apply_without_target_errors(self):
        result = migrate_store.run(src=str(self.store_file), apply=True)
        self.assertEqual(result["error"], "target_required")

    def test_sample_contains_three_entries_max(self):
        rows = [entry(id=str(index), text="memory " + str(index)) for index in range(5)]
        src = self.root / "many.json"
        src.write_text(json.dumps({"entries": rows}), encoding="utf-8")
        result = migrate_store.run(src=str(src))
        self.assertEqual(result["converted"], 5)
        self.assertEqual(len(result["sample"]), 3)


class VectorMigrationTest(unittest.TestCase):
    def test_vector_is_kept_with_model(self):
        entries = [{"id": "v1", "text": "hello", "vector": [0.1, 0.2, 0.3], "embedding_model": "m1"}]
        core, report = migrate_store.convert(entries)
        self.assertEqual(core[0]["vector"], [0.1, 0.2, 0.3])
        self.assertEqual(core[0]["vector_model"], "m1")
        self.assertEqual(report["vectors_migrated"], 1)
        self.assertEqual(report["vectors_dropped"], 0)

    def test_invalid_vector_is_dropped_and_counted(self):
        entries = [{"id": "v2", "text": "hello", "vector": [0.1, "x", 0.3]}]
        core, report = migrate_store.convert(entries)
        self.assertNotIn("vector", core[0])
        self.assertEqual(report["vectors_dropped"], 1)
        self.assertEqual(report["vectors_migrated"], 0)

    def test_empty_vector_is_dropped(self):
        entries = [{"id": "v3", "text": "hello", "vector": []}]
        core, report = migrate_store.convert(entries)
        self.assertNotIn("vector", core[0])
        self.assertEqual(report["vectors_dropped"], 0)
