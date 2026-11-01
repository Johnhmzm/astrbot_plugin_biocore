# -*- coding: utf-8 -*-
"""Per-turn "which memories were used" receipt (pure, no IO).

The retrieval trace already records rank/score/source/components; this module
turns it into up to MAX_ROWS readable rows (entry text + short selection
reason) and keeps a bounded per-user history. Consumers: the /biocore memory
command (chat text) and the dashboard state payload (panel data).
"""
from __future__ import annotations

MAX_ROWS = 4
HARD_ROWS = 8
MAX_TEXT = 80
RECEIPT_TEXT = 48
RECEIPT_MAX_CHARS = 600
HISTORY_LIMIT = 5

REASON_LABELS = (
    ("lexical", "关键词"),
    ("recency", "近期"),
    ("retention", "留存"),
    ("schema", "结构契合"),
    ("inhibition", "抑制"),
    ("regulation", "调节"),
    ("source_weight", "来源权重"),
    ("sensitive", "敏感"),
    ("salience", "显著"),
)


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _trim(text, limit=MAX_TEXT):
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[:limit].rstrip() + "…"


def _clamp_limit(value, default, hard):
    try:
        number = int(value)
    except Exception:
        number = int(default)
    if number < 0:
        return 0
    return min(number, int(hard))


def reason_text(components=None, cosine=0.0, importance=0.0) -> str:
    """Short "why this entry was picked" string: top two ranking factors."""
    factors = []
    if isinstance(components, dict):
        for key, label in REASON_LABELS:
            if key not in components:
                continue
            value = _num(components.get(key))
            if value > 0.0001:
                factors.append((value, label))
    factors.sort(key=lambda item: item[0], reverse=True)
    if factors:
        return " / ".join("%s %.2f" % (label, value)
                          for value, label in factors[:2])
    fallback = []
    cosine = max(0.0, _num(cosine))
    importance = max(0.0, _num(importance))
    if cosine > 0.0001:
        fallback.append("相似度 %.2f" % cosine)
    if importance > 0.0001:
        fallback.append("重要度 %.2f" % importance)
    return " / ".join(fallback) if fallback else "规则打分"


def build(trace, limit=MAX_ROWS):
    """Turn the retrieval trace into at most ``limit`` receipt rows."""
    cap = _clamp_limit(limit, MAX_ROWS, HARD_ROWS)
    rows = []
    if cap <= 0 or not isinstance(trace, (list, tuple)):
        return rows
    for index, item in enumerate(list(trace)):
        if not isinstance(item, dict):
            continue
        entry_id = str(item.get("entry_id") or item.get("id") or "").strip()
        text = str(item.get("text") or "").strip()
        if not entry_id and not text:
            continue
        rows.append({
            "rank": len(rows) + 1,
            "id": entry_id[:24],
            "text": _trim(text, MAX_TEXT),
            "source": str(item.get("source") or "unknown")[:16],
            "tier": str(item.get("tier") or "")[:8],
            "score": round(_num(item.get("score")), 4),
            "reason": reason_text(item.get("components"),
                                  item.get("cosine"),
                                  item.get("importance")),
        })
        if len(rows) >= cap:
            break
    return rows


def build_record(rows, reply="", ts=0.0, limit=MAX_ROWS):
    """Bundle one turn's receipt rows with the reply text and timestamp."""
    picked = list(rows)[: _clamp_limit(limit, MAX_ROWS, HARD_ROWS)] if isinstance(
        rows, (list, tuple)) else []
    return {
        "ts": round(_num(ts), 3),
        "reply": _trim(reply, 120),
        "count": len(picked),
        "rows": picked,
    }


def render_receipt(record) -> str:
    """Render the receipt as chat text; empty/invalid records are explained."""
    rows = record.get("rows") if isinstance(record, dict) else None
    if not isinstance(rows, (list, tuple)) or not rows:
        return "本轮记忆：暂无（本轮没有召回到记忆）"
    lines = ["本轮记忆：用了 %d 条" % len(rows)]
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        lines.append("%d. [%s] %s（score %.3f；原因：%s）" % (
            index + 1,
            str(row.get("source") or "unknown"),
            _trim(row.get("text") or row.get("id") or "—", RECEIPT_TEXT),
            _num(row.get("score")),
            str(row.get("reason") or "规则打分"),
        ))
    text = "\n".join(lines).strip()
    if len(text) > RECEIPT_MAX_CHARS:
        text = text[:RECEIPT_MAX_CHARS].rstrip()
    return text


def merge_history(history, record, limit=HISTORY_LIMIT):
    """Prepend *record* to a bounded newest-first history (never mutates)."""
    cap = _clamp_limit(limit, HISTORY_LIMIT, 50)
    if cap <= 0:
        return []
    kept = []
    if isinstance(history, (list, tuple)):
        kept = [item for item in history if isinstance(item, dict)]
    if not isinstance(record, dict):
        return kept[:cap]
    return ([record] + kept)[:cap]
