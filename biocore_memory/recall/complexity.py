# -*- coding: utf-8 -*-
"""Query-complexity estimate + suggested recall budget (default OFF; pure)."""
from __future__ import annotations

import re

enabled = False
ENABLED = False
SIMPLE_BUDGET, SIMPLE_TOPK = 2, 3
COMPLEX_BUDGET, COMPLEX_TOPK = 4, 5
_LENGTH_COMPLEX = 24
_MULTI_QUESTION = 2
_MULTI_ENTITY = 3
_MULTI_CLAUSE = 3
_CLAUSE_SPLIT = re.compile(r"[，,。；;！!？?、\n]+")
_CJK = re.compile(r"[\u4e00-\u9fff]{2,4}")
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,15}|@[A-Za-z0-9_]+")


def _entity_count(query):
    names = set(_LATIN.findall(query))
    names.update(_CJK.findall(query))
    return len(names)


def _clause_count(query):
    return len([part for part in _CLAUSE_SPLIT.split(query) if part.strip()])


def complexity(query):
    """Return 'simple' or 'complex' from length/questions/entities/clauses."""
    text = str(query or "").strip()
    if not text:
        return "simple"
    score = 0
    if len(text) >= _LENGTH_COMPLEX:
        score += 1
    if text.count("?") + text.count("？") >= _MULTI_QUESTION:
        score += 1
    if _entity_count(text) >= _MULTI_ENTITY:
        score += 1
    if _clause_count(text) >= _MULTI_CLAUSE:
        score += 1
    return "complex" if score >= 2 else "simple"


def suggest_budget(query):
    """Suggested recall budget: 2 for simple, 4 for complex."""
    return COMPLEX_BUDGET if complexity(query) == "complex" else SIMPLE_BUDGET


def suggest_topk(query):
    """Suggested top-k: 3 for simple, 5 for complex."""
    return COMPLEX_TOPK if complexity(query) == "complex" else SIMPLE_TOPK


def suggest(query):
    """Return {'complexity', 'budget', 'topk'} for a query."""
    level = complexity(query)
    return {"complexity": level,
            "budget": COMPLEX_BUDGET if level == "complex" else SIMPLE_BUDGET,
            "topk": COMPLEX_TOPK if level == "complex" else SIMPLE_TOPK}
