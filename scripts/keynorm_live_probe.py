# -*- coding: utf-8 -*-
# 副本：真模型服从率探针。原始版本在 .archify/bench/harness/bcmb_keynorm_live.py，
# 两处保持一致；这里放一份是为了让报告与代码在同一个仓库里。
"""P01 键归一：真模型的服从率与残留同义键（不上 REPLAY_ALIASES）。

设计：
  head = 结束轮 < 150 的事件 —— 只用来长出第一批键（键表从零开始）；
  tail = 结束轮 150..330 的事件 —— 测量集，包含叶楠生日(165/183)与地板颜色(279/317)。
  A 臂（现状）：facts.FACT_PROMPT，无键表，同一批 tail；
  B 臂（键归一）：keynorm.extract_facts，把 head 长出的键表当已有键。

    python bcmb_keynorm_live.py
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path

HARNESS = Path(r"C:/Users/Administrator/Desktop/deepseek/.archify/bench/harness")
if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))

import bcmb_config as C  # noqa: E402  模型、缓存与数据集配置都在 bench 侧
from bcmb_llm import Usage, chat  # noqa: E402

sys.path.insert(0, str(C.CORE_ROOT))
from biocore_memory.event import events as E      # noqa: E402
from biocore_memory.event import facts as F       # noqa: E402
from biocore_memory.event import keynorm as K     # noqa: E402

FLAGS = {E.FLAG_KEY: True}
PERSONA = "P01"
HEAD_END = 150
TAIL_END = 330
CACHE = C.HARNESS_DIR.parent / "cache" / "keynorm-live-P01-v2.json"
OUT = C.HARNESS_DIR.parent / "runs" / "keynorm-live-P01-v2.json"


def load_events():
    hist = C.DATASET / "histories" / ("%s.jsonl" % PERSONA)
    rows = [json.loads(x) for x in hist.read_text(encoding="utf-8").splitlines() if x.strip()]
    entries = []
    for row in rows:
        ts = datetime.datetime.fromisoformat(row["逻辑时间"]).timestamp()
        turn = int(row["轮次"])
        if str(row.get("用户消息") or "").strip():
            entries.append({"turn": turn, "role": "user", "text": row["用户消息"], "ts": ts})
        if str(row.get("助手回复") or "").strip():
            entries.append({"turn": turn, "role": "assistant", "text": row["助手回复"], "ts": ts})
    evs = E.build_events(entries, flags=FLAGS, merge_small=True)
    head = [e for e in evs if int(e["end"]) < HEAD_END]
    tail = [e for e in evs if HEAD_END <= int(e["end"]) <= TAIL_END]
    return evs, head, tail


def make_llm(usage, cache, tag):
    def llm(prompt):
        key = hashlib.sha1((tag + "||" + prompt).encode("utf-8")).hexdigest()[:16]
        if key in cache:
            return cache[key]
        text, _u = chat([{"role": "system", "content": "只输出 JSON 数组，不要解释。"},
                         {"role": "user", "content": prompt}],
                        C.ANSWER_MODEL, usage, max_tokens=3000, json_mode=False,
                        base_url=C.ANSWER_BASE_URL, api_key=C.ANSWER_KEY,
                        thinking=C.THINKING)
        cache[key] = text
        CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        return strip_fence(text)
    return llm


def strip_fence(text):
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1] if "\n" in raw else raw.strip("`")
        if raw.rstrip().endswith("```"):
            raw = raw.rstrip()[:-3]
    return raw.strip()


def census(facts):
    values = {}
    for f in facts:
        key = K.key_of(f.get("subject"), f.get("attr") or f.get("attribute"))
        if not key:
            continue
        values.setdefault(key, [])
        if f["value"] not in values[key]:
            values[key].append(f["value"])
    multi = {k: v for k, v in values.items() if len(v) > 1}
    return {"keys": len(values), "multi": len(multi),
            "ratio": (len(multi) / float(len(values))) if values else 0.0,
            "values": values}


def groups(values):
    out = {}
    for key in values:
        subject, attr = K.split_key(key)
        out.setdefault(subject, []).append(attr)
    return {s: sorted(a) for s, a in out.items() if len(a) > 1}


def main():
    evs, head, tail = load_events()
    cache = {}
    if CACHE.exists():
        try:
            cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    usage = Usage()
    print("events=%d head=%d tail=%d (head<%d, %d<=tail<=%d)" % (
        len(evs), len(head), len(tail), HEAD_END, HEAD_END, TAIL_END), flush=True)

    seed_stats = {}
    seed_facts = K.extract_facts(head, make_llm(usage, cache, "S"), [], stats=seed_stats)
    seed_keys = K.advanced_keys([], seed_facts)
    print("seed: calls=%s facts=%d keys=%d" % (seed_stats.get("calls"),
                                               len(seed_facts), len(seed_keys)), flush=True)

    stats_a = {}
    facts_a = F.extract_facts(tail, llm=make_llm(usage, cache, "A"), cache={},
                              flags=FLAGS, stats=stats_a)
    stats_b = {}
    facts_b = K.extract_facts(tail, make_llm(usage, cache, "B"), seed_keys, stats=stats_b)
    print("A: calls=%s facts=%d | B: calls=%s facts=%d reused=%s new=%s" % (
        stats_a.get("calls"), len(facts_a), stats_b.get("calls"), len(facts_b),
        stats_b.get("reused"), stats_b.get("new")), flush=True)

    ca, cb = census(facts_a), census(facts_b)
    seeded = set(seed_keys)
    on_seed = [f for f in facts_b if K.key_of(f["subject"], f["attr"]) in seeded]
    state = K.merge_fact_state({}, seed_facts, turn=0)
    state = K.merge_fact_state(state, facts_b, turn=int(tail[-1]["end"]) if tail else 0)

    report = {"persona": PERSONA, "events": len(evs), "head": len(head), "tail": len(tail),
              "seed": {"facts": len(seed_facts), "keys": seed_keys,
                       "calls": seed_stats.get("calls")},
              "arm_a": {"facts": len(facts_a), "calls": stats_a.get("calls"), **ca,
                        "groups": groups(ca["values"])},
              "arm_b": {"facts": len(facts_b), "calls": stats_b.get("calls"),
                        "reused": stats_b.get("reused"), "new": stats_b.get("new"),
                        "on_seed": len(on_seed), **cb, "groups": groups(cb["values"])},
              "state": {k: {"value": v.get("value"), "status": v.get("status"),
                            "values": v.get("values")} for k, v in state.items()}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print("")
    print("%-12s %6s %6s %8s %8s" % ("臂", "facts", "key 数", "多值键", "多值比例"))
    print("%-12s %6d %6d %8d %7.1f%%" % ("A 无键表", len(facts_a), ca["keys"],
                                         ca["multi"], ca["ratio"] * 100))
    print("%-12s %6d %6d %8d %7.1f%%" % ("B 键表", len(facts_b), cb["keys"],
                                         cb["multi"], cb["ratio"] * 100))
    print("B 事实落在已有键上：%d/%d = %.0f%%" % (len(on_seed), len(facts_b),
                                                  100.0 * len(on_seed) / max(1, len(facts_b))))
    print("")
    for key in sorted(state):
        if "生日" in key or "颜色" in key or "地板" in key:
            print(K.state_line(key, state[key]))
    print("")
    print("B 同一主体多键（同义键残留候选）：")
    for subject, attrs in sorted(report["arm_b"]["groups"].items()):
        print("  %s: %s" % (subject, " / ".join(attrs)))
    print("写文件：%s" % OUT)


if __name__ == "__main__":
    main()