# -*- coding: utf-8 -*-
"""task-126: rollback snapshot/restore + bounded ring tests."""
import unittest
from pathlib import Path

from biocore_model import rollback

REPO = Path(__file__).resolve().parents[2]


def _doc():
    return {
        "state": {"v": 0.2, "a": 0.6, "d": 0.5, "social": 0.4,
                  "stress": 0.3, "energy": 0.7, "trust": 0.55,
                  "echo": 0.1, "echo_trace": 0.1, "attention": 0.5,
                  "boredom": 0.1, "novelty_need": 0.4,
                  "boundary_pressure": 0.0, "refusal_readiness": 0.0,
                  "conflict_ema": 0.0, "rumination_ema": 0.0, "ticks": 7,
                  "unknown": 99, "label": "x", "flag": True},
        "needs": {"belonging": 0.6, "self_esteem": 0.5, "control": 0.4,
                  "meaningful_existence": 0.55, "other": 0.1},
        "relationship": {"trust": 0.55, "state": {"closeness": 0.6},
                         "repair_state": {"phase": "stable"}},
        "recent_turns": [{"role": "user", "text": "a"},
                         {"role": "assistant", "text": "b"}],
        "memory_marker": {"entries": ["id1"], "turn": {"count": 1}},
    }


class SnapshotTest(unittest.TestCase):
    def test_state_whitelist_only(self):
        snap = rollback.snapshot(_doc())
        self.assertNotIn("unknown", snap["state"])
        self.assertNotIn("label", snap["state"])
        self.assertNotIn("flag", snap["state"])
        self.assertEqual(snap["state"]["v"], 0.2)
        self.assertIn("ticks", snap["state"])

    def test_needs_whitelist(self):
        snap = rollback.snapshot(_doc())
        self.assertNotIn("other", snap["needs"])
        self.assertEqual(snap["needs"]["belonging"], 0.6)

    def test_relationship_and_recent_copied(self):
        doc = _doc()
        snap = rollback.snapshot(doc)
        self.assertEqual(snap["relationship"]["trust"], 0.55)
        self.assertEqual(len(snap["recent_turns"]), 2)
        self.assertEqual(snap["memory_marker"]["entries"], ["id1"])
        doc["relationship"]["trust"] = 0.9
        doc["recent_turns"].append({"role": "user", "text": "c"})
        self.assertEqual(snap["relationship"]["trust"], 0.55)
        self.assertEqual(len(snap["recent_turns"]), 2)

    def test_recent_turns_bounded(self):
        doc = _doc()
        doc["recent_turns"] = [{"role": "user", "text": str(i)}
                               for i in range(20)]
        snap = rollback.snapshot(doc)
        self.assertEqual(len(snap["recent_turns"]), rollback.RECENT_LIMIT)
        self.assertEqual(snap["recent_turns"][-1]["text"], "19")
        snap2 = rollback.snapshot(doc, recent_limit=3)
        self.assertEqual(len(snap2["recent_turns"]), 3)

    def test_empty_and_none_are_safe(self):
        for value in (None, {}, [], "x"):
            snap = rollback.snapshot(value)
            self.assertIsInstance(snap, dict)
            self.assertEqual(snap["state"], {})
            self.assertEqual(snap["recent_turns"], [])


class RestoreTest(unittest.TestCase):
    def test_restore_applies_all_fields(self):
        snap = rollback.snapshot(_doc())
        target = {"state": {"v": -0.5, "stress": 0.9}, "needs": {},
                  "relationship": {}, "recent_turns": []}
        out = rollback.restore(target, snap)
        self.assertAlmostEqual(out["state"]["v"], 0.2)
        self.assertAlmostEqual(out["state"]["stress"], 0.3)
        self.assertEqual(out["needs"]["control"], 0.4)
        self.assertEqual(len(out["recent_turns"]), 2)
        self.assertEqual(out["memory_marker"]["entries"], ["id1"])

    def test_restore_empty_snapshot_keeps_doc(self):
        target = _doc()
        out = rollback.restore(target, {})
        self.assertEqual(out["state"]["v"], 0.2)
        out2 = rollback.restore(target, None)
        self.assertEqual(out2["state"]["stress"], 0.3)

    def test_restore_malformed_snapshot_is_safe(self):
        target = {"state": {"v": 0.1}}
        for snap in ([], "x", {"state": "nope"}, {"needs": 5}):
            out = rollback.restore(target, snap)
            self.assertEqual(out["state"]["v"], 0.1)

    def test_restore_does_not_mutate_inputs(self):
        doc = _doc()
        snap = rollback.snapshot(doc)
        before_doc = repr(doc)
        before_snap = repr(snap)
        rollback.restore(doc, snap)
        self.assertEqual(repr(doc), before_doc)
        self.assertEqual(repr(snap), before_snap)

    def test_roundtrip(self):
        doc = _doc()
        snap = rollback.snapshot(doc)
        doc["state"]["v"] = -0.9
        doc["recent_turns"] = []
        doc["relationship"]["trust"] = 0.1
        restored = rollback.restore(doc, snap)
        self.assertAlmostEqual(restored["state"]["v"], 0.2)
        self.assertEqual(len(restored["recent_turns"]), 2)
        self.assertEqual(restored["relationship"]["trust"], 0.55)


class RingTest(unittest.TestCase):
    def _snap(self, value):
        return {"state": {"v": value}}

    def test_push_bounded_to_limit(self):
        ring = []
        for index in range(15):
            ring = rollback.push(ring, self._snap(index / 10.0))
        self.assertEqual(len(ring), rollback.RING_LIMIT)
        self.assertAlmostEqual(ring[-1]["state"]["v"], 1.4)
        self.assertAlmostEqual(ring[0]["state"]["v"], 0.5)

    def test_push_copies_snapshot(self):
        snap = self._snap(0.3)
        ring = rollback.push([], snap)
        snap["state"]["v"] = -1.0
        self.assertAlmostEqual(ring[0]["state"]["v"], 0.3)

    def test_pop_newest_first(self):
        ring = rollback.push(rollback.push([], self._snap(0.1)),
                             self._snap(0.2))
        left, latest = rollback.pop(ring)
        self.assertAlmostEqual(latest["state"]["v"], 0.2)
        self.assertEqual(len(left), 1)

    def test_pop_empty(self):
        self.assertEqual(rollback.pop([]), ([], None))
        self.assertEqual(rollback.pop(None), ([], None))

    def test_consecutive_two_rollbacks(self):
        ring = []
        for value in (0.1, 0.2, 0.3):
            ring = rollback.push(ring, self._snap(value))
        ring, first = rollback.pop(ring)
        ring, second = rollback.pop(ring)
        self.assertAlmostEqual(first["state"]["v"], 0.3)
        self.assertAlmostEqual(second["state"]["v"], 0.2)
        self.assertEqual(len(ring), 1)

    def test_can_rollback_and_describe(self):
        self.assertFalse(rollback.can_rollback([]))
        self.assertTrue(rollback.can_rollback([{"state": {}}]))
        snap = rollback.snapshot(_doc())
        self.assertIn("v=0.20", rollback.describe(snap))
        self.assertEqual(rollback.describe(None), "没有可回退的轮次")


class WiringStaticTest(unittest.TestCase):
    def test_main_has_rollback_command_and_ring(self):
        source = (REPO / "main.py").read_text(encoding="utf-8")
        self.assertIn("sub == \"rollback\"", source)
        self.assertIn("_rollback_ring", source)
        self.assertIn("_rollback_doc", source)


if __name__ == "__main__":
    unittest.main()
