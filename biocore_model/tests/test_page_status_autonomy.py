# -*- coding: utf-8 -*-
"""page_status autonomy: fake plugin variants ensure data.autonomy.state carries V/theta.

Regression for the live bug: when self.data_dir is missing at page_status time,
ui_settings.base_dir fell back to an old directory whose accumulator had None
values, overwriting the real state. The fix resolves the authority dir from
_data_dir/DATA_DIR and merges the accumulator outside the state try-block.
"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from biocore_model import plugin_routes as routes
from biocore_model import ui_settings


class FakeCore:
    def snapshot(self): return {"v": 0.0, "a": 0.4}
    def intent(self): return {}
    def load_state(self, state): return None
    def autonomy_state(self, relationship=None, now=None, persist=True):
        return {"enabled": True, "ready": False, "V": 0.71, "theta": 0.60}


class FakePlugin(routes.RoutesMixin):
    def __init__(self, data_dir, *, with_data_dir=True, state_attr="method",
                 state_raises=False):
        self._tmp = data_dir
        if with_data_dir:
            self.data_dir = str(data_dir)
        self._data_dir = data_dir
        self.context = type("Ctx", (), {"persona_manager": None})()
        self.cores = {}                       # empty cores
        self.profile = {}
        self.persona_text = ""
        self.self_model = {}
        self.enabled = True
        self.inject_intent = True
        self.proactive_reply = False
        self.proactive_autonomy = False
        self.proactive_send = False
        self.memory_dedup_embedding = True
        self._migration_note = ""
        if state_attr == "method":
            if state_raises:
                def _state():
                    raise RuntimeError("state source down")
            else:
                def _state():
                    return {"source": "method"}
            self._autonomy_readonly_state = _state
        self._relationship_of = lambda data=None: {}
        self._working_set_preview = lambda key: {}
        self._ensure_autonomy_task = lambda: None
        self._functions_public = lambda: {}
        self._llm_provider_options = lambda: []
        self._public_api_config = lambda: {}
        self._memory_stats = lambda: {}
        self._decayed_merge_count = lambda *a, **k: 0
        self._event_archive = lambda *a, **k: []
        self._insights = lambda *a, **k: []
        self._astrbot_llm_default = lambda: None
        self._astrbot_embedding_default = lambda: None
        self._astrbot_rerank_default = lambda: None
        self._astrbot_tts_default = lambda: None
        self._astrbot_image_default = lambda: None
        async def _kb_available(): return False
        self._kb_available = _kb_available


class PageStatusAutonomyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.authority = self.tmp / "plugin_data" / "astrbot_plugin_biocore"
        self.authority.mkdir(parents=True, exist_ok=True)
        (self.authority / "ui_settings.json").write_text(json.dumps({
            "autonomy": {"accumulator": {"V": 0.2838, "theta": 0.55,
                                         "ticks_since_fire": 3}},
            "schema": 1}, ensure_ascii=False), encoding="utf-8")
        routes.DATA_DIR = self.authority
        routes.MEMORY_DIR = self.tmp / "memory"
        routes.STATE_DIR = self.tmp / "states"
        routes.USER_DIR = self.tmp / "users"
        routes.DEFAULT_PROFILE = {}
        routes.DEFAULT_MEMORY_TRACE = {}
        routes._memory_index_rows = lambda *a, **k: []
        routes._relationship_rows = lambda *a, **k: []
        routes.LLM_FUNCTIONS = ()
        routes.LLM_FUNCTION_DEFAULTS = {}
        for folder in (routes.MEMORY_DIR, routes.STATE_DIR, routes.USER_DIR):
            folder.mkdir(parents=True, exist_ok=True)
        # isolate from the real instance layout for attr-based tests
        self._orig_module_file = routes._MODULE_FILE
        routes._MODULE_FILE = (self.tmp / "no_instance" / "plugins" / "x"
                               / "biocore_model" / "plugin_routes.py")

    def tearDown(self):
        routes._MODULE_FILE = self._orig_module_file
        self._tmp.cleanup()

    def _run(self, plugin):
        out = asyncio.run(plugin.page_status())
        self.assertEqual(out.get("status"), "ok")
        return out["data"]["autonomy"]

    def test_data_dir_set_and_state_attr_is_method(self):
        plugin = FakePlugin(self.authority, with_data_dir=True, state_attr="method")
        path = routes._authority_settings_path(plugin)
        self.assertEqual(Path(str(path)), self.authority / "ui_settings.json")
        automation = self._run(plugin)
        self.assertEqual(set(automation), {"enabled", "send", "state", "_debug"})
        state = automation["state"]
        self.assertEqual(state["V"], 0.2838)
        self.assertEqual(state["theta"], 0.55)
        self.assertEqual(state["ticks_since_fire"], 3)

    def test_data_dir_missing_falls_back_to_authority(self):
        plugin = FakePlugin(self.authority, with_data_dir=False, state_attr="method")
        path = routes._authority_settings_path(plugin)
        self.assertEqual(Path(str(path)), self.authority / "ui_settings.json")
        state = self._run(plugin)["state"]
        self.assertEqual(state["V"], 0.2838)
        self.assertEqual(state["theta"], 0.55)

    def test_stale_data_dir_reads_injected_authority(self):
        stale = self.tmp / "stale_A"
        stale.mkdir(parents=True, exist_ok=True)
        (stale / "ui_settings.json").write_text(json.dumps({
            "autonomy": {"accumulator": {"V": None, "theta": None,
                                         "ticks_since_fire": None}}},
            ensure_ascii=False), encoding="utf-8")
        plugin = FakePlugin(self.authority, with_data_dir=False, state_attr="method")
        plugin.data_dir = str(stale)          # stale data_dir must not win
        state = self._run(plugin)["state"]
        self.assertEqual(state["V"], 0.2838)
        self.assertEqual(state["theta"], 0.55)
        self.assertIsNotNone(state["ticks_since_fire"])

    def test_state_source_failure_still_merges_accumulator(self):
        plugin = FakePlugin(self.authority, with_data_dir=False, state_attr="method",
                            state_raises=True)
        state = self._run(plugin)["state"]
        self.assertEqual(state["V"], 0.2838)
        self.assertEqual(state["theta"], 0.55)

    def test_authority_file_survives_old_accumulator_none(self):
        old = self.tmp / "old_A"
        old.mkdir(parents=True, exist_ok=True)
        (old / "ui_settings.json").write_text(json.dumps({
            "autonomy": {"accumulator": {"V": None, "theta": None,
                                         "ticks_since_fire": None}}},
            ensure_ascii=False), encoding="utf-8")
        plugin = FakePlugin(self.authority, with_data_dir=False, state_attr="method")
        state = self._run(plugin)["state"]
        self.assertEqual(state["V"], 0.2838)
        self.assertIsNotNone(state["theta"])


    def test_module_candidates_follow_instance_layout(self):
        data_root = self.tmp / "inst" / "core" / "data"
        mod_file = (data_root / "plugins" / "astrbot_plugin_biocore_standalone"
                    / "biocore_model" / "plugin_routes.py")
        routes._MODULE_FILE = mod_file
        candidates = routes._module_candidate_paths()
        self.assertEqual(Path(str(candidates[0])).resolve(),
                         (data_root / "plugin_data" / "astrbot_plugin_biocore"
                          / "ui_settings.json").resolve())
        self.assertEqual(Path(str(candidates[1])).resolve(),
                         (data_root / "plugins" / "astrbot_plugin_biocore_standalone"
                          / "data" / "ui_settings.json").resolve())

    def test_real_instance_authority_file(self):
        authority = None
        base = Path.home() / ".astrbot_launcher" / "instances"
        for candidate in sorted(base.glob(
                "*/core/data/plugin_data/astrbot_plugin_biocore/ui_settings.json")):
            if candidate.is_file():
                authority = candidate
                break
        if authority is None:
            self.skipTest("no real AstrBot instance ui_settings.json")
        data_root = authority.parents[2]      # .../core/data
        routes._MODULE_FILE = (data_root / "plugins" / "astrbot_plugin_biocore_standalone"
                               / "biocore_model" / "plugin_routes.py")
        candidates = routes._module_candidate_paths()
        self.assertEqual(candidates[0], authority)
        self.assertTrue(candidates[0].exists())
        acc = routes._read_accumulator(candidates[0])
        self.assertTrue(acc)
        self.assertTrue(any(value is not None for value in acc.values()))

    def test_debug_field_reports_used_candidate(self):
        data_root = self.tmp / "inst_debug" / "core" / "data"
        authority = data_root / "plugin_data" / "astrbot_plugin_biocore"
        authority.mkdir(parents=True, exist_ok=True)
        (authority / "ui_settings.json").write_text(json.dumps({
            "autonomy": {"accumulator": {"V": 0.2838, "theta": 0.55}},
            "schema": 1}, ensure_ascii=False), encoding="utf-8")
        routes._MODULE_FILE = (data_root / "plugins" / "x"
                               / "biocore_model" / "plugin_routes.py")
        plugin = FakePlugin(self.authority, with_data_dir=False, state_attr="method")
        automation = self._run(plugin)
        self.assertEqual(automation["state"]["V"], 0.2838)
        debug = automation["_debug"]
        self.assertEqual(debug["used"], debug["candidates"][0])
        self.assertTrue(debug["exists"][0])
        self.assertIn("V", debug["acc_keys"])
        self.assertIn("theta", debug["acc_keys"])


if __name__ == "__main__":
    unittest.main()
