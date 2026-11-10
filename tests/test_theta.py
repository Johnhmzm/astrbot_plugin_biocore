# -*- coding: utf-8 -*-
"""The parameter loop: one vector, held-out validation, rollback."""
import random

from biocore_runtime import theta as T


def _fill(store, fn, n=40, noise=0.05, seed=1):
    rng = random.Random(seed)
    for _ in range(n):
        g = 0.35 + rng.uniform(-0.15, 0.15)
        th = dict(T.DEFAULTS)
        th['push_gain'] = round(g, 3)
        T.log_turn(store, th, fn(g) + rng.gauss(0, noise))


def test_accepts_a_knob_that_tracks_the_grade(tmp_path):
    _fill(str(tmp_path), lambda g: (g - 0.35) * 2.0)
    out = T.iterate(str(tmp_path))
    assert out['accepted'] is True
    assert out['knob'] == 'push_gain'
    assert T.values(str(tmp_path))['push_gain'] > T.DEFAULTS['push_gain']


def test_rejects_when_the_grade_is_noise(tmp_path):
    _fill(str(tmp_path), lambda g: 0.5, noise=0.30, seed=3)
    out = T.iterate(str(tmp_path))
    assert out['accepted'] is False


def test_refuses_with_too_few_rows(tmp_path):
    _fill(str(tmp_path), lambda g: 0.5, n=5)
    out = T.iterate(str(tmp_path))
    assert out['ok'] is False and out['reason'] == 'not_enough_rows'


def test_rollback_restores_the_previous_value(tmp_path):
    store = str(tmp_path)
    _fill(store, lambda g: (g - 0.35) * 2.0)
    T.iterate(store)
    moved = T.values(store)['push_gain']
    T.rollback(store)
    assert T.values(store)['push_gain'] != moved
    assert abs(T.values(store)['push_gain'] - T.DEFAULTS['push_gain']) < 1e-9
