# -*- coding: utf-8 -*-
"""Inline state tag: ask the reply call itself for the state numbers.

The reply call is owned by the host, but we control the injected content, so we
can append ONE instruction that asks for a JSON line after the reply text. When
the model complies we get the state for free (single call). When it does not,
callers fall back to the separate probe call.

This module is pure: it builds the instruction text and parses the model output.
"""
from __future__ import annotations

import json
import re

from . import entity_resolve as _er

INSTRUCTION = """【回复后附状态】
回复正文之后，另起一行，输出这一行（照抄结构，不要解释，不要包在代码块里）：
{"dims":{"goal":0.0,"blame":0.0,"hit":0.0,"involve":0.5},"situation":{"challenge":0.0,"praise":0.0,"hurt":0.0},"why":"不超过20字","c":0.8,"fact":"","entities":[{"name":"小夏","type":"人物"},{"name":"体检","type":"事件"}],"relations":[{"src":"小夏","rel":"have_checkup","dst":"体检","when":"周五"}]}

说明：
- goal 是目标顺逆（-1 受阻 到 +1 顺利），blame 是责怪对方程度（0 到 1），hit 是被击中程度（0 到 1），involve 是这件事与你的相关程度（0 到 1）
- situation 三个数表示对方这句话的意图强度：challenge 质疑、praise 夸赞、hurt 受伤
- why 用你自己的话写一句，不超过 20 字；c 是这句判断的置信度（0 到 1）
- fact 是对方透露的关于他自己的长期信息（姓名/称呼/家人/住址/工作/长期偏好），不超过 20 字；这句没有就写空字符串 ""，不要编造
- entities 是这句里值得记住的实体，最多 3 个，type 用 人物/地点/事件/话题；别名写进 aliases；没有就给空数组 []
- relations 是实体间的长期关系，最多 3 条，rel 用英文 snake_case（如 planned/located_at），when 用时间词（今天/昨天/周五/上周）；没有就给空数组 []
- 若这句话对你没有明显影响，输出 {"dims":{"goal":0.0,"blame":0.0,"hit":0.0,"involve":0.2},"why":"没有明显影响","c":0.5}"""

DIM_KEYS = {"goal": (-1.0, 1.0), "blame": (0.0, 1.0), "control": (0.0, 1.0),
            "certainty": (0.0, 1.0), "novelty": (0.0, 1.0),
            "involve": (0.0, 1.0), "hit": (0.0, 1.0)}
SIT_KEYS = ("challenge", "praise", "hurt")
_CLOSE = re.compile(r'\{\s*"dims".*?\}', re.S)
_FENCE = re.compile(r'```(?:json)?\s*(\{.*?\})\s*```', re.S)


def instruction() -> str:
    return INSTRUCTION


def _clamp(value, low, high):
    try:
        num = float(value)
    except Exception:
        return None
    if num != num:  # NaN
        return None
    return max(low, min(high, num))


def _loads(text):
    try:
        return json.loads(text)
    except Exception:
        return None


def _candidate_blocks(text):
    raw = str(text or "")
    blocks = [m.group(1) for m in _FENCE.finditer(raw)]
    for match in _CLOSE.finditer(raw):
        blocks.append(match.group(0))
    # last resort: outermost braces containing "dims"
    start = raw.find('{"dims"')
    if start >= 0:
        depth = 0
        for idx in range(start, len(raw)):
            if raw[idx] == "{":
                depth += 1
            elif raw[idx] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(raw[start:idx + 1])
                    break
    return blocks


MAX_GRAPH_ITEMS = 3


def _bounded_entities(raw) -> list:
    out = []
    if not isinstance(raw, (list, tuple)):
        return out
    for item in raw:
        if len(out) >= MAX_GRAPH_ITEMS:
            break
        if isinstance(item, str):
            name = " ".join(item.split()).strip()[:40]
            if name:
                out.append(name)
            continue
        if isinstance(item, dict):
            name = " ".join(str(item.get("name") or "").split()).strip()[:40]
            if not name:
                continue
            kind = str(item.get("type") or "").strip()[:10]
            # P0-1: the model may declare other names for the same entity.
            aliases = _er.bounded_aliases(item.get("aliases") or item.get("aka"),
                                          name)
            if aliases:
                row = {"name": name, "aliases": aliases}
                if kind:
                    row["type"] = kind
                out.append(row)
                continue
            out.append({"name": name, "type": kind} if kind else name)
    return out


def _bounded_relations(raw) -> list:
    out = []
    if not isinstance(raw, (list, tuple)):
        return out
    for item in raw:
        if len(out) >= MAX_GRAPH_ITEMS:
            break
        if not isinstance(item, dict):
            continue
        src = " ".join(str(item.get("src") or "").split()).strip()[:40]
        rel = " ".join(str(item.get("rel") or "").split()).strip()[:40]
        dst = " ".join(str(item.get("dst") or "").split()).strip()[:40]
        if not src or not rel or not dst:
            continue
        row = {"src": src, "rel": rel, "dst": dst}
        when = " ".join(str(item.get("when") or "").split()).strip()[:20]
        if when:
            row["when"] = when
        out.append(row)
    return out


def parse(text) -> dict:
    """Return {dims, situation, fact, why, confidence, source} or {} when absent."""
    raw = str(text or "")
    if not raw or "dims" not in raw:
        return {}
    for block in reversed(_candidate_blocks(raw)):
        data = _loads(block)
        if not isinstance(data, dict):
            continue
        dims_in = data.get("dims")
        if not isinstance(dims_in, dict):
            continue
        dims = {}
        for key, (low, high) in DIM_KEYS.items():
            if key not in dims_in:
                continue
            value = _clamp(dims_in.get(key), low, high)
            if value is not None:
                dims[key] = value
        situation = {}
        sit_in = data.get("situation")
        if isinstance(sit_in, dict):
            for key in SIT_KEYS:
                value = _clamp(sit_in.get(key), 0.0, 1.0)
                if value is not None:
                    situation[key] = value
        why = str(data.get("why") or "").strip()[:40]
        fact = str(data.get("fact") or "").strip()
        if len(fact) > 20:
            fact = fact[:20]
        confidence = _clamp(data.get("c"), 0.0, 1.0)
        if confidence is None:
            confidence = 0.6 if dims else 0.0
        if not dims and not situation and not fact:
            continue
        out = {"dims": dims, "situation": situation, "why": why,
               "confidence": confidence, "source": "inline_tag"}
        if fact:
            out["fact"] = fact
        entities = _bounded_entities(data.get("entities"))
        relations = _bounded_relations(data.get("relations"))
        if entities:
            out["entities"] = entities
        if relations:
            out["relations"] = relations
        return out
    return {}


def _balanced_block(raw, start):
    depth = 0
    in_str = False
    escape = False
    for idx in range(start, len(raw)):
        ch = raw[idx]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw[start:idx + 1]
    return ""


def strip(text) -> str:
    """Remove the state tag (balanced braces) from the visible reply text."""
    raw = str(text or "")
    if "dims" not in raw:
        return raw
    out = raw
    while True:
        start = out.find('{"dims"')
        if start < 0:
            break
        block = _balanced_block(out, start)
        if not block:
            break
        out = (out[:start] + out[start + len(block):])
    out = _FENCE.sub("", out)
    return re.sub(r"\n{3,}", "\n\n", out).strip()
