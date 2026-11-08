# -*- coding: utf-8 -*-
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from biocore_memory.event import chains as C


def _rows():
    return [
        {'turn': 183, 'ts': 200.0, 'text': '叶楠生日改成八月十八', 'vector': [1.0, 0.02, 0.0]},
        {'turn': 165, 'ts': 100.0, 'text': '叶楠生日是八月十六', 'vector': [0.98, 0.0, 0.0]},
        {'turn': 90, 'ts': 50.0, 'text': '今天下雨了', 'vector': [0.0, 0.0, 1.0]},
    ]


def test_cluster_orders_by_time_and_keeps_others_apart():
    clusters = C.cluster_candidates(_rows(), threshold=0.75)
    assert len(clusters) == 2
    chain = [c for c in clusters if len(c) == 2][0]
    assert [item['turn'] for item in chain] == [165, 183]


def test_render_marks_current_value_at_tail():
    clusters = C.cluster_candidates(_rows(), threshold=0.75)
    chain = [c for c in clusters if len(c) == 2][0]
    lines = C.render_cluster(chain)
    assert lines[0].startswith('【时间链｜第165轮/第183轮】')
    assert '当前值' in lines[-1] and '八月十八' in lines[-1]
    assert all('当前值' not in line for line in lines[1:-1])


def test_retraction_marks_old_value_and_is_cached():
    clusters = C.cluster_candidates(_rows(), threshold=0.75)
    chain = [c for c in clusters if len(c) == 2][0]
    calls = []

    def llm(prompt):
        calls.append(prompt)
        return '{"retract": true}'

    cache = {}
    flags = C.mark_retractions(chain, llm=llm, cache=cache)
    assert flags == {183: True}
    assert len(calls) == 1
    lines = C.render_cluster(chain, flags=flags)
    assert '已作废' in lines[1]
    assert '当前值' in lines[2]
    # cached: a second call must not hit the model again
    C.mark_retractions(chain, llm=llm, cache=cache)
    assert len(calls) == 1


def test_no_retraction_lists_both_sayings_when_close_in_time():
    rows = [{'turn': 279, 'ts': 1000.0, 'text': '地板浅灰色', 'vector': [1.0, 0.0]},
            {'turn': 317, 'ts': 1000.0 + 3600.0, 'text': '地板米色', 'vector': [0.99, 0.01]}]
    chain = C.cluster_candidates(rows, threshold=0.75)[0]
    flags = C.mark_retractions(chain, llm=lambda p: '{"retract": false}')
    lines = C.render_cluster(chain, flags=flags)
    text = '\n'.join(lines)
    assert '同一属性的两种说法' in text
    assert '已作废' not in text


def test_cluster_uses_vectors_only():
    called = []
    rows = [{'turn': 1, 'ts': 1.0, 'text': 'a', 'vector': [1.0, 0.0]},
            {'turn': 2, 'ts': 2.0, 'text': 'b', 'vector': [0.99, 0.0]}]
    C.cluster_candidates(rows)
    assert called == []


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('OK', name)
    print('all chain tests passed')
