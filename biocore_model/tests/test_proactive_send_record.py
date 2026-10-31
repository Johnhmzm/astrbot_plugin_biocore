# -*- coding: utf-8 -*-
"""Regression: proactive _send must record with event=None and never NameError."""
import ast
import asyncio
import types
import unittest
from pathlib import Path

MAIN = Path(__file__).resolve().parents[2] / "main.py"


def _load_send():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    node = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.AsyncFunctionDef) and n.name == "_send"), None)
    assert node is not None, "_send closure not found"
    return node


class FakeTarget:
    sent = []

    def __init__(self, plugin, umo, private=True):
        self.plugin = plugin
        self.umo = umo

    async def send(self, chain):
        FakeTarget.sent.append((self.umo, chain))


class SendRecordTest(unittest.IsolatedAsyncioTestCase):
    def _run_send(self, recorder):
        FakeTarget.sent = []
        warnings = []
        logger = types.SimpleNamespace(
            warning=lambda *a, **k: warnings.append(a),
            info=lambda *a, **k: None)
        plugin = types.SimpleNamespace(
            proactive_llm_enabled=False,
            _sanitize_proactive_text=lambda text, cap=0: str(text or ""),
            _opening_repeats=lambda text: False,
            _record_proactive_sent=recorder)
        ns = {
            "self": plugin,
            "text": "哟，老板！今晚好",
            "umo": "umo-1",
            "_built": {"prompt": "", "system": "", "max_chars": 0,
                       "reason": "lonely"},
            "_AutonomySendTarget": FakeTarget,
            "MessageChain": lambda parts: list(parts),
            "Plain": lambda text: ("plain", text),
            "logger": logger,
        }
        node = _load_send()
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<send>", "exec"), ns)
        return ns["_send"], warnings

    async def test_record_called_once_with_event_none(self):
        calls = []

        def recorder(umo, text, reason="", event=None):
            calls.append({"umo": umo, "text": text, "reason": reason,
                          "event": event})
        send, warnings = self._run_send(recorder)
        await send()
        self.assertEqual(len(FakeTarget.sent), 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["umo"], "umo-1")
        self.assertEqual(calls[0]["text"], "哟，老板！今晚好")
        self.assertEqual(calls[0]["reason"], "lonely")
        self.assertIsNone(calls[0]["event"])
        self.assertEqual(warnings, [])

    async def test_record_exception_is_swallowed_after_send(self):
        def recorder(*args, **kwargs):
            raise RuntimeError("record boom")
        send, warnings = self._run_send(recorder)
        await send()
        self.assertEqual(len(FakeTarget.sent), 1)
        self.assertTrue(any("proactive record failed" in str(args)
                            for args in warnings))


if __name__ == "__main__":
    unittest.main()
