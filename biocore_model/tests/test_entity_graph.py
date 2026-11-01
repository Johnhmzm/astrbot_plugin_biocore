# -*- coding: utf-8 -*-
"""task-134: full entity graph + migration v3 tests."""
import json
import tempfile
import types
import unittest
from pathlib import Path

from biocore_model import entity_graph as eg
from biocore_model import migrate, ui_settings


def _host(tmp, version=2):
    data = Path(tmp) / "plugins" / "astrbot_plugin_biocore" / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "ui_settings.json").write_text(
        json.dumps({"schema": 1, "schema_version": version}),
        encoding="utf-8")
    host = types.SimpleNamespace(data_dir=str(data))
    authority = Path(tmp) / "plugin_data" / "astrbot_plugin_biocore"
    return host, authority


class GraphModelTest(unittest.TestCase):
    def test_empty_and_normalize_invalid(self):
        graph = eg.empty_graph()
        self.assertEqual(graph["schema"], 3)
        self.assertEqual(eg.normalize_graph(None), graph)
        self.assertEqual(eg.normalize_graph("x")["entities"], [])
        dirty = {"schema": "x", "entities": [None, {"name": ""}, {"name": "x"}],
                 "edges": [None, {"src": "a", "dst": "b", "rel": "r"}]}
        clean = eg.normalize_graph(dirty)
        self.assertEqual(len(clean["entities"]), 1)
        self.assertEqual(clean["edges"], [])  # dangling edge dropped

    def test_upsert_entity_fields_and_last_seen(self):
        graph, eid = eg.upsert_entity(eg.empty_graph(), "小夏", type="person",
                                      now=100.0)
        row = eg.find_entity(graph, "小夏")
        self.assertEqual(row["id"], eid)
        self.assertEqual(row["type"], "person")
        self.assertEqual(row["first_seen"], 100.0)
        graph, eid2 = eg.upsert_entity(graph, "小夏", now=200.0)
        self.assertEqual(eid, eid2)
        row = eg.find_entity(graph, "小夏")
        self.assertEqual(row["first_seen"], 100.0)
        self.assertEqual(row["last_seen"], 200.0)
        self.assertEqual(len(graph["entities"]), 1)

    def test_dedupe_ignores_case_and_spaces(self):
        graph, eid = eg.upsert_entity(eg.empty_graph(), "Xiao Xia")
        graph, eid2 = eg.upsert_entity(graph, " xiao  xia ")
        self.assertEqual(eid, eid2)
        self.assertEqual(len(graph["entities"]), 1)

    def test_alias_merge(self):
        graph, eid = eg.upsert_entity(eg.empty_graph(), "小夏",
                                      aliases=["夏夏", "小夏"])
        graph, eid2 = eg.upsert_entity(graph, "夏夏")
        self.assertEqual(eid, eid2)
        row = eg.find_entity(graph, "夏夏")
        self.assertIn("夏夏", row["aliases"])
        self.assertEqual(row["aliases"].count("夏夏"), 1)
        self.assertNotIn("小夏", row["aliases"])

    def test_upsert_edge_creates_entities(self):
        graph, rid = eg.upsert_edge(eg.empty_graph(), "小夏", "planned", "体检",
                                    ts=1000.0, confidence=0.8,
                                    source_entry="m1")
        self.assertTrue(rid)
        edge = graph["edges"][0]
        self.assertEqual(edge["rel"], "planned")
        self.assertEqual(edge["ts"], 1000.0)
        self.assertEqual(edge["confidence"], 0.8)
        self.assertEqual(edge["source_entry"], "m1")
        self.assertEqual(len(graph["entities"]), 2)

    def test_edge_dedupe_same_ts_keeps_max_confidence(self):
        graph, rid = eg.upsert_edge(eg.empty_graph(), "a", "knows", "b", ts=5.0,
                                    confidence=0.4)
        graph, rid2 = eg.upsert_edge(graph, "a", "knows", "b", ts=5.0,
                                     confidence=0.9)
        self.assertEqual(rid, rid2)
        self.assertEqual(len(graph["edges"]), 1)
        self.assertEqual(graph["edges"][0]["confidence"], 0.9)

    def test_two_hop_neighbors(self):
        graph = eg.empty_graph()
        graph, _ = eg.upsert_edge(graph, "a", "r1", "b", ts=10.0)
        graph, _ = eg.upsert_edge(graph, "b", "r2", "c", ts=11.0)
        graph, _ = eg.upsert_edge(graph, "c", "r3", "d", ts=12.0)
        two = eg.neighbors(graph, "a", hops=2)
        names = {row["name"] for row in two["entities"]}
        self.assertEqual(names, {"a", "b", "c"})
        self.assertEqual(len(two["edges"]), 2)
        one = eg.neighbors(graph, "a", hops=1)
        self.assertEqual({row["name"] for row in one["entities"]}, {"a", "b"})

    def test_neighbors_window_days(self):
        graph = eg.empty_graph()
        graph, _ = eg.upsert_edge(graph, "a", "old", "b", ts=100.0)
        graph, _ = eg.upsert_edge(graph, "a", "new", "c", ts=900000.0)
        now = 1000000.0
        recent = eg.neighbors(graph, "a", hops=1, window_days=7, now=now)
        self.assertEqual({row["name"] for row in recent["entities"]},
                         {"a", "c"})
        self.assertEqual(len(recent["edges"]), 1)
        all_time = eg.neighbors(graph, "a", hops=1, now=now)
        self.assertEqual(len(all_time["edges"]), 2)

    def test_neighbors_unknown_entity_is_empty(self):
        self.assertEqual(eg.neighbors(eg.empty_graph(), "nobody")["entities"],
                         [])

    def test_search_by_name_and_alias(self):
        graph = eg.empty_graph()
        graph, _ = eg.upsert_entity(graph, "小夏", aliases=["夏夏"])
        graph, _ = eg.upsert_entity(graph, "海边计划")
        names = [row["name"] for row in eg.search(graph, "夏夏说海边计划真好")]
        self.assertIn("小夏", names)
        self.assertIn("海边计划", names)
        self.assertEqual(eg.search(graph, ""), [])

    def test_stats(self):
        graph = eg.empty_graph()
        graph, _ = eg.upsert_entity(graph, "a", type="person", aliases=["AA"])
        graph, _ = eg.upsert_edge(graph, "a", "r", "b", ts=42.0)
        out = eg.stats(graph)
        self.assertEqual(out["entities"], 2)
        self.assertEqual(out["edges"], 1)
        self.assertEqual(out["types"].get("person"), 1)
        self.assertEqual(out["aliases"], 1)
        self.assertEqual(out["latest_ts"], 42.0)

    def test_save_load_roundtrip_and_corrupt_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph" / "graph.json"
            graph = eg.empty_graph()
            graph, _ = eg.upsert_edge(graph, "a", "r", "b", ts=1.0)
            eg.save_graph(path, graph)
            loaded = eg.load_graph(path)
            self.assertEqual(len(loaded["entities"]), 2)
            self.assertEqual(len(loaded["edges"]), 1)
            self.assertFalse((path.parent / "graph.json.tmp").exists())
            path.write_text("{not json", encoding="utf-8")
            recovered = eg.load_graph(path)
            self.assertEqual(recovered["entities"], [])
            self.assertTrue((path.parent / "graph.json.corrupt.bak").is_file())


class MigrationV3Test(unittest.TestCase):
    def test_migrate_creates_graph_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, authority = _host(tmp, version=2)
            report = migrate.migrate(host)
            graph_path = authority / "graph" / "graph.json"
            self.assertTrue(graph_path.is_file())
            payload = json.loads(graph_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], 3)
            self.assertEqual(report["stats"].get("graph"), "created")
            before = graph_path.read_bytes()
            second = migrate.migrate(host)
            self.assertTrue(second["stats"].get("already"))
            self.assertEqual(graph_path.read_bytes(), before)

    def test_migrate_recovers_corrupt_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, authority = _host(tmp, version=2)
            graph_dir = authority / "graph"
            graph_dir.mkdir(parents=True, exist_ok=True)
            (graph_dir / "graph.json").write_text("broken{", encoding="utf-8")
            report = migrate.migrate(host)
            self.assertEqual(report["stats"].get("graph"), "recovered")
            payload = json.loads((graph_dir / "graph.json").read_text(
                encoding="utf-8"))
            self.assertEqual(payload["schema"], 3)
            self.assertTrue((graph_dir / "graph.json.corrupt.bak").is_file())

    def test_backup_and_restore_include_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, authority = _host(tmp, version=2)
            graph_dir = authority / "graph"
            graph_dir.mkdir(parents=True, exist_ok=True)
            seed = eg.empty_graph()
            seed, _ = eg.upsert_edge(seed, "a", "r", "b", ts=1.0)
            eg.save_graph(graph_dir / "graph.json", seed)
            report = migrate.migrate(host)
            backup = Path(report["backup_dir"])
            self.assertTrue((backup / "graph" / "graph.json").is_file())
            (graph_dir / "graph.json").write_text("{}", encoding="utf-8")
            result = migrate.restore(str(backup), host)
            self.assertGreaterEqual(result["restored"]["graph"], 1)
            restored = eg.load_graph(graph_dir / "graph.json")
            self.assertEqual(len(restored["edges"]), 1)


if __name__ == "__main__":
    unittest.main()
