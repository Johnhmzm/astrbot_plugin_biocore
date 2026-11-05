# -*- coding: utf-8 -*-
"""Contract migration 1: main.py memory scoring == core scoring (8+ inputs)."""
import math
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "biocore_memory")):
    if path not in sys.path:
        sys.path.insert(0, path)

import memory_meta  # noqa: E402
from biocore_memory import scoring  # noqa: E402

NOW = 1_700_000_000.0
ACT_R_DECAY = 0.5


class Core:
    def __init__(self, **values):
        self.a = values.get("a", 0.5)
        self.v = values.get("v", 0.0)
        self.trust = values.get("trust", 0.5)
        self.retention_model = values.get("retention_model", "power_law")
        self.regulation = values.get("regulation", "none")
        self._last_memory_trace = values.get("trace")


def ref_importance(core, role):
    if core is None:
        return 0.5
    salience = 0.25 + 0.35 * float(getattr(core, "a", 0.5)) + 0.25 * abs(float(getattr(core, "v", 0.0)))
    salience += 0.15 * (1.0 - float(getattr(core, "trust", 0.5)))
    if role == "assistant":
        salience *= 0.9
    return max(0.15, min(1.0, salience))


def ref_parts(core, entry, cosine, query_text="", hybrid=False,
              sensitive_protect=False, salience_boost=False,
              fan_penalty=False, fan_cap=32, fan_floor=0.70, fan_gain=0.10):
    importance = memory_meta.effective_importance(entry)
    age = max(0.0, time.time() - float(entry.get("ts", 0) or 0))
    age_days = age / 86400.0
    model = getattr(core, "retention_model", "power_law") if core is not None else "power_law"
    if model in ("power_law", "multi_scale"):
        recency = memory_meta.retention_weight(age_days, model)
    else:
        recency = 1.0 / math.pow(1.0 + max(0.0, age_days) * 0.35, 0.55)
    recall_count = int(entry.get("recall_count", 0) or 0)
    assoc = memory_meta.decayed_assoc(entry)
    due = 1.15 if 0 < float(entry.get("next_review_ts", 0) or 0) <= time.time() else 1.0
    stability = max(0.2, float(entry.get("stability_days", 1.0) or 1.0))
    retention = math.exp(-age_days / stability)
    _d = ACT_R_DECAY
    _b = math.log(max(1e-9, (age_days + 0.05) ** (-_d)))
    base = 1.0 / (1.0 + math.exp(-(_b + 1.0)))
    schema = memory_meta.effective_schema_congruence(entry)
    inhibition = memory_meta.retrieval_inhibition(entry)
    regulation = str(getattr(core, "regulation", "none") or "none") if core is not None else "none"
    regulation_mod = memory_meta.regulation_memory_modifier(entry, regulation)
    lexical_mod = 1.0
    if hybrid and query_text:
        entry_text = str(entry.get("text") or "")
        variants = memory_meta.expand_query(query_text)
        lexical = max(memory_meta.lexical_overlap(v, entry_text) for v in variants) if variants else 0.0
        lexical_mod = 1.0 + 0.12 * lexical
    sensitive_mod = memory_meta.sensitivity_weight(entry) if sensitive_protect else 1.0
    source_weight = memory_meta.retrieval_weight(entry)
    score = (cosine * (0.40 + 0.60 * importance) * recency
             * (0.65 + 0.35 * retention)
             * (0.85 + 0.15 * base)
             * (1.0 + 0.10 * math.log1p(max(0, recall_count)))
             * due
             * (1.0 + 0.05 * math.log1p(max(0, assoc)))
             * source_weight
             * (1.0 + 0.10 * schema)
             * (1.0 - 0.15 * inhibition)
             * regulation_mod * lexical_mod * sensitive_mod)
    sal = 1.0
    if salience_boost:
        _c = max(0.0, min(1.0, float(cosine)))
        if _c > 0.0:
            sal = 0.90 + 0.20 * _c
            score *= sal
    if fan_penalty:
        links = entry.get("links") if isinstance(entry.get("links"), list) else []
        try:
            raw = sum(int(v) for v in (entry.get("assoc") or {}).values())
        except Exception:
            raw = 0
        fan = min(int(fan_cap or 32), raw + len(links))
        pen = max(float(fan_floor or 0.70),
                  1.0 / (1.0 + float(fan_gain or 0.10) * math.log1p(max(0, fan))))
        score *= pen
    return {
        "score": float(score), "salience": round(sal, 4),
        "cosine": round(float(cosine), 6), "importance": round(importance, 4),
        "recency": round(recency, 4), "retention": round(0.65 + 0.35 * retention, 4),
        "base": round(0.85 + 0.15 * base, 4),
        "recall_boost": round(1.0 + 0.10 * math.log1p(max(0, recall_count)), 4),
        "assoc_boost": round(1.0 + 0.05 * math.log1p(max(0, assoc)), 4),
        "due": round(due, 4), "source_weight": round(float(source_weight), 4),
        "schema": round(schema, 4), "inhibition": round(float(inhibition), 4),
        "regulation": round(float(regulation_mod), 4),
        "lexical": round(float(lexical_mod), 4),
        "sensitive": round(float(sensitive_mod), 4),
    }


def ref_select(entries, room, importance_max=0.5):
    rows = [e for e in (entries or []) if isinstance(e, dict)]
    rows.sort(key=lambda e: float(e.get("ts", 0) or 0))
    keep_n = max(0, int(room or 0))
    keep = rows[-keep_n:] if keep_n else []
    overflow = []
    for row in rows:
        if row in keep:
            continue
        importance = float(row.get("importance", 0.5) or 0.5)
        if importance < float(importance_max) and not memory_meta.is_pinned(row):
            overflow.append(row)
        else:
            keep.append(row)
    keep.sort(key=lambda e: float(e.get("ts", 0) or 0))
    return keep, overflow


def entries():
    base = {"id": "e1", "text": "苹果很甜，今天又买了。", "ts": NOW - 3 * 86400,
            "importance": 0.6, "recall_count": 2, "assoc": {"a": 3},
            "next_review_ts": NOW - 10, "stability_days": 2.0,
            "schema_congruence": 0.4, "inhibition": 0.2,
            "inhibition_ts": NOW - 86400, "memory_source": "user",
            "memory_confidence": 0.8, "sensitive": True,
            "links": ["x"], "encoding_valence": -0.3,
            "encoding_arousal": 0.7}
    rows = []
    for index in range(8):
        row = dict(base)
        row["id"] = "e%d" % index
        row["ts"] = NOW - index * 7 * 86400
        row["importance"] = 0.3 + 0.07 * index
        row["recall_count"] = index
        row["assoc"] = {"a": index}
        row["stability_days"] = 0.5 + index
        row["schema_congruence"] = 0.1 * index
        rows.append(row)
    return rows


class EquivalenceTest(unittest.TestCase):
    def test_importance_matches(self):
        cores = [None, Core(a=0.8, v=-0.4, trust=0.2), Core(a=0.3, v=0.6, trust=0.9)]
        for core in cores:
            for role in ("user", "assistant"):
                self.assertAlmostEqual(scoring.memory_importance(core, role),
                                       ref_importance(core, role), places=9)

    def test_score_parts_matches_eight_inputs(self):
        with mock.patch("time.time", return_value=NOW):
            for index, row in enumerate(entries()):
                kwargs = {"query_text": "苹果 甜", "hybrid": bool(index % 2),
                          "sensitive_protect": bool(index % 3 == 0),
                          "salience_boost": bool(index % 2 == 0),
                          "fan_penalty": bool(index % 4 == 0),
                          "fan_cap": 32, "fan_floor": 0.70, "fan_gain": 0.10}
                got = scoring.score_parts(Core(), row, 0.73, **kwargs)
                want = ref_parts(Core(), row, 0.73, **kwargs)
                for key in want:
                    self.assertAlmostEqual(got[key], want[key], places=9,
                                           msg="%s/%s" % (index, key))

    def test_memory_score_matches_with_trace(self):
        with mock.patch("time.time", return_value=NOW):
            for index, row in enumerate(entries()):
                trace = {"entry_ids": [row["id"]] if index % 2 else [],
                         "valence": 0.5 - 0.1 * index}
                got = scoring.memory_score(Core(trace=trace), row, 0.66)
                want = ref_parts(Core(trace=trace), row, 0.66)["score"]
                if index % 2:
                    want *= 1.0 + 0.04 * max(-1.0, min(1.0, 0.5 - 0.1 * index))
                self.assertAlmostEqual(got, max(0.0, want), places=9)

    def test_select_overflow_matches(self):
        rows = entries()
        rows[2]["pin"] = True
        for room in (0, 2, 5, 99):
            got = scoring.select_overflow_archive(rows, room)
            want = ref_select(rows, room)
            self.assertEqual([e["id"] for e in got[0]], [e["id"] for e in want[0]])
            self.assertEqual([e["id"] for e in got[1]], [e["id"] for e in want[1]])


if __name__ == "__main__":
    unittest.main()
