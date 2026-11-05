# -*- coding: utf-8 -*-
"""task-218: recall feedback into affect (回忆回灌情绪).

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_memory_feedback.py"
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from biocore_memory.engine import MemoryEngine
from biocore_memory.core import config as engine_config


def entry(i, text, affect=None, importance=0.5, ts=1700000000.0):
    value = {"id": i, "text": text, "role": "user", "ts": ts,
             "importance": importance, "vector": [], "hits": 1,
             "self_relevance": 0.0, "pin": False, "memory_source": "direct",
             "memory_confidence": 0.7, "previous_versions": [],
             "module": "biocore_memory", "scope": "default"}
    if affect is not None:
        value["affect"] = affect
    return value


class MemoryFeedbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.clock = [1700000000.0]
        self._saved = os.environ.get("BIOCORE_MEMORY_FEEDBACK")
        os.environ.pop("BIOCORE_MEMORY_FEEDBACK", None)

    def tearDown(self):
        self.tmp.cleanup()
        if self._saved is None:
            os.environ.pop("BIOCORE_MEMORY_FEEDBACK", None)
        else:
            os.environ["BIOCORE_MEMORY_FEEDBACK"] = self._saved

    def write(self, entries):
        (self.dir / "memory.json").write_text(
            json.dumps({"entries": entries, "tombstones": [],
                        "schema_version": 1}), encoding="utf-8")

    def engine(self, affect, enabled=True):
        e = MemoryEngine(data_dir=str(self.dir), affect=affect,
                         now=lambda: self.clock[0])
        if enabled:
            e.flags["memory_feedback"] = True
        return e

    # -- switch ---------------------------------------------------------
    def test_flag_defaults_off(self):
        self.assertIs(engine_config.FLAGS.get("memory_feedback"), False)

    def test_off_leaves_affect_unchanged(self):
        self.write([entry("warm", "beach warm", {"valence": 0.9, "arousal": 0.9})])
        affect = {"v": 0.0, "a": 0.5}
        e = self.engine(affect, enabled=False)
        rows = e.recall("beach", budget=3)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(affect["v"], 0.0, places=6)
        self.assertAlmostEqual(affect["a"], 0.5, places=6)
        self.assertIsNone(e._last_memory_feedback)

    # -- basic pull -----------------------------------------------------
    def test_on_pulls_toward_recalled_affect(self):
        self.write([entry("warm", "beach warm", {"valence": 0.8, "arousal": 0.9})])
        affect = {"v": 0.0, "a": 0.5}
        e = self.engine(affect)
        e.recall("beach", budget=3)
        report = e._last_memory_feedback
        self.assertIsNotNone(report)
        self.assertEqual(report["applied"], ["warm"])
        self.assertAlmostEqual(report["delta"][0], 0.02, places=6)
        self.assertAlmostEqual(report["delta"][1], 0.02, places=6)
        self.assertAlmostEqual(affect["v"], 0.02, places=4)
        self.assertAlmostEqual(affect["a"], 0.52, places=4)

    def test_per_turn_cap_both_axes(self):
        self.write([entry("max", "beach max", {"valence": 1.0, "arousal": 1.0})])
        affect = {"v": -1.0, "a": 0.0}
        e = self.engine(affect)
        e.recall("beach", budget=3)
        report = e._last_memory_feedback
        self.assertTrue(report["capped"])
        self.assertAlmostEqual(report["delta"][0], 0.02, places=6)
        self.assertAlmostEqual(report["delta"][1], 0.02, places=6)
        self.assertAlmostEqual(affect["v"], -0.98, places=4)
        self.assertAlmostEqual(affect["a"], 0.02, places=4)

    def test_positive_cap_is_symmetric(self):
        self.write([entry("max", "beach max", {"valence": 1.0, "arousal": 1.0})])
        affect = {"v": -0.2, "a": 0.3}
        e = self.engine(affect)
        e.recall("beach", budget=3)
        self.assertAlmostEqual(affect["v"], -0.18, places=4)
        self.assertAlmostEqual(affect["a"], 0.32, places=4)

    def test_weighted_mean_of_batch(self):
        self.write([
            entry("hi", "beach one", {"valence": 0.9, "arousal": 0.9},
                  importance=1.0),
            entry("lo", "beach two", {"valence": -0.9, "arousal": 0.1},
                  importance=0.0),
        ])
        affect = {"v": 0.0, "a": 0.5}
        e = self.engine(affect)
        e.recall("beach", budget=3)
        report = e._last_memory_feedback
        # weight 1.0 vs 0.0 -> target is the weighty memory (0.9, 0.9)
        self.assertAlmostEqual(report["target"][0], 0.9, places=4)
        self.assertAlmostEqual(report["target"][1], 0.9, places=4)
        self.assertAlmostEqual(affect["v"], 0.02, places=4)

    # -- cooldown -------------------------------------------------------
    def test_cooldown_blocks_same_memory(self):
        self.write([entry("warm", "beach warm", {"valence": 0.8, "arousal": 0.9})])
        affect = {"v": 0.0, "a": 0.5}
        e = self.engine(affect)
        e.recall("beach", budget=3)
        moved = affect["v"]
        self.assertAlmostEqual(moved, 0.02, places=4)
        e.recall("beach", budget=3)
        report = e._last_memory_feedback
        self.assertEqual(report["applied"], [])
        self.assertEqual(report["delta"], [0.0, 0.0])
        self.assertIn("cooldown", [x["reason"] for x in report["skipped"]])
        self.assertAlmostEqual(affect["v"], moved, places=6)

    def test_cooldown_expires_after_window(self):
        self.write([entry("warm", "beach warm", {"valence": 0.8, "arousal": 0.9})])
        affect = {"v": 0.0, "a": 0.5}
        e = self.engine(affect)
        e.recall("beach", budget=3)
        self.clock[0] += engine_config.FEEDBACK_COOLDOWN + 1.0
        e.recall("beach", budget=3)
        report = e._last_memory_feedback
        self.assertEqual(report["applied"], ["warm"])
        self.assertAlmostEqual(affect["v"], 0.04, places=4)

    # -- negative floor / regulation ------------------------------------
    def test_negative_floor_blocks_descent_and_regulates(self):
        self.write([entry("bad", "beach bad", {"valence": -0.9, "arousal": 0.5})])
        affect = {"v": -0.5, "a": 0.5}
        e = self.engine(affect)
        e.recall("beach", budget=3)
        report = e._last_memory_feedback
        self.assertTrue(report["blocked_negative"])
        self.assertEqual(report["delta"][0], 0.0)
        self.assertAlmostEqual(affect["v"], -0.5, places=6)
        regulation = report.get("regulation")
        self.assertIsInstance(regulation, dict)
        self.assertIn(regulation.get("strategy"),
                      ("situation_selection", "situation_modification",
                       "attentional_deployment", "cognitive_reappraisal",
                       "response_modulation"))
        self.assertEqual(report["applied"], [])

    def test_negative_above_floor_still_pulls(self):
        self.write([entry("bad", "beach bad", {"valence": -0.9, "arousal": 0.5})])
        affect = {"v": -0.2, "a": 0.5}
        e = self.engine(affect)
        e.recall("beach", budget=3)
        report = e._last_memory_feedback
        self.assertFalse(report["blocked_negative"])
        self.assertIsNone(report["regulation"])
        self.assertAlmostEqual(affect["v"], -0.22, places=4)

    # -- scope: only the injected top-k ---------------------------------
    def test_only_injected_topk_matters(self):
        self.write([
            entry("hit", "beach picnic", {"valence": 0.9, "arousal": 0.9}),
            entry("miss", "zebra zebra", {"valence": -1.0, "arousal": 0.0}),
        ])
        affect = {"v": 0.0, "a": 0.5}
        e = self.engine(affect)
        rows = e.recall("beach picnic", budget=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entry"]["id"], "hit")
        report = e._last_memory_feedback
        self.assertEqual(report["applied"], ["hit"])
        self.assertAlmostEqual(affect["v"], 0.02, places=4)

    def test_entry_without_affect_is_skipped(self):
        self.write([entry("plain", "beach plain")])
        affect = {"v": 0.0, "a": 0.5}
        e = self.engine(affect)
        e.recall("beach", budget=3)
        report = e._last_memory_feedback
        self.assertEqual(report["applied"], [])
        self.assertEqual(report["reason"], "no_eligible_memory")
        self.assertIn("no_affect", [x["reason"] for x in report["skipped"]])
        self.assertAlmostEqual(affect["v"], 0.0, places=6)

    # -- state-only, env switch, robustness -----------------------------
    def test_memory_entry_is_not_rewritten(self):
        warm = entry("warm", "beach warm", {"valence": 0.8, "arousal": 0.9})
        self.write([warm])
        affect = {"v": 0.0, "a": 0.5}
        e = self.engine(affect)
        e.recall("beach", budget=3)
        stored = e.store.find("warm")
        self.assertIsNotNone(stored)
        self.assertEqual(stored["affect"], {"valence": 0.8, "arousal": 0.9})
        self.assertEqual(len(e.store.entries), 1)

    def test_env_switch_enables(self):
        os.environ["BIOCORE_MEMORY_FEEDBACK"] = "1"
        self.write([entry("warm", "beach warm", {"valence": 0.8, "arousal": 0.9})])
        affect = {"v": 0.0, "a": 0.5}
        e = self.engine(affect, enabled=False)
        e.recall("beach", budget=3)
        self.assertAlmostEqual(affect["v"], 0.02, places=4)

    def test_no_affect_state_is_noop(self):
        self.write([entry("warm", "beach warm", {"valence": 0.8, "arousal": 0.9})])
        e = self.engine(None)
        rows = e.recall("beach", budget=3)
        self.assertEqual(len(rows), 1)
        report = e._last_memory_feedback
        self.assertEqual(report["reason"], "no_affect_state")
        self.assertEqual(report["applied"], [])

    def test_missing_affect_dict_is_noop(self):
        self.write([{"id": "bare", "text": "beach bare", "ts": 1700000000.0,
                     "importance": 0.5, "hits": 1, "affect": {"v": None}}])
        affect = {"v": 0.0, "a": 0.5}
        e = self.engine(affect)
        e.recall("beach", budget=3)
        report = e._last_memory_feedback
        self.assertEqual(report["delta"], [0.0, 0.0])
        self.assertAlmostEqual(affect["v"], 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
