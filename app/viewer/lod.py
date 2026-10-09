"""Coarser copies of large parts, for drawing them where their triangles are smaller than a pixel.

A model built for close-up study (the kidney goes from the whole organ down to podocyte foot processes) spends most of
its triangles on detail that covers a pixel or less at the opening view. Each large part gets a few coarser index lists
over its own vertices, made by vertex clustering: every vertex is replaced by the first vertex of its grid cell and the
triangles that collapse are dropped. The cell doubles from level to level. The renderer draws the coarsest level whose
cell is no bigger than a pixel at the part's nearest point, so the picture changes by under a pixel.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import numpy as np

WORKERS = 3                 # threads building parts' levels at once (results do not depend on it)
LEVELS = 4
MIN_TRIANGLES = 2000        # smaller parts cost little at any distance
MIN_KEEP = 50               # a level never takes a part below this many triangles
MIN_GAIN = 0.8              # a level is kept only if it drops at least a fifth of the triangles
_BITS = 21                  # grid coordinates per axis packed into one int64 key
REFERENCE_PIXELS = 1000     # a part gets levels only if its finest one is under a pixel with the whole model this
                            # many pixels across (about the opening view); other parts would draw in full anyway


class PartLod:
    """One part's coarser levels: the cell size of each (in the part's own units) and its triangles."""

    __slots__ = ("cells", "indices")

    def __init__(self, cells, indices):
        self.cells = cells          # (LEVELS,) float64, non-decreasing
        self.indices = indices      # LEVELS uint32 arrays (a level that gained nothing repeats the one before)


def _triangle_keys(t, n):
    """One int64 per triangle, the same for every rotation of it (winding kept)."""
    i = np.argmin(t, axis=1)
    r = np.arange(len(t))
    a, b, c = t[r, i], t[r, (i + 1) % 3], t[r, (i + 2) % 3]
    return (a * n + b) * n + c


def part_levels(pos, tris, vertex_base, vertex_count, max_cell=np.inf):
    """The coarser levels of one part (``tris``: (n, 3) global vertex indices), or None if it gains nothing or its
    finest level's cell (in the part's units) would be larger than ``max_cell``."""
    if len(tris) < MIN_TRIANGLES or vertex_count <= 0:
        return None
    if int(tris.min()) < vertex_base or int(tris.max()) >= vertex_base + vertex_count:
        return None             # the part shares vertices outside its own range
    local = pos[vertex_base:vertex_base + vertex_count]
    sample = tris[::max(1, len(tris) // 20000)]
    cell = 2.0 * float(np.median(np.linalg.norm(pos[sample[:, 0]] - pos[sample[:, 1]], axis=1)))
    if not np.isfinite(cell) or cell <= 0.0 or cell > max_cell:
        return None
    q = np.floor((local - local.min(0)) / cell).astype(np.int64)
    if q.size == 0 or int(q.max()) >= 1 << _BITS:
        return None
    t_local = tris - vertex_base
    cur, cells, out = tris, [], []
    for k in range(LEVELS):
        qk = q >> k
        key = (qk[:, 0] << (2 * _BITS)) | (qk[:, 1] << _BITS) | qk[:, 2]
        _, first, inverse = np.unique(key, return_index=True, return_inverse=True)
        t = inverse.reshape(-1)[t_local]
        t = t[(t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])]
        n = len(first)
        if n < (1 << _BITS) and len(t):
            _, keep = np.unique(_triangle_keys(t, n), return_index=True)
            t = t[np.sort(keep)]
        if len(t) >= MIN_KEEP and len(t) < MIN_GAIN * len(cur):
            cur = (first + vertex_base)[t].astype(np.uint32).reshape(-1)
            cur_cell = cell * (1 << k)
        elif not out:
            return None
        else:
            cur_cell = cells[-1]
        cells.append(cur_cell)
        out.append(cur)
        cur = cur.reshape(-1, 3)
    return PartLod(np.array(cells), [o.reshape(-1) for o in out])


def build(model, check=None):
    """{part id: PartLod} for the parts of ``model`` that gain from coarser levels. Textured parts are left alone
    (clustering would smear their texture across seams), and so is an animated model (its vertices move)."""
    if model.anim_vertices is not None or model.vertices is None:
        return {}
    pos = model.vertices[:, :3]
    pixel = float(np.linalg.norm(np.asarray(model.bounds_max) - np.asarray(model.bounds_min))) / REFERENCE_PIXELS

    def one(p):
        tris = model.indices[p.first:p.first + p.count].reshape(-1, 3).astype(np.int64)
        scale = float(np.max(np.linalg.norm(model.part_matrix(p)[:3, :3], axis=0)))
        return part_levels(pos, tris, p.vertex_base, p.vertex_count, pixel / max(scale, 1e-12))

    todo = []
    for p in model.parts:
        if check is not None:
            check()
        if p.count < 3 * MIN_TRIANGLES or p.look.texture is not None:
            continue
        todo.append(p)
    out = {}
    # Each part is independent and numpy's sorts release the GIL: a few workers cut the wait on big models.
    # Results are collected in part order, so the dict is the same as a serial build.
    workers = min(WORKERS, len(todo))
    if workers > 1:
        with ThreadPoolExecutor(workers) as pool:
            pending = deque()
            for p in todo:
                if check is not None:
                    check()
                pending.append((p, pool.submit(one, p)))
                while len(pending) > workers:       # bounded: parts in flight hold int64 copies of their triangles
                    q, future = pending.popleft()
                    lod = future.result()
                    if lod is not None:
                        out[q.id] = lod
            while pending:
                if check is not None:
                    check()
                q, future = pending.popleft()
                lod = future.result()
                if lod is not None:
                    out[q.id] = lod
        return out
    for p in todo:
        if check is not None:
            check()
        lod = one(p)
        if lod is not None:
            out[p.id] = lod
    return out
