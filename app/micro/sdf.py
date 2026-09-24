"""Signed-distance modelling on voxel grids, polygonised with marching cubes.

Distances are negative inside. Each primitive is evaluated only inside its own bounding box, so thousands of cells,
glands or villi stay cheap. Smooth unions and subtractions give organic junctions (villi growing out of the mucosa,
ducts merging into glands) that analytic meshes cannot."""
import numpy as np
from scipy import ndimage
from skimage.measure import marching_cubes

from .geometry import Mesh

BIG = 1.0e3


def smin(a, b, k):
    """Polynomial smooth minimum (union with a fillet of size k)."""
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b + (a - b) * h - k * h * (1.0 - h)


# ----------------------------------------------------------------------------------------------- noise
def _hash(ix, iy, iz, seed):
    h = (ix * 374761393 + iy * 668265263 + iz * 1440662683 + seed * 1013904223) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    h = h ^ (h >> 16)
    return (h & 0xFFFF).astype(np.float32) / 32767.5 - 1.0


def value_noise3(x, y, z, seed=0):
    """Smooth value noise in [-1, 1] for broadcastable coordinate arrays."""
    x, y, z = np.broadcast_arrays(np.asarray(x, np.float32), np.asarray(y, np.float32), np.asarray(z, np.float32))
    xi, yi, zi = np.floor(x), np.floor(y), np.floor(z)
    u, v, w = x - xi, y - yi, z - zi
    u, v, w = u * u * (3 - 2 * u), v * v * (3 - 2 * v), w * w * (3 - 2 * w)
    xi, yi, zi = xi.astype(np.int64), yi.astype(np.int64), zi.astype(np.int64)
    out = None
    for dz in (0, 1):
        plane = None
        for dy in (0, 1):
            a = _hash(xi, yi + dy, zi + dz, seed)
            b = _hash(xi + 1, yi + dy, zi + dz, seed)
            row = a + (b - a) * u
            plane = row if plane is None else plane + (row - plane) * v
        out = plane if out is None else out + (plane - out) * w
    return out


def fbm3(x, y, z, freq=1.0, octaves=4, seed=0, gain=0.5):
    total, amp, norm = 0.0, 1.0, 0.0
    for o in range(octaves):
        f = freq * (2.03 ** o)
        total = total + amp * value_noise3(x * f + 17.1 * o, y * f + 5.3 * o, z * f + 11.7 * o, seed + o)
        norm += amp
        amp *= gain
    return total / norm


def fbm2(x, z, freq=1.0, octaves=4, seed=0, gain=0.5):
    return fbm3(x, np.float32(0.37), z, freq, octaves, seed, gain)


# ----------------------------------------------------------------------------------------------- primitives
# Each returns (fn(x, y, z) -> distance, bbox_min, bbox_max).
def sphere(c, r):
    c = np.asarray(c, np.float32)
    return (lambda x, y, z: np.sqrt((x - c[0]) ** 2 + (y - c[1]) ** 2 + (z - c[2]) ** 2) - r), c - r, c + r


def ellipsoid(c, radii, rot=None):
    c = np.asarray(c, np.float32)
    r = np.asarray(radii, np.float32)
    R = None if rot is None else np.asarray(rot, np.float32)
    ext = float(r.max())

    def f(x, y, z):
        px, py, pz = x - c[0], y - c[1], z - c[2]
        if R is not None:
            px, py, pz = (R[0, 0] * px + R[1, 0] * py + R[2, 0] * pz, R[0, 1] * px + R[1, 1] * py + R[2, 1] * pz,
                          R[0, 2] * px + R[1, 2] * py + R[2, 2] * pz)
        k0 = np.sqrt((px / r[0]) ** 2 + (py / r[1]) ** 2 + (pz / r[2]) ** 2)
        k1 = np.sqrt((px / r[0] ** 2) ** 2 + (py / r[1] ** 2) ** 2 + (pz / r[2] ** 2) ** 2)
        return k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)
    return f, c - ext, c + ext


def round_cone(a, b, r1, r2):
    """Capsule whose radius tapers from r1 at a to r2 at b."""
    a = np.asarray(a, np.float32)
    b = np.asarray(b, np.float32)
    ba = b - a
    l2 = max(float(ba @ ba), 1e-12)
    rr = r1 - r2
    a2 = l2 - rr * rr
    il2 = 1.0 / l2

    def f(x, y, z):
        pax, pay, paz = x - a[0], y - a[1], z - a[2]
        yv = pax * ba[0] + pay * ba[1] + paz * ba[2]
        zv = yv - l2
        qx, qy, qz = pax * l2 - ba[0] * yv, pay * l2 - ba[1] * yv, paz * l2 - ba[2] * yv
        x2 = qx * qx + qy * qy + qz * qz
        y2 = yv * yv * l2
        z2 = zv * zv * l2
        k = np.sign(rr) * rr * rr * x2
        body = (np.sqrt(np.maximum(x2 * a2 * il2, 0.0)) + yv * rr) * il2 - r1
        cap_a = np.sqrt(x2 + y2) * il2 - r1
        cap_b = np.sqrt(x2 + z2) * il2 - r2
        out = np.where(np.sign(yv) * a2 * y2 < k, cap_a, body)
        return np.where(np.sign(zv) * a2 * z2 > k, cap_b, out)
    rmax = max(r1, r2)
    return f, np.minimum(a, b) - rmax, np.maximum(a, b) + rmax


def capsule(a, b, r):
    return round_cone(a, b, r, r)


def squashed(shape, center, scale):
    """Anisotropically scale a primitive about a point (e.g. flatten a finger into a leaf). Distances are rescaled by
    the smallest factor, which keeps them conservative."""
    fn, bmin, bmax = shape
    c = np.asarray(center, np.float32)
    s = np.asarray(scale, np.float32)
    k = float(s.min())

    def f(x, y, z):
        return fn(c[0] + (x - c[0]) / s[0], c[1] + (y - c[1]) / s[1], c[2] + (z - c[2]) / s[2]) * k
    lo = c + (np.asarray(bmin) - c) * s
    hi = c + (np.asarray(bmax) - c) * s
    return f, np.minimum(lo, hi), np.maximum(lo, hi)


def box(c, half, radius=0.0):
    c = np.asarray(c, np.float32)
    h = np.asarray(half, np.float32) - radius

    def f(x, y, z):
        qx, qy, qz = np.abs(x - c[0]) - h[0], np.abs(y - c[1]) - h[1], np.abs(z - c[2]) - h[2]
        outside = np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2 + np.maximum(qz, 0) ** 2)
        inside = np.minimum(np.maximum(np.maximum(qx, qy), qz), 0.0)
        return outside + inside - radius
    return f, c - np.asarray(half, np.float32), c + np.asarray(half, np.float32)


def torus_y(c, R, r):
    """Torus lying in the xz plane."""
    c = np.asarray(c, np.float32)

    def f(x, y, z):
        q = np.sqrt((x - c[0]) ** 2 + (z - c[2]) ** 2) - R
        return np.sqrt(q * q + (y - c[1]) ** 2) - r
    e = np.array([R + r, r, R + r], np.float32)
    return f, c - e, c + e


def layer_y(bottom, top, lo, hi):
    """Region between two height functions of (x, z) — an approximate distance, exact on the surfaces."""
    def f(x, y, z):
        return np.maximum(bottom(x, z) - y, y - top(x, z))
    return f, np.asarray(lo, np.float32), np.asarray(hi, np.float32)


# ----------------------------------------------------------------------------------------------- volume
class Volume:
    def __init__(self, lo, hi, voxel, fill=BIG):
        self.voxel = float(voxel)
        self.lo = np.asarray(lo, dtype=np.float64)
        self.shape = tuple(int(np.ceil((h - l) / self.voxel)) + 1 for l, h in zip(lo, hi))
        self.d = np.full(self.shape, fill, dtype=np.float32)
        self._slices = None

    @property
    def hi(self):
        return self.lo + (np.array(self.shape) - 1) * self.voxel

    def axes(self, i0=(0, 0, 0), i1=None):
        i1 = self.shape if i1 is None else i1
        v = self.voxel
        x = (self.lo[0] + np.arange(i0[0], i1[0]) * v).astype(np.float32)[:, None, None]
        y = (self.lo[1] + np.arange(i0[1], i1[1]) * v).astype(np.float32)[None, :, None]
        z = (self.lo[2] + np.arange(i0[2], i1[2]) * v).astype(np.float32)[None, None, :]
        return x, y, z

    def region(self, bmin, bmax):
        v = self.voxel
        i0 = np.maximum(np.floor((np.asarray(bmin, np.float64) - self.lo) / v).astype(int), 0)
        i1 = np.minimum(np.ceil((np.asarray(bmax, np.float64) - self.lo) / v).astype(int) + 1, self.shape)
        if np.any(i1 <= i0):
            return None
        return tuple(slice(int(a), int(b)) for a, b in zip(i0, i1)), self.axes(i0, i1)

    def apply(self, d, sl, op="union", k=0.0):
        cur = self.d[sl]
        if op == "union":
            np.minimum(cur, d, out=cur)
        elif op == "smooth":
            cur[...] = smin(cur, d, k)
        elif op == "subtract":
            np.maximum(cur, -d, out=cur)
        elif op == "smooth_subtract":
            cur[...] = -smin(-cur, d, k)
        elif op == "intersect":
            np.maximum(cur, d, out=cur)
        elif op == "smooth_intersect":
            cur[...] = -smin(-cur, -d, k)
        elif op == "replace":
            cur[...] = d
        else:
            raise ValueError(op)

    def add(self, shape, op="union", k=0.0):
        """Stamp a primitive (fn, bmin, bmax) inside its bounding box. Not valid for intersections."""
        fn, bmin, bmax = shape
        pad = k + 2.5 * self.voxel
        r = self.region(np.asarray(bmin) - pad, np.asarray(bmax) + pad)
        if r is None:
            return self
        sl, (x, y, z) = r
        self.apply(np.asarray(fn(x, y, z), dtype=np.float32), sl, op, k)
        return self

    def add_all(self, shapes, op="union", k=0.0):
        """Union a group of primitives first, then combine the group with the field in one operation."""
        shapes = list(shapes)
        if not shapes:
            return self
        if op == "union":
            for s in shapes:
                self.add(s)
            return self
        bmin = np.min([s[1] for s in shapes], axis=0) - k
        bmax = np.max([s[2] for s in shapes], axis=0) + k
        sub = self.sub(bmin, bmax)
        if sub is None:
            return self
        for s in shapes:
            sub.add(s)
        self.merge(sub, op, k)
        return self

    def tube(self, path, radii, op="union", k=0.0):
        path = np.asarray(path, np.float32)
        radii = np.broadcast_to(np.asarray(radii, np.float32), (len(path),))
        segs = [round_cone(path[i], path[i + 1], float(radii[i]), float(radii[i + 1])) for i in range(len(path) - 1)]
        return self.add_all(segs, op, k)

    def sub(self, bmin, bmax):
        r = self.region(bmin, bmax)
        if r is None:
            return None
        sl, _ = r
        s = Volume.__new__(Volume)
        s.voxel = self.voxel
        s.lo = self.lo + np.array([t.start for t in sl]) * self.voxel
        s.shape = tuple(t.stop - t.start for t in sl)
        s.d = np.full(s.shape, BIG, dtype=np.float32)
        s._slices = sl
        return s

    def merge(self, other, op="union", k=0.0):
        self.apply(other.d, other._slices, op, k)
        return self

    def copy(self, d=None):
        s = Volume.__new__(Volume)
        s.voxel, s.lo, s.shape, s._slices = self.voxel, self.lo.copy(), self.shape, self._slices
        s.d = self.d.copy() if d is None else d.astype(np.float32, copy=False)
        return s

    # ---- whole-field operations
    def intersect_box(self, lo, hi, radius=0.0):
        c = (np.asarray(lo) + np.asarray(hi)) / 2
        half = (np.asarray(hi) - np.asarray(lo)) / 2
        fn, _, _ = box(c, half, radius)
        x, y, z = self.axes()
        np.maximum(self.d, fn(x, y, z), out=self.d)
        return self

    def displace(self, amp, freq, octaves=3, seed=0, coarse=3):
        """Add fbm noise (computed on a coarser grid and upsampled) to roughen surfaces organically."""
        step = max(1, int(coarse))
        x, y, z = self.axes()
        cx, cy, cz = x[::step], y[:, ::step], z[:, :, ::step]
        n = fbm3(cx, cy, cz, freq, octaves, seed).astype(np.float32)
        if step > 1:
            zoom = [s / c for s, c in zip(self.shape, n.shape)]
            n = ndimage.zoom(n, zoom, order=1, mode="nearest")
            n = n[:self.shape[0], :self.shape[1], :self.shape[2]]
            if n.shape != self.shape:
                n = np.pad(n, [(0, s - c) for s, c in zip(self.shape, n.shape)], mode="edge")
        self.d += amp * n
        return self

    def shell(self, thickness, gap=0.0):
        """The band  -thickness < d < -gap : a skin of tissue lining the surface (e.g. epithelium)."""
        return self.copy(np.maximum(self.d + gap, -(self.d + thickness)))

    def offset(self, amount):
        """Shrink (amount > 0) or grow the shape."""
        return self.copy(self.d + amount)

    def mesh(self, smooth=0.8, level=0.0, step=1):
        """Polygonise the zero level set. step > 1 skips voxels for coarser, lighter meshes of hidden layers."""
        d = self.d
        if not (d.min() < level < d.max()):
            return Mesh()
        limit = self.voxel * (4.0 + 3.0 * smooth) * step
        d = np.clip(d, level - limit, level + limit)
        if smooth > 0:
            d = ndimage.gaussian_filter(d, smooth * step, mode="nearest")
            if not (d.min() < level < d.max()):
                return Mesh()      # features thinner than the smoothing kernel vanished
        d = np.pad(d, step, mode="constant", constant_values=level + limit)
        try:
            verts, faces, normals, _ = marching_cubes(d, level, spacing=(self.voxel,) * 3, step_size=step,
                                                      allow_degenerate=False)
        except (ValueError, RuntimeError):
            return Mesh()
        verts = (verts + (self.lo - self.voxel * step)).astype(np.float32)
        return Mesh().add(verts, faces.astype(np.int64), (-normals).astype(np.float32))
