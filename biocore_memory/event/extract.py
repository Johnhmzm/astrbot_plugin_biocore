# -*- coding: utf-8 -*-
"""Host-neutral event extraction: message text + optional L1 affect snapshot."""
from __future__ import annotations
from ..core.util import now_ts, sha12
from ._types import MemoryEvent
from .vector import extract_vector


def from_message(text, role="user", session="", ts=None, vector=None,
                 importance=0.5, metadata=None, affect=None):
    """Build a MemoryEvent from a message; never calls LLMs or writes L1 state."""
    clean = str(text or "").strip()
    if len(clean) < 2:
        return None
    meta = dict(metadata or {})
    event_vector = extract_vector(meta, affect).as_dict()
    meta.setdefault("_event_vector", event_vector)
    return MemoryEvent(text=clean, role=str(role or "user"),
                       session=str(session or ""), ts=now_ts(ts),
                       id=sha12(clean + str(ts or "")),
                       vector=list(vector or []),
                       importance=max(0.0, min(1.0, float(importance or 0.5))),
                       self_relevance=float(event_vector.get("self_relevance", 0.0) or 0.0),
                       metadata=meta)


def extract(text, affect=None, **kw):
    """Alias for from_message with an explicit L1 affect snapshot."""
    return from_message(text, affect=affect, **kw)


def from_l1(text, snapshot=None, **kw):
    """Extract from a text plus raw L1 snapshot (snapshot is read-only input)."""
    snap = snapshot if isinstance(snapshot, dict) else {}
    meta = dict(kw.get("metadata") or {})
    meta["_event_vector"] = extract_vector(meta, snap).as_dict()
    return from_message(text, affect=snap, metadata=meta,
                        **{k: v for k, v in kw.items() if k != "metadata"})


def event_from_any(value):
    """Coerce a MemoryEvent/dict/str into MemoryEvent (best effort)."""
    if isinstance(value, MemoryEvent):
        return value
    if isinstance(value, dict):
        return MemoryEvent(**{k: value[k] for k in MemoryEvent.__dataclass_fields__
                              if k in value})
    return from_message(str(value or ""))
