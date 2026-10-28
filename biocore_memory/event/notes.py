# -*- coding: utf-8 -*-
"""A-MEM style structured notes (pure, deterministic; no IO, no LLM).

Module is disabled by default: callers MUST check `enabled` before consuming it.
Functions never write files, never import AstrBot, and never mutate their inputs.
"""
from __future__ import annotations

import re

enabled = False
NOTES_ENABLED = enabled

TITLE_MAX = 40
SUMMARY_MAX = 120
TAG_MAX = 12
LINK_MAX = 8
TAG_CHARS = 24
LINK_CHARS = 80

_SENTENCE_END = re.compile(r"[。！？!?；;\n.]")


def _clean(value) -> str:
    """Collapse all whitespace to single spaces (deterministic)."""
    return " ".join(str(value or "").split())


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [value]
    try:
        return list(value)
    except Exception:
        return [value]


def _first_sentence(text: str) -> str:
    part = _SENTENCE_END.split(text, maxsplit=1)[0]
    return _clean(part)


def _norm_items(value, item_chars: int, limit: int) -> list:
    out = []
    seen = set()
    for item in _as_list(value):
        if isinstance(item, dict):
            item = item.get("id") or item.get("target") or item.get("text") or ""
        text = _clean(item)[:item_chars]
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def make_note(text, tags=None, links=None) -> dict:
    """Return a bounded structured note: {title, summary, tags, links}.

    title <= 40 chars (first sentence or first 40 chars of text);
    summary <= 120 chars (full normalized text, truncated);
    tags/links are de-duplicated string lists (12 / 8 entries).
    Pure: no file/network/LLM access and the input objects are not modified.
    """
    clean = _clean(text)
    title = _first_sentence(clean)[:TITLE_MAX].strip()
    if not title:
        title = "未命名"
    summary = clean[:SUMMARY_MAX]
    return {
        "title": title[:TITLE_MAX],
        "summary": summary[:SUMMARY_MAX],
        "tags": _norm_items(tags, TAG_CHARS, TAG_MAX),
        "links": _norm_items(links, LINK_CHARS, LINK_MAX),
    }


__all__ = ["enabled", "NOTES_ENABLED", "make_note", "TITLE_MAX", "SUMMARY_MAX",
           "TAG_MAX", "LINK_MAX"]
