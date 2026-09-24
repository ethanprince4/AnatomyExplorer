"""Compact bone: osteons, interstitial lamellae, periosteum and the trabecular margin.

Osteons are not drilled holes. Each Haversian canal wanders slightly as it runs, and the lamellae around it are
irregular ovals rather than circles - so a cut face shows the ragged, overlapping mosaic of a real cortex instead of
a set of printed bullseyes. The periosteum is built as a felt of collagen anchored by Sharpey fibres that actually
penetrate the outer circumferential lamellae.
"""
import math

import numpy as np

from .base import Part
from .geometry import Mesh, ellipsoid as ellipsoid_mesh, slab, smooth_path, tube
from .kit import Volume, mesh_part, sdf_part
from .organic import Sweep, curved_path, lobed, rmul, rsum, settle, surf_noise
from .organs import BONE
from .sdf import fbm3

H = 1.3
Z0, Z1 = -0.55, 0.55
OSTEONS = [(-0.45, 0.0, 0.20, 5), (0.0, 0.30, 0.19, 6), (-0.02, -0.27, 0.18, 4), (0.45, 0.05, 0.20, 5),
           (-0.62, -0.35, 0.15, 6), (0.55, -0.37, 0.14, 4), (0.52, 0.42, 0.13, 5), (-0.45, 0.40, 0.14, 6)]


def _osteon_sweep(cx, cz, i, n_theta=136, n_s=46):
    # slightly longer than the block so the cut ends of the lamellae never fight the matrix for the same plane
    path = curved_path(H + 0.05, bend=(0.020 * math.cos(i * 1.7), 0.020 * math.sin(i * 2.3)), wobble=0.016, freq=1.2,
                       seed=i, n=n_s, axis=1)
    path = path + np.array([cx, H / 2.0, cz])
    return Sweep(path, n_theta, n_s)


def _osteon_shape(i, lobes):
    """Multiplicative outline shared by every ring of one osteon, so the rings nest however irregular it is."""
    out = rsum(1.0, lobed(lobes, 0.052, 0.9), surf_noise(0.030, 3.2, 2.2, 60 + i),
               surf_noise(0.010, 15.0, 7.0, 70 + i))
    return lambda base: rmul(base, out)


def build_osteon():
    parts = []
    rng = np.random.default_rng(8)
    canal, vessels, lam_a, lam_b, cement, ost, canalic = (Mesh() for _ in range(7))
    for i, (cx, cz, R, lobes) in enumerate(OSTEONS):
        sw = _osteon_sweep(cx, cz, i)
        shape = _osteon_shape(i, lobes)
        rc = 0.035 + 0.012 * rng.random()
        canal.extend(sw.shell(shape(rc - 0.007), shape(rc)))
        s = np.linspace(0.0, 1.0, 26)
        for off, rv in ((-0.011, 0.009), (0.012, 0.011)):
            th = np.full(26, 0.4 if off < 0 else 3.4)
            vessels.extend(tube(sw.curve(s, th, np.full(26, abs(off))), rv, 12))
        n_rings = 5 + int(R > 0.17)
        radii = np.linspace(rc + 0.005, R - 0.014, n_rings + 1)
        for k in range(n_rings):
            ring = sw.shell(shape(radii[k] + 0.0018), shape(radii[k + 1] - 0.0018))
            (lam_a if k % 2 == 0 else lam_b).extend(ring)
            r_out = shape(radii[k + 1] - 0.004)
            for _ in range(int(9 + k * 2.5)):
                a = rng.uniform(0, 2 * math.pi)
                sv = rng.uniform(0.05, 0.95)
                aa, ss = np.array([a]), np.array([sv])
                r_here = float(np.ravel(r_out(aa, ss))[0])
                c = sw.curve(ss, aa, np.array([r_here]))[0]
                radial = np.array([math.cos(a), 0.0, math.sin(a)])
                tang = np.array([-math.sin(a), 0.0, math.cos(a)])
                rot = np.stack([tang, np.array([0.0, 1.0, 0.0]), radial], axis=1)
                ost.extend(ellipsoid_mesh(c, (0.016, 0.009, 0.005), 8, rotation=rot))
                for m in range(6):
                    sgn = 1 if m % 2 else -1
                    d = radial * sgn + tang * rng.uniform(-0.4, 0.4) + np.array([0, rng.uniform(-0.3, 0.3), 0])
                    d /= np.linalg.norm(d)
                    canalic.extend(tube(np.array([c, c + d * 0.02, c + d * 0.034]),
                                        np.array([0.0018, 0.0014, 0.001]), 4, caps=True))
        cement.extend(sw.shell(shape(R - 0.011), shape(R - 0.005)))
    parts += [
        mesh_part(canal, "Central (Haversian) canals", "Osteons", "#8b5a4e", BONE["canal"], "fascia", rank=1,
                  detail=(0.1, 90.0, 0.5, 2)),
        mesh_part(vessels, "Canal vessels & nerves", "Osteons", "#cf3a31", BONE["vessels"], "artery", rank=1),
        mesh_part(lam_a, "Concentric lamellae (set A)", "Osteons", "#efe5cf", BONE["lamellae"], "bone", rank=1,
                  detail=(0.08, 0.0, 0.0, 0)),
        mesh_part(lam_b, "Concentric lamellae (set B)", "Osteons", "#dccfb3", BONE["lamellae"], "bone", rank=1,
                  detail=(0.08, 0.0, 0.0, 0)),
        mesh_part(cement, "Cement lines", "Osteons", "#b8a27a", BONE["cement"], "bone", rank=1,
                  detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(ost, "Osteocytes in lacunae", "Osteons", "#6f4538", BONE["osteocytes"], "nucleus", rank=1.1,
                  detail=(0.03, 0.0, 0.0, 0)),
        mesh_part(canalic, "Canaliculi", "Osteons", "#8f6a5a", BONE["osteocytes"], "nucleus", rank=1.1, label=False,
                  detail=(0.02, 0.0, 0.0, 0)),
    ]

    a, b = OSTEONS[0], OSTEONS[3]
    path = smooth_path(np.array([(a[0], 0.62, a[1]), ((a[0] + b[0]) / 2, 0.68, (a[1] + b[1]) / 2 - 0.06),
                                 (b[0], 0.71, b[1]), (0.86, 0.76, b[1] + 0.04), (1.12, 0.80, b[1] + 0.09)]), 50)
    parts.append(mesh_part(tube(path, 0.026, 16), "Perforating (Volkmann) canal", "Osteons", "#7c4f45",
                           BONE["volkmann"], "fascia", rank=1.2))
    parts.append(mesh_part(tube(path, 0.009, 10), "Volkmann canal vessel", "Osteons", "#cf3a31", BONE["vessels"],
                           "artery", rank=1.2, label=False))

    parts.append(Part("Interstitial lamellae & matrix", "Bone matrix", "#e6dac1",
                      slab(-0.85, 0.85, Z0, Z1, lambda X, Z: H + 0 * X, lambda X, Z: 0 * X, 150),
                      BONE["interstitial"], category="bone", bulk=True, clip=True, rank=0,
                      detail=(0.10, 40.0, 0.35, 2)))
    ocl = Mesh()
    for k in range(5):
        x0 = 0.85 + k * 0.026
        ocl.extend(slab(x0 + 0.002, x0 + 0.024, Z0, Z1, lambda X, Z: H + 0 * X, lambda X, Z: 0 * X, 26))
    parts.append(mesh_part(ocl, "Outer circumferential lamellae", "Periosteum", "#e9dec7", BONE["outer_circ"], "bone",
                           rank=2, detail=(0.08, 45.0, 0.35, 2)))
    parts.append(Part("Periosteum – cambium layer", "Periosteum", "#c98b80",
                      slab(0.982, 1.018, Z0, Z1, lambda X, Z: H + 0 * X, lambda X, Z: 0 * X, 60),
                      BONE["periosteum_c"], category="fascia", clip=True, rank=2.2, detail=(0.1, 150.0, 0.9, 0)))

    # fibrous periosteum: real collagen bundles running along the bone, not a smooth board
    fib = Mesh()
    frng = np.random.default_rng(77)
    t = np.linspace(0.0, 1.0, 40)
    for _ in range(320):
        ph = frng.uniform(0, 2 * math.pi)
        if frng.random() < 0.72:                       # most bundles run along the bone
            y0, y1 = frng.uniform(-0.02, 0.35), frng.uniform(H - 0.35, H + 0.02)
            ys = y0 + (y1 - y0) * t
            zs = frng.uniform(Z0, Z1) + 0.10 * np.sin(2.2 * math.pi * t + ph)
        else:                                          # the rest wind around it
            zs = Z0 - 0.02 + (Z1 - Z0 + 0.04) * t
            ys = frng.uniform(0.02, H - 0.02) + 0.13 * np.sin(2.0 * math.pi * t + ph)
        ys = np.clip(ys, -0.01, H + 0.01)
        zs = np.clip(zs, Z0 - 0.02, Z1 + 0.02)
        xs = 1.024 + 0.062 * (0.5 + 0.5 * np.sin(3.0 * math.pi * t + ph * 1.3)) + frng.uniform(0.0, 0.010)
        fib.extend(tube(np.stack([xs, ys, zs], -1), frng.uniform(0.0045, 0.0105), 7))
    parts.append(mesh_part(fib, "Periosteum – fibrous layer", "Periosteum", "#dcb79c", BONE["periosteum_f"],
                           "ligament", clip=True, rank=2.4, detail=(0.12, 55.0, 0.15, 2)))

    sh = Mesh()
    srng = np.random.default_rng(78)
    for y in np.linspace(0.10, H - 0.10, 11):
        for z in np.linspace(-0.48, 0.48, 7):
            yy = y + srng.uniform(-0.03, 0.03)
            zz = z + srng.uniform(-0.03, 0.03)
            ctrl = np.array([(1.10, yy + 0.07, zz + 0.03), (1.04, yy + 0.02, zz + 0.01), (0.98, yy - 0.03, zz),
                             (0.90, yy - 0.07, zz - 0.01)])
            sh.extend(tube(smooth_path(ctrl, 16), np.linspace(0.0060, 0.0028, 16), 8))
    parts.append(mesh_part(sh, "Sharpey fibres", "Periosteum", "#f2e9d6", BONE["sharpey"], "ligament", rank=2.4))

    parts.append(Part("Endosteum", "Marrow side", "#c98b80",
                      slab(-0.885, -0.85, Z0, Z1, lambda X, Z: H + 0 * X, lambda X, Z: 0 * X, 60), BONE["endosteum"],
                      category="fascia", clip=True, rank=-1, detail=(0.1, 150.0, 0.9, 0)))
    tr = Volume((-1.4, 0.0, Z0), (-0.88, H, Z1), 0.005)
    x, y, z = tr.axes()
    f = 12.0
    g = (np.sin(x * f) * np.cos(y * f) + np.sin(y * f) * np.cos(z * f) + np.sin(z * f) * np.cos(x * f))
    g = g + 0.6 * fbm3(x * 4, y * 4, z * 4, 1.0, 3, 7) + 0.35 * fbm3(x * 9, y * 9, z * 9, 1.0, 2, 11)
    tr.d = (np.abs(g) - 0.36).astype(np.float32) * 0.03
    tr.d = np.minimum(tr.d, (x + 0.9).astype(np.float32) * np.ones_like(tr.d))
    tr.intersect_box((-1.38, 0.0, Z0), (-0.86, H, Z1))
    parts.append(sdf_part(tr, "Trabeculae (spongy bone)", "Marrow side", "#e4d7bd", BONE["trabeculae"], "bone",
                          smooth=0.9, rank=-2, detail=(0.10, 45.0, 0.4, 0)))
    parts.append(Part("Red marrow", "Marrow side", "#b8473f",
                      slab(-1.38, -0.89, Z0, Z1, lambda X, Z: H + 0 * X, lambda X, Z: 0 * X, 50), BONE["marrow"],
                      alpha=0.35, category="organ", bulk=True, clip=True, rank=-2.5, detail=(0.12, 200.0, 0.95, 0)))
    return settle(parts, seed=601, amp_xz=0.018, amp_y=0.026, freq=1.5, shear=0.008, grain=0.004, grain_across=15.0,
                  grain_along=4.0, grain_axis=1, micro=0.0030, micro_freq=22.0)
