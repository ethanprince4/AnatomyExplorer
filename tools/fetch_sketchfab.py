"""Download (or refresh) the 3D models of data/content/sketchfab.json from Sketchfab's official Download API.

    python tools/fetch_sketchfab.py            # every model of the catalogue that is not complete on disk
    python tools/fetch_sketchfab.py UID ...    # just these
    python tools/fetch_sketchfab.py --force    # fetch again even if already on disk

Needs your own API token (sketchfab.com -> Settings -> Password & API) in data/user/sketchfab_token.txt. Models the
author did not make downloadable are skipped. Each model lands in data/sketchfab_models/<uid>/ as model.glb plus
info.json with its licence and credit, which the app shows wherever the model appears. The app opens these files
offline; it never streams a model.

The catalogue is read through app.sketchfab.load_catalog(), which lists only models already on disk, so in practice
this refreshes the downloaded models (--force) rather than adding new ones.
"""
import datetime
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.sketchfab import LOCAL_DIR, TOKEN_PATH, load_catalog     # noqa: E402

API = "https://api.sketchfab.com/v3/models/{uid}"
PAGE = "https://sketchfab.com/3d-models/{uid}"       # the model's source page, credited in info.json


def get_json(url, token=None):
    headers = {"Authorization": f"Token {token}"} if token else {}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
        return json.load(r)


def download(url, dest):
    """Fetch to a .part file and keep it only if it is a whole .glb (its header states its own length)."""
    import struct
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(url, timeout=300) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    with open(tmp, "rb") as f:
        head = f.read(12)
    if len(head) < 12 or head[:4] != b"glTF" or struct.unpack_from("<I", head, 8)[0] != tmp.stat().st_size:
        tmp.unlink()
        raise OSError("download was incomplete")
    tmp.replace(dest)


def fetch(model, token, force=False):
    out = LOCAL_DIR / model.uid
    glb = out / "model.glb"
    if glb.exists() and (out / "info.json").exists() and not force:
        return "already here"
    meta = get_json(API.format(uid=model.uid))
    if not meta.get("isDownloadable"):
        return "not downloadable"
    links = get_json(API.format(uid=model.uid) + "/download", token)
    if "glb" not in links:
        return f"no glb archive (has {', '.join(links) or 'nothing'})"
    out.mkdir(parents=True, exist_ok=True)
    download(links["glb"]["url"], glb)       # a pre-signed link: no token goes with it
    lic = meta.get("license") or {}
    user = meta.get("user") or {}
    info = {
        "uid": model.uid,
        "name": meta.get("name") or model.name,
        "author": user.get("displayName") or user.get("username") or model.author,
        "author_url": user.get("profileUrl", ""),
        "license": lic.get("label", ""),
        "license_slug": lic.get("slug", ""),
        "license_url": lic.get("url", ""),
        "source_url": meta.get("viewerUrl", PAGE.format(uid=model.uid)),
        "downloaded": datetime.date.today().isoformat(),
        "bytes": glb.stat().st_size,
    }
    (out / "info.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    result = f"{info['bytes'] / 1e6:.1f} MB, {info['license']}"
    if info["bytes"] > 95 * 1024 * 1024:           # GitHub refuses files over 100 MB outside Git LFS
        rel = glb.relative_to(ROOT).as_posix()
        result += f"\n          over GitHub's file limit - before committing run: git lfs track \"{rel}\""
    return result


def main(argv):
    try:
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        print(f"Put your Sketchfab API token in {TOKEN_PATH} first (Settings -> Password & API on sketchfab.com).")
        return 1
    force = "--force" in argv
    wanted = [a for a in argv if not a.startswith("--")]
    models = [m for m in load_catalog() if not wanted or m.uid in wanted]
    failed = 0
    for m in models:
        try:
            result = fetch(m, token, force)
        except urllib.error.HTTPError as exc:
            failed += 1
            result = f"HTTP {exc.code} {exc.reason}"
        except OSError as exc:
            failed += 1
            result = f"failed: {exc}"
        print(f"{m.uid[:8]}  {m.name[:48]:48}  {result}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
