"""Check microanatomy models against the rules in docs/microanatomy_models.md.

Usage: python tools/check_micro.py [model_id ...] [--all] [--rebuild] [--names-out FILE] [--names-against FILE]

For each model (read from data/micro_cache, or built when stale; --rebuild always builds and times it):

* FAIL  the builder raises, a part is empty, two parts share a name, or a part name that a lesson uses
        (micro_focus, find_micro, practice items) no longer exists;
* WARN  more than 1.5 M triangles, a build over 180 s, or a part that is not closed - more than 1% of its edges
        have only one face after merging coincident vertices (cut faces need closed meshes; tiny particles and
        deliberately open sheets can be ignored if they look right in the cut view).

--names-out writes {model: [part names]} so a later run with --names-against reports every part that was
renamed or removed. Take the snapshot before a redesign.
Exit status is 1 when anything FAILs.
"""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TRI_BUDGET = 1_500_000
TIME_BUDGET = 180.0
OPEN_EDGE_LIMIT = 0.01


def lesson_refs():
    """{model id: {part name: [where, ...]}} for every micro part named in data/content."""
    refs = {}

    def add(model, part, where):
        refs.setdefault(model, {}).setdefault(part, []).append(where)

    def walk(node, where, micro=None):
        if isinstance(node, dict):
            micro = node.get("micro", micro) if isinstance(node.get("micro", micro), str) else micro
            for part in node.get("micro_focus", []) or []:
                if micro:
                    add(micro, part, where)
            if node.get("type") == "find_micro" and node.get("model") and node.get("part"):
                add(node["model"], node["part"], where)
            for k, v in node.items():
                walk(v, where, micro)
        elif isinstance(node, list):
            for v in node:
                walk(v, where, micro)

    for f in sorted((ROOT / "data" / "content").glob("*.json")):
        try:
            walk(json.loads(f.read_text(encoding="utf-8")), f.name)
        except (OSError, ValueError):
            pass
    return refs


def open_edge_fraction(pos, idx):
    if len(idx) == 0:
        return 0.0
    _, inv = np.unique(np.round(pos, 6), axis=0, return_inverse=True)
    tri = inv.reshape(-1)[idx.astype(np.int64)]
    e = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    e.sort(axis=1)
    e = e[e[:, 0] != e[:, 1]]
    if len(e) == 0:
        return 0.0
    _, counts = np.unique(e, axis=0, return_counts=True)
    return float((counts == 1).sum()) / len(counts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--rebuild", action="store_true", help="build from source (and time it) even if cached")
    ap.add_argument("--names-out")
    ap.add_argument("--names-against")
    a = ap.parse_args()

    from PySide6.QtGui import QGuiApplication  # noqa: F401  (QColor needs the Qt GUI module loaded)
    from app.micro.cache import save_parts, source_digest
    from app.micro.registry import MODELS

    ids = list(MODELS) if a.all or not a.models else a.models
    refs = lesson_refs()
    before = json.loads(Path(a.names_against).read_text()) if a.names_against else {}
    fails = warns = 0
    snapshot = {}
    for mid in ids:
        if mid not in MODELS:
            print(f"FAIL {mid}: not registered")
            fails += 1
            continue
        model = MODELS[mid]
        t = time.time()
        try:
            if a.rebuild:
                parts = model.build()
                save_parts(mid, parts, source_digest(model))
                model._parts = parts
            else:
                parts = model.parts()
        except Exception as exc:                     # noqa: BLE001
            print(f"FAIL {mid}: build raised {type(exc).__name__}: {exc}")
            fails += 1
            continue
        dt = time.time() - t
        names = [p.name for p in parts]
        snapshot[mid] = names
        tris = verts = 0
        problems = []
        for p in parts:
            pos, _nrm, idx = p.mesh.arrays()
            tris += len(idx)
            verts += len(pos)
            if len(idx) == 0:
                problems.append(("FAIL", f"part {p.name!r} is empty"))
            elif not getattr(p, "anim", None) or len(idx) > 2000:
                frac = open_edge_fraction(pos, idx)
                if frac > OPEN_EDGE_LIMIT:
                    problems.append(("WARN", f"part {p.name!r} is not closed ({frac:.1%} open edges)"))
        for name, n in Counter(names).items():
            if n > 1:
                problems.append(("FAIL", f"{n} parts are named {name!r}"))
        for part, where in sorted(refs.get(mid, {}).items()):
            if part not in names:
                problems.append(("FAIL", f"part {part!r} used by {', '.join(sorted(set(where)))} is missing"))
        for part in before.get(mid, []):
            if part not in names:
                problems.append(("WARN", f"part {part!r} from the snapshot was renamed or removed"))
        if tris > TRI_BUDGET:
            problems.append(("WARN", f"{tris:,} triangles is over the {TRI_BUDGET:,} budget"))
        if a.rebuild and dt > TIME_BUDGET:
            problems.append(("WARN", f"build took {dt:.0f} s (budget {TIME_BUDGET:.0f} s)"))
        anim = " animated" if getattr(model, "animation", None) is not None else ""
        how = "built" if a.rebuild else "loaded"
        print(f"{'OK  ' if not problems else '    '}{mid}: {len(parts)} parts, {tris:,} tris, {verts:,} verts,"
              f"{anim} {how} in {dt:.1f} s")
        for level, msg in problems:
            print(f"  {level} {msg}")
            fails += level == "FAIL"
            warns += level == "WARN"
    if a.names_out:
        Path(a.names_out).write_text(json.dumps(snapshot, indent=1))
    print(f"{len(ids)} models: {fails} failures, {warns} warnings")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
