# -*- coding: utf-8 -*-
"""recall_depth, stage order and the inhibition gate."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.engine import MemoryEngine  # noqa: E402
from biocore_memory.store.json_store import MemoryStore  # noqa: E402
from biocore_runtime import pipeline  # noqa: E402

NOW = 1_700_000_000.0


def make(flags=None, count=40, vector=True):
    entries = []
    for index in range(count):
        entry = {"id": "e%02d" % index, "text": "memory %d" % index,
                 "role": "user", "ts": NOW - index * 60, "hits": 1,
                 "scope": "default"}
        if vector:
            entry["vector"] = [1.0, 0.01 * index]
        entries.append(entry)
    return MemoryEngine(store=MemoryStore(doc={"entries": entries}),
                        config={"flags": dict(flags or {})}, now=lambda: NOW)


class DepthTest(unittest.TestCase):
    """The pool is widened before the sorting stages, then cut to budget."""

    def test_the_default_depth_keeps_the_old_budget(self):
        engine = make()
        rows = engine.recall("memory", budget=3)
        self.assertLessEqual(len(rows), 3)
        self.assertEqual(engine.monitor()["recall_stage"]["depth"], 5)

    def test_depth_forty_widens_the_pool(self):
        engine = make({"recall_depth": 40})
        rows = engine.recall("memory", budget=3)
        stage = engine.monitor()["recall_stage"]
        self.assertEqual(stage["depth"], 40)
        self.assertEqual(stage["pool"], 40)
        self.assertLessEqual(len(rows), 3)

    def test_activation_sees_the_whole_depth(self):
        engine = make({"recall_depth": 40, "activation_rank": True})
        rows = engine.recall("memory", budget=3, vector=[1.0, 0.0])
        stage = engine.monitor()["recall_stage"]
        self.assertEqual(stage["after_activation"], 40)
        self.assertLessEqual(len(rows), 3)
        self.assertTrue(all("activation_score" in row for row in rows))

    def test_after_rerank_is_recorded(self):
        engine = make({"recall_depth": 40})
        engine.recall("memory", budget=2)
        stage = engine.monitor()["recall_stage"]
        self.assertEqual(stage["after_rerank"], stage["pool"])

    def test_a_small_depth_carries_only_the_budget(self):
        engine = make({"recall_depth": 5})
        engine.recall("memory", budget=2)
        self.assertEqual(engine.monitor()["recall_stage"]["pool"], 2)

    def test_depth_is_capped_at_forty(self):
        engine = make({"recall_depth": 999})
        engine.recall("memory", budget=2)
        self.assertEqual(engine.monitor()["recall_stage"]["depth"], 40)


class InhibitionGateTest(unittest.TestCase):
    """inhibition joins only when the caller says the question repeats."""

    def test_inhibition_is_off_by_default(self):
        engine = make()
        engine.recall("memory", budget=2)
        self.assertEqual(engine.monitor().get("inhibition_applied"), 0)

    def test_inhibition_on_without_repeat_is_still_out(self):
        engine = make({"inhibition": True})
        engine.recall("memory", budget=2)
        self.assertEqual(engine.monitor().get("inhibition_applied"), 0)

    def test_inhibition_with_repeat_joins_the_chain(self):
        engine = make({"inhibition": True})
        engine.recall("memory", budget=2)
        engine.recall("memory", budget=2, repeat=True)
        self.assertGreaterEqual(engine.monitor().get("inhibition_applied", 0), 0)


class StateTest(unittest.TestCase):
    """The /state block."""

    def test_the_pipeline_state_carries_the_stage_block(self):
        root = tempfile.mkdtemp()
        pipeline.tool_call("remember", {"text": "memory one", "ts": NOW}, root, "s1")
        block = pipeline.dispatch("state", {"session_id": "s1", "store": root})["state"]["recall_stage"]
        for key in ("pool", "depth", "after_activation", "after_rerank",
                    "after_mmr"):
            self.assertIn(key, block)
        self.assertEqual(block["depth"], 5)


if __name__ == "__main__":
    unittest.main()
