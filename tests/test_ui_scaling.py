"""The 5,000-structure speedups of the model viewer's side panels give exactly the results they gave before."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tools" / "perf", ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np  # noqa: E402

from bench_ui import make_host, tree_snapshot  # noqa: E402
from ui_perf_reference import old_filter_tree, old_resolve, old_sync_tree  # noqa: E402
from app.viewer.catalog import ModelEntry  # noqa: E402

QUERIES = ["", "c", "cell", "cell 1", "lining cell 3 nucleus", "wall segment", "group 4", "region 3", "k00010",
           "zzz", "structure part 2", "old"]


class UiScalingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = make_host(400, seed=3)
        cls.b = make_host(400, seed=3)

    def test_filter_identical_for_every_query_and_restores_expansion(self):
        base = tree_snapshot(self.a)
        self.assertEqual(base, tree_snapshot(self.b))
        for q in QUERIES + list(reversed(QUERIES)):
            ma = old_filter_tree(self.a, q)
            self.b._filter_tree(q)
            self.assertEqual(tree_snapshot(self.a), tree_snapshot(self.b), q)
            self.assertEqual(self.a.status, self.b.status, q)
            self.assertEqual(bool(ma), self.b.status == "Check to show or hide", q)
        self.assertEqual(tree_snapshot(self.b), base)

    def test_sync_identical_for_random_visibility(self):
        rng = np.random.default_rng(5)
        n = len(self.a.vmodel.items)
        for density in (0.0, 1.0, 0.5, 0.97, 0.03):
            vis = rng.random(n) < density
            self.a.vis[:] = vis
            self.b.vis[:] = vis
            old_sync_tree(self.a)
            self.b._sync_tree()
            self.assertEqual(tree_snapshot(self.a), tree_snapshot(self.b), density)

    def test_sync_after_click_hides_the_same_parts(self):
        row = next(iter(self.b.group_items.values()))
        self.b.vis[:] = True
        self.b._set_hidden(self.b._sids_of(row), True)
        self.assertEqual(row.checkState(0).value, 0)
        self.assertEqual(self.b.sync_calls > 0, True)

    def test_resolve_identical_and_cache_follows_model_changes(self):
        model = self.a.vmodel
        entry = ModelEntry("synthetic_bench_model", "Synthetic")
        entry.aliases = {"Cells": ["group:S3", "Lining cell 1"], "walls": ["Wall segment 2", "k00001"], "x": ["nope"]}
        names = ["Group 4", "lining  cell 2", "cells", "walls", "nope", "x", "old " + model.items[97].name,
                 model.items[5].key, "Region 1 / Group 1", "group 4"]
        want = old_resolve(entry, model, names)
        self.assertEqual(entry.resolve(model, names), want)
        self.assertEqual(entry.resolve(model, names), want)          # served from the cache
        self.assertEqual(entry.resolve(model, []), ([], []))
        model.items[0].name = "Renamed first part"                    # a changed catalog is picked up on rebuild
        entry._lookup_cache = None
        self.assertEqual(entry.resolve(model, ["Renamed first part"]), ([0], []))
        model.items[0].name = "Lining cell 1"

    def test_kidney_families_identical(self):
        model = self.a.vmodel
        entry = ModelEntry("kidney_nephron", "Kidney")
        names = ["Segmental arteries", "Renal pyramids", "Renal capsule (fibrous capsule)", "Wall segment 2"]
        self.assertEqual(entry.resolve(model, names), old_resolve(entry, model, names))


if __name__ == "__main__":
    unittest.main()
