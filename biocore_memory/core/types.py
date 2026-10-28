# -*- coding: utf-8 -*-
"""Host-neutral data structures for the memory layer.

Interface summary:
  MemoryEntry(id, text, role, session, ts, vector, importance, pin, metadata, scope)
  Cue(entities, place, time, event_name, id)
  EventVector(intensity, self_relevance, schema_conflict, relation_weight,
              novelty, unresolved, repetition)
  ThreadCard(id, text, ts); RelayCard(identity, relationship, open_loops,
              recent, pins)
Each type exposes from_dict/to_dict (signatures below); no host imports.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, field


@dataclass
class MemoryEntry:
    id: str = ""
    text: str = ""
    role: str = "user"
    session: str = ""
    ts: float = 0.0
    vector: list = field(default_factory=list)
    importance: float = 0.5
    pin: bool = False
    metadata: dict = field(default_factory=dict)
    scope: str = "default"

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            return cls(text=str(value or ""))
        return cls(**{k: value[k] for k in cls.__dataclass_fields__ if k in value})

    def to_dict(self):
        out = asdict(self)
        metadata = out.pop("metadata", {}) or {}
        out.update(metadata)
        return out


@dataclass
class Cue:
    entities: list = field(default_factory=list)
    place: list = field(default_factory=list)
    time: list = field(default_factory=list)
    event_name: str = ""
    id: str = ""

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            return cls()
        return cls(**{k: value[k] for k in cls.__dataclass_fields__ if k in value})

    def to_dict(self):
        return asdict(self)


@dataclass
class EventVector:
    intensity: float = 0.0
    self_relevance: float = 0.0
    schema_conflict: float = 0.0
    relation_weight: float = 0.0
    novelty: float = 0.0
    unresolved: float = 0.0
    repetition: float = 0.0

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            return cls()
        return cls(**{k: value[k] for k in cls.__dataclass_fields__ if k in value})

    def to_dict(self):
        return asdict(self)

    def as_dict(self):
        """Compatibility alias for to_dict (older call sites)."""
        return self.to_dict()


@dataclass
class ThreadCard:
    id: str = ""
    text: str = ""
    ts: float = 0.0

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            return cls()
        return cls(**{k: value[k] for k in cls.__dataclass_fields__ if k in value})

    def to_dict(self):
        return asdict(self)


@dataclass
class RelayCard:
    identity: list = field(default_factory=list)
    relationship: list = field(default_factory=list)
    open_loops: list = field(default_factory=list)
    recent: list = field(default_factory=list)
    pins: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            return cls()
        return cls(**{k: value[k] for k in cls.__dataclass_fields__ if k in value})

    def to_dict(self):
        return asdict(self)