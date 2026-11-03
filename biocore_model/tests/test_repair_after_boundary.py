# -*- coding: utf-8 -*-
"""task-155 修复流程单测：四阶段、道歉质量、超时回落、关闭、与 boundary 打通。

只依赖 biocore_model 的纯函数；不导入 main.py，不新增 LLM 调用。
"""
import unittest

from biocore_model import boundary as bd
from biocore_model import repair_after_boundary as rp

CALM = {"closeness": 0.5, "trust": 0.5, "conflict": 0.0}
EVENT = bd.judge("你就是个工具", CALM)


def gates(quality=0.0, count=0, severity=None):
    return rp.thresholds(EVENT["severity"] if severity is None else severity,
                        quality, count, CALM)


class ContractTest(unittest.TestCase):
    def test_result_keys(self):
        out = rp.evaluate(EVENT, relationship=CALM)
        for key in ("enabled", "active", "kind", "severity", "stage",
                    "label", "elapsed", "apology_quality", "apology_count",
                    "forgiveness", "debt", "hold", "resolved",
                    "fallback", "thresholds", "directive", "reason"):
            self.assertIn(key, out)

    def test_stages_and_labels(self):
        self.assertEqual(rp.STAGES, ("cold", "state", "record", "turn_page"))
        self.assertEqual(set(rp.LABELS), set(rp.STAGES))
        self.assertEqual(rp.LABELS["cold"], "冷处理")
        self.assertEqual(rp.LABELS["turn_page"], "翻页")

    def test_values_bounded(self):
        for elapsed in (0, 500, 5000, 20000, 999999):
            out = rp.evaluate(EVENT, elapsed_seconds=elapsed, relationship=CALM)
            for key in ("severity", "forgiveness", "debt"):
                self.assertGreaterEqual(out[key], 0.0)
                self.assertLessEqual(out[key], 1.0)
            self.assertGreaterEqual(out["elapsed"], 0.0)

    def test_gates_are_ordered(self):
        g = gates()
        self.assertLessEqual(g["state"], g["record"])
        self.assertLessEqual(g["record"], g["page"])


class StageProgressionTest(unittest.TestCase):
    def test_cold_right_after_crossing(self):
        out = rp.evaluate(EVENT, relationship=CALM)
        self.assertTrue(out["active"])
        self.assertEqual(out["stage"], "cold")
        self.assertTrue(out["hold"])
        self.assertFalse(out["resolved"])

    def test_state_after_cooling(self):
        out = rp.evaluate(EVENT, elapsed_seconds=gates()["state"],
                          relationship=CALM)
        self.assertEqual(out["stage"], "state")
        self.assertTrue(out["hold"])

    def test_record_after_a_while(self):
        out = rp.evaluate(EVENT, elapsed_seconds=gates()["record"],
                          relationship=CALM)
        self.assertEqual(out["stage"], "record")
        self.assertFalse(out["hold"])

    def test_turn_page_by_time(self):
        out = rp.evaluate(EVENT, elapsed_seconds=gates()["page"] + 1,
                          relationship=CALM)
        self.assertEqual(out["stage"], "turn_page")
        self.assertFalse(out["fallback"])


class ApologyTest(unittest.TestCase):
    def test_apology_speeds_stage_progress(self):
        elapsed = gates(quality=1.0, count=1)["page"] + 10
        slow = rp.evaluate(EVENT, elapsed_seconds=elapsed,
                           apology_quality=0.0, relationship=CALM)
        fast = rp.evaluate(EVENT, elapsed_seconds=elapsed,
                           apology_quality=1.0, relationship=CALM)
        self.assertGreater(rp.STAGES.index(fast["stage"]),
                           rp.STAGES.index(slow["stage"]))

    def test_apology_raises_forgiveness(self):
        elapsed = gates()["record"]
        low = rp.evaluate(EVENT, elapsed_seconds=elapsed,
                          apology_quality=0.0, relationship=CALM)
        high = rp.evaluate(EVENT, elapsed_seconds=elapsed,
                           apology_quality=1.0, relationship=CALM)
        self.assertGreater(high["forgiveness"], low["forgiveness"])

    def test_good_apology_resolves_page(self):
        out = rp.evaluate(EVENT,
                          elapsed_seconds=gates(1.0, 1)["page"] + 10,
                          apology_quality=1.0, relationship=CALM)
        self.assertEqual(out["stage"], "turn_page")
        self.assertTrue(out["resolved"])
        self.assertIn("过去", out["reason"])

    def test_good_apology_lowers_debt(self):
        elapsed = gates()["record"]
        low = rp.evaluate(EVENT, elapsed_seconds=elapsed,
                          apology_quality=0.0, relationship=CALM)
        high = rp.evaluate(EVENT, elapsed_seconds=elapsed,
                           apology_quality=0.9, relationship=CALM)
        self.assertLess(high["debt"], low["debt"])

    def test_repeated_apology_counts_less(self):
        self.assertLess(rp.apology_quality(0.9, 3),
                        rp.apology_quality(0.9, 1))
        self.assertLess(rp.thresholds(0.6, 0.9, 1)["state"],
                        rp.thresholds(0.6, 0.9, 3)["state"])


class TimeoutFallbackTest(unittest.TestCase):
    def test_timeout_falls_back_to_page(self):
        out = rp.evaluate(EVENT, elapsed_seconds=600, relationship=CALM,
                          flags={"timeout_seconds": 500})
        self.assertEqual(out["stage"], "turn_page")
        self.assertTrue(out["fallback"])
        self.assertFalse(out["resolved"])
        self.assertIn("账", out["reason"])

    def test_timeout_keeps_debt(self):
        out = rp.evaluate(EVENT, elapsed_seconds=600, relationship=CALM,
                          flags={"timeout_seconds": 500})
        self.assertGreater(out["debt"], 0.0)

    def test_good_apology_survives_timeout(self):
        out = rp.evaluate(EVENT, elapsed_seconds=2500,
                          apology_quality=0.95, relationship=CALM,
                          flags={"timeout_seconds": 2000})
        self.assertEqual(out["stage"], "turn_page")
        self.assertFalse(out["fallback"])


class AdvanceTest(unittest.TestCase):
    def test_stage_never_goes_backwards(self):
        state = rp.start(EVENT, CALM)
        first = rp.advance(state, 400)
        second = rp.advance(first, 3000)
        back = rp.advance(second, -999)
        order = [rp.STAGES.index(row["stage"])
                 for row in (state, first, second, back)]
        self.assertEqual(order, sorted(order))
        self.assertEqual(back["stage"], second["stage"])

    def test_advance_does_not_mutate_input(self):
        state = rp.start(EVENT, CALM)
        before = dict(state)
        rp.advance(state, 5000, apology_quality=0.5)
        self.assertEqual(state, before)

    def test_advance_records_apology(self):
        state = rp.advance(rp.start(EVENT, CALM), 100,
                            apology_quality=0.8)
        self.assertAlmostEqual(state["apology_quality"], 0.8)
        self.assertGreaterEqual(state["apology_count"], 1)
        self.assertGreater(state["forgiveness"], 0.0)


class BoundaryBridgeTest(unittest.TestCase):
    def test_crossed_boundary_opens_cold_flow(self):
        out = rp.from_boundary(EVENT, CALM)
        self.assertTrue(out["active"])
        self.assertEqual(out["stage"], "cold")
        self.assertEqual(out["kind"], EVENT["kind"])
        self.assertEqual(out["severity"], EVENT["severity"])

    def test_clean_boundary_does_not_open_flow(self):
        out = rp.from_boundary(bd.judge("晚安", CALM), CALM)
        self.assertFalse(out["active"])
        self.assertFalse(out["hold"])

    def test_accepts_plain_event_dict(self):
        out = rp.from_boundary({"crossed": True, "kind": "lie",
                                "severity": 0.8})
        self.assertTrue(out["active"])
        self.assertEqual(out["kind"], "lie")
        self.assertAlmostEqual(out["severity"], 0.8)

    def test_handoff_field_opens_flow(self):
        out = rp.from_boundary({"handoff": {"to": "repair_after_boundary"},
                                "kind": "contempt", "severity": 0.7})
        self.assertTrue(out["active"])
        self.assertEqual(out["kind"], "contempt")


class SwitchAndPolicyTest(unittest.TestCase):
    def test_disabled_returns_old_behavior(self):
        out = rp.evaluate(EVENT, relationship=CALM,
                          flags={"enabled": False})
        self.assertFalse(out["enabled"])
        self.assertFalse(out["active"])
        self.assertFalse(out["hold"])
        self.assertIn("关闭", out["reason"])

    def test_reply_policy_cold_suppresses_warmth(self):
        out = rp.reply_policy(rp.evaluate(EVENT, relationship=CALM))
        self.assertTrue(out["suppress_affection"])
        self.assertLessEqual(out["max_chars"], 25)
        self.assertEqual(out["mode"], "cold_short")

    def test_reply_policy_page_is_normal(self):
        state = rp.evaluate(EVENT, elapsed_seconds=gates()["page"] + 1,
                            relationship=CALM)
        out = rp.reply_policy(state)
        self.assertFalse(out["suppress_affection"])
        self.assertGreaterEqual(out["max_chars"], 100)

    def test_directives_bounded_every_stage(self):
        for elapsed in (0, gates()["state"], gates()["record"],
                        gates()["page"] + 1):
            out = rp.directives(rp.evaluate(EVENT, elapsed_seconds=elapsed,
                                           relationship=CALM))
            self.assertGreaterEqual(out["length_scale"], 0.3)
            self.assertLessEqual(out["length_scale"], 1.1)
            for key in ("warmth", "initiative"):
                self.assertGreaterEqual(out[key], 0.0)
                self.assertLessEqual(out[key], 1.0)
            self.assertTrue(out["tone"])

    def test_inactive_result_has_reason(self):
        out = rp.evaluate(None)
        self.assertFalse(out["active"])
        self.assertTrue(out["reason"])

    def test_negative_elapsed_is_clamped(self):
        out = rp.evaluate(EVENT, elapsed_seconds=-500, relationship=CALM)
        self.assertEqual(out["elapsed"], 0.0)
        self.assertEqual(out["stage"], "cold")

    def test_reason_present_for_all_stages(self):
        for elapsed in (0, gates()["state"], gates()["record"],
                        gates()["page"] + 1):
            out = rp.evaluate(EVENT, elapsed_seconds=elapsed,
                              relationship=CALM)
            self.assertTrue(out["reason"])

    def test_evaluate_accepts_non_dict(self):
        for value in (None, "x", 3, []):
            out = rp.evaluate(value)
            self.assertFalse(out["active"])


if __name__ == "__main__":
    unittest.main()
