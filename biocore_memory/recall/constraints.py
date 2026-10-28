# -*- coding: utf-8 -*-
"""Potential-constraint hints for advice/plan questions (default OFF; pure).

check_constraints() looks for open loops / commitments that overlap the query
and returns a short deterministic hint (<=140 chars), or None when the query is
not an advice/plan question or nothing relevant is open.
"""
from __future__ import annotations

import re

enabled = False
ENABLED = False
MAX_HINT = 140
_TRIGGERS = ("应该", "要不要", "计划", "决定", "打算", "安排", "该不该",
             "是否", "值不值得", "怎么办")
_LATIN = re.compile(r"[a-z0-9_]+")
_CJK = re.compile(r"[\u4e00-\u9fff]+")
_CLOSED = ("closed", "done", "cancelled", "canceled", "已完成", "已关闭")


def _tokens(text):
    s = str(text or "").lower()
    out = _LATIN.findall(s)
    for run in _CJK.findall(s):
        if len(run) == 1:
            out.append(run)
        else:
            out.extend(run[i:i + 2] for i in range(len(run) - 1))
    return out


def _is_question(query):
    if "?" in query or "？" in query:
        return True
    return any(word in query for word in _TRIGGERS)


def _item_text(item):
    if isinstance(item, dict):
        if str(item.get("status") or "").lower() in _CLOSED:
            return ""
        return str(item.get("topic") or item.get("text") or item.get("promise")
                   or item.get("commitment") or item.get("content")
                   or item.get("id") or "").strip()
    return str(item or "").strip()


def _match_score(query_tokens, text_tokens):
    if not query_tokens or not text_tokens:
        return 0.0
    overlap = len(set(query_tokens) & set(text_tokens))
    return overlap / float(len(set(query_tokens)))


def check_constraints(query, open_loops=None, commitments=None):
    """Return a hint string (<=140 chars) when a plan/advice query meets an open item."""
    text = str(query or "").strip()
    if not text or not _is_question(text):
        return None
    q_tokens = _tokens(text)
    candidates = []
    for index, item in enumerate(list(open_loops or []) + list(commitments or [])):
        label = _item_text(item)
        if not label:
            continue
        score = _match_score(q_tokens, _tokens(label))
        if score > 0.0:
            candidates.append((score, index, label))
    if not candidates:
        return None
    candidates.sort(key=lambda row: (-row[0], row[1]))
    label = candidates[0][2]
    hint = "之前提到「%s」还没完成；先确认是否仍有效，再决定。" % label[:80]
    return hint[:MAX_HINT]
