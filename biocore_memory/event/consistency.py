# -*- coding: utf-8 -*-
"""Deterministic old/new fact conflict detection (default OFF; no writes)."""
from __future__ import annotations

import re

CONSISTENCY_ENABLED = False

_PRED = ("喜欢", "讨厌", "爱", "去", "在", "是", "有", "会", "能", "住", "工作",
         "吃", "喝", "买", "看", "养", "叫", "生日", "体温", "体重", "想要")
_NEG = ("不", "没", "未", "别", "无")
_TIME = re.compile(r"(今天|昨天|明天|后天|前天|周[一二三四五六日天]|"
                   r"\d{1,2}月\d{1,2}日|\d{1,2}点|\d{1,2}:\d{2})")
_NUM = re.compile(r"\d+(?:\.\d+)?")
_ENTITY = re.compile(r"[\u4e00-\u9fff]{2,8}")


def _text(value):
    if isinstance(value, dict):
        return str(value.get("text") or "")
    return str(value or "")


def _clean(value):
    return re.sub(r"[\s了过的，。！？；;,.!?、]+", "", str(value or ""))


def extract_facts(value):
    """Return deterministic fact slots: entity/predicate/value/negated/nums/time."""
    text = _text(value)
    if not text:
        return []
    facts = []
    for predicate in _PRED:
        pos = text.find(predicate)
        if pos < 0:
            continue
        prefix = text[max(0, pos - 1):pos]
        negated = prefix in _NEG
        subject = _clean(text[:pos])
        if subject and subject[-1] in _NEG:
            subject = subject[:-1]
        for token in _TIME.findall(subject):
            subject = subject.replace(token, "")
        entity = subject[-8:]
        tail = text[pos + len(predicate):]
        value = _clean(re.split(r"[，。！？；;,.!?\n]", tail)[0])[:24]
        nums = _NUM.findall(tail)
        times = _TIME.findall(text)
        facts.append({"entity": entity, "predicate": predicate, "value": value,
                      "negated": bool(negated), "nums": nums, "times": times})
    return facts


def _pair_conflict(a, b):
    if not a or not b or a.get("predicate") != b.get("predicate"):
        return ""
    if a.get("entity") and b.get("entity") and a["entity"] != b["entity"]:
        return ""
    if a.get("value") and b.get("value") and a["value"] != b["value"]:
        if a.get("nums") and b.get("nums") and a["nums"] != b["nums"]:
            return "numeric"
        if a.get("times") and b.get("times") and a["times"] != b["times"]:
            return "time"
        return ""
    if bool(a.get("negated")) != bool(b.get("negated")):
        return "negation"
    if a.get("nums") and b.get("nums") and a["nums"] != b["nums"]:
        return "numeric"
    if a.get("times") and b.get("times") and a["times"] != b["times"]:
        return "time"
    return ""


def detect_conflicts(entry, old_entries):
    """Return {conflict, uncertainty, target_ids, details}; default off is neutral."""
    neutral = {"conflict": False, "uncertainty": 0.0, "target_ids": [], "details": []}
    if not CONSISTENCY_ENABLED:
        return neutral
    try:
        new_facts = extract_facts(entry)
        if not new_facts:
            return neutral
        details = []
        targets = []
        for old in old_entries or []:
            if not isinstance(old, dict):
                continue
            old_facts = extract_facts(old)
            for fresh in new_facts:
                for prior in old_facts:
                    reason = _pair_conflict(fresh, prior)
                    if not reason:
                        continue
                    oid = str(old.get("id") or "")
                    if oid and oid not in targets:
                        targets.append(oid)
                    details.append({"reason": reason,
                                    "old": prior, "new": fresh})
        if not details:
            return neutral
        uncertainty = min(1.0, 0.55 + 0.15 * (len(details) - 1))
        return {"conflict": True, "uncertainty": round(uncertainty, 3),
                "target_ids": targets, "details": details[:10]}
    except Exception:
        return neutral


def annotate(entry, result):
    """Attach conflict metadata to a copy; never overwrites the old facts/text."""
    row = dict(entry) if isinstance(entry, dict) else {"text": str(entry or "")}
    if not isinstance(result, dict) or not result.get("conflict"):
        return row
    row["conflict"] = True
    row["uncertainty"] = float(result.get("uncertainty") or 0.0)
    row["conflict_with"] = list(result.get("target_ids") or [])
    return row
