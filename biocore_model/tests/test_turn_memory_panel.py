# -*- coding: utf-8 -*-
"""P0-3 本轮记忆可见: turn_memory receipt -> dashboard card projection.

The view logic lives in pages/dashboard/turn_memory_view.js (pure functions);
these tests execute it with node and also pin the dashboard wiring + the
backend receipt contract.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from biocore_model import turn_memory as tm

ROOT = Path(__file__).resolve().parents[2]
DASH = ROOT / "pages" / "dashboard"
VIEW = DASH / "turn_memory_view.js"
APP = DASH / "app.js"
SRC_HTML = DASH / "index.src.html"
INDEX_HTML = DASH / "index.html"
MAIN = ROOT / "main.py"
ROUTES = ROOT / "biocore_model" / "plugin_routes.py"

NODE = shutil.which("node")

RECORD = {
    "ts": 1800000000.0,
    "reply": "好，知道了",
    "count": 4,
    "rows": [
        {"rank": 1, "id": "e1", "text": "她周五去体检",
         "source": "lexical", "tier": "hot", "score": 0.8123,
         "reason": "关键词 0.40 / 近期 0.20"},
        {"rank": 2, "id": "e2", "text": "老板张总",
         "source": "graph", "tier": "warm", "score": 0.5,
         "reason": "规则打分"},
        {"rank": 3, "id": "e3", "text": "常驻事实：她在医院工作",
         "source": "resident", "tier": "hot", "score": 0.4},
        {"rank": 4, "id": "e4", "text": "上次聊到奶茶",
         "source": "retrieval", "tier": "cold", "score": 0.2,
         "reason": "留存 0.10"},
    ],
}


def _node_view(payload):
    """Run turn_memory_view.js against *payload* and return its projections."""
    script = (
        "require(" + json.dumps(str(VIEW)) + ");"
        "const v=globalThis.BioTurnMemoryView;"
        "const p=JSON.parse(require('fs').readFileSync(process.argv[1],'utf8'));"
        "process.stdout.write(JSON.stringify({"
        "summary:v.summary(p),all:v.rows(p),two:v.rows(p,2),"
        "zero:v.rows(p,0),none:v.summary(null)}));"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "payload.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        done = subprocess.run([NODE, "-e", script, str(path)],
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=60)
    if done.returncode != 0:
        raise AssertionError("node view failed: " + done.stderr[-800:])
    return json.loads(done.stdout)


@unittest.skipUnless(NODE, "node is required for the dashboard view tests")
class ViewProjectionTest(unittest.TestCase):
    def test_four_rows_keep_source_and_reason(self):
        out = _node_view(RECORD)
        rows = out["summary"]["rows"]
        self.assertEqual(len(rows), 4)
        self.assertEqual([row["source"] for row in rows],
                         ["lexical", "graph", "resident", "retrieval"])
        self.assertEqual(rows[0]["reason"], "关键词 0.40 / 近期 0.20")
        self.assertEqual(rows[2]["reason"], "规则打分")  # default filled in
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[0]["id"], "e1")
        self.assertAlmostEqual(rows[0]["score"], 0.8123)
        self.assertEqual(out["summary"]["count"], 4)
        self.assertEqual(out["summary"]["total"], 4)

    def test_never_more_than_four_rows(self):
        payload = dict(RECORD)
        payload["rows"] = RECORD["rows"] + [
            {"rank": 5, "id": "e5", "text": "第五条", "source": "lexical"},
            {"rank": 6, "id": "e6", "text": "第六条", "source": "lexical"},
        ]
        out = _node_view(payload)
        self.assertEqual(len(out["all"]), 4)
        self.assertEqual(len(out["summary"]["rows"]), 4)
        self.assertEqual([row["id"] for row in out["all"]],
                         ["e1", "e2", "e3", "e4"])

    def test_empty_or_broken_record_is_safe(self):
        out = _node_view({"rows": "nope"})
        self.assertEqual(out["all"], [])
        self.assertEqual(out["summary"]["count"], 0)
        self.assertEqual(out["none"]["rows"], [])
        self.assertEqual(out["none"]["count"], 0)
        # rows without id and text are dropped
        out = _node_view({"rows": [{"source": "x"}, {}]})
        self.assertEqual(out["all"], [])

    def test_limit_argument(self):
        out = _node_view(RECORD)
        self.assertEqual(len(out["two"]), 2)
        self.assertEqual(out["zero"], [])
        self.assertEqual(out["two"][0]["id"], "e1")


class ReceiptContractTest(unittest.TestCase):
    def test_build_record_keeps_four_sources(self):
        trace = [
            {"entry_id": "a1", "text": "她周五体检", "source": "lexical",
             "tier": "hot", "score": 0.8,
             "components": {"lexical": 0.4, "recency": 0.2}},
            {"entry_id": "a2", "text": "老板张总", "source": "graph",
             "tier": "warm", "score": 0.5},
            {"entry_id": "a3", "text": "常驻事实", "source": "resident",
             "tier": "hot", "score": 0.4},
            {"entry_id": "a4", "text": "上次聊到奶茶", "source": "retrieval",
             "tier": "cold", "score": 0.2},
        ]
        rows = tm.build(trace, limit=4)
        record = tm.build_record(rows, reply="ok", ts=1.0)
        self.assertEqual(record["count"], 4)
        for row in record["rows"]:
            self.assertTrue(row["source"])
        project = _node_panel(record) if NODE else None
        if project is not None:
            self.assertEqual(project["count"], 4)
            self.assertEqual(len({row["source"] for row in project["rows"]}), 4)


def _node_panel(record):
    out = _node_view(record)
    return out["summary"]


class DashboardWiringTest(unittest.TestCase):
    def test_status_payload_exposes_turn_memory(self):
        for path in (MAIN, ROUTES):
            text = path.read_text(encoding="utf-8")
            self.assertIn('"turn_memory"', text)
            self.assertIn("_last_turn_memory", text)

    def test_source_markup_and_renderer_present(self):
        src = SRC_HTML.read_text(encoding="utf-8")
        self.assertIn('id="turnMemoryList"', src)
        self.assertIn('id="turnMemoryNote"', src)
        self.assertIn("turn_memory_view.js", src)
        app = APP.read_text(encoding="utf-8")
        self.assertIn("function renderTurnMemory()", app)
        self.assertIn("BioTurnMemoryView", app)
        self.assertIn("data&&data.turn_memory", app)
        self.assertIn("renderTurnMemory()", app)

    def test_inlined_index_contains_view_module(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('id="turnMemoryList"', html)
        self.assertIn("BioTurnMemoryView", html)
        self.assertIn("root.BioTurnMemoryView", html)

    def test_inliner_builds_the_view_module(self):
        inliner = (ROOT / "scripts" / "inline-assets.mjs").read_text(
            encoding="utf-8")
        self.assertIn("turn_memory_view.js", inliner)


if __name__ == "__main__":
    unittest.main()
