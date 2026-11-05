# -*- coding: utf-8 -*-
"""task-36 + task-78: tier hysteresis, reconsolidation, minimal repair loop.

- tier_tick: call after recall; hot stays hot until hits < 3 (task-36).
- record_recall/reconsolidate: 6h window; recall + new input marks the entry
  regenerated_at and nudges its strength via biocore_model.feedback_memory.
  It never deletes and is idempotent per recall batch (task-78).
- repair: a blocked boundary arms one repair turn; prompt_block then lowers
  confrontation / prefers repair wording, with a short cooldown (task-78).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from biocore_memory.store import tiering as _tiering

try:
    from biocore_model import feedback_memory as _feedback
except Exception:  # pragma: no cover
    _feedback = None

TIERS_FILE = "tiers.json"
RECALL_FILE = "recall_state.json"
REPAIR_FILE = "repair.json"
SCHEMA = 1
RECONSOLIDATION_WINDOW_S = 6 * 3600.0
REPAIR_TTL_S = 30 * 60.0
REPAIR_COOLDOWN_S = 10 * 60.0
IMPORTANCE_STEP = 0.02


def _root(store):
    if isinstance(store, dict):
        raw = store.get("root") or store.get("store") or store.get("path")
    else:
        raw = store
    text = str(raw or "").strip()
    return Path(text) if text else None


def _data_dir(store):
    root = _root(store)
    return (root.parent if root.name == "memory" else root) if root else None


def _read(path):
    try:
        if path is None or not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write(path, doc):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(path)
        return True
    except Exception:
        return False


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return default
    return number if number == number else default


# ---------------------------------------------------------------- tiers
def tier_tick(store, entries, now=None):
    """Classify the recalled entries with hysteresis; returns counters."""
    root = _root(store)
    if root is None:
        return None
    stamp = round(float(now or time.time()), 3)
    doc = _read(root / TIERS_FILE)
    by_id = doc.get("by_id") if isinstance(doc.get("by_id"), dict) else {}
    counts = {"hot": 0, "warm": 0, "cold": 0}
    entered = int(_num(doc.get("entered"), 0))
    exited = int(_num(doc.get("exited"), 0))
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id") or "")
        if not entry_id:
            continue
        previous = str((by_id.get(entry_id) or {}).get("tier") or "")
        tier = _tiering.tier_of(entry, now=stamp, previous=previous)
        if previous and previous != tier:
            if tier == "hot":
                entered += 1
            elif previous == "hot":
                exited += 1
        by_id[entry_id] = {"tier": tier, "ts": stamp}
        counts[tier] = counts.get(tier, 0) + 1
    doc.update({"schema": SCHEMA, "by_id": by_id, "counts": counts,
                "entered": entered, "exited": exited, "updated_at": stamp})
    _write(root / TIERS_FILE, doc)
    return {"counts": counts, "entered": entered, "exited": exited,
            "total": sum(counts.values()), "updated_at": stamp}


def tier_summary(store):
    doc = _read((_root(store) or Path(".")) / TIERS_FILE)
    counts = doc.get("counts") if isinstance(doc.get("counts"), dict) else {}
    return {"hot": int(_num(counts.get("hot"))),
            "warm": int(_num(counts.get("warm"))),
            "cold": int(_num(counts.get("cold"))),
            "entered": int(_num(doc.get("entered"))),
            "exited": int(_num(doc.get("exited"))),
            "updated_at": _num(doc.get("updated_at"))}


# ---------------------------------------------------------- reconsolidation
def record_recall(store, session_id, ids, now=None):
    root = _root(store)
    if root is None:
        return False
    stamp = round(float(now or time.time()), 3)
    doc = {"schema": SCHEMA, "session_id": str(session_id or ""),
           "ids": [str(item) for item in (ids or [])][:12], "ts": stamp}
    return _write(root / RECALL_FILE, doc)


def _load_session_entries(root, session_id):
    path = root / "sessions" / str(session_id or "") / "memory.json"
    doc = _read(path)
    entries = doc.get("entries") if isinstance(doc.get("entries"), list) else []
    return doc, entries


def reconsolidate(store, now=None):
    """Within 6h of a recall, a new input marks recalled entries regenerated."""
    root = _root(store)
    if root is None:
        return {"enabled": False, "reason": "no_store"}
    stamp = float(now or time.time())
    state = _read(root / RECALL_FILE)
    ids = [str(item) for item in (state.get("ids") or [])]
    recalled_at = _num(state.get("ts"))
    if not ids or recalled_at <= 0 or stamp - recalled_at > RECONSOLIDATION_WINDOW_S:
        return {"enabled": True, "updated": 0, "skipped": len(ids),
                "reason": "window"}
    doc, entries = _load_session_entries(root, state.get("session_id"))
    updated = 0
    skipped = 0
    for entry in entries:
        if not isinstance(entry, dict) or str(entry.get("id") or "") not in ids:
            continue
        if _num(entry.get("regenerated_at")) >= recalled_at:
            skipped += 1
            continue
        if _feedback is not None:
            result = _feedback.touch([entry], entry.get("id"), stamp,
                                     kind="reconsolidation")
            touched = (result.get("entries") or [entry])[0]
            entry.update(touched)
        entry["regenerated_at"] = round(stamp, 3)
        entry["reconsolidation_count"] = int(
            _num(entry.get("reconsolidation_count"))) + 1
        entry["importance"] = round(min(1.0, max(0.0,
            _num(entry.get("importance"), 0.5) + IMPORTANCE_STEP)), 4)
        updated += 1
    if updated:
        _write(root / "sessions" / str(state.get("session_id") or "")
               / "memory.json", doc)
    return {"enabled": True, "updated": updated, "skipped": skipped,
            "ids": ids[:12], "ts": round(stamp, 3)}


def reconsolidation_summary(store):
    root = _root(store)
    if root is None:
        return {"ids": [], "recalled_at": 0.0, "window_s": RECONSOLIDATION_WINDOW_S}
    state = _read(root / RECALL_FILE)
    return {"ids": list(state.get("ids") or [])[:5],
            "recalled_at": _num(state.get("ts")),
            "window_s": RECONSOLIDATION_WINDOW_S}


# ---------------------------------------------------------------- repair
def arm_repair(store, reason="", now=None):
    root = _root(store)
    if root is None:
        return False
    stamp = float(now or time.time())
    doc = _read(root / REPAIR_FILE)
    if stamp < _num(doc.get("cooldown_until")):
        return False
    doc = {"schema": SCHEMA, "armed": True, "reason": str(reason or "")[:40],
           "armed_at": round(stamp, 3),
           "expires_at": round(stamp + REPAIR_TTL_S, 3),
           "used_at": 0.0,
           "cooldown_until": round(stamp + REPAIR_TTL_S + REPAIR_COOLDOWN_S, 3)}
    return _write(root / REPAIR_FILE, doc)


def repair_lines(store, now=None):
    """Wording constraints for the next reply; one-shot per arming."""
    root = _root(store)
    if root is None:
        return []
    stamp = float(now or time.time())
    doc = _read(root / REPAIR_FILE)
    if not doc.get("armed") or _num(doc.get("used_at")) > 0:
        return []
    if stamp > _num(doc.get("expires_at")):
        doc["armed"] = False
        _write(root / REPAIR_FILE, doc)
        return []
    doc["used_at"] = round(stamp, 3)
    doc["armed"] = False
    _write(root / REPAIR_FILE, doc)
    return ["先修复关系：承认刚才越界或语气不对，不辩解。",
            "降低对抗：句子短、语气软，先问对方现在的感受。"]


def repair_state(store):
    doc = _read((_root(store) or Path(".")) / REPAIR_FILE)
    return {"armed": bool(doc.get("armed")),
            "reason": str(doc.get("reason") or ""),
            "armed_at": _num(doc.get("armed_at")),
            "used_at": _num(doc.get("used_at")),
            "cooldown_until": _num(doc.get("cooldown_until"))}
