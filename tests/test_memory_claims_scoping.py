# -*- coding: utf-8 -*-
"""Claims in the block are scoped to the events whose sentences were hit."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_runtime import pipeline as P  # noqa: E402


def entry(entry_id, text, ts, event_id):
    return {"id": entry_id, "text": text, "role": "user", "ts": ts,
            "event_id": event_id, "vector": [1.0, 0.0]}


def claim(subject, attr, value, turn):
    return {"subject": subject, "attr": attr, "value": value,
            "turn": turn, "status": "current", "source": "direct"}


class ClaimsScopingTest(unittest.TestCase):
    def test_only_the_hit_event_contributes_claims(self):
        a = {"event_id": "EV001", "overview": "生日",
             "entries": [{"id": "s1", "text": "生日是八月十六。", "ts": 1777800000,
                          "turn": 1, "vector": [1.0, 0.0]}],
             "claims": [claim("叶楠", "生日", "八月十六", 1)]}
        b = {"event_id": "EV002", "overview": "口头禅",
             "entries": [{"id": "s2", "text": "先记着，别急。", "ts": 1777800100,
                          "turn": 2, "vector": [0.0, 1.0]}],
             "claims": [claim("叶楠", "口头禅", "先记着，别急", 2)]}
        hit = P._claims_state_lines([a], limit=8)
        joined = chr(10).join(hit)
        self.assertIn("生日", joined)
        self.assertNotIn("口头禅", joined)

    def test_an_empty_hit_set_falls_back_to_all_claims(self):
        a = {"event_id": "EV001", "overview": "生日", "entries": [],
             "claims": [claim("叶楠", "生日", "八月十六", 1)]}
        lines = P._claims_state_lines([a], limit=8)
        self.assertTrue(lines)
        self.assertIn("生日", chr(10).join(lines))


if __name__ == "__main__":
    unittest.main()