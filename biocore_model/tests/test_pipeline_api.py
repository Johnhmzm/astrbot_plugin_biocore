# -*- coding: utf-8 -*-
"""PIPE-3 pipeline API tests: status, toggle, persistence, dry-run, routes."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from biocore_model import pipeline_api as pa
from biocore_model import runtime as rt


class FakePlugin:
    def __init__(self, data_dir, pipeline_mode="shadow"):
        self.data_dir = str(data_dir)
        self.pipeline_mode = pipeline_mode


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.plugin = FakePlugin(self.tmp)
        rt.reset_pipeline()
        rt.apply_switches({})
        pa.reset_boot()

    def tearDown(self):
        rt.apply_switches({})
        rt.reset_pipeline()
        pa.reset_boot()
        self._tmp.cleanup()

    def settings(self):
        return json.loads((self.tmp / "ui_settings.json").read_text(encoding="utf-8"))


class StatusTest(Base):
    def test_status_payload_structure(self):
        payload = pa.payload_status(self.plugin)
        for key in ("mode", "stages", "last_trace", "updated_ts", "schema", "switches"):
            self.assertIn(key, payload)
        self.assertEqual(payload["mode"], "shadow")
        self.assertEqual(len(payload["stages"]), 11)
        for row in payload["stages"]:
            self.assertEqual(set(row), {"name", "required", "enabled",
                                        "last_status", "last_ms"})

    def test_status_stage_order_matches_runtime(self):
        payload = pa.payload_status(self.plugin)
        self.assertEqual([row["name"] for row in payload["stages"]],
                         list(rt.get_pipeline().names()))

    def test_status_updated_ts_and_schema(self):
        payload = pa.payload_status(self.plugin)
        self.assertIsInstance(payload["updated_ts"], float)
        self.assertEqual(payload["schema"], pa.SCHEMA)

    def test_status_reflects_applied_switches(self):
        rt.apply_switches({"memory": False})
        payload = pa.payload_status(self.plugin)
        rows = {row["name"]: row for row in payload["stages"]}
        self.assertFalse(rows["memory"]["enabled"])
        self.assertFalse(payload["switches"]["memory"])


class ToggleTest(Base):
    def test_toggle_non_required_ok(self):
        result = pa.payload_toggle(self.plugin, "expr_intent", False)
        self.assertTrue(result["ok"])
        self.assertTrue(result["saved"])
        rows = {row["name"]: row for row in result["stages"]}
        self.assertFalse(rows["expr_intent"]["enabled"])

    def test_toggle_required_rejected(self):
        for name in pa.REQUIRED_STAGES:
            result = pa.payload_toggle(self.plugin, name, False)
            self.assertFalse(result["ok"], name)
            self.assertEqual(result["message"], "required_stage")
            rows = {row["name"]: row for row in result["stages"]}
            self.assertTrue(rows[name]["enabled"])

    def test_toggle_think_rejected(self):
        result = pa.payload_toggle(self.plugin, "think", False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "required_stage")

    def test_toggle_unknown_stage(self):
        result = pa.payload_toggle(self.plugin, "nope", True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "unknown_stage")

    def test_toggle_name_required(self):
        result = pa.payload_toggle(self.plugin, "", True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "name_required")

    def test_toggle_persists_to_ui_settings(self):
        pa.payload_toggle(self.plugin, "expr_tone", False)
        data = self.settings()
        stages = data["autonomy"]["pipeline_stages"]
        self.assertFalse(stages["expr_tone"])
        self.assertEqual(data["schema"], 1)

    def test_persistence_reload(self):
        pa.payload_toggle(self.plugin, "memory", False)
        pa.reset_boot()
        rt.reset_pipeline()
        other = FakePlugin(self.tmp)
        payload = pa.payload_status(other)
        rows = {row["name"]: row for row in payload["stages"]}
        self.assertFalse(rows["memory"]["enabled"])

    def test_switches_roundtrip(self):
        saved = pa.save_switches(self.plugin, {"memory": False, "bio": True})
        self.assertTrue(saved["ok"])
        self.assertEqual(pa.load_switches(self.plugin),
                         {"memory": False, "bio": True})

    def test_boot_is_idempotent(self):
        pa.reset_boot()
        self.assertTrue(pa.boot(self.plugin))
        self.assertFalse(pa.boot(self.plugin))


class DryrunTest(Base):
    def test_dryrun_structure(self):
        result = pa.payload_dryrun(self.plugin, "今天有点累", now=1000.0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "dryrun")
        self.assertEqual(result["stages"], 11)
        self.assertEqual(len(result["trace"]["stages"]), 11)
        self.assertTrue(result["out_preview"])
        self.assertIsNone(result["error"])

    def test_dryrun_empty_text(self):
        result = pa.payload_dryrun(self.plugin, "   ")
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "sample_text_required")

    def test_dryrun_has_no_side_effects(self):
        captured = {}

        def fake_make_ctx(**kwargs):
            captured.update(kwargs)
            return {"meta": {"dryrun": True, "write_core": False,
                             "observe": False, "llm": None, "now": 1000.0},
                    "text": kwargs.get("text") or "", "trace": {"stages": []}}

        with mock.patch.object(rt, "make_request_ctx", side_effect=fake_make_ctx), \
                mock.patch.object(rt, "run_reply", return_value={
                    "trace": {"stages": []}, "reply": "", "state_text": "状态块",
                    "meta": {"dryrun": True}}):
            result = pa.payload_dryrun(self.plugin, "样例", now=1000.0)
        self.assertTrue(result["ok"])
        self.assertIsNone(captured.get("core"))
        meta = captured.get("meta")
        self.assertTrue(meta["dryrun"])
        self.assertFalse(meta["write_core"])
        self.assertFalse(meta["observe"])
        self.assertIsNone(meta["llm"])
        self.assertFalse((self.tmp / "ui_settings.json").exists())

    def test_dryrun_does_not_create_settings_file(self):
        pa.payload_dryrun(self.plugin, "你好", now=5.0)
        self.assertFalse((self.tmp / "ui_settings.json").exists())


class RouteTest(unittest.TestCase):
    def test_main_routes_and_auth_present(self):
        root = Path(__file__).resolve().parent.parent.parent
        source = (root / "main.py").read_text(encoding="utf-8")
        for path in ('/page/pipeline"', '/page/pipeline_toggle"',
                     '/page/pipeline_dryrun"'):
            self.assertIn(path, source)
        self.assertIn("self.page_pipeline, [\"GET\"]", source)
        self.assertIn("self.page_pipeline_toggle, [\"POST\"]", source)
        self.assertIn("self.page_pipeline_dryrun, [\"POST\"]", source)
        self.assertGreaterEqual(source.count("_pa.payload_dryrun"), 1)
        toggle_block = source.split("async def page_pipeline_toggle", 1)[1].split(
            "async def page_pipeline_dryrun", 1)[0]
        dry_block = source.split("async def page_pipeline_dryrun", 1)[1].split(
            "async def generate_manual_insight", 1)[0]
        self.assertIn("_page_is_local_admin", toggle_block)
        self.assertIn("_page_is_local_admin", dry_block)
        status_block = source.split("async def page_pipeline(self)", 1)[1].split(
            "async def page_pipeline_toggle", 1)[0]
        self.assertIn("payload_status", status_block)


if __name__ == "__main__":
    unittest.main()
