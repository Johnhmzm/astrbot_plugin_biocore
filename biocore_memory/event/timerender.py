# -*- coding: utf-8 -*-
"""Pure helpers for the note pipeline: relative-time normalisation and the
mandatory conflict banner. No model calls, no lexicon beyond the time words
the spec names.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

_WEEK = {'一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6, '天': 6}
_DAY_WORDS = (('大前天', 3), ('前天', 2), ('昨天', 1), ('今天', 0), ('后天', -1), ('明天', -2))


def _fmt(moment):
    return moment.strftime('%Y-%m-%d')


def _replace(text, phrase, day):
    return text.replace(phrase, '%s（原文：%s）' % (_fmt(day), phrase))


def normalize_relative_time(text, ts):
    """Rewrite relative day words into absolute dates anchored at ts."""
    raw = str(text or '')
    try:
        base = datetime.fromtimestamp(float(ts))
    except Exception:
        return raw
    out = raw
    for phrase, back in _DAY_WORDS:
        if phrase in out:
            out = _replace(out, phrase, base - timedelta(days=back))
    out = re.sub(r'(\d+)\s*天前', lambda m: '%s（原文：%s天前）' % (
        _fmt(base - timedelta(days=int(m.group(1)))), m.group(1)), out)
    # 上周X / 本周X / 下周X
    def week(match):
        which, weekday = match.group(1), match.group(2)
        target = _WEEK.get(weekday)
        if target is None:
            return match.group(0)
        monday = base - timedelta(days=base.weekday())
        offset = {'上周': -7, '本周': 0, '这周': 0, '下周': 7}.get(which, 0)
        day = monday + timedelta(days=offset + target)
        return '%s（原文：%s）' % (_fmt(day), match.group(0))
    out = re.sub(r'(上周|本周|这周|下周)([一二三四五六日天])', week, out)
    return out


def conflict_lines(state):
    """Unconditional banner for every attribute holding more than one value."""
    lines = []
    for key, item in sorted((state or {}).items()):
        if not isinstance(item, dict):
            continue
        values = []
        for value in (item.get('coexist') or []) + [item.get('value')]:
            value = str(value or '').strip()
            if value and value not in values:
                values.append(value)
        if len(values) < 2:
            continue
        subject = key.split('·')[0]
        shown = ' / '.join('%s（第%s轮）' % (value, item.get('valid_at_turn') or '?')
                           for value in values)
        lines.append('【注意】%s 有两种说法：%s，记录不足以确定，需向用户确认'
                     % (key, shown))
    return lines
