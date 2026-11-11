# -*- coding: utf-8 -*-
"""19 单根不变量：一个会话只该有一套自洽的状态。"""
import json
import os

from biocore_runtime import state_health as H


def _sess(tmp_path, sid="s"):
    d = os.path.join(str(tmp_path), "sessions", sid)
    os.makedirs(d, exist_ok=True)
    return d


def test_empty_session_has_no_contradiction(tmp_path):
    assert H.contradictions(str(tmp_path), "s") == []


def test_norm_without_body_is_reported(tmp_path):
    d = _sess(tmp_path)
    json.dump({"rows": {}}, open(os.path.join(d, "mindbase_norm.json"), "w"))
    issues = H.contradictions(str(tmp_path), "s")
    assert any("norm 存在但 body 不在" in x for x in issues)


def test_future_clock_is_reported_and_repaired(tmp_path):
    d = _sess(tmp_path)
    future = 4102444800.0        # 2100-01-01
    json.dump({"last": future}, open(os.path.join(d, "mindbase_clock.json"), "w"))
    issues = H.contradictions(str(tmp_path), "s", now=1794000000.0)
    assert any("时钟在未来" in x for x in issues)
    assert H.repair_clock(str(tmp_path), "s", now=1794000000.0) is True
    assert H.contradictions(str(tmp_path), "s", now=1794000000.0) == []


def test_inventory_lists_all_roots(tmp_path):
    inv = H.inventory(str(tmp_path), "s")
    assert set(inv) == set(H.ROOTS)
    assert all(v["exists"] is False for v in inv.values())
