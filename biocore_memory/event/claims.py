# -*- coding: utf-8 -*-
"""Claims: memory units that already carry the inference.

A claim is (subject, attribute, value, when, status). Dates are resolved and
subjects are bound at write time, so answering becomes a lookup instead of an
inference. No lexicon: the prompt states the fields and the status test.
"""
from __future__ import annotations

import json

from .timerender import normalize_relative_time

MAX_CLAIMS_PER_EVENT = 12
STATUSES = ("current", "superseded", "coexist", "private")
# Source -> confidence (base table from BIOCORE-LAYER-MEMORY-v1 §1)
SOURCE_CONFIDENCE = {"direct": 0.82, "media": 0.70, "told": 0.62,
                     "unknown": 0.55, "inferred": 0.45}
LOW_CONFIDENCE = 0.60


def _known_lines(known):
    keys = [str(k) for k in (known or [])][:60]
    return "\n".join("- " + k for k in keys) if keys else "（空）"


def claims_prompt(event, known=None, day=None, threads=None):
    start = int(event.get("start") or 0)
    end = int(event.get("end") or 0)
    return (
        "从下面这段对话里抽出“断言”。每条断言是一个四元组。\n"
        "【已有键｜必须复用其中写法，确实没有才新建“主体·属性”】\n%s\n\n"
        "【已有线索｜同一件事必须用同一条线索名，确实没有才新建】\n%s\n\n"
        "【对话｜本段日期 %s】\n%s\n\n"
        "规则："
        "一、主体写具体的人名或物件名，不要用“我/她/他/那个”；"
        "二、属性用已有键的写法，稳定，不要同义改写；"
        "三、值写成可以直接回答问题的短语，数字与日期写全；"
        "四、把“明天/前天/下周二”这类相对说法按本段日期换算成 YYYY-MM-DD；"
        "五、状态只能是 current（当前有效）、superseded（被后文更正，不再有效）、"
        "coexist（两种说法并存，记录不足以确定）、private（不能对第三方透露）；"
        "六、只抽对话里明确说过的，不要推测；"
        "七、每条给 source：direct（用户亲口说）、told（他人转述）、media（图片/文件）、"
        "inferred（助手推断）、unknown（不确定）；"
        "八、每条给 entity：这件事牵涉的那个人/那个物件/那个地点（写名词，不写代词），"
        "同一个人或同一个物件在不同断言里必须写成同一个词；"
        "九、每条给 thread：这条属于“哪件事”（例如“门口灯箱”而不是“师傅”），"
        "同一次事情的多条断言必须用同一个 thread，能复用已有线索就复用；"
        "十、一条消息里可能包含好几个可以被追问的事实（时间、数量、地点、人名、约定、偏好、"
        "先后变化），每一个都要单独抽成一条，不要合并、不要只抽主题、不要因为“看起来琐碎”而省略；"
        "宁可多抽，不可漏抽，同一段最多 12 条。\n"
        "只输出 JSON：{\"overview\": \"...30字以内\", \"claims\": "
        "[{\"subject\": \"...\", \"attr\": \"...\", \"value\": \"...\", "
        "\"status\": \"current\", \"source\": \"direct\", \"entity\": \"...\", \"thread\": \"...\", \"note\": \"\"}]}"
        % (_known_lines(known), _known_lines(threads), str(day or ""),
           str(event.get("text") or "").strip())
    )


class ParseError(ValueError):
    """A model answer that could not be read; the caller must log it."""


def parse_claims(raw, day=None):
    """Tolerant JSON read; returns (overview, claims)."""
    try:
        from . import json_tolerant as _jt
        data = _jt.loads(raw, prefer="{")
    except Exception as exc:
        # never silent: the caller records why, so a 0-claim event has a reason
        raise ParseError(str(exc))
    if not isinstance(data, dict):
        raise ParseError("model answer is not a JSON object")
    overview = str(data.get("overview") or "").strip()
    out = []
    for item in data.get("claims") or []:
        if not isinstance(item, dict):
            continue
        subject = str(item.get("subject") or "").strip()
        attr = str(item.get("attr") or "").strip()
        value = str(item.get("value") or "").strip()
        if not subject or not attr or not value:
            continue
        status = str(item.get("status") or "current").strip().lower()
        if status not in STATUSES:
            status = "current"
        try:
            value = normalize_relative_time(value, day) if day else value
        except Exception:
            pass
        source = str(item.get("source") or "unknown").strip().lower()
        if source not in SOURCE_CONFIDENCE:
            source = "unknown"
        out.append({"subject": subject, "attr": attr, "value": value,
                    "entity": str(item.get("entity") or "").strip(),
                    "thread": str(item.get("thread") or "").strip(),
                    "status": status, "source": source,
                    "confidence": SOURCE_CONFIDENCE[source],
                    "note": str(item.get("note") or "").strip()})
    return overview, out[:MAX_CLAIMS_PER_EVENT]




_CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_to_int(text):
    """Small Chinese numeral reader for dates/months (十, 十八, 二十)."""
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if "十" not in text:
        return _CN_NUM.get(text)
    head, _, tail = text.partition("十")
    tens = _CN_NUM.get(head, 1) if head else 1
    ones = _CN_NUM.get(tail, 0) if tail else 0
    return tens * 10 + ones


def value_key(value):
    """Comparable form of a value: dates to MM-DD, annotations and spacing dropped."""
    import re as _re
    text = str(value or "")
    text = _re.sub(r"[（(][^）)]*[）)]", "", text)      # drop parenthetical notes
    text = text.replace(" ", "").replace("\u3000", "")
    text = text.strip("。，,.;；!！?？")
    m = _re.search(r"(\d{4})\D{0,2}(\d{1,2})\D{0,2}(\d{1,2})", text)
    if m:
        return "%02d-%02d" % (int(m.group(2)), int(m.group(3)))
    m = _re.search(r"(\d{1,2})\s*月\s*(\d{1,2})", text)
    if m:
        return "%02d-%02d" % (int(m.group(1)), int(m.group(2)))
    m = _re.search(r"([零一二两三四五六七八九十]+)\s*月\s*([零一二两三四五六七八九十]+)", text)
    if m:
        month, day = _cn_to_int(m.group(1)), _cn_to_int(m.group(2))
        if month and day:
            return "%02d-%02d" % (month, day)
    return text.rstrip("号日")


def confidence_of(base, repeats=1, age_days=None):
    """base + repetition bonus - small age decay (keeps facts, doubts staleness)."""
    conf = float(base) + 0.03 * max(0, int(repeats) - 1)
    conf = min(conf, 0.95)
    if age_days is not None:
        try:
            conf -= min(0.15, 0.15 * (float(age_days) / 30.0))
        except Exception:
            pass
    return round(max(0.05, conf), 3)



def combined_prompt(event, state=None, known=None, day=None, threads=None):
    """One call for everything: rolling state, event overview and the claims."""
    start = int(event.get("start") or 0)
    end = int(event.get("end") or 0)
    state_lines = []
    for key in sorted(state or {}):
        item = state[key] or {}
        state_lines.append("%s = %s（%s）" % (key, item.get("value"), item.get("status") or "current"))
    return (
        "看下面这段对话，一次性输出三样东西：状态更新、事件概览、断言清单。\n"
        "【当前状态】\n%s\n\n"
        "【已有键｜优先复用】\n%s\n\n"
        "【已有线索｜优先复用】\n%s\n\n"
        "【对话｜本段日期 %s】\n%s\n\n"
        "规则："
        "一、status 只能是 current/superseded/coexist/private；"
        "二、键写成“主体·属性”，能复用已有键就复用；"
        "三、把“明天/前天/下周二”按本段日期换算成 YYYY-MM-DD；"
        "四、一条消息里每个可被追问的事实（时间、数量、地点、人名、约定、偏好、前后变化）"
        "都要单独抽成一条断言，宁可多抽不可漏抽，本段最多 12 条；"
        "五、每条断言给 source（direct/told/media/inferred/unknown）与 entity（人名或物件名）；"
        "六、thread 写“这件事叫什么”，同一件事用同一条线索；"
        "七、state 只写本段确实变化的键值，没变化就给空对象；"
        "八、overview 不超过 60 字，写清“谁·什么·什么值”。\n"
        "只输出 JSON：{\"overview\": \"...\", \"state\": {\"主体·属性\": {\"value\": \"...\", "
        "\"status\": \"current\"}}, \"claims\": [{\"subject\": \"...\", \"attr\": \"...\", "
        "\"value\": \"...\", \"status\": \"current\", \"source\": \"direct\", "
        "\"entity\": \"...\", \"thread\": \"...\"}]}"
        % ("\n".join(state_lines) if state_lines else "（空）", _known_lines(known),
           _known_lines(threads), str(day or ""), str(event.get("text") or "").strip())
    )


def parse_combined(raw, day=None):
    """(overview, state, claims) from the single combined call."""
    data = {}
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            data = json.loads(text[start:end + 1])
        except Exception:
            data = {}
    overview = str(data.get("overview") or "").strip()
    state = {}
    for key, item in (data.get("state") or {}).items():
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip()
        if not value:
            continue
        status = str(item.get("status") or "current").strip().lower()
        if status not in STATUSES:
            status = "current"
        state[str(key)] = {"value": value, "status": status,
                           "note": str(item.get("note") or "").strip()}
    _ov, claims = parse_claims(json.dumps({"claims": data.get("claims") or []}, ensure_ascii=False), day=day)
    return overview, state, claims

def merge_claims(claims, now=None):
    """Group by (subject, attr) with per-value confidence.

    A later, different value weakens the earlier one (x0.6); an explicit
    correction from a first-hand statement supersedes it outright. The key's
    confidence is the strongest value it holds, not the weakest.
    """
    table = {}
    # 键归一：同一个属性换个说法（或主体带了个限定词）要落回同一个键，
    # 否则两条关于同一件事的事实永远见不到面，状态也就一直是单值。
    from biocore_memory.event import keynorm as _kn
    known = []
    for item in claims or []:
        try:
            hit = _kn.normalize_key(item.get("subject"), item.get("attr"), known)
            if hit:
                subj, attr = _kn.split_key(hit)
                item = dict(item, subject=subj, attr=attr)
            else:
                made = _kn.key_of(item.get("subject"), item.get("attr"))
                if made:
                    known.append(made)
        except Exception:
            pass
        key = "%s·%s" % (item.get("subject"), item.get("attr"))
        slot = table.setdefault(key, {"values": [], "status": "current"})
        raw = str(item.get("value") or "")
        canon = value_key(raw)
        turn = int(item.get("turn") or 0)
        base = float(item.get("confidence") or 0.55)
        source = item.get("source") or "unknown"
        explicit = str(item.get("status") or "") == "superseded"
        hit = None
        for row in slot["values"]:
            if row["canon"] == canon:
                hit = row
                break
        if hit is None:
            slot["values"].append({"canon": canon, "value": raw, "turn": turn,
                                   "entity": item.get("entity") or "",
                                   "thread": item.get("thread") or "",
                                   "repeats": 1, "source": source,
                                   "confidence": confidence_of(
                                       base, 1,
                                       age_days=(max(0.0, float(now) - float(turn))
                                                 if now is not None and turn else None)),
                                   "status": "current"})
        else:
            hit["repeats"] += 1
            hit["confidence"] = confidence_of(max(base, 0.55), hit["repeats"])
            hit["source"] = source if base >= confidence_of(0.55, 1) else hit["source"]
            if turn and (not hit["turn"] or turn < hit["turn"]):
                hit["turn"] = turn
        if item.get("status") == "private":
            slot["status"] = "private"
    for key, slot in table.items():
        newest = max((v["turn"] for v in slot["values"]), default=0)
        for row in slot["values"]:
            if row["turn"] >= newest or len(slot["values"]) == 1:
                continue
            later_direct = any(o["turn"] > row["turn"] and o["source"] == "direct"
                               for o in slot["values"])
            row["confidence"] = round(max(0.05, row["confidence"] * 0.6), 3)
            if later_direct and row["source"] != "direct":
                row["status"] = "superseded"
                row["confidence"] = min(row["confidence"], 0.2)
        if len(slot["values"]) > 1 and slot["status"] != "private":
            slot["status"] = "coexist"
        slot["confidence"] = round(max(v["confidence"] for v in slot["values"]), 3)
        slot["values"].sort(key=lambda v: v["turn"])
    return table


MAX_VALUES_PER_KEY = 4


def audit_table(table):
    """Mechanical checks: over-merged keys and values that are really attrs.

    No lexicon: a value is "really an attr" when the same string is used as an
    attribute somewhere in the same table, or when it contains no digit/date.
    """
    import re as _re
    attrs = set()
    for key in (table or {}):
        parts = str(key).split("·")
        if len(parts) == 2:
            attrs.add(parts[1])
    over, value_attrs = [], []
    for key, slot in (table or {}).items():
        vals = [v["value"] if isinstance(v, dict) else v
                for v in (slot.get("values") or [])]
        if len(vals) > MAX_VALUES_PER_KEY:
            over.append((key, len(vals)))
        for v in vals:
            if v in attrs:
                value_attrs.append((key, v))
                continue
            if not _re.search(r"\d|[一二三四五六七八九十]|叫|是", str(v)) and len(str(v)) <= 6:
                value_attrs.append((key, v))
    return {"over_merged": over, "value_as_attr": value_attrs}


def trim_values(table, limit=MAX_VALUES_PER_KEY):
    """Keep the newest values per key so a bad key cannot swallow everything."""
    for key, slot in (table or {}).items():
        vals = sorted(slot.get("values") or [], key=lambda v: v["turn"] if isinstance(v, dict) else v[1])
        if len(vals) > limit:
            slot["values"] = vals[-limit:]
            slot["trimmed"] = len(vals) - limit
    return table





def threads_of(table):
    """{thread: [keys]} — the grouping that answering actually needs."""
    out = {}
    for key, slot in (table or {}).items():
        for row in slot.get("values") or []:
            th = row.get("thread") if isinstance(row, dict) else ""
            if th:
                out.setdefault(th, [])
                if key not in out[th]:
                    out[th].append(key)
    return out


def render_threads(table, threads, limit=4, per_thread=6):
    """One block per thread: every claim that belongs to the same matter."""
    lines = []
    for th in list(threads or [])[:limit]:
        keys = (threads or {}).get(th) or []
        if not keys:
            continue
        lines.append("【线索】%s（%d 条）" % (th, len(keys)))
        for line in render_claims({k: table[k] for k in keys if k in table}, limit=per_thread):
            lines.append("  " + line)
    return lines



def consolidate(table, limit_per_thread=6):
    """Fold a thread into a timeline: newest value per key, older ones kept as history."""
    out = {}
    for line in render_threads(table, threads_of(table), limit=99, per_thread=limit_per_thread):
        out.setdefault("lines", []).append(line)
    return out.get("lines", [])


def density(claims, chars):
    """Claims per 100 characters: chit-chat scores low, business talk scores high."""
    try:
        chars = float(chars or 0)
    except Exception:
        return 0.0
    if chars <= 0:
        return 0.0
    return round(len(claims or []) * 100.0 / chars, 2)


def budget_hint(event, low=0.25, high=0.6):
    """How much of an event deserves raw sentences: 0 none, 5 top sentences, 10 all."""
    claims = event.get("claims") or []
    if not claims:
        return 5, 0.0        # unknown density: keep the usual five sentences
    chars = len(str(event.get("text") or ""))
    d = density(claims, chars)
    if d < low:
        return 0, d
    if d < high:
        return 5, d
    return 10, d


def private_lines(table):
    """Claims whose status is private: they must not reach a third party."""
    lines = []
    for key, slot in (table or {}).items():
        if slot.get("status") != "private":
            continue
        vals = [v.get("value") for v in slot.get("values") or [] if isinstance(v, dict)]
        lines.append("【不可外传】%s：%s" % (key, " / ".join(str(v) for v in vals[-2:])))
    return lines

def claim_graph(table, entities=None):
    """Claims sharing a subject, an attribute, or an entity are linked."""
    subjects, attrs = {}, {}
    for key in (table or {}):
        parts = str(key).split("·")
        if len(parts) != 2:
            continue
        subject, attr = parts
        subjects.setdefault(subject, []).append(key)
        attrs.setdefault(attr, []).append(key)
    graph = {}
    groups = list(subjects.values()) + list(attrs.values())
    for entity, keys in (entities or {}).items():
        if len(keys) > 1:
            groups.append(list(keys))
    for group in groups:
        for key in group:
            for other in group:
                if other != key:
                    graph.setdefault(key, set()).add(other)
    return graph


def entities_of(table):
    """{entity: [keys]} collected from the claim rows that still carry it."""
    out = {}
    for key, slot in (table or {}).items():
        for row in slot.get("values") or []:
            ent = row.get("entity") if isinstance(row, dict) else ""
            if ent:
                out.setdefault(ent, [])
                if key not in out[ent]:
                    out[ent].append(key)
    return out


def expand_claims(table, seeds, hops=1, limit=6):
    """One-hop neighbours of the seed keys, most-linked first."""
    graph = claim_graph(table)
    found = []
    for seed in seeds or []:
        if seed not in (table or {}):
            continue
        for other in sorted(graph.get(seed, ())):
            if other not in found and other not in (seeds or []):
                found.append(other)
    return found[:limit]

def _when(turn, turn_dates=None):
    """Rendered time for one claim row: a date, never an internal coordinate.

    The table keeps turn/event ids for indexing; the model only sees when a
    fact was recorded, because "第15轮" means nothing to a reader who never
    saw the turn list.
    """
    if not turn or not turn_dates:
        return ""
    stamp = turn_dates.get(int(turn or 0)) or turn_dates.get(str(int(turn or 0)))
    text = str(stamp or "").strip()
    return ("（%s 记录）" % text) if text else ""


def render_claims(table, limit=8, turn_dates=None):
    lines = []
    for key in sorted(table):
        slot = table[key]
        rows = list(slot.get("values") or [])[-3:]
        dicts = [row for row in rows if isinstance(row, dict)]
        current = [row for row in dicts if row.get("status") != "superseded"]
        retired = [row for row in dicts if row.get("status") == "superseded"]
        parts = []
        # The current value is labelled first: a line that only says
        # "superseded" leaves the reader with two candidates and no way to
        # pick one, which is how "八月十八 -> 八月十六" became "无法确定".
        if current:
            row = current[-1]
            weak = float(row.get("confidence") or 1.0) < 0.5
            parts.append("【当前】%s%s%s"
                         % (row.get("value"),
                            _when(row.get("turn"), turn_dates),
                            "，可信度低" if weak else ""))
        # At most one retired value: the newest one. Two candidates are a
        # question, three are noise.
        for row in retired[-1:]:
            parts.append("【已作废，仅供参考】%s%s"
                         % (row.get("value"),
                            _when(row.get("turn"), turn_dates)))
        for value, turn in [row for row in rows if not isinstance(row, dict)]:
            parts.append("%s%s" % (value, _when(turn, turn_dates)))
        shown = "，".join(parts)
        state = {"coexist": "，两种说法并存，记录不足以确定",
                 "private": "，不能对第三方透露",
                 "current": ""}.get(slot.get("status"), "")
        conf = float(slot.get("confidence") or 0.0)
        if conf and conf < LOW_CONFIDENCE:
            state += "（来源不确定，需向用户确认）"
        lines.append("【状态】%s：%s%s" % (key, shown, state))
    return lines[:limit]