"""What the whole-body renderer has to send to the GPU in a frame.

The atlas keeps every structure in one vertex buffer and one index buffer. Drawing the whole index buffer in each
pass costs the same whatever is on screen, so the renderer asks this module which structures a pass can touch and
draws only their index ranges, in buffer order.

The answer is always a superset of what the shaders would keep: the vertex shader still tests visibility, opacity
and selection for every vertex it is given, and the GPU still clips. A structure is left out only when it cannot
produce a pixel in that pass (hidden, wrong pass, wholly outside the view, wholly cut away), and what is left is
drawn in the same order as before, so the picture is the same to the last bit.

Nothing here needs OpenGL. DrawRanges.build returns None when the layout of a dataset cannot be proved (index
ranges that overlap or leave gaps, vertices of a structure that are not one block tagged with its id); the renderer
then draws the whole buffer as it always did.
"""
from __future__ import annotations

import numpy as np

VERTEX_STRIDE = 28            # "3f 3f u2 u2": position, normal, structure id, material id
OBJ_OFFSET = 24
OPAQUE_ALPHA = 0.995          # GEOMETRY_VS: transparent = alpha < 0.995
ALPHA_BAND = 1e-4             # a structure this close to the limit goes to both passes; the shader decides
F_VISIBLE, F_GHOST, F_SELECTED, F_NOCLIP = 1, 2, 4, 64
REL_TOL = 1e-5                # about 40 x the rounding of a float32 matrix product

# the six sides of the view volume as rows applied to the view-projection matrix: a point is beyond a side when
# (side @ vp) @ (x, y, z, 1) > 0, that is x > w, -x > w, y > w, -y > w, z > w, -z > w
_SIDES = np.array([[s if a == k else 0.0 for k in range(3)] + [-1.0] for a in range(3) for s in (1.0, -1.0)])


class DrawRanges:
    def __init__(self):
        self.n = 0
        self.first = self.count = None            # per structure, in indices
        self.order = None                         # structures that have triangles, in index-buffer order
        self.sorted_first = self.sorted_end = None
        self.box_min = self.box_max = None        # float64 (n, 3), from the vertex buffer itself
        self.box_ok = None                        # finite box: may be tested against the view
        self.center = self.half = None            # of the boxes, (n, 3)
        self.extent = None                        # largest |coordinate| per axis over all boxes, and 1 for w
        self.alpha_min = self.alpha_max = None    # material alpha range over the structure's vertices
        self.triangles = 0

    # ------------------------------------------------------------------ load
    @classmethod
    def build(cls, structures, materials, vertices, indices):
        """Ranges, boxes and material alphas for a dataset, or None when its layout cannot be proved."""
        try:
            return cls._build(structures, materials, vertices, indices)
        except Exception:               # noqa: BLE001 - any doubt about the layout means: draw the whole buffer
            return None

    @classmethod
    def _build(cls, structures, materials, vertices, indices):
        n = len(structures)
        vb = np.frombuffer(vertices, dtype=np.uint8)
        ib = np.frombuffer(indices, dtype=np.uint8)
        if n == 0 or len(vb) % VERTEX_STRIDE or len(ib) % 4 or not len(vb) or not len(ib):
            return None
        nv = len(vb) // VERTEX_STRIDE
        idx = ib.view("<u4")
        first = np.array([s["i_start"] for s in structures], dtype=np.int64)
        count = np.array([s["i_count"] for s in structures], dtype=np.int64)
        if (count < 0).any() or (count % 3).any() or (first < 0).any():
            return None
        order = np.flatnonzero(count > 0)
        order = order[np.argsort(first[order], kind="stable")]
        if not len(order):
            return None
        f, c = first[order], count[order]
        # the ranges must tile the index buffer exactly: no gap (it would not be drawn), no overlap (drawn twice)
        if f[0] != 0 or f[-1] + c[-1] != len(idx) or (f[1:] != f[:-1] + c[:-1]).any():
            return None

        # runs of vertices that share a structure id and a material (a muscle and its tendon are two materials)
        tag = np.ndarray((nv,), dtype="<u4", buffer=vb, offset=OBJ_OFFSET, strides=(VERTEX_STRIDE,))
        starts = np.concatenate(([0], np.flatnonzero(tag[1:] != tag[:-1]) + 1))
        if len(starts) > max(64 * n + 1024, nv // 8):
            return None
        ends = np.concatenate((starts[1:], [nv]))
        run_obj = (tag[starts] & 0xFFFF).astype(np.int64)
        run_mat = (tag[starts] >> 16).astype(np.int64)
        if run_obj.max() >= n or run_mat.max() >= len(materials):
            return None
        v_lo = np.full(n, nv, dtype=np.int64)
        v_hi = np.zeros(n, dtype=np.int64)
        v_len = np.zeros(n, dtype=np.int64)
        np.minimum.at(v_lo, run_obj, starts)
        np.maximum.at(v_hi, run_obj, ends)
        np.add.at(v_len, run_obj, ends - starts)
        has_v = v_len > 0
        if (v_hi[has_v] - v_lo[has_v] != v_len[has_v]).any():      # a structure's vertices are not one block
            return None
        # every index of a structure's range must point into that structure's own block of vertices
        i_min = np.minimum.reduceat(idx, f)
        i_max = np.maximum.reduceat(idx, f)
        if not has_v[order].all() or (i_min < v_lo[order]).any() or (i_max >= v_hi[order]).any():
            return None

        self = cls()
        self.n, self.first, self.count, self.order = n, first, count, order
        self.sorted_first, self.sorted_end = f, f + c
        self.triangles = int(c.sum() // 3)
        alpha = np.array([m["alpha"] for m in materials], dtype=np.float32)[run_mat]
        self.alpha_min = np.full(n, np.inf, dtype=np.float32)
        self.alpha_max = np.full(n, -np.inf, dtype=np.float32)
        np.minimum.at(self.alpha_min, run_obj, alpha)
        np.maximum.at(self.alpha_max, run_obj, alpha)

        # boxes from the positions that are drawn (the blocks tile the vertex buffer in v_lo order)
        blocks = np.flatnonzero(has_v)
        blocks = blocks[np.argsort(v_lo[blocks], kind="stable")]
        pos = np.ndarray((nv, 3), dtype="<f4", buffer=vb, offset=0, strides=(VERTEX_STRIDE, 4))
        self.box_min = np.zeros((n, 3))
        self.box_max = np.zeros((n, 3))
        self.box_min[blocks] = np.minimum.reduceat(pos, v_lo[blocks], axis=0)
        self.box_max[blocks] = np.maximum.reduceat(pos, v_lo[blocks], axis=0)
        self._finish_boxes(has_v)
        return self

    def _finish_boxes(self, has_v):
        ok = has_v & np.isfinite(self.box_min).all(axis=1) & np.isfinite(self.box_max).all(axis=1)
        self.box_ok = ok
        lo = np.where(ok[:, None], self.box_min, 0.0)
        hi = np.where(ok[:, None], self.box_max, 0.0)
        self.center = (lo + hi) * 0.5
        self.half = (hi - lo) * 0.5
        ext = np.maximum(np.abs(lo).max(axis=0), np.abs(hi).max(axis=0)) if ok.any() else np.zeros(3)
        self.extent = np.append(ext, 1.0)

    # ------------------------------------------------------------------ frame
    def _least(self, rows):
        """Smallest value of rows @ (x, y, z, 1) over each structure's box: (n, len(rows))."""
        return self.center @ rows[:, :3].T + rows[:, 3] - self.half @ np.abs(rows[:, :3]).T

    def outside_view(self, vp):
        """True for structures whose box lies wholly beyond one side of the view volume (-w <= x, y, z <= w)."""
        vp = np.asarray(vp, dtype=np.float64)
        rows = _SIDES @ vp
        tol = REL_TOL * (np.abs(_SIDES) @ (np.abs(vp) @ self.extent)) + 1e-12   # from the largest sum of |terms|
        return (self._least(rows) > tol).any(axis=1) & self.box_ok

    def cut_away(self, clip, flags):
        """True for structures a section removes completely (shaders.clipped is true at every point of the box)."""
        planes = np.asarray(clip[0], dtype=np.float32).astype(np.float64).reshape(-1, 4)
        mode = int(clip[2]) if len(clip) > 2 else 0
        active = [i for i in range(min(3, len(planes))) if int(clip[1][i]) == 1]
        if not active:
            return np.zeros(self.n, dtype=bool)
        rows = -planes[active]                                       # removed where plane @ p < 0
        tol = REL_TOL * (np.abs(rows) @ self.extent) + 1e-9
        gone = self._least(rows) > tol
        gone = gone.all(axis=1) if mode == 1 else gone.any(axis=1)
        return gone & self.box_ok & ((np.asarray(flags) & F_NOCLIP) == 0)

    def classify(self, flags, opacity, ghost_alpha):
        """(drawable, may be opaque, may be transparent, selected) per structure, from the state texture's values."""
        flags = np.asarray(flags, dtype=np.int64)
        opacity = np.asarray(opacity, dtype=np.float32)
        live = ((flags & F_VISIBLE) != 0) & (self.count > 0)
        a0, a1 = self.alpha_min * opacity, self.alpha_max * opacity
        lo, hi = np.minimum(a0, a1), np.maximum(a0, a1)
        ghost = (flags & F_GHOST) != 0
        g = np.float32(ghost_alpha)
        lo = np.where(ghost, np.minimum(lo, g), lo)
        hi = np.where(ghost, np.minimum(hi, g), hi)
        # not (x < limit) rather than x >= limit: a NaN alpha is opaque in the shader too
        return (live, ~(hi < OPAQUE_ALPHA - ALPHA_BAND), ~(lo >= OPAQUE_ALPHA + ALPHA_BAND),
                (flags & F_SELECTED) != 0)

    def passes(self, flags, opacity, ghost_alpha, vp=None, clip=None):
        """Boolean masks (opaque, transparent, selection mask) of the structures each pass has to be given.

        flags, opacity: per structure, as packed for the state texture (row 0 alpha, row 1 red).
        vp, clip: leave out to skip the view test or the section test (an animated model moves its vertices).
        """
        live, opaque, transparent, selected = self.classify(flags, opacity, ghost_alpha)
        if vp is not None:
            live = live & ~self.outside_view(vp)
        if clip is not None:
            live = live & ~self.cut_away(clip, flags)
        return live & opaque, live & transparent, live & selected

    def runs(self, mask):
        """(first index, index count) of the draws for the structures in mask: neighbours in the buffer are joined."""
        m = mask[self.order]
        edge = np.diff(np.concatenate(([False], m, [False])).astype(np.int8))
        start, stop = np.flatnonzero(edge == 1), np.flatnonzero(edge == -1)
        first = self.sorted_first[start]
        return first, self.sorted_end[stop - 1] - first

    @staticmethod
    def bridge(first, count, limit):
        """At most `limit` draws: the smallest gaps are drawn through (the shader rejects what lies in them)."""
        if len(first) <= limit:
            return first, count
        end = first + count
        gaps = first[1:] - end[:-1]
        keep = np.sort(np.argsort(gaps, kind="stable")[len(gaps) - (limit - 1):])     # the largest gaps stay gaps
        start = np.concatenate(([0], keep + 1))
        stop = np.concatenate((keep, [len(first) - 1]))
        return first[start], end[stop] - first[start]

    @staticmethod
    def commands(first, count):
        """glMultiDrawElementsIndirect records: count, instances, first index, base vertex, base instance."""
        cmd = np.zeros((len(first), 5), dtype="<u4")
        cmd[:, 0], cmd[:, 1], cmd[:, 2] = count, 1, first
        return cmd
