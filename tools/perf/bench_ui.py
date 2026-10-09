"""Time the model viewer's side-panel hot paths on a synthetic ~5,000-structure model, before and after.

    python tools/perf/bench_ui.py [--items 5000] [--repeat 5]

Builds the real ModelView tree (ModelView._build_tree) on synthetic items in realistic groups (numbered cell
families, multi-mesh structures, singletons), then times one filter keystroke, one visibility sync and one
catalog resolve(), with the original implementations (reference copies in tests/ui_perf_reference.py) as "before"
and the current ModelView / ModelEntry code as "after". No GPU, no model files. Prints the medians in ms and checks
the two give identical results.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT, ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui import model_view as mv  # noqa: E402
from app.viewer.catalog import ModelEntry  # noqa: E402

_METHODS = ("_build_tree", "_filter_tree", "_sids_of", "_sids_cached", "_item_changed", "_sync_tree",
            "_build_sync_plan", "_part_description")


def synthetic_model(n_items=5000, seed=1):
    """Items and groups shaped like a real model: numbered families, multi-mesh structures, single parts."""
    rng = np.random.default_rng(seed)
    items, groups = [], []

    gnum = 0

    def add(name, structure_id):
        i = len(items)
        items.append(SimpleNamespace(index=i, name=name, key=f"k{i:05d}_{name.lower().replace(' ', '_')}",
                                     description="", group=f"Region {gnum % 12} / Group {gnum}", parts=[SimpleNamespace(structure_id=structure_id)],
                                     former_names=(("old " + name,) if i % 97 == 0 else ())))
        return i

    while len(items) < n_items:
        gnum += 1
        kind = int(rng.integers(0, 3))
        ids = []
        if kind == 0:                              # a numbered family of cells and their nuclei
            for n in range(1, int(rng.integers(8, 40))):
                ids.append(add(f"Lining cell {n}", f"S{gnum}"))
                ids.append(add(f"Lining cell {n} nucleus", f"S{gnum}"))
        elif kind == 1:                            # a structure split over several meshes
            for n in range(int(rng.integers(2, 6))):
                ids.append(add(f"Wall segment {gnum}", f"S{gnum}"))
        else:                                      # a handful of distinct parts
            for n in range(int(rng.integers(1, 6))):
                ids.append(add(f"Structure {gnum} part {n}", f"S{gnum}_{n}"))
        groups.append(SimpleNamespace(key=f"Region {gnum % 12} / Group {gnum}", title=f"Group {gnum}", items=ids))
    return SimpleNamespace(items=items, groups=groups)


class Host:
    """The slice of ModelView the tree code touches, with the real methods bound to it."""

    def __init__(self, model):
        self.vmodel = model
        self.entry = SimpleNamespace(id="synthetic_bench_model")
        self.content = SimpleNamespace(tissues={})
        self.tree = mv.Outline()
        self.vis = np.ones(len(model.items), dtype=bool)
        self.state = SimpleNamespace(visible_mask=lambda: self.vis, selected=[],
                                     set_hidden=self._set_hidden)
        self.parts_status = SimpleNamespace(setText=lambda t: setattr(self, "status", t))
        self._filter_expanded = None
        self._sync = False
        self.status = ""
        self.sync_calls = 0
        self._build_tree()
        self._sync_tree()

    def _set_hidden(self, sids, hidden):
        self.vis[list(sids)] = not hidden
        self._sync_tree()

    def _parts_layout_changed(self):
        pass

    def _update_selection_controls(self):
        self.sync_calls += 1


for _name in _METHODS:
    setattr(Host, _name, getattr(mv.ModelView, _name))


def make_host(n_items=5000, seed=1):
    QApplication.instance() or QApplication([])
    return Host(synthetic_model(n_items, seed))


def tree_snapshot(host):
    """Hidden / check state / expanded of every row, in tree order."""
    out = []

    def walk(row):
        out.append((row.text(0), row.isHidden(), row.checkState(0).value, row.isExpanded()))
        for k in range(row.childCount()):
            walk(row.child(k))

    root = host.tree.invisibleRootItem()
    for k in range(root.childCount()):
        walk(root.child(k))
    return out


def median_ms(fn, repeat):
    times = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t) * 1000)
    return statistics.median(times)


def main():
    from ui_perf_reference import old_filter_tree, old_resolve, old_sync_tree
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", type=int, default=5000)
    ap.add_argument("--repeat", type=int, default=5)
    a = ap.parse_args()
    host = make_host(a.items)
    n_rows = len(tree_snapshot(host))
    print(f"{len(host.vmodel.items)} items, {len(host.vmodel.groups)} groups, {n_rows} tree rows")

    def keystrokes(fn):
        def run():
            for text in ("c", "ce", "cel", "cell 1"):
                fn(host, text)
            fn(host, "")
        return run

    def filt_new(h, text):
        h._filter_tree(text)

    res = {}
    res["filter (5 keystrokes)"] = (median_ms(keystrokes(old_filter_tree), a.repeat),
                                    median_ms(keystrokes(filt_new), a.repeat))
    host.vis[::7] = False

    def sync_after(fn):
        def run():
            host.vis[::7] = ~host.vis[::7]
            fn(host)
        return run

    res["visibility sync"] = (median_ms(sync_after(old_sync_tree), a.repeat),
                              median_ms(sync_after(lambda h: h._sync_tree()), a.repeat))
    entry = ModelEntry("synthetic_bench_model", "Synthetic")
    entry.aliases = {"cells": ["group:S3", "Lining cell 1"], "walls": ["Wall segment 2"]}
    names = ["Group 4", "Lining cell 2", "cells", "walls", "nope"] + [it.name for it in host.vmodel.items[::50]]
    res["resolve() x1 call"] = (median_ms(lambda: old_resolve(entry, host.vmodel, names), a.repeat),
                                median_ms(lambda: entry.resolve(host.vmodel, names), a.repeat))
    print(f"{'path':24s} {'before ms':>10s} {'after ms':>10s} {'speedup':>8s}")
    for k, (b, f) in res.items():
        print(f"{k:24s} {b:10.2f} {f:10.2f} {b / f:7.1f}x")
    same = old_resolve(entry, host.vmodel, names) == entry.resolve(host.vmodel, names)
    print("resolve identical:", same)


if __name__ == "__main__":
    main()
