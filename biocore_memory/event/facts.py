# -*- coding: utf-8 -*-
"""Bi-temporal fact rows: (subject, attribute, value, valid_at, invalid_at, turn).

A new value never deletes the old row; a row gets invalid_at only when the
model judges that a later message declares the old one no longer holds. When
that cannot be judged, both rows stay valid. Extraction and verdicts are
cached by content hash, so changing logic does not force a full recompute.
"""
from __future__ import annotations

import hashlib
import json

FACT_PROMPT = ('下面有 %d 段记录，每段以“【起止轮号】”开头。请从每段里抽取可以长期记住的事实，'
               '每条事实给出：主体、属性、值、时间（时间用原文里出现的说法；原文没有就写轮号）。'
               '只抽记录里出现过的事实，不判断真假，不做合并。'
               '只输出 JSON 数组，元素形如 {"start": 起轮, "end": 止轮, "facts": '
               '[{"subject": "...", "attribute": "...", "value": "...", "time": "..."}]}，不要解释。')

RETRACT_PROMPT = ('同一主体同一属性的先后两条事实如下。判断后一条是否声明前一条不再成立：'
                  '只有后一条让前一条失效才算；无法判断就返回 false。'
                  '只输出 JSON：{"invalidates": true 或 false}。\n\n'
                  '【前一条】%s = %s（第%d轮）\n【后一条】%s = %s（第%d轮）')


def _h(text, tag=''):
    return hashlib.sha1(('%s||%s' % (tag, text)).encode('utf-8')).hexdigest()[:16]


def _blocks(rows):
    out = []
    for ev in rows:
        out.append('【%d-%d】\n%s' % (int(ev.get('start') or 0), int(ev.get('end') or 0),
                                     str(ev.get('text') or '').strip()))
    return out


def extract_facts(rows, *, llm=None, cache=None, flags=None, stats=None):
    """One batched call per uncached batch; each event cached by its own hash."""
    record = stats if isinstance(stats, dict) else {}
    record.update({'calls': 0, 'hit': 0, 'miss': 0, 'facts': 0})
    cache = cache if isinstance(cache, dict) else {}
    if not llm:
        return []
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    todo, per_event = [], {}
    for ev in rows:
        key = _h(str(ev.get('text') or ''), 'fact')
        if key in cache:
            record['hit'] += 1
            per_event[id(ev)] = cache[key]
        else:
            todo.append(ev)
    for start in range(0, len(todo), 8):
        batch = todo[start:start + 8]
        record['calls'] += 1
        record['miss'] += len(batch)
        prompt = (FACT_PROMPT % len(batch)) + '\n\n' + '\n\n'.join(_blocks(batch))
        try:
            data = json.loads(llm(prompt) or '[]')
        except Exception:
            data = None
        by_span = {}
        for item in (data or []):
            if not isinstance(item, dict):
                continue
            try:
                span = (int(item.get('start')), int(item.get('end')))
            except Exception:
                continue
            by_span[span] = item.get('facts') or []
        for ev in batch:
            span = (int(ev.get('start') or 0), int(ev.get('end') or 0))
            facts = []
            for fact in by_span.get(span) or []:
                if not isinstance(fact, dict):
                    continue
                subject = str(fact.get('subject') or '').strip()
                attribute = str(fact.get('attribute') or '').strip()
                value = str(fact.get('value') or '').strip()
                if not (subject and attribute and value):
                    continue
                facts.append({'subject': subject, 'attribute': attribute, 'value': value,
                              'valid_at': str(fact.get('time') or span[0]),
                              'invalid_at': None, 'turn': span[0]})
            per_event[id(ev)] = facts
            cache[_h(str(ev.get('text') or ''), 'fact')] = facts
    out = []
    for ev in rows:
        out.extend(per_event.get(id(ev)) or [])
    record['facts'] = len(out)
    return out


def attach_invalid(rows, *, llm=None, cache=None, stats=None):
    """Model verdict per adjacent pair; only then does the old row get invalid_at."""
    record = stats if isinstance(stats, dict) else {}
    record.update({'retract_calls': 0, 'invalidated': 0})
    cache = cache if isinstance(cache, dict) else {}
    groups = {}
    for row in rows or []:
        groups.setdefault((row['subject'], row['attribute']), []).append(row)
    for _key, group in groups.items():
        group.sort(key=lambda r: int(r.get('turn') or 0))
        for index in range(1, len(group)):
            earlier, later = group[index - 1], group[index]
            if earlier.get('invalid_at'):
                continue
            key = _h('%s|%s|%s|%s' % (earlier['value'], earlier['turn'],
                                      later['value'], later['turn']), 'retract')
            if key not in cache and llm is not None:
                record['retract_calls'] += 1
                try:
                    data = json.loads(llm(RETRACT_PROMPT % (
                        earlier['attribute'], earlier['value'], int(earlier['turn']),
                        later['attribute'], later['value'], int(later['turn']))) or '{}')
                    cache[key] = bool((data or {}).get('invalidates'))
                except Exception:
                    cache[key] = False
            if cache.get(key):
                earlier['invalid_at'] = later.get('valid_at') or later.get('turn')
                record['invalidated'] += 1
    return rows


def render_table(rows, *, max_facts=8):
    """Valid rows first; each dead row gets one 已失效 line."""
    groups = {}
    for row in rows or []:
        groups.setdefault((row['subject'], row['attribute']), []).append(row)
    lines, shown = [], 0
    for key in sorted(groups, key=lambda k: min(int(r.get('turn') or 0) for r in groups[k])):
        if shown >= max_facts:
            break
        group = sorted(groups[key], key=lambda r: int(r.get('turn') or 0))
        valid = [r for r in group if not r.get('invalid_at')]
        dead = [r for r in group if r.get('invalid_at')]
        head = '%s·%s：' % key
        if len(valid) == 1:
            line = head + '%s（%s）' % (valid[0]['value'], valid[0].get('valid_at'))
        elif len(valid) > 1:
            line = head + ' / '.join('%s（%s）' % (r['value'], r.get('valid_at')) for r in valid)
            line += '，均有效'
        else:
            line = head + '（无有效值）'
        lines.append(line)
        for row in dead:
            lines.append('（曾为%s，时间%s，已失效）' % (row['value'], row.get('valid_at')))
        shown += 1
    return lines
