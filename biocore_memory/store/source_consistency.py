# -*- coding: utf-8 -*-
"""Source consistency across same-topic entries (default OFF; pure, no writes)."""
from __future__ import annotations

import re

SOURCE_CONSISTENCY_ENABLED = False
SOURCE_RANKS = {"user": 0.80, "self": 0.80, "system": 0.70,
                "consolidate": 0.60, "ti_mem": 0.55, "memory": 0.50,
                "model": 0.45, "unknown": 0.35}
_PRED = ("喜欢", "讨厌", "爱", "去", "在", "是", "有", "会", "能", "住",
         "工作", "吃", "喝", "买", "看", "养", "叫", "体温", "体重")
_NEG = ("不", "没", "未", "别", "无")
_NUM = re.compile(r"\d+(?:\.\d+)?")
_TIME = re.compile(r"(今天|昨天|明天|后天|前天|周[一二三四五六日天]|"
                   r"\d{1,2}月\d{1,2}日|\d{1,2}点)")


def _text(value):
    return str(value.get("text") or "") if isinstance(value, dict) else str(value or "")


def _topic(entry):
    for key in ("topic", "event_key", "event_name"):
        value = str(entry.get(key) or "").strip().lower()
        if value:
            return value
    tags = entry.get("tags")
    if isinstance(tags, list) and tags:
        return str(tags[0]).strip().lower()
    return ""


def _clean(value):
    return re.sub(r"[\s了过的，。！？；;,.!?、]+", "", str(value or ""))


def _facts(value):
    text = _text(value)
    out = []
    for predicate in _PRED:
        pos = text.find(predicate)
        if pos < 0:
            continue
        prefix = text[max(0, pos - 1):pos]
        tail = text[pos + len(predicate):]
        out.append({"predicate": predicate,
                    "negated": prefix in _NEG,
                    "value": _clean(re.split(r"[，。！？；;,.!?\n]", tail)[0])[:24],
                    "nums": _NUM.findall(tail),
                    "times": _TIME.findall(text)})
    return out


def source_rank(entry):
    """0..1 source reliability rank (source table + memory_confidence)."""
    e = entry if isinstance(entry, dict) else {}
    name = str(e.get("source") or e.get("memory_source") or "unknown").lower()
    base = SOURCE_RANKS.get(name, SOURCE_RANKS["unknown"])
    try:
        conf = float(e.get("memory_confidence", e.get("confidence", 0.5)) or 0.5)
    except Exception:
        conf = 0.5
    prov = e.get("provenance") if isinstance(e.get("provenance"), dict) else {}
    try:
        prov_conf = float(prov.get("confidence", conf) or conf)
    except Exception:
        prov_conf = conf
    return round(max(0.0, min(1.0, 0.45 * base + 0.35 * conf + 0.20 * prov_conf)), 4)


def _contradict(a, b):
    if a["predicate"] != b["predicate"]:
        return ""
    if a["value"] and b["value"] and a["value"] != b["value"]:
        if a["nums"] and b["nums"] and a["nums"] != b["nums"]:
            return "numeric"
        if a["times"] and b["times"] and a["times"] != b["times"]:
            return "time"
        return ""
    if bool(a["negated"]) != bool(b["negated"]):
        return "negation"
    if a["nums"] and b["nums"] and a["nums"] != b["nums"]:
        return "numeric"
    return ""


def detect_conflicts(entry, entries):
    """Return {conflict, confidence, source_rank, target_ids}; default off neutral."""
    neutral = {"conflict": False, "confidence": 0.0,
               "source_rank": 0.0, "target_ids": []}
    if not SOURCE_CONSISTENCY_ENABLED:
        return neutral
    try:
        topic = _topic(entry) if isinstance(entry, dict) else ""
        fresh = _facts(entry)
        if not topic or not fresh:
            return neutral
        targets = []
        ranks = []
        details = []
        for old in entries or []:
            if not isinstance(old, dict) or _topic(old) != topic:
                continue
            for prior in _facts(old):
                for fact in fresh:
                    reason = _contradict(fact, prior)
                    if not reason:
                        continue
                    oid = str(old.get("id") or "")
                    if oid and oid not in targets:
                        targets.append(oid)
                        ranks.append(source_rank(old))
                    details.append(reason)
        if not targets:
            return neutral
        rank = max(ranks) if ranks else 0.0
        confidence = round(min(1.0, 0.5 + 0.5 * rank), 4)
        return {"conflict": True, "confidence": confidence,
                "source_rank": round(rank, 4), "target_ids": targets,
                "details": details[:8]}
    except Exception:
        return neutral
