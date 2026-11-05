# -*- coding: utf-8 -*-
"""task-220: growth metrics + read-only consolidation dry-run."""
import json
import tempfile
import unittest
from pathlib import Path

from biocore_runtime import growth


NOW = 1700000000.0


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def memory(entry_id, text, ts=NOW, importance=0.5, affect=None):
    row = {"id": entry_id, "text": text, "role": "user", "ts": ts,
           "importance": importance, "hits": 1}
    if affect is not None:
        row["affect"] = affect
    return row


def trace_row(ts, ids, top=None, intent=""):
    mem = {"recalled_ids": list(ids), "captured_id": ""}
    if top is not None:
        mem["top_score"] = top
    return {"ts": ts, "session_id": "s1", "state_delta": [],
            "intent": {"kind": intent, "weight": 0.0, "reason": ""},
            "constraints": {}, "length": {"scale": 1.0, "source": "state"},
            "gate": {"action": "pass", "rule": "", "label": ""},
            "memory": mem, "modules": {"ran": [], "skipped": []}}


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "store"

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, entries=None, state=None, traces=None,
              relationship=None, flags=None, history=None):
        session = self.root / "sessions" / "s1"
        write_json(session / "memory.json",
                   {"session_id": "s1", "entries": entries or []})
        write_json(session / "state.json", state or {"v": 0.2, "a": 0.4})
        if traces:
            trace_file = self.root / "traces" / "s1.jsonl"
            trace_file.parent.mkdir(parents=True, exist_ok=True)
            trace_file.write_text("\n".join(
                json.dumps(row, ensure_ascii=False) for row in traces) + "\n",
                encoding="utf-8")
        if relationship is not None:
            write_json(self.root / "relationship.json",
                       {"schema_version": 1, "version": 3,
                        "updated_ts": NOW, "relationship": relationship})
        if flags is not None:
            write_json(self.root / "flags.json", flags)
        if history is not None:
            (self.root / "growth_history.jsonl").write_text(
                "\n".join(json.dumps(row, ensure_ascii=False)
                           for row in history) + "\n", encoding="utf-8")
        return str(self.root)

    def snapshot(self):
        files = {}
        base = self.root / "sessions"
        for path in sorted(base.rglob("*")):
            if path.is_file():
                files[str(path)] = path.read_bytes()
        return files


class SwitchTest(StoreCase):
    def test_default_off(self):
        self.assertFalse(growth.enabled({}))
        self.assertTrue(growth.enabled({}, {"BIOCORE_GROWTH_REPORT": "1"}))
        self.assertTrue(growth.enabled({"growth_report": True}))
        self.assertFalse(growth.enabled({"growth_report": False},
                                        {"BIOCORE_GROWTH_REPORT": "1"}))

    def test_disabled_writes_no_report(self):
        store = self.build(entries=[memory("a", "hello")])
        out = growth.consolidate(store, now=NOW)
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "disabled")
        self.assertFalse((Path(store) / "consolidate_report.json").exists())


class MetricsTest(StoreCase):
    def test_empty_store(self):
        store = self.build()
        out = growth.metrics(store, now=NOW)
        self.assertEqual(out["memory"]["total"], 0)
        self.assertEqual(out["memory"]["with_affect_ratio"], 0.0)
        self.assertEqual(out["recall"]["hits_total"], 0)
        self.assertIsNone(out["recall"]["avg_top_score"])
        self.assertEqual(out["narrative"]["top_intents"], [])
        self.assertEqual(out["relation"]["change_7d"],
                         {"trust": 0.0, "closeness": 0.0})
        self.assertEqual(out["relation"]["change_basis"], "no_history")

    def test_fields_present(self):
        store = self.build(entries=[memory("a", "hello")])
        out = growth.metrics(store, now=NOW)
        for key in ("total", "added_this_week", "avg_importance",
                    "with_affect", "with_affect_ratio"):
            self.assertIn(key, out["memory"])
        for key in ("hits_total", "mood_match_hits", "avg_top_score",
                    "score_source"):
            self.assertIn(key, out["recall"])
        for key in ("trust", "closeness", "change_7d", "change_basis"):
            self.assertIn(key, out["relation"])
        self.assertIn("top_intents", out["narrative"])
        for key in growth.LEARNING_FLAGS:
            self.assertIn(key, out["flags"])

    def test_memory_metrics(self):
        store = self.build(entries=[
            memory("a", "one", ts=NOW - 86400, importance=0.6,
                   affect={"valence": 0.4, "arousal": 0.5}),
            memory("b", "two", ts=NOW - 2 * 86400, importance=0.8,
                   affect={"valence": -0.3, "arousal": 0.6}),
            memory("c", "three", ts=NOW - 10 * 86400, importance=0.4),
        ])
        out = growth.metrics(store, now=NOW)["memory"]
        self.assertEqual(out["total"], 3)
        self.assertEqual(out["added_this_week"], 2)
        self.assertAlmostEqual(out["avg_importance"], 0.6, places=4)
        self.assertEqual(out["with_affect"], 2)
        self.assertAlmostEqual(out["with_affect_ratio"], 0.6667, places=3)

    def test_recall_metrics(self):
        store = self.build(
            entries=[
                memory("a", "one", affect={"valence": 0.8, "arousal": 0.7}),
                memory("b", "two", affect={"valence": -0.8, "arousal": 0.1}),
                memory("c", "three", affect={"valence": -0.9, "arousal": 0.2}),
            ],
            state={"v": 0.8, "a": 0.7},
            traces=[trace_row(NOW - 30, ["a", "b"], top=0.8, intent="陪伴"),
                    trace_row(NOW - 20, ["c"], intent="陪伴"),
                    trace_row(NOW - 10, [], intent="好奇")])
        out = growth.metrics(store, now=NOW)["recall"]
        self.assertEqual(out["hits_total"], 3)
        self.assertEqual(out["mood_match_hits"], 1)
        self.assertAlmostEqual(out["avg_top_score"], 0.8, places=4)
        self.assertEqual(out["score_source"], "trace")

    def test_avg_top_score_unavailable(self):
        store = self.build(
            entries=[memory("a", "one")],
            traces=[trace_row(NOW, ["a"])])
        out = growth.metrics(store, now=NOW)["recall"]
        self.assertIsNone(out["avg_top_score"])
        self.assertEqual(out["score_source"], "unavailable")

    def test_narrative_top3(self):
        store = self.build(entries=[memory("a", "one")], traces=[
            trace_row(NOW - 40, [], intent="陪伴"),
            trace_row(NOW - 30, [], intent="陪伴"),
            trace_row(NOW - 20, [], intent="好奇"),
            trace_row(NOW - 10, [], intent="好奇"),
            trace_row(NOW, [], intent="关心"),
        ])
        rows = growth.metrics(store, now=NOW)["narrative"]["top_intents"]
        self.assertEqual(rows[0], {"kind": "陪伴", "count": 2})
        self.assertEqual(len(rows), 3)

    def test_relation_change_7d(self):
        store = self.build(
            relationship={"trust": 0.60, "closeness": 0.58},
            history=[{"ts": NOW - 10 * 86400, "trust": 0.50,
                      "closeness": 0.50},
                     {"ts": NOW - 2 * 86400, "trust": 0.55,
                      "closeness": 0.52}])
        out = growth.metrics(store, now=NOW)["relation"]
        self.assertAlmostEqual(out["change_7d"]["trust"], 0.10, places=4)
        self.assertAlmostEqual(out["change_7d"]["closeness"], 0.08, places=4)
        self.assertEqual(out["change_basis"], "seven_day")

    def test_relation_change_uses_oldest_sample(self):
        store = self.build(
            relationship={"trust": 0.60, "closeness": 0.50},
            history=[{"ts": NOW - 2 * 86400, "trust": 0.55,
                      "closeness": 0.45}])
        out = growth.metrics(store, now=NOW)["relation"]
        self.assertAlmostEqual(out["change_7d"]["trust"], 0.05, places=4)
        self.assertEqual(out["change_basis"], "oldest_sample")

    def test_flags_from_parent_data_dir(self):
        store = self.build(entries=[memory("a", "hello")])
        write_json(Path(store).parent / "flags.json",
                   {"memory_feedback": True})
        out = growth.metrics(store, now=NOW)["flags"]["memory_feedback"]
        self.assertEqual(out, {"enabled": True, "source": "flags.json"})

    def test_flags_sources(self):
        store = self.build(flags={"mood_recall": True})
        out = growth.metrics(
            store, now=NOW, flags={"affect_encoding": True},
            env={"BIOCORE_PREFERENCE_DRIFT": "1"})["flags"]
        self.assertEqual(out["mood_recall"],
                         {"enabled": True, "source": "flags.json"})
        self.assertEqual(out["affect_encoding"],
                         {"enabled": True, "source": "flags"})
        self.assertEqual(out["preference_drift"],
                         {"enabled": True, "source": "env"})
        self.assertEqual(out["memory_feedback"],
                         {"enabled": False, "source": "default"})


class ConsolidateTest(StoreCase):
    def test_dry_run_does_not_write_memory(self):
        store = self.build(entries=[
            memory("a", "注意安全", ts=NOW - 30),
            memory("b", "出门注意安全", ts=NOW - 20),
            memory("c", "记得注意安全", ts=NOW - 10),
        ])
        before = self.snapshot()
        growth.consolidate(store, now=NOW, enabled=True)
        self.assertEqual(self.snapshot(), before)

    def test_report_is_written(self):
        store = self.build(entries=[memory("a", "注意安全")])
        out = growth.consolidate(store, now=NOW, enabled=True)
        path = Path(store) / "consolidate_report.json"
        self.assertTrue(path.exists())
        report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(report["schema"], "bc.consolidate_report.v1")
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["memory_written"])
        self.assertIn("candidates", report)
        self.assertEqual(out["report"], report)
        self.assertTrue((Path(store) / "growth_history.jsonl").exists())

    def test_idempotent_same_day(self):
        store = self.build(
            entries=[memory("a", "注意安全", ts=NOW - 30),
                     memory("b", "注意安全", ts=NOW - 20)],
            relationship={"trust": 0.8, "closeness": 0.7})
        first = growth.consolidate(store, now=NOW, enabled=True)["report"]
        second = growth.consolidate(store, now=NOW, enabled=True)["report"]
        self.assertEqual(first, second)
        lines = (Path(store) / "growth_history.jsonl").read_text(
            encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)

    def test_repeated_topic_candidate(self):
        store = self.build(entries=[
            memory("a", "注意安全", ts=NOW - 30),
            memory("b", "出门注意安全", ts=NOW - 20),
            memory("c", "记得注意安全", ts=NOW - 10),
        ])
        report = growth.consolidate(store, now=NOW, enabled=True)["report"]
        topic = [row for row in report["candidates"]
                 if row["kind"] == "repeated_topic"]
        self.assertTrue(topic)
        self.assertEqual(topic[0]["topic"], "安全")
        self.assertEqual(topic[0]["count"], 3)
        self.assertEqual(topic[0]["dimension"], "security")
        self.assertEqual(report["counts"]["repeated_topic"], len(topic))

    def test_stable_relation_candidate(self):
        store = self.build(
            entries=[memory("a", "hello")],
            relationship={"trust": 0.72, "closeness": 0.66,
                          "conflict": 0.05, "days_known": 12,
                          "attachment_style": "secure"})
        report = growth.consolidate(store, now=NOW, enabled=True)["report"]
        stable = [row for row in report["candidates"]
                  if row["kind"] == "stable_relation"]
        self.assertEqual(len(stable), 1)
        self.assertAlmostEqual(stable[0]["trust"], 0.72, places=4)
        self.assertIn("12", stable[0]["fact"])

    def test_low_relation_has_no_candidate(self):
        store = self.build(
            entries=[memory("a", "hello")],
            relationship={"trust": 0.4, "closeness": 0.5})
        report = growth.consolidate(store, now=NOW, enabled=True)["report"]
        self.assertEqual(report["counts"]["stable_relation"], 0)

    def test_empty_store_report(self):
        store = self.build()
        report = growth.consolidate(store, now=NOW, enabled=True)["report"]
        self.assertEqual(report["candidates"], [])
        self.assertEqual(report["episodes"]["scanned"], 0)
        self.assertEqual(report["counts"],
                         {"repeated_topic": 0, "stable_relation": 0})


if __name__ == "__main__":
    unittest.main()
