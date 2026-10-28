# -*- coding: utf-8 -*-
"""TiMem-style three-level temporal tree summaries (pure, no writes)."""
from __future__ import annotations

import time

TREE_ENABLED = False
THRESHOLD_L1 = 10
THRESHOLD_L2 = 5
THRESHOLD_L3 = 3
MAX_SOURCE_IDS = 8


def _ts(entry):
    try:
        return float(entry.get("ts") or 0.0)
    except Exception:
        return 0.0


def _day(entry):
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(_ts(entry)))
    except Exception:
        return ""


def _key(entry):
    for key in ("event_key", "topic", "event_name", "thread"):
        value = str(entry.get(key) or "").strip()
        if value:
            return value[:60]
    text = " ".join(str(entry.get("text") or "").split())
    return text[:40] or "untitled"


def _raw(rows):
    return [{"id": str(e.get("id") or ""), "text": str(e.get("text") or "")[:120],
             "ts": _ts(e)} for e in rows]


def _group(rows, key_fn):
    groups = {}
    for entry in rows:
        key = str(key_fn(entry) or "")
        if not key:
            continue
        groups.setdefault(key, []).append(entry)
    out = []
    for key, items in groups.items():
        items = sorted(items, key=_ts)
        out.append({"key": key, "count": len(items),
                    "source_ids": [str(x.get("id") or "") for x in items[:MAX_SOURCE_IDS]
                                   if str(x.get("id") or "")],
                    "ts_min": _ts(items[0]), "ts_max": _ts(items[-1]),
                    "sample": str(items[-1].get("text") or "")[:120]})
    out.sort(key=lambda row: (-row["count"], row["key"]))
    return out


def build_summary(entries, level=1):
    """Build a level summary only when its threshold is exceeded.

    Failure/disabled returns the original rows unchanged (items + generated=False).
    """
    try:
        rows = [e for e in (entries or []) if isinstance(e, dict)]
    except Exception:
        rows = []
    try:
        lvl = int(level if level is not None else 1)
    except Exception:
        lvl = 1
    base = {"level": lvl, "items": _raw(rows), "generated": False,
            "enabled": bool(TREE_ENABLED)}
    if not TREE_ENABLED:
        return base
    try:
        if lvl <= 1:
            if len(rows) <= THRESHOLD_L1:
                return base
            return {"level": 1, "items": _raw(rows)[:THRESHOLD_L1],
                    "generated": True, "enabled": True, "truncated": len(rows)}
        if lvl == 2:
            if len(rows) <= THRESHOLD_L2:
                return base
            return {"level": 2, "items": _group(rows, _key),
                    "generated": True, "enabled": True}
        if len(rows) <= THRESHOLD_L3:
            return base
        return {"level": 3, "items": _group(rows, _day),
                "generated": True, "enabled": True}
    except Exception:
        return {"level": lvl, "items": _raw(rows), "generated": False,
                "enabled": bool(TREE_ENABLED), "error": "summary_failed"}
