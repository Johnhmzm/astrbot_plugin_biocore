# -*- coding: utf-8 -*-
"""Maximal Marginal Relevance selection (pure; default OFF)."""
from __future__ import annotations

MMR_ENABLED = False


def _vec(candidate):
    if isinstance(candidate, dict):
        vec = candidate.get("vector")
        return list(vec) if isinstance(vec, (list, tuple)) and vec else []
    return []


def _relevance(candidate):
    if isinstance(candidate, dict):
        for key in ("score", "relevance", "sim"):
            try:
                return float(candidate.get(key) or 0.0)
            except Exception:
                continue
    try:
        return float(candidate or 0.0)
    except Exception:
        return 0.0


def _cosine(a, b):
    try:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(float(x) * float(y) for x, y in zip(a, b))
        na = sum(float(x) ** 2 for x in a) ** 0.5
        nb = sum(float(y) ** 2 for y in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0
    except Exception:
        return 0.0


def mmr_select(candidates, k=3, lambda_=0.7, cosine_fn=None):
    """Diversity-aware top-k; disabled returns the first k candidates unchanged."""
    try:
        limit = max(0, int(k if k is not None else 3))
        rows = list(candidates or [])
    except Exception:
        return []
    if limit == 0:
        return []
    if not MMR_ENABLED:
        return rows[:limit]
    try:
        lam = max(0.0, min(1.0, float(lambda_ if lambda_ is not None else 0.7)))
        score_fn = cosine_fn if callable(cosine_fn) else _cosine
        selected = []
        remaining = list(rows)
        while remaining and len(selected) < limit:
            best_idx, best_val = 0, None
            for idx, cand in enumerate(remaining):
                relevance = _relevance(cand)
                diversity = 0.0
                if selected:
                    diversity = max(score_fn(_vec(cand), _vec(other))
                                    for other in selected)
                value = lam * relevance - (1.0 - lam) * diversity
                if best_val is None or value > best_val:
                    best_idx, best_val = idx, value
            selected.append(remaining.pop(best_idx))
        return selected
    except Exception:
        return rows[:limit]
