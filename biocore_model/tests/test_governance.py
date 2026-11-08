# -*- coding: utf-8 -*-
"""task-223: memory governance (decay/index/consolidate/concepts) + relationship."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from biocore_runtime import governance
from biocore_runtime import pipeline
from biocore_runtime import relationship_state


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def memory(entry_id, text, ts, importance=0.5, concepts=None):
    row = {"id": entry_id, "text": text, "role": "user", "ts": ts,
           "importance": importance, "hits": 1}
    if concepts is not None:
        row["concepts"] = list(concepts)
    return row


class StoreCase(unittest.TestCase):
    NOW = 1700000000.0

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "data"
        self.store = self.data_dir / "memory"
        self.persona = Path(self.tmp.name) / "missing_persona.json"
        self.write_session("s1", [
            memory("fresh", "今天买了咖啡", self.NOW - 60, 0.9),
            memory("old", "很久以前的事", self.NOW - 400 * 86400, 0.2),
            memory("mid", "苹果很甜", self.NOW - 86400, 0.5),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def write_session(self, session_id, entries):
        write_json(self.store / "sessions" / session_id / "memory.json",
                   {"session_id": session_id, "entries": entries})

    def payload(self, session_id="s1", **extra):
        data = {"store": str(self.store), "session_id": session_id,
                "persona_profile": str(self.persona)}
        data.update(extra)
        return data

    def turn_end(self, session_id="s1", user_text="", **extra):
        return pipeline.dispatch("turn_end", self.payload(
            session_id, user_text=user_text, assistant_text="嗯。",
            capture=False, **extra))


class DecayTest(StoreCase):
    def test_decay_marks_but_never_deletes(self):
        before = len(governance._entries(self.store))
        out = governance.run(self.store, now=self.NOW, force=True)
        after = len(governance._entries(self.store))
        self.assertEqual(before, after)
        self.assertGreaterEqual(out["decay"]["cold"], 1)
        self.assertEqual(out["decay"]["deleted"], 0)
        self.assertLess(governance.weight_of(self.store, "old"), 1.0)

    def test_fresh_entry_keeps_full_weight(self):
        governance.run(self.store, now=self.NOW, force=True)
        self.assertEqual(governance.weight_of(self.store, "fresh"), 1.0)

    def test_evict_delete_flag_does_not_delete(self):
        write_json(self.data_dir / "flags.json", {"evict_delete": True})
        before = len(governance._entries(self.store))
        governance.run(self.store, now=self.NOW, force=True)
        self.assertEqual(len(governance._entries(self.store)), before)

    def test_governance_off_skips(self):
        write_json(self.data_dir / "flags.json", {"governance": False})
        out = governance.run(self.store, now=self.NOW, force=True)
        self.assertTrue(out.get("skipped"))
        self.assertFalse((self.store / "governance.json").exists())


class IndexAndConceptTest(StoreCase):
    def test_index_lookup_hits_entry(self):
        governance.run(self.store, now=self.NOW, force=True)
        self.assertIn("mid", governance.lookup(self.store, "苹果"))
        doc = json.loads((self.store / "index.json").read_text(encoding="utf-8"))
        self.assertTrue(doc["terms"])

    def test_inject_uses_index_and_counts_hit(self):
        governance.run(self.store, now=self.NOW, force=True)
        out = pipeline.inject_block("s1", str(self.store), query="苹果",
                                    mode="query", top_k=3)
        self.assertEqual(out["ids"][0], "mid")
        gov = json.loads((self.store / "governance.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(gov.get("index_hits", 0), 1)

    def test_remember_stores_concepts(self):
        pipeline.tool_call("remember", {"text": "苹果和咖啡都很好"},
                           {"root": str(self.store)}, session_id="s2")
        doc = pipeline.export_session_json(str(self.store), "s2")
        self.assertTrue(doc["entries"][0].get("concepts"))

    def test_concept_filter_narrows_candidates(self):
        entries = [{"id": "a", "concepts": ["苹果", "甜"]},
                   {"id": "b", "concepts": ["香蕉", "黄"]}]
        kept = pipeline._concept_filter(entries, "苹果")
        self.assertEqual([row["id"] for row in kept], ["a"])


class ConsolidateTest(StoreCase):
    def test_consolidate_is_idempotent(self):
        self.write_session("s2", [
            memory("c1", "注意安全", self.NOW - 3),
            memory("c2", "出门注意安全", self.NOW - 2),
            memory("c3", "记得注意安全", self.NOW - 1),
        ])
        first = governance.run(self.store, now=self.NOW, force=True)
        second = governance.run(self.store, now=self.NOW + 1, force=True)
        self.assertEqual(first["consolidate"]["candidates"],
                         second["consolidate"]["candidates"])
        self.assertTrue(second["consolidate"]["candidates"] >= 1)
        self.assertFalse(second["consolidate"]["changed"])
        doc = json.loads((self.store / "consolidate.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(doc["runs"], 2)

    def test_graph_and_aggregate(self):
        self.write_session("s2", [memory("g1", "苹果 苹果 甜", self.NOW - 5),
                                  memory("g2", "苹果 很甜", self.NOW - 4)])
        out = governance.run(self.store, now=self.NOW, force=True)
        self.assertGreaterEqual(out["graph"]["nodes"], 1)
        self.assertGreaterEqual(out["aggregate"]["sessions"], 2)


class RelationshipTest(StoreCase):
    def test_warm_text_raises_closeness(self):
        self.turn_end(user_text="谢谢你陪我，今天很开心")
        rel = json.loads((self.store / "relationship.json").read_text(encoding="utf-8"))
        self.assertGreater(rel["relationship"]["closeness"], 0.5)
        self.assertGreater(rel["relationship"]["trust"], 0.5)

    def test_conflict_text_raises_conflict(self):
        self.turn_end(user_text="我很生气，别说了")
        rel = json.loads((self.store / "relationship.json").read_text(encoding="utf-8"))
        self.assertGreater(rel["relationship"]["conflict"], 0.0)
        self.assertLess(rel["relationship"]["trust"], 0.5)

    def test_repair_lowers_conflict(self):
        self.turn_end(user_text="我很生气")
        self.turn_end(user_text="对不起，是我不好")
        rel = json.loads((self.store / "relationship.json").read_text(encoding="utf-8"))
        summary = relationship_state.summary(self.store, rel["relationship"])
        self.assertGreaterEqual(summary["repairs"], 1)
        self.assertLess(rel["relationship"]["conflict"], 0.02)

    def test_relationship_off_keeps_values(self):
        write_json(self.data_dir / "flags.json", {"relationship_governance": False})
        self.turn_end(user_text="谢谢你陪我")
        rel = json.loads((self.store / "relationship.json").read_text(encoding="utf-8"))
        self.assertAlmostEqual(rel["relationship"]["closeness"], 0.5, places=4)
        self.assertAlmostEqual(rel["relationship"]["trust"], 0.5, places=4)
        self.assertFalse((self.store / "relationship_memory.json").exists())

    def test_state_exposes_numbers(self):
        self.turn_end(user_text="谢谢你陪我")
        out = pipeline.dispatch("state", self.payload())
        body = out["state"]
        self.assertIn("governance", body)
        self.assertIn("decay", body["governance"])
        self.assertIn("relationship_summary", body)
        self.assertGreaterEqual(body["relationship_summary"]["events"], 1)


if __name__ == "__main__":
    unittest.main()
