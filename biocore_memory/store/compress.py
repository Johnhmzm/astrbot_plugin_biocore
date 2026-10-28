# -*- coding: utf-8 -*-
"""Deterministic same-topic compression (default OFF; no LLM, no IO).

compress(entries, max_chars=200) groups entries by their first shared tag and
returns one sentence plus the ids that were compressed. Pure string work only.
"""
from __future__ import annotations

import re

enabled = False
COMPRESS_ENABLED = False
DEFAULT_MAX_CHARS = 200
MIN_MAX_CHARS = 40
MAX_SENTENCE_CHARS = 80
MAX_GROUP_ITEMS = 3

_SENTENCE_END = re.compile(r"[。！？!?；;\n]")


def _tags(entry):
    raw = entry.get("tags")
    if not isinstance(raw, list):
        meta = entry.get("metadata")
        raw = meta.get("tags") if isinstance(meta, dict) else None
    tags = []
    for value in raw or []:
        text = " ".join(str(value or "").split())
        if text and text not in tags:
            tags.append(text)
    return tags


def _sentence(entry):
    text = " ".join(str(entry.get("text") or "").split())
    if not text:
        return ""
    return _SENTENCE_END.split(text, maxsplit=1)[0].strip()[:MAX_SENTENCE_CHARS]


def _ts(entry):
    try:
        return float(entry.get("ts") or entry.get("created_ts") or 0.0)
    except Exception:
        return 0.0


def compress(entries, max_chars=DEFAULT_MAX_CHARS):
    """Return {summary, ids}; disabled or nothing compressible -> empty result."""
    if not enabled:
        return {"summary": "", "ids": []}
    try:
        limit = int(max_chars or DEFAULT_MAX_CHARS)
    except Exception:
        limit = DEFAULT_MAX_CHARS
    limit = max(MIN_MAX_CHARS, min(2000, limit))
    rows = [e for e in (entries or []) if isinstance(e, dict)]
    groups = {}
    for entry in rows:
        tags = _tags(entry)
        if not tags:
            continue
        key = sorted(tags)[0].lower()
        groups.setdefault(key, []).append(entry)
    groups = {key: items for key, items in groups.items() if len(items) >= 2}
    if not groups:
        return {"summary": "", "ids": []}
    parts = []
    ids = []
    for key in sorted(groups, key=lambda k: (-len(groups[k]), k)):
        items = sorted(groups[key], key=lambda e: (_ts(e), str(e.get("id") or "")))
        excerpts = [text for text in (_sentence(e) for e in items[:MAX_GROUP_ITEMS])
                    if text]
        if not excerpts:
            continue
        ids.extend(str(e.get("id") or "") for e in items if e.get("id"))
        parts.append("[%s] %d条：%s" % (key, len(items), "；".join(excerpts)))
    if not parts:
        return {"summary": "", "ids": []}
    summary = ("同主题摘要：" + "。".join(parts))[:limit]
    return {"summary": summary, "ids": ids}
