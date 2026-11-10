# -*- coding: utf-8 -*-
"""回复长度与评分的关系：长一点更好，还是短一点更好。

回答一个问题：现在「越难受说得越短」这条规则，是否真的更受欢迎。
做法：从 turn_log.jsonl 里取 expr.chars 与 grade，控制掉状态（stress/valence）后看偏相关。

用法：
    python tools/fit_expression.py                    # 合成数据自检
    python tools/fit_expression.py --log <turn_log>   # 真实日志
"""
from __future__ import annotations

import argparse
import json
import math
import random
from typing import Dict, List


def _rows_from_log(path: str) -> List[Dict[str, float]]:
    out = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                expr = row.get("expr") or {}
                if not isinstance(expr, dict):
                    continue
                chars = expr.get("chars")
                grade = row.get("grade")
                if not isinstance(chars, (int, float)) or not isinstance(grade, (int, float)):
                    continue
                st = row.get("state") or {}
                out.append({"chars": float(chars), "grade": float(grade),
                            "stress": float(st.get("stress") or 0.0),
                            "valence": float(st.get("valence") or 0.0)})
    except Exception:
        return []
    return out


def _corr(xs, ys) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def partial(rows: List[Dict[str, float]], control: str = "stress") -> float:
    """控制掉状态后的偏相关：长度 ↔ 评分。"""
    if len(rows) < 6:
        return 0.0
    r_xy = _corr([r["chars"] for r in rows], [r["grade"] for r in rows])
    r_xz = _corr([r["chars"] for r in rows], [r[control] for r in rows])
    r_yz = _corr([r["grade"] for r in rows], [r[control] for r in rows])
    denom = math.sqrt(max(1e-9, (1 - r_xz ** 2) * (1 - r_yz ** 2)))
    return round((r_xy - r_xz * r_yz) / denom, 4)


def demo() -> List[Dict[str, float]]:
    rng = random.Random(3)
    rows = []
    for _ in range(120):
        stress = abs(rng.gauss(0.2, 0.15))
        chars = 40 - 60 * stress + rng.gauss(0, 8)          # 越紧绷越短
        grade = 0.6 + 0.004 * chars + rng.gauss(0, 0.08)     # 长一点略好
        rows.append({"chars": max(4, chars), "grade": grade,
                     "stress": round(stress, 3), "valence": 0.0})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="")
    args = ap.parse_args(argv)
    rows = _rows_from_log(args.log) if args.log else demo()
    if not rows:
        print("no usable rows")
        return 1
    print("样本 %d 条" % len(rows))
    print("  长度↔评分        r = %+.3f" % _corr([r["chars"] for r in rows],
                                                [r["grade"] for r in rows]))
    print("  长度↔压力        r = %+.3f" % _corr([r["chars"] for r in rows],
                                                [r["stress"] for r in rows]))
    print("  控制压力后的偏相关 r = %+.3f" % partial(rows, "stress"))
    print()
    print("读法：偏相关为正 → 同样的状态下，说长一点分数更高；"
          "为负 → 说短更好。绝对值 <0.15 视为没有可学信号。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
