"""Validate the licence record of every third-party file the app ships.

Every histology and radiology image and every downloaded Sketchfab model must name its author, its licence and its
source page, and the licence must be one we may redistribute. NonCommercial Sketchfab licences are allowed but
counted and must be listed (with the notice) in THIRD_PARTY_LICENSES.md; they are allowed nowhere else. The online
Sketchfab list is only streamed through Sketchfab's embed, so it needs a uid, a name and an author but no licence."""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# licences an image may carry (Wikimedia Commons short names); "de" etc. are CC jurisdiction ports
IMAGE_OK = re.compile(r"^(CC0|Public domain|No restrictions|Copyrighted free use|GFDL|"
                      r"CC BY(-SA)? (1\.0|2\.0|2\.5|3\.0|4\.0)( [a-z]{2})?)$")
# Sketchfab licence slugs: free ones, and NonCommercial ones that may only ship with the non-commercial notice
SKETCHFAB_FREE = {"cc0", "by", "by-sa"}
SKETCHFAB_NC = {"by-nc", "by-nc-sa", "by-nc-nd"}
SKETCHFAB_ND = {"by-nd", "by-nc-nd"}
UID = re.compile(r"^[0-9a-f]{32}$")

bad = 0


def problem(msg):
    global bad
    bad += 1
    print(msg)


def need(where, entry, fields):
    for f in fields:
        if not str(entry.get(f) or "").strip():
            problem(f"{where}: missing {f}")


def check_notices():
    lic = ROOT / "LICENSE"
    if not lic.exists() or "Ethan Prince" not in lic.read_text(encoding="utf-8"):
        problem("LICENSE missing or without the copyright line")
    for rel in ("THIRD_PARTY_LICENSES.md", "data/anatomy/LICENSE"):
        if not (ROOT / rel).exists():
            problem(f"{rel} missing")
    anatomy = json.loads((DATA / "anatomy" / "anatomy.json").read_text(encoding="utf-8"))
    if not anatomy.get("attribution"):
        problem("data/anatomy/anatomy.json has no attribution list")


def check_histology():
    cat = json.loads((DATA / "histology" / "catalog.json").read_text(encoding="utf-8"))
    counts, files = Counter(), set()
    for t in cat["tissues"]:
        for img in t["images"]:
            where = f"histology {t['id']}/{img.get('file')}"
            need(where, img, ("file", "author", "license", "source"))
            if img.get("license") and not IMAGE_OK.match(img["license"]):
                problem(f"{where}: licence {img['license']!r} not allowed")
            if img.get("source") and not img["source"].startswith("https://commons.wikimedia.org/wiki/File:"):
                problem(f"{where}: source is not a Commons file page: {img['source']}")
            if img.get("file") and not (DATA / "histology" / "images" / img["file"]).exists():
                problem(f"{where}: image file missing")
            if img.get("file") not in files:
                files.add(img.get("file"))
                counts[img.get("license")] += 1
    print(f"histology: {len(files)} images - " + ", ".join(f"{k} {v}" for k, v in counts.most_common()))
    return counts


def check_radiology():
    src = json.loads((DATA / "radiology" / "sources.json").read_text(encoding="utf-8"))
    counts = Counter()
    for key, e in src.items():
        where = f"radiology {key}"
        need(where, e, ("file", "author", "licence", "page"))
        if e.get("licence") and not IMAGE_OK.match(e["licence"]):
            problem(f"{where}: licence {e['licence']!r} not allowed")
        if e.get("file") and not (DATA / "radiology" / "images" / e["file"]).exists():
            problem(f"{where}: image file missing ({e['file']})")
        counts[e.get("licence")] += 1
    print(f"radiology: {len(src)} images - " + ", ".join(f"{k} {v}" for k, v in counts.most_common()))
    return counts


def check_sketchfab():
    notices = (ROOT / "THIRD_PARTY_LICENSES.md")
    notices = notices.read_text(encoding="utf-8") if notices.exists() else ""
    counts = Counter()
    for folder in sorted((DATA / "sketchfab_models").iterdir()):
        if not folder.is_dir():
            continue
        where = f"sketchfab_models/{folder.name}"
        info_path = folder / "info.json"
        if not info_path.exists():
            problem(f"{where}: no info.json")
            continue
        info = json.loads(info_path.read_text(encoding="utf-8"))
        need(where, info, ("uid", "name", "author", "license", "license_slug", "license_url", "source_url"))
        slug = info.get("license_slug", "")
        if slug not in SKETCHFAB_FREE | SKETCHFAB_NC:
            problem(f"{where}: licence {slug!r} not allowed")
        if slug in SKETCHFAB_NC and "non-commercial" not in notices.lower():
            problem(f"{where}: NonCommercial model but THIRD_PARTY_LICENSES.md has no non-commercial notice")
        if folder.name not in notices:
            problem(f"{where}: not listed in THIRD_PARTY_LICENSES.md")
        counts[slug] += 1
    nc = sum(v for k, v in counts.items() if k in SKETCHFAB_NC)
    nd = sum(v for k, v in counts.items() if k in SKETCHFAB_ND)
    print(f"downloaded Sketchfab models: {sum(counts.values())} - "
          + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
          + f"; {nc} NonCommercial (allowed with notice), {nd} NoDerivatives")

    models = json.loads((DATA / "content" / "sketchfab.json").read_text(encoding="utf-8"))["models"]
    for m in models:
        where = f"sketchfab.json {m.get('uid')}"
        need(where, m, ("uid", "name", "author"))
        if m.get("uid") and not UID.match(m["uid"]):
            problem(f"{where}: uid is not a Sketchfab model id")
    print(f"online Sketchfab list: {len(models)} models (streamed through the official embed, not redistributed)")


def main():
    check_notices()
    check_histology()
    check_radiology()
    check_sketchfab()
    print("OK" if not bad else f"{bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
