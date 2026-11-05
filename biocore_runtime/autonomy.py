# -*- coding: utf-8 -*-
"""task-222: autonomy / motivation decision layer (core-owned).

The adapter only executes the one action this module returns and appends the
result to <dataDir>/actions.jsonl. Every limit, quiet-hour and drive check is
here; the adapter has no judgement.

Action kinds:
  send      deliver a short message (adapter uses the host channel)
  write     remember one short note
  retrieve  recall by topic and read the result
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ACTIONS_FILE = "actions.jsonl"
ACTIONS_KEEP = 500
LIMIT_DEFAULTS = {
    "max_actions_per_hour": 20,
    "max_sends_per_hour": 5,
    "max_sends_per_day": 30,
    "quiet_hours": [],
    "auto_decay_on_silence": True,
}
MIN_ACTION_GAP_SECONDS = 600
DECAYED_GAP_SECONDS = 1800
SEND_TEXT = "在忙吗？突然想问一句。"
MEMORY_NOTE = "刚才想到一点，先记下来。"


def _root(store):
    if isinstance(store, dict):
        raw = store.get("root") or store.get("store") or store.get("path")
    else:
        raw = store
    text = str(raw or "").strip()
    return Path(text) if text else None


def _data_dir(store):
    root = _root(store)
    if root is None:
        return None
    return root.parent if root.name == "memory" else root


def _load_config(store):
    data_dir = _data_dir(store)
    if data_dir is None:
        return {}
    try:
        cfg = json.loads((data_dir / "core_config.json").read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    return cfg if isinstance(cfg, dict) else {}


def limits(store):
    raw = _load_config(store).get("autonomy")
    out = dict(LIMIT_DEFAULTS)
    if isinstance(raw, dict):
        for key in ("max_actions_per_hour", "max_sends_per_hour",
                    "max_sends_per_day"):
            try:
                out[key] = max(0, int(raw.get(key, out[key])))
            except Exception:
                pass
        quiet = raw.get("quiet_hours")
        if isinstance(quiet, list):
            out["quiet_hours"] = [str(item)[:12] for item in quiet][:12]
        out["auto_decay_on_silence"] = raw.get(
            "auto_decay_on_silence", out["auto_decay_on_silence"]) is not False
    return out


def actions_path(store):
    data_dir = _data_dir(store)
    return (data_dir / ACTIONS_FILE) if data_dir is not None else None


def read_actions(store):
    path = actions_path(store)
    rows = []
    try:
        if path is None or not path.exists():
            return rows
        for line in path.read_text(encoding="utf-8").splitlines():
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
        return rows
    return rows


def _in_quiet(hours, now):
    try:
        stamp = time.localtime(float(now))
    except Exception:
        return False
    minute = stamp.tm_hour * 60 + stamp.tm_min
    for window in hours or []:
        text = str(window or "").strip()
        if "-" not in text:
            continue
        try:
            left, right = text.split("-", 1)
            lh, lm = [int(part) for part in left.split(":")]
            rh, rm = [int(part) for part in right.split(":")]
        except Exception:
            continue
        start, end = lh * 60 + lm, rh * 60 + rm
        if start <= end and start <= minute < end:
            return True
        if start > end and (minute >= start or minute < end):
            return True
    return False


def metrics(store, now=None):
    stamp = float(now or time.time())
    day_start = time.mktime(time.localtime(stamp)[:3] + (0, 0, 0, 0, 0, -1))
    hour_start = stamp - 3600.0
    actions_today = sends_today = actions_hour = sends_hour = 0
    for row in read_actions(store):
        ts = float(row.get("ts") or 0.0)
        kind = str(row.get("kind") or "")
        if ts >= day_start:
            actions_today += 1
            if kind == "send":
                sends_today += 1
        if ts >= hour_start:
            actions_hour += 1
            if kind == "send":
                sends_hour += 1
    last_ts = max((float(row.get("ts") or 0.0) for row in read_actions(store)),
                  default=0.0)
    return {"actions_today": actions_today, "sends_today": sends_today,
            "actions_hour": actions_hour, "sends_hour": sends_hour,
            "last_action_ts": round(last_ts, 3)}


def _memory_count(store, session_id):
    root = _root(store)
    if root is None:
        return 0
    try:
        doc = json.loads((root / "sessions" / str(session_id or "autonomy")
                          / "memory.json").read_text(encoding="utf-8"))
        return len([row for row in (doc.get("entries") or [])
                    if isinstance(row, dict) and not row.get("deleted")])
    except Exception:
        return 0


def decide(store, now=None, session_id="autonomy", state=None,
           silence_minutes=0.0, last_human_ts=0.0):
    """Return at most one action; limits are evaluated here, not in JS."""
    stamp = float(now or time.time())
    lim = limits(store)
    stats = metrics(store, stamp)
    base = {"ok": True, "action": None, "metrics": stats, "limits": lim,
            "reason": ""}
    if stats["actions_hour"] >= lim["max_actions_per_hour"]:
        base["reason"] = "limit_actions_hour"
        return base
    last_ts = stats["last_action_ts"]
    gap = stamp - last_ts if last_ts > 0 else 10 ** 9
    silence = max(0.0, float(silence_minutes or 0.0))
    silence = silence or ((stamp - float(last_human_ts or 0.0)) / 60.0
                          if last_human_ts else 0.0)
    if lim["auto_decay_on_silence"] and silence >= 6 * 60 and gap < DECAYED_GAP_SECONDS:
        base["reason"] = "decayed_silence"
        return base
    if gap < MIN_ACTION_GAP_SECONDS:
        base["reason"] = "too_soon"
        return base
    core = state.get("core") if isinstance(state, dict) and isinstance(
        state.get("core"), dict) else (state if isinstance(state, dict) else {})
    social = float(core.get("social") or 0.55)
    energy = float(core.get("energy") or 0.6)
    quiet = _in_quiet(lim["quiet_hours"], stamp)
    can_send = (not quiet
                and stats["sends_hour"] < lim["max_sends_per_hour"]
                and stats["sends_today"] < lim["max_sends_per_day"])
    if social < 0.45 and can_send:
        base["action"] = {"kind": "send", "session_id": str(session_id),
                          "text": SEND_TEXT, "reason": "social_gap"}
        base["reason"] = "social_gap"
        return base
    if _memory_count(store, session_id) > 0 and energy >= 0.4:
        base["action"] = {"kind": "retrieve", "session_id": str(session_id),
                          "query": "最近", "reason": "review_memory"}
        base["reason"] = "review_memory"
        return base
    base["action"] = {"kind": "write", "session_id": str(session_id),
                      "text": MEMORY_NOTE, "reason": "self_note"}
    base["reason"] = "self_note"
    return base
