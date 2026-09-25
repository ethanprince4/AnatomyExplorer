"""Blood: the formed elements suspended in plasma, drawn to scale and coloured as on a Wright-stained smear.

The field is a thin sheet of plasma a few cells deep, like the monolayer at the feathered edge of a good smear, so
every cell can be seen from above while still being three-dimensional from the side. All sizes are true to scale
(K model units per micrometre); only the granules of the granulocytes are slightly enlarged so they read.

* Erythrocytes are analytic biconcave discs (the Evans-Fung profile of a resting red cell), scattered flat or
  tipped in two loose layers, with a short rouleau and one red cell cut through to show its dumbbell section.
* Leukocytes are signed-distance cells cut in half at their equator, the way a smear shows them: the cut face
  carries the section of the nucleus and the granules poking through it, while the lower half keeps the ruffled
  cell surface. Each type sits once in a labelled-looking lineup along the front edge, in their order of abundance
  (neutrophil, lymphocytes, monocyte, eosinophil, basophil - "Never Let Monkeys Eat Bananas"), and again scattered
  among the red cells behind it.
* Platelets are small lentils, single and in little clumps. The back-right corner holds an early clot: a fibrin
  mesh with spiky activated platelets and trapped red cells.
"""
import math

import numpy as np
from scipy.spatial import cKDTree

from .cellkit import star_cell
from .cells import hex_points
from .geometry import Mesh, box as box_mesh, compute_normals, tube
from .kit import Volume, capsule, ellipsoid, mesh_part, smooth_path
from .sdf import BIG

K = 0.03                       # model units per micrometre: the field is ~97 x 77 um
VOX = 0.0032                   # voxel for the leukocyte fields (~0.1 um)
X0, X1, Z0, Z1 = -1.45, 1.45, -1.35, 0.95
Y_LO, Y_HI = -0.22, 0.17       # plasma sheet
LANE_Z = 0.64                  # the lineup along the front edge
CLOT = (0.70, 1.40, -1.32, -0.72)      # x0, x1, z0, z1 of the clot corner
ROULEAU = (-0.92, -0.02, -1.02)

GROUP_RBC = "Red cells & platelets"
GROUP_GRAN = "Granulocytes"
GROUP_AGRAN = "Agranulocytes"
GROUP_PLASMA = "Plasma"
GROUP_CLOT = "Clot"

C = {
    "plasma": "#efd98a", "rbc": "#c9564d", "rbc_cut": "#d06a60", "rouleau": "#bd4c48",
    "platelet": "#7f52aa", "platelet_act": "#6a3d98", "fibrin": "#e4c0c8",
    "neut": "#c898b6", "band": "#c494b2", "neut_gran": "#a0689f", "neut_nuc": "#38175f",
    "eos": "#dc9d88", "eos_gran": "#e2502a", "eos_nuc": "#3e1d68",
    "baso": "#a88cc6", "baso_gran": "#26114f", "baso_nuc": "#4c2e7c",
    "lymph_s": "#5b8bd0", "lymph_l": "#6a96d4", "lymph_nuc": "#2c1352",
    "mono": "#7085b4", "mono_nuc": "#5b3d8a",
}

# mottle only - these are cells, not blocks of tissue, so no fake cell mosaic on their faces. The nuclei get a
# fine, strong mottle that reads as clumped chromatin.
FLAT = (0.06, 0.0, 0.0, 0)
CHROMATIN = (0.24, 260.0, 0.0, 0)


# ================================================================================================ mesh helpers
def _revolve(profile, n_phi=30, phi0=0.0, phi1=2 * math.pi):
    """Surface of revolution about y of a profile [(r, y), ...] running from the top pole to the bottom pole."""
    prof = np.asarray(profile, float)
    closed = abs(phi1 - phi0) >= 2 * math.pi - 1e-6
    phi = np.linspace(phi0, phi1, n_phi, endpoint=not closed)
    r, y = prof[:, 0], prof[:, 1]
    pos = np.stack([r[:, None] * np.cos(phi)[None], np.broadcast_to(y[:, None], (len(r), len(phi))),
                    r[:, None] * np.sin(phi)[None]], -1).reshape(-1, 3)
    n = len(phi)
    a = np.arange(len(r) * n).reshape(len(r), n)
    b = np.roll(a, -1, axis=1) if closed else a[:, 1:]
    a = a if closed else a[:, :-1]
    q0, q1, q2, q3 = a[:-1].ravel(), b[:-1].ravel(), b[1:].ravel(), a[1:].ravel()
    tri = np.concatenate([np.stack([q0, q1, q2], 1), np.stack([q0, q2, q3], 1)])
    return pos, tri


def _rbc_profile(scale=1.0, n=13):
    """Evans-Fung shape of a resting red cell: thickness 2.1-2.6 um at the rim, ~0.8 um at the centre, 7.8 um
    across. Returns (r, y) from the top centre over the rim to the bottom centre, in model units."""
    R = 3.9 * scale
    t = np.sin(np.linspace(0.0, 1.0, n) * math.pi / 2)            # crowd samples toward the rim
    rho2 = t * t
    h = 0.5 * np.sqrt(np.clip(1.0 - rho2, 0.0, 1.0)) * (0.81 + 7.83 * rho2 - 4.39 * rho2 * rho2) * scale
    h = np.maximum(h, 0.0)
    top = np.stack([t * R, h], -1)
    bot = np.stack([t * R, -h], -1)[::-1][1:]
    return np.vstack([top, bot]) * K


RBC_POS, RBC_TRI = _revolve(_rbc_profile(), 30)
RBC_NRM = compute_normals(RBC_POS.astype(np.float32), RBC_TRI)


def _rot(axis, ang):
    axis = np.asarray(axis, float)
    axis /= np.linalg.norm(axis)
    x, y, z = axis
    c, s = math.cos(ang), math.sin(ang)
    return np.array([[c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
                     [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
                     [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)]])


def _instances(pos, tri, nrm, placements):
    """One mesh of many copies of a template: placements are (matrix, offset, scale)."""
    m = Mesh()
    if not placements:
        return m
    ps, ns, ids = [], [], []
    for i, (R, off, s) in enumerate(placements):
        ps.append(pos * s @ R.T + off)
        ns.append(nrm @ R.T)
        ids.append(tri + i * len(pos))
    return m.add(np.concatenate(ps), np.concatenate(ids), np.concatenate(ns))


def _dots(centers, radii, res=5, squash=(1.0, 0.8, 1.0)):
    """Many small ellipsoids (granules, plasma droplets) as one mesh."""
    centers = np.asarray(centers, float).reshape(-1, 3)
    if not len(centers):
        return Mesh()
    nu, nv = res, res * 2
    th = np.linspace(0, math.pi, nu)
    ph = np.linspace(0, 2 * math.pi, nv)
    T, P = np.meshgrid(th, ph, indexing="ij")
    unit = np.stack([np.sin(T) * np.cos(P), np.cos(T), np.sin(T) * np.sin(P)], -1).reshape(-1, 3)
    a = np.arange(nu * nv).reshape(nu, nv)
    q0, q1, q2, q3 = a[:-1, :-1].ravel(), a[1:, :-1].ravel(), a[1:, 1:].ravel(), a[:-1, 1:].ravel()
    tri = np.concatenate([np.stack([q0, q2, q1], 1), np.stack([q0, q3, q2], 1)])
    radii = np.broadcast_to(np.asarray(radii, float), (len(centers),))
    sq = np.asarray(squash, float)
    pos = (unit[None] * sq * radii[:, None, None] + centers[:, None]).reshape(-1, 3)
    nrm = np.tile(unit / sq, (len(centers), 1))
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
    idx = (tri[None] + (np.arange(len(centers)) * len(unit))[:, None, None]).reshape(-1, 3)
    return Mesh().add(pos, idx, nrm)


# ================================================================================================ red cells
def _rbc_cross_section(c, scale=1.0):
    """A red cell sliced through its centre: half a disc plus the flat dumbbell-shaped face of the cut."""
    prof = _rbc_profile(scale)
    pos, tri = _revolve(prof, 18, 0.0, math.pi)
    m = Mesh().add(pos, tri)
    # the cut face lies in the plane z = 0: a strip between the top and bottom halves of the profile, both sides
    n = (len(prof) + 1) // 2
    top = prof[:n]
    bot = prof[len(prof) - n:][::-1]
    face = []
    for sgn in (1.0, -1.0):
        face.append(np.stack([top[:, 0] * sgn, top[:, 1], np.zeros(n)], -1))
        face.append(np.stack([bot[:, 0] * sgn, bot[:, 1], np.zeros(n)], -1))
    fp = np.vstack(face)
    idx = []
    for k, flip in ((0, False), (2 * n, True)):
        i = np.arange(n - 1)
        a0, a1, b0, b1 = k + i, k + i + 1, k + n + i, k + n + i + 1
        t = np.concatenate([np.stack([a0, b0, b1], 1), np.stack([a0, b1, a1], 1)])
        idx.append(t[:, ::-1] if flip else t)
    face_tri = np.vstack(idx)
    face_nrm = np.tile([0.0, 0.0, -1.0], (len(fp), 1))
    # the half disc keeps phi in [0, pi] (z >= 0), so the cut faces -z; turn it to face the viewer (+z), then tip
    # the cut face up so it can be read from above
    m.add(fp, face_tri[:, ::-1] if _faces_minus_z(fp, face_tri) else face_tri, face_nrm)
    R = _rot((1, 0, 0), math.radians(-55.0)) @ _rot((0, 1, 0), math.pi)
    return m.transformed(R, c)


def _faces_minus_z(p, t):
    n = np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]])
    return n[:, 2].sum() > 0


def _scatter_rbcs(rng, keepout, counts, layers, region, tilt_max=0.26, edge_on=0.08, placed=None,
                  dense=False):
    """Dart-throw flat-lying red cells into layers of the plasma sheet without overlaps: counts[i] cells into
    layers[i], filling the lowest layer first like a smear's monolayer. A cell stood on its edge blocks every layer.
    `placed` ({layer: [(x, z)]}) carries the occupied spots from one call to the next."""
    x0, x1, z0, z1 = region
    r_disc = 3.9 * K * 1.04
    placed = placed if placed is not None else {}
    for ly in layers:
        placed.setdefault(ly, [])
    out = []
    ko = np.asarray(keepout, float).reshape(-1, 3)
    for li, (ly, count) in enumerate(zip(layers, counts)):
        tries, n = 0, 0
        # the bottom layer is seeded from a loose hexagonal packing, which random darts can never reach
        lattice = []
        if li == 0 and dense:
            lattice = hex_points((x0, z0), (x1, z1), 2 * r_disc * 1.06, 0.07, seed=int(rng.integers(1 << 30)))
            lattice = list(lattice[rng.permutation(len(lattice))])
        while n < count and tries < count * 300:
            tries += 1
            x, z = lattice.pop() if lattice else (rng.uniform(x0, x1), rng.uniform(z0, z1))
            if len(ko) and np.any(np.hypot(ko[:, 0] - x, ko[:, 1] - z) < ko[:, 2] + r_disc):
                continue
            s = rng.uniform(0.94, 1.05)
            on_edge = li == 0 and rng.random() < edge_on
            near = [placed[o] for o in (layers if on_edge else [ly]) if placed[o]]
            if any(np.min(np.hypot(np.array(q)[:, 0] - x, np.array(q)[:, 1] - z)) < 2 * r_disc * s + 0.006
                   for q in near):
                continue
            tilt = rng.uniform(1.2, 1.45) if on_edge else rng.uniform(0.0, tilt_max)
            axis = rng.normal(size=3)
            axis[1] = 0.0
            R = _rot((0, 1, 0), rng.uniform(0, 2 * math.pi)) @ _rot(axis, tilt)
            y = ly + rng.uniform(-0.012, 0.012)
            if on_edge:
                y = (Y_LO + Y_HI) / 2 - 0.02
                for o in layers:
                    placed[o].append((x, z))
            else:
                placed[ly].append((x, z))
            out.append((R, np.array([x, y, z]), s))
            n += 1
    return out


def _rouleau(c, n=7, seed=0):
    """Red cells stacked face to face like coins, the stack gently bowed."""
    rng = np.random.default_rng(seed)
    pitch = 2.05 * K
    out = []
    for i in range(n):
        t = (i - (n - 1) / 2)
        bow = 0.0025 * t * t
        ang = 0.05 * t
        R = _rot((0, 0, 1), math.pi / 2 + ang) @ _rot((0, 1, 0), rng.uniform(0, 6.28))
        out.append((R, np.array([c[0] + t * pitch, c[1] + bow * 0.4, c[2] + bow]), rng.uniform(0.97, 1.02)))
    return out


# ================================================================================================ leukocytes
class _Frame:
    """In-plane frame of one cell: local (u, v) in micrometres -> world, rotated by a random angle."""

    def __init__(self, c, ang):
        self.c = np.asarray(c, float)
        self.e1 = np.array([math.cos(ang), 0.0, math.sin(ang)])
        self.e2 = np.array([-math.sin(ang), 0.0, math.cos(ang)])

    def p(self, u, v, h=0.0):
        return self.c + (self.e1 * u + self.e2 * v) * K + np.array([0.0, h * K, 0.0])

    def arc(self, cu, cv, R, a0, a1, n=24):
        a = np.radians(np.linspace(a0, a1, n))
        return np.array([self.p(cu + R * math.cos(t), cv + R * math.sin(t)) for t in a])


def _nuc_neutrophil(f, rng, lobes=4):
    """3-5 lobes of condensed chromatin strung on thin filaments along a loose, irregular chain."""
    shapes = []
    span = 40.0 + 36.0 * lobes
    a0 = rng.uniform(0, 360)
    cen = []
    for i in range(lobes):
        a = math.radians(a0 + span * i / (lobes - 1) + rng.uniform(-10, 10))
        R = 2.6 + rng.uniform(-0.5, 0.5)
        cen.append(f.p(R * math.cos(a) - 0.6, R * math.sin(a)))
    for i, p in enumerate(cen):
        r = rng.uniform(1.1, 1.45) * K
        shapes.append(("s", ellipsoid(p, (r * rng.uniform(1.0, 1.25), r * 0.72, r * rng.uniform(0.8, 1.0)))))
        if i:
            mid = (p + cen[i - 1]) / 2 + rng.normal(scale=0.25 * K, size=3) * [1, 0, 1]
            shapes.append(("s", capsule(cen[i - 1], mid, 0.30 * K)))
            shapes.append(("s", capsule(mid, p, 0.30 * K)))
    return shapes


def _nuc_band(f, rng):
    path = f.arc(0.0, 0.0, 2.5, 20, 265, 30)
    return [("t", path, 0.82 * K)]


def _nuc_eosinophil(f, rng):
    """Two plump lobes joined by a band: the 'spectacles' nucleus."""
    a = f.p(-2.35, 0.45)
    b = f.p(2.35, 0.45)
    m = f.p(0.0, -0.1)
    return [("s", ellipsoid(a, (1.95 * K, 1.35 * K, 1.75 * K))), ("s", ellipsoid(b, (1.9 * K, 1.35 * K, 1.8 * K))),
            ("s", capsule(a, m, 0.55 * K)), ("s", capsule(m, b, 0.55 * K))]


def _nuc_basophil(f, rng):
    """An S-shaped, bilobed nucleus - mostly hidden under the granules."""
    p1 = f.arc(-1.3, 0.0, 1.35, 20, 200, 12)
    p2 = f.arc(1.3, 0.0, 1.35, 200, 380, 12)[::-1]
    path = smooth_path(np.vstack([p1, p2[1:]]), 30)
    return [("t", path, 1.25 * K)]


def _nuc_lymphocyte(f, rng, r_nuc, offset):
    """A round, dense nucleus with a shallow indentation on one side."""
    c = f.p(offset, 0.0)
    return [("s", ellipsoid(c, (r_nuc * K, r_nuc * 0.78 * K, r_nuc * 0.96 * K))),
            ("-", ellipsoid(f.p(offset + r_nuc * 1.18, 0.0), (0.9 * K, 1.2 * K, 1.1 * K)))]


def _nuc_monocyte(f, rng, horseshoe=False):
    """Kidney (bean) or horseshoe nucleus with a loose, lacy chromatin."""
    if horseshoe:
        path = f.arc(-0.8, 0.0, 3.1, 60, 300, 36)
        r = np.full(len(path), 1.55 * K)
    else:
        path = f.arc(-2.2, 0.0, 3.3, -62, 62, 30)
        t = np.linspace(-1, 1, len(path))
        r = (2.35 - 0.35 * t * t) * K
    return [("t", path, r)]


def _shape_field(vol, shapes, blend):
    """Signed distance of a nucleus made of smooth-blended spheres/capsules/tubes minus indentations."""
    v = vol.copy(np.full(vol.shape, BIG, np.float32))
    minus = []
    for s in shapes:
        if s[0] == "s":
            v.add(s[1], "smooth", blend)
        elif s[0] == "t":
            path, r = s[1], s[2]
            r = np.broadcast_to(np.asarray(r, float), (len(path),))
            for i in range(len(path) - 1):
                v.add(capsule(path[i], path[i + 1], float(max(r[i], r[i + 1]))), "smooth", blend * 0.5)
        elif s[0] == "-":
            minus.append(s[1])
    for m in minus:
        v.add(m, "smooth_subtract", blend)
    return v.d


def _point_sdf(shapes, pts):
    """Distance of points to the nucleus shapes (union of solids only - good enough to keep granules off it)."""
    pts = np.asarray(pts, float)
    d = np.full(len(pts), BIG)
    x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
    for s in shapes:
        if s[0] == "s":
            d = np.minimum(d, s[1][0](x, y, z))
        elif s[0] == "t":
            path, r = s[1], np.broadcast_to(np.asarray(s[2], float), (len(s[1]),))
            for i in range(len(path) - 1):
                d = np.minimum(d, capsule(path[i], path[i + 1], float(r[i]))[0](x, y, z))
    return d


def _leukocyte(c, r_um, flat, shapes, rng, granules=None, vacuoles=0, ruffle=0.0022):
    """A white cell cut in half at its equator. Returns (cytoplasm, nucleus, granules) meshes.

    The cytoplasm is the lower half of a flattened, ruffled ellipsoid with the nucleus carved out of it; the nucleus
    fills that hole and stands a hair proud of the cut, and granules are strewn across the cut face so their tops
    break through it the way they stud the cytoplasm on a smear."""
    c = np.asarray(c, float)
    r = r_um * K
    pad = 0.02
    ext = np.array([r + pad, r * flat + pad, r + pad])
    vol = Volume(c - ext, c + ext, VOX)
    vol.add(ellipsoid(c, (r, r * flat, r)))
    vol.displace(ruffle, 70.0, octaves=2, seed=int(rng.integers(1000)), coarse=2)
    cell = vol.d.copy()
    _, y, _ = vol.axes()
    cut = y - c[1]
    nuc = _shape_field(vol, shapes, 0.3 * K)
    cyto = np.maximum(np.maximum(cell, cut), -nuc)
    for _ in range(vacuoles):
        a, rr = rng.uniform(0, 2 * math.pi), rng.uniform(0.55, 0.9) * r
        p = c + np.array([math.cos(a) * rr, rng.uniform(-0.3, 0.1) * K, math.sin(a) * rr])
        if _point_sdf(shapes, p[None])[0] < 0.4 * K:
            continue
        vr = rng.uniform(0.25, 0.45) * K
        sub = vol.copy(np.full(vol.shape, BIG, np.float32))
        sub.add(ellipsoid(p, (vr, vr, vr)))
        cyto = np.maximum(cyto, -sub.d)
    nucl = np.maximum(np.maximum(nuc, cut - 0.10 * K), cell + 0.004)
    cyto_mesh = vol.copy(cyto).mesh(0.6, step=2)          # the cytoplasm is smooth: half resolution
    nuc_mesh = vol.copy(nucl).mesh(0.7)
    gran = Mesh()
    if granules:
        g, spacing, over = granules["r"] * K, granules["spacing"] * K, granules.get("over_nucleus", False)
        n_try = int(8 * (r / spacing) ** 2) + 50
        a = rng.uniform(0, 2 * math.pi, n_try)
        rr = np.sqrt(rng.uniform(0, 1, n_try)) * (r * 0.93 - g)
        pts = np.stack([c[0] + np.cos(a) * rr, np.full(n_try, c[1]), c[2] + np.sin(a) * rr], -1)
        if not over:
            pts = pts[_point_sdf(shapes, pts) > g * 0.9]
        keep = []
        tree = None
        for p in pts:
            if keep and tree is not None and tree.query(p)[0] < spacing:
                continue
            keep.append(p)
            tree = cKDTree(np.array(keep))
        keep = np.array(keep).reshape(-1, 3)
        rad = g * rng.uniform(0.8, 1.2, len(keep))
        keep[:, 1] = c[1] - rad * 0.25 + (0.10 * K if over else 0.0)
        gran = _dots(keep, rad, res=granules.get("res", 5))
        # a few granules pressing up under the membrane of the intact lower half
        if granules.get("rim"):
            m = granules["rim"]
            th = rng.uniform(0, 2 * math.pi, m)
            ph = rng.uniform(0.15, 1.2, m)
            rim = c + np.stack([np.cos(th) * np.cos(ph) * r * 0.98, -np.sin(ph) * r * flat * 0.98,
                                np.sin(th) * np.cos(ph) * r * 0.98], -1)
            gran.extend(_dots(rim, g * rng.uniform(0.8, 1.1, m), res=granules.get("res", 5)))
    return cyto_mesh, nuc_mesh, gran


# ================================================================================================ platelets & clot
def _platelet_placements(rng, centers):
    out = []
    for p in centers:
        R = _rot((0, 1, 0), rng.uniform(0, 6.28)) @ _rot((1, 0, 0), rng.uniform(-0.3, 0.3))
        out.append((R, np.asarray(p, float), rng.uniform(0.75, 1.3)))
    return out


def _platelet_template():
    """A resting platelet: a lentil ~3 um across and ~1 um thick with a slightly granular (bumpy) centre."""
    t = np.linspace(0.0, 1.0, 8)
    r = np.sin(t * math.pi / 2)
    h = 0.5 * np.sqrt(np.clip(1 - r * r, 0, 1)) * (1.0 + 0.25 * np.cos(r * 9.0))
    top = np.stack([r * 1.5, h * 1.0], -1)
    bot = np.stack([r * 1.5, -h * 0.9], -1)[::-1][1:]
    pos, tri = _revolve(np.vstack([top, bot]) * K, 14)
    pos[:, 2] *= 0.8
    return pos, tri, compute_normals(pos.astype(np.float32), tri)


def _fibrin(rng, region, count=70):
    """A loose felt of fibrin strands: long, slightly wavy fibres crossing the clot and branching at nodes."""
    x0, x1, z0, z1 = region
    m = Mesh()
    nodes = np.stack([rng.uniform(x0, x1, count), rng.uniform(Y_LO + 0.03, Y_HI - 0.02, count),
                      rng.uniform(z0, z1, count)], -1)
    tree = cKDTree(nodes)
    done = set()
    for i, p in enumerate(nodes):
        d, nb = tree.query(p, k=4)
        for dist, j in zip(d[1:], nb[1:]):
            key = (min(i, j), max(i, j))
            if key in done or dist > 0.34:
                continue
            done.add(key)
            q = nodes[j]
            mid = (p + q) / 2 + rng.normal(scale=dist * 0.10, size=3)
            path = smooth_path(np.array([p, mid, q]), 12)
            m.extend(tube(path, rng.uniform(0.10, 0.2) * K, 7, caps=False))
    # a few long strands that run out of the clot into the field
    for _ in range(9):
        a = nodes[rng.integers(count)]
        d = np.array([rng.uniform(-1, 0.2), rng.uniform(-0.1, 0.1), rng.uniform(-0.1, 1)])
        d /= np.linalg.norm(d)
        pts = [a + d * s + rng.normal(scale=0.02, size=3) * [1, 0.3, 1] for s in np.linspace(0, 0.38, 5)]
        pts = np.array(pts)
        pts[:, 1] = np.clip(pts[:, 1], Y_LO + 0.02, Y_HI - 0.02)
        m.extend(tube(smooth_path(pts, 20), 0.16 * K, 7, caps=False))
    return m, nodes


# ================================================================================================ build
DESC = {
    "plasma": (
        "Plasma: the straw-coloured fluid that makes up ~55% of blood volume (the formed elements are the other "
        "~45%, the haematocrit). It is ~91% water plus plasma proteins - albumin (~60%, made by the liver, holds "
        "oncotic pressure and carries drugs, bilirubin and hormones), globulins (alpha and beta transport "
        "proteins; gamma globulins are antibodies made by plasma cells) and fibrinogen (liver; becomes fibrin in "
        "a clot). The liver also makes most clotting factors. It carries electrolytes (Na+, K+, Cl-, HCO3-), "
        "glucose, lipids, hormones and wastes such as urea. Serum is plasma with the fibrinogen and clotting "
        "factors used up by clotting."),
    "rbc": (
        "Erythrocytes (red blood cells): the most numerous cells, ~4.5-5.5 million/mm3 (lower in women). "
        "Anucleate, pink-staining biconcave discs ~7.5-7.8 um across and ~2.5 um thick at the rim, ~0.8 um at the "
        "centre - hence the pale central pallor (about a third of the diameter) on a smear. The biconcave shape "
        "gives a large surface for gas exchange, keeps every haemoglobin molecule close to the membrane, and lets "
        "the cell fold through 3 um capillaries and splenic slits. No nucleus or mitochondria: glycolysis only, "
        "so they cannot use the oxygen they carry. Packed with haemoglobin (~33% of the cell). Made in red bone "
        "marrow (erythropoiesis, driven by renal erythropoietin in hypoxia), released as reticulocytes (~1%), live "
        "~120 days and are removed by macrophages of the spleen and liver. Fall in anaemia and haemorrhage; rise "
        "(polycythaemia) at altitude, in chronic hypoxia, with EPO-secreting tumours and in polycythaemia vera. "
        "Here scattered in two loose layers, most lying flat, a few tipped on edge, and trapped in the clot."),
    "rbc_cut": (
        "Erythrocyte cut through its centre: the section is a dumbbell - thick rim, thin centre - which is why "
        "red cells show central pallor. Size to compare with the white cells: a red cell is ~7.5 um, about the "
        "size of a small lymphocyte's nucleus. Spherocytes (hereditary spherocytosis) lose this shape and the "
        "pallor; sickle cells (HbS polymerises when deoxygenated) become rigid crescents that block capillaries."),
    "rouleau": (
        "Rouleau: red cells stacked face to face like a pile of coins. A few form in thick areas of any smear, "
        "but extensive rouleaux mean more positively charged plasma proteins (fibrinogen, immunoglobulins) "
        "neutralising the negative surface charge (zeta potential) that normally keeps red cells apart - "
        "inflammation, pregnancy and above all multiple myeloma. Rouleaux sediment fast, which is what the "
        "erythrocyte sedimentation rate (ESR) measures."),
    "platelet": (
        "Platelets (thrombocytes): 150,000-400,000/mm3. Anucleate fragments of megakaryocytes in the bone marrow "
        "(one megakaryocyte sheds ~2,000-4,000), 2-4 um discs that stain purple on a smear - a granular purple "
        "centre (granulomere: alpha and dense granules) and a pale blue rim (hyalomere) - seen singly or in small "
        "clumps. Live ~7-10 days; a third are pooled in the spleen. Production is driven by liver thrombopoietin. "
        "They plug breaches in vessel walls (adhere via von Willebrand factor to collagen, activate, aggregate "
        "via fibrinogen bridges on GPIIb/IIIa) and provide the surface on which the coagulation cascade makes "
        "thrombin. Low (thrombocytopenia): petechiae, purpura, mucosal bleeding - ITP, marrow failure, leukaemia, "
        "DIC, hypersplenism, heparin (HIT). High (thrombocytosis): reactive after bleeding, iron deficiency, "
        "inflammation or splenectomy, or essential thrombocythaemia."),
    "platelet_act": (
        "Activated platelets: on contact with collagen, thrombin or ADP they change from smooth discs into spiky "
        "spheres with long pseudopods, release their granules (ADP, serotonin, thromboxane A2, fibrinogen, vWF, "
        "PDGF) which recruit more platelets, and aggregate into the primary haemostatic plug. Aspirin blocks "
        "thromboxane A2 synthesis for the platelet's whole 7-10 day life; clopidogrel blocks the ADP (P2Y12) "
        "receptor. Clot retraction by their actin-myosin pulls the fibrin mesh tight."),
    "fibrin": (
        "Fibrin: the coagulation cascade ends with thrombin cutting soluble fibrinogen (a liver-made plasma "
        "protein) into fibrin monomers that polymerise into long strands, cross-linked by factor XIIIa. The mesh "
        "traps red cells and platelets to form a stable clot (secondary haemostasis). Plasmin later dissolves it "
        "(fibrinolysis; D-dimers are the breakdown products). Clotting factors II, VII, IX and X need vitamin K, "
        "which warfarin blocks; haemophilia A and B lack factors VIII and IX."),
    "neut": (
        "Neutrophil (polymorphonuclear leukocyte): the most common white cell, 60-70% of leukocytes (about "
        "2,000-7,500/mm3), 10-12 um (~1.5 red cells). Nucleus of 3-5 lobes joined by thin chromatin threads; pale "
        "pink-lilac cytoplasm with fine, barely visible granules. Made in the bone marrow, circulate only 6-10 "
        "hours and live 1-2 days in the tissues. They are the first cells to arrive at acute inflammation: they "
        "roll, adhere and squeeze between endothelial cells (diapedesis), then phagocytose and kill bacteria with "
        "their granule enzymes and oxidative burst (NADPH oxidase, myeloperoxidase); dead neutrophils make pus. "
        "Rise (neutrophilia) in acute bacterial infection (appendicitis, pneumonia), tissue damage, "
        "corticosteroids, stress and CML; immature band forms appear (left shift). Fall (neutropenia) with "
        "chemotherapy, some drugs (carbimazole, clozapine), viral infection and marrow failure - with a high risk "
        "of bacterial and fungal sepsis. Hypersegmented nuclei (6+ lobes) suggest B12/folate deficiency."),
    "band": (
        "Band neutrophil: an immature neutrophil whose nucleus is still an unsegmented, curved band (a U or C of "
        "even width) - normally under 5% of white cells. More bands in the blood (a 'left shift') means the marrow "
        "is releasing neutrophils early, typically in acute bacterial infection or sepsis."),
    "neut_nuc": (
        "Neutrophil nucleus: 3-5 lobes of condensed, dark purple chromatin linked by fine threads - "
        "'polymorphonuclear'. The number of lobes rises with the cell's age. In women a small drumstick (the "
        "inactive X, Barr body) hangs from a lobe in a few percent of cells. The band form (unsegmented horseshoe) "
        "is the stage before segmentation."),
    "neut_gran": (
        "Neutrophil granules: fine, pale lilac-pink dust ('neutrophilic' - they take up neither dye strongly). "
        "Primary (azurophilic) granules are lysosomes holding myeloperoxidase, elastase and defensins; the more "
        "numerous secondary (specific) granules hold lactoferrin, lysozyme and collagenase. Coarse, dark 'toxic "
        "granulation' appears in severe infection."),
    "eos": (
        "Eosinophil: 2-4% of white cells, 12-14 um (~2 red cells). A bilobed 'spectacles' nucleus and cytoplasm "
        "packed with large, uniform, bright orange-red granules (they bind the acidic dye eosin). Circulate for "
        "hours, then live ~1-2 weeks in tissues, especially under the mucosa of the gut, airways and skin. They "
        "kill helminths too large to phagocytose by releasing granule proteins onto them, and modulate allergic "
        "reactions (they degrade histamine and leukotrienes but also cause tissue damage in asthma). Rise "
        "(eosinophilia) in allergy (asthma, hay fever, eczema), parasitic worm infection (e.g. trichinosis, "
        "Strongyloides, schistosomiasis), drug reactions, Addison disease, Hodgkin lymphoma and eosinophilic "
        "granulomatosis with polyangiitis. Fall with corticosteroids and acute stress."),
    "eos_nuc": (
        "Eosinophil nucleus: usually two plump lobes joined by a thin band, like a pair of spectacles or a "
        "telephone receiver, and less condensed than a neutrophil's."),
    "eos_gran": (
        "Eosinophil (specific) granules: large (0.5-1 um), round, refractile and orange-red with eosin. Each has a "
        "crystalline core of major basic protein surrounded by eosinophil cationic protein, eosinophil peroxidase "
        "and eosinophil-derived neurotoxin - toxic to worms and to host epithelium. The core crystallises as "
        "Charcot-Leyden crystals in asthmatic sputum."),
    "baso": (
        "Basophil: the rarest white cell, 0.5-1%, 8-10 um. The nucleus is S-shaped or bilobed but largely hidden "
        "by coarse, dark blue-purple granules that also lie over it. Granules hold histamine (vasodilator, "
        "increases capillary permeability) and heparin (anticoagulant); the surface carries IgE receptors, so "
        "allergen cross-linking releases them - like the tissue mast cell, which it resembles but is a different "
        "lineage. Lives hours to days. Rise (basophilia) in allergic and inflammatory reactions, hypothyroidism "
        "and especially chronic myeloid leukaemia and other myeloproliferative disorders."),
    "baso_nuc": (
        "Basophil nucleus: S-shaped or bilobed, paler than a neutrophil's, and on a smear mostly obscured by the "
        "granules lying on top of it."),
    "baso_gran": (
        "Basophil granules: large, uneven, deep blue-purple (basophilic - they bind the basic dye because of "
        "their sulphated heparin; metachromatic). They contain histamine, heparin and chemotactic factors and are "
        "released within seconds in anaphylaxis. Water-soluble, so on a poor smear they may be washed out, "
        "leaving empty spaces."),
    "lymph_s": (
        "Small lymphocyte: the commonest lymphocyte, 6-9 um - about the size of a red cell. A round, very dense, "
        "dark purple nucleus (sometimes slightly indented) nearly fills the cell, leaving a thin rim (halo) of "
        "sky-blue cytoplasm. Lymphocytes are 20-30% of white cells, the second most numerous. B and T cells look "
        "identical on Wright stain: both arise from marrow stem cells; B cells mature in the bone marrow and become "
        "antibody-secreting plasma cells (humoral immunity); T cells mature in the thymus and kill virus-infected "
        "and tumour cells or direct the immune response (cell-mediated immunity). Most lymphocytes live in lymph "
        "nodes, spleen and MALT and recirculate between blood and lymph; memory cells live for years. Rise "
        "(lymphocytosis) in viral infections (infectious mononucleosis with atypical lymphocytes, CMV, hepatitis), "
        "pertussis, tuberculosis and chronic lymphocytic leukaemia. Fall (lymphopenia) with corticosteroids, HIV "
        "(CD4 T cells), chemotherapy and immunodeficiency."),
    "lymph_l": (
        "Large lymphocyte: 10-15 um, with more pale blue cytoplasm around an eccentric round nucleus with less "
        "condensed chromatin. These are activated lymphocytes responding to antigen, and natural killer cells "
        "(large granular lymphocytes, with a few pink azurophilic granules). Reactive ('atypical') large "
        "lymphocytes with abundant cytoplasm that hugs the red cells are typical of glandular fever (EBV)."),
    "lymph_nuc": (
        "Lymphocyte nucleus: round or slightly indented, with dense, coarsely clumped dark chromatin; in the small "
        "lymphocyte it fills almost the whole cell. Nuclear size is the easiest yardstick on a smear: a small "
        "lymphocyte nucleus is about one red cell across."),
    "mono": (
        "Monocyte: the largest white cell, 12-20 um (~2-3 red cells), 3-8% of leukocytes. Abundant grey-blue "
        "'ground glass' cytoplasm, often with small vacuoles and a fine dust of azurophil granules, around a "
        "large kidney- or horseshoe-shaped nucleus with lacy, less condensed chromatin. Made in the bone marrow, "
        "circulate 1-3 days, then enter tissues and become macrophages (Kupffer cells, alveolar macrophages, "
        "microglia, osteoclasts arise from the same lineage), which phagocytose microbes and debris, present "
        "antigen and live months. Rise (monocytosis) in chronic infection (tuberculosis, endocarditis, "
        "brucellosis), recovery from acute infection, inflammatory bowel disease, sarcoidosis and chronic "
        "myelomonocytic leukaemia."),
    "mono_nuc": (
        "Monocyte nucleus: large, eccentric, kidney-bean or horseshoe shaped, with a delicate lacy (open) "
        "chromatin pattern that stains paler than a lymphocyte's - the two features that separate a monocyte from "
        "a large lymphocyte."),
}


def build_blood():
    rng = np.random.default_rng(2024)
    parts = []
    keep = []                      # (x, z, radius) of everything red cells must avoid

    # ------------------------------------------------------------------ white cells
    # lineup along the front in order of abundance: N L L M E B
    lineup = [("neut", 6.0), ("lymph_s", 3.6), ("lymph_l", 5.6), ("mono", 8.0), ("eos", 6.5), ("baso", 5.2)]
    gap = 0.11
    total = sum(r * 2 * K for _, r in lineup) + gap * (len(lineup) - 1)
    x = -total / 2
    cells = []
    for kind, r in lineup:
        x += r * K
        cells.append((kind, np.array([x, 0.0, LANE_Z + rng.uniform(-0.03, 0.03)]), r, 1))
        x += r * K + gap
    # scattered among the red cells: neutrophils commonest, then lymphocytes, a monocyte, an eosinophil
    scatter = [("neut", (-0.45, -0.02, 0.06), 5.8), ("neut", (0.42, 0.0, -0.40), 6.1),
               ("neut", (1.12, 0.01, 0.10), 5.9), ("band", (-0.05, 0.0, -0.66), 5.9),
               ("lymph_s", (0.62, 0.0, 0.02), 3.7), ("lymph_s", (-1.22, 0.0, 0.12), 3.5),
               ("mono", (-0.02, -0.01, -0.20), 7.6), ("eos", (-0.70, 0.0, -0.40), 6.4),
               ("neut", (-1.25, 0.0, -0.22), 6.0)]
    for kind, p, r in scatter:
        cells.append((kind, np.array(p, float), r, 0))
    mesh = {k: Mesh() for k in ("neut", "band", "neut_nuc", "neut_gran", "eos", "eos_nuc", "eos_gran", "baso",
                                "baso_nuc", "baso_gran", "lymph_s", "lymph_l", "lymph_nuc", "mono", "mono_nuc")}
    for i, (kind, c, r, _) in enumerate(cells):
        crng = np.random.default_rng(100 + i)
        f = _Frame(c, crng.uniform(0, 2 * math.pi))
        if kind == "neut":
            shapes = _nuc_neutrophil(f, crng, lobes=int(crng.choice([3, 4, 4, 5])) if i else 4)
            out = _leukocyte(c, r, 0.62, shapes, crng, granules={"r": 0.22, "spacing": 0.55, "res": 4})
            keys = ("neut", "neut_nuc", "neut_gran")
        elif kind == "band":
            out = _leukocyte(c, r, 0.62, _nuc_band(f, crng), crng, granules={"r": 0.22, "spacing": 0.55, "res": 4})
            keys = ("band", "neut_nuc", "neut_gran")
        elif kind == "eos":
            out = _leukocyte(c, r, 0.62, _nuc_eosinophil(f, crng), crng,
                             granules={"r": 0.42, "spacing": 0.88, "res": 6, "rim": 120})
            keys = ("eos", "eos_nuc", "eos_gran")
        elif kind == "baso":
            out = _leukocyte(c, r, 0.66, _nuc_basophil(f, crng), crng,
                             granules={"r": 0.50, "spacing": 1.0, "over_nucleus": True, "res": 6, "rim": 70})
            keys = ("baso", "baso_nuc", "baso_gran")
        elif kind == "lymph_s":
            out = _leukocyte(c, r, 0.80, _nuc_lymphocyte(f, crng, 2.95, 0.25), crng, ruffle=0.0015)
            keys = ("lymph_s", "lymph_nuc", None)
        elif kind == "lymph_l":
            out = _leukocyte(c, r, 0.66, _nuc_lymphocyte(f, crng, 3.6, 1.05), crng)
            keys = ("lymph_l", "lymph_nuc", None)
        else:
            out = _leukocyte(c, r, 0.60, _nuc_monocyte(f, crng, horseshoe=(i != 3)), crng, vacuoles=9,
                             ruffle=0.0028)
            keys = ("mono", "mono_nuc", None)
        for k, m in zip(keys, out):
            if k:
                mesh[k].extend(m)
        keep.append((c[0], c[2], r * K + 0.012))
    # keep the lineup lane clear of red cells so the row reads at a glance
    lane_keep = [(xx, LANE_Z, 0.25) for xx in np.linspace(-1.3, 1.3, 14)]

    # ------------------------------------------------------------------ red cells
    rbc_cut_c = np.array([0.24, -0.03, 0.30])
    keep += [(rbc_cut_c[0], rbc_cut_c[2], 0.13)]
    ro = np.array(ROULEAU)
    keep += [(ro[0] + t, ro[2], 0.14) for t in np.linspace(-0.2, 0.2, 5)]
    clot_keep = [(x_, z_, 0.07) for x_ in np.linspace(CLOT[0], CLOT[1], 8) for z_ in np.linspace(CLOT[2], CLOT[3], 6)]
    layers = [-0.105, 0.035]
    placed = {}
    field = _scatter_rbcs(rng, keep + lane_keep + clot_keep, (90, 22), layers, (X0 + 0.1, X1 - 0.1, Z0 + 0.1, 0.36),
                          placed=placed, dense=True)
    # a few red cells drifting in the lane between the lineup cells for scale
    field += _scatter_rbcs(rng, keep + clot_keep, (7,), [-0.105], (X0 + 0.1, X1 - 0.1, 0.36, Z1 - 0.16), edge_on=0.0,
                           placed=placed)
    # trapped in the clot
    clot_box = (CLOT[0] + 0.04, CLOT[1] - 0.04, CLOT[2] + 0.04, CLOT[3] - 0.02)
    trapped = _scatter_rbcs(rng, keep, (10, 6), layers, clot_box,
                            tilt_max=0.7, edge_on=0.15)
    rbc = _instances(RBC_POS, RBC_TRI, RBC_NRM, field + trapped)
    parts.append(mesh_part(rbc, "Erythrocytes", GROUP_RBC, C["rbc"], DESC["rbc"], category="other", clip=False,
                           detail=FLAT))
    parts.append(mesh_part(_instances(RBC_POS, RBC_TRI, RBC_NRM, _rouleau(ro, 7)), "Rouleau", GROUP_RBC,
                           C["rouleau"], DESC["rouleau"], category="other", clip=False, detail=FLAT))
    parts.append(mesh_part(_rbc_cross_section(rbc_cut_c, 1.0), "Erythrocyte cross-section", GROUP_RBC,
                           C["rbc_cut"], DESC["rbc_cut"], category="other", clip=False, detail=FLAT))

    # ------------------------------------------------------------------ platelets
    all_rbc = np.array([o for _, o, _ in field + trapped])
    solid = cKDTree(np.vstack([all_rbc[:, [0, 2]], np.array([[k[0], k[1]] for k in keep])]))
    rad = np.concatenate([np.full(len(all_rbc), 0.0), np.array([k[2] for k in keep])])
    pl = []
    tries = 0
    while len(pl) < 34 and tries < 5000:
        tries += 1
        p = np.array([rng.uniform(X0 + 0.08, X1 - 0.08), 0.0, rng.uniform(Z0 + 0.08, Z1 - 0.08)])
        if CLOT[0] - 0.05 < p[0] and p[2] < CLOT[3] + 0.05:
            continue
        idx = solid.query_ball_point(p[[0, 2]], 0.16)
        # float above or below the red cells where they would touch one
        p[1] = rng.choice([-0.185, 0.115]) if idx else rng.uniform(-0.12, 0.06)
        if any(np.hypot(*(p[[0, 2]] - solid.data[j])) < rad[j] + 0.05 for j in idx if rad[j] > 0):
            continue
        if pl and min(np.linalg.norm(p - q) for q in pl) < 0.09:
            continue
        pl.append(p)
        if rng.random() < 0.2:                        # a little clump
            for _ in range(rng.integers(2, 5)):
                pl.append(p + np.array([rng.uniform(-0.07, 0.07), rng.uniform(-0.02, 0.02),
                                        rng.uniform(-0.07, 0.07)]))
    ppos, ptri, pnrm = _platelet_template()
    parts.append(mesh_part(_instances(ppos, ptri, pnrm, _platelet_placements(rng, pl)), "Platelets", GROUP_RBC,
                           C["platelet"], DESC["platelet"], category="other", clip=False, detail=(0.18, 0, 0, 0)))

    # ------------------------------------------------------------------ white-cell parts
    def wbc(key, name, group, detail=FLAT):
        parts.append(mesh_part(mesh[key], name, group, C[key], DESC[key], category="other", clip=False,
                               detail=detail))
    wbc("neut", "Neutrophil", GROUP_GRAN)
    wbc("band", "Band neutrophil", GROUP_GRAN)
    wbc("neut_nuc", "Neutrophil nucleus", GROUP_GRAN, CHROMATIN)
    wbc("neut_gran", "Neutrophil granules", GROUP_GRAN)
    wbc("eos", "Eosinophil", GROUP_GRAN)
    wbc("eos_nuc", "Eosinophil nucleus", GROUP_GRAN, CHROMATIN)
    wbc("eos_gran", "Eosinophil granules", GROUP_GRAN, (0.12, 0, 0, 0))
    wbc("baso", "Basophil", GROUP_GRAN)
    wbc("baso_nuc", "Basophil nucleus", GROUP_GRAN, CHROMATIN)
    wbc("baso_gran", "Basophil granules", GROUP_GRAN, (0.12, 0, 0, 0))
    wbc("lymph_s", "Small lymphocyte", GROUP_AGRAN)
    wbc("lymph_l", "Large lymphocyte", GROUP_AGRAN)
    wbc("lymph_nuc", "Lymphocyte nucleus", GROUP_AGRAN, CHROMATIN)
    wbc("mono", "Monocyte", GROUP_AGRAN, (0.10, 0, 0, 0))
    wbc("mono_nuc", "Monocyte nucleus", GROUP_AGRAN, (0.20, 180.0, 0.0, 0))

    # ------------------------------------------------------------------ clot corner
    fib, nodes = _fibrin(rng, (CLOT[0] + 0.02, CLOT[1] - 0.02, CLOT[2] + 0.02, CLOT[3] - 0.02))
    parts.append(mesh_part(fib, "Fibrin", GROUP_CLOT, C["fibrin"], DESC["fibrin"], category="other", clip=False,
                           detail=FLAT))
    act = Mesh()
    for j in range(11):
        p = nodes[rng.integers(len(nodes))] + rng.normal(scale=0.01, size=3)
        p[1] = np.clip(p[1], Y_LO + 0.06, Y_HI - 0.06)
        body = np.array([1.3, 1.0, 1.3]) * K * rng.uniform(0.9, 1.2)
        act.extend(star_cell(p, body, int(rng.integers(5, 9)), 2.6 * K, rng, sub_vox=0.0036))
    parts.append(mesh_part(act, "Activated platelets", GROUP_CLOT, C["platelet_act"], DESC["platelet_act"],
                           category="other", clip=False, detail=(0.15, 0, 0, 0)))

    # ------------------------------------------------------------------ plasma
    plasma = box_mesh(((X0 + X1) / 2, (Y_LO + Y_HI) / 2, (Z0 + Z1) / 2), (X1 - X0, Y_HI - Y_LO, Z1 - Z0))
    parts.append(mesh_part(plasma, "Plasma", GROUP_PLASMA, C["plasma"], DESC["plasma"], category="csf",
                           alpha=0.24, bulk=True, rank=-1, detail=(0.02, 0, 0, 0)))
    return parts
