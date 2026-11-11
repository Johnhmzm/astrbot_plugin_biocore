# -*- coding: utf-8 -*-
"""chains 接进注入块：同一属性多次说法的撤回标注。"""
import json

from biocore_runtime import pipeline as P


def _rows():
    return [
        {"turn": 3, "ts": 1794000000.0, "text": "周六不去看展了", "vector": [1.0, 0.0] },
        {"turn": 9, "ts": 1794000500.0, "text": "说错了，周六还是去看展", "vector": [0.98, 0.19] },
    ]


def test_chain_marks_the_retracted_value():
    lines = P._chains_lines(_rows(), lambda prompt: json.dumps({"retract": True}))
    text = "\n".join(lines)
    assert "【时间链" in text
    assert "已作废" in text
    assert "当前值" in text


def test_one_model_call_per_pair_and_memoised():
    calls = []
    def llm(prompt):
        calls.append(prompt)
        return json.dumps({"retract": False})
    P.CHAIN_CACHE.clear()
    P._chains_lines(_rows(), llm)
    first = len(calls)
    P._chains_lines(_rows(), llm)
    assert first == 1
    assert len(calls) == first, "同一链条不应重复问模型"


def test_without_a_summarizer_nothing_is_rendered():
    assert P._chains_lines(_rows(), None) == []


def test_single_item_is_not_a_chain():
    rows = [{"turn": 1, "ts": 1.0, "text": "只有一句", "vector": [1.0, 0.0]}]
    assert P._chains_lines(rows, lambda p: '{"retract": true}') == []


def test_switch_off_disables_chains(monkeypatch):
    monkeypatch.setattr(P, "CHAINS_ON", False)
    assert P._chains_lines(_rows(), lambda p: '{"retract": true}') == []
