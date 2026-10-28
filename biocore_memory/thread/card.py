# -*- coding: utf-8 -*-
"""Thread card: <=3 active threads, 6h TTL; expired -> open_loop."""
from __future__ import annotations
from ..core.config import THREAD_LIMIT, THREAD_TTL
from ..core.util import now_ts


def update_thread(threads, topic, status="active", now=None):
    rows = threads if isinstance(threads, dict) else {}
    key = str(topic or "").strip()
    if not key:
        return rows, None
    stamp = now_ts(now)
    card = rows.get(key) or {"topic": key, "created_ts": stamp,
                             "status": "active", "updated_ts": stamp}
    card["status"] = str(status or card.get("status") or "active")
    card["updated_ts"] = stamp
    rows[key] = card
    return rows, {"topic": key, "status": card["status"], "updated_ts": stamp}


def expire_threads(threads, now=None, ttl=THREAD_TTL):
    rows = threads if isinstance(threads, dict) else {}
    stamp = now_ts(now)
    active, loops = [], []
    for topic, card in rows.items():
        if not isinstance(card, dict):
            continue
        age = stamp - float(card.get("updated_ts", 0.0) or 0.0)
        if age > float(ttl or THREAD_TTL) and card.get("status") not in ("open_loop", "closed"):
            card["status"] = "open_loop"
            loops.append(card)
        if card.get("status") == "active":
            active.append(card)
        elif card.get("status") == "open_loop":
            loops.append(card)
    active.sort(key=lambda c: float(c.get("updated_ts", 0.0) or 0.0), reverse=True)
    return active[:max(1, int(THREAD_LIMIT))], loops


def thread_card(entries=None, threads=None, now=None, ttl=THREAD_TTL,
                limit=THREAD_LIMIT):
    if threads is not None:
        active, _ = expire_threads(threads, now=now, ttl=ttl)
        return [{"id": c.get("topic"), "text": c.get("topic"),
                 "ts": c.get("updated_ts"), "status": c.get("status")}
                for c in active[:max(1, int(limit or THREAD_LIMIT))]]
    rows = [e for e in (entries or []) if isinstance(e, dict)]
    out = []
    stamp = now_ts(now) if now else 0.0
    for e in sorted(rows, key=lambda x: float(x.get("ts", 0.0) or 0.0), reverse=True):
        if not stamp or (stamp - float(e.get("ts", 0.0) or 0.0)) <= ttl:
            out.append({"id": str(e.get("id") or ""),
                        "text": str(e.get("text") or "")[:80],
                        "ts": float(e.get("ts", 0.0) or 0.0)})
        if len(out) >= max(1, int(limit or THREAD_LIMIT)):
            break
    return out
