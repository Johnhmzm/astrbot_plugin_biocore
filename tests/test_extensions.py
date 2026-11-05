# -*- coding: utf-8 -*-
"""task-225 (5b): P0 memory extensions + expression modules."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from biocore_model import (entity_graph, entity_resolve, expr_template,
                           graph_extract, graph_recall, layered_memory,
                           memory_dual, prompt_rules, prospective,
                           reconstruction, template_expr, topic_control,
                           turn_memory, voice_bank)
from biocore_runtime import extensions, pipeline


def entry(i, text, ts=1700000000.0):
    return {"id": i, "text": text, "role": "user", "ts": ts,
            "importance": 0.5, "hits": 1}


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "data"
        self.store = self.data_dir / "memory"
        (self.store / "sessions" / "s1").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()


class GraphTest(Case):
    def test_entity_graph_build_search(self):
        graph, _ = extensions._entity_graph([
            entry("a", "苹果 很甜"), entry("b", "苹果 咖啡")])
        self.assertGreaterEqual(len(graph.get("entities") or []), 1)
        hits = entity_graph.search(graph, "苹果", limit=4)
        self.assertTrue(hits)

    def test_entity_resolve(self):
        self.assertEqual(entity_resolve.normalize("苹果 甜"), "苹果甜")
        self.assertGreaterEqual(entity_resolve.similarity("苹果", "苹果"), 0.9)

    def test_graph_extract(self):
        self.assertEqual(graph_extract.canonical_type("人物"), "person")
        self.assertGreater(graph_extract.when_to_ts("明天", 1000.0), 1000.0)

    def test_graph_recall_window(self):
        window = graph_recall.detect_window("上周")
        self.assertNotEqual(window, None)

    def test_graph_hits_extra(self):
        rows = [entry("a", "苹果 很甜"), entry("b", "苹果 咖啡"),
                entry("c", "香蕉")]
        hits, stats = extensions.graph_hits(rows, "苹果")
        self.assertGreaterEqual(stats["hits"], 0)
        self.assertIsInstance(hits, list)


class MemoryExtTest(Case):
    def test_layered_select(self):
        result = layered_memory.select([entry("a", "早上的事"), entry("b", "刚才的事")],
                                       recalled_ids=["b"])
        self.assertIn("resident", result)
        self.assertIn("retrieval", result)
        self.assertTrue(result["resident"] or result["retrieval"])

    def test_memory_dual_score(self):
        e = memory_dual.encode("苹果", 1700000000.0, arousal=0.5)
        self.assertGreater(memory_dual.score(e, 1700000100.0), 0)
        self.assertTrue(memory_dual.select([e], 1700000100.0, limit=2))

    def test_prospective_due(self):
        now = time.time()
        rec = prospective.entry("his_event", "体检", now - 10)
        items, changed = prospective.add([], rec)
        self.assertTrue(changed)
        due = prospective.due_now(items, now, window_s=60)
        self.assertEqual(len(due), 1)
        self.assertTrue(prospective.build_hint(due[0], now))
        self.assertEqual(prospective.stats(items)["by_status"]["pending"], 1)

    def test_reconstruction(self):
        out = reconstruction.conserve([entry("a", "旧的记忆")])
        self.assertIn("total", out)

    def test_turn_memory(self):
        rows = turn_memory.build([{"entry_id": "a", "text": "记得喝水",
                                   "source": "recall"}])
        self.assertEqual(len(rows), 1)
        record = turn_memory.build_record(rows, reply="好", ts=10.0)
        self.assertTrue(turn_memory.render_receipt(record))

    def test_recall_graph_expansion(self):
        rows = [entry("a", "苹果 很甜", 1700000001.0),
                entry("b", "苹果 咖啡", 1700000002.0),
                entry("c", "香蕉 黄", 1700000003.0)]
        (self.store / "sessions" / "s1" / "memory.json").write_text(
            json.dumps({"entries": rows}), encoding="utf-8")
        out = pipeline.inject_block("s1", str(self.store), query="苹果 咖啡",
                                    mode="query", top_k=3)
        self.assertGreaterEqual(len(out["ids"]), 2)
        self.assertIn("b", out["ids"])


class ExpressionTest(Case):
    def test_expr_template(self):
        out = expr_template.build_reply({"v": 0.2}, {"trust": 0.5})
        self.assertIsInstance(out, dict)

    def test_prompt_rules(self):
        text = prompt_rules.render_rules(affect={"valence": -0.4, "stress": 0.7},
                                         relation={"closeness": 0.5},
                                         certainty=0.7, soft_target=12,
                                         soft_max=30)
        self.assertIsInstance(text, str)
        self.assertTrue(text)

    def test_template_expr(self):
        self.assertEqual(template_expr.render("你好 {{name}}", {"name": "主管"}),
                         "你好 主管")

    def test_topic_control(self):
        result = topic_control.topic_control(turns=[], state={"v": 0.0},
                                             relationship={"trust": 0.5})
        self.assertIsInstance(result, dict)
        self.assertTrue("tendency" in result or "holder" in result)

    def test_voice_bank(self):
        bank = [{"id": "v1", "phrase": "嗯。", "weight": 1.0,
                 "when": {"v_min": -1, "v_max": 1, "tension_min": 0,
                          "tension_max": 1}, "cooldown_s": 0}]
        picked = voice_bank.pick({"v": 0.1, "tension": 0.2},
                                 {"stage": "normal"}, [], time.time(),
                                 entries=bank)
        self.assertTrue(picked)

    def test_expression_block(self):
        block = extensions.expression_block(
            str(self.store), {"core": {"v": -0.2, "stress": 0.7}},
            {"trust": 0.5, "closeness": 0.4, "stage": "normal"},
            soft_target=12, soft_max=30)
        self.assertTrue(block["rules"] or block["template"])
        self.assertIn("template_name", block)


class StateTest(Case):
    def test_state_exposes_extensions(self):
        rows = [entry("a", "苹果 很甜"), entry("b", "香蕉")]
        (self.store / "sessions" / "s1" / "memory.json").write_text(
            json.dumps({"entries": rows}), encoding="utf-8")
        pipeline.dispatch("turn_end", {
            "store": str(self.store), "session_id": "s1",
            "user_text": "苹果很甜", "assistant_text": "嗯。",
            "capture": False,
            "persona_profile": str(Path(self.tmp.name) / "missing.json")})
        body = pipeline.dispatch("state", {
            "store": str(self.store), "session_id": "s1",
            "persona_profile": str(Path(self.tmp.name) / "missing.json")})["state"]
        self.assertIn("extensions", body)
        self.assertIn("graph", body["extensions"])
        self.assertIn("layered", body["extensions"])


if __name__ == "__main__":
    unittest.main()
