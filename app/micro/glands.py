"""Thyroid follicles (with a parathyroid gland) and the dorsum of the tongue with its papillae and taste buds.

Both are organs whose units are rounded bodies packed in three dimensions - follicles in the thyroid, papillae, taste
buds and glands in the tongue - so both are built from explicit placements (packed follicles, papillae scattered on
the dorsum) that are then turned into signed-distance fields or meshes, rather than from stacked slabs."""
import math

import numpy as np
from scipy import ndimage
from scipy.spatial import ConvexHull, Delaunay, cKDTree

from .cells import frame_from_normal, hex_points, jittered_bcc, poisson_disk
from .geometry import Mesh, ellipsoid as ellipsoid_mesh, smooth_path, tube
from .kit import Volume, blob_cluster, box_shape, ellipsoid, mesh_part, round_cone, sdf_part, wavy_path
from .organic import cell_relief, fibre_relief, relief, settle
from .sdf import fbm3, smin, sphere as sphere_shape

X0, X1, Z0, Z1 = -1.0, 1.0, -0.6, 0.6


# =============================================================================== shared helpers
def _sampler(vol):
    """Trilinear lookup of a Volume's distance field at arbitrary points (n, 3)."""
    def f(p):
        q = ((np.asarray(p, np.float64) - vol.lo) / vol.voxel).T
        return ndimage.map_coordinates(vol.d, q, order=1, mode="nearest")
    return f


def _ray_hits(sample, c, dirs, rmax, n=32):
    """Distance from c along each unit direction to where the field first turns positive (the surface)."""
    dirs = np.asarray(dirs, np.float64).reshape(-1, 3)
    t = np.linspace(0.0, rmax, n)
    P = np.asarray(c, np.float64)[None, None, :] + dirs[:, None, :] * t[None, :, None]
    d = sample(P.reshape(-1, 3)).reshape(len(dirs), n)
    out = d > 0
    k = np.argmax(out, axis=1)
    k = np.where(out.any(axis=1), np.maximum(k, 1), n - 1)
    rows = np.arange(len(dirs))
    d0, d1 = d[rows, k - 1], d[rows, k]
    w = np.clip(d0 / np.where(np.abs(d0 - d1) < 1e-9, -1e-9, d0 - d1), 0.0, 1.0)
    return t[k - 1] + (t[k] - t[k - 1]) * w


def _fibonacci(n, rng):
    """n well-spread unit vectors, randomly rotated."""
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    th = math.pi * (1 + 5 ** 0.5) * i
    v = np.stack([np.cos(th) * np.sin(phi), np.cos(phi), np.sin(th) * np.sin(phi)], -1)
    q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    return v @ q.T


def _slerp(a, b, n):
    om = math.acos(float(np.clip(a @ b, -1.0, 1.0)))
    if om < 1e-6:
        return np.repeat(a[None], n, 0)
    t = np.linspace(0, 1, n)[:, None]
    return (np.sin((1 - t) * om) * a + np.sin(t * om) * b) / math.sin(om)


def _rand_rot(rng):
    q, r = np.linalg.qr(rng.normal(size=(3, 3)))
    return q * np.sign(np.diag(r))


def _merged(parts):
    """Fuse each part's sub-meshes into one, so the finishing warp runs once per part instead of once per tube."""
    for part in parts:
        if len(part.mesh.parts) > 1:
            pos, nrm, idx = part.mesh.arrays()
            part.mesh = Mesh().add(pos, idx, nrm)
    return parts


def _inside_box(p, lo, hi, m=0.0):
    p = np.asarray(p)
    return np.all((p > np.asarray(lo) + m) & (p < np.asarray(hi) - m), axis=-1)


# =============================================================================== thyroid
THYROID = {
    "follicular": "Follicular (principal) cells: a simple epithelium, one cell thick, resting on a basal lamina and "
                  "facing the colloid with microvilli. Its height tracks activity – flattened in large, resting "
                  "follicles, cuboidal in the usual state, and columnar in small, TSH-stimulated follicles (as in "
                  "Graves disease). The cells take up iodide from the blood (Na+/I- symporter, NIS), make "
                  "thyroglobulin and iodinate it at the apical surface (thyroid peroxidase), then take the colloid "
                  "back in by endocytosis, digest it in lysosomes and release T4 (and some T3) basally.",
    "colloid": "Colloid: the follicle lumen, filled with stored iodinated thyroglobulin – roughly two to three "
               "months' supply of hormone, making the thyroid the only endocrine gland that stores its product "
               "outside its cells. Eosinophilic in H&E and PAS-positive. Large follicles with dense colloid are storing; small "
               "follicles with pale, scalloped colloid are actively releasing hormone.",
    "vacuoles": "Resorption vacuoles: clear scallops at the edge of the colloid, next to the apical surface of the "
                "follicular cells. They mark active endocytosis of colloid (pseudopodia and pinocytosis) under TSH "
                "stimulation, and are prominent in hyperactive glands such as Graves disease.",
    "c_cells": "Parafollicular (C) cells: large, pale-staining neuroendocrine cells, single or in small groups. They "
               "sit within the follicle wall on the basal lamina but never reach the colloid, or lie in the "
               "connective tissue between follicles. They secrete calcitonin, which lowers blood calcium by "
               "inhibiting osteoclasts. Derived from neural crest via the ultimobranchial body (4th pharyngeal "
               "pouch); their tumour is medullary thyroid carcinoma (MEN2, RET mutations, calcitonin as tumour "
               "marker, amyloid stroma).",
    "caps": "Perifollicular capillaries: a dense basket of fenestrated capillaries hugging the basal surface of every "
            "follicle, fed by branches of the superior and inferior thyroid arteries. They deliver iodide and "
            "carry away T3/T4 – per gram, the thyroid receives one of the highest blood flows of any organ.",
    "stroma": "Interfollicular connective tissue: a delicate reticular stroma between the follicles that carries the "
              "capillaries, lymphatics and sympathetic nerve fibres. Here it has been partly dissected away at the "
              "surface to expose the follicles in three dimensions.",
    "septa": "Interlobular septa: sheets of connective tissue running in from the capsule that divide the gland into "
             "lobules of 20-40 follicles and carry the larger arteries, veins, lymphatics and nerves.",
    "capsule": "Capsule: a thin fibrous capsule of dense connective tissue (true capsule) that sends septa into the "
               "gland. Outside it the pretracheal layer of deep cervical fascia forms a false capsule attaching the "
               "gland to the larynx and trachea, which is why the thyroid moves up on swallowing.",
    "artery": "Arterioles: branches of the superior thyroid artery (from the external carotid) and inferior thyroid "
              "artery (from the thyrocervical trunk) that run in the capsule and septa before breaking up into "
              "the perifollicular capillary baskets.",
    "vein": "Venules and veins: drain the follicular capillaries through the septa to the capsular plexus and on to "
            "the superior, middle and inferior thyroid veins.",
    "pt_capsule": "Parathyroid capsule: the parathyroid glands (usually four, each about 6 × 4 × 2 mm) lie on the "
                  "posterior surface of the thyroid lobes, each wrapped in its own thin capsule that separates it "
                  "from the thyroid tissue.",
    "chief": "Parathyroid chief cells: small, polygonal cells with a central nucleus and pale cytoplasm, arranged in "
             "anastomosing cords and nests around capillaries. They sense blood calcium through the "
             "calcium-sensing receptor and secrete parathyroid hormone (PTH) when it falls: PTH releases calcium "
             "from bone, increases renal calcium reabsorption and phosphate excretion, and activates vitamin D "
             "(1α-hydroxylase).",
    "oxyphil": "Oxyphil cells: larger cells with strongly eosinophilic cytoplasm packed with mitochondria, single or "
               "in clusters. They appear around puberty and increase with age; their function is uncertain.",
    "pt_fat": "Adipocytes of the parathyroid: fat cells in the stroma that increase with age, occupying up to half "
              "of the gland in older adults – a feature that helps identify parathyroid tissue on biopsy.",
    "pt_caps": "Parathyroid capillaries: a rich network of fenestrated capillaries between the cords of chief cells, "
               "into which PTH is secreted.",
}

T_TOP, T_STROMA_TOP, T_CAPS_BOT = 0.92, 0.76, 0.855
INFLATE = 1.35                 # follicles grow into the voids left by packing, until neighbours flatten them
PT_C, PT_R = np.array([0.72, 0.30, 0.36]), np.array([0.34, 0.28, 0.30])
# interlobular septa as polylines in the xz plane (they run the full depth of the block); kept oblique to the
# default cut planes so the cut sections them instead of sliding along one
SEPTA = [smooth_path(np.array(p, float), 60) for p in (
    [(-1.06, 0.30), (-0.62, 0.08), (-0.30, -0.14), (-0.08, -0.40), (0.02, -0.66)],
    [(-0.30, -0.14), (0.10, -0.06), (0.52, -0.16), (1.06, -0.08)])]
_SEPTA_TREE = cKDTree(np.vstack([np.linspace(a, b, 6) for sp in SEPTA for a, b in zip(sp[:-1], sp[1:])]))


def _capsule_x(z):
    """Free edge of the capsule where it has been peeled back from the front of the block."""
    z = np.asarray(z, np.float64)
    return 0.22 + 0.07 * np.sin(z * 4.3 + 0.6) + 0.035 * np.sin(z * 11.0 + 2.0)


def _septum_edge(x, z):
    """Distance in the xz plane to the nearest septum centreline."""
    x, z = np.broadcast_arrays(np.asarray(x, np.float64), np.asarray(z, np.float64))
    d, _ = _SEPTA_TREE.query(np.stack([x.ravel(), z.ravel()], -1))
    return d.reshape(x.shape)


def _pt_d(p, grow=0.0):
    """Approximate distance to the parathyroid ellipsoid (negative inside)."""
    q = (np.asarray(p, np.float64) - PT_C) / (PT_R + grow)
    return (np.linalg.norm(q, axis=-1) - 1.0) * float((PT_R + grow).min())


def _pack_follicles(rng, lo, hi):
    """Dart-throwing of follicles from the largest down, so big resting follicles and small active ones mix.

    Follicles may cross the sides and floor of the block (they are sectioned there) but never the top, where the
    dissected surface exposes them whole."""
    radii = np.sort(0.055 + 0.13 * rng.beta(1.3, 2.6, 900))[::-1]
    cs, rs = [], []
    for r in radii:
        for _ in range(40):
            p = rng.uniform(lo - 0.5 * r, hi + 0.5 * r)
            top = T_TOP if p[0] < _capsule_x(p[2]) - 0.04 else T_CAPS_BOT - 0.01
            if p[1] + r * 1.2 > top - 0.01 or p[1] < -0.4 * r:
                continue
            if _pt_d(p) < r + 0.05:
                continue
            if float(_septum_edge(p[0], p[2])) < r * 0.8 + 0.025:
                continue
            if cs:
                d = np.linalg.norm(np.asarray(cs) - p, axis=1) - np.asarray(rs)
                if d.min() < r + 0.012:
                    continue
            cs.append(p)
            rs.append(r)
            break
    return np.array(cs), np.array(rs)


def _thyroid_vessels(rng):
    """Capsular artery and vein on the capsule, dividing into interlobular branches that run down the septa."""
    art, vein = Mesh(), Mesh()
    top = T_TOP + 0.004                  # half sunk into the capsule surface

    def vessel(mesh, pts, r0, r1, ry=1.0, n=50):
        path = smooth_path(np.array(pts, float), n)
        r = np.linspace(r0, r1, len(path))
        mesh.extend(tube(path, r, 16, ry=r * ry))
        return path
    a = vessel(art, [(X1 + 0.004, top, -0.50), (0.80, top + 0.004, -0.40), (0.60, top, -0.24), (0.42, top, -0.02),
                     (0.30, top - 0.012, 0.08)], 0.022, 0.014)
    v = vessel(vein, [(X1 + 0.004, top + 0.004, -0.36), (0.82, top + 0.006, -0.25), (0.64, top, -0.10),
                      (0.50, top, 0.10), (0.36, top - 0.014, 0.22)], 0.031, 0.020, 0.75)
    # side branches that taper and dive through the capsule towards the septa
    for mesh, path, r0, seed in ((art, a, 0.013, 1), (art, a, 0.012, 2), (vein, v, 0.018, 3)):
        rr = np.random.default_rng(seed)
        p0 = path[rr.integers(10, 38)]
        d = np.array([rr.uniform(-0.3, 0.1), 0.0, rr.choice([-1, 1]) * rr.uniform(0.15, 0.25)])
        vessel(mesh, [p0, p0 + d * 0.5 + (0, 0.004, 0), p0 + d + (0, -0.02, 0), p0 + d * 1.2 + (0, -0.06, 0)],
               r0, r0 * 0.55, n=24)
    # interlobular branches along each septum, with a branch climbing to the capsule
    for k, sp in enumerate(SEPTA):
        n = len(sp)
        ya = 0.44 + 0.05 * np.sin(np.linspace(0, 3, n) + k)
        pa = np.stack([sp[:, 0], ya, sp[:, 1]], -1)
        ph = np.linspace(0, 5, n)
        pv = pa + np.stack([0.012 * np.sin(ph), np.full(n, -0.075), 0.012 * np.cos(ph)], -1)
        art.extend(tube(pa, 0.016, 14))
        vein.extend(tube(pv, 0.022, 14, ry=0.017))
        j = int(n * 0.7)
        if sp[j, 0] > _capsule_x(sp[j, 1]):
            up = pa[j] + np.array([(0, 0, 0), (0.01, 0.2, 0.0), (0.0, 0.42, 0.01)])
            art.extend(tube(smooth_path(up, 20), 0.011, 12))
    return art, vein


def build_thyroid():
    parts = []
    rng = np.random.default_rng(21)
    lo, hi = np.array([X0, 0.0, Z0]), np.array([X1, T_TOP, Z1])
    vox = 0.012
    cs, rs = _pack_follicles(rng, lo, hi)
    n = len(cs)
    rots = np.array([_rand_rot(rng) for _ in range(n)])
    axes = np.stack([rng.uniform(0.95, 1.18, n), rng.uniform(0.78, 0.95, n), rng.uniform(0.9, 1.05, n)], -1)
    # epithelial height follows activity: big follicles are resting (low cells), small ones stimulated (tall cells)
    epi_t = np.interp(rs, [0.055, 0.09, 0.14, 0.19], [0.026, 0.019, 0.013, 0.009]) * rng.uniform(0.85, 1.15, n)

    fol = Volume(lo - vox * 2, hi + vox * 2, vox)
    x, y, z = fol.axes()
    grid = np.stack(np.broadcast_arrays(x, y, z), -1).reshape(-1, 3)
    k = 6
    dist, idx = cKDTree(cs).query(grid, k=k, workers=2)
    w = dist - rs[idx]                                   # additively weighted (Apollonius) distance
    order = np.argsort(w, axis=1)
    w_sorted = np.take_along_axis(w, order, 1)
    owner = np.take_along_axis(idx, order[:, :1], 1)[:, 0]
    edge = (w_sorted[:, 1] - w_sorted[:, 0]) / 2
    del dist, w, order, w_sorted
    # ellipsoid of the owning follicle, inflated a little so neighbours press flat faces into one another
    loc = np.einsum("nij,ni->nj", rots[owner], grid - cs[owner])
    R = axes[owner] * (rs[owner, None] * INFLATE)
    ell = (np.linalg.norm(loc / R, axis=1) - 1.0) * R.min(axis=1)
    del loc, grid
    d = -smin(-ell, -(0.009 - edge), 0.02)               # smooth max: ellipsoid clipped by the gap to neighbours
    d = d.reshape(fol.shape).astype(np.float32)
    owner = owner.reshape(fol.shape)
    fol.d = d
    fol.displace(0.004, 7.0, 2, seed=3)
    # the parathyroid corner and the septa are kept clear of follicles
    ax_, ay_, az_ = fol.axes()
    pgrid = np.stack(np.broadcast_arrays(ax_, ay_, az_), -1)
    pt_far = _pt_d(pgrid.reshape(-1, 3), 0.03).reshape(fol.shape).astype(np.float32)
    sep = _septum_edge(*np.broadcast_arrays(ax_[:, 0, :], az_[:, 0, :]))[:, None, :].astype(np.float32)
    np.maximum(fol.d, 0.03 - pt_far, out=fol.d)
    np.maximum(fol.d, 0.022 - np.abs(sep), out=fol.d)

    # the colloid is everything deeper than one epithelial height inside a follicle, measured with a true distance
    # transform so the cell layer keeps its height all round, whatever the follicle's shape
    depth = ndimage.distance_transform_edt(fol.d < 0).astype(np.float32) * vox
    t_own = epi_t[owner].astype(np.float32)
    colloid = fol.copy(np.maximum(np.where(fol.d < 0, t_own - depth, t_own + fol.d), -0.04))
    del t_own
    del depth
    samp_col = _sampler(colloid)
    samp_fol = _sampler(fol)
    # resorption vacuoles: bubbles where the colloid meets the apical surface, many in small active follicles
    vac_mesh = Mesh()
    vac_c, vac_r = [], []
    for i in range(n):
        m = int(np.interp(rs[i], [0.055, 0.1, 0.16], [12, 5, 0]) * rng.uniform(0.6, 1.2))
        if m <= 0:
            continue
        dirs = _fibonacci(m * 2, rng)[:m]
        hit = _ray_hits(samp_col, cs[i], dirs, rs[i] * 1.6)
        for dv, h in zip(dirs, hit):
            p = cs[i] + dv * (h - 0.002)
            r = min(epi_t[i] * 0.75, rng.uniform(0.010, 0.016))
            if _inside_box(p, lo + 0.02, hi - 0.02):
                vac_c.append(p)
                vac_r.append(r)
                vac_mesh.extend(ellipsoid_mesh(p, (r, r * 0.8, r), 5, rotation=frame_from_normal(dv)))
    for p, r in zip(vac_c, vac_r):
        colloid.add(ellipsoid(p, (r * 1.15, r * 0.95, r * 1.15)), "subtract")

    # C cells: in the follicle wall on the basal lamina (never touching the colloid), and a few between follicles
    cc = Mesh()
    for i in range(n):
        if rng.random() > 0.45:
            continue
        for dv in _fibonacci(3, rng)[:rng.integers(1, 3)]:
            h = float(_ray_hits(samp_fol, cs[i], dv[None], rs[i] * 1.6)[0])
            p = cs[i] + dv * (h - 0.008)
            if _inside_box(p, lo + 0.03, hi - 0.02):
                cc.extend(ellipsoid_mesh(p, (0.024, 0.013, 0.018), 8, rotation=frame_from_normal(dv) @ _yrot(rng)))
    gaps = np.argwhere((fol.d > 0.006) & (fol.d < 0.03) & (pt_far > 0.05) & (np.abs(sep) > 0.05))
    for g in gaps[rng.choice(len(gaps), 18, replace=False)]:
        p = fol.lo + g * vox
        if p[1] > T_STROMA_TOP - 0.05 or not _inside_box(p, lo + 0.05, hi - 0.05):
            continue
        for _ in range(3):
            cc.extend(ellipsoid_mesh(p + rng.normal(scale=0.014, size=3), (0.017, 0.014, 0.015), 8))

    # capillary basket round each follicle: an irregular net laid on its surface. Dense where the follicle is
    # exposed above the dissected stroma, sparser (and only near the default cut planes) inside the block
    caps = Mesh()
    for i in range(n):
        exposed = cs[i][1] + rs[i] > T_STROMA_TOP + 0.02 and cs[i][0] < _capsule_x(cs[i][2]) - 0.05
        near_cut = (min(abs(cs[i][0]), abs(cs[i][2])) < rs[i] + 0.05 and cs[i][0] < 0.05 and cs[i][2] > -0.05)
        if not (exposed or near_cut):
            continue
        m = 30 if exposed else 9
        dirs = _fibonacci(m, rng) + rng.normal(scale=0.22 if exposed else 0.15, size=(m, 3))
        dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
        hull = ConvexHull(dirs)
        edges = set()
        for s_ in hull.simplices:
            for a, b in ((s_[0], s_[1]), (s_[1], s_[2]), (s_[2], s_[0])):
                edges.add((min(a, b), max(a, b)))
        for a, b in edges:
            arc = _slerp(dirs[a], dirs[b], 7)
            mid = np.sin(np.linspace(0, math.pi, 7))[:, None]
            arc = arc + mid * rng.normal(scale=0.05, size=3)
            arc /= np.linalg.norm(arc, axis=1, keepdims=True)
            r_cap = rng.uniform(0.0045, 0.006) if exposed else rng.uniform(0.005, 0.0065)
            h = _ray_hits(samp_fol, cs[i], arc, rs[i] * 1.6)
            pts = cs[i] + arc * (h + r_cap * 0.7)[:, None]
            if not _inside_box(pts, lo + (0.03, 0.03, 0.03), hi + np.array([-0.03, 0.05, -0.03])).all():
                continue
            if (_pt_d(pts) < 0.04).any():
                continue
            caps.extend(tube(pts, r_cap, 5, caps=True))

    fol.intersect_box(lo + 0.012, hi - np.array([0.012, 0.0, 0.012]))
    colloid.intersect_box(lo + 0.012, hi - np.array([0.012, 0.0, 0.012]))
    # the epithelium is solid except within a short distance of the block faces, where it is hollowed out round the
    # colloid: follicles sectioned by a face then show a disc of colloid in a ring of cells, while deeper down the
    # colloid simply nests inside a solid follicle (half the surfaces, and cut-away caps stay correct)
    fx, fy, fz = fol.axes()
    to_face = np.minimum(np.minimum(np.minimum(fx - lo[0], hi[0] - fx), np.minimum(fz - lo[2], hi[2] - fz)),
                         fy - lo[1])
    samp_full = _sampler(fol.copy())                     # the solid follicles, which the stroma is carved around
    hollow = np.maximum(colloid.d - 0.002, (to_face - 0.04).astype(np.float32))
    np.maximum(fol.d, -hollow, out=fol.d)
    del hollow, to_face
    epi_mesh = fol.mesh(0.8)
    epi_mesh = relief(epi_mesh, cell_relief(0.034, 0.006, seed=7, groove=0.3, dome=0.55))
    parts.append(mesh_part(epi_mesh, "Follicular epithelium", "Thyroid follicles", "#b8739a", THYROID["follicular"],
                           "gland", rank=0, detail=(0.08, 150.0, 0.95, 0)))
    parts.append(sdf_part(colloid, "Colloid", "Thyroid follicles", "#eba27c", THYROID["colloid"], "mucosa",
                          smooth=0.9, rank=0, step=2, detail=(0.05, 0.0, 0.0, 0)))
    parts.append(mesh_part(vac_mesh, "Resorption vacuoles", "Thyroid follicles", "#f7ecd6", THYROID["vacuoles"],
                           "other", rank=0.2, detail=(0.02, 0.0, 0.0, 0)))
    parts.append(mesh_part(cc, "Parafollicular C cells", "Thyroid follicles", "#8fc9e6", THYROID["c_cells"], "gland",
                           rank=0.5, detail=(0.05, 60.0, 0.9, 0)))
    parts.append(mesh_part(caps, "Perifollicular capillaries", "Vessels", "#cf3b34", THYROID["caps"], "artery",
                           rank=0.3))

    # connective tissue: the complement of the follicles, lowered in front to expose them, under a capsule behind
    ct = Volume(lo, hi + np.array([0, 0.02, 0]), vox)
    cx, cy, cz = ct.axes()
    X2, Z2 = np.broadcast_arrays(cx[:, 0, :], cz[:, 0, :])
    under_caps = (X2 > _capsule_x(Z2)).astype(np.float32)
    lift = np.clip((X2 - _capsule_x(Z2) + 0.04) / 0.04, 0.0, 1.0)
    stroma_top = (T_STROMA_TOP + 0.012 * fbm3(X2 * 6, 0.3, Z2 * 6, 1.0, 3, 5)) * (1 - lift) + T_CAPS_BOT * lift
    ct.d = np.maximum(cy - stroma_top[:, None, :], box_shape((lo + hi) / 2, (hi - lo) / 2 - 0.012)[0](cx, cy, cz))
    ct.d = ct.d.astype(np.float32)
    ct_grid = np.stack(np.broadcast_arrays(cx, cy, cz), -1).reshape(-1, 3)
    fd = samp_full(ct_grid).reshape(ct.shape).astype(np.float32)
    np.maximum(ct.d, -(fd - 0.006), out=ct.d)
    pd = _pt_d(ct_grid, 0.03).reshape(ct.shape).astype(np.float32)
    np.maximum(ct.d, -pd, out=ct.d)
    sep_ct = np.abs(_septum_edge(X2, Z2))[:, None, :].astype(np.float32)
    in_sep = sep_ct - 0.02                                 # negative inside a septum
    stroma = ct.copy(np.maximum(ct.d, -in_sep))
    septa = ct.copy(np.maximum(ct.d, in_sep))
    parts.append(sdf_part(stroma, "Interfollicular connective tissue", "Capsule & stroma", "#e9cdb6",
                          THYROID["stroma"], "fascia", smooth=0.8, bulk=True, rank=-1, step=1,
                          detail=(0.12, 60.0, 0.2, 0)))
    parts.append(sdf_part(septa, "Interlobular septa", "Capsule & stroma", "#dcbf9c", THYROID["septa"], "ligament",
                          smooth=0.7, rank=-1, step=2, detail=(0.12, 55.0, 0.15, 2)))
    del ct_grid, fd, pd

    # capsule: a fibrous sheet over the back of the block, its free edge peeled back from the front
    cap = Volume((X0, T_CAPS_BOT - 0.03, Z0), (X1, T_TOP + 0.03, Z1), 0.008)
    kx, ky, kz = cap.axes()
    top_s = T_TOP + 0.006 * fbm3(kx * 9, 0.1, kz * 9, 1.0, 3, 12)
    top_s = top_s - 0.035 * np.clip(1.0 - (kx - _capsule_x(kz)) / 0.12, 0.0, 1.0) ** 2     # thinning free edge
    cap.d = np.maximum(np.maximum(ky - top_s, T_CAPS_BOT + 0.002 - ky), (_capsule_x(kz) - kx) * 0.9)
    cap.d = cap.d.astype(np.float32)
    cap.displace(0.0025, 30.0, 2, seed=8)
    cap.intersect_box((X0, 0, Z0), (X1, 2, Z1))
    cap_mesh = relief(cap.mesh(0.8), fibre_relief(0.004, 60.0, 8.0, seed=9, axis=0))
    parts.append(mesh_part(cap_mesh, "Capsule", "Capsule & stroma", "#dac5a3", THYROID["capsule"], "ligament",
                           rank=1, detail=(0.12, 55.0, 0.15, 1)))
    art, vein = _thyroid_vessels(rng)
    parts.append(mesh_part(art, "Arteries (capsular & interlobular)", "Vessels", "#c8322c", THYROID["artery"],
                           "artery", rank=1))
    parts.append(mesh_part(vein, "Veins (capsular & interlobular)", "Vessels", "#5f5aa8", THYROID["vein"], "vein",
                           rank=1))
    parts += _parathyroid(rng)
    return settle(_merged(parts), seed=404, amp_xz=0.024, amp_y=0.040, freq=1.5, grain=0.004)


def _yrot(rng):
    a = rng.uniform(0, 2 * math.pi)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _parathyroid(rng):
    """A parathyroid gland tucked into the posterior corner: capsule, cords of chief cells round a capillary net,
    nests of oxyphil cells and adipocytes."""
    parts = []
    lo = np.maximum(PT_C - PT_R - 0.04, (X0, 0.0, Z0))
    hi = np.minimum(PT_C + PT_R + 0.04, (X1, T_TOP, Z1))
    vox = 0.009
    v = Volume(lo, hi, vox)
    x, y, z = v.axes()
    g = np.stack(np.broadcast_arrays(x, y, z), -1).reshape(-1, 3)
    outer = _pt_d(g, 0.022).reshape(v.shape).astype(np.float32)
    inner = _pt_d(g, 0.0).reshape(v.shape).astype(np.float32)
    del g
    box_d = box_shape(((X0 + X1) / 2, T_TOP / 2, 0.0),
                      ((X1 - X0) / 2 - 0.006, T_TOP / 2 - 0.006, (Z1 - Z0) / 2 - 0.006))
    bd = box_d[0](x, y, z).astype(np.float32)
    capsule = v.copy(np.maximum(np.maximum(outer, -inner), bd))
    parts.append(sdf_part(capsule, "Parathyroid capsule", "Parathyroid gland", "#d7c09c", THYROID["pt_capsule"],
                          "ligament", smooth=0.7, rank=0.5, detail=(0.12, 55.0, 0.15, 0)))

    def inside(p, m):
        return _pt_d(p) < -m and _inside_box(p, (X0, 0.0, Z0), (X1, T_TOP, Z1), 0.0)
    # adipocytes
    fat_c, fat_r = [], []
    seeds = [np.array([X1 - 0.02, 0.24, 0.30]), np.array([0.62, 0.36, Z1 - 0.03])]
    for k in range(400):
        p = seeds[k] if k < len(seeds) else PT_C + rng.uniform(-1, 1, 3) * PT_R
        r = rng.uniform(0.035, 0.055)
        if not inside(p, r * 0.5) or len(fat_c) >= 9:
            continue
        if fat_c and (np.linalg.norm(np.array(fat_c) - p, axis=1) - np.array(fat_r) < r + 0.02).any():
            continue
        fat_c.append(p)
        fat_r.append(r)
    fat = Volume(lo, hi, vox)
    for p, r in zip(fat_c, fat_r):
        fat.add(ellipsoid(p, (r, r * 0.9, r * 1.05)), "smooth", 0.01)
    # oxyphil nests
    oxy = Volume(lo, hi, vox)
    ox_c = []
    seeds = [np.array([X1 - 0.03, 0.40, 0.46]), np.array([0.78, 0.20, Z1 - 0.03]), np.array([0.50, 0.30, Z1 - 0.1])]
    for k in range(200):
        p = seeds[k] if k < len(seeds) else PT_C + rng.uniform(-1, 1, 3) * PT_R * 0.9
        if not inside(p, 0.05) or len(ox_c) >= 5:
            continue
        if fat_c and (np.linalg.norm(np.array(fat_c) - p, axis=1) - np.array(fat_r) < 0.06).any():
            continue
        if ox_c and (np.linalg.norm(np.array(ox_c) - p, axis=1) < 0.14).any():
            continue
        ox_c.append(p)
        oxy.add_all(blob_cluster(p, 14, 0.021, (0.06, 0.05, 0.06), seed=int(rng.integers(1e6))), "smooth", 0.004)
    # capillary network: Delaunay edges of well-spread points inside the gland
    pts = [p for p in jittered_bcc(lo, hi, 0.105, 0.2, seed=31) if inside(p, 0.0)]
    pts = np.array(pts)
    cap_m = Mesh()
    tri = Delaunay(pts)
    seen = set()
    for s in tri.simplices:
        for a in range(4):
            for b in range(a + 1, 4):
                e = (min(s[a], s[b]), max(s[a], s[b]))
                if e in seen:
                    continue
                seen.add(e)
                pa, pb = pts[e[0]], pts[e[1]]
                if np.linalg.norm(pa - pb) > 0.1:
                    continue
                mid = (pa + pb) / 2 + rng.normal(scale=0.01, size=3)
                # capillaries reaching the block faces are flattened into them, so they show in section there
                path = np.clip(smooth_path(np.array([pa, mid, pb]), 6), (X0 + 0.005, 0.005, Z0 + 0.005),
                               (X1 - 0.005, T_TOP, Z1 - 0.005))
                cap_m.extend(tube(path, 0.009, 5))
    # chief cells fill what is left inside the capsule: cords separated by the capillaries
    chief = v.copy(np.maximum(inner + 0.004, bd))
    np.maximum(chief.d, -(fat.d - 0.004), out=chief.d)
    np.maximum(chief.d, -(oxy.d - 0.003), out=chief.d)
    for f in (fat, oxy):
        np.maximum(f.d, inner + 0.004, out=f.d)
        np.maximum(f.d, bd, out=f.d)
    chief_mesh = chief.mesh(0.8)
    oxy_mesh = oxy.mesh(0.7)
    # where the block faces section the gland, its cells show individually: small chief cells, big oxyphils
    s_chief, s_oxy = _sampler(chief), _sampler(oxy)
    for axis, val in ((0, X1), (2, Z1)):
        other = [a for a in (0, 1, 2) if a != axis]
        uv = hex_points((lo[other[0]], lo[other[1]]), (hi[other[0]], hi[other[1]]), 0.021, 0.18,
                        seed=axis + 50)
        p = np.zeros((len(uv), 3))
        p[:, other[0]], p[:, other[1]] = uv[:, 0], uv[:, 1]
        p[:, axis] = val - 0.014
        n_ax = np.zeros(3)
        n_ax[axis] = 1.0
        rot = frame_from_normal(n_ax)
        for q, dc, do in zip(p, s_chief(p), s_oxy(p)):
            c = q.copy()
            c[axis] = val - 0.008
            if do < -0.004 and rng.random() < 0.5:
                oxy_mesh.extend(ellipsoid_mesh(c, (0.017, 0.006, 0.015), 6, rotation=rot @ _yrot(rng)))
            elif dc < -0.004:
                chief_mesh.extend(ellipsoid_mesh(c, (0.0105, 0.005, 0.0095), 5, rotation=rot @ _yrot(rng)))
    parts.append(mesh_part(chief_mesh, "Parathyroid chief cells", "Parathyroid gland", "#8c7cc4", THYROID["chief"],
                           "gland", rank=0.4, detail=(0.10, 180.0, 0.95, 0)))
    parts.append(mesh_part(oxy_mesh, "Oxyphil cells", "Parathyroid gland", "#e47f93", THYROID["oxyphil"], "gland",
                           rank=0.45, detail=(0.08, 110.0, 0.8, 0)))
    parts.append(sdf_part(fat, "Parathyroid adipocytes", "Parathyroid gland", "#f1dc97", THYROID["pt_fat"], "fat",
                          smooth=0.8, rank=0.4))
    parts.append(mesh_part(cap_m, "Parathyroid capillaries", "Parathyroid gland", "#cf3b34", THYROID["pt_caps"],
                           "artery", rank=0.4))
    return parts


# =============================================================================== tongue
TONGUE = {
    "epi": "Stratified squamous epithelium of the dorsum: 15-20 cells thick, with a basal layer on the basement "
           "membrane, a thick spinous (prickle) layer and flattened superficial cells that are partly keratinised "
           "(parakeratinised) between the papillae. There is no submucosa on the dorsum, so the mucosa is bound "
           "firmly to the muscle beneath and does not slide.",
    "lp": "Lamina propria: loose to dense connective tissue with a rich capillary bed. It rises into the epithelium "
          "as primary papillae (the connective tissue cores of the lingual papillae) and, above those, as small "
          "secondary papillae that interlock epithelium and connective tissue. It merges directly with the "
          "connective tissue between the muscle bundles.",
    "filiform": "Filiform papillae: the most numerous papillae, covering the anterior two-thirds of the dorsum in "
                "rows parallel to the sulcus terminalis. Slender cones of epithelium around a small connective "
                "tissue core, with NO taste buds - they are mechanical, giving the tongue its rough, rasp-like "
                "grip on food, and their tips point backwards towards the pharynx. Overgrowth of their keratin "
                "gives 'hairy tongue'; their loss in iron, B12 or folate deficiency gives a smooth, sore, red "
                "atrophic glossitis.",
    "keratin": "Keratinised tips of the filiform papillae: each papilla ends in several hair-like processes of hard, "
               "fully keratinised cells, which is why the filiform papillae look white and give the tongue its "
               "velvety white-grey surface. Retained keratin and debris form the coating of a 'furred' tongue.",
    "fungiform": "Fungiform papillae: mushroom-shaped papillae scattered among the filiform papillae, most numerous "
                 "at the tip and sides of the tongue. Their epithelium is thin and not keratinised, so the vascular "
                 "connective tissue core shows through and they look like red dots. Each carries a few (0-15) "
                 "taste buds on its upper surface, supplied by the chorda tympani (facial nerve, VII).",
    "vallate": "Circumvallate papilla: 8-12 large papillae (1-3 mm across) lying in a V just in front of the sulcus "
               "terminalis. Each is sunk below the surface and surrounded by a circular trench (furrow). Hundreds "
               "of taste buds line its side walls facing the trench; they are supplied by the glossopharyngeal "
               "nerve (IX). The trench is flushed by von Ebner glands, which open into its floor.",
    "foliate": "Foliate papillae: 4-5 parallel vertical folds on the lateral margin of the posterior tongue, "
               "separated by deep clefts. Taste buds line the walls of the clefts, and serous glands open into "
               "their floors. Well developed in children, rudimentary in many adults; the posterior folds are "
               "supplied by the glossopharyngeal nerve. Their lymphoid tissue can be mistaken for a tumour.",
    "taste": "Taste buds: pale, barrel-shaped bodies of 50-100 cells spanning the full thickness of the epithelium, "
             "about 70 µm tall. They contain elongated gustatory and supporting cells (types I-III) and basal stem "
             "cells (type IV), and open onto the surface through a small taste pore. Cells turn over every 10-14 "
             "days. About 5000 taste buds are spread over the vallate, foliate and fungiform papillae, soft palate "
             "and pharynx.",
    "gustatory": "Gustatory (receptor) cells inside the taste bud: type II cells carry G-protein-coupled receptors "
                 "for sweet, bitter and umami and release ATP onto the afferent fibres; type III cells detect sour "
                 "(and some salt) and form true synapses; type I cells are glia-like supporting cells. Their "
                 "microvilli reach the taste pore.",
    "pore": "Taste pores: the openings of the taste buds on the epithelial surface. The microvilli (taste hairs) "
            "of the gustatory cells project into the pore, where dissolved tastants reach their receptors.",
    "ebner": "Von Ebner glands: purely serous lingual glands lying among the muscle bundles beneath the "
             "circumvallate and foliate papillae. Their watery secretion continuously rinses the trenches and "
             "clefts so that new tastants can reach the taste buds, and contains lingual lipase and von Ebner "
             "gland protein (lipocalin), which binds hydrophobic taste molecules.",
    "ebner_ducts": "Ducts of the von Ebner glands, opening into the floor of the circumvallate trench and of the "
                   "foliate clefts.",
    "interstitium": "Perimysium and interstitial fat: connective tissue between the muscle bundles, continuous with "
                    "the lamina propria above, carrying the vessels, nerves and lingual glands.",
    "sup_long": "Superior longitudinal muscle: a sheet of fibres running front to back just beneath the lamina "
                "propria. It shortens the tongue and curls its tip and sides upwards.",
    "inf_long": "Inferior longitudinal muscle: fibres running front to back near the underside of the tongue. It "
                "shortens the tongue and curls its tip downwards.",
    "trans": "Transverse muscle: fibres running from the median septum out to the margins. It narrows and "
             "elongates (and so protrudes) the tongue.",
    "vert": "Vertical muscle: fibres running from the dorsum down to the underside, interlacing with the transverse "
            "fibres in alternating sheets. It flattens and broadens the tongue. All intrinsic muscles are skeletal "
            "muscle supplied by the hypoglossal nerve (XII).",
    "ix": "Glossopharyngeal nerve (IX) branch: taste and general sensation from the posterior third of the tongue, "
          "including the circumvallate papillae, whose walls it reaches through a plexus under the epithelium.",
    "chorda": "Lingual nerve branch carrying chorda tympani fibres: taste from the anterior two-thirds (fungiform "
              "papillae) via the facial nerve (VII), running with general sensation from the mandibular nerve (V3). "
              "A lesion of VII proximal to the chorda (e.g. Bell palsy) abolishes taste on that side.",
    "xii": "Hypoglossal nerve (XII) branch: motor supply to all intrinsic and extrinsic tongue muscles except "
           "palatoglossus. A lesion makes the protruded tongue deviate towards the weak side.",
    "artery": "Lingual artery branch (from the external carotid): runs among the intrinsic muscles and sends "
              "branches up to the capillary loops in the papillae.",
    "vein": "Deep lingual vein: drains the tongue to the internal jugular vein; visible through the thin mucosa of "
            "the underside, which is why sublingual drugs such as glyceryl trinitrate are absorbed so fast.",
}

T_SURF = 0.80                                   # height of the dorsum
T_ZC, T_RM = 0.16, 0.52                         # the dorsum rolls over the lateral margin (z > T_ZC) on this radius
VC, R_V, W_T, T_FLOOR = np.array([-0.45, 0.0]), 0.24, 0.07, 0.64      # circumvallate papilla, trench, trench floor
FUNG = [(0.0, 0.34), (0.42, -0.30), (0.80, 0.02), (-0.04, -0.40)]
R_F = 0.085
FOLIATE_X = [0.24 + 0.115 * k for k in range(7)]
T_EPI = 0.05


def _t_surface(x, z):
    """Dorsal surface height before the lateral roll: a slight noise, and the vallate papilla sits a little low."""
    x, z = np.asarray(x, np.float64), np.asarray(z, np.float64)
    s = T_SURF + 0.006 * fbm3(x * 4.0, 0.2, z * 4.0, 1.0, 3, 21)
    r = np.sqrt((x - VC[0]) ** 2 + (z - VC[1]) ** 2)
    t = np.clip((R_V - r) / 0.03, 0.0, 1.0)
    return s - 0.018 * t * t * (3 - 2 * t)


def _t_top(x, z):
    """Surface height including the rounded lateral margin (analytic, for placing things on the surface)."""
    s = _t_surface(x, z)
    dz = np.maximum(np.asarray(z, np.float64) - T_ZC, 0.0)
    return s - T_RM + np.sqrt(np.maximum(T_RM ** 2 - dz ** 2, 0.0))


def _t_normal(x, z):
    dz = max(float(z) - T_ZC, 0.0)
    y = math.sqrt(max(T_RM ** 2 - dz ** 2, 0.0))
    n = np.array([0.0, y, dz])
    return n / np.linalg.norm(n)


def _t_muscle_top(x, z):
    return np.minimum(0.60, _t_top(x, z) - 0.19)


def _t_body(x, y, z):
    """Signed distance to the mucosal surface: flat dorsum rolling over into the lateral margin."""
    s = _t_surface(x, z)
    dz = z - T_ZC
    yc = s - T_RM
    roll = np.where(y >= yc, np.sqrt(dz * dz + (y - yc) ** 2) - T_RM, dz - T_RM)
    return np.where(dz <= 0, y - s, roll).astype(np.float32)


def _taper(pts, n, r0, r1, segments):
    """Smoothed tube through a few control points whose radius tapers from r0 to r1."""
    path = smooth_path(np.asarray(pts, float), n)
    return tube(path, np.linspace(r0, r1, len(path)), segments)


def _carve(target, vols, gap):
    """Take other solids (grown by `gap`) out of a volume, resampling them only where they overlap it."""
    for v in vols:
        r = target.region(v.lo, v.hi)
        if r is None:
            continue
        sl, (x, y, z) = r
        g = np.stack(np.broadcast_arrays(x, y, z), -1).reshape(-1, 3)
        d = _sampler(v)(g).reshape(target.d[sl].shape).astype(np.float32)
        np.maximum(target.d[sl], -(d - gap), out=target.d[sl])


def _bud(mesh_bud, mesh_cells, mesh_pore, apex, axis, rng, length=0.026, width=0.014):
    """One taste bud: a barrel of cells spanning the epithelium, spindle-shaped gustatory cells inside it, and a
    tuft of microvilli in the taste pore at its apex."""
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    rot = frame_from_normal(axis) @ _yrot(rng)
    c = apex - axis * (length * 0.95)
    mesh_bud.extend(ellipsoid_mesh(c, (width, length, width * 0.9), 9, rotation=rot))
    for k in range(6):
        a = 2 * math.pi * k / 6 + rng.uniform(-0.3, 0.3)
        off = (rot[:, 0] * math.cos(a) + rot[:, 2] * math.sin(a)) * width * rng.uniform(0.25, 0.55)
        mesh_cells.extend(ellipsoid_mesh(c + off * (0.9 if k % 2 else 0.6) + axis * rng.uniform(-0.004, 0.006),
                                         (0.004, length * 0.82, 0.004), 5,
                                         rotation=frame_from_normal(axis + off * 3.0)))
    for k in range(4):
        tip = apex + axis * 0.004 + rng.normal(scale=0.0025, size=3)
        mesh_pore.extend(tube(np.array([apex - axis * 0.01, tip]), np.array([0.0018, 0.0008]), 5))


def build_tongue():
    parts = []
    rng = np.random.default_rng(5)
    lo, hi = np.array([X0, 0.33, Z0]), np.array([X1, 1.0, Z1])
    vox = 0.0065
    body = Volume(lo, hi, vox)
    x, y, z = body.axes()
    body.d = _t_body(x, y, z)
    rr = np.sqrt((x - VC[0]) ** 2 + (z - VC[1]) ** 2)
    # circumvallate trench: an annular moat whose floor sits well below the surface
    trench = np.maximum(np.abs(rr - (R_V + W_T / 2)) - W_T / 2, T_FLOOR - y).astype(np.float32)
    body.apply(trench, (slice(None),) * 3, "smooth_subtract", 0.016)
    # secondary papillae dimple the flat top of the vallate papilla
    tops = poisson_disk(VC - R_V * 0.85, VC + R_V * 0.85, 0.045, seed=8)
    for px, pz in tops:
        if math.hypot(px - VC[0], pz - VC[1]) < R_V - 0.04:
            body.add(ellipsoid((px, T_SURF - 0.018, pz), (0.022, 0.009, 0.022)), "smooth", 0.01)
    # foliate papillae: deep vertical clefts across the lateral margin separate the leaf-like folds
    for fx in FOLIATE_X:
        cleft = (lambda X, Y, Z, fx=fx: np.maximum(np.maximum(np.abs(X - fx) - 0.011, -_t_body(X, Y, Z) - 0.13),
                                                   0.30 - Z),
                 np.array([fx - 0.03, 0.33, 0.25]), np.array([fx + 0.03, 1.0, 0.65]))
        body.add(cleft, "smooth_subtract", 0.008)
    # fungiform papillae: a stalk and an overhanging, mushroom-like cap
    for fx, fz in FUNG:
        ys = float(_t_top(fx, fz))
        body.add(round_cone((fx, ys - 0.03, fz), (fx, ys + 0.05, fz), 0.058, 0.066), "smooth", 0.022)
        body.add(ellipsoid((fx, ys + 0.062, fz), (R_F, 0.042, R_F)), "smooth", 0.018)
    # taste pores: tiny pits where each taste bud reaches the surface
    buds = []                                                   # (apex, axis, where)
    for k in range(30):
        a = 2 * math.pi * k / 30
        n = np.array([math.cos(a), 0.0, math.sin(a)])
        for j, yy in enumerate((0.705, 0.745)):
            aa = a + (math.pi / 30 if j else 0.0)
            nn = np.array([math.cos(aa), 0.0, math.sin(aa)])
            buds.append((np.array([VC[0], yy, VC[1]]) + nn * (R_V - 0.004), nn, "vallate"))
        if k % 3 == 0:
            buds.append((np.array([VC[0], 0.715, VC[1]]) + n * (R_V + W_T + 0.004), -n, "vallate"))
    for fx, fz in FUNG:
        ys = float(_t_top(fx, fz)) + 0.104
        for k in range(4):
            a = 2 * math.pi * k / 4 + rng.uniform(-0.3, 0.3)
            off = np.array([math.cos(a), 0.0, math.sin(a)]) * 0.042
            n = np.array([off[0] * 6, 1.0, off[2] * 6])
            buds.append((np.array([fx, ys - 0.006, fz]) + off, n / np.linalg.norm(n), "fungiform"))
    for fx in FOLIATE_X:
        for side in (-1, 1):
            for zz in (0.40, 0.49):
                yy = float(_t_top(fx, zz)) - 0.06
                buds.append((np.array([fx + side * 0.011, yy, zz]), np.array([-side, 0.0, 0.0]), "foliate"))
    for apex, axis, _ in buds:
        body.add(sphere_shape(apex + axis * 0.003, 0.009), "smooth_subtract", 0.003)

    # lamina propria top: an offset of the surface, raised into small secondary papillae under the epithelium
    t_epi = np.full(body.shape, T_EPI, np.float32)
    for fx, fz in FUNG:                                         # thin epithelium over the fungiform papillae
        rf = np.sqrt((x - fx) ** 2 + (z - fz) ** 2)
        np.minimum(t_epi, np.broadcast_to(0.028 + 0.022 * np.clip((rf - R_F) / 0.04, 0, 1), body.shape), out=t_epi)
    lp_top = body.copy(body.d + t_epi)
    del t_epi
    fil_pts = []
    # filiform papillae stand in rows parallel to the sulcus terminalis: a V whose apex points backwards
    cand = []
    for u in np.arange(-1.6, 1.1, 0.054):
        zs_ = np.arange(Z0 + 0.03, Z1, 0.045)
        cand += [(u + 0.55 * abs(zz) + rng.uniform(-0.009, 0.009), zz + rng.uniform(-0.008, 0.008)) for zz in zs_]
    for px, pz in cand:
        if not (X0 + 0.03 < px < X1 - 0.03):
            continue
        if math.hypot(px - VC[0], pz - VC[1]) < R_V + W_T + 0.05:
            continue
        if any(math.hypot(px - fx, pz - fz) < R_F + 0.05 for fx, fz in FUNG):
            continue
        if pz > 0.26 and FOLIATE_X[0] - 0.08 < px < FOLIATE_X[-1] + 0.08:
            continue
        if pz > 0.5:
            continue
        fil_pts.append((px, pz))
    for px, pz in fil_pts:
        n = _t_normal(px, pz)
        b = np.array([px, float(_t_top(px, pz)), pz])
        lp_top.add(round_cone(b - n * 0.055, b - n * 0.018, 0.022, 0.009), "smooth", 0.012)
    mt = _t_muscle_top(x, z).astype(np.float32)
    epi = body.copy(np.maximum(body.d, -lp_top.d))
    lp = lp_top.copy(np.maximum(lp_top.d, mt - y))
    for v in (epi, lp):                     # trim to the block only now, or its sides would grow an epithelium
        v.intersect_box((X0, -1.0, Z0), (X1, 2.0, Z1))

    # von Ebner glands (under the vallate trench and the foliate clefts) and their ducts
    glv = Volume((VC[0] - 0.42, 0.30, VC[1] - 0.42), (VC[0] + 0.42, 0.70, VC[1] + 0.42), 0.0055)
    duv = Volume((VC[0] - 0.42, 0.30, VC[1] - 0.42), (VC[0] + 0.42, 0.70, VC[1] + 0.42), 0.0055)
    gland_c = []
    for i, a in enumerate(np.linspace(0, 2 * math.pi, 7, endpoint=False) + 0.3):
        r0 = R_V + W_T / 2
        c = np.array([VC[0] + r0 * math.cos(a), 0.47 + 0.03 * math.sin(3 * a), VC[1] + r0 * math.sin(a)])
        glv.add_all(blob_cluster(c, 40, 0.024, (0.085, 0.055, 0.085), seed=30 + i), "smooth", 0.007)
        gland_c.append(c)
        top = np.array([VC[0] + r0 * math.cos(a + 0.1), T_FLOOR - 0.005, VC[1] + r0 * math.sin(a + 0.1)])
        duv.tube(smooth_path(np.array([c, c + (0, 0.07, 0), top - (0, 0.05, 0), top]), 16), 0.0085)
    glf = Volume((0.2, 0.2, 0.22), (1.0, 0.62, Z1), 0.0055)
    duf = Volume((0.2, 0.2, 0.22), (1.0, 0.62, Z1), 0.0055)
    for k, fx in enumerate(FOLIATE_X[1:-1:2]):
        c = np.array([fx + 0.05, 0.30, 0.40])
        glf.add_all(blob_cluster(c, 26, 0.023, (0.08, 0.05, 0.065), seed=60 + k), "smooth", 0.007)
        gland_c.append(c)
        top = np.array([fx, float(_t_top(fx, 0.45)) - 0.125, 0.45])
        duf.tube(smooth_path(np.array([c, c + (0, 0.07, 0.02), top - (0, 0.04, 0), top]), 16), 0.008)
    for v in (glv, glf):
        v.displace(0.0015, 50.0, 2, seed=4)
    gland_vols = [glv, duv, glf, duf]
    _carve(lp, gland_vols, 0.003)
    _carve(epi, [duv, duf], 0.002)

    # split the epithelium into the named papillae and the rest of the dorsum
    fung_d = np.full(epi.shape, 1e3, np.float32)
    for fx, fz in FUNG:
        ys = float(_t_top(fx, fz))
        fung_d = np.minimum(fung_d, np.maximum(np.sqrt((x - fx) ** 2 + (z - fz) ** 2) - (R_F + 0.018),
                                               ys - 0.012 - y).astype(np.float32))
    vall_d = np.broadcast_to(np.maximum(rr - (R_V + 0.004), T_FLOOR + 0.004 - y), epi.shape).astype(np.float32)
    fol_d = np.broadcast_to(np.maximum(np.maximum(FOLIATE_X[0] - 0.07 - x, x - FOLIATE_X[-1] - 0.07),
                                       0.27 - z), epi.shape).astype(np.float32)
    regions = [("Fungiform papillae", fung_d, TONGUE["fungiform"], "#e58c8f"),
               ("Circumvallate papilla", vall_d, TONGUE["vallate"], "#e6a3a6"),
               ("Foliate papillae", fol_d, TONGUE["foliate"], "#e19b9d")]
    rest = epi.d.copy()
    for name, rd, desc, col in regions:
        part = epi.copy(np.maximum(epi.d, rd))
        np.maximum(rest, -rd, out=rest)
        m = relief(part.mesh(0.8), cell_relief(0.024, 0.0035, seed=11, groove=0.3, dome=0.5))
        parts.append(mesh_part(m, name, "Papillae", col, desc, "mucosa", rank=1, detail=(0.08, 140.0, 0.8, 0)))
    epi.d = rest
    del fung_d, vall_d, fol_d, rest
    m = relief(epi.mesh(0.8), cell_relief(0.026, 0.0035, seed=12, groove=0.3, dome=0.5))
    parts.insert(0, mesh_part(m, "Stratified squamous epithelium", "Mucosa", "#e8b9bb", TONGUE["epi"], "mucosa",
                              rank=1, detail=(0.08, 140.0, 0.8, 0)))
    parts.insert(1, sdf_part(lp, "Lamina propria", "Mucosa", "#e8a595", TONGUE["lp"], "mucosa", smooth=0.8,
                             rank=0.5, bulk=True, step=2, detail=(0.12, 100.0, 0.3, 0)))
    parts.append(mesh_part(glv.mesh(0.7).extend(glf.mesh(0.7)), "Von Ebner glands", "Glands", "#aac8e6",
                           TONGUE["ebner"], "gland", rank=-2, detail=(0.08, 140.0, 0.9, 0)))
    parts.append(mesh_part(duv.mesh(0.6).extend(duf.mesh(0.6)), "Von Ebner ducts", "Glands", "#7fa8d4",
                           TONGUE["ebner_ducts"], "gland", rank=-1))

    # filiform papillae: backward-leaning cones of epithelium ending in a crown of keratinised spines
    fil, ker = Mesh(), Mesh()
    back = np.array([-1.0, 0.0, 0.0])
    for px, pz in fil_pts:
        n = _t_normal(px, pz)
        b = np.array([px, float(_t_top(px, pz)), pz])
        h = rng.uniform(0.065, 0.092)
        d = n + back * rng.uniform(0.30, 0.45) + np.array([0, 0, rng.uniform(-0.12, 0.12)])
        d /= np.linalg.norm(d)
        pts = np.array([b - n * 0.012, b + n * h * 0.25 + d * h * 0.05, b + d * h * 0.62, b + d * h])
        fil.extend(_taper(pts, 8, 0.026, 0.011, 9))
        tip = b + d * h
        for k in range(rng.integers(2, 4)):
            sd = d + rng.normal(scale=0.2, size=3) + back * 0.25
            sd /= np.linalg.norm(sd)
            L = rng.uniform(0.035, 0.055)
            ker.extend(_taper([tip - d * 0.012, tip + sd * L * 0.5, tip + sd * L], 6, 0.0085, 0.0015, 6))
    parts.append(mesh_part(fil, "Filiform papillae", "Papillae", "#ecc8c6", TONGUE["filiform"], "mucosa", rank=1.2,
                           detail=(0.08, 140.0, 0.6, 2)))
    parts.append(mesh_part(ker, "Keratinised tips (filiform)", "Papillae", "#f2ece0", TONGUE["keratin"], "skin",
                           rank=1.4, detail=(0.05, 60.0, 0.05, 2)))

    bud_m, cell_m, pore_m = Mesh(), Mesh(), Mesh()
    for apex, axis, _ in buds:
        _bud(bud_m, cell_m, pore_m, apex, axis, rng)
    parts.append(mesh_part(bud_m, "Taste buds", "Taste buds", "#f1dd8a", TONGUE["taste"], "gland", rank=1.1,
                           detail=(0.05, 180.0, 0.9, 2)))
    parts.append(mesh_part(cell_m, "Gustatory receptor cells", "Taste buds", "#c9a13a", TONGUE["gustatory"],
                           "gland", rank=1.1, detail=(0.05, 200.0, 0.95, 2)))
    parts.append(mesh_part(pore_m, "Taste pores & microvilli", "Taste buds", "#8a5a2a", TONGUE["pore"], "gland",
                           rank=1.3))
    parts += _tongue_muscle(rng, gland_vols, np.array(gland_c))
    parts += _tongue_nerves(rng)
    return settle(_merged(parts), seed=405, amp_xz=0.022, amp_y=0.040, freq=1.5, grain=0.004)


def _tongue_muscle(rng, gland_vols, gland_c):
    """Intrinsic muscle in three planes: superior and inferior longitudinal sheets, and between them alternating
    sheets of transverse and vertical bundles. The perimysium is what is left between the bundles."""
    lo, hi = np.array([X0, 0.03, Z0]), np.array([X1, 0.62, Z1])
    inter = Volume(lo, hi, 0.009)
    sl, il, tr, ve = Mesh(), Mesh(), Mesh(), Mesh()

    def bundle(mesh, pts, r, ry):
        path = smooth_path(np.asarray(pts, float), max(12, len(pts)))
        rad = r * (0.85 + 0.15 * np.sin(np.linspace(0, math.pi, len(path))) ** 0.3)
        mesh.extend(tube(path, rad, 12, ry=rad * ry / r))
        inter.tube(path[::2] if len(path) > 8 else path, r * 1.06 + 0.004)

    def runs(pts, r, mesh, ry, min_len=5):
        """Lay a bundle along pts, broken where it would run through a lingual gland."""
        free = np.array([np.min(np.linalg.norm(gland_c - p, axis=1)) > r + 0.075 for p in pts])
        start = None
        for i, f in enumerate(np.append(free, False)):
            if f and start is None:
                start = i
            elif not f and start is not None:
                if i - start >= min_len:
                    bundle(mesh, pts[start:i], r, ry)
                start = None
    e = 0.002                                  # bundles end flush with the block faces
    xs = np.linspace(X0 + e, X1 - e, 28)
    for zb in np.arange(Z0 + 0.036, Z1, 0.07):
        ph = rng.uniform(0, 6.3)
        zz = zb + 0.010 * np.sin(xs * 3.1 + ph)
        top = np.array([float(_t_muscle_top(0.0, zi)) for zi in zz])
        bundle(sl, np.stack([xs, top - 0.046 + 0.006 * np.sin(xs * 4 + ph), zz], -1), 0.036, 0.026)
        bundle(il, np.stack([xs, 0.058 + 0.004 * np.sin(xs * 3 + ph), np.clip(zz + 0.02, Z0 + e, Z1 - e)], -1),
               0.036, 0.025)
    zs = np.linspace(Z0 + e, Z1 - e, 26)
    sheet = 0.13
    for xb in np.arange(X0 + 0.035, X1, sheet):
        for yb in (0.15, 0.232, 0.314, 0.396, 0.478):
            ph = rng.uniform(0, 6.3)
            xx = xb + 0.009 * np.sin(zs * 3.7 + ph)
            yy = yb + 0.007 * np.sin(zs * 2.9 + ph)
            ok = yy + 0.085 < np.array([float(_t_muscle_top(xb, zi)) for zi in zs])
            if not ok[0] or ok.sum() < 6:
                continue
            k = int(np.argmax(~ok)) if not ok.all() else len(zs)
            runs(np.stack([xx, yy, zs], -1)[:max(k, 6)], 0.034, tr, 0.038)
        xv = xb + sheet / 2
        if xv > X1 - 0.02:
            continue
        for zb in np.arange(Z0 + 0.04, Z1 - 0.02, 0.078):
            zb2 = zb + rng.uniform(-0.012, 0.012)
            ytop = float(_t_muscle_top(xv, zb2)) - 0.09
            ys = np.linspace(0.11, ytop, 9)
            pts = np.stack([xv + 0.008 * np.sin(ys * 9 + zb * 7), ys, zb2 + 0.008 * np.cos(ys * 8 + xb * 5)], -1)
            runs(pts, 0.027, ve, 0.024, 4)
    ix, iy, iz = inter.axes()
    mt = _t_muscle_top(ix, iz).astype(np.float32)
    box_d = box_shape((lo + hi) / 2, (hi - lo) / 2 - 0.004)[0](ix, iy, iz)
    inter.d = np.maximum(np.maximum(box_d, iy - mt), -inter.d).astype(np.float32)
    _carve(inter, gland_vols, 0.004)
    parts = [sdf_part(inter, "Perimysium & interstitial fat", "Intrinsic muscle", "#d8ab94", TONGUE["interstitium"],
                      "fascia", smooth=0.8, bulk=True, rank=-3, step=2, detail=(0.12, 60.0, 0.2, 0))]
    for mesh, name, key, col, ax, det in ((sl, "Superior longitudinal muscle", "sup_long", "#c25a50", 0, 1),
                                          (tr, "Transverse muscle", "trans", "#a8453d", 2, 3),
                                          (ve, "Vertical muscle", "vert", "#b54f46", 1, 2),
                                          (il, "Inferior longitudinal muscle", "inf_long", "#bb554b", 0, 1)):
        mesh = relief(mesh, fibre_relief(0.0035, 70.0, 5.0, seed=ax + 3, axis=ax))
        parts.append(mesh_part(mesh, name, "Intrinsic muscle", col, TONGUE[key], "muscle", rank=-3,
                               detail=(0.06, 90.0, 0.4, det)))
    return parts


def _tongue_nerves(rng):
    ix_n, ch, xii, art, vein = Mesh(), Mesh(), Mesh(), Mesh(), Mesh()
    # IX climbs to the vallate papilla and fans out under the epithelium of its walls
    stem = smooth_path(np.array([(X0 - 0.004, 0.40, -0.30), (-0.75, 0.45, -0.20), (VC[0] - 0.05, 0.56, -0.05),
                                 (VC[0], 0.66, VC[1])]), 40)
    ix_n.extend(tube(stem, 0.021, 14))
    for k in range(6):
        a = 2 * math.pi * k / 6 + 0.4
        end = np.array([VC[0] + (R_V - 0.07) * math.cos(a), 0.715, VC[1] + (R_V - 0.07) * math.sin(a)])
        ix_n.extend(_taper([stem[-1], (stem[-1] + end) / 2 + (0, 0.02, 0), end], 14, 0.011, 0.005, 8))
    # lingual nerve (chorda tympani fibres) to the fungiform papillae
    lstem = smooth_path(np.array([(X1 + 0.004, 0.50, -0.46), (0.6, 0.55, -0.40), (0.1, 0.58, -0.2),
                                  (-0.5, 0.56, -0.45), (-0.86, 0.60, -0.40)]), 50)
    ch.extend(tube(lstem, 0.018, 12))
    for fx, fz in FUNG:
        d = np.linalg.norm(lstem[:, [0, 2]] - (fx, fz), axis=1)
        p0 = lstem[int(np.argmin(d))]
        ys = float(_t_top(fx, fz))
        end = np.array([fx, ys + 0.03, fz])
        ch.extend(_taper([p0, (p0 + end) / 2 + (0, -0.02, 0), end - (0, 0.05, 0), end], 16, 0.011, 0.005, 8))
    xii.extend(tube(wavy_path((X1 + 0.004, 0.24, -0.20), (X0 - 0.004, 0.26, -0.12), 50, 0.02, 1.5, seed=3),
                    0.02, 12))
    art.extend(tube(wavy_path((X1 + 0.004, 0.30, 0.02), (X0 - 0.004, 0.28, -0.02), 60, 0.025, 2.0, seed=2),
                    0.024, 14))
    vein.extend(tube(wavy_path((X1 + 0.004, 0.19, 0.12), (X0 - 0.004, 0.18, 0.08), 60, 0.02, 1.6, seed=7),
                     0.032, 14, ry=0.025))
    return [mesh_part(ix_n, "Glossopharyngeal nerve (IX) branch", "Nerves & vessels", "#f0cf45", TONGUE["ix"],
                      "nerve", rank=-1),
            mesh_part(ch, "Lingual nerve (chorda tympani) branch", "Nerves & vessels", "#e8d77a", TONGUE["chorda"],
                      "nerve", rank=-1),
            mesh_part(xii, "Hypoglossal nerve (XII) branch", "Nerves & vessels", "#d9b83a", TONGUE["xii"], "nerve",
                      rank=-2),
            mesh_part(art, "Lingual artery branch", "Nerves & vessels", "#cf3a31", TONGUE["artery"], "artery",
                      rank=-2),
            mesh_part(vein, "Deep lingual vein", "Nerves & vessels", "#5f5aa8", TONGUE["vein"], "vein", rank=-2)]
