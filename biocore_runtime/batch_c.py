# -*- coding: utf-8 -*-
"""Batch C — relationship / self modules, independent hook.

Pure aggregation: reads state + payload, returns proposed deltas and module
views. Never mutates state or writes relationship state. Relationship
accumulation is dry-run by default and logged first (irreversible guard).
"""
from __future__ import annotations

from copy import deepcopy

from biocore_model import (connection_bids, metacog, possible_selves,
                           relationship_stage, repair_after_boundary,
                           self_interest, self_verification, social_repair)

FIELDS = ("relationship_stage", "relationship_trust", "connection_bids",
          "metacog", "possible_selves", "repair", "self_interest",
          "self_verification", "social_repair", "deltas", "dry_run", "logs")


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _dict(value):
    return value if isinstance(value, dict) else {}


def _relationship(state):
    rel = _dict(state.get("relationship")) or _dict(state.get("relation"))
    return rel


def _self(state):
    for key in ("self", "self_image", "identity"):
        value = state.get(key)
        if isinstance(value, dict):
            return value
    return _dict(state.get("core"))


def _bids(state):
    rel = _relationship(state)
    value = rel.get("bids") or state.get("bids") or []
    return [dict(item) for item in value if isinstance(item, dict)]


def _context(state, payload):
    ctx = dict(_dict(payload.get("context")))
    ctx.setdefault("state", state)
    ctx.setdefault("relationship", _relationship(state))
    ctx.setdefault("self", _self(state))
    return ctx


def apply_turn(state, phase, payload):
    """phase: turn_start | turn_end | state. Returns a pure delta bundle."""
    state = deepcopy(state) if isinstance(state, dict) else {}
    data = _dict(payload)
    phase = str(phase or "turn_end")
    dry_run = data.get("dry_run", True) is not False
    now = _num(data.get("now"), 0.0)
    rel = _relationship(state)
    logs = []
    deltas = {}

    hours = _num(rel.get("hours_total", rel.get("hours", data.get("hours_total"))), 0.0)
    try:
        stage = relationship_stage.stage_for(hours)
        stage_cfg = relationship_stage.stage_config(hours)
    except Exception:
        stage, stage_cfg = "stranger", {}

    trust = _num(rel.get("trust"), 0.5)
    try:
        bid_rows = _bids(state)
        if data.get("bid") or data.get("bid_code"):
            bid_rows = connection_bids.record_bid(
                bid_rows, now, str(data.get("bid") or data.get("bid_code") or ""))
        settled = connection_bids.settle_bids(
            bid_rows, now, responded_ts=data.get("responded_ts"),
            window_s=_num(data.get("bid_window_s"), 300.0))
        streak = connection_bids.streaks(bid_rows)
        next_trust = connection_bids.trust_update(
            trust, regular=bool(data.get("regular")),
            kept=bool(data.get("kept")),
            delayed=bool(data.get("delayed")),
            response_rate=_num(data.get("response_rate"), 0.0))
    except Exception:
        bid_rows, settled, streak, next_trust = [], {}, {}, trust
    trust_delta = round(float(next_trust) - trust, 6)
    deltas["relationship.trust"] = trust_delta
    deltas["relationship.stage"] = stage
    logs.append({"kind": "relationship_accumulation", "dry_run": bool(dry_run),
                 "stage": stage, "trust_before": round(trust, 6),
                 "trust_delta": trust_delta,
                 "action": "log_only" if dry_run else "proposed"})
    if not dry_run:
        logs.append({"kind": "relationship_accumulation", "dry_run": False,
                     "reason": "batch_c_is_pure; Lead integrates the delta"})

    try:
        meta = metacog.evaluate(
            intent=data.get("intent") or None,
            confidence=_num(data.get("confidence"), 0.6),
            guard_hits=int(_num(data.get("guard_hits"), 0)),
            conflict=bool(data.get("conflict")),
            history=data.get("history") if isinstance(data.get("history"), list) else [])
        meta_view = {"result": meta, "directives": metacog.directives(meta)}
    except Exception as error:
        meta_view = {"error": str(error)[:120]}

    try:
        selves = possible_selves.rank(
            selves=data.get("selves") or state.get("possible_selves"),
            current=data.get("current") or _self(state),
            flags=data.get("flags") if isinstance(data.get("flags"), dict) else None)
        self_view = {"result": selves, "directives": possible_selves.directives(selves)}
    except Exception as error:
        self_view = {"error": str(error)[:120]}

    try:
        boundary = _dict(data.get("boundary"))
        repair = repair_after_boundary.thresholds(
            severity=_num(boundary.get("severity", data.get("severity")), 0.5),
            quality=_num(data.get("apology_quality"), 0.0),
            count=int(_num(data.get("apology_count"), 1)),
            relationship=rel,
            now=now) if (boundary or data.get("repair")) else repair_after_boundary._inactive()
        deltas["repair.debt"] = _num(repair.get("debt"), 0.0)
    except Exception as error:
        repair = {"error": str(error)[:120]}

    try:
        interest = self_interest.assess(_context(state, data),
                                        config=data.get("config") if isinstance(data.get("config"), dict) else None)
        interest_view = {"result": interest, "view": self_interest.view(interest)}
        deltas["self_interest.weight"] = _num(interest.get("self_weight"), 0.0)
    except Exception as error:
        interest_view = {"error": str(error)[:120]}

    try:
        misread = _num(data.get("misread"), 0.0)
        verification = self_verification.observe(
            state.get("verification") or self_verification.initial(now),
            misread, clarity=_num(data.get("clarity"), 0.6),
            relation=_num(rel.get("trust"), 0.6), now=now)
        verify_view = {"result": verification,
                       "intent": self_verification.intent(verification.get("state") or verification)}
        deltas["self_verification.correction_urge"] = _num(
            _dict(verification.get("result")).get("correction_urge"), 0.0)
    except Exception as error:
        verify_view = {"error": str(error)[:120]}

    try:
        gratitude = _num(rel.get("gratitude"), 0.0)
        if data.get("kindness"):
            gratitude = social_repair.gratitude_event(gratitude, kindness=True)
        empathy = social_repair.empathy(
            _num(state.get("v", _self(state).get("v")), 0.0),
            user_mood=str(data.get("user_mood") or "unknown"),
            cognitive_accuracy=_num(data.get("cognitive_accuracy"), 0.5))
        repair_hint = social_repair.repair_check(
            str(data.get("user_text") or ""), str(data.get("previous_reply") or ""),
            clarify_failures=int(_num(data.get("clarify_failures"), 0)))
        social = social_repair.view(gratitude=gratitude, empathy_info=empathy,
                                    repair=repair_hint)
        deltas["social_repair.gratitude"] = round(float(gratitude) - _num(rel.get("gratitude"), 0.0), 6)
    except Exception as error:
        social = {"error": str(error)[:120]}

    return {"ok": True, "phase": phase, "dry_run": bool(dry_run),
            "fields": list(FIELDS),
            "relationship_stage": {"stage": stage, "config": stage_cfg},
            "relationship_trust": {"before": round(trust, 6),
                                   "delta": trust_delta,
                                   "after": round(float(next_trust), 6)},
            "connection_bids": {"bids": bid_rows, "settled": settled,
                                "streaks": streak},
            "metacog": meta_view, "possible_selves": self_view,
            "repair": repair, "self_interest": interest_view,
            "self_verification": verify_view, "social_repair": social,
            "deltas": deltas, "logs": logs}
