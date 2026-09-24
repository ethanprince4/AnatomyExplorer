"""Procedural mesh primitives for microanatomy models (Y up)."""
import math

import numpy as np


def compute_normals(pos, idx):
    tri = pos[idx]
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n = np.zeros_like(pos)
    for k in range(3):
        for c in range(3):
            n[:, c] += np.bincount(idx[:, k], weights=fn[:, c], minlength=len(pos))
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    ln[ln == 0] = 1
    return (n / ln).astype(np.float32)


class Mesh:
    def __init__(self):
        self.parts = []

    def add(self, pos, idx, nrm=None):
        pos = np.asarray(pos, dtype=np.float32)
        idx = np.asarray(idx, dtype=np.int64).reshape(-1, 3)
        if nrm is None:
            nrm = compute_normals(pos, idx)
        self.parts.append((pos, np.asarray(nrm, dtype=np.float32), idx))
        return self

    def extend(self, other):
        self.parts.extend(other.parts)
        return self

    def arrays(self):
        if not self.parts:
            return np.zeros((0, 3), np.float32), np.zeros((0, 3), np.float32), np.zeros((0, 3), np.int64)
        ps, ns, ids = [], [], []
        off = 0
        for p, n, i in self.parts:
            ps.append(p)
            ns.append(n)
            ids.append(i + off)
            off += len(p)
        return np.concatenate(ps), np.concatenate(ns), np.concatenate(ids)

    def transformed(self, matrix=None, offset=(0, 0, 0)):
        m = np.identity(3) if matrix is None else np.asarray(matrix, dtype=np.float64)
        out = Mesh()
        for p, n, i in self.parts:
            out.parts.append(((p @ m.T + offset).astype(np.float32), (n @ m.T).astype(np.float32), i))
        return out


def _grid_indices(nu, nv, flip=False):
    a = np.arange(nu * nv).reshape(nu, nv)
    q0, q1, q2, q3 = a[:-1, :-1].ravel(), a[1:, :-1].ravel(), a[1:, 1:].ravel(), a[:-1, 1:].ravel()
    if flip:
        t = np.stack([np.stack([q0, q2, q1], 1), np.stack([q0, q3, q2], 1)], 1)
    else:
        t = np.stack([np.stack([q0, q1, q2], 1), np.stack([q0, q2, q3], 1)], 1)
    return t.reshape(-1, 3)


def slab(x0, x1, z0, z1, top_fn, bottom_fn, res=64, gap=0.0015):
    """Closed solid between two height fields y = f(x, z). A tiny gap avoids z-fighting between stacked slabs."""
    nx = max(2, int(res * (x1 - x0) / max(x1 - x0, z1 - z0)) + 1)
    nz = max(2, int(res * (z1 - z0) / max(x1 - x0, z1 - z0)) + 1)
    xs = np.linspace(x0, x1, nx)
    zs = np.linspace(z0, z1, nz)
    X, Z = np.meshgrid(xs, zs, indexing="ij")
    top = np.asarray(top_fn(X, Z), dtype=np.float64) * np.ones_like(X) - gap
    bot = np.asarray(bottom_fn(X, Z), dtype=np.float64) * np.ones_like(X) + gap
    bot = np.minimum(bot, top - 1e-4)
    m = Mesh()
    ptop = np.stack([X, top, Z], -1).reshape(-1, 3)
    m.add(ptop, _grid_indices(nx, nz, flip=True))
    pbot = np.stack([X, bot, Z], -1).reshape(-1, 3)
    m.add(pbot, _grid_indices(nx, nz, flip=False))
    edges = [
        (X[:, 0], Z[:, 0], top[:, 0], bot[:, 0], True),
        (X[:, -1], Z[:, -1], top[:, -1], bot[:, -1], False),
        (X[0, :], Z[0, :], top[0, :], bot[0, :], False),
        (X[-1, :], Z[-1, :], top[-1, :], bot[-1, :], True),
    ]
    for ex, ez, et, eb, flip in edges:
        n = len(ex)
        p = np.concatenate([np.stack([ex, eb, ez], -1), np.stack([ex, et, ez], -1)])
        a = np.arange(n)
        q0, q1, q2, q3 = a[:-1], a[1:], a[1:] + n, a[:-1] + n
        tri = np.concatenate([np.stack([q0, q1, q2], 1), np.stack([q0, q2, q3], 1)])
        if flip:
            tri = tri[:, ::-1]
        m.add(p, tri)
    return m


def frames(path):
    path = np.asarray(path, dtype=np.float64)
    t = np.gradient(path, axis=0)
    ln = np.linalg.norm(t, axis=1, keepdims=True)
    # repeated points give a zero tangent, which would poison the whole frame: carry the last good one instead
    good = (ln[:, 0] > 1e-12)
    if not good.any():
        t = np.tile(np.array([1.0, 0.0, 0.0]), (len(path), 1))
    elif not good.all():
        idx = np.where(good, np.arange(len(path)), -1)
        idx = np.maximum.accumulate(idx)
        first = int(np.argmax(good))
        idx[idx < 0] = first
        t = t[idx]
        ln = ln[idx]
    t = t / np.maximum(ln, 1e-12)
    ref = np.array([0.0, 1.0, 0.0]) if abs(t[0][1]) < 0.9 else np.array([1.0, 0.0, 0.0])
    n = np.cross(t[0], ref)
    nl = np.linalg.norm(n)
    if nl < 1e-9:
        n = np.cross(t[0], np.array([0.0, 0.0, 1.0]))
        nl = np.linalg.norm(n)
        if nl < 1e-9:
            n, nl = np.array([1.0, 0.0, 0.0]), 1.0
    n = n / nl
    normals = [n]
    for i in range(1, len(path)):
        v = np.cross(normals[-1], t[i])
        b = np.cross(t[i], normals[-1])
        nn = np.cross(b, t[i])
        ln = np.linalg.norm(nn)
        normals.append(nn / ln if ln > 1e-9 else normals[-1])
    normals = np.array(normals)
    binormals = np.cross(t, normals)
    return t, normals, binormals


def tube(path, radius, segments=12, caps=True, ry=None):
    """Sweep an ellipse (radius, ry) along a polyline."""
    path = np.asarray(path, dtype=np.float64)
    k = len(path)
    r = np.broadcast_to(np.asarray(radius, dtype=np.float64), (k,))
    r2 = r if ry is None else np.broadcast_to(np.asarray(ry, dtype=np.float64), (k,))
    t, nrm, bin_ = frames(path)
    ang = np.linspace(0, 2 * math.pi, segments, endpoint=False)
    c, s = np.cos(ang), np.sin(ang)
    ring = (path[:, None, :] + nrm[:, None, :] * (r[:, None, None] * c[None, :, None])
            + bin_[:, None, :] * (r2[:, None, None] * s[None, :, None]))
    pos = ring.reshape(-1, 3)
    a = np.arange(k * segments).reshape(k, segments)
    q0 = a[:-1, :].ravel()
    q1 = np.roll(a[:-1, :], -1, axis=1).ravel()
    q2 = np.roll(a[1:, :], -1, axis=1).ravel()
    q3 = a[1:, :].ravel()
    tri = np.concatenate([np.stack([q0, q1, q2], 1), np.stack([q0, q2, q3], 1)])
    m = Mesh().add(pos, tri)
    if caps:
        for end, sign in ((0, -1), (k - 1, 1)):
            rp = ring[end]
            center = path[end]
            p = np.vstack([center[None], rp])
            idx = np.array([[0, i + 1, (i + 1) % segments + 1] for i in range(segments)])
            if sign < 0:
                idx = idx[:, ::-1]
            m.add(p, idx)
    return m


def ellipsoid(center, radii, res=16, rotation=None):
    nu, nv = res, res * 2
    th = np.linspace(0, math.pi, nu)
    ph = np.linspace(0, 2 * math.pi, nv)
    T, P = np.meshgrid(th, ph, indexing="ij")
    unit = np.stack([np.sin(T) * np.cos(P), np.cos(T), np.sin(T) * np.sin(P)], -1).reshape(-1, 3)
    pos = unit * np.asarray(radii)
    nrm = unit / np.asarray(radii)
    if rotation is not None:
        pos = pos @ np.asarray(rotation).T
        nrm = nrm @ np.asarray(rotation).T
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
    return Mesh().add(pos + np.asarray(center), _grid_indices(nu, nv, flip=True), nrm)


def box(center, size):
    cx, cy, cz = center
    sx, sy, sz = (s / 2 for s in size)
    return slab(cx - sx, cx + sx, cz - sz, cz + sz, lambda X, Z: cy + sy, lambda X, Z: cy - sy, res=2)


def capsule(base, top, radius, segments=14, rings=10):
    """Finger-like shape (villus): tube with a hemispherical tip and flat base."""
    base = np.asarray(base, dtype=np.float64)
    top = np.asarray(top, dtype=np.float64)
    axis = top - base
    length = np.linalg.norm(axis)
    d = axis / length
    body = [base + d * length * t for t in np.linspace(0, 1, rings)]
    tip = [top + d * radius * math.sin(a) for a in np.linspace(0, math.pi / 2, 6)[1:]]
    radii = [radius] * rings + [radius * math.cos(a) for a in np.linspace(0, math.pi / 2, 6)[1:]]
    radii[-1] = radius * 0.08
    return tube(np.array(body + tip), np.array(radii), segments=segments, caps=True)


def rotation_to(direction):
    d = np.asarray(direction, dtype=np.float64)
    d /= np.linalg.norm(d)
    up = np.array([0.0, 1.0, 0.0])
    v = np.cross(up, d)
    s = np.linalg.norm(v)
    c = np.dot(up, d)
    if s < 1e-9:
        return np.identity(3) if c > 0 else np.diag([1, -1, -1])
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.identity(3) + vx + vx @ vx * ((1 - c) / (s * s))


def helix_path(center, radius, height, turns, points=120, phase=0.0, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 1, points)
    a = phase + t * turns * 2 * math.pi
    p = np.stack([center[0] + radius * np.cos(a), center[1] + height * t, center[2] + radius * np.sin(a)], -1)
    if noise:
        p += np.cumsum(rng.normal(0, noise, p.shape), axis=0) * 0.15
    return p


def coil_ball(center, extent, points=260, seed=0):
    """Tangled tubular coil (e.g. sweat gland secretory portion)."""
    rng = np.random.default_rng(seed)
    p = np.zeros((points, 3))
    v = rng.normal(size=3)
    v /= np.linalg.norm(v)
    cur = np.zeros(3)
    for i in range(points):
        v = v + rng.normal(0, 0.55, 3) - cur / (extent * 1.2)
        v /= np.linalg.norm(v)
        cur = cur + v * extent * 0.12
        p[i] = cur
    k = 5
    kernel = np.ones(k) / k
    smooth = np.stack([np.convolve(p[:, j], kernel, mode="same") for j in range(3)], -1)
    smooth[: k // 2] = p[: k // 2]
    smooth[-k // 2:] = p[-k // 2:]
    return smooth + np.asarray(center)


def smooth_path(points, samples=60):
    """Catmull-Rom spline through control points."""
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 3:
        return np.linspace(pts[0], pts[-1], samples)
    p = np.vstack([pts[0] * 2 - pts[1], pts, pts[-1] * 2 - pts[-2]])
    out = []
    segs = len(pts) - 1
    per = max(2, samples // segs)
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
        for t in np.linspace(0, 1, per, endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    out.append(pts[-1])
    return np.array(out)


def lobules(center, count, radius, spread, seed=0, res=10, squash=(1, 1, 1)):
    """Cluster of small spheres (acini, sebaceous lobules, adipocytes)."""
    rng = np.random.default_rng(seed)
    m = Mesh()
    for _ in range(count):
        off = rng.normal(0, spread, 3) * np.asarray(squash)
        r = radius * rng.uniform(0.7, 1.15)
        m.extend(ellipsoid(np.asarray(center) + off, (r, r * rng.uniform(0.8, 1.1), r), res=res))
    return m


def arc_band(center, radius, thickness, height, start_deg, end_deg, axis="y", segments=48):
    """Thick curved band, e.g. a C-shaped cartilage ring or a muscle layer around a tube."""
    a = np.radians(np.linspace(start_deg, end_deg, segments))
    cx, cy, cz = center
    path = np.stack([cx + radius * np.cos(a), np.full_like(a, cy), cz + radius * np.sin(a)], -1)
    m = tube(path, thickness / 2, segments=10, ry=height / 2)
    return m


def cylinder_shell(center, r_in, r_out, length, start_deg=0, end_deg=360, segments=64, axis="x"):
    """Thick-walled cylinder segment along an axis (vessel wall layers, gut wall). Closed solid."""
    a = np.radians(np.linspace(start_deg, end_deg, segments))
    full = abs(end_deg - start_deg) >= 359.9
    xs = np.array([-length / 2, length / 2])
    m = Mesh()

    def ring_points(r, x):
        return np.stack([np.full_like(a, x), r * np.cos(a), r * np.sin(a)], -1)

    for r, outward in ((r_out, True), (r_in, False)):
        p = np.concatenate([ring_points(r, xs[0]), ring_points(r, xs[1])])
        n = segments
        i0 = np.arange(n - 1)
        tri = np.concatenate([np.stack([i0, i0 + 1, i0 + n + 1], 1), np.stack([i0, i0 + n + 1, i0 + n], 1)])
        if full:
            tri = np.vstack([tri, [[n - 1, 0, n], [n - 1, n, 2 * n - 1]]])
        if not outward:
            tri = tri[:, ::-1]
        m.add(p, tri)
    for x, flip in ((xs[0], True), (xs[1], False)):
        p = np.concatenate([ring_points(r_in, x), ring_points(r_out, x)])
        n = segments
        i0 = np.arange(n - 1)
        tri = np.concatenate([np.stack([i0, i0 + 1, i0 + n + 1], 1), np.stack([i0, i0 + n + 1, i0 + n], 1)])
        if full:
            tri = np.vstack([tri, [[n - 1, 0, n], [n - 1, n, 2 * n - 1]]])
        m.add(p, tri if flip else tri[:, ::-1])
    if not full:
        for ang, flip in ((a[0], True), (a[-1], False)):
            ca, sa = math.cos(ang), math.sin(ang)
            p = np.array([[xs[0], r_in * ca, r_in * sa], [xs[1], r_in * ca, r_in * sa],
                          [xs[1], r_out * ca, r_out * sa], [xs[0], r_out * ca, r_out * sa]])
            tri = np.array([[0, 1, 2], [0, 2, 3]])
            m.add(p, tri[:, ::-1] if flip else tri)
    return m.transformed(offset=center)
