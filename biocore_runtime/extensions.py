# -*- coding: utf-8 -*-
"""task-225 (5b): P0 memory extensions + expression extensions for the core.

Recall side (all optional, failure -> current lexical path):
  entity_graph / entity_resolve / graph_extract / graph_recall  lightweight
      entity graph over memory entries; query entities pull neighbour entries
  layered_memory    resident vs retrieval tiers for the injected rows
  memory_dual       decayed dual score for ordering
  prospective       commitments in <dataDir>/prospective.json + due hints
  reconstruction    reconstruction drift summary (read-only)
  turn_memory       receipt rows for the last recall batch

Expression side (wording constraints only; never changes facts):
  expr_template, prompt_rules, template_expr, topic_control, voice_bank

No LLM calls. All sidecar writes are atomic and bounded.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from biocore_model import (entity_graph as _graph,
                           entity_resolve as _resolve,
                           graph_extract as _extract,
                           layered_memory as _layered,
                           memory_dual as _dual,
                           prospective as _prospective,
                           reconstruction as _reconstruct,
                           turn_memory as _turn_memory,
                           expr_template as _expr_template,
                           prompt_rules as _prompt_rules,
                           template_expr as _template,
                           topic_control as _topic,
                           voice_bank as _voice)

PROSPECTIVE_FILE = "prospective.json"
EXTENSIONS_FILE = "extensions.json"
VOICE_FILE = "voice_bank.json"
SCHEMA = 1


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


def _read(path, fallback):
    try:
        if path is None or not Path(path).exists():
            return fallback
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else fallback
    except Exception:
        return fallback


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


def _tokens(text):
    import re
    lowered = str(text or "").lower()
    out = re.findall(r"[a-z0-9_]{3,}", lowered)
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        out.extend(run[index:index + 2] for index in range(len(run) - 1))
    return out


def _entity_graph(entries):
    """Tiny in-memory graph: every concept token is a node, co-occurrence an edge."""
    graph = _graph.empty_graph()
    names = {}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        tokens = list(dict.fromkeys(_tokens(entry.get("text"))))
        for token in tokens[:12]:
            names.setdefault(token, entry)
        for left in tokens[:8]:
            for right in tokens[:8]:
                if left == right:
                    continue
                try:
                    updated = _graph.upsert_edge(
                        graph, left, right, "co_occurs",
                        ts=float(entry.get("ts") or 0.0), inplace=True)
                    graph = updated[0] if isinstance(updated, tuple) else updated
                except Exception:
                    pass
    for token in names:
        try:
            updated = _graph.upsert_entity(graph, token, "topic", inplace=True)
            graph = updated[0] if isinstance(updated, tuple) else updated
        except Exception:
            pass
    return graph, names


def graph_hits(entries, query, exclude=None):
    """Neighbour entry ids for the query's entities (graph recall)."""
    exclude = set(exclude or [])
    graph, by_name = _entity_graph(entries)
    hits = []
    seen = set()
    try:
        matches = _graph.search(graph, query, limit=6)
    except Exception:
        matches = []
    for item in matches or []:
        name = item.get("name") if isinstance(item, dict) else item
        entry = by_name.get(str(name or ""))
        entry_id = str((entry or {}).get("id") or "")
        if entry_id and entry_id not in exclude and entry_id not in seen:
            seen.add(entry_id)
            hits.append(entry)
    stats = {"entities": len(graph.get("entities") or []),
             "edges": len(graph.get("edges") or []),
             "hits": len(hits)}
    try:
        stats.update(_graph.stats(graph))
    except Exception:
        pass
    return hits, stats


def expand_recall(store, entries, query, picked_ids, now=None):
    """Add graph neighbours / dual-score rows; never raises."""
    stamp = float(now or time.time())
    picked_ids = [str(item) for item in (picked_ids or [])]
    hits, graph_stats = graph_hits(entries, query, exclude=picked_ids)
    extra = []
    for entry in hits[:3]:
        if str(entry.get("id") or "") not in picked_ids:
            extra.append(entry)
    dual_rows = []
    try:
        ordered = _dual.select(entries, stamp, limit=max(4, len(picked_ids) + 2))
        dual_rows = [entry for entry in ordered
                     if str(entry.get("id") or "") not in picked_ids]
    except Exception:
        dual_rows = []
    for entry in dual_rows[:2]:
        if entry not in extra:
            extra.append(entry)
    return {
        "extra": extra,
        "graph": graph_stats,
        "dual": {"rows": len(dual_rows)},
    }


def layered_view(entries, picked_ids):
    try:
        result = _layered.select(entries, recalled_ids=picked_ids) or {}
    except Exception:
        result = {}
    resident = result.get("resident") or []
    retrieval = result.get("retrieval") or []
    return {"selected": len(resident) + len(retrieval),
            "resident": len(resident), "retrieval": len(retrieval)}


def prospective_view(store, now=None):
    data_dir = _data_dir(store)
    path = (data_dir / PROSPECTIVE_FILE) if data_dir else None
    doc = _read(path, {"items": []})
    items = [row for row in (doc.get("items") or []) if isinstance(row, dict)]
    stamp = float(now or time.time())
    due = []
    try:
        due = _prospective.due_now(items, stamp, window_s=3600.0)
    except Exception:
        due = []
    hint = ""
    if due:
        try:
            hint = _prospective.build_hint(due[0], stamp)
        except Exception:
            hint = ""
    return {"pending": len([row for row in items
                            if row.get("status") in ("pending", "overdue")]),
            "due": len(due), "hint": str(hint or "")[:80]}


def add_commitment(store, text, due_ts, now=None, kind="his_event"):
    data_dir = _data_dir(store)
    path = (data_dir / PROSPECTIVE_FILE) if data_dir else None
    if path is None:
        return None
    doc = _read(path, {"items": []})
    items = [row for row in (doc.get("items") or []) if isinstance(row, dict)]
    try:
        record = _prospective.entry(kind, text, due_ts, now=now)
        items, changed = _prospective.add(items, record)
    except Exception:
        return None
    doc.update({"schema": SCHEMA, "items": items[-200:],
                "updated_at": round(float(now or time.time()), 3)})
    _write(path, doc)
    return record if changed else None


def reconstruction_view(entries):
    try:
        result = _reconstruct.conserve(entries) or {}
    except Exception:
        return {"drift": 0.0}
    return {"drift": round(float(result.get("total") or 0.0), 4),
            "scale": result.get("scale", 1.0)}


def turn_memory_view(trace_rows, reply="", now=None):
    try:
        rows = _turn_memory.build(trace_rows)
        record = _turn_memory.build_record(rows, reply=reply,
                                           ts=float(now or time.time()))
        receipt = _turn_memory.render_receipt(record)
    except Exception:
        rows, record, receipt = [], {}, ""
    return {"rows": rows, "receipt": str(receipt or "")[:120],
            "record": record}


def expression_block(store=None, state=None, relationship=None,
                     soft_target=0, soft_max=0, hour=None):
    """Wording constraints from the expression P0 modules."""
    core = (state or {}).get("core") if isinstance(state, dict) else {}
    core = core if isinstance(core, dict) else {}
    affect = {"valence": float(core.get("v") or 0.0),
              "arousal": float(core.get("a") or 0.5),
              "stress": float(core.get("stress") or 0.2)}
    rel = relationship if isinstance(relationship, dict) else {}
    out = {"rules": "", "template": "", "topic": "", "voice": "",
           "template_name": "default", "topic_name": "", "voice_name": ""}
    try:
        out["rules"] = _prompt_rules.render_rules(
            affect=affect, relation=rel, certainty=0.7,
            soft_target=int(soft_target or 0), soft_max=int(soft_max or 0))
    except Exception:
        out["rules"] = ""
    try:
        built = _expr_template.build_reply({}, rel)
        out["expr_template_order"] = [str(item) for item in
                                      (built.get("order") or [])][:8]
    except Exception:
        out["expr_template_order"] = []
    try:
        rendered = _template.render(
            "{{# if tense}}稳一点说。{{/ if}}{{closing}}",
            {"tense": float(core.get("stress") or 0.0) >= 0.6,
             "closing": "不用急着答。"})
        out["template"] = str(rendered or "")
        out["template_name"] = "reply-soft"
    except Exception:
        out["template"] = ""
    try:
        topic = _topic.topic_control(turns=[], state=affect, relationship=rel,
                                     hour=hour)
        out["topic"] = str((_topic.directives(topic) or {}).get("tone") or "")
        out["topic_name"] = str((topic or {}).get("tendency")
                                or (topic or {}).get("holder") or "")
    except Exception:
        out["topic"] = ""
    try:
        data_dir = _data_dir(store)
        bank = _read((data_dir / VOICE_FILE) if data_dir else None,
                     {"entries": []})
        entries = [row for row in (bank.get("entries") or [])
                   if isinstance(row, dict)]
        picked = _voice.pick({"v": affect["valence"], "tension": affect["stress"]},
                             rel, [], float(time.time()), entries=entries)
        if picked:
            out["voice"] = str(picked[0].get("phrase") or "")[:40]
            out["voice_name"] = str(picked[0].get("id") or "voice")[:24]
    except Exception:
        out["voice"] = ""
    return out


def record_extension_snapshot(store, snapshot):
    data_dir = _data_dir(store)
    path = (data_dir / EXTENSIONS_FILE) if data_dir else None
    if path is None:
        return False
    doc = _read(path, {})
    doc.update({"schema": SCHEMA, "ts": round(float(time.time()), 3),
                "latest": snapshot,
                "history": ((doc.get("history") or [])
                            + [snapshot])[-50:]})
    return _write(path, doc)


def extension_summary(store):
    data_dir = _data_dir(store)
    doc = _read((data_dir / EXTENSIONS_FILE) if data_dir else None, {})
    latest = doc.get("latest") if isinstance(doc.get("latest"), dict) else {}
    return latest
