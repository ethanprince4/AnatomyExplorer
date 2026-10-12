"""The frame's draw list from per-part arrays (numpy only, no GPU object): which parts a frame draws, in which order,
and the rows of the draw table (tables.wgsl, DRAW_FLOATS floats per draw slot).

The renderer used to walk the model's parts in Python on every frame (a visibility test, a level lookup, a sort tuple
and about ten row writes per part). Here the per-part facts live in arrays: PartStatics for what is fixed while a model
is on the GPU, and the functions below turn the frame's state (shown items, x-ray, opacity, chosen levels, transforms,
look records) into the same table with array operations. renderer.py keeps the result and reuses it while its inputs
are unchanged (FrameDraws.same).

Draw order: by the GL renderer's index-buffer span start of the drawn level, then by part index (geometry.gl_order_keys).
A draw of more than 2**bits triangles is split over consecutive slots; a visibility id is (slot << bits) | primitive.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

DRAW_FLOATS = 40
DRAW_NOCLIP, DRAW_MIRRORED, DRAW_SELECTED = 1, 2, 4
XF_FLOATS = 28                           # of a row: the model matrix (16, column major), then the normal matrix (3 x vec4)


class SlotError(RuntimeError):
    """The frame's draw slots do not fit a 32-bit visibility id (args[0]: the slot count at 8 primitive bits)."""


class PartStatics:
    """Per part, fixed while a model is on the GPU. ``first`` / ``count`` / ``key`` are (parts, levels): the index range
    and the GL order key of every level, level 0's where a part has no such level (the renderer falls back to it)."""

    def __init__(self, parts, geom):
        n = len(parts)
        levels = max([1] + [len(r) for r in geom.ranges[:n]] + [len(k) for k in geom.gl_keys[:n]])
        self.n, self.levels = n, levels
        self.index_of = {p.id: i for i, p in enumerate(parts)}
        self.item = np.fromiter((p.item for p in parts), dtype=np.int64, count=n)
        self.page = np.asarray(geom.page_of, dtype=np.int64).reshape(-1)[:n].copy()
        self.first = np.zeros((n, levels), dtype=np.int64)
        self.count = np.zeros((n, levels), dtype=np.int64)
        self.key = np.zeros((n, levels), dtype=np.int64)
        for i in range(n):
            rng, keys = geom.ranges[i], geom.gl_keys[i]
            for k in range(levels):
                self.first[i, k], self.count[i, k] = rng[k] if k < len(rng) else rng[0]
                self.key[i, k] = keys[k] if k < len(keys) else keys[0]
        anim = getattr(geom, "anim_base", None)
        self.anim = (np.asarray(anim).reshape(-1)[:n] >= 0) if anim is not None else np.zeros(n, dtype=bool)
        # app.viewer.renderer._transparent_pass, the part's own share: a covering or a translucent look
        self.see_through = np.fromiter((p.role == "covering" or bool(p.look.translucent) for p in parts), dtype=bool, count=n)


def split_parts(ps, vis, ghost, alpha, opaque_materials, inside):
    """(opaque part indices, translucent part indices) of a frame, each in model order: a part is drawn when its item is
    shown and its bounding sphere is in the frustum (``inside``, per part); it takes the translucent pass when its item is
    x-rayed or below full opacity, or (unless materials are forced opaque) it is a covering or has a translucent look."""
    it = ps.item
    keep = np.asarray(vis)[it].astype(bool) & np.asarray(inside, dtype=bool).reshape(-1)
    through = np.asarray(ghost)[it].astype(bool) | (np.asarray(alpha)[it].astype(np.float64) < 0.999)
    if not opaque_materials:
        through = through | ps.see_through
    return np.flatnonzero(keep & ~through), np.flatnonzero(keep & through)


def order_draws(ps, draw_idx, level):
    """(part index, level, first index, index count) of the opaque draws in draw order. ``level`` is the chosen level of
    every part of the model. Parts without geometry on a page or with less than a triangle at that level are dropped."""
    idx = np.asarray(draw_idx, dtype=np.int64).reshape(-1)
    k = np.asarray(level, dtype=np.int64)[idx]
    kk = np.where(k < ps.levels, k, 0)
    first, count = ps.first[idx, kk], ps.count[idx, kk]
    ok = (count >= 3) & (ps.page[idx] >= 0)
    idx, k, kk, first, count = idx[ok], k[ok], kk[ok], first[ok], count[ok]
    o = np.lexsort((idx, ps.key[idx, kk]))
    return idx[o], k[o], first[o], count[o]


def pick_bits(tris, bits_max):
    """(primitive bits, slots per draw, slot count): the most primitive bits (at most bits_max, at least 8) with which
    every slot, slot 0 included, keeps bit 31 of the id clear (the culler's ids own that bit)."""
    bits = int(bits_max)
    while True:
        per = -(-tris // (1 << bits))
        n_slots = int(per.sum())
        if n_slots + 1 <= (1 << (31 - bits)):
            return bits, per, n_slots
        bits -= 1
        if bits < 8:
            raise SlotError(n_slots)


@dataclass
class FrameDraws:
    """One built draw table and everything read off it, kept by the renderer until an input changes."""
    sig: np.ndarray                      # (4, n): part index, level, selected, look record of the draws, in draw order
    scalars: tuple                       # the inputs that are not per draw (see WgpuRenderer._build_table)
    xf: object                           # the transform state the rows were built from (identity)
    table: np.ndarray                    # (slots + 1, DRAW_FLOATS) float32
    entries: list                        # [(slot, part index, level, first index, index count)]
    bits: int
    feat: int = 0
    slot0: np.ndarray = None             # (n,) first slot of each draw
    tex_slots: list = field(default_factory=lambda: [0])    # the shade-pass texture slots the table uses, 0 first
    drawn_tris: int = 0
    parts: object = None                 # the culler's FrameParts and the part index list, built when first asked for
    plain: tuple = (None, None)          # (positions bytes, entries of those draws): the culler's unculled draws
    cut_parts: tuple = None              # sorted part indices (the key of the cut classification)

    def same(self, sig, scalars, xf):
        return self.xf is xf and self.scalars == scalars and self.sig.shape == sig.shape and bool(np.array_equal(self.sig, sig))


def build_rows(idx, k, first, count, bits_max, xrow, item, page, flags, weight, rec, tex_slot):
    """(table, entries, bits, first slot of each draw). Every argument after ``bits_max`` is per draw, in draw order: the
    XF_FLOATS transform floats, item, page, DRAW_* flags, morph weight, looks-table record and shade-pass texture slot."""
    tris = count // 3
    bits, per, n_slots = pick_bits(tris, bits_max)
    cap = 1 << bits
    start = np.cumsum(per) - per                       # row (slot - 1) of each draw's first slot
    rows = np.repeat(np.arange(len(idx), dtype=np.int64), per)
    a = (np.arange(n_slots, dtype=np.int64) - start[rows]) * cap       # first triangle of the slot within its draw
    n = np.minimum(cap, tris[rows] - a)
    table = np.zeros((n_slots + 1, DRAW_FLOATS), dtype=np.float32)
    body = table[1:]
    bu = body.view(np.uint32)
    e_first = first[rows] + 3 * a
    e_part, e_level = idx[rows], k[rows]
    body[:, 0:XF_FLOATS] = xrow[rows]
    bu[:, 28] = e_first
    bu[:, 30] = n
    bu[:, 31] = page[rows]
    bu[:, 32] = e_part
    bu[:, 33] = item[rows]
    bu[:, 34] = flags[rows]
    bu[:, 35] = e_level
    body[:, 36] = weight[rows]
    bu[:, 37] = rec[rows]
    bu[:, 38] = tex_slot[rows]
    entries = list(zip(range(1, n_slots + 1), e_part.tolist(), e_level.tolist(), e_first.tolist(), (3 * n).tolist()))
    return table, entries, bits, start + 1
