# -*- coding: utf-8 -*-
"""BioCore memory layer (pure Python; no astrbot, no prompt text).

Public API: MemoryEngine, MemoryStore, MemoryEvent, recall_entries,
eviction_score, identity_snapshot, relay_card, thread_card.
"""
from __future__ import annotations

from .engine import MemoryEngine
from .store import MemoryStore
from .event._types import MemoryEvent
from .recall import recall_entries
from .evict import eviction_score
from .identity import identity_snapshot
from .relay import relay_card
from .thread import thread_card
from . import identity, index  # noqa: F401 (compatibility for callers)

__all__ = ["MemoryEngine", "MemoryStore", "MemoryEvent", "recall_entries",
           "eviction_score", "identity_snapshot", "relay_card", "thread_card"]
