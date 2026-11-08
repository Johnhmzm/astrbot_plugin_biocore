# -*- coding: utf-8 -*-
"""Compaction: capacity triggers it, the model decides, nothing is truncated."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.event import compaction as comp  # noqa: E402


def events():
    return [{
        "event_id": "EV001", "overview": "门口灯箱的事",
        "entries": [
            {"id": "s1", "text": "灯箱昨天晚上不亮了。"},
            {"id": "s2", "text": "师傅说明天上午过来看。"},
            {"id": "s3", "text": "我们约在九点半。"},
        ],
    }]


def decision(keep, drop, note="灯箱约好次日上午九点半维修。"):
    return json.dumps([{"event_id": "EV001", "keep_sentence_ids": keep,
                        "drop_sentence_ids": drop, "note": note}], ensure_ascii=False)


class CapacityTriggerTest(unittest.TestCase):
    def test_under_capacity_does_not_trigger(self):
        rows = events()
        result = comp.compact(rows, budget_chars=1000, ask=lambda prompt: decision(["s1"], ["s2"]))
        self.assertFalse(result["triggered"])
        self.assertEqual(result["applied"], [])
        self.assertFalse(any(r.get("archived") for r in rows[0]["entries"]))

    def test_over_capacity_triggers_and_the_model_decides(self):
        rows = events()
        seen = {}

        def ask(prompt):
            seen["prompt"] = prompt
            return decision(["s1", "s3"], ["s2"])

        result = comp.compact(rows, budget_chars=10, ask=ask)
        self.assertTrue(result["triggered"])
        archived = [r["id"] for r in rows[0]["entries"] if r.get("archived")]
        self.assertEqual(archived, ["s2"])              # only what the model dropped
        self.assertEqual(rows[0]["note"], "灯箱约好次日上午九点半维修。")
        self.assertIn("s1", seen["prompt"])            # the prompt carries the sentences
        self.assertIn("注入预算", seen["prompt"])


class InvalidAnswerTest(unittest.TestCase):
    def test_a_non_array_answer_raises(self):
        with self.assertRaises(comp.CompactionError):
            comp.parse_decisions("我觉得都留着比较好")

    def test_a_missing_note_raises(self):
        bad = json.dumps([{"event_id": "EV001", "keep_sentence_ids": ["s1"],
                           "drop_sentence_ids": ["s2"], "note": ""}])
        with self.assertRaises(comp.CompactionError):
            comp.parse_decisions(bad)

    def test_no_model_raises_instead_of_truncating(self):
        with self.assertRaises(comp.CompactionError):
            comp.compact(events(), budget_chars=10, ask=None)

    def test_a_row_dropped_twice_is_still_archived_once(self):
        rows = events()
        comp.compact(rows, budget_chars=10,
                     ask=lambda prompt: decision(["s1"], ["s2", "s2"]))
        self.assertEqual([r["id"] for r in rows[0]["entries"] if r.get("archived")],
                         ["s2"])


if __name__ == "__main__":
    unittest.main()
