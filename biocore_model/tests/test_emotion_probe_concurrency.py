# -*- coding: utf-8 -*-
"""Probe concurrency tests: no probe-level deadline + inflight drop."""
import ast
import asyncio
import types
import unittest
from pathlib import Path

from biocore_model import emotion_probe as ep

MAIN = Path(__file__).resolve().parents[2] / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")


def _load_helpers():
    tree = ast.parse(SOURCE)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "BioCorePlugin")
    wanted = {"_emotion_probe_acquire", "_emotion_probe_release"}
    ns = {}
    fns = {}
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            clone = ast.FunctionDef(name=node.name, args=node.args, body=node.body,
                                    decorator_list=[], returns=node.returns,
                                    type_comment=None, lineno=node.lineno,
                                    col_offset=node.col_offset,
                                    end_lineno=node.end_lineno,
                                    end_col_offset=node.end_col_offset)
            exec(compile(ast.Module(body=[clone], type_ignores=[]), "<probe-conc>", "exec"),
                 ns)
            fns[node.name] = ns[node.name]
    return fns


FNS = _load_helpers()


class FakePlugin:
    def __init__(self, max_inflight=None):
        self._probe_inflight = 0
        if max_inflight is not None:
            self.emotion_probe_max_inflight = max_inflight

    def acquire(self):
        return FNS["_emotion_probe_acquire"](self)

    def release(self):
        return FNS["_emotion_probe_release"](self)


class ProbeTimeoutTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_timeout_does_not_cancel(self):
        done = {"value": False}

        async def call(prompt):
            await asyncio.sleep(0.2)
            done["value"] = True
            return '{"deltas":{"v":-0.1},"why":"x","c":0.8}'

        out = await ep.probe("x", "y", call, timeout=None, core=object(), now=1000.0)
        self.assertTrue(done["value"])
        self.assertEqual(out["deltas"], {"v": -0.1})

    async def test_explicit_timeout_still_cancels(self):
        async def call(prompt):
            await asyncio.sleep(1.0)
            return '{"deltas":{"v":-0.1},"c":0.8}'

        out = await ep.probe("x", "y", call, timeout=0.05, core=object(), now=1000.0)
        self.assertEqual(out, {})


class InflightTest(unittest.TestCase):
    def test_default_limit_is_one(self):
        plugin = FakePlugin()
        self.assertTrue(plugin.acquire())
        self.assertFalse(plugin.acquire())
        self.assertEqual(plugin._probe_inflight, 1)

    def test_release_allows_next(self):
        plugin = FakePlugin()
        self.assertTrue(plugin.acquire())
        plugin.release()
        self.assertEqual(plugin._probe_inflight, 0)
        self.assertTrue(plugin.acquire())

    def test_exception_path_releases(self):
        plugin = FakePlugin()
        self.assertTrue(plugin.acquire())
        try:
            raise RuntimeError("probe failed")
        except RuntimeError:
            pass
        finally:
            plugin.release()
        self.assertEqual(plugin._probe_inflight, 0)
        self.assertTrue(plugin.acquire())

    def test_max_inflight_two(self):
        plugin = FakePlugin(max_inflight=2)
        self.assertTrue(plugin.acquire())
        self.assertTrue(plugin.acquire())
        self.assertFalse(plugin.acquire())
        plugin.release()
        self.assertTrue(plugin.acquire())

    def test_release_never_negative(self):
        plugin = FakePlugin()
        plugin.release()
        plugin.release()
        self.assertEqual(plugin._probe_inflight, 0)


class WiringStaticTest(unittest.TestCase):
    def test_main_guard_and_finally(self):
        self.assertIn("[biocore] emotion probe skipped (inflight)", SOURCE)
        self.assertIn("if not self._emotion_probe_acquire():", SOURCE)
        self.assertIn("self._emotion_probe_release()", SOURCE)
        self.assertIn("timeout=None", SOURCE)

    def test_probe_default_timeout_none(self):
        import inspect
        self.assertIsNone(inspect.signature(ep.probe).parameters["timeout"].default)


if __name__ == "__main__":
    unittest.main()
