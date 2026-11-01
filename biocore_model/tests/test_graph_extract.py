# -*- coding: utf-8 -*-
"""task-135: inline-tag entity/relation extraction tests."""
import json
import tempfile
import unittest
from pathlib import Path

from biocore_model import entity_graph as eg
from biocore_model import graph_extract as ge
from biocore_model import state_tag

NOW = 1704844800.0  # 2024-01-10 (Wednesday, local Asia/Shanghai)
DAY = 86400.0


def _tag(entities=None, relations=None, confidence=0.8):
    return {"dims": {"goal": 0.1}, "confidence": confidence,
            "entities": entities or [], "relations": relations or []}


class TypeMappingTest(unittest.TestCase):
    def test_chinese_type_to_canonical_and_back(self):
        self.assertEqual(ge.canonical_type("人物"), "person")
        self.assertEqual(ge.canonical_type("地点"), "place")
        self.assertEqual(ge.canonical_type("事件"), "event")
        self.assertEqual(ge.canonical_type("话题"), "topic")
        self.assertEqual(ge.canonical_type("unknown-thing"), "topic")
        self.assertEqual(ge.type_label("person"), "人物")
        self.assertEqual(ge.type_label("place"), "地点")

    def test_relation_label(self):
        self.assertEqual(ge.rel_label("planned"), "计划")
        self.assertEqual(ge.rel_label("custom_rel"), "custom_rel")


class WhenTest(unittest.TestCase):
    def test_relative_words(self):
        self.assertEqual(ge.when_to_ts("今天", NOW), NOW)
        self.assertEqual(ge.when_to_ts("昨天", NOW), NOW - DAY)
        self.assertEqual(ge.when_to_ts("前天", NOW), NOW - 2 * DAY)
        self.assertEqual(ge.when_to_ts("明天", NOW), NOW + DAY)
        self.assertEqual(ge.when_to_ts("3天前", NOW), NOW - 3 * DAY)
        self.assertEqual(ge.when_to_ts("2小时前", NOW), NOW - 7200.0)

    def test_weekday_words(self):
        self.assertEqual(ge.when_to_ts("周五", NOW), NOW - 5 * DAY)
        self.assertEqual(ge.when_to_ts("上周五", NOW), NOW - 12 * DAY)

    def test_unknown_or_empty(self):
        self.assertEqual(ge.when_to_ts("", NOW), 0.0)
        self.assertEqual(ge.when_to_ts("某个时候", NOW), 0.0)
        self.assertEqual(ge.when_to_ts(None, NOW), 0.0)


class ExtractTest(unittest.TestCase):
    def test_entities_with_types(self):
        out = ge.extract(_tag(entities=[{"name": "小夏", "type": "人物"},
                                        {"name": "体检", "type": "事件"}]), now=NOW)
        self.assertEqual([row["name"] for row in out["entities"]],
                         ["小夏", "体检"])
        self.assertEqual(out["entities"][0]["type"], "person")
        self.assertEqual(out["entities"][1]["type"], "event")

    def test_bare_string_entities_are_topic(self):
        out = ge.extract(_tag(entities=["海边", "打雷"]), now=NOW)
        self.assertEqual([row["type"] for row in out["entities"]],
                         ["topic", "topic"])

    def test_entity_cap_and_dedupe(self):
        out = ge.extract(_tag(entities=["a", "b", "c", "d", "e", "A"]), now=NOW)
        self.assertEqual(len(out["entities"]), 3)
        self.assertEqual([row["name"] for row in out["entities"]],
                         ["a", "b", "c"])

    def test_relation_cap_and_validation(self):
        relations = [
            {"src": "a", "rel": "planned", "dst": "b", "when": "周五"},
            {"src": "b", "rel": "likes", "dst": "c", "when": "昨天"},
            {"src": "c", "rel": "knows", "dst": "a"},
            {"src": "a", "rel": "r4", "dst": "b"},
            {"src": "bad", "rel": "", "dst": "x"},
            "garbage",
        ]
        out = ge.extract(_tag(entities=["a", "b", "c"], relations=relations),
                         now=NOW)
        self.assertLessEqual(len(out["relations"]), ge.MAX_RELATIONS)
        self.assertEqual(len(out["relations"]), 3)
        self.assertEqual(out["relations"][0]["rel"], "planned")
        self.assertEqual(out["relations"][0]["ts"], NOW - 5 * DAY)

    def test_relation_endpoints_join_until_cap(self):
        out = ge.extract(_tag(entities=["a"],
                              relations=[{"src": "a", "rel": "r", "dst": "b"}]),
                         now=NOW)
        names = [row["name"] for row in out["entities"]]
        self.assertEqual(names, ["a", "b"])
        self.assertEqual(len(out["relations"]), 1)

    def test_relation_with_unknown_endpoint_dropped_when_full(self):
        out = ge.extract(_tag(entities=["a", "b", "c"],
                              relations=[{"src": "a", "rel": "r", "dst": "z"}]),
                         now=NOW)
        self.assertEqual(out["relations"], [])

    def test_dirty_input_is_safe(self):
        for value in (None, {}, [], "x", {"entities": "x", "relations": 5}):
            out = ge.extract(value, now=NOW)
            self.assertEqual(out["entities"], [])
            self.assertEqual(out["relations"], [])


class ApplyTest(unittest.TestCase):
    def test_apply_writes_sqlite_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = eg.open_store(Path(tmp) / "graph" / eg.SQLITE_FILE)
            try:
                extracted = ge.extract(_tag(
                    entities=[{"name": "小夏", "type": "人物"},
                              {"name": "体检", "type": "事件"}],
                    relations=[{"src": "小夏", "rel": "planned",
                                "dst": "体检", "when": "周五"}]), now=NOW)
                applied = ge.apply(store, extracted, now=NOW, source_entry="m1")
                self.assertEqual(applied["entities"], 2)
                self.assertEqual(applied["relations"], 1)
                stats = eg.stats(store)
                self.assertEqual(stats["entities"], 2)
                self.assertEqual(stats["edges"], 1)
                row = store._conn.execute(
                    "SELECT ts, confidence, source_entry FROM edges").fetchone()
                self.assertEqual(row[0], NOW - 5 * DAY)
                self.assertEqual(row[2], "m1")
                found = eg.neighbors(store, "小夏", hops=1)
                self.assertEqual({item["name"] for item in found["entities"]},
                                 {"小夏", "体检"})
            finally:
                store.close()

    def test_apply_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = eg.open_store(Path(tmp) / "graph" / eg.SQLITE_FILE)
            try:
                extracted = ge.extract(_tag(entities=["a", "b"],
                                            relations=[{"src": "a", "rel": "r",
                                                        "dst": "b",
                                                        "when": "今天"}]),
                                       now=NOW)
                ge.apply(store, extracted, now=NOW, source_entry="m1")
                ge.apply(store, extracted, now=NOW, source_entry="m1")
                stats = eg.stats(store)
                self.assertEqual(stats["entities"], 2)
                self.assertEqual(stats["edges"], 1)
            finally:
                store.close()

    def test_apply_empty_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = eg.open_store(Path(tmp) / "graph" / eg.SQLITE_FILE)
            try:
                self.assertEqual(ge.apply(store, {}, now=NOW),
                                 {"entities": 0, "relations": 0})
            finally:
                store.close()


class StateTagIntegrationTest(unittest.TestCase):
    def test_instruction_exposes_graph_fields(self):
        text = state_tag.instruction()
        self.assertIn('"entities"', text)
        self.assertIn('"relations"', text)
        self.assertIn("最多 3", text)

    def test_parse_graph_fields_bounded(self):
        raw = json.dumps({
            "dims": {"goal": 0.1}, "c": 0.8,
            "entities": [{"name": "a", "type": "人物"}, "b", "c", "d"],
            "relations": [{"src": "a", "rel": "r", "dst": "b",
                           "when": "昨天"},
                          {"src": "b", "rel": "r2", "dst": "c"},
                          {"src": "c", "rel": "r3", "dst": "d"},
                          {"src": "d", "rel": "r4", "dst": "a"}]},
            ensure_ascii=False)
        out = state_tag.parse("reply\n" + raw)
        self.assertEqual(len(out["entities"]), 3)
        self.assertEqual(len(out["relations"]), 3)
        self.assertEqual(out["entities"][0]["name"], "a")

    def test_end_to_end_tag_to_graph(self):
        raw = json.dumps({
            "dims": {"goal": 0.2}, "c": 0.9,
            "entities": [{"name": "小夏", "type": "人物"},
                         {"name": "医院", "type": "地点"}],
            "relations": [{"src": "小夏", "rel": "located_at",
                           "dst": "医院", "when": "昨天"}]},
            ensure_ascii=False)
        tag = state_tag.parse("好。\n" + raw)
        extracted = ge.extract(tag, now=NOW)
        with tempfile.TemporaryDirectory() as tmp:
            store = eg.open_store(Path(tmp) / "graph" / eg.SQLITE_FILE)
            try:
                ge.apply(store, extracted, now=NOW, source_entry="m9")
                found = eg.neighbors(store, "医院", hops=1)
                labels = {item["name"]: ge.type_label(item["type"])
                          for item in found["entities"]}
                self.assertEqual(labels.get("小夏"), "人物")
                self.assertEqual(labels.get("医院"), "地点")
                self.assertEqual(len(found["edges"]), 1)
            finally:
                store.close()



class WiringStaticTest(unittest.TestCase):
    def test_main_wires_tag_graph_ingest(self):
        from pathlib import Path as _Path
        source = (_Path(__file__).resolve().parents[2] / "main.py").read_text(
            encoding="utf-8")
        self.assertIn("_ingest_graph_from_tag", source)
        self.assertIn("graph_memory_enabled", source)
        self.assertIn("graph_extract as _ge", source)
        self.assertIn("source_entry=str(", source)


if __name__ == "__main__":
    unittest.main()
