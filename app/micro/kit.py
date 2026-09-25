"""Shared building blocks for the high-resolution microanatomy models."""
import math

import numpy as np
from scipy.spatial import cKDTree

from .base import Part
from .cells import poisson_disk, sample_surface
from .geometry import Mesh, slab, smooth_path, tube
from .sdf import (Volume, box as box_shape, capsule, ellipsoid, fbm2, layer_y, round_cone,  # noqa: F401
                  sphere)

HF_RES = 250          # height-field layers: samples along the long side of the block


def const(v):
    return lambda X, Z: np.full(np.broadcast(np.asarray(X), np.asarray(Z)).shape, float(v))


def fn(v):
    return v if callable(v) else const(v)


def hlayer(name, group, color, bottom, top, desc, category="organ", x=(-1.0, 1.0), z=(-0.6, 0.6), res=HF_RES,
           bulk=False, clip=True, rank=0.0, alpha=1.0, label=True, detail=None):
    """A closed tissue layer between two height functions y(x, z)."""
    mesh = slab(x[0], x[1], z[0], z[1], fn(top), fn(bottom), res)
    return Part(name, group, color, mesh, desc, alpha=alpha, category=category, bulk=bulk, clip=clip, rank=rank,
                label=label, detail=detail)


def at(f, x, z):
    return float(np.asarray(f(np.array(x, float), np.array(z, float))))


class Bumps:
    """Sum of smooth radial bumps centred on 2D points: dermal papillae, mucosal folds, pores (negative amp)."""

    def __init__(self, points, radius, amp, k=6, sharp=1.0):
        self.pts = np.asarray(points, float).reshape(-1, 2)
        self.tree = cKDTree(self.pts) if len(self.pts) else None
        self.radius, self.amp, self.k, self.sharp = radius, amp, min(k, max(len(self.pts), 1)), sharp

    def __call__(self, X, Z):
        X, Z = np.broadcast_arrays(np.asarray(X, float), np.asarray(Z, float))
        if self.tree is None:
            return np.zeros(X.shape)
        q = np.stack([X.ravel(), Z.ravel()], -1)
        d, _ = self.tree.query(q, k=self.k)
        d = d.reshape(len(q), -1)
        t = np.clip(1.0 - d / self.radius, 0.0, 1.0)
        prof = t * t * (3.0 - 2.0 * t)
        if self.sharp != 1.0:
            prof = prof ** self.sharp
        amp = np.asarray(self.amp, float)
        return (prof.sum(axis=1) * amp).reshape(X.shape) if amp.ndim == 0 else (prof.sum(axis=1)).reshape(X.shape)


class Grooves:
    """Voronoi furrows (F2 - F1 small near cell borders): skin surface lines, cell mosaics on epithelia."""

    def __init__(self, points, width, depth):
        self.tree = cKDTree(np.asarray(points, float))
        self.width, self.depth = width, depth

    def __call__(self, X, Z):
        X, Z = np.broadcast_arrays(np.asarray(X, float), np.asarray(Z, float))
        d, _ = self.tree.query(np.stack([X.ravel(), Z.ravel()], -1), k=2)
        edge = (d[:, 1] - d[:, 0]) / 2.0
        t = np.clip(1.0 - edge / self.width, 0.0, 1.0)
        return (-self.depth * t * t * (3 - 2 * t)).reshape(X.shape)


def noise2(amp, freq, seed=0, octaves=4):
    return lambda X, Z: amp * fbm2(np.asarray(X, np.float32), np.asarray(Z, np.float32), freq, octaves, seed)


def add(*fns):
    fns = [fn(f) for f in fns]
    return lambda X, Z: sum(f(X, Z) for f in fns)


def shift(f, dy):
    f = fn(f)
    return lambda X, Z: f(X, Z) + dy


def minimum(a, b):
    a, b = fn(a), fn(b)
    return lambda X, Z: np.minimum(a(X, Z), b(X, Z))


def maximum(a, b):
    a, b = fn(a), fn(b)
    return lambda X, Z: np.maximum(a(X, Z), b(X, Z))


def muscle_bundles(bottom, top, axis, spacing, radius, seed, x=(-1.0, 1.0), z=(-0.6, 0.6), rows=2, voxel=0.0055,
                   waves=2.4, blend=0.012):
    """A muscle layer built from interlacing bundles instead of a smooth slab.

    Smooth muscle in a hollow organ is bundles of fibres wrapped in connective tissue, and the gaps between them
    are where the plexuses and vessels run. `bottom` and `top` are height functions, so the bundles follow a rugal
    fold or a taenia the way the layer itself does. `axis` is 0 for bundles running along x, 2 for along z."""
    bottom, top = fn(bottom), fn(top)
    xs = np.linspace(x[0], x[1], 40)
    zs = np.linspace(z[0], z[1], 30)
    X, Z = np.meshgrid(xs, zs, indexing="ij")
    y_lo = float(np.min(bottom(X, Z)))
    y_hi = float(np.max(top(X, Z)))
    rng = np.random.default_rng(abs(int(seed)) + 1)
    v = Volume((x[0], y_lo - 0.03, z[0]), (x[1], y_hi + 0.03, z[1]), voxel)
    a0, a1 = (z if axis == 0 else x)
    b0, b1 = (x[0] - 0.03, x[1] + 0.03) if axis == 0 else (z[0] - 0.03, z[1] + 0.03)
    n = 46
    t = np.linspace(0.0, 1.0, n)
    main = b0 + (b1 - b0) * t
    for r in range(rows):
        c = a0 + spacing * (0.5 + r * 0.5)
        while c < a1 + spacing * 0.5:
            ph = rng.uniform(0, 2 * math.pi)
            side = c + spacing * 0.26 * np.sin(waves * math.pi * t + ph)
            px, pz = (main, side) if axis == 0 else (side, main)
            lo_y = bottom(px, pz)
            hi_y = top(px, pz)
            frac = (r + 0.5) / rows + 0.16 * np.sin(waves * 0.8 * math.pi * t + ph * 1.3) / rows
            ys = lo_y + (hi_y - lo_y) * np.clip(frac, 0.12, 0.88)
            v.tube(np.stack([px, ys, pz], -1), radius * rng.uniform(0.85, 1.15), "smooth", blend)
            c += spacing * rng.uniform(0.9, 1.1)
    slab_fn, _, _ = layer_y(lambda X_, Z_: bottom(X_, Z_), lambda X_, Z_: top(X_, Z_), (0, 0, 0), (0, 0, 0))
    ax, ay, az = v.axes()
    np.maximum(v.d, slab_fn(ax, ay, az), out=v.d)
    v.intersect_box((x[0], y_lo - 0.03, z[0]), (x[1], y_hi + 0.03, z[1]))
    return v


def sdf_part(vol, name, group, color, desc, category="organ", smooth=0.9, rank=0.0, alpha=1.0, bulk=False, clip=True,
             label=True, detail=None, step=1):
    return Part(name, group, color, vol.mesh(smooth, step=step), desc, alpha=alpha, category=category, bulk=bulk,
                clip=clip, rank=rank, label=label, detail=detail)


def mesh_part(mesh, name, group, color, desc, category="organ", rank=0.0, alpha=1.0, bulk=False, clip=True,
              label=True, detail=None):
    return Part(name, group, color, mesh, desc, alpha=alpha, category=category, bulk=bulk, clip=clip, rank=rank,
                label=label, detail=detail)


def tube_mesh(points, radius, segments=18, samples=None, caps=True):
    path = np.asarray(points, float)
    if samples:
        path = smooth_path(path, samples)
    return tube(path, radius, segments, caps=caps)


def tube_shell(path, r_out, r_in, segments=20):
    """Hollow tube (tubule, duct, vessel wall) along a path: outer and inner walls joined by annular end caps."""
    path = np.asarray(path, float)
    outer = tube(path, r_out, segments, caps=False)
    inner = tube(path, r_in, segments, caps=False)
    po, _, io = outer.arrays()
    pi, _, ii = inner.arrays()
    k = len(path)
    n = segments
    pos = np.vstack([po, pi])
    idx = [io, ii[:, ::-1] + len(po)]
    ring = np.arange(n)
    nxt = (ring + 1) % n
    for row, flip in ((0, True), (k - 1, False)):
        o0, o1 = row * n + ring, row * n + nxt
        i0, i1 = o0 + len(po), o1 + len(po)
        tri = np.vstack([np.stack([o0, o1, i1], 1), np.stack([o0, i1, i0], 1)])
        idx.append(tri[:, ::-1] if flip else tri)
    from .cells import orient_outward
    return orient_outward(Mesh().add(pos, np.vstack(idx)))


def wavy_path(a, b, n=40, amp=0.02, freq=3.0, seed=0):
    """Straight-ish vessel/nerve course with gentle meanders."""
    rng = np.random.default_rng(abs(int(seed)))
    a, b = np.asarray(a, float), np.asarray(b, float)
    t = np.linspace(0, 1, n)[:, None]
    p = a + (b - a) * t
    d = b - a
    d /= np.linalg.norm(d)
    side = np.cross(d, [0.0, 1.0, 0.0])
    if np.linalg.norm(side) < 1e-6:
        side = np.cross(d, [1.0, 0.0, 0.0])
    side /= np.linalg.norm(side)
    up = np.cross(side, d)
    ph1, ph2 = rng.uniform(0, 2 * math.pi, 2)
    s = np.sin(t * math.pi)
    p += side * (amp * np.sin(t * freq * 2 * math.pi + ph1) * s)
    p += up * (amp * 0.5 * np.sin(t * freq * 1.3 * 2 * math.pi + ph2) * s)
    return p


def coil_path(center, extent, turns=9, points=320, seed=0, radii=None, step=None, length=None):
    """Loosely wound ball of tubule (sweat gland coils, glomerular tufts): a smooth random walk with momentum that
    turns back whenever it leaves an ellipsoid, like a ball of yarn."""
    rng = np.random.default_rng(seed)
    c = np.asarray(center, float)
    r = np.asarray(radii if radii is not None else (extent, extent * 0.75, extent), float)
    step = step or extent * 0.11
    p = c + rng.normal(size=3) * r * 0.2
    d = rng.normal(size=3)
    d /= np.linalg.norm(d)
    pts = [p.copy()]
    n_steps = int(length / step) if length else max(points // 2, 40) + turns * 4
    for _ in range(n_steps):
        d = d + rng.normal(size=3) * 0.55
        q = (p - c) / r
        outside = float(np.linalg.norm(q))
        if outside > 0.82:
            d -= q / outside * (outside - 0.6) * 3.0
        d /= np.linalg.norm(d)
        p = p + d * step
        pts.append(p.copy())
    return smooth_path(np.array(pts), points)


def blob_cluster(center, count, radius, spread, seed=0, squash=(1.0, 1.0, 1.0)):
    """Ellipsoid primitives for a lobulated gland (sebaceous, Brunner, von Ebner)."""
    rng = np.random.default_rng(seed)
    c = np.asarray(center, float)
    shapes = []
    for _ in range(count):
        off = rng.normal(size=3) * np.asarray(spread) * 0.6
        r = radius * rng.uniform(0.75, 1.25)
        shapes.append(ellipsoid(c + off, (r * squash[0], r * squash[1] * rng.uniform(0.8, 1.1), r * squash[2])))
    return shapes


def dendritic_cell(center, body, arms, arm_len, seed=0, plane_normal=(0.0, 1.0, 0.0)):
    """Cell body with tapering processes (melanocytes, keratocytes, podocyte-like cells)."""
    rng = np.random.default_rng(seed)
    c = np.asarray(center, float)
    n = np.asarray(plane_normal, float)
    n /= np.linalg.norm(n)
    helper = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 0.0, 1.0])
    u = np.cross(n, helper)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    shapes = [ellipsoid(c, (body, body * 0.7, body))]
    for i in range(arms):
        a = 2 * math.pi * i / arms + rng.uniform(-0.4, 0.4)
        d = u * math.cos(a) + v * math.sin(a) + n * rng.uniform(-0.25, 0.35)
        d /= np.linalg.norm(d)
        end = c + d * arm_len * rng.uniform(0.7, 1.2)
        shapes.append(round_cone(c, end, body * 0.45, body * 0.12))
    return shapes


__all__ = ["Volume", "Part", "Mesh", "sphere", "ellipsoid", "capsule", "round_cone", "poisson_disk",
           "sample_surface", "hlayer", "at", "Bumps", "Grooves", "noise2", "add", "shift", "minimum", "maximum",
           "sdf_part", "mesh_part", "muscle_bundles", "tube_mesh", "wavy_path", "coil_path", "blob_cluster",
           "dendritic_cell", "fn",
           "const", "smooth_path"]
