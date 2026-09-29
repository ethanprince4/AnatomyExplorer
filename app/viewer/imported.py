"""Downloaded models (data/sketchfab_models/<uid>/model.glb) as viewer models.

A downloaded model arrives as one .glb with whatever names its creator's tools produced - "Heart_Heart_0",
"SubTool-3-1234.OBJ", Dutch organ names, meshes split into anonymous chunks. So the file is read into items in two
steps:
1. Heuristics: each mesh is assigned to the nearest named object above it, wrapper nodes the exporters add
   (RootNode, *.fbx, Object_12, ...) are skipped, and chunks of one object merge back into one item.
2. data/content/sketchfab_parts/<uid>.json, written by hand, renames those items into proper anatomical terms,
   groups them, links them to atlas structures, hides clutter and fixes orientation.
tools/sketchfab_parts.py lists the heuristic names of a model so the second file can be written against them.

The model is centred and scaled into a two-unit block and drawn with its own colours: base colour factors, vertex
colours and base colour textures (alpha-tested where the texture is a cut-out).
"""
from __future__ import annotations

import html
import io
import json
import math
import re
from types import SimpleNamespace

import numpy as np

from ..config import ROOT
from ..gltf import Gltf, GltfError
from .model import Item, Look, Part, ViewerModel, linear_to_srgb, srgb_to_linear

CURATION_DIR = ROOT / "data" / "content" / "sketchfab_parts"
LOCAL_DIR = ROOT / "data" / "sketchfab_models"
MAX_PARTS = 1000                   # beyond this a parts list is useless: one item per group instead
MODEL_SIZE = 2.0

# names exporters and Sketchfab's converter wrap around the real objects: never a part's name
WRAPPER = re.compile(r"^(|root|rootnode|sketchfab_model|sketchfab_scene|gltf_scenerootnode|sketchfab\.timeframe"
                     r"|frame_\d+|object_\d+|_unknown_ref_node_.*|collada visual scene group|scene|default scene"
                     r"|world|group\d*|mesh\d*|polysurface\d*|[0-9a-f]{32}(\.\w+)?)$", re.I)
# names that are really file names: used only when nothing better is above a mesh
FILEISH = re.compile(r"(^/|\.(fbx|obj|gles|osgb|stl|dae|blend|3ds|ply|max|c4d|ma|mb|ztl|glb|gltf)$)", re.I)
GENERIC_MATERIAL = re.compile(r"^(|material|material_\d+(_\d+)?|mat|defaultmat|default|lambert\d*|phong\d*|blinn\d*)$",
                              re.I)


def _is_wrapper(name):
    return bool(WRAPPER.match(name.strip()))


def clean_name(raw):
    """'Left_zygomatic:STL_Output_from_geomagic...' -> 'Left zygomatic'; '/a/b/SubTool-3-12949775.OBJ' -> 'SubTool 3'."""
    s = raw.strip().rsplit("/", 1)[-1]
    s = s.split(":", 1)[0]
    s = re.sub(r"\.(fbx|obj|gles|osgb|stl|dae|blend|ztl)\b.*$", "", s, flags=re.I)
    s = re.sub(r"^(SubTool-\d+)-\d+$", r"\1", s)
    s = re.sub(r"[_\s]+", " ", s).strip()
    s = re.sub(r"\s*\.\d{3}$", "", s)                    # Blender duplicate suffixes
    return s[:1].upper() + s[1:] if s else raw


def _object_and_group(path):
    """(part name, group name) for a mesh at the end of `path` (node names from the root)."""
    names = list(path)
    mesh_node = names[-1]
    # an exporter names the mesh node after its object plus material: "Heart_Heart_0" under "Heart"
    if len(names) >= 2 and names[-2] and not _is_wrapper(names[-2]) and mesh_node.startswith(names[-2]):
        names = names[:-1]
    obj_i = next((i for i in range(len(names) - 1, -1, -1)
                  if not _is_wrapper(names[i]) and not FILEISH.search(names[i])), None)
    if obj_i is None:
        obj_i = next((i for i in range(len(names) - 1, -1, -1) if not _is_wrapper(names[i])), None)
    if obj_i is None:
        return "Model", ""
    group = next((names[i] for i in range(obj_i - 1, -1, -1)
                  if not _is_wrapper(names[i]) and not FILEISH.search(names[i])), "")
    return clean_name(names[obj_i]), clean_name(group) if group else ""


def _keep(path):
    """Animated 'timeframe' models store every frame as a copy of the scene; show the first."""
    for n in path:
        m = re.match(r"^frame_(\d+)$", n)
        if m:
            return m.group(1) == "0"
    return True


def _material(g, p):
    return g.materials[p.material] if p.material is not None and p.material < len(g.materials) else None


def part_keys(g, prims):
    """(part name, group) for every primitive. An object drawn with several materials is usually several things
    painted differently (bone and marrow, vessel wall layers), so it splits into one part per material."""
    objects = [_object_and_group(p.path) for p in prims]
    mats = {}
    for obj, p in zip(objects, prims):
        mats.setdefault(obj, []).append(p.material)
    keys = []
    for obj, p in zip(objects, prims):
        distinct = list(dict.fromkeys(mats[obj]))
        if len(distinct) < 2:
            keys.append(obj)
            continue
        m = _material(g, p)
        label = clean_name(m.name) if m is not None and not GENERIC_MATERIAL.match(m.name or "") else ""
        keys.append((label or f"{obj[0]} part {distinct.index(p.material) + 1}", obj[0]))
    return keys


def default_parts(glb_path):
    """[(part name, group, triangle count, material names)] as the heuristics see the file - what curation keys
    refer to."""
    g = Gltf(glb_path)
    prims = g.primitives(keep=_keep)
    seen = {}
    for key, p in zip(part_keys(g, prims), prims):
        tris, names = seen.get(key, (0, []))
        m = _material(g, p)
        seen[key] = (tris + len(p.idx), names + ([m.name] if m is not None and m.name not in names else []))
    return [(n, grp, t, mats) for (n, grp), (t, mats) in seen.items()]


def load_curation(folder=CURATION_DIR):
    """{uid: curation} from data/content/sketchfab_parts/<uid>.json - one hand-written file per model."""
    out = {}
    if not folder.exists():
        return out
    for f in sorted(folder.glob("*.json")):
        try:
            out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return out


def _rotation(degrees):
    rx, ry, rz = (math.radians(a) for a in degrees)
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return mz @ my @ mx


def _hex_linear(hex_colour):
    h = hex_colour.lstrip("#")
    return srgb_to_linear([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])


class ImportedModel(ViewerModel):
    kind = "downloaded"

    def __init__(self, glb_path, cur=None):
        super().__init__()
        from pathlib import Path
        self.path = glb_path = Path(glb_path)
        cur = cur or {}
        overrides = cur.get("parts", {})
        use_vcol = cur.get("vertex_colors", True)
        g = Gltf(glb_path)
        raw_mats = g.json.get("materials", [])
        prims = g.primitives(keep=_keep)

        # ---- primitives into items (curation first)
        groups, order = {}, []
        for (name, group), p in zip(part_keys(g, prims), prims):
            k = f"{group}/{name}" if f"{group}/{name}" in overrides else name
            o = overrides.get(k)
            if o is None and k in overrides:
                continue                                           # curated away (null)
            o = o or {}
            if o.get("hide"):
                continue
            name = o.get("name", name)
            group = o.get("group", group or cur.get("default_group", "Model"))
            key = (group, name)
            if key not in groups:
                groups[key] = {"prims": [], "o": dict(o)}
                order.append(key)
            else:                           # pieces merged under one name: whichever piece has a field supplies it
                for fld, value in o.items():
                    groups[key]["o"].setdefault(fld, value)
            groups[key]["prims"].append(p)
        if len(order) > MAX_PARTS:
            merged = {}
            for (group, name) in order:
                merged.setdefault((group, group), {"prims": [], "o": {}})["prims"].extend(groups[(group, name)]["prims"])
            groups, order = merged, list(merged)
        if len(order) > MAX_PARTS:
            everything = [p for key in order for p in groups[key]["prims"]]
            groups, order = {("Model", "Model"): {"prims": everything, "o": {}}}, [("Model", "Model")]
        if not order:
            raise GltfError("nothing in this file can be drawn")

        # ---- textures: the images the drawn materials use, with cut-outs told apart from see-through gradients
        self.doc = SimpleNamespace(images=[])
        image_of, cutout = {}, set()
        for p in prims:
            m = _material(g, p)
            if m is not None and m.texture is not None and p.uv is not None and m.texture not in image_of:
                data = g.image_bytes(m.texture)
                if not data:
                    continue
                image_of[m.texture] = len(self.doc.images)
                self.doc.images.append(data)
                if m.alpha_mode == "BLEND" and self._is_cutout(data):
                    cutout.add(m.texture)

        # ---- items, one draw part per material within each
        verts, inds = [], []
        rot = _rotation(cur["rotate"]) if cur.get("rotate") else np.eye(3)
        for key in order:
            group, name = key
            o = groups[key]["o"]
            override = _hex_linear(o["color"]) if o.get("color") else None
            it = Item(index=len(self.items), key=name, name=name, group=group, description=o.get("description", ""),
                      category=o.get("category", "organ"), label=bool(o.get("label", True)),
                      atlas=list(o.get("structures", ())))
            by_mat = {}
            for p in groups[key]["prims"]:
                by_mat.setdefault(p.material, []).append(p)
            shown = []
            for mi, ps in by_mat.items():
                m = _material(g, ps[0])
                rm = raw_mats[mi] if mi is not None and mi < len(raw_mats) else {}
                look = self._look(m, rm, override, image_of, cutout, o)
                pos, nrm, idx, uv, col = self._concat(ps, look.texture is not None, use_vcol)
                if nrm is None:
                    nrm_arr = None
                else:
                    nrm_arr = nrm
                look.use_vcol = col is not None and override is None
                part = Part(id=len(self.parts) + 1, node=0, name=name, mesh_name=name,
                            material_name=m.name if m is not None else "", structure=group, structure_id="",
                            label="", extras={}, look=look, item=it.index)

                def extra(v, uv=uv, col=col):
                    if uv is not None:
                        v[:, 17:19] = uv
                    if col is not None:
                        v[:, 13:17] = col

                self._add_part(part, (pos @ rot.T).astype(np.float32),
                               (nrm_arr @ rot.T).astype(np.float32) if nrm_arr is not None else None,
                               idx, verts, inds, extra)
                it.parts.append(part)
                shown.append(look.base)
            it.colour = linear_to_srgb(np.mean(np.array(shown), axis=0)) if shown else (0.7, 0.7, 0.7)
            it.bulk = any(pt.look.translucent for pt in it.parts)
            self.items.append(it)
        self.node_world = [np.eye(4)]
        # ---- centre and scale into the two-unit block
        allpos = np.concatenate([v[:, 0:3] for v in verts])
        lo, hi = allpos.min(0), allpos.max(0)
        centre = (lo + hi) / 2
        k = MODEL_SIZE / max(float((hi - lo).max()), 1e-9)
        self.root = np.array([[k, 0, 0, -k * centre[0]], [0, k, 0, -k * centre[1]], [0, 0, k, -k * centre[2]],
                              [0, 0, 0, 1]], dtype=np.float64)
        self._finish(verts, inds)
        self._build_groups()
        # glTF is meant to be in metres but these files rarely are (hearts a metre wide, an abdomen 700 m), so a real
        # scale exists only when curation states the model's size; without one, measuring shows relative lengths
        self.metres_per_unit = float(cur["size_mm"]) / 1000.0 / MODEL_SIZE if cur.get("size_mm") else 0.0
        self.look_defaults = {"exposure": 0.2, "studio": 0.45}
        view = cur.get("view") or [0.0, 8.0]
        try:
            self.home = (math.radians(float(view[0])), math.radians(float(view[1])))
        except (TypeError, ValueError, IndexError):
            self.home = (0.0, math.radians(8.0))

    @staticmethod
    def _is_cutout(data):
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(data))
            if "A" not in im.getbands():
                return False
            im.thumbnail((256, 256))
            a = np.asarray(im.getchannel("A"), dtype=np.uint8)
        except Exception:                               # noqa: BLE001 - an unreadable image is not a cut-out
            return False
        return (a < 128).mean() > 0.01 and ((a > 12) & (a < 243)).mean() < 0.10

    @staticmethod
    def _look(m, rm, override, image_of, cutout, o):
        factor = np.array(m.factor if m is not None else [1, 1, 1, 1], dtype=np.float64)
        pbr = rm.get("pbrMetallicRoughness") or {}
        rough = float(np.clip(pbr.get("roughnessFactor", 0.55), 0.35, 0.85))
        look = Look(base=tuple(override if override is not None else factor[:3]), alpha=float(factor[3]),
                    rough=rough, metal=0.0, f0=0.04, sss=0.08)
        if m is not None and m.texture is not None and m.texture in image_of:
            look.texture = image_of[m.texture]
            if m.alpha_mode == "MASK":
                look.alpha_cut = float(m.alpha_cutoff)
            elif m.alpha_mode == "BLEND" and m.texture in cutout:
                look.alpha_cut = 0.5
        if m is not None and m.alpha_mode == "BLEND" and look.alpha_cut <= 0.0:
            look.alpha = float(np.clip(look.alpha, 0.05, 1.0))
            look.translucent = look.alpha < 0.999
        if m is not None and m.transmission > 0:
            look.alpha = min(look.alpha, float(np.clip(1.0 - 0.75 * m.transmission, 0.2, 1.0)))
            look.translucent = True
        if "alpha" in o:
            look.alpha = float(o["alpha"])
            look.translucent = look.alpha < 0.999
        if look.translucent and look.alpha >= 0.99:
            look.alpha = 0.5
        return look

    @staticmethod
    def _concat(ps, textured, use_vcol):
        pos, nrm, idx, uv, col = [], [], [], [], []
        off = 0
        have_nrm = all(p.nrm is not None for p in ps)
        have_col = use_vcol and any(p.color is not None for p in ps)
        for p in ps:
            n = len(p.pos)
            pos.append(p.pos)
            if have_nrm:
                nrm.append(p.nrm)
            idx.append(p.idx + off)
            uv.append(p.uv if (textured and p.uv is not None) else np.zeros((n, 2), np.float32))
            if have_col:
                col.append(p.color if p.color is not None else np.ones((n, 4), np.float32))
            off += n
        P = np.concatenate(pos)
        N = np.concatenate(nrm) if have_nrm else None
        if N is None:
            from ..micro.geometry import compute_normals
            N = compute_normals(P, np.concatenate(idx))
        return (P, N, np.concatenate(idx), np.concatenate(uv).astype(np.float32) if textured else None,
                np.concatenate(col).astype(np.float32) if have_col else None)


def local_uids():
    """uids of every model that has been downloaded."""
    if not LOCAL_DIR.exists():
        return []
    return sorted(d.name for d in LOCAL_DIR.iterdir() if (d / "model.glb").exists() and (d / "info.json").exists())


def local_info(uid):
    try:
        return json.loads((LOCAL_DIR / uid / "info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def credit_html(info):
    i = {k: html.escape(str(v), quote=True) for k, v in (info or {}).items()}
    who = f'<a href="{i["author_url"]}">{i["author"]}</a>' if i.get("author_url") else i.get("author", "")
    lic = f'<a href="{i["license_url"]}">{i["license"]}</a>' if i.get("license_url") else i.get("license", "")
    src = f' · from <a href="{i["source_url"]}">Sketchfab</a>' if i.get("source_url") else ""
    return f"By {who} · {lic}{src}"
