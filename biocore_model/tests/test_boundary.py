# -*- coding: utf-8 -*-
"""task-158 底线单测：判定、多类底线、关系调制、关闭、交接修复。

只依赖 biocore_model.boundary 的纯函数；不导入 main.py。
"""
import unittest

from biocore_model import boundary as bd

CALM = {"closeness": 0.5, "trust": 0.5, "conflict": 0.0}
CLOSE = {"closeness": 0.9, "trust": 0.9, "conflict": 0.0}


class ContractTest(unittest.TestCase):
    def test_result_keys(self):
        out = bd.judge("你就是个工具", CALM)
        for key in ("enabled", "crossed", "kind", "severity", "threshold",
                    "violations", "relationship", "handoff", "reason"):
            self.assertIn(key, out)

    def test_relationship_echo_bounded(self):
        out = bd.judge("你就是个工具", {"closeness": 5, "trust": -2, "conflict": 9})
        rel = out["relationship"]
        self.assertEqual(rel["closeness"], 1.0)
        self.assertEqual(rel["trust"], 0.0)
        self.assertEqual(rel["conflict"], 1.0)

    def test_severity_and_threshold_bounded(self):
        for text in ("你就是个工具", "你算什么东西", "别烦我"):
            out = bd.judge(text, CLOSE)
            self.assertGreaterEqual(out["severity"], 0.0)
            self.assertLessEqual(out["severity"], 1.0)
            self.assertGreaterEqual(out["threshold"], 0.0)
            self.assertLessEqual(out["threshold"], 1.0)


class JudgmentTest(unittest.TestCase):
    def test_neutral_message_not_crossed(self):
        out = bd.judge("今天下雨了，要不要带伞", CALM)
        self.assertFalse(out["crossed"])
        self.assertEqual(out["kind"], "")
        self.assertEqual(out["severity"], 0.0)
        self.assertIsNone(out["handoff"])

    def test_empty_and_odd_input_safe(self):
        for text in (None, "", 0, [], {}, "   "):
            out = bd.judge(text)
            self.assertFalse(out["crossed"])
            self.assertEqual(out["severity"], 0.0)

    def test_kind_set_is_her_own_lines(self):
        self.assertEqual(bd.KINDS, ("tool", "old_score", "lie", "contempt"))
        self.assertNotIn("safety", bd.KINDS)


class MultiLineTest(unittest.TestCase):
    def test_tool_line(self):
        out = bd.judge("你就是个工具，想用就用", CALM)
        self.assertTrue(out["crossed"])
        self.assertEqual(out["kind"], "tool")

    def test_old_score_line(self):
        out = bd.judge("你总是这样，又翻旧账", CALM)
        self.assertTrue(out["crossed"])
        self.assertEqual(out["kind"], "old_score")

    def test_lie_line(self):
        out = bd.judge("我骗你的，那天根本没去", CALM)
        self.assertTrue(out["crossed"])
        self.assertEqual(out["kind"], "lie")

    def test_contempt_line(self):
        out = bd.judge("你算什么东西，也配问我", CALM)
        self.assertTrue(out["crossed"])
        self.assertEqual(out["kind"], "contempt")

    def test_two_lines_listed_strongest_first(self):
        out = bd.judge("你算什么东西，还翻旧账", CALM)
        kinds = [row["kind"] for row in out["violations"]]
        self.assertIn("contempt", kinds)
        self.assertIn("old_score", kinds)
        self.assertEqual(kinds[0], "contempt")
        self.assertGreaterEqual(out["violations"][0]["severity"],
                                out["violations"][1]["severity"])
        self.assertEqual(out["kind"], "contempt")

    def test_violation_rows_carry_reason(self):
        out = bd.judge("你就是个工具，还骗我", CALM)
        for row in out["violations"]:
            self.assertTrue(row["reason"])

    def test_boundary_requests_are_not_crossings(self):
        for text in ("别骗我", "不要把我当工具", "别翻旧账了好吗",
                     "我不该拿你当工具"):
            self.assertFalse(bd.judge(text, CALM)["crossed"], text)


class ModulationTest(unittest.TestCase):
    def test_closeness_makes_tool_line_hurt_more(self):
        far = bd.judge("你就是个工具", {"closeness": 0.1})
        near = bd.judge("你就是个工具", {"closeness": 0.9})
        self.assertTrue(near["crossed"])
        self.assertGreater(near["severity"], far["severity"])

    def test_trust_makes_lies_cross_the_line(self):
        low = bd.judge("我骗你的", {"trust": 0.0, "closeness": 0.0})
        high = bd.judge("我骗你的", {"trust": 0.9, "closeness": 0.9})
        self.assertFalse(low["crossed"])
        self.assertTrue(high["crossed"])

    def test_conflict_lowers_tolerance(self):
        calm = bd.judge("别烦我", {"conflict": 0.0})
        tense = bd.judge("别烦我", {"conflict": 0.9})
        self.assertFalse(calm["crossed"])
        self.assertTrue(tense["crossed"])
        self.assertLess(tense["threshold"], calm["threshold"])

    def test_conflict_raises_contempt_severity(self):
        calm = bd.judge("你看不起我", {"conflict": 0.0})
        tense = bd.judge("你看不起我", {"conflict": 0.9})
        self.assertTrue(calm["crossed"])
        self.assertGreater(tense["severity"], calm["severity"])


class HandoffTest(unittest.TestCase):
    def test_handoff_points_to_repair_flow(self):
        out = bd.judge("你就是个工具", CALM)
        handoff = out["handoff"]
        self.assertIsInstance(handoff, dict)
        self.assertEqual(handoff["to"], "repair_after_boundary")
        self.assertEqual(handoff["kind"], out["kind"])
        self.assertEqual(handoff["severity"], out["severity"])
        self.assertEqual(handoff["stage"], "cold")

    def test_no_handoff_without_crossing(self):
        self.assertIsNone(bd.judge("晚安", CALM)["handoff"])

    def test_crossed_helper(self):
        self.assertTrue(bd.crossed(bd.judge("你就是个工具", CALM)))
        self.assertFalse(bd.crossed(bd.judge("晚安", CALM)))
        self.assertFalse(bd.crossed(None))


class SwitchTest(unittest.TestCase):
    def test_disabled_never_crosses(self):
        out = bd.judge("你就是个工具", CALM, flags={"enabled": False})
        self.assertFalse(out["enabled"])
        self.assertFalse(out["crossed"])
        self.assertIsNone(out["handoff"])
        self.assertIn("关闭", out["reason"])

    def test_custom_threshold_suppresses(self):
        out = bd.judge("你就是个工具", CALM, flags={"threshold": 0.99})
        self.assertFalse(out["crossed"])

    def test_custom_threshold_opens(self):
        out = bd.judge("别烦我", CALM, flags={"threshold": 0.5})
        self.assertTrue(out["crossed"])

    def test_reason_always_present(self):
        self.assertTrue(bd.judge("晚安", CALM)["reason"])
        self.assertTrue(bd.judge("你就是个工具", CALM)["reason"])
        self.assertTrue(bd.judge("你就是个工具", CALM,
                                 flags={"enabled": False})["reason"])


class PayloadTest(unittest.TestCase):
    def test_payload_bounded(self):
        out = bd.payload(bd.judge("你算什么东西", CLOSE))
        self.assertEqual(out["kind"], "contempt")
        self.assertTrue(out["crossed"])
        self.assertGreaterEqual(out["severity"], 0.0)
        self.assertLessEqual(out["severity"], 1.0)
        self.assertLessEqual(len(out["violations"]), 4)

    def test_payload_handles_none(self):
        out = bd.payload(None)
        self.assertFalse(out["crossed"])
        self.assertEqual(out["severity"], 0.0)


if __name__ == "__main__":
    unittest.main()
