"""Secondary lymphoid organs: a whole lymph node and a block of splenic pulp.

The lymph node is modelled whole - a bean with its hilum underneath - because its architecture only makes sense as
concentric zones: capsule, subcapsular sinus, outer cortex with follicles, paracortex, medulla. Every zone is cut out
of one signed-distance field, the body of the node, by depth below the capsule, so the zones nest exactly and the
cut-away sections all of them at once, like a slide through the hilum.

The spleen is a block with the capsule on top. White pulp (a periarteriolar sheath around a central artery, with a
follicle budding from it) sits in red pulp that is itself two things: venous sinusoids with barrel-stave walls, and
the splenic cords between them, built as the complement of everything else so the sinusoids show on every face."""
import math

import numpy as np
from scipy.spatial import Delaunay, cKDTree

from .cells import frame_from_normal
from .geometry import Mesh, ellipsoid as ellipsoid_mesh, smooth_path, tube
from .kit import Volume, ellipsoid, hlayer, mesh_part, round_cone, sdf_part, sphere
from .organic import Sweep, cell_lattice, settle, tubule
from .sdf import smin


# =============================================================================== shared helpers
def _smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _thin(pts, spacing, seed=0):
    """Greedy thinning of candidate points to a minimum spacing (a cheap Poisson-disk set)."""
    pts = np.asarray(pts, float)
    if not len(pts):
        return pts
    order = np.random.default_rng(seed).permutation(len(pts))
    pts = pts[order]
    tree = cKDTree(pts)
    blocked = np.zeros(len(pts), bool)
    keep = []
    for i in range(len(pts)):
        if blocked[i]:
            continue
        keep.append(i)
        blocked[tree.query_ball_point(pts[i], spacing)] = True
    return pts[keep]


def _voxels_where(vol, mask, count, seed=0):
    """World positions of up to `count` random voxels where mask is true."""
    idx = np.argwhere(mask)
    if not len(idx):
        return np.zeros((0, 3))
    rng = np.random.default_rng(seed)
    idx = idx[rng.choice(len(idx), min(count, len(idx)), replace=False)]
    return vol.lo + idx * vol.voxel + rng.uniform(-0.5, 0.5, idx.shape) * vol.voxel


def _sample(vol, d, pts):
    """Nearest-voxel lookup of a field at world points."""
    idx = np.rint((np.asarray(pts, float) - vol.lo) / vol.voxel).astype(int)
    idx = np.clip(idx, 0, np.array(vol.shape) - 1)
    return d[idx[:, 0], idx[:, 1], idx[:, 2]]


def _halved(shape, c, n, sign):
    """A primitive cut in half by the plane through c normal to n (sign +1 keeps the side n points to)."""
    fn_, bmin, bmax = shape
    c = np.asarray(c, np.float32)
    n = np.asarray(n, np.float32)

    def f(x, y, z):
        s = (x - c[0]) * n[0] + (y - c[1]) * n[1] + (z - c[2]) * n[2]
        return np.maximum(fn_(x, y, z), -sign * s)
    return f, bmin, bmax


def _mesh_network(pts, link, radius, seed=0, k=2, segments=5):
    """A meshwork of thin fibres: every point joined to its k nearest neighbours closer than `link`."""
    m = Mesh()
    if len(pts) < 2:
        return m
    rng = np.random.default_rng(seed)
    tree = cKDTree(pts)
    done = set()
    d, nb = tree.query(pts, k=k + 1)
    for i in range(len(pts)):
        for dist, j in zip(d[i, 1:], nb[i, 1:]):
            key = (min(i, j), max(i, j))
            if dist > link or key in done:
                continue
            done.add(key)
            a, b = pts[i], pts[j]
            mid = (a + b) / 2 + rng.normal(scale=dist * 0.12, size=3)
            m.extend(tube(np.array([a, mid, b]), radius * rng.uniform(0.8, 1.2), segments))
    return m


def _valve_cusps(sw, s, r, flow=1.0):
    """Two semilunar cusps inside a swept lymphatic at arc fraction s, their free edges pointing downstream."""
    m = Mesh()
    i = int(np.clip(round(s * (sw.n_s - 1)), 0, sw.n_s - 1))
    c, t, nv, bv = sw.path[i], sw.t[i] * flow, sw.nrm[i], sw.bi[i]
    for sign in (-1.0, 1.0):
        d = t * 0.78 - nv * sign * 0.62
        d /= np.linalg.norm(d)
        thick = np.cross(bv, d)
        thick /= np.linalg.norm(thick)
        rot = np.stack([d, thick, bv], axis=1)
        centre = c + nv * sign * r * 0.52 + t * r * 0.30
        m.extend(ellipsoid_mesh(centre, (r * 0.58, r * 0.10, r * 0.86), 10, rotation=rot))
    return m


def _beaded_lymphatic(path, r0, wall, valves, n_theta=24, n_s=72, flow=1.0):
    """A collecting lymphatic: a thin wall pinched at each valve and swollen just downstream of it (the valve
    sinus), which is what gives lymphatics their beaded, string-of-pearls look. Returns (wall mesh, cusp mesh)."""
    sw = Sweep(path, n_theta, n_s)
    ss = np.asarray(valves, float)

    def r_out(T, S):
        prof = np.ones_like(S)
        for sk in ss:
            prof = prof - 0.22 * np.exp(-((S - sk) / 0.022) ** 2) + 0.24 * np.exp(-((S - sk - flow * 0.06) / 0.04) ** 2)
        return r0 * prof * (1.0 + 0.04 * np.cos(2 * T + 3 * S))

    def r_in(T, S):
        return r_out(T, S) - wall
    cusps = Mesh()
    for sk in ss:
        cusps.extend(_valve_cusps(sw, float(sk), r0 * 0.8, flow))
    return sw.shell(r_in, r_out), cusps


# =============================================================================== lymph node
LN = {
    "capsule": "Capsule: dense irregular connective tissue (type I collagen) enclosing the node and thickened at "
               "the hilum. Afferent lymphatics pierce it on the convex surface; trabeculae run inwards from it.",
    "trabeculae": "Trabeculae: connective-tissue septa that run from the capsule towards the hilum, partly dividing "
                  "the cortex into compartments and carrying blood vessels; in the medulla they become the medullary "
                  "trabeculae converging on the hilum.",
    "scs": "Subcapsular (marginal) sinus: the space under the capsule into which afferent lymph pours. It is crossed "
           "by reticular fibres and lined by endothelium; its macrophages and the floor's subcapsular-sinus "
           "macrophages capture particles and hand antigen to the follicles beneath. Metastatic carcinoma cells "
           "lodge here first, so a sentinel node is examined under the capsule.",
    "tsin": "Trabecular (cortical) sinuses: channels alongside the trabeculae that carry lymph from the subcapsular "
            "sinus through the cortex to the medullary sinuses.",
    "cortex": "Outer (superficial) cortex: the B-cell zone. Between the follicles lies diffuse lymphoid tissue on a "
              "meshwork of reticular cells and fibres.",
    "primary": "Primary follicles: round, uniformly dense clusters of naive (IgM+ IgD+) B cells on a meshwork of "
               "follicular dendritic cells, seen before antigen stimulation. They have no germinal centre.",
    "mantle": "Mantle zone (corona): the dark rim of small, resting naive B cells pushed aside by the expanding "
              "germinal centre; it is thickest on the capsular side, forming a 'cap'. Mantle cell lymphoma "
              "(cyclin D1, t(11;14)) arises here.",
    "gc_light": "Germinal centre - light zone (capsular pole): centrocytes, follicular dendritic cells holding "
                "antigen-antibody complexes and follicular helper T cells. Centrocytes compete for antigen and T-cell "
                "help: those with high-affinity receptors survive (affinity maturation), switch class and leave as "
                "plasma cells or memory B cells; the rest die by apoptosis and are eaten by tingible-body "
                "macrophages. Follicular lymphoma (BCL2, t(14;18)) mimics these follicles but lacks polarity and "
                "tingible-body macrophages.",
    "gc_dark": "Germinal centre - dark zone (medullary pole): densely packed, rapidly dividing centroblasts that "
               "undergo somatic hypermutation of their immunoglobulin genes (AID enzyme). A germinal centre marks "
               "a secondary follicle - one responding to antigen, 1-3 weeks after exposure.",
    "paracortex": "Paracortex (deep cortex): the thymus-dependent T-cell zone between the follicles and the medulla. "
                  "Dendritic cells arriving in afferent lymph present antigen to T cells here. It expands in viral "
                  "infections and is depleted in DiGeorge syndrome and after thymectomy in infancy.",
    "hev": "High endothelial venules: postcapillary venules of the paracortex lined by plump cuboidal endothelium. "
           "Naive T and B cells leave the blood here - L-selectin binds peripheral node addressin, CCL19/CCL21 "
           "activate integrins - so about 90 % of the lymphocytes entering a node arrive from the blood, not the "
           "lymph.",
    "cords": "Medullary cords: branching cords of lymphoid tissue rich in plasma cells, macrophages and lymphocytes, "
             "continuous with the paracortex. Plasma cells secrete antibody straight into the efferent lymph.",
    "msin": "Medullary sinuses: wide, tortuous lymph channels between the medullary cords, lined by discontinuous "
            "endothelium and full of macrophages; they converge on the efferent lymphatic at the hilum.",
    "reticular": "Reticular fibre meshwork (type III collagen) spun by fibroblastic reticular cells across the "
                 "sinuses and through the whole node. It slows the lymph so macrophages can filter it, and in the "
                 "cortex its fibres are sheathed as conduits that deliver small soluble antigens to the "
                 "high endothelial venules and dendritic cells. Shown by silver stains.",
    "macrophage": "Sinus macrophages: phagocytes clinging to the reticular meshwork of the sinuses. They remove "
                  "bacteria, debris and particles - carbon pigment (anthracosis) in thoracic nodes, tattoo ink in "
                  "axillary nodes - and present antigen.",
    "afferent": "Afferent lymphatic vessels: several thin-walled collecting lymphatics that pierce the capsule on the "
                "convex surface and empty into the subcapsular sinus. Their valves force one-way flow into the node, "
                "and the swelling just beyond each valve gives the vessel its beaded look.",
    "valves": "Lymphatic valves: paired semilunar cusps of endothelium on a thin connective-tissue core whose free "
              "edges point downstream - towards the node in afferent vessels, away from it in the efferent vessel.",
    "efferent": "Efferent lymphatic vessel: leaves at the hilum carrying filtered lymph, plasma-cell antibody and "
                "activated lymphocytes onward to the next node in the chain and ultimately to the thoracic or right "
                "lymphatic duct. There is usually only one, and it has valves.",
    "artery": "Nodal artery: enters at the hilum, runs in the medullary cords and trabeculae and breaks into a "
              "capillary bed in the cortex whose postcapillary venules are the high endothelial venules.",
    "vein": "Nodal vein: formed from the high endothelial venules and medullary veins, leaves at the hilum beside the "
            "artery.",
    "hilum": "Hilum: the indentation on the concave side where the artery enters and the vein and efferent "
             "lymphatic leave, packed with connective tissue and fat continuous with the capsule.",
}

T_CAP, T_SCS, T_PARA, T_MED = 0.030, 0.062, 0.215, 0.32
LN_LO, LN_HI = np.array([-1.08, -0.62, -0.62]), np.array([1.08, 0.66, 0.62])


def _ln_body(x, y, z):
    """Signed distance (approximate) of the node: a bean - ellipsoid with drooping ends - with the hilum notch."""
    yb = y - 0.03 + 0.13 * x * x
    r = (1.0, 0.56, 0.55)
    k0 = np.sqrt((x / r[0]) ** 2 + (yb / r[1]) ** 2 + (z / r[2]) ** 2)
    k1 = np.sqrt((x / r[0] ** 2) ** 2 + (yb / r[1] ** 2) ** 2 + (z / r[2] ** 2) ** 2)
    e = k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)
    nk0 = np.sqrt((x / 0.30) ** 2 + ((y + 0.76) / 0.33) ** 2 + (z / 0.30) ** 2)
    nk1 = np.sqrt((x / 0.09) ** 2 + ((y + 0.76) / 0.1089) ** 2 + (z / 0.09) ** 2)
    notch = nk0 * (nk0 - 1.0) / np.maximum(nk1, 1e-9)
    return -smin(-e, notch, 0.10)


def _ln_bias(y):
    """Extra depth towards the hilum: the cortex thins and the medulla comes close to the surface there."""
    return 0.20 * _smoothstep((0.10 - y) / 0.55)


def _ln_grad(p, eps=1e-3):
    g = np.zeros_like(p)
    for c in range(3):
        a, b = p.copy(), p.copy()
        a[:, c] += eps
        b[:, c] -= eps
        g[:, c] = (_ln_body(a[:, 0], a[:, 1], a[:, 2]) - _ln_body(b[:, 0], b[:, 1], b[:, 2])) / (2 * eps)
    return g


def _ln_surface(p):
    """Project points onto the node surface; returns (points, inward unit normals)."""
    p = np.asarray(p, float).copy()
    for _ in range(8):
        g = _ln_grad(p)
        d = _ln_body(p[:, 0], p[:, 1], p[:, 2])
        p -= (d / np.maximum((g * g).sum(1), 1e-9))[:, None] * g
    g = _ln_grad(p)
    return p, -g / np.linalg.norm(g, axis=1, keepdims=True)


def _ln_depth(p):
    p = np.atleast_2d(p)
    d = -_ln_body(p[:, 0], p[:, 1], p[:, 2])
    return d, d + _ln_bias(p[:, 1])


def _fib_dirs(n):
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    th = math.pi * (1 + 5 ** 0.5) * i
    return np.stack([np.sin(phi) * np.cos(th), np.cos(phi), np.sin(phi) * np.sin(th)], -1)


def _ln_seeds(dirs):
    return np.stack([dirs[:, 0] * 1.0, dirs[:, 1] * 0.56 + 0.03 - 0.13 * dirs[:, 0] ** 2, dirs[:, 2] * 0.55], -1)


def build_lymph_node():
    rng = np.random.default_rng(31)
    parts = []
    vox = 0.0105
    body = Volume(LN_LO, LN_HI, vox)
    x, y, z = body.axes()
    body.d = np.broadcast_to(_ln_body(x, y, z), body.shape).astype(np.float32).copy()
    body.displace(0.006, 3.2, 2, seed=5)
    B = body.d
    D = -B
    Dz = D + _ln_bias(y)
    hy = -0.43                                           # roof of the hilum notch on the axis
    for yy in np.linspace(-0.6, 0.0, 241):
        if _ln_body(np.array([0.0]), np.array([yy]), np.array([0.0]))[0] < 0:
            hy = yy
            break
    H = np.array([0.0, hy, 0.0])

    # ------------------------------------------------------------------ follicles (placed first; all else avoids)
    # seeds in the two cut planes come first so the cut-away sections a row of follicles through their middles
    th = np.linspace(0.18, math.pi - 0.18, 9)
    plane_z = [(-math.cos(t) * 0.95, math.sin(t), 0.0) for t in th if math.cos(t) > 0.12]
    plane_z += [(-0.93, -0.3, 0.0), (-0.72, -0.62, 0.0)]
    ph = np.linspace(-1.2, 1.35, 7)
    plane_x = [(0.0, math.sin(p), math.cos(p)) for p in ph]
    seeds = np.vstack([_ln_seeds(np.array(plane_z)), _ln_seeds(np.array(plane_x)),
                       _ln_seeds(_fib_dirs(420)[rng.permutation(420)])])
    surf, inward = _ln_surface(seeds)
    follicles = []
    for k, (p, n) in enumerate(zip(surf, inward)):
        if np.linalg.norm(p - H) < 0.42 or p[1] < H[1] + 0.06:
            continue
        secondary = rng.random() < 0.7 or k < len(plane_z) + len(plane_x) - 3
        r = rng.uniform(0.088, 0.112) if secondary else rng.uniform(0.064, 0.078)
        c = p + n * (T_SCS + 0.003 + r * 0.86)
        if all(np.linalg.norm(c - fc) > r + fr + 0.028 for fc, fr, _, _ in follicles):
            follicles.append((c, r, n, secondary))
    fol = Volume(LN_LO, LN_HI, vox)
    prim = Volume(LN_LO, LN_HI, vox)
    gcl = Volume(LN_LO, LN_HI, vox)
    gcd = Volume(LN_LO, LN_HI, vox)
    for c, r, n, secondary in follicles:
        rot = frame_from_normal(n)
        (fol if secondary else prim).add(ellipsoid(c, (r, r * 0.84, r), rot))
        if secondary:
            gc_c = c + n * r * 0.12
            gc = ellipsoid(gc_c, (r * 0.62, r * 0.60, r * 0.62), rot)
            gcl.add(_halved(gc, gc_c + n * r * 0.05, n, -1))
            gcd.add(_halved(gc, gc_c + n * r * 0.05, n, +1))
    for v in (fol, prim):
        v.displace(0.004, 16.0, 2, seed=7)
        np.maximum(v.d, B + T_SCS + 0.002, out=v.d)
    gc_all = np.minimum(gcl.d, gcd.d)
    fol_all = np.minimum(fol.d, prim.d)

    # ------------------------------------------------------------------ trabeculae and their sinuses
    fc_arr = np.array([f[0] for f in follicles])
    fr_arr = np.array([f[1] for f in follicles])
    th2 = np.linspace(0.3, math.pi - 0.3, 25)
    cand = [(-math.cos(t), math.sin(t), 0.0) for t in th2 if math.cos(t) > 0.1]
    cand += [(0.0, math.sin(p), math.cos(p)) for p in np.linspace(-1.1, 1.3, 19)]
    tseeds = np.vstack([_ln_seeds(np.array(cand)), _ln_seeds(_fib_dirs(300)[rng.permutation(300)])])
    tsurf, tin = _ln_surface(tseeds)
    tra_paths = []
    H_in = H + np.array([0.0, 0.12, 0.0])
    for p, n in zip(tsurf, tin):
        if np.linalg.norm(p - H) < 0.45 or p[1] < H[1] + 0.1:
            continue
        gap = np.linalg.norm(fc_arr - (p + n * 0.1), axis=1) - fr_arr
        if gap.min() < 0.035 or any(np.linalg.norm(p - q[0]) < 0.34 for q in tra_paths):
            continue
        mid = p + n * 0.24
        path = smooth_path(np.array([p - n * 0.008, p + n * 0.12, mid, mid * 0.45 + H_in * 0.55, H_in]), 40)
        tra_paths.append(path)
        if len(tra_paths) >= 16:
            break
    tra = Volume(LN_LO, LN_HI, vox)
    tsin = Volume(LN_LO, LN_HI, vox)
    for path in tra_paths:
        rad = np.interp(np.linspace(0, 1, len(path)), [0, 0.3, 0.8, 1], [0.024, 0.016, 0.014, 0.022])
        tra.tube(path, rad)
        tsin.tube(path, rad + 0.020)
    tra.displace(0.003, 22.0, 2, seed=9)

    # ------------------------------------------------------------------ hilum, vessels (carved from every zone)
    hil = Volume(LN_LO, LN_HI, vox)
    hil.add(ellipsoid(H + np.array([0.0, 0.03, 0.0]), (0.24, 0.12, 0.2)), "smooth", 0.04)
    np.maximum(hil.d, B + 0.004, out=hil.d)
    carve = Volume(LN_LO, LN_HI, vox)
    art_m, vein_m = Mesh(), Mesh()
    med_targets = [np.array(t) for t in ((-0.52, -0.12, 0.10), (-0.22, 0.02, -0.14), (0.25, 0.04, 0.12),
                                         (0.55, -0.10, -0.06), (-0.05, 0.12, 0.2), (0.05, 0.08, -0.25))]
    # outside the node the three hilar vessels run together down and forwards, clear of the cut-away quadrant
    for k, (off, rad, rb, mesh_, outs) in enumerate((
            (np.array([0.075, 0.0, 0.035]), 0.026, 0.012, art_m, ((0.5, -0.84, 0.58), (0.34, -0.76, 0.38),
                                                                  (0.16, -0.60, 0.14))),
            (np.array([-0.07, 0.0, 0.05]), 0.034, 0.016, vein_m, ((0.36, -0.90, 0.64), (0.22, -0.80, 0.42),
                                                                  (0.03, -0.62, 0.18))))):
        root = H + off
        trunk = smooth_path(np.array(list(outs) + [root + np.array([0, -0.10, 0]), root,
                                                   root + np.array([0, 0.10, 0])]), 60)
        mesh_.extend(tube(trunk, rad, 18))
        carve.tube(trunk, rad + 0.006)
        for j, t in enumerate(med_targets):
            tgt = t + rng.normal(scale=0.03, size=3) + np.array([0.0, 0.0, 0.05 * (1 - 2 * k)])
            a = root + np.array([0, 0.08, 0])
            bpath = smooth_path(np.array([a, a * 0.5 + tgt * 0.5 + np.array([0, -0.04, 0]), tgt,
                                          tgt + (tgt - a) * 0.35 + np.array([0, 0.1, 0])]), 30)
            mesh_.extend(tube(bpath, np.linspace(rb, rb * 0.6, len(bpath)), 12))
            carve.tube(bpath, rb + 0.005)
    eff_path = smooth_path(np.array([H + np.array([0.0, 0.10, -0.12]), H + np.array([0.0, -0.02, -0.12]),
                                     (0.1, -0.60, -0.02), (0.32, -0.78, 0.18), (0.56, -0.87, 0.34)]), 70)
    eff_wall, eff_valves = _beaded_lymphatic(eff_path, 0.048, 0.008, (0.45, 0.8), n_theta=40, n_s=80)
    carve.tube(eff_path[:30], 0.056)

    # ------------------------------------------------------------------ high endothelial venules (paracortex)
    hev_mesh = Mesh()
    hev_v = Volume(LN_LO, LN_HI, vox)
    band = (Dz > T_PARA + 0.03) & (Dz < T_MED - 0.03) & (fol_all > 0.03) & (D > T_SCS + 0.06)
    hv_pts = _thin(_voxels_where(body, band, 4000, seed=3), 0.2, seed=4)
    fixed = [np.array([-0.62, 0.20, 0.0]), np.array([-0.25, 0.30, 0.0]), np.array([0.0, 0.22, 0.30]),
             np.array([0.0, -0.1, 0.36])]
    hv_pts = [p for p in hv_pts if all(np.linalg.norm(p - f) > 0.18 for f in fixed)][:14]
    for i, p in enumerate(fixed + list(hv_pts)):
        dp, dzp = _ln_depth(p)
        if not (T_PARA < dzp[0] < T_MED):
            p = p * 0.97
        g = _ln_grad(p[None])[0]
        g /= np.linalg.norm(g)
        if i < 2:
            d = np.array([0.0, 0.0, 1.0])       # crosses the z = 0 cut: sectioned across, like on a slide
        elif i < 4:
            d = np.array([1.0, 0.0, 0.0])
        else:
            d = np.cross(g, rng.normal(size=3))
        d -= g * (d @ g)
        d /= np.linalg.norm(d)
        side = np.cross(d, g)
        jog = rng.uniform(-0.03, 0.03)
        for _ in range(5):                  # sink the venule until it runs clear of the follicles, in paracortex
            path = smooth_path(np.array([p - d * 0.11 + side * 0.02, p + side * jog,
                                         p + d * 0.11 - side * 0.02 + g * 0.02]), 40)
            if _sample(body, fol_all, path).min() > 0.045 and _sample(body, Dz, path).max() < T_MED + 0.01:
                break
            p = p - g * 0.03
        else:
            continue
        _, m = tubule(path, 0.012, 0.031, seed=40 + i, cell=0.019, amp=0.005, aspect=1.0, lobe=(4, 0.05),
                      calibre=0.05, n_theta=26, n_s=32)
        hev_mesh.extend(m)
        hev_v.tube(path, 0.033)

    # ------------------------------------------------------------------ medullary cords (a branching network)
    med_region = np.maximum(B + T_SCS, T_MED - Dz)
    cpts = _thin(_voxels_where(body, (med_region < 0.02) & (hil.d > 0.02), 6000, seed=11), 0.105, seed=12)
    cord = Volume(LN_LO, LN_HI, vox)
    shapes = [sphere(p, 0.040 * rng.uniform(0.85, 1.15)) for p in cpts]
    if len(cpts) >= 5:
        tri = Delaunay(cpts)
        edges = set()
        for s in tri.simplices:
            for a in range(4):
                for b in range(a + 1, 4):
                    i, j = sorted((int(s[a]), int(s[b])))
                    if np.linalg.norm(cpts[i] - cpts[j]) < 0.165:
                        edges.add((i, j))
        for i, j in edges:
            if rng.random() < 0.72:
                shapes.append(round_cone(cpts[i], cpts[j], 0.030, 0.030))
    cord.add_all(shapes, "smooth", 0.02)
    cord.displace(0.004, 18.0, 2, seed=13)

    # ------------------------------------------------------------------ assemble the zones
    def minus(field, *others, margin=0.001):
        out = field.copy()
        for o in others:
            np.maximum(out, -(o - margin), out=out)
        return out

    lymph_holes = np.minimum(np.minimum(carve.d, hev_v.d), hil.d)
    # the opaque zones are all polygonised at the same resolution and smoothing: a solid cut by the viewer is capped
    # at its own back faces, so neighbours must meet with only a hair's gap between them or the cut shows into the
    # gap. The capsule's inner face and the translucent subcapsular sinus are not capped and can be coarser.
    cap_mesh = body.copy(B).mesh(0.9)
    for pos, nrm, idx in body.copy(B + T_CAP).mesh(0.9, step=2).parts:
        cap_mesh.add(pos, idx[:, ::-1], -nrm)           # turned inside out: it faces the node's interior
    parts.append(mesh_part(cap_mesh, "Capsule", "Capsule & trabeculae", "#e0c09c", LN["capsule"], "ligament",
                           rank=2, detail=(0.12, 55.0, 0.15, 0)))
    tra_d = np.maximum(tra.d, B + 0.004)
    tra_d = minus(tra_d, carve.d, hil.d)
    parts.append(sdf_part(body.copy(tra_d), "Trabeculae", "Capsule & trabeculae", "#d6ae88", LN["trabeculae"],
                          "ligament", smooth=0.8, rank=1.5, detail=(0.12, 55.0, 0.15, 0)))
    hil_d = minus(hil.d, carve.d, tra.d)
    parts.append(sdf_part(body.copy(hil_d), "Hilum connective tissue", "Hilum & vessels", "#ecd6a8", LN["hilum"],
                          "fascia", smooth=0.8, rank=-2, detail=(0.10, 30.0, 0.15, 0)))

    scs = np.maximum(B + T_CAP, -(B + T_SCS))
    scs = minus(scs, tra.d, carve.d, fol_all)
    tsin_d = np.maximum(np.maximum(tsin.d, B + T_SCS - 0.004), Dz - T_MED - 0.02)
    tsin_d = minus(tsin_d, tra.d, fol_all, lymph_holes)
    sinus_detail = (0.05, 60.0, 0.25, 0)
    parts.append(sdf_part(body.copy(scs), "Subcapsular sinus", "Sinuses", "#cfe4ef", LN["scs"], "csf", smooth=0.7,
                          rank=1.8, alpha=0.78, step=2, detail=sinus_detail))
    parts.append(sdf_part(body.copy(tsin_d), "Trabecular sinuses", "Sinuses", "#c6deeb", LN["tsin"], "csf",
                          smooth=0.7, rank=1.2, alpha=0.78, detail=sinus_detail, step=1))

    ctx = np.maximum(B + T_SCS, Dz - T_PARA)
    ctx = minus(ctx, fol_all, tsin.d, lymph_holes)
    parts.append(sdf_part(body.copy(ctx), "Outer cortex (B-cell zone)", "Cortex", "#6d78bd", LN["cortex"], "lymph",
                          smooth=0.8, rank=1, bulk=True, detail=(0.07, 190.0, 0.97, 0)))
    parts.append(sdf_part(prim, "Primary follicles", "Cortex", "#4a53a4", LN["primary"], "lymph", smooth=0.8,
                          rank=1.1, detail=(0.06, 210.0, 0.98, 0)))
    mantle = minus(fol.d, gc_all)
    parts.append(sdf_part(body.copy(mantle), "Mantle zone (secondary follicles)", "Cortex", "#3f4799", LN["mantle"],
                          "lymph", smooth=0.8, rank=1.1, detail=(0.06, 220.0, 0.98, 0)))
    parts.append(sdf_part(gcl, "Germinal centre - light zone", "Cortex", "#dcd5f1", LN["gc_light"], "lymph",
                          smooth=0.8, rank=1.2, detail=(0.07, 110.0, 0.6, 0)))
    parts.append(sdf_part(gcd, "Germinal centre - dark zone", "Cortex", "#9d92d8", LN["gc_dark"], "lymph",
                          smooth=0.8, rank=1.2, detail=(0.07, 150.0, 0.9, 0)))

    para = np.maximum(np.maximum(B + T_SCS, T_PARA - Dz), Dz - T_MED)
    para = minus(para, fol_all, tsin.d, lymph_holes)
    parts.append(sdf_part(body.copy(para), "Paracortex (T-cell zone)", "Paracortex", "#78ab98", LN["paracortex"],
                          "lymph", smooth=0.8, rank=0, bulk=True, detail=(0.07, 180.0, 0.95, 0)))
    parts.append(mesh_part(hev_mesh, "High endothelial venules", "Paracortex", "#e27a8e", LN["hev"], "vein",
                           rank=0.2, detail=(0.06, 90.0, 0.8, 0)))

    cords = np.maximum(med_region, cord.d)
    cords = minus(cords, tra.d, lymph_holes)
    parts.append(sdf_part(body.copy(cords), "Medullary cords", "Medulla", "#c07a95", LN["cords"], "lymph",
                          smooth=0.8, rank=-1, detail=(0.08, 150.0, 0.9, 0)))
    msin = minus(med_region, cord.d, tra.d, lymph_holes)
    parts.append(sdf_part(body.copy(msin), "Medullary sinuses", "Sinuses", "#d3e7f1", LN["msin"], "csf",
                          smooth=0.7, rank=-1.2, detail=sinus_detail))

    # ------------------------------------------------------------------ reticular meshwork and sinus macrophages
    ret_pts = [_voxels_where(body, scs < -0.004, 1000, seed=21),
               _voxels_where(body, msin < -0.008, 1300, seed=22),
               _voxels_where(body, tsin_d < -0.006, 250, seed=23)]
    ret = Mesh()
    for i, pts in enumerate(ret_pts):
        ret.extend(_mesh_network(_thin(pts, 0.026, seed=24 + i), 0.06, 0.0028, seed=25 + i, k=3, segments=4))
    parts.append(mesh_part(ret, "Reticular fibre meshwork", "Sinuses", "#6b5140", LN["reticular"], "fascia",
                           rank=0.5, label=True, detail=(0.04, 0.0, 0.0, 0)))
    mac = Mesh()
    mac_pts = np.vstack([_thin(_voxels_where(body, scs < -0.008, 400, seed=31), 0.12, seed=32),
                         _thin(_voxels_where(body, msin < -0.015, 400, seed=33), 0.09, seed=34)])
    for i, c in enumerate(mac_pts):
        mac.extend(ellipsoid_mesh(c, (0.012, 0.009, 0.011), 5))
        for a in range(4):
            dvec = rng.normal(size=3)
            dvec /= np.linalg.norm(dvec)
            mac.extend(tube(np.array([c, c + dvec * 0.012, c + dvec * 0.024 + rng.normal(scale=0.004, size=3)]),
                            np.array([0.005, 0.0032, 0.0012]), 4))
    parts.append(mesh_part(mac, "Sinus macrophages", "Sinuses", "#b98a55", LN["macrophage"], "organ", rank=0.6,
                           detail=(0.05, 0.0, 0.0, 0)))

    # ------------------------------------------------------------------ lymphatics
    aff_w, aff_v = Mesh(), Mesh()
    entries = [(-0.5, 0.95, 0.0), (0.35, 0.9, -0.4), (0.0, 0.55, 0.85), (-0.8, 0.2, -0.55), (0.78, 0.4, 0.5),
               (0.55, 0.85, 0.3)]
    for i, e in enumerate(entries):
        p, n = _ln_surface(_ln_seeds(np.array([e]) / np.linalg.norm(e)))
        p, n = p[0], n[0]
        out = -n
        # the first vessel runs in the z = 0 cut plane, so the cut opens it where it pierces the capsule
        tang = np.cross(out, np.array([0.0, 0.0, 1.0]) if i == 0 else rng.normal(size=3))
        tang /= np.linalg.norm(tang)
        path = smooth_path(np.array([p + out * 0.40 + tang * 0.22, p + out * 0.22 + tang * 0.12,
                                     p + out * 0.07 + tang * 0.03, p + out * 0.01, p + n * (T_CAP + 0.006)]), 60)
        w, v = _beaded_lymphatic(path, 0.030, 0.006, (0.22, 0.52, 0.80))
        aff_w.extend(w)
        aff_v.extend(v)
    parts.append(mesh_part(aff_w, "Afferent lymphatic vessels", "Lymphatics", "#b3d67c", LN["afferent"], "lymph",
                           rank=3, alpha=0.72, detail=(0.05, 90.0, 0.5, 0)))
    parts.append(mesh_part(eff_wall, "Efferent lymphatic vessel", "Lymphatics", "#9fcb68", LN["efferent"], "lymph",
                           rank=-3, alpha=0.72, detail=(0.05, 90.0, 0.5, 0)))
    aff_v.extend(eff_valves)
    parts.append(mesh_part(aff_v, "Lymphatic valves", "Lymphatics", "#eef3cf", LN["valves"], "lymph", rank=3,
                           detail=(0.04, 0.0, 0.0, 0)))
    parts.append(mesh_part(art_m, "Artery (hilar and medullary branches)", "Hilum & vessels", "#cf3a31",
                           LN["artery"], "artery", rank=-3))
    parts.append(mesh_part(vein_m, "Vein (hilar and medullary tributaries)", "Hilum & vessels", "#3d5bc2",
                           LN["vein"], "vein", rank=-3))
    return settle(parts, seed=611, amp_xz=0.018, amp_y=0.03, freq=1.3, shear=0.008, grain=0.004, micro=0.003)


# =============================================================================== spleen
SPLEEN = {
    "mesothelium": "Mesothelium: the visceral peritoneum covering the spleen everywhere except at the hilum - a "
                   "simple squamous epithelium that keeps the surface slippery against the diaphragm and stomach.",
    "capsule": "Capsule: dense connective tissue with elastic fibres (and, in some mammals, smooth muscle that lets "
               "the spleen contract and release stored blood). It is thin in humans, which is why the spleen "
               "ruptures so easily after blunt trauma to the left upper quadrant.",
    "trabeculae": "Trabeculae: connective-tissue septa running in from the capsule and hilum, carrying the "
                  "trabecular arteries and veins. Unlike the lymph node, the spleen has no cortex and medulla - "
                  "the trabeculae simply subdivide a continuous pulp.",
    "tr_artery": "Trabecular artery: a branch of the splenic artery (from the coeliac trunk) running in a trabecula; "
                 "on leaving it the vessel picks up a lymphoid sheath and becomes the central artery. Splenic arterial "
                 "branches are end arteries, so their occlusion (sickle cell disease, emboli, massive splenomegaly) "
                 "gives wedge-shaped infarcts under the capsule.",
    "tr_vein": "Trabecular vein: thin-walled vein with no muscular coat of its own, collecting blood from the pulp "
               "veins and draining to the splenic vein and the portal system. Portal hypertension backs blood up "
               "here and causes congestive splenomegaly.",
    "central": "Central artery (arteriole): runs through the white pulp surrounded by its lymphoid sheath, usually "
               "eccentrically placed in a follicle. Its side branches supply the white pulp and end in the "
               "marginal zone; its end divides into penicillar arterioles in the red pulp.",
    "pals": "Periarteriolar lymphoid sheath (PALS): the T-cell zone of the white pulp, a cuff of T lymphocytes and "
            "interdigitating dendritic cells around the central artery - the counterpart of the lymph node "
            "paracortex. It is depleted in DiGeorge syndrome.",
    "follicle": "Splenic follicle (Malpighian corpuscle): the B-cell zone budding off the PALS, with a dark mantle "
                "of small naive B cells. Seen as the grey-white dots on a cut spleen that give the white pulp its "
                "name. Expanded in reactive hyperplasia and replaced in splenic lymphomas.",
    "gc": "Germinal centre: pale proliferating B cells (centroblasts and centrocytes) on follicular dendritic cells - "
          "the follicle is responding to blood-borne antigen and making high-affinity, class-switched antibody. "
          "This is where antibody to polysaccharide capsules is made.",
    "marginal_sinus": "Marginal sinus: small vascular spaces at the edge of the white pulp into which some side "
                      "branches of the central artery open; blood percolating from here brings circulating antigen "
                      "to the white pulp.",
    "mz": "Marginal zone: the border between white and red pulp, where blood first reaches the pulp. It holds "
          "marginal-zone B cells that respond fast, T-independently, to polysaccharide antigens (IgM against "
          "encapsulated bacteria), and macrophages that clear bacteria straight from the blood. Its loss after "
          "splenectomy is the reason for overwhelming post-splenectomy infection; marginal zone lymphoma arises "
          "here.",
    "penicillar": "Penicillar arterioles: the brush of short, straight arterioles into which the central artery "
                  "divides after leaving the white pulp. Each continues as a sheathed capillary and then a terminal "
                  "arterial capillary.",
    "sheath": "Sheathed capillaries: capillaries wrapped in a sheath (ellipsoid, of Schweigger-Seidel) of "
              "macrophages and reticular cells that filter the blood before it is released into the cords.",
    "cords": "Splenic cords (of Billroth): the spongy reticular tissue between the sinusoids, full of red cells, "
             "macrophages, plasma cells and platelets. Most arterial capillaries open directly into the cords "
             "('open circulation'), so blood must squeeze back into the sinusoids through the slits in their walls. "
             "Stiff or coated cells cannot - spherocytes, sickle cells and antibody-coated cells are held back and "
             "eaten by cord macrophages (extravascular haemolysis), and the macrophages 'pit' inclusions such as "
             "Howell-Jolly bodies out of passing red cells.",
    "sinusoids": "Venous sinusoids (sinuses): wide, anastomosing vessels lined by long rod-shaped stave cells aligned "
                 "along the vessel with slits between them. Red cells (about 7 µm) must deform to pass through 2-3 µm "
                 "slits - the spleen's test of red-cell flexibility. Blood then drains to the pulp veins.",
    "ring": "Ring fibres: the discontinuous basement membrane of the sinusoids, wound around the stave cells like the "
            "hoops of a barrel; silver stains show them as black rings.",
    "pulp_vein": "Pulp vein: collects blood from the venous sinusoids and carries it to a trabecular vein.",
}

SX0, SX1, SZ0, SZ1 = -1.0, 1.0, -0.6, 0.6


def _ring_fibres(path, radius, spacing, seed=0):
    """Hoops of basement membrane around a sinusoid, wound like the hoops of a barrel."""
    rng = np.random.default_rng(seed)
    m = Mesh()
    sw = Sweep(path, 16, max(8, len(path)))
    s_vals = np.arange(spacing * 0.5, sw.length, spacing) / max(sw.length, 1e-6)
    for s in s_vals:
        th = np.linspace(0, 2 * math.pi, 15)
        ring = sw.curve(np.full(len(th), s) + rng.uniform(-0.004, 0.004), th, radius)
        m.extend(tube(ring, 0.0032, 4, caps=False))
    return m



def _lowest(f):
    """Lowest value of a height function over the block (the underside of the capsule)."""
    X, Z = np.meshgrid(np.linspace(SX0, SX1, 21), np.linspace(SZ0, SZ1, 13), indexing="ij")
    return float(np.min(f(X, Z)))


def _sinusoid_walks(grid, avoid, y_hi, rng, total=36.0, step=0.02):
    """Centrelines of the venous sinusoids: smooth random walks through the red pulp that stop short of the white
    pulp, trabeculae and large vessels. A third start in each cut plane and a third on the outer faces, heading
    across them, so every face of the block shows sinusoids in section, as a slide of red pulp does."""
    lo = np.array([SX0, 0.05, SZ0])
    hi = np.array([SX1, y_hi, SZ1])

    def clear(q):
        return bool(np.all(q >= lo - 1e-6) and np.all(q <= hi + 1e-6)) and _sample(grid, avoid, q[None])[0] > 0.04

    def walk(p, d, length):
        pts = []
        for _ in range(int(length / step)):
            d = d + rng.normal(scale=0.28, size=3) * np.array([1.0, 0.6, 1.0])
            d /= np.linalg.norm(d)
            q = p + d * step
            if not clear(q):
                break
            pts.append(q)
            p = q
        return pts

    paths, starts, used = [], [], 0.0
    for k in range(600):
        kind = k % 3
        y = rng.uniform(0.07, y_hi - 0.02)
        if kind == 0:                                    # crossing the z = 0 cut
            p0, d0 = np.array([rng.uniform(-0.97, -0.02), y, 0.0]), np.array([0.0, 0.0, 1.0])
        elif kind == 1:                                  # crossing the x = 0 cut
            p0, d0 = np.array([0.0, y, rng.uniform(0.02, 0.58)]), np.array([1.0, 0.0, 0.0])
        else:                                            # entering from an outer face
            face = rng.integers(4)
            if face < 2:
                p0 = np.array([(SX0, SX1)[face], y, rng.uniform(SZ0, SZ1)])
                d0 = np.array([1.0 if face == 0 else -1.0, 0.0, 0.0])
            else:
                p0 = np.array([rng.uniform(SX0, SX1), y, (SZ0, SZ1)[face - 2]])
                d0 = np.array([0.0, 0.0, 1.0 if face == 2 else -1.0])
        d0 = d0 + rng.normal(scale=0.35 if kind < 2 else 0.15, size=3) * np.array([1.0, 0.5, 1.0])
        d0 /= np.linalg.norm(d0)
        if not clear(p0) or (starts and cKDTree(starts).query(p0)[0] < 0.09):
            continue
        back = walk(p0, -d0, rng.uniform(0.15, 0.4)) if kind < 2 else []
        fwd = walk(p0, d0, rng.uniform(0.3, 0.7))
        pts = back[::-1] + [p0] + fwd
        if len(pts) < 8:
            continue
        paths.append(np.array(pts))
        starts.append(p0)
        used += step * (len(pts) - 1)
        if used > total:
            break
    return paths

def build_spleen():
    rng = np.random.default_rng(47)
    parts = []
    y_top = lambda X, Z: 0.965 + 0.006 * np.sin(np.asarray(X) * 3.1 + 0.4) + 0.004 * np.cos(np.asarray(Z) * 4.0)
    y_cap = lambda X, Z: y_top(X, Z) - 0.008
    y_pulp = lambda X, Z: y_cap(X, Z) - 0.06
    parts.append(hlayer("Mesothelium (visceral peritoneum)", "Capsule & trabeculae", "#cfa696", y_cap, y_top,
                        SPLEEN["mesothelium"], "serosa", (SX0, SX1), (SZ0, SZ1), rank=3, res=120,
                        detail=(0.06, 140.0, 0.6, 0)))
    parts.append(hlayer("Capsule", "Capsule & trabeculae", "#dfbf9a", y_pulp, y_cap, SPLEEN["capsule"], "ligament",
                        (SX0, SX1), (SZ0, SZ1), rank=2, res=120, detail=(0.12, 55.0, 0.15, 1)))

    vox = 0.0095
    lo, hi = np.array([SX0, 0.0, SZ0]), np.array([SX1, 0.93, SZ1])
    V = lambda: Volume(lo, hi, vox)
    grid = V()
    x, y, z = grid.axes()
    yp = y_pulp(x, z).astype(np.float32)
    inner = np.maximum(np.maximum(y - yp, 0.012 - y), np.maximum(np.maximum(SX0 + 0.004 - x, x - SX1 + 0.004),
                                                                 np.maximum(SZ0 + 0.004 - z, z - SZ1 + 0.004)))
    inner = np.broadcast_to(inner, grid.shape).astype(np.float32)

    # ------------------------------------------------------------------ trabeculae with their artery and vein
    t1 = smooth_path(np.array([(-0.80, 0.97, 0.0), (-0.77, 0.70, 0.01), (-0.73, 0.42, 0.0), (-0.70, 0.18, -0.02)]), 40)
    t2 = smooth_path(np.array([(0.62, 0.97, -0.10), (0.58, 0.70, -0.05), (0.52, 0.45, 0.0), (0.50, 0.25, 0.04)]), 40)
    t3 = smooth_path(np.array([(0.02, 0.97, 0.50), (0.0, 0.84, 0.47), (-0.03, 0.72, 0.45)]), 20)
    t4 = smooth_path(np.array([(-0.2, 0.97, -0.45), (-0.25, 0.8, -0.42), (-0.3, 0.66, -0.4)]), 20)
    tra = V()
    for path, r0, r1 in ((t1, 0.10, 0.08), (t2, 0.075, 0.062), (t3, 0.05, 0.03), (t4, 0.05, 0.03)):
        tra.tube(path, np.linspace(r0, r1, len(path)), "smooth", 0.03)
    tra.displace(0.004, 14.0, 2, seed=3)
    tr_art_paths = [t1[3:] + np.array([0.045, 0.0, 0.0]), None]
    art_in_t2 = smooth_path(np.array([(0.64, 0.92, -0.12), (0.60, 0.72, -0.07), (0.55, 0.53, -0.02),
                                      (0.45, 0.46, 0.0)]), 40)
    tr_art_paths[1] = art_in_t2
    tr_vein_paths = [t1[3:] + np.array([-0.03, 0.0, 0.0]), t2[3:] + np.array([-0.02, 0.0, 0.02])]

    # ------------------------------------------------------------------ white pulp: PALS, follicles, germinal centres
    ca = smooth_path(np.array([(0.45, 0.46, 0.0), (0.2, 0.45, 0.0), (-0.1, 0.44, 0.0), (-0.36, 0.43, 0.0)]), 60)
    cb = smooth_path(np.array([(0.22, 0.45, 0.0), (0.12, 0.43, 0.18), (0.0, 0.42, 0.34), (-0.25, 0.41, 0.45),
                               (-0.5, 0.40, 0.5)]), 60)
    pals = V()
    pals.tube(ca, np.interp(np.linspace(0, 1, len(ca)), [0, 0.1, 0.85, 1], [0.05, 0.10, 0.10, 0.06]), "smooth", 0.03)
    pals.tube(cb, np.interp(np.linspace(0, 1, len(cb)), [0, 0.15, 1], [0.05, 0.085, 0.07]), "smooth", 0.04)
    fol = V()
    fol_c = [(np.array([-0.16, 0.58, 0.0]), 0.165), (np.array([0.02, 0.54, 0.36]), 0.14)]
    gcs = V()
    for c, r in fol_c:
        fol.add(ellipsoid(c, (r * 1.1, r * 0.95, r)), "smooth", 0.04)
        gcs.add(ellipsoid(c + np.array([0.0, 0.03, 0.0]), (r * 0.62, r * 0.55, r * 0.58)))
    for v in (pals, fol):
        v.displace(0.005, 12.0, 2, seed=5)
    wp = np.minimum(pals.d, fol.d)
    wp = smin(pals.d, fol.d, 0.04)
    wp = np.maximum(wp, inner)
    # nested shells leave a hair's gap between them: a solid cut by the viewer is capped at its own back faces,
    # so any overlap would let the outer shell's inner wall hide the inner solid's cap
    msin_d = np.maximum(wp - 0.024, -(wp - 0.002))
    mz_d = np.maximum(wp - 0.085, -(wp - 0.026))
    np.maximum(mz_d, inner, out=mz_d)
    np.maximum(msin_d, inner, out=msin_d)

    # ------------------------------------------------------------------ arteries of the white pulp
    art_mesh, pen_mesh, sheath_mesh = Mesh(), Mesh(), Mesh()
    carve = V()
    art_mesh.extend(tube(ca, 0.019, 16))
    art_mesh.extend(tube(cb, 0.015, 14))
    carve.tube(ca, 0.024)
    carve.tube(cb, 0.02)
    for k, (path, (c, r)) in enumerate(((ca, fol_c[0]), (cb, fol_c[1]))):
        # side branches into the follicle and on to the marginal zone
        i0 = int(np.argmin(np.linalg.norm(path - c, axis=1)))
        for j in range(5):
            a = path[int(np.clip(i0 + rng.integers(-8, 9), 0, len(path) - 1))]
            dvec = rng.normal(size=3)
            dvec[1] = abs(dvec[1]) + 0.6
            dvec /= np.linalg.norm(dvec)
            end = c + dvec * (r + 0.05)
            bp = smooth_path(np.array([a, (a + end) / 2 + rng.normal(scale=0.02, size=3), end]), 16)
            art_mesh.extend(tube(bp, np.linspace(0.008, 0.005, len(bp)), 8))
    e = ca[-1]
    for j, off in enumerate(((-0.26, -0.16, 0.0), (-0.22, 0.06, 0.07), (-0.2, -0.25, -0.06), (-0.27, -0.04, -0.13),
                             (-0.17, 0.12, -0.04), (-0.24, -0.2, 0.12))):
        end = e + np.array(off)
        mid = e + np.array(off) * 0.45 + rng.normal(scale=0.015, size=3)
        pp = smooth_path(np.array([e, mid, end]), 24)
        pen_mesh.extend(tube(pp, np.linspace(0.010, 0.006, len(pp)), 10))
        carve.tube(pp, 0.012)
        dvec = (end - mid) / np.linalg.norm(end - mid)
        sc = end + dvec * 0.03
        sheath_mesh.extend(ellipsoid_mesh(sc, (0.018, 0.036, 0.018), 10, rotation=frame_from_normal(dvec)))
        carve.add(ellipsoid(sc, (0.02, 0.038, 0.02), frame_from_normal(dvec)))
        cap_path = np.array([end, sc + dvec * 0.03, sc + dvec * 0.07 + rng.normal(scale=0.01, size=3)])
        pen_mesh.extend(tube(smooth_path(cap_path, 10), 0.0042, 7))
    pals_d = np.maximum(pals.d, inner)
    pals_d = np.maximum(pals_d, -(fol.d - 0.002))
    np.maximum(pals_d, -(carve.d - 0.002), out=pals_d)
    fol_d = np.maximum(np.maximum(fol.d, inner), -(gcs.d - 0.002))
    np.maximum(fol_d, -(carve.d - 0.002), out=fol_d)
    parts.append(sdf_part(grid.copy(pals_d), "Periarteriolar lymphoid sheath (PALS)", "White pulp", "#78ab98",
                          SPLEEN["pals"], "lymph", smooth=0.8, rank=0.5, detail=(0.07, 180.0, 0.95, 0)))
    parts.append(sdf_part(grid.copy(fol_d), "Splenic follicles & mantle zone", "White pulp", "#3f4799",
                          SPLEEN["follicle"], "lymph", smooth=0.8, rank=0.6, detail=(0.06, 220.0, 0.98, 0)))
    parts.append(sdf_part(gcs, "Germinal centres", "White pulp", "#d8d0f0", SPLEEN["gc"], "lymph", smooth=0.8,
                          rank=0.7, detail=(0.07, 120.0, 0.7, 0)))
    parts.append(sdf_part(grid.copy(msin_d), "Marginal sinus", "Marginal zone", "#e7c9d6", SPLEEN["marginal_sinus"],
                          "csf", smooth=0.6, rank=0.4, detail=(0.04, 40.0, 0.2, 0)))
    parts.append(sdf_part(grid.copy(mz_d), "Marginal zone", "Marginal zone", "#c69ac4", SPLEEN["mz"], "lymph",
                          smooth=0.8, rank=0.3, detail=(0.08, 160.0, 0.85, 0)))

    # ------------------------------------------------------------------ venous sinusoids
    wpz = wp - 0.085                                   # distance to the outer edge of the marginal zone
    avoid = np.minimum(np.minimum(wpz, tra.d), carve.d)
    y_hi = _lowest(y_pulp) - 0.05
    sin_paths = _sinusoid_walks(grid, avoid, y_hi, rng)
    sin_mesh, ring_mesh = Mesh(), Mesh()
    sinv = V()
    for i, p in enumerate(sin_paths):
        _, m = tubule(p, 0.024, 0.033, seed=200 + i, cell=0.013, amp=0.0045, aspect=4.5, lobe=(3, 0.05),
                      calibre=0.08, n_theta=24, n_s=max(20, min(70, len(p))))
        sin_mesh.extend(m)
        ring_mesh.extend(_ring_fibres(p, 0.0355, 0.055, seed=300 + i))
        sinv.tube(p, 0.040)                              # room for the ring fibres
    parts.append(mesh_part(sin_mesh, "Venous sinusoids (stave cells)", "Red pulp", "#e3a3ad", SPLEEN["sinusoids"],
                           "vein", rank=-0.5, detail=(0.06, 120.0, 0.6, 0)))
    parts.append(mesh_part(ring_mesh, "Ring fibres", "Red pulp", "#5e4535", SPLEEN["ring"], "fascia", rank=-0.4,
                           detail=(0.04, 0.0, 0.0, 0)))

    # ------------------------------------------------------------------ trabecular vessels and the pulp vein
    tv_mesh, ta_mesh, pv_mesh = Mesh(), Mesh(), Mesh()
    for path in tr_vein_paths:
        tv_mesh.extend(tubule(path, 0.036, 0.045, seed=61, cell=0.03, amp=0.003, lobe=(4, 0.05), calibre=0.04,
                              n_theta=40, n_s=40)[1])
        carve.tube(path, 0.047)
    for path in tr_art_paths:
        ta_mesh.extend(tubule(path, 0.010, 0.024, seed=62, cell=0.02, amp=0.003, lobe=(6, 0.08), calibre=0.03,
                              n_theta=32, n_s=40)[1])
        carve.tube(path, 0.026)
    pv = smooth_path(np.array([(-0.42, 0.2, 0.05), (-0.55, 0.28, 0.03), (-0.72, 0.36, 0.0)]), 30)
    pv_mesh.extend(tubule(pv, 0.026, 0.033, seed=63, cell=0.02, amp=0.003, n_theta=30, n_s=30)[1])
    carve.tube(pv, 0.035)
    tra_d = np.maximum(tra.d, np.maximum(0.012 - y, np.maximum(np.maximum(SX0 + 0.004 - x, x - SX1 + 0.004),
                                                               np.maximum(SZ0 + 0.004 - z, z - SZ1 + 0.004))))
    tra_d = np.maximum(tra_d, y - y_top(x, z) + 0.03)
    np.maximum(tra_d, -(carve.d - 0.002), out=tra_d)
    parts.append(sdf_part(grid.copy(tra_d.astype(np.float32)), "Trabeculae", "Capsule & trabeculae", "#d6ae88",
                          SPLEEN["trabeculae"], "ligament", smooth=0.8, rank=1.5, detail=(0.12, 55.0, 0.15, 1)))
    parts.append(mesh_part(ta_mesh, "Trabecular artery", "Vessels", "#cf3a31", SPLEEN["tr_artery"], "artery", rank=1))
    parts.append(mesh_part(tv_mesh, "Trabecular vein", "Vessels", "#3d5bc2", SPLEEN["tr_vein"], "vein", rank=1))
    parts.append(mesh_part(art_mesh, "Central artery & follicular branches", "Vessels", "#d23b33", SPLEEN["central"],
                           "artery", rank=0.8))
    parts.append(mesh_part(pen_mesh, "Penicillar arterioles", "Vessels", "#e0493f", SPLEEN["penicillar"], "artery",
                           rank=0))
    parts.append(mesh_part(sheath_mesh, "Sheathed capillaries (Schweigger-Seidel sheaths)", "Vessels", "#e7b27c",
                           SPLEEN["sheath"], "organ", rank=0, detail=(0.08, 120.0, 0.8, 0)))
    parts.append(mesh_part(pv_mesh, "Pulp vein", "Vessels", "#4a66c9", SPLEEN["pulp_vein"], "vein", rank=-0.3))

    # ------------------------------------------------------------------ splenic cords: everything that is left
    cords = inner.copy()
    for other in (wp - 0.085, tra.d, sinv.d, carve.d):
        np.maximum(cords, -(other - 0.002), out=cords)
    cords_v = grid.copy(cords)
    cords_v.d -= cell_lattice(x, y, z, 0.03, 0.0025, seed=9).astype(np.float32)
    parts.append(sdf_part(cords_v, "Splenic cords (of Billroth)", "Red pulp", "#a3303c", SPLEEN["cords"], "organ",
                          smooth=0.8, bulk=True, rank=-1, step=1, detail=(0.10, 170.0, 0.6, 0)))
    return settle(parts, seed=712, amp_xz=0.025, amp_y=0.04, freq=1.4, grain=0.004)
