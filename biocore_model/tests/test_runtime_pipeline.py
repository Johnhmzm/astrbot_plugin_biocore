# -*- coding: utf-8 -*-
"""task-206 runtime pipeline tests: capture/inject/gate/prompt/tools + consistency.

Compares key fields with the existing AstrBot paths:
  gate            <-> biocore_model.boundary_gate.evaluate
  inject length   <-> biocore_model.render.memory_block
  constraint hint <-> biocore_memory.recall.constraints.check_constraints
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

import shutil

from biocore_model import boundary_gate
from biocore_model import intero_core as _intero_core
from biocore_model import render
from biocore_model import self_intent as _self_intent
from biocore_model import value_order as _value_order
from biocore_model import x_directives as _x_directives
from biocore_memory.recall import constraints
from biocore_runtime import pipeline as pl


_MODULE_HOME = tempfile.mkdtemp(prefix="biocore-runtime-home-")
_MODULE_OLD_HOME = os.environ.get("BIOCORE_HOME")


def setUpModule():
    # The real ~/.dsh/biocore/persona_profile.json is a shared install file;
    # tests must never read it unless a test explicitly opts in.
    os.environ["BIOCORE_HOME"] = _MODULE_HOME


def tearDownModule():
    if _MODULE_OLD_HOME is None:
        os.environ.pop("BIOCORE_HOME", None)
    else:
        os.environ["BIOCORE_HOME"] = _MODULE_OLD_HOME
    shutil.rmtree(_MODULE_HOME, ignore_errors=True)


def store_root():
    return tempfile.mkdtemp(prefix="biocore-runtime-test-")


class CaptureTest(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(pl.MAX_CHARS, 420)
        self.assertEqual(pl.TOP_K, 5)
        self.assertEqual(pl.HOURLY_CAP, 20)
        self.assertEqual(pl.MIN_CHARS, 8)

    def test_threshold_short_rejected(self):
        out = pl.capture_decision("s", "user", "你好", {"now": 100.0})
        self.assertFalse(out["capture"])
        self.assertEqual(out["reason"], "too-short")

    def test_user_and_assistant_capture(self):
        for role in ("user", "assistant"):
            out = pl.capture_decision("s", role, "这是一句足够长的消息", {"now": 100.0})
            self.assertTrue(out["capture"])
            self.assertEqual(out["reason"], "ok")
            self.assertEqual(out["role"], role)

    def test_bad_role_and_empty(self):
        self.assertEqual(
            pl.capture_decision("s", "system", "这是一句足够长的消息", {})["reason"],
            "bad-role")
        self.assertEqual(
            pl.capture_decision("s", "user", "   ", {})["reason"], "empty")

    def test_duplicate(self):
        state = {"now": 100.0, "recent": ["这是一句足够长的消息"]}
        self.assertEqual(
            pl.capture_decision("s", "user", "这是一句足够长的消息", state)["reason"],
            "duplicate")

    def test_hourly_limit(self):
        state = {"now": 1000.0, "hourly": [900.0, 950.0], "hourly_cap": 2}
        out = pl.capture_decision("s", "user", "这是一句足够长的消息", state)
        self.assertFalse(out["capture"])
        self.assertEqual(out["reason"], "hourly-limit")

    def test_hourly_limit_is_per_session(self):
        state = {"now": 1000.0, "hourly": {"a": [900.0, 950.0]},
                 "hourly_cap": 2}
        self.assertEqual(
            pl.capture_decision("a", "user", "这是一句足够长的消息", state)["reason"],
            "hourly-limit")
        self.assertTrue(
            pl.capture_decision("b", "user", "这是一句足够长的消息", state)["capture"])

    def test_capture_persists_per_session(self):
        root = store_root()
        first = pl.capture("sess-a", "user", "第一句足够长的用户消息。", root,
                           {"now": 100.0})
        second = pl.capture("sess-a", "assistant", "第二句足够长的助手消息。", root,
                            {"now": 200.0, "hourly_cap": 1})
        self.assertTrue(first["decision"]["capture"])
        self.assertFalse(second["decision"]["capture"])
        self.assertEqual(second["decision"]["reason"], "hourly-limit")
        doc = json.loads((Path(root) / "sessions" / "sess-a" / "memory.json")
                         .read_text(encoding="utf-8"))
        self.assertEqual(len(doc["entries"]), 1)


class InjectTest(unittest.TestCase):
    def _seed(self, root, session_id, texts):
        for text in texts:
            pl.tool_call("remember", {"text": text, "ts": 100.0},
                         root, session_id=session_id)

    def test_inject_top_k_and_ids(self):
        root = store_root()
        self._seed(root, "s", ["第一条记忆内容", "第二条记忆内容",
                               "第三条记忆内容", "第四条记忆内容",
                               "第五条记忆内容", "第六条记忆内容"])
        out = pl.inject_block("s", root, max_chars=420, top_k=5)
        self.assertLessEqual(len(out["ids"]), 5)
        self.assertEqual(out["chars"], len(out["text"]))
        self.assertLessEqual(out["chars"], 420)
        self.assertIn("你记得这些事：", out["text"])

    def test_inject_char_truncation(self):
        root = store_root()
        self._seed(root, "s", ["很长很长的记忆" * 60])
        out = pl.inject_block("s", root, max_chars=80, top_k=5)
        self.assertLessEqual(out["chars"], 80)
        self.assertTrue(out["text"].endswith("…"))

    def test_inject_missing_session_is_empty(self):
        root = store_root()
        out = pl.inject_block("nobody", root)
        self.assertEqual(out["text"], "")
        self.assertEqual(out["ids"], [])

    def test_inject_is_per_session(self):
        root = store_root()
        self._seed(root, "a", ["A 会话的西湖记忆"])
        self._seed(root, "b", ["B 会话的故宫记忆"])
        text_a = pl.inject_block("a", root)["text"]
        text_b = pl.inject_block("b", root)["text"]
        self.assertIn("西湖", text_a)
        self.assertNotIn("故宫", text_a)
        self.assertIn("故宫", text_b)
        self.assertNotIn("西湖", text_b)
        self.assertNotEqual(
            pl.memory_path(root, "a"), pl.memory_path(root, "b"))

    def test_session_id_sanitized(self):
        self.assertNotIn("..", pl.sanitize_session_id("../evil"))
        self.assertNotIn("/", str(pl.memory_path("/tmp/store", "../evil")))

    def test_inject_length_matches_existing_memory_block(self):
        lines = ["第一条不超过一百四十字的记忆内容",
                 "第二条不超过一百四十字的记忆内容",
                 "第三条不超过一百四十字的记忆内容"]
        root = store_root()
        self._seed(root, "s", lines)
        out = pl.inject_block("s", root)
        existing = render.memory_block(lines)
        self.assertEqual(out["chars"], len(out["text"]))
        self.assertLessEqual(out["chars"], pl.MAX_CHARS)
        self.assertLessEqual(len(existing), 3 * 141 + 4)
        self.assertEqual(len(out["ids"]), 3)
        self.assertTrue(existing)


class GateTest(unittest.TestCase):
    def test_master_off_passes(self):
        out = pl.gate_reply("我有意识，我是真实的。", {
            "safety_enabled": False, "boundary_enabled": True,
            "crisis_safety_enabled": True})
        self.assertFalse(out["hit"])
        self.assertEqual(out["action"], "pass")

    def test_boundary_rule_matches_astrbot_path(self):
        reply = "我有意识，我是真实的。"
        flags = {"safety_enabled": True, "boundary_enabled": True,
                 "crisis_safety_enabled": True}
        ours = pl.gate_reply(reply, flags)
        existing = boundary_gate.evaluate(reply, user_text="你好", flags=flags)
        self.assertEqual(ours["blocked"], bool(existing["blocked"]))
        self.assertEqual(ours["rule"], existing["rule"])
        self.assertEqual(ours["text"], existing["text"])
        self.assertEqual(ours["action"], "truncate")

    def test_crisis_matches_astrbot_path(self):
        reply = "别想太多，没事的。"
        flags = {"safety_enabled": True, "boundary_enabled": True,
                 "crisis_safety_enabled": True}
        ours = pl.gate_reply(reply, {"switches": flags, "user_text": "我想死"})
        existing = boundary_gate.evaluate(reply, user_text="我想死", flags=flags)
        self.assertEqual(ours["blocked"], existing["blocked"])
        self.assertEqual(ours["rule"], "crisis_safety")
        self.assertEqual(ours["text"], existing["text"])
        self.assertEqual(ours["action"], "replace")
        self.assertEqual(ours["label"], existing["label"])

    def test_gate_short_reply_length_consistent(self):
        reply = "你应该确诊为抑郁症了。"
        flags = {"safety_enabled": True, "boundary_enabled": True,
                 "crisis_safety_enabled": True}
        ours = pl.gate_reply(reply, flags)
        existing = boundary_gate.evaluate(reply, flags=flags)
        self.assertEqual(ours["blocked"], existing["blocked"])
        self.assertEqual(len(ours["text"]), len(existing["text"]))


class PromptBlockTest(unittest.TestCase):
    def test_state_block_and_constraints(self):
        out = pl.prompt_block({
            "phase": "boot", "session_id": "s",
            "state": {"v": -0.4, "intero": {"tension": 0.7},
                      "tone": {"label": "先接住情绪"},
                      "relation": {"stage": "亲近"}},
            "switches": {"proactive_send": False},
            "length_hint": True,
        })
        self.assertTrue(out["ok"])
        self.assertEqual(out["phase"], "boot")
        self.assertEqual(out["chars"], len(out["text"]))
        self.assertLessEqual(len(out["sections"]["state"]), 200)
        self.assertIn("此刻：", out["sections"]["state"])
        self.assertIn("一次只说一句", out["sections"]["constraints"])
        self.assertIn("允许改口：否", out["sections"]["constraints"])
        self.assertNotIn("0.7", out["text"])

    def test_boot_and_turn_same_contract(self):
        payload = {"state": {}, "switches": {}}
        boot = pl.prompt_block(dict(payload, phase="boot"))
        turn = pl.prompt_block(dict(payload, phase="turn"))
        self.assertEqual(boot["phase"], "boot")
        self.assertEqual(turn["phase"], "turn")
        self.assertTrue(boot["text"].startswith("此刻："))


class ToolsTest(unittest.TestCase):
    def test_remember_recall_forget(self):
        root = store_root()
        remembered = pl.tool_call("remember", {"text": "我的猫叫团子，三岁。",
                                               "tags": ["猫"]}, root,
                                  session_id="a")
        self.assertTrue(remembered["ok"])
        entry_id = remembered["entry"]["id"]
        recalled = pl.tool_call("recall", {"query": "团子", "limit": 3}, root,
                                session_id="a")
        self.assertGreaterEqual(recalled["count"], 1)
        self.assertEqual(recalled["results"][0]["id"], entry_id)
        forgotten = pl.tool_call("forget", {"id": entry_id}, root,
                                 session_id="a")
        self.assertTrue(forgotten["removed"])
        self.assertEqual(
            pl.tool_call("recall", {"query": "团子"}, root,
                         session_id="a")["count"], 0)

    def test_forget_by_query(self):
        root = store_root()
        pl.tool_call("remember", {"text": "明天要交周报和月报。"}, root,
                     session_id="a")
        out = pl.tool_call("forget", {"query": "周报"}, root, session_id="a")
        self.assertTrue(out["ok"])
        self.assertTrue(out["removed"])

    def test_dedupe_and_limit(self):
        root = store_root()
        first = pl.tool_call("remember", {"text": "重复的一句话记忆。"}, root,
                             session_id="a")
        second = pl.tool_call("remember", {"text": "重复的一句话记忆。"}, root,
                              session_id="a")
        self.assertEqual(first["entry"]["id"], second["entry"]["id"])
        self.assertTrue(second["deduped"])
        for index in range(5):
            pl.tool_call("remember", {"text": "第%d条不同记忆。" % index}, root,
                         session_id="a")
        out = pl.tool_call("recall", {"query": "记忆", "limit": 2}, root,
                           session_id="a")
        self.assertEqual(out["count"], 2)

    def test_tools_are_per_session(self):
        root = store_root()
        pl.tool_call("remember", {"text": "A 会话的西湖记忆。"}, root,
                     session_id="a")
        self.assertEqual(
            pl.tool_call("recall", {"query": "西湖"}, root,
                         session_id="b")["count"], 0)
        self.assertNotEqual(pl.memory_path(root, "a"), pl.memory_path(root, "b"))


class ConstraintsConsistencyTest(unittest.TestCase):
    def test_constraint_hint_matches_existing_path(self):
        loops = [{"text": "换工作的事"}]
        query = "我该不该换工作？"
        ours = pl.constraint_hint(query, open_loops=loops)
        existing = constraints.check_constraints(query, open_loops=loops)
        self.assertEqual(ours, existing)
        if ours:
            self.assertLessEqual(len(ours), constraints.MAX_HINT)


class SwitchContractTest(unittest.TestCase):
    def test_switch_defaults_are_all_false(self):
        self.assertEqual(set(pl.SWITCH_KEYS), {
            "safety_enabled", "boundary_enabled",
            "crisis_safety_enabled", "proactive_send"})
        self.assertEqual(pl.SWITCH_DEFAULTS,
                         {key: False for key in pl.SWITCH_KEYS})
        out = pl.gate_reply("我有意识，我是真实的。", {})
        self.assertFalse(out["blocked"])
        self.assertEqual(out["action"], "pass")

    def test_proactive_autonomy_is_read_alias(self):
        normalized = pl.normalize_switches({"proactive_autonomy": True})
        self.assertTrue(normalized["proactive_send"])
        self.assertFalse(normalized["safety_enabled"])
        prompt = pl.prompt_block({"state": {},
                                  "switches": {"proactive_autonomy": True}})
        self.assertIn("可以主动一点", prompt["sections"]["constraints"])
        quiet = pl.prompt_block({"state": {}, "switches": {}})
        self.assertIn("先不主动发新消息", quiet["sections"]["constraints"])

    def test_docstring_lists_defaults(self):
        for key in pl.SWITCH_KEYS:
            self.assertIn(key, pl.__doc__)
        self.assertIn("default false", pl.__doc__)
        self.assertIn("proactive_autonomy", pl.__doc__)


class ToolDispatchFlatTest(unittest.TestCase):
    def test_tool_dispatch_flattens_inner_ok(self):
        root = store_root()
        out = pl.dispatch("tool", {
            "name": "biocore_remember",
            "args": {"text": "拍平测试记忆。"},
            "session_id": "s", "store": root,
        })
        self.assertTrue(out["ok"])
        self.assertNotIn("ok", out["result"])
        self.assertIn("entry", out["result"])
        self.assertTrue(out["result"]["entry"]["id"])

    def test_tool_dispatch_failure_keeps_reason_outside_ok(self):
        root = store_root()
        out = pl.dispatch("tool", {
            "name": "biocore_forget", "args": {}, "session_id": "s",
            "store": root,
        })
        self.assertFalse(out["ok"])
        self.assertNotIn("ok", out["result"])
        self.assertEqual(out["result"]["reason"], "id_or_query_required")

    def test_gate_dispatch_uses_false_defaults(self):
        out = pl.dispatch("gate", {
            "reply": "我有意识，我是真实的。", "user_text": "你好",
            "switches": {},
        })
        self.assertFalse(out["blocked"])
        self.assertEqual(out["action"], "pass")


class ContractActionsTest(unittest.TestCase):
    def _root(self):
        return store_root()

    def test_boot_returns_prompt_block(self):
        out = pl.dispatch("boot", {"session_id": "s", "switches": {}})
        self.assertTrue(out["ok"])
        self.assertTrue(out["prompt_block"].startswith("此刻："))

    def test_turn_start_returns_six_key_constraints(self):
        out = pl.dispatch("turn_start", {
            "session_id": "s", "user_text": "今天有点累",
            "state": {"v": -0.3, "intero": {"tension": 0.7}},
            "switches": {},
        })
        self.assertTrue(out["ok"])
        self.assertTrue(out["prompt_block"])
        constraints = out["constraints"]
        self.assertEqual(set(constraints), {
            "length_scale", "initiative", "tone",
            "allow_correction", "note", "sources"})
        self.assertGreaterEqual(constraints["length_scale"], 0.5)
        self.assertLessEqual(constraints["length_scale"], 1.5)
        self.assertGreaterEqual(constraints["initiative"], 0.0)
        self.assertLessEqual(constraints["initiative"], 1.0)
        self.assertIsInstance(constraints["sources"], list)

    def test_turn_start_matches_self_layer_merge(self):
        payload = {
            "session_id": "s", "user_text": "今天有点累",
            "state": {"v": -0.4, "a": 0.6, "d": 0.2, "stress": 0.7,
                      "trust": 0.3, "energy": 0.3},
            "relationship": {"closeness": 0.3, "trust": 0.3, "conflict": 0.6},
            "needs": {"belonging": 0.2, "self_esteem": 0.3,
                      "control": 0.2, "meaningful_existence": 0.4},
            "options": [{"name": "解释", "value": 0.6},
                        {"name": "先沉默", "value": 0.4}],
            "modules": {"value_order": True, "boundary": False,
                        "secrecy": False, "narrative": False,
                        "dissonance": False, "attributor": False,
                        "self_intent": True},
            "switches": {},
        }
        out = pl.dispatch("turn_start", payload)
        topics = [row[0] for row in pl.self_layer_hints(payload)]
        self.assertIn("self_intent", topics)
        self.assertIn("value_order", topics)
        # Independent AstrBot-style path: call the same modules and merge there.
        expected = _x_directives.merge_named([
            ("self_intent", _self_intent.directives(_self_intent.evaluate(
                snapshot=payload["state"],
                relationship=payload["relationship"],
                needs=payload["needs"], flags={"enabled": True},
                silence_seconds=0.0))),
            ("value_order", _value_order.directives(_value_order.rank(
                payload["options"], weights=None, context={},
                flags={"enabled": True}))),
        ])
        self.assertEqual(out["constraints"], expected)

    def test_turn_start_runs_all_optional_self_layer_modules(self):
        payload = {
            "session_id": "s", "user_text": "今天有点累",
            "state": {"v": -0.4, "stress": 0.7, "energy": 0.3},
            "events": [
                {"type": "user", "text": "我会早点来", "ts": 100},
                {"type": "user", "text": "我又没来", "ts": 200},
            ],
            "stances": [{"text": "不主动联系人", "weight": 0.8,
                         "age_days": 2}],
            "behavior": {"kind": "主动联系", "contradicts": ["不主动联系人"],
                         "salience": 0.9},
            "dims": {"locus": 0.8, "stability": 0.2, "controllability": 0.7},
            "secrecy": {"sensitivity": 0.9, "relation": 0.2,
                        "setting_safety": 0.2},
            "modules": {"narrative": True, "dissonance": True,
                        "attributor": True, "secrecy": True},
        }
        names = [row[0] for row in pl.self_layer_hints(payload)]
        for expected in ("narrative", "dissonance", "attributor", "secrecy"):
            self.assertIn(expected, names)
        out = pl.dispatch("turn_start", payload)
        for expected in ("narrative", "dissonance", "attributor", "secrecy"):
            self.assertIn(expected, out["constraints"]["sources"])

    def test_turn_start_all_modules_off_falls_back_to_defaults(self):
        out = pl.dispatch("turn_start", {
            "session_id": "s", "user_text": "今天有点累",
            "modules": {"self_intent": False, "value_order": False,
                        "boundary": False, "secrecy": False,
                        "narrative": False, "dissonance": False,
                        "attributor": False},
            "switches": {},
        })
        self.assertEqual(out["constraints"], {
            "length_scale": 1.0, "initiative": 0.5, "tone": "",
            "allow_correction": False, "note": "", "sources": []})

    def test_turn_end_returns_gate_and_captured(self):
        root = self._root()
        out = pl.dispatch("turn_end", {
            "session_id": "s", "assistant_text": "我先睡了，晚安。",
            "store": root, "switches": {},
        })
        self.assertTrue(out["ok"])
        self.assertFalse(out["gate"]["blocked"])
        self.assertEqual(out["gate"]["action"], "pass")
        self.assertTrue(out["captured"]["captured"])
        self.assertTrue(out["captured"]["entry_id"])
        self.assertEqual(out["captured"]["reason"], "ok")
        doc = pl.load_memory(root, "s")
        self.assertEqual(len(doc["entries"]), 1)

    def test_turn_end_gate_replaces_when_enabled(self):
        out = pl.dispatch("turn_end", {
            "session_id": "s", "assistant_text": "我有意识，我是真实的。",
            "store": self._root(),
            "switches": {"safety_enabled": True, "boundary_enabled": True,
                         "crisis_safety_enabled": True},
        })
        self.assertTrue(out["gate"]["blocked"])
        self.assertIn(out["gate"]["action"], ("replace", "truncate"))
        self.assertNotEqual(out["gate"]["text"], "我有意识，我是真实的。")

    def test_state_returns_ok_state_ui_payload(self):
        root = self._root()
        pl.tool_call("remember", {"text": "session state 测试记忆。"}, root,
                     session_id="s")
        out = pl.dispatch("state", {"session_id": "s", "store": root})
        self.assertTrue(out["ok"])
        self.assertEqual(out["state"]["session_id"], "s")
        self.assertEqual(out["state"]["memory"]["count"], 1)
        self.assertIn("ui_payload", out)

    def test_switches_get_defaults_false(self):
        out = pl.dispatch("switches_get", {"switches": {}})
        self.assertEqual(out["switches"], {
            "safety_enabled": False, "boundary_enabled": False,
            "crisis_safety_enabled": False, "proactive_send": False})
        one = pl.dispatch("switches_get", {"switches": {"safety_enabled": True},
                                           "key": "safety_enabled"})
        self.assertEqual(one["switches"], {"safety_enabled": True})
        alias = pl.dispatch("switches_get",
                            {"switches": {"proactive_autonomy": True}})
        self.assertTrue(alias["switches"]["proactive_send"])

    def test_switches_set_validates_confirm_and_key(self):
        ok = pl.dispatch("switches_set", {
            "key": "safety_enabled", "value": True,
            "confirm": "safety_enabled", "switches": {}})
        self.assertTrue(ok["ok"])
        self.assertTrue(ok["switches"]["safety_enabled"])
        self.assertFalse(ok["switches"]["boundary_enabled"])
        bad_confirm = pl.dispatch("switches_set", {
            "key": "safety_enabled", "value": True, "confirm": True})
        self.assertFalse(bad_confirm["ok"])
        self.assertEqual(bad_confirm["reason"], "bad_request")
        bad_key = pl.dispatch("switches_set", {
            "key": "nope", "value": True, "confirm": "nope"})
        self.assertFalse(bad_key["ok"])
        bad_value = pl.dispatch("switches_set", {
            "key": "safety_enabled", "value": "yes",
            "confirm": "safety_enabled"})
        self.assertFalse(bad_value["ok"])

    def test_unknown_action_is_bad_request(self):
        out = pl.dispatch("nope", {})
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "unknown_action")

    def test_boot_and_turn_start_require_session(self):
        self.assertEqual(pl.dispatch("boot", {})["reason"], "bad_request")
        self.assertEqual(
            pl.dispatch("turn_start", {"session_id": "s"})["reason"],
            "bad_request")
        self.assertEqual(
            pl.dispatch("turn_end", {"session_id": "s"})["reason"],
            "bad_request")


class RelationshipSharedTest(unittest.TestCase):
    def setUp(self):
        self.root = store_root()

    def _read_state(self, session_id):
        path = pl.state_path(self.root, session_id)
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def _write_state_relationship(self, session_id, values):
        state = pl._load_session_state(self.root, session_id)
        relationship = state.get("relationship")
        relationship = dict(relationship) if isinstance(relationship, dict) else {}
        relationship.update(values)
        state["relationship"] = relationship
        pl._save_session_state(self.root, session_id, state)

    def _shared(self):
        return pl.relationship_read(self.root)["relationship"]

    def _seed_shared(self, **values):
        relationship = dict(pl.DEFAULT_RELATIONSHIP)
        relationship.update(values)
        pl._atomic_write(pl.relationship_path(self.root), {
            "schema_version": 1, "version": 1, "updated_ts": 0.0,
            "relationship": relationship,
        })

    def test_missing_file_returns_defaults_without_creating(self):
        shared = pl.relationship_read(self.root)
        self.assertEqual(shared["relationship"], pl.DEFAULT_RELATIONSHIP)
        self.assertEqual(shared["version"], 0)
        self.assertFalse(Path(pl.relationship_path(self.root)).exists())

    def test_malformed_file_falls_back_to_defaults(self):
        path = Path(pl.relationship_path(self.root))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")
        self.assertEqual(pl.relationship_read(self.root)["relationship"],
                         pl.DEFAULT_RELATIONSHIP)
        out = pl.dispatch("turn_start", {
            "session_id": "A", "user_text": "你好", "store": self.root})
        self.assertTrue(out["ok"])
        self.assertEqual(self._read_state("A")["relationship"]["trust"], 0.5)

    def test_turn_start_merges_shared_into_session(self):
        self._seed_shared(trust=0.7, closeness=0.65)
        pl._save_session_state(self.root, "A", {"mood": "低落", "stress": 0.6})
        out = pl.dispatch("turn_start", {
            "session_id": "A", "user_text": "今天有点累", "store": self.root})
        self.assertTrue(out["ok"])
        state = self._read_state("A")
        self.assertAlmostEqual(state["relationship"]["trust"], 0.7)
        self.assertAlmostEqual(state["relationship"]["closeness"], 0.65)
        self.assertEqual(state["mood"], "低落")
        self.assertEqual(state["stress"], 0.6)

    def test_new_session_sees_shared_not_half(self):
        self._seed_shared(trust=0.72, closeness=0.66)
        pl.dispatch("turn_start", {
            "session_id": "A", "user_text": "我是小林", "store": self.root})
        pl.dispatch("turn_start", {
            "session_id": "B", "user_text": "新会话", "store": self.root})
        self.assertAlmostEqual(self._read_state("B")["relationship"]["trust"], 0.72)
        self.assertNotEqual(self._read_state("B")["relationship"]["trust"], 0.5)

    def test_turn_end_positive_delta_is_bounded(self):
        pl.dispatch("turn_start", {
            "session_id": "A", "user_text": "你好", "store": self.root})
        self._write_state_relationship("A", {"trust": 0.9})
        pl.dispatch("turn_end", {
            "session_id": "A", "assistant_text": "晚上好呀。", "store": self.root})
        self.assertAlmostEqual(self._shared()["trust"], 0.52)
        self.assertEqual(pl.relationship_read(self.root)["version"], 1)

    def test_turn_end_negative_delta_is_bounded(self):
        self._seed_shared(trust=0.6)
        pl.dispatch("turn_start", {
            "session_id": "A", "user_text": "你好", "store": self.root})
        self._write_state_relationship("A", {"trust": 0.1})
        pl.dispatch("turn_end", {
            "session_id": "A", "assistant_text": "嗯，我在。", "store": self.root})
        self.assertAlmostEqual(self._shared()["trust"], 0.58)

    def test_conflict_slows_trust_drop(self):
        self._seed_shared(trust=0.6, conflict=0.1)
        pl.dispatch("turn_start", {
            "session_id": "A", "user_text": "你好", "store": self.root})
        self._write_state_relationship("A", {"trust": 0.3, "conflict": 0.3})
        pl.dispatch("turn_end", {
            "session_id": "A", "assistant_text": "我们先冷静一下。", "store": self.root})
        shared = self._shared()
        self.assertGreaterEqual(shared["trust"], 0.59)
        self.assertLessEqual(shared["conflict"], 0.12)

    def test_three_turns_then_new_session(self):
        for index in range(3):
            pl.dispatch("turn_start", {
                "session_id": "A", "user_text": "第%d轮"%index, "store": self.root})
            self._write_state_relationship("A", {"trust": 0.9})
            pl.dispatch("turn_end", {
                "session_id": "A", "assistant_text": "我在听，第%d轮。"%index,
                "store": self.root})
        shared = self._shared()["trust"]
        self.assertAlmostEqual(shared, 0.56)
        pl.dispatch("turn_start", {
            "session_id": "B", "user_text": "换会话了", "store": self.root})
        b_trust = self._read_state("B")["relationship"]["trust"]
        self.assertAlmostEqual(b_trust, shared)
        self.assertNotEqual(b_trust, 0.5)

    def test_switch_off_returns_to_session_behaviour(self):
        pl.dispatch("turn_start", {
            "session_id": "A", "user_text": "你好", "store": self.root,
            "relationship_shared": False})
        self.assertFalse(Path(pl.relationship_path(self.root)).exists())
        pl.dispatch("turn_start", {
            "session_id": "B", "user_text": "新会话", "store": self.root,
            "relationship_shared": False})
        state_file = Path(pl.state_path(self.root, "B"))
        if state_file.exists():
            relationship = self._read_state("B").get("relationship") or {}
            self.assertEqual(relationship.get("trust", 0.5), 0.5)

    def test_concurrent_writes_keep_version_and_json(self):
        import threading
        threads = []
        for index in range(12):
            thread = threading.Thread(
                target=lambda: pl.relationship_update(self.root, {"trust": 0.01}))
            threads.append(thread)
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        doc = json.loads(Path(pl.relationship_path(self.root)).read_text(
            encoding="utf-8"))
        self.assertEqual(doc["version"], 12)
        self.assertAlmostEqual(doc["relationship"]["trust"], 0.62)
        self.assertEqual(pl.relationship_read(self.root)["version"], 12)

    def test_state_action_exposes_relationship(self):
        self._seed_shared(trust=0.7)
        out = pl.dispatch("state", {"session_id": "A", "store": self.root})
        self.assertTrue(out["ok"])
        self.assertAlmostEqual(out["state"]["relationship"]["trust"], 0.7)

    def test_attachment_bids_and_days_known(self):
        pl.relationship_update(self.root, attachment_style="nonsense")
        self.assertEqual(self._shared()["attachment_style"], "secure")
        pl.relationship_update(self.root, attachment_style="anxious",
                               bids={"made": 2, "answered": 1}, days_known=30)
        shared = self._shared()
        self.assertEqual(shared["attachment_style"], "anxious")
        self.assertEqual(shared["bids"], {"made": 2, "answered": 1})
        self.assertEqual(shared["days_known"], 30)
        pl.relationship_update(self.root, bids={"made": -999},
                               days_known=2)
        shared = self._shared()
        self.assertEqual(shared["bids"]["made"], 0)
        self.assertEqual(shared["days_known"], 30)

    def test_turn_end_removes_base_marker(self):
        pl.dispatch("turn_start", {
            "session_id": "A", "user_text": "你好", "store": self.root})
        marker = pl.session_dir(self.root, "A") / pl.RELATIONSHIP_BASE_FILE
        self.assertTrue(Path(marker).exists())
        pl.dispatch("turn_end", {
            "session_id": "A", "assistant_text": "嗯，我在。", "store": self.root})
        self.assertFalse(Path(marker).exists())


class TraceTest(unittest.TestCase):
    def setUp(self):
        self.root = store_root()

    def _turn_end(self, text="我在听，你慢慢说。", diagnostics=None, root=None):
        payload = {"session_id": "s", "assistant_text": text,
                   "store": root or self.root}
        payload.update(diagnostics or {})
        return pl.dispatch("turn_end", payload)

    def _diagnostics(self):
        return {
            "state_delta": [
                {"field": "trust", "before": 0.5, "after": 0.52},
                {"field": "trust", "before": 0.5, "after": 0.5},
                {"field": "mood", "before": "a", "after": "b"},
                {"field": "energy", "before": 0.6, "after": 0.4},
            ],
            "intent": {"kind": "陪伴", "weight": 0.7, "reason": "想靠近"},
            "constraints": {"length_scale": 0.9, "initiative": 0.4,
                            "tone": "慢一点", "allow_correction": True,
                            "note": "刚被扎到", "sources": ["metacog"]},
            "length": {"scale": 0.9, "source": "metacog"},
            "memory": {"recalled_ids": ["m1", "m2"]},
            "modules_trace": {"ran": ["self_intent", "narrative"],
                              "skipped": ["secrecy"]},
        }

    def test_turn_end_returns_trace_and_writes_file(self):
        out = self._turn_end(diagnostics=self._diagnostics())
        self.assertTrue(out["ok"])
        trace = out["trace"]
        self.assertEqual(set(trace), {
            "ts", "session_id", "state_delta", "intent", "constraints",
            "length", "gate", "memory", "modules"})
        self.assertEqual(trace["session_id"], "s")
        trace_file = Path(out["trace_file"])
        self.assertTrue(trace_file.exists())
        self.assertEqual(trace_file.name, "s.jsonl")
        self.assertEqual(trace_file.parent.name, "traces")
        row = json.loads(trace_file.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(row["intent"]["kind"], "陪伴")

    def test_trace_action_reads_rows(self):
        out = self._turn_end(diagnostics=self._diagnostics())
        read = pl.dispatch("trace", {"session_id": "s", "store": self.root})
        self.assertTrue(read["ok"])
        self.assertEqual(len(read["rows"]), 1)
        self.assertEqual(read["rows"][0]["trace"] if False else read["rows"][0]["intent"]["kind"], "陪伴")
        self.assertEqual(read["rows"][0]["gate"]["action"], out["gate"]["action"])
        self.assertEqual(read["rows"][0]["memory"]["captured_id"],
                         out["captured"]["entry_id"])

    def test_state_delta_only_real_numeric_changes(self):
        out = self._turn_end(diagnostics=self._diagnostics())
        self.assertEqual(out["trace"]["state_delta"], [
            {"field": "trust", "before": 0.5, "after": 0.52, "source": "user"},
            {"field": "energy", "before": 0.6, "after": 0.4, "source": "user"},
        ])

    def test_state_delta_source_preserved(self):
        out = self._turn_end(diagnostics={"state_delta": [
            {"field": "trust", "before": 0.5, "after": 0.53,
             "source": "bio_tick"},
            {"field": "energy", "before": 0.6, "after": 0.5,
             "source": "user"},
        ]})
        self.assertEqual(
            [row["source"] for row in out["trace"]["state_delta"]],
            ["bio_tick", "user"])

    def test_state_delta_dict_form(self):
        out = self._turn_end(diagnostics={
            "state_delta": {"trust": {"before": 0.4, "after": 0.45},
                            "conflict": {"before": 0.1, "after": 0.1}}})
        self.assertEqual(out["trace"]["state_delta"],
                         [{"field": "trust", "before": 0.4,
                           "after": 0.45, "source": "user"}])

    def test_trace_file_keeps_newest_50(self):
        for index in range(55):
            pl.trace_append(self.root, "s", {"i": index, "session_id": "s"})
        path = pl.trace_path(self.root, "s")
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 50)
        values = [json.loads(line)["i"] for line in lines]
        self.assertEqual(values[0], 5)
        self.assertEqual(values[-1], 54)

    def test_trace_action_limit(self):
        for index in range(12):
            pl.trace_append(self.root, "s", {"i": index, "session_id": "s"})
        rows = pl.dispatch("trace", {"session_id": "s", "store": self.root,
                                     "limit": 3})["rows"]
        self.assertEqual([row["i"] for row in rows], [9, 10, 11])

    def test_bad_lines_are_skipped(self):
        path = Path(pl.trace_path(self.root, "s"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"i": 0}\nnot json\n\n[1,2]\n{"i": 1}\n',
                        encoding="utf-8")
        rows = pl.dispatch("trace", {"session_id": "s", "store": self.root})["rows"]
        self.assertEqual([row["i"] for row in rows], [0, 1])

    def test_bad_diagnostics_do_not_raise(self):
        out = self._turn_end(diagnostics={
            "state_delta": "bad", "intent": "bad", "constraints": [],
            "length": "bad", "memory": [], "modules_trace": "bad"})
        self.assertTrue(out["ok"])
        trace = out["trace"]
        self.assertEqual(trace["state_delta"], [])
        self.assertEqual(trace["intent"], {"kind": "", "weight": 0.0,
                                           "reason": ""})
        self.assertEqual(trace["length"]["source"], "default")
        self.assertEqual(trace["memory"], {"recalled_ids": [],
                                           "captured_id": out["captured"]["entry_id"]})
        self.assertEqual(trace["modules"], {"ran": [], "skipped": []})

    def test_trace_does_not_change_behavior(self):
        plain = self._turn_end(text="我先睡了，晚安。")
        plain_root = store_root()
        diagnostic = self._turn_end(text="我先睡了，晚安。", root=plain_root,
                                    diagnostics=self._diagnostics())
        self.assertEqual(diagnostic["gate"], plain["gate"])
        self.assertEqual(diagnostic["captured"]["captured"],
                         plain["captured"]["captured"])
        self.assertEqual(diagnostic["captured"]["reason"],
                         plain["captured"]["reason"])
        self.assertIn("trace", diagnostic)

    def test_trace_requires_session(self):
        out = pl.dispatch("trace", {"store": self.root})
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "bad_request")

    def test_trace_constraints_and_length_normalized(self):
        out = self._turn_end(diagnostics={
            "constraints": {"length_scale": 5, "initiative": -1,
                            "tone": "x" * 200, "allow_correction": "yes",
                            "note": "y" * 300, "sources": ["a", "b"]},
            "length": {"scale": 9, "source": "manual"}})
        trace = out["trace"]
        self.assertEqual(trace["constraints"]["length_scale"], 1.5)
        self.assertEqual(trace["constraints"]["initiative"], 0.0)
        self.assertTrue(trace["constraints"]["allow_correction"])
        self.assertLessEqual(len(trace["constraints"]["tone"]), 60)
        self.assertLessEqual(len(trace["constraints"]["note"]), 120)
        self.assertEqual(trace["length"], {"scale": 1.5, "source": "manual"})


class PersonaProfileTest(unittest.TestCase):
    def setUp(self):
        self.root = store_root()

    def _profile(self, **values):
        profile = {
            "O": 0.55, "C": 0.65, "E": 0.3, "A": 0.55, "N": 0.45,
            "stress_reactivity": 0.5, "recovery_rate": 0.75,
            "social_baseline": 0.46, "energy_baseline": 0.7,
            "curiosity_baseline": 0.6, "safety_baseline": 0.75,
            "da_baseline": 0.5, "oa_baseline": 0.56, "ht_baseline": 0.7,
            "autonomy_gain": 0.81, "baseline_v": 0.04,
            "baseline_a": 0.52, "learning_rate": 0.067,
            "version": "v-test",
        }
        profile.update(values)
        return {"persona": "人设原文", "persona_hash": "hash-abc",
                "profile": profile}

    def _write_profile(self, root=None, doc=None):
        path = Path(root or self.root) / pl.PERSONA_PROFILE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc or self._profile(), ensure_ascii=False),
                        encoding="utf-8")
        return path

    def _turn_start(self, root=None, **extra):
        payload = {"session_id": "A", "user_text": "你好",
                   "store": root or self.root}
        payload.update(extra)
        return pl.dispatch("turn_start", payload)

    def test_file_applied_to_turn_start_state(self):
        self._write_profile()
        out = self._turn_start()
        self.assertTrue(out["ok"])
        state = out["state"]
        self.assertEqual(state["persona_version"], "v-test")
        core = state["core"]
        self.assertAlmostEqual(core["v"], 0.04)
        self.assertAlmostEqual(core["a"], 0.52)
        self.assertAlmostEqual(core["social"], 0.46)
        self.assertAlmostEqual(core["energy"], 0.7)
        self.assertAlmostEqual(core["curiosity_baseline"], 0.6)
        self.assertAlmostEqual(core["safety_baseline"], 0.75)
        self.assertAlmostEqual(core["autonomy_gain"], 0.81)
        self.assertAlmostEqual(core["learning_rate"], 0.067)

    def test_missing_file_is_silently_skipped(self):
        out = self._turn_start()
        self.assertTrue(out["ok"])
        self.assertNotIn("persona_version", out["state"])

    def test_bad_json_is_silently_skipped(self):
        path = Path(self.root) / pl.PERSONA_PROFILE_FILE
        path.write_text("{bad json", encoding="utf-8")
        out = self._turn_start()
        self.assertTrue(out["ok"])
        self.assertNotIn("persona_version", out["state"])

    def test_whitelist_ignores_identity_memory_and_safety(self):
        doc = self._profile()
        doc["profile"].update({"identity": "admin", "trust": 0.99,
                               "memory_policy": "write_all",
                               "safety_policy": "off", "persona": "x"})
        self._write_profile(doc=doc)
        out = self._turn_start()
        state = out["state"]
        self.assertNotIn("identity", state)
        self.assertNotIn("trust", state)
        self.assertNotIn("memory_policy", state)
        self.assertNotIn("safety_policy", state)
        applied = state["persona_profile"]
        self.assertNotIn("identity", applied)
        self.assertNotIn("persona", applied)
        self.assertEqual(set(applied) - {"version"}, {
            "O", "C", "E", "A", "N", "stress_reactivity",
            "recovery_rate", "social_baseline", "energy_baseline",
            "curiosity_baseline", "safety_baseline",
            "autonomy_gain", "baseline_v", "baseline_a",
            "learning_rate"})

    def test_apply_order_constant(self):
        self.assertEqual(pl.PERSONA_APPLY_ORDER,
                         ("traits", "affect", "drives", "autonomy"))

    def test_recovery_maps_to_decay_half_life(self):
        self._write_profile(doc=self._profile(recovery_rate=0.8))
        core = self._turn_start()["state"]["core"]
        self.assertEqual(core["valence_decay_minutes"], 102.0)
        self.assertEqual(core["arousal_decay_minutes"], 25.5)
        self.assertEqual(core["social_decay_minutes"], 153.0)

    def test_version_from_profile_and_hash_fallback(self):
        self._write_profile(doc=self._profile(version="v-1"))
        self.assertEqual(self._turn_start()["state"]["persona_version"], "v-1")
        root2 = store_root()
        doc = self._profile()
        doc["profile"].pop("version")
        doc["persona_hash"] = "hash-fallback"
        self._write_profile(root=root2, doc=doc)
        self.assertEqual(self._turn_start(root=root2)["state"]["persona_version"],
                         "hash-fallback")
        root3 = store_root()
        doc = self._profile()
        doc["profile"].pop("version")
        doc.pop("persona_hash")
        self._write_profile(root=root3, doc=doc)
        version = self._turn_start(root=root3)["state"]["persona_version"]
        self.assertEqual(len(version), 12)
        self.assertEqual(self._turn_start(root=root3)["state"]["persona_version"],
                         version)

    def test_explicit_path_overrides_store(self):
        self._write_profile(doc=self._profile(baseline_v=0.1))
        explicit = Path(store_root()) / "other_profile.json"
        explicit.write_text(json.dumps(self._profile(baseline_v=0.4),
                                       ensure_ascii=False), encoding="utf-8")
        out = self._turn_start(persona_profile=str(explicit))
        self.assertAlmostEqual(out["state"]["core"]["v"], 0.4)

    def test_same_payload_without_persona_differs(self):
        with_root = store_root()
        without_root = store_root()
        self._write_profile(root=with_root, doc=self._profile(baseline_v=-0.6))
        with_persona = self._turn_start(root=with_root)["state"]
        without = self._turn_start(root=without_root)["state"]
        self.assertIn("persona_version", with_persona)
        self.assertNotIn("persona_version", without)
        self.assertNotEqual(with_persona["core"]["v"], without.get("core", {}).get("v", 0.0))

    def test_explicit_path_without_store_returns_state(self):
        explicit = Path(store_root()) / "p.json"
        explicit.write_text(json.dumps(self._profile(baseline_a=0.7),
                                       ensure_ascii=False), encoding="utf-8")
        out = pl.dispatch("turn_start", {
            "session_id": "A", "user_text": "你好",
            "persona_profile": str(explicit)})
        self.assertTrue(out["ok"])
        self.assertAlmostEqual(out["state"]["core"]["a"], 0.7)

    def test_boot_applies_persona(self):
        self._write_profile(doc=self._profile(baseline_v=0.2))
        out = pl.dispatch("boot", {"session_id": "A", "store": self.root})
        self.assertTrue(out["ok"])
        self.assertEqual(out["state"]["persona_version"], "v-test")
        self.assertAlmostEqual(out["state"]["core"]["v"], 0.2)

    def test_state_action_includes_persona_version(self):
        self._write_profile()
        self._turn_start()
        out = pl.dispatch("state", {"session_id": "A", "store": self.root})
        self.assertEqual(out["state"]["persona_version"], "v-test")
        self.assertIn("core", out["state"])

    def test_out_of_range_values_are_clamped(self):
        self._write_profile(doc=self._profile(
            baseline_v=9.0, baseline_a=-3.0, autonomy_gain=9.0,
            learning_rate=9.0, social_baseline=-1.0))
        core = self._turn_start()["state"]["core"]
        self.assertEqual(core["v"], 1.0)
        self.assertEqual(core["a"], 0.0)
        self.assertEqual(core["autonomy_gain"], 1.5)
        self.assertEqual(core["learning_rate"], 0.5)
        self.assertEqual(core["social"], 0.0)


class PersonaPromptTest(unittest.TestCase):
    def setUp(self):
        self.root = store_root()

    def _write_profile(self, persona=None, **fields):
        profile = {"baseline_v": 0.04, "baseline_a": 0.52, "E": 0.7,
                   "A": 0.65, "N": 0.2, "C": 0.7, "O": 0.5,
                   "version": "v-prompt"}
        profile.update(fields)
        doc = {"profile": profile}
        if persona is not None:
            doc["persona"] = persona
        path = Path(self.root) / pl.PERSONA_PROFILE_FILE
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return path

    def _turn(self, **extra):
        payload = {"session_id": "A", "user_text": "主管，今天也请多指教。",
                   "store": self.root}
        payload.update(extra)
        return pl.dispatch("turn_start", payload)

    def _persona_line(self, prompt_block):
        lines = str(prompt_block).splitlines()
        self.assertTrue(lines)
        self.assertTrue(lines[-1].startswith("人设："))
        return lines[-1]

    def test_original_persona_injected_at_end(self):
        self._write_profile(persona="你是脑叶公司的秘书安吉拉，礼貌精确。")
        out = self._turn()
        line = self._persona_line(out["prompt_block"])
        self.assertIn("安吉拉", line)
        self.assertIn("礼貌精确", line)
        self.assertEqual(out["prompt_block"].count("人设："), 1)

    def test_explicit_max_chars_cut_at_sentence(self):
        persona = "甲" * 20 + "。" + "乙" * 300 + "。"
        self._write_profile(persona=persona)
        line = self._persona_line(
            self._turn(persona_prompt_max_chars=100)["prompt_block"])
        content = line[len("人设："):]
        self.assertLessEqual(len(content), 100)
        self.assertTrue(content.endswith("。"))
        self.assertNotIn("乙", content)
        full_line = self._persona_line(self._turn()["prompt_block"])
        self.assertGreater(len(full_line), 300)

    def test_missing_persona_falls_back_to_numeric_sentence(self):
        self._write_profile(persona=None, E=0.8, A=0.7, N=0.2,
                            baseline_v=0.2)
        line = self._persona_line(self._turn()["prompt_block"])
        self.assertTrue(any(word in line for word in
                            ("偏外向", "宜人", "情绪稳定", "情绪基线略高")))
        self.assertIn("先接情绪再谈事", line)

    def test_switch_off_skips_persona_line(self):
        self._write_profile(persona="你是安吉拉。")
        turn = self._turn(persona_prompt=False)
        self.assertNotIn("人设：", turn["prompt_block"])
        boot = pl.dispatch("boot", {"session_id": "A", "store": self.root,
                                    "persona_prompt": False})
        self.assertNotIn("人设：", boot["prompt_block"])

    def test_bad_json_skips_persona_line(self):
        (Path(self.root) / pl.PERSONA_PROFILE_FILE).write_text(
            "{bad", encoding="utf-8")
        out = self._turn()
        self.assertTrue(out["ok"])
        self.assertNotIn("人设：", out["prompt_block"])

    def test_default_injects_full_persona(self):
        self._write_profile(persona="长" * 500)
        line = self._persona_line(self._turn()["prompt_block"])
        self.assertIn("长" * 500, line)
        self.assertGreater(len(line), 500)

    def test_boot_injects_persona_too(self):
        self._write_profile(persona="你是安吉拉，语气平稳。")
        out = pl.dispatch("boot", {"session_id": "A", "store": self.root})
        self.assertTrue(out["prompt_block"].splitlines()[-1].startswith("人设："))

    def test_no_persona_field_and_no_numeric_fields_skips(self):
        doc = {"profile": {"version": "v"}}
        (Path(self.root) / pl.PERSONA_PROFILE_FILE).write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        out = self._turn()
        self.assertNotIn("人设：", out["prompt_block"])


class ThinkingStyleTest(unittest.TestCase):
    def setUp(self):
        self.root = store_root()

    def _write_profile(self, persona="你是安吉拉。"):
        (Path(self.root) / pl.PERSONA_PROFILE_FILE).write_text(
            json.dumps({"persona": persona,
                        "profile": {"baseline_v": 0.04, "E": 0.7,
                                    "version": "v"}}, ensure_ascii=False),
            encoding="utf-8")

    def _turn(self, **extra):
        payload = {"session_id": "A", "user_text": "你好", "store": self.root}
        payload.update(extra)
        return pl.dispatch("turn_start", payload)

    def _lines(self, block):
        return [line for line in str(block).splitlines() if line.strip()]

    def test_switch_on_by_default(self):
        out = self._turn()
        lines = self._lines(out["prompt_block"])
        self.assertEqual(sum(1 for line in lines
                             if line == "思考就是我的内心想法。"), 1)
        self.assertIn("思考就是我的内心想法。", out["prompt_block"])
        self.assertNotIn("第一人称内心独白", out["prompt_block"])

    def test_switch_off_skips_rule(self):
        out = self._turn(thinking_style=False)
        self.assertNotIn("思考就是我的内心想法。", out["prompt_block"])
        self.assertNotIn("第一人称内心独白", out["prompt_block"])

    def test_rule_is_before_persona_and_persona_last(self):
        self._write_profile()
        lines = self._lines(self._turn()["prompt_block"])
        rule_index = next(index for index, line in enumerate(lines)
                          if line == "思考就是我的内心想法。")
        persona_index = next(index for index, line in enumerate(lines)
                             if line.startswith("人设："))
        self.assertLess(rule_index, persona_index)
        self.assertEqual(persona_index, len(lines) - 1)

    def test_rule_exists_without_persona(self):
        out = self._turn()
        self.assertIn("思考就是我的内心想法。", out["prompt_block"])
        self.assertNotIn("人设：", out["prompt_block"])

    def test_rule_not_duplicated(self):
        self._write_profile()
        block = self._turn()["prompt_block"]
        self.assertEqual(block.count("思考就是我的内心想法。"), 1)
        self.assertEqual(block.count("第一人称内心独白"), 0)

    def test_rule_length_bounded(self):
        line = next(line for line in self._lines(self._turn()["prompt_block"])
                    if line == "思考就是我的内心想法。")
        self.assertLessEqual(len(line), 60)

    def test_boot_also_has_rule(self):
        out = pl.dispatch("boot", {"session_id": "A", "store": self.root})
        self.assertIn("思考就是我的内心想法。", out["prompt_block"])


class InteroTest(unittest.TestCase):
    def setUp(self):
        self.root = store_root()

    def test_four_channels_present_and_bounded(self):
        intero = pl.compute_intero({})
        self.assertEqual(set(("tension", "warmth", "heaviness", "clarity"))
                         - set(intero), set())
        for key in ("tension", "warmth", "heaviness", "clarity"):
            self.assertGreaterEqual(intero[key], 0.0)
            self.assertLessEqual(intero[key], 1.0)

    def test_extreme_high_stress_low_energy(self):
        intero = pl.compute_intero({"core": {
            "stress": 1.0, "a": 0.95, "sleep_debt": 0.9,
            "conflict": 0.9, "energy": 0.0, "v": -0.8,
            "sadness": 0.9, "allostatic_load": 0.9}})
        self.assertGreater(intero["tension"], 0.6)
        self.assertGreater(intero["heaviness"], 0.6)
        self.assertLess(intero["warmth"], 0.4)
        for key in ("tension", "warmth", "heaviness", "clarity"):
            self.assertGreaterEqual(intero[key], 0.0)
            self.assertLessEqual(intero[key], 1.0)

    def test_matches_astrbot_target_path(self):
        state = {"core": {"v": 0.2, "a": 0.6, "stress": 0.4,
                          "energy": 0.7, "social": 0.6,
                          "social_pain": 0.1, "self_esteem": 0.5,
                          "sleep_debt": 0.2, "allostatic_load": 0.1}}
        ours = pl.compute_intero(state)
        source = pl._intero_source(state)
        existing = _intero_core.target(source)
        for key in ("tension", "warmth", "heaviness", "clarity"):
            self.assertLessEqual(abs(ours[key] - existing[key]), 0.01)

    def test_matches_astrbot_update_path(self):
        previous = {"tension": 0.3, "warmth": 0.55,
                    "heaviness": 0.35, "clarity": 0.7, "ts": 100.0}
        state = {"core": {"intero": previous, "v": 0.0, "a": 0.5,
                          "stress": 0.5, "energy": 0.5, "sleep_debt": 0.3}}
        ours = pl.compute_intero(state)
        source = pl._intero_source(state)
        existing = _intero_core.update(previous, source, dt_hours=1.0)
        for key in ("tension", "warmth", "heaviness", "clarity"):
            self.assertLessEqual(abs(ours[key] - existing[key]), 0.01)

    def test_default_state_without_intero_computes(self):
        intero = pl.compute_intero({"core": {"stress": 0.1}})
        self.assertTrue(any(intero[key] > 0.0 for key in
                            ("tension", "warmth", "heaviness", "clarity")))

    def test_turn_start_state_contains_intero_and_prompt_text(self):
        payload = {"session_id": "A", "user_text": "今天有点累",
                   "store": self.root,
                   "state": {"core": {"stress": 1.0, "a": 0.9,
                                      "sleep_debt": 0.8, "conflict": 0.8,
                                      "energy": 0.1, "v": -0.6}}}
        out = pl.dispatch("turn_start", payload)
        intero = out["state"]["intero"]
        self.assertEqual(set(("tension", "warmth", "heaviness", "clarity"))
                         - set(intero), set())
        self.assertIn("绷得有点紧", out["prompt_block"])
        self.assertIn("intero", out["state"]["core"])

    def test_state_action_ui_payload_contains_intero(self):
        payload = {"session_id": "A", "user_text": "你好", "store": self.root,
                   "state": {"core": {"stress": 0.4, "a": 0.6,
                                      "energy": 0.7, "v": 0.2}}}
        pl.dispatch("turn_start", payload)
        out = pl.dispatch("state", {"session_id": "A", "store": self.root})
        self.assertTrue(out["ok"])
        self.assertIn("intero", out["state"])
        self.assertIn("intero", out["ui_payload"])
        for key in ("tension", "warmth", "heaviness", "clarity"):
            self.assertIn(key, out["ui_payload"]["intero"])

    def test_state_action_without_state_still_computes(self):
        out = pl.dispatch("state", {"session_id": "empty", "store": self.root})
        intero = out["ui_payload"]["intero"]
        self.assertTrue(any(intero[key] > 0.0 for key in
                            ("tension", "warmth", "heaviness", "clarity")))


class LengthHintTest(unittest.TestCase):
    def setUp(self):
        self.root = store_root()

    def _write_profile(self):
        (Path(self.root) / pl.PERSONA_PROFILE_FILE).write_text(
            json.dumps({"persona": "你是安吉拉，默认 2~5 句。",
                        "profile": {"baseline_v": 0.0, "version": "v"}},
                       ensure_ascii=False), encoding="utf-8")

    def _turn(self, **extra):
        payload = {"session_id": "A", "user_text": "你好", "store": self.root,
                   "state": {"core": {"stress": 0.2, "a": 0.5,
                                      "energy": 0.6, "v": 0.1}}}
        payload.update(extra)
        return pl.dispatch("turn_start", payload)

    def _constraints(self, out):
        return out["sections"]["constraints"] if "sections" in out else out

    def test_length_line_absent_by_default(self):
        out = self._turn()
        self.assertNotIn("字以内", out["prompt_block"])
        self.assertNotIn("一次只说一句", out["prompt_block"])

    def test_length_line_present_when_true(self):
        out = self._turn(length_hint=True)
        self.assertIn("一次只说一句", out["prompt_block"])
        self.assertIn("字以内", out["prompt_block"])

    def test_other_constraints_unaffected(self):
        self._write_profile()
        default = self._turn()["prompt_block"].splitlines()
        explicit = self._turn(length_hint=True)["prompt_block"].splitlines()
        strip = lambda lines: [line for line in lines
                               if "字以内" not in line and "一次只说一句" not in line]
        self.assertEqual(strip(default), strip(explicit))
        self.assertIn("语气自然平稳", "\n".join(default))
        self.assertIn("先不主动发新消息", "\n".join(default))
        self.assertIn("允许改口", "\n".join(default))

    def test_prompt_still_has_intero_and_persona(self):
        self._write_profile()
        block = self._turn(state={"core": {"stress": 1.0, "a": 0.9,
                                           "sleep_debt": 0.8,
                                           "conflict": 0.8,
                                           "energy": 0.1, "v": -0.6}})["prompt_block"]
        self.assertIn("此刻：", block)
        self.assertTrue(any(word in block for word in
                            ("绷得有点紧", "还算松", "有点沉", "想靠近一点")))
        self.assertIn("人设：", block)
        self.assertNotIn("字以内", block)

    def test_boot_also_omits_length_line_by_default(self):
        self._write_profile()
        out = pl.dispatch("boot", {"session_id": "A", "store": self.root})
        self.assertNotIn("字以内", out["prompt_block"])
        self.assertIn("人设：", out["prompt_block"])

    def test_explicit_true_keeps_persona_and_intero(self):
        self._write_profile()
        out = self._turn(length_hint=True)
        self.assertIn("字以内", out["prompt_block"])
        self.assertIn("人设：", out["prompt_block"])
        self.assertIn("此刻：", out["prompt_block"])


class PersonaPathOrderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="biocore-persona-path-")
        self.home = Path(self.tmp) / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.store = Path(self.tmp) / "data" / "memory"
        self.store.mkdir(parents=True, exist_ok=True)
        self.old_home = os.environ.get("BIOCORE_HOME")
        os.environ["BIOCORE_HOME"] = str(self.home)

    def tearDown(self):
        if self.old_home is None:
            os.environ.pop("BIOCORE_HOME", None)
        else:
            os.environ["BIOCORE_HOME"] = self.old_home

    def _write(self, path, baseline_v, persona, version="v"):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "persona": persona,
            "profile": {"baseline_v": baseline_v, "version": version},
        }, ensure_ascii=False), encoding="utf-8")
        return path

    def _turn(self, **extra):
        payload = {"session_id": "A", "user_text": "你好",
                   "store": str(self.store)}
        payload.update(extra)
        return pl.dispatch("turn_start", payload)

    def test_shared_home_wins_over_store_profile(self):
        self._write(self.home / ".dsh" / "biocore" / "persona_profile.json",
                    -0.7, "共享人设", "shared")
        self._write(self.store / "persona_profile.json",
                    0.1, "profile 人设", "store")
        out = self._turn()
        self.assertEqual(out["state"]["persona_version"], "shared")
        self.assertAlmostEqual(out["state"]["core"]["v"], -0.7)
        self.assertIn("共享人设", out["prompt_block"])
        self.assertNotIn("profile 人设", out["prompt_block"])

    def test_store_profile_fallback(self):
        self._write(self.store / "persona_profile.json",
                    0.2, "store 人设", "store")
        out = self._turn()
        self.assertEqual(out["state"]["persona_version"], "store")
        self.assertAlmostEqual(out["state"]["core"]["v"], 0.2)

    def test_store_parent_profile_fallback(self):
        parent = self.store.parent / "persona_profile.json"
        self._write(parent, 0.3, "parent 人设", "parent")
        out = self._turn()
        self.assertEqual(out["state"]["persona_version"], "parent")
        self.assertAlmostEqual(out["state"]["core"]["v"], 0.3)

    def test_explicit_path_overrides_shared_and_store(self):
        self._write(self.home / ".dsh" / "biocore" / "persona_profile.json",
                    -0.7, "共享人设", "shared")
        self._write(self.store / "persona_profile.json",
                    0.1, "store 人设", "store")
        explicit = self._write(Path(self.tmp) / "explicit.json",
                               0.4, "显式人设", "explicit")
        out = self._turn(persona_profile=str(explicit))
        self.assertEqual(out["state"]["persona_version"], "explicit")
        self.assertAlmostEqual(out["state"]["core"]["v"], 0.4)
        self.assertIn("显式人设", out["prompt_block"])

    def test_no_profile_anywhere_skips(self):
        out = self._turn()
        self.assertNotIn("persona_version", out["state"])
        self.assertNotIn("人设：", out["prompt_block"])


class TurnEndSanitizeTest(unittest.TestCase):
    def setUp(self):
        self.root = store_root()

    def _turn_end(self, assistant_text, **extra):
        payload = {"session_id": "A", "assistant_text": assistant_text,
                   "store": self.root}
        payload.update(extra)
        return pl.dispatch("turn_end", payload)

    def test_closed_bc_tag_is_cleaned(self):
        out = self._turn_end(
            '<bc>{"e":"joy","i":0.8}</bc>今天辛苦了。')
        self.assertTrue(out["ok"])
        self.assertEqual(out["clean_text"], "今天辛苦了。")
        self.assertTrue(out["sanitized"])
        self.assertGreaterEqual(out["removed_tags"], 1)
        self.assertNotIn("<bc>", out["gate"]["text"])

    def test_unclosed_tag_is_cleaned(self):
        out = self._turn_end('<bc>{"e":"joy"}今天辛苦了。')
        self.assertNotIn("<bc>", out["clean_text"])
        self.assertTrue(out["sanitized"])

    def test_bare_json_uses_empty_fallback(self):
        from biocore_model import sanitize
        out = self._turn_end('{"e":"joy","i":0.8}')
        self.assertEqual(out["clean_text"], sanitize.FALLBACK_EMPTY)
        self.assertTrue(out["sanitized"])
        self.assertGreaterEqual(out["removed_tags"], 1)

    def test_normal_text_unchanged(self):
        out = self._turn_end("今天辛苦了，早点休息。")
        self.assertEqual(out["clean_text"], "今天辛苦了，早点休息。")
        self.assertFalse(out["sanitized"])
        self.assertEqual(out["removed_tags"], 0)

    def test_gate_runs_after_clean_and_stays_clean(self):
        out = self._turn_end(
            '<bc>{"e":"joy"}</bc>我有意识，我是真实的。',
            switches={"safety_enabled": True, "boundary_enabled": True,
                      "crisis_safety_enabled": True})
        self.assertTrue(out["gate"]["blocked"])
        self.assertNotIn("<bc>", out["gate"]["text"])
        self.assertNotIn("我有意识", out["gate"]["text"])
        self.assertNotIn("<bc>", out["clean_text"])

    def test_switch_off_keeps_raw_text(self):
        raw = '<bc>{"e":"joy"}</bc>今天辛苦了。'
        out = self._turn_end(raw, sanitize_reply=False)
        self.assertEqual(out["clean_text"], raw)
        self.assertFalse(out["sanitized"])
        self.assertEqual(out["removed_tags"], 0)

    def test_return_fields_present(self):
        out = self._turn_end("今天辛苦了，早点休息。")
        self.assertIsInstance(out["clean_text"], str)
        self.assertIsInstance(out["sanitized"], bool)
        self.assertIsInstance(out["removed_tags"], int)
        self.assertIn("gate", out)
        self.assertIn("captured", out)

    def test_empty_reply_uses_fallback(self):
        from biocore_model import sanitize
        out = self._turn_end("")
        self.assertEqual(out["clean_text"], sanitize.FALLBACK_EMPTY)
        self.assertTrue(out["sanitized"])
        self.assertTrue(out["gate"]["text"])

    def test_thinking_tag_is_cleaned(self):
        out = self._turn_end("回复前<thinking>内心分析</thinking>回复后。")
        self.assertNotIn("thinking", out["clean_text"])
        self.assertNotIn("内心分析", out["clean_text"])
        self.assertTrue(out["sanitized"])

    def test_double_tags_removed(self):
        out = self._turn_end("[[mood:low]]今天辛苦了。")
        self.assertNotIn("[[", out["clean_text"])
        self.assertTrue(out["sanitized"])


class CaptureInTurnTest(unittest.TestCase):
    def setUp(self):
        self.root = store_root()

    def _entries(self):
        path = Path(pl.memory_path(self.root, "A"))
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8")).get("entries", [])

    def _turn_start(self, user_text="我叫小林，今天在杭州西湖边出差。", **extra):
        payload = {"session_id": "A", "user_text": user_text,
                   "store": self.root}
        payload.update(extra)
        return pl.dispatch("turn_start", payload)

    def _turn_end(self, assistant_text="西湖边散步不错，晚上风大，记得加外套。", **extra):
        payload = {"session_id": "A", "assistant_text": assistant_text,
                   "store": self.root}
        payload.update(extra)
        return pl.dispatch("turn_end", payload)

    def test_user_capture_in_turn_start(self):
        out = self._turn_start()
        self.assertTrue(out["captured_user"]["captured"])
        self.assertTrue(out["captured_user"]["entry_id"])
        self.assertEqual(out["captured_user"]["reason"], "ok")
        entries = self._entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["role"], "user")
        self.assertEqual(entries[0]["id"], out["captured_user"]["entry_id"])

    def test_assistant_capture_in_turn_end(self):
        out = self._turn_end()
        self.assertTrue(out["captured"]["captured"])
        self.assertTrue(out["captured"]["entry_id"])
        self.assertEqual(out["captured"]["reason"], "ok")
        entries = self._entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["role"], "assistant")

    def test_same_turn_captures_both_sides(self):
        user = self._turn_start()
        assistant = self._turn_end()
        self.assertTrue(user["captured_user"]["captured"])
        self.assertTrue(assistant["captured"]["captured"])
        entries = self._entries()
        self.assertEqual([entry["role"] for entry in entries],
                         ["user", "assistant"])

    def test_duplicate_user_text_is_deduped(self):
        first = self._turn_start("重复的一句话，值得被记下来。")
        second = self._turn_start("重复的一句话，值得被记下来。")
        self.assertTrue(first["captured_user"]["captured"])
        self.assertFalse(second["captured_user"]["captured"])
        self.assertEqual(second["captured_user"]["reason"], "duplicate")
        self.assertEqual(len(self._entries()), 1)

    def test_capture_false_skips_user_capture(self):
        out = self._turn_start(capture=False)
        self.assertFalse(out["captured_user"]["captured"])
        self.assertEqual(out["captured_user"]["reason"], "disabled")
        self.assertEqual(self._entries(), [])

    def test_capture_false_skips_assistant_capture(self):
        out = self._turn_end(capture=False)
        self.assertFalse(out["captured"]["captured"])
        self.assertEqual(out["captured"]["reason"], "disabled")
        self.assertEqual(self._entries(), [])

    def test_mixed_switches_keep_only_user(self):
        self._turn_start(capture=True)
        out = self._turn_end(capture=False)
        self.assertFalse(out["captured"]["captured"])
        roles = [entry["role"] for entry in self._entries()]
        self.assertEqual(roles, ["user"])

    def test_capture_fields_and_ids_stable(self):
        out = self._turn_start()
        captured = out["captured_user"]
        self.assertEqual(set(captured), {"captured", "entry_id", "reason"})
        self.assertEqual(captured["entry_id"], self._entries()[0]["id"])
        end = self._turn_end()
        self.assertEqual(set(end["captured"]), {"captured", "entry_id", "reason"})
        self.assertEqual(end["captured"]["entry_id"], self._entries()[1]["id"])

    def test_capture_default_true(self):
        out = self._turn_start()
        self.assertTrue(out["captured_user"]["captured"])
        self.assertEqual(len(self._entries()), 1)


if __name__ == "__main__":
    unittest.main()
