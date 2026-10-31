# -*- coding: utf-8 -*-
"""Wiring tests: validate the memory_dual snippets used/needed in main.py.

- sort: executes the ACTUAL snippet currently in main.py (search anchors, then
  exec with fake scored list) and asserts ordering follows memory_dual scores.
- forget: executes the proposed replacement for _memory_save_doc_for_session
  (main.py:9768-9770) with fake MEMORY_DIR/json/logger and asserts hidden marks.
- testing effect: executes the proposed on_recall write-back snippet.
- policy: reward direction, Q update direction, ui_settings persistence key.
"""
import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from biocore_model import memory_dual as md
from biocore_model import policy_learning as pl
from biocore_model import ui_settings

MAIN = Path(__file__).resolve().parents[2] / "main.py"
NOW = 1_700_000_000.0


class FakePlugin:
    def __init__(self, data_dir):
        self.data_dir = str(data_dir)


class FakeSelf:
    def __init__(self):
        self._last_memory_context = None


def _extract_sort_snippet():
    """The real insertion in main.py: from the memory_dual import to the fallback."""
    source = MAIN.read_text(encoding="utf-8").splitlines()
    import_line = None
    for index, line in enumerate(source):
        if "from biocore_model import memory_dual as _md" in line:
            import_line = index
            break
    if import_line is None:
        raise AssertionError("memory_dual sorting snippet not found in main.py")
    start = import_line
    for index in range(import_line - 1, max(-1, import_line - 8), -1):
        if source[index].strip().startswith("try:"):
            start = index
            break
    if start is None:
        raise AssertionError("memory_dual sorting snippet not found in main.py")
    end = None
    for index in range(start + 1, len(source)):
        if "scored.sort(key=lambda x: x[0], reverse=True)" in source[index]:
            end = index
            break
    if end is None:
        raise AssertionError("sort fallback not found")
    body = "\n".join(source[start:end + 1])
    return "def _run_snippet(self, scored, now):\n" + textwrap.indent(body, "    ")


class DualSortWiringTest(unittest.TestCase):
    def setUp(self):
        self.fresh = {"id": "fresh", "text": "fresh", "storage_s": 0.6,
                      "retrieval_s": 0.55, "access_count": 0,
                      "last_access_ts": NOW - 2 * 3600, "open_loop": False}
        self.stale = {"id": "stale", "text": "stale", "storage_s": 0.5,
                      "retrieval_s": 0.35, "access_count": 0,
                      "last_access_ts": NOW - 72 * 3600, "open_loop": False}

    def test_snippet_reorders_by_dual_score(self):
        snippet = _extract_sort_snippet()
        scored = [(0.99, self.stale), (0.50, self.fresh)]  # legacy order: stale first
        namespace = {}
        exec(compile(snippet, "<main.memory_dual.sort>", "exec"), namespace)
        namespace["_run_snippet"](FakeSelf(), scored, NOW)
        ordered = [entry["id"] for _score, entry in scored]
        expected = sorted(
            ["fresh", "stale"],
            key=lambda eid: -md.score(self.fresh if eid == "fresh" else self.stale,
                                      NOW, context_match=1.0))
        self.assertEqual(ordered, expected)
        self.assertEqual(ordered[0], "fresh")
        self.assertGreater(md.score(self.fresh, NOW), md.score(self.stale, NOW))

    def test_snippet_can_fall_back(self):
        snippet = _extract_sort_snippet()
        scored = [(0.90, {"id": "a", "retrieval_s": 0.5, "last_access_ts": NOW}),
                  (0.10, {"id": "b", "retrieval_s": 0.5, "last_access_ts": NOW})]
        namespace = {}
        exec(compile(snippet, "<main.memory_dual.sort>", "exec"), namespace)
        namespace["_run_snippet"](FakeSelf(), scored, NOW)
        self.assertEqual([e["id"] for _s, e in scored], ["a", "b"])


FORGET_PATCH = '''
def _memory_save_doc_for_session(self, path, doc):
    try:
        from biocore_model import memory_dual as _md
        _rows = doc.get("entries") if isinstance(doc.get("entries"), list) else []
        _fade = _md.forget(_rows, now=time.time())
        doc["entries"] = _fade["entries"]
        if _fade["forgotten_ids"]:
            logger.info("[biocore] memory_dual hidden=%s", _fade["forgotten_ids"])
    except Exception:
        pass
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
'''


class ForgetWiringTest(unittest.TestCase):
    def test_patch_marks_hidden_without_deleting(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            class Logger:
                def info(self, *a, **k): pass
                def warning(self, *a, **k): pass
            namespace = {"json": json, "time": __import__("time"),
                         "logger": Logger(), "MEMORY_DIR": tmp_path}
            exec(compile(FORGET_PATCH, "<forget_patch>", "exec"), namespace)
            fake = object.__new__(type("Fake", (), {}))
            import time as _time
            now_real = _time.time()
            doc = {"entries": [
                {"id": "faint", "retrieval_s": 0.10, "last_access_ts": now_real - 200 * 3600},
                {"id": "solid", "retrieval_s": 0.50, "last_access_ts": now_real},
            ]}
            target = tmp_path / "session.json"
            namespace["_memory_save_doc_for_session"](fake, target, doc)
            saved = json.loads(target.read_text(encoding="utf-8"))
            by_id = {row["id"]: row for row in saved["entries"]}
            self.assertEqual(len(saved["entries"]), 2)          # nothing deleted
            self.assertTrue(by_id["faint"]["hidden"])
            self.assertIn("hidden_ts", by_id["faint"])
            self.assertNotIn("hidden", by_id["solid"])

    def test_patch_second_call_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            class Logger:
                def info(self, *a, **k): pass
                def warning(self, *a, **k): pass
            namespace = {"json": json, "time": __import__("time"),
                         "logger": Logger(), "MEMORY_DIR": tmp_path}
            exec(compile(FORGET_PATCH, "<forget_patch>", "exec"), namespace)
            fake = object.__new__(type("Fake", (), {}))
            import time as _time
            doc = {"entries": [{"id": "faint", "retrieval_s": 0.10,
                                "last_access_ts": _time.time() - 200 * 3600}]}
            target = tmp_path / "session.json"
            namespace["_memory_save_doc_for_session"](fake, target, doc)
            first = json.loads(target.read_text(encoding="utf-8"))
            namespace["_memory_save_doc_for_session"](fake, target, first)
            second = json.loads(target.read_text(encoding="utf-8"))
            self.assertTrue(second["entries"][0]["hidden"])
            self.assertEqual(len(second["entries"]), 1)


TESTING_EFFECT_SNIPPET = '''
_upd = _md.on_recall(e, now)
e["storage_s"] = _upd["storage_s"]
e["retrieval_s"] = _upd["retrieval_s"]
e["access_count"] = _upd["access_count"]
e["last_access_ts"] = _upd["last_access_ts"]
'''


class TestingEffectWiringTest(unittest.TestCase):
    def test_patch_strengthens_selected_entry(self):
        entry = {"id": "e1", "storage_s": 0.5, "retrieval_s": 0.4,
                 "access_count": 0, "last_access_ts": NOW - 24 * 3600}
        namespace = {"e": entry, "now": NOW, "_md": md}
        exec(compile(TESTING_EFFECT_SNIPPET, "<testing_effect>", "exec"), namespace)
        self.assertGreater(entry["storage_s"], 0.5)
        self.assertAlmostEqual(entry["retrieval_s"], 0.75, places=4)
        self.assertEqual(entry["access_count"], 1)
        self.assertEqual(entry["last_access_ts"], NOW)

    def test_patch_is_idempotent_same_now(self):
        entry = {"id": "e1", "storage_s": 0.5, "retrieval_s": 0.4,
                 "access_count": 0, "last_access_ts": 0.0}
        namespace = {"e": entry, "now": NOW, "_md": md}
        exec(compile(TESTING_EFFECT_SNIPPET, "<testing_effect>", "exec"), namespace)
        first = dict(entry)
        exec(compile(TESTING_EFFECT_SNIPPET, "<testing_effect>", "exec"), namespace)
        self.assertEqual(entry, first)


class PolicyWiringTest(unittest.TestCase):
    def test_reward_direction(self):
        responded = pl.reward(True, 5.0, -0.5)
        ignored = pl.reward(False, 900.0, 0.0)
        self.assertGreater(responded, ignored)
        self.assertAlmostEqual(responded, 0.541667, places=6)
        self.assertAlmostEqual(ignored, 0.0, places=6)

    def test_update_direction(self):
        table = pl.update({}, "expect|secure|day", "approach", 1.0, alpha=0.2)
        self.assertGreater(table["expect|secure|day"]["approach"]["q"], 0.0)
        down = pl.update(table, "expect|secure|day", "approach", 0.0, alpha=0.2)
        self.assertLess(down["expect|secure|day"]["approach"]["q"],
                        table["expect|secure|day"]["approach"]["q"])

    def test_q_table_persists_under_ui_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = FakePlugin(tmp)
            table = pl.update({}, "expect|secure|day", "share", 0.5)
            saved = ui_settings.save(plugin, {"autonomy": {"policy_q": table}})
            self.assertTrue(saved.get("ok"))
            data = ui_settings.load(plugin)
            self.assertEqual(data["autonomy"]["policy_q"],
                             table)
            self.assertIn("policy_q", data["autonomy"])


if __name__ == "__main__":
    unittest.main()
