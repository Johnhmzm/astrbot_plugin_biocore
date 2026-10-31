# -*- coding: utf-8 -*-
"""Numeric schema + legend injection tests."""
import types
import unittest
from pathlib import Path

from biocore_model import expr_template as et
from biocore_model import runtime as rt
from biocore_model import schema

DOC = Path(__file__).resolve().parents[2] / "docs" / "NUMERIC-SCHEMA.md"


class SchemaTest(unittest.TestCase):
    def test_groups_and_fields_present(self):
        names = {field["name"] for field in schema.FIELDS}
        for expected in ("v", "a", "d", "social", "trust", "stress",
                         "self_esteem", "social_pain", "tension", "warmth",
                         "heaviness", "clarity", "belonging", "control",
                         "meaningful_existence", "goal", "blame", "certainty",
                         "novelty", "involve", "hit", "theta", "tau_hours",
                         "cooldown_s", "daily_cap", "storage_s", "retrieval_s",
                         "access_count", "arousal_at_encoding"):
            self.assertIn(expected, names)

    def test_ranges(self):
        ranges = {field["name"]: (field["min"], field["max"])
                  for field in schema.FIELDS}
        self.assertEqual(ranges["v"], (-1.0, 1.0))
        self.assertEqual(ranges["goal"], (-1.0, 1.0))
        self.assertEqual(ranges["stress"], (0.0, 1.0))
        self.assertEqual(ranges["theta"], (0.35, 0.75))
        self.assertEqual(ranges["cooldown_s"], (1200, 10800))

    def test_docs_match_code(self):
        self.assertEqual(DOC.read_text(encoding="utf-8"), schema.render_markdown())
        text = DOC.read_text(encoding="utf-8")
        for field in schema.FIELDS:
            self.assertIn(field["name"], text)
            self.assertIn(field["desc"], text)


class LegendTest(unittest.TestCase):
    def test_significant_values_appear(self):
        text = schema.numeric_legend({"v": 0.55, "a": 0.9, "stress": 0.7})
        self.assertIn(schema.LEGEND_HEADER, text)
        self.assertIn("v 效价", text)
        self.assertIn("a 唤醒", text)
        self.assertIn("stress 压力", text)
        self.assertLessEqual(len(text), schema.LEGEND_LIMIT)

    def test_flat_state_is_empty(self):
        text = schema.numeric_legend({"v": 0.0, "a": 0.4, "stress": 0.1,
                                      "social": 0.55, "trust": 0.5})
        self.assertEqual(text, "")

    def test_threshold_and_custom_baseline(self):
        self.assertEqual(schema.numeric_legend({"v": 0.14}), "")
        self.assertNotEqual(schema.numeric_legend({"v": 0.2}), "")
        self.assertEqual(schema.numeric_legend({"v": 0.9},
                                               baselines={"v": 0.9}), "")

    def test_max_five_items_and_limit(self):
        values = {"v": 1.0, "a": 1.0, "stress": 1.0, "social": 1.0,
                  "trust": 1.0, "self_esteem": 1.0, "social_pain": 1.0}
        text = schema.numeric_legend(values)
        self.assertLessEqual(text.count("现在"), schema.LEGEND_MAX_ITEMS)
        self.assertLessEqual(len(text), schema.LEGEND_LIMIT)


class InjectionTest(unittest.TestCase):
    def test_legend_in_system_after_persona_before_protocol(self):
        legend = schema.numeric_legend({"v": 0.8, "stress": 0.8})
        out = et.build_reply(state_ctx={"numeric_legend": legend},
                             opts={"persona": "你是小灰", "speak_style": "口语"})
        system = out["system"]
        self.assertIn(schema.LEGEND_HEADER, system)
        self.assertLess(system.index("小灰"), system.index(schema.LEGEND_HEADER))
        self.assertLess(system.index(schema.LEGEND_HEADER),
                        system.index("【输出格式"))
        self.assertNotIn(schema.LEGEND_HEADER, out["user"])

    def test_no_legend_when_flat(self):
        out = et.build_reply(opts={"persona": "你是小灰"})
        self.assertNotIn(schema.LEGEND_HEADER, out["system"])

    def test_runtime_enrich_sets_legend(self):
        core = types.SimpleNamespace(snapshot=lambda: {
            "v": 0.8, "a": 0.9, "stress": 0.8, "social": 0.2,
            "trust": 0.2, "self_esteem": 0.2})
        plugin = types.SimpleNamespace(_relationship_of=lambda user: {},
                                       persona_text="", prompt_rules=None)
        ctx = {"core": core, "plugin": plugin, "user": {}, "meta": {}}
        out = rt.enrich_ctx(ctx)
        self.assertIn(schema.LEGEND_HEADER, out.get("numeric_legend", ""))


if __name__ == "__main__":
    unittest.main()
