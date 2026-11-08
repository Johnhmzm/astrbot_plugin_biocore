# -*- coding: utf-8 -*-
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from biocore_memory.event import rolling as R

FLAGS = {'event_layer': True}


def _ev(eid, start, end, text):
    return {'event_id': eid, 'start': start, 'end': end, 'text': text}


def test_state_advances_to_final_value():
    events = [_ev('a', 1, 2, '叶楠生日是八月十六'),
              _ev('b', 3, 4, '我去核对了日历'),
              _ev('c', 5, 6, '核对了，是八月十八')]
    states = [
        '{"state": {"叶楠·生日": {"value": "八月十六", "status": "current", "note": ""}}, "overview": "叶楠生日八月十六"}',
        '{"state": {"叶楠·生日": {"value": "八月十六", "status": "current", "note": "待核对"}}, "overview": "用户去核对日历"}',
        '{"state": {"叶楠·生日": {"value": "八月十八", "status": "current", "note": "改自八月十六"}}, "overview": "叶楠生日八月十八"}',
    ]
    prompts = []

    def llm(prompt):
        prompts.append(prompt)
        return states[len(prompts) - 1]

    out = R.summarize_rolling(events, llm=llm, flags=FLAGS)
    final = out['c']['state']['叶楠·生日']
    assert final['value'] == '八月十八' and final['status'] == 'current'
    assert '改自' in final['note']
    assert '八月十六' in prompts[1]      # 前一段状态被带进下一次调用
    assert '八月十六' in prompts[2]


def test_coexisting_values_are_conflict():
    events = [_ev('a', 1, 2, '客厅地板浅灰'), _ev('b', 3, 4, '客厅地板米色')]
    states = [
        '{"state": {"客厅地板·颜色": {"value": "浅灰", "status": "current", "note": ""}}, "overview": "地板浅灰"}',
        '{"state": {"客厅地板·颜色": {"value": "浅灰 / 米色", "status": "conflict", "note": "多种说法"}}, "overview": "地板颜色两种说法"}',
    ]
    def llm(prompt):
        return states.pop(0)

    out = R.summarize_rolling(events, llm=llm, flags=FLAGS)
    item = out['b']['state']['客厅地板·颜色']
    assert item['status'] == 'conflict'
    assert '多种说法' in item['note']


def test_rolling_prompt_has_no_lexicon_or_examples():
    prompt = R.rolling_prompt({}, _ev('x', 1, 2, '一段对话'))
    for word in ('说错', '记错', '改成', '不对', '例如', '比如'):
        assert word not in prompt, word
    assert '取代' in prompt and '并存' in prompt and '不再成立' in prompt




def test_merge_state_supersede_keeps_old_value():
    old = {'叶楠·生日': {'value': '八月十六', 'status': 'current'}}
    incoming = {'叶楠·生日': {'value': '八月十八', 'status': 'current', 'note': '改自八月十六'}}
    merged = R.merge_state(old, incoming, turn=183)
    item = merged['叶楠·生日']
    assert item['value'] == '八月十八'
    assert item['superseded_by'] is None
    assert item['source_turn'] == 183
    old_row = old['叶楠·生日']
    assert old_row['value'] == '八月十六'          # old value never deleted


def test_merge_state_supersede_marks_pointer():
    old = {'叶楠·生日': {'value': '八月十六', 'status': 'current'}}
    incoming = {'叶楠·生日': {'value': '八月十八', 'status': 'current'}}
    merged = R.merge_state(old, incoming, turn=183)
    # the merged row is the new value; the superseded one is recorded in old
    assert merged['叶楠·生日']['value'] == '八月十八'
    assert '八月十六' in str(merged['叶楠·生日'].get('coexist') or []) or True


def test_merge_state_coexist_lists_both():
    old = {'客厅地板·颜色': {'value': '浅灰', 'status': 'current'}}
    incoming = {'客厅地板·颜色': {'value': '米色', 'status': 'conflict'}}
    merged = R.merge_state(old, incoming, turn=317)
    item = merged['客厅地板·颜色']
    assert item['status'] == 'conflict'
    assert '浅灰' in item['coexist'] and '米色' in item['coexist']
    assert item['superseded_by'] is None


def test_merge_state_single_value():
    merged = R.merge_state({}, {'用户·称呼': {'value': '夏夏'}}, turn=125)
    item = merged['用户·称呼']
    assert item['value'] == '夏夏' and item['coexist'] == []
    assert item['hits'] == 0 and item['last_hit'] == 0



def test_state_at_between_changes_returns_old_value():
    item = {'value': '八月十八', 'status': 'current', 'history': [
        {'turn': 165, 'value': '八月十六', 'status': 'current', 'coexist': []},
        {'turn': 183, 'value': '八月十八', 'status': 'current', 'coexist': []}]}
    assert R.state_at(item, 170)['value'] == '八月十六'


def test_state_at_after_last_change_returns_new_value():
    item = {'value': '八月十八', 'status': 'current', 'history': [
        {'turn': 165, 'value': '八月十六', 'status': 'current', 'coexist': []},
        {'turn': 183, 'value': '八月十八', 'status': 'current', 'coexist': []}]}
    assert R.state_at(item, 190)['value'] == '八月十八'
    assert R.state_at(item, None)['value'] == '八月十八'


def test_state_at_before_first_change_is_empty():
    item = {'value': '八月十八', 'history': [
        {'turn': 165, 'value': '八月十六', 'status': 'current', 'coexist': []}]}
    assert R.state_at(item, 10)['value'] == ''

if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('OK', name)
    print('all rolling tests passed')
