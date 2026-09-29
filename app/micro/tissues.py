"""Exocrine/endocrine pancreas, built cell by cell, and the mesh helpers app/micro/pancreas.py uses.

The block's every visible face is a section: cells that cross a face of the block are clipped against it and
capped, so the sides read like the cut surface of a specimen while the top stays three-dimensional. (The procedural
cardiac muscle block that also lived here was retired for the cardiac muscle model in models/cardiac-muscle.)

* Pancreas - lobules separated by septa. Each acinus is a berry of pyramidal cells whose basophilic bases and
  eosinophilic zymogen apices are separate objects, around a lumen holding centroacinar cells; intercalated ducts
  lead to intralobular ducts and on to an interlobular duct in a septum. Islets of Langerhans are packed Voronoi
  polyhedra of beta (core), alpha (mantle) and delta cells threaded by a fenestrated capillary network.
"""
import math

import numpy as np
from scipy.spatial import ConvexHull, SphericalVoronoi, Voronoi, cKDTree

from .cells import extrude, inset_polygon, poisson_disk, smooth_polygon
from .geometry import Mesh, ellipsoid as ellipsoid_mesh, smooth_path, tube
from .kit import Volume, hlayer, mesh_part, noise2, sdf_part, tube_shell
from .organic import settle, tubule
from .sdf import fbm3


# ================================================================================================ mesh helpers
def _merge(mesh):
    """One (pos, idx) array per part: the finishing warp then runs once per part instead of once per cell."""
    pos, nrm, idx = mesh.arrays()
    return Mesh().add(pos, idx, nrm) if len(idx) else Mesh()


def _compact(pos, idx):
    used = np.unique(idx)
    remap = np.full(len(pos), -1, np.int64)
    remap[used] = np.arange(len(used))
    return pos[used], remap[idx]


def _clip_plane(pos, idx, axis, bound, keep_below):
    """Clip a closed, locally convex mesh against an axis-aligned plane and cap the opening with a flat polygon.

    Returns (pos, idx) or None when nothing is left. Only the cell-sized pieces used here are clipped, so the
    section through each one is a single convex outline and a convex hull caps it exactly."""
    s = 1.0 if keep_below else -1.0
    d = (pos[:, axis] - bound) * s
    inside = d <= 0.0
    if inside.all():
        return pos, idx
    if not inside.any():
        return None
    n_in = inside[idx].sum(axis=1)
    tris = [idx[n_in == 3]]
    cross = idx[(n_in > 0) & (n_in < 3)]
    extra, cache = [], {}
    base = len(pos)

    def cut(a, b):
        key = (a, b) if a < b else (b, a)
        if key not in cache:
            t = d[a] / (d[a] - d[b])
            p = pos[a] + (pos[b] - pos[a]) * t
            p = np.array(p, np.float64)
            p[axis] = bound
            extra.append(p)
            cache[key] = base + len(extra) - 1
        return cache[key]

    fan = []
    for tri in cross:
        poly = []
        for k in range(3):
            a, b = int(tri[k]), int(tri[(k + 1) % 3])
            if inside[a]:
                poly.append(a)
            if inside[a] != inside[b]:
                poly.append(cut(a, b))
        for k in range(1, len(poly) - 1):
            fan.append((poly[0], poly[k], poly[k + 1]))
    if fan:
        tris.append(np.array(fan, np.int64))
    allpos = np.vstack([pos, np.array(extra)]) if extra else pos
    if len(extra) >= 3:
        pts = np.array(extra)
        uv = pts[:, [c for c in range(3) if c != axis]]
        try:
            hull = ConvexHull(uv)
            ring = pts[hull.vertices]
            centre = ring.mean(axis=0)
            cb = len(allpos)
            allpos = np.vstack([allpos, centre[None], ring])
            m = len(ring)
            cap = np.array([(cb, cb + 1 + i, cb + 1 + (i + 1) % m) for i in range(m)], np.int64)
            n = np.cross(ring[0] - centre, ring[1 % m] - centre)
            if n[axis] * s < 0:
                cap = cap[:, ::-1]
            tris.append(cap)
        except Exception:                                   # degenerate (sliver) sections need no cap
            pass
    idx = np.vstack([t for t in tris if len(t)])
    if not len(idx):
        return None
    return _compact(allpos, idx)


def _clip_box(mesh, lo, hi, eps=0.0):
    """Clip every piece of a mesh to a box (None on an axis leaves that side open), each piece capped on its own.
    `eps` pushes the caps a hair outside the box so a clipped cell wins the depth test against the layer it sits
    in, whose side wall lies exactly on the box face."""
    out = Mesh()
    for pos, _, idx in mesh.parts:
        p, i = pos.astype(np.float64), idx
        for axis in range(3):
            for bound, below in ((hi[axis], True), (lo[axis], False)):
                if bound is None or p is None:
                    continue
                b = bound + eps if below else bound - eps
                r = _clip_plane(p, i, axis, b, below)
                p, i = (None, None) if r is None else r
        if p is not None and len(i):
            out.add(p, i)
    return out


def _hull_mesh(points, shrink=1.0, round_amt=0.0):
    """Closed convex polyhedron through `points`, optionally shrunk towards its centroid (to leave a cleft between
    packed cells) and subdivided and pulled towards a sphere (to round off a Voronoi cell's corners)."""
    hull = ConvexHull(points)
    pos = points[hull.vertices]
    remap = {v: k for k, v in enumerate(hull.vertices)}
    idx = np.array([[remap[v] for v in s] for s in hull.simplices], np.int64)
    c = pos.mean(axis=0)
    # consistent outward winding
    tri = pos[idx]
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    flip = np.einsum("ij,ij->i", nrm, tri.mean(axis=1) - c) < 0
    idx[flip] = idx[flip][:, ::-1]
    if round_amt:
        pos, idx = _subdivide(pos, idx)
        v = pos - c
        rr = np.linalg.norm(v, axis=1, keepdims=True)
        rm = float(rr.mean())
        pos = c + v * (1.0 - round_amt) + v / np.maximum(rr, 1e-9) * rm * round_amt
    pos = c + (pos - c) * shrink
    return pos, idx


def _subdivide(pos, idx):
    """Split every triangle into four (shared midpoints)."""
    edges = np.sort(np.vstack([idx[:, [0, 1]], idx[:, [1, 2]], idx[:, [2, 0]]]), axis=1)
    uniq, inv = np.unique(edges, axis=0, return_inverse=True)
    inv = inv.reshape(3, -1)
    mids = (pos[uniq[:, 0]] + pos[uniq[:, 1]]) / 2
    m = len(pos) + inv
    a, b, c = idx[:, 0], idx[:, 1], idx[:, 2]
    ab, bc, ca = m[0], m[1], m[2]
    new = np.vstack([np.stack([a, ab, ca], 1), np.stack([ab, b, bc], 1), np.stack([ca, bc, c], 1),
                     np.stack([ab, bc, ca], 1)])
    return np.vstack([pos, mids]), new


def _voronoi_cells(seeds, ghosts, shrink=0.88, round_amt=0.0):
    """Convex Voronoi polyhedra of `seeds`, bounded by `ghosts` (points whose own cells are discarded)."""
    pts = np.vstack([seeds, ghosts])
    vor = Voronoi(pts)
    out = []
    for i in range(len(seeds)):
        region = vor.regions[vor.point_region[i]]
        if not region or -1 in region:
            out.append(None)
            continue
        verts = vor.vertices[region]
        if np.linalg.norm(verts - seeds[i], axis=1).max() > 0.5:
            out.append(None)
            continue
        try:
            out.append(_hull_mesh(verts, shrink, round_amt))
        except Exception:
            out.append(None)
    return out


def _fib_sphere(n, radius, centre=(0.0, 0.0, 0.0), seed=0, jitter=0.0):
    rng = np.random.default_rng(seed)
    k = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * k / n)
    th = math.pi * (1 + 5 ** 0.5) * k
    p = np.stack([np.cos(th) * np.sin(phi), np.cos(phi), np.sin(th) * np.sin(phi)], -1)
    if jitter:
        p = p + rng.normal(scale=jitter, size=p.shape)
        p /= np.linalg.norm(p, axis=1, keepdims=True)
    return np.asarray(centre) + p * radius


def _frame(d):
    """Orthonormal (d, n, b) with n as close to +y as possible."""
    d = np.asarray(d, float) / np.linalg.norm(d)
    up = np.array([0.0, 1.0, 0.0]) if abs(d[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
    n = up - d * np.dot(up, d)
    n /= np.linalg.norm(n)
    return d, n, np.cross(d, n)


# ================================================================================================= pancreas
PANC = {
    "basal": "Acinar cells – basal cytoplasm: the broad base of each pyramidal serous cell, packed with rough ER "
             "(and so basophilic, purple in H&E) around a round basal nucleus. The acinar cell makes more protein "
             "for export than any other cell: trypsinogen, chymotrypsinogen, procarboxypeptidase, proelastase, "
             "lipase, amylase and nucleases. The basal surface carries CCK1 and M3 receptors that trigger "
             "secretion.",
    "apical": "Acinar cells – apical zymogen granules: eosinophilic secretory granules crowded into the apex of each "
              "cell and released into the lumen by exocytosis. Proteases leave as inactive zymogens with trypsin "
              "inhibitor (SPINK1); they are activated only in the duodenum, where enteropeptidase cleaves "
              "trypsinogen to trypsin. Mutations of PRSS1 or SPINK1 cause hereditary pancreatitis.",
    "nuclei": "Acinar cell nuclei: round, basal, with a prominent nucleolus – the sign of a cell making ribosomes "
              "for heavy protein synthesis.",
    "centroacinar": "Centroacinar cells: pale, flattened cells inside the acinar lumen – the first cells of the "
                    "intercalated duct pushed into the acinus. Unique to the pancreas and a key to recognising it. "
                    "Together with duct cells they secrete bicarbonate-rich fluid through CFTR in response to "
                    "secretin, neutralising gastric acid in the duodenum.",
    "intercalated": "Intercalated ducts: long, narrow ducts of low cuboidal cells continuous with the centroacinar "
                    "cells, draining each acinus. They secrete bicarbonate and water (secretin, CFTR). The pancreas "
                    "has no striated ducts – one way to tell it from a salivary gland.",
    "intralobular": "Intralobular ducts: simple cuboidal ducts collecting intercalated ducts within the lobule.",
    "interlobular": "Interlobular duct: columnar epithelium with occasional goblet cells in a sheath of dense "
                    "connective tissue in the septum, draining towards the main pancreatic duct (of Wirsung) and the "
                    "ampulla. Ductal adenocarcinoma arises from this epithelium.",
    "septa": "Interlobular septa: connective tissue partitions dividing the gland into lobules and carrying the "
             "interlobular ducts, arteries, veins, lymphatics and nerves. The pancreas has only a thin capsule, so "
             "inflammation and tumour spread easily into the surrounding fat.",
    "stroma": "Intralobular connective tissue: a scant reticular framework between acini with a dense capillary "
              "network. Pancreatic stellate cells here store vitamin A and, when activated by alcohol or injury, "
              "cause the fibrosis of chronic pancreatitis.",
    "artery": "Interlobular artery: branch of the pancreaticoduodenal or splenic arteries. Arterioles supply the "
              "islets first; blood then flows on from the islets to the surrounding acini (the insulo-acinar "
              "portal system), bathing them in islet hormones.",
    "vein": "Interlobular vein draining to the splenic and superior mesenteric veins and so to the portal vein – "
            "islet insulin reaches the liver first.",
    "beta": "Beta cells: 60–70 % of islet cells, in the core of the islet (the mantle–core arrangement is clearest "
            "in rodents; human islets are more intermingled). Secrete insulin, C-peptide and amylin in response to "
            "glucose entering through GLUT2 and closing ATP-sensitive K+ channels (the target of sulfonylureas). "
            "Destroyed by autoimmunity in type 1 diabetes; exhausted and amyloid-laden in type 2.",
    "alpha": "Alpha cells: 15–20 % of islet cells, at the periphery (mantle) of the islet. Secrete glucagon, which "
             "raises blood glucose by glycogenolysis and gluconeogenesis in the liver. Glucagonoma causes "
             "diabetes, weight loss and necrolytic migratory erythema.",
    "delta": "Delta cells: 5–10 % of islet cells, scattered near the periphery with long processes. Secrete "
             "somatostatin, which inhibits both insulin and glucagon release (paracrine) as well as exocrine "
             "secretion. PP (F) cells, a few per cent mostly in the head, make pancreatic polypeptide.",
    "islet_caps": "Islet capillaries: fenestrated capillaries forming a dense glomerulus-like network (islets get "
                  "~10 % of pancreatic blood flow for ~2 % of its mass) so every endocrine cell touches blood. "
                  "Efferent vessels run on into the acini around the islet – the insulo-acinar portal system.",
}


def _square_ends(path, axis, margin=0.09):
    """Straighten the last stretch at each end of a path so it meets a block face square on: a duct or vessel
    then ends in a flat ring on the face instead of a tilted one half buried in it."""
    path = np.array(path, float)
    for end in (0, -1):
        ref = path[end, axis]
        near = np.abs(path[:, axis] - ref) < margin
        if near.all():
            continue
        k = np.argmin(np.where(near, np.inf, np.abs(path[:, axis] - ref)))
        others = [c for c in range(3) if c != axis]
        path[np.ix_(near, others)] = path[k, others]
    return path


def _septum_lines():
    """Four septa as polylines in the xz plane, and the rule that says which lobule a point is in."""
    zs = np.linspace(-0.68, 0.68, 120)
    xs = np.linspace(-1.08, 1.08, 150)
    x_s1 = lambda z: 0.33 + 0.07 * np.sin(3.0 * z + 0.5)
    z_s2 = lambda x: -0.25 + 0.05 * np.sin(3.3 * x)
    z_s3 = lambda x: 0.18 + 0.05 * np.sin(2.9 * x + 1.0)
    x_s4 = lambda z: -0.5 + 0.05 * np.sin(4.0 * z)
    s1 = np.stack([x_s1(zs), zs], -1)
    s2 = np.stack([xs, z_s2(xs)], -1)
    s2 = s2[s2[:, 0] < x_s1(s2[:, 1])]
    s3 = np.stack([xs, z_s3(xs)], -1)
    s3 = s3[s3[:, 0] > x_s1(s3[:, 1])]
    s4 = np.stack([x_s4(zs), zs], -1)
    s4 = s4[s4[:, 1] > z_s2(s4[:, 0])]
    lines = [(s1, 0.062), (s2, 0.036), (s3, 0.022), (s4, 0.022)]

    def lobule(x, z):
        if x > x_s1(z):
            return 3 if z > z_s3(x) else 4
        if z < z_s2(x):
            return 2
        return 0 if x < x_s4(z) else 1
    return lines, lobule, x_s1, z_s2


def _acinus(c, R, rot, stretch, rng, nuclei=True):
    """One serous acinus: pyramidal cells around a small lumen, each split into a basophilic base and a zymogen apex.

    Cell outlines are the spherical Voronoi regions of points on a sphere; each is extruded radially from the lumen
    to the basal lamina (so the cells taper into pyramids by construction), inset to leave a cleft between them, and
    domed at the base."""
    n = int(rng.integers(9, 14))
    dirs = _fib_sphere(n, 1.0, seed=int(rng.integers(1 << 30)), jitter=0.22)
    sv = SphericalVoronoi(dirs, 1.0, np.zeros(3))
    sv.sort_vertices_of_regions()
    M = rot @ np.diag(stretch) @ rot.T
    r_lum, r_mid = 0.2 * R, 0.53 * R
    base, apex, nuc = Mesh(), Mesh(), Mesh()
    for i, region in enumerate(sv.regions):
        s = dirs[i]
        _, e1, e2 = _frame(s)
        V = sv.vertices[region]
        q = V / np.maximum(V @ s, 0.2)[:, None]
        poly = np.stack([q @ e1, q @ e2], -1)
        ang = np.arctan2(poly[:, 1], poly[:, 0])
        poly = poly[np.argsort(ang)]
        poly = inset_polygon(smooth_polygon(poly, 1), 0.04)
        rho = float(np.linalg.norm(poly, axis=1).mean())

        def mapping(U, Vv, T, last=None):
            T = np.asarray(T, float)
            k = np.interp(T, [0.0, 0.84 * R, 0.95 * R, R], [1.0, 1.0, 0.95, 0.78])
            d = s[None, None, :] * 1.0 + (U * k)[..., None] * e1 + (Vv * k)[..., None] * e2
            d = d / np.linalg.norm(d, axis=-1, keepdims=True)
            dist = np.sqrt(U ** 2 + Vv ** 2) / rho
            rad = T + np.where(T >= R - 1e-9, 0.07 * R * np.clip(1.0 - dist ** 2, 0.0, 1.0), 0.0)
            p = (d * rad[..., None]) @ M.T + c
            return p[..., 0], p[..., 1], p[..., 2]

        base.extend(extrude(poly, mapping, [r_mid, 0.72 * R, 0.84 * R, 0.95 * R, R]))
        apex.extend(extrude(poly, mapping, [r_lum, r_mid + 0.002]))
        if nuclei:
            nc = (s * 0.73 * R) @ M.T + c
            rn = 0.15 * R * rng.uniform(0.9, 1.1)
            nuc.extend(ellipsoid_mesh(nc, (rn, rn * 0.92, rn), 5))
    return base, apex, nuc


def _islet(c, radii, rng, seed):
    """Islet of Langerhans: packed Voronoi cells threaded by capillaries, sorted into beta (core), alpha (mantle)
    and delta (scattered, peripheral) cells."""
    c = np.asarray(c, float)
    radii = np.asarray(radii, float)
    sp = 0.027
    pts = poisson_disk(-radii, radii, sp, seed=seed)
    q = np.linalg.norm(pts / radii, axis=1)
    pts = pts[q < 1.0 - 0.35 * sp / radii.min()]
    # capillaries: loops wandering through the islet and leaving it towards the acini
    capm = Mesh()
    cap_pts = []
    for k in range(9):
        a = _fib_sphere(9, 1.0, seed=seed + 5, jitter=0.3)[k]
        b = -a + rng.normal(scale=0.5, size=3)
        b /= np.linalg.norm(b)
        mid = rng.normal(scale=0.35, size=3)
        # each capillary arrives running over the islet surface, plunges through it and leaves on the far side
        # towards the surrounding acini
        ta = np.cross(a, rng.normal(size=3))
        tb = np.cross(b, rng.normal(size=3))
        ta /= np.linalg.norm(ta)
        tb /= np.linalg.norm(tb)
        ctrl = np.array([a * 1.22 + ta * 0.45, a * 1.08 + ta * 0.12, a * 0.6 + mid * 0.3, mid * 0.5,
                         b * 0.6 + mid * 0.3, b * 1.08 + tb * 0.12, b * 1.22 + tb * 0.45]) * radii
        path = smooth_path(ctrl, 44)
        capm.extend(tube(path + c, 0.0078, 8))
        cap_pts.append(path)
    # a few short cross-links make it a network rather than separate loops
    for k in range(6):
        i, j = rng.choice(9, 2, replace=False)
        pa = cap_pts[i][rng.integers(12, 28)]
        pb = cap_pts[j][np.argmin(np.linalg.norm(cap_pts[j] - pa, axis=1))]
        if np.linalg.norm(pa - pb) < 0.16:
            link = smooth_path(np.array([pa, (pa + pb) / 2 + rng.normal(scale=0.01, size=3), pb]), 8)
            capm.extend(tube(link + c, 0.0068, 8))
            cap_pts.append(link)
    line = np.vstack(cap_pts)
    dline, _ = cKDTree(line).query(pts)
    pts = pts[dline > 0.021]
    ghosts = [_fib_sphere(int(4 * math.pi * (radii.mean() + f * sp) ** 2 / sp ** 2 * 1.1), 1.0, seed=seed + int(f * 10))
              * (radii + f * sp) for f in (0.55, 1.6)]
    dense = np.vstack([smooth_path(p, max(8, int(len(p) * 1.5))) for p in cap_pts])
    ghosts.append(dense)
    cells = _voronoi_cells(pts, np.vstack(ghosts), shrink=0.86, round_amt=0.25)
    qn = np.linalg.norm(pts / radii, axis=1)
    kinds = {"beta": Mesh(), "alpha": Mesh(), "delta": Mesh()}
    for p, qq, cell in zip(pts, qn, cells):
        if cell is None:
            continue
        r = rng.random()
        kind = "delta" if (qq > 0.45 and r < 0.12) or r < 0.02 else ("alpha" if qq > 0.70 else "beta")
        kinds[kind].add(cell[0] + c, cell[1])
    return kinds, capm


def build_pancreas():
    rng = np.random.default_rng(83)
    X0, X1, Z0, Z1, Y_BOT = -1.0, 1.0, -0.6, 0.6, -0.5
    EPS = 0.004           # caps sit this far proud of the faces: more than the finishing warp's 3D terms can shift
    lo_clip, hi_clip = [X0, Y_BOT, Z0], [X1, None, Z1]
    parts = []
    lines, lobule, x_s1, z_s2 = _septum_lines()
    sep_pts = np.vstack([l for l, _ in lines])
    sep_half = np.concatenate([np.full(len(l), h) for l, h in lines])
    sep_tree = cKDTree(sep_pts)

    def d_sep(x, z):
        """Distance (in xz) from the surface of the nearest septum."""
        q = np.stack(np.broadcast_arrays(np.asarray(x, float), np.asarray(z, float)), -1)
        dd, j = sep_tree.query(q.reshape(-1, 2))
        return (dd - sep_half[j]).reshape(q.shape[:-1])

    groove = lambda X, Z: -0.075 * np.exp(-(np.maximum(d_sep(X, Z), 0.0) / 0.07) ** 2)
    y_str = lambda X, Z: 0.222 + groove(X, Z) + noise2(0.012, 3.0, seed=13)(X, Z)
    parts.append(hlayer("Intralobular connective tissue", "Lobules", "#edd9cb", Y_BOT, y_str, PANC["stroma"],
                        "fascia", (X0, X1), (Z0, Z1), res=140, bulk=True, rank=-1, label=False,
                        detail=(0.10, 60.0, 0.15, 0)))

    # ------------------------------------------------------------------ septa (signed-distance walls)
    vol = Volume((X0 - 0.02, Y_BOT - 0.02, Z0 - 0.02), (X1 + 0.02, 0.36, Z1 + 0.02), 0.009)
    x, y, z = vol.axes()
    XX, ZZ = np.meshgrid(x[:, 0, 0], z[0, 0, :], indexing="ij")
    ds = d_sep(XX, ZZ) + 0.006 * fbm3(XX * 9.0, 0.3, ZZ * 9.0, 1.0, 2, 3)
    top = y_str(XX, ZZ) + 0.012
    vol.d = np.maximum(ds[:, None, :], y - top[:, None, :]).astype(np.float32)
    vol.intersect_box((X0 - EPS * 0.7, Y_BOT - EPS * 0.7, Z0 - EPS * 0.7), (X1 + EPS * 0.7, 1.0, Z1 + EPS * 0.7))
    parts.append(sdf_part(vol, "Interlobular septa", "Septa & ducts", "#e2c2a2", PANC["septa"], "fascia",
                          smooth=0.9, rank=-0.5, detail=(0.12, 50.0, 0.15, 0)))

    # ------------------------------------------------------------------ duct tree
    # the septal duct and vessels end exactly on the block faces (just proud of them), so their lumens show
    zz = np.linspace(Z0 - EPS, Z1 + EPS, 70)
    inter = _square_ends(np.stack([x_s1(zz), 0.13 + 0.02 * np.sin(zz * 4.0), zz], -1), 2)
    xx = np.linspace(X0 - EPS, x_s1(-0.25) - 0.02, 60)
    inter2 = _square_ends(np.stack([xx, 0.11 + 0.015 * np.sin(xx * 5.0), z_s2(xx)], -1), 0)
    _, m_inter = tubule(inter, 0.033, 0.052, seed=5, cell=0.030, amp=0.004, aspect=1.2, lobe=(7, 0.06),
                        calibre=0.05, n_theta=40, n_s=70)
    _, m_inter2 = tubule(inter2, 0.018, 0.031, seed=6, cell=0.026, amp=0.003, aspect=1.2, lobe=(6, 0.05),
                         calibre=0.05, n_theta=28, n_s=60)
    parts.append(mesh_part(_merge(Mesh().extend(m_inter).extend(m_inter2)),
                           "Interlobular ducts", "Septa & ducts", "#c7a44c", PANC["interlobular"], "gland",
                           rank=1, detail=(0.08, 150.0, 0.9, 0)))
    art = _square_ends(np.stack([x_s1(zz) - 0.036, 0.025 + 0.01 * np.sin(zz * 3), zz], -1), 2)
    ven = _square_ends(np.stack([x_s1(zz) + 0.030, 0.018 + 0.01 * np.sin(zz * 2.6 + 1), zz], -1), 2)
    parts.append(mesh_part(tube_shell(art, 0.021, 0.011, 20),
                           "Interlobular artery", "Septa & ducts", "#c8322b", PANC["artery"], "artery", rank=1,
                           detail=(0.06, 110.0, 0.6, 3)))
    parts.append(mesh_part(tube_shell(ven, 0.027, 0.020, 20),
                           "Interlobular vein", "Septa & ducts", "#4f5fb0", PANC["vein"], "vein", rank=1))

    # intralobular ducts: a trunk from the septal duct into each lobule, with side branches
    def on_inter(zv):
        return np.array([x_s1(zv), 0.13 + 0.02 * np.sin(zv * 4.0), zv])

    def on_inter2(xv):
        return np.array([xv, 0.11 + 0.015 * np.sin(xv * 5.0), z_s2(xv)])

    trunks = [(0, on_inter2(-0.8), [(-0.78, 0.12, 0.05), (-0.74, 0.02, 0.4)]),
              (1, on_inter(0.3), [(0.05, 0.19, 0.32), (-0.3, 0.2, 0.36)]),
              (2, on_inter(-0.45), [(0.05, 0.02, -0.44), (-0.45, -0.1, -0.47)]),
              (3, on_inter(0.42), [(0.62, 0.08, 0.40), (0.95, -0.05, 0.38)]),
              (4, on_inter(-0.02), [(0.55, -0.1, -0.02), (0.92, -0.18, -0.05)])]
    lob_ducts = {k: [inter, inter2] for k in range(5)}
    intra = Mesh()
    for lob, start, ctrl in trunks:
        path = smooth_path(np.vstack([start, ctrl]), 40)
        lob_ducts[lob].append(path)
        _, m = tubule(path, 0.011, 0.021, seed=40 + lob, cell=0.022, amp=0.003, lobe=(5, 0.05), calibre=0.05,
                      n_theta=22, n_s=40)
        intra.extend(m)
        for j in (14, 28):
            p0 = path[j]
            tng = path[j + 1] - path[j - 1]
            side = np.cross(tng, [0.0, 1.0, 0.0])
            side /= np.linalg.norm(side)
            sgn = 1 if (j + lob) % 2 else -1
            br = smooth_path(np.array([p0, p0 + side * sgn * 0.12 + np.array([0, rng.uniform(-0.12, 0.08), 0]),
                                       p0 + side * sgn * 0.24 + np.array([0, rng.uniform(-0.2, 0.1), 0])]), 20)
            br = np.clip(br, [X0 + 0.1, Y_BOT + 0.1, Z0 + 0.1], [X1 - 0.1, 0.3, Z1 - 0.1])
            lob_ducts[lob].append(br)
            _, m = tubule(br, 0.008, 0.016, seed=60 + lob * 3 + j, cell=0.02, amp=0.002, lobe=(5, 0.05),
                          calibre=0.05, n_theta=18, n_s=20)
            intra.extend(m)
    parts.append(mesh_part(_merge(_clip_box(intra, lo_clip, hi_clip, EPS)), "Intralobular ducts",
                           "Septa & ducts", "#dcc27c", PANC["intralobular"], "gland", rank=0.8,
                           detail=(0.08, 170.0, 0.9, 0)))

    # ------------------------------------------------------------------ islets
    islets = [((-0.2, 0.0, 0.05), (0.17, 0.14, 0.155), 91), ((0.66, 0.29, -0.26), (0.14, 0.13, 0.135), 92),
              ((-0.93, -0.22, -0.45), (0.11, 0.1, 0.11), 93)]
    kinds = {"beta": Mesh(), "alpha": Mesh(), "delta": Mesh()}
    icaps = Mesh()
    for c, radii, sd in islets:
        k, capm = _islet(c, radii, rng, sd)
        for name in kinds:
            kinds[name].extend(k[name])
        icaps.extend(capm)

    # ------------------------------------------------------------------ acini
    duct_pts = np.vstack([np.vstack(v) for v in lob_ducts.values()] + [art, ven])
    duct_tree = cKDTree(duct_pts)
    # acini are packed as tightly as grapes on a body-centred lattice. Its planes are placed so that every block
    # face and both default cut planes pass just off a plane of acinar centres: each section then shows a
    # chequerboard of large acini cut near their equator (lumen, apical granules, basal nuclei) with smaller
    # glancing sections between them, as in a real slide
    A = 0.2
    org = np.array([X0 + 0.03, Y_BOT + 0.03, Z0 + 0.03])
    g = np.stack(np.meshgrid(*[np.arange(-1, n + 2) for n in (10, 5, 6)], indexing="ij"), -1).reshape(-1, 3) * A
    cand = np.vstack([g, g + A / 2]) + org
    # the second lattice plane lies 0.07 from each face: nudge it to 0.04 so it is cut through its lumen as well
    for axis, bound in ((0, X0), (0, X1), (2, Z0), (2, Z1), (1, Y_BOT)):
        dist = cand[:, axis] - bound
        far = (np.abs(dist) > 0.05) & (np.abs(dist) < 0.09)
        cand[far, axis] -= np.sign(dist[far]) * 0.03
    cand += rng.normal(scale=0.009, size=cand.shape)
    inb = np.all((cand > [X0 - 0.05, Y_BOT - 0.05, Z0 - 0.05]) & (cand < [X1 + 0.05, 0.35, Z1 + 0.05]), axis=1)
    cand = cand[inb]
    base, apex, nuc, cent, icd = Mesh(), Mesh(), Mesh(), Mesh(), Mesh()
    placed = {k: [] for k in range(5)}
    acini = []
    nn = cKDTree(cand).query(cand, k=2)[0][:, 1]
    for p, gap in zip(cand, nn):
        R = float(np.clip(0.5 * gap * rng.uniform(1.02, 1.1), 0.066, 0.096))
        if d_sep(p[0], p[2]) < R * 0.6:
            continue
        if duct_tree.query(p)[0] < R * 0.8 + 0.02:
            continue
        if any(np.linalg.norm((p - np.array(ic)) / (np.array(ir) + R + 0.012)) < 1.0 for ic, ir, _ in islets):
            continue
        acini.append((p, R))
    # drain the acini nearest the ducts first, so outer acini can drain through their neighbours' ducts
    acini.sort(key=lambda a: duct_tree.query(a[0])[0])
    lob_trees = {k: cKDTree(np.vstack(v)) for k, v in lob_ducts.items()}
    lob_pts = {k: np.vstack(v) for k, v in lob_ducts.items()}
    for p, R in acini:
        lob = lobule(p[0], p[2])
        rot = np.linalg.qr(rng.normal(size=(3, 3)))[0]
        stretch = np.array([rng.uniform(1.0, 1.12), rng.uniform(0.92, 1.0), rng.uniform(0.92, 1.0)])
        # nuclei only where a section can show them: near the block faces and the default cut planes
        near = (min(p[0] - X0, X1 - p[0], p[2] - Z0, Z1 - p[2], p[1] - Y_BOT) < R + 0.1
                or (p[0] < 0.15 and abs(p[2]) < R + 0.12) or (p[2] > -0.15 and abs(p[0]) < R + 0.12))
        b, a, n = _acinus(p, R, rot, stretch, rng, near)
        base.extend(b)
        apex.extend(a)
        nuc.extend(n)
        dd, j = lob_trees[lob].query(p)
        target = lob_pts[lob][j]
        if placed[lob]:
            prev = np.array(placed[lob])
            k = int(np.argmin(np.linalg.norm(prev - p, axis=1)))
            if np.linalg.norm(prev[k] - p) < dd * 0.8:
                target = prev[k]
        placed[lob].append(p)
        v = target - p
        L = float(np.linalg.norm(v))
        u = v / max(L, 1e-9)
        cent.extend(ellipsoid_mesh(p + u * 0.004, (0.013, 0.0075, 0.012), 6,
                                   rotation=np.stack(_frame(u), axis=1)))
        mid = p + v * 0.5 + rng.normal(scale=0.02, size=3)
        icd.extend(tube(smooth_path(np.array([p, mid, target]), 10), 0.0085, 8))
    parts += [
        mesh_part(_merge(_clip_box(base, lo_clip, hi_clip, EPS)), "Acinar cells – basal (basophilic) cytoplasm",
                  "Acini", "#a8788c", PANC["basal"], "gland", rank=0.5, detail=(0.09, 180.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(apex, lo_clip, hi_clip, EPS * 1.3)), "Acinar cells – apical zymogen granules",
                  "Acini", "#eba48c", PANC["apical"], "gland", rank=0.5, label=True, detail=(0.30, 260.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(nuc, lo_clip, hi_clip, EPS * 1.8)), "Acinar cell nuclei", "Acini", "#4b2c55",
                  PANC["nuclei"], "nucleus", rank=0.6, label=False, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(cent, lo_clip, hi_clip, EPS * 1.6)), "Centroacinar cells", "Acini", "#efe9d6",
                  PANC["centroacinar"], "gland", rank=0.6, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(icd, lo_clip, hi_clip, EPS * 1.4)), "Intercalated ducts", "Septa & ducts",
                  "#ece0bf", PANC["intercalated"], "gland", rank=0.7, detail=(0.06, 200.0, 0.9, 0)),
        mesh_part(_merge(_clip_box(kinds["beta"], lo_clip, hi_clip, EPS)), "Beta cells (core)",
                  "Islets of Langerhans", "#eee2d8", PANC["beta"], "gland", rank=1.5, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(kinds["alpha"], lo_clip, hi_clip, EPS)), "Alpha cells (mantle)",
                  "Islets of Langerhans", "#efbcb4", PANC["alpha"], "gland", rank=1.5, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(kinds["delta"], lo_clip, hi_clip, EPS)), "Delta cells",
                  "Islets of Langerhans", "#e8cf8e", PANC["delta"], "gland", rank=1.5, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(icaps, lo_clip, hi_clip, EPS * 1.2)), "Islet capillaries (fenestrated)",
                  "Islets of Langerhans", "#d8433b", PANC["islet_caps"], "artery", rank=1.6,
                  detail=(0.06, 120.0, 0.5, 0)),
    ]
    return settle(parts, seed=831, amp_xz=0.022, amp_y=0.035, freq=1.5, grain=0.002, micro=0.0015)
