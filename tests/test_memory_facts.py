# -*- coding: utf-8 -*-
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from biocore_memory.event import facts as F


def _ev(start, end, text):
    return {'start': start, 'end': end, 'text': text}


def test_extract_facts_cached_by_event_hash():
    calls = []

    def llm(prompt):
        calls.append(prompt)
        return ('[{"start": 1, "end": 2, "facts": ['
                 '{"subject": "甲", "attribute": "属性", "value": "值一", "time": "1"}]}]')

    cache = {}
    stats = {}
    rows = [ _ev(1, 2, '甲说了值一') ]
    F.extract_facts(rows, llm=llm, cache=cache, stats=stats)
    assert len(calls) == 1 and stats['miss'] == 1
    stats2 = {}
    F.extract_facts(rows, llm=llm, cache=cache, stats=stats2)
    assert len(calls) == 1 and stats2['hit'] == 1 and stats2['calls'] == 0


def test_new_value_invalidates_old_only_when_model_says_so():
    rows = [{'subject': '甲', 'attribute': '属性', 'value': '值一', 'valid_at': 't1',
             'invalid_at': None, 'turn': 1},
            {'subject': '甲', 'attribute': '属性', 'value': '值二', 'valid_at': 't2',
             'invalid_at': None, 'turn': 2}]
    F.attach_invalid(rows, llm=lambda p: '{"invalidates": true}', cache={})
    assert rows[0]['invalid_at'] == 't2'
    assert rows[1]['invalid_at'] is None


def test_unjudgeable_keeps_both_rows_valid():
    rows = [{'subject': '甲', 'attribute': '属性', 'value': '值一', 'valid_at': 't1',
             'invalid_at': None, 'turn': 1},
            {'subject': '甲', 'attribute': '属性', 'value': '值二', 'valid_at': 't2',
             'invalid_at': None, 'turn': 2}]
    F.attach_invalid(rows, llm=lambda p: '{"invalidates": false}', cache={})
    assert rows[0]['invalid_at'] is None and rows[1]['invalid_at'] is None
    text = '\n'.join(F.render_table(rows))
    assert '均有效' in text


def test_render_unique_and_dead_rows():
    rows = [{'subject': '甲', 'attribute': '属性', 'value': '旧', 'valid_at': 't1',
             'invalid_at': 't2', 'turn': 1},
            {'subject': '甲', 'attribute': '属性', 'value': '新', 'valid_at': 't2',
             'invalid_at': None, 'turn': 2}]
    lines = F.render_table(rows)
    assert lines[0] == '甲·属性：新（t2）'
    assert lines[1] == '（曾为旧，时间t1，已失效）'


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('OK', name)
    print('all fact tests passed')
