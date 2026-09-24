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

    def mesh(self, names):
        """Positions and triangles of one or more named structures, re-indexed to their own vertices."""
        parts = []
        for name in names:
            for s in self.by_name[name]:
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


# ---------------------------------------------------------------- build
RIGHT = ["Superior lobe of right lung", "Middle lobe of right lung", "Inferior lobe of right lung"]
LEFT = ["Superior lobe of left lung", "Inferior lobe of left lung"]
HEART = ["Right atrium", "Right ventricle", "Left atrium", "Left ventricle"]


def main():
    atlas = Atlas()
    out = []

    def add(name, latin, mesh, material, subsystem, note):
        pos, tris = mesh
        out.append({"name": name, "latin": latin, "material": material, "subsystem": subsystem,
                    "note": note, "pos": pos.astype(np.float32), "tris": tris.astype(np.int64)})
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
            "material": f["material"],
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
