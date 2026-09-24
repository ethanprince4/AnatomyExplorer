"""Nephron and renal corpuscle: a juxtamedullary nephron traced from its glomerulus to the collecting duct.

Calibres are to scale (1 unit = 0.5 mm, so the renal corpuscle is ~200 µm across, the proximal tubule ~55 µm and a
thin limb ~20 µm); lengths are foreshortened, as in every textbook drawing - the proximal tubule alone is ~14 mm long.

The whole tubule is one continuous centreline, so every segment hands over to the next at the right place and with
the right step in calibre. Before anything is meshed, all the centrelines (tubule, collecting ducts, arterioles,
vasa recta) are relaxed together: points that come closer than the two walls allow are pushed apart and the curves
smoothed again, which packs the convolutions the way they pack in the cortex without any tube passing through
another.
"""
import math

import numpy as np
from scipy.spatial import cKDTree

from .cells import frame_from_normal, sample_surface
from .geometry import Mesh, ellipsoid as ellipsoid_mesh, smooth_path, tube
from .kit import Volume, capsule, ellipsoid, mesh_part, round_cone, sdf_part
from .organic import Sweep, cell_lattice, cells_on, rmul, rsum, settle, surf_noise

# model units: 1 unit = 0.5 mm
GC = np.array([0.0, 0.80, 0.0])          # glomerulus centre
R_CAP_IN, R_CAP_OUT = 0.184, 0.200       # Bowman capsule, parietal layer
DV = np.array([-0.30, 1.0, 0.16])        # towards the vascular pole
DV = DV / np.linalg.norm(DV)
DU = -DV                                  # urinary pole opposite
# zone boundaries (y): cortex | outer stripe | inner stripe | inner medulla
Y_CM, Y_OS, Y_IS = 0.26, -0.16, -0.62
Y_TOP, Y_BOT = 1.36, -1.50
X_LO, X_HI = -1.02, 1.16
Z_BACK = -0.64

DESC = {
    "glom": "Glomerular capillaries: a tuft of 5–8 lobules of anastomosing capillary loops, fed by the afferent and "
            "drained by the efferent arteriole – a high-pressure (~50–60 mmHg) capillary bed between two "
            "arterioles. The endothelium is fenestrated (70–100 nm pores, no diaphragms). Filtration barrier: "
            "fenestrated endothelium + glomerular basement membrane (type IV collagen, negatively charged heparan "
            "sulfate) + podocyte slit diaphragms (nephrin, podocin). GFR ≈ 125 mL/min (~180 L/day); molecules "
            "above ~8 nm and anions such as albumin are held back. Alport syndrome (type IV collagen α3–α5), "
            "anti-GBM (Goodpasture) disease and diabetic GBM thickening all strike here.",
    "podocytes": "Podocytes (visceral layer of Bowman capsule): large cell bodies bulging into the urinary space, "
                 "whose primary processes wrap the capillary loops and end in interdigitating foot processes; the "
                 "slit diaphragms between them (nephrin, podocin) are the final size barrier. Foot-process "
                 "effacement is the lesion of minimal change disease and FSGS – nephrotic syndrome (proteinuria "
                 ">3.5 g/day, hypoalbuminaemia, oedema, hyperlipidaemia). Subepithelial immune deposits beneath "
                 "them give membranous nephropathy (anti-PLA2R).",
    "mesangium": "Intraglomerular mesangial cells: contractile, phagocytic cells in the stalk and axis of each "
                 "lobule, embedded in their own matrix. They support the loops, clear trapped macromolecules and "
                 "contract under angiotensin II. IgA nephropathy deposits IgA here (the commonest "
                 "glomerulonephritis worldwide); diabetic nephropathy expands the matrix into Kimmelstiel–Wilson "
                 "nodules.",
    "bowman": "Bowman capsule, parietal layer: simple squamous epithelium on a basement membrane enclosing the "
              "urinary (Bowman) space, which receives the ultrafiltrate. At the vascular pole it reflects onto the "
              "tuft as the podocyte (visceral) layer; at the urinary pole it turns abruptly into the cuboidal, "
              "brush-bordered epithelium of the proximal tubule. Proliferating parietal cells, macrophages and "
              "fibrin form the crescents of rapidly progressive glomerulonephritis.",
    "aff": "Afferent arteriole: a branch of the cortical radiate artery entering the vascular pole. Its tone sets "
           "glomerular pressure and is autoregulated by the myogenic response and tubuloglomerular feedback. "
           "Prostaglandins dilate it, so NSAIDs constrict it and can precipitate acute kidney injury (especially "
           "with an ACE inhibitor and a diuretic – the 'triple whammy'). Its wall holds the renin-secreting JG "
           "cells.",
    "eff": "Efferent arteriole: drains the glomerulus – narrower than the afferent, which keeps glomerular pressure "
           "high. Angiotensin II constricts it preferentially, sustaining GFR when perfusion falls; ACE inhibitors "
           "and ARBs dilate it, so GFR falls (a creatinine rise, dangerous in bilateral renal artery stenosis). It "
           "breaks up into a second capillary bed – peritubular capillaries from cortical glomeruli, vasa recta "
           "from juxtamedullary glomeruli like this one (an arterial portal system).",
    "jg": "Juxtaglomerular (granular) cells: epithelioid, modified smooth muscle cells in the wall of the afferent "
          "arteriole, packed with renin granules. Renin is released when (1) afferent stretch falls "
          "(intrarenal baroreceptor), (2) NaCl delivery to the macula densa falls, (3) β1-sympathetic tone rises. "
          "Renin → angiotensin I → (ACE) angiotensin II → vasoconstriction, aldosterone, ADH and thirst. "
          "β-blockers and aliskiren reduce the cascade at its start; a reninoma causes hypertension with "
          "hypokalaemia.",
    "md": "Macula densa: a plaque of tall, crowded, closely packed cells in the wall of the thick ascending limb "
          "where it touches the vascular pole of its own glomerulus – the sensor of the JG apparatus. It reads "
          "luminal NaCl through NKCC2: high NaCl → ATP/adenosine → afferent constriction (tubuloglomerular "
          "feedback, lowering single-nephron GFR); low NaCl → prostaglandin E2 and NO → renin release. Loop "
          "diuretics block its NKCC2 and so stimulate renin.",
    "lacis": "Extraglomerular mesangial (lacis, Goormaghtigh) cells: flat cells filling the triangle between the "
             "afferent arteriole, the efferent arteriole and the macula densa. Coupled by gap junctions to the "
             "intraglomerular mesangium and the JG cells, they relay the macula densa signal to the arterioles.",
    "pct": "Proximal convoluted tubule: simple cuboidal to low columnar cells, intensely eosinophilic (packed with "
           "mitochondria), with a tall brush border of microvilli that nearly fills the lumen and basolateral "
           "interdigitations. Reabsorbs ~65–70% of filtered Na⁺ and water (isosmotically), all the glucose "
           "(SGLT2) and amino acids, ~80% of HCO₃⁻ (NHE3 + carbonic anhydrase), and phosphate (NaPi-IIa, reduced "
           "by PTH and FGF23); secretes organic anions and cations (OAT/OCT – penicillin, most diuretics, "
           "creatinine); makes ammonia and 1α-hydroxylates vitamin D. Drug targets: SGLT2 inhibitors (-gliflozins), "
           "acetazolamide (carbonic anhydrase), mannitol. Fanconi syndrome; first to die in ischaemic or toxic "
           "(aminoglycoside, cisplatin, contrast) acute tubular necrosis.",
    "pst": "Proximal straight tubule (pars recta, S3): descends through the medullary ray into the outer stripe of the "
           "outer medulla. Shorter brush border and fewer mitochondria than the convoluted part; continues "
           "reabsorption and is the main site of organic anion and cation secretion. Lying in the poorly "
           "oxygenated outer stripe, S3 is the segment most vulnerable to ischaemic acute tubular necrosis.",
    "tdl": "Thin descending limb: simple squamous epithelium (nuclei bulge into the lumen – distinguish from "
           "capillaries by the absence of red cells). Highly permeable to water (aquaporin-1) but not to NaCl, so "
           "water leaves into the hyperosmotic interstitium and the tubular fluid concentrates, to ~1200 mOsm/kg "
           "at the hairpin of a long loop. Only juxtamedullary nephrons (~15%) have long loops reaching the inner "
           "medulla.",
    "tal_thin": "Thin ascending limb: simple squamous epithelium present only in long loops, starting just before "
                "the hairpin. Impermeable to water (no aquaporins) but permeable to NaCl, which leaves passively "
                "(ClC-K1 channels) down the gradient the descending limb created – the fluid starts to dilute "
                "while the inner medulla stays salty.",
    "tal": "Thick ascending limb: simple cuboidal cells with no brush border and deep basal mitochondrial "
           "infoldings. The apical Na⁺-K⁺-2Cl⁻ cotransporter NKCC2 reabsorbs ~25% of filtered Na⁺; K⁺ recycling "
           "through ROMK makes the lumen positive, driving paracellular Ca²⁺ and Mg²⁺ reabsorption "
           "(claudin-16/19). Impermeable to water – the 'diluting segment' and engine of the countercurrent "
           "multiplier. Secretes uromodulin (Tamm–Horsfall protein, the matrix of urinary casts). Loop diuretics "
           "(furosemide, bumetanide, torasemide) block NKCC2: potent natriuresis, hypokalaemia, hypomagnesaemia, "
           "hypercalciuria, ototoxicity. Bartter syndrome is the genetic equivalent. Ends at the macula densa.",
    "dct": "Distal convoluted tubule: simple cuboidal cells, a wider and cleaner lumen than the PCT, no brush "
           "border, many mitochondria. The Na⁺-Cl⁻ cotransporter NCC reabsorbs 5–10% of filtered Na⁺; impermeable "
           "to water, so dilution continues. Reabsorbs Ca²⁺ (TRPV5, stimulated by PTH) and Mg²⁺ (TRPM6). "
           "Thiazides block NCC: natriuresis, hypokalaemia, hyponatraemia, and less urinary calcium (useful for "
           "calcium stones). Gitelman syndrome is loss of NCC; Gordon syndrome (WNK kinase mutations) its "
           "overactivity.",
    "cnt": "Connecting tubule: joins the DCT to a cortical collecting duct, often as an arcade collecting several "
           "nephrons. Principal-like CNT cells with ENaC respond to aldosterone and ADH; intercalated cells appear; "
           "a major site of regulated Ca²⁺ reabsorption. Embryologically the junction with the collecting duct is "
           "where the nephron (metanephric mesenchyme) met the ureteric bud.",
    "ccd": "Cortical collecting duct: runs straight in a medullary ray. Principal cells (pale, one cilium) "
           "reabsorb Na⁺ through ENaC and secrete K⁺ through ROMK under aldosterone, and insert aquaporin-2 under "
           "ADH (V2 receptor → cAMP). Intercalated cells regulate acid–base: type A secrete H⁺ (H⁺-ATPase, "
           "H⁺/K⁺-ATPase), type B secrete HCO₃⁻ (pendrin). K⁺-sparing diuretics act here – amiloride and "
           "triamterene block ENaC, spironolactone and eplerenone block the mineralocorticoid receptor. Liddle "
           "syndrome (ENaC gain of function); distal (type 1) renal tubular acidosis; lithium enters via ENaC "
           "and causes nephrogenic diabetes insipidus.",
    "mcd": "Medullary collecting duct: ducts fuse repeatedly and widen as they descend, their cuboidal cells "
           "becoming columnar, until they open as papillary ducts of Bellini on the area cribrosa of the papilla. "
           "ADH-driven aquaporin-2 lets water leave into the hyperosmotic medulla, setting final urine osmolality "
           "(50–1200 mOsm/kg); inner medullary ducts recycle urea (UT-A1/3) to build the gradient. Nephrogenic "
           "diabetes insipidus (V2 receptor or AQP2 defects, lithium); vaptans (tolvaptan) block V2 in SIADH and "
           "ADPKD.",
    "ptc": "Peritubular capillaries: the second capillary bed, continuing from efferent arterioles and wrapping "
           "the cortical tubules. Low hydrostatic and high oncotic pressure (plasma was just concentrated by "
           "filtration) draw reabsorbed fluid back into the blood. Fenestrated; interstitial fibroblasts beside "
           "them make erythropoietin when oxygen falls – lost in the anaemia of chronic kidney disease.",
    "dvr": "Descending vasa recta: straight vessels arising from the efferent arterioles of juxtamedullary glomeruli, "
           "running down in vascular bundles beside the loops. Continuous endothelium with contractile pericytes, "
           "aquaporin-1 and urea transporters (UT-B). Medullary blood flow is only ~10% of renal flow, so the "
           "medulla is hypoxic – papillary necrosis (NSAIDs, sickle cell disease, diabetes, pyelonephritis).",
    "avr": "Ascending vasa recta: wider, fenestrated vessels returning from the hairpin to the arcuate veins. By "
           "countercurrent exchange with the descending vasa recta they carry away reabsorbed water without "
           "washing out the medullary salt and urea gradient.",
    "cra": "Cortical radiate (interlobular) artery: rises from the arcuate artery at the corticomedullary junction "
           "towards the capsule, between medullary rays, giving off afferent arterioles. Renal arteries are "
           "end-arteries, so occlusion gives a wedge-shaped infarct.",
    "arca": "Arcuate artery: arches along the corticomedullary junction at the base of the medullary pyramid, "
            "between the interlobar artery and the cortical radiate arteries it gives off towards the capsule.",
    "arcv": "Arcuate vein: runs beside the arcuate artery at the corticomedullary junction, collecting the cortical "
            "radiate veins and the ascending vasa recta and draining to the interlobar veins.",
    "crv": "Cortical radiate (interlobular) vein: collects the peritubular capillaries and drains to the arcuate "
           "vein at the corticomedullary junction.",
    "cortex": "Renal cortex: holds every renal corpuscle and the convoluted tubules (cortical labyrinth), with the "
              "medullary rays of straight tubules and collecting ducts running through it. Receives ~90% of renal "
              "blood flow.",
    "os": "Outer stripe of the outer medulla: proximal straight tubules (S3), thick ascending limbs and collecting "
          "ducts. High metabolic demand with little oxygen – where ischaemic tubular injury concentrates.",
    "is": "Inner stripe of the outer medulla: thin descending limbs, thick ascending limbs, collecting ducts and "
          "vascular bundles of vasa recta. The NaCl pumped out by the thick limbs begins the osmotic gradient "
          "here.",
    "im": "Inner medulla (papilla): only thin limbs of long loops, collecting ducts and vasa recta. Interstitial "
          "osmolality climbs to ~1200 mOsm/kg towards the papilla tip, about half NaCl and half urea.",
}


# --------------------------------------------------------------------------------------------- centrelines
def _resample(path, spacing):
    """Even arc-length resampling of a polyline."""
    path = np.asarray(path, float)
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    n = max(int(arc[-1] / spacing) + 1, 3)
    s = np.linspace(0.0, arc[-1], n)
    return np.stack([np.interp(s, arc, path[:, c]) for c in range(3)], -1)


def _spline(points, spacing=0.012):
    pts = np.asarray(points, float)
    return _resample(smooth_path(pts, max(len(pts) * 24, 60)), spacing)


def _untangle(paths, radii, fixed, avoid, anchors=None, iters=90, gap=0.014, spacing=0.012):
    """Relax a set of centrelines so no two walls overlap.

    Every point that is closer to another than their two radii plus `gap` is pushed apart along the line between
    them (points on the same curve are exempt within a few radii of arc length, since those are neighbours, not a
    collision); then each curve is smoothed a little so the pushes spread out into gentle bends. `fixed` marks
    points that must not move, `avoid` those that must keep clear of the renal corpuscle. `anchors` (per path, a
    list of indices) are points that may move but keep their place in the sequence when the spacing is evened out,
    so segment boundaries stay where they were put."""
    paths = [p.copy() for p in paths]
    owner = np.concatenate([np.full(len(p), k) for k, p in enumerate(paths)])
    index = np.concatenate([np.arange(len(p)) for p in paths])
    rad = np.concatenate(radii)
    fix = np.concatenate(fixed)
    avo = np.concatenate(avoid)
    offs = np.cumsum([0] + [len(p) for p in paths])
    reach = 2 * rad.max() + gap
    for it in range(iters):
        P = np.vstack(paths)
        pairs = cKDTree(P).query_pairs(reach, output_type="ndarray")
        disp = np.zeros_like(P)
        if len(pairs):
            i, j = pairs[:, 0], pairs[:, 1]
            v = P[i] - P[j]
            d = np.linalg.norm(v, axis=1)
            need = rad[i] + rad[j] + gap
            near = (owner[i] == owner[j]) & (np.abs(index[i] - index[j]) * spacing < need * 2.4 + 0.03)
            hit = (d < need) & ~near
            i, j, v, d, need = i[hit], j[hit], v[hit], d[hit], need[hit]
            u = v / np.maximum(d, 1e-6)[:, None]
            push = ((need - d) * 0.5)[:, None] * u
            wi = np.where(fix[j], 2.0, 1.0)[:, None]         # a fixed partner cannot give way, so move twice as far
            wj = np.where(fix[i], 2.0, 1.0)[:, None]
            np.add.at(disp, i, push * wi)
            np.add.at(disp, j, -push * wj)
        # keep clear of the renal corpuscle
        rel = P - GC
        dist = np.linalg.norm(rel, axis=1)
        clear = R_CAP_OUT + rad + gap
        bad = avo & (dist < clear)
        disp[bad] += rel[bad] / np.maximum(dist[bad], 1e-6)[:, None] * (clear[bad] - dist[bad])[:, None]
        disp[fix] = 0.0
        P = P + disp * 0.8
        free = ~fix
        P[free, 0] = np.clip(P[free, 0], X_LO + 0.06, X_HI - 0.06)
        P[free, 2] = np.clip(P[free, 2], Z_BACK + 0.1, 0.52)
        paths = [P[offs[k]:offs[k + 1]] for k in range(len(paths))]
        for k, p in enumerate(paths):
            f = fixed[k]
            lap = np.zeros_like(p)
            lap[1:-1] = (p[:-2] + p[2:]) * 0.5 - p[1:-1]
            lap[f] = 0.0
            p += lap * 0.35
        if it % 15 == 14:        # even out the point spacing again (endpoints and fixed points stay put)
            for k, p in enumerate(paths):
                if fixed[k].all():
                    continue
                seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
                arc = np.concatenate([[0.0], np.cumsum(seg)])
                keep = np.where(fixed[k])[0]
                if anchors is not None and anchors[k] is not None:
                    keep = np.unique(np.r_[keep, anchors[k], 0, len(p) - 1])
                target = np.linspace(0, arc[-1], len(p))
                # piecewise: fixed points keep their arc position
                target[keep] = arc[keep]
                for a, b in zip(keep[:-1], keep[1:]):
                    target[a:b + 1] = np.linspace(arc[a], arc[b], b - a + 1)
                paths[k] = np.stack([np.interp(target, arc, p[:, c]) for c in range(3)], -1)
    return paths


# convoluted segments wind on a smaller scale than their control points: (amplitude, wavelength)
_MEANDER = {"pct": (0.035, 0.30), "dct": (0.022, 0.26)}


def _meander(path, amp, wavelength, seed=0):
    """Add a small-scale winding to a centreline (fading out at both ends so the joins stay put)."""
    rng = np.random.default_rng(seed + 40)
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.gradient(path, axis=0)
    t /= np.linalg.norm(t, axis=1, keepdims=True)
    a = np.cross(t, rng.normal(size=3))
    a /= np.linalg.norm(a, axis=1, keepdims=True)
    b = np.cross(t, a)
    ph = arc / wavelength * 2 * math.pi
    fade = np.clip(np.minimum(arc, arc[-1] - arc) / 0.15, 0.0, 1.0)
    wob = 1.0 + 0.4 * np.sin(arc * 3.1 + rng.uniform(0, 6))
    off = a * np.sin(ph)[:, None] + b * np.sin(ph * 0.63 + 1.3)[:, None]
    return _resample(path + off * (amp * fade * wob)[:, None], 0.012)


# --------------------------------------------------------------------------------------------- walls
def _wall(path, r_in, r_out, seed, cell=0.040, amp=0.004, aspect=1.2, brush=0.0, calibre=0.05, n_theta=56,
          spacing=0.010, outer_cells=0.35):
    """Hollow tubule or vessel wall around a centreline, built from its own cells.

    r_in / r_out are numbers or arrays along the path. The cells bulge into the lumen (the apical side) and only
    faintly on the basal side, which sits on a smooth basement membrane. `brush` roughens the lumen into the fuzz of
    a brush border."""
    path = np.asarray(path, float)
    n = len(path)
    L = float(np.linalg.norm(np.diff(path, axis=0), axis=1).sum())
    n_s = int(np.clip(L / spacing, 24, 700))
    sw = Sweep(path, n_theta, n_s)
    xs = np.linspace(0.0, 1.0, n)
    ri_arr = np.broadcast_to(np.asarray(r_in, float), (n,))
    ro_arr = np.broadcast_to(np.asarray(r_out, float), (n,))
    ri = lambda T, S: np.interp(S, xs, ri_arr)
    ro = lambda T, S: np.interp(S, xs, ro_arr)
    r_typ = float(ro_arr.mean())
    cal = rsum(1.0, surf_noise(calibre, 1.6, max(L * 2.2, 2.0), seed + 11))
    cells = cells_on(cell, 1.0, seed + 17, aspect=aspect, groove=0.26, dome=0.6, r_typ=r_typ, length=L)
    outer = rsum(rmul(ro, cal), rmul(cells, amp * outer_cells))
    inner_terms = [rmul(ri, cal), rmul(cells, -amp)]
    if brush:
        inner_terms.append(surf_noise(brush, 34.0, max(L * 60.0, 30.0), seed + 23, octaves=2))
    inner = rsum(*inner_terms)
    return sw, sw.shell(inner, outer)


def _vessel_wall(path, r_in, r_out, seed, n_theta=40, spacing=0.012):
    """Arteriole or vein: smooth muscle cells wrapped round the circumference (aspect < 1)."""
    return _wall(path, r_in, r_out, seed, cell=0.022, amp=0.0025, aspect=0.35, calibre=0.04, n_theta=n_theta,
                 spacing=spacing, outer_cells=0.6)[1]


def _capillary(path, radius, segments=9):
    """A thin vessel with a slightly varying calibre (tube radius per point)."""
    path = np.asarray(path, float)
    k = np.arange(len(path))
    r = radius * (1.0 + 0.12 * np.sin(k * 0.45 + radius * 900.0) + 0.06 * np.sin(k * 1.3))
    return tube(path, r, segments)


# --------------------------------------------------------------------------------------------- renal corpuscle
def _frame():
    e1 = np.cross(DV, np.array([0.0, 0.0, 1.0]))
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(DV, e1)
    return e1, e2


def _tuft_paths(rng):
    """Capillary loops of the glomerular tuft.

    The afferent arteriole divides at the hilum into one branch per lobule; within each lobule the capillaries run
    out to the periphery as a meandering, anastomosing loop just under the capsule and come back to join the
    lobule's efferent branch, which returns to the hilum beside its afferent twin."""
    e1, e2 = _frame()
    hil_a = GC + DV * 0.150 - e1 * 0.030
    hil_e = GC + DV * 0.150 + e1 * 0.030
    branches, loops = [], []
    n_lob = 7
    for k in range(n_lob):
        # lobules fan out from the hilum and fill the capsule, the first ones curling back up beside the stalk
        pol = math.radians(48 + 125 * ((k * 3) % n_lob + 0.5) / n_lob)
        az = 2 * math.pi * k / n_lob * 2.0 + rng.uniform(-0.3, 0.3)
        d = DV * math.cos(pol) + math.sin(pol) * (e1 * math.cos(az) + e2 * math.sin(az))
        d /= np.linalg.norm(d)
        root = GC + DV * 0.085
        c_a = GC + d * 0.075 + rng.normal(scale=0.008, size=3)
        c_e = GC + d * 0.070 + rng.normal(scale=0.008, size=3) + np.cross(d, DV) * 0.018
        branches.append(smooth_path(np.array([hil_a, root - e1 * 0.02, c_a]), 20))
        branches.append(smooth_path(np.array([c_e, root + e1 * 0.02, hil_e]), 20))
        for m in range(5):
            # random walk over the sphere around this lobule's direction
            u = d + rng.normal(scale=0.30, size=3)
            u /= np.linalg.norm(u)
            h = np.cross(u, rng.normal(size=3))
            h /= np.linalg.norm(h)
            pts = [c_a + rng.normal(scale=0.01, size=3)]
            rr = rng.uniform(0.115, 0.14)
            for step in range(11):
                rr = float(np.clip(rr + rng.normal(scale=0.012), 0.105, 0.150))
                pts.append(GC + u * rr)
                turn = rng.normal(scale=0.9)
                side = np.cross(u, h)
                h = h * math.cos(turn) + side * math.sin(turn)
                h += (d - u) * 1.4                      # stay within the lobule
                h -= u * np.dot(h, u)
                h /= np.linalg.norm(h) + 1e-9
                u = u + h * (0.018 / rr * 1.6)
                u /= np.linalg.norm(u)
            pts.append(c_e + rng.normal(scale=0.01, size=3))
            loops.append(smooth_path(np.array(pts), 90))
    return branches, loops, hil_a, hil_e


def _renal_corpuscle(rng, pct_path, ro_pct, ri_pct):
    parts = []
    lo, hi = GC - 0.34, GC + 0.34
    branches, loops, hil_a, hil_e = _tuft_paths(rng)
    tuft = Volume(GC - 0.18, GC + 0.18, 0.0029)
    for p in branches:
        tuft.tube(p, np.linspace(0.0145, 0.0115, len(p)), "smooth", 0.006)
    for p in loops:
        tuft.tube(p, 0.0105, "smooth", 0.0055)
    tuft.displace(0.0010, 70.0, 2, seed=2)
    tuft_mesh = tuft.mesh(0.6)
    parts.append(mesh_part(tuft_mesh, "Glomerular capillaries", "Renal corpuscle", "#d23d34", DESC["glom"],
                           "artery", clip=False, detail=(0.05, 170.0, 0.5, 0)))

    # mesangial cells: a core along the stalk and the axis of every lobule
    mes = Volume(GC - 0.18, GC + 0.18, 0.0026)
    shapes = []
    for b in branches[::2]:
        for t in (0.35, 0.65, 0.95):
            c = b[int(t * (len(b) - 1))]
            shapes.append(ellipsoid(c + rng.normal(scale=0.004, size=3), (0.013, 0.010, 0.012)))
    mes.add_all(shapes, "smooth", 0.006)
    parts.append(sdf_part(mes, "Mesangial cells", "Renal corpuscle", "#c9a0a0", DESC["mesangium"], "gland",
                          smooth=0.7, clip=False, label=False))

    # podocytes: cell bodies on the outer face of the loops, primary processes clasping the capillaries
    pod = Volume(GC - 0.2, GC + 0.2, 0.0026)
    pts, nrm = sample_surface(tuft_mesh, 0.040, seed=3,
                              mask=lambda p, n: (np.einsum("ij,ij->i", n, p - GC) > 0.0)
                              & (np.linalg.norm(p - GC, axis=1) > 0.105))
    tuft_tree = cKDTree(tuft_mesh.arrays()[0])
    tuft_n = tuft_mesh.arrays()[1]

    def on_tuft(q, lift):
        _, j = tuft_tree.query(q)
        return tuft_tree.data[j] + tuft_n[j] * lift

    for p, n in zip(pts, nrm):
        c = p + n * 0.0085
        shapes = [ellipsoid(c, (0.0125, 0.0075, 0.011), rot=frame_from_normal(n))]
        for k in range(rng.integers(3, 6)):
            dvec = rng.normal(size=3)
            dvec -= n * np.dot(dvec, n)
            dvec /= np.linalg.norm(dvec) + 1e-9
            # each primary process runs over the surface of the loops and then forks
            a = on_tuft(c + dvec * 0.016, 0.0035)
            b = on_tuft(c + dvec * 0.030, 0.0025)
            shapes += [round_cone(c, a, 0.0046, 0.0032), round_cone(a, b, 0.0032, 0.0022)]
            fork = np.cross(dvec, n)
            shapes.append(round_cone(a, on_tuft(a + fork * 0.012 * rng.choice((-1, 1)), 0.0022), 0.0026, 0.0018))
        pod.add_all(shapes, "smooth", 0.004)
    parts.append(sdf_part(pod, "Podocytes (visceral layer)", "Renal corpuscle", "#8fcac1", DESC["podocytes"],
                          "gland", smooth=0.55, clip=False, detail=(0.05, 110.0, 0.9, 0)))

    # parietal layer, continuous with the proximal tubule at the urinary pole and open at the vascular pole
    cap = Volume(lo, hi, 0.0044)
    x, y, z = cap.axes()
    r = np.sqrt((x - GC[0]) ** 2 + (y - GC[1]) ** 2 + (z - GC[2]) ** 2)
    outer = r - R_CAP_OUT
    inner = r - R_CAP_IN
    neck = pct_path[:12]
    ov = Volume(lo, hi, 0.0044)
    ov.d = outer.astype(np.float32)
    ov.tube(np.vstack([GC + DU * 0.12, neck]), ro_pct, "smooth", 0.035)
    iv = Volume(lo, hi, 0.0044)
    iv.d = inner.astype(np.float32)
    iv.tube(np.vstack([GC + DU * 0.10, neck]), ri_pct * 1.4, "smooth", 0.03)
    shell = ov.copy(np.maximum(ov.d, -iv.d))
    shell.d = shell.d - cell_lattice(x, y, z, 0.05, 0.0006, seed=5)
    shell.add(capsule(GC + DV * 0.12, GC + DV * 0.32, 0.060), "smooth_subtract", 0.012)
    # the tubule wall takes over where the neck ends: trim the neck square there so its lumen stays open
    tip = pct_path[11]
    along = pct_path[12] - pct_path[10]
    along /= np.linalg.norm(along)
    half = (x - tip[0]) * along[0] + (y - tip[1]) * along[1] + (z - tip[2]) * along[2]
    near = np.sqrt((x - tip[0]) ** 2 + (y - tip[1]) ** 2 + (z - tip[2]) ** 2) < 0.1
    shell.d = np.where(near, np.maximum(shell.d, half), shell.d).astype(np.float32)
    parts.append(sdf_part(shell, "Bowman capsule (parietal layer)", "Renal corpuscle", "#d9bfae", DESC["bowman"],
                          "serosa", smooth=0.7, detail=(0.05, 120.0, 0.6, 0)))
    return parts, hil_a, hil_e


# --------------------------------------------------------------------------------------------- layout
def _layout():
    """Control points of every centreline. y runs from the capsule (top) to the papilla (bottom)."""
    e1, e2 = _frame()
    up0 = GC + DU * 0.195
    md = GC + DV * 0.225 + e2 * 0.075        # macula densa: against the vascular pole, between the two arterioles
    neph = {
        "pct": [up0, up0 + DU * 0.06, (0.10, 0.45, -0.05), (0.26, 0.40, -0.22), (0.30, 0.62, -0.35),
                (0.14, 0.78, -0.30), (0.22, 1.02, -0.22), (0.10, 1.18, -0.08), (0.30, 1.26, 0.05),
                (0.46, 1.10, -0.20), (0.38, 0.86, -0.08), (0.56, 0.70, -0.30), (0.74, 0.82, -0.12),
                (0.62, 1.04, 0.02), (0.80, 1.20, -0.02), (0.64, 1.26, 0.22), (0.42, 1.10, 0.24),
                (0.30, 0.86, 0.26), (0.46, 0.66, 0.30), (0.66, 0.60, 0.16), (0.80, 0.50, -0.02),
                (0.62, 0.40, 0.00)],
        "pst": [(0.62, 0.40, 0.00), (0.60, 0.20, 0.02), (0.60, -0.16, 0.03)],
        "tdl": [(0.60, -0.16, 0.03), (0.59, -0.60, 0.04), (0.58, -1.05, 0.03), (0.56, -1.30, 0.02)],
        "tal_thin": [(0.56, -1.30, 0.02), (0.52, -1.37, 0.02), (0.44, -1.36, 0.03), (0.42, -1.25, 0.04),
                     (0.41, -0.90, 0.05), (0.40, -0.62, 0.06)],
        "tal": [(0.40, -0.62, 0.06), (0.39, -0.20, 0.02), (0.36, 0.20, -0.10), (0.30, 0.50, -0.42),
                (0.16, 0.84, -0.40), md + np.array([0.12, -0.03, -0.07]), md],
        "dct": [md, md + np.array([-0.12, 0.02, -0.02]), (-0.28, 1.14, -0.10), (-0.42, 1.02, -0.30),
                (-0.56, 1.16, -0.40), (-0.62, 0.96, -0.26), (-0.48, 0.86, -0.46), (-0.30, 0.76, -0.34),
                (-0.44, 0.64, -0.20), (-0.60, 0.68, -0.44)],
        "cnt": [(-0.60, 0.68, -0.44), (-0.56, 1.00, -0.54), (-0.40, 1.26, -0.40), (0.0, 1.32, -0.36),
                (0.40, 1.34, -0.34), (0.74, 1.24, -0.26), (0.90, 1.14, -0.18)],
    }
    return neph, md


def build_nephron():
    rng = np.random.default_rng(7)
    parts = []
    neph, md_point = _layout()
    order = ["pct", "pst", "tdl", "tal_thin", "tal", "dct", "cnt"]
    # outer and luminal radius of each segment (to scale: 1 unit = 0.5 mm)
    calibre = {"pct": (0.056, 0.020), "pst": (0.050, 0.019), "tdl": (0.020, 0.012), "tal_thin": (0.019, 0.012),
               "tal": (0.032, 0.016), "dct": (0.037, 0.021), "cnt": (0.035, 0.021)}
    segs = [_meander(_spline(neph[k]), *_MEANDER[k], seed=i) if k in _MEANDER else _spline(neph[k])
            for i, k in enumerate(order)]
    path = np.vstack([segs[0]] + [s[1:] for s in segs[1:]])
    bounds = np.cumsum([0] + [len(segs[0])] + [len(s) - 1 for s in segs[1:]])
    rad_o = np.concatenate([np.full(b - a, calibre[k][0]) for k, a, b in zip(order, bounds[:-1], bounds[1:])])
    fix_n = np.zeros(len(path), bool)
    fix_n[:14] = True                                          # urinary pole and neck
    i_md = bounds[order.index("tal") + 1] - 1
    fix_n[i_md - 3:i_md + 4] = True                            # macula densa against the vascular pole
    fix_n[-1] = True
    avoid_n = np.ones(len(path), bool)
    avoid_n[:14] = False
    avoid_n[i_md - 14:i_md + 12] = False

    # collecting ducts: ours down the medullary ray, a second one from the neighbouring ray joining it in the
    # inner stripe; below the junction the duct is wider
    cd_main = _spline([(0.96, Y_TOP + 0.02, -0.18), (0.96, 0.6, -0.16), (0.97, -0.2, -0.14), (0.97, -0.62, -0.12),
                       (0.98, -1.1, -0.10), (0.98, Y_BOT - 0.02, -0.08)])
    cd_side = _spline([(0.78, Y_TOP + 0.02, -0.50), (0.80, 0.6, -0.50), (0.83, -0.10, -0.44), (0.90, -0.46, -0.28),
                       (0.965, -0.66, -0.14)])
    cd_r = np.interp(cd_main[:, 1], [Y_BOT, -0.66, -0.5, Y_CM, Y_TOP], [0.090, 0.078, 0.066, 0.056, 0.050])
    # arterial supply and venous drainage
    # arcuate artery and vein run along the corticomedullary junction; the cortical radiate vessels rise from them
    arca = _spline([(-0.74, Y_CM - 0.11, Z_BACK + 0.06), (-0.75, Y_CM - 0.10, 0.0), (-0.74, Y_CM - 0.12, 0.30)])
    arcv = _spline([(-0.91, Y_CM - 0.13, Z_BACK + 0.06), (-0.92, Y_CM - 0.12, 0.0), (-0.90, Y_CM - 0.14, 0.30)])
    cra = _spline([(-0.75, Y_CM - 0.10, -0.12), (-0.74, Y_CM + 0.12, -0.11), (-0.76, 0.7, -0.10),
                   (-0.74, Y_TOP + 0.02, -0.08)])
    crv = _spline([(-0.92, Y_CM - 0.12, -0.40), (-0.91, Y_CM + 0.12, -0.41), (-0.93, 0.7, -0.42),
                   (-0.92, Y_TOP + 0.02, -0.40)])
    e1, e2 = _frame()
    hil_a = GC + DV * 0.150 - e1 * 0.030
    hil_e = GC + DV * 0.150 + e1 * 0.030
    aff = _spline([(-0.74, 1.02, -0.08), (-0.56, 1.10, -0.03), (-0.36, 1.10, 0.00), hil_a + DV * 0.10 - e1 * 0.06,
                   hil_a])
    eff = _spline([hil_e, hil_e + DV * 0.08 + e1 * 0.05 - e2 * 0.02, (0.17, 1.12, 0.04), (0.22, 1.18, -0.20),
                   (0.10, 1.10, -0.48), (-0.02, 0.76, -0.52), (-0.10, 0.42, -0.48), (-0.10, Y_CM + 0.02, -0.42)])
    # vasa recta: three hairpins from the efferent arteriole, dropping to different depths
    vr_d, vr_a = [], []
    for k, (depth, dx, dz) in enumerate([(-0.55, -0.04, 0.0), (-0.98, 0.05, 0.06), (-1.34, 0.14, 0.02)]):
        top = eff[-1]
        a = _spline([top, top + np.array([dx * 0.5, -0.12, dz]), (top[0] + dx, (top[1] + depth) / 2, top[2] + dz),
                     (top[0] + dx, depth + 0.05, top[2] + dz * 0.5)])
        tip = a[-1] + np.array([0.07, -0.05, 0.0])
        b = _spline([tip, (a[-1][0] + 0.14, depth + 0.04, top[2] + dz - 0.04),
                     (top[0] + dx + 0.15, (top[1] + depth) / 2, top[2] + dz - 0.06),
                     (top[0] + dx + 0.16, Y_CM - 0.02, -0.50 + 0.04 * k), (-0.30, Y_CM - 0.10, -0.46 + 0.07 * k),
                     (-0.91, Y_CM - 0.13, -0.40 + 0.09 * k)])
        a = np.vstack([a, _spline([a[-1], a[-1] + np.array([0.035, -0.035, 0.0]), tip])[1:]])
        vr_d.append(a)
        vr_a.append(b)

    # ---- relax everything together
    paths = [path, cd_main, cd_side, cra, crv, aff, eff] + vr_d + vr_a + [arca, arcv]
    radii = [rad_o, cd_r, np.full(len(cd_side), 0.055), np.full(len(cra), 0.05), np.full(len(crv), 0.06),
             np.full(len(aff), 0.034), np.full(len(eff), 0.027)] + \
            [np.full(len(p), 0.011) for p in vr_d] + [np.full(len(p), 0.014) for p in vr_a] + \
            [np.full(len(arca), 0.07), np.full(len(arcv), 0.085)]
    fixed = [fix_n] + [np.ones(len(p), bool) for p in (cd_main, cd_side, cra, crv, aff)] + \
            [np.r_[np.ones(14, bool), np.zeros(len(eff) - 15, bool), True]] + \
            [np.r_[True, np.zeros(len(p) - 2, bool), True] for p in vr_d + vr_a] + \
            [np.ones(len(arca), bool), np.ones(len(arcv), bool)]
    avoid = [avoid_n] + [np.ones(len(p), bool) for p in (cd_main, cd_side, cra, crv)] + \
            [np.zeros(len(aff), bool), np.r_[np.zeros(20, bool), np.ones(len(eff) - 20, bool)]] + \
            [np.ones(len(p), bool) for p in vr_d + vr_a] + [np.ones(len(arca), bool), np.ones(len(arcv), bool)]
    relaxed = _untangle(paths, radii, fixed, avoid, anchors=[bounds[1:-1]] + [None] * (len(paths) - 1))
    path, eff = relaxed[0], relaxed[6]
    vr_d, vr_a = relaxed[7:10], relaxed[10:13]

    # ---- renal corpuscle
    ro_pct, ri_pct = calibre["pct"]
    rc_parts, _, _ = _renal_corpuscle(rng, path, ro_pct, ri_pct)
    parts += rc_parts
    parts.append(mesh_part(_vessel_wall(aff, 0.015, 0.034, 51), "Afferent arteriole", "Renal corpuscle", "#c8322b",
                           DESC["aff"], "artery", detail=(0.06, 120.0, 0.6, 4)))
    parts.append(mesh_part(_vessel_wall(eff, 0.012, 0.026, 53), "Efferent arteriole", "Renal corpuscle", "#a82a25",
                           DESC["eff"], "artery", detail=(0.06, 120.0, 0.6, 4)))

    # ---- juxtaglomerular apparatus
    jg = Mesh()
    L_aff = len(aff)
    # plump epithelioid cells replacing the smooth muscle of the last stretch before the pole, bulging a little
    # proud of the wall
    for i in range(int(L_aff * 0.76), int(L_aff * 0.96), 2):
        t = aff[min(i + 1, L_aff - 1)] - aff[max(i - 1, 0)]
        t /= np.linalg.norm(t)
        side = np.cross(t, [0.0, 1.0, 0.0])
        side /= np.linalg.norm(side)
        up = np.cross(side, t)
        for a in np.linspace(0, 2 * math.pi, 9, endpoint=False) + i * 0.9 + rng.uniform(-0.2, 0.2):
            dvec = side * math.cos(a) + up * math.sin(a)
            rot = frame_from_normal(dvec)
            jg.extend(ellipsoid_mesh(aff[i] + dvec * rng.uniform(0.026, 0.028),
                                     (0.0092, 0.0064, 0.0078) * rng.uniform(0.85, 1.15, 3), 9, rotation=rot))
    parts.append(mesh_part(jg, "Juxtaglomerular (granular) cells", "Juxtaglomerular apparatus", "#e9b04a",
                           DESC["jg"], "gland", clip=False))
    # macula densa: a plaque of tall, crowded cells on the side of the thick limb facing the vascular pole
    md = Mesh()
    c_md = path[i_md]
    t_md = path[i_md + 1] - path[i_md - 1]
    t_md /= np.linalg.norm(t_md)
    toward = (GC + DV * 0.2) - c_md
    toward -= t_md * np.dot(toward, t_md)
    toward /= np.linalg.norm(toward)
    side = np.cross(t_md, toward)
    for u in np.linspace(-0.05, 0.05, 11):
        for a in np.linspace(-0.8, 0.8, 7):
            if (u / 0.055) ** 2 + (a / 0.85) ** 2 > 1.0:          # an oval plaque
                continue
            a2 = a + rng.uniform(-0.08, 0.08)
            dvec = toward * math.cos(a2) + side * math.sin(a2)
            p = c_md + t_md * (u + rng.uniform(-0.003, 0.003)) + dvec * rng.uniform(0.029, 0.031)
            md.extend(ellipsoid_mesh(p, (0.0048, 0.0085, 0.0048) * rng.uniform(0.85, 1.1, 3), 9,
                                     rotation=frame_from_normal(dvec)))
    parts.append(mesh_part(md, "Macula densa", "Juxtaglomerular apparatus", "#8e6db5", DESC["md"], "gland",
                           clip=False))
    # lacis cells in the triangle between the two arterioles and the macula densa
    lac = Volume(GC - 0.4, GC + 0.4, 0.003)
    pole = GC + DV * 0.215
    tri = [pole, aff[int(L_aff * 0.9)], eff[min(12, len(eff) - 1)], c_md + toward * 0.03]
    centre = np.mean(tri, axis=0)
    shapes = []
    for k in range(16):
        w = rng.dirichlet(np.ones(4))
        p = np.sum(np.array(tri) * w[:, None], axis=0) * 0.7 + centre * 0.3
        shapes.append(ellipsoid(p, (0.013, 0.007, 0.011), rot=frame_from_normal(rng.normal(size=3))))
    lac.add_all(shapes, "smooth", 0.004)
    parts.append(sdf_part(lac, "Extraglomerular mesangial (lacis) cells", "Juxtaglomerular apparatus", "#e0895a",
                          DESC["lacis"], "gland", smooth=0.6, clip=False))

    # ---- the tubule, segment by segment
    names = {"pct": ("Proximal convoluted tubule", "Proximal tubule", "#e59b8c"),
             "pst": ("Proximal straight tubule", "Proximal tubule", "#dc8c7c"),
             "tdl": ("Thin descending limb", "Loop of Henle", "#efe0cc"),
             "tal_thin": ("Thin ascending limb", "Loop of Henle", "#dccb94"),
             "tal": ("Thick ascending limb", "Loop of Henle", "#b77fc4"),
             "dct": ("Distal convoluted tubule", "Distal nephron", "#78b98f"),
             "cnt": ("Connecting tubule", "Distal nephron", "#6fb3b0")}
    cells = {"pct": (0.036, 0.0045, 1.3, 0.0035), "pst": (0.036, 0.004, 1.4, 0.0025),
             "tdl": (0.040, 0.0018, 2.2, 0.0), "tal_thin": (0.040, 0.0018, 2.2, 0.0),
             "tal": (0.028, 0.0030, 1.3, 0.0), "dct": (0.030, 0.0032, 1.1, 0.0), "cnt": (0.030, 0.0030, 1.1, 0.0)}
    start = 11                                  # the first points are the capsule neck
    walls = {}
    for k, key in enumerate(order):
        a = max(bounds[k], start)
        b = bounds[k + 1] + 1 if k < len(order) - 1 else len(path)
        seg = path[a:min(b, len(path))]
        if key == "cnt":
            seg = seg[:-9]                      # the last stretch is merged into the collecting duct
        ro, ri = calibre[key]
        if key in ("pst", "dct", "cnt"):         # these segments take over gradually rather than with a step
            prev = calibre[order[k - 1]]
            w = np.clip(np.arange(len(seg)) / 8.0, 0.0, 1.0)
            ro, ri = prev[0] + (ro - prev[0]) * w, prev[1] + (ri - prev[1]) * w
        c, amp, asp, brush = cells[key]
        sw, mesh = _wall(seg, ri, ro, 101 + 7 * k, cell=c, amp=amp, aspect=asp, brush=brush,
                         n_theta=64 if np.max(ro) > 0.03 else 36)
        walls[key] = seg
        name, group, colour = names[key]
        cat = "serosa" if key in ("tdl", "tal_thin") else "organ"
        parts.append(mesh_part(mesh, name, group, colour, DESC[key], cat,
                               detail=(0.08, 150.0 if np.max(ro) > 0.03 else 190.0, 0.9, 0)))

    # ---- collecting ducts (one field, so the ducts and the connecting tubule merge with open lumens)
    lo = np.array([0.62, Y_BOT - 0.01, -0.62])
    hi = np.array([X_HI, Y_TOP + 0.01, 0.0])
    cdv = Volume(lo, hi, 0.0065)
    cdi = Volume(lo, hi, 0.0065)
    cdv.tube(cd_main, cd_r)
    cdi.tube(cd_main, cd_r * 0.66)
    cdv.tube(cd_side, 0.052, "smooth", 0.05)
    cdi.tube(cd_side, 0.052 * 0.64, "smooth", 0.03)
    cnt_end = path[-11:]
    cdv.tube(cnt_end, calibre["cnt"][0], "smooth", 0.03)
    cdi.tube(np.vstack([cnt_end, cd_main[np.argmin(np.linalg.norm(cd_main - path[-1], axis=1))]]),
             calibre["cnt"][1], "smooth", 0.012)
    x, y, z = cdv.axes()
    relief = cell_lattice(x, y, z, 0.030, 0.0022, seed=21)
    wall = np.maximum(cdv.d - relief * 0.25, -(cdi.d + relief))
    wall = np.maximum(wall, np.maximum(Y_BOT - y, y - Y_TOP))
    y_b = np.broadcast_to(y, wall.shape)
    for name, mask, key, colour in (("Cortical collecting duct", y_b >= Y_CM, "ccd", "#8fb8e0"),
                                    ("Medullary collecting duct", y_b < Y_CM, "mcd", "#6f9fd3")):
        v = cdv.copy(np.where(mask, wall, np.maximum(wall, 0.004)))
        parts.append(sdf_part(v, name, "Collecting duct", colour, DESC[key], "organ", smooth=0.8,
                              detail=(0.08, 120.0, 0.9, 2)))

    # ---- vessels
    parts.append(mesh_part(_vessel_wall(arca, 0.040, 0.070, 57, n_theta=64), "Arcuate artery", "Vessels",
                           "#b8322a", DESC["arca"], "artery", detail=(0.06, 120.0, 0.6, 4)))
    parts.append(mesh_part(_vessel_wall(arcv, 0.072, 0.085, 59, n_theta=64), "Arcuate vein", "Vessels",
                           "#44529e", DESC["arcv"], "vein", detail=(0.06, 100.0, 0.4, 0)))
    parts.append(mesh_part(_vessel_wall(cra, 0.026, 0.050, 61, n_theta=56), "Cortical radiate artery", "Vessels",
                           "#c43a30", DESC["cra"], "artery", detail=(0.06, 120.0, 0.6, 4)))
    parts.append(mesh_part(_vessel_wall(crv, 0.046, 0.058, 63, n_theta=56), "Cortical radiate vein", "Vessels",
                           "#4f5fae", DESC["crv"], "vein", detail=(0.06, 100.0, 0.4, 0)))
    parts.append(_peritubular(rng, walls, calibre, eff, crv, cd_main, cd_r))
    dvr, avr = Mesh(), Mesh()
    for p in vr_d:
        dvr.extend(_capillary(p, 0.0105, 10))
    for p in vr_a:
        avr.extend(_capillary(p, 0.0135, 10))
    parts.append(mesh_part(dvr, "Descending vasa recta", "Vessels", "#cf3f3a", DESC["dvr"], "artery"))
    parts.append(mesh_part(avr, "Ascending vasa recta", "Vessels", "#7b58a8", DESC["avr"], "vein"))

    parts += _zones()
    return settle(parts, seed=502, amp_xz=0.018, amp_y=0.03, freq=1.2, shear=0.006, grain=0.0018, micro=0.0010)


def _peritubular(rng, walls, calibre, eff, crv, cd_main, cd_r):
    """A net of capillaries draped over the cortical tubules: nodes scattered on a sleeve just outside each wall,
    joined to their nearest neighbours by vessels that bow outward around the tubule instead of cutting through."""
    centre_pts, centre_r = [], []
    for key in ("pct", "pst", "tal", "dct", "cnt"):
        p = walls[key]
        centre_pts.append(p)
        centre_r.append(np.full(len(p), calibre[key][0]))
    centre_pts.append(cd_main)
    centre_r.append(cd_r)
    C = np.vstack(centre_pts)
    Cr = np.concatenate(centre_r)
    ctree = cKDTree(C)
    nodes = []
    for key in ("pct", "pst", "tal", "dct", "cnt"):
        p = walls[key]
        ro = calibre[key][0]
        t = np.gradient(p, axis=0)
        t /= np.linalg.norm(t, axis=1, keepdims=True)
        for i in range(0, len(p), 5):
            if p[i, 1] < Y_CM - 0.05:
                continue
            for _ in range(2):
                v = rng.normal(size=3)
                v -= t[i] * np.dot(v, t[i])
                v /= np.linalg.norm(v)
                nodes.append(p[i] + v * (ro + 0.016))
    nodes = np.array(nodes)
    # thin out to an even spacing, dropping any node that sits inside another tubule or the capsule
    d, j = ctree.query(nodes)
    ok = (d > Cr[j] + 0.010) & (np.linalg.norm(nodes - GC, axis=1) > R_CAP_OUT + 0.02)
    nodes = nodes[ok]
    keep = []
    tree = cKDTree(nodes)
    taken = np.zeros(len(nodes), bool)
    for i in rng.permutation(len(nodes)):
        if taken[i]:
            continue
        keep.append(i)
        taken[tree.query_ball_point(nodes[i], 0.050)] = True
    nodes = nodes[keep]
    tree = cKDTree(nodes)
    m = Mesh()
    edges = set()
    for i, p in enumerate(nodes):
        dd, jj = tree.query(p, 5)
        for dist, j in zip(dd[1:], jj[1:]):
            if dist < 0.12 and (min(i, j), max(i, j)) not in edges:
                edges.add((min(i, j), max(i, j)))
    t = np.linspace(0.0, 1.0, 9)[:, None]
    kept = []
    for i, j in edges:
        a, b = nodes[i], nodes[j]
        seg = a + (b - a) * t
        # drape the vessel over the tubule it runs on: every point is pulled onto the sleeve just outside the
        # nearest wall, so the net hugs the tubules instead of cutting chords across them
        dist, k = ctree.query(seg[1:-1])
        sleeve = Cr[k] + 0.013
        out = seg[1:-1] - C[k]
        on = C[k] + out / (np.linalg.norm(out, axis=1, keepdims=True) + 1e-9) * sleeve[:, None]
        w = np.clip(1.0 - (dist - sleeve) / 0.05, 0.0, 1.0)[:, None]
        seg[1:-1] = seg[1:-1] * (1 - w) + on * w + rng.normal(scale=0.003, size=(7, 3))
        seg = smooth_path(seg, 13)
        dd, kk = ctree.query(seg)
        if np.any(dd < Cr[kk] + 0.004) or np.any(np.linalg.norm(seg - GC, axis=1) < R_CAP_OUT + 0.012):
            continue
        kept.append((i, j, seg))
    # prune dead ends, so every vessel of the net runs from one junction to another
    while True:
        deg = np.zeros(len(nodes), int)
        for i, j, _ in kept:
            deg[i] += 1
            deg[j] += 1
        nxt = [e for e in kept if deg[e[0]] > 1 and deg[e[1]] > 1]
        if len(nxt) == len(kept):
            break
        kept = nxt
    for _, _, seg in kept:
        m.extend(_capillary(seg, 0.0065, 7))
    for p in nodes[deg > 1]:
        m.extend(ellipsoid_mesh(p, (0.0072, 0.0072, 0.0072), 7))
    # the efferent arteriole feeds the net, and the net drains into the cortical radiate vein
    for src, count in ((eff[len(eff) // 3: len(eff) * 2 // 3: 6], 1), (crv[::10], 1)):
        for q in src:
            dd, jj = tree.query(q, count)
            jj = np.atleast_1d(jj)
            for j in jj:
                if np.linalg.norm(nodes[j] - q) < 0.15:
                    bend = rng.normal(scale=0.02, size=3)
                    m.extend(_capillary(smooth_path(np.array([q, (q * 2 + nodes[j]) / 3 + bend,
                                                              (q + nodes[j] * 2) / 3 + bend * 0.5, nodes[j]]),
                                                    14), 0.0075, 8))
    return mesh_part(m, "Peritubular capillaries", "Vessels", "#d8433b", DESC["ptc"], "artery", label=True)


def _zones():
    """A backdrop showing which zone of the kidney each segment lies in: cortex, the outer and inner stripes of the
    outer medulla, and the inner medulla."""
    lo = np.array([X_LO, Y_BOT, Z_BACK - 0.05])
    hi = np.array([X_HI, Y_TOP, Z_BACK + 0.02])
    v = Volume(lo - 0.02, hi + 0.02, 0.016)
    x, y, z = v.axes()
    front = (z - (Z_BACK + 0.006 * np.sin(x * 9.0 + y * 3.0))).astype(np.float32)
    back = (Z_BACK - 0.045) - z
    d = np.maximum(front, back)
    d = np.maximum(d, np.maximum(np.maximum(X_LO - x, x - X_HI), np.maximum(Y_BOT - y, y - Y_TOP)))
    d = d - cell_lattice(x, y, z, 0.09, 0.005, seed=31)
    d = np.broadcast_to(d, v.shape).astype(np.float32)
    yb = np.broadcast_to(y, v.shape)
    out = []
    for name, y0, y1, colour, key in (("Cortex", Y_CM, 9.0, "#8a4a42", "cortex"),
                                     ("Outer medulla – outer stripe", Y_OS, Y_CM, "#9a5f55", "os"),
                                     ("Outer medulla – inner stripe", Y_IS, Y_OS, "#a8766a", "is"),
                                     ("Inner medulla", -9.0, Y_IS, "#b79184", "im")):
        mask = (yb >= y0) & (yb < y1)
        # a narrow groove marks each boundary
        zv = v.copy(np.where(mask, d, np.maximum(d, 0.004)))
        out.append(sdf_part(zv, name, "Kidney zones", colour, DESC[key], "fascia", smooth=0.8, clip=False,
                            rank=-1, alpha=0.6, detail=(0.10, 50.0, 0.3, 0)))
    return out
