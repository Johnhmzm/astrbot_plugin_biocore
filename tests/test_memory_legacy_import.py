# -*- coding: utf-8 -*-
"""A copied store must not re-import the legacy events JSON.

Importing costs a 31 MB parse per copy; the fact is persisted in meta so the
second copy is free. The test proves it by renaming the legacy file: if the
importer still looked at it, the state would come back empty.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.store import sql_store  # noqa: E402
from biocore_runtime import pipeline  # noqa: E402


def seed_legacy(store, session="s1", events=2):
    root = Path(store)
    (root / "sessions" / session).mkdir(parents=True, exist_ok=True)
    (root / "sessions" / session / "memory.json").write_text(json.dumps(
        {"schema_version": 1, "session_id": session, "entries": [
            {"id": "e%d" % i, "text": "legacy 句子 %d" % i, "role": "user",
             "ts": 1.79e9 + i} for i in range(4)]}), encoding="utf-8")
    rows = []
    for i in range(events):
        rows.append({"event_id": "EV%03d" % (i + 1), "start": i * 2 + 1,
                     "end": i * 2 + 2, "overview": "ov%d" % i,
                     "text": "事件文本 %d" % i,
                     "entries": [{"id": "e%d" % (i * 2), "turn": i * 2 + 1,
                                  "ts": 1.79e9 + i, "role": "user",
                                  "text": "legacy 句子 %d" % (i * 2)}]})
    (root / "events").mkdir(parents=True, exist_ok=True)
    (root / "events" / (session + ".json")).write_text(json.dumps(
        {"seen": 4, "events": rows, "state": {}, "open": []}), encoding="utf-8")


class LegacyImportOnceTest(unittest.TestCase):
    def tearDown(self):
        sql_store.store_close()

    def test_a_copy_does_not_reparse_the_legacy_file(self):
        tmp = tempfile.mkdtemp(prefix="legacy-")
        try:
            first = str(Path(tmp) / "store")
            seed_legacy(first)
            state = pipeline._load_event_state(first, "s1")
            self.assertEqual(len(state["events"]), 2)
            meta = pipeline._read_vector_meta(first, "s1")
            self.assertEqual(str(meta.get("legacy_events_imported")), "1")

            # copy the store, then hide the legacy file: the copy must still work
            second = str(Path(tmp) / "copy")
            shutil.copytree(first, second)
            legacy = Path(second) / "events" / "s1.json"
            legacy.rename(legacy.with_suffix(".json.hidden"))
            copied = pipeline._load_event_state(second, "s1")
            self.assertEqual(len(copied["events"]), 2)
        finally:
            sql_store.store_close()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
