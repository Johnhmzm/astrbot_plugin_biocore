# -*- coding: utf-8 -*-
"""task-222: relationship governance for DSH (accumulation / memory / attachment).

The shared relationship file already stores trust/closeness/conflict. This
module adds the missing P0 pieces:

  accumulation   per-message signals -> bounded deltas (warmth, disclosure,
                 conflict, repair), applied by pipeline.relationship_update
  memory         <store>/relationship_memory.json keeps the last N notable
                 events (kind/ts/text preview/delta), append-only
  attachment     style + activation derived with biocore_model
                 attachment_state / attachment_regulation (pure, optional)
  repair         apology-style turns lower conflict and count as repairs

Never deletes relationship history and never writes memory entries.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

try:
    from biocore_model import attachment_regulation as _attach_reg
except Exception:  # pragma: no cover - stripped checkout
    _attach_reg = None
try:
    from biocore_model import attachment_state as _attach_state
except Exception:  # pragma: no cover
    _attach_state = None

MEMORY_FILE = "relationship_memory.json"
EVENT_LIMIT = 50
SCHEMA = 1

_CONFLICT = ("生气", "讨厌", "闭嘴", "滚", "烦", "失望", "吵架", "别说了",
             "你错了", "没用", "不想理")
_REPAIR = ("对不起", "抱歉", "是我不好", "别生气", "原谅", "我错了",
           "不好意思", "不是那个意思")
_WARMTH = ("谢谢", "喜欢", "想你", "抱抱", "辛苦", "开心", "爱你", "陪我",
           "在吗", "晚安")
_TRUST = ("相信", "告诉你", "秘密", "说实话", "只跟你说", "坦白")
_DISCLOSE = ("我其实", "我觉得", "我害怕", "我担心", "我一直")

DELTAS = {
    "warmth": {"trust": 0.004, "closeness": 0.010},
    "conflict": {"trust": -0.012, "closeness": -0.004, "conflict": 0.020},
    "repair": {"trust": 0.008, "closeness": 0.004, "conflict": -0.020},
    "trust": {"trust": 0.008, "closeness": 0.002},
    "disclose": {"trust": 0.006, "closeness": 0.006},
}


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return default
    return number if number == number else default


def _root(store):
    if isinstance(store, dict):
        raw = store.get("root") or store.get("store") or store.get("path")
    else:
        raw = store
    text = str(raw or "").strip()
    return Path(text) if text else None


def _data_dir(store):
    root = _root(store)
    if root is None:
        return None
    return root.parent if root.name == "memory" else root


def enabled(store):
    data_dir = _data_dir(store)
    raw = {}
    if data_dir is not None:
        try:
            raw = json.loads((data_dir / "flags.json").read_text(encoding="utf-8"))
        except Exception:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return raw.get("relationship_governance", True) is not False


def signals(text):
    """One user message -> at most one kind plus its bounded deltas."""
    value = str(text or "")
    if any(word in value for word in _REPAIR):
        kind = "repair"
    elif any(word in value for word in _CONFLICT):
        kind = "conflict"
    elif any(word in value for word in _WARMTH):
        kind = "warmth"
    elif any(word in value for word in _TRUST):
        kind = "trust"
    elif any(word in value for word in _DISCLOSE):
        kind = "disclose"
    else:
        return {"kind": "neutral", "deltas": {}}
    return {"kind": kind, "deltas": dict(DELTAS[kind])}


def style_for(trust, closeness, conflict, repairs=0):
    trust = _num(trust, 0.5)
    closeness = _num(closeness, 0.5)
    conflict = _num(conflict, 0.0)
    if conflict >= 0.45 and trust < 0.55:
        return "anxious"
    if trust < 0.35 and closeness < 0.40:
        return "avoidant"
    if trust >= 0.55 and conflict < 0.25:
        return "secure"
    return "mixed"


def activation_for(style, conflict=0.0, current=0.0, responded=False, hours=0.0):
    """Attachment activation via the pure model modules (safe fallback)."""
    style = style if style in ("secure", "anxious", "avoidant") else "secure"
    try:
        if _attach_reg is not None:
            return dict(_attach_reg.activation(
                style, threat=min(1.0, max(0.0, _num(conflict))), 
                current=_num(current), responded=bool(responded),
                hours=max(0.0, _num(hours))))
    except Exception:
        pass
    return {"style": style, "activation": round(min(1.0, max(0.0, _num(current))), 4),
            "mode": "comfort", "drive_mult": 1.0, "tone": "seek_comfort"}


def memory_path(store):
    root = _root(store)
    return (root / MEMORY_FILE) if root is not None else None


def read_memory(store):
    path = memory_path(store)
    try:
        if path is None or not path.exists():
            return {"schema": SCHEMA, "events": []}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"schema": SCHEMA, "events": []}
        events = [row for row in (data.get("events") or []) if isinstance(row, dict)]
        return {"schema": SCHEMA, "events": events[-EVENT_LIMIT:]}
    except Exception:
        return {"schema": SCHEMA, "events": []}


def _write_memory(store, doc):
    path = memory_path(store)
    if path is None:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(path)
        return True
    except Exception:
        return False


def record_event(store, kind, text, deltas, now=None):
    """Append one notable relationship event (no-op for neutral turns)."""
    if kind in ("", "neutral"):
        return None
    doc = read_memory(store)
    row = {"ts": round(_num(now, time.time()), 3),
           "kind": str(kind)[:16],
           "text": str(text or "")[:40],
           "delta": {key: round(_num(value, 0.0), 4)
                     for key, value in (deltas or {}).items()}}
    events = (doc.get("events") or []) + [row]
    doc["events"] = events[-EVENT_LIMIT:]
    _write_memory(store, doc)
    return row


def summary(store, relationship=None):
    """Counters for /state: accumulation totals + attachment view."""
    doc = read_memory(store)
    events = doc.get("events") or []
    rel = relationship if isinstance(relationship, dict) else {}
    counts = {}
    for row in events:
        kind = str(row.get("kind") or "")
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
    style = str(rel.get("attachment_style") or "")
    if not style:
        style = style_for(rel.get("trust"), rel.get("closeness"),
                          rel.get("conflict"), counts.get("repair", 0))
    view = activation_for(style, _num(rel.get("conflict"), 0.0))
    last = events[-1] if events else {}
    return {
        "events": len(events),
        "repairs": int(counts.get("repair", 0)),
        "warmth": int(counts.get("warmth", 0)),
        "conflicts": int(counts.get("conflict", 0)),
        "attachment_style": view.get("style") or style,
        "attachment_activation": round(_num(view.get("activation"), 0.0), 4),
        "last_event": {"kind": str(last.get("kind") or ""),
                       "ts": round(_num(last.get("ts"), 0.0), 3),
                       "text": str(last.get("text") or "")},
        "enabled": enabled(store),
    }
