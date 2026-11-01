# -*- coding: utf-8 -*-
"""Inline state tag: instruction text + tolerant parsing."""
import json
import unittest

from biocore_model import state_tag as st


class InstructionTest(unittest.TestCase):
    def test_contains_example_and_fields(self):
        text = st.instruction()
        self.assertIn('"dims"', text)
        self.assertIn('"situation"', text)
        self.assertIn('"why"', text)
        self.assertIn('"c"', text)
        self.assertLess(len(text), 900)


class ParseTest(unittest.TestCase):
    def test_plain_line(self):
        out = st.parse('好。\n{"dims":{"goal":-0.5,"blame":0.8,"hit":0.7},"why":"被指责","c":0.8}')
        self.assertEqual(out["dims"]["blame"], 0.8)
        self.assertEqual(out["source"], "inline_tag")
        self.assertAlmostEqual(out["confidence"], 0.8)

    def test_code_fence(self):
        out = st.parse('reply\n```json\n{"dims":{"hit":0.6},"c":0.7}\n```')
        self.assertEqual(out["dims"]["hit"], 0.6)

    def test_situation_and_fact(self):
        out = st.parse('{"dims":{"goal":0.2},"situation":{"praise":0.9},"fact":"他姓王","c":0.9}')
        self.assertEqual(out["situation"]["praise"], 0.9)
        self.assertEqual(out["fact"], "他姓王")

    def test_clamps_out_of_range(self):
        out = st.parse('{"dims":{"blame":5,"hit":-3},"c":2}')
        self.assertEqual(out["dims"]["blame"], 1.0)
        self.assertEqual(out["dims"]["hit"], 0.0)
        self.assertEqual(out["confidence"], 1.0)

    def test_missing_returns_empty(self):
        self.assertEqual(st.parse("就是普通回复"), {})
        self.assertEqual(st.parse(""), {})
        self.assertEqual(st.parse('{"dims":{}}'), {})

    def test_bad_json_ignored(self):
        self.assertEqual(st.parse('{"dims": {broken'), {})

    def test_garbage_values_ignored(self):
        out = st.parse('{"dims":{"goal":"abc","blame":0.4},"c":"x"}')
        self.assertNotIn("goal", out["dims"])
        self.assertEqual(out["dims"]["blame"], 0.4)

    def test_fact_truncated(self):
        out = st.parse('{"dims":{"hit":0.2},"fact":"' + "字" * 40 + '","c":0.6}')
        self.assertEqual(len(out["fact"]), 20)


class EdgeCaseTest(unittest.TestCase):
    def test_entities_only_tag_is_parsed(self):
        raw = json.dumps({"dims": {}, "entities": [{"name": "小夏",
                                                    "type": "人物"}],
                          "relations": [{"src": "小夏", "rel": "likes",
                                         "dst": "奶茶"}]},
                         ensure_ascii=False)
        out = st.parse("好。\n" + raw)
        self.assertTrue(out)
        self.assertEqual(out["entities"][0]["name"], "小夏")
        self.assertEqual(out["relations"][0]["rel"], "likes")

    def test_truncated_tag_is_stripped(self):
        self.assertEqual(st.strip('好的 {"dims": {"goal": 0.3'), "好的")
        self.assertEqual(st.strip('嗯 {"dims"'), "嗯")
        self.assertEqual(st.strip("就是普通回复"), "就是普通回复")


class StripTest(unittest.TestCase):
    def test_removes_tag(self):
        self.assertEqual(st.strip('好。\n{"dims":{"hit":0.3},"c":0.5}'), "好。")

    def test_keeps_plain_text(self):
        self.assertEqual(st.strip("就是普通回复"), "就是普通回复")


if __name__ == "__main__":
    unittest.main()
