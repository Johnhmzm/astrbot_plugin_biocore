# -*- coding: utf-8 -*-
import json, os, tempfile, unittest
from pathlib import Path
from biocore_memory.engine import MemoryEngine
from biocore_memory.core import config as engine_config

def entry(i, text, affect=None, importance=0.5, ts=1700000000.0):
    value = {"id": i, "text": text, "role": "user", "ts": ts, "importance": importance,
             "vector": [], "hits": 1, "self_relevance": 0.0, "pin": False,
             "memory_source": "direct", "memory_confidence": 0.7,
             "previous_versions": [], "module": "biocore_memory", "scope": "default"}
    if affect is not None:
        value["affect"] = affect
    return value

class MoodRecallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._saved = {k: os.environ.get(k) for k in ("BIOCORE_MOOD_RECALL", "BIOCORE_MOOD_LAMBDA")}
        os.environ.pop("BIOCORE_MOOD_RECALL", None)
        os.environ.pop("BIOCORE_MOOD_LAMBDA", None)

    def tearDown(self):
        self.tmp.cleanup()
        for k, v in self._saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    def write(self, entries):
        (self.dir / "memory.json").write_text(json.dumps({"entries": entries, "tombstones": [], "schema_version": 1}), encoding="utf-8")

    def engine(self, affect=None):
        return MemoryEngine(data_dir=str(self.dir), affect=affect)

    def test_flag_defaults_off(self):
        self.assertIs(engine_config.FLAGS.get("mood_recall"), False)

    def test_write_stores_affect(self):
        e = self.engine(affect={"v": 0.7, "a": 0.8})
        result = e.remember({"text": "affect write probe"})
        self.assertIsNotNone(result)
        self.assertIn("affect", result)
        self.assertAlmostEqual(result["affect"]["valence"], 0.7, places=3)
        self.assertAlmostEqual(result["affect"]["arousal"], 0.8, places=3)

    def test_off_is_baseline(self):
        self.write([entry("h", "beach happy", {"valence": 0.9, "arousal": 0.8}),
                    entry("s", "beach sad", {"valence": -0.9, "arousal": 0.2})])
        rows = self.engine(affect={"v": 0.9, "a": 0.8}).recall("beach", budget=3)
        self.assertEqual(len(rows), 2)
        happy = next(r for r in rows if r["entry"]["id"] == "h")
        sad = next(r for r in rows if r["entry"]["id"] == "s")
        self.assertAlmostEqual(float(happy["score"]), float(sad["score"]), places=4)

    def test_mood_on_ranks_matching_affect_higher(self):
        os.environ["BIOCORE_MOOD_RECALL"] = "1"
        self.write([entry("h", "beach happy", {"valence": 0.9, "arousal": 0.8}),
                    entry("s", "beach sad", {"valence": -0.9, "arousal": 0.2})])
        rows = self.engine(affect={"v": 0.9, "a": 0.8}).recall("beach", budget=3)
        self.assertEqual(rows[0]["entry"]["id"], "h")
        happy = next(r for r in rows if r["entry"]["id"] == "h")
        sad = next(r for r in rows if r["entry"]["id"] == "s")
        self.assertGreater(float(happy["score"]), float(sad["score"]))
        self.assertGreater(happy.get("mood_cos", 0), sad.get("mood_cos", 0))

    def test_mood_lambda_zero_neutralizes_affect_term(self):
        os.environ["BIOCORE_MOOD_RECALL"] = "1"
        os.environ["BIOCORE_MOOD_LAMBDA"] = "0"
        self.write([entry("h", "beach happy", {"valence": 0.9, "arousal": 0.8}),
                    entry("s", "beach sad", {"valence": -0.9, "arousal": 0.2})])
        rows = self.engine(affect={"v": 0.9, "a": 0.8}).recall("beach", budget=3)
        happy = next(r for r in rows if r["entry"]["id"] == "h")
        sad = next(r for r in rows if r["entry"]["id"] == "s")
        self.assertAlmostEqual(float(happy["score"]), float(sad["score"]), places=4)

    def test_missing_affect_falls_back_neutral(self):
        os.environ["BIOCORE_MOOD_RECALL"] = "1"
        self.write([entry("n", "beach plain"), entry("h", "beach happy", {"valence": 0.9, "arousal": 0.8})])
        rows = self.engine(affect={"v": 0.9, "a": 0.8}).recall("beach", budget=3)
        neutral = next(r for r in rows if r["entry"]["id"] == "n")
        self.assertIn("mood_cos", neutral)
        self.assertTrue(float(neutral["score"]) >= 0.0)
        self.assertLess(float(neutral["score"]), next(r for r in rows if r["entry"]["id"] == "h")["score"] + 1e-6)

    def test_scores_finite_and_ordered(self):
        os.environ["BIOCORE_MOOD_RECALL"] = "1"
        self.write([entry("h", "beach happy", {"valence": 0.5, "arousal": 0.5}),
                    entry("s", "beach sad", {"valence": -0.5, "arousal": 0.5})])
        rows = self.engine(affect={"v": 0.5, "a": 0.5}).recall("beach", budget=3)
        scores = [float(r["score"]) for r in rows]
        self.assertTrue(all(x == x and x >= 0 for x in scores))
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_stability_repeated_recall(self):
        os.environ["BIOCORE_MOOD_RECALL"] = "1"
        self.write([entry("h", "beach happy", {"valence": 0.9, "arousal": 0.8}),
                    entry("s", "beach sad", {"valence": -0.9, "arousal": 0.2})])
        e = self.engine(affect={"v": 0.9, "a": 0.8})
        first = [r["entry"]["id"] for r in e.recall("beach", budget=3)]
        second = [r["entry"]["id"] for r in e.recall("beach", budget=3)]
        self.assertEqual(first, second)

    def test_mood_mismatch_lower(self):
        os.environ["BIOCORE_MOOD_RECALL"] = "1"
        self.write([entry("m", "beach mixed", {"valence": 0.0, "arousal": 0.5}),
                    entry("h", "beach happy", {"valence": 0.9, "arousal": 0.8})])
        rows = self.engine(affect={"v": 0.9, "a": 0.8}).recall("beach", budget=3)
        mixed = next(r for r in rows if r["entry"]["id"] == "m")
        happy = next(r for r in rows if r["entry"]["id"] == "h")
        self.assertGreater(float(happy["score"]), float(mixed["score"]))

    def test_no_affect_field_no_crash(self):
        os.environ["BIOCORE_MOOD_RECALL"] = "1"
        self.write([{"id": "bare", "text": "beach bare", "ts": 1700000000.0, "importance": 0.5, "hits": 1}])
        rows = self.engine(affect=None).recall("beach", budget=3)
        self.assertEqual(len(rows), 1)
        self.assertIn("score", rows[0])