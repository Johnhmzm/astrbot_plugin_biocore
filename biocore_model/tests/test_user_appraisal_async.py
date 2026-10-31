# -*- coding: utf-8 -*-
"""Async user appraisal: non-blocking schedule, idempotency, fallback."""
import ast
import asyncio
import json
import time
import types
import unittest
from pathlib import Path

import interpretation

MAIN = Path(__file__).resolve().parents[2] / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")


def _load_methods():
    tree = ast.parse(SOURCE)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "BioCorePlugin")
    wanted = ("_user_appraisal_key", "_user_appraisal_immediate",
              "_schedule_user_appraisal", "_lexical_user_feedback",
              "_user_appraisal_async")
    log = []
    ns = {"asyncio": asyncio, "time": time, "interpretation": interpretation,
          "logger": types.SimpleNamespace(
              info=lambda *a, **k: log.append(a),
              warning=lambda *a, **k: None)}
    fns = {}
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
            _cls = (ast.AsyncFunctionDef if isinstance(node, ast.AsyncFunctionDef)
                    else ast.FunctionDef)
            clone = _cls(name=node.name, args=node.args, body=node.body,
                         decorator_list=[], returns=node.returns,
                         type_comment=None, lineno=node.lineno,
                         col_offset=node.col_offset,
                         end_lineno=node.end_lineno,
                         end_col_offset=node.end_col_offset)
            exec(compile(ast.Module(body=[clone], type_ignores=[]), "<uappr>", "exec"), ns)
            fns[node.name] = ns[node.name]
    return fns, log


FNS, LOG = _load_methods()
DIMS_RAW = ('{"dims":{"goal":0.7,"blame":0.1,"control":0.6,"certainty":0.6,'
            '"novelty":0.2,"involve":0.8,"hit":0.0},"why":"夸","c":0.9}')


class FakeCore:
    def __init__(self):
        self._snapshot = {"v": 0.0, "a": 0.4, "stress": 0.1, "social": 0.5,
                          "trust": 0.5, "self_esteem": 0.5}
        self.needs = {"belonging": 0.6, "self_esteem": 0.6,
                      "control": 0.6, "meaningful_existence": 0.6}
        self.loaded = []

    def snapshot(self):
        return dict(self._snapshot)

    def load_state(self, state):
        self.loaded.append(dict(state))
        self._snapshot.update(state)


class FakePlugin:
    def __init__(self, raw=DIMS_RAW):
        self.raw = raw
        self.llm_calls = 0
        self.lexical_fallback_enabled = True
        self._last_insult_ts = 0.0
        self._appraisal_seen = {}
        self._user_appraisal_task = None
        self._user_appraisal_async = types.MethodType(
            FNS["_user_appraisal_async"], self)
        for name in ("_user_appraisal_key", "_user_appraisal_immediate",
                     "_schedule_user_appraisal", "_lexical_user_feedback"):
            setattr(self, name, types.MethodType(FNS[name], self))

    async def _llm_v2_call(self, kind, prompt, parser, event=None, timeout_ms=None):
        self.llm_calls += 1
        if self.raw is None:
            return None
        return self.raw


class ScheduleTest(unittest.IsolatedAsyncioTestCase):
    async def test_schedule_does_not_block(self):
        plugin = FakePlugin()

        async def slow(*args, **kwargs):
            await asyncio.sleep(0.3)
        plugin._user_appraisal_async = slow
        started = time.time()
        task = plugin._schedule_user_appraisal(object(), FakeCore(), "夸她")
        elapsed = time.time() - started
        self.assertLess(elapsed, 0.05)
        self.assertIsNotNone(task)
        await asyncio.wait_for(task, timeout=1)

    async def test_insult_cooling_is_immediate(self):
        plugin = FakePlugin()
        plugin._user_appraisal_immediate(object(), "你真废物，闭嘴")
        self.assertGreater(plugin._last_insult_ts, 0.0)

    async def test_async_result_writes_once(self):
        plugin = FakePlugin()
        core = FakeCore()
        event = types.SimpleNamespace(unified_msg_origin="u1", message_id="m1")
        key = plugin._user_appraisal_key(event)
        self.assertTrue(await plugin._user_appraisal_async(event, core, "夸她", key))
        self.assertTrue(core.loaded)
        self.assertIn(key, plugin._appraisal_seen)

    async def test_idempotent_key(self):
        plugin = FakePlugin()
        core = FakeCore()
        event = types.SimpleNamespace(unified_msg_origin="u1", message_id="m2")
        key = plugin._user_appraisal_key(event)
        self.assertTrue(await plugin._user_appraisal_async(event, core, "夸她", key))
        writes = len(core.loaded)
        self.assertFalse(await plugin._user_appraisal_async(event, core, "夸她", key))
        self.assertEqual(len(core.loaded), writes)
        self.assertEqual(plugin.llm_calls, 1)

    async def test_dims_failure_falls_back_to_words(self):
        plugin = FakePlugin(raw=None)
        core = FakeCore()
        event = types.SimpleNamespace(unified_msg_origin="u1", message_id="m3")
        key = plugin._user_appraisal_key(event)
        self.assertFalse(await plugin._user_appraisal_async(event, core, "你真废物", key))
        self.assertIsNotNone(core.loaded)

    async def test_switch_off_disables_fallback(self):
        plugin = FakePlugin(raw=None)
        plugin.lexical_fallback_enabled = False
        core = FakeCore()
        event = types.SimpleNamespace(unified_msg_origin="u1", message_id="m4")
        key = plugin._user_appraisal_key(event)
        self.assertFalse(await plugin._user_appraisal_async(event, core, "你真废物", key))
        self.assertFalse(core.loaded)


class WiringStaticTest(unittest.TestCase):
    def test_async_log_and_schedule(self):
        self.assertIn("async=True", SOURCE)
        self.assertIn("_schedule_user_appraisal(event, core, text)", SOURCE)
        self.assertIn("_user_appraisal_async", SOURCE)


if __name__ == "__main__":
    unittest.main()
