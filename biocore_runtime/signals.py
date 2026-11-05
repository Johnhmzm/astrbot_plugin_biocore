# -*- coding: utf-8 -*-
"""task-224 (5a): P0 perception / relationship / self modules wired into the core.

One deterministic snapshot per turn, stored at <dataDir>/signals.json and
exposed through /state. Every module call is guarded: a missing or failing
module yields {"enabled": false, "reason": ...} instead of breaking a turn.
No LLM, no IO beyond the one sidecar file.
"""
from __future__ import annotations

import importlib
import json
import time
from pathlib import Path

import biocore_model as _bm

SIGNALS_FILE = "signals.json"
HISTORY_LIMIT = 50
SCHEMA = 1

PERCEPTION = ("affective_labor", "compassion_fatigue", "connection_bids",
              "defense_mechanisms", "emotion_geometry", "needs_events",
              "social_pain", "social_repair")
RELATIONSHIP = ("commitment_extractor", "relation_stage",
                "relationship_stage", "repair_after_boundary")
SELF = ("metacog", "possible_selves", "self_interest", "self_verification")


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
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
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


def _mod(name):
    module = getattr(_bm, name, None)
    if module is not None:
        return module
    try:
        return importlib.import_module("biocore_model." + name)
    except Exception:
        try:
            return importlib.import_module("." + name, package="biocore_model")
        except Exception:
            return None


def _call(name, fn, *args, **kwargs):
    module = _mod(name)
    if module is None or not callable(getattr(module, fn, None)):
        return {"enabled": False, "reason": "module_missing"}
    try:
        value = getattr(module, fn)(*args, **kwargs)
        return {"enabled": True, "value": value}
    except Exception as error:
        return {"enabled": False, "reason": type(error).__name__}


def evaluate(store, session_id="s1", user_text="", assistant_text="",
             state=None, relationship=None, now=None):
    """Run all 17 P0 modules once; never raises."""
    stamp = round(float(now or time.time()), 3)
    core = state.get("core") if isinstance(state, dict) and isinstance(
        state.get("core"), dict) else (state if isinstance(state, dict) else {})
    rel = relationship if isinstance(relationship, dict) else {}
    v = float(core.get("v") or 0.0)
    a = float(core.get("a") or 0.5)
    stress = float(core.get("stress") or 0.2)
    social = float(core.get("social") or 0.55)
    text = str(user_text or "")

    out = {"schema": SCHEMA, "ts": stamp, "session_id": str(session_id),
           "enabled": {}, "perception": {}, "relationship": {}, "self": {}}

    # --- perception ---------------------------------------------------
    labor = _call("affective_labor", "turn_cost", max(0.0, min(1.0, (v + 1) / 2)),
                  max(0.0, min(1.0, (v + 1) / 2)), 0.0)
    out["perception"]["affective_labor"] = labor
    out["enabled"]["affective_labor"] = labor["enabled"]

    fatigue = _call("compassion_fatigue", "fatigue", 0, max(0.0, -v), 0.0)
    out["perception"]["compassion_fatigue"] = fatigue
    out["enabled"]["compassion_fatigue"] = fatigue["enabled"]

    recorded = _call("connection_bids", "record_bid", [], stamp, "user")
    bid_items = recorded.get("value") if isinstance(recorded.get("value"), list) else []
    settled = _call("connection_bids", "settle_bids", bid_items, stamp)
    view = _call("connection_bids", "bid_view", bid_items, 1.0)
    out["perception"]["connection_bids"] = {
        "enabled": recorded["enabled"], "bids": len(bid_items),
        "settled": len(settled.get("value") or []) if isinstance(
            settled.get("value"), list) else 0,
        "view": view.get("value")}
    out["enabled"]["connection_bids"] = recorded["enabled"]

    defense = _call("defense_mechanisms", "assess",
                    {"kind": "message", "valence": v, "intensity": abs(v)},
                    {"valence": v, "arousal": a, "stress": stress})
    out["perception"]["defense_mechanisms"] = defense
    out["enabled"]["defense_mechanisms"] = defense["enabled"]

    geometry = _call("emotion_geometry", "classify",
                     {"v": v, "a": a, "stress": stress})
    out["perception"]["emotion_geometry"] = geometry
    out["enabled"]["emotion_geometry"] = geometry["enabled"]

    needs = _call("needs_events", "needs_state",
                  {"social": social, "energy": core.get("energy", 0.6),
                   "stress": stress})
    out["perception"]["needs_events"] = needs
    out["enabled"]["needs_events"] = needs["enabled"]

    pain = _call("social_pain", "update", {"value": 0.0},
                 "rejection" if v < -0.3 or rel.get("conflict", 0) > 0.2
                 else "neutral", stamp)
    pain_view = _call("social_pain", "view", pain.get("value") or {"value": 0.0})
    out["perception"]["social_pain"] = {
        "enabled": pain["enabled"], "view": pain_view.get("value")}
    out["enabled"]["social_pain"] = pain["enabled"]

    repair = _call("social_repair", "repair_check", text, "")
    empathy = _call("social_repair", "empathy", v)
    out["perception"]["social_repair"] = {
        "enabled": repair["enabled"], "repair": repair.get("value"),
        "empathy": empathy.get("value")}
    out["enabled"]["social_repair"] = repair["enabled"]

    # --- relationship -------------------------------------------------
    commitment = _call("commitment_extractor", "extract", text, None, stamp)
    value = commitment.get("value") if isinstance(commitment.get("value"), dict) else {}
    out["relationship"]["commitment_extractor"] = {
        "enabled": commitment["enabled"],
        "has_commitment": bool(value.get("has_commitment")),
        "what": str(value.get("what") or ""),
        "due_ts": value.get("due_ts"),
        "value": value}
    out["enabled"]["commitment_extractor"] = commitment["enabled"]

    stage = _call("relation_stage", "evaluate",
                  {"valence": v, "stress": stress, "relationship": rel})
    out["relationship"]["relation_stage"] = stage
    out["enabled"]["relation_stage"] = stage["enabled"]

    hours = float(rel.get("days_known", 0) or 0) * 24.0
    stage_word = _call("relationship_stage", "stage_for", hours)
    out["relationship"]["relationship_stage"] = stage_word
    out["enabled"]["relationship_stage"] = stage_word["enabled"]

    boundary = _call("repair_after_boundary", "evaluate", None, 0.0, None)
    out["relationship"]["repair_after_boundary"] = boundary
    out["enabled"]["repair_after_boundary"] = boundary["enabled"]

    # --- self ---------------------------------------------------------
    band = _call("metacog", "evaluate", None,
                 max(0.0, min(1.0, 1.0 - abs(v))), 0,
                 bool(rel.get("conflict", 0) > 0.3))
    out["self"]["metacog"] = band
    out["enabled"]["metacog"] = band["enabled"]

    selves = _call("possible_selves", "rank", None,
                   {"valence": v, "stress": stress})
    out["self"]["possible_selves"] = selves
    out["enabled"]["possible_selves"] = selves["enabled"]

    interest = _call("self_interest", "assess",
                     {"valence": v, "social": social,
                      "relationship": rel, "needs": core.get("needs")})
    out["self"]["self_interest"] = interest
    out["enabled"]["self_interest"] = interest["enabled"]

    verify = _call("self_verification", "observe", {"misread": 0.0},
                   0.0, 0.6, float(rel.get("trust", 0.5) or 0.5))
    verify_intent = _call("self_verification", "intent",
                          verify.get("value") or {"value": 0.0})
    out["self"]["self_verification"] = {
        "enabled": verify["enabled"], "state": verify.get("value"),
        "intent": verify_intent.get("value")}
    out["enabled"]["self_verification"] = verify["enabled"]

    out["counts"] = {
        "perception": len(out["perception"]),
        "relationship": len(out["relationship"]),
        "self": len(out["self"]),
        "enabled": sum(1 for value in out["enabled"].values() if value),
    }
    _record(store, session_id, out)
    return out


def _record(store, session_id, snapshot):
    path = (_data_dir(store) or Path(".")) / SIGNALS_FILE
    doc = _read(path)
    history = [row for row in (doc.get("history") or []) if isinstance(row, dict)]
    history.append(snapshot)
    doc.update({"schema": SCHEMA, "ts": snapshot["ts"],
                "session_id": str(session_id),
                "history": history[-HISTORY_LIMIT:],
                "latest": snapshot})
    _write(path, doc)


def summary(store):
    """Read-only snapshot for /state (never recomputes)."""
    doc = _read((_data_dir(store) or Path(".")) / SIGNALS_FILE)
    latest = doc.get("latest") if isinstance(doc.get("latest"), dict) else {}
    if not latest:
        return {"enabled": {name: False for name in
                            PERCEPTION + RELATIONSHIP + SELF},
                "perception": {}, "relationship": {}, "self": {},
                "counts": {"perception": 0, "relationship": 0, "self": 0,
                           "enabled": 0}}
    return latest
