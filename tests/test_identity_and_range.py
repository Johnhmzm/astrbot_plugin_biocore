# -*- coding: utf-8 -*-
"""16 身份分离、17 地址即读集、18 回放可续。"""
import os

import pytest

from biocore_memory import semantic_identity as I
from biocore_runtime import mindbase_bridge as B
from biocore_runtime import pipeline as P

needs_mindbase = pytest.mark.skipif(not B.available(), reason="mindbase not importable here")


def test_semantic_id_ignores_storage_id():
    a = {"id": "pk-1", "ts": 1794000000.0, "role": "user", "text": "同一句话"}
    b = {"id": "pk-999", "ts": 1794000000.0, "role": "user", "text": "同一句话"}
    assert I.semantic_id("s", a["ts"], a["role"], a["text"]) == \
           I.semantic_id("s", b["ts"], b["role"], b["text"])
    assert I.same_memory("s", a, b) is True


def test_different_text_is_a_different_memory():
    a = {"id": "1", "ts": 1.0, "role": "user", "text": "甲"}
    b = {"id": "2", "ts": 1.0, "role": "user", "text": "乙"}
    assert I.same_memory("s", a, b) is False


def test_storage_id_is_not_derived_from_content():
    assert I.storage_id_of({"id": "pk-7", "text": "x"}) == "pk-7"
    assert I.storage_id_of({"text": "x"}) == ""


def test_resume_point_is_none_before_any_run(tmp_path):
    assert B.idle_resume_point(str(tmp_path), "s") is None


@needs_mindbase
def test_resume_point_records_the_last_run(tmp_path):
    store = str(tmp_path)
    B.mirror_recall(store, "s", ["- 一句话"], valence=0.2)
    B.idle_activity(store, "s", now=1794000000.0)
    assert B.idle_resume_point(store, "s") == 1794000000.0


def test_range_recall_uses_position_when_turn_is_missing(tmp_path):
    store = str(tmp_path)
    rows = [{"id": "a%d" % i, "ts": 1794000000 + i, "role": "user",
             "text": "第 %d 句" % i} for i in range(1, 6)]
    B.save_state(store, "s", {"valence": 0.0})
    os.makedirs(os.path.join(store, "sessions", "s"), exist_ok=True)
    doc = {"entries": rows}
    B.store_write_doc(store, "s", doc) if hasattr(B, "store_write_doc") else None
    out = P.inject_block("s", store, max_chars=2000, payload={"turn_range": [2, 3]})
    assert out.get("mode") == "range"
