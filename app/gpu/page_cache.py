"""Store of GPU-ready geometry pages: what geometry.build_geometry hands to its sink, kept as plain files, so a later
open writes the files to the GPU instead of scanning, packing and reordering the model again.

* Where: ``<per-user cache folder>/gpu_pages/<key>/`` (beside ``prepared_models`` and ``clusters``, never next to the
  models). ``ANATOMY_PAGE_CACHE`` overrides the folder and ``=off`` disables the store; ``ANATOMY_PREPARED_CACHE=off``
  disables it too. ``ANATOMY_PAGE_CACHE_GB`` is the size cap (default 6); ``prune`` keeps the folder under it, least
  recently opened entries first.
* An entry: ``page<i>.npy`` (the page buffer, byte for byte what the sink received), ``tables.npz`` (the per-part
  tables of GpuGeometry, no pickle), ``tables.json`` (the page records, the statistics and the other scalars) and
  ``meta.json`` (key, versions, the request, the stage that resulted, the byte size and a digest of every file).
* Not stored: the draw-order keys (``gl_keys`` follow the parts' looks and materials, which are resolved at open time
  and are not part of any key; ``load`` computes them from the model in hand) and the cluster tables (``load`` takes
  the set from the cluster store and binds it to the stored layout with the functions build_geometry uses).
* Key: the cluster key of the model for cluster-ordered pages (cluster_cache.make_key: the prepared-model key, the
  cluster build and the model's layout), else the prepared-model key and the layout; ``PAGES_VERSION``; a hash of the
  source text of ``SHAPING_MODULES``; the page limit; the page count limit; the cluster-order flag; the compress
  request (not the stage: "auto" decides that while it builds, and meta.json records it). Limits, not a card name: any
  adapter with the same limits takes the same pages. A model without a prepared key, or an animated one, has no key.
* Quantised pages (stage 2) also depend on the error budget, which follows from the model's bounds and part matrices
  as they are when the pages are built. Those can move while a model is open, so the budget is not in the key (a
  different rounding would make every open miss): the entry records the budget and ``load`` accepts a stage-2 entry
  only when the model in hand gives exactly that budget again. ``bake`` replaces an entry whose budget no longer fits.
* Saved the way the other stores are, with prepared_cache's helpers: pages are written straight into their files
  (np.lib.format.open_memmap: no copy of a page sits in RAM), every file is flushed, meta.json goes last, then one
  rename; an entry an open accepts is never removed to be replaced; an entry is removed whole or left whole; what dead
  writers left is cleared before a save starts; nothing is written unless the volume keeps its free floor; a refused or failed key is remembered for the run.
* Anything that goes wrong reading or writing the store means "no pages" (None): the caller builds as before.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np

from app.viewer import prepared_cache as _prep

from . import cluster_cache
from . import clusters as cl
from . import geometry as geo
from . import quant as _q

PAGES_VERSION = 1
DEFAULT_CAP_GB = 6.0
# modules whose source text shapes a page (the cluster or prepared key under it carries the hashes of the rest)
SHAPING_MODULES = ("app.gpu.page_cache", "app.gpu.geometry", "app.gpu.quant", "app.gpu.clusters")
CHUNK = 16 << 20                           # bytes per sink.write when a stored page is handed over
_TABLES = ("page_of", "vbase", "vcount", "stream_base", "const_tail", "anim_base", "ranges", "range_counts")
_QUANT_ARRAYS = ("blocks", "words", "err", "budget")


class _Refused(Exception):
    """The store will not take this entry (too little disk, larger than the cap)."""


# ---------------------------------------------------------------------------------------------------- location
def cache_root():
    value = os.environ.get("ANATOMY_PAGE_CACHE", "")
    if value.lower() in ("off", "0", "false", "none"):
        return None
    if value:
        return Path(value)
    base = _prep.cache_root()
    return None if base is None else base.parent / "gpu_pages"


def cap_bytes():
    try:
        return int(float(os.environ.get("ANATOMY_PAGE_CACHE_GB", DEFAULT_CAP_GB)) * (1 << 30))
    except ValueError:
        return int(DEFAULT_CAP_GB * (1 << 30))


# ---------------------------------------------------------------------------------------------------- key
def compress_request(compress):
    """The compress argument as build_geometry reads it: 0, 1, 2 or "auto"."""
    return "auto" if isinstance(compress, str) and compress == "auto" else (min(int(compress), 2) if compress else 0)


def make_key(model, page_bytes, max_pages=None, cluster_order=False, compress=False):
    """Hex key of the pages build_geometry makes for these arguments, or None when the model has no identity."""
    try:
        if getattr(model, "anim_vertices", None) is not None:
            return None
        if cluster_order:
            base, shape = cluster_cache.make_key(model), None          # the cluster key holds the layout already
        else:
            base, shape = cluster_cache.prepared_identity(model), cluster_cache.model_shape(model)
        if base is None:
            return None
        ident = {"v": PAGES_VERSION, "code": _prep.code_id(SHAPING_MODULES), "base": base, "shape": shape,
                 "ordered": bool(cluster_order), "page_bytes": int(page_bytes),
                 "max_pages": None if max_pages is None else int(max_pages), "compress": compress_request(compress),
                 "floats": geo.VERTEX_FLOATS}
        return hashlib.sha256(json.dumps(ident, sort_keys=True).encode()).hexdigest()[:40]
    except Exception:
        return None


# ---------------------------------------------------------------------------------------------------- writing
class _FileSink:
    """A build_geometry sink whose buffers are the entry's page files, mapped for writing: what the build writes goes to
    the file through the system's file cache and no page is ever held as an array in RAM. Before a file is made the
    store's cap and the free-disk floor are asked."""

    def __init__(self, folder, root):
        self.folder, self.root = folder, root
        self.maps, self.paths, self.total = [], [], 0

    def create(self, size, label=""):
        size = max(int(size), 4)
        if self.maps:
            self.maps[-1].flush()                      # the page before is complete: its bytes count as used disk now
        if self.total + size > cap_bytes():
            raise _Refused("larger than the cache size limit")
        if not _prep.disk_allows(self.root, size):
            raise _Refused("too little free disk space")
        path = self.folder / f"{label or 'page' + str(len(self.paths))}.npy"
        handle = np.lib.format.open_memmap(path, mode="w+", dtype=np.uint8, shape=(size,))
        self.maps.append(handle)
        self.paths.append(path)
        self.total += size
        return handle

    def write(self, handle, offset, arr):
        raw = np.ascontiguousarray(arr).view(np.uint8).reshape(-1)
        handle[offset:offset + raw.size] = raw

    def read(self, handle, offset=0, size=None):
        end = handle.size if size is None else offset + size
        return np.array(handle[offset:end])

    def finish(self):
        pass

    def destroy(self, handle):
        pass

    def unmap(self):
        """Flush and let go of every mapping (a mapped file can be neither renamed with its folder nor deleted). The
        files close when the last reference to a mapping goes, so the caller must hold none (Page.buffer)."""
        for handle in self.maps:
            try:
                handle.flush()
            except Exception:
                pass
        self.maps = []

    def sync(self):
        """Every page file on the disk before the call returns."""
        for path in self.paths:
            with open(path, "r+b") as fh:
                os.fsync(fh.fileno())


def _plain(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"{type(value).__name__} is not stored as JSON")


def _write_file(path, write):
    with open(path, "wb") as fh:
        write(fh)
        fh.flush()
        os.fsync(fh.fileno())


def _tables(geom, model):
    """(scalars for tables.json, arrays for tables.npz) of a built geometry; neither holds gl_keys or cluster tables."""
    pages = [{"index": int(p.index), "v0": int(p.v0), "v1": int(p.v1), "parts": [int(i) for i in p.parts],
              "offs": {k: int(v) for k, v in p.offs.items()}, "counts": {k: int(v) for k, v in p.counts.items()},
              "words": int(p.words), "nlogical": int(p.nlogical), "nwide": int(p.nwide)} for p in geom.pages]
    scalars = {"pages": pages, "stats": geom.stats, "page_bytes": int(geom.page_bytes), "compressed": bool(geom.compressed),
               "stage": int(geom.stage), "ordered": geom.clusters is not None, "parts": len(model.parts),
               "vertices": int(len(model.vertices)), "indices": int(len(model.indices)), "quant": None}
    flat = [(int(first), int(count)) for levels in geom.ranges for first, count in levels]
    arrays = {"page_of": np.asarray(geom.page_of), "vbase": np.asarray(geom.vbase), "vcount": np.asarray(geom.vcount),
              "stream_base": np.asarray(geom.stream_base), "const_tail": np.asarray(geom.const_tail),
              "anim_base": np.asarray(geom.anim_base), "ranges": np.array(flat, dtype=np.int64).reshape(-1, 2),
              "range_counts": np.array([len(levels) for levels in geom.ranges], dtype=np.int64)}
    if geom.quant is not None:
        scalars["quant"] = {k: v for k, v in geom.quant.items() if k not in _QUANT_ARRAYS}
        for name in _QUANT_ARRAYS:
            arrays["quant_" + name] = np.asarray(geom.quant[name])
    return scalars, arrays


def bake(model, page_bytes, max_pages=None, cluster_order=False, compress=False, progress=None, cluster_progress=None,
         cluster_cache_use=True, key=None):
    """Build the model's pages for these build_geometry arguments straight into the store. Returns the entry's meta.json
    (plus ``"fresh"``: True when this call wrote the entry, False when a good one was there already), or None when the
    store holds no entry afterwards: no key, the store is off, the entry was refused or the build failed. The reason is
    then remembered and the same key is not tried again in this run. Raises only what a progress callback raises (a
    cancelled load), which is not remembered."""
    root = cache_root()
    if root is None:
        return None
    if key is None:
        key = make_key(model, page_bytes, max_pages, cluster_order, compress)
    if key is None or _prep.refused(root, key):
        return None
    passed = []

    def passing(callback):
        if callback is None:
            return None

        def call(*args):
            try:
                return callback(*args)
            except BaseException as exc:
                passed.append(exc)
                raise
        return call

    final = root / key
    if final.exists():
        found = _open(final, key, model)
        if found is not None:
            return dict(found[0], fresh=False)
    try:
        root.mkdir(parents=True, exist_ok=True)
        _prep.clear_leftovers(root)         # what dead writers left must not be what makes the floor refuse this save
        claim = _prep.TempFolder(root, key)
    except OSError as exc:
        _prep.refuse(root, key, f"{type(exc).__name__}: {exc}")
        return None
    temp = claim.path
    sink = _FileSink(temp, root)
    outcome = _write(key, model, root, temp, final, sink, passed,
                     dict(progress=passing(progress), max_pages=max_pages, cluster_order=cluster_order,
                          cluster_progress=passing(cluster_progress), cluster_cache_use=cluster_cache_use,
                          compress=compress), page_bytes)
    # _write has returned, so nothing of the build is alive any more (no frame holds a mapped page): the folder can go
    sink.unmap()
    claim.release()
    if isinstance(outcome, BaseException):
        raise outcome
    if isinstance(outcome, str):
        _prep.refuse(root, key, outcome)
        return None
    return outcome


def _write(key, model, root, temp, final, sink, passed, build, page_bytes):
    """The meta of the entry this call put in place, else the reason (text) the store holds none, else the exception a
    progress callback raised (without its traceback, whose frames would keep the page files mapped). Never raises."""
    started = time.perf_counter()

    def valid(folder):
        return _open(folder, key, model) is not None

    try:
        temp.mkdir()
        geom = geo.build_geometry(model, sink, page_bytes, **build)
        scalars, arrays = _tables(geom, model)
        for page in geom.pages:
            page.buffer = None
        sink.unmap()
        sink.sync()
        _write_file(temp / "tables.npz", lambda fh: np.savez(fh, **arrays))
        _write_file(temp / "tables.json", lambda fh: fh.write(json.dumps(scalars, default=_plain).encode("utf-8")))
        meta = {"version": PAGES_VERSION, "key": key, "code": _prep.code_id(SHAPING_MODULES), "created": time.time(),
                "prepared": cluster_cache.prepared_identity(model),
                "clusters": cluster_cache.make_key(model) if build["cluster_order"] else None,
                "page_bytes": int(page_bytes), "max_pages": None if build["max_pages"] is None else int(build["max_pages"]),
                "ordered": bool(build["cluster_order"]), "compress": compress_request(build["compress"]),
                "stage": int(geom.stage), "pages": len(geom.pages), "bytes": int(sink.total),
                "seconds": round(time.perf_counter() - started, 3)}
        _prep.write_meta(temp, meta)
        if not _prep.commit(temp, final, valid):
            return "the entry could not be put in place"
        if temp.exists():                   # another writer's good entry was there first: it stays, this one is dropped
            found = _open(final, key, model)
            return "the entry could not be read back" if found is None else dict(found[0], fresh=False)
        prune(root, keep=key)
        return dict(meta, fresh=True)
    except _Refused as exc:
        return str(exc)
    except Exception as exc:
        if passed and exc is passed[-1]:
            passed.clear()
            return exc.with_traceback(None)
        return f"{type(exc).__name__}: {exc}"


def prune(root, keep=None, cap=None):
    """Remove least recently opened entries until the folder fits the cap (prepared_cache.prune_store)."""
    _prep.prune_store(root, cap_bytes() if cap is None else cap, keep)


# ---------------------------------------------------------------------------------------------------- reading
def _geo_ids(model):
    return [i for i, p in enumerate(model.parts) if p.vertex_count > 0 or p.count > 0]


def _budget_fits(model, quant, budget):
    """True when the model in hand gives the stage-2 error budget the stored pages were quantised with, bit for bit."""
    ids = _geo_ids(model)
    now, (wpp, dmin) = _q.budget_part_space(model, ids)
    want = np.zeros(len(model.parts), dtype=np.float64)
    for i in ids:
        want[i] = now[i]
    return (_q.qerr_pixels() == quant["pixels"] and wpp == quant["world_per_pixel"] and dmin == quant["min_distance"]
            and budget.dtype == np.float64 and np.array_equal(want, budget))


def _open(folder, key, model):
    """(meta, scalars, arrays, [every page file memory mapped]) of the entry in ``folder`` when it is whole and fits the
    model in hand, else None. meta.json must name this key and version and list every file with the byte size and digest it has
    on disk; the tables must have the model's part count and array sizes; every page file must hold the bytes its record
    says; a stage-2 entry must have been quantised with the budget the model gives now."""
    try:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        if meta.get("version") != PAGES_VERSION or meta.get("key") != key:
            return None
        count = int(meta["pages"])
        if not _prep.files_match(folder, meta, ["tables.json", "tables.npz"] + [f"page{i}.npy" for i in range(count)]):
            return None
        t = json.loads((folder / "tables.json").read_text(encoding="utf-8"))
        with np.load(folder / "tables.npz", allow_pickle=False) as z:
            a = {name: z[name] for name in z.files}
        n = len(model.parts)
        if (t["parts"] != n or t["vertices"] != len(model.vertices) or t["indices"] != len(model.indices)
                or len(t["pages"]) != count or any(name not in a for name in _TABLES)):
            return None
        shapes = {"page_of": ((n,), np.int32), "vbase": ((n,), np.int64), "vcount": ((n,), np.int64),
                  "stream_base": ((n, len(geo.VARIABLE)), np.int64), "anim_base": ((n,), np.int64),
                  "const_tail": ((n, geo.VERTEX_FLOATS - 6), np.float32), "range_counts": ((n,), np.int64),
                  "ranges": ((int(a["range_counts"].sum()), 2), np.int64)}
        if any(a[name].shape != shape or a[name].dtype != dtype for name, (shape, dtype) in shapes.items()):
            return None
        if int(t["stage"]) >= 2:
            if any("quant_" + name not in a for name in _QUANT_ARRAYS) or not _budget_fits(model, t["quant"], a["quant_budget"]):
                return None
        maps = []
        for i, record in enumerate(t["pages"]):
            if int(record["index"]) != i:
                return None
            data = np.load(folder / f"page{i}.npy", mmap_mode="r", allow_pickle=False)
            if data.dtype != np.uint8 or data.shape != (int(record["words"]) * 4,):
                return None
            maps.append(data)
        return meta, t, a, maps
    except Exception:
        return None


def load(model, sink, page_bytes, max_pages=None, cluster_order=False, compress=False, progress=None,
         cluster_progress=None, cluster_cache_use=True, key=None):
    """The GpuGeometry build_geometry would return for these arguments, with every page written to ``sink`` from the
    store, or None when the store has no entry that is whole and fits the model (the caller then builds).

    A cluster-ordered entry needs the model's cluster set, taken as build_geometry takes it (riding on the model, from
    the cluster store, or built); what that step raises (ClusterError, a cancel from ``cluster_progress``) is raised
    here too, as is what ``progress`` raises. Nothing else is raised."""
    root = cache_root()
    if root is None:
        return None
    if key is None:
        key = make_key(model, page_bytes, max_pages, cluster_order, compress)
    if key is None:
        return None
    folder = root / key
    found = _open(folder, key, model)
    if found is None:
        return None
    meta, t, a, maps = found
    clusters0 = None
    if t["ordered"]:
        clusters0 = cluster_cache.get_clusters(model, None, progress=cluster_progress, use_cache=cluster_cache_use)
    try:
        ends = np.cumsum(a["range_counts"])
        flat = a["ranges"].tolist()
        ranges = [[(first, count) for first, count in flat[end - k:end]]
                  for end, k in zip(ends.tolist(), a["range_counts"].tolist())]
        quant = None
        if t["quant"] is not None:
            quant = dict(t["quant"], **{name: a["quant_" + name] for name in _QUANT_ARRAYS})
        clusters = order = None
        if clusters0 is not None:
            clusters = cl.bind_layout(clusters0, a["page_of"], ranges)
            if quant is not None:
                clusters = geo._inflate_bounds(clusters, quant["err"])
            order = geo.TriangleOrder(clusters)
        base, lods = geo.gl_order_keys(model)                       # draw order: from the looks the model has now
        gl_keys = [[base[p.id]] + list(lods.get(p.id, [])) for p in model.parts]
    except Exception:
        return None
    pages, passed = [], []
    try:
        for record, data in zip(t["pages"], maps):
            page = geo.Page(index=int(record["index"]), v0=int(record["v0"]), v1=int(record["v1"]),
                            parts=[int(i) for i in record["parts"]], offs=dict(record["offs"]),
                            counts=dict(record["counts"]), words=int(record["words"]),
                            nlogical=int(record["nlogical"]), nwide=int(record["nwide"]))
            page.buffer = sink.create(page.words * 4, f"page{page.index}")
            pages.append(page)
            for at in range(0, len(data), CHUNK):
                sink.write(page.buffer, at, data[at:at + CHUNK])
            if progress:
                try:
                    progress(len(pages), len(maps))
                except BaseException as exc:
                    passed.append(exc)
                    raise
        sink.finish()
    except Exception as exc:
        for page in pages:
            try:
                sink.destroy(page.buffer)
            except Exception:
                pass
        if passed and exc is passed[-1]:
            raise
        return None
    try:
        os.utime(folder / "meta.json")                                # read now: the last to be pruned
    except OSError:
        pass
    return geo.GpuGeometry(sink=sink, pages=pages, page_of=a["page_of"], vbase=a["vbase"], vcount=a["vcount"],
                           ranges=ranges, stream_base=a["stream_base"], const_tail=a["const_tail"], gl_keys=gl_keys,
                           stats=t["stats"], page_bytes=page_bytes, anim_base=a["anim_base"], clusters=clusters,
                           order=order, compressed=bool(t["compressed"]), stage=int(t["stage"]), quant=quant)
