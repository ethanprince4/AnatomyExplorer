"""Build (or rebuild) the microanatomy model cache in parallel.

Usage: python tools/build_micro.py [model_id ...] [--jobs N]
Meshes are written to data/micro_cache; the app loads them instantly afterwards."""
import sys
import time
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build(model_id):
    from PySide6.QtGui import QGuiApplication  # noqa: F401  (QColor needs the Qt GUI module loaded)
    from app.micro.cache import save_parts, source_digest
    from app.micro.registry import MODELS
    t = time.time()
    model = MODELS[model_id]
    parts = model.build()
    save_parts(model_id, parts, source_digest(model))
    tris = sum(len(p.mesh.arrays()[2]) for p in parts)
    return model_id, len(parts), tris, time.time() - t


def main():
    args = sys.argv[1:]
    jobs = 4
    if "--jobs" in args:
        i = args.index("--jobs")
        jobs = int(args[i + 1])
        del args[i:i + 2]
    from app.micro.registry import MODELS
    ids = args or list(MODELS)
    start = time.time()
    with Pool(min(jobs, len(ids))) as pool:
        for mid, n, tris, secs in pool.imap_unordered(build, ids):
            print(f"{mid:22s} {n:3d} parts {tris / 1e6:6.2f} M triangles  {secs:6.1f} s", flush=True)
    print(f"done in {time.time() - start:.1f} s")


if __name__ == "__main__":
    main()
