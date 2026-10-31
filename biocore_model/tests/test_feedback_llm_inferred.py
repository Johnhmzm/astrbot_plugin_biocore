# -*- coding: utf-8 -*-
"""FB-1 inferred-meta path tests (interpretation layer -> feedback deltas)."""
import unittest

from biocore_model import feedback_flow as ff
from biocore_model import feedback_llm as fl

INFERRED = {
    "emotion": "joy",
    "intensity": 0.807,
    "valence_delta": 0.145,
    "arousal_delta": 0.048,
    "dominance_delta": 0.032,
    "social_delta": 0.040,
    "trust_delta": 0.016,
    "confidence": 0.677,
    "source": "inferred",
}
NOW = 1_700_000_000.0


class InferredParseTest(unittest.TestCase):
    def test_full_meta_maps_to_feedback_fields(self):
        result = fl.parse_to_deltas(INFERRED, now=NOW)
        self.assertEqual(result["source"], "inferred")
        deltas = result["deltas"]
        self.assertAlmostEqual(deltas["v"], 0.0982, places=4)
        self.assertAlmostEqual(deltas["a"], 0.0325, places=4)
        self.assertAlmostEqual(deltas["d"], 0.0217, places=4)
        self.assertAlmostEqual(deltas["social"], 0.0271, places=4)
        self.assertAlmostEqual(deltas["trust"], 0.0108, places=4)
        self.assertEqual(result["rejected"], [])

    def test_confidence_scales_deltas(self):
        low = dict(INFERRED, confidence=0.5)
        high = dict(INFERRED, confidence=0.9)
        low_deltas = fl.parse_to_deltas(low, now=NOW)["deltas"]
        high_deltas = fl.parse_to_deltas(high, now=NOW)["deltas"]
        for field in ("v", "a", "d", "social", "trust"):
            self.assertGreater(high_deltas[field], low_deltas[field])
        self.assertAlmostEqual(high_deltas["v"] / low_deltas["v"], 0.9 / 0.5, places=3)

    def test_low_confidence_produces_nothing(self):
        payload = dict(INFERRED, confidence=0.39)
        result = fl.parse_to_deltas(payload, now=NOW)
        self.assertEqual(result["deltas"], {})
        self.assertEqual(result.get("gate"), "low_confidence")

    def test_confidence_threshold_boundary(self):
        result = fl.parse_to_deltas(dict(INFERRED, confidence=0.4), now=NOW)
        self.assertTrue(result["deltas"])
        self.assertNotIn("gate", result)

    def test_missing_confidence_produces_nothing(self):
        payload = dict(INFERRED)
        payload.pop("confidence")
        self.assertEqual(fl.parse_to_deltas(payload, now=NOW)["deltas"], {})

    def test_partial_fields_only_emit_present_ones(self):
        payload = {"valence_delta": 0.1, "confidence": 0.8}
        deltas = fl.parse_to_deltas(payload, now=NOW)["deltas"]
        self.assertEqual(list(deltas), ["v"])
        self.assertAlmostEqual(deltas["v"], 0.08, places=4)

    def test_invalid_field_is_rejected_not_crashing(self):
        payload = {"valence_delta": "not-a-number", "confidence": 0.9}
        result = fl.parse_to_deltas(payload, now=NOW)
        self.assertEqual(result["deltas"], {})
        self.assertIn("valence_delta", result["rejected"])

    def test_caps_are_applied(self):
        payload = {"valence_delta": 5.0, "confidence": 1.0}
        self.assertAlmostEqual(fl.parse_to_deltas(payload, now=NOW)["deltas"]["v"],
                               0.15, places=4)

    def test_idempotent_same_now(self):
        seen = {}
        first = fl.parse_to_deltas(INFERRED, now=NOW, seen=seen)
        second = fl.parse_to_deltas(INFERRED, now=NOW, seen=seen)
        self.assertTrue(first["deltas"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(second["deltas"], {})

    def test_audit_carries_confidence_and_reason(self):
        audit = fl.parse_to_deltas(INFERRED, now=NOW)["audit"]
        self.assertTrue(audit)
        for row in audit:
            self.assertEqual(row["reason"], "inferred meta")
            self.assertEqual(row["source"], "llm")
            self.assertGreater(row["confidence"], 0)


class LegacyPathUnchangedTest(unittest.TestCase):
    def test_target_value_path_still_works(self):
        result = fl.parse_to_deltas({"v": 0.9}, state={"v": 0.0}, now=NOW)
        self.assertAlmostEqual(result["deltas"]["v"], 0.15, places=4)

    def test_needs_path_still_works(self):
        result = fl.parse_to_deltas(
            {"needs": {"belonging": 0.9}}, state={"needs": {"belonging": 0.6}},
            now=NOW)
        self.assertAlmostEqual(result["deltas"]["needs"]["belonging"], 0.10,
                               places=4)


class ApplyLlmIntegrationTest(unittest.TestCase):
    def setUp(self):
        ff.reset_seen()

    def tearDown(self):
        ff.reset_seen()

    def test_apply_llm_consumes_inferred_meta(self):
        core = {"v": 0.0, "a": 0.5, "stress": 0.1, "trust": 0.5, "social": 0.5,
                "self_esteem": 0.5}
        report = ff.apply_llm(dict(INFERRED), core, NOW)
        deltas = report["deltas"]
        self.assertTrue(deltas)
        self.assertAlmostEqual(deltas["v"], 0.0982, places=4)
        self.assertAlmostEqual(deltas["a"], 0.0325, places=4)
        self.assertAlmostEqual(deltas["social"], 0.0271, places=4)
        self.assertAlmostEqual(deltas["trust"], 0.0108, places=4)
        # feedback_guard has no 'd' in its whitelist -> rejected at the gate
        rejected_fields = {row.get("field") if isinstance(row, dict) else row
                           for row in report["rejected"]}
        self.assertIn("d", rejected_fields)
        self.assertNotIn("d", deltas)
        self.assertGreater(report["summary"]["v"]["new"],
                           report["summary"]["v"]["old"])
        self.assertGreater(core["v"], 0.0)

    def test_apply_llm_ignores_low_confidence(self):
        core = {"v": 0.0, "a": 0.5, "stress": 0.1, "trust": 0.5, "social": 0.5}
        report = ff.apply_llm(dict(INFERRED, confidence=0.2), core, NOW)
        self.assertEqual(report["deltas"], {})
        self.assertEqual(report["summary"]["v"]["new"], report["summary"]["v"]["old"])


if __name__ == "__main__":
    unittest.main()
