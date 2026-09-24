"""High-resolution microanatomy models: urinary bladder, cornea and retina."""
import math

import numpy as np
from scipy.spatial import Delaunay, cKDTree

from .cells import hex_points, inset_polygon, orient_outward, polygon_area, smooth_polygon, voronoi_polygons
from .geometry import Mesh, tube
from .organic import cell_relief, relief, settle, warp_parts
from .kit import (Volume, add, at, const, ellipsoid, fn, hlayer, mesh_part, noise2, round_cone, sdf_part, shift,
                  smooth_path, wavy_path)
from .sdf import fbm2, fbm3

X0, X1, Z0, Z1 = -1.0, 1.0, -0.6, 0.6
XR, ZR = (X0, X1), (Z0, Z1)


# =============================================================================== cell-scale helpers
def _sstep(x, a, b):
    t = np.clip((np.asarray(x, float) - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _merged(mesh):
    """Fold a mesh made of thousands of small pieces (cells, rods, nuclei) into one sub-mesh, so the shared warp and
    the normal pass run once over big arrays instead of once per cell."""
    pos, nrm, idx = mesh.arrays()
    return Mesh().add(pos, idx, nrm) if len(idx) else Mesh()


_SPHERE = {}


def _unit_sphere(sub=1):
    """Icosphere: evenly spread triangles, so small nuclei stay round with very few of them (80 at sub=1). sub=-1
    is a once-divided octahedron (32 triangles) for the thousands of tiny nuclei of a nuclear layer."""
    if sub in _SPHERE:
        return _SPHERE[sub]
    if sub < 0:
        v = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
        f = [(2, 4, 0), (2, 0, 5), (2, 5, 1), (2, 1, 4), (3, 0, 4), (3, 5, 0), (3, 1, 5), (3, 4, 1)]
    else:
        t = (1.0 + 5 ** 0.5) / 2.0
        v = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
             (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
        f = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2),
             (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11),
             (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    v = [np.array(p, float) / np.linalg.norm(p) for p in v]
    for _ in range(abs(sub)):
        mid = {}

        def m(a, b):
            key = (min(a, b), max(a, b))
            if key not in mid:
                p = v[a] + v[b]
                v.append(p / np.linalg.norm(p))
                mid[key] = len(v) - 1
            return mid[key]
        nf = []
        for a, b, c in f:
            ab, bc, ca = m(a, b), m(b, c), m(c, a)
            nf += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        f = nf
    _SPHERE[sub] = (np.array(v), np.array(f, np.int64))
    return _SPHERE[sub]


def _blobs(centers, radii, rot=None, sub=1):
    """Many ellipsoids (nuclei, somata, vesicles) as one mesh. `radii` is (3,) or (n, 3); `rot` optional (n, 3, 3)
    local-to-world rotations."""
    c = np.asarray(centers, float).reshape(-1, 3)
    if not len(c):
        return Mesh()
    V, F = _unit_sphere(sub)
    r = np.broadcast_to(np.asarray(radii, float), c.shape)
    P = V[None] * r[:, None, :]
    N = V[None] / r[:, None, :]
    if rot is not None:
        P = np.einsum("cij,cvj->cvi", rot, P)
        N = np.einsum("cij,cvj->cvi", rot, N)
    P = P + c[:, None, :]
    N /= np.linalg.norm(N, axis=2, keepdims=True)
    idx = F[None] + (np.arange(len(c)) * len(V))[:, None, None]
    return Mesh().add(P.reshape(-1, 3), idx.reshape(-1, 3), N.reshape(-1, 3))


def _yaw(a):
    """Rotations about the vertical axis, one per angle."""
    a = np.asarray(a, float)
    c, s = np.cos(a), np.sin(a)
    R = np.zeros(a.shape + (3, 3))
    R[..., 0, 0], R[..., 0, 2], R[..., 1, 1], R[..., 2, 0], R[..., 2, 2] = c, s, 1.0, -s, c
    return R


def _tubes(paths, radii, segments=8, ry=None, caps=True):
    """Many swept tubes (processes, rods, fibres) merged into one mesh."""
    m = Mesh()
    for i, p in enumerate(paths):
        r = radii[i] if isinstance(radii, (list, tuple)) else radii
        m.extend(tube(np.asarray(p, float), r, segments, caps, None if ry is None else (ry[i] if isinstance(
            ry, (list, tuple)) else ry)))
    return _merged(m)


def _crossings(angle, spacing, y, seed, wobble=0.04, lat=0.0035, x=XR, z=ZR, offset=0.0):
    """Parallel vessel courses at `angle` (radians from x) that cross the whole block and meet its side walls
    square-on, so their flat end caps lie in the wall like vessels cut in a section."""
    rng = np.random.default_rng(seed)
    d = np.array([math.cos(angle), math.sin(angle)])
    perp = np.array([-d[1], d[0]])
    lo, hi = np.array([x[0], z[0]]), np.array([x[1], z[1]])
    half = float(np.abs(perp) @ ((hi - lo) / 2))
    paths = []
    for k in np.arange(-half + (offset % 1.0) * spacing, half, spacing):
        c = (lo + hi) / 2 + perp * (k + rng.uniform(-0.2, 0.2) * spacing)
        ts = []
        for ax in (0, 1):
            if abs(d[ax]) > 1e-9:
                ts += [(lo[ax] - c[ax]) / d[ax], (hi[ax] - c[ax]) / d[ax]]
        ts = sorted(ts)
        t0, t1 = ts[1], ts[2]                          # the segment of the line inside the rectangle
        if t1 - t0 < 0.15:
            continue
        a, b = c + d * t0, c + d * t1

        def wall_normal(p):
            g = np.minimum(np.abs(p - lo), np.abs(p - hi))
            ax = int(np.argmin(g))
            n = np.zeros(2)
            n[ax] = 1.0 if abs(p[ax] - lo[ax]) < abs(p[ax] - hi[ax]) else -1.0
            return n
        na, nb = wall_normal(a), wall_normal(b)
        m = max(int((t1 - t0) / 0.25), 1)
        mids = [a + (b - a) * f + perp * rng.uniform(-wobble, wobble) for f in np.linspace(0, 1, m + 2)[1:-1]]
        ctrl = [a - na * lat, a + na * 0.05] + mids + [b + nb * 0.05, b - nb * lat]
        ctrl = np.array([(p[0], y + rng.uniform(-0.3, 0.3) * wobble * 0.3, p[1]) for p in ctrl])
        ctrl[:, 0] = np.clip(ctrl[:, 0], x[0] - lat, x[1] + lat)
        ctrl[:, 2] = np.clip(ctrl[:, 2], z[0] - lat, z[1] + lat)
        paths.append(smooth_path(ctrl, max(24, int((t1 - t0) * 40))))
    return paths


def _capillaries(y, spacing, r, seed, ry=None, x=XR, z=ZR, jitter=0.35, segments=6):
    """A flat capillary bed: vessels along the edges of a jittered triangulation at height y(x, z), with small
    swellings where they join. Much lighter than a voxel network for beds that cover the whole block."""
    rng = np.random.default_rng(seed)
    pts = _lattice(spacing, jitter, seed, margin=spacing * 0.5, x=x, z=z)
    ys = fn(y)(pts[:, 0], pts[:, 1]) + 0 * pts[:, 0]
    tri = Delaunay(pts)
    inside = (pts[:, 0] > x[0]) & (pts[:, 0] < x[1]) & (pts[:, 1] > z[0]) & (pts[:, 1] < z[1])
    pts = np.column_stack([np.clip(pts[:, 0], x[0] - 0.003, x[1] + 0.003),
                           np.clip(pts[:, 1], z[0] - 0.003, z[1] + 0.003)])
    edges = set()
    for s in tri.simplices:
        for i in range(3):
            a, b = sorted((int(s[i]), int(s[(i + 1) % 3])))
            if (inside[a] or inside[b]) and 1e-4 < np.linalg.norm(pts[a] - pts[b]) < spacing * 1.6:
                edges.add((a, b))
    paths = []
    for a, b in edges:
        pa, pb = np.array([pts[a][0], ys[a], pts[a][1]]), np.array([pts[b][0], ys[b], pts[b][1]])
        mid = (pa + pb) / 2 + np.array([rng.uniform(-0.2, 0.2) * spacing, 0.0, rng.uniform(-0.2, 0.2) * spacing])
        mid[1] = fn(y)(mid[0], mid[2]) + rng.uniform(-0.2, 0.2) * r
        paths.append(np.array([pa, mid, pb]))
    m = _tubes(paths, r, segments, None if ry is None else [ry] * len(paths))
    ry_ = r if ry is None else ry
    m.extend(_blobs(np.column_stack([pts[:, 0], ys, pts[:, 1]])[inside], (r * 1.35, ry_ * 1.2, r * 1.35), sub=0))
    return _merged(m)


PRISM = ((0.0, 0.0, 0.0), (0.92, 0.0, 0.0), (1.0, 0.1, 0.0), (1.0, 0.86, 0.0), (0.86, 1.0, 0.25), (0.45, 1.0, 0.8),
         (0.0, 1.0, 1.0))
"""Default outline of an epithelial cell: rings (scale about the centroid, height fraction, share of the dome)
from the bottom centre to the top centre - a prism with a softened base and a domed apex."""
LOWPRISM = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.6, 1.0, 0.7), (0.0, 1.0, 1.0))
ENDO = ((0.0, 0.0, -1.0), (0.6, 0.0, -0.7), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0))     # bulges downwards
KERATO = ((0.0, 0.0, -1.0), (0.3, 0.0, -0.6), (1.0, 0.5, 0.0), (0.3, 1.0, 0.6), (0.0, 1.0, 1.0))  # flat, lens-edged


def _prisms(polys, bottom, top, profile=PRISM, dome=0.0):
    """Closed cells extruded from 2D outlines between two height functions: an epithelium whose every cell is a
    solid you can see on a cut or a side wall, instead of a flat band.

    `polys` are (n, 2) outlines in (x, z); `bottom`/`top` are y(x, z) functions evaluated at every vertex, so cells
    follow folds and ridges. `dome` (scalar, per-cell array or f(cx, cz)) raises the apex. The first and last
    profile rings must have scale 0 (the cap centres)."""
    polys = [np.asarray(p, float) for p in polys if p is not None and len(p) >= 3]
    if not polys:
        return Mesh()
    cen_all = np.array([p.mean(axis=0) for p in polys])
    if callable(dome):
        dome_all = np.asarray(dome(cen_all[:, 0], cen_all[:, 1]), float) * np.ones(len(polys))
    else:
        dome_all = np.broadcast_to(np.asarray(dome, float), (len(polys),))
    prof = np.asarray(profile, float)
    rings = prof[1:-1]
    R = len(rings)
    out = Mesh()
    by_n = {}
    for i, p in enumerate(polys):
        # counter-clockwise in (x, z) so every cell is wound the same way
        if 0.5 * float(np.dot(p[:, 0], np.roll(p[:, 1], -1)) - np.dot(p[:, 1], np.roll(p[:, 0], -1))) < 0:
            p = p[::-1]
        by_n.setdefault(len(p), []).append((i, p))
    for n, items in by_n.items():
        ids = np.array([i for i, _ in items])
        P = np.stack([p for _, p in items])                          # (C, n, 2)
        cen = cen_all[ids][:, None, :]
        dm = dome_all[ids][:, None]
        C = len(ids)
        pts = []
        for s, fr, dd in [prof[0]] + list(rings) + [prof[-1]]:
            xz = cen + (P - cen) * s if s > 0 else cen
            X, Z = xz[..., 0], xz[..., 1]
            b, t = bottom(X, Z), top(X, Z)
            Y = b + (t - b) * fr + dm * dd
            pts.append(np.stack(np.broadcast_arrays(X, Y, Z), -1))
        body = np.concatenate([pts[0]] + pts[1:-1] + [pts[-1]], axis=1)   # (C, 1 + R*n + 1, 3)
        nv = body.shape[1]
        tri = []
        k = np.arange(n)
        k1 = (k + 1) % n
        first = 1
        tri.append(np.stack([np.zeros(n, int), first + k, first + k1], 1))
        for r in range(R - 1):
            a0, a1 = first + r * n + k, first + r * n + k1
            b0, b1 = a0 + n, a1 + n
            tri += [np.stack([a0, b0, b1], 1), np.stack([a0, b1, a1], 1)]
        last = first + (R - 1) * n
        tri.append(np.stack([np.full(n, nv - 1), last + k1, last + k], 1))
        tri = np.vstack(tri)
        idx = tri[None] + (np.arange(C) * nv)[:, None, None]
        out.add(body.reshape(-1, 3), idx.reshape(-1, 3))
    return _merged(out)


def _oval_shell(c, rx, ry, wall, z, n=32):
    """Hollow channel of oval section running along z (a canal with its lining), closed at both ends."""
    th = np.linspace(0, 2 * math.pi, n, endpoint=False)
    k = np.arange(n)
    k1 = (k + 1) % n
    pos = []
    for r_x, r_y in ((rx + wall, ry + wall), (rx, ry)):
        for zz in z:
            pos.append(np.column_stack([c[0] + r_x * np.cos(th), c[1] + r_y * np.sin(th), np.full(n, zz)]))
    pos = np.vstack(pos)
    o0, o1, i0, i1 = k, n + k, 2 * n + k, 3 * n + k
    o0n, o1n, i0n, i1n = k1, n + k1, 2 * n + k1, 3 * n + k1
    tri = np.vstack([np.stack([o0, o0n, o1n], 1), np.stack([o0, o1n, o1], 1),
                     np.stack([i0, i1n, i0n], 1), np.stack([i0, i1, i1n], 1),
                     np.stack([o0, i0, i0n], 1), np.stack([o0, i0n, o0n], 1),
                     np.stack([o1, i1n, i1], 1), np.stack([o1, o1n, i1n], 1)])
    return orient_outward(Mesh().add(pos, tri))


def _clamp_box(mesh, lat=0.0035, x=XR, z=ZR):
    """Flatten whatever pokes out of the block onto its side walls, so cells, bundles and fat lobules end in a flat
    face, as if cut by the section, instead of bulging out of the tissue."""
    pos, _, idx = mesh.arrays()
    if not len(idx):
        return mesh
    pos = pos.copy()
    pos[:, 0] = np.clip(pos[:, 0], x[0] - lat, x[1] + lat)
    pos[:, 2] = np.clip(pos[:, 2], z[0] - lat, z[1] + lat)
    return Mesh().add(pos, idx)


def _cells(points, bottom, top, gap=0.002, profile=PRISM, dome=0.0, x=XR, z=ZR, smooth=0, keep=None):
    """Voronoi cell sheet: outlines from `points`, shrunk by `gap` so neighbours read as separate cells."""
    polys = voronoi_polygons(points, (x[0], z[0]), (x[1], z[1]))
    area = np.array([abs(polygon_area(p)) if p is not None else 0.0 for p in polys])
    floor = 0.3 * float(np.median(area[area > 0]))           # slivers clipped off by the block edge look like
    out = []                                                  # stray plates, so leave them out
    for i, p in enumerate(polys):
        if p is None or area[i] < floor or (keep is not None and not keep[i]):
            continue
        p = inset_polygon(p, gap / 2) if gap else p
        out.append(smooth_polygon(p, smooth) if smooth else p)
    return _prisms(out, bottom, top, profile, dome)


def _lattice(spacing, jitter=0.25, seed=0, margin=0.0, x=XR, z=ZR):
    """Jittered hexagonal points over the block (fast even spread for dense cell sheets)."""
    return hex_points((x[0] - margin, z[0] - margin), (x[1] + margin, z[1] + margin), spacing, jitter, seed)


# =============================================================================== urinary bladder
BLADDER = {
    "umbrella": "Umbrella (superficial) cells: the largest urothelial cells, each spanning several intermediate "
                "cells, often binucleate or polyploid. Tight junctions and the plaque-covered apical membrane make "
                "them the urine-blood barrier. They bulge as domes when the bladder is empty (the folded end of the "
                "block) and flatten and spread as it fills (the flat end).",
    "nuclei": "Umbrella cell nuclei: large nuclei, two in many cells (binucleate) - a normal finding in the "
              "superficial layer that should not be mistaken for atypia.",
    "plaques": "Uroplakin plaques: rigid plates of hexagonally packed uroplakins (Ia, Ib, II, IIIa) - the "
               "asymmetric unit membrane - covering about 90% of the umbrella cell surface, joined by flexible "
               "hinges. They seal the surface against urine; uroplakin Ia is also the receptor that type 1 "
               "fimbriae (FimH) of uropathogenic E. coli bind to in urinary tract infection.",
    "vesicles": "Fusiform (discoidal) vesicles: flattened, plaque-lined vesicles in the apical cytoplasm of "
                "umbrella cells. They fuse with the apical membrane as the bladder fills, adding surface area, and "
                "are retrieved by endocytosis after voiding.",
    "intermediate": "Intermediate cells: pear-shaped and polygonal cells, several layers deep when the bladder is "
                    "empty. As it fills they slide past one another so the urothelium thins from 5-7 cell layers "
                    "to 2-3 (compare the two ends of the block); they mature into umbrella cells when the surface "
                    "is injured.",
    "basal": "Basal cells: a single row of small cuboidal cells on the basement membrane - the progenitors that "
             "regenerate the urothelium, normally very slowly but rapidly after injury (infection, catheters, "
             "cyclophosphamide).",
    "lp": "Lamina propria: loose, vascular connective tissue with elastic fibres, lymphatics and a layer of "
          "suburothelial interstitial cells and afferent nerve endings that sense stretch. Urothelial carcinoma "
          "invading it is stage pT1; spread to the detrusor is pT2. There is no true submucosa; the loose deep "
          "lamina propria lets the mucosa fold into rugae when the bladder is empty.",
    "mm": "Muscularis mucosae: thin, discontinuous wisps of smooth muscle in the mid lamina propria, with the large "
          "vessels running at the same level. Pathologists must not mistake it for detrusor muscle: invasion of "
          "these wisps is still pT1, not muscle-invasive (pT2) cancer.",
    "cap": "Suburothelial capillary plexus: a dense capillary bed just beneath the basement membrane that feeds the "
           "avascular urothelium. It bleeds when the urothelium is injured - haematuria in cystitis, carcinoma in "
           "situ or cyclophosphamide/ifosfamide (acrolein) haemorrhagic cystitis, prevented by mesna.",
    "lp_art": "Arterioles of the lamina propria, branches of the superior and inferior vesical arteries (internal "
              "iliac).",
    "lp_vein": "Venules of the lamina propria draining to the vesical venous plexus.",
    "inner": "Inner longitudinal layer of the detrusor: large smooth muscle fascicles running mostly lengthways "
             "towards the bladder neck.",
    "middle": "Middle circular layer of the detrusor: the thickest layer, best defined at the bladder neck, where "
              "in males it forms the internal urethral sphincter (preventing retrograde ejaculation).",
    "outer": "Outer longitudinal layer of the detrusor. Around the bladder neck its fibres continue into the "
             "prostate or urethral wall.",
    "oblique": "Interlacing bundles: fascicles that pass obliquely from one layer into the next. The detrusor is a "
               "single meshwork whose three 'layers' are only distinct near the neck, so the whole bladder "
               "contracts together during voiding (parasympathetic pelvic splanchnic nerves S2-S4, acetylcholine "
               "on M3 receptors; relaxed for storage by sympathetic β3 receptors - antimuscarinics and mirabegron "
               "treat overactive bladder). Outflow obstruction makes the bundles hypertrophy into the ridges of a "
               "trabeculated bladder.",
    "ct": "Interfascicular connective tissue: collagen and elastic fibres between the muscle fascicles, carrying "
          "vessels, nerves and interstitial cells. Its increase with chronic obstruction or radiation stiffens the "
          "wall and lowers bladder compliance.",
    "adventitia": "Adventitia: connective tissue binding the bladder to the pelvic walls, with fat, the large "
                  "vesical vessels and the vesical nerve plexus.",
    "fat": "Perivesical fat: adipose tissue of the adventitia. Tumour spread into it is stage pT3.",
    "serosa": "Serosa: the peritoneum (mesothelium on a thin subserosa) covering only the superior surface (dome); "
              "elsewhere the outer coat is adventitia. A full bladder struck at the dome ruptures into the "
              "peritoneal cavity, whereas pelvic fractures cause extraperitoneal rupture.",
    "vessels": "Vesical arteries and veins of the adventitia (superior and inferior vesical arteries from the "
               "internal iliac artery; drainage to the vesical and prostatic venous plexuses).",
    "nerve": "Autonomic nerve bundles with small intramural ganglia: parasympathetic fibres from the pelvic "
             "splanchnic nerves (S2-S4) that drive voiding, sympathetic fibres from the hypogastric nerves "
             "(T10-L2) that relax the detrusor and close the neck, and stretch afferents that signal fullness. "
             "Botulinum toxin injected into the detrusor blocks their transmitter release in neurogenic "
             "overactivity.",
}


def build_bladder():
    """Relaxed (empty) bladder at the x < 0 end of the block, stretched (filling) bladder at the x > 0 end."""
    parts = []
    rng = np.random.default_rng(7)
    lat = 0.0035
    st = lambda X: _sstep(X, -0.25, 0.45)                      # 0 relaxed .. 1 stretched

    def y_bm(X, Z):                                             # basement membrane, thrown into rugae when empty
        X, Z = np.asarray(X, float), np.asarray(Z, float)
        fold = 0.055 * np.sin(X * 6.5 + 0.4) * np.cos(Z * 3.1 + 0.3 * np.sin(X * 3))
        return (0.78 + (1 - st(X)) * fold + 0.004 * fbm2(X.astype(np.float32), Z.astype(np.float32), 3.0, 3, 2)
                + 0 * Z)

    y_bas = lambda X, Z: y_bm(X, Z) + 0.022 - 0.004 * st(X)
    y_int = lambda X, Z: y_bas(X, Z) + 0.085 * (1 - st(X)) + 0.016 * st(X)
    y_umb = lambda X, Z: y_int(X, Z) + 0.036 * (1 - st(X)) + 0.013 * st(X)

    # ---------------------------------------------------------------- urothelium
    parts.append(mesh_part(_cells(_lattice(0.026, 0.2, seed=1, margin=0.03), y_bm, y_bas, gap=0.0024,
                                  profile=LOWPRISM, dome=0.002), "Basal cells", "Urothelium", "#95607f",
                           BLADDER["basal"], "mucosa", rank=1, detail=(0.08, 38.0, 0.9, 0)))
    n_int = lambda X: 1.0 + 3.0 * (1 - st(X))
    inter = Mesh()
    for j in range(4):
        pts = _lattice(0.042, 0.25, seed=10 + j, margin=0.04)

        def lvl(f, j=j):
            def g(X, Z):
                K = n_int(X)
                b, t = y_bas(X, Z), y_int(X, Z)
                return b + (t - b) * np.minimum(j + f, K) / K
            return g
        ok = lvl(1)(pts[:, 0], pts[:, 1]) - lvl(0)(pts[:, 0], pts[:, 1]) > 0.006
        inter.extend(_cells(pts, lvl(0), lvl(1), gap=0.0026, profile=LOWPRISM, dome=0.0025, keep=ok))
    parts.append(mesh_part(_merged(inter), "Intermediate cells", "Urothelium", "#d9b1c6", BLADDER["intermediate"],
                           "mucosa", rank=2, detail=(0.08, 28.0, 0.9, 0)))
    # umbrella cells: small and domed where the bladder is empty, wide and flat where it is stretched
    pa = _lattice(0.088, 0.22, seed=5, margin=0.06)
    pb = _lattice(0.13, 0.22, seed=6, margin=0.08)
    umb_pts = np.vstack([pa[pa[:, 0] < 0.12], pb[pb[:, 0] >= 0.12]])
    polys = voronoi_polygons(umb_pts, (X0, Z0), (X1, Z1))
    area = np.array([abs(polygon_area(p)) if p is not None else 0.0 for p in polys])
    polys = [smooth_polygon(inset_polygon(p, 0.0016), 1) for p, a in zip(polys, area) if p is not None and a > 0.002]
    cen = np.array([p.mean(axis=0) for p in polys])
    dome = lambda cx, cz: 0.026 * (1 - st(cx)) + 0.004
    parts.append(mesh_part(_prisms(polys, y_int, y_umb, PRISM, dome), "Umbrella cells", "Urothelium", "#f2e2ea",
                           BLADDER["umbrella"], "mucosa", rank=3, detail=(0.06, 0.0, 0.0, 0)))
    plaque = _prisms([inset_polygon(p, 0.004) for p in polys], shift(y_umb, -0.004), shift(y_umb, 0.0016), PRISM,
                     lambda cx, cz: dome(cx, cz) * 0.97)
    plaque = relief(plaque, cell_relief(0.011, 0.0022, seed=4))
    parts.append(mesh_part(plaque, "Uroplakin plaques (apical membrane)", "Urothelium", "#fbf3f7",
                           BLADDER["plaques"], "mucosa", rank=3.5, detail=(0.04, 0.0, 0.0, 0)))
    nuc_c, nuc_r, ves_c, ves_r, ves_rot = [], [], [], [], []
    for p, (cx, cz) in zip(polys, cen):
        b, t = at(y_int, cx, cz), at(y_umb, cx, cz)
        s = at(lambda X, Z: st(X) + 0 * Z, cx, cz)
        h = t - b
        rr = float(np.sqrt(abs(polygon_area(p))))
        flat = 0.55 + 0.45 * (1 - s)
        n = 2 if rng.random() < 0.45 else 1
        for k in range(n):
            off = (k - (n - 1) / 2) * rr * 0.34
            a = rng.uniform(0, math.pi)
            nuc_c.append((cx + off * math.cos(a), b + h * 0.45, cz + off * math.sin(a)))
            nuc_r.append((0.016, 0.011 * flat, 0.013))
        for k in range(6):
            q = np.array([cx, 0, cz]) + np.array([rng.uniform(-0.3, 0.3), 0, rng.uniform(-0.3, 0.3)]) * rr
            q[1] = b + h * rng.uniform(0.7, 0.92) + dome(cx, cz) * 0.3
            ves_c.append(q)
            ves_r.append((0.0085, 0.0014, 0.0035))
            ves_rot.append(rng.uniform(0, math.pi))
    nc = np.array(nuc_c)
    parts.append(mesh_part(_blobs(nc, np.array(nuc_r), _yaw(rng.uniform(0, math.pi, len(nc)))),
                           "Umbrella cell nuclei (often binucleate)", "Urothelium", "#5a3f8c", BLADDER["nuclei"],
                           "nucleus", rank=3, detail=(0.06, 0.0, 0.0, 0)))
    parts.append(mesh_part(_blobs(ves_c, np.array(ves_r), _yaw(np.array(ves_rot)), sub=0), "Fusiform vesicles",
                           "Urothelium", "#fff3c8", BLADDER["vesicles"], "mucosa", rank=3,
                           detail=(0.03, 0.0, 0.0, 0)))

    # ---------------------------------------------------------------- lamina propria
    Y_LP0, Y_MM = 0.56, 0.665
    parts.append(hlayer("Lamina propria", "Lamina propria", "#f1d5c6", Y_LP0, shift(y_bm, -0.001), BLADDER["lp"],
                        "mucosa", XR, ZR, bulk=True, rank=0, res=200, detail=(0.12, 70.0, 0.22, 0)))
    parts.append(mesh_part(_capillaries(shift(y_bm, -0.014), 0.075, 0.0048, seed=19), "Suburothelial capillary plexus",
                           "Lamina propria", "#d8483e", BLADDER["cap"], "artery", rank=0.5))
    mm_p, mm_r = [], []
    for x, z in _lattice(0.2, 0.45, seed=33, x=(X0 + 0.08, X1 - 0.08), z=(Z0 + 0.06, Z1 - 0.06)):
        if rng.random() < 0.3:
            continue                                            # the layer has gaps: it is discontinuous
        a = rng.choice([0.0, math.pi / 2]) + rng.uniform(-0.4, 0.4)
        L = rng.uniform(0.12, 0.26)
        d = np.array([math.cos(a), 0, math.sin(a)])
        c = np.array([x, Y_MM + rng.uniform(-0.03, 0.03), z])
        t = np.linspace(-0.5, 0.5, 9)[:, None]
        p = c + d * L * t + np.array([0, 1, 0]) * 0.008 * np.sin(t * 6 + x)
        mm_p.append(p)
        mm_r.append(0.012 * np.sqrt(1 - (2 * t[:, 0]) ** 2 * 0.85) + 0.002)
    parts.append(mesh_part(_tubes(mm_p, mm_r, 10), "Muscularis mucosae (discontinuous)", "Lamina propria", "#bb5a4f",
                           BLADDER["mm"], "muscle", rank=0, detail=(0.08, 90.0, 0.45, 1)))
    lp_a = _crossings(0.35, 0.3, Y_MM - 0.01, 41, 0.05) + _crossings(1.9, 0.34, Y_MM + 0.02, 42, 0.05)
    lp_v = _crossings(0.3, 0.3, Y_MM + 0.005, 43, 0.05, offset=0.5) + _crossings(1.95, 0.34, Y_MM - 0.02, 44, 0.05,
                                                                                 offset=0.5)
    parts.append(mesh_part(_tubes(lp_a, 0.013, 14), "Lamina propria arterioles", "Lamina propria", "#cf3a31",
                           BLADDER["lp_art"], "artery", rank=0))
    parts.append(mesh_part(_tubes(lp_v, 0.02, 16), "Lamina propria venules", "Lamina propria", "#3d5bc2",
                           BLADDER["lp_vein"], "vein", rank=0))

    # ---------------------------------------------------------------- detrusor: interlacing fascicles
    def fascicles(angle, spacing, y, r, seed, jitter=0.02, offset=0.0, y_end=None):
        paths = _crossings(angle, spacing, y, seed, 0.035, offset=offset)
        rr, yy = [], []
        for i, p in enumerate(paths):
            if y_end is not None:
                p[:, 1] = y + (y_end - y) * _sstep(np.linspace(0, 1, len(p)), 0.15, 0.85)
            p[:, 1] += jitter * np.sin(np.linspace(0, 1, len(p)) * 7 + i * 1.7)
            rr.append(r * (0.85 + 0.3 * ((i * 0.618) % 1)) * (1 + 0.12 * np.sin(np.linspace(0, 9, len(p)) + i)))
        flat = [q * (0.7 + 0.25 * ((i * 0.37) % 1)) for i, q in enumerate(rr)]      # oval fascicles
        return _clamp_box(_tubes(paths, rr, 16, ry=flat))

    outer = fascicles(0.08, 0.1, 0.148, 0.054, 51)
    outer.extend(fascicles(-0.1, 0.11, 0.165, 0.045, 52, offset=0.5))
    middle = fascicles(math.pi / 2 + 0.1, 0.1, 0.255, 0.054, 53)
    middle.extend(fascicles(math.pi / 2 - 0.12, 0.1, 0.33, 0.052, 54, offset=0.5))
    middle.extend(fascicles(math.pi / 2 + 0.05, 0.11, 0.405, 0.05, 59, offset=0.25))
    inner = fascicles(0.12, 0.09, 0.495, 0.045, 55)
    inner.extend(fascicles(-0.08, 0.12, 0.48, 0.036, 56, offset=0.5))
    obl = fascicles(0.8, 0.4, 0.16, 0.04, 57, y_end=0.48)
    obl.extend(fascicles(-0.75, 0.45, 0.48, 0.04, 58, y_end=0.17, offset=0.4))
    parts += [mesh_part(_merged(inner), "Inner longitudinal detrusor", "Detrusor muscle", "#bd5549",
                        BLADDER["inner"], "muscle", rank=-1, detail=(0.08, 80.0, 0.45, 1)),
              mesh_part(_merged(middle), "Middle circular detrusor", "Detrusor muscle", "#a8463d", BLADDER["middle"],
                        "muscle", rank=-2, detail=(0.08, 80.0, 0.45, 3)),
              mesh_part(_merged(outer), "Outer longitudinal detrusor", "Detrusor muscle", "#c46052",
                        BLADDER["outer"], "muscle", rank=-3, detail=(0.08, 80.0, 0.45, 1)),
              mesh_part(_merged(obl), "Interlacing (oblique) bundles", "Detrusor muscle", "#b44f5c",
                        BLADDER["oblique"], "muscle", rank=-2, detail=(0.08, 80.0, 0.45, 0))]
    # the connective tissue between fascicles stops just short of the walls, so the fascicles stand out on every
    # face the way they do in a section
    inset = 0.012
    parts.append(hlayer("Interfascicular connective tissue", "Detrusor muscle", "#ecd9c4", 0.1, Y_LP0 - 0.002,
                        BLADDER["ct"], "fascia", (X0 + inset, X1 - inset), (Z0 + inset, Z1 - inset), bulk=True,
                        rank=-2, res=80, detail=(0.14, 60.0, 0.2, 0)))

    # ---------------------------------------------------------------- adventitia, serosa, vessels and nerves
    parts.append(hlayer("Serosa (dome only)", "Adventitia & serosa", "#f1ead8", 0.0, 0.012, BLADDER["serosa"],
                        "serosa", XR, ZR, rank=-5, res=80, detail=(0.06, 90.0, 0.5, 0)))
    parts.append(hlayer("Adventitia", "Adventitia & serosa", "#e7d3ae", 0.013, 0.098, BLADDER["adventitia"], "fascia",
                        XR, ZR, bulk=True, rank=-4, res=100, detail=(0.14, 50.0, 0.15, 0)))
    fat = []
    for x, z in _lattice(0.34, 0.4, seed=71, margin=0.05):
        for k in range(9):
            fat.append((x + rng.normal(scale=0.05), rng.uniform(0.035, 0.075), z + rng.normal(scale=0.05)))
    fat = np.array(fat)
    fr = rng.uniform(0.024, 0.032, (len(fat), 1)) * np.array([1.0, 0.8, 1.0])
    parts.append(mesh_part(_clamp_box(_blobs(fat, fr)), "Perivesical fat", "Adventitia & serosa", "#f4dc8a",
                           BLADDER["fat"], "fat", rank=-4, detail=(0.05, 0.0, 0.0, 0)))
    va = _crossings(0.2, 0.55, 0.055, 61, 0.03)
    vv = _crossings(0.25, 0.55, 0.06, 62, 0.03, offset=0.45)
    parts.append(mesh_part(_tubes(va, 0.022, 18), "Vesical arteries", "Vessels & nerves", "#cf3a31",
                           BLADDER["vessels"], "artery", rank=-4))
    parts.append(mesh_part(_tubes(vv, 0.03, 18), "Vesical veins", "Vessels & nerves", "#3d5bc2", BLADDER["vessels"],
                           "vein", rank=-4))
    nv = _crossings(-0.3, 0.6, 0.075, 63, 0.03, offset=0.2) + _crossings(1.4, 0.7, 0.3, 64, 0.06)
    nerve = _tubes(nv, 0.012, 12)
    gang = []
    for p in nv[len(nv) // 2:]:
        for f in (0.3, 0.7):
            gang.append(p[int(f * (len(p) - 1))])
    nerve.extend(_blobs(gang, (0.026, 0.02, 0.026)))
    parts.append(mesh_part(_merged(nerve), "Autonomic nerves & intramural ganglia", "Vessels & nerves", "#f0cf45",
                           BLADDER["nerve"], "nerve", rank=-3))
    # the filling bladder wall is thinner as a whole, not just its urothelium
    warp_parts(parts, lambda p: np.column_stack([0 * p[:, 0], -0.12 * st(p[:, 0]) * p[:, 1], 0 * p[:, 0]]))
    return settle(parts, seed=401, amp_xz=0.026, amp_y=0.05, freq=1.5, grain=0.004, micro=0.002, micro_freq=24.0)
# =============================================================================== cornea
CORNEA = {
    "tear": "Tear film (~3-7 µm): outer lipid layer from the meibomian glands (slows evaporation), aqueous layer from "
            "the lacrimal glands and an inner mucin layer from conjunctival goblet cells. The air-tear interface is "
            "the most powerful refracting surface of the eye; its break-up causes dry eye disease.",
    "superficial": "Superficial squamous cells: 2-3 layers of flat, non-keratinised cells covered with microplicae "
                   "and a glycocalyx of membrane mucins that holds the tear film, sealed by tight junctions. They "
                   "desquamate into the tears; the whole epithelium turns over in 7-10 days.",
    "wing": "Wing cells: 2-3 layers of polygonal cells with wing-like lateral processes, between the basal and "
            "superficial cells. Most free nerve endings of the cornea end among them.",
    "basal": "Basal columnar cells: a single row of tall cells anchored by hemidesmosomes to their basement "
             "membrane - the only mitotic cells of the central epithelium, replenished by cells migrating in from "
             "the limbus (the X, Y, Z hypothesis). Recurrent erosion follows weak basal adhesion.",
    "bowman": "Bowman layer (8-12 µm): acellular, randomly woven collagen (types I and V), the condensed anterior "
              "stroma. It ends abruptly at the limbus and never regenerates: wounds through it heal with a scar. "
              "PRK removes it; it is ruptured in keratoconus.",
    "lamellae": "Stromal lamellae: ~90% of corneal thickness in 200-250 flat lamellae, each a sheet of parallel "
                "type I collagen fibrils of uniform diameter (~30 nm) held at a regular spacing by keratan sulphate "
                "proteoglycans (lumican, keratocan) - the lattice that makes the cornea transparent. Neighbouring "
                "lamellae cross roughly at right angles in the posterior stroma, obliquely and interwoven in the "
                "anterior third, which holds the corneal curvature. Oedema disturbs the spacing and clouds the "
                "cornea; LASIK reshapes the anterior stroma; keratoconus thins it.",
    "keratocytes": "Keratocytes: flattened, dendritic fibroblasts lying between the lamellae, linked into a network "
                   "by gap junctions. They make the matrix and are packed with crystallins (ALDH, transketolase) "
                   "that keep them from scattering light; after injury they turn into fibroblasts and "
                   "myofibroblasts, causing haze and scarring.",
    "dua": "Pre-Descemet (Dua) layer: a ~10-15 µm acellular band of tightly packed collagen just in front of "
           "Descemet membrane, described in 2013 and still debated as a separate layer. It splits off cleanly in "
           "the 'big bubble' of deep anterior lamellar keratoplasty.",
    "descemet": "Descemet membrane: basement membrane of the endothelium (collagen VIII and IV) with a banded fetal "
                "layer and a non-banded layer that thickens from ~3 µm at birth to over 10 µm in old age. Guttae in "
                "Fuchs dystrophy, Haab striae in congenital glaucoma, and copper in its periphery forms the "
                "Kayser-Fleischer ring of Wilson disease.",
    "endothelium": "Endothelium: a single layer of hexagonal cells (~5 µm high, 20 µm wide) whose Na+/K+-ATPase and "
                   "bicarbonate pumps keep the stroma dehydrated (the pump-leak balance). The cells do not divide in "
                   "humans: density falls from ~3000 to ~2500 cells/mm² over adult life, cells enlarge and lose "
                   "their hexagonal shape, and below ~500 cells/mm² the cornea swells - treated by endothelial "
                   "keratoplasty (DMEK).",
    "schwalbe": "Schwalbe line: the rounded end of Descemet membrane, marking the anterior limit of the trabecular "
                "meshwork and the peripheral end of the cornea on gonioscopy. When prominent and displaced it is a "
                "posterior embryotoxon (Axenfeld-Rieger syndrome).",
    "nerves": "Stromal nerves: branches of the long ciliary nerves (ophthalmic division of V) that enter the stroma "
              "radially at the limbus and lose their myelin within ~1 mm so the cornea stays transparent, then turn "
              "forwards and pierce Bowman layer. The cornea is the most densely innervated tissue in the body, the "
              "afferent limb of the corneal (blink) reflex; loss of innervation causes neurotrophic keratopathy.",
    "plexus": "Subbasal nerve plexus and free nerve endings: long beaded fibres running between the basal cells "
              "and Bowman layer, sending terminals up among the wing and superficial cells - why abrasions are so "
              "painful. Confocal microscopy counts them in diabetic neuropathy.",
    "limbal_epi": "Limbal epithelium: at the corneoscleral junction the epithelium thickens to 10 or more cell "
                  "layers and dips between the palisades of Vogt, then changes into conjunctival epithelium.",
    "stem": "Limbal epithelial stem cells: small, melanin-capped basal cells deep in the epithelial crypts between "
            "the palisades of Vogt, sheltered by their niche of stroma, vessels, nerves and melanocytes. They renew "
            "the corneal epithelium and act as a barrier to the conjunctiva: limbal stem cell deficiency (chemical "
            "burns, aniridia, Stevens-Johnson) lets vascularised conjunctiva grow over the cornea; cultured limbal "
            "grafts replace them.",
    "palisades": "Limbal stroma and palisades of Vogt: loose, vascular connective tissue whose radial "
                 "fibrovascular ridges (the palisades) interdigitate with the limbal epithelium; beyond the limbus it "
                 "becomes the substantia propria of the conjunctiva and Tenon capsule.",
    "arcades": "Limbal vascular arcades: branches of the anterior ciliary arteries end in hairpin capillary loops in "
               "the palisades, stopping short of the cornea, which is avascular - it lives on aqueous humour, tears, "
               "atmospheric oxygen and these limbal vessels. Hypoxia (contact lenses) or inflammation drives them "
               "into the cornea as corneal neovascularisation.",
    "goblet": "Conjunctival goblet cells: mucus cells of the conjunctival epithelium secreting MUC5AC, the gel "
              "mucin of the tear film. They are lost in cicatricial conjunctivitis and vitamin A deficiency "
              "(xerophthalmia).",
    "sclera": "Sclera: dense irregular collagen with fibrils of varied diameter and spacing interwoven in every "
              "direction - which is why it is white and opaque while the cornea, made of the same collagen, is "
              "clear. At the limbus its fibres run circumferentially; the scleral spur behind Schlemm canal anchors "
              "the ciliary muscle.",
    "tm": "Trabecular meshwork: perforated collagen beams covered by trabecular endothelial cells, stretching from "
          "Schwalbe line to the scleral spur - uveal and corneoscleral meshwork on the chamber side, "
          "juxtacanalicular tissue against the canal, where most outflow resistance lies. It drains ~80-90% of "
          "the aqueous (conventional outflow). Increased resistance raises intraocular pressure in open-angle "
          "glaucoma; ciliary muscle contraction (pilocarpine) pulls the spur and opens the meshwork.",
    "schlemm": "Schlemm canal: a circular, endothelium-lined channel in the scleral sulcus. Aqueous crosses its "
               "inner wall through giant vacuoles and pores and leaves by collector channels to the aqueous and "
               "episcleral veins. It is the target of canaloplasty and many micro-invasive glaucoma devices; blood "
               "refluxes into it on gonioscopy when episcleral venous pressure is high.",
    "collector": "Collector channels and aqueous veins: outlets from the outer wall of Schlemm canal through the "
                 "sclera to the deep scleral and episcleral venous plexuses.",
}


def _star(center, arms, reach, rng, waist=0.011):
    """Outline of a flat dendritic cell (keratocyte): a small body with tapering arms."""
    out = []
    a0 = rng.uniform(0, 2 * math.pi)
    for k in range(arms):
        a = a0 + k * 2 * math.pi / arms + rng.uniform(-0.3, 0.3)
        L = reach * rng.uniform(0.6, 1.15)
        for da, r in ((-0.32, waist), (0.0, L), (0.32, waist)):
            out.append((center[0] + r * math.cos(a + da), center[1] + r * math.sin(a + da)))
    return np.array(out)


def _ribbons(paths, half_w, half_t, n=12, p=4.0):
    """Flat collagen lamellae: a rounded-rectangle (superellipse) section swept along each path, kept level."""
    th = np.linspace(0, 2 * math.pi, n, endpoint=False)
    c, s = np.cos(th), np.sin(th)
    u = np.sign(c) * np.abs(c) ** (2.0 / p)
    v = np.sign(s) * np.abs(s) ** (2.0 / p)
    out = Mesh()
    for i, P in enumerate(paths):
        P = np.asarray(P, float)
        k = len(P)
        T = np.gradient(P, axis=0)
        T /= np.linalg.norm(T, axis=1, keepdims=True)
        side = np.cross(np.array([0.0, 1.0, 0.0]), T)
        side /= np.linalg.norm(side, axis=1, keepdims=True)
        up = np.cross(T, side)
        hw = np.broadcast_to(np.asarray(half_w[i] if isinstance(half_w, list) else half_w, float), (k,))
        ht = np.broadcast_to(np.asarray(half_t[i] if isinstance(half_t, list) else half_t, float), (k,))
        ring = (P[:, None, :] + side[:, None, :] * (u[None, :, None] * hw[:, None, None])
                + up[:, None, :] * (v[None, :, None] * ht[:, None, None]))
        pos = np.vstack([ring.reshape(-1, 3), P[0], P[-1]])
        a = np.arange(k * n).reshape(k, n)
        q0, q1 = a[:-1].ravel(), np.roll(a[:-1], -1, axis=1).ravel()
        q2, q3 = np.roll(a[1:], -1, axis=1).ravel(), a[1:].ravel()
        j = np.arange(n)
        tri = np.vstack([np.stack([q0, q2, q1], 1), np.stack([q0, q3, q2], 1),
                         np.stack([np.full(n, k * n), j, (j + 1) % n], 1),
                         np.stack([np.full(n, k * n + 1), (k - 1) * n + (j + 1) % n, (k - 1) * n + j], 1)])
        out.add(pos, tri)
    return orient_outward(_merged(out))


def build_cornea():
    """Peripheral cornea (x < -0.2) running out through the limbus (x -0.2 to 0.35) to conjunctiva and sclera, with
    the drainage angle (trabecular meshwork, Schlemm canal) in the deep limbus. The cut-away plane x = 0 falls
    across the palisades of Vogt, the cut plane z = 0 runs from cornea into limbus."""
    parts = []
    rng = np.random.default_rng(3)
    lat = 0.0035
    Y_BM0, Y_S0 = 0.886, 0.975
    Y_EN, Y_DM, Y_DUA = 0.014, 0.034, 0.05
    X_SW = -0.01                                           # Schwalbe line: the end of Descemet membrane

    def pal(X, Z):                                          # palisades of Vogt: radial ridges of limbal stroma
        X, Z = np.asarray(X, float), np.asarray(Z, float)
        env = _sstep(X, -0.15, -0.03) * (1 - _sstep(X, 0.23, 0.35))
        return 0.027 * env * np.cos(2 * math.pi * (Z + 0.02 * np.sin(7 * X)) / 0.12)

    def y_bm(X, Z):                                         # epithelial basement membrane
        X = np.asarray(X, float)
        return Y_BM0 - 0.05 * _sstep(X, -0.2, 0.0) + 0.055 * _sstep(X, 0.27, 0.45) + pal(X, Z)

    def y_s(X, Z):                                          # ocular surface under the tear film
        X, Z = np.asarray(X, float), np.asarray(Z, float)
        return (Y_S0 - 0.01 * _sstep(X, 0.15, 0.5)
                + 0.0015 * fbm2(X.astype(np.float32), Z.astype(np.float32), 5.0, 3, 8))

    def y_bow(X, Z):                                        # Bowman layer's lower face; it ends at the limbus
        return y_bm(X, Z) - 0.019 * (1 - _sstep(X, -0.25, -0.15))

    def y_lsb(X, Z=0.0):                                    # top of corneal stroma and sclera
        return (Y_BM0 - 0.019) - 0.105 * _sstep(X, -0.25, 0.05) + 0 * np.asarray(Z, float)

    def x_cs(y):                                            # oblique corneoscleral boundary
        return X_SW - 0.14 * np.clip(np.asarray(y, float) / 0.86, 0, 1)

    def y_tm(X):                                            # chamber face of the trabecular meshwork wedge
        return 0.03 + 0.17 * _sstep(X, X_SW, 0.33)

    # ---------------------------------------------------------------- epithelium, cell by cell
    bas_pts = _lattice(0.026, 0.2, seed=1, margin=0.03)
    trough = (pal(bas_pts[:, 0], bas_pts[:, 1]) < -0.014) & (bas_pts[:, 0] > -0.09) & (bas_pts[:, 0] < 0.27)
    top_b = lambda X, Z: y_bm(X, Z) + 0.033 - 0.008 * _sstep(X, -0.15, 0.05)
    parts.append(mesh_part(_cells(bas_pts, y_bm, top_b, gap=0.0024, profile=LOWPRISM, dome=0.003, keep=~trough),
                           "Basal columnar cells", "Epithelium", "#b58db5", CORNEA["basal"], "mucosa", rank=2,
                           detail=(0.08, 0.0, 0.0, 0)))
    parts.append(mesh_part(_cells(bas_pts, y_bm, top_b, gap=0.0024, profile=LOWPRISM, dome=0.003, keep=trough),
                           "Limbal epithelial stem cells", "Limbus", "#6e4a38", CORNEA["stem"], "mucosa", rank=2,
                           detail=(0.08, 0.0, 0.0, 0)))
    y_sup = lambda X, Z: y_s(X, Z) - 0.017
    n_wing = lambda X: 2.0 + 3.0 * _sstep(X, -0.19, 0.0) - 3.0 * _sstep(X, 0.27, 0.43)
    wing = Mesh()
    limbal = Mesh()
    for j in range(5):
        pts = _lattice(0.042, 0.25, seed=10 + j, margin=0.04)

        def lvl(f, j=j):
            def g(X, Z):
                K = n_wing(X)
                b, t = top_b(X, Z), y_sup(X, Z)
                return b + (t - b) * np.minimum(j + f, K) / K
            return g
        th = lvl(1)(pts[:, 0], pts[:, 1]) - lvl(0)(pts[:, 0], pts[:, 1])
        ok = th > 0.006
        m = _cells(pts, lvl(0), lvl(1), gap=0.0026, profile=LOWPRISM, dome=0.002, keep=ok)
        (wing if j < 2 else limbal).extend(m)
    parts.append(mesh_part(_merged(wing), "Wing cells", "Epithelium", "#dcc0d6", CORNEA["wing"], "mucosa", rank=3,
                           detail=(0.08, 0.0, 0.0, 0)))
    parts.append(mesh_part(_merged(limbal), "Limbal epithelium (extra layers)", "Limbus", "#d4b4cf",
                           CORNEA["limbal_epi"], "mucosa", rank=3, detail=(0.08, 0.0, 0.0, 0)))
    sq = Mesh()
    for j in range(2):
        b = lambda X, Z, j=j: y_sup(X, Z) + 0.0085 * j
        t = lambda X, Z, j=j: y_sup(X, Z) + 0.0085 * (j + 1)
        sq.extend(_cells(_lattice(0.08, 0.3, seed=20 + j, margin=0.05), b, t, gap=0.0012, profile=LOWPRISM,
                         dome=0.0012 * j + 0.0006, smooth=1))
    parts.append(mesh_part(_merged(sq), "Superficial squamous cells", "Epithelium", "#f3e5ee", CORNEA["superficial"],
                           "mucosa", rank=4, detail=(0.06, 0.0, 0.0, 0)))
    gob = [(x, at(y_s, x, z) - 0.026, z) for x, z in _lattice(0.07, 0.3, seed=5, x=(0.35, X1 - 0.02),
                                                            z=(Z0 + 0.02, Z1 - 0.02))]
    parts.append(mesh_part(_blobs(gob, (0.013, 0.024, 0.013)), "Conjunctival goblet cells", "Limbus", "#a9d4ee",
                           CORNEA["goblet"], "gland", rank=4, detail=(0.05, 0.0, 0.0, 0)))
    parts.append(hlayer("Tear film", "Epithelium", "#b9e3f2", shift(y_s, 0.006), shift(y_s, 0.014), CORNEA["tear"],
                        "csf", XR, ZR, rank=5, res=120, alpha=0.28))

    # ---------------------------------------------------------------- Bowman layer, stroma, keratocytes
    parts.append(hlayer("Bowman layer", "Anterior cornea", "#f1e7cc", y_bow, shift(y_bm, -0.0005), CORNEA["bowman"],
                        "cartilage", (X0, -0.15), ZR, rank=1, res=160, detail=(0.05, 0.0, 0.0, 0)))
    N = 22
    ribs, hws, hts = [], [], []
    for j in range(N):
        yc = lambda X, j=j: Y_DUA + (j + 0.5) / N * (y_lsb(X) - Y_DUA)
        pitch = lambda X: (y_lsb(X) - Y_DUA) / N
        if j >= 15:                                         # anterior third: narrower, oblique, interwoven
            ang = (0.55 if j % 2 else -0.6) + rng.uniform(-0.15, 0.15)
            hw = 0.042
        else:                                               # posterior: broad lamellae crossing at right angles
            ang = 0.0 if j % 2 == 0 else math.pi / 2
            hw = 0.062
        d = np.array([math.cos(ang), math.sin(ang)])
        perp = np.array([-d[1], d[0]])
        span = abs(perp[0]) * 1.0 + abs(perp[1]) * 0.6
        for k in np.arange(-span - rng.uniform(0, 2 * hw), span + 2 * hw, 2 * hw * 0.985):
            c = perp * k
            ts = np.linspace(-2.4, 2.4, 2000)
            q = c[None] + d[None] * ts[:, None]
            ext = hw * 1.2                                  # run past the side walls; clamped flush below
            inside = (q[:, 0] > X0 - ext) & (q[:, 1] > Z0 - ext) & (q[:, 1] < Z1 + ext)
            inside &= q[:, 0] < x_cs(yc(q[:, 0])) - hw * abs(perp[0]) - 0.004
            if inside.sum() < 4:
                continue
            q = q[inside]
            L = float(np.linalg.norm(q[-1] - q[0]))
            q = q[np.linspace(0, len(q) - 1, max(4, int(L * 12))).astype(int)]
            wob = 0.004 * np.sin(q[:, 0] * 5 + k * 9) + 0.002 * np.sin(q[:, 1] * 7 + j)
            ribs.append(np.column_stack([q[:, 0], yc(q[:, 0]) + wob, q[:, 1]]))
            hws.append(hw * rng.uniform(0.96, 1.04))
            hts.append(pitch(q[:, 0]) * 0.40)
    parts.append(mesh_part(_clamp_box(_ribbons(ribs, hws, hts)), "Stromal lamellae", "Stroma", "#d3e0ec",
                           CORNEA["lamellae"], "tendon", rank=-1, detail=(0.06, 0.0, 0.0, 0)))
    kmesh = Mesh()
    for j in range(N - 1):
        polys = [_star((x, z), int(rng.integers(5, 7)), 0.06, rng)
                 for x, z in _lattice(0.2, 0.4, seed=60 + j, x=(X0 + 0.05, -0.2), z=(Z0 + 0.05, Z1 - 0.05))]
        yg = lambda X, Z, j=j: Y_DUA + (j + 1.0) / N * (y_lsb(X) - Y_DUA)
        kmesh.extend(_prisms(polys, shift(yg, -0.0012), shift(yg, 0.0012), KERATO, dome=0.0022))
    parts.append(mesh_part(_merged(kmesh), "Keratocytes", "Stroma", "#6d8cc4", CORNEA["keratocytes"], "gland",
                           rank=-1, detail=(0.05, 0.0, 0.0, 0)))

    # ---------------------------------------------------------------- posterior cornea
    parts.append(hlayer("Pre-Descemet (Dua) layer", "Posterior cornea", "#e3e9ef", Y_DM, Y_DUA, CORNEA["dua"],
                        "cartilage", (X0, X_SW - 0.03), ZR, rank=-2, res=80, detail=(0.04, 0.0, 0.0, 0)))
    parts.append(hlayer("Descemet membrane", "Posterior cornea", "#efe0b0", Y_EN, Y_DM, CORNEA["descemet"],
                        "cartilage", (X0, X_SW), ZR, rank=-3, res=80, detail=(0.04, 0.0, 0.0, 0)))
    parts.append(mesh_part(tube(np.array([(X_SW, 0.024, Z0 - lat), (X_SW + 0.004, 0.024, 0.0),
                                          (X_SW, 0.024, Z1 + lat)]), 0.017, 16),
                           "Schwalbe line", "Drainage angle", "#e8d49a", CORNEA["schwalbe"], "cartilage", rank=-3))
    endo = _cells(_lattice(0.038, 0.1, seed=7, margin=0.03, x=(X0, X_SW)), const(0.0), const(Y_EN), gap=0.0022,
                  profile=ENDO, dome=0.0035, x=(X0, X_SW))
    parts.append(mesh_part(endo, "Endothelium", "Posterior cornea", "#8cbfd8", CORNEA["endothelium"], "mucosa",
                           rank=-4, detail=(0.06, 0.0, 0.0, 0)))

    # ---------------------------------------------------------------- limbus: stroma, vessels, sclera, drainage angle
    parts.append(hlayer("Limbal stroma & palisades of Vogt", "Limbus", "#eed3c6", y_lsb, y_bow, CORNEA["palisades"],
                        "fascia", (-0.25, X1), ZR, rank=0.5, res=220, detail=(0.12, 70.0, 0.25, 0)))
    loops, lr = [], []
    for zc in np.arange(Z0 + 0.03, Z1, 0.12):              # a hairpin loop up each palisade ridge
        z = zc - 0.02 * np.sin(7 * 0.5)
        pts = [(0.33, 0.83, z - 0.012), (0.1, 0.842, z - 0.01), (-0.05, 0.85, z - 0.008), (-0.105, 0.853, z),
               (-0.05, 0.85, z + 0.008), (0.1, 0.842, z + 0.01), (0.33, 0.83, z + 0.012)]
        loops.append(smooth_path(np.array(pts), 40))
        lr.append(0.0055)
    arc_a = [smooth_path(np.array([(0.35, 0.815, Z0 - lat), (0.34, 0.81, 0.0), (0.35, 0.815, Z1 + lat)]), 40)]
    arc_v = [smooth_path(np.array([(0.47, 0.8, Z0 - lat), (0.48, 0.805, 0.0), (0.47, 0.8, Z1 + lat)]), 40)]
    art = _tubes(loops, lr, 8)
    art.extend(_tubes(arc_a, 0.014, 14))
    conj = (_crossings(1.35, 0.16, 0.835, 45, 0.02, x=(0.36, X1)) + _crossings(0.1, 0.3, 0.8, 46, 0.02, x=(0.4, X1)))
    art.extend(_tubes(conj, 0.0065, 8))
    parts.append(mesh_part(_merged(art), "Limbal vascular arcades", "Limbus", "#d63d33", CORNEA["arcades"], "artery",
                           rank=0.5))
    # Schlemm canal: flat oval section, running round the limbus (along z here)
    SC_X, SC_Y, SC_RX, SC_RY = 0.29, 0.225, 0.075, 0.022
    col_paths = [smooth_path(np.array([(0.32, SC_Y + 0.01, zc), (0.35, 0.35, zc + 0.02), (0.41, 0.55, zc + 0.03),
                                       (0.47, 0.79, zc + 0.02)]), 30) for zc in (-0.3, 0.25)]
    scl = Volume((-0.2, 0.0, Z0), (X1, 0.8, Z1), 0.0085)
    x, y, z = scl.axes()
    d = np.maximum.reduce([np.broadcast_to(x_cs(y) - x, scl.shape), np.broadcast_to(y_tm(x) - y, scl.shape),
                           np.broadcast_to(y - y_lsb(x), scl.shape)]).astype(np.float32)
    spur = np.sqrt(((x - 0.48) / 0.07) ** 2 + ((y - 0.16) / 0.1) ** 2) - 1.0      # scleral spur
    d = np.minimum(d, np.broadcast_to(spur * 0.05, scl.shape).astype(np.float32))
    canal = np.sqrt(((x - SC_X) / (SC_RX + 0.008)) ** 2 + ((y - SC_Y) / (SC_RY + 0.008)) ** 2) - 1.0
    d = np.maximum(d, np.broadcast_to(-canal * 0.025, scl.shape).astype(np.float32))
    scl.d = d
    for p in col_paths:
        scl.tube(p, 0.014, "subtract")
    scl.intersect_box((-0.2, 0.0, Z0), (X1, 0.8, Z1))
    # dense irregular collagen: bundles running in every direction give the walls a woven relief, in contrast to
    # the orderly plywood of the corneal lamellae next to it
    x, y, z = scl.axes()
    ridge = lambda f: 1.0 - np.abs(f)                     # sharp-crested, fibre-like ridges
    scl.d -= 0.0045 * (ridge(fbm3(x * 3.0, y * 34.0, z * 34.0, 1.0, 2, 11))
                       + ridge(fbm3(x * 34.0, y * 34.0, z * 3.0, 1.0, 2, 12))
                       + ridge(fbm3(x * 28.0, y * 4.0, z * 28.0, 1.0, 2, 13)) - 2.0).astype(np.float32)
    parts.append(sdf_part(scl, "Sclera", "Limbus", "#f3eee2", CORNEA["sclera"], "ligament", smooth=0.8, rank=-1,
                          bulk=True, detail=(0.1, 0.0, 0.0, 3)))
    sc = _oval_shell((SC_X, SC_Y), SC_RX, SC_RY, 0.006, (Z0 - lat, Z1 + lat))
    parts.append(mesh_part(sc, "Schlemm canal", "Drainage angle", "#9cc9e3", CORNEA["schlemm"], "vein",
                           rank=-1))
    col = _tubes(col_paths, 0.009, 10)
    col.extend(_tubes(arc_v, 0.016, 14))
    parts.append(mesh_part(_merged(col), "Collector channels & aqueous veins", "Drainage angle",
                           "#86a8dd", CORNEA["collector"], "vein", rank=-1))
    beams, br = [], []
    for yy in np.arange(0.035, 0.2, 0.034):                 # circumferential beams, stacked like perforated sheets
        for xx in np.arange(X_SW + 0.03, 0.53, 0.04):
            if yy < y_tm(xx) - 0.012 and (xx - SC_X) ** 2 / 0.09 ** 2 + (yy - SC_Y) ** 2 / 0.035 ** 2 > 1:
                zz = np.linspace(Z0 - lat, Z1 + lat, 30)
                beams.append(np.column_stack([xx + 0.006 * np.sin(zz * 11 + yy * 40),
                                              yy + 0.004 * np.sin(zz * 9 + xx * 30), zz]))
                br.append(0.0075)
    for zz in np.arange(Z0 + 0.04, Z1, 0.09):               # radial struts linking them
        for yy in np.arange(0.05, 0.19, 0.05):
            xs_ = np.linspace(X_SW + 0.03 + 0.25 * (yy - 0.03), 0.51, 12)
            ok = yy < y_tm(xs_) - 0.012
            if ok.sum() >= 3:
                beams.append(np.column_stack([xs_[ok], np.full(ok.sum(), yy), zz + 0.01 * np.sin(xs_[ok] * 20)]))
                br.append(0.0055)
    parts.append(mesh_part(_tubes(beams, br, 8), "Trabecular meshwork", "Drainage angle", "#d6b27e", CORNEA["tm"],
                           "fascia", rank=-3))

    # ---------------------------------------------------------------- nerves
    trunks, tr, fib, fr = [], [], [], []
    for i, zc in enumerate((-0.38, 0.02, 0.4)):
        x_in = -0.62 + 0.1 * i                                 # where the nerve pierces Bowman layer
        yb = at(y_bm, x_in, zc)
        ctrl = np.array([(X1 + lat, 0.45 + 0.05 * i, zc), (0.45, 0.5 + 0.05 * i, zc + 0.03),
                         (-0.2, 0.6 + 0.03 * i, zc - 0.03), (x_in + 0.1, 0.78, zc), (x_in, yb - 0.01, zc + 0.02)])
        p = smooth_path(ctrl, 60)
        trunks.append(p)
        tr.append(np.linspace(0.016, 0.007, len(p)))
        for k in range(4):
            a = (k - 1.5) * 0.35 + rng.uniform(-0.1, 0.1)
            end = np.array([x_in - 0.8 * math.cos(a), 0, zc + 0.5 * math.sin(a)])
            xs_ = np.linspace(x_in, max(X0 - lat, end[0]), 40)
            zs_ = np.clip(np.linspace(zc + 0.02, end[2], 40) + 0.01 * np.sin(xs_ * 13 + k), Z0 + 0.01, Z1 - 0.01)
            ys_ = np.array([at(y_bm, xx, zz) for xx, zz in zip(xs_, zs_)]) + 0.0045
            fib.append(np.column_stack([xs_, ys_, zs_]))
            fr.append(0.0028 + 0.0008 * np.sin(np.linspace(0, 60, 40)) ** 2)          # beaded fibres
            for t in np.linspace(8, 36, 4).astype(int):
                b0 = np.array([xs_[t], ys_[t], zs_[t]])
                fib.append(np.array([b0, b0 + (0.004, 0.025, 0.003), b0 + (0.006, 0.05, 0.004)]))
                fr.append(np.array([0.0024, 0.0018, 0.0012]))
    parts.append(mesh_part(_tubes(trunks, tr, 12), "Stromal nerves", "Nerves", "#f0cf45", CORNEA["nerves"], "nerve",
                           rank=0))
    parts.append(mesh_part(_tubes(fib, fr, 6), "Subbasal plexus & free nerve endings", "Nerves", "#f5dc6a",
                           CORNEA["plexus"], "nerve", rank=2.5))
    # the corneal apex is at x = -1 and the surface falls away towards the limbus, as on the side of a globe
    warp_parts(parts, lambda p: np.column_stack([0 * p[:, 0], 0.3 * (1 - ((p[:, 0] + 1.0) / 2.4) ** 2
                                                                    - (p[:, 2] / 0.85) ** 2), 0 * p[:, 0]]))
    return settle(parts, seed=402, amp_xz=0.016, amp_y=0.022, freq=1.4, grain=0.0022, micro=0.0015, micro_freq=24.0)


# =============================================================================== retina
RETINA = {
    "sclera": "Sclera: dense irregular collagen coat of the eye, continuous with the dura of the optic nerve sheath "
              "behind and the corneal stroma in front. Its innermost layer (lamina fusca) carries melanocytes.",
    "choroid": "Choroid stroma: loose pigmented connective tissue with melanocytes, the outer large-vessel (Haller) "
               "and inner medium-vessel (Sattler) layers. The choroid has the highest blood flow per gram of any "
               "tissue and extracts so little oxygen that its venous blood is almost arterial. Choroidal naevi and "
               "melanoma arise from its melanocytes.",
    "melano": "Choroidal melanocytes: dendritic pigment cells that absorb light passing the retina and RPE. They "
              "are the cells of origin of uveal melanoma, the commonest primary intraocular malignancy of adults "
              "(spreads to the liver).",
    "arteries": "Choroidal arteries: branches of the short posterior ciliary arteries (from the ophthalmic artery), "
                "lying mostly in the inner, medium-vessel (Sattler) layer before they open into the "
                "choriocapillaris.",
    "veins": "Choroidal veins: the large vessels of the outer (Haller) layer, draining through the four vortex veins "
             "into the ophthalmic veins.",
    "cc": "Choriocapillaris: a single sheet of wide (up to 20 µm), fenestrated capillaries arranged in lobules "
          "directly beneath Bruch membrane. It supplies the RPE and photoreceptors - the outer third of the retina - "
          "by diffusion, and is the only supply of the avascular fovea.",
    "bruch": "Bruch membrane: a 2-4 µm, five-layered sheet (RPE basement membrane, inner collagenous, elastic, outer "
             "collagenous, choriocapillaris basement membrane). Drusen accumulate between the RPE and it in "
             "age-related macular degeneration; breaks let choroidal new vessels grow into the retina (wet AMD).",
    "rpe": "Retinal pigment epithelium: one layer of hexagonal cuboidal cells, melanin granules apically, joined by "
           "tight junctions that form the outer blood-retina barrier. Long apical microvilli embrace the outer "
           "segments; each cell phagocytoses the discs shed daily by ~30 photoreceptors and regenerates "
           "11-cis-retinal (RPE65) for the visual cycle. Retinal detachment opens the potential space between it "
           "and the photoreceptors.",
    "rod_os": "Rod outer segments: stacks of ~1000 free-floating membrane discs packed with rhodopsin; new discs "
              "form at the base and the oldest are shed from the tip into the RPE, renewing the segment every ~10 "
              "days. Rods (~120 million) are very sensitive, saturate in daylight and are absent from the foveola; "
              "they are lost first in retinitis pigmentosa (night blindness, then tunnel vision).",
    "rod_is": "Rod inner segments: the mitochondria-packed ellipsoid and the myoid (protein synthesis), joined to "
              "the outer segment by a modified non-motile connecting cilium - hence retinal degeneration in "
              "ciliopathies such as Usher and Bardet-Biedl syndromes.",
    "cones": "Cones (~6 million): short tapering outer segments whose discs stay continuous with the cell membrane, "
             "a fat mitochondria-rich inner segment, a nucleus in the outermost row of the ONL, an axon and a broad "
             "synaptic pedicle in the OPL. S, M or L opsins give colour vision and high acuity; cones outnumber rods "
             "only at the fovea. Here roughly 1 in 10 photoreceptors is a cone, as in the paramacular retina.",
    "olm": "Outer limiting membrane: not a membrane but a row of adherens junctions between the apical processes of "
           "Müller cells and the photoreceptor inner segments. Its integrity on OCT predicts visual recovery after "
           "macular surgery.",
    "onl": "Outer nuclear layer: the cell bodies and small, dark nuclei of the rods and cones, stacked several deep "
           "(4-5 rows peripherally, ~10 at the fovea). It has no blood vessels - it is fed from the choroid - and "
           "thins as photoreceptors die in retinitis pigmentosa.",
    "opl": "Outer plexiform layer: synapses of rod spherules and cone pedicles on bipolar dendrites and horizontal "
           "cell processes (ribbon synapses). At the macula the cone axons run obliquely as the Henle fibre layer, "
           "where fluid collects in the petaloid spaces of cystoid macular oedema. Hard exudates collect here.",
    "inl": "Inner nuclear layer: nuclei of horizontal cells (outer border), bipolar and Müller cells (middle) and "
           "amacrine cells (inner border). The deep capillary plexus at its outer border marks the limit of the "
           "central retinal artery territory, so retinal artery occlusion spares the ONL and photoreceptors.",
    "ipl": "Inner plexiform layer: bipolar axon terminals, amacrine processes and ganglion dendrites. It is "
           "stratified: OFF-pathway contacts in its outer half, ON-pathway contacts in its inner half.",
    "gcl": "Ganglion cell layer: ~1.2 million retinal ganglion cells, one cell deep outside the macula but up to "
           "8-10 deep around the fovea; also displaced amacrine cells. Ganglion cells are the only retinal neurons "
           "that fire action potentials; midget (parvo), parasol (magno) and melanopsin-containing cells (pupil "
           "reflex, circadian rhythm) project via the optic nerve. Their loss causes the arcuate field defects of "
           "glaucoma.",
    "nfl": "Nerve fibre layer: ganglion cell axons gathered into bundles that sweep towards the optic disc, "
           "unmyelinated until they pass the lamina cribrosa so the retina stays transparent. OCT measures its "
           "thickness to follow glaucoma; ischaemic swelling of its axons produces cotton-wool spots, and bleeding "
           "along the bundles gives flame haemorrhages.",
    "ilm": "Inner limiting membrane: the basement membrane of the Müller cell end-feet, facing the vitreous; shown "
           "translucent so the fibre bundles and vessels read as they do on fundoscopy. Surgeons peel it to close "
           "macular holes and remove epiretinal membranes.",
    "arteriole": "Retinal arteriole: branch of the central retinal artery running in the nerve fibre layer with a "
                 "small branch diving to the deep capillary plexus. Retinal vessels are end arteries with a tight "
                 "endothelium (inner blood-retina barrier) and no autonomic innervation. Occlusion whitens the "
                 "inner retina and leaves a cherry-red spot at the fovea.",
    "venule": "Retinal venule: wider and darker than its arteriole, draining to the central retinal vein. At "
              "arteriovenous crossings the two share an adventitial sheath - the usual site of branch retinal vein "
              "occlusion and of the AV nicking of hypertension.",
    "sup_plexus": "Superficial capillary plexus in the ganglion cell and nerve fibre layers, one of the retinal "
                  "capillary beds imaged by OCT angiography. Loss of capillary pericytes and microaneurysms are the "
                  "first lesions of diabetic retinopathy.",
    "deep_plexus": "Deep capillary plexus at the border of the inner nuclear and outer plexiform layers - the "
                   "outer limit of the retinal circulation. Everything outside it (ONL, photoreceptors) depends on "
                   "the choriocapillaris.",
    "muller": "Müller glia: radial glial cells spanning the whole retina, from microvilli beyond the outer limiting "
              "membrane to the conical end-feet that build the inner limiting membrane, with their nuclei in the "
              "INL. They buffer potassium, recycle glutamate (glutamine synthetase), store glycogen and even guide "
              "light to the photoreceptors.",
    "bipolar": "Bipolar cells: first-order interneurons with dendrites in the OPL and an axon ending in the IPL. "
               "ON bipolars (mGluR6, sign-inverting) end deep in the IPL, OFF bipolars (ionotropic receptors) end "
               "superficially; rod bipolars are all ON. They carry graded potentials, not spikes.",
    "horizontal": "Horizontal cells: flat cells at the outer edge of the INL whose long processes spread in the "
                  "OPL and feed back onto photoreceptor terminals, creating the centre-surround (lateral "
                  "inhibition) organisation of receptive fields.",
    "amacrine": "Amacrine cells: axonless interneurons at the inner edge of the INL whose processes spread in "
                "strata of the IPL - over 30 types, including AII cells relaying rod signals into cone pathways, "
                "starburst cells (direction selectivity, acetylcholine) and dopaminergic cells (light adaptation).",
    "vitreous": "Vitreous body: transparent gel of collagen II fibrils and hyaluronan, attached most firmly at the "
                "vitreous base, disc and macula. Posterior vitreous detachment with age can tear the retina, "
                "causing flashes, floaters and rhegmatogenous detachment.",
}


def _row(spacing, shift, jitter, seed, y, x=XR, z=ZR, margin=0.0):
    """One row of a close-packed stack: a hexagonal lattice shifted by `shift` (0, 1 or 2 thirds of a lattice
    step, like A, B and C layers of stacked spheres), at height y."""
    pts = hex_points((x[0] - spacing, z[0] - spacing), (x[1] + spacing, z[1] + spacing), spacing, 0.0, seed)
    pts = pts + np.array([0.5, math.sqrt(3) / 6]) * spacing * shift
    rng = np.random.default_rng(seed)
    pts += rng.uniform(-jitter, jitter, pts.shape) * spacing
    keep = ((pts[:, 0] > x[0] - margin) & (pts[:, 0] < x[1] + margin) & (pts[:, 1] > z[0] - margin)
            & (pts[:, 1] < z[1] + margin))
    pts = pts[keep]
    return np.column_stack([pts[:, 0], np.full(len(pts), float(y)), pts[:, 1]])


def _branch(rng, start, direction, length, r0, r1, n=4, wobble=0.25):
    """A gently curving tapered process from `start` along `direction`."""
    d = np.asarray(direction, float)
    d /= np.linalg.norm(d)
    pts = [np.asarray(start, float)]
    for k in range(n):
        d = d + rng.normal(size=3) * wobble * np.array([1.0, 0.35, 1.0])
        d /= np.linalg.norm(d)
        pts.append(pts[-1] + d * length / n)
    return np.array(pts), np.linspace(r0, r1, n + 1)


def build_retina():
    parts = []
    rng = np.random.default_rng(11)
    lat = 0.0035                                           # how far cells poke past the side walls

    # ---------------------------------------------------------------- level plan (vitreous side up, like a section)
    Y_SCL, Y_CH, Y_BR0, Y_BR1 = 0.07, 0.205, 0.224, 0.232
    Y_RPE, Y_OS0, Y_OS1, Y_IS1, Y_OLM = 0.262, 0.255, 0.333, 0.402, 0.408
    Y_OPL0, Y_OPL1, Y_IPL0, Y_IPL1 = 0.522, 0.572, 0.652, 0.738
    Y_GC, Y_NFL, Y_ILM = 0.757, 0.803, 0.831
    za = lambda x: 0.24 + 0.03 * np.sin(np.asarray(x) * 2.1 + 0.5)          # arteriole course (z of x)
    zv = lambda x: -0.20 + 0.035 * np.sin(np.asarray(x) * 1.7 + 2.0)        # venule course
    RA, RV = 0.016, 0.021

    def nz(amp, freq, seed):
        return noise2(amp, freq, seed=seed)

    # ---------------------------------------------------------------- choroid and sclera
    parts.append(hlayer("Sclera", "Choroid & sclera", "#efe9dc", 0.0, add(Y_SCL, nz(0.004, 3.0, 1)), RETINA["sclera"],
                        "ligament", XR, ZR, bulk=True, rank=-9, res=100, detail=(0.1, 40.0, 0.12, 1)))
    parts.append(hlayer("Choroid stroma", "Choroid & sclera", "#6b2c33", add(Y_SCL + 0.003, nz(0.004, 3.0, 1)), Y_CH,
                        RETINA["choroid"], "organ", XR, ZR, bulk=True, rank=-8, res=100,
                        detail=(0.16, 90.0, 0.35, 0)))
    # the choroid is mostly vessels: large veins outside (Haller), medium arteries inside (Sattler), crossing the
    # block obliquely so every side wall shows them cut across
    veins = _crossings(0.55, 0.2, 0.108, 1, 0.05) + _crossings(2.45, 0.22, 0.118, 2, 0.05, offset=0.5)
    arts = _crossings(1.05, 0.17, 0.163, 3, 0.04) + _crossings(-0.35, 0.19, 0.17, 4, 0.04, offset=0.3)
    vr = [np.full(len(p), rng.uniform(0.022, 0.03)) for p in veins]
    ar = [np.full(len(p), rng.uniform(0.011, 0.015)) for p in arts]
    parts.append(mesh_part(_tubes(veins, vr, 18), "Choroidal veins (Haller layer)", "Choroid & sclera",
                           "#8e3552", RETINA["veins"], "vein", rank=-8))
    parts.append(mesh_part(_tubes(arts, ar, 12), "Choroidal arteries (Sattler layer)", "Choroid & sclera",
                           "#c23b30", RETINA["arteries"], "artery", rank=-8))
    mel_c, mel_p = [], []
    for x, z in _lattice(0.17, 0.35, seed=31, x=(X0 + 0.03, X1 - 0.03), z=(Z0 + 0.03, Z1 - 0.03)):
        c = np.array([x, rng.uniform(0.085, 0.195), z])
        mel_c.append(c)
        for k in range(4):
            a = k * 2 * math.pi / 4 + rng.uniform(-0.4, 0.4)
            p, r = _branch(rng, c, (math.cos(a), rng.uniform(-0.15, 0.15), math.sin(a)), rng.uniform(0.03, 0.05),
                           0.004, 0.0012, 3)
            p[:, 1] = np.clip(p[:, 1], Y_SCL + 0.008, Y_CH - 0.008)
            mel_p.append((p, r))
    mel = _blobs(mel_c, (0.011, 0.006, 0.009), _yaw(rng.uniform(0, math.pi, len(mel_c))))
    mel.extend(_tubes([p for p, _ in mel_p], [r for _, r in mel_p], 6))
    parts.append(mesh_part(_merged(mel), "Choroidal melanocytes", "Choroid & sclera", "#2a1a14", RETINA["melano"],
                           "organ", rank=-8, detail=(0.05, 0.0, 0.0, 0)))
    cc = _capillaries(0.214, 0.06, 0.0105, seed=21, ry=0.0065, segments=5)
    parts.append(mesh_part(cc, "Choriocapillaris", "Choroid & sclera", "#cc4a3e", RETINA["cc"], "artery", rank=-7))
    parts.append(hlayer("Bruch membrane", "Choroid & sclera", "#efe0bd", Y_BR0, Y_BR1, RETINA["bruch"], "cartilage",
                        XR, ZR, rank=-6.5, res=60, detail=(0.03, 0.0, 0.0, 0)))

    # ---------------------------------------------------------------- RPE and photoreceptors
    rpe = _cells(_lattice(0.042, 0.12, seed=3, margin=0.05), const(Y_BR1 + 0.001), const(Y_RPE), gap=0.0028,
                 dome=0.004, profile=LOWPRISM)
    parts.append(mesh_part(rpe, "Retinal pigment epithelium", "Outer retina", "#3a2620", RETINA["rpe"], "mucosa",
                           rank=-6, detail=(0.08, 0.0, 0.0, 0)))
    pr = _lattice(0.027, 0.16, seed=4, x=(X0 + 0.004, X1 - 0.004), z=(Z0 + 0.004, Z1 - 0.004))
    is_cone = rng.random(len(pr)) < 0.1
    os_paths, is_paths, is_r = [], [], []
    for x, z in pr[~is_cone]:
        dx, dz = rng.normal(scale=0.0012, size=2)
        os_paths.append(np.array([(x + dx, Y_OS0, z + dz), (x + dx * 0.3, Y_OS1 - 0.006, z + dz * 0.3),
                                  (x, Y_OS1 + 0.001, z)]))
        is_paths.append(np.array([(x, Y_OS1 + 0.001, z), (x, Y_OS1 + 0.008, z), (x, Y_OS1 + 0.032, z),
                                  (x, Y_IS1 + 0.002, z)]))
        is_r.append(np.array([0.0016, 0.0058, 0.0073, 0.0052]))
    os_r = [np.array([0.0052, 0.0052, 0.0016])] * len(os_paths)
    parts.append(mesh_part(_tubes(os_paths, os_r, 5, caps=False), "Rod outer segments", "Outer retina", "#d9c79c",
                           RETINA["rod_os"], "nerve", rank=-5, detail=(0.04, 0.0, 0.0, 2)))
    parts.append(mesh_part(_tubes(is_paths, is_r, 5, caps=False), "Rod inner segments", "Outer retina", "#e6b39c",
                           RETINA["rod_is"], "nerve", rank=-5, detail=(0.04, 0.0, 0.0, 2)))
    cones = Mesh()
    cone_xz = pr[is_cone]
    cpaths, cr = [], []
    for x, z in cone_xz:
        cpaths.append(np.array([(x, Y_OS0 + 0.035, z), (x, Y_OS1 - 0.02, z), (x, Y_OS1, z), (x, Y_OS1 + 0.004, z),
                                (x, Y_OS1 + 0.02, z), (x, Y_OS1 + 0.042, z), (x, Y_IS1 - 0.01, z),
                                (x, Y_IS1 + 0.003, z)]))
        cr.append(np.array([0.0028, 0.006, 0.0088, 0.0098, 0.0128, 0.0133, 0.0105, 0.0065]))
        cpaths.append(np.array([(x, Y_OLM + 0.026, z), (x + 0.002, Y_OLM + 0.07, z), (x, Y_OPL0 + 0.004, z)]))
        cr.append(np.array([0.003, 0.0024, 0.0028]))
    cones.extend(_tubes(cpaths, cr, 7))
    cones.extend(_blobs(np.column_stack([cone_xz[:, 0], np.full(len(cone_xz), Y_OLM + 0.016), cone_xz[:, 1]]),
                        (0.0125, 0.0145, 0.0125)))
    cones.extend(_blobs(np.column_stack([cone_xz[:, 0], np.full(len(cone_xz), Y_OPL0 + 0.01), cone_xz[:, 1]]),
                        (0.0125, 0.006, 0.0125)))
    parts.append(mesh_part(_merged(cones), "Cones", "Outer retina", "#8fbde6", RETINA["cones"], "nerve", rank=-5,
                           detail=(0.04, 0.0, 0.0, 2)))
    parts.append(hlayer("Outer limiting membrane", "Outer retina", "#efe6d4", Y_IS1, Y_OLM, RETINA["olm"],
                        "cartilage", XR, ZR, rank=-4.5, res=60, detail=(0.02, 0.0, 0.0, 0)))

    # ---------------------------------------------------------------- Müller glia (placed first: nuclei avoid them)
    mu_xz = _lattice(0.1, 0.22, seed=10, x=(X0 + 0.03, X1 - 0.03), z=(Z0 + 0.03, Z1 - 0.03))
    mu_tree = cKDTree(mu_xz)

    def free(pts, r, tree, extra=()):
        ok = tree.query(pts[:, [0, 2]])[0] > r
        for t, rr in extra:
            ok &= t.query(pts[:, [0, 2]])[0] > rr
        return pts[ok]

    cone_tree = cKDTree(cone_xz)
    onl = []
    for k, (y, sh) in enumerate(((Y_OLM + 0.021, 0), (Y_OLM + 0.058, 1), (Y_OLM + 0.095, 2))):
        row = _row(0.04, sh, 0.1, 40 + k, y, margin=0.01)
        row = free(row, 0.012, mu_tree, [(cone_tree, 0.024)] if k == 0 else ())
        onl.append(row)
    onl = np.vstack(onl)
    onl_r = np.column_stack([rng.uniform(0.0155, 0.0172, len(onl)), rng.uniform(0.0175, 0.0192, len(onl)),
                             rng.uniform(0.0155, 0.0172, len(onl))])
    parts.append(mesh_part(_blobs(onl, onl_r, _yaw(rng.uniform(0, 2, len(onl))), sub=-1), "Outer nuclear layer",
                           "Neural retina layers", "#4b3a8c", RETINA["onl"], "nucleus", rank=-4,
                           detail=(0.07, 0.0, 0.0, 0)))
    parts.append(hlayer("Outer plexiform layer", "Neural retina layers", "#e8c3d2", add(Y_OPL0, nz(0.003, 4, 3)),
                        add(Y_OPL1, nz(0.003, 4, 5)), RETINA["opl"], "brain", XR, ZR, rank=-3.5, res=120,
                        detail=(0.08, 90.0, 0.08, 0)))

    # ---------------------------------------------------------------- inner nuclear layer and its four cell types
    inl_o = free(_row(0.042, 0, 0.1, 50, Y_OPL1 + 0.019, margin=0.01), 0.018, mu_tree)
    inl_i = free(_row(0.042, 1, 0.1, 51, Y_OPL1 + 0.061, margin=0.01), 0.014, mu_tree)
    roll_o, roll_i = rng.random(len(inl_o)), rng.random(len(inl_i))
    hor = inl_o[roll_o < 0.1]
    ama = inl_i[roll_i < 0.24]
    bip = np.vstack([inl_o[(roll_o >= 0.1) & (roll_o < 0.2)], inl_i[(roll_i >= 0.24) & (roll_i < 0.33)]])
    rest = np.vstack([inl_o[roll_o >= 0.2], inl_i[roll_i >= 0.33]])
    parts.append(mesh_part(_blobs(rest, (0.0155, 0.0175, 0.0155), _yaw(rng.uniform(0, 2, len(rest))), sub=-1),
                           "Inner nuclear layer", "Neural retina layers",
                           "#5d4a9e", RETINA["inl"], "nucleus", rank=-3, detail=(0.07, 0.0, 0.0, 0)))
    paths, radii = [], []
    for c in hor:
        for k in range(6):
            a = k * math.pi / 3 + rng.uniform(-0.35, 0.35)
            p, r = _branch(rng, c + np.array([0, -0.004, 0]), (math.cos(a), -0.28, math.sin(a)),
                           rng.uniform(0.06, 0.1), 0.0045, 0.0014, 4, 0.2)
            p[1:, 1] = np.clip(p[1:, 1], Y_OPL0 + 0.01, Y_OPL1 - 0.006)
            paths.append(p)
            radii.append(r)
    m = _blobs(hor, (0.024, 0.011, 0.022), _yaw(rng.uniform(0, math.pi, len(hor))))
    m.extend(_tubes(paths, radii, 5))
    parts.append(mesh_part(_merged(m), "Horizontal cells", "Retinal neurons & glia", "#3aa39a",
                           RETINA["horizontal"], "nerve", rank=-2.5, detail=(0.05, 0.0, 0.0, 0)))
    paths, radii, ends = [], [], []
    for c in bip:
        y_t = Y_IPL0 + (0.026 if rng.random() < 0.5 else 0.064)           # OFF or ON sublamina
        top = np.array([c[0] + rng.uniform(-0.01, 0.01), y_t, c[2] + rng.uniform(-0.01, 0.01)])
        paths.append(np.array([c + (0, 0.015, 0), (c + top) / 2 + (rng.uniform(-0.004, 0.004), 0, 0), top]))
        radii.append(np.array([0.0045, 0.0028, 0.0025]))
        ends.append(top)
        base = np.array([c[0], Y_OPL1 - 0.004, c[2]])
        paths.append(np.array([c - (0, 0.012, 0), base]))
        radii.append(np.array([0.004, 0.003]))
        for k in range(3):
            a = k * 2.1 + rng.uniform(0, 1)
            paths.append(np.array([base, base + (0.012 * math.cos(a), -0.014, 0.012 * math.sin(a)),
                                   base + (0.018 * math.cos(a), -0.026, 0.018 * math.sin(a))]))
            radii.append(np.array([0.0026, 0.0018, 0.0012]))
    m = _blobs(bip, (0.0115, 0.019, 0.0115))
    m.extend(_blobs(ends, (0.0075, 0.005, 0.0075)))
    m.extend(_tubes(paths, radii, 5))
    parts.append(mesh_part(_merged(m), "Bipolar cells", "Retinal neurons & glia", "#e0923f", RETINA["bipolar"],
                           "nerve", rank=-2.5, detail=(0.05, 0.0, 0.0, 0)))
    paths, radii = [], []
    for c in ama:
        y_s = Y_IPL0 + rng.choice([0.022, 0.042, 0.062])
        s = np.array([c[0] + rng.uniform(-0.006, 0.006), y_s, c[2] + rng.uniform(-0.006, 0.006)])
        paths.append(np.array([c + (0, 0.012, 0), s]))
        radii.append(np.array([0.0045, 0.003]))
        for k in range(rng.integers(3, 5)):
            a = rng.uniform(0, 2 * math.pi)
            p, r = _branch(rng, s, (math.cos(a), 0.0, math.sin(a)), rng.uniform(0.04, 0.08), 0.0028, 0.0012, 3, 0.3)
            p[:, 1] = np.clip(p[:, 1], Y_IPL0 + 0.006, Y_IPL1 - 0.006)
            paths.append(p)
            radii.append(r)
    m = _blobs(ama, (0.0175, 0.0165, 0.0175))
    m.extend(_tubes(paths, radii, 5))
    parts.append(mesh_part(_merged(m), "Amacrine cells", "Retinal neurons & glia", "#c4588f", RETINA["amacrine"],
                           "nerve", rank=-2.5, detail=(0.05, 0.0, 0.0, 0)))
    parts.append(hlayer("Inner plexiform layer", "Neural retina layers", "#ebcddb", add(Y_IPL0, nz(0.003, 4, 7)),
                        add(Y_IPL1, nz(0.003, 4, 9)), RETINA["ipl"], "brain", XR, ZR, rank=-2, res=120,
                        detail=(0.08, 90.0, 0.06, 0)))

    # ---------------------------------------------------------------- ganglion cells and nerve fibre layer
    gc = Volume((X0, Y_IPL0 + 0.01, Z0), (X1, 0.83, Z1), 0.0065)
    for i, (px, pz) in enumerate(_lattice(0.082, 0.3, seed=6, x=(X0 + 0.02, X1 - 0.02), z=(Z0 + 0.02, Z1 - 0.02))):
        if min(abs(pz - za(px)), abs(pz - zv(px))) < 0.03:
            continue                                          # the big vessels sit on this layer
        s = rng.uniform(0.8, 1.3)                             # midget cells small, parasol cells large
        c = np.array([px, Y_GC, pz])
        hill = c + np.array([-0.012, 0.022 * s, 0.0])
        shapes = [ellipsoid(c, (0.021 * s, 0.016 * s, 0.02 * s)),
                  round_cone(c, hill, 0.008 * s, 0.004),
                  round_cone(hill, hill + np.array([-0.07, 0.014, rng.uniform(-0.01, 0.01)]), 0.004, 0.0035)]
        for k in range(rng.integers(3, 5)):
            a = rng.uniform(0, 2 * math.pi)
            mid = c + np.array([0.03 * math.cos(a) * s, -0.035, 0.03 * math.sin(a) * s])
            shapes.append(round_cone(c, mid, 0.0065 * s, 0.0035))
            shapes.append(round_cone(mid, mid + np.array([0.035 * math.cos(a + 0.4), -0.02, 0.035 * math.sin(a + 0.4)]),
                                     0.0035, 0.002))
        gc.add_all(shapes, "smooth", 0.006)
    parts.append(sdf_part(gc, "Ganglion cell layer", "Neural retina layers", "#a77ac8", RETINA["gcl"], "nucleus",
                          smooth=0.6, rank=-1, detail=(0.05, 60.0, 0.9, 0)))
    bundles, bry = [], []
    for row, (y, off) in enumerate(((Y_NFL - 0.017, 0.0), (Y_NFL, 0.013), (Y_NFL + 0.017, 0.006))):
        for z in np.arange(Z0 + 0.012 + off, Z1, 0.026):
            if row > 0 and min(abs(z - 0.24), abs(z + 0.2)) < 0.075:
                continue                                  # the big vessels sit in the inner part of the layer
            p = wavy_path((X0 - lat, y, z), (X1 + lat, y + rng.uniform(-0.002, 0.002), z + rng.uniform(-0.01, 0.01)),
                          50, 0.004, 1.5, seed=int(z * 1000) + row * 7)
            bundles.append(p)
            bry.append(0.0085)
    parts.append(mesh_part(_tubes(bundles, 0.0135, 10, ry=bry), "Nerve fibre layer", "Neural retina layers",
                           "#f1e3c3", RETINA["nfl"], "white_matter", rank=0, detail=(0.05, 60.0, 0.1, 1)))
    xs = np.linspace(X0 - lat, X1 + lat, 90)
    ra = [np.column_stack([xs, np.full_like(xs, Y_NFL + 0.006), za(xs)])]
    dive = smooth_path(np.array([(0.12, Y_NFL + 0.002, za(0.12)), (0.2, Y_IPL1, za(0.12) - 0.05),
                                 (0.26, Y_IPL0 + 0.005, za(0.12) - 0.09), (0.3, Y_OPL1 + 0.004, za(0.12) - 0.1)]),
                       30)
    art = _tubes(ra, RA, 20)
    art.extend(tube(dive, np.linspace(0.008, 0.005, len(dive)), 12))
    parts.append(mesh_part(_merged(art), "Retinal arteriole", "Retinal vessels", "#d33a31", RETINA["arteriole"],
                           "artery", rank=0.5))
    rv = [np.column_stack([xs, np.full_like(xs, Y_NFL + 0.008), zv(xs)])]
    rise = smooth_path(np.array([(-0.5, Y_OPL1 + 0.004, zv(-0.5) + 0.1), (-0.46, Y_IPL0 + 0.005, zv(-0.5) + 0.09),
                                 (-0.42, Y_IPL1, zv(-0.5) + 0.05), (-0.38, Y_NFL + 0.006, zv(-0.38))]), 30)
    ven = _tubes(rv, RV, 20)
    ven.extend(tube(rise, np.linspace(0.006, 0.009, len(rise)), 12))
    parts.append(mesh_part(_merged(ven), "Retinal venule", "Retinal vessels", "#7b2d5c", RETINA["venule"], "vein",
                           rank=0.5))
    parts.append(mesh_part(_capillaries(Y_GC + 0.012, 0.1, 0.0045, seed=23), "Superficial capillary plexus",
                           "Retinal vessels", "#e0574a", RETINA["sup_plexus"], "artery", rank=0))
    parts.append(mesh_part(_capillaries(Y_OPL1 + 0.002, 0.09, 0.0045, seed=25), "Deep capillary plexus",
                           "Retinal vessels", "#e0574a", RETINA["deep_plexus"], "artery", rank=-3))

    # ---------------------------------------------------------------- Müller glia spanning OLM to ILM
    paths, radii = [], []
    for x, z in mu_xz:
        w = rng.normal(scale=0.003, size=(8, 2))
        ys = [Y_IS1 + 0.001, Y_OLM + 0.04, Y_OLM + 0.09, Y_OPL0 + 0.025, Y_OPL1 + 0.038, Y_IPL0 + 0.02,
              Y_IPL1 - 0.01, Y_NFL - 0.013, Y_ILM - 0.004]
        p = np.array([(x + (w[k - 1, 0] if 0 < k < 8 else 0), y, z + (w[k - 1, 1] if 0 < k < 8 else 0))
                      for k, y in enumerate(ys)])
        paths.append(p)
        radii.append(np.array([0.004, 0.0032, 0.0032, 0.0038, 0.005, 0.0036, 0.0036, 0.006, 0.019]))
        for y0 in (Y_OPL0 + 0.025, Y_IPL0 + 0.04):
            a = rng.uniform(0, 2 * math.pi)
            q, r = _branch(rng, (x, y0, z), (math.cos(a), 0.0, math.sin(a)), 0.03, 0.0025, 0.001, 3, 0.2)
            paths.append(q)
            radii.append(r)
    m = _tubes(paths, radii, 6)
    m.extend(_blobs(np.column_stack([mu_xz[:, 0], np.full(len(mu_xz), Y_OPL1 + 0.038), mu_xz[:, 1]]),
                    (0.009, 0.022, 0.009)))
    parts.append(mesh_part(_merged(m), "Müller glia", "Retinal neurons & glia", "#8fd3b3", RETINA["muller"], "nerve",
                           rank=-2.5, detail=(0.05, 0.0, 0.0, 2)))

    # ---------------------------------------------------------------- inner limiting membrane and vitreous
    def ilm(X, Z):
        X, Z = np.asarray(X, float), np.asarray(Z, float)
        b = 0.012 * np.exp(-((Z - za(X)) / 0.03) ** 2) + 0.015 * np.exp(-((Z - zv(X)) / 0.036) ** 2)
        return Y_ILM + b + 0.002 * fbm2(X.astype(np.float32), Z.astype(np.float32), 6.0, 3, 5)
    parts.append(hlayer("Inner limiting membrane", "Inner limiting membrane & vitreous", "#d7e4ea", ilm,
                        shift(ilm, 0.006), RETINA["ilm"], "cartilage", XR, ZR, rank=1, res=100, alpha=0.5,
                        detail=(0.02, 0.0, 0.0, 0)))
    parts.append(hlayer("Vitreous body", "Inner limiting membrane & vitreous", "#d6eef5", shift(ilm, 0.009), 0.9,
                        RETINA["vitreous"], "csf", XR, ZR, rank=2, res=40, alpha=0.1))
    return settle(parts, seed=403, amp_xz=0.018, amp_y=0.026, freq=1.5, grain=0.0025, micro=0.0015, micro_freq=24.0,
                  dome=(-0.30, 1.15, 0.82))
