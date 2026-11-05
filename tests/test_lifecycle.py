# -*- coding: utf-8 -*-
"""task-36 + task-78: tier hysteresis, reconsolidation, minimal repair loop."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from biocore_memory.store import tiering
from biocore_runtime import lifecycle, pipeline


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def entry(i, text="记得这件事", ts=None, hits=1, importance=0.5):
    return {"id": i, "text": text, "role": "user",
            "ts": ts or (time.time() - 3600), "importance": importance,
            "hits": hits}


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "data"
        self.store = self.data_dir / "memory"
        (self.store / "sessions" / "s1").mkdir(parents=True)
        self.persona = Path(self.tmp.name) / "missing.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write_entries(self, entries):
        write_json(self.store / "sessions" / "s1" / "memory.json",
                   {"entries": entries})
        return entries

    def read_entries(self):
        return json.loads((self.store / "sessions" / "s1" / "memory.json")
                          .read_text(encoding="utf-8"))["entries"]

    def payload(self, **extra):
        data = {"store": str(self.store), "session_id": "s1",
                "persona_profile": str(self.persona)}
        data.update(extra)
        return data


class TierTest(Case):
    def test_enter_hot_at_five_hits(self):
        self.assertEqual(tiering.tier_of(entry("a", hits=5), now=time.time()),
                         "hot")

    def test_stays_hot_between_three_and_five(self):
        now = time.time()
        self.assertEqual(tiering.tier_of(entry("a", hits=4), now=now,
                                         previous="hot"), "hot")

    def test_exits_hot_below_three(self):
        now = time.time()
        self.assertNotEqual(tiering.tier_of(entry("a", hits=2), now=now,
                                            previous="hot"), "hot")

    def test_tick_counts_entered_exited(self):
        now = time.time()
        old_ts = time.time() - 3 * 86400
        rows = [entry("a", hits=5), entry("b", hits=2, ts=old_ts)]
        first = lifecycle.tier_tick(self.store, rows, now=now)
        self.assertEqual(first["counts"]["hot"], 1)
        rows[0]["hits"] = 1
        second = lifecycle.tier_tick(self.store, rows, now=now + 1)
        self.assertGreaterEqual(second["exited"], 1)
        summary = lifecycle.tier_summary(self.store)
        self.assertIn("hot", summary)
        self.assertIn("exited", summary)


class ReconsolidationTest(Case):
    def test_updates_recalled_entry(self):
        now = time.time()
        self.write_entries([entry("a", "苹果很甜", hits=1)])
        lifecycle.record_recall(self.store, "s1", ["a"], now=now)
        result = lifecycle.reconsolidate(self.store, now=now + 60)
        self.assertEqual(result["updated"], 1)
        row = self.read_entries()[0]
        self.assertGreater(row.get("regenerated_at", 0), 0)
        self.assertEqual(row.get("reconsolidation_count"), 1)
        self.assertGreater(row.get("importance", 0), 0.5)
        self.assertEqual(len(self.read_entries()), 1)

    def test_idempotent_second_call(self):
        now = time.time()
        self.write_entries([entry("a", hits=1)])
        lifecycle.record_recall(self.store, "s1", ["a"], now=now)
        lifecycle.reconsolidate(self.store, now=now + 60)
        again = lifecycle.reconsolidate(self.store, now=now + 61)
        self.assertEqual(again["updated"], 0)
        self.assertGreaterEqual(again["skipped"], 1)

    def test_window_expires(self):
        now = time.time()
        self.write_entries([entry("a", hits=1)])
        lifecycle.record_recall(self.store, "s1", ["a"], now=now - 7 * 3600)
        result = lifecycle.reconsolidate(self.store, now=now)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["reason"], "window")

    def test_no_recall_ids(self):
        self.write_entries([entry("a")])
        result = lifecycle.reconsolidate(self.store, now=time.time())
        self.assertEqual(result["updated"], 0)


class RepairTest(Case):
    def test_arm_and_consume_once(self):
        now = time.time()
        self.assertTrue(lifecycle.arm_repair(self.store, "boundary", now=now))
        lines = lifecycle.repair_lines(self.store, now=now + 1)
        self.assertTrue(lines)
        self.assertTrue(any("修复" in line for line in lines))
        self.assertEqual(lifecycle.repair_lines(self.store, now=now + 2), [])

    def test_cooldown_blocks_rearm(self):
        now = time.time()
        lifecycle.arm_repair(self.store, "boundary", now=now)
        lifecycle.repair_lines(self.store, now=now + 1)
        self.assertFalse(lifecycle.arm_repair(self.store, "boundary",
                                             now=now + 2))

    def test_expired_repair_returns_empty(self):
        now = time.time()
        lifecycle.arm_repair(self.store, "boundary", now=now)
        self.assertEqual(lifecycle.repair_lines(self.store,
                                                now=now + 31 * 60), [])

    def test_state_exposes_lifecycle(self):
        now = time.time()
        self.write_entries([entry("a", hits=5)])
        lifecycle.record_recall(self.store, "s1", ["a"], now=now)
        lifecycle.tier_tick(self.store, [entry("a", hits=5)], now=now)
        pipeline.dispatch("turn_end", self.payload(
            user_text="好", assistant_text="嗯。", capture=False))
        body = pipeline.dispatch("state", self.payload())["state"]
        self.assertIn("tiers", body)
        self.assertIn("reconsolidation", body)
        self.assertIn("repair", body)


if __name__ == "__main__":
    unittest.main()
