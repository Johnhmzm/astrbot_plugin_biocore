# -*- coding: utf-8 -*-
"""activation_update: a returned hit is an access."""
import json
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


def make(flags=None, count=3):
    entries = [{"id": "e%d" % i, "text": "memory %d" % i, "role": "user",
                "ts": NOW - i * 60, "hits": 1, "scope": "default"}
               for i in range(count)]
    return MemoryEngine(store=MemoryStore(doc={"entries": entries}),
                        config={"flags": dict(flags or {})}, now=lambda: NOW)


class UpdateTest(unittest.TestCase):
    """Only the rows that come back are touched."""

    def test_a_returned_hit_gets_one_more_hit(self):
        engine = make()
        rows = engine.recall("memory", budget=1)
        entry = engine.store.find(rows[0]["entry"]["id"])
        self.assertEqual(entry["hits"], 2)

    def test_the_other_entries_are_untouched(self):
        engine = make()
        rows = engine.recall("memory", budget=1)
        returned = rows[0]["entry"]["id"]
        for other in engine.store.entries:
            if other["id"] != returned:
                self.assertEqual(other["hits"], 1)

    def test_the_same_row_twice_in_one_turn_counts_once(self):
        engine = make()
        row = {"entry": engine.store.find("e0")}
        engine._apply_activation_update([row, row], NOW)
        entry = engine.store.find("e0")
        self.assertEqual(entry["hits"], 2)

    def test_last_hit_is_the_recall_moment(self):
        engine = make()
        rows = engine.recall("memory", budget=1)
        entry = engine.store.find(rows[0]["entry"]["id"])
        self.assertAlmostEqual(entry["last_hit"], NOW, places=3)

    def test_retrieval_count_accumulates(self):
        engine = make()
        rows = engine.recall("memory", budget=1)
        entry = engine.store.find(rows[0]["entry"]["id"])
        self.assertEqual(entry.get("retrieval_count"), 1)

    def test_space_activation_is_refreshed(self):
        entries = [{"id": "e0", "text": "memory 0", "role": "user", "ts": NOW,
                    "hits": 1, "scope": "default",
                    "space": {"activation": {"hits": 1, "last_hit": NOW - 99}}}]
        engine = MemoryEngine(store=MemoryStore(doc={"entries": entries}),
                              config={"flags": {"spatial_recall": True}},
                              now=lambda: NOW)
        rows = engine.recall("memory", budget=1)
        entry = engine.store.find(rows[0]["entry"]["id"])
        activation = entry["space"]["activation"]
        self.assertEqual(activation["hits"], entry["hits"])
        self.assertAlmostEqual(activation["last_hit"], NOW, places=3)

    def test_the_switch_off_writes_nothing(self):
        engine = make({"activation_update": False})
        rows = engine.recall("memory", budget=1)
        entry = engine.store.find(rows[0]["entry"]["id"])
        self.assertEqual(entry["hits"], 1)
        self.assertNotIn("last_hit", entry)

    def test_the_returned_rows_are_unchanged(self):
        engine = make()
        rows = engine.recall("memory", budget=2)
        self.assertEqual(len(rows), 2)
        self.assertIn("score", rows[0])

    def test_the_state_reports_the_update(self):
        engine = make()
        engine.recall("memory", budget=1)
        block = engine.monitor()["activation_update"]
        self.assertTrue(block["enabled"])
        self.assertEqual(block["updated"], 1)
        self.assertAlmostEqual(block["last_ts"], NOW, places=3)

    def test_the_write_reaches_the_store_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "memory.json"
            store = MemoryStore(path=str(path), doc={"entries": [
                {"id": "e0", "text": "memory 0", "role": "user", "ts": NOW,
                 "hits": 1, "scope": "default"}]})
            store.save()
            engine = MemoryEngine(store=MemoryStore.load(path), now=lambda: NOW)
            engine.recall("memory", budget=1)
            engine.store.save()
            rows = json.loads(path.read_text(encoding="utf-8"))["entries"]
            self.assertEqual(rows[0]["hits"], 2)
            self.assertIn("last_hit", rows[0])


if __name__ == "__main__":
    unittest.main()
