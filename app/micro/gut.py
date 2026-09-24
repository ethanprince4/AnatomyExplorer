"""Intestinal wall models (jejunum, duodenum, ileum, colon) at high resolution.

The mucosa is a signed-distance solid: a lamina propria floor with finger-like (or leaf-like) villi smoothly grown
out of it and tubular crypts carved into it, lined by an epithelium of constant thickness. Muscle layers and
submucosa are height fields that follow the plica circularis. Plexuses are organic ganglion networks."""
import math

import numpy as np
from scipy.spatial import Delaunay, cKDTree

from .cells import frame_from_normal, poisson_disk, sample_surface
from .geometry import Mesh, capsule as capsule_mesh, ellipsoid as ellipsoid_mesh, tube
from .kit import (Volume, at, capsule, ellipsoid, hlayer, mesh_part, muscle_bundles, noise2, round_cone,
                  sdf_part, tube_mesh, wavy_path)
from .organic import settle
from .sdf import squashed
from .organs import GUT

X0, X1, Z0, Z1 = -1.0, 1.0, -0.6, 0.6

SPEC = {
    "jejunum": dict(spacing=0.15, radius=0.05, height=0.42, crypt=0.17, goblet=0.07, fold=True, leaf=False),
    "duodenum": dict(spacing=0.17, radius=0.075, height=0.30, crypt=0.17, goblet=0.08, fold=False, leaf=True),
    "ileum": dict(spacing=0.14, radius=0.045, height=0.28, crypt=0.17, goblet=0.045, fold=False, leaf=False),
    "colon": dict(spacing=0.0, radius=0.0, height=0.0, crypt=0.30, goblet=0.05, fold=False, leaf=False),
}


def _network(center_y_fn, spacing, node_r, strand_r, seed, voxel=0.0035, thickness=0.03):
    """Ganglia joined by nerve strands, polygonised as one organic network."""
    pts = poisson_disk((X0 - 0.05, Z0 - 0.05), (X1 + 0.05, Z1 + 0.05), spacing, seed=seed)
    ys = np.array([at(center_y_fn, p[0], p[1]) for p in pts])
    lo_y, hi_y = float(ys.min()) - thickness, float(ys.max()) + thickness
    vol = Volume((X0, lo_y, Z0), (X1, hi_y, Z1), voxel)
    rng = np.random.default_rng(seed)
    shapes = []
    for (x, z), y in zip(pts, ys):
        a = rng.uniform(0, math.pi)
        rot = np.array([[math.cos(a), 0, -math.sin(a)], [0, 1, 0], [math.sin(a), 0, math.cos(a)]])
        shapes.append(ellipsoid((x, y, z), (node_r * rng.uniform(1.0, 1.6), node_r * 0.38, node_r), rot))
    tri = Delaunay(pts)
    edges = set()
    for s in tri.simplices:
        for i in range(3):
            a, b = sorted((int(s[i]), int(s[(i + 1) % 3])))
            if np.linalg.norm(pts[a] - pts[b]) < spacing * 1.9:
                edges.add((a, b))
    for a, b in edges:
        pa = np.array([pts[a][0], ys[a], pts[a][1]])
        pb = np.array([pts[b][0], ys[b], pts[b][1]])
        mid = (pa + pb) / 2 + np.array([0.0, 0.0, rng.uniform(-0.02, 0.02)])
        shapes.append(round_cone(pa, mid, strand_r * 1.2, strand_r))
        shapes.append(round_cone(mid, pb, strand_r, strand_r * 1.2))
    vol.add_all(shapes, "union")
    vol.intersect_box((X0, lo_y - 1, Z0), (X1, hi_y + 1, Z1))
    return vol


def _lattice(spacing, jitter=0.0, seed=0):
    """Villus or crypt centres on a hexagonal lattice with rows on z = 0 and a column on x = 0 (the cut planes).

    `jitter` scatters them, but the scatter is faded out near each cut plane so the structures that the cut-away
    sections lengthwise still sit exactly in it - the packing looks natural without losing the clean section."""
    pts = []
    dz = spacing * math.sqrt(3) / 2
    for j in range(-int(Z1 / dz) - 1, int(Z1 / dz) + 2):
        z = j * dz
        off = spacing / 2 if j % 2 else 0.0
        for i in range(-int(X1 / spacing) - 2, int(X1 / spacing) + 3):
            x = i * spacing + off
            if X0 + spacing * 0.4 < x < X1 - spacing * 0.4 and Z0 + spacing * 0.4 < z < Z1 - spacing * 0.4:
                pts.append((x, z))
    pts = np.array(pts)
    if jitter and len(pts):
        rng = np.random.default_rng(abs(int(seed)) + 1)
        keep = np.clip(np.abs(pts) / (spacing * 0.7), 0.0, 1.0)
        pts = pts + rng.uniform(-jitter, jitter, pts.shape) * spacing * keep
    return pts


def build_gut(kind="jejunum"):
    sp = SPEC[kind]
    colon = kind == "colon"
    rng = np.random.default_rng({"jejunum": 1, "duodenum": 2, "ileum": 3, "colon": 4}[kind])
    parts = []
    fold = (lambda X, Z: 0.24 * np.exp(-((np.asarray(X) + 0.42) / 0.2) ** 2)) if sp["fold"] else \
        (lambda X, Z: 0.0 * np.asarray(X))
    band = (lambda X, Z: 0.09 * np.clip(1.0 - np.abs(np.asarray(Z) - 0.3) / 0.22, 0, 1) ** 0.5) if colon else \
        (lambda X, Z: 0.0 * np.asarray(Z))
    xr, zr = (X0, X1), (Z0, Z1)

    y_long = lambda X, Z: 0.11 + band(X, Z) + 0.004 * np.sin(np.asarray(X) * 9)
    y_circ0 = lambda X, Z: y_long(X, Z) + 0.014
    y_circ1 = lambda X, Z: 0.30 + band(X, Z) + 0.006 * np.sin(np.asarray(X) * 5 + 1)
    y_sub = lambda X, Z: 0.50 + band(X, Z) + fold(X, Z) + noise2(0.008, 3.0, seed=5)(X, Z)
    y_mm = lambda X, Z: y_sub(X, Z) + 0.03
    y_s = lambda X, Z: y_mm(X, Z) + sp["crypt"]

    parts.append(hlayer("Serosa", "Serosa & muscularis externa", "#eadcb8", 0.0, 0.03, GUT["serosa"], "serosa", xr,
                        zr, bulk=True, rank=-4, res=160))
    parts.append(sdf_part(muscle_bundles(0.032, y_long, 0, 0.105, 0.034, seed=81, voxel=0.0062),
                          "Taenia coli & longitudinal muscle" if colon else "Outer longitudinal muscle",
                          "Serosa & muscularis externa", "#c25d51", GUT["taenia"] if colon else GUT["long"],
                          "muscle", smooth=0.8, rank=-3, detail=(0.08, 80.0, 0.4, 1)))
    parts.append(sdf_part(muscle_bundles(y_circ0, y_circ1, 2, 0.115, 0.046, seed=82, rows=3, voxel=0.0062),
                          "Inner circular muscle", "Serosa & muscularis externa", "#a8463d", GUT["circ"], "muscle",
                          smooth=0.8, rank=-2, detail=(0.08, 80.0, 0.4, 3)))
    parts.append(hlayer("Submucosa", "Submucosa", "#f0d2c3", y_circ1, y_sub, GUT["submucosa"], "fascia", xr, zr,
                        bulk=True, rank=-1, res=220, detail=(0.14, 55.0, 0.15, 0)))
    parts.append(hlayer("Muscularis mucosae", "Mucosa", "#b95a50", y_sub, y_mm, GUT["mm"], "muscle", xr, zr, rank=0,
                        res=220, detail=(0.08, 90.0, 0.4, 1)))

    # ------------------------------------------------------------------ plexuses
    my = _network(lambda X, Z: y_long(X, Z) + 0.007, 0.22, 0.042, 0.0075, seed=11, voxel=0.0045)
    parts.append(sdf_part(my, "Myenteric (Auerbach) plexus", "Nerves & vessels", "#f0cf45", GUT["myenteric"], "nerve",
                          smooth=0.7, rank=-2.5, detail=(0.05, 150.0, 0.6, 0)))
    smp = _network(lambda X, Z: y_sub(X, Z) - 0.04, 0.19, 0.028, 0.0055, seed=13, voxel=0.004)
    parts.append(sdf_part(smp, "Submucosal (Meissner) plexus", "Nerves & vessels", "#f3d35a", GUT["submucosal_plexus"],
                          "nerve", smooth=0.7, rank=-1, detail=(0.05, 150.0, 0.6, 0)))

    # ------------------------------------------------------------------ vessels
    art, vein, branch = Mesh(), Mesh(), Mesh()
    for j, z in enumerate((-0.38, 0.0, 0.36)):
        path = wavy_path((X0 + 0.01, 0, z), (X1 - 0.01, 0, z + 0.04), 80, 0.03, 1.5, seed=20 + j)
        path[:, 1] = [at(y_circ1, p[0], p[2]) + 0.075 for p in path]
        art.extend(tube(path, 0.022, 20))
        vpath = path.copy()
        vpath[:, 2] += 0.075
        vpath[:, 1] -= 0.01
        vein.extend(tube(vpath, 0.032, 22))
        for x in np.linspace(-0.85, 0.85, 7):
            k = int(np.argmin(np.abs(path[:, 0] - x)))
            a = path[k]
            top = np.array([a[0] + 0.03, at(y_mm, a[0], a[2]) + 0.03, a[2] + 0.02])
            branch.extend(tube_mesh(wavy_path(a, top, 20, 0.01, 1.0, seed=int(x * 100) + j), 0.0075, 12))
    parts += [mesh_part(art, "Submucosal arterioles", "Nerves & vessels", "#cf3a31", GUT["sub_artery"], "artery",
                        rank=-1),
              mesh_part(vein, "Submucosal venules", "Nerves & vessels", "#3d5bc2", GUT["sub_vein"], "vein", rank=-1),
              mesh_part(branch, "Mucosal branches", "Nerves & vessels", "#d64b43", GUT["sub_artery"], "artery",
                        rank=-0.5, label=False)]

    # ------------------------------------------------------------------ mucosa (signed distance)
    peyer = [(-0.5, 0.0, 0.2), (0.45, -0.3, 0.16)] if kind == "ileum" else ([(-0.55, 0.0, 0.13)] if colon else [])
    villi = [] if colon else [p for p in _lattice(sp["spacing"], 0.24, seed=71)
                              if not any(math.hypot(p[0] - px, p[1] - pz) < pr + 0.06 for px, pz, pr in peyer)]
    top_extra = sp["height"] + 0.05
    y_lo = float(min(at(y_mm, x, z) for x in np.linspace(X0, X1, 15) for z in (Z0, 0, Z1))) - 0.01
    y_hi = float(max(at(y_s, x, z) for x in np.linspace(X0, X1, 41) for z in (Z0, 0, Z1))) + top_extra + 0.02
    vox = 0.006
    lum = Volume((X0, y_lo, Z0), (X1, y_hi, Z1), vox)
    x, y, z = lum.axes()
    dome = np.zeros((lum.shape[0], 1, lum.shape[2]), np.float32)
    for px, pz, pr in peyer:
        dome += (0.07 * np.clip(1 - ((x - px) ** 2 + (z - pz) ** 2) / (pr * 1.3) ** 2, 0, 1) ** 1.5)[:, :, :]
    surface = (y_s(x, z) + dome).astype(np.float32)
    lum.d = (y - surface).astype(np.float32) * np.ones((1, 1, 1), np.float32)
    lum.d = np.broadcast_to(lum.d, lum.shape).copy()
    lacteals, caps_mesh, muscle_strands = Mesh(), Mesh(), Mesh()
    for i, (vx, vz) in enumerate(villi):
        base_y = at(y_s, vx, vz)
        h = sp["height"] * rng.uniform(0.74, 1.16)
        lean = np.array([rng.uniform(-0.07, 0.07), 0.0, rng.uniform(-0.07, 0.07)])
        tip = np.array([vx, base_y + h, vz]) + lean
        base = np.array([vx, base_y - 0.03, vz])
        squash = np.array([1.0, 1.0, 1.0])
        w = rng.uniform(0.86, 1.14)
        bend = np.zeros(3)
        if sp["leaf"]:
            # broad leaf: a tapering finger flattened across its width (its core vessels follow the same flattening)
            squash = np.array([1.0, 1.0, 0.55]) if (i % 3) else np.array([0.55, 1.0, 1.0])
            leaf = squashed(round_cone(base, tip, sp["radius"], sp["radius"] * 0.72), base, squash)
            lum.add(leaf, "smooth", 0.03)
        else:
            # gently curved, slightly tapering finger
            bend = np.array([rng.uniform(-1, 1), 0.0, rng.uniform(-1, 1)]) * 0.055
            pts = [base, base + (tip - base) * 0.35 + bend * 0.4, base + (tip - base) * 0.7 + bend, tip]
            rads = [sp["radius"] * 1.08 * w, sp["radius"] * 1.0 * w, sp["radius"] * 0.95 * w,
                    sp["radius"] * 0.86 * w]
            lum.add_all([round_cone(pts[k], pts[k + 1], rads[k], rads[k + 1]) for k in range(3)], "smooth", 0.03)

        # the lacteal and the capillary basket follow the villus wherever it leans and bends, so nothing escapes
        # through its wall
        def axis_at(u):
            """Centre of the villus at height fraction u, including its lean and its bend."""
            u = np.asarray(u, float)[..., None]
            return (base + (tip - base) * u) + bend * np.sin(np.pi * np.clip(u, 0, 1)) * 1.15

        tt = np.linspace(0.06, 0.94, 14)
        core_r = sp["radius"] * (0.28 if not sp["leaf"] else 0.2)
        lac_path = axis_at(tt)
        lacteals.extend(tube(lac_path, np.full(len(tt), core_r * 0.9) * np.concatenate(
            [[0.35], np.ones(len(tt) - 2), [0.3]]), 12))
        turns = 5
        a = np.linspace(0, turns * 2 * math.pi, 80)
        u = a / a[-1]
        rr = (sp["radius"] * (1.0 if sp["leaf"] else w) - (0.030 if sp["leaf"] else 0.024)) * (1.0 - 0.18 * u)
        centre = axis_at(0.04 + u * 0.92)
        hel = centre + np.stack([rr * np.cos(a) * squash[0], np.zeros_like(a), rr * np.sin(a) * squash[2]], -1)
        caps_mesh.extend(tube(hel, 0.0042, 7, caps=True))
        if not sp["leaf"]:
            sm = axis_at(np.linspace(0.08, 0.9, 8)) + np.array([core_r * 1.5, 0.0, 0.0])
            muscle_strands.extend(tube(sm, 0.004, 6))
    # crypts: tubular glands opening between villi
    if colon:
        crypt_pts = _lattice(0.07, 0.26, seed=73)
    else:
        cand = _lattice(sp["spacing"] / 2.0, 0.22, seed=75)
        tree = cKDTree(villi) if len(villi) else None
        crypt_pts = np.array([c for c in cand if tree is None or tree.query(c)[0] > sp["radius"] + 0.018])
    crypt_pts = np.array([c for c in crypt_pts if not any(math.hypot(c[0] - px, c[1] - pz) < pr * 1.2
                                                          for px, pz, pr in peyer)])
    r_crypt = 0.02 if not colon else 0.024
    crypt_shapes = []
    for ci, (cx, cz) in enumerate(crypt_pts):
        top_y = at(y_s, cx, cz) + 0.04
        bot_y = at(y_mm, cx, cz) + 0.035 + rng.uniform(-0.012, 0.012)
        w = rng.uniform(0.85, 1.18)
        tilt = np.array([rng.uniform(-0.012, 0.012), 0.0, rng.uniform(-0.012, 0.012)])
        crypt_shapes.append(round_cone(np.array([cx, bot_y, cz]) - tilt, np.array([cx, top_y, cz]) + tilt,
                                       r_crypt * 0.95 * w, r_crypt * 1.15 * w))
    lum.add_all(crypt_shapes, "smooth_subtract", 0.008)
    lum.displace(0.0025, 26.0, 2, seed=7)
    floor = (y_mm(x, z) + 0.002 - y).astype(np.float32)
    epi = lum.copy(np.maximum(lum.d, floor))
    epi.intersect_box((X0, y_lo - 1, Z0), (X1, y_hi + 1, Z1))
    t_epi = 0.022 if not colon else 0.026
    lp = lum.copy(np.maximum(lum.d + t_epi, floor))
    lp.intersect_box((X0, y_lo - 1, Z0), (X1, y_hi + 1, Z1))
    split = (y_s(x, z) + dome).astype(np.float32)
    epi_mesh = None
    if colon:
        epi_mesh = epi.mesh(0.8)
        parts.append(mesh_part(epi_mesh, "Surface & crypt epithelium", "Mucosa", "#e3a19b", GUT["surface_epi"] + " " +
                               GUT["colon_crypt"], "mucosa", rank=2, detail=(0.1, 150.0, 0.85, 0)))
        parts.append(sdf_part(lp, "Lamina propria", "Mucosa", "#f0c3b5", GUT["lp"], "mucosa", bulk=True, rank=1,
                              detail=(0.12, 120.0, 0.5, 0), step=2))
    else:
        v_epi = epi.copy(np.maximum(epi.d, split - y + 0.001))
        c_epi = epi.copy(np.maximum(epi.d, y - split + 0.001))
        epi_mesh = v_epi.mesh(0.8)
        parts.append(mesh_part(epi_mesh, "Villus epithelium (enterocytes)", "Villi", "#e5a39c", GUT["villus_epi"],
                               "mucosa", rank=2.5, detail=(0.10, 150.0, 0.85, 2)))
        parts.append(sdf_part(lp.copy(np.maximum(lp.d, split - y + 0.001)), "Villus lamina propria core", "Villi",
                              "#f3c9b8", GUT["villus_core"], "mucosa", rank=2.4, detail=(0.12, 110.0, 0.45, 0),
                              step=1 if sp["leaf"] else 2))
        parts.append(sdf_part(c_epi, "Intestinal crypts (of Lieberkühn)", "Mucosa", "#d88d92", GUT["crypt"], "mucosa",
                              rank=1.2, detail=(0.10, 170.0, 0.9, 2)))
        parts.append(sdf_part(lp.copy(np.maximum(lp.d, y - split + 0.001)), "Lamina propria", "Mucosa", "#f0c3b5",
                              GUT["lp"], "mucosa", bulk=True, rank=1, detail=(0.12, 120.0, 0.5, 0), step=2))
        parts.append(mesh_part(lacteals, "Central lacteals", "Villi", "#f7f2df", GUT["lacteal"], "csf", rank=2.4,
                               detail=(0.02, 0.0, 0.0, 0)))
        parts.append(mesh_part(caps_mesh, "Villus capillary network", "Villi", "#d9463d", GUT["villus_cap"], "artery",
                               rank=2.4))
        if muscle_strands.parts:
            parts.append(mesh_part(muscle_strands, "Villus smooth muscle", "Villi", "#b95a50",
                                   "Smooth muscle strands in the villus core that shorten the villus rhythmically, "
                                   "pumping chyle out of the lacteal.", "muscle", rank=2.4, label=False))

    # goblet cells embedded in the epithelium, Paneth cells at crypt bases
    gob = Mesh()
    top_limit = (lambda p: p[:, 1] > np.array([at(y_s, q[0], q[2]) for q in p]) + 0.02) if not colon else None
    pts, nrm = sample_surface(epi_mesh, sp["goblet"], seed=3,
                              mask=lambda p, n: (np.abs(p[:, 0]) < 0.99) & (np.abs(p[:, 2]) < 0.59) & (n[:, 1] > -0.5))
    for p, n in zip(pts, nrm):
        if top_limit is not None and p[1] < at(y_s, p[0], p[2]) + 0.03:
            continue
        R = frame_from_normal(n)
        gob.extend(ellipsoid_mesh(p - n * (t_epi * 0.45), (0.0085, 0.013, 0.0085), 6, rotation=R))
    parts.append(mesh_part(gob, "Goblet cells", "Villi" if not colon else "Mucosa", "#e6ecf6", GUT["goblet"], "mucosa",
                           rank=2.6, detail=(0.03, 0.0, 0.0, 0)))
    if not colon:
        pan = Mesh()
        for cx, cz in crypt_pts:
            by = at(y_mm, cx, cz) + 0.035
            for k in range(5):
                a = k * 2 * math.pi / 5 + rng.uniform(-0.2, 0.2)
                c = (cx + (r_crypt + 0.008) * math.cos(a), by + rng.uniform(-0.004, 0.01), cz + (r_crypt + 0.008) *
                     math.sin(a))
                pan.extend(ellipsoid_mesh(c, (0.0085, 0.011, 0.0085), 6))
        parts.append(mesh_part(pan, "Paneth cells", "Mucosa", "#e5563f", GUT["paneth"], "gland", rank=1.3,
                               detail=(0.05, 0.0, 0.0, 0)))

    # ------------------------------------------------------------------ duodenal glands, lymphoid tissue
    if kind == "duodenum":
        parts += _brunner(y_circ1, y_sub, y_mm, rng)
    if peyer:
        parts += _lymphoid(peyer, y_mm, y_s, kind)
    return settle(parts, seed={"jejunum": 201, "duodenum": 202, "ileum": 203, "colon": 204}[kind], amp_xz=0.030, amp_y=0.070, freq=1.5, grain=0.005)


def _brunner(y_circ1, y_sub, y_mm, rng):
    centres = [(-0.7, 0.0), (-0.3, 0.0), (0.0, 0.2), (0.0, 0.48), (0.5, -0.3), (0.5, 0.25), (-0.6, -0.35)]
    lo = (X0, 0.28, Z0)
    hi = (X1, 0.72, Z1)
    glands = Volume(lo, hi, 0.0035)
    ducts = Volume(lo, hi, 0.0035)
    for i, (cx, cz) in enumerate(centres):
        base = at(y_circ1, cx, cz)
        top = at(y_sub, cx, cz)
        c = np.array([cx, (base + top) / 2 + 0.01, cz])
        shapes = []
        for k in range(22):
            off = rng.normal(size=3) * np.array([0.07, 0.035, 0.06])
            r = rng.uniform(0.018, 0.027)
            shapes.append(ellipsoid(c + off, (r, r * 0.85, r)))
        glands.add_all(shapes, "smooth", 0.012)
        end = np.array([cx + 0.02, at(y_mm, cx, cz) + 0.03, cz + 0.01])
        ducts.tube(np.array([c + np.array([0, 0.02, 0]), (c + end) / 2 + np.array([0.01, 0, 0]), end]), 0.0075)
    glands.displace(0.002, 40.0, 2, seed=9)
    return [sdf_part(glands, "Brunner glands", "Submucosa", "#b9d5ec", GUT["brunner"], "gland", smooth=0.8, rank=-1,
                     detail=(0.08, 120.0, 0.8, 0)),
            sdf_part(ducts, "Brunner gland ducts", "Submucosa", "#8fb6d8", GUT["brunner_duct"], "gland", smooth=0.6,
                     rank=-0.5, label=False)]


def _lymphoid(peyer, y_mm, y_s, kind):
    fol = Volume((X0, 0.3, Z0), (X1, 1.05, Z1), 0.004)
    gc = Volume((X0, 0.3, Z0), (X1, 1.05, Z1), 0.004)
    for px, pz, pr in peyer:
        cy = at(y_mm, px, pz) + 0.03
        fol.add(ellipsoid((px, cy, pz), (pr, pr * 0.95, pr)), "smooth", 0.02)
        if kind == "ileum":
            fol.add(ellipsoid((px + pr * 0.9, cy - 0.02, pz + 0.05), (pr * 0.7, pr * 0.65, pr * 0.7)), "smooth", 0.03)
        gc.add(ellipsoid((px, cy + 0.01, pz), (pr * 0.52, pr * 0.48, pr * 0.52)))
    fol.displace(0.003, 20.0, 2, seed=3)
    corona = fol.copy(np.maximum(fol.d, -(gc.d - 0.004)))
    parts = [sdf_part(corona, "Peyer patch follicles" if kind == "ileum" else "Solitary lymphoid follicle",
                      "Lymphoid tissue", "#86b873", GUT["peyer"] if kind == "ileum" else GUT["follicle"], "lymph",
                      rank=0.5, detail=(0.06, 190.0, 0.97, 0)),
             sdf_part(gc, "Germinal centres", "Lymphoid tissue", "#cfe6b2", GUT["germinal"], "lymph", rank=0.5,
                      detail=(0.06, 120.0, 0.6, 0))]
    return parts
