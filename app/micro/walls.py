"""High-resolution wall models of the stomach, oesophagus and trachea."""
import math

import numpy as np

from .cells import frame_from_normal, poisson_disk, sample_surface
from .geometry import Mesh, ellipsoid as ellipsoid_mesh, tube
from .gut import _lattice, _network
from .kit import (Bumps, Grooves, Volume, add, at, box_shape, capsule, ellipsoid, hlayer, mesh_part,
                  muscle_bundles, noise2, round_cone, sdf_part, shift, tube_mesh, wavy_path)
from .organs import GUT, OES, STOMACH, TRACH
from .organic import settle

X0, X1, Z0, Z1 = -1.0, 1.0, -0.6, 0.6
XR, ZR = (X0, X1), (Z0, Z1)


def _muscularis(parts, layers, y_top_fn, network_y=None, desc=GUT):
    """Stack of muscle layers, each a mesh of interlacing bundles (name, colour, bottom, top, description, axis)."""
    for i, (name, color, bottom, top, text, fiber) in enumerate(layers):
        axis = 2 if fiber == 3 else 0
        spacing = 0.115 if axis == 2 else 0.105
        parts.append(sdf_part(muscle_bundles(bottom, top, axis, spacing, 0.040, seed=180 + i * 7, rows=2,
                                             voxel=0.0062),
                              name, "Muscularis externa", color, text, "muscle", smooth=0.8, rank=-3,
                              detail=(0.08, 80.0, 0.4, fiber)))
    if network_y is not None:
        net = _network(network_y, 0.22, 0.042, 0.0075, seed=17, voxel=0.0045)
        parts.append(sdf_part(net, "Myenteric (Auerbach) plexus", "Nerves & vessels", "#f0cf45", desc["myenteric"],
                              "nerve", smooth=0.7, rank=-2.5, detail=(0.05, 150.0, 0.6, 0)))


def _submucosal_vessels(y_fn, seed, depth=0.07):
    art, vein = Mesh(), Mesh()
    for j, z in enumerate((-0.4, 0.02, 0.38)):
        path = wavy_path((X0 + 0.01, 0, z), (X1 - 0.01, 0, z + 0.05), 80, 0.03, 1.5, seed=seed + j)
        path[:, 1] = [at(y_fn, p[0], p[2]) + depth for p in path]
        art.extend(tube(path, 0.02, 20))
        v = path.copy()
        v[:, 2] += 0.07
        vein.extend(tube(v, 0.03, 22))
    return art, vein


# ==================================================================================================== stomach
def build_stomach():
    parts = []
    rng = np.random.default_rng(12)
    fold = lambda X, Z: 0.17 * np.exp(-((np.asarray(Z) - 0.26) / 0.15) ** 2)
    y_l = lambda X, Z: 0.10 + 0.004 * np.sin(np.asarray(X) * 7)
    y_c0, y_c1 = shift(y_l, 0.012), const_fn(0.22)
    y_o0, y_o1 = const_fn(0.232), const_fn(0.30)
    y_sub = lambda X, Z: 0.46 + fold(X, Z) + noise2(0.006, 3.0, seed=4)(X, Z)
    y_mm = shift(y_sub, 0.03)
    y_s = shift(y_mm, 0.46)

    parts.append(hlayer("Serosa", "Muscularis externa", "#eadcb8", 0.0, 0.03, GUT["serosa"], "serosa", XR, ZR,
                        bulk=True, rank=-4, res=120))
    _muscularis(parts, [("Outer longitudinal muscle", "#c25d51", 0.03, y_l, GUT["long"], 1),
                        ("Middle circular muscle", "#a8463d", y_c0, y_c1, GUT["circ"], 3),
                        ("Inner oblique muscle", "#b65247", y_o0, y_o1, STOMACH["oblique"], 1)],
                y_l, network_y=shift(y_l, 0.006))
    parts.append(hlayer("Submucosa (rugal core)", "Submucosa", "#f0d2c3", y_o1, y_sub, GUT["submucosa"] + " " +
                        STOMACH["rugae"], "fascia", XR, ZR, bulk=True, rank=-1, res=200, detail=(0.14, 55.0, 0.15, 0)))
    parts.append(hlayer("Muscularis mucosae", "Mucosa", "#b95a50", y_sub, y_mm, GUT["mm"], "muscle", XR, ZR, rank=0,
                        res=200, detail=(0.08, 90.0, 0.4, 1)))
    art, vein = _submucosal_vessels(y_o1, 30)
    parts += [mesh_part(art, "Submucosal arteries", "Nerves & vessels", "#cf3a31", GUT["sub_artery"], "artery",
                        rank=-1),
              mesh_part(vein, "Submucosal veins", "Nerves & vessels", "#3d5bc2", GUT["sub_vein"], "vein", rank=-1)]

    # ------------------------------------------------------------------ mucosa: pits and oxyntic glands
    y_lo = 0.47
    y_hi = float(max(at(y_s, 0, z) for z in np.linspace(Z0, Z1, 30))) + 0.03
    vox = 0.0055
    tissue = Volume((X0, y_lo, Z0), (X1, y_hi, Z1), vox)
    x, y, z = tissue.axes()
    surf = (y_s(x, z) + noise2(0.006, 9.0, seed=8)(x, z)).astype(np.float32)
    tissue.d = np.broadcast_to((y - surf).astype(np.float32), tissue.shape).copy()
    pits = _lattice(0.135, 0.22, seed=77)
    pit_depth = 0.13
    glands = Volume((X0, y_lo, Z0), (X1, y_hi, Z1), vox)
    parietal = Volume((X0, y_lo, Z0), (X1, y_hi, Z1), vox)
    pit_shapes, gland_shapes, cell_shapes = [], [], []
    for i, (px, pz) in enumerate(pits):
        top = at(y_s, px, pz)
        bottom = top - pit_depth
        pw = rng.uniform(0.82, 1.20)
        pit_shapes.append(round_cone((px, bottom + rng.uniform(-0.012, 0.012), pz), (px, top + 0.03, pz),
                                     0.02 * pw, 0.038 * pw))
        base_y = at(y_mm, px, pz) + 0.03
        for g in range(2):
            a = rng.uniform(0, 2 * math.pi)
            spread = np.array([math.cos(a), 0.0, math.sin(a)]) * 0.032
            p0 = np.array([px, bottom + 0.01, pz])
            p1 = p0 + spread * 0.6 + np.array([0.0, -(bottom - base_y) * 0.5, 0.0])
            p2 = np.array([px, base_y, pz]) + spread
            gland_shapes += [round_cone(p0, p1, 0.022, 0.027), round_cone(p1, p2, 0.027, 0.03)]
            for k in range(6):
                t = rng.uniform(0.15, 0.7)
                c = p0 + (p2 - p0) * t
                ang = rng.uniform(0, 2 * math.pi)
                off = np.array([math.cos(ang), 0.0, math.sin(ang)]) * 0.027
                cell_shapes.append(ellipsoid(c + off, (0.017, 0.02, 0.017)))
    tissue.add_all(pit_shapes, "smooth_subtract", 0.012)
    tissue.displace(0.002, 30.0, 2, seed=5)
    glands.add_all(gland_shapes, "union")
    glands.displace(0.0025, 45.0, 2, seed=6)
    parietal.add_all(cell_shapes, "union")
    floor = (y_mm(x, z) + 0.002 - y).astype(np.float32)
    split_y = (surf - pit_depth - 0.01).astype(np.float32)
    surface_epi = tissue.copy(np.maximum(np.maximum(tissue.d, floor), split_y - y))
    surface_epi.intersect_box((X0, 0, Z0), (X1, 2, Z1))
    lp = tissue.copy(np.maximum(np.maximum(tissue.d + 0.03, floor), -glands.d))
    lp.intersect_box((X0, 0, Z0), (X1, 2, Z1))
    base_zone = (y_mm(x, z) + 0.16).astype(np.float32)
    chief = glands.copy(np.maximum(glands.d, y - base_zone))
    neck = glands.copy(np.maximum(glands.d, base_zone - y))
    parietal.d = np.maximum(parietal.d, floor)
    parts += [
        sdf_part(surface_epi, "Surface mucous cells & gastric pits", "Mucosa", "#e9b3b7",
                 STOMACH["surface"] + " " + STOMACH["pits"], "mucosa", rank=2, detail=(0.10, 150.0, 0.85, 2)),
        sdf_part(neck, "Gland neck & body (mucous neck cells)", "Mucosa", "#e6a0a6", STOMACH["neck"] + " " +
                 STOMACH["glands"], "gland", rank=1.5, detail=(0.10, 150.0, 0.85, 0)),
        sdf_part(parietal, "Parietal (oxyntic) cells", "Mucosa", "#f08c95", STOMACH["parietal"], "gland", rank=1.5,
                 detail=(0.06, 110.0, 0.95, 0)),
        sdf_part(chief, "Chief (zymogen) cells – gland base", "Mucosa", "#9c7fc0", STOMACH["chief"], "gland",
                 rank=1.2, detail=(0.10, 170.0, 0.95, 0)),
        sdf_part(lp, "Lamina propria", "Mucosa", "#f1c9b9", GUT["lp"], "mucosa", bulk=True, rank=1, step=2,
                 detail=(0.12, 120.0, 0.5, 0)),
    ]
    return settle(parts, seed=301, amp_xz=0.030, amp_y=0.070, freq=1.4, grain=0.006)


def const_fn(v):
    return lambda X, Z: np.full(np.broadcast(np.asarray(X), np.asarray(Z)).shape, float(v))


# ==================================================================================================== oesophagus
def build_oesophagus():
    parts = []
    rng = np.random.default_rng(21)
    folds = lambda X, Z: 0.05 * np.maximum(np.sin(np.asarray(Z) * 7.5 + 0.4), 0) ** 2
    y_l = lambda X, Z: 0.15 + 0.004 * np.sin(np.asarray(X) * 6)
    y_c0, y_c1 = shift(y_l, 0.012), const_fn(0.31)
    y_sub = lambda X, Z: 0.56 + folds(X, Z) + noise2(0.006, 3.0, seed=3)(X, Z)
    y_mm = shift(y_sub, 0.06)
    pap_pts = poisson_disk((X0 - 0.05, Z0 - 0.05), (X1 + 0.05, Z1 + 0.05), 0.085, seed=4)
    papillae = Bumps(pap_pts, 0.04, 0.13, k=4, sharp=1.6)
    dej = add(shift(y_mm, 0.08), papillae, noise2(0.006, 10.0, seed=6))
    surface = add(shift(y_mm, 0.35), Grooves(poisson_disk((X0 - 0.1, Z0 - 0.1), (X1 + 0.1, Z1 + 0.1), 0.045, seed=8),
                                                0.006, 0.004), noise2(0.004, 8.0, seed=9))
    y_basal = shift(dej, 0.03)
    y_sup = shift(surface, -0.035)
    parts.append(hlayer("Adventitia", "Wall layers", "#e5d3b0", 0.0, 0.06, OES["adventitia"], "fascia", XR, ZR,
                        bulk=True, rank=-4, res=120, detail=(0.14, 50.0, 0.15, 0)))
    _muscularis(parts, [("Outer longitudinal muscle", "#c25d51", 0.06, y_l, OES["long"], 1),
                        ("Inner circular muscle", "#a8463d", y_c0, y_c1, OES["circ"], 3)], y_l,
                network_y=shift(y_l, 0.006))
    parts.append(hlayer("Submucosa", "Submucosa", "#f0d2c3", y_c1, y_sub, GUT["submucosa"], "fascia", XR, ZR,
                        bulk=True, rank=-1, res=200, detail=(0.14, 55.0, 0.15, 0)))
    parts.append(hlayer("Muscularis mucosae", "Mucosa", "#b95a50", y_sub, y_mm, OES["mm"], "muscle", XR, ZR, rank=0,
                        res=200, detail=(0.08, 90.0, 0.4, 1)))
    parts.append(hlayer("Lamina propria & papillae", "Mucosa", "#efbfb2", y_mm, dej, OES["papillae"], "mucosa", XR,
                        ZR, bulk=True, rank=1, res=300, detail=(0.12, 100.0, 0.35, 0)))
    parts.append(hlayer("Basal cell layer", "Stratified squamous epithelium", "#96597a", dej, y_basal, OES["basal"],
                        "mucosa", XR, ZR, rank=2, res=300, detail=(0.10, 180.0, 0.95, 0)))
    parts.append(hlayer("Intermediate (prickle) layers", "Stratified squamous epithelium", "#e3b3b3",
                        lambda X, Z: np.minimum(y_basal(X, Z), y_sup(X, Z) - 0.01), y_sup, OES["intermediate"],
                        "mucosa", XR, ZR, rank=3, res=300, detail=(0.10, 120.0, 0.8, 0)))
    parts.append(hlayer("Superficial squamous layer", "Stratified squamous epithelium", "#f3dcd6", y_sup, surface,
                        OES["superficial"], "mucosa", XR, ZR, rank=4, res=300, detail=(0.06, 140.0, 0.6, 1)))

    # submucosal mucous glands with ducts through the mucosa
    glands = Volume((X0, 0.3, Z0), (X1, 0.75, Z1), 0.0035)
    ducts = Volume((X0, 0.3, Z0), (X1, 1.05, Z1), 0.0035)
    for i, (gx, gz) in enumerate([(-0.62, 0.0), (-0.2, 0.0), (0.0, 0.3), (0.45, -0.28)]):
        c = np.array([gx, (at(y_c1, gx, gz) + at(y_sub, gx, gz)) / 2 + 0.02, gz])
        acini = []
        for k in range(40):
            off = rng.normal(size=3) * np.array([0.08, 0.04, 0.07])
            r = rng.uniform(0.016, 0.024)
            acini.append(ellipsoid(c + off, (r, r * 0.8, r)))
        glands.add_all(acini, "smooth", 0.01)
        top = np.array([gx + 0.05, at(surface, gx + 0.05, gz + 0.03) + 0.005, gz + 0.03])
        mid = np.array([gx + 0.03, at(y_mm, gx, gz) + 0.02, gz + 0.02])
        path = np.array([c + np.array([0, 0.03, 0]), mid, top])
        ducts.tube(path, [0.011, 0.009, 0.008])
    glands.displace(0.0018, 50.0, 2, seed=12)
    parts.append(sdf_part(glands, "Oesophageal glands", "Glands & vessels", "#b7d3ea", OES["glands"], "gland",
                          rank=-1, detail=(0.08, 130.0, 0.8, 0)))
    parts.append(sdf_part(ducts, "Gland ducts", "Glands & vessels", "#8fb6d8", OES["ducts"], "gland", rank=1,
                          smooth=0.6))
    art, vein = _submucosal_vessels(y_c1, 40, 0.13)
    plexus = Mesh()
    for j, z in enumerate(np.linspace(-0.5, 0.5, 6)):
        path = wavy_path((X0 + 0.01, 0, z), (X1 - 0.01, 0, z + 0.03), 70, 0.03, 2.2, seed=60 + j)
        path[:, 1] = [at(y_sub, p[0], p[2]) - 0.06 for p in path]
        plexus.extend(tube(path, rng.uniform(0.02, 0.03), 20))
    parts += [mesh_part(art, "Submucosal artery", "Glands & vessels", "#cf3a31", GUT["sub_artery"], "artery", rank=-1),
              mesh_part(plexus, "Submucosal venous plexus", "Glands & vessels", "#3d5bc2", OES["veins"], "vein",
                        rank=-1)]
    return settle(parts, seed=302, amp_xz=0.030, amp_y=0.070, freq=1.5, grain=0.006)


# ==================================================================================================== trachea
def build_trachea():
    parts = []
    rng = np.random.default_rng(31)
    parts.append(hlayer("Adventitia", "Wall layers", "#e5d3b0", 0.0, 0.06, TRACH["adventitia"], "fascia", XR, ZR,
                        bulk=True, rank=-4, res=120, detail=(0.14, 50.0, 0.15, 0)))
    cart = Volume((X0, 0.03, Z0), (X1, 0.34, Z1), 0.0055)
    peri = Volume((X0, 0.03, Z0), (X1, 0.34, Z1), 0.0055)
    for cx in (-0.62, -0.08, 0.5):
        shape = box_shape((cx, 0.185, 0.0), (0.105, 0.095, 0.64), 0.07)
        cart.add(shape)
    cart.displace(0.004, 6.0, 3, seed=3)
    cart.intersect_box((X0, 0, Z0), (X1, 1, Z1))
    peri.d = np.maximum(cart.d - 0.016, -cart.d)
    peri.intersect_box((X0, 0, Z0), (X1, 1, Z1))
    # the ligament fills the gaps between the rings rather than burying them in a slab
    anu = Volume((X0, 0.03, Z0), (X1, 0.34, Z1), 0.0055)
    ax, ay, az = anu.axes()
    anu_box, _, _ = box_shape((0.0, 0.185, 0.0), (1.0, 0.130, (Z1 - Z0) / 2))
    anu.d = np.maximum(anu_box(ax, ay, az), -(peri.d - 0.004)).astype(np.float32)
    parts.append(sdf_part(anu, "Anular ligaments", "Cartilage", "#cdbf9f", TRACH["anular"], "ligament", smooth=0.7,
                          bulk=True, rank=-3, detail=(0.12, 60.0, 0.12, 3)))
    parts.append(sdf_part(cart, "Hyaline cartilage rings", "Cartilage", "#b9d3da", TRACH["rings"], "cartilage",
                          rank=-2, detail=(0.07, 38.0, 0.55, 0)))
    parts.append(sdf_part(peri, "Perichondrium", "Cartilage", "#dcd3bd", TRACH["perichondrium"], "ligament", rank=-2,
                          detail=(0.10, 90.0, 0.35, 0)))
    parts.append(hlayer("Submucosa", "Mucosa & submucosa", "#f0d2c3", 0.31, 0.52, TRACH["sub"], "fascia", XR, ZR,
                        bulk=True, rank=-1, res=160, detail=(0.14, 55.0, 0.15, 0)))
    parts.append(hlayer("Lamina propria", "Mucosa & submucosa", "#efbfb2", 0.52, 0.60, TRACH["lp"], "mucosa", XR, ZR,
                        bulk=True, rank=0, res=160, detail=(0.12, 110.0, 0.5, 0)))
    parts.append(hlayer("Basement membrane", "Epithelium", "#f5ecd0", 0.60, 0.609, TRACH["bm"], "cartilage", XR, ZR,
                        rank=0.5, res=100, detail=(0.02, 0.0, 0.0, 0)))
    epi_top = add(0.675, Grooves(poisson_disk((X0 - 0.05, Z0 - 0.05), (X1 + 0.05, Z1 + 0.05), 0.03, seed=5), 0.004,
                                 0.003))
    parts.append(hlayer("Pseudostratified ciliated epithelium", "Epithelium", "#d8b3c7", 0.609, epi_top, TRACH["epi"],
                        "mucosa", XR, ZR, rank=1, res=320, detail=(0.10, 190.0, 0.9, 2)))
    # cilia: a tuft of tapering hairs over every ciliated cell
    cilia = Mesh()
    cells = poisson_disk((X0 + 0.01, Z0 + 0.01), (X1 - 0.01, Z1 - 0.01), 0.030, seed=7)
    gob_pts = poisson_disk((X0 + 0.02, Z0 + 0.02), (X1 - 0.02, Z1 - 0.02), 0.085, seed=9)
    from scipy.spatial import cKDTree
    gtree = cKDTree(gob_pts)
    # a real ciliary carpet: every cell carries a dense tuft, and all of them lean the same way - the metachronal
    # wave that drives the mucociliary escalator towards the larynx
    offsets = [(dx * 0.0062, dz * 0.0062) for dx in (-1, 0, 1) for dz in (-1, 0, 1)]
    for cx, cz in cells:
        if gtree.query((cx, cz))[0] < 0.02:
            continue
        beat = 0.0075 + 0.0020 * math.sin(cx * 9.0 + cz * 5.0)      # the wave sweeping across the sheet
        for dx, dz in offsets:
            jx, jz = rng.uniform(-0.0012, 0.0012), rng.uniform(-0.0012, 0.0012)
            b0 = np.array([cx + dx + jx, 0.672, cz + dz + jz])
            h = 0.022 + rng.uniform(-0.002, 0.002)
            tipv = b0 + np.array([beat * 1.6, h, rng.uniform(-0.0018, 0.0018)])
            mid = b0 + np.array([beat * 0.45, h * 0.55, 0.0])
            cilia.add(*_hair(b0, mid, tipv, 0.0021))
    parts.append(mesh_part(cilia, "Cilia", "Epithelium", "#d6c9bf", TRACH["cilia"], "mucosa", rank=1.5,
                           detail=(0.03, 0.0, 0.0, 2)))
    gob = Volume((X0, 0.60, Z0), (X1, 0.70, Z1), 0.0028)
    for gx, gz in gob_pts:
        gob.add(ellipsoid((gx, 0.651, gz), (0.0145, 0.026, 0.0145)), "smooth", 0.006)
        gob.add(round_cone((gx, 0.660, gz), (gx, 0.679, gz), 0.011, 0.0075), "smooth", 0.006)
    parts.append(sdf_part(gob, "Goblet cells", "Epithelium", "#e6ecf6", TRACH["goblet"], "mucosa", smooth=0.6,
                          rank=1.2, detail=(0.03, 0.0, 0.0, 0)))
    # seromucous glands with serous demilunes, ducts to the surface
    muc = Volume((X0, 0.3, Z0), (X1, 0.7, Z1), 0.0035)
    ser = Volume((X0, 0.3, Z0), (X1, 0.7, Z1), 0.0035)
    dct = Volume((X0, 0.3, Z0), (X1, 0.7, Z1), 0.0035)
    for i, (gx, gz) in enumerate([(-0.35, 0.0), (0.0, 0.28), (0.25, -0.3), (-0.75, 0.0)]):
        c = np.array([gx, 0.43, gz])
        mshapes, sshapes = [], []
        for k in range(30):
            off = rng.normal(size=3) * np.array([0.075, 0.03, 0.065])
            r = rng.uniform(0.015, 0.022)
            mshapes.append(ellipsoid(c + off, (r, r * 0.85, r)))
            if k % 2 == 0:
                d = rng.normal(size=3)
                d /= np.linalg.norm(d)
                sshapes.append(ellipsoid(c + off + d * r * 0.9, (r * 0.55, r * 0.4, r * 0.55)))
        muc.add_all(mshapes, "smooth", 0.009)
        ser.add_all(sshapes, "smooth", 0.004)
        dct.tube(np.array([c + np.array([0, 0.02, 0]), c + np.array([0.02, 0.12, 0.01]), (gx + 0.03, 0.68, gz + 0.02)]),
                 [0.01, 0.008, 0.007])
    ser.d = np.maximum(ser.d, -muc.d)
    parts += [sdf_part(muc, "Mucous gland acini", "Glands", "#c7d6ea", TRACH["glands"], "gland", rank=-1,
                       detail=(0.06, 90.0, 0.6, 0)),
              sdf_part(ser, "Serous demilunes", "Glands", "#8c6fb4", TRACH["glands"], "gland", rank=-1,
                       detail=(0.06, 150.0, 0.95, 0)),
              sdf_part(dct, "Gland ducts", "Glands", "#a58fc9", TRACH["ducts"], "gland", rank=0.5, smooth=0.6)]
    return settle(parts, seed=303, amp_xz=0.026, amp_y=0.060, freq=1.5, grain=0.005)


def _hair(base, mid, tip, r):
    """Tiny tapered hair as a 5-sided tube: (positions, indices)."""
    path = np.array([base, mid, tip])
    m = tube(path, np.array([r, r * 0.7, r * 0.25]), 5, caps=True)
    p, n, i = m.arrays()
    return p, i, n
