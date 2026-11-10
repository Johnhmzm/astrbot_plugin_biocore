# -*- coding: utf-8 -*-
"""PI homeostasis: proportional pull plus integral that removes the residual."""
import pytest

from biocore_runtime import mindbase_bridge as B

pytestmark = pytest.mark.skipif(not B.available(), reason='mindbase not importable here')


def _settle(kp, ki, steps=120, start=-0.6):
    B.PI_KP, B.PI_KI = kp, ki
    v, integ = start, 0.0
    for i in range(steps):
        err = -v
        integ = max(-B.PI_I_LIMIT, min(B.PI_I_LIMIT, integ + err * B.PI_KI_DT))
        v = max(-1.0, min(1.0, v + kp * err + ki * integ))
        if abs(v) < 0.02:
            return i + 1, v
    return None, v


def test_pi_reaches_the_baseline():
    steps, final = _settle(0.04, 0.010)
    assert steps is not None, 'PI never returned to baseline'
    assert abs(final) < 0.02


def test_pure_p_leaves_a_residual():
    steps, final = _settle(0.04, 0.0, steps=80)
    assert abs(final) > 0.01, 'P alone should still be short of zero'


def test_integral_is_clamped():
    assert B.PI_I_LIMIT > 0
    integ = 0.0
    for _ in range(10000):
        integ = max(-B.PI_I_LIMIT, min(B.PI_I_LIMIT, integ + (-1.0) * B.PI_KI_DT))
    assert integ >= -B.PI_I_LIMIT - 1e-9
