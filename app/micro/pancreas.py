"""Exocrine and endocrine pancreas, cell by cell, with a secretion cycle.

The block is packed, not piled: acinar centres are Poisson-disk points and every acinus owns its Voronoi region
(shrunk by a stromal cleft) cut back by tangent planes wherever a septum, a duct, a vessel or an islet passes. Inside
its region each acinus is split into pyramidal cells by planes through its centre (the spherical Voronoi cones of a
set of directions), truncated at a small central lumen. Every cell is an exact convex polytope, rounded by erosion
and dilation (a Minkowski sum with a sphere), so cells never overlap one another, their neighbours or the stroma -
the cut-away's cap pass then draws clean sections through them. Each cell is split into its basophilic base (with a
round basal nucleus) and its eosinophilic apex, which holds the zymogen granules. One cone of each acinus is left
for its intercalated duct, which starts at pale centroacinar cells in the lumen and runs straight to the
intralobular duct (or to a neighbour's intercalated duct); the other acini are cut back around it.

Islets of Langerhans are packed Voronoi cells (beta core, alpha mantle, scattered delta cells) threaded by
fenestrated capillary loops. Capillaries also wrap the acini, running along the triple junctions between them.

The animation (pancreas_animation) is one 4 s secretion cycle: granules drift from the Golgi region to the apex and
fuse with the apical membrane (exocytosis), enzyme-rich fluid runs down the intercalated and intralobular ducts, and
the beta cells pulse as they release insulin, which is carried off in the islet capillaries.
"""
import math

import numpy as np
from scipy.optimize import linprog
from scipy.spatial import ConvexHull, HalfspaceIntersection, SphericalVoronoi, Voronoi, cKDTree

from .anim import MODE_FLOW, Animation, Track, window
from .base import Part
from .cells import poisson_disk
from .geometry import Mesh, ellipsoid as ellipsoid_mesh, smooth_path, tube
from .kit import Volume, hlayer, mesh_part, noise2, sdf_part, tube_shell
from .organic import settle, tubule
from .sdf import fbm3
from .tissues import PANC, _clip_box, _clip_plane, _fib_sphere, _merge, _septum_lines, _square_ends, _voronoi_cells

X0, X1, Z0, Z1, Y_BOT = -1.0, 1.0, -0.6, 0.6, -0.5
EPS = 0.004

COL = {
    "stroma": "#f1ddd3", "septa": "#e9c3b4", "basal": "#a9606a", "apical": "#efb08f", "granules": "#dc6a45",
    "nuclei": "#33406e", "centro": "#f2ece0", "icd": "#e9dcc3", "intra": "#d8bf95", "inter": "#caa36a",
    "beta": "#f3e1bd", "alpha": "#e9a78e", "delta": "#8fc3b8", "islet_nuc": "#4a5680", "icap": "#c9403a",
    "cap": "#c7514a", "artery": "#c8322b", "vein": "#4f5fb0", "flow": "#f7b45a", "insulin": "#fff0a0",
}

DESC = dict(PANC)
DESC.update({
    "granules": "Zymogen granules: membrane-bound packets of inactive digestive enzymes, ~1 µm across, stored in the "
                "apex of the acinar cell. Stimulated by CCK and acetylcholine (vagus), they move to the apical "
                "membrane and fuse with it (exocytosis), emptying into the acinar lumen. Playing the animation shows "
                "them migrating and fusing.",
    "flow": "Pancreatic juice (animation): the enzyme-rich secretion of the acini, diluted and alkalinised by the "
            "bicarbonate and water that centroacinar and duct cells add (secretin, CFTR), flowing from the acinar "
            "lumen down the intercalated ducts to the intralobular ducts. About 1.5 L a day reaches the duodenum. "
            "Only visible while the animation plays.",
    "insulin": "Insulin release (animation): beta cells release insulin (with C-peptide and amylin) into the "
               "fenestrated islet capillaries when blood glucose rises; the blood carries it first to the acini "
               "around the islet and then, through the portal vein, to the liver. Only visible while the animation "
               "plays.",
    "caps": "Intralobular capillaries: a dense network wrapping each acinus in the scant connective tissue between "
            "acini, supplying the heavy protein synthesis of the acinar cells. Much of this blood has already "
            "passed through an islet (insulo-acinar portal system).",
    "islet_nuc": "Islet cell nuclei: round, central and paler than acinar nuclei; the pale, finely granular "
                 "cytoplasm of the endocrine cells is why the islets stand out as pale islands in H&E.",
})


# ================================================================================================ polytopes
def _cheby(A, b):
    """Centre and radius of the largest ball inside {x: A x + b <= 0}."""
    nrm = np.linalg.norm(A, axis=1)
    res = linprog(np.r_[0, 0, 0, -1.0], A_ub=np.c_[A, nrm], b_ub=-b, bounds=[(None, None)] * 3 + [(0, None)],
                  method="highs")
    if not res.success:
        return None, 0.0
    return res.x[:3], res.x[3]


_DIRS = _fib_sphere(30, 1.0)


def _rounded(A, b, r):
    """Convex polytope {A x + b <= 0} rounded by r (eroded then dilated): (points of the hull) or None."""
    A = np.asarray(A, float)
    b = np.asarray(b, float) + r            # rows of A are unit normals
    c, rad = _cheby(A, b)
    if c is None or rad < 0.002:
        return None
    try:
        hs = HalfspaceIntersection(np.c_[A, b], c)
    except Exception:
        return None
    v = hs.intersections
    v = v[np.all(np.isfinite(v), axis=1)]
    if len(v) < 4:
        return None
    return (v[:, None, :] + r * _DIRS[None]).reshape(-1, 3)


def _hull(points):
    hull = ConvexHull(points)
    pos = points[hull.vertices]
    remap = np.full(len(points), -1)
    remap[hull.vertices] = np.arange(len(hull.vertices))
    idx = remap[hull.simplices]
    c = pos.mean(axis=0)
    tri = pos[idx]
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    flip = np.einsum("ij,ij->i", nrm, tri.mean(axis=1) - c) < 0
    idx[flip] = idx[flip][:, ::-1]
    return pos, idx


def _basis(s):
    s = s / np.linalg.norm(s)
    a = np.array([0.0, 1.0, 0.0]) if abs(s[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
    e1 = np.cross(s, a)
    e1 /= np.linalg.norm(e1)
    return np.stack([s, e1, np.cross(s, e1)])        # rows: s -> x axis


def _split(pos, idx, c, s, h):
    """Split a convex mesh by the plane (x - c).s = h: (below, above), each capped."""
    Rm = _basis(s)
    q = (pos - c) @ Rm.T
    lo = _clip_plane(q, idx, 0, h, True)
    hi = _clip_plane(q, idx, 0, h, False)
    back = lambda r: None if r is None else ((r[0] @ Rm) + c, r[1])      # noqa: E731
    return back(lo), back(hi)


def _seg_dist(p, a, b):
    ab = b - a
    t = np.clip(((p - a) @ ab) / max(ab @ ab, 1e-12), 0.0, 1.0)
    q = a + t * ab
    return np.linalg.norm(p - q), q


def _poly_nearest(p, pts):
    """Nearest point on a polyline and the distance to it."""
    d = np.linalg.norm(pts - p, axis=1)
    k = int(np.argmin(d))
    best = (d[k], pts[k])
    for j in (k - 1, k):
        if 0 <= j < len(pts) - 1:
            dd, q = _seg_dist(p, pts[j], pts[j + 1])
            if dd < best[0]:
                best = (dd, q)
    return best


# ================================================================================================ islet
def _islet(c, radii, rng, seed):
    """Islet: packed Voronoi cells threaded by capillary loops; returns cell meshes by kind, nuclei, capillary mesh
    and the capillary centre lines."""
    c = np.asarray(c, float)
    radii = np.asarray(radii, float)
    sp = 0.029
    pts = poisson_disk(-radii, radii, sp, seed=seed)
    q = np.linalg.norm(pts / radii, axis=1)
    pts = pts[q < 1.0 - 0.35 * sp / radii.min()]
    capm = Mesh()
    cap_pts = []
    dirs = _fib_sphere(8, 1.0, seed=seed + 5, jitter=0.3)
    for k in range(8):
        a = dirs[k]
        b = -a + rng.normal(scale=0.5, size=3)
        b /= np.linalg.norm(b)
        mid = rng.normal(scale=0.35, size=3)
        ta = np.cross(a, rng.normal(size=3))
        tb = np.cross(b, rng.normal(size=3))
        ta /= np.linalg.norm(ta)
        tb /= np.linalg.norm(tb)
        ctrl = np.array([a * 1.12 + ta * 0.3, a * 0.98 + ta * 0.1, a * 0.6 + mid * 0.3, mid * 0.5,
                         b * 0.6 + mid * 0.3, b * 0.98 + tb * 0.1, b * 1.12 + tb * 0.3]) * radii
        path = smooth_path(ctrl, 44)
        capm.extend(tube(path + c, 0.0085, 8))
        cap_pts.append(path)
    line = np.vstack(cap_pts)
    dline, _ = cKDTree(line).query(pts)
    pts = pts[dline > 0.022]
    ghosts = [_fib_sphere(int(4 * math.pi * (radii.mean() + f * sp) ** 2 / sp ** 2 * 1.1), 1.0, seed=seed + int(f * 10))
              * (radii + f * sp) for f in (0.55, 1.6)]
    ghosts.append(np.vstack([smooth_path(p, max(8, int(len(p) * 1.5))) for p in cap_pts]))
    cells = _voronoi_cells(pts, np.vstack(ghosts), shrink=0.86, round_amt=0.3)
    qn = np.linalg.norm(pts / radii, axis=1)
    kinds = {"beta": Mesh(), "alpha": Mesh(), "delta": Mesh()}
    nuc = Mesh()
    for p, qq, cell in zip(pts, qn, cells):
        if cell is None:
            continue
        r = rng.random()
        kind = "delta" if (qq > 0.45 and r < 0.12) or r < 0.02 else ("alpha" if qq > 0.70 else "beta")
        kinds[kind].add(cell[0] + c, cell[1])
        rn = 0.0075 * rng.uniform(0.9, 1.1)
        nuc.extend(ellipsoid_mesh(cell[0].mean(axis=0) + c, (rn, rn, rn), 5))
    return kinds, nuc, capm, [p + c for p in cap_pts]


# ================================================================================================ build
def build_pancreas(fast=False):
    rng = np.random.default_rng(83)
    parts = []
    lines, lobule, x_s1, z_s2 = _septum_lines()
    sep_pts = np.vstack([l for l, _ in lines])
    sep_half = np.concatenate([np.full(len(l), h) for l, h in lines])
    sep_tree = cKDTree(sep_pts)
    lo_clip, hi_clip = [X0, Y_BOT, Z0], [X1, None, Z1]

    def d_sep(x, z):
        q = np.stack(np.broadcast_arrays(np.asarray(x, float), np.asarray(z, float)), -1)
        dd, j = sep_tree.query(q.reshape(-1, 2))
        return (dd - sep_half[j]).reshape(q.shape[:-1])

    # the stroma fills the block up to just below the tops of the uppermost acini, which bulge out of it like
    # grapes; over the septa it dips into a groove
    groove = lambda X, Z: -0.05 * np.exp(-(np.maximum(d_sep(X, Z), 0.0) / 0.07) ** 2)    # noqa: E731
    Y_TOP = 0.20
    Y_STROMA = 0.235
    y_str = lambda X, Z: Y_STROMA + groove(X, Z) + noise2(0.008, 3.0, seed=13)(X, Z)       # noqa: E731
    parts.append(hlayer("Intralobular connective tissue", "Lobules", COL["stroma"], Y_BOT, y_str, DESC["stroma"],
                        "fascia", (X0, X1), (Z0, Z1), res=140, bulk=True, rank=-1, label=False,
                        detail=(0.08, 60.0, 0.15, 0)))

    # ------------------------------------------------------------------ septa
    vol = Volume((X0 - 0.02, Y_BOT - 0.02, Z0 - 0.02), (X1 + 0.02, 0.34, Z1 + 0.02), 0.011 if fast else 0.009)
    x, y, z = vol.axes()
    XX, ZZ = np.meshgrid(x[:, 0, 0], z[0, 0, :], indexing="ij")
    ds = d_sep(XX, ZZ) + 0.006 * fbm3(XX * 9.0, 0.3, ZZ * 9.0, 1.0, 2, 3)
    top = y_str(XX, ZZ) + 0.012
    vol.d = np.maximum(ds[:, None, :], y - top[:, None, :]).astype(np.float32)
    vol.intersect_box((X0 - EPS * 0.7, Y_BOT - EPS * 0.7, Z0 - EPS * 0.7), (X1 + EPS * 0.7, 1.0, Z1 + EPS * 0.7))
    parts.append(sdf_part(vol, "Interlobular septa", "Septa & ducts", COL["septa"], DESC["septa"], "fascia",
                          smooth=0.9, rank=-0.5, detail=(0.12, 50.0, 0.15, 0)))

    # ------------------------------------------------------------------ interlobular ducts and vessels
    zz = np.linspace(Z0 - EPS, Z1 + EPS, 70)
    inter = _square_ends(np.stack([x_s1(zz), 0.10 + 0.02 * np.sin(zz * 4.0), zz], -1), 2)
    xx = np.linspace(X0 - EPS, x_s1(-0.25) - 0.02, 60)
    inter2 = _square_ends(np.stack([xx, 0.08 + 0.015 * np.sin(xx * 5.0), z_s2(xx)], -1), 0)
    _, m_inter = tubule(inter, 0.033, 0.052, seed=5, cell=0.030, amp=0.004, aspect=1.2, lobe=(7, 0.06),
                        calibre=0.05, n_theta=40, n_s=70)
    _, m_inter2 = tubule(inter2, 0.018, 0.031, seed=6, cell=0.026, amp=0.003, aspect=1.2, lobe=(6, 0.05),
                         calibre=0.05, n_theta=28, n_s=60)
    parts.append(mesh_part(_merge(Mesh().extend(m_inter).extend(m_inter2)), "Interlobular ducts", "Septa & ducts",
                           COL["inter"], DESC["interlobular"], "gland", rank=1, detail=(0.08, 150.0, 0.9, 0)))
    art = _square_ends(np.stack([x_s1(zz) - 0.036, -0.01 + 0.01 * np.sin(zz * 3), zz], -1), 2)
    ven = _square_ends(np.stack([x_s1(zz) + 0.030, -0.02 + 0.01 * np.sin(zz * 2.6 + 1), zz], -1), 2)
    parts.append(mesh_part(tube_shell(art, 0.021, 0.011, 20), "Interlobular artery", "Septa & ducts",
                           COL["artery"], DESC["artery"], "artery", rank=1, detail=(0.06, 110.0, 0.6, 3)))
    parts.append(mesh_part(tube_shell(ven, 0.027, 0.020, 20), "Interlobular vein", "Septa & ducts", COL["vein"],
                           DESC["vein"], "vein", rank=1))

    # ------------------------------------------------------------------ intralobular ducts
    def on_inter(zv):
        return np.array([x_s1(zv), 0.10 + 0.02 * np.sin(zv * 4.0), zv])

    def on_inter2(xv):
        return np.array([xv, 0.08 + 0.015 * np.sin(xv * 5.0), z_s2(xv)])

    trunks = [(0, on_inter2(-0.8), [(-0.78, 0.06, 0.05), (-0.74, -0.04, 0.4)]),
              (1, on_inter(0.3), [(0.05, 0.02, 0.30), (-0.3, -0.05, 0.36)]),
              (2, on_inter(-0.45), [(0.05, -0.05, -0.44), (-0.45, -0.15, -0.47)]),
              (3, on_inter(0.42), [(0.62, 0.0, 0.40), (0.95, -0.1, 0.38)]),
              (4, on_inter(-0.02), [(0.55, -0.12, -0.02), (0.92, -0.2, -0.05)])]
    R_INTRA = 0.016
    lob_ducts = {k: [] for k in range(5)}
    duct_paths = []                 # (path, radius) obstacles for the acini
    flow_paths = []                 # centre lines secretion flows along
    intra = Mesh()
    for lob, start, ctrl in trunks:
        path = smooth_path(np.vstack([start, ctrl]), 40)
        lob_ducts[lob].append(path)
        duct_paths.append((path, R_INTRA + 0.004))
        flow_paths.append(path[::-1])
        _, m = tubule(path, 0.007, R_INTRA, seed=40 + lob, cell=0.02, amp=0.002, lobe=(5, 0.05), calibre=0.05,
                      n_theta=22, n_s=40)
        intra.extend(m)
        for j in (14, 28):
            p0 = path[j]
            tng = path[j + 1] - path[j - 1]
            side = np.cross(tng, [0.0, 1.0, 0.0])
            side /= np.linalg.norm(side)
            sgn = 1 if (j + lob) % 2 else -1
            br = smooth_path(np.array([p0, p0 + side * sgn * 0.12 + np.array([0, rng.uniform(-0.1, 0.06), 0]),
                                       p0 + side * sgn * 0.24 + np.array([0, rng.uniform(-0.16, 0.06), 0])]), 20)
            br = np.clip(br, [X0 + 0.1, Y_BOT + 0.1, Z0 + 0.1], [X1 - 0.1, 0.1, Z1 - 0.1])
            lob_ducts[lob].append(br)
            duct_paths.append((br, 0.0125))
            flow_paths.append(br[::-1])
            _, m = tubule(br, 0.005, 0.0115, seed=60 + lob * 3 + j, cell=0.018, amp=0.0015, lobe=(5, 0.05),
                          calibre=0.05, n_theta=18, n_s=20)
            intra.extend(m)
    parts.append(mesh_part(_merge(_clip_box(intra, lo_clip, hi_clip, EPS)), "Intralobular ducts", "Septa & ducts",
                           COL["intra"], DESC["intralobular"], "gland", rank=0.8, alpha=0.55, detail=(0.08, 170.0, 0.9, 0)))
    duct_paths += [(inter, 0.056), (inter2, 0.034), (art, 0.024), (ven, 0.03)]

    # ------------------------------------------------------------------ islets
    islets = [((-0.36, -0.06, 0.0), (0.17, 0.15, 0.16), 91), ((0.62, 0.10, -0.30), (0.13, 0.12, 0.13), 92)]
    kinds = {"beta": Mesh(), "alpha": Mesh(), "delta": Mesh()}
    inuc, icaps, icap_lines = Mesh(), Mesh(), []
    for c, radii, sd in islets:
        k, nuc, capm, cl = _islet(c, radii, rng, sd)
        for name in kinds:
            kinds[name].extend(k[name])
        inuc.extend(nuc)
        icaps.extend(capm)
        icap_lines += cl

    # ------------------------------------------------------------------ acinar centres
    R = 0.104
    cand = poisson_disk(np.array([X0 - 0.06, Y_BOT - 0.06, Z0 - 0.06]), np.array([X1 + 0.06, Y_TOP + 0.03, Z1 + 0.06]),
                        0.158, seed=17)
    keep = []
    for p in cand:
        if d_sep(p[0], p[2]) < 0.05:
            continue
        if any(_poly_nearest(p, path)[0] < r + 0.045 for path, r in duct_paths):
            continue
        if any(np.linalg.norm((p - np.array(ic)) / (np.array(ir) + 0.015)) < 1.0 for ic, ir, _ in islets):
            continue
        keep.append(p)
    C = np.array(keep)
    # drainage: an acinus next to a duct drains straight into it; any other drains into the lumen of a Voronoi
    # neighbour that is nearer the ducts, so every intercalated duct runs only through the two acini it joins
    vor = Voronoi(C)
    nbrs = {i: [] for i in range(len(C))}
    for a_, b_ in vor.ridge_points:
        nbrs[a_].append(b_)
        nbrs[b_].append(a_)
    near = []
    for p in C:
        lob = lobule(p[0], p[2])
        near.append(min((_poly_nearest(p, path) for path in lob_ducts[lob]), key=lambda t: t[0]))
    order = np.argsort([n[0] for n in near])
    ctree = cKDTree(C)
    target_of, ports = {}, {i: [] for i in range(len(C))}
    connected = set()
    for i in order:
        p = C[i]
        dd, q = near[i]
        clear = True
        for j in ctree.query_ball_point((p + q) / 2, dd / 2 + 0.1):
            if j != i and _seg_dist(C[j], p, q)[0] < 0.075:
                clear = False
                break
        if clear or dd < 0.14:
            target_of[i] = q
        else:
            cands = [j for j in nbrs[i] if j in connected and lobule(C[j][0], C[j][2]) == lobule(p[0], p[2])
                     and np.linalg.norm(C[j] - p) < 0.26]
            if cands:
                j = min(cands, key=lambda j: np.linalg.norm(C[j] - p) + 0.5 * near[j][0])
                target_of[i] = C[j]
                ports[j].append((p - C[j]) / np.linalg.norm(p - C[j]))
            else:
                target_of[i] = q
        connected.add(i)
        ports[i].append((target_of[i] - p) / max(np.linalg.norm(target_of[i] - p), 1e-9))

    # ------------------------------------------------------------------ acinar polytopes
    clamp = _fib_sphere(40, 1.0, seed=3)
    GAP = 0.0065
    R_ICD = 0.0068
    base, apex, nuc, gran, cent, icd = Mesh(), Mesh(), Mesh(), Mesh(), Mesh(), Mesh()
    gran_meta = []                  # (phase, path) per granule
    acinus_info = []
    icd_lines = []

    def visible(p, pad):
        return (min(p[0] - X0, X1 - p[0], p[2] - Z0, Z1 - p[2], p[1] - Y_BOT) < pad or p[1] > Y_TOP - 0.1
                or (p[0] < 0.05 and abs(p[2]) < pad) or (p[2] > -0.05 and abs(p[0]) < pad))

    for i, c in enumerate(C):
        rows = []
        for j in nbrs[i]:
            q = C[j]
            n = q - c
            L = np.linalg.norm(n)
            n /= L
            rows.append((n, -(n @ ((c + q) / 2)) + GAP))
        for u in clamp:
            rows.append((u, -(u @ c) - R * 1.02))
        # tangent planes on everything the acinus must stay clear of
        for path, r in duct_paths:
            d, q = _poly_nearest(c, path)
            if d < R * 1.6 + r:
                n = (q - c) / max(d, 1e-9)
                rows.append((n, -(n @ (q - n * (r + GAP)))))
        dsp = float(d_sep(c[0], c[2]))
        if dsp < R * 1.6:
            e = 0.004
            g = np.array([float(d_sep(c[0] + e, c[2]) - d_sep(c[0] - e, c[2])), 0.0,
                          float(d_sep(c[0], c[2] + e) - d_sep(c[0], c[2] - e))])
            g = -g / max(np.linalg.norm(g), 1e-9)          # towards the septum
            rows.append((g, -(g @ (c + g * (dsp - GAP)))))
        for ic, ir, _ in islets:
            ic = np.asarray(ic)
            v = ic - c
            dist = np.linalg.norm(v)
            n = v / dist
            rad = 1.0 / np.linalg.norm(n / np.asarray(ir))        # the islet's radius in that direction
            if dist - rad < R * 1.6:
                rows.append((n, -(n @ (c + n * (dist - rad - GAP)))))
        A = np.array([r[0] for r in rows])
        bb = np.array([r[1] for r in rows])
        cc, rad = _cheby(A, bb)
        if cc is None or rad < 0.034:
            continue
        ex = ports[i][0]
        pts_dirs = np.array(ports[i])
        # directions of the cells: a cone for each intercalated duct, the others spread round the sphere
        n_cells = int(rng.integers(10, 13))
        dirs = _fib_sphere(n_cells + 2 + 2 * len(pts_dirs), 1.0, seed=int(rng.integers(1 << 30)), jitter=0.15)
        dirs = dirs[np.max(dirs @ pts_dirs.T, axis=1) < math.cos(0.55)]
        dirs = np.vstack([pts_dirs, dirs])
        r_lum = 0.026
        r_mid = 0.050
        show = visible(c, R + 0.06)
        for k, s in enumerate(dirs):
            if k < len(pts_dirs):
                continue
            cr = [(-s, (s @ c) + r_lum)]
            for j, t in enumerate(dirs):
                if j == k:
                    continue
                n = t - s
                n /= np.linalg.norm(n)
                cr.append((n, -(n @ c) + 0.0022))
            A2 = np.vstack([A, [r[0] for r in cr]])
            b2 = np.concatenate([bb, [r[1] for r in cr]])
            pts = _rounded(A2, b2, 0.011)
            if pts is None:
                continue
            pos, idx = _hull(pts)
            lo, hi = _split(pos, idx, c, s, r_mid)
            if hi is not None:
                base.add(*hi)
            if lo is not None:
                apex.add(*lo)
            if not show:
                continue
            # nucleus in the base, granules in the apex
            hmax = float(np.max((pos - c) @ s))
            hn = r_mid + 0.45 * (hmax - r_mid) + 0.004
            rn = min(0.0125, 0.32 * (hmax - r_mid))
            if hi is not None and rn > 0.005:
                nuc.extend(ellipsoid_mesh(c + s * hn, (rn, rn * 0.95, rn), 6))
            if lo is None:
                continue
            lpos = lo[0]
            for g in range(4):
                h = rng.uniform(r_lum + 0.007, r_mid - 0.006)
                sl = lpos[np.abs((lpos - c) @ s - h) < 0.004]
                if len(sl) < 3:
                    continue
                lat = sl.mean(axis=0)
                ctr = lat + (sl[rng.integers(len(sl))] - lat) * rng.uniform(0.0, 0.35)
                gr = rng.uniform(0.0052, 0.0064)
                gran.extend(ellipsoid_mesh(ctr, (gr, gr, gr), 5))
                a0 = c + s * (r_mid - 0.004) + (ctr - c - s * ((ctr - c) @ s))
                b0 = c + s * (r_lum - 0.002) + (ctr - c - s * ((ctr - c) @ s)) * 0.6
                phase = float(np.clip(((a0 - ctr) @ (a0 - b0)) / max((a0 - b0) @ (a0 - b0), 1e-9), 0.1, 0.85))
                gran_meta.append((phase, b0 - a0))
        # centroacinar cells in the lumen, and the intercalated duct leaving through the spare cone
        _, e1, e2 = _basis(ex)
        cent.extend(ellipsoid_mesh(c + ex * 0.006, (0.0095, 0.018, 0.016), 6, rotation=np.stack([ex, e1, e2], 1)))
        acinus_info.append((c, ex, show))
        b = target_of[i]
        icd_lines.append((c, b))
        icd.extend(tube(np.array([c + ex * 0.01, c + (b - c) * 0.5, b]), R_ICD, 8))

    # ------------------------------------------------------------------ capillaries around the acini
    caps = Mesh()
    avoid = np.vstack([np.vstack([p for p, _ in duct_paths])] + [np.vstack(smooth_path(np.array([a, b]), 8)) for a, b in icd_lines])
    avoid_tree = cKDTree(avoid)
    vor2 = Voronoi(np.array([a[0] for a in acinus_info]))
    seen = set()
    for ridge in vor2.ridge_vertices:
        if -1 in ridge:
            continue
        for k in range(len(ridge)):
            e = tuple(sorted((ridge[k], ridge[(k + 1) % len(ridge)])))
            if e in seen:
                continue
            seen.add(e)
            p, q = vor2.vertices[e[0]], vor2.vertices[e[1]]
            if rng.random() > 0.45:
                continue
            if np.linalg.norm(p - q) > 0.2 or np.linalg.norm(p - q) < 0.015:
                continue
            mid = (p + q) / 2
            if not (X0 + 0.01 < mid[0] < X1 - 0.01 and Z0 + 0.01 < mid[2] < Z1 - 0.01 and Y_BOT < mid[1] < Y_TOP + 0.06):
                continue
            if max(p[1], q[1]) > Y_TOP + 0.08 or d_sep(mid[0], mid[2]) < 0.02:
                continue
            seg = smooth_path(np.array([p, mid, q]), 6)
            if avoid_tree.query(seg)[0].min() < 0.03:
                continue
            if any(np.linalg.norm((seg - np.array(ic)) / (np.array(ir) + 0.02), axis=1).min() < 1.0
                   for ic, ir, _ in islets):
                continue
            caps.extend(tube(seg, 0.0052, 7))

    parts += [
        mesh_part(_merge(_clip_box(base, lo_clip, hi_clip, EPS)), "Acinar cells – basal (basophilic) cytoplasm",
                  "Acini", COL["basal"], DESC["basal"], "gland", rank=0.5, detail=(0.07, 180.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(apex, lo_clip, hi_clip, EPS * 1.3)), "Acinar cells – apical zymogen granules",
                  "Acini", COL["apical"], DESC["apical"], "gland", rank=0.5, label=True, detail=(0.10, 260.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(nuc, lo_clip, hi_clip, EPS * 1.8)), "Acinar cell nuclei", "Acini", COL["nuclei"],
                  DESC["nuclei"], "nucleus", rank=0.6, label=False, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(cent, lo_clip, hi_clip, EPS * 1.6)), "Centroacinar cells", "Acini", COL["centro"],
                  DESC["centroacinar"], "gland", rank=0.6, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(icd, lo_clip, hi_clip, EPS * 1.4)), "Intercalated ducts", "Septa & ducts",
                  COL["icd"], DESC["intercalated"], "gland", rank=0.7, alpha=0.55, detail=(0.06, 200.0, 0.9, 0)),
        mesh_part(_merge(_clip_box(caps, lo_clip, hi_clip, EPS * 1.2)), "Intralobular capillaries", "Lobules",
                  COL["cap"], DESC["caps"], "artery", rank=0.9, label=False, detail=(0.06, 120.0, 0.5, 0)),
        mesh_part(_merge(_clip_box(kinds["beta"], lo_clip, hi_clip, EPS)), "Beta cells (core)",
                  "Islets of Langerhans", COL["beta"], DESC["beta"], "gland", rank=1.5, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(kinds["alpha"], lo_clip, hi_clip, EPS)), "Alpha cells (mantle)",
                  "Islets of Langerhans", COL["alpha"], DESC["alpha"], "gland", rank=1.5, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(kinds["delta"], lo_clip, hi_clip, EPS)), "Delta cells",
                  "Islets of Langerhans", COL["delta"], DESC["delta"], "gland", rank=1.5, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(inuc, lo_clip, hi_clip, EPS * 1.8)), "Islet cell nuclei", "Islets of Langerhans",
                  COL["islet_nuc"], DESC["islet_nuc"], "nucleus", rank=1.6, label=False, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(icaps, lo_clip, hi_clip, EPS * 1.2)), "Islet capillaries (fenestrated)",
                  "Islets of Langerhans", COL["icap"], DESC["islet_caps"], "artery", rank=1.6,
                  detail=(0.06, 120.0, 0.5, 0)),
    ]
    # granules are kept whole (never clipped), so the moving ones never show a stale cap
    gk = Mesh()
    gm = []
    for (pos_, nrm_, idx_), meta in zip(gran.parts, gran_meta):
        if np.all((pos_ > [X0 + 0.005, Y_BOT + 0.005, Z0 + 0.005]).all(axis=1) & (pos_[:, [0, 2]] < [X1 - 0.005, Z1 - 0.005]).all(axis=1)):
            gk.parts.append((pos_, nrm_, idx_))
            gm.append(meta)
    gpart = mesh_part(gk, "Zymogen granules", "Acini", COL["granules"], DESC["granules"], "gland", rank=0.65,
                      label=False, detail=(0.04, 0.0, 0.0, 0))
    parts.append(gpart)

    # the finishing warp; a probe part carries the flow paths through it so the particles follow the ducts
    probe_pts = []
    lines_for_flow = [np.array([a, b]) for a, b in icd_lines] + flow_paths
    for l in lines_for_flow:
        probe_pts.append(l)
    gran_c = np.array([p[0].mean(axis=0) for p in gk.parts]) if gk.parts else np.zeros((0, 3))
    probe = Part("_probe", "_", "#000000", Mesh().add(np.vstack(probe_pts + [gran_c]).astype(np.float32),
                                                      np.zeros((0, 3), np.int64), np.zeros((sum(len(l) for l in probe_pts) + len(gran_c), 3), np.float32)), "")
    parts = settle(parts + [probe], seed=831, amp_xz=0.02, amp_y=0.03, freq=1.5, grain=0.0015, micro=0.001)
    probe = parts.pop()
    warped = probe.mesh.parts[0][0].astype(np.float64)
    off = 0
    wl = []
    for l in lines_for_flow:
        wl.append(warped[off:off + len(l)])
        off += len(l)
    n_icd = len(icd_lines)
    _attach_granule_motion(parts[-1], gm)
    parts.append(_particles(wl[:n_icd], 0.0055, "Pancreatic juice (secretion flow)", "Acini", COL["flow"], DESC["flow"],
                            step=0.03, seed=5))
    duct_flow = _particles(wl[n_icd:], 0.0085, "Pancreatic juice in intralobular ducts", "Septa & ducts", COL["flow"],
                           DESC["flow"], step=0.035, seed=6)
    parts.append(duct_flow)
    ins = _particles([smooth_path(l, 30) for l in icap_lines], 0.0045, "Insulin into islet capillaries",
                     "Islets of Langerhans", COL["insulin"], DESC["insulin"], step=0.03, seed=7)
    parts.append(ins)
    return parts


def _pulse(t):
    s = lambda a, b, x: np.clip((x - a) / (b - a), 0, 1) ** 2 * (3 - 2 * np.clip((x - a) / (b - a), 0, 1))  # noqa
    return 1.0 - s(0.0, 0.06, t) * (1.0 - s(0.90, 1.0, t))


def _attach_granule_motion(part, metas):
    """Granules on their own clocks: each drifts from the base of the apex to the lumen and shrinks away there
    (fuses with the apical membrane). At cycle phase 0 every granule is exactly where the static model has it."""
    morph, phase = [], []
    for (pos, _, _), (ph, vec) in zip(part.mesh.parts, metas):
        pos = pos.astype(np.float64)
        ctr = pos.mean(axis=0)
        n = len(pos)
        m = np.zeros((n, 4, 3))
        m[:, 0] = vec                       # one pass from the Golgi side of the apex to the lumen
        m[:, 2] = ctr - pos                 # shrink to nothing at both ends of the pass (budding, fusion)
        m[:, 3] = -ph * vec - float(_pulse(ph)) * m[:, 2]    # with weight 1: phase 0 of the cycle = the rest pose
        morph.append(m)
        phase.append(np.full(n, ph))
    if morph:
        part.anim = {"morph": np.vstack(morph).astype(np.float32), "phase": np.concatenate(phase).astype(np.float32)}
    return part


def _particles(paths, r, name, group, color, desc, step, seed):
    """Particles marching along polylines, one per `step` of length, collapsed to points in the rest pose (so the
    static model shows none). MODE_FLOW: morph 0 carries each particle one step, morph 3 (weighted by the track's
    gate) inflates it; consecutive particles share a phase so the stream is continuous."""
    rng = np.random.default_rng(seed)
    unit = ellipsoid_mesh((0, 0, 0), (r, r, r), 5)
    upos, unrm, uidx = unit.parts[0]
    pos_l, nrm_l, idx_l, m_l, ph_l = [], [], [], [], []
    off = 0
    for path in paths:
        path = np.asarray(path, float)
        seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
        L = seg.sum()
        if L < step:
            continue
        s = np.concatenate([[0], np.cumsum(seg)])
        ts = np.arange(0.0, L - step, step)
        ph0 = rng.random()
        for t in ts:
            a = np.array([np.interp(t, s, path[:, k]) for k in range(3)])
            b = np.array([np.interp(t + step, s, path[:, k]) for k in range(3)])
            n = len(upos)
            pos_l.append(np.repeat(a[None], n, 0))
            nrm_l.append(unrm)
            idx_l.append(uidx + off)
            m = np.zeros((n, 4, 3))
            m[:, 0] = b - a
            m[:, 3] = upos
            m_l.append(m)
            ph_l.append(np.full(n, ph0))
            off += n
    mesh = Mesh()
    if pos_l:
        mesh.add(np.vstack(pos_l), np.vstack(idx_l), np.vstack(nrm_l))
    part = mesh_part(mesh, name, group, color, desc, "gland", rank=2.0, label=False, clip=True,
                     detail=(0.02, 0.0, 0.0, 0))
    if pos_l:
        part.anim = {"morph": np.vstack(m_l).astype(np.float32), "phase": np.concatenate(ph_l).astype(np.float32)}
    return part


# ================================================================================================ animation
def _gate(t):
    """Duct flow runs for most of the cycle and is off at its ends, so phase 0 shows the static model."""
    return window(t, 0.06, 0.16, 0.86, 0.97)


def _insulin(t):
    return window(t, 0.38, 0.48, 0.70, 0.84)


PHASES = [(0.00, 0.12, "Stimulus (CCK, vagus) · zymogen granules move to the apex"),
          (0.12, 0.38, "Exocytosis into the lumen · juice flows down the intercalated ducts"),
          (0.38, 0.84, "Beta cells release insulin into the islet capillaries · ducts drain"),
          (0.84, 1.00, "Secretion subsides")]


def pancreas_animation():
    flow = lambda gate, rate: Track(lambda t: (0.0, 0.0, 0.0, gate(t)), glow=0.45, mode=MODE_FLOW,  # noqa: E731
                                    rate=rate)
    tracks = {
        "Zymogen granules": Track(lambda t: (0.0, 0.0, 0.0, 1.0), glow=lambda t: 0.25 * window(t, 0.02, 0.1, 0.3, 0.45),
                                  mode=MODE_FLOW, rate=1.0),
        "Pancreatic juice (secretion flow)": flow(_gate, 6.0),
        "Pancreatic juice in intralobular ducts": flow(_gate, 6.0),
        "Insulin into islet capillaries": flow(_insulin, 5.0),
        "Beta cells (core)": Track(glow=lambda t: 0.30 * _insulin(t)),
    }
    return Animation(4.0, tracks, phases=PHASES, title="Secretion cycle", speeds=(1.0, 0.5, 0.25))
