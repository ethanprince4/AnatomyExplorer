"""Build the pathology meshes used by the radiology cases into data/findings.

A finding is a mesh derived from the normal anatomy, so it sits in the same space and can be shown beside it:

  * an effusion is the volume the lung would occupy below a fluid level, voxelised, filled and re-meshed;
  * a compressed lung is the lung's own vertices squeezed up above that level;
  * a collapsed lung is the lung contracted towards its hilum;
  * an enlarged heart is the heart scaled about its centre;
  * a consolidated lobe is the lobe itself, nudged out along its normals so it reads as a separate surface.

Run after the dataset is built:  python tools/build_findings.py
Output: data/findings/findings.json (structure records) and findings.npz (geometry).
"""
import json
import sys
from pathlib import Path

import numpy as np
from scipy import ndimage
from skimage import measure

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SRC = ROOT / "data" / "anatomy"
OUT = ROOT / "data" / "findings"
OUT.mkdir(parents=True, exist_ok=True)

VDTYPE = np.dtype([("pos", "<f4", 3), ("nrm", "<f4", 3), ("obj", "<u2"), ("mat", "<u2")])

# name -> (colour, alpha) for the materials these meshes use
MATERIALS = {
    "Pleural fluid":   ((0.83, 0.66, 0.24), 0.80),
    "Collapsed lung":  ((0.72, 0.42, 0.45), 1.0),
    "Consolidation":   ((0.78, 0.69, 0.42), 1.0),
    "Enlarged heart":  ((0.72, 0.24, 0.24), 1.0),
    "Air in pleural space": ((0.55, 0.72, 0.82), 0.35),
    # used by tools/findings_specs.json
    "Mass": ((0.86, 0.80, 0.70), 1.0),
    "Calcification": ((0.98, 0.97, 0.90), 1.0),
    "Blood clot": ((0.42, 0.07, 0.09), 1.0),
    "Haemorrhage": ((0.66, 0.13, 0.12), 0.92),
    "Stone": ((0.93, 0.83, 0.48), 1.0),
    "Inflamed tissue": ((0.88, 0.42, 0.30), 1.0),
    "Fluid": ((0.83, 0.66, 0.24), 0.75),
    "Fracture": ((0.95, 0.36, 0.14), 1.0),
    "Abnormal vessel": ((0.86, 0.16, 0.18), 1.0),
    "Infarct": ((0.55, 0.62, 0.72), 0.95),
    "Breast tissue": ((0.94, 0.80, 0.70), 0.55),
    "Body soft tissue": ((0.74, 0.66, 0.55), 1.0),
}


# ---------------------------------------------------------------- source geometry
class Atlas:
    def __init__(self):
        self.meta = json.loads((SRC / "anatomy.json").read_text(encoding="utf-8"))
        self.verts = np.fromfile(SRC / "vertices.bin", dtype=VDTYPE)
        self.tris = np.fromfile(SRC / "indices.bin", dtype="<u4").reshape(-1, 3)
        self.by_name = {}
        for s in self.meta["structures"]:
            self.by_name.setdefault(s["name"], []).append(s)

    def records(self, name, side=""):
        if name.startswith("@"):                     # a whole subsystem, e.g. "@Brain" for the brain's surface
            pool = [s for s in self.meta["structures"] if s["subsystem"] == name[1:]]
        else:
            pool = self.by_name.get(name, [])
        found = [s for s in pool if not side or s["side"].lower() in (side.lower(), "")]
        if not found:
            raise KeyError(f"no atlas structure {name!r}" + (f" on the {side} side" if side else ""))
        return found

    def mesh(self, names, side=""):
        """Positions and triangles of one or more named structures, re-indexed to their own vertices."""
        parts = []
        for name in names:
            for s in self.records(name, side):
                a = s["i_start"] // 3
                parts.append(self.tris[a:a + s["i_count"] // 3])
        tris = np.concatenate(parts)
        used, inverse = np.unique(tris.ravel(), return_inverse=True)
        return self.verts["pos"][used].astype(np.float64), inverse.reshape(-1, 3).astype(np.int64)


# ---------------------------------------------------------------- mesh helpers
def normals_of(pos, tris):
    n = np.zeros_like(pos)
    a, b, c = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
    fn = np.cross(b - a, c - a)                  # area-weighted, so big faces dominate
    for k in range(3):
        np.add.at(n, tris[:, k], fn)
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    return (n / np.where(ln < 1e-20, 1.0, ln)).astype(np.float32)


def voxelise(pos, tris, pitch, pad=3):
    """Solid occupancy grid of a closed mesh: rasterise the shell, then fill it."""
    lo = pos.min(axis=0) - pad * pitch
    hi = pos.max(axis=0) + pad * pitch
    shape = np.maximum(np.ceil((hi - lo) / pitch).astype(int) + 1, 4)
    grid = np.zeros(shape, dtype=bool)
    a, b, c = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
    # enough barycentric samples that no triangle can slip between voxels
    longest = max(np.linalg.norm(b - a, axis=1).max(), np.linalg.norm(c - a, axis=1).max())
    n = int(max(2, np.ceil(longest / (pitch * 0.5))))
    us = np.linspace(0.0, 1.0, n)
    for u in us:
        vs = np.linspace(0.0, 1.0 - u, max(2, int(np.ceil(n * (1.0 - u))) + 1))
        for v in vs:
            p = a + (b - a) * u + (c - a) * v
            idx = np.rint((p - lo) / pitch).astype(int)
            np.clip(idx, 0, np.array(shape) - 1, out=idx)
            grid[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    return ndimage.binary_fill_holes(grid), lo


def surface(mask, lo, pitch, smooth=1.8):
    vol = ndimage.gaussian_filter(mask.astype(np.float32), smooth)
    verts, faces, _n, _v = measure.marching_cubes(vol, level=0.5)
    return verts * pitch + lo, faces.astype(np.int64)


# ---------------------------------------------------------------- the findings
def effusion(atlas, lobes, level, meniscus=0.014, grow=2, pitch=0.0016):
    """The space the lung gives up to fluid: its own volume below a level, with a meniscus up the chest wall."""
    pos, tris = atlas.mesh(lobes)
    mask, lo = voxelise(pos, tris, pitch)
    if grow:
        mask = ndimage.binary_dilation(mask, iterations=grow)   # reach into the costophrenic recess
    nx, ny, nz = mask.shape
    xs = lo[0] + np.arange(nx) * pitch
    ys = lo[1] + np.arange(ny) * pitch
    zs = lo[2] + np.arange(nz) * pitch
    cx, cz = pos[:, 0].mean(), pos[:, 2].mean()
    rx = (xs - cx) / max(abs(pos[:, 0] - cx).max(), 1e-6)
    rz = (zs - cz) / max(abs(pos[:, 2] - cz).max(), 1e-6)
    r2 = np.clip(rx[:, None] ** 2 + rz[None, :] ** 2, 0.0, 1.0)
    top = level + meniscus * r2                                  # fluid climbs the chest wall
    below = ys[None, :, None] < top[:, None, :]
    return surface(mask & below, lo, pitch)


def squeezed(atlas, lobes, level):
    """The lung pushed up above a fluid level, keeping its shape but compressed vertically."""
    pos, tris = atlas.mesh(lobes)
    y0, y1 = pos[:, 1].min(), pos[:, 1].max()
    f = (y1 - level) / (y1 - y0)
    out = pos.copy()
    out[:, 1] = y1 - (y1 - pos[:, 1]) * f
    # and pulled a little off the chest wall, the way a compressed lung retracts
    c = np.array([pos[:, 0].mean(), 0.0, pos[:, 2].mean()])
    out[:, 0] = c[0] + (out[:, 0] - c[0]) * 0.94
    out[:, 2] = c[2] + (out[:, 2] - c[2]) * 0.94
    return out, tris


def collapsed(atlas, lobes, hilum, k=0.44):
    """A lung that has let go of the chest wall and shrunk back towards its hilum."""
    pos, tris = atlas.mesh(lobes)
    h = np.asarray(hilum, dtype=np.float64)
    return h + (pos - h) * k, tris


def scaled(atlas, names, factors, centre=None):
    pos, tris = atlas.mesh(names)
    c = np.asarray(centre if centre is not None else pos.mean(axis=0), dtype=np.float64)
    return c + (pos - c) * np.asarray(factors, dtype=np.float64), tris


def moved(atlas, names, offset):
    pos, tris = atlas.mesh(names)
    return pos + np.asarray(offset, dtype=np.float64), tris


def swollen(atlas, names, amount=0.0015):
    """The structure itself, nudged out along its normals so it reads as a separate surface over the original."""
    pos, tris = atlas.mesh(names)
    return pos + normals_of(pos, tris) * amount, tris


# ---------------------------------------------------------------- declarative findings (tools/findings_specs.json)
SPECS = ROOT / "tools" / "findings_specs.json"
MM = 0.001


def icosphere(level=3):
    t = (1 + 5 ** 0.5) / 2
    v = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
         (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    f = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6),
         (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10),
         (8, 6, 7), (9, 8, 1)]
    verts = [np.array(p, dtype=np.float64) / np.linalg.norm(p) for p in v]
    for _ in range(level):
        cache, nf = {}, []
        def mid(a, b):
            key = (min(a, b), max(a, b))
            if key not in cache:
                m = verts[a] + verts[b]
                verts.append(m / np.linalg.norm(m))
                cache[key] = len(verts) - 1
            return cache[key]
        for a, b, c in f:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            nf += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        f = nf
    return np.array(verts), np.array(f, dtype=np.int64)


def merge(meshes):
    pos, tris, base = [], [], 0
    for p, t in meshes:
        pos.append(p)
        tris.append(t + base)
        base += len(p)
    return np.concatenate(pos), np.concatenate(tris)


def bbox_point(atlas, at):
    """A point given as fractions of a named structure's box (x: patient right 0 -> left 1, y: inferior 0 ->
    superior 1, z: posterior 0 -> anterior 1), optionally snapped to its surface and pushed out along the normal."""
    side = at.get("side", "")
    pos, tris = atlas.mesh([at["structure"]], side)
    lo, hi = pos.min(axis=0), pos.max(axis=0)
    f = np.array([at.get("x", 0.5), at.get("y", 0.5), at.get("z", 0.5)], dtype=np.float64)
    point = lo + np.clip(f, -0.5, 1.5) * (hi - lo)
    if at.get("surface"):
        i = int(np.argmin(np.sum((pos - point) ** 2, axis=1)))
        normal = normals_of(pos, tris)[i].astype(np.float64)
        point = pos[i] + normal * float(at.get("offset_mm", 0.0)) * MM
    else:
        point = point + np.asarray(at.get("shift_mm", (0, 0, 0)), dtype=np.float64) * MM
    return point


def blob(centre, radii_mm, irregular=0.0, seed=0, level=3):
    v, f = icosphere(level)
    if irregular:
        rng = np.random.default_rng(seed)
        bumps = rng.normal(size=(6, 3))
        r = 1 + irregular * np.tanh(np.sum(np.sin(v @ bumps.T * 3.1), axis=1) / 3)
        v = v * r[:, None]
    return centre + v * np.asarray(radii_mm, dtype=np.float64) * MM, f


def cluster(centre, spread_mm, count, size_mm, seed=0):
    rng = np.random.default_rng(seed)
    meshes = []
    for _ in range(int(count)):
        d = rng.normal(size=3)
        d *= rng.uniform(0.15, 1.0) / max(np.linalg.norm(d), 1e-9)
        size = float(size_mm) * rng.uniform(0.6, 1.3)
        meshes.append(blob(centre + d * np.asarray(spread_mm) * MM, (size, size, size), level=1))
    return merge(meshes)


def tube(a, b, radius_mm, segments=16):
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    axis = b - a
    length = np.linalg.norm(axis)
    w = axis / max(length, 1e-9)
    u = np.cross(w, [0, 0, 1] if abs(w[2]) < 0.9 else [1, 0, 0])
    u /= np.linalg.norm(u)
    v = np.cross(w, u)
    r = radius_mm * MM
    rings, tris = [], []
    steps = max(2, int(length / (r * 0.8)) + 1)
    for k in range(steps):
        c = a + axis * k / (steps - 1)
        for j in range(segments):
            ang = 2 * np.pi * j / segments
            rings.append(c + r * (np.cos(ang) * u + np.sin(ang) * v))
    for k in range(steps - 1):
        for j in range(segments):
            p0, p1 = k * segments + j, k * segments + (j + 1) % segments
            tris += [(p0, p1, p0 + segments), (p1, p1 + segments, p0 + segments)]
    pos = np.array(rings + [a, b])
    ia, ib = len(pos) - 2, len(pos) - 1
    last = (steps - 1) * segments
    for j in range(segments):
        tris += [(ia, (j + 1) % segments, j), (ib, last + j, last + (j + 1) % segments)]
    return pos, np.array(tris, dtype=np.int64)


def layer(atlas, names, side, thickness_mm, window, pitch=0.0015):
    """A collection lying on an organ: the shell the organ would gain if it grew by `thickness`, kept within a
    window given as fractions of the organ's box (the same axes as bbox_point)."""
    pos, tris = atlas.mesh(names, side)
    grow = max(1, int(round(thickness_mm * MM / pitch)))
    mask, lo = voxelise(pos, tris, pitch, pad=grow + 3)
    shell = ndimage.binary_dilation(mask, iterations=grow) & ~mask
    blo, bhi = pos.min(axis=0), pos.max(axis=0)
    coords = [lo[k] + np.arange(shell.shape[k]) * pitch for k in range(3)]
    for k, key in enumerate("xyz"):
        if key in window:
            f0, f1 = window[key]
            inside = (coords[k] >= blo[k] + f0 * (bhi[k] - blo[k])) & (coords[k] <= blo[k] + f1 * (bhi[k] - blo[k]))
            shape = [1, 1, 1]
            shape[k] = -1
            shell &= inside.reshape(shape)
    return surface(shell, lo, pitch, smooth=1.0)


def breast(atlas, side, depth_mm=48.0, radius_mm=None):
    """An illustrative breast for mammography: a dome on the mammary region of the chest wall, facing out."""
    pos, tris = atlas.mesh(["Mammary region"], side)
    centre = pos.mean(axis=0)
    normal = normals_of(pos, tris).astype(np.float64).mean(axis=0)
    normal = normal / np.linalg.norm(normal)
    if normal[2] < 0:
        normal = -normal
    r = (radius_mm * MM) if radius_mm else float(np.median(np.linalg.norm(pos - centre, axis=1))) * 1.25
    u = np.cross(normal, [0, 1, 0])
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    sph, f = icosphere(4)
    out = sph.copy()
    out[:, 2] = np.where(out[:, 2] < 0, out[:, 2] * 0.15, out[:, 2])      # a flattened base on the chest wall
    world = centre + r * (out[:, 0:1] * u + out[:, 1:2] * v) * 1.0 + (depth_mm * MM) * out[:, 2:3] * normal
    # the breast hangs: shift its lower half down and forward a little
    sag = np.clip(-out[:, 1], 0, None)[:, None]
    world += sag * (-0.18 * r * np.array([0, 1, 0]) + 0.10 * r * normal)
    return world, f


def body_fills(atlas, groups, pitch=0.005):
    """The body's soft tissue, so a section reads as tissue rather than empty space between the organs: the volume
    inside the skin, split into the given region groups by the nearest bone (bones carry reliable regions)."""
    structs = atlas.meta["structures"]
    names = sorted({s["name"] for s in structs if s["system"] == "regions"})
    pos, tris = atlas.mesh(names)
    lo = pos.min(axis=0) - 6 * pitch
    shape = np.ceil((pos.max(axis=0) + 6 * pitch - lo) / pitch).astype(int) + 1
    grid = np.zeros(shape, dtype=bool)
    a, b, c = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
    for u in np.linspace(0, 1, 7):
        for v in np.linspace(0, 1 - u, max(2, int(7 * (1 - u)) + 1)):
            idx = np.rint((a + (b - a) * u + (c - a) * v - lo) / pitch).astype(int)
            grid[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    grid = ndimage.binary_dilation(grid, iterations=2)          # close the seams between patches
    # Fill every horizontal slice: the skin rings each slice of the trunk, the head and the hanging limbs.
    solid = np.stack([ndimage.binary_fill_holes(grid[:, j, :]) for j in range(grid.shape[1])], axis=1)
    solid = ndimage.binary_erosion(solid, iterations=3)          # sit just inside the skin
    owner = np.zeros(shape, dtype=np.int16)                       # 1 + group of the bone at each voxel
    for s in structs:
        if s["system"] != "skeletal":
            continue
        group = next((g for g, (_n, regions) in enumerate(groups) if set(s["regions"]) & set(regions)), None)
        if group is None:
            continue
        a = s["i_start"] // 3
        used = np.unique(atlas.tris[a:a + s["i_count"] // 3].ravel())
        idx = np.rint((atlas.verts["pos"][used].astype(np.float64) - lo) / pitch).astype(int)
        ok = np.all((idx >= 0) & (idx < shape), axis=1)
        owner[idx[ok, 0], idx[ok, 1], idx[ok, 2]] = group + 1
    _d, nearest = ndimage.distance_transform_edt(owner == 0, return_indices=True)
    label = owner[nearest[0], nearest[1], nearest[2]]
    out = []
    for g, (name, regions) in enumerate(groups):
        part = solid & (label == g + 1)
        print(f"  {name}: {part.sum() * pitch ** 3 * 1000:.1f} litres")
        out.append((name, regions, surface(part, lo, pitch, smooth=1.2)))
    return out


def from_spec(atlas, spec, built):
    shape = spec["shape"]
    kind = shape["type"]
    def point(at):
        if at.get("structure") in built:
            pos = built[at["structure"]]
            lo, hi = pos.min(axis=0), pos.max(axis=0)
            f = np.array([at.get("x", 0.5), at.get("y", 0.5), at.get("z", 0.5)])
            return lo + f * (hi - lo) + np.asarray(at.get("shift_mm", (0, 0, 0)), dtype=np.float64) * MM
        return bbox_point(atlas, at)
    if kind == "blob":
        return blob(point(shape["at"]), shape["radii_mm"], shape.get("irregular", 0.0), shape.get("seed", 0))
    if kind == "cluster":
        return cluster(point(shape["at"]), shape["spread_mm"], shape.get("count", 12), shape.get("size_mm", 0.8),
                       shape.get("seed", 0))
    if kind == "tube":
        return tube(point(shape["from"]), point(shape["to"]), shape["radius_mm"])
    if kind == "swollen":
        pos, tris = atlas.mesh(shape["structures"], shape.get("side", ""))
        return pos + normals_of(pos, tris) * shape.get("mm", 1.5) * MM, tris
    if kind == "scaled":
        pos, tris = atlas.mesh(shape["structures"], shape.get("side", ""))
        c = pos.mean(axis=0)
        return c + (pos - c) * np.asarray(shape["factors"], dtype=np.float64), tris
    if kind == "moved":
        pos, tris = atlas.mesh(shape["structures"], shape.get("side", ""))
        return pos + np.asarray(shape["offset_mm"], dtype=np.float64) * MM, tris
    if kind == "layer":
        return layer(atlas, shape["structures"], shape.get("side", ""), shape["thickness_mm"], shape.get("window", {}))
    if kind == "breast":
        return breast(atlas, shape["side"], shape.get("depth_mm", 48.0), shape.get("radius_mm"))
    raise ValueError(f"unknown shape {kind!r}")


BODY_FILLS = [
    ("Soft tissue of head and neck (section fill)", ["head", "neck"]),
    ("Soft tissue of trunk (section fill)", ["thorax", "abdomen", "back"]),
    ("Soft tissue of right upper limb (section fill)", ["upper_limb_r"]),
    ("Soft tissue of left upper limb (section fill)", ["upper_limb_l"]),
    ("Soft tissue of right lower limb (section fill)", ["lower_limb_r"]),
    ("Soft tissue of left lower limb (section fill)", ["lower_limb_l"]),
]


# ---------------------------------------------------------------- build
RIGHT = ["Superior lobe of right lung", "Middle lobe of right lung", "Inferior lobe of right lung"]
LEFT = ["Superior lobe of left lung", "Inferior lobe of left lung"]
HEART = ["Right atrium", "Right ventricle", "Left atrium", "Left ventricle"]


def main():
    atlas = Atlas()
    out = []

    def add(name, latin, mesh, material, subsystem, note, regions=("thorax",)):
        pos, tris = mesh
        a_, b_, c_ = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
        if np.einsum("ij,ij->", a_, np.cross(b_, c_)) < 0:
            # Faces must wind outwards: a scan section finds the inside of a part from which faces it sees.
            tris = tris[:, [0, 2, 1]]
        out.append({"name": name, "latin": latin, "material": material, "subsystem": subsystem,
                    "note": note, "pos": pos.astype(np.float32), "tris": tris.astype(np.int64),
                    "regions": list(regions)})
        print(f"{name:38s} {len(pos):7d} verts {len(tris):7d} tris")

    add("Right pleural effusion", "Effusio pleuralis dextra",
        effusion(atlas, RIGHT, level=1.352, meniscus=0.010), "Pleural fluid", "Pleural space",
        "A massive effusion filling almost the whole right pleural cavity.")
    add("Right lung compressed by effusion", "Pulmo dexter compressus",
        squeezed(atlas, RIGHT, 1.352), "Collapsed lung", "Pleural space",
        "All that is left aerated of the right lung, squashed up against the apex.")
    add("Mediastinum shifted to the left", "Mediastinum translatum",
        moved(atlas, HEART + ["Trachea"], (0.026, 0.0, 0.0)), "Enlarged heart", "Cardiac",
        "Fluid under pressure pushes the heart and trachea away from the side it is on.")

    add("Small bilateral pleural effusions", "Effusiones pleurales bilaterales",
        (lambda a, b: (np.concatenate([a[0], b[0]]),
                       np.concatenate([a[1], b[1] + len(a[0])])))(
            effusion(atlas, RIGHT, level=1.198, meniscus=0.010),
            effusion(atlas, LEFT, level=1.195, meniscus=0.010)),
        "Pleural fluid", "Pleural space",
        "Small effusions blunting both costophrenic angles, as in heart failure.")

    add("Collapsed left lung (pneumothorax)", "Pulmo sinister collapsus",
        collapsed(atlas, LEFT, hilum=(0.030, 1.285, -0.010), k=0.80), "Collapsed lung", "Pleural space",
        "Air in the pleural space has let the left lung fall away from the chest wall.")
    add("Air in the left pleural space", "Pneumothorax sinister",
        swollen(atlas, LEFT, 0.0022), "Air in pleural space", "Pleural space",
        "The pleural cavity the lung has retreated from - no lung markings out here.")

    add("Consolidated right middle lobe", "Lobus medius consolidatus",
        swollen(atlas, ["Middle lobe of right lung"]), "Consolidation", "Airspace disease",
        "The right middle lobe filled with inflammatory exudate instead of air.")

    add("Enlarged heart", "Cor dilatatum",
        scaled(atlas, HEART, (1.34, 1.12, 1.30)), "Enlarged heart", "Cardiac",
        "The cardiac silhouette of a dilated heart, over half the width of the chest.")

    for name, regions, mesh in body_fills(atlas, BODY_FILLS):
        add(name, "", mesh, "Body soft tissue", "Section fill",
            "Fat, connective tissue and everything else under the skin that the atlas does not model as a named "
            "structure, shown only in scan sections so the cut reads as tissue.", regions)

    built = {}
    specs = json.loads(SPECS.read_text(encoding="utf-8")) if SPECS.is_file() else []
    for spec in specs:
        if spec["material"] not in MATERIALS:
            raise ValueError(f"{spec['name']}: unknown material {spec['material']!r}")
        mesh = from_spec(atlas, spec, built)
        built[spec["name"]] = mesh[0]
        add(spec["name"], spec.get("latin", ""), mesh, spec["material"], spec.get("subsystem", "Pathology"),
            spec.get("note", ""), spec.get("regions", ["thorax"]))

    # ---- pack
    mats = list(MATERIALS)
    verts = np.zeros(sum(len(f["pos"]) for f in out), dtype=VDTYPE)
    tris = np.zeros((sum(len(f["tris"]) for f in out), 3), dtype="<u4")
    records = []
    vo = to = 0
    for f in out:
        n, m = len(f["pos"]), len(f["tris"])
        verts["pos"][vo:vo + n] = f["pos"]
        verts["nrm"][vo:vo + n] = normals_of(f["pos"].astype(np.float64), f["tris"])
        verts["mat"][vo:vo + n] = mats.index(f["material"])       # local; offset when attached
        tris[to:to + m] = f["tris"] + vo
        records.append({
            "name": f["name"], "latin": f["latin"], "subsystem": f["subsystem"], "note": f["note"],
            "material": f["material"], "regions": f["regions"],
            "v_start": vo, "v_count": n, "i_start": to * 3, "i_count": m * 3,
            "bbox": [f["pos"].min(axis=0).tolist(), f["pos"].max(axis=0).tolist()],
            "centroid": f["pos"].mean(axis=0).tolist(),
        })
        vo += n
        to += m

    np.savez_compressed(OUT / "findings.npz", verts=verts, tris=tris)
    (OUT / "findings.json").write_text(json.dumps({
        "format": 1,
        "materials": [{"name": k, "color": list(v[0]), "alpha": v[1]} for k, v in MATERIALS.items()],
        "findings": records,
    }, indent=1), encoding="utf-8")
    print(f"\n{len(records)} findings, {vo} vertices, {to} triangles -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
