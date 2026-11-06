# -*- coding: utf-8 -*-
"""Near-duplicate, newer wins -- a separate mechanism from version resolution.

A changed fact usually arrives as a *near* duplicate of the stored memory.
This module marks the older one superseded when BOTH hold:

    similarity >= NEAR_DUP_COSINE   (embedding cosine -- vectors only)
    text not literally identical    (identical text belongs to dedupe)

There is no topic check, no number/date regex and no lexical fallback: the
judgement rests on the vectors alone, and without vectors it does not happen
at all (the pair is reported with reason "no_vector"). It is not version
resolution: no subject, no attribute, no key. The default filter
(versioning.visible) already hides superseded entries; include_superseded
shows both.
"""
from __future__ import annotations

import json
import os

from ..core.config import NEAR_DUP_COSINE
from ..recall.channels import cosine as _cosine

SWITCH_KEY = "near_dup_time"
SWITCH_ENV = "BIOCORE_NEAR_DUP_TIME"
THRESHOLD_KEY = "near_dup_cosine"
THRESHOLD_ENV = "BIOCORE_NEAR_DUP_COSINE"
REASON = "near_dup_time"
STATE_FILE = "near_dup.json"
PAIR_KEEP = 5

def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def enabled(flags=None, env=None):
    """near_dup_time: flag > nested switches > env > default ON."""
    data = flags if isinstance(flags, dict) else {}
    if isinstance(data.get(SWITCH_KEY), bool):
        return data[SWITCH_KEY]
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    if isinstance(switches.get(SWITCH_KEY), bool):
        return switches[SWITCH_KEY]
    environ = env if hasattr(env, "get") else None
    if environ is not None and SWITCH_ENV in environ:
        raw = str(environ.get(SWITCH_ENV)).strip().lower()
        if raw in ("0", "false", "off", "no"):
            return False
        if raw in ("1", "true", "on", "yes"):
            return True
    return True


def threshold(flags=None, env=None):
    """The cosine bar; the only measure this mechanism has."""
    data = flags if isinstance(flags, dict) else {}
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    environ = env if hasattr(env, "get") else None
    raw = data.get(THRESHOLD_KEY)
    if raw is None and switches:
        raw = switches.get(THRESHOLD_KEY)
    if raw is None and environ is not None and THRESHOLD_ENV in environ:
        raw = environ.get(THRESHOLD_ENV)
    try:
        value = float(raw)
    except Exception:
        value = float(NEAR_DUP_COSINE)
    return max(0.0, min(1.0, value))


def _id(entry):
    return str((entry or {}).get("id") or "")


def _vector(entry):
    raw = (entry or {}).get("vector")
    if not isinstance(raw, (list, tuple)) or not raw:
        block = (entry or {}).get("space")
        if isinstance(block, dict) and isinstance(block.get("semantic"), dict):
            raw = block["semantic"].get("vector")
    if not isinstance(raw, (list, tuple)) or not raw:
        return []
    try:
        return [float(value) for value in raw]
    except Exception:
        return []


def measure(left, right):
    """Cosine over the vectors; metric "none" when either side carries none."""
    a, b = _vector(left), _vector(right)
    if a and b and len(a) == len(b):
        return round(max(0.0, min(1.0, _cosine(a, b))), 6), "cosine"
    return 0.0, "none"


def similarity(left, right):
    """Just the number (0.0 when a vector is missing)."""
    return measure(left, right)[0]








def decide(entry, other, threshold_value=None, flags=None, env=None):
    """One comparison; returns the pair record (action in none/mark_old/mark_new)."""
    pair = {"id": _id(other), "newer": "", "similarity": 0.0,
            "metric": "", "threshold": 0.0,
            "reason": "", "action": "none"}
    if not isinstance(entry, dict) or not isinstance(other, dict):
        pair["reason"] = "invalid"
        return pair
    value, metric = measure(entry, other)
    limit = (threshold_value if threshold_value is not None
             else threshold(flags, env))
    pair["similarity"] = value
    pair["metric"] = metric
    pair["threshold"] = limit
    left = str(entry.get("text") or "").strip().lower()
    right = str(other.get("text") or "").strip().lower()
    if left and left == right:
        pair["reason"] = "identical_text"
        return pair
    if metric == "none":
        pair["reason"] = "no_vector"
        return pair
    if pair["similarity"] < limit:
        pair["reason"] = "below_threshold"
        return pair
    stamp, other_stamp = _num(entry.get("ts")), _num(other.get("ts"))
    if stamp == other_stamp:
        pair["reason"] = "same_time"
        return pair
    if stamp > other_stamp:
        pair["action"] = "mark_old"
        pair["newer"] = _id(entry)
        pair["reason"] = REASON
    else:
        pair["action"] = "mark_new"
        pair["newer"] = _id(other)
        pair["reason"] = REASON
    return pair


def _mark(entry, by_id, now=None):
    entry["status"] = "superseded"
    entry["superseded_by"] = str(by_id or "")
    entry["superseded_at"] = round(_num(now, 0.0), 3)
    entry["superseded_reason"] = REASON
    return entry


def state_path(data_dir):
    if data_dir in (None, ""):
        return None
    return os.path.join(str(data_dir), STATE_FILE)


def _write_state(data_dir, payload):
    path = state_path(data_dir)
    if path is None or not isinstance(payload, dict):
        return False
    try:
        folder = os.path.dirname(os.path.abspath(path))
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def load_state(data_dir):
    path = state_path(data_dir)
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def apply(entries, entry, flags=None, env=None, now=None, data_dir=None):
    """Mark near-duplicates by time; returns {marked, pairs, thresholds}."""
    report = {"marked": [], "pairs": [],
              "thresholds": {"cosine": threshold(flags, env)}}
    if not enabled(flags, env) or not isinstance(entry, dict):
        return report
    scope = str(entry.get("scope") or "default")
    for other in list(entries or []):
        if not isinstance(other, dict) or other is entry:
            continue
        if other.get("deleted") or other.get("archived"):
            continue
        if str(other.get("scope") or "default") != scope:
            continue
        pair = decide(entry, other, flags=flags, env=env)   # per-measure bar
        report["pairs"].append(pair)
        if pair["action"] == "mark_old":
            _mark(other, _id(entry), now)
            report["marked"].append(_id(other))
        elif pair["action"] == "mark_new":
            _mark(entry, _id(other), now)
            report["marked"].append(_id(entry))
    if report["pairs"]:
        previous = load_state(data_dir)
        history = [row for row in (previous.get("pairs") or [])
                   if isinstance(row, dict)]
        history.extend(report["pairs"])
        _write_state(data_dir, {
            "pairs": history[-PAIR_KEEP:],
            "last_pair": report["pairs"][-1],
            "threshold": report["thresholds"]["cosine"],
            "metric": report["pairs"][-1]["metric"],
            "thresholds": report["thresholds"],
            "marked_total": int(_num(previous.get("marked_total"), 0))
            + len(report["marked"]),
            "ts": round(_num(now, 0.0), 3)})
    return report


def state_of(entries, data_dir=None, flags=None, env=None):
    """The /state.memory_versions.near_dup block."""
    stored = load_state(data_dir)
    pool = [entry for entry in (entries or []) if isinstance(entry, dict)]
    marked = sum(1 for entry in pool
                 if str(entry.get("superseded_reason") or "") == REASON)
    last = stored.get("last_pair") if isinstance(stored.get("last_pair"), dict) else {}
    metric = str(last.get("metric") or (stored.get("metric") or "cosine"))
    return {"marked": marked,
            "metric": metric,
            "threshold": (last.get("threshold")
                          if last.get("threshold") is not None
                          else threshold(flags, env)),
            "thresholds": {"cosine": threshold(flags, env)},
            "last_pair": last,
            "marked_total": int(_num(stored.get("marked_total"), 0)),
            "pairs": stored.get("pairs") or []}
