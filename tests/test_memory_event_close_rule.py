# -*- coding: utf-8 -*-
"""Events close on information, not on message count.

Order is part of the contract: a topic change closes immediately, then the turn
floor is a HARD gate (a single long turn must not close an event on its own),
then the character budget, then the turn ceiling.
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

    def test_three_long_paragraphs_close_early(self):
        # two paragraphs already hold enough information: the third turn starts
        # a new event (at the tuned default of 1200 this needs three paragraphs)
        long_text = "这是一段很长的描述，" * 30          # ~300 chars each
        buf = [row(long_text), row(long_text)]
        self.assertEqual(self._why(buf, row(long_text)), "")          # 900 < 2000
        self.assertEqual(self._why(buf, row(long_text), close_chars=750,
                                   min_turns=2), "chars")

    def test_one_huge_turn_is_held_by_the_turn_floor(self):
        # P01 messages are long: without the hard floor one turn closes an event
        buf = [row("长" * 2000)]
        self.assertEqual(self._why(buf, row("短"), min_turns=2), "")

    def test_two_turns_under_the_2000_budget_do_not_close(self):
        # 2 turns x 750 chars: below the tuned default, so the event keeps going
        buf = [row("描" * 700), row("述" * 800)]
        self.assertEqual(self._why(buf, row("下一句"), close_chars=2000), "")

    def test_six_turns_over_the_2000_budget_close(self):
        buf = [row("字" * 350) for _ in range(6)]        # 2100 chars
        self.assertEqual(self._why(buf, row("下一句"), close_chars=2000), "chars")

    def test_two_turns_over_the_budget_close(self):
        # an event may close once it already holds MIN_TURNS turns whose text
        # reaches the budget; closing happens as the NEXT turn arrives
        buf = [row("描" * 700), row("述" * 600)]
        self.assertEqual(self._why(buf, row("下一句"), min_turns=2,
                                   close_chars=1200), "chars")

    def test_the_turn_ceiling_still_fires(self):
        buf = [row("嗯") for _ in range(12)]
        self.assertEqual(self._why(buf, row("好"), close_chars=999999), "max_turns")

    def test_a_topic_change_wins_over_the_turn_floor(self):
        buf = [row("一" * 100)]
        self.assertEqual(self._why(buf, row("无关话题"), sim=0.1), "topic")

    def test_a_long_silence_wins_over_the_turn_floor(self):
        buf = [row("一" * 100)]
        self.assertEqual(self._why(buf, row("后来又提起了"), gap=P.EVENT_GAP_S + 1),
                         "gap")


if __name__ == "__main__":
    unittest.main()
