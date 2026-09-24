"""High-resolution wall models of the stomach, oesophagus and trachea."""
import math

import numpy as np
from scipy.spatial import Delaunay, cKDTree

from .cells import hex_points, poisson_disk
from .geometry import Mesh, compute_normals, ellipsoid as ellipsoid_mesh, smooth_path, tube
from .kit import (Bumps, Grooves, Volume, add, at, capsule, ellipsoid, fn, hlayer, mesh_part, noise2, round_cone,
                  sdf_part, shift, wavy_path)
from .organic import settle, texture
from .sdf import fbm3

X0, X1, Z0, Z1 = -1.0, 1.0, -0.6, 0.6
XR, ZR = (X0, X1), (Z0, Z1)


def _network(center_y_fn, spacing, node_r, strand_r, seed, voxel=0.0035, thickness=0.03, x=XR, z=ZR):
    """A plexus: flattened ganglia joined by nerve strands, polygonised as one organic network."""
    pts = poisson_disk((x[0] - 0.05, z[0] - 0.05), (x[1] + 0.05, z[1] + 0.05), spacing, seed=seed)
    ys = np.array([at(center_y_fn, p[0], p[1]) for p in pts])
    lo_y, hi_y = float(ys.min()) - thickness, float(ys.max()) + thickness
    vol = Volume((x[0], lo_y, z[0]), (x[1], hi_y, z[1]), voxel)
    rng = np.random.default_rng(seed)
    shapes = []
    for (px, pz), y in zip(pts, ys):
        a = rng.uniform(0, math.pi)
        rot = np.array([[math.cos(a), 0, -math.sin(a)], [0, 1, 0], [math.sin(a), 0, math.cos(a)]])
        shapes.append(ellipsoid((px, y, pz), (node_r * rng.uniform(1.0, 1.6), node_r * 0.38, node_r), rot))
    edges = set()
    for s in Delaunay(pts).simplices:
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
    vol.intersect_box((x[0], lo_y - 1, z[0]), (x[1], hi_y + 1, z[1]))
    return vol


def _lattice(spacing, jitter=0.0, seed=0):
    """Gland or pit centres on a hexagonal lattice with a row on z = 0 and a column on x = 0 - the cut planes - so the
    cut-away sections them lengthwise. The jitter fades out near each plane to keep that section clean."""
    pts = []
    dz = spacing * math.sqrt(3) / 2
    for j in range(-int(Z1 / dz) - 1, int(Z1 / dz) + 2):
        z = j * dz
        off = spacing / 2 if j % 2 else 0.0
        for i in range(-int(X1 / spacing) - 2, int(X1 / spacing) + 3):
            x = i * spacing + off
            if X0 + spacing * 0.4 < x < X1 - spacing * 0.4 and Z0 + spacing * 0.4 < z < Z1 - spacing * 0.4:
                pts.append((x, z))
    pts = np.array(pts)
    if jitter and len(pts):
        rng = np.random.default_rng(abs(int(seed)) + 1)
        keep = np.clip(np.abs(pts) / (spacing * 0.7), 0.0, 1.0)
        pts = pts + rng.uniform(-jitter, jitter, pts.shape) * spacing * keep
    return pts


def _exposure(X, Z):
    """Distance from (x, z) to the nearest face that shows the inside of a block: its four sides and the two
    planes of the default cut-away (x = 0 for z > 0, z = 0 for x < 0)."""
    X, Z = np.broadcast_arrays(np.asarray(X, np.float64), np.asarray(Z, np.float64))
    return np.minimum.reduce([X1 - X, X - X0, Z1 - Z, Z - Z0, np.where(Z > -0.03, np.abs(X), 9.0),
                              np.where(X < 0.03, np.abs(Z), 9.0)])


def _bundles(bottom, top, angle, spacing, rows, seed, fill=0.62, segments=12, x=XR, z=ZR, wobble=0.22, proud=0.002,
             mask=None):
    """A layer of smooth-muscle bundles as swept tubes running at `angle` degrees in the xz plane (0 along x, 90 along
    z), stacked in `rows` between two height functions. Ends are pressed flat onto the faces of the block, so a
    face that cuts a bundle shows its section. `mask(x, z, i)` keeps only part of bundle i (where it is True)."""
    rng = np.random.default_rng(seed)
    a = math.radians(angle)
    d = np.array([math.cos(a), math.sin(a)])
    n = np.array([-math.sin(a), math.cos(a)])
    reach = math.hypot(x[1] - x[0], z[1] - z[0]) / 2 + 0.1
    t = np.linspace(-reach, reach, int(reach * 2 / 0.03))
    m = Mesh()
    count = 0
    for r in range(rows):
        c = -reach + spacing * (0.5 * (r % 2) + rng.uniform(0, 0.3))
        while c < reach:
            ph = rng.uniform(0, 2 * math.pi, 3)
            off = c + spacing * wobble * np.sin(t * 2.3 + ph[0])
            px, pz = d[0] * t + n[0] * off, d[1] * t + n[1] * off
            inside = (px > x[0] - 0.06) & (px < x[1] + 0.06) & (pz > z[0] - 0.06) & (pz < z[1] + 0.06)
            c += spacing * rng.uniform(0.9, 1.1)
            count += 1
            in_box = inside.copy()
            if mask is not None:
                inside &= mask(px, pz, count)
            edges = np.flatnonzero(np.diff(np.concatenate([[0], inside.astype(np.int8), [0]])))
            for i0, i1 in zip(edges[::2], edges[1::2]):
                if i1 - i0 < 4:
                    continue
                qx, qz, tt = px[i0:i1], pz[i0:i1], t[i0:i1]
                lo, hi = bottom(qx, qz), top(qx, qz)
                frac = (r + 0.5) / rows + 0.10 / rows * np.sin(tt * 3.1 + ph[1])
                py = lo + (hi - lo) * frac
                rs = spacing * fill * (1.0 + 0.10 * np.sin(tt * 4.3 + ph[2]))
                ry = (hi - lo) / rows * 0.56
                # a bundle that the mask ends inside the block tapers off there instead of stopping flat
                k_ = np.arange(i1 - i0, dtype=float)
                d0 = k_ if i0 > 0 and in_box[i0 - 1] else np.full_like(k_, 9.0)
                d1 = k_[::-1] if i1 < len(t) and in_box[i1] else np.full_like(k_, 9.0)
                end = np.clip(np.minimum(d0, d1) / 3.0, 0.35, 1.0)
                rs, ry = rs * end, ry * end
                m.extend(tube(np.stack([qx, py, qz], -1), rs, segments, ry=ry))
    for pos, _, _ in m.parts:
        np.clip(pos[:, 0], x[0] - proud, x[1] + proud, out=pos[:, 0])
        np.clip(pos[:, 2], z[0] - proud, z[1] + proud, out=pos[:, 2])
        # bundles pressed against the layer's boundaries flatten there rather than poke into the next layer
        pos[:, 1] = np.clip(pos[:, 1], bottom(pos[:, 0], pos[:, 2]) + 0.002, top(pos[:, 0], pos[:, 2]) - 0.002)
    return m


def _vessel_pairs(y_fn, zs, seed, r_art=0.016, r_vein=0.022, amp=0.03, gap=0.055):
    """Artery-vein pairs meandering along x at height y_fn(x, z)."""
    art, vein = Mesh(), Mesh()
    for j, z in enumerate(zs):
        path = wavy_path((X0, 0, z), (X1, 0, z + 0.05), 80, amp, 1.5, seed=seed + j)
        path[:, 1] = y_fn(path[:, 0], path[:, 2])
        art.extend(tube(path, r_art, 16))
        v = path.copy()
        v[:, 2] += gap
        v[:, 1] = y_fn(v[:, 0], v[:, 2])
        vein.extend(tube(v, r_vein, 16))
    for m in (art, vein):
        for pos, _, _ in m.parts:
            np.clip(pos[:, 0], X0 - 0.002, X1 + 0.002, out=pos[:, 0])
    return art, vein


def _drop_floor(mesh, floor_fn, tol=0.004):
    """Remove the downward faces lying on a floor (the top of the layer beneath covers them): a closed solid's flat
    underside costs as many triangles as its whole top."""
    out = Mesh()
    for pos, nrm, idx in mesh.parts:
        c = pos[idx].mean(axis=1)
        fn_ = np.cross(pos[idx[:, 1]] - pos[idx[:, 0]], pos[idx[:, 2]] - pos[idx[:, 0]])
        down = fn_[:, 1] < -0.9 * np.linalg.norm(fn_, axis=1)
        low = c[:, 1] < at_many(floor_fn, c[:, 0], c[:, 2]) + tol
        out.parts.append((pos, nrm, idx[~(down & low)]))
    return out


# ==================================================================================================== stomach
STOMACH_TEXT = {
    "surface": "Surface mucous (foveolar) cells: a simple columnar epithelium whose every cell is a mucous cell, "
               "secreting an adherent, bicarbonate-rich neutral mucus gel that shields the mucosa from acid and "
               "pepsin (prostaglandins keep it coming – NSAIDs undermine it). There are no goblet cells in the "
               "normal stomach; finding them is intestinal metaplasia. The cells are shed and replaced every 3–5 "
               "days. Gastric pits (foveolae) are funnels of the same epithelium; in the fundus and body they occupy "
               "the upper quarter of the mucosa and 2–7 glands open into each.",
    "neck": "Isthmus and neck: the isthmus under the pit holds the stem cells that renew both the pit and the gland; "
            "the neck is lined by mucous neck cells – small cells with pale apical mucin granules and a compressed "
            "basal nucleus – interspersed with parietal cells.",
    "parietal": "Parietal (oxyntic) cells: large, rounded, bright eosinophilic cells ('fried eggs' with a central "
                "nucleus) that bulge from the outside of the glands, most numerous in the neck and upper body. "
                "Intracellular canaliculi lined by H+/K+-ATPase secrete HCl, and they make intrinsic factor for "
                "vitamin B12 absorption. Driven by gastrin, histamine (H2) and acetylcholine (M3); blocked by PPIs "
                "and H2 antagonists. Destroyed in autoimmune (pernicious anaemia) gastritis.",
    "chief": "Chief (zymogen) cells: basophilic cells lining the base of the glands, full of rough ER and apical "
             "zymogen granules of pepsinogen (activated to pepsin by acid) and gastric lipase. Stimulated mainly by "
             "vagal acetylcholine.",
    "ee": "Enteroendocrine cells: small pale cells on the basal lamina of the gland with their granules at the "
          "base, releasing hormones into the lamina propria rather than the lumen. In the body most are "
          "enterochromaffin-like (ECL) cells that release histamine when gastrin reaches them; D cells make "
          "somatostatin. Chronic hypergastrinaemia makes ECL cells proliferate (carcinoid tumours).",
    "lp": "Lamina propria: scanty loose connective tissue squeezed between the glands, with capillaries, lymphocytes, "
          "plasma cells and wisps of smooth muscle from the muscularis mucosae. In H. pylori gastritis it fills with "
          "lymphoid follicles.",
    "mm": "Muscularis mucosae: thin inner circular and outer longitudinal smooth muscle whose strands rise between "
          "the glands and squeeze their secretions out. Cancer confined above it is 'early gastric cancer'.",
    "sub": "Submucosa: dense irregular connective tissue with the larger arteries, veins and lymphatics and the "
           "submucosal plexus; here it forms the core of a ruga, a longitudinal fold of mucosa and submucosa that "
           "flattens as the stomach fills.",
    "meissner": "Submucosal (Meissner) plexus: small ganglia and nerve strands controlling secretion and local blood "
                "flow in the mucosa.",
    "artery": "Submucosal arteries: from the gastric and gastroepiploic arcades; they form a plexus that supplies "
              "the mucosal capillaries around the glands. Erosion of one by a posterior duodenal or lesser-curve "
              "ulcer causes major haemorrhage.",
    "vein": "Submucosal veins: drain to the gastric veins and the portal vein; at the cardia they anastomose with "
            "oesophageal veins (a site of varices in portal hypertension).",
    "lymph": "Lymphatics: begin at the base of the glands, run in the submucosa and drain to the gastric and "
             "coeliac nodes – the path of lymphatic spread of gastric cancer.",
    "oblique": "Inner oblique layer: unique to the stomach, strongest near the cardia and over the body; it runs "
               "obliquely beneath the circular layer and helps churn food into chyme.",
    "circ": "Middle circular layer: the thickest layer of the muscularis externa; thickened into the pyloric "
            "sphincter (hypertrophied in infantile pyloric stenosis).",
    "long": "Outer longitudinal layer: most distinct along the curvatures. With the circular layer it drives the "
            "peristaltic waves that start at the pacemaker region of the greater curvature.",
    "myenteric": "Myenteric (Auerbach) plexus: ganglia between the circular and longitudinal layers that coordinate "
                 "gastric motility under vagal control; interstitial cells of Cajal alongside it set the slow-wave "
                 "rhythm (about 3 per minute).",
    "serosa": "Serosa: a simple squamous mesothelium on a thin layer of loose connective tissue – the visceral "
              "peritoneum, continuous with the lesser and greater omenta.",
    "septa": "Connective tissue septa between the smooth muscle bundles of the muscularis externa, carrying their "
             "capillaries and nerve fibres; the myenteric plexus lies in the septum between the circular and "
             "longitudinal layers.",
}


def build_stomach():
    parts = []
    rng = np.random.default_rng(12)
    fold = lambda X, Z: (0.15 * np.exp(-((np.asarray(Z) - 0.27 - 0.03 * np.sin(np.asarray(X) * 2.2)) / 0.13) ** 2)
                         + 0.09 * np.exp(-((np.asarray(Z) + 0.40 - 0.03 * np.sin(np.asarray(X) * 1.7 + 1)) / 0.11) ** 2))
    y_ser = 0.022
    y_l = add(0.100, noise2(0.004, 3.0, seed=3))
    y_c0, y_c1 = shift(y_l, 0.012), add(0.255, noise2(0.004, 3.0, seed=4))
    y_o0, y_o1 = shift(y_c1, 0.007), add(0.325, noise2(0.004, 3.0, seed=5))
    y_sub = add(0.435, fold, noise2(0.006, 3.0, seed=6))
    y_mm = shift(y_sub, 0.024)
    areae = Grooves(poisson_disk((X0 - 0.2, Z0 - 0.2), (X1 + 0.2, Z1 + 0.2), 0.26, seed=7), 0.016, 0.012)
    y_s = add(y_mm, 0.32, areae, noise2(0.004, 9.0, seed=8))

    parts.append(hlayer("Serosa", "Muscularis externa", "#eadcb8", 0.0, y_ser, STOMACH_TEXT["serosa"], "serosa", XR,
                        ZR, bulk=True, rank=-4, res=110, detail=(0.06, 80.0, 0.2, 0)))
    for k, (name, bottom, top, angle, spacing, rows, color, text, fibre) in enumerate((
            ("Outer longitudinal muscle", y_ser, y_l, 0, 0.085, 2, "#c25d51", STOMACH_TEXT["long"], 1),
            ("Middle circular muscle", y_c0, y_c1, 90, 0.080, 3, "#a8463d", STOMACH_TEXT["circ"], 3),
            ("Inner oblique muscle", y_o0, y_o1, 45, 0.085, 2, "#b65247", STOMACH_TEXT["oblique"], 0))):
        parts.append(mesh_part(_bundles(fn(bottom), fn(top), angle, spacing, rows, seed=180 + 7 * k), name,
                               "Muscularis externa", color, text, "muscle", rank=-3, detail=(0.08, 80.0, 0.4, fibre)))
    parts.append(hlayer("Intermuscular connective tissue", "Muscularis externa", "#d9b4a3", y_ser, y_o1,
                        STOMACH_TEXT["septa"], "fascia", XR, ZR, bulk=True, rank=-3.2, res=90,
                        detail=(0.12, 55.0, 0.15, 0)))
    net = _network(shift(y_l, 0.006), 0.26, 0.042, 0.0090, seed=17, voxel=0.0078)
    parts.append(sdf_part(net, "Myenteric (Auerbach) plexus", "Nerves & vessels", "#f0cf45",
                          STOMACH_TEXT["myenteric"], "nerve", smooth=0.7, rank=-2.5, detail=(0.05, 150.0, 0.6, 0)))
    parts.append(hlayer("Submucosa (rugal core)", "Submucosa", "#f0d6c6", y_o1, y_sub, STOMACH_TEXT["sub"], "fascia",
                        XR, ZR, bulk=True, rank=-1, res=130, detail=(0.14, 55.0, 0.15, 0)))
    parts.append(hlayer("Muscularis mucosae", "Mucosa", "#b95a50", y_sub, y_mm, STOMACH_TEXT["mm"], "muscle", XR, ZR,
                        rank=0, res=130, detail=(0.08, 90.0, 0.4, 1)))
    meis = _network(shift(y_sub, -0.024), 0.24, 0.024, 0.0060, seed=19, voxel=0.0064, thickness=0.02)
    parts.append(sdf_part(meis, "Submucosal (Meissner) plexus", "Nerves & vessels", "#e8c43c",
                          STOMACH_TEXT["meissner"], "nerve", smooth=0.7, rank=-1, detail=(0.05, 150.0, 0.6, 0)))
    art, vein = _vessel_pairs(lambda X, Z: at_many(y_sub, X, Z) - 0.058, (-0.42, 0.02, 0.36), 30)
    lym = Mesh()
    for j, z in enumerate((-0.2, 0.2, 0.5)):
        path = wavy_path((X0, 0, z), (X1, 0, z - 0.04), 70, 0.02, 1.2, seed=50 + j)
        path[:, 1] = at_many(y_sub, path[:, 0], path[:, 2]) - 0.035
        lym.extend(tube(path, 0.011, 12, ry=0.007))
    for pos, _, _ in lym.parts:
        np.clip(pos[:, 0], X0 - 0.002, X1 + 0.002, out=pos[:, 0])
    parts += [mesh_part(art, "Submucosal arteries", "Nerves & vessels", "#cf3a31", STOMACH_TEXT["artery"], "artery",
                        rank=-1),
              mesh_part(vein, "Submucosal veins", "Nerves & vessels", "#3d5bc2", STOMACH_TEXT["vein"], "vein", rank=-1),
              mesh_part(lym, "Lymphatic vessels", "Nerves & vessels", "#b8dcc0", STOMACH_TEXT["lymph"], "lymph",
                        rank=-1, detail=(0.04, 0.0, 0.0, 0))]

    # ------------------------------------------------------------------ mucosa: pits and oxyntic glands
    # The mucosa is one solid carrying the surface and its pits; lamina propria and glands are modelled inside it
    # only where a side of the block or the cut-away can show them (see _exposure), so the triangle budget goes on
    # what is seen.
    vox = 0.0072
    band = 0.095
    y_lo = float(min(at(y_mm, 0, z) for z in np.linspace(Z0, Z1, 40))) - 0.01
    y_hi = float(max(at(y_s, x, z) for x in (-1, 0, 1) for z in np.linspace(Z0, Z1, 60))) + 0.03
    tissue = Volume((X0, y_lo, Z0), (X1, y_hi, Z1), vox)
    x, y, z = tissue.axes()
    surf = y_s(x, z).astype(np.float32)
    tissue.d = np.broadcast_to((y - surf).astype(np.float32), tissue.shape).copy()
    pits = _lattice(0.090, 0.28, seed=77)
    # a row of pits just inside each side of the block, branching parallel to it, so the sides show glands in section
    edge = [(x_, z_) for z_ in (Z0 + 0.012, Z1 - 0.012) for x_ in np.arange(X0 + 0.045, X1 - 0.03, 0.09)]
    edge += [(x_, z_) for x_ in (X0 + 0.012, X1 - 0.012) for z_ in np.arange(Z0 + 0.10, Z1 - 0.08, 0.09)]
    pits = np.vstack([pits[cKDTree(np.array(edge)).query(pits)[0] > 0.06], edge])
    pit_depth = 0.085
    pit_shapes, gland_shapes, cell_shapes, ee_shapes = [], [], [], []
    for px, pz in pits:
        top = at(y_s, px, pz)
        bottom = top - pit_depth * rng.uniform(0.9, 1.1)
        pw = rng.uniform(0.85, 1.15)
        if float(_exposure(px, pz)) > band:
            # no face shows this pit's depths, so it is only as deep as the eye can see into it from above
            pit_shapes.append(round_cone((px, top - 0.05, pz), (px, top + 0.03, pz), 0.012 * pw, 0.021 * pw))
            continue
        pit_shapes.append(round_cone((px, bottom, pz), (px, top + 0.03, pz), 0.012 * pw, 0.021 * pw))
        base_y = at(y_mm, px, pz) + 0.022
        a = rng.uniform(0, math.pi)
        if abs(px) < 0.03 or abs(px) > X1 - 0.02:
            a = math.pi / 2                         # glands on a cut plane or a side branch within it
        elif abs(pz) < 0.03 or abs(pz) > Z1 - 0.02:
            a = 0.0
        for g, side in enumerate((-1, 1)):
            spread = np.array([math.cos(a), 0.0, math.sin(a)]) * 0.021 * side
            p0 = np.array([px, bottom + 0.012, pz])
            p1 = p0 + spread * 0.9 + np.array([0.0, -(bottom - base_y) * 0.30, 0.0])
            p2 = np.array([px, base_y + 0.035, pz]) + spread
            p3 = p2 + np.array([rng.uniform(-0.012, 0.012), -0.030, rng.uniform(-0.012, 0.012)])
            if abs(px) < 0.03 or abs(pz) < 0.03 or abs(px) > X1 - 0.02 or abs(pz) > Z1 - 0.02:
                p3 = p2 + spread * 0.4 + np.array([0.0, -0.030, 0.0])
            gland_shapes += [round_cone(p0, p1, 0.0140, 0.0150), round_cone(p1, p2, 0.0150, 0.0160),
                             round_cone(p2, p3, 0.0160, 0.0165)]
            path = smooth_path(np.array([p0, p1, p2, p3]), 40)
            along = lambda u: path[int(np.clip(u, 0, 1) * 39)]
            # parietal cells crowd the neck and upper body and thin out towards the base; enteroendocrine cells
            # sit low in the gland
            for u in rng.beta(1.5, 2.2, 7):
                ang = rng.uniform(0, 2 * math.pi)
                off = np.array([math.cos(ang), 0.0, math.sin(ang)]) * 0.0140
                cell_shapes.append(ellipsoid(along(u) + off, (0.0120, 0.0140, 0.0120)))
            if rng.random() < 0.7:
                ang = rng.uniform(0, 2 * math.pi)
                off = np.array([math.cos(ang), 0.0, math.sin(ang)]) * 0.0140
                ee_shapes.append(ellipsoid(along(rng.uniform(0.55, 0.97)) + off, (0.0060, 0.0085, 0.0060)))
    tissue.add_all(pit_shapes, "smooth_subtract", 0.010)
    tissue.displace(0.0018, 30.0, 2, seed=5)
    floor = at_many(y_mm, x, z).astype(np.float32)
    # where lamina propria and glands are modelled the surface solid stops under the pits, so a cut through it
    # meets each tissue in turn instead of looking into one tissue nested in another
    shown = (_exposure(x, z) < band + 0.03)
    pit_floor = (surf - pit_depth * 1.1 - 0.004).astype(np.float32)
    mucosa = tissue.copy(np.maximum(tissue.d, np.where(shown, pit_floor - y, floor + 0.001 - y)))
    mucosa.intersect_box((X0, 0, Z0), (X1, 2, Z1))

    # glands, cells and lamina propria stand a hair proud of the block's sides so they cap cleanly there
    lo, hi = (X0 - 0.003, y_lo, Z0 - 0.003), (X1 + 0.003, float(np.max(surf)) - 0.05, Z1 + 0.003)
    glands, parietal, ee = Volume(lo, hi, 0.0060), Volume(lo, hi, 0.0060), Volume(lo, hi, 0.0042)
    glands.add_all(gland_shapes, "smooth", 0.006)
    glands.displace(0.0016, 45.0, 2, seed=6)
    parietal.add_all(cell_shapes, "union")
    ee.add_all(ee_shapes, "union")
    for v in (glands, parietal, ee):
        vx, vy, vz = v.axes()
        v.d = np.maximum(v.d, at_many(y_mm, vx, vz).astype(np.float32) + 0.002 - vy)
    gx, gy, gz = glands.axes()
    g_floor = at_many(y_mm, gx, gz).astype(np.float32)
    g_pit = (y_s(gx, gz) - pit_depth * 1.1 - 0.004).astype(np.float32)
    parietal.d = np.maximum(parietal.d, gy - g_pit + 0.012)
    lp = glands.copy(np.maximum(np.maximum(g_floor + 0.002 - gy, gy - g_pit - 0.001),
                                -np.minimum(glands.d, parietal.d)))
    lp.d = np.maximum(lp.d, _exposure(gx, gz).astype(np.float32) - band - 0.03)
    base_zone = (g_floor + 0.105).astype(np.float32)
    chief = glands.copy(np.maximum(glands.d, gy - base_zone))
    neck = glands.copy(np.maximum(glands.d, base_zone - gy))
    for v in (chief, neck, parietal, ee, lp):
        v.intersect_box((X0 - 0.002, 0, Z0 - 0.002), (X1 + 0.002, 2, Z1 + 0.002))
    parts += [
        mesh_part(_drop_floor(mucosa.mesh(0.9), y_mm), "Surface mucous cells & gastric pits", "Mucosa", "#eec3c5",
                  STOMACH_TEXT["surface"], "mucosa", rank=2, detail=(0.10, 150.0, 0.85, 2)),
        sdf_part(neck, "Isthmus & neck (mucous neck cells)", "Gastric glands", "#e3c9d6", STOMACH_TEXT["neck"],
                 "gland", rank=1.5, detail=(0.10, 150.0, 0.85, 0)),
        sdf_part(parietal, "Parietal (oxyntic) cells", "Gastric glands", "#f27f8c", STOMACH_TEXT["parietal"], "gland",
                 rank=1.6, detail=(0.06, 110.0, 0.95, 0)),
        sdf_part(chief, "Chief (zymogen) cells – gland base", "Gastric glands", "#8a72c2", STOMACH_TEXT["chief"],
                 "gland", rank=1.2, detail=(0.10, 170.0, 0.95, 0)),
        sdf_part(ee, "Enteroendocrine (ECL) cells", "Gastric glands", "#e8b04a", STOMACH_TEXT["ee"], "gland",
                 smooth=0.6, rank=1.7, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_drop_floor(lp.mesh(0.9, step=2), y_mm), "Lamina propria", "Mucosa", "#f1c9b9", STOMACH_TEXT["lp"],
                  "mucosa", bulk=True, rank=1, detail=(0.12, 120.0, 0.5, 0)),
    ]
    return settle(parts, seed=301, amp_xz=0.030, amp_y=0.060, freq=1.4, grain=0.005)


def at_many(f, X, Z):
    return np.asarray(f(np.asarray(X, float), np.asarray(Z, float)), float)


def _gland_lobule(c, size, rng, branches=6, per=7, scale=(1.0, 0.45, 1.0), demilunes=0.0):
    """A lobule of a compound tubuloacinar gland: intralobular ducts branching from the centre, each ending in a
    bunch of acini (and, for a mixed gland, serous demilunes capping some of them). Returns (acinus and duct
    shapes, demilune shapes). `scale` squashes the lobule, e.g. flat into a cut plane or a thin submucosa."""
    c = np.asarray(c, float)
    sc = np.asarray(scale, float)
    body, caps = [], []
    for b in range(branches):
        d = rng.normal(size=3) * sc
        d /= max(np.linalg.norm(d), 1e-6)
        tip = c + d * size * rng.uniform(0.45, 0.8)
        body.append(capsule(c, tip, size * 0.085))
        for k in range(per):
            o = rng.normal(size=3) * size * 0.26 * sc
            r = size * rng.uniform(0.15, 0.20)
            p = tip + o
            body.append(ellipsoid(p, (r, r * rng.uniform(0.8, 1.0), r)))
            if rng.random() < demilunes:
                u = o / max(np.linalg.norm(o), 1e-6)
                caps.append(ellipsoid(p + u * r * 0.85, (r * 0.62, r * 0.5, r * 0.62)))
    return body, caps


# ==================================================================================================== oesophagus
OES_TEXT = {
    "superficial": "Superficial layer: flattened squamous cells that keep their nuclei – the epithelium is "
                   "non-keratinised, so the surface stays moist and pliable and is lubricated by gland mucus. Cells "
                   "are shed into the lumen and replaced from below in about a week.",
    "intermediate": "Intermediate (prickle) layers: many rows of polyhedral cells joined by desmosomes (the "
                    "'prickles' of H&E), flattening as they rise. Glycogen makes many of them pale – the basis of "
                    "the Lugol iodine stain at endoscopy, which spares dysplastic areas.",
    "basal": "Basal cell layer: one to three rows of small, dark, cuboidal cells on the basement membrane that "
             "divide to renew the epithelium. Basal cell hyperplasia (more than 15% of the thickness) is an early "
             "sign of reflux oesophagitis.",
    "papillae": "Lamina propria and papillae: loose connective tissue that rises into the epithelium as conical "
                "papillae, each with a capillary loop. Normally they reach less than about half to two-thirds of "
                "the epithelial thickness; elongation beyond that is a sign of reflux. Near the stomach it holds the "
                "oesophageal cardiac glands.",
    "loops": "Papillary capillary loops: hairpin capillaries in each papilla that nourish the avascular epithelium; "
             "magnifying endoscopy grades early squamous cancer by how these loops dilate and twist.",
    "mm": "Muscularis mucosae: unusually thick in the oesophagus, a sheet of longitudinal smooth muscle "
          "separating mucosa from submucosa. Cancer that has not breached it rarely spreads to lymph nodes.",
    "sub": "Submucosa: dense irregular connective tissue that, with the mucosa, throws the collapsed lumen into "
           "longitudinal folds that flatten as a bolus passes. It carries the glands, the venous plexus, "
           "lymphatics and the submucosal plexus.",
    "glands": "Oesophageal glands proper: small compound tubuloacinar glands, mostly mucous with some serous cells, "
              "scattered through the submucosa; their mucus lubricates the bolus and their bicarbonate helps clear "
              "refluxed acid.",
    "ducts": "Gland ducts: dilated as they leave the gland, lined by stratified epithelium, they cross the "
             "muscularis mucosae and lamina propria and open on the surface between the squamous cells.",
    "veins": "Submucosal venous plexus: a portosystemic anastomosis – the lower oesophageal veins drain both to the "
             "left gastric (portal) and to the azygos (systemic) veins. In portal hypertension they dilate into "
             "oesophageal varices, whose rupture causes massive haematemesis.",
    "artery": "Submucosal arteries: branches of the inferior thyroid artery, the thoracic aorta and the left gastric "
              "artery according to the level, feeding the submucosal and mucosal plexuses.",
    "lymph": "Lymphatics: a dense longitudinal network in the lamina propria and submucosa that lets carcinoma spread "
             "far along the wall (skip lesions) before it reaches the nodes.",
    "meissner": "Submucosal (Meissner) plexus: sparse in the oesophagus; ganglia regulating gland secretion and "
                "blood flow.",
    "long_sk": "Outer longitudinal muscle – skeletal fascicles. In the upper third the muscularis externa is striated "
               "muscle continuous with the pharynx (the upper sphincter is the cricopharyngeus). Its motor nerves "
               "are vagal branchiomotor fibres from the nucleus ambiguus ending on motor end plates; myasthenia "
               "gravis and polymyositis cause dysphagia here.",
    "long_sm": "Outer longitudinal muscle – smooth muscle bundles. In the lower third the layer is entirely smooth "
               "muscle driven by the myenteric plexus (vagal preganglionic fibres from the dorsal motor nucleus). "
               "The middle third is a mixture, as in this model. Systemic sclerosis weakens this part.",
    "circ_sk": "Inner circular muscle – skeletal fascicles of the upper third. The circular layer drives the "
               "peristaltic wave that follows each swallow.",
    "circ_sm": "Inner circular muscle – smooth muscle of the lower third; at the lower end it forms the tonically "
               "contracted lower oesophageal sphincter, which fails to relax in achalasia.",
    "septa": "Connective tissue septa between the muscle bundles and fascicles, carrying vessels and nerve fibres.",
    "myenteric": "Myenteric (Auerbach) plexus: ganglia between the circular and longitudinal layers. Present along "
                 "the whole oesophagus but controls only the smooth-muscle part; its inhibitory (NO, VIP) neurons "
                 "are lost in achalasia and destroyed by Trypanosoma cruzi in Chagas disease.",
    "adventitia": "Adventitia: loose connective tissue binding the thoracic oesophagus to the trachea, aorta and "
                  "pericardium – there is no serosa above the diaphragm, so carcinoma spreads outwards early and "
                  "anastomoses leak more easily.",
    "vagus": "Oesophageal (vagal) plexus: branches of the left and right vagus nerves on the oesophagus, which "
             "regroup as the anterior and posterior vagal trunks to pass through the diaphragm.",
    "adv_vessels": "Adventitial vessels: segmental oesophageal branches entering the wall and the veins draining to "
                   "the azygos system.",
}


def _hslab(x, z, top, bottom, res_top, res_bot, gap=0.0015):
    """Closed solid between two height fields sampled at different resolutions (papillae or a cell mosaic on one
    side, a smooth interface on the other). The side walls follow the finer of the two edges."""
    top, bottom = fn(top), fn(bottom)

    def grid(res):
        span = max(x[1] - x[0], z[1] - z[0])
        nx = max(2, int(res * (x[1] - x[0]) / span) + 1)
        nz = max(2, int(res * (z[1] - z[0]) / span) + 1)
        return np.meshgrid(np.linspace(x[0], x[1], nx), np.linspace(z[0], z[1], nz), indexing="ij")

    from .geometry import _grid_indices
    m = Mesh()
    Xt, Zt = grid(res_top)
    T = top(Xt, Zt) * np.ones_like(Xt) - gap
    m.add(np.stack([Xt, T, Zt], -1).reshape(-1, 3), _grid_indices(*Xt.shape, flip=True))
    Xb, Zb = grid(res_bot)
    B = np.minimum(bottom(Xb, Zb) * np.ones_like(Xb) + gap, top(Xb, Zb) - 1e-4)
    m.add(np.stack([Xb, B, Zb], -1).reshape(-1, 3), _grid_indices(*Xb.shape, flip=False))
    X, Z = grid(max(res_top, res_bot))
    for ex, ez, flip in ((X[:, 0], Z[:, 0], True), (X[:, -1], Z[:, -1], False), (X[0, :], Z[0, :], False),
                         (X[-1, :], Z[-1, :], True)):
        et = top(ex, ez) * np.ones_like(ex) - gap
        eb = np.minimum(bottom(ex, ez) * np.ones_like(ex) + gap, et - 1e-4)
        n = len(ex)
        p = np.concatenate([np.stack([ex, eb, ez], -1), np.stack([ex, et, ez], -1)])
        a = np.arange(n)
        tri = np.concatenate([np.stack([a[:-1], a[1:], a[1:] + n], 1), np.stack([a[:-1], a[1:] + n, a[:-1] + n], 1)])
        m.add(p, tri[:, ::-1] if flip else tri)
    return m


def build_oesophagus():
    parts = []
    rng = np.random.default_rng(21)
    folds = lambda X, Z: 0.055 * np.maximum(np.sin(np.asarray(Z) * 7.5 + 0.4 + 0.15 * np.sin(np.asarray(X) * 2.0)),
                                            0) ** 2
    y_adv = add(0.050, noise2(0.004, 3.0, seed=2))
    y_l = add(0.160, noise2(0.004, 3.0, seed=3))
    y_c0, y_c1 = shift(y_l, 0.012), add(0.330, noise2(0.004, 3.0, seed=4))
    y_sub = add(0.51, folds, noise2(0.006, 3.0, seed=5))
    y_mm = shift(y_sub, 0.040)
    dej0 = shift(y_mm, 0.035)
    pap_pts = poisson_disk((X0 - 0.05, Z0 - 0.05), (X1 + 0.05, Z1 + 0.05), 0.085, seed=4)
    # rows of papillae on the sides and the cut planes, so every section shows them standing up
    rows_ = [(x_, z_) for z_ in (Z0 + 0.004, Z1 - 0.004, 0.0) for x_ in np.arange(X0 + 0.03, X1, 0.085)
             if z_ != 0.0 or x_ < 0.02]
    rows_ += [(x_, z_) for x_ in (X0 + 0.004, X1 - 0.004, 0.0) for z_ in np.arange(Z0 + 0.03, Z1, 0.085)
              if x_ != 0.0 or z_ > -0.02]
    pap_pts = np.vstack([pap_pts[cKDTree(np.array(rows_)).query(pap_pts)[0] > 0.055], rows_])
    pap_h = rng.uniform(0.08, 0.125, len(pap_pts))
    papillae = Bumps(pap_pts, 0.044, 1.0, k=3, sharp=1.25)
    pap_amp = lambda X, Z: _nearest_value(pap_pts, pap_h, X, Z)
    dej = add(dej0, lambda X, Z: papillae(X, Z) * pap_amp(X, Z), noise2(0.004, 10.0, seed=6))
    squames = Grooves(poisson_disk((X0 - 0.1, Z0 - 0.1), (X1 + 0.1, Z1 + 0.1), 0.06, seed=8), 0.011, 0.006)
    surface = add(dej0, 0.27, squames, noise2(0.004, 8.0, seed=9))
    y_basal = shift(dej, 0.022)
    y_sup = shift(surface, -0.040)

    parts.append(hlayer("Adventitia", "Wall layers", "#e5d3b0", 0.0, y_adv, OES_TEXT["adventitia"], "fascia", XR, ZR,
                        bulk=True, rank=-4, res=110, detail=(0.14, 50.0, 0.15, 0)))
    # muscularis externa: skeletal fascicles towards +x (upper third), smooth bundles towards -x (lower third),
    # interleaved across the middle of the block as in the middle third of the oesophagus
    border = lambda PX, PZ: 0.22 * np.sin(PZ * 5.0 + 1.0) + 0.09 * np.sin(PZ * 13.0 + 0.3 * PX)
    for k, (name, bottom, top, angle, rows, text) in enumerate((("Outer longitudinal", y_adv, y_l, 0, 2, "long"),
                                                                 ("Inner circular", y_c0, y_c1, 90, 3, "circ"))):
        # skeletal fascicles are larger and packed tighter than the smooth muscle bundles
        sk = _bundles(fn(bottom), fn(top), angle, 0.100, rows, seed=190 + k, fill=0.64, segments=14,
                      mask=lambda PX, PZ, i: PX > border(PX, PZ))
        sm = _bundles(fn(bottom), fn(top), angle, 0.076, rows + 1, seed=195 + k, fill=0.64, segments=10,
                      mask=lambda PX, PZ, i: PX <= border(PX, PZ) - 0.015)
        parts += [mesh_part(sk, f"{name} muscle – skeletal (upper third)", "Muscularis externa", "#a8413b",
                            OES_TEXT[text + "_sk"], "muscle", rank=-3, detail=(0.07, 120.0, 0.45, 1 if angle == 0 else 3)),
                  mesh_part(sm, f"{name} muscle – smooth (lower third)", "Muscularis externa", "#c9675c",
                            OES_TEXT[text + "_sm"], "muscle", rank=-3, detail=(0.08, 80.0, 0.4, 1 if angle == 0 else 3))]
    parts.append(hlayer("Intermuscular connective tissue", "Muscularis externa", "#d9b4a3", y_adv, y_c1,
                        OES_TEXT["septa"], "fascia", XR, ZR, bulk=True, rank=-3.2, res=90,
                        detail=(0.12, 55.0, 0.15, 0)))
    net = _network(shift(y_l, 0.006), 0.26, 0.040, 0.0085, seed=23, voxel=0.0078)
    parts.append(sdf_part(net, "Myenteric (Auerbach) plexus", "Nerves & vessels", "#f0cf45", OES_TEXT["myenteric"],
                          "nerve", smooth=0.7, rank=-2.5, detail=(0.05, 150.0, 0.6, 0)))

    parts += [
        hlayer("Submucosa", "Submucosa", "#f0d6c6", y_c1, y_sub, OES_TEXT["sub"], "fascia", XR, ZR, bulk=True, rank=-1,
               res=130, detail=(0.14, 55.0, 0.15, 0)),
        hlayer("Muscularis mucosae", "Mucosa", "#b95a50", y_sub, y_mm, OES_TEXT["mm"], "muscle", XR, ZR, rank=0,
               res=130, detail=(0.08, 90.0, 0.4, 1)),
        mesh_part(_hslab(XR, ZR, dej, y_mm, 230, 90), "Lamina propria & papillae", "Mucosa", "#efbfb2",
                  OES_TEXT["papillae"], "mucosa", bulk=True, rank=1, detail=(0.12, 100.0, 0.35, 0)),
        hlayer("Basal cell layer", "Stratified squamous epithelium", "#8e5378", dej, y_basal, OES_TEXT["basal"],
               "mucosa", XR, ZR, rank=2, res=230, detail=(0.10, 190.0, 0.95, 0)),
        mesh_part(_hslab(XR, ZR, y_sup, lambda X, Z: np.minimum(y_basal(X, Z), y_sup(X, Z) - 0.01), 110, 230),
                  "Intermediate (prickle) layers", "Stratified squamous epithelium", "#e7b9b9",
                  OES_TEXT["intermediate"], "mucosa", rank=3, detail=(0.10, 120.0, 0.8, 0)),
        mesh_part(_hslab(XR, ZR, surface, y_sup, 250, 90), "Superficial squamous layer",
                  "Stratified squamous epithelium", "#ecccc8", OES_TEXT["superficial"], "mucosa", rank=4,
                  detail=(0.08, 140.0, 0.6, 0)),
    ]

    # papillary capillary loops where a face or the cut-away sections the papillae
    loops = Mesh()
    for (px, pz), h in zip(pap_pts, pap_h):
        on_x = min(abs(px - X0), abs(px - X1), abs(px) if pz > -0.03 else 9) < 0.03
        on_z = min(abs(pz - Z0), abs(pz - Z1), abs(pz) if px < 0.03 else 9) < 0.03
        if not (on_x or on_z) or not (X0 < px < X1 and Z0 < pz < Z1):
            continue
        d = np.array([0.0, 0.0, 1.0]) if on_x else np.array([1.0, 0.0, 0.0])
        base = np.array([px, at(y_mm, px, pz) + 0.012, pz])
        tip = np.array([px, at(dej, px, pz) - 0.010, pz])
        t = np.linspace(0, 1, 18)
        up = base[None] + (tip - base)[None] * t[:, None] - d[None] * 0.0075 * (1 - t[:, None] ** 3)
        down = up[::-1] + d[None] * 0.0150 * (1 - t[::-1, None] ** 3)
        loops.extend(tube(smooth_path(np.vstack([up, down[1:]]), 40), 0.0038, 8))
    for pos, _, _ in loops.parts:
        np.clip(pos[:, 0], X0 - 0.002, X1 + 0.002, out=pos[:, 0])
        np.clip(pos[:, 2], Z0 - 0.002, Z1 + 0.002, out=pos[:, 2])
    parts.append(mesh_part(loops, "Papillary capillary loops", "Mucosa", "#d23b36", OES_TEXT["loops"], "artery",
                           rank=1.2))

    # ------------------------------------------------------------------ submucosal glands, ducts and vessels
    lo, hi = (X0 - 0.003, 0.29, Z0 - 0.003), (X1 + 0.003, 0.62, Z1 + 0.003)
    glands = Volume(lo, hi, 0.0042)
    ducts = Mesh()
    sites = [(0.02, 0.30), (-0.5, 0.0), (0.55, -0.57), (0.97, 0.12), (-0.97, -0.32), (0.4, 0.22), (-0.35, -0.4),
             (-0.6, 0.35)]
    duct_tops = []
    for i, (gx, gz) in enumerate(sites):
        c = np.array([gx, at(y_sub, gx, gz) - 0.06, gz])            # glands high in the submucosa, vessels deep
        spread = np.array([0.055, 0.024, 0.055])
        if abs(gx) < 0.05 or abs(gx) > 0.9:
            spread[0] = 0.028                       # lobules on a cut plane or a side lie in it
        if abs(gz) < 0.05 or abs(gz) > 0.5:
            spread[2] = 0.028
        acini, _ = _gland_lobule(c, 0.11, rng, branches=8, per=8, scale=spread / 0.055)
        glands.add_all(acini, "smooth", 0.006)
        tx, tz = gx + rng.uniform(-0.04, 0.04), gz + rng.uniform(-0.03, 0.03)
        if abs(gx) < 0.05 or abs(gx) > 0.9:
            tx = gx
        if abs(gz) < 0.05 or abs(gz) > 0.5:
            tz = gz
        duct_tops.append((tx, tz))
        path = np.array([c + np.array([0.0, 0.02, 0.0]), [(gx + tx) / 2, at(y_sub, gx, gz) - 0.03, (gz + tz) / 2],
                         [tx, at(y_mm, tx, tz) + 0.01, tz], [tx, at(dej0, tx, tz) + 0.15, tz],
                         [tx, at(surface, tx, tz) - 0.002, tz]])
        sm = smooth_path(path, 40)
        r = np.interp(np.linspace(0, 1, len(sm)), [0, 0.2, 0.35, 0.55, 1.0], [0.012, 0.019, 0.013, 0.009, 0.008])
        ducts.extend(tube(sm, r, 12))
    glands.displace(0.0016, 50.0, 2, seed=12)
    glands.intersect_box((X0 - 0.002, 0, Z0 - 0.002), (X1 + 0.002, 2, Z1 + 0.002))
    for pos, _, _ in ducts.parts:
        np.clip(pos[:, 0], X0 - 0.003, X1 + 0.003, out=pos[:, 0])
        np.clip(pos[:, 2], Z0 - 0.003, Z1 + 0.003, out=pos[:, 2])
    parts.append(sdf_part(glands, "Oesophageal glands proper", "Submucosa", "#aebbd9", OES_TEXT["glands"], "gland",
                          rank=-0.8, detail=(0.08, 140.0, 0.7, 0)))
    parts.append(mesh_part(ducts, "Gland ducts", "Submucosa", "#b59ad0", OES_TEXT["ducts"], "gland", rank=1,
                           detail=(0.06, 120.0, 0.6, 0)))

    y_veins = lambda X, Z: at_many(y_c1, X, Z) + 0.036
    veins, arts = Mesh(), Mesh()
    zs = np.linspace(Z0 + 0.08, Z1 - 0.08, 7)
    vpaths = []
    for j, z0 in enumerate(zs):
        path = wavy_path((X0 - 0.01, 0, z0), (X1 + 0.01, 0, z0 + rng.uniform(-0.05, 0.05)), 80, 0.035, 2.2,
                         seed=60 + j)
        path[:, 1] = y_veins(path[:, 0], path[:, 2]) + 0.006 * np.sin(path[:, 0] * 9 + j)
        vpaths.append(path)
        veins.extend(tube(path, rng.uniform(0.016, 0.022), 16))
    for j in range(len(vpaths) - 1):                                # anastomoses between neighbouring veins
        for xi in rng.choice(np.arange(8, 72), 3, replace=False):
            a, b = vpaths[j][xi], vpaths[j + 1][xi + rng.integers(-4, 5)]
            mid = (a + b) / 2 + np.array([rng.uniform(-0.03, 0.03), 0.004, 0.0])
            veins.extend(tube(smooth_path(np.array([a, mid, b]), 12), 0.010, 10))
    for j, z0 in enumerate((zs[:-1] + zs[1:]) / 2):
        path = wavy_path((X0 - 0.01, 0, z0), (X1 + 0.01, 0, z0 + 0.03), 70, 0.02, 1.4, seed=80 + j)
        path[:, 1] = y_veins(path[:, 0], path[:, 2]) - 0.006
        arts.extend(tube(path, 0.009, 12))
    lym = Mesh()
    for j, z0 in enumerate((-0.45, -0.05, 0.4)):
        path = wavy_path((X0 - 0.01, 0, z0), (X1 + 0.01, 0, z0 - 0.04), 70, 0.02, 1.2, seed=90 + j)
        path[:, 1] = y_veins(path[:, 0], path[:, 2]) + 0.03
        lym.extend(tube(path, 0.011, 12, ry=0.007))
    for m in (veins, arts, lym):
        for pos, _, _ in m.parts:
            np.clip(pos[:, 0], X0 - 0.002, X1 + 0.002, out=pos[:, 0])
    meis = _network(shift(y_sub, -0.024), 0.32, 0.022, 0.0055, seed=29, voxel=0.0064, thickness=0.02)
    parts += [
        mesh_part(veins, "Submucosal venous plexus", "Submucosa", "#3d5bc2", OES_TEXT["veins"], "vein", rank=-1),
        mesh_part(arts, "Submucosal arteries", "Submucosa", "#cf3a31", OES_TEXT["artery"], "artery", rank=-1),
        mesh_part(lym, "Lymphatic vessels", "Submucosa", "#b8dcc0", OES_TEXT["lymph"], "lymph", rank=-1,
                  detail=(0.04, 0.0, 0.0, 0)),
        sdf_part(meis, "Submucosal (Meissner) plexus", "Nerves & vessels", "#e8c43c", OES_TEXT["meissner"], "nerve",
                 smooth=0.7, rank=-1, detail=(0.05, 150.0, 0.6, 0)),
    ]

    # adventitia: the vagal plexus and segmental vessels
    vag, aa, av = Mesh(), Mesh(), Mesh()
    for j, z0 in enumerate((-0.32, 0.28)):
        path = wavy_path((X0 - 0.01, 0.028, z0), (X1 + 0.01, 0.028, z0 + 0.06), 60, 0.03, 1.1, seed=100 + j)
        vag.extend(tube(path, 0.017, 16))
    for j, z0 in enumerate((-0.05, 0.47)):
        path = wavy_path((X0 - 0.01, 0.026, z0), (X1 + 0.01, 0.024, z0 - 0.05), 60, 0.02, 1.6, seed=110 + j)
        aa.extend(tube(path, 0.010, 12))
        v = path.copy()
        v[:, 2] += 0.035
        av.extend(tube(v, 0.014, 12))
    for m in (vag, aa, av):
        for pos, _, _ in m.parts:
            np.clip(pos[:, 0], X0 - 0.002, X1 + 0.002, out=pos[:, 0])
    parts += [
        mesh_part(vag, "Oesophageal (vagal) plexus", "Wall layers", "#f0cf45", OES_TEXT["vagus"], "nerve", rank=-4.2,
                  detail=(0.06, 60.0, 0.3, 1)),
        mesh_part(aa, "Adventitial arteries", "Wall layers", "#cf3a31", OES_TEXT["adv_vessels"], "artery", rank=-4.2),
        mesh_part(av, "Adventitial veins", "Wall layers", "#3d5bc2", OES_TEXT["adv_vessels"], "vein", rank=-4.2),
    ]
    return settle(parts, seed=302, amp_xz=0.030, amp_y=0.060, freq=1.5, grain=0.005)


def _nearest_value(pts, vals, X, Z):
    X, Z = np.broadcast_arrays(np.asarray(X, float), np.asarray(Z, float))
    _, i = cKDTree(pts).query(np.stack([X.ravel(), Z.ravel()], -1))
    return vals[i].reshape(X.shape)



# ==================================================================================================== trachea
# The trachea is a short length of the whole airway rather than a block, so the C-shaped rings and the trachealis
# that closes them read as they do in a transverse section. Everything is modelled flat with the block tools -
# x along the airway (+x towards the larynx), y the height above the luminal surface (the epithelium is on top,
# deeper layers below zero) and z the distance round the lumen - and then wrapped round a D-shaped lumen. Mucosa
# and submucosa are drawn about six times too thick so that cells, cilia and glands stay legible.
TRACH_TEXT = {
    "cilia": "Cilia: each ciliated cell carries about 200–300 motile cilia, 6–7 µm long, with a 9+2 axoneme whose "
             "dynein arms bend it about 12–15 times a second. Neighbouring cells beat in metachronal waves, sweeping "
             "the mucus blanket up towards the larynx (the mucociliary escalator). Tobacco smoke paralyses them; "
             "in primary ciliary dyskinesia (Kartagener syndrome, with situs inversus) missing dynein arms cause "
             "bronchiectasis, sinusitis and infertility.",
    "epi": "Respiratory epithelium – pseudostratified ciliated columnar epithelium with goblet cells. Every cell "
           "rests on the basement membrane but only ciliated and goblet cells reach the lumen, so nuclei lie at "
           "different levels and the single layer looks stratified. Also contains brush cells and neuroendocrine "
           "(Kulchitsky) cells. Chronic irritation (smoking) converts it to stratified squamous epithelium "
           "(squamous metaplasia).",
    "nuclei": "Nuclei of the ciliated columnar cells: oval and lying in the upper-middle part of the epithelium, above "
              "the row of basal-cell nuclei – two tiers of nuclei in one layer of cells are what make the "
              "epithelium 'pseudo'-stratified.",
    "basal": "Basal cells: small triangular stem cells sitting on the basement membrane without reaching the lumen. "
             "They renew the ciliated and goblet cells and anchor the epithelium by hemidesmosomes.",
    "goblet": "Goblet cells: unciliated cells whose apical theca is packed with mucin (MUC5AC) granules, PAS-positive "
              "and pale in H&E. Roughly one for every five ciliated cells; their mucus gel traps inhaled particles "
              "and floats on a watery periciliary layer. They multiply in smokers, asthma and chronic bronchitis.",
    "bm": "Basement membrane: unusually thick in the trachea because of a dense subepithelial layer of type III/V "
          "collagen (the lamina reticularis). It thickens further in asthma (subepithelial fibrosis).",
    "lp": "Lamina propria: loose connective tissue rich in lymphocytes, IgA plasma cells, mast cells, capillaries and "
          "bronchus-associated lymphoid tissue.",
    "elastic": "Elastic fibres: a dense sheet of longitudinal elastic fibres in the deep lamina propria (the elastic "
               "membrane) marks the border with the submucosa. It lets the airway recoil after stretching and throws "
               "the posterior wall into longitudinal ridges.",
    "sub": "Submucosa: looser connective tissue holding the seromucous glands, larger blood vessels and lymphatics. "
           "It blends with the perichondrium of the rings below.",
    "mucous": "Mucous gland tubules: pale, foamy cells with flattened basal nuclei secreting mucin into the gland "
              "lumen. Tracheobronchial glands are most numerous in the posterior wall and between the rings. Their "
              "hypertrophy raises the Reid index (gland thickness ÷ wall thickness between epithelium and "
              "cartilage; normal < 0.4) in chronic bronchitis.",
    "serous": "Serous demilunes and acini: dark, granular cells capping the mucous tubules. They add the watery "
              "periciliary fluid with lysozyme, lactoferrin and secretory IgA; CFTR in these cells drives the fluid "
              "secretion that fails in cystic fibrosis.",
    "ducts": "Gland ducts: collect the secretion and cross the lamina propria to open through the epithelium at "
             "small pits on the luminal surface.",
    "artery": "Arterioles: tracheal branches of the inferior thyroid arteries run in the adventitia and send twigs "
              "through the anular ligaments to the submucosa, the glands and a dense subepithelial capillary plexus.",
    "vein": "Venules: drain to the inferior thyroid veins. The subepithelial venous plexus warms and humidifies the "
            "inspired air.",
    "rings": "Hyaline cartilage ring: one of 16–20 C-shaped rings that hold the airway open. The open ends face "
             "posteriorly towards the oesophagus and are bridged by the trachealis. Matrix of type II collagen and "
             "aggrecan; avascular, so nutrients diffuse in from the perichondrium. Rings calcify with age; weak rings "
             "cause tracheomalacia.",
    "perichondrium": "Perichondrium: an outer fibrous layer of dense connective tissue carrying the vessels, and an "
                     "inner chondrogenic layer whose cells lay down new cartilage on the surface (appositional "
                     "growth). Chondrocytes next to it are flattened parallel to the surface.",
    "territorial": "Territorial matrix: the darker, strongly basophilic capsule of sulphated proteoglycans around each "
                   "isogenous group – the paler interterritorial matrix lies between groups.",
    "lacunae": "Lacunae: the spaces in the matrix that hold the chondrocytes. In fixed sections the cells shrink "
               "away from the wall, leaving a clear halo.",
    "chondrocytes": "Chondrocytes: rounded cells in lacunae, often in isogenous groups of two to four – the daughters "
                    "of one cell trapped together by the matrix they secrete (interstitial growth). Near the "
                    "perichondrium they are single and flattened.",
    "trachealis": "Trachealis muscle: smooth muscle bundles running transversely across the posterior gap, inserted "
                  "into the perichondrium on the inner aspect of the free ends of the rings. Contraction narrows the "
                  "lumen and speeds the airflow in a cough; the gap lets a food bolus bulge forward from the "
                  "oesophagus.",
    "anular": "Anular ligaments: fibroelastic membranes joining successive rings and continuous with their "
              "perichondrium; posteriorly they form the fibroelastic membrane behind the trachealis. They let the "
              "trachea lengthen with breathing and neck extension.",
    "adventitia": "Adventitia: loose connective tissue binding the trachea to the oesophagus behind and the thyroid "
                  "and neck structures in front; carries the vessels, nerves and lymphatics.",
}


class _Lumen:
    """D-shaped tracheal lumen: an elliptical anterior arch and a flattened posterior (membranous) wall.

    Maps flat coordinates (x, height above the lumen, distance s round it) onto the tube. Since the curve is convex
    and the wall lies outside it, the map can never fold, however thick the wall."""

    def __init__(self, a_ant=0.40, a_post=0.27, b=0.44, n_post=3.4, seam=0.57, samples=6000):
        th = np.linspace(0.0, 2 * math.pi, 24000, endpoint=False) + seam * math.pi
        c, s = np.cos(th), np.sin(th)
        ant = c >= 0
        y = np.where(ant, a_ant * c, -a_post * np.abs(c) ** (2 / n_post))
        z = np.where(ant, b * s, b * np.sign(s) * np.abs(s) ** (2 / n_post))
        closed = np.vstack([np.stack([y, z], -1), [[y[0], z[0]]]])
        arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1))])
        self.P = float(arc[-1])
        self.n = samples
        u = np.linspace(0.0, self.P, samples, endpoint=False)
        self.c = np.stack([np.interp(u, arc, closed[:, 0]), np.interp(u, arc, closed[:, 1])], -1)
        t = np.roll(self.c, -1, 0) - np.roll(self.c, 1, 0)
        t /= np.linalg.norm(t, axis=1, keepdims=True)
        nrm = np.stack([t[:, 1], -t[:, 0]], -1)
        if float(np.mean(np.sum(nrm * self.c, axis=1))) < 0:
            nrm = -nrm
        self.nrm = nrm
        # the flat frame (x, height, s) goes to (x, -normal, tangent); a left-handed image flips every winding
        self.flip = float(np.mean(-(nrm[:, 0] * t[:, 1] - nrm[:, 1] * t[:, 0]))) < 0
        self.u = u

    def point(self, s):
        """(y, z) of the lumen and its outward normal at arc length s."""
        f = np.mod(np.asarray(s, np.float64), self.P) / self.P * self.n
        i0 = np.floor(f).astype(np.int64) % self.n
        i1 = (i0 + 1) % self.n
        w = (f - np.floor(f))[..., None]
        c = self.c[i0] * (1 - w) + self.c[i1] * w
        n = self.nrm[i0] * (1 - w) + self.nrm[i1] * w
        return c, n / np.linalg.norm(n, axis=-1, keepdims=True)

    def s_where(self, fn):
        return self.u[fn(self.c)]

    def wrap(self, mesh):
        out = Mesh()
        for pos, _, idx in mesh.parts:
            p = pos.astype(np.float64)
            c, n = self.point(p[:, 2])
            q = np.stack([p[:, 0], c[:, 0] - n[:, 0] * p[:, 1], c[:, 1] - n[:, 1] * p[:, 1]], -1).astype(np.float32)
            i = idx[:, ::-1].copy() if self.flip else idx
            out.parts.append((q, compute_normals(q, i), i))
        return out


def _periodic_noise(amp, freq, period, seed=0, octaves=3):
    """fbm of (x, s) that is periodic in s, so the surfaces close seamlessly round the lumen."""
    r = period / (2 * math.pi)

    def f(X, S):
        a = np.asarray(S, np.float32) * np.float32(2 * math.pi / period)
        return amp * fbm3(np.asarray(X, np.float32) * freq, np.cos(a) * r * freq, np.sin(a) * r * freq, 1.0, octaves,
                          seed)
    return f


def _band_mesh(s0, s1, xc, wx, hc, wh, tip=0.035, n_s=170, n_p=26, expo=2.6):
    """A closed band swept along s with a rounded-rectangle section (centre xc, hc; half sizes wx, wh - functions of
    s): a cartilage ring. Its tips are rounded off over `tip`."""
    s = np.linspace(s0, s1, n_s)
    d = np.minimum(s - s0, s1 - s)
    e = np.sqrt(np.clip(1.0 - np.clip(1.0 - d / tip, 0.0, 1.0) ** 2, 0.0, 1.0))
    a = np.linspace(0.0, 2 * math.pi, n_p, endpoint=False)
    cu = np.sign(np.cos(a)) * np.abs(np.cos(a)) ** (2 / expo)
    sv = np.sign(np.sin(a)) * np.abs(np.sin(a)) ** (2 / expo)
    X = xc(s)[:, None] + (wx(s) * e)[:, None] * cu[None]
    H = hc(s)[:, None] + (wh(s) * e)[:, None] * sv[None]
    S = np.broadcast_to(s[:, None], X.shape)
    pos = np.stack([X, H, S], -1).reshape(-1, 3)
    g = np.arange(n_s * n_p).reshape(n_s, n_p)
    q0, q1 = g[:-1], np.roll(g[:-1], -1, axis=1)
    q3, q2 = g[1:], np.roll(g[1:], -1, axis=1)
    tri = np.concatenate([np.stack([q0.ravel(), q1.ravel(), q2.ravel()], 1),
                          np.stack([q0.ravel(), q2.ravel(), q3.ravel()], 1)])
    from .cells import orient_outward
    return orient_outward(Mesh().add(pos, tri))


def _spikes(base, tip, r, seed=0):
    """Three-sided tapering spikes from base points to tip points (open at the base, which is buried)."""
    rng = np.random.default_rng(seed)
    n = len(base)
    a0 = rng.uniform(0, 2 * math.pi, n)
    pos = np.empty((n, 4, 3))
    for k in range(3):
        a = a0 + k * 2 * math.pi / 3
        pos[:, k] = base + np.stack([np.cos(a) * r, np.zeros(n), np.sin(a) * r], -1)
    pos[:, 3] = tip
    o = (np.arange(n) * 4)[:, None]
    idx = np.concatenate([np.stack([o[:, 0] + 1, o[:, 0], o[:, 0] + 3], 1),
                          np.stack([o[:, 0] + 2, o[:, 0] + 1, o[:, 0] + 3], 1),
                          np.stack([o[:, 0], o[:, 0] + 2, o[:, 0] + 3], 1)])
    return Mesh().add(pos.reshape(-1, 3), idx)


def _merged(mesh):
    """One vertex array per part: the finishing warp costs the same for one sub-mesh as for thousands."""
    if len(mesh.parts) < 2:
        return mesh
    pos, nrm, idx = mesh.arrays()
    return Mesh().add(pos, idx, nrm)


def _blobs(centres, radii, res=4, clamp=None):
    """Many small ellipsoids in one mesh. `clamp` flattens anything beyond |x| = clamp onto that plane, so cells
    that the end of the model cuts through show as flat profiles, like a section."""
    if not len(centres):
        return Mesh()
    unit, _, tri = ellipsoid_mesh((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), res=res).arrays()
    c = np.asarray(centres, np.float64)[:, None, :]
    r = np.asarray(radii, np.float64)[:, None, :]
    pos = (unit[None] * r + c).reshape(-1, 3)
    if clamp is not None:
        np.clip(pos[:, 0], -clamp, clamp, out=pos[:, 0])
    idx = (tri[None] + (np.arange(len(c)) * len(unit))[:, None, None]).reshape(-1, 3)
    return Mesh().add(pos, idx)


def _columns(base, top, radii, segments=5, seed=0):
    """Straight vertical tubes of revolution with a shared radius profile (goblet cells): `base` and `top` are the
    (x, y, z) ends, `radii` the profile from base to top, scaled per tube. Closed at both ends."""
    rng = np.random.default_rng(seed)
    n, k = len(base), len(radii)
    t = np.linspace(0.0, 1.0, k)
    a = rng.uniform(0, 2 * math.pi, n)[:, None] + np.linspace(0, 2 * math.pi, segments, endpoint=False)[None]
    scale = rng.uniform(0.9, 1.1, n)
    axis = base[:, None, :] + (top - base)[:, None, :] * t[None, :, None]              # (n, k, 3)
    rr = scale[:, None] * np.asarray(radii)[None]                                     # (n, k)
    ring = axis[:, :, None, :] + np.stack([np.cos(a)[:, None, :] * rr[:, :, None], np.zeros((n, k, segments)),
                                           np.sin(a)[:, None, :] * rr[:, :, None]], -1)  # (n, k, seg, 3)
    pos = np.concatenate([ring.reshape(n, k * segments, 3), axis[:, :1], axis[:, -1:]], 1)
    g = np.arange(k * segments).reshape(k, segments)
    q0, q1 = g[:-1], np.roll(g[:-1], -1, axis=1)
    q3, q2 = g[1:], np.roll(g[1:], -1, axis=1)
    tri = [np.stack([q0.ravel(), q2.ravel(), q1.ravel()], 1), np.stack([q0.ravel(), q3.ravel(), q2.ravel()], 1)]
    s0, s1 = k * segments, k * segments + 1
    ring0, ringk = g[0], g[-1]
    tri.append(np.stack([np.full(segments, s0), ring0, np.roll(ring0, -1)], 1))
    tri.append(np.stack([np.full(segments, s1), np.roll(ringk, -1), ringk], 1))
    tri = np.concatenate(tri)
    idx = (tri[None] + (np.arange(n) * pos.shape[1])[:, None, None]).reshape(-1, 3)
    from .cells import orient_outward
    return orient_outward(Mesh().add(pos.reshape(-1, 3), idx))


def build_trachea():
    rng = np.random.default_rng(31)
    lum = _Lumen()
    P = lum.P
    SR = (0.0, P)
    XE = (-1.0, 1.0)
    s_post = float(lum.s_where(lambda c: np.arange(len(c)) == np.argmin(c[:, 0]))[0])
    gap = 0.16 * P                                   # half the posterior (membranous) wall
    in_gap = lambda S: np.abs(((np.asarray(S) - s_post + P / 2) % P) - P / 2) < gap
    ant_mask = lum.c[:, 0] > -0.02                  # where the transverse cut (x = 0, y > 0) sections the wall
    is_ant = lambda S: ant_mask[(np.mod(np.asarray(S), P) / P * lum.n).astype(np.int64) % lum.n]
    anterior = lum.u[ant_mask]
    lateral = [float(lum.u[i]) for i in np.nonzero(np.diff(np.sign(lum.c[:, 0])) != 0)[0]]

    # heights (y) of the interfaces, measured from the luminal surface
    H_EPI, H_BM, H_LP, H_SUB, H_ADV, H_OUT = -0.030, -0.035, -0.068, -0.142, -0.262, -0.300
    ring_x = np.array([-0.9, -0.45, 0.0, 0.45, 0.9]) + rng.uniform(-0.02, 0.02, 5)

    def ridge(X, S):
        """Rings show through the mucosa as low transverse ridges; the posterior wall is ribbed lengthwise."""
        X, S = np.broadcast_arrays(np.asarray(X, np.float64), np.asarray(S, np.float64))
        post = np.clip(1.0 - np.abs(((S - s_post + P / 2) % P) - P / 2) / gap, 0.0, 1.0)
        rings = sum(np.exp(-((X - xc) / 0.11) ** 2) for xc in ring_x)
        return (0.0045 * rings * (1.0 - np.minimum(post * 1.6, 1.0)) - 0.002
                + 0.0022 * np.sin(S * 2 * math.pi / 0.055) * np.minimum(post * 1.8, 1.0))

    # gland positions: crowded in the posterior wall and between the rings, a few over the rings, and one on each
    # cut plane so the default cut-away sections them
    glands = []
    for k in range(9):
        glands.append((rng.uniform(-0.9, 0.9), s_post + rng.uniform(-0.8, 0.8) * gap))
    for k, gx in enumerate((ring_x[:-1] + ring_x[1:]) / 2):
        for j in range(2):
            glands.append((gx + rng.uniform(-0.03, 0.03), rng.uniform(s_post + gap + 0.1, s_post + P - gap - 0.1)))
    glands += [(0.02, float(anterior[len(anterior) // 3])), ((ring_x[0] + ring_x[1]) / 2, lateral[0] + 0.02),
               ((ring_x[1] + ring_x[2]) / 2, lateral[1] - 0.02), (0.98, s_post + gap * 0.4)]
    glands = [(gx, float(gs % P)) for gx, gs in glands if 0.12 < gs % P < P - 0.12]
    duct_tops = []
    for gx, gs in glands:
        a = rng.uniform(0, 2 * math.pi)
        duct_tops.append((gx + 0.05 * math.cos(a), (gs + 0.05 * math.sin(a)) % P))
    pores = Bumps(np.array(duct_tops), 0.012, 1.0, k=2, sharp=1.4)
    surf = add(ridge, _periodic_noise(0.0018, 9.0, P, seed=5), lambda X, S: -0.006 * pores(X, S))
    lift = lambda h, k=1.0: add(h, lambda X, S: ridge(X, S) * k)

    def groove(X, S):
        """0 over a ring, 1 between rings and over the membranous wall: seen from outside, the rings stand out."""
        X, S = np.broadcast_arrays(np.asarray(X, np.float64), np.asarray(S, np.float64))
        post = np.clip((gap - 0.07 - np.abs(((S - s_post + P / 2) % P) - P / 2)) / 0.08, 0.0, 1.0)
        t = np.clip((0.19 - np.min([np.abs(X - xc) for xc in ring_x], axis=0)) / 0.05, 0.0, 1.0)
        return np.maximum(1.0 - t * t * (3 - 2 * t), post)

    y_out = add(H_OUT, lambda X, S: 0.030 * groove(X, S), _periodic_noise(0.003, 5.0, P, 4))
    y_adv = add(H_ADV, lambda X, S: 0.018 * groove(X, S), _periodic_noise(0.002, 4.0, P, 2))

    parts = [
        hlayer("Adventitia", "Wall layers", "#e5d3b0", y_out, y_adv, TRACH_TEXT["adventitia"], "fascia", XE, SR,
               bulk=True, rank=-4, res=120, detail=(0.14, 50.0, 0.15, 0)),
        hlayer("Anular ligaments & fibroelastic membrane", "Cartilage", "#d8c8a4", y_adv, H_SUB, TRACH_TEXT["anular"],
               "ligament", XE, SR,
               bulk=True, rank=-3, res=120, detail=(0.12, 60.0, 0.12, 1)),
        hlayer("Lamina propria", "Mucosa & submucosa", "#efc3b8", lift(H_LP, 0.6), lift(H_BM), TRACH_TEXT["lp"],
               "mucosa", XE, SR, bulk=True, rank=0, res=110, detail=(0.12, 110.0, 0.5, 0)),
        hlayer("Basement membrane", "Epithelium", "#f6e3d3", lift(H_BM), lift(H_EPI), TRACH_TEXT["bm"], "cartilage",
               XE, SR, rank=0.5, res=110, detail=(0.03, 0.0, 0.0, 0)),
        hlayer("Pseudostratified ciliated epithelium", "Epithelium", "#d9aac0", lift(H_EPI), surf, TRACH_TEXT["epi"],
               "mucosa", XE, SR, rank=1, res=150, detail=(0.10, 150.0, 0.0, 0)),
    ]

    # ------------------------------------------------------------------ cartilage rings and trachealis
    rings, peri = Mesh(), Mesh()
    ring_meta = []
    for k, xc0 in enumerate(ring_x):
        s0 = s_post + gap + rng.uniform(-0.04, 0.04)
        s1 = s_post + P - gap + rng.uniform(-0.04, 0.04)
        ph = rng.uniform(0, 2 * math.pi, 4)
        span = s1 - s0

        def taper(s, s0=s0, s1=s1):
            d = np.minimum(s - s0, s1 - s)
            return np.clip(1.0 - d / 0.14, 0.0, 1.0) ** 1.5          # 1 at the free ends, 0 along the arch

        xc = lambda s, xc0=xc0, ph=ph, span=span, s0=s0: xc0 + 0.022 * np.sin((s - s0) / span * 5.0 + ph[0])
        wx = lambda s, ph=ph, span=span, s0=s0, t=taper: (0.128 + 0.014 * np.sin((s - s0) / span * 7.0 + ph[1])) \
            * (1.0 - 0.25 * t(s))
        hc = lambda s, t=taper: -0.200 - 0.024 * t(s)
        wh = lambda s, ph=ph, span=span, s0=s0, t=taper: (0.049 + 0.004 * np.sin((s - s0) / span * 9.0 + ph[2])) \
            * (1.0 - 0.42 * t(s))
        ring_meta.append((s0, s1, xc, wx, hc, wh))
        rings.extend(_band_mesh(s0, s1, xc, wx, hc, wh))
        peri.extend(_band_mesh(s0 - 0.008, s1 + 0.008, xc, lambda s, f=wx: f(s) + 0.0085, hc,
                               lambda s, f=wh: f(s) + 0.0085, tip=0.043))
    # the ends of the model section the outer rings: clamp them to a hair past the end walls so they cap cleanly
    for m, lim in ((rings, 1.0035), (peri, 1.0018)):
        for pos, _, _ in m.parts:
            np.clip(pos[:, 0], -lim, lim, out=pos[:, 0])
    parts += [
        mesh_part(peri, "Perichondrium", "Cartilage", "#e8dcc4", TRACH_TEXT["perichondrium"], "ligament", rank=-2.2,
                  detail=(0.10, 90.0, 0.35, 0)),
        mesh_part(rings, "Hyaline cartilage ring (C-shaped)", "Cartilage", "#a3bddc", TRACH_TEXT["rings"],
                  "cartilage", rank=-2, detail=(0.06, 38.0, 0.0, 0)),
    ]

    z0, z1 = s_post - gap - 0.085, s_post + gap + 0.085

    def mus_edge(S):
        d = np.abs(np.asarray(S) - s_post)
        return np.clip((d - (gap - 0.06)) / 0.12, 0.0, 1.0)

    mus = Mesh()
    ss = np.linspace(z0, z1, 50)
    lo_h, hi_h = -0.238 + 0.056 * mus_edge(ss), -0.149
    for row, frac in enumerate((0.29, 0.71)):
        xb = -1.0 + 0.030 * row
        while xb < 1.03:
            ph = rng.uniform(0, 2 * math.pi, 3)
            cut = rng.uniform(0.0, 0.05, 2)
            keep = (ss > z0 + cut[0]) & (ss < z1 - cut[1])
            s_ = ss[keep]
            t = (s_ - s_[0]) / (s_[-1] - s_[0])
            h = lo_h[keep] + (hi_h - lo_h[keep]) * (frac + 0.06 * np.sin(t * 5.0 + ph[0]))
            x = xb + 0.010 * np.sin(t * 4.0 + ph[1])
            end = np.clip(np.minimum(t, 1 - t) / 0.08, 0.15, 1.0) ** 0.5
            rx = 0.028 * (1.0 + 0.12 * np.sin(t * 7.0 + ph[2])) * end
            ry = (hi_h - lo_h[keep]) * 0.25 * end
            mus.extend(tube(np.stack([x, h, s_], -1), rx, 10, ry=ry))
            xb += 0.060 * rng.uniform(0.92, 1.08)
    for pos, _, _ in mus.parts:
        np.clip(pos[:, 0], -1.003, 1.003, out=pos[:, 0])
    parts.append(mesh_part(mus, "Trachealis muscle", "Cartilage", "#b85c4f", TRACH_TEXT["trachealis"], "muscle",
                           rank=-2.5, detail=(0.08, 80.0, 0.4, 4)))

    # chondrocytes where a cut or an end wall sections the rings: in lacunae, in isogenous groups
    cells, lac, terr = [], [], []
    for k, (s0, s1, xc, wx, hc, wh) in enumerate(ring_meta):
        samples = []                                                   # (x, or None for anywhere across, s)
        if abs(ring_x[k]) < 0.2:                                       # the transverse cut at x = 0 (anterior half)
            samples += [(rng.uniform(-0.009, 0.009), s) for s in np.arange(s0 + 0.02, s1 - 0.02, 0.022)
                        if is_ant(s)]
        if ring_x[k] < -0.2:                                           # the lengthwise cut through the side walls
            for ls in lateral:
                ls += P * round((0.5 * (s0 + s1) - ls) / P)
                samples += [(None, ls + rng.uniform(-0.011, 0.011)) for _ in range(10)]
        if abs(ring_x[k]) > 0.7:                                       # the end walls
            samples += [(math.copysign(1.003, ring_x[k]), s) for s in np.arange(s0 + 0.02, s1 - 0.02, 0.03)]
        for x0, s in samples:
            s = s + rng.uniform(-0.005, 0.005)
            for v in (-0.8, -0.4, 0.0, 0.4, 0.8):
                v += rng.uniform(-0.1, 0.1)
                if x0 is None:
                    u = rng.uniform(-0.85, 0.85)
                    x = float(xc(s) + u * wx(s))
                else:
                    x = x0
                    u = (x - xc(s)) / wx(s)
                rho = (abs(u) ** 2.6 + abs(v) ** 2.6) ** (1 / 2.6)
                if rho > 0.88:
                    continue
                c = np.array([x, hc(s) + v * wh(s), s])
                edge = rho > 0.68                                      # single flattened cells under the perichondrium
                n = 1 if edge else int(rng.choice([1, 2, 2, 3, 4]))
                r = (np.array([0.0055, 0.0030, 0.0068]) if edge else np.array([0.0050, 0.0046, 0.0050])) \
                    * rng.uniform(0.85, 1.15)
                step = np.zeros(3)
                ax = 2 if edge else int(rng.choice([0, 1, 2]))
                step[ax] = r[ax] * 2.25
                offs = (np.arange(n) - (n - 1) / 2)[:, None] * step[None]
                if n == 4:
                    offs = np.array([[-1, -1, 0], [1, -1, 0], [-1, 1, 0], [1, 1, 0]]) * r * 1.12
                for o in offs:
                    lac.append((c + o, r))
                    cells.append((c + o + rng.uniform(-0.0008, 0.0008, 3), r * 0.72))
                terr.append((c, np.abs(offs).max(axis=0) + r + 0.0032))
    clamp = 1.0045
    parts += [
        mesh_part(_blobs([c for c, _ in terr], [r for _, r in terr], 5, clamp), "Territorial matrix (isogenous groups)",
                  "Cartilage", "#7d8fc6", TRACH_TEXT["territorial"], "cartilage", rank=-1.9,
                  detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_blobs([c for c, _ in lac], [r for _, r in lac], 4, clamp + 0.0006), "Lacunae", "Cartilage",
                  "#eef1f4", TRACH_TEXT["lacunae"], "cartilage", rank=-1.8, detail=(0.02, 0.0, 0.0, 0)),
        mesh_part(_blobs([c for c, _ in cells], [r for _, r in cells], 4, clamp + 0.0012), "Chondrocytes",
                  "Cartilage", "#8a5c9c", TRACH_TEXT["chondrocytes"], "nucleus", rank=-1.7,
                  detail=(0.06, 0.0, 0.0, 0)),
    ]

    # ------------------------------------------------------------------ submucosa with seromucous glands
    vox = 0.004
    lo, hi = (-1.004, H_SUB - 0.006, 0.0), (1.004, H_LP + 0.002, P)
    muc, ser = Volume(lo, hi, 0.0052), Volume(lo, hi, 0.0038)
    muc_fine = Volume(lo, hi, 0.0038)                                    # only to trim the demilunes
    duct = Mesh()
    for (gx, gs), (tx, ts) in zip(glands, duct_tops):
        c = np.array([gx, (H_SUB + H_LP) / 2 - 0.004, gs])
        mshapes, sshapes = _gland_lobule(c, 0.085, rng, branches=8, per=7, scale=(1.0, 0.30, 1.0), demilunes=0.5)
        muc.add_all(mshapes, "smooth", 0.004)
        muc_fine.add_all(mshapes, "smooth", 0.004)
        ser.add_all(sshapes, "smooth", 0.003)
        top_h = float(at(surf, tx, ts))
        path = np.array([c + np.array([0.0, 0.012, 0.0]), [(gx + tx) / 2, H_LP + 0.004, (gs + ts) / 2],
                         [tx, H_BM - 0.004, ts], [tx, top_h - 0.004, ts]])
        sm = smooth_path(path, 24)
        duct.extend(tube(sm, np.interp(np.linspace(0, 1, len(sm)), [0, 0.35, 0.8, 1.0], [0.0060, 0.0052, 0.0046, 0.0052]), 12))
    ser.d = np.maximum(ser.d, -muc_fine.d)
    for v in (muc, ser):
        v.intersect_box((-1.0015, -1, 0.0), (1.0015, 1, P))
    art, vein = Mesh(), Mesh()
    gs_all = np.array([g[1] for g in glands])
    cand = np.linspace(0.2, P - 0.25, 60)
    clear = np.array([np.min(np.abs((gs_all - s + P / 2) % P - P / 2)) for s in cand])
    for j, s in enumerate(sorted(cand[np.argsort(-clear)[:7]])):
        path = wavy_path((-1.004, -0.124, s), (1.004, -0.124, s + 0.03), 60, 0.010, 1.4, seed=70 + j)
        art.extend(tube(path, 0.0075, 12))
        v = path.copy()
        v[:, 2] += 0.03
        v[:, 1] -= 0.004
        vein.extend(tube(v, 0.0105, 12))
    for j, s in enumerate((lateral[0] - 0.25, lateral[1] + 0.25, s_post + P / 2 + 0.3)):   # adventitial vessels
        path = wavy_path((-1.004, 0.0, s), (1.004, 0.0, s + 0.05), 80, 0.012, 1.1, seed=90 + j)
        path[:, 1] = y_out(path[:, 0], path[:, 2]) + 0.0045
        art.extend(tube(path, 0.0070, 12))
        v = path.copy()
        v[:, 2] += 0.024
        v[:, 1] = y_out(v[:, 0], v[:, 2]) + 0.0055
        vein.extend(tube(v, 0.0085, 12))
    for j, gx in enumerate((ring_x[:-1] + ring_x[1:]) / 2):          # transverse branches in the grooves
        for k, lat in enumerate((lateral[0] - 0.25, lateral[1] + 0.25)):
            end = s_post + P / 2 + (-0.03 if k == 0 else 0.03)            # the two sides meet in front
            path = wavy_path((gx, 0.0, lat), (gx + 0.01, 0.0, end), 60, 0.018, 3.2, seed=110 + 2 * j + k)
            path[:, 1] = y_out(path[:, 0], path[:, 2]) + 0.0030
            art.extend(tube(path, 0.0048, 10))
            v = path.copy()
            v[:, 0] += 0.016 + 0.006 * np.sin(np.linspace(0, 9.0, len(v)) + j)
            v[:, 1] = y_out(v[:, 0], v[:, 2]) + 0.0036
            vein.extend(tube(v, 0.0058, 10))
    parts += [
        hlayer("Submucosa", "Mucosa & submucosa", "#f0d6c6", H_SUB, lift(H_LP, 0.6), TRACH_TEXT["sub"], "fascia", XE,
               SR, bulk=True, rank=-1, res=120, detail=(0.14, 55.0, 0.15, 0)),
        sdf_part(muc, "Mucous gland tubules", "Glands", "#b9c4de", TRACH_TEXT["mucous"], "gland", rank=-0.8,
                 detail=(0.06, 150.0, 0.6, 0)),
        sdf_part(ser, "Serous demilunes & acini", "Glands", "#7c58a8", TRACH_TEXT["serous"], "gland", rank=-0.8,
                 detail=(0.06, 170.0, 0.95, 0)),
        mesh_part(duct, "Gland ducts", "Glands", "#a58fc9", TRACH_TEXT["ducts"], "gland", rank=0.5),
        mesh_part(art, "Arterioles", "Mucosa & submucosa", "#cf3a31", TRACH_TEXT["artery"], "artery",
                  rank=-1),
        mesh_part(vein, "Venules", "Mucosa & submucosa", "#3d5bc2", TRACH_TEXT["vein"], "vein", rank=-1),
    ]

    # elastic fibres: a sheet of longitudinal fibres in the deep lamina propria, gathered into ridges posteriorly
    elastic = Mesh()
    for j, s in enumerate(np.arange(0.01, P, 0.019)):
        post = bool(in_gap(s))
        h = H_LP + 0.008 + rng.uniform(0.0, 0.010)
        path = wavy_path((-1.003, h, s), (1.003, h + rng.uniform(-0.003, 0.003), s + rng.uniform(-0.02, 0.02)), 30,
                         0.004, rng.uniform(2.0, 4.0), seed=300 + j)
        path[:, 1] += 0.6 * ridge(path[:, 0], path[:, 2])
        elastic.extend(tube(path, 0.0045 if post else 0.0028, 6))
    parts.append(mesh_part(elastic, "Elastic fibres (elastic membrane)", "Mucosa & submucosa", "#e2c35c",
                           TRACH_TEXT["elastic"], "ligament", rank=0.2, detail=(0.05, 0.0, 0.0, 1)))

    # ------------------------------------------------------------------ epithelial cells, goblet cells and cilia
    gob = hex_points((-0.99, 0.0), (0.99, P), 0.051, jitter=0.36, seed=9)
    gob = gob[(gob[:, 1] > 0.004) & (gob[:, 1] < P - 0.004)]
    prof_r = np.array([0.0016, 0.0022, 0.0050, 0.0068, 0.0060, 0.0034])
    gb = np.stack([gob[:, 0], H_EPI + ridge(gob[:, 0], gob[:, 1]) + 0.001, gob[:, 1]], -1)
    gt = np.stack([gob[:, 0], surf(gob[:, 0], gob[:, 1]) + 0.0022, gob[:, 1]], -1)
    gob_mesh = _columns(gb, gt, prof_r, 5, seed=10)
    parts.append(mesh_part(gob_mesh, "Goblet cells", "Epithelium", "#e4ebf6", TRACH_TEXT["goblet"], "gland",
                           rank=1.2, detail=(0.03, 0.0, 0.0, 0)))

    # one tuft per ciliated cell; the hairs splay a little and all lean the same way (the metachronal wave that
    # drives the mucociliary escalator towards the larynx, +x)
    cells_ = hex_points((-0.996, 0.0), (0.996, P), 0.0114, jitter=0.25, seed=7)
    keep = (cKDTree(gob).query(cells_)[0] > 0.0085) & (cKDTree(np.array(duct_tops)).query(cells_)[0] > 0.013)
    cells_ = cells_[keep & (cells_[:, 1] > 0.003) & (cells_[:, 1] < P - 0.003)]
    tuft = np.array([[-1, -1], [1, -1], [-1, 1], [1, 1]], float) * 0.0021
    n_c = len(cells_)
    off = tuft[None] + rng.uniform(-0.0007, 0.0007, (n_c, len(tuft), 2))
    bx = (cells_[:, None, 0] + off[..., 0]).ravel()
    bs = (cells_[:, None, 1] + off[..., 1]).ravel()
    splay = off.reshape(-1, 2) * 0.55
    bh = surf(bx, bs) - 0.0012
    L = 0.0118 + rng.uniform(-0.0012, 0.0012, len(bx))
    wave = 0.0032 + 0.0022 * np.sin(bx * 38.0 + bs * 11.0)          # the metachronal wave sweeping the carpet
    base = np.stack([bx, bh, bs], -1)
    tipv = base + np.stack([wave + splay[:, 0] + rng.uniform(-0.0006, 0.0006, len(bx)), L,
                            splay[:, 1] + rng.uniform(-0.0008, 0.0008, len(bx))], -1)
    parts.append(mesh_part(_spikes(base, tipv, 0.0012, seed=3), "Cilia", "Epithelium", "#dfc7d3", TRACH_TEXT["cilia"],
                           "mucosa", rank=1.5, detail=(0.03, 0.0, 0.0, 2)))

    # nuclei at two levels - the tell-tale of a pseudostratified epithelium - where the cut and the ends section it
    pts = hex_points((-1.0, 0.0), (1.0, P), 0.0105, jitter=0.3, seed=13)
    near = (np.abs(pts[:, 0]) < 0.011) & is_ant(pts[:, 1])
    for ls in lateral:
        near |= (pts[:, 0] < 0.01) & (np.abs(pts[:, 1] - ls) < 0.011)
    near |= np.abs(pts[:, 0]) > 0.988
    pts = pts[near]
    gtree = cKDTree(gob)
    nuc_c, nuc_r, bas_c, bas_r = [], [], [], []
    for px, ps in pts:
        rb = ridge(px, ps)
        if gtree.query((px, ps))[0] < 0.007:
            continue
        nuc_c.append((px, H_EPI + rb + rng.uniform(0.013, 0.020), ps))
        nuc_r.append(np.array([0.0030, 0.0056, 0.0030]) * rng.uniform(0.85, 1.15))
        if rng.random() < 0.55:
            bas_c.append((px + rng.uniform(-0.004, 0.004), H_EPI + rb + 0.0042, ps + rng.uniform(-0.004, 0.004)))
            bas_r.append(np.array([0.0048, 0.0034, 0.0048]) * rng.uniform(0.85, 1.1))
    parts += [
        mesh_part(_blobs(nuc_c, nuc_r, 4, 1.0015), "Ciliated cell nuclei", "Epithelium", "#5d4a91",
                  TRACH_TEXT["nuclei"], "nucleus", rank=1.1, detail=(0.05, 0.0, 0.0, 0)),
        mesh_part(_blobs(bas_c, bas_r, 4, 1.0015), "Basal (stem) cells", "Epithelium", "#7c4f86", TRACH_TEXT["basal"],
                  "nucleus", rank=0.9, detail=(0.05, 0.0, 0.0, 0)),
    ]

    for p in parts:
        p.mesh = lum.wrap(_merged(p.mesh))
    return texture(parts, seed=33, grain=0.004, grain_across=12.0, grain_along=3.0, micro=0.0022, micro_freq=34.0)
