# -*- coding: utf-8 -*-
"""Notes bridge: attach an A-MEM style note to one memory entry.

Calls event.notes.make_note(text, tags, links) and stores the bounded result
as metadata["note"] = {title, summary, tags, links}. Only metadata is written:
text / id / role / ts / vector are never modified.

Interface:
  enrich_entry(entry, enabled=None, tags=None, links=None) -> entry

The module is disabled by default (NOTES_LINK_ENABLED=False): callers gate on
'enabled' before writing. Passing enabled=False forces a no-op.
No IO, no LLM, no host imports.
"""
from __future__ import annotations

from .notes import make_note

enabled = False
NOTES_LINK_ENABLED = enabled

NOTE_KEY = "note"
MAX_LINKS = 8
MAX_SOURCE_ITEMS = 32


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return list(value.keys())
    try:
        return list(value)
    except TypeError:
        return [value]


def _entry_tags(entry):
    tags = []
    for key in ("tags", "labels", "topics"):
        tags.extend(_as_list(entry.get(key)))
    cue = entry.get("cue_index")
    if isinstance(cue, dict):
        tags.extend(_as_list(cue.get("entities")))
        tags.extend(_as_list(cue.get("place")))
        tags.append(cue.get("event_name"))
    metadata = entry.get("metadata")
    if isinstance(metadata, dict):
        tags.extend(_as_list(metadata.get("tags")))
    return tags[:MAX_SOURCE_ITEMS]


def _entry_links(entry):
    links = []
    for key in ("related_ids", "links"):
        links.extend(_as_list(entry.get(key)))
    cue = entry.get("cue_index")
    if isinstance(cue, dict):
        links.extend(_as_list(cue.get("related_ids")))
    metadata = entry.get("metadata")
    if isinstance(metadata, dict):
        links.extend(_as_list(metadata.get("links")))
    return links[:MAX_SOURCE_ITEMS]


def enrich_entry(entry, enabled=None, tags=None, links=None):
    """Attach metadata["note"] and return the entry (unchanged if disabled)."""
    if enabled is False or not isinstance(entry, dict):
        return entry
    text = entry.get("text") or entry.get("content") or ""
    if not str(text or "").strip():
        return entry
    note_tags = tags if tags is not None else _entry_tags(entry)
    note_links = links if links is not None else _entry_links(entry)
    note = make_note(text, tags=note_tags, links=note_links)
    metadata = entry.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        entry["metadata"] = metadata
    metadata[NOTE_KEY] = note
    return entry


__all__ = ["enabled", "NOTES_LINK_ENABLED", "enrich_entry", "NOTE_KEY",
           "MAX_LINKS"]
