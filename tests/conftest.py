# -*- coding: utf-8 -*-
"""Test-wide teardown for handles the runtime legitimately opens.

Two caches pool one handle per process (the embedding writer keeps a sqlite
connection open; the store registers every live one). On Windows a live handle
makes a temporary directory undeletable, so a leaked connection surfaces as
WinError 32 in teardown -- in whatever test happens to run next. Releasing both
after every test is the whole fix.
"""
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
        from biocore_memory.store import sql_store
        sql_store.store_close()
    except Exception:
        pass
    try:
        from biocore_memory.recall import embedding
        embedding.cache_close()
    except Exception:
        pass
