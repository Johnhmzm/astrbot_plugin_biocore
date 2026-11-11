# -*- coding: utf-8 -*-
"""逻辑身份落库：重排、换 id、重新导入都不该改变它。"""
from biocore_memory.store import sql_store as S


def _write(store, rid, text, ts=1794000000.0):
    S.write_doc(store, "s", {"entries": [{"id": rid, "turn": 1, "ts": ts,
                                     "role": "user", "text": text}]})
    return (S.read_doc(store, "s").get("entries") or [])[0]


def test_semantic_id_is_written(tmp_path):
    row = _write(str(tmp_path), "a", "同一句话")
    assert row["semantic_id"].startswith("S")
    assert row["code"] == "M0001"


def test_same_content_in_a_fresh_store_gets_the_same_identity(tmp_path):
    one = _write(str(tmp_path / "one"), "pk-1", "同一句话")
    two = _write(str(tmp_path / "two"), "pk-999", "同一句话")
    assert one["semantic_id"] == two["semantic_id"], "内容相同即同一条记忆"
    assert one["id"] != two["id"], "物理主键仍然是各自独立的"


def test_different_text_gets_a_different_identity(tmp_path):
    one = _write(str(tmp_path / "one"), "a", "甲")
    two = _write(str(tmp_path / "two"), "b", "乙")
    assert one["semantic_id"] != two["semantic_id"]


def test_identity_is_kept_on_rewrite(tmp_path):
    store = str(tmp_path)
    first = _write(store, "a", "同一句话")
    again = _write(store, "a", "同一句话")
    assert again["semantic_id"] == first["semantic_id"]
