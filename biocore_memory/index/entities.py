# -*- coding: utf-8 -*-
"""Deterministic entity/place/time cue rules (pure regex; no LLM)."""
from __future__ import annotations
import datetime as _dt
import re

# Latin handles and @mentions only: a CJK run is not an entity without a model,
# and the place/time/stop-word lexicons that used to sit here are gone.
_ENTITY = re.compile(r"@[A-Za-z0-9_\-]{1,30}|[A-Za-z][A-Za-z0-9_'-]{1,30}")
DISABLED_REASON = "no_lexicon"


def extract_entities(text, limit=8) -> list:
    """Return <=limit entity strings (Latin handles only; no lexicon)."""
    out = []
    for m in _ENTITY.finditer(str(text or "")):
        token = m.group(0).strip()
        if len(token) < 2 or token in out:
            continue
        out.append(token[:32])
        if len(out) >= limit:
            break
    return out


def extract_places(text, limit=4) -> list:
    """Places come from the caller (entry["place"]); no place lexicon here."""
    return []


def normalize_time(text, ref_ts=None) -> str:
    """No date parsing: the caller supplies ts / valid_from / valid_to."""
    return ""



def cues(text, ref_ts=None) -> dict:
    """Return a cue dict: entities/place/time_coarse/event_name/id (+ time alias)."""
    value = str(text or "")
    ents = extract_entities(value)
    time_coarse = normalize_time(value, ref_ts)
    event_name = (ents[0][:20] if ents else "")
    return {"entities": ents, "place": extract_places(value),
            "time_coarse": time_coarse, "time": time_coarse,
            "event_name": event_name, "id": ""}
