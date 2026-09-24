"""Check that every target named by a clinical correlation exists in the dataset."""
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DATA_DIR          # noqa: E402
from app.content import ContentIndex     # noqa: E402
from app.data import Dataset             # noqa: E402


def main():
    ds = Dataset(DATA_DIR)
    by_base = {s["base"].lower() for s in ds.structures}
    groups = {n["name"].lower() for n in ds.nodes.values() if n["kind"] != "structure"}
    pool = sorted(by_base | groups)
    bad = 0
    for entry in ContentIndex(ds).clinical:
        for target in entry["targets"]:
            key = target.lower()
            if key not in by_base and key not in groups:
                bad += 1
                near = difflib.get_close_matches(key, pool, n=4, cutoff=0.6)
                print(f"{entry['title']!r}: {target!r} -> {near}")
    print("OK" if not bad else f"{bad} unresolved targets")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
