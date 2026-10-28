# -*- coding: utf-8 -*-
"""Identity version-chain helpers (read-only view)."""
from __future__ import annotations


def history_rows(entry):
    e = entry if isinstance(entry, dict) else {}
    rows = e.get("previous_versions")
    return [dict(x) for x in rows if isinstance(x, dict)] if isinstance(rows, list) else []
