# -*- coding: utf-8 -*-
"""task-134 addendum: SQLite graph storage tests (temp dirs only)."""
import json
import sqlite3
import tempfile
import types
import unittest
from pathlib import Path

from biocore_model import entity_graph as eg
from biocore_model import migrate


def _store(tmp, name="graph"):
    return eg.open_store(Path(tmp) / name / eg.SQLITE_FILE)


class SqliteSchemaTest(unittest.TestCase):
    def test_tables_indexes_and_pragmas(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                tables = {row[0] for row in store._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                indexes = {row[0] for row in store._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'")}
                self.assertIn("entities", tables)
                self.assertIn("edges", tables)
                for key in ("idx_entities_name", "idx_edges_src",
                            "idx_edges_dst", "idx_edges_ts", "idx_edges_rel"):
                    self.assertIn(key, indexes)
                self.assertEqual(store._conn.execute(
                    "PRAGMA journal_mode").fetchone()[0].lower(), "wal")
                self.assertEqual(store._conn.execute(
                    "PRAGMA synchronous").fetchone()[0], 1)  # NORMAL
                self.assertEqual(store._conn.execute(
                    "PRAGMA busy_timeout").fetchone()[0], 5000)
                self.assertTrue(store.path.is_file())
            finally:
                store.close()

    def test_entity_crud_and_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                store, eid = eg.upsert_entity(store, "小夏", type="person",
                                              aliases=["夏夏"], now=100.0,
                                              entry_id="m1")
                found = eg.search(store, "夏夏来了")
                self.assertEqual([row["name"] for row in found], ["小夏"])
                row = store._find_entity("小夏")
                self.assertEqual(row["id"], eid)
                self.assertEqual(row["type"], "person")
                self.assertEqual(row["first_seen"], 100.0)
                self.assertIn("夏夏", row["aliases"])
                self.assertEqual(row["sources"], ["m1"])
            finally:
                store.close()

    def test_entity_dedupe_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                _, e1 = eg.upsert_entity(store, "Xiao Xia")
                _, e2 = eg.upsert_entity(store, " xiao  xia ")
                self.assertEqual(e1, e2)
                self.assertEqual(eg.stats(store)["entities"], 1)
            finally:
                store.close()

    def test_alias_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                _, e1 = eg.upsert_entity(store, "小夏", aliases=["夏夏"])
                _, e2 = eg.upsert_entity(store, "夏夏", type="person")
                self.assertEqual(e1, e2)
                row = store._find_entity("小夏")
                self.assertEqual(row["aliases"].count("夏夏"), 1)
                self.assertEqual(row["type"], "person")
            finally:
                store.close()


class SqliteQueryTest(unittest.TestCase):
    def test_edge_crud_and_dedupe(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                store, r1 = eg.upsert_edge(store, "a", "knows", "b", ts=5.0,
                                           confidence=0.4)
                store, r2 = eg.upsert_edge(store, "a", "knows", "b", ts=5.0,
                                           confidence=0.9, source_entry="m2")
                self.assertEqual(r1, r2)
                stats = eg.stats(store)
                self.assertEqual(stats["edges"], 1)
                row = store._conn.execute(
                    "SELECT confidence, source_entry FROM edges").fetchone()
                self.assertEqual(row[0], 0.9)
                self.assertEqual(row[1], "m2")
            finally:
                store.close()

    def test_two_hop_cte(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                eg.upsert_edge(store, "a", "r1", "b", ts=10.0)
                eg.upsert_edge(store, "b", "r2", "c", ts=11.0)
                eg.upsert_edge(store, "c", "r3", "d", ts=12.0)
                two = eg.neighbors(store, "a", hops=2)
                self.assertEqual({row["name"] for row in two["entities"]},
                                 {"a", "b", "c"})
                self.assertEqual(len(two["edges"]), 2)
                one = eg.neighbors(store, "a", hops=1)
                self.assertEqual({row["name"] for row in one["entities"]},
                                 {"a", "b"})
            finally:
                store.close()

    def test_time_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                eg.upsert_edge(store, "a", "old", "b", ts=100.0)
                eg.upsert_edge(store, "a", "new", "c", ts=900000.0)
                now = 1000000.0
                recent = eg.neighbors(store, "a", hops=1, window_days=7,
                                      now=now)
                self.assertEqual({row["name"] for row in recent["entities"]},
                                 {"a", "c"})
                self.assertEqual(len(recent["edges"]), 1)
                self.assertEqual(len(eg.neighbors(store, "a", hops=1,
                                                  now=now)["edges"]), 2)
            finally:
                store.close()

    def test_unknown_entity_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                self.assertEqual(eg.neighbors(store, "nobody")["entities"], [])
                self.assertEqual(eg.search(store, "nobody"), [])
            finally:
                store.close()

    def test_search_length_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                eg.upsert_entity(store, "夏")
                eg.upsert_entity(store, "小夏")
                names = [row["name"] for row in eg.search(store, "小夏在吗")]
                self.assertEqual(names[0], "小夏")
                self.assertIn("夏", names)
            finally:
                store.close()

    def test_stats_aggregation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                eg.upsert_entity(store, "a", type="person", aliases=["AA"])
                eg.upsert_edge(store, "a", "r", "b", ts=42.0)
                stats = eg.stats(store)
                self.assertEqual(stats["entities"], 2)
                self.assertEqual(stats["edges"], 1)
                self.assertEqual(stats["types"].get("person"), 1)
                self.assertEqual(stats["aliases"], 1)
                self.assertEqual(stats["latest_ts"], 42.0)
            finally:
                store.close()

    def test_corrupt_db_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph" / eg.SQLITE_FILE
            path.parent.mkdir(parents=True)
            path.write_bytes(b"not a sqlite database")
            store = eg.open_store(path)
            try:
                self.assertEqual(eg.stats(store)["entities"], 0)
                eg.upsert_entity(store, "x", now=1.0)
                self.assertEqual(eg.stats(store)["entities"], 1)
                self.assertTrue(path.with_name(path.name + ".corrupt.bak")
                                .is_file())
            finally:
                store.close()

    def test_export_import_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _store(tmp, "a")
            try:
                eg.upsert_edge(src, "a", "r", "b", ts=7.0, confidence=0.7)
                json_path = Path(tmp) / "a" / "graph.json"
                src.export_json(json_path)
                payload = json.loads(json_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["schema"], 3)
                self.assertEqual(len(payload["edges"]), 1)
            finally:
                src.close()
            dst = _store(tmp, "b")
            try:
                imported = dst.import_json(Path(tmp) / "a" / "graph.json")
                self.assertEqual(imported["edges"], 1)
                self.assertEqual(eg.stats(dst)["edges"], 1)
            finally:
                dst.close()


def _host(tmp, version=2):
    data = Path(tmp) / "plugins" / "astrbot_plugin_biocore" / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "ui_settings.json").write_text(
        json.dumps({"schema": 1, "schema_version": version}),
        encoding="utf-8")
    host = types.SimpleNamespace(data_dir=str(data))
    authority = Path(tmp) / "plugin_data" / "astrbot_plugin_biocore"
    return host, authority


class MigrationSqliteTest(unittest.TestCase):
    def test_migrate_imports_legacy_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, authority = _host(tmp)
            graph_dir = authority / "graph"
            graph_dir.mkdir(parents=True)
            seed = eg.empty_graph()
            seed, _ = eg.upsert_edge(seed, "小夏", "planned", "体检", ts=9.0)
            eg.save_graph(graph_dir / "graph.json", seed)
            report = migrate.migrate(host)
            self.assertEqual(report["stats"].get("graph"), "imported")
            store = eg.open_store(graph_dir / eg.SQLITE_FILE)
            try:
                self.assertEqual(eg.stats(store)["edges"], 1)
            finally:
                store.close()
            self.assertTrue((graph_dir / "graph.json").is_file())

    def test_migrate_is_idempotent_with_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, authority = _host(tmp)
            migrate.migrate(host)
            graph_dir = authority / "graph"
            db = graph_dir / eg.SQLITE_FILE
            before = db.read_bytes()
            second = migrate.migrate(host)
            self.assertTrue(second["stats"].get("already"))
            self.assertEqual(db.read_bytes(), before)

    def test_migrate_recovers_corrupt_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, authority = _host(tmp)
            graph_dir = authority / "graph"
            graph_dir.mkdir(parents=True)
            (graph_dir / eg.SQLITE_FILE).write_bytes(b"garbage-db")
            report = migrate.migrate(host)
            self.assertEqual(report["stats"].get("graph"), "recovered")
            self.assertTrue((graph_dir / (eg.SQLITE_FILE + ".corrupt.bak"))
                            .is_file())
            store = eg.open_store(graph_dir / eg.SQLITE_FILE)
            try:
                self.assertEqual(eg.stats(store)["entities"], 0)
            finally:
                store.close()

    def test_backup_and_restore_sqlite_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, authority = _host(tmp)
            migrate.migrate(host)
            graph_dir = authority / "graph"
            store = eg.open_store(graph_dir / eg.SQLITE_FILE)
            try:
                eg.upsert_edge(store, "a", "r", "b", ts=1.0)
                store.checkpoint()
            finally:
                store.close()
            # force a second migration to produce a fresh backup with the graph
            from biocore_model import ui_settings
            auth = authority / ui_settings.FILE_NAME
            settings = json.loads(auth.read_text(encoding="utf-8"))
            settings["schema_version"] = 2
            auth.write_text(json.dumps(settings), encoding="utf-8")
            report = migrate.migrate(host)
            backup = Path(report["backup_dir"])
            self.assertTrue((backup / "graph" / eg.SQLITE_FILE).is_file())
            self.assertTrue((backup / "graph" / "graph.json").is_file())
            (graph_dir / eg.SQLITE_FILE).write_bytes(b"broken")
            result = migrate.restore(str(backup), host)
            self.assertGreaterEqual(result["restored"]["graph"], 1)
            store = eg.open_store(graph_dir / eg.SQLITE_FILE)
            try:
                self.assertEqual(eg.stats(store)["edges"], 1)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
