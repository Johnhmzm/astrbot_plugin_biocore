# -*- coding: utf-8 -*-
"""Usage feedback and axis-weight learning for the spatial ranker.

A ranker that never looks at what was actually used cannot tell a good axis
from a decorative one. Each turn the reply is checked against the entries the
core recalled; "used" entries are recorded next to the ones it ignored, and a
perceptron-style update (Xing 2003 metric learning, the pull-push form of
LMNN) moves weight toward the axes on which the used entry sat closer than the
unused one. Everything here is deterministic and free: token/entity overlap,
no model call, no prompt text.

Two switches, both ON by default:
  spatial_feedback  record used/unused rows to <data dir>/spatial_feedback.jsonl
  spatial_learn     turn those rows into axis weights (<data dir>/spatial_weights.json)
Below MIN_SAMPLES rows the equal 0.2 weights stay: the learner has no evidence.
"""
from __future__ import annotations

import json
import math
import os
import re
import time

from . import space

FEEDBACK_SWITCH = "spatial_feedback"
FEEDBACK_ENV = "BIOCORE_SPATIAL_FEEDBACK"
LEARN_SWITCH = "spatial_learn"
LEARN_ENV = "BIOCORE_SPATIAL_LEARN"
ETA_KEY = "spatial_learn_eta"
ETA_ENV = "BIOCORE_SPATIAL_LEARN_ETA"
FEEDBACK_FILE = "spatial_feedback.jsonl"
WEIGHTS_FILE = "spatial_weights.json"
DEFAULT_ETA = 0.02
MIN_SAMPLES = 30
WEIGHT_MIN = 0.05
WEIGHT_MAX = 0.6
HISTORY_LIMIT = 10
FEEDBACK_READ_LIMIT = 2000

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _switch(name, env_name, flags=None, env=None, default=True):
    """flag > nested switches > env > default."""
    data = flags if isinstance(flags, dict) else {}
    if isinstance(data.get(name), bool):
        return data[name]
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    if isinstance(switches.get(name), bool):
        return switches[name]
    environ = env if hasattr(env, "get") else None
    if environ is not None and env_name in environ:
        raw = str(environ.get(env_name)).strip().lower()
        if raw in ("0", "false", "off", "no"):
            return False
        if raw in ("1", "true", "on", "yes"):
            return True
    return default


def feedback_enabled(flags=None, env=None):
    return _switch(FEEDBACK_SWITCH, FEEDBACK_ENV, flags, env, True)


def learn_enabled(flags=None, env=None):
    return _switch(LEARN_SWITCH, LEARN_ENV, flags, env, True)


def eta(flags=None, env=None):
    data = flags if isinstance(flags, dict) else {}
    raw = data.get(ETA_KEY)
    if raw is None and isinstance(data.get("switches"), dict):
        raw = data["switches"].get(ETA_KEY)
    environ = env if hasattr(env, "get") else None
    if raw is None and environ is not None and ETA_ENV in environ:
        raw = environ.get(ETA_ENV)
    try:
        value = float(raw)
    except Exception:
        value = DEFAULT_ETA
    return max(0.0, min(0.5, value))


def feedback_path(data_dir):
    return None if data_dir in (None, "") else os.path.join(str(data_dir), FEEDBACK_FILE)


def weights_path(data_dir):
    return None if data_dir in (None, "") else os.path.join(str(data_dir), WEIGHTS_FILE)


def equal_weights():
    return {axis: round(1.0 / len(space.AXES), 6) for axis in space.AXES}


def key_phrases(entry):
    """The phrases a reply must contain for the entry to count as used.

    Reuses what the write path already extracted: entities, tags, concepts,
    the cue index (entities/place/event_name), the numbers in the text and the
    long tokens space.tokens() produces. No model, no new word list.
    """
    entry = entry if isinstance(entry, dict) else {}
    raw = []
    for key in ("entities", "tags", "concepts", "entity"):
        values = entry.get(key)
        if isinstance(values, str):
            values = [values]
        for value in values or []:
            raw.append(str(value or "").strip())
    cues = entry.get("cues") if isinstance(entry.get("cues"), dict) else {}
    for key in ("entities", "place", "event_name"):
        values = cues.get(key)
        if isinstance(values, str):
            values = [values]
        for value in values or []:
            raw.append(str(value or "").strip())
    for number in _NUMBER.findall(str(entry.get("text") or "")):
        if len(number) >= 2:      # a single digit proves nothing on its own
            raw.append(number)
    for token in space.tokens(str(entry.get("text") or "")):
        if len(token) >= 4:      # long CJK run or a latin word, not a bigram
            raw.append(token)
    out = []
    for phrase in raw:
        phrase = phrase.strip()
        if len(phrase) >= 2 and phrase not in out:
            out.append(phrase)
    return out[:24]


def judge_used(entry, reply_text):
    """True when the reply mentions something only this entry supplied."""
    body = str(reply_text or "")
    if not body.strip():
        return False
    lowered = body.lower()
    for phrase in key_phrases(entry):
        if phrase in body or phrase.lower() in lowered:
            return True
    # no entity/number matched: fall back to overlap over the same tokens the
    # write path already produced (bigrams for CJK, words for latin). Half of
    # an entry reappearing in the reply is a usable, repeatable signal.
    tokens = [token for token in space.tokens(str(entry.get("text") or ""))
              if len(token) >= 2]
    if not tokens:
        return False
    hits = sum(1 for token in tokens if token in body)
    return hits / float(len(tokens)) >= 0.5


def distance_block(query, entry, now=None):
    """Per-axis distance from the turn query to one entry (for the update)."""
    try:
        query_space = space.query_space(query, now=now)
        entry_space = (entry.get("space") if isinstance(entry.get("space"), dict)
                       else space.build(entry, now=now))
        if not isinstance(entry_space, dict):
            return {}
        return space.distance(entry_space, query_space)
    except Exception:
        return {}


def append_rows(path, rows):
    """Append JSON lines; a broken write never breaks the turn."""
    if not path or not rows:
        return 0
    try:
        folder = os.path.dirname(os.path.abspath(path))
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return len(rows)
    except Exception:
        return 0


def load_rows(path, limit=None):
    """Read the feedback log; corrupt lines are skipped, not fatal."""
    if not path or not os.path.isfile(path):
        return []
    rows = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except Exception:
        return []
    if limit is not None:
        rows = rows[-max(0, int(limit)):]
    return rows


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return float(default)
    if not math.isfinite(number):
        return float(default)
    return number


def _groups(rows):
    """Feedback rows grouped by the query that produced them."""
    groups = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if not isinstance(row.get("d"), dict) or not row.get("d"):
            continue
        key = str(row.get("query") or "")
        bucket = groups.setdefault(key, {"used": [], "unused": []})
        bucket["used" if row.get("used") else "unused"].append(row)
    return groups


def learn(rows, eta_value=None):
    """Perceptron update from used/unused pairs (Xing 2003 / LMNN pull-push).

    For every pair inside one query, an axis on which the used entry sat closer
    than the unused one gains weight:  w += eta * (d_unused - d_used) / Z,
    with Z the number of pairs (a mean update, so the step does not explode
    when a turn recalls many entries). Weights are then clipped to
    [WEIGHT_MIN, WEIGHT_MAX] and normalised to sum one.
    """
    rate = DEFAULT_ETA if eta_value is None else max(0.0, min(0.5, _num(eta_value, DEFAULT_ETA)))
    weights = {axis: 0.2 for axis in space.AXES}
    deltas = {axis: 0.0 for axis in space.AXES}
    pairs = 0
    for bucket in _groups(rows).values():
        for used in bucket["used"]:
            for unused in bucket["unused"]:
                d_used = used.get("d") or {}
                d_unused = unused.get("d") or {}
                for axis in space.AXES:
                    deltas[axis] += (_num(d_unused.get(axis))
                                     - _num(d_used.get(axis)))
                pairs += 1
    if pairs:
        for axis in space.AXES:
            weights[axis] += rate * deltas[axis] / float(pairs)
    clipped = {axis: max(WEIGHT_MIN, min(WEIGHT_MAX, weights[axis]))
               for axis in space.AXES}
    total = sum(clipped.values())
    if total <= 0:
        return equal_weights(), pairs
    out = {axis: round(clipped[axis] / total, 6) for axis in space.AXES}
    return out, pairs


def load_weights(path):
    """Read the persisted learner state; a corrupt file is simply absent."""
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except Exception:
        return {}
    if not isinstance(doc, dict):
        return {}
    weights = doc.get("weights")
    if isinstance(weights, dict):
        doc["weights"] = {axis: _num(weights.get(axis), 0.0) for axis in space.AXES}
    return doc


def save_weights(path, state):
    """Atomic write: temp file + replace (a half file is never the file)."""
    if not path or not isinstance(state, dict):
        return False
    try:
        folder = os.path.dirname(os.path.abspath(path))
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def learn_and_save(path, rows, eta_value=None, now=None):
    """Recompute the weights from the log and persist them with a short history."""
    weights, pairs = learn(rows, eta_value)
    stamp = round(_num(now, time.time()), 3)
    previous = load_weights(path)
    history = [row for row in (previous.get("history") or [])
               if isinstance(row, dict)]
    history.append({"ts": stamp, "samples": len(rows or []), "pairs": pairs,
                    "weights": weights})
    state = {"weights": weights, "samples": len(rows or []), "pairs": pairs,
             "eta": DEFAULT_ETA if eta_value is None else _num(eta_value, DEFAULT_ETA),
             "updated_at": stamp, "history": history[-HISTORY_LIMIT:]}
    save_weights(path, state)
    return state


def learning_view(data_dir, flags=None, env=None):
    """The /state block: what the learner currently believes and why."""
    enabled = learn_enabled(flags, env)
    state = load_weights(weights_path(data_dir))
    rows = load_rows(feedback_path(data_dir), limit=FEEDBACK_READ_LIMIT)
    samples = len(rows)
    used = sum(1 for row in rows if row.get("used"))
    ready = bool(enabled and samples >= MIN_SAMPLES
                 and isinstance(state.get("weights"), dict))
    if not enabled:
        reason = "switch_off"
    elif samples < MIN_SAMPLES:
        reason = "sample_too_small"
    elif not isinstance(state.get("weights"), dict):
        reason = "no_weights"
    else:
        reason = ""
    return {"enabled": enabled,
            "weights": state.get("weights") if ready else equal_weights(),
            "samples": samples,
            "used_rate": round(used / float(samples), 4) if samples else 0.0,
            "last_update": _num(state.get("updated_at"), 0.0),
            "reason": reason,
            "pairs": int(_num(state.get("pairs"), 0)),
            "history": state.get("history") or []}


def active_weights(data_dir, flags=None, env=None):
    """Weights to rank with, or None to keep the configured/equal ones."""
    view = learning_view(data_dir, flags, env)
    if view["enabled"] and not view["reason"]:
        return view["weights"]
    return None
