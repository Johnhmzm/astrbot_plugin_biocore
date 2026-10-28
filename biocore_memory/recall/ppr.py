# -*- coding: utf-8 -*-
"""Multi-hop expansion via personalized PageRank (default OFF; pure)."""
from __future__ import annotations

enabled = False
ENABLED = False
DEFAULT_HOPS = 2
DEFAULT_DAMPING = 0.5
MAX_HOPS = 10


def _edge_parts(edge):
    if isinstance(edge, dict):
        src = edge.get("src", edge.get("source", edge.get("from")))
        dst = edge.get("dst", edge.get("target", edge.get("to")))
        weight = edge.get("weight", 1.0)
    elif isinstance(edge, (list, tuple)) and len(edge) >= 2:
        src, dst = edge[0], edge[1]
        weight = edge[2] if len(edge) > 2 else 1.0
    else:
        return None
    if src is None or dst is None:
        return None
    try:
        weight = float(weight)
    except Exception:
        weight = 1.0
    if weight <= 0:
        return None
    return str(src), str(dst), weight


def _adjacency(edges):
    graph = {}
    for edge in edges or []:
        parts = _edge_parts(edge)
        if parts is None:
            continue
        src, dst, weight = parts
        graph.setdefault(src, {})[dst] = graph.setdefault(src, {}).get(dst, 0.0) + weight
        graph.setdefault(dst, {})[src] = graph.setdefault(dst, {}).get(src, 0.0) + weight
    return graph


def expand_ppr(seed_ids, edges, hops=DEFAULT_HOPS, damping=DEFAULT_DAMPING):
    """Return [(id, score)] for non-seed nodes reached from the seeds.

    Deterministic personalized PageRank: uniform seed teleport, undirected
    weighted edges, fixed hop count, scores normalized to sum 1 and sorted by
    (score desc, id). Seeds themselves are not returned.
    """
    graph = _adjacency(edges)
    seeds = [str(s) for s in (seed_ids or []) if str(s or "")]
    seeds = [s for s in seeds if s in graph]
    if not seeds or not graph:
        return []
    try:
        hops = max(1, min(MAX_HOPS, int(hops or DEFAULT_HOPS)))
        damping = max(0.0, min(0.99, float(damping)))
    except Exception:
        hops, damping = DEFAULT_HOPS, DEFAULT_DAMPING
    personal = {node: 0.0 for node in graph}
    for seed in seeds:
        personal[seed] += 1.0 / len(seeds)
    scores = dict(personal)
    for _ in range(hops):
        nxt = {node: (1.0 - damping) * personal[node] for node in graph}
        for node, value in scores.items():
            if value <= 0.0:
                continue
            neighbors = graph.get(node) or {}
            total_weight = sum(neighbors.values())
            if total_weight <= 0.0:
                continue
            for neighbor, weight in sorted(neighbors.items()):
                nxt[neighbor] = nxt.get(neighbor, 0.0) + damping * value * weight / total_weight
        scores = nxt
    total = sum(scores.values())
    if total > 0:
        scores = {node: value / total for node, value in scores.items()}
    seed_set = set(seeds)
    rows = [(node, round(value, 6)) for node, value in scores.items()
            if node not in seed_set and value > 1e-12]
    rows.sort(key=lambda row: (-row[1], row[0]))
    return rows
