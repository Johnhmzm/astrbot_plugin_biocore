# -*- coding: utf-8 -*-
"""Deterministic entity/place/time cue rules (pure regex; no LLM)."""
from __future__ import annotations
import datetime as _dt
import re

_ENTITY = re.compile(r"@[A-Za-z0-9_\-]{1,30}|[A-Za-z][A-Za-z0-9_'-]{1,30}|[\u4e00-\u9fff]{2,8}")
_PLACE = re.compile(r"(家|公司|学校|医院|咖啡馆|餐厅|公园|车站|机场|商场|宿舍|图书馆|办公室|教室|超市)")
_TIME = re.compile(r"(今天|昨天|前天|明天|后天|上周|下周|上个月|今年|去年|"
                   r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}月\d{1,2}日|\d{1,2}:\d{2})")
_STOP = {"今天", "昨天", "明天", "我们", "你们", "他们", "这个", "那个", "什么", "怎么",
         "因为", "所以", "但是", "然后", "如果", "就是", "不是", "没有", "可以", "一个"}


def extract_entities(text, limit=8) -> list:
    """Return <=limit deterministic entity strings (Chinese/Latin/@handles)."""
    out = []
    for m in _ENTITY.finditer(str(text or "")):
        token = m.group(0).strip()
        if len(token) < 2 or token in _STOP or token in out:
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
