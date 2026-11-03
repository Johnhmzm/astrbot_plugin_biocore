# -*- coding: utf-8 -*-
"""task-176 来源监控 + 心境一致回忆单测：来源、置信、误归属、心境偏向、关闭。

只依赖 biocore_model.source_monitoring 的纯函数；不导入 main.py。
"""
import unittest

from biocore_model import source_monitoring as sm

YOUNG_TOLD = {"source": "told", "age_days": 3, "similarity": 0.2,
              "valence": -0.6, "importance": 0.5, "rehearsals": 1}
OLD_SIMILAR = {"source": "told", "age_days": 500, "similarity": 0.9,
               "valence": -0.6, "importance": 0.5}
OLD_DISSIMILAR = {"source": "told", "age_days": 500, "similarity": 0.1,
                  "valence": -0.3, "importance": 0.5}
OWN_MEMORY = {"source": "experienced", "age_days": 20, "similarity": 0.8,
              "valence": 0.4, "importance": 0.8, "rehearsals": 3}
POS_META = {"source": "experienced", "age_days": 10, "valence": 0.7,
            "importance": 0.4}
NEG_META = {"source": "told", "age_days": 10, "valence": -0.7,
            "importance": 0.4}
NEG_MOOD = {"valence": -0.8, "arousal": 0.6}
POS_MOOD = {"valence": 0.8, "arousal": 0.6}


class ContractTest(unittest.TestCase):
    def test_result_keys(self):
        out = sm.monitor(YOUNG_TOLD, NEG_MOOD)
        for key in ("enabled", "source", "label", "claimed_source",
                    "confidence", "probabilities", "misattribution",
                    "recall_bias", "recall_weight", "congruent", "reason"):
            self.assertIn(key, out)

    def test_sources(self):
        self.assertEqual(sm.SOURCES, ("experienced", "told", "inferred"))
        self.assertEqual(set(sm.LABELS), set(sm.SOURCES))
        self.assertEqual(sm.LABELS["experienced"], "自己经历")
        self.assertEqual(sm.LABELS["told"], "你告诉她的")
        self.assertEqual(sm.LABELS["inferred"], "她推测的")

    def test_probabilities_normalised(self):
        for meta in (YOUNG_TOLD, OLD_SIMILAR, OWN_MEMORY, None):
            out = sm.monitor(meta, NEG_MOOD)
            self.assertAlmostEqual(sum(out["probabilities"].values()), 1.0,
                                   places=2)
            for value in out["probabilities"].values():
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)
            self.assertEqual(out["source"],
                             max(out["probabilities"],
                                 key=lambda name: out["probabilities"][name]))

    def test_confidence_bounded(self):
        for meta in (YOUNG_TOLD, OLD_SIMILAR, OLD_DISSIMILAR, OWN_MEMORY, None):
            out = sm.monitor(meta, NEG_MOOD)
            self.assertGreaterEqual(out["confidence"], 0.0)
            self.assertLessEqual(out["confidence"], 1.0)


class SourceTest(unittest.TestCase):
    def test_young_told_is_believed(self):
        out = sm.monitor(YOUNG_TOLD, NEG_MOOD)
        self.assertEqual(out["source"], "told")
        self.assertEqual(out["claimed_source"], "told")
        self.assertGreater(out["confidence"], 0.5)

    def test_age_lowers_source_confidence(self):
        self.assertGreater(sm.confidence(YOUNG_TOLD),
                           sm.confidence(OLD_SIMILAR))

    def test_old_similar_memory_is_misattributed(self):
        out = sm.monitor(OLD_SIMILAR, NEG_MOOD)
        self.assertEqual(out["source"], "experienced")
        self.assertGreater(out["misattribution"], 0.5)
        self.assertLess(out["confidence"], 0.5)

    def test_old_dissimilar_falls_to_inference(self):
        out = sm.monitor(OLD_DISSIMILAR, NEG_MOOD)
        self.assertNotEqual(out["source"], "told")
        self.assertIn(out["source"], ("inferred", "experienced"))

    def test_own_memory_stays_own(self):
        out = sm.monitor(OWN_MEMORY, NEG_MOOD)
        self.assertEqual(out["source"], "experienced")
        self.assertGreater(out["confidence"], 0.5)

    def test_rehearsal_lifts_confidence(self):
        weak = dict(YOUNG_TOLD, rehearsals=0)
        strong = dict(YOUNG_TOLD, rehearsals=4)
        self.assertGreater(sm.confidence(strong), sm.confidence(weak))

    def test_misattribution_rises_with_age_and_similarity(self):
        young = sm.misattribution(YOUNG_TOLD)[0]
        old = sm.misattribution(OLD_SIMILAR)[0]
        self.assertGreater(old, young)

    def test_aliases(self):
        self.assertEqual(sm.monitor({"source": "self"})["source"],
                         "experienced")
        self.assertEqual(sm.monitor({"source": "you"})["source"], "told")
        self.assertEqual(sm.monitor({"source": "guess"})["source"],
                         "inferred")

    def test_trace_decays(self):
        self.assertEqual(sm.trace_strength(0), 1.0)
        self.assertAlmostEqual(sm.trace_strength(sm.AGE_HALF_LIFE), 0.3679,
                               places=3)
        self.assertLess(sm.trace_strength(1000),
                        sm.trace_strength(sm.AGE_HALF_LIFE))


class MoodCongruenceTest(unittest.TestCase):
    def test_negative_mood_biases_negative(self):
        self.assertLess(sm.monitor(POS_META, NEG_MOOD)["recall_bias"], 0.0)
        self.assertLess(sm.monitor(NEG_META, NEG_MOOD)["recall_bias"], 0.0)

    def test_positive_mood_biases_positive(self):
        self.assertGreater(sm.monitor(POS_META, POS_MOOD)["recall_bias"], 0.0)
        self.assertGreater(sm.monitor(NEG_META, POS_MOOD)["recall_bias"], 0.0)

    def test_neutral_mood_has_no_bias(self):
        for meta in (POS_META, NEG_META):
            out = sm.monitor(meta, {"valence": 0.0, "arousal": 0.5})
            self.assertEqual(out["recall_bias"], 0.0)
            self.assertEqual(out["recall_weight"], 1.0)
            self.assertFalse(out["congruent"])

    def test_negative_mood_eases_negative_memory(self):
        out = sm.monitor(NEG_META, NEG_MOOD)
        self.assertGreater(out["recall_weight"], 1.0)
        self.assertTrue(out["congruent"])

    def test_negative_mood_hardens_positive_memory(self):
        out = sm.monitor(POS_META, NEG_MOOD)
        self.assertLess(out["recall_weight"], 1.0)
        self.assertFalse(out["congruent"])

    def test_positive_mood_eases_positive_memory(self):
        out = sm.monitor(POS_META, POS_MOOD)
        self.assertGreater(out["recall_weight"], 1.0)
        self.assertTrue(out["congruent"])

    def test_positive_mood_hardens_negative_memory(self):
        out = sm.monitor(NEG_META, POS_MOOD)
        self.assertLess(out["recall_weight"], 1.0)
        self.assertFalse(out["congruent"])

    def test_recall_weight_helper_matches(self):
        for meta in (POS_META, NEG_META):
            for mood in (NEG_MOOD, POS_MOOD, 0.0):
                self.assertEqual(
                    sm.recall_weight(mood, meta),
                    sm.monitor(meta, mood)["recall_weight"])

    def test_recall_weight_bounded(self):
        for meta in (POS_META, NEG_META):
            for mood in ({"valence": -1.0, "arousal": 1.0},
                         {"valence": 1.0, "arousal": 1.0},
                         None, "x"):
                weight = sm.recall_weight(mood, meta)
                self.assertGreaterEqual(weight, 0.4)
                self.assertLessEqual(weight, 1.6)


class SwitchTest(unittest.TestCase):
    def test_disabled_is_neutral(self):
        out = sm.monitor(YOUNG_TOLD, NEG_MOOD, flags={"enabled": False})
        self.assertFalse(out["enabled"])
        self.assertEqual(out["source"], "told")
        self.assertEqual(out["confidence"], 0.0)
        self.assertEqual(out["recall_bias"], 0.0)
        self.assertEqual(out["recall_weight"], 1.0)
        self.assertEqual(out["probabilities"], {})
        self.assertIn("关闭", out["reason"])

    def test_readout_bounded(self):
        out = sm.readout(sm.monitor(OLD_SIMILAR, NEG_MOOD))
        self.assertEqual(out["source"], "experienced")
        self.assertGreaterEqual(out["confidence"], 0.0)
        self.assertLessEqual(out["confidence"], 1.0)
        self.assertGreaterEqual(out["recall_weight"], 0.4)
        self.assertLessEqual(out["recall_weight"], 1.6)
        self.assertTrue(out["reason"])


class RobustnessTest(unittest.TestCase):
    def test_odd_inputs(self):
        for meta in (None, "x", 3, [], {"age_days": float("nan")},
                     {"source": "what", "age_days": "?"}):
            for mood in (None, "x", 3, [], {"valence": float("nan")}):
                out = sm.monitor(meta, mood)
                self.assertIn(out["source"], sm.SOURCES)
                self.assertGreaterEqual(out["confidence"], 0.0)
                self.assertLessEqual(out["confidence"], 1.0)
                self.assertTrue(out["reason"])

    def test_bare_valence_is_accepted(self):
        out = sm.monitor(POS_META, 0.8)
        self.assertGreater(out["recall_bias"], 0.0)
        self.assertGreater(out["recall_weight"], 1.0)


if __name__ == "__main__":
    unittest.main()
