# -*- coding: utf-8 -*-
"""Compaction: switchable, tolerant, and never fatal."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os  # noqa: E402

from biocore_memory.event import compaction as comp  # noqa: E402
from biocore_runtime import pipeline as P  # noqa: E402


def events():
    return [{"event_id": "EV001", "overview": "灯箱",
             "entries": [{"id": "s1", "text": "灯箱不亮了。"},
                         {"id": "s2", "text": "师傅明天来。"}]}]


VALID = {"event_id": "EV001", "keep_sentence_ids": ["s1"],
         "drop_sentence_ids": ["s2"], "note": "灯箱明天修。"}


class SwitchTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("BIOCORE_COMPACT", None)

    def test_compact_zero_never_calls_the_model(self):
        os.environ["BIOCORE_COMPACT"] = "0"
        called = {"n": 0}

        def ask(prompt):
            called["n"] += 1
            return "[]"

        result = comp.compact(events(), budget_chars=1, ask=ask)
        self.assertFalse(result["triggered"])
        self.assertEqual(result["reason"], "disabled")
        self.assertEqual(called["n"], 0)


class TolerantParseTest(unittest.TestCase):
    def test_a_fenced_answer_parses(self):
        raw = "好的，整理结果如下：\n\x60\x60\x60json\n%s\n\x60\x60\x60" % json.dumps([VALID], ensure_ascii=False)
        rows = comp.parse_decisions(raw)
        self.assertEqual(rows[0]["event_id"], "EV001")

    def test_a_trailing_comma_is_repaired(self):
        raw = json.dumps([VALID], ensure_ascii=False).replace('"note": "灯箱明天修。"',
                                                              '"note": "灯箱明天修。",')
        rows = comp.parse_decisions(raw)
        self.assertEqual(rows[0]["note"], "灯箱明天修。")

    def test_garbage_raises_for_the_caller_to_downgrade(self):
        with self.assertRaises(comp.CompactionError):
            comp.parse_decisions("模型说：这件事我记住就好，不需要 JSON。")


class NeverFatalTest(unittest.TestCase):
    def test_a_bad_model_answer_does_not_break_the_injection(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            store = Path(tmp.name)
            (store / "flags.json").write_text(json.dumps({"event_layer": True}),
                                              encoding="utf-8")
            (store / "core_config.json").write_text(json.dumps(
                {"summarizer": {"base_url": "http://127.0.0.1:9/v1", "model": "m"}}),
                encoding="utf-8")
            stub = lambda prompt: json.dumps({"overview": "灯箱", "claims": []},
                                             ensure_ascii=False)
            with mock.patch.object(comp, "should_compact", return_value=True), \
                    mock.patch.object(comp, "compact", side_effect=comp.CompactionError("bad")), \
                    mock.patch.object(P.logger, "warning") as warned:
                rows = P._event_layer_block(str(store), "s1", "灯箱", 10,
                                            payload={"event_summarizer": stub},
                                            summarizer=stub)
            self.assertTrue(warned.called, "a failed compaction must be logged")
            self.assertTrue(rows is None or isinstance(rows, dict))
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
