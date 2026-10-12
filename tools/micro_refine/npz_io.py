"""Read and write the app's model-library NPZ format (what app/variants/local_runtime.decode_local_npz reads).

A model file holds, per part i (in the order of meta["parts"]):
  p{i}  positions, float32 (n,3)   - or uint16 (n,3) with b{i} = [[lo xyz], [span xyz]] (quantised; ~1/65535 of the span)
  n{i}  normals, float32 (n,3) or int8 (n,3) scaled by 127
  i{i}  triangles, int32 (m,3)
  c{i}  optional per-vertex linear RGB, float32 (n,3) in 0..1 (baked teaching pattern; the part colour is the fallback)
  meta  utf-8 JSON bytes: {"parts": [{"name", "group", "color" "#rrggbb", "alpha", "category", "label", "rank",
        "clip", "bulk", "detail", "description", ...}], ...}  Unknown keys are kept as they are.

The app is +Y up. Blender is +Z up: app (x, y, z) == Blender (x, -z, y). blender_io.py converts.

Usage as a library:
    from tools.micro_refine.npz_io import read_model, write_model, Part
    meta, parts = read_model(path)          # parts: list of Part
    write_model(path, parts, meta_extra={"review_presentation": ...})
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

PART_DEFAULTS = {"alpha": 1.0, "label": True, "rank": 2, "clip": True, "bulk": False}


@dataclass
class Part:
    name: str
    vertices: np.ndarray            # (n,3) float32, app space (+Y up)
    faces: np.ndarray               # (m,3) int32
    meta: dict = field(default_factory=dict)   # group, color, alpha, category, description, ... (name is kept in sync)
    normals: np.ndarray | None = None
    colors: np.ndarray | None = None           # (n,3) float32 linear RGB 0..1

    def record(self):
        row = dict(PART_DEFAULTS)
        row.update(self.meta)
        row["name"] = self.name
        return row


def _vertex_normals(v, f):
    v = np.asarray(v, np.float64)
    f = np.asarray(f, np.int64)
    n = np.zeros_like(v)
    if len(f):
        fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
        for k in range(3):
            np.add.at(n, f[:, k], fn)
    ln = np.linalg.norm(n, axis=1)
    bad = ln < 1e-20
    n[~bad] /= ln[~bad, None]
    n[bad] = (0.0, 1.0, 0.0)
    return n.astype(np.float32)


def read_model(path):
    """Return (meta, [Part]) decoded exactly as the app decodes it (quantisation, delta indices, int8 normals)."""
    with np.load(path, allow_pickle=False) as z:
        keys = set(z.files)
        meta = json.loads(z["meta"].tobytes().decode("utf-8"))
        parts = []
        for i, row in enumerate(meta["parts"]):
            raw = z[f"p{i}"]
            if raw.dtype.kind == "u" and f"b{i}" in keys:
                lo, span = z[f"b{i}"]
                v = (raw.astype(np.float64) / 65535.0 * span + lo).astype(np.float32)
            else:
                v = raw.astype(np.float32)
            idx = z[f"i{i}"]
            f = idx.astype(np.int64) if idx.ndim == 2 else np.cumsum(idx.astype(np.int64)).reshape(-1, 3)
            n = None
            if f"n{i}" in keys:
                n = z[f"n{i}"].astype(np.float32)
                if z[f"n{i}"].dtype.kind in "iu":
                    n /= 127.0
            c = z[f"c{i}"].astype(np.float32) if f"c{i}" in keys else None
            if c is not None and z[f"c{i}"].dtype.kind in "ui":
                c /= np.iinfo(z[f"c{i}"].dtype).max
            rec = dict(row)
            name = rec.pop("name", f"Part {i + 1}")
            parts.append(Part(name, v, f.astype(np.int32), rec, n, c))
    return meta, parts


def write_model(path, parts, meta_extra=None, quantise=True, overwrite=False):
    """Write parts to a library NPZ. quantise=True stores uint16 positions (+b{i}) and int8 normals, like the
    slimmed library files; precision is span/65535 per axis per part (sub-micrometre on a 2-unit block)."""
    path = Path(path)
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} exists; never save over a model file (use a new version folder)")
    names = [p.name for p in parts]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"duplicate part names: {dup[:10]}")
    arrays = {}
    rows = []
    for i, p in enumerate(parts):
        v = np.ascontiguousarray(p.vertices, np.float32)
        f = np.ascontiguousarray(p.faces, np.int64)
        if v.ndim != 2 or v.shape[1] != 3 or not len(v) or not np.isfinite(v).all():
            raise ValueError(f"{p.name}: bad vertices")
        if f.ndim != 2 or f.shape[1] != 3 or not len(f) or f.min() < 0 or f.max() >= len(v):
            raise ValueError(f"{p.name}: bad faces")
        n = p.normals if p.normals is not None and np.shape(p.normals) == v.shape else _vertex_normals(v, f)
        n = np.asarray(n, np.float32)
        if quantise:
            lo = v.min(0).astype(np.float64)
            span = np.maximum(v.max(0).astype(np.float64) - lo, 1e-12)
            arrays[f"p{i}"] = np.round((v - lo) / span * 65535.0).clip(0, 65535).astype(np.uint16)
            arrays[f"b{i}"] = np.stack([lo, span])
            ln = np.linalg.norm(n, axis=1, keepdims=True)
            ln[ln < 1e-20] = 1.0
            arrays[f"n{i}"] = np.round(n / ln * 127.0).clip(-127, 127).astype(np.int8)
        else:
            arrays[f"p{i}"] = v
            arrays[f"n{i}"] = n
        arrays[f"i{i}"] = f.astype(np.int32)
        if p.colors is not None:
            c = np.asarray(p.colors, np.float32)
            if c.shape != v.shape or not np.isfinite(c).all() or c.min() < 0 or c.max() > 1:
                raise ValueError(f"{p.name}: colours must be (n,3) linear RGB in 0..1")
            arrays[f"c{i}"] = c
        rows.append(p.record())
    meta = dict(meta_extra or {})
    meta["parts"] = rows
    meta["position_encoding"] = "uint16" if quantise else "float32"
    meta["normal_encoding"] = "int8" if quantise else "float32"
    arrays["meta"] = np.frombuffer(json.dumps(meta, ensure_ascii=False, allow_nan=False).encode("utf-8"), np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb" if overwrite else "xb") as fh:
        np.savez_compressed(fh, **arrays)
    return path


def summary(path):
    meta, parts = read_model(path)
    tris = sum(len(p.faces) for p in parts)
    groups = {}
    for p in parts:
        groups.setdefault(p.meta.get("group", ""), []).append(p.name)
    return {"parts": len(parts), "triangles": tris, "groups": {g: len(v) for g, v in groups.items()},
            "bounds": [np.min([p.vertices.min(0) for p in parts], 0).round(4).tolist(),
                       np.max([p.vertices.max(0) for p in parts], 0).round(4).tolist()]}


if __name__ == "__main__":
    import sys
    for a in sys.argv[1:]:
        print(a, json.dumps(summary(a), indent=1))
