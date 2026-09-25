"""Check the hand-written supplementary content in data/content/descriptions_extra*.json.

Every key must name a structure (by base name), tree group or landmark in the dataset, fields must be the known ones
with the right types, and a description is flagged when the atlas already has one (it would never be shown).
Innervation names that are not nerves in the atlas are listed as notes - they still show, just not as links.
Ends with coverage: how many structures have a description and how many muscles carry innervation.
Pass --missing to list the described-less structures that are still missing a text."""
import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DATA_DIR          # noqa: E402
from app.data import Dataset             # noqa: E402
from app.extra_content import FIELDS, GLOB, PREFIX   # noqa: E402

SKIP_MISSING = {"attachments", "regions", "reference", "findings"}


def main():
    ds = Dataset(DATA_DIR)
    content_dir = DATA_DIR.parent / "content"
    wiki = json.loads((DATA_DIR / "definitions.json").read_text(encoding="utf-8"))
    bases = {s["base"] for s in ds.structures}
    groups = {n["name"] for n in ds.nodes.values() if "sid" not in n}
    lms = {lm["name"] for lm in ds.landmarks}
    nerves = {s["base"] for s in ds.structures if s["system"] == "nervous"}
    pool = sorted(bases | groups | lms)
    has_wiki = set()
    for item in list(ds.structures) + [n for n in ds.nodes.values() if "sid" not in n] + list(ds.landmarks):
        if item.get("def") in wiki:
            has_wiki.add(item.get("base") or item["name"])

    bad = notes = 0
    seen = {}
    for path in sorted(content_dir.glob(GLOB)):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            print(f"{path.name}: invalid JSON: {exc}")
            bad += 1
            continue
        for name, entry in data.items():
            if name.startswith("_"):
                continue
            where = f"{path.name}: {name!r}"
            if not isinstance(entry, dict) or not entry:
                print(f"{where}: entry must be a non-empty object")
                bad += 1
                continue
            for field in entry:
                if (name, field) in seen:
                    print(f"{where}: {field} also set in {seen[name, field]} (the later file wins)")
                    bad += 1
                seen[name, field] = path.name
            if name not in bases and name not in groups and name not in lms:
                print(f"{where}: not in the atlas -> {difflib.get_close_matches(name, pool, n=4, cutoff=0.6)}")
                bad += 1
            for field in entry:
                if field not in FIELDS:
                    print(f"{where}: unknown field {field!r} (known: {', '.join(FIELDS)})")
                    bad += 1
            for field in ("description", "action", "blood_supply"):
                if field in entry and (not isinstance(entry[field], str) or not entry[field].strip()):
                    print(f"{where}: {field} must be a non-empty string")
                    bad += 1
            text = entry.get("description") or ""
            if text and name in has_wiki:
                print(f"{where}: already has a Wikipedia description, this text is never shown")
                bad += 1
            if '"' in text or text != text.strip():
                print(f"{where}: stray quotes or surrounding whitespace in description")
                bad += 1
            inn = entry.get("innervation")
            if inn is not None:
                if not isinstance(inn, list) or not all(isinstance(n, str) and n.strip() for n in inn):
                    print(f"{where}: innervation must be a list of nerve names ([] clears it)")
                    bad += 1
                else:
                    for n in inn:
                        if n not in nerves:
                            notes += 1
                            if "--notes" in sys.argv:
                                print(f"  note {where}: nerve {n!r} is not in the atlas (shown without a link)")

    described = sum(1 for s in ds.structures if s.get("def") in ds.definitions)
    extra = sum(1 for s in ds.structures if str(s.get("def", "")).startswith(PREFIX))
    muscles = [s for s in ds.structures if s["system"] == "muscular" and not s.get("role")]
    innerv = sum(1 for s in muscles if s.get("innervation"))
    action = sum(1 for s in muscles if s.get("action"))
    print(f"{len({n for n, _ in seen})} names; structures described {described}/{ds.n} ({extra} hand-written); "
          f"muscles with innervation {innerv}/{len(muscles)}, with action {action}; "
          f"{notes} innervation names outside the atlas (--notes lists them)")
    if "--missing" in sys.argv:
        missing = sorted({(s["system"], s["base"]) for s in ds.structures
                          if s["system"] not in SKIP_MISSING and s.get("def") not in ds.definitions})
        for system, base in missing:
            print(f"  missing: {system:15s} {base}")
    print("OK" if not bad else f"{bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
