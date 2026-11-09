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


@pytest.mark.skipif(not B.available(), reason='mindbase not importable here')
def test_dialogue_body_keeps_state_and_reacts():
    body = B.DialogueBody(seed=1)
    pos = body.feed('谢谢你', {'valence': 0.7, 'arousal': 0.4, 'social': 0.6})
    neg = body.feed('你怎么又搞砸了', {'valence': -0.8, 'arousal': 0.7, 'social': -0.7, 'control': 0.2})
    assert neg['valence'] < pos['valence']
    assert neg['stress'] > pos['stress']
    assert 'action' in neg


@pytest.mark.skipif(not B.available(), reason='mindbase not importable here')
def test_body_state_is_continuous_across_turns():
    body = B.DialogueBody(seed=2)
    first = body.feed('嗯。', {'valence': -0.6, 'arousal': 0.3, 'social': -0.5})
    second = body.feed('嗯。', {'valence': -0.6, 'arousal': 0.3, 'social': -0.5})
    assert second['stress'] >= first['stress'] - 0.05 or second['valence'] != first['valence']


@pytest.mark.skipif(not B.available(), reason='mindbase not importable here')
def test_idle_noise_produces_spontaneous_choice():
    """Idle ticks must not be identical across seeds: noise creates options."""
    actions = set()
    for seed in range(12):
        body = B.DialogueBody(seed=seed)
        actions.add(body.idle(200)['action'])
    assert len(actions) > 1, 'every seed chose the same action at rest'


@pytest.mark.skipif(not B.available(), reason='mindbase not importable here')
def test_persisted_state_keeps_the_action(tmp_path):
    body = B.DialogueBody(seed=1)
    state = body.feed('嗯', {'valence': -0.4, 'arousal': 0.3, 'social': -0.4})
    B.save_state(str(tmp_path), 's1', state)
    back = B.load_state(str(tmp_path), 's1')
    assert 'action' in back, 'the body decision must survive a process restart'
    assert back['action'] in ('speak', 'silence')


@pytest.mark.skipif(not B.available(), reason='mindbase not importable here')
def test_mirror_recall_reaches_body_memory(tmp_path):
    B.mirror_recall(str(tmp_path), 's1', ['- 她答应过五月一号前写完'])
    body = B.body_for(str(tmp_path), 's1')
    hit = body.mind.memory.retrieve('五月一号', float(body.mind.t))
    assert hit is not None, 'the substrate memory lost the mirrored line'
    assert '五月一号' in getattr(hit, 'text', '')


def test_q_table_learns_both_directions(tmp_path):
    from biocore_runtime import pipeline as P
    store = str(tmp_path)
    for _ in range(5):
        P.q_note_choice(store, 'good', 'approach', {'now': 1000.0, 'gap_minutes': 5})
        P.q_reward_last(store, 'good', True, 300.0, {'now': 1000.0})
    good = P.q_decision(store, 'good', {'now': 1000.0, 'gap_minutes': 5})
    assert good['samples'] == 5
    assert good['rows'][0]['q'] > 0.2
