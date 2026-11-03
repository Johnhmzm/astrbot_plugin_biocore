# -*- coding: utf-8 -*-
"""task-146: SQLite memory store + upgrade/degrade compatibility scenarios."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from biocore_model import memory_store as ms

VECTOR = [round((i - 10) / 100.0, 4) for i in range(1024)]


def _doc(name="friend", count=3):
    entries = []
    for index in range(count):
        entries.append({
            "id": "%s%02d" % (name, index),
            "text": "%s 的第 %d 条记忆" % (name, index),
            "role": "user" if index % 2 == 0 else "assistant",
            "ts": 1000.0 + index,
            "importance": 0.5 + index * 0.1,
            "vector": VECTOR,
            "storage_s": 0.45, "retrieval_s": 0.5, "access_count": 2,
            "hits": index, "inhibition": 0.0, "suppression_count": 0,
            "memory_tier": "hot" if index == 0 else "warm",
            "memory_source": "direct", "memory_confidence": 0.7,
            "arousal_at_encoding": 0.4, "hidden": False,
            "tags": ["t%d" % index],
            "unknown_future_field": {"keep": index},
        })
    return {"schema_version": 3, "entries": entries,
            "tombstones": [{"id": "gone", "ts": 1.0, "status": "deleted"}],
            "working_set": ["friend00"], "write_log": [{"op": "ADD"}]}


def _write_json(memory_dir, name, doc):
    path = Path(memory_dir) / (name + ".json")
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


class SchemaTest(unittest.TestCase):
    def test_tables_indexes_and_pragmas(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            try:
                tables = {row[0] for row in store._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                indexes = {row[0] for row in store._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'")}
                for name in ("entries", "session_docs", "meta"):
                    self.assertIn(name, tables)
                for name in ("idx_entries_ts", "idx_entries_importance",
                             "idx_entries_hidden", "idx_entries_tier",
                             "idx_entries_session"):
                    self.assertIn(name, indexes)
                self.assertEqual(store._conn.execute(
                    "PRAGMA journal_mode").fetchone()[0].lower(), "wal")
                self.assertEqual(store._conn.execute(
                    "PRAGMA busy_timeout").fetchone()[0], 5000)
                self.assertEqual(store.schema_version(), ms.SCHEMA_VERSION)
                self.assertIn(ms.TEXT_HASH_INDEX, indexes)
                self.assertTrue(Path(tmp, ms.SQLITE_FILE).is_file())
            finally:
                store.close()


class CrudTest(unittest.TestCase):
    def test_save_load_get_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            try:
                result = store.save_doc("friend", _doc(count=3))
                self.assertEqual(result["entries"], 3)
                self.assertTrue(result["json_mirror"])
                doc = store.load_doc("friend")
                self.assertEqual(len(doc["entries"]), 3)
                self.assertEqual(doc["entries"][0]["text"], "friend 的第 0 条记忆")
                self.assertEqual(store.get_entry("friend", "friend00")["role"],
                                 "user")
                self.assertTrue(store.delete_entry("friend", "friend00"))
                self.assertIsNone(store.get_entry("friend", "friend00"))
                self.assertEqual(store.stats()["entries"], 2)
            finally:
                store.close()

    def test_vector_blob_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            try:
                store.save_doc("friend", _doc(count=1))
                entry = store.load_doc("friend")["entries"][0]
                self.assertEqual(len(entry["vector"]), 1024)
                self.assertAlmostEqual(entry["vector"][0], VECTOR[0], places=9)
                self.assertAlmostEqual(entry["vector"][-1], VECTOR[-1], places=9)
                blob = store._conn.execute(
                    "SELECT vector FROM entries").fetchone()[0]
                self.assertIsInstance(blob, bytes)
                self.assertEqual(len(blob), 1024 * 8)
            finally:
                store.close()

    def test_unknown_fields_and_extras_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            try:
                store.save_doc("friend", _doc(count=1))
                doc = store.load_doc("friend")
                entry = doc["entries"][0]
                self.assertEqual(entry["unknown_future_field"], {"keep": 0})
                self.assertEqual(entry["tags"], ["t0"])
                self.assertEqual(len(doc["tombstones"]), 1)
                self.assertEqual(doc["working_set"], ["friend00"])
                self.assertEqual(doc["write_log"], [{"op": "ADD"}])
            finally:
                store.close()

    def test_identical_text_is_deduped_per_session(self):
        # task-147: same normalized text inside one session is one row; the
        # same text in another session is a separate row (unique per session).
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            try:
                doc = {"entries": [{"text": "同样的话", "ts": 1.0},
                                   {"text": "同样的话", "ts": 2.0}]}
                store.save_doc("s1", doc)
                store.save_doc("s2", {"entries": [{"text": "同样的话", "ts": 3.0}]})
                total = store.stats()["entries"]
                self.assertEqual(total, 2)
                ids = {row[0] for row in store._conn.execute(
                    "SELECT id FROM entries")}
                self.assertEqual(len(ids), 2)
                per_session = {row[0]: row[1] for row in store._conn.execute(
                    "SELECT session, COUNT(*) FROM entries GROUP BY session")}
                self.assertEqual(per_session, {"s1": 1, "s2": 1})
            finally:
                store.close()


class MirrorTest(unittest.TestCase):
    def test_write_updates_json_mirror(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            try:
                store.save_doc("friend", _doc(count=2))
                mirror = Path(tmp) / "friend.json"
                self.assertTrue(mirror.is_file())
                mirrored = json.loads(mirror.read_text(encoding="utf-8"))
                self.assertEqual(len(mirrored["entries"]), 2)
                self.assertTrue(mirrored["entries"][0]["id"])
                store.save_doc("friend", {"entries": []})
                mirrored = json.loads(mirror.read_text(encoding="utf-8"))
                self.assertEqual(mirrored["entries"], [])
            finally:
                store.close()

    def test_hidden_and_tier_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            try:
                store.save_doc("friend", _doc(count=3))
                rows = store._conn.execute(
                    "SELECT memory_tier, hidden FROM entries ORDER BY seq").fetchall()
                self.assertEqual(rows[0][0], "hot")
                self.assertEqual(rows[1][0], "warm")
                self.assertEqual(rows[0][1], 0)
            finally:
                store.close()


class CorruptionTest(unittest.TestCase):
    def test_corrupt_db_recovers_with_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ms.SQLITE_FILE).write_bytes(b"not a sqlite database")
            report = ms.ensure_store(tmp)
            self.assertTrue(report["ok"])
            self.assertTrue(report["recovered"])
            self.assertTrue(Path(tmp, ms.SQLITE_FILE + ".corrupt.bak").is_file())
            store = ms.open_store(tmp)
            try:
                self.assertEqual(store.stats()["entries"], 0)
                store.save_doc("s", {"entries": [{"text": "ok"}]})
                self.assertEqual(store.stats()["entries"], 1)
            finally:
                store.close()

    def test_corrupt_json_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_json(tmp, "friend", _doc(count=2))
            (Path(tmp) / "broken.json").write_text("{not json", encoding="utf-8")
            report = ms.ensure_store(tmp)
            self.assertTrue(report["ok"])
            self.assertEqual(report["entries"], 2)
            self.assertIn("broken.json", report["skipped"])


class MigrationScenarioTest(unittest.TestCase):
    def test_empty_db_with_json_imports(self):
        """场景1：空库 + 有 JSON -> 自动导入，不报错。"""
        with tempfile.TemporaryDirectory() as tmp:
            _write_json(tmp, "friend", _doc("friend", 3))
            _write_json(tmp, "group", _doc("group", 2))
            report = ms.ensure_store(tmp)
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["state"], "imported")
            self.assertEqual(report["sessions"], 2)
            self.assertEqual(report["entries"], 5)
            self.assertTrue(report["backup"]["dir"])
            backup = Path(report["backup"]["dir"])
            self.assertTrue((backup / "friend.json").is_file())
            store = ms.open_store(tmp)
            try:
                self.assertEqual(len(store.load_doc("friend")["entries"]), 3)
                self.assertEqual(len(store.load_doc("group")["entries"]), 2)
            finally:
                store.close()

    def test_db_and_json_both_present_config_wins(self):
        """场景2：有库 + 有 JSON -> 以库为准，不做隐式合并/去重。"""
        with tempfile.TemporaryDirectory() as tmp:
            _write_json(tmp, "friend", _doc("friend", 2))
            first = ms.ensure_store(tmp)
            self.assertEqual(first["entries"], 2)
            # now the JSON gains one extra entry (simulating a stale/other copy)
            _write_json(tmp, "friend", _doc("friend", 5))
            second = ms.ensure_store(tmp)
            self.assertTrue(second["ok"])
            self.assertEqual(second["entries"], 2)   # DB authoritative
            store = ms.open_store(tmp)
            try:
                self.assertEqual(len(store.load_doc("friend")["entries"]), 2)
            finally:
                store.close()

    def test_corrupt_db_with_json_rebuilds(self):
        """场景3：库损坏 + JSON 有数据 -> 备份损坏库并从 JSON 重建。"""
        with tempfile.TemporaryDirectory() as tmp:
            _write_json(tmp, "friend", _doc("friend", 3))
            (Path(tmp) / ms.SQLITE_FILE).write_bytes(b"garbage")
            report = ms.ensure_store(tmp)
            self.assertTrue(report["ok"])
            self.assertTrue(report["recovered"])
            self.assertEqual(report["entries"], 3)
            self.assertTrue(Path(tmp, ms.SQLITE_FILE + ".corrupt.bak").is_file())

    def test_corrupt_json_with_healthy_db_still_reads(self):
        """场景4：JSON 损坏 + 库健康 -> 库可读，损坏 JSON 跳过。"""
        with tempfile.TemporaryDirectory() as tmp:
            _write_json(tmp, "friend", _doc("friend", 2))
            ms.ensure_store(tmp)
            (Path(tmp) / "friend.json").write_text("{broken", encoding="utf-8")
            report = ms.ensure_store(tmp)
            self.assertTrue(report["ok"])
            self.assertEqual(report["entries"], 2)
            store = ms.open_store(tmp)
            try:
                self.assertEqual(len(store.load_doc("friend")["entries"]), 2)
            finally:
                store.close()

    def test_json_only_downgrade_startup(self):
        """场景5：降级兼容（只有 JSON 文件也能启动）。"""
        with tempfile.TemporaryDirectory() as tmp:
            _write_json(tmp, "friend", _doc("friend", 3))
            backend = ms.resolve_backend("auto", tmp)
            self.assertEqual(backend, "json")
            counts = ms.json_counts(tmp)
            self.assertEqual(counts["entries"], 3)
            self.assertFalse(ms.db_present_healthy(tmp))

    def test_migration_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_json(tmp, "friend", _doc("friend", 4))
            first = ms.ensure_store(tmp)
            second = ms.ensure_store(tmp)
            self.assertEqual(first["entries"], 4)
            self.assertEqual(second["entries"], 4)
            self.assertEqual(second["state"], "ok")


class PerfAndPathTest(unittest.TestCase):
    def test_raw_column_does_not_duplicate_vector(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            try:
                store.save_doc("friend", _doc(count=2))
                raws = [row[0] for row in store._conn.execute(
                    "SELECT raw FROM entries")]
                for raw in raws:
                    self.assertNotIn('"vector"', raw)
                entry = store.load_doc("friend")["entries"][0]
                self.assertEqual(len(entry["vector"]), 1024)
                raw_bytes = sum(len(raw) for raw in raws)
                blob_bytes = sum(int(row[0]) for row in store._conn.execute(
                    "SELECT LENGTH(vector) FROM entries"))
                # raw must no longer carry a full copy of the vector data
                self.assertLess(raw_bytes, blob_bytes)
            finally:
                store.close()

    def test_compact_raw_drops_legacy_vector_duplication(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            try:
                store.save_doc("friend", _doc(count=1))
                entry = store.load_doc("friend")["entries"][0]
                store._conn.execute(
                    "UPDATE entries SET raw=? WHERE id=?",
                    (json.dumps(entry), entry["id"]))
                store._conn.commit()
                self.assertEqual(store.compact_raw(), 1)
                raw = store._conn.execute(
                    "SELECT raw FROM entries").fetchone()[0]
                self.assertNotIn('"vector"', raw)
                loaded = store.load_doc("friend")["entries"][0]
                self.assertEqual(len(loaded["vector"]), 1024)
                self.assertEqual(store.compact_raw(), 0)   # idempotent
            finally:
                store.close()

    def test_export_default_path_outside_legacy_glob(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            try:
                store.save_doc("friend", _doc(count=2))
                exported = store.export_json()
                self.assertTrue(Path(exported).is_file())
                self.assertEqual(Path(exported).parent.name, "exports")
                # legacy scanners glob("*.json") on the memory dir itself and
                # must not see the export as a fake session
                counts = ms.json_counts(tmp)
                self.assertEqual(counts, {"sessions": 1, "entries": 2})
            finally:
                store.close()


class ExportImportTest(unittest.TestCase):
    def test_export_import_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            store = ms.open_store(tmp)
            try:
                store.save_doc("friend", _doc(count=3))
                exported = store.export_json()
                self.assertTrue(Path(exported).is_file())
            finally:
                store.close()
            store2 = ms.open_store(other)
            try:
                report = store2.import_json(exported)
                self.assertEqual(report["entries"], 3)
                self.assertEqual(len(store2.load_doc("friend")["entries"]), 3)
                self.assertTrue((Path(other) / "friend.json").is_file())
            finally:
                store2.close()

    def test_restore_from_json_backup(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as backup:
            _write_json(backup, "friend", _doc("friend", 2))
            report = ms.restore(backup, tmp)
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["restored_files"], 1)
            store = ms.open_store(tmp)
            try:
                self.assertEqual(store.stats()["entries"], 2)
                self.assertEqual(len(store.load_doc("friend")["entries"]), 2)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
