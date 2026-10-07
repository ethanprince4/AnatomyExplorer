"""Build every cache the installed app would otherwise try to build (and fail to write) on first use.

1. The microanatomy meshes in data/micro_cache (tools/build_micro.py; only the stale ones are rebuilt), then a
   check that every model now loads from the cache - the packaged app ships the app/micro sources, so it computes
   the same digest and never rebuilds.
2. The atlas manifest, surface samples and depth index, stamped with the installed content identity,
   written to packaging/build/stage/data/anatomy. The spec ships these in place
   of the copies in data/anatomy, which carry this machine's file times and would not match after installation.
3. For legacy builds without a release library, check the in-house GLB models.
   A post-only release library replaces those assets; build.py checks its selected paths before packaging.

Usage: python packaging/prebuild.py [--jobs N] [--skip-micro] [--skip-models]"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "packaging" / "build" / "stage"
sys.path.insert(0, str(ROOT))


def micro(jobs):
    from PySide6.QtGui import QGuiApplication  # noqa: F401  (QColor needs the Qt GUI module loaded)
    from app.micro.cache import load_parts, source_digest
    from app.micro.registry import MODELS

    def stale():
        return [mid for mid, m in MODELS.items() if load_parts(mid, source_digest(m)) is None]

    todo = stale()
    print(f"micro models: {len(MODELS)}, to build: {len(todo)}", flush=True)
    if todo:
        subprocess.run([sys.executable, str(ROOT / "tools" / "build_micro.py"), *todo, "--jobs", str(jobs)],
                       cwd=ROOT, check=True)
        todo = stale()
        if todo:
            sys.exit(f"these micro models still do not load from the cache: {', '.join(todo)}")


def anatomy():
    from app import depth, relations
    from app.config import DATA_DIR
    from app.data import Dataset
    from app.dataset_identity import MANIFEST_NAME, build_manifest

    out = STAGE / "data" / "anatomy"
    out.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(DATA_DIR)
    (out / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    relations.STAMP_MTIME = False
    # read nothing, write into the stage (never over the repo's own copies)
    relations.cache_candidates = lambda path: ([], out / Path(path).name)
    depth.cache_candidates = relations.cache_candidates
    t = time.time()
    ds = Dataset(DATA_DIR)
    ds._dataset_content_id = manifest["content_id"]
    d, _ = depth.DepthIndex(ds)._load()          # computes the surface samples on the way
    if not (out / "samples.npz").exists() or not (out / "depth.npz").exists() or d is None:
        sys.exit("failed to build the anatomy caches")
    print(f"anatomy caches written to {out} in {time.time() - t:.0f} s", flush=True)


def models():
    from app.viewer.catalog import GlbEntry, load_meta

    t = time.time()
    for meta in load_meta():
        e = GlbEntry(meta)
        if not e.available():
            sys.exit(f"{e.path} is missing or a Git LFS pointer: run git lfs pull")
        m = e.load()
        print(f"model {e.id}: {len(m.items)} parts, {m.triangle_count:,} triangles", flush=True)
    print(f"in-house models checked in {time.time() - t:.0f} s", flush=True)


def main():
    args = sys.argv[1:]
    jobs = int(args[args.index("--jobs") + 1]) if "--jobs" in args else 4
    if "--skip-micro" not in args:
        micro(jobs)
    anatomy()
    if "--skip-models" not in args:
        models()


if __name__ == "__main__":
    main()
