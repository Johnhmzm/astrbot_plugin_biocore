# -*- coding: utf-8 -*-
"""item-3: LEX + bio_state text emotion word lists are gone; numeric path only."""
import inspect
import unittest
from pathlib import Path

from biocore_model import bio_const, bio_emotion, bio_state
from biocore_model.bio_state import StateMixin

PKG = Path(__file__).resolve().parents[1]


class Dummy:
    def __init__(self):
        self.conflict_ema = 0.0
        self.rumination_ema = 0.0
        self.rumination_suppress = False
        self.rumination_effect_enabled = False
        self._neg_repeat = 0
        self._last_neg_topic = ""


class TableRemovalTest(unittest.TestCase):
    def test_bio_const_has_no_lex(self):
        self.assertFalse(hasattr(bio_const, "LEX"))

    def test_bio_emotion_source_has_no_lex(self):
        source = (PKG / "bio_emotion.py").read_text(encoding="utf-8")
        self.assertNotIn("LEX", source)

    def test_bio_emotion_has_no_command_word_lists(self):
        source = (PKG / "bio_emotion.py").read_text(encoding="utf-8")
        for word in ("必须", "服从", "不许", "麻烦"):
            self.assertNotIn(word, source, word)

    def test_bio_state_has_no_text_emotion_words(self):
        source = (PKG / "bio_state.py").read_text(encoding="utf-8")
        for word in ("不对", "你错了", "矛盾", "难受", "委屈", "崩溃"):
            self.assertNotIn(word, source, word)


class NumericConflictTest(unittest.TestCase):
    def test_goal_blocked_raises_conflict(self):
        dummy = Dummy()
        out = StateMixin.update_conflict_ema(dummy, "随便什么字",
                                             dims={"goal": -1.0})
        self.assertGreater(out["delta"], 0.0)
        self.assertGreater(out["conflict_ema"], 0.0)

    def test_blame_raises_conflict(self):
        dummy = Dummy()
        out = StateMixin.update_conflict_ema(dummy, "", dims={"blame": 1.0})
        self.assertGreater(out["delta"], 0.3)

    def test_text_words_are_ignored(self):
        dummy = Dummy()
        out = StateMixin.update_conflict_ema(
            dummy, "不对 你错了 矛盾 但是 说错了 纠正")
        self.assertEqual(out["delta"], 0.0)

    def test_correction_flag_still_counted(self):
        dummy = Dummy()
        plain = StateMixin.update_conflict_ema(dummy, "", dims={})
        dummy2 = Dummy()
        flagged = StateMixin.update_conflict_ema(dummy2, "", correction=True)
        self.assertGreater(flagged["delta"], plain["delta"])


class NumericRuminationTest(unittest.TestCase):
    def test_negative_label_increases(self):
        dummy = Dummy()
        out = StateMixin.update_rumination_ema(dummy, "", emotion="sadness",
                                              intensity=0.8)
        self.assertGreater(out["rumination_ema"], 0.0)

    def test_text_words_without_signal_do_not_increase(self):
        dummy = Dummy()
        out = StateMixin.update_rumination_ema(dummy, "难受 难过 委屈 崩溃",
                                              emotion="neutral")
        self.assertEqual(out["rumination_ema"], 0.0)
        self.assertFalse(out["repeat"])

    def test_dims_hit_marks_negative(self):
        dummy = Dummy()
        out = StateMixin.update_rumination_ema(dummy, "", emotion="neutral",
                                              dims={"hit": 0.8})
        self.assertGreater(out["rumination_ema"], 0.0)

    def test_repeat_same_label_counts(self):
        dummy = Dummy()
        StateMixin.update_rumination_ema(dummy, "", emotion="anger")
        second = StateMixin.update_rumination_ema(dummy, "", emotion="anger")
        self.assertTrue(second["repeat"])
        self.assertEqual(second["repeat_count"], 2)

    def test_neutral_decays(self):
        dummy = Dummy()
        dummy.rumination_ema = 0.8
        out = StateMixin.update_rumination_ema(dummy, "", emotion="neutral",
                                              novelty=0.9)
        self.assertLess(out["rumination_ema"], 0.8)


if __name__ == "__main__":
    unittest.main()
