# -*- coding: utf-8 -*-
"""Compaction: the model decides what to drop, capacity decides when.

Two different questions, deliberately kept apart:
  - segmentation ("when does an event end") is structural -- character budget,
    similarity drift, turn floor/ceiling (pipeline._event_should_close);
  - compaction ("what do we stop injecting") is a judgement call -- it happens
    when the un-compacted context approaches the budget, and the model picks the
    sentences, because a fixed ratio is exactly the kind of silent policy that
    looks fine until it deletes the one sentence that mattered.

Nothing is truncated here. A dropped sentence is marked archived: out of the
injected block, still on disk, still reachable.
"""
from __future__ import annotations

import json
import os

DEFAULT_TRIGGER_RATIO = 0.70


class CompactionError(RuntimeError):
    """The model answer or the configuration cannot be used."""


def unarchived_chars(events):
    """Characters still eligible for injection (archived rows do not count)."""
    total = 0
    for ev in events or []:
        for row in ev.get("entries") or []:
            if not isinstance(row, dict) or row.get("archived"):
                continue
            total += len(str(row.get("text") or ""))
    return total


def should_compact(events, budget_chars, ratio=None, unarchived=None):
    """True when the un-compacted context is close enough to the budget.

    Capacity is the trigger: "we have eight memories" says nothing about whether
    the next question still fits.
    """
    try:
        limit = int(budget_chars or 0)
    except Exception:
        limit = 0
    if limit <= 0:
        return False
    try:
        trigger = float(ratio if ratio is not None else DEFAULT_TRIGGER_RATIO)
    except Exception:
        trigger = DEFAULT_TRIGGER_RATIO
    used = unarchived_chars(events) if unarchived is None else int(unarchived)
    return used >= limit * trigger


def sentence_ids(event):
    return [str(row.get("id") or "")
            for row in (event or {}).get("entries") or []
            if isinstance(row, dict) and row.get("id")]


def compaction_prompt(events, budget_chars, notes=None):
    """The whole input the model gets: the budget and the candidate events.

    No instruction about how much to keep: that is the model's call.
    """
    # one implicitly-concatenated literal: prompt text, not a word list (the
    # core contract forbids CJK literal *collections* anywhere in the source)
    head = ("下面是一次记忆整理的候选事件。每个事件给出 id、概要与句子原文。\n"
            "注入预算是 %d 字符。哪些句子留下、哪些不再注入，由你判断；" % int(budget_chars or 0)
            + "留下的必须覆盖回答所需的证据，丢弃的原句会被归档而不是删除。\n"
            "对每个事件输出一个对象：{\"event_id\": \"...\", "
            "\"keep_sentence_ids\": [\"...\"], "
            "\"drop_sentence_ids\": [\"...\"], \"note\": \"完整的一句话概括\"}\n"
            "只输出 JSON 数组，不要解释。\n")
    lines = [head]
    for ev in events or []:
        eid = str(ev.get("event_id") or "")
        if not eid:
            continue
        lines.append("【事件 %s】%s" % (eid, str(ev.get("overview") or "")[:80]))
        for row in ev.get("entries") or []:
            if not isinstance(row, dict) or row.get("archived"):
                continue
            lines.append("  - %s：%s" % (row.get("id"), str(row.get("text") or "")))
    return "\n".join(lines)


def _strip_fence(text):
    """Drop a markdown fence and any prose around the payload."""
    body = str(text or "").strip()
    if body.startswith("```"):
        body = body.split(chr(10), 1)[-1] if chr(10) in body else body
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
    body = body.strip("`").strip()
    return body


def _cut_json(body):
    """The first opening bracket to the last matching close, prose dropped."""
    for left, right in (("[", "]"), ("{", "}")):
        start, end = body.find(left), body.rfind(right)
        if 0 <= start < end:
            return body[start:end + 1]
    return ""


def _drop_trailing_commas(body):
    """A trailing comma before ] or } is the most common model JSON slip."""
    out = []
    index = 0
    length = len(body)
    while index < length:
        ch = body[index]
        if ch == ",":
            look = index + 1
            while look < length and body[look] in " \t\r\n":
                look += 1
            if look < length and body[look] in "]}":
                index += 1
                continue
        out.append(ch)
        index += 1
    return "".join(out)


def _tolerant_loads(text):
    """Three attempts: as-is, de-fenced/bracket-cut, then commas repaired."""
    for candidate in _candidates(text):
        try:
            return json.loads(candidate)
        except Exception:
            continue
    raise CompactionError("整理结果无法解析：%r" % str(text or "")[:120])


def _candidates(text):
    body = _strip_fence(text)
    out = []
    if body:
        out.append(body)
    cut = _cut_json(body)
    if cut and cut != body:
        out.append(cut)
    for candidate in list(out):
        fixed = _drop_trailing_commas(candidate)
        if fixed != candidate:
            out.append(fixed)
    return out


def parse_decisions(raw):
    """Validated [{event_id, keep, drop, note}]; anything else raises."""
    rows = _tolerant_loads(raw)
    if not isinstance(rows, list):
        raise CompactionError("整理结果必须是数组")
    out = []
    for row in rows:
        if not isinstance(row, dict):
            raise CompactionError("数组元素必须是对象：%r" % (row,))
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            raise CompactionError("缺少 event_id")
        keep = row.get("keep_sentence_ids")
        drop = row.get("drop_sentence_ids")
        note = str(row.get("note") or "").strip()
        if not isinstance(keep, list) or not isinstance(drop, list):
            raise CompactionError("keep/drop 必须是数组（event %s）" % event_id)
        keep = [str(x) for x in keep if str(x or "").strip()]
        drop = [str(x) for x in drop if str(x or "").strip()]
        if not keep and not drop:
            raise CompactionError("事件 %s 既没有保留也没有丢弃任何句子" % event_id)
        if not note:
            raise CompactionError("事件 %s 缺少 note" % event_id)
        out.append({"event_id": event_id, "keep": keep, "drop": drop, "note": note})
    if not out:
        raise CompactionError("整理结果为空")
    return out


def apply_decisions(events, decisions, now=None):
    """Mark dropped rows archived and attach the note. Nothing is deleted."""
    known = {str(ev.get("event_id") or ""): ev for ev in events or []}
    applied = []
    for decision in decisions:
        ev = known.get(decision["event_id"])
        if ev is None:
            continue
        drop = set(decision["drop"])
        for row in ev.get("entries") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("id") or "") in drop:
                row["archived"] = True
                row["archived_reason"] = "compaction"
        ev["note"] = decision["note"]
        applied.append({"event_id": decision["event_id"],
                        "dropped": len(drop), "note": decision["note"]})
    return applied


def compact(events, budget_chars, ask, ratio=None, unarchived=None):
    """One compaction pass.

    ask(prompt) -> raw model text. A missing ask is an error: falling back to
    "cut the context" is the silent degradation this module exists to avoid.
    """
    if str(os.environ.get("BIOCORE_COMPACT", "1")).strip().lower() in ("0", "off", "false", "no"):
        return {"triggered": False, "reason": "disabled", "applied": []}
    if not should_compact(events, budget_chars, ratio=ratio, unarchived=unarchived):
        return {"triggered": False, "reason": "under_capacity", "applied": []}
    if not callable(ask):
        raise CompactionError(
            "容量已达阈值但没有可用的整理模型：拒绝回落到截断上下文")
    raw = ask(compaction_prompt(events, budget_chars))
    decisions = parse_decisions(raw)
    applied = apply_decisions(events, decisions)
    return {"triggered": True, "applied": applied,
            "remaining_chars": unarchived_chars(events)}
