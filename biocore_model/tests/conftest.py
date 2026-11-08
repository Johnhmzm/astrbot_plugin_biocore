# -*- coding: utf-8 -*-
"""Same handle teardown as tests/conftest.py, for the model-side suite."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
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
