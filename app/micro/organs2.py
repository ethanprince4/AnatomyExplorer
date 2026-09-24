"""High-resolution microanatomy models: urinary bladder, cornea, retina, thyroid follicles and tongue papillae."""
import math

import numpy as np
from scipy.spatial import Voronoi, cKDTree

from .cells import frame_from_normal, jittered_bcc, poisson_disk
from .geometry import Mesh, capsule as capsule_mesh, ellipsoid as ellipsoid_mesh, tube
from .gut import _network
from .organic import settle
from .kit import (Volume, add, at, blob_cluster, box_shape, ellipsoid, hlayer, mesh_part, noise2, round_cone,
                  sdf_part, shift,
                  smooth_path, wavy_path)
from .sdf import fbm3

X0, X1, Z0, Z1 = -1.0, 1.0, -0.6, 0.6
XR, ZR = (X0, X1), (Z0, Z1)


class Domes:
    """Cobblestone cell tops: every Voronoi cell of a 2D point set bulges into a dome (umbrella cells, corneal
    surface cells, endothelium, RPE)."""

    def __init__(self, points, height, border=0.004):
        self.tree = cKDTree(np.asarray(points, float))
        self.h, self.border = height, border

    def __call__(self, X, Z):
        X, Z = np.broadcast_arrays(np.asarray(X, float), np.asarray(Z, float))
        d, _ = self.tree.query(np.stack([X.ravel(), Z.ravel()], -1), k=2)
        edge = np.clip((d[:, 1] - d[:, 0]) / 2.0, 0, None)
        prof = np.sqrt(np.clip(edge / (edge + self.border * 4), 0, 1))
        return (self.h * prof).reshape(X.shape)


def _hex_points(spacing, jitter, rng, margin=0.1):
    pts = []
    for j, zz in enumerate(np.arange(Z0 - margin, Z1 + margin, spacing * 0.866)):
        for xx in np.arange(X0 - margin, X1 + margin, spacing):
            pts.append((xx + (spacing / 2 if j % 2 else 0) + rng.uniform(-jitter, jitter), zz))
    return np.array(pts)


# =============================================================================== urinary bladder
BLADDER = {
    "umbrella": "Umbrella (superficial) cells: very large, often binucleate cells whose apical membrane is stiffened "
                "by uroplakin plaques (asymmetric unit membrane). They form the urine-blood barrier and flatten "
                "when the bladder fills, as membrane is added from fusiform vesicles.",
    "intermediate": "Intermediate cells: several layers of polygonal cells that slide past each other as the "
                    "bladder distends, so the epithelium thins from 6-7 cells to 2-3.",
    "basal": "Basal cells: small cuboidal stem cells on the basement membrane that regenerate the urothelium.",
    "lp": "Lamina propria: loose connective tissue with a rich capillary plexus, lymphatics and elastic fibres. "
          "Invasion of the lamina propria (pT1) versus the detrusor muscle (pT2) is the key staging step in bladder "
          "cancer.",
    "mm": "Muscularis mucosae: thin, discontinuous smooth muscle bundles in the lamina propria – easily mistaken for "
          "detrusor muscle on biopsy, which matters for cancer staging.",
    "inner": "Inner longitudinal layer of the detrusor muscle.",
    "middle": "Middle circular layer of the detrusor, thickest at the bladder neck where it contributes to the "
              "internal urethral sphincter in males.",
    "outer": "Outer longitudinal layer of the detrusor. The three layers interlace and are not cleanly separable; "
             "parasympathetic (pelvic splanchnic, S2-S4) M3 stimulation contracts them during voiding.",
    "adventitia": "Adventitia (serosa over the dome): connective tissue binding the bladder to the pelvic walls.",
    "cap": "Subepithelial capillary plexus: bleeds as painless haematuria when the urothelium is breached by tumour "
           "or cyclophosphamide cystitis.",
    "nerve": "Autonomic nerve fibres and stretch afferents that signal bladder fullness via the pelvic nerves.",
    "vessels": "Arterioles and venules of the lamina propria and detrusor.",
}


def _muscle_bundles(y0, y1, axis, spacing, radius, seed, rows=2, voxel=0.0055, waves=2.4):
    """A layer of interlacing smooth-muscle bundles rather than a flat sheet.

    The detrusor is a meshwork - bundles weave between the three named layers - and drawing it as three smooth
    slabs is what makes a bladder wall look like laminated card."""
    rng = np.random.default_rng(seed)
    lo = np.array([X0, y0, Z0])
    hi = np.array([X1, y1, Z1])
    v = Volume(lo - 0.02, hi + 0.02, voxel)
    across = 2 if axis == 0 else 0                       # the axis the bundles are spread along
    a0, a1 = (Z0, Z1) if across == 2 else (X0, X1)
    b0, b1 = (X0 - 0.03, X1 + 0.03) if axis == 0 else (Z0 - 0.03, Z1 + 0.03)
    n = 44
    t = np.linspace(0.0, 1.0, n)
    for r in range(rows):
        y = y0 + (y1 - y0) * (r + 0.5) / rows
        off = spacing * 0.5 * r
        c = a0 + off
        while c < a1 + spacing * 0.5:
            ph = rng.uniform(0, 2 * math.pi)
            main = b0 + (b1 - b0) * t
            side = c + spacing * 0.28 * np.sin(waves * math.pi * t + ph)
            ys = y + (y1 - y0) * 0.20 * np.sin(waves * 0.8 * math.pi * t + ph * 1.3)
            path = np.stack([main, ys, side], -1) if axis == 0 else np.stack([side, ys, main], -1)
            v.tube(path, radius * rng.uniform(0.85, 1.15), "smooth", 0.012)
            c += spacing * rng.uniform(0.9, 1.1)
    v.intersect_box(lo, hi)
    return v


def build_bladder():
    parts = []
    rng = np.random.default_rng(7)
    rugae = add(lambda X, Z: 0.05 * np.sin(np.asarray(X) * 5.2 + 0.4) * np.cos(np.asarray(Z) * 2.3),
                noise2(0.012, 3.0, seed=2))
    y_lp_top = add(0.80, rugae)
    y_basal = shift(y_lp_top, 0.028)
    y_int = add(y_basal, 0.075, noise2(0.004, 9.0, seed=4))
    umb_pts = poisson_disk((X0 - 0.05, Z0 - 0.05), (X1 + 0.05, Z1 + 0.05), 0.085, seed=5)
    y_umb = add(y_int, 0.018, Domes(umb_pts, 0.03, 0.006))

    def wav(b, s):
        return add(b, noise2(0.008, 3.5, seed=s))

    parts.append(hlayer("Adventitia", "Wall layers", "#e5d3b0", 0.0, 0.06, BLADDER["adventitia"], "fascia", XR, ZR,
                        bulk=True, rank=-5, res=120, detail=(0.14, 50.0, 0.15, 0)))
    parts.append(sdf_part(_muscle_bundles(0.062, 0.188, 0, 0.105, 0.040, seed=61),
                          "Outer longitudinal detrusor", "Detrusor muscle", "#c25d51", BLADDER["outer"], "muscle",
                          smooth=0.8, rank=-4, detail=(0.08, 80.0, 0.45, 1)))
    parts.append(sdf_part(_muscle_bundles(0.196, 0.368, 2, 0.115, 0.046, seed=62, rows=3),
                          "Middle circular detrusor", "Detrusor muscle", "#a8463d", BLADDER["middle"], "muscle",
                          smooth=0.8, rank=-3, detail=(0.08, 80.0, 0.45, 3)))
    parts.append(sdf_part(_muscle_bundles(0.376, 0.468, 0, 0.098, 0.034, seed=63),
                          "Inner longitudinal detrusor", "Detrusor muscle", "#bb5448", BLADDER["inner"], "muscle",
                          smooth=0.8, rank=-2, detail=(0.08, 80.0, 0.45, 1)))
    parts.append(hlayer("Lamina propria", "Mucosa", "#f0d2c3", wav(0.475, 13), y_lp_top, BLADDER["lp"], "mucosa", XR,
                        ZR, bulk=True, rank=-1, res=220, detail=(0.12, 90.0, 0.25, 0)))
    parts.append(hlayer("Basal cells", "Urothelium", "#98607f", y_lp_top, y_basal, BLADDER["basal"], "mucosa", XR, ZR,
                        rank=1, res=240, detail=(0.10, 190.0, 0.95, 0)))
    parts.append(hlayer("Intermediate cells", "Urothelium", "#d8b3c5", y_basal, y_int, BLADDER["intermediate"],
                        "mucosa", XR, ZR, rank=2, res=240, detail=(0.10, 120.0, 0.85, 0)))
    parts.append(hlayer("Umbrella cells", "Urothelium", "#f1e1ea", y_int, y_umb, BLADDER["umbrella"], "mucosa", XR,
                        ZR, rank=3, res=320, detail=(0.06, 60.0, 0.7, 0)))
    mm = Volume((X0, 0.55, Z0), (X1, 0.8, Z1), 0.004)
    shapes = []
    for _ in range(26):
        a = np.array([rng.uniform(-0.95, 0.7), 0, rng.uniform(-0.55, 0.5)])
        b = a + np.array([rng.uniform(0.15, 0.35), 0, rng.uniform(-0.12, 0.12)])
        a[1] = at(y_lp_top, a[0], a[2]) - 0.11
        b[1] = at(y_lp_top, b[0], b[2]) - 0.11
        mid = (a + b) / 2 + np.array([0, 0.01, 0])
        shapes += [round_cone(a, mid, 0.008, 0.016), round_cone(mid, b, 0.016, 0.007)]
    mm.add_all(shapes, "union")
    mm.displace(0.002, 40.0, 2, seed=3)
    parts.append(sdf_part(mm, "Muscularis mucosae (discontinuous)", "Mucosa", "#b95a50", BLADDER["mm"], "muscle",
                          rank=-0.5, detail=(0.08, 90.0, 0.45, 1)))
    cap = _network(shift(y_lp_top, -0.022), 0.1, 0.012, 0.0045, seed=19, voxel=0.0035)
    parts.append(sdf_part(cap, "Subepithelial capillary plexus", "Vessels & nerves", "#d0463c", BLADDER["cap"],
                          "artery", smooth=0.6, rank=0))
    art, vein, nerve = Mesh(), Mesh(), Mesh()
    for j, z in enumerate((-0.3, 0.02, 0.35)):
        p = wavy_path((X0 + 0.01, 0.53, z), (X1 - 0.01, 0.55, z + 0.05), 70, 0.025, 1.5, seed=j)
        art.extend(tube(p, 0.018, 18))
        q = p.copy()
        q[:, 2] += 0.07
        vein.extend(tube(q, 0.027, 20))
    nerve.extend(tube(wavy_path((X0 + 0.01, 0.33, 0.3), (X1 - 0.01, 0.34, 0.25), 70, 0.03, 2.0, seed=9), 0.013, 14))
    parts += [mesh_part(art, "Arterioles", "Vessels & nerves", "#cf3a31", BLADDER["vessels"], "artery", rank=-1),
              mesh_part(vein, "Venules", "Vessels & nerves", "#3d5bc2", BLADDER["vessels"], "vein", rank=-1),
              mesh_part(nerve, "Autonomic nerve", "Vessels & nerves", "#f0cf45", BLADDER["nerve"], "nerve", rank=-3)]
    return settle(parts, seed=401, amp_xz=0.030, amp_y=0.065, freq=1.5, grain=0.006)


# =============================================================================== cornea
CORNEA = {
    "tear": "Tear film: outer lipid layer (meibomian glands), aqueous layer (lacrimal gland) and inner mucin layer "
            "(conjunctival goblet cells). Deficiency causes dry eye disease.",
    "superficial": "Superficial squamous cells: 2-3 layers of flattened non-keratinised cells with microvilli that "
                   "hold the tear film. They are continuously shed and replaced every 7-10 days.",
    "wing": "Wing cells: 2-3 layers of polygonal cells between the basal and superficial layers.",
    "basal": "Basal columnar cells: the only mitotic layer of the corneal epithelium, fed by limbal stem cells at "
             "the corneoscleral junction. Limbal stem cell deficiency (chemical burns) lets conjunctiva grow over "
             "the cornea.",
    "bowman": "Bowman layer: acellular condensed collagen that does not regenerate – injuries through it heal with a "
              "scar. Removed during PRK laser surgery.",
    "stroma": "Stroma: about 90% of corneal thickness, ~200 lamellae of uniformly thin collagen fibrils (type I) "
              "spaced precisely by proteoglycans; this regular spacing makes the cornea transparent. Oedema "
              "disrupts the spacing and clouds the cornea. LASIK reshapes the anterior stroma. Keratoconus is "
              "progressive stromal thinning and ectasia.",
    "keratocytes": "Keratocytes: flattened fibroblasts between the lamellae that maintain the matrix and become "
                   "myofibroblasts (causing haze) after injury.",
    "descemet": "Descemet membrane: thick basement membrane of the endothelium that thickens throughout life. "
                "Copper deposits at its periphery form Kayser-Fleischer rings in Wilson disease.",
    "endothelium": "Endothelium: a single layer of hexagonal cells that pump fluid out of the stroma to keep it "
                   "dehydrated. The cells do not divide in humans; loss with age, surgery or Fuchs dystrophy leads "
                   "to corneal oedema and needs endothelial keratoplasty (DMEK).",
    "nerves": "Corneal nerves: branches of the ophthalmic nerve (V1, via long ciliary nerves) run in the anterior "
              "stroma, pierce Bowman layer and form a subbasal plexus – the cornea is the most densely innervated "
              "tissue in the body, the basis of the corneal reflex.",
}


def build_cornea():
    parts = []
    rng = np.random.default_rng(3)
    hexes = _hex_points(0.07, 0.006, rng)
    endo_bottom = lambda X, Z: -Domes(hexes, 0.012, 0.004)(X, Z)
    parts.append(hlayer("Endothelium", "Posterior cornea", "#9fc6d9", endo_bottom, 0.028, CORNEA["endothelium"],
                        "mucosa", XR, ZR, rank=-4, res=320, detail=(0.06, 150.0, 0.9, 0)))
    parts.append(hlayer("Descemet membrane", "Posterior cornea", "#e8e3c7", 0.03, 0.062, CORNEA["descemet"],
                        "cartilage", XR, ZR, rank=-3, res=140, alpha=0.80, detail=(0.04, 0.0, 0.0, 0)))
    parts.append(hlayer("Stroma", "Stroma", "#dde7ef", 0.064, 0.82, CORNEA["stroma"], "cartilage", XR, ZR, bulk=True,
                        rank=-2, res=140, alpha=0.42, detail=(0.05, 40.0, 0.12, 1)))
    lam = Mesh()
    levels = np.linspace(0.1, 0.78, 16)
    for i, yl in enumerate(levels):
        undul = noise2(0.006, 2.5, seed=40 + i)
        lam.extend(hlayer("lamella", "Stroma", "#c5d6e6", add(yl, undul), add(yl + 0.006, undul), "", "tendon",
                          (X0 + 0.004, X1 - 0.004), (Z0 + 0.004, Z1 - 0.004), res=90).mesh)
    parts.append(mesh_part(lam, "Collagen lamellae", "Stroma", "#c5d6e6", CORNEA["stroma"], "tendon", rank=-2,
                           detail=(0.04, 0.0, 0.0, 0)))
    kc = Volume((X0, 0.08, Z0), (X1, 0.8, Z1), 0.003)
    for i, yl in enumerate(levels[:-1]):
        ymid = (yl + levels[i + 1]) / 2 + 0.003
        for (px, pz) in poisson_disk((X0 + 0.05, Z0 + 0.05), (X1 - 0.05, Z1 - 0.05), 0.2, seed=60 + i)[:22]:
            shapes = [ellipsoid((px, ymid, pz), (0.022, 0.0035, 0.016))]
            for k in range(6):
                a = k * math.pi / 3 + rng.uniform(-0.3, 0.3)
                end = np.array([px + 0.06 * math.cos(a), ymid + rng.uniform(-0.002, 0.002), pz + 0.05 * math.sin(a)])
                shapes.append(round_cone((px, ymid, pz), end, 0.0035, 0.0012))
            kc.add_all(shapes, "smooth", 0.004)
    parts.append(sdf_part(kc, "Keratocytes", "Stroma", "#7f9cc4", CORNEA["keratocytes"], "gland", smooth=0.5,
                          rank=-1.5, detail=(0.04, 0.0, 0.0, 0)))
    parts.append(hlayer("Bowman layer", "Anterior cornea", "#efe8d2", 0.822, 0.85, CORNEA["bowman"], "cartilage", XR,
                        ZR, rank=1, res=140, alpha=0.72, detail=(0.04, 0.0, 0.0, 0)))
    parts.append(hlayer("Basal columnar cells", "Epithelium", "#b58fb0", 0.852, 0.892, CORNEA["basal"], "mucosa", XR,
                        ZR, rank=2, res=80, detail=(0.10, 210.0, 0.95, 2)))
    wing_top = add(0.946, noise2(0.002, 8.0, seed=5))
    parts.append(hlayer("Wing cells", "Epithelium", "#dcc2d6", 0.894, wing_top, CORNEA["wing"], "mucosa", XR, ZR,
                        rank=3, res=160, alpha=0.80, detail=(0.10, 150.0, 0.85, 0)))
    sq_pts = poisson_disk((X0 - 0.05, Z0 - 0.05), (X1 + 0.05, Z1 + 0.05), 0.075, seed=8)
    y_sq = add(0.966, Domes(sq_pts, 0.006, 0.003))
    parts.append(hlayer("Superficial squamous cells", "Epithelium", "#f1e3ec", shift(wing_top, 0.002), y_sq,
                        CORNEA["superficial"], "mucosa", XR, ZR, rank=4, res=320, detail=(0.06, 110.0, 0.6, 0)))
    parts.append(hlayer("Tear film", "Epithelium", "#b9e3f2", shift(y_sq, 0.004), 0.99, CORNEA["tear"], "csf", XR, ZR,
                        rank=5, res=160, alpha=0.3))
    nv = Volume((X0, 0.5, Z0), (X1, 0.9, Z1), 0.003)
    for i, z in enumerate((-0.35, 0.05, 0.42)):
        trunk = smooth_path(np.array([(X0 - 0.02, 0.6, z), (-0.5, 0.66, z + 0.04), (-0.05, 0.74, z - 0.03),
                                      (0.2, 0.82, z), (0.28, 0.86, z + 0.02)]), 60)
        nv.tube(trunk, np.linspace(0.013, 0.008, len(trunk)))
        for k in range(5):
            start = np.array([0.28, 0.86, z + 0.02])
            a = (k - 2) * 0.5 + rng.uniform(-0.1, 0.1)
            end = start + np.array([0.7 * math.cos(a), 0.0, 0.3 * math.sin(a)])
            path = smooth_path(np.array([start, start + (end - start) * 0.5, end]), 30)
            path[:, 1] = np.clip(path[:, 1], 0.855, 0.87)
            nv.tube(path, np.linspace(0.006, 0.004, len(path)))
    parts.append(sdf_part(nv, "Corneal nerves & subbasal plexus", "Stroma", "#f0cf45", CORNEA["nerves"], "nerve",
                          smooth=0.6, rank=0))
    return settle(parts, seed=402, amp_xz=0.016, amp_y=0.026, freq=1.4, grain=0.0030, micro=0.0024, micro_freq=26.0,
                  dome=(0.34, 1.15, 0.82))


# =============================================================================== retina
RETINA = {
    "sclera": "Sclera: dense irregular collagen coat continuous with the cornea.",
    "choroid": "Choroid: highly vascular pigmented layer with the largest blood flow per gram in the body; the "
               "choriocapillaris feeds the outer retina (photoreceptors). Choroidal neovascularisation causes wet "
               "age-related macular degeneration.",
    "choroid_vessels": "Choroidal arteries and veins (from the short posterior ciliary arteries; drained by vortex "
                       "veins).",
    "cc": "Choriocapillaris: a sheet of wide, fenestrated capillaries directly beneath Bruch membrane.",
    "bruch": "Bruch membrane: five-layered membrane between choriocapillaris and RPE. Drusen deposits here are the "
             "hallmark of age-related macular degeneration.",
    "rpe": "Retinal pigment epithelium: melanin-filled cuboidal cells that absorb stray light, phagocytose shed "
           "outer-segment discs, recycle retinal (vitamin A) and form the outer blood-retina barrier. Retinal "
           "detachment separates the neural retina from the RPE along this plane.",
    "rods": "Rods: ~120 million, long cylindrical outer segments packed with rhodopsin discs; very sensitive, used "
            "in dim light, absent from the fovea. Lost first in retinitis pigmentosa (night blindness, tunnel "
            "vision).",
    "cones": "Cones: ~6 million, shorter conical outer segments with S, M or L opsins for colour and acuity; "
             "concentrated at the fovea.",
    "olm": "Outer limiting membrane: junctions between Müller cells and photoreceptor inner segments (not a true "
           "membrane).",
    "onl": "Outer nuclear layer: photoreceptor cell bodies and nuclei.",
    "opl": "Outer plexiform layer: synapses between photoreceptors, bipolar and horizontal cells. Hard exudates "
           "and haemorrhages collect here in diabetic retinopathy.",
    "inl": "Inner nuclear layer: nuclei of bipolar, horizontal, amacrine and Müller cells. Supplied by the central "
           "retinal artery, like all the inner layers.",
    "ipl": "Inner plexiform layer: synapses of bipolar and amacrine cells onto ganglion cells.",
    "gcl": "Ganglion cell layer: retinal ganglion cells whose axons form the optic nerve. Their loss causes the "
           "progressive visual field defects of glaucoma.",
    "nfl": "Nerve fibre layer: unmyelinated ganglion cell axons converging on the optic disc. Infarcts here appear "
           "as cotton-wool spots.",
    "ilm": "Inner limiting membrane: basement membrane of the Müller cell end-feet, facing the vitreous.",
    "vessels": "Branches of the central retinal artery and vein running in the nerve fibre layer. Occlusion of the "
               "artery whitens the inner retina with a cherry-red spot at the fovea.",
    "muller": "Müller glia: span the whole retina from inner to outer limiting membranes, providing structural and "
              "metabolic support and recycling glutamate.",
    "bipolar": "Bipolar cells: relay signals from photoreceptors to ganglion cells.",
    "ganglion": "Ganglion cell bodies with their axons turning into the nerve fibre layer.",
    "vitreous": "Vitreous body: transparent gel of collagen and hyaluronan. Posterior vitreous detachment can tear "
                "the retina, causing floaters and flashes.",
}


def build_retina():
    parts = []
    rng = np.random.default_rng(11)

    def nz(amp, freq, seed):
        return noise2(amp, freq, seed=seed)

    parts.append(hlayer("Sclera", "Outer coats", "#efe9dc", 0.0, add(0.08, nz(0.004, 3.0, 1)), RETINA["sclera"],
                        "ligament", XR, ZR, bulk=True, rank=-8, res=100, detail=(0.1, 40.0, 0.12, 1)))
    parts.append(hlayer("Choroid stroma", "Outer coats", "#6e2f3a", add(0.083, nz(0.004, 3.0, 1)), 0.19,
                        RETINA["choroid"], "organ", XR, ZR, bulk=True, rank=-7, res=100, detail=(0.12, 90.0, 0.4, 0)))
    cv = Mesh()
    for i, z in enumerate(np.linspace(-0.5, 0.5, 7)):
        cv.extend(tube(wavy_path((X0 + 0.01, 0.12 + 0.02 * (i % 2), z), (X1 - 0.01, 0.13, z + 0.04), 60, 0.03, 1.2,
                                 seed=i), 0.028 + 0.006 * (i % 2), 20))
    parts.append(mesh_part(cv, "Choroidal vessels", "Outer coats", "#b53a36", RETINA["choroid_vessels"], "artery",
                           rank=-7))
    cc = _network(lambda X, Z: 0.185 + 0 * np.asarray(X), 0.07, 0.016, 0.011, seed=21, voxel=0.0035)
    parts.append(sdf_part(cc, "Choriocapillaris", "Outer coats", "#c9443e", RETINA["cc"], "artery", smooth=0.7,
                          rank=-6.5))
    parts.append(hlayer("Bruch membrane", "Outer coats", "#e8dcc0", 0.2, 0.21, RETINA["bruch"], "cartilage", XR, ZR,
                        rank=-6, res=60, detail=(0.03, 0.0, 0.0, 0)))
    parts.append(hlayer("Retinal pigment epithelium", "Photoreceptors & RPE", "#3b2a26", 0.212,
                        add(0.244, Domes(_hex_points(0.05, 0.0, rng, 0.05), 0.008, 0.003)), RETINA["rpe"], "mucosa",
                        XR, ZR, rank=-5, res=300, detail=(0.08, 0.0, 0.0, 0)))
    rods_os, rods_is, cones = Mesh(), Mesh(), Mesh()
    for x, z in poisson_disk((X0 + 0.01, Z0 + 0.01), (X1 - 0.01, Z1 - 0.01), 0.021, seed=4):
        if rng.random() < 0.1:
            path = np.array([(x, 0.3, z), (x, 0.35, z), (x, 0.395, z), (x, 0.44, z)])
            cones.extend(tube(path, np.array([0.004, 0.012, 0.016, 0.013]), 12))
            cones.extend(capsule_mesh((x, 0.29, z), (x, 0.3, z), 0.004, 8, 2))
        else:
            rods_os.extend(capsule_mesh((x, 0.245, z), (x, 0.36, z), 0.0055, 8, 3))
            rods_is.extend(tube(np.array([(x, 0.36, z), (x, 0.40, z), (x, 0.44, z)]),
                                np.array([0.0055, 0.0068, 0.005]), 8))
    parts += [mesh_part(rods_os, "Rod outer segments", "Photoreceptors & RPE", "#d7c7a4", RETINA["rods"], "nerve",
                        rank=-4, detail=(0.04, 400.0, 0.0, 2)),
              mesh_part(rods_is, "Rod inner segments", "Photoreceptors & RPE", "#e7b9a4", RETINA["rods"], "nerve",
                        rank=-4, label=False),
              mesh_part(cones, "Cones", "Photoreceptors & RPE", "#9fc3e0", RETINA["cones"], "nerve", rank=-4,
                        detail=(0.04, 300.0, 0.0, 2))]
    parts.append(hlayer("Outer limiting membrane", "Neural retina", "#e9e1d0", 0.44, 0.447, RETINA["olm"],
                        "cartilage", XR, ZR, rank=-3, res=60, detail=(0.02, 0.0, 0.0, 0)))
    b1, b2, b3 = add(0.57, nz(0.004, 4, 3)), add(0.61, nz(0.004, 4, 5)), add(0.71, nz(0.004, 4, 7))
    parts.append(hlayer("Outer nuclear layer", "Neural retina", "#7b5ea8", 0.45, b1, RETINA["onl"], "nucleus", XR, ZR,
                        rank=-2.5, res=120, detail=(0.06, 260.0, 1.0, 0)))
    parts.append(hlayer("Outer plexiform layer", "Neural retina", "#e4c9d6", shift(b1, 0.003), b2, RETINA["opl"],
                        "brain", XR, ZR, rank=-2, res=120, detail=(0.08, 90.0, 0.08, 0)))
    parts.append(hlayer("Inner nuclear layer", "Neural retina", "#6f5aa3", shift(b2, 0.003), b3, RETINA["inl"],
                        "nucleus", XR, ZR, rank=-1.5, res=120, detail=(0.06, 220.0, 0.95, 0)))
    parts.append(hlayer("Inner plexiform layer", "Neural retina", "#e7d0de", shift(b3, 0.003), 0.79, RETINA["ipl"],
                        "brain", XR, ZR, rank=-1, res=120, detail=(0.08, 90.0, 0.06, 0)))
    parts.append(hlayer("Ganglion cell layer", "Neural retina", "#c9b9dc", 0.793, 0.84, RETINA["gcl"], "brain", XR, ZR,
                        rank=-0.5, res=60, detail=(0.08, 90.0, 0.2, 0)))
    gc = Volume((X0, 0.78, Z0), (X1, 0.9, Z1), 0.003)
    for i, (px, pz) in enumerate(poisson_disk((X0 + 0.04, Z0 + 0.04), (X1 - 0.04, Z1 - 0.04), 0.13, seed=6)):
        c = np.array([px, 0.815, pz])
        bend = c + np.array([0.03, 0.035, 0.0])
        shapes = [ellipsoid(c, (0.024, 0.017, 0.022)), round_cone(c, bend, 0.006, 0.004),
                  round_cone(bend, c + np.array([0.12, 0.05, 0.02]), 0.004, 0.0035)]
        for k in range(3):
            a = k * 2.1 + i
            shapes.append(round_cone(c, c + np.array([0.04 * math.cos(a), -0.03, 0.04 * math.sin(a)]), 0.005, 0.002))
        gc.add_all(shapes, "smooth", 0.006)
    parts.append(sdf_part(gc, "Ganglion cells", "Neural retina", "#8e62b5", RETINA["ganglion"], "nucleus", smooth=0.6,
                          rank=-0.5, detail=(0.05, 60.0, 0.9, 0)))
    bip = Volume((X0, 0.56, Z0), (X1, 0.8, Z1), 0.003)
    for i, (px, pz) in enumerate(poisson_disk((X0 + 0.03, Z0 + 0.03), (X1 - 0.03, Z1 - 0.03), 0.09, seed=8)):
        c = np.array([px, 0.66, pz])
        shapes = [ellipsoid(c, (0.011, 0.02, 0.011)),
                  round_cone(c, c + np.array([rng.uniform(-0.02, 0.02), 0.1, rng.uniform(-0.02, 0.02)]), 0.004, 0.002)]
        for k in range(3):
            a = k * 2.1 + i
            shapes.append(round_cone(c, c + np.array([0.025 * math.cos(a), -0.075, 0.025 * math.sin(a)]), 0.004,
                                     0.0015))
        bip.add_all(shapes, "smooth", 0.004)
    parts.append(sdf_part(bip, "Bipolar cells", "Neural retina", "#5a4b91", RETINA["bipolar"], "nucleus", smooth=0.5,
                          rank=-1.5, detail=(0.05, 60.0, 0.9, 0)))
    nfl_top = add(0.9, nz(0.004, 3, 9))
    parts.append(hlayer("Nerve fibre layer", "Neural retina", "#f2e6c8", 0.843, nfl_top, RETINA["nfl"], "white_matter",
                        XR, ZR, rank=0, res=100, detail=(0.06, 60.0, 0.1, 1)))
    parts.append(hlayer("Inner limiting membrane", "Neural retina", "#dfe7e9", shift(nfl_top, 0.002),
                        shift(nfl_top, 0.01), RETINA["ilm"], "cartilage", XR, ZR, rank=0.5, res=100,
                        detail=(0.02, 0.0, 0.0, 0)))
    mu = Volume((X0, 0.43, Z0), (X1, 0.92, Z1), 0.0032)
    for i, (px, pz) in enumerate(poisson_disk((X0 + 0.05, Z0 + 0.05), (X1 - 0.05, Z1 - 0.05), 0.16, seed=10)):
        path = np.array([(px, 0.445, pz), (px + 0.004, 0.6, pz), (px - 0.004, 0.75, pz + 0.004), (px, 0.88, pz)])
        shapes = [round_cone(path[k], path[k + 1], 0.005, 0.005) for k in range(3)]
        shapes.append(round_cone(path[-1], (px, 0.893, pz), 0.006, 0.013))
        shapes.append(ellipsoid((px, 0.66, pz), (0.01, 0.022, 0.01)))
        mu.add_all(shapes, "smooth", 0.004)
    parts.append(sdf_part(mu, "Müller glia", "Neural retina", "#9fd1b8", RETINA["muller"], "nerve", smooth=0.5,
                          rank=-1))
    ra = tube(wavy_path((X0 + 0.01, 0.875, 0.2), (X1 - 0.01, 0.875, 0.26), 80, 0.06, 1.0, seed=3), 0.02, 18)
    rv = tube(wavy_path((X0 + 0.01, 0.872, -0.22), (X1 - 0.01, 0.872, -0.16), 80, 0.06, 1.0, seed=5), 0.026, 18)
    parts.append(mesh_part(ra, "Retinal arteriole", "Neural retina", "#d33a31", RETINA["vessels"], "artery", rank=0))
    parts.append(mesh_part(rv, "Retinal venule", "Neural retina", "#7a2f6a", RETINA["vessels"], "vein", rank=0))
    parts.append(hlayer("Vitreous body", "Vitreous", "#d6eef5", shift(nfl_top, 0.013), 1.02, RETINA["vitreous"], "csf",
                        XR, ZR, rank=1, res=40, alpha=0.12))
    return settle(parts, seed=403, amp_xz=0.018, amp_y=0.030, freq=1.5, grain=0.0035, micro=0.0026, micro_freq=26.0,
                  dome=(-0.30, 1.15, 0.82))


# =============================================================================== thyroid
THYROID = {
    "follicular": "Follicular cells: simple epithelium whose height reflects activity – cuboidal when resting, "
                  "columnar when stimulated by TSH (Graves disease), flattened when inactive. They take up iodide "
                  "(NIS symporter), iodinate thyroglobulin at the apical surface (thyroid peroxidase) and later "
                  "endocytose colloid to release T4 and T3.",
    "colloid": "Colloid: stored thyroglobulin, enough hormone for 2-3 months. Scalloped edges (resorption vacuoles) "
               "indicate active hormone release.",
    "c_cells": "Parafollicular C cells: pale neuroendocrine cells between follicles and the follicular epithelium "
               "that secrete calcitonin. They derive from the ultimobranchial body and give rise to medullary "
               "thyroid carcinoma (MEN2, RET mutations; calcitonin as tumour marker).",
    "caps": "Fenestrated capillary network wrapping each follicle, receiving secreted T3/T4 – the thyroid has one of "
            "the highest blood flows per gram of any organ.",
    "stroma": "Interfollicular connective tissue carrying capillaries, lymphatics and sympathetic nerves.",
    "capsule": "Capsule and septa: connective tissue that divides the gland into lobules; lies inside the pretracheal "
               "fascia, which is why the thyroid moves with swallowing.",
}


def build_thyroid():
    parts = []
    rng = np.random.default_rng(21)
    lo, hi = np.array([X0, 0.0, Z0]), np.array([X1, 0.86, Z1])
    vox = 0.0085
    fol = Volume(lo, hi, vox)
    x, y, z = fol.axes()
    centres = jittered_bcc(lo - 0.1, hi + 0.1, 0.3, 0.25, seed=5)
    grid = np.stack(np.broadcast_arrays(x, y, z), -1).reshape(-1, 3)
    d, idx = cKDTree(centres).query(grid, k=2, workers=-1)
    edge = ((d[:, 1] - d[:, 0]) / 2).reshape(fol.shape).astype(np.float32)
    owner = idx[:, 0].reshape(fol.shape)
    size = rng.uniform(0.0, 0.035, len(centres)).astype(np.float32)
    fol.d = ((0.022 + size[owner]) - edge).astype(np.float32)            # negative inside a follicle
    fol.displace(0.004, 9.0, 2, seed=3)
    epi_t = rng.uniform(0.020, 0.040, len(centres)).astype(np.float32)[owner]
    colloid = fol.copy(fol.d + epi_t)                 # built before the block is trimmed, so cut follicles show
    colloid.intersect_box(lo + 0.01, hi - 0.01)       # a ring of epithelium round a disc of colloid
    fol.intersect_box(lo + 0.01, hi - 0.01)
    vac = np.full(colloid.shape, 1e3, np.float32)
    for c in centres[rng.choice(len(centres), len(centres) // 3, replace=False)]:
        for k in range(6):
            dv = rng.normal(size=3)
            dv /= np.linalg.norm(dv)
            p = c + dv * 0.1
            r = colloid.region(p - 0.05, p + 0.05)
            if r is None:
                continue
            sl, (xx, yy, zz) = r
            vac[sl] = np.minimum(vac[sl], np.sqrt((xx - p[0]) ** 2 + (yy - p[1]) ** 2 + (zz - p[2]) ** 2) - 0.03)
    colloid.d = np.maximum(colloid.d, -vac + 0.004)
    # the epithelium is a rim of cuboidal cells around the colloid, not a solid ball: cut follicles then read the
    # way they do down a microscope - an eosinophilic disc of colloid inside a thin ring of cells
    epi = fol.copy(np.maximum(fol.d, -(colloid.d - 0.002)))
    parts.append(sdf_part(epi, "Follicular epithelium", "Follicles", "#b9789b", THYROID["follicular"], "gland",
                          smooth=0.8, rank=0, detail=(0.08, 150.0, 0.95, 0)))
    parts.append(sdf_part(colloid, "Colloid", "Follicles", "#e8b489", THYROID["colloid"], "mucosa", smooth=0.9,
                          rank=0, detail=(0.05, 0.0, 0.0, 0)))
    vor = Voronoi(centres)
    inside = lambda p: bool(np.all(p > lo + 0.03) and np.all(p < hi - 0.03))
    ccv = Volume(lo, hi, vox)
    c_pts = []
    for q in vor.vertices[::3]:
        if inside(q):
            for k in range(3):
                c_pts.append(q + rng.normal(scale=0.013, size=3))
    for q in c_pts:
        ccv.add(ellipsoid(q, (0.016, 0.014, 0.016)), "smooth", 0.006)
    parts.append(sdf_part(ccv, "Parafollicular C cells", "Follicles", "#9fd0e8", THYROID["c_cells"], "gland",
                          smooth=0.7, rank=0.5, detail=(0.05, 60.0, 0.9, 0)))
    capv = Volume(lo, hi, vox)
    for ridge in vor.ridge_vertices:
        if -1 in ridge:
            continue
        verts = vor.vertices[ridge]
        for i in range(len(verts)):
            a2, b2 = verts[i], verts[(i + 1) % len(verts)]
            if inside(a2) and inside(b2) and np.linalg.norm(a2 - b2) < 0.3:
                capv.tube(smooth_path(np.array([a2, (a2 + b2) / 2 + rng.normal(scale=0.010, size=3), b2]), 8),
                          rng.uniform(0.007, 0.011), "union")
    parts.append(sdf_part(capv, "Perifollicular capillaries", "Stroma & capsule", "#d0463c", THYROID["caps"],
                          "artery", smooth=0.6, rank=0))
    # the stroma is what is left of the block once the follicles are taken out of it, so every follicle shows on
    # every free surface and in every cut instead of being buried in a solid slab
    stroma = Volume(lo, hi, vox)
    sx, sy, sz = stroma.axes()
    box_d, _, _ = box_shape((lo + hi) / 2, (hi - lo) / 2 - 0.008)
    stroma.d = np.maximum(box_d(sx, sy, sz), -(fol.d - 0.007)).astype(np.float32)
    np.maximum(stroma.d, -(capv.d - 0.003), out=stroma.d)
    np.maximum(stroma.d, -(ccv.d - 0.003), out=stroma.d)
    parts.append(sdf_part(stroma, "Interfollicular connective tissue", "Stroma & capsule", "#efdcca",
                          THYROID["stroma"], "fascia", smooth=0.7, bulk=True, rank=-1, detail=(0.12, 60.0, 0.2, 0)))
    parts.append(hlayer("Capsule", "Stroma & capsule", "#e3cfa8", add(0.860, noise2(0.005, 7, seed=12)),
                        add(0.888, noise2(0.006, 4, seed=2)), THYROID["capsule"], "ligament", XR, ZR, rank=1,
                        res=160, detail=(0.12, 55.0, 0.15, 1)))
    art = tube(smooth_path(np.array([(X0 + 0.01, 0.885, -0.2), (-0.3, 0.878, 0.0), (0.3, 0.888, 0.1),
                                     (X1 - 0.01, 0.882, 0.3)]), 60), 0.020, 18)
    parts.append(mesh_part(art, "Capsular artery", "Stroma & capsule", "#cf3a31", THYROID["caps"], "artery", rank=1))
    return settle(parts, seed=404, amp_xz=0.028, amp_y=0.055, freq=1.6, grain=0.005)


# =============================================================================== tongue
TONGUE = {
    "filiform": "Filiform papillae: the most numerous papillae, slender keratinised cones that give the tongue its "
                "rough texture; they have NO taste buds. Overgrowth forms 'hairy tongue'; loss in iron, B12 or "
                "folate deficiency gives a smooth atrophic glossitis.",
    "fungiform": "Fungiform papillae: mushroom-shaped, scattered mainly on the tip and sides, red because their "
                 "thin epithelium shows the vascular core; taste buds on the upper surface are supplied by the "
                 "chorda tympani (facial nerve).",
    "vallate": "Circumvallate papilla: 8-12 large papillae in a V in front of the sulcus terminalis, each sunk in a "
               "circular trench. Hundreds of taste buds line its walls; supplied by the glossopharyngeal nerve.",
    "taste": "Taste buds: barrel-shaped clusters of 50-100 gustatory, supporting and basal cells opening via a taste "
             "pore. Type II cells detect sweet, bitter and umami; type III cells detect sour. Renewed every ~10 days.",
    "ebner": "Von Ebner glands: serous glands in the muscle beneath the vallate papillae that flush the trench so "
             "new tastants can reach the taste buds, and secrete lingual lipase.",
    "ebner_ducts": "Ducts of von Ebner glands opening into the base of the trench.",
    "epi": "Stratified squamous epithelium, partly keratinised on the dorsum, non-keratinised on the underside.",
    "lp": "Lamina propria forming secondary connective tissue papillae under the epithelium; there is no submucosa "
          "on the dorsum, so the mucosa is bound directly to the muscle.",
    "muscle": "Intrinsic skeletal muscle in three planes (longitudinal, transverse, vertical) interlaced with fat and "
              "glands, allowing the precise shape changes of speech and swallowing. Supplied by the hypoglossal "
              "nerve.",
    "long": "Longitudinal intrinsic fibres (superior and inferior longitudinal muscles) – shorten and curl the tongue.",
    "trans": "Transverse intrinsic fibres – narrow and elongate the tongue.",
    "vert": "Vertical intrinsic fibres – flatten and broaden the tongue.",
    "nerve": "Glossopharyngeal nerve branches carrying taste from the vallate papillae and general sensation from "
             "the posterior third of the tongue.",
    "vessels": "Branches of the lingual artery.",
}


def build_tongue():
    parts = []
    rng = np.random.default_rng(5)
    vc = np.array([-0.35, 0.0, 0.0])
    R_v, W = 0.23, 0.07
    fung = [(0.0, 0.32), (-0.78, 0.0), (0.55, -0.25), (0.6, 0.3)]
    lo, hi = np.array([X0, 0.42, Z0]), np.array([X1, 1.02, Z1])
    epi = Volume(lo, hi, 0.0045)
    x, y, z = epi.axes()
    rr = np.sqrt((x - vc[0]) ** 2 + (z - vc[2]) ** 2)
    base = 0.8 + 0.006 * fbm3(x * 5, np.float32(0.0), z * 5, 1.0, 3, 2)
    epi.d = np.broadcast_to((y - base).astype(np.float32), epi.shape).copy()
    # circular trench around the vallate papilla, then the papilla itself rising in its middle
    trench = np.broadcast_to(np.maximum(np.abs(rr - (R_v + W / 2)) - W / 2, 0.58 - y).astype(np.float32), epi.shape)
    epi.apply(trench, (slice(None),) * 3, "smooth_subtract", 0.02)
    papilla = (lambda X, Y, Z: np.maximum(np.sqrt((X - vc[0]) ** 2 + (Z - vc[2]) ** 2) - (R_v - 0.01),
                                          np.abs(Y - 0.72) - 0.12),
               vc + np.array([-R_v, 0.58, -R_v]), vc + np.array([R_v, 0.86, R_v]))
    epi.add(papilla, "smooth", 0.015)
    for fx, fz in fung:
        epi.add(round_cone((fx, 0.78, fz), (fx, 0.86, fz), 0.04, 0.05), "smooth", 0.02)
        epi.add(ellipsoid((fx, 0.87, fz), (0.075, 0.035, 0.075)), "smooth", 0.015)
    fil_shapes = []
    for px, pz in poisson_disk((X0 + 0.02, Z0 + 0.02), (X1 - 0.02, Z1 - 0.02), 0.052, seed=6):
        if math.hypot(px - vc[0], pz - vc[2]) < R_v + W + 0.05 or any(math.hypot(px - fx, pz - fz) < 0.12
                                                                     for fx, fz in fung):
            continue
        # filiform papillae are keratinised cones that curve backwards - it is the reason a tongue feels rough
        # one way and smooth the other
        lean = np.array([0.085 + rng.uniform(-0.02, 0.02), 0.0, rng.uniform(-0.022, 0.022)])
        h = 0.105 + rng.uniform(-0.015, 0.020)
        b0 = np.array([px, 0.785, pz])
        m1 = b0 + np.array([0.0, h * 0.42, 0.0]) + lean * 0.18
        m2 = b0 + np.array([0.0, h * 0.76, 0.0]) + lean * 0.58
        t = b0 + np.array([0.0, h, 0.0]) + lean
        fil_shapes += [round_cone(b0, m1, 0.028, 0.018), round_cone(m1, m2, 0.018, 0.011),
                       round_cone(m2, t, 0.011, 0.005)]
    epi.add_all(fil_shapes, "smooth", 0.012)
    epi.intersect_box(lo + 0.005, hi - 0.005)
    floor = (0.45 - y).astype(np.float32)
    lp = epi.copy(np.maximum(epi.d + 0.075, floor))
    epi.d = np.maximum(epi.d, floor)
    parts.append(sdf_part(epi, "Stratified squamous epithelium & papillae", "Mucosa", "#e9c0c2",
                          TONGUE["epi"] + " " + TONGUE["filiform"] + " " + TONGUE["vallate"] + " " +
                          TONGUE["fungiform"], "mucosa", smooth=0.8, rank=1, detail=(0.08, 140.0, 0.8, 0)))
    parts.append(sdf_part(lp, "Lamina propria", "Mucosa", "#efb6aa", TONGUE["lp"], "mucosa", smooth=0.8, rank=0.5,
                          bulk=True, step=2, detail=(0.12, 100.0, 0.3, 0)))
    tb = Mesh()
    for a in np.linspace(0, 2 * math.pi, 26, endpoint=False):
        n = np.array([math.cos(a), 0.0, math.sin(a)])
        for yy in (0.66, 0.73, 0.8):
            p = vc + np.array([(R_v + 0.005) * math.cos(a), yy, (R_v + 0.005) * math.sin(a)])
            tb.extend(ellipsoid_mesh(p - n * 0.02, (0.014, 0.024, 0.014), 12, rotation=frame_from_normal(n)))
            q = vc + np.array([(R_v + W - 0.005) * math.cos(a + 0.12), yy, (R_v + W - 0.005) * math.sin(a + 0.12)])
            tb.extend(ellipsoid_mesh(q + n * 0.02, (0.014, 0.024, 0.014), 12, rotation=frame_from_normal(-n)))
    for fx, fz in fung:
        for k in range(5):
            a = k * 2 * math.pi / 5
            tb.extend(ellipsoid_mesh((fx + 0.035 * math.cos(a), 0.885, fz + 0.035 * math.sin(a)), (0.012, 0.02, 0.012),
                                     12))
    parts.append(mesh_part(tb, "Taste buds", "Papillae", "#f5d96b", TONGUE["taste"], "gland", rank=2,
                           detail=(0.05, 200.0, 0.9, 2)))
    gl = Volume((vc[0] - 0.5, 0.2, -0.5), (vc[0] + 0.5, 0.62, 0.5), 0.0035)
    du = Volume((vc[0] - 0.5, 0.2, -0.5), (vc[0] + 0.5, 0.62, 0.5), 0.0035)
    for i, a in enumerate(np.linspace(0, 2 * math.pi, 6, endpoint=False)):
        c = vc + np.array([(R_v + W / 2) * math.cos(a), 0.34, (R_v + W / 2) * math.sin(a)])
        gl.add_all(blob_cluster(c, 18, 0.02, (0.07, 0.04, 0.07), seed=30 + i), "smooth", 0.01)
        du.tube(np.array([c, c + np.array([0.0, 0.12, 0.0]), c + np.array([0.0, 0.25, 0.0])]), [0.009, 0.008, 0.007])
    gl.displace(0.0015, 50.0, 2, seed=4)
    parts.append(sdf_part(gl, "Von Ebner glands", "Muscle & glands", "#b7d3ea", TONGUE["ebner"], "gland", rank=-2,
                          detail=(0.08, 140.0, 0.9, 0)))
    parts.append(sdf_part(du, "Von Ebner ducts", "Muscle & glands", "#8fb6d8", TONGUE["ebner_ducts"], "gland",
                          rank=-1, smooth=0.6))
    longm, transm, vertm = Mesh(), Mesh(), Mesh()
    fib_lo, fib_hi = np.array([X0, 0.0, Z0]), np.array([X1, 0.45, Z1])
    fibres = Volume(fib_lo, fib_hi, 0.0065)                    # only used to carve the interstitium
    for yb in (0.08, 0.3):
        for zb in np.arange(Z0 + 0.06, Z1, 0.1):
            p = wavy_path((X0 - 0.006, yb + rng.uniform(-0.01, 0.01), zb), (X1 + 0.006, yb, zb + 0.02), 40, 0.008, 2,
                          seed=int(abs(zb) * 100 + 60))
            rad = rng.uniform(0.028, 0.036)
            longm.extend(tube(p, rad, 18))
            fibres.tube(p, rad)
    for xb in np.arange(X0 + 0.06, X1, 0.1):
        p = wavy_path((xb, 0.19, Z0 - 0.006), (xb + 0.02, 0.2, Z1 + 0.006), 30, 0.008, 2,
                      seed=int(abs(xb) * 100 + 90))
        rad = rng.uniform(0.028, 0.036)
        transm.extend(tube(p, rad, 18))
        fibres.tube(p, rad)
    for xb in np.arange(X0 + 0.1, X1, 0.2):
        for zb in np.arange(Z0 + 0.1, Z1, 0.2):
            vp = np.array([(xb, 0.02, zb), (xb + 0.01, 0.22, zb), (xb, 0.42, zb + 0.01)])
            vertm.extend(tube(vp, 0.018, 14))
            fibres.tube(vp, 0.018)
    # the interstitium is what is left between the bundles, so all three fibre directions stay visible
    inter = Volume(fib_lo, fib_hi, 0.0065)
    ix, iy, iz = inter.axes()
    ibox, _, _ = box_shape((fib_lo + fib_hi) / 2, (fib_hi - fib_lo) / 2 - 0.004)
    inter.d = np.maximum(ibox(ix, iy, iz), -(fibres.d - 0.004)).astype(np.float32)
    parts.append(sdf_part(inter, "Intrinsic muscle (interstitium)", "Muscle & glands", "#b04e45", TONGUE["muscle"],
                          "muscle", smooth=0.7, bulk=True, rank=-3, detail=(0.1, 60.0, 0.3, 0)))
    parts += [mesh_part(longm, "Longitudinal fibres", "Muscle & glands", "#c45f55", TONGUE["long"], "muscle", rank=-3,
                        detail=(0.06, 90.0, 0.4, 1)),
              mesh_part(transm, "Transverse fibres", "Muscle & glands", "#9a4038", TONGUE["trans"], "muscle", rank=-3,
                        detail=(0.06, 90.0, 0.4, 3)),
              mesh_part(vertm, "Vertical fibres", "Muscle & glands", "#b85248", TONGUE["vert"], "muscle", rank=-3,
                        detail=(0.06, 90.0, 0.4, 2))]
    nerve = tube(smooth_path(np.array([(X0 + 0.02, 0.47, -0.1), (vc[0] - 0.1, 0.5, -0.05), (vc[0], 0.56, 0.0)]), 40),
                 0.018, 14)
    art = tube(wavy_path((X0 + 0.01, 0.46, 0.35), (X1 - 0.01, 0.46, 0.4), 60, 0.02, 2.0, seed=2), 0.022, 16)
    parts.append(mesh_part(nerve, "Glossopharyngeal nerve branch", "Nerves & vessels", "#f0cf45", TONGUE["nerve"],
                           "nerve", rank=-1))
    parts.append(mesh_part(art, "Lingual artery branch", "Nerves & vessels", "#cf3a31", TONGUE["vessels"], "artery",
                           rank=-1))
    return settle(parts, seed=405, amp_xz=0.030, amp_y=0.065, freq=1.5, grain=0.006)
