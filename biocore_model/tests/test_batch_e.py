# -*- coding: utf-8 -*-
"""task-239 (batch E): the thirty-two miscellaneous / adapter modules.

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_batch_e.py"
"""
import copy
import json
import os
import unittest

from biocore_runtime import batch_e as be


NOW = 1700000000.0


def state():
    return {"core": {"v": -0.2, "a": 0.6, "stress": 0.55, "social": 0.45},
            "needs": {"belonging": 0.5, "self_esteem": 0.55, "control": 0.6,
                      "meaningful_existence": 0.55}}


def payload(**extra):
    data = {"now": NOW,
            "before": {"v": -0.1, "a": 0.6, "stress": 0.5},
            "deltas": {"v": 0.5, "stress": 0.5, "social": 0.5},
            "command": "biocore_core shadow", "mode": "shadow",
            "provider": "primary", "fallback_order": ["secondary", "tertiary"],
            "noise_seed": "s1", "wander_seed": "s1"}
    data.update(extra)
    return data


def turn(phase, **extra):
    return be.apply_turn(state(), phase, payload(**extra))


class SwitchTest(unittest.TestCase):
    def test_default_is_on(self):
        self.assertTrue(be.enabled())
        self.assertTrue(be.enabled({}, env={}))

    def test_payload_and_env_can_turn_it_off(self):
        self.assertFalse(be.enabled({"batch_e": False}))
        self.assertFalse(be.enabled({"switches": {"batch_e": False}}))
        self.assertFalse(be.enabled({}, env={"BIOCORE_BATCH_E": "0"}))

    def test_bad_phase_is_refused(self):
        out = be.apply_turn(state(), "recall", payload())
        self.assertFalse(out["enabled"])
        self.assertEqual(out["reason"], "bad_phase")

    def test_thirty_two_modules_declared_and_available(self):
        self.assertEqual(len(be.MODULES), 32)
        out = turn("turn_start")
        self.assertEqual(out["counts"]["modules"], 32)
        self.assertEqual(out["counts"]["available"], 32)
        self.assertEqual(set(out["modules"]), set(be.MODULES))


class IsolationTest(unittest.TestCase):
    def test_platform_modules_are_never_invoked(self):
        out = turn("turn_start")
        active = {name for name, flag in out["activity"].items() if flag}
        self.assertEqual(set(be.PLATFORM) & active, set())
        for name in be.PLATFORM:
            self.assertTrue(out["platform"][name]["available"])
            self.assertFalse(out["platform"][name]["used"])
            self.assertEqual(out["platform"][name]["reason"],
                             "platform_isolation")

    def test_isolation_flags_are_false(self):
        out = turn("turn_start")
        self.assertEqual(out["isolation"],
                         {"network": False, "host_imports": False,
                          "filesystem": False})
        self.assertEqual(out["counts"]["platform"], len(be.PLATFORM))

    def test_host_coupled_modules_are_isolated(self):
        for name in ("core_mode", "emotion_probe", "bio_config",
                     "plugin_routes", "ui_settings"):
            self.assertIn(name, be.PLATFORM)

    def test_skipped_rows_explain_themselves(self):
        out = turn("turn_start")
        reasons = {row["reason"] for row in out["skipped"]}
        self.assertIn("platform_isolation", reasons)
        for row in out["skipped"]:
            self.assertIn("module", row)


class DiagnosticsTest(unittest.TestCase):
    def test_snapshot_carries_the_body_numbers(self):
        snapshot = turn("turn_start")["reads"]["diagnostics"]["snapshot"]
        self.assertAlmostEqual(snapshot["v"], -0.2, places=4)
        self.assertAlmostEqual(snapshot["stress"], 0.55, places=4)
        self.assertIn("belonging", snapshot)

    def test_diff_reports_only_moved_values(self):
        diff = turn("turn_start")["reads"]["diagnostics"]["diff"]
        self.assertEqual(set(diff), {"v", "social", "stress"})
        self.assertAlmostEqual(diff["stress"], 0.05, places=4)

    def test_delta_budget_limits_the_message(self):
        value = turn("turn_start")["reads"]["diagnostics"]["deltas"]
        self.assertAlmostEqual(value["total"], 1.5, places=4)
        self.assertLessEqual(value["budget_total"], 1.2 + 1e-6)
        self.assertTrue(value["limited"])

    def test_legend_is_bounded(self):
        value = turn("turn_start")["reads"]["diagnostics"]
        self.assertLessEqual(value["legend_chars"], be.LEGEND_CHARS)
        self.assertGreater(value["legend_chars"], 0)

    def test_circadian_alertness_is_bounded_and_dips_at_night(self):
        night = turn("turn_start", hour=3)["reads"]["diagnostics"]["alertness"]
        noon = turn("turn_start", hour=10)["reads"]["diagnostics"]["alertness"]
        for value in (night, noon):
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)
        self.assertLess(night, noon)

    def test_diagnostic_row_is_written_to_state(self):
        row = turn("turn_end")["state_deltas"]["diagnostic_row"]
        self.assertEqual(row["phase"], "turn_end")
        self.assertTrue(row["budget_limited"])
        self.assertIn("diff_count", row)


class ConfigTest(unittest.TestCase):
    def test_command_parsing(self):
        command = turn("turn_start")["reads"]["config"]["command"]
        self.assertTrue(command["usable"])
        self.assertEqual(command["mode"], "shadow")

    def test_provider_fallback_candidates(self):
        config = turn("turn_start")["reads"]["config"]
        self.assertEqual(config["candidate_count"], 3)
        self.assertEqual(config["mode"], "shadow")

    def test_stages_factory_is_reported(self):
        stages = turn("turn_start")["reads"]["config"]["stages"]
        self.assertIsInstance(stages, list)


class MonitoringTest(unittest.TestCase):
    def test_source_monitoring_readout(self):
        source = turn("turn_start")["reads"]["monitoring"]["source"]
        self.assertIn("source", source)
        self.assertIn("confidence", source)
        self.assertGreaterEqual(source["confidence"], 0.0)
        self.assertLessEqual(source["confidence"], 1.0)

    def test_mind_wander_is_deterministic(self):
        first = turn("turn_start")["reads"]["monitoring"]["wander"]
        second = turn("turn_start")["reads"]["monitoring"]["wander"]
        self.assertEqual(first, second)
        self.assertIn("topic", first)

    def test_noise_window_is_bounded(self):
        noise = turn("turn_start", noise_count=6)["reads"]["monitoring"]
        self.assertEqual(len(noise["noise"]), 6)
        self.assertLessEqual(noise["noise_max"], 3.0)

    def test_learning_probe_and_scenarios(self):
        probe = turn("turn_start")["reads"]["probe"]
        self.assertIn("rows", probe["learning"])
        self.assertGreaterEqual(probe["learning"]["ratio"], 0.0)
        self.assertEqual(len(probe["scenarios"]), 8)


class ContractTest(unittest.TestCase):
    def test_state_is_never_mutated(self):
        before = state()
        snapshot = copy.deepcopy(before)
        be.apply_turn(before, "turn_start", payload())
        be.apply_turn(before, "turn_end", payload())
        be.diagnose(before, payload())
        self.assertEqual(json.dumps(before, sort_keys=True),
                         json.dumps(snapshot, sort_keys=True))

    def test_deterministic_numbers(self):
        first = turn("turn_start")
        second = turn("turn_start")
        for out in (first, second):
            out.pop("ts", None)
        self.assertEqual(json.dumps(first, sort_keys=True, ensure_ascii=False),
                         json.dumps(second, sort_keys=True, ensure_ascii=False))

    def test_json_safe(self):
        for phase in ("turn_start", "turn_end"):
            json.dumps(turn(phase), ensure_ascii=False)

    def test_diagnose_is_the_turn_start_row(self):
        direct = be.diagnose(state(), payload())
        started = be.apply_turn(state(), "turn_start", payload())
        self.assertEqual(direct["reads"]["diagnostics"],
                         started["reads"]["diagnostics"])

    def test_missing_payload_degrades_quietly(self):
        out = be.apply_turn(state(), "turn_start", {})
        self.assertTrue(out["enabled"])
        self.assertIn("diagnostics", out["reads"])
        self.assertEqual(out["reads"]["diagnostics"]["diff"], {})


if __name__ == "__main__":
    unittest.main()
