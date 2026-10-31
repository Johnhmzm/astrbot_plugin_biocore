# -*- coding: utf-8 -*-
"""page/debug tests: field completeness, real attribute reads, error -> null."""
import ast
import asyncio
import json
import tempfile
import types
import unittest
from pathlib import Path

from biocore_model import intero_core as ic

MAIN = Path(__file__).resolve().parents[2] / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")


def _load_page_debug():
    tree = ast.parse(SOURCE)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "BioCorePlugin")
    node = next(f for f in cls.body
                if isinstance(f, ast.AsyncFunctionDef) and f.name == "page_debug")
    blocks = types.SimpleNamespace(
        BLOCKS=[types.SimpleNamespace(id="bio_emotion"),
                types.SimpleNamespace(id="bio_goal"),
                types.SimpleNamespace(id="runtime")],
        _enabled_map=lambda plugin: {"bio_emotion": True, "bio_goal": False, "runtime": True})
    ns = {"_bc_blocks": blocks,
          "PROFILE_PATH": Path("/data/persona_profile.json"),
          "DATA_DIR": Path("/data")}
    clone = ast.AsyncFunctionDef(name=node.name, args=node.args, body=node.body,
                                 decorator_list=[], returns=node.returns,
                                 type_comment=None, lineno=node.lineno,
                                 col_offset=node.col_offset, end_lineno=node.end_lineno,
                                 end_col_offset=node.end_col_offset)
    exec(compile(ast.Module(body=[clone], type_ignores=[]), "<page_debug>", "exec"), ns)
    return ns[node.name], ns


PAGE_DEBUG, NS = _load_page_debug()


class FakeCore:
    def __init__(self):
        self.intero = {"tension": 0.8, "warmth": 0.2, "heaviness": 0.5, "clarity": 0.4}
        self.needs = {"belonging": 0.4, "control": 0.6}
        self.pending_intent = {"action": "repair", "reason": "tension"}
        self.last_bio_tick_ts = 1700000000.0


class FakePlugin:
    def __init__(self, tmp):
        self.data_dir = str(tmp)
        self.cores = {"s1": FakeCore()}
        self._life_tick_n = 42
        self._policy_pending = {"ctx": "expect|secure|day"}

    def _load_policy_q(self):
        return {"expect|secure|day": {"q": 0.1}, "protest|secure|day": {"q": 0.2}}


class PageDebugTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.plugin = FakePlugin(self.tmp.name)
        from biocore_model import ui_settings
        ui_settings.save(self.plugin, {"autonomy": {"accumulator": {
            "V": 0.3, "theta": 0.55, "ticks_since_fire": 2}}})

    def tearDown(self):
        self.tmp.cleanup()

    async def _payload(self):
        return await PAGE_DEBUG(self.plugin)

    async def test_all_fields_present_and_json_safe(self):
        out = await self._payload()
        self.assertEqual(out["status"], "ok")
        data = out["data"]
        for key in ("loop", "bio", "autonomy", "paths", "blocks", "pipeline", "policy"):
            self.assertIn(key, data)
        json.dumps(out)  # must be serialisable

    async def test_loop_reads_live_counter(self):
        data = (await self._payload())["data"]
        self.assertEqual(data["loop"]["count"], 42)
        self.assertEqual(data["loop"]["interval_s"], 10)
        self.assertEqual(data["loop"]["last_tick_ts"], 1700000000.0)

    async def test_bio_reads_core(self):
        data = (await self._payload())["data"]
        expected = ic.discomfort(self.plugin.cores["s1"].intero)["total"]
        self.assertAlmostEqual(data["bio"]["discomfort"], expected)
        self.assertEqual(data["bio"]["pending_intent"]["action"], "repair")
        self.assertEqual(data["bio"]["needs"]["belonging"], 0.4)
        self.assertEqual(data["bio"]["intero"]["tension"], 0.8)

    async def test_autonomy_accumulator(self):
        data = (await self._payload())["data"]
        self.assertEqual(data["autonomy"]["V"], 0.3)
        self.assertEqual(data["autonomy"]["theta"], 0.55)
        self.assertEqual(data["autonomy"]["ticks_since_fire"], 2)

    async def test_paths_use_authority_settings_file(self):
        data = (await self._payload())["data"]
        self.assertTrue(data["paths"]["settings"].endswith("ui_settings.json"))
        self.assertIn("persona_profile.json", data["paths"]["profile"])
        self.assertTrue(data["paths"]["data_dir"])

    async def test_blocks_and_pipeline_and_policy(self):
        data = (await self._payload())["data"]
        self.assertEqual(data["blocks"]["enabled"], ["bio_emotion", "runtime"])
        self.assertEqual(data["blocks"]["skipped"], ["bio_goal"])
        self.assertIn(data["pipeline"]["mode"], ("shadow", "active"))
        self.assertIsInstance(data["pipeline"]["last_trace"], dict)
        self.assertEqual(data["policy"]["q_size"], 2)
        self.assertEqual(data["policy"]["last_ctx"], "expect|secure|day")

    async def test_failures_degrade_to_null_not_crash(self):
        plugin = FakePlugin(self.tmp.name)
        plugin._life_tick_n = None

        def boom(*args, **kwargs):
            raise RuntimeError("boom")

        plugin._load_policy_q = boom
        plugin._policy_pending = None
        old = NS["_bc_blocks"]
        NS["_bc_blocks"] = types.SimpleNamespace(
            BLOCKS=[types.SimpleNamespace(id="bio_emotion")],
            _enabled_map=boom)
        try:
            out = await PAGE_DEBUG(plugin)
        finally:
            NS["_bc_blocks"] = old
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["data"]["policy"], {"q_size": None, "last_ctx": None})
        self.assertEqual(out["data"]["blocks"], {"enabled": [], "skipped": []})
        json.dumps(out)

    async def test_route_registered(self):
        self.assertIn("/astrbot_plugin_biocore/page/debug", SOURCE)
        self.assertIn("self.page_debug", SOURCE)


if __name__ == "__main__":
    unittest.main()
