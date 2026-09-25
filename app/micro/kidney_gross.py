"""The kidney in coronal section: a whole right kidney with its coverings, opened along its frontal plane.

Unlike the other micro models this is gross anatomy (1 unit = 5 cm, the kidney is ~11 cm long), built the same way
as the lymph node: every zone is carved from signed-distance fields of one body, so capsule, cortex, columns,
pyramids and papillae nest exactly and the coronal cut-away (the anterior half is removed) sections them together,
the way a kidney is bisected in the dissection room.

Layout: +y superior, +x medial (the hilum), -x lateral, +z anterior. The cut plane is z = 0. The structures that the
section is meant to show - pyramids, calyces, pelvis, the interlobar-arcuate-cortical radiate vessels, medullary
rays and striations - are laid out in or across that plane; the rest of the kidney stays whole behind it.
"""
import math

import numpy as np
from scipy import ndimage

from .geometry import Mesh, ellipsoid as ellipsoid_mesh, smooth_path, tube
from .kit import Volume, ellipsoid as ellipsoid_sdf, mesh_part, round_cone
from .sdf import fbm3, smin

VOX = 0.012                                    # kidney parenchyma and collecting system
T_CAP = 0.028                                  # fibrous capsule (exaggerated ~2x)
T_C = 0.175                                    # depth of the corticomedullary junction (cortex ~1 cm)
K_LO, K_HI = np.array([-0.95, -1.98, -0.44]), np.array([0.80, 1.25, 0.44])
KR = (0.64, 1.12, 0.39)                        # kidney semi-axes before bending
SIN_C, SIN_R = np.array([0.13, 0.0, 0.0]), np.array([0.30, 0.62, 0.17])
PLANE_Z = -0.004                               # structures drawn "in" the section sit just behind the cut

DESC = {
    "fascia": "Renal fascia (Gerota fascia): a condensation of extraperitoneal connective tissue that encloses the "
              "kidney, its perirenal fat and the suprarenal gland. Its anterior and posterior layers fuse above the "
              "suprarenal gland and laterally, but stay open inferiorly along the ureter and blend medially with the "
              "sheaths of the renal vessels. It anchors the kidney to the posterior abdominal wall; outside it lies "
              "the pararenal fat, and anterior to it the parietal peritoneum - the kidney is retroperitoneal. "
              "Clinically it confines perirenal haematomas, abscesses and early renal cell carcinoma (a tumour "
              "breaching it is stage T4), while the open lower end lets perirenal fluid or pus track down towards "
              "the pelvis.",
    "fat": "Perirenal fat (adipose capsule): the fat inside the renal fascia, thickest at the borders and poles. It "
           "cushions the kidney and helps hold it in place; it is continuous through the hilum with the fat of the "
           "renal sinus. When it is lost (rapid weight loss, cachexia) the kidney can drop - nephroptosis - and "
           "kink its ureter. It shows as a dark rim on CT that tumour or inflammation 'strands' into.",
    "capsule": "Fibrous (renal) capsule: a thin, tough layer of dense connective tissue (collagen with some elastic "
               "fibres and myofibroblasts) adherent to the cortex. In the healthy kidney it strips off easily; it "
               "sticks and roughens where the cortex is scarred. At the hilum it turns inwards to line the renal "
               "sinus and blends with the adventitia of the calyces and vessels. It barely stretches, so acute "
               "swelling (pyelonephritis, obstruction) stretches it painfully - loin pain and costovertebral-angle "
               "tenderness - and a subcapsular haematoma can compress the parenchyma (Page kidney).",
    "cortex": "Renal cortex: the outer, granular, reddish-brown zone about 1 cm thick, between the capsule and the "
              "bases of the pyramids. It contains all the renal corpuscles (glomeruli) and the convoluted tubules - "
              "the cortical labyrinth - and receives about 90 % of renal blood flow. It filters ~180 L of plasma a "
              "day and makes renin and erythropoietin. Cortical thinning on ultrasound marks chronic kidney "
              "disease; renal cell carcinoma arises from the proximal tubules here. Histology: kidney cortex.",
    "columns": "Renal columns (of Bertin): extensions of cortical tissue that dip down between neighbouring pyramids "
               "as far as the renal sinus. The interlobar arteries and veins run in them. An unusually large column "
               "can look like a mass on ultrasound (a 'pseudotumour' - column of Bertin hypertrophy).",
    "rays": "Medullary rays: pale radial striations running from the base of each pyramid out into the cortex. Each is "
            "a bundle of straight tubules - collecting ducts and the straight parts of proximal and distal tubules "
            "- so the medulla continues into the cortex along them. A ray with the cortical labyrinth around it "
            "forms a renal lobule, drained by one collecting duct system and centred between two cortical radiate "
            "arteries.",
    "pyramids": "Renal pyramids: the renal medulla is made of 8-18 of these cone-shaped masses. Each base faces the "
                "cortex at the corticomedullary junction (marked by the arcuate vessels); each apex forms a "
                "papilla pointing into the sinus. They look darker and striated because they are packed with "
                "parallel nephron loops, collecting ducts and vasa recta. Their countercurrent multiplier builds a "
                "gradient from ~300 mOsm/kg at the base to ~1200 at the papilla, which lets ADH concentrate the "
                "urine. A pyramid with its covering cortex (half of each adjacent column) is a renal lobe. "
                "Histology: kidney medulla.",
    "striations": "Medullary striations: the streaks that make a cut pyramid look striped - straight collecting "
                  "ducts, nephron loops and bundles of vasa recta all running from base to papilla. Medullary "
                  "sponge kidney dilates these collecting ducts into small cysts that grow stones.",
    "papillae": "Renal papillae: the rounded tips of the pyramids, projecting into the minor calyces. Each is "
                "pierced by 10-25 openings of the papillary ducts (ducts of Bellini) - the area cribrosa - "
                "through which urine drips into the calyx. The papilla has the most concentrated interstitium "
                "and the poorest blood supply in the kidney, so it can die: papillary necrosis in analgesic "
                "(NSAID) abuse, diabetes, sickle cell disease and severe pyelonephritis, with sloughed papillae "
                "passing as clots or blocking the ureter. Papillae are also where Randall plaques seed calcium "
                "stones.",
    "minor": "Minor calyces: 7-14 cup-shaped tubes of urothelium-lined wall, each fitting round one papilla (or a "
             "compound papilla at a pole) and attached round its base at the fornix. They collect urine from the "
             "papillary ducts; smooth muscle in their walls starts the peristalsis that drives urine to the ureter. "
             "The fornix is the weak point where the calyx tears in acute obstruction, leaking urine into the sinus.",
    "major": "Major calyces: two or three (superior, middle, inferior) wider tubes (infundibula), each formed by the "
             "union of 2-4 minor calyces and opening into the renal pelvis. A staghorn calculus fills the pelvis "
             "and branches into the major and minor calyces like antlers; obstruction balloons them "
             "(hydronephrosis: 'clubbed' calyces on imaging).",
    "pelvis": "Renal pelvis: the funnel-shaped expansion of the upper ureter, formed by the major calyces and lying "
              "in the renal sinus 'like a glove in a pocket'. Its wall is urothelium, smooth muscle and adventitia; "
              "it narrows at the pelviureteric junction, the first of the ureter's three narrowings where stones "
              "lodge (then the pelvic brim and the vesicoureteric junction). A stone in the pelvis may be silent, "
              "but a stone that impacts at the junction causes colic and hydronephrosis. Pyelonephritis is an "
              "infection ascending from the bladder into the pelvis and on up the collecting ducts into the "
              "parenchyma. Urothelial (transitional cell) carcinoma can arise here as in the bladder.",
    "ureter": "Ureter (proximal part): a muscular tube ~25-30 cm long and 3-4 mm wide, running retroperitoneally on "
              "psoas from the pelviureteric junction to the bladder. Its wall has urothelium on a lamina propria "
              "(folded into a star-shaped lumen), smooth muscle (inner longitudinal, outer circular in the upper "
              "two-thirds) and adventitia; peristaltic waves (1-5 a minute), not gravity, move urine. It is "
              "supplied segmentally (renal, gonadal, iliac and vesical arteries). Stones stuck in it cause "
              "colic radiating from loin to groin. Histology: ureter.",
    "sinus": "Renal sinus fat: the renal sinus is the space inside the kidney that opens at the hilum. It holds the "
             "renal pelvis and calyces, the branches of the renal vessels, lymphatics and nerves, all packed in "
             "fat continuous with the perirenal fat. Sinus fat increases with age and obesity (renal sinus "
             "lipomatosis). Renal cell carcinoma that invades sinus fat has access to the veins and lymphatics "
             "and is upstaged (T3a).",
    "hilum": "Hilum of kidney: the vertical slit on the concave medial border, at about L1, through which the "
             "structures of the renal sinus enter and leave. From anterior to posterior: renal vein, renal "
             "artery, renal pelvis ('VAP' - vein, artery, pelvis/ureter); lymphatics and autonomic nerves come "
             "with them. The left hilum lies a little higher than the right because the liver pushes the right "
             "kidney down.",
    "a_renal": "Renal artery: a lateral branch of the abdominal aorta at L1-L2; the kidneys receive ~20-25 % of the "
               "cardiac output (about 1.2 L/min). The right artery is longer and passes behind the inferior vena "
               "cava. Accessory (polar) arteries are common (~25-30 %) and are end arteries. Stenosis - "
               "atherosclerosis in the elderly, fibromuscular dysplasia in young women - lowers perfusion, "
               "activates renin-angiotensin and causes renovascular hypertension; ACE inhibitors can then drop GFR "
               "sharply. Near the hilum it splits into anterior and posterior divisions.",
    "a_seg": "Segmental arteries: five branches in the renal sinus - superior (apical), anterosuperior, "
             "anteroinferior and inferior from the anterior division, and posterior from the posterior division "
             "(running behind the pelvis; shown out of the plane of section). They are end arteries with no "
             "anastomoses, so the kidney has vascular segments that can be resected separately, and blocking one "
             "(embolus) causes a wedge-shaped infarct. The avascular plane (Brödel line) between anterior and "
             "posterior territories, just behind the lateral border, is where surgeons open the kidney.",
    "a_ilob": "Interlobar arteries: branches of the segmental arteries that leave the sinus beside the papillae and "
              "run outwards through the renal columns, between the pyramids (between the lobes, hence the name), "
              "to the corticomedullary junction.",
    "a_arc": "Arcuate arteries: arch over the bases of the pyramids at the corticomedullary junction, running "
             "parallel to the kidney surface. They are end arteries that do not anastomose with each other, and "
             "they mark the border between cortex and medulla in a section. On ultrasound calcified arcuate "
             "arteries in diabetes show as bright dots at the junction.",
    "a_crad": "Cortical radiate (interlobular) arteries: run from the arcuate arteries straight out through the "
              "cortex towards the capsule, between the medullary rays. They give off the afferent arterioles, one "
              "to each glomerulus; the efferent arterioles then form the peritubular capillaries (and, from "
              "juxtamedullary glomeruli, the vasa recta) - two capillary beds in series. Sequence: renal → "
              "segmental → interlobar → arcuate → cortical radiate → afferent arteriole → glomerulus.",
    "v_renal": "Renal vein: formed at the hilum, lies anterior to the artery and drains into the inferior vena cava. "
               "The left renal vein is three times longer, crosses in front of the aorta just below the superior "
               "mesenteric artery (where it can be compressed - nutcracker syndrome) and receives the left gonadal "
               "and left suprarenal veins; so a left varicocele that appears suddenly in an older man can signal a "
               "left renal tumour. Renal cell carcinoma characteristically grows along it as a tumour thrombus, "
               "even into the vena cava and right atrium; renal vein thrombosis complicates the nephrotic "
               "syndrome (especially membranous nephropathy).",
    "v_seg": "Sinus (segmental) veins: large tributaries in the renal sinus that join to form the renal vein. Unlike "
             "the arteries, renal veins anastomose freely and are not segmental, so a vein branch can be tied "
             "without venous infarction.",
    "v_ilob": "Interlobar veins: run beside the interlobar arteries in the renal columns, collecting the arcuate "
              "veins and draining to the sinus veins.",
    "v_arc": "Arcuate veins: arch over the pyramid bases alongside the arcuate arteries; unlike the arteries they "
             "form anastomosing arches. They receive the cortical radiate veins and the ascending vasa recta.",
    "v_crad": "Cortical radiate (interlobular) veins: drain the peritubular capillaries of the cortex (and the "
              "stellate veins just under the capsule) back to the arcuate veins. Venous return: peritubular "
              "capillaries → cortical radiate → arcuate → interlobar → sinus veins → renal vein.",
    "wedge": "Nephron position (lobule wedge): a window cut into one renal lobe to show where a single nephron and "
             "its collecting duct lie, drawn many times larger than life (a nephron is ~50 µm wide; each kidney "
             "has about a million). The renal corpuscle and convoluted tubules sit in the cortex; the nephron loop "
             "dips into the pyramid - only a short way for the ~85 % cortical nephrons, deep towards the papilla "
             "for the ~15 % juxtamedullary nephrons that build the concentration gradient. Open the 'Nephron & "
             "renal corpuscle' model to see its microanatomy.",
    "corpuscle": "Renal corpuscle: the glomerulus (a capillary tuft fed by an afferent arteriole from a cortical "
                 "radiate artery) inside the glomerular (Bowman) capsule. It filters plasma into the capsular space "
                 "- the start of the nephron. Corpuscles lie only in the cortex, which is why the cortex looks "
                 "granular; this one sits deep in the cortex, as a juxtamedullary nephron's does.",
    "tubule": "Nephron tubule: proximal convoluted tubule (reabsorbs ~65 % of the filtrate: all the glucose and "
              "amino acids, most Na+, water and bicarbonate) → nephron loop, descending and ascending limbs "
              "(countercurrent multiplier) → back to its own corpuscle (macula densa, juxtaglomerular apparatus) "
              "→ distal convoluted tubule (Na+ and Ca2+ reabsorption; thiazide target) → connecting tubule to a "
              "collecting duct.",
    "cd": "Collecting duct: receives many nephrons, runs down a medullary ray and straight through the pyramid, "
          "and opens as a papillary duct on the tip of the papilla. ADH (aquaporin-2) makes it permeable to water "
          "as it crosses the hypertonic medulla, which concentrates the urine; aldosterone acts on its principal "
          "cells (Na+ in, K+ out). Nephrogenic diabetes insipidus (lithium, V2 receptor mutations) blocks this.",
    "adr_cortex": "Suprarenal gland - cortex: the golden-yellow outer part (the colour is its cholesterol-rich "
                  "lipid) of the right suprarenal gland, a small pyramid capping the upper pole inside the renal "
                  "fascia but in its own compartment, separated from the kidney by fat - so it stays behind when "
                  "a kidney drops or is removed. Zona glomerulosa makes aldosterone, fasciculata cortisol, "
                  "reticularis androgens. Excess: Conn syndrome (aldosterone - hypertension, hypokalaemia), Cushing "
                  "syndrome (cortisol); failure: Addison disease. Its three arteries (superior, middle, inferior "
                  "suprarenal - the last from the renal artery) contrast with a single vein. Histology: adrenal.",
    "adr_medulla": "Suprarenal gland - medulla: the reddish-brown core, modified sympathetic postganglionic neurons "
                   "(chromaffin cells) that release adrenaline and noradrenaline into the blood when stimulated by "
                   "preganglionic splanchnic fibres. A phaeochromocytoma arising here causes episodic "
                   "hypertension, headache, sweating and palpitations.",
}


# =============================================================================== fields
def _ell(x, y, z, c, r):
    """Approximate signed distance to an axis-aligned ellipsoid."""
    px, py, pz = x - c[0], y - c[1], z - c[2]
    k0 = np.sqrt((px / r[0]) ** 2 + (py / r[1]) ** 2 + (pz / r[2]) ** 2)
    k1 = np.sqrt((px / r[0] ** 2) ** 2 + (py / r[1] ** 2) ** 2 + (pz / r[2] ** 2) ** 2)
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)


def kidney_sdf(x, y, z):
    """The bean: an ellipsoid bowed laterally at its middle, with a smooth notch for the hilum on the medial side.
    The upper pole is a little broader and thicker than the lower, as in most kidneys."""
    yc = np.clip(y / KR[1], -1.0, 1.0)
    xb = x + 0.10 * (1.0 - yc * yc)
    sc = 1.0 + 0.05 * yc                                           # upper pole fuller
    e = _ell(xb / sc, y, z / sc, (0.0, 0.0, 0.0), KR) * sc
    notch = _ell(x, y, z, (0.84, -0.03, 0.0), (0.30, 0.40, 0.62))
    return -smin(-e, notch, 0.12)


def sinus_sdf(x, y, z):
    """The renal sinus: the space inside the kidney that opens medially through the hilum."""
    s = _ell(x, y, z, SIN_C, SIN_R)
    ch = _ell(x, y, z, (0.58, -0.06, 0.0), (0.44, 0.34, 0.135))
    return smin(s, ch, 0.09)


class Field:
    """A scalar grid with trilinear lookup and gradient, used to route vessels and tubes along depth contours."""

    def __init__(self, vol, d):
        self.lo, self.vox, self.d = vol.lo, vol.voxel, d

    def __call__(self, p):
        p = np.atleast_2d(np.asarray(p, float))
        idx = ((p - self.lo) / self.vox).T
        return ndimage.map_coordinates(self.d, idx, order=1, mode="nearest")

    def grad(self, p, eps=0.006):
        p = np.atleast_2d(np.asarray(p, float))
        g = np.zeros_like(p)
        for c in range(3):
            a, b = p.copy(), p.copy()
            a[:, c] += eps
            b[:, c] -= eps
            g[:, c] = (self(a) - self(b)) / (2 * eps)
        return g


def _crop_mesh(vol, d, smooth=0.9, step=1, pad=4):
    """Polygonise a field over the bounding box of its interior only (fast for small parts in a big grid)."""
    inside = np.argwhere(d < 0)
    if not len(inside):
        return Mesh()
    i0 = np.maximum(inside.min(0) - pad * step, 0)
    i1 = np.minimum(inside.max(0) + pad * step + 1, d.shape)
    sub = Volume.__new__(Volume)
    sub.voxel = vol.voxel
    sub.lo = vol.lo + i0 * vol.voxel
    sub.d = np.ascontiguousarray(d[i0[0]:i1[0], i0[1]:i1[1], i0[2]:i1[2]])
    sub.shape = sub.d.shape
    sub._slices = None
    return sub.mesh(smooth, step=step)


def _part(vol, d, name, group, color, desc, category="organ", smooth=0.9, step=1, **kw):
    return mesh_part(_crop_mesh(vol, d, smooth, step), name, group, color, desc, category, **kw)


def _minus(f, *others, margin=0.0):
    out = f.copy()
    for o in others:
        np.maximum(out, -(o - margin), out=out)
    return out


def _edt_depth(mask, vox):
    """Exact distance (world units) from every inside voxel to the outside."""
    return (ndimage.distance_transform_edt(mask) * vox).astype(np.float32)


# =============================================================================== pyramids
class Pyramid:
    def __init__(self, phi, depth):
        """A renal pyramid whose papilla points into the sinus at parametric angle phi (degrees from lateral,
        positive upwards) on the sinus ellipse; its axis is the ellipse normal there."""
        f = math.radians(phi)
        self.phi = phi
        c, s = math.cos(f), math.sin(f)
        wall = SIN_C + np.array([-SIN_R[0] * c, SIN_R[1] * s, 0.0])
        n = np.array([-c / SIN_R[0], s / SIN_R[1], 0.0])
        n /= np.linalg.norm(n)
        radial = wall - SIN_C
        radial /= np.linalg.norm(radial)
        a = n * 0.7 + radial * 0.3
        a /= np.linalg.norm(a)
        self.a = a
        self.e = np.cross(np.array([0.0, 0.0, 1.0]), a)          # in-plane, perpendicular to the axis
        self.zax = np.array([0.0, 0.0, 1.0])
        self.A = wall - a * 0.015 + np.array([0.0, 0.0, PLANE_Z])  # centre of the papillary dome
        self.rh = 0.065                                            # dome reaches this far below A
        self.tip = self.A - a * self.rh
        # length to the corticomedullary junction along the axis
        L = 0.0
        for t in np.arange(0.0, 0.8, 0.004):
            if depth(self.A + a * t)[0] < T_C:
                L = t
                break
        self.L = L
        self.base = self.A + a * L
        self.w = 0.2
        self.dz = 0.30
        self.rp = 0.30

    def shape(self):
        A, a, e, zax = self.A, self.a, self.e, self.zax
        L, w, dz, rp, rh = self.L, self.w, self.dz, self.rp, self.rh
        corners = [A + a * h + e * sw * w * 1.5 + zax * sz * dz * 1.2 for h in (-rh - 0.02, L + 0.25)
                   for sw in (-1, 1) for sz in (-1, 1)]
        bmin, bmax = np.min(corners, 0), np.max(corners, 0)

        def f(x, y, z):
            px, py, pz = x - A[0], y - A[1], z - A[2]
            h = px * a[0] + py * a[1] + pz * a[2]
            s = px * e[0] + py * e[1] + pz * e[2]
            t = pz
            g = rp + (1.0 - rp) * np.clip(h / L, 0.0, None) ** 0.75
            ws, ts = w * g, dz * g
            q = np.sqrt((s / ws) ** 2 + (t / ts) ** 2)
            body = np.maximum((q - 1.0) * np.minimum(ws, ts), -h)
            dq0 = np.sqrt((s / (rp * w)) ** 2 + (t / (rp * dz)) ** 2 + (h / rh) ** 2)
            dome = (dq0 - 1.0) * min(rp * w, rh)
            return smin(body, dome, 0.03)
        return f, bmin, bmax

    def h_of(self, x, y, z):
        return (x - self.A[0]) * self.a[0] + (y - self.A[1]) * self.a[1] + (z - self.A[2]) * self.a[2]

    def at(self, h, u, z=PLANE_Z):
        """Point on the pyramid's midplane: h along the axis, u in [-1, 1] across its width."""
        g = self.rp + (1.0 - self.rp) * max(h / self.L, 0.0) ** 0.75
        p = self.A + self.a * h + self.e * u * self.w * g
        p[2] = z
        return p


PHIS = (-124, -93, -62, -31, 0, 31, 62, 93, 122)
GROUP_OF = {-124: "inf", -93: "inf", -62: "inf", -31: "mid", 0: "mid", 31: "mid", 62: "sup", 93: "sup", 122: "sup"}


def _fit_widths(pyrs):
    """Size each pyramid so the renal columns between neighbours stay ~1 cm wide at the base."""
    bases = [p.base for p in pyrs]
    for i, p in enumerate(pyrs):
        gaps = [np.linalg.norm(bases[i] - bases[j]) for j in (i - 1, i + 1) if 0 <= j < len(pyrs)]
        p.w = float(np.clip(0.5 * min(gaps) - 0.012, 0.10, 0.32))


def _project_to_depth(depth, p, target, iters=12, zlock=True):
    """Slide points along the depth gradient onto the contour depth == target (in their own z plane unless
    zlock is off)."""
    p = np.atleast_2d(np.asarray(p, float)).copy()
    for _ in range(iters):
        g = depth.grad(p)
        if zlock:
            g[:, 2] = 0.0
        gn = np.maximum((g * g).sum(1), 1e-6)
        p -= ((depth(p) - target) / gn)[:, None] * g
    return p


# =============================================================================== small geometry helpers
def _tri_sdf(px, py, v0, v1, v2):
    """Exact signed distance to a 2D triangle (negative inside)."""
    def comp(pa, pb):
        ex, ey = pb[0] - pa[0], pb[1] - pa[1]
        vx, vy = px - pa[0], py - pa[1]
        t = np.clip((vx * ex + vy * ey) / (ex * ex + ey * ey), 0.0, 1.0)
        qx, qy = vx - ex * t, vy - ey * t
        return qx * qx + qy * qy, vx * ey - vy * ex
    s = np.sign((v1[0] - v0[0]) * (v0[1] - v2[1]) - (v1[1] - v0[1]) * (v0[0] - v2[0]))
    d0, c0 = comp(v0, v1)
    d1, c1 = comp(v1, v2)
    d2, c2 = comp(v2, v0)
    d = np.minimum(np.minimum(d0, d1), d2)
    c = np.minimum(np.minimum(s * c0, s * c1), s * c2)
    return -np.sqrt(d) * np.sign(c)


ADR = ((-0.30, 1.10), (0.44, 0.98), (0.12, 1.80))     # right suprarenal gland: lateral, medial, apex (x, y)
ADR_Z = -0.012


def _adr_zc(x, y):
    """Mid-surface of the gland: its apex leans forwards and its limbs curl back round the pole."""
    return ADR_Z + 0.05 * np.clip((y - 1.05) / 0.7, 0.0, 1.0) - 0.04 * np.clip((x - 0.1) / 0.3, -1.0, 1.0) ** 2


def adrenal_sdf(x, y, z):
    """Right suprarenal gland: a flattened pyramid capping the upper pole, separated from it by a film of fat."""
    tri = _tri_sdf(x, y, *ADR) - 0.03
    inner = np.clip(-tri / 0.18, 0.0, 1.0)
    half = 0.02 + 0.075 * np.sqrt(inner)
    d = np.maximum(tri, np.abs(z - _adr_zc(x, y)) - half)
    return np.maximum(d, -(kidney_sdf(x, y, z) - 0.045))


def _smooth(path, n=None):
    path = np.asarray(path, float)
    return smooth_path(path, n or max(12, int(np.linalg.norm(np.diff(path, axis=0), axis=1).sum() / 0.012)))


def _side(path):
    """Unit in-plane perpendiculars along a path (tangent x z)."""
    t = np.gradient(path, axis=0)
    t[:, 2] = 0.0
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-9)
    return np.stack([t[:, 1], -t[:, 0], np.zeros(len(t))], -1)


def _beside(path, amount, toward=None):
    """The companion vein of an artery: the same course shifted sideways in the section plane."""
    sd = _side(path)
    if toward is not None and float(((np.asarray(toward) - path.mean(0)) * sd.mean(0)).sum()) < 0:
        sd = -sd
    return path + sd * amount


class Tree:
    """Tube meshes for one class of vessel (renal artery, segmental arteries ...)."""

    def __init__(self):
        self.mesh = Mesh()
        self.paths = []

    def add(self, path, r0, r1=None, segments=12):
        path = np.asarray(path, float)
        r = np.linspace(r0, r0 if r1 is None else r1, len(path))
        self.mesh.extend(tube(path, r, segments))
        self.paths.append((path, r))
        return path


def _march_out(depth, p, stop, step=0.012, wiggle=0.0, rng=None, zlock=True):
    """Walk from p towards the surface (against the depth gradient) until depth < stop."""
    pts = [np.array(p, float)]
    for _ in range(80):
        g = depth.grad(pts[-1])[0]
        if zlock:
            g[2] = 0.0
        g /= max(np.linalg.norm(g), 1e-9)
        q = pts[-1] - g * step
        if wiggle and rng is not None:
            sd = np.array([g[1], -g[0], 0.0])
            q += sd * rng.normal(0, wiggle)
        pts.append(q)
        if depth(q)[0] < stop:
            break
    return np.array(pts)


def _chord_on_contour(depth, a, b, target, n=14):
    pts = np.linspace(a, b, n)
    return _project_to_depth(depth, pts, target)


# =============================================================================== the model
def build_kidney_section():
    rng = np.random.default_rng(7)
    parts = []

    # ------------------------------------------------------------------ body, sinus and depth fields
    kv = Volume(K_LO, K_HI, VOX)
    x, y, z = kv.axes()
    K = np.broadcast_to(kidney_sdf(x, y, z), kv.shape).astype(np.float32).copy()
    K += 0.004 * fbm3(x * 5.0, y * 5.0, z * 5.0, 1.0, 2, 3)
    S = np.broadcast_to(sinus_sdf(x, y, z), kv.shape).astype(np.float32).copy()
    S += 0.012 * fbm3(x * 6.0 + 3, y * 6.0, z * 6.0, 1.0, 2, 5)
    depth_k = ndimage.gaussian_filter(_edt_depth(K < 0, VOX), 1.0)        # below the outer surface
    depth = Field(kv, depth_k)
    P = -smin(-K, S, 0.03)                           # parenchyma = body minus sinus
    tc = (T_C + 0.018 * fbm3(x * 9.0, y * 9.0, z * 9.0, 1.0, 2, 11)).astype(np.float32)

    # ------------------------------------------------------------------ pyramids and papillae
    pyrs = [Pyramid(phi, depth) for phi in PHIS]
    pyrs = [p for p in pyrs if p.L > 0.12]
    _fit_widths(pyrs)
    pyr_v = Volume(K_LO, K_HI, VOX)
    pap_v = Volume(K_LO, K_HI, VOX)
    for p in pyrs:
        shp = p.shape()
        pyr_v.add(shp)
        fn_, bmin, bmax = shp
        pap_v.add((lambda X, Y, Z, fn_=fn_, p=p: np.maximum(fn_(X, Y, Z), p.h_of(X, Y, Z) - 0.10), bmin, bmax))
    pyr_v.displace(0.006, 7.0, 2, seed=21)
    pyr_d = np.maximum(pyr_v.d, tc - depth_k)
    pap_d = np.maximum(pap_v.d, pyr_d)
    med_d = _minus(pyr_d, pap_d)
    del pyr_v, pap_v

    # ------------------------------------------------------------------ nephron wedge (a window cut into one lobe)
    wp = [p for p in pyrs if p.phi == -31][0]
    w_len = wp.L + T_C

    def wedge_fn(X, Y, Z, zr=(-0.075, 0.075)):
        h = wp.h_of(X, Y, Z)
        s = (X - wp.A[0]) * wp.e[0] + (Y - wp.A[1]) * wp.e[1]
        half = 0.036 + 0.10 * np.clip(h / w_len, 0.0, 1.2)
        d = np.maximum(np.abs(s) - half, -(h + wp.rh + 0.004))
        return np.maximum(d, np.maximum(zr[0] - Z, Z - zr[1]))
    wedge = np.maximum(wedge_fn(x, y, z), T_CAP + 0.004 - depth_k).astype(np.float32)

    def in_wedge(pts, margin=0.012):
        pts = np.atleast_2d(pts)
        return wedge_fn(pts[:, 0], pts[:, 1], pts[:, 2]) < margin

    # ------------------------------------------------------------------ collecting system (one field, split by label)
    cs_o = {k: Volume(K_LO, K_HI, VOX) for k in ("minor", "major", "pelvis", "ureter")}
    lumen = Volume(K_LO, K_HI, VOX)
    WALL = 0.028
    J = {"sup": np.array([0.14, 0.34, -0.02]), "mid": np.array([0.0, 0.03, -0.022]),
         "inf": np.array([0.14, -0.36, -0.025])}
    PC, UPJ = np.array([0.33, -0.08, -0.024]), np.array([0.60, -0.27, -0.022])
    for p in pyrs:
        rcup = p.rp * p.w + 0.048
        neck = p.A - p.a * 0.15
        cc, ce = p.A - p.a * 0.015, p.A + p.a * 0.07
        for vol, dr in ((cs_o["minor"], 0.0), (lumen, WALL)):
            vol.add(round_cone(neck, cc, 0.046 - dr, rcup - dr), "smooth", 0.02)
            vol.add(round_cone(cc, ce, rcup - dr, rcup * 0.92 - dr), "smooth", 0.02)
        jk = J[GROUP_OF[p.phi]]
        br = _smooth([neck, neck - p.a * 0.05, (neck - p.a * 0.05) * 0.4 + jk * 0.6, jk], 24)
        cs_o["major"].tube(br, np.linspace(0.042, 0.054, len(br)), "smooth", 0.02)
        lumen.tube(br, np.linspace(0.042, 0.054, len(br)) - WALL, "smooth", 0.02)
    for k, jk in J.items():
        tr = _smooth([jk, jk * 0.55 + PC * 0.45 + np.array([0.0, 0.0, -0.004]), jk * 0.3 + PC * 0.7], 20)
        cs_o["major"].tube(tr, np.linspace(0.056, 0.08, len(tr)), "smooth", 0.03)
        lumen.tube(tr, np.linspace(0.056, 0.08, len(tr)) - WALL, "smooth", 0.03)
    for vol, dr in ((cs_o["pelvis"], 0.0), (lumen, WALL)):
        vol.add(ellipsoid_sdf(PC, (0.17 - dr, 0.15 - dr, 0.088 - dr)), "smooth", 0.04)
        vol.add(round_cone(PC, UPJ, 0.10 - dr, 0.054 - dr), "smooth", 0.05)
    ureter_path = _smooth([UPJ - (UPJ - PC) * 0.15, UPJ, (0.68, -0.50, -0.014), (0.70, -0.92, -0.010),
                           (0.64, -1.40, -0.010), (0.58, -1.97, -0.012)], 80)
    cs_o["ureter"].tube(ureter_path, 0.052, "smooth", 0.02)
    lumen.tube(ureter_path, 0.052 - 0.031, "smooth", 0.02)
    lumen.add(round_cone(PC, UPJ, 0.10 - WALL, 0.054 - 0.031), "smooth", 0.03)
    names = list(cs_o)
    outer = cs_o["minor"].d
    for k in names[1:]:
        outer = smin(outer, cs_o[k].d, 0.03)
    wall = np.maximum(outer, -lumen.d)
    wall = _minus(wall, pyr_d, margin=0.003)
    wall = np.maximum(wall, -(P + 0.010))                    # the cups stop at the fornix, on the sinus wall
    wall = np.maximum(wall, K_LO[1] + 0.02 - y)               # cut end of the ureter
    cs_colors = {"minor": ("Minor calyces", "#e7cfbf"), "major": ("Major calyces", "#e3c7b4"),
                 "pelvis": ("Renal pelvis", "#dfc0aa"), "ureter": ("Ureter (proximal)", "#d9b89f")}
    for k in names:
        other = np.min(np.stack([cs_o[j].d for j in names if j != k]), axis=0)
        d = np.maximum(wall, (cs_o[k].d - other) * 0.5)
        nm, col = cs_colors[k]
        parts.append(_part(kv, d, nm, "Collecting system", col, DESC.get(k, ""), "mucosa", rank=-0.5, smooth=0.6,
                           detail=(0.06, 60.0, 0.05, 0)))
    cs_all = outer
    del cs_o, lumen, wall

    # ------------------------------------------------------------------ tissue zones
    cap_d = np.maximum(P, -P - T_CAP)                # a smooth band under both surfaces of the parenchyma
    cap_d = _minus(cap_d, pyr_d)
    cortex_all = P + (T_CAP - 0.004)                               # tucks just under the capsule
    cortex_all = _minus(cortex_all, pyr_d, wedge)
    cortex_d = np.maximum(cortex_all, depth_k - tc)
    column_d = np.maximum(cortex_all, tc - depth_k)
    med_d = _minus(med_d, wedge)
    pap_d = _minus(pap_d, wedge)
    sinus_fat = _minus(np.maximum(S, K), cs_all, pyr_d, margin=0.002)
    hilum_d = _minus(np.maximum(np.abs(K) - 0.010, S + 0.01), cs_all)

    parts.append(_part(kv, cap_d, "Fibrous capsule", "Coverings", "#b67f70", DESC.get("capsule", ""), "fascia",
                       rank=2, smooth=0.7, detail=(0.05, 0.0, 0.0, 0)))
    parts.append(_part(kv, cortex_d, "Renal cortex", "Renal cortex", "#a8583f", DESC.get("cortex", ""), "organ",
                       rank=1, detail=(0.12, 70.0, 0.0, 0)))
    parts.append(_part(kv, column_d, "Renal columns", "Renal cortex", "#a4553e", DESC.get("columns", ""), "organ",
                       rank=0.8, detail=(0.12, 70.0, 0.0, 0)))
    parts.append(_part(kv, med_d, "Renal pyramids", "Renal medulla", "#74292b", DESC.get("pyramids", ""), "organ",
                       rank=0.5, detail=(0.10, 50.0, 0.0, 0)))
    parts.append(_part(kv, pap_d, "Renal papillae", "Renal medulla", "#a1594f", DESC.get("papillae", ""), "organ",
                       rank=0.3, detail=(0.08, 50.0, 0.0, 0)))
    parts.append(_part(kv, sinus_fat, "Renal sinus fat", "Renal sinus & hilum", "#e9c766", DESC.get("sinus", ""),
                       "fat", rank=-1, detail=(0.07, 30.0, 0.0, 0)))
    parts.append(_part(kv, hilum_d, "Hilum of kidney", "Renal sinus & hilum", "#f2e6c8", DESC.get("hilum", ""),
                       "fascia", rank=-1.5, alpha=0.28, smooth=0.7))
    del cap_d, cortex_all, cortex_d, column_d, med_d, pap_d, sinus_fat, hilum_d, tc

    # ------------------------------------------------------------------ medullary striations and medullary rays
    stri, rays = Mesh(), Mesh()
    for p in pyrs:
        for u in np.linspace(-0.82, 0.82, 9):
            end = _project_to_depth(depth, p.at(p.L * 0.9, u * 0.97), T_C + 0.012)[0]
            mid = p.at(p.L * 0.5, u * 0.92)
            start = p.at(0.01, u * 0.85)
            path = _smooth([start, mid, end], 30)
            path[:, 2] = PLANE_Z + 0.001
            if in_wedge(path).any():
                continue
            stri.extend(tube(path, np.linspace(0.0045, 0.006, len(path)), 8))
        for u in np.linspace(-0.75, 0.75, 6):
            b = _project_to_depth(depth, p.at(p.L * 0.95, u), T_C + 0.02)[0]
            path = _march_out(depth, b, T_CAP + 0.07, step=0.012)
            path[:, 2] = PLANE_Z + 0.001
            if len(path) < 4 or in_wedge(path).any():
                continue
            path = _smooth(path, 20)
            rays.extend(tube(path, np.linspace(0.008, 0.0045, len(path)), 8))
    parts.append(mesh_part(stri, "Medullary striations", "Renal medulla", "#551c20", DESC.get("striations", ""),
                           "organ", rank=0.55, detail=(0.05, 0.0, 0.0, 0)))
    parts.append(mesh_part(rays, "Medullary rays", "Renal cortex", "#bd7a5e", DESC.get("rays", ""), "organ",
                           rank=1.05, detail=(0.05, 0.0, 0.0, 0)))

    # ------------------------------------------------------------------ blood vessels
    A = {k: Tree() for k in ("renal", "seg", "ilob", "arc", "crad")}
    V = {k: Tree() for k in ("renal", "seg", "ilob", "arc", "crad")}
    R_A = {"renal": 0.048, "seg": 0.021, "ilob": 0.0125, "arc": 0.009, "crad": 0.0052}
    R_V = {"renal": 0.068, "seg": 0.026, "ilob": 0.015, "arc": 0.0105, "crad": 0.006}
    Z_SIN = 0.008                                         # sinus branches lie just in front of the pelvis
    a_div = np.array([0.50, 0.15, Z_SIN])
    v_div = np.array([0.46, 0.02, 0.022])
    A["renal"].add(_smooth([(1.55, 0.27, -0.02), (1.10, 0.24, -0.015), (0.72, 0.19, -0.005), a_div]), 0.05, 0.046,
                   18)
    V["renal"].add(_smooth([(1.55, 0.03, 0.04), (1.05, 0.03, 0.04), (0.72, 0.02, 0.035), v_div]), 0.072, 0.066, 20)
    E = [np.array(e) for e in ((0.18, 0.45, Z_SIN), (-0.03, 0.24, Z_SIN), (-0.05, -0.20, Z_SIN),
                                (0.17, -0.46, Z_SIN))]
    Ev = [e + np.array([0.035, -0.02, 0.012]) for e in E]
    for e, ev in zip(E, Ev):
        A["seg"].add(_smooth([a_div, a_div * 0.55 + e * 0.45 + np.array([0.0, 0.04, 0.0]), e]), R_A["seg"],
                     R_A["seg"] * 0.8)
        V["seg"].add(_smooth([v_div, v_div * 0.55 + ev * 0.45 + np.array([0.0, -0.03, 0.0]), ev]), R_V["seg"],
                     R_V["seg"] * 0.85)
    # posterior segmental artery: behind the pelvis, out of the plane of section
    A["seg"].add(_smooth([a_div, (0.40, 0.10, -0.06), (0.22, 0.06, -0.13), (0.02, 0.10, -0.14)]), R_A["seg"],
                 R_A["seg"] * 0.7)

    def column(start, direction):
        pts = [np.array(start, float)]
        for _ in range(120):
            q = pts[-1] + direction * 0.01
            pts.append(q)
            if depth(q)[0] < T_C + 0.005:
                break
        return np.array(pts)

    def branch_tree(start, d, top, arc_targets, zc):
        """Interlobar artery from the sinus up a column, arcuate arteries over the neighbouring pyramid bases,
        cortical radiate arteries up to the capsule - and the companion veins beside each."""
        seg_i = int(np.argmin([np.linalg.norm(start[:2] - e[:2]) for e in E]))
        for tree, ends, r, off in ((A, E, R_A, 0.0), (V, Ev, R_V, R_A["ilob"] + R_V["ilob"] + 0.004)):
            path = _smooth([ends[seg_i], start - d * 0.09, start, top[-1]], 40)
            path[:, 2] = np.interp(np.linspace(0, 1, len(path)), [0.0, 0.3], [Z_SIN, zc])
            if off:
                path = _beside(path, off)
            tree["ilob"].add(path, r["ilob"], r["ilob"] * 0.85)
        radiate_from = [top[-1]]
        for tgt in arc_targets:
            arc = _chord_on_contour(depth, top[-1], tgt, T_C - 0.014, 12)
            arc = _smooth(np.vstack([top[-1:], arc[1:]]), 30)
            arc[:, 2] = zc
            if in_wedge(arc, 0.02).any():
                keep = ~in_wedge(arc, 0.03)
                arc = arc[:max(int(np.argmin(keep)) if not keep.all() else len(arc), 3)]
            A["arc"].add(arc, R_A["arc"], R_A["arc"] * 0.7)
            V["arc"].add(_beside(arc, R_A["arc"] + R_V["arc"] + 0.003, toward=tgt - (top[-1] - tgt)),
                         R_V["arc"], R_V["arc"] * 0.7)
            L_arc = np.linalg.norm(np.diff(arc, axis=0), axis=1).sum()
            n_r = max(1, int(L_arc / 0.075))
            cum = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(arc, axis=0), axis=1))])
            for k in range(1, n_r + 1):
                radiate_from.append(arc[int(np.searchsorted(cum, cum[-1] * k / (n_r + 0.3)))])
        radiates(radiate_from, zc)
        return top[-1]

    def radiates(points, zc=None):
        for q in points:
            path = _march_out(depth, q, T_CAP + 0.035, 0.012, 0.004, rng, zlock=zc is not None)
            if len(path) < 4 or in_wedge(path, 0.015).any():
                continue
            path = _smooth(path, 22)
            if zc is not None:
                path[:, 2] = zc
            A["crad"].add(path, R_A["crad"], R_A["crad"] * 0.6, 8)
            V["crad"].add(_beside(path, R_A["crad"] + R_V["crad"] + 0.002), R_V["crad"], R_V["crad"] * 0.6, 8)

    def arcade_3d(p, top, sz):
        """An arcuate artery arching back (or forwards) over the curved base of a pyramid, out of the plane of
        section, with its cortical radiate branches - the vascular tree is three-dimensional."""
        tgt = p.at(p.L, 0.0, z=sz * 0.20)
        arc = _project_to_depth(depth, np.linspace(top, tgt, 14), T_C - 0.014, zlock=False)
        arc = _smooth(np.vstack([top[None], arc[1:]]), 30)
        if in_wedge(arc, 0.02).any():
            return
        g = depth.grad(arc)
        g /= np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-9)
        A["arc"].add(arc, R_A["arc"], R_A["arc"] * 0.7)
        V["arc"].add(arc + g * (R_A["arc"] + R_V["arc"] + 0.003), R_V["arc"], R_V["arc"] * 0.7)
        radiates([arc[k] for k in (9, 18, 27) if k < len(arc)])

    tops = {}
    for i in range(len(pyrs) + 1):
        pa = pyrs[i - 1] if i > 0 else None
        pb = pyrs[i] if i < len(pyrs) else None
        if pa is not None and pb is not None:
            d = pa.a + pb.a
            d /= np.linalg.norm(d)
            start = (pa.A + pb.A) / 2 + d * 0.01
            targets = [pa.at(pa.L, 0.0), pb.at(pb.L, 0.0)]
        else:
            p = pa if pa is not None else pb
            other = pyrs[-2] if pa is not None else pyrs[1]
            sgn = -np.sign((other.A - p.A) @ p.e)
            start = p.at(0.02, 1.45 * sgn)
            d = p.a
            targets = [p.at(p.L, 0.0)]
        start[2] = PLANE_Z
        top = column(start, d)
        top[:, 2] = PLANE_Z
        t_end = branch_tree(start, d, top, targets, PLANE_Z)
        for p in (pa, pb):
            if p is not None and p.phi not in tops:
                tops[p.phi] = t_end
    for p in pyrs:
        for sz in (-1.0, 1.0):
            arcade_3d(p, tops[p.phi], sz)

    anames = {"renal": "Renal artery", "seg": "Segmental arteries", "ilob": "Interlobar arteries",
              "arc": "Arcuate arteries", "crad": "Cortical radiate (interlobular) arteries"}
    vnames = {"renal": "Renal vein", "seg": "Segmental (sinus) veins", "ilob": "Interlobar veins",
              "arc": "Arcuate veins", "crad": "Cortical radiate (interlobular) veins"}
    for k, t in A.items():
        parts.append(mesh_part(t.mesh, anames[k], "Arteries", "#c62e2a", DESC.get("a_" + k, ""), "artery",
                               rank=-2, detail=(0.05, 60.0, 0.2, 0)))
    for k, t in V.items():
        parts.append(mesh_part(t.mesh, vnames[k], "Veins", "#34509f", DESC.get("v_" + k, ""), "vein",
                               rank=-2.5, detail=(0.05, 60.0, 0.2, 0)))

    # ------------------------------------------------------------------ nephron and collecting duct in the wedge
    zc = -0.038

    def loc(h, s, dz=0.0):
        return wp.A + wp.a * h + wp.e * s + np.array([0.0, 0.0, zc + dz - wp.A[2]])
    L0 = wp.L
    top_h = w_len - T_CAP - 0.03
    cd = _smooth([loc(top_h, 0.030), loc(L0 + 0.06, 0.026), loc(L0 * 0.5, 0.016), loc(-wp.rh + 0.012, 0.004)],
                 60)
    gc = loc(L0 + 0.05, -0.040)
    neph = [loc(L0 + 0.05 + 0.016, -0.048, 0.004)]
    for k in range(7):                                   # proximal convoluted tubule
        neph.append(loc(L0 + 0.08 + 0.022 * math.sin(k * 1.7), -0.060 + 0.012 * math.cos(k * 2.3),
                        0.014 * math.sin(k * 2.1)))
    neph += [loc(L0 + 0.03, -0.034, 0.0), loc(L0 * 0.6, -0.030), loc(L0 * 0.22, -0.026),        # descending limb
             loc(L0 * 0.16, -0.019), loc(L0 * 0.22, -0.012), loc(L0 * 0.6, -0.013),              # hairpin, ascending
             loc(L0 + 0.02, -0.020, 0.004), loc(L0 + 0.045, -0.026, 0.006)]                       # macula densa
    for k in range(5):                                   # distal convoluted tubule
        neph.append(loc(L0 + 0.08 + 0.018 * math.sin(k * 1.9 + 1), -0.004 + 0.010 * math.cos(k * 2.2),
                        -0.012 * math.sin(k * 1.6)))
    neph.append(loc(L0 + 0.13, 0.024))                   # connecting tubule joins the collecting duct
    neph = _smooth(neph, 260)
    n_s = len(neph)
    s_idx = np.arange(n_s) / (n_s - 1)
    r_t = np.interp(s_idx, [0, 0.33, 0.36, 0.52, 0.60, 0.70, 0.78, 1.0],
                    [0.0055, 0.0055, 0.0032, 0.0032, 0.0042, 0.0042, 0.0046, 0.0046])
    parts.append(mesh_part(tube(neph, r_t, 10), "Nephron tubule", "Nephron wedge", "#f0d98a", DESC.get("tubule", ""),
                           "gland", rank=0.2, detail=(0.04, 0.0, 0.0, 0)))
    parts.append(mesh_part(tube(cd, np.linspace(0.0058, 0.0092, len(cd)), 10), "Collecting duct", "Nephron wedge",
                           "#8fd0e8", DESC.get("cd", ""), "gland", rank=0.2, detail=(0.04, 0.0, 0.0, 0)))
    corp = Mesh()
    corp.extend(ellipsoid_mesh(gc, (0.016, 0.016, 0.016), 14))
    aff = _smooth([gc + wp.a * 0.07 + wp.e * 0.02, gc + wp.a * 0.035 + wp.e * 0.012, gc], 14)
    corp.extend(tube(aff, 0.0038, 8))
    parts.append(mesh_part(corp, "Renal corpuscle", "Nephron wedge", "#d2463c", DESC.get("corpuscle", ""), "artery",
                           rank=0.2, detail=(0.04, 0.0, 0.0, 0)))
    wz = np.maximum(wedge_fn(x, y, z, zr=(-0.071, -0.005)) + 0.003, T_CAP + 0.008 - depth_k)
    parts.append(_part(kv, wz, "Nephron position (lobule wedge)", "Nephron wedge", "#cfe6ef",
                       DESC.get("wedge", ""), "csf", rank=0.2, alpha=0.22, smooth=0.8))
    del wz, wedge, depth_k, P, S

    # ------------------------------------------------------------------ suprarenal gland
    av = Volume((-0.42, 0.92, -0.16), (0.60, 1.95, 0.22), 0.007)
    ax_, ay_, az_ = av.axes()
    adr = np.broadcast_to(adrenal_sdf(ax_, ay_, az_), av.shape).astype(np.float32).copy()
    adr += 0.006 * fbm3(ax_ * 9.0, ay_ * 9.0, az_ * 9.0, 1.0, 3, 17)
    # the medulla is a flattened core in the body of the gland; the limbs and apex are cortex only
    core = np.sqrt(((ax_ - 0.09) / 0.085) ** 2 + ((ay_ - 1.29) / 0.20) ** 2) - 1.0
    core = core + 0.25 * fbm3(ax_ * 7.0, ay_ * 7.0, az_ * 0.0, 1.0, 2, 29)
    medulla = np.maximum(core * 0.08, np.abs(az_ - _adr_zc(ax_, ay_)) - 0.016 - 0.016 * np.clip(-core, 0, 1))
    medulla = np.broadcast_to(np.maximum(medulla, adr + 0.02), av.shape).astype(np.float32)
    medulla = medulla + 0.004 * fbm3(ax_ * 14.0, ay_ * 14.0, az_ * 14.0, 1.0, 2, 19)
    parts.append(_part(av, _minus(adr, medulla), "Suprarenal gland – cortex", "Suprarenal gland", "#d08a2c",
                       DESC.get("adr_cortex", ""), "gland", rank=3, detail=(0.08, 25.0, 0.0, 0)))
    parts.append(_part(av, medulla, "Suprarenal gland – medulla", "Suprarenal gland", "#6b3a33",
                       DESC.get("adr_medulla", ""), "gland", rank=3, detail=(0.10, 60.0, 0.0, 0)))
    del av, adr, medulla

    # ------------------------------------------------------------------ perirenal fat and renal fascia
    fv = Volume((-1.22, -1.80, -0.74), (1.45, 2.08, 0.74), 0.022)
    fx, fy, fz = fv.axes()
    Kf = kidney_sdf(fx, fy, fz)
    lateral = np.clip(-fx / 0.7, 0.0, 1.0)
    thick = 0.15 + 0.08 * lateral + 0.05 * np.clip(-fz / 0.4, 0.0, 1.0) + 0.05 * np.clip(np.abs(fy) - 0.6, 0, 1)
    F = Kf - thick - 0.035 * fbm3(fx * 4.5, fy * 4.5, fz * 4.5, 1.0, 3, 23)
    F = smin(F, adrenal_sdf(fx, fy, fz) - 0.07, 0.16)
    shf, bmin_, bmax_ = round_cone((0.45, 0.08, 0.0), (1.5, 0.12, 0.0), 0.20, 0.16)
    F = smin(F, shf(fx, fy, fz), 0.12)
    shu, _, _ = round_cone((0.68, -0.42, -0.01), (0.60, -1.85, -0.01), 0.15, 0.085)
    F = smin(F, shu(fx, fy, fz), 0.12)
    F = np.maximum(F, fx - 1.42)
    F = np.maximum(F, -1.78 - fy).astype(np.float32)
    holes = Volume(fv.lo, fv.hi, fv.voxel)
    for t in (A["renal"], V["renal"]):
        for path, r in t.paths:
            holes.tube(path[::3], r[::3] + 0.004)
    holes.tube(ureter_path[::3], 0.056)
    fat = np.maximum(F, -(Kf - 0.004))
    fat = np.maximum(fat, -adrenal_sdf(fx, fy, fz))
    fat = _minus(fat, holes.d)
    parts.append(_part(fv, fat.astype(np.float32), "Perirenal fat (adipose capsule)", "Coverings", "#e7c35c",
                       DESC.get("fat", ""), "fat", rank=4, smooth=0.9, detail=(0.10, 18.0, 0.0, 0)))
    fas = np.maximum(F - 0.045, -F)
    fas = np.maximum(fas, -1.38 - fy)                      # open below, where it lets the ureter through
    fas = _minus(fas, holes.d, margin=-0.01)
    parts.append(_part(fv, fas.astype(np.float32), "Renal fascia", "Coverings", "#d8d2c2", DESC.get("fascia", ""),
                       "fascia", rank=5, alpha=0.55, smooth=0.8, detail=(0.10, 30.0, 0.05, 0)))
    # list the layers from the outside in, the way the kidney is approached in the dissection room
    order = ["Coverings", "Renal cortex", "Renal medulla", "Collecting system", "Renal sinus & hilum", "Arteries",
             "Veins", "Nephron wedge", "Suprarenal gland"]
    first = ["Renal fascia", "Perirenal fat (adipose capsule)", "Fibrous capsule"]
    parts.sort(key=lambda q: (order.index(q.group), first.index(q.name) if q.name in first else 9))
    return parts
