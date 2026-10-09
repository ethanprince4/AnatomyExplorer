"""Prepared-model cache: the CPU arrays a library model needs after decode, build and lod.build, kept uncompressed.

Opening a big library model spends seconds inflating the .npz members, undoing the index delta coding, packing the
(V, 19) vertex array and clustering the coarser LOD levels. None of that changes between two opens of the same file, so
the result is stored once as plain .npy files and memory-mapped on the next open.

* Where: ``<per-user cache folder>/prepared_models/<key>/`` (never next to the models, never under data/).
  ``ANATOMY_PREPARED_CACHE`` overrides the folder, ``ANATOMY_PREPARED_CACHE_GB`` the size cap (default 8), and
  ``ANATOMY_PREPARED_CACHE=off`` switches the cache off.
* Key: source path + size + mtime + companion files + retired groups + the LOD constants + ``FORMAT_VERSION``.
  Bump ``FORMAT_VERSION`` whenever what is stored (or how the build derives it) changes.
* A save writes a temporary folder next to the final one and renames it; a half-written entry is never read.
* Anything that goes wrong (missing files, wrong shapes, a full disk, a locked file) means "no cache": the caller
  runs the normal path. Nothing here ever raises into the loader.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import numpy as np

FORMAT_VERSION = 1
DEFAULT_CAP_GB = 8.0
_STALE_TEMP_SECONDS = 3600


class PreparedMismatch(Exception):
    """The cached arrays do not fit the model being built; the caller must rebuild normally."""


# ---------------------------------------------------------------------------------------------------- location
def cache_root():
    value = os.environ.get("ANATOMY_PREPARED_CACHE", "")
    if value.lower() in ("off", "0", "false", "none"):
        return None
    if value:
        return Path(value)
    try:
        from ..config import _user_base
        return Path(_user_base()) / "cache" / "prepared_models"
    except Exception:
        return None


def cap_bytes():
    try:
        return int(float(os.environ.get("ANATOMY_PREPARED_CACHE_GB", DEFAULT_CAP_GB)) * (1 << 30))
    except ValueError:
        return int(DEFAULT_CAP_GB * (1 << 30))


def _stat(path):
    try:
        st = os.stat(path)
        return [int(st.st_size), int(st.st_mtime_ns)]
    except OSError:
        return [-1, -1]


def make_key(path, companions=(), retired=()):
    """Hex key of a source file and everything else the prepared arrays depend on, or None."""
    try:
        from . import lod, model as viewer_model
        ident = {
            "v": FORMAT_VERSION,
            "path": os.path.normcase(os.path.abspath(path)),
            "stat": _stat(path),
            "companions": sorted([role, os.path.normcase(os.path.abspath(p)), *_stat(p)] for role, p in companions),
            "retired": sorted(str(r) for r in retired),
            "lod": [lod.LEVELS, lod.MIN_TRIANGLES, lod.MIN_KEEP, lod.MIN_GAIN, lod._BITS, lod.REFERENCE_PIXELS],
            "layout": [viewer_model.VERTEX_FLOATS],
        }
        return hashlib.sha256(json.dumps(ident, sort_keys=True).encode()).hexdigest()[:40]
    except Exception:
        return None


# ---------------------------------------------------------------------------------------------------- stub meshes
class StubMesh:
    """Stands in for ``micro.geometry.Mesh`` when the real arrays are not needed: right shapes, no memory."""

    def __init__(self, vertex_count, triangle_count):
        zero_f, zero_i = np.zeros((), np.float32), np.zeros((), np.int64)
        self._arrays = (np.broadcast_to(zero_f, (vertex_count, 3)), np.broadcast_to(zero_f, (vertex_count, 3)),
                        np.broadcast_to(zero_i, (triangle_count, 3)))
        self.parts = []

    def arrays(self):
        return self._arrays


def stub_rows(metadata, manifest):
    """Decoded rows like ``decode_local_npz`` makes, but with zero-memory arrays of the recorded sizes."""
    from copy import deepcopy
    entries = metadata["parts"]
    if len(entries) != len(manifest):
        raise PreparedMismatch("part count changed")
    rows = []
    for i, (original, (nv, nf, coloured)) in enumerate(zip(entries, manifest)):
        row = deepcopy(original)
        row.setdefault("name", f"Part {i + 1}")
        zero = np.zeros((), np.float32)
        verts = np.broadcast_to(zero, (nv, 3))
        faces = np.broadcast_to(np.zeros((), np.int64), (nf, 3))
        colors = np.broadcast_to(zero, (nv, 3)) if coloured else None
        rows.append((row, verts, verts, faces, colors))
    return rows


# ---------------------------------------------------------------------------------------------------- loading
class Prepared:
    """One cache entry, opened: memory-mapped arrays plus the small metadata of the parts and LOD levels."""

    def __init__(self, folder, meta):
        self.folder = folder
        self.meta = meta
        self.manifest = [tuple(m) for m in meta["decode"]]
        self.decode_warnings = list(meta["warnings"])
        self.part_meta = meta["parts"]
        self.vertices = np.load(folder / "vertices.npy", mmap_mode="c")
        self.indices = np.load(folder / "indices.npy", mmap_mode="c")
        if self.vertices.shape != (meta["vertices"], meta["floats"]) or self.vertices.dtype != np.float32:
            raise PreparedMismatch("vertex array shape")
        if self.indices.shape != (meta["indices"],) or self.indices.dtype != np.uint32:
            raise PreparedMismatch("index array shape")
        self.bounds = (np.array(meta["bounds_min"], dtype=np.float64), np.array(meta["bounds_max"], dtype=np.float64))
        self.lod = self._load_lod(folder, meta)

    @staticmethod
    def _load_lod(folder, meta):
        from .lod import PartLod
        if not meta["lod"]:
            return {}
        flat = np.load(folder / "lod.npy", mmap_mode="r")
        if flat.shape != (meta["lod_total"],) or flat.dtype != np.uint32:
            raise PreparedMismatch("lod array shape")
        out = {}
        for entry in meta["lod"]:
            views, levels = [], []
            for offset, length, same_as in entry["levels"]:
                view = views[same_as] if same_as >= 0 else flat[offset:offset + length]
                views.append(view)
                levels.append(view)
            out[int(entry["id"])] = PartLod(np.array(entry["cells"], dtype=np.float64), levels)
        return out

    def part_geometry(self, k, name, vertex_count, index_count):
        """Recorded draw range and bounds of the k-th part added; checked against what the builder is adding."""
        if k >= len(self.part_meta):
            raise PreparedMismatch("more parts than recorded")
        m = self.part_meta[k]
        if m["name"] != name or m["n"] != vertex_count or m["count"] != index_count:
            raise PreparedMismatch(f"part {k} differs")
        return m


def lookup(key):
    """The opened entry for ``key`` or None. Touches the entry so the size cap drops the least recently used first."""
    root = cache_root()
    if root is None or not key:
        return None
    folder = root / key
    try:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        if meta.get("version") != FORMAT_VERSION or meta.get("key") != key:
            return None
        prepared = Prepared(folder, meta)
        try:
            os.utime(folder / "meta.json")
        except OSError:
            pass
        return prepared
    except Exception:
        return None


# builders ask the active entry (thread-local: loads run on worker threads) for the arrays
_local = threading.local()


@contextmanager
def using(prepared):
    previous = getattr(_local, "active", None)
    _local.active = prepared
    try:
        yield prepared
    finally:
        _local.active = previous


def active():
    return getattr(_local, "active", None)


# ---------------------------------------------------------------------------------------------------- saving
_inflight = set()
_inflight_lock = threading.Lock()
_threads = []


def eligible(model):
    """Static, array-backed library models only (animated models keep their per-part source arrays)."""
    try:
        return (getattr(model, "_prepared_plan", None) is not None and model.vertices is not None
                and model.anim_vertices is None and getattr(model, "animation", None) is None
                and model.lod is not None and model.vertices.ndim == 2 and model.vertices.dtype == np.float32
                and model.indices.dtype == np.uint32 and model.indices.ndim == 1
                and len(model._geom_log) == len(model.parts))
    except Exception:
        return False


def _part_entries(model):
    out = []
    for p, (first, count, base, n, lo, hi, centre, radius) in zip(model.parts, model._geom_log):
        out.append({"name": p.name, "id": int(p.id), "first": int(first), "count": int(count), "base": int(base),
                    "n": int(n), "min": [float(x) for x in lo], "max": [float(x) for x in hi],
                    "centre": [float(x) for x in centre], "radius": float(radius)})
    return out


def _lod_entries(model):
    flat, entries, offset = [], [], 0
    for pid, part_lod in model.lod.items():
        seen, levels = {}, []
        for level in part_lod.indices:
            level = np.asarray(level)
            if level.dtype != np.uint32 or level.ndim != 1:
                raise ValueError("unexpected LOD level layout")
            same = seen.get(id(level), -1)
            if same >= 0:
                levels.append([0, 0, same])
                continue
            seen[id(level)] = len(levels)
            levels.append([offset, int(level.size), -1])
            flat.append(level)
            offset += int(level.size)
        entries.append({"id": int(pid), "cells": [float(c) for c in part_lod.cells], "levels": levels})
    return flat, entries, offset


def _folder_bytes(folder):
    total = 0
    try:
        for f in folder.iterdir():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return total


def prune(root, keep=None, cap=None):
    """Delete least recently used entries until the folder fits the cap; clear abandoned temporary folders."""
    cap = cap_bytes() if cap is None else cap
    entries, now = [], time.time()
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        if folder.name.startswith(".tmp-"):
            try:
                if now - folder.stat().st_mtime > _STALE_TEMP_SECONDS:
                    shutil.rmtree(folder, ignore_errors=True)
            except OSError:
                pass
            continue
        try:
            stamp = (folder / "meta.json").stat().st_mtime
        except OSError:
            stamp = 0.0           # no meta: a broken entry, first to go
        entries.append((stamp, folder, _folder_bytes(folder)))
    entries.sort(key=lambda e: e[0])
    total = sum(e[2] for e in entries)
    for stamp, folder, size in entries:
        if total <= cap:
            break
        if keep is not None and folder.name == keep:
            continue
        shutil.rmtree(folder, ignore_errors=True)
        if not folder.exists():
            total -= size


def _save(model, plan):
    root = cache_root()
    key = plan["key"]
    if root is None:
        return False
    bytes_needed = int(model.vertices.nbytes + model.indices.nbytes)
    flat, lod_entries, lod_total = _lod_entries(model)
    bytes_needed += 4 * lod_total
    if bytes_needed > cap_bytes():
        return False
    root.mkdir(parents=True, exist_ok=True)
    final = root / key
    temp = root / f".tmp-{key[:12]}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    try:
        temp.mkdir()
        np.save(temp / "vertices.npy", model.vertices, allow_pickle=False)
        np.save(temp / "indices.npy", model.indices, allow_pickle=False)
        if flat:
            np.save(temp / "lod.npy", np.concatenate(flat) if len(flat) > 1 else flat[0], allow_pickle=False)
        meta = {"version": FORMAT_VERSION, "key": key, "created": time.time(), "source": plan["source"],
                "vertices": int(model.vertices.shape[0]), "floats": int(model.vertices.shape[1]),
                "indices": int(model.indices.size), "decode": [list(m) for m in plan["decode"]],
                "warnings": plan["warnings"], "parts": _part_entries(model),
                "bounds_min": [float(x) for x in model._finish_bounds[0]],
                "bounds_max": [float(x) for x in model._finish_bounds[1]],
                "lod": lod_entries, "lod_total": int(lod_total)}
        (temp / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        if final.exists():              # only reached when the entry could not be read: replace it
            shutil.rmtree(final, ignore_errors=True)
        os.replace(temp, final)
        prune(root, keep=key)
        return True
    finally:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)


def save_async(model):
    """Store a freshly prepared model's arrays in the background. Silent on any failure."""
    try:
        if not eligible(model) or cache_root() is None:
            return
        plan = model._prepared_plan
        with _inflight_lock:
            if plan["key"] in _inflight:
                return
            _inflight.add(plan["key"])

        def run():
            try:
                _save(model, plan)
            except Exception:
                pass
            finally:
                with _inflight_lock:
                    _inflight.discard(plan["key"])

        thread = threading.Thread(target=run, name="prepared-cache-save", daemon=True)
        _threads.append(thread)
        thread.start()
    except Exception:
        pass


def wait_for_saves(timeout=600.0):
    """Block until background saves finish (tests, benchmarks, and a clean shutdown)."""
    deadline = time.time() + timeout
    for thread in list(_threads):
        thread.join(max(0.0, deadline - time.time()))
    _threads[:] = [t for t in _threads if t.is_alive()]
