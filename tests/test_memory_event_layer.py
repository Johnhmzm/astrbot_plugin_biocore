# -*- coding: utf-8 -*-
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from biocore_memory.event import events as E


def _entries(n=30, gap=60.0, vecs=True):
    rows = []
    for i in range(n):
        entry = {'turn': i + 1, 'role': 'user' if i % 2 == 0 else 'assistant',
                 'text': '第%d轮的说话内容' % (i + 1), 'ts': 1000.0 + i * gap}
        if vecs:
            entry['vector'] = [1.0, float(i % 3), 0.5]
        rows.append(entry)
    return rows


def test_off_by_default_changes_nothing():
    calls = []
    rows = _entries()
    assert E.build_events(rows) == []
    assert E.event_recall('问题', [{'overview': 'x', 'text': 'y', 'tokens': 10}]) == []
    assert E.summarize_event({'text': 'a'}, llm=lambda p: calls.append(p) or '{}') == {}
    assert calls == []


def test_build_events_covers_every_turn_once():
    rows = _entries(30)
    evs = E.build_events(rows, flags={E.FLAG_KEY: True})
    covered = [t for ev in evs for t in ev['members']]
    assert sorted(covered) == [r['turn'] for r in rows]
    assert len(covered) == len(set(covered)), 'overlap'
    assert all(ev['members'] for ev in evs)
    assert all(len(ev['members']) <= 15 for ev in evs)


def test_build_events_with_llm_segments():
    rows = _entries(12)
    def llm(prompt):
        assert '轮号' in prompt
        return '[{"start": 1, "end": 4}, {"start": 3, "end": 9}, {"start": 12, "end": 12}]'
    evs = E.build_events(rows, llm=llm, flags={E.FLAG_KEY: True})
    covered = [t for ev in evs for t in ev['members']]
    assert sorted(covered) == list(range(1, 13))
    assert len(covered) == len(set(covered))


def test_summarize_overview_and_chronicle_threshold():
    small = {'text': '短文本', 'tokens': 5}
    res = E.summarize_event(small, llm=lambda p: '{"overview": "许砚舟记下生日八月十八"}',
                            flags={E.FLAG_KEY: True})
    assert res['overview'] == '许砚舟记下生日八月十八'
    assert res['chronicle'] == ''
    big_text = '很长的一段记录。' * 400
    big = {'text': big_text}
    calls = []
    def llm(prompt):
        calls.append(prompt)
        return ('{"overview": "用户确认生日"}' if '概览' in prompt
                else '{"chronicle": "用户说自己生日是八月十八。"}')
    res2 = E.summarize_event(big, llm=llm, flags={E.FLAG_KEY: True})
    assert res2['chronicle'].startswith('用户说')
    assert len(calls) == 2


def test_event_recall_budget_drops_whole_events():
    events = [{'event_id': 'a', 'overview': '生日', 'text': 'x' * 6000, 'tokens': 4000},
              {'event_id': 'b', 'overview': '生日', 'text': 'y' * 6000, 'tokens': 4000},
              {'event_id': 'c', 'overview': '生日', 'text': 'z' * 3000, 'tokens': 2000}]
    picked = E.event_recall('生日是哪天', events, budget_tokens=6000, flags={E.FLAG_KEY: True})
    assert [e['event_id'] for e in picked] == ['a', 'c']
    assert len(picked) == 2


def test_event_recall_uses_selector_when_given():
    events = [{'event_id': 'a', 'overview': 'x', 'text': 'x', 'tokens': 10},
              {'event_id': 'b', 'overview': 'x', 'text': 'y', 'tokens': 10}]
    def selector(question, cands, budget):
        return list(reversed(cands))
    picked = E.event_recall('q', events, flags={E.FLAG_KEY: True}, selector=selector)
    assert [e['event_id'] for e in picked] == ['b', 'a']


def _ev(eid, tokens, overview='x', vec=None):
    return {'event_id': eid, 'overview': overview, 'text': 't' * 10,
            'tokens': tokens, 'vector': vec or []}


def test_event_recall_big_pool_fills_budget():
    events = [_ev('e%d' % i, 400) for i in range(150)]
    stats = {}
    picked = E.event_recall('问题', events, budget_tokens=8000, flags={E.FLAG_KEY: True}, stats=stats)
    assert stats['pool'] == 100, stats
    assert stats['selected'] == 20
    assert stats['tokens'] == 8000
    assert stats['fill'] == 1.0 and stats['underfilled'] is False


def test_event_recall_flags_underfilled_pool():
    events = [_ev('a', 1000), _ev('b', 1000)]
    stats = {}
    picked = E.event_recall('问题', events, budget_tokens=8000, flags={E.FLAG_KEY: True}, stats=stats)
    assert stats['selected'] == 2
    assert stats['fill'] == 0.25
    assert stats['underfilled'] is True


def test_event_recall_rerank_reorders():
    events = [_ev('a', 100, vec=[1.0, 0.0]), _ev('b', 100, vec=[0.9, 0.1]),
              _ev('c', 100, vec=[0.1, 1.0])]
    def rerank(question, cands):
        # higher is better, like a cross-encoder relevance score
        return [0.9 if ev['event_id'] == 'c' else 0.1 for ev in cands]
    stats = {}
    picked = E.event_recall('q', events, flags={E.FLAG_KEY: True}, embed=lambda q: [1.0, 0.0],
                            rerank=rerank, stats=stats)
    assert stats['rerank_used'] is True
    assert picked[0]['event_id'] == 'c'


def test_event_recall_max_events_caps_selection():
    events = [_ev('e%d' % i, 100) for i in range(50)]
    stats = {}
    picked = E.event_recall('q', events, budget_tokens=8000, max_events=5,
                            flags={E.FLAG_KEY: True}, stats=stats)
    assert len(picked) == 5
    assert stats['selected'] == 5
    assert stats['max_events'] == 5


def test_event_recall_selector_by_id_keeps_order():
    events = [_ev('a', 100), _ev('b', 100), _ev('c', 100)]
    stats = {}
    picked = E.event_recall('q', events, flags={E.FLAG_KEY: True},
                            selector=lambda q, c, b: ['c', 'a'], stats=stats)
    assert [e['event_id'] for e in picked] == ['c', 'a']
    assert stats['selector_used'] is True

def _vec_entries(n=12, jump_at=5):
    rows = []
    for i in range(n):
        base = [1.0, 0.0] if i < jump_at else [0.0, 1.0]
        rows.append({'turn': i + 1, 'role': 'user', 'text': 'x%d' % i,
                     'ts': 1000.0 + i * 30.0, 'vector': base})
    return rows


def test_build_events_cuts_on_vector_jump_not_time():
    rows = _vec_entries(12, jump_at=5)
    trace = []
    evs = E.build_events(rows, flags={E.FLAG_KEY: True}, trace=trace)
    cuts = [t for t in trace if t['cut']]
    assert len(cuts) == 1, trace
    # the vector changes between turn 5 and turn 6, so the new event starts at 6
    assert cuts[0]['turn'] == 6 and cuts[0]['reason'] == 'jump'
    assert all(t['by'] == 'vector' for t in trace)
    assert [ev['start'] for ev in evs] == [1, 6]


def test_build_events_falls_back_to_time_without_vectors():
    rows = [{'turn': i + 1, 'role': 'user', 'text': 'x', 'ts': 1000.0 + i * 7200.0}
            for i in range(6)]
    trace = []
    E.build_events(rows, flags={E.FLAG_KEY: True}, trace=trace)
    assert all(t['by'] == 'time' for t in trace)
    assert all(t['cut'] for t in trace)


def test_event_recall_uses_default_rerank():
    def better(question, cands):
        return [1.0 if ev['event_id'] == 'c' else 0.0 for ev in cands]
    E.set_default_rerank(better)
    try:
        events = [_ev('a', 100), _ev('b', 100), _ev('c', 100)]
        stats = {}
        picked = E.event_recall('q', events, flags={E.FLAG_KEY: True}, stats=stats)
        assert picked[0]['event_id'] == 'c'
        assert stats['rerank_used'] is True and stats['rerank_calls'] == 1
    finally:
        E.set_default_rerank(None)
    stats2 = {}
    E.event_recall('q', events, flags={E.FLAG_KEY: True}, stats=stats2)
    assert stats2['rerank_used'] is False

def test_summarize_events_batch_aligns_by_turns():
    evs = [{'event_id': 'a', 'start': 1, 'end': 3, 'text': 'x' * 30},
           {'event_id': 'b', 'start': 4, 'end': 6, 'text': 'y' * 30}]
    def llm(prompt):
        return '[{"start": 4, "end": 6, "overview": "乙"}, {"start": 1, "end": 3, "overview": "甲"}]'
    out = E.summarize_events_batch(evs, llm=llm, flags={E.FLAG_KEY: True})
    assert [(o['start'], o['overview']) for o in out] == [(1, '甲'), (4, '乙')]


def test_summarize_events_batch_falls_back_to_single():
    evs = [{'event_id': 'a', 'start': 1, 'end': 2, 'text': 'x' * 20},
           {'event_id': 'b', 'start': 3, 'end': 4, 'text': 'y' * 20}]
    calls = []
    def llm(prompt):
        calls.append(prompt)
        if '【1-2】' in prompt or '【3-4】' in prompt:
            return '[{"start": 1, "end": 2, "overview": "甲"}]'
        return '{"overview": "乙单条"}'
    out = E.summarize_events_batch(evs, llm=llm, flags={E.FLAG_KEY: True})
    assert out[0]['overview'] == '甲'
    assert out[1]['overview'] == '乙单条'
    assert out[1]['source'] in ('single', 'batch')


def test_summarize_events_batch_off_by_default():
    calls = []
    out = E.summarize_events_batch([{'start': 1, 'end': 2, 'text': 'x'}],
                                   llm=lambda p: calls.append(p) or '[]')
    assert out == [] and calls == []


def _sentence_events():
    return [{'event_id': 'a', 'start': 1, 'end': 2, 'overview': '闲聊天气',
             'text': 'x' * 10, 'tokens': 100, 'vector': [1.0, 0.0]},
            {'event_id': 'b', 'start': 3, 'end': 4, 'overview': '闲聊吃饭',
             'text': 'y' * 10, 'tokens': 100, 'vector': [0.0, 1.0]}]


def test_event_recall_sentence_channel_reaches_raw_hits():
    events = _sentence_events()
    entries = [{'turn': 1, 'vector': [0.0, 1.0]}, {'turn': 3, 'vector': [1.0, 0.0]}]
    stats = {}
    picked = E.event_recall('猫叫什么名字', events, flags={E.FLAG_KEY: True},
                            embed=lambda text: [1.0, 0.0], entry='sentence',
                            entries=entries, budget_tokens=1000, stats=stats)
    # the overview says nothing about the question; the entry vector does
    assert picked[0]['event_id'] == 'b'
    assert stats['sentence_used'] is True
    assert stats['sentence_hits'] == 2


def test_event_recall_union_dedupes_candidates():
    events = _sentence_events()
    entries = [{'turn': 1, 'vector': [1.0, 0.0]}, {'turn': 3, 'vector': [1.0, 0.0]}]
    picked = E.event_recall('生日', events, flags={E.FLAG_KEY: True},
                            embed=lambda text: [1.0, 0.0], entry='union',
                            entries=entries, budget_tokens=1000)
    ids = [ev['event_id'] for ev in picked]
    assert sorted(ids) == ['a', 'b'], ids
    assert len(ids) == len(set(ids))


def test_event_recall_summary_entry_matches_default():
    events = _sentence_events()
    entries = [{'turn': 1, 'vector': [1.0, 0.0]}]
    base = E.event_recall('生日', events, flags={E.FLAG_KEY: True},
                          embed=lambda text: [1.0, 0.0])
    explicit = E.event_recall('生日', events, flags={E.FLAG_KEY: True},
                              embed=lambda text: [1.0, 0.0], entry='summary',
                              entries=entries)
    assert [ev['event_id'] for ev in base] == [ev['event_id'] for ev in explicit]
    no_entries = E.event_recall('生日', events, flags={E.FLAG_KEY: True},
                                embed=lambda text: [1.0, 0.0], entry='union')
    assert [ev['event_id'] for ev in no_entries] == [ev['event_id'] for ev in base]


def test_build_events_merge_small_keeps_partition():
    rows = []
    for i in range(24):
        ts = 1000.0 + (i // 2) * 200000.0 + (i % 2) * 30.0
        rows.append({'turn': i + 1, 'role': 'user', 'text': 'x%d' % i,
                     'ts': ts, 'vector': [1.0, 0.0]})
    raw = E.build_events(rows, flags={E.FLAG_KEY: True})
    merged = E.build_events(rows, flags={E.FLAG_KEY: True}, merge_small=True)
    assert all(len(ev['members']) <= 2 for ev in raw)
    covered = [t for ev in merged for t in ev['members']]
    assert sorted(covered) == list(range(1, 25))
    assert len(covered) == len(set(covered)), 'overlap'
    assert len(merged) < len(raw)
    assert all(3 <= len(ev['members']) <= 6 for ev in merged), [len(ev['members']) for ev in merged]


def test_event_recall_passes_rerank_text():
    seen = []
    events = [_ev('a', 100, vec=[1.0, 0.0]), _ev('b', 100, vec=[0.9, 0.1])]

    def rerank(question, cands, text='overview'):
        seen.append(text)
        return [1.0, 0.0]

    E.event_recall('q', events, flags={E.FLAG_KEY: True}, embed=lambda t: [1.0, 0.0],
                   rerank=rerank, rerank_text='sentence')
    assert seen == ['sentence']
    E.event_recall('q', events, flags={E.FLAG_KEY: True}, embed=lambda t: [1.0, 0.0],
                   rerank=rerank)
    assert seen == ['sentence', 'overview']


def test_event_recall_sentence_falls_back_when_empty():
    events = _sentence_events()
    def rerank(question, cands, text='overview'):
        return [1.0 if ev['event_id'] == 'a' else 0.0 for ev in cands]
    stats = {}
    picked = E.event_recall('生日', events, flags={E.FLAG_KEY: True},
                            embed=lambda text: [1.0, 0.0], entry='sentence',
                            entries=[{'turn': 99, 'vector': [1.0, 0.0]}],
                            rerank=rerank, budget_tokens=1000, stats=stats)
    assert stats['sentence_used'] is False
    assert [ev['event_id'] for ev in picked][:2] == ['a', 'b']
    assert stats['entry'] == 'sentence'


def test_two_stage_stays_inside_coarse_events():
    events = [{'event_id': 'a', 'start': 1, 'end': 2, 'overview': 'x', 'text': 'x',
               'tokens': 10, 'vector': [1.0, 0.0]},
              {'event_id': 'b', 'start': 3, 'end': 4, 'overview': 'y', 'text': 'y',
               'tokens': 10, 'vector': [0.0, 1.0]}]
    entries = [{'turn': 1, 'vector': [0.0, 1.0], 'text': '用户提到猫叫团子'},
               {'turn': 3, 'vector': [1.0, 0.0], 'text': '闲聊天气'}]
    seen = []

    def rerank(question, cands, text='overview'):
        seen.extend(ev['text'] for ev in cands)
        return [1.0 for _ in cands]

    stats = {}
    picked = E.event_recall('猫叫什么', events, flags={E.FLAG_KEY: True},
                            embed=lambda t: [1.0, 0.0], entry='two_stage',
                            entries=entries, coarse_events=1, rerank=rerank,
                            budget_tokens=1000, stats=stats)
    # stage 1 keeps only event a, so b's entry must never reach the rerank
    assert [ev['event_id'] for ev in picked] == ['a']
    assert len(seen) == 1 and '用户提到猫叫团子' in seen[0]
    assert stats['coarse_events'] == 1 and stats['fine_entries'] == 1


def test_two_stage_rerank_width_is_fixed():
    events = [{'event_id': 'e%d' % i, 'start': i * 10 + 1, 'end': i * 10 + 10,
               'overview': 'o%d' % i, 'text': 't%d' % i, 'tokens': 10,
               'vector': [1.0, 0.0]} for i in range(30)]
    entries = [{'turn': t, 'vector': [float(t % 7), 1.0], 'text': 'x%d' % t}
               for t in range(1, 301)]
    widths = []

    def rerank(question, cands, text='overview'):
        widths.append(len(cands))
        return [0.5] * len(cands)

    stats = {}
    picked = E.event_recall('q', events, flags={E.FLAG_KEY: True},
                            embed=lambda t: [1.0, 0.0], entry='two_stage',
                            entries=entries, rerank=rerank, coarse_events=30,
                            fine_pool=100, fine_keep=30, budget_tokens=100000,
                            stats=stats)
    assert widths == [100], widths
    assert 0 < len(picked) <= 30
    assert stats['fine_kept'] == len(picked)


def test_overview_passes_value_time_text_through():
    ev = {'start': 1, 'end': 3,
          'text': 'user：叶楠生日是八月十六\nassistant：好的\nuser：后来是八月十八'}
    prompts = []

    def llm(prompt):
        prompts.append(prompt)
        return '[{"start": 1, "end": 3, "overview": "叶楠生日先说十六，后定为十八"}]'

    out = E.summarize_events_batch([ev], llm=llm, flags={E.FLAG_KEY: True})
    assert '十八' in out[0]['overview']
    assert '笔记' in prompts[0]

def test_single_overview_prompt_states_correction_and_conflict():
    calls = []
    E.summarize_event({'text': '用户说生日是八月十六，又改成八月十八'},
                      llm=lambda p: calls.append(p) or '{"overview": "ok"}',
                      flags={E.FLAG_KEY: True})
    assert '笔记' in calls[0] and '说法' in calls[0]

def test_render_event_hits_keeps_context():
    ev = {'start': 5, 'end': 9, 'overview': '叶楠生日八月十八（曾更正自十六）',
          'hit_turns': [7],
          'entries': [{'turn': 5, 'role': 'user', 'text': '早上好。'},
                      {'turn': 7, 'role': 'user', 'text': '叶楠生日是八月十六。'},
                      {'turn': 8, 'role': 'user', 'text': '不对，是八月十八。'},
                      {'turn': 9, 'role': 'assistant', 'text': '记下了。'}]}
    text = '\n'.join(E.render_event_hits(ev))
    assert '第5-9轮' in text and '八月十八' in text
    assert '命中：[用户] 叶楠生日是八月十六。' in text
    assert '开头' in text and '早上好。' in text
    assert '结尾' in text and '记下了。' in text
    assert '不对，是八月十八。' not in text  # only the hit message is pasted in full


def test_two_stage_annotates_hit_turns():
    events = [{'event_id': 'a', 'start': 1, 'end': 4, 'overview': 'x', 'text': 'x',
               'tokens': 10, 'vector': [1.0, 0.0]},
              {'event_id': 'b', 'start': 5, 'end': 8, 'overview': 'y', 'text': 'y',
               'tokens': 10, 'vector': [0.0, 1.0]}]
    entries = [{'turn': 3, 'vector': [1.0, 0.0], 'text': '叶楠生日是八月十六'}]

    def rerank(question, cands, text='overview'):
        return [1.0 for _ in cands]

    picked = E.event_recall('生日', events, flags={E.FLAG_KEY: True},
                            embed=lambda t: [1.0, 0.0], entry='two_stage',
                            entries=entries, rerank=rerank, budget_tokens=1000)
    assert picked[0]['event_id'] == 'a'
    assert picked[0]['hit_turns'] == [3]


def test_overview_prompt_states_correction_and_conflict():
    calls = []
    E.summarize_event({'text': '叶楠生日八月十六，后来是八月十八'},
                      llm=lambda p: calls.append(p) or '{"overview": "x"}',
                      flags={E.FLAG_KEY: True})
    prompts = calls + [E._batch_prompt([{'start': 1, 'end': 2, 'text': 't'}])]
    for prompt in prompts:
        assert '笔记' in prompt and '说法' in prompt

def test_overview_keeps_value_time_format_verbatim():
    ev = {'start': 165, 'end': 167,
          'text': 'user：叶楠生日八月十六。\nuser：后来是八月十八。'}
    reply = '叶楠·生日：八月十六(5月1日) / 八月十八(5月3日)'

    def llm(prompt):
        return '[{"start": 165, "end": 167, "overview": "' + reply + '"}]'

    out = E.summarize_events_batch([ev], llm=llm, flags={E.FLAG_KEY: True})
    assert out[0]['overview'] == reply          # 原样使用，不再加工
    assert '(5月1日)' in out[0]['overview'] and '(5月3日)' in out[0]['overview']


TRIGGERS = ('说错', '记错', '改错', '改成', '说早', '不对')
TOPICS = ('生日', '地板', '芹菜', '邮票', '夜班', '咖啡')


def test_overview_prompt_mentions_two_output_shapes():
    calls = []
    E.summarize_event({'text': '甲说了某件事，后文又说了另一件事'},
                      llm=lambda p: calls.append(p) or '{"overview": "x"}',
                      flags={E.FLAG_KEY: True})
    prompts = calls + [E._batch_prompt([{'start': 1, 'end': 2, 'text': 't'}])]
    for prompt in prompts:
        assert '取代' in prompt and '并存' in prompt

def test_overview_unknown_subject_branch_renders():
    ev = {'start': 7, 'end': 8, 'text': 'user：有人把东西放这儿了。\nassistant：好。'}

    def llm(prompt):
        return '[{"start": 7, "end": 8, "overview": "主体不明·位置：靠门(7)"}]'

    out = E.summarize_events_batch([ev], llm=llm, flags={E.FLAG_KEY: True})
    assert out[0]['overview'].startswith('主体不明·')
    ev = dict(ev, overview=out[0]['overview'])
    lines = E.render_event_hits(ev)
    assert any('主体不明' in line for line in lines)

def test_overview_prompt_forbids_default_latest():
    ev = {'start': 1, 'end': 2, 'text': 'user：叶楠生日是八月十六\nassistant：好'}
    prompts = []

    def llm(prompt):
        prompts.append(prompt)
        return '[{"start": 1, "end": 2, "overview": "叶楠生日先说十六，后按日历定为十八"}]'

    out = E.summarize_events_batch([ev], llm=llm, flags={E.FLAG_KEY: True})
    assert '十八' in out[0]['overview']

def test_rerank_doc_carries_time_speaker_and_clue():
    entry = {'turn': 3, 'role': 'user', 'ts': 1777814836.0,
             'text': '叶楠生日其实是八月十八号，我翻日历对过' * 3}
    event = {'overview': '叶楠生日八月十八（曾更正自十六）' * 5}
    doc = E.rerank_doc(entry, event)
    assert doc.startswith('[2026-') or doc.startswith('[20')
    assert '用户]' in doc
    assert '｜ 事件：' in doc
    assert entry['text'] in doc                      # sentence not truncated
    clue = doc.split('｜ 事件：')[1]
    assert len(clue) == 40



def test_recency_channel_is_mandatory():
    events = [{'event_id': 'old', 'start': 1, 'end': 2, 'overview': 'o', 'text': 'x',
               'tokens': 10, 'vector': [1.0, 0.0]},
              {'event_id': 'new', 'start': 19, 'end': 20, 'overview': 'n', 'text': 'y',
               'tokens': 10, 'vector': [0.0, 1.0]}]
    entries = [{'turn': t, 'vector': [1.0, 0.0], 'text': 'm%d' % t} for t in range(1, 21)]
    picked = E.event_recall('问题', events, flags={E.FLAG_KEY: True},
                            embed=lambda q: [1.0, 0.0], entry='two_stage',
                            rank='recency', entries=entries, rerank=None,
                            budget_tokens=1000)
    ids = [ev['event_id'] for ev in picked]
    assert 'new' in ids            # recency event kept even with cosine 0


def test_recency_candidates_dedupe():
    events = [{'event_id': 'a', 'start': 1, 'end': 2, 'overview': 'o', 'text': 'x',
               'tokens': 10, 'vector': [1.0, 0.0]},
              {'event_id': 'b', 'start': 3, 'end': 4, 'overview': 'n', 'text': 'y',
               'tokens': 10, 'vector': [0.9, 0.1]}]
    entries = [{'turn': t, 'vector': [1.0, 0.0], 'text': 'm%d' % t} for t in range(1, 21)]
    stats = {}
    picked = E.event_recall('问题', events, flags={E.FLAG_KEY: True},
                            embed=lambda q: [1.0, 0.0], entry='two_stage',
                            rank='recency', entries=entries, rerank=None,
                            budget_tokens=1000, stats=stats)
    ids = [ev['event_id'] for ev in picked]
    assert len(ids) == len(set(ids))






def test_batch_alignment_tolerates_extra_text_and_keys():
    evs = [{'event_id': 'a', 'start': 1, 'end': 3, 'text': 'x' * 20},
           {'event_id': 'b', 'start': 4, 'end': 6, 'text': 'y' * 20}]
    def llm(prompt):
        return ('好的，结果如下：'
                '[{"Start": "4-6", "Summary": "乙事件"},'
                 ' {"start": 1, "end": 3, "overview": "甲事件"}] 以上。')
    out = E.summarize_events_batch(evs, llm=llm, flags={E.FLAG_KEY: True})
    assert [o['overview'] for o in out] == ['甲事件', '乙事件']
    assert all(o['source'] == 'batch' for o in out)


def test_batch_alignment_falls_back_to_order():
    evs = [{'event_id': 'a', 'start': 1, 'end': 3, 'text': 'x' * 20},
           {'event_id': 'b', 'start': 4, 'end': 6, 'text': 'y' * 20}]
    def llm(prompt):
        return '[{"start": 0, "end": 0, "overview": "甲"}, {"start": 0, "end": 0, "overview": "乙"}]'
    stats = {}
    out = E.summarize_events_batch(evs, llm=llm, flags={E.FLAG_KEY: True}, stats=stats)
    assert [o['overview'] for o in out] == ['甲', '乙']
    assert stats['single_calls'] == 0

if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('OK', name)
    print('all event-layer tests passed')
