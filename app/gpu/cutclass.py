"""Which side of the cut planes a box lies on: the CPU twin of cull_test.wgsl's cluster_clip_class.

A cut view discards the fragments on the removed side of the planes (clip.wgsl clipped()), which switches off early depth
rejection for everything drawn with that fragment shader. A box that lies wholly on the kept side can be drawn without the
discard, one wholly on the removed side need not be drawn at all, and only the boxes that may straddle a plane keep the
discard. The classes are conservative: a box is only called KEPT or REMOVED when every fragment it can produce provably is.

    KEPT       every fragment is on the kept side of the planes (or the part is never cut)
    STRADDLE   anything else, and anything not proved (morphed, animated, reaching the camera plane)
    REMOVED    every fragment is removed

What "every fragment" means. The visibility pass interpolates the world position at the pixel CENTRE (no centroid), so a pixel
the triangle covers only partly is clipped by a position extrapolated beyond the triangle. The box is therefore widened by
``PIXELS`` pixels of world size at its farthest point (``pixel_margin``): a fragment centre is never farther than that from the
triangle for any triangle not seen almost edge-on (80 degrees or more from the view plane), and the clip test is linear in the
position. Float32 rounding of the world position is covered by a relative margin (``MARGIN``).

The box is the part's local box (or a cluster's) taken through the part matrix of the frame, which carries the explode and node
offsets: the bound is the one that is drawn this frame. The planes are the frame's final planes (a flipped section is a
negated plane), so the flip flag and several sections need nothing extra: ``mode`` 0 removes where any enabled plane is negative,
mode 1 (a corner) where all enabled planes are.
"""
from __future__ import annotations

import numpy as np

KEPT, STRADDLE, REMOVED = 0, 1, 2
MARGIN = 3e-5               # relative to the magnitudes that enter the signed distance (cull_test.wgsl plane_range)
BOX_PAD = 2e-6              # the cluster box's rounding allowance (cull_test.wgsl cluster_box)
PIXELS = 128.0               # pixel-centre extrapolation allowance (cull_test.wgsl cluster_clip_class)


def box_world(lo, hi, mats):
    """(centre (n,3), axes (n,3,3) columns scaled by the half extents) of the boxes in world space."""
    lo = np.asarray(lo, np.float64).reshape(-1, 3)
    hi = np.asarray(hi, np.float64).reshape(-1, 3)
    mats = np.asarray(mats, np.float64).reshape(-1, 4, 4)
    c = (lo + hi) / 2
    h = (hi - lo) / 2 + BOX_PAD * (np.abs(c) + (hi - lo) / 2)
    wc = np.einsum("nij,nj->ni", mats[:, :3, :3], c) + mats[:, :3, 3]
    return wc, mats[:, :3, :3], h


def plane_bounds(wc, A, h, planes, on):
    """Static signed-distance bounds (n, k) of the boxes to the k enabled planes: (lowest, highest), rounding margin included."""
    lo_, hi_ = [], []
    for i in range(3):
        if not int(on[i]):
            continue
        P = np.asarray(planes[i], np.float64)
        s = wc @ P[:3] + P[3]
        ax = np.einsum("nij,i->nj", A, P[:3])                          # n . (column j of the matrix)
        r = (np.abs(ax) * h).sum(1)
        e = MARGIN * (np.abs(wc * P[:3]).sum(1) + abs(P[3]) + r)
        lo_.append(s - r - e)
        hi_.append(s + r + e)
    if not lo_:
        return np.zeros((len(wc), 0)), np.zeros((len(wc), 0))
    return np.stack(lo_, 1), np.stack(hi_, 1)


def pixel_margin(wc, A, h, view, tan_y, ortho, height):
    """World size of PIXELS pixels at the far end of each box (inf where the box reaches the camera plane)."""
    R = np.abs(np.linalg.norm(A, axis=1) * h).sum(1)                   # half diagonal bound
    if ortho:
        return np.full(len(wc), PIXELS * 2.0 * tan_y / height)
    depth = -(wc @ np.asarray(view, np.float64)[2, :3] + view[2, 3])
    ok = depth - R > 1e-4
    return np.where(ok, PIXELS * 2.0 * tan_y * (depth + R) / height, np.inf)


def classes_from_bounds(dlo, dhi, plane_len, margin, mode, straddle=None, never_cut=None):
    """Classes from the static bounds, the planes' normal lengths (k,) and the per-box world margin (n,)."""
    n = len(dlo)
    out = np.zeros(n, np.uint8)
    if dlo.shape[1] == 0:
        return out
    with np.errstate(invalid="ignore"):
        m = margin[:, None] * np.asarray(plane_len)[None, :]
        kept = dlo - m >= 0.0
        gone = dhi + m < 0.0
    kept &= np.isfinite(m)
    gone &= np.isfinite(m)
    out[:] = STRADDLE
    if int(mode) == 1:
        out[kept.any(1)] = KEPT
        out[~kept.any(1) & gone.all(1)] = REMOVED
    else:
        out[kept.all(1)] = KEPT
        out[gone.any(1)] = REMOVED
    if straddle is not None:
        out[np.asarray(straddle, bool)] = STRADDLE
    if never_cut is not None:
        out[np.asarray(never_cut, bool)] = KEPT
    return out


def classify_boxes(lo, hi, mats, planes, on, mode, view, tan_y, ortho, height, straddle=None, never_cut=None):
    """Class of every box. lo, hi: (n, 3) local box corners; mats: (n, 4, 4) world = M @ (p, 1); planes: (3, 4) with the
    removed side dot(p, n) + d < 0; on: three flags; mode: 0 any plane removes, 1 corner; view: the 4x4 view matrix, tan_y:
    tan(half fov y) (half height when orthographic), height: render height in pixels. ``straddle`` (n,) bool forces STRADDLE
    (morphed / animated parts), ``never_cut`` (n,) bool forces KEPT. Returns (n,) uint8."""
    wc, A, h = box_world(lo, hi, mats)
    if not any(int(x) for x in on) or len(wc) == 0:
        return np.zeros(len(wc), np.uint8)
    dlo, dhi = plane_bounds(wc, A, h, planes, on)
    plen = [float(np.linalg.norm(np.asarray(planes[i], np.float64)[:3])) for i in range(3) if int(on[i])]
    return classes_from_bounds(dlo, dhi, plen, pixel_margin(wc, A, h, view, tan_y, ortho, height), mode, straddle, never_cut)
