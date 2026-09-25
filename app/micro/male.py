"""Male reproductive system: a midsagittal section of the male pelvis with the right testis opened in its scrotum.

The pelvis is built whole and in the round - bladder, prostate, urethra, penis, pubic bones, rectum - and the viewer's
own cut-away takes the midsagittal section, so every midline organ is sectioned by one plane and the whole of the
external genitalia comes back when the cut is switched off. The right testis and its coverings are opened by a second,
parasagittal cut through the middle of the testis (a stepped section, as in an atlas plate): the scrotal wall shows
all of its layers in profile, the testis its tunica albuginea, septa, lobules of seminiferous tubules and the
mediastinum with the rete, and the spermatic cord is laid open on its way up to the inguinal canal, which is shown in
a patch of the lower abdominal wall with both of its rings.

Two magnified insets stand beside the pelvis: a seminiferous tubule in cross-section, cell by cell, and a
spermatozoon, both sectioned by the same midline plane.

Units: 1 unit = 10 cm. +y is superior, -x anterior, the section plane is z = 0 and the right half of the body lies at
z < 0 (the patient faces the viewer's left, as in a textbook sagittal section).
"""
import math

import numpy as np

from .base import Part
from .geometry import Mesh, ellipsoid as ell_mesh, frames, smooth_path, tube
from .kit import Volume, ellipsoid, round_cone
from .organic import Sweep, noise_field, warp_parts, worley
from .sdf import BIG, fbm3, smin

# ----------------------------------------------------------------------------------------------- landmarks
ZT = -0.20                                          # parasagittal plane through the right testis
HALF = 0.004                                        # interior parts are built only for the half the section shows
T_C = np.array([-0.29, -0.515, ZT])                  # testis centre
_TILT = math.radians(20.0)                          # upper pole tilted forwards
T_U = np.array([math.cos(_TILT), math.sin(_TILT), 0.0])        # posterior (towards the epididymis)
T_V = np.array([-math.sin(_TILT), math.cos(_TILT), 0.0])       # long axis, upwards
T_W = np.array([0.0, 0.0, 1.0])
T_R = (0.13, 0.22, 0.11)                            # testis radii along u, v, w

P_C = np.array([-0.14, 0.02, 0.0])                  # prostate centre
_pa = np.array([-0.06, -0.274, 0.0])
P_A = _pa / np.linalg.norm(_pa)                     # prostate axis, base -> apex
P_B = np.array([-P_A[1], P_A[0], 0.0])              # posterior
if P_B[0] < 0:
    P_B = -P_B
P_HALF = 0.14

B_C = np.array([-0.06, 0.40, 0.0])                  # bladder centre

# centreline of the penis shaft (root under the symphysis -> tip of the glans)
S_CTRL = [(-0.20, -0.212), (-0.30, -0.205), (-0.40, -0.197), (-0.49, -0.192), (-0.575, -0.212), (-0.635, -0.262),
          (-0.672, -0.335), (-0.688, -0.43), (-0.694, -0.53), (-0.696, -0.60), (-0.697, -0.66), (-0.697, -0.715)]
Y_CORONA = -0.595

# right spermatic cord, deep inguinal ring -> top of the testis
CORD_CTRL = [(-0.462, 0.545, -0.585), (-0.500, 0.500, -0.480), (-0.535, 0.445, -0.370), (-0.560, 0.385, -0.285),
             (-0.566, 0.300, -0.256), (-0.537, 0.140, -0.236), (-0.462, -0.020, -0.222), (-0.372, -0.150, -0.212),
             (-0.300, -0.283, -0.205)]
DEEP_RING = np.array(CORD_CTRL[0])
SUP_RING = np.array(CORD_CTRL[3])

# colours
C = {
    "bone": "#e4d5b7", "disc": "#bfcdd3", "bladder": "#cf8a7e", "bl_muc": "#e7a39c", "ureter": "#d9a38e",
    "pz": "#c7795a", "cz": "#9c5747", "tz": "#e0b07e", "afs": "#b89890", "caps": "#e3cbbb", "coll": "#e58f8c",
    "urethra": "#e3858a", "meatus": "#d9737c", "sv": "#d9ab86", "amp": "#e6d2b4", "ejac": "#f0c56a",
    "int_sph": "#b85a50", "ext_sph": "#a8403a", "bug": "#e3c79c", "spong": "#b3525c", "bulb": "#a94a55",
    "cav": "#9c3f4b", "tun_cav": "#ece4d8", "glans": "#c8646f", "buck": "#e5dccd", "sfasc": "#d9c0ab",
    "pskin": "#c6977f", "prepuce": "#c98a82", "frenulum": "#d97f85", "susp": "#e9e0cf", "deep_art": "#d0342c",
    "dors_art": "#d23a31", "dors_vein": "#4a62a8", "sup_vein": "#5b72b3", "dors_nerve": "#f0cf62",
    "isch": "#a93f38", "bulbosp": "#b04740", "perbody": "#c4968a", "permem": "#e0d6c3", "rectum": "#e2a699",
    "perit": "#e6d3cf", "rectus": "#b1443d", "skin": "#b98470", "dartos": "#b86d5f", "esf": "#e2d6c2",
    "crem": "#b8473c", "isf": "#e9dfcf", "tv": "#e6dfe3", "alb": "#e8eaec", "septa": "#efe9df",
    "lobule": "#b8735c", "tubules": "#efcf98", "medi": "#ece2d2", "rete": "#f2d7ad", "effer": "#e7c28f",
    "epi_h": "#c98a6c", "epi_b": "#c28064", "epi_t": "#bb775c", "ductus": "#e6d0bc", "t_art": "#c93a33",
    "pamp": "#4d64a6", "gf_nerve": "#efd06a", "ext_obl": "#eceee8", "int_obl": "#ad4a41", "tf": "#e3d8c6",
    "ing_lig": "#efe7d6", "sup_ring": "#f0e6d0", "deep_ring": "#ece0cc", "canal": "#b9d3e0", "ie_art": "#cc3a31",
    "ie_vein": "#4b63a5", "t_vein": "#4d64a6", "fat": "#e8cf8c",
    # insets
    "bm": "#c9738f", "sertoli": "#efc6cf", "s_nuc": "#b8a2cf", "sg": "#8c62b0", "sc1": "#a77cc4",
    "sc2": "#c09ad2", "sd": "#dbbde2", "sz": "#4f3c86", "nuc": "#4a3478", "leydig": "#e58a64", "cap": "#cf3a37",
    "acro": "#8cc0de", "sp_nuc": "#4f3a8e", "neck": "#e3be52", "mito": "#d97a3e", "axo": "#f1ead7",
    "fib": "#d6cab5", "end": "#e8e0cc",
}


# ----------------------------------------------------------------------------------------------- helpers
def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def _rot(u, v, w):
    """Rotation whose columns are the local axes (sdf.ellipsoid convention)."""
    return np.column_stack([_unit(u), _unit(v), _unit(w)])


def _sstep(x, a, b):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


class _Grid:
    """A voxel grid on which fields are combined with plain numpy and then polygonised part by part."""

    def __init__(self, lo, hi, vox):
        self.v = Volume(lo, hi, vox)
        self.vox = vox
        self.shape = self.v.shape
        self.x, self.y, self.z = self.v.axes()

    def full(self, d):
        return np.ascontiguousarray(np.broadcast_to(np.asarray(d, np.float32), self.shape))

    def tube(self, path, r, margin=0.0):
        """Distance to a swept tube, valid out to `margin` beyond its surface (BIG further away)."""
        t = self.v.copy(np.full(self.shape, BIG, np.float32))
        t.tube(np.asarray(path, np.float32), np.asarray(r, np.float32) + margin)
        t.d += margin
        return t.d

    def shapes(self, shapes, margin=0.0):
        t = self.v.copy(np.full(self.shape, BIG, np.float32))
        for fn, lo, hi in shapes:
            t.add((fn, np.asarray(lo) - margin, np.asarray(hi) + margin))
        return t.d

    def mesh(self, d, smooth=0.7, step=1):
        return self.v.copy(self.full(d)).mesh(smooth, step=step)


def _halves(g, d, smooth=0.7):
    """Mesh a field at full resolution on the sectioned (right) side and coarsely on the left, which is only ever
    seen from outside with the cut-away off."""
    return g.mesh(np.maximum(d, g.z - 0.002), smooth).extend(g.mesh(np.maximum(d, 0.002 - g.z), smooth, step=2))


def _I(*ds):
    """Intersection of fields."""
    out = ds[0]
    for d in ds[1:]:
        out = np.maximum(out, d)
    return out


def _U(*ds):
    out = ds[0]
    for d in ds[1:]:
        out = np.minimum(out, d)
    return out


def _mirror(mesh):
    out = Mesh()
    f = np.array([1.0, 1.0, -1.0], np.float32)
    for p, n, i in mesh.parts:
        out.parts.append(((p * f).astype(np.float32), (n * f).astype(np.float32), i[:, ::-1].copy()))
    return out


def _both(mesh):
    return Mesh().extend(mesh).extend(_mirror(mesh))


def _resample(path, n):
    path = np.asarray(path, float)
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.linspace(0.0, s[-1], n)
    return np.stack([np.interp(t, s, path[:, c]) for c in range(3)], -1)


def _curve(ctrl, n=120, z=None):
    pts = np.array([(p[0], p[1], z if z is not None else (p[2] if len(p) > 2 else 0.0)) for p in ctrl], float)
    return _resample(smooth_path(pts, max(n * 2, 60)), n)


def _tubes(paths, radii, seg=10):
    m = Mesh()
    for p, r in zip(paths, radii):
        m.extend(tube(np.asarray(p, float), r, seg))
    return m


def _ell_fn(c, radii, R=None):
    return ellipsoid(c, radii, R)[0]


def _sheet(P, N, h):
    """Closed slab of half-thickness h around a mid-surface grid P (nu, nv, 3) with unit normals N."""
    from .geometry import _grid_indices
    from .cells import orient_outward
    nu, nv = P.shape[:2]
    top = (P + N * h).reshape(-1, 3)
    bot = (P - N * h).reshape(-1, 3)
    n = nu * nv
    tri = [_grid_indices(nu, nv), _grid_indices(nu, nv, flip=True) + n]
    a = np.arange(n).reshape(nu, nv)
    for edge in (a[0, :], a[-1, :], a[:, 0], a[:, -1]):
        e0, e1 = edge[:-1], edge[1:]
        tri.append(np.stack([e0, e1, e1 + n], 1))
        tri.append(np.stack([e0, e1 + n, e0 + n], 1))
    m = Mesh().add(np.vstack([top, bot]), np.vstack(tri))
    # make every face wind the same way as the top surface's first face, then orient the whole shell outward
    return orient_outward(_unify(m))


def _unify(mesh):
    """Consistently orient a closed triangle mesh by walking across shared edges."""
    pos, nrm, idx = mesh.arrays()
    idx = idx.copy()
    from collections import defaultdict, deque
    edges = defaultdict(list)
    for t, (a, b, c) in enumerate(idx):
        for u, v in ((a, b), (b, c), (c, a)):
            edges[(min(u, v), max(u, v))].append(t)
    seen = np.zeros(len(idx), bool)
    for start in range(len(idx)):
        if seen[start]:
            continue
        seen[start] = True
        q = deque([start])
        while q:
            t = q.popleft()
            a, b, c = idx[t]
            for u, v in ((a, b), (b, c), (c, a)):
                for o in edges[(min(u, v), max(u, v))]:
                    if o == t or seen[o]:
                        continue
                    oa, ob, oc = idx[o]
                    same = (oa, ob) == (u, v) or (ob, oc) == (u, v) or (oc, oa) == (u, v)
                    if same:
                        idx[o] = idx[o][::-1]
                    seen[o] = True
                    q.append(o)
    return Mesh().add(pos, idx)


def _poly2d(px, py, poly):
    """Signed distance (approximate, exact on edges) to a convex polygon in the xy plane, counter-clockwise."""
    d = None
    n = len(poly)
    for i in range(n):
        a, b = np.asarray(poly[i], float), np.asarray(poly[(i + 1) % n], float)
        e = b - a
        nx, ny = e[1], -e[0]
        ln = math.hypot(nx, ny)
        di = ((px - a[0]) * nx + (py - a[1]) * ny) / ln
        d = di if d is None else np.maximum(d, di)
    return d


# ----------------------------------------------------------------------------------------------- shared shapes
def _prostate_fields(x, y, z):
    """(distance to the prostate surface, s along the axis towards the apex, q posterior, z) at grid points."""
    px, py = x - P_C[0], y - P_C[1]
    s = px * P_A[0] + py * P_A[1]
    q = px * P_B[0] + py * P_B[1]
    t = np.clip(s / P_HALF, -1.2, 1.2)
    rl = 0.132 - 0.052 * t
    rq = np.where(q > 0, 0.08, 0.094) - 0.018 * t
    k = np.sqrt((s / P_HALF) ** 2 + (q / rq) ** 2 + (z / rl) ** 2)
    return (k - 1.0) * 0.085, s, q


def _penis_frame():
    S = _curve(S_CTRL, 220, z=0.0)
    T = np.gradient(S, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True)
    D = np.stack([T[:, 1], -T[:, 0], np.zeros(len(S))], -1)
    D /= np.linalg.norm(D, axis=1, keepdims=True)
    ic = int(np.argmin(np.abs(S[:, 1] - Y_CORONA) + (S[:, 0] > -0.6) * 9))
    return S, T, D, ic


def _urethra_path():
    S, T, D, ic = _penis_frame()
    top = [(-0.112, 0.205), (-0.121, 0.16), (-0.131, 0.10), (-0.143, 0.04), (-0.152, -0.01), (-0.160, -0.05),
           (-0.172, -0.09), (-0.186, -0.125), (-0.197, -0.17), (-0.206, -0.212), (-0.214, -0.248), (-0.232, -0.272),
           (-0.265, -0.281)]
    sp = S - D * 0.065
    k = np.where(sp[:, 0] < -0.30)[0][0]
    pen = [tuple(sp[i, :2]) for i in range(k, ic - 12, 12)]
    tip = S[-1]
    tail = [tuple(S[ic - 4, :2] - D[ic - 4, :2] * 0.045), tuple(S[ic + 18, :2] - D[ic + 18, :2] * 0.028),
            tuple(tip[:2] - D[-1, :2] * 0.01 - T[-1, :2] * 0.006)]
    U = _curve(top + pen + tail, 420, z=0.0)
    y_apex, y_bulb = -0.125, -0.243
    L = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(U, axis=0), axis=1))])
    ro = np.empty(len(U))
    ri = np.empty(len(U))
    i_apex = int(np.argmin(np.abs(U[:, 1] - y_apex) + (U[:, 0] < -0.25) * 9))
    i_bulb = int(np.argmin(np.abs(U[:, 1] - y_bulb) + (U[:, 0] < -0.25) * 9))
    i_gl = int(np.argmin(np.linalg.norm(U - S[ic], axis=1)))
    for i in range(len(U)):
        if i <= i_apex:
            ro[i], ri[i] = 0.021, 0.0115
        elif i <= i_bulb:
            ro[i], ri[i] = 0.016, 0.0075
        elif L[i] - L[i_bulb] < 0.13:
            ro[i], ri[i] = 0.024, 0.0155
        else:
            ro[i], ri[i] = 0.0165, 0.0095
    # fossa navicularis widens in the glans, then the meatus narrows again
    rel = (L - L[i_gl]) / (L[-1] - L[i_gl])
    fossa = np.exp(-((rel - 0.45) / 0.25) ** 2) * (rel > -0.2)
    ro += fossa * 0.004
    ri += fossa * 0.0045
    end = rel > 0.82
    ro[end] -= (rel[end] - 0.82) * 0.02
    ri[end] -= (rel[end] - 0.82) * 0.018
    # smooth the calibre steps
    k = np.ones(9) / 9
    ro = np.convolve(np.pad(ro, 4, mode="edge"), k, mode="valid")
    ri = np.convolve(np.pad(ri, 4, mode="edge"), k, mode="valid")
    return U, ro, ri, i_apex, i_bulb


def _colliculus():
    """Seminal colliculus: an ellipsoid on the posterior wall of the prostatic urethra."""
    U, ro, ri, _, _ = _urethra_path()
    i = int(np.argmin(np.abs(U[:, 1] + 0.035) + (U[:, 0] < -0.25) * 9))
    t = _unit(U[i + 1] - U[i - 1])
    b = _unit(np.array([-t[1], t[0], 0.0]))
    if b[0] < 0:
        b = -b
    c = U[i] + b * 0.0125
    return ellipsoid(c, (0.009, 0.028, 0.0085), _rot(b, t, (0, 0, 1)))


def _ejac_path(side=-1):
    zc = -0.0035 if side < 0 else 0.009
    pts = [(-0.035, 0.132, 0.034 * side), (-0.062, 0.105, 0.02 * side), (-0.092, 0.063, zc + 0.004 * side),
           (-0.118, 0.02, zc), (-0.134, -0.012, zc), (-0.140, -0.032, zc)]
    return _curve(pts, 60)


# ----------------------------------------------------------------------------------------------- the build
def build_male():
    parts = []

    def add(mesh, name, group, color, desc, cat="organ", alpha=1.0, clip=True, label=True, detail=None):
        if mesh.parts:
            parts.append(Part(name, group, C.get(color, color), mesh, desc, alpha=alpha, category=cat, clip=clip,
                              label=label, detail=detail))

    _pelvis(add)
    _urinary_and_glands(add)
    _penis(add)
    _perineum(add)
    _testis(add)
    _cord_and_coverings(add)
    _inguinal_wall(add)
    # the insets stay crisp; the anatomy gets one gentle shared warp so nothing looks turned on a lathe
    n_main = len(parts)
    _tubule_inset(add)
    _sperm_inset(add)
    warp_parts(parts[:n_main], noise_field((0.004, 0.004, 0.0025), 3.2, 2, seed=91))
    return parts


# ----------------------------------------------------------------------------------------------- pelvis context
G_PEL = "Pelvis (context)"


def _pubis_field(g):
    x, y, z = g.x, g.y, g.z
    ax = np.array([-math.sin(math.radians(18)), math.cos(math.radians(18))])
    c = np.array([-0.40, 0.14])
    px, py = x - c[0], y - c[1]
    a = px * ax[0] + py * ax[1]
    b = px * ax[1] - py * ax[0]
    oval = np.sqrt((a / 0.215) ** 2 + (b / 0.072) ** 2) - 1.0
    body = np.maximum(oval * 0.07, np.maximum(z + 0.016, -0.15 - z))             # z in [-0.15, -0.016]
    sup = g.tube(_curve([(-0.45, 0.30, -0.12), (-0.43, 0.33, -0.25), (-0.38, 0.35, -0.36), (-0.31, 0.36, -0.45)], 30),
                 np.linspace(0.055, 0.045, 30), 0.03)
    inf = g.tube(_curve([(-0.35, 0.00, -0.10), (-0.30, -0.10, -0.15), (-0.20, -0.20, -0.20), (-0.08, -0.28, -0.24),
                         (0.02, -0.315, -0.265), (0.08, -0.33, -0.285)], 40), np.linspace(0.04, 0.036, 40), 0.03)
    d = smin(smin(body, sup, 0.04), inf, 0.05)
    d = np.maximum(d, z + 0.016)
    d = d + 0.003 * fbm3(x * 24, y * 24, z * 24, 1.0, 2, 3)
    return d


def _pelvis(add):
    # pubic bones (right built, left mirrored) and the interpubic disc in the midline
    g = _Grid((-0.56, -0.40, -0.52), (0.10, 0.42, 0.0), 0.0082)
    pub = g.mesh(_pubis_field(g), 0.8)
    add(pub, "Pubic bone & ischiopubic ramus", G_PEL, "bone", DESC["pubis"], "bone")
    g = _Grid((-0.52, -0.12, -0.03), (-0.26, 0.40, 0.03), 0.0035)
    ax = np.array([-math.sin(math.radians(18)), math.cos(math.radians(18))])
    px, py = g.x + 0.40, g.y - 0.14
    a = px * ax[0] + py * ax[1]
    b = px * ax[1] - py * ax[0]
    oval = (np.sqrt((a / 0.205) ** 2 + (b / 0.066) ** 2) - 1.0) * 0.066
    add(g.mesh(np.maximum(oval, np.abs(g.z) - 0.017), 0.8), "Pubic symphysis (interpubic disc)", G_PEL, "disc",
        DESC["symphysis"], "cartilage")

    # rectum and anal canal (translucent context)
    rp = _curve([(0.092, -0.375), (0.060, -0.29), (0.036, -0.215), (0.06, -0.10), (0.10, 0.0), (0.155, 0.11),
                 (0.235, 0.255), (0.30, 0.44), (0.335, 0.64), (0.34, 0.90)], 100, z=0.0)
    t = np.linspace(0, 1, len(rp))
    r_out = np.interp(t, [0, 0.12, 0.2, 0.3, 0.45, 0.6, 0.8, 1], [0.028, 0.035, 0.05, 0.105, 0.115, 0.1, 0.085, 0.08])
    from .kit import tube_shell
    add(tube_shell(rp, r_out, r_out - 0.013, 48), "Rectum & anal canal", G_PEL, "rectum", DESC["rectum"], "mucosa",
        alpha=0.55)

    # peritoneum over the bladder and down into the rectovesical pouch
    curve = _curve([(-0.50, 0.72), (-0.36, 0.665), (-0.20, 0.628), (-0.06, 0.628), (0.07, 0.59), (0.135, 0.50),
                    (0.155, 0.40), (0.175, 0.33), (0.20, 0.32), (0.215, 0.38), (0.235, 0.52), (0.262, 0.70),
                    (0.275, 0.94)], 110, z=0.0)
    tg = np.gradient(curve, axis=0)
    tg /= np.linalg.norm(tg, axis=1, keepdims=True)
    nrm = np.stack([-tg[:, 1], tg[:, 0], np.zeros(len(tg))], -1)
    zs = np.linspace(-0.16, 0.16, 33)
    P = np.repeat(curve[:, None, :], len(zs), 1)
    P[..., 2] = zs[None, :]
    P[..., 1] -= 1.1 * zs[None, :] ** 2
    N = np.repeat(nrm[:, None, :], len(zs), 1)
    add(_sheet(P, N, 0.0045), "Peritoneum (rectovesical pouch)", G_PEL, "perit", DESC["peritoneum"], "serosa",
        alpha=0.5)

    # rectus abdominis (right and left) above the pubic crest
    g = _Grid((-0.60, 0.30, -0.14), (-0.42, 0.92, 0.006), 0.005)
    # a strap of muscle, thick in the middle and thinning to its tendon on the pubic crest; the medial edge
    # reaches the midline (linea alba) so the section cuts it
    xf = -0.515 - 0.025 * _sstep(g.y, 0.35, 0.9)
    ax = 0.012 + 0.018 * _sstep(g.y, 0.345, 0.55)
    az = 0.036 + 0.03 * _sstep(g.y, 0.35, 0.9)
    zc = 0.004 - az
    d = (np.sqrt(((g.x - xf) / ax) ** 2 + ((g.z - zc) / az) ** 4) - 1.0) * ax
    d = _I(d, 0.345 - g.y, g.y - 0.90)
    d = d + 0.0018 * fbm3(g.x * 50, g.y * 8, g.z * 50, 1.0, 2, 8)
    add(_both(g.mesh(d, 0.7)), "Rectus abdominis", G_PEL, "rectus", DESC["rectus"], "muscle")


# ----------------------------------------------------------------------------------------------- bladder, prostate
G_URI = "Bladder & urethra"
G_GLAND = "Prostate & seminal glands"


def _bladder_outer(g):
    e = _ell_fn(B_C, (0.20, 0.21, 0.235))(g.x, g.y, g.z)
    neck = round_cone((-0.085, 0.25, 0.0), (-0.115, 0.17, 0.0), 0.11, 0.035)[0](g.x, g.y, g.z)
    return smin(e, neck, 0.06)


def _urinary_and_glands(add):
    U, ro, ri, i_apex, i_bulb = _urethra_path()
    coll = _colliculus()
    ej_r, ej_l = _ejac_path(-1), _ejac_path(1)
    ureter_r = _curve([(0.31, 0.95, -0.30), (0.25, 0.66, -0.33), (0.18, 0.44, -0.305), (0.12, 0.32, -0.225),
                       (0.07, 0.255, -0.15), (0.025, 0.232, -0.105)], 120)
    u_ro = np.full(len(ureter_r), 0.02)
    u_ro[-12:] = np.linspace(0.02, 0.016, 12)

    # ---- bladder
    g = _Grid((-0.29, 0.12, -0.27), (0.18, 0.64, 0.27), 0.006)
    outer = _bladder_outer(g)
    inner = outer + 0.021
    pro, _, _ = _prostate_fields(g.x, g.y, g.z)
    uro = g.tube(U, ro)
    uri = g.tube(U, ri)
    ure = _U(g.tube(ureter_r, u_ro), g.tube(ureter_r * [1, 1, -1], u_ro))
    isph = _I(g.tube(U[:70], 0.041), 0.105 - g.y, g.y - 0.215)
    trig = _sstep(g.x, -0.14, -0.08) * _sstep(-g.y, -0.30, -0.24)
    f = fbm3(g.x * 15, g.y * 15, g.z * 15, 1.0, 2, 5) * 6.0
    rug = 0.0032 * np.log1p(np.exp(f)) * (1 - trig)
    lumen = _U(inner + 0.0085 + rug, uri)
    wall = _I(outer, -inner, -pro, -isph, -ure, -uro)
    wall = wall - 0.002 * fbm3(g.x * 30, g.y * 30, g.z * 30, 1.0, 2, 6) * (wall > -0.01)
    add(_halves(g, wall, 0.8), "Urinary bladder (detrusor wall)", G_URI, "bladder", DESC["bladder"], "muscle")
    mucosa = _I(inner, -lumen, -pro, -isph, -ure, -uro, g.z - HALF)
    add(g.mesh(mucosa, 0.6), "Bladder mucosa & trigone", G_URI, "bl_muc",
        DESC["bl_mucosa"], "mucosa")
    add(_both(_ureter_mesh(ureter_r, u_ro)), "Ureter (entering the bladder)", G_URI, "ureter", DESC["ureter"], "mucosa")

    # ---- prostate block: zones, capsule, urethra, colliculus, ejaculatory ducts, sphincters, bulbourethral glands
    g = _Grid((-0.30, -0.245, -0.215), (0.0, 0.215, 0.215), 0.0044)
    pro, s, q = _prostate_fields(g.x, g.y, g.z)
    inner = pro + 0.0065
    uro = g.tube(U, ro)
    uri = g.tube(U, ri)
    col = g.shapes([coll])
    ejr = g.tube(ej_r, 0.0068)
    ejl = g.tube(ej_l, 0.0055)
    ej = _U(ejr, ejl)
    # urethra position along the prostate axis, for the zones
    us = (U[:, 0] - P_C[0]) * P_A[0] + (U[:, 1] - P_C[1]) * P_A[1]
    uq = (U[:, 0] - P_C[0]) * P_B[0] + (U[:, 1] - P_C[1]) * P_B[1]
    sel = (us > -0.2) & (us < 0.2) & (U[:, 0] > -0.26)
    order = np.argsort(us[sel])
    qu = np.interp(s, us[sel][order], uq[sel][order])
    dq = q - qu
    s_col = float(np.interp(-0.035, U[sel][order][:, 1][::-1], us[sel][order][::-1]))
    s_afs = dq + 0.03
    rad = np.sqrt(dq ** 2 + (g.z * 0.8) ** 2)
    s_tz = _I(s - s_col, -0.118 - s, rad - 0.075, dq - 0.034, -s_afs)
    wcz = 0.02 + 0.075 * np.clip((s_col - s) / (s_col + P_HALF), 0.0, 1.0)
    s_cz = _I(s - s_col - 0.008, 0.03 - dq, np.sqrt(((dq - 0.055) * 0.7) ** 2 + g.z ** 2) - wcz)
    # prostatic glands: small cavities, only near the section plane where they show
    rng = np.random.default_rng(12)
    voids = []
    for _ in range(260):
        c = P_C + P_A * rng.uniform(-0.13, 0.13) + P_B * rng.uniform(-0.08, 0.08)
        c[2] = rng.uniform(-0.03, 0.01)
        r = rng.uniform(0.0045, 0.0085)
        voids.append(ellipsoid(c, (r, r * rng.uniform(1.0, 1.8), r), _rot(P_B, P_A, (0, 0, 1))))
    vd = g.shapes(voids)
    vd = np.maximum(vd, -(inner + 0.012))              # keep them off the capsule
    cut = _U(uro, ej, col)
    d_afs = _I(inner, s_afs, -cut)
    d_tz = _I(inner, s_tz, -cut, -vd)
    d_cz = _I(inner, s_cz, -s_afs, -s_tz, -cut, -vd)
    d_pz = _I(inner, -s_afs, -s_tz, -s_cz, -cut, -vd)
    add(g.mesh(_I(d_pz, g.z - HALF), 0.6), "Prostate - peripheral zone", G_GLAND, "pz", DESC["pz"], "gland")
    add(g.mesh(_I(d_cz, g.z - HALF), 0.6), "Prostate - central zone", G_GLAND, "cz", DESC["cz"], "gland")
    add(g.mesh(_I(d_tz, g.z - HALF), 0.6), "Prostate - transition zone", G_GLAND, "tz", DESC["tz"], "gland")
    add(g.mesh(_I(d_afs, g.z - HALF), 0.6), "Anterior fibromuscular stroma", G_GLAND, "afs", DESC["afs"], "muscle")
    add(g.mesh(_I(pro, -inner, -uro, -ej), 0.5), "Prostatic capsule", G_GLAND, "caps", DESC["capsule"], "fascia")
    add(g.mesh(_I(col, -uri), 0.5), "Seminal colliculus (verumontanum)", G_GLAND, "coll", DESC["colliculus"], "mucosa")
    ej_in = _I(ej, -uri)
    add(g.mesh(ej_in, 0.5), "Ejaculatory duct", G_GLAND, "ejac", DESC["ejac"], "gland")

    # sphincters and bulbourethral glands
    isph = _I(g.tube(U[:70], 0.041), 0.105 - g.y, g.y - 0.215, -uro)
    add(g.mesh(isph, 0.6), "Internal urethral sphincter (bladder neck)", G_URI, "int_sph", DESC["int_sph"], "muscle")
    # bulbourethral glands: pea-sized lobulated glands posterolateral to the membranous urethra, above the membrane
    rng = np.random.default_rng(4)
    bug_c = np.array((-0.150, -0.198, -0.03))
    bug_sh = [ellipsoid(bug_c, (0.014, 0.013, 0.012))]
    bug_sh += [ellipsoid(bug_c + rng.normal(0, 0.0055, 3), (0.0075, 0.0075, 0.0075)) for _ in range(9)]
    bug = g.shapes(bug_sh)
    bug = bug - 0.0015 * np.abs(fbm3(g.x * 150, g.y * 150, g.z * 150, 1.0, 2, 6))
    esph = _I(g.tube(U[i_apex - 40:i_bulb + 4], 0.044), -0.214 - g.y, g.y + 0.085, -uro, -(pro - 0.003),
              -(bug - 0.002))
    esph = esph - 0.002 * fbm3(g.x * 50, g.y * 12, g.z * 50, 1.0, 2, 3)
    add(_halves(g, esph, 0.7), "External urethral sphincter", G_URI, "ext_sph", DESC["ext_sph"], "muscle")
    duct = _curve([bug_c + (-0.004, -0.008, 0.004), (-0.172, -0.232, -0.026), (-0.205, -0.262, -0.018),
                   (-0.25, -0.279, -0.01), (-0.30, -0.279, -0.005), (-0.33, -0.276, -0.003)], 40)
    bug_m = g.mesh(bug, 0.6).extend(tube(duct, 0.0036, 8))
    bug_mesh = Mesh().extend(bug_m).extend(_mirror(bug_m))
    add(bug_mesh, "Bulbourethral (Cowper) gland", G_GLAND, "bug", DESC["bug"], "gland")

    # urethra, cut into its three parts (plus the orifice in the glans), from two grids
    g1 = _Grid((-0.34, -0.31, -0.03), (-0.08, 0.215, 0.03), 0.0027)
    d1 = _I(g1.tube(U, ro), -g1.tube(U, ri), -g1.shapes([coll]))
    d1 = np.maximum(d1, -(g1.x + 0.33))
    y_apex, y_bulb = U[i_apex, 1], U[i_bulb, 1]
    top = np.maximum(d1, -(g1.y - y_apex))
    add(g1.mesh(_I(top, g1.z - HALF), 0.5), "Prostatic urethra", G_URI, "urethra", DESC["u_pro"], "mucosa")
    mem = _I(d1, g1.y - y_apex, -(g1.y - y_bulb))
    add(g1.mesh(_I(mem, g1.z - HALF), 0.5), "Membranous (intermediate) urethra", G_URI, "urethra", DESC["u_mem"],
        "mucosa")
    sp1 = _I(d1, g1.y - y_bulb)
    g2 = _Grid((-0.735, -0.735, -0.03), (-0.31, -0.24, 0.03), 0.0033)
    d2 = _I(g2.tube(U, ro), -g2.tube(U, ri), g2.x + 0.33)
    tip = U[-1]
    near_tip = np.sqrt((g2.x - tip[0]) ** 2 + (g2.y - tip[1]) ** 2 + g2.z ** 2) - 0.022
    sp = g1.mesh(_I(sp1, g1.z - HALF), 0.5).extend(g2.mesh(_I(d2, -near_tip, g2.z - HALF), 0.5))
    add(sp, "Spongy (penile) urethra", G_URI, "urethra", DESC["u_spon"], "mucosa")
    orifice = _I(near_tip, g2.tube(U, ro + 0.004), -g2.tube(U, ri))
    add(g2.mesh(orifice, 0.5), "External urethral orifice", G_URI, "meatus", DESC["meatus"], "mucosa")

    # ---- seminal vesicles, ampullae
    g = _Grid((-0.07, 0.07, -0.25), (0.20, 0.36, 0.25), 0.0036)
    # a coiled tube packed into a flattened pouch: an envelope with deep knobbly sacculations
    sva, svb = np.array([0.025, 0.105, -0.055]), np.array([0.13, 0.285, -0.21])
    sv = round_cone(sva, svb, 0.022, 0.034)[0](g.x, g.y, g.z)
    sv = sv - 0.011 * np.abs(fbm3(g.x * 38, g.y * 38, g.z * 38, 1.0, 2, 1)) + 0.004
    sv = sv + 0.012 * np.maximum((g.x - (0.02 + 0.55 * (g.y - 0.1))) * 4.0, 0.0)        # flattened front to back
    exc = _curve([sva, (0.0, 0.118, -0.045), (-0.035, 0.132, -0.034)], 20)
    sv = smin(sv, g.tube(exc, 0.008), 0.01)
    amp_path = _curve([(0.14, 0.33, -0.16), (0.118, 0.30, -0.105), (0.08, 0.24, -0.075), (0.045, 0.19, -0.058),
                       (0.01, 0.15, -0.045), (-0.02, 0.135, -0.036), (-0.035, 0.132, -0.034)], 90)
    tt = np.linspace(0, 1, len(amp_path))
    amp_r = 0.009 + 0.0075 * np.sin(tt * math.pi) ** 0.6 * (1 + 0.35 * np.sin(tt * 38))
    amp = g.tube(amp_path, amp_r)
    pro, _, _ = _prostate_fields(g.x, g.y, g.z)
    sv = np.maximum(sv, -(pro - 0.002))
    amp = np.maximum(np.maximum(amp, -(pro - 0.002)), -(sv - 0.001))
    add(_both(g.mesh(np.maximum(sv, g.z), 0.6)), "Seminal vesicle (seminal gland)", G_GLAND, "sv", DESC["sv"], "gland")
    add(_both(g.mesh(np.maximum(amp, g.z), 0.6)), "Ampulla of ductus deferens", G_GLAND, "amp", DESC["ampulla"],
        "muscle")


def _ureter_mesh(path, r_out):
    from .kit import tube_shell
    return tube_shell(path, r_out, 0.0065, 24)


# ----------------------------------------------------------------------------------------------- penis
G_PEN = "Penis"


def _cav_path(side):
    S, T, D, ic = _penis_frame()
    k = np.where(S[:, 0] < -0.30)[0][0]
    shaft = S[k:ic + 8] + D[k:ic + 8] * 0.03
    shaft[:, 2] = 0.05 * side
    crus = [(0.03, -0.30, 0.182 * side), (-0.03, -0.283, 0.166 * side), (-0.12, -0.25, 0.132 * side),
            (-0.22, -0.212, 0.09 * side), (-0.28, -0.184, 0.058 * side)]
    ctrl = [np.array(c) for c in crus] + list(shaft[::14]) + [shaft[-1]]
    path = _curve(ctrl, 260)
    L = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))])
    r = 0.055 * np.ones(len(path))
    r = np.minimum(r, 0.022 + L * 0.28)          # the crus tapers to its attachment
    tip = L[-1] - L
    r = np.minimum(r, 0.028 + tip * 0.9)
    return path, r


def _penis_core(g, cut_right=True):
    """Fields shared by the penile layers."""
    S, T, D, ic = _penis_frame()
    cav = []
    for side in (-1, 1):
        p, r = _cav_path(side)
        cav.append((p, r))
    k = np.where(S[:, 0] < -0.30)[0][0]
    sp = S[k - 4:ic + 2] - D[k - 4:ic + 2] * 0.065
    sp_r = np.full(len(sp), 0.04)
    sp_r[-20:] = np.linspace(0.04, 0.05, 20)
    return S, T, D, ic, cav, sp, sp_r


def _glans_field(g, S, T, D, ic, grow=0.0):
    """Glans: a cap on the end of the shaft, widest at the corona."""
    base = S[ic]
    ax = _unit(S[-1] - S[ic])
    L = np.linalg.norm(S[-1] - base)
    px, py, pz = g.x - base[0], g.y - base[1], g.z - base[2]
    a = px * ax[0] + py * ax[1] + pz * ax[2]
    rx, ry, rz = px - a * ax[0], py - a * ax[1], pz - a * ax[2]
    rho = np.sqrt(rx ** 2 + ry ** 2 + rz ** 2)
    t = np.clip(a / L, 0.0, 1.0)
    prof = 0.114 * np.clip(1.0 - t, 0.0, 1.0) ** 0.62 * (1.0 + 0.22 * t) * (1.0 - 0.25 * np.exp(-(t / 0.08) ** 2))
    prof = prof + 0.01 * np.exp(-((t - 0.09) / 0.06) ** 2)                   # the corona projects
    d = rho - prof - grow
    d = np.maximum(d, 0.045 * (1.0 - rho / 0.1) - a - grow)          # concave base over the corpora tips
    return d, a, rho


def _penis(add):
    g = _Grid((-0.835, -0.765, -0.155), (-0.29, -0.02, 0.155), 0.0048)
    _shaft(add, g)


def _shaft(add, g):
    S, T, D, ic, cav, sp, sp_r = _penis_core(g)
    U, ro, ri, _, _ = _urethra_path()
    uro = g.tube(U, ro)
    right = g.x + 0.30                                # this grid holds the shaft only (x < -0.30)
    cav_d = [g.tube(p, r + 0.008, 0.06) for p, r in cav]
    cav_t = [g.tube(p, r) for p, r in cav]
    spong = g.tube(sp, sp_r, 0.06)
    gl, ga, grho = _glans_field(g, S, T, D, ic)
    dors = S + D * 0.083
    bundle = g.tube(dors[:ic], 0.022, 0.05)
    core = _U(cav_d[0], cav_d[1], spong, bundle, gl)
    # the corona plane
    n_c = T[ic]
    corona = (g.x - S[ic, 0]) * n_c[0] + (g.y - S[ic, 1]) * n_c[1]

    # cavernous spaces near the section planes
    def spaces(path, r, z0, z1, n, seed):
        rr = np.random.default_rng(seed)
        sh = []
        for _ in range(n):
            i = rr.integers(8, len(path) - 8)
            c = path[i].copy()
            off = rr.normal(size=2) * r[i] * 0.45
            c[0] += off[0]
            c[1] += off[1]
            c[2] = rr.uniform(z0, z1)
            rad = rr.uniform(0.004, 0.0075)
            sh.append(ellipsoid(c, (rad * 1.3, rad * 1.3, rad)))
        return sh

    cavR, cavL = cav
    # right corpus cavernosum: opened by a parasagittal cut through its axis
    art_r = cavR[0].copy()
    art_r[:, 2] = -0.035
    art_path = art_r[60:-10]
    vr = g.shapes(spaces(cavR[0][60:], cavR[1][60:], -0.042, -0.03, 170, 1))
    art_d = g.tube(art_path, 0.0048)
    cav_tissue_r = _I(cav_t[0], -_U(vr, art_d - 0.0015), g.z + 0.035, right)
    add(g.mesh(cav_tissue_r, 0.6), "Corpus cavernosum (erectile tissue)", G_PEN, "cav", DESC["cav"], "organ")
    tun_r = _I(cav_d[0], -cav_t[0], g.z + 0.035, right, -(gl - 0.002))
    # the left corpus is only ever seen whole, from outside, with the cut-away off: one coarse solid is enough
    tun_l = _I(cav_d[1], 0.002 - g.z, right, -(gl - 0.002))
    add(g.mesh(tun_r, 0.55).extend(g.mesh(tun_l, 0.6, step=2)), "Tunica albuginea of corpora cavernosa", G_PEN,
        "tun_cav", DESC["tun_cav"], "fascia")
    art_l = cavL[0].copy()
    art_l[:, 2] = 0.043
    add(Mesh().extend(tube(art_path, 0.0048, 10)).extend(tube(art_l[60:-10], 0.0045, 10)), "Deep artery of penis",
        G_PEN, "deep_art", DESC["deep_art"], "artery")

    # corpus spongiosum (shaft) and glans
    vs = g.shapes(spaces(sp, sp_r, -0.012, 0.004, 90, 2))
    spong_t = _I(spong, -uro, -vs, corona - 0.03, right, -gl)
    add(g.mesh(_I(spong_t, g.z - HALF), 0.6), "Corpus spongiosum", G_PEN, "spong", DESC["spong"], "organ")
    vg = g.shapes(spaces(S[ic:], np.full(len(S) - ic, 0.08), -0.012, 0.004, 60, 3))
    glans = _I(gl, -uro, -(cav_d[0] + 0.002), -(cav_d[1] + 0.002), -vg)
    add(g.mesh(glans, 0.6), "Glans penis", G_PEN, "glans", DESC["glans"], "organ")

    # dorsal neurovascular bundle
    k = np.where(S[:, 0] < -0.30)[0][0]
    vein = S[k - 10:ic - 4] + D[k - 10:ic - 4] * 0.087
    vein = np.vstack([np.array([[-0.25, -0.078, 0.0], [-0.28, -0.098, 0.0]]), vein])
    add(tube(_curve(vein, 160), 0.0095, 14), "Deep dorsal vein of penis", G_PEN, "dors_vein", DESC["dd_vein"], "vein")
    arts, nerves = [], []
    for side in (-1, 1):
        a = S[k - 6:ic - 2] + D[k - 6:ic - 2] * 0.084
        a[:, 2] = 0.022 * side
        a = np.vstack([np.array([[-0.24, -0.12, 0.05 * side]]), a])
        arts.append(_curve(a, 140))
        n = S[k - 6:ic + 6] + D[k - 6:ic + 6] * 0.077
        n[:, 2] = 0.043 * side
        n = np.vstack([np.array([[-0.22, -0.13, 0.08 * side]]), n])
        nerves.append(_curve(n, 140))
    add(_tubes(arts, [0.0052, 0.0052], 10), "Dorsal artery of penis", G_PEN, "dors_art", DESC["dors_art"], "artery")
    add(_tubes(nerves, [0.0062, 0.0062], 10), "Dorsal nerve of penis", G_PEN, "dors_nerve", DESC["dors_nerve"], "nerve")

    # fascial and skin coverings
    # Buck's fascia and the skin are swept round the shaft: each section is the envelope of the three corpora
    # and the dorsal bundle, so the coverings bridge the grooves between them the way fascia does
    k0 = int(np.where(S[:, 0] < -0.30)[0][0])
    k1 = int(np.where(S[:, 0] < -0.345)[0][0])
    buck = _covering(S, D, k0, ic + 1, 0.0015, 0.0095, seed=3)
    add(buck, "Deep (Buck) fascia of penis", G_PEN, "buck", DESC["buck"], "fascia")
    sup_v = S[k:ic] + D[k:ic] * 0.117
    add(tube(_curve(sup_v, 120), 0.0055, 10), "Superficial dorsal vein of penis", G_PEN, "sup_vein", DESC["sup_vein"],
        "vein")
    skin = _covering(S, D, k1, ic + 1, 0.012, 0.034, seed=7, rough=0.0012)
    add(skin, "Skin & superficial (dartos) fascia of penis", G_PEN, "pskin", DESC["pskin"], "skin")
    # prepuce: a double fold of skin over the glans, open at the preputial orifice
    gp, ga, grho = _glans_field(g, S, T, D, ic, grow=0.0)
    Lg = np.linalg.norm(S[-1] - S[ic])
    shell = _I(gp - 0.036, -(gp - 0.013), -corona - 0.006)
    orifice = _I(ga - (Lg - 0.006), grho - 0.017)
    prep = _I(shell, -orifice, ga - (Lg + 0.02))
    prep = _U(prep, _I(core - 0.034, -(core - 0.013), -corona - 0.007 + 0.0 * g.x, corona - 0.012))
    add(g.mesh(prep, 0.5), "Prepuce (foreskin)", G_PEN, "prepuce", DESC["prepuce"], "skin")
    # frenulum: a median fold from the inner prepuce to the underside of the glans
    ven = -((g.x - S[ic, 0]) * D[ic, 0] + (g.y - S[ic, 1]) * D[ic, 1])
    fren = _I(np.abs(g.z) - 0.0045, gp - 0.018, -gl + 0.0, -corona, ga - Lg * 0.85, 0.03 - ven)
    add(g.mesh(fren, 0.5), "Frenulum of prepuce", G_PEN, "frenulum", DESC["frenulum"], "skin")
    # suspensory ligament: a midline fan from the front of the symphysis to the dorsum
    poly = [(-0.60, -0.107), (-0.465, -0.088), (-0.445, -0.06), (-0.47, 0.035), (-0.515, 0.02)]
    poly = poly[::-1] if _area(poly) < 0 else poly
    lig = _I(_poly2d(g.x, g.y, poly), np.abs(g.z) - 0.007, -(core - 0.009))
    add(g.mesh(lig, 0.5), "Suspensory ligament of penis", G_PEN, "susp", DESC["susp"], "ligament")


def _covering(S, D, i0, i1, off_in, off_out, seed=0, rough=0.0, n_theta=84):
    """A sleeve round the shaft between two offsets from the envelope of the corpora (analytic ray-circle hits)."""
    sel = np.unique(np.linspace(i0, i1 - 1, max(12, (i1 - i0) * 2 // 3)).astype(int))
    path = S[sel]
    D = D[sel]
    i0, i1 = 0, len(sel)
    sw = Sweep(path, n_theta, len(path))
    circles = [(0.03, 0.05, 0.063), (0.03, -0.05, 0.063), (-0.065, 0.0, 0.04), (0.083, 0.0, 0.022)]
    dirs = sw.nrm[None, :, :] * np.cos(sw.T)[..., None] + sw.bi[None, :, :] * np.sin(sw.T)[..., None]
    Dn = D[i0:i1][None, :, :]
    du = np.sum(dirs * Dn, -1)
    dz = dirs[..., 2]
    r = np.zeros(sw.T.shape)
    for cu, cz, R in circles:
        b = cu * du + cz * dz
        disc = b * b - (cu * cu + cz * cz - R * R)
        r = np.maximum(r, np.where(disc > 0, b + np.sqrt(np.maximum(disc, 0.0)), 0.0))
    wob = rough * fbm3(np.cos(sw.T) * 9.0, np.sin(sw.T) * 9.0, sw.S * 60.0, 1.0, 2, seed) if rough else 0.0
    return sw.shell(r + off_in, r + off_out + wob)


def _area(poly):
    p = np.asarray(poly)
    return 0.5 * float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]))


# ----------------------------------------------------------------------------------------------- root & perineum
G_PER = "Root of penis & perineum"


def _perineum(add):
    g = _Grid((-0.31, -0.40, -0.26), (0.10, -0.075, 0.26), 0.0052)
    S, T, D, ic, cav, sp, sp_r = _penis_core(g)
    U, ro, ri, _, i_bulb = _urethra_path()
    uro = g.tube(U, ro)
    left = -(g.x + 0.30)                              # this grid holds x > -0.30
    bulb_e = _ell_fn((-0.165, -0.292, 0.0), (0.125, 0.048, 0.062))(g.x, g.y, g.z)
    bulb = smin(bulb_e, g.tube(sp[:40], sp_r[:40]), 0.03)
    rng = np.random.default_rng(8)
    vs = []
    for _ in range(70):
        c = np.array([rng.uniform(-0.27, -0.07), rng.uniform(-0.31, -0.275), rng.uniform(-0.012, 0.004)])
        r = rng.uniform(0.004, 0.007)
        vs.append(ellipsoid(c, (r * 1.4, r, r)))
    vd = g.shapes(vs)
    bulb_t = _I(bulb, -uro, -vd, left)
    add(g.mesh(bulb_t, 0.6), "Bulb of penis", G_PER, "bulb", DESC["bulb"], "organ")
    crura = [g.tube(p, r + 0.008) for p, r in cav]
    cr_t = _I(_U(crura[0], crura[1]), left)
    add(_halves(g, cr_t, 0.6), "Crus of penis", G_PER, "cav", DESC["crus"], "organ")
    # ischiocavernosus over each crus, bulbospongiosus over the bulb
    isc = []
    for (p, r), cr in zip(cav, crura):
        sh = _I(cr - 0.018, -(cr - 0.002), -(g.x + 0.21), g.x - 0.035)
        isc.append(sh)
    isc = _U(*isc) - 0.0015 * fbm3(g.x * 20, g.y * 60, g.z * 60, 1.0, 2, 2)
    add(_halves(g, isc, 0.6), "Ischiocavernosus", G_PER, "isch", DESC["isch"], "muscle")
    fib = 0.0025 * np.sin((g.x * 0.6 + np.abs(g.z)) * 260.0)
    thick = 0.018 * _sstep(-g.x, -0.01, 0.06) * _sstep(g.x, -0.31, -0.25) + 0.002
    bs = _I(bulb - thick + fib * thick / 0.018, -(bulb - 0.002), g.y + 0.268)
    add(g.mesh(bs, 0.6), "Bulbospongiosus", G_PER, "bulbosp", DESC["bulbosp"], "muscle")
    pb = _ell_fn((0.005, -0.318, 0.0), (0.042, 0.034, 0.03))(g.x, g.y, g.z)
    pb = _I(pb, -(bulb - 0.018))
    add(g.mesh(pb, 0.6), "Perineal body", G_PER, "perbody", DESC["perbody"], "fascia")
    # perineal membrane: an inclined sheet spanning the pubic arch above the root of the penis
    a0, a1 = np.array([-0.30, -0.168]), np.array([-0.02, -0.308])
    e = _unit(a1 - a0)
    nrm = np.array([-e[1], e[0]])
    along = (g.x - a0[0]) * e[0] + (g.y - a0[1]) * e[1]
    off = (g.x - a0[0]) * nrm[0] + (g.y - a0[1]) * nrm[1]
    Lm = np.linalg.norm(a1 - a0)
    half_w = 0.06 + 0.13 * np.clip(along / Lm, 0, 1)
    mem = _I(np.abs(off) - 0.0055, -along, along - Lm, np.abs(g.z) - half_w, -(uro - 0.0), -(bulb - 0.002),
             -(_U(*crura) - 0.002))
    add(g.mesh(mem, 0.5), "Perineal membrane", G_PER, "permem", DESC["permem"], "fascia")


# ----------------------------------------------------------------------------------------------- testis
G_TES = "Testis & epididymis"
G_SCR = "Scrotum & coverings"
G_CORD = "Spermatic cord & inguinal canal"


def _local(x, y, z):
    px, py, pz = x - T_C[0], y - T_C[1], z - T_C[2]
    return px * T_U[0] + py * T_U[1], px * T_V[0] + py * T_V[1], pz


def _world(u, v, w):
    return T_C + T_U * u + T_V * v + T_W * w


def _epi_path():
    pts = [(0.075, 0.205, -0.004), (0.118, 0.17, -0.02), (0.14, 0.09, -0.042), (0.146, 0.0, -0.05),
           (0.14, -0.09, -0.045), (0.118, -0.175, -0.03), (0.085, -0.212, -0.01)]
    return _curve([_world(*p) for p in pts], 120)


def _epi_radius(n):
    t = np.linspace(0, 1, n)
    return np.interp(t, [0, 0.12, 0.3, 0.5, 0.75, 0.9, 1.0], [0.042, 0.05, 0.03, 0.026, 0.027, 0.036, 0.03])


def _testis_d(x, y, z):
    return _ell_fn(T_C, T_R, _rot(T_U, T_V, T_W))(x, y, z)


def _ductus_path():
    """Ductus deferens from the tail of the epididymis up the cord, through the canal, over the ureter."""
    start = [_world(0.085, -0.214, -0.004), _world(0.12, -0.215, 0.02), _world(0.172, -0.16, 0.03),
             _world(0.178, -0.02, 0.028), _world(0.17, 0.12, 0.02), _world(0.14, 0.235, 0.012)]
    cord = _cord_path()
    idx = np.linspace(len(cord) - 1, 0, 14).astype(int)
    frame_t, frame_n, frame_b = frames(cord)
    up = [cord[i] + _cord_offset(i, cord, frame_n, frame_b, 0.018, 2.4) for i in idx[1:]]
    pelvic = [(-0.425, 0.55, -0.565), (-0.36, 0.545, -0.53), (-0.22, 0.525, -0.465), (-0.06, 0.49, -0.40),
              (0.07, 0.46, -0.33), (0.13, 0.43, -0.28), (0.15, 0.38, -0.22), (0.14, 0.33, -0.16)]
    return _curve(start + up + [np.array(p) for p in pelvic], 420)


def _cord_path():
    return _curve(CORD_CTRL, 160)


def _cord_offset(i, path, fn, fb, r, ang):
    return fn[i] * r * math.cos(ang) + fb[i] * r * math.sin(ang)


def _testis(add):
    lo = T_C - np.array([0.17, 0.30, 0.16])
    hi = T_C + np.array([0.22, 0.31, 0.012])
    g = _Grid(lo, hi, 0.0045)
    u, v, w = _local(g.x, g.y, g.z)
    cut = g.z - ZT                                     # keep w <= 0
    td = _testis_d(g.x, g.y, g.z)
    inner = td + 0.012
    alb = _I(td, -inner, cut)
    # mediastinum along the posterior border, rete testis inside it
    med = _ell_fn(_world(0.103, 0.04, 0.0), (0.032, 0.135, 0.036), _rot(T_U, T_V, T_W))(g.x, g.y, g.z)
    med = np.maximum(med, inner - 0.004)
    n1 = fbm3(g.x * 90, g.y * 90, g.z * 90, 1.0, 2, 41)
    rete = _I(med + 0.005, np.abs(n1) - 0.11, cut)
    # septa fanning from the mediastinum to the tunica (seen in the plane of section)
    F = np.array([0.17, 0.03])
    ang = np.arctan2(v - F[1], u - F[0])
    ang = np.where(ang < 0, ang + 2 * math.pi, ang)
    rr = np.sqrt((u - F[0]) ** 2 + (v - F[1]) ** 2)
    rng = np.random.default_rng(5)
    phis = np.linspace(math.pi - 1.25, math.pi + 1.25, 13) + rng.uniform(-0.05, 0.05, 13)
    wav = 0.03 * fbm3(g.x * 18, g.y * 18, g.z * 4, 1.0, 2, 3)
    dang = np.full(g.shape, 9.0, np.float32)
    for phi in phis:
        np.minimum(dang, np.abs(ang + wav - phi), out=dang)
    sep = _I(dang * rr - 0.0029, inner, -(med - 0.002), -(w + 0.045), cut, u - 0.1)
    lob_region = _I(inner, -(sep - 0.0), -(med - 0.0))
    # seminiferous tubules: where two independent noise fields both cross zero - a tangle of convoluted tubes
    # seminiferous tubules: a packed mosaic of rounded, slightly elongated profiles (a Worley field - each cell a
    # loop of tubule) with thin interstitium between them; only built near the plane of section, where it shows
    slab = (w > -0.045) & (lob_region < 0.004)
    pts = np.stack(np.broadcast_arrays(g.x, g.y, g.z), -1)[slab]
    sz = 0.026
    warp_p = pts + 0.35 * sz * np.stack([fbm3(pts[:, 0] * 14, pts[:, 1] * 14, pts[:, 2] * 14, 1.0, 2, 71 + c)
                                         for c in range(3)], -1)
    f1, f2 = worley(warp_p, sz, seed=9, stretch=(1.0, 1.5, 1.0))
    tv_ = np.full(g.shape, 1.0, np.float32)
    tv_[slab] = np.maximum(0.0026 - (f2 - f1) * 0.5, f1 - sz * 0.72)
    tub = _I(tv_, lob_region + 0.0025, -(w + 0.04), cut)
    # tubuli recti: short straight tubes from the lobule apices into the rete
    tr = []
    for v0 in np.linspace(-0.07, 0.15, 7):
        tr.append(round_cone(_world(0.058, v0 * 1.1, -0.012), _world(0.098, v0 * 0.85 + 0.006, -0.012), 0.0045, 0.0045))
    trd = g.shapes(tr)
    rete = _U(rete, _I(trd, cut))
    lob = _I(lob_region, -tub, -trd, cut)
    add(g.mesh(alb, 0.55), "Tunica albuginea of testis", G_TES, "alb", DESC["alb"], "fascia")
    add(g.mesh(_I(sep, -tub), 0.5), "Septa of testis", G_TES, "septa", DESC["septa"], "fascia")
    add(g.mesh(lob, 0.55), "Lobules of testis (interstitial tissue)", G_TES, "lobule", DESC["lobule"], "gland")
    add(g.mesh(tub, 0.5), "Seminiferous tubules", G_TES, "tubules", DESC["tubules"], "gland")
    add(g.mesh(_I(med, -rete, cut, -trd), 0.55), "Mediastinum testis", G_TES, "medi", DESC["medi"], "fascia")
    add(g.mesh(_I(rete, inner - 0.001), 0.5), "Rete testis & tubuli recti", G_TES, "rete", DESC["rete"], "gland")

    # epididymis: head, body, tail - a lumpy mass of coiled duct; efferent ductules run up into the head
    ep = _epi_path()
    epd = g.tube(ep, _epi_radius(len(ep)), 0.03)
    lumps = 0.0055 * np.abs(fbm3(g.x * 75, g.y * 75, g.z * 75, 1.0, 2, 17))
    epd = epd - lumps + 0.002
    epd = np.maximum(epd, -(td - 0.004))
    eff = []
    for i in range(9):
        t0 = i / 8.0
        a = _world(0.07 + 0.03 * t0, 0.155 + 0.02 * math.sin(i), -0.006 - 0.035 * t0)
        b = _world(0.10 + 0.025 * t0, 0.215 - 0.01 * t0, -0.01 - 0.03 * t0)
        axis = b - a
        ln = np.linalg.norm(axis)
        e1 = _unit(np.cross(axis, [0, 0, 1.0]))
        e2 = _unit(np.cross(axis, e1))
        tt = np.linspace(0, 1, 50)
        rad = 0.009 * np.sin(tt * math.pi)
        ph = tt * 2 * math.pi * 2.6 + i
        pts = a + np.outer(tt, axis) + np.outer(rad * np.cos(ph), e1) + np.outer(rad * np.sin(ph), e2)
        eff.append(pts)
        del ln
    effd = _U(*[g.tube(p, 0.0052) for p in eff])
    effd = np.maximum(effd, -(td + 0.0))
    effd = _I(effd, cut, -(med - 0.0))
    head = _I(epd, 0.125 - v, cut, -effd)
    tail = _I(epd, v + 0.14, cut)
    body = _I(epd, v - 0.125, -(v + 0.14), cut)
    add(g.mesh(head, 0.6), "Head of epididymis", G_TES, "epi_h", DESC["epi_h"], "gland")
    add(g.mesh(body, 0.6), "Body of epididymis", G_TES, "epi_b", DESC["epi_b"], "gland")
    add(g.mesh(tail, 0.6), "Tail of epididymis", G_TES, "epi_t", DESC["epi_t"], "gland")
    add(g.mesh(effd, 0.45), "Efferent ductules", G_TES, "effer", DESC["effer"], "gland")
    # tunica vaginalis, parietal layer: a serous sac round the front and sides, open behind (the bare area)
    # tunica vaginalis, parietal layer: a serous sac round the front and sides, open behind (the bare area)
    g = _Grid(lo - 0.03, hi + np.array([0.03, 0.03, 0.0]), 0.0052)
    u, v, w = _local(g.x, g.y, g.z)
    ed = g.tube(ep, _epi_radius(len(ep)), 0.04) - 0.0035
    core = _U(_testis_d(g.x, g.y, g.z), ed)
    tv = _I(core - 0.027, -(core - 0.0175), u - 0.155, g.z - ZT)
    add(g.mesh(tv, 0.5), "Tunica vaginalis (parietal layer)", G_SCR, "tv", DESC["tv"], "serosa")


def _cord_and_coverings(add):
    cord = _cord_path()
    ft, fn_, fb = frames(cord)
    n = len(cord)
    # ---- contents: ductus deferens, testicular artery, pampiniform plexus, genital branch of genitofemoral nerve
    duct = _ductus_path()
    add(tube(duct, 0.0135, 14), "Ductus deferens (vas deferens)", G_CORD, "ductus", DESC["ductus"], "muscle")
    art = cord + np.array([_cord_offset(i, cord, fn_, fb, 0.006 * math.sin(i * 0.4), 1.0) for i in range(n)])
    art = np.vstack([np.array([[-0.20, 0.95, -0.55], [-0.33, 0.72, -0.60], [-0.44, 0.58, -0.60]]), art,
                     [_world(0.14, 0.17, -0.015), _world(0.13, 0.10, -0.035), _world(0.118, 0.03, -0.042)]])
    art = _curve(art, 220)
    art += 0.004 * np.stack([np.sin(np.arange(len(art)) * 0.5), np.cos(np.arange(len(art)) * 0.37), 0 * art[:, 0]], -1)
    add(tube(art, 0.0052, 10), "Testicular artery", G_CORD, "t_art", DESC["t_art"], "artery")
    veins = []
    for k in range(9):
        a0 = 2 * math.pi * k / 9
        pts = []
        for i in range(n):
            s = i / (n - 1)
            conv = _sstep(s, 0.05, 0.4)            # the plexus funnels into one testicular vein in the canal
            r = 0.022 * conv + 0.001
            ang = a0 + 7.0 * s + 0.6 * math.sin(s * 31 + k) + 0.3 * math.sin(s * 57 + 2 * k)
            r = r * (1.0 + 0.35 * math.sin(s * 41 + k * 1.3))
            pts.append(cord[i] + _cord_offset(i, cord, fn_, fb, r, ang) + fb[i] * 0.004 * conv)
        tail = [_world(0.155 + 0.01 * math.cos(k), 0.14 - 0.03 * k, -0.02 + 0.012 * math.sin(k * 1.7))]
        veins.append(_curve(np.vstack([pts, tail]), 170))
    vein_up = _curve([(-0.19, 0.95, -0.53), (-0.32, 0.73, -0.58), (-0.45, 0.575, -0.585), cord[0], cord[3]], 80)
    add(_tubes(veins + [vein_up], [0.0062] * 9 + [0.0085], 9), "Pampiniform plexus & testicular vein", G_CORD, "pamp",
        DESC["pamp"], "vein")
    gfn = cord + np.array([_cord_offset(i, cord, fn_, fb, 0.036, -1.9) for i in range(n)])
    gfn = np.vstack([np.array([[-0.40, 0.62, -0.62]]), gfn[:-10]])
    add(tube(_curve(gfn, 120), 0.0032, 8), "Genital branch of genitofemoral nerve", G_CORD, "gf_nerve",
        DESC["gf_nerve"], "nerve")

    # ---- coverings of the cord and testis (built in two grids: scrotal sac and the cord above it)
    zc_y = cord[:, 1][::-1]
    zc_z = cord[:, 2][::-1]
    t_d = ft[0]
    t_s = ft[np.argmin(np.linalg.norm(cord - SUP_RING, axis=1))]
    i_mid = int(np.argmin(np.linalg.norm(cord - (DEEP_RING * 0.45 + SUP_RING * 0.55), axis=1)))
    t_m = ft[i_mid]
    rc = np.interp(np.arange(n), [0, 40, 60, n - 1], [0.030, 0.034, 0.041, 0.042])
    y_win = 0.33
    layers = [("Internal spermatic fascia", 0.0, 0.0105, DEEP_RING, t_d, "isf", "isf", "fascia"),
              ("Cremaster muscle & fascia", 0.0125, 0.0265, cord[i_mid], t_m, "crem", "crem", "muscle"),
              ("External spermatic fascia", 0.0285, 0.039, SUP_RING, t_s, "esf", "esf", "fascia")]
    meshes = {name: Mesh() for name, *_ in layers}
    grids = [((-0.57, -0.83, -0.44), (-0.0, -0.14, -0.04), 0.0074, True),
             ((-0.64, -0.145, -0.66), (-0.30, 0.60, -0.14), 0.0085, False)]
    for lo, hi, vox, sac in grids:
        g = _Grid(lo, hi, vox)
        cd = g.tube(cord, rc, 0.08)
        if sac:
            td = _testis_d(g.x, g.y, g.z)
            ep = _epi_path()
            ed = g.tube(ep, _epi_radius(len(ep)), 0.1)
            core = _U(td, ed) - 0.028
            S0 = smin(core, cd, 0.05)
            S0 = np.maximum(S0, g.y + 0.14)
        else:
            S0 = np.maximum(cd, -(g.y + 0.14))
        zc = np.interp(g.y, zc_y, zc_z)
        window = _I(-(g.z - np.where(g.y < -0.20, ZT, zc)), g.y - y_win)       # removed where negative
        stripes = np.sin((g.y + 0.35 * g.x + 0.3 * g.z + 0.01 * fbm3(g.x * 30, g.y * 30, g.z * 30, 1, 2, 4))
                         * 2 * math.pi / 0.03)
        for name, r0, r1, org, tdir, *_ in layers:
            start = (g.x - org[0]) * tdir[0] + (g.y - org[1]) * tdir[1] + (g.z - org[2]) * tdir[2]
            d = _I(S0 - r1, -(S0 - r0), -start, -window)
            if "Cremaster" in name:
                d = np.maximum(d, (-stripes - 0.15) * 0.004)
            meshes[name].extend(g.mesh(d, 0.5))
    for name, r0, r1, org, tdir, col, key, cat in layers:
        add(meshes[name], name, G_SCR, col, DESC[key], cat)

    # ---- scrotal skin and dartos: one bag for both testes, opened on the right
    g = _Grid((-0.57, -0.86, -0.47), (0.0, -0.13, 0.47), 0.0074)
    lobe_c = T_C + np.array([0.02, -0.01, 0.0])
    bag = smin(_ell_fn((lobe_c[0], lobe_c[1], -0.19), (0.235, 0.29, 0.215))(g.x, g.y, g.z),
               _ell_fn((lobe_c[0], lobe_c[1], 0.19), (0.235, 0.29, 0.215))(g.x, g.y, g.z), 0.07)
    wr = 0.0045 * np.sin((g.y + 0.25 * g.x + 0.03 * fbm3(g.x * 14, g.y * 14, g.z * 14, 1, 2, 9)) * 2 * math.pi / 0.032)
    raphe = 0.006 * np.exp(-(g.z / 0.01) ** 2)
    outer = bag + wr * _sstep(-g.y, 0.2, 0.3) + raphe
    cordd = g.tube(cord, rc + 0.04)
    opened = np.maximum(ZT - g.z, g.z)              # the medial part of the right half is taken away
    skin = _I(outer, -(bag + 0.013), -opened, -cordd, g.z)
    # the left half stays closed: a solid bag is enough there (its inside is never seen)
    gl_ = _Grid((-0.57, -0.86, -0.004), (0.0, -0.13, 0.47), 0.0095)
    bag_l = smin(_ell_fn((lobe_c[0], lobe_c[1], -0.19), (0.235, 0.29, 0.215))(gl_.x, gl_.y, gl_.z),
                 _ell_fn((lobe_c[0], lobe_c[1], 0.19), (0.235, 0.29, 0.215))(gl_.x, gl_.y, gl_.z), 0.07)
    wr_l = 0.0045 * np.sin((gl_.y + 0.25 * gl_.x + 0.03 * fbm3(gl_.x * 14, gl_.y * 14, gl_.z * 14, 1, 2, 9))
                           * 2 * math.pi / 0.032)
    left_bag = _I(bag_l + wr_l * _sstep(-gl_.y, 0.2, 0.3) + 0.006 * np.exp(-(gl_.z / 0.01) ** 2), 0.003 - gl_.z)
    dartos = _I(bag + 0.0145, -(bag + 0.031), -opened, -cordd, g.z)     # hidden under the skin on the left
    add(g.mesh(skin, 0.55).extend(gl_.mesh(left_bag, 0.6)), "Scrotal skin", G_SCR, "skin", DESC["scr_skin"], "skin")
    add(g.mesh(dartos, 0.5), "Dartos muscle & fascia", G_SCR, "dartos", DESC["dartos"], "muscle")


def _inguinal_wall(add):
    g = _Grid((-0.66, 0.30, -0.82), (-0.37, 0.86, -0.07), 0.0062)
    x, y, z = g.x, g.y, g.z
    xw = -0.50 + 0.14 * np.clip(-z - 0.28, 0.0, None) + 0.0 * y          # plane of the transversalis fascia
    tp = np.array([-0.49, 0.335, -0.24])
    lat = np.array([-0.40, 0.52, -0.82])
    y_lig = tp[1] + (lat[1] - tp[1]) * np.clip((-z + tp[2]) / (-lat[2] + tp[2]), 0.0, 1.0)
    z_edge = -0.10 - 0.08 * _sstep(y, 0.35, 0.85)
    cord = _cord_path()
    cd = g.tube(cord, 0.034, 0.05)
    # external oblique aponeurosis with the superficial ring
    xa = xw - 0.056
    sr = SUP_RING + np.array([0.0, 0.012, 0.0])
    fib = _unit(np.array([0.0, -0.45, 1.0]))            # the ring is a slit along the aponeurotic fibres
    ra = (y - sr[1]) * fib[1] + (z - sr[2]) * fib[2]
    rb = (y - sr[1]) * fib[2] - (z - sr[2]) * fib[1]
    ring = np.sqrt((ra / 0.036) ** 2 + (rb / 0.022) ** 2) - 1.0
    def window(inset):
        q = ((y - 0.60) / (0.27 - inset)) ** 4 + ((z + 0.44) / (0.37 - inset)) ** 4
        return _I((q - 1.0) * 0.08, z - z_edge)
    apo = _I(np.abs(x - xa) - 0.0045, y_lig - y, window(0.0))
    apo = apo + 0.0015 * fbm3(x * 30, y * 30, z * 30, 1, 2, 5)
    rim = _I(np.abs(x - xa) - 0.0065, -(ring * 0.022), ring * 0.022 - 0.0085, y_lig - y)
    add(g.mesh(_I(apo, -(ring * 0.022) + 0.0), 0.5), "External oblique aponeurosis", G_CORD, "ext_obl", DESC["ext_obl"],
        "tendon", alpha=0.45)
    add(g.mesh(rim, 0.5), "Superficial inguinal ring", G_CORD, "sup_ring", DESC["sup_ring"], "tendon")
    # internal oblique & transversus: muscle arching over the canal, conjoint tendon medially
    y_arch = np.interp(z, [-0.82, -0.66, -0.52, -0.40, -0.30, -0.20, -0.07], [0.50, 0.60, 0.56, 0.50, 0.44, 0.36, 0.35])
    mus = _I(np.abs(x - (xw - 0.028)) - 0.018, y_arch - y, window(0.03), -(cd - 0.004))
    mus = mus - 0.002 * fbm3(x * 40, y * 90, z * 90, 1, 2, 12)
    add(g.mesh(mus, 0.6), "Internal oblique & transversus abdominis", G_CORD, "int_obl", DESC["int_obl"], "muscle")
    # transversalis fascia with the deep ring
    dr = DEEP_RING
    dring = np.sqrt((y - dr[1]) ** 2 + (z - dr[2]) ** 2) - 0.03
    tf = _I(np.abs(x - (xw - 0.003)) - 0.0042, y_lig - 0.02 - y, window(0.055), -dring)
    add(g.mesh(tf, 0.5), "Transversalis fascia", G_CORD, "tf", DESC["tf"], "fascia", alpha=0.8)
    drim = _I(np.abs(x - (xw - 0.003)) - 0.006, -dring, dring - 0.009)
    add(g.mesh(drim, 0.5), "Deep inguinal ring", G_CORD, "deep_ring", DESC["deep_ring"], "fascia")
    # inguinal ligament: the rolled-under lower border of the aponeurosis
    lig = _curve([tp, (-0.47, 0.37, -0.35), (-0.44, 0.43, -0.52), (-0.41, 0.50, -0.72), (-0.40, 0.52, -0.80)], 80)
    for i in range(len(lig)):
        zz = lig[i, 2]
        lig[i, 0] = -0.50 + 0.14 * max(-zz - 0.28, 0.0) - 0.05
        lig[i, 1] = tp[1] + (lat[1] - tp[1]) * min(max((-zz + tp[2]) / (-lat[2] + tp[2]), 0.0), 1.0) + 0.004
    add(tube(lig, 0.011, 12), "Inguinal ligament", G_CORD, "ing_lig", DESC["ing_lig"], "ligament")
    # the canal itself, as a faint sleeve between the rings
    ic0 = int(np.argmin(np.linalg.norm(cord - SUP_RING, axis=1)))
    canal = cord[:ic0 + 3]
    add(tube(canal, 0.046, 20), "Inguinal canal", G_CORD, "canal", DESC["canal"], "other", alpha=0.22)
    # inferior epigastric vessels, medial to the deep ring
    ie = _curve([(-0.40, 0.49, -0.64), (-0.43, 0.53, -0.56), (-0.452, 0.60, -0.47), (-0.47, 0.70, -0.36),
                 (-0.48, 0.82, -0.24)], 90)
    for i in range(len(ie)):
        zz = ie[i, 2]
        ie[i, 0] = -0.50 + 0.14 * max(-zz - 0.28, 0.0) + 0.012
    add(tube(ie, 0.0075, 10), "Inferior epigastric artery", G_CORD, "ie_art", DESC["ie_art"], "artery")
    v1 = ie + np.array([0.004, 0.0, 0.011])
    v2 = ie + np.array([0.004, 0.0, -0.011])
    add(_tubes([v1, v2], [0.0058, 0.0058], 9), "Inferior epigastric veins", G_CORD, "ie_vein", DESC["ie_vein"], "vein")


# ----------------------------------------------------------------------------------------------- insets
G_TUB = "Seminiferous tubule (inset, ~x200)"
G_SP = "Spermatozoon (inset, ~x1300)"
TI = np.array([0.80, 0.37, 0.0])


def _tubule_inset(add):
    rng = np.random.default_rng(77)
    R_IN, R_BM = 0.186, 0.199
    R_LUM = 0.056
    Z0, Z1 = -0.055, 0.042
    cells = {k: [] for k in ("sg", "sc1", "sc2", "sd", "esd")}

    def put(kind, r, rad, count, zs, squash=(1.0, 1.0, 1.0), jitter=0.2):
        for zc in zs:
            off = rng.uniform(0, 2 * math.pi)
            for i in range(count):
                a = off + 2 * math.pi * (i + rng.uniform(-jitter, jitter)) / count
                rr = r + rng.uniform(-0.006, 0.006)
                c = TI + np.array([rr * math.cos(a), rr * math.sin(a), zc + rng.uniform(-0.006, 0.006)])
                cells[kind].append((c, rad * rng.uniform(0.9, 1.1), a, squash))

    put("sg", 0.172, 0.0125, 34, [0.0], (0.75, 1.1, 1.0))
    put("sc1", 0.140, 0.0175, 22, [0.0], jitter=0.25)
    put("sc2", 0.113, 0.0125, 6, [0.0], jitter=0.4)
    put("sd", 0.097, 0.0092, 32, [0.0], jitter=0.3)
    put("esd", 0.076, 0.0055, 30, [0.0], (1.9, 0.75, 0.75), jitter=0.3)
    # cell meshes
    mesh = {k: Mesh() for k in cells}
    nuc = Mesh()
    frac = {"sg": 0.62, "sc1": 0.58, "sc2": 0.55, "sd": 0.55, "esd": 0.8}
    for kind, lst in cells.items():
        for c, rad, a, sq in lst:
            radial = np.array([math.cos(a), math.sin(a), 0.0])
            tang = np.array([-math.sin(a), math.cos(a), 0.0])
            R = np.column_stack([radial, tang, [0, 0, 1.0]])
            radii = np.array([rad * sq[0], rad * sq[1], rad * sq[2]])
            mesh[kind].extend(ell_mesh((0, 0, 0), radii, res=8).transformed(R, c))
            nr = radii * frac[kind]
            if kind == "esd":
                nr = radii * np.array([0.75, 0.7, 0.7])
            nuc.extend(ell_mesh((0, 0, 0), nr, res=6).transformed(R, c))
    # spermatozoa in the lumen: heads near the Sertoli apices, tails streaming along the lumen
    heads = Mesh()
    tails = []
    for i in range(26):
        a = 2 * math.pi * i / 26 + rng.uniform(-0.1, 0.1)
        radial = np.array([math.cos(a), math.sin(a), 0.0])
        zc = rng.uniform(-0.045, 0.03)
        hc = TI + radial * rng.uniform(0.045, 0.058) + np.array([0, 0, zc])
        R = np.column_stack([radial, [-radial[1], radial[0], 0], [0, 0, 1.0]])
        heads.extend(ell_mesh((0, 0, 0), (0.0065, 0.0042, 0.0028), res=7).transformed(R, hc))
        pts = [hc - radial * 0.006]
        d = -radial
        for k in range(26):
            d = _unit(d + rng.normal(0, 0.25, 3) * np.array([1, 1, 0.6]) + np.array([0, 0, 0.12 * np.sign(zc + 1e-3)]))
            p = pts[-1] + d * 0.0045
            rho = np.linalg.norm(p[:2] - TI[:2])
            if rho > R_LUM - 0.006:
                p[:2] = TI[:2] + (p[:2] - TI[:2]) * (R_LUM - 0.006) / rho
            p[2] = np.clip(p[2], Z0 + 0.004, Z1 - 0.004)
            pts.append(p)
        tails.append(_curve(pts, 50))
    sz = Mesh().extend(heads).extend(_tubes(tails, [0.0013] * len(tails), 6))

    # Sertoli cytoplasm: the whole epithelium, split into cells by thin gaps; the germ cells are nested inside it
    # (the cut-away draws the innermost part on the plane, so each germ cell shows in its Sertoli cytoplasm)
    # Sertoli cells: wedges of cytoplasm from the basement membrane to the lumen, one per sector, with thin gaps;
    # the germ cells are nested inside them (the cut-away draws the innermost part on the plane)
    from .cells import extrude
    n_s = 13
    sa = np.linspace(-math.pi, math.pi, n_s, endpoint=False) + 0.11
    sert = Mesh()
    for a0 in sa:
        a1 = a0 + 2 * math.pi / n_s
        outer = [(R_IN * math.cos(t), R_IN * math.sin(t))
                 for t in np.linspace(a0 + 0.0013 / R_IN, a1 - 0.0013 / R_IN, 14)]
        inner = []
        for t in np.linspace(a1, a0, 7):
            r = R_LUM + 0.006 * math.sin(t * 13 + 1.0) + rng.uniform(-0.003, 0.004)
            inner.append((r * math.cos(t - 0.0013 / r * np.sign(t - (a0 + a1) / 2)),
                          r * math.sin(t - 0.0013 / r * np.sign(t - (a0 + a1) / 2))))
        poly = np.array(outer + inner)
        sert.extend(extrude(poly, lambda u, v, t: (TI[0] + u, TI[1] + v, t), np.linspace(Z0, Z1, 3)))
    # Sertoli nuclei: pale, oval, near the base, one per cell
    snuc = Mesh()
    for a in sa + (math.pi / n_s):
        for zc in (-0.03, 0.004, 0.034):
            radial = np.array([math.cos(a), math.sin(a), 0.0])
            R = np.column_stack([radial, [-radial[1], radial[0], 0], [0, 0, 1.0]])
            snuc.extend(ell_mesh((0, 0, 0), (0.014, 0.0075, 0.0085), res=8).transformed(R, TI + radial * 0.158
                                                                                          + np.array([0, 0, zc])))
    sw = Sweep(np.array([[TI[0], TI[1], Z0], [TI[0], TI[1], Z1]]), 180, 14)
    wav = 0.0022 * np.sin(sw.T * 23.0 + 2.0 * np.sin(sw.S * 6.0))
    bm = sw.shell(R_IN - 0.001 + wav * 0.5, R_BM + wav)
    add(bm, "Basement membrane & peritubular myoid cells", G_TUB, "bm", DESC["bm"], "muscle")
    add(sert, "Sertoli (sustentacular) cells", G_TUB, "sertoli", DESC["sertoli"], "gland")
    add(snuc, "Sertoli cell nuclei", G_TUB, "s_nuc", DESC["s_nuc"], "nucleus")
    add(mesh["sg"], "Spermatogonia", G_TUB, "sg", DESC["sg"], "gland")
    add(mesh["sc1"], "Primary spermatocytes", G_TUB, "sc1", DESC["sc1"], "gland")
    add(mesh["sc2"], "Secondary spermatocytes", G_TUB, "sc2", DESC["sc2"], "gland")
    add(Mesh().extend(mesh["sd"]).extend(mesh["esd"]), "Spermatids", G_TUB, "sd", DESC["sd"], "gland")
    add(sz, "Spermatozoa (lumen)", G_TUB, "sz", DESC["sz"], "nucleus")
    add(nuc, "Germ cell nuclei", G_TUB, "nuc", DESC["nuc"], "nucleus")
    # interstitium: Leydig cell clusters and capillaries in the angles outside the tubule
    ley = Mesh()
    lnuc = Mesh()
    for a0 in (0.5, 2.6, 4.55):
        for k in range(9):
            a = a0 + rng.uniform(-0.2, 0.2)
            r = rng.uniform(0.214, 0.245)
            c = TI + np.array([r * math.cos(a), r * math.sin(a), rng.uniform(-0.045, 0.03)])
            rad = rng.uniform(0.011, 0.015)
            ley.extend(ell_mesh(c, (rad, rad * 0.85, rad * 0.9), res=7))
            lnuc.extend(ell_mesh(c, (rad * 0.42, rad * 0.42, rad * 0.42), res=6))
    add(ley, "Leydig (interstitial) cells", G_TUB, "leydig", DESC["leydig"], "gland")
    add(lnuc, "Leydig cell nuclei", G_TUB, "nuc", DESC["l_nuc"], "nucleus", label=False)
    caps = [np.array([[TI[0] + r * math.cos(a), TI[1] + r * math.sin(a), z] for z in np.linspace(Z0, Z1, 12)])
            for a, r in ((1.55, 0.222), (3.55, 0.226), (5.6, 0.222))]
    add(_tubes(caps, [0.0105] * 3, 14), "Interstitial capillaries", G_TUB, "cap", DESC["icap"], "artery")


def _sperm_inset(add):
    X0 = 0.80
    top = 0.085
    # head: paddle-shaped, the nucleus capped over its front two-thirds by the acrosome
    g = _Grid((X0 - 0.045, top - 0.14, -0.026), (X0 + 0.045, top + 0.01, 0.026), 0.0018)
    hc = np.array([X0, top - 0.055, 0.0])
    head = _ell_fn(hc, (0.034, 0.052, 0.0165))(g.x, g.y, g.z)
    nucd = _ell_fn(hc + np.array([0, -0.004, 0]), (0.0285, 0.046, 0.0118))(g.x, g.y, g.z)
    acro = _I(head, -nucd, -(g.y - (hc[1] - 0.008)))
    add(g.mesh(nucd, 0.6), "Sperm nucleus", G_SP, "sp_nuc", DESC["sp_nuc"], "nucleus")
    add(g.mesh(acro, 0.5), "Acrosome", G_SP, "acro", DESC["acro"], "gland")
    post = _I(head, -nucd, g.y - (hc[1] - 0.008))
    neck_c = hc[1] - 0.056
    neck = round_cone((X0, neck_c + 0.008, 0), (X0, neck_c - 0.012, 0), 0.0105, 0.0095)[0](g.x, g.y, g.z)
    add(g.mesh(_U(post, _I(neck, -nucd)), 0.5), "Neck (centrioles) & post-acrosomal region", G_SP, "neck",
        DESC["neck"], "other")
    # tail: axoneme all the way, mitochondrial sheath in the midpiece, fibrous sheath in the principal piece
    ys = np.linspace(neck_c - 0.008, top - 0.80, 300)
    amp = 0.04 * np.clip((neck_c - 0.12 - ys) / 0.55, 0.0, 1.0) ** 1.3
    xs = X0 + amp * np.sin((ys - neck_c) * 16.0)
    axis = np.stack([xs, ys, np.zeros_like(ys)], -1)
    L = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(axis, axis=0), axis=1))])
    i_mid = int(np.searchsorted(L, 0.105))
    i_end = int(np.searchsorted(L, L[-1] - 0.06))
    add(tube(axis[:i_end + 2], 0.0042, 12), "Axoneme (9+2 microtubules)", G_SP, "axo", DESC["axo"], "other")
    add(tube(axis[i_end:], np.linspace(0.0042, 0.0022, len(axis) - i_end), 12), "End piece", G_SP, "end",
        DESC["end_piece"], "other")
    t_, n_, b_ = frames(axis[:i_mid + 3])
    th = np.linspace(0, i_mid + 1.999, 900)
    i0 = th.astype(int)
    f = (th - i0)[:, None]
    P = axis[i0] * (1 - f) + axis[i0 + 1] * f
    nn = n_[i0] * (1 - f) + n_[i0 + 1] * f
    bb = b_[i0] * (1 - f) + b_[i0 + 1] * f
    ph = (L[i0] * (1 - f[:, 0]) + L[i0 + 1] * f[:, 0]) / 0.0095 * 2 * math.pi
    hel = P + nn * (0.0088 * np.cos(ph))[:, None] + bb * (0.0088 * np.sin(ph))[:, None]
    add(tube(hel, 0.0042, 8), "Midpiece (mitochondrial sheath)", G_SP, "mito", DESC["mito"], "gland")
    from .kit import tube_shell
    pp = axis[i_mid + 3:i_end]
    rr = np.linspace(0.0092, 0.0058, len(pp))
    add(tube_shell(pp, rr, 0.0047, 16), "Principal piece (fibrous sheath)", G_SP, "fib", DESC["fib"], "fascia")


# ----------------------------------------------------------------------------------------------- descriptions
DESC = {
    "pubis": "Right pubic bone and ischiopubic ramus, lateral to the plane of section. The two bodies meet at the "
             "symphysis; the inferior pubic and ischial rami form the pubic arch, to which the crura of the penis "
             "and the perineal membrane are attached. The pubic tubercle, just lateral to the symphysis, is the "
             "landmark for the superficial inguinal ring: an inguinal hernia emerges above "
             "and medial to it, a femoral hernia below and lateral.",
    "symphysis": "Pubic symphysis: a secondary cartilaginous joint - hyaline cartilage on each pubic face joined by "
                 "an interpubic fibrocartilaginous disc, reinforced by the superior and arcuate (inferior) pubic "
                 "ligaments. The bladder lies directly behind it; the retropubic space (of Retzius) between them is "
                 "where a full bladder can be approached extraperitoneally (suprapubic catheter) and where the deep "
                 "dorsal vein enters the pelvis beneath the arcuate ligament.",
    "rectum": "Rectum and anal canal (translucent). The ampulla lies directly behind the seminal vesicles and the "
              "prostate, separated only by the rectovesical (Denonvilliers) fascia - which is why a digital rectal "
              "examination (DRE) can feel the posterior surface of the prostate: normal is rubbery with a palpable "
              "median sulcus; a hard, irregular nodule suggests carcinoma (peripheral zone); a smooth, symmetrical "
              "enlargement suggests benign hyperplasia; a boggy, very tender gland suggests prostatitis.",
    "peritoneum": "Peritoneum: covers the dome of the bladder and dips down between bladder and rectum as the "
                  "rectovesical pouch - the lowest part of the peritoneal cavity in the male, where pus, blood or "
                  "tumour deposits collect (palpable on rectal examination as a 'rectal shelf'). The prostate, "
                  "seminal vesicles and bladder neck lie below it, extraperitoneally.",
    "rectus": "Rectus abdominis: inserts on the pubic crest and symphysis. Its lateral border is the medial side of "
              "the inguinal (Hesselbach) triangle - bounded laterally by the inferior epigastric vessels and below "
              "by the inguinal ligament - through which direct inguinal hernias push.",
    "bladder": "Urinary bladder, detrusor muscle: interlacing bundles of smooth muscle forming a hollow reservoir "
               "(300-500 mL), shown moderately full and rising above the pubis. Parasympathetic S2-S4 fibres "
               "contract it for voiding. In men the base (fundus) rests on the seminal vesicles, ampullae and "
               "rectum, and the neck rests on the prostate - so an enlarged prostate obstructs outflow and the "
               "detrusor thickens into trabeculae and diverticula, with incomplete emptying and retention.",
    "bl_mucosa": "Bladder mucosa: urothelium thrown into rugae when the bladder is empty - except over the trigone, "
                 "the smooth triangle between the two ureteric orifices and the internal urethral orifice, which "
                 "stays smooth because its mucosa is firmly bound to the underlying muscle. Common site of bladder "
                 "tumours and of cystitis-related irritation.",
    "ureter": "Ureter: descends on the lateral pelvic wall and enters the posterolateral bladder base obliquely; "
              "the intramural course acts as a flap valve against reflux. In the male the ductus deferens crosses "
              "over (superior/anterior to) it just before it enters the bladder - 'water under the bridge', as in "
              "the female with the uterine artery.",
    "pz": "Peripheral zone: about 70% of the glandular prostate, forming the posterior, lateral and apical parts - "
          "the part felt on rectal examination. About 70% of prostate cancers (adenocarcinoma) arise here, which "
          "is why a hard nodule on DRE is significant; cancer here seldom causes early urinary symptoms. PSA is "
          "made by all prostatic epithelium and is raised in cancer, but also in BPH, prostatitis and after "
          "instrumentation. Spread is to the pelvic lymph nodes and to bone (osteoblastic metastases in the "
          "lumbar spine and pelvis, via the vertebral venous plexus).",
    "cz": "Central zone: about 25% of the glandular prostate, a cone around the ejaculatory ducts from the base to "
          "the seminal colliculus. Embryologically derived from the Wolffian duct; rarely the site of either "
          "hyperplasia or carcinoma.",
    "tz": "Transition zone: only ~5% of the young prostate - two small lobes beside the proximal prostatic urethra, "
          "above the colliculus - but the site of benign prostatic hyperplasia (BPH). DHT-driven nodules of glands "
          "and stroma enlarge it (the 'median' and 'lateral lobes' of the surgeon), compressing the urethra: "
          "hesitancy, weak stream, frequency, nocturia, retention. Treated with α1-blockers (tamsulosin, relaxes "
          "the smooth muscle), 5α-reductase inhibitors (finasteride, shrinks the gland) or transurethral "
          "resection (TURP). BPH is not premalignant.",
    "afs": "Anterior fibromuscular stroma: the non-glandular front of the prostate, fibrous tissue and smooth "
           "muscle continuous with the bladder neck muscle and the external sphincter. Lies behind the pubic "
           "symphysis, separated from it by the retropubic space and the prostatic venous plexus.",
    "capsule": "Prostatic 'capsule': a fibromuscular condensation around the gland, surrounded outside by the "
               "prostatic venous plexus and the prostatic (periprostatic) fascia; the cavernous nerves for erection "
               "run posterolaterally beside it. Extension of cancer through it (T3) changes staging; nerve-sparing "
               "radical prostatectomy tries to preserve the neurovascular bundles to protect erectile function.",
    "colliculus": "Seminal colliculus (verumontanum): a rounded elevation on the urethral crest in the posterior "
                  "wall of the prostatic urethra. On its summit opens the prostatic utricle (a small blind pouch, "
                  "the remnant of the Müllerian ducts - homologue of the uterus and vagina), with the two "
                  "ejaculatory ducts opening on either side; the many prostatic ducts open into the prostatic "
                  "sinuses beside it. It is the urologist's landmark in TURP: resection stays proximal to it to "
                  "protect the external sphincter.",
    "ejac": "Ejaculatory duct (~2 cm): formed by the union of the ductus deferens (ampulla) and the duct of the "
            "seminal vesicle at the base of the prostate; runs anteroinferiorly through the central zone to open on "
            "the seminal colliculus. Emission carries sperm and seminal fluid through it into the prostatic "
            "urethra. Obstruction (cysts, stones) gives low-volume, fructose-negative, acidic ejaculate and "
            "infertility.",
    "int_sph": "Internal urethral sphincter (preprostatic sphincter): smooth muscle at the bladder neck, "
               "sympathetic (α1, L1-L2) supply. It contracts during ejaculation so that semen goes forward and not "
               "into the bladder; damage (TURP, bladder-neck surgery) or α-blockers cause retrograde ejaculation. "
               "α-blockers relax it to improve flow in BPH.",
    "ext_sph": "External urethral sphincter (rhabdosphincter): skeletal muscle around the membranous urethra in the "
               "deep perineal pouch, supplied by the pudendal nerve (S2-S4) - the voluntary 'stop' of urination. "
               "Injury in radical prostatectomy or pelvic fracture causes incontinence.",
    "bug": "Bulbourethral (Cowper) glands: paired pea-sized mucous glands in the deep perineal pouch beside the "
           "membranous urethra, embedded in the external sphincter. Their ducts (~2.5 cm) pierce the perineal "
           "membrane and open into the proximal spongy urethra. On arousal they secrete clear mucus (pre-ejaculate) "
           "that lubricates and neutralises residual acidic urine; it can carry sperm, which is why withdrawal is "
           "unreliable contraception.",
    "u_pro": "Prostatic urethra (3-4 cm): the widest and most dilatable part, lined by urothelium, running from the "
             "bladder neck through the prostate, slightly concave forwards. Its posterior wall carries the urethral "
             "crest and seminal colliculus. Shared by the urinary and reproductive tracts - it receives the "
             "ejaculatory ducts and the prostatic ducts, and is compressed by BPH.",
    "u_mem": "Membranous (intermediate) urethra (1-2 cm): the shortest, narrowest and least distensible part, "
             "passing through the external sphincter and perineal membrane. Most vulnerable to injury: a pelvic "
             "fracture can shear it just above the membrane (blood at the meatus, high-riding prostate on DRE, "
             "urinary retention) - do not pass a catheter blindly. Also where a catheter or cystoscope is most "
             "likely to cause a false passage.",
    "u_spon": "Spongy (penile) urethra (~15 cm): runs in the corpus spongiosum. It is dilated in the bulb "
              "(intrabulbar fossa, receiving the bulbourethral ducts) and again in the glans (navicular fossa), "
              "with the ducts of the small urethral (Littré) glands along its roof. Straddle injury tears the bulbar "
              "urethra below the perineal membrane: urine extravasates into the superficial perineal pouch and "
              "tracks into the scrotum, penis and anterior abdominal wall under Colles/Scarpa fascia - but not into "
              "the thighs. Gonococcal and post-traumatic strictures are commonest here.",
    "meatus": "External urethral orifice (meatus): a vertical slit at the tip of the glans - the narrowest point of "
              "the urethra, so calculi may lodge just behind it. In hypospadias the orifice opens on the ventral "
              "(under) surface of the penis or perineum, from incomplete fusion of the urethral folds; in the rarer "
              "epispadias it opens dorsally (associated with bladder exstrophy).",
    "sv": "Seminal vesicle (seminal gland): a coiled, sacculated tube ~5 cm long lying on the posterior bladder "
          "base, lateral to the ampulla and in front of the rectum. It secretes ~60-70% of semen volume: alkaline "
          "fluid rich in fructose (sperm energy), prostaglandins and semenogelin (coagulum). Its duct joins the "
          "ductus deferens to form the ejaculatory duct. Palpable above the prostate on DRE when enlarged; "
          "invasion by prostate cancer upstages it.",
    "ampulla": "Ampulla of the ductus deferens: the dilated, tortuous terminal part behind the bladder, medial to "
               "the seminal vesicle, where sperm are stored before emission; it joins the seminal vesicle duct to "
               "form the ejaculatory duct.",
    "cav": "Corpora cavernosa: the paired dorsal erectile bodies (the right one opened along its axis). A sponge of "
           "vascular sinusoids (cavernous spaces) lined by endothelium in trabeculae of smooth muscle, fed by the "
           "helicine branches of the deep artery. Erection: parasympathetic pelvic splanchnic nerves (S2-S4) "
           "release NO, cGMP relaxes the smooth muscle, the sinusoids fill and compress the subtunical venules "
           "against the tunica albuginea (veno-occlusion). PDE5 inhibitors (sildenafil) prolong cGMP. Priapism - "
           "an erection lasting over 4 h (sickle cell disease, intracavernosal drugs) - is ischaemic and an "
           "emergency.",
    "tun_cav": "Tunica albuginea of the corpora cavernosa: a thick sheath of dense collagen (inner circular, outer "
               "longitudinal layers) around both corpora, forming the incomplete median septum of the penis between "
               "them. Rupture during forceful bending of the erect penis is a 'penile fracture' (snap, detumescence, "
               "'aubergine' haematoma) needing surgical repair; fibrous plaques in it cause the curvature of "
               "Peyronie disease.",
    "deep_art": "Deep artery of the penis (cavernosal artery): a branch of the internal pudendal artery that enters "
                "the crus and runs along the centre of each corpus cavernosum, giving coiled helicine arteries that "
                "straighten and open into the cavernous spaces during erection. Atherosclerosis here is a common "
                "cause of erectile dysfunction, often an early marker of coronary disease.",
    "spong": "Corpus spongiosum: the single ventral erectile body that surrounds the spongy urethra, expanding "
             "proximally into the bulb and distally into the glans. Its tunica is thin and its sinusoids fill "
             "less firmly, so the urethra stays open for ejaculation during erection.",
    "glans": "Glans penis: the cap-shaped expansion of the corpus spongiosum over the blunt ends of the corpora "
             "cavernosa, its projecting rim the corona and the groove behind it the neck. Densely innervated "
             "(dorsal nerve, genital corpuscles) - the main sensory zone. Balanitis (inflammation of the glans) is "
             "commonest with poor hygiene, diabetes and phimosis; the glans and prepuce are sites of penile "
             "squamous cell carcinoma (HPV, uncircumcised men).",
    "dd_vein": "Deep dorsal vein of the penis: single, midline, beneath the deep fascia between the dorsal arteries; "
               "drains the glans and corpora and passes beneath the arcuate pubic ligament into the prostatic "
               "venous plexus. Compressed against the tunica during erection (veno-occlusion).",
    "dors_art": "Dorsal arteries of the penis: paired terminal branches of the internal pudendal artery, running on "
                "the dorsum between the deep dorsal vein (medial) and the dorsal nerves (lateral), deep to Buck's "
                "fascia; supply the skin, fascia and glans.",
    "dors_nerve": "Dorsal nerves of the penis: terminal branches of the pudendal nerve (S2-S4), the main sensory "
                  "supply of the penile skin and glans, running lateral to the dorsal arteries. Blocked at the base "
                  "of the penis (dorsal penile nerve block) for circumcision.",
    "buck": "Deep fascia of the penis (Buck fascia): a strong membranous sleeve binding the three corpora together "
            "with the deep dorsal vein, dorsal arteries and dorsal nerves inside it. It limits the haematoma of a "
            "penile fracture to the shaft if intact, and a urethral tear deep to it keeps extravasated urine and "
            "blood confined to the penis.",
    "sup_vein": "Superficial dorsal vein of the penis: in the superficial fascia, drains the skin and prepuce to the "
                "superficial external pudendal veins and so to the great saphenous vein.",
    "pskin": "Skin and superficial (dartos) fascia of the penis: thin, hairless (beyond the base), dark skin that "
             "slides freely on a loose, fat-free layer of connective tissue and smooth muscle - continuous with the "
             "dartos of the scrotum and Colles fascia of the perineum - which carries the superficial dorsal vein. "
             "Urine from a bulbar urethral tear spreads in the plane deep to it into the scrotum and penis. Lymph "
             "drains to the superficial inguinal nodes (the glans to the deep inguinal nodes).",
    "prepuce": "Prepuce (foreskin): a double fold of skin covering the glans, its inner layer mucosa-like and "
               "reflected onto the neck of the glans; smegma collects in the preputial sac. Removed in circumcision. "
               "Phimosis - a prepuce too tight to retract (physiological in infants) - can cause balanitis and "
               "urinary obstruction; paraphimosis - a retracted prepuce trapped behind the corona, strangling the "
               "glans with oedema - is an emergency.",
    "frenulum": "Frenulum of the prepuce: a median fold on the underside of the glans joining it to the inner "
                "prepuce, very richly innervated and carrying the frenular artery - it may tear and bleed "
                "briskly during intercourse. A short frenulum (frenulum breve) causes painful retraction.",
    "susp": "Suspensory ligament of the penis: a triangular condensation of deep fascia from the front of the pubic "
            "symphysis to the dorsum of the penis, which holds the root up and fixes the angle between root and "
            "body; the more superficial fundiform ligament loops round the shaft from the linea alba. Division in "
            "'lengthening' surgery makes the erect penis less stable.",
    "bulb": "Bulb of the penis: the expanded proximal end of the corpus spongiosum in the superficial perineal "
            "pouch, attached to the perineal membrane; the urethra enters its upper surface and the bulbourethral "
            "ducts open nearby. With the two crura it forms the root (fixed part) of the penis.",
    "crus": "Crura of the penis: the proximal, diverging ends of the corpora cavernosa, each firmly attached to the "
            "ischiopubic ramus and perineal membrane and covered by ischiocavernosus. They converge beneath the "
            "pubic symphysis to form the body of the penis. Crura + bulb = root of the penis.",
    "isch": "Ischiocavernosus: covers each crus from the ischial tuberosity and ramus; compresses the crus and "
            "retards venous return to maintain erection. Pudendal nerve (perineal branch).",
    "bulbosp": "Bulbospongiosus: paired halves united in a median raphe on the bulb and the perineal body, wrapping "
               "the bulb and root. Its rhythmic contractions expel the last urine and propel semen in ejaculation "
               "and assist erection by compressing the bulb and the deep dorsal vein. Pudendal nerve (perineal "
               "branch). Absent bulbocavernosus reflex suggests a sacral cord or cauda equina lesion.",
    "perbody": "Perineal body (central tendon of the perineum): the fibromuscular node between the bulb and the anal "
               "canal where bulbospongiosus, the transverse perineal muscles, external anal sphincter and levator "
               "ani meet - the 'clinical perineum'. It supports the pelvic floor.",
    "permem": "Perineal membrane: a strong triangular fascial sheet spanning the pubic arch between the ischiopubic "
              "rami. It separates the deep perineal pouch (external sphincter, bulbourethral glands, membranous "
              "urethra) from the superficial pouch (root of the penis, ischiocavernosus, bulbospongiosus), and "
              "anchors the root of the penis. It defines where extravasated urine goes after urethral injury.",
    "alb": "Tunica albuginea of the testis: a tough, white capsule of dense collagen, covered by the visceral layer "
           "of the tunica vaginalis; it thickens posteriorly into the mediastinum and sends septa inwards. Being "
           "inelastic, it makes orchitis (mumps) painful and ischaemic.",
    "septa": "Septa of the testis: thin fibrous partitions from the mediastinum to the tunica albuginea that divide "
             "the testis into about 250 pyramidal lobules.",
    "lobule": "Lobules of the testis: each holds 1-4 highly coiled seminiferous tubules in loose interstitial "
              "tissue containing the Leydig (interstitial) cells, capillaries and lymphatics. Leydig cells make "
              "testosterone under LH; FSH acts on the Sertoli cells in the tubules.",
    "tubules": "Seminiferous tubules: coiled tubes (~0.2 mm wide, 30-80 cm long each, ~500 m in all) where "
               "spermatogenesis takes about 64-74 days, needing a temperature ~2-3 °C below core (hence the "
               "scrotum). See the magnified inset for the cells. In cryptorchidism (an undescended testis) the "
               "warmer environment impairs spermatogenesis and the risk of germ cell tumour (seminoma) is raised - "
               "orchidopexy is done by 6-12 months. Germ cell tumours (seminoma, teratoma) arise from these "
               "tubules and present as a painless, hard testicular lump (tumour markers AFP, β-hCG, LDH).",
    "medi": "Mediastinum testis: the thickened posterior part of the tunica albuginea, entered by vessels and "
            "nerves and containing the rete testis. The septa radiate from it.",
    "rete": "Tubuli recti and rete testis: at the apex of each lobule the tubule straightens (tubulus rectus, lined "
            "by Sertoli cells only) and enters the rete testis - an anastomosing network of channels lined by "
            "cuboidal epithelium in the mediastinum. Path of sperm: seminiferous tubule → tubulus rectus → rete "
            "testis → efferent ductules → epididymis.",
    "effer": "Efferent ductules: 12-20 coiled ducts from the rete testis to the head of the epididymis, each forming "
             "a conical lobule (conus vasculosus). Their epithelium alternates tall ciliated and short absorptive "
             "cells (a 'saw-tooth' lumen) and reabsorbs most of the testicular fluid. They derive from mesonephric "
             "tubules.",
    "epi_h": "Head of the epididymis: the expanded upper part on the superior pole, made of the coiled efferent "
             "ductules and the start of the duct of the epididymis. A small appendix of the epididymis may twist "
             "(torsion of an appendage - a 'blue dot' sign), mimicking testicular torsion.",
    "epi_b": "Body of the epididymis: the single, highly coiled duct of the epididymis (~6 m long, pseudostratified "
             "columnar epithelium with stereocilia) along the posterolateral border of the testis. Sperm spend "
             "~2 weeks passing through it and acquire motility and the ability to fertilise (maturation); sperm "
             "taken straight from the testis cannot fertilise. Epididymitis (Chlamydia/gonorrhoea in young men, "
             "E. coli in older men) causes a tender swelling whose pain is relieved by elevation (Prehn sign).",
    "epi_t": "Tail of the epididymis: at the lower pole, the main reservoir of mature sperm; its duct thickens and "
             "straightens into the ductus deferens, which turns sharply up the posterior border of the testis.",
    "tv": "Tunica vaginalis, parietal layer: the serous sac pinched off from the processus vaginalis as the testis "
          "descends, covering the front and sides of the testis and epididymis (the visceral layer is fused with the "
          "tunica albuginea). Fluid between the layers is a hydrocele (transilluminates). If the processus stays "
          "open, abdominal contents can follow it: congenital indirect inguinal hernia. A high 'bell-clapper' "
          "attachment lets the testis rotate on the cord - testicular torsion: sudden severe pain, high-riding "
          "horizontal testis, absent cremasteric reflex; surgical exploration within 6 hours to save the testis, "
          "with fixation of both sides.",
    "isf": "Internal spermatic fascia: the innermost covering of the cord and testis, derived from the transversalis "
           "fascia at the deep inguinal ring.",
    "crem": "Cremaster muscle and fascia: loops of skeletal muscle derived from the internal oblique, in the middle "
            "covering of the cord and testis. Supplied by the genital branch of the genitofemoral nerve (L1-L2), "
            "it draws the testis up in the cold, fear or when the inner thigh is stroked (cremasteric reflex, "
            "L1-L2) - the reflex is typically absent in testicular torsion.",
    "esf": "External spermatic fascia: the outermost covering of the cord and testis, derived from the external "
           "oblique aponeurosis at the superficial inguinal ring.",
    "scr_skin": "Scrotal skin: thin, pigmented, hairy and wrinkled into transverse rugae by the underlying dartos, "
                "with a median raphe marking the line of fusion of the labioscrotal swellings. Lying outside the "
                "body lets the testes sit ~2-3 °C below core temperature. Lymph drains to the superficial inguinal "
                "nodes - unlike the testis, which drains to the para-aortic nodes (so a testicular cancer is "
                "removed through the groin, never through the scrotum, to avoid seeding the inguinal nodes).",
    "dartos": "Dartos muscle and fascia: a layer of smooth muscle in the fat-free subcutaneous tissue of the "
              "scrotum, forming the scrotal septum between the testes. It contracts in the cold, wrinkling the skin "
              "and drawing the testes towards the body to conserve heat, and relaxes in warmth - with the "
              "cremaster and the pampiniform plexus it regulates testicular temperature. Sympathetic supply.",
    "ductus": "Ductus (vas) deferens: a thick-walled muscular tube (~45 cm, lumen tiny, wall three smooth muscle "
              "layers) that feels like a firm cord when rolled between the fingers in the scrotum. It runs from "
              "the tail of the epididymis up the spermatic cord, through the inguinal canal and the deep ring, "
              "hooks lateral to the inferior epigastric artery, crosses the external iliac vessels and runs over the "
              "ureter to the back of the bladder, ending in the ampulla. Peristalsis propels sperm during emission "
              "(sympathetic). Vasectomy: both ducts are divided and tied through a small scrotal incision; sperm "
              "are still made but reabsorbed, and ejaculate volume barely changes (most comes from the seminal "
              "vesicles and prostate) - sterility is confirmed by semen analysis some weeks later. Congenital "
              "bilateral absence is linked to cystic fibrosis (CFTR).",
    "t_art": "Testicular artery: from the abdominal aorta at L2 (the testis develops high on the posterior abdominal "
             "wall and descends, dragging its vessels, nerves and lymphatics with it), runs in the cord - tortuous "
             "near the testis - to the mediastinum. The artery to the ductus and the cremasteric artery give a "
             "collateral supply, which is why a divided testicular artery is sometimes survived; torsion, which "
             "twists all three, is not.",
    "pamp": "Pampiniform plexus and testicular vein: a network of 8-12 anastomosing veins wrapped round the "
            "testicular artery that acts as a countercurrent heat exchanger, cooling arterial blood before it "
            "reaches the testis. It condenses into a single testicular vein in the canal; the right drains into "
            "the IVC, the left into the left renal vein at a right angle. Dilatation is a varicocele - a 'bag of "
            "worms' above the testis, commoner on the left (longer vein, right-angle entry, compression by the "
            "sigmoid colon or between aorta and SMA - 'nutcracker'), that reduces fertility. A new left "
            "varicocele in an older man can signal a left renal tumour blocking the vein.",
    "gf_nerve": "Genital branch of the genitofemoral nerve (L1-L2): runs in the cord to supply the cremaster and the "
                "anterior scrotal skin - the efferent limb of the cremasteric reflex. May be caught in hernia "
                "repair, causing groin pain.",
    "ext_obl": "External oblique aponeurosis (translucent): its fibres run inferomedially and form the anterior wall "
               "of the inguinal canal; its lower border rolls under as the inguinal ligament, and just above the "
               "pubic tubercle it splits into medial and lateral crura around the superficial inguinal ring.",
    "sup_ring": "Superficial inguinal ring: a triangular gap in the external oblique aponeurosis above and lateral to "
                "the pubic tubercle through which the spermatic cord leaves the canal, gaining the external "
                "spermatic fascia from the margins. Both indirect and direct inguinal hernias can emerge through "
                "it into the scrotum; the ring can be felt by invaginating scrotal skin with a fingertip.",
    "int_obl": "Internal oblique and transversus abdominis: their lower fibres arch over the spermatic cord to form "
               "the roof of the inguinal canal and then fuse medially as the conjoint tendon (falx inguinalis), "
               "which reinforces the posterior wall behind the superficial ring. The internal oblique gives the "
               "cremaster muscle to the cord.",
    "tf": "Transversalis fascia (translucent): the posterior wall of the inguinal canal; the deep inguinal ring is an "
          "opening in it, from whose margins the internal spermatic fascia is drawn out along the cord. Weakness "
          "of the posterior wall medial to the inferior epigastric vessels (Hesselbach triangle) gives a direct "
          "inguinal hernia - common in older men, rarely enters the scrotum, low risk of strangulation.",
    "deep_ring": "Deep inguinal ring: the opening in the transversalis fascia ~1.5 cm above the midpoint of the "
                 "inguinal ligament, just lateral to the inferior epigastric vessels, where the ductus deferens and "
                 "testicular vessels enter the canal. An indirect inguinal hernia enters the canal here, lateral to "
                 "the inferior epigastric vessels, following the processus vaginalis (patent in infants, commonest "
                 "hernia at all ages) - it may descend into the scrotum and is controlled by pressure over the deep "
                 "ring.",
    "ing_lig": "Inguinal ligament: the rolled lower border of the external oblique aponeurosis from the anterior "
               "superior iliac spine to the pubic tubercle, forming the floor (gutter) of the inguinal canal. An "
               "inguinal hernia appears above it, a femoral hernia below it and lateral to the pubic tubercle.",
    "canal": "Inguinal canal (outlined): a ~4 cm oblique passage through the lower abdominal wall from the deep to "
             "the superficial ring, above the medial half of the inguinal ligament, carrying the spermatic cord "
             "(the round ligament in women). Walls: anterior - external oblique aponeurosis (plus internal oblique "
             "laterally); posterior - transversalis fascia (plus conjoint tendon medially); roof - arching internal "
             "oblique and transversus; floor - inguinal ligament. The testis descends through it in the 7th-8th "
             "months; arrest along the way is cryptorchidism.",
    "ie_art": "Inferior epigastric artery: from the external iliac artery, ascends medial to the deep inguinal ring "
              "into the rectus sheath - the landmark separating indirect (lateral) from direct (medial) inguinal "
              "hernias, and at risk in laparoscopic port placement.",
    "ie_vein": "Inferior epigastric veins: paired venae comitantes of the artery, draining to the external iliac "
               "vein.",
    # insets
    "bm": "Basement membrane and peritubular myoid cells: the tubule's boundary - a basal lamina with 3-5 layers of "
          "contractile myoid cells and collagen that squeeze the tubule and move immotile sperm towards the rete. "
          "Thickened and hyalinised in Klinefelter syndrome (47,XXY) and in atrophy.",
    "sertoli": "Sertoli (sustentacular) cells: tall columnar cells from the basement membrane to the lumen that "
               "envelop the developing germ cells. Tight junctions between neighbouring Sertoli cells form the "
               "blood-testis barrier, dividing the epithelium into a basal compartment (spermatogonia) and an "
               "adluminal compartment (spermatocytes and later) where haploid cells are hidden from the immune "
               "system - breach (trauma, vasectomy) causes anti-sperm antibodies. Under FSH they make "
               "androgen-binding protein, inhibin (negative feedback on FSH) and, in the embryo, anti-Müllerian "
               "hormone; they phagocytose residual bodies and release the sperm (spermiation). Sertoli cell tumours "
               "are rare.",
    "s_nuc": "Sertoli cell nuclei: pale, oval to triangular, often indented, with a large prominent nucleolus, "
             "lying near the basement membrane - easy to tell from the dark round nuclei of the germ cells.",
    "sg": "Spermatogonia: diploid (2n) stem cells on the basement membrane, in the basal compartment outside the "
          "blood-testis barrier. Type A dark cells are reserve stem cells; type A pale cells divide by mitosis to "
          "renew themselves and to give type B spermatogonia, which enter meiosis as primary spermatocytes. "
          "Spermatogenesis begins at puberty and continues throughout life.",
    "sc1": "Primary spermatocytes: the largest germ cells (2n, 4c), in the middle of the epithelium, with coarse "
           "thread-like chromatin because they spend ~3 weeks in the prophase of meiosis I - so they are the "
           "commonest germ cell seen. Meiosis I (reduction division) gives two secondary spermatocytes. Errors "
           "(non-disjunction) here produce aneuploid sperm.",
    "sc2": "Secondary spermatocytes: haploid (1n, 2c) cells that complete meiosis II within hours, so they are "
           "rarely seen in sections. Each gives two spermatids.",
    "sd": "Spermatids: small haploid (1n, 1c) cells near the lumen. Round spermatids transform without further "
          "division (spermiogenesis): the Golgi forms the acrosome, the nucleus condenses and elongates, a "
          "flagellum grows from the distal centriole, mitochondria gather round the midpiece and the excess "
          "cytoplasm is shed as a residual body. Late (elongated) spermatids lie in deep recesses of the Sertoli "
          "apices with their heads pointing to the basement membrane.",
    "sz": "Spermatozoa in the lumen: released by spermiation, still immotile - carried by fluid and myoid "
          "contraction to the rete and epididymis, where they gain motility. One primary spermatocyte yields four "
          "sperm; ~100 million a day.",
    "nuc": "Germ cell nuclei: the chromatin of each stage - large and rounded in spermatogonia, coarsely clumped "
           "threads in primary spermatocytes, small and round in early spermatids, condensed and dense in "
           "elongating spermatids.",
    "l_nuc": "Leydig cell nuclei: round, eccentric, with a prominent nucleolus.",
    "leydig": "Leydig (interstitial) cells: polygonal, eosinophilic cells in clusters in the angles between tubules, "
              "beside capillaries. Rich in smooth ER and lipid droplets (steroid synthesis) and sometimes with "
              "Reinke crystals. Under LH they secrete testosterone, which acts locally at very high concentration on "
              "Sertoli cells to sustain spermatogenesis and systemically for male characteristics. Exogenous "
              "testosterone or anabolic steroids suppress LH and FSH and so shrink the testes and reduce sperm "
              "production. Leydig cell tumours may secrete androgens or oestrogens (gynaecomastia).",
    "icap": "Interstitial capillaries: supply the tubules and carry testosterone away; the continuous endothelium "
            "is outside the blood-testis barrier.",
    "acro": "Acrosome: a cap-like lysosome-derived vesicle over the anterior two-thirds of the nucleus, containing "
            "hyaluronidase and acrosin. The acrosome reaction on binding the zona pellucida (ZP3) releases them so "
            "the sperm can penetrate the corona radiata and zona pellucida of the oocyte.",
    "sp_nuc": "Sperm nucleus: highly condensed haploid DNA packaged with protamines instead of histones - "
              "transcriptionally silent and compact (head ~5 µm long, flattened).",
    "neck": "Neck (connecting piece) and post-acrosomal region: the neck joins the head to the tail and holds the "
            "proximal centriole, which the sperm contributes to the zygote (forming its first mitotic spindle); the "
            "distal centriole gave rise to the axoneme. Behind the acrosome the post-acrosomal plasma membrane is "
            "where the sperm fuses with the oocyte.",
    "mito": "Midpiece: mitochondria wound helically round the axoneme and outer dense fibres, supplying ATP for "
            "flagellar beating. Sperm mitochondria are destroyed after fertilisation, so mitochondrial DNA is "
            "inherited from the mother. Defects cause asthenozoospermia (poor motility).",
    "axo": "Axoneme: the 9+2 arrangement of microtubule doublets with dynein arms running the length of the tail - "
           "dynein ATPase slides the doublets to bend the flagellum. Absent dynein arms (primary ciliary "
           "dyskinesia / Kartagener syndrome) give immotile sperm and infertility, with chronic sinusitis, "
           "bronchiectasis and situs inversus.",
    "fib": "Principal piece (tail / flagellum): the longest part of the tail (~45 µm), where the axoneme is "
           "surrounded "
           "by outer dense fibres and a fibrous sheath of circumferential ribs; its whip-like beating propels the "
           "sperm at ~3 mm/min.",
    "end_piece": "End piece: the short tip of the tail, containing only the axoneme under the plasma membrane.",
}
