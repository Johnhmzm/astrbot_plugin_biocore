# -*- coding: utf-8 -*-
import datetime
import unittest

from biocore_model import commitment_extractor as ce
from biocore_model import prospective

NOW_DT = datetime.datetime(2026, 11, 2, 22, 25)  # Monday
NOW = NOW_DT.timestamp()


def stamp(year, month, day, hour=9, minute=0):
    return datetime.datetime(year, month, day, hour, minute).timestamp()


class CommitmentTimeTest(unittest.TestCase):
    def test_relative_tomorrow(self):
        out = ce.extract("明天提醒我交报告", now=NOW)
        self.assertTrue(out["has_commitment"])
        self.assertAlmostEqual(out["due_ts"], stamp(2026, 11, 3))
        self.assertEqual(out["surface_phrase"], "明天")
        self.assertIn("交报告", out["what"])

    def test_relative_day_after_tomorrow(self):
        out = ce.extract("后天体检", now=NOW)
        self.assertAlmostEqual(out["due_ts"], stamp(2026, 11, 4))

    def test_relative_three_days_out(self):
        out = ce.extract("大后天交报告", now=NOW)
        self.assertAlmostEqual(out["due_ts"], stamp(2026, 11, 5))

    def test_relative_day_with_afternoon_time(self):
        out = ce.extract("我明天下午三点开会", now=NOW)
        self.assertAlmostEqual(out["due_ts"], stamp(2026, 11, 3, 15, 0))
        self.assertEqual(out["surface_phrase"], "明天下午三点")
        self.assertEqual(out["what"], "开会")

    def test_relative_day_with_evening_digits(self):
        out = ce.extract("明天晚上8点开会", now=NOW)
        self.assertAlmostEqual(out["due_ts"], stamp(2026, 11, 3, 20, 0))

    def test_weekday_next_week(self):
        out = ce.extract("下周三开会", now=NOW)
        self.assertAlmostEqual(out["due_ts"], stamp(2026, 11, 11))

    def test_weekday_this_week(self):
        out = ce.extract("本周五交报告", now=NOW)
        self.assertAlmostEqual(out["due_ts"], stamp(2026, 11, 6))

    def test_weekday_bare_is_next_occurrence(self):
        out = ce.extract("周五体检", now=NOW)
        self.assertAlmostEqual(out["due_ts"], stamp(2026, 11, 6))

    def test_absolute_date_this_year(self):
        out = ce.extract("11月5日交报告", now=NOW)
        self.assertAlmostEqual(out["due_ts"], stamp(2026, 11, 5))

    def test_absolute_date_already_passed_rolls_to_next_year(self):
        out = ce.extract("3月5日交报告", now=NOW)
        self.assertAlmostEqual(out["due_ts"], stamp(2027, 3, 5))

    def test_bare_clock_rolls_to_tomorrow_when_passed(self):
        out = ce.extract("下午3点开会", now=NOW)
        self.assertAlmostEqual(out["due_ts"], stamp(2026, 11, 3, 15, 0))


class CommitmentBoundaryTest(unittest.TestCase):
    def test_vague_changeday_has_no_due(self):
        out = ce.extract("改天一起吃饭", now=NOW)
        self.assertTrue(out["has_commitment"])
        self.assertIsNone(out["due_ts"])
        self.assertEqual(out["reason"], "vague")
        self.assertLess(out["confidence"], 0.5)

    def test_vague_find_time_has_no_due(self):
        out = ce.extract("找时间聊", now=NOW)
        self.assertTrue(out["has_commitment"])
        self.assertIsNone(out["due_ts"])

    def test_past_relative_is_not_a_commitment(self):
        out = ce.extract("昨天开会到很晚", now=NOW)
        self.assertFalse(out["has_commitment"])
        self.assertEqual(out["reason"], "past")

    def test_past_weekday_is_not_a_commitment(self):
        out = ce.extract("上周三开会", now=NOW)
        self.assertFalse(out["has_commitment"])
        self.assertEqual(out["reason"], "past")

    def test_no_time_no_commitment(self):
        out = ce.extract("今天天气不错", now=NOW)
        self.assertFalse(out["has_commitment"])
        self.assertEqual(out["reason"], "no_intent")

    def test_most_specific_commitment_wins(self):
        out = ce.extract("明天提醒我交报告，下周三下午三点开会", now=NOW)
        self.assertTrue(out["has_commitment"])
        self.assertAlmostEqual(out["due_ts"], stamp(2026, 11, 11, 15, 0))
        self.assertIn("下周三", out["surface_phrase"])
        self.assertEqual(out["what"], "开会")

    def test_confidence_is_bounded(self):
        for text in ("明天提醒我交报告", "下周三开会", "改天吃饭",
                     "今天天气不错"):
            out = ce.extract(text, now=NOW)
            self.assertGreaterEqual(out["confidence"], 0.0)
            self.assertLessEqual(out["confidence"], 1.0)


class CommitmentWhoTest(unittest.TestCase):
    def test_request_to_her_is_her_promise(self):
        out = ce.extract("你明天记得问我体检结果", now=NOW)
        self.assertEqual(out["who"], "her")
        self.assertEqual(out["kind"], "her_promise")
        self.assertIn("体检结果", out["what"])

    def test_first_person_is_his_event(self):
        out = ce.extract("我周五体检", now=NOW)
        self.assertEqual(out["who"], "him")
        self.assertEqual(out["kind"], "his_event")
        self.assertEqual(out["what"], "体检")

    def test_reminder_request_is_her_promise(self):
        out = ce.extract("明天提醒我交报告", now=NOW)
        self.assertEqual(out["who"], "her")


class CommitmentTagsTest(unittest.TestCase):
    def test_structured_due_overrides_text(self):
        due = NOW + 86400
        out = ce.extract("记得那件事", tags={"due_ts": due}, now=NOW)
        self.assertTrue(out["has_commitment"])
        self.assertAlmostEqual(out["due_ts"], due)
        self.assertGreaterEqual(out["confidence"], 0.95)

    def test_structured_time_and_fact(self):
        out = ce.extract("回头弄一下",
                         tags={"time": "明天下午3点", "fact": "弄材料",
                               "entities": ["材料"]},
                         now=NOW)
        self.assertTrue(out["has_commitment"])
        self.assertAlmostEqual(out["due_ts"], stamp(2026, 11, 3, 15, 0))
        self.assertEqual(out["what"], "弄材料")
        self.assertEqual(out["entities"], ["材料"])

    def test_disabled_switch(self):
        for config in (False, {"enabled": False}):
            out = ce.extract("明天提醒我交报告", now=NOW, config=config)
            self.assertFalse(out["enabled"])
            self.assertFalse(out["has_commitment"])
            self.assertEqual(out["reason"], "disabled")

    def test_malformed_inputs_do_not_crash(self):
        for text in (None, 123, "", "   "):
            out = ce.extract(text, now=NOW)
            self.assertIn("has_commitment", out)
            self.assertFalse(out["has_commitment"])
        missing_now = ce.extract("明天开会", now=None)
        self.assertFalse(missing_now["has_commitment"])

    def test_reason_is_always_present(self):
        for text in ("明天开会", "改天吃饭", "昨天开会", "今天天气不错"):
            self.assertTrue(ce.extract(text, now=NOW)["reason"])


class CommitmentProspectiveBridgeTest(unittest.TestCase):
    def test_bridge_builds_prospective_record(self):
        result = ce.extract("你明天记得问我体检结果", now=NOW)
        record = ce.to_prospective(result, now=NOW)
        self.assertIsNotNone(record)
        self.assertEqual(record["kind"], "her_promise")
        self.assertEqual(record["text"], result["what"])
        self.assertAlmostEqual(record["due_ts"], result["due_ts"])
        self.assertEqual(record["status"], "pending")
        self.assertTrue(record["id"])
        self.assertEqual(record["meta"]["surface_phrase"], "明天")

    def test_bridge_rejects_vague(self):
        result = ce.extract("改天一起吃饭", now=NOW)
        self.assertIsNone(ce.to_prospective(result, now=NOW))

    def test_bridge_rejects_no_commitment(self):
        result = ce.extract("今天天气不错", now=NOW)
        self.assertIsNone(ce.to_prospective(result, now=NOW))

    def test_bridge_record_roundtrips_into_prospective_store(self):
        result = ce.extract("明天下午三点开会", now=NOW)
        record = ce.to_prospective(result, now=NOW)
        store, changed = prospective.add([], record)
        self.assertTrue(changed)
        self.assertEqual(len(store), 1)
        due = prospective.due_now(store, record["due_ts"])
        self.assertEqual(len(due), 1)


if __name__ == "__main__":
    unittest.main()
