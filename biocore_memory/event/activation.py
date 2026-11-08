# -*- coding: utf-8 -*-
"""Activation ranking for event recall: ACT-R base + cos + time + specificity.

score = 0.5*B_i + 0.3*cos + 0.1*time_proximity + 0.1*specificity

B_i = ln(sum (now - t_k)^-0.5) over past hits; hits and last_hit live on the
event itself so they persist with the event table.
"""
from __future__ import annotations

import math

DECAY = 0.5
W_BASE, W_COS, W_TIME, W_SPEC = 0.5, 0.3, 0.1, 0.1
HALF_LIFE = 86400.0


def actr_activation(hits, now, decay=DECAY):
    """ln(sum (now - t_k)^-0.5); 0 when there is no usable history."""
    if not hits:
        return 0.0
    total = 0.0
    for stamp in hits:
        try:
            age = max(1.0, float(now) - float(stamp))
        except Exception:
            continue
        total += age ** (-decay)
    if total <= 0:
        return 0.0
    # ln(1 + x) keeps the value bounded and monotone in the raw sum
    return math.log(1.0 + total)


def time_proximity(as_of, end, span=None):
    """1 at the event end, falling linearly to 0 at one full span away."""
    if as_of is None or end is None:
        return 0.0
    try:
        gap = abs(float(as_of) - float(end))
        scale = float(span) if span else max(1.0, abs(float(end)) * 0.2)
    except Exception:
        return 0.0
    if scale <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - gap / scale))


def cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = float(sum(x * y for x, y in zip(a, b)))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def specificity(vector, centroid):
    """Distance from the global event centroid, squashed into [0, 1]."""
    if not vector or not centroid:
        return 0.0
    return max(0.0, min(1.0, 1.0 - cosine(vector, centroid)))


def score(event, qvec, *, now=None, as_of=None, span=None, centroid=None):
    cos = cosine(qvec, event.get("vector") or [])
    base = actr_activation(event.get("hits_ts") or [], now if now is not None else as_of)
    spec = specificity(event.get("vector") or [], centroid)
    tp = time_proximity(as_of if as_of is not None else now, event.get("end"), span)
    return (W_BASE * base + W_COS * cos + W_TIME * tp + W_SPEC * spec,
            base, cos, tp, spec)


def bump_hits(event, now):
    """Record one injection: hits+1, last_hit=now, keep the hit timestamps."""
    if not isinstance(event, dict):
        return event
    event["hits"] = int(event.get("hits") or 0) + 1
    event["last_hit"] = now
    stamps = list(event.get("hits_ts") or [])
    stamps.append(now)
    event["hits_ts"] = stamps[-20:]
    return event


RRF_K = 60


def rrf_merge(channels, k=RRF_K):
    """Cormack 2009: score(d) = sum over channels 1/(k + rank). Empty channels are skipped."""
    fused = {}
    for ranking in channels or []:
        seen = set()
        rank = 0
        for doc in ranking or []:
            if doc in seen:
                continue
            seen.add(doc)
            rank += 1
            fused[doc] = fused.get(doc, 0.0) + 1.0 / (k + rank)
    return sorted(fused, key=lambda doc: fused[doc], reverse=True)


def rrf_scores(channels, events, k=RRF_K):
    """(score, event) pairs in fused order; ids are matched on event_id."""
    by_id = {}
    for ev in events or []:
        by_id[str(ev.get('event_id') or '')] = ev
    order = rrf_merge(channels, k=k)
    out = []
    for doc in order:
        ev = by_id.get(str(doc))
        if ev is None:
            continue
        out.append((1.0 / (k + order.index(doc) + 1), ev))
    return out
