# -*- coding: utf-8 -*-
"""Cache/usage accounting in the core (contract migration 1).

Usage events live in <dataDir>/usage_events.jsonl; the core is the only writer.
The adapter may still read the legacy <dataDir>/cache_stats.json for a week as
a read-only fallback, but it never writes or recomputes hit_rate.

hit_rate = cache_read / (cache_read + cache_write), falling back to
cache_read / prompt_tokens when no write tokens were reported; clamped to
[0, 1]. The default window is 7 days and every event is bounded.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

USAGE_FILE = "usage_events.jsonl"
LEGACY_FILE = "cache_stats.json"
SCHEMA = 1
DEFAULT_WINDOW_HOURS = 24 * 7
MAX_EVENTS = 5000


def _root(store):
    if isinstance(store, dict):
        raw = store.get("root") or store.get("store") or store.get("path")
    else:
        raw = store
    text = str(raw or "").strip()
    return Path(text) if text else None


def _data_dir(store):
    root = _root(store)
    return (root.parent if root.name == "memory" else root) if root else None


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return default
    return number if number == number else default


def usage_path(store):
    data_dir = _data_dir(store)
    return (data_dir / USAGE_FILE) if data_dir is not None else None


def legacy_path(store):
    data_dir = _data_dir(store)
    return (data_dir / LEGACY_FILE) if data_dir is not None else None


def _read_events(store):
    path = usage_path(store)
    rows = []
    try:
        if path is None or not path.exists():
            return rows
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                rows.append(item)
    except Exception:
        return []
    return rows


def record_event(store, event, now=None):
    """Append one usage event; bounded to MAX_EVENTS."""
    path = usage_path(store)
    if path is None:
        return None
    stamp = round(float(now or event.get("ts") or time.time()), 3)
    row = {
        "ts": stamp,
        "prompt_tokens": max(0, int(_num(event.get("prompt_tokens")))),
        "output_tokens": max(0, int(_num(event.get("output_tokens")))),
        "cache_read": max(0, int(_num(event.get("cache_read")))),
        "cache_write": max(0, int(_num(event.get("cache_write")))),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = _read_events(store)[-(MAX_EVENTS - 1):] + [row]
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text("\n".join(json.dumps(item, ensure_ascii=False)
                                  for item in rows) + "\n", encoding="utf-8")
        tmp.replace(path)
    except Exception:
        return None
    return row


def _legacy(store):
    path = legacy_path(store)
    try:
        if path is None or not path.exists():
            return None
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(doc, dict):
        return None
    return {
        "turns": max(0, int(_num(doc.get("turns")))),
        "prompt_tokens": max(0, int(_num(doc.get("prompt_tokens")))),
        "output_tokens": max(0, int(_num(doc.get("output_tokens")))),
        "cache_read": max(0, int(_num(doc.get("cache_read")))),
        "cache_write": max(0, int(_num(doc.get("cache_write")))),
        "hit_rate": round(min(1.0, max(0.0, _num(doc.get("hit_rate")))), 4),
        "updated_at": round(_num(doc.get("updated_at")), 3),
        "source": "legacy_file",
    }


def compute(store, now=None, window_hours=DEFAULT_WINDOW_HOURS):
    """Aggregate usage events in the window; legacy file only if no events."""
    stamp = float(now or time.time())
    window = max(1.0, _num(window_hours, DEFAULT_WINDOW_HOURS))
    cutoff = stamp - window * 3600.0
    events = [row for row in _read_events(store)
              if _num(row.get("ts"), 0.0) >= cutoff]
    if not events:
        legacy = _legacy(store)
        if legacy is not None:
            legacy["window_hours"] = round(window, 2)
            return legacy
        return {"turns": 0, "prompt_tokens": 0, "output_tokens": 0,
                "cache_read": 0, "cache_write": 0, "hit_rate": 0.0,
                "updated_at": 0.0, "window_hours": round(window, 2),
                "source": "empty"}
    prompt = sum(max(0, int(_num(row.get("prompt_tokens")))) for row in events)
    output = sum(max(0, int(_num(row.get("output_tokens")))) for row in events)
    cache_read = sum(max(0, int(_num(row.get("cache_read")))) for row in events)
    cache_write = sum(max(0, int(_num(row.get("cache_write")))) for row in events)
    denom = cache_read + cache_write
    if prompt > 0:
        hit_rate = cache_read / float(prompt)
    elif denom > 0:
        hit_rate = cache_read / float(denom)
    else:
        hit_rate = 0.0
    hit_rate = round(min(1.0, max(0.0, hit_rate)), 4)
    return {"turns": len(events), "prompt_tokens": prompt,
            "output_tokens": output, "cache_read": cache_read,
            "cache_write": cache_write, "hit_rate": hit_rate,
            "updated_at": round(_num(events[-1].get("ts")), 3),
            "window_hours": round(window, 2), "source": "usage_events"}


def summary(store, now=None):
    return compute(store, now=now, window_hours=DEFAULT_WINDOW_HOURS)
