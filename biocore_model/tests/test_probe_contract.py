# -*- coding: utf-8 -*-
import json
import unittest

from biocore_model import appraisal


def _raw(**extra):
    data = {"dims": {"goal": 0.2, "blame": 0.1, "control": 0.5,
                     "certainty": 0.5, "novelty": 0.2, "involve": 0.6,
                     "hit": 0.1},
            "why": "test", "c": 0.8}
    data.update(extra)
    return json.dumps(data, ensure_ascii=False)


class ProbeContractTest(unittest.TestCase):
    def test_prompt_declares_situation_and_fact(self):
        prompt = appraisal.build_prompt("在吗", "在的")
        for token in ("situation", "challenge", "praise", "hurt", "fact",
                      "≤20 字"):
            self.assertIn(token, prompt)
        self.assertIn("对方：在吗", prompt)
        self.assertIn("你：在的", prompt)

    def test_parse_situation_numbers(self):
        out = appraisal.parse(_raw(situation={"challenge": 0.6,
                                           "praise": 0.1, "hurt": 0.0}))
        self.assertEqual(out["situation"]["challenge"], 0.6)
        self.assertEqual(out["situation"]["praise"], 0.1)
        self.assertEqual(out["situation"]["hurt"], 0.0)
        self.assertEqual(out["dims"]["goal"], 0.2)

    def test_parse_clamps_situation_range(self):
        out = appraisal.parse(_raw(situation={"challenge": 2.0,
                                           "praise": -1.0, "hurt": 0.4}))
        self.assertEqual(out["situation"]["challenge"], 1.0)
        self.assertEqual(out["situation"]["praise"], 0.0)
        self.assertEqual(out["situation"]["hurt"], 0.4)

    def test_parse_fact_short_kept(self):
        out = appraisal.parse(_raw(fact="他姓王"))
        self.assertEqual(out["fact"], "他姓王")

    def test_parse_fact_truncated_to_limit(self):
        out = appraisal.parse(_raw(fact="他" * 40))
        self.assertEqual(len(out["fact"]), appraisal.FACT_MAX_CHARS)

    def test_parse_missing_optional_fields(self):
        out = appraisal.parse(_raw())
        self.assertEqual(out["situation"], {})
        self.assertEqual(out["fact"], "")

    def test_parse_low_confidence_drops_everything(self):
        raw = json.dumps({"dims": {"goal": 0.5}, "c": 0.2,
                          "situation": {"challenge": 0.9},
                          "fact": "他姓王"}, ensure_ascii=False)
        self.assertEqual(appraisal.parse(raw), {})

    def test_parse_malformed_situation_is_safe(self):
        out = appraisal.parse(_raw(situation={"challenge": "高",
                                           "praise": None, "hurt": 0.3}))
        self.assertNotIn("challenge", out["situation"])
        self.assertNotIn("praise", out["situation"])
        self.assertEqual(out["situation"]["hurt"], 0.3)
        out2 = appraisal.parse(_raw(situation=["challenge"]))
        self.assertEqual(out2["situation"], {})


if __name__ == "__main__":
    unittest.main()
