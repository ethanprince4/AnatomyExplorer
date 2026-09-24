"""Skin block models: thin (hairy), thick (glabrous), scalp and axillary skin.

Epidermal strata and dermal layers are high-resolution height fields (dermal papillae, rete ridges, skin furrows,
fingerprint ridges, pores). Appendages, adipocytes and receptors are signed-distance models polygonised with
marching cubes, so follicles, glands and ducts merge smoothly."""
import math

import numpy as np
from scipy.spatial import cKDTree

from .cells import jittered_bcc, poisson_disk
from .organic import settle
from .kit import (Bumps, Grooves, Mesh, Part, Volume, add, at, blob_cluster, capsule, coil_path, dendritic_cell,
                  ellipsoid, hlayer, mesh_part, noise2, round_cone, sdf_part, shift, smooth_path, sphere, tube_mesh,
                  wavy_path)

X0, X1, Z0, Z1 = -1.0, 1.0, -0.7, 0.7

D = {
    "corneum": "Stratum corneum: 15–20 layers (far more in thick skin) of dead, flattened, anucleate corneocytes packed "
               "with keratin and bound by lipid lamellae – the main water barrier. Cells shed continuously (desquamation).",
    "lucidum": "Stratum lucidum: a thin, clear, eosinophilic band of flattened dead cells containing eleidin, "
               "present only in thick skin of palms and soles.",
    "granulosum": "Stratum granulosum: 3–5 layers of flattened cells filled with basophilic keratohyalin granules "
                  "(profilaggrin) and lamellar bodies that release lipids to seal the skin. Nuclei and organelles "
                  "are destroyed here.",
    "spinosum": "Stratum spinosum: several layers of polyhedral keratinocytes joined by numerous desmosomes, which "
                "look like 'prickles' after shrinkage. Langerhans cells (antigen-presenting) live here. Pemphigus "
                "vulgaris antibodies attack these desmosomes.",
    "basale": "Stratum basale: a single row of cuboidal-to-columnar stem keratinocytes on the basement membrane, "
              "anchored by hemidesmosomes (targeted in bullous pemphigoid). Contains melanocytes and Merkel cells.",
    "melanocytes": "Melanocytes: neural-crest-derived dendritic cells in the basal layer (about 1 per 10 basal cells). "
                   "They transfer melanin granules to keratinocytes, forming supranuclear caps against UV light. "
                   "Skin colour depends on melanin type and transfer, not melanocyte number.",
    "papillary": "Papillary dermis: loose connective tissue with thin type I and III collagen, capillary loops and "
                 "sensory endings. Dermal papillae interdigitate with epidermal rete ridges to resist shear forces.",
    "reticular": "Reticular dermis: the thick, dense irregular connective tissue of the skin – coarse type I collagen "
                 "and elastic fibres give strength and recoil. Contains hair follicles, glands and larger vessels. "
                 "Langer's (cleavage) lines follow its collagen orientation.",
    "hypodermis": "Hypodermis (subcutis): loose connective tissue and lobules of white adipose tissue divided by fibrous "
                  "septa. Insulates, stores energy and allows skin to move over deeper fascia. Not strictly part of "
                  "the skin.",
    "fat": "Adipocytes of the hypodermis: large unilocular fat cells (up to 100 µm) whose single lipid droplet pushes "
           "the nucleus to the rim, packed into lobules separated by connective-tissue septa.",
    "shaft": "Hair shaft: keratinised medulla, cortex and cuticle produced by the matrix cells of the hair bulb. Its "
             "pigment comes from melanocytes in the bulb.",
    "irs": "Inner root sheath: keratinising layers (Henle, Huxley and cuticle) that mould the growing hair and "
           "disintegrate at the level of the sebaceous duct.",
    "ors": "Outer root sheath: downward continuation of the epidermis around the follicle. Its bulge region (near the "
           "arrector pili insertion) holds follicular stem cells that also re-epithelialise wounds.",
    "bulb": "Hair bulb & matrix: the expanded base of the follicle where rapidly dividing matrix cells produce the hair. "
            "Chemotherapy halts these cells, causing hair loss.",
    "dermal_papilla": "Dermal papilla of the hair: vascular connective tissue that invaginates the bulb and signals "
                      "to the matrix; its size determines hair size.",
    "sebaceous": "Sebaceous gland: holocrine gland whose cells fill with lipid and disintegrate to release sebum into "
                 "the follicle. Androgen-sensitive – enlarges at puberty (acne vulgaris).",
    "arrector": "Arrector pili: a small bundle of smooth muscle from the follicle bulge to the papillary dermis. "
                "Sympathetic stimulation erects the hair ('goose bumps') and squeezes the sebaceous gland.",
    "eccrine": "Eccrine sweat gland (secretory coil): coiled tubule deep in the dermis with clear cells (water, "
               "electrolytes), dark cells (glycoproteins) and myoepithelial cells. Innervated by sympathetic "
               "cholinergic fibres.",
    "eccrine_duct": "Eccrine sweat duct: two layers of cuboidal cells that reabsorb NaCl (via CFTR) and spiral through "
                    "the epidermis to open at a sweat pore.",
    "apocrine": "Apocrine sweat gland: large coiled gland with a wide lumen in the deep dermis/hypodermis of the axilla, "
                "areola and anogenital region. Secretes viscous protein-rich sweat into hair follicles after puberty; "
                "bacterial breakdown produces odour. Hidradenitis suppurativa affects these regions.",
    "apocrine_duct": "Apocrine duct: opens into the hair follicle above the sebaceous duct.",
    "artery": "Cutaneous arterioles (deep plexus): at the dermis–hypodermis junction, feeding vertical vessels to the "
              "subpapillary plexus. Arteriovenous anastomoses here regulate heat loss.",
    "vein": "Cutaneous venules: drain the papillary capillaries back through the superficial and deep plexuses.",
    "subpapillary": "Subpapillary plexus: horizontal network of small vessels just beneath the papillary dermis that "
                    "gives rise to the capillary loops.",
    "capillary": "Capillary loops of the dermal papillae: supply the avascular epidermis by diffusion. Their "
                 "dilation causes flushing; blanching on pressure distinguishes erythema from purpura.",
    "nerve": "Cutaneous nerve: myelinated and unmyelinated sensory fibres plus sympathetic fibres to glands, vessels "
             "and arrector pili. Many end as free nerve endings (pain, temperature, itch) in the epidermis.",
    "meissner": "Meissner corpuscle: encapsulated stack of flattened Schwann-like cells with interwoven axons, in "
                "dermal papillae of glabrous skin. Rapidly adapting – detects light touch and texture.",
    "pacinian": "Pacinian (lamellar) corpuscle: 20–60 concentric lamellae around a single axon terminal, in the deep "
                "dermis and hypodermis. Rapidly adapting – detects vibration (~250 Hz) and deep pressure.",
}

# The default cut-away removes the quadrant x < 0, z > 0, exposing the planes z = 0 (for x < 0) and x = 0 (for z > 0).
# Follicles are (exit x, exit z, heading in degrees); heading 0 leans toward +x, -90 toward -z, so a follicle can lie
# in a cut plane and be sectioned lengthwise. Eccrine glands are given by their surface pore.
CONFIG = {
    "thin": dict(t_c=0.035, t_l=0.0, t_g=0.02, t_b=0.016, dej=0.855, pap_bottom=0.76, ret_bottom=0.31,
                 follicles=[(-0.22, 0.0, 0), (0.0, 0.2, -90), (0.5, -0.35, 20), (-0.7, 0.34, 35),
                            (0.24, 0.44, -60)], bulb_y=0.33,
                 eccrine=[(-0.78, 0.0), (0.0, 0.62), (0.62, 0.3)],
                 pacinian=[(-0.1, 0.13, 0.0), (0.55, 0.12, -0.4)]),
    "thick": dict(t_c=0.17, t_l=0.03, t_g=0.03, t_b=0.02, dej=0.60, pap_bottom=0.50, ret_bottom=0.28,
                  follicles=[], bulb_y=0.0, eccrine=[(-0.38, 0.0), (-0.76, 0.0), (0.0, 0.3), (0.0, 0.62),
                                                   (0.57, -0.3), (0.19, -0.55)],
                  pacinian=[(0.0, 0.13, 0.5), (-0.58, 0.12, 0.0)]),
    "scalp": dict(t_c=0.03, t_l=0.0, t_g=0.02, t_b=0.016, dej=0.86, pap_bottom=0.78, ret_bottom=0.42,
                  follicles=[(-0.12, 0.0, 0), (-0.38, 0.0, 0), (-0.66, 0.0, 0), (0.0, 0.1, -90), (0.0, 0.34, -90),
                             (0.45, -0.3, 10), (0.7, -0.12, 10)],
                  bulb_y=0.14, eccrine=[(0.0, 0.62), (0.3, -0.55)], pacinian=[]),
    "axilla": dict(t_c=0.035, t_l=0.0, t_g=0.02, t_b=0.016, dej=0.855, pap_bottom=0.76, ret_bottom=0.34,
                   follicles=[(-0.3, 0.0, 0), (0.0, 0.18, -90), (0.5, -0.35, 15), (-0.72, 0.36, 30)], bulb_y=0.31,
                   eccrine=[(-0.85, 0.0), (0.6, 0.35)], pacinian=[]),
}

EPI = "Epidermis"


def build_skin(kind="thin"):
    cfg = CONFIG[kind]
    thick = kind == "thick"
    rng = np.random.default_rng({"thin": 1, "thick": 2, "scalp": 3, "axilla": 4}[kind])
    parts = []
    xr, zr = (X0, X1), (Z0, Z1)

    # ------------------------------------------------------------------ surfaces
    follicle_exits = [(fx, fz) for fx, fz, _ in cfg["follicles"]]
    pore_pts = [(ex, ez) for ex, ez in cfg["eccrine"]]
    period = 0.19
    if thick:
        ridge = lambda X, Z: 0.02 * np.cos(2 * math.pi * (np.asarray(X) + 0.03 * np.sin(np.asarray(Z) * 3.1)) / period
                                           ) * (1.0 + 0.18 * np.sin(np.asarray(Z) * 7.3 + 1.1))
        pores = Bumps(pore_pts, 0.035, -0.03)
        cross = Grooves(poisson_disk((X0 - 0.2, Z0 - 0.2), (X1 + 0.2, Z1 + 0.2), 0.105, seed=17), 0.016, 0.0055)
        base_surf = add(1.0, ridge, pores, noise2(0.004, 8.0, seed=5))
        surf = add(base_surf, cross, noise2(0.0022, 28.0, seed=25, octaves=3))
    else:
        # skin is furrowed at several scales at once: primary sulci, the finer network between them, and the
        # micro-relief of individual shedding corneocytes
        furrows = Grooves(poisson_disk((X0 - 0.2, Z0 - 0.2), (X1 + 0.2, Z1 + 0.2), 0.185, seed=7), 0.020, 0.016)
        fine = Grooves(poisson_disk((X0 - 0.2, Z0 - 0.2), (X1 + 0.2, Z1 + 0.2), 0.072, seed=17), 0.013, 0.0060)
        funnels = Bumps(follicle_exits, 0.07, -0.035) if follicle_exits else (lambda X, Z: 0.0 * np.asarray(X))
        pores = Bumps(pore_pts, 0.03, -0.015)
        base_surf = add(1.0, furrows, funnels, pores, noise2(0.005, 6.0, seed=5))
        surf = add(base_surf, fine, noise2(0.0050, 15.0, seed=24, octaves=2), noise2(0.0026, 30.0, seed=25, octaves=3))

    if thick:
        troughs = lambda X, Z: -0.075 * (0.5 + 0.5 * np.cos(2 * math.pi * (np.asarray(X) + 0.03 * np.sin(
            np.asarray(Z) * 3.1)) / period))
        pap_pts = []
        for k in range(-6, 7):
            for zz in np.arange(Z0 + 0.03, Z1, 0.075):
                cx = (k + 0.5) * period + 0.03 * math.sin(zz * 3.1)
                for side in (-0.028, 0.028):
                    pap_pts.append((cx + side, zz + rng.uniform(-0.01, 0.01)))
        pap_pts = np.array([p for p in pap_pts if X0 - 0.05 < p[0] < X1 + 0.05])
        papillae = Bumps(pap_pts, 0.042, 0.045, k=4)
        dej = add(cfg["dej"], troughs, papillae, noise2(0.004, 11.0, seed=9))
    else:
        pap_pts = poisson_disk((X0 - 0.1, Z0 - 0.1), (X1 + 0.1, Z1 + 0.1), 0.088, seed=11)
        papillae = Bumps(pap_pts, 0.068, 0.058, k=5, sharp=1.5)
        dej = add(cfg["dej"] - 0.028, papillae, noise2(0.010, 5.0, seed=9), noise2(0.004, 17.0, seed=19))

    y_corneum_bottom = add(base_surf, -cfg["t_c"], noise2(0.005, 12.0, seed=21))
    upper = y_corneum_bottom
    parts.append(hlayer("Stratum corneum", EPI, "#e3cfa4", upper, surf, D["corneum"], "skin", xr, zr, rank=4,
                        res=360, detail=(0.07, 120.0, 0.0, 0)))
    if thick:
        y_luc = shift(upper, -cfg["t_l"])
        parts.append(hlayer("Stratum lucidum", EPI, "#e9dfc2", y_luc, upper, D["lucidum"], "skin", xr, zr, rank=3.5, res=300,
                            detail=(0.04, 120.0, 0.0, 0)))
        upper = y_luc
    y_gran = shift(upper, -cfg["t_g"])
    parts.append(hlayer("Stratum granulosum", EPI, "#b184aa", y_gran, upper, D["granulosum"], "skin", xr, zr, rank=3, res=300,
                        detail=(0.12, 150.0, 0.55, 0)))
    y_basale_top = shift(dej, cfg["t_b"])
    y_spin_bottom = lambda X, Z: np.minimum(y_basale_top(X, Z), y_gran(X, Z) - 0.012)
    parts.append(hlayer("Stratum spinosum", EPI, "#e0aeaa", y_spin_bottom, y_gran, D["spinosum"], "skin", xr, zr,
                        rank=2, res=300, detail=(0.10, 120.0, 0.75, 0)))
    parts.append(hlayer("Stratum basale", EPI, "#98566b", dej, y_spin_bottom, D["basale"], "skin", xr, zr, rank=1, res=300,
                        detail=(0.10, 170.0, 0.95, 0)))

    mel = Volume((X0, cfg["dej"] - 0.12, Z0), (X1, cfg["dej"] + 0.12, Z1), 0.0035)
    for i, (mx, mz) in enumerate(poisson_disk((X0 + 0.06, Z0 + 0.06), (X1 - 0.06, Z1 - 0.06), 0.24, seed=31)):
        y = at(dej, mx, mz) + cfg["t_b"] * 0.45
        mel.add_all(dendritic_cell((mx, y, mz), 0.011, 5, 0.04, seed=i), "smooth", 0.006)
    parts.append(sdf_part(mel, "Melanocytes", EPI, "#3b271f", D["melanocytes"], "skin", smooth=0.7, rank=1,
                          detail=(0.05, 0.0, 0.0, 0)))

    # ------------------------------------------------------------------ dermis & hypodermis
    y_pap = add(cfg["pap_bottom"], noise2(0.030, 2.6, seed=41), noise2(0.010, 7.0, seed=42))
    y_ret = add(cfg["ret_bottom"], noise2(0.050, 2.0, seed=43), noise2(0.016, 5.5, seed=44))
    parts.append(hlayer("Papillary dermis", "Dermis", "#efbcac", y_pap, dej, D["papillary"], "fascia", xr, zr,
                        bulk=True, rank=0, res=300, detail=(0.12, 70.0, 0.18, 0)))
    parts.append(hlayer("Reticular dermis", "Dermis", "#dfa092", y_ret, y_pap, D["reticular"], "fascia", xr, zr,
                        bulk=True, rank=-1, detail=(0.16, 42.0, 0.10, 1)))
    parts.append(hlayer("Hypodermis septa", "Hypodermis", "#efd6a6", 0.0, y_ret, D["hypodermis"], "fascia", xr, zr,
                        bulk=True, rank=-2, detail=(0.10, 50.0, 0.12, 0)))
    parts.append(_adipocytes(y_ret, rng))

    # ------------------------------------------------------------------ appendages
    follicle_paths = []
    if cfg["follicles"]:
        follicle_parts, follicle_paths = _follicles(cfg, surf, dej, kind)
        parts += follicle_parts
    parts += _eccrine(cfg, surf, dej, thick, kind)
    if kind == "axilla":
        parts += _apocrine(follicle_paths)

    # ------------------------------------------------------------------ vessels, nerves, receptors
    parts += _vessels(cfg, dej, pap_pts, thick)
    parts += _nerves(cfg, dej, pap_pts, thick)
    return settle(parts, seed={"thin": 101, "thick": 102, "scalp": 103, "axilla": 104}[kind],
                  amp_xz=0.030, amp_y=0.075, freq=1.7)


# ============================================================================================ helpers
def _adipocytes(y_ret, rng):
    top = float(np.min(y_ret(np.linspace(X0, X1, 50)[:, None], np.linspace(Z0, Z1, 40)[None, :])))
    vol = Volume((X0, 0.0, Z0), (X1, top, Z1), 0.0085)
    x, y, z = vol.axes()
    lob_centres = jittered_bcc((X0 - 0.2, -0.1, Z0 - 0.2), (X1 + 0.2, top + 0.1, Z1 + 0.2), 0.42, 0.25, seed=51)
    cells = jittered_bcc((X0 - 0.08, -0.06, Z0 - 0.08), (X1 + 0.08, top + 0.06, Z1 + 0.08), 0.082, 0.2, seed=53)
    grid = np.stack(np.broadcast_arrays(x, y, z), -1).reshape(-1, 3)
    d, _ = cKDTree(cells).query(grid, k=2, workers=-1)
    cell_d = (-(d[:, 1] - d[:, 0]) / 2.0 + 0.0045).reshape(vol.shape).astype(np.float32)
    dl, il = cKDTree(lob_centres).query(grid, k=2, workers=-1)
    lobule_d = ((-(dl[:, 1] - dl[:, 0]) / 2.0) + 0.02).reshape(vol.shape).astype(np.float32)
    vol.d = np.maximum(cell_d, lobule_d)
    vol.intersect_box((X0, 0.0, Z0), (X1, top - 0.012, Z1))
    return sdf_part(vol, "Adipocytes (fat lobules)", "Hypodermis", "#f6dc93", D["fat"], "fat", smooth=0.9, rank=-2,
                    detail=(0.05, 22.0, 0.08, 0))


def _follicle_path(exit_xz, surf, bulb_y, lean, heading_deg):
    ex, ez = exit_xz
    top_y = at(surf, ex, ez)
    h = math.radians(heading_deg)
    horiz = np.array([math.cos(h), 0.0, math.sin(h)])
    d = np.array([lean * horiz[0], 1.0, lean * horiz[2]])
    d /= np.linalg.norm(d)
    length = (top_y - bulb_y) / d[1]
    base = np.array([ex, top_y, ez]) - d * length
    # 'side' stays in the vertical plane of the follicle, so glands attached along it share any cut through the hair
    side = horiz - d * float(np.dot(d, horiz))
    side /= np.linalg.norm(side)
    ctrl = [base, base + d * length * 0.35 + side * 0.012, base + d * length * 0.7 - side * 0.01,
            np.array([ex, top_y, ez])]
    return smooth_path(np.array(ctrl), 60), d, side


def _follicles(cfg, surf, dej, kind):
    groups = {k: Mesh() for k in ("shaft", "irs", "ors", "bulb", "pap", "seb", "arr")}
    paths = []
    scalp = kind == "scalp"
    for i, (fx, fz, heading) in enumerate(cfg["follicles"]):
        lean = 0.42 if not scalp else 0.30
        path, d, side = _follicle_path((fx, fz), surf, cfg["bulb_y"] + (0.02 * (i % 2) if scalp else 0.0), lean,
                                       heading)
        paths.append((path, d, side))
        base, top = path[0], path[-1]
        length = float(np.linalg.norm(top - base))
        r_ors = 0.046 if scalp else 0.040
        lo = np.minimum(base, top) - 0.16
        hi = np.maximum(base, top) + np.array([0.16, 0.34, 0.16])
        vox = 0.0032

        def vol():
            return Volume(lo, hi, vox)

        n = len(path)
        t = np.linspace(0, 1, n)
        # outer root sheath: widens into the infundibulum at the surface
        ors = vol().tube(path[4:], r_ors * (1.0 + 0.35 * t[4:] ** 6), "union")
        bulb = vol().add(ellipsoid(base + d * 0.035, (r_ors * 1.75, r_ors * 2.0, r_ors * 1.75)), "union")
        pap = vol().add(ellipsoid(base + d * 0.012, (r_ors * 0.62, r_ors * 1.05, r_ors * 0.62)), "union")
        irs = vol().tube(path[2:int(n * 0.62)], r_ors * 0.62, "union")
        out_t = np.linspace(0.02, 0.34 if not scalp else 0.40, 18)[:, None]
        bend = np.array([math.cos(h_out := math.radians(30 + 55 * i)), 0.0, math.sin(h_out)])
        curl = side[None, :] * (0.9 * out_t ** 2) + bend[None, :] * (0.7 * out_t ** 2.3)
        shaft_path = np.vstack([path[3:], top + d * out_t + curl])
        shaft_r = np.concatenate([np.full(len(path) - 3, r_ors * 0.46),
                                  np.linspace(r_ors * 0.46, r_ors * 0.22, 18)])
        shaft = vol().tube(shaft_path, shaft_r, "union")
        # bulb cups the dermal papilla; root sheaths are hollow around the hair
        bulb.apply(pap.d, (slice(None),) * 3, "smooth_subtract", 0.006)
        ors.apply(bulb.d, (slice(None),) * 3, "smooth", 0.02)
        ors.apply(irs.d, (slice(None),) * 3, "subtract")
        ors.apply(shaft.d, (slice(None),) * 3, "subtract")
        bulb_only = bulb.copy(np.maximum(bulb.d, -(irs.d - 0.004)))
        irs.apply(shaft.d, (slice(None),) * 3, "subtract")
        ors.apply(bulb_only.d, (slice(None),) * 3, "subtract")
        ors.displace(0.0015, 55.0, 2, seed=i)
        # sebaceous gland and arrector pili sit on the obtuse-angle side (the side the hair leans toward)
        s_anchor = path[int(n * 0.66)]
        s_center = s_anchor + side * 0.085 - d * 0.03
        seb = vol().add_all(blob_cluster(s_center, 8 if not scalp else 10, 0.032 if not scalp else 0.038,
                                         (0.05, 0.06, 0.05), seed=60 + i), "smooth", 0.018)
        seb.add(capsule(s_center, s_anchor + side * 0.02, 0.016), "smooth", 0.012)
        seb.apply(ors.d, (slice(None),) * 3, "smooth_subtract", 0.004)
        seb.displace(0.002, 45.0, 2, seed=70 + i)
        # arrector pili from the bulge to the papillary dermis
        bulge = path[int(n * 0.38)] + side * r_ors * 1.05
        end_xz = bulge[[0, 2]] + side[[0, 2]] * 0.28 / max(float(np.linalg.norm(side[[0, 2]])), 1e-6)
        end = np.array([end_xz[0], at(dej, end_xz[0], end_xz[1]) - 0.05, end_xz[1]])
        mid = (bulge + end) / 2 + np.array([0.0, -0.04, 0.0])
        arr_path = smooth_path(np.array([bulge, mid, end]), 24)
        arr = vol().tube(arr_path, np.linspace(0.02, 0.009, len(arr_path)), "union")
        arr.displace(0.0025, 38.0, 2, seed=80 + i)

        groups["shaft"].extend(shaft.mesh(0.7))
        groups["irs"].extend(irs.mesh(0.7))
        groups["ors"].extend(ors.mesh(0.8))
        groups["bulb"].extend(bulb_only.mesh(0.8))
        groups["pap"].extend(pap.mesh(0.8))
        groups["seb"].extend(seb.mesh(0.9))
        groups["arr"].extend(arr.mesh(0.8))
    parts = [
        mesh_part(groups["shaft"], "Hair shaft", "Hair follicle", "#5a3d2b", D["shaft"], "nail", rank=3,
                  detail=(0.05, 60.0, 0.0, 2)),
        mesh_part(groups["irs"], "Inner root sheath", "Hair follicle", "#d8b172", D["irs"], "skin", rank=0.2,
                  detail=(0.08, 140.0, 0.5, 2)),
        mesh_part(groups["ors"], "Outer root sheath", "Hair follicle", "#e7bea0", D["ors"], "skin", rank=0.1,
                  detail=(0.10, 130.0, 0.85, 0)),
        mesh_part(groups["bulb"], "Hair bulb (matrix)", "Hair follicle", "#8d5664", D["bulb"], "skin", rank=-0.6,
                  detail=(0.10, 170.0, 0.95, 0)),
        mesh_part(groups["pap"], "Dermal papilla of hair", "Hair follicle", "#dc7470", D["dermal_papilla"], "fascia",
                  rank=-0.8, detail=(0.10, 80.0, 0.45, 0)),
        mesh_part(groups["seb"], "Sebaceous gland", "Glands", "#f2df98", D["sebaceous"], "gland", rank=-0.4,
                  detail=(0.10, 75.0, 0.55, 0)),
        mesh_part(groups["arr"], "Arrector pili muscle", "Glands", "#b64c45", D["arrector"], "muscle", rank=-0.4,
                  detail=(0.08, 90.0, 0.45, 0)),
    ]
    return parts, paths


def _eccrine(cfg, surf, dej, thick, kind):
    coils, ducts = Mesh(), Mesh()
    for i, (ex, ez) in enumerate(cfg["eccrine"]):
        cy = cfg["ret_bottom"] + (0.05 if thick else 0.04)
        center = np.array([ex + 0.05, cy, ez - 0.03])
        coil = coil_path(center, 0.085 if not thick else 0.078, points=360, seed=40 + i, length=1.05)
        top_y = at(surf, ex, ez)
        dej_y = at(dej, ex, ez)
        rise = smooth_path(np.array([coil[-1], center + np.array([-0.02, 0.12, 0.02]),
                                     np.array([ex + 0.03, (cy + dej_y) / 2, ez + 0.01]),
                                     np.array([ex, dej_y - 0.01, ez])]), 50)
        turns = 3.5 if thick else 2.5
        a = np.linspace(0, turns * 2 * math.pi, 90)
        spiral = np.stack([ex + 0.022 * np.cos(a), dej_y + (top_y - dej_y + 0.004) * a / a[-1],
                           ez + 0.022 * np.sin(a)], -1)
        lo = np.array([min(ex, center[0]) - 0.15, cy - 0.12, min(ez, center[2]) - 0.15])
        hi = np.array([max(ex, center[0]) + 0.15, top_y + 0.03, max(ez, center[2]) + 0.15])
        v = Volume(lo, hi, 0.0032)
        v.tube(coil, 0.0135, "union")
        v.displace(0.0012, 60.0, 2, seed=90 + i)
        coils.extend(v.mesh(0.8))
        w = Volume(lo, hi, 0.0032)
        w.tube(np.vstack([rise, spiral[1:]]), 0.0105, "union")
        ducts.extend(w.mesh(0.7))
    return [
        mesh_part(coils, "Eccrine sweat gland (secretory coil)", "Glands", "#8db8e6", D["eccrine"], "gland", rank=-1,
                  detail=(0.08, 150.0, 0.85, 0)),
        mesh_part(ducts, "Eccrine sweat duct", "Glands", "#5d8fd0", D["eccrine_duct"], "gland", rank=0,
                  detail=(0.08, 160.0, 0.85, 0)),
    ]


def _apocrine(follicle_paths):
    glands, ducts = Mesh(), Mesh()
    for i, (path, d, side) in enumerate(follicle_paths):
        base = path[0]
        horiz = np.array([side[0], 0.0, side[2]])
        horiz /= max(float(np.linalg.norm(horiz)), 1e-6)
        center = base - horiz * 0.17 + np.array([0.0, -0.07, 0.0])
        coil = coil_path(center, 0.12, points=300, seed=70 + i, step=0.02, length=0.75)
        entry = path[int(len(path) * 0.8)]
        lo, hi = np.minimum(center, entry) - 0.18, np.maximum(center, entry) + 0.18
        v = Volume(lo, hi, 0.0038)
        v.tube(coil, 0.032, "union")
        lumen = Volume(lo, hi, 0.0038).tube(coil, 0.019, "union")
        v.apply(lumen.d, (slice(None),) * 3, "subtract")
        v.displace(0.0015, 40.0, 2, seed=110 + i)
        glands.extend(v.mesh(0.8))
        w = Volume(lo, hi, 0.0038)
        w.tube(smooth_path(np.array([coil[-1], (coil[-1] + entry) / 2 + np.array([-0.06, 0.02, 0.0]), entry]), 40),
               0.011, "union")
        ducts.extend(w.mesh(0.7))
    return [mesh_part(glands, "Apocrine sweat gland", "Glands", "#7fc4ae", D["apocrine"], "gland", rank=-1.5,
                      detail=(0.08, 110.0, 0.8, 0)),
            mesh_part(ducts, "Apocrine duct", "Glands", "#58a78d", D["apocrine_duct"], "gland", rank=-0.5)]


def _vessels(cfg, dej, pap_pts, thick):
    art, vein, subp, caps = Mesh(), Mesh(), Mesh(), Mesh()
    deep_y = cfg["ret_bottom"] + 0.01
    sub_y = cfg["pap_bottom"] + 0.02
    for j, z in enumerate((-0.48, 0.02, 0.5)):
        art.extend(tube_mesh(wavy_path((X0 + 0.01, deep_y, z), (X1 - 0.01, deep_y + 0.01, z + 0.05), 60, 0.025, 2.0,
                                       seed=j), 0.018, 20))
        vein.extend(tube_mesh(wavy_path((X0 + 0.01, deep_y - 0.02, z + 0.08), (X1 - 0.01, deep_y - 0.015, z + 0.1), 60,
                                        0.03, 1.6, seed=10 + j), 0.026, 22))
    for k, x in enumerate(np.linspace(-0.8, 0.8, 6)):
        z = -0.48 if k % 2 else 0.02
        art.extend(tube_mesh(wavy_path((x, deep_y, z), (x + 0.05, sub_y, z + 0.12), 30, 0.015, 1.5, seed=20 + k),
                             0.0085, 14))
        vein.extend(tube_mesh(wavy_path((x + 0.06, deep_y - 0.02, z + 0.08), (x + 0.1, sub_y - 0.01, z + 0.2), 30,
                                        0.015, 1.5, seed=30 + k), 0.011, 14))
    for j, z in enumerate(np.linspace(Z0 + 0.1, Z1 - 0.1, 5)):
        subp.extend(tube_mesh(wavy_path((X0 + 0.01, sub_y, z), (X1 - 0.01, sub_y + 0.01, z + 0.04), 80, 0.02, 4.0,
                                        seed=40 + j), 0.008, 12))
    for j, x in enumerate(np.linspace(X0 + 0.15, X1 - 0.15, 6)):
        subp.extend(tube_mesh(wavy_path((x, sub_y + 0.004, Z0 + 0.01), (x + 0.06, sub_y, Z1 - 0.01), 60, 0.02, 3.0,
                                        seed=60 + j), 0.007, 12))
    for i, (px, pz) in enumerate(pap_pts):
        if not (X0 + 0.03 < px < X1 - 0.03 and Z0 + 0.03 < pz < Z1 - 0.03):
            continue
        apex = at(dej, px, pz) - 0.018
        a = i * 1.7
        off = np.array([math.cos(a), 0.0, math.sin(a)]) * 0.011
        c = np.array([px, apex, pz])
        loop = np.array([np.array([px, sub_y, pz]) - off * 1.5, c - off + np.array([0, -0.03, 0]),
                         c + np.array([0.0, 0.006, 0.0]), c + off + np.array([0, -0.03, 0]),
                         np.array([px, sub_y, pz]) + off * 1.5])
        caps.extend(tube_mesh(loop, 0.0042, 8, samples=24))
    return [
        mesh_part(art, "Arterioles", "Vessels & nerves", "#cf3a31", D["artery"], "artery", rank=-1),
        mesh_part(vein, "Venules", "Vessels & nerves", "#3b5cc4", D["vein"], "vein", rank=-1),
        mesh_part(subp, "Subpapillary plexus", "Vessels & nerves", "#d9564e", D["subpapillary"], "artery", rank=0),
        mesh_part(caps, "Papillary capillary loops", "Vessels & nerves", "#e3625a", D["capillary"], "artery",
                  rank=0.5),
    ]


def _nerves(cfg, dej, pap_pts, thick):
    parts = []
    nerve = Mesh()
    ny = cfg["ret_bottom"] + 0.07
    nerve.extend(tube_mesh(wavy_path((X0 + 0.01, ny, 0.42), (X1 - 0.01, ny + 0.02, 0.36), 70, 0.03, 1.5, seed=3),
                           0.018, 18))
    near_cut = [p for p in pap_pts if (abs(p[1]) < 0.035 and X0 + 0.05 < p[0] < 0.0) or
                (abs(p[0]) < 0.035 and 0.0 < p[1] < Z1 - 0.05)]
    elsewhere = [p for p in pap_pts if 0.05 < p[1] < 0.6 and X0 + 0.05 < p[0] < X1 - 0.05]
    targets = near_cut[::2] + elsewhere[:: (6 if thick else 9)]
    meiss = None
    if thick:
        lo = np.array([X0, cfg["dej"] - 0.12, Z0])
        hi = np.array([X1, cfg["dej"] + 0.12, Z1])
        meiss = Volume(lo, hi, 0.0028)
    for i, (px, pz) in enumerate(targets):
        apex = at(dej, px, pz)
        start = np.array([px - 0.1, ny, 0.40])
        end = np.array([px, apex - (0.05 if thick else 0.02), pz])
        nerve.extend(tube_mesh(smooth_path(np.array([start, (start + end) / 2 + np.array([0.03, 0.02, 0.0]), end]),
                                           30), 0.0045, 10))
        if meiss is not None:
            c = np.array([px, apex - 0.035, pz])
            shell = meiss.sub(c - 0.05, c + 0.05)
            shell.add(ellipsoid(c, (0.017, 0.032, 0.017)))
            core = shell.copy(shell.d + 0.004)
            shell.d = np.maximum(shell.d, -core.d)
            for k in range(6):
                shell.add(ellipsoid(c + np.array([0.0, -0.024 + k * 0.0095, 0.0]), (0.013, 0.0028, 0.012)))
            meiss.merge(shell, "union")
    parts.append(mesh_part(nerve, "Cutaneous nerve & branches", "Vessels & nerves", "#f0cf45", D["nerve"], "nerve",
                           rank=-1))
    if meiss is not None:
        parts.append(sdf_part(meiss, "Meissner corpuscles", "Sensory receptors", "#f5de7a", D["meissner"], "nerve",
                              smooth=0.6, rank=0.5, detail=(0.05, 160.0, 0.6, 2)))
    if cfg["pacinian"]:
        lam = Mesh()
        axon = Mesh()
        for i, (px, py, pz) in enumerate(cfg["pacinian"]):
            c = np.array([px, py, pz])
            v = Volume(c - 0.12, c + 0.12, 0.0026)
            base = ellipsoid(c, (0.085, 0.055, 0.055))
            fnb, _, _ = base
            x, y, z = v.axes()
            dist = fnb(x, y, z)
            onion = np.full(v.shape, 1e3, np.float32)
            for k in range(8):
                ring = np.abs(dist + k * 0.0068) - 0.0016
                onion = np.minimum(onion, ring)
            v.d = np.maximum(onion, dist).astype(np.float32)
            lam.extend(v.mesh(0.6))
            a = Volume(c - 0.25, c + 0.12, 0.0026)
            ax_path = smooth_path(np.array([c + np.array([-0.24, 0.05, 0.0]), c + np.array([-0.12, 0.01, 0.0]),
                                            c + np.array([0.05, 0.0, 0.0])]), 20)
            a.tube(ax_path, np.linspace(0.006, 0.0045, len(ax_path)))
            axon.extend(a.mesh(0.6))
        parts.append(mesh_part(lam, "Pacinian corpuscles (lamellae)", "Sensory receptors", "#efe6c8", D["pacinian"],
                               "serosa", rank=-2, detail=(0.04, 90.0, 0.25, 0)))
        parts.append(mesh_part(axon, "Pacinian axon terminal", "Sensory receptors", "#f0cf45", D["pacinian"], "nerve",
                               rank=-2, label=False))
    return parts
