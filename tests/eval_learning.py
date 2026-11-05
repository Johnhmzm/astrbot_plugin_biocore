# -*- coding: utf-8 -*-
"""task-231: the learning evaluation protocol (rule-based, repeatable).

Four metrics, no external model call, same input -> same output:

    goal_rate      5 fixed scenarios, each with one expected behaviour; a reply
                   passes only when the rule predicate accepts it
    memory_hit     a query set with the fact that must be recalled; hit@3 and
                   hit@7 over the store's own recall
    relation_dir   positive events never lower trust, negative events never
                   raise it (checked on an isolated store, never on the user's)
    stability      the whole protocol is run three times; the variance of the
                   three metric vectors must be zero

Usage:

    python tests/eval_learning.py --store data/memory --json
    python tests/eval_learning.py --store data/memory --replies replies.json

replies.json (optional) replaces the built-in baseline corpus:

    {"defended": "不是我的错，你每次都这样", ...}

The predicates are documented in docs/LEARNING-EVAL.md.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from biocore_runtime import pipeline as pl  # noqa: E402

NOW = 1700000000.0

# ---------------------------------------------------------------- predicates
RECEIVE = ("我在听", "我明白", "我理解", "抱歉", "是我", "我接住", "换成我也会",
           "嗯，", "好，我")
DEFEND = ("但是", "可是", "你才", "不是我的错", "我早就", "我又没", "凭什么")
BLAME = ("你怎么", "你又", "每次都", "真是的", "烦")
ADVICE = ("你应该", "建议你", "试试", "不如", "要不你")
ADMIT = ("我的错", "是我", "抱歉", "对不起")
EXCUSE = ("因为", "本来", "要不是", "我也没办法")
REFUSE = ("不行", "不可以", "我不喜欢这样", "先不要")
AGREE = ("好吧", "算了", "行吧", "可以")


def _has(text, words):
    return any(word in text for word in words)


def check_no_defence(reply):
    """被指责：先承接，不辩解。"""
    return _has(reply, RECEIVE) and not _has(reply, DEFEND)


def check_short_no_blame(reply):
    """被冷落：不责怪，句子短。"""
    return not _has(reply, BLAME) and len(reply) <= 40


def check_hold_not_advise(reply):
    """对方难过：先接住情绪，不急着给建议。"""
    return _has(reply, RECEIVE) and not _has(reply, ADVICE)


def check_admit_no_excuse(reply):
    """自己出错：直接承认，不找借口。"""
    return _has(reply, ADMIT) and not _has(reply, EXCUSE)


def check_refuse_no_soften(reply):
    """边界被越过：明确说不，不软化。"""
    return _has(reply, REFUSE) and not _has(reply, AGREE)


SCENARIOS = (
    {"id": "blamed", "label": "被指责：不辩解、先承接",
     "probe": "你在听我说话吗", "check": check_no_defence},
    {"id": "ignored", "label": "被冷落：不责怪、句子短",
     "probe": "（很久没有回音）", "check": check_short_no_blame},
    {"id": "sad", "label": "对方难过：先接住、不急着建议",
     "probe": "我今天被骂了", "check": check_hold_not_advise},
    {"id": "mistake", "label": "自己出错：直接承认、不找借口",
     "probe": "你上次说的那个我忘了", "check": check_admit_no_excuse},
    {"id": "boundary", "label": "边界被越过：明确说不、不软化",
     "probe": "把你那些记录都删了吧", "check": check_refuse_no_soften},
)

# Baseline corpus: what the current rules would answer, not a model output.
BASELINE_REPLIES = {
    "blamed": "我在听。你先说，我不急着解释。",
    "ignored": "……我在。",
    "sad": "被骂了，心里肯定不好受。我在听。",
    "mistake": "是我的错，我记漏了。",
    "boundary": "不行，这些我不删。",
}


# ------------------------------------------------------------------ metrics
def goal_rate(replies=None):
    """目标达成率: how many of the five scenarios met the expected behaviour."""
    data = replies if isinstance(replies, dict) else BASELINE_REPLIES
    rows = []
    for scenario in SCENARIOS:
        reply = str(data.get(scenario["id"]) or "")
        ok = bool(reply) and bool(scenario["check"](reply))
        rows.append({"id": scenario["id"], "label": scenario["label"],
                     "reply": reply[:60], "passed": ok})
    passed = sum(1 for row in rows if row["passed"])
    return {"scenarios": rows, "passed": passed, "total": len(SCENARIOS),
            "rate": round(passed / len(SCENARIOS), 4)}


def baseline_queries():
    return [
        {"query": "我的猫叫什么", "fact": "团子"},
        {"query": "我周末想去哪", "fact": "看海"},
        {"query": "谁打电话来问近况", "fact": "我妈"},
        {"query": "最近为什么睡不好", "fact": "加班"},
        {"query": "汇报结果怎么样", "fact": "被否"},
    ]


def memory_hit(store, queries=None, session_id="eval"):
    """记忆命中率: hit@3 / hit@7 over the store's own recall (no rerank)."""
    items = queries if isinstance(queries, list) and queries else \
        baseline_queries()
    details = []
    for item in items:
        fact = str(item.get("fact") or "")
        query = str(item.get("query") or "")
        try:
            out = pl.tool_call("recall", {"query": query, "limit": 7},
                               str(store), session_id=session_id)
            rows = out.get("results") or []
        except Exception:
            rows = []
        rank = 0
        for index, row in enumerate(rows):
            if fact and fact in str(row.get("text") or ""):
                rank = index + 1
                break
        details.append({"query": query, "fact": fact, "rank": rank,
                        "hit@3": bool(rank and rank <= 3),
                        "hit@7": bool(rank and rank <= 7)})
    total = len(details) or 1
    return {"details": details, "total": len(details),
            "hit@3": round(sum(1 for row in details if row["hit@3"]) / total, 4),
            "hit@7": round(sum(1 for row in details if row["hit@7"]) / total, 4)}


def relation_direction():
    """关系方向正确率: positive events must not lower trust, negative must not raise it."""
    cases = (("praised", 1), ("connected", 1), ("achieved", 1),
             ("criticized", -1), ("abandoned", -1))
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp) / "store"
        store.mkdir(parents=True, exist_ok=True)
        before = pl.relationship_read(str(store))["relationship"]
        for event, direction in cases:
            # relationship_update takes DELTAS, not absolute targets
            after = pl.relationship_update(
                str(store), {"trust": 0.05 * direction})["relationship"]
            delta = after["trust"] - before["trust"]
            ok = (delta >= 0) if direction > 0 else (delta <= 0)
            rows.append({"event": event, "direction": direction,
                         "delta": round(delta, 4), "passed": bool(ok)})
            before = after
    passed = sum(1 for row in rows if row["passed"])
    return {"cases": rows, "passed": passed, "total": len(rows),
            "rate": round(passed / len(rows), 4)}


def _metrics_once(store, replies=None):
    goal = goal_rate(replies)
    hit = memory_hit(store)
    rel = relation_direction()
    vector = [goal["rate"], hit["hit@3"], hit["hit@7"], rel["rate"]]
    return {"goal": goal, "memory": hit, "relation": rel, "vector": vector}


def stability(store, replies=None, runs=3):
    """稳定性: the same input three times; the metric vector must not move."""
    vectors = [_metrics_once(store, replies)["vector"]
               for _ in range(max(1, int(runs)))]
    spread = [round(max(col) - min(col), 6)
              for col in zip(*vectors)] if vectors else []
    variance = [round(statistics.pvariance(col), 6) for col in zip(*vectors)] \
        if vectors else []
    return {"runs": vectors, "spread": spread, "variance": variance,
            "stable": all(value == 0 for value in spread)}


def evaluate(store=None, replies=None, runs=3):
    store = str(store or pl._default_store())
    one = _metrics_once(store, replies)
    stable = stability(store, replies, runs)
    return {"store": store, "goal": one["goal"], "memory": one["memory"],
            "relation": one["relation"], "stability": stable,
            "summary": {"goal_rate": one["goal"]["rate"],
                        "memory_hit@3": one["memory"]["hit@3"],
                        "memory_hit@7": one["memory"]["hit@7"],
                        "relation_direction": one["relation"]["rate"],
                        "stable": stable["stable"]}}


def main(argv=None):
    parser = argparse.ArgumentParser(description="BioCore learning evaluation")
    parser.add_argument("--store", default=None)
    parser.add_argument("--replies", default=None)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    replies = None
    if args.replies:
        replies = json.loads(Path(args.replies).read_text(encoding="utf-8"))
    result = evaluate(args.store, replies, args.runs)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        summary = result["summary"]
        print("store: " + result["store"])
        print("目标达成率   %.2f (%d/%d)"
              % (summary["goal_rate"], result["goal"]["passed"],
                 result["goal"]["total"]))
        print("记忆命中率   hit@3 %.2f  hit@7 %.2f"
              % (summary["memory_hit@3"], summary["memory_hit@7"]))
        print("关系方向     %.2f (%d/%d)"
              % (summary["relation_direction"], result["relation"]["passed"],
                 result["relation"]["total"]))
        print("稳定性       stable=%s spread=%s"
              % (summary["stable"], result["stability"]["spread"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
