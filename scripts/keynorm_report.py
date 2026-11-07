# -*- coding: utf-8 -*-
"""P01 状态层键归一的前后对比（不调用模型）。

归一前：cache/facts-P01.json 里的原始抽取结果，键 = 主体·属性，同一属性被
抽成不同名字时就是对不上的两个键。

归一后：把同一批抽取结果回放进新的抽取/合并流程——extract_facts 带着当前
键表提问，回答里能对上已有键的就照抄（REPLAY_ALIASES 记录模型会做的复用
决定），再用 merge_fact_state 合并。回放不放宽任何规则：能归到已有键的，
要么完全同名，要么是同一属性下多带限定的主体（如「合租房客厅地板」）。

    python scripts/keynorm_report.py
    python scripts/keynorm_report.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from biocore_memory.event import keynorm as K  # noqa: E402

DEFAULT_FACTS = Path(r"C:/Users/Administrator/Desktop/deepseek/.archify/bench/cache/facts-P01.json")

# 模型在带键表抽取时会做的复用决定：属性换了名字，但它指的是同一个属性。
# 机器无法判断这一步；回放把它当作输入，并在报告里单列出来。
REPLAY_ALIASES = {
    ('叶楠', '日历日期'): ('叶楠', '生日'),
}


def load_facts(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = []
    for group in (data.get("events") or {}).values():
        for row in group or []:
            if not isinstance(row, dict):
                continue
            if not (row.get("subject") and row.get("attribute") and row.get("value")):
                continue
            rows.append({"subject": row["subject"], "attr": row["attribute"],
                         "value": row["value"], "turn": int(row.get("turn") or 0),
                         "ts": 0.0, "invalid_at": row.get("invalid_at")})
    rows.sort(key=lambda r: (r["turn"], r["subject"], r["attr"]))
    return rows


def census(facts):
    values = {}
    for fact in facts:
        key = K.key_of(fact.get("subject"), fact.get("attr"))
        values.setdefault(key, [])
        if fact["value"] not in values[key]:
            values[key].append(fact["value"])
    multi = {k: v for k, v in values.items() if len(v) > 1}
    return {"keys": len(values),
            "multi": len(multi),
            "ratio": (len(multi) / float(len(values))) if values else 0.0,
            "per_key": {k: len(v) for k, v in values.items()},
            "multi_keys": multi}


def replay_events(facts):
    """按轮次把抽取结果并回「事件」，当作回放的输入。

    一轮一个事件：轮号唯一，所以提示词里的【起止轮号】不会重复，回放不会
    把两条事实挂到错误的事件上。text 只是占位，回放不重新抽取文本。
    """
    events = []
    for turn in sorted({int(f["turn"]) for f in facts}):
        rows = [f for f in facts if int(f["turn"]) == turn]
        events.append({"event_id": "t%d" % turn, "start": turn, "end": turn,
                       "text": "\n".join("（回放）%s：%s" % (f["subject"], f["value"])
                                         for f in rows),
                       "rows": rows})
    return events


def replay_llm_factory(events):
    by_span = {}
    for ev in events:
        by_span[(int(ev["start"]), int(ev["end"]))] = ev["rows"]

    def llm(prompt):
        out = []
        for ev in events:
            span = (int(ev["start"]), int(ev["end"]))
            if "【%d-%d】" % span not in prompt:
                continue
            facts = []
            for row in by_span[span]:
                subject, attr = REPLAY_ALIASES.get((row["subject"], row["attr"]),
                                                   (row["subject"], row["attr"]))
                facts.append({"subject": subject, "attr": attr, "value": row["value"],
                              "turn": row["turn"]})
            out.append({"start": span[0], "end": span[1], "facts": facts})
        return json.dumps(out, ensure_ascii=False)

    return llm


def run_normalized(facts):
    events = replay_events(facts)
    stats = {}
    extracted = K.extract_facts(events, replay_llm_factory(events), [], stats=stats)
    state = {}
    for start in range(0, len(extracted), 8):
        chunk = extracted[start:start + 8]
        state = K.merge_fact_state(state, chunk, turn=int(chunk[-1]["turn"]))
    return extracted, state, stats


def show_key(census_rows, state, key):
    item = state.get(key) or {}
    if not item:
        return ["%s：（缺失）" % key]
    lines = [K.state_line(key, item),
             "  status=%s value=%s coexist=%s" % (item.get("status"), item.get("value"),
                                                  item.get("coexist"))]
    for row in K.value_list(item):
        lines.append("  值=%s 轮次=%s" % (row["value"], row["turn"]))
    return lines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts", default=str(DEFAULT_FACTS))
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    raw = load_facts(args.facts)
    before = census(raw)
    extracted, state, stats = run_normalized(raw)
    after_facts = [{"subject": r["subject"], "attr": r["attr"], "value": r["value"]}
                   for r in extracted]
    after = census(after_facts)

    print("P01 事实抽取：%d 条，轮次 %d-%d" % (len(raw), raw[0]["turn"], raw[-1]["turn"]))
    print("")
    print("%-14s %8s %10s %10s" % ("口径", "key 数", "多值 key", "多值比例"))
    print("%-14s %8d %10d %9.1f%%" % ("归一前（原键）", before["keys"], before["multi"],
                                      before["ratio"] * 100))
    print("%-14s %8d %10d %9.1f%%" % ("归一后（复用键）", after["keys"], after["multi"],
                                      after["ratio"] * 100))
    print("")
    print("回放统计：calls=%d reused=%d new=%d keys=%d" % (
        stats.get("calls"), stats.get("reused"), stats.get("new"), stats.get("keys")))
    print("")
    print("【叶楠生日】")
    for key in ("叶楠·生日", "叶楠·日历日期"):
        print("  归一前 %s = %s" % (key, [r["value"] for r in raw
                                        if K.key_of(r["subject"], r["attr"]) == key]))
    for line in show_key({}, state, "叶楠·生日"):
        print("  " + line)
    print("")
    print("【地板颜色】")
    for key in ("合租房客厅地板·颜色", "客厅地板·颜色"):
        print("  归一前 %s = %s" % (key, [r["value"] for r in raw
                                        if K.key_of(r["subject"], r["attr"]) == key]))
    floor = [k for k in state if k.endswith("地板·颜色")]
    for key in floor:
        for line in show_key({}, state, key):
            print("  " + line)
    print("")
    print("多值 key 清单（归一后）：")
    for key in sorted(after["multi_keys"]):
        print("  %s -> %s" % (key, after["multi_keys"][key]))

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"facts": len(raw), "before": {"keys": before["keys"], "multi": before["multi"],
                                           "ratio": before["ratio"]},
             "after": {"keys": after["keys"], "multi": after["multi"],
                       "ratio": after["ratio"]},
             "replay": stats, "aliases": {"%s·%s" % k: "%s·%s" % v
                                          for k, v in REPLAY_ALIASES.items()},
             "multi_keys": {k: v for k, v in after["multi_keys"].items()}},
            ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
