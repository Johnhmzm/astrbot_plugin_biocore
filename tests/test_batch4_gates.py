# -*- coding: utf-8 -*-
"""13 批次原子门禁、14 配置白名单。"""
import pytest

from biocore_runtime import pipeline as P


def test_atomic_gate_is_on_by_default():
    assert P.ATOMIC_BLOCKS is True


def test_over_budget_block_is_rejected_whole(tmp_path):
    store = str(tmp_path)
    entries = [{"id": "e%d" % i, "turn": i, "ts": 1794000000 + i,
                "role": "user", "text": "第 %d 条内容，写得长一点便于超预算" % i}
               for i in range(6)]
    P.save_memory(store, "s", entries)
    # 预算小到连块头加折叠行都装不下：旧行为交付半块，现在必须整块回退
    out = P._sentence_recall_block(store, "s", "内容", entries, [], budget_chars=10)
    assert out.get("atomic_rejected") is True
    assert out.get("text") == ""
    assert out.get("reason") == "over_budget"
    assert out.get("over_by", 0) > 0


def test_config_keeps_declared_keys():
    doc = {"embedding": {"model": "x"}, "sanitize_reply": True,
           "recall_mode": "query", "switches": {"body": True}}
    out = P.sanitize_config(doc)
    assert set(out) == {"embedding", "sanitize_reply", "recall_mode", "switches"}
    assert out["switches"] == {"body": True}


def test_config_drops_unknown_keys():
    out = P.sanitize_config({"embedding": {}, "totally_made_up": 1})
    assert "totally_made_up" not in out
    assert "totally_made_up(未声明)" in P.CONFIG_DROPPED.get("last", [])


def test_config_drops_wrong_types():
    out = P.sanitize_config({"summarizer": "应该是对象", "sanitize_reply": "yes"})
    assert "summarizer" not in out
    assert "sanitize_reply" not in out


def test_switches_keep_only_booleans():
    out = P.sanitize_config({"switches": {"body": True, "memory": "true", "x": 1}})
    assert out["switches"] == {"body": True}


def test_non_dict_config_is_dropped():
    assert P.sanitize_config(None) == {}
    assert P.sanitize_config([1, 2]) == {}
