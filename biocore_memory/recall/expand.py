# -*- coding: utf-8 -*-
"""Event-chain expansion (1-2 hops), deterministic and bounded."""
from __future__ import annotations
from ..core.config import MAX_BUDGET


def expand_links(entries, seed_ids, hops=2, fan_out=3):
    rows = {str(e.get("id") or ""): e for e in (entries or []) if isinstance(e, dict)}
    seen = set(str(x) for x in (seed_ids or []))
    frontier = list(seen)
    out = []
    for _ in range(max(1, min(2, int(hops or 2)))):
        nxt = []
        for sid in frontier:
            entry = rows.get(sid) or {}
            links = entry.get("chain_links") or entry.get("links") or []
            for link in list(links)[:max(1, min(5, int(fan_out or 3)))]:
                lid = str(link.get("id") if isinstance(link, dict) else link)
                if lid and lid not in seen:
                    seen.add(lid)
                    nxt.append(lid)
                    out.append(lid)
        frontier = nxt
        if len(out) >= MAX_BUDGET * 3:
            break
    return out[:MAX_BUDGET * 3]
