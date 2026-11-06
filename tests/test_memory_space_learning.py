# -*- coding: utf-8 -*-
"""Usage feedback and axis-weight learning (Xing 2003 / LMNN pull-push).

The reply is checked against what each recalled entry supplied; used/unused
pairs move weight toward the axes on which the used entry was closer. Below 30
rows the equal 0.2 weights stay. Both switches default ON.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory import space as sp  # noqa: E402
from biocore_memory import space_learning as sl  # noqa: E402
from biocore_memory.engine import MemoryEngine  # noqa: E402
from biocore_memory.store.json_store import MemoryStore  # noqa: E402
from biocore_runtime import pipeline  # noqa: E402

NOW = 1_700_000_000.0


def entry(entry_id="e1", text="\u5c0f\u590f\u5468\u4e94\u53bb\u533b\u9662\u590d\u67e5",
          **extra):
    row = {"id": entry_id, "text": text, "role": "user", "ts": NOW,
           "tags": [], "importance": 0.5, "hits": 1, "scope": "default"}
    row.update(extra)
    return row


def feedback_row(query, used, d):
    return {"query": query, "id": "x", "used": used, "ts": NOW, "d": dict(d)}


def many_rows(count=30, used_d=None, unused_d=None):
    rows = []
    for index in range(count // 2):
        query = "q%d" % index
        rows.append(feedback_row(query, True, used_d or
                                 {"semantic": 0.5, "time": 0.5, "affect": 0.1,
                                  "social": 0.5, "activation": 0.5}))
        rows.append(feedback_row(query, False, unused_d or
                                 {"semantic": 0.5, "time": 0.5, "affect": 0.9,
                                  "social": 0.5, "activation": 0.5}))
    return rows


class SwitchTest(unittest.TestCase):
    """Both switches default ON and can be turned off."""

    def test_defaults_are_on(self):
        self.assertTrue(sl.feedback_enabled({}))
        self.assertTrue(sl.learn_enabled({}))
        self.assertFalse(sl.feedback_enabled({"spatial_feedback": False}))
        self.assertFalse(sl.learn_enabled({"spatial_learn": False}))
        self.assertFalse(sl.learn_enabled({}, {"BIOCORE_SPATIAL_LEARN": "off"}))

    def test_eta_defaults_and_is_configurable(self):
        self.assertEqual(sl.eta({}), 0.02)
        self.assertEqual(sl.eta({"spatial_learn_eta": 0.1}), 0.1)
        self.assertEqual(sl.eta({}, {"BIOCORE_SPATIAL_LEARN_ETA": "0.05"}), 0.05)
        self.assertEqual(sl.eta({"spatial_learn_eta": "bad"}), 0.02)


class JudgeTest(unittest.TestCase):
    """Did the reply use this entry?"""

    def test_a_shared_entity_counts(self):
        item = entry(tags=["\u5c0f\u590f"], text="\u5c0f\u590f\u8981\u53bb\u590d\u67e5")
        self.assertTrue(sl.judge_used(item, "\u4f60\u8bf4\u5c0f\u590f\u8981\u53bb\u590d\u67e5\uff0c\u6211\u8bb0\u4e0b\u4e86"))

    def test_shared_numbers_count(self):
        item = entry(text="\u9884\u7ea6\u65f6\u95f4\u662f20241108\u4e0b\u5348")
        self.assertTrue(sl.judge_used(item, "\u597d\u7684\uff0c20241108 \u4e0b\u5348\u89c1"))

    def test_token_overlap_counts(self):
        item = entry(text="\u5c0f\u590f\u5468\u4e94\u53bb\u533b\u9662\u590d\u67e5")
        self.assertTrue(sl.judge_used(item, "\u5468\u4e94\u53bb\u533b\u9662\u590d\u67e5\uff0c\u522b\u5fd8\u4e86"))

    def test_an_unrelated_reply_does_not_count(self):
        item = entry(text="\u5c0f\u590f\u5468\u4e94\u53bb\u533b\u9662\u590d\u67e5")
        self.assertFalse(sl.judge_used(item, "\u4eca\u5929\u5929\u6c14\u4e0d\u9519\uff0c\u9002\u5408\u51fa\u95e8"))
        self.assertFalse(sl.judge_used(item, ""))


class LearnTest(unittest.TestCase):
    """The update direction, the clipping and the normalisation."""

    def test_used_nearer_axis_gains_weight(self):
        weights, pairs = sl.learn(many_rows(10))
        self.assertEqual(pairs, 5)
        self.assertGreater(weights["affect"], weights["semantic"])
        self.assertAlmostEqual(weights["semantic"], weights["time"], places=6)

    def test_weights_are_clipped_and_normalised(self):
        rows = many_rows(10, used_d={"semantic": 0.0, "time": 0.0, "affect": 0.0,
                                     "social": 0.0, "activation": 0.0},
                         unused_d={"semantic": 2.0, "time": 2.0, "affect": 2.0,
                                   "social": 2.0, "activation": 2.0})
        weights, _ = sl.learn(rows, 0.5)
        for axis in sp.AXES:
            self.assertGreaterEqual(weights[axis], 0.0)
            self.assertLessEqual(weights[axis], 0.62)
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=4)

    def test_pairs_only_inside_one_query(self):
        rows = [feedback_row("a", True, {"affect": 0.0}),
                feedback_row("b", False, {"affect": 1.0})]
        weights, pairs = sl.learn(rows)
        self.assertEqual(pairs, 0)
        self.assertEqual(weights, sl.equal_weights())


class PersistenceTest(unittest.TestCase):
    """The weights survive a restart, and so does the history."""

    def test_saved_weights_are_loaded_back(self):
        with tempfile.TemporaryDirectory() as root:
            path = sl.weights_path(root)
            rows = many_rows(30)
            state = sl.learn_and_save(path, rows, now=NOW)
            loaded = sl.load_weights(path)
            self.assertEqual(loaded["samples"], 30)
            self.assertEqual(loaded["updated_at"], round(NOW, 3))
            self.assertEqual(loaded["weights"], state["weights"])

    def test_below_the_sample_floor_the_learner_stays_off(self):
        with tempfile.TemporaryDirectory() as root:
            sl.append_rows(sl.feedback_path(root), many_rows(10))
            view = sl.learning_view(root)
            self.assertFalse(view["reason"] == "")
            self.assertEqual(view["reason"], "sample_too_small")
            self.assertEqual(view["weights"], sl.equal_weights())
            self.assertIsNone(sl.active_weights(root))

    def test_enough_samples_activate_the_weights(self):
        with tempfile.TemporaryDirectory() as root:
            rows = many_rows(30)
            sl.append_rows(sl.feedback_path(root), rows)
            sl.learn_and_save(sl.weights_path(root), rows, now=NOW)
            view = sl.learning_view(root)
            self.assertEqual(view["reason"], "")
            self.assertGreater(view["weights"]["affect"], 0.2)
            self.assertEqual(sl.active_weights(root), view["weights"])

    def test_the_history_keeps_the_last_ten_updates(self):
        with tempfile.TemporaryDirectory() as root:
            path = sl.weights_path(root)
            rows = many_rows(30)
            for step in range(12):
                sl.learn_and_save(path, rows, now=NOW + step)
            loaded = sl.load_weights(path)
            self.assertEqual(len(loaded["history"]), 10)
            self.assertEqual(loaded["history"][-1]["ts"], round(NOW + 11, 3))

    def test_switching_learning_off_returns_equal_weights(self):
        with tempfile.TemporaryDirectory() as root:
            rows = many_rows(30)
            sl.append_rows(sl.feedback_path(root), rows)
            sl.learn_and_save(sl.weights_path(root), rows, now=NOW)
            view = sl.learning_view(root, {"spatial_learn": False})
            self.assertFalse(view["enabled"])
            self.assertEqual(view["reason"], "switch_off")
            self.assertEqual(view["weights"], sl.equal_weights())
            self.assertIsNone(sl.active_weights(root, {"spatial_learn": False}))


class HostFeedbackTest(unittest.TestCase):
    """The turn end judges and appends; the engine then ranks with the weights."""

    def test_a_turn_appends_one_row_per_recalled_entry(self):
        with tempfile.TemporaryDirectory() as root:
            pipeline.tool_call("remember", {"text": "\u5c0f\u590f\u5468\u4e94\u53bb\u533b\u9662\u590d\u67e5",
                                            "ts": NOW, "tags": ["\u5c0f\u590f"]},
                               root, session_id="s1")
            pipeline.tool_call("remember", {"text": "\u5468\u672b\u60f3\u53bb\u770b\u6d77", "ts": NOW},
                               root, session_id="s1")
            found = pipeline.tool_call("recall", {"query": "\u590d\u67e5 \u770b\u6d77",
                                                  "limit": 2}, root, session_id="s1")
            ids = [row["id"] for row in found["results"]]
            self.assertEqual(len(ids), 2)
            out = pipeline.dispatch("turn_end", {
                "session_id": "s1", "user_text": "\u5c0f\u590f\u4ec0\u4e48\u65f6\u5019\u53bb\u533b\u9662",
                "assistant_text": "\u5c0f\u590f\u5468\u4e94\u53bb\u533b\u9662\u590d\u67e5",
                "store": root, "recalled_ids": ids, "now": NOW})
            block = out.get("spatial_feedback") or {}
            self.assertEqual(block.get("rows"), 2)
            self.assertEqual(block.get("used"), 1)
            rows = sl.load_rows(sl.feedback_path(root))
            self.assertEqual(len(rows), 2)
            self.assertEqual(sum(1 for row in rows if row["used"]), 1)
            self.assertEqual(rows[0]["query"], "\u5c0f\u590f\u4ec0\u4e48\u65f6\u5019\u53bb\u533b\u9662")

    def test_the_debug_action_returns_the_last_rows(self):
        with tempfile.TemporaryDirectory() as root:
            sl.append_rows(sl.feedback_path(root), many_rows(4))
            out = pipeline.dispatch("spatial_feedback", {"store": root})
            self.assertTrue(out["ok"])
            self.assertEqual(out["count"], 4)
            self.assertIn("learning", out)

    def test_state_reports_spatial_learning(self):
        with tempfile.TemporaryDirectory() as root:
            sl.append_rows(sl.feedback_path(root), many_rows(30))
            sl.learn_and_save(sl.weights_path(root), many_rows(30), now=NOW)
            out = pipeline.dispatch("state", {"session_id": "s1", "store": root})
            block = out["state"]["spatial_learning"]
            for key in ("enabled", "weights", "samples", "used_rate",
                        "last_update", "reason"):
                self.assertIn(key, block)
            self.assertEqual(block["samples"], 30)
            self.assertGreater(block["weights"]["affect"], 0.2)

    def test_the_engine_ranks_with_the_learned_weights(self):
        with tempfile.TemporaryDirectory() as root:
            rows = many_rows(30)
            sl.append_rows(sl.feedback_path(root), rows)
            sl.learn_and_save(sl.weights_path(root), rows, now=NOW)
            engine = MemoryEngine(data_dir=root, now=lambda: NOW)
            out = engine.spatial_rank("q", query_ts=NOW, limit=2)
            self.assertIn("weights", out)
            self.assertGreater(out["weights"]["affect"], 0.2)
            self.assertEqual(out["weights"], sl.active_weights(root))


if __name__ == "__main__":
    unittest.main()
