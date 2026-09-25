"""Validate data/content/sketchfab.json: every structure name resolves, every cross-link exists.

    python tools/check_sketchfab.py          # offline checks
    python tools/check_sketchfab.py --live   # also ask Sketchfab that each model is still public and embeddable
"""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DATA_DIR                          # noqa: E402
from app.data import Dataset                             # noqa: E402
from app.lessons import Resolver                         # noqa: E402
from app.sketchfab import TOPIC_NAME, load_catalog       # noqa: E402


def live_status(uid):
    try:
        with urllib.request.urlopen(f"https://api.sketchfab.com/v3/models/{uid}", timeout=30) as r:
            d = json.load(r)
    except Exception as exc:                             # noqa: BLE001 - any failure means "not usable"
        return f"unreachable ({exc})"
    if not d.get("embedUrl"):
        return "no embed URL"
    if d.get("isAgeRestricted"):
        return "age-restricted"
    if (d.get("status") or {}).get("processing") != "SUCCEEDED":
        return "not processed"
    return ""


def main(argv):
    ds = Dataset(DATA_DIR)
    res = Resolver(ds)
    from app.content import ContentIndex
    from app.micro.registry import MODELS
    tissues = set(ContentIndex(ds).tissues)
    models = load_catalog()
    bad = 0
    seen = set()
    for m in models:
        where = f"{m.uid} {m.name!r}"
        if m.uid in seen:
            bad += 1
            print(f"{where}: duplicate uid")
        seen.add(m.uid)
        if m.topic not in TOPIC_NAME:
            bad += 1
            print(f"{where}: topic {m.topic!r} is not one of {sorted(TOPIC_NAME)}")
        if not m.structures:
            bad += 1
            print(f"{where}: no structures, so nothing in the atlas will ever offer it")
        for n in m.structures:
            if not res.resolve(n):
                bad += 1
                print(f"{where}: structure {n!r} does not resolve")
        for mid in m.micro:
            if mid not in MODELS:
                bad += 1
                print(f"{where}: micro {mid!r} is not a model")
        for tid in m.histology:
            if tid not in tissues:
                bad += 1
                print(f"{where}: histology {tid!r} is not a tissue")
        if "--live" in argv:
            problem = live_status(m.uid)
            if problem:
                bad += 1
                print(f"{where}: {problem}")
    # the hand-written part names of downloaded models
    from app.config import SHADING
    from tools.sketchfab_parts import check as check_parts
    from app.sketchfab_local import load_curation
    for uid, cur in load_curation().items():
        for problem in check_parts(uid, cur, res, SHADING):
            bad += 1
            print(f"{uid[:8]} parts: {problem}")
    print(f"{len(models)} models, {sum(m.local for m in models)} downloaded")
    print("OK" if not bad else f"{bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
