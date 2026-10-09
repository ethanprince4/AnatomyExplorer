"""Stage D: write review copies of model files with the accepted simplified parts swapped in.
Originals are never touched; copies go to OUT/staged/<library path>.
usage: slim_stage.py OUT [model ...]   (default: every model with an accepted part)"""
import json, os, sys
from collections import defaultdict
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "data" / "local_model_library"
out = Path(sys.argv[1])
res = [json.loads(l) for l in open(out / "results.jsonl")]
models = json.loads((LIB / "library.json").read_text())["models"]
wanted = set(sys.argv[2:])


def face_normals(v, f):
    raw = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    n = raw / np.maximum(np.linalg.norm(raw, axis=1, keepdims=True), 1e-30)
    return raw, n


def has_hard_edges(p):
    """Whether the original carries hard edges: positions that appear with more than one normal."""
    q = np.round(p.astype(np.float64), 6)
    return len(np.unique(q, axis=0)) < 0.995 * len(p)


def smooth_normals(v, f, crease=None):
    """Area-weighted vertex normals of the simplified shape itself. With `crease` (degrees), a vertex is split where
    its faces meet at more than that, so cut faces and box edges stay sharp. (Copying the original's normals onto the
    coarser shape was tried and showed blotches on noisy, nearly flat surfaces.)"""
    raw, fn = face_normals(v, f)
    V = len(v)
    if crease is None:
        vn = np.zeros((V, 3))
        for k in range(3):
            np.add.at(vn, f[:, k], raw)
        vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-30)
        return v, vn, f
    cv = f.reshape(-1)
    cf = np.repeat(np.arange(len(f)), 3)
    order = np.argsort(cv, kind="stable")
    cv_s, cf_s = cv[order], cf[order]
    val = np.bincount(cv, minlength=V)
    start = np.concatenate([[0], np.cumsum(val)[:-1]])
    K = int(val.max())
    table = np.full((V, K), -1, dtype=np.int64)
    table[cv_s, np.arange(len(cv_s)) - start[cv_s]] = cf_s
    cos = np.cos(np.radians(crease))
    corner_n = np.zeros((len(cv_s), 3))
    step = max(1, 40_000_000 // (K * 3))
    for s in range(0, len(cv_s), step):
        rows = table[cv_s[s:s + step]]
        valid = rows >= 0
        safe_rows = np.where(valid, rows, 0)
        mask = valid & (np.einsum("ckj,cj->ck", fn[safe_rows], fn[cf_s[s:s + step]]) >= cos)
        corner_n[s:s + step] = np.einsum("ck,ckj->cj", mask.astype(np.float64), raw[safe_rows])
    corner_n /= np.maximum(np.linalg.norm(corner_n, axis=1, keepdims=True), 1e-30)
    key = np.column_stack([cv_s, np.round(corner_n * 1000).astype(np.int64)])
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    nn = np.zeros((len(uniq), 3))
    np.add.at(nn, inv, corner_n)
    nn /= np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-30)
    faces = np.empty(len(cv_s), dtype=np.int64)
    faces[order] = inv
    return v[uniq[:, 0]], nn, faces.reshape(-1, 3)


def encode_faces(f):
    flat = f.reshape(-1).astype(np.int64)
    return np.diff(flat, prepend=0).astype(np.int32)        # the library stores index deltas (decoder: cumsum)


accepted = defaultdict(list)
for r in res:
    if r.get("accepted") and (not wanted or r["model"] in wanted):
        accepted[r["model"]].append(r)
summary = []
for mid, rows in sorted(accepted.items()):
    rel = models[mid]["variants"]["post"]["path"]
    src = LIB / rel
    dst = out / "staged" / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    z = np.load(src)
    arrays = {k: z[k] for k in z.files}
    meta = json.loads(bytes(arrays["meta"]).decode())
    names = [p["name"] for p in meta["parts"]]
    before = after = 0
    for r in rows:
        i = names.index(r["part"])
        p, n = arrays[f"p{i}"].astype(np.float64), arrays[f"n{i}"].astype(np.float64)
        s = np.load(r["slim_file"])
        v, f = s["vertices"].astype(np.float64), s["triangles"].astype(np.int64)
        nv, nn, nf = smooth_normals(v, f, 60.0 if has_hard_edges(p) else None)
        if f"c{i}" in arrays:                                 # per-vertex colours: nearest original vertex
            _, near = cKDTree(p).query(nv)
            arrays[f"c{i}"] = arrays[f"c{i}"][near]
        arrays[f"p{i}"] = nv.astype(np.float32)
        arrays[f"n{i}"] = nn.astype(np.float32)
        arrays[f"i{i}"] = encode_faces(nf)
        before += r["triangles"]; after += len(nf)
        check = np.cumsum(arrays[f"i{i}"].astype(np.int64)).reshape(-1, 3)
        assert (check == nf).all() and check.max() < len(nv)
        print(f"{mid} / {r['part']}: {r['triangles']:,} -> {len(nf):,} triangles, {len(p):,} -> {len(nv):,} vertices, "
              f"({len(nv) / max(1, len(nf)):.2f} vertices per triangle; original {len(p) / max(1, r['triangles']):.2f})", flush=True)
    np.savez_compressed(dst, **arrays)
    total = sum(len(arrays[k]) // 3 for k in arrays if k.startswith("i") and k[1:].isdigit())
    summary.append({"model": mid, "file": str(dst), "source": str(src), "parts": len(rows), "part_triangles_before": before,
                    "part_triangles_after": after, "model_triangles_after": total,
                    "bytes_before": src.stat().st_size, "bytes_after": dst.stat().st_size})
    print(f"== {mid}: {src.stat().st_size / 1e6:.0f} MB -> {dst.stat().st_size / 1e6:.0f} MB", flush=True)
path = out / "staged" / "summary.json"
done = {s["model"]: s for s in (json.loads(path.read_text()) if path.exists() else [])}
done.update({s["model"]: s for s in summary})               # a later run for some models keeps the others
with open(path, "w") as fh:
    json.dump(sorted(done.values(), key=lambda s: s["model"]), fh, indent=1)
