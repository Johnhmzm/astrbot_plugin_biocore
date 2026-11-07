# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from biocore_memory.event import keynorm as K


def _fact(subject, attr, value='x'):
    return {'subject': subject, 'attr': attr, 'value': value}


def test_key_of_keeps_subject_and_attribute():
    assert K.key_of('叶楠', '生日') == '叶楠·生日'
    assert K.key_of(' 叶楠 ', '生日 ') == '叶楠·生日'
    assert K.key_of('', '生日') == ''
    assert K.key_of('叶楠', '') == ''


def test_rank_keys_orders_by_frequency_then_name():
    facts = [_fact('用户', '称呼'), _fact('客厅地板', '颜色'), _fact('用户', '称呼'),
             _fact('用户', '生日')]
    keys = K.rank_keys(facts)
    assert keys[0] == '用户·称呼'          # 2 hits beat every single
    assert keys[1:] == ['客厅地板·颜色', '用户·生日']  # ties by name


def test_rank_keys_caps_at_limit():
    facts = [_fact('主体%d' % i, '属性') for i in range(90)]
    keys = K.rank_keys(facts, limit=K.KNOWN_KEYS_LIMIT)
    assert len(keys) == 60
    assert len(K.rank_keys(facts, limit=5)) == 5


def test_rank_keys_reads_a_state_dict():
    state = {'叶楠·生日': {'value': '八月十六', 'history': [{}, {}]},
             '用户·称呼': {'value': '夏夏'}}
    keys = K.rank_keys(state)
    assert keys[0] == '叶楠·生日'


def test_normalize_key_reuses_exact_key():
    known = ['叶楠·生日', '用户·称呼']
    assert K.normalize_key('叶楠', '生日', known) == '叶楠·生日'


def test_normalize_key_unifies_qualified_subject():
    known = ['客厅地板·颜色']
    assert K.normalize_key('合租房客厅地板', '颜色', known) == '客厅地板·颜色'


def test_normalize_key_leaves_semantic_aliases_to_the_model():
    # 日历日期 only becomes 生日 if the model copies the key; no rule invents it
    known = ['叶楠·生日']
    assert K.normalize_key('叶楠', '日历日期', known) == ''


def test_normalize_key_without_known_keys_creates_nothing():
    assert K.normalize_key('叶楠', '生日', None) == ''
    assert K.normalize_key('叶楠', '生日', []) == ''


def test_extract_prompt_lists_known_keys_and_demands_reuse():
    events = [{'start': 165, 'end': 166, 'text': 'user：叶楠生日八月十六'}]
    known = ['叶楠·生日', '用户·称呼']
    prompt = K.extract_prompt(events, known)
    assert '叶楠·生日' in prompt and '用户·称呼' in prompt
    assert '照抄' in prompt and '才新建' in prompt
    assert '【165-166】' in prompt and '叶楠生日八月十六' in prompt
    assert 'JSON 数组' in prompt


def test_extract_prompt_without_keys_still_asks_for_json():
    prompt = K.extract_prompt([{'start': 1, 'end': 2, 'text': 't'}], None)
    assert '暂无已有键' in prompt and 'JSON 数组' in prompt


def test_extract_prompt_caps_key_block_at_sixty():
    known = ['主体%d·属性' % i for i in range(80)]
    prompt = K.extract_prompt([{'start': 1, 'end': 2, 'text': 't'}], known)
    assert '主体59·属性' in prompt
    assert '主体60·属性' not in prompt


def test_advanced_keys_appends_only_new_keys():
    known = ['叶楠·生日']
    facts = [{'subject': '叶楠', 'attr': '生日', 'value': '八月十六'},
             {'subject': '客厅地板', 'attr': '颜色', 'value': '浅灰'}]
    assert K.advanced_keys(known, facts) == ['叶楠·生日', '客厅地板·颜色']


def _ev(eid, start, end, text, entries=None):
    ev = {'event_id': eid, 'start': start, 'end': end, 'text': text}
    if entries is not None:
        ev['entries'] = entries
    return ev


def _reply(span, facts):
    return json.dumps([{'start': span[0], 'end': span[1], 'facts': facts}],
                      ensure_ascii=False)


def test_extract_reuses_the_known_key_instead_of_renaming_it():
    events = [_ev('a', 165, 166, 'user：叶楠生日是八月十六')]
    seen = []

    def llm(prompt):
        seen.append(prompt)
        return _reply((165, 166), [{'subject': '叶楠', 'attr': '生日', 'value': '八月十六'}])

    facts = K.extract_facts(events, llm, ['叶楠·生日'])
    assert '叶楠·生日' in seen[0]              # the key list reached the model
    assert facts == [{'subject': '叶楠', 'attr': '生日', 'value': '八月十六',
                      'turn': 165, 'ts': 0.0}]


def test_extract_keeps_a_reused_key_even_when_subject_is_qualified():
    events = [_ev('a', 279, 281, 'user：合租房客厅地板是浅灰色')]

    def llm(prompt):
        return _reply((279, 281), [{'subject': '合租房客厅地板', 'attr': '颜色',
                                    'value': '浅灰色'}])

    facts = K.extract_facts(events, llm, ['客厅地板·颜色'])
    assert facts[0]['subject'] == '客厅地板' and facts[0]['attr'] == '颜色'


def test_extract_adds_a_new_key_when_none_fits():
    events = [_ev('a', 1, 2, 'user：邻居小禾家孩子生日是十二月二号')]
    stats = {}

    def llm(prompt):
        return _reply((1, 2), [{'subject': '邻居小禾家孩子', 'attr': '生日',
                                'value': '十二月二号'}])

    facts = K.extract_facts(events, llm, ['叶楠·生日'], stats=stats)
    assert facts[0]['subject'] == '邻居小禾家孩子'
    assert stats['new'] == 1 and stats['reused'] == 0 and stats['keys'] == 2


def test_extract_without_known_keys_degrades_to_new_keys():
    events = [_ev('a', 3, 4, 'user：叶楠生日是八月十六')]
    seen = []

    def llm(prompt):
        seen.append(prompt)
        return _reply((3, 4), [{'subject': '叶楠', 'attr': '生日', 'value': '八月十六'}])

    facts = K.extract_facts(events, llm, None)
    assert '暂无已有键' in seen[0]
    assert len(facts) == 1 and facts[0]['attr'] == '生日'


def test_extract_without_llm_returns_nothing():
    facts = K.extract_facts([_ev('a', 1, 2, 'x')], None, ['叶楠·生日'])
    assert facts == []


def test_extract_drops_incomplete_facts():
    events = [_ev('a', 1, 2, 'x')]

    def llm(prompt):
        return _reply((1, 2), [{'subject': '叶楠', 'attr': '', 'value': '八月十六'},
                                {'subject': '', 'attr': '生日', 'value': '八月十六'}])

    assert K.extract_facts(events, llm, []) == []


def test_extract_takes_ts_from_the_event_entries():
    events = [_ev('a', 165, 166, 'x', entries=[{'turn': 165, 'ts': 111.5, 'text': 't'}])]

    def llm(prompt):
        return _reply((165, 166), [{'subject': '叶楠', 'attr': '生日', 'value': '八月十六'}])

    facts = K.extract_facts(events, llm, [])
    assert facts[0]['ts'] == 111.5


def test_two_values_on_one_key_become_one_conflict_row():
    facts = [{'subject': '叶楠', 'attr': '生日', 'value': '八月十六', 'turn': 165, 'ts': 0.0},
             {'subject': '叶楠', 'attr': '生日', 'value': '八月十八', 'turn': 183, 'ts': 0.0}]
    state = K.merge_fact_state({}, facts, turn=183)
    assert list(state) == ['叶楠·生日']
    item = state['叶楠·生日']
    assert item['status'] == 'conflict'
    assert [v['value'] for v in item['values']] == ['八月十六', '八月十八']
    assert [v['turn'] for v in item['values']] == [165, 183]
    assert item['value'] == '八月十六 / 八月十八'
    assert item['superseded_by'] is None


def test_merge_is_incremental_across_batches():
    first = [{'subject': '客厅地板', 'attr': '颜色', 'value': '浅灰色', 'turn': 279, 'ts': 0.0}]
    state = K.merge_fact_state({}, first, turn=279)
    assert state['客厅地板·颜色']['status'] == 'current'
    second = [{'subject': '客厅地板', 'attr': '颜色', 'value': '米色', 'turn': 317, 'ts': 0.0}]
    state = K.merge_fact_state(state, second, turn=317)
    item = state['客厅地板·颜色']
    assert item['status'] == 'conflict'
    assert [v['value'] for v in item['values']] == ['浅灰色', '米色']


def test_merge_repeated_value_does_not_add_a_second_row():
    facts = [{'subject': '叶楠', 'attr': '生日', 'value': '八月十六', 'turn': 165, 'ts': 0.0},
             {'subject': '叶楠', 'attr': '生日', 'value': '八月十六', 'turn': 200, 'ts': 0.0}]
    state = K.merge_fact_state({}, facts, turn=200)
    assert state['叶楠·生日']['status'] == 'current'
    assert [v['value'] for v in state['叶楠·生日']['values']] == ['八月十六']


def test_state_line_states_values_turns_and_whether_it_is_settled():
    item = {'status': 'conflict', 'value': '八月十六 / 八月十八',
            'coexist': ['八月十六', '八月十八'], 'source_turn': 183,
            'values': [{'value': '八月十六', 'turn': 165},
                       {'value': '八月十八', 'turn': 183}]}
    line = K.state_line('叶楠·生日', item)
    assert line == '【状态】叶楠·生日：八月十六（第165轮） / 八月十八（第183轮），未确定（2 种说法并存）'
    single = {'value': '夏夏', 'source_turn': 125}
    assert K.state_line('用户·称呼', single) == '【状态】用户·称呼：夏夏（第125轮），已确定'


def test_state_lines_only_for_multi_value_keys_mentioned_by_the_event():
    state = {'叶楠·生日': {'status': 'conflict', 'value': '八月十六 / 八月十八',
                          'values': [{'value': '八月十六', 'turn': 165},
                                     {'value': '八月十八', 'turn': 183}]},
             '用户·称呼': {'value': '夏夏', 'source_turn': 125}}
    ev = {'start': 183, 'end': 184, 'overview': '用户核对日历，叶楠生日定为八月十八',
          'entries': [{'turn': 183, 'text': '不对，叶楠生日是八月十八'}]}
    lines = K.state_lines_for(ev, state)
    assert len(lines) == 1 and lines[0].startswith('【状态】叶楠·生日：')
    assert '未确定' in lines[0]
    assert K.state_lines_for({'overview': '无关的话'}, state) == []


def test_prepend_state_lines_puts_the_state_on_top_of_the_block():
    state = {'叶楠·生日': {'status': 'conflict', 'value': 'a / b',
                          'values': [{'value': 'a', 'turn': 1}, {'value': 'b', 'turn': 2}]}}
    ev = {'start': 2, 'end': 3, 'overview': '叶楠生日', 'entries': []}
    lines = K.prepend_state_lines(['【事件｜第2-3轮】叶楠生日'], ev, state)
    assert lines[0].startswith('【状态】叶楠·生日：')
    assert lines[1] == '【事件｜第2-3轮】叶楠生日'
    assert K.prepend_state_lines(['x'], ev, {}) == ['x']


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('OK', name)
    print('all keynorm tests passed')
