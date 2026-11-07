# -*- coding: utf-8 -*-
"""Key normalization for the state layer.

The state is keyed by "主体·属性". Without a key list the extractor named the
same property differently every time -- "叶楠·生日" in one event, "叶楠·日历
日期" in the next -- so two facts about one property never met, and the state
stayed single valued for ever.

Extraction now receives the keys already in hand: the prompt asks the model to
reuse one whenever it can and to invent a key only when none fits. What comes
back is folded into the state with rolling.merge_state, so two values on one
key become one two-value row instead of two unrelated keys. Nothing here reads
the event text for meaning: the model decides, the rules below only repair the
cases a machine can repair without guessing (spacing, and a subject that is a
longer or shorter name for the same thing).
"""
from __future__ import annotations

import json
import re

from . import rolling

KNOWN_KEYS_LIMIT = 60
KEY_SEP = '·'
_SPACE = re.compile(r'\s+')


def clean(text):
    """Trim and drop whitespace; spacing is not part of a key name."""
    return _SPACE.sub('', str(text or '').strip())


def key_of(subject, attr):
    subject, attr = clean(subject), clean(attr)
    if not subject or not attr:
        return ''
    return '%s%s%s' % (subject, KEY_SEP, attr)


def split_key(key):
    subject, _, attr = str(key or '').partition(KEY_SEP)
    return clean(subject), clean(attr)


def key_counts(items):
    """How often each key was seen: facts count rows, a state counts its rows."""
    counts = {}
    if isinstance(items, dict):
        for key, item in items.items():
            if not key:
                continue
            history = (item or {}).get('history') if isinstance(item, dict) else None
            counts[str(key)] = 1 + len(history or [])
    else:
        for fact in items or []:
            if not isinstance(fact, dict):
                continue
            key = key_of(fact.get('subject'), fact.get('attr') or fact.get('attribute'))
            if key:
                counts[key] = counts.get(key, 0) + 1
    return counts


def rank_keys(items, limit=KNOWN_KEYS_LIMIT):
    """Keys ordered by frequency, then by name; capped at limit."""
    counts = key_counts(items)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [key for key, _ in ordered][:max(0, int(limit or 0))]


def _same_subject(left, right):
    """One name is the other plus a qualifier (合租房客厅地板 / 客厅地板)."""
    if not left or not right or left == right:
        return False
    short, long = (left, right) if len(left) <= len(right) else (right, left)
    return len(short) >= 2 and long.endswith(short)


def normalize_key(subject, attr, known=None):
    """Existing key this fact belongs to, or empty string when it needs a new one.

    Only two mechanical cases are unified: an exact key, and the same attribute
    under a subject that is a qualified form of an existing one. Anything that
    needs meaning is left to the model and to the key list in the prompt.
    """
    name = key_of(subject, attr)
    if not name:
        return ''
    names = [str(k) for k in (known or []) if k]
    if name in names:
        return name
    subject, attr = split_key(name)
    for key in names:
        known_subject, known_attr = split_key(key)
        if known_attr and known_attr == attr and _same_subject(subject, known_subject):
            return key
    return ''


def extract_prompt(events, known_keys=None, batch=None):
    """One extraction prompt: the records plus the keys already in hand."""
    rows = [e for e in (events or []) if isinstance(e, dict)]
    names = [str(k) for k in (known_keys or []) if k]
    if names:
        key_block = '\n'.join(names[:KNOWN_KEYS_LIMIT])
        key_rule = ('能从上面选到，就照抄已有的键，主体、属性一个字都不要改；'
                    '确实没有能对上的键，才新建。')
    else:
        key_block = '（暂无已有键，本次全部新建）'
        key_rule = '这一批还没有已有键，按原文说法新建。'
    blocks = []
    for ev in rows:
        blocks.append('【%d-%d】\n%s' % (int(ev.get('start') or 0), int(ev.get('end') or 0),
                                      str(ev.get('text') or '').strip()))
    return ('下面有 %d 段记录，每段以“【起止轮号】”开头。'
            '请从每段里抽取可以长期记住的事实：主体、属性、值。\n'
            '【已有键｜优先复用】\n%s\n'
            '规则：%s\n'
            '只输出 JSON 数组，元素形如 {"start": 起轮, "end": 止轮, "facts": '
            '[{"subject": "...", "attr": "...", "value": "..."}]}，不要解释。\n\n%s'
            % (len(rows), key_block, key_rule, '\n\n'.join(blocks)))


def advanced_keys(known_keys, facts):
    """Key list after folding a batch of facts: old keys first, new ones appended."""
    names = [str(k) for k in (known_keys or []) if k]
    for fact in facts or []:
        key = key_of(fact.get('subject'), fact.get('attr'))
        if key and key not in names:
            names.append(key)
    return names

def _ts_for(event, turn):
    """Timestamp of the turn, when the event carries its entries."""
    turn = int(turn or 0)
    for entry in event.get('entries') or []:
        if not isinstance(entry, dict):
            continue
        try:
            if int(entry.get('turn')) == turn:
                return float(entry.get('ts') or 0.0)
        except Exception:
            continue
    try:
        return float(event.get('ts') or 0.0)
    except Exception:
        return 0.0


def _pairs(data, chunk):
    """(event, raw fact) pairs out of one model answer."""
    if isinstance(data, dict):
        data = data.get('facts') or data.get('claims') or []
    by_span, loose = {}, []
    for item in data or []:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get('facts'), list):
            try:
                by_span[(int(item.get('start')), int(item.get('end')))] = item['facts']
            except Exception:
                continue
        elif item.get('subject'):
            loose.append(item)
    out = []
    for ev in chunk:
        span = (int(ev.get('start') or 0), int(ev.get('end') or 0))
        for fact in by_span.get(span) or []:
            if isinstance(fact, dict):
                out.append((ev, fact))
    for item in loose:
        turn = item.get('turn') or item.get('start')
        ev = chunk[0] if len(chunk) == 1 else None
        for row in chunk:
            try:
                if int(row.get('start') or 0) <= int(turn or 0) <= int(row.get('end') or 0):
                    ev = row
                    break
            except Exception:
                continue
        out.append((ev if ev is not None else (chunk[0] if chunk else {}), item))
    return out


def extract_facts(events, llm, known_keys=None, *, batch=8, stats=None):
    """Facts per event, extracted against the keys already in hand.

    Each batch is shown the current key list; a fact that can be attached to
    an existing key is written with that key's own subject and attribute,
    so the same property keeps landing on the same row across the whole
    history. Returns [{'subject', 'attr', 'value', 'turn', 'ts'}] in event
    order; without an llm the call degrades to no facts at all.
    """
    record = stats if isinstance(stats, dict) else {}
    record.update({'calls': 0, 'facts': 0, 'reused': 0, 'new': 0, 'keys': 0})
    names = [str(k) for k in (known_keys or []) if k]
    rows = [e for e in (events or []) if isinstance(e, dict)]
    if not llm or not rows:
        record['keys'] = len(names)
        return []
    size = max(1, int(batch or 8))
    out = []
    for start in range(0, len(rows), size):
        chunk = rows[start:start + size]
        record['calls'] += 1
        try:
            data = json.loads(llm(extract_prompt(chunk, names)) or '[]')
        except Exception:
            data = []
        for ev, raw in _pairs(data, chunk):
            subject = str(raw.get('subject') or '').strip()
            attr = str(raw.get('attr') or raw.get('attribute') or '').strip()
            value = str(raw.get('value') or '').strip()
            if not (subject and attr and value):
                continue
            try:
                turn = int(raw.get('turn') or ev.get('start') or 0)
            except Exception:
                turn = int(ev.get('start') or 0)
            name = normalize_key(subject, attr, names)
            if name:
                subject, attr = split_key(name)
                record['reused'] += 1
            else:
                record['new'] += 1
            out.append({'subject': subject, 'attr': attr, 'value': value,
                        'turn': turn, 'ts': _ts_for(ev, turn)})
            key = key_of(subject, attr)
            if key and key not in names:
                names.append(key)
    record['facts'] = len(out)
    record['keys'] = len(names)
    return out


def values_of(item):
    """Every value on a state row, with the turn it was said."""
    item = item if isinstance(item, dict) else {}
    turn = int(item.get('source_turn') or item.get('valid_at_turn') or 0)
    values = [v for v in (item.get('values') or [])
              if isinstance(v, dict) and v.get('value')]
    if not values:
        values = [{'value': str(v), 'turn': turn} for v in (item.get('coexist') or []) if v]
    if not values and item.get('value'):
        values = [{'value': item['value'], 'turn': turn}]
    return [{'value': str(v.get('value')), 'turn': int(v.get('turn') or turn)} for v in values]


def is_multi_value(item):
    return len(values_of(item)) > 1


def value_list(item):
    """Distinct values, first said first."""
    out = []
    for row in values_of(item):
        if row['value'] not in [v['value'] for v in out]:
            out.append(row)
    return out


def merge_fact_state(state, facts, turn=0):
    """Fold normalized facts into the state through rolling.merge_state.

    Two facts on one key are a conflict unless the model already superseded
    one of them, so the row keeps both values instead of two unrelated keys.
    """
    groups = {}
    for fact in facts or []:
        if not isinstance(fact, dict):
            continue
        key = key_of(fact.get('subject'), fact.get('attr'))
        value = str(fact.get('value') or '').strip()
        if not key or not value:
            continue
        try:
            said = int(fact.get('turn') or turn or 0)
        except Exception:
            said = int(turn or 0)
        groups.setdefault(key, []).append({'value': value, 'turn': said})
    if not groups:
        return rolling.merge_state(state or {}, {}, turn=turn)
    before = {key: value_list((state or {}).get(key)) for key in groups}
    incoming = {}
    for key, rows in groups.items():
        merged = list(before.get(key) or [])
        for row in rows:
            if row['value'] not in [v['value'] for v in merged]:
                merged.append(dict(row))
        last = rows[-1]
        incoming[key] = {'value': last['value'],
                         'status': 'conflict' if len(merged) > 1 else 'current',
                         'coexist': [v['value'] for v in merged] if len(merged) > 1 else [],
                         'source_turn': last['turn'], 'valid_at_turn': last['turn']}
    out = rolling.merge_state(state or {}, incoming, turn=turn)
    for key, rows in groups.items():
        item = out.get(key)
        if not isinstance(item, dict):
            continue
        values = list(before.get(key) or [])
        for row in rows:
            if row['value'] not in [v['value'] for v in values]:
                values.append(dict(row))
        item['values'] = values
        if item.get('status') == 'conflict':
            item['value'] = ' / '.join(item.get('coexist') or
                                      [v['value'] for v in values])
    return out


def state_line(key, item, max_values=4):
    """One 【状态】 line: value (turn) / value (turn), and whether it is settled."""
    values = value_list(item)[:max(1, int(max_values or 1))]
    if not values:
        return ''
    body = ' / '.join('%s（第%d轮）' % (v['value'], int(v['turn'] or 0)) for v in values)
    if is_multi_value(item):
        tail = '，未确定（%d 种说法并存）' % len(value_list(item))
    else:
        tail = '，已确定'
    return '【状态】%s：%s%s' % (key, body, tail)


def state_lines_for(event, state, max_lines=3):
    """【状态】 lines for the multi-value keys this event actually mentions."""
    if not isinstance(event, dict) or not isinstance(state, dict):
        return []
    text = str(event.get('overview') or '')
    for entry in event.get('entries') or []:
        if isinstance(entry, dict):
            text += ' ' + str(entry.get('text') or '')
    lines = []
    for key in sorted(state):
        item = state.get(key) or {}
        subject = split_key(key)[0]
        if not subject or subject not in text:
            continue
        if not is_multi_value(item):
            continue
        line = state_line(key, item)
        if line:
            lines.append(line)
    return lines[:max(0, int(max_lines or 0))]

def prepend_state_lines(lines, event, state, max_lines=3):
    """Put the 【状态】 lines on top of an already rendered block.

    Kept separate from the event renderer so the block keeps its own shape:
    the state line is added only when the hit mentions a multi-value key.
    """
    head = state_lines_for(event, state, max_lines=max_lines)
    if not head:
        return list(lines or [])
    return head + list(lines or [])

