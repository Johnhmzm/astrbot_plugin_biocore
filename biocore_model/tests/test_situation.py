# -*- coding: utf-8 -*-
import unittest

from biocore_model import situation

NOW = 1_700_000_000


def _history(*rows):
    return [{"role": role, "content": text, "ts": ts} for role, text, ts in rows]


class SituationTest(unittest.TestCase):
    def test_challenge_from_probe_number(self):
        out = situation.summarize(
            history=_history(("user", "这句话什么意思？", NOW - 60)),
            core_state={"v": -0.5, "stress": 0.7,
                        "labels": {"emotion": "anger"}},
            relationship={"state": {"trust": 0.5, "conflict": 0.2,
                                    "closeness": 0.5}},
            situation={"challenge": 0.8},
            now=NOW)
        self.assertTrue(out.startswith("局面："))
        self.assertIn("质问你", out)
        self.assertIn("语气不满", out)
        self.assertIn("关系：", out)
        self.assertLessEqual(len(out.splitlines()), 3)

    def test_praise_from_probe_number(self):
        out = situation.summarize(
            history=[{"role": "user", "content": "今天多亏你了"}],
            relationship={"state": {"closeness": 0.72, "trust": 0.7,
                                    "conflict": 0.05}},
            situation={"praise": 0.75},
            now=NOW)
        self.assertIn("夸你", out)
        self.assertIn("亲近", out)
        self.assertIn("信任高", out)

    def test_hurt_from_probe_number(self):
        out = situation.summarize(
            history=[{"role": "user", "content": "随便你"}],
            situation={"hurt": 0.7},
            now=NOW)
        self.assertIn("火气", out)

    def test_weak_signals_keep_neutral_line(self):
        out = situation.summarize(
            history=[{"role": "user", "content": "今天天气不错"}],
            situation={"challenge": 0.2, "praise": 0.3, "hurt": 0.1},
            now=NOW)
        self.assertIn("日常闲聊", out)

    def test_no_word_scanning_without_probe(self):
        # the old keyword tables are gone: text alone never picks a scene
        out = situation.summarize(
            history=[{"role": "user", "content": "你凭什么骗我？"}] +
                    [{"role": "user", "content": "你真厉害，谢谢你"}],
            now=NOW)
        self.assertIn("日常闲聊", out)
        self.assertNotIn("质问你", out)
        self.assertNotIn("夸你", out)

    def test_unanswered_proactive_messages(self):
        out = situation.summarize(
            history=_history(
                ("user", "在吗", NOW - 120),
                ("assistant", "在的", NOW - 100),
                ("assistant", "看到回我一下", NOW - 80),
                ("assistant", "我先睡了", NOW - 60)),
            now=NOW)
        self.assertIn("主动发了 3 条", out)
        self.assertIn("还没回", out)

    def test_long_silence(self):
        out = situation.summarize(
            history=_history(("user", "晚安", NOW - 8 * 3600)), now=NOW)
        self.assertIn("8 小时", out)
        self.assertIn("没说话", out)

    def test_silence_not_triggered_recently(self):
        out = situation.summarize(
            history=_history(("user", "刚到家", NOW - 300)), now=NOW)
        self.assertNotIn("没说话", out)
        self.assertIn("最近话题", out)

    def test_relationship_tension(self):
        out = situation.summarize(
            history=[{"role": "user", "content": "嗯"}],
            relationship={"state": {"conflict": 0.6, "trust": 0.3,
                                    "closeness": 0.6}},
            now=NOW)
        self.assertIn("紧张", out)
        self.assertIn("信任偏低", out)

    def test_three_line_budget_and_no_overflow(self):
        out = situation.summarize(
            history=_history(("user", "你为什么骗我？", NOW - 9 * 3600)),
            core_state={"v": -0.6, "stress": 0.9,
                        "labels": {"emotion": "anger"}},
            relationship={"state": {"conflict": 0.7, "trust": 0.2,
                                    "closeness": 0.8}},
            situation={"challenge": 0.9, "hurt": 0.6},
            now=NOW)
        lines = out.splitlines()
        self.assertLessEqual(len(lines), 3)
        self.assertGreaterEqual(len(lines), 2)
        self.assertLessEqual(len(out), situation.MAX_CHARS)
        self.assertTrue(all(line.strip() for line in lines))

    def test_empty_inputs(self):
        self.assertEqual(situation.summarize(), "")
        self.assertEqual(situation.summarize(None, None, None, None, None, None),
                         "")

    def test_tolerant_history_shapes(self):
        out = situation.summarize(
            history=["在吗", ("user", "早"), {"text": "吃了吗"}], now=NOW)
        self.assertIn("局面：", out)

    def test_events_clock_fallback(self):
        out = situation.summarize(
            history=[],
            events=[{"ts": NOW - 10 * 3600, "event": "上次聊天"}],
            now=NOW)
        self.assertIn("10 小时", out)
        self.assertIn("没说话", out)

    def test_malformed_situation_values_are_safe(self):
        out = situation.summarize(
            history=[{"role": "user", "content": "在吗"}],
            situation={"challenge": "高", "praise": None, "hurt": 2.0},
            now=NOW)
        self.assertIn("局面：", out)
        self.assertIn("火气", out)  # hurt clamped to 1.0
        values = situation.situation_values({"challenge": -1, "praise": 3})
        self.assertEqual(values["challenge"], 0.0)
        self.assertEqual(values["praise"], 1.0)


if __name__ == "__main__":
    unittest.main()
