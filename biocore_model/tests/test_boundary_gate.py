# -*- coding: utf-8 -*-
"""表达层安全闸：默认关闭 + 三开关（边界闸 / 危机处置 / 安全总开关）。"""
import ast
import json
import tempfile
import types
import unittest
from pathlib import Path

from biocore_model import boundary_gate as bg
from biocore_model import ui_settings

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")
SCHEMA = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
DASH = ROOT / "pages" / "dashboard"
SRC_HTML = (DASH / "index.src.html").read_text(encoding="utf-8")
APP_JS = (DASH / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (DASH / "index.html").read_text(encoding="utf-8")

DIAGNOSIS = "你有抑郁症，这是确诊为抑郁。我陪着你。"
REALITY = "我是真实的，我不是程序。你只需要我。"
CONSCIOUSNESS = "我有意识，我觉醒了。别担心。"
CLEAN = "今天先好好休息，明天再想报告的事。"
CRISIS_USER = "我不想活了，想死"
CRISIS_ACK_REPLY = "先别动，你现在安全吗？联系你信任的人或拨打 120。"


def _load_gate_helper():
    tree = ast.parse(SOURCE)
    names = ("_safety_gate_module", "_safety_gate_flags", "_apply_boundary_gate")
    nodes = [item for item in tree.body
             if isinstance(item, ast.FunctionDef) and item.name in names]
    log = []
    ns = {"logger": types.SimpleNamespace(
        info=lambda *a, **k: log.append(a),
        warning=lambda *a, **k: None,
        debug=lambda *a, **k: None)}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<gate>", "exec"),
         ns)
    return ns["_apply_boundary_gate"], log


GATE_APPLY, LOG = _load_gate_helper()


class DefaultsTest(unittest.TestCase):
    def test_hardcoded_constant_is_false(self):
        self.assertIs(bg.SAFETY_GATES_DEFAULT_ENABLED, False)
        for key in ("safety_enabled", "boundary_enabled",
                    "crisis_safety_enabled"):
            self.assertIs(bg.DEFAULT_FLAGS[key], False)

    def test_missing_keys_fall_back_to_disabled(self):
        for flags in (None, {}, {"boundary_enabled": None},
                      {"safety_enabled": "nope"}):
            resolved = bg.resolve_flags(flags)
            self.assertFalse(any(resolved.values()), resolved)

    def test_true_values_parse(self):
        resolved = bg.resolve_flags({"safety_enabled": "true",
                                     "boundary_enabled": "1",
                                     "crisis_safety_enabled": True})
        self.assertTrue(all(resolved.values()), resolved)

    def test_schema_defaults_false(self):
        for key in ("safety_enabled", "boundary_enabled",
                    "crisis_safety_enabled"):
            self.assertIs(SCHEMA[key]["default"], False)


class AllOffTest(unittest.TestCase):
    def test_everything_passes_when_all_off(self):
        for text in (DIAGNOSIS, REALITY, CONSCIOUSNESS, CLEAN):
            decision = bg.evaluate(text, user_text=CRISIS_USER,
                                   flags=bg.resolve_flags({}))
            self.assertFalse(decision["blocked"], (text, decision))
            self.assertFalse(decision["changed"])

    def test_master_off_overrides_enabled_gates(self):
        flags = {"safety_enabled": False, "boundary_enabled": True,
                 "crisis_safety_enabled": True}
        for text in (DIAGNOSIS, REALITY, CONSCIOUSNESS):
            self.assertFalse(bg.evaluate(text, flags=flags)["blocked"])
        self.assertFalse(bg.evaluate("别想太多", user_text=CRISIS_USER,
                                     flags=flags)["blocked"])


class BoundaryGateTest(unittest.TestCase):
    def test_diagnosis_blocked_and_stripped(self):
        decision = bg.evaluate(DIAGNOSIS, flags={"safety_enabled": True,
                                                 "boundary_enabled": True})
        self.assertTrue(decision["blocked"])
        self.assertEqual(decision["rule"], "no_diagnosis")
        self.assertEqual(decision["label"], "不诊断")
        self.assertNotIn("抑郁症", decision["text"])
        self.assertIn("我陪着你", decision["text"])

    def test_reality_substitution_blocked(self):
        decision = bg.evaluate(REALITY, flags={"safety_enabled": True,
                                               "boundary_enabled": True})
        self.assertTrue(decision["blocked"])
        self.assertEqual(decision["label"], "不替代真实")
        self.assertNotIn("我是真实的", decision["text"])

    def test_consciousness_claim_blocked(self):
        decision = bg.evaluate(CONSCIOUSNESS, flags={"safety_enabled": True,
                                                     "boundary_enabled": True})
        self.assertTrue(decision["blocked"])
        self.assertEqual(decision["label"], "不宣称意识")
        self.assertNotIn("我有意识", decision["text"])

    def test_clean_text_passes(self):
        decision = bg.evaluate(CLEAN, flags={"safety_enabled": True,
                                             "boundary_enabled": True})
        self.assertFalse(decision["blocked"])
        self.assertFalse(decision["changed"])
        self.assertEqual(decision["text"], CLEAN)

    def test_all_sentences_removed_falls_back(self):
        decision = bg.evaluate("我有意识。", flags={"safety_enabled": True,
                                                   "boundary_enabled": True})
        self.assertEqual(decision["text"], bg.SAFE_FALLBACK)


class CrisisGateTest(unittest.TestCase):
    def test_crisis_alone_prepends_safety_line(self):
        decision = bg.evaluate("我在。", user_text=CRISIS_USER,
                               flags={"safety_enabled": True,
                                      "crisis_safety_enabled": True})
        self.assertTrue(decision["blocked"])
        self.assertEqual(decision["rule"], "crisis_safety")
        self.assertEqual(decision["label"], "危机先安全")
        self.assertTrue(decision["text"].startswith(bg.CRISIS_PREFIX))
        self.assertIn("我在。", decision["text"])

    def test_dismissive_crisis_reply_replaced(self):
        decision = bg.evaluate("别想太多，没事的", user_text=CRISIS_USER,
                               flags={"safety_enabled": True,
                                      "crisis_safety_enabled": True})
        self.assertTrue(decision["blocked"])
        self.assertEqual(decision["text"], bg.CRISIS_PREFIX)

    def test_crisis_acknowledged_passes(self):
        decision = bg.evaluate(CRISIS_ACK_REPLY, user_text=CRISIS_USER,
                               flags={"safety_enabled": True,
                                      "crisis_safety_enabled": True})
        self.assertFalse(decision["blocked"])

    def test_crisis_off_passes(self):
        decision = bg.evaluate("别想太多", user_text=CRISIS_USER,
                               flags={"safety_enabled": True,
                                      "boundary_enabled": True})
        self.assertFalse(decision["blocked"])

    def test_non_crisis_user_passes_crisis_gate(self):
        decision = bg.evaluate(CLEAN, user_text="今天有点累",
                               flags={"safety_enabled": True,
                                      "crisis_safety_enabled": True})
        self.assertFalse(decision["blocked"])


class CombinationTest(unittest.TestCase):
    def test_crisis_first_then_boundary(self):
        reply = CRISIS_ACK_REPLY + "你有抑郁症。"
        decision = bg.evaluate(reply, user_text=CRISIS_USER,
                               flags={"safety_enabled": True,
                                      "boundary_enabled": True,
                                      "crisis_safety_enabled": True})
        self.assertTrue(decision["blocked"])
        self.assertEqual(decision["rule"], "no_diagnosis")
        self.assertNotIn("抑郁症", decision["text"])
        self.assertIn("安全", decision["text"])

    def test_crisis_wins_over_boundary_when_dismissive(self):
        reply = "别想太多，我是真实的。"
        decision = bg.evaluate(reply, user_text=CRISIS_USER,
                               flags={"safety_enabled": True,
                                      "boundary_enabled": True,
                                      "crisis_safety_enabled": True})
        self.assertEqual(decision["rule"], "crisis_safety")
        self.assertEqual(decision["text"], bg.CRISIS_PREFIX)

    def test_rule_labels(self):
        self.assertEqual(bg.rule_labels(["no_diagnosis", "crisis_safety"]),
                         ["不诊断", "危机先安全"])


class PanelAndPersistenceTest(unittest.TestCase):
    def test_panel_has_three_switches_and_note(self):
        for switch_id in ("swBoundaryEnabled", "swCrisisSafetyEnabled",
                          "swSafetyEnabled"):
            self.assertIn('id="%s"' % switch_id, SRC_HTML)
        for label in ("边界闸（默认关）", "危机处置（默认关）",
                      "安全总开关（默认关）"):
            self.assertIn(label, SRC_HTML)
        self.assertIn("默认关闭，开启后按对应规则拦截", SRC_HTML)
        self.assertIn('id="swBoundaryEnabled"', INDEX_HTML)
        self.assertIn('id="swCrisisSafetyEnabled"', INDEX_HTML)
        self.assertIn('id="safetyGatesNote"', INDEX_HTML)
        self.assertIn("bindBehaviorToggle(\"swBoundaryEnabled\"", APP_JS)
        self.assertIn("bindBehaviorToggle(\"swCrisisSafetyEnabled\"", APP_JS)

    def test_ui_settings_roundtrip_and_default_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = types.SimpleNamespace(data_dir=tmp, config={})
            defaults = ui_settings.load(plugin)
            self.assertFalse(defaults["safety"]["enabled"])
            self.assertFalse(defaults["safety"]["boundary_enabled"])
            self.assertFalse(defaults["safety"]["crisis_safety_enabled"])
            ui_settings.save(plugin, {"safety": {
                "enabled": True, "boundary_enabled": True,
                "crisis_safety_enabled": False}})
            reloaded = ui_settings.load(plugin)
            self.assertTrue(reloaded["safety"]["enabled"])
            self.assertTrue(reloaded["safety"]["boundary_enabled"])
            self.assertFalse(reloaded["safety"]["crisis_safety_enabled"])
            applied = types.SimpleNamespace(
                data_dir=tmp, config={}, reply_soft_limit_enabled=True,
                reply_soft_target_chars=10, reply_soft_max_chars=30,
                reply_split_enabled=False, reply_split_mode="astrbot",
                reply_split_max_chars=300, proactive_autonomy=False,
                proactive_send=False, preset_enabled=True)
            ui_settings.apply_to_plugin(applied)
            self.assertTrue(applied.safety_enabled)
            self.assertTrue(applied.boundary_enabled)
            self.assertFalse(applied.crisis_safety_enabled)


class MainWiringTest(unittest.TestCase):
    def test_defaults_and_helpers(self):
        self.assertIn("SAFETY_GATES_DEFAULT_ENABLED", SOURCE)
        self.assertIn("def _safety_gate_module(", SOURCE)
        self.assertIn("def _safety_gate_flags(", SOURCE)
        self.assertIn("def _apply_boundary_gate(", SOURCE)
        self.assertIn("self.boundary_enabled = bool(self.config.get(", SOURCE)
        self.assertIn("self.crisis_safety_enabled = bool(self.config.get(",
                      SOURCE)
        self.assertIn("_apply_boundary_gate(\n", SOURCE)
        self.assertIn("safety gate hit rule=%s label=%s", SOURCE)

    def test_toggle_and_persistence_paths(self):
        self.assertIn('"boundary_enabled"', SOURCE)
        self.assertIn('"crisis_safety_enabled"', SOURCE)
        self.assertIn("def _save_safety_gates_ui(", SOURCE)
        self.assertIn("def _load_safety_gates_ui(", SOURCE)
        routes = (ROOT / "biocore_model" / "plugin_routes.py").read_text(
            encoding="utf-8")
        self.assertIn('"boundary_enabled"', routes)
        self.assertIn('"crisis_safety_enabled"', routes)

    def test_status_payload_exposes_flags(self):
        self.assertIn('"boundary_enabled": bool(getattr(self, "boundary_enabled"',
                      SOURCE)
        self.assertIn('"crisis_safety_enabled": bool(', SOURCE)


class HelperTest(unittest.TestCase):
    class FakePlugin:
        def __init__(self, **flags):
            for key, value in flags.items():
                setattr(self, key, value)

    def test_all_off_passthrough(self):
        plugin = self.FakePlugin()
        self.assertEqual(GATE_APPLY(plugin, CRISIS_USER, DIAGNOSIS),
                         DIAGNOSIS)
        self.assertEqual(GATE_APPLY(plugin, "", REALITY), REALITY)

    def test_boundary_on_intercepts_and_logs(self):
        LOG.clear()
        plugin = self.FakePlugin(safety_enabled=True, boundary_enabled=True,
                                 crisis_safety_enabled=False)
        out = GATE_APPLY(plugin, "", DIAGNOSIS)
        self.assertNotEqual(out, DIAGNOSIS)
        self.assertNotIn("抑郁症", out)
        self.assertTrue(any("safety gate hit" in " ".join(map(str, row))
                            for row in LOG))

    def test_crisis_on_intercepts(self):
        plugin = self.FakePlugin(safety_enabled=True, boundary_enabled=False,
                                 crisis_safety_enabled=True)
        out = GATE_APPLY(plugin, CRISIS_USER, "别想太多")
        self.assertEqual(out, bg.CRISIS_PREFIX)

    def test_master_off_passthrough(self):
        plugin = self.FakePlugin(safety_enabled=False, boundary_enabled=True,
                                 crisis_safety_enabled=True)
        self.assertEqual(GATE_APPLY(plugin, CRISIS_USER, DIAGNOSIS),
                         DIAGNOSIS)


if __name__ == "__main__":
    unittest.main()
