"""Eye: the right eyeball with its muscles, eyelids, conjunctiva and lacrimal apparatus.

Built in millimetres around the centre of the globe and scaled to model units at the end (1 unit = 12 mm, so the
globe is two units across like every other model). Axes: +z anterior (the optical axis), +y superior, +x medial
(nasal) - a right eye seen from the front has its nose side on the viewer's right.

Everything that is round about the optical axis (cornea, limbus, iris, ciliary body, lens, chambers) is a lathe of
a hand-drawn meridional profile, so the tissues nest exactly. The coats of the posterior globe (sclera, choroid,
pigmented and neural retina) are shells between a rim around the optic disc - which sits 3 mm nasal to the
posterior pole, so it is off the optical axis - and a rim at the front (limbus or ora serrata), with their thickness
a function of direction: the fovea is a real pit in the neural retina and the disc a real hole in every coat.

The eyelids and the conjunctival sac are profiles drawn in planes through the vertical axis of the globe and swept
from the lateral to the medial canthus, so the lids wrap round the globe, and every layer of a lid (skin, orbicularis,
tarsus, tarsal glands, palpebral conjunctiva, fornix) stays in register in the sagittal cut. Extraocular muscles are
flat ribbons that run from the common tendinous ring and wrap onto the globe to their insertions.
"""
import math

import numpy as np

from .base import Part
from .cells import orient_outward
from .geometry import Mesh, ellipsoid as ellipsoid_mesh, smooth_path, tube
from .kit import Volume, ellipsoid

MM = 1.0 / 12.0                 # model units per millimetre

# ------------------------------------------------------------------------------------------------ dimensions (mm)
R_S = 11.5                      # outer radius of the sclera, centred on the origin
CF_C, CF_R = 4.69, 7.8          # anterior corneal surface: centre z, radius (vertex at z = 12.49; axial length 24)
CB_C, CB_R = 5.14, 6.8          # posterior corneal surface (vertex 11.94: central cornea 0.55 mm thick)
LIMBUS_R = 5.75                 # corneal radius (11.5 mm horizontal diameter)
LENS_A, LENS_B1, LENS_B2, LENS_Z = 4.6, 1.65, 2.35, 7.0      # lens: equatorial radius, front/back half-thickness
PUPIL_R = 1.75
IRIS_ROOT = 6.05
TH_LIMBUS, TH_SPUR, TH_ORA = 30.0, 38.0, 68.0                # angles from the anterior pole (degrees)
SPUR = (6.22, 7.96)
GAP = 0.36                      # conjunctival sac (tear film) between the lids and the globe, exaggerated
CT = 0.13                       # conjunctival thickness, exaggerated


def _unit(*v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


D_DISC = _unit(0.262, 0.035, -0.964)       # optic disc: 3 mm nasal, slightly above the posterior pole
F_FOV = _unit(-0.13, -0.04, -0.99)         # fovea: ~4 mm temporal and a little below the disc
APEX = np.array([11.5, 0.8, -32.0])        # common tendinous ring at the orbital apex (posterior and medial)


# ================================================================================================ mesh helpers
def _closed(pos, tri):
    return orient_outward(Mesh().add(np.asarray(pos, np.float64), np.asarray(tri, np.int64)))


def _grid(nu, nv, wrap_v=True, off=0):
    a = np.arange(nu * nv).reshape(nu, nv) + off
    b = np.roll(a, -1, 1) if wrap_v else a[:, 1:]
    a0 = a if wrap_v else a[:, :-1]
    q00, q01 = a0[:-1], b[:-1]
    q10, q11 = a0[1:], b[1:]
    return np.concatenate([np.stack([q00, q10, q11], -1).reshape(-1, 3),
                           np.stack([q00, q11, q01], -1).reshape(-1, 3)])


def lathe(profile, n=240, disp=None):
    """Solid of revolution about the z axis from a closed (r, z) profile. disp(R, Z, PHI) may displace it."""
    prof = np.asarray(profile, float)
    m = len(prof)
    phi = np.linspace(0.0, 2 * math.pi, n, endpoint=False)
    P = np.repeat(phi[:, None], m, 1)
    R = np.repeat(prof[None, :, 0], n, 0)
    Z = np.repeat(prof[None, :, 1], n, 0)
    if disp is not None:
        R, Z = disp(R, Z, P)
    pos = np.stack([R * np.cos(P), R * np.sin(P), Z], -1).reshape(-1, 3)
    a = np.arange(n * m).reshape(n, m)
    b = np.roll(a, -1, 0)
    a1, b1 = np.roll(a, -1, 1), np.roll(b, -1, 1)
    tri = np.concatenate([np.stack([a, b, b1], -1).reshape(-1, 3), np.stack([a, b1, a1], -1).reshape(-1, 3)])
    return _closed(pos, tri)


def _rot_z_to(axis):
    """Rotation taking +z onto `axis`."""
    a = _unit(*axis)
    z = np.array([0.0, 0.0, 1.0])
    v = np.cross(z, a)
    s, c = np.linalg.norm(v), float(z @ a)
    if s < 1e-9:
        return np.identity(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.identity(3) + vx + vx @ vx * ((1 - c) / (s * s))


def _place(mesh, rot=None, offset=(0.0, 0.0, 0.0)):
    return mesh.transformed(rot, offset)


def _slerp(p0, p1, t):
    """Great-circle interpolation between unit vectors p0, p1 (..., 3) at fractions t (nu,) -> (nu, ..., 3)."""
    dot = np.clip(np.sum(p0 * p1, -1), -1.0, 1.0)
    om = np.arccos(dot)[None]
    so = np.maximum(np.sin(om), 1e-9)
    t = np.asarray(t, float).reshape((-1,) + (1,) * p0.ndim)[..., 0]
    w0 = np.sin((1 - t) * om) / so
    w1 = np.sin(t * om) / so
    return w0[..., None] * p0[None] + w1[..., None] * p1[None]


def ring_about(axis, alpha_deg, v):
    """Unit directions at angle alpha from `axis`, azimuth v measured like the front rings (x, then y)."""
    D = _unit(*axis)
    e1 = np.array([1.0, 0.0, 0.0]) - D * D[0]
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(e1, D)
    if e2[1] < 0:
        e2 = -e2
    a = np.radians(np.broadcast_to(np.asarray(alpha_deg, float), v.shape))
    return (np.cos(a)[:, None] * D[None] + np.sin(a)[:, None] * (np.cos(v)[:, None] * e1 + np.sin(v)[:, None] * e2))


def ring_front(theta_deg, v):
    t = np.radians(np.broadcast_to(np.asarray(theta_deg, float), v.shape))
    return np.stack([np.sin(t) * np.cos(v), np.sin(t) * np.sin(v), np.cos(t)], -1)


def shell(back_in, back_out, front_in, front_out, rho_in, rho_out, nu, u_power=1.0):
    """Closed coat of the globe between a back rim and a front rim (arrays of unit directions, (nv, 3) each).
    Directions run along great circles from rim to rim; rho_in / rho_out give the radius for any directions."""
    nv = len(back_in)
    t = np.linspace(0.0, 1.0, nu) ** u_power
    d_out = _slerp(back_out, front_out, t)
    d_in = _slerp(back_in, front_in, t)
    s_out = d_out * rho_out(d_out)[..., None]
    s_in = d_in * rho_in(d_in)[..., None]
    pos = np.concatenate([s_out.reshape(-1, 3), s_in.reshape(-1, 3)])
    n = nu * nv
    tri = [_grid(nu, nv), _grid(nu, nv, off=n)[:, ::-1]]
    j = np.arange(nv)
    j1 = (j + 1) % nv
    o0, i0 = j, n + j
    o1, i1 = j1, n + j1
    tri.append(np.stack([o0, o1, i1], 1))
    tri.append(np.stack([o0, i1, i0], 1))
    last = (nu - 1) * nv
    o0, o1, i0, i1 = last + j, last + j1, n + last + j, n + last + j1
    tri.append(np.stack([o1, o0, i0], 1))
    tri.append(np.stack([o1, i0, i1], 1))
    return _closed(pos, np.concatenate(tri))


def _triangulate(poly):
    """Ear clipping of a simple polygon; triangles keep the polygon's own winding."""
    pts = np.asarray(poly, float)
    n = len(pts)
    area = 0.5 * np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1])
    sgn = 1.0 if area > 0 else -1.0
    idx = list(range(n))
    out = []

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    guard = 0
    while len(idx) > 3 and guard < 20 * n:
        guard += 1
        m = len(idx)
        for k in range(m):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % m]
            a, b, c = pts[i0], pts[i1], pts[i2]
            if cross(a, b, c) * sgn <= 1e-12:
                continue
            ok = True
            for j in idx:
                if j in (i0, i1, i2):
                    continue
                p = pts[j]
                if (cross(a, b, p) * sgn >= 0 and cross(b, c, p) * sgn >= 0 and cross(c, a, p) * sgn >= 0):
                    ok = False
                    break
            if ok:
                out.append((i0, i1, i2))
                idx.pop(k)
                break
        else:
            break
    if len(idx) == 3:
        out.append(tuple(idx))
    elif len(idx) > 3:            # degenerate leftovers: fan them
        for k in range(1, len(idx) - 1):
            out.append((idx[0], idx[k], idx[k + 1]))
    return np.array(out, np.int64)


def sweep(rings):
    """Closed solid from a stack of closed cross-section rings (K, N, 3) with polygonal end caps."""
    rings = np.asarray(rings, float)
    K, N, _ = rings.shape
    pos = rings.reshape(-1, 3)
    tri = [_grid(K, N)]
    for k, flip in ((0, False), (K - 1, True)):
        ring = rings[k]
        c = ring.mean(0)
        # project the end ring onto its best-fit plane for triangulation
        u, s, vt = np.linalg.svd(ring - c)
        p2 = (ring - c) @ vt[:2].T
        t = _triangulate(p2) + k * N
        tri.append(t[:, ::-1] if flip else t)
    return _fix_caps(pos, tri)


def _fix_caps(pos, tri):
    """Flip any cap whose edges run the same way as the side wall's (a closed surface uses each edge both ways)."""
    side = tri[0]
    e_side = np.concatenate([side[:, [0, 1]], side[:, [1, 2]], side[:, [2, 0]]])
    key = set(map(tuple, e_side.tolist()))
    out = [side]
    for cap in tri[1:]:
        e_cap = np.concatenate([cap[:, [0, 1]], cap[:, [1, 2]], cap[:, [2, 0]]])
        same = sum(1 for e in map(tuple, e_cap.tolist()) if e in key)
        out.append(cap[:, ::-1] if same > 0 else cap)
    return _closed(pos, np.concatenate(out))


def ribbon(path, nvec, hw, ht, seg=22, power=3.0, caps=True):
    """Sweep a rounded-rectangle section (half-width hw along the side, half-thickness ht along nvec)."""
    path = np.asarray(path, float)
    K = len(path)
    t = np.gradient(path, axis=0)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-9)
    nvec = np.asarray(nvec, float)
    side = np.cross(t, nvec)
    side /= np.maximum(np.linalg.norm(side, axis=1, keepdims=True), 1e-9)
    nv = np.cross(side, t)
    a = np.linspace(0, 2 * math.pi, seg, endpoint=False)
    ca, sa = np.cos(a), np.sin(a)
    cx = np.sign(ca) * np.abs(ca) ** (2.0 / power)
    cy = np.sign(sa) * np.abs(sa) ** (2.0 / power)
    hw = np.broadcast_to(np.asarray(hw, float), (K,))
    ht = np.broadcast_to(np.asarray(ht, float), (K,))
    ring = (path[:, None] + side[:, None] * (hw[:, None, None] * cx[None, :, None])
            + nv[:, None] * (ht[:, None, None] * cy[None, :, None]))
    pos = ring.reshape(-1, 3)
    tri = [_grid(K, seg)]
    if caps:
        n0 = len(pos)
        pos = np.vstack([pos, path[0], path[-1]])
        j = np.arange(seg)
        j1 = (j + 1) % seg
        tri.append(np.stack([np.full(seg, n0), j1, j], 1))
        last = (K - 1) * seg
        tri.append(np.stack([np.full(seg, n0 + 1), last + j, last + j1], 1))
    return _fix_caps(pos, tri) if caps else Mesh().add(pos, np.concatenate(tri))


def ctube(path, radius, segments=12):
    """Capped tube as one closed, outward-facing surface (the cut-away caps rely on consistent winding)."""
    pos, _, idx = tube(np.asarray(path, float), radius, segments, caps=True).arrays()
    return _closed(pos, idx)


def tubes(paths, radii, segments=8):
    return merged([ctube(p, r, segments) for p, r in zip(paths, radii)])


def merged(meshes):
    m = Mesh()
    for x in meshes:
        m.extend(x)
    return m


def torus_mesh(center, axis, R, r, n=48, m=14):
    a = np.linspace(0, 2 * math.pi, m, endpoint=False)
    prof = np.stack([R + r * np.cos(a), r * np.sin(a)], -1)
    return _place(lathe(prof, n), _rot_z_to(axis), center)


# ================================================================================================ globe geometry
def _theta(d):
    return np.degrees(np.arccos(np.clip(d[..., 2], -1.0, 1.0)))


def sclera_thickness(th):
    return np.interp(th, [TH_SPUR, 42, 46, 55, 90, 130, 180], [1.40, 1.0, 0.75, 0.6, 0.55, 0.8, 1.0])


def rho_sclera_in(d):
    return R_S - sclera_thickness(_theta(d))


def choroid_thickness(th):
    return np.interp(th, [TH_ORA, 90, 150, 180], [0.22, 0.28, 0.36, 0.38])


def rho_choroid_in(d):
    return rho_sclera_in(d) - choroid_thickness(_theta(d))


RPE_T = 0.08


def rho_rpe_in(d):
    return rho_choroid_in(d) - RPE_T


def _ang_mm(d, axis, radius=10.2):
    return np.arccos(np.clip(np.tensordot(d, axis, axes=([-1], [0])), -1.0, 1.0)) * radius


def retina_thickness(d):
    th = _theta(d)
    base = np.interp(th, [TH_ORA, 80, 120, 180], [0.10, 0.16, 0.21, 0.23])
    f = _ang_mm(d, F_FOV)
    macula = 0.11 * np.exp(-((f - 1.25) / 0.85) ** 2)       # thick rim of the macula
    pit = 0.20 * np.exp(-(f / 0.62) ** 2)                    # the foveal pit: inner layers displaced
    g = _ang_mm(d, D_DISC)
    nfl = 0.12 * np.exp(-np.maximum(g - 0.95, 0.0) / 0.9)     # nerve-fibre layer piling up at the disc margin
    return np.maximum(base + macula - pit + nfl, 0.06)


def rho_retina_in(d):
    return rho_rpe_in(d) - retina_thickness(d)


def globe_radius(d):
    """Distance from the centre to the outer surface of the globe (sclera or cornea) along directions d."""
    dz = d[..., 2]
    b = dz * CF_C
    t = b + np.sqrt(np.maximum(b * b - CF_C * CF_C + CF_R * CF_R, 0.0))
    return np.maximum(R_S, np.where(dz > 0.5, t, 0.0))


def cornea_front(r):
    return CF_C + np.sqrt(np.maximum(CF_R ** 2 - np.asarray(r) ** 2, 0.0))


def cornea_back(r):
    return CB_C + np.sqrt(np.maximum(CB_R ** 2 - np.asarray(r) ** 2, 0.0))


def lens_z(r, front=True):
    r = np.asarray(r, float)
    s = np.sqrt(np.maximum(1.0 - (r / LENS_A) ** 2, 0.0))
    return LENS_Z + (LENS_B1 * s if front else -LENS_B2 * s)


def lens_profile(grow=0.0, n=90):
    """Meridional outline of the lens from the anterior pole round the equator to the posterior pole."""
    t = np.linspace(0.0, math.pi, n)
    a = LENS_A + grow
    r = a * np.sin(t)
    # front and back halves are ellipses of different depth; the equator is slightly rounded by the power
    c = np.cos(t)
    z = LENS_Z + np.where(c > 0, (LENS_B1 + grow) * np.abs(c) ** 0.95, -(LENS_B2 + grow) * np.abs(c) ** 0.95)
    return np.stack([r, z], -1)


def polar(theta_deg, rho):
    t = np.radians(theta_deg)
    return np.stack([rho * np.sin(t), rho * np.cos(t)], -1)


def iris_back(r):
    r = np.asarray(r, float)
    u = (r - PUPIL_R) / (IRIS_ROOT - PUPIL_R)
    z0 = lens_z(PUPIL_R) + 0.03
    return z0 + (7.45 - z0) * u + 0.16 * np.sin(math.pi * np.clip(u, 0, 1))


def iris_thickness(r):
    return np.interp(r, [PUPIL_R, 2.2, 3.3, 4.5, IRIS_ROOT], [0.34, 0.46, 0.62, 0.45, 0.30])


def rho_retina_in_base(th):
    """Inner surface of the retina without the fovea and disc: the rotationally symmetric wall of the vitreous."""
    sclera = R_S - sclera_thickness(th)
    return (sclera - choroid_thickness(th) - RPE_T
            - np.interp(th, [TH_ORA, 80, 120, 180], [0.10, 0.16, 0.21, 0.23]))


def _fundus_dir(a, b):
    """Direction to a fundus point a mm nasal and b mm superior of the disc centre (measured on the retina)."""
    e_h = np.array([1.0, 0.0, 0.0]) - D_DISC * D_DISC[0]
    e_h /= np.linalg.norm(e_h)
    e_v = np.cross(e_h, D_DISC)
    if e_v[1] < 0:
        e_v = -e_v
    a, b = np.asarray(a, float), np.asarray(b, float)
    q = np.sqrt(a * a + b * b)
    ang = q / 10.0
    w = np.where(q > 1e-9, np.sin(ang) / np.maximum(q, 1e-9), 0.1)
    d = (np.cos(ang)[..., None] * D_DISC + (a * w)[..., None] * e_h + (b * w)[..., None] * e_v)
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


# ================================================================================================ globe parts
def _ciliary_outline():
    """Meridional outline of the ciliary body: along the sclera from the spur to the ora serrata, back along the
    pars plana and the base of the processes (pars plicata), round the iris root to the angle recess."""
    th_o = np.linspace(TH_SPUR + 0.4, TH_ORA, 22)
    outer = polar(th_o, R_S - sclera_thickness(th_o))
    th_i = np.linspace(TH_ORA, 52.0, 10)
    inner = polar(th_i, R_S - sclera_thickness(th_i) - np.interp(th_i, [52, 55, 60, 68], [0.56, 0.47, 0.44, 0.40]))
    plicata = np.array([[7.62, 6.42], [7.05, 6.72], [6.62, 7.02], [6.36, 7.26]])
    front = np.array([[6.16, 7.42], [6.07, 7.56], [6.06, 7.70], [6.14, 7.84]])
    return np.vstack([outer, inner, plicata, front])


PLICATA = (np.array([7.75, 6.36]), np.array([6.40, 7.22]))      # base line of the ciliary processes (r, z)


def _processes(n=72, seed=3):
    """Ciliary processes: ~70 meridional ridges standing on the pars plicata, pointing at the lens equator."""
    rng = np.random.default_rng(seed)
    b0, b1 = PLICATA
    along = (b0 - b1) / np.linalg.norm(b0 - b1)          # meridional, backwards
    inward = np.array([-along[1], along[0]])
    if inward[0] > 0:
        inward = -inward
    m = Mesh()
    for i in range(n):
        phi = 2 * math.pi * (i + rng.uniform(-0.15, 0.15)) / n
        big = i % 2 == 0                                   # major and minor processes alternate
        c2 = (b0 + b1) / 2 + along * rng.uniform(-0.15, 0.25) + inward * (0.42 if big else 0.28)
        length = rng.uniform(0.95, 1.15) if big else rng.uniform(0.6, 0.8)
        height = rng.uniform(0.5, 0.62) if big else rng.uniform(0.3, 0.4)
        width = rng.uniform(0.12, 0.16)
        er = np.array([math.cos(phi), math.sin(phi), 0.0])
        ez = np.array([0.0, 0.0, 1.0])
        centre = er * c2[0] + ez * c2[1]
        ax_len = er * along[0] + ez * along[1]
        ax_h = er * inward[0] + ez * inward[1]
        ax_w = np.array([-math.sin(phi), math.cos(phi), 0.0])
        rot = np.stack([ax_len, ax_h, ax_w], 1)            # local x = length, y = height, z = width
        m.extend(ellipsoid_mesh(centre, (length, height, width), res=10, rotation=rot))
    return m


def _zonules(n=72, seed=5):
    rng = np.random.default_rng(seed)
    paths, radii = [], []
    b0, b1 = PLICATA
    for i in range(n):
        phi = 2 * math.pi * (i + 0.5) / n + rng.uniform(-0.02, 0.02)
        er = np.array([math.cos(phi), math.sin(phi), 0.0])
        ez = np.array([0.0, 0.0, 1.0])

        def p3(rz):
            return er * rz[0] + ez * rz[1]
        # anterior fibres from the pars plana forward, posterior fibres from the valleys of the processes backward
        th = rng.uniform(53, 58)
        src_pp = polar(th, R_S - sclera_thickness(th) - 0.5)
        src_val = b0 * 0.55 + b1 * 0.45 + np.array([-0.18, -0.12])
        lr = LENS_A - 0.35
        dst_front = np.array([lr, lens_z(lr) + 0.08])
        dst_back = np.array([lr + 0.05, lens_z(lr + 0.05, front=False) - 0.08])
        dst_eq = np.array([LENS_A + 0.06, LENS_Z])
        for src, dst in ((src_pp, dst_front), (src_val, dst_back), ((src_pp + src_val) / 2, dst_eq)):
            p = np.linspace(p3(src), p3(dst), 9)
            paths.append(p)
            radii.append(0.022)
    return tubes(paths, radii, 5)


def _iris_relief(R, Z, P, front):
    r = R
    ridges = 0.05 * np.abs(np.sin(34 * P + 1.8 * np.sin(5 * P) + 0.9 * r)) ** 0.6
    collarette = 0.09 * np.exp(-((r - 3.25 - 0.12 * np.sin(9 * P)) / 0.22) ** 2)
    crypts = -0.16 * np.maximum(np.sin(17 * P + 1.3 * r + np.sin(3 * P)), 0) ** 10 * np.exp(-((r - 3.9) / 0.55) ** 2)
    crypts2 = -0.12 * np.maximum(np.sin(23 * P - 0.7 * r), 0) ** 12 * np.exp(-((r - 2.6) / 0.3) ** 2)
    furrow = -0.05 * np.exp(-((r - 4.95 - 0.08 * np.sin(7 * P)) / 0.07) ** 2)
    ramp = np.clip((r - PUPIL_R) / 0.25, 0, 1) * np.clip((IRIS_ROOT - r) / 0.3, 0, 1)
    return Z + front * ramp * (ridges + collarette + crypts + crypts2 + furrow), R


def _iris():
    rb = np.linspace(PUPIL_R, IRIS_ROOT, 70)
    back = np.stack([rb, iris_back(rb) + 0.03], -1)
    rf = rb[::-1]
    front = np.stack([rf, iris_back(rf) + iris_thickness(rf)], -1)
    prof = np.vstack([back, front])
    flag = np.concatenate([np.zeros(len(back)), np.ones(len(front))])
    flag[len(back)] = 0.0
    flag[-1] = 0.0

    def disp(R, Z, P):
        z, r = _iris_relief(R, Z, P, flag[None, :])
        return r, z
    return lathe(prof, 300, disp)


def _band(r0, r1, z_lo, z_hi, n=20):
    r = np.linspace(r0, r1, n)
    return np.vstack([np.stack([r, z_lo(r)], -1), np.stack([r[::-1], z_hi(r[::-1])], -1)])


def build_globe():
    """The eyeball: (name, group, colour, mesh, key, category, alpha, rank) records in millimetres."""
    out = []
    v_hi = np.linspace(0, 2 * math.pi, 300, endpoint=False)
    v_mid = np.linspace(0, 2 * math.pi, 200, endpoint=False)

    def add(name, group, color, mesh, key, cat="organ", alpha=1.0, rank=0.0):
        out.append((name, group, color, mesh, key, cat, alpha, rank))

    # ---- fibrous tunic
    sclera = shell(ring_about(D_DISC, 5.1, v_hi), ring_about(D_DISC, 7.4, v_hi), ring_front(TH_SPUR, v_hi),
                   ring_front(35.0, v_hi), rho_sclera_in, lambda d: np.full(d.shape[:-1], R_S), 120)
    add("Sclera", "Fibrous tunic", "#efebe0", sclera, "sclera", "fascia", rank=-1)

    r1 = np.linspace(0.0, 5.3, 60)
    cornea_prof = np.vstack([np.stack([r1, cornea_front(r1)], -1),
                             np.stack([r1[::-1] * (5.0 / 5.3), cornea_back(r1[::-1] * (5.0 / 5.3))], -1)])
    add("Cornea", "Fibrous tunic", "#cfe6f2", lathe(cornea_prof, 240), "cornea", "eye", alpha=0.42, rank=1)

    W = np.array([5.6, float(cornea_back(5.6))])
    S = np.array(SPUR)
    rl = np.linspace(5.3, LIMBUS_R, 8)
    th_l = np.linspace(TH_LIMBUS, 35.0, 8)
    rb = np.linspace(5.6, 5.0, 6)
    limbus_prof = np.vstack([np.stack([rl, cornea_front(rl)], -1), polar(th_l, np.full(8, R_S))[1:],
                             S[None], W[None], np.stack([rb, cornea_back(rb)], -1)[1:]])
    add("Limbus (corneoscleral junction)", "Fibrous tunic", "#c9d4d8", lathe(limbus_prof, 300), "limbus",
        "fascia", alpha=0.9)

    tdir = (W - S) / np.linalg.norm(W - S)
    nrm = np.array([tdir[1], -tdir[0]])
    if nrm[0] < 0:
        nrm = -nrm
    tm_prof = np.array([S + nrm * 0.02, W + nrm * 0.02, W + nrm * 0.16, S + nrm * 0.16])
    add("Trabecular meshwork", "Fibrous tunic", "#d9b677", lathe(tm_prof, 300), "trabecular", "gland", rank=1)
    c = (S + W) / 2 + nrm * 0.30
    a = np.linspace(0, 2 * math.pi, 18, endpoint=False)
    sc_prof = c + np.outer(np.cos(a) * 0.27, tdir) + np.outer(np.sin(a) * 0.10, nrm)
    add("Scleral venous sinus (canal of Schlemm)", "Fibrous tunic", "#5f7fcf", lathe(sc_prof, 300), "schlemm",
        "vein", rank=1)

    # ---- vascular tunic (uvea)
    choroid = shell(ring_about(D_DISC, 5.2, v_mid), ring_about(D_DISC, 5.2, v_mid), ring_front(TH_ORA, v_mid),
                    ring_front(TH_ORA, v_mid), rho_choroid_in, rho_sclera_in, 84)
    add("Choroid", "Vascular tunic (uvea)", "#5e2227", choroid, "choroid", "artery")

    add("Ciliary body (ciliary ring)", "Vascular tunic (uvea)", "#4a2520",
        lathe(_ciliary_outline(), 240), "ciliary_body", "organ")
    th_m = np.linspace(TH_SPUR + 0.6, 52.0, 12)
    mus_outer = polar(th_m, R_S - sclera_thickness(th_m) - 0.04)
    mus_prof = np.vstack([mus_outer, [[7.55, 6.62], [6.95, 6.98], [6.52, 7.3], [6.28, 7.62]]])
    add("Ciliary muscle", "Vascular tunic (uvea)", "#b9574c", lathe(mus_prof, 240), "ciliary_muscle", "muscle",
        rank=1)
    add("Ciliary processes", "Vascular tunic (uvea)", "#5a2a24", _processes(), "ciliary_processes", "organ")

    add("Iris", "Vascular tunic (uvea)", "#6e4424", _iris(), "iris", "organ", rank=1)
    add("Sphincter pupillae", "Vascular tunic (uvea)", "#c0574a",
        lathe(_band(PUPIL_R + 0.1, 2.75, lambda r: iris_back(r) + 0.07, lambda r: iris_back(r) + 0.24), 220),
        "sphincter", "muscle", rank=2)

    def dil_disp(R, Z, P):
        top = Z > iris_back(R) + 0.06
        return R, Z + top * 0.02 * np.cos(90 * P)
    add("Dilator pupillae", "Vascular tunic (uvea)", "#d07a66",
        lathe(_band(2.95, IRIS_ROOT - 0.2, lambda r: iris_back(r) + 0.045, lambda r: iris_back(r) + 0.1), 270,
              dil_disp), "dilator", "muscle", rank=2)
    pe = _band(PUPIL_R - 0.03, IRIS_ROOT, lambda r: iris_back(r) - 0.005, lambda r: iris_back(r) + 0.045, 40)
    add("Iris pigment epithelium", "Vascular tunic (uvea)", "#231510", lathe(pe, 200), "iris_pe", "mucosa")
    zp = float(iris_back(PUPIL_R)) + 0.2
    pupil_prof = [[0.0, zp - 0.015], [PUPIL_R - 0.02, zp - 0.015], [PUPIL_R - 0.02, zp + 0.015], [0.0, zp + 0.015]]
    add("Pupil", "Vascular tunic (uvea)", "#030304", lathe(pupil_prof, 120), "pupil", "eye", alpha=0.86, rank=3)

    # ---- nervous tunic
    add("Pigmented layer of retina", "Nervous tunic (retina)", "#2c1b15",
        shell(ring_about(D_DISC, 5.25, v_mid), ring_about(D_DISC, 5.25, v_mid), ring_front(TH_ORA, v_mid),
              ring_front(TH_ORA, v_mid), rho_rpe_in, rho_choroid_in, 84), "rpe", "mucosa")
    v_r = np.linspace(0, 2 * math.pi, 300, endpoint=False)
    add("Neural layer of retina", "Nervous tunic (retina)", "#e29a86",
        shell(ring_about(D_DISC, 5.3, v_r), ring_about(D_DISC, 5.3, v_r), ring_front(TH_ORA + 0.8, v_r),
              ring_front(TH_ORA + 0.8, v_r), rho_retina_in, rho_rpe_in, 180), "retina", "nerve")
    v_o = np.linspace(0, 2 * math.pi, 624, endpoint=False)
    teeth = TH_ORA + 0.3 - 2.6 * np.maximum(np.cos(26 * v_o + 0.7 * np.sin(3 * v_o)), 0) ** 2
    add("Ora serrata", "Nervous tunic (retina)", "#c98a5a",
        shell(ring_front(TH_ORA + 1.4, v_o), ring_front(TH_ORA + 1.4, v_o), ring_front(teeth, v_o),
              ring_front(teeth, v_o), lambda d: rho_retina_in(d) - 0.01, lambda d: rho_rpe_in(d) + 0.005, 8),
        "ora", "nerve", rank=1)
    v_p = np.linspace(0, 2 * math.pi, 120, endpoint=False)
    add("Macula lutea", "Nervous tunic (retina)", "#c9a352",
        shell(ring_about(F_FOV, 0.2, v_p), ring_about(F_FOV, 0.2, v_p), ring_about(F_FOV, 15.5, v_p),
              ring_about(F_FOV, 15.5, v_p), lambda d: rho_retina_in(d) - 0.03, lambda d: rho_retina_in(d) + 0.01, 40),
        "macula", "nerve", rank=1)
    add("Fovea centralis", "Nervous tunic (retina)", "#8a3526",
        shell(ring_about(F_FOV, 0.1, v_p), ring_about(F_FOV, 0.1, v_p), ring_about(F_FOV, 4.0, v_p),
              ring_about(F_FOV, 4.0, v_p), lambda d: rho_retina_in(d) - 0.045, lambda d: rho_retina_in(d) + 0.008,
              16), "fovea", "nerve", rank=2)
    rim_d = ring_about(D_DISC, 5.3, v_p[:1])
    rim_in = float(rho_retina_in(rim_d)[0])
    disc_prof = [[0.0, rim_in + 0.42], [0.3, rim_in + 0.36], [0.55, rim_in + 0.16], [0.8, rim_in + 0.02],
                 [0.93, rim_in - 0.01], [0.955, rim_in + 0.15], [0.955, 10.95], [0.0, 10.95]]
    add("Optic disc (blind spot)", "Nervous tunic (retina)", "#f0d3a2",
        _place(lathe(disc_prof, 120), _rot_z_to(D_DISC)), "disc", "nerve", rank=2)

    # ---- lens and zonule
    add("Lens", "Lens & zonule", "#e6dfbd", lathe(lens_profile(0.0), 180), "lens", "eye", rank=2)
    add("Lens capsule", "Lens & zonule", "#f4f1e2", lathe(lens_profile(0.07), 180), "capsule", "eye", rank=2)
    add("Zonular fibres (suspensory ligament)", "Lens & zonule", "#e9e3cf", _zonules(), "zonules", "tendon", rank=2)

    # ---- chambers and humours
    ri = np.linspace(IRIS_ROOT - 0.05, PUPIL_R, 40)
    rc = np.linspace(0.0, 5.6, 40)
    ac = np.vstack([np.stack([rc, cornea_back(rc) - 0.01], -1), [[5.95, 8.4], [6.08, 7.84]],
                    np.stack([ri, iris_back(ri) + iris_thickness(ri) - 0.03], -1),
                    np.stack([np.linspace(PUPIL_R - 0.02, 0.0, 14), lens_z(np.linspace(PUPIL_R - 0.02, 0.0, 14))
                              + 0.075], -1)])
    add("Anterior chamber (aqueous humor)", "Anterior segment (aqueous humor)", "#8fd0ea", lathe(ac[::-1], 160),
        "anterior_chamber", "csf", alpha=0.16, rank=3)
    rp = np.linspace(PUPIL_R, IRIS_ROOT - 0.05, 36)
    rl_ = np.linspace(LENS_A - 0.05, PUPIL_R, 30)
    pc = np.vstack([np.stack([rp, iris_back(rp) + 0.0], -1), [[6.3, 7.35], [6.05, 6.95], [5.35, 6.55],
                                                              [LENS_A + 0.05, 6.8]],
                    np.stack([rl_, lens_z(rl_) + 0.075], -1)])
    add("Posterior chamber (aqueous humor)", "Anterior segment (aqueous humor)", "#7cc6e4", lathe(pc, 160),
        "posterior_chamber", "csf", alpha=0.2, rank=3)
    lp = lens_profile(0.08)
    back = lp[lp[:, 1] < LENS_Z - 0.2]
    th_v = np.linspace(52.0, 180.0, 90)
    wall = polar(th_v, rho_retina_in_base(th_v) - 0.03)
    wall[th_v < TH_ORA, :] = polar(th_v[th_v < TH_ORA], R_S - sclera_thickness(th_v[th_v < TH_ORA]) - 0.6)
    vit = np.vstack([[[0.0, float(lens_z(0.0, False)) - 0.08]], back[::-1], [[5.3, 6.25], [7.3, 5.95]], wall])
    add("Vitreous humor (vitreous body)", "Posterior segment (vitreous chamber)", "#cde6ec", lathe(vit, 160),
        "vitreous", "csf", alpha=0.11, rank=3)
    return out


# ================================================================================================ assembly
DETAIL = {"Sclera": (0.07, 40.0, 0.10, 0), "Neural layer of retina": (0.05, 0.0, 0.0, 0),
          "Pigmented layer of retina": (0.05, 0.0, 0.0, 0), "Choroid": (0.12, 60.0, 0.2, 0),
          "Iris": (0.22, 90.0, 0.2, 0), "Optic nerve (CN II)": (0.06, 70.0, 0.3, 3)}


def _scaled(mesh):
    out = Mesh()
    for p, n, i in mesh.parts:
        out.parts.append(((p * MM).astype(np.float32), n, i))
    return out


def build_eyeball():
    records = build_globe() + build_nerve() + build_muscles() + build_lids() + build_levator() + build_lacrimal()
    parts = []
    for name, group, color, mesh, key, cat, alpha, rank in records:
        parts.append(Part(name, group, color, _scaled(mesh), DESC[key], alpha=alpha, category=cat,
                          rank=rank, clip=True, detail=DETAIL.get(name)))
    return parts


DESC = {
    # ---- fibrous tunic
    "sclera": "Sclera: the white, opaque posterior five-sixths of the fibrous (outer) tunic - dense irregular "
              "connective tissue of interwoven type I collagen, about 1 mm thick at the back, 0.6 mm at the equator "
              "and thinnest (0.3 mm) just behind the rectus insertions. It protects the eye, gives the extrinsic "
              "muscles their insertions and, with the intraocular pressure (normally 10-21 mmHg), holds the globe "
              "in shape. Behind, its inner layers form the sieve-like lamina cribrosa that the optic nerve fibres "
              "pass through, and its outer layers continue as the dural sheath of the nerve. It is covered by the "
              "bulbar conjunctiva; dilated anterior vessels between them are the 'bloodshot' eye. A bluish sclera "
              "(thin, so the choroid shows through) suggests osteogenesis imperfecta; yellow 'sclera' in jaundice is "
              "really bilirubin in the conjunctiva.",
    "cornea": "Cornea: the transparent, avascular anterior sixth of the fibrous tunic, ~11.5 mm across and 0.55 mm "
              "thick centrally. Five layers: non-keratinised stratified squamous epithelium (outer epithelium, "
              "regenerates in days), Bowman layer, the stroma of ~200 orthogonal collagen lamellae whose regular "
              "spacing makes it clear, Descemet membrane, and a single-layer endothelium (inner epithelium) that "
              "pumps water out - it cannot divide, and when it fails the cornea swells and clouds. The air-tear "
              "interface makes the cornea the main refracting surface (~43 of the eye's ~60 dioptres; the lens adds "
              "the adjustable rest). Uneven curvature is astigmatism (lines in one orientation blur); it is reshaped "
              "in LASIK and PRK. Densely innervated by CN V1 (the corneal blink reflex); nourished by aqueous humor "
              "and tears. Its lack of vessels makes corneal grafts the most successful transplants.",
    "limbus": "Limbus (corneoscleral junction): the 1-2 mm grey-blue ring where the clear cornea meets the white "
              "sclera and the conjunctiva inserts. Its palisades of Vogt hold the corneal epithelial stem cells "
              "(chemical burns that destroy them let conjunctiva grow over the cornea). Inside it lie the drainage "
              "angle, trabecular meshwork and scleral venous sinus. It is the surgeon's landmark: the rectus "
              "insertions are measured from it, and cataract and glaucoma incisions are made here. A white ring at "
              "the limbus (arcus) in a young adult suggests hyperlipidaemia.",
    "trabecular": "Trabecular meshwork: a sponge of collagen beams lined by endothelium-like cells spanning the "
                  "inner limbus from Schwalbe line (end of Descemet membrane) to the scleral spur, facing the "
                  "anterior chamber angle. Aqueous humor filters through it into the canal of Schlemm - the "
                  "conventional outflow (~85%). Increased resistance here, without a closed angle, is primary "
                  "open-angle glaucoma; laser trabeculoplasty and trabecular bypass stents treat it.",
    "schlemm": "Scleral venous sinus (canal of Schlemm): a circular, endothelium-lined channel running all round "
               "the limbus just outside the trabecular meshwork. Aqueous crosses its inner wall (through giant "
               "vacuoles and pores) and leaves by ~30 collector channels and aqueous veins to the episcleral "
               "veins. Production and drainage balance to keep intraocular pressure ~15 mmHg: if drainage fails, "
               "pressure rises and damages the optic nerve (glaucoma). Congenital glaucoma is maldevelopment of "
               "the angle; blood can reflux into the canal when episcleral venous pressure rises.",
    # ---- vascular tunic
    "choroid": "Choroid: the posterior part of the vascular tunic (uvea), a thin, dark brown, highly vascular layer "
               "between the sclera and the retina. Large outer vessels (Haller and Sattler layers) feed the "
               "choriocapillaris, which nourishes the outer retina - the pigmented layer and the photoreceptors - "
               "through Bruch membrane. Its melanocytes absorb stray light, preventing scatter and reflection "
               "inside the eye. In many mammals (the sheep and cow eyes dissected in the lab) part of the choroid is "
               "an iridescent reflecting layer, the tapetum lucidum, that bounces light back through the "
               "photoreceptors for night vision and makes their eyes shine in headlights; humans have no tapetum. "
               "Choroidal melanoma is the commonest primary intraocular tumour of adults; new vessels growing from "
               "the choroid through Bruch membrane cause wet macular degeneration.",
    "ciliary_body": "Ciliary body: the thickened ring of the vascular tunic between the iris root and the ora "
                    "serrata, triangular in section. It is the ciliary muscle plus the ciliary processes (pars "
                    "plicata, in front) and the flat ciliary ring (pars plana, behind), lined by a two-layer "
                    "epithelium - pigmented outside, non-pigmented facing the vitreous - that continues the two "
                    "layers of the retina forward. The pars plana is avascular and the safe route for injections "
                    "and vitrectomy instruments (3.5-4 mm behind the limbus). Its inflammation is intermediate "
                    "uveitis; its root is the site of the drainage angle.",
    "ciliary_muscle": "Ciliary muscle: smooth muscle in the outer ciliary body, its longitudinal fibres anchored to "
                      "the scleral spur, with radial and circular fibres inside. Parasympathetic fibres (CN III via "
                      "the ciliary ganglion, muscarinic M3) make it contract for near vision: the ring narrows, the "
                      "zonular fibres slacken and the elastic lens rounds up and refracts more (accommodation). "
                      "Relaxed, the zonules are taut and the lens flat for distance. Its pull on the scleral spur "
                      "also opens the trabecular meshwork (pilocarpine lowers eye pressure this way). Atropine and "
                      "cyclopentolate paralyse it (cycloplegia) for refraction in children. With age the lens stiffens "
                      "and accommodation fails - presbyopia, noticeable at 40-50 y (near point ~10 cm at 10 y, "
                      "~80-100 cm at 65 y).",
    "ciliary_processes": "Ciliary processes: 70-80 radial folds of the pars plicata, each with a core of "
                         "fenestrated capillaries covered by the two-layer ciliary epithelium. The non-pigmented "
                         "cells secrete aqueous humor (~2-3 µL/min) into the posterior chamber - carbonic anhydrase "
                         "and Na+/K+-ATPase drive it, and tight junctions between these cells form the "
                         "blood-aqueous barrier. Zonular fibres arise from the valleys between them. Glaucoma drugs "
                         "that cut production act here: beta-blockers (timolol), carbonic anhydrase inhibitors "
                         "(dorzolamide, oral acetazolamide) and alpha-2 agonists.",
    "iris": "Iris: the coloured, contractile diaphragm of the vascular tunic between the cornea and the lens, its "
            "root attached to the ciliary body, its free edge forming the pupil. It divides the anterior segment "
            "into the anterior and posterior chambers. The stroma is loose, vascular connective tissue with "
            "melanocytes: colour depends on how much melanin the stroma holds - little in blue and grey eyes (the "
            "blue is scattered light, and these eyes are more sensitive to UV and glare), much in brown. The "
            "front shows radial ridges, crypts, the collarette and circular contraction furrows. Its muscles, the "
            "sphincter and dilator pupillae, set pupil size. Inflammation is iritis (anterior uveitis): pain, "
            "photophobia, a small pupil and redness round the limbus. A convex iris narrows the angle "
            "(angle-closure glaucoma); iris nodules and heterochromia are clinical signs.",
    "sphincter": "Sphincter pupillae: a ring of smooth muscle ~1 mm wide in the posterior stroma at the pupillary "
                 "margin. Parasympathetic (CN III, Edinger-Westphal nucleus - ciliary ganglion - short ciliary "
                 "nerves, M3 receptors) contraction constricts the pupil (miosis) in bright light, in the light "
                 "reflex and with accommodation for near vision. A 'blown' dilated pupil after head injury means "
                 "compression of CN III, whose superficial pupillary fibres fail first. Pilocarpine and opioids "
                 "cause miosis.",
    "dilator": "Dilator pupillae: radially arranged myoepithelial cells forming a thin sheet in the anterior layer "
               "of the iris pigment epithelium, from the root to near the sphincter. Sympathetic fibres (T1 - "
               "superior cervical ganglion - along the internal carotid, alpha-1 receptors) make it pull the "
               "pupil wide (mydriasis) in dim light and with fear or excitement. Horner syndrome (loss of this "
               "pathway) gives a small pupil, ptosis and anhidrosis. Phenylephrine drops dilate the pupil for "
               "fundoscopy; dilating a narrow-angled eye can trigger angle-closure glaucoma.",
    "iris_pe": "Iris pigment epithelium: two layers of densely pigmented cells on the back of the iris, the forward "
               "continuation of the retina's two layers (through the ciliary epithelium). It makes the iris opaque "
               "so that light enters only through the pupil, and peeks round the pupillary margin as a dark ruff. "
               "Rubbing of the zonules against it releases pigment that clogs the trabecular meshwork (pigment "
               "dispersion glaucoma); transillumination defects show up in albinism.",
    "pupil": "Pupil: the round opening in the centre of the iris - an aperture, not a structure - through which "
             "light reaches the lens and retina; it looks black because light entering it is absorbed inside the "
             "eye. Normal diameter 2-4 mm in light, up to 8 mm in the dark. Its size is set by the balance of the "
             "sphincter (parasympathetic) and dilator (sympathetic) pupillae. The pupillary light reflex (direct "
             "and consensual, CN II in, CN III out) and the swinging-flashlight test (relative afferent pupillary "
             "defect in optic nerve disease) are key bedside tests. The red reflex seen through it is lost with "
             "cataract, retinoblastoma or vitreous haemorrhage.",
    # ---- nervous tunic
    "rpe": "Pigmented layer of the retina (retinal pigment epithelium): a single layer of cuboidal, melanin-laden "
           "cells on Bruch membrane, the outer layer of the retina, derived from the outer wall of the optic cup. "
           "With the choroid it absorbs stray light and prevents scatter; it phagocytoses the shed tips of "
           "photoreceptor outer segments, recycles retinal (the visual cycle), stores vitamin A and forms the outer "
           "blood-retina barrier. The neural layer is only apposed to it, not fused (the old optic ventricle): "
           "fluid entering this potential space separates them - retinal detachment. Its failure underlies "
           "age-related macular degeneration (drusen) and retinitis pigmentosa.",
    "retina": "Neural layer of the retina: the inner, light-sensitive layer of the nervous tunic, lining the back of "
              "the eye from the optic disc to the ora serrata. From outside inwards: rods and cones (photoreceptors, "
              "facing away from the light), bipolar cells, ganglion cells whose axons run over the inner surface to "
              "the optic disc; horizontal and amacrine cells integrate across. Light passes through the ganglion and "
              "bipolar layers to reach the photoreceptors; signals travel back towards the vitreous. Rods (~120 "
              "million) serve dim light and peripheral vision; cones (~6 million) serve colour and acuity and crowd "
              "the macula. The neural retina is held on only by the pressure of the vitreous and the pumping of the "
              "pigment epithelium: in retinal detachment it lifts off (flashes, floaters, a curtain over the "
              "field) and must be reattached urgently. Diabetic retinopathy damages its vessels.",
    "ora": "Ora serrata: the scalloped (dentate) front edge of the neural retina, ~7-8 mm behind the limbus, where "
           "the light-sensitive retina ends and continues as the thin non-pigmented epithelium of the ciliary "
           "body. It marks the boundary between the optic (photosensitive) and non-optic parts of the retina. "
           "The vitreous base is anchored across it, so tears and dialyses that start retinal detachments often "
           "form here; it is seen only with indentation ophthalmoscopy.",
    "macula": "Macula lutea: a yellowish oval ~5.5 mm across at the posterior pole, temporal to the optic disc, "
              "coloured by the carotenoids lutein and zeaxanthin (which filter blue light). Packed with cones and "
              "ganglion cells, it gives central, detailed and colour vision - reading, faces. Age-related macular "
              "degeneration (drusen and atrophy in the dry form, leaking choroidal new vessels in the wet form, "
              "treated with anti-VEGF injections) destroys central vision while peripheral vision survives; "
              "patients notice distorted straight lines (Amsler grid). In central retinal artery occlusion the "
              "macula stands out as a cherry-red spot against the pale, swollen retina.",
    "fovea": "Fovea centralis: the pit at the centre of the macula, ~1.5 mm wide, where the inner retinal layers "
             "are swept aside so light falls directly on the photoreceptors. Its centre (foveola) holds only "
             "cones, at the highest density in the retina, each with its own ganglion cell - the site of sharpest "
             "vision. Looking straight at an object turns the eye so its image falls on the fovea; the visual axis "
             "passes through it. It has no blood vessels (the foveal avascular zone) and lives off the choroid. "
             "Snellen acuity (20/20) tests the fovea.",
    "disc": "Optic disc (blind spot): the pale, round spot ~1.5-1.8 mm across, 3-4 mm nasal to the fovea, where "
            "ganglion cell axons turn to leave the eye as the optic nerve and the central retinal vessels enter "
            "and leave. It has no photoreceptors, so it is the blind spot (~15 degrees temporal to fixation in the "
            "visual field; we do not notice it because the other eye and the brain fill it in). The central "
            "depression is the physiological cup: an enlarging cup-to-disc ratio signals glaucomatous loss of "
            "axons; a swollen disc with blurred margins (papilloedema) signals raised intracranial pressure "
            "transmitted along the optic nerve sheath; a pale disc means optic atrophy.",
    # ---- lens
    "lens": "Lens: a transparent, avascular, biconvex body ~9-10 mm across and 4 mm thick behind the iris, the "
            "anterior surface flatter than the posterior. It is made of long, anucleate lens fibres packed with "
            "crystallin proteins, laid down throughout life around an older central nucleus, and adds ~15-20 "
            "adjustable dioptres to the cornea's fixed power. Suspended by the zonule, it changes shape in "
            "accommodation - rounder for near vision, flatter for distance. Clouding of the lens is cataract (age, "
            "diabetes, steroids, UV, trauma, congenital rubella): painless, gradual blur and glare, a lost red "
            "reflex; it is removed by phacoemulsification through the capsule and replaced with a plastic lens. "
            "Hardening of the lens with age causes presbyopia; dislocation of the lens occurs in Marfan syndrome "
            "(up and out) and homocystinuria (down and in).",
    "capsule": "Lens capsule: the thick, elastic basement membrane (type IV collagen) enclosing the lens, made by "
               "the lens epithelium beneath its anterior surface. It is the thickest basement membrane in the "
               "body; its elasticity moulds the lens into a rounder shape when the zonules relax. The zonular "
               "fibres insert into it around the equator. In cataract surgery a circular opening is torn in the "
               "anterior capsule and the posterior capsule is left to hold the implant; its later clouding "
               "(posterior capsule opacification) is cleared with a YAG laser.",
    "zonules": "Zonular fibres (suspensory ligament of the lens): hundreds of fine fibrillin-rich fibres that run "
               "from the ciliary processes and pars plana to the lens capsule in front of, at and behind the "
               "equator. Relaxed ciliary muscle keeps them taut and the lens flat (distance vision); contraction "
               "of the muscle slackens them so the lens rounds up (near vision). Defective fibrillin-1 in Marfan "
               "syndrome weakens them and the lens dislocates (ectopia lentis).",
    # ---- chambers
    "anterior_chamber": "Anterior chamber: the space between the back of the cornea and the front of the iris "
                        "(and the lens in the pupil), ~3 mm deep centrally, filled with aqueous humor. With the "
                        "posterior chamber it forms the anterior segment (anterior cavity) of the eye. Aqueous is "
                        "a clear, watery filtrate secreted by the ciliary processes (a few mL per day), which "
                        "nourishes the avascular cornea and lens and keeps the intraocular pressure; it flows from "
                        "the posterior chamber through the pupil into this chamber and drains at the angle into the "
                        "scleral venous sinus. Its peripheral recess, the iridocorneal angle, is where drainage "
                        "happens and where angle-closure glaucoma begins (sudden pain, red eye, halos, a fixed "
                        "mid-dilated pupil). Blood layering here is a hyphaema; pus is a hypopyon.",
    "posterior_chamber": "Posterior chamber: the narrow ring-shaped space behind the iris and in front of the lens "
                         "and zonule, bounded peripherally by the ciliary processes. It is part of the anterior "
                         "segment and is filled with aqueous humor freshly secreted by the ciliary processes, which "
                         "then flows through the pupil into the anterior chamber. If the pupil is blocked (the iris "
                         "stuck to the lens), aqueous builds up here, bows the iris forward and closes the angle "
                         "(pupillary-block angle closure) - relieved by a laser peripheral iridotomy.",
    "vitreous": "Vitreous humor (vitreous body): the clear gel filling the vitreous chamber - the posterior segment "
                "behind the lens, ~4 mL and two-thirds of the eye's volume. It is ~99% water held in a network of "
                "collagen fibrils and hyaluronic acid, is not replaced once formed, and presses the neural retina "
                "against the pigmented layer and maintains the shape of the eyeball. The back of the eye seen "
                "through it with an ophthalmoscope is the fundus. With age it liquefies and pulls away from the "
                "retina (posterior vitreous detachment): floaters and flashes, sometimes a retinal tear. Bleeding "
                "into it (diabetic retinopathy) blocks vision; vitrectomy removes it.",
    # ---- nerve
    "optic_nerve": "Optic nerve (CN II): ~1.2 million ganglion cell axons leaving the eye at the optic disc, "
                   "passing through the lamina cribrosa (behind which they gain myelin, so the nerve doubles in "
                   "width to ~3-4 mm) and running ~25 mm backwards and medially in a slack S-curve (allowing eye "
                   "movement) through the muscle cone and common tendinous ring to the optic canal. It is a tract of "
                   "the CNS: myelinated by oligodendrocytes, wrapped in all three meninges, unable to regenerate. "
                   "Pathway: optic nerve - optic chiasm (nasal retinal fibres cross, temporal fibres stay "
                   "ipsilateral) - optic tract - lateral geniculate nucleus - optic radiations - primary visual "
                   "cortex; some fibres go to the superior colliculi and pretectum for reflexes. Optic neuritis "
                   "(multiple sclerosis) causes painful loss of vision and a relative afferent pupillary defect; "
                   "glaucoma kills its axons.",
    "dura": "Dural sheath of the optic nerve: the outer meningeal sheath around the nerve, fused with the sclera "
            "in front and with the periosteum of the optic canal behind; inside it are the arachnoid and pia and "
            "a subarachnoid space continuous with that around the brain. Raised intracranial pressure is "
            "transmitted along this space, compressing the nerve and its central retinal vein behind the eye - "
            "the swollen optic disc of papilloedema. Optic nerve sheath fenestration relieves it.",
    "cra": "Central retinal artery: the first branch of the ophthalmic artery (from the internal carotid). It runs "
           "under the optic nerve, pierces the dural sheath and enters the nerve ~10 mm behind the eye, travels "
           "in its centre to the optic disc and divides into superior and inferior, nasal and temporal branches "
           "that spread over the inner surface of the retina (arcing around the macula) and supply its inner "
           "layers. They are end arteries: occlusion (embolus from a carotid plaque, giant cell arteritis) causes "
           "sudden painless loss of vision, a pale retina and a cherry-red spot at the fovea. Amaurosis fugax is "
           "a transient version. Seen with the ophthalmoscope, the arterioles are narrower and brighter than the "
           "veins (hypertensive nipping, diabetic changes).",
    "crv": "Central retinal vein: drains the retina, its tributaries accompanying the arteries across the fundus "
           "and converging at the optic disc; it runs back in the centre of the optic nerve beside the artery, "
           "leaves it with the artery and drains to the superior ophthalmic vein and the cavernous sinus. Where "
           "it crosses the subarachnoid space it can be compressed by raised intracranial pressure "
           "(papilloedema; loss of spontaneous venous pulsation). Central retinal vein occlusion (hypertension, "
           "glaucoma, hyperviscosity) gives a 'stormy sunset' fundus of haemorrhages.",
    # ---- extrinsic muscles
    "sr": "Superior rectus: arises from the upper part of the common tendinous ring and inserts on the sclera "
          "~7.7 mm behind the upper limbus. Because the orbit points laterally (~23 degrees) while the eye looks "
          "forward, it elevates the eye (mainly), and also adducts and intorts it; it is a pure elevator when "
          "the eye is abducted, which is how it is tested clinically. Nerve: superior division of the "
          "oculomotor nerve (CN III). Mnemonic LR6 SO4, rest 3.",
    "ir": "Inferior rectus: arises from the lower part of the common tendinous ring and inserts ~6.5 mm behind "
          "the lower limbus. It depresses the eye (mainly), and adducts and extorts it; tested looking down with "
          "the eye abducted. Nerve: inferior division of CN III. It can be trapped in an orbital floor ('blowout') "
          "fracture, limiting upgaze and causing diplopia; it is enlarged in thyroid eye disease.",
    "mr": "Medial rectus: the largest rectus, from the medial part of the common tendinous ring to ~5.5 mm "
          "behind the medial limbus. Pure adductor (turns the eye medially toward the nose); both medial recti "
          "converge the eyes for near vision. Nerve: inferior division of CN III. A lesion of the medial "
          "longitudinal fasciculus (multiple sclerosis) prevents adduction on lateral gaze - internuclear "
          "ophthalmoplegia.",
    "lr": "Lateral rectus: arises by two heads from the lateral part of the common tendinous ring and inserts "
          "~6.9 mm behind the lateral limbus. Pure abductor (turns the eye laterally). Nerve: abducens nerve "
          "(CN VI), whose long intracranial course makes it the cranial nerve most often affected by raised "
          "intracranial pressure: the eye turns in (esotropia) with horizontal double vision.",
    "so": "Superior oblique: arises from the body of the sphenoid above the common tendinous ring, runs forward "
          "along the superomedial orbit, becomes a round tendon that passes through the trochlea, then turns "
          "back and laterally under the superior rectus to insert on the posterosuperolateral globe behind the "
          "equator. Pulling the back of the eye up and forward, it depresses, abducts and intorts - it moves the "
          "eye down and out, and is the only muscle that looks down when the eye is adducted (reading, walking "
          "downstairs). Nerve: trochlear nerve (CN IV); palsy gives vertical diplopia worse on looking down, "
          "with a compensatory head tilt away from the affected side.",
    "trochlea": "Trochlea: a fibrocartilaginous pulley (~4 mm) attached to the trochlear fovea of the frontal "
                "bone just behind the superomedial orbital margin, lined by a synovial sheath. The tendon of the "
                "superior oblique slides through it and is redirected backwards and laterally, so the muscle "
                "effectively pulls from the front of the orbit. Inflammation (trochleitis) causes pain in the "
                "upper inner orbit; a tight tendon sheath causes Brown syndrome (the eye cannot look up when "
                "adducted).",
    "io": "Inferior oblique: the only extrinsic muscle not arising at the orbital apex - it arises from the "
          "orbital floor (maxilla) just lateral to the nasolacrimal canal, runs back and laterally under the "
          "inferior rectus and inserts on the posterolateral globe below the lateral rectus, near the macula. It "
          "elevates, abducts and extorts - moves the eye up and out, and is the elevator when the eye is "
          "adducted. Nerve: inferior division of CN III. Overaction of it causes a V-pattern strabismus.",
    "annulus": "Common tendinous ring (annulus of Zinn): a fibrous ring at the orbital apex around the optic canal "
               "and the middle of the superior orbital fissure, from which the four recti arise. Through it pass "
               "the optic nerve and ophthalmic artery, the oculomotor (both divisions), abducens and nasociliary "
               "nerves; the trochlear, frontal and lacrimal nerves pass outside it. The recti fanning from it "
               "form the muscle cone. Inflammation here compresses the optic nerve (orbital apex syndrome) - one "
               "reason optic neuritis hurts on eye movement.",
    "lps": "Levator palpebrae superioris: arises from the lesser wing of the sphenoid above the common tendinous "
           "ring, runs forward above the superior rectus and, behind the orbital septum, becomes a broad "
           "aponeurosis that fans into the upper eyelid - inserting on the front of the superior tarsal plate "
           "and, through the orbicularis, into the skin to form the lid crease. It elevates and retracts the "
           "upper eyelid. Nerve: superior division of CN III (a complete CN III palsy gives severe ptosis with the "
           "eye 'down and out'). Stretching or disinsertion of its aponeurosis is the common age-related ptosis; "
           "myasthenia gravis gives a fatigable ptosis. Its deep smooth-muscle slip is the superior tarsal "
           "muscle.",
    # ---- eyelids
    "upper_lid": "Upper eyelid (superior palpebra): a mobile fold that covers and protects the front of the eye, "
                 "spreads the tear film with each blink (~15 per minute) and shuts out light during sleep. Layers "
                 "from front to back: thin skin (the thinnest in the body) with fine hairs, loose areolar "
                 "connective tissue (no fat, so it swells readily - periorbital oedema), orbicularis oculi, the "
                 "tarsal plate with its tarsal glands (and above it the levator aponeurosis and superior tarsal "
                 "muscle), and palpebral conjunctiva. The margin carries the eyelashes in front and the openings "
                 "of the tarsal glands behind, separated by the grey line (a surgical plane). The lids meet at the "
                 "medial and lateral canthi; the gap between them is the palpebral fissure. Ptosis is drooping of "
                 "this lid; a stye (hordeolum) is an infected lash follicle gland.",
    "lower_lid": "Lower eyelid (inferior palpebra): smaller and less mobile than the upper lid, with the same "
                 "layers - skin, areolar tissue, orbicularis oculi, a narrow inferior tarsal plate with tarsal "
                 "glands, palpebral conjunctiva. It is lowered by the capsulopalpebral fascia from the inferior "
                 "rectus as the eye looks down. Its margin carries the lower lashes and the lower lacrimal "
                 "punctum medially. With age or facial palsy it can sag outward (ectropion: tears spill, the "
                 "exposed conjunctiva dries) or roll inward (entropion: lashes scratch the cornea).",
    "tarsus_sup": "Superior tarsal plate (tarsus): a ~10 mm high, crescent-shaped plate of dense fibrous "
                  "connective tissue that gives the upper eyelid its shape and stiffness. The tarsal glands are "
                  "embedded in it; the levator aponeurosis inserts on its front, the superior tarsal muscle on its "
                  "upper border, and the medial and lateral palpebral ligaments anchor its ends to the orbital "
                  "margins. It is everted (the lid flipped over a cotton bud) to find foreign bodies under the upper "
                  "lid.",
    "tarsus_inf": "Inferior tarsal plate (tarsus): the smaller (~4-5 mm high) plate of dense connective tissue in "
                  "the lower eyelid, holding its tarsal glands and anchored by the palpebral ligaments; the "
                  "capsulopalpebral fascia attaches to its lower border. Laxity of its ligaments lets the lid "
                  "turn out (ectropion) or in (entropion).",
    "meibomian": "Tarsal (meibomian) glands: 25-30 vertical sebaceous glands in the upper tarsal plate and ~20 in "
                 "the lower, each a straight central duct with acini budding off it, opening in a row on the lid "
                 "margin behind the lashes. Their oily meibum forms the outer lipid layer of the tear film, slowing "
                 "evaporation and stopping tears spilling over the lid margin. Blocked glands cause evaporative "
                 "dry eye and blepharitis; a blocked gland that swells into a painless, firm lump in the tarsus is "
                 "a chalazion (a lipogranuloma), whereas an acutely infected one is an internal hordeolum. A "
                 "recurrent 'chalazion' in an older person may be sebaceous carcinoma.",
    "orbicularis": "Orbicularis oculi (palpebral part): the thin, pale sheet of skeletal muscle in the eyelids in "
                   "front of the tarsal plates and orbital septum, arising from the medial palpebral ligament and "
                   "inserting into the lateral palpebral raphe. It closes the lids gently (blinking, sleep); its "
                   "orbital part, around the orbital margin, squeezes them shut. Its lacrimal part, behind the "
                   "lacrimal sac, pumps tears into the sac with each blink. Nerve: temporal and zygomatic branches "
                   "of the facial nerve (CN VII) - in Bell palsy the eye cannot close and the cornea dries.",
    "muller": "Superior tarsal muscle (Müller muscle): a thin sheet of smooth muscle from the underside of the "
              "levator palpebrae superioris to the upper border of the superior tarsal plate, lying just in front "
              "of the conjunctiva. Sympathetic tone raises the upper lid by 1-2 mm; its loss in Horner syndrome "
              "gives a mild ptosis (with miosis and anhidrosis), and its overactivity contributes to lid "
              "retraction in thyroid eye disease. Phenylephrine drops lift the lid by stimulating it.",
    "lashes": "Eyelashes (cilia): 2-3 rows of short, thick, curved hairs on the anterior edge of each lid margin - "
              "~100-150 on the upper lid, 50-75 on the lower - that curve away from the eye. Touching them "
              "triggers a blink; they keep dust and particles out of the eye. Their follicles have sebaceous "
              "glands (of Zeis) and apocrine glands (of Moll); an infected follicle is a stye (external "
              "hordeolum). Lashes growing back toward the cornea (trichiasis, as in trachoma) scar it.",
    "medial_canthus": "Medial canthus (medial palpebral commissure): the rounded inner angle where the upper and "
                      "lower lids meet, attached to the frontal process of the maxilla by the medial palpebral "
                      "ligament, in front of the lacrimal sac. It encloses the lacus lacrimalis, a small triangular "
                      "space holding the lacrimal caruncle, where tears collect before entering the puncta. "
                      "Epicanthic folds of skin cover it in many East Asian people and in Down syndrome. The "
                      "palpebral fissure spans from here to the lateral canthus (~30 mm).",
    "lateral_canthus": "Lateral canthus (lateral palpebral commissure): the sharper outer angle where the upper and "
                       "lower lids meet, 1-2 mm higher than the medial canthus and closer to the globe, anchored to "
                       "the orbital tubercle of the zygomatic bone by the lateral palpebral ligament. Cutting this "
                       "ligament (lateral canthotomy) is the emergency decompression for a retrobulbar haemorrhage "
                       "compressing the optic nerve.",
    # ---- conjunctiva
    "conj_palp": "Palpebral conjunctiva: the transparent mucous membrane lining the back of the eyelids, firmly "
                 "attached to the tarsal plates; red because its blood vessels show through. Stratified columnar "
                 "epithelium with goblet cells (mucin layer of the tear film) on a vascular lamina propria. At the "
                 "lid margin it meets the skin (the mucocutaneous junction). It is examined by pulling down the "
                 "lower lid or everting the upper - pale in anaemia; follicles (viral, chlamydial) or papillae "
                 "(allergic) in conjunctivitis.",
    "fornix_sup": "Superior conjunctival fornix: the deep recess, ~8-10 mm above the upper limbus, where the "
                  "palpebral conjunctiva of the upper lid reflects onto the globe as bulbar conjunctiva. The "
                  "ducts of the lacrimal gland open into its lateral part. The loose fold lets the eye and lid move "
                  "freely; lost contact lenses and foreign bodies lodge here. Together with the inferior fornix it "
                  "closes the conjunctival sac, the potential space between lids and globe that holds the tears.",
    "fornix_inf": "Inferior conjunctival fornix: the shallower recess below the lower limbus where the palpebral "
                  "conjunctiva of the lower lid reflects onto the globe. Eye drops are placed into it by pulling "
                  "down the lower lid. Shortening and scarring of the fornices (symblepharon) follow chemical "
                  "burns, Stevens-Johnson syndrome and ocular cicatricial pemphigoid.",
    "conj_bulb": "Bulbar conjunctiva: the thin, loose, transparent mucous membrane over the anterior sclera, from "
                 "the fornices to the limbus (it does not cover the cornea, whose epithelium it continues). Its fine "
                 "vessels move with it over the sclera. Inflammation (conjunctivitis - bacterial, viral, "
                 "allergic, chlamydial) dilates them: diffuse redness most marked towards the fornices, discharge, "
                 "grittiness, normal vision. Blood under it is a subconjunctival haemorrhage (alarming but "
                 "harmless); yellowing in jaundice is bilirubin bound in it; a fleshy wedge growing onto the cornea "
                 "is a pterygium.",
    "caruncle": "Lacrimal caruncle: a small, pink, fleshy nodule in the lacus lacrimalis at the medial canthus - a "
                "piece of modified skin with fine hairs, sebaceous and sweat glands. It produces the whitish "
                "secretion that collects at the inner corner of the eye. Tumours here are skin-type (naevi, "
                "papillomas).",
    "plica": "Plica semilunaris: a crescent-shaped fold of bulbar conjunctiva just lateral to the caruncle, "
             "allowing the eye to abduct without stretching the conjunctiva. It is the vestigial homologue of the "
             "nictitating membrane (third eyelid) of other vertebrates.",
    # ---- lacrimal apparatus
    "lacrimal_gland": "Lacrimal gland: an almond-sized, lobulated serous (tubuloacinar) gland in the lacrimal fossa "
                      "at the superolateral orbital margin, divided by the lateral horn of the levator aponeurosis "
                      "into a larger orbital lobe and a smaller palpebral lobe. It secretes the watery part of the "
                      "tears (with lysozyme, lactoferrin and IgA) for reflex tearing and crying; small accessory "
                      "glands in the conjunctiva maintain basal secretion. Parasympathetic secretomotor fibres come "
                      "from the facial nerve (superior salivatory nucleus - greater petrosal nerve - pterygopalatine "
                      "ganglion - zygomatic and lacrimal nerves). Sjögren syndrome (lymphocytic infiltration) "
                      "causes dry eyes; the gland enlarges in sarcoidosis and lymphoma.",
    "lacrimal_ducts": "Excretory ducts of the lacrimal gland: 6-12 fine ducts, all passing through the palpebral "
                      "lobe, that open into the lateral part of the superior conjunctival fornix. Tears then wash "
                      "across the eye from lateral to medial, helped by blinking, to the lacus lacrimalis. Removing "
                      "the palpebral lobe cuts all the ducts and so abolishes the gland's output.",
    "puncta": "Lacrimal puncta: two tiny openings (~0.3 mm), one on a small elevation (lacrimal papilla) near the "
              "medial end of each lid margin, turned back towards the lacus lacrimalis. They are the entrances to "
              "the tear drainage system; when the lower lid turns out (ectropion) or a punctum narrows (stenosis), "
              "tears overflow onto the cheek (epiphora). Punctal plugs are inserted to keep tears in dry eye.",
    "canaliculi": "Lacrimal canaliculi: from each punctum a canaliculus runs ~2 mm vertically (the dilated "
                  "ampulla) and then ~8 mm horizontally within the lid margin to the medial canthus; usually the "
                  "two join as a common canaliculus that opens into the lateral wall of the lacrimal sac. Blinking "
                  "and the lacrimal part of orbicularis oculi pump tears through them. Lacerations of the medial "
                  "lid can sever them and must be repaired over a stent.",
    "lacrimal_sac": "Lacrimal sac: the upper, dilated blind end of the tear drainage system, ~12 mm long, lying in "
                    "the lacrimal fossa of the medial orbital wall (between the anterior and posterior lacrimal "
                    "crests), behind the medial palpebral ligament. It receives tears from the canaliculi and "
                    "continues below as the nasolacrimal duct. Obstruction below it leads to a swollen, infected "
                    "sac - dacryocystitis, a tender swelling below the medial canthus; dacryocystorhinostomy opens "
                    "the sac directly into the nose.",
    "nld": "Nasolacrimal duct: a membranous duct ~12-18 mm long running down, slightly back and lateral in the "
           "bony nasolacrimal canal from the lacrimal sac to open into the inferior nasal meatus under the "
           "inferior nasal concha, guarded by a mucosal fold (valve of Hasner). Tear pathway: lacrimal gland - "
           "excretory ducts - across the eye - puncta - canaliculi - lacrimal sac - nasolacrimal duct - nasal "
           "cavity; this is why crying makes the nose run and why eye drops can be tasted. Failure of its lower "
           "end to open at birth (congenital nasolacrimal duct obstruction) gives a watery, sticky eye in ~5% of "
           "infants and usually resolves by a year.",
}


# ================================================================================================ optic nerve
def _nerve_path():
    pts = [D_DISC * 10.3, D_DISC * 11.4, D_DISC * 12.6, np.array([3.45, 0.5, -15.5]), np.array([4.0, 0.6, -19.5]),
           np.array([4.9, 1.0, -23.5]), np.array([8.4, 1.7, -28.6]), np.array([12.2, 2.3, -32.8])]
    return smooth_path(np.array(pts), 160)


def _arclen(p):
    return np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))])


def _retinal_tree(rng, vein):
    """Branches of the central retinal artery or vein on the inner surface of the retina: four arcades that arch
    round the macula temporally and fan out nasally, with twigs towards (never reaching) the fovea."""
    sgn = -1.0 if vein else 1.0
    off = 0.28 * sgn
    arcades = [
        [(0.0, 0.2), (-1.4, 1.4), (-3.6, 2.7), (-6.4, 3.0), (-9.4, 2.1), (-12.0, 0.6)],
        [(0.0, -0.2), (-1.4, -1.6), (-3.6, -3.3), (-6.4, -3.7), (-9.4, -2.9), (-12.0, -1.4)],
        [(0.2, 0.3), (1.4, 1.5), (3.2, 3.4), (5.6, 5.6), (8.2, 7.4)],
        [(0.2, -0.3), (1.4, -1.6), (3.2, -3.6), (5.6, -6.0), (8.2, -8.0)],
        [(0.3, 0.0), (2.2, 0.2), (4.8, 0.7), (7.6, 1.2)],
    ]
    paths, radii = [], []
    for k, ctrl in enumerate(arcades):
        c = np.array(ctrl, float)
        c[1:, 1] += off * np.linspace(0.3, 1.0, len(c) - 1)
        c[1:, 0] += 0.15 * sgn
        p2 = smooth_path(c, 60)
        paths.append(p2)
        radii.append(np.linspace(0.075 if vein else 0.058, 0.03, len(p2)) * (0.75 if k == 4 else 1.0))
        # side twigs
        for j in range(3 if k < 2 else 2):
            s = rng.uniform(0.3, 0.85)
            i0 = int(s * (len(p2) - 1))
            base = p2[i0]
            tang = p2[min(i0 + 1, len(p2) - 1)] - p2[max(i0 - 1, 0)]
            tang /= np.linalg.norm(tang)
            side = np.array([-tang[1], tang[0]]) * rng.choice([-1.0, 1.0])
            if k < 2:                       # temporal arcades send twigs towards the macula and outwards
                toward = (np.array([-4.1, -0.9]) - base)
                side = toward / np.linalg.norm(toward) if j == 0 else -side if side @ toward > 0 else side
            end = base + (tang * 0.8 + side) * rng.uniform(2.0, 3.5)
            if k < 2 and j == 0:
                end = base + (np.array([-4.1, -0.9]) - base) * 0.62      # stop short: foveal avascular zone
            tw = smooth_path(np.array([base, base * 0.5 + end * 0.5 + side * 0.4, end]), 20)
            paths.append(tw)
            radii.append(np.linspace(0.032, 0.018, len(tw)))
    out = []
    for p2, r in zip(paths, radii):
        d = _fundus_dir(p2[:, 0], p2[:, 1])
        p3 = d * (rho_retina_in(d) - r * 0.7)[:, None]
        out.append((p3, r))
    return out


def build_nerve():
    out = []

    def add(name, group, color, mesh, key, cat="organ", alpha=1.0, rank=0.0):
        out.append((name, group, color, mesh, key, cat, alpha, rank))

    path = _nerve_path()
    s = _arclen(path)
    rho = path @ D_DISC
    r = np.interp(rho, [10.3, 11.05, 11.9, 12.8], [0.93, 0.96, 1.45, 1.6])
    r = np.where(s > 5.0, np.interp(s, [5.0, s[-1]], [1.6, 1.5]), r)
    add("Optic nerve (CN II)", "Optic nerve & vessels", "#f2e6bf", ctube(path, r, 40), "optic_nerve", "nerve")
    i0 = int(np.searchsorted(rho, 11.2))
    sp = path[i0:]
    ss = _arclen(sp)
    r_out = np.interp(ss, [0.0, 1.2, 3.0, ss[-1]], [2.9, 2.55, 2.4, 2.2])
    r_in = np.interp(ss, [0.0, 1.2, 3.0, ss[-1]], [1.2, 1.9, 2.0, 1.85])
    from .kit import tube_shell
    add("Dural sheath of optic nerve", "Optic nerve & vessels", "#d8ccb6", tube_shell(sp, r_out, r_in, 40),
        "dura", "fascia", rank=-1)

    rng = np.random.default_rng(11)
    for vein in (False, True):
        side = np.array([0.0, -0.21, 0.0]) if vein else np.array([0.0, 0.21, 0.0])
        k = int(np.searchsorted(path[:, 2] * -1, 19.0))      # ~8 mm behind the globe
        axis = path[:k][::-1] + side                           # back along the nerve axis to the disc
        axis = axis[axis @ D_DISC > 10.25]
        entry = path[k] + side + np.array([0.3, -1.2, 0.0])
        outside = path[k] + side + np.array([1.2, -4.2, -1.5])
        far = path[k] + side + np.array([2.6, -6.0, -4.5])
        trunk = smooth_path(np.vstack([far, outside, entry, path[k] + side * 1.0, axis[::4], axis[-1:],
                                       D_DISC * (float(rho_retina_in(D_DISC[None])[0]) + 0.28)]), 120)
        rr = 0.19 if vein else 0.15
        meshes = [ctube(trunk, np.full(len(trunk), rr), 12)]
        for p3, rad in _retinal_tree(rng, vein):
            meshes.append(ctube(p3, rad, 7))
        name = "Central retinal vein" if vein else "Central retinal artery"
        add(name, "Optic nerve & vessels", "#3c4ea6" if vein else "#c9352d", orient_outward(merged(meshes)),
            "crv" if vein else "cra", "vein" if vein else "artery", rank=1)
    return out


# ================================================================================================ extrinsic muscles
def _sph(theta_deg, phi_deg, r=1.0):
    t, p = math.radians(theta_deg), math.radians(phi_deg)
    return r * np.array([math.sin(t) * math.cos(p), math.sin(t) * math.sin(p), math.cos(t)])


def _wrap_path(ins_dir, origin, lift, n_arc=40, n_line=60):
    """Centreline of a rectus: along the globe from its insertion (great circle towards the origin) to the point
    where it leaves the globe tangentially, then straight to the origin. lift(s) gives the height of the
    centreline above the sclera at arclength s from the insertion."""
    I = _unit(*ins_dir)
    O = np.asarray(origin, float)
    n = np.cross(I, O)
    n /= np.linalg.norm(n)
    e1, e2 = I, np.cross(n, I)
    L = np.linalg.norm(O)
    gam = math.atan2(O @ e2, O @ e1)
    Rw = R_S + lift(8.0)
    tau = max(gam - math.acos(min(Rw / L, 1.0)), 0.05)
    a = np.linspace(0.0, tau, n_arc)
    s_arc = a * R_S
    arc = (np.cos(a)[:, None] * e1 + np.sin(a)[:, None] * e2) * (R_S + lift(s_arc))[:, None]
    T = arc[-1]
    line = np.linspace(T, O, n_line)[1:]
    return np.vstack([arc, line])


def _push_out(path, clearance):
    """Keep a centreline outside the globe (radius R_S + clearance, clearance per point)."""
    r = np.linalg.norm(path, axis=1)
    need = R_S + np.asarray(clearance, float)
    k = np.maximum(need / np.maximum(r, 1e-9), 1.0)
    return path * k[:, None]


def _rectus(ins_theta, ins_phi, origin, tendon, width, lift0=0.0, belly_t=1.45, seed=0):
    def ht(s):
        s = np.asarray(s, float)
        return np.interp(s, [0.0, tendon, tendon + 7.0, 26.0, 36.0, 60.0],
                         [0.32, 0.4, belly_t, belly_t, 0.75, 0.6])

    path = _wrap_path(_sph(ins_theta, ins_phi), origin, lambda s: ht(s) + 0.06 + lift0 * np.clip(
        (np.asarray(s, float) - tendon * 0.2) / 3.0, 0, 1))
    path = smooth_path(path, 110)
    s = _arclen(path)
    hw = np.interp(s, [0.0, tendon, tendon + 8.0, 28.0, s[-1] - 2.0, s[-1]],
                   [width / 2, width / 2 * 0.95, width / 2 * 0.85, width / 2 * 0.68, 1.9, 1.6])
    h = ht(s)
    # the flat face of the muscle faces the globe (and the optic nerve behind it)
    g = np.gradient(path, axis=0)
    nvec = path - (np.sum(path * g, 1) / np.maximum(np.sum(g * g, 1), 1e-9))[:, None] * g
    nvec /= np.linalg.norm(nvec, axis=1, keepdims=True)
    return ribbon(path, nvec, hw, h, 26, 3.2)


def _ring_point(offset):
    return APEX + np.asarray(offset, float)


TROCHLEA = np.array([12.4, 13.4, 2.2])


def build_muscles():
    out = []

    def add(name, color, mesh, key, cat="muscle", rank=0.0, group="Extrinsic eye muscles"):
        out.append((name, group, color, mesh, key, cat, 1.0, rank))

    red = "#b3453d"
    add("Superior rectus", red, _rectus(68.4, 85.0, _ring_point((0.3, 3.6, 0.0)), 5.8, 10.6, lift0=0.75), "sr")
    add("Inferior rectus", red, _rectus(62.4, 275.0, _ring_point((0.3, -3.6, 0.0)), 5.5, 9.8), "ir")
    add("Medial rectus", red, _rectus(57.4, 0.0, _ring_point((3.6, 0.0, 0.2)), 3.7, 10.3, belly_t=1.6), "mr")
    add("Lateral rectus", red, _rectus(64.4, 180.0, _ring_point((-3.6, 0.2, -0.2)), 8.8, 9.2), "lr")

    # superior oblique: belly along the superomedial wall, round tendon through the trochlea, reflected tendon
    # back under the superior rectus to the posterosuperolateral globe
    o = _ring_point((2.8, 4.3, 0.4))
    belly = smooth_path(np.array([o, [15.0, 8.6, -19.0], [14.6, 11.6, -8.0], [13.4, 13.0, -1.5], TROCHLEA]), 80)
    sb = _arclen(belly)
    rb = np.interp(sb, [0, 4, 12, 26, sb[-1] - 9, sb[-1] - 6, sb[-1]], [0.9, 1.35, 1.9, 1.7, 1.1, 0.62, 0.55])
    ins = _sph(102.0, 118.0, R_S)
    refl = smooth_path(np.array([TROCHLEA, [9.0, 13.0, 1.6], [5.0, 12.2, 0.9], [1.0, 11.8, -0.2], [-2.6, 11.2, -1.2],
                                 ins * 1.0]), 80)
    refl = _push_out(refl, np.full(len(refl), 0.3))
    sr_ = _arclen(refl)
    hw = np.interp(sr_, [0, 6, sr_[-1] - 8, sr_[-1]], [0.55, 0.9, 2.2, 4.8])
    ht = np.interp(sr_, [0, 6, sr_[-1] - 8, sr_[-1]], [0.55, 0.42, 0.3, 0.22])
    nv = refl / np.linalg.norm(refl, axis=1, keepdims=True)
    so = merged([ctube(belly, rb, 22), ribbon(refl, nv, hw, ht, 22, 3.0)])
    add("Superior oblique", red, orient_outward(so), "so")
    tro = torus_mesh(TROCHLEA, belly[-1] - belly[-6], 0.95, 0.42, 36, 14)
    add("Trochlea", "#dfe6df", tro, "trochlea", "cartilage", rank=1)

    # inferior oblique: from the orbital floor beside the nasolacrimal canal, under the inferior rectus, to the
    # posterolateral globe near the macula
    ins = _sph(114.0, 202.0, R_S)
    io = smooth_path(np.array([[13.2, -14.0, 6.2], [8.5, -15.4, 3.8], [3.0, -15.9, 0.8], [-3.0, -14.9, -1.8],
                               [-7.4, -11.6, -3.6], [-9.9, -7.6, -4.6], ins]), 110)
    s = _arclen(io)
    ht = np.interp(s, [0, 3, 10, s[-1] - 5, s[-1]], [0.7, 0.9, 1.05, 0.6, 0.3])
    io = _push_out(io, ht + 0.06)
    hw = np.interp(s, [0, 3, 14, s[-1] - 6, s[-1]], [2.2, 2.6, 3.0, 3.6, 4.4])
    nv = io / np.linalg.norm(io, axis=1, keepdims=True)
    add("Inferior oblique", red, ribbon(io, nv, hw, ht, 24, 3.0), "io")

    ring_axis = -APEX / np.linalg.norm(APEX)
    add("Common tendinous ring", "#e4dccb", torus_mesh(APEX + ring_axis * 0.2, ring_axis, 3.7, 0.75, 48, 14),
        "annulus", "tendon", rank=1)
    return out


# ================================================================================================ eyelids & conjunctiva
PSI_L, PSI_M = -80.0, 72.0          # lateral and medial ends of the lids (degrees about the vertical axis)
BETA_FU, BETA_FL = 72.0, -62.0      # superior and inferior conjunctival fornices (elevation, degrees)


def P3(psi, beta, r):
    """Point at azimuth psi about the vertical axis, elevation beta, distance r from the centre of the globe."""
    psi, beta, r = np.broadcast_arrays(np.radians(psi), np.radians(beta), np.asarray(r, float))
    c = np.cos(beta)
    return np.stack([r * c * np.sin(psi), r * np.sin(beta), r * c * np.cos(psi)], -1)


def G(psi, beta):
    return globe_radius(P3(psi, beta, 1.0))


def _s(psi):
    return np.clip((np.asarray(psi, float) - PSI_L) / (PSI_M - PSI_L), 0.0, 1.0)


def beta_upper(psi):
    s = _s(psi)
    base = 4.5 * (1 - s)
    return base + (19.0 - base) * np.sin(math.pi * s) ** 0.7


def beta_lower(psi):
    s = _s(psi)
    base = 4.5 * (1 - s)
    return base - (26.5 + base) * np.sin(math.pi * s) ** 0.85


def _extra(psi, beta, beta_margin):
    """The lids stand off the globe near the canthi (the caruncle and lacus lacrimalis fill the medial angle)."""
    s = _s(psi)
    e = 3.0 * np.maximum((s - 0.84) / 0.16, 0) ** 1.6 + 0.9 * np.maximum((0.1 - s) / 0.1, 0) ** 2
    return e * np.clip(1.0 - np.abs(np.asarray(beta) - beta_margin) / 22.0, 0.0, 1.0)


def r_post(psi, beta, beta_margin):
    """Posterior surface of a lid (the free surface of its palpebral conjunctiva)."""
    return G(psi, beta) + GAP + CT + _extra(psi, beta, beta_margin)


def _yh(beta, r):
    b = np.radians(beta)
    return np.stack([r * np.sin(b), r * np.cos(b)], -1)


def _resample(poly, n):
    poly = np.asarray(poly, float)
    s = _arclen(poly)
    t = np.linspace(0, s[-1], n)
    return np.stack([np.interp(t, s, poly[:, k]) for k in range(poly.shape[1])], -1)


def _offset(center, half):
    """Band of half-thickness `half` around a 2D centreline: a closed polygon."""
    c = np.asarray(center, float)
    t = np.gradient(c, axis=0)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-9)
    n = np.stack([-t[:, 1], t[:, 0]], -1)
    half = np.broadcast_to(np.asarray(half, float), (len(c),))[:, None]
    return np.vstack([c + n * half, (c - n * half)[::-1]])


def _to3d(psi, yh):
    y, h = yh[:, 0], yh[:, 1]
    p = math.radians(psi)
    return np.stack([h * math.sin(p), y, h * math.cos(p)], -1)


def _taper(psi, yh):
    """Shape the lids as a patch of face: away from the midline every layer stands further off the globe (the face
    is much flatter than the globe, so the lids thicken towards the canthi), and right at the canthi every layer
    sinks back towards the globe so the lids end thin instead of as blocks. Both are radial moves about the lid's
    posterior surface, so nested layers stay in register."""
    s = float(_s(psi))
    w = np.clip(min(s, 1.0 - s) / 0.11, 0.0, 1.0)
    w = 0.2 + 0.8 * w * w * (3 - 2 * w)
    w *= 1.0 + 0.85 * (1.0 - math.cos(math.radians(psi)))
    if abs(w - 1.0) < 1e-3:
        return yh
    y, h = yh[:, 0], yh[:, 1]
    r = np.hypot(y, h)
    beta = np.degrees(np.arctan2(y, h))
    rg = G(psi, beta) + GAP + CT
    d = r - rg
    r2 = rg + np.where(d > 0, d * w, d)
    return _yh(beta, r2)


def lid_sweep(profile_fn, psi0, psi1, k=120):
    rings = [_to3d(p, _taper(p, profile_fn(p))) for p in np.linspace(psi0, psi1, k)]
    return sweep(np.array(rings))


# ---- upper and lower lid profile pieces (y, h) that do not depend on psi
UP_Q = np.array([12.4, 8.2])           # orbital septum fuses with the levator aponeurosis
UP_RIM = np.array([14.4, 10.9])        # septum's attachment to the orbital rim (arcus marginalis)
UP_TOP = np.array([[14.9, 11.3], [15.4, 12.2], [15.5, 13.3]])     # rounded upper edge of the specimen
UP_SKIN = np.array([[15.2, 14.1], [14.3, 14.2], [13.3, 13.8], [12.5, 13.4], [11.9, 12.9], [11.5, 11.9],
                    [11.1, 10.3], [10.9, 9.5]])           # fold of the upper lid tucking into the lid crease
LO_Q = np.array([-11.8, 8.3])
LO_RIM = np.array([-13.6, 9.6])
LO_BOTTOM = np.array([[-14.1, 10.1], [-14.6, 11.0], [-14.7, 12.0]])
LO_SKIN = np.array([[-14.4, 12.8], [-13.5, 12.3], [-12.4, 11.5]])


def _margin(psi, bm, r0, thick, upper):
    """Rounded free margin from the anterior to the posterior edge."""
    t = np.linspace(0, 1, 9)
    r = r0 + thick * (1 - t)
    sgn = 1.0 if upper else -1.0
    beta = bm + sgn * (0.9 * (1 - t) ** 2) - sgn * 0.55 * np.sin(math.pi * t)
    return _yh(beta, r)


def upper_lid_profile(psi):
    bu = float(beta_upper(psi))
    bpost = np.linspace(bu, BETA_FU, 44)
    post = _yh(bpost, r_post(psi, bpost, bu))
    F = post[-1]
    pre_b = np.linspace(min(bu + 27.0, 50.0), bu + 1.1, 22)
    T = np.interp(pre_b - bu, [0, 8, 27], [2.45, 2.75, 2.95])
    pre = _yh(pre_b, r_post(psi, pre_b, bu) + T)
    back = _resample(np.vstack([F, UP_Q, UP_RIM]), 16)[1:]
    skin = _resample(np.vstack([UP_TOP, UP_SKIN]), 26)
    marg = _margin(psi, bu, float(r_post(psi, bu, bu)), 2.45, True)
    return np.vstack([post, back, skin, pre, marg[1:-1]])


def lower_lid_profile(psi):
    bl = float(beta_lower(psi))
    bpost = np.linspace(bl, BETA_FL, 40)
    post = _yh(bpost, r_post(psi, bpost, bl))
    F = post[-1]
    pre_b = np.linspace(max(bl - 20.0, -50.0), bl - 1.1, 18)
    T = np.interp(bl - pre_b, [0, 8, 20], [2.3, 2.6, 2.8])
    pre = _yh(pre_b, r_post(psi, pre_b, bl) + T)
    back = _resample(np.vstack([F, LO_Q, LO_RIM]), 14)[1:]
    skin = _resample(np.vstack([LO_BOTTOM, LO_SKIN]), 12)
    marg = _margin(psi, bl, float(r_post(psi, bl, bl)), 2.3, False)
    return np.vstack([post, back, skin, pre, marg[1:-1]])


def _tarsus_height(psi, upper):
    s = _s(psi)
    lo, hi = (0.06, 0.86) if upper else (0.07, 0.85)
    u = np.clip((s - lo) / (hi - lo), 0, 1)
    return (10.0 if upper else 4.6) * np.maximum(np.sin(math.pi * u), 0.08) ** 0.55


def tarsus_profile(psi, upper):
    bm = float(beta_upper(psi) if upper else beta_lower(psi))
    sgn = 1.0 if upper else -1.0
    H = float(_tarsus_height(psi, upper))
    rp = float(r_post(psi, bm, bm))
    b1 = bm + sgn * math.degrees(H / rp)
    b = np.linspace(bm + sgn * 0.5, b1, 24)
    inner = _yh(b, r_post(psi, b, bm) + 0.02)
    outer = _yh(b[::-1], r_post(psi, b[::-1], bm) + 0.95 - 0.35 * ((b[::-1] - bm) / (b1 - bm)) ** 4)
    return np.vstack([inner, outer])


def conj_profile(psi, upper):
    bm = float(beta_upper(psi) if upper else beta_lower(psi))
    bf = BETA_FU if upper else BETA_FL
    sgn = 1.0 if upper else -1.0
    b = np.linspace(bm + sgn * 0.3, bf - sgn * 7.0, 50)
    c = _yh(b, r_post(psi, b, bm) - CT / 2)
    return _offset(c, CT / 2)


def fornix_profile(psi, upper):
    bf = BETA_FU if upper else BETA_FL
    sgn = 1.0 if upper else -1.0
    b = np.linspace(bf - sgn * 7.0, bf, 16)
    g = G(psi, bf)
    pal = _yh(b, G(psi, b) + GAP + CT / 2)
    bul = _yh(b[::-1], G(psi, b[::-1]) + CT / 2)
    cb = math.radians(bf)
    radial = np.array([math.sin(cb), math.cos(cb)])
    tang = np.array([math.cos(cb), -math.sin(cb)]) * sgn
    C = _yh(np.array([bf]), np.array([g + GAP / 2 + CT / 2]))[0]
    tau = np.linspace(0, math.pi, 14)[1:-1]
    cap = C + (GAP / 2) * (np.cos(tau)[:, None] * radial + np.sin(tau)[:, None] * tang)
    return _offset(np.vstack([pal, cap, bul]), CT / 2)


def _band_path(psi, upper):
    """Centreline of the palpebral orbicularis: in front of the tarsus, under the crease and up into the fold."""
    if upper:
        bu = float(beta_upper(psi))
        b = np.linspace(bu + 1.2, min(bu + 27.0, 50.0), 16)
        pre = _yh(b, r_post(psi, b, bu) + np.interp(b - bu, [0, 8, 27], [2.45, 2.75, 2.95]) - 0.85)
        up = np.array([[10.75, 8.6], [11.55, 10.5], [12.45, 12.2], [13.6, 13.0], [14.6, 13.35]])
        return smooth_path(np.vstack([pre, up]), 60)
    bl = float(beta_lower(psi))
    b = np.linspace(bl - 1.2, max(bl - 20.0, -50.0), 14)
    pre = _yh(b, r_post(psi, b, bl) + np.interp(bl - b, [0, 8, 20], [2.3, 2.6, 2.8]) - 0.8)
    down = np.array([[-12.0, 10.0], [-13.2, 10.9], [-13.9, 11.4]])
    return smooth_path(np.vstack([pre, down]), 50)


def aponeurosis_path(psi):
    bu = float(beta_upper(psi))
    H = float(_tarsus_height(psi, True))
    b = np.linspace(bu + math.degrees(H / 12.6) - 3.0, bu + 0.35 * math.degrees(H / 12.6), 12)
    pre = _yh(b, r_post(psi, b, bu) + 1.07)
    top = np.array([[14.6, 4.9], [13.4, 6.8], [12.35, 7.7], [11.6, 7.5]])
    return smooth_path(np.vstack([top, pre]), 50)


def muller_path(psi):
    bu = float(beta_upper(psi))
    H = float(_tarsus_height(psi, True))
    b0 = bu + math.degrees(H / 12.6) - 0.8
    b = np.linspace(b0, BETA_FU + 1.5, 10)
    low = _yh(b, G(psi, b) + GAP + CT + 0.42)
    top = np.array([[13.35, 4.15], [14.2, 4.3]])
    return smooth_path(np.vstack([low, top]), 30)


def _fornix_loop(n=300):
    """Directions along the whole fornix line (the edge of the bulbar conjunctiva): superior fornix lateral to
    medial, down the medial side (plica), inferior fornix medial to lateral, up the lateral side."""
    k = n // 4
    up_psi = np.linspace(PSI_L, PSI_M, k)
    med_b = np.linspace(BETA_FU - 7.0, BETA_FL + 7.0, k)
    lo_psi = np.linspace(PSI_M, PSI_L, k)
    lat_b = np.linspace(BETA_FL + 7.0, BETA_FU - 7.0, k)
    pts = np.vstack([P3(up_psi, BETA_FU - 7.0, 1.0)[:-1], P3(PSI_M, med_b, 1.0)[:-1],
                     P3(lo_psi, BETA_FL + 7.0, 1.0)[:-1], P3(PSI_L, lat_b, 1.0)[:-1]])
    return pts / np.linalg.norm(pts, axis=1, keepdims=True)


def _lashes(upper, rng):
    paths, radii = [], []
    s0, s1 = (0.05, 0.80) if upper else (0.07, 0.79)
    count = 125 if upper else 62
    for i in range(count):
        s = s0 + (s1 - s0) * (i + rng.uniform(-0.4, 0.4)) / count
        psi = PSI_L + s * (PSI_M - PSI_L)
        bm = float(beta_upper(psi) if upper else beta_lower(psi))
        rp = float(r_post(psi, bm, bm))
        row = rng.integers(0, 3)
        sgn = 1.0 if upper else -1.0
        base = P3(psi, bm + sgn * (0.25 + 0.2 * row), rp + 2.05 + 0.13 * row)
        radial = base / np.linalg.norm(base)
        curl = P3(psi, bm + sgn * 90.0, 1.0)                  # towards increasing |elevation|
        d0 = radial * 0.93 - curl * 0.37
        L = (rng.uniform(7.0, 9.0) if upper else rng.uniform(4.5, 6.0)) * (0.55 + 0.45 * math.sin(math.pi * s))
        t = np.linspace(0, 1, 10)[:, None]
        side = np.cross(radial, curl) * rng.uniform(-0.12, 0.12)
        p = base + L * (t * (d0 + side) + t * t * curl * 0.62)
        paths.append(p)
        radii.append(np.linspace(0.075, 0.025, 10))
    return tubes(paths, radii, 5)


def _tarsal_glands(upper, rng):
    meshes = []
    s0, s1 = (0.10, 0.83) if upper else (0.11, 0.82)
    count = 28 if upper else 22
    for i in range(count):
        s = s0 + (s1 - s0) * (i + 0.5 + rng.uniform(-0.2, 0.2)) / count
        psi = PSI_L + s * (PSI_M - PSI_L)
        bm = float(beta_upper(psi) if upper else beta_lower(psi))
        sgn = 1.0 if upper else -1.0
        H = float(_tarsus_height(psi, upper))
        rp = float(r_post(psi, bm, bm))
        b = np.linspace(bm - sgn * 0.25, bm + sgn * math.degrees(0.9 * H / rp), 26)
        path = P3(psi, b, r_post(psi, b, bm) + 0.45)
        rad = 0.14 + 0.05 * np.abs(np.sin(np.linspace(0, 1, 26) * math.pi * (5 if upper else 3)))
        rad[:2] = 0.08
        meshes.append(ctube(path, rad, 8))
        # acini budding off the central duct
        for j in range(4, 26, 3):
            side = 1 if (j // 3) % 2 else -1
            q = P3(psi + side * math.degrees(0.2 / rp), b[j], float(r_post(psi, b[j], bm)) + 0.45)
            meshes.append(ellipsoid_mesh(q, (0.18, 0.2, 0.18), res=5))
    return orient_outward(merged(meshes))


def _band_sweep(path_fn, half, psi0, psi1, k=90):
    return lid_sweep(lambda p: _offset(path_fn(p), half), psi0, psi1, k)


def build_lids():
    out = []
    rng = np.random.default_rng(21)

    def add(name, group, color, mesh, key, cat="skin", alpha=1.0, rank=0.0):
        out.append((name, group, color, mesh, key, cat, alpha, rank))

    skin = "#e6b598"
    add("Upper eyelid", "Eyelids", skin, lid_sweep(upper_lid_profile, PSI_L, PSI_M, 150), "upper_lid", rank=-1)
    add("Lower eyelid", "Eyelids", skin, lid_sweep(lower_lid_profile, PSI_L, PSI_M, 150), "lower_lid", rank=-1)
    add("Superior tarsal plate", "Eyelids", "#efe5cc",
        lid_sweep(lambda p: tarsus_profile(p, True), PSI_L + 8.0, PSI_M - 20.0, 110), "tarsus_sup", "fascia")
    add("Inferior tarsal plate", "Eyelids", "#efe5cc",
        lid_sweep(lambda p: tarsus_profile(p, False), PSI_L + 9.0, PSI_M - 20.0, 110), "tarsus_inf", "fascia")
    add("Tarsal (meibomian) glands", "Eyelids", "#f0d27a",
        merged([_tarsal_glands(True, rng), _tarsal_glands(False, rng)]), "meibomian", "gland", rank=1)
    add("Orbicularis oculi (palpebral part)", "Eyelids", "#b8493f",
        merged([_band_sweep(lambda p: _band_path(p, True), 0.34, PSI_L + 2, PSI_M - 3),
                _band_sweep(lambda p: _band_path(p, False), 0.32, PSI_L + 2, PSI_M - 3)]), "orbicularis", "muscle")
    add("Superior tarsal muscle", "Eyelids", "#c7746a", _band_sweep(muller_path, 0.2, -48.0, 38.0, 70), "muller",
        "muscle", rank=1)
    add("Eyelashes", "Eyelids", "#2a1c15", merged([_lashes(True, rng), _lashes(False, rng)]), "lashes", "nail",
        rank=1)

    # canthi: where the free margins of the two lids meet
    for psi, name, key in ((PSI_M - 0.5, "Medial canthus (medial palpebral commissure)", "medial_canthus"),
                           (PSI_L + 0.5, "Lateral canthus (lateral palpebral commissure)", "lateral_canthus")):
        bm = float(beta_upper(psi))
        c = P3(psi, bm, float(r_post(psi, bm, bm)) + 1.25)
        tang = P3(psi + 90.0, 0.0, 1.0)
        rot = np.stack([tang, [0.0, 1.0, 0.0], np.cross(tang, [0.0, 1.0, 0.0])], 1)
        add(name, "Eyelids", "#e2a88d", ellipsoid_mesh(c, (1.7, 1.25, 1.4), res=16, rotation=rot), key, rank=1)

    # conjunctiva
    pink = "#e2878a"
    add("Palpebral conjunctiva", "Conjunctiva", pink,
        merged([lid_sweep(lambda p: conj_profile(p, True), PSI_L + 1, PSI_M - 1, 120),
                lid_sweep(lambda p: conj_profile(p, False), PSI_L + 1, PSI_M - 1, 120)]), "conj_palp", "mucosa",
        rank=1)
    add("Superior conjunctival fornix", "Conjunctiva", "#d9727d",
        lid_sweep(lambda p: fornix_profile(p, True), PSI_L + 1, PSI_M - 1, 120), "fornix_sup", "mucosa", rank=1)
    add("Inferior conjunctival fornix", "Conjunctiva", "#d9727d",
        lid_sweep(lambda p: fornix_profile(p, False), PSI_L + 1, PSI_M - 1, 120), "fornix_inf", "mucosa", rank=1)
    loop = _fornix_loop(320)
    phi = np.arctan2(loop[:, 1], loop[:, 0])
    front = ring_front(TH_LIMBUS + 0.4, phi)
    add("Bulbar conjunctiva", "Conjunctiva", "#f0c3bd",
        shell(loop, loop, front, front, lambda d: np.full(d.shape[:-1], R_S + 0.01),
              lambda d: np.full(d.shape[:-1], R_S + CT), 36), "conj_bulb", "mucosa", alpha=0.42, rank=1)

    # caruncle and plica in the medial angle
    c = P3(65.5, -1.2, R_S + 1.75)
    m = ellipsoid_mesh(c, (1.35, 2.0, 1.3), res=22)
    p, n, i = m.parts[0]
    bump = 1.0 + 0.07 * np.sin(p[:, 0] * 9.0) * np.sin(p[:, 1] * 8.0) * np.sin(p[:, 2] * 7.0)
    add("Lacrimal caruncle", "Conjunctiva", "#dd7f7c", Mesh().add((p - c) * bump[:, None] + c, i), "caruncle",
        "mucosa", rank=1)
    b = np.linspace(-8.5, 8.0, 30)
    psi_p = 58.5 - 1.6 * np.cos(np.radians(b) * 5.0)
    path = P3(psi_p, b, G(psi_p, b) + 0.55)
    nvec = P3(psi_p + 90.0, np.zeros_like(b), 1.0)
    hw = 0.5 * np.sin(np.linspace(0.12, 0.88, 30) * math.pi) + 0.05
    add("Plica semilunaris", "Conjunctiva", "#e79b98", ribbon(path, nvec, hw, 0.14, 12, 2.5), "plica", "mucosa",
        rank=1)
    return out


# ================================================================================================ levator & lacrimal
def build_levator():
    o = _ring_point((1.0, 5.6, 0.6))
    belly = smooth_path(np.array([o, [7.6, 13.6, -16.5], [2.7, 15.7, -4.6], [0.6, 15.5, 1.6], [0.1, 15.0, 3.8]]),
                        90)
    s = _arclen(belly)
    hw = np.interp(s, [0, 5, 20, s[-1] - 6, s[-1]], [1.8, 2.6, 4.2, 5.4, 5.8])
    ht = np.interp(s, [0, 5, 20, s[-1] - 6, s[-1]], [0.45, 0.62, 0.75, 0.6, 0.3])
    nv = belly / np.linalg.norm(belly, axis=1, keepdims=True)
    apo = _band_sweep(aponeurosis_path, 0.11, -56.0, 46.0, 80)
    m = merged([ribbon(belly, nv, hw, ht, 24, 3.0), apo])
    return [("Levator palpebrae superioris", "Extrinsic eye muscles", "#b04a42", m, "lps", "muscle", 1.0, 0.0)]


SAC_C = np.array([17.2, 1.0, 3.0])


def _lobules(centre, axes, radii, count, rng, r_lob=(0.9, 1.4)):
    """Lobulated gland: small spheres packed inside an ellipsoid, smoothly united."""
    axes = np.asarray(axes, float)
    pts = []
    while len(pts) < count:
        q = rng.uniform(-1, 1, 3)
        if q @ q <= 1.0:
            pts.append(q)
    lo = np.asarray(centre) - max(radii) - 2.0
    hi = np.asarray(centre) + max(radii) + 2.0
    v = Volume(lo, hi, 0.2)
    shapes = []
    for q in pts:
        c = np.asarray(centre) + axes.T @ (q * np.asarray(radii) * 0.82)
        shapes.append(ellipsoid(c, (rng.uniform(*r_lob),) * 3))
    v.add_all(shapes, "smooth", 0.35)
    return v.mesh(0.8)


def build_lacrimal():
    out = []
    rng = np.random.default_rng(31)

    def add(name, color, mesh, key, cat="gland", rank=0.0):
        out.append((name, "Lacrimal apparatus", color, mesh, key, cat, 1.0, rank))

    # orbital and palpebral lobes, separated by the lateral horn of the levator aponeurosis
    u1 = _unit(0.72, 0.66, 0.2)
    u3 = np.array([-0.7, 0.7, 0.0])
    u3 -= u1 * (u3 @ u1)
    u3 /= np.linalg.norm(u3)
    u2 = np.cross(u1, u3)
    orb = _lobules((-10.8, 11.2, 0.4), [u1, u2, u3], (9.0, 5.6, 2.4), 260, rng, (0.55, 0.9))
    pc = P3(-58.0, 66.0, 13.3)
    t1 = P3(-58.0 + 90.0, 0.0, 1.0)                              # horizontal tangent
    rad = pc / np.linalg.norm(pc)
    t2 = np.cross(rad, t1)
    pal = _lobules(pc, [t1, t2, rad], (3.6, 1.8, 1.1), 60, rng, (0.45, 0.7))
    add("Lacrimal gland", "#e2a98f", merged([orb, pal]), "lacrimal_gland")

    ducts = []
    for k in range(8):
        psi = -70.0 + 25.0 * k / 7
        a = P3(-58.0 + (psi + 58.0) * 0.6, 65.5, 12.7)
        b = P3(psi, 69.0, R_S + 0.2)
        mid = (a + b) / 2 + rad * 0.3
        ducts.append(smooth_path(np.array([a, mid, b]), 12))
    add("Excretory ducts of lacrimal gland", "#f0cfa8", tubes(ducts, [0.1] * len(ducts), 6), "lacrimal_ducts",
        rank=1)

    # puncta, canaliculi, sac, nasolacrimal duct
    tori, canal = [], []
    common = SAC_C + np.array([-1.75, 0.7, 1.3])
    for upper, psi_p in ((True, 49.0), (False, 50.5)):
        bm = float(beta_upper(psi_p) if upper else beta_lower(psi_p))
        sgn = 1.0 if upper else -1.0
        rp = float(r_post(psi_p, bm, bm))
        axis = P3(psi_p, bm - sgn * 90.0, 1.0)
        tori.append(torus_mesh(P3(psi_p, bm - sgn * 0.35, rp + 0.5), axis, 0.32, 0.13, 24, 10))
        pts = [P3(psi_p, bm - sgn * 0.1, rp + 0.5), P3(psi_p, bm + sgn * 5.0, rp + 0.55),
               P3(psi_p + 1.5, bm + sgn * 8.5, rp + 0.6)]
        for psi in (56.0, 63.0, 69.0):
            b = float(beta_upper(psi) if upper else beta_lower(psi))
            pts.append(P3(psi, b + sgn * 5.0, float(r_post(psi, b, b)) + 0.6))
        pts += [common + np.array([-0.9, sgn * 0.6, 0.4]), common]
        canal.append(smooth_path(np.array(pts), 60))
    add("Lacrimal puncta", "#f2b2a2", orient_outward(merged(tori)), "puncta", "mucosa", rank=2)
    add("Lacrimal canaliculi", "#e7928d",
        merged([ctube(p, np.interp(_arclen(p), [0, 0.8, 1.8, 3.0, 100], [0.2, 0.34, 0.34, 0.24, 0.24]), 10)
                for p in canal] + [ctube(np.array([common, common + (SAC_C - common) * 0.7]), 0.3, 10)]),
        "canaliculi", "mucosa", rank=1)
    add("Lacrimal sac", "#d98586", ellipsoid_mesh(SAC_C, (1.9, 6.0, 2.6), res=28), "lacrimal_sac", "mucosa")
    nld = smooth_path(np.array([SAC_C + [0.0, -3.5, 0.0], SAC_C + [-0.2, -9.0, -0.7], SAC_C + [-0.6, -15.0, -1.8],
                                SAC_C + [-1.2, -21.5, -3.0]]), 60)
    add("Nasolacrimal duct", "#cf7f86", ctube(nld, np.linspace(1.55, 1.25, len(nld)), 22), "nld", "mucosa")
    return out
