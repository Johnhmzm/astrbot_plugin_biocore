# -*- coding: utf-8 -*-
"""The digital-fly substrate must stay reachable from the core.

It spent the whole project as an island: present in the tree, never imported by
the runtime. These tests fail loudly if that happens again.
"""
import sys, pathlib
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'dsh-biocore-ui' / 'python'))

from biocore_runtime import mindbase_bridge as B


@pytest.mark.skipif(not B.available(), reason='mindbase not importable here')
def test_episode_returns_metrics():
    m = B.run_episode(seed=1, steps=20)
    assert set(m) >= {'energy', 'viability', 'initiative'}
    assert 0.0 <= m['energy'] <= 1.0
    assert 0.0 <= m['viability'] <= 1.0


@pytest.mark.skipif(not B.available(), reason='mindbase not importable here')
def test_fitness_is_bounded():
    f = B.fitness({'energy': 1.0, 'viability': 1.0, 'initiative': 1.0})
    assert 0.0 <= f <= 1.0


@pytest.mark.skipif(not B.available(), reason='mindbase not importable here')
def test_evolve_runs_and_reports_history():
    out = B.evolve(generations=1, population=3, steps=10, seed=2)
    assert len(out['history']) == 1
    assert out['best'] is not None
    assert len(out['best']) == len(out['bounds'])
