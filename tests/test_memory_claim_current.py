# -*- coding: utf-8 -*-
"""A claim line must say which value is CURRENT, not only which one is stale."""
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


class ClaimCurrentMarkTest(unittest.TestCase):
    def test_three_values_current_is_labelled_and_comes_first(self):
        rows = [
            {"value": "八月十八", "turn": 3, "status": "superseded", "confidence": 0.9},
            {"value": "八月十七", "turn": 9, "status": "superseded", "confidence": 0.9},
            {"value": "八月十六", "turn": 15, "status": "current", "confidence": 0.9},
        ]
        lines = claims.render_claims(table(rows))
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertIn("【当前】八月十六", line)
        self.assertIn("【已作废", line)
        # the current value must appear before any retired one
        self.assertLess(line.index("【当前】"), line.index("【已作废"))
        # only the newest retired value is kept: three candidates are noise
        self.assertEqual(line.count("【已作废"), 1)
        self.assertIn("八月十七", line)
        self.assertNotIn("八月十八", line)

    def test_two_values_show_both_with_current_first(self):
        rows = [
            {"value": "八月十八", "turn": 3, "status": "superseded", "confidence": 0.9},
            {"value": "八月十六", "turn": 15, "status": "current", "confidence": 0.9},
        ]
        line = claims.render_claims(table(rows))[0]
        self.assertIn("【当前】八月十六", line)
        self.assertIn("【已作废，仅供参考】八月十八", line)
        self.assertLess(line.index("【当前】"), line.index("【已作废"))

    def test_a_value_that_was_never_corrected_has_no_label(self):
        rows = [{"value": "八月十六", "turn": 15, "status": "current",
                 "confidence": 0.9}]
        line = claims.render_claims(table(rows))[0]
        self.assertIn("八月十六", line)
        self.assertNotIn("【已作废", line)
        self.assertIn("【当前】", line)


if __name__ == "__main__":
    unittest.main()
