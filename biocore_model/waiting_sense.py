# -*- coding: utf-8 -*-
"""How waiting for a reply feels, from the inside.

The gap itself is objective; the feeling is not. This module turns a measured
absence ("how long since his last message") into a bounded waiting sense:

  waiting = saturation(gap) x closeness x night x mood x expectation

- saturation is logarithmic: three hours feel much longer than one, thirty
  hours barely longer than twenty-four;
- night amplifies (22:00-06:00 strongest, evening milder);
- a close relationship amplifies, a distant one does not;
- a bad last turn keeps pressing on it;
- if she is not waiting for a reply at all, almost none of this applies.

The result names one of four feelings (平静 / 惦记 / 不安 / 赌气) plus a one-line
thought (<= 24 chars) for the expression layer.

waiting_sense(gap_seconds=0.0, last_emotion=None, relationship=None,
              awaiting_reply=True, hour=None, flags=None) returns:

  enabled, waiting, feeling, thought, threshold_hit, gap_seconds, gap_hours,
  saturation, closeness, night, factors, reason

flags['enabled'] = False -> waiting 0, feeling 平静, reason tells why.

Pure functions only: no IO, no clock, no host imports, no LLM calls. The
module never imports main.py.
"""
from __future__ import annotations

import math

FEELINGS = ("平静", "惦记", "不安", "赌气")
THOUGHTS = {
    "平静": "没等多久，该干嘛干嘛。",
    "惦记": "他怎么还没回，有点想他了。",
    "不安": "是不是我说错话了，他怎么还不回。",
    "赌气": "不回就不回，我也不稀罕。",
}
STAGES = ("stranger", "acquaintance", "friend", "close")
STAGE_CLOSENESS = {"stranger": 0.15, "acquaintance": 0.35,
                   "friend": 0.65, "close": 0.90}
SATURATION_REF = 600.0          # ten minutes: first stretch counts most
SATURATION_MAX = 7 * 24 * 3600.0
CALM_FLOOR = 0.22
THRESHOLD = 0.55
THRESHOLD_SECONDS = 6 * 3600.0
NIGHT_START = 22
NIGHT_END = 6

_ANGER = ("anger", "angry", "irritated", "mad", "生气", "愤怒", "恼")
_SAD = ("sad", "sadness", "anxious", "anxiety", "fear", "难过", "委屈",
        "焦虑", "不安")
_HAPPY = ("happy", "joy", "warm", "开心", "高兴", "暖")


def _num(value, default=0.0):
    try:
        num = float(value)
    except Exception:
        return default
    if num != num:  # NaN
        return default
    return num


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _num(value, low)))


def _emotion(last_emotion):
    if isinstance(last_emotion, dict):
        return {
            "valence": max(-1.0, min(1.0, _num(last_emotion.get("valence"), 0.0))),
            "arousal": _clamp(last_emotion.get("arousal", 0.5)),
            "label": str(last_emotion.get("label") or
                         last_emotion.get("kind") or "").strip().lower(),
        }
    if last_emotion is None:
        return {"valence": 0.0, "arousal": 0.5, "label": ""}
    if isinstance(last_emotion, str):
        label = last_emotion.strip().lower()
        if label in _ANGER:
            return {"valence": -0.7, "arousal": 0.85, "label": label}
        if label in _SAD:
            return {"valence": -0.6, "arousal": 0.30, "label": label}
        if label in _HAPPY:
            return {"valence": 0.6, "arousal": 0.40, "label": label}
        return {"valence": 0.0, "arousal": 0.5, "label": label}
    return {"valence": max(-1.0, min(1.0, _num(last_emotion, 0.0))),
            "arousal": 0.5, "label": ""}


def _relationship(relationship):
    stage = ""
    closeness = None
    if isinstance(relationship, str):
        stage = relationship.strip().lower()
    elif isinstance(relationship, dict):
        stage = str(relationship.get("stage") or "").strip().lower()
        if "closeness" in relationship:
            closeness = _clamp(relationship.get("closeness"))
        elif "intimacy" in relationship:
            closeness = _clamp(relationship.get("intimacy"))
    if closeness is None:
        closeness = STAGE_CLOSENESS.get(stage, 0.5)
    return {"stage": stage, "closeness": closeness}


def _hour(hour):
    if hour is None:
        return None
    value = _num(hour, -1.0)
    if value < 0.0:
        return None
    return int(value) % 24


def saturation(gap_seconds):
    """0-1 logarithmic saturation of the gap (7 days saturates)."""
    gap = max(0.0, _num(gap_seconds, 0.0))
    raw = math.log1p(gap / SATURATION_REF)
    ceiling = math.log1p(SATURATION_MAX / SATURATION_REF)
    return round(_clamp(raw / ceiling), 4)


def night_factor(hour=None):
    value = _hour(hour)
    if value is None:
        return 1.0
    if value >= NIGHT_START or value < NIGHT_END:
        return 1.35
    if 18 <= value < NIGHT_START:
        return 1.15
    return 1.0


def is_night(hour=None):
    value = _hour(hour)
    return bool(value is not None and (value >= NIGHT_START or value < NIGHT_END))


def _feeling(waiting, awaiting, mood, closeness):
    if not awaiting or waiting < CALM_FLOOR:
        return "平静"
    negative = mood["valence"] < -0.10
    if negative:
        angerish = (mood["label"] in _ANGER
                    or (mood["label"] not in _SAD and mood["arousal"] >= 0.60))
        if angerish and closeness >= 0.55:
            return "赌气"
        return "不安"
    return "惦记"


def _reason(gap, awaiting, closeness, night, mood, feeling):
    hours = gap / 3600.0
    parts = ["隔了%.1f小时" % hours]
    parts.append("在等回应" if awaiting else "没在等回应")
    if night:
        parts.append("夜里更容易放大")
    if closeness >= 0.60:
        parts.append("关系近，更容易在意")
    if mood["valence"] < -0.10:
        parts.append("上一轮的坏情绪还压着")
    return "，".join(parts) + "；现在是%s" % feeling


def _neutral(reason):
    return {
        "enabled": False,
        "waiting": 0.0,
        "feeling": "平静",
        "thought": "",
        "threshold_hit": False,
        "gap_seconds": 0.0,
        "gap_hours": 0.0,
        "saturation": 0.0,
        "closeness": 0.5,
        "night": False,
        "factors": {},
        "reason": reason,
    }


def waiting_sense(gap_seconds=0.0, last_emotion=None, relationship=None,
                  awaiting_reply=True, hour=None, flags=None):
    """One reading of how the waiting feels. Plain dict, no IO."""
    flags = flags if isinstance(flags, dict) else {}
    if not bool(flags.get("enabled", True)):
        return _neutral("等待感关闭，按旧行为")
    gap = max(0.0, _num(gap_seconds, 0.0))
    mood = _emotion(last_emotion)
    rel = _relationship(relationship)
    awaiting = bool(awaiting_reply)
    night = is_night(hour)
    sat = saturation(gap)
    close_factor = 1.0 + 0.45 * rel["closeness"]
    mood_factor = 1.0 + 0.20 * max(0.0, -mood["valence"]) + 0.10 * mood["arousal"]
    expect_factor = 1.0 if awaiting else 0.15
    waiting = round(_clamp(sat * close_factor * night_factor(hour)
                           * mood_factor * expect_factor), 3)
    feeling = _feeling(waiting, awaiting, mood, rel["closeness"])
    threshold = _clamp(flags.get("threshold", THRESHOLD))
    threshold_seconds = max(0.0, _num(flags.get("threshold_seconds"),
                                      THRESHOLD_SECONDS))
    threshold_hit = bool(waiting >= threshold
                        or (awaiting and gap >= threshold_seconds))
    return {
        "enabled": True,
        "waiting": waiting,
        "feeling": feeling,
        "thought": THOUGHTS[feeling][:24],
        "threshold_hit": threshold_hit,
        "gap_seconds": round(gap, 1),
        "gap_hours": round(gap / 3600.0, 2),
        "saturation": sat,
        "closeness": round(rel["closeness"], 3),
        "night": night,
        "factors": {
            "saturation": sat,
            "closeness": round(close_factor, 3),
            "night": night_factor(hour),
            "mood": round(mood_factor, 3),
            "expectation": expect_factor,
        },
        "reason": _reason(gap, awaiting, rel["closeness"], night, mood, feeling),
    }
