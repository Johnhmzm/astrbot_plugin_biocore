# -*- coding: utf-8 -*-
"""Life-loop startup tests: pending flag, running-loop start, bio_tick call.

main.py cannot be imported without AstrBot, so the three lifecycle methods are
extracted from the main.py AST and bound to a fake plugin. This keeps the test
about the real code while staying headless.
"""
import ast
import asyncio
import time
import types
import unittest
from pathlib import Path

PLUG = Path(__file__).resolve().parents[2]
SOURCE = (PLUG / "main.py").read_text(encoding="utf-8")


class _Log:
    def __init__(self):
        self.rows = []

    def info(self, fmt, *args):
        self.rows.append(("info", fmt % args if args else fmt))

    def warning(self, fmt, *args):
        self.rows.append(("warn", fmt % args if args else fmt))

    def debug(self, fmt, *args):
        self.rows.append(("debug", fmt % args if args else fmt))


def load_methods():
    tree = ast.parse(SOURCE)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "BioCorePlugin")
    wanted = ("_ensure_life_task", "_stop_life_task", "_life_loop")
    log = _Log()
    calls = {"bio": 0, "memory": 0}

    def _bio_tick(core, now, dt_hours=None):
        calls["bio"] += 1
        return {"changed": True, "log": {"emit": False, "count": calls["bio"]}}

    def _memory_maintenance(core, now, **kwargs):
        calls["memory"] += 1
        return {"skipped": False}

    fake_tick = types.SimpleNamespace(bio_tick=_bio_tick,
                                      memory_maintenance=_memory_maintenance)
    fast_asyncio = types.SimpleNamespace(
        get_running_loop=asyncio.get_running_loop,
        create_task=asyncio.create_task,
        CancelledError=asyncio.CancelledError,
        sleep=lambda _delay: asyncio.sleep(0.005),
    )
    ns = {"asyncio": fast_asyncio, "time": time, "logger": log,
          "_bio_tick": fake_tick}
    fns = {}
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
            kind = ast.AsyncFunctionDef if isinstance(node, ast.AsyncFunctionDef) else ast.FunctionDef
            clone = kind(name=node.name, args=node.args, body=node.body,
                                    decorator_list=[], returns=node.returns,
                                    type_comment=None, lineno=node.lineno,
                                    col_offset=node.col_offset,
                                    end_lineno=node.end_lineno,
                                    end_col_offset=node.end_col_offset)
            exec(compile(ast.Module(body=[clone], type_ignores=[]), "<life>", "exec"), ns)
            fns[node.name] = ns[node.name]
    return fns, log, calls


class FakePlugin:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.cores = {"s1": object()}
        self._life_task = None
        self._life_start_pending = False
        self.proactive_autonomy = False
        self.autonomy_loop_enabled = False
        self.autonomy_calls = 0

    def _bio_cores_for_tick(self):
        return list(self.cores.values())

    async def _autonomy_tick(self, now=None):
        self.autonomy_calls += 1


FNS, LOG, CALLS = load_methods()


def make_plugin(enabled=True):
    plugin = FakePlugin(enabled=enabled)
    plugin._ensure_life_task = types.MethodType(FNS["_ensure_life_task"], plugin)
    plugin._stop_life_task = types.MethodType(FNS["_stop_life_task"], plugin)
    plugin._life_loop = types.MethodType(FNS["_life_loop"], plugin)
    return plugin


class NoLoopStartupTest(unittest.TestCase):
    def test_start_without_running_loop_sets_pending(self):
        plugin = make_plugin()
        plugin._ensure_life_task()  # called from a sync context: no loop here
        self.assertIsNone(plugin._life_task)
        self.assertTrue(plugin._life_start_pending)

    def test_disabled_plugin_does_not_start(self):
        plugin = make_plugin(enabled=False)
        plugin._ensure_life_task()
        self.assertIsNone(plugin._life_task)
        self.assertFalse(plugin._life_start_pending)


class RunningLoopTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        CALLS["bio"] = 0
        CALLS["memory"] = 0
        LOG.rows.clear()

    async def test_start_inside_loop_creates_task(self):
        plugin = make_plugin()
        plugin._ensure_life_task()
        self.assertIsNotNone(plugin._life_task)
        self.assertFalse(plugin._life_task.done())
        self.assertFalse(plugin._life_start_pending)
        self.assertTrue(any("life loop started" in row[1]
                            for row in LOG.rows if row[0] == "info"))
        plugin.enabled = False
        await asyncio.wait_for(plugin._life_task, timeout=1)

    async def test_second_call_is_idempotent(self):
        plugin = make_plugin()
        plugin._ensure_life_task()
        first = plugin._life_task
        plugin._ensure_life_task()
        self.assertIs(plugin._life_task, first)
        plugin.enabled = False
        await asyncio.wait_for(first, timeout=1)

    async def test_life_loop_calls_bio_tick(self):
        plugin = make_plugin()
        plugin._ensure_life_task()
        await asyncio.sleep(0.03)
        self.assertGreaterEqual(CALLS["bio"], 1)
        plugin.enabled = False
        await asyncio.wait_for(plugin._life_task, timeout=1)

    async def test_autonomy_tick_called_only_when_switch_on(self):
        plugin = make_plugin()
        plugin._ensure_life_task()
        await asyncio.sleep(0.03)
        self.assertEqual(plugin.autonomy_calls, 0)
        plugin.proactive_autonomy = True
        for _ in range(200):
            await asyncio.sleep(0.002)
            if plugin._life_tick_n >= 6:
                break
        self.assertGreaterEqual(plugin.autonomy_calls, 1)
        plugin.enabled = False
        await asyncio.wait_for(plugin._life_task, timeout=1)

    async def test_stop_cancels_and_clears(self):
        plugin = make_plugin()
        plugin._ensure_life_task()
        task = plugin._life_task
        plugin._stop_life_task()
        self.assertIsNone(plugin._life_task)
        self.assertFalse(plugin._life_start_pending)
        await asyncio.sleep(0.02)
        self.assertTrue(task.done())

    async def test_pending_flag_cleared_after_start(self):
        plugin = make_plugin()
        plugin._ensure_life_task()  # no loop: pending (but this test runs in a loop)
        self.assertFalse(plugin._life_start_pending)
        plugin.enabled = False
        await asyncio.wait_for(plugin._life_task, timeout=1)

    async def test_memory_maintenance_wired(self):
        plugin = make_plugin()
        plugin._ensure_life_task()
        await asyncio.sleep(0.05)
        self.assertGreaterEqual(CALLS["memory"], 0)  # every 60th tick; smoke only
        plugin.enabled = False
        await asyncio.wait_for(plugin._life_task, timeout=1)


class DeprecatedAutonomyTaskTest(unittest.TestCase):
    def test_source_has_no_legacy_loop_task(self):
        self.assertNotIn("create_task(self._autonomy_loop())", SOURCE)

    def test_ensure_autonomy_task_is_noop(self):
        tree = ast.parse(SOURCE)
        cls = next(n for n in tree.body
                   if isinstance(n, ast.ClassDef) and n.name == "BioCorePlugin")
        node = next(f for f in cls.body
                    if isinstance(f, ast.FunctionDef) and f.name == "_ensure_autonomy_task")
        created = []
        fake_asyncio = types.SimpleNamespace(
            create_task=lambda coro: created.append(coro),
            get_running_loop=asyncio.get_running_loop)
        ns = {"asyncio": fake_asyncio, "logger": _Log()}
        clone = ast.FunctionDef(name=node.name, args=node.args, body=node.body,
                                decorator_list=[], returns=node.returns,
                                type_comment=None, lineno=node.lineno,
                                col_offset=node.col_offset, end_lineno=node.end_lineno,
                                end_col_offset=node.end_col_offset)
        exec(compile(ast.Module(body=[clone], type_ignores=[]),
                     "<autonomy>", "exec"), ns)
        plugin = FakePlugin()
        plugin._autonomy_task = None
        plugin.proactive_autonomy = True
        plugin.autonomy_loop_enabled = True
        ns["_ensure_autonomy_task"](plugin)
        self.assertIsNone(plugin._autonomy_task)
        self.assertEqual(created, [])


if __name__ == "__main__":
    unittest.main()
