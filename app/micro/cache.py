"""Disk cache for built microanatomy meshes (data/micro_cache/<model>.npz).

High-resolution models take seconds to build, so they are built once (tools/build_micro.py does all of them in
parallel) and reloaded instantly. The cache is invalidated whenever any source file in app/micro changes."""
import hashlib
import json
from pathlib import Path

import numpy as np

from ..config import ROOT

CACHE_DIR = ROOT / "data" / "micro_cache"
FORMAT = 4


TOOLKIT = ("base.py", "cache.py", "cells.py", "geometry.py", "kit.py", "organic.py", "sdf.py")


def _builder_files(builder):
    """Source files of a builder: the file defining it plus files of functions it calls by name (lambdas in the
    registry call e.g. build_skin)."""
    import inspect
    here = Path(__file__).parent
    names = set()
    candidates = [builder]
    code = getattr(builder, "__code__", None)
    glb = getattr(builder, "__globals__", {})
    for n in getattr(code, "co_names", ()):
        if callable(glb.get(n)):
            candidates.append(glb[n])
    for obj in candidates:
        try:
            names.add(Path(inspect.getsourcefile(obj)).name)
        except (TypeError, OSError):
            pass
    return {n for n in names if (here / n).exists()}


def source_digest(model=None):
    """Hash of the toolkit plus the model's own builder sources (all micro sources when no model is given)."""
    here = Path(__file__).parent
    files = set(TOOLKIT) | (_builder_files(model.builder) if model is not None else {f.name for f in here.glob("*.py")})
    h = hashlib.sha1(str(FORMAT).encode())
    for name in sorted(files):
        h.update(name.encode())
        h.update((here / name).read_bytes())
    return h.hexdigest()[:20]


def _path(model_id):
    return CACHE_DIR / f"{model_id}.npz"


def save_parts(model_id, parts, digest=None):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    arrays = {}
    meta = []
    for i, p in enumerate(parts):
        pos, nrm, idx = p.mesh.arrays()
        lo = pos.min(axis=0) if len(pos) else np.zeros(3, np.float32)
        span = np.maximum((pos.max(axis=0) if len(pos) else lo) - lo, 1e-9)
        arrays[f"b{i}"] = np.stack([lo, span]).astype(np.float64)
        arrays[f"p{i}"] = np.round((pos - lo) / span * 65535.0).astype(np.uint16)
        arrays[f"n{i}"] = np.clip(np.round(nrm * 127.0), -127, 127).astype(np.int8)
        flat = idx.astype(np.int64).ravel()
        arrays[f"i{i}"] = np.diff(flat, prepend=0).astype(np.int32)     # small deltas compress far better
        meta.append({"name": p.name, "group": p.group, "color": p.color, "description": p.description,
                     "alpha": p.alpha, "category": p.category, "label": p.label, "rank": p.rank, "clip": p.clip,
                     "bulk": p.bulk, "detail": list(p.detail)})
    arrays["meta"] = np.frombuffer(json.dumps({"digest": digest or source_digest(), "parts": meta}).encode("utf-8"),
                                   dtype=np.uint8)
    tmp = _path(model_id).with_suffix(".tmp.npz")
    np.savez_compressed(tmp, **arrays)
    tmp.replace(_path(model_id))


def load_parts(model_id, digest=None):
    path = _path(model_id)
    if not path.exists():
        return None
    from .base import Part
    from .geometry import Mesh
    try:
        with np.load(path) as z:
            meta = json.loads(bytes(z["meta"]).decode("utf-8"))
            if meta.get("digest") != (digest or source_digest()):
                return None
            parts = []
            for i, m in enumerate(meta["parts"]):
                nrm = z[f"n{i}"].astype(np.float32) / 127.0
                nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-6)
                lo, span = z[f"b{i}"]
                pos = (z[f"p{i}"].astype(np.float64) / 65535.0 * span + lo).astype(np.float32)
                idx = np.cumsum(z[f"i{i}"].astype(np.int64)).reshape(-1, 3)
                mesh = Mesh().add(pos, idx, nrm)
                parts.append(Part(m["name"], m["group"], m["color"], mesh, m["description"], alpha=m["alpha"],
                                  category=m["category"], label=m["label"], rank=m["rank"], clip=m["clip"],
                                  bulk=m["bulk"], detail=tuple(m["detail"])))
            return parts
    except (OSError, ValueError, KeyError):
        return None
