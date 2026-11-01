# -*- coding: utf-8 -*-
"""Turn the inline state tag's optional graph fields into graph writes.

task-135: the reply call already carries the state tag; we reuse that single
call for entity/relation extraction (no extra LLM call). This module is pure:
it validates and bounds the model output and converts Chinese type/time words,
then applies the result through entity_graph. Failures stay silent upstream.
"""
from __future__ import annotations

import re
import time

from . import entity_graph as _eg
from . import entity_resolve as _er

MAX_ENTITIES = 3
MAX_RELATIONS = 3
MAX_NAME_CHARS = 40

TYPE_ALIASES = {
    "person": ("person", "人物", "人", "家伙", "朋友"),
    "place": ("place", "地点", "地方", "场所", "城市"),
    "event": ("event", "事件", "事情", "活动", "计划"),
    "topic": ("topic", "话题", "主题", "事物", "东西"),
}
TYPE_LABELS = {"person": "人物", "place": "地点", "event": "事件",
               "topic": "话题"}
REL_LABELS = {
    "planned": "计划", "located_at": "位于", "lives_at": "住在",
    "works_at": "工作于", "afraid_of": "害怕", "likes": "喜欢",
    "dislikes": "讨厌", "belongs_to": "属于", "has_state": "有状态",
    "have_checkup": "要体检", "knows": "认识", "family_of": "家人",
}

_REL_TIME = re.compile(r"(\d+)\s*(分钟|小时|天|周|个月|月)\s*前")
_WEEKDAY = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5,
            "日": 6, "天": 6, "七": 6}
_WEEKDAY_RE = re.compile(r"(上|这|本|下)?\s*(?:周|星期|礼拜)([一二三四五六日天七])")
_MONTHDAY_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")


def canonical_type(value, default="topic"):
    text = " ".join(str(value or "").split()).strip().lower()
    if not text:
        return default
    for key, aliases in TYPE_ALIASES.items():
        if text == key or text in [alias.lower() for alias in aliases]:
            return key
    return default


def type_label(kind):
    return TYPE_LABELS.get(canonical_type(kind), TYPE_LABELS["topic"])


def rel_label(rel):
    key = str(rel or "").strip().lower()
    return REL_LABELS.get(key, key)


def when_to_ts(when, now=None):
    """Best-effort timestamp for a Chinese time word; 0.0 when unknown."""
    text = " ".join(str(when or "").split()).strip()
    if not text:
        return 0.0
    try:
        base = float(now if now is not None else time.time())
    except Exception:
        return 0.0
    if base <= 0:
        return 0.0
    if text in ("今天", "今日", "刚才", "刚刚", "本日"):
        return base
    if text in ("昨天", "昨日"):
        return base - 86400.0
    if text == "前天":
        return base - 2 * 86400.0
    if text == "明天":
        return base + 86400.0
    if text == "后天":
        return base + 2 * 86400.0
    if text in ("上周", "上星期", "上礼拜"):
        return base - 7 * 86400.0
    if text in ("本周", "这周", "这星期", "这礼拜"):
        return base
    if text in ("下周", "下星期", "下礼拜"):
        return base + 7 * 86400.0
    match = _REL_TIME.search(text)
    if match:
        try:
            amount = float(match.group(1))
        except Exception:
            return 0.0
        unit = match.group(2)
        if unit == "分钟":
            return base - amount * 60.0
        if unit == "小时":
            return base - amount * 3600.0
        if unit == "天":
            return base - amount * 86400.0
        if unit == "周":
            return base - amount * 7 * 86400.0
        return base - amount * 30 * 86400.0
    match = _WEEKDAY_RE.search(text)
    if match:
        target = _WEEKDAY.get(match.group(2))
        if target is None:
            return 0.0
        try:
            current = int(time.localtime(base).tm_wday)
        except Exception:
            return 0.0
        delta = (current - target) % 7
        stamp = base - delta * 86400.0
        prefix = match.group(1) or ""
        if prefix == "上":
            stamp -= 7 * 86400.0
        elif prefix == "下":
            stamp += (7 if delta == 0 else 7) * 86400.0
        return stamp
    match = _MONTHDAY_RE.search(text)
    if match:
        try:
            month = int(match.group(1))
            day = int(match.group(2))
            current_tm = time.localtime(base)
            candidate = time.mktime((current_tm.tm_year, month, day,
                                     12, 0, 0, 0, 0, -1))
            if candidate > base:
                candidate = time.mktime((current_tm.tm_year - 1, month, day,
                                         12, 0, 0, 0, 0, -1))
            return float(candidate)
        except Exception:
            return 0.0
    return 0.0


def _clean_name(value):
    return " ".join(str(value or "").split()).strip()[:MAX_NAME_CHARS]


def _dedupe(rows):
    out = []
    seen = set()
    for row in rows:
        key = _eg._norm(row["name"])
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def extract(tag, now=None):
    """Validate the tag graph fields: at most 3 entities and 3 relations."""
    result = {"entities": [], "relations": []}
    if not isinstance(tag, dict):
        return result
    raw_entities = tag.get("entities")
    rows = []
    if isinstance(raw_entities, (list, tuple)):
        for item in raw_entities:
            if isinstance(item, str):
                name = _clean_name(item)
                if name:
                    rows.append({"name": name, "type": "topic"})
            elif isinstance(item, dict):
                name = _clean_name(item.get("name"))
                if name:
                    row = {"name": name,
                           "type": canonical_type(item.get("type"))}
                    # P0-1: optional model-declared aliases for this entity.
                    aliases = _er.bounded_aliases(
                        item.get("aliases") or item.get("aka"), name)
                    if aliases:
                        row["aliases"] = aliases
                    rows.append(row)
    rows = _dedupe(rows)[:MAX_ENTITIES]
    by_norm = {_eg._norm(row["name"]): row for row in rows}
    relations = []
    raw_relations = tag.get("relations")
    if isinstance(raw_relations, (list, tuple)):
        for item in raw_relations:
            if len(relations) >= MAX_RELATIONS:
                break
            if not isinstance(item, dict):
                continue
            src = _clean_name(item.get("src"))
            dst = _clean_name(item.get("dst"))
            rel = " ".join(str(item.get("rel") or "").split()).strip().lower()
            rel = rel.replace(" ", "_")[:MAX_NAME_CHARS]
            if not src or not dst or not rel or _eg._norm(src) == _eg._norm(dst):
                continue
            # Bound the entity set: relation endpoints join only while slots last.
            for name in (src, dst):
                key = _eg._norm(name)
                if key in by_norm:
                    continue
                if len(rows) >= MAX_ENTITIES:
                    break
                row = {"name": name, "type": "topic"}
                rows.append(row)
                by_norm[key] = row
            if _eg._norm(src) not in by_norm or _eg._norm(dst) not in by_norm:
                continue
            relation = {"src": by_norm[_eg._norm(src)]["name"],
                        "rel": rel,
                        "dst": by_norm[_eg._norm(dst)]["name"],
                        "confidence": 0.6}
            when = " ".join(str(item.get("when") or "").split()).strip()[:20]
            if when:
                relation["when"] = when
                relation["ts"] = when_to_ts(when, now)
            relations.append(relation)
    result["entities"] = rows[:MAX_ENTITIES]
    result["relations"] = relations
    return result


def apply(store, extracted, now=None, source_entry=""):
    """Upsert one extracted batch into a GraphStore (silent on bad rows)."""
    applied = {"entities": 0, "relations": 0}
    if not isinstance(extracted, dict):
        return applied
    stamp = float(now if now is not None else time.time())
    for row in extracted.get("entities") or []:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        store, _eid = _eg.upsert_entity(
            store, row["name"], type=canonical_type(row.get("type")),
            aliases=row.get("aliases") or None, now=stamp,
            entry_id=source_entry)
        applied["entities"] += 1
    for row in extracted.get("relations") or []:
        if not isinstance(row, dict):
            continue
        edge_ts = row.get("ts")
        if not edge_ts:
            edge_ts = when_to_ts(row.get("when"), stamp)
        if not edge_ts:
            edge_ts = stamp
        store, _rid = _eg.upsert_edge(
            store, row.get("src"), row.get("rel"), row.get("dst"),
            ts=edge_ts, confidence=row.get("confidence", 0.6),
            source_entry=source_entry, now=stamp)
        applied["relations"] += 1
    return applied
