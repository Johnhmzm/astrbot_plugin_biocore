# -*- coding: utf-8 -*-
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from biocore_memory.event import activation as A


def test_base_activation_decays_with_age():
    now = 1000.0
    fresh = A.actr_activation([now - 10], now)
    old = A.actr_activation([now - 500], now)
    assert fresh > old > 0


def test_base_activation_grows_with_hits():
    now = 1000.0
    one = A.actr_activation([now - 10], now)
    three = A.actr_activation([now - 10, now - 11, now - 12], now)
    assert three > one
    assert A.actr_activation([], now) == 0.0


def test_bump_hits_updates_and_persists():
    ev = {'event_id': 'a'}
    A.bump_hits(ev, 100.0)
    A.bump_hits(ev, 200.0)
    assert ev['hits'] == 2 and ev['last_hit'] == 200.0
    assert ev['hits_ts'] == [100.0, 200.0]


def test_time_proximity_bounds():
    assert abs(A.time_proximity(190, 183, span=100) - 0.93) < 1e-9
    assert A.time_proximity(183, 183, span=100) == 1.0
    assert A.time_proximity(1000, 183, span=100) == 0.0
    assert A.time_proximity(None, 183, span=100) == 0.0


def test_specificity_bounds():
    assert A.specificity([1.0, 0.0], [1.0, 0.0]) == 0.0
    assert A.specificity([1.0, 0.0], [0.0, 1.0]) == 1.0
    assert 0.0 <= A.specificity([1.0, 0.0], [0.7, 0.7]) <= 1.0
    assert A.specificity([], [1.0, 0.0]) == 0.0


def test_score_weights_are_used():
    ev = {'vector': [1.0, 0.0], 'end': 183, 'hits_ts': [], 'event_id': 'a'}
    score, base, cos, tp, spec = A.score(ev, [1.0, 0.0], as_of=183, span=100,
                                          centroid=[1.0, 0.0])
    assert abs(score - (0.5 * 0 + 0.3 * 1.0 + 0.1 * 1.0 + 0.1 * 0.0)) < 1e-9




def test_rrf_is_scale_free():
    # a channel with huge negative scores must not dominate: only rank matters
    ch1 = ['a', 'b', 'c']
    ch2 = ['c', 'a', 'b']
    fused = A.rrf_merge([ch1, ch2])
    assert set(fused) == {'a', 'b', 'c'}
    assert fused[0] == 'a'          # a is 1st and 2nd -> highest


def test_rrf_skips_missing_channel():
    only_one = A.rrf_merge([['a', 'b'], []])
    assert only_one == ['a', 'b']
    # docs only present in the empty channel get no score at all
    assert 'z' not in only_one


def test_rrf_scores_keep_event_objects():
    events = [{'event_id': 'a'}, {'event_id': 'b'}]
    scored = A.rrf_scores([['b', 'a'], ['b']], events)
    assert [ev['event_id'] for _s, ev in scored] == ['b', 'a']

if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('OK', name)
    print('all activation tests passed')
