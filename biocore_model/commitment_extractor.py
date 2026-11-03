# -*- coding: utf-8 -*-
"""P1 commitment extractor: turn one sentence into a prospective-memory row.

prospective.py only knows how to store and fire commitments; somebody has to
register them first.  This module is that writer, and it is deliberately
rule-based: no LLM call, no IO, no clock (the caller passes now), no main.py.

Two commitment kinds map onto prospective.py:

  * her_promise - the user asks her to do something ('你明天记得问我结果');
  * his_event   - the user mentions his own dated thing ('我周五体检').

Time table (the only accepted surface forms):

  relative   今天 / 明天 / 后天 / 大后天
  weekday    周一..周日, 本周X / 这周X / 下周X / 下下周X
  absolute   N月N日 (with optional N年)
  clock      N点 / N点N分, 上午 / 中午 / 下午 / 晚上 / 傍晚 / 凌晨
  vague      改天 / 找时间 / 有空 / 回头 / 晚点 -> recognized, but no due_ts

Output::

    {'enabled': True, 'has_commitment': True, 'who': 'her', 'what': '问我结果',
     'due_ts': 1790000000.0, 'confidence': 0.9, 'surface_phrase': '明天',
     'kind': 'her_promise', 'reason': 'ok', 'entities': []}

The module can be switched off with config=False / {'enabled': False}.
"""
from __future__ import annotations

import datetime
import re

try:
    from . import prospective
except Exception:  # pragma: no cover - direct script import
    import prospective

DEFAULT_HOUR = 9
DEFAULT_MINUTE = 0
MAX_WHAT = 60
DATE_WINDOW = 12
WEEKDAY_CHARS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5,
                 "日": 6, "天": 6, "1": 0, "2": 1, "3": 2, "4": 3,
                 "5": 4, "6": 5, "7": 6}
CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
          "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}
CONFIDENCE = {
    "tag": 0.99,
    "absolute_time": 0.95,
    "relative_time": 0.90,
    "weekday_time": 0.85,
    "absolute": 0.82,
    "relative": 0.80,
    "weekday": 0.68,
    "bare_time": 0.60,
    "vague": 0.35,
}
INTENT_MARKERS = (
    "提醒", "记得", "别忘", "答应", "约", "见", "去", "来", "回", "交",
    "发", "问", "查", "拿", "送", "开始", "截止", "考试", "体检", "开会",
    "生日", "聚会", "吃饭", "看", "学", "写", "买", "还", "改", "到",
    "完成", "安排", "定", "请假", "加班", "上班", "下班", "医院", "报告",
    "面试", "旅行", "出门", "参加", "做", "办", "有事", "有课", "有会",
    "聊", "谈", "商量", "讨论",
)
PAST_WORDS = ("昨天", "昨日", "前天", "去年", "刚才", "刚刚",
              "上个星期", "上礼拜")
HER_MARKERS = ("提醒我", "叫我", "帮我记", "你记得", "你别忘", "你答应",
               "你问", "你查", "你告诉我", "你跟我说")
ACTION_PREFIXES = ("提醒我", "别忘了", "别忘", "记得", "帮我", "到时候",
                   "到时", "我们", "请你", "请", "你", "我")
_ABS_RE = re.compile(
    r"(?:(?P<year>\d{4})年)?\s*(?P<month>\d{1,2})月\s*(?P<day>\d{1,2})[日号]")
_REL_RE = re.compile(r"大后天|后天|明天|明日|今天|今日")
_WEEKDAY_RE = re.compile(
    r"(?P<prefix>下下周|下周|下星期|下礼拜|本周|这周|这个星期|这星期|周|星期|礼拜)"
    r"(?P<day>[一二三四五六日天1-7])")
_VAGUE_RE = re.compile(r"改天|找时间|有空|回头|晚点|过几天|以后|哪天|抽时间")
_TIME_RE = re.compile(
    r"(?:(?P<period>上午|早上|清晨|中午|下午|傍晚|晚上|夜里|凌晨))?\s*"
    r"(?:(?P<hour>\d{1,2})|(?P<hour_cn>[一二两三四五六七八九十]{1,2}))\s*"
    r"(?:点|时)(?:(?P<minute>\d{1,2})\s*分?)?")
_PUNCT_RE = re.compile(r"[，。！？、,.!?;；:：\s]+")
_CLAUSE_PUNCT = set("，。！？、,.!?;；\n")


def _num(value, default=0.0):
    try:
        num = float(value)
    except Exception:
        return float(default)
    if num != num or num in (float("inf"), float("-inf")):
        return float(default)
    return num


def _clamp01(value, default=0.0):
    return max(0.0, min(1.0, _num(value, default)))


def _config(config):
    if isinstance(config, bool):
        return {"enabled": config}
    if isinstance(config, dict):
        return {"enabled": bool(config.get("enabled", True))}
    return {"enabled": True}


def _now_dt(now):
    stamp = _num(now, 0.0)
    if stamp <= 0.0:
        return None
    try:
        return datetime.datetime.fromtimestamp(stamp)
    except Exception:
        return None


def _cn_number(text):
    return CN_NUM.get(str(text or "").strip(), 0)


def _hour_minute(match):
    hour_text = match.group("hour")
    minute_text = match.group("minute")
    if hour_text is not None:
        try:
            hour = int(hour_text)
        except Exception:
            return None
    else:
        hour = _cn_number(match.group("hour_cn"))
    try:
        minute = int(minute_text) if minute_text is not None else 0
    except Exception:
        minute = 0
    period = str(match.group("period") or "")
    if period in ("下午", "傍晚", "晚上", "夜里") and hour < 12:
        hour += 12
    elif period == "中午" and hour < 11:
        hour += 12
    elif period == "凌晨" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def _find_time_after(text, position):
    """Nearest clock token after a date token, not across punctuation."""
    start = max(0, int(position))
    end = min(len(text), start + DATE_WINDOW)
    segment = text[start:end]
    punct = _PUNCT_RE.search(segment)
    if punct:
        end = start + punct.start()
    match = _TIME_RE.search(text, start, end)
    if not match:
        return None
    parsed = _hour_minute(match)
    if not parsed:
        return None
    return {"hour": parsed[0], "minute": parsed[1],
            "start": match.start(), "end": match.end()}


def _absolute_date(now_dt, year, month, day):
    try:
        base = datetime.date(int(year) if year else now_dt.year,
                             int(month), int(day))
    except Exception:
        return None
    if not year and base < now_dt.date() - datetime.timedelta(days=1):
        try:
            base = base.replace(year=base.year + 1)
        except Exception:
            return None
    return base


def _weekday_date(now_dt, prefix, day_char):
    index = WEEKDAY_CHARS.get(str(day_char))
    if index is None:
        return None
    monday = now_dt.date() - datetime.timedelta(days=now_dt.weekday())
    weeks = 0
    kind = "weekday_bare"
    prefix = str(prefix or "")
    if prefix in ("下下周",):
        weeks = 2
        kind = "weekday"
    elif prefix in ("下周", "下星期", "下礼拜"):
        weeks = 1
        kind = "weekday"
    elif prefix in ("本周", "这周", "这个星期", "这星期"):
        weeks = 0
        kind = "weekday"
    else:
        delta = (index - now_dt.weekday()) % 7
        return {"date": now_dt.date() + datetime.timedelta(days=delta),
                "kind": kind}
    return {"date": monday + datetime.timedelta(days=7 * weeks + index),
            "kind": kind}


def _due_from(now_dt, base_date, kind, hour, minute, explicit):
    dt = datetime.datetime.combine(base_date, datetime.time(hour, minute))
    due = dt.timestamp()
    now_ts = now_dt.timestamp()
    if kind == "weekday_bare" and due <= now_ts + 1.0:
        due = (dt + datetime.timedelta(days=7)).timestamp()
        explicit = True
    if due > now_ts + 1.0:
        return due, False
    if not explicit and base_date == now_dt.date():
        return now_ts + 1800.0, False
    return due, True


def _date_tokens(text, now_dt):
    """All date-like tokens with their base date and specificity."""
    tokens = []
    taken = []

    def free(start, end):
        for left, right in taken:
            if not (end <= left or start >= right):
                return False
        return True

    for match in _ABS_RE.finditer(text):
        base = _absolute_date(now_dt, match.group("year"),
                              match.group("month"), match.group("day"))
        if base is None:
            continue
        tokens.append({"start": match.start(), "end": match.end(),
                       "phrase": match.group(0).strip(),
                       "date": base, "kind": "absolute",
                       "specificity": 78})
        taken.append((match.start(), match.end()))
    for match in _REL_RE.finditer(text):
        if not free(match.start(), match.end()):
            continue
        offset = {"大后天": 3, "后天": 2, "明天": 1, "明日": 1,
                  "今天": 0, "今日": 0}.get(match.group(0), 0)
        tokens.append({"start": match.start(), "end": match.end(),
                       "phrase": match.group(0),
                       "date": now_dt.date() + datetime.timedelta(days=offset),
                       "kind": "relative", "specificity": 74})
        taken.append((match.start(), match.end()))
    for match in _WEEKDAY_RE.finditer(text):
        if not free(match.start(), match.end()):
            continue
        resolved = _weekday_date(now_dt, match.group("prefix"),
                                 match.group("day"))
        if not resolved:
            continue
        previous = text[match.start() - 1:match.start()]
        tokens.append({"start": match.start(), "end": match.end(),
                       "phrase": match.group(0),
                       "date": resolved["date"], "kind": resolved["kind"],
                       "specificity": 62 if resolved["kind"] == "weekday" else 58,
                       "past_hint": previous == "上"})
        taken.append((match.start(), match.end()))
    return tokens, taken


def _tag_candidate(tags, now_dt):
    if not isinstance(tags, dict):
        return None
    now_ts = now_dt.timestamp()
    raw_due = tags.get("due_ts")
    if raw_due is not None:
        due = _num(raw_due, 0.0)
        if due > now_ts + 1.0:
            phrase = str(tags.get("time") or "")
            return {"start": 0, "end": 0, "phrase": phrase, "due_ts": due,
                    "past": False, "vague": False, "kind": "tag",
                    "specificity": 100, "explicit_time": True}
        return None
    raw_time = tags.get("time")
    if isinstance(raw_time, str) and raw_time.strip():
        candidates, _ = _parse_candidates(raw_time, now_dt, allow_bare=True)
        concrete = [row for row in candidates
                    if row["due_ts"] is not None and not row["past"]]
        if concrete:
            concrete.sort(key=lambda row: (-row["specificity"], row["due_ts"]))
            best = dict(concrete[0])
            best["kind"] = "tag"
            best["specificity"] = 100
            best["phrase"] = raw_time.strip()
            best["start"] = 0
            best["end"] = 0
            return best
    return None


def _parse_candidates(text, now_dt, allow_bare=True):
    """Build concrete and vague candidates for one piece of text."""
    tokens, taken = _date_tokens(text, now_dt)
    candidates = []
    for token in tokens:
        clock = _find_time_after(text, token["end"])
        explicit = clock is not None
        hour = clock["hour"] if clock else DEFAULT_HOUR
        minute = clock["minute"] if clock else DEFAULT_MINUTE
        due, past = _due_from(now_dt, token["date"], token["kind"],
                              hour, minute, explicit)
        phrase = token["phrase"]
        end = token["end"]
        if clock:
            phrase = text[token["start"]:clock["end"]].strip()
            end = clock["end"]
        specificity = token["specificity"]
        if explicit:
            specificity += 20
        if token.get("past_hint"):
            past = True
        label = ("absolute" if token["kind"] == "absolute" else
                 "relative" if token["kind"] == "relative" else "weekday")
        if explicit:
            label += "_time"
        candidates.append({"start": token["start"], "end": end,
                           "phrase": phrase, "due_ts": due, "past": past,
                           "vague": False, "kind": label,
                           "specificity": specificity,
                           "explicit_time": explicit})
    if not candidates and allow_bare:
        for match in _TIME_RE.finditer(text):
            parsed = _hour_minute(match)
            if not parsed:
                continue
            base = now_dt.date()
            due, past = _due_from(now_dt, base, "bare_time",
                                  parsed[0], parsed[1], True)
            if past:
                due = (datetime.datetime.combine(
                    base + datetime.timedelta(days=1),
                    datetime.time(parsed[0], parsed[1]))).timestamp()
                past = due <= now_dt.timestamp()
            candidates.append({"start": match.start(), "end": match.end(),
                               "phrase": match.group(0), "due_ts": due,
                               "past": past, "vague": False,
                               "kind": "bare_time", "specificity": 50,
                               "explicit_time": True})
    if not candidates:
        for match in _VAGUE_RE.finditer(text):
            candidates.append({"start": match.start(), "end": match.end(),
                               "phrase": match.group(0), "due_ts": None,
                               "past": False, "vague": True,
                               "kind": "vague", "specificity": 10,
                               "explicit_time": False})
    return candidates, taken


def _has_intent(text):
    return any(marker in text for marker in INTENT_MARKERS)


def _who(text):
    if any(marker in text for marker in HER_MARKERS):
        return "her"
    if "你" in text and any(verb in text for verb in
                            ("问", "查", "提醒", "记得", "告诉我", "跟我说",
                             "答应")):
        return "her"
    return "him"


def _clause_bounds(text, start, end):
    """Sentence clause around the matched time phrase (for a clean what)."""
    left = 0
    for index in range(int(start) - 1, -1, -1):
        if text[index] in _CLAUSE_PUNCT:
            left = index + 1
            break
    right = len(text)
    for index in range(int(end), len(text)):
        if text[index] in _CLAUSE_PUNCT:
            right = index
            break
    return left, right


def _clean_what(text, start, end):
    rest = text[:start] + " " + text[end:]
    rest = _PUNCT_RE.sub(" ", rest).strip()
    changed = True
    while changed and rest:
        changed = False
        for prefix in ACTION_PREFIXES:
            if rest.startswith(prefix) and len(rest) > len(prefix):
                rest = rest[len(prefix):].lstrip(" ，,")
                changed = True
                break
    rest = rest.strip()
    if not rest:
        rest = _PUNCT_RE.sub(" ", text).strip()
    return rest[:MAX_WHAT]


def _entities(tags):
    if not isinstance(tags, dict):
        return []
    raw = tags.get("entities")
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text[:20])
    return out[:5]


def extract(text, tags=None, now=None, config=None):
    """Extract at most one commitment (the most specific one) from a sentence."""
    cfg = _config(config)
    raw = str(text or "").strip()
    result = {
        "enabled": bool(cfg["enabled"]),
        "has_commitment": False,
        "who": "",
        "what": "",
        "due_ts": None,
        "confidence": 0.0,
        "surface_phrase": "",
        "kind": "",
        "reason": "",
        "entities": _entities(tags),
    }
    if not result["enabled"]:
        result["reason"] = "disabled"
        return result
    now_dt = _now_dt(now)
    tag_candidate = _tag_candidate(tags, now_dt) if now_dt else None
    if not raw and not tag_candidate:
        result["reason"] = "no_text"
        return result
    if now_dt is None:
        result["reason"] = "no_now"
        return result
    candidates, _ = _parse_candidates(raw, now_dt) if raw else ([], [])
    concrete = [row for row in candidates
                if row["due_ts"] is not None and not row["past"]]
    vague = [row for row in candidates if row["vague"]]
    past = [row for row in candidates if row["past"]]
    past_text = any(word in raw for word in PAST_WORDS)
    chosen = None
    if tag_candidate:
        chosen = tag_candidate
    elif concrete:
        concrete.sort(key=lambda row: (-row["specificity"], row["due_ts"]))
        chosen = concrete[0]
    elif vague and _has_intent(raw):
        chosen = vague[0]
    elif past or past_text:
        result["reason"] = "past"
        return result
    elif candidates:
        result["reason"] = "no_intent"
        return result
    else:
        result["reason"] = "no_time"
        return result
    if not tag_candidate and not chosen["vague"] and not _has_intent(raw):
        result["reason"] = "no_intent"
        return result
    who = _who(raw)
    kind = "her_promise" if who == "her" else "his_event"
    fact = ""
    if isinstance(tags, dict):
        fact = str(tags.get("fact") or "").strip()
    what = ""
    if raw and chosen["kind"] != "tag":
        left, right = _clause_bounds(raw, chosen["start"], chosen["end"])
        what = _clean_what(raw[left:right], chosen["start"] - left,
                           chosen["end"] - left)
    if not what and fact:
        what = fact[:MAX_WHAT]
    if not what and raw:
        what = _clean_what(raw, chosen["start"], chosen["end"])
    confidence = CONFIDENCE.get(chosen["kind"], 0.6)
    if not what:
        confidence *= 0.6
    result.update({
        "has_commitment": True,
        "who": who,
        "what": what,
        "due_ts": (round(float(chosen["due_ts"]), 3)
                   if chosen["due_ts"] is not None else None),
        "confidence": round(_clamp01(confidence), 3),
        "surface_phrase": str(chosen["phrase"] or ""),
        "kind": kind,
        "reason": "vague" if chosen["vague"] else "ok",
    })
    return result


def to_prospective(result, now=None, source="chat"):
    """Convert one extract() result into a prospective.entry() record, or None."""
    if not isinstance(result, dict) or not result.get("has_commitment"):
        return None
    due = result.get("due_ts")
    if due is None:
        return None
    kind = str(result.get("kind") or "")
    if kind not in prospective.KINDS:
        kind = "his_event"
    meta = {
        "confidence": _clamp01(result.get("confidence", 0.0)),
        "surface_phrase": str(result.get("surface_phrase") or ""),
        "who": str(result.get("who") or ""),
    }
    return prospective.entry(kind, str(result.get("what") or ""), due,
                             now=now, source=source, meta=meta)
