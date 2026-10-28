# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class MemoryEvent:
    text: str = ""
    role: str = "user"
    session: str = ""
    ts: float = 0.0
    id: str = ""
    vector: list = field(default_factory=list)
    importance: float = 0.5
    self_relevance: float = 0.0
    metadata: dict = field(default_factory=dict)
