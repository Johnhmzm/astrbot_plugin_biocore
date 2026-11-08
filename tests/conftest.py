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
        # a suite that pins a cache file must not leak that pin into the next
        # suite: env/config win only when no override is set
        embedding.set_cache_file(None)
    except Exception:
        pass


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    # A plain tryfirst hook (no hookwrapper: that spelling is gone in pytest 9)
    # runs BEFORE the test's own teardown -- which is exactly where a unittest
    # tearDown removes its TemporaryDirectory. Releasing after the call phase is
    # what makes the delete succeed.
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

@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """Run every test in its own directory.

    One test used to hand a store path to the core as if it were a session id,
    which wrote sessions/<sanitized-path>/memory.db into the repo root (and once
    got committed). Chdir makes that class of mistake land in a temp dir no
    matter which call site is wrong; the actual call site can be fixed later.
    """
    monkeypatch.chdir(tmp_path)
    yield
