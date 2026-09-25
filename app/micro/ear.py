"""The ear: external, middle and inner ear in a coronal section through the right temporal bone.

Laid out like the classic atlas figure, seen from in front: the auricle on the left, the external acoustic meatus
running medially to the tympanic membrane, the air-filled tympanic cavity with its ossicular chain, and the inner ear
- vestibule, semicircular canals and cochlea - excavated out of the petrous bone on the right, with the
vestibulocochlear and facial nerves leaving through the internal acoustic meatus. Beside the block are three magnified
insets: a cross-section of one cochlear turn, a crista ampullaris and a macula.

Everything is authored in millimetres at true relative size (auricle ~62 mm tall, meatus ~24 mm, cochlea ~9 mm wide,
stapes ~3.2 mm) and scaled to model units at the end. The section is one coronal plane, z = Z_CUT: bone, skin,
cartilage, meatus, tympanic membrane, mucosa and muscle bellies are cut on it, while the ossicles, the labyrinth and
the nerves stay whole. Structures that lie deeper than the plane - the labyrinth, the facial canal, the internal
acoustic meatus, the stapedius, the mastoid antrum - are exposed by bevelled troughs dug forward through the bone to
the section, the way a dissector drills out the petrous bone.

Frame (mm): x runs lateral (-) to medial (+), y is up, z is anterior (+, towards the viewer). The origin is near the
centre of the tympanic membrane.
"""
import math

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree

from .cells import frame_from_normal, orient_outward
from .geometry import Mesh, ellipsoid as ellipsoid_mesh, slab, smooth_path, tube
from .kit import Volume, capsule, ellipsoid, mesh_part, round_cone, sdf_part, sphere
from .sdf import smin

MM = 1.0 / 40.0                      # model units per millimetre: 1 unit = 40 mm
ORIGIN = np.array([14.0, 2.0, -4.0])  # the point (mm) that becomes the model's origin
Z_CUT = 0.6                           # the coronal section plane (mm), just in front of the tympanic membrane centre


def to_model(p):
    """Millimetre coordinates -> model units (used by the registry for the cut-away position)."""
    return (np.asarray(p, float) - ORIGIN) * MM


# =============================================================================== small helpers
def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def _basis(n, hint=(0.0, 1.0, 0.0)):
    """Two unit vectors perpendicular to n (the first as close to `hint` as possible)."""
    n = _unit(n)
    a = np.asarray(hint, float) - np.dot(hint, n) * n
    if np.linalg.norm(a) < 1e-6:
        a = np.cross(n, [1.0, 0.0, 0.0])
    a = _unit(a)
    return a, np.cross(n, a)


def _smooth01(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _stamp(vol, shapes, k=0.0):
    """A fresh field of the (smooth) union of primitives, on the grid of `vol`."""
    v = vol.copy(np.full(vol.shape, 1.0e3, np.float32))
    for s in shapes:
        v.add(s, "smooth" if k else "union", k)
    return v.d


def _tube_field(vol, path, radii, k=0.0):
    v = vol.copy(np.full(vol.shape, 1.0e3, np.float32))
    v.tube(path, radii, "smooth" if k else "union", k)
    return v.d


def _trough(d, voxel, depth, bevel=0.45):
    """Extend a cavity forward (+z) through `depth` mm, widening by `bevel` mm per mm: the bevelled channel a
    dissector drills through bone to lay a deep structure open to the section plane."""
    out = d.copy()
    n = int(math.ceil(depth / voxel))
    s = 1
    while s <= n:
        shifted = np.full_like(out, 1.0e3)
        shifted[:, :, s:] = out[:, :, :-s] - bevel * s * voxel
        np.minimum(out, shifted, out=out)
        s *= 2
    return out


def _cut(vol, d, z=None):
    """Clip a field at the coronal section plane."""
    _, _, zz = vol.axes()
    return np.maximum(d, zz - (Z_CUT if z is None else z))


def _exact(vol, d, keep=None):
    """Repair a field whose values are only trustworthy near its surface (the ellipsoid bound, smooth unions) into a
    signed distance: near the surface keep the analytic value, deeper in use the Euclidean distance transform. Shells
    and offsets taken inside a raw ellipsoid field would otherwise sprout sheets through its centre."""
    inside = d < 0
    e = np.where(inside, -ndimage.distance_transform_edt(inside), ndimage.distance_transform_edt(~inside)) * vol.voxel
    keep = 2.0 * vol.voxel if keep is None else keep
    return np.where(np.abs(e) > keep, e, d).astype(np.float32)


def _shell(d, t):
    """The band of thickness t just inside the surface of d."""
    return np.maximum(d, -(d + t))


def _split(vol, d, regions, eps=None):
    """Cut one closed field into closed parts along smooth region boundaries.

    `regions` are signed fields in priority order (negative inside); every region takes what is left of the field
    inside it, and the remainder is returned last. Neighbours overlap by a fraction of a voxel so that no crack
    opens between them after smoothing."""
    eps = 0.3 * vol.voxel if eps is None else eps
    out = []
    rest = d
    for s_ in regions:
        s_ = np.broadcast_to(s_, d.shape)
        out.append(vol.copy(np.maximum(rest, s_ - eps).astype(np.float32)))
        rest = np.maximum(rest, -s_ - eps)
    out.append(vol.copy(rest.astype(np.float32)))
    return out


def _circle3(p1, p2, p3):
    """Centre, radius and in-plane basis of the circle through three points."""
    p1, p2, p3 = (np.asarray(p, float) for p in (p1, p2, p3))
    n = np.cross(p2 - p1, p3 - p1)
    A = np.array([2 * (p2 - p1), 2 * (p3 - p1), n])
    rhs = np.array([np.dot(p2, p2) - np.dot(p1, p1), np.dot(p3, p3) - np.dot(p1, p1), np.dot(n, p1)])
    c = np.linalg.solve(A, rhs)
    r = float(np.linalg.norm(p1 - c))
    e1 = _unit(p1 - c)
    e2 = _unit(np.cross(_unit(n), e1))
    return c, r, e1, e2, _unit(n)


def _canal_path(start, apex, end, n=120):
    """The major arc of the circle through start - apex - end, from start to end."""
    c, r, e1, e2, _ = _circle3(start, apex, end)
    ang = lambda p: math.atan2(np.dot(p - c, e2), np.dot(p - c, e1))  # noqa: E731
    a_apex, a_end = ang(apex) % (2 * math.pi), ang(end) % (2 * math.pi)
    if a_apex > a_end:                     # go the other way round so that the apex lies on the arc
        e2 = -e2
        a_end = (2 * math.pi - a_end) % (2 * math.pi)
    t = np.linspace(0.0, a_end, n)
    return c + r * (np.cos(t)[:, None] * e1 + np.sin(t)[:, None] * e2)


def _resample(path, spacing):
    path = np.asarray(path, float)
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    n = max(int(arc[-1] / spacing) + 1, 3)
    s = np.linspace(0.0, arc[-1], n)
    return np.stack([np.interp(s, arc, path[:, c]) for c in range(3)], -1)


def _spline(points, spacing=0.1):
    pts = np.asarray(points, float)
    return _resample(smooth_path(pts, max(len(pts) * 30, 60)), spacing)


def _fusiform(n, r_mid, r_end, power=1.0):
    t = np.linspace(-1.0, 1.0, n)
    return r_end + (r_mid - r_end) * (1.0 - np.abs(t) ** 2) ** power


# =============================================================================== key positions (mm)
# tympanic membrane: faces lateral, inferior and anterior, set ~55 degrees to the floor of the meatus
TM_C = np.array([-1.4, 0.4, -0.9])
TM_OUT = _unit([-0.82, -0.57, 0.22])       # lateral surface normal
TM_IN = -TM_OUT
TM_UP, TM_ANT = _basis(TM_OUT, (0.0, 1.0, 0.0))
if TM_ANT[2] < 0:
    TM_ANT = -TM_ANT
TM_RA, TM_RB = 4.7, 4.2                     # semi-axes: 9-10 mm tall, 8-9 mm wide
TM_DEPTH = 2.0                              # the umbo is drawn ~2 mm medially by the handle of the malleus
TM_T = 0.28                                 # thickness (0.1 mm in life; drawn thicker)


def tm_depth(a, b):
    rho = np.sqrt((a / TM_RA) ** 2 + (b / TM_RB) ** 2)
    return TM_DEPTH * np.clip(1.0 - rho, 0.0, 1.0) ** 0.75


def tm_point(a, b, lift=0.0):
    """A point on the medial face of the tympanic membrane (lift > 0 moves it further medially)."""
    return TM_C + a * TM_UP + b * TM_ANT + (float(tm_depth(np.float64(a), np.float64(b))) + TM_T / 2 + lift) * TM_IN


UMBO = tm_point(0.0, 0.0)
LAT_PROC = tm_point(3.55, 0.25, 0.25)
OW = np.array([4.35, 2.9, -2.4])             # centre of the oval window (stapes footplate)
RW = np.array([3.75, -0.7, -3.6])            # centre of the round window
VEST = np.array([6.35, 3.2, -2.7])           # centre of the vestibule
# cochlea: modiolus axis runs anterolaterally and a little downwards from the fundus of the internal acoustic meatus
CO_AX = _unit([-0.35, -0.15, 0.92])
CO_BASE = np.array([10.8, -2.4, -6.6])       # centre of the base of the modiolus
CO_E1, _e2 = _basis(CO_AX, (1.0, 0.0, 0.0))
CO_E2 = np.cross(CO_AX, CO_E1)
if CO_E2[1] < 0:
    CO_E1, CO_E2 = CO_E1, -CO_E2
# internal acoustic meatus: from the fundus (lateral) to the porus on the posterior face of the petrous bone
IAM_FUNDUS = np.array([12.6, 2.6, -6.6])
IAM_PORUS = np.array([30.0, 2.8, -6.4])
# block of bone (lateral surface of the squamous/tympanic parts to the petrous ridge)
BX0, BX1 = -15.5, 34.0
BZ0 = -15.0
SKIN_X = -19.0                               # skin surface of the side of the head


def meatus_path():
    """Centre-line of the external acoustic meatus, from the concha to the tympanic membrane: a gentle S that rises
    and runs backwards laterally, then turns forwards and down medially."""
    return _spline([(-25.5, 1.4, -0.4), (-22.5, 1.5, -0.6), (-19.0, 1.7, -0.8), (-15.5, 1.3, -0.9),
                    (-11.0, 0.5, -0.7), (-6.5, 0.0, -0.6), (-3.2, -0.2, -0.8), TM_C + TM_OUT * 0.3], 0.1)


MEATUS_BONY_X = -15.5                        # the lateral third is cartilaginous, the medial two thirds bony


# =============================================================================== cochlea: the spiral and its sections
PHI0 = math.radians(135.0)             # the basal end of the spiral sits at the upper lateral side of the basal turn
PHI_MAX = math.radians(936.0)          # 2.6 turns
PHI_HEL = math.radians(880.0)          # the spiral lamina ends (hamulus) and the scalae meet at the helicotrema
SECTOR = (math.radians(40.0), math.radians(130.0))   # the stretch of the basal turn that is cut open


def co_station(phi):
    """Centre-line point, radial and axial unit vectors and section half-sizes of the cochlear canal at spiral angle
    phi (0 at the basal end). The canal narrows and the spiral tightens and climbs towards the apex."""
    phi = np.atleast_1d(np.asarray(phi, float))
    f = np.clip(phi / PHI_MAX, 0.0, 1.0)
    psi = PHI0 - phi
    R = 3.0 * (1.0 - 0.68 * f ** 0.9)
    H = 0.9 + 3.5 * f ** 0.85
    er = np.cos(psi)[:, None] * CO_E1 + np.sin(psi)[:, None] * CO_E2
    p = CO_BASE + H[:, None] * CO_AX + R[:, None] * er
    W = 1.0 - 0.45 * f
    Hc = 0.85 - 0.35 * f
    return p, er, f, W, Hc, R, H


def co_hook():
    """The basal hook: the first few millimetres of the canal, curving from the round window into the spiral."""
    p0, er0, *_ = co_station(0.0)
    p1, *_ = co_station(0.25)
    t = _unit(p0[0] - p1[0])
    return _spline([RW + np.array([0.7, 0.0, -0.1]), RW + np.array([2.0, 0.4, -0.9]), p0[0] + t * 1.2, p0[0]], 0.15)


def _pip(poly, pts):
    """Point-in-polygon (even-odd) for 2D points."""
    x, y = pts[:, 0][:, None], pts[:, 1][:, None]
    x0, y0 = poly[:, 0][None, :], poly[:, 1][None, :]
    x1, y1 = np.roll(poly[:, 0], -1)[None, :], np.roll(poly[:, 1], -1)[None, :]
    cond = (y0 > y) != (y1 > y)
    xi = x0 + (y - y0) * (x1 - x0) / np.where(np.abs(y1 - y0) < 1e-12, 1e-12, y1 - y0)
    return (np.sum(cond & (x < xi), axis=1) % 2) == 1


def _cap_tris(poly):
    """Triangles filling a simple (possibly concave) polygon: Delaunay of its vertices, keeping inside triangles."""
    from scipy.spatial import Delaunay
    tri = Delaunay(poly).simplices
    cen = poly[tri].mean(axis=1)
    return tri[_pip(poly, cen)]


def _loft(sections, P, U, V, caps=True):
    """Closed solid swept through per-station outlines: sections (m, n, 2) in the (U, V) frame at each point of P."""
    sections = np.asarray(sections, float)
    m, n, _ = sections.shape
    pos = (P[:, None, :] + sections[:, :, 0:1] * U[:, None, :] + sections[:, :, 1:2] * V[:, None, :]).reshape(-1, 3)
    a = np.arange(m * n).reshape(m, n)
    q0, q1 = a[:-1, :].ravel(), np.roll(a[:-1, :], -1, axis=1).ravel()
    q2, q3 = np.roll(a[1:, :], -1, axis=1).ravel(), a[1:, :].ravel()
    tris = [np.stack([q0, q2, q1], 1), np.stack([q0, q3, q2], 1)]
    if caps:
        for end, flip in ((0, True), (m - 1, False)):
            t = _cap_tris(sections[end])
            t = a[end][t]
            tris.append(t[:, ::-1] if flip else t)
    mesh = Mesh().add(pos, np.vstack(tris))
    return orient_outward(mesh)


def _oval(W, Hc, t):
    return np.stack([W * np.cos(t), Hc * np.sin(t)], -1)


def co_sections(f, W, Hc, n_arc=28):
    """Outlines of the compartments of the cochlear canal at one station (u radial, outwards; v towards the apex).

    Scala vestibuli above, scala tympani below, the triangular cochlear duct between them bounded by the vestibular
    (Reissner) membrane, the basilar membrane and the stria on the outer wall. The basilar membrane widens from the
    base to the apex while the osseous spiral lamina shortens - the anatomical basis of tonotopy."""
    lam = 0.10
    bm = 0.05
    rm = 0.035
    v0 = -0.12 * Hc
    t_bm = math.asin(v0 / Hc)                          # oval angle where the partition meets the outer wall
    u_out = W * math.cos(t_bm) - 0.02
    bm_w = 0.30 + 0.38 * f
    u_tip = u_out - bm_w
    u_mod = -W * math.cos(t_bm) + 0.02
    u_lim = u_tip - 0.32 * W - 0.04
    v_lim = v0 + lam / 2 + 0.07
    t_rm = math.radians(54.0)
    rm_out = np.array([W * math.cos(t_rm), Hc * math.sin(t_rm)])
    lim = np.array([u_lim, v_lim])

    def line(a, b, k):
        return np.linspace(a, b, k, endpoint=False)

    def arc(t0, t1, k, w=W, h=Hc):
        return _oval(w, h, np.linspace(t0, t1, k, endpoint=False))
    rm_dir = _unit(rm_out - lim)
    rm_nrm = np.array([-rm_dir[1], rm_dir[0]])       # points up, into the scala vestibuli
    top = v0 + lam / 2
    s = {}
    # cochlear duct: lamina lip -> basilar membrane -> stria (outer wall) -> vestibular membrane
    s["duct"] = np.vstack([line([u_lim, top], [u_tip, v0 + bm / 2], 4), line([u_tip, v0 + bm / 2], [u_out, v0 + bm / 2], 8),
                           arc(t_bm + 0.05, t_rm - 0.02, 8), line(rm_out - rm_nrm * rm / 2, lim - rm_nrm * rm / 2 +
                                                                  np.array([0.0, 0.0]), 8)])
    s["rm"] = np.vstack([line(lim - rm_nrm * rm / 2, rm_out - rm_nrm * rm / 2, 10),
                         line(rm_out + rm_nrm * rm / 2, lim + rm_nrm * rm / 2, 10)])
    t_lam = math.pi - math.asin((top + 0.01) / Hc)
    s["sv"] = np.vstack([line(lim + rm_nrm * rm / 2, rm_out + rm_nrm * rm / 2, 8), arc(t_rm + 0.03, t_lam, n_arc),
                         line([u_mod, top + 0.005], [u_lim, top + 0.005], 8)])
    t_st0 = math.pi - math.asin((v0 - lam / 2 - 0.01) / Hc)
    s["st"] = np.vstack([arc(t_st0, 2 * math.pi + t_bm - 0.03, n_arc + 6),
                         line([u_out, v0 - bm / 2], [u_tip, v0 - bm / 2], 8),
                         line([u_tip, v0 - lam / 2], [u_mod, v0 - lam / 2], 8)])
    s["bm"] = np.vstack([line([u_tip - 0.02, v0 - bm / 2], [u_out + 0.02, v0 - bm / 2], 8),
                         line([u_out + 0.02, v0 + bm / 2], [u_tip - 0.02, v0 + bm / 2], 8)])
    s["lamina"] = np.vstack([line([u_mod - 0.35, v0 - lam / 2], [u_tip, v0 - lam / 2], 10),
                             line([u_tip, v0 + lam / 2], [u_mod - 0.35, v0 + lam / 2], 10)])
    # spiral organ: a low mound on the inner part of the basilar membrane (drawn about twice life size)
    o0, o1 = u_tip + 0.03, u_tip + 0.75 * bm_w
    th = np.linspace(0.0, math.pi, 12)
    s["organ"] = np.vstack([np.stack([o0 + (o1 - o0) * (1 - np.cos(th)) / 2,
                                      v0 + bm / 2 + 0.005 + (0.12 + 0.03 * f) * np.sin(th) ** 0.7], -1)[::-1][:-1],
                            line([o0, v0 + bm / 2 + 0.005], [o1, v0 + bm / 2 + 0.005], 4)])
    # tectorial membrane: from the limbus out over the hair cells
    tm0 = np.array([u_lim + 0.02, v_lim - 0.02])
    tm1 = np.array([o0 + 0.62 * (o1 - o0), v0 + bm / 2 + 0.20])
    k = 10
    tt = np.linspace(0, 1, k)
    mid = tm0[None] + (tm1 - tm0)[None] * tt[:, None]
    thick = 0.03 + 0.05 * np.sin(tt * math.pi) ** 0.8
    s["tect"] = np.vstack([mid + np.stack([0 * tt, thick], -1), (mid - np.stack([0 * tt, 0.01 + 0 * tt], -1))[::-1]])
    s["canal"] = arc(0.0, 2 * math.pi, 3 * n_arc, W + 0.02, Hc + 0.02)
    # spiral ligament and stria: a crescent thickening the outer wall
    tl = np.linspace(-1.1, 1.05, 18)
    s["lig"] = np.vstack([_oval(W + 0.02, Hc + 0.02, tl), _oval(W + 0.30, Hc + 0.14, tl[::-1])])
    return s


# =============================================================================== labyrinth layout
CC = VEST + np.array([1.3, 1.9, -1.6])        # crus commune (anterior + posterior canals)
GENICULATE = np.array([5.6, 7.3, 0.1])


def _canals():
    """Centre-lines of the three bony semicircular canals: (path from the ampullated end, arc centre)."""
    a_s = np.array([6.1, 6.5, -1.9])
    a_apex = (a_s + CC) / 2 + np.array([0.0, 5.0, 0.0])
    l_s = np.array([5.9, 6.0, -1.3])
    l_e = np.array([6.6, 5.6, -5.0])
    l_apex = np.array([2.9, 6.9, -4.6])
    p_e = np.array([7.4, 2.3, -5.2])
    p_apex = (CC + p_e) / 2 + 4.3 * _unit([-0.6, 0.0, -0.8])
    out = {}
    for key, (s, apex, e, amp_first) in {"anterior": (a_s, a_apex, CC, True), "lateral": (l_s, l_apex, l_e, True),
                                         "posterior": (CC, p_apex, p_e, False)}.items():
        path = _canal_path(s, apex, e, 140)
        c, *_ = _circle3(s, apex, e)
        if not amp_first:
            path = path[::-1]                 # every path starts at its ampulla
        out[key] = (path, c)
    return out


CANALS = _canals()
R_CANAL = 0.45            # bony canal lumen (0.8-1 mm across)
R_DUCT = 0.19             # semicircular duct (0.3-0.4 mm across; drawn a little thicker)


def _at_arc(path, s):
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    i = int(np.clip(np.searchsorted(arc, s), 1, len(path) - 1))
    t = _unit(path[i] - path[i - 1])
    return path[i], t


def ampullae():
    """Centre, canal direction and outward (away from the arc centre) direction of each ampulla."""
    out = {}
    for key, (path, c) in CANALS.items():
        p, t = _at_arc(path, 0.85)
        outward = _unit((p - c) - np.dot(p - c, t) * t)
        out[key] = (p, t, outward)
    return out


AMP = ampullae()
UTRICLE = (VEST + np.array([0.35, 0.9, -0.7]), np.array([0.75, 0.85, 1.55]))
SACCULE = (VEST + np.array([-0.35, -1.25, 0.75]), np.array([0.62, 0.78, 0.62]))
ENDO_SAC = np.array([10.8, 5.0, -10.0])


def endolymphatic_path():
    j = VEST + np.array([1.1, -0.4, -0.9])
    return _spline([UTRICLE[0] + np.array([0.3, -0.5, -0.4]), j, np.array([8.8, 4.6, -5.8]),
                    np.array([10.0, 5.1, -8.2]), ENDO_SAC], 0.08)


def duct_paths():
    """Semicircular ducts: eccentric in their canals (against the outer wall), each end run into the utricle."""
    out = {}
    uc = UTRICLE[0]
    for key, (path, c) in CANALS.items():
        rad = path - c
        rad -= np.einsum("ij,j->i", rad, _circle3(path[0], path[len(path) // 2], path[-1])[4])[:, None] * \
            _circle3(path[0], path[len(path) // 2], path[-1])[4][None]
        rad /= np.linalg.norm(rad, axis=1, keepdims=True)
        duct = path + rad * (R_CANAL - R_DUCT - 0.06)
        head = _spline([uc + (duct[0] - uc) * 0.35, duct[0] + (uc - duct[0]) * 0.25, duct[3]], 0.06)
        tail = _spline([duct[-4], duct[-1] + (uc - duct[-1]) * 0.25, uc + (duct[-1] - uc) * 0.35], 0.06)
        out[key] = np.vstack([head, duct[4:-4], tail])
    return out


def facial_path():
    """Facial nerve from the internal acoustic meatus: labyrinthine segment over the cochlea, geniculate ganglion,
    tympanic segment along the medial wall above the oval window, second genu, mastoid segment down to the
    stylomastoid foramen."""
    return _spline([(35.5, 3.9, -5.7), (22.0, 3.9, -5.7), (13.4, 3.8, -5.7), (11.2, 5.6, -4.6), (9.2, 7.6, -2.6),
                    (7.3, 8.1, -0.8), GENICULATE, (4.2, 6.3, 0.1), (3.4, 5.0, -0.9), (3.3, 4.5, -2.0),
                    (3.3, 4.55, -4.4), (3.15, 4.1, -6.2), (2.95, 1.0, -7.25), (2.8, -6.0, -7.45), (2.6, -14.5, -7.3),
                    (2.5, -17.5, -7.1)], 0.3)




def chorda_path():
    return _spline([(2.65, -11.0, -7.35), (1.1, -5.0, -7.6), (0.4, 0.0, -6.3), (-0.3, 2.6, -4.8), (-0.75, 4.0, -3.0),
                    (-1.05, 4.45, -1.7), (-1.2, 4.6, -0.4), (-1.3, 4.4, Z_CUT + 0.35)], 0.08)


def tube_path():
    """Pharyngotympanic tube: from the protympanum forwards, medially and down towards the nasopharynx."""
    return _spline([(2.3, -3.0, -0.8), (4.8, -5.4, -0.5), (8.5, -8.6, -0.3), (12.5, -12.0, -0.25),
                    (16.5, -15.8, -0.2), (21.0, -20.5, -0.1), (25.0, -25.0, 0.0)], 0.12)


TUBE_ISTHMUS_X = 12.5


def tensor_path():
    return _spline([(3.4, 3.5, 0.0), (4.0, 0.8, 0.15), (4.9, -2.0, 0.25), (6.4, -4.2, 0.45), (7.6, -5.4, 1.2),
                    (8.2, -6.0, 2.2)], 0.1)


def stapedius_path():
    return _spline([(1.9, 2.2, -6.0), (1.75, -1.0, -6.4), (1.7, -4.0, -6.5), (1.7, -6.5, -6.5)], 0.1)


# =============================================================================== middle-ear fields
def _tm_coords(x, y, z):
    qx, qy, qz = x - TM_C[0], y - TM_C[1], z - TM_C[2]
    a = qx * TM_UP[0] + qy * TM_UP[1] + qz * TM_UP[2]
    b = qx * TM_ANT[0] + qy * TM_ANT[1] + qz * TM_ANT[2]
    w = qx * TM_IN[0] + qy * TM_IN[1] + qz * TM_IN[2]
    return a, b, w


def tm_field(x, y, z, grow=0.0):
    a, b, w = _tm_coords(x, y, z)
    rho = np.sqrt((a / TM_RA) ** 2 + (b / TM_RB) ** 2)
    dep = tm_depth(a, b)
    return np.maximum(np.abs(w - dep) - TM_T / 2 - grow, (rho - 1.0) * min(TM_RA, TM_RB) - grow)


def meatus_field(vol, grow=0.0):
    """Air in the external acoustic meatus, including the recess in front of the obliquely set tympanic membrane."""
    path = meatus_path()
    x = path[:, 0]
    r = np.interp(x, [-26.0, -23.5, -20.0, -15.5, -9.0, -4.0, 0.0], [4.9, 4.0, 3.8, 3.5, 3.0, 3.3, 3.4])
    d = _tube_field(vol, path, r + grow, 0.0)
    X, Y, Z = vol.axes()
    a, b, w = _tm_coords(X, Y, Z)
    rho = np.sqrt((a / TM_RA) ** 2 + (b / TM_RB) ** 2)
    rec = np.maximum.reduce([(rho - 1.0) * 4.2, w - (tm_depth(a, b) - TM_T / 2), -3.2 - w]) - grow
    return np.minimum(d, rec)


def _medial_of_tm(X, Y, Z):
    a, b, w = _tm_coords(X, Y, Z)
    return tm_depth(a, b) + TM_T / 2 + 0.02 - w


def cavity_field(vol, grow=0.0):
    """Air of the tympanic cavity (hypo-, meso- and epitympanum, niches of the windows), aditus and mastoid antrum."""
    X, Y, Z = vol.axes()
    shape = vol.shape

    def st(shapes, k=0.8):
        return _stamp(vol, shapes, k)
    meso = st([ellipsoid((1.2, 0.3, -1.4), (2.45, 4.9, 4.1)), ellipsoid((1.6, -4.2, -1.8), (1.8, 2.0, 3.8)),
               capsule((1.4, -2.2, -0.9), (2.6, -3.6, -0.6), 1.5)])
    prom = st([ellipsoid((5.65, -0.3, -2.3), (2.75, 3.0, 3.7))])
    meso = -smin(-meso, prom, 0.7)
    meso = np.maximum(meso, np.broadcast_to(_medial_of_tm(X, Y, Z), shape))
    niches = st([ellipsoid((3.75, 2.9, -2.4), (0.75, 0.95, 1.7)), ellipsoid((3.45, -0.55, -3.9), (0.75, 0.9, 0.95))],
                0.3)
    epi = st([ellipsoid((-0.45, 7.0, -2.2), (2.85, 3.05, 4.7)), capsule((-0.7, 7.5, -5.8), (-2.6, 7.8, -8.6), 1.3),
              sphere((-3.2, 8.0, -9.9), 2.5)], 0.9)
    d = smin(smin(meso, epi, 0.9), niches, 0.4)
    return d - grow


def ow_window(vol):
    """The oval window: the opening the footplate fills, bored from the niche into the vestibule."""
    x, y, z = vol.axes()
    col = np.maximum(np.sqrt(((y - OW[1]) / 0.82) ** 2 + ((z - OW[2]) / 1.58) ** 2) - 1.0,
                     np.maximum(OW[0] - 0.9 - x, x - OW[0] - 0.9))
    return np.broadcast_to(col, vol.shape).astype(np.float32)


def rw_window(vol):
    x, y, z = vol.axes()
    n = _unit([-0.75, 0.1, -0.35])
    qx, qy, qz = x - RW[0], y - RW[1], z - RW[2]
    along = qx * n[0] + qy * n[1] + qz * n[2]
    rad = np.sqrt(np.maximum(qx ** 2 + qy ** 2 + qz ** 2 - along ** 2, 0.0))
    return np.broadcast_to(np.maximum(rad - 0.75, np.abs(along) - 1.0), vol.shape).astype(np.float32)


def bony_labyrinth_shapes(grow=0.0):
    """Primitives of the bony labyrinth (vestibule, canals with their ampullae) - the cochlea is added separately."""
    shapes = [ellipsoid(VEST, (1.75 + grow, 2.35 + grow, 2.25 + grow))]
    for key, (path, c) in CANALS.items():
        p = path[::3]
        shapes += [capsule(p[i], p[i + 1], R_CANAL + grow) for i in range(len(p) - 1)]
        pa, t, o = AMP[key]
        shapes.append(ellipsoid(pa + o * 0.12, (0.85 + grow, 0.85 + grow, 1.25 + grow),
                                rot=frame_from_normal(t)[:, [0, 2, 1]]))
    # the scala vestibuli opens into the lower vestibule
    p0, er, *_ = co_station(np.array([0.0, 0.3]))
    shapes.append(capsule(p0[0] + CO_AX * 0.35, VEST + np.array([0.3, -1.7, -0.9]), 0.8 + grow))
    return shapes


def cochlea_field(vol, grow=0.0):
    """A round-tube stand-in for the cochlear canal (for carving the bone), plus the hook and the modiolus base."""
    ph = np.linspace(0.0, PHI_MAX, 160)
    P, er, f, W, Hc, *_ = co_station(ph)
    hook = co_hook()
    d = _tube_field(vol, np.vstack([hook[:-1], P]),
                    np.concatenate([np.full(len(hook) - 1, 1.0), W]) + grow)
    return d


# =============================================================================== colours
COL = {
    "bone": "#e6dcc3", "petrous": "#eee3c8", "mastoid": "#dccfb1", "air_lining": "#d9a79b", "mucosa": "#e6bdb3",
    "tm": "#cbbfc3", "tm_flac": "#d8a8a6", "malleus": "#f1e6c6", "incus": "#e9dab2", "stapes": "#f4ead0",
    "footplate": "#e7d7a8", "joint": "#b9c3cf", "ligament": "#d9ceb0", "muscle": "#a9453c", "tendon": "#ece5d2",
    "tube": "#d98e8a", "cartilage": "#b7c9d8", "skin": "#e2a88c", "subcut": "#ecc792", "meatus": "#dd9f86",
    "meatus_bony": "#d69a8f", "gland": "#c98a38", "cerumen": "#9a6424", "nerve": "#f2d450", "facial": "#f6e27a",
    "ganglion": "#e3b43c", "chorda": "#eed96c", "perilymph": "#bcdcef", "sv": "#9fd0ea", "st": "#86bedf",
    "endolymph": "#5d7fd0", "utricle": "#6b8bd8", "macula": "#e6be4f", "otolith": "#f3f0e6", "crista": "#e6b84a",
    "cupula": "#e7eef2", "modiolus": "#e9dcc0", "lamina": "#e2d4b4", "rm": "#c9b6ec", "bm": "#ef946d",
    "organ": "#f0c35a", "tect": "#b99ad6", "ligament_sp": "#d7a48d", "helicotrema": "#9ccbe6", "endo_sac": "#7d93cf",
}

DESC = {}          # filled in below, after the geometry


def D(key):
    return DESC.get(key, "")


# =============================================================================== middle ear
def _ossicle_parts():
    parts = []
    # ---- malleus: head in the epitympanum, neck, lateral process at the top of the membrane, handle down to the umbo
    mh = np.array([-1.35, 6.75, -0.95])
    neck = np.array([-1.95, 4.75, -0.65])
    handle = np.array([tm_point(a, 0.12, 0.2 + 0.1 * a / 3.3) for a in np.linspace(3.35, -0.1, 14)])
    hr = np.linspace(0.36, 0.27, len(handle))
    mal = [ellipsoid(mh, (1.05, 1.42, 1.18)), round_cone(neck, mh + np.array([-0.1, -0.7, 0.0]), 0.55, 0.85),
           round_cone(neck, LAT_PROC + TM_OUT * 0.05, 0.5, 0.33),
           round_cone(neck, np.array([-1.8, 5.0, 0.35]), 0.3, 0.12)]
    mal += [round_cone(handle[i], handle[i + 1], hr[i], hr[i + 1]) for i in range(len(handle) - 1)]
    mal.append(round_cone(neck, handle[0], 0.5, 0.36))
    mal.append(ellipsoid(handle[-1], (0.42, 0.32, 0.42), rot=frame_from_normal(TM_IN)))    # spatulate tip at the umbo
    # ---- incus: body articulating with the malleus head, short process back to the fossa incudis, long process down
    ib = np.array([-0.25, 6.55, -3.25])
    lp0 = ib + np.array([0.1, -1.2, 0.1])
    lp1 = np.array([0.35, 3.35, -2.6])
    knob = np.array([1.02, 2.95, -2.45])
    inc = [ellipsoid(ib, (1.08, 1.45, 1.25)), round_cone(ib, np.array([0.1, 6.95, -6.25]), 0.78, 0.33),
           round_cone(lp0, lp1, 0.5, 0.3), round_cone(lp1, knob - np.array([0.25, 0.0, 0.0]), 0.28, 0.22),
           sphere(knob, 0.3)]
    # ---- stapes: head, neck, two crura arching to the footplate in the oval window
    sh = np.array([1.52, 2.93, -2.43])
    sn = np.array([1.95, 2.93, -2.43])
    sta = [ellipsoid(sh, (0.3, 0.34, 0.37)), round_cone(sh, sn, 0.3, 0.22)]
    for side in (1.0, -1.0):
        crus = _spline([sn + np.array([0.0, 0.0, side * 0.12]), np.array([2.7, 2.93, -2.43 + side * 1.0]),
                        np.array([3.55, 2.93, -2.43 + side * 1.28]), np.array([4.18, 2.93, -2.43 + side * 1.18])], 0.08)
        sta += [round_cone(crus[i], crus[i + 1], 0.15, 0.15) for i in range(len(crus) - 1)]
    fp = [ellipsoid(OW, (0.17, 0.74, 1.5))]
    for name, key, shapes, col, lo, hi in (
            ("Malleus", "malleus", mal, COL["malleus"], (-3.9, 1.0, -2.4), (0.2, 8.6, 0.9)),
            ("Incus", "incus", inc, COL["incus"], (-1.6, 2.4, -7.2), (1.6, 8.2, -1.8)),
            ("Stapes", "stapes", sta, COL["stapes"], (1.0, 2.3, -4.0), (4.4, 3.6, -0.8)),
            ("Base (footplate) of stapes", "footplate", fp, COL["footplate"], (4.0, 2.0, -4.1), (4.7, 3.8, -0.7))):
        v = Volume(lo, hi, 0.065)
        v.add_all(shapes, "smooth", 0.12)
        parts.append(sdf_part(v, name, "Auditory ossicles", col, D(key), "bone", smooth=0.8, clip=False,
                              detail=(0.08, 60.0, 0.2, 0)))
    # ---- joints
    parts.append(mesh_part(ellipsoid_mesh((mh + ib) / 2 + np.array([0.35, -0.1, 0.25]), (0.8, 1.0, 0.28), 18),
                           "Incudomallear joint", "Auditory ossicles", COL["joint"], D("im_joint"), "ligament",
                           clip=False))
    parts.append(mesh_part(ellipsoid_mesh((knob + sh) / 2, (0.2, 0.36, 0.38), 14), "Incudostapedial joint",
                           "Auditory ossicles", COL["joint"], D("is_joint"), "ligament", clip=False))
    return parts, mh, ib


def _ligament_parts(mh, ib):
    parts = []
    grp = "Ossicular ligaments & muscles"
    for name, key, a, b, r in (
            ("Superior ligament of malleus", "lig_sup", mh + np.array([0.0, 1.3, 0.0]), (-1.2, 10.35, -1.0), 0.2),
            ("Lateral ligament of malleus", "lig_lat", (-2.2, 4.95, -0.8), (-3.75, 5.2, -0.9), 0.22),
            ("Posterior ligament of incus", "lig_inc", (0.1, 6.95, -6.2), (0.2, 7.05, -7.25), 0.3)):
        parts.append(mesh_part(tube(_spline([a, b], 0.05), np.full(len(_spline([a, b], 0.05)), r), 12),
                               name, grp, COL["ligament"], D(key), "ligament", clip=False))
    # anterior ligament of malleus: from the anterior process forwards; it continues in the removed half
    v = Volume((-2.6, 4.2, -0.5), (-0.9, 5.9, Z_CUT + 0.3), 0.05)
    v.add(round_cone((-1.8, 5.0, 0.2), (-1.7, 5.1, 2.0), 0.26, 0.3))
    parts.append(sdf_part(v.copy(_cut(v, v.d)), "Anterior ligament of malleus", grp, COL["ligament"], D("lig_ant"),
                          "ligament", smooth=0.7))
    # annular ligament: the ring of fibres that seals the footplate into the oval window
    v = Volume(OW - np.array([0.5, 1.2, 2.0]), OW + np.array([0.5, 1.2, 2.0]), 0.04)
    x, y, z = v.axes()
    e_out = np.sqrt(((y - OW[1]) / 0.88) ** 2 + ((z - OW[2]) / 1.64) ** 2) - 1.0
    e_in = np.sqrt(((y - OW[1]) / 0.72) ** 2 + ((z - OW[2]) / 1.48) ** 2) - 1.0
    v.d = np.broadcast_to(np.maximum(np.maximum(e_out * 0.8, -e_in * 0.7), np.abs(x - OW[0]) - 0.2),
                          v.shape).astype(np.float32).copy()
    parts.append(sdf_part(v, "Oval window & annular ligament", grp, COL["joint"], D("annular"), "ligament", smooth=0.6,
                          clip=False))
    # ---- muscles of the middle ear
    tp = tensor_path()
    v = Volume(tp.min(axis=0) - 1.6, np.minimum(tp.max(axis=0) + 1.6, [99, 99, Z_CUT + 0.3]), 0.12)
    v.tube(tp, np.interp(np.linspace(0, 1, len(tp)), [0.0, 0.06, 0.3, 1.0], [0.3, 0.42, 0.75, 0.85]), "smooth", 0.3)
    parts.append(sdf_part(v.copy(_cut(v, v.d)), "Tensor tympani", grp, COL["muscle"], D("tensor"), "muscle", smooth=0.8,
                          detail=(0.08, 70.0, 0.35, 1)))
    ten = _spline([tp[0], (1.2, 3.95, -0.45), tm_point(2.7, 0.2, 0.45)], 0.05)
    parts.append(mesh_part(tube(ten, np.full(len(ten), 0.16), 10), "Tensor tympani tendon", grp, COL["tendon"],
                           D("tensor_t"), "tendon", clip=False))
    sp = stapedius_path()
    parts.append(mesh_part(tube(sp, np.concatenate([[0.35], _fusiform(len(sp) - 1, 0.7, 0.3, 0.6)]), 16),
                           "Stapedius", grp, COL["muscle"], D("stapedius"), "muscle", clip=False,
                           detail=(0.08, 70.0, 0.35, 2)))
    st = _spline([(1.95, 2.35, -5.6), (1.9, 2.75, -4.0), (1.75, 2.95, -2.75)], 0.05)
    parts.append(mesh_part(tube(st, np.full(len(st), 0.12), 10), "Stapedius tendon", grp, COL["tendon"],
                           D("stapedius_t"), "tendon", clip=False))
    return parts


def _tympanic_membrane():
    lo = TM_C - np.array([5.3, 5.3, 5.3])
    hi = np.minimum(TM_C + 5.3, [99, 99, Z_CUT + 0.3])
    v = Volume(lo, hi, 0.1)
    x, y, z = v.axes()
    d = _cut(v, np.broadcast_to(tm_field(x, y, z), v.shape))
    a, b, _ = _tm_coords(x, y, z)
    flaccida, tensa = _split(v, d, [np.maximum(3.95 - a, np.abs(b) - 1.9)])
    return [sdf_part(tensa, "Tympanic membrane – pars tensa", "Middle ear", COL["tm"], D("tm"), "serosa", smooth=0.7,
                     detail=(0.05, 60.0, 0.2, 0)),
            sdf_part(flaccida, "Tympanic membrane – pars flaccida", "Middle ear", COL["tm_flac"], D("tm_flac"),
                     "serosa", smooth=0.7)]


def _cavity_parts():
    parts = []
    v = Volume((-6.2, -7.8, -13.0), (5.9, 11.3, Z_CUT + 0.3), 0.16)
    cav = _exact(v, cavity_field(v), 0.75)
    lining = _cut(v, _shell(cav, 0.3))
    x, y, z = v.axes()
    an, tc = _split(v, lining, [np.maximum(z + 6.3, 4.5 - y)])
    parts.append(sdf_part(tc, "Tympanic cavity (mucosal lining)", "Middle ear", COL["mucosa"], D("cavity"), "mucosa",
                          smooth=0.7, detail=(0.10, 90.0, 0.6, 0)))
    # round window: the secondary tympanic membrane closing the end of the scala tympani
    n = _unit([-0.75, 0.1, -0.35])
    rw = Volume(RW - 1.2, RW + 1.2, 0.04)
    rw.add(ellipsoid(RW + n * 0.1, (0.72, 0.1, 0.72), rot=frame_from_normal(n)))
    parts.append(sdf_part(rw, "Round window (secondary tympanic membrane)", "Middle ear", COL["tm"], D("rw"), "serosa",
                          smooth=0.6, clip=False))
    # pharyngotympanic tube: mucosa-lined lumen, bony then cartilaginous
    tp = tube_path()
    x_ = tp[:, 0]
    r = np.interp(x_, [2.3, 5.0, TUBE_ISTHMUS_X, 16.0, 25.0], [1.5, 1.1, 0.7, 1.05, 1.35])
    tv = Volume(tp.min(axis=0) - 3.2, np.minimum(tp.max(axis=0) + 3.2, [99, 99, Z_CUT + 0.3]), 0.2)
    lumen = _tube_field(tv, tp, r)
    wall = _tube_field(tv, tp, r + 0.35)
    X, Y, Z = tv.axes()
    medial = np.broadcast_to(_medial_of_tm(X, Y, Z), tv.shape)
    muc = _cut(tv, np.maximum.reduce([wall, -lumen, medial]))
    parts.append(sdf_part(tv.copy(muc), "Pharyngotympanic (auditory) tube", "Middle ear", COL["tube"], D("tube"), "mucosa",
                          smooth=0.7, detail=(0.10, 90.0, 0.6, 0)))
    X, Y, Z = tv.axes()
    t = _unit(tp[-1] - tp[0])
    nrm = _unit(np.cross(t, [0.0, 0.0, 1.0]))       # in the coronal plane, perpendicular to the tube
    if nrm[1] > 0:
        nrm = -nrm                                      # points down and laterally (the membranous wall)
    s = (X - tp[0][0]) * nrm[0] + (Y - tp[0][1]) * nrm[1] + (Z - tp[0][2]) * nrm[2]
    shell = np.maximum(_tube_field(tv, tp, r + 1.35), -wall)
    cart = np.maximum(shell, np.maximum(s - 0.55, TUBE_ISTHMUS_X + 0.5 - X))
    parts.append(sdf_part(tv.copy(_cut(tv, cart)), "Tubal cartilage", "Middle ear", COL["cartilage"], D("tube_cart"),
                          "cartilage", smooth=0.8))
    return parts, an, v


def _nerve_tube(path, r, n=14):
    return tube(path, np.broadcast_to(np.asarray(r, float), (len(path),)).copy(), n)


# =============================================================================== bone, skin, meatus
def _block_field(v):
    x, y, z = v.axes()
    top = np.interp(x, [-16, -9, -5, -1, 4, 8, 14, 22, 35], [20.0, 17.0, 12.8, 11.4, 12.6, 13.4, 12.6, 11.0, 7.5])
    bot = np.interp(x, [-16, -5, 2, 8, 16, 24, 35], [-17.0, -15.5, -14.5, -13.2, -13.8, -15.5, -12.5])
    d = np.maximum.reduce([np.broadcast_to(BX0 - x, v.shape), np.broadcast_to(x - BX1, v.shape),
                           np.broadcast_to(y - top, v.shape), np.broadcast_to(bot - y, v.shape),
                           np.broadcast_to(BZ0 - z, v.shape)])
    mp = _stamp(v, [ellipsoid((-8.8, -16.0, -7.0), (5.6, 9.5, 6.0))])
    return smin(d, mp, 4.0)


def _deep_set(v):
    """Everything the bone is dug away from, down to the section plane."""
    d = _stamp(v, bony_labyrinth_shapes(0.45))
    d = np.minimum(d, cochlea_field(v, 0.45))
    d = np.minimum(d, _tube_field(v, np.array([IAM_FUNDUS, IAM_PORUS, (36.0, 2.0, -6.1)]), 2.3))
    d = np.minimum(d, _tube_field(v, facial_path(), 0.95))
    d = np.minimum(d, _tube_field(v, chorda_path(), 0.45))
    d = np.minimum(d, _tube_field(v, stapedius_path(), 0.95))
    ep = endolymphatic_path()
    d = np.minimum(d, _tube_field(v, ep, 0.45))
    d = np.minimum(d, _stamp(v, [ellipsoid(ENDO_SAC, (1.6, 2.6, 0.9))]))
    d = np.minimum(d, _stamp(v, [capsule((-0.7, 7.5, -5.8), (-2.6, 7.8, -8.6), 1.3), sphere((-3.2, 8.0, -9.9), 2.5)]))
    # the superior and inferior vestibular nerves reach the vestibule through the bone of the fundus
    for p in vestibular_paths().values():
        d = np.minimum(d, _tube_field(v, p, 0.55))
    return d


def _air_cells(v, avoid):
    """Mastoid air cells: a honeycomb of mucosa-lined spaces, bigger near the antrum, smaller at the periphery."""
    rng = np.random.default_rng(12)
    region = _stamp(v, [ellipsoid((-8.8, -12.5, -6.2), (5.6, 11.0, 6.8)), ellipsoid((-8.5, 7.5, -6.5), (5.0, 5.0, 6.8)),
                        sphere((-4.0, 8.0, -10.0), 4.6)], 2.0)
    # only cells within reach of the section are modelled: deeper ones would be sealed inside the bone
    _, _, zz = v.axes()
    region = np.maximum(region, np.broadcast_to(-4.5 - zz, v.shape))
    pts = []
    lo, hi = np.array([-15.0, -25.0, -14.5]), np.array([-1.0, 13.0, 2.0])
    cand = lo + rng.random((6000, 3)) * (hi - lo)
    for p in cand:
        spacing = 3.6 if p[1] > -4 else 3.0
        if pts and np.min(np.linalg.norm(np.asarray(pts) - p, axis=1)) < spacing:
            continue
        pts.append(p)
    pts = np.asarray(pts)
    x, y, z = v.axes()
    grid = np.stack(np.broadcast_arrays(x, y, z), -1)
    inside = region < 0.5
    q = grid[inside]
    dd, _ = cKDTree(pts).query(q, k=2)
    cell = np.full(v.shape, 1.0e3, np.float32)
    cell[inside] = 0.2 - (dd[:, 1] - dd[:, 0]) / 2.0
    cell = np.maximum(cell, region)
    cell = np.maximum(cell, 1.1 - avoid)
    return cell.astype(np.float32)


def _bone_parts():
    v = Volume((BX0 - 1.2, -28.5, BZ0 - 0.6), (BX1 + 0.8, 21.2, Z_CUT + 0.6), 0.34)
    block = _block_field(v)
    v.d = block.astype(np.float32)
    v.displace(0.22, 0.22, 3, seed=4)
    block = v.d.copy()
    x, y, z = v.axes()
    tp = tube_path()
    r = np.interp(tp[:, 0], [2.3, 5.0, TUBE_ISTHMUS_X, 16.0, 25.0], [1.5, 1.1, 0.7, 1.05, 1.35])
    direct = np.minimum.reduce([
        cavity_field(v), meatus_field(v), np.broadcast_to(tm_field(x, y, z, 0.05), v.shape),
        ow_window(v), rw_window(v), _tube_field(v, tp, r + 0.35), _tube_field(v, tensor_path(), 1.3)])
    direct = _exact(v, direct)
    deep = _exact(v, _deep_set(v))
    avoid = np.minimum(direct, deep)
    cells = _air_cells(v, avoid)
    carve = np.minimum.reduce([direct, _trough(deep, v.voxel, 17.0, 0.35), cells])
    bone = _cut(v, np.maximum(block, -carve))
    # bone parts: the petrous part medial to the tympanic cavity, the mastoid process below and behind the meatus
    regions = _split(v, bone, [3.0 - x, np.maximum(x - 3.0, y + 4.2 + 0.1 * (x + 8))])
    parts = []
    for pv, name, key, col in zip(regions, ("Petrous part (otic capsule)", "Mastoid process", "Squamous & tympanic parts"),
                                  ("petrous", "mastoid_proc", "squamous"), (COL["petrous"], COL["mastoid"], COL["bone"])):
        parts.append(sdf_part(pv, name, "Temporal bone", col, D(key), "bone", smooth=0.7,
                              detail=(0.10, 18.0, 0.25, 0)))
    mv = Volume((BX0 - 0.6, -27.5, BZ0 - 0.3), (0.5, 14.5, Z_CUT + 0.4), 0.3)
    mx, my, mz = mv.axes()
    m_direct = np.minimum.reduce([cavity_field(mv), meatus_field(mv), _tube_field(mv, tp, r + 0.35)])
    m_cells = _air_cells(mv, np.minimum(m_direct, _deep_set(mv)))
    lining = mv.copy(_cut(mv, np.maximum(_shell(m_cells, 0.36), _block_field(mv) - 0.3)))
    return parts, lining


def _meatus_parts():
    parts = []
    v = Volume((-24.6, -4.8, -6.2), (0.6, 7.2, Z_CUT + 0.3), 0.18)
    x, y, z = v.axes()
    L = meatus_field(v)
    xb = np.broadcast_to(x, v.shape)
    t = np.where(xb < MEATUS_BONY_X, 1.15, 0.32)
    skin = _cut(v, np.maximum(np.maximum(L, -(L + t)), -22.9 - xb))
    # the meatal skin stops at the rim of the tympanic membrane, whose outer layer it becomes
    a_, b_, w_ = _tm_coords(x, y, z)
    rho = np.sqrt((a_ / TM_RA) ** 2 + (b_ / TM_RB) ** 2)
    on_tm = np.maximum((rho - 0.97) * 4.2, tm_depth(a_, b_) - TM_T / 2 - 0.45 - w_)
    skin = np.maximum(skin, -np.broadcast_to(on_tm, v.shape))
    c, b = _split(v, skin, [xb - MEATUS_BONY_X])
    parts.append(sdf_part(c, "External acoustic meatus – cartilaginous part", "External ear", COL["meatus"], D("eam_c"),
                          "skin", smooth=0.8, detail=(0.10, 80.0, 0.55, 0)))
    parts.append(sdf_part(b, "External acoustic meatus – bony part", "External ear", COL["meatus_bony"], D("eam_b"),
                          "skin", smooth=0.8, detail=(0.10, 80.0, 0.55, 0)))
    # meatal cartilage: a gutter, open posterosuperiorly, continuous with the cartilage of the tragus
    yc, zc = 1.5, -0.8
    gap = ((y - yc) * 0.75 - (z - zc) * 0.65) - 1.4
    cart = np.maximum.reduce([L - 1.05, -(L + 0.02), np.broadcast_to(-gap, v.shape), np.broadcast_to(xb - (MEATUS_BONY_X - 0.2), v.shape),
                              np.broadcast_to(-23.2 - xb, v.shape)])
    parts.append(sdf_part(v.copy(_cut(v, cart)), "Meatal cartilage", "External ear", COL["cartilage"], D("meatal_cart"),
                          "cartilage", smooth=0.8))
    # ceruminous and sebaceous glands in the thick skin of the cartilaginous part
    rng = np.random.default_rng(5)
    path = meatus_path()
    seg = path[(path[:, 0] > -23.2) & (path[:, 0] < MEATUS_BONY_X - 0.4)]
    shapes = []
    for k in range(95):
        i = rng.integers(1, len(seg) - 1)
        tt = _unit(seg[i + 1] - seg[i - 1])
        e1, e2 = _basis(tt)
        ang = rng.uniform(0, 2 * math.pi)
        rr = np.interp(seg[i][0], [-23.5, -20.0, -15.5], [4.0, 3.8, 3.5])
        dvec = e1 * math.cos(ang) + e2 * math.sin(ang)
        c0 = seg[i] + dvec * (rr - rng.uniform(0.35, 0.6))
        for j in range(3):
            shapes.append(sphere(c0 + rng.normal(0, 0.12, 3), rng.uniform(0.11, 0.17)))
    gv = v.copy(np.full(v.shape, 1.0e3, np.float32))
    gv.add_all(shapes, "smooth", 0.06)
    parts.append(sdf_part(gv.copy(_cut(v, np.maximum(gv.d, L + 0.05))), "Ceruminous & sebaceous glands", "External ear",
                          COL["gland"], D("cerumin"), "gland", smooth=0.6))
    # a little cerumen on the floor of the lateral meatus
    wax = v.copy(np.full(v.shape, 1.0e3, np.float32))
    for p, s in (((-21.0, -1.6, -1.3), (1.4, 0.35, 0.9)), ((-19.2, -1.75, -1.8), (0.9, 0.3, 0.7)),
                 ((-17.5, -1.6, -0.9), (0.7, 0.25, 0.5))):
        wax.add(ellipsoid(p, s), "smooth", 0.2)
    parts.append(sdf_part(wax.copy(_cut(v, np.maximum(wax.d, -(L + 1.0)))), "Cerumen (earwax)", "External ear",
                          COL["cerumen"], D("cerumen"), "gland", smooth=0.7))
    return parts


def _skin_parts():
    v = Volume((SKIN_X - 1.2, -30.5, BZ0 - 0.6), (BX0 + 0.9, 22.5, Z_CUT + 0.6), 0.45)
    x, y, z = v.axes()
    d = np.maximum.reduce([np.broadcast_to(SKIN_X - x, v.shape), np.broadcast_to(x - (BX0 + 0.35), v.shape),
                           np.broadcast_to(y - 21.5, v.shape), np.broadcast_to(-29.5 - y, v.shape),
                           np.broadcast_to(BZ0 - z, v.shape)])
    v.d = d.astype(np.float32)
    v.displace(0.25, 0.15, 3, seed=9)
    d = np.maximum(v.d, -(meatus_field(v) - 0.0))
    d = np.maximum(d, -(meatus_field(v, 1.05)))
    d = _cut(v, d)
    xb = np.broadcast_to(x, v.shape)
    sk, sub = _split(v, d, [xb - (SKIN_X + 1.6)])
    return [sdf_part(sk, "Skin of the side of the head", "Surrounding tissues", COL["skin"], D("skin"), "skin",
                     smooth=0.8),
            sdf_part(sub, "Subcutaneous tissue", "Surrounding tissues", COL["subcut"], D("subcut"), "fat", smooth=0.8)]


# =============================================================================== inner ear
VIII_AXIS = (np.array([36.0, 2.2, -6.9]), np.array([21.0, 2.2, -6.9]))


def vestibular_paths():
    """The two divisions of the vestibular nerve and their end branches to the five sensory patches."""
    sup_b = np.array([9.9, 4.0, -5.6])
    inf_b = np.array([9.4, 2.1, -5.6])
    utr = UTRICLE[0] + np.array([0.0, -0.45, 0.0])
    sac = SACCULE[0] + np.array([0.38, 0.0, 0.0])
    return {
        "trunk": _spline([VIII_AXIS[1] + np.array([0.0, 0.5, -0.4]), (16.0, 3.1, -7.6), (13.5, 3.1, -7.6)], 0.1),
        "sup": _spline([(13.5, 3.1, -7.6), (12.0, 3.4, -7.6), sup_b], 0.08),
        "inf": _spline([(13.5, 3.1, -7.6), (12.0, 2.1, -7.6), inf_b], 0.08),
        "utr": _spline([sup_b, (8.3, 4.4, -3.9), utr], 0.15),
        "ampA": _spline([sup_b, (7.9, 6.3, -2.9), AMP["anterior"][0]], 0.15),
        "ampL": _spline([sup_b, (7.6, 6.4, -2.6), AMP["lateral"][0]], 0.15),
        "sac": _spline([inf_b, (7.8, 1.9, -3.4), sac], 0.15),
        "ampP": _spline([inf_b, (8.3, 2.0, -5.3), AMP["posterior"][0]], 0.15),
    }


def cochlear_nerve_path():
    return _spline([VIII_AXIS[1] + np.array([0.0, -0.5, 0.7]), (16.0, 1.3, -5.9), (13.2, 0.3, -6.3),
                    CO_BASE + CO_AX * 0.25], 0.1)


def _lathe(base, axis, hs, rs, n=40):
    e1, e2 = _basis(axis, (1.0, 0.0, 0.0))
    ang = np.linspace(0, 2 * math.pi, n, endpoint=False)
    ring = np.cos(ang)[:, None] * e1 + np.sin(ang)[:, None] * e2
    pos = (base[None, None, :] + np.asarray(hs)[:, None, None] * axis[None, None, :]
           + np.asarray(rs)[:, None, None] * ring[None, :, :])
    m = len(hs)
    a = np.arange(m * n).reshape(m, n)
    q0, q1 = a[:-1].ravel(), np.roll(a[:-1], -1, axis=1).ravel()
    q2, q3 = np.roll(a[1:], -1, axis=1).ravel(), a[1:].ravel()
    tris = [np.stack([q0, q1, q2], 1), np.stack([q0, q2, q3], 1)]
    pts = pos.reshape(-1, 3)
    c0, c1 = len(pts), len(pts) + 1
    pts = np.vstack([pts, base + axis * hs[0], base + axis * hs[-1]])
    i = np.arange(n)
    tris.append(np.stack([np.full(n, c0), a[0, (i + 1) % n], a[0, i]], 1))
    tris.append(np.stack([np.full(n, c1), a[-1, i], a[-1, (i + 1) % n]], 1))
    return orient_outward(Mesh().add(pts, np.vstack(tris)))


def _co_line(phis, hook=False):
    """Stations along the cochlear canal (optionally preceded by the basal hook, which keeps the basal section)."""
    P, er, f, W, Hc, *_ = co_station(phis)
    if not hook:
        return P, er, f, W, Hc
    hp = co_hook()[:-1]
    q = hp - CO_BASE
    q -= np.einsum("ij,j->i", q, CO_AX)[:, None] * CO_AX[None]
    her = q / np.linalg.norm(q, axis=1, keepdims=True)
    k = len(hp)
    return (np.vstack([hp, P]), np.vstack([her, er]), np.concatenate([np.zeros(k), f]),
            np.concatenate([np.full(k, W[0]), W]), np.concatenate([np.full(k, Hc[0]), Hc]))


def _co_loft(key, phis, hook=False, extend=0.0):
    P, er, f, W, Hc = _co_line(np.asarray(phis, float), hook)
    if extend:
        t = np.gradient(P, axis=0)
        t /= np.linalg.norm(t, axis=1, keepdims=True)
        P = P.copy()
        P[0] -= t[0] * extend
        P[-1] += t[-1] * extend
    secs = np.array([co_sections(fi, wi, hi)[key] for fi, wi, hi in zip(f, W, Hc)])
    return _loft(secs, P, er, np.broadcast_to(CO_AX, P.shape).copy())


def _inner_ear_parts():
    parts = []
    g_bony = "Inner ear – bony labyrinth"
    g_mem = "Inner ear – membranous labyrinth"
    g_n = "Nerves"
    # ---------------------------------------------------------------- bony labyrinth (perilymphatic space)
    allp = np.vstack([p for p, _ in CANALS.values()])
    lo = np.minimum(allp.min(axis=0), VEST - 2.6) - 1.2
    hi = np.maximum(allp.max(axis=0), VEST + 2.6) + 1.2
    bv = Volume(lo, hi, 0.14)
    bv.add_all(bony_labyrinth_shapes(0.0), "smooth", 0.25)
    bony = bv.mesh(0.8)
    s0, s1 = SECTOR
    bony.extend(_co_loft("canal", np.linspace(0.0, s0, 26), hook=True))
    bony.extend(_co_loft("canal", np.linspace(s1, PHI_HEL, 260)))
    parts.append(mesh_part(bony, "Bony labyrinth (perilymph)", g_bony, COL["perilymph"], D("bony_lab"), "csf",
                           alpha=0.3, rank=1.0))
    hel = _co_loft("canal", np.linspace(PHI_HEL - 0.02, PHI_MAX, 30))
    Pm, erm, fm, Wm, Hm = _co_line(np.array([PHI_MAX - 0.01, PHI_MAX]))
    tm_ = _unit(Pm[1] - Pm[0])
    hel.extend(ellipsoid_mesh(Pm[1], (Wm[1] + 0.02, Hm[1] + 0.02, Wm[1] * 0.7), 16,
                              rotation=np.column_stack([erm[1], CO_AX, tm_])))
    parts.append(mesh_part(hel, "Helicotrema", g_bony, COL["helicotrema"], D("helicotrema"), "csf", alpha=0.5))
    # the opened stretch of the basal turn: the two perilymphatic scalae as solids
    ph = np.linspace(s0, s1, 40)
    parts.append(mesh_part(_co_loft("sv", ph), "Scala vestibuli (perilymph)", g_bony, COL["sv"], D("sv"), "csf",
                           alpha=0.8))
    parts.append(mesh_part(_co_loft("st", ph), "Scala tympani (perilymph)", g_bony, COL["st"], D("st"), "csf",
                           alpha=0.8))
    parts.append(mesh_part(_co_loft("lamina", np.linspace(0.02, PHI_HEL, 300)), "Osseous spiral lamina", g_bony,
                           COL["lamina"], D("lamina"), "bone"))
    # modiolus: the spongy bony core, a cone whose surface is the inner wall of every turn
    f = np.linspace(0.0, 1.0, 60)
    Hs = 0.9 + 3.5 * f ** 0.85
    Rs = 3.0 * (1.0 - 0.68 * f ** 0.9) - (1.0 - 0.45 * f) + 0.06
    hs = np.concatenate([[0.0, 0.45], Hs, [Hs[-1] + 0.35]])
    rs = np.concatenate([[2.25, 2.1], Rs, [0.12]])
    parts.append(mesh_part(_lathe(CO_BASE, CO_AX, hs, rs), "Modiolus", g_bony, COL["modiolus"], D("modiolus"), "bone",
                           detail=(0.10, 40.0, 0.25, 0)))
    # ---------------------------------------------------------------- cochlear duct and its walls
    parts.append(mesh_part(_co_loft("duct", np.linspace(0.14, PHI_HEL + 0.25, 320)),
                           "Cochlear duct (scala media, endolymph)", g_mem, COL["endolymph"], D("duct"), "csf"))
    parts.append(mesh_part(_co_loft("bm", np.linspace(0.14, PHI_HEL + 0.2, 320)), "Basilar membrane", g_mem, COL["bm"],
                           D("bm"), "fascia"))
    parts.append(mesh_part(_co_loft("rm", ph, extend=0.01), "Vestibular (Reissner) membrane", g_mem, COL["rm"], D("rm"),
                           "serosa"))
    parts.append(mesh_part(_co_loft("organ", ph, extend=0.012), "Spiral organ (of Corti)", g_mem, COL["organ"],
                           D("organ"), "organ"))
    parts.append(mesh_part(_co_loft("tect", ph, extend=0.014), "Tectorial membrane", g_mem, COL["tect"], D("tect"),
                           "serosa"))
    # ---------------------------------------------------------------- vestibular membranous labyrinth
    ep = endolymphatic_path()
    lo = np.minimum(lo, ENDO_SAC - 2.8)
    hi = np.maximum(hi, ENDO_SAC + 1.0)
    mv = Volume(lo, hi, 0.07)
    ducts = duct_paths()
    comp = {}
    comp["ducts"] = np.minimum.reduce([_tube_field(mv, p, R_DUCT) for p in ducts.values()])
    amp_shapes = []
    for key, (p, t, o) in AMP.items():
        across = np.cross(t, o)
        amp_shapes.append(ellipsoid(p + o * 0.1, (0.46, 0.5, 0.78), rot=np.column_stack([across, o, t])))
    comp["amp"] = _stamp(mv, amp_shapes)
    comp["utricle"] = _stamp(mv, [ellipsoid(*UTRICLE)])
    sac_c, sac_r = SACCULE
    d0 = co_station(0.2)
    reun = _spline([sac_c + np.array([0.1, -0.6, -0.3]), sac_c + np.array([0.6, -1.8, -1.6]),
                    d0[0][0] + CO_AX * 0.35], 0.05)
    comp["saccule"] = np.minimum(_stamp(mv, [ellipsoid(sac_c, sac_r)]), _tube_field(mv, reun, 0.13))
    us = _spline([sac_c + np.array([0.3, 0.4, -0.3]), VEST + np.array([1.0, -0.3, -0.8]),
                  UTRICLE[0] + np.array([0.35, -0.5, -0.4])], 0.05)
    comp["endo"] = np.minimum.reduce([_tube_field(mv, ep, 0.2), _tube_field(mv, us, 0.12),
                                      _stamp(mv, [ellipsoid(ENDO_SAC, (1.25, 2.2, 0.42),
                                                            rot=frame_from_normal(_unit([0.3, 0.0, 1.0])))])])
    keys = list(comp)
    stack = np.stack([comp[k] for k in keys])
    label = np.argmin(stack, axis=0)
    field = stack[0]
    for k in range(1, len(keys)):
        field = smin(field, stack[k], 0.1)
    names = {"ducts": ("Semicircular ducts", COL["endolymph"], 1.0),
             "amp": ("Membranous ampullae", COL["utricle"], 0.5),
             "utricle": ("Utricle", COL["utricle"], 0.5), "saccule": ("Saccule", COL["utricle"], 0.5),
             "endo": ("Endolymphatic duct & sac", COL["endo_sac"], 1.0)}
    for i, k in enumerate(keys):
        name, col, alpha = names[k]
        pv = mv.copy(np.where(label == i, field, np.maximum(field, 0.004)))
        parts.append(sdf_part(pv, name, g_mem, col, D(k), "csf", smooth=0.8, alpha=alpha))
    # cristae and cupulae inside the ampullae
    cr, cu = Mesh(), Mesh()
    for key, (p, t, o) in AMP.items():
        across = np.cross(t, o)
        rot = np.column_stack([across, o, t])
        c = p + o * 0.1
        cr.extend(ellipsoid_mesh(c - o * 0.3, (0.40, 0.2, 0.11), 14, rotation=rot))
        cu.extend(ellipsoid_mesh(c + o * 0.08, (0.36, 0.34, 0.075), 14, rotation=rot))
    parts.append(mesh_part(cr, "Cristae ampullares", g_mem, COL["crista"], D("crista"), "organ", clip=False))
    parts.append(mesh_part(cu, "Cupulae", g_mem, COL["cupula"], D("cupula"), "csf", alpha=0.55, clip=False))
    # maculae: the utricular macula lies in the floor (horizontal), the saccular on the medial wall (vertical)
    uc, _ = UTRICLE
    mac_u = (uc + np.array([0.0, -0.5, 0.15]), np.eye(3), (0.5, 0.05, 0.88))
    mac_s = (sac_c + np.array([0.34, 0.0, 0.0]), np.column_stack([[0, 1, 0], [1, 0, 0], [0, 0, 1]]).astype(float),
             (0.5, 0.05, 0.38))
    mac, oto = Mesh(), Mesh()
    rng = np.random.default_rng(3)
    for c, rot, rad in (mac_u, mac_s):
        mac.extend(ellipsoid_mesh(c, rad, 16, rotation=rot))
        up = rot[:, 1]
        if np.dot(up, c - (uc if c[1] > VEST[1] else sac_c)) > 0:
            up = -up
        top = c + up * 0.1
        oto.extend(ellipsoid_mesh(top, (rad[0] * 0.92, 0.035, rad[2] * 0.92), 14, rotation=rot))
        for _ in range(110):
            u, w = rng.uniform(-1, 1, 2)
            if u * u + w * w > 0.9:
                continue
            q = top + rot[:, 0] * u * rad[0] * 0.85 + rot[:, 2] * w * rad[2] * 0.85 + up * 0.04
            oto.extend(ellipsoid_mesh(q, rng.uniform(0.018, 0.034, 3), 5, rotation=frame_from_normal(rng.normal(size=3))))
    parts.append(mesh_part(mac, "Maculae (utricle & saccule)", g_mem, COL["macula"], D("macula"), "organ", clip=False))
    parts.append(mesh_part(oto, "Otolithic membranes & otoliths", g_mem, COL["otolith"], D("otolith"), "organ",
                           clip=False))
    # ---------------------------------------------------------------- nerves
    vp = vestibular_paths()
    ves = Mesh()
    for k, p in vp.items():
        r = {"trunk": 0.85, "sup": 0.55, "inf": 0.5}.get(k, 0.2)
        ves.extend(_nerve_tube(p, r))
    parts.append(mesh_part(ves, "Vestibular nerve (superior & inferior divisions)", g_n, COL["nerve"], D("vest_n"),
                           "nerve"))
    parts.append(mesh_part(ellipsoid_mesh(np.array([15.6, 1.9, -7.2]), (1.6, 1.05, 1.05), 16),
                           "Vestibular (Scarpa) ganglion", g_n, COL["ganglion"], D("scarpa"), "nerve"))
    cp = cochlear_nerve_path()
    parts.append(mesh_part(_nerve_tube(cp, np.interp(np.arange(len(cp)), [0, len(cp) - 1], [0.8, 0.95])),
                           "Cochlear nerve", g_n, COL["nerve"], D("coch_n"), "nerve"))
    trunk = _spline([VIII_AXIS[0], VIII_AXIS[1] + np.array([-0.6, 0.0, 0.0])], 0.2)
    parts.append(mesh_part(_nerve_tube(trunk, 1.25, 20), "Vestibulocochlear nerve (VIII)", g_n, COL["nerve"], D("viii"),
                           "nerve"))
    P, er, f, W, Hc = _co_line(np.linspace(0.05, 1.7 * 2 * math.pi, 200))
    gang = P + er * (-W - 0.08)[:, None] + CO_AX * (-0.12 * Hc)[:, None]
    parts.append(mesh_part(_nerve_tube(gang, np.interp(f, [0, 0.7], [0.24, 0.16]), 10), "Spiral ganglion", g_n,
                           COL["ganglion"], D("spiral_g"), "nerve"))
    fp = facial_path()
    parts.append(mesh_part(_nerve_tube(fp, 0.55, 16), "Facial nerve (VII)", g_n, COL["facial"], D("facial"), "nerve"))
    parts.append(mesh_part(ellipsoid_mesh(GENICULATE, (0.8, 0.7, 0.75), 16), "Geniculate ganglion", g_n,
                           COL["ganglion"], D("geniculate"), "nerve"))
    parts.append(mesh_part(_nerve_tube(chorda_path(), 0.22, 10), "Chorda tympani", g_n, COL["chorda"], D("chorda"),
                           "nerve"))
    return parts


# =============================================================================== assembly
def _to_model(parts):
    for p in parts:
        m = Mesh()
        for pos, nrm, idx in p.mesh.parts:
            m.parts.append((((pos - ORIGIN) * MM).astype(np.float32), nrm, idx))
        p.mesh = m
    return parts


def build_ear():
    parts = []
    parts += _auricle_parts()
    parts += _meatus_parts()
    oss, mh, ib = _ossicle_parts()
    parts += _tympanic_membrane()
    cav, antrum_lining, cav_v = _cavity_parts()
    parts += cav
    bone, cells_lining = _bone_parts()
    mastoid = sdf_part(cells_lining, "Mastoid antrum & air cells", "Middle ear", COL["air_lining"],
                       D("air_cells"), "mucosa", smooth=0.7)
    mastoid.mesh.extend(antrum_lining.mesh(0.7))
    parts.append(mastoid)
    parts += oss
    parts += _ligament_parts(mh, ib)
    parts += _inner_ear_parts()
    parts += bone
    parts += _skin_parts()
    parts += _inset_cochlea()
    parts += _inset_crista()
    parts += _inset_macula()
    return _to_model(parts)


# =============================================================================== auricle
AU_O = np.array([-21.6, 1.2, -0.9])                  # the concha opening of the meatus
AU_U = _unit([-0.42, 0.0, -0.91])                    # backwards (and away from the head: the auricle stands off it)
AU_V = np.array([0.0, 1.0, 0.0])
AU_W = np.cross(AU_U, AU_V)                          # lateral surface normal
if AU_W[0] > 0:
    AU_W = -AU_W

AU_OUTLINE = np.array([
    (-5.5, -9.0), (-6.0, -2.0), (-5.8, 5.0), (-5.0, 11.0), (-4.0, 17.0), (-2.0, 22.5), (1.5, 27.5), (6.0, 30.5),
    (11.0, 31.5), (16.0, 30.0), (20.5, 26.0), (23.5, 20.0), (25.0, 13.0), (25.0, 6.0), (23.8, -1.0), (21.5, -7.0),
    (18.5, -12.5), (15.5, -18.0), (13.5, -23.0), (11.0, -27.5), (7.5, -30.0), (3.5, -29.5), (0.5, -26.5),
    (-1.5, -21.5), (-3.2, -16.0), (-4.5, -12.0)])
AU_ANTIHELIX = [np.array([(13.5, -11.5), (15.0, -3.0), (15.4, 5.0), (14.0, 11.0)]),
                np.array([(14.0, 11.0), (12.2, 17.0), (9.6, 23.5)]),
                np.array([(14.0, 11.0), (9.0, 13.6), (3.0, 15.2)])]
AU_TRAGUS = (np.array([-2.5, -1.2]), 2.6, np.array([2.4, 4.8, 1.8]))
AU_ANTITRAGUS = (np.array([8.8, -12.3]), 2.3, np.array([3.4, 2.4, 2.2]))


def _seg_dist2(u, v, poly):
    """Distance from (u, v) arrays to a 2D polyline."""
    best = np.full(np.shape(u), 1.0e3)
    for (a0, b0), (a1, b1) in zip(poly[:-1], poly[1:]):
        du, dv = a1 - a0, b1 - b0
        t = np.clip(((u - a0) * du + (v - b0) * dv) / (du * du + dv * dv), 0.0, 1.0)
        best = np.minimum(best, np.hypot(u - a0 - t * du, v - b0 - t * dv))
    return best


def _poly_sd(u, v, poly):
    """Signed distance to a closed 2D polygon (negative inside)."""
    closed = np.vstack([poly, poly[:1]])
    d = _seg_dist2(u, v, closed)
    inside = _pip(poly, np.stack([np.ravel(u), np.ravel(v)], -1)).reshape(np.shape(u))
    return np.where(inside, -d, d)


def _au_height(u, v):
    """Lateral surface of the auricle: w as a function of (u, v). Concha deep, antihelix raised, scapha and
    triangular fossa in between; the lobule is a thick soft flap."""
    h = 3.0 + 0.06 * u
    rc = np.sqrt(((u - 5.0) / 8.6) ** 2 + ((v + 1.2) / 10.6) ** 2)
    h = h - 4.6 * _smooth01((1.0 - rc) / 0.4)
    for line in AU_ANTIHELIX:
        d = _seg_dist2(u, v, line)
        h = np.maximum(h, 3.0 + 0.06 * u + 2.3 * np.exp(-(d / 2.0) ** 2) - 4.6 * _smooth01((1.0 - rc) / 0.4) * 0.6)
    fossa = np.sqrt(((u - 7.5) / 3.6) ** 2 + ((v - 18.5) / 3.0) ** 2)
    h = h - 1.0 * _smooth01((1.0 - fossa) / 0.5)
    return h


def _au_thick(u, v):
    return 2.3 + 2.6 * _smooth01((-14.0 - v) / 6.0)


def helix_path():
    """The rolled rim: from the crus of the helix in the concha, up the front, over the top and down the back to the
    tail of the helix above the lobule."""
    ol = AU_OUTLINE
    i0, i1 = 3, 18
    rim = ol[i0:i1 + 1]
    n = np.zeros_like(rim)
    for k in range(len(rim)):
        a = ol[(i0 + k - 1) % len(ol)]
        b = ol[(i0 + k + 1) % len(ol)]
        t = _unit(b - a)
        n[k] = [t[1], -t[0]]                      # inward normal (outline runs clockwise in u-v)
    inset = rim + n * 2.2
    crus = np.array([(4.5, 4.2), (1.0, 6.8), (-2.2, 10.0)])
    uv = np.vstack([crus, inset[1:]])
    path2 = smooth_path(uv, 160)
    w = _au_height(path2[:, 0], path2[:, 1]) + 0.2
    w[:12] = np.linspace(-0.4, w[12], 12)            # the crus rises out of the concha floor
    return AU_O + path2[:, 0:1] * AU_U + path2[:, 1:2] * AU_V + w[:, None] * AU_W, path2


def _auricle_parts():
    corners = []
    for uu in (-8.0, 27.5):
        for vv in (-32.5, 33.5):
            for ww in (-9.0, 10.0):
                corners.append(AU_O + uu * AU_U + vv * AU_V + ww * AU_W)
    corners = np.array(corners)
    lo, hi = corners.min(axis=0), corners.max(axis=0)
    hi[0] = min(hi[0], SKIN_X + 1.2)
    v = Volume(lo, hi, 0.46)
    X, Y, Z = v.axes()
    qx, qy, qz = X - AU_O[0], Y - AU_O[1], Z - AU_O[2]
    U = qx * AU_U[0] + qy * AU_U[1] + qz * AU_U[2]
    Vv = np.broadcast_to(qy, np.broadcast(qx, qy, qz).shape)
    W = qx * AU_W[0] + qy * AU_W[1] + qz * AU_W[2]
    U, Vv, W = np.broadcast_arrays(U, Vv, W)
    # the (u, v) quantities are evaluated on a 2D grid and looked up per voxel
    g = 0.2
    gu = np.arange(-9.0, 29.0, g)
    gv = np.arange(-34.0, 35.0, g)
    GU, GV = np.meshgrid(gu, gv, indexing="ij")
    grids = {"h": _au_height(GU, GV), "t": _au_thick(GU, GV),
             "out": _poly_sd(GU, GV, smooth_path(np.vstack([AU_OUTLINE, AU_OUTLINE[:2]]), 400)[:-40]),
             "ah": np.minimum.reduce([_seg_dist2(GU, GV, ln) for ln in AU_ANTIHELIX])}
    coords = np.stack([(U - gu[0]) / g, (Vv - gv[0]) / g])

    def look(key):
        return ndimage.map_coordinates(grids[key], coords.reshape(2, -1), order=1, mode="nearest").reshape(U.shape)
    h, t, out, ah = look("h"), look("t"), look("out"), look("ah")
    plate = np.maximum(np.abs(W - (h - t / 2)) - t / 2, out + 0.4)
    hp, hp2 = helix_path()
    helix = _tube_field(v, hp, np.interp(np.arange(len(hp)), [0, 20, len(hp) - 30, len(hp) - 1],
                                         [1.2, 2.2, 2.2, 1.4]))
    tc, tw, tr = AU_TRAGUS
    trag_c = AU_O + tc[0] * AU_U + tc[1] * AU_V + tw * AU_W
    rot = np.column_stack([AU_U, AU_V, AU_W])
    tragus = _stamp(v, [ellipsoid(trag_c, tr, rot=rot)])
    ac, aw, ar = AU_ANTITRAGUS
    anti_c = AU_O + ac[0] * AU_U + ac[1] * AU_V + aw * AU_W
    antitragus = _stamp(v, [ellipsoid(anti_c, ar, rot=rot)])
    w_head = ((SKIN_X + 0.6) - AU_O[0] - U * AU_U[0]) / AU_W[0]
    ell = np.sqrt(((U - 4.5) / 11.5) ** 2 + ((Vv + 0.5) / 15.0) ** 2) - 1.0
    attach = np.maximum.reduce([ell * 6.0, W - (h - t + 0.6), w_head - W])
    body = smin(smin(smin(plate, helix, 1.0), smin(tragus, antitragus, 0.8), 0.9), attach, 2.2)
    vv = v.copy(body.astype(np.float32))
    vv.displace(0.12, 0.35, 2, seed=21)
    lumen = meatus_field(v, -1.15)
    body = np.maximum(vv.d, -lumen)
    # elastic cartilage: everything but the lobule, under ~0.8 mm of skin
    cart = np.maximum(smin(smin(plate, helix, 1.0), smin(tragus, antitragus, 0.8), 0.9) + 1.0, -14.0 - Vv)
    cart = np.maximum(cart, -(lumen - 0.9))
    skin = np.maximum(body, -cart)
    parts = [sdf_part(v.copy(cart.astype(np.float32)), "Auricular cartilage (elastic)", "External ear", COL["cartilage"],
                      D("au_cart"), "cartilage", smooth=0.8, detail=(0.07, 45.0, 0.5, 0))]
    # the surface regions of the auricle, in order of precedence
    rc = np.sqrt(((U - 5.0) / 8.6) ** 2 + ((Vv + 1.2) / 10.6) ** 2)
    regions = _split(v, skin, [tragus - 1.2, antitragus - 1.0, Vv + 15.0, helix - 1.1, W - (h - t - 0.4),
                               (rc - 0.92) * 9.0, ah - 3.0])
    names = (("Tragus", "tragus", "#e2a48a"), ("Antitragus", "antitragus", "#e0a288"),
             ("Lobule of auricle", "lobule", "#e8ae96"), ("Helix", "helix", "#e3a58b"),
             ("Cranial surface of auricle", "au_back", COL["skin"]), ("Concha of auricle", "concha", "#d99a84"),
             ("Antihelix", "antihelix", "#e6ae94"), ("Scapha & triangular fossa", "scapha", "#dea189"))
    for pv, (name, key, c) in zip(regions, names):
        parts.append(sdf_part(pv, name, "External ear", c, D(key), "skin", smooth=0.9, detail=(0.08, 60.0, 0.4, 0)))
    return parts


# =============================================================================== inset 1: one turn of the cochlea
# Magnified ~x10 (the organ of Corti and its cells a further ~x3 so that single cells read). Section coordinates
# (u outwards from the modiolus, v towards the apex) are in inset millimetres; the section is swept backwards round
# the modiolar axis through INS1_SPAN, so its front face is a cut through one turn, like a slide.
INS1_C = np.array([51.0, 14.5, -2.0])          # centre of the canal on the front face
INS1_R = 28.0                                   # radius of the turn (to the canal centre)
INS1_SPAN = math.radians(22.0)
INS1_K = 0.8                                    # the whole inset is drawn at 0.8 of these sizes (~x8)
IV0 = -1.0                                      # level of the basilar membrane


def _seg_sd(u, v, a, b, r):
    """Distance to a 2D segment minus r (a capsule)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    t = np.clip(((u - a[0]) * d[0] + (v - a[1]) * d[1]) / float(d @ d), 0.0, 1.0)
    return np.hypot(u - a[0] - t * d[0], v - a[1] - t * d[1]) - r


def _ell_sd(u, v, c, a, b):
    """Approximate signed distance to an ellipse (scaled radial distance)."""
    k = np.sqrt(((u - c[0]) / a) ** 2 + ((v - c[1]) / b) ** 2)
    return (k - 1.0) * min(a, b)


def _box_sd(u, v, u0, u1, v0, v1, r=0.0):
    cu, cv = (u0 + u1) / 2, (v0 + v1) / 2
    hu, hv = (u1 - u0) / 2 - r, (v1 - v0) / 2 - r
    qu, qv = np.abs(u - cu) - hu, np.abs(v - cv) - hv
    return np.hypot(np.maximum(qu, 0), np.maximum(qv, 0)) + np.minimum(np.maximum(qu, qv), 0) - r


RM_A = np.array([-5.8, IV0 + 2.15])             # vestibular membrane: from the limbus ...
RM_B = np.array([5.3, 7.2])                   # ... to the outer wall above the stria
TUNNEL = np.array([(-1.15, IV0 + 0.18), (0.35, IV0 + 0.18), (-0.45, IV0 + 1.75)])
IHC_U = -1.95
OHC_U = (0.95, 1.65, 2.35)


def _ins1_fields(U, V):
    """2D signed-distance fields of every compartment of the magnified section."""
    f = {}
    oval = _ell_sd(U, V, (0, 0), 10.0, 8.5)
    lig_out = _ell_sd(U, V, (0.4, 0.3), 12.4, 9.6)
    f["lig"] = np.maximum.reduce([lig_out, -oval, -U + 1.5, _box_sd(U, V, 0, 20, -6.8, 7.6, 1.0)])
    rm_side = ((U - RM_A[0]) * (RM_B[1] - RM_A[1]) - (V - RM_A[1]) * (RM_B[0] - RM_A[0])) / \
        np.hypot(*(RM_B - RM_A))                    # > 0 below the membrane (duct side)
    f["rm"] = _seg_sd(U, V, RM_A, RM_B, 0.11)
    f["bm"] = _box_sd(U, V, -3.3, 9.7, IV0 - 0.13, IV0 + 0.13)
    f["bm"] = np.maximum(f["bm"], oval + 0.02)
    plate = _box_sd(U, V, -15.0, -3.2, IV0 - 0.6, IV0 + 0.6, 0.25)
    chan = _box_sd(U, V, -14.0, -3.6, IV0 - 0.17, IV0 + 0.17)
    f["lamina"] = np.maximum(plate, -chan)
    limb = np.maximum(_ell_sd(U, V, (-5.9, IV0 + 0.5), 2.5, 1.65), IV0 + 0.45 - V)
    sulcus = _ell_sd(U, V, (-2.85, IV0 + 1.05), 0.95, 0.75)
    f["limbus"] = np.maximum(limb, -sulcus)
    organ_poly = np.array([(-3.15, IV0 + 0.13), (-3.05, IV0 + 0.75), (-2.6, IV0 + 1.55), (-1.6, IV0 + 2.05),
                           (-0.3, IV0 + 2.2), (1.0, IV0 + 2.35), (2.6, IV0 + 2.42), (3.7, IV0 + 2.3),
                           (4.5, IV0 + 1.7), (5.1, IV0 + 1.05), (6.2, IV0 + 0.7), (7.8, IV0 + 0.45),
                           (8.8, IV0 + 0.3), (8.9, IV0 + 0.13)])
    organ = _poly_sd(U, V, organ_poly)
    tun = _poly_sd(U, V, TUNNEL)
    pillars = np.minimum(_seg_sd(U, V, TUNNEL[0] + (-0.1, 0), TUNNEL[2] + (-0.05, 0.35), 0.16),
                         _seg_sd(U, V, TUNNEL[1] + (0.1, 0), TUNNEL[2] + (0.05, 0.35), 0.16))
    f["pillars"] = np.maximum(np.maximum(pillars, organ), -tun + 0.0)
    f["support"] = np.maximum.reduce([organ, -(tun - 0.0), -pillars])
    tect_mid_a = np.array([-5.4, IV0 + 2.2])
    tect_mid_b = np.array([2.9, IV0 + 2.95])
    tect = np.minimum(_seg_sd(U, V, tect_mid_a, tect_mid_b, 0.45), _ell_sd(U, V, (-1.6, IV0 + 2.75), 3.2, 0.6))
    tect = np.maximum(tect, -(organ - 0.02))
    f["tect"] = np.maximum(tect, U - 3.4)
    stria_in = _ell_sd(U, V, (0, 0), 9.1, 7.7)
    f["stria"] = np.maximum.reduce([oval, -stria_in, -U + 3.0, IV0 + 1.0 - V, rm_side * -1.0 + 0.05])
    inside = oval
    f["duct"] = np.maximum.reduce([inside, -rm_side + 0.11, IV0 + 0.13 - V, -U - 5.6, -f["stria"],
                                   -f["limbus"], -organ, -f["tect"]])
    rosen = _ell_sd(U, V, (-13.4, IV0 - 0.4), 1.8, 1.9)
    plate = np.maximum(plate, -rosen)
    f["lamina"] = np.maximum(f["lamina"], -rosen)
    f["sv"] = np.maximum.reduce([inside, np.minimum(rm_side + 0.11, U + 5.4), -limb, -plate, IV0 + 0.6 - V,
                                 -(f["rm"])])
    f["st"] = np.maximum.reduce([inside, V - (IV0 - 0.13), -plate])
    wall = _box_sd(U, V, -18.0, 14.2, -11.8, 11.6, 2.5)
    f["wall"] = np.maximum.reduce([wall, -oval, -f["lig"], -rosen, -plate])
    f["rosen"] = rosen
    return f


def _ins1_frame(theta):
    er = np.array([math.cos(theta), 0.0, -math.sin(theta)])
    et = np.array([-math.sin(theta), 0.0, -math.cos(theta)])
    return er, et


def ins1_pt(u, v, theta):
    ax = INS1_C - np.array([INS1_R, 0.0, 0.0])
    er, _ = _ins1_frame(theta)
    return ax + (INS1_R + u) * er + np.array([0.0, v, 0.0])


def _sweep_region(F, gu, gv, point, dirs, thetas, spacing=0.12):
    """Sweep the region F < 0 of a 2D field (sampled on the grid gu x gv) through the parameter values `thetas`.

    point(u, v, theta) -> xyz arrays; dirs(theta) -> (radial, up, along) unit vectors. The outline of the region,
    holes included, comes from marching squares; each loop becomes a wall and the two ends are capped with a
    triangulation of the section, so a compartment with holes (bone round a canal) sweeps as one closed solid."""
    from scipy.spatial import Delaunay
    from skimage.measure import find_contours
    g = gu[1] - gu[0]
    pad = np.pad(F, 1, mode="constant", constant_values=1.0)
    loops = []
    for c in find_contours(pad, 0.0):
        uv = np.stack([gu[0] + (c[:, 0] - 1) * g, gv[0] + (c[:, 1] - 1) * g], -1)
        if len(uv) < 4:
            continue
        seg = np.linalg.norm(np.diff(uv, axis=0), axis=1)
        L = seg.sum()
        if L < 3 * spacing:
            continue
        uv = _resample(np.c_[uv, np.zeros(len(uv))], max(spacing, L / 400))[:, :2]
        if np.linalg.norm(uv[0] - uv[-1]) < 1e-6:
            uv = uv[:-1]
        # make the region lie to the left of every loop
        mid = (uv[0] + uv[1]) / 2
        e = _unit(uv[1] - uv[0])
        probe = mid + np.array([-e[1], e[0]]) * g * 0.8
        iu, iv = (probe[0] - gu[0]) / g, (probe[1] - gv[0]) / g
        val = ndimage.map_coordinates(F, [[iu], [iv]], order=1, mode="nearest")[0]
        if val > 0:
            uv = uv[::-1]
        loops.append(uv)
    if not loops:
        return Mesh()
    m = len(thetas)
    mesh = Mesh()
    for uv in loops:
        n = len(uv)
        U = np.broadcast_to(uv[None, :, 0], (m, n))
        V = np.broadcast_to(uv[None, :, 1], (m, n))
        T = np.broadcast_to(np.asarray(thetas)[:, None], (m, n))
        pos = np.stack(point(U, V, T), -1).reshape(-1, 3)
        a = np.arange(m * n).reshape(m, n)
        q0, q1 = a[:-1, :].ravel(), np.roll(a[:-1, :], -1, axis=1).ravel()
        q2, q3 = np.roll(a[1:, :], -1, axis=1).ravel(), a[1:, :].ravel()
        tri = np.vstack([np.stack([q0, q1, q2], 1), np.stack([q0, q2, q3], 1)])
        # outward = to the right of the loop direction
        e = uv[1] - uv[0]
        er, up, _ = dirs(thetas[0])
        out3 = er * e[1] - up * e[0]
        t0 = pos[tri[0]]
        if np.dot(np.cross(t0[1] - t0[0], t0[2] - t0[0]), out3) < 0:
            tri = tri[:, ::-1]
        mesh.add(pos, tri)
    allp = np.vstack(loops)
    tri = Delaunay(allp).simplices
    cen = allp[tri].mean(axis=1)
    val = ndimage.map_coordinates(F, [(cen[:, 0] - gu[0]) / g, (cen[:, 1] - gv[0]) / g], order=1, mode="nearest")
    tri = tri[val < 0]
    for th, sign in ((thetas[0], -1.0), (thetas[-1], 1.0)):
        P = np.stack(point(allp[:, 0], allp[:, 1], np.full(len(allp), th)), -1)
        _, _, along = dirs(th)
        t = tri
        n0 = np.cross(P[t[0, 1]] - P[t[0, 0]], P[t[0, 2]] - P[t[0, 0]])
        if np.dot(n0, along * sign) < 0:
            t = t[:, ::-1]
        mesh.add(P, t)
    return mesh


def _ins1_point(U, V, T):
    ax = INS1_C - np.array([INS1_R, 0.0, 0.0])
    rr = INS1_R + U
    return ax[0] + rr * np.cos(T), ax[1] + V, ax[2] - rr * np.sin(T)


def _ins1_dirs(t):
    er, et = _ins1_frame(t)
    return er, np.array([0.0, 1.0, 0.0]), et


def _inset_cochlea():
    g_name = "Inset: cochlear duct (magnified)"
    parts = []
    u0, u1, v0, v1 = -18.4, 14.6, -12.2, 12.0
    g = 0.04
    gu = np.arange(u0, u1, g)
    gv = np.arange(v0, v1, g)
    GU, GV = np.meshgrid(gu, gv, indexing="ij")
    F = _ins1_fields(GU, GV)
    # rows of hair cells sit in grooves of the supporting cells, so the section shows each cut cell
    rows = np.minimum.reduce([_ell_sd(GU, GV, (IHC_U, IV0 + 1.42), 0.42, 0.64)] +
                             [_seg_sd(GU, GV, (uu, IV0 + 1.28), (uu - 0.12, IV0 + 2.2), 0.27) for uu in OHC_U])
    F["support"] = np.maximum(F["support"], -rows)
    thetas = np.linspace(0.0, INS1_SPAN, 26)
    spec = [("wall", "Bony wall of cochlea (magnified)", COL["petrous"], "i_wall", "bone", 1.0),
            ("lamina", "Osseous spiral lamina (magnified)", COL["lamina"], "i_lamina", "bone", 1.0),
            ("lig", "Spiral ligament (magnified)", COL["ligament_sp"], "i_lig", "fascia", 1.0),
            ("stria", "Stria vascularis", "#c2525d", "i_stria", "mucosa", 1.0),
            ("limbus", "Spiral limbus", "#d9928c", "i_limbus", "fascia", 1.0),
            ("sv", "Scala vestibuli (magnified)", COL["sv"], "sv", "csf", 0.72),
            ("st", "Scala tympani (magnified)", COL["st"], "st", "csf", 0.72),
            ("duct", "Cochlear duct endolymph (magnified)", COL["endolymph"], "duct", "csf", 0.35),
            ("rm", "Vestibular membrane (magnified)", COL["rm"], "rm", "serosa", 1.0),
            ("bm", "Basilar membrane (magnified)", COL["bm"], "bm", "fascia", 1.0),
            ("tect", "Tectorial membrane (magnified)", COL["tect"], "tect", "serosa", 0.85),
            ("pillars", "Pillar cells & tunnel of Corti", "#f4ecd2", "i_pillars", "organ", 1.0),
            ("support", "Supporting cells (Deiters, Hensen, Claudius)", "#ecc27a", "i_support", "organ", 1.0)]
    for key, name, col, dkey, cat, alpha in spec:
        mesh = _sweep_region(F[key], gu, gv, _ins1_point, _ins1_dirs, thetas, 0.14 if key != "wall" else 0.3)
        parts.append(mesh_part(mesh, name, g_name, col, D(dkey), cat, alpha=alpha, rank=0.5 if alpha < 1 else 0.0))
    # hair cells, cut by the front face
    ax = INS1_C - np.array([INS1_R, 0.0, 0.0])
    lo = np.array(_ins1_point(np.array(-3.0), np.array(IV0 + 0.5), np.array(INS1_SPAN))) - 1.0
    hi = np.array(_ins1_point(np.array(3.0), np.array(IV0 + 2.8), np.array(0.0))) + 1.0
    lo, hi = np.minimum(lo, hi), np.maximum(lo, hi)
    cv = Volume(lo, hi, 0.09)
    X, Y, Z = cv.axes()
    r = np.sqrt((X - ax[0]) ** 2 + (Z - ax[2]) ** 2)
    th = np.arctan2(-(Z - ax[2]), X - ax[0])
    dth = np.broadcast_to(np.maximum(-th, th - INS1_SPAN) * r, cv.shape).astype(np.float32)
    ihc, ohc = [], []
    for k in range(40):
        t = (k + 0.1) * 0.8 / (INS1_R + IHC_U)
        if t > INS1_SPAN:
            break
        er, et = _ins1_frame(t)
        ihc.append((ellipsoid(ins1_pt(IHC_U, IV0 + 1.42, t), (0.4, 0.62, 0.37), rot=np.column_stack([er, [0, 1, 0], et])),
                    t, IHC_U))
    for j, uu in enumerate(OHC_U):
        for k in range(60):
            t = (k + 0.1 + 0.33 * j) * 0.7 / (INS1_R + uu)
            if t > INS1_SPAN:
                break
            ohc.append((capsule(ins1_pt(uu, IV0 + 1.28, t), ins1_pt(uu - 0.12, IV0 + 2.2, t), 0.25), t, uu))
    for lst, name, col, key in ((ihc, "Inner hair cells", "#f29a3a", "ihc"), (ohc, "Outer hair cells", "#e8683a", "ohc")):
        vv = cv.copy(np.full(cv.shape, 1.0e3, np.float32))
        vv.add_all([s_ for s_, _, _ in lst])
        parts.append(sdf_part(cv.copy(np.maximum(vv.d, dth)), name, g_name, col, D(key), "organ", smooth=0.6))
    # spiral ganglion neurons in Rosenthal's canal
    rng = np.random.default_rng(8)
    gm = Mesh()
    for k in range(70):
        t = rng.uniform(0.02, INS1_SPAN)
        a = rng.uniform(0, 2 * math.pi)
        rr = math.sqrt(rng.uniform(0, 1)) * 1.3
        c = ins1_pt(-13.4 + rr * math.cos(a), IV0 - 0.4 + rr * math.sin(a) * 1.05, t)
        gm.extend(ellipsoid_mesh(c, rng.uniform(0.3, 0.42, 3), 8, rotation=frame_from_normal(rng.normal(size=3))))
    parts.append(mesh_part(gm, "Spiral ganglion neurons", g_name, COL["ganglion"], D("i_ganglion"), "nerve", clip=False))
    # stereocilia: IHC in a gently curved line, OHC in a W; the tallest OHC stereocilia touch the tectorial membrane
    cil = Mesh()
    for _, t, uu in ihc:
        er, et = _ins1_frame(t)
        top = ins1_pt(uu, IV0 + 2.02, t)
        for s_ in np.linspace(-0.26, 0.26, 6):
            for du, hgt in ((-0.08, 0.28), (0.0, 0.42), (0.09, 0.58)):
                b = top + et * s_ + er * (du + 0.04 * s_ * s_)
                cil.extend(tube(np.array([b, b + np.array([0.0, hgt, 0.0]) + er * 0.03]), np.array([0.035, 0.03]), 5))
    for _, t, uu in ohc:
        er, et = _ins1_frame(t)
        top = ins1_pt(uu - 0.12, IV0 + 2.42, t)
        for s_ in np.linspace(-0.24, 0.24, 6):
            vshape = 0.18 - 0.55 * abs(s_)
            for du, hgt in ((-0.07, 0.18), (0.0, 0.3), (0.07, 0.44)):
                b = top + et * s_ + er * (vshape + du)
                cil.extend(tube(np.array([b, b + np.array([0.0, hgt, 0.0])]), np.array([0.03, 0.026]), 5))
    parts.append(mesh_part(cil, "Hair-cell stereocilia", g_name, "#fff1c9", D("stereocilia"), "organ", clip=False))
    # cochlear nerve fibres: from the ganglion through the lamina and the habenula perforata to the hair cells
    fib = Mesh()
    for k in range(14):
        t = (k + 0.4) * INS1_SPAN / 14
        uv = [(-13.0, IV0 - 0.3), (-11.5, IV0), (-3.8, IV0), (-3.2, IV0 + 0.35), (-2.3, IV0 + 0.8)]
        if k % 3:
            uv += [(-1.2, IV0 + 0.62), (-0.4, IV0 + 0.66), (0.4, IV0 + 0.7), (OHC_U[k % 3], IV0 + 1.08)]
        else:
            uv += [(IHC_U, IV0 + 0.88)]
        path = np.array([ins1_pt(a, b, t) for a, b in uv])
        fib.extend(tube(_spline(path, 0.25), 0.075, 6))
    parts.append(mesh_part(fib, "Cochlear nerve fibres", g_name, COL["nerve"], D("i_fibres"), "nerve", clip=False))
    return _scale_about(parts, INS1_C, INS1_K)


def _scale_about(parts, c, k):
    for p in parts:
        p.mesh.parts = [((c + (pos - c) * k).astype(np.float32), nrm, idx) for pos, nrm, idx in p.mesh.parts]
    return parts


# =============================================================================== inset 2: crista ampullaris
INS2_C = np.array([51.0, -8.8, -4.0])           # centre of the ampulla; the front half is cut away at z = INS2_C.z


def _hair_bundle(apex, n, side, rng, tall=1.5, count=8, kino=True, r=0.045):
    """A staircase of stereocilia on one hair cell, tallest next to the single kinocilium on the `side` edge."""
    m = Mesh()
    e1 = _unit(side - np.dot(side, n) * n)
    e2 = np.cross(n, e1)
    for i in range(count):
        a = (i / (count - 1) - 0.5) * 0.5
        for row in range(3):
            off = e1 * (0.08 * (row - 1)) + e2 * a
            h = tall * (0.45 + 0.25 * row) * (1.0 - 0.25 * abs(a))
            b = apex + off
            m.extend(tube(np.array([b, b + n * h]), np.array([r, r * 0.8]), 5))
    if kino:
        b = apex + e1 * 0.2
        kp = _spline([b, b + n * tall * 0.8 + e1 * 0.08, b + n * tall * 1.35 + e1 * 0.05], 0.15)
        m.extend(tube(kp, np.full(len(kp), r * 1.2), 6))
    return m


def _inset_crista():
    g = "Inset: crista ampullaris (magnified)"
    parts = []
    c = INS2_C
    lo = c - np.array([11.6, 5.4, 5.2])
    hi = c + np.array([11.6, 5.0, 0.25])
    v = Volume(lo, hi, 0.18)
    crest_c = c + np.array([0.0, -3.3, 0.0])
    crest_r = np.array([2.7, 2.8, 4.8])

    def fields(v):
        X, Y, Z = v.axes()
        front = np.broadcast_to(Z - c[2], v.shape)
        outer = _stamp(v, [ellipsoid(c, (7.4, 4.5, 4.5)), capsule(c - (11.4, 0, 0), c + (11.4, 0, 0), 2.0)], 1.2)
        inner = _stamp(v, [ellipsoid(c, (7.05, 4.15, 4.15)), capsule(c - (11.6, 0, 0), c + (11.6, 0, 0), 1.65)], 1.2)
        core = np.maximum(_stamp(v, [ellipsoid(crest_c, crest_r)]), outer - 0.1)
        core = smin(core, np.maximum(_stamp(v, [ellipsoid(c + np.array([0.0, -4.3, 0.0]), (3.4, 0.9, 4.6))]), outer),
                    0.8)
        return X, Y, Z, front, _exact(v, outer, 0.8), _exact(v, inner, 0.8), _exact(v, core, 1.4)
    X, Y, Z, front, outer, inner, core = fields(v)
    xx = np.broadcast_to(X, v.shape)
    ends = np.maximum(xx - (c[0] + 11.2), (c[0] - 11.2) - xx)
    wall = np.maximum.reduce([outer, -inner, front, ends])
    parts.append(sdf_part(v.copy(wall), "Ampulla wall (membranous)", g, COL["utricle"], D("i_amp_wall"), "serosa",
                          smooth=0.7, alpha=0.9))
    top_y = crest_c[1] + 1.2
    ct = np.maximum(core, np.where(np.broadcast_to(Y > top_y, v.shape), -(core + 0.95), -1.0e3))
    parts.append(sdf_part(v.copy(np.maximum(ct, front)), "Crista ampullaris (connective tissue core)", g, "#e7b2a0",
                          D("crista"), "fascia", smooth=0.7))
    cup = np.maximum.reduce([_stamp(v, [ellipsoid(c + np.array([0.0, 0.6, 0.0]), (2.0, 4.6, 4.6))]), inner + 0.02,
                             -(core - 0.02), front])
    parts.append(sdf_part(v.copy(cup), "Cupula (magnified)", g, COL["cupula"], D("cupula"), "csf", smooth=0.7,
                          alpha=0.4, rank=0.5))
    # the sensory epithelium on the crest, with its hair cells, at finer resolution
    fv = Volume(crest_c - np.array([3.4, -0.4, 5.0]), np.array([crest_c[0] + 3.4, crest_c[1] + 3.2, c[2] + 0.25]), 0.07)
    FX, FY, FZ, ffront, _, _, fcore = fields(fv)
    epi = np.where(np.broadcast_to(FY > top_y, fv.shape), np.maximum(fcore, -(fcore + 0.95)), 1.0e3)
    rng = np.random.default_rng(14)
    type1, type2, bundles, fib = [], [], Mesh(), Mesh()
    for i, a in enumerate(np.linspace(0.35, math.pi - 0.35, 9)):
        for j, zz in enumerate(np.linspace(-4.3, -0.3, 8)):
            k = zz / crest_r[2]
            s_ = math.sqrt(1 - k * k)
            px = crest_c[0] + crest_r[0] * s_ * math.cos(a)
            py = crest_c[1] + crest_r[1] * s_ * math.sin(a)
            p = np.array([px, py, c[2] + zz])
            nrm = _unit([(px - crest_c[0]) / crest_r[0] ** 2, (py - crest_c[1]) / crest_r[1] ** 2,
                         (p[2] - crest_c[2]) / crest_r[2] ** 2])
            if py < top_y + 0.4 or nrm[1] < 0.35:
                continue
            p = p + rng.normal(0, 0.05, 3)
            body = p - nrm * 0.5
            if (i + j) % 2 == 0:
                type1.append(ellipsoid(body, (0.3, 0.46, 0.3), rot=frame_from_normal(nrm)))
            else:
                type2.append(capsule(body - nrm * 0.3, body + nrm * 0.3, 0.2))
            up = _unit(nrm + np.array([0.0, 1.2, 0.0]))
            bundles.extend(_hair_bundle(p + nrm * 0.02, up, np.array([-1.0, 0.0, 0.0]), rng, 0.95, 5))
            if j % 2 == 0:
                fib.extend(tube(_spline([body - nrm * 0.35, body - nrm * 1.4, crest_c + np.array([0, -0.8, 0]) + nrm * 0.3,
                                         c + np.array([0.3 * (i - 4) / 4, -5.4, zz * 0.4])], 0.3), 0.07, 5))
    cells = {}
    for key, lst in (("t1", type1), ("t2", type2)):
        vv = fv.copy(np.full(fv.shape, 1.0e3, np.float32))
        vv.add_all(lst)
        cells[key] = vv.d
    parts.append(sdf_part(fv.copy(np.maximum(cells["t1"], ffront)), "Type I hair cells (crista)", g, "#ef8f3a",
                          D("i_hc1"), "organ", smooth=0.6))
    parts.append(sdf_part(fv.copy(np.maximum(cells["t2"], ffront)), "Type II hair cells (crista)", g, "#e5673c",
                          D("i_hc2"), "organ", smooth=0.6))
    parts.append(sdf_part(fv.copy(np.maximum.reduce([epi, -np.minimum(cells["t1"], cells["t2"]), ffront])),
                          "Supporting cells (crista)", g, "#ecc27a", D("i_support_v"), "organ", smooth=0.6))
    parts.append(mesh_part(bundles, "Stereocilia & kinocilia (crista)", g, "#fff1c9", D("i_cilia"), "organ",
                           clip=False))
    nerve = _nerve_tube(_spline([c + np.array([0.0, -5.2, -2.0]), c + np.array([0.0, -7.2, -2.6]),
                                 c + np.array([0.8, -9.3, -3.2])], 0.3), 0.75)
    fib.extend(nerve)
    parts.append(mesh_part(fib, "Ampullary nerve fibres", g, COL["nerve"], D("i_amp_n"), "nerve", clip=False))
    return parts


# =============================================================================== inset 3: macula
INS3_C = np.array([51.0, -24.5, -3.0])          # centre of the front face of the macular block


def _inset_macula():
    g = "Inset: macula (magnified)"
    parts = []
    c = INS3_C
    half_x, depth = 8.5, 6.0
    x0, x1, z0, z1 = c[0] - half_x, c[0] + half_x, c[2] - depth, c[2]

    def wav(X, Z):
        return c[1] + 0.12 * np.sin((X - c[0]) * 0.9) * np.cos((Z - c[2]) * 0.7)

    def lvl(a):
        return lambda X, Z: wav(X, Z) + a
    for name, key, col, a, b, cat, alpha in (
            ("Lamina propria of macula", "i_lp", "#e7b2a0", -2.8, -1.4, "fascia", 1.0),
            ("Gelatinous layer", "i_gel", COL["cupula"], 0.3, 1.2, "csf", 0.45),
            ("Otolithic membrane (magnified)", "otolith", "#dcd6e8", 1.2, 1.75, "serosa", 0.8)):
        parts.append(mesh_part(slab(x0, x1, z0, z1, lvl(b), lvl(a), 90), name, g, col, D(key), cat, alpha=alpha,
                               rank=0.5 if alpha < 1 else 0.0))
    v = Volume((x0 - 0.3, c[1] - 1.7, c[2] - 2.9), (x1 + 0.3, c[1] + 0.6, z1 + 0.3), 0.09)
    X, Y, Z = v.axes()
    box_ = np.broadcast_to(np.maximum(np.maximum(X - x1, x0 - X), np.maximum(Z - z1, z0 - Z)), v.shape)
    yy = np.broadcast_to(Y, v.shape)
    w = wav(X, Z)
    epi = np.maximum(box_, np.maximum(w - 1.4 - yy, yy - w - 0.3))
    epi = np.maximum(epi, np.broadcast_to(c[2] - 2.6 - Z, v.shape))     # the front of the epithelium, cut cells and all
    back = slab(x0, x1, z0, c[2] - 2.6, lambda X_, Z_: wav(X_, Z_) + 0.3, lambda X_, Z_: wav(X_, Z_) - 1.4, 70)
    rng = np.random.default_rng(22)
    t1, t2, bundles, fib = [], [], Mesh(), Mesh()
    xs = np.arange(-half_x + 0.7, half_x - 0.4, 1.25)
    zs = np.arange(-0.4, -depth + 0.5, -1.25)
    striola = c[0] + 1.2
    for i, x in enumerate(xs):
        for j, z in enumerate(zs):
            p = np.array([c[0] + x + rng.normal(0, 0.1), c[1] + 0.25, c[2] + z + rng.normal(0, 0.1)])
            body = p - np.array([0.0, 0.62, 0.0])
            if j < 2:                            # cells further back are hidden in the epithelium
                if (i + j) % 2 == 0:
                    t1.append(ellipsoid(body, (0.3, 0.5, 0.3)))
                else:
                    t2.append(capsule(body - (0, 0.35, 0), body + (0, 0.35, 0), 0.21))
            # kinocilia point towards the striola in the utricle (the line where hair-cell polarity reverses)
            side = np.array([1.0 if p[0] < striola else -1.0, 0.0, 0.0])
            bundles.extend(_hair_bundle(p + np.array([0, 0.02, 0]), np.array([0.0, 1.0, 0.0]), side, rng, 0.75, 5))
            if j % 2 == 0:
                fib.extend(tube(_spline([body - (0, 0.45, 0), body - (0, 1.3, 0), body + (0.3, -2.4, 0.1),
                                         (body[0] * 0.6 + c[0] * 0.4, c[1] - 3.0, body[2])], 0.3), 0.065, 5))
    front = np.broadcast_to(Z - c[2], v.shape)
    cells = {}
    for key, lst in (("t1", t1), ("t2", t2)):
        vv = v.copy(np.full(v.shape, 1.0e3, np.float32))
        vv.add_all(lst)
        cells[key] = vv.d
    parts.append(sdf_part(v.copy(np.maximum(cells["t1"], front)), "Type I hair cells (macula)", g, "#ef8f3a", D("i_hc1"),
                          "organ", smooth=0.6))
    parts.append(sdf_part(v.copy(np.maximum(cells["t2"], front)), "Type II hair cells (macula)", g, "#e5673c",
                          D("i_hc2"), "organ", smooth=0.6))
    sup = sdf_part(v.copy(np.maximum(epi, -np.minimum(cells["t1"], cells["t2"]))), "Supporting cells (macula)", g,
                   "#ecc27a", D("i_support_v"), "organ", smooth=0.6)
    sup.mesh.extend(back)
    parts.append(sup)
    # otoconia: calcium carbonate crystals, spindle-shaped with pointed ends, largest along the striola
    oto = Mesh()
    for k in range(380):
        x = rng.uniform(-half_x + 0.3, half_x - 0.3)
        z = rng.uniform(-depth + 0.3, -0.2)
        size = rng.uniform(0.2, 0.42) * (1.0 + 0.4 * math.exp(-((c[0] + x - striola) / 2.0) ** 2))
        p = c + np.array([x, 1.75 + size * 0.45 + rng.uniform(0, 0.3), z])
        oto.extend(ellipsoid_mesh(p, (size * 0.55, size * 0.55, size * 1.25), 4,
                                  rotation=frame_from_normal(rng.normal(size=3))))
    parts.append(mesh_part(oto, "Otoconia (otoliths)", g, "#f6f3ea", D("i_otoconia"), "organ", clip=False))
    parts.append(mesh_part(bundles, "Stereocilia & kinocilia (macula)", g, "#fff1c9", D("i_cilia"), "organ",
                           clip=False))
    parts.append(mesh_part(fib, "Macular nerve fibres", g, COL["nerve"], D("i_mac_n"), "nerve", clip=False))
    return parts


# =============================================================================== descriptions
DESC.update({
    # ---- external ear
    "helix": "Helix: the rolled free rim of the auricle, starting as the crus of the helix in the concha and curving up, "
             "over the top and down the back to the tail above the lobule. Skin tightly bound to elastic cartilage. "
             "Darwin's tubercle may project from its upper posterior part. Its thin skin over cartilage makes it a "
             "common site of frostbite, actinic keratosis, basal and squamous cell carcinoma, and of painful chondro"
             "dermatitis nodularis helicis; gouty tophi collect here.",
    "antihelix": "Antihelix: the curved ridge parallel to and in front of the helix, dividing above into superior and "
                 "inferior crura that enclose the triangular fossa. Like all of the auricle except the lobule, it is "
                 "skin over elastic cartilage. Failure of the antihelical fold to form gives the prominent "
                 "('bat') ear corrected by otoplasty.",
    "scapha": "Scapha and triangular fossa: the scapha is the groove between the helix and the antihelix; the "
              "triangular fossa is the hollow between the two crura of the antihelix. The auricle's folds act as a "
              "direction-dependent filter: they add frequency notches above ~5 kHz that change with the elevation "
              "of a sound source, which the brain uses to locate sounds above, below, in front and behind.",
    "concha": "Concha of the auricle: the deep bowl in front of the antihelix, divided by the crus of the helix into the "
              "cymba (above) and the cavum (below), which leads into the external acoustic meatus. The concha and meatus "
              "resonate at ~2.5-4 kHz and add 10-20 dB of gain there - one reason hearing is most sensitive and "
              "noise damage commonest at these frequencies. Its skin is supplied partly by the auricular branch of the "
              "vagus (Arnold's nerve): touching it can trigger a cough.",
    "tragus": "Tragus: the small flap of cartilage-backed skin in front of the opening of the meatus, projecting "
              "backwards over it; the antitragus faces it across the intertragic notch. Pressing on the tragus is "
              "painful in otitis externa (infection of the meatal skin) but not in otitis media. The tragal "
              "cartilage is continuous with the cartilage of the meatus and is a favourite graft for repairing the "
              "tympanic membrane.",
    "antitragus": "Antitragus: the small tubercle opposite the tragus, above the lobule, separated from it by the "
                  "intertragic notch; the lower end of the antihelix runs into it.",
    "lobule": "Lobule of the auricle (earlobe): the only part without cartilage - skin over fibrofatty tissue, richly "
              "vascular. Used for capillary blood sampling and piercing (keloids and allergic nickel dermatitis are "
              "common complications). A diagonal earlobe crease (Frank's sign) has a weak association with coronary "
              "artery disease.",
    "au_back": "Cranial (posterior) surface of the auricle, where it is attached to the side of the head over the "
               "mastoid region by skin, ligaments and vestigial auricular muscles (supplied by the facial nerve). "
               "The retroauricular sulcus behind it is where a mastoid abscess pushes the auricle forwards and "
               "outwards, and the usual incision for mastoid surgery.",
    "au_cart": "Auricular cartilage: a single plate of elastic cartilage (chondrocytes in a matrix with a dense "
               "network of elastic fibres, surrounded by perichondrium) that gives the auricle its shape and "
               "springiness; it continues into the lateral third of the meatus. The cartilage has no blood vessels "
               "of its own and depends on the perichondrium: a blow that lifts it off (haematoma auris) must be "
               "drained, or the cartilage necroses and fibroses into a 'cauliflower ear'. Relapsing polychondritis "
               "attacks it and spares the lobule.",
    "eam_c": "External acoustic meatus, cartilaginous part (lateral third, ~8 mm): lined by thick skin with hairs "
             "(tragi), sebaceous glands and ceruminous glands, over the meatal cartilage. Its skin is mobile, so "
             "pulling the auricle up and back (in adults) straightens the S-shaped canal for otoscopy; in infants "
             "the auricle is pulled down and back. Epithelium migrates outwards from the tympanic membrane, "
             "carrying wax and debris with it - the canal cleans itself, and cotton buds push wax inwards.",
    "eam_b": "External acoustic meatus, bony part (medial two thirds, ~16 mm, in the tympanic part of the temporal "
             "bone): very thin skin with no hairs or glands, fused to the periosteum, so any swelling here is "
             "exquisitely painful. The canal narrows at the bony-cartilaginous junction (isthmus), where foreign "
             "bodies lodge. The whole meatus (~24 mm) is a tube closed at one end and resonates near 3 kHz. Sensory "
             "supply: auriculotemporal nerve (V3) anteriorly and superiorly, auricular branch of vagus posteriorly "
             "and inferiorly.",
    "meatal_cart": "Cartilage of the meatus: a gutter of elastic cartilage continuous with the tragus, deficient "
                   "posterosuperiorly where the gap is closed by fibrous tissue. Fissures in it (of Santorini) let "
                   "infection spread from the canal to the parotid gland and back.",
    "cerumin": "Ceruminous and sebaceous glands of the cartilaginous meatus: ceruminous glands are modified apocrine "
               "sweat glands (coiled tubules with a myoepithelial layer) that open with sebaceous glands onto the "
               "hair follicles. Their secretions mix with shed keratin to form cerumen. Wet (sticky, brown) versus "
               "dry (flaky, grey) wax is inherited through a single-nucleotide variant in the ABCC11 gene.",
    "cerumen": "Cerumen (earwax): secretions of ceruminous and sebaceous glands mixed with desquamated keratin. It is "
               "water-repellent, slightly acidic and antimicrobial (lysozyme, fatty acids) and traps dust. Impacted "
               "wax completely occluding the canal causes a conductive hearing loss (Weber lateralises to that ear, "
               "Rinne negative) that is cured by removal - drops, irrigation or microsuction.",
    "skin": "Skin of the side of the head over the temporal bone, continuous with the skin of the auricle and of the "
            "external acoustic meatus.",
    "subcut": "Subcutaneous tissue between the skin and the temporal bone (in life here also the attachments of "
              "the auricular muscles and, above, the temporalis muscle and fascia).",
    # ---- tympanic membrane and middle ear
    "tm": "Tympanic membrane, pars tensa: an oval, pearly-grey membrane ~9-10 mm across and ~0.1 mm thick, set "
          "obliquely (facing laterally, forwards and downwards) at the end of the meatus. Three layers: outer skin "
          "(stratified squamous, continuous with the meatus), middle fibrous layer (radial and circular collagen - "
          "what makes it 'tense'), inner mucosa of the middle ear. The handle of the malleus is embedded in it and "
          "draws its centre medially into the umbo, from which the cone of light points anteroinferiorly on "
          "otoscopy. Its area (~55 mm2 effective) is ~17 times that of the stapes footplate - the main part of "
          "the impedance match between air and the fluids of the inner ear (together with the ossicular lever "
          "~1.3x: ~22x, ~25-30 dB pressure gain). Bulging and red in acute otitis media; retracted and dull with a "
          "middle-ear effusion (glue ear) or a blocked auditory tube; perforations follow infection or trauma and "
          "cause a conductive loss.",
    "tm_flac": "Tympanic membrane, pars flaccida (Shrapnell membrane): the small, lax upper part above the anterior "
               "and posterior malleolar folds, lacking the organised fibrous layer. It faces Prussak's space in the "
               "epitympanum. Chronic negative middle-ear pressure retracts it into a pocket that traps keratin - "
               "the origin of most acquired cholesteatomas, which erode the ossicles, the lateral semicircular "
               "canal and the facial canal.",
    "cavity": "Tympanic cavity: an air-filled slit in the temporal bone, ~15 mm high and front to back but only ~2 mm "
              "wide opposite the umbo (6 mm above in the epitympanum, 4 mm below in the hypotympanum). Lined by a "
              "thin mucosa (simple squamous to cuboidal, ciliated near the auditory tube) over the periosteum. "
              "Walls: roof = tegmen tympani (thin bone under the middle cranial fossa); floor = jugular bulb; "
              "lateral = tympanic membrane; medial = promontory (basal turn of the cochlea), oval and round windows, "
              "facial canal and lateral semicircular canal; anterior = auditory tube, tensor tympani, carotid canal; "
              "posterior = aditus to the mastoid antrum and the pyramidal eminence. Acute otitis media (usually "
              "Streptococcus pneumoniae, Haemophilus influenzae, Moraxella after a viral cold) fills it with pus; a "
              "persisting effusion (otitis media with effusion) is the commonest cause of conductive hearing loss "
              "in children. Infection can spread up through the tegmen (meningitis, temporal lobe abscess), back "
              "into the mastoid, or medially into the labyrinth.",
    "air_cells": "Mastoid antrum and air cells: the antrum is a single large air space behind the epitympanum, joined "
                 "to it by the aditus; from it a honeycomb of mucosa-lined air cells extends through the mastoid "
                 "process (and variably into the squamous and petrous bone). Pneumatisation develops after birth "
                 "and is reduced by chronic childhood otitis. Acute mastoiditis (infection spreading from the middle "
                 "ear, coalescing the cells) pushes the auricle forwards with tender swelling behind it, and can "
                 "extend to the sigmoid sinus (thrombosis), the meninges, or under the neck muscles (Bezold "
                 "abscess). Mastoidectomy opens these cells.",
    "tube": "Pharyngotympanic (auditory, Eustachian) tube: ~36 mm long, running forwards, medially and downwards from "
            "the anterior wall of the tympanic cavity to the lateral wall of the nasopharynx. Posterolateral third "
            "bony, anteromedial two thirds cartilaginous, narrowest at their junction (isthmus); lined by ciliated "
            "respiratory epithelium that sweeps mucus towards the pharynx. Normally closed, it opens on swallowing "
            "and yawning (tensor veli palatini, levator veli palatini, salpingopharyngeus) to equalise middle-ear "
            "pressure with the atmosphere and drain the cavity. In children it is shorter, wider and more "
            "horizontal, so nasopharyngeal infection reaches the middle ear easily - hence the frequency of otitis "
            "media; enlarged adenoids, cleft palate and barotrauma (flying, diving) all act through tube "
            "dysfunction. A unilateral middle-ear effusion in an adult warrants a look for nasopharyngeal carcinoma.",
    "tube_cart": "Cartilage of the auditory tube: a hook-shaped plate of (largely elastic) cartilage forming the "
                 "upper and medial walls of the cartilaginous part; the lower lateral wall is membranous. Its "
                 "pharyngeal end raises the torus tubarius behind the tube's opening in the nasopharynx, with the "
                 "pharyngeal recess (fossa of Rosenmüller) behind that.",
    "rw": "Round window (fenestra cochleae), closed by the secondary tympanic membrane: an opening in the medial wall "
          "below and behind the promontory, at the basal end of the scala tympani. Because fluid is incompressible, "
          "every inward push of the stapes footplate must be matched by an outward bulge here - the pressure "
          "relief that lets the cochlear fluids and basilar membrane move. It is protected by a bony niche from "
          "sound arriving directly through the air. Round-window rupture (straining, barotrauma) causes a "
          "perilymph fistula with sudden hearing loss and vertigo; cochlear implant electrodes are usually inserted "
          "through or next to it.",
    # ---- ossicles
    "malleus": "Malleus (hammer), ~8-9 mm: head in the epitympanum, articulating behind with the incus; neck; lateral "
               "process pressing on the upper tympanic membrane; anterior process; and the handle (manubrium) "
               "embedded in the membrane down to the umbo. The chain transmits the membrane's vibration to the oval "
               "window; the malleus and incus rotate together as a lever about an axis through the anterior "
               "ligament of the malleus and the short process of the incus (lever ratio ~1.3:1). Tensor tympani "
               "inserts on its upper handle. Fixation of the malleus head in the attic (tympanosclerosis) and "
               "erosion by cholesteatoma cause conductive loss. First pharyngeal arch (Meckel cartilage) derivative.",
    "incus": "Incus (anvil), ~7 mm: body articulating with the malleus head (saddle-shaped incudomallear joint); short "
             "process pointing back to the fossa incudis (posterior ligament); long process descending behind and "
             "parallel to the handle of the malleus, ending in the lenticular process that articulates with the "
             "stapes head. The tip of the long process has the poorest blood supply in the chain and is the part "
             "most often eroded by chronic otitis media or cholesteatoma - ossicular discontinuity gives a large "
             "(~50-60 dB) conductive loss. First pharyngeal arch derivative.",
    "stapes": "Stapes (stirrup), ~3.2 mm - the smallest bone in the body: head (articulating with the lenticular "
              "process of the incus), neck (where the stapedius tendon inserts), anterior and posterior crura, and "
              "the footplate that fills the oval window. It pistons and rocks in the window, pressing on the "
              "perilymph of the vestibule. Second pharyngeal arch (Reichert cartilage) derivative, except the "
              "vestibular face of the footplate (otic capsule). A persistent stapedial artery sometimes passes "
              "between the crura.",
    "footplate": "Base (footplate) of the stapes: a kidney-shaped plate ~3 x 1.4 mm (area ~3.2 mm2) sealed into the "
                 "oval window by the annular ligament, with the vestibule and saccule immediately medial to it. In "
                 "otosclerosis (autosomal dominant with variable penetrance, commoner in women, worse in pregnancy) "
                 "spongy new bone at the front of the window (fissula ante fenestram) fixes the footplate: a "
                 "progressive conductive loss from early adulthood with a normal drum, a negative Rinne, Weber to the "
                 "worse ear, a Carhart notch at 2 kHz on bone conduction and absent stapedial reflexes. Treated by "
                 "stapedotomy (a piston prosthesis through a hole in the footplate) or a hearing aid.",
    "im_joint": "Incudomallear joint: a small synovial saddle joint between the head of the malleus and the body of the "
                "incus; the two usually move as one unit, and the joint slips only with large static pressure "
                "changes, protecting the inner ear.",
    "is_joint": "Incudostapedial joint: a synovial ball-and-socket joint between the lenticular process of the incus "
                "and the head of the stapes. Dislocation by head injury or erosion by infection breaks the chain.",
    "lig_sup": "Superior ligament of the malleus: from the head of the malleus up to the roof (tegmen) of the "
               "epitympanum; it suspends the malleus.",
    "lig_lat": "Lateral ligament of the malleus: from the neck of the malleus to the margin of the tympanic notch "
               "(scutum) - limits inward rotation of the chain.",
    "lig_ant": "Anterior ligament of the malleus: from the anterior process forwards to the petrotympanic fissure "
               "(it carries remnants of Meckel cartilage, continuous with the sphenomandibular ligament). With the "
               "posterior ligament of the incus it defines the axis about which the malleus-incus complex rotates.",
    "lig_inc": "Posterior ligament of the incus: attaches the short process of the incus to the fossa incudis on the "
               "posterior wall of the epitympanum - the posterior end of the ossicular axis of rotation.",
    "annular": "Oval window (fenestra vestibuli) and the annular (stapediovestibular) ligament: the kidney-shaped "
               "opening in the medial wall into the vestibule, closed by the stapes footplate, which is held in by "
               "a ring of elastic fibres that lets it move. Sound pressure concentrated from the large tympanic "
               "membrane onto this small window (area ratio ~17:1) overcomes the ~30 dB loss that air-to-fluid "
               "transmission would otherwise suffer. The window is the target of stapes surgery; a leak around it "
               "(perilymph fistula) causes fluctuating hearing loss and vertigo.",
    "tensor": "Tensor tympani: arises from the cartilage of the auditory tube and the adjacent sphenoid, lies in a bony "
              "semicanal above the tube, and its tendon turns laterally round the cochleariform process to insert "
              "on the upper handle of the malleus. Nerve: medial pterygoid branch of the mandibular nerve (V3) - "
              "first-arch muscle. It pulls the handle medially, tensing the tympanic membrane; it contracts with "
              "chewing, swallowing, vocalisation and startle rather than with sound alone.",
    "tensor_t": "Tendon of tensor tympani, turning laterally over the cochleariform process to the handle of the "
                "malleus.",
    "stapedius": "Stapedius: the smallest skeletal muscle in the body, lying in a canal beside the descending (mastoid) "
                 "facial canal; its tendon emerges from the apex of the pyramidal eminence to insert on the neck of "
                 "the stapes. Nerve: facial nerve (VII) - second-arch muscle. The acoustic (stapedial) reflex: sound "
                 ">70-90 dB above threshold contracts both stapedius muscles (cochlear nerve -> cochlear nuclei -> "
                 "superior olivary complex -> facial motor nuclei, bilaterally), stiffening the chain and reducing "
                 "low-frequency transmission by up to ~20 dB. It protects against sustained loud sound but is too "
                 "slow (~25-150 ms) for gunshots or explosions. A facial palsy proximal to the nerve to stapedius "
                 "causes hyperacusis; absent reflexes on tympanometry point to otosclerosis or a VII/VIII lesion.",
    "stapedius_t": "Tendon of stapedius, from the pyramidal eminence forwards to the neck of the stapes; it tilts "
                   "the footplate and damps its movement.",
    # ---- temporal bone
    "petrous": "Petrous part of the temporal bone and otic capsule: the densest bone in the body, forming the medial "
               "wall of the tympanic cavity and enclosing the inner ear. The otic capsule around the labyrinth ossifies "
               "from 14 centres and reaches adult size by mid-fetal life; it scarcely remodels afterwards, which is "
               "why otosclerosis (a focal remodelling disorder of this bone) is so distinctive. Here it has been "
               "dug away in front of the labyrinth, the internal acoustic meatus and the facial canal to show "
               "them. Transverse fractures of the petrous bone cross the labyrinth (sensorineural loss, vertigo, "
               "facial palsy); longitudinal fractures run through the middle ear (haemotympanum, conductive loss, "
               "CSF otorrhoea).",
    "squamous": "Squamous and tympanic parts of the temporal bone: the tympanic plate forms most of the bony meatus; the "
                "squamous part forms the roof of the meatus and the lateral wall of the epitympanum (the scutum) and "
                "the tegmen above. The thin tegmen tympani is all that separates the middle ear from the temporal "
                "lobe and meninges.",
    "mastoid_proc": "Mastoid process: the nipple of bone behind the meatus, containing the mastoid air cells; "
                    "sternocleidomastoid, splenius capitis and longissimus capitis attach to it. It is absent at "
                    "birth (so the facial nerve at the stylomastoid foramen is superficial and vulnerable in "
                    "infants) and grows with the pull of the neck muscles. Bone conduction is tested by placing a "
                    "256/512 Hz tuning fork on it (Rinne test).",
    # ---- inner ear
    "bony_lab": "Bony labyrinth (perilymph): the system of cavities in the otic capsule - vestibule, three "
                "semicircular canals and the cochlea - lined by endosteum and filled with perilymph, a fluid like "
                "extracellular fluid or CSF (high Na+ ~140 mM, low K+ ~5 mM), connected to the subarachnoid space "
                "through the cochlear aqueduct. It is drawn translucent so that the membranous labyrinth floating in "
                "it can be seen. Sound pushed in at the oval window travels through the perilymph of the scala "
                "vestibuli, crosses the cochlear partition and is released at the round window.",
    "helicotrema": "Helicotrema: the opening at the apex of the cochlea where the cochlear duct ends blindly and the "
                   "scala vestibuli and scala tympani join round the free hook (hamulus) of the spiral lamina. It "
                   "lets very slow pressure changes equalise without moving the basilar membrane.",
    "sv": "Scala vestibuli: the perilymph-filled channel above the cochlear duct, beginning at the vestibule (and so "
          "at the oval window) and running up to the helicotrema. The pressure wave from the stapes enters it and "
          "presses down on the cochlear partition.",
    "st": "Scala tympani: the perilymph-filled channel below the basilar membrane, running from the helicotrema down "
          "to the round window. Cochlear implant electrode arrays are threaded into it from the base, where they "
          "stimulate the spiral ganglion - which is why the highest-pitched (basal) regions are the easiest to "
          "reach.",
    "spiral_lig": "Spiral ligament and stria vascularis: the spiral ligament is thickened periosteum on the outer wall "
                  "of the cochlear canal, anchoring the outer edge of the basilar membrane (basilar crest). Its inner "
                  "surface facing the cochlear duct carries the stria vascularis, a vascular, three-layered "
                  "epithelium that secretes K+ into the endolymph and generates the +80 mV endocochlear potential "
                  "- the 'battery' that drives current into the hair cells. Loop diuretics and aminoglycosides can "
                  "damage it; its atrophy is one form of presbycusis.",
    "lamina": "Osseous spiral lamina: a shelf of bone winding round the modiolus for 2.5 turns, projecting halfway "
              "across the canal; its outer edge carries the basilar membrane. It is wide at the base and narrow at "
              "the apex, the reverse of the basilar membrane. Between its two plates the peripheral processes of the "
              "spiral ganglion cells run out to the hair cells.",
    "modiolus": "Modiolus: the conical spongy-bone core of the cochlea, its base at the fundus of the internal acoustic "
                "meatus and its tip at the apex (cupula). The cochlea winds ~2.5 turns round it (~35 mm of duct in a "
                "structure 9 mm across and 5 mm high). It contains the spiral (Rosenthal) canal with the spiral "
                "ganglion and the channels through which the cochlear nerve fibres reach its base.",
    "duct": "Cochlear duct (scala media): the triangular, endolymph-filled membranous tube between the scala vestibuli "
            "and scala tympani, ~35 mm long, beginning with a blind end in the vestibule (joined to the saccule by "
            "the ductus reuniens) and ending blindly at the apex. Endolymph is unique among extracellular fluids: "
            "high K+ (~150 mM), low Na+, and +80 mV relative to perilymph. Roof = vestibular membrane, floor = "
            "basilar membrane with the spiral organ, outer wall = stria vascularis. Distension by excess endolymph "
            "(endolymphatic hydrops) is the lesion of Ménière disease.",
    "rm": "Vestibular (Reissner) membrane: the roof of the cochlear duct, only two cell layers thick (squamous "
          "epithelium facing the endolymph, mesothelium facing the perilymph), separating the scala vestibuli from "
          "the cochlear duct. It keeps the two fluids apart but is acoustically transparent. It bulges and can "
          "rupture in endolymphatic hydrops (Ménière disease), mixing K+-rich endolymph into the perilymph - "
          "thought to cause the attacks of vertigo, tinnitus and fluctuating low-frequency hearing loss.",
    "bm": "Basilar membrane: the fibrous floor of the cochlear duct, from the osseous spiral lamina to the spiral "
          "ligament, carrying the spiral organ. It is narrow (~0.1 mm) and stiff at the base and wide (~0.5 mm) "
          "and floppy at the apex, so a travelling wave set up by the stapes peaks at a place determined by its "
          "frequency: 20 kHz at the base next to the oval window, 20 Hz at the apex. This tonotopic map is "
          "preserved all the way to the auditory cortex. Because every wave passes the base first, the basal "
          "(high-frequency) hair cells take the most wear: noise and age both cause high-frequency loss first.",
    "organ": "Spiral organ (of Corti): the sensory epithelium on the basilar membrane - one row of ~3500 inner hair "
             "cells and three rows of ~12000 outer hair cells, with pillar, Deiters, Hensen and Claudius supporting "
             "cells and the tunnel of Corti; the tectorial membrane lies over it. When the basilar membrane moves up "
             "and down, the shearing between the reticular lamina and the tectorial membrane bends the stereocilia; "
             "opening their K+ channels depolarises the cells. Inner hair cells send the signal (~95% of afferent "
             "fibres); outer hair cells amplify it (see the magnified inset).",
    "tect": "Tectorial membrane: a gelatinous flap (collagen and tectorins) attached to the spiral limbus, lying over "
            "the hair cells with the tips of the tallest outer hair-cell stereocilia embedded in it. Because it "
            "pivots about a different point from the basilar membrane, vertical motion of the partition becomes a "
            "shearing force across the stereocilia. TECTA mutations cause hereditary hearing loss.",
    "ducts": "Semicircular ducts: the membranous tubes (~0.3 mm across, a quarter of the canal's diameter) lying "
             "against the outer wall of the bony canals, filled with endolymph and opening at both ends into the "
             "utricle. Anterior (superior), posterior and lateral (horizontal) ducts lie in three roughly "
             "perpendicular planes, and each works with a partner canal in the other ear (left lateral with right "
             "lateral, left anterior with right posterior) as a push-pull pair. They sense angular (rotational) "
             "acceleration of the head: the endolymph lags behind the moving wall by inertia and deflects the "
             "cupula. Anterior canal: nodding (pitch); posterior canal: tilting towards the shoulder (roll); lateral "
             "canal: turning (yaw) - with the head tilted 30 degrees forwards (as in the Barany chair test) the "
             "lateral canals are horizontal.",
    "amp": "Membranous ampullae: the dilated end of each semicircular duct, containing its crista ampullaris and "
           "cupula. The anterior and lateral ampullae lie together at the anterior end of the vestibule, the "
           "posterior ampulla at its lower posterior part; the other ends of the anterior and posterior ducts join as "
           "the crus commune. Lateral canal: flow of endolymph towards the ampulla (ampullopetal) excites; "
           "anterior and posterior canals: flow away from the ampulla excites.",
    "utricle": "Utricle: the larger, oval sac in the upper posterior vestibule into which all five openings of the "
               "semicircular ducts empty. Its macula lies in its floor, roughly horizontal when the head is upright, "
               "so it senses horizontal linear acceleration and head tilt - static equilibrium. Otoconia broken "
               "loose from the utricular macula are the debris of benign paroxysmal positional vertigo.",
    "saccule": "Saccule: the smaller, round sac in the spherical recess of the lower anterior vestibule, close to the "
               "stapes footplate; joined to the cochlear duct by the ductus reuniens and to the utricle and "
               "endolymphatic duct by the utriculosaccular duct. Its macula stands vertically on the medial wall, so "
               "it senses vertical linear acceleration (lifts, jumping) and gravity in the sagittal plane. Loud "
               "clicks stimulate it - the basis of vestibular evoked myogenic potentials (VEMP) tests.",
    "endo": "Endolymphatic duct and sac: the duct leaves the utricle and saccule, runs through the vestibular "
            "aqueduct and ends in the endolymphatic sac, which lies between the layers of dura on the posterior "
            "surface of the petrous bone. The sac resorbs endolymph and handles its debris and immune defence. "
            "Poor resorption is thought to underlie endolymphatic hydrops (Ménière disease; decompression of the "
            "sac is one operation for it). An enlarged vestibular aqueduct is the commonest inner-ear malformation "
            "seen on imaging in congenital hearing loss (often with SLC26A4/Pendred syndrome).",
    "crista": "Crista ampullaris: a saddle-shaped ridge across the floor of each ampulla, covered by sensory epithelium "
              "(type I and type II hair cells with supporting cells) whose stereocilia and kinocilia project into the "
              "gelatinous cupula; the connective tissue core carries the ampullary nerve fibres. All hair cells in "
              "one crista are polarised the same way, so flow of endolymph in one direction deflects the bundles "
              "towards their kinocilia (depolarisation, more firing) and flow the other way inhibits. This is the "
              "receptor for angular acceleration - dynamic equilibrium.",
    "cupula": "Cupula: a gelatinous (mucopolysaccharide) dome sitting on the crista and reaching the roof of the "
              "ampulla, sealing it like a swing door. It has the same density as endolymph, so it ignores gravity "
              "and responds only to the flow produced when the head turns. During sustained rotation the endolymph "
              "catches up and the cupula returns; when rotation stops the endolymph keeps moving and bends it the "
              "other way - the post-rotatory nystagmus and vertigo of the Barany test. In cupulolithiasis "
              "otoconia stuck to it make it gravity-sensitive.",
    "macula": "Maculae of the utricle and saccule: plaques of sensory epithelium (type I and II hair cells and "
              "supporting cells) covered by a gelatinous layer and the otolithic membrane. The utricular macula is "
              "horizontal, the saccular vertical, so together they sense linear acceleration and the direction of "
              "gravity in every plane - static equilibrium. Along a curved line, the striola, the polarity of the "
              "hair cells reverses, so any tilt excites some cells and inhibits others.",
    "otolith": "Otolithic membrane with otoliths (otoconia): a gelatinous sheet over each macula whose upper surface "
               "is loaded with calcium carbonate crystals (~3-30 um). Being denser than endolymph (~2.7 g/cm3), the "
               "crystal-laden membrane lags or slides under gravity and linear acceleration, bending the hair "
               "bundles below. Otoconia dislodged by age, head injury or inner-ear disease can drift into a "
               "semicircular duct (almost always the posterior, the most dependent): benign paroxysmal positional "
               "vertigo (BPPV) - seconds of intense rotatory vertigo on lying down or turning in bed, diagnosed by the "
               "Dix-Hallpike test (torsional upbeating nystagmus after a latency, fatiguing) and cured by the Epley "
               "repositioning manoeuvre.",
    # ---- nerves
    "viii": "Vestibulocochlear nerve (VIII): formed by the cochlear and vestibular nerves in the internal acoustic "
            "meatus; it crosses the cerebellopontine angle with the facial nerve to enter the brainstem at the "
            "pontomedullary junction. Cochlear fibres go to the cochlear nuclei, then (bilaterally, mainly "
            "crossed) through the superior olivary complex (sound localisation by interaural time and level "
            "differences), lateral lemniscus, inferior colliculus and medial geniculate body to the primary "
            "auditory cortex (transverse temporal gyri of Heschl). Because the pathway is bilateral above the "
            "cochlear nuclei, a unilateral hearing loss means a lesion of the ear, the nerve or the cochlear nuclei, "
            "not of the cortex. A vestibular schwannoma ('acoustic neuroma') arising in the meatus causes "
            "progressive unilateral sensorineural loss and tinnitus, then facial numbness (V) and ataxia as it "
            "grows; bilateral tumours define neurofibromatosis type 2.",
    "coch_n": "Cochlear nerve: the central processes of the bipolar spiral ganglion neurons (~30000 fibres), leaving "
              "the base of the modiolus through the cochlear area of the fundus in the anteroinferior part of the "
              "internal acoustic meatus. Most (type I) fibres carry signals from inner hair cells, each inner hair "
              "cell supplied by ~10-20 fibres; a few (type II) from outer hair cells. Efferent olivocochlear fibres "
              "run with it back to the outer hair cells. Damage to the nerve, the hair cells or the cochlea causes "
              "sensorineural loss (Weber lateralises to the better ear; Rinne positive in both ears, air > bone).",
    "vest_n": "Vestibular nerve: the central processes of the vestibular (Scarpa) ganglion. The superior division "
              "supplies the utricular macula and the anterior and lateral cristae; the inferior division the "
              "saccular macula and the posterior crista. Fibres go to the vestibular nuclei and the flocculonodular "
              "lobe of the cerebellum, and from there to the eye muscles (vestibulo-ocular reflex through the MLF), "
              "the spinal cord (vestibulospinal tracts - posture) and the cortex. Vestibular neuritis (viral "
              "inflammation, usually of the superior division) causes days of severe continuous vertigo with "
              "horizontal nystagmus and an abnormal head impulse test, but no hearing loss.",
    "scarpa": "Vestibular (Scarpa) ganglion: the cell bodies of the bipolar vestibular neurons, a swelling on the "
              "vestibular nerve in the internal acoustic meatus. Vestibular schwannomas arise from the Schwann cells "
              "of the vestibular nerve around here, usually at the glial-Schwann junction in the meatus.",
    "spiral_g": "Spiral ganglion: the cell bodies of the bipolar cochlear neurons, in the spiral (Rosenthal) canal "
                "winding up the modiolus at the root of the osseous spiral lamina. Unusually, most are myelinated "
                "bipolar cells. Cochlear implants stimulate them directly, bypassing lost hair cells; noise can "
                "destroy the synapses between inner hair cells and these neurons before any hair cells die "
                "('hidden hearing loss').",
    "facial": "Facial nerve (VII): enters the internal acoustic meatus with VIII, then runs through the facial canal - "
              "labyrinthine segment (its narrowest, most vulnerable part), geniculate ganglion (sharp bend: first "
              "genu), tympanic segment along the medial wall of the middle ear above the oval window and below the "
              "lateral semicircular canal, second genu, and mastoid segment descending to the stylomastoid foramen. "
              "Branches in the temporal bone: greater petrosal nerve (lacrimal and nasal glands), nerve to stapedius, "
              "chorda tympani. It is at risk in middle-ear and mastoid surgery, in temporal bone fractures, from "
              "cholesteatoma and acute otitis media (the tympanic canal is often dehiscent), and in herpes zoster "
              "oticus (Ramsay Hunt syndrome: vesicles in the concha and meatus, facial palsy, hearing loss and "
              "vertigo). Bell palsy is an idiopathic swelling of the nerve in the canal; the level of a lesion is "
              "read from which branches still work (tears, hyperacusis, taste).",
    "geniculate": "Geniculate ganglion: the sensory ganglion of the facial nerve at its first genu, above the cochlea "
                  "- cell bodies of the taste fibres from the anterior two thirds of the tongue and of the few "
                  "cutaneous fibres from the concha. The greater petrosal nerve leaves it forwards. It is the site of "
                  "reactivation of varicella-zoster in Ramsay Hunt syndrome.",
    "chorda": "Chorda tympani: leaves the mastoid segment of the facial nerve, enters the tympanic cavity through the "
              "posterior wall, crosses the upper part of the tympanic membrane between the handle of the malleus "
              "(lateral) and the long process of the incus (medial), under the mucosa, and leaves through the "
              "petrotympanic fissure to join the lingual nerve. It carries taste from the anterior two thirds of "
              "the tongue and parasympathetic (preganglionic) fibres to the submandibular ganglion for the "
              "submandibular and sublingual glands. Commonly stretched or cut in middle-ear surgery - altered taste "
              "on that side of the tongue.",
    # ---- inset: cochlear duct
    "i_wall": "Bony wall of the cochlear canal (otic capsule), shown in section through one turn, with the modiolus "
              "at the left and the outer wall at the right.",
    "i_lamina": "Osseous spiral lamina in section: two thin plates of bone projecting from the modiolus, between which "
                "the myelinated peripheral processes of the spiral ganglion cells run out to the habenula perforata, "
                "where they lose their myelin and pass to the hair cells.",
    "i_lig": "Spiral ligament: the thickened, vascular periosteum of the outer wall; its fibrocytes recycle K+ from the "
             "organ of Corti back to the stria vascularis through gap junctions (connexin 26 - the GJB2 gene, whose "
             "mutations are the commonest cause of congenital non-syndromic deafness). Its basilar crest anchors the "
             "basilar membrane.",
    "i_stria": "Stria vascularis: a multilayered epithelium with an intraepithelial capillary network (marginal, "
               "intermediate and basal cells) on the outer wall of the cochlear duct. Marginal cells pump K+ into "
               "the endolymph (Na+/K+-ATPase, NKCC1 - blocked by loop diuretics, hence their ototoxicity) and "
               "generate the +80 mV endocochlear potential, which with the -70 mV inside hair cells gives a ~150 mV "
               "driving force for the transduction current. Strial atrophy gives flat 'metabolic' presbycusis.",
    "i_limbus": "Spiral limbus: a thickened pad of connective tissue on the osseous spiral lamina, capped by "
                "interdental cells that secrete the tectorial membrane, which is attached to it; the vestibular "
                "membrane attaches near its inner edge. Its overhanging lip covers the inner spiral sulcus.",
    "i_pillars": "Inner and outer pillar cells: stiff supporting cells packed with microtubules, leaning together to "
                 "enclose the triangular tunnel of Corti (filled with a perilymph-like fluid crossed by nerve fibres "
                 "on their way to the outer hair cells). Their heads form part of the reticular lamina.",
    "i_support": "Supporting cells: phalangeal (Deiters) cells cup the base of each outer hair cell and send a "
                 "process up to the reticular lamina, the tight-junction sheet that seals the endolymph away from the "
                 "cell bodies; Hensen cells (tall) and Claudius cells (low) lie further out. They buffer K+, and in "
                 "birds (not mammals) they can regenerate hair cells.",
    "ihc": "Inner hair cells: one row of ~3500 flask-shaped cells, each with a straight line of stereocilia graded in "
           "height, not attached to the tectorial membrane (moved by fluid flow). They are the true sensory "
           "receptors: each is contacted by ~10-20 type I afferent fibres, so ~95% of the cochlear nerve carries "
           "their output. Deflection of the bundle towards the tallest row opens mechanotransduction channels at "
           "the tip links; K+ flows in from endolymph, the cell depolarises and glutamate is released at ribbon "
           "synapses (otoferlin - OTOF deafness is an 'auditory neuropathy').",
    "ohc": "Outer hair cells: three rows of ~12000 cylindrical cells, their stereocilia in a W with the tallest "
           "embedded in the tectorial membrane. They are the cochlear amplifier: the motor protein prestin in their "
           "wall makes them shorten and lengthen with each cycle of sound (electromotility), boosting the "
           "basilar-membrane vibration ~100-fold (40-50 dB) and sharpening frequency tuning; by-products are "
           "otoacoustic emissions, used to screen newborn hearing. Outer hair cells are the first cells killed by "
           "noise, aminoglycosides (gentamicin), cisplatin and ageing - so noise-induced loss produces a notch at "
           "~4 kHz on the audiogram with loss of sensitivity and of frequency selectivity, tinnitus and difficulty "
           "hearing speech in background noise. Lost mammalian hair cells do not regenerate.",
    "stereocilia": "Stereocilia: rigid actin-filled microvilli arranged in rows of increasing height and linked tip "
                   "to tip; bending the bundle towards the tallest row stretches the tip links and opens "
                   "mechanotransduction channels (TMC1/2). Cochlear hair cells lose their kinocilium after "
                   "development. Myosin VIIA (Usher syndrome 1B: deafness with retinitis pigmentosa) and other "
                   "bundle proteins are frequent genetic causes of deafness.",
    "i_ganglion": "Spiral ganglion neurons in Rosenthal's canal: bipolar cell bodies whose peripheral processes run "
                  "through the osseous spiral lamina to the hair cells and whose central processes form the "
                  "cochlear nerve.",
    "i_fibres": "Cochlear nerve fibres: peripheral processes of the spiral ganglion neurons passing through the "
                "habenula perforata. Type I fibres (95%) each end on a single inner hair cell; type II fibres cross "
                "the tunnel of Corti and spiral along the outer hair cells, each contacting many.",
    # ---- insets: crista and macula
    "i_amp_wall": "Wall of the membranous ampulla: a thin connective-tissue layer lined by simple squamous "
                  "epithelium, with the dark cells near the crista that secrete K+ into the endolymph (as the stria "
                  "does in the cochlea).",
    "i_hc1": "Type I vestibular hair cells: flask-shaped, each enclosed by a cup-shaped nerve ending (calyx) of an "
             "afferent fibre; concentrated at the crest of the crista and the striola of the macula. Found only in "
             "amniotes, they are the most sensitive to aminoglycosides - gentamicin is deliberately used to destroy "
             "vestibular function in intractable Ménière disease.",
    "i_hc2": "Type II vestibular hair cells: cylindrical, contacted by several small bouton endings (afferent and "
             "efferent). Each hair cell carries 50-100 stereocilia in a staircase and one kinocilium at the tall "
             "edge.",
    "i_support_v": "Supporting cells of the vestibular sensory epithelium: columnar cells resting on the basement "
                   "membrane with their nuclei in a basal row, holding the hair cells and secreting the gelatinous "
                   "cupula or otolithic membrane.",
    "i_cilia": "Stereocilia and kinocilium: each hair cell has a staircase of stereocilia with a single true "
               "kinocilium beside the tallest row. Bending towards the kinocilium depolarises the cell and increases "
               "the firing of its afferent fibre above its resting rate (~90 spikes/s); bending away hyperpolarises "
               "it and reduces firing. In a crista all bundles point the same way; in a macula they reverse across "
               "the striola.",
    "i_amp_n": "Ampullary nerve: the fibres from the crista gather into a branch of the vestibular nerve (superior "
               "division for the anterior and lateral cristae, inferior division for the posterior).",
    "i_lp": "Connective tissue of the macula, beneath the sensory epithelium, carrying the myelinated vestibular "
            "nerve fibres to the calyx and bouton endings on the hair cells.",
    "i_gel": "Gelatinous layer of the otolithic membrane, into which the hair bundles project; it couples the heavy "
             "crystal layer to the hair bundles.",
    "i_otoconia": "Otoconia: calcium carbonate (calcite) crystals bound in a protein matrix (otoconin-90), spindle "
                  "shaped with pointed ends, loading the otolithic membrane so that it has inertia and weight. They "
                  "are slowly renewed and degenerate with age; loose otoconia cause BPPV.",
    "i_mac_n": "Nerve fibres of the macula: afferents to the vestibular nerve (utricle - superior division; saccule - "
               "inferior division), plus efferent fibres from the brainstem.",
})
