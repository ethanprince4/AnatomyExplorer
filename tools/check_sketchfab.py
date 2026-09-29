"""Validate data/content/sketchfab.json, the catalogue of the downloaded models: every structure name resolves and
every cross-link exists. Also validates the hand-written part curation of each downloaded model. Works offline.

    python tools/check_sketchfab.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DATA_DIR                          # noqa: E402
from app.data import Dataset                             # noqa: E402
from app.lessons import Resolver                         # noqa: E402
from app.sketchfab import TOPIC_NAME, load_catalog       # noqa: E402


def main(argv):
    if argv:
        print(__doc__)
        return 0 if argv[0] in ("-h", "--help") else 2
    ds = Dataset(DATA_DIR)
    res = Resolver(ds)
    from app.content import ContentIndex
    from app.viewer.catalog import load_catalog as load_models
    MODELS = load_models()
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
                print(f"{where}: micro {mid!r} is not a model in the catalogue")
        for tid in m.histology:
            if tid not in tissues:
                bad += 1
                print(f"{where}: histology {tid!r} is not a tissue")
    # the hand-written part names of downloaded models
    from app.config import SHADING
    from tools.sketchfab_parts import check as check_parts
    from app.viewer.imported import load_curation
    for uid, cur in load_curation().items():
        for problem in check_parts(uid, cur, res, SHADING):
            bad += 1
            print(f"{uid[:8]} parts: {problem}")
    print(f"{len(models)} downloaded models")
    print("OK" if not bad else f"{bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
