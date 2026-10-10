"""Quantised vertex positions for compressed geometry (stage 2, see geometry.py and wgsl/geom.wgsl g_pos).

The vertices of a part are stored in first-use order (stage 1). Every block of 64 consecutive vertices gets its own fixed-point
grid per axis: step 2^k (a power of two), origin mn = a multiple of the step, and q = round((p - mn) / step) in
``bits`` bits (bits = bit length of the largest q, 0 for a flat axis). The decode is mn + float(q) * step. Because the step
is a power of two and |mn| and |mn + q * step| stay below 2^24 steps, that sum is exactly representable in float32, so the GPU
result is the grid value itself, with or without fused multiply-add and the same on the CPU. The error of a vertex is therefore
exactly |stored float32 position - grid value| (zero where the stored value lies on the grid; at most step / 2 otherwise).

A block is kept as float32 (flag in its table entry) when its error would exceed the budget, when it needs more than 24 bits
on an axis, when its 3 axes together need 96 bits or more, or when it holds a non-finite value.

The error budget is a length in PART space: ``budget_part_space`` takes the world length that is 1/16 pixel (ANATOMY_GEOM_QERR
pixels) at the closest zoom the viewer allows on the model (app/viewer/camera.py OrbitCamera.min_distance, the perspective
camera at the viewer's field of view, 2560 x 1600) and divides it by the largest scale of the part's matrix.

Block table entry (6 words, section posb, one per 64 vertices of the page): word 0 = first word of the block's data in the posq
section; word 1 = bx | by << 5 | bz << 10 (bits per axis), bit 31 set = the block is float32 (3 x 64 float words at word 0);
words 2..4 = origin mn (float32 bits); word 5 = biased float32 exponent of the step per axis, x | y << 8 | z << 16.
Block data: vertex j, axis a is the field at bit j * (bx + by + bz) + (bits of the axes before a), LSB first (so a block takes
2 * (bx + by + bz) words).
"""
from __future__ import annotations

import math
import os

import numpy as np

BLOCK = 64
TABLE_WORDS = 6
FLOAT_FLAG = 0x80000000
MAX_BITS = 24
K_MIN = -100                      # the smallest step exponent (keeps steps and products clear of denormals)
_CHUNK = 1 << 15                  # blocks per vectorised step

QERR_DEFAULT = 1.0 / 256.0        # pixels at the closest zoom (1/16 px was tried: ref images differ by mean 0.04/255, see s2.HANDOFF.md)


def qerr_pixels():
    try:
        v = float(os.environ.get("ANATOMY_GEOM_QERR", ""))
        return v if v > 0 else QERR_DEFAULT
    except ValueError:
        return QERR_DEFAULT


def world_per_pixel_closest(model, width=2560, height=1600, fov=39.597753):
    """World length of one pixel at the closest zoom the viewer allows on ``model`` (the smaller of the perspective and
    the orthographic camera). Assumes the target surface is at the camera distance OrbitCamera.min_distance; geometry nearer than
    that (down to the near plane, 0.2 x distance) is magnified by up to 5x."""
    from app.viewer.camera import OrbitCamera
    cam = OrbitCamera(fov=fov)
    try:
        lo, hi = model.world_bounds(visible_only=False)
    except Exception:
        lo, hi = getattr(model, "bounds_min", None), getattr(model, "bounds_max", None)
        if lo is None:
            v = np.asarray(model.vertices[:, 0:3])
            lo, hi = v.min(0), v.max(0)
    cam.set_scene(lo, hi)
    aspect = width / height
    cam.distance = cam.min_distance
    persp = cam.world_per_pixel(height, aspect)
    cam.ortho = True
    cam.ortho_width = cam.min_distance
    return float(min(persp, cam.world_per_pixel(height, aspect))), float(cam.min_distance)


def part_scales(model, geo_ids):
    """Largest singular value of every part's 3x3 matrix (rest pose), 1.0 where it cannot be read."""
    out = {}
    for i in geo_ids:
        s = 1.0
        try:
            m = np.asarray(model.part_matrix(model.parts[i]), dtype=np.float64)[:3, :3]
            s = float(np.linalg.svd(m, compute_uv=False)[0])
            if not math.isfinite(s) or s <= 0:
                s = 1.0
        except Exception:
            pass
        out[i] = s
    return out


def budget_part_space(model, geo_ids, pixels=None):
    """{part index: allowed error in part space}. Also returns (world per pixel, min distance) for reports."""
    pixels = qerr_pixels() if pixels is None else float(pixels)
    wpp, dmin = world_per_pixel_closest(model)
    sc = part_scales(model, geo_ids)
    return {i: wpp * pixels / sc[i] for i in geo_ids}, (wpp, dmin)


def _exp_floor_log2(x):
    """floor(log2(x)) for x > 0 (exact for float64 inputs)."""
    m, e = math.frexp(x)
    return e - 1


def _data_grid(p32):
    """(nb, 3) int64: per block and axis the exponent k such that every nonzero value of the block is a multiple of 2^k (the
    finest bit that is set in any mantissa); 1000 where the axis is all zero."""
    u = np.ascontiguousarray(p32).view(np.uint32).astype(np.int64)
    ex = (u >> 23) & 255
    m = (u & 0x7FFFFF) | (1 << 23)
    low = m & (-m)
    tz = np.log2(low.astype(np.float64)).astype(np.int64)
    t = ex - 127 - 23 + tz
    t = np.where(ex == 0, -149, t)
    t = np.where((u & 0x7FFFFFFF) == 0, 1000, t)
    return t.min(axis=1)


def _eval_grid(p, mn32, k):
    """Quantise blocks p (nb, 64, 3) float64 onto the grid mn + q * 2^k (mn: float32 block minimum): bits per axis, and the
    exact error of the float32 decode  mn + float(q) * 2^k  (q * 2^k is exact, the sum is one IEEE rounding)."""
    s = np.exp2(k.astype(np.float64))
    q = np.maximum(np.rint((p - mn32[:, None, :].astype(np.float64)) / s[:, None, :]), 0.0)
    rng = q.max(1)
    bits = np.where(rng > 0, np.floor(np.log2(np.maximum(rng, 1.0))) + 1, 0).astype(np.int64)
    with np.errstate(over="ignore", invalid="ignore"):
        dec = mn32[:, None, :] + q.astype(np.float32) * s.astype(np.float32)[:, None, :]
        err = np.abs(dec.astype(np.float64) - p).max(axis=(1, 2))
    return bits, np.where(np.isnan(err), np.inf, err)


def _quantise_chunk(pos, budget):
    """pos (nb, 64, 3) float32 -> (bits (nb,3) int64, k (nb,3) int64, mn (nb,3) float32, ok (nb,) bool, err (nb,) float64).

    The grid of an axis is anchored at the block's float32 minimum. First try the coarsest step the budget allows (2^kb with
    kb = floor(log2(2 * budget)), not finer than the data's own grid); if the float32 decode then misses the budget (the sum
    rounds), use the data's own grid: every value is then hit exactly (error 0)."""
    finite = np.isfinite(pos).all(axis=(1, 2))
    p32 = np.where(np.isfinite(pos), pos, np.float32(0)).astype(np.float32)
    p = p32.astype(np.float64)
    mn32 = p32.min(1)
    kb = _exp_floor_log2(2.0 * budget) if budget > 0 else K_MIN
    kd = _data_grid(p32)
    kd = np.where(kd >= 1000, kb, kd)
    k_data = np.clip(kd, K_MIN, 100)
    k_c = np.clip(np.maximum(kb, kd), K_MIN, 100)
    bits, err = _eval_grid(p, mn32, k_c)
    ok = finite & (bits.max(1) <= MAX_BITS) & (err <= budget)
    k = k_c
    redo = np.nonzero(finite & ~ok & (k_data != k_c).any(axis=1))[0]
    if len(redo):
        b2, e2 = _eval_grid(p[redo], mn32[redo], k_data[redo])
        ok2 = (b2.max(1) <= MAX_BITS) & (e2 <= budget)
        bits = bits.copy(); err = err.copy(); k = k.copy()
        bits[redo[ok2]] = b2[ok2]; err[redo[ok2]] = e2[ok2]; k[redo[ok2]] = k_data[redo[ok2]]
        ok[redo[ok2]] = True
    return bits, k, mn32, ok, err


def _blocks_of(pos):
    """(n, 3) float32 -> (nb, 64, 3), the missing vertices of the last block repeat the last vertex."""
    n = len(pos)
    nb = -(-n // BLOCK)
    pad = nb * BLOCK - n
    if pad:
        pos = np.concatenate([pos, np.repeat(pos[-1:], pad, axis=0)])
    return pos.reshape(nb, BLOCK, 3)


def plan_part(pos, budget):
    """Choose the grid of every block of a part (pos: (n, 3) float32 in first-use order). Returns
    (table (nb, 6) uint32 with word 0 relative to the part's data, words (data words of the part), err_max (realised
    maximum error in part space over the quantised blocks), counts dict)."""
    blocks = _blocks_of(np.ascontiguousarray(pos, dtype=np.float32))
    nb = len(blocks)
    table = np.zeros((nb, TABLE_WORDS), dtype=np.uint32)
    nwords = np.zeros(nb, dtype=np.int64)
    err_max = 0.0
    n_float = 0
    for a in range(0, nb, _CHUNK):
        b = min(a + _CHUNK, nb)
        bits, k, mn, ok, err = _quantise_chunk(blocks[a:b], budget)
        t = table[a:b]
        S = bits.sum(1)
        t[:, 1] = (bits[:, 0] | (bits[:, 1] << 5) | (bits[:, 2] << 10)).astype(np.uint32)
        t[:, 2:5] = mn.view(np.uint32)
        t[:, 5] = ((k[:, 0] + 127).astype(np.uint32) | ((k[:, 1] + 127).astype(np.uint32) << 8)
                   | ((k[:, 2] + 127).astype(np.uint32) << 16))
        nwords[a:b] = np.where(ok, 2 * S, 192)
        if (~ok).any():
            fl = ~ok
            t[fl, 1] = np.uint32(FLOAT_FLAG)
            t[fl, 2:6] = 0
            n_float += int(fl.sum())
        if ok.any():
            err_max = max(err_max, float(err[ok].max()))
    off = np.concatenate([[0], np.cumsum(nwords)[:-1]]).astype(np.int64)
    if off.size and int(off[-1] + nwords[-1]) >= (1 << 32):
        raise ValueError("a part's quantised positions exceed 2^32 words")
    table[:, 0] = off.astype(np.uint32)
    return table, int(nwords.sum()), err_max, {"blocks": nb, "float_blocks": n_float}


def encode_part(pos, table):
    """The data words (uint32) of a part planned by plan_part."""
    blocks = _blocks_of(np.ascontiguousarray(pos, dtype=np.float32))
    nb = len(blocks)
    w1 = table[:, 1]
    isf = (w1 & np.uint32(FLOAT_FLAG)) != 0
    bits = np.stack([w1 & 31, (w1 >> 5) & 31, (w1 >> 10) & 31], axis=1).astype(np.int64)
    S = bits.sum(1)
    nwords = np.where(isf, 192, 2 * S)
    total = int(nwords.sum())
    out = np.zeros(total, dtype=np.uint32)
    off = table[:, 0].astype(np.int64)
    for a in range(0, nb, _CHUNK):
        b = min(a + _CHUNK, nb)
        f = isf[a:b]
        if f.any():
            idx = np.nonzero(f)[0] + a
            for j, bi in enumerate(idx):          # (float blocks are rare)
                o = int(off[bi])
                out[o:o + 192] = blocks[bi].reshape(-1).view(np.uint32)
        qb = np.nonzero(~f)[0]
        if not len(qb):
            continue
        gi = qb + a
        mn = table[gi, 2:5].view(np.float32).astype(np.float64)
        ex = table[gi, 5].astype(np.int64)
        k = np.stack([ex & 255, (ex >> 8) & 255, (ex >> 16) & 255], axis=1) - 127
        s = np.exp2(k.astype(np.float64))
        p = blocks[gi].astype(np.float64)
        bq = bits[gi]
        rng = (1 << bq) - 1
        q = np.clip(np.rint((p - mn[:, None, :]) / s[:, None, :]), 0, rng[:, None, :]).astype(np.uint64)
        Sq = S[gi]
        cum = np.concatenate([np.zeros((len(gi), 1), np.int64), np.cumsum(bq, axis=1)[:, :2]], axis=1)
        j = np.arange(BLOCK, dtype=np.int64)
        bitpos = j[None, :, None] * Sq[:, None, None] + cum[:, None, :]
        w = off[gi][:, None, None] + (bitpos >> 5)
        sh = (bitpos & 31).astype(np.uint64)
        val = q << sh
        lo = (val & np.uint64(0xFFFFFFFF)).astype(np.float64).ravel()
        hi = (val >> np.uint64(32)).astype(np.float64).ravel()
        wf = w.ravel()
        base = int(off[gi[0]])
        top = int(off[gi[-1]] + 2 * Sq[-1]) + 1
        acc = np.bincount(wf - base, weights=lo, minlength=top - base)
        acc[1:] += np.bincount(wf - base, weights=hi, minlength=top - base)[:-1] if top - base > 1 else 0
        seg = acc[:top - base].astype(np.uint64).astype(np.uint32)
        # blocks of this chunk are not contiguous when float blocks sit between them: add (words are disjoint, so OR == add)
        wmin = int(w.min())
        L = int(w.max()) - wmin + 2
        wf = w.ravel() - wmin
        acc = np.bincount(wf, weights=lo, minlength=L) + np.bincount(wf + 1, weights=hi, minlength=L + 1)[:L]
        end = min(wmin + L, total)
        out[wmin:end] += acc[:end - wmin].astype(np.uint64).astype(np.uint32)       # (the words of different blocks are disjoint)
    return out


def decode_part(table, data, n):
    """numpy twin of geom.wgsl g_pos for the vertices 0..n-1 of one part (table: its (nb, 6) rows with word 0 relative to
    ``data``): (n, 3) float32."""
    nb = len(table)
    out = np.zeros((nb, BLOCK, 3), dtype=np.float32)
    w1 = table[:, 1]
    isf = (w1 & np.uint32(FLOAT_FLAG)) != 0
    for bi in np.nonzero(isf)[0]:
        o = int(table[bi, 0])
        out[bi] = data[o:o + 192].view(np.float32).reshape(BLOCK, 3)
    qi = np.nonzero(~isf)[0]
    for a in range(0, len(qi), _CHUNK):
        gi = qi[a:a + _CHUNK]
        bits = np.stack([w1[gi] & 31, (w1[gi] >> 5) & 31, (w1[gi] >> 10) & 31], axis=1).astype(np.int64)
        S = bits.sum(1)
        cum = np.concatenate([np.zeros((len(gi), 1), np.int64), np.cumsum(bits, axis=1)[:, :2]], axis=1)
        j = np.arange(BLOCK, dtype=np.int64)
        bitpos = j[None, :, None] * S[:, None, None] + cum[:, None, :]
        w = table[gi, 0].astype(np.int64)[:, None, None] + (bitpos >> 5)
        sh = (bitpos & 31).astype(np.uint64)
        nbits = np.broadcast_to(bits[:, None, :], bitpos.shape).astype(np.uint64)
        pad = np.concatenate([data, np.zeros(2, np.uint32)])
        v = pad[w].astype(np.uint64) | (pad[w + 1].astype(np.uint64) << np.uint64(32))
        q = (v >> sh) & ((np.uint64(1) << nbits) - np.uint64(1))
        ex = table[gi, 5].astype(np.int64)
        k = np.stack([ex & 255, (ex >> 8) & 255, (ex >> 16) & 255], axis=1) - 127
        step = np.exp2(k.astype(np.float64)).astype(np.float32)
        mn = table[gi, 2:5].view(np.float32)
        out[gi] = mn[:, None, :] + q.astype(np.float32) * step[:, None, :]
    return out.reshape(-1, 3)[:n]
