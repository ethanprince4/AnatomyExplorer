"""Skin block models: thin (hairy), thick (glabrous), scalp and axillary skin.

Epidermal strata and dermal layers are height fields. Thin skin carries a rhomboid network of furrows with the hairs
emerging where furrows cross; thick skin carries curved friction ridges with sweat pores along their crests, and its
dermo-epidermal junction is built from the same ridge pattern: a deep rete ridge under every surface ridge (it carries
the sweat duct), a shallower one under every furrow, and double rows of dermal papillae between them.

Hair follicles are swept tubes (hair shaft, inner and outer root sheaths) on a bulb and papilla modelled as signed
distances, so follicles stay cheap enough to pack a scalp with follicular units. The hypodermis is fat lobules with
the fibrous septa between them built as their complement."""
import math

import numpy as np
from scipy.spatial import Delaunay, cKDTree

from .base import Part
from .cells import jittered_bcc, poisson_disk
from .geometry import Mesh, _grid_indices, tube
from .kit import (Bumps, Volume, add, at, blob_cluster, capsule, coil_path, dendritic_cell, ellipsoid, mesh_part,
                  noise2, sdf_part, shift, smooth_path, tube_mesh, wavy_path)
from .organic import Sweep, fibre_relief, settle
from .sdf import fbm3

X0, X1, Z0, Z1 = -1.0, 1.0, -0.7, 0.7

D = {
    "corneum": "Stratum corneum: 15–20 layers of dead, flattened, anucleate corneocytes – bags of keratin filaments "
               "(held in a filaggrin matrix) with a cross-linked cornified envelope, glued by the lipid lamellae "
               "secreted in the granular layer. It is the skin's water and microbial barrier and is shed "
               "continuously as squames (desquamation). The surface is thrown into a network of furrows that "
               "divides it into small rhomboid fields; hairs emerge where furrows cross, and sweat pores open on the "
               "fields between them.",
    "corneum_thick": "Stratum corneum of thick skin: hundreds of layers of flattened anucleate corneocytes, so thick "
                     "that it forms most of the height of the epidermis on the palm and sole. Its surface is raised "
                     "into friction (epidermal) ridges – the fingerprint pattern, fixed before birth and unique to "
                     "each person – which improve grip. Sweat pores open in a row along the crest of every ridge.",
    "lucidum": "Stratum lucidum: a thin, clear, glassy eosinophilic band between the granular layer and the corneum, "
               "found only in the thick skin of the palms and soles. Its tightly packed cells have lost nuclei and "
               "organelles and are filled with eleidin, an intermediate stage of keratinisation.",
    "granulosum": "Stratum granulosum: 1–3 (thin skin) to 3–5 (thick skin) layers of flattened cells filled with "
                  "basophilic keratohyalin granules (profilaggrin, loricrin) and lamellar bodies. The lamellar bodies "
                  "discharge lipid into the intercellular space to seal the barrier, and tight junctions form here; "
                  "the nuclei and organelles are then destroyed. Filaggrin loss-of-function causes ichthyosis "
                  "vulgaris and predisposes to atopic eczema.",
    "spinosum": "Stratum spinosum: the thickest living layer – several layers of polyhedral keratinocytes joined by "
                "numerous desmosomes, seen as 'prickles' after fixation shrinkage, and rich in keratin filaments "
                "(K1/K10). Dendritic Langerhans cells (antigen-presenting) live here. Pemphigus vulgaris "
                "autoantibodies against desmoglein 3 split this layer just above the basal cells.",
    "basale": "Stratum basale (germinativum): a single row of cuboidal-to-columnar stem and transit-amplifying "
              "keratinocytes (K5/K14) on the basement membrane, anchored by hemidesmosomes (targeted in bullous "
              "pemphigoid). Its undersurface forms the rete ridges that interlock with the dermal papillae. "
              "Contains melanocytes (about 1 in 10 basal cells) and Merkel cells. Renewal from basale to shedding "
              "takes about 4 weeks.",
    "melanocytes": "Melanocytes: neural-crest-derived dendritic cells sitting in the basal layer, about 1 per 10 basal "
                   "keratinocytes. Their processes reach up between the spinous cells and hand melanosomes to about "
                   "36 keratinocytes each (the epidermal melanin unit), where they form supranuclear caps against "
                   "UV. Skin colour depends on melanin type and transfer, not on melanocyte number. Melanoma arises "
                   "from these cells.",
    "papillary": "Papillary dermis: a thin layer of loose connective tissue – fine type III and I collagen, "
                 "oxytalan elastic fibres, many fibroblasts and mast cells. It fills the dermal papillae that "
                 "interlock with the epidermal rete ridges (resisting shear), and carries the capillary loops that "
                 "nourish the avascular epidermis by diffusion, and sensory endings.",
    "reticular": "Reticular dermis: the thick bulk of the dermis – dense irregular connective tissue of coarse type I "
                 "collagen bundles and thick elastic fibres, giving the skin its tensile strength and recoil. It "
                 "holds the hair follicles, glands, deep vascular plexus and nerves. The predominant orientation of "
                 "its bundles gives Langer's cleavage lines; tears in it form striae.",
    "hypodermis": "Hypodermis (subcutis, superficial fascia): lobules of white fat separated by fibrous septa "
                  "(retinacula cutis) that tie the dermis to the deep fascia and carry the larger vessels and nerves. "
                  "It insulates, cushions and stores energy, and lets the skin glide over deeper structures. "
                  "Inflammation of the septa is septal panniculitis (erythema nodosum). Not strictly part of the skin.",
    "hypodermis_scalp": "Dense subcutaneous connective tissue of the scalp (the 'C' of SCALP): fat lobules held in "
                        "a tough network of fibrous septa that bind the skin firmly to the galea aponeurotica. The "
                        "septa carry the large scalp vessels and nerves and hold their walls open, so scalp wounds "
                        "bleed profusely. The bulbs of terminal hair follicles lie in this layer.",
    "fat": "Adipocytes of the hypodermis: large unilocular fat cells (up to 100–120 µm) whose single lipid droplet "
           "pushes a flattened nucleus to the rim, packed into lobules (each fed by its own arteriole) and separated "
           "by connective-tissue septa.",
    "galea": "Galea aponeurotica (epicranial aponeurosis, the 'A' of SCALP): a tough sheet of dense regular "
             "connective tissue joining the frontal and occipital bellies of occipitofrontalis. The skin and dense "
             "subcutaneous tissue are bound to it and move with it; beneath it lies the loose areolar 'danger "
             "space' in which scalp infection and blood can spread. A wound that splits the galea gapes because "
             "the muscle bellies pull its edges apart.",
    "shaft": "Hair shaft: dead, fully keratinised cells made by the matrix of the bulb – a central medulla (only in "
             "thick terminal hairs), a cortex of hard keratin carrying the pigment, and a cuticle of overlapping "
             "scales pointing towards the tip. Its colour comes from melanin transferred by melanocytes in the "
             "bulb.",
    "shaft_vellus": "Hair shaft (vellus/intermediate hair of body skin): short, fine and lightly pigmented, with no "
                    "medulla. Its cuticle is made of overlapping keratinised scales pointing towards the tip. "
                    "Androgens convert vellus follicles to terminal ones at puberty (axilla, pubis, beard).",
    "irs": "Inner root sheath: three keratinising layers – Henle's (outer), Huxley's (with trichohyalin granules) and "
           "the sheath cuticle, which interlocks with the hair cuticle – that mould and guide the growing hair. It "
           "grows up with the hair and disintegrates at the isthmus, where the sebaceous duct opens.",
    "ors": "Outer root sheath: the downward continuation of the epidermis around the follicle; its pale "
           "glycogen-rich cells are not keratinised below the isthmus. The bulge – where the arrector pili inserts "
           "– holds the follicular stem cells that regenerate the follicle each cycle and re-epithelialise wounds, "
           "which is why partial-thickness burns heal without grafting. Above the sebaceous duct it lines the "
           "infundibulum, the funnel that opens at the surface.",
    "bulb": "Hair bulb & matrix: the onion-shaped base of an anagen follicle, cupped over the dermal papilla. Its "
            "matrix cells divide faster than almost any other cells in the body to form the hair and the inner "
            "root sheath, and its melanocytes pigment the cortex. Chemotherapy halts them (anagen effluvium).",
    "dermal_papilla": "Dermal papilla of the hair: a pear-shaped knot of specialised fibroblasts and capillaries "
                      "inside the bulb, joined by a stalk to the connective-tissue sheath. It signals the matrix to "
                      "grow and its volume sets the size of the hair – it shrinks as follicles miniaturise in "
                      "androgenetic alopecia.",
    "sebaceous": "Sebaceous gland: a lobulated holocrine gland in the angle between follicle and arrector pili. "
                 "Peripheral basal cells divide and move inwards, filling with lipid until they disintegrate, and the "
                 "whole cell becomes sebum, which drains through a short duct into the follicle at the isthmus. "
                 "Androgen-driven – they enlarge at puberty, and blockage of the pilosebaceous unit is acne.",
    "arrector": "Arrector pili: a slip of smooth muscle from the follicle bulge to the papillary dermis on the side "
                "towards which the hair slopes (the obtuse angle). Sympathetic (adrenergic) contraction pulls the "
                "follicle upright ('goose bumps') and squeezes sebum out of the gland it wraps.",
    "eccrine": "Eccrine sweat gland (secretory coil): a coiled simple tubular gland in the deep dermis or upper "
               "hypodermis. Clear cells secrete the watery, isotonic primary sweat; dark cells secrete glycoproteins; "
               "myoepithelial cells lie beneath them. Supplied by sympathetic cholinergic fibres – about 3 million "
               "glands, densest on palms and soles, the body's main means of losing heat.",
    "eccrine_duct": "Eccrine sweat duct: two layers of small, darker cuboidal cells. The dermal duct reabsorbs Na+ "
                    "and Cl- (via ENaC and CFTR) so sweat reaching the surface is hypotonic – in cystic fibrosis it "
                    "stays salty (sweat test). It enters the epidermis at the tip of a rete ridge and corkscrews "
                    "through it (the acrosyringium) to open at a sweat pore.",
    "apocrine": "Apocrine sweat gland: a large coil of wide-lumened tubules (up to ten times the calibre of an eccrine "
                "gland) in the deep dermis and hypodermis of the axilla, areola and anogenital skin. Its cuboidal to "
                "columnar cells show apical 'snouts' and it releases a viscous, protein- and lipid-rich secretion "
                "that is odourless until skin bacteria break it down. Active from puberty; adrenergic control.",
    "apocrine_duct": "Apocrine duct: a narrow duct lined by a double layer of cuboidal cells that opens into the hair "
                     "follicle infundibulum, above the entry of the sebaceous duct – not onto the skin surface.",
    "artery": "Cutaneous arterioles: branches of the cutaneous plexus (deep plexus) at the junction of dermis and "
              "hypodermis, which also feeds the fat lobules, follicles and glands. Arterioles rise from it "
              "through the reticular dermis to the subpapillary plexus. Arteriovenous anastomoses (glomus bodies, "
              "abundant in fingertips) regulate heat loss.",
    "vein": "Cutaneous venules: collect blood from the capillary loops into the subpapillary and deep venous plexuses, "
            "which run alongside the arterial plexuses. Postcapillary venules are where leukocytes leave the blood "
            "in inflammation.",
    "subpapillary": "Subpapillary plexus: a horizontal network of arterioles and venules at the junction of the "
                    "papillary and reticular dermis. It gives off a capillary loop to each dermal papilla, and its "
                    "venous part holds much of the skin's blood – it largely determines skin colour and heat loss.",
    "capillary": "Capillary loops of the dermal papillae: a hairpin capillary rises into each papilla and returns to "
                 "the subpapillary plexus. They supply the avascular epidermis by diffusion; their dilation causes "
                 "flushing, and blanching on pressure distinguishes erythema from purpura.",
    "nerve": "Cutaneous nerves: mixed bundles of myelinated and unmyelinated sensory fibres running with the vessels "
             "of the deep plexus, plus postganglionic sympathetic fibres to the sweat glands (cholinergic), "
             "arterioles and arrector pili (adrenergic). Branches rise to the papillary dermis to supply the "
             "corpuscles and free endings.",
    "free_endings": "Free nerve endings: thin myelinated (Aδ) and unmyelinated (C) fibres that lose their Schwann "
                    "cells at the basement membrane and end between the keratinocytes. The most widespread "
                    "cutaneous receptors – pain, temperature and itch.",
    "follicle_nerve": "Hair follicle nerve endings: longitudinal lanceolate endings in a palisade around the follicle "
                      "below the sebaceous gland, encircled by circumferential fibres. Rapidly adapting "
                      "mechanoreceptors that fire when the hair is bent – the main light-touch receptor of hairy skin.",
    "meissner": "Meissner corpuscle: an encapsulated stack of flattened lamellar Schwann cells with an axon "
                "zig-zagging between them, in the tips of dermal papillae just beneath the epidermis. Rapidly "
                "adapting – light (discriminative) touch and low-frequency flutter. Densest in glabrous skin: "
                "fingertips, palms, soles and lips.",
    "meissner_hairy": "Meissner corpuscle: an encapsulated stack of flattened lamellar Schwann cells with an axon "
                      "zig-zagging between them, in the tip of a dermal papilla. Rapidly adapting – light touch and "
                      "flutter. Sparse in hairy skin, where hair follicle endings take over much of its role; "
                      "densest in the fingertips, palms, soles and lips.",
    "pacinian": "Pacinian (lamellar) corpuscle: a 1–2 mm ovoid of 20–60 concentric lamellae of flattened cells "
                "separated by fluid around a single unmyelinated axon terminal, in the deep dermis and hypodermis. "
                "The lamellae filter out sustained pressure, so it is rapidly adapting and tuned to vibration "
                "(~200–300 Hz).",
    "pacinian_axon": "Axon of a Pacinian corpuscle: a myelinated Aβ fibre that loses its myelin on entering the "
                     "corpuscle and runs through the central inner core as a single unmyelinated terminal.",
}

# ----------------------------------------------------------------------------------------------------------- config
# The default cut-away removes the quadrant x < 0, z > 0, exposing the planes z = 0 (for x < 0) and x = 0 (for z > 0).
# Follicles are (exit x, exit z, heading in degrees); heading 0 means the hair slopes towards +x (the follicle then
# runs down towards -x), 90 towards +z. A follicle exiting on z = 0 with heading 0 or 180 lies in the cut plane and
# is sectioned lengthwise; one with heading 0 whose track crosses x = 0 at z > 0 is cut across.
# Eccrine glands are given by their surface pore.
CONFIG = {
    "thin": dict(surf_res=320, t_c=0.024, t_l=0.0, t_g=0.012, t_b=0.013, dej=0.872, pap=(0.080, 0.068, 0.046),
                 pap_bottom=0.79, ret_bottom=0.35, galea=0.0, furrow=(0.30, 0.013, 0.020), fine=(0.085, 0.0060, 0.009),
                 corneum="#e1b99d", hair="#7c5537",
                 follicle=dict(R=0.030, rh=0.010, lean=0.62, out=0.38, curl=0.0, taper=True),
                 follicles=[(-0.14, 0.0, 0, 0.40), (0.0, 0.60, 90, 0.42), (0.42, -0.30, 18, 0.41),
                            (0.62, 0.36, 8, 0.43), (-0.58, -0.40, 160, 0.40)],
                 eccrine=[(-0.80, 0.0), (0.0, 0.10), (0.20, -0.52), (0.74, -0.08)],
                 meissner=2, pacinian=[(-0.52, 0.17, 0.0, 0.0), (0.0, 0.20, 0.36, 1.2)]),
    "thick": dict(surf_res=330, t_c=0.150, t_l=0.020, t_g=0.022, t_b=0.016, dej=0.66, pap_bottom=0.54, ret_bottom=0.27,
                  galea=0.0, corneum="#e8cfae",
                  follicles=[],
                  eccrine=[(-0.30, 0.0), (-0.74, 0.0), (0.0, 0.22), (0.0, 0.56), (0.52, -0.30), (0.22, -0.52),
                           (0.72, 0.30), (-0.50, -0.45), (0.36, 0.30), (-0.14, -0.30), (0.80, -0.55)],
                  meissner=40, pacinian=[(-0.55, 0.14, 0.0, 0.0), (0.0, 0.16, 0.42, 1.3), (0.55, 0.12, -0.25, 0.5)]),
    "scalp": dict(surf_res=250, t_c=0.020, t_l=0.0, t_g=0.011, t_b=0.013, dej=0.905, pap=(0.095, 0.070, 0.032),
                  pap_bottom=0.845, ret_bottom=0.50, galea=0.10, furrow=(0.40, 0.007, 0.018), fine=(0.12, 0.003, 0.008),
                  corneum="#dcb89e", hair="#2f1d13",
                  follicle=dict(R=0.046, rh=0.020, lean=0.40, out=0.52, curl=0.0, taper=False),
                  # follicular units of 2-3 terminal follicles opening close together
                  units=[((-0.12, 0.0), 0, [(0.0, 0.0), (0.075, 0.0), (0.03, -0.075)]),
                         ((-0.54, 0.0), 0, [(0.0, 0.0), (0.075, 0.0)]),
                         ((0.13, 0.27), 0, [(0.0, 0.0), (0.0, 0.085), (0.05, 0.16)]),
                         ((0.40, -0.28), 6, [(0.0, 0.0), (0.06, 0.05)]),
                         ((0.64, 0.38), -4, [(0.0, 0.0), (0.07, 0.03)]),
                         ((0.02, -0.46), 8, [(0.0, 0.0), (0.06, 0.04)]),
                         ((-0.50, -0.38), 4, [(0.0, 0.0), (0.07, -0.03)]),
                         ((0.84, -0.12), 2, [(0.0, 0.0)])],
                  bulb_y=(0.20, 0.30),
                  eccrine=[(0.0, 0.60), (0.55, -0.60), (-0.62, -0.08)],
                  meissner=0, pacinian=[(0.0, 0.26, 0.48, 1.4)]),
    "axilla": dict(surf_res=300, t_c=0.026, t_l=0.0, t_g=0.013, t_b=0.014, dej=0.870, pap=(0.085, 0.068, 0.046),
                   pap_bottom=0.79, ret_bottom=0.40, galea=0.0, furrow=(0.22, 0.024, 0.028), fine=(0.075, 0.006, 0.010),
                   corneum="#c99a7c", hair="#34221a",
                   follicle=dict(R=0.042, rh=0.015, lean=0.50, out=0.55, curl=1.0, taper=True),
                   follicles=[(-0.20, 0.0, 0, 0.33), (0.0, 0.62, 90, 0.35), (0.50, -0.30, 30, 0.34),
                              (0.56, 0.36, -20, 0.36), (-0.60, -0.30, 150, 0.33)],
                   eccrine=[(-0.82, 0.0), (0.30, 0.12), (0.18, -0.10)],
                   apocrine=[0, 1, 2],
                   meissner=2, pacinian=[(0.30, 0.18, 0.02, 0.4)]),
}

EPI = "Epidermis"
VS = "Vessels & nerves"


def build_skin(kind="thin"):
    cfg = CONFIG[kind]
    thick = kind == "thick"
    rng = np.random.default_rng({"thin": 1, "thick": 2, "scalp": 3, "axilla": 4}[kind])
    parts = []

    # ------------------------------------------------------------------ follicles, surface, dermo-epidermal junction
    fols = _follicle_specs(kind, cfg)
    if thick:
        geo = _thick_geometry(cfg)
    else:
        geo = _hairy_geometry(kind, cfg, fols)
    surf, base_surf, dej = geo["surf"], geo["base"], geo["dej"]

    # ------------------------------------------------------------------ epidermis
    y_cb = add(base_surf, -cfg["t_c"], noise2(0.004, 10.0, seed=21))
    parts.append(_layer("Stratum corneum", EPI, cfg["corneum"], y_cb, surf,
                        D["corneum_thick" if thick else "corneum"], "skin", 4,
                        res=(cfg["surf_res"], 150), detail=(0.07, 70.0, 0.0, 0)))
    upper = y_cb
    if thick:
        y_luc = shift(upper, -cfg["t_l"])
        parts.append(_layer("Stratum lucidum", EPI, "#f1e2c0", y_luc, upper, D["lucidum"], "skin", 3.5,
                            res=(150, 150), detail=(0.03, 110.0, 0.0, 1)))
        upper = y_luc
    y_gran = shift(upper, -cfg["t_g"])
    parts.append(_layer("Stratum granulosum", EPI, "#9a6593", y_gran, upper, D["granulosum"], "skin", 3,
                        res=(150, 150), detail=(0.14, 160.0, 0.6, 0)))
    y_bt = shift(dej, cfg["t_b"])
    dres = 230 if thick else 190          # the dermo-epidermal junction's relief
    y_spin_bottom = lambda X, Z: np.minimum(y_bt(X, Z), y_gran(X, Z) - 0.012)
    parts.append(_layer("Stratum spinosum", EPI, "#e3ada3", y_spin_bottom, y_gran, D["spinosum"], "skin", 2,
                        res=(150, dres), detail=(0.10, 120.0, 0.75, 0)))
    parts.append(_layer("Stratum basale", EPI, "#8c4a64", dej, y_spin_bottom, D["basale"], "skin", 1,
                        res=(dres, dres), detail=(0.10, 190.0, 0.95, 0)))
    parts.append(_melanocytes(cfg, dej))

    # ------------------------------------------------------------------ dermis & hypodermis
    y_pap = add(cfg["pap_bottom"], noise2(0.022, 2.6, seed=41), noise2(0.008, 7.0, seed=42))
    # the dermis-hypodermis junction is ragged: fat rises into the dermis around coils and follicle bulbs
    lifts = [(ex, ez) for ex, ez in cfg["eccrine"]] + [f["base_xz"] for f in fols]
    y_ret = add(cfg["ret_bottom"], noise2(0.045, 2.0, seed=43), noise2(0.014, 5.5, seed=44),
                Bumps(lifts, 0.16, 0.05, k=3) if lifts else 0.0)
    y_floor = cfg["galea"]
    parts.append(_layer("Papillary dermis", "Dermis", "#f0c0b0", y_pap, dej, D["papillary"], "fascia", 0,
                        res=(dres, 90), bulk=True, detail=(0.12, 80.0, 0.22, 0)))
    parts.append(_layer("Reticular dermis", "Dermis", "#d99a8e", y_ret, y_pap, D["reticular"], "fascia", -1,
                        res=(90, 90), bulk=True, detail=(0.16, 40.0, 0.10, 0),
                        wall=(fibre_relief(0.013, 30.0, 5.0, seed=5, axis=0), 36)))
    parts += _hypodermis(kind, y_ret, y_floor)
    if cfg["galea"]:
        top = add(cfg["galea"], noise2(0.010, 3.0, seed=47))
        parts.append(_layer("Galea aponeurotica", "Galea aponeurotica", "#dcdfe3", 0.0, top, D["galea"], "tendon",
                            -3, res=(120, 40), bulk=True, detail=(0.08, 55.0, 0.12, 1),
                            wall=(fibre_relief(0.006, 60.0, 4.0, seed=9, axis=0), 8)))

    # ------------------------------------------------------------------ appendages
    if fols:
        parts += _follicles(kind, cfg, fols, surf, dej)
    parts += _eccrine(cfg, geo, surf, dej, thick)
    if kind == "axilla":
        parts += _apocrine(cfg, fols)

    # ------------------------------------------------------------------ vessels, nerves, receptors
    parts += _vessels(cfg, dej, geo["papillae"], y_ret)
    parts += _nerves(kind, cfg, dej, geo["papillae"], fols, rng)
    if kind == "axilla":
        # Embedded structures share the specimen's cut planes; otherwise their
        # networks remain floating in the corner where tissue was removed.
        for part in parts:
            if part.group in {VS, "Sensory receptors"}:
                part.clip = True
    return settle(parts, seed={"thin": 101, "thick": 102, "scalp": 103, "axilla": 104}[kind],
                  amp_xz=0.030, amp_y=0.070, freq=1.7)


# ============================================================================================ layers
def _grid(res):
    nx = int(res) + 1
    nz = max(2, int(res * (Z1 - Z0) / (X1 - X0)) + 1)
    return np.linspace(X0, X1, nx), np.linspace(Z0, Z1, nz)


def _layer(name, group, color, bottom, top, desc, category, rank, res=(250, 250), bulk=False, detail=None,
           wall=None):
    return Part(name, group, color, _slab(top, bottom, res[0], res[1], wall=wall), desc, category=category,
                bulk=bulk, clip=True, rank=rank, detail=detail)


def _fnv(f):
    return f if callable(f) else (lambda X, Z, v=float(f): np.full(np.broadcast(np.asarray(X), np.asarray(Z)).shape, v))


def _slab(top, bottom, res_top, res_bot, gap=0.0015, wall=None):
    """Closed solid between two height fields, like geometry.slab, except that the two faces are sampled at their own
    resolutions (a layer's hidden underside needs far fewer triangles than its relief) and the side walls can be
    subdivided into rows and given a relief - `wall` is (height(p) -> outward offset, rows)."""
    top, bottom = _fnv(top), _fnv(bottom)
    m = Mesh()
    faces = {}
    for key, f, res, up in (("top", top, res_top, True), ("bot", bottom, res_bot, False)):
        xs, zs = _grid(res)
        X, Z = np.meshgrid(xs, zs, indexing="ij")
        Y = np.asarray(f(X, Z), float) * np.ones_like(X) + (-gap if up else gap)
        faces[key] = (xs, zs, Y)
        m.add(np.stack([X, Y, Z], -1).reshape(-1, 3), _grid_indices(len(xs), len(zs), flip=up))
    (txs, tzs, TY), (bxs, bzs, BY) = faces["top"], faces["bot"]
    relief, rows = wall if wall else (None, 1)
    # (fixed axis, fixed value, top edge heights, bottom edge heights, outward normal)
    sides = [(2, Z0, txs, TY[:, 0], bxs, BY[:, 0], np.array([0.0, 0.0, -1.0])),
             (2, Z1, txs, TY[:, -1], bxs, BY[:, -1], np.array([0.0, 0.0, 1.0])),
             (0, X0, tzs, TY[0, :], bzs, BY[0, :], np.array([-1.0, 0.0, 0.0])),
             (0, X1, tzs, TY[-1, :], bzs, BY[-1, :], np.array([1.0, 0.0, 0.0]))]
    for axis, value, tu, ty, bu, by, out in sides:
        u = tu if len(tu) >= len(bu) else bu
        yt = np.interp(u, tu, ty)
        yb = np.minimum(np.interp(u, bu, by), yt - 1e-4)
        f = np.linspace(0.0, 1.0, rows + 1)
        Y = yb[None, :] + (yt - yb)[None, :] * f[:, None]
        U = np.broadcast_to(u[None, :], Y.shape)
        V = np.full(Y.shape, value)
        P = np.stack([V, Y, U] if axis == 0 else [U, Y, V], -1).reshape(-1, 3)
        if relief is not None and rows > 1:
            fade = (np.sin(math.pi * f)[:, None] ** 0.5 *
                    np.clip(np.minimum(U - u[0], u[-1] - U) / 0.03, 0.0, 1.0)).reshape(-1)
            P = P + out[None, :] * (np.asarray(relief(P), float).reshape(-1) * fade)[:, None]
        idx = _grid_indices(rows + 1, len(u))
        tri = P[idx]
        nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]).sum(axis=0)
        if float(nrm @ out) < 0:
            idx = idx[:, ::-1]
        m.add(P, idx)
    return m


# ============================================================================================ surfaces
def _furrow_net(ostia, seed, spacing, depth, width, angles=(28.0, 118.0, 73.0), through=2):
    """Skin furrows (sulci cutis): straight-ish grooves in a few crossing directions that divide the surface into
    rhomboid fields. The first `through` families have a line through every follicle ostium, because hairs emerge
    where the furrows cross."""
    rng = np.random.default_rng(seed)
    fams = []
    for k, ang in enumerate(angles):
        a = math.radians(ang + rng.uniform(-6.0, 6.0))
        n = np.array([math.cos(a), math.sin(a)])
        offs = list(np.cumsum(rng.uniform(0.65, 1.35, 60) * spacing) - 1.35)
        offs = [o for o in offs if o < 1.35]
        if k < through:
            for ox, oz in ostia:
                c = ox * n[0] + oz * n[1]
                offs = [o for o in offs if abs(o - c) > spacing * 0.45] + [c]
        offs = np.array(sorted(offs))
        deps = rng.uniform(0.55, 1.15, len(offs)) * (1.0 if k < 2 else 0.6)
        fams.append((n, offs, deps, noise2(1.0, 2.4, seed=seed * 7 + k)))
    warp = noise2(0.028, 2.0, seed=seed + 3)

    def f(X, Z):
        X, Z = np.broadcast_arrays(np.asarray(X, float), np.asarray(Z, float))
        W = warp(X, Z)
        out = np.zeros(X.shape)
        for n, offs, deps, fade_n in fams:
            u = X * n[0] + Z * n[1] + W
            i = np.clip(np.searchsorted(offs, u), 1, len(offs) - 1)
            lo, hi = offs[i - 1], offs[i]
            near = np.where(u - lo < hi - u, i - 1, i)
            dist = np.abs(u - offs[near])
            t = np.clip(1.0 - dist / width, 0.0, 1.0)
            fade = np.clip(0.75 + 1.3 * fade_n(X, Z), 0.15, 1.0)
            out -= depth * deps[near] * t * t * (3.0 - 2.0 * t) * fade
        return out
    return f


def _hairy_geometry(kind, cfg, fols):
    ostia = [(f["x"], f["z"]) for f in fols]
    pores = [(ex, ez) for ex, ez in cfg["eccrine"]]
    sp, dp, wd = cfg["furrow"]
    fsp, fdp, fwd = cfg["fine"]
    furrows = _furrow_net(ostia, {"thin": 7, "scalp": 8, "axilla": 9}[kind], sp, dp, wd)
    fine = _furrow_net([], {"thin": 17, "scalp": 18, "axilla": 19}[kind], fsp, fdp, fwd,
                       angles=(55.0, 145.0, 100.0), through=0)
    R = cfg["follicle"]["R"]
    funnels = Bumps(ostia, R * 1.9, -0.030, k=3)
    pits = Bumps(pores, 0.016, -0.014, k=2)
    base = add(1.0, furrows, funnels, pits, noise2(0.006, 3.0, seed=5))
    # the corneocyte micro-relief: shallow overlapping squames
    surf = add(base, fine, noise2(0.0022, 34.0, seed=24, octaves=2), noise2(0.0035, 13.0, seed=25, octaves=2))
    spacing, rad, amp = cfg["pap"]
    pap_pts = poisson_disk((X0 - 0.1, Z0 - 0.1), (X1 + 0.1, Z1 + 0.1), spacing, seed=11)
    # no papillae inside a follicle's funnel of epidermis
    if ostia:
        dd, _ = cKDTree(np.array(ostia)).query(pap_pts)
        pap_pts = pap_pts[dd > R * 2.0]
    papillae = Bumps(pap_pts, rad, amp, k=5)
    dips = Bumps(ostia, R * 2.4, -0.035, k=3)
    dej = add(cfg["dej"] - amp * 0.45, papillae, dips, noise2(0.010, 4.0, seed=9), noise2(0.004, 15.0, seed=19))
    inside = [(float(x), float(z)) for x, z in pap_pts if X0 + 0.02 < x < X1 - 0.02 and Z0 + 0.02 < z < Z1 - 0.02]
    return dict(surf=surf, base=base, dej=dej, papillae=inside, pores=pores)


# ---- thick skin: friction ridges
FP_C = np.array([1.95, -1.85])      # centre of the ridge arcs, off the block: ridges run diagonally across both cuts
FP_PERIOD = 0.19
_fp_warp = noise2(0.030, 1.5, seed=61)


def _fp_phase(X, Z):
    X, Z = np.asarray(X, float), np.asarray(Z, float)
    return (np.hypot(X - FP_C[0], Z - FP_C[1]) + _fp_warp(X, Z)) / FP_PERIOD


def _wrap(u):
    return u - np.floor(u + 0.5)


def _fp_snap(p, target, axis=None):
    """Move a point onto the ridge line phase == target: radially, or along x (axis 0) / z (axis 2) to stay in a
    cut plane."""
    p = np.array(p, float)
    for _ in range(6):
        ph = float(_fp_phase(p[0], p[1]))
        if axis is None:
            r = p - FP_C
            dirv = r / np.linalg.norm(r)
        else:
            dirv = np.array([1.0, 0.0]) if axis == 0 else np.array([0.0, 1.0])
        e = 1e-3
        g = (float(_fp_phase(*(p + dirv * e))) - ph) / e
        p = p - dirv * (ph - target) / g
    return p


def _thick_geometry(cfg):
    # sweat pores along every ridge crest; the glands we model get pores snapped to a crest (inside a cut plane
    # when their pore was placed on one), the rest of the crest gets pores every ~0.1
    glands = []
    for ex, ez in cfg["eccrine"]:
        axis = 0 if abs(ez) < 1e-6 and ex < 0 else (2 if abs(ex) < 1e-6 and ez > 0 else None)
        ph = float(_fp_phase(ex, ez))
        glands.append(tuple(_fp_snap((ex, ez), round(ph), axis)))
    rng = np.random.default_rng(71)
    pores = []
    r_lo = np.hypot(X1 - FP_C[0], Z0 - FP_C[1]) - 0.3
    r_hi = np.hypot(X0 - FP_C[0], Z1 - FP_C[1]) + 0.3
    for k in range(int(r_lo / FP_PERIOD), int(r_hi / FP_PERIOD) + 1):
        r = k * FP_PERIOD
        th = rng.uniform(0, 0.1 / r)
        while th < math.pi:
            q = FP_C + r * np.array([math.cos(th), math.sin(th)])
            if not (X0 - 0.1 < q[0] < X1 + 0.1 and Z0 - 0.1 < q[1] < Z1 + 0.1):
                th += 0.1 / r
                continue
            p = _fp_snap(FP_C + r * np.array([math.cos(th), math.sin(th)]), k)
            if X0 + 0.02 < p[0] < X1 - 0.02 and Z0 + 0.02 < p[1] < Z1 - 0.02:
                if min((np.hypot(p[0] - gx, p[1] - gz) for gx, gz in glands), default=1.0) > 0.07:
                    pores.append(tuple(p))
            th += rng.uniform(0.085, 0.125) / r
    all_pores = glands + pores

    def ridge(X, Z):
        u = _fp_phase(X, Z)
        return 0.036 * (0.5 + 0.5 * np.cos(2 * math.pi * u)) ** 0.45

    pits = Bumps(all_pores, 0.017, -0.024, k=2)
    base = add(1.0, ridge, noise2(0.006, 3.0, seed=5))
    surf = add(base, pits, noise2(0.0018, 30.0, seed=25, octaves=2), noise2(0.0025, 11.0, seed=26, octaves=2))

    lam = 0.078       # papilla spacing along a row

    def along(X, Z):
        X, Z = np.asarray(X, float), np.asarray(Z, float)
        r = np.hypot(X - FP_C[0], Z - FP_C[1])
        return np.arctan2(Z - FP_C[1], X - FP_C[0]) * r

    def dej_fn(X, Z):
        X, Z = np.broadcast_arrays(np.asarray(X, float), np.asarray(Z, float))
        u = _fp_phase(X, Z)
        v = along(X, Z)
        inter = np.exp(-(_wrap(u) / 0.14) ** 2)           # rete ridge under each surface ridge (carries the duct)
        limit = np.exp(-(_wrap(u - 0.5) / 0.11) ** 2)     # rete ridge under each furrow
        pap = np.zeros(X.shape)
        for row, ph in ((0.25, 0.0), (0.75, math.pi)):
            across = np.exp(-(_wrap(u - row) / 0.12) ** 4)
            pap += across * (0.5 + 0.5 * np.cos(2 * math.pi * v / lam + ph + 0.6 * np.floor(u)))
        pap = np.minimum(pap, 1.0)
        # papillae are fingers with rounded tips, not cones
        return cfg["dej"] - 0.075 * inter - 0.035 * limit + 0.055 * pap * (2.0 - pap)

    dej = add(dej_fn, noise2(0.005, 5.0, seed=9))
    # papilla centres, for the capillary loops and Meissner corpuscles
    papillae = []
    for k in range(int(r_lo / FP_PERIOD), int(r_hi / FP_PERIOD) + 1):
        for row, ph in ((0.25, 0.0), (0.75, math.pi)):
            r = (k + row) * FP_PERIOD
            j0 = int(math.floor(-math.pi * r / lam)) - 1
            for j in range(j0, int(math.pi * r / lam) + 2):
                v = (j - (ph + 0.6 * k) / (2 * math.pi)) * lam
                th = v / r
                q = FP_C + r * np.array([math.cos(th), math.sin(th)])
                if not (-math.pi < th < math.pi and X0 - 0.1 < q[0] < X1 + 0.1 and Z0 - 0.1 < q[1] < Z1 + 0.1):
                    continue
                p = _fp_snap(FP_C + r * np.array([math.cos(th), math.sin(th)]), k + row)
                if X0 + 0.03 < p[0] < X1 - 0.03 and Z0 + 0.03 < p[1] < Z1 - 0.03:
                    papillae.append((float(p[0]), float(p[1])))
    return dict(surf=surf, base=base, dej=dej, papillae=papillae, pores=glands)


# ============================================================================================ epidermal cells
def _melanocytes(cfg, dej):
    mel = Volume((X0, cfg["dej"] - 0.16, Z0), (X1, cfg["dej"] + 0.14, Z1), 0.0035)
    for i, (mx, mz) in enumerate(poisson_disk((X0 + 0.06, Z0 + 0.06), (X1 - 0.06, Z1 - 0.06), 0.25, seed=31)):
        y = at(dej, mx, mz) + cfg["t_b"] * 0.5
        mel.add_all(dendritic_cell((mx, y, mz), 0.010, 5, 0.04, seed=i), "smooth", 0.006)
    return sdf_part(mel, "Melanocytes", EPI, "#3b271f", D["melanocytes"], "skin", smooth=0.7, rank=1,
                    detail=(0.05, 0.0, 0.0, 0))


# ============================================================================================ hypodermis
def _hypodermis(kind, y_ret, y_floor):
    """Fat lobules, each a cluster of bulging adipocytes, and the fibrous septa between them built as the complement
    of the lobules - select the septa alone and they stand as a honeycomb."""
    xs, zs = np.linspace(X0, X1, 60), np.linspace(Z0, Z1, 44)
    yr = y_ret(xs[:, None], zs[None, :])
    top = float(np.max(yr)) + 0.01
    lo_y = y_floor
    vox = 0.016 if kind == "scalp" else 0.014
    vol = Volume((X0 - 0.01, lo_y - 0.01, Z0 - 0.01), (X1 + 0.01, top, Z1 + 0.01), vox)
    x, y, z = vol.axes()
    grid = np.stack(np.broadcast_arrays(x, y, z), -1).reshape(-1, 3)
    scalp = kind == "scalp"
    lob_sp = 0.47 if scalp else 0.56
    lob_c = jittered_bcc((X0 - 0.3, lo_y - 0.2, Z0 - 0.3), (X1 + 0.3, top + 0.2, Z1 + 0.3), lob_sp, 0.25, seed=51)
    dl, _ = cKDTree(lob_c).query(grid, k=2, workers=-1)
    septum = (0.022 if scalp else 0.012)
    wall = ((dl[:, 1] - dl[:, 0]) / 2.0).reshape(vol.shape).astype(np.float32)       # distance to the septum plane
    wall += np.float32(0.006) * fbm3(x * 7.0, y * 7.0, z * 7.0, 1.0, 2, 57).astype(np.float32)
    yr = y_ret(x, z).astype(np.float32)
    box = np.maximum(np.abs(x) - np.float32(X1), np.abs(z) - np.float32(Z1))
    # where a lobule meets the sides or floor of the block its adipocytes bulge as a mosaic of domes
    cells = jittered_bcc((X0 - 0.1, lo_y - 0.1, Z0 - 0.1), (X1 + 0.1, top + 0.1, Z1 + 0.1), 0.075, 0.2, seed=53)
    dc, _ = cKDTree(cells).query(grid, k=2, workers=-1)
    edge = ((dc[:, 1] - dc[:, 0]) / 2.0).reshape(vol.shape).astype(np.float32)
    groove = np.float32(0.012) * np.clip(1.0 - edge / np.float32(0.022), 0.0, 1.0) ** 2
    outer = np.maximum(box, lo_y - y) + np.float32(0.006) + groove
    # the septa stop just short of the lobules, so a cut shows each lobule's own face and not a septum behind it
    lob = vol.copy(np.maximum(np.maximum(septum - wall, y - yr + np.float32(0.010)), outer))
    sep = vol.copy(np.maximum(np.maximum(wall - septum + np.float32(0.0015), y - yr + np.float32(0.004)),
                              np.maximum(box, lo_y + np.float32(0.002) - y)))
    desc = D["hypodermis_scalp" if scalp else "hypodermis"]
    return [
        sdf_part(sep, "Hypodermis septa", "Hypodermis", "#eadcc2", desc, "fascia", smooth=0.6, rank=-2, bulk=True,
                 detail=(0.10, 55.0, 0.15, 0)),
        sdf_part(lob, "Adipocytes (fat lobules)", "Hypodermis", "#f4d47a", D["fat"], "fat", smooth=0.7, rank=-2,
                 detail=(0.05, 22.0, 0.10, 0)),
    ]


# ============================================================================================ hair follicles
def _follicle_specs(kind, cfg):
    """Follicle geometry: exit point, axis and radii. The axis runs from the ostium down and back, away from the
    direction the hair slopes."""
    if kind == "thick":
        return []
    fc = cfg["follicle"]
    raw = []
    if kind == "scalp":
        rng = np.random.default_rng(33)
        for u, ((cx, cz), heading, members) in enumerate(cfg["units"]):
            for m, (dx, dz) in enumerate(members):
                # follicles of a unit converge on a shared funnel and splay slightly towards their bulbs
                h = heading + (0 if abs(cz) < 1e-6 and m < 2 and abs(dz) < 1e-6 else rng.uniform(-6, 6))
                raw.append(dict(x=cx + dx * 0.5, z=cz + dz * 0.5, heading=h, bulb_y=rng.uniform(*cfg["bulb_y"]),
                                unit=u, first=m == 0, splay=(dx * 0.8, dz * 0.8)))
    else:
        for i, (fx, fz, heading, by) in enumerate(cfg["follicles"]):
            raw.append(dict(x=fx, z=fz, heading=heading, bulb_y=by, unit=i, first=True, splay=(0.0, 0.0)))
    out = []
    for i, f in enumerate(raw):
        h = math.radians(f["heading"])
        horiz = np.array([math.cos(h), 0.0, math.sin(h)])
        drop = (1.0 - f["bulb_y"]) * fc["lean"]
        base_xz = (f["x"] - horiz[0] * drop + f["splay"][0], f["z"] - horiz[2] * drop + f["splay"][1])
        out.append(dict(f, idx=i, horiz=horiz, R=fc["R"], rh=fc["rh"], lean=fc["lean"], out=fc["out"],
                        curl=fc["curl"], taper=fc["taper"], base_xz=base_xz))
    return out


def _arc(path):
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    return np.concatenate([[0.0], np.cumsum(seg)])


def _subpath(path, a0, a1, n):
    arc = _arc(path)
    t = np.linspace(a0, a1, n)
    return np.stack([np.interp(t, arc, path[:, k]) for k in range(3)], -1)


def _point_at(path, a):
    return _subpath(path, a, a, 1)[0]


def _hair_path(top, d, horiz, length, curl, seed, n=90):
    """The free hair: leaves the ostium along the follicle axis, then bends over to lie at a shallow angle, with a
    wave (or a tight curl for axillary hair)."""
    rng = np.random.default_rng(seed)
    lie = horiz * math.cos(math.radians(24)) + np.array([0.0, math.sin(math.radians(24)), 0.0])
    side = np.cross(horiz, [0.0, 1.0, 0.0])
    step = length / n
    p = top.copy()
    v = d.copy()
    pts = [p.copy()]
    ph = rng.uniform(0, 2 * math.pi)
    for i in range(n):
        t = i / n
        target = lie + np.array([0.0, -0.10 * t, 0.0])
        v = v + (target - v) * 0.07
        if curl:
            # coarse axillary hair: an irregular, loose spiral rather than a regular wave
            w = 2 * math.pi * t * (2.2 + 0.6 * math.sin(3 * t + ph)) + ph
            v = v + (side * math.cos(w) + np.array([0.0, 1.0, 0.0]) * math.sin(w)) * 0.075 * curl
        else:
            v = v + side * 0.012 * math.sin(2 * math.pi * t * 1.3 + ph)
        v /= np.linalg.norm(v)
        p = p + v * step
        pts.append(p.copy())
    return np.array(pts)


def _follicles(kind, cfg, fols, surf, dej):
    groups = {k: Mesh() for k in ("shaft", "irs", "ors", "bulb", "pap", "seb", "arr")}
    for f in fols:
        i = f["idx"]
        R, rh, horiz = f["R"], f["rh"], f["horiz"]
        ex, ez = f["x"], f["z"]
        top_y = at(surf, ex, ez)
        d = np.array([f["lean"] * horiz[0], 1.0, f["lean"] * horiz[2]])
        d /= np.linalg.norm(d)
        length = (top_y - f["bulb_y"]) / d[1]
        base = np.array([ex, top_y, ez]) - d * length + np.array([f["splay"][0], 0.0, f["splay"][1]])
        side = horiz - d * float(np.dot(d, horiz))
        side /= np.linalg.norm(side)
        top = np.array([ex, top_y, ez])
        ctrl = [base, base + (top - base) * 0.35 + side * 0.010, base + (top - base) * 0.7 - side * 0.008, top]
        path = smooth_path(np.array(ctrl), 80)
        d = (top - base) / np.linalg.norm(top - base)
        L = float(_arc(path)[-1])
        f.update(path=path, d=d, side=side, length=L, base=base, top=top)
        a_iso = L * 0.70              # isthmus: sebaceous duct opens here, the inner root sheath ends
        a_bulge = L * 0.56            # bulge: arrector pili insertion
        corneum = cfg["t_c"] + cfg["t_g"] * 0.5

        # ---- hair shaft: from the keratogenous zone above the papilla, out of the ostium and on as the free hair
        inner = _subpath(path, R * 1.3, L, 60)
        free = _hair_path(top, d, horiz, f["out"], f["curl"], seed=200 + i)
        shaft_path = np.vstack([inner, free[1:]])
        n_s = 160
        sw = Sweep(shaft_path, 16, n_s)
        arc = sw.A / sw.length
        a_out = L - R * 1.3
        s_exit = a_out / (a_out + float(_arc(free)[-1]))
        out_s = np.clip((arc - s_exit) / (1.0 - s_exit), 0.0, 1.0)
        tip = (1.0 - 0.85 * np.clip((out_s - 0.55) / 0.45, 0, 1) ** 1.4) if f["taper"] else \
            (1.0 - 0.18 * out_s)
        root = 0.75 + 0.25 * np.clip(arc / 0.06, 0, 1)          # the club of the root inside the bulb
        # cuticle: overlapping scales, each a ramp that steps down towards the tip
        scale = 1.0 + 0.04 * (out_s > 0) * ((sw.A / 0.013 + 0.25 * np.cos(sw.T)) % 1.0 - 0.5)
        groups["shaft"].extend(sw.solid(rh * tip * root * scale * (1.0 + 0.04 * np.cos(2 * sw.T))))

        # ---- inner root sheath: from the bulb to the isthmus
        irs_path = _subpath(path, R * 1.5, a_iso, 48)
        sw = Sweep(irs_path, 20, 48)
        r_irs = rh * 1.45 + 0.002
        ramp_top = np.clip((sw.S - 0.85) / 0.15, 0, 1)
        groups["irs"].extend(sw.shell(rh * 1.04, r_irs * (1.0 - 0.18 * ramp_top)))

        # ---- outer root sheath: thick around the bulb's neck, a swelling at the bulge, then the infundibulum
        a_top = L - corneum / d[1]
        ors_path = _subpath(path, R * 1.8, a_top, 60)
        sw = Sweep(ors_path, 24, 60)
        a = R * 1.8 + sw.S * (a_top - R * 1.8)
        bulge = np.exp(-((a - a_bulge) / (L * 0.08)) ** 2)
        flare = np.clip((a - a_iso) / (a_top - a_iso), 0, 1)
        r_out = R * (1.0 + 0.22 * bulge + 0.9 * flare ** 3) * (1.0 + 0.05 * np.cos(3 * sw.T + a * 30))
        canal = np.where(a < a_iso, r_irs + 0.0015, rh * (1.25 + 1.6 * flare ** 2))
        groups["ors"].extend(sw.shell(np.minimum(canal, r_out - 0.006), r_out))

        # ---- bulb (matrix) cupping the dermal papilla: both swept about the follicle axis. The bulb is a thick cup
        # whose bottom annulus lets the papilla's stalk through to the connective-tissue sheath.
        a0, a1 = -1.5 * R, 3.0 * R
        axis = base[None, :] + d[None, :] * np.linspace(a0, a1, 48)[:, None]
        rp_tab = ([-1.5, -0.3, 0.0, 0.5, 0.9, 1.3, 1.55], [0.28, 0.30, 0.42, 0.62, 0.58, 0.30, 0.02])
        sw = Sweep(axis[(np.linspace(a0, a1, 48) >= -0.3 * R)], 32, 36)
        ab = (-0.3 + sw.S * 3.3) * R
        ro = np.interp(ab / R, [-0.3, 0.0, 0.5, 1.0, 1.6, 2.2, 3.0], [0.50, 1.05, 1.42, 1.45, 1.22, 1.02, 0.95]) * R
        ro = ro * (1.0 + 0.035 * np.sin(5 * sw.T + ab / R * 7.0 + i) * np.sin(ab / R * 9.0))
        rp = np.interp(ab / R, *rp_tab) * R
        ri = np.where(ab < 1.55 * R, rp + 0.003, 0.0005)
        groups["bulb"].extend(sw.shell(np.minimum(ri, ro - 0.004), ro))
        sw = Sweep(axis[(np.linspace(a0, a1, 48) <= 1.6 * R)], 24, 30)
        ap = (-1.5 + sw.S * 3.1) * R
        rp = np.interp(ap / R, *rp_tab) * R * (1.0 + 0.05 * np.sin(4 * sw.T + ap / R * 6.0))
        groups["pap"].extend(sw.solid(np.maximum(rp, 0.0008)))

        # ---- sebaceous gland: lobules in the obtuse angle, duct into the follicle at the isthmus
        big = {"scalp": 1.25, "axilla": 1.0, "thin": 0.85}[kind]
        s_anchor = _point_at(path, a_iso)
        s_c = _point_at(path, a_iso - L * 0.07) + side * (R + 0.045 * big)
        lo, hi = s_c - 0.12 * big - 0.03, s_c + 0.12 * big + 0.03
        vs = Volume(np.minimum(lo, s_anchor - 0.02), np.maximum(hi, s_anchor + 0.02), 0.0048 * big)
        lobs = blob_cluster(s_c, 7 if f["first"] else 5, 0.032 * big, (0.035 * big, 0.06 * big, 0.035 * big),
                            seed=60 + i, squash=(1.0, 1.3, 1.0))
        vs.add_all(lobs, "smooth", 0.012)
        vs.add(capsule(s_c + d * 0.02 * big, s_anchor + side * rh * 0.5, 0.013 * big), "smooth", 0.010)
        # the lobules are made of bulging sebocytes
        xg, yg, zg = vs.axes()
        vs.d += np.float32(0.0025) * np.sin(xg * 190.0 + 1.3 * np.sin(zg * 90.0)) * np.sin(yg * 170.0) * \
            np.sin(zg * 185.0 + 0.8 * np.sin(xg * 70.0))
        ors_sdf = vs.copy(np.full(vs.shape, 1e3, np.float32)).tube(_subpath(path, 0.0, L, 40), R * 0.95, "union")
        vs.apply(ors_sdf.d, (slice(None),) * 3, "subtract")
        groups["seb"].extend(vs.mesh(0.8))

        # ---- arrector pili: from the bulge, past the outside of the gland, up to the papillary dermis
        if f["first"]:
            b = _point_at(path, a_bulge) + side * R * 0.9
            horiz_side = np.array([side[0], 0.0, side[2]])
            horiz_side /= max(float(np.linalg.norm(horiz_side)), 1e-6)
            reach = 0.30 if kind != "scalp" else 0.34
            e_xz = np.array([b[0], b[2]]) + horiz_side[[0, 2]] * reach
            e = np.array([e_xz[0], at(dej, e_xz[0], e_xz[1]) - 0.035, e_xz[1]])
            mid = s_c + side * (0.05 * big + 0.03) - d * 0.02
            ap = smooth_path(np.array([b, (b + mid) / 2 - side * 0.01, mid, e]), 40)
            sw = Sweep(ap, 18, 40)
            prof = np.interp(sw.S, [0.0, 0.08, 0.6, 0.9, 1.0], [0.55, 1.0, 0.85, 0.75, 0.55])
            fan = 1.0 + 0.9 * np.clip((sw.S - 0.75) / 0.25, 0, 1) * np.cos(sw.T) ** 2
            r = 0.016 * prof * (1.0 + 0.35 * np.cos(2 * sw.T)) * fan * (1.0 + 0.06 * np.sin(sw.A * 90 + 2 * sw.T))
            groups["arr"].extend(sw.solid(r))

    terminal = kind != "thin"
    return [
        mesh_part(groups["shaft"], "Hair shaft", "Hair follicle", cfg["hair"],
                  D["shaft"] if terminal else D["shaft_vellus"], "nail", rank=3, detail=(0.06, 60.0, 0.0, 2)),
        mesh_part(groups["irs"], "Inner root sheath", "Hair follicle", "#d9a960", D["irs"], "skin", rank=0.2,
                  detail=(0.08, 150.0, 0.5, 2)),
        mesh_part(groups["ors"], "Outer root sheath", "Hair follicle", "#ecc9ae", D["ors"], "skin", rank=0.1,
                  detail=(0.10, 120.0, 0.8, 0)),
        mesh_part(groups["bulb"], "Hair bulb (matrix)", "Hair follicle", "#7c4760", D["bulb"], "skin", rank=-0.6,
                  detail=(0.12, 180.0, 0.95, 0)),
        mesh_part(groups["pap"], "Dermal papilla of hair", "Hair follicle", "#e0827a", D["dermal_papilla"], "fascia",
                  rank=-0.8, detail=(0.10, 80.0, 0.45, 0)),
        mesh_part(groups["seb"], "Sebaceous gland", "Glands", "#f3e2a0", D["sebaceous"], "gland", rank=-0.4,
                  detail=(0.08, 70.0, 0.6, 0)),
        mesh_part(groups["arr"], "Arrector pili muscle", "Glands", "#b5705a", D["arrector"], "muscle", rank=-0.4,
                  detail=(0.08, 110.0, 0.45, 0)),
    ]


# ============================================================================================ sweat glands
def _eccrine(cfg, geo, surf, dej, thick):
    coils, ducts = Mesh(), Mesh()
    pores = geo["pores"]
    for i, (ex, ez) in enumerate(pores):
        in_cut = (abs(ez) < 0.02 and ex < 0) or (abs(ex) < 0.02 and ez > 0)
        # coils sit at the dermis-hypodermis junction; a cut gland keeps its coil in the cut plane
        off = np.array([0.07, 0.0, 0.0]) if (in_cut and abs(ez) < 0.02) else \
            (np.array([0.0, 0.0, -0.07]) if in_cut else np.array([0.05, 0.0, -0.04]))
        cy = cfg["ret_bottom"] + (0.03 if thick else 0.02)
        center = np.array([ex, cy, ez]) + off
        coil = coil_path(center, 0.075, points=420, seed=40 + i, length=1.25, radii=(0.078, 0.05, 0.078))
        top_y = at(surf, ex, ez)
        dej_y = at(dej, ex, ez)
        entry = dej_y - 0.012
        rise = smooth_path(np.array([coil[-1], center + np.array([0.0, 0.09, 0.0]),
                                     np.array([ex + 0.02, (cy + entry) / 2 + 0.03, ez - 0.012]),
                                     np.array([ex - 0.01, entry - 0.07, ez + 0.01]),
                                     np.array([ex, entry, ez])]), 60)
        # the acrosyringium corkscrews through the epidermis; tighter and with more turns through thick corneum
        turns = 5.5 if thick else 2.5
        a = np.linspace(0, turns * 2 * math.pi, 140 if thick else 70)
        t = a / a[-1]
        rad = 0.014 * np.clip(t / 0.08, 0, 1)
        spiral = np.stack([ex + rad * np.cos(a), entry + (top_y - entry - 0.004) * t, ez + rad * np.sin(a)], -1)
        coils.extend(tube(coil, np.full(len(coil), 0.0125), 12))
        duct = np.vstack([coil[-1:], rise[1:], spiral[1:]])
        ducts.extend(tube(duct, np.concatenate([np.full(len(rise), 0.0085), np.full(len(spiral) - 1, 0.0075)]),
                          12))
    return [
        mesh_part(coils, "Eccrine sweat gland (secretory coil)", "Glands", "#86b6e6", D["eccrine"], "gland", rank=-1,
                  detail=(0.08, 150.0, 0.85, 0)),
        mesh_part(ducts, "Eccrine sweat duct", "Glands", "#4f86cc", D["eccrine_duct"], "gland", rank=0,
                  detail=(0.08, 170.0, 0.9, 0)),
    ]


def _apocrine(cfg, fols):
    glands, ducts = Mesh(), Mesh()
    for n, fi in enumerate(cfg["apocrine"]):
        f = fols[fi]
        path, d, side, L = f["path"], f["d"], f["side"], f["length"]
        base = f["base"]
        # the coil lies beside the follicle's deep end, in the plane of the follicle
        horiz = np.array([side[0], 0.0, side[2]])
        horiz /= max(float(np.linalg.norm(horiz)), 1e-6)
        center = base + horiz * 0.14 + np.array([0.0, -0.04, 0.0])
        coil = coil_path(center, 0.16, points=260, seed=70 + n, step=0.03, length=0.85, radii=(0.19, 0.10, 0.17))
        entry = _point_at(path, L * 0.84)
        lo, hi = np.minimum(center, entry) - 0.2, np.maximum(center, entry) + 0.2
        v = Volume(lo, hi, 0.0042)
        v.tube(coil, 0.032, "union")
        lumen = Volume(lo, hi, 0.0042).tube(coil, 0.021, "union")
        # the secretory cells bulge into the lumen (apical snouts)
        xg, yg, zg = lumen.axes()
        lumen.d += np.float32(0.004) * (np.sin(xg * 160.0) * np.sin(yg * 150.0 + 0.7) * np.sin(zg * 170.0 + 1.9))
        v.apply(lumen.d, (slice(None),) * 3, "subtract")
        v.displace(0.0022, 45.0, 2, seed=110 + n)
        glands.extend(v.mesh(0.8))
        mid = (coil[-1] + entry) / 2 - horiz * 0.04 + np.array([0.0, 0.03, 0.0])
        ducts.extend(tube_mesh(smooth_path(np.array([coil[-1], mid, entry - d * 0.03,
                                                     entry]), 50), 0.011, 12))
    return [mesh_part(glands, "Apocrine sweat gland", "Glands", "#76c2a6", D["apocrine"], "gland", rank=-1.5,
                      detail=(0.08, 110.0, 0.85, 0)),
            mesh_part(ducts, "Apocrine duct", "Glands", "#4f9f86", D["apocrine_duct"], "gland", rank=-0.5,
                      detail=(0.08, 140.0, 0.85, 0))]


# ============================================================================================ vessels
def _network(y_fn, spacing, seed, max_len):
    """Edges of a jittered Delaunay net - a horizontal vascular plexus."""
    pts = poisson_disk((X0 - 0.05, Z0 - 0.05), (X1 + 0.05, Z1 + 0.05), spacing, seed=seed)
    tri = Delaunay(pts)
    edges = set()
    for s in tri.simplices:
        for a, b in ((s[0], s[1]), (s[1], s[2]), (s[2], s[0])):
            edges.add((min(a, b), max(a, b)))
    rng = np.random.default_rng(seed)
    out = []
    for a, b in sorted(edges):
        pa, pb = pts[a], pts[b]
        if np.linalg.norm(pa - pb) > max_len or rng.random() < 0.18:
            continue
        pa = np.clip(pa, [X0 + 0.005, Z0 + 0.005], [X1 - 0.005, Z1 - 0.005])
        pb = np.clip(pb, [X0 + 0.005, Z0 + 0.005], [X1 - 0.005, Z1 - 0.005])
        out.append((np.array([pa[0], y_fn(pa), pa[1]]), np.array([pb[0], y_fn(pb), pb[1]])))
    return out


def _vessels(cfg, dej, papillae, y_ret):
    art, vein, subp, caps = Mesh(), Mesh(), Mesh(), Mesh()
    sub_y = cfg["pap_bottom"] - 0.012
    # deep (cutaneous) plexus: paired arterioles and venules meandering along the dermis-hypodermis junction
    for j, z in enumerate((-0.46, 0.06, 0.52)):
        xs = np.linspace(X0 + 0.01, X1 - 0.01, 50)
        zz = z + 0.05 * np.sin(xs * 2.3 + j)
        ys = np.array([at(y_ret, x_, z_) for x_, z_ in zip(xs, zz)]) + 0.01
        pa = np.stack([xs, ys, zz], -1)
        art.extend(tube_mesh(pa, 0.017, 16))
        pv = pa + np.array([0.0, -0.012, 0.045])
        vein.extend(tube_mesh(pv, 0.024, 16))
        # candelabra: vessels rising through the reticular dermis to the subpapillary plexus
        for k, x in enumerate(np.linspace(-0.85, 0.85, 5) + 0.12 * j):
            if not X0 + 0.05 < x < X1 - 0.05:
                continue
            i0 = int(np.argmin(np.abs(xs - x)))
            a0 = pa[i0]
            art.extend(tube_mesh(wavy_path(a0, (a0[0] + 0.04, sub_y, a0[2] - 0.03), 30, 0.014, 1.4,
                                           seed=20 + 5 * j + k), 0.0075, 10))
            v0 = pv[i0]
            vein.extend(tube_mesh(wavy_path(v0, (v0[0] + 0.07, sub_y - 0.004, v0[2] + 0.02), 30, 0.014, 1.4,
                                            seed=40 + 5 * j + k), 0.0095, 10))
    # subpapillary plexus: a horizontal net
    for n, (a, b) in enumerate(_network(lambda p: sub_y, 0.16, 81, 0.30)):
        subp.extend(tube_mesh(wavy_path(a, b, 14, 0.010, 1.5, seed=n), 0.0055, 7))
    # a hairpin capillary loop up into every papilla
    for i, (px, pz) in enumerate(papillae):
        apex = at(dej, px, pz) - 0.014
        a = i * 2.39
        off = np.array([math.cos(a), 0.0, math.sin(a)]) * 0.008
        c = np.array([px, apex, pz])
        foot = np.array([px, sub_y, pz])
        wob = np.array([math.sin(a * 1.7), 0.0, math.cos(a * 2.3)]) * 0.012
        loop = np.array([foot - off * 3.0, (foot + c) / 2 - off * 1.4 + wob, c - off + np.array([0, -0.03, 0]),
                         c + np.array([0.0, 0.003, 0.0]), c + off + np.array([0, -0.03, 0]),
                         (foot + c) / 2 + off * 1.4 + wob * 0.6, foot + off * 3.0])
        caps.extend(tube_mesh(loop, 0.0026, 6, samples=26))
    return [
        mesh_part(art, "Arterioles", VS, "#cf3a31", D["artery"], "artery", rank=-1),
        mesh_part(vein, "Venules", VS, "#3b5cc4", D["vein"], "vein", rank=-1),
        mesh_part(subp, "Subpapillary plexus", VS, "#c9505a", D["subpapillary"], "artery", rank=0),
        mesh_part(caps, "Papillary capillary loops", VS, "#e3625a", D["capillary"], "artery", rank=0.5),
    ]


# ============================================================================================ nerves & receptors
def _lamellar_shell(c, radii, t, seed, res=21):
    """One closed lamella of a Pacinian corpuscle: an outer and an inner wobbly ellipsoid surface."""
    from .geometry import ellipsoid as ell_mesh
    m = Mesh()
    for k, (rr, flip) in enumerate(((1.0, False), (1.0 - t, True))):
        e = ell_mesh(c, np.asarray(radii) * rr, res)
        pos, nrm, idx = e.parts[0]
        q = pos.astype(np.float64)
        w = 1.0 + 0.035 * fbm3(q[:, 0] * 18.0, q[:, 1] * 18.0, q[:, 2] * 18.0, 1.0, 2, seed)
        q = c + (q - c) * w[:, None]
        m.add(q, idx[:, ::-1] if flip else idx)
    return m


def _nerves(kind, cfg, dej, papillae, fols, rng):
    thick = kind == "thick"
    parts = []
    nerve, free, fnerve = Mesh(), Mesh(), Mesh()
    # deep nerve trunks run with the deep vascular plexus; branches rise from them to a superficial plexus of fine
    # bundles just beneath the subpapillary vessels, which supplies the papillae and the epidermis
    ny = cfg["ret_bottom"] + 0.06
    trunks = [wavy_path((X0 + 0.01, ny, 0.40), (X1 - 0.01, ny + 0.02, 0.33), 70, 0.03, 1.5, seed=3),
              wavy_path((X0 + 0.01, ny + 0.02, -0.30), (X1 - 0.01, ny, -0.36), 70, 0.03, 1.5, seed=4)]
    for t in trunks:
        nerve.extend(tube_mesh(t, 0.018, 16))
    deep = np.vstack(trunks)
    tree = cKDTree(deep[:, [0, 2]])
    sy = cfg["pap_bottom"] - 0.03
    plexus = []
    for j, z in enumerate(np.arange(Z0 + 0.10, Z1 - 0.05, 0.25)):
        p = wavy_path((X0 + 0.01, sy, z), (X1 - 0.01, sy + 0.008, z + 0.05), 60, 0.03, 2.0, seed=600 + j)
        plexus.append(p)
        nerve.extend(tube_mesh(p, 0.0055, 8))
        for k, x in enumerate((-0.62, 0.08, 0.66)):
            i = int(np.argmin(np.abs(p[:, 0] - x - 0.07 * j)))
            _, t = tree.query([p[i, 0], p[i, 2]])
            nerve.extend(tube_mesh(wavy_path(deep[t], p[i], 30, 0.015, 1.3, seed=620 + 3 * j + k), 0.0065, 8))
    shallow = np.vstack(plexus)
    stree = cKDTree(shallow[:, [0, 2]])

    def branch(end, r=0.0045, seed=0, from_deep=False):
        src, tr = (deep, tree) if from_deep else (shallow, stree)
        _, j = tr.query([end[0], end[2]])
        start = src[j]
        mid = (start + end) / 2 + np.array([0.0, 0.012, 0.0])
        nerve.extend(tube_mesh(wavy_path(start, end, 30, 0.012, 1.2, seed=seed) if seed else
                               smooth_path(np.array([start, mid, end]), 20), r, 7))

    # Meissner corpuscles in papilla tips, with their afferent fibres
    meiss = None
    n_m = cfg["meissner"]
    if n_m:
        near = [p for p in papillae if (abs(p[1]) < 0.06 and p[0] < -0.05) or (abs(p[0]) < 0.06 and p[1] > 0.05)]
        far = [p for p in papillae if p not in near]
        rng.shuffle(far)
        chosen = (near[::2] + far)[:n_m] if thick else [min(papillae, key=lambda p: abs(p[1]) + abs(p[0] + 0.62)),
                                                        min(papillae, key=lambda p: abs(p[0]) + abs(p[1] - 0.45))]
        meiss = Mesh()
        for i, (px, pz) in enumerate(chosen):
            apex = at(dej, px, pz)
            c = np.array([px, apex - 0.036, pz])
            sub = Volume(c - 0.042, c + 0.042, 0.0027)
            fn_, _, _ = ellipsoid(c, (0.015, 0.030, 0.014))
            x, y, z = sub.axes()
            # a stack of flattened lamellar cells, slightly tilted
            ph = (y - c[1] + 0.25 * (x - c[0])) * (2 * math.pi / 0.0085)
            sub.d = (fn_(x, y, z) + 0.0022 * (np.abs(np.sin(ph)) - 0.5)).astype(np.float32)
            meiss.extend(sub.mesh(0.6))
            branch(c - np.array([0.0, 0.026, 0.0]), 0.0035)
    # free nerve endings: fine fibres through the basement membrane, ending among the spinous cells
    targets = [(-0.15 - 0.17 * k, 0.0) for k in range(5)] + [(0.0, 0.1 + 0.15 * k) for k in range(4)] + \
              [(0.3, -0.2), (0.6, 0.1), (-0.4, -0.3)]
    for i, (tx, tz) in enumerate(targets):
        base_y = cfg["pap_bottom"] - 0.01
        top_y = at(dej, tx, tz) + cfg["t_b"] + 0.03
        p0 = np.array([tx - 0.05, base_y, tz + 0.02])
        path = wavy_path(p0, (tx, top_y, tz), 24, 0.006, 2.0, seed=500 + i)
        free.extend(tube_mesh(path, 0.0022, 6))
        # two short twigs fanning into the epidermis
        for s in (-1, 1):
            q = path[-6]
            free.extend(tube_mesh(smooth_path(np.array([q, q + np.array([0.012 * s, 0.014, 0.006]),
                                                        q + np.array([0.02 * s, 0.024, 0.004 * s])]), 8), 0.0016, 5))
        branch(p0, 0.0035)
    # hair follicle (palisade) endings: lanceolate fibres parallel to the follicle, girdled by a ring
    for f in fols:
        if not f["first"]:
            continue
        path, d, L, R = f["path"], f["d"], f["length"], f["R"]
        a0, a1 = L * 0.50, L * 0.64
        ring_c = _point_at(path, a0)
        u = np.cross(d, [0.0, 0.0, 1.0])
        u /= np.linalg.norm(u)
        w = np.cross(d, u)
        ang = np.linspace(0, 2 * math.pi, 40)
        rr = R * 1.25
        ring = ring_c + (np.cos(ang)[:, None] * u + np.sin(ang)[:, None] * w) * rr
        fnerve.extend(tube_mesh(ring, 0.0028, 6))
        for k in range(10):
            t = 2 * math.pi * k / 10
            off = (math.cos(t) * u + math.sin(t) * w) * (R * 1.15)
            p = np.array([ring_c + off, _point_at(path, (a0 + a1) / 2) + off * 1.02, _point_at(path, a1) + off])
            fnerve.extend(tube_mesh(p, 0.0022, 5, samples=8))
        if f["first"]:
            branch(ring_c + u * rr, 0.004, seed=700 + f["idx"], from_deep=True)
    parts.append(mesh_part(nerve, "Cutaneous nerve & branches", VS, "#f0cf45", D["nerve"], "nerve", rank=-1))
    parts.append(mesh_part(free, "Free nerve endings", VS, "#f7dd6a", D["free_endings"], "nerve", rank=0.6))
    if fols:
        parts.append(mesh_part(fnerve, "Hair follicle nerve endings", VS, "#e8c23a", D["follicle_nerve"], "nerve",
                               rank=0.0))
    if meiss is not None:
        parts.append(mesh_part(meiss, "Meissner corpuscles", "Sensory receptors", "#f3dc84",
                               D["meissner"] if thick else D["meissner_hairy"], "nerve", rank=0.5,
                               detail=(0.05, 160.0, 0.6, 2)))
    if cfg["pacinian"]:
        lam, axon = Mesh(), Mesh()
        for i, (px, py, pz, yaw) in enumerate(cfg["pacinian"]):
            c = np.array([px, py, pz])
            ax = np.array([math.cos(yaw), 0.0, math.sin(yaw)])
            radii = np.array([0.13, 0.075, 0.075])
            rot = np.array([[math.cos(yaw), 0.0, -math.sin(yaw)], [0.0, 1.0, 0.0], [math.sin(yaw), 0.0, math.cos(yaw)]])
            for k in range(6):
                s = 1.0 - k * 0.14
                shell = _lamellar_shell(np.zeros(3), radii * s, 0.028 / s, seed=900 + 10 * i + k)
                lam.extend(shell.transformed(rot, c))
            apath = np.array([c - ax * 0.30 + np.array([0.0, 0.04, 0.0]), c - ax * 0.16, c + ax * 0.06])
            axon.extend(tube_mesh(apath, 0.0065, 10, samples=24))
            branch(c - ax * 0.30 + np.array([0.0, 0.04, 0.0]), 0.006, from_deep=True)
        parts.append(mesh_part(lam, "Pacinian corpuscles (lamellae)", "Sensory receptors", "#ece3c6", D["pacinian"],
                               "serosa", rank=-2, detail=(0.04, 90.0, 0.25, 0)))
        parts.append(mesh_part(axon, "Pacinian axon terminal", "Sensory receptors", "#f0cf45", D["pacinian_axon"],
                               "nerve", rank=-2, label=False))
    return parts
