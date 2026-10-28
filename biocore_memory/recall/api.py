# -*- coding: utf-8 -*-
"""Public recall API: preserves M1/M2 behaviour, injectable cue scorer."""
from __future__ import annotations
from ..core.config import DEFAULT_BUDGET, MAX_BUDGET
from .channels import _embed, score_channels
from .fusion import fuse
from ..core.config import (CUE_WEIGHT, IMPORTANCE_WEIGHT, SEM_WEIGHT,
                           SOURCE_CONFIDENCE_DEFAULT, SOURCE_MIN_CONFIDENCE)


def recall_entries(entries, query, budget=DEFAULT_BUDGET, vector=None,
                   embedder=None, three_channel=False, now=None,
                   cue_scorer=None):
    qvec = list(vector) if isinstance(vector, (list, tuple)) else _embed(embedder, query)
    rows = []
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        text = str(e.get("text") or "")
        if not text:
            continue
        meta = e.get("metadata") if isinstance(e.get("metadata"), dict) else {}
        try:
            conf = float(meta.get("memory_confidence",
                                  e.get("memory_confidence",
                                      SOURCE_CONFIDENCE_DEFAULT)) or SOURCE_CONFIDENCE_DEFAULT)
        except Exception:
            conf = SOURCE_CONFIDENCE_DEFAULT
        if conf < SOURCE_MIN_CONFIDENCE and not e.get("pin"):
            continue
        if three_channel:
            channels = score_channels(e, query, vector=qvec, now=now,
                                      cue_scorer=cue_scorer)
            score, tier = fuse(channels)
            rows.append({"entry": e, "score": score, "mode": "three_channel",
                         "tier": tier, "channels": channels,
                         "fusion": [CUE_WEIGHT, SEM_WEIGHT, IMPORTANCE_WEIGHT],
                         "reasons": ["cue", "semantic", "time", "tier:" + tier]})
            continue
        from .channels import cosine
        channels = score_channels(e, query, vector=qvec)
        lex = channels["lexical"]
        has_semantic = bool(qvec and e.get("vector"))
        sem = cosine(qvec, e.get("vector") or []) if has_semantic else 0.0
        if has_semantic:
            mode = "semantic"
            score = 0.7 * sem + 0.3 * lex
            reasons = ["vector", "lexical"]
        else:
            # No query/entry vector: degrade to lexical (never fail recall).
            mode = "lexical"
            score = lex
            reasons = ["lexical_fallback"]
        try:
            score = score * (0.5 + 0.5 * min(1.0, float(e.get("importance", 0.5) or 0.5)))
        except Exception:
            pass
        rows.append({"entry": e, "score": round(float(score), 6),
                     "mode": mode, "reasons": reasons})
    rows.sort(key=lambda x: x["score"], reverse=True)
    try:
        limit = max(1, min(MAX_BUDGET, int(budget or DEFAULT_BUDGET)))
    except Exception:
        limit = DEFAULT_BUDGET
    return rows[:limit]