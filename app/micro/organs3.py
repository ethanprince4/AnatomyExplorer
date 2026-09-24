"""High-resolution nephron model. The lung acinus and liver lobule live in lung.py and liver.py and are re-exported
here for existing imports."""
import math

import numpy as np
from scipy.spatial import Voronoi, cKDTree

from .base import Part
from .cells import jittered_bcc, poisson_disk, sample_surface, frame_from_normal
from .geometry import Mesh, ellipsoid as ellipsoid_mesh, smooth_path, tube
from .kit import (Volume, capsule, coil_path, ellipsoid, mesh_part, round_cone, sdf_part, tube_mesh, tube_shell,
                  wavy_path)
from .organs import LIVER, LUNG, NEPH
from .organic import Sweep, cell_lattice, curved_path, lobed, rsum, settle, surf_noise, tubule
from .sdf import fbm3
from .liver import build_liver_lobule  # noqa: F401,E402
from .lung import build_alveoli  # noqa: F401,E402


# =================================================================================================== nephron
def build_nephron():
    parts = []
    rng = np.random.default_rng(4)
    gc = np.array([-0.3, 1.0, 0.0])
    # glomerular tuft: looping capillaries in a ball
    tuft = Volume(gc - 0.26, gc + 0.26, 0.0032)
    for k in range(4):
        loop = coil_path(gc + rng.normal(scale=0.03, size=3), 0.16, points=220, seed=10 + k, step=0.02, length=0.9,
                         radii=(0.16, 0.14, 0.16))
        tuft.tube(loop, 0.017)
    tuft.displace(0.0012, 60.0, 2, seed=2)
    parts.append(sdf_part(tuft, "Glomerular capillaries", "Renal corpuscle", "#d23d34", NEPH["glom"], "artery",
                          smooth=0.7, detail=(0.05, 170.0, 0.5, 0)))
    tpos, tn = [], []
    pod = Volume(gc - 0.28, gc + 0.28, 0.0032)
    pts, nrm = sample_surface(tuft.mesh(0.7), 0.06, seed=3)
    for p, n in zip(pts, nrm):
        c = p + n * 0.012
        shapes = [ellipsoid(c, (0.015, 0.012, 0.015))]
        for k in range(4):
            dvec = rng.normal(size=3)
            dvec -= n * np.dot(dvec, n)
            dvec /= np.linalg.norm(dvec) + 1e-9
            shapes.append(round_cone(c, c + dvec * 0.035 - n * 0.008, 0.006, 0.003))
        pod.add_all(shapes, "smooth", 0.006)
    parts.append(sdf_part(pod, "Podocytes", "Renal corpuscle", "#8fcac1", NEPH["podocytes"], "gland", smooth=0.6,
                          detail=(0.05, 110.0, 0.9, 0)))
    # Bowman capsule opening into the proximal tubule at the urinary pole
    cap = Volume(gc - np.array([0.36, 0.36, 0.36]), gc + np.array([0.5, 0.36, 0.36]), 0.004)
    cap.add(ellipsoid(gc, (0.29, 0.28, 0.29)))
    pct_start = gc + np.array([0.27, -0.1, 0.0])
    neck = smooth_path(np.array([gc + np.array([0.15, -0.06, 0]), pct_start, pct_start + np.array([0.12, -0.05, 0.03])]),
                       12)
    cap.tube(neck, 0.05, "smooth", 0.03)
    inner = cap.copy(cap.d + 0.012)
    shell = cap.copy(np.maximum(cap.d, -inner.d))
    vp = cap.copy(np.full(cap.shape, 1e3, np.float32)).add(capsule(gc, gc + np.array([-0.4, 0.05, 0.0]), 0.07))
    shell.apply(vp.d, (slice(None),) * 3, "subtract")
    parts.append(sdf_part(shell, "Bowman capsule (parietal layer)", "Renal corpuscle", "#e8d9d1", NEPH["bowman"],
                          "serosa", smooth=0.7, alpha=0.32, detail=(0.05, 120.0, 0.6, 0)))
    aff = smooth_path(np.array([(-1.15, 1.25, 0.05), (-0.8, 1.15, 0.05), (-0.58, 1.07, 0.02), (-0.4, 1.03, 0.0)]), 40)
    eff = smooth_path(np.array([(-0.4, 0.97, 0.07), (-0.62, 0.92, 0.15), (-0.9, 0.85, 0.25), (-1.15, 0.8, 0.3)]), 40)
    parts.append(mesh_part(tube_shell(aff, 0.038, 0.022, 28), "Afferent arteriole", "Renal corpuscle", "#c8322b",
                           NEPH["aff"], "artery", detail=(0.06, 120.0, 0.6, 4)))
    parts.append(mesh_part(tube_shell(eff, 0.028, 0.015, 24), "Efferent arteriole", "Renal corpuscle", "#a82a25",
                           NEPH["eff"], "artery", detail=(0.06, 120.0, 0.6, 4)))
    jg = Mesh()
    for t in np.linspace(0.62, 0.95, 7):
        p = aff[int(t * (len(aff) - 1))]
        a = t * 9
        off = np.array([0.0, math.cos(a), math.sin(a)]) * 0.036
        jg.extend(ellipsoid_mesh(p + off, (0.016, 0.013, 0.013), 10, rotation=frame_from_normal(off)))
    parts.append(mesh_part(jg, "Juxtaglomerular cells", "Renal corpuscle", "#e9b04a", NEPH["jg"], "gland"))
    # tubules as hollow walls
    pct = smooth_path(np.array([pct_start + np.array([0.12, -0.05, 0.03]), (0.15, 0.72, 0.2), (0.42, 1.05, 0.35),
                                (0.62, 0.78, 0.1), (0.36, 0.56, -0.25), (0.66, 0.36, -0.2), (0.45, 0.12, 0.0)]), 160)
    loop_d = smooth_path(np.array([(0.45, 0.12, 0.0), (0.46, -0.4, 0.02), (0.45, -1.1, 0.0)]), 60)
    turn = smooth_path(np.array([(0.45, -1.1, 0), (0.4, -1.2, 0.0), (0.3, -1.2, 0), (0.25, -1.1, 0)]), 20)
    loop_u = smooth_path(np.array([(0.25, -1.1, 0.0), (0.24, -0.5, -0.02), (0.25, 0.3, 0.0)]), 60)
    dct = smooth_path(np.array([(0.25, 0.3, 0.0), (0.05, 0.6, -0.15), (-0.15, 0.85, -0.2), (-0.34, 0.86, -0.08),
                                (-0.1, 0.55, -0.35), (0.05, 0.35, -0.5), (0.85, 0.3, -0.5)]), 120)
    cd = smooth_path(np.array([(0.85, 1.3, -0.5), (0.86, 0.3, -0.5), (0.9, -0.6, -0.45), (0.95, -1.35, -0.4)]), 80)
    # every tubule is a wall of cells rather than a length of pipe: the epithelium bulges into the lumen, the
    # calibre wanders, and each segment's cells are the size and shape of the real thing
    seg_specs = [
        (pct, 0.022, 0.050, "Proximal convoluted tubule", "Tubule", "#e59b8c", NEPH["pct"], "organ",
         (0.08, 140.0, 0.9, 0), 0.055, 0.011, 1.0, True, 31),
        (np.vstack([loop_d[:7]]), 0.022, 0.050, "Straight proximal tubule", "Tubule", "#e39888", NEPH["pct"],
         "organ", None, 0.055, 0.010, 1.0, False, 33),
        (loop_d[6:], 0.017, 0.024, "Thin descending limb", "Loop of Henle", "#efe0cc", NEPH["thin_desc"], "serosa",
         (0.05, 150.0, 0.7, 2), 0.045, 0.005, 1.6, True, 35),
        (np.vstack([turn, loop_u[1:20]]), 0.017, 0.024, "Thin ascending limb", "Loop of Henle", "#e2ddc6",
         NEPH["thin_asc"], "serosa", (0.05, 150.0, 0.7, 2), 0.045, 0.005, 1.6, True, 37),
        (loop_u[19:], 0.020, 0.042, "Thick ascending limb", "Loop of Henle", "#d7a6c8", NEPH["tal"], "organ",
         (0.08, 150.0, 0.9, 2), 0.050, 0.009, 1.0, True, 39),
        (dct, 0.022, 0.042, "Distal convoluted tubule", "Tubule", "#c69ad6", NEPH["dct"], "organ",
         (0.08, 150.0, 0.9, 0), 0.050, 0.009, 1.0, True, 41),
        (cd, 0.042, 0.065, "Collecting duct", "Tubule", "#9ec4e0", NEPH["cd"], "organ", (0.08, 120.0, 0.9, 2),
         0.065, 0.011, 1.3, True, 43),
    ]
    for path, ri, ro, name, group, colour, desc, cat, det, cell, camp, asp, lab, sd in seg_specs:
        _, mesh = tubule(path, ri, ro, seed=sd, cell=cell, amp=camp, aspect=asp, lobe=(6, 0.05), calibre=0.07,
                         n_theta=76)
        parts.append(mesh_part(mesh, name, group, colour, desc, cat, label=lab,
                               detail=det if det is not None else (0.08, 140.0, 0.9, 0)))
    md = Mesh()
    p = dct[len(dct) // 3]
    for k in range(10):
        a = k * 0.25
        md.extend(ellipsoid_mesh(p + np.array([0.0, 0.04 * math.cos(a) - 0.02, 0.04 * math.sin(a)]),
                                 (0.01, 0.022, 0.01), 8))
    parts.append(mesh_part(md, "Macula densa", "Tubule", "#8e6db5", NEPH["md"], "gland"))
    ptc, vr = Mesh(), Mesh()
    for host, wrap_r, turns, count, step in ((pct, 0.070, 5.0, 14, 11), (dct, 0.062, 4.0, 10, 11),
                                             (loop_u[19:], 0.058, 3.0, 5, 8), (loop_d[6:], 0.052, 3.0, 5, 10)):
        for k in range(count):
            i0 = k * step
            seg = host[i0: i0 + int(step * 1.9)]
            if len(seg) < 10:
                continue
            idx = np.linspace(0, len(seg) - 1, 64).astype(int)
            a = np.linspace(0, turns * 2 * math.pi, 64) + k
            tangent = np.gradient(seg[idx], axis=0)
            tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-9)
            side = np.cross(tangent, np.array([0.0, 1.0, 0.0]))
            bad = np.linalg.norm(side, axis=1) < 1e-3
            side[bad] = np.cross(tangent[bad], np.array([1.0, 0.0, 0.0]))
            side /= np.maximum(np.linalg.norm(side, axis=1, keepdims=True), 1e-9)
            up = np.cross(side, tangent)
            rr = wrap_r * (1.0 + 0.12 * np.sin(a * 0.7 + k))
            path = seg[idx] + side * (rr * np.cos(a))[:, None] + up * (rr * np.sin(a))[:, None]
            ptc.extend(tube(path, rng.uniform(0.0050, 0.0080), 8))
            if k % 2 == 0:                                  # cross-links between neighbouring loops
                j = 20 + (k * 7) % 20
                ptc.extend(tube(smooth_path(np.array([path[j], (path[j] + path[j + 22]) / 2 +
                                                      rng.normal(scale=0.02, size=3), path[j + 22]]), 12),
                                0.0042, 6))
    for off in (-0.085, 0.085, 0.0):
        vr.extend(tube(smooth_path(np.array([(0.35 + off, 0.16, 0.10 + off * 0.4), (0.36 + off, -0.6, 0.12),
                                             (0.35 + off, -1.18, 0.10)]), 46), 0.011, 12))
    for off in (-0.05, 0.05):
        vr.extend(tube(smooth_path(np.array([(0.22 + off, 0.10, -0.06), (0.24 + off, -0.65, -0.05),
                                             (0.23 + off, -1.20, -0.04)]), 46), 0.009, 10))
    parts += [mesh_part(ptc, "Peritubular capillaries", "Vessels", "#d8433b", NEPH["ptc"], "artery"),
              mesh_part(vr, "Vasa recta", "Vessels", "#b93a47", NEPH["vr"], "artery")]
    return settle(parts, seed=502, amp_xz=0.026, amp_y=0.050, freq=1.5, grain=0.005)
