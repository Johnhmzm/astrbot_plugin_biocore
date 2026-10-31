# -*- coding: utf-8 -*-
"""Emotion geometry tests: prototypes, mixed distributions, tone mixing."""
import unittest

from biocore_model import emotion_geometry as eg
from biocore_model import expr_tone as et
from biocore_model import stages as st


def core_state(proto):
    state = {"v": proto.get("v", 0.0)}
    for name in ("a", "d", "social", "stress", "trust"):
        if name in proto:
            state[name] = (float(proto[name]) + 1.0) / 2.0
    return state


class PrototypeTest(unittest.TestCase):
    def test_each_prototype_wins(self):
        for label, proto in eg.PROTOTYPES.items():
            out = eg.classify(core_state(proto))
            self.assertEqual(out["label"], label, label)
            self.assertGreater(out["probs"][label], 0.5, label)

    def test_probs_sum_to_one(self):
        out = eg.classify(core_state(eg.PROTOTYPES["joy"]))
        self.assertAlmostEqual(sum(out["probs"].values()), 1.0, places=3)

    def test_mixed_state_has_low_confidence(self):
        a = core_state(eg.PROTOTYPES["sadness"])
        b = core_state(eg.PROTOTYPES["anger"])
        mixed = {key: (a.get(key, 0.5) + b.get(key, 0.5)) / 2.0 for key in a}
        out = eg.classify(mixed)
        single = eg.classify(a)
        self.assertLess(out["confidence"], single["confidence"])
        self.assertLess(out["probs"][out["label"]], 0.8)

    def test_missing_dimensions_do_not_crash_and_lower_confidence(self):
        full = eg.classify(core_state(eg.PROTOTYPES["joy"]))
        partial = eg.classify({"v": 0.7, "a": 0.7})
        self.assertIn(partial["label"], eg.LABELS)
        self.assertLess(partial["confidence"], full["confidence"])

    def test_temperature_changes_entropy(self):
        state = core_state(eg.PROTOTYPES["fear"])
        cold = eg.classify(state, temperature=0.08)
        hot = eg.classify(state, temperature=0.8)
        self.assertLess(eg.entropy(cold["probs"]), eg.entropy(hot["probs"]))
        self.assertGreaterEqual(cold["probs"][cold["label"]],
                                hot["probs"][hot["label"]])

    def test_confidence_and_prob_bounds(self):
        out = eg.classify({"v": 0.0, "a": 0.5, "d": 0.5})
        self.assertGreaterEqual(out["confidence"], 0.0)
        self.assertLessEqual(out["confidence"], 1.0)
        for prob in out["probs"].values():
            self.assertGreaterEqual(prob, 0.0)
            self.assertLessEqual(prob, 1.0)

    def test_single_prototype_has_low_entropy(self):
        out = eg.classify(core_state(eg.PROTOTYPES["joy"]))
        self.assertLess(eg.entropy(out["probs"]), 2.0)

    def test_top2_structure(self):
        out = eg.classify(core_state(eg.PROTOTYPES["trust"]))
        self.assertEqual(len(out["top2"]), 2)
        self.assertIn("label", out["top2"][0])
        self.assertEqual(eg.top_probs(out, 3)[0]["label"], out["label"])


class ToneTest(unittest.TestCase):
    def test_no_probs_is_backward_compatible(self):
        old = et.tone_block("sadness", emotion="sadness", intensity=0.6,
                            self_esteem=0.6)
        self.assertEqual(old["tendency"], "sadness")
        self.assertIn("少说两句", old["text"])
        self.assertFalse(old["mixed"])

    def test_single_distribution_keeps_tendency(self):
        probs = {"joy": 0.8, "trust": 0.1, "sadness": 0.05,
                 "anger": 0.02, "fear": 0.02, "loneliness": 0.01}
        out = et.tone_block("", probs=probs)
        self.assertEqual(out["tendency"], "joy")
        self.assertIn("分享", out["text"])

    def test_mixed_distribution_uses_mixed_branch(self):
        probs = {"sadness": 0.36, "anger": 0.33, "fear": 0.12,
                 "joy": 0.08, "loneliness": 0.07, "trust": 0.04}
        out = et.tone_block("", probs=probs)
        self.assertTrue(out["mixed"])
        self.assertEqual(out["tendency"], "mixed")
        self.assertIn("混合情绪", out["text"])
        for token in ("轻", "慢", "留点空白"):
            self.assertIn(token, out["text"])

    def test_tone_stage_attaches_distribution(self):
        ctx = {"state": core_state(eg.PROTOTYPES["joy"]),
               "meta": {"template_opts": {}}}
        out = st.expr_tone().run(ctx)
        self.assertIn("dist", out["meta"]["expr_tone"])
        self.assertIn("top1", out["meta"]["expr_tone"])


class WiringStaticTest(unittest.TestCase):
    def test_page_debug_exposes_emotion_dist(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[2] / "main.py").read_text(
            encoding="utf-8")
        self.assertIn("emotion_geometry", source)
        self.assertIn("emotion_dist", source)


if __name__ == "__main__":
    unittest.main()
