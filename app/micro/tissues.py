"""Cardiac muscle and exocrine/endocrine pancreas, built cell by cell.

Both models are blocks whose every visible face is a section: cells that cross a face of the block are clipped
against it and capped, so the sides read like the cut surface of a specimen while the top (and the teased-out end
of the heart block) stay three-dimensional.

* Cardiac muscle - a transmural block of ventricular wall. Each cardiomyocyte is its own closed mesh with a central
  nucleus in a pale perinuclear cone, joined end to end with its neighbours through stepped intercalated discs.
  Fibres run in laminae whose direction turns through the wall (the helical fibre architecture), branch into their
  neighbours, and are separated by an endomysium full of capillaries. Subendocardial Purkinje fibres run beneath
  the endocardium; the epicardium carries fat, a coronary artery, a cardiac vein and an autonomic nerve.
* Pancreas - lobules separated by septa. Each acinus is a berry of pyramidal cells whose basophilic bases and
  eosinophilic zymogen apices are separate objects, around a lumen holding centroacinar cells; intercalated ducts
  lead to intralobular ducts and on to an interlobular duct in a septum. Islets of Langerhans are packed Voronoi
  polyhedra of beta (core), alpha (mantle) and delta cells threaded by a fenestrated capillary network.
"""
import math

import numpy as np
from scipy.spatial import ConvexHull, Delaunay, SphericalVoronoi, Voronoi, cKDTree

from .cells import extrude, hex_points, inset_polygon, poisson_disk, smooth_polygon
from .geometry import Mesh, ellipsoid as ellipsoid_mesh, smooth_path, tube
from .kit import Bumps, Volume, hlayer, mesh_part, noise2, sdf_part, tube_shell
from .organic import Sweep, cell_relief, lobed, relief_part, rsum, settle, surf_noise, tubule
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


def _spindle(a, b, r, seg=8, n=7):
    """Closed spindle (pointed at both ends) from a to b."""
    s = np.linspace(0.0, 1.0, n)
    path = np.asarray(a) + (np.asarray(b) - np.asarray(a)) * s[:, None]
    return tube(path, np.maximum(r * np.sin(math.pi * s) ** 0.75, r * 0.04), seg)


# ============================================================================================ cardiac muscle
CARD = {
    "myocytes": "Cardiomyocytes (working myocardium): branched, striated cells about 100 µm long and 15–20 µm wide, "
                "joined end to end into a three-dimensional network (a functional syncytium). Each has one, "
                "sometimes two, central nuclei. The sarcomeres give cross-striations like skeletal muscle, but "
                "the myofibrils are less regular and split around the nucleus, and mitochondria fill about a third "
                "of the cell – the heart cannot run up an oxygen debt. Cardiomyocytes are essentially "
                "post-mitotic: dead cells are replaced by scar, not new muscle.",
    "discs": "Intercalated discs: the stepped end-to-end junctions between cardiomyocytes, seen as dark lines that "
             "jog across the fibre. The transverse risers carry fasciae adherentes (anchoring actin filaments of the "
             "terminal sarcomere) and desmosomes (tying desmin intermediate filaments together); the longitudinal "
             "treads carry gap junctions (connexin 43) that pass the action potential from cell to cell. "
             "Desmosomal gene mutations cause arrhythmogenic cardiomyopathy.",
    "nuclei": "Cardiomyocyte nuclei: single (about a quarter of cells are binucleate), oval and central, lying in "
              "the axis of the fibre – unlike the peripheral nuclei of skeletal muscle. In hypertrophy they enlarge "
              "and become hyperchromatic and rectangular ('boxcar' nuclei).",
    "halo": "Perinuclear clear zone: the cone of sarcoplasm at each pole of the nucleus where the myofibrils part. "
            "It holds mitochondria, Golgi, glycogen and golden-brown lipofuscin 'wear-and-tear' pigment that "
            "accumulates with age. In atrial myocytes it also contains the granules of atrial natriuretic peptide.",
    "endomysium": "Endomysium and perimysium (interstitium): delicate reticular and collagen fibres around each "
                  "cardiomyocyte and between the laminae (sheets) of fibres, with fibroblasts, capillaries and "
                  "lymphatics. The sheet architecture lets the laminae slide during contraction; after infarction "
                  "or in chronic pressure overload fibroblasts lay down interstitial fibrosis that stiffens the wall "
                  "(diastolic dysfunction).",
    "caps": "Endomysial capillaries: continuous capillaries running parallel to the fibres, about one per "
            "cardiomyocyte – the densest capillary bed of any muscle. They fill mostly in diastole, when the "
            "contracting wall stops squeezing them, which is why tachycardia (shorter diastole) and a raised "
            "ventricular diastolic pressure starve the subendocardium first.",
    "arteriole": "Intramyocardial arteriole: a branch of an epicardial coronary artery that has dived into the wall "
                 "and runs in the perimysium between laminae. These resistance vessels autoregulate coronary flow "
                 "(adenosine, NO) and are the site of microvascular angina.",
    "venule": "Intramyocardial venule draining the capillary bed back to the cardiac veins (and some directly into "
              "the chambers via thebesian veins).",
    "purkinje": "Purkinje fibres: subendocardial conducting cardiomyocytes, wider than working cells (up to 50 µm) "
                "and paler because their few myofibrils are pushed to the periphery around glycogen-rich "
                "sarcoplasm. They carry abundant gap junctions (connexin 40) and conduct at 2–4 m/s, the fastest "
                "in the heart, spreading the impulse from the bundle branches over the endocardium so the ventricles "
                "contract from apex to base.",
    "purkinje_core": "Glycogen-rich sarcoplasm of Purkinje cells: pale, almost empty-looking cytoplasm around the "
                     "nucleus. The glycogen lets the conduction system survive ischaemia longer than working "
                     "muscle.",
    "purkinje_nuclei": "Purkinje cell nuclei: one or two, central and round, often with a clear perinuclear halo.",
    "subendo": "Subendocardial layer: loose connective tissue joining the endocardium to the myocardium. It carries "
               "the Purkinje fibres, small veins and nerves. This innermost zone is furthest from the epicardial "
               "arteries and most compressed in systole, so it is the first to infarct (subendocardial / "
               "NSTEMI infarction).",
    "subendothelial": "Subendothelial layer of the endocardium: dense connective tissue with elastic fibres and "
                      "scattered smooth muscle cells beneath the endothelium. Thickened and fibrotic in "
                      "endocardial fibroelastosis.",
    "endothelium": "Endocardial endothelium: simple squamous epithelium lining the chamber, continuous with the "
                   "endothelium of the great vessels and covering the valves. Damage here (infarction, "
                   "inflammation) exposes collagen and seeds mural thrombus.",
    "epi_ct": "Subepicardial connective tissue: loose connective tissue beneath the mesothelium carrying the "
              "coronary arteries, cardiac veins, nerves, lymphatics and a variable amount of fat.",
    "fat": "Epicardial adipose tissue: unilocular adipocytes concentrated in the atrioventricular and "
           "interventricular grooves around the coronary vessels, cushioning them. Its volume correlates with "
           "coronary artery disease and atrial fibrillation.",
    "mesothelium": "Mesothelium (visceral pericardium / epicardium): simple squamous mesothelial cells secreting the "
                   "serous fluid that lets the heart glide within the pericardial sac. Inflamed in pericarditis "
                   "(fibrinous 'bread-and-butter' exudate, friction rub).",
    "art_intima": "Coronary artery – tunica intima: endothelium on a thin subendothelial layer and a wavy internal "
                  "elastic lamina. Atherosclerotic plaques form here: lipid-laden foam cells beneath a fibrous "
                  "cap. Rupture of a thin cap causes thrombosis and acute myocardial infarction.",
    "art_media": "Coronary artery – tunica media: circumferential smooth muscle between the internal and external "
                 "elastic laminae (a muscular artery). Its tone is set by metabolites, NO and sympathetic nerves; "
                 "vasospasm here causes Prinzmetal angina.",
    "art_adv": "Coronary artery – tunica adventitia: collagen and elastic fibres with vasa vasorum and nerves, "
               "blending into the epicardial fat. The epicardial arteries are end-arteries functionally, so a "
               "sudden occlusion leaves their territory without collateral supply.",
    "vein": "Cardiac vein: thin-walled, wide lumen, running with the arteries in the epicardial fat and draining to "
            "the coronary sinus. Veins such as the great cardiac vein are used to place left-ventricular pacing "
            "leads.",
    "nerve": "Autonomic nerve: sympathetic (from the cervical and thoracic ganglia) and parasympathetic (vagal) "
             "fibres of the cardiac plexus running with the vessels. Visceral afferents travelling with the "
             "sympathetics refer ischaemic pain to the chest wall and left arm.",
}


class _Fibre:
    """A cardiac fibre: a gently meandering line with an out-of-round section, made of cells."""

    def __init__(self, origin, direction, r0, rng):
        self.o = np.asarray(origin, float)
        self.d, self.n, self.b = _frame(direction)
        self.r0 = r0
        self.ph = rng.uniform(0, 2 * math.pi, 6)
        self.f = rng.uniform(5.0, 9.0, 2)

    def centre(self, t):
        t = np.asarray(t, float)
        wob_n = 0.0035 * np.sin(t * self.f[0] + self.ph[0])
        wob_b = 0.0040 * np.sin(t * self.f[1] + self.ph[1])
        return (self.o + t[..., None] * self.d + wob_n[..., None] * self.n + wob_b[..., None] * self.b)

    def radius(self, th, t):
        return self.r0 * (1.0 + 0.07 * np.cos(2 * th + self.ph[2]) + 0.04 * np.cos(3 * th + self.ph[3])) * \
            (1.0 + 0.05 * np.sin(t * 7.0 + self.ph[4]))

    def point(self, t, th, rho):
        """Surface points for broadcastable t (along), th (around), rho (fraction of the local radius)."""
        t, th, rho = np.broadcast_arrays(np.asarray(t, float), np.asarray(th, float), np.asarray(rho, float))
        r = self.radius(th, t) * rho
        return (self.centre(t) + (r * np.cos(th))[..., None] * self.n + (r * np.sin(th))[..., None] * self.b)


def _step(fib, tb, step, th, rho, scale=1.0):
    """Axial offset of an intercalated disc surface: one riser across the fibre at a0 along direction psi."""
    psi, a0, h = step
    a = rho * fib.radius(th, tb) * np.cos(th - psi) / fib.r0
    return 0.5 * h * np.tanh((a - a0) / 0.16) * scale


def _grid_mesh(P):
    """Closed mesh from a (rings x segments x 3) grid whose first and last rings are collapsed to points."""
    k, m = P.shape[:2]
    a = np.arange(k * m).reshape(k, m)
    q0, q1 = a[:-1, :].ravel(), np.roll(a[:-1, :], -1, axis=1).ravel()
    q2, q3 = np.roll(a[1:, :], -1, axis=1).ravel(), a[1:, :].ravel()
    idx = np.concatenate([np.stack([q0, q2, q1], 1), np.stack([q0, q3, q2], 1)])
    from .cells import orient_outward
    return orient_outward(Mesh().add(P.reshape(-1, 3), idx))


def _cell(fib, tb0, tb1, step0, step1, rho_scale=1.0, seg=12, pitch=0.04):
    """One cardiomyocyte between two disc positions: a tube whose two ends follow the stepped disc surfaces, the
    rim rounded off so the disc shows as a dark band between neighbouring cells."""
    th = np.linspace(0, 2 * math.pi, seg, endpoint=False)
    cap = np.array([0.0, 0.45, 0.75, 0.92, 1.0])
    rnd = 0.005 * np.clip((cap - 0.75) / 0.25, 0, 1) ** 2
    rings = []
    for c, ro in zip(cap, rnd):                      # start cap, centre outwards
        t = tb0 + _step(fib, tb0, step0, th, c) + ro + 0.0012
        rings.append(fib.point(t, th, c * rho_scale))
    t_a = tb0 + _step(fib, tb0, step0, th, 1.0) + rnd[-1] + 0.0012
    t_b = tb1 + _step(fib, tb1, step1, th, 1.0) - rnd[-1] - 0.0012
    n_side = max(2, int((tb1 - tb0) / pitch))
    for u in np.linspace(0, 1, n_side + 2)[1:-1]:
        rings.append(fib.point(t_a + (t_b - t_a) * u, th, rho_scale))
    for c, ro in zip(cap[::-1], rnd[::-1]):
        t = tb1 + _step(fib, tb1, step1, th, c) - ro - 0.0012
        rings.append(fib.point(t, th, c * rho_scale))
    return _grid_mesh(np.array(rings))


def _disc(fib, tb, step, seg=10, thick=0.0045, grow=1.05):
    """Intercalated disc: a thin stepped plate filling the gap between two cells, its rim just proud of them.
    Sampled on rows across the riser so the step stays crisp."""
    psi, a0, h = step
    # rows across the riser, clustered where the step is
    u = np.concatenate([np.linspace(-0.999, a0 - 0.3, 3), np.linspace(a0 - 0.16, a0 + 0.16, 4),
                        np.linspace(a0 + 0.3, 0.999, 3)])
    u = np.clip(np.sort(u), -0.999, 0.999)
    ph = np.linspace(0, 2 * math.pi, seg, endpoint=False)
    U, PH = np.meshgrid(u, ph, indexing="ij")
    half = np.sqrt(1.0 - U ** 2)
    a = U
    v = half * np.cos(PH)
    off = 0.5 * thick * np.sin(PH)
    th = np.arctan2(v, a) + psi
    rho = np.sqrt(a ** 2 + v ** 2) * grow
    t = tb + 0.5 * h * np.tanh((a - a0) / 0.16) + off
    P = fib.point(t, th, np.minimum(rho, grow))
    # poles
    tip0 = fib.point(tb - 0.5 * h, psi + math.pi, grow)
    tip1 = fib.point(tb + 0.5 * h, psi, grow)
    P = np.concatenate([np.repeat(tip0[None, None], seg, 1), P, np.repeat(tip1[None, None], seg, 1)])
    return _grid_mesh(P)


def _nucleus(fib, t, half, r, seed):
    c = fib.centre(t)
    rot = np.stack([fib.d, fib.n, fib.b], axis=1)
    rng = np.random.default_rng(seed)
    return ellipsoid_mesh(c, (half * rng.uniform(0.9, 1.1), r * rng.uniform(0.9, 1.1), r), 5, rotation=rot)


def _line_t_range(o, d, lo, hi):
    """Parameter range where the line o + t d lies inside the x/z extent of the box, and the face it enters by."""
    t0, t1, face = -1e9, 1e9, None
    for axis in (0, 2):
        if abs(d[axis]) < 1e-9:
            if not lo[axis] <= o[axis] <= hi[axis]:
                return None
            continue
        a = (lo[axis] - o[axis]) / d[axis]
        b = (hi[axis] - o[axis]) / d[axis]
        ent = min(a, b)
        if ent > t0:
            t0 = ent
            face = (axis, lo[axis] if a < b else hi[axis])
        t1 = min(t1, max(a, b))
    if t1 <= t0:
        return None
    return t0, t1, face


def build_cardiac():
    rng = np.random.default_rng(71)
    X0, X1, Z0, Z1 = -1.0, 1.0, -0.6, 0.6
    Y_BOT = -0.545
    Y_ENDO = -0.537                      # endothelium top
    Y_SUBEN = -0.505                     # subendothelial layer top
    Y_MYO0, Y_MYO1 = -0.335, 0.300      # myocardium
    parts = []
    lo = np.array([X0, Y_BOT, Z0])
    hi = np.array([X1, 1.0, Z1])
    EPS = 0.004           # caps sit this far proud of the faces: more than the finishing warp's 3D terms can shift

    # ------------------------------------------------------------------ fibres in laminae
    # the fibre angle turns through the wall (endocardial laminae one way, epicardial the other), as in the
    # helical architecture of the ventricle
    laminae = [(-0.335, -0.125, math.radians(30.0)), (-0.105, 0.075, math.radians(8.0)),
               (0.135, 0.295, math.radians(-22.0))]
    myo, discs, nuclei, halos, caps = Mesh(), Mesh(), Mesh(), Mesh(), Mesh()
    fringe_cells = 0
    for li, (ya, yb, ang) in enumerate(laminae):
        d = np.array([math.cos(ang), 0.0, math.sin(ang)])
        e = np.array([-math.sin(ang), 0.0, math.cos(ang)])       # across the fibres, in the lamina plane
        corners = np.array([[x, z] for x in (X0, X1) for z in (Z0, Z1)])
        w = corners[:, 0] * e[0] + corners[:, 1] * e[2]
        # a jittered hexagonal packing in the plane of section: rows of fibres within the lamina
        pts = hex_points((w.min() - 0.05, ya + 0.031), (w.max() + 0.05, yb - 0.031), 0.072, 0.07, seed=300 + li)
        fibs = []
        for wv, y in pts:
            o = np.array([0.0, y, 0.0]) + e * wv
            f = _Fibre(o, d, rng.uniform(0.0265, 0.0305), rng)
            rng_t = _line_t_range(o, d, lo, hi)
            if rng_t is None:
                continue
            fibs.append((f, rng_t, (y, wv)))
        # capillaries in the clefts between fibres (Delaunay triangle centres with room to spare)
        yw = np.array([p for _, _, p in fibs])
        rads = np.array([f.r0 for f, _, _ in fibs])
        tree = cKDTree(yw)
        if len(yw) >= 4:
            tri = Delaunay(yw)
            for s in tri.simplices:
                cc = yw[s].mean(axis=0)
                dist, j = tree.query(cc, k=3)
                clear = np.min(dist - rads[j] * 1.11)
                if clear < 0.0068 or rng.random() < 0.45:
                    continue
                o = np.array([0.0, cc[0], 0.0]) + e * cc[1]
                tr = _line_t_range(o, d, lo, hi)
                if tr is None:
                    continue
                t = np.linspace(tr[0] - 0.05, tr[1] + 0.05, max(8, int((tr[1] - tr[0]) / 0.06)))
                ph = rng.uniform(0, 6.3)
                path = o + t[:, None] * d + (0.002 * np.sin(t * 9 + ph))[:, None] * e
                caps.extend(tube(path, 0.0056, 8))
            # branches: an oblique limb from one fibre into a close neighbour
            for s in tri.simplices:
                for k in range(3):
                    i, j = s[k], s[(k + 1) % 3]
                    if i > j or np.linalg.norm(yw[i] - yw[j]) > 0.092 or rng.random() > 0.22:
                        continue
                    fi, ri, _ = fibs[i]
                    fj, rj, _ = fibs[j]
                    t_lo = max(ri[0], rj[0]) + 0.05
                    t_hi = min(ri[1], rj[1]) - 0.2
                    if ri[2] and ri[2][0] == 0 and ri[2][1] == X0:
                        t_lo -= 0.25                                 # also in the teased-out fringe
                    if t_hi <= t_lo:
                        continue
                    t1 = rng.uniform(t_lo, t_hi)
                    a, b = fi.centre(t1), fj.centre(t1 + rng.uniform(0.12, 0.18))
                    path = np.linspace(a, b, 8)
                    rr = min(fi.r0, fj.r0) * 0.52
                    myo.extend(tube(path, rr, 12))
        for fi_idx, (f, (t0, t1, face), _) in enumerate(fibs):
            fringe = face is not None and face[0] == 0 and face[1] == X0
            # cell boundaries: from the fringe tip (fibres pull apart at their discs when teased, leaving the
            # stepped end of the cell bare) or from outside the box
            start = t0 - (rng.uniform(0.03, 0.34) if fringe else rng.uniform(0.05, 0.28))
            bounds = [start]
            while bounds[-1] < t1 + 0.05:
                bounds.append(bounds[-1] + rng.uniform(0.19, 0.29))
            steps = [(rng.uniform(0, 2 * math.pi), rng.uniform(-0.35, 0.35), rng.uniform(0.012, 0.018))
                     for _ in bounds]
            for k in range(len(bounds) - 1):
                b0, b1 = bounds[k], bounds[k + 1]
                myo.extend(_cell(f, b0, b1, steps[k], steps[k + 1]))
                if fringe and b0 < t0:
                    fringe_cells += 1
                # nucleus (a quarter binucleate) in its clear cone at the middle of the cell
                tm = (b0 + b1) / 2 + rng.uniform(-0.015, 0.015)
                if rng.random() < 0.22:
                    for off in (-0.032, 0.032):
                        nuclei.extend(_nucleus(f, tm + off, 0.024, 0.0098, int(rng.integers(1 << 30))))
                    halos.extend(_spindle(f.centre(tm - 0.105), f.centre(tm + 0.105), 0.0150))
                else:
                    nuclei.extend(_nucleus(f, tm, 0.027, 0.0105, int(rng.integers(1 << 30))))
                    halos.extend(_spindle(f.centre(tm - 0.072), f.centre(tm + 0.072), 0.0150))
            for k in range(1, len(bounds) - 1):
                discs.extend(_disc(f, bounds[k], steps[k]))

    open_lo = [None, None, Z0]            # the -x end is the teased fringe
    clip_hi = [X1, None, Z1]
    parts += [
        mesh_part(_merge(_clip_box(myo, open_lo, clip_hi, EPS)), "Cardiomyocytes", "Myocardium", "#c45a64",
                  CARD["myocytes"], "muscle", rank=0.5, detail=(0.06, 150.0, 0.0, 1)),
        mesh_part(_merge(_clip_box(halos, open_lo, clip_hi, EPS * 1.4)), "Perinuclear clear zone", "Myocardium",
                  "#f2d9cf", CARD["halo"], "gland", rank=0.6, label=False, detail=(0.06, 0.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(nuclei, open_lo, clip_hi, EPS * 2.0)), "Cardiomyocyte nuclei", "Myocardium",
                  "#3d2c78", CARD["nuclei"], "nucleus", rank=0.7, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(caps, [X0, None, Z0], clip_hi, EPS * 1.2)), "Endomysial capillaries",
                  "Myocardium", "#e03a30", CARD["caps"], "artery", rank=0.55, detail=(0.06, 120.0, 0.5, 1)),
        hlayer("Endomysium & perimysium", "Myocardium", "#f0dfd2", Y_MYO0, Y_MYO1, CARD["endomysium"], "fascia",
               (X0, X1), (Z0, Z1), res=90, bulk=True, rank=0, label=False, detail=(0.10, 60.0, 0.2, 1)),
    ]

    # intramyocardial arteriole and venule in the perimysial cleft between the middle and outer laminae
    xs = np.linspace(X0, X1, 50)
    xs = np.linspace(X0 - EPS, X1 + EPS, 50)
    art = _square_ends(np.stack([xs, 0.105 + 0.006 * np.sin(xs * 3.1), 0.16 + 0.02 * np.sin(xs * 2.3 + 1)], -1), 0)
    ven = _square_ends(np.stack([xs, 0.104 + 0.005 * np.sin(xs * 2.7 + 2), 0.36 + 0.025 * np.sin(xs * 1.9)], -1), 0)
    parts.append(mesh_part(tube_shell(art, 0.024, 0.011, 22), "Intramyocardial arteriole", "Vessels & nerves",
                           "#b8403b", CARD["arteriole"], "artery", rank=1, detail=(0.06, 110.0, 0.6, 4)))
    parts.append(mesh_part(tube_shell(ven, 0.025, 0.018, 22), "Intramyocardial venule", "Vessels & nerves",
                           "#5b64a8", CARD["venule"], "vein", rank=1))

    # ------------------------------------------------------------------ endocardium with Purkinje fibres
    pk_rim, pk_core, pk_nuc = Mesh(), Mesh(), Mesh()
    pk_rows = [(-0.447, z) for z in (-0.02, 0.098, 0.216, -0.43, -0.315, 0.47, 0.585)] + \
              [(-0.388, z) for z in (0.04, 0.157, -0.372, 0.528)]
    for k, (y, z) in enumerate(pk_rows):
        f = _Fibre((0.0, y + rng.uniform(-0.004, 0.004), z), (1.0, 0.0, 0.0), rng.uniform(0.045, 0.050), rng)
        bounds = [X0 - rng.uniform(0.02, 0.12)]
        while bounds[-1] < X1 + 0.05:
            bounds.append(bounds[-1] + rng.uniform(0.12, 0.17))
        steps = [(rng.uniform(0, 2 * math.pi), rng.uniform(-0.3, 0.3), rng.uniform(0.012, 0.016)) for _ in bounds]
        for j in range(len(bounds) - 1):
            b0, b1 = bounds[j], bounds[j + 1]
            outer = _cell(f, b0, b1, steps[j], steps[j + 1], 1.0, seg=13, pitch=0.035)
            inner = _cell(f, b0 + 0.012, b1 - 0.012, steps[j], steps[j + 1], 0.74, seg=13, pitch=0.035)
            rim = Mesh()
            po, _, io = outer.arrays()
            pi, _, ii = inner.arrays()
            rim.add(np.vstack([po, pi]), np.vstack([io, ii[:, ::-1] + len(po)]))
            pk_rim.extend(rim)
            pk_core.extend(_cell(f, b0 + 0.0125, b1 - 0.0125, steps[j], steps[j + 1], 0.735, seg=13, pitch=0.035))
            tm = (b0 + b1) / 2
            n_nuc = 2 if rng.random() < 0.3 else 1
            for q in range(n_nuc):
                off = (q - (n_nuc - 1) / 2) * 0.036
                c = f.centre(tm + off)
                pk_nuc.extend(ellipsoid_mesh(c, (0.016, 0.0145, 0.0145), 7))
            if j:
                discs.extend(_disc(f, b0, steps[j], seg=14))
    pk_box = ([X0, None, Z0], [X1, None, Z1])
    parts += [
        mesh_part(_merge(_clip_box(pk_rim, *pk_box, EPS)), "Purkinje fibres", "Endocardium", "#e6a9b0",
                  CARD["purkinje"], "muscle", rank=-1, detail=(0.05, 150.0, 0.0, 1)),
        mesh_part(_merge(_clip_box(pk_core, *pk_box, EPS * 1.3)), "Purkinje cell sarcoplasm (glycogen)",
                  "Endocardium", "#f5ece6", CARD["purkinje_core"], "fat", rank=-1, label=False,
                  detail=(0.05, 40.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(pk_nuc, *pk_box, EPS * 2.0)), "Purkinje cell nuclei", "Endocardium", "#4b3a8a",
                  CARD["purkinje_nuclei"], "nucleus", rank=-0.9, label=False, detail=(0.05, 0.0, 0.0, 0)),
    ]
    # the Purkinje discs are made the same way and belong to the same object
    parts.insert(1, mesh_part(_merge(_clip_box(discs, open_lo, clip_hi, EPS * 1.6)), "Intercalated discs", "Myocardium",
                         "#351a47", CARD["discs"], "nucleus", rank=0.6, detail=(0.03, 0.0, 0.0, 0)))
    parts += [
        hlayer("Subendocardial layer", "Endocardium", "#efdcc3", Y_SUBEN, Y_MYO0, CARD["subendo"], "fascia",
               (X0, X1), (Z0, Z1), res=90, bulk=True, rank=-1.2, detail=(0.12, 55.0, 0.18, 0)),
        hlayer("Subendothelial connective tissue", "Endocardium", "#e3c9ae", Y_ENDO, Y_SUBEN,
               CARD["subendothelial"], "fascia", (X0, X1), (Z0, Z1), res=90, rank=-1.5,
               detail=(0.12, 70.0, 0.25, 1)),
        hlayer("Endocardial endothelium", "Endocardium", "#eec3bd", Y_BOT, Y_ENDO, CARD["endothelium"], "serosa",
               (X0, X1), (Z0, Z1), res=90, rank=-1.8, detail=(0.06, 140.0, 0.6, 0)),
    ]

    # ------------------------------------------------------------------ epicardium: fat, coronary vessels, nerve
    ART_Z, ART_Y = 0.30, 0.425
    VEIN_Z, VEIN_Y = -0.24, 0.418
    NERVE = (0.455, 0.385)
    X_STRIP = -0.28                          # mesothelium and the top of the connective tissue stop here
    vessels = [((ART_Y, ART_Z), 0.095), ((VEIN_Y, VEIN_Z), 0.080), (NERVE, 0.035)]
    seeds = poisson_disk((X0 - 0.05, 0.345, Z0 - 0.05), (X1 + 0.05, 0.49, Z1 + 0.05), 0.118, seed=81)
    keep = np.ones(len(seeds), bool)
    for (vy, vz), vr in vessels:
        keep &= np.hypot(seeds[:, 1] - vy, seeds[:, 2] - vz) > vr + 0.035
    seeds = seeds[keep]
    # the smooth epicardial surface is lifted by the fat lobules and the artery beneath it
    ridge = lambda X, Z: 0.045 * np.exp(-((np.asarray(Z) - ART_Z) / 0.13) ** 2)
    fat_bumps = Bumps(seeds[seeds[:, 1] > 0.40][:, [0, 2]], 0.085, 0.011, k=4)
    y_top = lambda X, Z: 0.522 + ridge(X, Z) + fat_bumps(X, Z) + noise2(0.006, 3.0, seed=5)(X, Z)
    y_meso_bot = lambda X, Z: y_top(X, Z) - 0.012

    def y_ct_top(X, Z):
        w = np.clip((np.asarray(X) - (X_STRIP - 0.07)) / 0.07, 0.0, 1.0)
        w = w * w * (3 - 2 * w)
        return 0.338 + (y_meso_bot(X, Z) - 0.338) * w

    meso = hlayer("Mesothelium (visceral pericardium)", "Epicardium", "#f1e3d6", y_meso_bot, y_top,
                  CARD["mesothelium"], "serosa", (X_STRIP, X1), (Z0, Z1), res=150, rank=3,
                  detail=(0.06, 130.0, 0.6, 0))
    parts.append(relief_part(meso, cell_relief(0.034, 0.0025, seed=7, stretch=(1.0, 1.0, 1.0))))
    parts.append(hlayer("Subepicardial connective tissue", "Epicardium", "#eddcc0", Y_MYO1, y_ct_top, CARD["epi_ct"],
                        "fascia", (X0, X1), (Z0, Z1), res=120, bulk=True, rank=2, label=False,
                        detail=(0.12, 55.0, 0.15, 0)))

    # adipocytes: rounded Voronoi polyhedra packed between the myocardium and the mesothelium, kept clear of the
    # vessels by rings of ghost seeds around them
    ghosts = []
    for (vy, vz), vr in vessels:
        for gx in np.arange(X0 - 0.15, X1 + 0.15, 0.03):
            for a in np.linspace(0, 2 * math.pi, 16, endpoint=False):
                ghosts.append((gx, vy + (vr + 0.004) * math.cos(a), vz + (vr + 0.004) * math.sin(a)))
    ghosts = np.array(ghosts)
    ghosts = np.vstack([ghosts, seeds * [1, 0, 1] + [0, 2 * 0.318, 0] - seeds * [0, 1, 0],
                        seeds * [1, 0, 1] + [0, 2 * 0.508, 0] - seeds * [0, 1, 0],
                        seeds * [-1, 1, 1] + [2 * (X0 - 0.03), 0, 0], seeds * [-1, 1, 1] + [2 * (X1 + 0.03), 0, 0],
                        seeds * [1, 1, -1] + [0, 0, 2 * (Z0 - 0.03)], seeds * [1, 1, -1] + [0, 0, 2 * (Z1 + 0.03)]])
    fat = Mesh()
    for cell in _voronoi_cells(seeds, ghosts, shrink=0.94, round_amt=0.45):
        if cell is not None:
            fat.add(*cell)
    parts.append(mesh_part(_merge(_clip_box(fat, [X0, None, Z0], [X1, None, Z1], EPS)), "Epicardial adipocytes",
                           "Epicardium", "#f4d98e", CARD["fat"], "fat", rank=2.2, detail=(0.05, 22.0, 0.08, 0)))

    def sweep_along_x(y, z, seed, n_s=80):
        xs = np.linspace(X0 - EPS, X1 + EPS, n_s)
        return Sweep(_square_ends(np.stack([xs, y + 0.008 * np.sin(xs * 2.3 + seed),
                                            z + 0.012 * np.sin(xs * 1.7 + seed * 2)], -1), 0), 72, n_s)
    asw = sweep_along_x(ART_Y, ART_Z, 1)
    wav = rsum(0.0, lobed(9, 0.0030, 0.6))
    r_lum = rsum(0.036, wav)
    r_iel = rsum(0.043, wav)
    r_med = rsum(0.066, surf_noise(0.002, 3.0, 2.0, 7))
    r_adv = rsum(0.086, surf_noise(0.005, 3.0, 2.0, 8))
    parts += [
        mesh_part(asw.shell(r_lum, r_iel), "Coronary artery – intima", "Vessels & nerves", "#efcfc4",
                  CARD["art_intima"], "artery", rank=3.2, detail=(0.05, 120.0, 0.6, 4)),
        mesh_part(asw.shell(rsum(r_iel, 0.0005), r_med), "Coronary artery – media", "Vessels & nerves", "#b64b46",
                  CARD["art_media"], "artery", rank=3.2, detail=(0.06, 120.0, 0.6, 4)),
        mesh_part(asw.shell(rsum(r_med, 0.0005), r_adv), "Coronary artery – adventitia", "Vessels & nerves",
                  "#e2cba9", CARD["art_adv"], "fascia", rank=3.2, detail=(0.10, 60.0, 0.2, 1)),
    ]
    vsw = sweep_along_x(VEIN_Y, VEIN_Z, 3)
    vwall = rsum(lobed(3, 0.006, 0.8), surf_noise(0.003, 4.0, 6.0, 9))
    parts.append(mesh_part(vsw.shell(rsum(0.058, vwall), rsum(0.069, vwall, surf_noise(0.0015, 9.0, 30.0, 10))),
                           "Cardiac vein", "Vessels & nerves", "#5566b0", CARD["vein"], "vein", rank=3.2,
                           detail=(0.06, 100.0, 0.4, 1)))
    nerve = Mesh()
    xs = np.linspace(X0 - EPS, X1 + EPS, 60)
    for k in range(5):
        a = k * 2 * math.pi / 5
        nerve.extend(tube(np.stack([xs, NERVE[0] + 0.011 * math.cos(a) + 0.002 * np.sin(xs * 9 + k),
                                    np.full_like(xs, NERVE[1] + 0.011 * math.sin(a))], -1), 0.0085, 10))
    parts.append(mesh_part(nerve, "Autonomic nerve", "Vessels & nerves", "#f0cf45", CARD["nerve"], "nerve",
                           rank=3.2, detail=(0.06, 80.0, 0.3, 1)))
    return settle(parts, seed=711, amp_xz=0.022, amp_y=0.035, freq=1.5, grain=0.002, micro=0.0015)


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
                  "Acini", "#7a5eae", PANC["basal"], "gland", rank=0.5, detail=(0.09, 180.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(apex, lo_clip, hi_clip, EPS * 1.3)), "Acinar cells – apical zymogen granules",
                  "Acini", "#e8836a", PANC["apical"], "gland", rank=0.5, label=True, detail=(0.30, 260.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(nuc, lo_clip, hi_clip, EPS * 1.8)), "Acinar cell nuclei", "Acini", "#2e2466",
                  PANC["nuclei"], "nucleus", rank=0.6, label=False, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(cent, lo_clip, hi_clip, EPS * 1.6)), "Centroacinar cells", "Acini", "#efe9d6",
                  PANC["centroacinar"], "gland", rank=0.6, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(icd, lo_clip, hi_clip, EPS * 1.4)), "Intercalated ducts", "Septa & ducts",
                  "#ece0bf", PANC["intercalated"], "gland", rank=0.7, detail=(0.06, 200.0, 0.9, 0)),
        mesh_part(_merge(_clip_box(kinds["beta"], lo_clip, hi_clip, EPS)), "Beta cells (core)",
                  "Islets of Langerhans", "#cbc2ea", PANC["beta"], "gland", rank=1.5, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(kinds["alpha"], lo_clip, hi_clip, EPS)), "Alpha cells (mantle)",
                  "Islets of Langerhans", "#f0a7b5", PANC["alpha"], "gland", rank=1.5, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(kinds["delta"], lo_clip, hi_clip, EPS)), "Delta cells",
                  "Islets of Langerhans", "#f2cd5e", PANC["delta"], "gland", rank=1.5, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_merge(_clip_box(icaps, lo_clip, hi_clip, EPS * 1.2)), "Islet capillaries (fenestrated)",
                  "Islets of Langerhans", "#d8433b", PANC["islet_caps"], "artery", rank=1.6,
                  detail=(0.06, 120.0, 0.5, 0)),
    ]
    return settle(parts, seed=831, amp_xz=0.022, amp_y=0.035, freq=1.5, grain=0.002, micro=0.0015)
