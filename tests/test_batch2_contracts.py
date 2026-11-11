# -*- coding: utf-8 -*-
"""第二批三条：请求级作用域、写集版本戳、副作用回执。"""
import pytest

from biocore_runtime import memory_revision as R
from biocore_runtime import mindbase_bridge as B
from biocore_runtime import receipts as RC


needs_mindbase = pytest.mark.skipif(not B.available(), reason="mindbase not importable here")


@needs_mindbase
def test_theta_scope_overrides_module_override(tmp_path):
    B._THETA_OVERRIDE.clear()
    with B.theta_scope({"push_gain": 0.9}):
        assert B.eff("push_gain", 0.35) == 0.9
    assert B.eff("push_gain", 0.35) == 0.35


@needs_mindbase
def test_two_scopes_do_not_leak(tmp_path):
    with B.theta_scope({"push_gain": 0.1}):
        inner = B.eff("push_gain", 0.35)
    with B.theta_scope({"push_gain": 0.7}):
        outer = B.eff("push_gain", 0.35)
    assert (inner, outer) == (0.1, 0.7)
    assert B.eff("push_gain", 0.35) == 0.35


def test_revision_bumps_and_stale_write_is_rejected(tmp_path):
    store = str(tmp_path)
    rev = R.current_revision(store, "s")
    assert rev == 0
    R.assert_fresh(store, "s", rev)
    R.bump_revision(store, "s", write_set=["entry:1"])
    assert R.current_revision(store, "s") == 1
    with pytest.raises(R.StaleWrite):
        R.assert_fresh(store, "s", rev)


def test_write_set_is_recorded(tmp_path):
    store = str(tmp_path)
    R.bump_revision(store, "s", write_set=["b", "a"])
    doc = R._load(store, "s")
    assert doc["last_write_set"] == ["a", "b"]


def test_receipts_flag_the_missing_side_effect(tmp_path):
    store = str(tmp_path)
    fp = RC.fingerprint("s", "你好", "在。")
    RC.record(store, "s", "grade", fp)
    RC.record(store, "s", "turn_log", fp)
    assert RC.missing_kinds(store, "s") == ["learn_log"]
    RC.record(store, "s", "learn_log", fp)
    assert RC.missing_kinds(store, "s") == []


def test_fingerprint_is_stable_and_distinct():
    a = RC.fingerprint("s", "你好", "在。")
    b = RC.fingerprint("s", "你好", "在。")
    c = RC.fingerprint("s", "你好", "不在。")
    assert a == b != c
