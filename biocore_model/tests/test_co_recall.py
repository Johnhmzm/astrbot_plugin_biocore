# -*- coding: utf-8 -*-
"""task-187 共召回统计单测：配对、去重、阈值、30 天时间窗、标记、畸形/空输入。

只依赖 biocore_memory.co_recall；使用临时 SQLite 文件，不碰真实 memory 库，
不导入 main.py，不新增 LLM 调用。
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from biocore_memory import co_recall as cr

NOW = 1_700_000_000.0
DAY = 86400.0


class CoRecallStorageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "memory" / "memory.sqlite3"

    def tearDown(self):
        self._tmp.cleanup()


class PureFunctionTest(unittest.TestCase):
    def test_normalize_id(self):
        self.assertEqual(cr.normalize_id("  a  "), "a")
        self.assertEqual(cr.normalize_id(3), "3")
        for bad in (None, "", "   ", {}, [], ("x",)):
            self.assertEqual(cr.normalize_id(bad), "")

    def test_unique_ids(self):
        self.assertEqual(cr.unique_ids(["b", "a", "b", "", None, "a"]),
                         ["b", "a"])
        self.assertEqual(cr.unique_ids("a,b"), [])
        self.assertEqual(cr.unique_ids(None), [])

    def test_pair_key_is_unordered(self):
        self.assertEqual(cr.pair_key("b", "a"), ("a", "b"))
        self.assertEqual(cr.pair_key("a", "b"), ("a", "b"))
        self.assertIsNone(cr.pair_key("a", "a"))
        self.assertIsNone(cr.pair_key("", "b"))
        self.assertIsNone(cr.pair_key(None, "b"))

    def test_pairs_unordered_and_deduped(self):
        self.assertEqual(cr.pairs(["c", "a", "b", "a", None, ""]),
                         [("a", "b"), ("a", "c"), ("b", "c")])
        self.assertEqual(cr.pairs([]), [])
        self.assertEqual(cr.pairs(None), [])
        self.assertEqual(cr.pairs("not-a-list"), [])

    def test_pairs_skips_container_ids(self):
        self.assertEqual(cr.pairs(["a", "b", {"id": "c"}, ["d"]]),
                         [("a", "b")])

    def test_qualifies_rule(self):
        self.assertTrue(cr.qualifies(3, NOW - DAY, 3, 30, now=NOW))
        self.assertFalse(cr.qualifies(2, NOW - DAY, 3, 30, now=NOW))
        self.assertFalse(cr.qualifies(5, NOW - 40 * DAY, 3, 30, now=NOW))
        self.assertTrue(cr.qualifies(5, NOW - 40 * DAY, 3, 0, now=NOW))
        self.assertFalse(cr.qualifies("x", None, 3, 30, now=NOW))


class RecordTest(CoRecallStorageTest):
    def test_record_inserts_pairs(self):
        out = cr.record_recall(["m1", "m2", "m3"], ts=NOW, db_path=self.db)
        self.assertEqual(out["pairs"], 3)
        self.assertEqual(out["ids"], 3)
        rows = cr.candidates(threshold=1, window_days=0, now=NOW,
                             db_path=self.db)
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(row["count"], 1)
            self.assertEqual(row["first_ts"], NOW)
            self.assertEqual(row["last_ts"], NOW)
            self.assertEqual(row["marked"], False)

    def test_repeat_updates_count_and_last_ts(self):
        cr.record_recall(["a", "b"], ts=NOW - 10 * DAY, db_path=self.db)
        cr.record_recall(["a", "b"], ts=NOW - DAY, db_path=self.db)
        row = cr.candidates(threshold=1, window_days=0, now=NOW,
                            db_path=self.db)[0]
        self.assertEqual(row["count"], 2)
        self.assertEqual(row["first_ts"], NOW - 10 * DAY)
        self.assertEqual(row["last_ts"], NOW - DAY)

    def test_unordered_pairs_merge(self):
        cr.record_recall(["a", "b"], ts=NOW, db_path=self.db)
        cr.record_recall(["b", "a"], ts=NOW, db_path=self.db)
        rows = cr.candidates(threshold=1, window_days=0, now=NOW,
                             db_path=self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["count"], 2)
        self.assertEqual(rows[0]["pair"], ("a", "b"))

    def test_duplicate_id_in_one_batch_counts_once(self):
        out = cr.record_recall(["a", "a", "b", "a"], ts=NOW, db_path=self.db)
        self.assertEqual(out["pairs"], 1)
        self.assertEqual(out["ids"], 2)
        rows = cr.candidates(threshold=1, window_days=0, now=NOW,
                             db_path=self.db)
        self.assertEqual(rows[0]["count"], 1)

    def test_empty_batch_is_noop(self):
        out = cr.record_recall([], ts=NOW, db_path=self.db)
        self.assertEqual(out["pairs"], 0)
        self.assertFalse(self.db.exists())
        self.assertEqual(cr.stats(db_path=self.db)["pairs"], 0)

    def test_invalid_ids_are_skipped(self):
        out = cr.record_recall(["a", "b", "", None, {"x": 1}, ["c"]],
                               ts=NOW, db_path=self.db)
        self.assertEqual(out["pairs"], 1)
        self.assertEqual(out["ids"], 2)


class ThresholdAndWindowTest(CoRecallStorageTest):
    def test_threshold_boundary(self):
        for tick in range(2):
            cr.record_recall(["a", "b"], ts=NOW - tick * DAY, db_path=self.db)
        self.assertEqual(cr.candidates(threshold=3, window_days=30, now=NOW,
                                       db_path=self.db), [])
        cr.record_recall(["a", "b"], ts=NOW, db_path=self.db)
        rows = cr.candidates(threshold=3, window_days=30, now=NOW,
                             db_path=self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["count"], 3)

    def test_window_excludes_old_pairs(self):
        for stamp in (40, 39, 38):
            cr.record_recall(["old", "pair"], ts=NOW - stamp * DAY,
                             db_path=self.db)
        for stamp in (2, 1, 0):
            cr.record_recall(["new", "pair"], ts=NOW - stamp * DAY,
                             db_path=self.db)
        recent = cr.candidates(threshold=3, window_days=30, now=NOW,
                               db_path=self.db)
        self.assertEqual([row["pair"] for row in recent], [("new", "pair")])
        every = cr.candidates(threshold=3, window_days=0, now=NOW,
                              db_path=self.db)
        self.assertEqual(len(every), 2)

    def test_candidates_sorted_by_count_then_recency(self):
        for _ in range(2):
            cr.record_recall(["a", "b"], ts=NOW - DAY, db_path=self.db)
        for _ in range(4):
            cr.record_recall(["c", "d"], ts=NOW, db_path=self.db)
        rows = cr.candidates(threshold=2, window_days=30, now=NOW,
                             db_path=self.db)
        self.assertEqual(rows[0]["pair"], ("c", "d"))
        self.assertEqual(rows[1]["pair"], ("a", "b"))
        self.assertGreaterEqual(rows[0]["count"], rows[1]["count"])

    def test_30_day_sample(self):
        for stamp in (20, 10, 1):
            cr.record_recall(["m1", "m2", "m3"], ts=NOW - stamp * DAY,
                             db_path=self.db)
        for stamp in (40, 39, 38):
            cr.record_recall(["m4", "m5"], ts=NOW - stamp * DAY,
                             db_path=self.db)
        rows = cr.candidates(threshold=3, window_days=30, now=NOW,
                             db_path=self.db)
        self.assertEqual([row["pair"] for row in rows],
                         [("m1", "m2"), ("m1", "m3"), ("m2", "m3")])
        for row in rows:
            self.assertEqual(row["count"], 3)
            self.assertEqual(row["age_days"], 1.0)


class MarkTest(CoRecallStorageTest):
    def _seed(self):
        for stamp in (3, 2, 1):
            cr.record_recall(["a", "b"], ts=NOW - stamp * DAY, db_path=self.db)
        for _ in range(2):
            cr.record_recall(["c", "d"], ts=NOW, db_path=self.db)

    def test_mark_only_over_threshold(self):
        self._seed()
        out = cr.mark_candidates(threshold=3, window_days=30, now=NOW,
                                 db_path=self.db)
        self.assertEqual(out["marked"], 1)
        marked = cr.read_marked(db_path=self.db)
        self.assertEqual([row["pair"] for row in marked], [("a", "b")])
        self.assertEqual(marked[0]["count"], 3)

    def test_mark_is_additive_not_destructive(self):
        self._seed()
        cr.mark_candidates(threshold=3, window_days=30, now=NOW,
                           db_path=self.db)
        rows = cr.candidates(threshold=1, window_days=0, now=NOW,
                             db_path=self.db)
        self.assertEqual(len(rows), 2)
        self.assertTrue(any(row["pair"] == ("a", "b") and row["marked"]
                            for row in rows))
        self.assertEqual(cr.stats(db_path=self.db)["pairs"], 2)

    def test_mark_is_idempotent(self):
        self._seed()
        cr.mark_candidates(threshold=3, window_days=30, now=NOW,
                           db_path=self.db)
        out = cr.mark_candidates(threshold=3, window_days=30, now=NOW + DAY,
                                 db_path=self.db)
        self.assertEqual(out["marked"], 1)
        marked = cr.read_marked(db_path=self.db)
        self.assertEqual(len(marked), 1)
        self.assertEqual(marked[0]["marked_ts"], NOW + DAY)

    def test_mark_then_candidates_show_flag(self):
        self._seed()
        cr.mark_candidates(threshold=3, window_days=30, now=NOW,
                           db_path=self.db)
        rows = cr.candidates(threshold=3, window_days=30, now=NOW,
                             db_path=self.db)
        self.assertTrue(rows[0]["marked"])

    def test_read_marked_limit(self):
        self._seed()
        for stamp in (2, 1, 0):
            cr.record_recall(["e", "f"], ts=NOW - stamp * DAY,
                             db_path=self.db)
        cr.mark_candidates(threshold=3, window_days=30, now=NOW,
                           db_path=self.db)
        self.assertEqual(len(cr.read_marked(db_path=self.db)), 2)
        self.assertEqual(len(cr.read_marked(db_path=self.db, limit=1)), 1)


class ReadOnlyTest(CoRecallStorageTest):
    def test_stats(self):
        cr.record_recall(["a", "b", "c"], ts=NOW, db_path=self.db)
        cr.record_recall(["a", "b"], ts=NOW, db_path=self.db)
        cr.mark_candidates(threshold=2, window_days=30, now=NOW,
                           db_path=self.db)
        out = cr.stats(db_path=self.db)
        self.assertEqual(out["pairs"], 3)
        self.assertEqual(out["recalls"], 4)
        self.assertEqual(out["marked"], 1)

    def test_readout_shape(self):
        cr.record_recall(["a", "b", "c", "d"], ts=NOW, db_path=self.db)
        out = cr.readout(threshold=1, window_days=30, now=NOW,
                         db_path=self.db, limit=2)
        self.assertEqual(out["threshold"], 1)
        self.assertIn("stats", out)
        self.assertEqual(len(out["candidates"]), 2)
        self.assertEqual(out["stats"]["pairs"], 6)

    def test_default_path_is_memory_sqlite3(self):
        path = cr.default_db_path()
        self.assertEqual(path.name, "memory.sqlite3")
        self.assertEqual(path.parent.name, "memory")

    def test_entries_table_is_untouched(self):
        self.db.parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(str(self.db))
        raw.execute("CREATE TABLE entries(id TEXT PRIMARY KEY, text TEXT)")
        raw.execute("INSERT INTO entries VALUES('m1', 'hello')")
        raw.commit()
        raw.close()
        cr.record_recall(["m1", "m2"], ts=NOW, db_path=self.db)
        cr.record_recall(["m1", "m2"], ts=NOW, db_path=self.db)
        cr.record_recall(["m1", "m2"], ts=NOW, db_path=self.db)
        cr.mark_candidates(threshold=3, window_days=30, now=NOW,
                           db_path=self.db)
        raw = sqlite3.connect(str(self.db))
        rows = raw.execute("SELECT id, text FROM entries").fetchall()
        tables = {row[0] for row in raw.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        raw.close()
        self.assertEqual(rows, [("m1", "hello")])
        self.assertIn("entries", tables)
        self.assertIn("co_recall", tables)
        self.assertIn("co_recall_marks", tables)


class SchemaAndConnectionTest(CoRecallStorageTest):
    def test_schema_columns(self):
        conn = cr.connect(self.db)
        try:
            names = [row[1] for row in conn.execute(
                "PRAGMA table_info(co_recall)")]
            self.assertEqual(names, ["pair_a", "pair_b", "count",
                                     "first_ts", "last_ts"])
            mark_names = [row[1] for row in conn.execute(
                "PRAGMA table_info(co_recall_marks)")]
            for column in ("pair_a", "pair_b", "marked_ts", "threshold",
                           "window_days"):
                self.assertIn(column, mark_names)
        finally:
            conn.close()

    def test_ensure_schema_is_idempotent(self):
        conn = cr.connect(self.db)
        try:
            cr.ensure_schema(conn)
            cr.ensure_schema(conn)
        finally:
            conn.close()
        cr.record_recall(["a", "b"], ts=NOW, db_path=self.db)
        self.assertEqual(cr.stats(db_path=self.db)["pairs"], 1)

    def test_injected_connection_stays_open(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            cr.record_recall(["a", "b"], ts=NOW, conn=conn)
            cr.record_recall(["a", "b"], ts=NOW, conn=conn)
            cr.record_recall(["a", "b"], ts=NOW, conn=conn)
            rows = cr.candidates(threshold=3, window_days=30, now=NOW,
                                 conn=conn)
            self.assertEqual(rows[0]["count"], 3)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM co_recall").fetchone()[0], 1)
        finally:
            conn.close()

    def test_parent_dir_is_created(self):
        self.assertFalse(self.db.exists())
        cr.record_recall(["a", "b"], ts=NOW, db_path=self.db)
        self.assertTrue(self.db.exists())


class RobustnessTest(CoRecallStorageTest):
    def test_bad_threshold_and_window(self):
        for stamp in range(3):
            cr.record_recall(["a", "b"], ts=NOW - stamp * DAY,
                             db_path=self.db)
        for threshold in (None, "x", 0, -3):
            rows = cr.candidates(threshold=threshold, window_days=30,
                                 now=NOW, db_path=self.db)
            self.assertIsInstance(rows, list)
        for days in (None, "x", -5):
            rows = cr.candidates(threshold=1, window_days=days, now=NOW,
                                 db_path=self.db)
            self.assertIsInstance(rows, list)

    def test_record_tolerates_odd_args(self):
        out = cr.record_recall(None, ts="x", db_path=self.db)
        self.assertEqual(out["pairs"], 0)
        self.assertIsInstance(out["ts"], float)

    def test_mark_empty_db(self):
        out = cr.mark_candidates(db_path=self.db)
        self.assertEqual(out["marked"], 0)
        self.assertEqual(out["pairs"], [])


if __name__ == "__main__":
    unittest.main()
