# -*- coding: utf-8 -*-
"""每个参数需要多少样本才能可靠估计。

参数循环现在用「相关系数 > 0.15」作门槛，但没说这个门槛需要多少数据才可信。
按 Fisher z 的近似，相关系数 r 的检验需要 n ≈ ((z_{α/2}+z_β)/r)² ；
取 α=0.05、功效 0.8，得 n ≈ 7.85 / r²。

用法：
    python tools/scaling_law.py            # 打表
    python tools/scaling_law.py --log <turn_log.jsonl>   # 用真实日志算当前 r
"""
from __future__ import annotations

import argparse
import json
import math
from typing import Dict, List

Z_SUM = 1.959964 + 0.841621  # z_{0.975} + z_{0.80}


def required_n(r: float) -> int:
    """样本量下界：|r| 越小，需要的数据越多（平方关系）。"""
    r = abs(float(r))
    if r <= 1e-6:
        return 10 ** 9
    return int(math.ceil((Z_SUM / r) ** 2))


def table(rs=(0.10, 0.15, 0.20, 0.30, 0.50)) -> List[Dict[str, object]]:
    return [{"r": r, "n_needed": required_n(r)} for r in rs]


def from_log(path: str) -> List[Dict[str, object]]:
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except Exception:
        return []
    out = []
    knobs = set()
    for row in rows:
        knobs.update((row.get("theta") or {}).keys())
    for knob in sorted(knobs):
        xs, ys = [], []
        for row in rows:
            val = (row.get("theta") or {}).get(knob)
            grade = row.get("grade")
            if isinstance(val, (int, float)) and isinstance(grade, (int, float)):
                xs.append(float(val))
                ys.append(float(grade))
        n = len(xs)
        if n < 3:
            out.append({"knob": knob, "n": n, "r": 0.0, "n_needed": None})
            continue
        mx = sum(xs) / n
        my = sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        dx = sum((x - mx) ** 2 for x in xs) ** 0.5
        dy = sum((y - my) ** 2 for y in ys) ** 0.5
        r = num / (dx * dy) if dx and dy else 0.0
        out.append({"knob": knob, "n": n, "r": round(r, 4),
                    "n_needed": required_n(r)})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="")
    args = ap.parse_args(argv)
    if args.log:
        rows = from_log(args.log)
        if not rows:
            print("no usable rows in " + args.log)
            return 1
        print("%-14s %6s %8s %10s  %s" % ("knob", "n", "r", "n_needed", "verdict"))
        for row in rows:
            need = row["n_needed"]
            verdict = "unknown" if need is None else ("enough" if row["n"] >= need else "short")
            print("%-14s %6d %8.3f %10s  %s" % (row["knob"], row["n"], row["r"],
                                                 need if need is not None else "-", verdict))
        return 0
    print("%-8s %12s %10s" % ("|r|", "n_needed", "约合天数"))
    for row in table():
        days = row["n_needed"] / 50.0
        print("%-8.2f %12d %10.0f" % (row["r"], row["n_needed"], days))
    print()
    print("按每天 50 轮估算；真实速度取决于对话量。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
