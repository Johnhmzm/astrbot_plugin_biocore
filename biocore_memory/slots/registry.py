# -*- coding: utf-8 -*-
"""Slot registry: bounded attention-window slots (host-neutral, no LLM/IO)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_SLOT_COUNT = 4
MAX_SLOTS = 7
MAX_DYNAMIC = 3
MAX_ITEMS = 3
DEFAULT_BUDGET_CHARS = 90
TOTAL_BUDGET_CHARS = 360
FIXED_KINDS = ("identity", "relationship", "promises_open_loops", "recent_changes")


def _text(item):
    if isinstance(item, dict):
        return str(item.get("text") or item.get("content") or "")
    return str(item or "")


@dataclass
class Slot:
    slot_id: str
    kind: str
    items: list = field(default_factory=list)
    budget_chars: int = DEFAULT_BUDGET_CHARS
    order: int = 0
    created_ts: float = 0.0
    updated_ts: float = 0.0

    def chars(self):
        return sum(len(_text(x)) for x in self.items)

    def add(self, item):
        text = _text(item)
        if not text or len(self.items) >= MAX_ITEMS:
            return False
        if self.chars() + len(text) > self.budget_chars:
            return False
        self.items.append(item)
        return True

    def remove(self, item_id):
        before = len(self.items)
        self.items = [x for x in self.items
                      if str(x.get("id") if isinstance(x, dict) else x) != str(item_id)]
        return len(self.items) != before

    def as_dict(self):
        return {"slot_id": self.slot_id, "kind": self.kind,
                "items": [dict(x) if isinstance(x, dict) else x for x in self.items],
                "budget_chars": int(self.budget_chars), "order": int(self.order),
                "created_ts": float(self.created_ts), "updated_ts": float(self.updated_ts)}


@dataclass
class SlotRegistry:
    enabled: bool = False
    slots: list = field(default_factory=list)
    dynamic_ids: list = field(default_factory=list)

    def __post_init__(self):
        if not self.slots:
            self.slots = [Slot(slot_id=k, kind=k, order=i)
                          for i, k in enumerate(FIXED_KINDS)]

    def get(self, slot_id):
        return next((s for s in self.slots if s.slot_id == slot_id), None)

    def fixed(self):
        return [s for s in self.slots if s.slot_id in FIXED_KINDS]

    def dynamic(self):
        return [s for s in self.slots if s.slot_id not in FIXED_KINDS]

    def total_chars(self):
        return sum(s.chars() for s in self.slots)

    def add_dynamic(self, topic, slot_id=None):
        if not self.enabled or not str(topic or "").strip():
            return None
        if len(self.dynamic()) >= MAX_DYNAMIC or len(self.slots) >= MAX_SLOTS:
            return None
        sid = str(slot_id or ("topic:" + str(topic).strip()[:24]))
        if self.get(sid):
            return self.get(sid)
        slot = Slot(slot_id=sid, kind="topic", order=len(self.slots))
        self.slots.append(slot)
        self.dynamic_ids.append(sid)
        return slot

    def add_item(self, slot_id, item):
        if not self.enabled:
            return False
        slot = self.get(slot_id)
        return bool(slot and slot.add(item))

    def remove(self, slot_id, item_id=None):
        slot = self.get(slot_id)
        if not slot:
            return False
        if item_id is None:
            self.slots = [x for x in self.slots if x.slot_id != slot_id]
            self.dynamic_ids = [x for x in self.dynamic_ids if x != slot_id]
            return True
        return slot.remove(item_id)

    def to_dict(self):
        return {"enabled": bool(self.enabled),
                "dynamic_ids": list(self.dynamic_ids),
                "slots": [s.as_dict() for s in self.slots],
                "total_chars": self.total_chars()}

    @classmethod
    def from_dict(cls, data):
        d = data if isinstance(data, dict) else {}
        reg = cls(enabled=bool(d.get("enabled", False)))
        raw = d.get("slots") if isinstance(d.get("slots"), list) else None
        if raw:
            reg.slots = []
            for row in raw:
                if not isinstance(row, dict):
                    continue
                reg.slots.append(Slot(
                    slot_id=str(row.get("slot_id") or ""),
                    kind=str(row.get("kind") or "topic"),
                    items=list(row.get("items") or []),
                    budget_chars=int(row.get("budget_chars") or DEFAULT_BUDGET_CHARS),
                    order=int(row.get("order") or 0),
                    created_ts=float(row.get("created_ts") or 0.0),
                    updated_ts=float(row.get("updated_ts") or 0.0)))
        reg.dynamic_ids = [s.slot_id for s in reg.slots if s.slot_id not in FIXED_KINDS]
        return reg
