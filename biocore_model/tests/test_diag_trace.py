# -*- coding: utf-8 -*-
"""task-171 只读诊断单测：状态差/提示词差/记录有界/落盘规则/面板投射。

纯函数行为 + main.py 接线源码断言；不导入 AstrBot。
"""
import ast
import json
import unittest
from pathlib import Path

from biocore_model import diag_trace as dt

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "biocore_model" / "plugin_routes.py").read_text(encoding="utf-8")
SCHEMA = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
DASH = ROOT / "pages" / "dashboard"
SRC_HTML = (DASH / "index.src.html").read_text(encoding="utf-8")
INDEX_HTML = (DASH / "index.html").read_text(encoding="utf-8")
APP_JS = (DASH / "app.js").read_text(encoding="utf-8")


class SnapshotDiffTest(unittest.TestCase):
    def test_snapshot_keys_and_rounding(self):
        class Core:
            v = 0.123456
            stress = 0.4
        snap = dt.state_snapshot(Core())
        self.assertIn("v", snap)
        self.assertEqual(snap["v"], 0.1235)
        self.assertEqual(set(snap), set(dt.SNAPSHOT_KEYS))
        self.assertTrue(all(isinstance(value, float) for value in snap.values()))

    def test_snapshot_reads_nested_needs(self):
        snap = dt.state_snapshot({"v": 0.1, "needs": {"belonging": 0.7}})
        self.assertEqual(snap["belonging"], 0.7)
        self.assertEqual(snap["v"], 0.1)

    def test_diff_only_moved_values(self):
        before = {"v": 0.1, "stress": 0.2, "energy": 0.5}
        after = {"v": 0.15, "stress": 0.2, "energy": 0.44}
        delta = dt.diff_state(before, after)
        self.assertEqual(set(delta), {"v", "energy"})
        self.assertEqual(delta["v"], 0.05)
        self.assertEqual(delta["energy"], -0.06)

    def test_diff_empty_when_same(self):
        snap = {"v": 0.1, "a": 0.2}
        self.assertEqual(dt.diff_state(snap, dict(snap)), {})


class PromptDiffTest(unittest.TestCase):
    def test_unchanged(self):
        diff = dt.prompt_diff("a\nb", "a\nb")
        self.assertFalse(diff["changed"])
        self.assertEqual(diff["chars_delta"], 0)
        self.assertEqual(diff["preview"], "")

    def test_changed_counts(self):
        diff = dt.prompt_diff("a\nb", "a\nb\nc")
        self.assertTrue(diff["changed"])
        self.assertEqual(diff["chars_delta"], 2)
        self.assertEqual(diff["lines_added"], 1)
        self.assertEqual(diff["lines_removed"], 0)
        self.assertTrue(diff["preview"])

    def test_preview_bounded(self):
        diff = dt.prompt_diff("a", "b" * 500)
        self.assertLessEqual(len(diff["preview"]), dt.PREVIEW_CHARS)


class BuildTest(unittest.TestCase):
    def _record(self, **overrides):
        kwargs = dict(
            before={"v": 0.1, "stress": 0.2}, after={"v": 0.2, "stress": 0.2},
            intent={"top": "要你陪", "intents": [
                {"kind": "要你陪", "weight": 0.7, "reason": "有点空"},
                {"kind": "自己待着", "weight": 0.3, "reason": "累"}],
                "motivation": "想让他陪一会儿", "self_weight": 0.7,
                "drive": 0.5, "urge": 0.35, "satisfaction": -0.1,
                "candidates": [{"kind": "要你陪", "score": 0.8},
                               {"kind": "顺着你", "score": 0.2}]},
            metacog={"band": "low", "confidence": 0.3, "converge": False,
                     "allow_self_correction": False, "reason": "把握不大"},
            pending_prompts=["该问一句：体检"], voice_phrases=["少来。"],
            length={"scale": 0.8, "brevity": "short", "source": "metacog"},
            hints={"strategy": "hint", "prospective": "p", "voice": "v",
                   "metacog": "m"},
            prompt={"changed": True, "chars": 120, "chars_delta": 12,
                    "lines_added": 1, "lines_removed": 0, "preview": "x"},
            session="s1", ts=100.0, turn=3, latency_ms=123.4,
            text_chars=8, switches={"diag_trace_enabled": True})
        kwargs.update(overrides)
        return dt.build(**kwargs)

    def test_record_contract(self):
        rec = self._record()
        for key in ("ts", "session", "turn", "state_delta", "intent",
                    "candidates", "metacog", "length", "hints", "prompt",
                    "switches", "latency_ms"):
            self.assertIn(key, rec)
        self.assertEqual(rec["turn"], 3)
        self.assertEqual(rec["state_delta"], {"v": 0.1})
        self.assertEqual(rec["intent"]["top"], "要你陪")
        self.assertEqual(rec["intent"]["weight"], 0.7)
        self.assertEqual(rec["intent"]["reason"], "有点空")
        self.assertEqual(rec["length"]["source"], "metacog")
        self.assertEqual(rec["candidates"][0]["kind"], "要你陪")

    def test_record_bounds(self):
        rec = self._record(session="s" * 500, pending_prompts=["p" * 500] * 9,
                           voice_phrases=["v" * 500] * 9,
                           hints={"strategy": "h" * 900})
        self.assertEqual(len(rec["session"]), 80)
        self.assertEqual(len(rec["pending_prompts"]), 3)
        self.assertLessEqual(len(rec["pending_prompts"][0]), 60)
        self.assertEqual(len(rec["voice_phrases"]), 2)
        self.assertLessEqual(len(rec["hints"]["strategy"]), 140)

    def test_record_garbage_safe(self):
        rec = dt.build(before="x", after=3, intent="no", metacog=None,
                       pending_prompts="no", length="no", prompt=7)
        self.assertEqual(rec["state_delta"], {})
        self.assertEqual(rec["intent"]["top"], "")
        self.assertEqual(rec["length"]["scale"], 1.0)

    def test_render_text_bounded(self):
        text = dt.render_text(self._record())
        self.assertLessEqual(len(text), dt.TEXT_CHARS)
        self.assertIn("turn=3", text)
        self.assertIn("intent=要你陪", text)
        self.assertIn("len=0.80", text)
        self.assertIn("prompt=chars120", text)
        self.assertEqual(dt.render_text("nope"), "")


class RowsTest(unittest.TestCase):
    def test_append_keeps_newest_50(self):
        rows = [{"turn": i} for i in range(60)]
        out = dt.append(rows, {"turn": 60}, limit=50)
        self.assertEqual(len(out), 50)
        self.assertEqual(out[-1]["turn"], 60)
        self.assertEqual(out[0]["turn"], 11)

    def test_view_newest_first(self):
        rows = [{"turn": i} for i in range(1, 6)]
        view = dt.view(rows, limit=3)
        self.assertEqual([row["turn"] for row in view], [5, 4, 3])

    def test_append_ignores_garbage(self):
        out = dt.append(["x", None, {"turn": 1}], "nope", limit=50)
        self.assertEqual(out, [{"turn": 1}])


class PurityAndWiringTest(unittest.TestCase):
    def test_pure_module_imports(self):
        tree = ast.parse((ROOT / "biocore_model" / "diag_trace.py")
                         .read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
        self.assertEqual(modules, {"__future__"})

    def test_schema_flag_default_off(self):
        entry = SCHEMA.get("diag_trace_enabled")
        self.assertIsInstance(entry, dict)
        self.assertEqual(entry.get("type"), "bool")
        self.assertIs(entry.get("default"), False)

    def test_main_wiring(self):
        self.assertIn('self.config.get("diag_trace_enabled", False)', MAIN)
        self.assertIn("diag_trace as _diag_mod", MAIN)
        self.assertIn("_diag_mod3.build(", MAIN)
        self.assertIn("_diag_trace_write(", MAIN)
        self.assertIn('DATA_DIR / "trace.jsonl"', MAIN)
        self.assertIn("self._diag_pending", MAIN)
        self.assertIn("[biocore] diag ", MAIN)
        self.assertIn("diag_trace_enabled", MAIN)

    def test_status_projection(self):
        self.assertIn('"diag_trace": (self._diag_trace_payload()', MAIN)
        self.assertIn('"diag_trace": (self._diag_trace_payload()', ROUTES)
        self.assertIn("self._diag_trace_rows(5)", MAIN)

    def test_dashboard_page(self):
        for text in (SRC_HTML, INDEX_HTML):
            self.assertIn('data-session-tab="diag"', text)
            self.assertIn('id="sessionPanelDiag"', text)
            self.assertIn('id="diagRows"', text)
            self.assertIn("这一轮为什么", text)
        self.assertIn("function renderDiagTrace()", APP_JS)
        self.assertIn('$("diagRows")', APP_JS)
        self.assertIn("renderDiagTrace();", APP_JS)
        self.assertIn("data.diag_trace", APP_JS)


if __name__ == "__main__":
    unittest.main()
