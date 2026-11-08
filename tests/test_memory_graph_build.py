# -*- coding: utf-8 -*-
"""Graph building must not copy the whole graph on every upsert."""
import copy
import unittest
from unittest import mock

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_model import entity_graph as EG


class GraphUpsertCostTest(unittest.TestCase):

    def test_inplace_upsert_does_not_deepcopy_the_graph(self):
        calls = {"n": 0}
        real = copy.deepcopy

        def counted(value, *args, **kwargs):
            calls["n"] += 1
            return real(value, *args, **kwargs)

        graph = EG.empty_graph()
        with mock.patch("copy.deepcopy", counted):
            for index in range(120):
                graph, _eid = EG.upsert_edge(graph, "甲%d" % index, "co_occurs",
                                             "乙%d" % index, ts=float(index),
                                             inplace=True)
        self.assertGreater(len(graph["edges"]), 0)
        self.assertLess(calls["n"], 10, "deepcopy must not grow with N")

    def test_external_callers_still_get_a_copy(self):
        graph = EG.empty_graph()
        before = copy.deepcopy(graph)
        graph, eid = EG.upsert_entity(graph, "阿野", "person")
        self.assertTrue(eid)
        self.assertEqual(before["entities"], [], "input graph must stay untouched")
        self.assertEqual(len(graph["entities"]), 1)

    def test_inplace_build_matches_the_copy_build(self):
        left = EG.empty_graph()
        right = EG.empty_graph()
        for index in range(40):
            left, _ = EG.upsert_edge(left, "甲%d" % index, "co_occurs", "乙%d" % index,
                                     ts=float(index))
            right, _ = EG.upsert_edge(right, "甲%d" % index, "co_occurs", "乙%d" % index,
                                      ts=float(index), inplace=True)
        self.assertEqual(left["entities"], right["entities"])
        self.assertEqual(left["edges"], right["edges"])


if __name__ == "__main__":
    unittest.main()
