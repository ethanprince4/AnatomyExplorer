"""Spike: decode library models, build <=64 vertex / <=124 triangle clusters, quantise vertices.

Read-only on model.npz (same layout and decode rules as app/variants/local_runtime.py:79-110).
Output goes to a cache directory as plain .npy files, one directory per model.

Per model output (all part-local indices; parts keep their model-space placement):
  vtx16     (V,5) uint16   x,y,z quantised in the part box (0..65535), nx,ny octahedral snorm16 (int16 bits)
  idx8      (B,)  uint8    per cluster tcount*3 local indices, each cluster starts on a 4-byte boundary
  c_vfirst  (C,)  int64    first vertex of the cluster in vtx16 (the cluster's vertices are contiguous)
  c_vcount, c_tcount (C,) uint8 ; c_ioff (C,) int64 byte offset in idx8
  c_center (C,3) f32, c_radius (C,) f32 (bounding sphere of the dequantised vertices)
  c_cone   (C,4) uint8    snorm8 axis xyz + cutoff in 0..127 (127 = never culled), rounded conservatively
  part_lo, part_ext (P,3) f32 ; part_cstart (P+1,) int64 ; stats.json
"""
import json
import os
import sys
import time

import numpy as np

MAX_V = int(os.environ.get("CULL_MAXV", "64"))
MAX_T = int(os.environ.get("CULL_MAXT", "124"))
CHUNK = 4 * MAX_T


def decode_model(path):
    """Yield (name, positions f32 (N,3), normals f32 (N,3) unit, faces int32 (T,3))."""
    parts = []
    with np.load(path, allow_pickle=False) as archive:
        keys = set(archive.files)
        meta = json.loads(archive["meta"].tobytes().decode("utf-8"))
        for i, row in enumerate(meta["parts"]):
            raw = archive[f"p{i}"]
            if raw.dtype.kind == "u" and f"b{i}" in keys:
                lo, span = archive[f"b{i}"]
                pos = (raw.astype(np.float64) / 65535.0 * span + lo).astype(np.float32)
            else:
                pos = raw.astype(np.float32, copy=False)
            idx = archive[f"i{i}"]
            if idx.ndim == 2 and idx.shape[1] == 3:
                faces = idx.astype(np.int64)
            else:
                faces = np.cumsum(idx.astype(np.int64)).reshape(-1, 3)
            if faces.size and (faces.min() < 0 or faces.max() >= len(pos)):
                raise ValueError(f"{path}: part {i} index out of range")
            nrm = None
            if f"n{i}" in keys:
                rn = archive[f"n{i}"]
                nrm = rn.astype(np.float32)
                if rn.dtype.kind in "iu":
                    nrm /= 127.0
                if nrm.shape != pos.shape:
                    nrm = None
            if nrm is None:
                nrm = face_normals_to_vertices(pos, faces)
            ln = np.linalg.norm(nrm, axis=1)
            bad = ln < 1e-20
            nrm[~bad] /= ln[~bad, None]
            if bad.any():
                nrm[bad] = (0.0, 0.0, 1.0)
            parts.append((row.get("name", f"part{i}"), pos, nrm, faces.astype(np.int32)))
    return parts


def face_normals_to_vertices(pos, faces):
    a, b, c = pos[faces[:, 0]], pos[faces[:, 1]], pos[faces[:, 2]]
    fn = np.cross(b - a, c - a)
    out = np.zeros_like(pos)
    for k in range(3):
        np.add.at(out, faces[:, k], fn)
    return out


def _spread(v):
    """Spread the low 21 bits of v so there are two zero bits between them (3D Morton)."""
    v = v.astype(np.uint64) & np.uint64(0x1FFFFF)
    v = (v | (v << np.uint64(32))) & np.uint64(0x1F00000000FFFF)
    v = (v | (v << np.uint64(16))) & np.uint64(0x1F0000FF0000FF)
    v = (v | (v << np.uint64(8))) & np.uint64(0x100F00F00F00F00F)
    v = (v | (v << np.uint64(4))) & np.uint64(0x10C30C30C30C30C3)
    v = (v | (v << np.uint64(2))) & np.uint64(0x1249249249249249)
    return v


def morton_order(pos, faces):
    cen = (pos[faces[:, 0]].astype(np.float64) + pos[faces[:, 1]] + pos[faces[:, 2]]) / 3.0
    lo = cen.min(0)
    span = np.maximum(cen.max(0) - lo, 1e-12)
    q = np.clip(((cen - lo) / span * 2097151.0).astype(np.int64), 0, 2097151)
    code = _spread(q[:, 0]) | (_spread(q[:, 1]) << np.uint64(1)) | (_spread(q[:, 2]) << np.uint64(2))
    return np.argsort(code, kind="stable")


def greedy_clusters(faces, nv):
    """faces (T,3) in spatial order -> (start, count) arrays of consecutive-triangle clusters.

    Vectorised greedy fill: independent segments of CHUNK triangles each peel one cluster per round
    (longest prefix with <=64 distinct vertices and <=124 triangles).
    """
    nt = len(faces)
    seg_start = np.arange(0, nt, CHUNK, dtype=np.int64)
    seg_len = np.minimum(CHUNK, nt - seg_start)
    out_s, out_c = [], []
    while len(seg_start):
        m = int(seg_len.sum())
        sid = np.repeat(np.arange(len(seg_start)), seg_len)
        base = np.cumsum(seg_len) - seg_len
        pos_in = np.arange(m, dtype=np.int64) - np.repeat(base, seg_len)
        tri = np.repeat(seg_start, seg_len) + pos_in
        key = (sid[:, None].astype(np.int64) * nv + faces[tri].astype(np.int64)).reshape(-1)
        _, first = np.unique(key, return_index=True)
        new = np.zeros(3 * m, dtype=np.int32)
        new[first] = 1
        new_tri = new.reshape(m, 3).sum(1)
        cum = np.cumsum(new_tri)
        before = np.concatenate([[0], cum])[base]
        cum_seg = cum - before[sid]
        ok = (cum_seg <= MAX_V) & (pos_in < MAX_T)
        cnt = np.bincount(sid, weights=ok, minlength=len(seg_start)).astype(np.int64)
        out_s.append(seg_start.copy())
        out_c.append(cnt)
        seg_start = seg_start + cnt
        seg_len = seg_len - cnt
        keep = seg_len > 0
        seg_start, seg_len = seg_start[keep], seg_len[keep]
    s = np.concatenate(out_s)
    c = np.concatenate(out_c)
    o = np.argsort(s, kind="stable")
    return s[o], c[o]


def oct_encode(n):
    n = n / np.maximum(np.abs(n).sum(1, keepdims=True), 1e-20)
    x, y, z = n[:, 0].copy(), n[:, 1].copy(), n[:, 2]
    neg = z < 0
    xo = (1.0 - np.abs(y)) * np.where(x >= 0, 1.0, -1.0)
    yo = (1.0 - np.abs(x)) * np.where(y >= 0, 1.0, -1.0)
    x = np.where(neg, xo, x)
    y = np.where(neg, yo, y)
    return np.stack([np.round(np.clip(x, -1, 1) * 32767.0), np.round(np.clip(y, -1, 1) * 32767.0)], 1).astype(np.int16)


def oct_decode(e):
    x = e[:, 0].astype(np.float64) / 32767.0
    y = e[:, 1].astype(np.float64) / 32767.0
    z = 1.0 - np.abs(x) - np.abs(y)
    t = np.clip(-z, 0.0, None)
    x = x + np.where(x >= 0, -t, t)
    y = y + np.where(y >= 0, -t, t)
    v = np.stack([x, y, z], 1)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def vertex_morton_rank(pos):
    lo = pos.min(0).astype(np.float64)
    span = np.maximum(pos.max(0) - lo, 1e-12)
    q = np.clip(((pos - lo) / span * 2097151).astype(np.int64), 0, 2097151)
    code = _spread(q[:, 0]) | (_spread(q[:, 1]) << np.uint64(1)) | (_spread(q[:, 2]) << np.uint64(2))
    o = np.argsort(code, kind="stable")
    r = np.empty(len(pos), np.int64)
    r[o] = np.arange(len(pos))
    return r


def best_order(pos, faces, nv, stats):
    """Try several triangle orders, keep the one that gives the fewest clusters."""
    cands = {"natural": faces,
             "minvert": faces[np.argsort(faces.min(1), kind="stable")],
             "morton": faces[morton_order(pos, faces)]}
    srt = np.sort(vertex_morton_rank(pos)[faces], 1)
    cands["vmorton"] = faces[np.lexsort((srt[:, 2], srt[:, 1], srt[:, 0]))]
    res = []
    for name, f in cands.items():
        st, c = greedy_clusters(f, nv)
        P = pos[f]
        cmn = np.minimum.reduceat(P.min(1), st, axis=0)
        cmx = np.maximum.reduceat(P.max(1), st, axis=0)
        res.append((name, f, st, c, float(((cmx - cmn) ** 2).sum())))
    nmin = min(len(r[2]) for r in res)
    ok = [r for r in res if len(r[2]) <= 1.1 * nmin]   # near-minimal cluster count, then the tightest boxes
    best = min(ok, key=lambda r: r[4])
    best = (best[1], best[2], best[3], best[0])
    used = stats.setdefault("order_used", {})
    used[best[3]] = used.get(best[3], 0) + 1
    return best[0], best[1], best[2]


def process_part(pos, nrm, faces, stats):
    """Returns per-part dict of cluster-ordered arrays."""
    nv = len(pos)
    lo = pos.min(0).astype(np.float32)
    ext = (pos.max(0) - lo).astype(np.float32)
    safe = np.where(ext > 0, ext, 1.0).astype(np.float64)
    q = np.clip(np.round((pos.astype(np.float64) - lo) / safe * 65535.0), 0, 65535).astype(np.uint16)
    deq = (lo.astype(np.float64) + q.astype(np.float64) * (np.where(ext > 0, ext, 0.0) / 65535.0)).astype(np.float32)
    diag = float(np.linalg.norm(ext)) or 1.0
    perr = float(np.abs(deq.astype(np.float64) - pos).max() / diag)
    enc = oct_encode(nrm.astype(np.float64))
    dec = oct_decode(enc)
    cosv = np.clip((dec * nrm).sum(1), -1, 1)
    nerr = float(np.degrees(np.arccos(cosv.min())))
    stats["pos_err_rel"] = max(stats.get("pos_err_rel", 0.0), perr)
    stats["nrm_err_deg"] = max(stats.get("nrm_err_deg", 0.0), nerr)

    f, start, count = best_order(pos, faces, nv, stats)
    ncl = len(start)
    # per-cluster local vertices: unique (cluster, vertex) pairs
    cid = np.repeat(np.arange(ncl, dtype=np.int64), count)
    key = cid[:, None] * nv + f.astype(np.int64)
    ukey, inv = np.unique(key.reshape(-1), return_inverse=True)
    ucl = ukey // nv
    uv = (ukey % nv).astype(np.int64)
    vcount = np.bincount(ucl, minlength=ncl)
    vfirst_loc = np.cumsum(vcount) - vcount
    local = (inv - vfirst_loc[cid].repeat(3)).astype(np.int64).reshape(-1, 3)
    assert vcount.max() <= MAX_V and count.max() <= MAX_T and local.max() < MAX_V
    vtx = np.zeros((len(uv), 5), dtype=np.uint16)
    vtx[:, :3] = q[uv]
    vtx[:, 3:5] = enc[uv].view(np.uint16)
    # bounding sphere and normal cone from the dequantised positions
    dp = deq[uv].astype(np.float64)
    cmin = np.minimum.reduceat(dp, vfirst_loc, axis=0)
    cmax = np.maximum.reduceat(dp, vfirst_loc, axis=0)
    center = (cmin + cmax) * 0.5
    dist = np.linalg.norm(dp - center[ucl], axis=1)
    radius = np.maximum.reduceat(dist, vfirst_loc) * (1.0 + 1e-5) + 1e-9
    a = deq[f[:, 0]].astype(np.float64)
    b = deq[f[:, 1]].astype(np.float64)
    c = deq[f[:, 2]].astype(np.float64)
    fn = np.cross(b - a, c - a)
    fl = np.linalg.norm(fn, axis=1)
    good = fl > 1e-30
    fn[good] /= fl[good, None]
    fn[~good] = 0.0
    tsum = np.add.reduceat(fn, np.cumsum(count) - count, axis=0)
    tl = np.linalg.norm(tsum, axis=1)
    axis = np.where(tl[:, None] > 1e-20, tsum / np.maximum(tl, 1e-20)[:, None], np.array([[0.0, 0.0, 1.0]]))
    aq = np.clip(np.round(axis * 127.0), -127, 127)
    axq = aq / np.maximum(np.linalg.norm(aq, axis=1, keepdims=True), 1e-20)  # what the shader decodes
    dpn = (fn * axq[cid]).sum(1)
    dpn = np.where(good, dpn, 2.0)
    mindp = np.minimum.reduceat(dpn, np.cumsum(count) - count)
    mindp = np.where(mindp > 1.5, 1.0, mindp)  # cluster of only degenerate triangles
    cutoff = np.where(mindp > 0.0, np.sqrt(np.clip(1.0 - mindp * mindp, 0.0, 1.0)), 1.0)
    cut_q = np.minimum(np.ceil(cutoff * 127.0 + 1e-3), 127).astype(np.uint8)
    cone = np.zeros((ncl, 4), dtype=np.uint8)
    cone[:, :3] = aq.astype(np.int8).view(np.uint8)
    cone[:, 3] = cut_q
    # local triangle indices, 4-byte aligned per cluster
    ibytes = ((count * 3 + 3) // 4) * 4
    ioff = np.cumsum(ibytes) - ibytes
    idx8 = np.zeros(int(ibytes.sum()), dtype=np.uint8)
    tstart = np.cumsum(count) - count
    dest = np.repeat(ioff, count * 3) + (np.arange(int(count.sum()) * 3) - np.repeat(tstart * 3, count * 3))
    idx8[dest] = local.reshape(-1).astype(np.uint8)
    half = ((cmax - cmin) * 0.5 * (1.0 + 1e-5) + 1e-9).astype(np.float32)
    return dict(half=half, lo=lo, ext=ext, vtx=vtx, idx8=idx8, vcount=vcount, tcount=count, ioff=ioff,
                center=center.astype(np.float32), radius=radius.astype(np.float32), cone=cone)


def build_model(path, out_dir, log=print):
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    parts = decode_model(path)
    stats = {"model": os.path.basename(os.path.dirname(os.path.dirname(path)))}
    acc = {k: [] for k in ("vtx", "idx8", "vcount", "tcount", "ioff", "center", "radius", "cone", "lo", "ext", "half")}
    cstart, vbase, ibase, nverts, ntris = [0], 0, 0, 0, 0
    vfirst = []
    for name, pos, nrm, faces in parts:
        if len(faces) == 0:
            continue
        r = process_part(pos, nrm, faces, stats)
        for k in acc:
            acc[k].append(r[k] if k not in ("lo", "ext") else r[k][None])
        vf = np.cumsum(r["vcount"]) - r["vcount"] + vbase
        vfirst.append(vf)
        acc["ioff"][-1] = r["ioff"] + ibase
        vbase += len(r["vtx"])
        ibase += len(r["idx8"])
        ntris += int(len(faces))
        cstart.append(cstart[-1] + len(r["tcount"]))
    np.save(os.path.join(out_dir, "vtx16.npy"), np.concatenate(acc["vtx"]))
    np.save(os.path.join(out_dir, "idx8.npy"), np.concatenate(acc["idx8"]))
    np.save(os.path.join(out_dir, "c_vfirst.npy"), np.concatenate(vfirst).astype(np.int64))
    np.save(os.path.join(out_dir, "c_vcount.npy"), np.concatenate(acc["vcount"]).astype(np.uint8))
    np.save(os.path.join(out_dir, "c_tcount.npy"), np.concatenate(acc["tcount"]).astype(np.uint8))
    np.save(os.path.join(out_dir, "c_ioff.npy"), np.concatenate(acc["ioff"]).astype(np.int64))
    np.save(os.path.join(out_dir, "c_center.npy"), np.concatenate(acc["center"]))
    np.save(os.path.join(out_dir, "c_radius.npy"), np.concatenate(acc["radius"]))
    np.save(os.path.join(out_dir, "c_half.npy"), np.concatenate(acc["half"]))
    np.save(os.path.join(out_dir, "c_cone.npy"), np.concatenate(acc["cone"]))
    np.save(os.path.join(out_dir, "part_lo.npy"), np.concatenate(acc["lo"]))
    np.save(os.path.join(out_dir, "part_ext.npy"), np.concatenate(acc["ext"]))
    np.save(os.path.join(out_dir, "part_cstart.npy"), np.array(cstart, dtype=np.int64))
    ncl = cstart[-1]
    stats.update(parts=len(cstart) - 1, tris=ntris, clusters=ncl, verts=vbase, idx_bytes=ibase,
                 tris_per_cluster=ntris / max(ncl, 1), verts_per_cluster=vbase / max(ncl, 1),
                 verts_per_tri=vbase / max(ntris, 1), seconds=round(time.time() - t0, 1))
    with open(os.path.join(out_dir, "stats.json"), "w") as fh:
        json.dump(stats, fh)
    log(json.dumps(stats))
    return stats


def load_model(cache_dir):
    d = {}
    for f in os.listdir(cache_dir):
        if f.endswith(".npy"):
            d[f[:-4]] = np.load(os.path.join(cache_dir, f))
    with open(os.path.join(cache_dir, "stats.json")) as fh:
        d["stats"] = json.load(fh)
    return d


DEFAULT_MODELS = ["ileocecal_rectum", "eyeball", "whole_heart", "ear", "male_reproductive",
                  "hepatobiliary", "lymph_node", "bladder_wall", "cornea"]

if __name__ == "__main__":
    root = sys.argv[1]       # repo root
    cache = sys.argv[2]
    names = sys.argv[3:] or DEFAULT_MODELS
    for n in names:
        out = os.path.join(cache, n)
        if os.path.exists(os.path.join(out, "stats.json")):
            print("cached", n)
            continue
        build_model(os.path.join(root, "data", "local_model_library", "models", n, "v4", "model.npz"), out)
