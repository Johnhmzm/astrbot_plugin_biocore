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
    """Return <=limit place tokens from a fixed deterministic lexicon."""
    out = []
    for m in _PLACE.finditer(str(text or "")):
        token = m.group(0)
        if token not in out:
            out.append(token)
        if len(out) >= limit:
            break
    return out


def normalize_time(text, ref_ts=None) -> str:
    """Coarse deterministic date (YYYY-MM-DD / YYYY-MM) from relative or absolute cues."""
    value = str(text or "")
    try:
        base = _dt.datetime.fromtimestamp(float(ref_ts)) if ref_ts else _dt.datetime.now()
    except Exception:
        base = _dt.datetime.now()
    rel = {"今天": 0, "昨天": -1, "前天": -2, "明天": 1, "后天": 2}
    for word, delta in rel.items():
        if word in value:
            return (base + _dt.timedelta(days=delta)).strftime("%Y-%m-%d")
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    if m:
        try:
            return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except Exception:
            pass
    m = re.search(r"(\d{1,2})月(\d{1,2})日", value)
    if m:
        try:
            return _dt.date(base.year, int(m.group(1)), int(m.group(2))).strftime("%Y-%m-%d")
        except Exception:
            pass
    if "今年" in value:
        return base.strftime("%Y")
    if "去年" in value:
        return str(base.year - 1)
    if "上个月" in value:
        return (base.replace(day=1) - _dt.timedelta(days=1)).strftime("%Y-%m")
    return ""


def cues(text, ref_ts=None) -> dict:
    """Return a cue dict: entities/place/time_coarse/event_name/id (+ time alias)."""
    value = str(text or "")
    ents = extract_entities(value)
    time_coarse = normalize_time(value, ref_ts)
    event_name = ""
    m = re.search(r"(?:去|在|到)([\u4e00-\u9fffA-Za-z0-9]{2,12})", value)
    if m:
        event_name = m.group(1)[:20]
    elif ents:
        event_name = ents[0][:20]
    return {"entities": ents, "place": extract_places(value),
            "time_coarse": time_coarse, "time": time_coarse,
            "event_name": event_name, "id": ""}
