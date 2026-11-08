# -*- coding: utf-8 -*-
"""Test-wide teardown for handles the runtime legitimately pools.

The embedding cache keeps one sqlite writer open per process (opening it per
vector dominated the write). On Windows that handle makes a temporary store
undeletable, so every test -- related or not -- would fail in teardown with
WinError 32. Closing it after each test is the whole fix.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _release_pooled_handles():
    yield
    try:
        from biocore_memory.recall import embedding
        embedding.cache_close()
    except Exception:
        pass
    try:
        from biocore_memory.store import sql_store
        sql_store.close_connections()
    except Exception:
        pass
