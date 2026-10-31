# -*- coding: utf-8 -*-
"""Single source of truth for BioCore numeric fields + prompt legend.

The same FIELD groups generate docs/NUMERIC-SCHEMA.md (render_markdown) and the
compact prompt legend (numeric_legend), so code and documentation cannot drift.
"""
from __future__ import annotations

LEGEND_HEADER = "【内部数值 · 你的状态】"
LEGEND_LIMIT = 400
SIGNIFICANT_DELTA = 0.15
LEGEND_MAX_ITEMS = 5

GROUPS = (
    {"key": "state", "title": "内部状态",
     "items": (
         {"name": "v", "label": "效价", "min": -1.0, "max": 1.0,
          "desc": "-1 极难受 .. +1 极舒服", "baseline": 0.0, "legend": "v 效价 -1难受~+1舒服"},
         {"name": "a", "label": "唤醒", "min": 0.0, "max": 1.0,
          "desc": "0 平静 .. 1 激动", "baseline": 0.4, "legend": "a 唤醒 0平静~1激动"},
         {"name": "d", "label": "支配", "min": 0.0, "max": 1.0,
          "desc": "0 被压 .. 1 掌控", "baseline": 0.55, "legend": "d 支配 0被压~1掌控"},
         {"name": "social", "label": "社交饱和", "min": 0.0, "max": 1.0,
          "desc": "0 空 .. 1 足", "baseline": 0.55, "legend": "social 社交饱和 0空~1足"},
         {"name": "trust", "label": "信任", "min": 0.0, "max": 1.0,
          "desc": "0 无 .. 1 深", "baseline": 0.5, "legend": "trust 信任 0无~1深"},
         {"name": "stress", "label": "压力", "min": 0.0, "max": 1.0,
          "desc": "0 无 .. 1 极", "baseline": 0.1, "legend": "stress 压力 0~1"},
         {"name": "self_esteem", "label": "自尊", "min": 0.0, "max": 1.0,
          "desc": "0 低 .. 1 高", "baseline": 0.5, "legend": "self_esteem 自尊 0低~1高"},
         {"name": "social_pain", "label": "社交痛", "min": 0.0, "max": 1.0,
          "desc": "0 无 .. 1 强烈", "baseline": 0.0, "legend": "social_pain 社交痛 0~1"},
     )},
    {"key": "intero", "title": "内感受（非语言，0..1）",
     "items": (
         {"name": "tension", "label": "绷紧", "min": 0.0, "max": 1.0, "desc": "0 松 .. 1 紧", "baseline": 0.3},
         {"name": "warmth", "label": "暖", "min": 0.0, "max": 1.0, "desc": "0 冷 .. 1 暖", "baseline": 0.6},
         {"name": "heaviness", "label": "沉", "min": 0.0, "max": 1.0, "desc": "0 轻 .. 1 沉", "baseline": 0.3},
         {"name": "clarity", "label": "清", "min": 0.0, "max": 1.0, "desc": "0 糊 .. 1 清", "baseline": 0.7},
     )},
    {"key": "needs", "title": "需求（0..1，1=满足）",
     "items": (
         {"name": "belonging", "label": "归属", "min": 0.0, "max": 1.0, "desc": "0 缺 .. 1 满足", "baseline": 0.6},
         {"name": "self_esteem", "label": "自尊需求", "min": 0.0, "max": 1.0, "desc": "0 缺 .. 1 满足", "baseline": 0.6},
         {"name": "control", "label": "控制需求", "min": 0.0, "max": 1.0, "desc": "0 缺 .. 1 满足", "baseline": 0.6},
         {"name": "meaningful_existence", "label": "意义需求", "min": 0.0, "max": 1.0, "desc": "0 缺 .. 1 满足", "baseline": 0.6},
     )},
    {"key": "dims", "title": "评价维度（模型输出）",
     "items": (
         {"name": "goal", "label": "目标", "min": -1.0, "max": 1.0, "desc": "-1 受阻 .. +1 达成", "baseline": 0.0},
         {"name": "blame", "label": "归责", "min": 0.0, "max": 1.0, "desc": "0 怪我 .. 1 怪对方", "baseline": 0.5},
         {"name": "control", "label": "可控性", "min": 0.0, "max": 1.0, "desc": "0 无力 .. 1 可控", "baseline": 0.5},
         {"name": "certainty", "label": "意料程度", "min": 0.0, "max": 1.0, "desc": "0 意外 .. 1 意料之中", "baseline": 0.5},
         {"name": "novelty", "label": "新鲜", "min": 0.0, "max": 1.0, "desc": "0 熟悉 .. 1 新鲜", "baseline": 0.3},
         {"name": "involve", "label": "关乎我", "min": 0.0, "max": 1.0, "desc": "0 无关 .. 1 关乎我", "baseline": 0.5},
         {"name": "hit", "label": "被击中", "min": 0.0, "max": 1.0, "desc": "0 无冲击 .. 1 关系/自尊被击中", "baseline": 0.2},
     )},
    {"key": "rhythm", "title": "节奏参数（非状态）",
     "items": (
         {"name": "theta", "label": "阈值", "min": 0.35, "max": 0.75, "desc": "越大人设越不主动", "baseline": 0.55},
         {"name": "tau_hours", "label": "沉默时间常数", "min": 6.0, "max": 36.0, "desc": "慢/快衰减", "baseline": 18.0},
         {"name": "cooldown_s", "label": "冷却秒", "min": 1200, "max": 10800, "desc": "两次主动最短间隔", "baseline": 1800},
         {"name": "daily_cap", "label": "每日上限", "min": 1, "max": 8, "desc": "每日主动次数", "baseline": 3},
     )},
    {"key": "memory", "title": "记忆（每条）",
     "items": (
         {"name": "storage_s", "label": "存储强度", "min": 0.0, "max": 1.0, "desc": "0 弱 .. 1 强", "baseline": 0.5},
         {"name": "retrieval_s", "label": "提取强度", "min": 0.0, "max": 1.0, "desc": "0 弱 .. 1 强", "baseline": 0.5},
         {"name": "access_count", "label": "提取次数", "min": 0, "max": None, "desc": ">=0 的整数", "baseline": 0},
         {"name": "arousal_at_encoding", "label": "编码唤醒", "min": 0.0, "max": 1.0, "desc": "0 平静 .. 1 激动", "baseline": 0.5},
     )},
)
FIELDS = tuple(dict(item, group=group["key"]) for group in GROUPS for item in group["items"])
LEGEND_FIELDS = tuple(item for item in FIELDS if item.get("legend"))
LEGEND_BASELINES = {item["name"]: float(item["baseline"]) for item in LEGEND_FIELDS}


def render_markdown() -> str:
    lines = ["# BioCore 数值字典（NUMERIC-SCHEMA）", "",
             "由 biocore_model/schema.py 的 GROUPS 生成；改字段请改代码后重新生成。", ""]
    for group in GROUPS:
        lines += ["## " + group["title"], "",
                  "| 字段 | 范围 | 含义 | 基线 |", "|---|---|---|---|"]
        for item in group["items"]:
            low = item["min"]
            high = "∞" if item["max"] is None else item["max"]
            lines.append("| %s | %s .. %s | %s | %s |"
                         % (item["name"], low, high, item["desc"], item["baseline"]))
        lines.append("")
    return chr(10).join(lines)


def numeric_legend(values, baselines=None, threshold=SIGNIFICANT_DELTA,
                   max_items=LEGEND_MAX_ITEMS) -> str:
    """Compact legend for significant deviations only (<=400 chars)."""
    values = values if isinstance(values, dict) else {}
    base = dict(LEGEND_BASELINES)
    if isinstance(baselines, dict):
        base.update({key: value for key, value in baselines.items() if key in base})
    rows = []
    for item in LEGEND_FIELDS:
        name = item["name"]
        try:
            value = float(values.get(name))
        except Exception:
            continue
        try:
            delta = abs(value - float(base.get(name, item["baseline"])))
        except Exception:
            continue
        if delta >= float(threshold):
            rows.append((delta, value, item["legend"]))
    if not rows:
        return ""
    rows.sort(key=lambda row: row[0], reverse=True)
    lines = [LEGEND_HEADER]
    for _delta, value, label in rows[:max(0, int(max_items))]:
        lines.append("%s：现在 %.2f" % (label, value))
    text = chr(10).join(lines)
    return text[:LEGEND_LIMIT]
