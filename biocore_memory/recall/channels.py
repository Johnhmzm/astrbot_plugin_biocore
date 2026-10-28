# -*- coding: utf-8 -*-
"""Cue/lexical/semantic/time channel scores (recall mechanism).

Semantic is used only when a query vector is available; otherwise the
semantic channel degrades to the lexical score (both are deterministic).
An optional embedder may be passed to _embed(); failures return None so the
caller falls back to lexical.
"""
from __future__ import annotations
import math, re


def _tokens(text):
    return set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", str(text or "").lower()))


def _bigrams(text):
    s = re.sub(r"\s+", "", str(text or "").lower())
    return set(s[i:i + 2] for i in range(max(0, len(s) - 1))) or _tokens(text)


def lexical_score(query, text):
    q = str(query or "").strip().lower()
    t = str(text or "").lower()
    if not q or not t:
        return 0.0
    if q in t:
        return 1.0
    a, b = _bigrams(query), _bigrams(text)
    if not a or not b:
        return 0.0
    overlap = len(a & b) / float(min(len(a), len(b)))
    uni = _tokens(query)
    unit = _tokens(text)
    uni_score = len(uni & unit) / float(min(len(uni), len(unit))) if uni and unit else 0.0
    return round(max(0.0, min(1.0, 0.7 * overlap + 0.3 * uni_score)), 6)


def cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    try:
        dot = sum(float(x) * float(y) for x, y in zip(a, b))
        na = math.sqrt(sum(float(x) ** 2 for x in a))
        nb = math.sqrt(sum(float(y) ** 2 for y in b))
        return dot / (na * nb) if na and nb else 0.0
    except Exception:
        return 0.0


def _embed(embedder, query):
    """Optional query vector via the safe embedding gateway (None on failure)."""
    if embedder is None:
        return None
    try:
        from .embedding import embed as _safe_embed
        value = _safe_embed(query, embedder)
        if isinstance(value, (list, tuple)) and value:
            return list(value)
    except Exception:
        return None
    try:
        fn = getattr(embedder, "embed_text", None) or getattr(embedder, "embed", None)
        value = fn(query) if fn else None
        return list(value) if isinstance(value, (list, tuple)) else None
    except Exception:
        return None


def score_channels(entry, query, vector=None, now=None, cue_scorer=None):
    e = entry if isinstance(entry, dict) else {}
    text = str(e.get("text") or "")
    lex = lexical_score(query, text)
    vec = list(vector) if isinstance(vector, (list, tuple)) else None
    sem = cosine(vec, e.get("vector") or []) if vec and e.get("vector") else lex
    cue = 0.0
    if cue_scorer is not None:
        try:
            cue = float(cue_scorer(query, e))
        except Exception:
            cue = 0.0
    else:
        cue = lex
    time_score = 0.0
    if now:
        try:
            age = max(0.0, float(now) - float(e.get("ts", 0.0) or 0.0))
            time_score = 1.0 / (1.0 + age / 86400.0)
        except Exception:
            time_score = 0.0
    try:
        importance = max(0.0, min(1.0, float(e.get("importance", 0.5) or 0.5)))
    except Exception:
        importance = 0.5
    return {"cue": max(0.0, min(1.0, cue)),
            "semantic": max(0.0, min(1.0, sem)),
            "importance": importance,
            "lexical": lex, "time": max(0.0, min(1.0, time_score))}