# -*- coding: utf-8 -*-
"""BioCore model layer package.

Phase 1: deterministic rendering only.

This package is the future home of the model layer (render/contract/think/
route). It must stay dependency-free from the plugin's L3 wiring: it may only
use the Python standard library, so it can be imported by tests without
AstrBot.

The biological layer (L1) never writes prompt text; the interpretation layer
(L2) owns prompt construction and parsing, and this package owns the
deterministic text that L2 injects.
"""
from __future__ import annotations

from .render import (
    TEXT_LIMIT,
    TEXT_LEGEND_LINES,
    derive_event_links,
    render_compact,
    render_semantic,
    render_text,
    semantic_brief,
    text_legend,
)

__all__ = [
    "TEXT_LIMIT",
    "TEXT_LEGEND_LINES",
    "derive_event_links",
    "render_compact",
    "render_semantic",
    "render_text",
    "semantic_brief",
    "text_legend",
]
