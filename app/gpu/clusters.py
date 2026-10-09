"""Triangle clusters for GPU culling: at most 64 triangles per cluster, per part and per LOD index range.

Nothing here touches the vertex data of the model: a cluster is a run of 64 consecutive entries of a per-range
triangle order ``perm`` (the triangles of one index range sorted by the Morton code of their centroid), plus a
bounding box in PART space. The GPU copies the triangles of the surviving clusters into a compacted index buffer by
looking the triangle up in the page's own index buffer (geometry.py is not changed).

Ranges. ``geom.ranges[part]`` lists (first_index, count) for level 0 and LOD levels 1..LEVELS; levels that share one
index array repeat the same entry. A *range* here is one distinct (page, first_index, count). ``level_range[part, k]``
maps the renderer's level choice (``k`` beyond the part's list falls back to level 0, as the renderer does) to a range
id, -1 when the renderer skips the part (fewer than 3 indices). Ranges are ordered by (page, first_index), so the
clusters of a page are contiguous: clusters ``page_cfirst[g] : page_cfirst[g + 1]``.

Bounds and displacement. The box of a cluster is the exact min/max of its vertex positions (``pos``, the stored
float32 value). The shader moves nothing but the part matrix today; the dynamic displacements are covered like this:
  * explode, node offsets, animation of rigid nodes: all are part of the per-frame part matrix the caller passes, the
    box is transformed with it (an oriented box), nothing to expand;
  * morph weight ``w`` (p = pos + w * dpos): ``dmax`` is the largest |dpos| of the cluster's vertices (the value of
    the vertex stream or of the part's constant, whichever the part has). The shader grows every half extent by
    ``|w| * dmax`` (+ 2e-6 relative), which contains the displaced vertex for any ``w`` (|w*dpos_axis| <= |w|*|dpos|);
  * procedural animation (m0..m3 attributes, ``model.anim_vertices``): not bounded; every part of such a model is
    ``uncullable`` and the renderer draws it plain.
Parts whose indices leave their own vertex range are uncullable too (the vertex -> part lookup of the indexed draw
relies on it), as are parts without geometry.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from app.viewer import lod as _lod

CLUSTER_TRIS = 64
BUILD_VERSION = 1
_CHUNK = 1 << 21                       # triangles per vectorised step (a multiple of CLUSTER_TRIS)
LEVEL_COUNT = _lod.LEVELS + 1


class ClusterError(Exception):
    pass


@dataclass
class ClusterData:
    # ranges (R)
    r_part: np.ndarray                 # int32 part index
    r_page: np.ndarray                 # int32
    r_first: np.ndarray                # int64 first index, page local
    r_ntri: np.ndarray                 # int64 triangles
    r_cfirst: np.ndarray               # int64 first cluster
    r_tfirst: np.ndarray               # int64 first entry in perm
    r_ccount: np.ndarray               # int64 clusters
    level_range: np.ndarray            # (P, LEVEL_COUNT) int32, -1 = not drawn
    uncullable: np.ndarray             # (P,) bool
    page_cfirst: np.ndarray            # (G + 1,) int64
    # clusters (C) and triangles (T)
    cl_geom: np.ndarray                # (C, 8) float32: cx cy cz dmax | hx hy hz 0
    cl_range: np.ndarray               # (C,) uint32
    perm: np.ndarray                   # (T,) uint32: range-local triangle index, cluster order
    stats: dict = field(default_factory=dict)

    @property
    def n_ranges(self):
        return len(self.r_part)

    @property
    def n_clusters(self):
        return len(self.cl_range)

    @property
    def n_tris(self):
        return len(self.perm)

    def range_table(self):
        """(R, 8) uint32 rows for the shader: part, page, first, ntri | cfirst, tfirst, ccount, 0."""
        t = np.zeros((self.n_ranges, 8), dtype=np.uint32)
        t[:, 0], t[:, 1], t[:, 2], t[:, 3] = self.r_part, self.r_page, self.r_first, self.r_ntri
        t[:, 4], t[:, 5], t[:, 6] = self.r_cfirst, self.r_tfirst, self.r_ccount
        return t

    def cluster_tris(self, c):
        r = int(self.cl_range[c])
        j = int(c - self.r_cfirst[r])
        return int(min(CLUSTER_TRIS, self.r_ntri[r] - CLUSTER_TRIS * j))

    def cluster_perm(self, c):
        """Range-local triangle indices of cluster ``c`` (the order inside the cluster is the Morton order)."""
        r = int(self.cl_range[c])
        j = int(c - self.r_cfirst[r])
        a = int(self.r_tfirst[r]) + CLUSTER_TRIS * j
        return self.perm[a:a + self.cluster_tris(c)]


# ------------------------------------------------------------------------------------------------ morton codes
def _spread(v):
    v = v.astype(np.uint64) & np.uint64(0x1FFFFF)
    v = (v | (v << np.uint64(32))) & np.uint64(0x1F00000000FFFF)
    v = (v | (v << np.uint64(16))) & np.uint64(0x1F0000FF0000FF)
    v = (v | (v << np.uint64(8))) & np.uint64(0x100F00F00F00F00F)
    v = (v | (v << np.uint64(4))) & np.uint64(0x10C30C30C30C30C3)
    v = (v | (v << np.uint64(2))) & np.uint64(0x1249249249249249)
    return v


def morton_codes(centroids, lo, span):
    q = np.clip(((centroids - lo) / span * 2097151.0), 0, 2097151).astype(np.int64)
    return _spread(q[:, 0]) | (_spread(q[:, 1]) << np.uint64(1)) | (_spread(q[:, 2]) << np.uint64(2))


# ------------------------------------------------------------------------------------------------ one range
def _build_range(pos, dn, tris, lo, span):
    """pos (V,3) f32 part vertices, dn (V,) f32 |dpos|, tris (n,3) integer part-local vertex ids.
    Returns (perm uint32 (n,), geom (nc, 8) float32)."""
    n = len(tris)
    code = np.empty(n, dtype=np.uint64)
    for a in range(0, n, _CHUNK):
        t = tris[a:a + _CHUNK]
        cen = (pos[t[:, 0]].astype(np.float64) + pos[t[:, 1]] + pos[t[:, 2]]) * (1.0 / 3.0)
        code[a:a + _CHUNK] = morton_codes(cen, lo, span)
    order = np.argsort(code)
    del code
    nc = -(-n // CLUSTER_TRIS)
    geom = np.zeros((nc, 8), dtype=np.float32)
    for a in range(0, n, _CHUNK):
        b = min(a + _CHUNK, n)
        t = tris[order[a:b]]
        p = pos[t]                                         # (m, 3, 3)
        tlo, thi = p.min(axis=1), p.max(axis=1)
        td = dn[t].max(axis=1)
        starts = np.arange(0, b - a, CLUSTER_TRIS)
        clo = np.minimum.reduceat(tlo, starts, axis=0)
        chi = np.maximum.reduceat(thi, starts, axis=0)
        cd = np.maximum.reduceat(td, starts)
        k0 = a // CLUSTER_TRIS
        k1 = k0 + len(starts)
        geom[k0:k1, 0:3] = (clo.astype(np.float64) + chi) * 0.5
        geom[k0:k1, 3] = cd
        geom[k0:k1, 4:7] = (chi.astype(np.float64) - clo) * 0.5
        # float32 rounding of centre / half must not shrink the box
        c32 = geom[k0:k1, 0:3].astype(np.float64)
        h32 = geom[k0:k1, 4:7].astype(np.float64)
        need = np.maximum(chi - c32, c32 - clo)
        geom[k0:k1, 4:7] = np.where(need > h32, np.nextafter((need).astype(np.float32), np.float32(np.inf)), geom[k0:k1, 4:7])
        del t, p, tlo, thi
    return order.astype(np.uint32), geom


def _source_indices(model, part, level):
    if level == 0:
        return model.indices[part.first:part.first + part.count]
    return model.lod[part.id].indices[level - 1]


# ------------------------------------------------------------------------------------------------ build
def plan_ranges(model, geom):
    """Ranges, level -> range map and the uncullable parts. Returns (range keys sorted, level_range, uncullable,
    range_source) where range_source[i] = (part index, level) of the first level that uses range i."""
    parts = model.parts
    P = len(parts)
    animated = getattr(model, "anim_vertices", None) is not None
    uncullable = np.zeros(P, dtype=bool)
    level_range = np.full((P, LEVEL_COUNT), -1, dtype=np.int32)
    key_of, source = {}, []
    pending = np.full((P, LEVEL_COUNT), -1, dtype=np.int64)       # key index per level
    keys = []
    for pi, p in enumerate(parts):
        if geom.page_of[pi] < 0 or animated:
            uncullable[pi] = True
            continue
        rr = geom.ranges[pi]
        for k in range(LEVEL_COUNT):
            first, count = rr[k] if k < len(rr) else rr[0]
            if count < 3:
                continue
            key = (int(geom.page_of[pi]), int(first), int(count))
            ki = key_of.get(key)
            if ki is None:
                ki = key_of[key] = len(keys)
                keys.append(key)
                source.append((pi, k if k < len(rr) else 0))
            pending[pi, k] = ki
    order = sorted(range(len(keys)), key=lambda i: keys[i])
    new_id = np.empty(len(keys), dtype=np.int64)
    for rank, i in enumerate(order):
        new_id[i] = rank
    if keys:                                                       # (a model whose parts are all uncullable has no range)
        level_range[:] = np.where(pending >= 0, new_id[np.maximum(pending, 0)], -1)
    return [keys[i] for i in order], level_range, uncullable, [source[i] for i in order]


def build_clusters(model, geom, threads=None, progress=None):
    t_start = time.perf_counter()
    parts = model.parts
    keys, level_range, uncullable, source = plan_ranges(model, geom)
    R = len(keys)
    r_part = np.array([s[0] for s in source], dtype=np.int32) if R else np.zeros(0, np.int32)
    r_page = np.array([k[0] for k in keys], dtype=np.int32)
    r_first = np.array([k[1] for k in keys], dtype=np.int64)
    r_ntri = np.array([k[2] // 3 for k in keys], dtype=np.int64)
    r_ccount = -(-r_ntri // CLUSTER_TRIS)
    r_cfirst = np.concatenate([[0], np.cumsum(r_ccount)[:-1]]).astype(np.int64) if R else np.zeros(0, np.int64)
    r_tfirst = np.concatenate([[0], np.cumsum(r_ntri)[:-1]]).astype(np.int64) if R else np.zeros(0, np.int64)
    C, T = int(r_ccount.sum()), int(r_ntri.sum())
    perm = np.empty(T, dtype=np.uint32)
    cgeom = np.empty((C, 8), dtype=np.float32)
    cl_range = np.repeat(np.arange(R, dtype=np.uint32), r_ccount)

    by_part = {}
    for ri in range(R):
        by_part.setdefault(int(r_part[ri]), []).append(ri)
    bad = []

    def job(pi):
        p = parts[pi]
        vb, vc = p.vertex_base, p.vertex_count
        blk = np.asarray(model.vertices[vb:vb + vc, 0:9])
        pos = np.ascontiguousarray(blk[:, 0:3])
        dn = np.sqrt((blk[:, 6:9].astype(np.float64) ** 2).sum(axis=1)).astype(np.float32)
        lo = pos.min(axis=0).astype(np.float64)
        span = np.maximum(pos.max(axis=0).astype(np.float64) - lo, 1e-12)
        for ri in by_part[pi]:
            # any level that uses this range carries the same array: take the lowest one
            lv = int(np.nonzero(level_range[pi] == ri)[0][0])
            src = _source_indices(model, p, lv)
            tris = np.asarray(src, dtype=np.int64).reshape(-1, 3) - vb
            if len(tris) != r_ntri[ri]:
                raise ClusterError(f"part {p.name!r} level {lv}: index count differs from the geometry range")
            if len(tris) and (tris.min() < 0 or tris.max() >= vc):
                bad.append(pi)
                return
            pm, g = _build_range(pos, dn, tris, lo, span)
            t0, c0 = int(r_tfirst[ri]), int(r_cfirst[ri])
            perm[t0:t0 + len(pm)] = pm
            cgeom[c0:c0 + len(g)] = g

    todo = sorted(by_part, key=lambda pi: -sum(int(r_ntri[r]) for r in by_part[pi]))
    n_threads = threads or min(8, max(1, (__import__("os").cpu_count() or 2)))
    done = 0
    with ThreadPoolExecutor(max_workers=n_threads) as pool:
        for _ in pool.map(job, todo):
            done += 1
            if progress:
                progress(done, len(todo))
    if bad:
        raise ClusterError("parts index vertices outside their own range: " + ", ".join(parts[i].name for i in set(bad)))
    G = int(r_page.max()) + 1 if R else 0
    page_cfirst = np.zeros(G + 1, dtype=np.int64)
    for g in range(G):
        page_cfirst[g + 1] = page_cfirst[g] + int(r_ccount[r_page == g].sum())
    stats = {"ranges": R, "clusters": C, "triangles": T, "uncullable_parts": int(uncullable.sum()),
             "build_s": time.perf_counter() - t_start, "bytes": int(perm.nbytes + cgeom.nbytes + cl_range.nbytes),
             "bytes_per_triangle": (perm.nbytes + cgeom.nbytes + cl_range.nbytes) / max(T, 1),
             "avg_tris_per_cluster": T / max(C, 1)}
    return ClusterData(r_part=r_part, r_page=r_page, r_first=r_first, r_ntri=r_ntri, r_cfirst=r_cfirst,
                       r_tfirst=r_tfirst, r_ccount=r_ccount, level_range=level_range, uncullable=uncullable,
                       page_cfirst=page_cfirst, cl_geom=cgeom, cl_range=cl_range, perm=perm, stats=stats)


# ------------------------------------------------------------------------------------------------ page capacity
def page_capacity(cd, n_pages):
    """Compacted-buffer capacity (blocks of 64 triangles) per page: the sum over the page's parts of the largest
    cluster count among the part's levels. One level is drawn per part per frame and a cluster is drawn at most once
    per frame (phase 1 draws what phase 2 skips), so a page can never need more: overflow is impossible."""
    cap = np.zeros(n_pages, dtype=np.int64)
    P = cd.level_range.shape[0]
    cc = np.where(cd.level_range >= 0, cd.r_ccount[np.maximum(cd.level_range, 0)], 0)
    best = cc.max(axis=1) if P else np.zeros(0, np.int64)
    # pages of the parts: take them from the ranges
    part_page = np.full(P, -1, dtype=np.int64)
    part_page[cd.r_part] = cd.r_page
    for g in range(n_pages):
        cap[g] = int(best[part_page == g].sum())
    return cap
