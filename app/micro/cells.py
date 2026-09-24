"""Cell-scale helpers: point distributions, 2D Voronoi cell outlines, extrusion and surface scattering."""
import math

import numpy as np
from scipy.spatial import Voronoi, cKDTree

from .geometry import Mesh


def hex_points(lo, hi, spacing, jitter=0.0, seed=0):
    """Jittered hexagonal lattice of 2D points inside a rectangle."""
    rng = np.random.default_rng(seed)
    dy = spacing * math.sqrt(3) / 2
    pts = []
    for j, v in enumerate(np.arange(lo[1], hi[1] + 1e-9, dy)):
        off = spacing / 2 if j % 2 else 0.0
        for u in np.arange(lo[0] + off, hi[0] + 1e-9, spacing):
            pts.append((u, v))
    pts = np.array(pts, dtype=np.float64)
    if jitter:
        pts += rng.uniform(-jitter, jitter, pts.shape) * spacing
    return pts


def jittered_bcc(lo, hi, spacing, jitter=0.18, seed=0, relax=2):
    """Fast, evenly spread 3D points: a body-centred cubic lattice with jitter and a little repulsion.
    Its Voronoi cells are rounded polyhedra, like packed adipocytes or follicles."""
    rng = np.random.default_rng(seed)
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    axes = [np.arange(l, h + spacing, spacing) for l, h in zip(lo, hi)]
    g = np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3)
    pts = np.vstack([g, g + spacing / 2])
    pts += rng.uniform(-jitter, jitter, pts.shape) * spacing
    for _ in range(relax):
        tree = cKDTree(pts)
        d, j = tree.query(pts, k=9)
        push = np.zeros_like(pts)
        for c in range(1, 9):
            v = pts - pts[j[:, c]]
            w = np.clip(spacing * 0.9 - d[:, c], 0, None)[:, None] / np.maximum(d[:, c], 1e-9)[:, None]
            push += v * w * 0.25
        pts += push
    return pts


def poisson_disk(lo, hi, radius, seed=0, k=24, max_points=200000):
    """Bridson Poisson-disk sampling in 2 or 3 dimensions."""
    rng = np.random.default_rng(seed)
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    dim = len(lo)
    cell = radius / math.sqrt(dim)
    gshape = np.maximum(np.ceil((hi - lo) / cell).astype(int), 1)
    grid = -np.ones(gshape, dtype=np.int64)
    pts = []
    first = rng.uniform(lo, hi)
    pts.append(first)
    grid[tuple(np.minimum(((first - lo) / cell).astype(int), gshape - 1))] = 0
    active = [0]
    rad2 = radius * radius
    offsets = np.stack(np.meshgrid(*[np.arange(-2, 3)] * dim, indexing="ij"), -1).reshape(-1, dim)
    while active and len(pts) < max_points:
        i = active[rng.integers(len(active))]
        base = pts[i]
        placed = False
        for _ in range(k):
            d = rng.normal(size=dim)
            d /= np.linalg.norm(d)
            cand = base + d * radius * rng.uniform(1.0, 2.0)
            if np.any(cand < lo) or np.any(cand > hi):
                continue
            gi = np.minimum(((cand - lo) / cell).astype(int), gshape - 1)
            ok = True
            for off in offsets:
                g = gi + off
                if np.any(g < 0) or np.any(g >= gshape):
                    continue
                j = grid[tuple(g)]
                if j >= 0 and np.sum((pts[j] - cand) ** 2) < rad2:
                    ok = False
                    break
            if ok:
                grid[tuple(gi)] = len(pts)
                pts.append(cand)
                active.append(len(pts) - 1)
                placed = True
                break
        if not placed:
            active.remove(i)
    return np.array(pts)


def clip_polygon(poly, lo, hi):
    """Sutherland–Hodgman clip of a polygon to an axis-aligned rectangle."""
    def clip(points, axis, value, keep_greater):
        out = []
        n = len(points)
        for i in range(n):
            a, b = points[i], points[(i + 1) % n]
            ina = a[axis] >= value if keep_greater else a[axis] <= value
            inb = b[axis] >= value if keep_greater else b[axis] <= value
            if ina:
                out.append(a)
            if ina != inb:
                t = (value - a[axis]) / (b[axis] - a[axis])
                out.append(a + (b - a) * t)
        return out
    pts = [np.asarray(p, float) for p in poly]
    for axis, value, greater in ((0, lo[0], True), (0, hi[0], False), (1, lo[1], True), (1, hi[1], False)):
        if not pts:
            break
        pts = clip(pts, axis, value, greater)
    return np.array(pts)


def voronoi_polygons(points, lo, hi):
    """Voronoi cell polygon (counter-clockwise) for every 2D point, clipped to the rectangle."""
    points = np.asarray(points, float)
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    mirrored = [points]
    for axis in (0, 1):
        for bound in (lo[axis], hi[axis]):
            m = points.copy()
            m[:, axis] = 2 * bound - m[:, axis]
            mirrored.append(m)
    vor = Voronoi(np.vstack(mirrored))
    polys = []
    for i in range(len(points)):
        region = vor.regions[vor.point_region[i]]
        if not region or -1 in region:
            polys.append(None)
            continue
        poly = vor.vertices[region]
        c = points[i]
        ang = np.arctan2(poly[:, 1] - c[1], poly[:, 0] - c[0])
        poly = poly[np.argsort(ang)]
        poly = clip_polygon(poly, lo, hi)
        polys.append(poly if len(poly) >= 3 else None)
    return polys


def inset_polygon(poly, d):
    """Shrink a convex CCW polygon by moving every edge inward by d."""
    poly = np.asarray(poly, float)
    n = len(poly)
    c = poly.mean(axis=0)
    out = []
    for i in range(n):
        p0, p1, p2 = poly[i - 1], poly[i], poly[(i + 1) % n]
        e1 = p1 - p0
        e2 = p2 - p1
        n1 = np.array([-e1[1], e1[0]]) / (np.linalg.norm(e1) + 1e-12)
        n2 = np.array([-e2[1], e2[0]]) / (np.linalg.norm(e2) + 1e-12)
        bis = n1 + n2
        ln = np.linalg.norm(bis)
        if ln < 1e-6:
            out.append(p1 + n1 * d)
            continue
        bis /= ln
        cos_half = max(float(np.dot(bis, n1)), 0.25)
        out.append(p1 + bis * d / cos_half)
    out = np.array(out)
    # guard against collapse: never pass the centroid
    r_old = np.linalg.norm(poly - c, axis=1)
    r_new = np.linalg.norm(out - c, axis=1)
    bad = r_new > r_old
    out[bad] = c + (poly[bad] - c) * 0.3
    return out


def smooth_polygon(poly, iterations=2):
    """Chaikin corner cutting – rounds cell corners."""
    p = np.asarray(poly, float)
    for _ in range(iterations):
        q = 0.75 * p + 0.25 * np.roll(p, -1, axis=0)
        r = 0.25 * p + 0.75 * np.roll(p, -1, axis=0)
        p = np.empty((len(q) * 2, 2))
        p[0::2], p[1::2] = q, r
    return p


def polygon_area(poly):
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def extrude(poly, mapping, t_values, caps=True):
    """Sweep a 2D outline along t. mapping(u, v, t) -> xyz arrays. Returns a closed, outward-wound Mesh."""
    poly = np.asarray(poly, float)
    if polygon_area(poly) < 0:
        poly = poly[::-1]
    n = len(poly)
    t_values = np.asarray(t_values, float)
    m = len(t_values)
    U = np.broadcast_to(poly[:, 0], (m, n))
    V = np.broadcast_to(poly[:, 1], (m, n))
    T = np.broadcast_to(t_values[:, None], (m, n))
    x, y, z = mapping(U, V, T)
    ring = np.stack(np.broadcast_arrays(x, y, z), -1).reshape(-1, 3)
    a = np.arange(m * n).reshape(m, n)
    q0, q1 = a[:-1, :].ravel(), np.roll(a[:-1, :], -1, axis=1).ravel()
    q2, q3 = np.roll(a[1:, :], -1, axis=1).ravel(), a[1:, :].ravel()
    tris = [np.stack([q0, q2, q1], 1), np.stack([q0, q3, q2], 1)]
    pos = ring
    if caps:
        centers = []
        for end in (0, m - 1):
            cu, cv = poly[:, 0].mean(), poly[:, 1].mean()
            cx, cy, cz = mapping(np.array([cu]), np.array([cv]), np.array([t_values[end]]))
            centers.append(np.array([float(np.ravel(cx)[0]), float(np.ravel(cy)[0]), float(np.ravel(cz)[0])]))
        base = len(pos)
        pos = np.vstack([pos, centers])
        i = np.arange(n)
        tris.append(np.stack([np.full(n, base), a[0, (i + 1) % n], a[0, i]], 1))
        tris.append(np.stack([np.full(n, base + 1), a[-1, i], a[-1, (i + 1) % n]], 1))
    idx = np.vstack(tris)
    mesh = Mesh().add(pos, idx)
    return orient_outward(mesh)


def orient_outward(mesh):
    """Flip every sub-mesh whose signed volume is negative."""
    fixed = []
    for p, n, i in mesh.parts:
        tri = p[i]
        vol = float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum())
        if vol < 0:
            i = i[:, ::-1].copy()
            n = -n
        fixed.append((p, n, i))
    mesh.parts = fixed
    return mesh


def sample_surface(mesh, spacing, seed=0, mask=None):
    """Well-spread points on a mesh (area-weighted random samples thinned to a minimum spacing).
    Returns positions and unit normals. mask(points, normals) -> bool array filters candidates."""
    pos, nrm, idx = mesh.arrays()
    if len(idx) == 0:
        return np.zeros((0, 3)), np.zeros((0, 3))
    tri = pos[idx].astype(np.float64)
    area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    total = float(area.sum())
    n_cand = int(min(max(total / (spacing * spacing) * 4, 16), 400000))
    rng = np.random.default_rng(seed)
    choice = rng.choice(len(idx), size=n_cand, p=area / total)
    r1, r2 = rng.random(n_cand), rng.random(n_cand)
    s = np.sqrt(r1)
    w0, w1, w2 = 1 - s, s * (1 - r2), s * r2
    t = tri[choice]
    pts = t[:, 0] * w0[:, None] + t[:, 1] * w1[:, None] + t[:, 2] * w2[:, None]
    nn = nrm[idx[choice]].astype(np.float64)
    nv = nn[:, 0] * w0[:, None] + nn[:, 1] * w1[:, None] + nn[:, 2] * w2[:, None]
    nv /= np.maximum(np.linalg.norm(nv, axis=1, keepdims=True), 1e-9)
    if mask is not None:
        keep = mask(pts, nv)
        pts, nv = pts[keep], nv[keep]
    if len(pts) == 0:
        return pts, nv
    order = rng.permutation(len(pts))
    pts, nv = pts[order], nv[order]
    tree = cKDTree(pts)
    taken = np.zeros(len(pts), bool)
    blocked = np.zeros(len(pts), bool)
    for i in range(len(pts)):
        if blocked[i]:
            continue
        taken[i] = True
        for j in tree.query_ball_point(pts[i], spacing):
            blocked[j] = True
    return pts[taken], nv[taken]


def frame_from_normal(n):
    """Rotation matrix whose local y axis is n."""
    n = np.asarray(n, float)
    n = n / np.linalg.norm(n)
    helper = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 0.0, 1.0])
    x = np.cross(helper, n)
    x /= np.linalg.norm(x)
    z = np.cross(x, n)
    return np.stack([x, n, z], axis=1)
