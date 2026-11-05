# -*- coding: utf-8 -*-
"""task-236 (batch B): the fifteen memory / narrative modules behind apply_turn.

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_batch_b.py"
"""
import copy
import json
import os
import unittest

from biocore_runtime import batch_b as bb
from biocore_model import entity_graph, policy_learning


NOW = 1700000000.0


def entries():
    return [
        {"id": "e1", "text": "我叫小林，喜欢猫", "role": "user", "ts": NOW - 3600,
         "importance": 0.9, "tags": ["profile"], "strength": 0.9,
         "retrieval_s": 0.8, "storage_s": 0.9, "recall_count": 2},
        {"id": "e2", "text": "昨天去了公园看猫", "role": "user", "ts": NOW - 7200,
         "importance": 0.5, "strength": 0.6, "retrieval_s": 0.5,
         "storage_s": 0.8, "recall_count": 1},
    ]


def state():
    return {"core": {"v": 0.1, "a": 0.55, "stress": 0.4, "social": 0.5,
                     "energy": 0.6},
            "relationship": {"trust": 0.6, "closeness": 0.55,
                             "attachment_style": "secure"},
            "needs": {"belonging": 0.55, "self_esteem": 0.6, "control": 0.6,
                      "meaningful_existence": 0.55}}


def payload(**extra):
    data = {"user_text": "小林上周说喜欢猫", "assistant_text": "嗯，我记得。",
            "dims": {"goal": -0.3, "blame": 0.7, "hit": 0.6, "involve": 0.7},
            "entries": entries(), "recalled_ids": ["e1", "e2", "e3"],
            "graph_tag": {"entities": [{"name": "小林", "type": "person"},
                                       {"name": "猫", "type": "topic"}],
                          "relations": [{"src": "小林", "rel": "喜欢",
                                         "dst": "猫"}]},
            "silence_phase": "expect", "responded": True,
            "response_gap_s": 120, "delta_discomfort": -0.1, "now": NOW}
    data.update(extra)
    return data


def turn(phase, **extra):
    return bb.apply_turn(state(), phase, payload(**extra))


class SwitchTest(unittest.TestCase):
    def test_default_is_on(self):
        self.assertTrue(bb.enabled())
        self.assertTrue(bb.enabled({}))
        self.assertTrue(bb.enabled({}, env={}))

    def test_payload_and_env_can_turn_it_off(self):
        self.assertFalse(bb.enabled({"batch_b": False}))
        self.assertFalse(bb.enabled({"switches": {"batch_b": False}}))
        self.assertFalse(bb.enabled({}, env={"BIOCORE_BATCH_B": "0"}))

    def test_bad_phase_is_refused(self):
        out = bb.apply_turn(state(), "recall", payload())
        self.assertFalse(out["enabled"])
        self.assertEqual(out["reason"], "bad_phase")

    def test_fifteen_modules_declared(self):
        self.assertEqual(len(bb.MODULES), 15)
        self.assertEqual(len(set(bb.MODULES)), 15)
        out = turn("turn_start")
        self.assertEqual(out["counts"]["modules"], 15)
        self.assertEqual(out["counts"]["available"], 15)
        self.assertEqual(set(out["modules"]), set(bb.MODULES))


class ReadSideTest(unittest.TestCase):
    def test_turn_start_reports_every_read(self):
        out = turn("turn_start")
        for key in ("identity", "graph", "entities", "memory_tiers", "dual",
                    "forgetting", "store", "policy", "forecast", "scores"):
            self.assertIn(key, out["reads"])
        self.assertGreaterEqual(out["counts"]["active"], 8)

    def test_identity_threat_proposes_capped_field_deltas(self):
        out = turn("turn_start")
        self.assertTrue(out["reads"]["identity"]["threat"])
        self.assertLess(out["field_deltas"]["trust"], 0.0)
        self.assertGreater(out["field_deltas"]["stress"], 0.0)
        for name, value in out["field_deltas"].items():
            self.assertLessEqual(abs(value), bb.CAPS[name] + 1e-9)

    def test_quiet_turn_proposes_nothing(self):
        out = bb.apply_turn(
            state(), "turn_start",
            payload(dims={"goal": 0.4, "blame": 0.0, "hit": 0.0,
                          "involve": 0.2}))
        self.assertFalse(out["reads"]["identity"]["threat"])
        # warm feedback is fine; nothing may push the field *down*
        self.assertGreaterEqual(out["field_deltas"].get("trust", 0.0), 0.0)
        self.assertGreaterEqual(out["field_deltas"].get("v", 0.0), 0.0)
        self.assertLessEqual(out["field_deltas"].get("stress", 0.0), 0.0)

    def test_entity_resolve_matches_an_alias(self):
        graph = entity_graph.empty_graph()
        graph, _ = entity_graph.upsert_entity(graph, "小林", "person", ["林"], NOW)
        out = bb.apply_turn(state(), "turn_start",
                            payload(graph=graph, entity_name="林"))
        value = out["reads"]["entities"]
        self.assertTrue(value["match"])
        self.assertEqual(value["name"], "小林")
        self.assertEqual(value["via"], "alias")
        self.assertAlmostEqual(value["score"], 1.0, places=4)

    def test_graph_recall_rows_are_bounded_and_windowed(self):
        graph = entity_graph.empty_graph()
        graph, _ = entity_graph.upsert_entity(graph, "小林", "person", None, NOW)
        graph, _ = entity_graph.upsert_entity(graph, "猫", "topic", None, NOW)
        graph, _ = entity_graph.upsert_edge(graph, "小林", "喜欢", "猫", NOW,
                                           0.9, "e2")
        out = bb.apply_turn(state(), "turn_start",
                            payload(graph=graph, user_text="上周小林的事"))
        value = out["reads"]["graph"]
        self.assertEqual(value["window_days"], 7)
        self.assertLessEqual(len(value["rows"]), 5)
        self.assertGreater(value["block_chars"], 0)

    def test_layered_memory_splits_resident_and_retrieval(self):
        tiers = turn("turn_start")["state_deltas"]["memory_tiers"]
        self.assertEqual(tiers["resident"], ["e1"])
        self.assertEqual(tiers["retrieval"], ["e2"])
        self.assertEqual(tiers["archive_count"], 2)

    def test_memory_dual_returns_scored_picks(self):
        dual = turn("turn_start")["reads"]["dual"]
        self.assertEqual(len(dual["picked"]), 2)
        for row in dual["picked"]:
            self.assertGreaterEqual(row["score"], 0.0)
            self.assertLessEqual(row["score"], 1.0)
        self.assertGreaterEqual(dual["picked"][0]["score"],
                                dual["picked"][1]["score"])

    def test_forgetting_counts_injectable_rows(self):
        value = turn("turn_start")["reads"]["forgetting"]
        self.assertEqual(value["total"], 2)
        self.assertGreaterEqual(value["injectable"], 1)
        weak = bb.apply_turn(state(), "turn_start",
                             payload(entries=[{"id": "x", "text": "弱记忆",
                                               "strength": 0.0}]))
        self.assertEqual(weak["reads"]["forgetting"]["injectable"], 0)

    def test_scoring_prefers_the_query_match(self):
        base = turn("turn_start")
        self.assertGreater(base["reads"]["scores"]["top"]["e1"], 0.0)
        other = bb.apply_turn(state(), "turn_start", payload(query="公园",
                                                             user_text="公园"))
        self.assertGreater(other["reads"]["scores"]["top"]["e2"],
                           other["reads"]["scores"]["top"]["e1"])

    def test_policy_chooses_a_known_action(self):
        policy = turn("turn_start")["reads"]["policy"]
        self.assertIn(policy["action"], policy_learning.ACTIONS)
        self.assertIn("|", policy["context"])

    def test_predictor_forecasts_every_channel(self):
        forecast = turn("turn_start")["state_deltas"]["predictor_forecast"]
        self.assertEqual(set(forecast["channels"]),
                         {"v", "a", "d", "social", "stress", "energy", "trust"})
        self.assertAlmostEqual(forecast["channels"]["v"], 0.1, places=4)
        self.assertGreater(forecast["confidence"], 0.0)

    def test_memory_store_normalizes_the_backend(self):
        self.assertEqual(turn("turn_start")["reads"]["store"]["backend"], "sqlite")
        weird = bb.apply_turn(state(), "turn_start",
                              payload(backend="not-a-backend"))
        self.assertIn(weird["reads"]["store"]["backend"], ("sqlite", "auto"))


class WriteSideTest(unittest.TestCase):
    def test_turn_end_reports_every_write(self):
        out = turn("turn_end")
        for key in ("graph", "strength", "co_recall", "policy", "predictor",
                    "identity"):
            self.assertIn(key, out["reads"])
        for key in ("entity_graph", "memory_strength", "co_recall", "policy_q",
                    "predictor_history", "identity_read"):
            self.assertIn(key, out["state_deltas"])

    def test_graph_tag_becomes_nodes_and_edges(self):
        out = turn("turn_end")
        graph = out["state_deltas"]["entity_graph"]
        self.assertEqual(len(graph["entities"]), 2)
        self.assertEqual(len(graph["edges"]), 1)
        self.assertEqual(out["state_deltas"]["graph_stats"]["edges"], 1)
        self.assertEqual(out["reads"]["graph"]["wrote"], {"entities": 2,
                                                          "edges": 1})

    def test_graph_write_is_bounded(self):
        tag = {"entities": [{"name": name, "type": "person"}
                            for name in ("甲", "乙", "丙", "丁", "戊")],
               "relations": []}
        out = turn("turn_end", graph_tag=tag)
        entities = out["state_deltas"]["entity_graph"]["entities"]
        self.assertLessEqual(len(entities), 3)

    def test_no_tag_is_skipped_not_an_error(self):
        out = bb.apply_turn(state(), "turn_end", payload(graph_tag=None))
        self.assertIn({"module": "entity_graph", "reason": "no_tag"},
                      [{"module": row["module"], "reason": row["reason"]}
                       for row in out["skipped"]])
        self.assertNotIn("entity_graph", out["state_deltas"])

    def test_memory_strength_boosts_the_recalled_entry(self):
        rows = turn("turn_end")["state_deltas"]["memory_strength"]
        self.assertIn("e1", rows)
        self.assertGreaterEqual(rows["e1"]["strength"], 0.9)
        self.assertGreaterEqual(rows["e1"]["count"], 2)

    def test_co_recall_counts_and_dedupes_pairs(self):
        pairs = turn("turn_end")["state_deltas"]["co_recall"]
        self.assertEqual(set(pairs), {"e1|e2", "e1|e3", "e2|e3"})
        repeated = bb.apply_turn(
            dict(state(), co_recall=pairs), "turn_end",
            payload(recalled_ids=["e1", "e1", "e2", "e3"]))
        again = repeated["state_deltas"]["co_recall"]
        self.assertEqual(again["e1|e2"]["count"], 2)

    def test_co_recall_is_bounded(self):
        ids = ["id%02d" % index for index in range(12)]
        out = bb.apply_turn(state(), "turn_end", payload(recalled_ids=ids))
        self.assertLessEqual(len(out["state_deltas"]["co_recall"]), bb.PAIR_LIMIT)

    def test_policy_update_records_the_chosen_action(self):
        start = turn("turn_start")
        context = start["reads"]["policy"]["context"]
        action = start["reads"]["policy"]["action"]
        out = bb.apply_turn(dict(state(), policy_q={}), "turn_end",
                            payload(policy_context=context,
                                    policy_action=action, responded=True))
        table = out["state_deltas"]["policy_q"]
        self.assertEqual(table[context][action]["n"], 1)
        self.assertNotEqual(table[context][action]["q"], 0.0)

    def test_prediction_error_grows_with_a_real_surprise(self):
        start = turn("turn_start")
        forecast = start["state_deltas"]["predictor_forecast"]
        moved = dict(state())
        moved["core"] = dict(moved["core"], v=0.9, a=0.05, stress=0.95)
        out = bb.apply_turn(dict(moved, predictor_forecast=forecast),
                            "turn_end", payload())
        self.assertGreater(out["state_deltas"]["prediction"]["surprise"], 0.0)
        self.assertGreaterEqual(len(out["state_deltas"]["predictor_history"]), 1)

    def test_migrate_store_stays_a_dry_run(self):
        sample = [{"id": "m1", "text": "迁移测试", "ts": NOW, "role": "user",
                   "importance": 0.4, "tags": []}]
        out = turn("turn_end", migrate_sample=sample)
        report = out["state_deltas"]["migrate_report"]
        self.assertEqual(report["converted"], 1)
        self.assertNotIn("no_sample",
                         [row["reason"] for row in out["skipped"]])

    def test_migrate_without_a_sample_is_skipped(self):
        out = turn("turn_end")
        self.assertIn("migrate_store",
                      [row["module"] for row in out["skipped"]])
        self.assertNotIn("migrate_report", out["state_deltas"])


class ContractTest(unittest.TestCase):
    def test_input_state_is_never_mutated(self):
        before = state()
        snapshot = copy.deepcopy(before)
        bb.apply_turn(before, "turn_start", payload())
        bb.apply_turn(before, "turn_end", payload())
        self.assertEqual(json.dumps(before, sort_keys=True),
                         json.dumps(snapshot, sort_keys=True))

    def test_same_inputs_give_the_same_numbers(self):
        first = turn("turn_end")
        second = turn("turn_end")
        for out in (first, second):
            out.pop("ts", None)
        self.assertEqual(json.dumps(first, sort_keys=True, ensure_ascii=False),
                         json.dumps(second, sort_keys=True, ensure_ascii=False))

    def test_result_is_json_safe(self):
        for phase in ("turn_start", "turn_end"):
            out = turn(phase)
            json.dumps(out, ensure_ascii=False)  # must not raise
            self.assertNotIn("prompt", json.dumps(out, ensure_ascii=False).lower())

    def test_missing_payload_blocks_degrade_quietly(self):
        out = bb.apply_turn(state(), "turn_start", {})
        self.assertTrue(out["enabled"])
        self.assertEqual(out["state_deltas"]["memory_tiers"]["archive_count"], 0)
        self.assertTrue(out["skipped"])
        for row in out["skipped"]:
            self.assertIn("module", row)
            self.assertIn("reason", row)


if __name__ == "__main__":
    unittest.main()
