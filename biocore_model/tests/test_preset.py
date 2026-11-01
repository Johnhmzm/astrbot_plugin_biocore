# -*- coding: utf-8 -*-
"""Preset structure tests: positions, order, conditions, depth, empty skip."""
import sys
import unittest
from pathlib import Path

from biocore_model import preset

PKG = Path(__file__).resolve().parents[1]
IDS = ["situation", "layered_memory", "graph_memory", "state_block",
       "relationship", "gap", "speak_style", "numeric_legend"]
FULL = {"situation": "对方在质问你。", "layered_memory": "[分层记忆] 常驻事实：他姓王", "graph_memory": "你知道的：\n- 小夏 —害怕→ 打雷",
        "state_block": "她此刻：紧张。", "relationship": "关系：亲近，信任中等。",
        "gap": "已 3 小时没说话。", "speak_style": "一次只说一句，10 字以内。",
        "numeric_legend": "v 正面度 / a 唤醒度"}


def _rec(**extra):
    base = {"id": "x", "name": "X", "role": "system",
            "position": "before_history", "depth": 4, "order": 100,
            "enabled": True, "condition": "", "content": "{{ value }}"}
    base.update(extra)
    return base


class StructureTest(unittest.TestCase):
    def test_default_record_ids(self):
        self.assertEqual([r["id"] for r in preset.PRESET], IDS)

    def test_default_record_fields(self):
        required = {"id", "name", "role", "position", "depth", "order",
                    "enabled", "condition", "content"}
        for record in preset.PRESET:
            self.assertTrue(required.issubset(record.keys()), record["id"])
            self.assertIn(record["position"], preset.POSITIONS)
            self.assertTrue(record["enabled"])

    def test_default_positions(self):
        by_id = {r["id"]: r for r in preset.PRESET}
        for key in ("situation", "layered_memory", "state_block",
                    "relationship", "gap"):
            self.assertEqual(by_id[key]["position"], "before_history")
        self.assertEqual(by_id["speak_style"]["position"], "depth")
        self.assertEqual(by_id["speak_style"]["depth"], 2)
        self.assertEqual(by_id["numeric_legend"]["position"], "after_history")

    def test_before_history_order(self):
        out = preset.assemble(FULL, history_len=10)
        self.assertEqual([b["id"] for b in out["before_history"]],
                         ["situation", "layered_memory", "graph_memory",
                          "state_block", "relationship", "gap"])

    def test_depth_group(self):
        out = preset.assemble(FULL, history_len=10)
        self.assertEqual(len(out["depth"]), 1)
        self.assertEqual(out["depth"][0]["depth"], 2)
        self.assertEqual(out["depth"][0]["blocks"][0]["id"], "speak_style")

    def test_after_history_group(self):
        out = preset.assemble(FULL, history_len=10)
        self.assertEqual([b["id"] for b in out["after_history"]],
                         ["numeric_legend"])

    def test_empty_action_skips_missing_vars(self):
        out = preset.assemble({}, history_len=3)
        self.assertEqual(out["before_history"], [])
        self.assertEqual(out["depth"], [])
        self.assertEqual(out["after_history"], [])

    def test_empty_content_is_skipped(self):
        out = preset.assemble({"situation": "   ", "gap": "\n"}, 3)
        self.assertEqual(out["before_history"], [])

    def test_variables_are_substituted(self):
        out = preset.assemble({"situation": "他在夸你。"}, 3)
        self.assertEqual(out["before_history"][0]["content"],
                         "[局面摘要]\n他在夸你。")

    def test_condition_false_hides_block(self):
        out = preset.assemble({"situation": "x", "layered_memory": ""}, 3)
        self.assertEqual([b["id"] for b in out["before_history"]],
                         ["situation"])

    def test_threshold_condition(self):
        record = _rec(condition="trust > 0.5", content="trusted")
        self.assertEqual(len(preset._blocks([record], {"trust": 0.8}, 0)), 1)
        self.assertEqual(len(preset._blocks([record], {"trust": 0.2}, 0)), 0)

    def test_invalid_condition_fails_closed(self):
        record = _rec(condition="1 +", content="never")
        self.assertEqual(preset._blocks([record], {}, 0), [])

    def test_order_sorting(self):
        low = _rec(id="b", order=200, content="B")
        high = _rec(id="a", order=100, content="A")
        out = preset._blocks([low, high], {}, 0)
        self.assertEqual([b["id"] for b in out], ["a", "b"])

    def test_depth_clamped_by_history_len(self):
        out = preset.assemble(FULL, history_len=1)
        self.assertEqual(out["depth"][0]["depth"], 1)
        out2 = preset.assemble(FULL, history_len=0)
        self.assertEqual(out2["depth"][0]["depth"], 0)

    def test_render_texts_flattens_positions(self):
        rows = preset.render_texts(preset.assemble(FULL, 10))
        positions = [row[0] for row in rows]
        self.assertEqual(positions.count("before_history"), 6)
        self.assertEqual(positions.count("depth"), 1)
        self.assertEqual(positions.count("after_history"), 1)

    def test_module_is_pure_and_does_not_import_main(self):
        source = (PKG / "preset.py").read_text(encoding="utf-8")
        self.assertNotIn("import main", source)
        self.assertNotIn("main.py", source)
        # Check the module's own namespace instead of the global sys.modules:
        # discovery imports root-level test modules that import main, which made
        # the old process-wide assertion order-dependent.
        module = sys.modules.get("biocore_model.preset")
        self.assertIsNotNone(module)
        self.assertNotIn("main", vars(module))

    def test_depth_index_after_nth_newest(self):
        self.assertEqual(preset.depth_index(10, 2), 9)
        self.assertEqual(preset.depth_index(3, 5), 0)
        self.assertEqual(preset.depth_index(0, 2), 0)

    def test_ui_settings_preset_default_is_on(self):
        from biocore_model import ui_settings
        self.assertIs(ui_settings.DEFAULTS["preset"]["enabled"], True)

    def test_main_has_gated_fallback_path(self):
        from pathlib import Path
        repo = Path(__file__).resolve().parents[2]
        main = (repo / "main.py").read_text(encoding="utf-8")
        self.assertIn("if self._preset_enabled():", main)
        self.assertIn("self._inject_preset(req, event, core, _user_data,", main)
        self.assertIn("self._legacy_context_blocks(req, event, core, _user_data,",
                      main)

if __name__ == "__main__":
    unittest.main()
