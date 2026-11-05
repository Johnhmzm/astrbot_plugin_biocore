# -*- coding: utf-8 -*-
"""task-62: retrieval enhancement -- normalized channels, chunks, shards,
predictive exploration.

Pipeline-level retriever used after the memory engine returns candidates:
  bm25   lexical term overlap with idf-like weighting
  vector hashed bag-of-tokens cosine
  graph  query-entity co-occurrence neighbours
  time   recency decay
Each channel is min-max normalized independently, then fused. Sentences are
chunked (indexed per entry) and the best chunk provides the returned snippet.
Entries are assigned to physical shards (session or month) with a per-shard
cap and rolling suffix. Recent queries form a topic "expectation": entries far
from it get a small exploration boost, highly expected ones a redundancy
penalty.

Default on; the caller passes enabled=False to keep the legacy order.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path

CHANNELS = ("bm25", "vector", "graph", "time")
SHARD_LIMIT = 200
VECTOR_DIM = 64
EXPECTATION_TURNS = 5
EXPLORE_ALPHA = 0.6
DEBUG_FILE = "recall_debug.json"
TOPIC_FILE = "topic_history.json"
SHARD_FILE = "retrieval/shards.json"
CHUNK_FILE = "retrieval/chunks.json"
SCHEMA = 1

_WORD = re.compile(r"[a-z0-9_]{2,}")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_SENT = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")


def _root(store):
    if isinstance(store, dict):
        raw = store.get("root") or store.get("store") or store.get("path")
    else:
        raw = store
    text = str(raw or "").strip()
    return Path(text) if text else None


def _data_dir(store):
    root = _root(store)
    return (root.parent if root.name == "memory" else root) if root else None


def _read(path):
    try:
        if path is None or not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write(path, doc):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(path)
        return True
    except Exception:
        return False


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return default
    return number if number == number else default


def tokens(text):
    lowered = str(text or "").lower()
    out = _WORD.findall(lowered)
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        out.extend(run[i:i + 2] for i in range(len(run) - 1))
        if len(run) <= 2:
            out.append(run)
    return out


def vector(text, dim=VECTOR_DIM):
    counts = {}
    for token in tokens(text):
        bucket = int(hashlib.sha1(token.encode("utf-8")).hexdigest()[:8], 16) % dim
        counts[bucket] = counts.get(bucket, 0) + 1
    norm = math.sqrt(sum(value * value for value in counts.values())) or 1.0
    return {bucket: value / norm for bucket, value in counts.items()}


def cosine(left, right):
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(bucket, 0.0) for bucket, value in left.items())


def normalize(scores):
    """Min-max each channel independently; flat all-equal -> 1.0 or 0.0."""
    values = [float(value) for value in scores]
    if not values:
        return []
    low, high = min(values), max(values)
    if high - low <= 1e-12:
        return [1.0 if high > 0 else 0.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def split_chunks(text, max_chars=120):
    pieces = [piece.strip() for piece in _SENT.findall(str(text or ""))
              if piece.strip()]
    chunks = []
    for piece in pieces:
        if len(piece) <= max_chars:
            chunks.append(piece)
            continue
        for start in range(0, len(piece), max_chars):
            part = piece[start:start + max_chars].strip()
            if part:
                chunks.append(part)
    return chunks or ([str(text or "").strip()] if str(text or "").strip() else [])


def chunk_index(store):
    return _read((_data_dir(store) or Path(".")) / CHUNK_FILE)


def build_chunks(store, entries):
    """Persist a sentence index per entry; returns id -> chunks."""
    doc = chunk_index(store)
    mapping = doc.get("entries") if isinstance(doc.get("entries"), dict) else {}
    for entry in entries or []:
        entry_id = str((entry or {}).get("id") or "")
        text = str((entry or {}).get("text") or "")
        if not entry_id or not text:
            continue
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
        current = mapping.get(entry_id)
        if isinstance(current, dict) and current.get("hash") == digest:
            continue
        mapping[entry_id] = {"hash": digest, "chunks": split_chunks(text)}
    doc.update({"schema": SCHEMA, "entries": mapping,
                "updated_at": round(time.time(), 3)})
    _write((_data_dir(store) or Path(".")) / CHUNK_FILE, doc)
    return {key: value.get("chunks") or [] for key, value in mapping.items()}


def _best_chunk(chunks, query_tokens):
    best = ""
    best_hits = -1
    for chunk in chunks:
        lowered = set(tokens(chunk))
        hits = len(lowered & set(query_tokens))
        if hits > best_hits:
            best, best_hits = chunk, hits
    return best, max(0, best_hits)


def _shard_base(entry, session_id):
    session = str(session_id or entry.get("session_id") or "")
    if session:
        return "s-" + re.sub(r"[^A-Za-z0-9_-]", "", session)[:24]
    ts = _num(entry.get("ts"), 0.0)
    return time.strftime("%Y-%m", time.localtime(ts or time.time()))


def assign_shards(store, entries, session_id="", limit=SHARD_LIMIT):
    """Session/month shard with rolling suffix when a shard exceeds the cap."""
    doc = _read((_data_dir(store) or Path(".")) / SHARD_FILE)
    by_id = doc.get("by_id") if isinstance(doc.get("by_id"), dict) else {}
    for entry in entries or []:
        entry_id = str((entry or {}).get("id") or "")
        if not entry_id:
            continue
        base = _shard_base(entry, session_id)
        index = sum(1 for value in by_id.values()
                    if str((value or {}).get("base")) == base)
        shard = base if index < limit else base + "-r%d" % (index // limit)
        by_id[entry_id] = {"base": base, "shard": shard,
                           "ts": round(time.time(), 3)}
    doc.update({"schema": SCHEMA, "by_id": by_id,
                "updated_at": round(time.time(), 3)})
    data_dir = _data_dir(store) or Path(".")
    _write(data_dir / SHARD_FILE, doc)
    # physical shard files: one JSON per shard with its entry ids
    grouped = {}
    for entry_id, value in by_id.items():
        grouped.setdefault(str(value.get("shard") or ""), []).append(entry_id)
    for name, ids in grouped.items():
        _write(data_dir / "retrieval" / "shards" / (name + ".json"),
               {"schema": SCHEMA, "shard": name, "ids": ids[-200:],
                "updated_at": round(time.time(), 3)})
    return {key: value.get("shard") for key, value in by_id.items()}


def record_query(store, query, now=None):
    path = (_data_dir(store) or Path(".")) / TOPIC_FILE
    doc = _read(path)
    rows = [row for row in (doc.get("turns") or []) if isinstance(row, dict)]
    rows.append({"ts": round(float(now or time.time()), 3),
                 "vector": vector(query)})
    doc.update({"schema": SCHEMA, "turns": rows[-20:]})
    _write(path, doc)
    return len(rows[-20:])


def expectation(store):
    doc = _read((_data_dir(store) or Path(".")) / TOPIC_FILE)
    rows = [row for row in (doc.get("turns") or [])
            if isinstance(row.get("vector"), dict)][-EXPECTATION_TURNS:]
    if not rows:
        return {}
    total = {}
    for row in rows:
        for bucket, value in row["vector"].items():
            try:
                bucket = int(bucket)
            except Exception:
                continue
            total[bucket] = total.get(bucket, 0.0) + _num(value)
    norm = math.sqrt(sum(value * value for value in total.values())) or 1.0
    return {bucket: value / norm for bucket, value in total.items()}


def _bm25_score(query_tokens, text, corpus_size, df):
    body = tokens(text)
    if not body:
        return 0.0
    score = 0.0
    for token in set(query_tokens):
        tf = body.count(token)
        if not tf:
            continue
        idf = math.log(1.0 + (corpus_size + 1) / (df.get(token, 1) + 0.5))
        score += idf * tf / (tf + 1.2)
    return score


def _graph_score(query_tokens, entry, neighbours):
    body = set(tokens(entry.get("text")))
    score = 0.0
    for token in query_tokens:
        for other in neighbours.get(token, ()):
            if other != entry.get("id") and other in neighbours.get(
                    "__entry_text__", {}):
                pass
    # co-occurrence: count query-token neighbours that also contain entry tokens
    for token in query_tokens:
        for other_id in neighbours.get(token, ()):
            if other_id == entry.get("id"):
                continue
            other_text = neighbours.get("__text__", {}).get(other_id, "")
            if set(tokens(other_text)) & body:
                score += 1.0
    return score


def rank(store, session_id, query, entries, now=None, limit=24,
         enabled=True, alpha=EXPLORE_ALPHA):
    """Return ranked rows with channel scores, chunk snippet, shard, reason."""
    rows = [dict(entry) for entry in (entries or []) if isinstance(entry, dict)]
    stamp = float(now or time.time())
    query_tokens = tokens(query)
    if not enabled or not rows:
        return [{"entry": row, "score": float(row.get("score") or 0.0),
                 "reason": "fallback", "channels": {}, "chunk": "",
                 "shard": "", "chunk_hits": 0} for row in rows][:limit]
    chunks_map = build_chunks(store, rows)
    shard_map = assign_shards(store, rows, session_id=session_id)
    corpus = len(rows)
    df = {}
    for row in rows:
        for token in set(tokens(row.get("text"))):
            df[token] = df.get(token, 0) + 1
    neighbours = {"__text__": {str(row.get("id")): str(row.get("text")) for row in rows}}
    for row in rows:
        for token in set(tokens(row.get("text"))):
            neighbours.setdefault(token, []).append(str(row.get("id")))
    raw = {channel: [] for channel in CHANNELS}
    for row in rows:
        text = str(row.get("text") or "")
        raw["bm25"].append(_bm25_score(query_tokens, text, corpus, df))
        raw["vector"].append(cosine(vector(query), vector(text)))
        raw["graph"].append(_graph_score(query_tokens, row, neighbours))
        age_hours = max(0.0, (stamp - _num(row.get("ts"), stamp)) / 3600.0)
        raw["time"].append(math.exp(-age_hours / (24.0 * 30.0)))
    norm = {channel: normalize(values) for channel, values in raw.items()}
    weights = {"bm25": 0.4, "vector": 0.3, "graph": 0.2, "time": 0.1}
    expected = expectation(store)
    scored = []
    for index, row in enumerate(rows):
        channels = {channel: round(norm[channel][index], 4)
                    for channel in CHANNELS}
        base = sum(weights[channel] * channels[channel] for channel in CHANNELS)
        dev = 1.0 - cosine(vector(row.get("text")), expected) if expected else 0.5
        expected_weight = max(0.4, min(1.6, 1.0 + alpha * (dev - 0.5)))
        chunk, hits = _best_chunk(chunks_map.get(str(row.get("id")), []),
                                  query_tokens)
        scored.append({
            "entry": row,
            "score": round(base * expected_weight, 4),
            "base": round(base, 4),
            "reason": "fused",
            "channels": channels,
            "expectation_weight": round(expected_weight, 4),
            "chunk": chunk,
            "chunk_hits": hits,
            "shard": shard_map.get(str(row.get("id")), ""),
        })
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


def record_debug(store, query, rows, now=None):
    path = (_data_dir(store) or Path(".")) / DEBUG_FILE
    payload = {
        "schema": SCHEMA,
        "ts": round(float(now or time.time()), 3),
        "query": str(query or "")[:80],
        "rows": [{"id": str(item["entry"].get("id") or ""),
                  "score": item["score"],
                  "channels": item["channels"],
                  "reason": item["reason"],
                  "chunk": str(item["chunk"])[:120],
                  "chunk_hits": item["chunk_hits"],
                  "shard": item["shard"]} for item in rows[:8]],
        "expectation_turns": EXPECTATION_TURNS,
    }
    _write(path, payload)
    return payload


def summary(store):
    doc = _read((_data_dir(store) or Path(".")) / DEBUG_FILE)
    return doc if doc else {"query": "", "rows": [], "ts": 0.0}
