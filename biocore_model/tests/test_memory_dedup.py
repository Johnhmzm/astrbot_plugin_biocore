# -*- coding: utf-8 -*-
"""task-147: memory dedupe (text_hash unique key + semantic second pass)."""
import json
import sqlite3
import tempfile
import types
import unittest
from pathlib import Path

from biocore_model import memory_store as ms

VEC_A = [1.0, 0.0, 0.0, 0.0]
VEC_NEAR = [0.92, 0.391918, 0.0, 0.0]      # cosine ~0.92 with VEC_A


def _entry(text, ts=100.0, importance=0.5, hits=1, access=1,
           vector=None, eid=None, **extra):
    entry = {"text": text, "ts": ts, "importance": importance,
             "hits": hits, "access_count": access,
             "vector": list(vector) if vector else None, "role": "user"}
    if eid:
        entry["id"] = eid
    entry.update(extra)
    return entry


def _append_save(store, session, entries):
    """Full-doc save (what main does): keep existing rows, append new entries."""
    doc = store.load_doc(session)
    doc["entries"] = list(doc.get("entries") or []) + list(entries)
    return store.save_doc(session, doc)


def _legacy_db(path, session="s1"):
    """Create a pre-dedupe (schema v4, no text_hash) SQLite file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript("""
CREATE TABLE entries(
    id TEXT PRIMARY KEY, session TEXT NOT NULL, seq INTEGER NOT NULL DEFAULT 0,
    text TEXT, role TEXT, ts REAL, importance REAL, vector BLOB,
    storage_s REAL, retrieval_s REAL, access_count INTEGER, hits INTEGER,
    inhibition REAL, suppression_count INTEGER, memory_tier TEXT,
    memory_source TEXT, memory_confidence REAL, arousal_at_encoding REAL,
    hidden INTEGER, tags TEXT, raw TEXT
);
CREATE TABLE session_docs(session TEXT PRIMARY KEY, doc TEXT, updated_at REAL);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
""")
    return conn


def _insert_legacy(conn, session, rows):
    for seq, entry in enumerate(rows):
        conn.execute(
            "INSERT OR REPLACE INTO entries(id, session, seq, text, role, ts, "
            "importance, vector, access_count, hits, memory_tier, "
            "memory_source, raw) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (entry.get("id") or "e%d" % seq, session, seq,
             entry.get("text"), "user", entry.get("ts", 0.0),
             entry.get("importance", 0.5),
             ms.encode_vector(entry.get("vector")),
             int(entry.get("access_count", 1)), int(entry.get("hits", 0)),
             "warm", "direct",
             json.dumps({k: v for k, v in entry.items() if k != "vector"})))
    conn.commit()


class TextHashTest(unittest.TestCase):
    def test_normalize_and_hash(self):
        self.assertEqual(ms.normalize_text(" 今天 很累！"), "今天很累")
        self.assertEqual(ms.text_hash("今天 很累！"),
                         ms.text_hash("今天很累"))
        self.assertNotEqual(ms.text_hash("今天很累"),
                            ms.text_hash("今天很开心"))

    def test_same_text_written_twice_merges(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            try:
                store.save_doc("s", {"entries": [
                    _entry("今天很累", ts=100.0, importance=0.4, hits=1)]})
                store.save_doc("s", {"entries": [
                    _entry("今天很累", ts=50.0, importance=0.9, hits=2)]})
                self.assertEqual(store.stats()["entries"], 1)
                entry = store.load_doc("s")["entries"][0]
                self.assertEqual(entry["ts"], 50.0)         # earliest
                self.assertAlmostEqual(entry["importance"], 0.9)  # higher
                self.assertEqual(entry["hits"], 3)          # summed
                self.assertEqual(entry["access_count"], 2)
                self.assertTrue(entry["text_hash"])
            finally:
                store.close()

    def test_normalized_duplicate_merges(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            try:
                store.save_doc("s", {"entries": [
                    _entry("今天，很累！"), _entry(" 今天 很累 ") ]})
                self.assertEqual(store.stats()["entries"], 1)
            finally:
                store.close()

    def test_unique_index_blocks_direct_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            try:
                store.save_doc("s", {"entries": [_entry("同一句")]})
                self.assertTrue(store._has_index(ms.TEXT_HASH_INDEX))
                row = store._conn.execute(
                    "SELECT id, text_hash FROM entries").fetchone()
                with self.assertRaises(sqlite3.IntegrityError):
                    store._conn.execute(
                        "INSERT INTO entries(id, session, text_hash) "
                        "VALUES(?,?,?)", ("dup", "s", row[1]))
                    store._conn.commit()
            finally:
                store.close()


class SemanticDedupTest(unittest.TestCase):
    def test_semantic_paraphrase_merges(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            try:
                store.save_doc("s", {"entries": [
                    _entry("我很开心", ts=100.0, vector=[1.0, 0.001, 0, 0])]})
                report = _append_save(store, "s", [
                    _entry("我很开心呀", ts=200.0, vector=[0.999, 0.0, 0, 0])])
                self.assertEqual(store.stats()["entries"], 1)
                self.assertGreaterEqual(report["semantic_merged"], 1)
                entry = store.load_doc("s")["entries"][0]
                self.assertEqual(entry["ts"], 100.0)
                self.assertEqual(entry["hits"], 2)
            finally:
                store.close()

    def test_cosine_090_095_not_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            captured = []
            original = ms.logger
            ms.logger = types.SimpleNamespace(
                info=lambda *a, **k: captured.append(a),
                warning=lambda *a, **k: None,
                debug=lambda *a, **k: None)
            try:
                store.save_doc("s", {"entries": [
                    _entry("我有点开心", vector=VEC_A)]})
                report = _append_save(store, "s", [
                    _entry("我有点开心呢", vector=VEC_NEAR)])
                self.assertEqual(store.stats()["entries"], 2)
                self.assertEqual(report["semantic_merged"], 0)
                self.assertGreaterEqual(report["near_merge"], 1)
                self.assertEqual(ms.cosine(VEC_A, VEC_NEAR) >= 0.90, True)
                self.assertEqual(ms.cosine(VEC_A, VEC_NEAR) < 0.95, True)
                self.assertTrue(any("near-merge" in " ".join(map(str, row))
                                    for row in captured))
            finally:
                ms.logger = original
                store.close()

    def test_doc_internal_duplicates_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            try:
                store.save_doc("s", {"entries": [
                    _entry("同一句"), _entry("同一句。")]})
                self.assertEqual(store.stats()["entries"], 1)
                mirror = json.loads(
                    (Path(tmp) / "s.json").read_text(encoding="utf-8"))
                self.assertEqual(len(mirror["entries"]), 1)
                self.assertIn("text_hash", mirror["entries"][0])
            finally:
                store.close()

    def test_save_is_idempotent_for_same_doc(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            try:
                doc = {"entries": [_entry("一天", ts=10.0, hits=2,
                                          access=3)]}
                store.save_doc("s", doc)
                first = store.load_doc("s")["entries"][0]
                doc2 = {"entries": [_entry("一天", ts=10.0, hits=2,
                                           access=3, id=first["id"])]}
                store.save_doc("s", doc2)
                second = store.load_doc("s")["entries"][0]
                self.assertEqual(store.stats()["entries"], 1)
                self.assertEqual(second["hits"], 2)        # no inflation
                self.assertEqual(second["access_count"], 3)
            finally:
                store.close()


class MergeFieldTest(unittest.TestCase):
    def test_merge_field_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            try:
                store.save_doc("s", {"entries": [
                    _entry("同句", ts=300.0, importance=0.3, hits=1,
                           access=1)]})
                store.save_doc("s", {"entries": [
                    _entry("同句", ts=100.0, importance=0.8, hits=4,
                           access=2)]})
                entry = store.load_doc("s")["entries"][0]
                self.assertEqual(entry["ts"], 100.0)
                self.assertAlmostEqual(entry["importance"], 0.8)
                self.assertEqual(entry["hits"], 5)
                self.assertEqual(entry["access_count"], 3)
            finally:
                store.close()


class MigrationCleanupTest(unittest.TestCase):
    def _rows(self):
        return [
            _entry("今天很累", ts=100.0, importance=0.4, hits=1,
                   access=1, vector=VEC_A),
            _entry("今天很累。", ts=50.0, importance=0.9, hits=2,
                   access=1, vector=VEC_A),
            _entry("我很开心", ts=200.0, importance=0.5, hits=1,
                   access=1, vector=[0.0, 1.0, 0.0, 0.0]),
            _entry("我很开心呀", ts=250.0, importance=0.7, hits=3,
                   access=2, vector=[0.0, 0.999, 0.0, 0.0]),
            _entry("我有点开心", ts=260.0, importance=0.5, hits=1,
                   access=1, vector=VEC_NEAR),
            _entry("别的事", ts=300.0, importance=0.5, hits=1,
                   access=1, vector=[0.0, 0.0, 1.0, 0.0]),
        ]

    def test_migration_merges_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / ms.SQLITE_FILE
            conn = _legacy_db(db)
            try:
                _insert_legacy(conn, "s1", self._rows())
            finally:
                conn.close()
            store = ms.open_store(tmp)
            try:
                report = store.migration_report
                self.assertTrue(report.get("ran"))
                self.assertEqual(report.get("merged_pairs"), 2)
                self.assertEqual(report.get("deleted_rows"), 2)
                self.assertEqual(store.stats()["entries"], 4)
                self.assertTrue(store._has_index(ms.TEXT_HASH_INDEX))
                # rows are merged into the earliest row (ts=50 is e1)
                merged = store.get_entry("s1", "e1")
                self.assertEqual(merged["ts"], 50.0)
                self.assertAlmostEqual(merged["importance"], 0.9)
                self.assertEqual(merged["hits"], 3)
                # 0.90-0.95 pair is kept separate
                self.assertIsNotNone(store.get_entry("s1", "e4"))
            finally:
                store.close()

    def test_migration_backup_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / ms.SQLITE_FILE
            conn = _legacy_db(db)
            try:
                _insert_legacy(conn, "s1", self._rows())
            finally:
                conn.close()
            store = ms.open_store(tmp)
            try:
                backup = store.migration_report.get("backup")
                self.assertTrue(backup)
                self.assertTrue(Path(backup).is_dir())
                self.assertGreater(len(list(Path(backup).iterdir())), 0)
            finally:
                store.close()

    def test_migration_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / ms.SQLITE_FILE
            conn = _legacy_db(db)
            try:
                _insert_legacy(conn, "s1", self._rows())
            finally:
                conn.close()
            store = ms.open_store(tmp)
            try:
                first = store.stats()["entries"]
            finally:
                store.close()
            store = ms.open_store(tmp)
            try:
                self.assertFalse(store.migration_report.get("ran"))
                self.assertEqual(store.stats()["entries"], first)
            finally:
                store.close()


class MirrorSyncTest(unittest.TestCase):
    def test_json_mirror_matches_deduped_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ms.open_store(tmp)
            try:
                store.save_doc("s", {"entries": [
                    _entry("镜像同步"), _entry("镜像同步！")]})
                mirror = json.loads(
                    (Path(tmp) / "s.json").read_text(encoding="utf-8"))
                self.assertEqual(len(mirror["entries"]), 1)
                self.assertEqual(mirror["entries"][0]["text"], "镜像同步")
                self.assertTrue(mirror["entries"][0]["text_hash"])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
