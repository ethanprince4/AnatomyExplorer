"""The parts of a downloaded Sketchfab model, and a check of the hand-written curation for it.

    python tools/sketchfab_parts.py                 # every downloaded model, one line each
    python tools/sketchfab_parts.py UID             # that model's parts as the importer's heuristics name them
    python tools/sketchfab_parts.py --check [UID]   # validate data/content/sketchfab_parts/<uid>.json

A curation file (data/content/sketchfab_parts/<uid>.json) looks like:
{
  "name": "optional display name", "summary": "optional",
  "rotate": [x, y, z],            degrees, if the model comes in lying on its side
  "view": [yaw, pitch],           degrees, the camera it opens with (yaw 0 = looking at the model's front)
  "vertex_colors": true,          false if the file's vertex colours are junk
  "default_group": "Heart",       group for parts that have none
  "size_mm": 120,                 the model's largest real dimension, when the file's own units are wrong (measuring)
  "clinical": [["title", "text"], ...],
  "parts": {
    "<heuristic name, or group/name>": {"name": "...", "group": "...", "description": "...",
                                        "structures": ["atlas names"], "category": "bone", "color": "#rrggbb",
                                        "alpha": 0.4, "label": true, "hide": false},
    "<a part to drop>": null
  }
}
Parts that share a new name and group merge into one.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.sketchfab_local import CURATION_DIR, build_parts, default_parts, load_curation, local_uids  # noqa: E402
from app.sketchfab import LOCAL_DIR                                                                   # noqa: E402

KEYS = {"name", "summary", "rotate", "view", "vertex_colors", "default_group", "clinical", "parts", "notes", "size_mm"}
PART_KEYS = {"name", "group", "description", "structures", "category", "color", "alpha", "label", "hide"}


def resolve_uid(arg):
    hits = [u for u in local_uids() if u.startswith(arg)]
    if len(hits) != 1:
        sys.exit(f"{arg!r} matches {len(hits)} downloaded models")
    return hits[0]


def info(uid):
    return json.loads((LOCAL_DIR / uid / "info.json").read_text(encoding="utf-8"))


def list_parts(uid):
    glb = LOCAL_DIR / uid / "model.glb"
    print(f"{uid}  {info(uid)['name']}")
    print("  (centre and size are in the viewer's units: the model spans 2 across; +y up, +z towards the viewer)")
    stats = {(p.name, p.group): p for p in build_parts(glb, {})[0]}
    for name, group, tris, mats in default_parts(glb):
        p = stats.get((name, group))
        extra = ""
        if p is not None:
            v = p.mesh.parts[0][0]
            lo, hi = v.min(axis=0), v.max(axis=0)
            c, sz = (lo + hi) / 2, hi - lo
            extra = (f"  centre ({c[0]:+.2f},{c[1]:+.2f},{c[2]:+.2f}) size ({sz[0]:.2f},{sz[1]:.2f},{sz[2]:.2f})"
                     f"  colour {p.color}" + (f"  alpha {p.alpha:.2f}" if p.alpha < 1 else ""))
        key = f"{group}/{name}" if group else name
        print(f"  {key!r:44} {tris:>8} tris  materials {mats}{extra}")


def check(uid, cur, resolver, shading):
    problems = []
    if uid not in local_uids():
        return [f"{uid}: curation for a model that is not downloaded"]
    for k in cur:
        if k not in KEYS:
            problems.append(f"unknown key {k!r}")
    for k, n in (("rotate", 3), ("view", 2)):
        if k in cur and (not isinstance(cur[k], list) or len(cur[k]) != n):
            problems.append(f"{k} must be a list of {n} numbers")
    names = set()
    for name, group, _t, _m in default_parts(LOCAL_DIR / uid / "model.glb"):
        names.add(name)
        names.add(f"{group}/{name}")
    for key, o in (cur.get("parts") or {}).items():
        if key not in names:
            problems.append(f"part {key!r} is not in the model (see tools/sketchfab_parts.py {uid[:8]})")
        if o is None:
            continue
        for k in o:
            if k not in PART_KEYS:
                problems.append(f"part {key!r}: unknown key {k!r}")
        for s in o.get("structures", []):
            if not resolver.resolve(s):
                problems.append(f"part {key!r}: structure {s!r} does not resolve in the atlas")
        if o.get("category") and o["category"] not in shading:
            problems.append(f"part {key!r}: category {o['category']!r} is not one of {sorted(shading)}")
        col = o.get("color")
        if col and not (isinstance(col, str) and len(col) == 7 and col.startswith("#")):
            problems.append(f"part {key!r}: color must look like #rrggbb")
        if "alpha" in o and not 0.02 <= float(o["alpha"]) <= 1.0:
            problems.append(f"part {key!r}: alpha must be between 0.02 and 1")
    return problems


def main(argv):
    if "--check" in argv:
        from app.config import DATA_DIR, SHADING
        from app.data import Dataset
        from app.lessons import Resolver
        resolver = Resolver(Dataset(DATA_DIR))
        wanted = [resolve_uid(a) for a in argv if not a.startswith("--")]
        cur = load_curation()
        bad = 0
        for f in sorted(CURATION_DIR.glob("*.json")):
            if wanted and f.stem not in wanted:
                continue
            if f.stem not in cur:
                print(f"{f.name}: not valid JSON")
                bad += 1
                continue
            for p in check(f.stem, cur[f.stem], resolver, SHADING):
                print(f"{f.stem[:8]}: {p}")
                bad += 1
        print(f"{len(cur)} curation files, " + ("OK" if not bad else f"{bad} problems"))
        return 1 if bad else 0
    if argv:
        list_parts(resolve_uid(argv[0]))
        return 0
    cur = load_curation()
    for uid in local_uids():
        n = len(default_parts(LOCAL_DIR / uid / "model.glb"))
        print(f"{uid[:8]}  {n:3} parts  {'curated' if uid in cur else 'not curated':11}  {info(uid)['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
