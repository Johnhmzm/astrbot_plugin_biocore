# -*- coding: utf-8 -*-
"""P0-1 entity disambiguation: alias merge, similarity merge, panel merge API.

Covers the pure resolver (biocore_model/entity_resolve.py), its storage wiring
(entity_graph upsert/merge), the model-facing alias pass-through (state_tag +
graph_extract) and the dashboard merge endpoint (main.py).
"""
import ast
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

from biocore_model import entity_graph as eg
from biocore_model import entity_resolve as er
from biocore_model import graph_extract as ge
from biocore_model import state_tag as st

NOW = 1800000000.0
MAIN = Path(__file__).resolve().parents[2] / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")


def _store(tmp, name="graph", threshold=None):
    return eg.open_store(Path(tmp) / name / eg.SQLITE_FILE,
                         similarity_threshold=threshold)


class SimilarityTest(unittest.TestCase):
    def test_normalize_and_ratio(self):
        self.assertEqual(er.normalize(" Xiao  Xia! "), "xiaoxia")
        self.assertEqual(er.similarity("Xiao Xia", "xiaoxia"), 1.0)
        self.assertGreaterEqual(er.similarity("老板张总", "老板张"), 0.85)
        self.assertLessEqual(er.similarity("小夏", "小美"), 0.5)
        self.assertEqual(er.similarity("", "小夏"), 0.0)

    def test_match_priority_name_alias_similarity(self):
        rows = [{"id": "e_1", "name": "小夏", "aliases": ["夏夏"]},
                {"id": "e_2", "name": "老板张总", "aliases": []}]
        self.assertEqual(er.match(rows, "小夏")["via"], "name")
        self.assertEqual(er.match(rows, "夏夏")["via"], "alias")
        self.assertEqual(er.match(rows, "老板张")["via"], "similarity")
        self.assertIsNone(er.match(rows, "奶茶"))

    def test_bounded_aliases(self):
        out = er.bounded_aliases(["夏夏", "小夏", "夏夏", "字" * 40, ""], "小夏")
        self.assertEqual(out[0], "夏夏")
        self.assertEqual(len(out), 2)
        self.assertEqual(len(out[1]), 20)

    def test_clean_merge_ids(self):
        self.assertEqual(er.clean_merge_ids({"keep_id": "a", "drop_id": "b"}),
                         ("a", "b"))
        self.assertEqual(er.clean_merge_ids({"keep": "a", "drop": "b"}),
                         ("a", "b"))
        self.assertEqual(er.clean_merge_ids({"keep_id": "a", "drop_id": "a"}),
                         ("a", ""))
        self.assertEqual(er.clean_merge_ids("nope"), ("", ""))


class UpsertMergeTest(unittest.TestCase):
    def test_alias_merge_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                _, e1 = eg.upsert_entity(store, "小夏", type="person",
                                         aliases=["夏夏"], now=100.0)
                _, e2 = eg.upsert_entity(store, "夏夏", type="person",
                                         now=200.0)
                self.assertEqual(e1, e2)
                self.assertEqual(eg.stats(store)["entities"], 1)
                row = store._row_by_id(e1)
                self.assertEqual(row["aliases"].count("夏夏"), 1)
                self.assertEqual(row["last_seen"], 200.0)
            finally:
                store.close()

    def test_similarity_merge_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                _, e1 = eg.upsert_entity(store, "老板张总", type="person",
                                         now=100.0)
                _, e2 = eg.upsert_entity(store, "老板张", now=200.0)
                self.assertEqual(e1, e2)
                self.assertEqual(eg.stats(store)["entities"], 1)
                self.assertIn("老板张", store._row_by_id(e1)["aliases"])
            finally:
                store.close()

    def test_similarity_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, threshold=0)
            try:
                _, e1 = eg.upsert_entity(store, "老板张总")
                _, e2 = eg.upsert_entity(store, "老板张")
                self.assertNotEqual(e1, e2)
                self.assertEqual(eg.stats(store)["entities"], 2)
            finally:
                store.close()

    def test_candidate_alias_matches_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                _, e1 = eg.upsert_entity(store, "小夏", type="person")
                _, e2 = eg.upsert_entity(store, "夏夏", aliases=["小夏"])
                self.assertEqual(e1, e2)
                self.assertEqual(eg.stats(store)["entities"], 1)
            finally:
                store.close()

    def test_different_people_not_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                for name in ("小夏", "夏夏", "小美", "老板", "老板娘",
                             "张三", "李四"):
                    eg.upsert_entity(store, name)
                self.assertEqual(eg.stats(store)["entities"], 7)
            finally:
                store.close()

    def test_dict_graph_similarity_merge(self):
        graph, e1 = eg.upsert_entity(eg.empty_graph(), "老板张总",
                                     type="person")
        graph, e2 = eg.upsert_entity(graph, "老板张")
        self.assertEqual(e1, e2)
        self.assertEqual(len(graph["entities"]), 1)
        self.assertIn("老板张", graph["entities"][0]["aliases"])
        self.assertIsNotNone(eg.find_similar(graph, "老板张"))


class SelfLoopGuardTest(unittest.TestCase):
    def test_edge_between_two_spellings_is_not_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                eg.upsert_entity(store, "体检", type="event",
                                 aliases=["体检医院"])
                _, edge_id = eg.upsert_edge(store, "体检", "located_at",
                                            "体检医院", ts=100.0)
                self.assertEqual(edge_id, "")
                self.assertEqual(eg.stats(store)["edges"], 0)
                self.assertEqual(eg.stats(store)["entities"], 1)
            finally:
                store.close()

    def test_dict_edge_between_two_spellings_is_not_stored(self):
        graph, _ = eg.upsert_entity(eg.empty_graph(), "体检", type="event",
                                    aliases=["体检医院"])
        graph, edge_id = eg.upsert_edge(graph, "体检", "located_at",
                                        "体检医院", ts=100.0)
        self.assertEqual(edge_id, "")
        self.assertEqual(len(graph["edges"]), 0)


class MergeEntitiesTest(unittest.TestCase):
    def test_merge_unions_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                _, keep = eg.upsert_entity(store, "小夏", type="topic",
                                           now=100.0, entry_id="m1")
                _, drop = eg.upsert_entity(store, "夏夏", type="person",
                                           now=300.0, entry_id="m2")
                report = store.merge_entities(keep, drop)
                self.assertTrue(report["ok"], report)
                row = store._row_by_id(keep)
                self.assertEqual(row["type"], "person")  # topic -> specific
                self.assertIn("夏夏", row["aliases"])
                self.assertEqual(row["sources"], ["m1", "m2"])
                self.assertEqual(row["first_seen"], 100.0)
                self.assertEqual(row["last_seen"], 300.0)
                self.assertIsNone(store._row_by_id(drop))
            finally:
                store.close()

    def test_merge_rewires_edges_and_drops_self_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                eg.upsert_edge(store, "小夏", "planned", "体检", ts=100.0)
                eg.upsert_edge(store, "夏夏", "likes", "奶茶", ts=200.0)
                eg.upsert_edge(store, "小夏", "knows", "夏夏", ts=300.0)
                eg.upsert_edge(store, "夏夏", "planned", "体检", ts=100.0)
                keep = store._find_entity("小夏")["id"]
                drop = store._find_entity("夏夏")["id"]
                report = store.merge_entities(keep, drop)
                self.assertTrue(report["ok"], report)
                self.assertEqual(report["edges_rewired"], 2)
                self.assertEqual(report["edges_dropped"], 2)
                names = {(row[0], row[1], row[2]) for row in
                         store._conn.execute(
                             "SELECT src, rel, dst FROM edges").fetchall()}
                self.assertIn((keep, "planned", store._find_entity("体检")["id"]),
                              names)
                self.assertIn((keep, "likes", store._find_entity("奶茶")["id"]),
                              names)
                self.assertEqual(len(names), 2)
                self.assertEqual(eg.stats(store)["entities"], 3)
            finally:
                store.close()

    def test_merge_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                _, eid = eg.upsert_entity(store, "小夏")
                self.assertFalse(store.merge_entities(eid, eid)["ok"])
                self.assertFalse(store.merge_entities(eid, "e_missing")["ok"])
                self.assertFalse(store.merge_entities("", "")["ok"])
                self.assertIsNotNone(store._row_by_id(eid))
            finally:
                store.close()

    def test_dict_graph_merge(self):
        graph, keep = eg.upsert_entity(eg.empty_graph(), "小夏",
                                       type="person")
        graph, drop = eg.upsert_entity(graph, "夏夏")
        graph, _ = eg.upsert_edge(graph, "夏夏", "likes", "奶茶", ts=5.0)
        graph, report = eg.merge_entities(graph, keep, drop)
        self.assertTrue(report["ok"], report)
        self.assertEqual(len(graph["entities"]), 2)
        self.assertEqual(len(graph["edges"]), 1)
        self.assertEqual(graph["edges"][0]["src"], keep)
        self.assertIn("夏夏", graph["entities"][0]["aliases"])


def _load_page_graph_merge():
    tree = ast.parse(SOURCE)
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == "BioCorePlugin")
    node = next(item for item in cls.body
                if isinstance(item, ast.AsyncFunctionDef)
                and item.name == "page_graph_merge")
    clone = ast.AsyncFunctionDef(name=node.name, args=node.args, body=node.body,
                                 decorator_list=[], returns=node.returns,
                                 type_comment=None, lineno=node.lineno,
                                 col_offset=node.col_offset,
                                 end_lineno=node.end_lineno,
                                 end_col_offset=node.end_col_offset)
    ns = {"logger": types.SimpleNamespace(
        info=lambda *a, **k: None, warning=lambda *a, **k: None)}
    exec(compile(ast.Module(body=[clone], type_ignores=[]),
                 "<page_graph_merge>", "exec"), ns)
    return ns[node.name], ns


PAGE_MERGE, MERGE_NS = _load_page_graph_merge()


class _FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def get_json(self, silent=False):
        return self.payload


class _FakePlugin:
    def __init__(self, path):
        self._path = path

    def _graph_db_path(self):
        return self._path


class PanelMergeApiTest(unittest.IsolatedAsyncioTestCase):
    async def _call(self, plugin, payload):
        module = types.ModuleType("quart")
        module.request = _FakeRequest(payload)
        previous = sys.modules.get("quart")
        sys.modules["quart"] = module
        try:
            return await PAGE_MERGE(plugin)
        finally:
            if previous is None:
                sys.modules.pop("quart", None)
            else:
                sys.modules["quart"] = previous

    async def test_merge_endpoint_merges_two_entities(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph" / eg.SQLITE_FILE
            store = eg.open_store(path)
            try:
                _, keep = eg.upsert_entity(store, "小夏", type="person")
                _, drop = eg.upsert_entity(store, "夏夏")
                eg.upsert_edge(store, "夏夏", "likes", "奶茶")
            finally:
                store.close()
            out = await self._call(_FakePlugin(path),
                                   {"keep_id": keep, "drop_id": drop})
            self.assertEqual(out["status"], "ok", out)
            self.assertTrue(out["data"]["ok"])
            self.assertEqual(out["data"]["aliases"], 1)
            store = eg.open_store(path)
            try:
                self.assertIsNone(store._row_by_id(drop))
                self.assertIn("夏夏", store._row_by_id(keep)["aliases"])
                self.assertEqual(eg.stats(store)["entities"], 2)
                self.assertEqual(eg.stats(store)["edges"], 1)
            finally:
                store.close()

    async def test_merge_endpoint_rejects_bad_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph" / eg.SQLITE_FILE
            out = await self._call(_FakePlugin(path), {})
            self.assertEqual(out["status"], "error")
            out = await self._call(_FakePlugin(path),
                                   {"keep_id": "e_nope", "drop_id": "e_also"})
            self.assertEqual(out["status"], "error")
            self.assertEqual(out["message"], "entity not found")

    def test_route_registered(self):
        self.assertIn("/astrbot_plugin_biocore/page/graph/merge", SOURCE)
        self.assertIn("self.page_graph_merge", SOURCE)


class AliasPassThroughTest(unittest.TestCase):
    def test_state_tag_keeps_bounded_aliases(self):
        raw = json.dumps({"dims": {"goal": 0.1}, "c": 0.8, "entities": [
            {"name": "小夏", "type": "人物",
             "aliases": ["夏夏", "小夏", "夏夏", "字" * 40]}]},
            ensure_ascii=False)
        out = st.parse("好。\n" + raw)
        entity = out["entities"][0]
        self.assertEqual(entity["name"], "小夏")
        self.assertEqual(entity["aliases"][0], "夏夏")
        self.assertEqual(len(entity["aliases"]), 2)
        self.assertEqual(len(entity["aliases"][1]), 20)

    def test_graph_extract_and_apply_carry_aliases(self):
        tag = {"dims": {"goal": 0.2}, "c": 0.9, "entities": [
            {"name": "小夏", "type": "人物", "aliases": ["夏夏"]},
            {"name": "体检", "type": "事件"}],
            "relations": [{"src": "小夏", "rel": "have_checkup",
                           "dst": "体检", "when": "周五"}]}
        extracted = ge.extract(tag, now=NOW)
        self.assertEqual(extracted["entities"][0]["aliases"], ["夏夏"])
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                ge.apply(store, extracted, now=NOW, source_entry="m1")
                row = store._find_entity("小夏")
                self.assertIn("夏夏", row["aliases"])
                _, eid = eg.upsert_entity(store, "夏夏")
                self.assertEqual(eid, row["id"])
                self.assertEqual(eg.stats(store)["entities"], 2)
            finally:
                store.close()


TURNS = [
    {"entities": [{"name": "小夏", "type": "人物"}],
     "relations": [{"src": "小夏", "rel": "planned", "dst": "海边",
                    "when": "周末"}]},
    {"entities": [{"name": "夏夏", "type": "人物", "aliases": ["小夏"]}],
     "relations": [{"src": "夏夏", "rel": "have_checkup", "dst": "体检",
                    "when": "周五"}]},
    {"entities": [{"name": "小夏", "type": "人物"},
                  {"name": "海边", "type": "地点"}]},
    {"entities": [{"name": "海边", "type": "地点"}]},
    {"entities": [{"name": "体检", "type": "事件",
                   "aliases": ["体检医院"]}]},
    {"entities": [{"name": "老板张总", "type": "人物"}],
     "relations": [{"src": "老板张总", "rel": "likes", "dst": "奶茶",
                    "when": "今天"}]},
    {"entities": [{"name": "夏夏", "type": "人物"},
                  {"name": "体检医院", "type": "地点"}],
     "relations": [{"src": "夏夏", "rel": "planned", "dst": "体检医院",
                    "when": "昨天"}]},
    {"entities": [{"name": "小夏", "type": "人物"},
                  {"name": "奶茶", "type": "话题"}]},
    {"entities": [{"name": "老板张", "type": "人物"}]},
    {"entities": [{"name": "夏夏姐", "type": "人物", "aliases": ["夏夏"]}],
     "relations": [{"src": "夏夏姐", "rel": "likes", "dst": "奶茶",
                    "when": "今天"}]},
    {"entities": [{"name": "海边", "type": "地点"},
                  {"name": "奶茶", "type": "话题"}]},
    {"entities": [{"name": "小夏", "type": "人物"},
                  {"name": "体检", "type": "事件"}],
     "relations": [{"src": "小夏", "rel": "have_checkup", "dst": "体检",
                    "when": "周五"}]},
    {"entities": [{"name": "老板张总", "type": "人物"}]},
    {"entities": [{"name": "夏夏", "type": "人物"}]},
    {"entities": [{"name": "体检医院", "type": "地点"}]},
    {"entities": [{"name": "老板张", "type": "人物"},
                  {"name": "奶茶", "type": "话题"}],
     "relations": [{"src": "老板张", "rel": "likes", "dst": "奶茶",
                    "when": "今天"}]},
    {"entities": [{"name": "小夏", "type": "人物"},
                  {"name": "海边", "type": "地点"}]},
    {"entities": [{"name": "夏夏姐", "type": "人物"}]},
    {"entities": [{"name": "体检", "type": "事件"},
                  {"name": "体检医院", "type": "地点"}],
     "relations": [{"src": "体检", "rel": "located_at", "dst": "体检医院",
                    "when": "昨天"}]},
    {"entities": [{"name": "奶茶", "type": "话题"}]},
]


class TwentyTurnSimulationTest(unittest.TestCase):
    def test_twenty_turns_do_not_inflate_entities(self):
        mentioned = []
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                for index, turn in enumerate(TURNS):
                    payload = {"dims": {"goal": 0.1}, "c": 0.8,
                               "entities": turn["entities"]}
                    if turn.get("relations"):
                        payload["relations"] = turn["relations"]
                    tag = st.parse("好。\n" + json.dumps(payload,
                                                         ensure_ascii=False))
                    extracted = ge.extract(tag, now=NOW + index * 60.0)
                    ge.apply(store, extracted, now=NOW + index * 60.0,
                             source_entry="m%d" % index)
                    mentioned.extend(row["name"]
                                     for row in turn["entities"])
                entities = eg.stats(store)["entities"]
                self.assertGreater(len(mentioned), 20)
                self.assertLessEqual(entities, 5, eg.stats(store))
                self.assertGreaterEqual(eg.stats(store)["edges"], 4)
                known = {row[0] for row in store._conn.execute(
                    "SELECT id FROM entities").fetchall()}
                for row in store._conn.execute(
                        "SELECT src, dst FROM edges").fetchall():
                    self.assertIn(row[0], known)
                    self.assertIn(row[1], known)
                row = store._find_entity("小夏")
                self.assertIn("夏夏", row["aliases"])
                self.assertIn("夏夏姐", row["aliases"])
                self.assertEqual(eg.stats(store)["entities"], 5)
                self.assertEqual(store._find_entity("老板张")["id"],
                                 store._find_entity("老板张总")["id"])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
