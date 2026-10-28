# -*- coding: utf-8 -*-
"""Thin AstrBot adapter (callbacks only; never imports astrbot)."""
from __future__ import annotations


class AstrBotMemoryAdapter:
    def __init__(self, engine, session="", embed=None, now=None):
        self.engine = engine
        self.session = str(session or "")
        self.embed = embed
        self.now = now

    def remember(self, text, role="user", vector=None, importance=0.5):
        from ..event.extract import from_message
        event = from_message(text, role=role, session=self.session,
                             ts=self.now() if callable(self.now) else self.now,
                             vector=vector, importance=importance)
        return self.engine.remember(event)

    def recall(self, query, budget=3, vector=None):
        return self.engine.recall(query, budget=budget, vector=vector)

    def embed_text(self, text):
        return self.embed(text) if callable(self.embed) else None
