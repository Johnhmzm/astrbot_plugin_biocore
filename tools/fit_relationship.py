# -*- coding: utf-8 -*-
"""关系更新率：一次好评/差评，信任与亲密各变动多少。

回答一个问题：现在 trust/closeness 的更新是手写常数的叠加，是否符合真实数据的走向。
做法：turn_log 里相邻两行的 trust 差 vs 该行评分，回归斜率就是「每单位评分的信任增量」。

用法：
    python tools/fit_relationship.py                    # 合成数据自检
    python tools/fit_relationship.py --log <turn_log>   # 真实日志
"""
from __future__ import annotations

import argparse
import json
import math
import random
from typing import Dict, List


def _rows(path: str) -> List[Dict[str, float]]:
    raw = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    raw.append(json.loads(line))
    except Exception:
        return []
    out = []
    prev = None
    for row in raw:
        rel = row.get("rel") or {}
        grade = row.get("grade")
        if not isinstance(rel, dict) or not isinstance(grade, (int, float)):
            prev = None
            continue
        if prev is not None:
            d = {}
            for key in ("trust", "closeness"):
                a, b = prev.get(key), rel.get(key)
                if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                    d[key] = float(b) - float(a)
            if d:
                out.append({"grade": float(grade), **d})
        prev = rel
    return out


def _slope(rows: List[Dict[str, float]], key: str) -> float:
    pts = [(r["grade"], r[key]) for r in rows if key in r]
    if len(pts) < 4:
        return 0.0
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    num = sum((x - mx) * (y - my) for x, y in pts)
    den = sum((x - mx) ** 2 for x, _ in pts)
    return round(num / den, 5) if den else 0.0


def demo() -> List[Dict[str, float]]:
    rng = random.Random(4)
    rows, trust = [], 0.5
    for _ in range(120):
        grade = rng.uniform(-1, 1)
        new = max(0.0, min(1.0, trust + 0.05 * grade))
        rows.append({"grade": grade, "trust": new - trust,
                     "closeness": (new - trust) * 0.6})
        trust = new
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="")
    args = ap.parse_args(argv)
    rows = _rows(args.log) if args.log else demo()
    if not rows:
        print("no usable consecutive rel rows")
        return 1
    print("样本 %d 条" % len(rows))
    print("  每单位评分的信任增量    d(trust)/d(grade)     = %+.4f" % _slope(rows, "trust"))
    print("  每单位评分的亲密增量    d(closeness)/d(grade) = %+.4f" % _slope(rows, "closeness"))
    print()
    print("读法：合成数据真值 trust 为 0.05；估出来接近即方法可信，"
          "真实日志上得到的数就是现在这套更新规则的等效增益。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
