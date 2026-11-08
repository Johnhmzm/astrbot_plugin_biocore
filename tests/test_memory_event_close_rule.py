# -*- coding: utf-8 -*-
"""Events close on information, not on message count.

Eight "嗯"s are 20 characters; three long descriptions are 2000. A turn count
cannot tell those apart, so the character budget is the primary signal and the
turn bounds are only a floor and a ceiling.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_runtime import pipeline as P  # noqa: E402


def row(text, ts=0.0):
    return {"text": text, "ts": ts, "turn": 1}


class EventCloseRuleTest(unittest.TestCase):
    THR = 0.30

    def _why(self, buf, item, sim=1.0, gap=0.0, **kwargs):
        return P._event_should_close(buf, item, sim, gap, self.THR, **kwargs)

    def test_eight_short_lines_do_not_close(self):
        buf = [row("嗯") for _ in range(7)]
        self.assertEqual(self._why(buf, row("好")), "")   # 8 lines, < 100 chars

    def test_three_long_paragraphs_close_on_the_third_turn(self):
        long_text = "这是一段很长的描述，" * 30          # ~300 chars each
        buf = [row(long_text), row(long_text)]
        self.assertEqual(self._why(buf, row(long_text), close_chars=750), "chars")

    def test_a_single_line_never_closes(self):
        buf = [row("一" * 2000)]
        self.assertEqual(self._why(buf, row("短"), close_chars=750, min_turns=2), "max_turns"
                         if P.EVENT_MAX_TURNS and len(buf) >= P.EVENT_MAX_TURNS else "")

    def test_the_turn_ceiling_still_fires(self):
        buf = [row("嗯") for _ in range(12)]
        self.assertEqual(self._why(buf, row("好"), close_chars=999999), "max_turns")

    def test_a_topic_change_wins_over_the_budget(self):
        buf = [row("一" * 100)]
        self.assertEqual(self._why(buf, row("无关话题"), sim=0.1), "topic")


if __name__ == "__main__":
    unittest.main()
