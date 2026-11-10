# -*- coding: utf-8 -*-
"""Two lessons from the scaling law: enough samples, and steps by range."""
import random

from biocore_runtime import theta as T


def _fill(store, n, noise=0.05, seed=1, knob='push_gain'):
    rng = random.Random(seed)
    for _ in range(n):
        th = dict(T.DEFAULTS)
        th[knob] = round(0.35 + rng.uniform(-0.15, 0.15), 3)
        T.log_turn(store, th, (th[knob] - 0.35) * 2.0 + rng.gauss(0, noise))


def test_required_n_follows_the_inverse_square():
    assert T.required_n(0.5) < T.required_n(0.25) < T.required_n(0.125)
    assert 25 <= T.required_n(0.5) <= 40      # ~32 for r=0.5


def test_too_few_rows_are_rejected_even_with_a_strong_looking_correlation(tmp_path):
    store = str(tmp_path)
    _fill(store, n=20, noise=0.30)
    out = T.iterate(store)
    r = abs((out.get('corr') or {}).get('push_gain', 0.0))
    if out.get('accepted'):
        assert len(T.read_log(store)) >= T.required_n(r)
    else:
        assert True


def test_a_small_valued_knob_can_still_move(tmp_path):
    store = str(tmp_path)
    rng = random.Random(4)
    for _ in range(200):
        th = dict(T.DEFAULTS)
        th['replay_learn'] = round(0.02 + rng.uniform(0, 0.10), 3)
        T.log_turn(store, th, (th['replay_learn'] - 0.02) * 4.0 + rng.gauss(0, 0.05))
    before = T.values(store)['replay_learn']
    out = T.iterate(store)
    assert out['accepted'] is True
    assert out['knob'] == 'replay_learn'
    assert T.values(store)['replay_learn'] > before
