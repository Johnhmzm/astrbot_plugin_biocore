# -*- coding: utf-8 -*-
"""Rolling state: events processed in time order, each one may update a state.

The state is a plain dict: "主体·属性" -> {"value", "status", "note"}.
Status is "current" or "conflict"; the model decides whether a new saying
supersedes the old one or merely coexists with it. Nothing here carries a
lexicon; the prompt states the semantic test and nothing else.
"""
from __future__ import annotations

import copy
import json

from .events import enabled

MAX_STATE_KEYS = 40


def _state_lines(state):
    lines = []
    for key in sorted(state or {}):
        item = state[key] or {}
        lines.append('%s = %s（%s）%s' % (key, item.get('value'), item.get('status') or 'current',
                                          ('，' + str(item.get('note'))) if item.get('note') else ''))
    if not lines:
        lines.append('（空）')
    return lines


def rolling_prompt(state, event):
    start = int(event.get('start') or 0)
    end = int(event.get('end') or 0)
    return ('下面是目前已知的状态，以及新的一段对话。\n'
            '【当前状态】\n%s\n\n'
            '【新对话｜第%d-%d轮】\n%s\n\n'
            '键的写法必须复用【当前状态】里已有的键；只有记录里确实没有对应键时才新建，'
            '新建的键用“主体·属性”两段式，主体写人名或物件名。'
            '如果需要更新状态，就输出新状态；对每处变化说明是【取代】还是【并存】。'
            '判断取代的依据：新说法是否让旧说法不再成立（核对过、纠正过）。'
            '只是又一个不同说法、没有让旧说法失效时，标为并存。'
            '同时给出本事件的一句概览（不超过 30 字，写谁/什么/什么值）。'
            '只输出 JSON：{"state": {"主体·属性": {"value": "...", "status": "current 或 conflict", '
            '"note": "改自X / 多种说法"}}, "overview": "..."}，不要解释。'
            % ('\n'.join(_state_lines(state)), start, end,
               str(event.get('text') or '').strip()))


def normalize_state(raw):
    out = {}
    for key, item in (raw or {}).items():
        if not isinstance(item, dict):
            continue
        value = str(item.get('value') or '').strip()
        if not value:
            continue
        status = str(item.get('status') or 'current').strip().lower()
        if status not in ('current', 'conflict'):
            status = 'current'
        out[str(key)] = {'value': value, 'status': status,
                         'note': str(item.get('note') or '').strip()}
    return out


def summarize_rolling(events, *, llm=None, flags=None, stats=None, cache=None):
    """One pass in time order; returns {event_id: {'overview', 'state'}}."""
    record = stats if isinstance(stats, dict) else {}
    record.update({'calls': 0, 'events': 0, 'keys': 0, 'conflicts': 0})
    if not enabled(flags) or not llm:
        return {}
    rows = [e for e in (events or []) if isinstance(e, dict)]
    rows.sort(key=lambda e: (int(e.get('start') or 0), int(e.get('end') or 0)))
    state, out = {}, {}
    for ev in rows:
        record['calls'] += 1
        try:
            data = json.loads(llm(rolling_prompt(state, ev)) or '{}')
        except Exception:
            data = {}
        if isinstance(data.get('state'), dict) and data['state']:
            state = normalize_state(data['state'])
        else:
            state = normalize_state(state)
        if len(state) > MAX_STATE_KEYS:
            keep = sorted(state)[:MAX_STATE_KEYS]
            state = {k: state[k] for k in keep}
        out[ev.get('event_id')] = {'overview': str(data.get('overview') or '').strip(),
                                   'state': copy.deepcopy(state)}
        record['events'] += 1
    record['keys'] = len(state)
    record['conflicts'] = sum(1 for item in state.values() if item.get('status') == 'conflict')
    return out


def state_entries_for(event, state):
    """State keys whose subject shows up in this event's text."""
    text = str(event.get('text') or '')
    picked = []
    for key in sorted(state or {}):
        subject = key.split('·')[0]
        if subject and subject in text:
            item = state[key]
            picked.append('%s = %s（%s）%s' % (key, item.get('value'), item.get('status'),
                                               ('，' + item['note']) if item.get('note') else ''))
    return picked


def _norm_item(raw, turn=0):
    item = raw if isinstance(raw, dict) else {}
    value = str(item.get('value') or '').strip()
    status = str(item.get('status') or 'current').strip().lower()
    if status not in ('current', 'conflict'):
        status = 'current'
    coexist = [str(x) for x in (item.get('coexist') or []) if str(x).strip()]
    return {'value': value,
            'status': status,
            'superseded_by': str(item.get('superseded_by') or '').strip() or None,
            'coexist': coexist,
            'valid_at_turn': int(item.get('valid_at_turn') or turn or 0),
            'source_turn': int(item.get('source_turn') or turn or 0),
            'hits': int(item.get('hits') or 0),
            'last_hit': int(item.get('last_hit') or 0),
            'note': str(item.get('note') or '').strip()}


def merge_state(old, incoming, turn=0):
    """Fold the model's new state into the stored one.

    A superseded value is never deleted: the old row keeps its value and gets
    superseded_by pointing at the new one. Coexisting values list each other.
    """
    out = {key: _norm_item(item, turn) for key, item in (old or {}).items()}
    for key, raw in (incoming or {}).items():
        if not isinstance(raw, dict):
            continue
        item = _norm_item(raw, turn)
        if not item['value']:
            continue
        prev = out.get(key)
        if prev is None:
            out[key] = item
            continue
        prev_hits = prev.get('hits') or 0
        prev_last = prev.get('last_hit') or 0
        if item['status'] == 'conflict':
            values = []
            for value in (prev.get('coexist') or []) + [prev['value']] + \
                    (item.get('coexist') or []) + [item['value']]:
                if value and value not in values:
                    values.append(value)
            current = ' / '.join(values)
            merged = dict(item)
            merged['value'] = current
            merged['status'] = 'conflict'
            merged['coexist'] = values
            merged['superseded_by'] = None
        else:
            superseded = set(prev.get('coexist') or [])
            merged = dict(item)
            if prev['value'] and prev['value'] != item['value']:
                # the model judged this a replacement: keep the old row
                out[key] = dict(prev)
                out[key]['superseded_by'] = item['value']
                out[key]['status'] = 'current' if prev['status'] == 'conflict' else prev['status']
                merged['coexist'] = []
                merged['superseded_by'] = None
            else:
                merged['coexist'] = sorted(superseded)
        merged['hits'] = prev_hits
        merged['last_hit'] = prev_last
        history = list(prev.get('history') or [])
        history.append({'turn': int(turn or merged.get('source_turn') or 0),
                        'value': merged['value'], 'status': merged['status'],
                        'coexist': list(merged.get('coexist') or [])})
        merged['history'] = history[-20:]
        out[key] = merged
    return out


def bump_hits(state, keys, turn=0):
    for key in keys or []:
        item = (state or {}).get(key)
        if isinstance(item, dict):
            item['hits'] = int(item.get('hits') or 0) + 1
            item['last_hit'] = int(turn or item.get('last_hit') or 0)
    return state


def state_at(item, as_of=None):
    """Value this state held at as_of (turn); None = latest."""
    if not isinstance(item, dict):
        return item
    history = item.get("history") or []
    if as_of is None or not history:
        return item
    current = None
    for row in sorted(history, key=lambda h: int(h.get("turn") or 0)):
        if int(row.get("turn") or 0) <= int(as_of):
            current = row
        else:
            break
    if current is None:
        return {"value": "", "status": "current", "superseded_by": None, "coexist": []}
    out = dict(item)
    out["value"] = current.get("value") or ""
    out["status"] = current.get("status") or "current"
    out["coexist"] = list(current.get("coexist") or [])
    return out


def history_of(item):
    return list((item or {}).get("history") or [])
