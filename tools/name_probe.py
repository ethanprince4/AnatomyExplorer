"""Check names against the dataset before writing them into a lesson.

    python tools/name_probe.py "Median nerve" "Flexor pollicis longus"
    python tools/name_probe.py --file candidates.txt        # one name per line
    python tools/name_probe.py --like "flexor"              # every resolvable name containing a word

Prints one line per name: OK with how many structures it resolves to, or the nearest matches.
"""
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DATA_DIR                 # noqa: E402
from app.data import Dataset                    # noqa: E402
from app.lessons import Resolver                # noqa: E402


def main(argv):
    ds = Dataset(DATA_DIR)
    res = Resolver(ds)
    pool = sorted(set(list(res.by_lower) + list(res.groups) + list(res.collections) + list(res.landmarks)))
    if argv and argv[0] == "--like":
        needle = " ".join(argv[1:]).lower()
        hits = [n for n in pool if needle in n]
        print(f"{len(hits)} names contain {needle!r}")
        for n in hits:
            print("  ", n)
        return 0
    if argv and argv[0] == "--file":
        names = [ln.strip() for ln in Path(argv[1]).read_text(encoding="utf-8").splitlines() if ln.strip()]
    else:
        names = list(argv)
    bad = 0
    for name in names:
        sids = res.resolve(name)
        if sids:
            print(f"OK   {name}  ({len(sids)})")
        else:
            bad += 1
            near = difflib.get_close_matches(name.lower(), pool, n=5, cutoff=0.5)
            print(f"MISS {name}  -> {near}")
    print(f"{len(names) - bad}/{len(names)} resolve")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
