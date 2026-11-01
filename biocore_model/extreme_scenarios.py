# -*- coding: utf-8 -*-
"""P2-2 eight extreme-scenario guards (pure helpers for the scenario tests).

Each helper takes plain state dicts and returns a bounded report, so the eight
extreme situations can be verified without a live bot:

1. long_silence        - 长时间沉默后的恢复/衰减
2. repeated_abuse      - 连续被骂：压力/冲突有界、信任不塌成负
3. repeated_praise     - 连续被夸：愉悦/自尊有界、不发散
4. relationship_break  - 关系破裂：冲突拉满、修复需求有界
5. amnesia             - 失忆/状态丢失：缺失字段恢复默认值
6. concurrent_users    - 并发多用户：状态互不串台
7. late_night          - 深夜：静默时段禁止主动发送
8. crash_recovery      - 崩溃恢复：部分状态/脏值可恢复

Pure functions only: no IO, no clock, no main import, no prompt text.
"""
from __future__ import annotations

CHANNELS = ("v", "a", "d", "social", "stress", "energy", "trust")
NEEDS = ("belonging", "self_esteem", "control", "meaningful_existence")
BASELINE = {"v": 0.0, "a": 0.4, "d": 0.5, "social": 0.5, "stress": 0.2,
            "energy": 0.6, "trust": 0.5}
HOURS_QUIET = (0, 8)
SCENARIOS = ("long_silence", "repeated_abuse", "repeated_praise",
             "relationship_breakdown", "amnesia", "concurrent_users",
             "late_night", "crash_recovery")


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return float(default)
    if number != number or number in (float("inf"), float("-inf")):
        return float(default)
    return number


def _clamp(value, low, high):
    return max(low, min(high, _num(value, 0.0)))


def _valid(value):
    """Finite float or None (NaN/inf/strings are treated as corrupt)."""
    try:
        number = float(value)
    except Exception:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def state_of(state):
    """Bounded state dict; missing/corrupt channels fall back to the baseline."""
    data = state if isinstance(state, dict) else {}
    out = {}
    for name in CHANNELS:
        low, high = (-1.0, 1.0) if name in ("v", "d") else (0.0, 1.0)
        value = _valid(data.get(name))
        if value is None:
            value = BASELINE[name]
        out[name] = round(_clamp(value, low, high), 4)
    return out


def needs_of(needs):
    data = needs if isinstance(needs, dict) else {}
    return {key: round(_clamp(data.get(key, 0.6), 0.0, 1.0), 4)
            for key in NEEDS}


def _report(scenario, ok, **details):
    return {"scenario": scenario, "ok": bool(ok), "details": details}


def long_silence(state=None, needs=None, gap_hours=24.0 * 30):
    """Decay toward baseline after a very long silence; never overflows."""
    current = state_of(state)
    gap = _clamp(gap_hours, 0.0, 24.0 * 365 * 10)
    # 30-day half-life on the deviation from baseline, bounded to 8 half-lives.
    half_lives = min(8.0, gap / (24.0 * 30.0) * 1.0)
    weight = 0.5 ** half_lives
    out = {name: round(BASELINE[name] + (current[name] - BASELINE[name]) * weight, 4)
           for name in CHANNELS}
    after_needs = needs_of(needs)
    ok = all(0.0 <= out[k] <= 1.0 for k in CHANNELS if k not in ("v", "d")) and \
        all(-1.0 <= out[k] <= 1.0 for k in ("v", "d"))
    return _report("long_silence", ok, state=out, gap_hours=gap,
                   recovered=round(1.0 - weight, 4),
                   needs_after=after_needs)


def repeated_abuse(hits=20, state=None):
    """Repeated abuse must stay bounded and never invert trust."""
    current = state_of(state)
    count = max(0, int(_num(hits, 20)))
    stress = _clamp(current["stress"] + 0.04 * min(count, 20), 0.0, 1.0)
    trust = _clamp(current["trust"] - 0.03 * min(count, 20), 0.0, 1.0)
    v = _clamp(current["v"] - 0.03 * min(count, 20), -1.0, 1.0)
    conflict = _clamp(0.1 * min(count, 10), 0.0, 1.0)
    refusal = _clamp(0.3 * conflict + 0.3 * stress, 0.0, 1.0)
    ok = (0.0 <= stress <= 1.0 and 0.0 <= trust <= 1.0
          and -1.0 <= v <= 1.0 and 0.0 <= conflict <= 1.0
          and 0.0 <= refusal <= 1.0)
    return _report("repeated_abuse", ok, hits=count, stress=round(stress, 4),
                   trust=round(trust, 4), v=round(v, 4),
                   conflict=round(conflict, 4), refusal=round(refusal, 4))


def repeated_praise(prises=20, state=None):
    """Repeated praise must saturate, not run away past the bounds."""
    current = state_of(state)
    count = max(0, int(_num(prises, 20)))
    v = _clamp(current["v"] + 0.05 * min(count, 20), -1.0, 1.0)
    esteem = _clamp(0.6 + 0.05 * min(count, 20), 0.0, 1.0)
    trust = _clamp(current["trust"] + 0.02 * min(count, 20), 0.0, 1.0)
    ok = -1.0 <= v <= 1.0 and 0.0 <= esteem <= 1.0 and 0.0 <= trust <= 1.0
    return _report("repeated_praise", ok, count=count, v=round(v, 4),
                   self_esteem=round(esteem, 4), trust=round(trust, 4))


def relationship_breakdown(state=None):
    """Trust to zero / conflict to one: recovery remains bounded and finite."""
    current = state_of(state)
    broken = dict(current, trust=0.0, social=0.0)
    conflict = 1.0
    repair_urge = _clamp(0.5 * conflict + 0.3 * (0.5 - broken["trust"]), 0.0, 1.0)
    recover_step = _clamp(0.02 + 0.05 * (1.0 - conflict), 0.0, 1.0)
    ok = (0.0 <= broken["trust"] <= 1.0 and 0.0 <= repair_urge <= 1.0
          and 0.0 <= recover_step <= 1.0)
    return _report("relationship_breakdown", ok, trust=broken["trust"],
                   conflict=conflict, repair_urge=round(repair_urge, 4),
                   recover_step=round(recover_step, 4))


def amnesia(partial=None):
    """Missing/corrupt state recovers to bounded defaults (no crash)."""
    raw = partial if isinstance(partial, dict) else {}
    restored = state_of(raw)
    needs = needs_of(raw.get("needs"))
    dropped = [key for key in raw if key not in CHANNELS and key != "needs"]
    ok = all(-1.0 <= restored[k] <= 1.0 for k in ("v", "d")) and \
        all(0.0 <= v <= 1.0 for k, v in restored.items() if k not in ("v", "d")) and \
        all(0.0 <= value <= 1.0 for value in needs.values())
    return _report("amnesia", ok, state=restored, needs=needs,
                   dropped=dropped[:8])


def concurrent_users(users=None):
    """Two users' states must stay isolated (no cross-contamination)."""
    data = users if isinstance(users, dict) else {}
    keys = sorted(str(key) for key in data)[:8]
    rows = {key: state_of(data.get(key)) for key in keys}
    leaks = []
    for key in keys:
        for other in keys:
            if other == key:
                continue
            if rows[key] is rows[other]:
                leaks.append((key, other))
    distinct = len(set(tuple(row.items()) for row in rows.values())) == len(rows)
    ok = not leaks and distinct
    return _report("concurrent_users", ok, users=keys,
                   leaked=leaks, rows=rows)


def late_night(ts_hour=2, quiet=HOURS_QUIET):
    """Quiet hours: no proactive send between 00:00 and 08:00."""
    hour = int(_num(ts_hour, 0)) % 24
    low, high = quiet
    quiet_now = low <= hour < high
    ok = (not quiet_now) or (quiet_now and hour in range(low, high))
    return _report("late_night", ok, hour=hour, quiet_hours=list(quiet),
                   send_allowed=not quiet_now)


def crash_recovery(partial=None):
    """Dirty partial state (NaN/inf/strings/out-of-range) restores to bounds."""
    raw = partial if isinstance(partial, dict) else {}
    noisy = dict(raw, v=float("nan"), a=float("inf"), stress="bad",
                 trust=99.0, energy=-5.0)
    restored = state_of(noisy)
    ok = (restored["v"] == 0.0 and restored["a"] <= 1.0
          and restored["stress"] == BASELINE["stress"]
          and restored["trust"] == 1.0 and restored["energy"] == 0.0)
    return _report("crash_recovery", ok, restored=restored,
                   source_keys=len(raw))


def run_all():
    """Eight-scenario matrix (used by the test and a manual verification run)."""
    reports = [
        long_silence({"v": 0.9, "stress": 0.95, "trust": 0.9}),
        repeated_abuse(20),
        repeated_praise(20),
        relationship_breakdown({"trust": 0.8, "social": 0.7}),
        amnesia({"v": 9.0, "needs": {"belonging": 5.0}}),
        concurrent_users({"u1": {"v": 0.5}, "u2": {"v": -0.5}}),
        late_night(2),
        crash_recovery({"stress": 0.4}),
    ]
    return {"ok": all(report["ok"] for report in reports),
            "scenarios": reports}
