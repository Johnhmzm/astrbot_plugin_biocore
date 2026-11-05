# -*- coding: utf-8 -*-
"""task-224 (5a): the 17 P0 modules are evaluated and exposed via /state."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from biocore_runtime import pipeline, signals


class SignalsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "data"
        self.store = self.data_dir / "memory"
        (self.store / "sessions").mkdir(parents=True)
        self.state = {"core": {"v": 0.2, "a": 0.6, "stress": 0.4,
                               "social": 0.4, "energy": 0.7}}
        self.rel = {"trust": 0.55, "closeness": 0.5, "conflict": 0.1,
                    "days_known": 12}
        self.out = signals.evaluate(self.store, "s1",
                                    user_text="我们约好明天见面，谢谢你",
                                    assistant_text="好。",
                                    state=self.state, relationship=self.rel,
                                    now=time.time())

    def tearDown(self):
        self.tmp.cleanup()

    def module_ok(self, group, name):
        row = self.out[group][name]
        self.assertTrue(row.get("enabled"), row)
        return row

    def test_affective_labor(self):
        self.module_ok("perception", "affective_labor")

    def test_compassion_fatigue(self):
        self.module_ok("perception", "compassion_fatigue")

    def test_connection_bids(self):
        self.module_ok("perception", "connection_bids")

    def test_defense_mechanisms(self):
        self.module_ok("perception", "defense_mechanisms")

    def test_emotion_geometry(self):
        self.module_ok("perception", "emotion_geometry")

    def test_needs_events(self):
        self.module_ok("perception", "needs_events")

    def test_social_pain(self):
        self.module_ok("perception", "social_pain")

    def test_social_repair(self):
        self.module_ok("perception", "social_repair")

    def test_commitment_extractor(self):
        row = self.module_ok("relationship", "commitment_extractor")
        self.assertIsInstance(row.get("value"), dict)

    def test_relation_stage(self):
        self.module_ok("relationship", "relation_stage")

    def test_relationship_stage(self):
        self.module_ok("relationship", "relationship_stage")

    def test_repair_after_boundary(self):
        self.module_ok("relationship", "repair_after_boundary")

    def test_metacog(self):
        self.module_ok("self", "metacog")

    def test_possible_selves(self):
        self.module_ok("self", "possible_selves")

    def test_self_interest(self):
        self.module_ok("self", "self_interest")

    def test_self_verification(self):
        self.module_ok("self", "self_verification")

    def test_counts_and_sidecar(self):
        self.assertEqual(self.out["counts"]["perception"], 8)
        self.assertEqual(self.out["counts"]["relationship"], 4)
        self.assertEqual(self.out["counts"]["self"], 4)
        doc = json.loads((self.data_dir / "signals.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["latest"]["session_id"], "s1")

    def test_state_exposes_signals(self):
        pipeline.dispatch("turn_start", {
            "store": str(self.store), "session_id": "s1",
            "user_text": "你好", "capture": False,
            "persona_profile": str(Path(self.tmp.name) / "missing.json")})
        body = pipeline.dispatch("state", {
            "store": str(self.store), "session_id": "s1",
            "persona_profile": str(Path(self.tmp.name) / "missing.json")})["state"]
        self.assertIn("signals", body)
        self.assertTrue(body["signals"]["enabled"]["metacog"])
        self.assertEqual(body["signals"]["counts"]["self"], 4)


if __name__ == "__main__":
    unittest.main()
