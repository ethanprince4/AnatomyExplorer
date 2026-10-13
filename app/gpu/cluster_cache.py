"""Cache of the cluster build (app/gpu/clusters.py), beside the prepared-model cache, never next to the models.

* Where: ``<per-user cache folder>/clusters/<key>/`` (the prepared cache is ``.../cache/prepared_models``; its own
  prune() never sees this folder). ``ANATOMY_CLUSTER_CACHE`` overrides the folder and ``=off`` disables the cache;
  ``ANATOMY_PREPARED_CACHE=off`` disables it too. ``ANATOMY_CLUSTER_CACHE_GB`` is the size cap (default 4).
* Identity: a cluster set depends on every vertex position and index of the model, so the key is derived from the
  model's prepared-model key (it already covers what the source file holds, the LOD constants, the prepared
  FORMAT_VERSION and the code that shapes the arrays), plus the clusters' BUILD_VERSION, a hash of the source text of
  ``SHAPING_MODULES`` (no version bump to remember), the cluster size and a hash of the model's layout
  (``model_shape``). The same file decodes to the same arrays every time (tests/test_cluster_identity.py), so a
  model has that key on its first open already, when its arrays are still in RAM (local_runtime sets
  ``model._prepared_key``): the first open saves the clusters and the second finds them. The cluster set does not
  depend on the geometry layout (page size, page of a part, compressed or not). A model with no prepared key (a
  .glb, a component, an open with the cache switched off) has no stable identity: it is built every time and not
  saved (no stale-bounds risk).
* Same write protocol as prepared_cache, with its helpers: every file flushed, meta.json (with the byte size and
  a digest of every file, checked on open) last, one rename; a good entry is never removed to be replaced; an entry
  is removed whole or left whole; what dead writers left is cleared before the free-disk floor is asked; no save
  under that floor; a refused or failed key is remembered for the run. Anything
  that goes wrong means "no cache" and the caller builds. Nothing here raises into the renderer.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np

from app.viewer import prepared_cache as _prep

from . import clusters as cl

DEFAULT_CAP_GB = 4.0
# modules whose source text shapes a cluster set (the prepared key under it carries the hash of the model's own)
SHAPING_MODULES = ("app.gpu.cluster_cache", "app.gpu.clusters")
# the page layout (r_page, r_first, page_cfirst) is NOT cached: the cluster set is independent of it (clusters.bind_layout)
_ARRAYS = ("r_part", "r_ntri", "r_cfirst", "r_tfirst", "r_ccount", "level_range", "uncullable",
           "cl_geom", "cl_range", "perm", "vorder", "cl_base", "r_level", "r_slot")


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
    """The prepared-model key of the model's arrays, or None.

    A library file opened by local_runtime carries it as ``model._prepared_key`` from its first open on, when the
    arrays were decoded into RAM a moment ago, and on every later open, when they are mapped from the entry of that
    key. Any other model with mapped arrays is identified by the entry it is mapped from."""
    key = getattr(model, "_prepared_key", None)
    if key:
        return str(key)
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


def model_shape(model):
    """Short hash of what the tables of a cluster set are laid out on: the array sizes, the draw range of every part
    and the sizes and sharing of its detail levels. The prepared key says which numbers the arrays hold; this says the
    model in hand has the layout those clusters index (a model whose detail levels are not built yet, or one that lost
    or gained a part after it was opened, gets another key instead of a set that does not fit it)."""
    digest = hashlib.sha256()
    digest.update(f"{len(model.vertices)} {len(model.indices)} {len(model.parts)}\n".encode())
    for part in model.parts:
        levels, order = cl.part_levels(model, part)
        digest.update(f"{int(part.first)} {int(part.count)} {int(part.vertex_base)} {int(part.vertex_count)} "
                      f"{[int(len(a)) for a in levels]} {[int(k) for k in order]}\n".encode())
    return digest.hexdigest()[:16]


def make_key(model, geom=None):
    ident = prepared_identity(model)
    if ident is None:
        return None
    animated = getattr(model, "anim_vertices", None) is not None
    try:
        code = _prep.code_id(SHAPING_MODULES)
        shape = model_shape(model)
    except Exception:
        return None
    return hashlib.sha256(json.dumps({"prepared": ident, "v": cl.BUILD_VERSION, "code": code, "tris": cl.CLUSTER_TRIS,
                                      "levels": cl.LEVEL_COUNT, "animated": animated, "shape": shape},
                                     sort_keys=True).encode()).hexdigest()[:40]


def _read_entry(folder, key):
    """(meta, memory-mapped arrays) of the entry in ``folder``, or None: its meta.json must name this key and version
    and list every array file with the byte size and digest it has on disk. An entry written before those were recorded is
    not accepted."""
    try:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        if meta.get("version") != cl.BUILD_VERSION or meta.get("key") != key:
            return None
        if not _prep.files_match(folder, meta, [f"{n}.npy" for n in _ARRAYS]):
            return None
        return meta, {n: np.load(folder / f"{n}.npy", mmap_mode="r") for n in _ARRAYS}
    except Exception:
        return None


def load(key):
    root = cache_root()
    if root is None or key is None:
        return None
    folder = root / key
    try:
        found = _read_entry(folder, key)
        if found is None:
            return None
        meta, arrays = found
        R = len(arrays["r_part"])
        os.utime(folder / "meta.json")
        return cl.ClusterData(stats=dict(meta["stats"], cached=True), r_page=np.zeros(R, np.int32), r_first=np.zeros(R, np.int64),
                              page_cfirst=np.zeros(1, np.int64), **arrays)
    except Exception:
        return None


def save(key, cd):
    """Write the entry of ``key`` the safe way (prepared_cache: flushed files, meta.json last, one rename, a good entry
    never replaced, the free-disk floor). A save that is refused or fails is remembered for this run and not tried again."""
    root = cache_root()
    if root is None or key is None or _prep.refused(root, key):
        return False
    try:
        why = _write(key, cd, root)
    except Exception as exc:
        why = f"{type(exc).__name__}: {exc}"
    if why:
        _prep.refuse(root, key, why)
    return not why


def _write(key, cd, root):
    """None when the store holds a good entry for ``key`` afterwards, else the reason it does not."""
    final = root / key

    def valid(folder):
        return _read_entry(folder, key) is not None

    if final.exists() and valid(final):
        return None                     # another writer finished first: its entry stays
    _prep.clear_leftovers(root)         # what dead writers left must not be what makes the floor refuse this save
    need = sum(getattr(cd, n).nbytes for n in _ARRAYS)
    if need > cap_bytes():
        return "larger than the cache size limit"
    if not _prep.disk_allows(root, need):
        return "too little free disk space"
    root.mkdir(parents=True, exist_ok=True)
    claim = _prep.TempFolder(root, key)
    temp = claim.path
    try:
        temp.mkdir()
        for n in _ARRAYS:
            _prep.write_array(temp / f"{n}.npy", np.asarray(getattr(cd, n)))
        _prep.write_meta(temp, {"version": cl.BUILD_VERSION, "key": key, "code": _prep.code_id(SHAPING_MODULES),
                                "created": time.time(), "stats": cd.stats})
        if not _prep.commit(temp, final, valid):
            return "the entry could not be put in place"
        prune(root, keep=key)
        return None
    finally:
        claim.release()


def prune(root, keep=None, cap=None):
    """Remove least recently opened entries until the folder fits the cap (prepared_cache.prune_store)."""
    _prep.prune_store(root, cap_bytes() if cap is None else cap, keep)


def carry(model, cd):
    """Let the cluster set ``cd`` ride on ``model`` (``model._clusters0``), with the layout it was made for: _get hands
    it out before it looks anywhere else. The load thread does this (app/gpu/prep.py), so the renderer's request on the
    GUI thread costs nothing, also for a model whose set cannot be kept on disk. False when the model takes no attribute."""
    try:
        model._clusters0_shape = model_shape(model)
        model._clusters0, model._clusters0_error = cd, None
        return True
    except Exception:
        return False


def carry_failure(model, error):
    """Remember on the model that its cluster build failed (a ClusterError), so the same build is not run again only to
    fail again: _get raises it anew while the model keeps this layout."""
    try:
        model._clusters0_shape = model_shape(model)
        model._clusters0, model._clusters0_error = None, str(error)
        return True
    except Exception:
        return False


def carried(model):
    """The set riding on the model, or None. A set made for another layout (a detail level or a part changed since) is
    not handed out. Raises ClusterError when what rides is the failure of the build for this layout."""
    cd, error = getattr(model, "_clusters0", None), getattr(model, "_clusters0_error", None)
    if cd is None and not error:
        return None
    try:
        same = getattr(model, "_clusters0_shape", None) == model_shape(model)
    except Exception:
        same = False
    if not same:
        return None
    if cd is None:
        raise cl.ClusterError(error)
    return cd


def get_clusters(model, geom=None, progress=None, use_cache=True):
    """ClusterData for the model: the set riding on it when there is one (carry), else from the cache when present, else
    built (and saved when the model has an identity; the returned arrays are then the memory-mapped files, not the
    builder's RAM copies). With ``geom`` (page_of and ranges are read) the layout dependent tables are bound
    (clusters.bind_layout); without, the page-independent set is returned."""
    cd = _get(model, progress, use_cache)
    return cl.bind_layout(cd, geom.page_of, geom.ranges) if geom is not None else cd


def _get(model, progress, use_cache):
    cd = carried(model)
    if cd is not None:
        return cd
    key = make_key(model) if use_cache else None
    cd = load(key)
    if cd is not None:
        return cd
    cd = cl.build_clusters(model, None, progress=progress)
    cd.stats["cached"] = False
    if key is not None:
        cd.stats["saved"] = save(key, cd)
        if cd.stats["saved"]:
            # re-open the saved arrays memory mapped: the builder's RAM copies (perm is 4 B per triangle) are dropped
            mapped = load(key)
            if mapped is not None:
                mapped.stats = dict(cd.stats)
                return mapped
    return cd
