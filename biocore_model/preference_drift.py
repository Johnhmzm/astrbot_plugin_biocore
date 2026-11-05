# -*- coding: utf-8 -*-
"""task-219: repeated topics slowly drift the value_order weights.

Memory already knows what keeps coming back. This module counts those topics
with the tokenizer that already ships in biocore_model (memory_store.bigrams
for CJK, a latin-word regex), maps the ones with a known dimension onto
value_order, and -- only once a topic has appeared in more than
TOPIC_THRESHOLD memory entries -- nudges that dimension by a small amount per
new occurrence.

Guards, all here so a theme can never rewrite her in one night:

  THRESHOLD  cumulative occurrences must pass TOPIC_THRESHOLD (5)
  PER CALL   one step moves a dimension by at most DAILY_CAP (0.01), which is
             also the per-day allowance; callers run one step per day
  BOUNDS     every weight stays inside value_order.WEIGHT_FLOOR..CEIL
  WATERMARK  only occurrences since the previous call drift the table
             (last_counts), so replaying the same batch is idempotent
  DECAY      a dimension whose topic stopped being active relaxes toward
             value_order.DEFAULTS by DECAY_PER_DAY per elapsed day
  LAYERS     biocore_model only; never writes a memory entry, never touches
             the persona file, never renders prompt text

Pure functions only: no IO, no clock, no host imports, no LLM calls. The
caller passes weights, counts and the last watermark, so a drift step can be
replayed exactly in a test. Default OFF: flags {"preference_drift": True} or
env BIOCORE_PREFERENCE_DRIFT=1.
"""
from __future__ import annotations

import re

try:
    from . import value_order as _vo
except Exception:  # pragma: no cover - degraded checkout
    _vo = None

TOPIC_THRESHOLD = 5
PER_REPEAT = 0.002
DAILY_CAP = 0.01
DECAY_PER_DAY = 0.0005
MAX_TOPICS = 24

_WS = re.compile(r"\s+")
_LATIN = re.compile(r"[a-z][a-z0-9_']*")
_CJK = re.compile(r"[\u4e00-\u9fff]+")

# topic keyword -> value_order dimension; the longest matching keyword wins.
TOPIC_DIMENSIONS = (
    ("self_direction", ("自由", "自己做主", "自己决定", "独立", "选择", "决定")),
    ("stimulation", ("新鲜", "刺激", "旅行", "冒险", "出去玩", "尝试")),
    ("hedonism", ("开心", "好吃", "吃", "玩", "舒服", "放松")),
    ("achievement", ("认可", "夸", "厉害", "成功", "进步", "成绩")),
    ("power", ("掌控", "主导", "说话算数", "权力", "命令")),
    ("security", ("安全", "害怕", "担心", "不安", "稳定")),
    ("conformity", ("规矩", "礼貌", "应该", "不能", "越界")),
    ("tradition", ("传统", "习惯", "以前", "老规矩")),
    ("benevolence", ("陪", "需要我", "帮你", "关心", "照顾", "倾听")),
    ("universalism", ("公平", "诚实", "尊重", "正义", "原则")),
)

STOPWORDS = frozenset((
    "我们", "你们", "他们", "她们", "这个", "那个", "就是", "不是", "一个",
    "什么", "怎么", "可以", "没有", "因为", "所以", "然后", "还是", "现在",
    "今天", "明天", "知道", "觉得", "自己", "已经", "这样", "那样", "东西",
))
FALLBACK_DEFAULTS = {
    "self_direction": 0.62, "stimulation": 0.45, "hedonism": 0.40,
    "achievement": 0.55, "power": 0.38, "security": 0.70,
    "conformity": 0.35, "tradition": 0.30, "benevolence": 0.75,
    "universalism": 0.60,
}


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return default
    return number if number == number else default


def _clamp(value, low, high):
    return max(low, min(high, _num(value, low)))


def _dimensions():
    return tuple(_vo.DIMENSIONS) if _vo is not None else tuple(FALLBACK_DEFAULTS)


def _defaults():
    return dict(_vo.DEFAULTS) if _vo is not None else dict(FALLBACK_DEFAULTS)


def enabled(flags=None, env=None):
    """Flag or env switch; both default OFF (old behaviour)."""
    flags = flags if isinstance(flags, dict) else {}
    if flags.get("preference_drift") is True:
        return True
    raw = env.get("BIOCORE_PREFERENCE_DRIFT") if hasattr(env, "get") else None
    return str(raw or "").strip().lower() in ("1", "true", "on", "yes")


def topics(text, limit=MAX_TOPICS):
    """Topic tokens for one memory text (CJK bigrams + latin words)."""
    lowered = _WS.sub(" ", str(text or "").lower())
    out = []
    seen = set()
    for run in _CJK.findall(lowered):
        if len(run) < 2:
            continue
        for index in range(len(run) - 1):
            cand = run[index:index + 2]
            if cand in seen or cand in STOPWORDS:
                continue
            seen.add(cand)
            out.append(cand)
            if len(out) >= limit:
                return out
    for word in _LATIN.findall(lowered):
        if len(word) < 3 or word in seen or word in STOPWORDS:
            continue
        seen.add(word)
        out.append(word)
        if len(out) >= limit:
            break
    return out


def dimension_of(topic):
    """value_order dimension for a topic, or None (longest keyword wins)."""
    key = str(topic or "").lower()
    if not key:
        return None
    best = None
    best_len = 0
    for dim, keywords in TOPIC_DIMENSIONS:
        for word in keywords:
            if word in key and len(word) > best_len:
                best, best_len = dim, len(word)
    return best


def accumulate(counts=None, entries=None):
    """Add one count per entry per topic; returns a new dict (never mutates)."""
    table = {}
    if isinstance(counts, dict):
        for key, value in counts.items():
            table[str(key)] = int(_num(value, 0))
    for entry in entries or []:
        text = entry.get("text") if isinstance(entry, dict) else str(entry or "")
        if not text:
            continue
        for topic in set(topics(text)):
            table[topic] = table.get(topic, 0) + 1
    return table


def count_topics(entries):
    """Cumulative topic counts for a whole memory list."""
    return accumulate({}, entries)


def decay_counts(counts=None, days=0.0, half_life_days=60.0):
    """Halve the counts once per half-life; keeps a fading theme fading."""
    days = max(0.0, _num(days, 0.0))
    half_life = max(1e-6, _num(half_life_days, 60.0))
    factor = 0.5 ** (days / half_life)
    table = {}
    if isinstance(counts, dict):
        for key, value in counts.items():
            table[str(key)] = round(max(0.0, _num(value, 0.0)) * factor, 4)
    return table


def step(weights=None, counts=None, last_counts=None, days=1.0,
         enabled=True, threshold=TOPIC_THRESHOLD, per_repeat=PER_REPEAT,
         daily_cap=DAILY_CAP, decay_per_day=DECAY_PER_DAY):
    """One drift step. Call once per day with the counts seen so far.

    weights      the current value table (normalized copy is returned)
    counts       cumulative topic occurrences in memory
    last_counts  the counts watermark from the previous step
    days         elapsed days since the previous step (decay only)
    """
    if _vo is None:
        return {"enabled": bool(enabled), "weights": dict(weights or {}),
                "drifted": {}, "decayed": [], "active": {}, "counts": {},
                "reason": "value_order_unavailable"}
    base = _vo.normalize(weights)
    result = {"enabled": bool(enabled), "weights": base, "drifted": {},
              "decayed": [], "active": {}, "counts": {}, "reason": "ok"}
    if not enabled:
        result["reason"] = "disabled"
        return result

    counts = counts if isinstance(counts, dict) else {}
    last = last_counts if isinstance(last_counts, dict) else {}
    days = max(0.0, _num(days, 1.0))
    threshold = max(1, int(_num(threshold, TOPIC_THRESHOLD)))
    per_repeat = _clamp(per_repeat, 0.0, DAILY_CAP)
    cap = _clamp(daily_cap, 0.0, 0.05)
    decay = _clamp(decay_per_day, 0.0, DAILY_CAP)
    dimensions = _dimensions()
    defaults = _defaults()

    fresh = {}
    active = {}
    for topic, total in counts.items():
        total = _num(total, 0.0)
        if total <= threshold:
            continue
        active[str(topic)] = total
        new = max(0.0, total - _num(last.get(topic), 0.0))
        if new:
            fresh[str(topic)] = new
    result["active"] = active

    by_dim = {}
    for topic, new in fresh.items():
        dim = dimension_of(topic)
        if dim is None:
            continue
        by_dim[dim] = by_dim.get(dim, 0.0) + per_repeat * new
    active_dims = {dimension_of(topic) for topic in active}
    for dim, raw in by_dim.items():
        delta = min(cap, raw)
        if delta <= 0:
            continue
        before = base[dim]
        base[dim] = round(_clamp(before + delta, _vo.WEIGHT_FLOOR,
                                 _vo.WEIGHT_CEIL), 4)
        moved = round(base[dim] - before, 4)
        if moved:
            result["drifted"][dim] = moved

    if decay > 0 and days > 0:
        relax = min(cap * days, decay * days)
        for dim in dimensions:
            if dim in active_dims or dim in result["drifted"]:
                continue
            before = base[dim]
            default = _num(defaults.get(dim), before)
            if abs(before - default) <= 1e-9:
                continue
            toward = 1.0 if default > before else -1.0
            base[dim] = round(_clamp(before + toward * min(relax, abs(default - before)),
                                     _vo.WEIGHT_FLOOR, _vo.WEIGHT_CEIL), 4)
            if abs(base[dim] - before) > 1e-9:
                result["decayed"].append(dim)

    result["weights"] = base
    result["counts"] = {str(key): _num(value, 0.0)
                        for key, value in counts.items()}
    return result
