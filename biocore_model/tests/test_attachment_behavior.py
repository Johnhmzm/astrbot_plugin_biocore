# -*- coding: utf-8 -*-
"""Attachment styles as behaviour parameters."""
import unittest

from biocore_model import attachment_behavior as ab


class StyleTest(unittest.TestCase):
    def test_three_styles_distinct(self):
        secure = ab.evaluate("secure")
        anxious = ab.evaluate("anxious")
        avoidant = ab.evaluate("avoidant")
        self.assertGreater(anxious["seeking"], secure["seeking"])
        self.assertGreater(anxious["seeking"], avoidant["seeking"])
        self.assertGreater(avoidant["withdrawal"], secure["withdrawal"])
        self.assertGreater(secure["initiative"], avoidant["initiative"])

    def test_unknown_style_falls_back_secure(self):
        out = ab.evaluate("weird")
        self.assertEqual(out["style"], "secure")

    def test_labels(self):
        self.assertEqual(ab.evaluate("anxious")["label"], "焦虑型")


class BoundsTest(unittest.TestCase):
    def test_all_params_bounded(self):
        for style in ab.STYLES:
            out = ab.evaluate(style, {"closeness": 1.0, "stress": 1.0})
            for key in ("initiative", "seeking", "withdrawal"):
                self.assertGreaterEqual(out[key], 0.0)
                self.assertLessEqual(out[key], 1.0)


class ModifierTest(unittest.TestCase):
    def test_stress_lowers_initiative_raises_withdrawal(self):
        calm = ab.evaluate("secure", {"stress": 0.0})
        tense = ab.evaluate("secure", {"stress": 1.0})
        self.assertGreater(calm["initiative"], tense["initiative"])
        self.assertLess(calm["withdrawal"], tense["withdrawal"])

    def test_closeness_lifts_initiative(self):
        far = ab.evaluate("secure", {"closeness": 0.1})
        near = ab.evaluate("secure", {"closeness": 0.9})
        self.assertGreater(near["initiative"], far["initiative"])


class IgnoredTest(unittest.TestCase):
    def test_anxious_seeks_more_when_ignored(self):
        normal = ab.evaluate("anxious")
        ignored = ab.evaluate("anxious", {"ignored": True})
        self.assertGreater(ignored["seeking"], normal["seeking"])

    def test_avoidant_withdraws_more_when_ignored(self):
        normal = ab.evaluate("avoidant")
        ignored = ab.evaluate("avoidant", {"ignored": True})
        self.assertGreater(ignored["withdrawal"], normal["withdrawal"])

    def test_on_ignored_text_per_style(self):
        self.assertIn("再发", ab.evaluate("anxious")["on_ignored"])
        self.assertIn("退回去", ab.evaluate("avoidant")["on_ignored"])


class MixedTest(unittest.TestCase):
    def test_blend_sits_between(self):
        blend = ab.evaluate({"secure": 0.5, "anxious": 0.5})
        self.assertTrue(0.4 <= blend["seeking"] <= 0.8)

    def test_empty_mix_defaults_secure(self):
        self.assertEqual(ab.evaluate({})["style"], "secure")


class FallbackTest(unittest.TestCase):
    def test_disabled(self):
        out = ab.evaluate("anxious", flags={"enabled": False})
        self.assertFalse(out["enabled"])
        self.assertEqual(out["style"], "secure")

    def test_malformed_context(self):
        out = ab.evaluate("secure", "nope")
        self.assertIn(out["style"], ab.STYLES)


class DirectiveTest(unittest.TestCase):
    def test_withdrawal_shortens(self):
        out = ab.directives(ab.evaluate("avoidant", {"stress": 0.9}))
        self.assertLessEqual(out["length_scale"], 1.0)

    def test_disabled_directive(self):
        out = ab.directives({"enabled": False})
        self.assertEqual(out["tone"], "")


if __name__ == "__main__":
    unittest.main()
