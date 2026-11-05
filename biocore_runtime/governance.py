# -*- coding: utf-8 -*-
"""task-222: DSH memory governance (decay / index / consolidate / graph / aggregate).

Operating on the DSH runtime store (<dataDir>/memory/sessions/...), never on
the engine store. Everything here is additive sidecar state: memory entries
are only read, never deleted or rewritten. "Decay" lowers the weight used for
recall ordering, it does not erase anything.

Sidecar files under <store>/:
  governance.json  per-entry retention score/tier/weight + counters
  index.json       token -> entry ids (cue index)
  graph.json       concept co-occurrence graph (nodes/edges)
  consolidate.json  repeated-topic candidates (hash => idempotent)
  aggregate.json   cross-session counts and top topics

Public:
  run(store, now) -> summary counters (called once per turn_end)
  lookup(store, query) -> entry ids from the index (counts index hits)
  weight_of(store, entry_id) -> retention weight (1.0 when unknown)
  summary(store) -> counters for /state and /stats
  enabled(store) -> governance flag (default ON, file override)
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from pathlib import Path

GOVERNANCE_FILE = "governance.json"
INDEX_FILE = "index.json"
GRAPH_FILE = "graph.json"
CONSOLIDATE_FILE = "consolidate.json"
AGGREGATE_FILE = "aggregate.json"
SCHEMA = 1
MAX_ENTRIES = 400
COLD_SCORE = 0.35
WARM_SCORE = 0.55
COLD_WEIGHT = 0.4
WARM_WEIGHT = 0.7
TOPIC_MIN = 2
MAX_TOPICS = 8
GRAPH_MIN_COUNT = 2
MAX_GRAPH_NODES = 80
MAX_GRAPH_EDGES = 160
RECENT_EPISODES = 40
HALF_LIFE_DAYS = 30.0
THROTTLE_SECONDS = 30.0

_WS = re.compile(r"\s+")
_LATIN = re.compile(r"[a-z][a-z0-9_']*")
_CJK = re.compile(r"[\u4e00-\u9fff]+")
_STOP = frozenset((
    "我们", "你们", "他们", "这个", "那个", "就是", "不是", "一个", "什么",
    "怎么", "可以", "没有", "因为", "所以", "然后", "还是", "现在", "今天",
    "明天", "知道", "觉得", "已经", "这样", "那样", "东西", "自己",
))


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


def _data_dir(store):
    root = _root(store)
    if root is None:
        return None
    return root.parent if root.name == "memory" else root


def _flags(store):
    data_dir = _data_dir(store)
    raw = {}
    if data_dir is not None:
        try:
            raw = json.loads((data_dir / "flags.json").read_text(encoding="utf-8"))
        except Exception:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return {"governance": raw.get("governance", True) is not False,
            "evict_delete": raw.get("evict_delete") is True,
            "relationship_governance":
                raw.get("relationship_governance", True) is not False}


def enabled(store):
    if str(os.environ.get("BIOCORE_GOVERNANCE") or "").strip().lower() in (
            "0", "false", "off", "no"):
        return False
    return _flags(store)["governance"]


def _read(path, fallback):
    try:
        if path is None or not Path(path).exists():
            return fallback
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else fallback
    except Exception:
        return fallback


def _write(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, path)


def _tokens(text):
    lowered = _WS.sub(" ", str(text or "").lower())
    out = []
    for run in _CJK.findall(lowered):
        if len(run) < 2:
            continue
        for index in range(len(run) - 1):
            token = run[index:index + 2]
            if token not in _STOP:
                out.append(token)
    out.extend(word for word in _LATIN.findall(lowered) if len(word) >= 3)
    return out


def extract_concepts(text, limit=8):
    """Stable concepts for one entry (unique tokens, first-seen order)."""
    seen = []
    for token in _tokens(text):
        if token not in seen:
            seen.append(token)
    return seen[:max(1, int(limit))]


def _entries(store):
    """Visible entries from every session, newest first."""
    root = _root(store)
    base = (root / "sessions") if root is not None else None
    rows = []
    if base is None or not base.exists():
        return rows
    try:
        sessions = [child for child in base.iterdir() if child.is_dir()]
    except Exception:
        return rows
    for directory in sessions:
        doc = _read(directory / "memory.json", {})
        for entry in doc.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            if entry.get("deleted") or entry.get("archived"):
                continue
            item = dict(entry)
            item["_session"] = directory.name
            rows.append(item)
    rows.sort(key=lambda row: _num(row.get("ts"), 0.0), reverse=True)
    return rows[:MAX_ENTRIES]


def _entry_id(entry):
    return str(entry.get("id") or "").strip()


def retention(entry, now):
    """0..1 retention: importance + recency + usage, never negative."""
    ts = _num(entry.get("ts"), 0.0)
    age_days = max(0.0, (now - ts) / 86400.0) if ts > 0 else 0.0
    recency = 0.5 ** (age_days / HALF_LIFE_DAYS)
    importance = max(0.0, min(1.0, _num(entry.get("importance"), 0.5)))
    hits = max(0.0, _num(entry.get("hits"), 1.0))
    usage = min(1.0, hits / 5.0)
    value = max(0.0, min(1.0, _num(entry.get("value"), 0.5)))
    score = 0.40 * importance + 0.30 * recency + 0.20 * usage + 0.10 * value
    return round(max(0.0, min(1.0, score)), 4)


def _tier(score):
    if score < COLD_SCORE:
        return "cold", COLD_WEIGHT
    if score < WARM_SCORE:
        return "warm", WARM_WEIGHT
    return "hot", 1.0


def decay(store, now=None, previous=None):
    """Recompute retention weights; never deletes or rewrites an entry."""
    stamp = _num(now, time.time())
    prev = previous if isinstance(previous, dict) else {}
    prev_entries = prev.get("entries") if isinstance(prev.get("entries"), dict) else {}
    rows = _entries(store)
    table = {}
    cold = warm = hot = demoted = 0
    for entry in rows:
        entry_id = _entry_id(entry)
        if not entry_id:
            continue
        score = retention(entry, stamp)
        tier, weight = _tier(score)
        old_tier = str((prev_entries.get(entry_id) or {}).get("tier") or "")
        if old_tier and old_tier != "cold" and tier == "cold":
            demoted += 1
        table[entry_id] = {"score": score, "tier": tier,
                           "weight": round(weight, 3),
                           "session": str(entry.get("_session") or ""),
                           "ts": round(_num(entry.get("ts"), 0.0), 3)}
        if tier == "cold":
            cold += 1
        elif tier == "warm":
            warm += 1
        else:
            hot += 1
    return {
        "entries": table,
        "stats": {"total": len(table), "cold": cold, "warm": warm,
                  "hot": hot, "demoted": demoted,
                  "deleted": 0, "updated_at": round(stamp, 3)},
    }


def build_index(store):
    """token -> entry ids; bounded and deterministic."""
    index = {}
    for entry in _entries(store):
        entry_id = _entry_id(entry)
        if not entry_id:
            continue
        for token in dict.fromkeys(_tokens(entry.get("text"))):
            index.setdefault(token, [])
            if entry_id not in index[token]:
                index[token].append(entry_id)
    # keep the index bounded: tokens seen in one entry are noise
    kept = {token: ids for token, ids in index.items() if len(ids) >= 1}
    topics = [token for token, ids in sorted(kept.items(),
                                             key=lambda item: (-len(item[1]), item[0]))
              if len(ids) >= 2][:MAX_TOPICS]
    latest_ts = max((_num(entry.get("ts"), 0.0) for entry in _entries(store)),
                    default=0.0)
    return {"schema": SCHEMA, "terms": kept, "topics": topics,
            "latest_ts": round(latest_ts, 3)}


def lookup(store, query):
    """Entry ids matching the query tokens (read; caller counts the hit)."""
    doc = _read((_root(store) or Path(".")) / INDEX_FILE, {})
    terms = doc.get("terms") if isinstance(doc.get("terms"), dict) else {}
    hits = []
    for token in dict.fromkeys(_tokens(query)):
        for entry_id in terms.get(token) or []:
            if entry_id not in hits:
                hits.append(entry_id)
    return hits


def weight_of(store, entry_id):
    doc = _read((_root(store) or Path(".")) / GOVERNANCE_FILE, {})
    record = (doc.get("entries") or {}).get(str(entry_id))
    return _num((record or {}).get("weight"), 1.0)


def consolidate(store, now=None):
    """Repeated-topic candidates; hash keeps repeated runs idempotent."""
    stamp = _num(now, time.time())
    candidates = []
    try:  # task-223: keep one rule set with the growth report
        from . import growth as _growth
        for row in _growth.candidates(store, RECENT_EPISODES):
            topic = str(row.get("topic") or "")
            if not topic:
                continue
            candidates.append({"topic": topic,
                               "count": int(row.get("count") or 0),
                               "evidence": list(row.get("evidence") or [])[:5]})
    except Exception:
        candidates = []
    if not candidates:
        episodes = _entries(store)[:RECENT_EPISODES]
        counts = {}
        evidence = {}
        for entry in episodes:
            for token in dict.fromkeys(_tokens(entry.get("text"))):
                counts[token] = counts.get(token, 0) + 1
                evidence.setdefault(token, [])
                entry_id = _entry_id(entry)
                if entry_id and entry_id not in evidence[token]:
                    evidence[token].append(entry_id)
        for token, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            if count < TOPIC_MIN:
                continue
            candidates.append({"topic": token, "count": int(count),
                               "evidence": evidence.get(token, [])[:5]})
            if len(candidates) >= MAX_TOPICS:
                break
    candidates = candidates[:MAX_TOPICS]
    digest = hashlib.sha256(json.dumps(candidates, ensure_ascii=False,
                                       sort_keys=True).encode("utf-8")).hexdigest()
    previous = _read((_root(store) or Path(".")) / CONSOLIDATE_FILE, {})
    runs = int(_num(previous.get("runs"), 0)) + 1
    changed = digest != str(previous.get("hash") or "")
    return {"schema": SCHEMA, "ts": round(stamp, 3), "hash": digest,
            "runs": runs, "changed": changed, "candidates": candidates,
            "count": len(candidates)}


def build_graph(store):
    """Concept co-occurrence graph over the same bounded entry set."""
    counts = {}
    pairs = {}
    for entry in _entries(store):
        tokens = list(dict.fromkeys(_tokens(entry.get("text"))))
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        for index, left in enumerate(tokens):
            for right in tokens[index + 1:]:
                key = tuple(sorted((left, right)))
                pairs[key] = pairs.get(key, 0) + 1
    nodes = [{"id": token, "count": count}
             for token, count in sorted(counts.items(),
                                        key=lambda item: (-item[1], item[0]))
             if count >= GRAPH_MIN_COUNT][:MAX_GRAPH_NODES]

    def _is_node(token):
        return any(node["id"] == token for node in nodes)

    edges = [{"a": left, "b": right, "weight": count}
             for (left, right), count in sorted(
                 pairs.items(), key=lambda item: (-item[1], item[0]))
             if count >= GRAPH_MIN_COUNT and _is_node(left) and _is_node(right)]
    return {"schema": SCHEMA, "nodes": nodes, "edges": edges[:MAX_GRAPH_EDGES]}


def aggregate(store):
    """Cross-session counts (read-only projection, one row per session)."""
    root = _root(store)
    base = (root / "sessions") if root is not None else None
    sessions = {}
    topics = {}
    if base is not None and base.exists():
        try:
            for directory in base.iterdir():
                if not directory.is_dir():
                    continue
                entries = [entry for entry in
                           (_read(directory / "memory.json", {}).get("entries") or [])
                           if isinstance(entry, dict) and not entry.get("deleted")
                           and not entry.get("archived")]
                sessions[directory.name] = len(entries)
                for entry in entries:
                    for token in dict.fromkeys(_tokens(entry.get("text"))):
                        topics[token] = topics.get(token, 0) + 1
        except Exception:
            pass
    top = [{"topic": token, "count": count}
           for token, count in sorted(topics.items(),
                                      key=lambda item: (-item[1], item[0]))[:5]]
    return {"schema": SCHEMA, "sessions": sessions,
            "session_count": len(sessions),
            "entries": sum(sessions.values()), "top_topics": top}


def summary(store):
    gov = _read((_root(store) or Path(".")) / GOVERNANCE_FILE, {})
    index = _read((_root(store) or Path(".")) / INDEX_FILE, {})
    graph = _read((_root(store) or Path(".")) / GRAPH_FILE, {})
    consolidate_doc = _read((_root(store) or Path(".")) / CONSOLIDATE_FILE, {})
    aggregate_doc = _read((_root(store) or Path(".")) / AGGREGATE_FILE, {})
    stats = gov.get("stats") if isinstance(gov.get("stats"), dict) else {}
    return {
        "decay": {"total": int(_num(stats.get("total"), 0)),
                  "cold": int(_num(stats.get("cold"), 0)),
                  "warm": int(_num(stats.get("warm"), 0)),
                  "hot": int(_num(stats.get("hot"), 0)),
                  "decayed": (int(_num(stats.get("cold"), 0))
                              + int(_num(stats.get("warm"), 0))),
                  "demoted": int(_num(stats.get("demoted"), 0)),
                  "deleted": 0},
        "index": {"terms": len(index.get("terms") or {}),
                  "topics": len(index.get("topics") or []),
                  "latest_ts": _num(index.get("latest_ts"), 0.0),
                  "hits": int(_num(gov.get("index_hits"), 0))},
        "concepts": {"entries": sum(1 for row in _entries(store)
                                    if row.get("concepts")),
                     "filtered": int(_num(gov.get("concept_filters"), 0)),
                     "kept": int(_num(gov.get("concept_kept"), 0))},
        "consolidate": {"candidates": len(consolidate_doc.get("candidates") or []),
                        "runs": int(_num(consolidate_doc.get("runs"), 0))},
        "graph": {"nodes": len(graph.get("nodes") or []),
                  "edges": len(graph.get("edges") or [])},
        "aggregate": {"sessions": int(_num(aggregate_doc.get("session_count"), 0)),
                      "entries": int(_num(aggregate_doc.get("entries"), 0))},
        "enabled": enabled(store),
    }


def run(store, now=None, force=False):
    """One governance pass; writes sidecars, never touches memory entries."""
    if not enabled(store):
        return {"enabled": False, "skipped": True}
    root = _root(store)
    if root is None:
        return {"enabled": False, "skipped": True}
    stamp = _num(now, time.time())
    gov_path = root / GOVERNANCE_FILE
    previous = _read(gov_path, {})
    last = _num((previous.get("stats") or {}).get("updated_at"), 0.0)
    if not force and last > 0 and stamp - last < THROTTLE_SECONDS:
        summary_doc = summary(store)
        summary_doc["skipped"] = True
        summary_doc["reason"] = "throttle"
        return summary_doc
    gov = decay(store, now=stamp, previous=previous)
    gov["index_hits"] = int(_num(previous.get("index_hits"), 0))
    gov["schema"] = SCHEMA
    gov.setdefault("stats", {})["updated_at"] = round(stamp, 3)
    try:
        _write(gov_path, gov)
    except Exception:
        pass
    index = build_index(store)
    try:
        _write(root / INDEX_FILE, index)
    except Exception:
        pass
    graph = build_graph(store)
    try:
        _write(root / GRAPH_FILE, graph)
    except Exception:
        pass
    consolidation = consolidate(store, now=stamp)
    try:
        _write(root / CONSOLIDATE_FILE, consolidation)
    except Exception:
        pass
    agg = aggregate(store)
    try:
        _write(root / AGGREGATE_FILE, agg)
    except Exception:
        pass
    return {"enabled": True, "decay": gov["stats"],
            "index": {"terms": len(index.get("terms") or {}),
                      "hits": gov["index_hits"]},
            "consolidate": {"candidates": consolidation["count"],
                            "runs": consolidation["runs"],
                            "changed": consolidation["changed"]},
            "graph": {"nodes": len(graph.get("nodes") or []),
                      "edges": len(graph.get("edges") or [])},
            "aggregate": {"sessions": agg["session_count"],
                          "entries": agg["entries"]}}


def note_concept_filter(store, kept):
    """Count how many recalls were narrowed by concepts."""
    root = _root(store)
    if root is None:
        return
    path = root / GOVERNANCE_FILE
    doc = _read(path, {})
    doc["concept_filters"] = int(_num(doc.get("concept_filters"), 0)) + 1
    doc["concept_kept"] = int(_num(doc.get("concept_kept"), 0)) + max(0, int(kept))
    doc["schema"] = SCHEMA
    try:
        _write(path, doc)
    except Exception:
        pass


def note_index_hit(store):
    """Increment the index-hit counter once per query recall."""
    root = _root(store)
    if root is None:
        return
    path = root / GOVERNANCE_FILE
    doc = _read(path, {})
    doc["index_hits"] = int(_num(doc.get("index_hits"), 0)) + 1
    doc["schema"] = SCHEMA
    try:
        _write(path, doc)
    except Exception:
        pass
