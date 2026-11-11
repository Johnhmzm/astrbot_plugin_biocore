# -*- coding: utf-8 -*-
"""keynorm 接进合并路径：同一个属性的不同说法要落回同一个键。"""
from biocore_memory.event import claims as C
from biocore_memory.event import keynorm as K


def test_same_attr_under_qualified_subject_merges():
    rows = [
        {"subject": "客厅地板", "attr": "颜色", "value": "浅木色",
         "turn": 3, "confidence": 0.7},
        {"subject": "合租房客厅地板", "attr": "颜色", "value": "深棕色",
         "turn": 9, "confidence": 0.6},
    ]
    table = C.merge_claims(rows)
    assert list(table) == ["客厅地板·颜色"]
    values = [v["value"] for v in table["客厅地板·颜色"]["values"]]
    assert values == ["浅木色", "深棕色"]


def test_merging_does_not_hide_a_conflict():
    rows = [
        {"subject": "客厅地板", "attr": "颜色", "value": "浅木色",
         "turn": 3, "confidence": 0.7},
        {"subject": "客厅地板", "attr": "颜色", "value": "深棕色",
         "turn": 9, "confidence": 0.7},
    ]
    table = C.merge_claims(rows)
    values = table["客厅地板·颜色"]["values"]
    assert len(values) == 2, "两种说法必须并列，不能覆盖"
    assert values[0]["confidence"] < 0.7, "旧值应被后来者削弱"


def test_different_attrs_stay_apart():
    rows = [
        {"subject": "叶楠", "attr": "生日", "value": "3月5日", "turn": 1},
        {"subject": "叶楠", "attr": "身高", "value": "165", "turn": 2},
    ]
    table = C.merge_claims(rows)
    assert set(table) == {"叶楠·生日", "叶楠·身高"}


def test_normalize_key_is_mechanical_only():
    # 只做机械归并：完全相同的键、或主体是已有主体的限定形式
    assert K.normalize_key("叶楠", "生日", ["叶楠·生日"]) == "叶楠·生日"
    assert K.normalize_key("合租房客厅地板", "颜色", ["客厅地板·颜色"]) == "客厅地板·颜色"
    # 语义不同的一律不猜
    assert K.normalize_key("叶楠", "日历日期", ["叶楠·生日"]) == ""
