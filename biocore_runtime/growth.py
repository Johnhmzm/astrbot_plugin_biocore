# -*- coding: utf-8 -*-
"""task-220: growth metrics + a read-only consolidation dry-run.

Two read-only products over the DSH runtime store (<store>/sessions/...,
traces/, relationship.json):

1. metrics(store) -> one JSON object:
   memory    total / added_this_week / avg_importance / with_affect ratio
   recall    hits_total / mood_match_hits / avg_top_score
   relation  trust, closeness, change_7d (from growth_history.jsonl)
   narrative intent distribution (top 3, from turn traces)
   flags     the four learning switches and where their value came from

2. consolidate(store) -> candidate facts from the newest N memory entries
   (the only per-turn record that carries text):
     repeated topics (>= TOPIC_MIN_REPEAT episodes, reusing
     biocore_model.preference_drift.topics)
     stable relationship facts (trust/closeness above RELATION_STABLE_MIN)
   The result is written to <store>/consolidate_report.json. It never calls
   save_memory()/tool_call(), never edits an entry and never calls a model:
   dry_run is always true and memory_written always false.

Both are OFF by default: {"growth_report": True} or
BIOCORE_GROWTH_REPORT=1 enables consolidate(); metrics() is pure read-only and
can be called without the switch (the switch is reported in the output).

Pure-ish: no network, no LLM, no host imports. The only writes are the report
file and one history line per day.
"""
from __future__ import annotations

import json
import math
import time
from collections import Counter
from pathlib import Path

try:
    from . import pipeline as _pipeline
except Exception:  # pragma: no cover - script mode
    from biocore_runtime import pipeline as _pipeline

try:
    from biocore_model import preference_drift as _drift
except Exception:  # pragma: no cover - degraded checkout
    _drift = None

LEARNING_FLAGS = ("mood_recall", "affect_encoding",
                  "memory_feedback", "preference_drift")
ENV_FLAGS = {
    "mood_recall": "BIOCORE_MOOD_RECALL",
    "affect_encoding": "BIOCORE_AFFECT_ENCODING",
    "memory_feedback": "BIOCORE_MEMORY_FEEDBACK",
    "preference_drift": "BIOCORE_PREFERENCE_DRIFT",
}
GROWTH_ENV = "BIOCORE_GROWTH_REPORT"
REPORT_FILE = "consolidate_report.json"
HISTORY_FILE = "growth_history.jsonl"
DEFAULT_EPISODES = 30
HISTORY_KEEP = 120
WEEK_SECONDS = 7 * 86400.0
SECTION_TOP = 3
TOPIC_MIN_REPEAT = 2
MAX_CANDIDATES = 8
RELATION_STABLE_MIN = 0.60


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return default
    return number if number == number else default


def _root(store):
    if isinstance(store, dict):
        raw = store.get("root") or store.get("store") or store.get("path")
    else:
        raw = store
    text = str(raw or "").strip()
    return Path(text) if text else None


def _read_json(path, fallback):
    try:
        if path is None or not Path(path).exists():
            return fallback
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else fallback
    except Exception:
        return fallback


def _atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)


def _truthy(raw):
    return str(raw or "").strip().lower() in ("1", "true", "on", "yes")


def enabled(flags=None, env=None):
    """Flag or env switch; both default OFF."""
    data = flags if isinstance(flags, dict) else {}
    if "growth_report" in data:
        return bool(data.get("growth_report"))
    raw = env.get(GROWTH_ENV) if hasattr(env, "get") else None
    return _truthy(raw)


# consolidate() takes an "enabled" argument, so keep a second name for the
# function itself (the parameter must not shadow the module's switch reader).
_enabled = enabled


def report_path(store):
    root = _root(store)
    return (root / REPORT_FILE) if root is not None else None


def history_path(store):
    root = _root(store)
    return (root / HISTORY_FILE) if root is not None else None


# ---------------------------------------------------------------- readers
def session_ids(store):
    root = _root(store)
    base = (root / "sessions") if root is not None else None
    if base is None or not base.exists():
        return []
    try:
        return sorted(child.name for child in base.iterdir()
                      if child.is_dir())
    except Exception:
        return []


def entries(store):
    """Every visible memory entry, newest first, tagged with its session."""
    rows = []
    root = _root(store)
    base = (root / "sessions") if root is not None else None
    if base is None or not base.exists():
        return rows
    try:
        sessions = sorted(child for child in base.iterdir() if child.is_dir())
    except Exception:
        return rows
    for directory in sessions:
        doc = _read_json(directory / "memory.json", {})
        for entry in doc.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            if entry.get("deleted") or entry.get("archived"):
                continue
            item = dict(entry)
            item["_session"] = directory.name
            rows.append(item)
    rows.sort(key=lambda row: _num(row.get("ts"), 0.0), reverse=True)
    return rows


def episodes(store, limit=DEFAULT_EPISODES):
    """Newest N memory entries: the per-turn record that carries text."""
    count = max(1, int(_num(limit, DEFAULT_EPISODES)))
    return entries(store)[:count]


def traces(store):
    rows = []
    for session_id in session_ids(store):
        try:
            rows.extend(_pipeline.trace_read(store, session_id,
                                             limit=_pipeline.TRACE_KEEP))
        except Exception:
            continue
    rows.sort(key=lambda row: _num(row.get("ts"), 0.0))
    return rows


def relationship(store):
    try:
        return _pipeline.relationship_read(store)["relationship"]
    except Exception:
        return {"trust": 0.5, "closeness": 0.5, "conflict": 0.0,
                "attachment_style": "secure", "bids": {},
                "days_known": 0}


def read_history(store):
    path = history_path(store)
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
        return []
    rows.sort(key=lambda row: _num(row.get("ts"), 0.0))
    return rows


def _record_history(store, now, current):
    path = history_path(store)
    if path is None:
        return False
    rows = read_history(store)
    day = time.strftime("%Y-%m-%d", time.gmtime(_num(now, time.time())))
    last = rows[-1] if rows else {}
    last_day = time.strftime("%Y-%m-%d", time.gmtime(_num(last.get("ts"), 0)))
    if last and last_day == day:
        return False
    rows.append({"ts": round(_num(now, time.time()), 3),
                 "trust": round(_num(current.get("trust"), 0.5), 4),
                 "closeness": round(_num(current.get("closeness"), 0.5), 4)})
    rows = rows[-HISTORY_KEEP:]
    try:
        _atomic_write_text(path, "\n".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":"))
            for row in rows) + "\n")
        return True
    except Exception:
        return False


def _atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _session_affect(store, session_id):
    directory = _pipeline.session_dir(store, session_id)
    if directory is None:
        return None
    state = _read_json(directory / "state.json", {})
    core = state.get("core") if isinstance(state.get("core"), dict) else {}
    for source in (state, core):
        valence = source.get("v", source.get("valence"))
        if valence is None:
            continue
        arousal = source.get("a", source.get("arousal", 0.5))
        return (max(-1.0, min(1.0, _num(valence, 0.0))),
                max(0.0, min(1.0, _num(arousal, 0.5))))
    return None


def _entry_affect(entry):
    affect = entry.get("affect") if isinstance(entry, dict) else None
    if not isinstance(affect, dict):
        return None
    valence = affect.get("valence", affect.get("v"))
    arousal = affect.get("arousal", affect.get("a", 0.5))
    if valence is None:
        return None
    try:
        return (max(-1.0, min(1.0, float(valence))),
                max(0.0, min(1.0, float(arousal))))
    except Exception:
        return None


def _cosine(left, right):
    lv, la = left
    rv, ra = right
    ln = math.sqrt(lv * lv + la * la)
    rn = math.sqrt(rv * rv + ra * ra)
    if not ln or not rn:
        return 0.0
    return (lv * rv + la * ra) / (ln * rn)


def _flags(store, flags=None, env=None):
    data = flags if isinstance(flags, dict) else {}
    environ = env if hasattr(env, "get") else {}
    root = _root(store)
    file_flags = {}
    if root is not None:
        # DSH keeps flags.json in the data dir above the memory store, so the
        # store root is checked first and its parent second.
        for path in (root / "flags.json", root.parent / "flags.json"):
            if path.exists():
                file_flags = _read_json(path, {})
                break
    out = {}
    for key in LEARNING_FLAGS:
        if key in data:
            out[key] = {"enabled": bool(data[key]), "source": "flags"}
        elif key in file_flags:
            out[key] = {"enabled": bool(file_flags[key]), "source": "flags.json"}
        elif ENV_FLAGS.get(key) and ENV_FLAGS[key] in environ:
            out[key] = {"enabled": _truthy(environ.get(ENV_FLAGS[key])),
                        "source": "env"}
        else:
            out[key] = {"enabled": False, "source": "default"}
    return out


# ---------------------------------------------------------------- metrics
def _change_7d(store, now, current):
    rows = read_history(store)
    if not rows:
        return {"trust": 0.0, "closeness": 0.0}, "no_history", 0.0
    target = _num(now, time.time()) - WEEK_SECONDS
    older = [row for row in rows if _num(row.get("ts"), 0.0) <= target]
    if older:
        base = older[-1]
        basis = "seven_day"
    else:
        base = rows[0]
        basis = "oldest_sample"
    return (
        {"trust": round(_num(current.get("trust"), 0.5)
                        - _num(base.get("trust"), 0.5), 4),
         "closeness": round(_num(current.get("closeness"), 0.5)
                            - _num(base.get("closeness"), 0.5), 4)},
        basis,
        round(_num(base.get("ts"), 0.0), 3),
    )


def metrics(store, now=None, flags=None, env=None):
    """Observable growth metrics; never writes anything."""
    stamp = _num(now, time.time())
    rows = entries(store)
    total = len(rows)
    week = stamp - WEEK_SECONDS
    added = 0
    importance = []
    with_affect = 0
    for entry in rows:
        if _num(entry.get("ts"), 0.0) >= week:
            added += 1
        importance.append(_num(entry.get("importance"), 0.0))
        if _entry_affect(entry) is not None:
            with_affect += 1
    avg_importance = (round(sum(importance) / total, 4) if total else 0.0)

    by_id = {str(entry.get("id") or ""): entry for entry in rows}
    trace_rows = traces(store)
    hits_total = 0
    mood_match_hits = 0
    scores = []
    for row in trace_rows:
        memory = row.get("memory") if isinstance(row.get("memory"), dict) else {}
        ids = memory.get("recalled_ids")
        ids = [str(item) for item in ids] if isinstance(ids, list) else []
        hits_total += len(ids)
        top = memory.get("top_score")
        if top is None:
            listed = memory.get("scores")
            top = listed[0] if isinstance(listed, list) and listed else None
        if top is not None:
            scores.append(_num(top, 0.0))
        if not ids:
            continue
        current = _session_affect(store, row.get("session_id"))
        if current is None:
            continue
        for entry_id in ids:
            stored = _entry_affect(by_id.get(entry_id))
            if stored is not None and _cosine(stored, current) >= 0.3:
                mood_match_hits += 1
                break

    rel = relationship(store)
    change, basis, base_ts = _change_7d(store, stamp, rel)

    intents = Counter()
    for row in trace_rows:
        intent = row.get("intent") if isinstance(row.get("intent"), dict) else {}
        kind = str(intent.get("kind") or "").strip()
        if kind:
            intents[kind] += 1
    narrative = [{"kind": kind, "count": count}
                 for kind, count in intents.most_common(SECTION_TOP)]

    return {
        "memory": {
            "total": total,
            "added_this_week": added,
            "avg_importance": avg_importance,
            "with_affect": with_affect,
            "with_affect_ratio": (round(with_affect / total, 4)
                                  if total else 0.0),
        },
        "recall": {
            "hits_total": hits_total,
            "mood_match_hits": mood_match_hits,
            "avg_top_score": (round(sum(scores) / len(scores), 4)
                              if scores else None),
            "score_source": "trace" if scores else "unavailable",
            "traces": len(trace_rows),
        },
        "relation": {
            "trust": round(_num(rel.get("trust"), 0.5), 4),
            "closeness": round(_num(rel.get("closeness"), 0.5), 4),
            "change_7d": change,
            "change_basis": basis,
            "change_base_ts": base_ts,
            "days_known": int(_num(rel.get("days_known"), 0)),
            "attachment_style": str(rel.get("attachment_style") or ""),
        },
        "narrative": {"top_intents": narrative,
                      "traces": len(trace_rows)},
        "flags": _flags(store, flags=flags, env=env),
    }


# ---------------------------------------------------------------- dry-run
def _topics(text):
    if _drift is not None:
        try:
            return _drift.topics(text)
        except Exception:
            pass
    return []


def candidates(store, limit=DEFAULT_EPISODES):
    """Candidate facts from the newest N episodes; never mutates anything."""
    rows = episodes(store, limit)
    counts = Counter()
    evidence = {}
    for entry in rows:
        for topic in dict.fromkeys(_topics(str(entry.get("text") or ""))):
            counts[topic] += 1
            evidence.setdefault(topic, [])
            entry_id = str(entry.get("id") or "")
            if entry_id and entry_id not in evidence[topic]:
                evidence[topic].append(entry_id)
    found = []
    for topic, count in counts.most_common():
        if count < TOPIC_MIN_REPEAT:
            continue
        dimension = None
        if _drift is not None:
            dimension = _drift.dimension_of(topic)
        found.append({
            "kind": "repeated_topic",
            "topic": topic,
            "count": int(count),
            "dimension": dimension,
            "confidence": round(min(0.95, 0.4 + 0.1 * count), 3),
            "evidence": evidence.get(topic, [])[:5],
        })
    # a theme that maps onto a value dimension is the useful candidate, so
    # unmapped bigram noise sorts after it on a tie
    found.sort(key=lambda item: (-item["count"], item["dimension"] is None))
    found = found[:MAX_CANDIDATES]

    rel = relationship(store)
    trust = _num(rel.get("trust"), 0.5)
    closeness = _num(rel.get("closeness"), 0.5)
    conflict = _num(rel.get("conflict"), 0.0)
    if trust >= RELATION_STABLE_MIN and closeness >= RELATION_STABLE_MIN:
        days = int(_num(rel.get("days_known"), 0))
        style = str(rel.get("attachment_style") or "secure")
        fact = ("关系稳定：信任 %.2f、亲近 %.2f（%s）" % (trust, closeness, style))
        if days > 0:
            fact += "，已相处 %d 天" % days
        found.append({
            "kind": "stable_relation",
            "fact": fact,
            "trust": round(trust, 4),
            "closeness": round(closeness, 4),
            "conflict": round(conflict, 4),
            "days_known": days,
            "attachment_style": style,
            "confidence": round(min(0.95, (trust + closeness) / 2.0), 3),
        })
    return found


def consolidate(store, limit=DEFAULT_EPISODES, now=None, enabled=None,
                flags=None, env=None, write_report=True):
    """Dry-run consolidation: candidates + report file, memory untouched."""
    stamp = _num(now, time.time())
    on = (bool(enabled) if enabled is not None
          else _enabled(flags=flags, env=env))
    if not on:
        return {"ok": False, "reason": "disabled", "dry_run": True,
                "report": None, "path": ""}
    scanned = episodes(store, limit)
    found = candidates(store, limit)
    counts = Counter(item.get("kind") for item in found)
    report = {
        "schema": "bc.consolidate_report.v1",
        "generated_ts": round(stamp, 3),
        "dry_run": True,
        "memory_written": False,
        "episodes": {"source": "memory_entries", "scanned": len(scanned),
                     "limit": max(1, int(_num(limit, DEFAULT_EPISODES)))},
        "candidates": found,
        "counts": {kind: counts.get(kind, 0)
                   for kind in ("repeated_topic", "stable_relation")},
        "flags": _flags(store, flags=flags, env=env),
    }
    path = report_path(store)
    written = False
    if write_report and path is not None:
        try:
            _atomic_write(path, report)
            written = True
            _record_history(store, stamp, relationship(store))
        except Exception:
            written = False
    return {"ok": True, "reason": "dry_run", "dry_run": True,
            "report": report, "path": str(path or ""),
            "written": written}
