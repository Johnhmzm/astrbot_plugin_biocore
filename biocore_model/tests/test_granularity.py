# -*- coding: utf-8 -*-
import unittest

from biocore_model import granularity as g


class GranularityMappingTest(unittest.TestCase):
    def test_aggrieved_mapping(self):
        out = g.refine({"sadness": 0.50, "anger": 0.20, "joy": 0.05})
        self.assertEqual(out["primary"], "sadness")
        self.assertEqual(out["labels"], ["委屈"])
        self.assertFalse(out["fallback"])

    def test_disappointed_mapping(self):
        out = g.refine({"sadness": 0.50, "trust": 0.20, "anger": 0.05})
        self.assertEqual(out["labels"], ["失望"])

    def test_ignored_mapping(self):
        out = g.refine({"loneliness": 0.60, "sadness": 0.15})
        self.assertEqual(out["primary"], "loneliness")
        self.assertEqual(out["labels"], ["被忽视"])

    def test_offended_mapping(self):
        out = g.refine({"anger": 0.55, "trust": 0.10},
                       context={"offense": 0.50})
        self.assertEqual(out["labels"], ["被冒犯"])

    def test_uneasy_mapping(self):
        out = g.refine({"fear": 0.55, "loneliness": 0.15})
        self.assertEqual(out["labels"], ["不安"])

    def test_worn_out_mapping(self):
        out = g.refine({"sadness": 0.50}, context={"fatigue": 0.60})
        self.assertEqual(out["labels"], ["疲惫"])

    def test_offended_needs_appraisal_cue(self):
        # anger alone is a prototype, not an appraisal of being offended
        out = g.refine({"anger": 0.90})
        self.assertEqual(out["labels"], [])
        self.assertTrue(out["fallback"])
        self.assertEqual(out["display"], "生气")

    def test_weak_anger_does_not_invent_aggrieved(self):
        out = g.refine({"sadness": 0.90, "anger": 0.05})
        self.assertEqual(out["labels"], [])
        self.assertEqual(out["display"], "难过")


class GranularityFallbackAndSwitchTest(unittest.TestCase):
    def test_fallback_to_six_prototypes(self):
        out = g.refine({"joy": 0.90, "trust": 0.10})
        self.assertEqual(out["primary"], "joy")
        self.assertTrue(out["fallback"])
        self.assertEqual(out["display"], "开心")
        self.assertEqual(out["secondary"], [])

    def test_disabled_bool_keeps_prototype(self):
        out = g.refine({"sadness": 0.50, "anger": 0.20}, config=False)
        self.assertFalse(out["enabled"])
        self.assertEqual(out["labels"], [])
        self.assertEqual(out["display"], "难过")

    def test_disabled_config_dict(self):
        out = g.refine({"loneliness": 0.60, "sadness": 0.15},
                       config={"enabled": False})
        self.assertFalse(out["enabled"])
        self.assertTrue(out["fallback"])
        self.assertEqual(out["display"], "孤独")

    def test_empty_scores(self):
        out = g.refine({})
        self.assertEqual(out["primary"], "")
        self.assertEqual(out["display"], "")
        self.assertTrue(out["fallback"])

    def test_unknown_keys_ignored(self):
        out = g.refine({"sadness": 0.60, "bogus": 0.99})
        self.assertEqual(out["primary"], "sadness")
        self.assertEqual(out["labels"], [])

    def test_primary_tie_is_deterministic(self):
        self.assertEqual(g.primary({"joy": 0.50, "trust": 0.50}), "joy")
        self.assertEqual(g.primary({"trust": 0.50, "joy": 0.50}), "joy")

    def test_custom_rules_replace_table(self):
        rules = ({"key": "hollow", "label": "空落", "primary": "loneliness",
                  "weights": {"loneliness": 1.0}, "threshold": 0.30},)
        out = g.refine({"loneliness": 0.50}, rules=rules)
        self.assertEqual(out["labels"], ["空落"])
        default = g.refine({"loneliness": 0.50, "sadness": 0.20})
        self.assertEqual(default["labels"], ["被忽视"])

    def test_max_labels_limit(self):
        out = g.refine({"sadness": 0.60, "anger": 0.20},
                       context={"fatigue": 0.60},
                       config={"max_labels": 1})
        self.assertEqual(out["labels"], ["委屈"])

    def test_deterministic_same_input(self):
        scores = {"sadness": 0.55, "anger": 0.25}
        first = g.refine(scores)
        second = g.refine(dict(scores))
        self.assertEqual(first, second)


class GranularityViewAndStateTest(unittest.TestCase):
    def test_view_line(self):
        panel = g.view({"sadness": 0.50, "anger": 0.20})
        self.assertEqual(panel["display"], "委屈")
        self.assertEqual(panel["line"], "委屈（难过）")
        self.assertEqual(panel["secondary"][0]["key"], "aggrieved")

    def test_view_fallback_line(self):
        panel = g.view({"joy": 0.90})
        self.assertEqual(panel["line"], "开心")
        self.assertTrue(panel["fallback"])

    def test_from_state_reaches_six_prototypes(self):
        out = g.from_state({"v": -0.70, "a": 0.30, "d": 0.20,
                            "social": 0.30, "stress": 0.60})
        self.assertEqual(out["primary"], "sadness")
        self.assertEqual(out["primary_zh"], "难过")

    def test_from_state_with_fatigue_cue(self):
        out = g.from_state({"v": -0.70, "a": 0.30, "d": 0.20,
                            "social": 0.30, "stress": 0.60},
                           context={"fatigue": 0.80})
        self.assertEqual(out["labels"], ["疲惫"])
        self.assertFalse(out["fallback"])


if __name__ == "__main__":
    unittest.main()
