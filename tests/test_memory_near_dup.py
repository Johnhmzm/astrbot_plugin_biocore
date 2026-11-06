# -*- coding: utf-8 -*-
"""near_dup_time: a changed fact arrives as a near duplicate; the newer wins.

Similarity (cosine, lexical fallback) + topic/entity overlap + different
numbers/dates marks the older entry superseded. It is not version resolution:
no subject, no attribute, no keyword list.
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


def remember(engine_, text, ts, tags=None, vector=None, **extra):
    event = {"text": text, "role": "user", "ts": ts}
    if tags is not None:
        event["tags"] = list(tags)
    if vector is not None:
        event["vector"] = list(vector)
    event.update(extra)
    return engine_.remember(event)


class CosineRuleTest(unittest.TestCase):
    """The four gates, checked one at a time."""

    def test_a_changed_birthday_marks_the_old_memory(self):
        e = engine()
        old = remember(e, "\u5c0f\u590f\u751f\u65e5\u6539\u62104\u67083\u65e5", NOW - 60,
                       tags=["\u751f\u65e5"], vector=[1.0, 0.0])
        new = remember(e, "\u5c0f\u590f\u751f\u65e5\u6539\u62105\u670830\u65e5", NOW,
                       tags=["\u751f\u65e5"], vector=[0.99, 0.14])
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(old["superseded_by"], new["id"])
        self.assertEqual(old["superseded_reason"], "near_dup_time")
        self.assertNotEqual(new.get("status"), "superseded")

    def test_supplementary_information_keeps_both(self):
        e = engine()
        remember(e, "\u5c0f\u590f\u7684\u7535\u5f71\u7968\u4e70\u597d\u4e86", NOW - 60,
                 tags=["\u7535\u5f71"], vector=[1.0, 0.0])
        second = remember(e, "\u5c0f\u590f\u7684\u7535\u5f71\u7968\u4e70\u597d\u4e86\uff0c\u8fd8\u52a0\u4e86\u7206\u7c73\u82b1",
                          NOW, tags=["\u7535\u5f71"], vector=[0.98, 0.2])
        self.assertNotEqual(second.get("status"), "superseded")
        self.assertEqual(len([x for x in e.store.entries
                              if x.get("status") == "superseded"]), 0)

    def test_a_different_topic_is_never_a_near_duplicate(self):
        e = engine()
        remember(e, "\u5c0f\u590f\u751f\u65e5\u6539\u62104\u67083\u65e5", NOW - 60,
                 tags=["\u751f\u65e5"], vector=[1.0, 0.0])
        second = remember(e, "\u5c0f\u590f\u5de5\u4f5c\u6539\u52304\u67083\u65e5", NOW,
                          tags=["\u5de5\u4f5c"], vector=[1.0, 0.0])
        self.assertNotEqual(str((second).get("status") or ""), "superseded")

    def test_the_same_numbers_are_not_a_change(self):
        e = engine()
        remember(e, "\u5c0f\u590f\u751f\u65e5\u6539\u62104\u67083\u65e5", NOW - 60,
                 tags=["\u751f\u65e5"], vector=[1.0, 0.0])
        second = remember(e, "\u5c0f\u590f\u751f\u65e5\u6539\u62104\u67083\u65e5\u4e86", NOW,
                          tags=["\u751f\u65e5"], vector=[1.0, 0.0])
        self.assertNotEqual(str((second).get("status") or ""), "superseded")

    def test_a_backdated_write_marks_the_new_entry(self):
        e = engine()
        remember(e, "\u5c0f\u590f\u751f\u65e5\u6539\u62105\u670830\u65e5", NOW,
                 tags=["\u751f\u65e5"], vector=[1.0, 0.0])
        backdated = remember(e, "\u5c0f\u590f\u751f\u65e5\u6539\u62104\u67083\u65e5", NOW - 600,
                             tags=["\u751f\u65e5"], vector=[0.99, 0.14])
        self.assertEqual(backdated["status"], "superseded")
        self.assertEqual(backdated["superseded_reason"], "near_dup_time")

    def test_the_threshold_is_configurable(self):
        strict = engine({"near_dup_cosine": 0.999})
        remember(strict, "\u5c0f\u590f\u751f\u65e5\u6539\u62104\u67083\u65e5", NOW - 60,
                 tags=["\u751f\u65e5"], vector=[1.0, 0.0])
        second = remember(strict, "\u5c0f\u590f\u751f\u65e5\u6539\u62105\u670830\u65e5", NOW,
                          tags=["\u751f\u65e5"], vector=[0.9, 0.1])
        self.assertNotEqual(str((second).get("status") or ""), "superseded")
        loose = engine({"near_dup_cosine": 0.5})
        remember(loose, "\u5c0f\u590f\u751f\u65e5\u6539\u62104\u67083\u65e5", NOW - 60,
                 tags=["\u751f\u65e5"], vector=[1.0, 0.0])
        marked = remember(loose, "\u5c0f\u590f\u751f\u65e5\u6539\u62105\u670830\u65e5", NOW,
                          tags=["\u751f\u65e5"], vector=[0.9, 0.1])
        self.assertNotEqual(str((marked).get("status") or ""), "superseded")


class SwitchAndSimilarityTest(unittest.TestCase):
    """Switch off is the old behaviour; similarity falls back to words."""

    def test_switching_off_marks_nothing(self):
        e = engine({"near_dup_time": False})
        remember(e, "\u5c0f\u590f\u751f\u65e5\u6539\u62104\u67083\u65e5", NOW - 60,
                 tags=["\u751f\u65e5"], vector=[1.0, 0.0])
        second = remember(e, "\u5c0f\u590f\u751f\u65e5\u6539\u62105\u670830\u65e5", NOW,
                          tags=["\u751f\u65e5"], vector=[1.0, 0.0])
        self.assertNotEqual(str((second).get("status") or ""), "superseded")
        self.assertEqual(nd.state_of(e.store.entries, None, {"near_dup_time": False})["marked"], 0)

    def test_similarity_uses_words_without_vectors(self):
        left = {"id": "a", "text": "\u5c0f\u590f\u5468\u4e94\u53bb\u533b\u9662\u590d\u67e5"}
        same = {"id": "b", "text": "\u5c0f\u590f\u5468\u4e94\u53bb\u533b\u9662\u590d\u67e5"}
        other = {"id": "c", "text": "\u4eca\u5929\u5929\u6c14\u4e0d\u9519"}
        self.assertEqual(nd.similarity(left, same), 1.0)
        self.assertLess(nd.similarity(left, other), 0.2)
        self.assertEqual(nd.similarity({"vector": [1.0, 0.0]},
                                       {"vector": [0.0, 1.0]}), 0.0)

    def test_numbers_and_dates_are_extracted(self):
        self.assertEqual(nd.numeric_tokens("\u751f\u65e5\u6539\u62104\u67083\u65e5"),
                         ["4\u67083\u65e5"])
        self.assertNotEqual(nd.numeric_tokens("\u751f\u65e5\u6539\u62104\u67083\u65e5"),
                            nd.numeric_tokens("\u751f\u65e5\u6539\u62105\u670830\u65e5"))
        self.assertEqual(nd.numeric_tokens("\u9884\u7ea62024-11-08\u4e0b\u5348"),
                         ["2024-11-08"])

    def test_entities_can_carry_the_overlap(self):
        left = {"id": "a", "text": "\u5f00\u4f1a\u6539\u672c\u5468\u4e94", "entities": ["\u4f1a\u8bae\u5ba4"]}
        right = {"id": "b", "text": "\u5f00\u4f1a\u6539\u4e0b\u5468\u4e94", "entities": ["\u4f1a\u8bae\u5ba4"]}
        self.assertTrue(nd._entities(left) & nd._entities(right))


class MetricTest(unittest.TestCase):
    """One mechanism, two rulers: the bar belongs to the measure."""

    def test_the_defaults_are_per_measure(self):
        self.assertEqual(nd.threshold(metric="cosine"), 0.90)
        self.assertEqual(nd.threshold(metric="jaccard"), 0.75)
        self.assertEqual(nd.threshold({}), 0.90)      # historical signature

    def test_each_measure_has_its_own_knob(self):
        flags = {"near_dup_cosine": 0.95, "near_dup_jaccard": 0.6}
        self.assertEqual(nd.threshold(flags, metric="cosine"), 0.95)
        self.assertEqual(nd.threshold(flags, metric="jaccard"), 0.6)

    def test_a_cosine_of_087_is_not_enough_any_more(self):
        e = engine()
        remember(e, "\u5c0f\u590f\u7684\u805a\u4f1a\u6539\u52304\u67083\u65e5", NOW - 60,
                 tags=["\u805a\u4f1a"], vector=[1.0, 0.0])
        second = remember(e, "\u5c0f\u590f\u7684\u805a\u4f1a\u6539\u52305\u670830\u65e5", NOW,
                          tags=["\u805a\u4f1a"], vector=[0.87, 0.49])
        self.assertNotEqual(second.get("status"), "superseded")

    def test_the_jaccard_bar_catches_the_chinese_paraphrase(self):
        e = engine()
        remember(e, "\u5c0f\u590f\u7684\u805a\u4f1a\u6539\u52304\u67083\u65e5", NOW - 60,
                 tags=["\u805a\u4f1a"])
        second = remember(e, "\u5c0f\u590f\u7684\u805a\u4f1a\u6539\u52305\u670830\u65e5", NOW,
                          tags=["\u805a\u4f1a"])
        self.assertNotEqual(second.get("status"), "superseded")
        marked = [x for x in e.store.entries if x.get("status") == "superseded"]
        self.assertEqual(len(marked), 1)
        self.assertEqual(marked[0]["superseded_reason"], "near_dup_time")

    def test_the_decision_records_which_ruler_was_used(self):
        with tempfile.TemporaryDirectory() as root:
            e = engine(data_dir=root)
            remember(e, "\u5c0f\u590f\u7684\u805a\u4f1a\u6539\u52304\u67083\u65e5", NOW - 60,
                     tags=["\u805a\u4f1a"])
            remember(e, "\u5c0f\u590f\u7684\u805a\u4f1a\u6539\u52305\u670830\u65e5", NOW,
                     tags=["\u805a\u4f1a"])
            block = nd.state_of(e.store.entries, root, {})
            self.assertEqual(block["metric"], "jaccard")
            self.assertEqual(block["last_pair"]["metric"], "jaccard")
            self.assertAlmostEqual(block["last_pair"]["similarity"], 0.789474,
                                   places=5)


class HostTest(unittest.TestCase):
    """The host path: marking, filtering, state and the debug action."""

    def store(self, threshold=None):
        root = tempfile.mkdtemp()
        flags = ({"near_dup_jaccard": threshold} if threshold is not None
                 else {})
        if flags:
            Path(root, "flags.json").write_text(json.dumps(flags), encoding="utf-8")
        return root

    def test_identical_text_goes_to_dedupe_not_here(self):
        root = self.store()
        first = pipeline.tool_call("remember", {"text": "\u5c0f\u590f\u5468\u4e94\u53bb\u533b\u9662\u590d\u67e5",
                                                "ts": NOW}, root, "s1")
        again = pipeline.tool_call("remember", {"text": "\u5c0f\u590f\u5468\u4e94\u53bb\u533b\u9662\u590d\u67e5",
                                                "ts": NOW + 5}, root, "s1")
        self.assertTrue(again.get("deduped"))
        rows = json.loads((Path(root) / "sessions" / "s1" / "memory.json")
                          .read_text(encoding="utf-8"))["entries"]
        self.assertEqual(len(rows), 1)
        self.assertNotEqual(str((rows[0]).get("status") or ""), "superseded")
        self.assertEqual(rows[0]["id"], first["entry"]["id"])

    def test_the_host_marks_and_filters(self):
        root = self.store(threshold=0.3)
        pipeline.tool_call("remember", {"text": "\u5c0f\u590f\u751f\u65e5\u6539\u62104\u67083\u65e5",
                                        "ts": NOW - 60, "tags": ["\u751f\u65e5"]},
                           root, "s1")
        pipeline.tool_call("remember", {"text": "\u5c0f\u590f\u751f\u65e5\u6539\u62105\u670830\u65e5",
                                        "ts": NOW, "tags": ["\u751f\u65e5"]},
                           root, "s1")
        plain = pipeline.tool_call("recall", {"query": "\u751f\u65e5", "limit": 5},
                                   root, "s1")
        history = pipeline.tool_call("recall", {"query": "\u751f\u65e5", "limit": 5,
                                                "include_superseded": True},
                                     root, "s1")
        self.assertEqual(len(plain["results"]), 1)
        self.assertEqual(len(history["results"]), 2)
        statuses = {row["text"]: row.get("status") for row in history["results"]}
        self.assertEqual(statuses["\u5c0f\u590f\u751f\u65e5\u6539\u62104\u67083\u65e5"],
                         "superseded")

    def test_state_and_debug_expose_the_decision(self):
        root = self.store(threshold=0.3)
        pipeline.tool_call("remember", {"text": "\u5c0f\u590f\u751f\u65e5\u6539\u62104\u67083\u65e5",
                                        "ts": NOW - 60, "tags": ["\u751f\u65e5"]},
                           root, "s1")
        pipeline.tool_call("remember", {"text": "\u5c0f\u590f\u751f\u65e5\u6539\u62105\u670830\u65e5",
                                        "ts": NOW, "tags": ["\u751f\u65e5"]},
                           root, "s1")
        state = pipeline.dispatch("state", {"session_id": "s1", "store": root})
        block = state["state"]["memory_versions"]["near_dup"]
        self.assertEqual(block["marked"], 1)
        self.assertEqual(block["threshold"], 0.3)
        self.assertEqual(block["metric"], "jaccard")
        self.assertTrue(block["last_pair"])
        debug = pipeline.dispatch("near_dup", {"store": root, "session_id": "s1"})
        self.assertTrue(debug["ok"])
        self.assertLessEqual(len(debug["pairs"]), 5)
        self.assertTrue(any(pair.get("reason") == "near_dup_time"
                            for pair in debug["pairs"]))


if __name__ == "__main__":
    unittest.main()
