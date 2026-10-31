# -*- coding: utf-8 -*-
"""Why she wants to reach out: reason extraction + prompt/fallback text."""
from __future__ import annotations

TEXTS = {
    "social_gap": "很久没联系了",
    "lonely": "有点闷，想找人说说话",
    "anxiety": "心里有点不安",
    "sadness": "情绪有点低落",
    "joy": "心情不错，想分享",
    "anger": "有点憋着火",
    "boredom": "有点无聊",
    "open_loop": "上次的话题还没说完",
    "memory_due": "记得一件和你有关的事",
    "repair": "想缓和一下气氛",
}
WEIGHTS = {"social_gap": "social_gap", "lonely": "lonely", "anxiety": "anxiety_fear",
           "sadness": "sadness", "joy": "joy", "anger": "anger_conflict",
           "boredom": "boredom", "open_loop": "open_loops", "repair": "repair_urge",
           "memory_due": "memory_due"}
ORDER = ("social_gap", "memory_due", "open_loop", "repair", "lonely", "anxiety",
         "sadness", "anger", "joy", "boredom")


def extract(parts, memory_title="", memory_due=0.0):
    """Pick the strongest 1-2 reasons from v3 drift parts."""
    parts = parts if isinstance(parts, dict) else {}
    best_code, best_weight = "", 0.0
    for code in ORDER:
        key = WEIGHTS[code]
        try:
            weight = float(parts.get(key, 0.0) or 0.0)
        except Exception:
            weight = 0.0
        if code == "memory_due" and memory_due:
            weight = max(weight, float(memory_due))
        if weight > best_weight:
            best_code, best_weight = code, weight
    if not best_code:
        return {"code": "lonely", "text": TEXTS["lonely"], "weight": 0.0,
                "detail": {"top_parts": {}, "memory_title": ""}}
    top = {code: round(best_weight, 4)}
    text = TEXTS.get(best_code, "")
    if best_code == "memory_due" and memory_title:
        text = "记得你" + str(memory_title)[:20]
    return {"code": best_code, "text": text, "weight": round(best_weight, 4),
            "detail": {"top_parts": top, "memory_title": str(memory_title or "")}}


def build_prompt(reason):
    reason = reason if isinstance(reason, dict) else {}
    return ("你现在想主动找对方说话。\n"
            "动机：%s（%s，强度 %.2f）\n"
            "要求：按当前行为规则说话（短句、约 10 字、最多 30 字、可用换行）；"
            "不要解释动机、不要提“触发”；严格按【输出格式】输出 <bc> 情绪标签。"
            % (reason.get("text") or "想说话了", reason.get("code") or "lonely",
               float(reason.get("weight", 0.0) or 0.0)))


def fallback_text(reason, template=""):
    reason = reason if isinstance(reason, dict) else {}
    prefix = "（%s）" % (reason.get("text") or "想说话了")
    return (prefix + str(template or "在。"))[:120]
