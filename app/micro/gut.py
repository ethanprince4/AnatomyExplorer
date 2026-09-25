"""Intestinal wall models (duodenum, jejunum, ileum, colon) at high resolution.

Each segment is built to show what a student is examined on:
  duodenum  broad leaf-shaped villi and lobules of Brunner glands filling a thick submucosa;
  jejunum   tall finger-like villi carried on a plica circularis whose core is submucosa;
  ileum     shorter, goblet-rich villi around a Peyer patch - follicles with germinal centres under domes of
            follicle-associated epithelium with M cells;
  colon     no villi - a flat surface of crypt openings over long straight crypts packed with goblet cells, a taenia
            coli and an appendix epiploica.

Villi and crypts are swept surfaces (not voxels): a villus is a set of nested closed sheaths - brush border,
enterocytes, lamina propria core - around its lacteal, capillary net and smooth muscle, and a crypt is a
blind-ended tube of epithelium with a real lumen that opens on the surface. That keeps them smooth and crisp at
a fraction of the triangles, which leaves room for the individual goblet, Paneth and stem cells. The mucosa between
them, the muscularis mucosae and the submucosa are height-field layers. On the plica those layers are true
offsets of the submucosal core (a morphological dilation), so the mucosa keeps its thickness over the steep fold
and the villi and crypts stand normal to it. Muscle, plexuses and Brunner glands are signed-distance solids."""
import math

import numpy as np
from scipy.spatial import Delaunay, cKDTree

from .cells import frame_from_normal, poisson_disk
from .geometry import Mesh, _grid_indices, ellipsoid as ellipsoid_mesh, tube
from .kit import (Bumps, Volume, at, ellipsoid, hlayer, mesh_part, muscle_bundles, noise2, round_cone, sdf_part,
                  tube_mesh, wavy_path)
from .organic import Sweep, cell_lattice, settle

X0, X1, Z0, Z1 = -1.0, 1.0, -0.6, 0.6

# Teaching descriptions, one per selectable part.
TXT = {
    "serosa": "Serosa (visceral peritoneum): a simple squamous mesothelium on a thin layer of loose connective "
              "tissue carrying vessels, lymphatics and fat. Its secretions let the loops slide freely. The "
              "retroperitoneal parts of the gut (most of the duodenum, ascending and descending colon) have an "
              "adventitia instead on their posterior surface.",
    "long": "Outer longitudinal layer of the muscularis externa: smooth muscle bundles running along the gut. "
            "Contraction shortens the segment; coordinated with the circular layer by the myenteric plexus it "
            "produces peristalsis and segmentation.",
    "taenia": "Taenia coli: in the caecum and colon the outer longitudinal muscle is gathered into three flat bands "
              "(mesocolic, omental and free taeniae), each about 1 cm wide, with only a thin longitudinal layer "
              "between them. Being shorter than the gut they gather the wall into haustra. The taeniae converge on "
              "the base of the appendix - the surgeon's guide to finding it - and diverticula herniate between them "
              "where vasa recta pierce the circular muscle.",
    "circ": "Inner circular layer of the muscularis externa: bundles wrapped around the gut. Contraction narrows "
            "the lumen; the layer thickens to form the pyloric, ileocaecal and internal anal sphincters. The "
            "interstitial cells of Cajal (pacemakers of the slow waves) lie at its borders.",
    "myenteric": "Myenteric (Auerbach) plexus: ganglia and interconnecting nerve strands between the circular and "
                 "longitudinal muscle layers. Part of the enteric nervous system, it controls motility (peristalsis) "
                 "and is modulated by vagal and sympathetic input. Ganglion cells are absent in Hirschsprung disease "
                 "and lost in achalasia and Chagas disease.",
    "submucosa": "Submucosa: dense irregular connective tissue carrying the larger arterioles, venules, lymphatics "
                 "and the submucosal plexus. It gives the wall its strength - it is the layer that holds sutures.",
    "submucosa_plica": "Submucosa: dense irregular connective tissue with the larger vessels, lymphatics and the "
                       "submucosal plexus. In the jejunum it is raised with the overlying mucosa into the plicae "
                       "circulares (valves of Kerckring): permanent circular folds - they do not flatten when the "
                       "gut is distended - with a submucosal core. Tallest and most closely packed in the distal "
                       "duodenum and jejunum, they fade out in the ileum.",
    "submucosa_duo": "Submucosa of the duodenum: dense irregular connective tissue largely filled by the lobules of "
                     "Brunner glands, with the larger vessels, lymphatics and the submucosal plexus.",
    "submucosal_plexus": "Submucosal (Meissner) plexus: small ganglia and nerve strands in the submucosa next to "
                         "the muscularis mucosae. It controls epithelial secretion, absorption and local blood flow "
                         "and the muscularis mucosae. In Hirschsprung disease its ganglion cells are absent too - a "
                         "suction rectal biopsy, which samples the submucosa, is diagnostic.",
    "sub_artery": "Submucosal arterioles: branches of the vasa recta forming a submucosal plexus, from which "
                  "arterioles pierce the muscularis mucosae to supply the crypts and the villus capillary loops.",
    "sub_vein": "Submucosal venules: collect blood from the mucosa. Intestinal venous blood, rich in absorbed sugars "
                "and amino acids, drains through the superior and inferior mesenteric veins into the hepatic portal "
                "vein.",
    "mucosal_branch": "Mucosal branches: small arterioles and venules crossing the muscularis mucosae between the "
                      "submucosal plexus and the capillaries of the lamina propria and villi.",
    "plica_vessels": "Vessels in the core of the plica circularis: branches of the submucosal plexus that run in "
                     "the fold and feed the mucosa covering it.",
    "mm": "Muscularis mucosae: a thin layer of smooth muscle (inner circular, outer longitudinal) at the base of "
          "the mucosa. It moves the mucosa locally, independently of peristalsis. In colorectal cancer, invasion "
          "through it into the submucosa is what defines an invasive carcinoma (pT1).",
    "lp": "Lamina propria: loose (areolar) connective tissue between the crypts, rich in IgA-secreting plasma "
          "cells, lymphocytes, macrophages, eosinophils, fenestrated capillaries and lymphatics - the diffuse part "
          "of the gut-associated lymphoid tissue (GALT).",
    "villus_epi": "Villus epithelium: simple columnar absorptive cells (enterocytes) joined near their apices by "
                  "tight junctions, with goblet cells scattered between them and occasional enteroendocrine cells and "
                  "intraepithelial lymphocytes. Enterocytes are born in the crypts and migrate to the villus tip, "
                  "where they are shed after about 3-5 days. They take up sugars (SGLT1, GLUT5), amino acids and "
                  "peptides, and re-esterify fatty acids into chylomicrons for the lacteal.",
    "brush": "Brush border (striated border): thousands of microvilli on the apical surface of each enterocyte, "
             "each with a core of actin filaments anchored in the terminal web, covered by a carbohydrate-rich "
             "glycocalyx. Together with villi and plicae it multiplies the absorptive area about 600-fold. Its "
             "membrane carries the digestive enzymes - lactase, sucrase-isomaltase, maltase, aminopeptidases and "
             "enteropeptidase (duodenum) - so it stains PAS-positive and loss of lactase causes lactose "
             "intolerance.",
    "villus_core": "Villus core: lamina propria in the centre of the villus, containing the central lacteal, a "
                   "subepithelial capillary network, strands of smooth muscle and immune cells (plasma cells, "
                   "macrophages, lymphocytes).",
    "lacteal": "Central lacteal: a blind-ended lymphatic capillary in the axis of each villus. It takes up "
               "chylomicrons (absorbed dietary fat), which are too large to enter blood capillaries, and carries "
               "them via mesenteric lymphatics and the cisterna chyli to the thoracic duct - lymph (chyle) is milky "
               "after a fatty meal.",
    "villus_cap": "Villus capillary network: an arteriole ascends the villus and breaks up at the tip into a "
                  "fenestrated capillary net lying just beneath the epithelium, drained by a venule. It absorbs "
                  "water-soluble nutrients (monosaccharides, amino acids) into the portal circulation. The "
                  "countercurrent arrangement makes the villus tip relatively hypoxic, so it is the first part "
                  "injured in ischaemia.",
    "villus_muscle": "Villus smooth muscle: strands from the muscularis mucosae running up the villus core beside "
                     "the lacteal. Their rhythmic contraction shortens the villus and pumps chyle out of the "
                     "lacteal.",
    "goblet": "Goblet cells: unicellular mucous glands whose apical cup (theca) is packed with mucin granules, "
              "PAS-positive and pale in H&E, above a narrow stem with the nucleus. The mucus (mainly MUC2) lubricates "
              "and protects the epithelium. They become more numerous along the gut, from the duodenum to the "
              "colon.",
    "goblet_ileum": "Goblet cells: unicellular mucous glands whose apical cup (theca) is packed with mucin "
                    "granules, PAS-positive and pale in H&E. They are more numerous in the ileum than in the "
                    "jejunum and duodenum, and more numerous still in the colon.",
    "goblet_colon": "Goblet cells: the dominant cell of the colonic crypts - the crypts are packed with them, "
                    "giving the mucosa its pale, 'test-tube rack' look. Their mucus forms a thick two-layered gel; "
                    "the dense inner layer keeps bacteria away from the epithelium. Goblet cells are depleted in "
                    "active ulcerative colitis.",
    "crypt": "Intestinal crypts (of Lieberkühn): simple tubular glands opening between the villi and reaching down "
             "to the muscularis mucosae. They are the regenerative compartment: stem cells at the base give rise to "
             "transit-amplifying cells in the lower half, which differentiate into enterocytes, goblet cells, "
             "enteroendocrine cells (e.g. I cells making CCK, S cells making secretin, K cells making GIP) and "
             "Paneth cells. Crypt hyperplasia with villous atrophy is the lesion of coeliac disease.",
    "colon_crypt": "Colonic crypts (of Lieberkühn): long, straight, unbranched tubular glands packed side by side "
                   "like test tubes in a rack and opening on the flat surface. They consist mainly of goblet cells "
                   "and absorptive colonocytes, with stem cells and enteroendocrine cells at the base; normally no "
                   "Paneth cells in the distal colon. Branched or distorted crypts indicate chronic colitis, and "
                   "neutrophils in the lumen form crypt abscesses.",
    "paneth": "Paneth cells: pyramidal cells clustered at the crypt base, with large eosinophilic (bright red) "
              "apical granules containing lysozyme, alpha-defensins and phospholipase A2. They shape the gut "
              "microbiome and form the niche that supports the neighbouring stem cells. Mainly in the small "
              "intestine, most numerous in the ileum; abnormal in Crohn disease, and their appearance in the distal "
              "colon (Paneth cell metaplasia) is a sign of chronic colitis.",
    "stem": "Crypt base columnar stem cells (Lgr5+): slender cells wedged between the Paneth cells at the crypt "
            "base. They divide continuously to renew the whole epithelium every 3-5 days, via transit-amplifying "
            "cells; Wnt signalling from Paneth cells and the surrounding stroma keeps them in the stem state. APC "
            "mutations that switch this Wnt signalling on permanently start most colorectal cancers.",
    "stem_colon": "Crypt base stem cells (Lgr5+): slender cells at the base of each colonic crypt that renew the "
                  "epithelium every 5-7 days via transit-amplifying cells. APC mutations here, which switch on "
                  "Wnt signalling, are the first step of the adenoma-carcinoma sequence.",
    "brunner": "Brunner (duodenal) glands: branched tubuloalveolar glands in the submucosa - the histological "
               "hallmark of the duodenum. Their pale-staining mucous cells secrete an alkaline, bicarbonate-rich "
               "mucus (and epidermal growth factor) that neutralises acid chyme from the stomach and protects the "
               "duodenal mucosa. Most abundant in the first part of the duodenum, they fade out near the ampulla. "
               "Some lobules sit above the muscularis mucosae.",
    "brunner_duct": "Ducts of the Brunner glands: they pierce the muscularis mucosae and open into the bases of "
                    "the crypts of Lieberkühn.",
    "peyer": "Peyer patch follicles: lymphoid follicles aggregated on the antimesenteric wall of the ileum. They "
             "sit in the lamina propria and bulge through the muscularis mucosae into the submucosa. The dark rim "
             "(mantle zone) of small naive B cells surrounds the germinal centre; T cells occupy the "
             "interfollicular areas. Peyer patches are largest in adolescence and can be a lead point for "
             "intussusception, and in typhoid fever they ulcerate and can perforate.",
    "follicle": "Solitary lymphoid follicle: an isolated follicle of B lymphocytes in the lamina propria that often "
                "extends through the muscularis mucosae into the submucosa (a lymphoglandular complex). "
                "Such follicles become more common towards the rectum; the appendix is packed with them.",
    "germinal": "Germinal centre: the pale centre of a secondary follicle, where antigen-stimulated B cells "
                "proliferate (centroblasts), undergo affinity maturation among follicular dendritic cells and "
                "class-switch, mainly to IgA; the plasma cells they give rise to home to the lamina propria and "
                "secrete dimeric IgA.",
    "dome": "Subepithelial dome: the region between a follicle and the dome epithelium, rich in dendritic cells, "
            "macrophages and B and T cells. The dendritic cells here pick up the antigens delivered by M cells and "
            "present them to T cells.",
    "fae": "Follicle-associated epithelium: the epithelium over the dome of each follicle. It has no villi, few "
           "goblet cells (so the mucus layer is thin) and a thin, less enzymatic brush border. Interspersed "
           "between the enterocytes are M cells.",
    "m_cells": "M (microfold) cells: specialised cells of the follicle-associated epithelium. Instead of a brush "
               "border they carry short microfolds, and their basal surface is hollowed into a pocket holding "
               "lymphocytes and dendritic cells. They take up luminal antigens and microbes by transcytosis and "
               "hand them to the immune cells beneath - the route by which Salmonella, Shigella, Yersinia, "
               "poliovirus and prions cross the gut wall.",
    "surface_colon": "Surface epithelium of the colon: simple columnar absorptive cells (colonocytes) with short "
                     "microvilli, absorbing water and sodium and secreting potassium and bicarbonate, with goblet "
                     "cells between them. The surface is flat - there are no villi in the large intestine - and is "
                     "perforated by the regularly spaced openings of the crypts.",
    "appendix_epi": "Appendix epiploica (epiploic appendage): a small peritoneal pouch of fat hanging from the "
                    "serosa of the colon, mainly along the free and omental taeniae. Present on the colon but not "
                    "on the small intestine or rectum, so it identifies large bowel at surgery. It can twist and "
                    "infarct (epiploic appendagitis), mimicking appendicitis or diverticulitis.",
}

# Per-segment geometry. Heights are in model units (1 unit ~ 1.5 mm). v_*: villus shape; crypt: mucosal thickness
# that the crypts span; sub: top of the submucosa; gob: goblet cells per villus.
SPEC = {
    "jejunum": dict(v_space=0.15, v_r=0.045, v_flat=0.82, v_h=0.34, leaf=False, crypt=0.19, sub=0.44, gob=11,
                    fold=0.64, seed=1),
    "duodenum": dict(v_space=0.21, v_r=0.085, v_flat=0.36, v_h=0.29, leaf=True, crypt=0.19, sub=0.62, gob=8,
                     fold=0.0, seed=2),
    "ileum": dict(v_space=0.14, v_r=0.042, v_flat=0.88, v_h=0.24, leaf=False, crypt=0.19, sub=0.47, gob=19,
                  fold=0.0, seed=3),
    "colon": dict(v_space=0.0, v_r=0.0, v_flat=1.0, v_h=0.0, leaf=False, crypt=0.40, sub=0.44, gob=0, fold=0.0,
                  seed=4),
}

T_MM = 0.024        # muscularis mucosae
T_EPI = 0.020       # enterocyte height (epithelium thickness)
T_BB = 0.0045       # brush border
Y_SER = 0.024       # top of the serosa
Y_CIRC0 = 0.112     # bottom of the circular muscle (the myenteric plexus runs in the gap below it)
Y_CIRC1 = 0.28      # top of the circular muscle


# --------------------------------------------------------------------------------------------- helpers
def _dilate(F, d, n=29):
    """Morphological dilation of a height field that varies along x: the surface lying a distance d above F measured
    along the normal, not straight up. Over a steep fold a vertical offset would thin to nothing on the flanks."""
    if d <= 0:
        return F
    ks = np.linspace(-d, d, n)
    hs = np.sqrt(np.maximum(d * d - ks * ks, 0.0))

    def f(X, Z):
        X, Z = np.broadcast_arrays(np.asarray(X, float), np.asarray(Z, float))
        out = None
        for k, h in zip(ks, hs):
            v = F(X + k, Z) + h
            out = v if out is None else np.maximum(out, v)
        return out
    return f


def _normals(fy, x, z, h=0.004):
    """Unit normals of the surface y = fy(x, z) at arrays of points."""
    x, z = np.asarray(x, float), np.asarray(z, float)
    gx = (fy(x + h, z) - fy(x - h, z)) / (2 * h)
    gz = (fy(x, z + h) - fy(x, z - h)) / (2 * h)
    n = np.stack([-gx, np.ones_like(gx), -gz], -1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def _lattice(u0, u1, spacing, jitter, seed, margin):
    """Hexagonal lattice in (u, z) with a row on z = 0 and a column on u = 0 - the cut planes - so the cut-away
    sections villi and crypts lengthwise. The jitter fades out near each plane to keep that section clean."""
    dz = spacing * math.sqrt(3) / 2
    pts = []
    for j in range(int(Z0 / dz) - 1, int(Z1 / dz) + 2):
        z = j * dz
        off = spacing / 2 if j % 2 else 0.0
        for i in range(int(u0 / spacing) - 2, int(u1 / spacing) + 3):
            u = i * spacing + off
            if u0 + margin < u < u1 - margin and Z0 + margin < z < Z1 - margin:
                pts.append((u, z))
    pts = np.array(pts)
    rng = np.random.default_rng(seed)
    keep = np.clip(np.abs(pts) / (spacing * 0.7), 0.0, 1.0)
    return pts + rng.uniform(-jitter, jitter, pts.shape) * spacing * keep


def _map_u(fy):
    """Arc length along x over the surface (at z = 0), so villi and crypts are spread evenly over a fold's flanks
    instead of thinning out where the surface is steep. Returns (u(x), x(u), u range)."""
    xs = np.linspace(X0, X1, 2001)
    ys = fy(xs, np.zeros_like(xs))
    s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(xs), np.diff(ys)))])
    s -= np.interp(0.0, xs, s)
    return (lambda x: np.interp(x, xs, s)), (lambda u: np.interp(u, s, xs)), (float(s[0]), float(s[-1]))


def _dome(d, R):
    """Radius factor that rounds a swept tube off over its last R of length (d = distance from that end)."""
    R = np.maximum(R, 1e-6)
    return np.where(d < R, np.sqrt(np.clip(1.0 - (1.0 - d / R) ** 2, 0.0025, 1.0)), 1.0)


def _ease_end(t):
    return 0.5 * t + 0.5 * np.sin(t * math.pi / 2)          # rings crowd towards t = 1 (a rounded tip)


def _ease_start(t):
    return 0.5 * t + 0.5 * (1.0 - np.cos(t * math.pi / 2))  # rings crowd towards t = 0 (a rounded base)


def _cell(center, direction, radii, res=4):
    """A cell as a small ellipsoid whose long (local y) axis follows `direction`."""
    return ellipsoid_mesh(center, radii, res, rotation=frame_from_normal(direction))


def _radial(sw, s, theta, r):
    """Point at (s, theta, r) of a sweep and the outward radial direction there."""
    p = sw.curve(np.atleast_1d(s), np.atleast_1d(theta), np.atleast_1d(r))[0]
    q = sw.curve(np.atleast_1d(s), np.atleast_1d(theta), np.atleast_1d(r + 0.01))[0]
    d = q - p
    return p, d / max(np.linalg.norm(d), 1e-9)


def _phase(sw, direction):
    """Sweep angle theta that points along a world direction at the start of the sweep."""
    return math.atan2(float(sw.bi[0] @ direction), float(sw.nrm[0] @ direction))


def _slab2(top_fn, bot_fn, res_top, res_bot, gap=0.0015):
    """Closed solid between two height fields whose top is sampled more finely than its bottom - a surface with
    small pits over a smooth base, without paying for the fine grid twice."""
    parts = []

    def grid(res):
        nx = int(res) + 1
        nz = int(res * (Z1 - Z0) / (X1 - X0)) + 1
        return np.meshgrid(np.linspace(X0, X1, nx), np.linspace(Z0, Z1, nz), indexing="ij")
    Xt, Zt = grid(res_top)
    Xb, Zb = grid(res_bot)
    top = np.asarray(top_fn(Xt, Zt), float) * np.ones_like(Xt) - gap
    bot = np.asarray(bot_fn(Xb, Zb), float) * np.ones_like(Xb) + gap
    # keep the top above the bottom everywhere (the bottom interpolated onto the fine grid)
    from scipy.interpolate import RegularGridInterpolator
    bi = RegularGridInterpolator((Xb[:, 0], Zb[0]), bot)
    top = np.maximum(top, bi(np.stack([Xt.ravel(), Zt.ravel()], -1)).reshape(Xt.shape) + 1e-4)
    parts.append((np.stack([Xt, top, Zt], -1).reshape(-1, 3), _grid_indices(*Xt.shape, flip=True), 1.0))
    parts.append((np.stack([Xb, bot, Zb], -1).reshape(-1, 3), _grid_indices(*Xb.shape), -1.0))
    edges = [((slice(None), 0), 2, -1.0), ((slice(None), -1), 2, 1.0), ((0, slice(None)), 0, -1.0),
             ((-1, slice(None)), 0, 1.0)]
    for sl, axis, sgn in edges:
        pt = np.stack([Xt[sl], top[sl], Zt[sl]], -1)
        pb = np.stack([Xb[sl], bot[sl], Zb[sl]], -1)
        along = 2 if axis == 0 else 0
        tt, tb = pt[:, along], pb[:, along]
        n, m = len(pt), len(pb)
        tri, i, j = [], 0, 0
        while i < n - 1 or j < m - 1:              # zip the fine and the coarse edge together
            if j == m - 1 or (i < n - 1 and tt[i + 1] <= tb[j + 1]):
                tri.append((i, i + 1, n + j))
                i += 1
            else:
                tri.append((i, n + j + 1, n + j))
                j += 1
        parts.append((np.vstack([pt, pb]), np.array(tri), (axis, sgn)))
    mesh = Mesh()
    for pos, idx, want in parts:
        a, b, c = pos[idx[0, 0]], pos[idx[0, 1]], pos[idx[0, 2]]
        nrm = np.cross(b - a, c - a)
        ok = nrm[1] * want > 0 if not isinstance(want, tuple) else nrm[want[0]] * want[1] > 0
        mesh.add(pos, idx if ok else idx[:, ::-1])
    return mesh


def _disc(cx, cz, R, top_fn, bot_fn, n_r=12, n_t=48):
    """Closed solid between two height fields over a disc (a patch of epithelium over a dome)."""
    r = np.linspace(0.0, R, n_r)
    t = np.linspace(0.0, 2 * math.pi, n_t, endpoint=False)
    Rg, Tg = np.meshgrid(r, t, indexing="ij")
    X, Z = cx + Rg * np.cos(Tg), cz + Rg * np.sin(Tg)
    top = np.asarray(top_fn(X, Z), float)
    bot = np.minimum(np.asarray(bot_fn(X, Z), float), top - 1e-4)
    a = np.arange(n_r * n_t).reshape(n_r, n_t)
    q0, q1 = a[:-1, :].ravel(), np.roll(a[:-1, :], -1, axis=1).ravel()
    q2, q3 = np.roll(a[1:, :], -1, axis=1).ravel(), a[1:, :].ravel()
    quad = np.vstack([np.stack([q0, q2, q1], 1), np.stack([q0, q3, q2], 1)])
    pt = np.stack([X, top, Z], -1).reshape(-1, 3)
    pb = np.stack([X, bot, Z], -1).reshape(-1, 3)
    k = n_r * n_t
    rim_t, rim_b = a[-1], a[-1] + k
    nxt_t, nxt_b = np.roll(rim_t, -1), np.roll(rim_b, -1)
    side = np.vstack([np.stack([rim_t, nxt_t, nxt_b], 1), np.stack([rim_t, nxt_b, rim_b], 1)])
    from .cells import orient_outward
    return orient_outward(Mesh().add(np.vstack([pt, pb]), np.vstack([quad, quad[:, ::-1] + k, side[:, ::-1]])))


def _network(center_y_fn, spacing, node_r, strand_r, seed, voxel=0.007, thickness=0.03):
    """Ganglia joined by nerve strands, polygonised as one organic network."""
    pts = poisson_disk((X0 - 0.05, Z0 - 0.05), (X1 + 0.05, Z1 + 0.05), spacing, seed=seed)
    ys = np.asarray(center_y_fn(pts[:, 0], pts[:, 1]), float)
    lo_y, hi_y = float(ys.min()) - thickness, float(ys.max()) + thickness
    vol = Volume((X0, lo_y, Z0), (X1, hi_y, Z1), voxel)
    rng = np.random.default_rng(seed)
    shapes = []
    for (x, z), y in zip(pts, ys):
        a = rng.uniform(0, math.pi)
        rot = np.array([[math.cos(a), 0, -math.sin(a)], [0, 1, 0], [math.sin(a), 0, math.cos(a)]])
        shapes.append(ellipsoid((x, y, z), (node_r * rng.uniform(1.0, 1.6), node_r * 0.4, node_r), rot))
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


# --------------------------------------------------------------------------------------------- the model
def build_gut(kind="jejunum"):
    sp = SPEC[kind]
    colon = kind == "colon"
    rng = np.random.default_rng(sp["seed"])
    parts = []
    xr, zr = (X0, X1), (Z0, Z1)

    # ---- the layer stack. F is the top of the submucosa; everything above is a dilation of it
    wobble = noise2(0.006, 3.0, seed=5)
    if sp["fold"]:
        H = sp["fold"]

        def F(X, Z):
            X, Z = np.asarray(X, float), np.asarray(Z, float)
            xc = -0.45 + 0.045 * np.sin(2.3 * Z + 0.5) * np.clip(np.abs(Z) / 0.12, 0, 1)
            h = H * (1.0 + 0.06 * np.sin(3.1 * Z + 0.4))
            return sp["sub"] + h * np.exp(-((X - xc) / 0.13) ** 2) + wobble(X, Z)
        y_sub = F
        y_mm = _dilate(F, T_MM)
        y_s0 = _dilate(F, T_MM + sp["crypt"])
    else:
        y_sub = lambda X, Z: sp["sub"] + wobble(X, Z)
        y_mm = lambda X, Z: sp["sub"] + T_MM + wobble(X, Z)
        y_s0 = lambda X, Z: sp["sub"] + T_MM + sp["crypt"] + wobble(X, Z)

    # lymphoid follicles push the mucosa up into domes and break through the muscularis mucosae
    if kind == "ileum":
        follicles = [(-0.64, 0.0, 0.165), (-0.27, 0.0, 0.155), (-0.46, -0.34, 0.15), (-0.10, -0.36, 0.14)]
    elif colon:
        follicles = [(-0.52, 0.0, 0.14)]
    else:
        follicles = []
    dome_h = 0.11 if kind == "ileum" else 0.03

    def dome_mask(X, Z, grow=1.0):
        X, Z = np.asarray(X, float), np.asarray(Z, float)
        m = np.zeros(np.broadcast(X, Z).shape)
        for fx, fz, fr in follicles:
            t = np.clip(1.0 - np.hypot(X - fx, Z - fz) / (fr * grow), 0.0, 1.0)
            m = np.maximum(m, t * t * (3 - 2 * t))
        return m

    def y_s(X, Z):
        base = y_s0(X, Z)
        if not follicles:
            return base
        X, Z = np.asarray(X, float), np.asarray(Z, float)
        bump = np.zeros(np.broadcast(X, Z).shape)
        for fx, fz, fr in follicles:
            q = np.clip(1.0 - ((X - fx) ** 2 + (Z - fz) ** 2) / (fr * 1.15) ** 2, 0.0, 1.0)
            bump = np.maximum(bump, q ** 1.4)
        return base + dome_h * bump

    fae = (lambda X, Z: dome_mask(X, Z, 0.95)) if kind == "ileum" else (lambda X, Z: 0.0 * np.asarray(X, float))
    mm_thin = lambda X, Z: y_sub(X, Z) + (y_mm(X, Z) - y_sub(X, Z)) * (1.0 - dome_mask(X, Z, 0.85))
    # each follicle sits in a pocket of lamina propria that reaches down into the submucosa, so it is wholly
    # nested in one layer and a section through it is not overdrawn by the layer boundary crossing it
    t_epi = T_EPI if not colon else 0.024
    geoms = [_follicle_geom(f, y_sub, y_s, t_epi) for f in follicles]

    def pocket(X, Z):
        X, Z = np.asarray(X, float), np.asarray(Z, float)
        out = np.full(np.broadcast(X, Z).shape, 9.0)
        for (fx, fz, fr), (yb, H, Hf) in zip(follicles, geoms):
            d = np.hypot(X - fx, Z - fz)
            R, c = fr * 1.15, yb + Hf / 2
            v = np.where(d < R, c - (Hf / 2 + 0.014) * np.sqrt(np.clip(1.0 - (d / R) ** 2, 0.0, 1.0)),
                         c + 0.15 * np.clip((d - R) / 0.06, 0.0, 1.0))
            out = np.minimum(out, v)
        return out
    mm_top = lambda X, Z: np.minimum(mm_thin(X, Z), pocket(X, Z))
    sub_top = lambda X, Z: np.minimum(y_sub(X, Z), pocket(X, Z))

    # colon: the taenia coli bulges outwards (down) from the longitudinal layer, which is thin between the bands
    if colon:
        band = lambda X, Z: 0.15 * np.clip(1.0 - np.abs(np.asarray(Z) - 0.3 + 0.02 * np.sin(np.asarray(X) * 2.2))
                                           / 0.2, 0, 1) ** 0.6
        y_long0 = lambda X, Z: -band(X, Z) + 0.004 * np.sin(np.asarray(X) * 7.0)
        y_long1 = lambda X, Z: 0.07 + 0.0 * np.asarray(X)
    else:
        y_long0 = lambda X, Z: Y_SER + 0.0 * np.asarray(X) + 0.003 * np.sin(np.asarray(Z) * 6.0)
        y_long1 = lambda X, Z: 0.098 + 0.004 * np.sin(np.asarray(X) * 9)
    y_circ0 = lambda X, Z: y_long1(X, Z) + 0.014
    y_circ1 = lambda X, Z: Y_CIRC1 + 0.006 * np.sin(np.asarray(X) * 5 + 1)

    # ---- serosa & muscularis externa
    parts.append(hlayer("Serosa", "Serosa & muscularis externa", "#eadcb8", lambda X, Z: y_long0(X, Z) - 0.024,
                        y_long0, TXT["serosa"], "serosa", xr, zr, bulk=True, rank=-4, res=150))
    if colon:
        long_vol = muscle_bundles(y_long0, y_long1, 0, 0.085, 0.036, seed=81, rows=4, voxel=0.011)
    else:
        long_vol = muscle_bundles(y_long0, y_long1, 0, 0.1, 0.032, seed=81, voxel=0.011)
    parts.append(sdf_part(long_vol, "Taenia coli & longitudinal muscle" if colon else "Outer longitudinal muscle",
                          "Serosa & muscularis externa", "#c25d51", TXT["taenia"] if colon else TXT["long"],
                          "muscle", smooth=0.8, rank=-3, detail=(0.08, 80.0, 0.4, 1)))
    parts.append(sdf_part(muscle_bundles(y_circ0, y_circ1, 2, 0.11, 0.044, seed=82, rows=3, voxel=0.0125),
                          "Inner circular muscle", "Serosa & muscularis externa", "#a8463d", TXT["circ"], "muscle",
                          smooth=0.8, rank=-2, detail=(0.08, 80.0, 0.4, 3)))
    if colon:
        parts.append(_appendix_epiploica(y_long0))

    sub_desc = TXT["submucosa_plica"] if sp["fold"] else (TXT["submucosa_duo"] if kind == "duodenum"
                                                          else TXT["submucosa"])
    parts.append(hlayer("Submucosa", "Submucosa", "#f0d2c3", y_circ1, sub_top, sub_desc, "fascia", xr, zr, bulk=True,
                        rank=-1, res=160 if sp["fold"] else 120, detail=(0.14, 55.0, 0.15, 0)))
    parts.append(hlayer("Muscularis mucosae", "Mucosa", "#b95a50", sub_top, mm_top, TXT["mm"], "muscle", xr, zr,
                        rank=0, res=160 if sp["fold"] else 120, detail=(0.08, 90.0, 0.4, 1)))

    # ---- plexuses
    my = _network(lambda X, Z: y_long1(X, Z) + 0.007, 0.22, 0.042, 0.0075, seed=11)
    parts.append(sdf_part(my, "Myenteric (Auerbach) plexus", "Nerves & vessels", "#f0cf45", TXT["myenteric"], "nerve",
                          smooth=0.7, rank=-2.5, detail=(0.05, 150.0, 0.6, 0)))
    smp_y = lambda X, Z: np.maximum(np.minimum(y_sub(X, Z) - 0.035, pocket(X, Z) - 0.025), Y_CIRC1 + 0.045)
    smp = _network(smp_y, 0.19, 0.028, 0.0055, seed=13, voxel=0.006)
    parts.append(sdf_part(smp, "Submucosal (Meissner) plexus", "Nerves & vessels", "#f3d35a",
                          TXT["submucosal_plexus"], "nerve", smooth=0.7, rank=-1, detail=(0.05, 150.0, 0.6, 0)))

    # ---- submucosal vessels
    art, vein, branch = Mesh(), Mesh(), Mesh()
    v_y = Y_CIRC1 + (0.035 if follicles else (0.05 if kind == "duodenum" else 0.07))
    for j, z in enumerate((-0.40, 0.02, 0.36)):
        path = wavy_path((X0 + 0.01, 0, z), (X1 - 0.01, 0, z + 0.04), 80, 0.03, 1.5, seed=20 + j)
        path[:, 1] = v_y + 0.01 * np.sin(path[:, 0] * 4 + j)
        art.extend(tube(path, 0.021, 16))
        vpath = path.copy()
        vpath[:, 2] += 0.07
        vpath[:, 1] -= 0.008
        vein.extend(tube(vpath, 0.031, 18))
        for x in np.linspace(-0.85, 0.85, 7):
            k = int(np.argmin(np.abs(path[:, 0] - x)))
            a = path[k]
            if any(math.hypot(a[0] - fx, a[2] - fz) < fr * 1.3 for fx, fz, fr in follicles):
                continue
            top = np.array([a[0] + 0.03, at(y_mm, a[0] + 0.03, a[2] + 0.02) + 0.03, a[2] + 0.02])
            branch.extend(tube_mesh(wavy_path(a, top, 18, 0.01, 1.0, seed=int(x * 100) + j), 0.0075, 8))
    if sp["fold"]:
        pa, pv = _plica_vessels(y_sub, sp["fold"])
        art.extend(pa)
        vein.extend(pv)
    parts += [mesh_part(art, "Submucosal arterioles", "Nerves & vessels", "#cf3a31", TXT["sub_artery"], "artery",
                        rank=-1),
              mesh_part(vein, "Submucosal venules", "Nerves & vessels", "#3d5bc2", TXT["sub_vein"], "vein", rank=-1),
              mesh_part(branch, "Mucosal branches", "Nerves & vessels", "#d64b43", TXT["mucosal_branch"], "artery",
                        rank=-0.5, label=False)]

    # ---- lamina propria and surface epithelium between the villi (or the flat colonic surface)
    res_top = 150 if sp["fold"] else 120
    parts.append(hlayer("Lamina propria", "Mucosa", "#f0c3b5", mm_top, lambda X, Z: y_s(X, Z) - t_epi, TXT["lp"],
                        "mucosa", xr, zr, bulk=True, rank=1, res=res_top, detail=(0.12, 120.0, 0.5, 0)))

    # ---- crypts (and, in the small intestine, the villi they open between)
    if colon:
        crypt_pts = _lattice(X0, X1, 0.075, 0.2, 73, 0.05)
        villi = np.zeros((0, 2))
    else:
        u_of_x, x_of_u, (u0, u1) = _map_u(y_s0)
        uv = _lattice(u0, u1, sp["v_space"], 0.22, 71, sp["v_space"] * 0.42)
        villi = np.stack([x_of_u(uv[:, 0]), uv[:, 1]], -1)
        clear = (villi[:, 0] > X0 + 0.07) & (villi[:, 0] < X1 - 0.07) & np.array(
            [not any(math.hypot(v[0] - fx, v[1] - fz) < fr * 1.15 + 0.05 for fx, fz, fr in follicles) for v in villi],
                                                                     bool)
        villi = villi[clear]
        # crypts open around each villus: the centres of the villus triangles, plus the midpoints between
        # neighbours along the cut planes, so a section shows villi and crypts alternating as on a slide
        uvk = uv[clear]
        tri = Delaunay(uvk)
        cand = [uvk[s].mean(axis=0) for s in tri.simplices]
        for s in tri.simplices:
            for i in range(3):
                a, b = uvk[s[i]], uvk[s[(i + 1) % 3]]
                m = (a + b) / 2
                if (abs(a[1]) < 0.02 and abs(b[1]) < 0.02) or (abs(m[0]) < 0.02):
                    cand.append(m)
        cand = np.array(cand)
        cand = cand[np.linalg.norm(cand[:, None, :] - uvk[None, :, :], axis=-1).min(axis=1) < sp["v_space"] * 0.8]
        crypt_pts = np.stack([x_of_u(cand[:, 0]), cand[:, 1]], -1)
    # no crypts under a lymphoid dome, none crowding the walls
    ok = np.array([all(math.hypot(c[0] - fx, c[1] - fz) > fr * 1.02 for fx, fz, fr in follicles) for c in crypt_pts],
                  bool) if len(crypt_pts) else np.zeros(0, bool)
    crypt_pts = crypt_pts[ok]
    crypt_pts = crypt_pts[(np.abs(crypt_pts[:, 0]) < X1 - 0.04) & (np.abs(crypt_pts[:, 1]) < Z1 - 0.04)]
    if len(crypt_pts) > 1:      # drop near-duplicates
        tree = cKDTree(crypt_pts)
        drop = set()
        for i, j in sorted(tree.query_pairs(0.045 if not colon else 0.05)):
            if i not in drop:
                drop.add(j)
        crypt_pts = crypt_pts[[i for i in range(len(crypt_pts)) if i not in drop]]

    # the surface epithelium between the villi dips into a funnel at the mouth of every crypt; the crypt's own
    # wall and lumen continue down from the bottom of the funnel
    pit_r, pit_d = (0.02, 0.021) if colon else (0.016, 0.018)
    pits = Bumps(crypt_pts, pit_r, -pit_d, k=3, sharp=0.8)
    skin = 0.0 if colon else T_BB          # the floor epithelium carries its brush border as its top surface
    floor_epi = _slab2(lambda X, Z: y_s(X, Z) + skin - (t_epi + skin) * fae(X, Z) + pits(X, Z),
                       lambda X, Z: y_s(X, Z) - t_epi, 360 if colon else 300, 110)
    crypts, pan, stem, gob_c = _crypts(crypt_pts, y_s, sp["crypt"], colon, kind, rng, pit_d)
    parts.append(mesh_part(crypts, "Colonic crypts (of Lieberkühn)" if colon else "Intestinal crypts (of Lieberkühn)",
                           "Mucosa", "#c9819a" if not colon else "#c98fa6",
                           TXT["colon_crypt"] if colon else TXT["crypt"], "mucosa", rank=1.2,
                           detail=(0.10, 170.0, 0.9, 2)))
    if pan.parts:
        parts.append(mesh_part(pan, "Paneth cells", "Mucosa", "#e5563f", TXT["paneth"], "gland", rank=1.3,
                               detail=(0.05, 0.0, 0.0, 0)))
    parts.append(mesh_part(stem, "Crypt base stem cells (Lgr5+)", "Mucosa", "#7d6bc9",
                           TXT["stem_colon"] if colon else TXT["stem"], "mucosa", rank=1.3,
                           detail=(0.05, 0.0, 0.0, 0)))

    if colon:
        parts.append(mesh_part(floor_epi, "Surface epithelium (colonocytes)", "Mucosa", "#e2a3a0",
                               TXT["surface_colon"], "mucosa", rank=2, detail=(0.10, 150.0, 0.85, 0)))
        # goblet cells also open on the surface between the crypt mouths
        tree = cKDTree(crypt_pts)
        for p in poisson_disk((X0 + 0.02, Z0 + 0.02), (X1 - 0.02, Z1 - 0.02), 0.05, seed=31):
            if tree.query(p)[0] < 0.036 or dome_mask(p[0], p[1]) > 0.1:
                continue
            y = at(y_s, p[0], p[1])
            gob_c.extend(_cell((p[0], y - 0.009, p[1]), (0, 1, 0), (0.0065, 0.0105, 0.0065)))
        parts.append(mesh_part(gob_c, "Goblet cells", "Mucosa", "#e6ecf6", TXT["goblet_colon"], "mucosa", rank=2.6,
                               detail=(0.03, 0.0, 0.0, 0)))
    else:
        v = _villi(villi, y_s, sp, kind, rng)
        epi = v["epi"]
        epi.extend(floor_epi)
        bb = v["bb"]
        gob = v["goblet"]
        gob.extend(gob_c)
        parts += [
            mesh_part(bb, "Brush border (microvilli)", "Villi", "#eab0a6", TXT["brush"], "mucosa", rank=2.7,
                      detail=(0.06, 0.0, 0.0, 2)),
            mesh_part(epi, "Villus epithelium (enterocytes)", "Villi", "#d98c88", TXT["villus_epi"], "mucosa",
                      rank=2.5, detail=(0.10, 190.0, 0.85, 2)),
            mesh_part(v["core"], "Villus lamina propria core", "Villi", "#f3c9b8", TXT["villus_core"], "mucosa",
                      rank=2.4, detail=(0.12, 110.0, 0.45, 0)),
            mesh_part(v["lacteal"], "Central lacteals", "Villi", "#f7f2df", TXT["lacteal"], "csf", rank=2.45,
                      detail=(0.02, 0.0, 0.0, 0)),
            mesh_part(v["caps"], "Villus capillary network", "Villi", "#d9463d", TXT["villus_cap"], "artery",
                      rank=2.45),
            mesh_part(v["muscle"], "Villus smooth muscle", "Villi", "#b95a50", TXT["villus_muscle"], "muscle",
                      rank=2.45, label=False),
            mesh_part(gob, "Goblet cells", "Villi", "#e6ecf6", TXT["goblet_ileum"] if kind == "ileum"
                      else TXT["goblet"], "mucosa", rank=2.8, detail=(0.03, 0.0, 0.0, 0)),
        ]

    # ---- duodenal glands, lymphoid tissue
    if kind == "duodenum":
        parts += _brunner(y_circ1, y_sub, y_mm, crypt_pts, y_s, sp["crypt"], rng)
    if follicles:
        parts += _lymphoid(follicles, geoms, y_s, kind, t_epi, rng)
    # thousands of little cell meshes: fuse each part into one array first, so the shared warp runs once per part
    for p in parts:
        pos, nrm, idx = p.mesh.arrays()
        p.mesh = Mesh().add(pos, idx, nrm) if len(idx) else Mesh()
    return settle(parts, seed={"jejunum": 201, "duodenum": 202, "ileum": 203, "colon": 204}[kind], amp_xz=0.028,
                  amp_y=0.06, freq=1.5, grain=0.004)


# --------------------------------------------------------------------------------------------- villi
def _villi(pts, y_s, sp, kind, rng):
    """Every villus is a set of nested closed sheaths around one curved axis - brush border, enterocytes, lamina
    propria core - with the lacteal, the capillary net, smooth muscle strands and goblet cells placed in the same
    (s, theta, r) frame, so nothing pokes out through the wrong layer however the villus leans."""
    out = {k: Mesh() for k in ("bb", "epi", "core", "lacteal", "caps", "muscle", "goblet")}
    if not len(pts):
        return out
    leaf = sp["leaf"]
    ys = y_s(pts[:, 0], pts[:, 1])
    ns = _normals(y_s, pts[:, 0], pts[:, 1])
    ex, ez = np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0])
    for i, ((x, z), y, n) in enumerate(zip(pts, ys, ns)):
        on_z, on_x = abs(z) < 0.03, abs(x) < 0.03       # sectioned by a cut plane: keep it in that plane
        n = n.copy()
        if on_z:
            n[2] = 0.0
        n /= np.linalg.norm(n)
        # villi stand normal to the mucosa, but on a fold's flanks they are drawn up a little towards the lumen
        up = n + np.array([0.0, 0.9 * (1.0 - n[1]), 0.0])
        up /= np.linalg.norm(up)
        lean = rng.normal(size=3) * 0.08
        bend = rng.normal(size=3) * (0.045 if not leaf else 0.02)
        L = sp["v_h"] * rng.uniform(0.82, 1.12) * (0.8 + 0.2 * n[1])      # a little shorter on a fold's flanks
        bury = 0.028
        p0 = np.array([x, y, z]) - n * bury
        Lt = L + bury
        in_cut = x < -0.03 and z > 0.03             # rooted in the quadrant the cut-away removes
        for vec in (lean, bend):
            vec -= up * (vec @ up)
            if on_z:
                vec[2] = 0.0
            if on_x:
                vec[0] = 0.0
            vec *= np.clip(min(X1 - abs(x), Z1 - abs(z)) / 0.15, 0.0, 1.0)   # nothing leans out of the block
        d = up + lean
        d /= np.linalg.norm(d)
        if in_cut:
            # a villus rooted in the removed quadrant must not lean out of it, or its top would float in the air
            m = sp["v_r"] * 1.4
            for c, sgn in ((0, -1.0), (2, 1.0)):
                if (p0[c] + d[c] * Lt + bend[c]) * sgn < m:
                    lean[c] = bend[c] = 0.0
                    d = up + lean
                    d /= np.linalg.norm(d)
                if (p0[c] + d[c] * Lt) * sgn < m:       # still over the line (a fold's flank): stand it up
                    d[c] = (m * sgn - p0[c]) / Lt
                    d[1] = math.sqrt(max(1.0 - d[0] ** 2 - d[2] ** 2, 0.05))
                    d /= np.linalg.norm(d)

        def axis(a, p0=p0, d=d, bend=bend, Lt=Lt):
            a = np.asarray(a, float)[:, None]
            return p0 + d * a + bend * np.clip(a / Lt, 0, 1.1) ** 2

        w = rng.uniform(0.88, 1.12)
        if leaf:
            half_w = sp["v_r"] * w
            half_t = sp["v_r"] * sp["v_flat"]
            prof_a = lambda A, Lt=Lt, hw=half_w: hw * (0.78 + 0.30 * np.sin(np.clip(A / Lt, 0, 1) * math.pi * 0.85))
            prof_b = lambda A, ht=half_t: ht + 0.0 * A
            tip_r = half_w * 0.95
        else:
            r0 = sp["v_r"] * w
            club = 0.12 if kind == "ileum" else -0.08          # ileal villi are club-shaped, jejunal ones taper
            prof_a = lambda A, Lt=Lt, r0=r0, club=club: r0 * (1.0 + club * np.clip(A / Lt, 0, 1))
            prof_b = lambda A, Lt=Lt, r0=r0, club=club: r0 * sp["v_flat"] * (1.0 + club * np.clip(A / Lt, 0, 1))
            tip_r = r0 * (1.0 + club) * 0.95
        # broad face across the cut plane for sectioned villi (so the section shows the full width), else random
        # (duodenal leaves mostly face the same way, in loose rows like ridges)
        ang = rng.normal(0.0, 0.35) if leaf else rng.uniform(0, math.pi)
        face = ex if on_z else (ez if on_x else np.array([math.cos(ang), 0.0, math.sin(ang)]))
        ph_fur = rng.uniform(0, 2 * math.pi)

        def radius(T, A, off, end, phi, prof_a=prof_a, prof_b=prof_b, tip_r=tip_r, ph_fur=ph_fur, bury=bury,
                   rough=0.35 if leaf else 1.0):
            """Villus section radius at angle T and arc position A, grown by `off` (brush border > 0, core < 0)."""
            a = prof_a(A) + off
            b = prof_b(A) + off
            c, s = np.cos(T - phi), np.sin(T - phi)
            r = a * b / np.sqrt((b * c) ** 2 + (a * s) ** 2)
            # a flared foot where the villus grows out of the mucosa, shallow transverse furrows, a slightly
            # irregular calibre and section - no two villi and no two levels of one villus quite alike
            flare = 1.0 + 0.28 * np.clip(1.0 - (A - bury) / 0.07, 0.0, 1.0) ** 2
            fur = 1.0 + rough * 0.018 * np.sin(A * 115.0 + ph_fur + 0.8 * np.sin(T * 2)) * np.clip(A / 0.06, 0, 1)
            wav = 1.0 + rough * (0.045 * np.sin(A * 13.0 + ph_fur * 2.0) + 0.04 * np.sin(2 * T + A * 9.0 + ph_fur))
            return np.maximum((r * flare * fur * wav) * _dome(end - A, tip_r + off), 0.0006)

        def sheath(off, n_theta, n_s, end=None, start=0.0):
            end = Lt + off if end is None else end
            # rings evenly up the shaft, then spaced by angle over the rounded tip so it stays a smooth dome
            tr = min(tip_r + off, (end - start) * 0.4)
            n_tip = 6
            A = np.concatenate([np.linspace(start, end - tr, n_s - n_tip, endpoint=False),
                                end - tr + tr * np.sin(np.linspace(0.0, math.pi / 2, n_tip))])
            sw = Sweep(axis(A), n_theta, n_s)
            phi = _phase(sw, face)
            Ag = np.interp(sw.S, np.linspace(0.0, 1.0, n_s), A)
            return sw, sw.solid(lambda T, S: radius(T, Ag, off, end, phi)), phi, A

        sw, m, phi, A_s = sheath(0.0, 16, 18)
        out["epi"].extend(m)
        out["bb"].extend(sheath(T_BB, 20, 21)[1])
        out["core"].extend(sheath(-T_EPI, 10, 13)[1])

        def at_s(s_frac):
            return np.interp(s_frac, np.linspace(0, 1, len(A_s)), A_s)

        # central lacteal: blind-ended, in the axis, up to ~80 % of the height
        lac_end = Lt * 0.8
        lac_t = np.linspace(0.0, 1.0, 12)
        lac_A = _ease_end(lac_t) * lac_end
        lsw = Sweep(axis(lac_A), 8, 12)
        lphi = _phase(lsw, face)
        lac_a = lambda A: 0.30 * (prof_a(A) - T_EPI) + 0.004
        lac_b = lambda A: 0.42 * (prof_b(A) - T_EPI) + 0.002
        lAg = _ease_end(lsw.S) * lac_end

        def lac_r(T, S):
            a, b = lac_a(lAg), lac_b(lAg)
            c, s = np.cos(T - lphi), np.sin(T - lphi)
            return a * b / np.sqrt((b * c) ** 2 + (a * s) ** 2) * _dome(lac_end - lAg, a * 1.6)
        out["lacteal"].extend(lsw.solid(lac_r))

        # capillary net: two strands spiralling in opposite senses beneath the epithelium, meeting at the tip
        s = np.linspace(0.05, 0.97, 26)
        A = at_s(s)
        for sense, th0 in ((1.0, phi + 0.3), (-1.0, phi + math.pi + 0.3)):
            th = th0 + sense * (2.6 * math.pi) * s
            r = radius(th, A, -T_EPI - 0.0045, Lt, phi)
            out["caps"].extend(tube(sw.curve(s, th, r), 0.0034, 5))
        # smooth muscle strands beside the lacteal
        for th in (phi + math.pi / 2, phi - math.pi / 2):
            s2 = np.linspace(0.02, 0.8, 8)
            r = radius(np.full_like(s2, th), at_s(s2), -T_EPI, Lt, phi) * 0.55
            out["muscle"].extend(tube(sw.curve(s2, np.full_like(s2, th), r), 0.0028, 4))
        # goblet cells: theca bulging through the brush border, stem down among the enterocytes
        n_gob = rng.poisson(sp["gob"])
        for _ in range(n_gob):
            s_g = rng.uniform(0.22, 0.86)
            th = rng.uniform(0, 2 * math.pi)
            A_g = float(at_s(s_g))
            r = float(radius(np.array([th]), np.array([A_g]), 0.0, Lt, phi)[0])
            p, e = _radial(sw, s_g, th, r - 0.0058)
            out["goblet"].extend(_cell(p, e, (0.0072, 0.011, 0.0072), res=5))
    return out


# --------------------------------------------------------------------------------------------- crypts
def _crypts(pts, y_s, depth, colon, kind, rng, pit):
    """Blind-ended tubes of epithelium with a real lumen, standing normal to the surface and opening on it through
    a slightly raised collar. Their base holds the stem cells (and in the small intestine the Paneth cells);
    goblet cells sit in the wall. Cells inside crypts are seen only in section, so the crypts near the cut planes
    get the full complement and the rest a few."""
    crypts, pan, stem, gob = Mesh(), Mesh(), Mesh(), Mesh()
    if not len(pts):
        return crypts, pan, stem, gob
    r_out, r_in = (0.025, 0.0085) if colon else (0.020, 0.0055)
    ys = y_s(pts[:, 0], pts[:, 1])
    ns = _normals(y_s, pts[:, 0], pts[:, 1])
    ex, ez = np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0])
    for (x, z), y, n in zip(pts, ys, ns):
        on_z, on_x = abs(z) < 0.03, abs(x) < 0.03
        n = n.copy()
        if on_z:
            n[2] = 0.0
        n /= np.linalg.norm(n)
        L = depth - 0.012 - pit * 0.5 + rng.uniform(-0.012, 0.006)
        top = np.array([x, y, z]) - n * (pit * 0.5)
        base = top - n * L
        wig = rng.normal(size=3) * 0.006
        wig -= n * (wig @ n)
        if on_z:
            wig[2] = 0.0
        if on_x:
            wig[0] = 0.0
        t = np.linspace(0.0, 1.0, 12)
        A = _ease_start(t) * L
        path = base + n * A[:, None] + wig * np.sin(np.pi * A / L)[:, None]
        sw = Sweep(path, 10, 12)
        Ag = _ease_start(sw.S) * L
        w = rng.uniform(0.92, 1.08)
        bulb = 1.0 + 0.12 * np.exp(-(Ag / 0.05) ** 2) * (0.0 if colon else 1.0)
        # the mouth: the wall thins and the lumen widens where the crypt opens into the funnel in the surface
        mouth = np.clip(1.0 - (L - Ag) / 0.03, 0.0, 1.0) ** 2
        R_out = r_out * w * bulb * _dome(Ag, r_out * 1.1) * (1.0 - 0.4 * mouth)     # narrows into the funnel
        R_in = np.maximum(r_in * w * np.clip((Ag - 0.022) / 0.02, 0.0, 1.0) * (1.0 + 0.5 * mouth), 0.0007)
        crypts.extend(sw.shell(lambda T, S: R_in, lambda T, S: R_out))

        full = on_z or on_x
        theta0 = _phase(sw, ex if on_z else ez) if (on_z or on_x) else rng.uniform(0, 2 * math.pi)
        r_mid = (r_in + r_out) * 0.5 * w
        # crypt base: Paneth cells (small intestine) ringed around the base with stem cells between them
        k_ring = 6
        for k in range(k_ring):
            th = theta0 + k * 2 * math.pi / k_ring
            if not colon:
                s_p = float(np.interp(0.030, A, t))
                p, e = _radial(sw, s_p, th, r_mid)
                pan.extend(_cell(p, e, (0.0078, 0.0085, 0.0078)))
            th_s = th + math.pi / k_ring
            s_s = float(np.interp(0.034 if not colon else 0.028, A, t))
            p, e = _radial(sw, s_s, th_s, r_mid)
            if k % 2 == 0:
                stem.extend(_cell(p, sw.curve(np.array([s_s + 0.1]), np.array([th_s]), np.array([r_mid]))[0] - p,
                                  (0.0036, 0.0095, 0.0036), res=3))
        # goblet cells up the wall - the colon's crypts are packed with them
        if colon:
            levels = np.linspace(0.07, L - 0.03, 9) if full else np.linspace(0.12, L - 0.04, 2)
            per = 5 if full else 2
        else:
            levels = np.linspace(0.07, L - 0.03, 3) if full else np.array([L * 0.6])
            per = 2 if full else 1
        for j, a in enumerate(levels):
            s_g = float(np.interp(a, A, t))
            for k in range(per):
                th = theta0 + (k + 0.5 * (j % 2)) * 2 * math.pi / per + rng.uniform(-0.25, 0.25)
                p, e = _radial(sw, s_g, th, r_mid + 0.001)
                gob.extend(_cell(p, e, (0.0068, 0.0082, 0.0068) if colon else (0.0055, 0.008, 0.0055)))
    return crypts, pan, stem, gob


# --------------------------------------------------------------------------------------------- jejunum: plica
def _plica_vessels(y_sub, H):
    """An arteriole and venule running along the core of the plica circularis, with twigs to the mucosa on it."""
    art, vein = Mesh(), Mesh()
    zs = np.linspace(Z0 + 0.01, Z1 - 0.01, 60)
    xc = -0.45 + 0.045 * np.sin(2.3 * zs + 0.5) * np.clip(np.abs(zs) / 0.12, 0, 1)
    h = H * (1.0 + 0.06 * np.sin(3.1 * zs + 0.4))
    y_top = np.array([at(y_sub, a, b) for a, b in zip(xc, zs)])
    pa = np.stack([xc - 0.025, y_top - h * 0.55, zs], -1)
    pv = np.stack([xc + 0.03, y_top - h * 0.62, zs + 0.01], -1)
    art.extend(tube(pa, 0.017, 12))
    vein.extend(tube(pv, 0.024, 14))
    for k, z in enumerate(np.linspace(-0.5, 0.5, 6)):
        i = int(np.argmin(np.abs(zs - z)))
        a = pa[i]
        top = np.array([xc[i] + (0.05 if k % 2 else -0.05), y_top[i] + 0.012, zs[i] + 0.02])
        art.extend(tube_mesh(wavy_path(a, top, 14, 0.008, 1.0, seed=40 + k), 0.007, 8))
    return art, vein


# --------------------------------------------------------------------------------------------- duodenum: Brunner
def _brunner(y_circ1, y_sub, y_mm, crypt_pts, y_s, depth, rng):
    """Lobules of coiled tubuloalveolar gland filling the submucosa, each drained by a duct that pierces the
    muscularis mucosae to open into the base of a crypt."""
    lobules = [(-0.72, 0.0), (-0.34, 0.03), (0.02, 0.24), (0.0, -0.3), (0.42, -0.02), (0.72, 0.3), (-0.55, -0.36),
               (0.5, -0.38), (-0.3, 0.42), (0.34, 0.42), (-0.82, 0.36)]
    lo = (X0, Y_CIRC1 - 0.02, Z0)
    hi = (X1, at(y_sub, 0, 0) + 0.12, Z1)
    glands = Volume(lo, hi, 0.006)
    ducts = Mesh()
    tree = cKDTree(crypt_pts)
    for i, (cx, cz) in enumerate(lobules):
        bot = at(y_circ1, cx, cz) + 0.02
        top = at(y_sub, cx, cz) + (0.07 if i in (1, 4) else -0.01)      # a few lobules rise above the mm
        c = np.array([cx, (bot + top) / 2, cz])
        ry = (top - bot) / 2
        rxz = rng.uniform(0.13, 0.17)
        # a lobule of mucous acini and tubules packed round its duct, the lobules separated by septa
        shapes = []
        for k in range(100):
            q = c + np.clip(rng.normal(size=3) * np.array([rxz, ry, rxz * 0.85]) * 0.42, -1, 1)
            q = np.clip(q, [X0 + 0.03, bot + 0.02, Z0 + 0.03], [X1 - 0.03, top - 0.02, Z1 - 0.03])
            r = rng.uniform(0.019, 0.028)
            a = rng.uniform(0, math.pi)
            rot = np.array([[math.cos(a), 0, -math.sin(a)], [0, 1, 0], [math.sin(a), 0, math.cos(a)]])
            shapes.append(ellipsoid(q, (r * 1.3, r, r * 0.9), rot))
        glands.add_all(shapes, "smooth", 0.012)
        # the duct: from the top of the lobule, through the muscularis mucosae, to the base of the nearest crypt
        _, j = tree.query((cx, cz))
        qx, qz = crypt_pts[j]
        end = np.array([qx, at(y_s, qx, qz) - depth + 0.03, qz])
        start = c + np.array([0.0, ry * 0.7, 0.0])
        mid = (start + end) / 2 + np.array([0.02, 0.0, -0.02])
        ducts.extend(tube_mesh(wavy_path(start, mid, 10, 0.006, 1.0, seed=i), 0.0085, 10))
        ducts.extend(tube_mesh(wavy_path(mid, end, 10, 0.004, 1.0, seed=i + 50), 0.0075, 10))
    glands.displace(0.003, 35.0, 2, seed=9)
    glands.intersect_box((X0 + 0.005, lo[1], Z0 + 0.005), (X1 - 0.005, hi[1], Z1 - 0.005))
    return [sdf_part(glands, "Brunner glands", "Submucosa", "#b9d5ec", TXT["brunner"], "gland", smooth=0.7, rank=-1,
                     detail=(0.08, 120.0, 0.8, 0)),
            mesh_part(ducts, "Brunner gland ducts", "Submucosa", "#8fb6d8", TXT["brunner_duct"], "gland", rank=-0.5,
                      label=False)]


# --------------------------------------------------------------------------------------------- lymphoid tissue
def _follicle_geom(f, y_sub, y_s, t_epi):
    """Base height, total height (to just under the dome epithelium) and follicle height of a lymphoid follicle."""
    fx, fz, fr = f
    y_base = at(y_sub, fx, fz) - 0.1
    H = at(y_s, fx, fz) - t_epi - 0.012 - y_base
    return y_base, H, H * 0.62


def _lymphoid(follicles, geoms, y_s, kind, t_epi, rng):
    """Pear-shaped follicles straddling the muscularis mucosae, a pale germinal centre in each, the subepithelial
    dome above and - in the ileum - the dome epithelium with its M cells."""
    fol, gc, dome, fae, mcell = Mesh(), Mesh(), Mesh(), Mesh(), Mesh()
    up = np.array([0.0, 1.0, 0.0])
    for i, ((fx, fz, fr), (y_base, H, Hf)) in enumerate(zip(follicles, geoms)):
        p0 = np.array([fx, y_base, fz])
        wob = rng.uniform(0, 2 * math.pi)

        def follicle(T, A, Hf=Hf, fr=fr, wob=wob):
            u = A / Hf                                   # a slightly pear-shaped ball, fuller below
            r = fr * np.sqrt(np.clip(1.0 - (2.0 * u - 1.0) ** 2, 0.0, 1.0)) * (1.0 + 0.08 * (0.5 - u))
            return np.maximum(r * (1.0 + 0.05 * np.sin(3 * T + wob) + 0.03 * np.sin(5 * T + 2 * wob)), 0.0008)

        s0 = Hf * 0.8

        def sed(T, A, H=H, s0=s0, fr=fr, wob=wob):
            u = (A - s0) / (H - s0)                     # a cone of mixed cells rising from the follicle to the dome
            r = fr * (0.8 - 0.2 * u) * _dome(H - A, fr * 0.45) * _dome(A - s0, fr * 0.3)
            return np.maximum(r * (1.0 + 0.04 * np.sin(3 * T + wob)), 0.0008)

        gc_c, gc_h, gc_r = Hf * 0.48, Hf * 0.3, fr * 0.58

        def centre(T, A, gc_c=gc_c, gc_h=gc_h, gc_r=gc_r, wob=wob):
            r = gc_r * np.sqrt(np.clip(1.0 - ((A - gc_c) / gc_h) ** 2, 0.0, 1.0))
            return np.maximum(r * (1.0 + 0.04 * np.sin(4 * T - wob)), 0.0007)

        def sweep(a0, a1, n_t=28, n_s=24):
            t = np.linspace(0.0, 1.0, n_s)
            A = a0 + t * (a1 - a0)
            sw = Sweep(p0 + up * A[:, None], n_t, n_s)
            return sw, a0 + sw.S * (a1 - a0)

        # the mantle is a shell around the germinal centre rather than a solid holding it, so a section shows a
        # flat ring round a flat centre instead of looking down into a hollow
        sw, Ag = sweep(0.0, Hf, n_s=30)
        fol.extend(sw.shell(lambda T, S: centre(T, Ag), lambda T, S: follicle(T, Ag)))
        sw, Ag = sweep(gc_c - gc_h, gc_c + gc_h, 24, 16)
        gc.extend(sw.solid(lambda T, S: np.maximum(centre(T, Ag) - 0.0015, 0.0006)))
        if kind == "ileum":
            sw, Ag = sweep(s0, H)
            dome.extend(sw.solid(lambda T, S: sed(T, Ag)))
        if kind == "ileum":
            # dome epithelium: a cap of epithelium over the follicle, with no villi
            m = lambda X, Z: _mask(X, Z, fx, fz, fr * 0.95)
            fae.extend(_disc(fx, fz, fr * 0.95, lambda X, Z: y_s(X, Z) + T_BB,
                             lambda X, Z: y_s(X, Z) + T_BB - (t_epi + T_BB) * m(X, Z)))
            for p in poisson_disk((fx - fr * 0.7, fz - fr * 0.7), (fx + fr * 0.7, fz + fr * 0.7), 0.045,
                                  seed=60 + i):
                if math.hypot(p[0] - fx, p[1] - fz) > fr * 0.72:
                    continue
                y = at(y_s, p[0], p[1])
                nrm = _normals(y_s, np.array([p[0]]), np.array([p[1]]))[0]
                mcell.extend(_cell(np.array([p[0], y, p[1]]) + nrm * 0.001, nrm, (0.012, 0.0045, 0.009)))
    out = [mesh_part(fol, "Peyer patch follicles" if kind == "ileum" else "Solitary lymphoid follicle",
                     "Lymphoid tissue", "#86b873", TXT["peyer"] if kind == "ileum" else TXT["follicle"], "lymph",
                     rank=0.5, detail=(0.06, 190.0, 0.97, 0)),
           mesh_part(gc, "Germinal centres", "Lymphoid tissue", "#cfe6b2", TXT["germinal"], "lymph", rank=0.6,
                     detail=(0.06, 120.0, 0.6, 0)),
           mesh_part(dome, "Subepithelial dome", "Lymphoid tissue", "#a9cc92", TXT["dome"], "lymph", rank=0.7,
                     detail=(0.08, 170.0, 0.9, 0))]
    if kind == "ileum":
        out += [mesh_part(fae, "Follicle-associated epithelium", "Lymphoid tissue", "#d9a9bb", TXT["fae"], "mucosa",
                          rank=2.6, detail=(0.10, 190.0, 0.85, 0)),
                mesh_part(mcell, "M cells", "Lymphoid tissue", "#9c7fd1", TXT["m_cells"], "mucosa", rank=2.9,
                          detail=(0.04, 0.0, 0.0, 0))]
    return out


def _mask(X, Z, fx, fz, r):
    t = np.clip(1.0 - np.hypot(np.asarray(X, float) - fx, np.asarray(Z, float) - fz) / r, 0.0, 1.0)
    return t * t * (3 - 2 * t)


# --------------------------------------------------------------------------------------------- colon: fat tag
def _appendix_epiploica(y_long0):
    """A small peritoneal pouch of fat hanging from the serosa beside the taenia."""
    cx, cz = 0.5, 0.36
    top = at(y_long0, cx, cz) - 0.02
    vol = Volume((cx - 0.2, top - 0.34, cz - 0.2), (cx + 0.2, top + 0.03, cz + 0.2), 0.0065)
    c = np.array([cx + 0.03, top - 0.2, cz + 0.02])
    vol.add(round_cone((cx, top + 0.02, cz), c, 0.055, 0.08), "smooth", 0.05)
    vol.add(ellipsoid(c, (0.11, 0.1, 0.09)), "smooth", 0.06)
    vol.add(ellipsoid(c + np.array([-0.05, -0.05, 0.03]), (0.07, 0.065, 0.07)), "smooth", 0.04)
    x, y, z = vol.axes()
    vol.d -= cell_lattice(x, y, z, 0.05, 0.006, seed=5)          # the bulge of the fat lobules through the serosa
    vol.intersect_box((X0, -1.0, Z0), (X1, top + 0.02, Z1))
    return sdf_part(vol, "Appendix epiploica (fat tag)", "Serosa & muscularis externa", "#efcf78",
                    TXT["appendix_epi"], "fat", smooth=0.8, rank=-4.5, detail=(0.06, 40.0, 0.12, 0))
