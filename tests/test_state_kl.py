# -*- coding: utf-8 -*-
"""KL between the state before and after one exchange."""
import pytest

from biocore_runtime import mindbase_bridge as B


pytestmark = pytest.mark.skipif(not B.available(), reason='mindbase not importable here')


def _state(v=0.0, a=0.45, s=0.0, sd=0.55):
    return {'valence': v, 'arousal': a, 'stress': s, 'social_drive': sd}


def test_no_change_is_zero():
    s = _state()
    assert B.state_kl(s, s) == 0.0


def test_a_bigger_shift_scores_higher():
    before = _state()
    small = B.state_kl(before, _state(v=-0.05, s=0.02))
    big = B.state_kl(before, _state(v=-0.45, s=0.30))
    assert big > small > 0


def test_a_shove_beats_a_greeting():
    before = _state()
    greeting = B.state_kl(before, _state(v=0.08))
    shove = B.state_kl(before, _state(v=-0.40, s=0.35))
    assert shove > greeting * 5
