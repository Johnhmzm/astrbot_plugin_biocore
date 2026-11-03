# -*- coding: utf-8 -*-
"""Prospective memory: registration, due queries, overdue, dedup."""
import unittest

from biocore_model import prospective as pm

NOW = 1790000000.0
DAY = 86400.0

class NormalizeTest(unittest.TestCase):
    def test_strips_punctuation_and_space(self):
        self.assertEqual(pm.normalize("  明天 问你，结果！ "), "明天问你结果")

    def test_none_is_empty(self):
        self.assertEqual(pm.normalize(None), "")

class IdTest(unittest.TestCase):
    def test_same_text_same_id(self):
        a = pm.make_id("her_promise", "问他体检结果", NOW)
        b = pm.make_id("her_promise", "问他体检结果！", NOW + 3600)
        self.assertEqual(a, b)

    def test_reschedule_keeps_id(self):
        a = pm.make_id("her_promise", "问他体检结果", NOW)
        b = pm.make_id("her_promise", "问他体检结果", NOW + 7 * DAY)
        self.assertEqual(a, b)

    def test_kind_changes_id(self):
        a = pm.make_id("her_promise", "体检", NOW)
        b = pm.make_id("his_event", "体检", NOW)
        self.assertNotEqual(a, b)

class EntryTest(unittest.TestCase):
    def test_fields(self):
        row = pm.entry("his_event", "周五体检", NOW + 2 * DAY, now=NOW)
        self.assertEqual(row["kind"], "his_event")
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["due_ts"], NOW + 2 * DAY)
        self.assertEqual(row["created_ts"], NOW)
        self.assertTrue(row["id"])

    def test_text_truncated(self):
        row = pm.entry("his_event", "x" * 200, NOW)
        self.assertEqual(len(row["text"]), 80)

class AddTest(unittest.TestCase):
    def test_add_new(self):
        row = pm.entry("his_event", "周五体检", NOW + DAY, now=NOW)
        store, changed = pm.add([], row)
        self.assertTrue(changed)
        self.assertEqual(len(store), 1)

    def test_duplicate_refreshes_due(self):
        row = pm.entry("his_event", "周五体检", NOW + DAY, now=NOW)
        store, _ = pm.add([], row)
        later = pm.entry("his_event", "周五体检", NOW + 2 * DAY, now=NOW)
        store, changed = pm.add(store, later)
        self.assertTrue(changed)
        self.assertEqual(len(store), 1)
        self.assertEqual(store[0]["due_ts"], NOW + 2 * DAY)

    def test_duplicate_done_stays_done(self):
        row = pm.entry("his_event", "周五体检", NOW + DAY, now=NOW)
        store, _ = pm.add([], row)
        store, _ = pm.resolve(store, row["id"], "done", now=NOW)
        again = pm.entry("his_event", "周五体检", NOW + DAY, now=NOW)
        store, changed = pm.add(store, again)
        self.assertFalse(changed)
        self.assertEqual(store[0]["status"], "done")

    def test_bad_record_ignored(self):
        store, changed = pm.add([], {"text": "没有 id"})
        self.assertFalse(changed)
        self.assertEqual(store, [])

class DueTest(unittest.TestCase):
    def _store(self):
        rows = [pm.entry("his_event", "早上的事", NOW - 3 * 3600, now=NOW),
                pm.entry("her_promise", "刚到期", NOW, now=NOW),
                pm.entry("his_event", "明天的事", NOW + DAY, now=NOW)]
        store = []
        for row in rows:
            store, _ = pm.add(store, row)
        return store

    def test_due_now_with_window(self):
        rows = pm.due_now(self._store(), NOW, window_s=4 * 3600)
        self.assertEqual([row["text"] for row in rows], ["早上的事", "刚到期"])

    def test_due_now_without_window(self):
        rows = pm.due_now(self._store(), NOW)
        self.assertEqual([row["text"] for row in rows], ["刚到期"])

    def test_due_soon(self):
        rows = pm.due_soon(self._store(), NOW, ahead_s=2 * DAY)
        self.assertEqual([row["text"] for row in rows], ["明天的事"])

class OverdueTest(unittest.TestCase):
    def test_marks_after_grace(self):
        row = pm.entry("his_event", "昨天的事", NOW - DAY, now=NOW - DAY)
        store, _ = pm.add([], row)
        store, changed = pm.mark_overdue(store, NOW)
        self.assertEqual(changed, 1)
        self.assertEqual(store[0]["status"], "overdue")

    def test_not_early(self):
        row = pm.entry("his_event", "刚到期", NOW, now=NOW)
        store, _ = pm.add([], row)
        store, changed = pm.mark_overdue(store, NOW + 60)
        self.assertEqual(changed, 0)

class ResolveTest(unittest.TestCase):
    def test_done(self):
        row = pm.entry("his_event", "周五体检", NOW + DAY, now=NOW)
        store, _ = pm.add([], row)
        store, changed = pm.resolve(store, row["id"], "done", now=NOW)
        self.assertTrue(changed)
        self.assertEqual(store[0]["status"], "done")

    def test_invalid_status_noop(self):
        row = pm.entry("his_event", "周五体检", NOW + DAY, now=NOW)
        store, _ = pm.add([], row)
        store, changed = pm.resolve(store, row["id"], "weird")
        self.assertFalse(changed)
        self.assertEqual(store[0]["status"], "pending")

class HintTest(unittest.TestCase):
    def test_pending_hint(self):
        row = pm.entry("his_event", "周五体检", NOW + DAY, now=NOW)
        self.assertEqual(pm.build_hint(row, NOW), "他提过的事到了：周五体检")

    def test_overdue_hint(self):
        row = pm.entry("her_promise", "问他结果", NOW - DAY, now=NOW - DAY)
        self.assertIn("还没问", pm.build_hint(row, NOW))

    def test_empty_text(self):
        self.assertEqual(pm.build_hint({"kind": "his_event", "text": ""}), "")

class StatsTest(unittest.TestCase):
    def test_counts(self):
        store = []
        for kind, text, due in (("his_event", "a", NOW), ("her_promise", "b", NOW),
                                ("his_event", "c", NOW)):
            store, _ = pm.add(store, pm.entry(kind, text, due, now=NOW))
        out = pm.stats(store)
        self.assertEqual(out["total"], 3)
        self.assertEqual(out["by_kind"]["his_event"], 2)
        self.assertEqual(out["by_kind"]["her_promise"], 1)

    def test_malformed_store(self):
        self.assertEqual(pm.stats([None, "x", 3])["total"], 0)

if __name__ == "__main__":
    unittest.main()
