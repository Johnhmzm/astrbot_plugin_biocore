# -*- coding: utf-8 -*-
"""Per-test isolation for the model suite.

Two things leak across tests otherwise:
  - a pooled sqlite handle (WinError 32 when a temp store is deleted), and
  - the embedding disk cache, whose key is (model, text): two tests that embed
    the same text under the same model name would share rows even when they
    expect different dimensions. Each test therefore gets its own cache file.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CACHE_ENV = "BIOCORE_EMBEDDING_CACHE_FILE"


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
    _release_handles()


@pytest.fixture(autouse=True)
def _isolated_embedding_cache():
    saved = os.environ.get(CACHE_ENV)
    folder = tempfile.mkdtemp(prefix="embcache-")
    os.environ[CACHE_ENV] = str(Path(folder) / "embedding.json")
    _release_handles()
    try:
        yield
    finally:
        _release_handles()
        if saved is None:
            os.environ.pop(CACHE_ENV, None)
        else:
            os.environ[CACHE_ENV] = saved