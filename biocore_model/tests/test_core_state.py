# -*- coding: utf-8 -*-
"""task-221: global core state + intero/series plumbing (DSH pipeline)."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from biocore_runtime import core_state
from biocore_runtime import pipeline


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class CoreStateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_dir = self.root / "data"
        self.store = self.data_dir / "memory"
        self.core_file = self.data_dir / "core_state.json"
        self.persona = self.root / "missing_persona.json"

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self, session_id="s1", **extra):
        data = {"store": str(self.store), "session_id": session_id,
                "persona_profile": str(self.persona)}
        data.update(extra)
        return data

    def turn_start(self, session_id="s1", **extra):
        return pipeline.dispatch("turn_start", self.payload(
            session_id, user_text="hello there", capture=False, **extra))

    def turn_end(self, session_id="s1", **extra):
        return pipeline.dispatch("turn_end", self.payload(
            session_id, assistant_text="hi", capture=False, **extra))

    def state(self, session_id="s1"):
        return pipeline.dispatch("state", self.payload(session_id))

    def session_state(self, session_id="s1"):
        path = self.store / "sessions" / session_id / "state.json"
        return json.loads(path.read_text(encoding="utf-8"))


class PathTest(CoreStateCase):
    def test_core_path_is_data_dir(self):
        self.assertEqual(
            pipeline._core_state_path({"store": str(self.store)}),
            self.core_file)


class TurnTest(CoreStateCase):
    def test_turn_start_creates_global_state(self):
        self.turn_start()
        self.assertTrue(self.core_file.exists())
        doc = json.loads(self.core_file.read_text(encoding="utf-8"))
        self.assertGreater(doc["ts"], 0)
        self.assertIsInstance(doc["intero"], dict)
        self.assertEqual(set(doc["intero"]),
                         {"tension", "warmth", "heaviness", "clarity"})
        session = self.session_state()
        self.assertIn("core_delta", session)
        self.assertEqual(session["core_delta"], {})

    def test_turn_end_delta_is_additive(self):
        self.turn_start()
        base = json.loads(self.core_file.read_text(encoding="utf-8"))["stress"]
        self.turn_end(state_delta=[{"field": "stress", "before": 0.0,
                                    "after": 0.2}])
        mid = json.loads(self.core_file.read_text(encoding="utf-8"))["stress"]
        self.assertAlmostEqual(mid, base + 0.2, places=3)
        self.turn_end(state_delta=[{"field": "stress", "before": 0.2,
                                    "after": 0.3}])
        end = json.loads(self.core_file.read_text(encoding="utf-8"))["stress"]
        self.assertAlmostEqual(end, base + 0.3, places=3)

    def test_turn_end_does_not_overwrite(self):
        self.turn_start()
        start = json.loads(self.core_file.read_text(encoding="utf-8"))["v"]
        self.turn_end(delta={"v": -0.05})
        self.turn_end(delta={"v": -0.05})
        end = json.loads(self.core_file.read_text(encoding="utf-8"))["v"]
        self.assertAlmostEqual(end, start - 0.10, places=4)

    def test_turn_end_returns_core_snapshot(self):
        self.turn_start()
        result = self.turn_end(delta={"v": 0.01})
        self.assertTrue(result.get("ok"))
        snapshot = result.get("core_state") or {}
        self.assertTrue(snapshot.get("exists"))
        self.assertIn("intero", snapshot)


class CrossSessionTest(CoreStateCase):
    def test_two_sessions_share_one_body(self):
        self.turn_start("s1")
        self.turn_end("s1", delta={"v": 0.02})
        self.turn_start("s2")
        a = self.state("s1")["state"]
        b = self.state("s2")["state"]
        self.assertAlmostEqual(a["core"]["v"], b["core"]["v"], places=6)
        self.assertEqual(a["intero"], b["intero"])
        self.assertGreater(a["core_state_ts"], 0)

    def test_state_prefers_global_intero(self):
        self.turn_start()
        doc = json.loads(self.core_file.read_text(encoding="utf-8"))
        out = self.state()["state"]
        self.assertEqual(out["intero"], doc["intero"])
        self.assertEqual(out["core_state_ts"], doc["ts"])

    def test_restart_keeps_values(self):
        self.turn_start()
        self.turn_end(delta={"v": 0.04})
        before = self.state()["state"]
        # A fresh reader (new process would do the same) sees the same body.
        reloaded = core_state.load(self.core_file)
        after = self.state()["state"]
        self.assertAlmostEqual(reloaded["v"], after["core"]["v"], places=4)
        self.assertEqual(before["intero"], after["intero"])
        self.assertEqual(before["core_state_ts"], after["core_state_ts"])

    def test_concurrent_updates_do_not_lose_deltas(self):
        core_state.apply(self.core_file, absolute={"v": 0.0}, now=time.time())
        errors = []

        def worker():
            try:
                core_state.apply(self.core_file, deltas={"v": 0.01},
                                 now=time.time())
            except Exception as error:  # pragma: no cover
                errors.append(error)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        doc = json.loads(self.core_file.read_text(encoding="utf-8"))
        self.assertAlmostEqual(doc["v"], 0.20, places=3)


class MigrationTest(CoreStateCase):
    def test_legacy_session_core_migrates_once(self):
        legacy = {"core": {"v": 0.3, "stress": 0.5,
                           "intero": {"tension": 0.4, "warmth": 0.5,
                                      "heaviness": 0.3, "clarity": 0.6}}}
        write_json(self.store / "sessions" / "s1" / "state.json", legacy)
        self.turn_start("s1")
        first = json.loads(self.core_file.read_text(encoding="utf-8"))
        self.assertAlmostEqual(first["v"], 0.3, places=4)
        self.assertIn("s1", first["migrated_sessions"])
        self.turn_start("s1")
        second = json.loads(self.core_file.read_text(encoding="utf-8"))
        self.assertAlmostEqual(second["v"], 0.3, places=4)
        self.assertEqual(second["migrated_sessions"].count("s1"), 1)

    def test_migration_does_not_override_existing_global(self):
        core_state.apply(self.core_file, absolute={"v": 0.1}, now=time.time())
        write_json(self.store / "sessions" / "s1" / "state.json",
                   {"core": {"v": 0.9}})
        self.turn_start("s1")
        doc = json.loads(self.core_file.read_text(encoding="utf-8"))
        self.assertAlmostEqual(doc["v"], 0.1, places=4)


class FallbackTest(CoreStateCase):
    def test_empty_store_falls_back_to_session_state(self):
        write_json(self.store / "sessions" / "s1" / "state.json",
                   {"core": {"v": 0.2, "stress": 0.6, "energy": 0.4}})
        out = self.state("s1")["state"]
        self.assertAlmostEqual(out["core"]["v"], 0.2, places=4)
        self.assertIn("tension", out["intero"])
        self.assertGreater(out["intero"]["tension"], 0.0)
        self.assertEqual(out["core_state_ts"], 0.0)

    def test_series_empty_is_array(self):
        result = pipeline.dispatch("series", self.payload())
        self.assertTrue(result["ok"])
        self.assertEqual(result["series"]["v"], [])
        self.assertEqual(result["points"], [])

    def test_placeholders_are_zero_not_fake(self):
        out = self.state("s1")["state"]
        self.assertEqual(out["recall_count"], 0)
        self.assertEqual(out["proactive_sent_today"], 0)

    def test_recall_count_reads_traces(self):
        trace_dir = self.store / "traces"
        trace_dir.mkdir(parents=True, exist_ok=True)
        rows = [
            {"ts": 1.0, "memory": {"recalled_ids": ["a", "b"]}},
            {"ts": 2.0, "memory": {"recalled_ids": ["c"]}},
        ]
        (trace_dir / "s1.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n",
            encoding="utf-8")
        out = self.state("s1")["state"]
        self.assertEqual(out["recall_count"], 3)

    def test_proactive_sent_today_counts(self):
        now_ms = int(time.time() * 1000)
        write_json(self.store / "proactive.json",
                   {"lastSentAt": now_ms, "sent": [now_ms]})
        out = self.state("s1")["state"]
        self.assertEqual(out["proactive_sent_today"], 1)


class SeriesTest(CoreStateCase):
    def test_series_points_after_turns(self):
        self.turn_start()
        self.turn_end(delta={"v": 0.02})
        self.turn_end(delta={"v": 0.03})
        result = pipeline.dispatch("series", self.payload())
        points = result["points"]
        self.assertGreaterEqual(len(points), 1)
        self.assertLessEqual(len(points), 24)
        self.assertIn("v", points[-1])
        self.assertEqual(result["series"]["v"],
                         [p.get("v") for p in points if p.get("v") is not None])

    def test_series_merges_growth_history(self):
        write_json(self.store / "memory.json", {"entries": []})
        (self.store / "growth_history.jsonl").write_text(
            json.dumps({"ts": time.time() - 3600, "trust": 0.6,
                        "closeness": 0.55}) + "\n", encoding="utf-8")
        result = pipeline.dispatch("series", self.payload())
        self.assertTrue(result["ok"])
        self.assertIn("trust", result["series"])
        self.assertGreaterEqual(len(result["series"]["trust"]), 1)
