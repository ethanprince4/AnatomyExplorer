"""High-resolution lung acinus, nephron and liver lobule models."""
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


# =================================================================================================== lung acinus
def build_alveoli():
    parts = []
    rng = np.random.default_rng(12)
    lo = np.array([-1.1, -0.62, -0.62])
    hi = np.array([1.05, 0.66, 0.62])
    vox = 0.0072
    vol = Volume(lo, hi, vox)
    x, y, z = vol.axes()
    # airway tree: terminal bronchiole -> respiratory bronchiole -> alveolar ducts
    tb = smooth_path(np.array([(-1.2, 0.02, 0.0), (-0.85, 0.0, 0.0), (-0.55, 0.03, 0.0)]), 20)
    rb = smooth_path(np.array([(-0.55, 0.03, 0.0), (-0.35, 0.06, 0.02), (-0.15, 0.05, 0.0)]), 20)
    ducts = []
    for k, (dy, dz) in enumerate([(0.28, 0.0), (-0.26, 0.1), (0.05, -0.34), (0.0, 0.34)]):
        a = rb[-1]
        mid = a + np.array([0.35, dy * 0.6, dz * 0.6])
        end = a + np.array([0.95, dy * 1.2, dz * 1.2])
        ducts.append(smooth_path(np.array([a, mid, end]), 24))
    # alveoli: Voronoi foam packed around the ducts
    centres = jittered_bcc(lo - 0.05, hi + 0.05, 0.17, 0.22, seed=3)
    grid = np.stack(np.broadcast_arrays(x, y, z), -1).reshape(-1, 3)
    d, _ = cKDTree(centres).query(grid, k=2, workers=-1)
    # tissue is the thin sheet that lies along each Voronoi boundary; everything else is air, so the acinus comes
    # out as a foam of open alveoli rather than a heap of solid pellets
    septa = ((d[:, 1] - d[:, 0]) / 2 - 0.0115).reshape(vol.shape).astype(np.float32)
    vol.d = septa
    # the acinus: a lobulated envelope around the duct tree (everything outside is left open)
    env = Volume(lo, hi, vox)
    env.tube(np.vstack([tb, rb]), 0.2)
    for p in ducts:
        env.tube(p, np.linspace(0.26, 0.34, len(p)), "smooth", 0.1)
    env.displace(0.03, 3.0, 2, seed=11)
    vol.d = np.maximum(vol.d, env.d)
    def env_at(p):
        return float(env.d[tuple(np.clip(((np.asarray(p) - lo) / vox).astype(int), 0, np.array(vol.shape) - 1))])

    centres = centres[np.array([env_at(c) < 0.02 for c in centres])]
    airways = Volume(lo, hi, vox)
    for path, r in [(tb, 0.1), (rb, 0.08)] + [(p, 0.065) for p in ducts]:
        airways.tube(path, r)
    mouths = []
    tree = cKDTree(np.vstack(ducts))
    duct_pts = np.vstack(ducts)
    for c in centres:
        dist, j = tree.query(c)
        if dist < 0.2:
            mouths.append(capsule(c, duct_pts[j], 0.045))
    for p in (rb,):
        for c in centres:
            dist = np.min(np.linalg.norm(p - c, axis=1))
            if dist < 0.16:
                mouths.append(capsule(c, p[np.argmin(np.linalg.norm(p - c, axis=1))], 0.035))
    airways.add_all(mouths, "union")
    vol.apply(airways.d, (slice(None),) * 3, "smooth_subtract", 0.012)
    # the terminal bronchiole keeps a complete wall
    tbwall = Volume(lo, hi, vox)
    tbwall.tube(tb, 0.125)
    inner = Volume(lo, hi, vox).tube(tb, 0.1)
    tbwall.d = np.maximum(tbwall.d, -inner.d)
    vol.d = np.where(tbwall.d < 0.02, np.maximum(vol.d, -(tbwall.d - 0.02)), vol.d).astype(np.float32)
    vol.intersect_box(lo + 0.02, hi - 0.02)
    septa_part = sdf_part(vol, "Alveolar septa (type I pneumocytes)", "Alveoli", "#efc2bd",
                          LUNG["alveoli"] + " " + LUNG["sac"] + " " + LUNG["duct"], "lung", smooth=0.8, rank=0,
                          detail=(0.08, 140.0, 0.45, 0))
    parts.append(septa_part)
    septa_vol = vol
    tbwall.intersect_box(lo + 0.02, hi - 0.02)
    parts.append(sdf_part(tbwall, "Terminal bronchiole wall", "Airways", "#e3aa9c", LUNG["tb"], "airway", rank=-1,
                          detail=(0.08, 170.0, 0.85, 1)))
    rbw = Volume(lo, hi, vox).tube(rb, 0.098)
    rbw.d = np.maximum(rbw.d, -Volume(lo, hi, vox).tube(rb, 0.08).d)
    rbw.apply(Volume(lo, hi, vox).add_all(mouths, "union").d, (slice(None),) * 3, "subtract")
    parts.append(sdf_part(rbw, "Respiratory bronchiole", "Airways", "#e9b8aa", LUNG["rb"], "airway", rank=-0.5,
                          detail=(0.08, 160.0, 0.8, 1)))
    # smooth muscle rings and club cells on the terminal bronchiole
    sm = Mesh()
    for t in np.linspace(0.1, 0.95, 7):
        c = tb[int(t * (len(tb) - 1))]
        ang = np.linspace(0, 2 * math.pi, 48)
        ring = np.stack([np.full_like(ang, c[0]), c[1] + 0.13 * np.cos(ang), c[2] + 0.13 * np.sin(ang)], -1)
        sm.extend(tube(ring, 0.011, 10, caps=False))
    parts.append(mesh_part(sm, "Bronchiolar smooth muscle", "Airways", "#b54a44", LUNG["sm"], "muscle", rank=-1,
                           detail=(0.08, 100.0, 0.5, 4)))
    club = Mesh()
    for t in np.linspace(0.05, 0.95, 16):
        c = tb[int(t * (len(tb) - 1))]
        a = rng.uniform(0, 2 * math.pi)
        dvec = np.array([0.0, math.cos(a), math.sin(a)])
        club.extend(ellipsoid_mesh(c + dvec * 0.098, (0.014, 0.018, 0.014), 10, rotation=frame_from_normal(-dvec)))
    parts.append(mesh_part(club, "Club (Clara) cells", "Airways", "#f2e3a3", LUNG["club"], "gland", rank=-1))
    # capillaries along the edges of the foam (septal junctions)
    vor = Voronoi(centres)
    capm = Mesh()
    capv = Volume(lo, hi, vox)                # also carved out of the septa so the capillaries show on the walls
    inside = lambda p: np.all(p > lo + 0.06) and np.all(p < hi - 0.06)
    count = 0
    duct_tree = cKDTree(np.vstack([np.vstack(ducts), tb, rb]))
    for ridge in vor.ridge_vertices:
        if -1 in ridge or count > 2600:
            continue
        verts = vor.vertices[ridge]
        for i in range(len(verts)):
            a, b = verts[i], verts[(i + 1) % len(verts)]
            if not (inside(a) and inside(b)) or np.linalg.norm(a - b) > 0.14:
                continue
            if env_at(a) > -0.015 or env_at(b) > -0.015:
                continue
            if duct_tree.query((a + b) / 2)[0] < 0.1:
                continue
            seg = np.array([a, (a + b) / 2 + rng.normal(scale=0.004, size=3), b])
            capm.extend(tube(seg, 0.0085, 8))
            capv.tube(seg, 0.0085)
            count += 1
    parts.append(mesh_part(capm, "Alveolar capillaries", "Vessels", "#d8433b", LUNG["cap"], "artery", rank=0.3))
    t2, mac = Mesh(), Mesh()
    t2v = Volume(lo, hi, vox)
    for i, p in enumerate(vor.vertices[:: 7]):
        if inside(p) and env_at(p) < -0.02 and duct_tree.query(p)[0] > 0.1 and len(t2.parts) < 260:
            n = rng.normal(size=3)
            n /= np.linalg.norm(n)
            t2.extend(ellipsoid_mesh(p + n * 0.014, (0.016, 0.014, 0.016), 10))
            t2v.add(ellipsoid(p + n * 0.014, (0.016, 0.014, 0.016)))
    parts.append(mesh_part(t2, "Type II pneumocytes", "Alveoli", "#f0d88f", LUNG["t2"], "gland", rank=0.2))
    mv = Volume(lo, hi, 0.0035).sub(lo, hi)
    for c in centres[rng.choice(len(centres), 12, replace=False)]:
        if not inside(c):
            continue
        shapes = [ellipsoid(c, (0.028, 0.024, 0.026))]
        for k in range(5):
            dvec = rng.normal(size=3)
            dvec /= np.linalg.norm(dvec)
            shapes.append(round_cone(c, c + dvec * 0.05, 0.012, 0.004))
        sub = Volume(c - 0.08, c + 0.08, 0.0035)
        sub.add_all(shapes, "smooth", 0.01)
        mac.extend(sub.mesh(0.7))
    parts.append(mesh_part(mac, "Alveolar macrophages", "Alveoli", "#b88f72", LUNG["mac"], "lymph", rank=0.2,
                           detail=(0.05, 60.0, 0.9, 0)))
    # capillaries and type II cells bulge out of the septum instead of being buried in it
    np.maximum(septa_vol.d, -(capv.d - 0.0012), out=septa_vol.d)
    np.maximum(septa_vol.d, -(t2v.d - 0.0012), out=septa_vol.d)
    septa_part.mesh = septa_vol.mesh(0.8)

    # vessels: arteriole beside the airway, venule at the lobule edge, pleura
    pa = smooth_path(np.array([(-1.1, 0.2, 0.12), (-0.5, 0.22, 0.12), (-0.1, 0.18, 0.1), (0.4, 0.3, 0.06)]), 40)
    pv = smooth_path(np.array([(1.0, -0.5, -0.45), (0.3, -0.52, -0.5), (-0.4, -0.5, -0.5), (-1.1, -0.48, -0.52)]), 40)
    parts.append(mesh_part(tube_shell(pa, 0.055, 0.04, 28), "Pulmonary arteriole (deoxygenated)", "Vessels", "#3d5bc2",
                           LUNG["pa"], "vein", rank=0.5))
    parts.append(mesh_part(tube_shell(pv, 0.06, 0.047, 28), "Pulmonary venule (oxygenated)", "Vessels", "#cf3a31",
                           LUNG["pv"], "artery", rank=0.5))
    return settle(parts, seed=501, amp_xz=0.024, amp_y=0.045, freq=1.6, grain=0.004)


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


# =================================================================================================== liver lobule
def build_liver_lobule():
    parts = []
    rng = np.random.default_rng(9)
    R, H = 0.9, 1.0
    corners = [np.array([R * math.cos(k * math.pi / 3), 0.0, R * math.sin(k * math.pi / 3)]) for k in range(6)]
    lo = np.array([-R - 0.12, 0.0, -R - 0.12])
    hi = np.array([R + 0.12, H, R + 0.12])
    vox = 0.0058
    vol = Volume(lo, hi, vox)
    x, y, z = vol.axes()
    r = np.sqrt(x ** 2 + z ** 2)
    th = np.arctan2(z, x)
    # hexagon boundary distance (positive outside)
    hexd = np.full(np.broadcast(x, z).shape, -1e3, np.float32)
    for k in range(6):
        a = k * math.pi / 3 + math.pi / 6
        hexd = np.maximum(hexd, x * math.cos(a) + z * math.sin(a) - R * math.cos(math.pi / 6))
    n_plates = 26
    wave = 0.44 * fbm3(x * 2.0, y * 2.0, z * 2.0, 1.0, 3, 4) + 0.16 * fbm3(x * 6.0, y * 5.0, z * 6.0, 1.0, 2, 9)
    phase = th * n_plates / (2 * math.pi) + wave
    arc = np.abs((phase % 1.0) - 0.5) * (2 * math.pi / n_plates) * np.maximum(r, 0.05)
    plates = (0.024 - arc).astype(np.float32)             # positive inside a plate
    # sparse anastomoses between neighbouring plates, the way real hepatic laminae join
    bridges = 0.013 - np.abs(np.sin(r * 15 + wave * 4) * np.sin(y * 9 + th * 3 + wave * 3)) * 0.05
    tissue = -np.maximum(plates, bridges.astype(np.float32))
    # each plate is one or two hepatocytes thick, so give it the relief of the cells themselves
    tissue = tissue - cell_lattice(x, y, z, 0.048, 0.010, seed=17)
    cv = np.sqrt(x ** 2 + z ** 2) - 0.1
    tissue = np.maximum(tissue, -cv + 0.012)
    tissue = np.maximum(tissue, hexd - 0.005)
    tissue = np.broadcast_to(tissue, vol.shape).astype(np.float32)
    for k, c in enumerate(corners):
        tract = np.sqrt((x - c[0]) ** 2 + (z - c[2]) ** 2) - 0.2
        tissue = np.maximum(tissue, -tract)
    # zones by relative distance from the central vein to the lobule edge
    rel = r / np.maximum(r - hexd, 1e-3)
    rel = np.broadcast_to(rel, vol.shape)
    zones = [("Hepatocytes – zone 3 (centrilobular)", "#c77a58", rel < 0.36, LIVER["z3"]),
             ("Hepatocytes – zone 2 (midzonal)", "#cf8a64", (rel >= 0.36) & (rel < 0.68), LIVER["z2"]),
             ("Hepatocytes – zone 1 (periportal)", "#d89a70", rel >= 0.68, LIVER["z1"])]
    for name, color, mask, desc in zones:
        zv = vol.copy(np.where(mask, tissue, np.maximum(tissue, 0.02)).astype(np.float32))
        zv.intersect_box(lo + 0.01, hi - 0.01)
        parts.append(sdf_part(zv, name, "Hepatic plates", color, desc, "organ", smooth=0.8, rank=0,
                              detail=(0.10, 95.0, 0.9, 0)))
    cv_path = curved_path(H + 0.04, bend=(0.02, -0.015), wobble=0.012, seed=3, n=64, axis=1) + np.array([0, H / 2, 0])
    _, cvm = tubule(cv_path, 0.085, 0.100, seed=61, cell=0.055, amp=0.007, aspect=2.0, lobe=(6, 0.07),
                    calibre=0.05, n_theta=96)
    parts.append(mesh_part(cvm, "Central vein", "Central vein", "#3d5bc2", LIVER["cv"], "vein", rank=1))
    bc, kup, ito = Mesh(), Mesh(), Mesh()
    for k in range(n_plates):
        a = (k + 0.5) * 2 * math.pi / n_plates
        for yy in (0.2, 0.5, 0.8):
            rs = np.linspace(0.14, R * 0.85, 30)
            wv = 0.45 * fbm3(rs * math.cos(a) * 2.2, np.full_like(rs, yy * 2.2), rs * math.sin(a) * 2.2, 1.0, 3, 4)
            ang = a - (wv % 1.0 - 0.5) * 0.0 - wv * (2 * math.pi / n_plates)
            path = np.stack([rs * np.cos(ang), np.full_like(rs, yy), rs * np.sin(ang)], -1)
            bc.extend(tube(path, 0.004, 6))
    parts.append(mesh_part(bc, "Bile canaliculi", "Hepatic plates", "#5fa05a", LIVER["canaliculi"], "biliary",
                           rank=0.5))
    for k in range(60):
        rr = rng.uniform(0.18, R * 0.8)
        a = (rng.integers(n_plates) + 0.0) * 2 * math.pi / n_plates
        c = np.array([rr * math.cos(a), rng.uniform(0.1, 0.9), rr * math.sin(a)])
        sub = Volume(c - 0.05, c + 0.05, 0.0025)
        shapes = [ellipsoid(c, (0.012, 0.01, 0.012))]
        for m in range(4):
            dvec = rng.normal(size=3)
            dvec /= np.linalg.norm(dvec)
            shapes.append(round_cone(c, c + dvec * 0.03, 0.005, 0.002))
        sub.add_all(shapes, "smooth", 0.005)
        (kup if k % 3 else ito).extend(sub.mesh(0.6))
    parts.append(mesh_part(kup, "Kupffer cells", "Sinusoids", "#7a5c9e", LIVER["kupffer"], "lymph", rank=0.5))
    parts.append(mesh_part(ito, "Stellate (Ito) cells", "Sinusoids", "#f1d36c", LIVER["stellate"], "fat", rank=0.5))
    pv, ha, bd, ct = Mesh(), Mesh(), Mesh(), Mesh()
    for k, c in enumerate(corners):
        tract_path = (curved_path(H + 0.03, bend=(0.018 * math.cos(k), 0.018 * math.sin(k)), wobble=0.010,
                                  seed=20 + k, n=56, axis=1) + np.array([c[0], H / 2, c[2]]))
        tsw = Sweep(tract_path, 108, 56)
        ct.extend(tsw.solid(rsum(0.126, lobed(3, 0.034, 0.6), surf_noise(0.020, 3.0, 2.4, 80 + k))))
        off = lambda dx, dz: tract_path + np.array([dx, 0.0, dz])
        _, m_pv = tubule(off(-0.03, 0.02), 0.064, 0.076, seed=90 + k, cell=0.050, amp=0.006, aspect=2.2,
                         lobe=(6, 0.07), calibre=0.05, n_theta=72)
        pv.extend(m_pv)
        _, m_ha = tubule(off(0.075, -0.055), 0.012, 0.028, seed=110 + k, cell=0.030, amp=0.004, aspect=0.4,
                         lobe=(5, 0.06), calibre=0.05, n_theta=56)
        ha.extend(m_ha)
        _, m_bd = tubule(off(0.052, 0.082), 0.012, 0.030, seed=130 + k, cell=0.034, amp=0.006, aspect=1.0,
                         lobe=(7, 0.07), calibre=0.05, n_theta=56)
        bd.extend(m_bd)
    parts += [
        mesh_part(ct, "Portal tract connective tissue", "Portal triads", "#e8d2b4", LIVER["septa"], "fascia",
                  bulk=True, rank=1, label=False, alpha=0.40, detail=(0.12, 55.0, 0.2, 2)),
        mesh_part(pv, "Portal venules", "Portal triads", "#6a4fb5", LIVER["pv"], "vein", rank=1.2),
        mesh_part(ha, "Hepatic arterioles", "Portal triads", "#cf3a31", LIVER["ha"], "artery", rank=1.2,
                  detail=(0.06, 120.0, 0.6, 2)),
        mesh_part(bd, "Bile ductules", "Portal triads", "#5fa05a", LIVER["bd"], "biliary", rank=1.2,
                  detail=(0.08, 180.0, 0.95, 2)),
    ]
    return settle(parts, seed=503, amp_xz=0.030, amp_y=0.060, freq=1.4, grain=0.005)
