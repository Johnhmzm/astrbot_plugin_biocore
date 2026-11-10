# -*- coding: utf-8 -*-
"""z-scores: her position in her own units, comparable across baselines."""
import pytest

from biocore_runtime import mindbase_bridge as B

pytestmark = pytest.mark.skipif(not B.available(), reason='mindbase not importable here')


def _feed(store, baseline, n=12, sd=0.02):
    import random
    rng = random.Random(3)
    z = {}
    for _ in range(n):
        z = B.norm_update(store, 's', {'valence': baseline + rng.gauss(0, sd),
                                       'arousal': 0.45, 'stress': 0.1,
                                       'social_drive': 0.55})
    return z


def test_silent_before_enough_samples(tmp_path):
    z = B.norm_update(str(tmp_path), 's', {'valence': 0.0, 'arousal': 0.4,
                                           'stress': 0.0, 'social_drive': 0.5})
    assert z['valence'] == 0.0


def test_same_drop_reads_similar_at_different_baselines(tmp_path):
    a = _feed(str(tmp_path / 'a'), 0.0)
    b = _feed(str(tmp_path / 'b'), 0.6)
    drop_a = B.norm_update(str(tmp_path / 'a'), 's', {'valence': 0.0 - 0.12,
                                                      'arousal': 0.45, 'stress': 0.1,
                                                      'social_drive': 0.55})['valence']
    drop_b = B.norm_update(str(tmp_path / 'b'), 's', {'valence': 0.6 - 0.12,
                                                      'arousal': 0.45, 'stress': 0.1,
                                                      'social_drive': 0.55})['valence']
    assert drop_a < 0 and drop_b < 0
    assert abs(drop_a - drop_b) < 0.6   # same size of drop, comparable reading


def test_bigger_drop_reads_larger(tmp_path):
    store = str(tmp_path)
    _feed(store, 0.0)
    small = B.norm_update(store, 's', {'valence': -0.10, 'arousal': 0.45,
                                       'stress': 0.1, 'social_drive': 0.55})['valence']
    big = B.norm_update(store, 's', {'valence': -0.45, 'arousal': 0.45,
                                     'stress': 0.1, 'social_drive': 0.55})['valence']
    assert big < small
