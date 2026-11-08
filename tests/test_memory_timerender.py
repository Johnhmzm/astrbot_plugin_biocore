# -*- coding: utf-8 -*-
import sys
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from biocore_memory.event import timerender as T

TS = datetime(2026, 5, 20, 10, 0).timestamp()   # 周三


def test_yesterday_and_day_before():
    out = T.normalize_relative_time('前天他说要搬家', TS)
    assert '2026-05-18' in out and '原文：前天' in out


def test_last_friday():
    out = T.normalize_relative_time('上周五借了相机', TS)
    assert '2026-05-15' in out and '原文：上周五' in out


def test_next_tuesday():
    out = T.normalize_relative_time('下周二还相机', TS)
    assert '2026-05-26' in out and '原文：下周二' in out


def test_days_ago():
    out = T.normalize_relative_time('3天前说的', TS)
    assert '2026-05-17' in out


def test_conflict_line_is_mandatory():
    state = {'客厅地板·颜色': {'value': '米色', 'status': 'conflict', 'valid_at_turn': 317,
                                'coexist': ['浅灰', '米色']},
             '用户·称呼': {'value': '夏夏', 'status': 'current', 'coexist': []}}
    lines = T.conflict_lines(state)
    assert len(lines) == 1
    assert lines[0].startswith('【注意】客厅地板·颜色')
    assert '浅灰' in lines[0] and '米色' in lines[0]
    assert '需向用户确认' in lines[0]


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('OK', name)
    print('all timerender tests passed')
