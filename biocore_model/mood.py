# -*- coding: utf-8 -*-
"""BIO-4: slow mood variable (biological layer). Pure functions only."""
from __future__ import annotations

RATE = 0.05


def clamp(value, low=-1.0, high=1.0):
    return max(low, min(high, float(value)))


def mood_update(mood, v, a, dt=0.0, rate=RATE, now=None):
    data = dict(mood or {"valence": 0.0, "arousal": 0.0})
    if now is not None and float(now) <= float(data.get("last_tick_ts", 0.0) or 0.0):
        return data
    data["valence"] = round(clamp(data.get("valence", 0.0) + rate * (float(v or 0.0) - float(data.get("valence", 0.0)))), 4)
    data["arousal"] = round(clamp(data.get("arousal", 0.0) + rate * (float(a or 0.0) - float(data.get("arousal", 0.0)))), 4)
    if now is not None:
        data["last_tick_ts"] = float(now)
    return data


def label(mood):
    data = mood or {}
    v = float(data.get("valence", 0.0) or 0.0)
    a = float(data.get("arousal", 0.0) or 0.0)
    if v <= 0 and a >= 0.5:
        return "低落"
    if v > 0 and a >= 0.5:
        return "愉快"
    if v > 0:
        return "平静偏正"
    return "平静"


def mood_view(mood):
    data = dict(mood or {"valence": 0.0, "arousal": 0.0})
    return {"valence": round(float(data.get("valence", 0.0) or 0.0), 3),
            "arousal": round(float(data.get("arousal", 0.0) or 0.0), 3),
            "label": label(data)}


def ticks_to_target(start, target, rate=RATE, threshold=0.05):
    import math
    distance = abs(float(target) - float(start))
    if distance <= threshold or rate <= 0:
        return 0
    return int(math.ceil(math.log(threshold / distance) / math.log(1 - rate)))
