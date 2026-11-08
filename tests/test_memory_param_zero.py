# -*- coding: utf-8 -*-
"""Parameters where 0 is a legal value, not "unset".

min_chars=0 must keep every non-empty line; hourly_cap=0 must mean no limit.
Both used to fall back to the default silently (or reject everything), which is
the same class of bug as a config default swallowing the user's value.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_runtime import pipeline as pl  # noqa: E402


class MinCharsZeroTest(unittest.TestCase):
    def test_zero_keeps_a_line_the_default_would_drop(self):
        short = "短句"            # 2 chars: below MIN_CHARS (8)
        dropped = pl.capture_decision("s", "user", short, {"now": 100.0})
        self.assertEqual(dropped["reason"], "too-short")
        kept = pl.capture_decision("s", "user", short,
                                   {"now": 100.0, "min_chars": 0})
        self.assertTrue(kept["capture"], kept)
        self.assertEqual(kept["reason"], "ok")

    def test_zero_still_rejects_an_empty_line(self):
        out = pl.capture_decision("s", "user", "   ", {"now": 100.0, "min_chars": 0})
        self.assertFalse(out["capture"])
        self.assertEqual(out["reason"], "empty")


class HourlyCapZeroTest(unittest.TestCase):
    def _state(self, stamps):
        return {"now": 100.0, "hourly": stamps}

    def test_zero_means_unlimited(self):
        # 25 stamps inside the hour: the default cap (20) would stop here
        stamps = [100.0 - index for index in range(25)]
        state = self._state({"s": stamps})
        state["hourly_cap"] = 0
        out = pl.capture_decision("s", "user", "这条句子足够长，应该被接受。", state)
        self.assertTrue(out["capture"], out)
        self.assertEqual(out["reason"], "ok")

    def test_the_default_cap_still_stops_the_same_state(self):
        stamps = [100.0 - index for index in range(25)]
        out = pl.capture_decision("s", "user", "这条句子足够长，应该被拒绝。",
                                  self._state({"s": stamps}))
        self.assertFalse(out["capture"])
        self.assertEqual(out["reason"], "hourly-limit")


if __name__ == "__main__":
    unittest.main()
