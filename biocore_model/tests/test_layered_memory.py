# -*- coding: utf-8 -*-
import unittest

from biocore_model import layered_memory as lm

NOW = 1_700_000_000
DAY = 86400


def _entry(eid, text, ts=0, importance=0.5, role="user", **extra):
    data = {"id": eid, "text": text, "role": role, "ts": ts,
            "importance": importance}
    data.update(extra)
    return data


def _resident(eid, text, ts=0, importance=0.5, **extra):
    return _entry(eid, text, ts, importance, tags=["resident"], **extra)


def _section(text, header):
    out, inside = [], False
    for line in text.splitlines():
        if line.strip() in ("常驻事实：", "相关事件："):
            inside = line.strip() == header
            continue
        if inside:
            out.append(line)
    return out


class LayeredMemoryTest(unittest.TestCase):
    def test_classification_uses_only_tags_kind_and_pin(self):
        # no keyword heuristics: a factual sentence without a tag stays retrieval
        plain = _entry("x1", "我姓王，我妈住院了")
        self.assertEqual(lm.classify(plain), "retrieval")
        tagged = _entry("x2", "我姓王", tags=["resident"])
        self.assertEqual(lm.classify(tagged), "resident")
        kinded = _entry("x3", "我姓王", kind="profile")
        self.assertEqual(lm.classify(kinded), "resident")
        pinned = _entry("x4", "我姓王", pin=True)
        self.assertEqual(lm.classify(pinned), "resident")
        self.assertEqual(lm.classify(_entry("x5", "我姓王", deleted=True)), "")

    def test_resident_facts_plus_capped_retrieval(self):
        entries = [
            _resident("f1", "小夏，昵称夏夏", NOW - 5 * DAY, 0.8),
            _resident("f2", "不喜欢下雨", NOW - 4 * DAY, 0.7),
            _entry("e1", "周末打算去海边", NOW - 3 * DAY),
            _entry("e2", "周五陪小夏体检", NOW - 2 * DAY),
            _entry("e3", "项目报告下周五截止", NOW - DAY),
        ]
        out = lm.render(entries, recalled_ids=["e1", "e2", "e3"], now=NOW)
        self.assertIn("[分层记忆]", out)
        self.assertIn("夏夏", out)
        self.assertIn("海边", out)
        self.assertEqual(len(_section(out, "相关事件：")), 2)

    def test_retrieval_limit_is_configurable_and_clamped(self):
        entries = [_resident("f1", "昵称小七", NOW, 0.9)]
        entries += [_entry("e%d" % i, "事件 %d" % i, NOW - i * DAY)
                    for i in range(1, 7)]
        one = lm.render(entries, retrieval_limit=1, now=NOW)
        self.assertEqual(len(_section(one, "相关事件：")), 1)
        zero = lm.render(entries, retrieval_limit=0, now=NOW)
        self.assertNotIn("相关事件：", zero)
        self.assertIn("小七", zero)
        huge = lm.render(entries, retrieval_limit=99, now=NOW)
        self.assertEqual(len(_section(huge, "相关事件：")),
                         lm.HARD_RETRIEVAL_LIMIT)

    def test_resident_facts_survive_three_days(self):
        entries = [
            _resident("f1", "叫他夏夏", NOW - 10 * DAY, 0.9),
            _resident("f2", "最怕打雷", NOW - 9 * DAY, 0.6),
            _entry("e1", "上周去了海边", NOW - 3 * DAY),
        ]
        for day in range(3):
            out = lm.render(entries, recalled_ids=["e1"],
                            now=NOW + day * DAY)
            self.assertIn("夏夏", out)
            self.assertIn("打雷", out)
            self.assertIn("常驻事实：", out)

    def test_recalled_order_is_respected(self):
        entries = [_entry("e1", "第一个事件", NOW - DAY),
                   _entry("e2", "第二个事件", NOW - 2 * DAY),
                   _entry("e3", "第三个事件", NOW - 3 * DAY)]
        out = lm.render(entries, recalled_ids=["e3", "e1", "e2"], now=NOW)
        rows = _section(out, "相关事件：")
        self.assertIn("第三个事件", rows[0])
        self.assertIn("第一个事件", rows[1])

    def test_resident_entries_never_repeat_in_retrieval(self):
        entries = [_resident("f1", "叫他阿夏", NOW, 0.9),
                   _entry("e1", "昨天一起吃了火锅", NOW - DAY)]
        out = lm.render(entries, recalled_ids=["f1", "e1"], now=NOW)
        rows = _section(out, "相关事件：")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("阿夏", rows[0])

    def test_duplicate_facts_collapse(self):
        entries = [_resident("f1", "昵称是夏夏", NOW, 0.8),
                   _resident("f2", "昵称是夏夏！", NOW - DAY, 0.7)]
        out = lm.render(entries, now=NOW)
        self.assertEqual(out.count("夏夏"), 1)

    def test_deleted_and_summarized_entries_are_skipped(self):
        entries = [_resident("f1", "叫小夏", NOW, 0.9, deleted=True),
                   _resident("f2", "喜欢下雨", NOW, 0.9, summarized=True),
                   _resident("f3", "长期摘要", NOW, 0.9, role="summary")]
        self.assertEqual(lm.render(entries, now=NOW), "")

    def test_pinned_event_becomes_resident(self):
        entries = [_entry("e1", "明天下午三点开会", NOW - DAY, 0.4, pin=True)]
        out = lm.render(entries, now=NOW)
        self.assertIn("常驻事实：", out)
        self.assertIn("三点开会", out)
        self.assertNotIn("相关事件：", out)

    def test_empty_and_malformed_inputs(self):
        self.assertEqual(lm.render(None), "")
        self.assertEqual(lm.render([]), "")
        self.assertEqual(lm.render([None, "x", {}, {"text": "  "}]), "")

    def test_render_is_bounded_and_trims(self):
        long_fact = "很长的偏好描述" * 60
        entries = [_resident("f1", long_fact, NOW, 0.9),
                   _entry("e1", "事件" * 80, NOW - DAY)]
        out = lm.render(entries, now=NOW)
        self.assertLessEqual(len(out), lm.MAX_CHARS)
        self.assertIn("…", out)
        rows = _section(out, "相关事件：")
        self.assertEqual(len(rows), 1)
        self.assertLessEqual(len(rows[0]), lm.EVENT_TRIM + 8)

    def test_fact_entry_validation(self):
        self.assertIsNone(lm.fact_entry("", 0.9))
        self.assertIsNone(lm.fact_entry("他姓王", 0.3))
        candidate = lm.fact_entry("他姓王", 0.8)
        self.assertEqual(candidate["text"], "他姓王")
        self.assertEqual(candidate["tags"], ["resident"])
        self.assertEqual(candidate["memory_source"], "probe_fact")
        long_fact = "他" * 40
        self.assertEqual(len(lm.fact_entry(long_fact, 0.9)["text"]),
                         lm.FACT_MAX_CHARS)

    def test_duplicate_resident_detection(self):
        entries = [_resident("f1", "他姓王，住在杭州")]
        self.assertTrue(lm.duplicate_resident("他姓王，住在杭州", entries))
        self.assertTrue(lm.duplicate_resident("他姓王住在杭州啊", entries))
        self.assertFalse(lm.duplicate_resident("他喜欢打游戏", entries))
        # a non-resident entry with the same text is not a resident duplicate
        self.assertFalse(lm.duplicate_resident(
            "他姓王，住在杭州", [_entry("e1", "他姓王，住在杭州")]))

    def test_should_write_fact_once_per_message(self):
        entries = [_resident("f1", "他姓王")]
        written = {}
        self.assertTrue(lm.should_write_fact("他喜欢打游戏", 0.8, entries,
                                             written, "msg-1"))
        written["msg-1"] = 1.0
        self.assertFalse(lm.should_write_fact("他喜欢打游戏", 0.8, entries,
                                              written, "msg-1"))
        self.assertFalse(lm.should_write_fact("他姓王", 0.8, entries, {},
                                              "msg-2"))
        self.assertFalse(lm.should_write_fact("他喜欢打游戏", 0.4, entries, {},
                                              "msg-3"))
        self.assertTrue(lm.should_write_fact("他喜欢打游戏", 0.8, entries, {},
                                             "msg-3"))


if __name__ == "__main__":
    unittest.main()
