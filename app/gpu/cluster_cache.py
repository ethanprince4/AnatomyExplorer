"""Cache of the cluster build (app/gpu/clusters.py), beside the prepared-model cache, never next to the models.

* Where: ``<per-user cache folder>/clusters/<key>/`` (the prepared cache is ``.../cache/prepared_models``; its own
  prune() never sees this folder). ``ANATOMY_CLUSTER_CACHE`` overrides the folder and ``=off`` disables the cache;
  ``ANATOMY_PREPARED_CACHE=off`` disables it too. ``ANATOMY_CLUSTER_CACHE_GB`` is the size cap (default 4).
* Identity: a cluster set depends on every vertex position and index of the model, so the key is derived from the
  prepared-model cache entry the model's arrays are memory-mapped from (its key already covers the source file's
  size and mtime, the LOD constants and the prepared FORMAT_VERSION), plus this module's BUILD_VERSION, the cluster
  size, and the geometry layout (page size, every part's page and index ranges). A model whose arrays are not backed
  by a prepared-cache file has no stable identity: it is built every time and not saved (no stale-bounds risk).
* Same write protocol as prepared_cache: a temporary folder renamed into place; anything that goes wrong means "no
  cache" and the caller builds. Nothing here raises into the renderer.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path

import numpy as np

from app.viewer import prepared_cache as _prep

from . import clusters as cl

DEFAULT_CAP_GB = 4.0
_ARRAYS = ("r_part", "r_page", "r_first", "r_ntri", "r_cfirst", "r_tfirst", "r_ccount", "level_range", "uncullable",
           "page_cfirst", "cl_geom", "cl_range", "perm")


def cache_root():
    value = os.environ.get("ANATOMY_CLUSTER_CACHE", "")
    if value.lower() in ("off", "0", "false", "none"):
        return None
    if value:
        return Path(value)
    base = _prep.cache_root()
    return None if base is None else base.parent / "clusters"


def cap_bytes():
    try:
        return int(float(os.environ.get("ANATOMY_CLUSTER_CACHE_GB", DEFAULT_CAP_GB)) * (1 << 30))
    except ValueError:
        return int(DEFAULT_CAP_GB * (1 << 30))


def prepared_identity(model):
    """The prepared-cache key the model's vertex array is mapped from, or None."""
    name = getattr(model.vertices, "filename", None)
    if not name:
        return None
    folder = Path(name).parent
    try:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        if meta.get("version") != _prep.FORMAT_VERSION or folder.name != meta.get("key"):
            return None
        return str(meta["key"])
    except Exception:
        return None


def make_key(model, geom):
    ident = prepared_identity(model)
    if ident is None:
        return None
    layout = hashlib.sha256()
    for i in range(len(model.parts)):
        layout.update(repr((int(geom.page_of[i]), [tuple(map(int, r)) for r in geom.ranges[i]])).encode())
    return hashlib.sha256(json.dumps({"prepared": ident, "v": cl.BUILD_VERSION, "tris": cl.CLUSTER_TRIS,
                                      "page_bytes": int(geom.page_bytes), "layout": layout.hexdigest(),
                                      "levels": cl.LEVEL_COUNT}, sort_keys=True).encode()).hexdigest()[:40]


def load(key):
    root = cache_root()
    if root is None or key is None:
        return None
    folder = root / key
    try:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        if meta.get("version") != cl.BUILD_VERSION or meta.get("key") != key:
            return None
        arrays = {n: np.load(folder / f"{n}.npy", mmap_mode="r") for n in _ARRAYS}
        os.utime(folder / "meta.json")
        return cl.ClusterData(stats=dict(meta["stats"], cached=True), **arrays)
    except Exception:
        return None


def save(key, cd):
    root = cache_root()
    if root is None or key is None:
        return False
    need = sum(getattr(cd, n).nbytes for n in _ARRAYS)
    if need > cap_bytes():
        return False
    final = root / key
    temp = root / f".tmp-{key[:12]}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    try:
        root.mkdir(parents=True, exist_ok=True)
        temp.mkdir()
        for n in _ARRAYS:
            np.save(temp / f"{n}.npy", np.asarray(getattr(cd, n)), allow_pickle=False)
        (temp / "meta.json").write_text(json.dumps({"version": cl.BUILD_VERSION, "key": key, "created": time.time(),
                                                    "stats": cd.stats}), encoding="utf-8")
        if final.exists():
            shutil.rmtree(final, ignore_errors=True)
        os.replace(temp, final)
        prune(root, keep=key)
        return True
    except Exception:
        return False
    finally:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)


def prune(root, keep=None, cap=None):
    cap = cap_bytes() if cap is None else cap
    entries, now = [], time.time()
    try:
        for folder in root.iterdir():
            if not folder.is_dir():
                continue
            if folder.name.startswith(".tmp-"):
                if now - folder.stat().st_mtime > 3600:
                    shutil.rmtree(folder, ignore_errors=True)
                continue
            try:
                stamp = (folder / "meta.json").stat().st_mtime
            except OSError:
                stamp = 0.0
            entries.append((stamp, folder, sum(f.stat().st_size for f in folder.glob("*") if f.is_file())))
        entries.sort(key=lambda e: e[0])
        total = sum(e[2] for e in entries)
        for _stamp, folder, size in entries:
            if total <= cap:
                break
            if keep is not None and folder.name == keep:
                continue
            shutil.rmtree(folder, ignore_errors=True)
            total -= size
    except OSError:
        pass


def get_clusters(model, geom, progress=None, use_cache=True):
    """ClusterData for the model: from the cache when present, else built (and saved when the model has an identity)."""
    key = make_key(model, geom) if use_cache else None
    cd = load(key)
    if cd is not None:
        return cd
    cd = cl.build_clusters(model, geom, progress=progress)
    cd.stats["cached"] = False
    if key is not None:
        cd.stats["saved"] = save(key, cd)
    return cd
