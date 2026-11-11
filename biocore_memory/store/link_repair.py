# -*- coding: utf-8 -*-
"""修复条目与事件之间的链接。

条目和事件本来是两本账：条目存句子，事件存它的成员快照。
只要条目的 turn 或 event_id 没写上，这两本账就对不上——按事件取值、按轮次取值、
按事件做价值筛选，全部静默失效（今晚就是在这里卡住的）。

这个函数把老数据补回去：轮次从位置推，event_id 用事件里那份成员快照反查。
"""
from __future__ import annotations

from typing import Dict, List


def _index_events(events) -> Dict[str, str]:
    """条目 id → 事件 id，来自每个事件自带的那份成员快照。"""
    out: Dict[str, str] = {}
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        eid = str(ev.get('event_id') or '')
        if not eid:
            continue
        for row in ev.get('entries') or []:
            if isinstance(row, dict) and row.get('id'):
                out[str(row['id'])] = eid
    return out


def repair(entries, events) -> Dict[str, int]:
    """就地修补；返回改了哪几类、各多少条。"""
    report = {'turn': 0, 'event_id': 0, 'total': 0}
    if not isinstance(entries, list):
        return report
    by_entry = _index_events(events)
    for index, row in enumerate(entries, 1):
        if not isinstance(row, dict):
            continue
        report['total'] += 1
        try:
            turn = int(row.get('turn') or 0)
        except Exception:
            turn = 0
        if turn <= 0:
            row['turn'] = index
            report['turn'] += 1
        if not str(row.get('event_id') or ''):
            eid = by_entry.get(str(row.get('id') or ''))
            if eid:
                row['event_id'] = eid
                report['event_id'] += 1
    return report


def broken_counts(entries, events) -> Dict[str, int]:
    """修复前先量一下：多少条缺轮次、多少条缺事件、多少条对不上事件。"""
    if not isinstance(entries, list):
        return {'no_turn': 0, 'no_event': 0, 'dangling': 0, 'total': 0}
    known = {str(ev.get('event_id') or '') for ev in (events or []) if isinstance(ev, dict)}
    no_turn = no_event = dangling = 0
    for row in entries:
        if not isinstance(row, dict):
            continue
        try:
            turn = int(row.get('turn') or 0)
        except Exception:
            turn = 0
        if turn <= 0:
            no_turn += 1
        eid = str(row.get('event_id') or '')
        if not eid:
            no_event += 1
        elif known and eid not in known:
            dangling += 1
    return {'no_turn': no_turn, 'no_event': no_event, 'dangling': dangling,
            'total': len([r for r in entries if isinstance(r, dict)])}
