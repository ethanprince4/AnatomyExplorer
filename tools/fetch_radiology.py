"""Fetch normal radiographs, CT and MRI images from Wikimedia Commons into data/radiology.

Two modes:

  python tools/fetch_radiology.py search "normal chest radiograph"   - list candidate files with licence and size
  python tools/fetch_radiology.py fetch                              - download the curated list in CASES

The curated list is deliberate: normal-anatomy images only, each one checked by eye before being added, with its
author and licence recorded so the viewer can show them.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "radiology"
IMAGES = OUT / "images"
CACHE = OUT / "cache"
for d in (IMAGES, CACHE):
    d.mkdir(parents=True, exist_ok=True)

UA = "AnatomyExplorer/1.0 (personal offline anatomy atlas) python-urllib"
API = "https://commons.wikimedia.org/w/api.php"
THUMB_WIDTH = 1280          # a standard Wikimedia thumbnail size, served from cache
MAX_SIDE = 1600
_interval = [1.2]
_last = [0.0]

# Commons file titles to download, keyed by the id used in data/content/radiology.json.
WANTED = {}


def get(url, binary=False, retries=6):
    for attempt in range(retries):
        wait = _interval[0] - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            return data if binary else json.loads(data)
        except urllib.error.HTTPError as e:
            after = e.headers.get("Retry-After") if e.headers else None
            delay = float(after) if after and after.isdigit() else min(10 * (attempt + 1), 90)
            if e.code == 429:
                _interval[0] = min(_interval[0] * 1.6, 8.0)
            print(f"  HTTP {e.code}; waiting {delay:.0f}s")
            time.sleep(delay)
        except Exception as e:                      # noqa: BLE001
            print(f"  retry {attempt + 1}: {e}")
            time.sleep(4 + 4 * attempt)
    return None


def api(**params):
    params = dict(params, format="json", formatversion=2)
    return get(API + "?" + urllib.parse.urlencode(params))


def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = text.replace("&amp;", "&").replace("&nbsp;", " ").replace("&quot;", '"').replace("&#39;", "'")
    return re.sub(r"\s+", " ", text).strip()


def file_info(titles):
    """Image info, licence and description for a batch of File: titles."""
    out = {}
    titles = list(titles)
    for i in range(0, len(titles), 20):
        batch = titles[i:i + 20]
        data = api(action="query", prop="imageinfo", titles="|".join(batch),
                   iiprop="url|size|extmetadata|mime", iiurlwidth=THUMB_WIDTH)
        for page in (data or {}).get("query", {}).get("pages", []):
            info = (page.get("imageinfo") or [{}])[0]
            if not info:
                continue
            meta = info.get("extmetadata", {})
            out[page["title"]] = {
                "title": page["title"],
                "thumb": info.get("thumburl") or info.get("url"),
                "width": info.get("width"),
                "height": info.get("height"),
                "mime": info.get("mime", ""),
                "page": info.get("descriptionurl", ""),
                "licence": strip_html(meta.get("LicenseShortName", {}).get("value", "")),
                "author": strip_html(meta.get("Artist", {}).get("value", "")),
                "credit": strip_html(meta.get("Credit", {}).get("value", "")),
                "description": strip_html(meta.get("ImageDescription", {}).get("value", ""))[:400],
            }
    return out


def search(query, limit=25):
    data = api(action="query", list="search", srsearch=f"filetype:bitmap {query}", srnamespace=6, srlimit=limit)
    titles = [h["title"] for h in (data or {}).get("query", {}).get("search", [])]
    info = file_info(titles)
    for t in titles:
        m = info.get(t)
        if not m:
            continue
        print(f"{m['width']}x{m['height']:<6} {m['licence'][:22]:24s} {t}")
        if m["description"]:
            print(f"      {m['description'][:150]}")
    return titles


def fetch(wanted):
    """Download each wanted file and write data/radiology/sources.json with the attribution."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QImage
    app = QGuiApplication.instance() or QGuiApplication(["x", "-platform", "offscreen"])   # noqa: F841
    info = file_info(wanted.values())
    sources = {}
    path = OUT / "sources.json"
    if path.exists():
        try:
            sources = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            sources = {}
    for key, title in wanted.items():
        meta = info.get(title)
        if not meta:
            print(f"MISSING  {key}: {title}")
            continue
        ext = ".png" if meta["mime"].endswith("png") else ".jpg"
        dest = IMAGES / f"{key}{ext}"
        if not dest.exists():
            data = get(meta["thumb"].split("?")[0], binary=True)
            if not data or len(data) < 3000:
                print(f"FAILED   {key}")
                continue
            img = QImage()
            if not img.loadFromData(data):
                print(f"BAD IMG  {key}")
                continue
            if max(img.width(), img.height()) > MAX_SIDE:
                img = img.scaled(MAX_SIDE, MAX_SIDE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            if ext == ".jpg":
                img = img.convertToFormat(QImage.Format_RGB32)
                ok = img.save(str(dest), "JPG", 92)
            else:
                ok = img.save(str(dest), "PNG")
            if not ok:
                print(f"SAVE ERR {key}")
                continue
        sources[key] = {
            "file": dest.name, "commons": meta["title"], "page": meta["page"],
            "licence": meta["licence"], "author": meta["author"] or meta["credit"],
            "description": meta["description"],
        }
        print(f"ok       {key}  {dest.name}  {meta['licence']}")
    path.write_text(json.dumps(sources, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(sources)} images in {path}")


def main():
    args = sys.argv[1:]
    if args and args[0] == "search":
        search(" ".join(args[1:]) or "radiograph")
        return 0
    if args and args[0] == "info":
        for title, meta in file_info(args[1:]).items():
            print(json.dumps(meta, indent=1, ensure_ascii=False))
        return 0
    wanted = WANTED
    if not wanted:
        cfg = CACHE / "wanted.json"
        if cfg.exists():
            wanted = json.loads(cfg.read_text(encoding="utf-8"))
    if not wanted:
        print("Nothing to fetch: fill in WANTED or data/radiology/cache/wanted.json")
        return 1
    fetch(wanted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
