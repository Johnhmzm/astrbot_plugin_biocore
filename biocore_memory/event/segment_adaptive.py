# -*- coding: utf-8 -*-
"""Adaptive event boundaries: per-session drift threshold and note coverage.

Pure helpers, no model calls and no IO: the pipeline decides *when* to close an
event, these decide *where* the boundary inside a span is and whether the note
that came back actually covers the turns it claims to summarise.

Design (lead's spec):
  1) s_i = cos(turn_i, turn_{i-1}) over the session.
  2) thr = 20th percentile of s, mean - 1 sigma when the sample is tiny,
     clamped to [0.15, 0.45].
  3) close when sim(new turn, event centroid) < thr or gap > 24 h.
  4) a closed span whose note covers < 0.45 of its turns is bisected at the
     largest adjacent drop, recursively, down to a single turn.
  5) no event smaller than MIN_TURNS turns: a leftover is merged into the
     neighbour it is closest to.
"""
from __future__ import annotations

import math

THR_PCT = 0.20
THR_MIN = 0.15
THR_MAX = 0.45
THR_SMALL_N = 5          # below this many samples, mean - sigma instead of a quantile
COVER_MIN = 0.45         # median(cos(note, turn)) a note must reach to keep its span
MIN_TURNS = 2


def cos(a, b):
    """Cosine of two vectors; 0.0 when either is unusable."""
    try:
        va, vb = list(a or []), list(b or [])
        if not va or len(va) != len(vb):
            return 0.0
        dot = sum(x * y for x, y in zip(va, vb))
        na = math.sqrt(sum(x * x for x in va))
        nb = math.sqrt(sum(y * y for y in vb))
        return dot / (na * nb) if na and nb else 0.0
    except Exception:
        return 0.0


def median(values):
    rows = sorted(float(v) for v in (values or []))
    if not rows:
        return 0.0
    mid = len(rows) // 2
    return rows[mid] if len(rows) % 2 else (rows[mid - 1] + rows[mid]) / 2.0


def quantile(values, q):
    rows = sorted(float(v) for v in (values or []))
    if not rows:
        return 0.0
    if len(rows) == 1:
        return rows[0]
    pos = max(0.0, min(1.0, float(q))) * (len(rows) - 1)
    low = int(math.floor(pos))
    high = min(len(rows) - 1, low + 1)
    return rows[low] + (rows[high] - rows[low]) * (pos - low)


def adjacent_similarities(vectors):
    """s_i = cos(turn_i, turn_{i-1}); skips pairs with an unusable vector."""
    rows = [list(v) for v in (vectors or []) if v]
    return [cos(rows[i], rows[i - 1]) for i in range(1, len(rows))]


def adaptive_threshold(sims, *, pct=THR_PCT, small_n=THR_SMALL_N,
                       low=THR_MIN, high=THR_MAX):
    """Per-session drift threshold; None when there is nothing to learn from."""
    rows = [float(s) for s in (sims or []) if isinstance(s, (int, float))]
    if not rows:
        return None
    if len(rows) < small_n:
        mean = sum(rows) / len(rows)
        var = sum((r - mean) ** 2 for r in rows) / len(rows)
        thr = mean - math.sqrt(var)
    else:
        thr = quantile(rows, pct)
    return max(low, min(high, thr))


def coverage(note_vec, turn_vectors):
    """Median cosine between the note and the turns it claims to cover."""
    return median([cos(note_vec, v) for v in (turn_vectors or []) if v])


def largest_jump(vectors):
    """Split index: right after the biggest drop between neighbouring turns."""
    rows = [list(v) for v in (vectors or []) if v]
    if len(rows) < 2:
        return 0
    sims = [cos(rows[i], rows[i - 1]) for i in range(1, len(rows))]
    worst = min(range(len(sims)), key=lambda i: sims[i])
    return worst + 1


def merge_singletons(parts, *, min_turns=MIN_TURNS):
    """No part below min_turns: fold a leftover into its closest neighbour."""
    kept = [list(part) for part in (parts or []) if part]
    if len(kept) <= 1:
        return kept
    out = []
    for part in kept:
        if len(part) >= min_turns or not out:
            out.append(list(part))
            continue
        out[-1].extend(part)
    if len(out) > 1 and len(out[0]) < min_turns:
        out[1] = out[0] + out[1]
        out.pop(0)
    return out
