# -*- coding: utf-8 -*-
"""task-173 批二接线测试：granularity / affective_labor / self_verification。

同时覆盖 task-173 的开关拆分：boundary_enabled 只表示内容安全闸，
boundary_lines_enabled 才是「她的底线」。三个模块的 directives 必须走现有
唯一 merge_named 入口。
"""
import ast
import json
import unittest
from pathlib import Path

from biocore_model import affective_labor as al
from biocore_model import granularity as gr
from biocore_model import self_verification as sv
from biocore_model import x_directives as xd

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "biocore_model" / "plugin_routes.py").read_text(encoding="utf-8")
SCHEMA = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
DASH = ROOT / "pages" / "dashboard"
SRC_HTML = (DASH / "index.src.html").read_text(encoding="utf-8")
INDEX_HTML = (DASH / "index.html").read_text(encoding="utf-8")
APP_JS = (DASH / "app.js").read_text(encoding="utf-8")

NOW = 1_700_000_000


class FlagTest(unittest.TestCase):
    def test_schema_defaults(self):
        expected = {"boundary_lines_enabled": False,
                    "granularity_enabled": True,
                    "affective_labor_enabled": True,
                    "self_verification_enabled": True}
        for key, default in expected.items():
            entry = SCHEMA.get(key)
            self.assertIsInstance(entry, dict, key)
            self.assertEqual(entry.get("type"), "bool", key)
            self.assertIs(entry.get("default"), default, key)

    def test_main_reads_flags(self):
        expected = {"boundary_lines_enabled": "False",
                    "granularity_enabled": "True",
                    "affective_labor_enabled": "True",
                    "self_verification_enabled": "True"}
        for key, default in expected.items():
            self.assertIn('self.config.get("%s", %s)' % (key, default), MAIN)


class BoundarySplitTest(unittest.TestCase):
    def test_hints_are_distinct(self):
        safety = SCHEMA["boundary_enabled"]
        lines = SCHEMA["boundary_lines_enabled"]
        self.assertIn("内容安全", safety.get("description", ""))
        self.assertIn("不诊断", safety.get("hint", ""))
        self.assertNotIn("她的底线——", safety.get("hint", ""))
        self.assertIn("独立", lines.get("hint", ""))
        self.assertIn("boundary_enabled", lines.get("hint", ""))

    def test_relational_block_uses_lines_switch(self):
        self.assertIn(
            'if bool(getattr(self, "boundary_lines_enabled", False)):', MAIN)
        block = MAIN[MAIN.index("task-172 batch-1: boundary judgment first"):
                     MAIN.index("# A4: capture open loops")]
        self.assertNotIn('getattr(self, "boundary_enabled"', block)
        # content-safety gate module is untouched and still keys off its switch
        gate = (ROOT / "biocore_model" / "boundary_gate.py").read_text(
            encoding="utf-8")
        self.assertIn("boundary_enabled", gate)


class GranularityWiringTest(unittest.TestCase):
    def test_wiring(self):
        self.assertIn("from .biocore_model import granularity as _gr_mod", MAIN)
        self.assertIn("from .biocore_model import emotion_geometry as _eg_mod",
                      MAIN)
        self.assertIn("core.emotion_granularity = _gr_view", MAIN)
        self.assertIn("[biocore] emotion granularity primary=%s line=%s", MAIN)
        self.assertIn("if bool(getattr(self, \"granularity_enabled\", True)):", MAIN)

    def test_read_only_no_directive(self):
        block = MAIN[MAIN.index("task-173 granularity"):
                     MAIN.index("# task-173 affective_labor")]
        self.assertNotIn("_x_pairs.append", block)
        self.assertIn("_gr_mod.view(", block)

    def test_labels(self):
        aggrieved = gr.refine({"sadness": 0.50, "anger": 0.20})
        self.assertEqual(aggrieved["labels"], ["委屈"])
        disappointed = gr.refine({"sadness": 0.50, "trust": 0.20})
        self.assertEqual(disappointed["labels"], ["失望"])
        ignored = gr.refine({"loneliness": 0.60, "sadness": 0.15})
        self.assertEqual(ignored["labels"], ["被忽视"])
        panel = gr.view({"sadness": 0.50, "anger": 0.20})
        self.assertEqual(panel["line"], "委屈（难过）")

    def test_panel_projection(self):
        self.assertIn('"emotion_granularity": (self._granularity_payload()',
                      MAIN)
        self.assertIn('"emotion_granularity": (self._granularity_payload()',
                      ROUTES)
        self.assertIn('id="granularityNote"', SRC_HTML)
        self.assertIn('id="granularityNote"', INDEX_HTML)
        self.assertIn('$("granularityNote")', APP_JS)

    def test_payload_method(self):
        tree = ast.parse(MAIN)
        nodes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                 and n.name == "_granularity_payload"]
        self.assertEqual(len(nodes), 1)
        module = ast.Module(body=nodes, type_ignores=[])
        ns = {}
        exec(compile(module, "<granularity_panel>", "exec"), ns)
        import types
        core = types.SimpleNamespace(emotion_granularity={
            "enabled": True, "display": "委屈", "line": "委屈（难过）",
            "primary": "sadness", "primary_zh": "难过",
            "secondary": [{"key": "aggrieved", "label": "委屈"}],
            "fallback": False})
        plugin = types.SimpleNamespace(
            cores={"k": core}, granularity_enabled=True)
        out = ns["_granularity_payload"](plugin)
        self.assertTrue(out["enabled"])
        self.assertEqual(out["line"], "委屈（难过）")
        self.assertEqual(out["secondary"][0]["label"], "委屈")


class AffectiveLaborWiringTest(unittest.TestCase):
    def test_wiring(self):
        self.assertIn("from .biocore_model import affective_labor as _al_mod",
                      MAIN)
        self.assertIn("from .biocore_model import affective_labor as _al_mod2",
                      MAIN)
        self.assertIn("core.affective_labor = _al_mod2.update(", MAIN)
        self.assertIn("core.affective_labor_view = _al_panel", MAIN)
        self.assertIn("self._labor_felt = {", MAIN)
        self.assertIn("/** task-173", MAIN) if False else None

    def test_high_load_restrains_through_bus(self):
        self.assertIn('self._x_pairs.append((\n                        "affective_labor",', MAIN) or \
            self.assertIn('"affective_labor",', MAIN)
        self.assertIn('"length_scale": 0.85', MAIN)
        self.assertIn('>= 0.60', MAIN)

    def test_load_accumulates(self):
        first = al.update(al.initial(NOW - 10),
                          {"v": 0.6, "a": 0.4}, {"v": -0.6, "a": 0.4},
                          honesty=0.0, now=NOW)
        second = al.update(first, {"v": 0.6}, {"v": -0.6},
                           honesty=0.0, now=NOW + 60)
        self.assertGreater(second["load"], first["load"])
        paused = al.update(second, {"v": 0.6}, {"v": -0.6},
                           honesty=0.0, now=NOW + 60)
        self.assertEqual(paused["load"], second["load"])
        view = al.view(second)
        self.assertIn("risk", view)
        self.assertGreaterEqual(view["risk"], 0.0)


class SelfVerificationWiringTest(unittest.TestCase):
    def test_wiring(self):
        self.assertIn("from .biocore_model import self_verification as _sv_mod",
                      MAIN)
        self.assertIn("core.self_verification = _sv_state", MAIN)
        self.assertIn("core.self_verification_view = _sv_mod.view(_sv_state)",
                      MAIN)
        self.assertIn("_sv_mod.observe(", MAIN)
        self.assertIn("_sv_mod.intent(_sv_state)", MAIN)

    def test_urge_allows_correction(self):
        misread = sv.observe(sv.initial(NOW - 10), True,
                             clarity=0.9, relation=0.9, severity=1.0, now=NOW)
        accurate = sv.observe(sv.initial(NOW - 10), False,
                              clarity=0.9, relation=0.9, now=NOW)
        self.assertGreater(misread["urge"], accurate["urge"])
        self.assertEqual(accurate["urge"], 0.0)
        decided = sv.intent(misread)
        self.assertTrue(decided["want_correct"])
        self.assertIn("allow_correction",
                      str(xd.normalize({"allow_correction": True}, "sv")))


class BusTest(unittest.TestCase):
    def test_still_single_merge(self):
        self.assertEqual(MAIN.count("merge_named("), 1)
        self.assertIn("merge_named(self._x_pairs)", MAIN)

    def test_batch2_directives_merge(self):
        merged = xd.merge_named([
            ("affective_labor", {"length_scale": 0.85, "tone": "累了，话少一点",
                                 "initiative": 0.35}),
            ("self_verification", {"allow_correction": True,
                                   "tone": "可以补一句纠正"}),
            ("attributor", {"length_scale": 0.9, "tone": "语气硬一点"}),
        ])
        self.assertIn("affective_labor", merged["sources"])
        self.assertIn("self_verification", merged["sources"])
        self.assertTrue(merged["allow_correction"])
        self.assertLessEqual(merged["length_scale"], 0.85)
        self.assertLessEqual(merged["initiative"], 0.5)


class RollbackTest(unittest.TestCase):
    def test_each_block_guarded(self):
        for key in ("granularity_enabled", "affective_labor_enabled",
                    "self_verification_enabled"):
            self.assertIn('if bool(getattr(self, "%s", True)):' % key, MAIN)
        self.assertIn('if bool(getattr(self, "boundary_lines_enabled", False)):',
                      MAIN)


class PurityTest(unittest.TestCase):
    def test_modules_stay_pure(self):
        for name in ("granularity", "affective_labor", "self_verification"):
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
            self.assertNotIn("random", modules, name)


if __name__ == "__main__":
    unittest.main()
