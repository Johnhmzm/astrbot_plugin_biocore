# -*- coding: utf-8 -*-
import unittest
from biocore_memory.event import claims as CL


class SourceConfidenceTest(unittest.TestCase):
    def test_direct_beats_inferred(self):
        _o, cs = CL.parse_claims(
            '{"claims": [{"subject": "叶楠", "attr": "生日", "value": "八月十八",'
            ' "status": "current", "source": "direct"},'
            '{"subject": "叶楠", "attr": "生日", "value": "八月十六",'
            ' "status": "coexist", "source": "inferred"}]}')
        self.assertEqual(len(cs), 2)
        self.assertGreater(cs[0]["confidence"], cs[1]["confidence"])

    def test_unknown_source_is_low_confidence(self):
        _o, cs = CL.parse_claims(
            '{"claims": [{"subject": "A", "attr": "B", "value": "C",'
            ' "status": "current", "source": "???"}]}')
        self.assertEqual(cs[0]["source"], "unknown")
        self.assertLess(cs[0]["confidence"], CL.LOW_CONFIDENCE)

    def test_conflict_caps_confidence(self):
        table = CL.merge_claims([
            {"subject": "A", "attr": "B", "value": "1", "status": "current",
             "source": "direct", "confidence": 0.82, "turn": 1},
            {"subject": "A", "attr": "B", "value": "2", "status": "coexist",
             "source": "inferred", "confidence": 0.45, "turn": 2},
        ])
        slot = table["A·B"]
        self.assertLessEqual(slot["confidence"], 0.55)
        self.assertEqual(slot["status"], "coexist")

    def test_render_flags_uncertainty(self):
        table = CL.merge_claims([
            {"subject": "A", "attr": "B", "value": "1", "status": "current",
             "source": "inferred", "confidence": 0.45, "turn": 1},
        ])
        lines = CL.render_claims(table)
        self.assertEqual(len(lines), 1)
        self.assertIn("需向用户确认", lines[0])

    def test_render_quiet_when_confident(self):
        table = CL.merge_claims([
            {"subject": "A", "attr": "B", "value": "1", "status": "current",
             "source": "direct", "confidence": 0.82, "turn": 1},
        ])
        self.assertNotIn("需向用户确认", CL.render_claims(table)[0])


class ValueCanonicalTest(unittest.TestCase):
    def test_annotation_is_ignored(self):
        self.assertEqual(CL.value_key("7月12日（公历）"), CL.value_key("7月12日"))

    def test_iso_and_chinese_month_agree(self):
        self.assertEqual(CL.value_key("2026-05-25"), CL.value_key("5月25日"))

    def test_chinese_numeral_month(self):
        self.assertEqual(CL.value_key("八月十八号"), "08-18")


class MergeSemanticsTest(unittest.TestCase):
    def test_repetition_raises_confidence_not_conflict(self):
        table = CL.merge_claims([
            {"subject": "用户", "attr": "生日", "value": "7月12日", "status": "current",
             "source": "direct", "confidence": 0.82, "turn": 1},
            {"subject": "用户", "attr": "生日", "value": "7月12日（公历）", "status": "current",
             "source": "direct", "confidence": 0.82, "turn": 2},
        ])
        slot = table["用户·生日"]
        self.assertEqual(slot["status"], "current")
        self.assertEqual(len(slot["values"]), 1)
        self.assertGreater(slot["confidence"], 0.82)

    def test_conflict_capped_low(self):
        table = CL.merge_claims([
            {"subject": "叶楠", "attr": "生日", "value": "八月十六", "status": "current",
             "source": "direct", "confidence": 0.82, "turn": 1},
            {"subject": "叶楠", "attr": "生日", "value": "八月十八", "status": "current",
             "source": "direct", "confidence": 0.82, "turn": 2},
        ])
        slot = table["叶楠·生日"]
        self.assertEqual(slot["status"], "coexist")
        older = [v for v in slot["values"] if v["value"] == "八月十六"][0]
        newer = [v for v in slot["values"] if v["value"] == "八月十八"][0]
        self.assertLess(older["confidence"], newer["confidence"])

    def test_age_decays_slightly(self):
        fresh = CL.merge_claims([{"subject": "A", "attr": "B", "value": "1",
                                  "source": "direct", "confidence": 0.82, "turn": 100}])
        old = CL.merge_claims([{"subject": "A", "attr": "B", "value": "1",
                                "source": "direct", "confidence": 0.82, "turn": 1}], now=900)
        self.assertGreater(fresh["A·B"]["confidence"], old["A·B"]["confidence"])
        self.assertLessEqual(fresh["A·B"]["confidence"] - old["A·B"]["confidence"], 0.16)


class AuditTest(unittest.TestCase):
    def _table(self, rows):
        return CL.merge_claims(rows)

    def test_over_merge_detected(self):
        rows = [{"subject": "S", "attr": "A", "value": str(i), "source": "direct",
                 "confidence": 0.82, "turn": i} for i in range(1, 7)]
        table = self._table(rows)
        self.assertEqual(CL.audit_table(table)["over_merged"], [("S·A", 6)])
        CL.trim_values(table)
        self.assertEqual(len(table["S·A"]["values"]), CL.MAX_VALUES_PER_KEY)
        self.assertEqual(table["S·A"]["trimmed"], 2)

    def test_value_used_as_attr_detected(self):
        rows = [
            {"subject": "A", "attr": "生日", "value": "生日", "source": "direct",
             "confidence": 0.82, "turn": 1},
            {"subject": "B", "attr": "生日", "value": "八月十八", "source": "direct",
             "confidence": 0.82, "turn": 2},
        ]
        table = self._table(rows)
        flagged = [v for k, v in CL.audit_table(table)["value_as_attr"]]
        self.assertIn("生日", flagged)

    def test_clean_table_has_no_warnings(self):
        rows = [{"subject": "叶楠", "attr": "生日", "value": "八月十八", "source": "direct",
                 "confidence": 0.82, "turn": 1}]
        audit = CL.audit_table(self._table(rows))
        self.assertEqual(audit["over_merged"], [])
        self.assertEqual(audit["value_as_attr"], [])


class BudgetAndPrivateTest(unittest.TestCase):
    def test_density_ranks_business_above_chitchat(self):
        self.assertGreater(CL.density([1, 2, 3], 200), CL.density([1], 400))

    def test_budget_collapses_low_density(self):
        ev = {"text": "闲聊" * 300, "claims": [{"value": "x"}]}
        cap, _d = CL.budget_hint(ev)
        self.assertEqual(cap, 0)

    def test_budget_keeps_five_without_claims(self):
        cap, _d = CL.budget_hint({"text": "abc", "claims": []})
        self.assertEqual(cap, 5)

    def test_private_lines_render(self):
        table = CL.merge_claims([{"subject": "A", "attr": "B", "value": "秘密",
                                  "status": "private", "source": "direct",
                                  "confidence": 0.82, "turn": 1}])
        lines = CL.private_lines(table)
        self.assertEqual(len(lines), 1)
        self.assertIn("不可外传", lines[0])

    def test_threads_group_across_events(self):
        table = CL.merge_claims([
            {"subject": "师傅", "attr": "报价", "value": "已发来", "status": "current",
             "source": "direct", "confidence": 0.82, "turn": 183, "thread": "门口灯箱"},
            {"subject": "灯箱", "attr": "进度", "value": "只量了尺寸", "status": "current",
             "source": "direct", "confidence": 0.82, "turn": 180, "thread": "门口灯箱"},
        ])
        th = CL.threads_of(table)
        self.assertEqual(len(th["门口灯箱"]), 2)


if __name__ == "__main__":
    unittest.main()
