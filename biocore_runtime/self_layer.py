# -*- coding: utf-8 -*-
"""task-222: self layer (persona lock / narrative / drift) for the DSH core."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

IDENTITY_FILE = "identity.json"
NARRATIVE_LIMIT = 30
SCHEMA = 1


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


def path_for(store):
    data_dir = _data_dir(store)
    return (data_dir / IDENTITY_FILE) if data_dir is not None else None


def _read(path):
    try:
        if path is None or not path.exists():
            return {}
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
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


def hash_persona(text):
    raw = str(text or "").strip()
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def update(store, persona_hash="", narrative=None, now=None):
    """Lock the persona hash, append one narrative line, detect drift."""
    path = path_for(store)
    if path is None:
        return None
    stamp = round(float(now or time.time()), 3)
    doc = _read(path)
    locked = str(doc.get("persona_hash") or "")
    incoming = str(persona_hash or "").strip()
    drift = bool(locked and incoming and locked != incoming)
    if incoming and not locked:
        locked = incoming
    if incoming and drift:
        history = [row for row in (doc.get("drift") or []) if isinstance(row, dict)]
        history.append({"ts": stamp, "from": locked, "to": incoming})
        doc["drift"] = history[-10:]
        locked = incoming
    lines = [row for row in (doc.get("narrative") or []) if isinstance(row, dict)]
    if isinstance(narrative, dict) and str(narrative.get("text") or "").strip():
        lines.append({"ts": stamp, "kind": str(narrative.get("kind") or "note")[:16],
                      "text": str(narrative.get("text"))[:60]})
    doc.update({"schema": SCHEMA, "persona_hash": locked,
                "persona_locked": bool(locked), "narrative": lines[-NARRATIVE_LIMIT:],
                "updated_at": stamp, "drift_count": len(doc.get("drift") or [])})
    _write(path, doc)
    return doc


def summary(store):
    doc = _read(path_for(store))
    lines = [row for row in (doc.get("narrative") or []) if isinstance(row, dict)]
    return {
        "persona_locked": bool(doc.get("persona_locked")),
        "persona_hash": str(doc.get("persona_hash") or "")[:12],
        "drift_count": int(doc.get("drift_count") or 0),
        "narrative_count": len(lines),
        "last_narrative": (lines[-1].get("text") if lines else ""),
        "updated_at": float(doc.get("updated_at") or 0.0),
    }
