# -*- coding: utf-8 -*-
"""task-236 (batch B): the fifteen memory / narrative modules behind one hook.

Batch B of docs/COVERAGE-BATCHES.md is "记忆/叙事". This module owns those
fifteen and nothing else:

    bio_identity  entity_graph  entity_resolve  feedback_memory  graph_extract
    graph_recall  layered_memory  memory_dual  memory_forgetting  memory_store
    migrate_store  policy_learning  predictor  co_recall  scoring

It is deliberately standalone: one entry point, no IO, no import from
pipeline.py or engine.py. The Lead wires it in later; that is why everything
below returns *deltas* instead of writing anything.

    deltas = apply_turn(state, phase, payload)

phase
  "turn_start"  read-only: identity threat, entity resolution, graph recall,
                layered / dual / forgetting projections, scoring, forecast,
                policy choice.
  "turn_end"    compute what should change: graph writes, co-recall counts,
                memory strength, policy update, prediction error, identity
                feedback. Nothing is written here either.

payload keys (all optional, every one is bounded and guarded)
  user_text, assistant_text   this turn's text
  dims, confidence            the appraisal/probe numbers
  entries                     memory rows (id/text/ts/importance/...)
  recalled_ids                the ids this turn injected
  query                       recall query (defaults to user_text)
  graph                       in-memory entity graph {"schema","entities","edges"}
  graph_tag                   {"entities":[{name,type,aliases}],"relations":[...]}
  silence_phase, hour         policy context (hour defaults to local hour)
  responded, response_gap_s, delta_discomfort   policy reward inputs
  migrate_sample              legacy entries for the read-only migration map
  backend                     memory store backend name
  batch_b                     explicit switch for this batch

Return
  {"enabled", "phase", "ts", "modules", "reads", "field_deltas",
   "state_deltas", "skipped", "counts"}

  field_deltas   proposals for biocore_runtime.arbiter (v/a/stress/social/
                 trust/closeness) -- only bio_identity proposes today.
  state_deltas   ready-to-merge blocks: entity_graph, memory_tiers, dual_scores,
                 memory_strength, co_recall, policy_q, predictor_forecast,
                 predictor_history, migrate_report, identity.

/state fields this batch can feed (the Lead mounts them):
  memory_tiers   <- layered_memory        (resident / retrieval / archive)
  graph          <- entity_graph + graph_recall (nodes, edges, matched rows)
  co_recall      <- co_recall             (pair -> count)
  narrative      <- bio_identity          (identity threat + feedback read)
"""
from __future__ import annotations

import importlib
import json
import math
import time
from pathlib import Path

SCHEMA = 1
SWITCH_KEY = "batch_b"
ENV_KEY = "BIOCORE_BATCH_B"

MODULES = ("bio_identity", "entity_graph", "entity_resolve",
           "feedback_memory", "graph_extract", "graph_recall",
           "layered_memory", "memory_dual", "memory_forgetting",
           "memory_store", "migrate_store", "policy_learning", "predictor",
           "co_recall", "scoring")

GRAPH_LIMIT = 8          # entities kept per turn
EDGE_LIMIT = 12          # edges kept per turn
PAIR_LIMIT = 32          # co-recall pairs kept in state
SCORE_LIMIT = 8          # scored entries kept in state
STRENGTH_LIMIT = 20      # strength rows kept in state
HISTORY_LIMIT = 24       # predictor history rows
Q_LIMIT = 32             # policy contexts kept
RECALL_LIMIT = 5         # graph recall rows (module cap is 5)
CHANNELS = ("v", "a", "stress", "social", "trust", "closeness")
CAPS = {"v": 0.10, "a": 0.10, "stress": 0.08, "social": 0.08,
        "trust": 0.02, "closeness": 0.02}


# ---------------------------------------------------------------- helpers
def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return default  # may be None: callers use that to mean "unknown"
    if not math.isfinite(number):
        return default
    return number


def _clamp(value, low, high):
    return max(low, min(high, _num(value, low)))


def _truthy(raw, default):
    if raw is None:
        return bool(default)
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("1", "true", "on", "yes"):
        return True
    if text in ("0", "false", "off", "no"):
        return False
    return bool(default)


def enabled(payload=None, env=None):
    """Explicit payload > env > default ON (the Lead gates it globally)."""
    data = payload if isinstance(payload, dict) else {}
    if isinstance(data.get(SWITCH_KEY), bool):
        return data[SWITCH_KEY]
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    if isinstance(switches.get(SWITCH_KEY), bool):
        return switches[SWITCH_KEY]
    environ = env if hasattr(env, "get") else None
    if environ is not None and ENV_KEY in environ:
        return _truthy(environ.get(ENV_KEY), True)
    return True


def _mod(name):
    """Import one module of the batch; None when the checkout is stripped."""
    for path in ("biocore_model." + name, "biocore_memory." + name):
        try:
            return importlib.import_module(path)
        except Exception:
            continue
    return None


def _call(name, fn, *args, **kwargs):
    module = _mod(name)
    if module is None or not callable(getattr(module, fn, None)):
        return {"enabled": False, "reason": "module_missing", "value": None}
    try:
        return {"enabled": True, "reason": "ok",
                "value": getattr(module, fn)(*args, **kwargs)}
    except Exception as error:
        return {"enabled": False, "reason": type(error).__name__, "value": None}


def _value(result, fallback=None):
    if not isinstance(result, dict) or not result.get("enabled"):
        return fallback
    return result.get("value", fallback)


def _entries(payload):
    rows = payload.get("entries")
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _graph(payload, state):
    raw = payload.get("graph")
    if not isinstance(raw, dict):
        raw = state.get("entity_graph") if isinstance(state, dict) else None
    if not isinstance(raw, dict):
        empty = _value(_call("entity_graph", "empty_graph"), None)
        return dict(empty) if isinstance(empty, dict) else {
            "schema": 1, "entities": [], "edges": []}
    graph = dict(raw)
    graph["entities"] = [row for row in (graph.get("entities") or [])
                         if isinstance(row, dict)]
    graph["edges"] = [row for row in (graph.get("edges") or [])
                      if isinstance(row, dict)]
    return graph


def _local_hour(now, offset_hours=8.0):
    return round(((_num(now) / 3600.0 + float(offset_hours)) % 24.0), 3)


def _bounded_dict(mapping, limit):
    rows = dict(mapping or {})
    if len(rows) <= limit:
        return rows
    ordered = sorted(rows.items(),
                     key=lambda item: (-_num(_value_of(item[1]), 0.0),
                                       str(item[0])))
    return dict(ordered[:limit])


def _value_of(row):
    if isinstance(row, dict):
        return row.get("count", row.get("q", row.get("score", 0.0)))
    return row


# ---------------------------------------------------------------- reads
def _read_identity(payload, state):
    """bio_identity: is this a threat to the self, and what does it do."""
    module = _mod("bio_identity")
    if module is None or not hasattr(module, "IdentityMixin"):
        return {"enabled": False, "reason": "module_missing", "value": {}}
    dims = payload.get("dims") if isinstance(payload.get("dims"), dict) else {}
    core = state.get("core") if isinstance(state.get("core"), dict) else {}
    try:
        obj = module.IdentityMixin()
        obj.v = _clamp(core.get("v", 0.0), -1.0, 1.0)
        obj.stress = _clamp(core.get("stress", 0.2), 0.0, 1.0)
        obj.trust = _clamp((state.get("relationship") or {}).get("trust", 0.5),
                           0.0, 1.0)
        obj.echo_trace = 0.0
        obj.identity_threat_stress_enabled = True
        before = (obj.v, obj.stress, obj.trust)
        threat = bool(obj.detect_identity_threat(dims=dims))
        obj.feedback_user(dims=dims)
        deltas = {"v": round(obj.v - before[0], 6),
                  "stress": round(obj.stress - before[1], 6),
                  "trust": round(obj.trust - before[2], 6)}
        return {"enabled": True, "reason": "ok", "value": {
            "threat": threat,
            "echo_trace": round(_num(obj.echo_trace), 4),
            "deltas": {key: _clamp(value, -CAPS[key], CAPS[key])
                       for key, value in deltas.items()}}}
    except Exception as error:
        return {"enabled": False, "reason": type(error).__name__, "value": {}}


def _read_entity_resolve(payload, state, graph):
    text = str(payload.get("user_text") or "")
    entities = graph.get("entities") or []
    if not text or not entities:
        return {"enabled": bool(entities), "reason": "nothing_to_resolve",
                "value": {"normalized": "", "match": "", "score": 0.0}}
    name = str(payload.get("entity_name") or "").strip()
    target = name or text[:24]
    normalized = _value(_call("entity_resolve", "normalize", target), "")
    matched = _value(_call("entity_resolve", "match", entities, target), None)
    score = 0.0
    if isinstance(matched, dict):
        score = _num(matched.get("score"), 0.0)
        module = _mod("entity_resolve")
        if not score and module is not None and hasattr(module, "similarity"):
            score = _num(module.similarity(
                target, matched.get("name") or ""), 0.0)
    return {"enabled": True, "reason": "ok", "value": {
        "normalized": str(normalized or ""),
        "match": str((matched or {}).get("id") or ""),
        "name": str((matched or {}).get("name") or ""),
        "via": str((matched or {}).get("via") or ""),
        "score": round(score, 4)}}


def _read_graph(payload, state, graph, now):
    """graph_recall: the "你知道的" rows around the entities in the text."""
    text = str(payload.get("user_text") or "")
    window, label = _value(_call("graph_recall", "detect_window", text, now),
                           (None, "")) or (None, "")
    rows = _value(_call("graph_recall", "recall", graph, text, now, 2,
                        RECALL_LIMIT) if text else [], [])
    rows = [row for row in (rows or []) if isinstance(row, dict)][:RECALL_LIMIT]
    block = ""
    if text and rows:
        block = str(_value(_call("graph_recall", "render", graph, text, now),
                           "") or "")
    return {"enabled": True, "reason": "ok", "value": {
        "window_days": window, "window": str(label or ""),
        "rows": rows, "block_chars": len(block)}}


def _read_layered(payload, state):
    entries = _entries(payload)
    recalled = [str(item) for item in (payload.get("recalled_ids") or [])]
    selected = _value(_call("layered_memory", "select", entries, recalled), {})
    selected = selected if isinstance(selected, dict) else {}
    resident = [row for row in (selected.get("resident") or [])
                if isinstance(row, dict)]
    retrieval = [row for row in (selected.get("retrieval") or [])
                 if isinstance(row, dict)]
    return {"enabled": bool(entries), "reason": "ok" if entries else "no_entries",
            "value": {"resident": [str(row.get("id") or "") for row in resident],
                      "retrieval": [str(row.get("id") or "") for row in retrieval],
                      "archive_count": int(_num(
                          selected.get("archive_count"), len(entries)))}}


def _read_dual(payload, state, now):
    entries = _entries(payload)
    limit = int(_clamp(payload.get("dual_limit", 4), 1, 8))
    context = {"query": str(payload.get("query") or payload.get("user_text") or "")}
    picked = _value(_call("memory_dual", "select", entries, now, limit, context),
                    {}) or {}
    rows = [row for row in (picked.get("picked") or [])
            if isinstance(row, dict)][:limit]
    return {"enabled": bool(entries), "reason": "ok" if entries else "no_entries",
            "value": {"picked": [{"id": str(row.get("id") or ""),
                                  "score": round(_num(row.get("score")), 4)}
                                 for row in rows],
                      "skipped": max(0, len(entries) - len(rows))}}


def _read_forgetting(payload, state, now):
    entries = _entries(payload)
    view = _value(_call("memory_forgetting", "memory_view", entries, 5), []) or []
    injectable = 0
    for entry in entries:
        if bool(_value(_call("memory_forgetting", "injectable", entry), False)):
            injectable += 1
    return {"enabled": bool(entries), "reason": "ok" if entries else "no_entries",
            "value": {"view": view if isinstance(view, list) else [],
                      "injectable": injectable, "total": len(entries)}}


def _read_store(payload):
    backend = _value(_call("memory_store", "normalize_backend",
                           payload.get("backend") or "sqlite"), "sqlite")
    return {"enabled": True, "reason": "ok",
            "value": {"backend": str(backend or "sqlite")}}


def _read_policy(payload, state, now):
    q_table = state.get("policy_q") if isinstance(state.get("policy_q"), dict) else {}
    hour = int(_clamp(payload.get("hour", _local_hour(now)), 0, 23))
    attachment = str((state.get("relationship") or {}).get("attachment_style")
                     or "secure")
    context = _value(_call("policy_learning", "make_context",
                           payload.get("silence_phase") or "expect",
                           attachment, hour), "")
    choice = _value(_call("policy_learning", "choose", str(context or ""),
                          q_table), None)
    if isinstance(choice, dict):
        action = str(choice.get("action") or "rest")
    else:
        action = str(choice or "rest")
    view = _value(_call("policy_learning", "policy_view", q_table,
                        str(context or "")), {})
    return {"enabled": True, "reason": "ok",
            "value": {"context": str(context or ""), "action": str(action or ""),
                      "hrs": hour, "view": view if isinstance(view, dict) else {}}}


def _flat_state(state):
    """predictor / scoring want one flat snapshot (v, a, ... at the top)."""
    state = state if isinstance(state, dict) else {}
    core = state.get("core") if isinstance(state.get("core"), dict) else {}
    flat = dict(core)
    rel = state.get("relationship") if isinstance(state.get("relationship"), dict) else {}
    for key in ("trust", "closeness", "conflict"):
        if key in rel and key not in flat:
            flat[key] = rel[key]
    needs = state.get("needs") if isinstance(state.get("needs"), dict) else core.get("needs")
    if isinstance(needs, dict):
        flat["needs"] = dict(needs)
    emotion = state.get("emotion")
    if isinstance(emotion, dict) and emotion.get("label"):
        flat["emotion"] = emotion.get("label")
    return flat


def _read_predictor(payload, state, now):
    history = state.get("predictor_history")
    history = history if isinstance(history, list) else []
    forecast = _value(_call("predictor", "predict", _flat_state(state), history), {})
    return {"enabled": bool(forecast), "reason": "ok" if forecast else "module_missing",
            "value": forecast if isinstance(forecast, dict) else {}}


def _tokens(text):
    text = str(text or "").lower()
    out = set()
    for chunk in text.replace("，", " ").replace("。", " ").split():
        out.add(chunk)
        for index in range(len(chunk) - 1):
            out.add(chunk[index:index + 2])
    return out


def _cosine(query, text):
    """Lexical overlap proxy used when the caller has no embedding cosine."""
    left, right = _tokens(query), _tokens(text)
    if not left or not right:
        return 0.0
    return round(len(left & right) / float(len(left | right)), 4)


def _read_scoring(payload, state, now=None):
    """scoring: pure per-entry score for this turn's query (turn clock)."""
    entries = _entries(payload)
    query = str(payload.get("query") or payload.get("user_text") or "")
    core = _flat_state(state)
    stamp = _num(now if now is not None else payload.get("now"), time.time())
    given = payload.get("cosines") if isinstance(payload.get("cosines"), dict) else {}
    rows = {}
    for entry in entries:
        entry_id = str(entry.get("id") or "")
        cosine = _clamp(given.get(entry_id, _cosine(query, entry.get("text"))),
                        0.0, 1.0)
        score = _value(_call("scoring", "memory_score", core, entry, cosine,
                             query, now=stamp), None)
        if score is None:
            continue
        rows[str(entry.get("id") or "")] = round(_num(score), 6)
    ordered = sorted(rows.items(), key=lambda item: (-item[1], item[0]))
    return {"enabled": bool(rows), "reason": "ok" if rows else "no_entries",
            "value": {"top": dict(ordered[:SCORE_LIMIT]),
                      "count": len(rows)}}


# ---------------------------------------------------------------- writes
def _write_graph(payload, state, graph, now):
    """graph_extract + entity_graph: one tag -> bounded nodes and edges."""
    tag = payload.get("graph_tag")
    tag = tag if isinstance(tag, dict) else {}
    extracted = _value(_call("graph_extract", "extract", tag, now), {}) or {}
    entities = [row for row in (extracted.get("entities") or [])
                if isinstance(row, dict)][:GRAPH_LIMIT]
    relations = [row for row in (extracted.get("relations") or [])
                 if isinstance(row, dict)][:EDGE_LIMIT]
    if not entities and not relations:
        return {"enabled": True, "reason": "no_tag", "value": None}
    work = {"schema": graph.get("schema", 1),
            "entities": [dict(row) for row in graph.get("entities") or []],
            "edges": [dict(row) for row in graph.get("edges") or []]}
    wrote_entities = 0
    wrote_edges = 0
    for row in entities:
        result = _value(_call("entity_graph", "upsert_entity", work,
                              row.get("name"), row.get("type"),
                              row.get("aliases"), now), None)
        if isinstance(result, tuple) and len(result) == 2:
            work = result[0] if isinstance(result[0], dict) else work
            wrote_entities += 1
    for row in relations:
        result = _value(_call("entity_graph", "upsert_edge", work,
                              row.get("src") or row.get("from"),
                              row.get("rel") or row.get("relation"),
                              row.get("dst") or row.get("to"), now,
                              _clamp(row.get("confidence", 1.0), 0.0, 1.0),
                              str(payload.get("entry_id") or "")), None)
        if isinstance(result, tuple) and len(result) == 2:
            work = result[0] if isinstance(result[0], dict) else work
            wrote_edges += 1
    counts = _value(_call("entity_graph", "stats", work), {}) or {}
    return {"enabled": True, "reason": "ok", "value": {
        "graph": work,
        "wrote": {"entities": wrote_entities, "edges": wrote_edges},
        "stats": counts if isinstance(counts, dict) else {}}}


def _write_strength(payload, state, now):
    entries = _entries(payload)
    recalled = [str(item) for item in (payload.get("recalled_ids") or [])]
    if not entries:
        return {"enabled": True, "reason": "no_entries", "value": None}
    touched = _value(_call("feedback_memory", "touch", entries,
                           recalled[0] if recalled else "", now, "recall"), None)
    if isinstance(touched, dict):
        touched = touched.get("entries")
    decayed = _value(_call("feedback_memory", "decay_all", entries, now), None)
    if isinstance(decayed, dict):
        decayed = decayed.get("entries")
    rows = {}
    for source in (decayed if isinstance(decayed, list) else [],
                   touched if isinstance(touched, list) else []):
        for entry in source:
            if not isinstance(entry, dict):
                continue
            entry_id = str(entry.get("id") or "")
            if not entry_id:
                continue
            rows[entry_id] = {"strength": round(_num(entry.get("strength")), 4),
                              "count": int(_num(entry.get("recall_count",
                                                          entry.get("count")), 0))}
    bounded = _bounded_dict(rows, STRENGTH_LIMIT)
    return {"enabled": True, "reason": "ok", "value": {
        "rows": bounded, "count": len(bounded)}}


def _write_co_recall(payload, state):
    recalled = [str(item) for item in (payload.get("recalled_ids") or [])]
    pairs = _value(_call("co_recall", "pairs", recalled), []) or []
    previous = state.get("co_recall") if isinstance(state.get("co_recall"), dict) else {}
    if not pairs:
        return {"enabled": True, "reason": "no_pairs", "value": None}
    updated = {}
    for key, row in previous.items():
        if isinstance(row, dict):
            updated[str(key)] = {"count": int(_num(row.get("count"), 0)),
                                 "last_ts": _num(row.get("last_ts"), 0.0)}
    stamp = _num(payload.get("now"), time.time())
    for key in pairs:
        if isinstance(key, (tuple, list)) and len(key) == 2:
            label = "%s|%s" % (key[0], key[1])
        else:
            label = str(key)
        slot = updated.get(label) or {"count": 0, "last_ts": 0.0}
        updated[label] = {"count": slot["count"] + 1, "last_ts": stamp}
    return {"enabled": True, "reason": "ok",
            "value": {"pairs": _bounded_dict(updated, PAIR_LIMIT),
                      "added": len(pairs)}}


def _write_policy(payload, state, now):
    context = str(payload.get("policy_context") or "")
    action = str(payload.get("policy_action") or "")
    if not context:
        hour = int(_clamp(payload.get("hour", _local_hour(now)), 0, 23))
        attachment = str((state.get("relationship") or {}).get("attachment_style")
                         or "secure")
        context = str(_value(_call("policy_learning", "make_context",
                                   payload.get("silence_phase") or "expect",
                                   attachment, hour), "") or "")
    if not context:
        return {"enabled": True, "reason": "no_context", "value": None}
    if not action:
        table = state.get("policy_q") if isinstance(state.get("policy_q"), dict) else {}
        choice = _value(_call("policy_learning", "choose", context, table), None)
        action = (str(choice.get("action")) if isinstance(choice, dict)
                  else str(choice or ""))
    if not action:
        return {"enabled": True, "reason": "no_action", "value": None}
    reward = _value(_call("policy_learning", "reward",
                          bool(payload.get("responded", False)),
                          _num(payload.get("response_gap_s"), 0.0),
                          _num(payload.get("delta_discomfort"), 0.0)), 0.0)
    table = state.get("policy_q") if isinstance(state.get("policy_q"), dict) else {}
    updated = _value(_call("policy_learning", "update", table, context, action,
                           reward), {})
    updated = updated if isinstance(updated, dict) else {}
    return {"enabled": True, "reason": "ok",
            "value": {"q_table": _bounded_dict(updated, Q_LIMIT),
                      "reward": round(_num(reward), 4)}}


def _write_predictor(payload, state, now):
    history = state.get("predictor_history")
    history = history if isinstance(history, list) else []
    forecast = state.get("predictor_forecast")
    forecast = forecast if isinstance(forecast, dict) else {}
    actual = _flat_state(state)
    error = _value(_call("predictor", "compare", forecast, actual), {}) if forecast else {}
    error = error if isinstance(error, dict) else {}
    surprise = _num(error.get("surprise"), None)
    if surprise is None:
        surprise = _num(_value(_call("predictor", "surprise",
                                     _num(error.get("error"), 0.0)), 0.0), 0.0)
    boost = _value(_call("predictor", "attention_boost", _num(surprise)), 0.0)
    appended = _value(_call("predictor", "append_history", history,
                            _flat_state(state), HISTORY_LIMIT), history)
    return {"enabled": True, "reason": "ok" if forecast else "no_forecast",
            "value": {"error": error, "surprise": round(_num(surprise), 4),
                      "attention_boost": round(_clamp(_num(boost), 0.0, 1.0), 4),
                      "history": appended if isinstance(appended, list)
                      else history}}


def _write_migrate(payload, state):
    sample = payload.get("migrate_sample")
    if not isinstance(sample, list):
        return {"enabled": True, "reason": "no_sample", "value": None}
    report = _value(_call("migrate_store", "convert", sample), None)
    if isinstance(report, tuple) and len(report) == 2:
        rows, detail = report
        return {"enabled": True, "reason": "dry_run", "value": {
            "converted": len(rows) if isinstance(rows, list) else 0,
            "report": detail if isinstance(detail, dict) else {}}}
    return {"enabled": True, "reason": "convert_failed", "value": None}


# ---------------------------------------------------------------- entry
def apply_turn(state, phase, payload=None, now=None, enabled_override=None):
    """One turn of batch B: read at turn_start, compute deltas at turn_end."""
    data = payload if isinstance(payload, dict) else {}
    session_state = state if isinstance(state, dict) else {}
    stamp = round(_num(now if now is not None else data.get("now"), time.time()), 3)
    phase = str(phase or "").strip().lower()
    result = {"schema": SCHEMA, "enabled": False, "phase": phase, "ts": stamp,
              "modules": {name: False for name in MODULES},
              "reads": {}, "field_deltas": {}, "state_deltas": {},
              "skipped": [], "counts": {"modules": len(MODULES), "enabled": 0}}
    if phase not in ("turn_start", "turn_end"):
        result["reason"] = "bad_phase"
        return result
    on = (enabled_override if isinstance(enabled_override, bool)
          else enabled(data))
    if not on:
        result["reason"] = "disabled"
        return result
    result["enabled"] = True
    result["reason"] = "ok"
    result["activity"] = {name: False for name in MODULES}
    if not isinstance(data.get("now"), (int, float)):
        data = dict(data, now=stamp)

    graph = _graph(data, session_state)
    skipped = result["skipped"]

    # -- read side (both phases; turn_end reads less) --------------------
    if phase == "turn_start":
        identity = _read_identity(data, session_state)
        graph_read = _read_graph(data, session_state, graph, stamp)
        resolve = _read_entity_resolve(data, session_state, graph)
        layers = _read_layered(data, session_state)
        dual = _read_dual(data, session_state, stamp)
        forgetting = _read_forgetting(data, session_state, stamp)
        store = _read_store(data)
        policy = _read_policy(data, session_state, stamp)
        forecast = _read_predictor(data, session_state, stamp)
        scoring = _read_scoring(data, session_state, stamp)
        for key, read, name in (
                ("identity", identity, "bio_identity"),
                ("graph", graph_read, "graph_recall"),
                ("entities", resolve, "entity_resolve"),
                ("memory_tiers", layers, "layered_memory"),
                ("dual", dual, "memory_dual"),
                ("forgetting", forgetting, "memory_forgetting"),
                ("store", store, "memory_store"),
                ("policy", policy, "policy_learning"),
                ("forecast", forecast, "predictor"),
                ("scores", scoring, "scoring")):
            result["reads"][key] = read.get("value")
            result["activity"][name] = bool(read.get("enabled"))
            if not read.get("enabled"):
                skipped.append({"module": name, "reason": read.get("reason")})
        result["activity"]["entity_graph"] = bool(graph.get("entities"))
        result["reads"]["graph_stats"] = _value(
            _call("entity_graph", "stats", graph), {})
        identity_value = identity.get("value") or {}
        for name, delta in (identity_value.get("deltas") or {}).items():
            if name in CHANNELS and abs(_num(delta)) > 1e-6:
                result["field_deltas"][name] = round(
                    _clamp(delta, -CAPS[name], CAPS[name]), 6)
        result["state_deltas"]["identity_read"] = {
            "threat": bool(identity_value.get("threat")),
            "ts": stamp}
        if isinstance(forecast.get("value"), dict):
            result["state_deltas"]["predictor_forecast"] = forecast["value"]
        tiers = layers.get("value") or {}
        if tiers:
            result["state_deltas"]["memory_tiers"] = tiers
        if isinstance(dual.get("value"), dict) and dual["value"].get("picked"):
            result["state_deltas"]["dual_scores"] = {
                row["id"]: row["score"] for row in dual["value"]["picked"]}
        if isinstance(scoring.get("value"), dict) and scoring["value"].get("top"):
            result["state_deltas"]["memory_scores"] = scoring["value"]["top"]

    # -- write side ------------------------------------------------------
    if phase == "turn_end":
        graph_write = _write_graph(data, session_state, graph, stamp)
        strength = _write_strength(data, session_state, stamp)
        co_recall = _write_co_recall(data, session_state)
        migrate = _write_migrate(data, session_state)
        policy = _write_policy(data, session_state, stamp)
        predictor = _write_predictor(data, session_state, stamp)
        identity = _read_identity(data, session_state)
        for key, write, name in (
                ("graph", graph_write, "entity_graph"),
                ("strength", strength, "feedback_memory"),
                ("co_recall", co_recall, "co_recall"),
                ("migrate", migrate, "migrate_store"),
                ("policy", policy, "policy_learning"),
                ("predictor", predictor, "predictor"),
                ("identity", identity, "bio_identity")):
            result["reads"][key] = write.get("value")
            result["activity"][name] = bool(write.get("enabled"))
            if not write.get("enabled") or write.get("reason") not in ("ok", "dry_run"):
                skipped.append({"module": name, "reason": write.get("reason")})
        result["activity"]["graph_extract"] = bool(
            (graph_write.get("value") or {}).get("wrote"))
        result["activity"]["layered_memory"] = bool(_entries(data))
        result["activity"]["memory_dual"] = bool(_entries(data))
        result["activity"]["memory_forgetting"] = bool(_entries(data))
        result["activity"]["memory_store"] = True
        result["activity"]["scoring"] = bool(_entries(data))
        result["activity"]["entity_resolve"] = bool(_mod("entity_resolve"))
        graph_value = graph_write.get("value") or {}
        if isinstance(graph_value.get("graph"), dict):
            result["state_deltas"]["entity_graph"] = graph_value["graph"]
            result["state_deltas"]["graph_stats"] = graph_value.get("stats") or {}
        if isinstance(strength.get("value"), dict):
            result["state_deltas"]["memory_strength"] = strength["value"]["rows"]
        if isinstance(co_recall.get("value"), dict):
            result["state_deltas"]["co_recall"] = co_recall["value"]["pairs"]
        if isinstance(policy.get("value"), dict):
            result["state_deltas"]["policy_q"] = policy["value"]["q_table"]
        if isinstance(predictor.get("value"), dict):
            result["state_deltas"]["predictor_history"] = predictor["value"]["history"]
            result["state_deltas"]["prediction"] = {
                "surprise": predictor["value"].get("surprise"),
                "attention_boost": predictor["value"].get("attention_boost")}
        if isinstance(migrate.get("value"), dict):
            result["state_deltas"]["migrate_report"] = migrate["value"]
        identity_value = identity.get("value") or {}
        for name, delta in (identity_value.get("deltas") or {}).items():
            if name in CHANNELS and abs(_num(delta)) > 1e-6:
                result["field_deltas"][name] = round(
                    _clamp(delta, -CAPS[name], CAPS[name]), 6)
        result["state_deltas"]["identity_read"] = {
            "threat": bool(identity_value.get("threat")),
            "ts": stamp}

    result["modules"] = {name: _mod(name) is not None for name in MODULES}
    result["counts"] = {"modules": len(MODULES),
                        "available": sum(1 for flag in result["modules"].values()
                                         if flag),
                        "active": sum(1 for flag in result["activity"].values()
                                      if flag)}
    return result


# ---------------------------------------------------------------- CLI
def main(argv=None):  # pragma: no cover - manual debugging only
    import sys
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    payload = json.loads(raw) if raw.strip() else {}
    state = payload.pop("state", {})
    phase = payload.pop("phase", "turn_start")
    print(json.dumps(apply_turn(state, phase, payload),
                     ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
