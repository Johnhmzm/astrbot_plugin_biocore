# -*- coding: utf-8 -*-
"""Background archive batch (one LLM call per batch, queue persisted)."""
from __future__ import annotations

import json
import time
from pathlib import Path

BATCH_MIN = 5
INTERVAL_SECONDS = 600.0
QUEUE_NAME = 'archive-queue.jsonl'


def queue_path(store_dir):
    return Path(str(store_dir)) / QUEUE_NAME


def enqueue(store_dir, event, now=None):
    row = {"ts": float(now if now is not None else time.time()), "level": str((event or {}).get('level') or 'high')[:16],
           "kind": str((event or {}).get('kind') or 'event')[:16], "text": str((event or {}).get('text') or '')[:500]}
    try:
        path = queue_path(store_dir); path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'a', encoding='utf-8') as handle: handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    except Exception:
        return None
    return row


def read_queue(store_dir):
    try:
        return [json.loads(line) for line in queue_path(store_dir).read_text(encoding='utf-8').splitlines() if line.strip()]
    except Exception:
        return []


def due(rows, last_run_ts, now=None):
    n = len(rows or [])
    if n >= BATCH_MIN:
        return True
    if n and last_run_ts and (float(now or time.time()) - float(last_run_ts)) >= INTERVAL_SECONDS:
        return True
    return False


def run_batch(store_dir, llm_call=None, last_run_ts=0.0, now=None):
    """One LLM call for the whole queue; keep the queue on failure for retry."""
    rows = read_queue(store_dir)
    if not rows or llm_call is None:
        return {"ok": True, "rows": len(rows), "calls": 0, "summaries": [], "batch": False}
    if not due(rows, last_run_ts, now):
        return {"ok": True, "rows": len(rows), "calls": 0, "summaries": [], "batch": False}
    try:
        summary = llm_call([dict(row) for row in rows])
    except Exception:
        return {"ok": False, "rows": len(rows), "calls": 1, "summaries": [], "batch": True, "retry": True}
    try:
        queue_path(store_dir).write_text('', encoding='utf-8')
    except Exception:
        pass
    return {"ok": True, "rows": len(rows), "calls": 1, "summaries": [summary], "batch": True}
