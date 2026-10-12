"""Prepared-model cache: the CPU arrays a library model needs after decode, build and lod.build, kept uncompressed.

Opening a big library model spends seconds inflating the .npz members, undoing the index delta coding, packing the
(V, 19) vertex array and clustering the coarser LOD levels. None of that changes between two opens of the same file, so
the result is stored once as plain .npy files and memory-mapped on the next open.

* Where: ``<per-user cache folder>/prepared_models/<key>/`` (never next to the models, never under data/).
  ``ANATOMY_PREPARED_CACHE`` overrides the folder, ``ANATOMY_PREPARED_CACHE_GB`` the size cap (default 8), and
  ``ANATOMY_PREPARED_CACHE=off`` switches the cache off.
* Key: what the source file holds (its size and a digest of its zip directory: name, CRC-32 and size of every
  member; never its path or modified time, so a copied or moved file finds the same entry) + its companion files
  (``.npz`` the same way, the others by a hash of their bytes) + who opens it + retired groups + the LOD constants +
  ``FORMAT_VERSION`` + a hash of the source text of the modules that shape the arrays (``SHAPING_MODULES``), so an
  edit to one of them gives new entries without anyone remembering to bump the version.
* A save writes a temporary folder next to the final one: every array flushed to disk, then ``meta.json`` (which
  lists the byte size of every file) flushed last, then one rename. An open checks those sizes. An entry an open
  accepts is never removed to be replaced: the later writer drops its own temporary folder. Whatever is removed
  loses ``meta.json`` first, so a half-removed entry can never be opened.
* No save unless it leaves free the larger of ``MIN_FREE_BYTES`` and ``MIN_FREE_FRACTION`` of the volume. A key
  whose save was refused or failed is remembered until the program closes and not tried again on every open.
* Anything that goes wrong (missing files, wrong sizes or shapes, a full disk, a locked file) means "no cache": the
  caller runs the normal path. Nothing here ever raises into the loader.

The helpers of the "identity" and "safe saving" sections are shared with the other stores (app/gpu/cluster_cache.py).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import marshal
import os
import shutil
import threading
import time
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

import numpy as np

FORMAT_VERSION = 2
DEFAULT_CAP_GB = 8.0
MIN_FREE_BYTES = 10 << 30          # a save must leave free at least this much ...
MIN_FREE_FRACTION = 0.10           # ... and at least this share of the volume
HASH_LIMIT_BYTES = 64 << 20        # a companion that is not a zip is hashed whole up to this size
_STALE_TEMP_SECONDS = 3600
# Modules whose source text shapes the stored arrays: the store itself, the decode and normals, the mesh arrays and
# base colours, the vertex layout and packing, the detail levels.
SHAPING_MODULES = ("app.viewer.prepared_cache", "app.variants.local_runtime", "app.micro.geometry", "app.micro.base",
                   "app.viewer.model", "app.viewer.procedural", "app.viewer.lod")


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


# ---------------------------------------------------------------------------------------------------- identity
def zip_directory_digest(path):
    """Digest of a zip's directory (name, CRC-32 and size of every member, in directory order), or None when the
    file is not a readable zip. Only the directory at the end of the file is read, never the members."""
    try:
        digest = hashlib.sha256()
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                digest.update(f"{info.filename}\0{info.CRC:08x}\0{info.file_size}\n".encode("utf-8", "surrogateescape"))
        return digest.hexdigest()
    except Exception:
        return None


def _located(path):
    size, mtime = _stat(path)
    return ["stat", os.path.normcase(os.path.abspath(path)), size, mtime]


def source_identity(path):
    """What a model file contributes to a key: its size and zip-directory digest, wherever it lies. A file that is
    not a zip (it cannot be decoded either) keeps the old identity of path, size and modified time."""
    digest = zip_directory_digest(path)
    if digest is None:
        return _located(path)
    return ["zip", _stat(path)[0], digest]


def companion_identity(path):
    """A companion file's share of a key: ``.npz`` like the model file, anything else by a hash of its bytes."""
    if str(path).lower().endswith((".npz", ".zip")):
        return source_identity(path)
    try:
        if os.stat(path).st_size > HASH_LIMIT_BYTES:
            return _located(path)
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                digest.update(block)
        return ["bytes", digest.hexdigest()]
    except OSError:
        return _located(path)


_code_ids = {}


def _module_bytes(name):
    """The source text of a module (line ends normalised); in a build that ships no source, its compiled code."""
    spec = importlib.util.find_spec(name)
    loader = spec.loader
    try:
        text = loader.get_source(name)
    except Exception:
        text = None
    if text is not None:
        return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    try:
        return marshal.dumps(loader.get_code(name))
    except Exception:
        return Path(spec.origin).read_bytes()


def code_id(modules):
    """Short hash of the code of ``modules``, worked out once per run. Raises when a module cannot be read."""
    modules = tuple(modules)
    found = _code_ids.get(modules)
    if found is None:
        digest = hashlib.sha256()
        for name in modules:
            data = _module_bytes(name)
            digest.update(f"{name}\0{len(data)}\0".encode())
            digest.update(data)
        found = _code_ids[modules] = digest.hexdigest()[:16]
    return found


def make_key(path, companions=(), retired=(), owner=None):
    """Hex key of a source file and everything else the prepared arrays depend on, or None.

    ``owner`` names the library model that opens the file (its hooks and guide can shape the parts); None for a file
    opened on its own, whose key then depends on nothing but what the files hold."""
    try:
        from . import lod, model as viewer_model
        ident = {
            "v": FORMAT_VERSION,
            "code": code_id(SHAPING_MODULES),
            "source": source_identity(path),
            "companions": sorted([str(role), *companion_identity(p)] for role, p in companions),
            "owner": owner,
            "retired": sorted(str(r) for r in retired),
            "lod": [lod.LEVELS, lod.MIN_TRIANGLES, lod.MIN_KEEP, lod.MIN_GAIN, lod._BITS, lod.REFERENCE_PIXELS],
            "layout": [viewer_model.VERTEX_FLOATS],
        }
        return hashlib.sha256(json.dumps(ident, sort_keys=True).encode()).hexdigest()[:40]
    except Exception:
        return None


# ---------------------------------------------------------------------------------------------------- safe saving
def write_array(path, array):
    """One array as a plain .npy, flushed to the disk before the call returns."""
    with open(path, "wb") as fh:
        np.save(fh, array, allow_pickle=False)
        fh.flush()
        os.fsync(fh.fileno())


def write_meta(folder, meta):
    """``meta.json``, written last and flushed: it adds the byte size of every file already in the folder."""
    files = {f.name: int(f.stat().st_size) for f in sorted(folder.iterdir()) if f.is_file() and f.name != "meta.json"}
    with open(folder / "meta.json", "w", encoding="utf-8") as fh:
        fh.write(json.dumps({**meta, "files": files}))
        fh.flush()
        os.fsync(fh.fileno())


def sizes_match(folder, meta, required=()):
    """True when ``meta`` lists every required file and every listed file has its recorded byte size on disk."""
    files = meta.get("files")
    if not isinstance(files, dict) or any(name not in files for name in required):
        return False
    try:
        for name, size in files.items():
            if os.path.basename(name) != name or os.stat(folder / name).st_size != int(size):
                return False
    except (OSError, TypeError, ValueError):
        return False
    return True


def remove_entry(folder):
    """Delete an entry or temporary folder, ``meta.json`` first, so that what is left if the rest cannot go (a file
    still mapped on Windows) is never opened. True when the folder is gone."""
    try:
        (folder / "meta.json").unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False                       # still whole and readable: leave it alone
    shutil.rmtree(folder, ignore_errors=True)
    return not folder.exists()


def commit(temp, final, valid):
    """Rename a finished temporary folder into place. ``valid(folder)`` says whether an open would accept what is
    there. A valid entry stays as it is (the caller then drops its temporary folder); a broken one is removed first.
    True when ``final`` holds a good entry afterwards."""
    if final.exists():
        if valid(final):
            return True
        if not remove_entry(final):
            return False
    try:
        os.replace(temp, final)
    except OSError:
        return bool(valid(final))          # another writer got there first
    try:                                   # the rename itself, where the system can flush a folder
        fd = os.open(final.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass
    return True


def _disk_usage(folder):
    probe = Path(folder)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe)


def disk_allows(root, need):
    """True when writing ``need`` bytes under ``root`` leaves the volume its free floor."""
    try:
        usage = _disk_usage(root)
        return usage.free - int(need) >= max(MIN_FREE_BYTES, int(usage.total * MIN_FREE_FRACTION))
    except Exception:
        return False


_refused = {}                              # (store folder, key) -> why its save did not happen, for this run


def refuse(root, key, why):
    _refused[(str(root), key)] = str(why)


def refused(root, key):
    """Why the save of ``key`` was refused or failed earlier in this run, or None."""
    return _refused.get((str(root), key))


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
    prepared = _read_entry(root / key, key)
    if prepared is not None:
        try:
            os.utime(root / key / "meta.json")
        except OSError:
            pass
    return prepared


def _read_entry(folder, key):
    """The entry in ``folder`` opened, or None: its meta.json must name this key and version and list every file
    with the byte size it has on disk, and the arrays must have the recorded shapes. An entry written before the
    sizes were recorded is not accepted."""
    try:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        if meta.get("version") != FORMAT_VERSION or meta.get("key") != key:
            return None
        required = ["vertices.npy", "indices.npy"] + (["lod.npy"] if meta["lod"] else [])
        if not sizes_match(folder, meta, required):
            return None
        return Prepared(folder, meta)
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
                    remove_entry(folder)
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
        if remove_entry(folder):
            total -= size


def _save(model, plan):
    """Write the entry of ``plan["key"]``. A save that is refused or fails is remembered for this run (see
    ``refused``) and not tried again; the model is open either way."""
    root = cache_root()
    key = plan["key"]
    if root is None or refused(root, key):
        return False
    try:
        why = _write(model, plan, root, key)
    except Exception as exc:
        why = f"{type(exc).__name__}: {exc}"
    if why:
        refuse(root, key, why)
    return not why


def _write(model, plan, root, key):
    """None when the store holds a good entry for ``key`` afterwards, else the reason it does not."""
    final = root / key

    def valid(folder):
        return _read_entry(folder, key) is not None

    if final.exists() and valid(final):
        return None                     # another writer finished first: its entry stays
    bytes_needed = int(model.vertices.nbytes + model.indices.nbytes)
    flat, lod_entries, lod_total = _lod_entries(model)
    bytes_needed += 4 * lod_total
    if bytes_needed > cap_bytes():
        return "larger than the cache size limit"
    if not disk_allows(root, bytes_needed):
        return "too little free disk space"
    root.mkdir(parents=True, exist_ok=True)
    temp = root / f".tmp-{key[:12]}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    try:
        temp.mkdir()
        write_array(temp / "vertices.npy", model.vertices)
        write_array(temp / "indices.npy", model.indices)
        if flat:
            write_array(temp / "lod.npy", np.concatenate(flat) if len(flat) > 1 else flat[0])
        meta = {"version": FORMAT_VERSION, "key": key, "code": code_id(SHAPING_MODULES), "created": time.time(),
                "source": plan["source"],
                "vertices": int(model.vertices.shape[0]), "floats": int(model.vertices.shape[1]),
                "indices": int(model.indices.size), "decode": [list(m) for m in plan["decode"]],
                "warnings": plan["warnings"], "parts": _part_entries(model),
                "bounds_min": [float(x) for x in model._finish_bounds[0]],
                "bounds_max": [float(x) for x in model._finish_bounds[1]],
                "lod": lod_entries, "lod_total": int(lod_total)}
        write_meta(temp, meta)
        if not commit(temp, final, valid):
            return "the entry could not be put in place"
        prune(root, keep=key)
        return None
    finally:
        if temp.exists():
            remove_entry(temp)


def save_async(model):
    """Store a freshly prepared model's arrays in the background. Silent on any failure."""
    try:
        root = cache_root()
        if not eligible(model) or root is None:
            return
        plan = model._prepared_plan
        if refused(root, plan["key"]):
            return
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
