# -*- coding: utf-8 -*-
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


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('OK', name)
    print('all keynorm tests passed')
