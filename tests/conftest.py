# -*- coding: utf-8 -*-
"""Test-wide handle hygiene.

Two caches legitimately keep a sqlite handle open for the process (the embedding
writer is pooled; the store registers every live connection). On Windows a live
handle -- or an antivirus still scanning a freshly written file -- makes a
temporary directory undeletable, and the failure lands in whichever test runs
next as WinError 32.

So this file does three things, in order of increasing bluntness:
  1. release both caches before AND after every test's teardown phase;
  2. force a gc pass, because a connection object can outlive its last use;
  3. retry TemporaryDirectory.cleanup a few times, which covers a scanner
     holding the file for a few milliseconds.
"""
import gc
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _release_handles():
    try:
        from biocore_memory.store import sql_store
        sql_store.store_close()
    except Exception:
        pass
    try:
        from biocore_memory.recall import embedding
        embedding.cache_close()
    except Exception:
        pass


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    # runs BEFORE the test's own teardown (unittest tearDown included), which is
    # exactly where a TemporaryDirectory gets cleaned up
    _release_handles()
    yield
    _release_handles()


@pytest.fixture(autouse=True)
def _release_pooled_handles():
    yield
    _release_handles()


_ORIGINAL_CLEANUP = tempfile.TemporaryDirectory.cleanup


def _cleanup_with_retry(self):
    last = None
    for _ in range(8):
        _release_handles()
        try:
            return _ORIGINAL_CLEANUP(self)
        except PermissionError as exc:      # WinError 32: still held / scanning
            last = exc
            time.sleep(0.05)
    if last is not None:
        raise last


tempfile.TemporaryDirectory.cleanup = _cleanup_with_retry