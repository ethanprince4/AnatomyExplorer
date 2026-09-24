"""Tools that stop procedural tissue from looking procedural.

Three ideas do most of the work:

* **Cellular relief** - real tissue surfaces are made of cells, so every free surface gets a Worley-based mosaic of
  shallow domes separated by grooves. Cells can be stretched along an axis (endothelium along the flow, smooth muscle
  around the circumference).
* **Swept, non-circular tubes** - vessels, nerves and muscles are built around a curved centreline with a radius that
  varies with angle and position, so no layer is ever a cylinder of revolution.
* **A shared warp** - at the end of a build every part of a model is pushed through the same smooth noise field.
  Because the field is a function of world position, nested layers stay perfectly in register while the block as a
  whole loses its machined, axis-aligned look.
"""
import math

import numpy as np

from .geometry import Mesh, compute_normals, frames
from .sdf import fbm3, value_noise3


# --------------------------------------------------------------------------------------------- cellular fields
def _jitter(ix, iy, iz, seed, comp):
    """Deterministic offset in [0, 1) for a lattice cell."""
    h = (ix * 1610612741 + iy * 805306457 + iz * 402653189 + seed * 196613 + comp * 83492791) & 0xFFFFFFFF
    h = ((h ^ (h >> 15)) * 2246822519) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 3266489917) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFFFF).astype(np.float64) / 16777216.0


def worley(p, size, seed=0, stretch=(1.0, 1.0, 1.0), jitter=0.85):
    """Nearest two feature-point distances of a jittered lattice.

    Returns (f1, f2) in the units of `p`. `stretch` scales the lattice per axis, which makes the cells elongated
    (endothelium along the vessel, smooth muscle around it)."""
    p = np.asarray(p, np.float64).reshape(-1, 3)
    s = np.asarray(stretch, np.float64) * float(size)
    q = p / s
    base = np.floor(q).astype(np.int64)
    f1 = np.full(len(p), 1e9)
    f2 = np.full(len(p), 1e9)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                cx, cy, cz = base[:, 0] + dx, base[:, 1] + dy, base[:, 2] + dz
                fx = cx + 0.5 + (_jitter(cx, cy, cz, seed, 0) - 0.5) * jitter
                fy = cy + 0.5 + (_jitter(cx, cy, cz, seed, 1) - 0.5) * jitter
                fz = cz + 0.5 + (_jitter(cx, cy, cz, seed, 2) - 0.5) * jitter
                d = np.sqrt(((q[:, 0] - fx) * s[0]) ** 2 + ((q[:, 1] - fy) * s[1]) ** 2 + ((q[:, 2] - fz) * s[2]) ** 2)
                np.minimum(f2, np.maximum(f1, d), out=f2)
                np.minimum(f1, d, out=f1)
    return f1, f2


def cell_profile(p, size, seed=0, stretch=(1.0, 1.0, 1.0), groove=0.28, dome=0.45):
    """Height in [0, 1] of a mosaic of cells: a plateau per cell with a groove along every border.

    `groove` is the border width as a fraction of the cell size, `dome` how much each cell bulges in the middle."""
    f1, f2 = worley(p, size, seed, stretch)
    edge = (f2 - f1) / max(size * groove * 2.0, 1e-6)
    t = np.clip(edge, 0.0, 1.0)
    plate = t * t * (3.0 - 2.0 * t)
    if dome <= 0:
        return plate
    u = np.clip(1.0 - f1 / (size * 0.62), 0.0, 1.0)
    return (1.0 - dome) * plate + dome * plate * (u * u * (3.0 - 2.0 * u))


def worley2(u, v, size, seed=0, stretch=(1.0, 1.0), groove=0.28, dome=0.45, wrap=None):
    """`cell_profile` on a parametric surface. `wrap` is the period of u (a circumference), so cells join seamlessly."""
    u = np.asarray(u, np.float64)
    v = np.asarray(v, np.float64)
    u, v = np.broadcast_arrays(u, v)
    if wrap:
        a = u * (2.0 * math.pi / wrap)
        r = wrap / (2.0 * math.pi)
        p = np.stack([r * np.cos(a), r * np.sin(a), v], -1)
        st = (stretch[0], stretch[0], stretch[1])
    else:
        p = np.stack([u, np.zeros_like(u), v], -1)
        st = (stretch[0], 1.0, stretch[1])
    return cell_profile(p.reshape(-1, 3), size, seed, st, groove, dome).reshape(u.shape)


# --------------------------------------------------------------------------------------------- mesh deformation
def _apply(mesh, fn, recompute=True):
    out = Mesh()
    for pos, nrm, idx in mesh.parts:
        p = np.asarray(fn(pos.astype(np.float64), nrm.astype(np.float64)), np.float32)
        out.parts.append((p, compute_normals(p, idx) if recompute else nrm, idx))
    return out


def warp(mesh, field):
    """Push every vertex through a world-space displacement field  field(pos) -> delta."""
    return _apply(mesh, lambda p, n: p + field(p))


def relief(mesh, height, scale=1.0):
    """Displace along the vertex normal by  height(pos) (a scalar per vertex)."""
    return _apply(mesh, lambda p, n: p + n * (np.asarray(height(p), np.float64).reshape(-1, 1) * scale))


def noise_field(amp, freq, octaves=3, seed=0, weight=None):
    """Smooth vector noise: the shared warp that takes the machined look off a whole model."""
    def field(p):
        d = np.empty_like(p)
        for c in range(3):
            d[:, c] = fbm3(p[:, 0] * freq + 13.7 * c, p[:, 1] * freq + 5.1 * c, p[:, 2] * freq + 29.3 * c,
                           1.0, octaves, seed + 7 * c)
        d = d * np.asarray(amp, np.float64)
        if weight is not None:
            d = d * np.asarray(weight(p), np.float64).reshape(-1, 1)
        return d
    return field


def cell_relief(size, amp, seed=0, stretch=(1.0, 1.0, 1.0), groove=0.28, dome=0.45, bias=0.0):
    """Height function for `relief`: a mosaic of cells."""
    def height(p):
        return (cell_profile(p, size, seed, stretch, groove, dome) - 0.5) * amp + bias
    return height


def fibre_relief(amp, across, along, seed=0, axis=0, octaves=3):
    """Height function that grooves a surface into parallel fibre bundles running along `axis`."""
    f = np.ones(3) * float(across)
    f[axis] = float(along)

    def height(p):
        return amp * fbm3(p[:, 0] * f[0], p[:, 1] * f[1], p[:, 2] * f[2], 1.0, octaves, seed)
    return height


def bumpy(amp, freq, octaves=3, seed=0):
    def height(p):
        return amp * fbm3(p[:, 0] * freq, p[:, 1] * freq, p[:, 2] * freq, 1.0, octaves, seed)
    return height


def combine(*heights):
    def height(p):
        return sum(np.asarray(h(p), np.float64).reshape(-1) for h in heights)
    return height


def warp_parts(parts, field):
    """Apply one displacement field to every part of a model, keeping nested layers in register."""
    for part in parts:
        if part.mesh.parts:
            part.mesh = warp(part.mesh, field)
    return parts


def relief_part(part, height, scale=1.0):
    part.mesh = relief(part.mesh, height, scale)
    return part


def sag_field(amp_xz=0.035, amp_y=0.085, freq=1.6, seed=0, octaves=2, shear=0.014, shear_freq=2.6):
    """A warp that is (mostly) a function of x and z only, so a vertical column of tissue moves as a unit.

    Stacked layers therefore slide together and can never poke through one another, however thin they are, while
    the block as a whole sags, its free surfaces billow and its side walls bow. A small fully three-dimensional
    term on top breaks the remaining parallelism."""
    def field(p):
        x, z = p[:, 0], p[:, 2]
        d = np.empty_like(p)
        d[:, 0] = amp_xz * fbm3(x * freq, 3.1, z * freq, 1.0, octaves, seed)
        d[:, 2] = amp_xz * fbm3(x * freq + 7.3, 9.7, z * freq + 2.1, 1.0, octaves, seed + 3)
        d[:, 1] = amp_y * fbm3(x * freq + 1.7, 0.5, z * freq + 5.5, 1.0, octaves, seed + 5)
        if shear:
            d[:, 1] += shear * fbm3(x * shear_freq, p[:, 1] * shear_freq, z * shear_freq, 1.0, 2, seed + 9)
        return d
    return field


def grain_field(amp=0.006, across=13.0, along=3.0, axis=0, seed=0, octaves=3):
    """Fine position-based warp with an anisotropic frequency: surfaces come out striated along `axis`, the way
    collagen-rich tissue does. Because it depends only on position it can never open a gap between layers."""
    f = np.ones(3) * float(across)
    f[axis] = float(along)

    def field(p):
        d = np.empty_like(p)
        for c in range(3):
            d[:, c] = amp * fbm3(p[:, 0] * f[0] + 3.3 * c, p[:, 1] * f[1] + 11.9 * c, p[:, 2] * f[2] + 7.7 * c,
                                 1.0, octaves, seed + 5 * c)
        return d
    return field


def texture(parts, seed=0, grain=0.006, grain_across=13.0, grain_along=3.0, grain_axis=0, micro=0.0045,
            micro_freq=26.0):
    """The finishing pass for models that are already built around a curved axis (vessels, nerves, muscle): just
    the tissue grain and the cell-sized micro-relief, with no extra sag."""
    fields = []
    if grain:
        fields.append(grain_field(grain, grain_across, grain_along, grain_axis, seed + 31))
    if micro:
        fields.append(grain_field(micro, micro_freq, micro_freq, 0, seed + 57, octaves=2))
    if not fields:
        return parts
    if len(fields) == 1:
        return warp_parts(parts, fields[0])
    return warp_parts(parts, lambda p: sum(f(p) for f in fields))


def dome_field(amp, rx=1.0, rz=0.7, power=1.0):
    """Bend a block over a sphere. Organs that are curved in life - cornea, retina, a stretch of gut wall - read as
    slabs if every layer is a plane; one shared dome fixes that without moving the layers relative to each other."""
    def field(p):
        d = np.zeros_like(p)
        q = 1.0 - (p[:, 0] / rx) ** 2 - (p[:, 2] / rz) ** 2
        d[:, 1] = amp * np.sign(q) * np.abs(q) ** power
        return d
    return field


def settle(parts, seed=0, amp_xz=0.035, amp_y=0.085, freq=1.6, octaves=2, shear=0.014, grain=0.006,
           grain_across=13.0, grain_along=3.0, grain_axis=0, micro=0.0045, micro_freq=26.0, dome=None):
    """The finishing pass every block model gets: one warp shared by all its layers, so the slab stops looking
    milled - surfaces sag and billow, side walls bow, no two interfaces stay parallel, and every surface picks up
    a tissue grain and a cell-sized micro-relief.

    All three terms are pure functions of position, so nested layers move together. As long as each term's
    amplitude x frequency stays well below 1 the warp cannot fold the mesh or push one layer through another."""
    fields = [sag_field(amp_xz, amp_y, freq, seed, octaves, shear)]
    if dome:
        fields.append(dome_field(*dome))
    if grain:
        fields.append(grain_field(grain, grain_across, grain_along, grain_axis, seed + 31))
    if micro:
        fields.append(grain_field(micro, micro_freq, micro_freq, 0, seed + 57, octaves=2))
    if len(fields) == 1:
        return warp_parts(parts, fields[0])
    return warp_parts(parts, lambda p: sum(f(p) for f in fields))


# --------------------------------------------------------------------------------------------- swept tubes
class Sweep:
    """A tube built around a curved centreline, with a radius that is a free function of angle and position.

    r(theta, s) is evaluated on an (n_theta x n_s) grid, where s runs 0..1 along the path. Nothing about the result
    is a surface of revolution: the axis bends, the section is out of round, and the radius carries as much relief
    as the caller puts into it."""

    def __init__(self, path, n_theta=224, n_s=96):
        from .geometry import smooth_path
        path = np.asarray(path, np.float64)
        if len(path) != n_s:
            path = smooth_path(path, n_s) if len(path) > 2 else np.linspace(path[0], path[-1], n_s)
            if len(path) > n_s:
                path = path[np.linspace(0, len(path) - 1, n_s).astype(int)]
            elif len(path) < n_s:
                path = np.vstack([path, np.repeat(path[-1:], n_s - len(path), 0)])
        self.path = path
        self.n_theta, self.n_s = n_theta, n_s
        self.t, self.nrm, self.bi = frames(path)
        th = np.linspace(0, 2 * math.pi, n_theta, endpoint=False)
        s = np.linspace(0.0, 1.0, n_s)
        self.T, self.S = np.meshgrid(th, s, indexing="ij")
        seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
        self.length = float(seg.sum())
        self.arc = np.concatenate([[0.0], np.cumsum(seg)])
        self.A = np.broadcast_to(self.arc[None, :], self.T.shape)

    def eval(self, r):
        r = np.broadcast_to(np.asarray(r(self.T, self.S) if callable(r) else r, np.float64), self.T.shape)
        c, s = np.cos(self.T), np.sin(self.T)
        return (self.path[None, :, :] + self.nrm[None, :, :] * (r * c)[:, :, None]
                + self.bi[None, :, :] * (r * s)[:, :, None])

    def points(self, r):
        return self.eval(r).reshape(-1, 3)

    def frame_at(self, s, theta, r):
        """World position of one (s in 0..1, theta) sample at radius r."""
        i = int(np.clip(round(s * (self.n_s - 1)), 0, self.n_s - 1))
        return self.path[i] + self.nrm[i] * (r * math.cos(theta)) + self.bi[i] * (r * math.sin(theta))

    def curve(self, s, theta, r):
        """World polyline through (s, theta, r) samples - for anything that runs inside or around the tube:
        collagen bundles, vasa vasorum, nerve fibres, muscle cells."""
        s = np.clip(np.asarray(s, np.float64), 0.0, 1.0)
        theta = np.broadcast_to(np.asarray(theta, np.float64), s.shape)
        r = np.broadcast_to(np.asarray(r, np.float64), s.shape)
        f = s * (self.n_s - 1)
        i = np.clip(f.astype(int), 0, self.n_s - 2)
        w = (f - i)[:, None]
        p = self.path[i] * (1 - w) + self.path[i + 1] * w
        nv = self.nrm[i] * (1 - w) + self.nrm[i + 1] * w
        bv = self.bi[i] * (1 - w) + self.bi[i + 1] * w
        return p + nv * (r * np.cos(theta))[:, None] + bv * (r * np.sin(theta))[:, None]

    def _grid(self, flip):
        nt, ns = self.n_theta, self.n_s
        a = np.arange(nt * ns).reshape(nt, ns)
        i0, i1 = a[:, :-1], np.roll(a, -1, axis=0)[:, :-1]
        j0, j1 = a[:, 1:], np.roll(a, -1, axis=0)[:, 1:]
        tri = np.vstack([np.stack([i0.ravel(), i1.ravel(), j0.ravel()], 1),
                         np.stack([i1.ravel(), j1.ravel(), j0.ravel()], 1)])
        return tri[:, ::-1] if flip else tri

    def shell(self, r_in, r_out):
        """Closed tube wall between two radius functions."""
        po = self.eval(r_out).reshape(-1, 3)
        pi = self.eval(r_in).reshape(-1, 3)
        n = len(po)
        idx = [self._grid(False), self._grid(True) + n]
        nt, ns = self.n_theta, self.n_s
        a = np.arange(nt * ns).reshape(nt, ns)
        ring, nxt = np.arange(nt), np.roll(np.arange(nt), -1)
        for col, flip in ((0, True), (ns - 1, False)):
            o0, o1 = a[ring, col], a[nxt, col]
            i0, i1 = o0 + n, o1 + n
            tri = np.vstack([np.stack([o0, o1, i1], 1), np.stack([o0, i1, i0], 1)])
            idx.append(tri[:, ::-1] if flip else tri)
        from .cells import orient_outward
        return orient_outward(Mesh().add(np.vstack([po, pi]), np.vstack(idx)))

    def solid(self, r_out):
        ro = self.eval(r_out).reshape(-1, 3)
        nt, ns = self.n_theta, self.n_s
        idx = [self._grid(False)]
        base = len(ro)
        pos = np.vstack([ro, self.path[0][None], self.path[-1][None]])
        a = np.arange(nt * ns).reshape(nt, ns)
        ring, nxt = np.arange(nt), np.roll(np.arange(nt), -1)
        idx.append(np.stack([np.full(nt, base), a[nxt, 0], a[ring, 0]], 1))
        idx.append(np.stack([np.full(nt, base + 1), a[ring, -1], a[nxt, -1]], 1))
        from .cells import orient_outward
        return orient_outward(Mesh().add(pos, np.vstack(idx)))


def collagen_felt(sw, r_lo, r_hi, count, seed, r_range=(0.010, 0.028), pitch=(-2.4, 2.4), waves=3.0, samples=46,
                  segments=7):
    """Wavy collagen bundles wound round a swept tube at mixed pitches.

    Dense connective tissue - adventitia, epineurium, epimysium, periosteum, dermis - is a felt of these, and
    modelling them as real geometry is what stops those layers looking like shrink-wrap."""
    from .geometry import tube
    rng = np.random.default_rng(seed)
    m = Mesh()
    s = np.linspace(0.0, 1.0, samples)
    taper_prof = 0.55 + 0.45 * np.sin(np.linspace(0, math.pi, samples)) ** 0.35
    for _ in range(count):
        th0 = rng.uniform(0, 2 * math.pi)
        p = rng.uniform(*pitch)
        ph = rng.uniform(0, 2 * math.pi)
        theta = th0 + p * s + 0.22 * np.sin(waves * math.pi * s + ph)
        u = np.clip(rng.uniform(0.05, 0.95) + 0.16 * np.sin(2.3 * math.pi * s + ph * 1.7), 0.02, 0.98)
        lo = r_lo(theta, s) if callable(r_lo) else np.full(samples, float(r_lo))
        hi = r_hi(theta, s) if callable(r_hi) else np.full(samples, float(r_hi))
        r = lo + u * (hi - lo)
        m.extend(tube(sw.curve(s, theta, r), rng.uniform(*r_range) * taper_prof, segments))
    return m


def cell_lattice(x, y, z, size, amp, seed=0, warp=0.30, octaves=2):
    """Cell-sized relief evaluated directly on a voxel grid - a sine lattice pushed around by low-frequency noise.

    Subtract it from a signed-distance field and a smooth sheet of tissue turns into a sheet of bulging cells. It is
    far cheaper than a true Worley field, which matters when the grid has ten million voxels."""
    f = 2.0 * math.pi / float(size)
    w = warp * size
    wx = w * fbm3(x * 1.7, y * 1.7, z * 1.7, 1.0, octaves, seed)
    wy = w * fbm3(x * 1.9 + 5.1, y * 1.9, z * 1.9 + 2.3, 1.0, octaves, seed + 4)
    wz = w * fbm3(x * 1.6 + 9.4, y * 1.6 + 3.7, z * 1.6, 1.0, octaves, seed + 8)
    return amp * (np.sin(f * (x + wx)) * np.sin(f * (y + wy)) * np.sin(f * (z + wz)))


def tubule(path, r_lumen, r_outer, seed=0, cell=0.055, amp=0.009, aspect=1.0, lobe=(5, 0.06), calibre=0.06,
           n_theta=72, n_s=None):
    """A duct or tubule whose wall is built from its own cells.

    Both surfaces carry the same mosaic of bulges, so the wall keeps its thickness while the tube stops being a
    pipe: cells press into the lumen, the calibre wanders, and the section is never quite round."""
    path = np.asarray(path, np.float64)
    n_s = n_s or max(40, min(220, len(path)))
    sw = Sweep(path, n_theta, n_s)
    rng = np.random.default_rng(abs(int(seed)) + 3)
    shared = rsum(1.0,
                  lobed(lobe[0], lobe[1], 0.9),
                  surf_noise(calibre, 2.4, 3.0, seed + 11),
                  cells_on(cell, amp / max(r_outer, 1e-6), seed + 17, aspect=aspect, groove=0.24, dome=0.6,
                           r_typ=r_outer, length=float(np.linalg.norm(np.diff(path, axis=0), axis=1).sum())))
    del rng
    return sw, sw.shell(rmul(r_lumen, shared), rmul(r_outer, shared))


def curved_path(length=2.0, bend=(0.0, 0.0), wobble=0.0, freq=1.4, seed=0, n=140, axis=0):
    """A gently curved centreline along one axis: a shallow arc plus low-frequency meander."""
    rng = np.random.default_rng(abs(int(seed)) + 1)
    t = np.linspace(-1.0, 1.0, n)
    p = np.zeros((n, 3))
    p[:, axis] = t * (length / 2.0)
    other = [i for i in range(3) if i != axis]
    arc = 1.0 - t ** 2
    ph = rng.uniform(0, 2 * math.pi, 2)
    for k, c in enumerate(other):
        p[:, c] = bend[k] * arc
        if wobble:
            p[:, c] += wobble * np.sin(t * freq * math.pi + ph[k]) * (0.35 + 0.65 * arc)
    return p


def lobed(n_lobes, amp, phase_drift=0.8, harmonics=((2, 0.28), (3, 0.14))):
    """Radius modulation that throws a tube into longitudinal folds (a contracted artery's wavy intima)."""
    def f(T, S):
        ph = phase_drift * np.sin(S * 2.6 * math.pi) + 0.5 * np.sin(S * 1.3 * math.pi + 1.1)
        v = np.cos(n_lobes * T + ph)
        for mult, w in harmonics:
            v = v + w * np.cos(n_lobes * mult * T + ph * mult * 0.6 + 0.7 * mult)
        return amp * v / (1.0 + sum(w for _, w in harmonics))
    return f


def surf_noise(amp, freq_t, freq_s, seed=0, octaves=3):
    """fbm on the (theta, s) grid of a Sweep, wrapping correctly around the circumference."""
    def f(T, S):
        return amp * fbm3(np.cos(T) * freq_t, np.sin(T) * freq_t, S * freq_s, 1.0, octaves, seed)
    return f


def rsum(*fns):
    """Add radius terms (numbers or callables of (T, S))."""
    def f(T, S):
        total = 0.0
        for g in fns:
            total = total + (g(T, S) if callable(g) else g)
        return total
    return f


def rmul(*fns):
    def f(T, S):
        total = 1.0
        for g in fns:
            total = total * (g(T, S) if callable(g) else g)
        return total
    return f


def cells_on(size, amp, seed=0, aspect=1.0, groove=0.3, dome=0.5, r_typ=0.3, length=2.0):
    """Radius relief: a mosaic of cells wrapped around a tube, `aspect` times longer along it than around it."""
    wrap = 2.0 * math.pi * r_typ

    def f(T, S):
        return (worley2(T * r_typ, S * length, size, seed, (1.0, float(aspect)), groove, dome,
                        wrap=wrap) - 0.5) * amp
    return f


def taper(profile):
    """Radius factor along the tube from a few control values, smoothly interpolated."""
    vals = np.asarray(profile, np.float64)
    xs = np.linspace(0.0, 1.0, len(vals))

    def f(T, S):
        return np.interp(S, xs, vals)
    return f
