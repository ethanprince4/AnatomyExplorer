# Headless Blender script: extracts geometry + metadata from the Z-Anatomy blend
# into a renderer-agnostic format consumed by tools/build_dataset.py.
# Run: blender -b Startup.blend --factory-startup --python export_zanatomy.py -- <out_dir>
import bpy
import json
import os
import sys
import time

import numpy as np

OUT = sys.argv[sys.argv.index("--") + 1]
os.makedirs(OUT, exist_ok=True)
LOG = open(os.path.join(OUT, "export_log.txt"), "w", encoding="utf-8")


def log(msg):
    LOG.write(str(msg) + "\n")
    LOG.flush()


t0 = time.time()
depsgraph = bpy.context.evaluated_depsgraph_get()
view_layer = bpy.context.view_layer
in_layer = set(o.name for o in view_layer.objects)

# Blender is Z-up, facing -Y. Convert to Y-up, facing +Z.
CONV = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=np.float64)


def rgba(v):
    return [round(float(x), 4) for x in v]


def material_info(mat):
    if mat is None:
        return None
    info = {"name": mat.name, "diffuse": rgba(mat.diffuse_color), "candidates": []}
    if mat.use_nodes and mat.node_tree:
        for n in mat.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                inp = n.inputs["Base Color"]
                if not inp.is_linked:
                    info["candidates"].append(["principled", rgba(inp.default_value)])
            elif n.type == "RGB":
                info["candidates"].append(["rgb", rgba(n.outputs[0].default_value)])
            elif n.type == "GROUP" and n.node_tree:
                for i in n.inputs:
                    if getattr(i, "type", None) == "RGBA" and not i.is_linked:
                        info["candidates"].append(["group:" + n.node_tree.name + ":" + i.name, rgba(i.default_value)])
                for gn in n.node_tree.nodes:
                    if gn.type == "RGB":
                        info["candidates"].append(["grouprgb:" + n.node_tree.name, rgba(gn.outputs[0].default_value)])
    return info


# ---- collections
collections = {}
for c in bpy.data.collections:
    collections[c.name] = {"children": [ch.name for ch in c.children]}
scene_roots = [c.name for c in bpy.context.scene.collection.children]

# ---- materials
materials = {}
for m in bpy.data.materials:
    try:
        materials[m.name] = material_info(m)
    except Exception as e:
        log(f"material fail {m.name}: {e}")

# ---- texts (definitions)
texts = {}
for t in bpy.data.texts:
    if t.name.endswith(".py"):
        continue
    try:
        texts[t.name] = t.as_string()
    except Exception as e:
        log(f"text fail {t.name}: {e}")

# ---- geometry
positions = []
normals = []
indices = []
tri_mats = []
objects = []
v_total = 0
i_total = 0

renderable = [o for o in bpy.data.objects if o.type in ("MESH", "CURVE")]
log(f"renderable candidates {len(renderable)}")

for n, ob in enumerate(renderable):
    name = ob.name
    base_suffix = name.rsplit(".", 1)[-1] if "." in name else ""
    if ob.type == "MESH" and base_suffix in ("j", "i"):
        continue  # label leader lines
    if name not in in_layer:
        continue
    try:
        ev = ob.evaluated_get(depsgraph)
        me = ev.to_mesh()
    except Exception as e:
        log(f"to_mesh fail {name}: {e}")
        continue
    if me is None:
        continue
    try:
        me.calc_loop_triangles()
        nv = len(me.vertices)
        nt = len(me.loop_triangles)
        if nv == 0 or nt == 0:
            log(f"empty {name} type={ob.type}")
            continue
        co = np.empty(nv * 3, dtype=np.float32)
        me.vertices.foreach_get("co", co)
        nr = np.empty(nv * 3, dtype=np.float32)
        me.vertices.foreach_get("normal", nr)
        tri = np.empty(nt * 3, dtype=np.int64)
        me.loop_triangles.foreach_get("vertices", tri)
        tmat = np.empty(nt, dtype=np.int32)
        me.loop_triangles.foreach_get("material_index", tmat)

        mw = np.array(ev.matrix_world, dtype=np.float64)
        m3 = mw[:3, :3]
        co = co.reshape(-1, 3).astype(np.float64) @ m3.T + mw[:3, 3]
        nmat = np.linalg.inv(m3).T
        nr = nr.reshape(-1, 3).astype(np.float64) @ nmat.T
        ln = np.linalg.norm(nr, axis=1, keepdims=True)
        ln[ln == 0] = 1
        nr = nr / ln
        co = co @ CONV.T
        nr = nr @ CONV.T
        tri = tri.reshape(-1, 3)
        if np.linalg.det(m3) < 0:
            tri = tri[:, ::-1]

        mats = [s.material.name if s.material else None for s in ob.material_slots]
        rec = {
            "name": name,
            "data_name": ob.data.name if ob.data else name,
            "type": ob.type,
            "parent": ob.parent.name if ob.parent else None,
            "parent_type": ob.parent.type if ob.parent else None,
            "collections": [c.name for c in ob.users_collection],
            "materials": mats,
            "hidden": bool(ob.hide_get()),
            "hide_viewport": bool(ob.hide_viewport),
            "v_start": v_total,
            "v_count": nv,
            "i_start": i_total,
            "i_count": nt * 3,
            "bbox_min": [round(float(x), 5) for x in co.min(axis=0)],
            "bbox_max": [round(float(x), 5) for x in co.max(axis=0)],
            "centroid": [round(float(x), 5) for x in co.mean(axis=0)],
        }
        positions.append(co.astype(np.float32))
        normals.append(nr.astype(np.float32))
        indices.append((tri + v_total).astype(np.uint32))
        tri_mats.append(np.clip(tmat, 0, 255).astype(np.uint8))
        v_total += nv
        i_total += nt * 3
        objects.append(rec)
    finally:
        ev.to_mesh_clear()
    if n % 250 == 0:
        log(f"{n}/{len(renderable)} verts={v_total} tris={i_total // 3} t={time.time() - t0:.1f}s")

log(f"geometry done: objects={len(objects)} verts={v_total} tris={i_total // 3}")

pos = np.concatenate(positions)
nrm = np.concatenate(normals)
idx = np.concatenate(indices)
pos.tofile(os.path.join(OUT, "positions.f32"))
nrm.tofile(os.path.join(OUT, "normals.f32"))
idx.tofile(os.path.join(OUT, "indices.u32"))
np.concatenate(tri_mats).tofile(os.path.join(OUT, "tri_material_slot.u8"))

# ---- groups (.g labels form the curated hierarchy)
groups = []
for o in bpy.data.objects:
    if o.name.endswith(".g"):
        groups.append({
            "name": o.name,
            "data_name": o.data.name if o.data else o.name,
            "type": o.type,
            "parent": o.parent.name if o.parent else None,
            "collections": [c.name for c in o.users_collection],
        })

# ---- landmark labels (.t / .s with leader line children .j / .i)
labels = []
for o in bpy.data.objects:
    if o.type != "FONT":
        continue
    suf = o.name.rsplit(".", 1)[-1] if "." in o.name else ""
    if suf not in ("t", "s", "st"):
        continue
    lp = np.array(o.matrix_world.translation, dtype=np.float64)
    anchor = None
    for c in o.children:
        if c.type != "MESH":
            continue
        try:
            ev = c.evaluated_get(depsgraph)
            me = ev.to_mesh()
            if me and len(me.vertices) >= 2:
                vs = np.array([list(ev.matrix_world @ v.co) for v in me.vertices], dtype=np.float64)
                d = np.linalg.norm(vs - lp, axis=1)
                anchor = vs[int(np.argmax(d))]
            ev.to_mesh_clear()
        except Exception as e:
            log(f"label line fail {c.name}: {e}")
        if anchor is not None:
            break
    rec = {
        "name": o.name,
        "data_name": o.data.name if o.data else o.name,
        "parent": o.parent.name if o.parent else None,
        "collections": [c.name for c in o.users_collection],
        "label_pos": [round(float(x), 5) for x in (CONV @ lp)],
        "anchor": [round(float(x), 5) for x in (CONV @ anchor)] if anchor is not None else None,
    }
    labels.append(rec)

meta = {
    "objects": objects,
    "groups": groups,
    "labels": labels,
    "collections": collections,
    "scene_roots": scene_roots,
    "materials": materials,
    "counts": {"verts": int(v_total), "indices": int(i_total)},
}
with open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False)
with open(os.path.join(OUT, "texts.json"), "w", encoding="utf-8") as f:
    json.dump(texts, f, ensure_ascii=False)

log(f"ALL DONE in {time.time() - t0:.1f}s")
LOG.close()
