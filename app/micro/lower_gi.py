"""Gross specimens of the lower gut: the ileocaecal region with the appendix, and the rectum and anal canal.

Unlike the tissue blocks, these are whole opened specimens at dissection scale (1 unit = 6 cm). Each is written as a
set of signed-distance fields in cylindrical coordinates about the gut's own axis: every coat of the wall is the
band between two radius functions of height and angle, so haustra, taeniae, semilunar folds, rectal folds and anal
columns are all just terms in those radii, and neighbouring layers stay in register by construction. Every part is
evaluated on its own grid (fine for the anal canal, coarser for fat and muscle) and the specimens are opened with a
flat cut, so the section shows each layer as a clean band.

(a) Ileocaecal region, viewed through a window in the front of the caecum; (b) rectum and anal canal, the posterior
half of a coronal section."""
import math

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.spatial import cKDTree

from .base import Part
from .geometry import Mesh, ellipsoid, tube
from .sdf import BIG, Volume, round_cone

A_OFF = np.array([-1.42, 0.0, 0.0])      # ileocaecal specimen
B_OFF = np.array([1.30, 0.0, 0.0])       # rectum & anal canal


# =============================================================================== field helpers
def _ss(x, a, b):
    t = np.clip((np.asarray(x, np.float32) - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _band(x, a, b, c, d):
    """Rises from 0 to 1 over [a, b] and falls back over [c, d]."""
    return _ss(x, a, b) * (1.0 - _ss(x, c, d))


def _wrap(a):
    return (a + np.pi) % (2 * np.pi) - np.pi


def _full(d, shape):
    return np.ascontiguousarray(np.broadcast_to(np.asarray(d, np.float32), shape), dtype=np.float32)


def _mesh(fn, lo, hi, voxel, smooth=0.8):
    """Polygonise fn(x, y, z) (negative inside) on its own grid over the box lo..hi."""
    v = Volume(lo, hi, voxel)
    x, y, z = v.axes()
    v.d = _full(fn(x, y, z), v.shape)
    return v.mesh(smooth)


def _slices(x, y, z, bmin, bmax):
    ax = (x.ravel(), y.ravel(), z.ravel())
    sl = []
    for a, lo, hi in zip(ax, bmin, bmax):
        i0 = int(np.searchsorted(a, lo, "left"))
        i1 = int(np.searchsorted(a, hi, "right"))
        if i1 <= i0:
            return None
        sl.append(slice(i0, i1))
    return tuple(sl)


def _capsules(x, y, z, paths, radii, pad=0.0):
    """Union of tapered capsules along polylines, each segment evaluated only inside its own bounding box."""
    shape = (x.shape[0], y.shape[1], z.shape[2])
    out = np.full(shape, BIG, np.float32)
    for path, rad in zip(paths, radii):
        path = np.asarray(path, np.float32)
        rad = np.broadcast_to(np.asarray(rad, np.float32), (len(path),))
        for i in range(len(path) - 1):
            fn, bmin, bmax = round_cone(path[i], path[i + 1], float(rad[i]), float(rad[i + 1]))
            sl = _slices(x, y, z, np.asarray(bmin) - pad - 0.02, np.asarray(bmax) + pad + 0.02)
            if sl is None:
                continue
            d = fn(x[sl[0]], y[:, sl[1]], z[:, :, sl[2]])
            np.minimum(out[sl], d, out=out[sl])
    return out


def _cloud(x, y, z, pts, half):
    """A sheet of tissue: distance to a dense point sampling of a surface, minus half its thickness."""
    shape = (x.shape[0], y.shape[1], z.shape[2])
    out = np.full(shape, BIG, np.float32)
    pts = np.asarray(pts, np.float64)
    reach = half + 0.03
    sl = _slices(x, y, z, pts.min(axis=0) - reach, pts.max(axis=0) + reach)
    if sl is None:
        return out
    X, Y, Z = np.broadcast_arrays(x[sl[0]], y[:, sl[1]], z[:, :, sl[2]])
    q = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
    dist, _ = cKDTree(pts).query(q, distance_upper_bound=reach)
    dist = np.where(np.isfinite(dist), dist, BIG).reshape(X.shape).astype(np.float32)
    out[sl] = dist - half
    return out


def _ellipsoid(x, y, z, c, radii, axes=None):
    """Approximate distance to an ellipsoid; `axes` are its three local axes as rows."""
    px, py, pz = x - c[0], y - c[1], z - c[2]
    if axes is not None:
        a = np.asarray(axes, np.float32)
        px, py, pz = (a[0, 0] * px + a[0, 1] * py + a[0, 2] * pz, a[1, 0] * px + a[1, 1] * py + a[1, 2] * pz,
                      a[2, 0] * px + a[2, 1] * py + a[2, 2] * pz)
    r = np.asarray(radii, np.float32)
    k0 = np.sqrt((px / r[0]) ** 2 + (py / r[1]) ** 2 + (pz / r[2]) ** 2)
    k1 = np.sqrt((px / r[0] ** 2) ** 2 + (py / r[1] ** 2) ** 2 + (pz / r[2] ** 2) ** 2)
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)


def _poly2d(u, v, pts):
    """Distance from points (u, v) to a 2-D polyline."""
    pts = np.asarray(pts, np.float32)
    best = None
    for (a0, a1), (b0, b1) in zip(pts[:-1], pts[1:]):
        du, dv = b0 - a0, b1 - a1
        t = np.clip(((u - a0) * du + (v - a1) * dv) / (du * du + dv * dv), 0.0, 1.0)
        d = np.sqrt((u - a0 - t * du) ** 2 + (v - a1 - t * dv) ** 2)
        best = d if best is None else np.minimum(best, d)
    return best


def _smooth(path, n):
    """Catmull-Rom resampling of a few control points into a smooth polyline."""
    p = np.asarray(path, float)
    p = np.vstack([2 * p[0] - p[1], p, 2 * p[-1] - p[-2]])
    out = []
    for i in range(1, len(p) - 2):
        for t in np.linspace(0, 1, n, endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p[i]) + (-p[i - 1] + p[i + 1]) * t + (2 * p[i - 1] - 5 * p[i] + 4 * p[i + 1] - p[i + 2]) * t2
                              + (-p[i - 1] + 3 * p[i] - 3 * p[i + 1] + p[i + 2]) * t3))
    out.append(p[-2])
    return np.array(out)


def _quads(ny, nt, wrap=False, flip=False):
    a = np.arange(ny * nt).reshape(ny, nt)
    b = np.roll(a, -1, axis=1) if wrap else a[:, 1:]
    a = a if wrap else a[:, :-1]
    q0, q1, q2, q3 = a[:-1].ravel(), a[1:].ravel(), b[1:].ravel(), b[:-1].ravel()
    t = np.concatenate([np.stack([q0, q1, q3], 1), np.stack([q1, q2, q3], 1)])
    return t[:, ::-1] if flip else t


def _strip(a, b, expect):
    """Close the gap between two matching boundary curves with a ribbon whose normal faces `expect`."""
    n = len(a)
    i = np.arange(n - 1)
    tri = np.concatenate([np.stack([i, i + 1, n + i], 1), np.stack([i + 1, n + i + 1, n + i], 1)])
    pos = np.concatenate([a, b])
    t = pos[tri]
    nsum = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]).sum(axis=0)
    if float(nsum @ np.asarray(expect, float)) < 0:
        tri = tri[:, ::-1]
    return pos, tri


def _shell(r_in, r_out, ys, ths, axis=None, full=False, keep=None, caps=True):
    """A closed wall coat between two radius functions r(y, theta) about a vertical axis: inner and outer surfaces,
    flat caps where theta starts and ends (the section faces) and annular caps at the ends of the y range.
    `keep(centroids)` optionally drops quads (a hole that another part fills)."""
    def surf(r_fn):
        def f(Y, T):
            R = np.broadcast_to(r_fn(Y, T), np.broadcast_shapes(Y.shape, T.shape))
            cx = axis(Y) if axis is not None else 0.0
            return cx + R * np.cos(T), np.broadcast_to(Y, R.shape), R * np.sin(T)
        return f
    return _surf_shell(surf(r_in), surf(r_out), ys, ths, full, keep, caps)


def _surf_shell(s_in, s_out, vs, ths, full=False, keep=None, caps=True):
    """Closed shell between two parametric surfaces s(v, theta) -> (x, y, z), sampled on rows vs and columns ths."""
    vs = np.asarray(vs, np.float32)
    ths = np.asarray(ths, np.float32)
    V, T = vs[:, None], ths[None, :]
    ny, nt = len(vs), len(ths)

    def grid(sf):
        return np.stack([np.broadcast_to(c, (ny, nt)) for c in sf(V, T)], -1).astype(np.float32)
    Pi, Po = grid(s_in), grid(s_out)
    m = Mesh()
    for P, flip in ((Po, False), (Pi, True)):
        tri = _quads(ny, nt, full, flip)
        if keep is not None:
            c = P.reshape(-1, 3)[tri].mean(axis=1)
            tri = tri[keep(c)]
        if len(tri):
            m.add(P.reshape(-1, 3), tri)
    if not caps:
        return m
    for row, sgn in ((0, -1.0), (ny - 1, 1.0)):
        a, b = Pi[row], Po[row]
        if full:
            a, b = np.vstack([a, a[:1]]), np.vstack([b, b[:1]])
        d = (Po[min(row + 1, ny - 1)] - Po[max(row - 1, 0)]).mean(axis=0)
        m.add(*_strip(a, b, sgn * d))
    if not full:
        for col, sgn in ((0, -1.0), (nt - 1, 1.0)):
            d = (Po[:, min(col + 1, nt - 1)] - Po[:, max(col - 1, 0)]).mean(axis=0)
            m.add(*_strip(Pi[:, col], Po[:, col], sgn * d))
    return m


def _rows(*spans):
    """Concatenate linspace spans [(y0, y1, step), ...] into one increasing sample of heights."""
    out = []
    for y0, y1, step in spans:
        n = max(2, int(round((y1 - y0) / step)) + 1)
        seg = np.linspace(y0, y1, n)
        out.append(seg if not out else seg[1:])
    return np.concatenate(out)


def _part(mesh, offset, name, group, color, desc, category, rank=0.0, label=True):
    if offset is not None and mesh.parts:
        mesh = mesh.transformed(offset=tuple(float(o) for o in offset))
    return Part(name, group, color, mesh, desc, category=category, rank=rank, label=label)


# =============================================================================== (b) rectum & anal canal
YTOP = 1.35          # transverse cut through the rectosigmoid junction
YARJ = -0.56         # anorectal junction (puborectalis level)
YP = -0.87           # pectinate line
YWL = -1.0           # intersphincteric groove / white line, lower edge of the internal sphincter
TM, TS, TL = 0.024, 0.024, 0.022      # mucosa, submucosa, longitudinal muscle
CUSHIONS = (0.0, -0.75 * np.pi, 0.75 * np.pi)      # left lateral, right posterior, right anterior (3, 7, 11 o'clock)
FOLDS = ((0.86, 0.0, 0.16), (0.36, np.pi, 0.23), (-0.07, 0.0, 0.16))    # (height, side, depth): left, right, left

_R0 = PchipInterpolator([-1.05, -0.9, -0.66, -0.57, -0.45, -0.3, -0.1, 0.2, 0.6, 1.0, 1.45],
                        [0.10, 0.10, 0.11, 0.15, 0.27, 0.40, 0.45, 0.41, 0.31, 0.245, 0.23])


def _r_axis(y):
    """Lateral flexures: the upper and lower bends convex to the right, the middle one to the left."""
    return -0.055 * np.cos(2 * np.pi * (y - 0.86)) * _ss(y, -0.6, -0.2)


def _rcyl(x, y, z):
    dx = x - _r_axis(y)
    return np.sqrt(dx * dx + z * z), np.arctan2(z, dx)


def _cushion(th, y):
    c = sum(np.exp(-(_wrap(th - a) / 0.36) ** 2) for a in CUSHIONS)
    return c * _band(y, -0.86, -0.79, -0.66, -0.57)


def _columns(th):
    """1 on the crest of each of the 8 anal columns, 0 midway between them (where the cut plane falls)."""
    return ((1.0 + np.cos(8.0 * (th - np.pi / 8.0))) * 0.5) ** 2


def _col_env(y):
    return _band(y, YP + 0.004, YP + 0.03, -0.64, -0.57)


def _radii(y, th):
    """Boundaries of the wall, inside out: lumen, mucosa|submucosa, submucosa|circular, circular|longitudinal, outer."""
    r0 = _R0(np.clip(y, -1.05, 1.45)).astype(np.float32)
    cu = _cushion(th, y)
    col = 0.028 * _columns(th) * _col_env(y)
    F = _folds(y, th)
    rl = r0 - col - 0.042 * cu - F
    r1 = r0 + TM - 0.038 * cu - 0.95 * F
    r2 = r0 + TM + TS + 0.012 * cu - 0.85 * F
    r3 = r2 + 0.028 + 0.034 * _ss(y, -0.45, -0.62) + 0.8 * F    # circular coat thickens into the internal sphincter
    r4 = r3 + TL
    return rl, r1, r2, r3, r4


def _fold_profile(dy, a=0.038):
    """Cross-section of a transverse fold: a plate with a rounded free edge and a fillet where it meets the wall."""
    core = np.clip(1.0 - (dy / a) ** 2, 0.0, 1.0) ** 0.6
    return np.maximum(core, 0.12 * np.exp(-(dy / (2.2 * a)) ** 2))


def _fold(k, y, th):
    yf, side, depth = FOLDS[k]
    w = np.clip(np.cos(_wrap(th - side)) * 1.25, 0.0, 1.0) ** 0.9
    return depth * w * _fold_profile(y - yf + 0.012 * w)


def _folds(y, th):
    return sum(_fold(k, y, th) for k in range(len(FOLDS)))


def _between(rho, a, b):
    return np.maximum(a - rho, rho - b)


def _ycut(d, y, lo, hi):
    return np.maximum(np.maximum(d, lo - y), y - hi)


def _lev_y(rho):
    """Upper-to-lower centre surface of levator ani as a height over the radius: a funnel sagging into a bowl."""
    return -0.575 + 0.93 * (rho - 0.27) - 0.22 * (rho - 0.27) * (1.0 - rho)


LEV_HALF = 0.03
RMAX = 0.9          # lateral edge of the specimen
SKIN = [(0.112, -0.985), (0.118, -1.06), (0.15, -1.14), (0.22, -1.19), (0.34, -1.215), (0.7, -1.225), (1.02, -1.228)]
SKIN_HALF = 0.016


def _skin_y(rho):
    s = np.array(SKIN[2:])
    return np.interp(rho, s[:, 0], s[:, 1]).astype(np.float32)


def _levator(rho, y):
    return np.maximum((np.abs(y - _lev_y(rho)) - LEV_HALF) / 1.33, np.maximum(0.25 - rho, rho - 0.985))


def _puborectalis(x, y, z):
    rho, th = _rcyl(x, y, z)
    q = np.sqrt(((rho - 0.335) / 0.078) ** 2 + ((y + 0.57) / 0.062) ** 2)
    return (q - 1.0) * 0.062


def _eas(rho, th, y, which):
    rl, r1, r2, r3, r4 = _radii(y, th)
    if which == "deep":
        q = np.sqrt(((rho - 0.26) / 0.1) ** 2 + ((y + 0.71) / 0.085) ** 2)
        d = (q - 1.0) * 0.085
    elif which == "superficial":
        ext = 1.0 + 0.8 * np.maximum(0.0, -np.sin(th)) ** 2
        q = np.sqrt(((rho - 0.26) / (0.105 * ext)) ** 2 + ((y + 0.885) / 0.085) ** 2)
        d = (q - 1.0) * 0.085
    else:
        q = np.sqrt(((rho - 0.195) / 0.066) ** 2 + ((y + 1.085) / 0.052) ** 2)
        d = (q - 1.0) * 0.052
        d = np.maximum(d, -(_poly2d(rho, y, SKIN) - SKIN_HALF - 0.006))
    return np.maximum(d, (r4 + 0.005) - rho)


def _eas_all(x, y, z):
    rho, th = _rcyl(x, y, z)
    return np.minimum(np.minimum(_eas(rho, th, y, "deep"), _eas(rho, th, y, "superficial")),
                      _eas(rho, th, y, "sub"))


def _cushion_veins(internal=True, seed=3):
    """Tortuous submucosal veins: the internal plexus in the three anal cushions, the external one under the skin."""
    rng = np.random.default_rng(seed)
    paths, radii = [], []
    if internal:
        for c in CUSHIONS:
            for k in range(16):
                a = c + rng.uniform(-0.3, 0.3)
                ys = np.linspace(-0.83, -0.6, 9)
                pts = []
                for i, yy in enumerate(ys):
                    th = a + 0.07 * math.sin(i * 1.7 + k) + rng.normal(0, 0.03)
                    rl, r1, r2, r3, r4 = (float(np.asarray(v).ravel()[0]) for v in _radii(np.float32(yy), np.float32(th)))
                    rr = r1 + (r2 - r1) * rng.uniform(0.35, 0.65)
                    pts.append((_r_axis(yy) + rr * math.cos(th), yy + rng.normal(0, 0.006), rr * math.sin(th)))
                paths.append(_smooth(pts, 5))
                radii.append(rng.uniform(0.008, 0.0125))
    else:
        for k in range(26):
            a0 = rng.uniform(-np.pi, np.pi)
            rr = rng.uniform(0.28, 0.44)
            pts = []
            for i in range(7):
                a = a0 + i * 0.09
                r = rr + rng.normal(0, 0.012)
                pts.append((r * math.cos(a), float(_skin_y(np.float32(r))) + SKIN_HALF + 0.022 + rng.normal(0, 0.004),
                            r * math.sin(a)))
            paths.append(_smooth(pts, 4))
            radii.append(rng.uniform(0.009, 0.013))
    return paths, radii


def _rectal_vessels():
    """Superior rectal artery and vein: down the back of the mesorectum, dividing into right and left branches that
    run to the ampulla and pierce the wall."""
    art, vein = [], []
    for side in (-0.30 * np.pi, -0.70 * np.pi):
        for off, dr, out in ((0.0, 0.07, art), (0.10, 0.11, vein)):
            th = side + off
            pts = [(0.03 + off * 0.3, YTOP, -0.53 - dr * 0.2), (0.02 + off * 0.3, 1.12, -0.5 - dr * 0.2)]
            for yy in (0.9, 0.62, 0.34, 0.06, -0.16):
                t = (1.0 - (yy + 0.16) / 1.06)
                a = -np.pi / 2 + (th + np.pi / 2) * min(1.0, 0.35 + 1.2 * t)
                r4 = float(np.asarray(_radii(np.float32(yy), np.float32(a))[4]).ravel()[0])
                rr = r4 + dr * (1.0 - 0.5 * t)
                pts.append((_r_axis(yy) + rr * math.cos(a), yy, rr * math.sin(a)))
            rl, r1, r2, r3, r4 = (float(np.asarray(v).ravel()[0]) for v in _radii(np.float32(-0.3), np.float32(th)))
            pts.append((_r_axis(-0.3) + r2 * math.cos(th), -0.3, r2 * math.sin(th)))
            out.append(_smooth(pts, 6))
    return art, vein


NODES = [(0.62, -0.5 * np.pi, 0.036), (0.25, -0.3 * np.pi, 0.03), (0.08, -0.72 * np.pi, 0.032),
         (0.9, -0.62 * np.pi, 0.028), (0.42, -0.66 * np.pi, 0.034), (0.02, -0.42 * np.pi, 0.03)]


def _node_list():
    out = []
    for yy, th, r in NODES:
        r4 = float(np.asarray(_radii(np.float32(yy), np.float32(th))[4]).ravel()[0])
        m = (0.09 + 0.15 * max(0.0, -math.sin(th))) * (1.0 - 0.55 * float(_ss(yy, 0.8, 1.4)))
        r = min(r, 0.3 * m)
        rr = r4 + 0.004 + 0.5 * m
        out.append(((_r_axis(yy) + rr * math.cos(th), yy, rr * math.sin(th)), (r * 1.25, r * 0.9, r)))
    return out


def _lathe_sheet(rhos, ths, y_top, y_bot):
    """A closed sheet of revolution (the levator funnel) between two height profiles y(rho)."""
    R, T = np.asarray(rhos, np.float32)[:, None], np.asarray(ths, np.float32)[None, :]
    nr, nt = R.shape[0], T.shape[1]

    def surf(fy):
        Y = np.broadcast_to(fy(R), (nr, nt))
        return np.stack([np.broadcast_to(R * np.cos(T), (nr, nt)), Y, np.broadcast_to(R * np.sin(T), (nr, nt))], -1)
    Pt, Pb = surf(y_top), surf(y_bot)
    m = Mesh()
    m.add(Pt.reshape(-1, 3), _quads(nr, nt, flip=True))
    m.add(Pb.reshape(-1, 3), _quads(nr, nt))
    for row, sgn in ((0, -1.0), (nr - 1, 1.0)):
        m.add(*_strip(Pb[row], Pt[row], sgn * Pt[row].mean(axis=0) * [1.0, 0.0, 1.0]))
    for col in (0, nt - 1):
        m.add(*_strip(Pb[:, col], Pt[:, col], (0.0, 0.0, 1.0)))
    t = Pt.reshape(-1, 3)[_quads(nr, nt, flip=True)[:1]][0]
    if np.cross(t[1] - t[0], t[2] - t[0])[1] < 0:                  # make the upper surface face up
        m.parts[0] = (m.parts[0][0], -m.parts[0][1], m.parts[0][2][:, ::-1])
        m.parts[1] = (m.parts[1][0], -m.parts[1][1], m.parts[1][2][:, ::-1])
    return m


def _tubes(paths, r, segments=14):
    m = Mesh()
    for p in paths:
        m.extend(tube(np.asarray(p, float), r, segments, caps=True))
    return m


def _nodes_mesh(nodes):
    m = Mesh()
    for c, r in nodes:
        m.extend(ellipsoid(c, r, res=12))
    return m


def build_rectum():
    """Posterior half of a coronal section through the rectum and anal canal, in its pelvic floor."""
    G = "Rectum & anal canal – "
    parts = []
    art, vein = _rectal_vessels()
    nodes = _node_list()
    ip_paths, ip_radii = _cushion_veins(True)
    ep_paths, ep_radii = _cushion_veins(False, seed=11)

    def half(d, z):
        return np.maximum(d, z)                     # the coronal cut: keep the posterior half

    VF = 0.0048                                    # anal canal detail
    canal_lo, canal_hi = (-0.34, -1.03, -0.34), (0.34, -0.44, 0.012)

    def mk(fn, lo_, hi_, vox, name, color, desc, cat, grp="Rectal wall", smooth=0.8):
        mesh = fn if isinstance(fn, Mesh) else _mesh(fn, lo_, hi_, vox, smooth)
        parts.append(_part(mesh, B_OFF, name, G + grp, color, desc, cat))

    THS = np.linspace(-np.pi, 0.0, 57)

    def shell(k0, k1, ys, keep=None, caps=True):
        return _shell(lambda Y, T: _radii(Y, T)[k0], lambda Y, T: _radii(Y, T)[k1], ys, THS, axis=_r_axis,
                      keep=keep, caps=caps)

    def local(c):
        dx = c[:, 0] - _r_axis(c[:, 1])
        return c[:, 1].astype(np.float32), np.arctan2(c[:, 2], dx).astype(np.float32)

    def in_fold(k):
        return lambda c: _fold(k, *local(c)) > 0.02

    def no_fold(c):
        return _folds(*local(c)) <= 0.02
    fold_rows = [(yf - 0.09, yf + 0.07, 0.005) for yf, _, _ in FOLDS]
    rows_hi = np.unique(np.concatenate([_rows((0.2, YTOP, 0.02))] + [_rows(r) for r in fold_rows[:2]]))
    rows_hi = rows_hi[(rows_hi >= 0.2) & (rows_hi <= YTOP)]
    rows_lo = np.unique(np.concatenate([_rows((-0.5, 0.2, 0.016)), _rows(fold_rows[2])]))
    rows_up = np.unique(np.concatenate([_rows((-0.56, -0.5, 0.01)), rows_lo, rows_hi]))

    def rows_from(y0):
        r = rows_up[rows_up > y0 + 1e-4]
        return np.concatenate([[y0], r])

    # ---- mucosa
    mk(shell(0, 1, rows_hi, no_fold), None, None, None,
       "Rectal mucosa (upper rectum)", "#cc7a72",
       "Glandular mucosa of the rectum: simple columnar epithelium with very many goblet cells in straight crypts, "
       "like the colon but with no taeniae, haustra, appendices epiploicae or mesentery outside it – the taeniae "
       "spread into a continuous longitudinal coat at the rectosigmoid junction (S3). Inspected by rigid or flexible "
       "sigmoidoscopy. Colorectal adenocarcinoma arises here from adenomatous polyps (adenoma–carcinoma sequence: "
       "APC → KRAS → TP53); about a third of colorectal cancers are rectal. It presents with rectal bleeding, "
       "tenesmus and change in bowel habit.", "mucosa")
    mk(shell(0, 1, rows_lo, no_fold), None, None, None,
       "Rectal ampulla", "#c8736d",
       "The dilated lower rectum resting on the pelvic floor, where faeces collect before defecation. Stretch of "
       "its wall (sensed via pelvic splanchnic nerves) gives the call to stool and triggers the rectoanal inhibitory "
       "reflex – the internal sphincter relaxes so the anal canal can 'sample' the contents while the external "
       "sphincter holds. Reachable by digital rectal examination (DRE), which also assesses the prostate or cervix, "
       "rectal tumours and sphincter tone. Low rectal cancers (< 5 cm from the anal verge) may need "
       "abdominoperineal resection with a permanent colostomy.", "mucosa")
    names = ["Superior transverse rectal fold", "Middle transverse rectal fold (Kohlrausch)",
             "Inferior transverse rectal fold"]
    texts = [
        "Upper of the three transverse rectal folds (valves of Houston), projecting from the left wall where the "
        "rectum bends to the right, about 11 cm from the anal verge. The folds are permanent crescentic shelves of "
        "mucosa, submucosa and circular muscle that help support the faecal mass so that flatus can pass without "
        "faeces; they are landmarks – and potential snags – for sigmoidoscopes and biopsy forceps.",
        "The largest and most constant fold, from the right wall about 7–8 cm from the anal verge, at the level of "
        "the peritoneal reflection (floor of the rectovesical/rectouterine pouch). Perforation above it enters the "
        "peritoneal cavity, below it the extraperitoneal pelvis – which matters for biopsies, endoscopic resection "
        "and staging of rectal tumours.",
        "Lowest fold, on the left wall just above the ampulla's widest part. Together the three folds mark the "
        "lateral flexures of the rectum: each fold lies on the concave side of a bend."]
    for k, (nm, tx) in enumerate(zip(names, texts)):
        mk(shell(0, 1, rows_hi if k < 2 else rows_lo, in_fold(k), caps=False), None, None, None, nm, "#b9625c", tx,
           "mucosa")

    # ---- anal canal lining (fine grid)
    def valve(rho, th, y, rl):
        # a low scalloped lip along the pectinate line, rising at each column and dipping between them
        g = _columns(th)
        yv = YP + 0.009 + 0.014 * g
        return np.maximum(_between(rho, rl - 0.02 + 0.008 * g, rl + 0.002), np.maximum(YP - 0.006 - y, y - yv))

    def sinus(rho, th, y, rl):
        free = 1.0 - _columns(th)
        top = YP + 0.012 + 0.03 * np.clip((free - 0.3) / 0.7, 0.0, 1.0) ** 0.6
        return np.maximum(_between(rho, rl - 0.01, rl + 0.011), np.maximum(YP - y, y - top))

    def lining(zone):
        def f(x, y, z):
            rho, th = _rcyl(x, y, z)
            rl, r1 = _radii(y, th)[:2]
            d = _between(rho, rl, r1)
            if zone == "junction":
                d = _ycut(d, y, -0.605, -0.5)
            elif zone == "columns":
                d = _ycut(d, y, YP, -0.605)
                d = np.maximum(d, -sinus(rho, th, y, rl))
            elif zone == "sinuses":
                d = np.maximum(_ycut(d, y, YP, -0.7), sinus(rho, th, y, rl))
            elif zone == "pectinate":
                d = _ycut(d, y, YP - 0.016, YP)
            elif zone == "valves":
                d = np.maximum(valve(rho, th, y, rl), -_between(rho, rl, r1))
            else:
                d = _ycut(d, y, YWL, YP - 0.016)
            return half(d, z)
        return f

    mk(lining("junction"), canal_lo, (0.34, -0.48, 0.012), 0.0062, "Anorectal junction", "#c56c6c",
       "Where the rectum turns into the anal canal as it passes through the pelvic floor, slung forward by "
       "puborectalis (the anorectal angle, ~90°, is key to continence). Its muscular 'anorectal ring' – "
       "puborectalis, the deep external sphincter and the top of the internal sphincter – is palpable on DRE; "
       "dividing it in fistula surgery causes incontinence. The anal canal proper (~4 cm) runs from here to the "
       "anal verge.", "mucosa", "Anal canal lining")
    mk(lining("columns"), canal_lo, canal_hi, VF, "Anal columns (of Morgagni)", "#b65964",
       "Six to ten vertical mucosal ridges in the upper half of the anal canal, each carrying a terminal branch of "
       "the superior rectal artery and vein. Their lining changes from rectal columnar epithelium to the stratified "
       "epithelium of the anal transition zone. Together with the submucosal venous cushions under them they seal "
       "the canal (about 15 % of resting continence).", "mucosa", "Anal canal lining")
    mk(lining("sinuses"), canal_lo, canal_hi, VF, "Anal sinuses", "#8a3848",
       "Small pockets between the bases of the columns, above each anal valve. The ducts of the anal "
       "(intramuscular) glands open into them. Blocked, infected glands cause cryptoglandular sepsis – perianal, "
       "intersphincteric or ischioanal abscesses – and, when these drain onto the skin, anal fistula (Goodsall's "
       "rule relates the external opening to the internal one).", "mucosa", "Anal canal lining")
    mk(lining("valves"), canal_lo, canal_hi, 0.0036, "Anal valves", "#cf8584",
       "Crescentic mucosal folds joining the lower ends of the anal columns. Their free edges lie on the "
       "pectinate line and close off the anal sinuses above them; hard stool can tear them (papillitis, "
       "cryptitis).", "mucosa", "Anal canal lining", smooth=0.7)
    mk(lining("pectinate"), canal_lo, canal_hi, VF, "Pectinate (dentate) line", "#efe0c8",
       "The wavy line of the anal valves, ~2 cm above the anal verge: the junction of hindgut endoderm with "
       "ectoderm (proctodeum). Above it: columnar/transitional epithelium, autonomic (pain-insensitive) nerves, "
       "superior rectal vessels to the portal system and lymph to the inferior mesenteric and internal iliac nodes. "
       "Below it: squamous epithelium, somatic inferior rectal nerve (very pain-sensitive), inferior rectal "
       "vessels to the systemic (caval) veins and lymph to the superficial inguinal nodes. So internal "
       "haemorrhoids (above) are painless and bleed bright red; external haemorrhoids, fissures and anal "
       "squamous carcinoma (below) hurt and drain to the groin.", "mucosa", "Anal canal lining")
    mk(lining("pecten"), canal_lo, canal_hi, VF, "Anal pecten (anoderm)", "#d8a9a3",
       "The smooth zone between the pectinate line and the intersphincteric (white) line: thin, hairless, "
       "non-keratinised stratified squamous epithelium firmly tethered to the underlying internal sphincter, "
       "and exquisitely sensitive. An anal fissure is a longitudinal tear of the anoderm, almost always in the "
       "posterior midline (poorest blood supply), from passage of hard stool: sharp pain on defecation with "
       "bright red blood on the paper. Spasm of the internal sphincter keeps it ischaemic – treated with stool "
       "softeners, topical GTN or diltiazem, botulinum toxin or lateral internal sphincterotomy.", "mucosa",
       "Anal canal lining")

    def skin(x, y, z):
        rho, th = _rcyl(x, y, z)
        d = np.maximum(_poly2d(rho, y, SKIN) - SKIN_HALF, np.maximum(y - YWL, rho - RMAX))
        return half(d, z)
    mk(skin, (-1.0, -1.27, -1.0), (1.0, -0.97, 0.012), 0.011, "Anus & perianal skin", "#b07a62",
       "Below the white line the canal is lined by keratinised, pigmented skin with hairs, sweat and apocrine "
       "glands, which turns out onto the perineum at the anal verge (the anus). Somatic sensation via the inferior "
       "rectal nerve (pudendal, S2–4). A thrombosed external haemorrhoid is a painful blue lump here; perianal "
       "abscesses point here; the anal wink reflex (S2–4) is tested by stroking it.", "skin", "Anal canal lining")

    # ---- submucosa and venous plexuses
    def submucosa(x, y, z):
        rho, th = _rcyl(x, y, z)
        r = _radii(y, th)
        d = _ycut(_between(rho, r[1], r[2]), y, -0.88, -0.56)
        d = np.maximum(d, -(_capsules(x, y, z, ip_paths, ip_radii) - 0.002))
        d = np.maximum(d, -(_capsules(x, y, z, art + vein, [0.02] * len(art) + [0.027] * len(vein)) - 0.002))
        return half(d, z)
    mk(shell(1, 2, rows_from(-0.56)).extend(shell(1, 2, _rows((YWL, -0.88, 0.006)))).extend(
        _mesh(submucosa, canal_lo, canal_hi, 0.0065)), None, None, None, "Submucosa", "#e6c4b2",
       "Loose connective tissue carrying the submucosal (Meissner) plexus, lymphatics and the branches of the "
       "superior rectal vessels. In the upper anal canal it thickens into the three vascular anal cushions.",
       "fascia")
    mk(lambda x, y, z: half(_capsules(x, y, z, ip_paths, ip_radii), z), canal_lo, canal_hi, 0.0045,
       "Internal rectal venous plexus (anal cushions)", "#5d4a93",
       "Arteriovenous sinusoids in the submucosa of the anal columns, bunched into three cushions at 3, 7 and 11 "
       "o'clock (patient in lithotomy: left lateral, right posterior, right anterior). They drain to the superior "
       "rectal vein (portal) and communicate with the middle and inferior rectal veins (systemic) – a portosystemic "
       "anastomosis. Haemorrhoids (piles) are these cushions enlarged and slipping down: internal haemorrhoids arise "
       "above the pectinate line, are painless, bleed bright red blood after defecation and are graded I–IV by "
       "prolapse (banding, sclerotherapy, haemorrhoidectomy). Rectal varices of portal hypertension are a different "
       "lesion.", "vein", "Vessels, nerves & nodes")
    mk(lambda x, y, z: half(_capsules(x, y, z, ep_paths, ep_radii), z), (-0.5, -1.25, -0.5), (0.5, -1.05, 0.012),
       0.0065, "External rectal venous plexus", "#57468c",
       "Subcutaneous veins around the anal verge, below the pectinate line, draining via the inferior rectal "
       "veins to the internal pudendal and internal iliac veins. External haemorrhoids arise here; covered by "
       "somatically innervated skin, an acutely thrombosed one (perianal haematoma) is very painful and is "
       "treated by incision within 72 h.", "vein", "Vessels, nerves & nodes")

    # ---- muscular coats
    mk(shell(2, 3, rows_from(-0.55)), None, None, None, "Circular muscle of rectum", "#c68a74",
       "Inner coat of the muscularis externa (smooth muscle, enteric and autonomic control). It forms the core of "
       "the transverse folds and continues down as the internal anal sphincter.", "muscle", "Muscle coats")
    mk(shell(3, 4, rows_from(-0.5)), None, None, None, "Longitudinal muscle of rectum", "#b97a66",
       "Outer smooth-muscle coat: the three taeniae coli spread out into a continuous layer at the rectosigmoid "
       "junction, so the rectum has no haustra. It shortens the rectum during defecation and continues below as "
       "the conjoint longitudinal muscle.", "muscle", "Muscle coats")
    mk(shell(2, 3, _rows((YWL, -0.55, 0.006))), None, None, None, "Internal anal sphincter", "#d7a189",
       "The thickened lower end of the circular smooth muscle, surrounding the upper three-quarters of the anal "
       "canal and ending at the intersphincteric groove. Involuntary (sympathetic L1–2 keeps it contracted, "
       "parasympathetic S2–4 relaxes it); it provides ~70–85 % of resting anal pressure and relaxes reflexly when "
       "the rectum fills (rectoanal inhibitory reflex – absent in Hirschsprung disease). Its spasm keeps anal "
       "fissures from healing (lateral sphincterotomy, GTN, diltiazem, botulinum toxin); obstetric or surgical "
       "damage causes passive faecal soiling.", "muscle", "Muscle coats")
    mk(shell(3, 4, _rows((YWL - 0.02, -0.5, 0.008))), None, None, None, "Conjoint longitudinal muscle", "#c9a27e",
       "Longitudinal rectal muscle joined by fibres from puborectalis, running down in the intersphincteric plane "
       "between the internal and external sphincters and fanning out through the subcutaneous external sphincter "
       "into the perianal skin (corrugator cutis ani). The intersphincteric plane is where many anal gland "
       "abscesses start and where surgeons dissect in intersphincteric resection.", "muscle", "Muscle coats")

    # ---- pelvic floor and external sphincter (skeletal muscle)
    def ext(which):
        def f(x, y, z):
            rho, th = _rcyl(x, y, z)
            d = _eas(rho, th, y, which)
            if which == "deep":
                d = np.maximum(d, -(_puborectalis(x, y, z) - 0.003))
            return half(d, z)
        return f
    eas_lo, eas_hi = (-0.52, -1.18, -0.52), (0.52, -0.58, 0.012)
    mk(ext("deep"), eas_lo, eas_hi, 0.008, "External anal sphincter – deep part", "#a23b34",
       "Upper ring of the voluntary external sphincter (skeletal muscle, inferior rectal branch of the pudendal "
       "nerve, S2–4), blending with puborectalis to form the anorectal ring.", "muscle", "Pelvic floor & sphincters")
    mk(ext("superficial"), eas_lo, eas_hi, 0.008, "External anal sphincter – superficial part", "#983530",
       "Middle, elliptical part, anchored behind to the coccyx by the anococcygeal ligament and in front to the "
       "perineal body. The external sphincter gives the voluntary 'squeeze' and ~15–20 % of resting pressure; it "
       "is torn in 3rd/4th-degree obstetric perineal tears – a leading cause of faecal incontinence in women.",
       "muscle", "Pelvic floor & sphincters")
    mk(ext("sub"), eas_lo, eas_hi, 0.008, "External anal sphincter – subcutaneous part", "#ab4239",
       "A ring just under the perianal skin, below the lower edge of the internal sphincter; the intersphincteric "
       "(white) line can be felt between the two. Pierced by fibres of the conjoint longitudinal muscle.",
       "muscle", "Pelvic floor & sphincters")

    def pr(x, y, z):
        rho, th = _rcyl(x, y, z)
        r4 = _radii(y, th)[4]
        d = np.maximum(_puborectalis(x, y, z), (r4 + 0.005) - rho)
        return half(np.maximum(d, -(_levator(rho, y) - 0.002)), z)
    mk(pr, (-0.5, -0.7, -0.5), (0.5, -0.45, 0.012), 0.008, "Puborectalis", "#8f302b",
       "The innermost part of levator ani: a U-shaped sling from the back of the pubic bodies around the "
       "anorectal junction, pulling it forward to create the anorectal angle (~90° at rest). This flap-valve "
       "mechanism is central to continence; the sling relaxes and the angle straightens to ~130° for defecation. "
       "Failure to relax (dyssynergic defecation) causes obstructed defecation.", "muscle",
       "Pelvic floor & sphincters")

    lev = _lathe_sheet(_rows((0.36, RMAX, 0.012)), THS, lambda r: _lev_y(r) + LEV_HALF,
                       lambda r: _lev_y(r) - LEV_HALF)
    mk(lev, None, None, None, "Levator ani", "#a7473d",
       "The muscular pelvic floor (pubococcygeus and iliococcygeus, with puborectalis), sloping down from the "
       "tendinous arch over obturator internus to the anorectal junction and anococcygeal ligament. It supports "
       "the pelvic viscera and raises intra-abdominal pressure. Nerve to levator ani (S3–4) and pudendal branches. "
       "It separates the mesorectum above from the ischioanal fossa below; weakness after childbirth leads to "
       "pelvic organ prolapse and incontinence.", "muscle", "Pelvic floor & sphincters")

    # ---- fat, vessels and nodes
    def meso(x, y, z):
        rho, th = _rcyl(x, y, z)
        r4 = _radii(y, th)[4]
        m = (0.09 + 0.15 * np.maximum(0.0, -np.sin(th))) * (1.0 - 0.55 * _ss(y, 0.8, 1.4))
        d = np.maximum(_between(rho, r4 + 0.004, r4 + m), rho - RMAX)
        d = np.maximum(d, (_lev_y(rho) + LEV_HALF + 0.005) - y)
        d = np.maximum(d, y - YTOP)
        d = np.maximum(d, -(_capsules(x, y, z, art + vein, [0.02] * len(art) + [0.027] * len(vein)) - 0.003))
        for c, r in nodes:
            d = np.maximum(d, -(_ellipsoid(x, y, z, c, r) - 0.003))
        return half(d, z)
    mk(meso, (-1.0, -0.5, -1.0), (1.0, 1.42, 0.012), 0.02, "Mesorectum", "#e8c35e",
       "Fat around the rectum, thickest behind, enclosed by the mesorectal fascia and carrying the superior "
       "rectal vessels, lymphatics and nodes. Rectal cancer spreads first into it, so total mesorectal excision "
       "(TME) – removing the rectum in its intact fascial envelope along the 'holy plane' – has greatly reduced "
       "local recurrence. MRI measures the distance from tumour to the mesorectal fascia (circumferential "
       "resection margin) to decide on neoadjuvant chemoradiotherapy.", "fat", "Fat & fossae")

    def ischio(x, y, z):
        rho, th = _rcyl(x, y, z)
        r4 = _radii(y, th)[4]
        d = np.maximum(y - (_lev_y(rho) - LEV_HALF - 0.004), (_skin_y(rho) + SKIN_HALF + 0.004) - y)
        d = np.maximum(d, np.maximum(rho - RMAX, (r4 + 0.004) - rho))
        d = np.maximum(d, -(_eas_all(x, y, z) - 0.004))
        d = np.maximum(d, -(_puborectalis(x, y, z) - 0.004))
        d = np.maximum(d, -(_capsules(x, y, z, ep_paths, ep_radii) - 0.003))
        d = np.maximum(d, -(_poly2d(rho, y, SKIN) - SKIN_HALF - 0.004))
        return half(d, z)
    mk(ischio, (-1.0, -1.25, -1.0), (1.0, 0.2, 0.012), 0.02, "Ischioanal fossa fat", "#e3bb52",
       "Wedge-shaped fat-filled space on each side of the anal canal, below levator ani and medial to obturator "
       "internus, crossed by the inferior rectal vessels and nerve; the pudendal canal runs in its lateral wall. "
       "The fat lets the canal distend during defecation. The two fossae connect behind the anal canal, so an "
       "ischioanal abscess can spread around it (horseshoe abscess).", "fat", "Fat & fossae")
    mk(_tubes(art, 0.02), None, None, None, "Superior rectal artery", "#c1302a",
       "Continuation of the inferior mesenteric artery over the pelvic brim; divides into right and left branches "
       "that pierce the wall and run in the anal columns. The middle (internal iliac) and inferior (internal "
       "pudendal) rectal arteries supply the lower rectum and canal. Ligated high (at the IMA) in cancer "
       "resections to clear the lymph nodes that follow it.", "artery", "Vessels, nerves & nodes")
    mk(_tubes(vein, 0.027), None, None, None, "Superior rectal vein", "#3e5da8",
       "Drains the rectum and the internal venous plexus to the inferior mesenteric vein and so to the hepatic "
       "portal vein – which is why colorectal cancer metastasises first to the liver, whereas low anal "
       "tumours spread to the lungs via the systemic veins.", "vein", "Vessels, nerves & nodes")

    def nodes_fn(x, y, z):
        d = None
        for c, r in nodes:
            e = _ellipsoid(x, y, z, c, r)
            d = e if d is None else np.minimum(d, e)
        return half(d, z)
    mk(_nodes_mesh(nodes), None, None, None, "Mesorectal lymph nodes", "#c8b197",
       "Nodes within the mesorectum along the superior rectal vessels; they drain up to the inferior mesenteric "
       "nodes. Their involvement (N stage) and removal within an intact mesorectum are central to rectal cancer "
       "staging and surgery. Below the pectinate line lymph goes instead to the superficial inguinal nodes.",
       "lymph", "Vessels, nerves & nodes")
    return parts


# =============================================================================== (a) ileocaecal region
YV, THV = -0.35, -0.62          # ileocaecal valve: height and angle (posteromedial wall)
YD, HD = -0.62, 0.5             # the caecum closes below YD as a dome of height HD
YW = 0.2                        # top of the window cut in the front of the caecum
YT = 1.35                       # transverse cut through the ascending colon
YA, THA = -0.93, -0.3           # appendix base on the posteromedial dome
T_MUS, T_MUC = 0.036, 0.028     # muscular coat (with serosa), mucosa with submucosa
H_FOLDS = (-0.02, 0.36, 0.72, 1.08)
TAENIAE = (("Taenia libera (free taenia)", 1.57), ("Taenia mesocolica", -1.4), ("Taenia omentalis", -2.6))

_RC = PchipInterpolator([-0.7, -0.3, 0.1, 0.5, 1.45], [0.6, 0.62, 0.56, 0.5, 0.48])


def _c_axis(y):
    return -0.07 * _ss(y, 0.1, -0.9)


def _taenia_th(k, y):
    th0 = TAENIAE[k][1]
    return th0 + _wrap(THA - th0) * _ss(y, -0.3, -0.93)


def _haustra(y, th):
    """1 in the middle of a sacculation between two taeniae, 0 along the taeniae and at the semilunar folds."""
    u = (y - H_FOLDS[0]) / (H_FOLDS[1] - H_FOLDS[0])
    h = np.abs(np.sin(np.pi * u)) ** 0.6
    r0 = _RC(np.clip(y, -0.7, 1.45))
    t = None
    for k in range(3):
        sk = np.abs(_wrap(th - _taenia_th(k, y))) * r0
        tk = _ss(sk, 0.05, 0.22)
        t = tk if t is None else np.minimum(t, tk)
    env = 0.45 + 0.55 * _ss(y, -0.55, -0.1)
    return h * t * env, t


def _plicae(y, th):
    """Semilunar folds: crescentic ridges inside the colon between the taeniae, at the haustral constrictions."""
    d = np.full(np.broadcast_shapes(np.shape(y), np.shape(th)), 1.0, np.float32)
    for yf in H_FOLDS:
        d = np.minimum(d, np.abs(y - yf))
    _, t = _haustra(y, th)
    return 0.05 * t * np.exp(-(d / 0.028) ** 2) * _ss(y, -0.2, -0.08)


def _c_radii(y, th):
    """Outer surface, muscle|mucosa boundary and lumen of the caecum and colon at heights y >= YD."""
    yc = np.maximum(y, YD)
    r0 = _RC(np.clip(yc, -0.7, 1.45)).astype(np.float32)
    h, _ = _haustra(yc, th)
    ro = r0 * (0.955 + 0.11 * h)
    pl = _plicae(yc, th)
    return ro, ro - T_MUS - 0.7 * pl, ro - T_MUS - T_MUC - pl


def _c_surface(k):
    """Surface k (0 outer, 1 muscle|mucosa, 2 lumen) as a parametric surface of (v, theta): v < 0 is the dome
    (v = -1 at the pole), v >= 0 is the height above YD."""
    def f(V, T):
        r_top = _c_radii(np.float32(YD), T)[k]
        h = HD - (_c_radii(np.float32(YD), T)[0] - r_top)
        phi = np.clip(-V, 0.0, 1.0) * (np.pi / 2)
        yd = YD - h * np.sin(phi)
        y = np.where(V < 0, yd, YD + V)
        r = np.where(V < 0, r_top * np.cos(phi), _c_radii(np.maximum(y, YD), T)[k])
        cx = _c_axis(y)
        return cx + r * np.cos(T), y, r * np.sin(T)
    return f


def _c_implicit(k, x, y, z):
    """Signed distance-like value of surface k on a grid (negative inside it)."""
    dx = x - _c_axis(y)
    rho = np.sqrt(dx * dx + z * z)
    th = np.arctan2(z, dx)
    rk = _c_radii(y, th)[k]
    r_top = _c_radii(np.float32(YD), th)[k]
    h = HD - (_c_radii(np.float32(YD), th)[0] - r_top)
    q = np.sqrt((rho / r_top) ** 2 + ((YD - y) / h) ** 2)
    return np.where(y >= YD, rho - rk, (q - 1.0) * np.minimum(r_top, h))


def _c_points(k, y, th, extra=0.0):
    """World points on surface k at heights y and angles theta (arrays), pushed `extra` along the outward radius."""
    y = np.asarray(y, np.float32)
    th = np.asarray(th, np.float32)
    r_top = _c_radii(np.float32(YD), th)[k]
    h = HD - (_c_radii(np.float32(YD), th)[0] - r_top)
    r_dome = r_top * np.sqrt(np.clip(1.0 - ((YD - y) / h) ** 2, 0.0, 1.0))
    r = np.where(y >= YD, _c_radii(np.maximum(y, YD), th)[k], r_dome) + extra
    return np.stack(np.broadcast_arrays(_c_axis(y) + r * np.cos(th), y, r * np.sin(th)), -1).astype(np.float64)


def _c_point(k, y, th, extra=0.0):
    return _c_points(k, np.float32(y), np.float32(th), extra)


def _window(d, y, z):
    """Remove the front of the caecum below YW (the window through which the valve is seen)."""
    return np.maximum(d, np.minimum(z, YW - y))


def _frame(th):
    n = np.array([math.cos(th), 0.0, math.sin(th)])
    t = np.array([-math.sin(th), 0.0, math.cos(th)])
    return n, np.array([0.0, 1.0, 0.0]), t


def _appendix_path():
    n = np.array([math.cos(THA), -0.55, math.sin(THA)])
    n /= np.linalg.norm(n)
    o_in = _c_point(2, YA, THA)
    o_out = _c_point(0, YA, THA)
    ctrl = [o_in - 0.07 * n, o_in, o_out, o_out + 0.14 * n + np.array([0.02, -0.06, 0.04]),
            np.array([0.62, -1.3, -0.07]), np.array([0.84, -1.47, -0.01]), np.array([1.06, -1.53, 0.0]),
            np.array([1.24, -1.47, 0.0])]
    path = _smooth(ctrl, 6)
    return path, o_in, o_out


def _ileum_path():
    n = np.array([math.cos(THV), 0.0, math.sin(THV)])
    p0 = _c_point(0, YV, THV, -0.03)
    pin = _c_point(2, YV, THV, -0.012)
    ctrl = [pin, p0, p0 + 0.25 * n, p0 + 0.48 * n + np.array([0.12, -0.01, 0.0]), np.array([1.08, -0.39, -0.55]),
            np.array([1.34, -0.43, -0.5])]
    return _smooth(ctrl, 8)


def _tube_surfaces(path, r_fn):
    """Parametric surface of a tube round a centreline: v runs along the path (0..1), theta around it."""
    from .geometry import frames
    path = np.asarray(path, float)
    t, nrm, bin_ = frames(path)
    L = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))])
    L /= L[-1]

    def f(V, T):
        idx = np.clip(V[:, 0] * (len(path) - 1), 0, len(path) - 1)
        i0 = np.floor(idx).astype(int)
        i1 = np.minimum(i0 + 1, len(path) - 1)
        w = (idx - i0)[:, None, None]
        c = path[i0][:, None, :] * (1 - w) + path[i1][:, None, :] * w
        nn = nrm[i0][:, None, :] * (1 - w) + nrm[i1][:, None, :] * w
        bb = bin_[i0][:, None, :] * (1 - w) + bin_[i1][:, None, :] * w
        R = np.broadcast_to(r_fn(V, T), (V.shape[0], T.shape[1]))[..., None]
        P = c + R * (np.cos(T)[..., None] * nn + np.sin(T)[..., None] * bb)
        return P[..., 0], P[..., 1], P[..., 2]
    return f


def _omental_appendices():
    rng = np.random.default_rng(5)
    blobs = []
    for k, ys in ((0, (0.34, 0.58, 0.83, 1.06)), (2, (0.42, 0.7, 0.95, 1.2))):
        for y in ys:
            th = TAENIAE[k][1] + rng.choice([-1, 1]) * rng.uniform(0.2, 0.28)
            base = _c_point(0, y, th, -0.015)
            n = np.array([math.cos(th), 0.0, math.sin(th)])
            t = np.array([-math.sin(th), 0.0, math.cos(th)])
            r = rng.uniform(0.05, 0.068)
            body = base + n * (r * 0.9) + np.array([0.0, -r * 1.1, 0.0])
            lobe = body + n * r * 0.4 + t * rng.uniform(-0.5, 0.5) * r + np.array([0.0, -r * 1.2, 0.0])
            blobs.append((base, body, lobe, r))
    return blobs


def build_caecum():
    """The ileocaecal region seen through a window in the front of the caecum."""
    G = "Ileocaecal region – "
    parts = []
    app_path, o_in, o_out = _appendix_path()
    il_path = _ileum_path()
    orifice = 0.5 * (o_in + o_out)
    n_v, up, t_v = _frame(THV)
    pw = _c_point(2, YV, THV)                   # valve centre on the lumen surface

    def mk(mesh, name, grp, color, desc, cat):
        parts.append(_part(mesh, A_OFF, name, G + grp, color, desc, cat))

    def sdf(fn, lo, hi, vox, smooth=0.8):
        return _mesh(fn, lo, hi, vox, smooth)

    # ---- caecal and colic wall (parametric), with a hole round the appendix orifice filled by an SDF patch
    ths_full = np.linspace(-np.pi, np.pi, 97)[:-1]
    ths_half = np.linspace(-np.pi, 0.0, 49)
    fold_rows = np.concatenate([_rows((yf - 0.08, yf + 0.08, 0.011)) - YD for yf in H_FOLDS])
    v_lo = np.unique(np.concatenate([_rows((-1.0, 0.0, 0.04)), _rows((0.0, YW - YD, 0.028)),
                                     fold_rows[(fold_rows > 0) & (fold_rows < YW - YD)]]))
    v_hi = np.unique(np.concatenate([_rows((YW - YD, YT - YD, 0.028)),
                                     fold_rows[(fold_rows > YW - YD) & (fold_rows < YT - YD)]]))
    v_split = -0.2 - YD                          # caecum below, ascending colon above

    def hole(c):
        # the appendix orifice (filled by an SDF patch) and the passage of the ileum through the wall
        u = np.clip((c - pw) @ n_v, -0.05, 0.2)
        d_il = np.linalg.norm(c - (pw + u[:, None] * n_v), axis=1)
        return (np.linalg.norm(c - orifice, axis=1) > 0.1) & (d_il > 0.162)

    def coat(k0, k1, vs, ths, full, keep=None):
        return _surf_shell(_c_surface(k1), _c_surface(k0), vs, ths, full, keep)

    patch_r = 0.135

    def patch(k0, k1, inner):
        def f(x, y, z):
            d = np.maximum(-_c_implicit(k1, x, y, z) if k1 is not None else -BIG, _c_implicit(k0, x, y, z))
            d = np.maximum(d, np.sqrt((x - orifice[0]) ** 2 + (y - orifice[1]) ** 2 + (z - orifice[2]) ** 2) - patch_r)
            d = np.maximum(d, -_capsules(x, y, z, [app_path[:12]], [0.036]))
            if inner is not None:
                ring = np.sqrt((x - orifice[0]) ** 2 + (y - orifice[1]) ** 2 + (z - orifice[2]) ** 2) - 0.075
                d = np.maximum(d, ring if inner else -ring)
            return d
        return sdf(f, orifice - 0.17, orifice + 0.17, 0.0045)

    lo_rows = v_lo[v_lo <= v_split + 1e-6]
    mid_rows = np.concatenate([[v_split], v_lo[v_lo > v_split + 1e-6]])
    caecum = coat(0, 1, lo_rows, ths_half, False, hole).extend(patch(0, 1, None))
    colon = coat(0, 1, mid_rows, ths_half, False, hole).extend(coat(0, 1, v_hi, ths_full, True))
    mucosa = coat(1, 2, v_lo, ths_half, False, hole).extend(coat(1, 2, v_hi, ths_full, True))
    mucosa.extend(patch(1, 2, False))
    mk(caecum, "Caecum", "Caecum & colon", "#d6a491",
       "The blind pouch of the large intestine below the ileocaecal junction, ~6 cm long and 7.5 cm wide, in "
       "the right iliac fossa. It is usually wholly covered by peritoneum and mobile; its three taeniae converge "
       "on the base of the appendix. As the widest part of the colon it has the thinnest-stretched wall (Laplace), "
       "so in distal large-bowel obstruction with a competent ileocaecal valve it dilates most and perforates first "
       "(caecal diameter > 12 cm is dangerous). Caecal volvulus occurs when it is abnormally mobile; right-sided "
       "colon cancers here present with iron-deficiency anaemia rather than obstruction.", "organ")
    mk(colon, "Ascending colon (haustra)", "Caecum & colon", "#d19c8a",
       "Retroperitoneal on its back surface, running up the right flank to the right colic (hepatic) flexure. "
       "Its wall is gathered into sacculations – haustra – because the three taeniae coli are shorter than the "
       "wall; between haustra the wall is creased into semilunar folds. Haustra give the colon its segmented "
       "outline on abdominal X-ray (incomplete bands, unlike the complete valvulae conniventes of small bowel) and "
       "are lost in chronic ulcerative colitis ('lead-pipe' colon). Supplied by the ileocolic and right colic "
       "branches of the superior mesenteric artery; venous blood drains to the portal vein.", "organ")
    mk(mucosa, "Mucosa & semilunar folds (plicae semilunares)", "Caecum & colon", "#cf8579",
       "Colonic mucosa: no villi, a flat surface of straight crypts with very many goblet cells secreting "
       "lubricating mucus; the colon absorbs water and electrolytes (Na+ via ENaC, aldosterone-sensitive) and "
       "houses the gut microbiota. The crescentic semilunar folds (mucosa, submucosa and circular muscle) lie "
       "between the haustra. Adenomatous polyps arise here and progress to adenocarcinoma – the basis of "
       "screening by faecal immunochemical testing and colonoscopy.", "mucosa")

    # ---- taeniae coli (parametric bands, clipped at the window)
    texts = {
        0: "The anterior taenia, not attached to anything, on the front of the ascending colon (and the lower "
           "border of the transverse colon). Surgeons follow it down to find the appendix base.",
        1: "The posteromedial taenia, where the mesocolon attaches (on the transverse colon) – on the ascending "
           "colon it faces the posterior abdominal wall.",
        2: "The posterolateral taenia; on the transverse colon the greater omentum attaches along it."}
    common = (" The three taeniae coli are the longitudinal muscle of the colon gathered into bands ~1 cm wide; "
              "because they are shorter than the gut they pucker the wall into haustra. They converge on the base "
              "of the appendix and spread out into a complete longitudinal coat on the appendix and the rectum. "
              "Diverticula of the colon push out between them where vessels pierce the circular muscle.")
    for k, (nm, _) in enumerate(TAENIAE):
        mk(_taenia_mesh(k), nm, "Caecum & colon", "#e2c7ae", texts[k] + common, "muscle")

    blobs = _omental_appendices()

    oa_mesh = Mesh()
    for base, body, lobe, r in blobs:
        def oa(x, y, z, base=base, body=body, lobe=lobe, r=r):
            e = np.minimum(_ellipsoid(x, y, z, body, (r * 0.85, r * 1.3, r)),
                           _ellipsoid(x, y, z, lobe, (r * 0.5, r * 0.62, r * 0.55)))
            e = np.minimum(e, _capsules(x, y, z, [[base, body]], [[r * 0.7, r * 0.8]]))
            return np.maximum(e, -_c_implicit(0, x, y, z) + 0.004)
        pts = np.array([base, body, lobe])
        oa_mesh.extend(sdf(oa, pts.min(axis=0) - 2.2 * r, pts.max(axis=0) + 2.2 * r, 0.0072))
    mk(oa_mesh, "Omental (epiploic) appendices", "Caecum & colon", "#ebc75a",
       "Small peritoneal pouches of fat hanging from the colon along the taeniae (few on the caecum, most on the "
       "sigmoid) – a feature, with taeniae and haustra, that tells large from small intestine at operation. One "
       "can twist and infarct (epiploic appendagitis: sharp localised pain mimicking diverticulitis or "
       "appendicitis, with a fat-density ring on CT).", "fat")

    # ---- terminal ileum and the ileocaecal valve
    il_s = _tube_surfaces(il_path, lambda V, T: 0.19 + 0 * V)
    il_m = _tube_surfaces(il_path, lambda V, T: 0.152 + 0 * V)
    il_l = _tube_surfaces(il_path, lambda V, T: 0.126 + 0.004 * np.sin(9 * T) + 0 * V)
    ths_t = np.linspace(0, 2 * np.pi, 49)[:-1]
    vv = np.linspace(0.0, 1.0, 70)
    mk(_surf_shell(il_m, il_s, vv, ths_t, True), "Terminal ileum", "Ileocaecal junction", "#d7a08f",
       "The last part of the ileum, entering the posteromedial caecum. It absorbs vitamin B12 (intrinsic-factor "
       "complex, cubilin receptors) and recycles bile salts – so its resection or disease (Crohn's disease, which "
       "favours the terminal ileum) causes B12 deficiency, bile-acid diarrhoea and gallstones. Its lymphoid "
       "Peyer patches can lead an ileocolic intussusception in infants. Supplied by the ileal branch of the "
       "ileocolic artery.", "organ")
    mk(_surf_shell(il_l, il_m, vv, ths_t, True), "Ileal mucosa", "Ileocaecal junction", "#c56f77",
       "Velvety mucosa of the ileum covered with villi (absorptive enterocytes, many goblet cells) over Peyer "
       "patches of lymphoid tissue.", "mucosa")

    def mound(x, y, z):
        return _ellipsoid(x, y, z, pw + 0.01 * n_v, (0.16, 0.2, 0.3), axes=(n_v, up, t_v))

    def slit(x, y, z):
        return _ellipsoid(x, y, z, pw - 0.1 * n_v, (0.12, 0.03, 0.19), axes=(n_v, up, t_v))

    def channel(x, y, z):
        return _capsules(x, y, z, [[pw + 0.08 * n_v, pw - 0.06 * n_v]], [[0.1, 0.07]])

    def lip(upper):
        def f(x, y, z):
            d = np.maximum(mound(x, y, z), _c_implicit(2, x, y, z) - 0.003)
            d = np.maximum(d, -slit(x, y, z))
            d = np.maximum(d, -channel(x, y, z))
            return _window(np.maximum(d, (YV - y) if upper else (y - YV)), y, z)
        return f
    vlo, vhi = pw - 0.36, pw + 0.36
    mk(sdf(lip(True), vlo, vhi, 0.006), "Ileocaecal valve – upper (ileocolic) lip", "Ileocaecal junction",
       "#c46b6c",
       "The terminal ileum invaginates into the caecum as a papilla whose slit-like opening (the ileal orifice) "
       "is bounded by an upper and a lower lip of mucosa, submucosa and circular muscle. The upper lip is at the "
       "ileocolic junction. The valve (with a thickened circular 'sphincter') slows ileal emptying and largely "
       "prevents reflux of colonic contents and bacteria into the ileum. A competent valve turns distal colonic "
       "obstruction into a closed loop, so the caecum distends and can perforate.", "mucosa")
    mk(sdf(lip(False), vlo, vhi, 0.006), "Ileocaecal valve – lower (ileocaecal) lip", "Ileocaecal junction",
       "#bb6466",
       "The lower lip of the ileal orifice, at the ileocaecal junction proper. At colonoscopy the valve is "
       "recognised as a yellowish fold on the medial caecal wall; passing through it lets the terminal ileum be "
       "inspected and biopsied (Crohn's disease, backwash ileitis). The appendiceal orifice lies ~2–3 cm below "
       "it, where the taeniae converge.", "mucosa")

    fr_paths, fr_rads = [], []
    for sgn in (-1, 1):
        fr_paths.append([_c_point(2, YV + 0.005 * i, THV + sgn * (0.36 + 0.11 * i), 0.048 + 0.004 * i)
                         for i in range(5)])
        fr_rads.append([0.068, 0.066, 0.064, 0.062, 0.06])
    fr_pts = np.concatenate(fr_paths)

    def frenula(x, y, z):
        paths, rads = fr_paths, fr_rads
        d = np.maximum(_capsules(x, y, z, paths, rads), _c_implicit(2, x, y, z) - 0.003)
        return _window(np.maximum(d, -(mound(x, y, z) - 0.002)), y, z)
    mk(sdf(frenula, fr_pts.min(axis=0) - 0.08, fr_pts.max(axis=0) + 0.08, 0.005), "Frenula of the ileocaecal valve", "Ileocaecal junction", "#c87a74",
       "Where the two lips meet at each end of the orifice they continue round the caecal wall as mucosal ridges, "
       "the frenula (frenulum of the ileocaecal valve), which fade into the semilunar folds.", "mucosa")

    # ---- appendix
    n_app = len(app_path)
    r_out = np.interp(np.arange(n_app), [0, 3, n_app - 3, n_app - 1], [0.078, 0.074, 0.066, 0.05])
    r_mid = r_out - 0.021
    r_lum = np.interp(np.arange(n_app), [0, n_app - 4, n_app - 1], [0.03, 0.026, 0.002])
    rng = np.random.default_rng(8)
    fol = []
    for i in range(13, n_app - 4, 2):
        c = app_path[i]
        tdir = app_path[min(i + 1, n_app - 1)] - app_path[i - 1]
        tdir /= np.linalg.norm(tdir)
        a = np.cross(tdir, [0.0, 0.0, 1.0])
        a /= np.linalg.norm(a) + 1e-9
        b = np.cross(tdir, a)
        for ang in np.linspace(0, 2 * np.pi, 5, endpoint=False) + rng.uniform(0, 1.3):
            fol.append(c + (r_lum[i] + 0.012) * (math.cos(ang) * a + math.sin(ang) * b))

    def outside(d, x, y, z):
        return _window(np.maximum(d, -_c_implicit(0, x, y, z) - 0.002), y, z)

    def app_wall(x, y, z):
        d = np.maximum(_capsules(x, y, z, [app_path], [r_out]), -_capsules(x, y, z, [app_path], [r_mid]))
        return outside(d, x, y, z)

    def app_muc(x, y, z):
        d = np.maximum(_capsules(x, y, z, [app_path], [r_mid + 0.001]), -_capsules(x, y, z, [app_path], [r_lum]))
        d = np.maximum(d, -(_capsules(x, y, z, [[p, p] for p in fol], [0.013] * len(fol)) - 0.001))
        return outside(d, x, y, z)

    def app_fol(x, y, z):
        d = np.maximum(_capsules(x, y, z, [[p, p] for p in fol], [0.013] * len(fol)),
                       -_capsules(x, y, z, [app_path], [r_lum + 0.003]))
        return outside(d, x, y, z)
    alo, ahi = app_path.min(axis=0) - 0.1, app_path.max(axis=0) + 0.1
    mk(sdf(app_wall, alo, ahi, 0.0075), "Vermiform appendix", "Vermiform appendix", "#d39d8b",
       "A blind worm-like tube 6–10 cm long opening into the posteromedial caecum ~2 cm below the ileocaecal "
       "valve; its base is constant (where the taeniae meet), its tip variable – retrocaecal (~65 %), pelvic "
       "(~30 %), pre- or post-ileal. It has a complete longitudinal muscle coat. Appendicitis follows obstruction "
       "of the lumen (faecolith, lymphoid hyperplasia): distension, ischaemia, bacterial invasion, gangrene and "
       "perforation. Pain starts periumbilical (visceral afferents to T10) and shifts to the right iliac fossa "
       "when the parietal peritoneum is inflamed, with tenderness at McBurney's point (one-third of the way from "
       "the anterior superior iliac spine to the umbilicus); Rovsing, psoas (retrocaecal) and obturator (pelvic) "
       "signs; fever, anorexia, neutrophilia. Treated by appendicectomy (or antibiotics in selected cases).",
       "organ")
    mk(sdf(app_muc, alo, ahi, 0.0065), "Appendiceal mucosa", "Vermiform appendix", "#c17078",
       "Colonic-type mucosa with crypts and goblet cells around a narrow, often irregular lumen, the submucosa "
       "packed with lymphoid tissue.", "mucosa")
    mk(sdf(app_fol, alo, ahi, 0.0055), "Lymphoid follicles of the appendix", "Vermiform appendix", "#efe2d3",
       "Aggregated lymphoid follicles with germinal centres form an almost continuous ring in the mucosa and "
       "submucosa – the appendix is gut-associated lymphoid tissue (GALT), most abundant in childhood and "
       "adolescence. Their hyperplasia after viral infection is a common cause of luminal obstruction and "
       "appendicitis in the young.", "lymph")
    mk(patch(1, 2, True), "Appendiceal orifice", "Vermiform appendix", "#9d4c57",
       "The opening of the appendix into the caecum, sometimes guarded by a small mucosal fold (valve of "
       "Gerlach). At colonoscopy it is a crescentic slit at the convergence of the taeniae and marks, with the "
       "ileocaecal valve, that the caecum has been reached.", "mucosa")

    # ---- mesoappendix and appendicular artery
    ab = o_out + np.array([0.02, 0.0, -0.03])
    ip = np.array([0.72, -0.62, -0.42])
    att_i = int(0.68 * (n_app - 1))                  # the fold reaches two-thirds of the way along the appendix
    us = np.linspace(0.0, 1.0, 150)
    idx = 3 + us * (att_i - 3)
    i0 = np.floor(idx).astype(int)
    w = (idx - i0)[:, None]
    A_u = app_path[i0] * (1 - w) + app_path[np.minimum(i0 + 1, n_app - 1)] * w + np.array([0.0, 0.05, -0.03])
    C_u = ab[None, :] + us[:, None] * (ip - ab)[None, :]
    vs = np.linspace(0.0, 1.0, 100)
    U, Vv = us[:, None, None], vs[None, :, None]
    nrm = np.cross(ip - ab, A_u[-1] - ab)
    nrm /= np.linalg.norm(nrm)
    toward = ab - 0.5 * (A_u[-1] + ip)
    toward /= np.linalg.norm(toward)
    S = (A_u[:, None, :] * (1 - Vv) + C_u[:, None, :] * Vv
         + 0.16 * U ** 3 * np.sin(np.pi * Vv) * toward + 0.035 * np.sin(np.pi * U) * np.sin(np.pi * Vv) * nrm)
    sheet = S.reshape(-1, 3)
    edge = S[-1, ::-1][::9] - 0.008 * toward               # along the free edge, from the ileal end down
    tail = app_path[att_i:n_app - 2:3] + np.array([0.0, 0.05, -0.03])
    art = [np.vstack([ip + np.array([0.04, 0.03, -0.05]), edge[1:], tail])]
    for u0 in (0.3, 0.55, 0.8):
        i = int(u0 * (len(us) - 1))
        art.append(S[i, 55::-11])

    def meso(x, y, z):
        d = _cloud(x, y, z, sheet, 0.011)
        d = np.maximum(d, -_capsules(x, y, z, [app_path], [r_out]))
        d = np.maximum(d, -_c_implicit(0, x, y, z))
        return _window(d, y, z)
    mlo, mhi = sheet.min(axis=0) - 0.05, sheet.max(axis=0) + 0.05
    mk(sdf(meso, mlo, mhi, 0.0075), "Mesoappendix", "Vermiform appendix", "#e8cd8c",
       "A triangular fold of peritoneum from the back of the terminal ileal mesentery to the appendix, carrying "
       "the appendicular vessels in its free edge. It is divided between clips or ligatures at appendicectomy.",
       "fat")
    mk(_tubes([_smooth(a, 3) for a in art], 0.012, 10), "Appendicular artery", "Vermiform appendix", "#c3322c",
       "A branch of the ileocolic artery (from the superior mesenteric) that runs behind the terminal ileum and "
       "along the free edge of the mesoappendix. It is an end artery: when an inflamed appendix swells and the "
       "artery thromboses, the tip becomes gangrenous and perforates.", "artery")
    return parts


def _taenia_mesh(k, width=0.13, height=0.013):
    """A taenia coli as a raised band on the outer surface, sunk into the muscle coat; clipped to the window."""
    ys = _rows((-0.92, YT, 0.012))
    rows = []
    for y in ys:
        thc = float(_taenia_th(k, np.float32(y)))
        r0 = float(_RC(np.clip(y, -0.7, 1.45)))
        w = width * (0.65 + 0.35 * _ss(y, -0.9, -0.5))
        hw = 0.5 * w / r0
        a, b = thc - hw, thc + hw
        if y < YW:
            a, b = a, min(b, 0.0)
            if a < -np.pi:
                a = -np.pi
        rows.append((y, a, b, thc, hw) if b - a > 0.02 * hw else None)
    meshes = Mesh()
    run = []
    for r in rows + [None]:
        if r is not None:
            run.append(r)
            continue
        if len(run) >= 2:
            meshes.extend(_band_run(run, height))
        run = []
    return meshes


def _band_run(run, height, ncol=13):
    y = np.array([r[0] for r in run], np.float32)
    s = np.linspace(0.0, 1.0, ncol, dtype=np.float32)
    A = np.array([r[1] for r in run], np.float32)[:, None]
    B = np.array([r[2] for r in run], np.float32)[:, None]
    C = np.array([r[3] for r in run], np.float32)[:, None]
    HW = np.array([r[4] for r in run], np.float32)[:, None]
    TH = A + (B - A) * s[None, :]
    prof = np.sqrt(np.clip(1.0 - ((TH - C) / HW) ** 2, 0.0, 1.0))
    Y = np.broadcast_to(y[:, None], TH.shape)
    pts = {"in": _c_points(0, Y, TH, -0.6 * T_MUS), "out": _c_points(0, Y, TH, height * prof - 0.001)}
    m = Mesh()
    ny, nt = TH.shape
    m.add(pts["out"].reshape(-1, 3), _quads(ny, nt))
    m.add(pts["in"].reshape(-1, 3), _quads(ny, nt, flip=True))
    for row in (0, ny - 1):
        d = pts["out"][min(row + 1, ny - 1)].mean(axis=0) - pts["out"][max(row - 1, 0)].mean(axis=0)
        m.add(*_strip(pts["in"][row], pts["out"][row], d if row else -d))
    for col in (0, nt - 1):
        d = pts["out"][:, min(col + 1, nt - 1)].mean(axis=0) - pts["out"][:, max(col - 1, 0)].mean(axis=0)
        m.add(*_strip(pts["in"][:, col], pts["out"][:, col], d if col else -d))
    return m


def build_ileocecal_rectum():
    return build_caecum() + build_rectum()
