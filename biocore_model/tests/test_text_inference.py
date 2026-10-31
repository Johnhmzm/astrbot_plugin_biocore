# -*- coding: utf-8 -*-
"""L2 text-only inference tests: lexicon, punctuation, threshold, tag priority."""
import unittest

import interpretation as it


class InferShapeTest(unittest.TestCase):
    def test_negative_reply_is_negative_with_high_confidence(self):
        out = it.infer_from_text("我今天特别难受，别烦我")
        self.assertIn(out["emotion"], ("sadness", "anger", "fear"))
        self.assertGreaterEqual(out["confidence"], 0.4)
        visible, update = it.parse_response("我今天特别难受，别烦我")
        self.assertEqual(update["source"], "inferred")
        self.assertLess(update["valence_delta"], 0.0)
        self.assertGreaterEqual(update["confidence"], 0.4)

    def test_positive_reply_is_joy(self):
        out = it.infer_from_text("今天特别开心！")
        self.assertEqual(out["emotion"], "joy")
        self.assertGreaterEqual(out["confidence"], 0.4)
        _visible, update = it.parse_response("今天特别开心！")
        self.assertEqual(update["emotion"], "joy")
        self.assertGreater(update["valence_delta"], 0.0)

    def test_neutral_reply_is_dropped(self):
        out = it.infer_from_text("在吗")
        self.assertLess(out["confidence"], 0.4)
        self.assertIsNone(it.parse_response("在吗")[1])

    def test_sarcasm_stays_low_confidence(self):
        out = it.infer_from_text("你可真行啊")
        self.assertLess(out["confidence"], 0.4)
        self.assertIsNone(it.parse_response("你可真行啊")[1])

    def test_empty_input_does_not_crash(self):
        out = it.infer_from_text("")
        self.assertEqual(out["emotion"], "neutral")
        self.assertLess(out["confidence"], 0.3)
        self.assertEqual(it.parse_response("")[1], None)

    def test_ranges_are_bounded(self):
        for text in ("开心", "难受", "压力大", "在吗", "你可真行啊", ""):
            out = it.infer_from_text(text)
            self.assertGreaterEqual(out["intensity"], 0.0)
            self.assertLessEqual(out["intensity"], 1.0)
            self.assertGreaterEqual(out["confidence"], 0.0)
            self.assertLessEqual(out["confidence"], 1.0)


class RulesTest(unittest.TestCase):
    def test_negated_positive_becomes_sadness(self):
        out = it.infer_from_text("今天不开心")
        self.assertEqual(out["emotion"], "sadness")
        _visible, update = it.parse_response("今天不开心")
        self.assertLess(update["valence_delta"], 0.0)

    def test_adverb_bie_is_not_negation(self):
        out = it.infer_from_text("今天特别开心")
        self.assertEqual(out["emotion"], "joy")

    def test_reassurance_is_not_fear(self):
        out = it.infer_from_text("别担心，我陪你去医院，周五我请假。")
        self.assertLess(out["confidence"], 0.4)
        self.assertIsNone(it.parse_response("别担心，我陪你去医院，周五我请假。")[1])

    def test_exclamation_raises_confidence_intensity(self):
        plain = it.infer_from_text("太好了")
        loud = it.infer_from_text("太好了！！")
        self.assertGreaterEqual(loud["confidence"], plain["confidence"])
        self.assertGreaterEqual(loud["intensity"], plain["intensity"])

    def test_question_without_signal_stays_low(self):
        self.assertLess(it.infer_from_text("真的吗？")["confidence"], 0.4)

    def test_ellipsis_does_not_raise_confidence(self):
        out = it.infer_from_text("唉……")
        self.assertLessEqual(out["confidence"], 0.6)


class ParseIntegrationTest(unittest.TestCase):
    def test_tag_has_priority_over_inference(self):
        visible, update = it.parse_response(
            '<bc>{"e":"joy","i":0.4}</bc> 我今天特别难受，别烦我')
        self.assertNotIn("<bc>", visible)
        self.assertEqual(update["emotion"], "joy")
        self.assertNotEqual(update.get("source"), "inferred")

    def test_invalid_tag_does_not_fall_back_to_inference(self):
        _visible, update = it.parse_response("嗯。<bc>not json</bc>")
        self.assertIsNone(update)

    def test_inferred_update_is_feedback_compatible(self):
        _visible, update = it.parse_response("最近压力好大，晚上总睡不着。")
        for key in ("emotion", "intensity", "valence_delta", "arousal_delta",
                    "dominance_delta", "social_delta", "trust_delta"):
            self.assertIn(key, update)
        self.assertEqual(update["source"], "inferred")
        self.assertLess(update["valence_delta"], 0.0)


if __name__ == "__main__":
    unittest.main()
