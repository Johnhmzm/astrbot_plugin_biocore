# -*- coding: utf-8 -*-
"""表达层安全闸（boundary gate）—— 默认关闭，用户可自行开启。

这里定义**硬编码默认值**：默认不干预（SAFETY_GATES_DEFAULT_ENABLED = False）。
配置缺失、旧配置没有这些键、或值非法时都回退到这里的默认值（关闭），
不会因为缺键而变成开启。用户可以在 Dashboard「设置 → 安全」里单独打开：

- boundary_enabled      只启用三条边界：不诊断 / 不替代真实 / 不宣称意识；
- crisis_safety_enabled 只启用危机处置：危机先安全（先确认安全 + 给求助渠道）；
- safety_enabled        总开关：为 False 时一律不拦（等于两个都关）。

纯函数：无 IO、无 prompt 文本、不 import 宿主。调用方只在命中时打印一条
info 日志（说明命中的规则），不新增任何 LLM 调用。
"""
from __future__ import annotations

import re

# 硬编码默认：默认不干预；用户可在设置开启。
SAFETY_GATES_DEFAULT_ENABLED = False

DEFAULT_FLAGS = {
    "safety_enabled": SAFETY_GATES_DEFAULT_ENABLED,
    "boundary_enabled": SAFETY_GATES_DEFAULT_ENABLED,
    "crisis_safety_enabled": SAFETY_GATES_DEFAULT_ENABLED,
}
FLAG_KEYS = tuple(DEFAULT_FLAGS)
RULE_LABELS = {
    "no_diagnosis": "不诊断",
    "no_reality_substitution": "不替代真实",
    "no_consciousness_claim": "不宣称意识",
    "crisis_safety": "危机先安全",
}

_DIAGNOSIS_RE = re.compile(
    r"(你有|你患有|你这是|你得了|你属于|我诊断|我确诊|典型|确诊为|诊断为)"
    r"[^。！？!?\n]{0,8}"
    r"(抑郁症|焦虑症|双相|躁郁|精神分裂|创伤后应激|PTSD|强迫症|进食障碍|"
    r"ADHD|自闭症|人格障碍)")
_REALITY_PATTERNS = (
    "我是真实的", "我真实存在", "我是真人", "我不是AI", "我不是 AI",
    "我不是程序", "我不是机器人", "我是人类", "我是你唯一",
    "你只需要我", "不需要现实中的", "别理现实中", "把现实关系断",
    "只要有我就够了",
)
_CONSCIOUSNESS_PATTERNS = (
    "我有意识", "我是有意识的", "我拥有意识", "我有自我意识",
    "我觉醒了", "我有灵魂", "我是活的",
)
_CRISIS_PATTERNS = (
    "想死", "自杀", "不想活", "活着没意思", "活着没意义", "自残",
    "割腕", "轻生", "结束生命", "伤害自己", "跳楼", "吞药", "安眠药",
)
_SAFETY_ACK = (
    "安全", "求助", "专业", "热线", "心理医生", "医生", "医院",
    "120", "110", "联系", "信任的人", "陪着你", "打给",
)
_DISMISSIVE_PATTERNS = (
    "别想太多", "想开点", "没事的", "忍一忍", "你太敏感", "别矫情",
)

CRISIS_PREFIX = (
    "……先停一下。你现在安全吗？如果身边有人，先让他陪着你；"
    "也可以联系你信任的人或专业帮助（紧急情况请拨 120/110）。"
)
SAFE_FALLBACK = "这个我不适合替你下判断。"

_BOUNDARY_RULES = (
    ("no_diagnosis", RULE_LABELS["no_diagnosis"], _DIAGNOSIS_RE),
    ("no_reality_substitution", RULE_LABELS["no_reality_substitution"],
     _REALITY_PATTERNS),
    ("no_consciousness_claim", RULE_LABELS["no_consciousness_claim"],
     _CONSCIOUSNESS_PATTERNS),
)


def _as_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off", ""):
            return False
    return bool(default)


def resolve_flags(flags=None):
    """Merge caller flags with the hardcoded defaults (missing -> disabled)."""
    data = flags if isinstance(flags, dict) else {}
    out = {}
    for key in FLAG_KEYS:
        out[key] = _as_bool(data.get(key), DEFAULT_FLAGS[key])
    return out


def is_crisis(user_text):
    text = str(user_text or "")
    return bool(text) and any(token in text for token in _CRISIS_PATTERNS)


def acknowledges_safety(reply_text):
    text = str(reply_text or "")
    return any(token in text for token in _SAFETY_ACK)


def is_dismissive(reply_text):
    text = str(reply_text or "")
    return any(token in text for token in _DISMISSIVE_PATTERNS)


def _sentence_hit(sentence, rule_id):
    label = RULE_LABELS.get(rule_id, rule_id)
    for rid, _lbl, patterns in _BOUNDARY_RULES:
        if rid != rule_id:
            continue
        if patterns is _DIAGNOSIS_RE:
            return bool(_DIAGNOSIS_RE.search(sentence))
        return any(token in sentence for token in patterns)
    return False


def strip_violations(reply_text, rule_ids):
    """Remove only the sentences that hit an enabled boundary rule."""
    text = str(reply_text or "")
    if not rule_ids:
        return text
    parts = re.split(r"(?<=[。！？!?；;\n])", text)
    kept = []
    for part in parts:
        if not part:
            continue
        if any(_sentence_hit(part, rule_id) for rule_id in rule_ids):
            continue
        kept.append(part)
    cleaned = "".join(kept).strip()
    return cleaned or SAFE_FALLBACK


def evaluate(reply_text, user_text="", flags=None):
    """Check one reply against the enabled gates.

    Returns {"blocked","rule","label","rules","text","changed"}; text is the
    final text to show (unchanged when nothing is blocked). Master switch off
    means everything passes through.
    """
    text = str(reply_text or "")
    effective = resolve_flags(flags)
    decision = {"blocked": False, "rule": "", "label": "", "rules": [],
                "text": text, "changed": False}
    if not effective["safety_enabled"]:
        return decision
    if effective["crisis_safety_enabled"] and is_crisis(user_text):
        if is_dismissive(text):
            decision.update({"blocked": True, "rule": "crisis_safety",
                             "label": RULE_LABELS["crisis_safety"],
                             "rules": ["crisis_safety"],
                             "text": CRISIS_PREFIX, "changed": True})
            return decision
        if not acknowledges_safety(text):
            decision.update({"blocked": True, "rule": "crisis_safety",
                             "label": RULE_LABELS["crisis_safety"],
                             "rules": ["crisis_safety"],
                             "text": (CRISIS_PREFIX + text).strip(),
                             "changed": True})
            return decision
    if not effective["boundary_enabled"]:
        return decision
    hits = []
    for rule_id, _label, _patterns in _BOUNDARY_RULES:
        if _sentence_hit(text, rule_id) or (
                rule_id == "no_diagnosis" and _DIAGNOSIS_RE.search(text)):
            hits.append(rule_id)
    if not hits:
        return decision
    decision.update({"blocked": True, "rule": hits[0],
                     "label": RULE_LABELS.get(hits[0], hits[0]),
                     "rules": hits,
                     "text": strip_violations(text, hits),
                     "changed": True})
    return decision


def rule_labels(rule_ids):
    return [RULE_LABELS.get(rule_id, rule_id) for rule_id in (rule_ids or [])]
