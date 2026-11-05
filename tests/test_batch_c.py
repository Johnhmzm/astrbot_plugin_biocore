# -*- coding: utf-8 -*-
import copy
import unittest
from biocore_runtime import batch_c

class BatchCTest(unittest.TestCase):
    def state(self, **rel):
        base = {"relationship": {"trust": 0.5, "hours_total": 12.0,
                                 "gratitude": 0.2, "bids": []},
                "core": {"v": 0.1, "a": 0.5}, "self": {"v": 0.1}}
        base["relationship"].update(rel)
        return base

    def test_fields_complete(self):
        out = batch_c.apply_turn(self.state(), "turn_end", {})
        for name in batch_c.FIELDS:
            self.assertIn(name, out)
        self.assertTrue(out["ok"])

    def test_default_dry_run(self):
        out = batch_c.apply_turn(self.state(), "turn_end", {})
        self.assertTrue(out["dry_run"])

    def test_no_state_mutation(self):
        state = self.state()
        before = copy.deepcopy(state)
        batch_c.apply_turn(state, "turn_end", {"kept": True, "regular": True})
        self.assertEqual(state, before)

    def test_relationship_log_present(self):
        out = batch_c.apply_turn(self.state(), "turn_end", {"kept": True})
        logs = [row for row in out["logs"] if row.get("kind") == "relationship_accumulation"]
        self.assertTrue(logs)
        self.assertTrue(logs[0]["dry_run"])
        self.assertIn("trust_delta", logs[0])

    def test_non_dry_log_is_proposed(self):
        out = batch_c.apply_turn(self.state(), "turn_end", {"dry_run": False, "kept": True})
        self.assertFalse(out["dry_run"])
        self.assertTrue(any(row.get("action") == "proposed" for row in out["logs"]))
        self.assertTrue(any("pure" in str(row.get("reason")) for row in out["logs"]))

    def test_trust_delta_direction(self):
        no = batch_c.apply_turn(self.state(), "turn_end", {"trust_delta": 0})
        yes = batch_c.apply_turn(self.state(), "turn_end", {"kept": True, "regular": True,
                                                           "response_rate": 1.0})
        self.assertGreaterEqual(yes["relationship_trust"]["delta"],
                                no["relationship_trust"]["delta"])

    def test_stage_for_hours(self):
        early = batch_c.apply_turn(self.state(hours_total=1.0), "turn_end", {})
        late = batch_c.apply_turn(self.state(hours_total=500.0), "turn_end", {})
        self.assertIn("stage", early["relationship_stage"])
        self.assertIn("stage", late["relationship_stage"])
        self.assertNotEqual(early["relationship_stage"]["stage"],
                            late["relationship_stage"]["stage"])

    def test_connection_bid_record(self):
        out = batch_c.apply_turn(self.state(), "turn_start", {"bid": "hello", "now": 100})
        self.assertIsInstance(out["connection_bids"], dict)
        self.assertIn("bids", out["connection_bids"])

    def test_metacog_shape(self):
        out = batch_c.apply_turn(self.state(), "turn_end", {"confidence": 0.2, "guard_hits": 1})
        self.assertIn("result", out["metacog"])

    def test_possible_selves_shape(self):
        out = batch_c.apply_turn(self.state(), "turn_end", {})
        self.assertIn("result", out["possible_selves"])

    def test_repair_inactive_or_shape(self):
        out = batch_c.apply_turn(self.state(), "turn_end", {})
        self.assertIsInstance(out["repair"], dict)
        out2 = batch_c.apply_turn(self.state(), "turn_end", {
            "repair": True, "severity": 0.8, "apology_quality": 0.5, "apology_count": 1})
        self.assertIsInstance(out2["repair"], dict)

    def test_self_interest_shape(self):
        out = batch_c.apply_turn(self.state(), "turn_end", {})
        self.assertIn("view", out["self_interest"])
        self.assertIn("self_interest.weight", out["deltas"])

    def test_self_verification_shape(self):
        out = batch_c.apply_turn(self.state(), "turn_end", {"misread": 0.5, "clarity": 0.3})
        self.assertIn("result", out["self_verification"])
        self.assertIn("self_verification.correction_urge", out["deltas"])

    def test_social_repair_shape(self):
        out = batch_c.apply_turn(self.state(), "turn_end", {"kindness": True,
                                                           "user_mood": "sad"})
        self.assertIsInstance(out["social_repair"], dict)
        self.assertIn("social_repair.gratitude", out["deltas"])

    def test_phase_variants(self):
        for phase in ("turn_start", "turn_end", "state"):
            out = batch_c.apply_turn(self.state(), phase, {})
            self.assertEqual(out["phase"], phase)

    def test_missing_inputs(self):
        out = batch_c.apply_turn({}, "turn_end", {})
        self.assertTrue(out["ok"])
        self.assertEqual(out["relationship_trust"]["delta"], 0.0)

    def test_empty_relationship(self):
        out = batch_c.apply_turn({"relationship": {}}, "turn_end", {})
        self.assertTrue(out["ok"])
        self.assertIn("relationship.stage", out["deltas"])

    def test_deltas_are_proposals_not_mutation(self):
        state = self.state()
        out = batch_c.apply_turn(state, "turn_end", {"kept": True})
        self.assertIn("relationship.trust", out["deltas"])
        self.assertEqual(state["relationship"]["trust"], 0.5)
