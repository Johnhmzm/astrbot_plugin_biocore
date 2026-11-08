# -*- coding: utf-8 -*-
"""Store handles: a store that is not held open can be deleted.

Windows turns a leaked sqlite handle into WinError 32 at temp-dir cleanup, which
surfaces in whatever test runs next -- the bug that cost an afternoon twice.
This is the regression test that keeps it gone.
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


class StoreHandleTest(unittest.TestCase):
    def test_a_store_can_be_deleted_right_after_a_capture(self):
        tmp = tempfile.mkdtemp(prefix="handle-")
        try:
            store = str(Path(tmp) / "store")
            out = pipeline.capture("s1", "user", "回归测试用的一条足够长的句子。", store,
                                   config={"now": 1.79e9, "enabled": True})
            self.assertIsNotNone(out.get("entry"))
            self.assertTrue(Path(store, "sessions", "s1", "memory.db").exists())
            # no store_close() call on purpose: a caller that forgets must still
            # not be able to keep the file locked
            shutil.rmtree(tmp)
            self.assertFalse(Path(tmp).exists())
        finally:
            if Path(tmp).exists():
                sql_store.store_close()
                shutil.rmtree(tmp, ignore_errors=True)

    def test_store_close_releases_every_registered_connection(self):
        tmp = tempfile.mkdtemp(prefix="handle2-")
        try:
            store = str(Path(tmp) / "store")
            pipeline.capture("s1", "user", "第二条回归测试句子，长度足够。", store,
                             config={"now": 1.79e9, "enabled": True})
            closed = sql_store.store_close()
            self.assertGreaterEqual(closed, 0)     # 0 is fine: nothing was held
            shutil.rmtree(tmp)
            self.assertFalse(Path(tmp).exists())
        finally:
            if Path(tmp).exists():
                sql_store.store_close()
                shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
