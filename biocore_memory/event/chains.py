# -*- coding: utf-8 -*-
"""Query-time attribute chains: cluster the recall candidates, no precompute.

Nothing here carries a domain lexicon. Clustering is pure vector similarity;
whether a later message explicitly retracts an earlier one is a single model
call per chain, cached by the hash of that chain's text.
"""
from __future__ import annotations

import hashlib
import json
import math

SAME_ATTR = 0.75          # cluster threshold
SAME_SAYING = 0.90        # 'two ways of saying it' threshold
SAME_DAY = 86400.0


def _cos(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = float(sum(x * y for x, y in zip(a, b)))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def cluster_candidates(rows, *, threshold=SAME_ATTR):
    """Greedy single-link clustering of recall candidates by vector similarity.

    Rows are {'turn','ts','text','vector'}; the order they arrive in is the
    recall rank, and the first member of a cluster is its seed.
    """
    clusters = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get('vector'):
            continue
        best, best_score = None, threshold
        for cluster in clusters:
            score = _cos(row['vector'], cluster[0]['vector'])
            if score >= best_score:
                best, best_score = cluster, score
        if best is None:
            clusters.append([dict(row)])
        else:
            best.append(dict(row))
    for cluster in clusters:
        cluster.sort(key=lambda x: (float(x.get('ts') or 0.0), int(x.get('turn') or 0)))
    return clusters


def chain_key(cluster):
    """Stable cache key for one cluster."""
    raw = '||'.join('%s:%s' % (int(item.get('turn') or 0), str(item.get('text') or ''))
                    for item in cluster)
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]


def _pair_prompt(earlier, later):
    from biocore_memory import timefmt as _tf
    return ('判断同一属性的后一次说法是否明确撤回前一次：'
            '只有原文明确否定前一个值（“说错了/记错了/说早了/改成/不对”这类）才算撤回；'
            '补充、细化、换个说法都不算。只输出 JSON：{"retract": true 或 false}。\n\n'
            '【前一次｜%s】%s\n【后一次｜%s】%s'
            % (_tf.label(earlier.get('ts'), earlier.get('turn')),
               str(earlier.get('text') or ''),
               _tf.label(later.get('ts'), later.get('turn')),
               str(later.get('text') or '')))


def mark_retractions(cluster, *, llm=None, cache=None):
    """One verdict per adjacent pair, memoised in the given dict."""
    cache = cache if isinstance(cache, dict) else {}
    flags = {}
    for index in range(1, len(cluster)):
        earlier, later = cluster[index - 1], cluster[index]
        key = ('%s|%s|%s' % (chain_key([earlier, later]),
                             int(earlier.get('turn') or 0),
                             int(later.get('turn') or 0)))
        if key not in cache and llm is not None:
            try:
                data = json.loads(llm(_pair_prompt(earlier, later)) or '{}')
                cache[key] = bool((data or {}).get('retract'))
            except Exception:
                cache[key] = False
        flags[int(later.get('turn') or 0)] = bool(cache.get(key))
    return flags


def render_cluster(cluster, *, flags=None, max_links=6):
    """Old -> new; tail labelled 当前值; retracted links say 已作废."""
    if not cluster:
        return []
    flags = flags if isinstance(flags, dict) else {}
    links = list(cluster)[-max_links:]
    _stamps = [item.get('ts') for item in links]
    from biocore_memory import timefmt as _tf
    turns = _tf.span(_stamps) or ' / '.join(
        _tf.label(item.get('ts'), item.get('turn')) for item in links)
    notes = {}
    for index in range(1, len(links)):
        prev, cur = links[index - 1], links[index]
        if flags.get(int(cur.get('turn') or 0)):
            notes[index - 1] = '（已作废）'
        else:
            gap = abs(float(cur.get('ts') or 0.0) - float(prev.get('ts') or 0.0))
            sim = _cos(prev.get('vector'), cur.get('vector'))
            if gap < SAME_DAY and sim >= SAME_SAYING:
                notes[index - 1] = '（同一属性的两种说法）'
    lines = ['【时间链｜%s】' % turns]
    for index, item in enumerate(links):
        tail = ' ← 当前值' if index == len(links) - 1 else ''
        lines.append('  %d. %s：%s%s%s' % (index + 1,
                                           _tf.label(item.get('ts'), item.get('turn')),
                                           str(item.get('text') or '')[:80],
                                           notes.get(index, ''), tail))
    return lines
