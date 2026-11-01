# -*- coding: utf-8 -*-
"""task-136: graph recall, time window, "你知道的" render, panel data tests."""
import tempfile
import unittest
from pathlib import Path

from biocore_model import entity_graph as eg
from biocore_model import graph_extract as gx
from biocore_model import graph_recall as gr

NOW = 1704844800.0
DAY = 86400.0


def _store(tmp):
    return eg.open_store(Path(tmp) / "graph" / eg.SQLITE_FILE)


def _seed(store, now=NOW):
    eg.upsert_edge(store, "小夏", "afraid_of", "打雷", ts=now - 2 * DAY,
                   confidence=0.9, source_entry="m1")
    eg.upsert_edge(store, "小夏", "planned", "海边", ts=now - DAY,
                   confidence=0.8, source_entry="m2")
    eg.upsert_edge(store, "周末", "planned", "海边", ts=now - DAY,
                   confidence=0.6, source_entry="m3")


class WindowTest(unittest.TestCase):
    def test_detect_window_words(self):
        self.assertEqual(gr.detect_window("上周去了吗"), (7, "上周"))
        self.assertEqual(gr.detect_window("昨天呢"), (1, "昨天"))
        self.assertEqual(gr.detect_window("今天如何"), (None, ""))
        self.assertEqual(gr.detect_window(""), (None, ""))

    def test_window_filters_old_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                eg.upsert_edge(store, "海边", "located_at", "旧码头",
                               ts=NOW - 30 * DAY, confidence=0.9)
                eg.upsert_edge(store, "海边", "planned", "新行程",
                               ts=NOW - DAY, confidence=0.6)
                recent = gr.recall(store, "上周去海边", now=NOW)
                self.assertTrue(recent)
                for row in recent:
                    self.assertGreaterEqual(row["ts"], NOW - 7 * DAY)
                all_time = gr.recall(store, "海边", now=NOW)
                self.assertTrue(any("旧码头" in row["line"] for row in all_time))
            finally:
                store.close()


class RecallTest(unittest.TestCase):
    def test_two_hop_association(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                _seed(store)
                one = gr.recall(store, "海边", now=NOW, hops=1)
                self.assertFalse(any("打雷" in row["line"] for row in one))
                two = gr.recall(store, "海边", now=NOW, hops=2)
                self.assertTrue(any("打雷" in row["line"] for row in two))
            finally:
                store.close()

    def test_no_entity_match_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                _seed(store)
                self.assertEqual(gr.recall(store, "今天吃什么", now=NOW), [])
                self.assertEqual(gr.render(store, "今天吃什么", now=NOW), "")
            finally:
                store.close()

    def test_render_lines_and_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                _seed(store)
                for index in range(8):
                    eg.upsert_edge(store, "海边", "topic_%d" % index,
                                   "话题节点%d" % index,
                                   ts=NOW - index * 3600., confidence=0.5)
                text = gr.render(store, "海边还去吗", now=NOW)
                self.assertTrue(text.startswith("你知道的："))
                bullets = [line for line in text.splitlines()
                           if line.startswith("- ")]
                self.assertLessEqual(len(bullets), gr.MAX_LINES)
                self.assertLessEqual(len(text.splitlines()), gr.MAX_LINES + 1)
            finally:
                store.close()

    def test_ranking_prefers_recent_and_confident(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                eg.upsert_edge(store, "海边", "planned", "旧计划",
                               ts=NOW - 20 * DAY, confidence=0.2)
                eg.upsert_edge(store, "海边", "planned", "新计划",
                               ts=NOW - 3600.0, confidence=0.9)
                rows = gr.recall(store, "海边", now=NOW)
                self.assertIn("新计划", rows[0]["line"])
            finally:
                store.close()

    def test_cross_entry_after_twenty_dialogues(self):
        bags = [
            [{"name": "小夏", "type": "人物"}, {"name": "打雷", "type": "话题"}],
            [{"name": "小夏", "type": "人物"}, {"name": "海边", "type": "地点"}],
            [{"name": "周末", "type": "事件"}, {"name": "海边", "type": "地点"}],
            [{"name": "雨伞", "type": "话题"}, {"name": "下雨", "type": "事件"}],
        ]
        relations = [
            ("小夏", "afraid_of", "打雷", 2),
            ("小夏", "planned", "海边", 1),
            ("周末", "planned", "海边", 1),
            ("下雨", "blocks", "海边", 0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                for turn in range(20):
                    tag = {"entities": bags[turn % len(bags)],
                           "relations": [], "confidence": 0.8}
                    extracted = gx.extract(tag, now=NOW)
                    gx.apply(store, extracted, now=NOW, source_entry="m%d" % turn)
                for src, rel, dst, days_ago in relations:
                    eg.upsert_edge(store, src, rel, dst,
                                   ts=NOW - days_ago * DAY, confidence=0.8,
                                   source_entry="r")
                text = gr.render(store, "下雨了海边还去吗", now=NOW)
                self.assertIn("你知道的：", text)
                self.assertIn("打雷", text)
                bullets = [line for line in text.splitlines()
                           if line.startswith("- ")]
                self.assertLessEqual(len(bullets), 5)
            finally:
                store.close()


class TimelinePanelTest(unittest.TestCase):
    def test_timeline_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                _seed(store)
                rows = gr.timeline(store, "小夏", now=NOW)
                self.assertGreaterEqual(len(rows), 2)
                self.assertGreaterEqual(rows[0]["ts"], rows[-1]["ts"])
                self.assertIn("—", rows[0]["text"])
            finally:
                store.close()

    def test_timeline_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                eg.upsert_edge(store, "小夏", "old_rel", "旧事",
                               ts=NOW - 40 * DAY)
                rows = gr.timeline(store, "小夏", now=NOW, window_days=7)
                self.assertTrue(all(row["ts"] >= NOW - 7 * DAY for row in rows))
            finally:
                store.close()

    def test_panel_data_entities_and_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                _seed(store)
                data = gr.panel_data(store, now=NOW)
                self.assertEqual(data["stats"]["entities"], 4)
                self.assertEqual(data["stats"]["edges"], 3)
                names = [row["name"] for row in data["entities"]]
                self.assertIn("小夏", names)
                person = [row for row in data["entities"] if row["name"] == "小夏"][0]
                self.assertEqual(person["type"], "topic")
                self.assertEqual(person["type_label"], "话题")
                edge = [row for row in data["edges"] if row["rel"] == "planned"][0]
                self.assertEqual(edge["rel_label"], "计划")
                self.assertIn(edge["src_name"], ("小夏", "周末"))
                self.assertTrue(edge["when"])
            finally:
                store.close()

    def test_source_entries(self):
        rows = [{"source_entry": "m1"}, {"source_entry": "m1"},
                {"source_entry": "m2"}, {"source_entry": ""}]
        self.assertEqual(gr.source_entries(rows), ["m1", "m2"])

    def test_panel_data_empty_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            try:
                data = gr.panel_data(store, now=NOW)
                self.assertEqual(data["entities"], [])
                self.assertEqual(data["edges"], [])
                self.assertEqual(data["stats"]["entities"], 0)
            finally:
                store.close()


class WiringStaticTest(unittest.TestCase):
    def test_preset_and_main_have_graph_block(self):
        repo = Path(__file__).resolve().parents[2]
        preset_src = (repo / "biocore_model" / "preset.py").read_text(
            encoding="utf-8")
        main_src = (repo / "main.py").read_text(encoding="utf-8")
        self.assertIn('"graph_memory"', preset_src)
        self.assertIn("graph_recall", main_src)
        self.assertIn("/astrbot_plugin_biocore/page/graph", main_src)
        self.assertIn("async def page_graph", main_src)
        graph_ui = repo / "pages" / "dashboard" / "graph.js"
        self.assertTrue(graph_ui.is_file())
        ui = graph_ui.read_text(encoding="utf-8")
        self.assertIn("page/graph", ui)
        self.assertIn("registerPage", ui)
        self.assertIn("id: 'graph'", ui)
        built = (repo / "pages" / "dashboard" / "index.html").read_text(
            encoding="utf-8")
        self.assertIn('id="view-graph"', built)
        self.assertIn("__ui3GraphInstalled", built)


if __name__ == "__main__":
    unittest.main()
