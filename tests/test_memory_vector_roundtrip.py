# -*- coding: utf-8 -*-
"""load_memory must carry the vectors stored in sqlite (no re-embedding)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.store import sql_store  # noqa: E402
from biocore_runtime import pipeline as P  # noqa: E402


def store_with_two_rows(with_vector=True):
    tmp = tempfile.mkdtemp()
    root = Path(tmp)
    row = {"id": "r1", "turn": 1, "ts": 1777800000.0, "role": "user",
           "text": "灯箱不亮了。", "hits": 1, "importance": 0.2}
    second = dict(row, id="r2", turn=2, text="师傅明天来。")
    if with_vector:
        row["vector"] = [0.5] * 4
        second["vector"] = [0.25] * 4
    P.save_memory(str(root), "s1", {"session_id": "s1", "entries": [row, second]})
    return tmp


class VectorRoundTripTest(unittest.TestCase):
    def test_entries_come_back_with_their_vectors(self):
        tmp = store_with_two_rows()
        try:
            doc = P.load_memory(tmp, "s1")
            rows = doc.get("entries") or []
            self.assertEqual(len(rows), 2)
            for entry in rows:
                self.assertEqual(len(entry.get("vector") or []), 4)
                self.assertAlmostEqual(entry["vector"][0], 0.5 if entry["id"] == "r1" else 0.25,
                                   places=6)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_row_without_a_vector_gets_an_empty_list_not_none(self):
        tmp = store_with_two_rows(with_vector=False)
        try:
            rows = P.load_memory(tmp, "s1").get("entries") or []
            self.assertEqual(len(rows), 2)
            for entry in rows:
                self.assertEqual(entry.get("vector"), [])
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()