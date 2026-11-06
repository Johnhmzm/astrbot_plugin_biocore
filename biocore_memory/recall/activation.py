# -*- coding: utf-8 -*-
"""ACT-R activation as one retrieval score (Anderson 2004).

score(i) = B_i + sum_j W_j*cos(q_j, d_i) + lambda*PPR(i|seeds) + mu*specificity(i)

Every term reuses a quantity the core already has: access times (hits /
last_hit / ts) for the base level, the query vectors for the semantic term, the
graph edges for PPR (recall/ppr.py), and the nearest-neighbour cosine for
specificity. No new data source, no word list. Entries without vectors simply
lose the semantic and specificity terms (0), never an exception.
"""
from __future__ import annotations

import math

from ..core.config import (ACTIVATION_DECAY, ACTIVATION_NEIGHBOURS,
                           ACTIVATION_PPR_LAMBDA, ACTIVATION_SPEC_MU)

SWITCH_KEY = "activation_rank"
SWITCH_ENV = "BIOCORE_ACTIVATION_RANK"


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def enabled(flags=None, env=None):
    """activation_rank: flag > switches > env > default OFF."""
    data = flags if isinstance(flags, dict) else {}
    value = data.get(SWITCH_KEY)
    if value is None and isinstance(data.get("switches"), dict):
        value = data["switches"].get(SWITCH_KEY)
    if isinstance(value, bool):
        return value
    environ = env if hasattr(env, "get") else None
    if environ is not None and SWITCH_ENV in environ:
        return str(environ.get(SWITCH_ENV)).strip().lower() in ("1", "true", "on", "yes")
    return False


def decay(flags=None):
    data = flags if isinstance(flags, dict) else {}
    raw = data.get("activation_decay")
    try:
        value = float(raw)
    except Exception:
        value = float(ACTIVATION_DECAY)
    return max(0.05, min(1.0, value))


def weights_for(flags=None):
    data = flags if isinstance(flags, dict) else {}
    def _pick(key, fallback):
        try:
            return float(data.get(key))
        except Exception:
            return float(fallback)
    return {"lambda": _pick("activation_ppr_lambda", ACTIVATION_PPR_LAMBDA),
            "mu": _pick("activation_spec_mu", ACTIVATION_SPEC_MU)}


def access_times(entry):
    """The entry access times: last_hit and ts, plus hits-1 earlier repeats."""
    entry = entry if isinstance(entry, dict) else {}
    stamps = []
    for key in ("last_hit", "last_access", "ts"):
        value = _num(entry.get(key), 0.0)
        if value > 0:
            stamps.append(value)
            break
    hits = int(_num(entry.get("hits"), 1.0))
    if hits > 1 and stamps:
        stamps.extend([stamps[0]] * min(hits - 1, 50))
    return stamps


def base_level(entry, now, decay_value=None):
    """B_i = ln(sum_k (now - t_k)^(-d)); no times -> the floor (no evidence)."""
    stamps = access_times(entry)
    if not stamps:
        return 0.0
    d = _num(decay_value, ACTIVATION_DECAY)
    total = 0.0
    for stamp in stamps:
        gap = max(1.0, _num(now, 0.0) - _num(stamp, 0.0))
        total += math.pow(gap, -d)
    return round(math.log(total) if total > 0 else 0.0, 6)


def semantic_term(query_vectors, query_weights, entry_vector):
    """sum_j W_j * cos(q_j, d); one query degenerates to plain cosine."""
    vec = entry_vector if isinstance(entry_vector, (list, tuple)) else []
    if not vec:
        return 0.0
    from .channels import cosine
    total = 0.0
    for index, query in enumerate(query_vectors or []):
        if not isinstance(query, (list, tuple)) or len(query) != len(vec):
            continue
        weight = (query_weights[index] if isinstance(query_weights, (list, tuple))
                  and index < len(query_weights) else 1.0)
        total += _num(weight, 1.0) * cosine(list(query), list(vec))
    return round(total, 6)


def specificity_term(entry_vector, all_vectors, neighbours=ACTIVATION_NEIGHBOURS):
    """1 - rho: rho is the mean cosine to the nearest neighbours; 0 without vectors."""
    vec = entry_vector if isinstance(entry_vector, (list, tuple)) else []
    if not vec:
        return 0.0
    from .channels import cosine
    scores = []
    for other in all_vectors or []:
        if not isinstance(other, (list, tuple)) or len(other) != len(vec):
            continue
        if list(other) == list(vec):
            continue
        scores.append(cosine(list(vec), list(other)))
    if not scores:
        return 0.0
    scores.sort(reverse=True)
    top = scores[:max(1, int(neighbours))]
    rho = sum(top) / float(len(top))
    return round(1.0 - rho, 6)


def ppr_scores(seed_ids, edges, damping=0.5):
    """{id: score} from the existing PPR; no edges -> {}."""
    try:
        from . import ppr as ppr_mod
        rows = ppr_mod.expand_ppr(seed_ids, edges, damping=damping)
    except Exception:
        return {}
    return {str(node): _num(score) for node, score in rows or []}


def combine(base, semantic, ppr, spec, lam=ACTIVATION_PPR_LAMBDA,
            mu=ACTIVATION_SPEC_MU):
    """The four weighted terms, added exactly as written in the header."""
    return round(_num(base) + _num(semantic) + _num(lam) * _num(ppr)
                 + _num(mu) * _num(spec), 6)