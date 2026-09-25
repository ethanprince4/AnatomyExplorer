"""Tooth structure: a lower first molar in mesiodistal section in its socket, and the four adult tooth types.

1 unit = 1 cm. x runs mesiodistally (mesial -x), y up with the cementoenamel junction at y = 0, z buccolingually
(buccal +z). The molar, its periodontium and the block of mandible are cut at z = 0 and the lingual half kept, so
the section faces the viewer. Everything is a signed-distance field: the outer surface of the tooth, T, is built
once from the crown (a superellipse whose width follows the crown's profile, capped by cusps) and the two roots
(tapered, buccolingually flattened cones), and every tissue is a band of T - enamel and cementum are offsets inside
it, periodontal ligament and lamina dura offsets outside it - so the layers nest exactly."""
import numpy as np
from scipy.interpolate import PchipInterpolator

from .base import Part
from .geometry import Mesh
from .sdf import BIG, Volume, fbm3, round_cone

G_MOLAR = "Molar in section"
G_PERIO = "Periodontium & jaw"
G_NV = "Nerves & vessels"
G_TYPES = "Adult tooth types"


# =============================================================================== helpers
def _ss(x, a, b):
    t = np.clip((np.asarray(x, np.float32) - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b + (a - b) * h - k * h * (1.0 - h)


class _Grid:
    """A voxel grid on which several fields are evaluated once and every part is cut from them."""

    def __init__(self, lo, hi, voxel):
        self.v = Volume(lo, hi, voxel)
        self.x, self.y, self.z = self.v.axes()
        self.shape = self.v.shape

    def mesh(self, d, smooth=0.8):
        d = np.ascontiguousarray(np.broadcast_to(np.asarray(d, np.float32), self.shape), dtype=np.float32)
        inside = d < 0.0
        if not inside.any():
            return Mesh()
        sl = []
        for ax in range(3):
            other = tuple(a for a in range(3) if a != ax)
            idx = np.where(inside.any(axis=other))[0]
            sl.append(slice(max(int(idx[0]) - 5, 0), min(int(idx[-1]) + 6, self.shape[ax])))
        sub = Volume.__new__(Volume)
        sub.voxel = self.v.voxel
        sub.lo = self.v.lo + np.array([s.start for s in sl]) * self.v.voxel
        sub.d = d[tuple(sl)].copy()
        sub.shape = sub.d.shape
        sub._slices = None
        return sub.mesh(smooth)


def _capsules(x, y, z, paths, radii):
    shape = (x.shape[0], y.shape[1], z.shape[2])
    out = np.full(shape, BIG, np.float32)
    ax = (x.ravel(), y.ravel(), z.ravel())
    for path, rad in zip(paths, radii):
        path = np.asarray(path, np.float32)
        rad = np.broadcast_to(np.asarray(rad, np.float32), (len(path),))
        for i in range(len(path) - 1):
            fn, bmin, bmax = round_cone(path[i], path[i + 1], float(rad[i]), float(rad[i + 1]))
            sl = []
            for a, lo, hi in zip(ax, np.asarray(bmin) - 0.02, np.asarray(bmax) + 0.02):
                i0, i1 = int(np.searchsorted(a, lo)), int(np.searchsorted(a, hi, "right"))
                sl.append(slice(i0, i1))
            if any(s.stop <= s.start for s in sl):
                continue
            sl = tuple(sl)
            d = fn(x[sl[0]], y[:, sl[1]], z[:, :, sl[2]])
            np.minimum(out[sl], d, out=out[sl])
    return out


def _smooth(path, n):
    p = np.asarray(path, float)
    p = np.vstack([2 * p[0] - p[1], p, 2 * p[-1] - p[-2]])
    out = []
    for i in range(1, len(p) - 2):
        for t in np.linspace(0, 1, n, endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p[i]) + (-p[i - 1] + p[i + 1]) * t
                              + (2 * p[i - 1] - 5 * p[i] + 4 * p[i + 1] - p[i + 2]) * t2
                              + (-p[i - 1] + 3 * p[i] - 3 * p[i + 1] + p[i + 2]) * t3))
    out.append(p[-2])
    return np.array(out)


def _superellipse(x, z, a, b, p):
    q = (np.abs(x / a) ** p + np.abs(z / b) ** p) ** (1.0 / p)
    return (q - 1.0) * np.minimum(a, b)


def _cone(x, y, z, top, apex, r0, r1, zscale):
    """A root: a tapered cone from `top` to `apex` (x, y), flattened mesiodistally (broad buccolingually)."""
    fn, _, _ = round_cone((top[0], top[1], 0.0), (apex[0], apex[1], 0.0), r0, r1)
    return fn(x, y, z / zscale)


# =============================================================================== the molar
_CA = PchipInterpolator([-0.15, 0.0, 0.2, 0.4, 0.55, 0.7, 0.85], [0.42, 0.43, 0.53, 0.555, 0.53, 0.45, 0.33])
_CB = PchipInterpolator([-0.15, 0.0, 0.15, 0.4, 0.55, 0.7, 0.85], [0.37, 0.38, 0.47, 0.46, 0.42, 0.33, 0.24])
CUSPS = ((-0.3, 0.26, 0.0), (0.05, 0.29, -0.01), (0.37, 0.16, -0.035), (-0.27, -0.25, 0.02), (0.13, -0.26, 0.02))
ROOTS = (((-0.27, -0.18), (-0.23, -0.8), (-0.18, -1.4)), ((0.28, -0.18), (0.31, -0.75), (0.36, -1.3)))
Y_CREST = -0.15
PDL, LAM = 0.03, 0.036


def _occlusal(x, z):
    h = 0.56
    for cx, cz, dh in CUSPS:
        h = h + (0.14 + dh) * np.exp(-((x - cx) / 0.15) ** 2 - ((z - cz) / 0.28) ** 2)
    h = h - 0.03 * np.exp(-(z / 0.05) ** 2) * (1.0 - _ss(np.abs(x), 0.36, 0.5))     # central groove
    return h


def _molar(x, y, z):
    """Outer surface of a lower first molar (negative inside)."""
    yc = np.clip(y, -0.15, 0.85)
    crown = np.maximum(_superellipse(x, z, _CA(yc), _CB(yc), 2.6) * 0.95, (y - _occlusal(x, z)) * 0.85)
    crown = np.maximum(crown, -0.12 - y)
    trunk = np.maximum(_superellipse(x, z, 0.43 - 0.05 * _ss(-y, 0.0, 0.4), 0.385 - 0.02 * _ss(-y, 0.0, 0.4), 2.4),
                       np.maximum(y - 0.05, (-0.33 - 0.2 * (x / 0.43) ** 2) - y))     # arched furcation
    roots = None
    for top, mid, apex in ROOTS:
        r = np.minimum(_cone(x, y, z, top, mid, 0.165, 0.12, 2.15), _cone(x, y, z, mid, apex, 0.12, 0.05, 2.15))
        roots = r if roots is None else np.minimum(roots, r)
    return _smin(_smin(crown, trunk, 0.05), roots, 0.09)


def _molar_pulp(x, y, z):
    q = np.sqrt((x / 0.25) ** 2 + ((y - 0.1) / 0.115) ** 2 + (z / 0.19) ** 2)
    ch = (q - 1.0) * 0.115
    horns = []
    for cx, cz, _ in CUSPS:
        horns.append(((cx * 0.62, 0.12, cz * 0.1), (cx * 0.76, 0.35, cz * 0.12)))
    h = _capsules(x, y, z, horns, [[0.065, 0.03]] * len(horns))
    canals = []
    for top, mid, apex in ROOTS:
        canals.append([(top[0] * 0.8, 0.02, 0.0), (top[0] * 0.97, -0.25, 0.0), (mid[0], mid[1], 0.0),
                       (apex[0], apex[1], 0.0), (apex[0] + 0.004, apex[1] - 0.08, 0.0)])
    c = _capsules(x, y, z / 1.3, canals, [[0.07, 0.045, 0.032, 0.015, 0.015]] * 2)
    return _smin(_smin(ch, h, 0.04), c, 0.05)


def _enamel_t(y):
    return 0.2 * _ss(y, 0.0, 0.5) + 0.012 * _ss(y, 0.0, 0.05)


def _cement_t(y):
    return (0.028 + 0.03 * _ss(-y, 0.9, 1.4)) * _ss(-y, 0.0, 0.06)


def _apices():
    return [np.array([apex[0], apex[1] - 0.03, 0.0]) for _, _, apex in ROOTS]


# =============================================================================== the jaw
_BW = PchipInterpolator([-2.9, -2.4, -1.6, -0.9, -0.4, -0.1], [0.6, 0.68, 0.67, 0.62, 0.56, 0.53])
Y_CANAL = -1.95
X_HALF = 0.78


def _crest(x, z):
    return Y_CREST - 0.28 * _ss(np.abs(z), 0.44, 0.75) - 0.07 * _ss(np.abs(x), 0.52, X_HALF)


def _body(x, y, z):
    w = _BW(np.clip(y, -2.9, -0.1))
    bottom = -2.72 + 0.3 * (np.abs(z) / 0.68) ** 4
    d = np.maximum(np.abs(z) - w, np.maximum(y - _crest(x, z), bottom - y))
    return np.maximum(d, np.abs(x) - X_HALF)


def _body_inner(x, y, z):
    w = _BW(np.clip(y, -2.9, -0.1))
    bottom = -2.72 + 0.3 * (np.abs(z) / 0.68) ** 4 + 0.22
    d = np.maximum(np.abs(z) - (w - 0.075), np.maximum(y - (_crest(x, z) - 0.04), bottom - y))
    return np.maximum(d, np.abs(x) - X_HALF - 0.01)


def _nv_paths():
    """Inferior alveolar nerve, artery and vein along the mandibular canal, each sending a branch up through the
    bone and the apical foramen of each root and on through the root canal into the pulp chamber and horns."""
    out = {}
    for name, dy, dx in (("nerve", 0.02, 0.0), ("artery", 0.085, 0.016), ("vein", -0.05, -0.016)):
        paths = [np.array([(-X_HALF - 0.02, Y_CANAL + dy, 0.0), (X_HALF + 0.02, Y_CANAL + dy, 0.0)])]
        for (top, mid, apex), horn_x in zip(ROOTS, ((-0.28, -0.26), (0.09, 0.36))):
            ctrl = [(apex[0] - 0.2 + dx, Y_CANAL + dy + 0.02, 0.0), (apex[0] - 0.05 + dx, -1.62, 0.0),
                    (apex[0] + dx * 0.25, apex[1] - 0.1, 0.0), (apex[0], apex[1] + 0.03, 0.0),
                    (mid[0] + dx * 0.6, mid[1], 0.0), (top[0] * 0.95 + dx, -0.02, 0.0),
                    (top[0] * 0.7 + dx, 0.12, 0.0)]
            paths.append(_smooth(ctrl, 6))
            for hx in horn_x:
                paths.append(_smooth([(top[0] * 0.7 + dx, 0.12, 0.0), (hx * 0.9, 0.22, 0.0),
                                      (hx * 0.78, 0.285 - abs(dx), 0.0)], 5))
        out[name] = paths
    return out


# =============================================================================== the tooth types
def _types():
    """(name, local SDF, x position, description of the type) for the line-up."""
    def incisor(x, y, z):
        yc = np.clip(y, -0.1, 0.95)
        a = np.interp(yc, [-0.1, 0.0, 0.5, 0.95], [0.17, 0.18, 0.26, 0.27])
        b = np.interp(yc, [-0.1, 0.0, 0.25, 0.6, 0.95], [0.27, 0.28, 0.3, 0.18, 0.05])
        crown = np.maximum(_superellipse(x, z, a, b, 2.3), (y - 0.92 - 0.02 * np.cos(x * 6)) * 0.8)
        root = np.minimum(_cone(x, y, z, (0.0, 0.0), (0.01, -0.7), 0.18, 0.13, 1.6),
                          _cone(x, y, z, (0.01, -0.7), (0.05, -1.2), 0.13, 0.035, 1.6))
        return _smin(np.maximum(crown, -0.02 - y), root, 0.06)

    def canine(x, y, z):
        yc = np.clip(y, -0.1, 1.1)
        a = np.interp(yc, [-0.1, 0.0, 0.45, 0.85, 1.1], [0.25, 0.26, 0.35, 0.26, 0.06])
        b = np.interp(yc, [-0.1, 0.0, 0.3, 0.8, 1.1], [0.32, 0.33, 0.38, 0.23, 0.08])
        crown = np.maximum(_superellipse(x, z, a, b, 2.3), (y - (1.1 - 0.75 * np.abs(x + 0.02))) * 0.7)
        root = np.minimum(_cone(x, y, z, (0.0, 0.0), (0.01, -0.9), 0.26, 0.19, 1.3),
                          _cone(x, y, z, (0.01, -0.9), (0.07, -1.6), 0.19, 0.04, 1.3))
        return _smin(np.maximum(crown, -0.02 - y), root, 0.06)

    def premolar(x, y, z):
        yc = np.clip(y, -0.1, 0.9)
        a = np.interp(yc, [-0.1, 0.0, 0.35, 0.65, 0.9], [0.23, 0.24, 0.35, 0.33, 0.2])
        b = np.interp(yc, [-0.1, 0.0, 0.3, 0.6, 0.9], [0.29, 0.3, 0.38, 0.33, 0.2])
        top = (0.5 + 0.36 * np.exp(-(x / 0.2) ** 2 - ((z - 0.12) / 0.25) ** 2)
               + 0.13 * np.exp(-(x / 0.18) ** 2 - ((z + 0.2) / 0.14) ** 2))
        crown = np.maximum(_superellipse(x, z, a, b, 2.4), (y - top) * 0.8)
        root = np.minimum(_cone(x, y, z, (0.0, 0.0), (0.01, -0.8), 0.24, 0.17, 1.25),
                          _cone(x, y, z, (0.01, -0.8), (0.06, -1.4), 0.17, 0.04, 1.25))
        return _smin(np.maximum(crown, -0.02 - y), root, 0.06)

    return [
        ("Incisor", incisor, 1.28,
         "Incisors (8 in the adult, 2 per quadrant – central and lateral): chisel-shaped crowns with a straight "
         "incisal edge for cutting and nipping food, and a single conical root. Lower central incisors are the "
         "first deciduous teeth to erupt (~6–8 months) and the permanent ones erupt at 6–7 years."),
        ("Canine", canine, 1.78,
         "Canines (cuspids, 4 in the adult): a single pointed cusp for piercing and tearing and the longest root "
         "of any tooth (the upper canine's reaches up beside the nose – 'eye tooth'), which makes it a stable "
         "anchor at the corner of the arch."),
        ("Premolar", premolar, 2.32,
         "Premolars (bicuspids, 8 in the adult, 2 per quadrant): a large buccal and a smaller lingual cusp for "
         "crushing and grinding; usually one root (the upper first premolar often two). There are no deciduous "
         "premolars – they replace the deciduous molars."),
        ("Molar", lambda x, y, z: _molar(x, y, z), 2.95,
         "Molars (12 in the adult including the four third molars or wisdom teeth): broad occlusal surfaces with "
         "3–5 cusps for grinding; lower molars have two roots (mesial and distal), upper molars three (two buccal, "
         "one palatal). First permanent molars erupt at ~6 years behind the deciduous teeth – often mistaken for "
         "milk teeth – and third molars at 17–21 years, often impacted.")]


# =============================================================================== build
def build_tooth():
    parts = []

    def add(mesh, name, group, color, desc, cat, offset=None):
        if offset is not None and mesh.parts:
            mesh = mesh.transformed(offset=offset)
        parts.append(Part(name, "Tooth – " + group, color, mesh, desc, category=cat))

    # ---- the molar and its periodontium on a fine grid
    g = _Grid((-0.62, -1.52, -0.52), (0.62, 0.8, 0.008), 0.0095)
    x, y, z = g.x, g.y, g.z
    T = _molar(x, y, z)
    P = np.maximum(_molar_pulp(x, y, z), T)
    nv = _nv_paths()
    nv_d = {k: _capsules(x, y, z, v, [{"nerve": 0.013, "artery": 0.009, "vein": 0.011}[k]] * len(v))
            for k, v in nv.items()}
    nv_all = np.minimum(np.minimum(nv_d["nerve"], nv_d["artery"]), nv_d["vein"])
    off = np.where(y > 0, _enamel_t(y), _cement_t(y))
    cut = z                                           # section plane: keep z <= 0
    apex_d = np.full(g.shape, BIG, np.float32)
    for a in _apices():
        apex_d = np.minimum(apex_d, np.sqrt((x - a[0]) ** 2 + (y - a[1]) ** 2 + (z - a[2]) ** 2) - 0.075)

    def sect(d):
        return np.maximum(np.maximum(d, cut), -(nv_all - 0.0015))

    enamel = sect(np.maximum(np.maximum(T, -(T + off)), -y))
    cement = sect(np.maximum(np.maximum(np.maximum(T, -(T + off)), y), -P))
    dentin = sect(np.maximum(T + off, -P))
    add(g.mesh(enamel), "Enamel", G_MOLAR, "#e9edf0",
        "The hardest substance in the body: ~96 % hydroxyapatite in long prisms (rods), secreted by ameloblasts "
        "that are lost when the tooth erupts – so enamel cannot regrow. It covers the crown (the part above the "
        "gum), is thickest over the cusps (~2.5 mm) and thins to nothing at the neck, where it meets cementum at "
        "the cementoenamel junction (cervical line). Acid from plaque bacteria dissolves it (caries); fluoride "
        "converts it to more resistant fluorapatite.", "bone")
    add(g.mesh(dentin), "Dentin", G_MOLAR, "#ead6a2",
        "Bone-like tissue (~70 % mineral) forming the bulk of the tooth, under enamel in the crown and cementum on "
        "the root. It is pierced by dentinal tubules containing processes of the odontoblasts that line the pulp, "
        "so it is living and sensitive: exposed dentin (recession, worn enamel) hurts with cold and sweet "
        "(hydrodynamic theory), and odontoblasts lay down secondary and reparative dentin throughout life, "
        "slowly narrowing the pulp.", "bone")
    add(g.mesh(sect(np.maximum(P, -0.07 - y))), "Pulp chamber (coronal pulp)", G_MOLAR, "#df7c88",
        "Soft connective tissue in the pulp cavity of the crown, with horns reaching up under each cusp. Odontoblasts "
        "line its surface; it contains fibroblasts, stem cells, blood vessels, lymphatics and nerves (Aδ fibres "
        "for sharp pain, C fibres for dull, throbbing pain). Deep caries or a fracture that exposes a pulp horn "
        "causes pulpitis. It shrinks with age as dentin is added.", "organ")
    add(g.mesh(sect(np.maximum(np.maximum(P, y + 0.07), T))), "Root canals (radicular pulp)",
        G_MOLAR, "#d46f7c",
        "The pulp cavity continues down each root as the root canal (the mesial root of a lower first molar "
        "usually has two canals, mesiobuccal and mesiolingual, the distal root one or two). Nerves and vessels "
        "enter through the apical foramen. Root canal treatment (endodontics) removes infected pulp, shapes and "
        "disinfects the canals and seals them with gutta-percha, saving a tooth with irreversible pulpitis or a "
        "dead pulp.", "organ")
    add(g.mesh(np.maximum(cement, -apex_d)), "Cementum", G_MOLAR, "#d8bd86",
        "A thin layer of bone-like tissue covering the root dentin from the neck to the apex, thickest near the "
        "apex (cellular cementum with cementocytes). Collagen (Sharpey's) fibres of the periodontal ligament are "
        "anchored in it. It is deposited throughout life, which compensates for occlusal wear, and is exposed "
        "when the gum recedes (root caries, sensitivity).", "bone")
    add(g.mesh(np.maximum(cement, apex_d)), "Apical foramen", G_MOLAR, "#a8784e",
        "The opening at the tip (apex) of each root through which the dental artery, vein and nerve pass between "
        "the jaw and the pulp. Its narrowness is why an inflamed pulp strangles its own blood supply, and why "
        "infection of a dead pulp escapes here to form a periapical abscess or granuloma, seen on X-ray as a dark "
        "halo at the root tip with loss of the lamina dura.", "bone")

    below_crest = y - Y_CREST
    deep = -0.34 - z                  # PDL and lamina dura stop behind the root: the rest is buried in bone
    pdl = sect(np.maximum(np.maximum(np.maximum(-T, T - PDL), below_crest), deep))
    lam = sect(np.maximum(np.maximum(np.maximum(PDL - T, T - PDL - LAM), np.maximum(below_crest, _body(x, y, z))),
                          deep))
    add(g.mesh(pdl), "Periodontal ligament", G_PERIO, "#c98883",
        "A 0.15–0.4 mm layer of dense collagen fibres (Sharpey's fibres) slung between cementum and the bony socket "
        "wall: the tooth is suspended in its socket by a fibrous joint (gomphosis). It acts as a shock absorber, "
        "carries mechanoreceptors that sense biting force, and its cells remodel the socket – the basis of "
        "orthodontic tooth movement. It is destroyed in periodontitis; on X-ray it is the thin dark line round "
        "each root.", "ligament")
    add(g.mesh(lam, smooth=0.7), "Alveolar bone proper (lamina dura)", G_PERIO, "#efe5d1",
        "The thin plate of compact bone lining the socket (alveolus), perforated by vessels and nerves "
        "(cribriform plate) and receiving the periodontal ligament fibres. It shows as a continuous white line "
        "round the root on dental X-rays; its loss at the apex signals periapical infection. Bone of the "
        "alveolar process exists only to hold teeth and resorbs after extraction.", "bone")

    # ---- the jaw on a coarser grid
    gb = _Grid((-X_HALF - 0.02, -2.78, -0.72), (X_HALF + 0.02, -0.08, 0.008), 0.0135)
    xb, yb, zb = gb.x, gb.y, gb.z
    Tb = _molar(xb, yb, zb)
    socket = Tb - PDL - LAM
    canal = np.sqrt((yb - Y_CANAL) ** 2 + zb ** 2) + 0 * xb
    body = _body(xb, yb, zb)
    inner = _body_inner(xb, yb, zb)
    nvb = _nv_paths()
    nvb_all = _capsules(xb, yb, zb, [p for v in nvb.values() for p in v], [0.012] * sum(len(v) for v in nvb.values()))

    def sect_b(d):
        return np.maximum(np.maximum(d, zb), -(nvb_all - 0.002))
    cortex = sect_b(np.maximum(np.maximum(np.maximum(body, -inner), -socket), -(canal - 0.13)))
    canal_wall = sect_b(np.maximum(np.maximum(canal - 0.13, 0.105 - canal), body))
    spongy = np.maximum(np.maximum(np.maximum(inner, -socket), -(canal - 0.13)), -(Tb - PDL - LAM + 0.001))
    n1 = fbm3(xb * 5.6, yb * 5.6, zb * 5.6, 1.0, 3, seed=21)
    n2 = fbm3(xb * 5.6 + 3.1, yb * 5.6 + 7.7, zb * 5.6 + 1.3, 1.0, 3, seed=37)
    trab = (np.minimum(np.abs(n1), np.abs(n2)) - 0.075) * 0.09
    slab = -0.085 - zb                                    # the trabecular pattern shows in the cut face
    marrow = sect_b(np.maximum(np.maximum(spongy, slab), -trab))
    # behind the cut face only thin plates at the mesial and distal saw cuts are needed; the rest is hidden
    ends = X_HALF - 0.035 - np.abs(xb)
    spongy_all = sect_b(np.maximum(spongy, np.minimum(np.maximum(trab, slab), np.maximum(ends, slab))))
    add(gb.mesh(cortex), "Cortical bone of mandible", G_PERIO, "#ece2cc",
        "Dense compact bone forming the buccal and lingual plates of the alveolar process and the thick inferior "
        "border of the mandible. The lingual plate is thinner by the molars, and the buccal plate over the lower "
        "molars thick – so lower molar infections tend to spread lingually, below the mylohyoid line into the "
        "submandibular space (Ludwig's angina), and anaesthetic by infiltration works poorly here, needing an "
        "inferior alveolar nerve block.", "bone")
    add(gb.mesh(spongy_all), "Cancellous (spongy) bone", G_PERIO, "#dcc59b",
        "A lattice of trabeculae between the cortical plates, supporting the sockets and carrying the dental "
        "vessels and nerves to the root apices; the interradicular septum between the two roots and the "
        "interdental septa between teeth are made of it.", "bone")
    add(gb.mesh(marrow), "Bone marrow", G_PERIO, "#9e5846",
        "Marrow in the spaces of the spongy bone – largely fatty (yellow) in the adult mandible, with islands of "
        "haemopoietic (red) marrow. Infection spreading from a dead tooth through the marrow causes osteomyelitis "
        "of the jaw; radiotherapy and antiresorptive drugs (bisphosphonates) predispose to osteonecrosis after "
        "extractions.", "bone")
    add(gb.mesh(canal_wall), "Mandibular canal", G_PERIO, "#f3ead6",
        "A tunnel lined by a thin shell of cortical bone running forward through the body of the mandible below "
        "the root apices, from the mandibular foramen on the ramus to the mental foramen below the premolars. It "
        "carries the inferior alveolar nerve, artery and vein. Its closeness to the lower molar roots (especially "
        "third molars) is checked on X-ray before extractions and implants.", "bone")

    # ---- nerves and vessels (fine slab around the section plane)
    gn = _Grid((-X_HALF - 0.02, -2.12, -0.07), (X_HALF + 0.02, 0.5, 0.008), 0.0062)
    xn, yn, zn = gn.x, gn.y, gn.z
    radius = {"nerve": (0.056, 0.013), "artery": (0.024, 0.009), "vein": (0.032, 0.011)}
    texts = {
        "nerve": ("Inferior alveolar nerve & dental nerves", "#f1d26a",
                  "Branch of the mandibular division of the trigeminal nerve (V3) running in the mandibular canal; "
                  "its dental branches enter each apical foramen and form a plexus in the pulp (plexus of "
                  "Raschkow) under the odontoblasts. Pulpal nerves signal only pain, whatever the stimulus. The "
                  "nerve ends as the mental nerve (lower lip and chin) – anaesthetised by an inferior alveolar "
                  "nerve block for lower dental work.", "nerve"),
        "artery": ("Inferior alveolar artery & dental arteries", "#c8322e",
                   "Branch of the maxillary artery (external carotid) running with the nerve in the mandibular "
                   "canal; small dental arteries pass through each apical foramen into the pulp, and others supply "
                   "the periodontal ligament and bone.", "artery"),
        "vein": ("Inferior alveolar vein & dental veins", "#3f5fa8",
                 "Drains the pulp, periodontium and bone to the pterygoid venous plexus. Pulpal veins leave "
                 "through the same narrow apical foramen as the arteries enter, so pulpal swelling compresses them "
                 "first.", "vein")}
    main_d = {"nerve": 0.02, "artery": 0.085, "vein": -0.05}
    for k, paths in _nv_paths().items():
        r_main, r_branch = radius[k]
        d = _capsules(xn, yn, zn, paths[1:], [r_branch] * (len(paths) - 1))
        d = np.minimum(d, np.sqrt((yn - Y_CANAL - main_d[k]) ** 2 + zn ** 2) - r_main + 0 * xn)
        d = np.maximum(d, np.abs(xn) - X_HALF)
        nm, col, tx, cat = texts[k]
        add(gn.mesh(np.maximum(d, zn), smooth=0.6), nm, G_NV, col, tx, cat)

    # ---- gingiva and alveolar mucosa
    gg = _Grid((-X_HALF - 0.02, -1.2, -0.78), (X_HALF + 0.02, 0.22, 0.008), 0.012)
    xg, yg, zg = gg.x, gg.y, gg.z
    Tg = _molar(xg, yg, zg)
    U = np.minimum(Tg, _body(xg, yg, zg))
    Us = _smin(Tg, _body(xg, yg, zg), 0.22)             # rounded, so the gum rises smoothly into its collar
    sulcus = np.maximum(Tg - 0.016, 0.035 - yg)
    gum = np.maximum(np.maximum(Us - 0.1, -U), yg - (0.165 - 1.3 * np.maximum(Tg, 0.0)))
    gum = np.maximum(np.maximum(gum, -0.62 - yg), np.maximum(np.abs(xg) - X_HALF, -sulcus))
    add(gg.mesh(np.maximum(gum, zg)), "Gingiva", G_PERIO, "#e3999a",
        "The gum: masticatory mucosa of keratinised stratified squamous epithelium firmly bound to the alveolar "
        "bone (attached gingiva, stippled) and forming a free collar round the neck of the tooth. Between the free "
        "gingiva and the enamel lies the gingival sulcus (0.5–3 mm deep); at its floor the junctional epithelium "
        "attaches to the tooth – the seal between mouth and periodontium. Plaque here causes gingivitis (red, "
        "swollen, bleeding gums); in periodontitis the attachment migrates down the root, the sulcus deepens into "
        "a periodontal pocket (> 3–4 mm on probing) and the ligament and bone are lost.", "mucosa")
    muc = np.maximum(np.maximum(U - 0.055, -U), np.maximum(yg + 0.62, -1.15 - yg))
    add(gg.mesh(np.maximum(np.maximum(muc, np.abs(xg) - X_HALF), zg)), "Alveolar mucosa", G_PERIO, "#d4707a",
        "Thin, red, loosely attached, non-keratinised lining mucosa below the mucogingival junction, continuous "
        "with the floor of the mouth and the cheek. It moves with the lips and cheeks; flaps for surgery and local "
        "anaesthetic infiltrations are placed here.", "mucosa")

    # ---- the four adult tooth types, whole, beside the section
    s = 0.58
    for name, fn, xc, desc in _types():
        gt = _Grid((xc - 0.42, -1.1, -0.36), (xc + 0.42, 0.62, 0.36), 0.013)
        d = fn((gt.x - xc) / s, gt.y / s, gt.z / s) * s
        crown = np.maximum(d, -gt.y)
        root = np.maximum(d, gt.y)
        if name == "Molar":
            neck = 0.05 * s
            crown = np.maximum(d, neck - gt.y)
            root = np.maximum(d, gt.y + neck)
            add(gt.mesh(crown), "Molar – crown", G_TYPES, "#eceff1",
                "The crown is the part covered by enamel, above the gum line. " + desc, "bone")
            add(gt.mesh(np.maximum(d, np.abs(gt.y) - neck)), "Molar – neck", G_TYPES, "#e2d3a6",
                "The neck (cervix) is the slightly constricted junction of crown and root at the cementoenamel "
                "junction, normally just under the free margin of the gingiva, which is attached to it by "
                "junctional epithelium. Gum recession exposes it (cervical sensitivity, root caries).", "bone")
            add(gt.mesh(root), "Molar – roots", G_TYPES, "#dcc48c",
                "The roots, covered by cementum, are held in the alveolar sockets by the periodontal ligament. "
                + desc, "bone")
            continue
        add(gt.mesh(crown), f"{name} – crown", G_TYPES, "#eceff1",
            "Crown: the enamel-covered part above the gum line. " + desc, "bone")
        add(gt.mesh(root), f"{name} – root", G_TYPES, "#dcc48c",
            "Root: covered by cementum and held in its socket by the periodontal ligament. " + desc, "bone")
    return parts
