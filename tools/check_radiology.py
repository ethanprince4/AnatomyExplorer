"""Validate radiology cases: images present, label coordinates sane, structure names resolvable."""
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DATA_DIR              # noqa: E402
from app.data import Dataset                 # noqa: E402
from app.lessons import Resolver             # noqa: E402
from app.radiology import IMAGE_DIR, load_cases   # noqa: E402


def main():
    ds = Dataset(DATA_DIR)
    res = Resolver(ds)
    pool = list(res.by_lower) + list(res.groups) + list(res.collections) + list(res.landmarks)
    systems = {s["key"] for s in ds.systems}
    regions = {r["key"] for r in ds.regions}
    cases = load_cases()
    bad = 0
    from app.viewer.catalog import load_catalog
    catalog = load_catalog()
    prepared = {}
    token = type("Token", (), {"cancelled": False, "check": lambda self: None})()
    for case in cases:
        model_id = case.scene.get("micro")
        entry = catalog.get(model_id) if model_id else None
        model = None
        if model_id:
            if entry is None:
                bad += 1
                print(f"{case.id}: model {model_id!r} is unavailable")
            else:
                if model_id not in prepared:
                    prepared[model_id] = entry.load() if hasattr(entry, "load") else entry.prepare_cpu(token)
                model = prepared[model_id]
                for field in ("micro_focus", "micro_context"):
                    _, missing = entry.resolve(model, case.scene.get(field, []))
                    for name in missing:
                        bad += 1
                        print(f"{case.id} scene[{field}]: model part {name!r} is unavailable")
        if not case.has_image:
            bad += 1
            print(f"{case.id}: image missing ({case.image})")
        for key in case.scene.get("systems", []):
            if key not in systems:
                bad += 1
                print(f"{case.id}: unknown system {key!r}")
        for key in case.scene.get("regions", []):
            if key not in regions:
                bad += 1
                print(f"{case.id}: unknown region {key!r}")
        for field in ("focus", "show", "frame_on"):
            for name in case.scene.get(field, []):
                if not res.resolve(name):
                    bad += 1
                    print(f"{case.id} scene[{field}] {name!r} -> "
                          f"{difflib.get_close_matches(name.lower(), pool, n=4, cutoff=0.6)}")
        for i, lab in enumerate(case.labels, 1):
            if not (0.0 <= lab.x <= 1.0 and 0.0 <= lab.y <= 1.0):
                bad += 1
                print(f"{case.id} label {i} off the image: {lab.x}, {lab.y}")
            for name in lab.structures:
                if not (bool(entry.resolve(model, [name])[0]) if model is not None else res.resolve(name)):
                    bad += 1
                    print(f"{case.id} label {i} ({lab.text!r}) {name!r} -> "
                          f"{difflib.get_close_matches(name.lower(), pool, n=4, cutoff=0.6)}")
    found = {p.stem for p in IMAGE_DIR.glob("*")}
    unused = found - {c.id for c in cases}
    print(f"{len(cases)} cases, {sum(len(c.labels) for c in cases)} labels"
          + (f"; images with no case yet: {sorted(unused)}" if unused else ""))
    print("OK" if not bad else f"{bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
