"""Lung acinus: terminal bronchiole, respiratory bronchioles, alveolar ducts and sacs with their vessels."""
import math

import numpy as np
from scipy.spatial import Voronoi, cKDTree

from .cellkit import band_cells, star_cell
from .cells import frame_from_normal, jittered_bcc
from .geometry import Mesh, ellipsoid as ellipsoid_mesh, frames, smooth_path, tube
from .kit import Volume, capsule, ellipsoid, mesh_part, sdf_part, sphere
from .organic import Sweep, rmul, rsum, settle, surf_noise, tubule


# =================================================================================================== lung acinus
LUNG_D = {
    "tb": "Terminal bronchiole: the last purely conducting airway (~0.5 mm). Simple cuboidal epithelium of ciliated "
          "cells and club cells, a complete coat of smooth muscle, and no cartilage or glands. Everything distal to "
          "it – the acinus – exchanges gas.",
    "tb_muscle": "Bronchiolar smooth muscle: spiral bundles wrapping the terminal and respiratory bronchioles. With "
                 "no cartilage to hold them open, bronchioles narrow when it contracts – bronchoconstriction in "
                 "asthma and anaphylaxis, relieved by β2-agonists.",
    "club": "Club (Clara) cells: dome-shaped, non-ciliated secretory cells bulging into the bronchiolar lumen. They "
            "secrete club cell secretory protein and surfactant components, detoxify inhaled toxins with cytochrome "
            "P450, and act as stem cells for the bronchiolar epithelium.",
    "rb": "Respiratory bronchioles: transitional airways whose cuboidal-epithelium wall is interrupted by scattered "
          "alveoli opening directly into the lumen – the first place gas exchange happens. There are 1–3 orders, "
          "each with more alveoli. Centriacinar emphysema of smokers destroys this region first.",
    "rb_alv": "Interalveolar septa of the alveoli budding from the respiratory bronchioles: each alveolus opens "
              "through a gap in the bronchiolar wall.",
    "duct": "Alveolar ducts: long passages whose wall is nothing but the mouths of alveoli. The free edges of the "
            "septa ringing each mouth hold elastic, collagen and smooth muscle fibres (the knobs seen in section). "
            "The septa are thin sheets lined on both sides by type I pneumocytes (~95% of the surface, 0.1–0.2 µm "
            "thick) over a capillary network.",
    "sac": "Alveolar sacs: the blind ends of the alveolar ducts, a common space (atrium) surrounded by a cluster of "
           "alveoli. Each alveolus is ~200 µm across; there are ~300–500 million in the lungs, ~70 m² of surface. "
           "Panacinar emphysema (α1-antitrypsin deficiency) destroys the septa uniformly.",
    "kohn": "Pores of Kohn: 10–15 µm holes through the interalveolar septa connecting neighbouring alveoli. They "
            "allow collateral ventilation past a blocked airway – and let bacteria and exudate spread in lobar "
            "pneumonia.",
    "t2": "Type II pneumocytes (great alveolar cells): cuboidal cells that bulge into the alveolus at the corners of "
          "the septa. Their lamellar bodies secrete surfactant (DPPC) that lowers surface tension and stops alveoli "
          "collapsing at end-expiration; they also divide to replace type I cells after injury. Too few in "
          "premature infants → neonatal respiratory distress syndrome.",
    "mac": "Alveolar macrophages ('dust cells'): wander over the alveolar surface phagocytosing inhaled particles, "
           "microbes and surfactant, then leave via the mucociliary escalator or the lymphatics. Haemosiderin-laden "
           "in left heart failure ('heart failure cells').",
    "knobs": "Smooth muscle of the alveolar ducts: bundles in the free rims of the septa that ring each alveolar "
             "mouth, seen as knobs in section. Together with elastic fibres they set the calibre of the duct.",
    "cap": "Alveolar capillaries: a network so dense that blood flows through the septa almost as a sheet. The "
           "air–blood barrier – type I cell, fused basement membranes and endothelium – is only ~0.5 µm thick. "
           "Continuous, non-fenestrated endothelium; blood arrives deoxygenated and leaves oxygenated.",
    "pa": "Pulmonary arteriole: carries deoxygenated blood and runs with the airway, branching as it branches "
          "(bronchovascular bundle) down to the alveolar ducts, where it breaks up into the capillaries. Hypoxic "
          "vasoconstriction diverts blood away from poorly ventilated alveoli; chronic hypoxia remodels it "
          "(pulmonary hypertension).",
    "pv": "Pulmonary venule: carries oxygenated blood away from the capillaries. It runs at the periphery of the "
          "acinus and lobule, in the connective-tissue septa, well away from the airway and artery – so veins, "
          "not arteries, outline the lobules.",
}


def _lung_tree():
    """The airway tree as (kind, path) segments, plus the leaf ends that finish in alveolar sacs."""
    tb = smooth_path(np.array([(-1.09, 0.0, 0.0), (-0.86, 0.012, -0.01), (-0.62, 0.02, 0.0)]), 30)
    b0 = tb[-1]
    leaves = {"a1": [(0.42, -0.06), (0.40, 0.34)], "a2": [(0.05, 0.44), (0.13, 0.10)],
              "b1": [(-0.24, 0.30), (-0.43, -0.05)], "b2": [(-0.05, -0.42), (-0.39, -0.40)]}
    segs = []
    ends = []
    rng = np.random.default_rng(21)
    for rb, subs in (("a", ("a1", "a2")), ("b", ("b1", "b2"))):
        allyz = np.array([yz for s in subs for yz in leaves[s]])
        rb_end = np.array([-0.12, *(allyz.mean(0) * 0.5)])
        rb_path = smooth_path(np.array([b0, (b0 + rb_end) / 2 + np.array([0, 0.02, 0.0]), rb_end]), 30)
        segs.append(("rb", rb_path))
        for s in subs:
            yz = np.array(leaves[s])
            g1_end = np.array([0.36 + rng.uniform(-0.05, 0.05), *(yz.mean(0) * 0.85)])
            p = smooth_path(np.array([rb_end, (rb_end + g1_end) / 2 + rng.normal(scale=0.02, size=3), g1_end]), 30)
            segs.append(("duct", p))
            for leaf in yz:
                end = np.array([0.86 + rng.uniform(-0.04, 0.05), *leaf])
                q = smooth_path(np.array([g1_end, (g1_end + end) / 2 + rng.normal(scale=0.025, size=3), end]), 30)
                segs.append(("leaf", q))
                ends.append(end)
    return tb, segs, np.array(ends)


def _axis_points(path, spacing):
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.arange(0.0, s[-1] + 1e-9, spacing)
    return np.stack([np.interp(t, s, path[:, c]) for c in range(3)], -1), t / max(s[-1], 1e-9)


def build_alveoli():
    parts = []
    rng = np.random.default_rng(12)
    lo = np.array([-1.1, -0.64, -0.64])
    hi = np.array([1.08, 0.64, 0.64])
    vox = 0.0092
    tb, segs, ends = _lung_tree()
    rb_paths = [p for k, p in segs if k == "rb"]
    duct_paths = [p for k, p in segs if k != "rb"]
    # ---- the acinus envelope: lobulated sleeves around the respiratory tree and grape bunches at the sacs
    env = Volume(lo - 0.02, hi + 0.02, 0.02)
    for p in rb_paths:
        env.tube(p, np.linspace(0.16, 0.24, len(p)), "smooth", 0.08)
    for k, p in segs:
        if k != "rb":
            env.tube(p, 0.25 if k == "duct" else 0.24, "smooth", 0.08)
    for e in ends:
        env.add(sphere(e + np.array([0.04, 0, 0]), 0.21), "smooth", 0.08)
    env.displace(0.035, 3.0, 2, seed=11, coarse=1)

    def env_at(p):
        from scipy.ndimage import map_coordinates
        q = ((np.asarray(p, float).reshape(-1, 3) - env.lo) / env.voxel).T
        return map_coordinates(env.d, q, order=1, mode="nearest")

    # ---- seeds: alveoli packed around open axial seeds of the ducts and bronchioles
    ALV, DUCT, RB, OUT = 0, 1, 2, 3
    ax_pts, ax_type, ax_leaf = [], [], []
    for k, p in segs:
        q, frac = _axis_points(p, 0.03)
        ax_pts.append(q)
        ax_type.append(np.full(len(q), RB if k == "rb" else DUCT))
        ax_leaf.append((frac > 0.55) if k == "leaf" else np.zeros(len(q), bool))
    ax_pts, ax_type, ax_leaf = np.vstack(ax_pts), np.concatenate(ax_type), np.concatenate(ax_leaf)
    grid = jittered_bcc(lo - 0.12, hi + 0.12, 0.18, 0.2, seed=3)
    ax_tree = cKDTree(ax_pts)
    dax, jax = ax_tree.query(grid)
    tb_d = np.min(np.linalg.norm(grid[:, None, :] - tb[None, ::3, :], axis=2), axis=1)
    inside = env_at(grid) < 0
    min_d = np.where(ax_type[jax] == RB, 0.13, 0.145)
    alv = grid[inside & (dax > min_d)]
    out = grid[~inside & (tb_d > 0.2)]
    # every alveolus must open onto a duct, a sac or a respiratory bronchiole: drop the buried ones
    for _ in range(4):
        seeds = np.vstack([alv, ax_pts, out])
        vor = Voronoi(seeds)
        na = len(alv)
        rp = vor.ridge_points
        open_nb = np.zeros(na, bool)
        for a, b in rp:
            if a < na and na <= b < na + len(ax_pts):
                open_nb[a] = True
            if b < na and na <= a < na + len(ax_pts):
                open_nb[b] = True
        if open_nb.all():
            break
        alv = alv[open_nb]
    na, nx = len(alv), len(ax_pts)
    seeds = np.vstack([alv, ax_pts, out])
    stype = np.concatenate([np.full(na, ALV), ax_type, np.full(len(out), OUT)])
    vor = Voronoi(seeds)
    # which region each alveolus belongs to (for the three septal parts): bronchiole, duct or sac
    owner = np.full(na, 1)                                  # 0 rb, 1 duct, 2 sac
    for a, b in vor.ridge_points:
        for i, j in ((a, b), (b, a)):
            if i < na and na <= j < na + nx:
                if ax_type[j - na] == RB:
                    owner[i] = 0
                elif ax_leaf[j - na] and owner[i] != 0:
                    owner[i] = 2
    # ---- voxel field of the foam
    vol = Volume(lo, hi, vox)
    stree = cKDTree(seeds)
    sheet = np.empty(vol.shape, np.float32)
    own = np.empty(vol.shape, np.int8)
    half = 0.0105
    for i in range(0, vol.shape[0], 24):
        j = min(i + 24, vol.shape[0])
        x, y, z = vol.axes((i, 0, 0), (j, vol.shape[1], vol.shape[2]))
        P = np.stack(np.broadcast_arrays(x, y, z), -1).reshape(-1, 3)
        d, l = stree.query(P, k=3, workers=2)
        t1, t2, t3 = stype[l[:, 0]], stype[l[:, 1]], stype[l[:, 2]]
        e = (d[:, 1] - d[:, 0]) / 2
        keep = ((t1 == ALV) & ((t2 == ALV) | (t2 == OUT))) | ((t1 == OUT) & (t2 == ALV))
        f = np.where(keep, e - half, 1.0)
        # the free rim of a septum at an alveolar mouth is beaded (elastic fibres and muscle)
        rim = keep & (t1 == ALV) & (t2 == ALV) & ((t3 == DUCT) | (t3 == RB))
        e3 = (d[:, 2] - d[:, 0]) / 2
        f = np.where(rim, np.minimum(f, np.sqrt(e * e + e3 * e3) - 0.0165), f)
        a_own = np.where(t1 == ALV, l[:, 0], l[:, 1])
        a_own = np.minimum(a_own, na - 1)
        sheet[i:j] = f.reshape(j - i, vol.shape[1], vol.shape[2])
        own[i:j] = owner[a_own].reshape(j - i, vol.shape[1], vol.shape[2])
    vol.d = sheet
    # pores of Kohn through a quarter of the septa between alveoli
    pores = []
    for (a, b), rv in zip(vor.ridge_points, vor.ridge_vertices):
        if a < na and b < na and -1 not in rv and rng.random() < 0.28:
            poly = vor.vertices[rv]
            c = poly.mean(0)
            if np.all(c > lo + 0.05) and np.all(c < hi - 0.05) and np.linalg.norm(poly - c, axis=1).min() > 0.045:
                n = seeds[b] - seeds[a]
                pores.append((c + rng.normal(scale=0.008, size=3), n / np.linalg.norm(n)))
    vol.add_all([sphere(c, 0.019) for c, _ in pores], "smooth_subtract", 0.006) if pores else None

    # ---- respiratory bronchiole walls with alveolar mouths, blended onto the end of the terminal bronchiole
    rbw = Volume(np.min([p.min(0) for p in rb_paths], 0) - 0.14, np.max([p.max(0) for p in rb_paths], 0) + 0.14,
                 0.005)
    lum = rbw.copy()
    for p in rb_paths:
        pp = np.vstack([tb[-6:-1], p])
        rbw.tube(pp, np.linspace(0.108, 0.086, len(pp)), "smooth", 0.03)
        lum.tube(pp, np.linspace(0.084, 0.066, len(pp)), "smooth", 0.03)
    rbw.d = np.maximum(rbw.d, -lum.d)
    mouths = []
    rb_pts = ax_pts[ax_type == RB]
    rb_tree = cKDTree(rb_pts)
    for i in np.nonzero(owner == 0)[0]:
        dd, jj = rb_tree.query(alv[i])
        if rng.random() < 0.75:
            mouths.append(capsule(alv[i], rb_pts[jj], 0.042))
    rbw.add_all(mouths, "smooth_subtract", 0.01)
    band_cells(rbw, rbw.d, 0.03, 0.006, 55)
    parts.append(sdf_part(rbw, "Respiratory bronchioles", "Airways", "#e6b3a3", LUNG_D["rb"], "airway", smooth=0.7,
                          rank=-0.5, detail=(0.08, 160.0, 0.8, 1)))
    # the foam never enters an airway lumen or its wall
    air = Volume(lo, hi, vox)
    for p in rb_paths:
        air.tube(np.vstack([tb[-6:-1], p]), 0.095)
    air.tube(tb, 0.14)
    vol.apply(air.d, (slice(None),) * 3, "smooth_subtract", 0.01)

    # ---- vessels: arteriole with the airways, venule at the periphery; the foam is carved round both
    up = np.array([0.0, 1.0, 0.0])

    def beside(path, off, rr):
        t, _, _ = frames(path)
        side = np.cross(t, np.cross(up if abs(t[0] @ up) < 0.9 else np.array([0, 0, 1.0]), t))
        side /= np.linalg.norm(side, axis=1, keepdims=True)
        return path + side * off[:, None] if np.ndim(off) else path + side * off
    art = []
    art.append((beside(tb, 0.16, 0.0), np.full(len(tb), 0.042)))
    for k, p in segs:
        r0, r1, off = {"rb": (0.036, 0.028, 0.125), "duct": (0.026, 0.019, 0.09), "leaf": (0.018, 0.009, 0.075)}[k]
        pp = beside(p, off, 0.0)
        if k == "rb":
            pp = np.vstack([art[0][0][-1], pp[3:]])
        pp = smooth_path(pp, len(pp))
        art.append((pp, np.linspace(r0, r1, len(pp))))
    for p, rr in art:
        vol.tube(p, rr + 0.012, "smooth_subtract", 0.012)
    parts.append(mesh_part(_vessel_mesh(art, 0.35), "Pulmonary arteriole (deoxygenated)", "Vessels", "#3d5bc2",
                           LUNG_D["pa"], "vein", rank=0.5, detail=(0.06, 90.0, 0.4, 1)))
    # venule: traced along the underside of the acinus, then leaving through the floor of the block
    xs = np.linspace(0.95, -0.28, 26)
    vpts = []
    for xx in xs:
        zc = -0.12 + 0.08 * math.sin(xx * 2.5)
        ys = np.linspace(-0.1, -0.62, 80)
        ev = env_at(np.stack([np.full_like(ys, xx), ys, np.full_like(ys, zc)], -1))
        k = int(np.argmax(ev > 0)) if (ev > 0).any() else len(ys) - 1
        vpts.append((xx, max(ys[k] + 0.03, -0.56), zc))
    vpts = np.array(vpts)
    vpts = np.vstack([vpts, vpts[-1] + np.array([-0.08, -0.06, 0.0]), vpts[-1] + np.array([-0.12, -0.2, 0.0])])
    vpath = smooth_path(vpts, 70)
    ven = [(vpath, np.linspace(0.024, 0.05, len(vpath)))]
    for s0 in (0.12, 0.3, 0.5, 0.7):
        a = vpath[int(s0 * len(vpath))]
        tip = a + np.array([rng.uniform(-0.1, 0.1), 0.24, rng.uniform(-0.05, 0.12)])
        tp = smooth_path(np.array([a, (a + tip) / 2 + rng.normal(scale=0.02, size=3), tip]), 16)
        ven.append((tp, np.linspace(0.02, 0.009, len(tp))))
    for p, rr in ven:
        vol.tube(p, rr + 0.010, "smooth_subtract", 0.012)
    parts.append(mesh_part(_vessel_mesh(ven, 0.2), "Pulmonary venule (oxygenated)", "Vessels", "#cf3a31",
                           LUNG_D["pv"], "artery", rank=0.5, detail=(0.06, 90.0, 0.4, 1)))

    # ---- capillaries along every septal junction, and a meander across some septa
    capm = Mesh()
    caps = []
    stree_ = stree
    inner = lambda p: np.all(p > lo + 0.03) and np.all(p < hi - 0.03)
    seen = set()
    for (a, b), rv in zip(vor.ridge_points, vor.ridge_vertices):
        if -1 in rv or not ((a < na and b < na) or (a < na and stype[b] == OUT) or (b < na and stype[a] == OUT)):
            continue
        poly = vor.vertices[rv]
        for i in range(len(rv)):
            key = tuple(sorted((rv[i], rv[(i + 1) % len(rv)])))
            if key in seen:
                continue
            seen.add(key)
            pa_, pb_ = poly[i], poly[(i + 1) % len(poly)]
            if not (inner(pa_) and inner(pb_)) or np.linalg.norm(pa_ - pb_) > 0.16:
                continue
            m = (pa_ + pb_) / 2
            _, l3 = stree_.query(m, k=3)
            if not np.all(stype[l3] != DUCT) or np.any(stype[l3] == RB):
                continue
            if np.all(stype[l3] == OUT):
                continue
            caps.append(np.array([pa_, m + rng.normal(scale=0.005, size=3), pb_]))
        if ((a < na and stype[b] in (ALV, OUT)) or (b < na and stype[a] == OUT)) and rng.random() < 0.5:
            c = poly.mean(0)
            if inner(c):
                i0 = rng.integers(len(poly))
                i1 = (i0 + len(poly) // 2) % len(poly)
                pa_, pb_ = (poly[i0] + poly[(i0 + 1) % len(poly)]) / 2, (poly[i1] + poly[(i1 + 1) % len(poly)]) / 2
                if inner(pa_) and inner(pb_):
                    caps.append(np.array([pa_, (pa_ + c) / 2 + rng.normal(scale=0.01, size=3), c,
                                          (pb_ + c) / 2 + rng.normal(scale=0.01, size=3), pb_]))
    capv = Volume(lo, hi, vox)
    for seg in caps:
        pth = smooth_path(seg, 2 * len(seg)) if len(seg) > 3 else seg
        capm.extend(tube(pth, 0.0074, 5))
        capv.tube(seg, 0.0074)
    parts.append(mesh_part(capm, "Alveolar capillaries", "Vessels", "#d0525e", LUNG_D["cap"], "artery", rank=0.3,
                           detail=(0.05, 120.0, 0.4, 0)))

    # ---- cells on the septa
    t2, t2v = Mesh(), Volume(lo, hi, vox)
    corners = [v for v in vor.vertices if inner(v) and env_at(v)[0] < -0.03]
    corners = np.array(corners)[rng.permutation(len(corners))]
    count = 0
    for v in corners:
        d, l = stree.query(v, k=4)
        if np.sum(stype[l] == ALV) < 3 or np.any((stype[l] == DUCT) | (stype[l] == RB)) or count >= 260:
            continue
        cen = seeds[rng.choice(l[stype[l] == ALV])]
        n = (cen - v) / np.linalg.norm(cen - v)
        c = v + n * 0.02
        t2.extend(ellipsoid_mesh(c, (0.017, 0.013, 0.017), 7, rotation=frame_from_normal(n)))
        t2v.add(ellipsoid(c, (0.017, 0.017, 0.017)))
        count += 1
    parts.append(mesh_part(t2, "Type II pneumocytes", "Alveoli", "#f0d88f", LUNG_D["t2"], "gland", rank=0.2,
                           detail=(0.08, 160.0, 0.95, 0)))
    mac = Mesh()
    for i in rng.permutation(na)[:40]:
        c0 = alv[i]
        if not inner(c0) or len(mac.parts) >= 14:
            continue
        dvec = rng.normal(size=3)
        dvec /= np.linalg.norm(dvec)
        c = c0 + dvec * 0.045
        mac.extend(star_cell(c, (0.026, 0.021, 0.024), 6, 0.045, rng, sub_vox=0.0035))
    parts.append(mesh_part(mac, "Alveolar macrophages", "Alveoli", "#a9805f", LUNG_D["mac"], "lymph", rank=0.2,
                           detail=(0.05, 60.0, 0.9, 0)))
    # smooth muscle knobs on the rims of the alveolar mouths along the ducts
    knobs = Mesh()
    seen = set()
    for (a, b), rv in zip(vor.ridge_points, vor.ridge_vertices):
        if -1 in rv:
            continue
        if not ((a < na and stype[b] == DUCT) or (b < na and stype[a] == DUCT)):
            continue
        poly = vor.vertices[rv]
        for i in range(len(rv)):
            key = tuple(sorted((rv[i], rv[(i + 1) % len(rv)])))
            if key in seen:
                continue
            seen.add(key)
            pa_, pb_ = poly[i], poly[(i + 1) % len(poly)]
            if not (inner(pa_) and inner(pb_)) or np.linalg.norm(pa_ - pb_) > 0.14:
                continue
            _, l3 = stree.query((pa_ + pb_) / 2, k=3)
            if np.sum(stype[l3] == ALV) != 2 or env_at((pa_ + pb_) / 2)[0] > -0.02:
                continue
            ev = pb_ - pa_
            ln = float(np.linalg.norm(ev))
            knobs.extend(ellipsoid_mesh((pa_ + pb_) / 2, (0.0115, ln * 0.36, 0.0115), 4,
                                        rotation=frame_from_normal(ev / ln)))
    parts.append(mesh_part(knobs, "Alveolar duct smooth muscle (knobs)", "Airways", "#b8794f", LUNG_D["knobs"],
                           "muscle", rank=0.1, detail=(0.08, 100.0, 0.5, 4)))
    pk = Mesh()
    for c, n in pores:
        if env_at(c)[0] > -0.02:
            continue
        R = frame_from_normal(n)
        ang = np.linspace(0, 2 * math.pi, 17)
        ring = c + (R[:, 0][None, :] * np.cos(ang)[:, None] + R[:, 2][None, :] * np.sin(ang)[:, None]) * 0.021
        pk.extend(tube(ring, 0.0085, 8, caps=False))
    parts.append(mesh_part(pk, "Pores of Kohn", "Alveoli", "#e89a92", LUNG_D["kohn"], "lung", rank=0.1))

    # capillaries and type II cells bulge out of the septa instead of being buried in them
    np.maximum(vol.d, -(capv.d - 0.0010), out=vol.d)
    np.maximum(vol.d, -(t2v.d - 0.0012), out=vol.d)
    vol.intersect_box(lo + 0.012, hi - 0.012)
    for g, name, color, desc in ((0, "Interalveolar septa – respiratory bronchioles", "#eab6b0", "rb_alv"),
                                 (1, "Interalveolar septa – alveolar ducts", "#efc2bd", "duct"),
                                 (2, "Interalveolar septa – alveolar sacs", "#f3cdc5", "sac")):
        gv = vol.copy(np.where(own == g, vol.d, np.maximum(vol.d, 0.01)))
        parts.append(sdf_part(gv, name, "Alveoli", color, LUNG_D[desc] + " " + LUNG_D["duct"].split(". ", 2)[-1]
                              if g != 1 else LUNG_D[desc], "lung", smooth=0.8, rank=0,
                              detail=(0.08, 140.0, 0.45, 0)))

    # ---- terminal bronchiole: cuboidal epithelium with club cells, spiral smooth muscle
    _, tbm = tubule(tb, 0.086, 0.112, seed=7, cell=0.03, amp=0.004, aspect=1.0, lobe=(7, 0.05), calibre=0.03,
                    n_theta=96)
    parts.append(mesh_part(tbm, "Terminal bronchiole", "Airways", "#e3aa9c", LUNG_D["tb"], "airway", rank=-1,
                           detail=(0.08, 170.0, 0.85, 1)))
    sm = Mesh()
    for p, r_sm, turns, nb in ((tb, 0.12, 3.5, 3), *[(np.vstack([tb[-6:-1], p]), 0.095, 2.5, 2) for p in rb_paths]):
        t, nn, bb = frames(p)
        for b in range(nb):
            ph = b * 2 * math.pi / nb
            a = np.linspace(0, turns * 2 * math.pi, len(p)) + ph
            pts = p + (nn * np.cos(a)[:, None] + bb * np.sin(a)[:, None]) * r_sm
            sm.extend(tube(smooth_path(pts, len(p) * 3), 0.011, 8))
    parts.append(mesh_part(sm, "Bronchiolar smooth muscle", "Airways", "#b54a44", LUNG_D["tb_muscle"], "muscle",
                           rank=-1, detail=(0.08, 100.0, 0.5, 4)))
    club = Mesh()
    t, nn, bb = frames(tb)
    for i in range(2, len(tb) - 1):
        for j in range(5):
            a = rng.uniform(0, 2 * math.pi)
            dvec = nn[i] * math.cos(a) + bb[i] * math.sin(a)
            c = tb[i] + dvec * 0.084 + rng.normal(scale=0.004, size=3)
            club.extend(ellipsoid_mesh(c, (0.012, 0.016, 0.012), 8, rotation=frame_from_normal(-dvec)))
    parts.append(mesh_part(club, "Club (Clara) cells", "Airways", "#f2e3a3", LUNG_D["club"], "gland", rank=-1,
                           detail=(0.08, 160.0, 0.95, 0)))
    return settle(parts, seed=501, amp_xz=0.02, amp_y=0.03, freq=1.6, grain=0.003)


def _vessel_mesh(items, wall):
    """Hollow vessels: each branch a shell whose wall is `wall` of its radius."""
    m = Mesh()
    for p, rr in items:
        rr = np.asarray(rr, float)
        seg = max(10, int(rr.max() * 500))
        sw = Sweep(p, seg, max(12, len(p)))
        prof = lambda T, S, rr=rr: np.interp(S, np.linspace(0, 1, len(rr)), rr)
        m.extend(sw.shell(rmul(prof, 1.0 - wall, rsum(1.0, surf_noise(0.05, 2.0, 4.0, len(m.parts)))),
                          rmul(prof, rsum(1.0, surf_noise(0.05, 2.0, 4.0, len(m.parts))))))
    return m
