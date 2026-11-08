# -*- coding: utf-8 -*-
"""Summariser payload: thinking off by default, empty content is a failure."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_runtime import pipeline as P  # noqa: E402


class FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def store_with(block):
    tmp = tempfile.TemporaryDirectory()
    Path(tmp.name, "core_config.json").write_text(
        json.dumps({"summarizer": block}), encoding="utf-8")
    return tmp


class ThinkingPayloadTest(unittest.TestCase):
    def _call(self, block, reply):
        tmp = store_with(block)
        sent = {}

        def fake_urlopen(request, timeout=None):
            sent["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(reply)

        try:
            P._SUMMARIZER_CACHE.clear()
            fn = P.summarizer_from_config(tmp.name)
            with mock.patch("urllib.request.urlopen", fake_urlopen):
                text = fn("请总结")
        finally:
            P._SUMMARIZER_CACHE.clear()
            tmp.cleanup()
        return sent["payload"], text

    def test_thinking_is_disabled_by_default(self):
        block, text = self._call({"base_url": "http://x/v1", "model": "m"},
                                 {"choices": [{"message": {"content": "笔记"}}]})
        self.assertEqual(block["thinking"], {"type": "disabled"})
        self.assertEqual(text, "笔记")

    def test_config_can_enable_thinking(self):
        block, _text = self._call(
            {"base_url": "http://x/v1", "model": "m", "thinking": "enabled"},
            {"choices": [{"message": {"content": "笔记"}}]})
        self.assertEqual(block["thinking"], {"type": "enabled"})

    def test_an_empty_content_response_raises_instead_of_writing_an_empty_note(self):
        with self.assertRaises(RuntimeError) as caught:
            self._call({"base_url": "http://x/v1", "model": "m"},
                       {"choices": [{"message": {"content": "   "}}]})
        self.assertIn("EMPTY", str(caught.exception))

    def test_no_reply_at_all_raises(self):
        with self.assertRaises(RuntimeError):
            self._call({"base_url": "http://x/v1", "model": "m"}, {"choices": []})


if __name__ == "__main__":
    unittest.main()
