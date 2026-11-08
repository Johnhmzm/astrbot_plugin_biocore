# -*- coding: utf-8 -*-
"""Event association graph: shared entities link events (offline, statistics only).

Nodes are events; an edge weight is the number of shared entities. Entities are
surface tokens from the event note (CJK bigrams, numbers); common tokens are
dropped by document frequency, so no lexicon is involved.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict

MAX_DF_RATIO = 0.2     # a token in more than this share of events is "common"
MIN_LEN = 2


def _tokens(text):
    text = str(text or '')
    out = []
    for run in re.findall(r'[\u4e00-\u9fff]{2,}', text):
        for i in range(len(run) - 1):
            out.append(run[i:i + 2])
    out.extend(re.findall(r'\d{1,4}', text))
    return [t for t in out if len(t) >= MIN_LEN]


def key_terms(notes):
    """Terms kept as entities: appeared at least twice but not in most events."""
    df = Counter()
    for note in notes:
        for term in set(_tokens(note)):
            df[term] += 1
    total = max(1, len(notes))
    ceiling = max(2, int(total * MAX_DF_RATIO))
    return {term for term, count in df.items() if 2 <= count <= ceiling}, dict(df)


def build_graph(events):
    """{event_id: {neighbor_id: weight}} plus the term table."""
    events = [e for e in (events or []) if isinstance(e, dict)]
    notes = [str(e.get('note') or e.get('overview') or '') for e in events]
    keep, df = key_terms(notes)
    by_term = defaultdict(list)
    for ev, note in zip(events, notes):
        for term in set(_tokens(note)) & keep:
            by_term[term].append(str(ev.get('event_id') or ''))
    graph = defaultdict(dict)
    for term, ids in by_term.items():
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if not a or not b or a == b:
                    continue
                graph[a][b] = graph[a].get(b, 0) + 1
                graph[b][a] = graph[b].get(a, 0) + 1
    return dict(graph), {'terms': len(keep), 'df': df}


def graph_digest(events):
    raw = json.dumps([(e.get('event_id'), e.get('note') or e.get('overview') or '')
                      for e in (events or [])], ensure_ascii=False)
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]


def neighbors(graph, seed_ids, per_seed=3):
    """One-hop neighbours, best edge first, capped per seed; deduped."""
    out, seen = [], set(str(s) for s in seed_ids or [])
    for seed in seed_ids or []:
        ranked = sorted((graph.get(str(seed)) or {}).items(),
                        key=lambda item: (-item[1], item[0]))
        added = 0
        for node, _weight in ranked:
            if added >= per_seed:
                break
            if node in seen:
                continue
            seen.add(node)
            out.append(node)
            added += 1
    return out


def expand(events, seed_ids, per_seed=3):
    """Candidates = seeds then neighbours, deduped, with the graph attached."""
    graph, stats = build_graph(events)
    by_id = {str(e.get('event_id') or ''): e for e in events}
    picked, seen = [], set()
    for seed in seed_ids:
        sid = str(seed)
        if sid in by_id and sid not in seen:
            seen.add(sid)
            picked.append(by_id[sid])
    for node in neighbors(graph, seed_ids, per_seed=per_seed):
        if node in by_id and node not in seen:
            seen.add(node)
            picked.append(by_id[node])
    return picked, {'edges': sum(len(v) for v in graph.values()) // 2,
                    'terms': stats['terms'],
                    'neighbours': len(picked) - len([s for s in seed_ids if str(s) in by_id])}
