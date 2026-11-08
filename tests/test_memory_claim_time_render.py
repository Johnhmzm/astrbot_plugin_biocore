# -*- coding: utf-8 -*-
"""Rendered claim lines carry a date, never an internal coordinate.

The table keeps turn ids for indexing; the reader (a language model) has never
seen the turn list, so "第15轮" is noise while "2026-08-18 记录" is evidence.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.event import claims  # noqa: E402


def table(values):
    return {"shift_date·日期": {"values": values, "status": "current",
                               "confidence": 0.9}}


ROWS = [
    {"value": "八月十八", "turn": 3, "status": "superseded", "confidence": 0.9},
    {"value": "八月十七", "turn": 9, "status": "superseded", "confidence": 0.9},
    {"value": "八月十六", "turn": 15, "status": "current", "confidence": 0.9},
]
DATES = {3: "2026-08-15", 9: "2026-08-17", 15: "2026-08-18"}


class NoTurnNumbersTest(unittest.TestCase):
    def test_the_rendered_line_has_no_turn_or_event_coordinates(self):
        line = claims.render_claims(table(ROWS), turn_dates=DATES)[0]
        self.assertNotIn("轮", line)
        self.assertNotIn("EV0", line)
        self.assertNotIn("turn", line)

    def test_each_value_carries_its_own_date_and_the_order_is_visible(self):
        line = claims.render_claims(table(ROWS), turn_dates=DATES)[0]
        self.assertIn("八月十六（2026-08-18 记录）", line)
        self.assertIn("八月十七（2026-08-17 记录）", line)
        # display order is "current first"; the *chronology* is what the dates
        # must carry, and the retired value has to be the older one
        current = line.split("【当前】", 1)[1].split("【已作废", 1)[0]
        retired = line.split("【已作废", 1)[1]
        self.assertIn("2026-08-18", current)
        self.assertIn("2026-08-17", retired)
        self.assertLess("2026-08-17", "2026-08-18")   # ISO strings sort by time

    def test_a_missing_date_degrades_to_no_parenthetical_not_to_a_turn(self):
        line = claims.render_claims(table(ROWS))[0]
        self.assertIn("八月十六", line)
        self.assertNotIn("轮", line)
        self.assertNotIn("（", line.split("：", 1)[1].split("，")[0] or "")

    def test_the_extraction_prompt_asks_for_dates_not_turn_ranges(self):
        prompt = claims.claims_prompt({"start": 3, "end": 9, "text": "对话"},
                                     known=[], day="2026-08-18", threads=[])
        self.assertIn("本段日期 2026-08-18", prompt)
        self.assertNotIn("轮", prompt)


if __name__ == "__main__":
    unittest.main()
