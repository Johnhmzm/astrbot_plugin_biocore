# -*- coding: utf-8 -*-
"""task-149/150/151 接线测试：三个自我层模块 + 面板投射（只读源码断言）。

纯函数行为由 test_prospective / test_voice_bank / test_metacog 覆盖；这里只确认
main.py 的接线位置、开关默认值、回退守卫、提示合流与面板投射都存在，不导入
AstrBot。
"""
import json
import unittest
from pathlib import Path

from biocore_model import self_intent as si

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "biocore_model" / "plugin_routes.py").read_text(encoding="utf-8")
SCHEMA = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
DASH = ROOT / "pages" / "dashboard"
SRC_HTML = (DASH / "index.src.html").read_text(encoding="utf-8")
INDEX_HTML = (DASH / "index.html").read_text(encoding="utf-8")
APP_JS = (DASH / "app.js").read_text(encoding="utf-8")


class FlagTest(unittest.TestCase):
    def test_schema_flags_default_true(self):
        for key in ("prospective_enabled", "voice_bank_enabled",
                    "metacog_enabled"):
            entry = SCHEMA.get(key)
            self.assertIsInstance(entry, dict, key)
            self.assertEqual(entry.get("type"), "bool", key)
            self.assertIs(entry.get("default"), True, key)

    def test_main_reads_flags(self):
        for key in ("prospective_enabled", "voice_bank_enabled",
                    "metacog_enabled"):
            self.assertIn('self.config.get("%s", True)' % key, MAIN)
        self.assertIn("self.prospective_enabled = True", MAIN)
        self.assertIn("self.voice_bank_enabled = True", MAIN)
        self.assertIn("self.metacog_enabled = True", MAIN)


class ProspectiveWiringTest(unittest.TestCase):
    def test_due_check_and_pending_prompts(self):
        self.assertIn("from .biocore_model import prospective as _pm_mod", MAIN)
        self.assertIn("_pm_mod.mark_overdue(", MAIN)
        self.assertIn("_pm_mod.due_now(", MAIN)
        self.assertIn("_pm_mod.build_hint(", MAIN)
        self.assertIn("core.pending_prompts = _pm_hints", MAIN)
        self.assertIn('if bool(getattr(self, "prospective_enabled", True)):', MAIN)

    def test_prospective_hint_feeds_expression_layer(self):
        self.assertIn("self._prospective_hint = _pm_hints[0]", MAIN)
        self.assertIn("self._prospective_hint", MAIN)
        self.assertNotIn("await event.send", MAIN.split("prospective as _pm_mod")[1][:4000])

    def test_prospective_store_path(self):
        self.assertIn('self._self_layer_data_file("prospective.json")', MAIN)
        self.assertIn('base = DATA_DIR / "biocore"', MAIN)


class VoiceBankWiringTest(unittest.TestCase):
    def test_pick_and_phrases(self):
        self.assertIn("from .biocore_model import voice_bank as _vb_mod", MAIN)
        self.assertIn("_vb_mod.pick(", MAIN)
        self.assertIn("core.voice_phrases = _vb_phrases", MAIN)
        self.assertIn('if bool(getattr(self, "voice_bank_enabled", True)):', MAIN)

    def test_voice_data_file_and_usage(self):
        self.assertIn('self._self_layer_data_file("voice_bank.json")', MAIN)
        self.assertIn('self._self_layer_data_file(\n                                "voice_bank_used.json")', MAIN)
        self.assertIn("_vb_mod.mark_used(", MAIN)

    def test_voice_hint_bounded(self):
        self.assertIn('"口头习惯：" + "；".join(_vb_phrases)', MAIN)
        self.assertIn("self._voice_hint", MAIN)


class MetacogWiringTest(unittest.TestCase):
    def test_evaluate_and_history(self):
        self.assertIn("from .biocore_model import metacog as _mc_mod", MAIN)
        self.assertIn("_mc_mod.evaluate(", MAIN)
        self.assertIn("_mc_mod.directives(", MAIN)
        self.assertIn("_mc_mod.remember(", MAIN)
        self.assertIn('if _sl_meta_on:', MAIN)

    def test_directives_drive_length(self):
        self.assertIn("core.self_length_scale = max(0.5, min(1.5, _sl_scale))", MAIN)
        self.assertIn("_sl_scale = min(_sl_scale, max(0.0, _mc_scale))", MAIN)
        self.assertIn("self._metacog_hint = _mc_tone", MAIN)
        self.assertIn('self._self_layer_data_file("metacog.json")', MAIN)

    def test_expression_layers_read_metacog_flag(self):
        self.assertIn('getattr(core, "metacog_enabled", False)', MAIN)


class HintCombineTest(unittest.TestCase):
    def test_hints_combined_once(self):
        self.assertIn("for _sl_hint in (getattr(self, \"_prospective_hint\", \"\"),", MAIN)
        self.assertIn("interpretation.combine_strategy_hint(", MAIN)
        self.assertIn("self._last_strategy_hint = str(_strategy_hint)[:140]", MAIN)


class PanelProjectionTest(unittest.TestCase):
    def test_payload_uses_module_projection(self):
        self.assertIn("_si_view.payload(", MAIN)
        self.assertIn('_self_intent_status_payload', MAIN)
        self.assertIn('"self_intent": (self._self_intent_status_payload()', MAIN)
        self.assertIn('"self_intent": (self._self_intent_status_payload()', ROUTES)

    def test_payload_projection_bounds(self):
        result = si.evaluate(snapshot={"stress": 0.2}, relationship={},
                             needs={"belonging": 0.2})
        out = si.payload(result, pending_prompts=["p" * 100],
                         voice_phrases=["v" * 40],
                         metacog={"band": "low" * 5, "confidence": 0.3})
        self.assertLessEqual(len(out["pending_prompts"][0]), 60)
        self.assertLessEqual(len(out["voice_phrases"][0]), 20)
        self.assertTrue(out["metacog"]["band"].startswith("low"))
        self.assertLessEqual(out["top_weight"], 1.0)
        self.assertGreaterEqual(out["top_weight"], 0.0)

    def test_dashboard_row_next_to_memory_meta(self):
        self.assertIn('id="selfIntentNote"', SRC_HTML)
        self.assertIn('id="selfIntentNote"', INDEX_HTML)
        self.assertIn('siEl=$("selfIntentNote")', APP_JS)
        self.assertIn("她的意图：", SRC_HTML)
        # the row sits right after the memory-meta strategy line
        self.assertLess(SRC_HTML.index("memHintNote"),
                        SRC_HTML.index("selfIntentNote"))


class RollbackTest(unittest.TestCase):
    def test_disabled_switch_clears_projection(self):
        self.assertIn('core.pending_prompts = []', MAIN)
        self.assertIn('core.voice_phrases = []', MAIN)
        self.assertIn('if not _sl_self_on and not _sl_meta_on:', MAIN)

    def test_one_turn_computation(self):
        # a single occurrence in the turn path (prospective block marker)
        self.assertEqual(MAIN.count('self._self_layer_data_file("prospective.json")'), 1)
        self.assertEqual(MAIN.count('_pm_mod.due_now('), 1)
        self.assertEqual(MAIN.count('_vb_mod.pick('), 1)
        self.assertEqual(MAIN.count('_mc_mod.evaluate('), 1)


class PanelMethodTest(unittest.TestCase):
    """Exec the real projection method from main.py against a fake plugin."""

    @staticmethod
    def _method():
        import ast
        import types
        tree = ast.parse(MAIN)
        nodes = [node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)
                 and node.name == "_self_intent_status_payload"]
        assert len(nodes) == 1, "expected exactly one projection method"
        module = ast.Module(body=nodes, type_ignores=[])
        ns = {}
        exec(compile(module, "<panel_projection>", "exec"), ns)
        return ns["_self_intent_status_payload"]

    def test_projection_reads_core_state(self):
        import types
        method = self._method()
        result = si.evaluate(
            snapshot={"stress": 0.2, "energy": 0.7},
            relationship={"closeness": 0.9, "trust": 0.9},
            needs={"belonging": 0.2, "self_esteem": 0.6,
                   "control": 0.6, "meaningful_existence": 0.6},
            silence_seconds=12 * 3600)
        core = types.SimpleNamespace(
            self_intent=result,
            pending_prompts=["你答应过要问一句：体检结果"],
            voice_phrases=["少来。"],
            metacog={"band": "low", "confidence": 0.3, "converge": False,
                     "allow_self_correction": False, "low_streak": 1})
        plugin = types.SimpleNamespace(cores={"k": core},
                                       self_intent_enabled=True)
        out = method(plugin)
        self.assertEqual(out["top"], result["top"])
        self.assertEqual(out["top_weight"], result["intents"][0]["weight"])
        self.assertEqual(out["pending_prompts"][0][:4], "你答应过")
        self.assertEqual(out["voice_phrases"], ["少来。"])
        self.assertEqual(out["metacog"]["band"], "low")

    def test_projection_defaults_without_core(self):
        method = self._method()
        import types
        plugin = types.SimpleNamespace(cores={}, self_intent_enabled=True)
        out = method(plugin)
        self.assertEqual(out["top"], "顺着你")
        self.assertEqual(out["intents"], [])
        self.assertGreaterEqual(out["self_weight"], si.SELF_WEIGHT_FLOOR)


if __name__ == "__main__":
    unittest.main()
