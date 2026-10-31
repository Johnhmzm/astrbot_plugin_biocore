# -*- coding: utf-8 -*-
"""L0 constants shared by BioCore and extracted bio mixins."""
from __future__ import annotations

from typing import Any

SENSITIZATION_STRONG_NEG_DV = -0.12
SENSITIZATION_STEP = 0.15
SENSITIZATION_MAX = 1.25
SENSITIZATION_HALF_LIFE_HOURS = 24.0
SENSITIZATION_HISTORY_MAX = 12
SENSITIZATION_HISTORY_MAX_AGE = 2 * 86400.0
RECOVERY_CONTEXT_MIN = 0.8
RECOVERY_CONTEXT_MAX = 1.2

LEX = {
    "sadness": ("难过", "伤心", "委屈", "哭", "失望", "累", "撑不住", "难受", "委屈", "失落", "低落"),
    "anger": ("生气", "烦", "气死", "骂", "傻逼", "滚", "恶心", "废物", "垃圾", "讨厌", "闭嘴", "没用", "蠢", "去死", "烦", "别烦", "闭嘴", "滚", "讨厌", "气人"),
    "fear": ("怕", "焦虑", "紧张", "担心", "失眠", "慌", "慌", "不安", "怕", "紧张"),
    "joy": ("开心", "高兴", "喜欢", "好耶", "笑死", "可爱", "谢谢"),
    "loneliness": ("孤独", "一个人", "没人", "空虚", "丢下", "被丢下", "冷落", "忽视", "没人理", "不理我", "抛弃", "一个人", "孤单"),
}

EMOTION_SPECTRUM = [
    ("admiration", "钦佩", 0.40, 0.25, 0.45, 0.55),
    ("adoration", "爱慕", 0.80, 0.45, 0.40, 0.90),
    ("aesthetic", "审美欣赏", 0.50, 0.30, 0.45, 0.60),
    ("amusement", "好笑", 0.80, 0.60, 0.55, 0.60),
    ("anger", "生气", -0.60, 0.80, 0.85, 0.30),
    ("anxiety", "焦虑", -0.40, 0.80, 0.20, 0.30),
    ("awe", "敬畏", 0.60, 0.70, 0.20, 0.60),
    ("awkwardness", "尴尬", -0.20, 0.50, 0.10, 0.40),
    ("boredom", "无聊", -0.40, 0.10, 0.40, 0.40),
    ("calmness", "平静", 0.10, 0.20, 0.50, 0.50),
    ("confusion", "困惑", -0.10, 0.50, 0.40, 0.50),
    ("contempt", "轻蔑", -0.50, 0.40, 0.90, 0.30),
    ("contentment", "满足", 0.60, 0.20, 0.60, 0.70),
    ("desire", "欲望", 0.60, 0.70, 0.60, 0.60),
    ("disappointment", "失望", -0.50, 0.30, 0.40, 0.50),
    ("disgust", "厌恶", -0.60, 0.40, 0.70, 0.40),
    ("empathic_pain", "共情痛苦", -0.40, 0.40, 0.20, 0.70),
    ("entrancement", "入迷", 0.50, 0.50, 0.40, 0.60),
    ("envy", "嫉妒", -0.40, 0.60, 0.30, 0.40),
    ("excitement", "兴奋", 0.70, 0.90, 0.50, 0.60),
    ("fear", "害怕", -0.50, 0.80, 0.20, 0.40),
    ("guilt", "内疚", -0.50, 0.40, 0.30, 0.50),
    ("horror", "恐惧", -0.80, 0.90, 0.20, 0.40),
    ("interest", "兴趣", 0.40, 0.50, 0.50, 0.60),
    ("joy", "快乐", 0.80, 0.60, 0.60, 0.70),
    ("nostalgia", "怀念", 0.30, 0.30, 0.40, 0.60),
    ("pride", "自豪", 0.60, 0.50, 0.90, 0.60),
]

# Cowen & Keltner (2017) prototype space: which EMOTION_SPECTRUM anchors a
# basic emotion label may calibrate from this core's own state history.
SPECTRUM_FAMILY = {
    "joy": ("joy", "amusement", "contentment", "excitement", "pride", "adoration", "admiration"),
    "sadness": ("disappointment", "empathic_pain", "nostalgia", "guilt"),
    "anger": ("anger", "contempt", "disgust"),
    "fear": ("fear", "anxiety", "horror"),
    "loneliness": ("empathic_pain", "disappointment", "nostalgia"),
}

# Plutchik wheel pairs (L0 emotion wheel view, used by SnapshotMixin.snapshot).
PLUTCHIK_WHEEL = {
    "joy": ("joy", "trust", "anticipation", "surprise"),
    "trust": ("trust", "joy", "acceptance", "admiration"),
    "fear": ("fear", "surprise", "apprehension", "awe"),
    "surprise": ("surprise", "fear", "distraction", "amazement"),
    "sadness": ("sadness", "disgust", "pensiveness", "remorse"),
    "disgust": ("disgust", "sadness", "boredom", "loathing"),
    "anger": ("anger", "anticipation", "annoyance", "rage"),
    "anticipation": ("anticipation", "anger", "interest", "vigilance"),
}

# Batch B (task-115): moved verbatim from main.py so DailyMixin can import them.
LEARNING_Q_WEIGHT = 0.05

# Gross process model: cost paid by each regulation strategy (0..1 scale,
# distraction pays the highest bill because it leaves the concern unaddressed).
REGULATION_COST = {
    "seek_comfort": 0.003,
    "reappraise": 0.002,
    "suppress": 0.010,
    "avoid": 0.004,
    "express": 0.002,
    "distraction": 0.006,
    # Batch4 B2: affect labeling is the 7th, lowest-cost strategy.
    "label_emotion": 0.001,
}

# Batch4 B2: affect-labeling trigger thresholds (deterministic).
AFFECT_LABEL_MIN_TOP_P = 0.60
AFFECT_LABEL_MIN_AROUSAL = 0.60
# Low-cost strategy should not be picked every tick; deterministic cooldown.
AFFECT_LABEL_COOLDOWN_SECONDS = 600

REGULATION_STATS_HALF_LIFE_DAYS = 10.0
REFLECTION_TREE_TTL_DAYS = 90.0
NOISE_CLAMP = 0.30
AUTONOMY_WEIGHTS = {
    "chaos": 0.22, "echo": 0.16, "stress_load": 0.18,
    "drive_dev": 0.16, "distrust": 0.14, "distance": 0.14,
}

AUTONOMY_THRESHOLD_MIN = 0.55
AUTONOMY_THRESHOLD_MAX = 0.90
AUTONOMY_EXIT = 0.60  # hysteresis: stay ready until below this
AUTONOMY_ENTER = 0.72  # hysteresis: enter ready
AUTONOMY_MAX_CHARS_MIN = 60
AUTONOMY_MAX_CHARS_MAX = 240
AUTONOMY_COOLDOWN_SECONDS = 30 * 60
AUTONOMY_DAILY_CAP = 3
AUTONOMY_QUIET_START_HOUR = 0
AUTONOMY_QUIET_END_HOUR = 8


def circadian_alertness(hour: Any) -> float:
    """Deterministic local-hour alertness (0..1); no LLM/network."""
    try:
        h = float(hour) % 24.0
    except Exception:
        h = 12.0
    anchors = ((0.0, 0.25), (3.0, 0.20), (6.0, 0.35), (8.0, 0.85),
               (10.0, 0.95), (13.0, 0.78), (15.0, 0.72), (17.0, 0.88),
               (20.0, 0.70), (23.0, 0.45), (24.0, 0.25))
    for i in range(1, len(anchors)):
        if h <= anchors[i][0]:
            x0, y0 = anchors[i - 1]
            x1, y1 = anchors[i]
            if x1 <= x0:
                return round(y1, 3)
            return round(y0 + (y1 - y0) * (h - x0) / (x1 - x0), 3)
    return 0.25
