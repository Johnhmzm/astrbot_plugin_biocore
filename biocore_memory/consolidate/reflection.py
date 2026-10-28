# -*- coding: utf-8 -*-
"""Reflection stage: propose experience candidates from repeated events (no writes)."""
from __future__ import annotations

REFLECTION_ENABLED = False
MIN_REPEATS = 2
MAX_PROPOSALS = 5
MAX_TEXT = 120


def _key(entry):
    for key in ("event_key", "topic", "event_name"):
        value = str(entry.get(key) or "").strip()
        if value:
            return value[:60]
    return " ".join(str(entry.get("text") or "").split())[:60]


def propose(entries):
    """Return [{text, source_ids}] experience candidates; never writes storage."""
    if not REFLECTION_ENABLED:
        return []
    try:
        groups = {}
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            key = _key(entry)
            if key:
                groups.setdefault(key, []).append(entry)
        out = []
        for key, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            if len(items) < MIN_REPEATS:
                continue
            sample = " ".join(str(items[-1].get("text") or "").split())[:60]
            text = "经验：关于「%s」的重复经历共 %d 次；最近一次：%s" % (
                key[:40], len(items), sample)
            out.append({"text": text[:MAX_TEXT],
                        "source_ids": [str(x.get("id") or "") for x in items[:8]
                                       if str(x.get("id") or "")]})
            if len(out) >= MAX_PROPOSALS:
                break
        return out
    except Exception:
        return []
