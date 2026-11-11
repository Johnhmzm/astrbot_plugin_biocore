# -*- coding: utf-8 -*-
"""三个守卫：功能关闭要出声、注入内容要有边界、坏数值不许渲染。"""
import pytest

from biocore_runtime import pipeline as P


def test_require_feature_is_silent_when_on(tmp_path):
    store = str(tmp_path)
    assert P._require_feature(store, P.BODY_SWITCH_KEY, {P.BODY_SWITCH_KEY: True}) is True


def test_require_feature_raises_in_strict_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "_STRICT_FEATURES", True)
    with pytest.raises(P.ModeDisabled):
        P._require_feature(str(tmp_path), P.BODY_SWITCH_KEY, {P.BODY_SWITCH_KEY: False})


def test_untrusted_fence_wraps_and_marks_data():
    out = P._fence_untrusted("- 她说生日是 3 月 5 日")
    assert P.UNTRUSTED_OPEN in out and P.UNTRUSTED_CLOSE in out
    assert P.UNTRUSTED_NOTE in out
    assert out.index(P.UNTRUSTED_OPEN) < out.index("生日") < out.index(P.UNTRUSTED_CLOSE)


def test_empty_text_is_not_fenced():
    assert P._fence_untrusted("   ") == ""


def test_body_values_are_validated():
    assert P._body_values_healthy({"valence": 0.2, "arousal": 0.5, "stress": 0.1})
    assert not P._body_values_healthy({"valence": 9.0})
    assert not P._body_values_healthy({"stress": -1.0})
    assert not P._body_values_healthy({"valence": float("nan")})


def test_broken_body_is_not_rendered():
    state = {"body": {"valence": 99.0, "stress": 0.5}, "norm": {"valence": 1.0}}
    text = P._state_block(state, 400)
    assert "身上" not in text
    assert "σ" not in text


def test_healthy_body_still_renders():
    state = {"body": {"valence": 0.2, "stress": 0.2, "action": "speak"},
             "norm": {"valence": -0.5}}
    text = P._state_block(state, 400)
    assert "此刻" in text
