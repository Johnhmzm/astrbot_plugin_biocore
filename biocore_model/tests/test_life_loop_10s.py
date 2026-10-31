# -*- coding: utf-8 -*-
"""10s life loop tests: iteration counters, 6x autonomy, 360x memory, logging."""
import ast
import asyncio
import time
import types
import unittest
from pathlib import Path

MAIN = Path(__file__).resolve().parents[2] / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")


def _load_life_loop():
    tree = ast.parse(SOURCE)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "BioCorePlugin")
    node = next(f for f in cls.body
                if isinstance(f, ast.AsyncFunctionDef) and f.name == "_life_loop")
    log = []

    class _Log:
        def info(self, fmt, *args):
            log.append(("info", fmt % args if args else fmt))

        def warning(self, fmt, *args):
            log.append(("warn", fmt % args if args else fmt))

    calls = {"bio": 0, "memory": 0, "delays": []}

    def bio_tick(core, now, dt_hours=None):
        calls["bio"] += 1
        return {"discomfort": 0.0, "log": {"emit": False, "count": calls["bio"]}}

    def memory(core, now, **kwargs):
        calls["memory"] += 1

    class FastAsyncio:
        @staticmethod
        def sleep(delay):
            calls["delays"].append(delay)
            return asyncio.sleep(0)

        @staticmethod
        def create_task(coro):
            return asyncio.ensure_future(coro)

    ns = {"asyncio": FastAsyncio, "time": time, "logger": _Log(),
          "_bio_tick": types.SimpleNamespace(bio_tick=bio_tick,
                                              memory_maintenance=memory)}
    clone = ast.AsyncFunctionDef(name=node.name, args=node.args, body=node.body,
                            decorator_list=[], returns=node.returns,
                            type_comment=None, lineno=node.lineno,
                            col_offset=node.col_offset, end_lineno=node.end_lineno,
                            end_col_offset=node.end_col_offset)
    exec(compile(ast.Module(body=[clone], type_ignores=[]), "<life10>", "exec"), ns)
    return ns[node.name], log, calls


LIFE, LOG, CALLS = _load_life_loop()


class FakePlugin:
    def __init__(self, autonomy=True):
        self.enabled = True
        self.cores = {"s1": object()}
        self._life_tick_n = 0
        self.proactive_autonomy = bool(autonomy)
        self.autonomy_loop_enabled = False
        self.autonomy_calls = 0

    def _bio_cores_for_tick(self):
        return list(self.cores.values())

    def _memory_maintenance_pass(self, now):
        CALLS["memory"] += 1

    async def _autonomy_tick(self, now=None):
        self.autonomy_calls += 1


class TenSecondLoopTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        CALLS["bio"] = 0
        CALLS["memory"] = 0
        CALLS["delays"] = []
        LOG.clear()

    async def _run_until(self, plugin, target):
        task = asyncio.create_task(LIFE(plugin))
        for _ in range(200000):
            await asyncio.sleep(0)
            if plugin._life_tick_n >= target:
                break
        plugin.enabled = False
        await asyncio.wait_for(task, timeout=2)

    def test_static_sleep_is_ten_seconds(self):
        self.assertIn("await asyncio.sleep(10)", SOURCE)

    async def test_bio_tick_every_iteration_and_autonomy_every_six(self):
        plugin = FakePlugin(autonomy=True)
        await self._run_until(plugin, 13)
        n = plugin._life_tick_n
        self.assertEqual(CALLS["bio"], n)
        self.assertEqual(plugin.autonomy_calls, n // 6)
        self.assertTrue(all(delay == 10 for delay in CALLS["delays"]))

    async def test_memory_every_360(self):
        plugin = FakePlugin(autonomy=False)
        await self._run_until(plugin, 361)
        n = plugin._life_tick_n
        self.assertEqual(CALLS["memory"], n // 360)
        self.assertEqual(plugin.autonomy_calls, 0)

    async def test_autonomy_switch_off_never_ticks(self):
        plugin = FakePlugin(autonomy=False)
        await self._run_until(plugin, 12)
        self.assertEqual(plugin.autonomy_calls, 0)

    async def test_first_and_every_sixth_log(self):
        plugin = FakePlugin(autonomy=False)
        await self._run_until(plugin, 12)
        messages = [row[1] for row in LOG if row[0] == "info"]
        self.assertTrue(any("count': 1" in message for message in messages))
        self.assertTrue(any("count': 6" in message for message in messages))
        self.assertTrue(any("count': 12" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
