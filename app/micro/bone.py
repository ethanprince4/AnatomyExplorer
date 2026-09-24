"""Compact bone: a wedge of long-bone cortex from the periosteum to the marrow cavity.

The cortex is modelled the way it is actually organised: as a two-dimensional mosaic that runs along the shaft.
Osteons of different ages are laid down on top of one another - each new osteon erodes the ones it overlaps, so
the older ones survive only as ragged crescents of interstitial lamellae bounded by cement lines - and the whole
cross-section (lamellae, canals, cement lines, circumferential lamellae) is resolved exactly with polygon
booleans before being extruded along the bone. Every lamella is therefore a real closed solid: a transverse face
shows rings, a longitudinal face or cut shows the same lamellae as parallel bands with the central canal running
down the middle, and nothing is a flat picture of a bullseye pasted on a slab.

After the mosaic is extruded the block is bent round the axis of the shaft (it is a true wedge of a cylinder), the
osteons are made to wander slightly along their length, and the usual shared settle warp takes the machined look
off. Lacunae, canaliculi and fibres that must lie exactly in the default cut planes are placed in world space after
that warp, by inverting it, so the cut-away always slices straight through them.
"""
import math

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from .cells import orient_outward, sample_surface
from .geometry import Mesh, ellipsoid as ellipsoid_mesh, slab, smooth_path, tube
from .kit import Volume, mesh_part, tube_shell
from .organic import grain_field, sag_field
from .sdf import ellipsoid as sdf_ellipsoid, fbm3

H = 1.3                      # length of shaft in the block (y is the long axis of the bone)
Z0, Z1 = -0.62, 0.62         # circumferential extent (z runs around the shaft)
XP = -0.90                   # periosteal (outer) surface of the cortex; x increases towards the marrow
XE = 0.66                    # mean endosteal surface
XM = 1.25                    # far side of the marrow block
R_SHAFT = 5.0                # radius of the shaft at its periosteal surface
PC, PF = 0.034, 0.085        # periosteum: cambium and fibrous-layer thickness
LINING, CEMENT = 0.006, 0.0065
GAP = 0.00035              # clearance between neighbouring solids
INSET = 0.05               # how far the marrow stops short of the faces of the block
LAMELLAR = ("lamA", "lamB", "inter", "ocirc", "icirc")

D = {
    "canal": "Central (Haversian) canal: the channel running along the axis of every osteon, about 50 µm across, "
             "lined by flattened bone-lining (endosteal) cells and osteoprogenitor cells. It carries one or two "
             "capillaries or postcapillary venules, unmyelinated nerve fibres and a little loose connective tissue, "
             "and is joined to neighbouring canals, the periosteum and the marrow by Volkmann canals. Canals "
             "enlarge and multiply in osteoporosis, and a resorption canal is the first stage of a new osteon.",
    "h_art": "Haversian arteriole/capillary: a thin vessel (derived mainly from the nutrient artery via the marrow, "
             "and from periosteal arteries in the outer cortex) supplying the osteon. Osteocytes up to ~100 µm away "
             "are fed by diffusion through canaliculi, which is why an osteon is only about 200 µm wide.",
    "h_vein": "Haversian venule: a thin-walled postcapillary venule, usually wider than the arterial vessel beside it, "
              "draining through Volkmann canals to periosteal and medullary veins.",
    "h_nerve": "Nerve fibres of the central canal: mostly unmyelinated sympathetic (vasomotor) and sensory fibres "
               "running with the vessels; they contribute to bone pain and may regulate remodelling.",
    "lamellae": "Concentric lamellae: 4–20 rings, each 3–7 µm thick, of mineralised type I collagen (with "
                "hydroxyapatite) laid down from the outside inwards around the central canal. Within one lamella "
                "the collagen fibres wind helically in a single direction; the pitch changes from one lamella to the "
                "next (a 'twisted plywood'), which is why alternate lamellae look light and dark in polarised light "
                "and why osteons resist bending and torsion. Sets A and B are the two alternating fibre orientations.",
    "cement": "Cement (reversal) line: a thin (1–5 µm), collagen-poor, mineral-rich, basophilic boundary around every "
              "osteon and interstitial fragment. It marks where osteoclasts stopped resorbing before osteoblasts "
              "began to fill the tunnel. Canaliculi rarely cross it, and microcracks are deflected along it, which "
              "toughens bone. A chaotic 'mosaic' of scalloped cement lines is the hallmark of Paget disease.",
    "osteocytes": "Osteocytes in lacunae: former osteoblasts walled up in the matrix they made, lying in lens-shaped "
                  "lacunae between the lamellae – oval and aligned round the canal in a transverse section, spindle-"
                  "shaped along the osteon in a longitudinal one. They are ~90–95% of bone cells and live for years; "
                  "they sense strain through fluid flow in the canaliculi and steer remodelling (sclerostin, RANKL) "
                  "and phosphate balance (FGF23). Empty lacunae mean dead bone (osteonecrosis, sequestrum).",
    "canaliculi": "Canaliculi: fine channels (~0.5 µm) containing the dendritic processes of osteocytes, joined by "
                  "gap junctions. They radiate from each lacuna across the lamellae towards the central canal and "
                  "neighbouring lacunae, carrying nutrients, waste and signals – and normally stop at the cement line.",
    "fibres": "Collagen fibres of the lamellae: one osteon is drawn telescoped, like pulled-out tubes, to show that the "
              "collagen in each lamella winds helically round the canal and that the direction of the helix "
              "alternates between successive lamellae (Benninghoff's classic drawing).",
    "volkmann": "Perforating (Volkmann) canals: channels running transversely or obliquely through the cortex, linking "
                "central canals with one another and with the periosteal and endosteal (marrow) surfaces. Unlike "
                "central canals they have no concentric lamellae of their own – they simply cut across lamellae. "
                "On a transverse ground section they appear as channels joining neighbouring Haversian canals.",
    "volk_vessels": "Vessels in the Volkmann canals: branches connecting the periosteal and medullary (nutrient) "
                    "circulations with the capillaries of the central canals.",
    "interstitial": "Interstitial lamellae: angular fragments of older osteons (and of circumferential lamellae) left "
                    "between intact osteons after remodelling partly resorbed them. Each is bounded by cement lines "
                    "and cut across by the newer osteons around it. They are the oldest, most highly mineralised "
                    "bone of the cortex and often contain empty lacunae.",
    "ocirc": "Outer circumferential lamellae: several continuous lamellae running round the whole shaft beneath the "
             "periosteum, laid down by periosteal osteoblasts as the bone grows in width (appositional growth). "
             "Sharpey fibres anchor in them; osteons produced by remodelling gradually replace them from within.",
    "icirc": "Inner circumferential lamellae: thinner, less complete lamellae lining the marrow cavity, laid down by "
             "endosteal osteoblasts and interrupted where trabeculae join the cortex.",
    "cambium": "Periosteum – cambium (osteogenic) layer: the inner, cellular layer applied to the bone, with "
               "osteoprogenitor (skeletal stem) cells, osteoblasts and a dense capillary network. Very active in "
               "children (growth in width) and after a fracture, when it forms the external callus – stripping "
               "the periosteum delays healing. Thin and inconspicuous in adults.",
    "fibrous": "Periosteum – fibrous layer: outer dense irregular connective tissue of type I collagen bundles and "
               "fibroblasts, carrying the periosteal vessels, lymphatics and a dense sensory innervation (so "
               "fractures, bone tumours and periostitis are painful). Tendons and ligaments blend into it; it is "
               "absent over articular cartilage.",
    "sharpey": "Sharpey (perforating) fibres: bundles of periosteal collagen that turn inwards and pierce the outer "
               "circumferential lamellae obliquely, anchoring the periosteum – and tendons and ligaments at their "
               "entheses – to the bone. The same fibres anchor the periodontal ligament in the tooth socket.",
    "p_art": "Periosteal artery: part of the periosteal plexus that supplies roughly the outer third of the adult "
             "cortex through Volkmann canals (the inner two-thirds is supplied centrifugally by the nutrient artery). "
             "Periosteal flow is vital when the medullary supply is destroyed, e.g. after reaming for a nail.",
    "p_vein": "Periosteal vein: drains the outer cortex and periosteum; blood from most of the cortex leaves "
              "centrifugally through Volkmann canals to these veins.",
    "p_nerve": "Periosteal nerve: myelinated (Aδ) and unmyelinated (C) sensory fibres plus sympathetic fibres; the "
               "periosteum is the most pain-sensitive part of bone.",
    "endosteum": "Endosteum: a thin, discontinuous layer of flattened bone-lining cells, osteoprogenitor cells, "
                 "osteoblasts and osteoclasts covering every inner bone surface – the endosteal surface of the "
                 "cortex, the trabeculae and the lining of the canals. Its balance of resorption and formation sets "
                 "the width of the marrow cavity, which widens with age as endosteal resorption wins.",
    "osteoblasts": "Osteoblasts: plump cuboidal cells with basophilic (RNA-rich) cytoplasm, lined up on a surface "
                   "where bone is forming over a thin seam of unmineralised osteoid. They secrete type I collagen, "
                   "osteocalcin and alkaline phosphatase, control osteoclasts through RANKL and osteoprotegerin, and "
                   "end as osteocytes, flat lining cells or by apoptosis. Driven by RUNX2 and Osterix.",
    "lining": "Bone-lining cells: flat, quiescent osteoblast-lineage cells covering inactive bone surfaces. They can be "
              "reactivated into osteoblasts, and retract to expose the surface to osteoclasts when remodelling starts.",
    "osteoclasts": "Osteoclasts: large multinucleated cells (fused monocyte–macrophage precursors, needing M-CSF and "
                   "RANKL) sitting in resorption pits (Howship lacunae). A sealing zone (αvβ3 integrin) surrounds a "
                   "ruffled border that pumps out H+ (carbonic anhydrase II, proton pump) to dissolve mineral and "
                   "cathepsin K to digest collagen. Inhibited by bisphosphonates, denosumab (anti-RANKL) and "
                   "calcitonin; defective in osteopetrosis.",
    "trabeculae": "Trabeculae (spongy, cancellous bone): a lattice of plates and rods of lamellar bone, each ~100–300 "
                  "µm thick, usually without osteons – they are nourished from the marrow surface. Near the cortex "
                  "they thicken and fuse into compact bone. They align with lines of stress (Wolff's law) and have a "
                  "large surface, so they remodel fast and are lost first in osteoporosis (vertebral fractures).",
    "marrow": "Red (haematopoietic) marrow: sinusoids in a reticular-cell stroma packed with developing blood cells – "
              "erythroid islands, granulocyte precursors and megakaryocytes. In adults it remains in the axial "
              "skeleton and the proximal femur and humerus; the shafts of long bones turn to yellow, fatty marrow.",
    "adipocytes": "Marrow adipocytes: unilocular fat cells among the haematopoietic tissue. They increase with age "
                  "(and after radiotherapy or in aplastic anaemia) until the marrow of the long-bone shafts is yellow.",
    "m_art": "Branch of the nutrient (medullary) artery: runs in the marrow cavity, supplies the marrow and, through "
             "endosteal branches entering Volkmann canals, the inner two-thirds of the cortex.",
    "m_vein": "Marrow sinusoids and central venous sinus: wide, thin-walled vessels into which newly formed blood "
              "cells squeeze through the endothelium; they drain to the central sinus and nutrient vein.",
}


# ---------------------------------------------------------------------------------------------- profiles
def _smooth(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _xe(z):
    """Endosteal surface of the cortex, x as a function of z: an irregular, scalloped inner border."""
    z = np.asarray(z, float)
    return XE + 0.030 * np.sin(4.3 * z + 0.6) + 0.018 * np.sin(9.7 * z + 2.1)


def _peel(z):
    """0 where the periosteum covers the bone to the top of the block, 1 where it is peeled back."""
    return _smooth((-0.20 - np.asarray(z, float)) / 0.16)


def _hp(z):
    return H - 0.30 * _peel(z) + 0.012 * np.sin(9.0 * np.asarray(z, float)) * _peel(z)


def _hf(z):
    return _hp(z) - 0.075 * _peel(z)


# ----------------------------------------------------------------------------------------------- osteons
class _Osteon:
    """Outline shared by every ring of one osteon (so they nest however irregular it is), plus its lamellae."""

    def __init__(self, cx, cz, R, rng, canal=True, n=None):
        self.c = np.array([cx, cz], float)
        self.R = R
        self.canal = canal
        self.rc = rng.uniform(0.030, 0.043) if canal else 0.0
        self.n = n or int(np.clip(round((R - 0.05) / 0.017), 5, 9))
        self.k = np.arange(2, 7)
        self.amp = rng.uniform(0.25, 1.0, 5) * 0.075 / self.k
        self.ph = rng.uniform(0, 2 * math.pi, 5)
        self.ecc = rng.uniform(0.0, 0.10)
        self.rot = rng.uniform(0, math.pi)
        inner = self.rc + LINING if canal else 0.010
        outer = R - CEMENT
        t = np.linspace(0.0, 1.0, self.n + 1)
        t[1:-1] += rng.uniform(-0.22, 0.22, self.n - 1) / self.n
        self.radii = inner + (outer - inner) * t
        self.wob = rng.uniform(0, 2 * math.pi, self.n + 1)
        self.pieces = []

    def shape(self, th):
        th = np.asarray(th, float)
        return 1.0 + (self.amp[:, None] * np.cos(self.k[:, None] * th[None] + self.ph[:, None])).sum(0)

    def xy(self, r, th, ring=None):
        th = np.asarray(th, float)
        rr = r * self.shape(th)
        if ring is not None and 0 < ring < self.n:
            rr = rr + 0.0028 * np.cos(3 * th + self.wob[ring])
        u, v = rr * np.cos(th), rr * np.sin(th)
        c, s = math.cos(self.rot), math.sin(self.rot)
        a, b = c * u + s * v, -s * u + c * v
        a, b = a * (1 + self.ecc), b * (1 - self.ecc)
        return np.stack([self.c[0] + c * a - s * b, self.c[1] + s * a + c * b], -1)

    def ring(self, r, ring=None):
        n = int(np.clip(2 * math.pi * r / 0.008, 40, 160))
        return Polygon(self.xy(r, np.linspace(0, 2 * math.pi, n, endpoint=False), ring))

    def disk(self):
        return self.ring(self.R)


def _polys(g, min_area=0.0):
    """The polygons of any shapely result, dropping slivers."""
    if g is None or g.is_empty:
        return []
    if not g.is_valid:
        g = shapely.make_valid(g)
    if g.geom_type == "Polygon":
        return [g] if g.area > min_area else []
    out = []
    for sub in getattr(g, "geoms", []):
        out.extend(_polys(sub, min_area))
    return out


def _dart(rng, n, lo, hi, min_d, existing, tries=4000):
    pts = [np.asarray(p, float) for p in existing]
    out = []
    for _ in range(tries):
        if len(out) >= n:
            break
        p = rng.uniform(lo, hi)
        if all(np.linalg.norm(p - q) >= min_d for q in pts):
            pts.append(p)
            out.append(p)
    return out


# ------------------------------------------------------------------------------------ polygon extrusion
def _cap(poly, y, up):
    """Flat cap of a polygon at height y, facing up or down (constrained Delaunay triangulation)."""
    tris = shapely.constrained_delaunay_triangles(orient(poly, 1.0))
    if tris.is_empty:
        return np.zeros((0, 3)), np.zeros((0, 3), int)
    tri = np.array([np.asarray(t.exterior.coords)[:3] for t in tris.geoms])
    cr = ((tri[:, 1, 0] - tri[:, 0, 0]) * (tri[:, 2, 1] - tri[:, 0, 1])
          - (tri[:, 1, 1] - tri[:, 0, 1]) * (tri[:, 2, 0] - tri[:, 0, 0]))
    tri[cr < 0] = tri[cr < 0][:, ::-1]
    flat = tri.reshape(-1, 2)
    n = len(tri)
    pos = np.column_stack([flat[:, 0], np.full(len(flat), y), flat[:, 1]])
    return pos, np.arange(3 * n).reshape(n, 3)[:, [0, 2, 1] if up else [0, 1, 2]]


def _walls(poly, bottom, top, step=0.15):
    """Side walls of a prism, with several rings along y so the later warps can bend them; sharp corners get
    split normals."""
    poly = orient(poly, 1.0)
    levels = np.linspace(bottom, top, max(2, int(math.ceil((top - bottom) / step)) + 1))
    L = len(levels)
    out = []
    for ring in [poly.exterior, *poly.interiors]:
        pts = np.asarray(ring.coords)[:-1]
        M = len(pts)
        if M < 3:
            continue
        prev = pts - np.roll(pts, 1, 0)
        nxt = np.roll(pts, -1, 0) - pts
        cosang = (prev * nxt).sum(1) / np.maximum(np.linalg.norm(prev, axis=1) * np.linalg.norm(nxt, axis=1), 1e-12)
        sharp = (cosang < 0.55).astype(int)
        out_id = np.cumsum(1 + sharp) - 1
        in_id = out_id - sharp
        src = np.repeat(np.arange(M), 1 + sharp)
        V = len(src)
        P = pts[src]
        grid = np.stack([np.broadcast_to(P[None, :, 0], (L, V)), np.broadcast_to(levels[:, None], (L, V)),
                         np.broadcast_to(P[None, :, 1], (L, V))], -1).reshape(-1, 3)
        a = out_id
        b = in_id[(np.arange(M) + 1) % M]
        lv = np.arange(L - 1)[:, None]
        a0, a1 = (lv * V + a).ravel(), ((lv + 1) * V + a).ravel()
        b0, b1 = (lv * V + b).ravel(), ((lv + 1) * V + b).ravel()
        out.append((grid, np.concatenate([np.stack([a1, b1, b0], 1), np.stack([a1, b0, a0], 1)])))
    return out


def _stack(layers):
    """One closed solid from a stack of prisms [(y0, y1, polygon)], bottom to top, each sitting on the last.

    Where consecutive layers differ, only the difference is capped (up-facing where the lower one sticks out,
    down-facing where the upper one overhangs), so a tunnel can be carved through a solid without splitting it
    into separate closed pieces whose coincident faces would fight on a cut face."""
    items = []
    for i, (y0, y1, poly) in enumerate(layers):
        items.extend(_walls(poly, y0, y1))
        if i == 0:
            items.append(_cap(poly, y0, False))
        if i == len(layers) - 1:
            items.append(_cap(poly, y1, True))
        else:
            above = layers[i + 1][2]
            for g, up in ((poly.difference(above), True), (above.difference(poly), False)):
                for p in _polys(g, 1e-9):
                    items.append(_cap(p, y1, up))
    items = [(p, i) for p, i in items if len(i)]
    if not items:
        return Mesh()
    pos, idx, off = [], [], 0
    for p, i in items:
        pos.append(p)
        idx.append(i + off)
        off += len(p)
    return Mesh().add(np.vstack(pos), np.vstack(idx))


def _extrude(poly, top, bottom=0.0):
    """Closed prism: a (possibly holed) polygon in the x-z plane extruded along y from `bottom` to `top`."""
    return _stack([(bottom, top, poly)])


# ---------------------------------------------------------------------------------------- batched cells
_TEMPLATES = {}


def _ellipsoids(centers, e1, e2, radii, res=5):
    """Many ellipsoids as one mesh. e1, e2 are unit axes (e3 = e1 x e2); radii are the semi-axes along them."""
    centers = np.asarray(centers, float).reshape(-1, 3)
    if not len(centers):
        return Mesh()
    if res not in _TEMPLATES:
        p, _, i = ellipsoid_mesh((0, 0, 0), (1, 1, 1), res).arrays()
        _TEMPLATES[res] = (p.astype(np.float64), i)
    tp, ti = _TEMPLATES[res]
    e1 = np.asarray(e1, float).reshape(-1, 3)
    e2 = np.asarray(e2, float).reshape(-1, 3)
    e3 = np.cross(e1, e2)
    loc = tp[None] * np.asarray(radii, float).reshape(-1, 1, 3)
    world = (centers[:, None] + loc[..., 0:1] * e1[:, None] + loc[..., 1:2] * e2[:, None]
             + loc[..., 2:3] * e3[:, None])
    idx = ti[None] + (np.arange(len(centers)) * len(tp))[:, None, None]
    return orient_outward(Mesh().add(world.reshape(-1, 3), idx.reshape(-1, 3)))


def _spikes(starts, ends, r):
    """Thin three-sided cones from `starts` to `ends` (canaliculi): four triangles each."""
    s = np.asarray(starts, float).reshape(-1, 3)
    e = np.asarray(ends, float).reshape(-1, 3)
    if not len(s):
        return Mesh()
    d = e - s
    d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-12)
    helper = np.where(np.abs(d[:, 1:2]) < 0.9, [[0.0, 1.0, 0.0]], [[1.0, 0.0, 0.0]])
    u = np.cross(d, helper)
    u /= np.linalg.norm(u, axis=1, keepdims=True)
    v = np.cross(d, u)
    rr = np.broadcast_to(np.asarray(r, float), (len(s),))[:, None]
    base = [s + rr * (math.cos(a) * u + math.sin(a) * v) for a in (0.0, 2.094, 4.189)]
    pos = np.stack(base + [e], 1).reshape(-1, 3)
    t = np.array([[0, 1, 3], [1, 2, 3], [2, 0, 3], [0, 2, 1]])
    idx = t[None] + (np.arange(len(s)) * 4)[:, None, None]
    return orient_outward(Mesh().add(pos, idx.reshape(-1, 3)))


def _drop_islands(mesh, min_tris=400):
    """Remove the stray specks marching cubes leaves where a noisy field just grazes zero."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    pos, _, idx = mesh.arrays()
    if not len(idx):
        return mesh
    e = np.concatenate([idx[:, [0, 1]], idx[:, [1, 2]], idx[:, [2, 0]]])
    g = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(len(pos), len(pos)))
    _, lab = connected_components(g, directed=False)
    size = np.bincount(lab[idx[:, 0]], minlength=lab.max() + 1)
    keep = size[lab[idx[:, 0]]] >= min_tris
    return Mesh().add(pos, idx[keep])


# --------------------------------------------------------------------------------------------- warps
def _wander(p):
    """Osteons are not ruler-straight: a slow drift of the cross-section along the bone."""
    d = np.zeros_like(p)
    x, y, z = p[:, 0] * 2.1, p[:, 1] * 1.05, p[:, 2] * 2.1
    d[:, 0] = 0.014 * fbm3(x, y, z, 1.0, 2, 401)
    d[:, 2] = 0.014 * fbm3(x + 4.1, y + 1.3, z + 7.7, 1.0, 2, 402)
    return d


def _bend(p):
    """Bend the block round the long axis of the shaft, which lies on the marrow side."""
    ax = XP + R_SHAFT
    rr = ax - p[:, 0]
    phi = p[:, 2] / R_SHAFT
    q = p.copy()
    q[:, 0] = ax - rr * np.cos(phi)
    q[:, 2] = rr * np.sin(phi)
    return q


_SAG = sag_field(amp_xz=0.010, amp_y=0.012, freq=1.4, seed=601, octaves=2, shear=0.006)
_GRAIN = grain_field(0.0028, 11.0, 3.0, 1, 632)


def _forward(p):
    p = np.asarray(p, np.float64)
    p = p + _wander(p)
    p = _bend(p)
    return p + _SAG(p) + _GRAIN(p)


def _inverse(q, iters=7):
    q = np.asarray(q, np.float64).reshape(-1, 3)
    p = q.copy()
    for _ in range(iters):
        p = p + (q - _forward(p))
    return p


def _warp_mesh(mesh):
    out = Mesh()
    for pos, _, idx in mesh.parts:
        out.add(_forward(pos), idx)
    return out


# ------------------------------------------------------------------------------------------- the model
def _layout(rng):
    """Positions of the complete osteons (newest first) and of the older, eroded ones."""
    key = [  # (x, z, R): placed where a face or the default cut-away slices them lengthwise
        (-0.47, 0.00, 0.165), (-0.13, 0.012, 0.150),        # sectioned by the cut plane z = 0
        (0.00, 0.33, 0.150),                                  # sectioned by the cut plane x = 0
        (0.30, Z1 - 0.014, 0.160), (-0.33, Z1 + 0.02, 0.150),  # front face
        (-0.28, Z0 + 0.012, 0.160), (0.33, Z0 - 0.03, 0.150),  # back face
    ]
    tele = (0.25, -0.24, 0.170)
    pts = [np.array(k[:2]) for k in key] + [np.array(tele[:2])]
    extra = _dart(rng, 9, (XP + 0.26, Z0 + 0.05), (XE - 0.17, Z1 - 0.05), 0.30, pts)
    comp = [(p[0], p[1], rng.uniform(0.125, 0.165)) for p in extra]
    order = list(key) + comp
    rng.shuffle(order)
    complete = [_Osteon(*tele, rng, n=6)] + [_Osteon(x, z, R, rng) for x, z, R in order]
    old = []
    for _ in range(44):
        x, z = rng.uniform(XP + 0.15, XE - 0.06), rng.uniform(Z0 - 0.05, Z1 + 0.05)
        old.append(_Osteon(x, z, rng.uniform(0.13, 0.21), rng, canal=False, n=int(rng.integers(5, 9))))
    return complete, old


def _circ_bands(outer):
    """Circumferential lamellae as strips following the periosteal or endosteal surface."""
    zs = np.linspace(Z0 - 0.02, Z1 + 0.02, 90)
    if outer:
        bounds = [np.full_like(zs, XP - 0.002)] + [XP + 0.026 * k + 0.004 * np.sin(6.0 * zs + 1.7 * k)
                                                   for k in range(1, 7)]
    else:
        base = _xe(zs)
        bounds = [base - 0.026 * k + 0.003 * np.sin(8.0 * zs + 2.3 * k) for k in range(3, 0, -1)] + [base + 0.002]
    bands = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        ring = np.concatenate([np.stack([a, zs], -1), np.stack([b, zs], -1)[::-1]])
        bands.append(Polygon(ring))
    return bands


def _mosaic(complete, old):
    """Resolve the cross-section: newest osteons first, each claiming what is left of its disk."""
    zs = np.linspace(Z0, Z1, 120)
    block = Polygon(np.concatenate([np.stack([np.full_like(zs, XP), zs], -1)[::-1],
                                    np.stack([_xe(zs), zs], -1)]))
    claimed = Polygon()
    pieces, voids = [], []
    tele = complete[0]
    tops_tele = {}

    def add(geom, key, top, owner, lam=None):
        for p in _polys(geom, 2.5e-5):
            pieces.append({"geom": p, "key": key, "top": top, "owner": owner, "lam": lam})

    for oi, o in enumerate(complete):
        avail = o.disk().intersection(block).difference(claimed)
        if avail.is_empty:
            continue
        rings = [o.ring(o.rc)] + [o.ring(r, i) for i, r in enumerate(o.radii)] + [o.disk()]
        is_tele = o is tele
        n = o.n
        # telescoped osteon: the canal lining rises highest, each lamella a step lower, the cement line lowest
        step = 0.032
        voids.append(rings[0].intersection(avail))
        add(rings[1].difference(rings[0]).intersection(avail), "canal", H + step * (n + 2) if is_tele else H, oi)
        for k in range(n):
            band = rings[k + 2].difference(rings[k + 1]).intersection(avail)
            top = H + step * (n + 1 - k) if is_tele else (H if k % 2 == 0 else H - 0.0025)
            if is_tele:
                tops_tele[k] = top
            add(band, "lamA" if k % 2 == 0 else "lamB", top, oi, k)
        add(rings[-1].difference(rings[-2]).intersection(avail), "cement", H + step if is_tele else H - 0.004, oi)
        claimed = claimed.union(o.disk().intersection(block))
    tele.tops = tops_tele
    for outer in (True, False):
        bands = _circ_bands(outer)
        region = unary_union(bands)
        avail = region.intersection(block).difference(claimed)
        for k, b in enumerate(bands):
            add(b.intersection(avail), "ocirc" if outer else "icirc", H if k % 2 == 0 else H - 0.0025, -1, k)
        claimed = claimed.union(region.intersection(block))
    for oi, o in enumerate(old):
        avail = o.disk().intersection(block).difference(claimed)
        if avail.area < 2e-3:
            continue
        rings = [o.ring(r, i) for i, r in enumerate(o.radii)] + [o.disk()]
        add(rings[0].intersection(avail), "inter", H, 1000 + oi, -1)
        for k in range(o.n):
            band = rings[k + 1].difference(rings[k]).intersection(avail)
            add(band, "inter", H if k % 2 == 0 else H - 0.0025, 1000 + oi, k)
        add(rings[-1].difference(rings[-2]).intersection(avail), "cement", H - 0.004, 1000 + oi)
        claimed = claimed.union(o.disk().intersection(block))
    used = unary_union([p["geom"] for p in pieces] + [v for v in voids if not v.is_empty])
    add(block.difference(used), "inter", H, -2)
    zs2 = np.linspace(Z0, Z1, 120)
    endo = Polygon(np.concatenate([np.stack([_xe(zs2), zs2], -1), np.stack([_xe(zs2) + 0.009, zs2], -1)[::-1]]))
    add(endo, "endo", H, -3)
    return pieces, block


def _volkmann_top(complete, rng):
    """Volkmann canals exposed on the transverse (top) face: channels joining Haversian canals, and one to the
    periosteal surface where the periosteum has been peeled back."""
    cand = [o for o in complete[1:] if Z0 + 0.12 < o.c[1] < Z1 - 0.12 and XP + 0.2 < o.c[0] < XE - 0.1
            and not (o.c[0] < 0.05 and o.c[1] > -0.05)]
    paths, used = [], set()
    pairs = sorted(((float(np.linalg.norm(a.c - b.c)), i, j) for i, a in enumerate(cand)
                    for j, b in enumerate(cand) if i < j), key=lambda t: t[0])
    for dist, i, j in pairs:
        if len(paths) >= 2:
            break
        if i in used or j in used or not 0.24 < dist < 0.40:
            continue
        a, b = cand[i].c, cand[j].c
        mid = (a + b) / 2 + np.array([-(b - a)[1], (b - a)[0]]) / dist * rng.uniform(-0.04, 0.04)
        paths.append(smooth_path(np.array([[a[0], 0, a[1]], [mid[0], 0, mid[1]], [b[0], 0, b[1]]]), 24)[:, [0, 2]])
        used |= {i, j}
    outer = [o for o in complete[1:] if o.c[1] < -0.33 and o.c[1] > Z0 + 0.1]
    if outer:
        o = min(outer, key=lambda q: q.c[0])
        a = o.c
        b = np.array([XP - 0.03, a[1] - 0.05])
        mid = (a + b) / 2 + np.array([0.0, 0.03])
        paths.append(smooth_path(np.array([[a[0], 0, a[1]], [mid[0], 0, mid[1]], [b[0], 0, b[1]]]), 24)[:, [0, 2]])
    return paths


def _groove(pieces, paths):
    """Cut the Volkmann channels into the top face: a stepped, rounded trench."""
    if not paths:
        return pieces
    lines = unary_union([LineString(p) for p in paths])
    zones = [(lines.buffer(w, quad_segs=6), d) for w, d in ((0.022, 0.007), (0.015, 0.015), (0.008, 0.021))]
    out = []
    for pc in pieces:
        if pc["top"] > H + 1e-6:
            out.append(pc)
            continue
        g = pc["geom"]
        rest = g.difference(zones[0][0])
        if rest.area > 1e-9:
            for p in _polys(rest):
                out.append(dict(pc, geom=p))
        for zi, (zone, depth) in enumerate(zones):
            inner = zones[zi + 1][0] if zi + 1 < len(zones) else None
            part = g.intersection(zone)
            if inner is not None:
                part = part.difference(inner)
            for p in _polys(part):
                out.append(dict(pc, geom=p, top=min(pc["top"], H - depth), groove=True))
    return out


class _Lacunae:
    """Collects osteocyte lacunae (flattened ellipsoids) and their canaliculi (hair-thin spikes)."""

    def __init__(self, rng):
        self.rng = rng
        self.cen, self.e1, self.e2, self.rad, self.c0, self.c1 = ([] for _ in range(6))

    def add(self, c, along, normal, across):
        """`along` is the long axis (the lamella's direction), `normal` the thin axis (normal to the face it is
        seen on), `across` the direction across the lamellae, which is where the canaliculi run."""
        rng = self.rng
        c = np.asarray(c, float)
        along, normal, across = (np.asarray(v, float) for v in (along, normal, across))
        self.cen.append(c)
        self.e1.append(along)
        self.e2.append(normal)
        self.rad.append((rng.uniform(0.0075, 0.0095), 0.0030, rng.uniform(0.0028, 0.0036)))
        for _ in range(int(rng.integers(3, 6))):
            d = across * (1 if rng.random() < 0.5 else -1) + along * rng.uniform(-0.35, 0.35)
            d /= np.linalg.norm(d)
            st = c + d * 0.0026 + along * rng.uniform(-0.005, 0.005)
            self.c0.append(st)
            self.c1.append(st + d * rng.uniform(0.010, 0.018))

    def meshes(self):
        cen = np.array(self.cen).reshape(-1, 3)
        lac = _ellipsoids(cen, np.array(self.e1).reshape(-1, 3), np.array(self.e2).reshape(-1, 3),
                          np.array(self.rad).reshape(-1, 3), 4)
        return lac, _spikes(np.array(self.c0).reshape(-1, 3), np.array(self.c1).reshape(-1, 3), 0.0010)


def _runs(label, ds, min_w=0.008):
    edges = np.flatnonzero(np.diff(label) != 0) + 1
    for s0, s1 in zip(np.concatenate([[0], edges]), np.concatenate([edges, [len(label)]])):
        if label[s0] >= 0 and (s1 - s0) * ds >= min_w:
            yield int(s0), int(s1)


def _plane_lacunae(lac, pieces, a, b, normal, world, rng):
    """Lacunae in a longitudinal plane: spindles along the osteon axis in the middle of each lamella they cross.

    For a block face the line a-b is in pre-warp coordinates (the lacunae are warped with the block); for a cut
    plane it is in world space and each row is pulled back through the warp to find the lamellae."""
    lam = [pc for pc in pieces if pc["key"] in LAMELLAR]
    tree = shapely.STRtree([pc["geom"] for pc in lam])
    ds = 0.0015
    n_s = int(np.linalg.norm(np.subtract(b, a)) / ds)
    t = np.linspace(0.0, 1.0, n_s)
    px, pz = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
    along = np.array([b[0] - a[0], 0.0, b[1] - a[1]])
    along /= np.linalg.norm(along)
    up = np.array([0.0, 1.0, 0.0])

    def labels(x, z):
        hit = tree.query(shapely.points(x, z), predicate="within")
        lab = np.full(len(x), -1)
        lab[hit[0]] = hit[1]
        return lab

    fixed = None if world else labels(px, pz)
    for y in np.arange(rng.uniform(0.02, 0.05), H - 0.02, 0.066):
        if world:
            pre = _inverse(np.column_stack([px, np.full(n_s, y), pz]))
            label = labels(pre[:, 0], pre[:, 2])
        else:
            label = fixed
        for s0, s1 in _runs(label, ds):
            k = max(1, int((s1 - s0) * ds / 0.04))
            for j in range(k):
                if rng.random() < 0.3:
                    continue
                i = int(s0 + (s1 - s0) * (j + 0.5 + rng.uniform(-0.25, 0.25)) / k)
                yy = min(max(y + rng.uniform(-0.02, 0.02), 0.012), H - 0.012)
                lac.add((px[i], yy, pz[i]), up, normal, along)


def _lacunae_top(lac, pieces, complete, old, rng):
    """Lacunae on the transverse face: lens-shaped, lying along the lamellae, canaliculi radiating across them."""
    by_owner = {}
    for pc in pieces:
        if pc["key"] in LAMELLAR and H - 0.003 <= pc["top"] <= H and not pc.get("groove"):
            by_owner.setdefault(pc["owner"], []).append(pc["geom"])
    regions = {k: unary_union(v).buffer(-0.005) for k, v in by_owner.items()}
    up = np.array([0.0, 1.0, 0.0])

    def emit(p, t):
        lac.add((p[0], H - 0.0006, p[1]), (t[0], 0.0, t[1]), up, (t[1], 0.0, -t[0]))

    sp = 0.066
    for owner, os_ in [(i, o) for i, o in enumerate(complete)] + [(1000 + i, o) for i, o in enumerate(old)]:
        reg = regions.get(owner)
        if reg is None or reg.is_empty:
            continue
        rs = list(os_.radii[1:-1]) + [0.5 * (os_.radii[0] + os_.radii[1])]
        for ri, r in enumerate(rs):
            th = np.arange(rng.uniform(0, 0.6), 2 * math.pi, sp / max(r, 0.03))
            th = th + rng.uniform(-0.3, 0.3, len(th)) * sp / max(r, 0.03)
            pts = os_.xy(r, th, ri + 1)
            ok = shapely.contains_xy(reg, pts[:, 0], pts[:, 1])
            nb = os_.xy(r, th + 0.01, ri + 1)
            for p, q, good in zip(pts, nb, ok):
                if good and rng.random() > 0.15:
                    emit(p, (q - p) / max(np.linalg.norm(q - p), 1e-9))
    reg = regions.get(-1)
    if reg is not None:
        for k in range(1, 7):
            for zz in np.arange(Z0 + 0.02, Z1 - 0.02, sp) + rng.uniform(-0.02, 0.02):
                for xb in (XP + 0.026 * k - 0.013, float(_xe(zz)) - 0.026 * min(k, 3) + 0.013):
                    if shapely.contains_xy(reg, xb, zz) and rng.random() > 0.2:
                        emit(np.array([xb, zz]), np.array([0.0, 1.0]))
    reg = regions.get(-2)
    if reg is not None and not reg.is_empty:
        x0, z0_, x1, z1_ = reg.bounds
        pts = np.column_stack([rng.uniform(x0, x1, 900), rng.uniform(z0_, z1_, 900)])
        pts = pts[shapely.contains_xy(reg, pts[:, 0], pts[:, 1])]
        for p in pts[: int(reg.area / (sp * sp))]:
            a = rng.uniform(0, math.pi)
            emit(p, np.array([math.cos(a), math.sin(a)]))


def _telescope_fibres(o, rng):
    """Helical collagen fibres on the exposed wall of each step of the telescoped osteon, alternating in hand."""
    m = Mesh()
    tops = o.tops
    for k in range(o.n):
        y_hi = tops[k]
        y_lo = tops[k + 1] if k + 1 < o.n else H + 0.032
        if y_hi - y_lo < 0.012:
            continue
        r = o.radii[k + 1]
        pitch = (0.75 if k % 2 == 0 else -0.75) * rng.uniform(0.85, 1.15)
        ys = np.linspace(y_lo + 0.003, y_hi - 0.002, 7)
        n_f = int(2 * math.pi * r / 0.012)
        for j in range(n_f):
            th = 2 * math.pi * j / n_f + (ys - ys[0]) * pitch / r
            xy = o.xy(r - 0.0006, th, k + 1)
            path = np.column_stack([xy[:, 0], ys, xy[:, 1]])
            m.extend(tube(path, 0.0019, 4))
    return m


def _haversian_contents(complete):
    art, vein, nerve = Mesh(), Mesh(), Mesh()
    tele = complete[0]
    for o in complete:
        if not o.canal:
            continue
        top = (H + 0.032 * (o.n + 2) + 0.018) if o is tele else H + 0.005
        ys = np.linspace(-0.004, top, int(top / 0.05) + 2)
        base = o.rot * 1.7
        for mesh, ang, off, r in ((art, base, 0.42, 0.0085), (vein, base + 2.7, 0.30, 0.0125),
                                  (nerve, base + 1.3, 0.55, 0.0055)):
            p = o.c + np.array([math.cos(ang), math.sin(ang)]) * o.rc * off
            if not (Z0 + r + 0.004 < p[1] < Z1 - r - 0.004):
                continue
            path = np.column_stack([np.full_like(ys, p[0]), ys, np.full_like(ys, p[1])])
            mesh.extend(tube(path, r, 10))
    return art, vein, nerve


def _plane_path(points, axis, samples=40):
    """A centreline that must lie in a default cut plane: warp it, flatten it onto the plane (world x or z = 0)
    and pull it back, so that after the warp it is sliced exactly down its middle."""
    q = _forward(smooth_path(np.asarray(points, float), samples))
    q[:, axis] = 0.0
    return _inverse(q)


def _sheet(x_lo, x_hi, top, res=48):
    """A closed layer between two x-surfaces over the outer face, from y = 0 up to top(z) (the periosteum)."""
    m = slab(0.0, 1.0, Z0, Z1, lambda A, Z: x_hi(Z) + 0 * A, lambda A, Z: x_lo(Z) + 0 * A, res, gap=0.0)
    out = Mesh()
    for pos, _, idx in m.parts:
        p = pos.astype(np.float64)
        a, xv, z = p[:, 0], p[:, 1], p[:, 2]
        out.add(np.column_stack([xv, a * top(z), z]), idx)
    return orient_outward(out)


def _periosteum(rng):
    cam = _sheet(lambda z: XP - PC + 0 * z, lambda z: XP - 0.0005 + 0 * z, _hp)
    back = _sheet(lambda z: XP - PC - 0.030 + 0 * z, lambda z: XP - PC - 0.0005 + 0 * z, _hf)
    fib = Mesh().extend(back)
    t = np.linspace(0.0, 1.0, 24)
    for _ in range(300):
        ph = rng.uniform(0, 2 * math.pi)
        x_c = XP - PC - 0.030 - rng.uniform(0.004, 0.050)
        if rng.random() < 0.75:                      # most bundles run along the bone
            zc = rng.uniform(Z0 + 0.005, Z1 - 0.005)
            zs = zc + 0.05 * np.sin(2.2 * math.pi * t + ph)
            zs = np.clip(zs, Z0 + 0.006, Z1 - 0.006)
            y1 = float(np.min(_hf(zs))) - rng.uniform(0.0, 0.03)
            ys = rng.uniform(-0.01, 0.2) * (1 - t) + y1 * t
        else:                                        # the rest wind round it
            zs = Z0 + 0.006 + (Z1 - Z0 - 0.012) * t
            y_top = float(np.min(_hf(zs)))
            ys = rng.uniform(0.03, max(y_top - 0.03, 0.05)) + 0.05 * np.sin(2.0 * math.pi * t + ph)
            ys = np.minimum(ys, _hf(zs) - 0.012)
        xs = x_c + 0.012 * np.sin(3.0 * math.pi * t + ph * 1.3)
        fib.extend(tube(np.stack([xs, ys, zs], -1), rng.uniform(0.0065, 0.0115), 7))
    # periosteal artery, vein and nerve running along the bone on the fibrous layer, with small branches
    art, vein, nerve = Mesh(), Mesh(), Mesh()
    xo = XP - PC - 0.030 - 0.064
    for mesh, zc, r, seed in ((art, -0.10, 0.013, 1), (vein, -0.155, 0.019, 2), (nerve, -0.045, 0.009, 3)):
        ys = np.linspace(-0.004, H + 0.005, 40)
        zs = zc + 0.025 * np.sin(ys * 3.1 + seed)
        mesh.extend(tube(np.column_stack([np.full_like(ys, xo - r * 0.3), ys, zs]), r, 12))
        for yb in (0.30 + 0.1 * seed, 0.85 + 0.05 * seed):
            zb = zc + 0.025 * math.sin(yb * 3.1 + seed)
            side = 1 if seed != 2 else -1
            br = smooth_path(np.array([(xo, yb, zb), (xo + 0.005, yb - 0.04, zb + side * 0.10),
                                       (XP - PC - 0.02, yb - 0.10, zb + side * 0.16)]), 16)
            mesh.extend(tube(br, np.linspace(r * 0.6, r * 0.35, len(br)), 8))
    return cam, fib, art, vein, nerve


def _sharpey(rng):
    """Sharpey fibres: in the radial cut plane (world space), crossing the top face where the periosteum reaches it,
    and as torn stubs on the bone surface where the periosteum is peeled back."""
    world, pre = [], []
    for y in np.arange(0.10, H - 0.08, 0.075):
        y0 = y + rng.uniform(-0.02, 0.02)
        pts = [(XP - PC - 0.055, y0 + 0.05, 0.0), (XP - PC * 0.5, y0 + 0.02, 0.0), (XP + 0.045, y0 - 0.02, 0.0),
               (XP + 0.105 + rng.uniform(0, 0.03), y0 - 0.055, 0.0)]
        world.append(pts)
    for z in np.arange(-0.17, -0.02, 0.05):
        z0 = z + rng.uniform(-0.01, 0.01)
        pre.append(smooth_path(np.array([(XP - PC - 0.05, H - 0.0015, z0 + 0.03), (XP - PC * 0.5, H - 0.0015, z0 + 0.01),
                                         (XP + 0.05, H - 0.0015, z0 - 0.01), (XP + 0.11, H - 0.0015, z0 - 0.02)]), 18))
    for _ in range(40):
        z = rng.uniform(Z0 + 0.03, -0.36)
        y = rng.uniform(float(_hp(z)) + 0.02, H - 0.025)
        a = np.array([XP + 0.03, y - 0.02, z])
        b = np.array([XP - 0.030, y + 0.014 + rng.uniform(0, 0.01), z + rng.uniform(-0.01, 0.01)])
        pre.append(smooth_path(np.array([a, (a + b) / 2 + [0, 0.004, 0], b]), 8))
    return world, pre


def _trabecular(rng):
    """Spongy bone and marrow on the inner side, the trabeculae thickening and fusing as they reach the cortex."""
    zmid = np.linspace(Z0, Z1, 50)
    x_lo = float(_xe(zmid).min()) - 0.02
    vol = Volume((x_lo, -0.01, Z0 - 0.01), (XM + 0.01, H + 0.01, Z1 + 0.01), 0.0068)
    x, y, z = vol.axes()
    xe = _xe(z)
    u = _smooth((x - xe) / 0.42)
    # a gyroid lattice with its coordinates pushed around by noise: plates and rods with no visible period
    f = 9.0
    xw = x + 0.10 * fbm3(x * 2.3, y * 2.3, z * 2.3, 1.0, 2, 21)
    yw = y + 0.10 * fbm3(x * 2.3 + 5.1, y * 2.3, z * 2.3 + 1.7, 1.0, 2, 22)
    zw = z + 0.10 * fbm3(x * 2.3 + 2.9, y * 2.3 + 8.3, z * 2.3, 1.0, 2, 23)
    g = np.sin(xw * f) * np.cos(yw * f) + np.sin(yw * f) * np.cos(zw * f) + np.sin(zw * f) * np.cos(xw * f)
    g = g + 0.30 * fbm3(x * 6, y * 6, z * 6, 1.0, 2, 11)
    del xw, yw, zw
    thr = 0.46 - 0.24 * u + 0.9 * (1.0 - _smooth((x - xe) / 0.07))
    d = ((np.abs(g) - thr) * 0.032).astype(np.float32)
    d = np.maximum(d, (xe - 0.004 - x).astype(np.float32))
    # channels for the medullary vessels
    vessel_paths = []
    for zc, xc, r in ((-0.30, 1.16, 0.016), (-0.22, 1.20, 0.028)):
        ys = np.linspace(-0.02, H + 0.02, 30)
        vessel_paths.append((np.column_stack([xc + 0.02 * np.sin(ys * 2.3 + zc), ys, zc + 0.02 * np.cos(ys * 1.7)]), r))
    vol.d = d
    for p, r in vessel_paths:
        vol.tube(p, r + 0.022, "subtract")
    d = vol.d
    # osteoclasts sit in resorption pits on the upper surfaces of trabeculae that stand above the marrow
    top_m = _marrow_top
    clasts = []
    tries = 0
    while len(clasts) < 8 and tries < 400:
        tries += 1
        cx, cz = rng.uniform(XE + 0.12, XM - 0.08), rng.uniform(Z0 + 0.08, Z1 - 0.08)
        ix = int((cx - vol.lo[0]) / vol.voxel)
        iz = int((cz - vol.lo[2]) / vol.voxel)
        col = d[ix, :, iz]
        ys = vol.lo[1] + np.arange(len(col)) * vol.voxel
        above = ys > float(top_m(np.array(cx), np.array(cz))) + 0.03
        inside = np.flatnonzero((col < 0) & above & (ys < H - 0.05))
        if not len(inside):
            continue
        j = inside[-1]
        if col[min(j + 3, len(col) - 1)] < 0.004:
            continue
        cy = float(ys[j])
        if any(np.linalg.norm(np.array([cx, cy, cz]) - c) < 0.15 for c in clasts):
            continue
        clasts.append(np.array([cx, cy, cz]))
    for c in clasts:
        vol.add(sdf_ellipsoid(c + [0, 0.004, 0], (0.034, 0.013, 0.028)), "subtract")
    d_tr = vol.d.copy()
    vol.intersect_box((x_lo, 0.0, Z0), (XM, H - 0.003, Z1))
    trab = _drop_islands(vol.mesh(0.9, step=2))
    # marrow: the complement of the trabeculae, scooped down so the upper trabeculae stand free
    m = vol.copy(-d_tr + 0.0025)
    mx, my, mz = m.axes()
    np.maximum(m.d, (_xe(mz) + 0.011 - mx).astype(np.float32), out=m.d)
    np.maximum(m.d, (my - top_m(mx, mz)).astype(np.float32), out=m.d)
    for p, r in vessel_paths:
        m.tube(p, r + 0.004, "subtract")
    # the marrow stops short of the cut faces of the block, so the trabeculae stand proud of it like a sponge
    inset = (INSET + 0.02 * fbm3(mx * 4.0, my * 4.0, mz * 4.0, 1.0, 2, 93)).astype(np.float32)
    np.maximum(m.d, Z0 + inset - mz, out=m.d)
    np.maximum(m.d, mz - (Z1 - inset), out=m.d)
    np.maximum(m.d, mx - (XM - inset), out=m.d)
    m.intersect_box((x_lo, 0.0, Z0), (XM, H, Z1))
    marrow = _drop_islands(m.mesh(0.7, step=2))
    return trab, marrow, clasts, vessel_paths, d_tr, vol


def _marrow_top(x, z):
    x, z = np.asarray(x, float), np.asarray(z, float)
    return H - 0.11 - 0.05 * _smooth((x - XE - 0.05) / 0.3) + 0.035 * fbm3(x * 3.0, 0.7, z * 3.0, 1.0, 2, 91)


def _bone_cells(trab, clasts, rng):
    """Osteoblasts in forming patches and flat lining cells elsewhere, on trabecular surfaces above the marrow."""
    def mask(p, n):
        return (p[:, 1] > _marrow_top(p[:, 0], p[:, 2]) - 0.005) & (p[:, 1] < H - 0.012) & \
               (p[:, 2] > Z0 + 0.01) & (p[:, 2] < Z1 - 0.01) & (p[:, 0] < XM - 0.01)
    pts, nrm = sample_surface(trab, 0.021, seed=611, mask=mask)
    if len(clasts):
        cl = np.array(clasts)
        far = np.min(np.linalg.norm(pts[:, None] - cl[None], axis=2), axis=1) > 0.05
        pts, nrm = pts[far], nrm[far]
    patch = fbm3(pts[:, 0] * 5.0, pts[:, 1] * 5.0, pts[:, 2] * 5.0, 1.0, 2, 77) > 0.12
    helper = np.where(np.abs(nrm[:, 1:2]) < 0.9, [[0.0, 1.0, 0.0]], [[1.0, 0.0, 0.0]])
    t1 = np.cross(nrm, helper)
    t1 /= np.maximum(np.linalg.norm(t1, axis=1, keepdims=True), 1e-9)
    ob = _ellipsoids(pts[patch] + nrm[patch] * 0.004, t1[patch], nrm[patch],
                     np.tile([0.0085, 0.0075, 0.0080], (int(patch.sum()), 1)), 4)
    lc = _ellipsoids(pts[~patch] + nrm[~patch] * 0.0005, t1[~patch], nrm[~patch],
                     np.tile([0.0120, 0.0024, 0.0100], (int((~patch).sum()), 1)), 4)
    oc = Mesh()
    for c in clasts:
        for k in range(3):
            off = np.array([rng.uniform(-0.014, 0.014), 0.006 + rng.uniform(0, 0.004), rng.uniform(-0.012, 0.012)])
            oc.extend(ellipsoid_mesh(c + off, (0.022 + 0.004 * k, 0.012, 0.018), 10))
    return ob, lc, oc


def _adipocytes(d_tr, vol, rng):
    cen, rad = [], []
    for _ in range(3000):
        if len(cen) >= 110:
            break
        p = np.array([rng.uniform(XE + 0.06, XM - 0.02), rng.uniform(0.02, H - 0.1), rng.uniform(Z0 + 0.01, Z1 - 0.01)])
        r = rng.uniform(0.034, 0.054)
        # distance inside each free surface of the marrow: its scooped top and the faces it stops short of
        depth = min(float(_marrow_top(p[0], p[2])) - p[1], p[2] - Z0 - INSET, Z1 - INSET - p[2], XM - INSET - p[0])
        if depth < -0.25 * r:
            continue
        # keep fat cells where they will be seen: bulging from the marrow's surfaces, or in the cut plane
        if not (depth < 0.45 * r or abs(p[2]) < r * 0.9):
            continue
        i = np.clip(((p - vol.lo) / vol.voxel).astype(int), 0, np.array(d_tr.shape) - 1)
        if d_tr[tuple(i)] < r * 0.8:
            continue
        if any(np.linalg.norm(p - q) < (r + s) * 0.95 for q, s in zip(cen, rad)):
            continue
        cen.append(p)
        rad.append(r)
    cen = np.array(cen).reshape(-1, 3)
    rr = np.array(rad)
    radii = np.column_stack([rr, rr * 0.92, rr * 0.96])
    return _ellipsoids(cen, np.tile([1.0, 0, 0], (len(cen), 1)), np.tile([0, 1.0, 0], (len(cen), 1)), radii, 7)


def _channels(complete):
    """Volkmann canals that the default cut-away slices lengthwise, as (centre line in x-z, height, half-width).
    They are carved out of the lamellae as real channels, so the cut shows an open canal crossing the lamellae."""
    by_pos = {tuple(np.round(o.c, 3)): o for o in complete}
    c1, c2, c3 = by_pos.get((-0.47, 0.0)), by_pos.get((-0.13, 0.012)), by_pos.get((0.0, 0.33))
    out = []
    if c1 is not None:
        out.append((LineString([(XP - 0.006, 0.0), (c1.c[0], c1.c[1])]), 0.80, 0.021))
    if c1 is not None and c2 is not None:
        out.append((LineString([(c1.c[0], c1.c[1]), (c2.c[0], c2.c[1])]), 0.47, 0.020))
    if c3 is not None:
        out.append((LineString([(c3.c[0], c3.c[1]), (c3.c[0] + 0.01, Z1 + 0.01)]), 0.66, 0.020))
    return out


def _carved(poly, top, channels):
    """Extrude a piece of the mosaic, leaving out any Volkmann channel that runs through it: the prism is split
    into layers along the bone, and the layers at a channel's height lose its (stepped, roughly round) footprint."""
    cuts = []
    for line, yc, hw in channels:
        if not poly.intersects(line.buffer(hw)):
            continue
        for (ya, yb), w in (((yc - hw, yc - 0.55 * hw), 0.72 * hw), ((yc - 0.55 * hw, yc + 0.55 * hw), hw),
                            ((yc + 0.55 * hw, yc + hw), 0.72 * hw)):
            cuts.append((ya, yb, line.buffer(w, cap_style="flat")))
    if not cuts:
        return _extrude(poly, top)
    ys = sorted({0.0, top, *[c[0] for c in cuts], *[c[1] for c in cuts]})
    ys = [y for y in ys if 0.0 <= y <= top]
    layers = []
    for ya, yb in zip(ys[:-1], ys[1:]):
        mid = 0.5 * (ya + yb)
        g = poly
        for ca, cb, fp in cuts:
            if ca < mid < cb:
                g = g.difference(fp)
        layers.append((ya, yb, g))
    # a channel can split a piece in two for part of its height: each connected part becomes its own stack
    m = Mesh()
    comps = _polys(poly)
    for comp in comps:
        sub = []
        for ya, yb, g in layers:
            gg = g.intersection(comp) if len(comps) > 1 else g
            sub.append((ya, yb, gg))
        m.extend(_stack_multi(sub))
    return m


def _stack_multi(layers):
    """_stack for layers that may be several polygons (a channel cut straight through a lamella)."""
    parts = [_polys(g, 1e-7) for _, _, g in layers]
    if all(len(p) == 1 for p in parts):
        return _stack([(a, b, p[0]) for (a, b, _), p in zip(layers, parts)])
    # fall back: walls per polygon, caps from the differences, all in one mesh
    items = Mesh()
    for i, ((y0, y1, g), ps) in enumerate(zip(layers, parts)):
        for p in ps:
            for pos, idx in _walls(p, y0, y1):
                items.add(pos, idx)
        below = layers[i - 1][2] if i > 0 else None
        above = layers[i + 1][2] if i + 1 < len(layers) else None
        for cap_g, y, up in ((g if above is None else g.difference(above), y1, True),
                             (g if below is None else g.difference(below), y0, False)):
            for p in _polys(cap_g, 1e-9):
                pos, idx = _cap(p, y, up)
                if len(idx):
                    items.add(pos, idx)
    return items


def build_osteon():
    rng = np.random.default_rng(8)
    complete, old = _layout(rng)
    pieces, block = _mosaic(complete, old)
    tele = complete[0]
    vk_top = _volkmann_top(complete, rng)
    pieces = _groove(pieces, vk_top)

    channels = _channels(complete)
    groups = {}
    for pc in pieces:
        groups.setdefault((pc["key"], round(pc["top"], 5)), []).append(pc["geom"])
    solids = {}
    for (key, top), geoms in groups.items():
        m = solids.setdefault(key, Mesh())
        # a hair's gap between neighbouring solids, so a cut face never shows two coincident walls fighting
        g = unary_union(geoms).buffer(-GAP, join_style="mitre")
        for p in _polys(g):
            m.extend(_carved(shapely.segmentize(p, 0.02), top, channels))

    meshes = {k: v for k, v in solids.items()}
    art, vein, nerve = _haversian_contents(complete)
    meshes["h_art"], meshes["h_vein"], meshes["h_nerve"] = art, vein, nerve
    meshes["fibres"] = _telescope_fibres(tele, rng)

    # osteocytes & canaliculi on the transverse face and the two longitudinal faces of the block (pre-warp)
    lac = _Lacunae(rng)
    _lacunae_top(lac, pieces, complete, old, rng)
    for zf, nrm in ((Z1 - 0.0008, (0.0, 0.0, 1.0)), (Z0 + 0.0008, (0.0, 0.0, -1.0))):
        _plane_lacunae(lac, pieces, (XP + 0.002, zf), (float(_xe(zf)) - 0.002, zf), np.array(nrm), False, rng)
    meshes["lac"], meshes["can"] = lac.meshes()

    # Volkmann canals: on the top face (in the grooves), in the radial cut plane z' = 0, in the tangential cut
    # plane x' = 0, and a few hidden ones for when the cut planes are moved
    vk, vkv = Mesh(), Mesh()
    for p in vk_top:
        path = np.column_stack([p[:, 0], np.full(len(p), H - 0.0125), p[:, 1]])
        vkv.extend(tube(path, 0.0085, 10))
    for line, yc, hw in channels:
        c = np.asarray(line.coords)
        ends = np.array([[c[0, 0], yc, c[0, 1]], [c[-1, 0], yc, c[-1, 1]]])
        path = np.linspace(ends[0], ends[1], 30)
        vk.extend(tube_shell(path, hw * 0.72, hw * 0.64, 16))
        vkv.extend(tube(path, 0.0085, 10))
    hidden = [((0.25, 0.30, 0.25), (0.45, 0.36, 0.05)), ((0.40, 0.95, -0.40), (XE + 0.05, 0.90, -0.42)),
              ((-0.50, 0.25, -0.30), (XP - 0.01, 0.22, -0.34))]
    for a, b in hidden:
        path = smooth_path(np.array([a, (np.add(a, b) / 2) + [0, 0.02, 0], b]), 24)
        vk.extend(tube(path, 0.020, 12))
        vkv.extend(tube(path, 0.008, 8))
    # Volkmann foramina on the bone surface where the periosteum is peeled back
    for z, y in ((-0.44, 1.14), (-0.52, 1.20)):
        path = np.array([(XP + 0.12, y - 0.03, z + 0.02), (XP + 0.05, y - 0.01, z + 0.01), (XP - 0.004, y, z)])
        vk.extend(tube(smooth_path(path, 12), 0.018, 14))
        vkv.extend(tube(smooth_path(path, 12), 0.007, 8))
    meshes["volkmann"], meshes["vk_vessels"] = vk, vkv

    cam, fib, p_art, p_vein, p_nerve = _periosteum(rng)
    meshes.update(cambium=cam, fibrous=fib, p_art=p_art, p_vein=p_vein, p_nerve=p_nerve)
    sh_world, sh_pre = _sharpey(rng)
    sh = Mesh()
    for p in sh_pre:
        sh.extend(tube(p, np.linspace(0.0052, 0.0040, len(p)), 7))
    for pts in sh_world:
        path = _plane_path(pts, 2, 20)
        sh.extend(tube(path, np.linspace(0.0055, 0.0035, len(path)), 7))
    meshes["sharpey"] = sh

    trab, marrow, clasts, vpaths, d_tr, vol = _trabecular(rng)
    ob, lc, oc = _bone_cells(trab, clasts, rng)
    meshes.update(trab=trab, marrow=marrow, osteoblasts=ob, lining=lc, osteoclasts=oc)
    meshes["adipocytes"] = _adipocytes(d_tr, vol, rng)
    meshes["m_art"] = tube(vpaths[0][0], vpaths[0][1], 12)
    meshes["m_vein"] = tube(vpaths[1][0], vpaths[1][1], 14)

    meshes = {k: _warp_mesh(v) for k, v in meshes.items()}
    # lacunae exactly in the default cut planes, placed in world space after the warp
    lac = _Lacunae(rng)
    _plane_lacunae(lac, pieces, (0.0, 0.0), (0.0, Z1), np.array([1.0, 0.0, 0.0]), True, rng)
    _plane_lacunae(lac, pieces, (XP + 0.002, 0.0), (0.0, 0.0), np.array([0.0, 0.0, 1.0]), True, rng)
    l2, c2_ = lac.meshes()
    meshes["lac"].extend(l2)
    meshes["can"].extend(c2_)

    spec = [
        # key, name, group, colour, description, category, rank, detail, label
        ("canal", "Central (Haversian) canals", "Osteons", "#c27c69", D["canal"], "fascia", 1.3, (0.1, 120.0, 0.8, 2)),
        ("h_art", "Haversian arterioles & capillaries", "Osteons", "#c8302a", D["h_art"], "artery", 1.4, None),
        ("h_vein", "Haversian venules", "Osteons", "#4460a8", D["h_vein"], "vein", 1.4, None),
        ("h_nerve", "Haversian nerve fibres", "Osteons", "#e6c34a", D["h_nerve"], "nerve", 1.4, None),
        ("lamA", "Concentric lamellae (set A)", "Osteons", "#efe5cc", D["lamellae"], "bone", 1.0,
         (0.05, 0.0, 0.0, 0)),
        ("lamB", "Concentric lamellae (set B)", "Osteons", "#d6c49f", D["lamellae"], "bone", 1.0,
         (0.05, 0.0, 0.0, 0)),
        ("cement", "Cement lines", "Osteons", "#8a7c9c", D["cement"], "bone", 1.05, (0.04, 0.0, 0.0, 0)),
        ("fibres", "Lamellar collagen fibres (telescoped osteon)", "Osteons", "#f6efe0", D["fibres"], "ligament",
         1.1, (0.05, 0.0, 0.0, 0)),
        ("lac", "Osteocytes in lacunae", "Osteons", "#5a3a2d", D["osteocytes"], "nucleus", 1.15,
         (0.03, 0.0, 0.0, 0)),
        ("can", "Canaliculi", "Osteons", "#957563", D["canaliculi"], "nucleus", 1.15, (0.02, 0.0, 0.0, 0)),
        ("volkmann", "Perforating (Volkmann) canals", "Canals", "#ae6a5b", D["volkmann"], "fascia", 1.2,
         (0.1, 120.0, 0.8, 0)),
        ("vk_vessels", "Volkmann canal vessels", "Canals", "#c8302a", D["volk_vessels"], "artery", 1.25, None),
        ("inter", "Interstitial lamellae", "Lamellar systems", "#d8c49a", D["interstitial"], "bone", 0.0,
         (0.09, 0.0, 0.0, 0)),
        ("ocirc", "Outer circumferential lamellae", "Lamellar systems", "#e9dec4", D["ocirc"], "bone", 0.5,
         (0.06, 0.0, 0.0, 0)),
        ("icirc", "Inner circumferential lamellae", "Lamellar systems", "#e4d6b6", D["icirc"], "bone", -0.5,
         (0.06, 0.0, 0.0, 0)),
        ("cambium", "Periosteum – cambium (osteogenic) layer", "Periosteum", "#c98579", D["cambium"], "fascia",
         2.2, (0.1, 150.0, 0.9, 0)),
        ("fibrous", "Periosteum – fibrous layer", "Periosteum", "#d7b595", D["fibrous"], "ligament", 2.4,
         (0.12, 55.0, 0.15, 2)),
        ("sharpey", "Sharpey fibres", "Periosteum", "#f4ecda", D["sharpey"], "ligament", 2.3, None),
        ("p_art", "Periosteal artery", "Periosteum", "#c8302a", D["p_art"], "artery", 2.6, None),
        ("p_vein", "Periosteal vein", "Periosteum", "#4460a8", D["p_vein"], "vein", 2.6, None),
        ("p_nerve", "Periosteal nerve", "Periosteum", "#e6c34a", D["p_nerve"], "nerve", 2.6, None),
        ("endo", "Endosteum", "Endosteum & marrow", "#c98a7b", D["endosteum"], "fascia", -1.0,
         (0.1, 150.0, 0.9, 0)),
        ("osteoblasts", "Osteoblasts", "Endosteum & marrow", "#8a74a3", D["osteoblasts"], "nucleus", -1.4, None),
        ("lining", "Bone-lining cells", "Endosteum & marrow", "#d4ad9c", D["lining"], "fascia", -1.4, None),
        ("osteoclasts", "Osteoclasts (Howship lacunae)", "Endosteum & marrow", "#c46e92", D["osteoclasts"],
         "nucleus", -1.5, (0.1, 60.0, 0.9, 0)),
        ("trab", "Trabeculae (spongy bone)", "Endosteum & marrow", "#e3d5b7", D["trabeculae"], "bone", -1.2,
         (0.08, 45.0, 0.35, 0)),
        ("marrow", "Red marrow", "Endosteum & marrow", "#7f2d2b", D["marrow"], "lymph", -2.2,
         (0.12, 220.0, 0.95, 0)),
        ("adipocytes", "Marrow adipocytes", "Endosteum & marrow", "#eadba2", D["adipocytes"], "fat", -2.0, None),
        ("m_art", "Nutrient artery branch", "Endosteum & marrow", "#c8302a", D["m_art"], "artery", -2.4, None),
        ("m_vein", "Marrow sinusoid & central vein", "Endosteum & marrow", "#4460a8", D["m_vein"], "vein", -2.4,
         None),
    ]
    parts = []
    for key, name, group, color, desc, cat, rank, detail in spec:
        m = meshes.get(key)
        if m is None or not m.parts:
            continue
        parts.append(mesh_part(m, name, group, color, desc, cat, rank=rank, detail=detail,
                               label=key not in ("can", "lining", "fibres")))
    return parts
