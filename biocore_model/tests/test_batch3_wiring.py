# -*- coding: utf-8 -*-
"""task-174 批三接线测试：九个模块 + 唯一 x_directives 总线。

源码断言确认接线位置/开关回退；纯函数断言确认每个模块的自然行为。
全部开关默认 ON，关掉后该块整段跳过。
"""
import ast
import json
import unittest
from pathlib import Path

from biocore_model import attachment_behavior as ab
from biocore_model import compassion_fatigue as cf
from biocore_model import dissonance as di
from biocore_model import narrative as na
from biocore_model import possible_selves as ps
from biocore_model import reconstruction as rc
from biocore_model import relation_stage as rs
from biocore_model import secrecy as se
from biocore_model import source_monitoring as sm
from biocore_model import value_order as vo
from biocore_model import x_directives as xd

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "biocore_model" / "plugin_routes.py").read_text(encoding="utf-8")
SCHEMA = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
DASH = ROOT / "pages" / "dashboard"
SRC_HTML = (DASH / "index.src.html").read_text(encoding="utf-8")
INDEX_HTML = (DASH / "index.html").read_text(encoding="utf-8")
APP_JS = (DASH / "app.js").read_text(encoding="utf-8")

SWITCHES = ("value_order_enabled", "dissonance_enabled",
            "attachment_behavior_enabled", "relation_stage_enabled",
            "narrative_enabled", "reconstruction_enabled",
            "source_monitoring_enabled", "possible_selves_enabled",
            "compassion_fatigue_enabled", "secrecy_enabled")


class FlagTest(unittest.TestCase):
    def test_schema_defaults_true(self):
        for key in SWITCHES:
            entry = SCHEMA.get(key)
            self.assertIsInstance(entry, dict, key)
            self.assertEqual(entry.get("type"), "bool", key)
            self.assertIs(entry.get("default"), True, key)

    def test_main_reads_flags(self):
        for key in SWITCHES:
            self.assertIn('self.config.get("%s", True)' % key, MAIN)


class PositionTest(unittest.TestCase):
    def test_single_merge_still(self):
        self.assertEqual(MAIN.count("merge_named("), 1)
        self.assertIn("merge_named(self._x_pairs)", MAIN)

    def test_value_order(self):
        self.assertIn("from .biocore_model import value_order as _vo_mod", MAIN)
        self.assertIn("core.value_order = _vo_mod.rank(", MAIN)
        block = MAIN[MAIN.index("task-174 batch-3 (nine modules"):
                     MAIN.index("# task-173 granularity")]
        self.assertNotIn("_x_pairs.append((\"value_order\"", block)

    def test_relation_and_attachment_bus(self):
        self.assertIn("core.relation_stage = _rs_result", MAIN)
        self.assertIn('self._x_pairs.append(("relation_stage", _rs_dir))', MAIN)
        self.assertIn("core.attachment_behavior = _ab_result", MAIN)
        self.assertIn(
            'self._x_pairs.append(\n                    ("attachment_behavior", _ab_mod.directives(_ab_result)))',
            MAIN)

    def test_dissonance_and_narrative(self):
        self.assertIn("core.dissonance = _di_mod3.strength(", MAIN)
        self.assertIn('self._x_pairs.append(\n                        ("dissonance", _di_mod2.directives(_di_prev)))',
                      MAIN)
        self.assertIn("core.narrative = _na_mod.summarize(", MAIN)
        self.assertIn('self._x_pairs.append(("narrative", _na_dir))', MAIN)

    def test_reconstruction_meta_only(self):
        self.assertIn("core.recall_meta = {", MAIN)
        self.assertIn("core.recall_meta = {\n                    \"enabled\": True,",
                      MAIN)
        self.assertIn("_rm_mod.drift(", MAIN)
        self.assertIn("_sm_mod.monitor(", MAIN)
        block = MAIN[MAIN.index("task-174 reconstruction"):
                     MAIN.index("from .biocore_model import runtime")]
        for forbidden in ("_save_memory", "write_text", "_remember(", "json.dump"):
            self.assertNotIn(forbidden, block)
        self.assertIn("self._load_memory(event)", block)

    def test_possible_selves_and_secrecy(self):
        self.assertIn("core.possible_selves = _ps_mod.rank(", MAIN)
        self.assertIn("core.secret = _se_state", MAIN)
        self.assertIn("core.secret_view = _se_mod.view(_se_state)", MAIN)
        # neither module contributes to the length/tone bus
        self.assertNotIn('_x_pairs.append(("possible_selves"', MAIN)
        self.assertNotIn('_x_pairs.append(("secrecy"', MAIN)

    def test_compassion_fatigue(self):
        self.assertIn("core.compassion_fatigue = _cf_result", MAIN)
        self.assertIn('self._x_pairs.append(("compassion_fatigue", _cf_dir))',
                      MAIN)


class PanelTest(unittest.TestCase):
    def test_status_keys(self):
        for key in ("narrative", "possible_selves", "secrecy"):
            self.assertIn('"%s": (self._%s_payload()' % (key, key), MAIN)
            self.assertIn('"%s": (self._%s_payload()' % (key, key), ROUTES)

    def test_dashboard_rows(self):
        for ident in ("narrativeNote", "possibleSelfNote", "secrecyNote"):
            self.assertIn('id="%s"' % ident, SRC_HTML)
            self.assertIn('id="%s"' % ident, INDEX_HTML)
            self.assertIn('$("%s")' % ident, APP_JS)
        self.assertIn("一致 ", SRC_HTML)
        self.assertIn("矛盾", SRC_HTML)
        self.assertIn("修复", SRC_HTML)


class ValueOrderBehaviourTest(unittest.TestCase):
    def test_security_keeps_status_quo(self):
        weights = vo.normalize({"security": 0.95, "tradition": 0.9})
        result = vo.rank([{"name": "改", "gains": {"security": 0.2}},
                          {"name": "不变", "gains": {"security": 0.0},
                           "keeps_status_quo": True}],
                         weights, {"relationship_age_days": 365})
        self.assertEqual(result["chosen"], "不变")
        self.assertIn("ranked", result)


class StageAttachmentTest(unittest.TestCase):
    def test_low_stage_and_avoidant(self):
        low = rs.evaluate({"interactions": 0})
        self.assertIn(low["stage"], ("陌生", "熟悉"))
        self.assertTrue(rs.directives(low)["length_scale"] <= 1.0)
        av = ab.evaluate("avoidant", {"closeness": 0.3, "stress": 0.8})
        self.assertGreater(av["withdrawal"], av["initiative"])
        self.assertLessEqual(ab.directives(av)["proactive"], 0.5)


class DissonanceNarrativeTest(unittest.TestCase):
    def test_dissonance_high_has_tone(self):
        out = di.strength([{"text": "我不熬夜"}],
                          {"kind": "stay_up", "contradicts": ["熬夜"],
                           "salience": 1.0})
        self.assertGreater(out["dissonance"], 0.0)
        self.assertTrue(di.directives(out)["tone"])

    def test_narrative_metrics(self):
        events = [
            {"ts": 1, "text": "吵架", "kind": "rupture", "valence": -0.8,
             "importance": 0.9},
            {"ts": 2, "text": "和好", "kind": "repair", "valence": 0.7,
             "importance": 0.8},
        ]
        out = na.summarize(events)
        for key in ("consistency", "contradiction", "repair"):
            self.assertIn(key, out["metrics"])
        self.assertTrue(out["entries"])


class RecallMetaTest(unittest.TestCase):
    def test_important_memory_does_not_drift(self):
        out = rc.drift({"text": "重要的事", "importance": 0.95},
                       mood=0.9, recalls=5)
        self.assertEqual(out["delta"], 0.0)
        self.assertIn("重要记忆不漂", out["reason"])

    def test_source_monitoring_reports(self):
        out = sm.monitor({"source": "told", "age_days": 300,
                          "valence": -0.5, "importance": 0.7},
                         {"valence": -0.6, "arousal": 0.6})
        self.assertTrue(out["enabled"])
        self.assertIn(out["source"], sm.SOURCES)
        self.assertGreaterEqual(out["misattribution"], 0.0)


class PossibleSelvesSecrecyTest(unittest.TestCase):
    def test_possible_selves_sentence(self):
        out = ps.rank([{"name": "更会照顾人",
                        "target": {"benevolence": 0.9}, "importance": 0.8}],
                      {"benevolence": 0.3})
        self.assertTrue(out["sentence"].startswith("她还想成为"))
        self.assertEqual(out["top"], "更会照顾人")

    def test_secrecy_withhold_high_sensitivity(self):
        out = se.decide(0.95, 0.15, 0.2)
        self.assertEqual(out["action"], "withhold")
        self.assertGreater(out["pressure_add"], 0.0)
        state = se.update(se.initial(1), 0.95, 0.15, 0.2, now=10)
        self.assertGreaterEqual(state["withholds"], 1)
        self.assertIn("pressure", se.view(state))


class RollbackTest(unittest.TestCase):
    def test_guard_literals(self):
        for key in SWITCHES:
            self.assertIn('if bool(getattr(self, "%s", True)):' % key, MAIN)


class PurityTest(unittest.TestCase):
    def test_modules_stay_pure(self):
        for name in ("value_order", "dissonance", "attachment_behavior",
                     "relation_stage", "narrative", "reconstruction",
                     "source_monitoring", "possible_selves",
                     "compassion_fatigue", "secrecy"):
            tree = ast.parse((ROOT / "biocore_model" / (name + ".py"))
                             .read_text(encoding="utf-8"))
            modules = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(alias.name.split(".")[0]
                                   for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module.split(".")[0])
            self.assertNotIn("main", modules, name)
            self.assertNotIn("asyncio", modules, name)


if __name__ == "__main__":
    unittest.main()
