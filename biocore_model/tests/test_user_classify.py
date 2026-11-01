# -*- coding: utf-8 -*-
"""User-message classification + empathy/insult wiring tests."""
import ast
import types
import unittest
from pathlib import Path

from biocore_model import feedback_user as fu
import interpretation

MAIN = Path(__file__).resolve().parents[2] / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")
NOW = 1_700_000_000.0


def _load_insult_helper():
    tree = ast.parse(SOURCE)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "BioCorePlugin")
    node = next(f for f in cls.body
                if isinstance(f, ast.FunctionDef) and f.name == "_autonomy_insult_blocked")
    ns = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<insult>", "exec"), ns)
    return ns[node.name]


INSULT_BLOCKED = _load_insult_helper()


class ClassifyTest(unittest.TestCase):
    def test_flag_is_off_by_default(self):
        self.assertIs(interpretation.USER_CLASSIFY_ENABLED, False)

    def test_no_word_table_remains(self):
        self.assertFalse(hasattr(interpretation, "_USER_WORDS"))

    def test_insult_text_is_neutral(self):
        out = interpretation.classify_user_msg("你真废物，闭嘴")
        self.assertEqual(out["kind"], "neutral")
        self.assertLess(out["confidence"], 0.4)

    def test_reject_text_is_neutral(self):
        self.assertEqual(
            interpretation.classify_user_msg("不用了，别说了")["kind"],
            "neutral")

    def test_sad_text_is_neutral(self):
        self.assertEqual(
            interpretation.classify_user_msg("我今天特别难受，想哭")["kind"],
            "neutral")

    def test_praise_text_is_neutral(self):
        self.assertEqual(
            interpretation.classify_user_msg("你好厉害，谢谢")["kind"],
            "neutral")

    def test_affectionate_text_is_neutral(self):
        self.assertEqual(
            interpretation.classify_user_msg("想你了，抱抱")["kind"], "neutral")

    def test_empty_is_neutral(self):
        self.assertEqual(interpretation.classify_user_msg("")["kind"],
                         "neutral")

    def test_bounds(self):
        out = interpretation.classify_user_msg("谢谢你，你真好，太厉害了")
        self.assertGreaterEqual(out["intensity"], 0.0)
        self.assertLessEqual(out["intensity"], 1.0)
        self.assertGreaterEqual(out["confidence"], 0.0)
        self.assertLessEqual(out["confidence"], 1.0)

    def test_all_kinds_share_neutral_shape(self):
        for text in ("我很难受，你真废物", "嗯", "晚安"):
            out = interpretation.classify_user_msg(text)
            self.assertEqual(out["kind"], "neutral", text)

class FeedbackEventTest(unittest.TestCase):
    def test_sad_empathy_raises_stress(self):
        out = fu.on_message({"stress": 0.1}, {"kind": "sad_empathy",
                                              "id": "m1", "ts": NOW}, NOW)
        self.assertGreater(out["deltas"]["stress"], 0.0)
        self.assertGreater(out["deltas"]["social_pain"], 0.0)

    def test_affection_raises_social_lowers_stress(self):
        out = fu.on_message({"social": 0.5, "stress": 0.2},
                            {"kind": "affection", "id": "m2", "ts": NOW}, NOW)
        self.assertGreater(out["deltas"]["social"], 0.0)
        self.assertLess(out["deltas"]["stress"], 0.0)

    def test_classifier_kinds_are_accepted(self):
        for kind in ("neutral", "sad", "affectionate", "insult", "reject", "praise"):
            out = fu.on_message({}, {"kind": kind, "id": kind, "ts": NOW}, NOW)
            self.assertEqual(out["rejected"], [], kind)


class InsultGateTest(unittest.TestCase):
    def test_blocked_within_30_minutes(self):
        plugin = types.SimpleNamespace(_last_insult_ts=NOW - 100)
        self.assertTrue(INSULT_BLOCKED(plugin, NOW))

    def test_not_blocked_after_30_minutes(self):
        plugin = types.SimpleNamespace(_last_insult_ts=NOW - 2000)
        self.assertFalse(INSULT_BLOCKED(plugin, NOW))

    def test_no_insult_not_blocked(self):
        self.assertFalse(INSULT_BLOCKED(types.SimpleNamespace(), NOW))


class WiringStaticTest(unittest.TestCase):
    def test_main_keeps_helpers_behind_default_off_switch(self):
        self.assertIn("classify_user_msg(text)", SOURCE)
        self.assertIn('getattr(self, "lexical_fallback_enabled", False)',
                      SOURCE)
        self.assertIn('self.config.get("lexical_fallback_enabled", False)',
                      SOURCE)
        self.assertIn('"sad_empathy"', SOURCE)
        self.assertIn('"affection"', SOURCE)
        self.assertIn("insult_cooldown", SOURCE)
        self.assertIn("[biocore] user kind=%s conf=%.2f deltas=%s", SOURCE)

if __name__ == "__main__":
    unittest.main()
