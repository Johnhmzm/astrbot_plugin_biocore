# -*- coding: utf-8 -*-
"""task-148 自我层单测：纯函数、意图归一、SVO、满足度、时间调制、接线。

全部断言只依赖 biocore_model.self_intent 的纯函数；接线测试只读 main.py 与
_conf_schema.json 的源码文本，不导入 AstrBot。
"""
import ast
import json
import math
import unittest
from pathlib import Path

from biocore_model import self_intent as si

ROOT = Path(__file__).resolve().parents[2]
MAIN_SRC = (ROOT / "main.py").read_text(encoding="utf-8")
SCHEMA = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))

DEFAULT_NEEDS = {"belonging": 0.6, "self_esteem": 0.6,
                 "control": 0.6, "meaningful_existence": 0.6}
CALM = {"stress": 0.2, "energy": 0.7, "social": 0.6, "trust": 0.6,
        "boundary_pressure": 0.0}


def _rel(closeness=0.5, trust=0.5, conflict=0.0):
    return {"closeness": closeness, "trust": trust, "conflict": conflict}


def _score(result, kind):
    for row in result.get("candidates") or []:
        if row.get("kind") == kind:
            return float(row.get("score", 0.0))
    return 0.0


class ContractTest(unittest.TestCase):
    def test_contract_keys(self):
        result = si.evaluate(snapshot=CALM, relationship=_rel(),
                             needs=DEFAULT_NEEDS)
        for key in ("intents", "motivation", "self_weight", "satisfaction",
                    "expected", "top", "drive", "urge", "candidates"):
            self.assertIn(key, result)

    def test_at_most_two_intents(self):
        result = si.evaluate(snapshot=CALM, relationship=_rel(0.9, 0.9),
                             needs={"belonging": 0.0, "self_esteem": 0.1,
                                    "control": 0.1, "meaningful_existence": 0.1})
        self.assertGreaterEqual(len(result["intents"]), 1)
        self.assertLessEqual(len(result["intents"]), si.MAX_INTENTS)

    def test_weights_normalized_exactly(self):
        for needs in (DEFAULT_NEEDS, {"belonging": 0.1, "self_esteem": 0.2,
                                      "control": 0.3, "meaningful_existence": 0.4}):
            result = si.evaluate(snapshot=CALM, relationship=_rel(),
                                 needs=needs)
            total = sum(item["weight"] for item in result["intents"])
            self.assertAlmostEqual(total, 1.0, places=3)

    def test_kinds_and_reasons(self):
        result = si.evaluate(snapshot=CALM, relationship=_rel(), needs=DEFAULT_NEEDS)
        for item in result["intents"]:
            self.assertIn(item["kind"], si.KINDS)
            self.assertTrue(item.get("reason"))
            self.assertGreaterEqual(item["weight"], 0.0)
            self.assertLessEqual(item["weight"], 1.0)

    def test_motivation_within_twenty_chars(self):
        cases = [
            {"snapshot": CALM, "relationship": _rel(0.9, 0.9),
             "needs": {"belonging": 0.1, "self_esteem": 0.6,
                       "control": 0.6, "meaningful_existence": 0.6},
             "silence_seconds": 36000},
            {"snapshot": {"stress": 0.9, "energy": 0.1},
             "relationship": _rel(0.5, 0.3), "needs": DEFAULT_NEEDS},
            {"snapshot": CALM, "relationship": _rel(0.3, 0.3, 0.9),
             "needs": DEFAULT_NEEDS},
            {"snapshot": CALM, "relationship": _rel(), "needs": DEFAULT_NEEDS},
        ]
        for case in cases:
            result = si.evaluate(**case)
            self.assertLessEqual(len(result["motivation"]), 20)
            self.assertTrue(result["motivation"])

    def test_disabled_falls_back_to_comply(self):
        result = si.evaluate(snapshot=CALM, relationship=_rel(0.3, 0.3, 0.9),
                             needs=DEFAULT_NEEDS, flags={"enabled": False})
        self.assertFalse(result["enabled"])
        self.assertEqual(result["top"], "顺着你")
        self.assertEqual(result["intents"], [{"kind": "顺着你", "weight": 1.0,
                                              "reason": "自我层关闭"}])
        self.assertEqual(result["candidates"], [])

    def test_candidates_count_and_order(self):
        result = si.evaluate(snapshot=CALM, relationship=_rel(), needs=DEFAULT_NEEDS)
        rows = result["candidates"]
        self.assertGreaterEqual(len(rows), 2)
        self.assertLessEqual(len(rows), si.MAX_CANDIDATES)
        scores = [row["score"] for row in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))


class SelfWeightTest(unittest.TestCase):
    def test_bounded(self):
        self.assertEqual(si.self_weight(1.0, -1.0, 1.0, 1.0, 0.0),
                         si.SELF_WEIGHT_CEIL)
        self.assertEqual(si.self_weight(-1.0, 1.0, 0.0, 0.0, 1.0),
                         si.SELF_WEIGHT_FLOOR)
        for closeness in (0.0, 0.5, 1.0):
            for trust in (0.0, 0.5, 1.0):
                for stress in (0.0, 0.5, 1.0):
                    value = si.self_weight(0.0, 0.0, closeness, trust, stress)
                    self.assertGreaterEqual(value, si.SELF_WEIGHT_FLOOR)
                    self.assertLessEqual(value, si.SELF_WEIGHT_CEIL)

    def test_closeness_raises_weight(self):
        low = si.self_weight(0.0, 0.0, 0.1, 0.5, 0.3)
        high = si.self_weight(0.0, 0.0, 0.9, 0.5, 0.3)
        self.assertGreater(high, low)

    def test_stress_lowers_weight(self):
        calm = si.self_weight(0.0, 0.0, 0.6, 0.6, 0.1)
        tense = si.self_weight(0.0, 0.0, 0.6, 0.6, 0.9)
        self.assertLess(tense, calm)

    def test_trust_raises_weight(self):
        low = si.self_weight(0.0, 0.0, 0.5, 0.1, 0.3)
        high = si.self_weight(0.0, 0.0, 0.5, 0.9, 0.3)
        self.assertGreater(high, low)

    def test_probe_other_state_shifts_weight(self):
        negative = si.evaluate(snapshot={"stress": 0.2},
                               relationship=_rel(0.6, 0.6),
                               needs=DEFAULT_NEEDS,
                               other_estimate={"v": -0.9, "stress": 0.8})
        positive = si.evaluate(snapshot={"stress": 0.2},
                               relationship=_rel(0.6, 0.6),
                               needs=DEFAULT_NEEDS,
                               other_estimate={"v": 0.9, "stress": 0.0})
        self.assertLess(negative["other_satisfaction"], 0.0)
        self.assertGreater(positive["other_satisfaction"], 0.0)
        self.assertGreater(negative["self_weight"], positive["self_weight"])


class SatisfactionTest(unittest.TestCase):
    def test_deficit_is_negative(self):
        result = si.evaluate(snapshot=CALM, relationship=_rel(),
                             needs={"belonging": 0.2, "self_esteem": 0.2,
                                    "control": 0.2, "meaningful_existence": 0.2})
        self.assertLess(result["satisfaction"], 0.0)
        self.assertLess(result["satisfaction_by_need"]["belonging"], 0.0)

    def test_surplus_is_positive(self):
        result = si.evaluate(snapshot=CALM, relationship=_rel(),
                             needs={"belonging": 0.95, "self_esteem": 0.95,
                                    "control": 0.95, "meaningful_existence": 0.95})
        self.assertGreater(result["satisfaction"], 0.0)

    def test_expected_drifts_toward_needs(self):
        prev = {"belonging": 0.5, "self_esteem": 0.5,
                "control": 0.5, "meaningful_existence": 0.5}
        result = si.evaluate(snapshot=CALM, relationship=_rel(),
                             needs={"belonging": 0.9, "self_esteem": 0.9,
                                    "control": 0.9, "meaningful_existence": 0.9},
                             expected=prev)
        self.assertGreater(result["expected"]["belonging"], 0.5)
        self.assertLess(result["expected"]["belonging"], 0.9)
        # pure: the caller's dict is never mutated
        self.assertEqual(prev["belonging"], 0.5)

    def test_expected_is_bounded(self):
        result = si.evaluate(snapshot=CALM, relationship=_rel(),
                             needs=DEFAULT_NEEDS,
                             expected={"belonging": 12.0, "self_esteem": -3.0})
        for key in si.NEED_KEYS:
            self.assertGreaterEqual(result["expected"][key], 0.0)
            self.assertLessEqual(result["expected"][key], 1.0)


class TimeAndRelationTest(unittest.TestCase):
    def test_long_silence_raises_company_candidate(self):
        needy = dict(DEFAULT_NEEDS, belonging=0.2)
        long_gap = si.evaluate(snapshot=CALM, relationship=_rel(0.9, 0.9),
                               needs=needy, silence_seconds=12 * 3600)
        just_talked = si.evaluate(snapshot=CALM, relationship=_rel(0.9, 0.9),
                                  needs=needy, silence_seconds=0)
        self.assertEqual(long_gap["top"], "要你陪")
        self.assertGreater(_score(long_gap, "要你陪"),
                           _score(just_talked, "要你陪"))

    def test_high_conflict_raises_refusal(self):
        result = si.evaluate(snapshot={"stress": 0.9, "energy": 0.8,
                                       "boundary_pressure": 0.8},
                             relationship=_rel(0.3, 0.3, 0.9),
                             needs=DEFAULT_NEEDS)
        self.assertEqual(result["top"], "拒绝话题")

    def test_low_energy_favors_being_alone(self):
        result = si.evaluate(snapshot={"stress": 0.9, "energy": 0.05},
                             relationship=_rel(0.5, 0.3),
                             needs=DEFAULT_NEEDS)
        self.assertEqual(result["top"], "自己待着")

    def test_default_calm_turn_complies(self):
        result = si.evaluate(snapshot=CALM, relationship=_rel(),
                             needs=DEFAULT_NEEDS)
        self.assertEqual(result["top"], "顺着你")

    def test_snapshot_derived_needs_when_missing(self):
        result = si.evaluate(snapshot={"social": 1.0, "stress": 0.0,
                                       "energy": 1.0, "trust": 1.0,
                                       "attention": 1.0, "boredom": 0.0},
                             relationship=_rel())
        self.assertIn(result["top"], si.KINDS)
        self.assertGreaterEqual(result["drive"], 0.0)
        self.assertLessEqual(result["drive"], 1.0)


class RobustnessTest(unittest.TestCase):
    def test_garbage_inputs_are_safe(self):
        result = si.evaluate(snapshot={"stress": "abc", "energy": float("nan")},
                             relationship={"closeness": None, "state": "x"},
                             needs={"belonging": float("inf"), "control": -5},
                             other_estimate={"v": "bad"},
                             expected="nope",
                             silence_seconds="soon")
        self.assertGreaterEqual(len(result["intents"]), 1)
        self.assertLessEqual(len(result["intents"]), si.MAX_INTENTS)
        self.assertAlmostEqual(sum(i["weight"] for i in result["intents"]), 1.0,
                               places=3)

    def test_deterministic(self):
        first = si.evaluate(snapshot=CALM, relationship=_rel(), needs=DEFAULT_NEEDS)
        second = si.evaluate(snapshot=CALM, relationship=_rel(), needs=DEFAULT_NEEDS)
        self.assertEqual(first, second)

    def test_select_always_returns_normalized(self):
        for context in ({}, {"self_weight": 0.0, "drive": 1.0},
                        {"self_weight": 1.0, "drive": 0.0}):
            intents = si.select(context)
            self.assertGreaterEqual(len(intents), 1)
            self.assertLessEqual(len(intents), si.MAX_INTENTS)
            self.assertAlmostEqual(sum(i["weight"] for i in intents), 1.0,
                                   places=3)

    def test_directives_differ_by_intent(self):
        alone = si.evaluate(snapshot={"stress": 0.9, "energy": 0.05},
                            relationship=_rel(0.5, 0.3), needs=DEFAULT_NEEDS)
        company = si.evaluate(snapshot=CALM, relationship=_rel(0.9, 0.9),
                              needs=dict(DEFAULT_NEEDS, belonging=0.2),
                              silence_seconds=12 * 3600)
        has_alone = si.directives(alone)
        has_company = si.directives(company)
        self.assertNotEqual(has_alone["kind"], has_company["kind"])
        self.assertNotEqual(has_alone["length_scale"],
                            has_company["length_scale"])
        self.assertNotEqual(has_alone["initiative"], has_company["initiative"])

    def test_directives_disabled(self):
        out = si.directives({"enabled": False, "top": "要你陪"})
        self.assertEqual(out["length_scale"], 1.0)
        self.assertEqual(out["initiative"], 0.0)


class PurityTest(unittest.TestCase):
    def test_no_host_imports(self):
        tree = ast.parse((ROOT / "biocore_model" / "self_intent.py")
                         .read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
        self.assertEqual(modules, {"__future__", "math"})
        self.assertNotIn("import main", (ROOT / "biocore_model" / "self_intent.py")
                         .read_text(encoding="utf-8"))


class WiringTest(unittest.TestCase):
    def test_config_flag_in_schema(self):
        entry = SCHEMA.get("self_intent_enabled")
        self.assertIsInstance(entry, dict)
        self.assertEqual(entry.get("type"), "bool")
        self.assertIs(entry.get("default"), True)

    def test_main_reads_flag_and_computes_once(self):
        self.assertIn('self.config.get("self_intent_enabled", True)', MAIN_SRC)
        self.assertIn("self_intent_mod.evaluate(", MAIN_SRC)
        self.assertIn("core.self_intent", MAIN_SRC)
        self.assertIn("core.self_motivation", MAIN_SRC)
        self.assertIn("core.self_initiative", MAIN_SRC)
        self.assertIn("[biocore] self intent", MAIN_SRC)

    def test_expression_layer_reads_directives(self):
        self.assertIn("self_length_scale", MAIN_SRC)
        self.assertIn("self_intent_mod.directives(", MAIN_SRC)


class PayloadTest(unittest.TestCase):
    def test_payload_defaults(self):
        out = si.payload(None)
        self.assertTrue(out["enabled"])
        self.assertEqual(out["top"], "顺着你")
        self.assertEqual(out["intents"], [])
        self.assertEqual(out["pending_prompts"], [])
        self.assertEqual(out["voice_phrases"], [])
        self.assertEqual(out["metacog"], {})

    def test_payload_projects_result(self):
        result = si.evaluate(snapshot=CALM, relationship=_rel(0.9, 0.9),
                             needs=dict(DEFAULT_NEEDS, belonging=0.2),
                             silence_seconds=12 * 3600)
        out = si.payload(result)
        self.assertEqual(out["top"], result["top"])
        self.assertEqual(len(out["intents"]), len(result["intents"]))
        self.assertAlmostEqual(out["top_weight"],
                               result["intents"][0]["weight"], places=3)
        self.assertLessEqual(out["self_weight"], si.SELF_WEIGHT_CEIL)
        self.assertGreaterEqual(out["self_weight"], si.SELF_WEIGHT_FLOOR)
        self.assertLessEqual(len(out["motivation"]), 20)

    def test_payload_bounds_extra_lists(self):
        out = si.payload(None,
                         pending_prompts=["a" * 400, "b", "c", "d"],
                         voice_phrases=["x" * 60, "y", "z"],
                         metacog={"band": "low" * 20, "confidence": 9,
                                  "converge": True, "allow_self_correction": True,
                                  "low_streak": 7, "reason": "r" * 200})
        self.assertEqual(len(out["pending_prompts"]), 3)
        self.assertLessEqual(len(out["pending_prompts"][0]), 60)
        self.assertEqual(len(out["voice_phrases"]), 2)
        self.assertLessEqual(len(out["voice_phrases"][0]), 20)
        self.assertEqual(len(out["metacog"]["band"]), 8)
        self.assertLessEqual(out["metacog"]["confidence"], 1.0)
        self.assertTrue(out["metacog"]["converge"])
        self.assertLessEqual(len(out["metacog"]["reason"]), 40)

    def test_payload_garbage_safe(self):
        out = si.payload("nope", pending_prompts="x", voice_phrases=3,
                         metacog="bad")
        self.assertEqual(out["intents"], [])
        self.assertEqual(out["pending_prompts"], [])
        self.assertEqual(out["voice_phrases"], [])


if __name__ == "__main__":
    unittest.main()
