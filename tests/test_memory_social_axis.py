# -*- coding: utf-8 -*-
"""S2: the social axis is per entry (Hastie & Kumar 1979).

People file memories by person/object, so the participant sets are the primary
distance and trust/closeness only separates memories about the same people.
Without participants the old scope+relationship formula runs and the coordinate
says fallback=True.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory import space as sp  # noqa: E402
from biocore_runtime import pipeline  # noqa: E402

NOW = 1_700_000_000.0


def entry(entry_id="e1", **extra):
    row = {"id": entry_id, "text": "\u8bb0\u5fc6 " + entry_id, "role": "user",
           "ts": NOW, "tags": [], "importance": 0.5, "hits": 1,
           "scope": "default", "trust": 0.5, "closeness": 0.5}
    row.update(extra)
    return row


def social(entry_a, entry_b):
    left = sp.build(entry_a, now=NOW)
    right = sp.build(entry_b, now=NOW)
    return sp.distance(left, right)["social"]


class ParticipantDistanceTest(unittest.TestCase):
    """Same people close, different people far, overlap in between."""

    def test_same_people_are_close(self):
        same = social(entry("a", participants=["\u5c0f\u590f", "\u5c0f\u738b"]),
                      entry("b", participants=["\u5c0f\u738b", "\u5c0f\u590f"]))
        other = social(entry("a", participants=["\u5c0f\u590f"]),
                       entry("b", participants=["\u5c0f\u738b"]))
        self.assertEqual(same, 0.0)
        self.assertGreater(other, same)
        self.assertGreaterEqual(other, 0.75)

    def test_partial_overlap_follows_jaccard(self):
        left = entry("a", participants=["\u5c0f\u590f", "\u5c0f\u738b"],
                     trust=0.5, closeness=0.5)
        right = entry("b", participants=["\u5c0f\u590f", "\u8001\u674e"],
                      trust=0.5, closeness=0.5)
        # |union| = 3, |shared| = 1 -> jaccard 2/3, spread 0
        expected = round(0.75 * (2.0 / 3.0), 6)
        self.assertAlmostEqual(social(left, right), expected, places=6)

    def test_the_relationship_only_separates_the_same_people(self):
        left = entry("a", participants=["\u5c0f\u590f"], trust=0.2, closeness=0.2)
        right = entry("b", participants=["\u5c0f\u590f"], trust=0.8, closeness=0.8)
        far = entry("c", participants=["\u5c0f\u590f"], trust=0.2, closeness=0.2)
        close = entry("d", participants=["\u5c0f\u738b"], trust=0.2, closeness=0.2)
        self.assertAlmostEqual(social(left, right), 0.25 * 0.6, places=6)
        self.assertGreater(social(left, close), social(left, right))
        self.assertEqual(social(left, far), 0.0)

    def test_without_participants_the_old_formula_runs(self):
        left = entry("a", scope="s1", trust=0.2, closeness=0.2)
        right = entry("b", scope="s2", trust=0.8, closeness=0.8)
        # 0.5 * scope(1.0) + 0.5 * spread(0.6)
        self.assertAlmostEqual(social(left, right), 0.8, places=6)

    def test_the_fallback_flag_is_per_entry(self):
        with_people = sp.build(entry("a", participants=["\u5c0f\u590f"]), now=NOW)
        without = sp.build(entry("b"), now=NOW)
        self.assertFalse(with_people["social"]["fallback"])
        self.assertTrue(without["social"]["fallback"])
        self.assertEqual(with_people["social"]["participants"], ["\u5c0f\u590f"])

    def test_social_scope_is_a_single_participant(self):
        coords = sp.build(entry("a", social_scope="\u5c0f\u590f"), now=NOW)
        self.assertEqual(coords["social"]["participants"], ["\u5c0f\u590f"])


class HostParticipantsTest(unittest.TestCase):
    """The write path carries the people the turn was about."""

    def test_remember_keeps_the_participants(self):
        with tempfile.TemporaryDirectory() as store:
            Path(store, "flags.json").write_text(
                json.dumps({"spatial_recall": True}), encoding="utf-8")
            out = pipeline.tool_call("remember", {
                "text": "\u5c0f\u590f\u8bf4\u5468\u4e94\u53bb\u770b\u7535\u5f71",
                "ts": NOW, "participants": ["\u5c0f\u590f", "\u5c0f\u738b"]},
                store, session_id="s1")
            rows = pipeline.export_session_json(store, "s1")["entries"]
            self.assertEqual(rows[0]["participants"], ["\u5c0f\u590f", "\u5c0f\u738b"])
            self.assertEqual(rows[0]["space"]["social"]["participants"],
                             ["\u5c0f\u590f", "\u5c0f\u738b"])
            self.assertFalse(rows[0]["space"]["social"]["fallback"])

    def test_remember_without_participants_does_not_guess(self):
        with tempfile.TemporaryDirectory() as store:
            pipeline.tool_call("remember", {"text": "\u4eca\u5929\u5929\u6c14\u4e0d\u9519",
                                            "ts": NOW}, store, session_id="s1")
            rows = pipeline.export_session_json(store, "s1")["entries"]
            self.assertNotIn("participants", rows[0])


if __name__ == "__main__":
    unittest.main()
