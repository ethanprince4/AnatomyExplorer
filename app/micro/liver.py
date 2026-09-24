"""Liver lobule: hepatic plates radiating from a central vein, portal triads at the corners, sinusoid cells, bile
canaliculi and the zones of the liver acinus."""
import math

import numpy as np

from .cellkit import band_cells, chunked, star_cell
from .cells import frame_from_normal
from .geometry import Mesh, ellipsoid as ellipsoid_mesh, frames, smooth_path, tube
from .kit import Volume, ellipsoid, mesh_part, sdf_part, sphere
from .organic import Sweep, rmul, rsum, settle, surf_noise, tubule
from .sdf import fbm3


# =================================================================================================== liver lobule
LIVER_D = {
    "z1": "Zone 1 (periportal) hepatocytes: first to receive blood from the portal venule and hepatic arteriole, so "
          "richest in oxygen and nutrients. Main site of gluconeogenesis, β-oxidation, cholesterol synthesis and the "
          "urea cycle. First injured by viral hepatitis and ingested direct toxins (e.g. cocaine, iron).",
    "z2": "Zone 2 (midzonal) hepatocytes: intermediate oxygen and metabolic profile between zones 1 and 3; "
          "characteristically necrotic in yellow fever.",
    "z3": "Zone 3 (centrilobular) hepatocytes: last to receive blood and poorest in oxygen, but richest in "
          "cytochrome P450 (CYP2E1). Site of glycolysis, lipogenesis and drug metabolism, so first to die in "
          "ischaemia, right heart failure ('nutmeg liver') and paracetamol overdose, and where alcoholic steatosis "
          "and hepatitis begin.",
    "limiting": "Limiting plate (lamina limitans): the continuous ring of periportal hepatocytes that walls off the "
                "portal tract from the parenchyma. Inlet venules and canals of Hering pierce it. In chronic hepatitis "
                "lymphocytes spill across and destroy it – interface ('piecemeal') hepatitis.",
    "cv": "Central (terminal hepatic) vein: a thin wall of endothelium and a little collagen, with no muscle; the "
          "sinusoids open straight into it. It drains into sublobular and then hepatic veins and the IVC. Zone 3 "
          "around it suffers first in hypoxia; occluded in Budd–Chiari syndrome and veno-occlusive disease.",
    "sinus_endo": "Sinusoidal endothelial cells: flat cells lining the sinusoids – the channels between the plates "
                  "through which blood runs from the portal tract to the central vein. The lining is discontinuous, "
                  "with no basal lamina and clusters of ~100 nm open fenestrae (sieve plates), so plasma but not blood "
                  "cells reaches the hepatocytes. The narrow gap between these cells and the plates is the space of "
                  "Disse (perisinusoidal space): hepatocyte microvilli, reticular fibres and stellate cells lie in it, "
                  "and hepatic lymph forms there. In cirrhosis the fenestrae close and collagen fills the space of "
                  "Disse ('capillarisation'), blocking exchange.",
    "kupffer": "Kupffer cells: resident macrophages sitting in the sinusoid lumen on the endothelium, most numerous "
               "periportally. They clear gut-derived bacteria and endotoxin and old red cells (iron, bilirubin "
               "production), and swell with haemosiderin in iron overload.",
    "stellate": "Hepatic stellate (Ito) cells: pericytes in the space of Disse storing vitamin A in lipid droplets. "
                "Activated by injury (TGF-β), they become myofibroblasts that lay down the collagen of fibrosis and "
                "cirrhosis.",
    "canaliculi": "Bile canaliculi: 1–2 µm channels formed by grooves in the membranes of adjacent hepatocytes, "
                  "sealed by tight junctions, belting each cell within the plate. Bile flows in them towards the "
                  "portal tract (opposite to blood) and leaves via the canals of Hering. Bile plugs here = "
                  "cholestasis.",
    "hering": "Canals of Hering: short channels lined partly by hepatocytes and partly by cholangiocytes, joining the "
              "canaliculi to the bile ductules across the limiting plate. They harbour hepatic progenitor cells "
              "that proliferate (ductular reaction) after massive necrosis.",
    "pv": "Portal venule: the largest, thin-walled vessel of the portal tract, a branch of the portal vein carrying "
          "nutrient-rich, oxygen-poor blood from the gut and spleen (~75% of hepatic blood flow).",
    "inlet": "Inlet (distributing) venules: side branches of the portal venule running along the lobule border and "
             "emptying into the sinusoids through the limiting plate; they form the axis of the liver acinus.",
    "ha": "Hepatic arteriole: small, thick-walled muscular vessel of the portal tract carrying well-oxygenated blood "
          "(~25% of flow but about half of the oxygen); its blood mixes with portal blood in the sinusoids. It also "
          "supplies the bile ducts (peribiliary plexus), so hepatic artery thrombosis after transplant causes "
          "biliary necrosis.",
    "bd": "Bile ductule (interlobular bile duct): a ring of cuboidal cholangiocytes on a basement membrane, carrying "
          "bile towards the hilum. Destroyed in primary biliary cholangitis; proliferates in large-duct obstruction.",
    "lymph": "Lymphatic vessel: thin-walled, irregular and often collapsed; drains lymph formed in the space of Disse "
             "via the space of Mall at the portal tract edge. The liver makes a quarter to half of all thoracic "
             "duct lymph.",
    "ct": "Portal tract (portal canal) connective tissue: collagen of Glisson capsule that sheathes the portal "
          "venule, hepatic arteriole, bile ductule (the 'triad'), lymphatics and nerves at the corners of the lobule. "
          "Fibrous septa bridging portal tracts are the first step towards cirrhosis.",
    "nb": "Hepatic plates of the neighbouring classic lobules. In humans there is no connective-tissue septum "
          "between lobules (unlike the pig), so plates run on from one lobule into the next and the border is only "
          "implied by the line joining the portal tracts.",
    "acinus": "Liver acinus (Rappaport): the functional unit centred on the inlet vessels running between two portal "
              "tracts and reaching out to the two central veins on either side, a diamond. Blood flows from its axis "
              "towards its tips, so zone 1 lies along the axis and zone 3 at the central veins. This overlay marks "
              "one acinus; the hepatocyte colours show the same zones throughout the lobule.",
}

LIV_R = 0.78                      # centre-to-corner radius of the hexagonal lobule
LIV_H = 0.42                      # the slab: a length of lobule prism running up y
_LIV_APO = LIV_R * math.cos(math.pi / 6)
# the lobule and the six neighbours whose edges reach into the block
LIV_CENTRES = np.array([[0.0, 0.0]] + [[math.sqrt(3) * LIV_R * math.cos(math.pi / 6 + k * math.pi / 3),
                                        math.sqrt(3) * LIV_R * math.sin(math.pi / 6 + k * math.pi / 3)]
                                       for k in range(6)])
LIV_PHASE = np.array([0.0, 0.31, 0.77, 0.12, 0.55, 0.93, 0.40])
LIV_CORNERS = [np.array([LIV_R * math.cos(k * math.pi / 3), 0.0, LIV_R * math.sin(k * math.pi / 3)])
               for k in range(6)]
# hepatic plates: (plates around the vein, phase offset, relative radius where the set begins). New plates start in
# the middle of the widening sinusoids, so plates branch as the lobule widens, as real laminae do
PLATE_SETS = ((14, 0.0, 0.0), (14, 0.5, 0.30), (28, 0.25, 0.63))


def _lobule_frame(x, z):
    """Polar coordinates about the central vein of whichever lobule a point lies in, and the hexagon distance."""
    X, Z = np.broadcast_arrays(np.asarray(x, np.float32), np.asarray(z, np.float32))
    d2 = np.stack([(X - c[0]) ** 2 + (Z - c[1]) ** 2 for c in LIV_CENTRES])
    idx = np.argmin(d2, axis=0)
    dx = X - LIV_CENTRES[idx, 0].astype(np.float32)
    dz = Z - LIV_CENTRES[idx, 1].astype(np.float32)
    r = np.sqrt(dx * dx + dz * dz)
    th = np.arctan2(dz, dx)
    hexd = np.full(X.shape, -1e3, np.float32)
    for k in range(6):
        a = math.pi / 6 + k * math.pi / 3
        hexd = np.maximum(hexd, dx * math.cos(a) + dz * math.sin(a) - _LIV_APO)
    rel = r / np.maximum(r - hexd, 1e-3)
    return r, th, hexd, rel, idx


def _plate_swing(x, y, z):
    """Angular meander of the plates: they curve and twist gently instead of running as ruled spokes."""
    return 0.10 * fbm3(x * 1.5, y * 1.5, z * 1.5, 1.0, 3, 4) + 0.03 * fbm3(x * 5.0, y * 4.0, z * 5.0, 1.0, 2, 9)


def _liver_plates(x, y, z, fr, windows=True):
    """Signed field of the hepatic plates (positive inside, roughly a distance)."""
    r, th, hexd, rel, idx = fr
    t = th + _plate_swing(x, y, z) + LIV_PHASE[idx].astype(np.float32) * (2 * math.pi / 14)
    hw = 0.0170 + 0.004 * fbm3(x * 6.0, y * 6.0, z * 6.0, 1.0, 2, 21)
    out = None
    for n, off, start in PLATE_SETS:
        u = t * (n / (2 * math.pi)) - off
        f = hw - np.abs(u - np.round(u)) * (2 * math.pi / n) * r
        if start:
            f = np.minimum(f, (rel - start) * 0.45)
        out = f if out is None else np.maximum(out, f)
    if windows:
        # plates anastomose here and there across the sinusoids, so the sinusoids form a web, not slots
        out = np.maximum(out, (fbm3(x * 11.0, y * 11.0, z * 11.0, 1.0, 2, 33) - 0.44) * 0.10)
    return out


def _hex_clip(x, z, margin=0.0):
    """Distance outside the block's outline: a hexagon parallel to the lobule's borders, 0.15 beyond them, so the
    neighbouring lobules show as a rim whose plates are cut across, end on."""
    d = None
    for k in range(6):
        a = math.pi / 6 + k * math.pi / 3
        e = x * math.cos(a) + z * math.sin(a) - (_LIV_APO + 0.15 - margin)
        d = e if d is None else np.maximum(d, e)
    return d


def _clip(vol, margin=0.004):
    """Trim a volume to the hexagonal block and its floor and roof."""
    x, y, z = vol.axes()
    np.maximum(vol.d, np.maximum(_hex_clip(x, z, margin), np.maximum(margin - y, y - (LIV_H - margin))), out=vol.d)
    return vol


def _cv_axis(y):
    return 0.010 * np.sin(np.asarray(y) * 3.1 + 0.4), 0.008 * np.sin(np.asarray(y) * 2.3 + 1.9)


def _tract_axis(k, y):
    y = np.asarray(y)
    c = LIV_CORNERS[k]
    return c[0] + 0.014 * np.sin(y * 2.7 + k * 1.3), c[2] + 0.012 * np.sin(y * 3.3 + k * 0.7 + 2.0)


def _tract_d(x, y, z, k):
    """Distance outside portal tract k: a three-pointed column following the three lobule borders that meet there."""
    cx, cz = _tract_axis(k, y)
    dx, dz = x - cx, z - cz
    th = np.arctan2(dz, dx) - k * math.pi / 3
    rad = 0.128 + 0.026 * np.cos(3 * th) + 0.012 * fbm3(x * 5.0, y * 4.0, z * 5.0, 1.0, 2, 70 + k)
    return np.sqrt(dx * dx + dz * dz) - rad


def _tract_frame(k):
    a = k * math.pi / 3
    return np.array([math.cos(a), 0.0, math.sin(a)]), np.array([-math.sin(a), 0.0, math.cos(a)])


def _tract_path(k, du, dw, n=48):
    u, w = _tract_frame(k)
    ys = np.linspace(-0.012, LIV_H + 0.012, n)
    cx, cz = _tract_axis(k, ys)
    p = np.stack([cx, ys, cz], -1) + u * du + w * dw
    return p + np.stack([0.004 * np.sin(ys * 7 + du * 40), 0 * ys, 0.004 * np.cos(ys * 6 + dw * 40)], -1)


# where each triad vessel sits in its tract, in (outward, sideways) offsets from the corner
TRIAD = {"pv": (-0.012, -0.022), "ha": (0.052, 0.058), "bd": (-0.030, 0.070), "lymph": (0.060, -0.074)}


def build_liver_lobule():
    parts = []
    rng = np.random.default_rng(9)
    H = LIV_H
    lo = np.array([-0.97, 0.0, -0.84])
    hi = np.array([0.97, H, 0.84])
    vox = 0.0085
    vol = Volume(lo, hi, vox)
    x2, _, z2 = vol.axes()
    fr2 = _lobule_frame(x2, z2)
    rel2, idx2, hexd2 = fr2[3], fr2[4], fr2[2]

    def tissue_fn(x, y, z):
        fr = _lobule_frame(x, z)
        t = -_liver_plates(x, y, z, fr)
        cx, cz = _cv_axis(y)
        t = np.maximum(t, 0.090 - np.sqrt((x - cx) ** 2 + (z - cz) ** 2))
        td = np.min(np.stack(np.broadcast_arrays(*[_tract_d(x, y, z, k) for k in range(6)])), axis=0)
        return np.maximum(t, 0.038 - td)

    vol.d = chunked(vol, tissue_fn)
    # the limiting plate: an unbroken ring of hepatocytes around each portal tract
    lim = Volume(lo, hi, vox)
    lim.d = chunked(lim, lambda x, y, z: np.min(np.stack(np.broadcast_arrays(
        *[np.maximum(_tract_d(x, y, z, k) - 0.036, 0.003 - _tract_d(x, y, z, k)) for k in range(6)])), axis=0))
    # inlet venules leave each portal venule along the lobule borders and open into the sinusoids
    inlets = []
    for k in range(6):
        u, w = _tract_frame(k)
        pv0 = LIV_CORNERS[k] + u * TRIAD["pv"][0] + w * TRIAD["pv"][1]
        for j, other in enumerate(((k + 1) % 6, (k + 5) % 6, None)):
            dirn = (LIV_CORNERS[other] - LIV_CORNERS[k]) if other is not None else u.copy()
            dirn /= np.linalg.norm(dirn)
            yy = 0.12 + 0.17 * ((k + j) % 2) + rng.uniform(-0.03, 0.03)
            a = pv0 + np.array([0, yy, 0])
            ln = rng.uniform(0.24, 0.32)
            if _hex_clip(*(a + dirn * ln)[[0, 2]], 0.03) > 0:
                continue
            side = np.cross(dirn, [0.0, 1.0, 0.0])
            path = smooth_path(np.array([a, a + dirn * ln * 0.5 + side * rng.uniform(-0.02, 0.02) +
                                         np.array([0, rng.uniform(-0.03, 0.03), 0]), a + dirn * ln]), 18)
            inlets.append((path, np.linspace(0.016, 0.006, len(path))))
    for path, rr in inlets:
        vol.tube(path, rr + 0.006, "smooth_subtract", 0.01)
        lim.tube(path, rr + 0.005, "subtract")
    band_cells(vol, vol.d, 0.040, 0.016, 17)
    band_cells(lim, lim.d, 0.038, 0.011, 18)
    _clip(vol)
    _clip(lim)
    # zones by relative distance from the central vein to the lobule border (the acinar axis)
    zones = [("Hepatocytes – zone 3 (centrilobular)", "#b8705a", -1.0, 0.34, LIVER_D["z3"]),
             ("Hepatocytes – zone 2 (midzonal)", "#c9866a", 0.34, 0.67, LIVER_D["z2"]),
             ("Hepatocytes – zone 1 (periportal)", "#d89d7c", 0.67, 9.0, LIVER_D["z1"])]
    for name, color, r0, r1, desc in zones:
        band = np.maximum((rel2 - r1) * 0.6, (r0 - rel2) * 0.6) + 0.0015
        zv = vol.copy(np.maximum(vol.d, band))
        zv.d = np.maximum(zv.d, np.where(idx2 == 0, -1.0, 1.0).astype(np.float32) * 0.02)
        parts.append(sdf_part(zv, name, "Hepatic plates", color, desc, "organ", smooth=0.7, rank=0,
                              detail=(0.10, 90.0, 0.95, 0)))
    # the neighbouring lobules, whose plates meet this one's along its borders, as a lighter mesh
    nb = vol.copy(np.maximum(vol.d, np.where(idx2 == 0, 0.02, -1.0).astype(np.float32)))
    parts.append(sdf_part(nb, "Hepatocytes – neighbouring lobules", "Hepatic plates", "#c68d72", LIVER_D["nb"],
                          "organ", smooth=0.8, rank=0, step=2, detail=(0.10, 90.0, 0.95, 0)))
    parts.append(sdf_part(lim, "Limiting plate", "Hepatic plates", "#dcaa86", LIVER_D["limiting"], "organ",
                          smooth=0.7, rank=0.3, detail=(0.10, 90.0, 0.95, 0)))
    parts.append(mesh_part(_tubes(inlets, 12), "Inlet venules", "Portal triads",
                           "#7a5cc4", LIVER_D["inlet"], "vein", rank=1.1))
    tissue = vol

    # central vein: a thin wall whose gaps are where the sinusoids pour in
    cvv = Volume(np.array([-0.14, lo[1], -0.14]), np.array([0.14, hi[1], 0.14]), 0.0045)

    def cv_fn(x, y, z):
        cx, cz = _cv_axis(y)
        dx, dz = x - cx, z - cz
        q = np.sqrt(dx * dx + dz * dz) - (0.074 + 0.004 * fbm3(x * 9, y * 6, z * 9, 1.0, 2, 5))
        return np.maximum(q - 0.013, -q)
    cvv.d = chunked(cvv, cv_fn)
    # the sinusoids open through gaps in the wall, between the plates that abut it
    holes = []
    for k in range(14):
        a0 = (k + 0.5) * 2 * math.pi / 14
        for yy in np.arange(0.04 + 0.035 * (k % 3), H - 0.03, 0.13):
            if rng.random() < 0.3:
                continue
            yy += rng.uniform(-0.025, 0.025)
            a1 = a0 + rng.uniform(-0.06, 0.06)
            th = a1
            for _ in range(3):
                th = a1 - float(_plate_swing(0.085 * math.cos(th), yy, 0.085 * math.sin(th)))
            cx, cz = _cv_axis(yy)
            c = np.array([cx + 0.085 * math.cos(th), yy, cz + 0.085 * math.sin(th)])
            rr = rng.uniform(0.009, 0.013)
            holes.append(ellipsoid(c, (rr, rr * rng.uniform(1.2, 1.8), rr)))
    cvv.add_all(holes, "smooth_subtract", 0.004)
    _clip(cvv)
    parts.append(sdf_part(cvv, "Central vein", "Central vein", "#4a63c4", LIVER_D["cv"], "vein", smooth=0.7,
                          rank=1, detail=(0.06, 110.0, 0.5, 0)))

    # sinusoidal endothelial cells: flat cells hovering off the plates across the space of Disse
    gx, gy, gz = np.gradient(vol.d)
    endo = Mesh()
    sel = np.stack(np.nonzero((vol.d > 0.0085) & (vol.d < 0.0105)), -1)
    sel = sel[rng.permutation(len(sel))]
    taken = []
    for ijk in sel:
        c = ijk * vox + lo
        if c[1] < 0.03 or c[1] > H - 0.02 or _hex_clip(c[0], c[2], 0.05) > 0:
            continue
        if taken and np.min(np.linalg.norm(np.array(taken) - c, axis=1)) < 0.05:
            continue
        g = np.array([gx[tuple(ijk)], gy[tuple(ijk)], gz[tuple(ijk)]])
        if np.linalg.norm(g) < 1e-6:
            continue
        n = g / np.linalg.norm(g)
        c = c - n * 0.003
        R_ = frame_from_normal(n)
        endo.extend(ellipsoid_mesh(c, (0.024, 0.0026, 0.015), 6, rotation=R_))
        endo.extend(ellipsoid_mesh(c + n * 0.0022, (0.008, 0.0035, 0.0055), 4, rotation=R_))
        taken.append(c)
        if len(taken) >= 440:
            break
    del gx, gy, gz
    parts.append(mesh_part(endo, "Sinusoidal endothelial cells", "Sinusoids", "#d7aab8", LIVER_D["sinus_endo"],
                           "artery", rank=0.6, detail=(0.05, 160.0, 0.6, 0)))

    # Kupffer cells in the sinusoid lumen, stellate cells in the space of Disse
    def pick(lo_t, hi_t, count, spacing, periportal=0.0, seed=0):
        r = np.random.default_rng(seed)
        m = (tissue.d > lo_t) & (tissue.d < hi_t)
        ii = np.stack(np.nonzero(m), -1)
        p = ii * vox + lo
        fr = _lobule_frame(p[:, 0], p[:, 2])
        keep = ((p[:, 1] > 0.05) & (p[:, 1] < H - 0.03) & (_hex_clip(p[:, 0], p[:, 2], 0.06) < 0)
                & (fr[3] > 0.2) & (fr[3] < 0.9))
        p, rel = p[keep], fr[3][keep]
        w = 1.0 + periportal * rel
        order = r.choice(len(p), size=min(len(p), count * 40), replace=False, p=w / w.sum())
        out = []
        for c in p[order]:
            if all(np.linalg.norm(c - o) > spacing for o in out):
                out.append(c)
            if len(out) >= count:
                break
        return out
    kup = Mesh()
    for c in pick(0.011, 0.014, 60, 0.09, periportal=2.0, seed=3):
        kup.extend(star_cell(c, (0.012, 0.010, 0.012), 5, 0.03, rng, sub_vox=0.003))
    parts.append(mesh_part(kup, "Kupffer cells", "Sinusoids", "#7a5c9e", LIVER_D["kupffer"], "lymph", rank=0.7,
                           detail=(0.08, 160.0, 0.95, 0)))
    ito = Mesh()
    for c in pick(0.003, 0.0055, 32, 0.12, seed=4):
        drops = [sphere(c + rng.normal(scale=0.006, size=3), rng.uniform(0.004, 0.006)) for _ in range(3)]
        ito.extend(star_cell(c, (0.009, 0.007, 0.009), 3, 0.04, rng, extra=drops))
    parts.append(mesh_part(ito, "Stellate (Ito) cells", "Sinusoids", "#efcf5e", LIVER_D["stellate"], "fat",
                           rank=0.7))

    # bile canaliculi: a belt network in the mid-plane of every plate of the central lobule
    parts.append(mesh_part(_canaliculi(tissue, lo, hi), "Bile canaliculi", "Bile flow", "#4f9a4a",
                           LIVER_D["canaliculi"], "biliary", rank=0.5))

    # portal triads
    pv, ha, bd, ly, hering = Mesh(), Mesh(), Mesh(), Mesh(), Mesh()
    ct = Mesh()
    for k in range(6):
        p_pv = _tract_path(k, *TRIAD["pv"])
        _, m = tubule(p_pv, 0.056, 0.064, seed=90 + k, cell=0.045, amp=0.004, aspect=2.2, lobe=(5, 0.09),
                      calibre=0.06, n_theta=60)
        pv.extend(m)
        _, m = tubule(_tract_path(k, *TRIAD["ha"]), 0.010, 0.024, seed=110 + k, cell=0.02, amp=0.003, aspect=0.4,
                      lobe=(6, 0.08), calibre=0.05, n_theta=36)
        ha.extend(m)
        p_bd = _tract_path(k, *TRIAD["bd"])
        bd.extend(_cuboidal_duct(p_bd, 0.011, 0.031, 8, 0.024, seed=130 + k))
        sw = Sweep(_tract_path(k, *TRIAD["lymph"]), 44, 36)
        flat = rsum(1.0, lambda T, S: 0.42 * np.cos(2 * T + 0.6 * np.sin(S * 6)), surf_noise(0.10, 2.0, 3.0, 150 + k))
        ly.extend(sw.shell(rmul(0.020, flat), rmul(0.025, flat)))
        # connective tissue, hollowed around the vessels it carries
        c = LIV_CORNERS[k]
        cv_ = Volume(c - np.array([0.2, 0.0, 0.2]) + np.array([0, lo[1], 0]),
                     c + np.array([0.2, 0.0, 0.2]) + np.array([0, hi[1], 0]), 0.0065)
        cv_.d = chunked(cv_, lambda x, y, z: _tract_d(x, y, z, k) + 0.002)
        for key, rr in (("pv", 0.066), ("ha", 0.026), ("bd", 0.033), ("lymph", 0.027)):
            cv_.tube(_tract_path(k, *TRIAD[key]), rr, "subtract")
        _clip(cv_)
        ct.extend(cv_.mesh(1.0, step=2))
        # canals of Hering: from the limiting plate to the ductule
        u, w = _tract_frame(k)
        for j, yy in enumerate((0.09 + 0.08 * (k % 2), 0.30 - 0.05 * (k % 3))):
            b = p_bd[int(yy / (H + 0.06) * (len(p_bd) - 1))]
            ang = k * math.pi / 3 + math.pi + (0.5 if j else -0.5)
            a = LIV_CORNERS[k] + np.array([math.cos(ang), 0, math.sin(ang)]) * 0.165 + np.array([0, yy + 0.03, 0])
            hering.extend(tube(smooth_path(np.array([a, (a + b) / 2 + np.array([0, 0.01, 0]), b]), 14), 0.0065, 8))
    parts += [
        mesh_part(ct, "Portal tract connective tissue", "Portal triads", "#e8d6c0", LIVER_D["ct"], "fascia",
                  bulk=True, rank=1, label=False, alpha=0.42, detail=(0.12, 55.0, 0.2, 2)),
        mesh_part(pv, "Portal venules", "Portal triads", "#6a4fb5", LIVER_D["pv"], "vein", rank=1.2),
        mesh_part(ha, "Hepatic arterioles", "Portal triads", "#cf3a31", LIVER_D["ha"], "artery", rank=1.2,
                  detail=(0.06, 120.0, 0.6, 2)),
        mesh_part(bd, "Bile ductules", "Portal triads", "#5fae62", LIVER_D["bd"], "biliary", rank=1.2,
                  detail=(0.08, 180.0, 0.95, 0)),
        mesh_part(ly, "Lymphatic vessels", "Portal triads", "#d9e6c8", LIVER_D["lymph"], "lymph", rank=1.2,
                  detail=(0.05, 90.0, 0.3, 0)),
        mesh_part(hering, "Canals of Hering", "Bile flow", "#79bf6c", LIVER_D["hering"], "biliary", rank=1.0),
    ]
    parts += _acinus_overlay(lo, hi)
    return settle(parts, seed=503, amp_xz=0.022, amp_y=0.030, freq=1.4, grain=0.004)


def _tubes(items, segments):
    m = Mesh()
    for path, rr in items:
        m.extend(tube(path, rr, segments))
    return m


def _cuboidal_duct(path, r_in, r_out, n_around, cell_len, seed=0):
    """A duct built of individual cuboidal cells ringed around a lumen."""
    rng = np.random.default_rng(seed)
    path = np.asarray(path, float)
    t, nrm, bi = frames(path)
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    lo, hi = path.min(0) - r_out - 0.01, path.max(0) + r_out + 0.01
    v = Volume(lo, hi, 0.005)
    rc = (r_in + r_out) / 2
    shapes = []
    for ring, s0 in enumerate(np.arange(cell_len / 2, s[-1], cell_len)):
        i = int(np.searchsorted(s, s0))
        i = min(i, len(path) - 1)
        for j in range(n_around):
            a = (j + 0.5 * (ring % 2)) * 2 * math.pi / n_around + rng.uniform(-0.12, 0.12)
            radial = nrm[i] * math.cos(a) + bi[i] * math.sin(a)
            tang = np.cross(t[i], radial)
            rot = np.stack([radial, t[i], tang], axis=1)
            c = path[i] + radial * rc
            shapes.append(ellipsoid(c, ((r_out - r_in) * 0.56, cell_len * 0.56, rc * math.pi / n_around * 1.02),
                                    rot=rot))
    v.add_all(shapes, "smooth", 0.004)
    return v.mesh(0.6)


def _canaliculi(tissue, lo, hi):
    """Tubes along the mid-plane of each hepatic plate of the central lobule, a mesh of belts round the cells."""
    m = Mesh()
    H = LIV_H

    def inside(p):
        idx = np.clip(np.round((p - tissue.lo) / tissue.voxel).astype(int), 0, np.array(tissue.shape) - 1)
        return tissue.d[idx[:, 0], idx[:, 1], idx[:, 2]]
    for n, off, start in PLATE_SETS:
        for k in range(n):
            tk = (k + off) * 2 * math.pi / n
            rs = np.arange(0.11, 0.80, 0.012)
            ys = np.arange(0.035, H - 0.02, 0.012)
            R_, Y_ = np.meshgrid(rs, ys, indexing="ij")
            th = np.full(R_.shape, tk)
            for _ in range(3):
                px, pz = R_ * np.cos(th), R_ * np.sin(th)
                th = tk - _plate_swing(px, Y_, pz) - LIV_PHASE[0] * (2 * math.pi / 14)
            # canaliculi wander a little within the plate rather than running on a ruled grid
            th = th + 0.004 / R_ * np.sin(Y_ * 70.0 + R_ * 23.0 + k)
            Yw = Y_ + 0.005 * np.sin(R_ * 80.0 + k * 1.7)
            P = np.stack([R_ * np.cos(th), Yw, R_ * np.sin(th)], -1)
            flat = P.reshape(-1, 3)
            fr = _lobule_frame(flat[:, 0], flat[:, 2])
            ok = ((inside(flat) < -0.008) & (fr[4] == 0) & (fr[3] > start + 0.04) & (fr[2] < -0.03)
                  & np.all(flat > lo + 0.01, axis=1) & np.all(flat < hi - 0.01, axis=1)).reshape(R_.shape)
            # radial runs every ~0.06 in height joined by staggered cross-links, like bricks: each hepatocyte is
            # belted by canaliculi shared with its neighbours
            rows = list(range(2, len(ys), 5))
            for j in rows:
                _runs(m, P[:, j], ok[:, j])
            for b_, (j0, j1) in enumerate(zip(rows[:-1], rows[1:])):
                for i in range(1 + 2 * (b_ % 2), len(rs), 5):
                    _runs(m, P[i, j0:j1 + 1], ok[i, j0:j1 + 1])
    return m


def _runs(m, pts, ok):
    i = 0
    n = len(pts)
    while i < n:
        if not ok[i]:
            i += 1
            continue
        j = i
        while j < n and ok[j]:
            j += 1
        if j - i >= 3:
            m.extend(tube(pts[i:j:2] if j - i > 6 else pts[i:j], 0.0045, 5))
        i = j


def _acinus_overlay(lo, hi):
    """Translucent zones of one Rappaport acinus: the diamond between the portal tracts at corners 3 and 4, reaching
    out to the central veins on either side of the border joining them (the far one lies beyond the block). Zone 1
    hugs the axis, zone 3 reaches the veins; every zone pinches down to the two portal tracts."""
    a_pt, b_pt = LIV_CORNERS[3][[0, 2]], LIV_CORNERS[4][[0, 2]]
    mid = (a_pt + b_pt) / 2
    half = float(np.linalg.norm(b_pt - a_pt)) / 2
    ax = (b_pt - a_pt) / (2 * half)
    reach = float(np.linalg.norm(mid))              # from the border to the central vein
    v = Volume(lo, hi, 0.011)
    x, y, z = v.axes()
    uu = (x - mid[0]) * ax[0] + (z - mid[1]) * ax[1]
    ww = np.abs((x - mid[0]) * -ax[1] + (z - mid[1]) * ax[0])
    prof = np.clip(1.0 - (np.abs(uu) / half) ** 1.6, 0.0, 1.0)
    yb = np.maximum(0.008 - y, y - (LIV_H - 0.008))
    out = []
    specs = [("Liver acinus – zone 1", "#e0584a", 0.0, 1 / 3), ("Liver acinus – zone 2", "#e5a53c", 1 / 3, 2 / 3),
             ("Liver acinus – zone 3", "#7a68d0", 2 / 3, 1.0)]
    for name, color, f0, f1 in specs:
        d = np.maximum(ww - f1 * reach * prof, np.abs(uu) - half)
        if f0 > 0:
            d = np.maximum(d, f0 * reach * prof - ww + 0.003)
        vv = v.copy(np.broadcast_to(np.maximum(d, yb), v.shape).astype(np.float32).copy())
        _clip(vv, 0.006)
        out.append(sdf_part(vv, name, "Liver acinus (Rappaport)", color, LIVER_D["acinus"], "serosa", smooth=1.0,
                            rank=1.5, alpha=0.24, detail=(0.02, 0.0, 0.0, 0)))
    return out
