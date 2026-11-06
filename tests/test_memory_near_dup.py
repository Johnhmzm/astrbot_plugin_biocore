# -*- coding: utf-8 -*-
"""near_dup_time after the word-table removal.

The judgement is the vector cosine alone: similarity >= near_dup_cosine, text
not literally identical, and nothing else. No topic list, no number/date
regex, no lexical fallback: without vectors the pair is reported with reason
"no_vector" and nothing is marked.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.engine import MemoryEngine  # noqa: E402
from biocore_memory.store import near_dup as nd  # noqa: E402
from biocore_memory.store.json_store import MemoryStore  # noqa: E402
from biocore_runtime import pipeline  # noqa: E402

NOW = 1_700_000_000.0


def engine(flags=None, data_dir=None):
    config = {"flags": dict(flags or {})}
    if data_dir is None:
        return MemoryEngine(store=MemoryStore(), config=config,
                            now=lambda: NOW)
    return MemoryEngine(data_dir=data_dir, config=config, now=lambda: NOW)


def remember(engine_, text, ts, vector=None, **extra):
    event = {"text": text, "role": "user", "ts": ts}
    if vector is not None:
        event["vector"] = list(vector)
    event.update(extra)
    return engine_.remember(event)


class VectorRuleTest(unittest.TestCase):
    """Cosine in, superseded out."""

    def test_a_near_duplicate_marks_the_older_memory(self):
        e = engine()
        old = remember(e, "\u4f1a\u8bae\u6539\u5230\u56db", NOW - 60, [1.0, 0.0])
        new = remember(e, "\u4f1a\u8bae\u6539\u5230\u4e94", NOW, [0.99, 0.14])
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(old["superseded_by"], new["id"])
        self.assertEqual(old["superseded_reason"], "near_dup_time")
        self.assertNotEqual(new.get("status"), "superseded")

    def test_a_below_threshold_pair_is_left_alone(self):
        e = engine()
        old = remember(e, "\u4f1a\u8bae\u6539\u5230\u56db", NOW - 60, [1.0, 0.0])
        new = remember(e, "\u5929\u6c14\u4e0d\u9519", NOW, [0.0, 1.0])
        self.assertNotIn("status", old)
        self.assertNotIn("status", new)

    def test_identical_text_is_not_this_mechanism(self):
        pair = nd.decide({"id": "a", "text": "\u540c\u4e00\u53e5",
                          "vector": [1.0, 0.0], "ts": NOW},
                         {"id": "b", "text": "\u540c\u4e00\u53e5",
                          "vector": [1.0, 0.0], "ts": NOW})
        self.assertEqual(pair["reason"], "identical_text")
        self.assertEqual(pair["action"], "none")

    def test_without_vectors_nothing_is_judged(self):
        e = engine()
        remember(e, "\u4f1a\u8bae\u6539\u5230\u56db", NOW - 60)
        second = remember(e, "\u4f1a\u8bae\u6539\u5230\u4e94", NOW)
        self.assertNotIn("status", second)
        pair = nd.decide({"id": "a", "text": "x", "ts": NOW},
                         {"id": "b", "text": "y", "ts": NOW - 1})
        self.assertEqual(pair["reason"], "no_vector")
        self.assertEqual(pair["metric"], "none")

    def test_a_backdated_write_marks_the_new_entry(self):
        e = engine()
        remember(e, "\u4f1a\u8bae\u6539\u5230\u4e94", NOW, [1.0, 0.0])
        backdated = remember(e, "\u4f1a\u8bae\u6539\u5230\u56db", NOW - 600,
                             [0.99, 0.14])
        self.assertEqual(backdated["status"], "superseded")
        self.assertEqual(backdated["superseded_reason"], "near_dup_time")

    def test_the_threshold_is_configurable(self):
        strict = engine({"near_dup_cosine": 0.999})
        remember(strict, "\u4f1a\u8bae\u6539\u5230\u56db", NOW - 60, [1.0, 0.0])
        second = remember(strict, "\u4f1a\u8bae\u6539\u5230\u4e94", NOW,
                          [0.9, 0.1])
        self.assertNotIn("status", second)
        loose = engine({"near_dup_cosine": 0.5})
        remember(loose, "\u4f1a\u8bae\u6539\u5230\u56db", NOW - 60, [1.0, 0.0])
        keep = remember(loose, "\u4f1a\u8bae\u6539\u5230\u4e94", NOW, [0.9, 0.1])
        self.assertNotIn("status", keep)

    def test_the_switch_off_marks_nothing(self):
        e = engine({"near_dup_time": False})
        remember(e, "\u4f1a\u8bae\u6539\u5230\u56db", NOW - 60, [1.0, 0.0])
        second = remember(e, "\u4f1a\u8bae\u6539\u5230\u4e94", NOW, [1.0, 0.0])
        self.assertNotIn("status", second)


class HostTest(unittest.TestCase):
    """Host path: no vectors means no marking, and the state says so."""

    def store(self):
        return tempfile.mkdtemp()

    def test_a_host_write_without_vectors_is_never_marked(self):
        root = self.store()
        pipeline.tool_call("remember", {"text": "\u4f1a\u8bae\u6539\u5230\u56db",
                                        "ts": NOW - 60}, root, "s1")
        pipeline.tool_call("remember", {"text": "\u4f1a\u8bae\u6539\u5230\u4e94",
                                        "ts": NOW}, root, "s1")
        rows = pipeline.load_memory(root, "s1")["entries"]
        self.assertTrue(all(row.get("status") != "superseded" for row in rows))

    def test_state_reports_the_near_dup_block(self):
        root = self.store()
        pipeline.tool_call("remember", {"text": "\u4f1a\u8bae\u6539\u5230\u56db",
                                        "ts": NOW - 60}, root, "s1")
        state = pipeline.dispatch("state", {"session_id": "s1", "store": root})
        block = state["state"]["memory_versions"]["near_dup"]
        self.assertIn("marked", block)
        self.assertIn("threshold", block)
        self.assertEqual(block["marked"], 0)

    def test_the_debug_action_exists_and_returns_pairs(self):
        root = self.store()
        pipeline.tool_call("remember", {"text": "\u4f1a\u8bae\u6539\u5230\u56db",
                                        "ts": NOW - 60}, root, "s1")
        pipeline.tool_call("remember", {"text": "\u4f1a\u8bae\u6539\u5230\u4e94",
                                        "ts": NOW}, root, "s1")
        out = pipeline.dispatch("near_dup", {"session_id": "s1", "store": root})
        self.assertTrue(out["ok"])
        self.assertIn("pairs", out)


if __name__ == "__main__":
    unittest.main()
