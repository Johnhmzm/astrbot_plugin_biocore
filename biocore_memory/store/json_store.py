# -*- coding: utf-8 -*-
"""JSON store: backward-compatible load, atomic save, corrupt backup."""
from __future__ import annotations
import json, os, shutil
from pathlib import Path

from ..core.config import SCHEMA_VERSION
from ..core.util import normalize_text
from .versions import record_version
from .tombstone import append_tombstone


class MemoryStore:
    def __init__(self, path=None, doc=None):
        self.path = Path(path) if path else None
        self.doc = {"entries": [], "tombstones": []}
        if isinstance(doc, dict):
            self.import_doc(doc)

    def import_doc(self, doc):
        data = doc if isinstance(doc, dict) else {}
        out = dict(data)
        entries = out.get("entries")
        out["entries"] = [dict(e) for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
        tombs = out.get("tombstones")
        out["tombstones"] = [dict(t) for t in tombs if isinstance(t, dict)] if isinstance(tombs, list) else []
        out.setdefault("schema_version", SCHEMA_VERSION)
        meta = out.get("meta")
        if not isinstance(meta, dict):
            meta = {}
        stats = meta.get("stats")
        meta["stats"] = stats if isinstance(stats, dict) else {}
        out["meta"] = meta
        self.doc = out
        return self

    @classmethod
    def load(cls, path):
        p = Path(path)
        store = cls(path=p)
        if not p.exists():
            return store
        try:
            store.import_doc(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            try:
                bak = p.with_suffix(p.suffix + ".corrupt.bak")
                if not bak.exists():
                    shutil.copy2(p, bak)
            except Exception:
                pass
        return store

    def save(self, path=None):
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("store has no path")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(self.doc, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(str(tmp), str(target))
        return target

    @property
    def entries(self):
        return self.doc.setdefault("entries", [])

    @property
    def tombstones(self):
        return self.doc.setdefault("tombstones", [])

    def find(self, entry_id):
        for e in self.entries:
            if str(e.get("id") or "") == str(entry_id):
                return e
        return None

    def add(self, entry):
        if not isinstance(entry, dict):
            return None
        item = dict(entry)
        text = normalize_text(item.get("text"))
        if len(text) < 2:
            return None
        item["text"] = text
        item.setdefault("id", "")
        item.setdefault("role", "user")
        item.setdefault("ts", 0.0)
        item.setdefault("hits", 1)
        item.setdefault("importance", 0.5)
        item.setdefault("pin", False)
        item.setdefault("previous_versions", [])
        item["schema_version"] = SCHEMA_VERSION
        self.entries.append(item)
        return item

    def update(self, entry_id, **fields):
        entry = self.find(entry_id)
        if entry is None:
            return None
        record_version(entry)
        for key, value in fields.items():
            entry[key] = value
        return entry

    def remove(self, entry_id, now=0.0, reason="deleted", hard=False):
        entry = self.find(entry_id)
        if entry is None:
            return False
        self.entries.remove(entry)
        if not hard:
            append_tombstone(self.tombstones, entry, now=now, reason=reason)
        return True

    def pin(self, entry_id, pinned=True):
        entry = self.find(entry_id)
        if entry is None:
            return False
        entry["pin"] = bool(pinned)
        return True

    # -- persisted read-only monitoring counters ---------------------------
    @property
    def meta(self):
        meta = self.doc.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            self.doc["meta"] = meta
        stats = meta.get("stats")
        if not isinstance(stats, dict):
            meta["stats"] = {}
        return meta

    def stats(self):
        raw = self.meta.get("stats") or {}
        out = {}
        for key, value in raw.items():
            try:
                out[str(key)] = int(value)
            except Exception:
                out[str(key)] = 0
        return out

    def bump_stats(self, key, amount=1):
        stats = self.meta.setdefault("stats", {})
        try:
            stats[str(key)] = int(stats.get(str(key), 0) or 0) + int(amount or 1)
        except Exception:
            stats[str(key)] = int(amount or 1)
        return stats[str(key)]

    def export(self):
        return json.loads(json.dumps(self.doc, ensure_ascii=False))
