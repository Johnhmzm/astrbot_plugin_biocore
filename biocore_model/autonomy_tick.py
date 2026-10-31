# -*- coding: utf-8 -*-
"""L4: autonomy tick (interaction layer). Dependency-injected; no main import."""
from __future__ import annotations


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, float(v)))


def _check_window(acc, now, snapshot=None):
    snap = snapshot if isinstance(snapshot, dict) else {}
    sleep = snap.get('sleep') if isinstance(snap.get('sleep'), dict) else {}
    if sleep.get('sleeping'):
        return False, 'sleeping'
    return True, ''


def _compute_silence(acc, now):
    try:
        last = float(acc.get('last_user_msg_ts', 0.0) or 0.0)
        current = float(now)
        hours = max(0.0, (current - last) / 3600.0) if last > 0 else 0.0
    except Exception:
        hours = 0.0
    return {'hours': round(hours, 3)}


def _compute_motive(acc, parts):
    try:
        from . import autonomy_model as am
    except Exception:
        from biocore_model import autonomy_model as am
    motive = am.motive_view(0.0, acc.get('frustration', 0), True, 'secure',
                            float(acc.get('self_blame', 0.0) or 0.0))
    drift = am.drift_value(parts or {}) * float(motive.get('total_mult', 1.0))
    return {'drift': round(drift, 4), 'motive': motive}


def _decide(acc, core, now, snapshot=None):
    allowed, reason = _check_window(acc, now, snapshot)
    if not allowed:
        return {'action': 'skip', 'reason': reason}
    return {'action': 'send', 'reason': ''}


def _build_text(core, acc, deps):
    builder = getattr(deps, 'build_text', None)
    if builder is not None:
        try:
            return str(builder(core, acc) or '')
        except Exception:
            return ''
    return ''


def _record(acc, deps, now, result):
    acc['last_tick_ts'] = float(now)
    # UI and step both need theta; an accumulator written before theta existed
    # (or by a hook that dropped it) must not lose the trigger threshold.
    try:
        acc['theta'] = float(acc.get('theta', 0.55) or 0.55)
    except Exception:
        acc['theta'] = 0.55
    try:
        acc['V'] = max(0.0, float(acc.get('V', 0.0) or 0.0))
    except Exception:
        acc['V'] = 0.0
    save = getattr(deps, 'save_acc', None)
    if save is not None:
        try:
            save(acc)
        except Exception:
            pass
    return result


def tick_once(deps, now):
    """One L4 tick; returns {sent, skipped, blocked, reason}.

    V evolution is session-independent: step/drift/decay run even when there is
    no private session (only SENDING needs a session). This fixes the frozen
    V=0.155 case where a missing last_umo skipped the whole tick.
    """
    result = {'sent': [], 'skipped': [], 'blocked': [], 'reason': ''}
    try:
        acc = dict(deps.load_acc() or {})
    except Exception:
        return result
    try:
        sessions = list(deps.list_sessions() or [])
    except Exception:
        sessions = []
    # Pick a core for state/parts even without a session (first session core,
    # then any live core injected by the caller).
    state_core = None
    if sessions:
        try:
            state_core = deps.get_core(str((sessions[0] or {}).get('umo') or ''))
        except Exception:
            state_core = None
    if state_core is None:
        _any = getattr(deps, "any_core", None)
        if callable(_any):
            try:
                state_core = _any()
            except Exception:
                state_core = None
    snapshot = {}
    try:
        if state_core is not None and hasattr(deps, "snapshot"):
            snapshot = deps.snapshot(state_core) or {}
    except Exception:
        snapshot = {}
    decision = _decide(acc, state_core, now, snapshot)
    silence = _compute_silence(acc, now)
    motive = _compute_motive(acc, (snapshot or {}).get('parts') or acc.get('parts') or {})
    params = {}
    try:
        _params = getattr(deps, "params", None)
        if callable(_params):
            params = dict(_params() or {})
    except Exception:
        params = {}
    theta = float(params.get('theta') or acc.get('theta', 0.55) or 0.55)
    acc['theta'] = theta
    try:
        step = deps.step(float(acc.get('V', 0.0) or 0.0), motive['drift'], theta)
    except Exception:
        step = {'V': float(acc.get('V', 0.0) or 0.0), 'fire': False}
    acc['V'] = float(step.get('V', 0.0) or 0.0)
    acc['ticks_since_fire'] = 0 if step.get('fire') else int(acc.get('ticks_since_fire', 0) or 0) + 1
    if not sessions:
        result['reason'] = 'no_session'
        return _record(acc, deps, now, result)
    if decision['action'] != 'send':
        for session in sessions:
            umo = str((session or {}).get('umo') or '')
            result['skipped'].append(umo)
        result['reason'] = decision['reason'] or 'not_ready'
        return _record(acc, deps, now, result)
    for session in sessions:
        umo = str((session or {}).get('umo') or '')
        try:
            core = deps.get_core(umo)
        except Exception:
            core = None
        if core is None:
            result['skipped'].append(umo)
            continue
        if not step.get('fire'):
            result['skipped'].append(umo)
            result['reason'] = 'not_ready'
            continue
        try:
            allowed, why = deps.gate(core, acc, silence, now)
        except Exception:
            allowed, why = False, 'gate_error'
        if not allowed:
            result['blocked'].append(umo)
            result['reason'] = str(why)
            continue
        text = _build_text(core, acc, deps)
        if not text:
            result['blocked'].append(umo)
            result['reason'] = 'no_text'
            continue
        try:
            ok = deps.send_text(umo, text)
        except Exception:
            ok = False
        if ok:
            result['sent'].append(umo)
            acc['V'] = 0.0
            acc['last_sent_ts'] = float(now)
        else:
            result['blocked'].append(umo)
            result['reason'] = 'send_error'
    return _record(acc, deps, now, result)
