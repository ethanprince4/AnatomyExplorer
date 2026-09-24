"""Peripheral nerve and skeletal muscle: bundles of bundles.

Both are built the same way. A curved trunk is swept first; every fascicle inside it then follows its own path
spiralling slowly around that trunk, so fascicles plait past one another instead of running as parallel rods, and
every fibre inside a fascicle follows its fascicle. The connective-tissue sheaths - epineurium, perineurium,
epimysium, perimysium - are given out-of-round sections and a felt of real collagen bundles on the outside.
"""
import math

import numpy as np

from .base import Part
from .cells import extrude, poisson_disk
from .geometry import Mesh, ellipsoid as ellipsoid_mesh, smooth_path, tube
from .kit import Volume, ellipsoid, mesh_part, round_cone, sdf_part
from .organic import (Sweep, cells_on, collagen_felt, curved_path, lobed, rsum, surf_noise, texture)
from .organs import MUSCLE, NERVE


def _pack(radius, spacing, seed):
    pts = poisson_disk((-radius, -radius), (radius, radius), spacing, seed=seed)
    return pts[np.hypot(pts[:, 0], pts[:, 1]) < radius - spacing * 0.40]


def _child(sw, theta0, r0, drift, wobble, seed, n=110):
    """Path of a fascicle inside a trunk: a slow spiral with a meander of its own."""
    rng = np.random.default_rng(seed)
    s = np.linspace(0.0, 1.0, n)
    ph = rng.uniform(0, 2 * math.pi, 2)
    theta = theta0 + drift * s + wobble * 1.6 * np.sin(2.1 * math.pi * s + ph[0])
    r = r0 * (1.0 + wobble * np.sin(1.7 * math.pi * s + ph[1]))
    return sw.curve(s, theta, r)


# ==================================================================================================== nerve
FASCICLES = [(0.00, 0.00, 0.225, 0.55), (0.45, 0.40, 0.150, -0.70), (1.95, 0.43, 0.135, 0.62),
             (3.30, 0.40, 0.165, -0.50), (4.55, 0.44, 0.120, 0.75), (5.60, 0.38, 0.100, -0.85)]


def build_nerve():
    parts = []
    rng = np.random.default_rng(21)
    trunk = Sweep(curved_path(2.0, bend=(0.075, -0.055), wobble=0.038, freq=1.0, seed=5), 240, 120)

    epi_r = rsum(0.66, lobed(6, 0.050, 0.7), surf_noise(0.026, 3.0, 2.4, 5), surf_noise(0.006, 17.0, 9.0, 6))
    parts.append(Part("Epineurium", "Connective tissue", "#e8dcc2", trunk.solid(epi_r), NERVE["epineurium"],
                      category="fascia", bulk=True, clip=True, detail=(0.14, 50.0, 0.15, 1)))
    parts.append(mesh_part(collagen_felt(trunk, rsum(epi_r, -0.006), rsum(epi_r, 0.058), 170, seed=90,
                                         r_range=(0.006, 0.016)),
                           "Epineurial collagen bundles", "Connective tissue", "#ddcba4",
                           "Longitudinally arranged bundles of type I collagen in the outer epineurium. They take "
                           "the tension of limb movement, which is why a nerve can be stretched about 10 per cent "
                           "before its fascicles are loaded at all.", "ligament", rank=0.3,
                           detail=(0.12, 45.0, 0.12, 1)))

    peri, endo, myelin, axons, remak_s, remak_a, schwann = (Mesh() for _ in range(7))
    fas_paths = []
    for fi, (th0, r0, fr, drift) in enumerate(FASCICLES):
        path = _child(trunk, th0, r0, drift, 0.10, seed=300 + fi)
        fsw = Sweep(path, 132, 76)
        fas_paths.append((fsw, fr))
        core = rsum(fr, lobed(5, fr * 0.12, 0.9), surf_noise(fr * 0.07, 3.4, 3.0, 30 + fi))
        endo.extend(fsw.solid(rsum(core, 0.002)))
        for k in range(3):
            off = 0.006 + k * 0.0085
            peri.extend(fsw.shell(rsum(core, off), rsum(core, off + 0.0048)))
        s = np.linspace(0.0, 1.0, 44)
        for k, (py, pz) in enumerate(_pack(fr, 0.048, seed=100 + fi)):
            th = math.atan2(pz, py)
            rr = math.hypot(py, pz)
            ph = rng.uniform(0, 2 * math.pi)
            wob = 0.035 * np.sin(s * 7.0 + ph)
            line = fsw.curve(s, th + wob * 0.5, rr * (1.0 + wob))
            if rng.random() < 0.72:
                rad = rng.uniform(0.013, 0.019)
                axons.extend(tube(line, rad * 0.46, 10))
                seg = rng.uniform(0.16, 0.23)                      # internode length as a fraction of the block
                start = -rng.uniform(0, seg)
                while start < 1.0:
                    a, b = max(start + 0.008, 0.0), min(start + seg - 0.008, 1.0)
                    if b - a > 0.045:
                        ss = np.linspace(a, b, 11)
                        w = 0.035 * np.sin(ss * 7.0 + ph)
                        prof = np.full(11, rad)
                        prof[0], prof[-1] = rad * 0.5, rad * 0.5
                        prof[1], prof[-2] = rad * 0.92, rad * 0.92
                        seg_line = fsw.curve(ss, th + w * 0.5, rr * (1.0 + w))
                        myelin.extend(tube(seg_line, prof, 14))
                        if rng.random() < 0.55:
                            mid = (a + b) / 2
                            c = fsw.curve(np.array([mid]), np.array([th + 0.035 * math.sin(mid * 7 + ph) * 0.5]),
                                          np.array([rr * (1 + 0.035 * math.sin(mid * 7 + ph)) + rad * 0.95]))[0]
                            schwann.extend(ellipsoid_mesh(c, (0.040, 0.006, 0.009), 8))
                    start += seg
            else:
                remak_s.extend(tube(line, 0.013, 12))
                for j in range(5):
                    a = j * 2 * math.pi / 5
                    remak_a.extend(tube(line + np.array([0.0, 0.006 * math.cos(a), 0.006 * math.sin(a)]), 0.0028, 6))
    parts += [
        mesh_part(peri, "Perineurium", "Connective tissue", "#e2cf9e", NERVE["perineurium"], "ligament", rank=0.5,
                  detail=(0.08, 120.0, 0.5, 4)),
        mesh_part(endo, "Endoneurium", "Connective tissue", "#f3e8d8", NERVE["endoneurium"], "fascia", bulk=True,
                  rank=0.2, label=False, detail=(0.10, 90.0, 0.2, 1)),
        mesh_part(myelin, "Myelin sheaths (internodes)", "Nerve fibres", "#f3efe2",
                  NERVE["myelin"] + " " + NERVE["node"], "white_matter", rank=1, detail=(0.04, 0.0, 0.0, 1)),
        mesh_part(axons, "Axons", "Nerve fibres", "#e2ae47", NERVE["axon"], "nerve", rank=1,
                  detail=(0.05, 0.0, 0.0, 1)),
        mesh_part(remak_s, "Remak Schwann cells", "Nerve fibres", "#d9cfb5", NERVE["unmyelinated"], "fascia", rank=1,
                  detail=(0.06, 80.0, 0.4, 1)),
        mesh_part(remak_a, "Unmyelinated axons (C fibres)", "Nerve fibres", "#c99a52", NERVE["unmyelinated"], "nerve",
                  rank=1, label=False),
        mesh_part(schwann, "Schwann cell nuclei", "Nerve fibres", "#5059a3", NERVE["schwann"], "nucleus", rank=1,
                  detail=(0.03, 0.0, 0.0, 0)),
    ]

    vasa = Mesh()
    s = np.linspace(0.02, 0.98, 56)
    for k, (th0, r0, rad) in enumerate(((0.9, 0.56, 0.030), (2.7, 0.60, 0.024), (4.3, 0.58, 0.028),
                                        (5.9, 0.52, 0.022))):
        th = th0 + 0.8 * s + 0.18 * np.sin(2.0 * math.pi * s + k)
        r = r0 + 0.04 * np.sin(1.6 * math.pi * s + k)
        vasa.extend(tube(trunk.curve(s, th, r), rad, 14))
        for _ in range(3):
            i = int(rng.integers(8, 46))
            bs = np.clip(s[i] + np.linspace(0, 0.14, 9), 0, 1)
            bt = th[i] + np.linspace(0, rng.uniform(-0.8, 0.8), 9)
            br = r[i] + np.linspace(0, rng.uniform(-0.18, 0.10), 9)
            vasa.extend(tube(trunk.curve(bs, bt, br), np.linspace(rad * 0.55, rad * 0.2, 9), 8))
    parts.append(mesh_part(vasa, "Vasa nervorum", "Connective tissue", "#cf3a31", NERVE["vasa"], "artery", rank=0))

    fat = Mesh()
    for _ in range(8):
        s0, t0 = rng.uniform(0.08, 0.92), rng.uniform(0, 2 * math.pi)
        origin = trunk.curve(np.array([s0]), np.array([t0]), np.array([rng.uniform(0.44, 0.56)]))[0]
        n = int(rng.integers(10, 18))
        centres = origin + rng.normal(0, 0.052, (n, 3)) * np.array([1.5, 1.0, 1.0])
        radii = rng.uniform(0.030, 0.050, n)
        v = Volume(centres.min(0) - 0.09, centres.max(0) + 0.09, 0.005)
        for c, rr in zip(centres, radii):
            v.add(ellipsoid(c, (rr, rr * rng.uniform(0.85, 1.15), rr * rng.uniform(0.85, 1.15))), "smooth", 0.014)
        fat.extend(v.mesh(0.7))
    parts.append(mesh_part(fat, "Epineurial fat", "Connective tissue", "#f3d98e", NERVE["fat"], "fat", rank=0,
                           detail=(0.05, 22.0, 0.08, 0)))
    return texture(parts, seed=21, grain=0.006, grain_across=12.0, grain_along=2.5, micro=0.0032, micro_freq=46.0)


# ==================================================================================================== muscle
def _rounded(poly, gap, radius):
    g = poly.buffer(-(gap + radius), join_style=2)
    if g.is_empty:
        return None
    g = g.buffer(radius, quad_segs=9) if radius > 0 else g
    if g.geom_type == "MultiPolygon":
        g = max(g.geoms, key=lambda q: q.area)
    return None if g.is_empty or g.area < 1e-5 else g


def _cells_in(points, region, gap, radius):
    from shapely.geometry import MultiPoint
    from shapely.ops import voronoi_diagram
    vd = voronoi_diagram(MultiPoint([tuple(p) for p in points]), envelope=region.envelope.buffer(1.0))
    out = []
    for cell in vd.geoms:
        c = cell.intersection(region)
        if c.is_empty:
            continue
        if c.geom_type == "MultiPolygon":
            c = max(c.geoms, key=lambda q: q.area)
        if gap or radius:
            c = _rounded(c, gap, radius)
        if c is not None and c.geom_type == "Polygon" and not c.is_empty:
            out.append(c)
    return out


def _circle_poly(r, n=72):
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return np.stack([r * np.cos(a), r * np.sin(a)], -1)


def build_muscle():
    parts = []
    rng = np.random.default_rng(6)
    L, R = 1.0, 0.60
    path = curved_path(2.0, bend=(0.065, -0.050), wobble=0.034, freq=1.0, seed=9)
    trunk = Sweep(path, 232, 116)
    # the fibres are extruded along x, so they are bent by the same offsets that define the trunk centreline
    off_y = np.interp(np.linspace(-L, L, 400), path[:, 0], path[:, 1])
    off_z = np.interp(np.linspace(-L, L, 400), path[:, 0], path[:, 2])
    xs_ref = np.linspace(-L, L, 400)

    def bend_y(t):
        return np.interp(t, xs_ref, off_y)

    def bend_z(t):
        return np.interp(t, xs_ref, off_z)

    epi_in = rsum(R + 0.010, lobed(7, 0.030, 0.8), surf_noise(0.018, 3.0, 2.4, 2))
    epi_out = rsum(epi_in, 0.045, surf_noise(0.010, 6.0, 3.0, 3))
    parts.append(Part("Epimysium", "Connective tissue", "#e9dfc9", trunk.shell(epi_in, epi_out), MUSCLE["epimysium"],
                      category="fascia", clip=True, rank=2, detail=(0.12, 50.0, 0.15, 1)))
    parts.append(mesh_part(collagen_felt(trunk, rsum(epi_out, -0.008), rsum(epi_out, 0.055), 170, seed=91,
                                         r_range=(0.006, 0.016)),
                           "Epimysial collagen bundles", "Connective tissue", "#dccba8",
                           "Coarse collagen of the epimysium, continuous with the tendon at each end of the muscle. "
                           "It is the layer a fascial plane is developed in surgically.", "ligament", rank=2.2,
                           detail=(0.12, 45.0, 0.12, 1)))
    parts.append(Part("Perimysium", "Connective tissue", "#e3d3b3", trunk.solid(rsum(epi_in, -0.002)),
                      MUSCLE["perimysium"], category="fascia", bulk=True, clip=True, rank=1.5,
                      detail=(0.14, 55.0, 0.18, 1)))

    from shapely.geometry import Point, Polygon
    region = Polygon(_circle_poly(R - 0.015, 96))
    fas_pts = np.array([(0.0, 0.0)] + [(0.31 * math.cos(a), 0.31 * math.sin(a)) for a in
                                       np.linspace(0, 2 * math.pi, 7)[:-1] + 0.3] +
                       [(0.50 * math.cos(a), 0.50 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 9)[:-1] + 0.1])
    fas_pts += rng.uniform(-0.035, 0.035, fas_pts.shape)
    fibers, endo, nuclei, caps = Mesh(), Mesh(), Mesh(), Mesh()
    t_vals = np.linspace(-L, L, 84)

    def mapping(phase, amp=0.004, centre=None, swell=0.0):
        """Extrusion that follows the muscle's curved axis, meanders a little, and - with `swell` - lets each fibre
        thicken and narrow along its length instead of running as a constant prism."""
        cu, cv = (0.0, 0.0) if centre is None else (float(centre[0]), float(centre[1]))

        def f(U, V, T):
            k = 1.0 + swell * (np.sin(T * 3.3 + phase) + 0.6 * np.sin(T * 7.1 + phase * 1.7))
            return (T, cu + (U - cu) * k + bend_y(T) + amp * np.sin(T * 5 + phase),
                    cv + (V - cv) * k + bend_z(T) + amp * np.cos(T * 4 + phase))
        return f

    for fi, fcell in enumerate(_cells_in(fas_pts, region, 0.0, 0.0)):
        sheath = _rounded(fcell, 0.016, 0.020)
        if sheath is None:
            continue
        sh = np.array(sheath.exterior.coords)[:-1]
        endo.extend(extrude(sh, mapping(fi, 0.006, sh.mean(axis=0), 0.012), t_vals))
        inner = fcell.buffer(-0.022)
        if inner.is_empty:
            continue
        minx, miny, maxx, maxy = inner.bounds
        pts = [p for p in poisson_disk((minx, miny), (maxx, maxy), 0.046, seed=200 + fi) if inner.contains(Point(p))]
        if len(pts) < 2:
            continue
        for ci, cell in enumerate(_cells_in(np.array(pts), inner, 0.0040, 0.013)):
            shape = np.array(cell.exterior.coords)[:-1]
            phase = fi * 1.3 + ci * 0.7
            fibers.extend(extrude(shape, mapping(phase, 0.006, shape.mean(axis=0), 0.045), t_vals))
            for k in range(4):
                j = rng.integers(len(shape))
                u, v = shape[j] * 0.90 + shape.mean(axis=0) * 0.10
                x = rng.uniform(-L + 0.12, L - 0.12)
                nuclei.extend(ellipsoid_mesh((x, u + bend_y(x) + 0.006 * math.sin(x * 5 + phase), v + bend_z(x)),
                                             (0.032, 0.005, 0.005), 8))
            if ci % 2 == 0:
                u, v = shape[0]
                xs = np.linspace(-L, L, 46)
                caps.extend(tube(np.stack([xs, u + bend_y(xs) + 0.005 * np.sin(xs * 7 + ci), v + bend_z(xs)], -1),
                                 0.0042, 8))
    parts += [
        mesh_part(endo, "Endomysium (fascicle sheaths)", "Connective tissue", "#f0e2cf",
                  MUSCLE["endomysium"] + " " + MUSCLE["fascicle"], "fascia", bulk=True, rank=1, label=False,
                  detail=(0.1, 60.0, 0.15, 1)),
        mesh_part(fibers, "Muscle fibres", "Muscle fibres", "#b0463f", MUSCLE["fibers"], "muscle", rank=0.5,
                  detail=(0.06, 260.0, 0.0, 1)),
        mesh_part(nuclei, "Myonuclei", "Muscle fibres", "#4c3f8c", MUSCLE["nuclei"], "nucleus", rank=0.6,
                  detail=(0.03, 0.0, 0.0, 0)),
        mesh_part(caps, "Endomysial capillaries", "Nerves & vessels", "#d8433b", MUSCLE["cap"], "artery", rank=0.6),
    ]

    myo = Mesh()
    c = np.array([0.0, 0.08 + bend_y(L), -0.12 + bend_z(L)])
    for m in range(11):
        a = m * 2 * math.pi / 11
        yz = c[1:] + 0.022 * np.array([math.cos(a), math.sin(a)]) if m else c[1:]
        xs = np.linspace(L, L + 0.5, 24)
        myo.extend(tube(np.stack([xs, np.full_like(xs, yz[0]) + 0.005 * np.sin(xs * 8 + m),
                                  np.full_like(xs, yz[1]) + 0.004 * np.cos(xs * 6 + m)], -1), 0.0080, 12))
    parts.append(mesh_part(myo, "Myofibrils", "Muscle fibres", "#cf6a60", MUSCLE["myofibrils"], "muscle", rank=0.5,
                           detail=(0.05, 330.0, 0.0, 1)))

    s = np.linspace(0.0, 1.0, 40)
    nerve_path = trunk.curve(s, 1.1 + 0.5 * s, 0.90 - 0.55 * s ** 1.4)
    parts.append(mesh_part(tube(nerve_path, np.linspace(0.020, 0.013, 40), 14), "Motor nerve branch",
                           "Nerves & vessels", "#f0cf45", MUSCLE["nerve"], "nerve", rank=2.5))
    nc = nerve_path[-1]
    nmj = Volume(nc - 0.14, nc + 0.14, 0.0022)
    shapes = [ellipsoid(nc, (0.035, 0.009, 0.026))]
    for k in range(7):
        a = k * 2 * math.pi / 7
        shapes.append(round_cone(nc, nc + np.array([0.042 * math.cos(a), -0.005, 0.032 * math.sin(a)]), 0.007, 0.005))
    nmj.add_all(shapes, "smooth", 0.006)
    parts.append(sdf_part(nmj, "Neuromuscular junction", "Nerves & vessels", "#f7dd6a", MUSCLE["nmj"], "nerve",
                          smooth=0.6, rank=2.5))

    sp_axis = np.array([-0.40, bend_y(-0.40) + 0.20, bend_z(-0.40) - 0.28])
    a0, a1 = sp_axis - np.array([0.34, 0.0, 0.0]), sp_axis + np.array([0.34, 0.0, 0.0])
    sp = Volume(np.minimum(a0, a1) - 0.12, np.maximum(a0, a1) + 0.12, 0.003)
    sp.add(round_cone(a0, sp_axis, 0.012, 0.046), "smooth", 0.02)
    sp.add(round_cone(sp_axis, a1, 0.046, 0.012), "smooth", 0.02)
    shell = sp.copy(np.maximum(sp.d, -(sp.d + 0.004)))
    parts.append(sdf_part(shell, "Muscle spindle capsule", "Nerves & vessels", "#e9e3d2", MUSCLE["spindle"], "fascia",
                          smooth=0.6, rank=1.5))
    intra = Mesh()
    for k in range(4):
        a = k * math.pi / 2
        d = np.array([0.0, 0.017 * math.sin(a), 0.017 * math.cos(a)])
        intra.extend(tube(np.linspace(a0 + d + np.array([0.04, 0, 0]), a1 + d - np.array([0.04, 0, 0]), 14),
                          0.0065, 10))
    parts.append(mesh_part(intra, "Intrafusal fibres", "Nerves & vessels", "#c9665d", MUSCLE["spindle"], "muscle",
                           rank=1.5, label=False, detail=(0.06, 200.0, 0.0, 1)))
    return texture(parts, seed=6, grain=0.005, grain_across=11.0, grain_along=2.0, micro=0.0042, micro_freq=30.0)
