# -*- coding: utf-8 -*-
"""EXP-2: tone instructions derived from action tendency (expression layer)."""
from __future__ import annotations

BASE = {
    "anxiety": (0.8, "想问清楚一点；句子短一点，可以连着问，少点修饰。"),
    "sadness": (0.7, "少说两句，留点空白；不用感叹号。"),
    "anger": (0.9, "直接说，不绕弯；句子硬一点。"),
    "joy": (1.2, "可以分享，稍微多说一点也不怕，带点语气词。"),
    "guilt": (0.75, "语气软一点，像在试探。"),
    "calm": (1.0, "语气自然。"),
}
UNCERTAIN = ("也许", "可能", "大概")


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


_PROB_LABELS = {"sadness": "sadness", "anger": "anger", "fear": "anxiety",
                "joy": "joy", "trust": "calm", "loneliness": "sadness"}


def _ranked_probs(probs):
    rows = []
    for label, value in (probs or {}).items():
        number = _num(value, -1.0)
        if number is not None and number >= 0:
            rows.append((label, float(number)))
    rows.sort(key=lambda item: item[1], reverse=True)
    return rows


def tone_block(action_tendency, emotion=None, intensity=0.5, self_esteem=0.6,
               regulation=None, probs=None):
    """Tone instructions; probs (optional) enables a mixed-emotion branch.

    Backward compatible: without probs the original single-tendency behaviour
    is unchanged. With probs, top1 < 0.45 and a close top2 produce a gentle
    mixed instruction instead of forcing one label.
    """
    mixed = False
    top1 = top2 = 0.0
    rows = _ranked_probs(probs)
    explicit = str(action_tendency or emotion or "").strip()
    if rows and explicit in ("", "neutral"):
        top1 = rows[0][1]
        top2 = rows[1][1] if len(rows) > 1 else 0.0
        if 0.20 <= top1 < 0.45 and (top1 - top2) < 0.15:
            mixed = True
    tendency = str(action_tendency or emotion or "calm")
    if mixed:
        tendency = "mixed"
    elif (rows and str(action_tendency or "") in ("", "calm", "neutral")
          and str(emotion or "") in ("", "calm", "neutral")):
        tendency = _PROB_LABELS.get(rows[0][0], "calm")
    if tendency not in BASE and tendency != "mixed":
        tendency = "calm"
    if mixed:
        text = "混合情绪：语气轻一点、慢一点，留点空白；不用感叹号。"
        return {"text": text, "chars_mult": 0.85, "tendency": "mixed",
                "suppressed": False,
                "uncertain_allowed": _num(self_esteem, 0.6) < 0.45,
                "mixed": True, "top1": round(top1, 4), "top2": round(top2, 4)}
    chars_mult, text = BASE[tendency]
    lines = [text]
    suppressed = str(regulation or "").lower() == "suppress"
    if suppressed:
        chars_mult *= 0.9
        lines.append("把情绪收一点：不加感叹号，少用强调词。")
    elif str(regulation or "").lower() == "reappraise":
        lines.append("语气平稳，可以讲道理，但别像说教。")
    if _num(self_esteem, 0.6) < 0.45:
        lines.append("允许一个不确定词（也许/可能），只用一次。")
    return {"text": "\n".join(lines), "chars_mult": round(chars_mult, 3),
            "tendency": tendency, "suppressed": suppressed,
            "uncertain_allowed": _num(self_esteem, 0.6) < 0.45,
            "mixed": False, "top1": round(top1, 4), "top2": round(top2, 4)}
