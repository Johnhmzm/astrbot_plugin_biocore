# -*- coding: utf-8 -*-
"""item-5: lexical inference is disabled; the probe owns semantics."""
import unittest

import interpretation as it


class DisabledInferenceTest(unittest.TestCase):
    def test_flag_is_off_by_default(self):
        self.assertIs(it.TEXT_INFERENCE_ENABLED, False)
        self.assertIs(it.USER_CLASSIFY_ENABLED, False)

    def test_negative_text_is_neutral(self):
        out = it.infer_from_text("我今天特别难受，别烦我")
        self.assertEqual(out["emotion"], "neutral")
        self.assertEqual(out["confidence"], 0.0)

    def test_positive_text_is_neutral(self):
        self.assertEqual(it.infer_from_text("今天特别开心！")["emotion"],
                         "neutral")

    def test_no_lexical_tables_remain(self):
        for name in ("_INFER_WORDS", "_INFER_EMOJI", "_SARCASM_MARKERS",
                     "_USER_WORDS", "_NEGATION_PREFIX_WORDS", "_negated"):
            self.assertFalse(hasattr(it, name), name)

    def test_parse_response_does_not_infer(self):
        for text in ("我今天特别难受，别烦我", "今天特别开心！", "你可真行啊",
                     "最近压力好大，晚上总睡不着。"):
            visible, update = it.parse_response(text)
            self.assertIsNone(update, text)
            self.assertEqual(visible, text)

    def test_empty_input_is_safe(self):
        self.assertEqual(it.infer_from_text("")["emotion"], "neutral")
        self.assertIsNone(it.parse_response("")[1])

    def test_ranges_are_bounded(self):
        for text in ("开心", "难受", "压力大", "在吗", ""):
            out = it.infer_from_text(text)
            self.assertGreaterEqual(out["intensity"], 0.0)
            self.assertLessEqual(out["intensity"], 1.0)
            self.assertGreaterEqual(out["confidence"], 0.0)
            self.assertLessEqual(out["confidence"], 1.0)

    def test_classify_is_neutral_noop(self):
        out = it.classify_user_msg("你真废物，闭嘴")
        self.assertEqual(out["kind"], "neutral")
        self.assertLess(out["confidence"], 0.4)


class ParseContractTest(unittest.TestCase):
    def test_tag_path_still_works(self):
        visible, update = it.parse_response(
            '<bc>{"e":"joy","i":0.4}</bc> 我今天特别难受')
        self.assertNotIn("<bc>", visible)
        self.assertEqual(update["emotion"], "joy")
        self.assertNotEqual(update.get("source"), "inferred")

    def test_invalid_tag_does_not_fall_back(self):
        _visible, update = it.parse_response("嗯。<bc>not json</bc>")
        self.assertIsNone(update)

    def test_update_shape_unchanged_for_tag_path(self):
        _visible, update = it.parse_response('<bc>{"e":"anger","i":0.6}</bc>')
        self.assertIn("valence_delta", update)


if __name__ == "__main__":
    unittest.main()
