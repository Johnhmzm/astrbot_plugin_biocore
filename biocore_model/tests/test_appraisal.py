# -*- coding: utf-8 -*-
"""Appraisal dims -> state deltas: matrix, monotonicity, caps, parse, wiring."""
import unittest

from biocore_model import appraisal as ap

MAIN = __import__("pathlib").Path(__file__).resolve().parents[2] / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")


def d(**kw):
    base = {name: 0.0 for name in ap.DIMS}
    base.update(kw)
    return base


class MatrixTest(unittest.TestCase):
    def test_weights_shape(self):
        self.assertEqual(set(ap.WEIGHTS), set(ap.DIMS))
        for dim in ap.DIMS:
            self.assertEqual(set(ap.WEIGHTS[dim]), set(ap.OUTPUTS))

    def test_monotonic_goal_v(self):
        low = ap.appraise(d(goal=0.0), confidence=1.0)
        high = ap.appraise(d(goal=0.8), confidence=1.0)
        self.assertGreater(high.get("v", 0.0), low.get("v", 0.0))

    def test_monotonic_blame_self_esteem_and_stress(self):
        low = ap.appraise(d(blame=0.0), confidence=1.0)
        high = ap.appraise(d(blame=0.9), confidence=1.0)
        self.assertLess(high["self_esteem"], low.get("self_esteem", 0.0))
        self.assertGreater(high["stress"], low.get("stress", 0.0))

    def test_monotonic_hit_social_and_stress(self):
        low = ap.appraise(d(hit=0.0), confidence=1.0)
        high = ap.appraise(d(hit=0.9), confidence=1.0)
        self.assertLess(high["social"], low.get("social", 0.0))
        self.assertGreater(high["stress"], low.get("stress", 0.0))

    def test_monotonic_control_stress_down(self):
        low = ap.appraise(d(control=0.0), confidence=1.0)
        high = ap.appraise(d(control=0.9), confidence=1.0)
        self.assertLess(high.get("stress", 0.0), low.get("stress", 0.0))

    def test_involve_amplifies(self):
        cold = ap.appraise(d(goal=0.1, involve=0.0), confidence=1.0)
        hot = ap.appraise(d(goal=0.1, involve=1.0), confidence=1.0)
        self.assertGreater(hot["v"], cold["v"])
        self.assertGreater(hot["trust"], cold["trust"])

    def test_confidence_scales(self):
        half = ap.appraise(d(goal=0.2, blame=0.2), confidence=0.5)
        full = ap.appraise(d(goal=0.2, blame=0.2), confidence=1.0)
        for key in ("v", "stress"):
            self.assertAlmostEqual(half[key] * 2, full[key], places=3)

    def test_caps(self):
        out = ap.appraise({name: 1.0 for name in ap.DIMS}, confidence=1.0)
        for key, value in out.items():
            self.assertLessEqual(abs(value), ap.CAPS[key] + 1e-9)

    def test_out_of_range_is_clipped(self):
        clipped = ap.appraise(d(goal=5.0), confidence=1.0)
        normal = ap.appraise(d(goal=1.0), confidence=1.0)
        self.assertEqual(clipped, normal)
        self.assertEqual(ap.appraise(d(blame=-3.0), confidence=1.0), {})

    def test_missing_dims_default(self):
        self.assertEqual(ap.appraise({}, confidence=1.0), {})
        out = ap.appraise({"goal": -0.5}, confidence=1.0)
        self.assertLess(out["v"], 0.0)


class ParseTest(unittest.TestCase):
    RAW = ('{"dims":{"goal":-0.6,"blame":0.8,"control":0.2,"certainty":0.5,'
           '"novelty":0.3,"involve":0.9,"hit":0.6},"why":"被骂","c":0.8}')

    def test_parse_ok(self):
        out = ap.parse(self.RAW)
        self.assertEqual(out["source"], "appraisal")
        self.assertAlmostEqual(out["dims"]["goal"], -0.6)
        self.assertEqual(out["why"], "被骂")

    def test_parse_fence_and_clip(self):
        raw = "\x60\x60\x60json\n" + self.RAW + "\n\x60\x60\x60"
        out = ap.parse(raw)
        self.assertEqual(out["dims"]["blame"], 0.8)

    def test_low_confidence_dropped(self):
        low = self.RAW.replace('"c":0.8', '"c":0.2')
        self.assertEqual(ap.parse(low), {})

    def test_garbage_dropped(self):
        self.assertEqual(ap.parse("不是 JSON"), {})


class AsyncProbeTest(unittest.IsolatedAsyncioTestCase):
    async def test_probe_success(self):
        async def call(prompt):
            return ParseTest.RAW
        out = await ap.probe("hi", "", call)
        self.assertEqual(out["dims"]["hit"], 0.6)

    async def test_probe_timeout_empty(self):
        async def call(prompt):
            await __import__("asyncio").sleep(1.0)
        self.assertEqual(await ap.probe("hi", "", call, timeout=0.05), {})


class FeedbackTest(unittest.TestCase):
    def test_feedback_payload(self):
        deltas = ap.appraise(d(goal=0.8, hit=0.9), confidence=1.0)
        payload = ap.feedback_payload(deltas, 0.8, source="user")
        self.assertIn("valence_delta", payload)
        self.assertEqual(payload["source"], "user")
        self.assertAlmostEqual(payload["confidence"], 0.8)

    def test_needs_deltas(self):
        hurt = ap.needs_deltas(d(blame=1.0, hit=1.0))
        self.assertLess(hurt["self_esteem"], 0.0)
        warm = ap.needs_deltas(d(goal=1.0, involve=1.0))
        self.assertGreater(warm["self_esteem"], 0.0)


class WiringStaticTest(unittest.TestCase):
    def test_both_paths_and_fallback(self):
        self.assertIn("appraisal src=user dims=%s deltas=%s c=%.2f", SOURCE)
        self.assertIn("appraisal src=reply dims=%s deltas=%s c=%.2f", SOURCE)
        self.assertIn("lexical_fallback_enabled", SOURCE)
        self.assertIn("classify_user_msg(text)", SOURCE)
        self.assertIn("getattr(self, \"lexical_fallback_enabled\", True)", SOURCE)
        self.assertIn("_appraisal_mod.probe", SOURCE)
        self.assertIn("appraise(_dims, confidence=_conf)", SOURCE)


if __name__ == "__main__":
    unittest.main()
