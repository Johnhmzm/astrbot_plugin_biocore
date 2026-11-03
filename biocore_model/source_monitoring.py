# -*- coding: utf-8 -*-
"""Source monitoring and mood-congruent recall, the missing half of reconstruction.

Reconstruction.py drifts the colour of a memory. This module answers two
questions that sit underneath it:

1. Source monitoring. A memory is either something she lived through, something
   she was told, or something she inferred. The trace of "where I got this"
   fades faster than the content: the guessed source can drift after a long
   time, especially when the memory is very similar to her own experience. The
   result reports the believed source, how confident she is, and how likely a
   misattribution is (1 - probability of the recorded source).

2. Mood-congruent recall. A low mood makes negative memories come easier and
   positive ones harder; a warm mood does the opposite. The result reports a
   signed recall_bias (negative = negative memories favoured) and a
   recall_weight multiplier the recall layer may apply.

monitor(memory_meta=None, emotion=None, flags=None) returns:

  enabled, source, label, claimed_source, confidence, probabilities,
  misattribution, recall_bias, recall_weight, congruent, reason

memory_meta: {'source': experienced|told|inferred, 'age_days': float,
              'similarity': 0-1, 'valence': -1..1, 'importance': 0-1,
              'rehearsals': int}
emotion:     {'valence': -1..1, 'arousal': 0-1} or a bare valence number

flags['enabled'] = False -> neutral result, original record wins.

Pure functions only: no IO, no clock, no host imports, no LLM calls. The
module never imports main.py.
"""
from __future__ import annotations

import math

SOURCES = ("experienced", "told", "inferred")
LABELS = {
    "experienced": "自己经历",
    "told": "你告诉她的",
    "inferred": "她推测的",
}
SOURCE_PRIOR = {"experienced": 0.55, "told": 0.28, "inferred": 0.17}
AGE_HALF_LIFE = 240.0
_ALIASES = {
    "experienced": "experienced", "self": "experienced", "own": "experienced",
    "lived": "experienced", "memory": "experienced",
    "told": "told", "hearsay": "told", "you": "told", "user": "told",
    "heard": "told", "secondhand": "told",
    "inferred": "inferred", "guess": "inferred", "guessed": "inferred",
    "inference": "inferred", "推测": "inferred",
}


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


def _signed(value):
    return max(-1.0, min(1.0, _num(value, 0.0)))


def _source_name(value):
    name = str(value or "").strip().lower()
    return _ALIASES.get(name, "")


def _meta(meta):
    meta = meta if isinstance(meta, dict) else {}
    age = _num(meta.get("age_days"), -1.0)
    if age < 0.0:
        age = _num(meta.get("age_hours"), -1.0)
        if age >= 0.0:
            age = age / 24.0
        else:
            age = _num(meta.get("age"), 0.0)
    return {
        "source": _source_name(meta.get("source")),
        "age_days": max(0.0, age),
        "similarity": _clamp(meta.get("similarity", 0.3)),
        "valence": _signed(meta.get("valence")),
        "importance": _clamp(meta.get("importance", 0.5)),
        "rehearsals": int(max(0.0, _num(
            meta.get("rehearsals", meta.get("recall_count")), 0.0))),
    }


def _emotion(emotion):
    if isinstance(emotion, dict):
        return {
            "valence": _signed(emotion.get("valence")),
            "arousal": _clamp(emotion.get("arousal", 0.5)),
        }
    if emotion is None:
        return {"valence": 0.0, "arousal": 0.5}
    return {"valence": _signed(emotion), "arousal": 0.5}


def trace_strength(age_days):
    """How much of the "where I got this" trace is left (0-1)."""
    return round(math.exp(-max(0.0, _num(age_days, 0.0)) / AGE_HALF_LIFE), 4)


def source_probabilities(meta=None):
    """Believed source distribution after time and similarity confusion."""
    row = _meta(meta)
    claimed = row["source"]
    trace = trace_strength(row["age_days"])
    confusion = (1.0 - trace) * row["similarity"]

    if claimed in SOURCES:
        raw = {source: 0.10 for source in SOURCES}
        raw[claimed] = 0.70
    else:
        raw = dict(SOURCE_PRIOR)

    raw["experienced"] += 0.60 * confusion
    if claimed == "told":
        raw["told"] *= (0.35 + 0.65 * trace)
    elif claimed == "experienced":
        raw["experienced"] *= (0.55 + 0.45 * trace)
    elif claimed == "inferred":
        raw["inferred"] *= (0.45 + 0.55 * trace)
    else:
        raw["experienced"] *= 0.85 + 0.15 * trace

    if claimed != "inferred":
        # Long ago and not similar to her own life: she may think she guessed.
        raw["inferred"] += 0.30 * (1.0 - trace) * (1.0 - row["similarity"])

    boost = 1.0 + 0.10 * min(row["rehearsals"], 5)
    for source in SOURCES:
        raw[source] = max(0.0, raw[source])
    if claimed in SOURCES:
        raw[claimed] *= boost

    total = sum(raw.values())
    if total <= 0.0:
        return {source: (1.0 if source == "experienced" else 0.0)
                for source in SOURCES}
    return {source: raw[source] / total for source in SOURCES}


def believed_source(meta=None):
    """The source she would name now, with its probability."""
    probs = source_probabilities(meta)
    source = max(SOURCES, key=lambda name: probs[name])
    return source, round(probs[source], 3)


def confidence(meta=None):
    """How sure she is about the source (0-1)."""
    row = _meta(meta)
    probs = source_probabilities(meta)
    ordered = sorted(probs.values(), reverse=True)
    top = ordered[0] if ordered else 0.0
    margin = top - (ordered[1] if len(ordered) > 1 else 0.0)
    base = (0.45 * top + 0.30 * margin + 0.15 * row["importance"]
            + 0.10 * min(row["rehearsals"], 5) / 5.0)
    decay = 0.55 + 0.45 * trace_strength(row["age_days"])
    return round(_clamp(base * decay), 3)


def misattribution(meta=None):
    """Probability that the believed source is not the recorded one."""
    row = _meta(meta)
    probs = source_probabilities(meta)
    source = max(SOURCES, key=lambda name: probs[name])
    claimed = row["source"]
    if claimed in SOURCES:
        return round(_clamp(1.0 - probs[claimed]), 3), source
    return 0.0, source


def recall_bias(emotion=None, meta=None):
    """Signed mood-congruent bias: negative = negative memories favoured."""
    mood = _emotion(emotion)
    row = _meta(meta)
    strength = (abs(mood["valence"]) * (0.55 + 0.25 * mood["arousal"])
                * (1.0 - 0.15 * row["importance"]))
    sign = 1.0 if mood["valence"] > 0 else (-1.0 if mood["valence"] < 0 else 0.0)
    return round(sign * _clamp(strength), 3)


def recall_weight(emotion=None, meta=None):
    """Multiplier for this memory under the current mood (0.4-1.6)."""
    row = _meta(meta)
    bias = recall_bias(emotion, meta)
    memory_valence = row["valence"]
    if abs(memory_valence) < 0.05 or bias == 0.0:
        return 1.0
    raw = 1.0 + 0.60 * bias * (1.0 if memory_valence > 0 else -1.0) \
        * _clamp(abs(memory_valence))
    return round(_clamp(raw, 0.4, 1.6), 3)


def _reason(row, emotion, source, probs, bias):
    bits = []
    claimed = row["source"]
    if claimed and source != claimed:
        bits.append("来源记混了，更像%s" % LABELS[source])
    elif claimed:
        bits.append("来源清楚：%s" % LABELS[source])
    else:
        bits.append("来源不明，更像%s" % LABELS[source])
    if row["age_days"] > AGE_HALF_LIFE:
        bits.append("隔得久了，细节已经淡了")
    if bias <= -0.05:
        bits.append("心情低，负性记忆更容易冒出来")
    elif bias >= 0.05:
        bits.append("心情好，好的记忆更容易冒出来")
    else:
        bits.append("情绪平，回忆没有明显偏向")
    return "；".join(bits)


def _disabled(meta=None):
    row = _meta(meta)
    return {
        "enabled": False,
        "source": row["source"] or "unknown",
        "label": LABELS.get(row["source"], ""),
        "claimed_source": row["source"],
        "confidence": 0.0,
        "probabilities": {},
        "misattribution": 0.0,
        "recall_bias": 0.0,
        "recall_weight": 1.0,
        "congruent": False,
        "reason": "来源监控关闭，按原始记录",
    }


def monitor(memory_meta=None, emotion=None, flags=None):
    """Believed source + mood-congruent recall bias. Plain dict, no IO."""
    flags = flags if isinstance(flags, dict) else {}
    if not bool(flags.get("enabled", True)):
        return _disabled(memory_meta)

    row = _meta(memory_meta)
    mood = _emotion(emotion)
    probs = source_probabilities(memory_meta)
    source = max(SOURCES, key=lambda name: probs[name])
    conf = confidence(memory_meta)
    mis, _ = misattribution(memory_meta)
    bias = recall_bias(emotion, memory_meta)
    weight = recall_weight(emotion, memory_meta)
    congruent = bool(
        bias != 0.0 and row["valence"] != 0.0
        and (bias > 0) == (row["valence"] > 0))
    return {
        "enabled": True,
        "source": source,
        "label": LABELS[source],
        "claimed_source": row["source"],
        "confidence": conf,
        "probabilities": {name: round(probs[name], 3) for name in SOURCES},
        "misattribution": mis,
        "recall_bias": bias,
        "recall_weight": weight,
        "congruent": congruent,
        "reason": _reason(row, mood, source, probs, bias),
    }


def readout(result):
    """Bounded projection for the dashboard (no IO, no prompt text)."""
    if not isinstance(result, dict) or not result.get("enabled", True):
        return {"enabled": False, "source": "", "confidence": 0.0,
                "recall_bias": 0.0, "recall_weight": 1.0, "reason": ""}
    source = str(result.get("source") or "")
    return {
        "enabled": True,
        "source": source if source in SOURCES else "unknown",
        "label": str(result.get("label") or "")[:12],
        "confidence": round(_clamp(result.get("confidence", 0.0)), 3),
        "recall_bias": round(max(-1.0, min(1.0, _num(result.get("recall_bias"), 0.0))), 3),
        "recall_weight": round(_clamp(result.get("recall_weight", 1.0), 0.4, 1.6), 3),
        "congruent": bool(result.get("congruent", False)),
        "reason": str(result.get("reason") or "")[:80],
    }
