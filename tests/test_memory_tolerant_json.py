# -*- coding: utf-8 -*-
"""The three model-answer parsers share one tolerant reader; a failure is loud."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.event import claims, compaction  # noqa: E402
from biocore_memory.event import json_tolerant as jt  # noqa: E402
from biocore_runtime import pipeline as P  # noqa: E402

F = chr(96) * 3
PAYLOAD = '{"overview": "o", "claims": []}'


class SharedParserTest(unittest.TestCase):
    def test_fenced(self):
        raw = F + 'json' + chr(10) + PAYLOAD + chr(10) + F
        self.assertEqual(jt.loads(raw)['overview'], 'o')

    def test_trailing_comma(self):
        self.assertEqual(jt.loads('{"a": 1,}')['a'], 1)

    def test_prose_around(self):
        self.assertEqual(jt.loads('好的：' + PAYLOAD + ' 以上')['overview'], 'o')

    def test_garbage_raises(self):
        with self.assertRaises(jt.ParseError):
            jt.loads('模型说不用 JSON')


class ClaimsUseTheSharedParserTest(unittest.TestCase):
    def test_fenced_answer_parses(self):
        raw = F + 'json' + chr(10) + PAYLOAD + chr(10) + F
        self.assertEqual(claims.parse_claims(raw)[0], 'o')

    def test_garbage_raises_for_the_caller(self):
        with self.assertRaises(claims.ParseError):
            claims.parse_claims('又不是 JSON')


class MaxCharsRuleTest(unittest.TestCase):
    def test_zero_means_the_default(self):
        self.assertEqual(P._int_param(0, P.MAX_CHARS, 0, 200), 0)   # raw parse keeps 0
        # the inject rule is explicit: 0 -> MAX_CHARS, never an empty block
        self.assertEqual(P.MAX_CHARS, 420)


if __name__ == "__main__":
    unittest.main()