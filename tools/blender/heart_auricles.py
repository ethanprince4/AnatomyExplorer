"""Model the two auricles (atrial appendages) of the heart model in Blender and export them for app/micro/heart.py.

Run with Blender's Python (the bpy module, Blender 4.2 LTS), headless:

    python tools/blender/heart_auricles.py            # a python with `import bpy` (e.g. a bpy venv)
    blender -b -P tools/blender/heart_auricles.py     # or Blender itself

Writes data/models/heart_auricles.npz: for each auricle a closed triangle mesh (verts, faces) in the heart frame of
heart.py. The builder turns each into a signed-distance field, so the auricle's wall, its pectinate-lined cavity and
its junction with the atrium come out of the same field pipeline as the rest of the heart. After changing this
script, rerun it and bump AURICLE_ASSET_VERSION in heart.py (the model cache keys on source files, not on data).

Why Blender: an auricle is a flattened, lobulated pouch whose free margin is crenated (notched) - a shape made of
a coarse control cage refined by Catmull-Clark subdivision, which keeps the notches crisp while everything else
rounds off, and then roughened by a displacement texture so no two lobules are alike. Everything is procedural:
the cage is generated here from the same path the old builder used, nothing is imported.

Anatomy (Gray's, Netter pl. 216-217): the right auricle is a broad triangular flap from the anterosuperior right
atrium, lying forwards and to the left over the root of the ascending aorta. The left auricle is long, narrow and
hooked, with a scalloped margin of several lobes, curling forwards round the left side of the pulmonary trunk and
overlapping the origin of the left coronary artery.
"""
import math
from pathlib import Path

import numpy as np

try:
    import bpy
except ImportError:               # pragma: no cover - this script only runs inside Blender
    raise SystemExit("Run this with Blender's Python (import bpy), e.g. blender -b -P " + __file__)

VERSION = 1
OUT = Path(__file__).resolve().parents[2] / "data" / "models" / "heart_auricles.npz"

# ---------------------------------------------------------------------------------------------- heart frame
# mirrors heart.py: the heart frame is tilted 48 degrees about z and -33 degrees about x into the body
_A, _B = math.radians(48.0), math.radians(-33.0)
_RZ = np.array([[math.cos(_A), -math.sin(_A), 0.0], [math.sin(_A), math.cos(_A), 0.0], [0.0, 0.0, 1.0]])
_RX = np.array([[1.0, 0.0, 0.0], [0.0, math.cos(_B), -math.sin(_B)], [0.0, math.sin(_B), math.cos(_B)]])
R_BODY = _RX @ _RZ


def to_heart(p):
    return np.asarray(p, float) @ R_BODY


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


# Each auricle: centreline in body coordinates (from its root in the atrial wall to its tip), half-width and half-
# thickness along it, the outward normal of the flap (body), and its margin: scallops per side, their depth, and how
# strongly the pouch is lobulated between pectinate grooves.
AURICLES = {
    "right": dict(path=[[-0.74, 0.26, 0.02], [-0.66, 0.36, 0.17], [-0.56, 0.43, 0.27], [-0.46, 0.46, 0.33],
                        [-0.36, 0.45, 0.37]],
                  width=[0.19, 0.18, 0.15, 0.11, 0.06], thick=[0.10, 0.085, 0.07, 0.058, 0.04],
                  out=(-0.3, 0.2, 1.0), scallops=3, depth=0.22, lobes=5, seed=3),
    "left": dict(path=[[0.00, 0.58, -0.28], [0.20, 0.66, -0.15], [0.33, 0.64, 0.00], [0.35, 0.58, 0.14],
                       [0.29, 0.53, 0.25], [0.22, 0.50, 0.30]],
                 width=[0.10, 0.115, 0.11, 0.095, 0.075, 0.04], thick=[0.078, 0.075, 0.068, 0.058, 0.048, 0.03],
                 out=(1.0, 0.1, 0.6), scallops=5, depth=0.30, lobes=7, seed=5),
}


def catmull(pts, n):
    """Centripetal-ish Catmull-Rom through pts, n samples."""
    pts = np.asarray(pts, float)
    P = np.vstack([2 * pts[0] - pts[1], pts, 2 * pts[-1] - pts[-2]])
    seg = len(pts) - 1
    out = []
    for i in range(n):
        u = i / (n - 1) * seg
        k = min(int(u), seg - 1)
        t = u - k
        p0, p1, p2, p3 = P[k], P[k + 1], P[k + 2], P[k + 3]
        out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                          + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    return np.array(out)


def cage(spec, rings=16, around=16):
    """Control cage of one auricle: flattened elliptical rings along the centreline whose rim points are pushed
    in and out to notch the margin, closed at the root and at a rounded tip."""
    rng = np.random.default_rng(spec["seed"])
    path = catmull(to_heart(spec["path"]), rings)
    s = np.linspace(0.0, 1.0, rings)
    w = np.interp(s, np.linspace(0, 1, len(spec["width"])), spec["width"])
    th = np.interp(s, np.linspace(0, 1, len(spec["thick"])), spec["thick"])
    out = to_heart(unit(spec["out"]))
    verts = []
    phase = rng.uniform(0, 2 * math.pi, 2)
    for i in range(rings):
        tan = unit(path[min(i + 1, rings - 1)] - path[max(i - 1, 0)])
        n = unit(out - tan * np.dot(out, tan))
        bi = np.cross(tan, n)
        # the margin is notched only beyond the root, and the notches deepen towards the tip
        notch = np.clip((s[i] - 0.15) / 0.3, 0.0, 1.0)
        for j in range(around):
            a = 2 * math.pi * j / around
            ca, sa = math.cos(a), math.sin(a)
            rim = abs(ca) ** 3                       # 1 on the margin, 0 on the flat faces
            side = 0 if ca > 0 else 1
            scal = math.sin(math.pi * spec["scallops"] * s[i] * 2 + phase[side])
            ww = w[i] * (1.0 + spec["depth"] * notch * rim * scal)
            # lobules bulge between the grooves left by the pectinate muscles inside
            lob = 1.0 + 0.16 * notch * math.sin(2 * math.pi * spec["lobes"] * s[i] + 1.3 * ca) * (1 - rim)
            tt = th[i] * lob * (1.0 + 0.1 * rng.normal())
            verts.append(path[i] + bi * ca * ww + n * sa * tt)
    verts = np.array(verts)
    faces = []
    for i in range(rings - 1):
        for j in range(around):
            a, b = i * around + j, i * around + (j + 1) % around
            faces.append((a, b, b + around, a + around))
    # root cap (buried in the atrial wall) and a blunt tip
    root = len(verts)
    tip = root + 1
    tip_pt = path[-1] + unit(path[-1] - path[-2]) * th[-1] * 0.8
    verts = np.vstack([verts, path[0] - unit(path[1] - path[0]) * 0.04, tip_pt])
    for j in range(around):
        faces.append((root, (j + 1) % around, j))
        last = (rings - 1) * around
        faces.append((tip, last + j, last + (j + 1) % around))
    return verts, faces


def build(name, spec):
    verts, faces = cage(spec)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    sub = obj.modifiers.new("subdivide", "SUBSURF")
    sub.levels = sub.render_levels = 3
    tex = bpy.data.textures.new(name + "_lobules", "CLOUDS")
    tex.noise_scale = 0.07
    tex.noise_depth = 2
    disp = obj.modifiers.new("lobules", "DISPLACE")
    disp.texture = tex
    disp.texture_coords = "GLOBAL"
    disp.strength = 0.010
    disp.mid_level = 0.5
    smooth = obj.modifiers.new("relax", "SMOOTH")
    smooth.iterations = 3
    smooth.factor = 0.35
    tri = obj.modifiers.new("triangulate", "TRIANGULATE")
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    m = ev.to_mesh()
    v = np.array([vv.co[:] for vv in m.vertices], np.float32)
    f = np.array([p.vertices[:] for p in m.polygons], np.int32)
    ev.to_mesh_clear()
    assert tri and f.shape[1] == 3
    return v, f


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    arrays = {"version": np.array(VERSION)}
    for name, spec in AURICLES.items():
        v, f = build(name + "_auricle", spec)
        arrays[f"{name}_verts"] = v
        arrays[f"{name}_faces"] = f
        print(f"{name} auricle: {len(v)} vertices, {len(f)} triangles")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT, **arrays)
    print("wrote", OUT)


main()
