"""Sketchfab models that are on disk (fetched with tools/fetch_sketchfab.py) shown natively, in the microanatomy viewer.

A downloaded model arrives as one .glb with whatever names its creator's tools produced - "Heart_Heart_0",
"SubTool-3-1234.OBJ", Dutch organ names, meshes split into anonymous chunks. So the file is read into parts in two
steps:
1. Heuristics: each mesh is assigned to the nearest named object above it, wrapper nodes the exporters add
   (RootNode, *.fbx, Object_12, ...) are skipped, and chunks of one object merge back into one part.
2. data/content/sketchfab_parts/<uid>.json, written by hand, renames those parts into proper anatomical terms, groups
   them, links them to atlas structures, hides clutter and fixes orientation.
tools/sketchfab_parts.py lists the heuristic names of a model so the second file can be written against them.

The model is centred and scaled to the two-unit block the micro viewer is built around, and draws with its own
colours: base colour factors, vertex colours and base colour textures (see ImportedDataset).
"""
import html
import io
import json
import math
import re

import numpy as np

from .config import ROOT
from .gltf import Gltf, GltfError
from .micro.base import MicroDataset, Part
from .micro.geometry import Mesh
from .sketchfab import LOCAL_DIR

CURATION_DIR = ROOT / "data" / "content" / "sketchfab_parts"
MAX_PARTS = 1000                   # the renderer's material table is 1024 wide
TEXTURE_BUDGET = 192 * 1024 * 1024  # bytes of albedo texture, all layers and mip levels together
MODEL_SIZE = 2.0                   # the micro viewer's block is two units across

# names exporters and Sketchfab's converter wrap around the real objects: never a part's name
WRAPPER = re.compile(r"^(|root|rootnode|sketchfab_model|sketchfab_scene|gltf_scenerootnode|sketchfab\.timeframe"
                     r"|frame_\d+|object_\d+|_unknown_ref_node_.*|collada visual scene group|scene|default scene"
                     r"|world|group\d*|mesh\d*|polysurface\d*|[0-9a-f]{32}(\.\w+)?)$", re.I)
# names that are really file names: used only when nothing better is above a mesh
FILEISH = re.compile(r"(^/|\.(fbx|obj|gles|osgb|stl|dae|blend|3ds|ply|max|c4d|ma|mb|ztl|glb|gltf)$)", re.I)


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


def _srgb(linear):
    linear = np.clip(linear, 0.0, 1.0)
    return np.where(linear <= 0.0031308, linear * 12.92, 1.055 * np.power(linear, 1 / 2.4) - 0.055)


def _rotation(degrees):
    rx, ry, rz = (math.radians(a) for a in degrees)
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return mz @ my @ mx


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


class ImportedPart(Part):
    def __init__(self, *args, uv=None, tint=None, layer=None, structures=(), **kw):
        super().__init__(*args, **kw)
        self.uv = uv                  # (n, 2) float32
        self.tint = tint              # (n, 4) uint8, sRGB
        self.layer = layer            # (n,) float32, -1 where untextured
        self.structures = list(structures)


GENERIC_MATERIAL = re.compile(r"^(|material|material_\d+(_\d+)?|mat|defaultmat|default|lambert\d*|phong\d*|blinn\d*)$",
                              re.I)


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


def build_parts(glb_path, cur=None):
    """(parts, texture layers as (n, size, size, 4) uint8 or None, metres per viewer unit) for a downloaded
    model."""
    cur = cur or {}
    overrides = cur.get("parts", {})
    use_vcol = cur.get("vertex_colors", True)
    g = Gltf(glb_path)
    prims = g.primitives(keep=_keep)

    # ---- textures actually used, as layers of one array
    used = []
    for p in prims:
        m = g.materials[p.material] if p.material is not None and p.material < len(g.materials) else None
        if m is not None and m.texture is not None and p.uv is not None and m.texture not in used:
            used.append(m.texture)
    layers = None
    layer_of = {}
    cutout = set()                      # layers whose alpha is holes (0 or 1), not a see-through gradient
    if used:
        from PIL import Image
        opened = []
        for t in used:
            data = g.image_bytes(t)
            try:
                im = Image.open(io.BytesIO(data)) if data else None        # header only: nothing decoded yet
            except OSError:
                im = None
            if im is not None:
                layer_of[t] = len(opened)
                opened.append(im)
        if opened:
            size = max(max(im.size) for im in opened)
            size = 1 << max(0, int(math.ceil(math.log2(size))))
            while size > 256 and len(opened) * size * size * 4 * 4 // 3 > TEXTURE_BUDGET:
                size //= 2
            size = min(size, 4096)
            layers = np.zeros((len(opened), size, size, 4), np.uint8)
            for i, im in enumerate(opened):            # one image decoded at a time
                try:
                    im = im.convert("RGBA")
                except OSError:
                    layers[i] = 255
                    continue
                if im.size != (size, size):
                    im = im.resize((size, size), Image.LANCZOS)
                layers[i] = np.asarray(im, dtype=np.uint8)
                a = layers[i, ..., 3]
                if (a < 128).mean() > 0.01 and ((a > 12) & (a < 243)).mean() < 0.10:
                    cutout.add(i)
    mean_of_layer = {i: layers[i, ..., :3].reshape(-1, 3).mean(axis=0) / 255.0 for i in range(len(layers))} \
        if layers is not None else {}

    # ---- primitives into parts
    groups = {}
    order = []
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
            for field, value in o.items():
                groups[key]["o"].setdefault(field, value)
        groups[key]["prims"].append(p)
    if len(order) > MAX_PARTS:                                  # far too many to list: one part per group instead
        merged = {}
        for (group, name) in order:
            merged.setdefault((group, group), {"prims": [], "o": {}})["prims"].extend(groups[(group, name)]["prims"])
        groups, order = merged, list(merged)
    if len(order) > MAX_PARTS:                                  # still too many: the model as one part
        everything = [p for key in order for p in groups[key]["prims"]]
        groups, order = {("Model", "Model"): {"prims": everything, "o": {}}}, [("Model", "Model")]
    if not order:
        raise GltfError("nothing in this file can be drawn")

    rot = _rotation(cur["rotate"]) if cur.get("rotate") else None
    parts = []
    for key in order:
        group, name = key
        o = groups[key]["o"]
        pos, nrm, idx, uv, tint, layer, cut = [], [], [], [], [], [], []
        off = 0
        blend_alpha = 1.0
        override = None
        if o.get("color"):
            from .micro.base import rgb as _rgb
            override = np.power(np.array(_rgb(o["color"]), np.float32), 2.2)       # sRGB hex -> linear
        for p in groups[key]["prims"]:
            m = _material(g, p)
            factor = np.array(m.factor if m else [1, 1, 1, 1], dtype=np.float32)
            n = len(p.pos)
            col = np.tile(factor, (n, 1))
            if use_vcol and p.color is not None:
                col = col * p.color
            if override is not None:
                col[:, :3] = override
            tex = layer_of.get(m.texture) if m is not None and m.texture is not None and p.uv is not None else None
            # see-through: blended materials by their alpha, glass-like ones by how much light they transmit
            if m is not None and m.alpha_mode == "BLEND":
                blend_alpha = min(blend_alpha, float(np.clip(col[:, 3].mean(), 0.05, 1.0)))
            if m is not None and m.transmission > 0:
                blend_alpha = min(blend_alpha, float(np.clip(1.0 - 0.75 * m.transmission, 0.2, 1.0)))
            # textures with holes (labels on transparent cards, masked leaves) are alpha-tested
            threshold = 0.0
            if tex is not None and m.alpha_mode == "MASK":
                threshold = float(m.alpha_cutoff)
            elif tex is not None and m.alpha_mode == "BLEND" and tex in cutout:
                threshold = 0.5
            pos.append(p.pos)
            if p.nrm is None:
                from .micro.geometry import compute_normals
                nrm.append(compute_normals(p.pos, p.idx))
            else:
                nrm.append(p.nrm)
            idx.append(p.idx + off)
            uv.append(p.uv if tex is not None else np.zeros((n, 2), np.float32))
            layer.append(np.full(n, -1.0 if tex is None else float(tex), np.float32))
            tint.append(col)
            cut.append(np.full(n, max(1, round(threshold * 255)) if threshold > 0 else 0, np.uint8))
            off += n
        P = np.concatenate(pos)
        I = np.concatenate(idx)
        N = np.concatenate(nrm)
        C = np.concatenate(tint)
        L = np.concatenate(layer)
        if rot is not None:
            P = (P @ rot.T).astype(np.float32)
            N = (N @ rot.T).astype(np.float32)
        srgb = _srgb(C[:, :3])
        # the alpha byte carries the alpha-test threshold (0: none)
        tint_u8 = np.concatenate([np.round(srgb * 255), np.concatenate(cut)[:, None]], 1).astype(np.uint8)
        # the colour the part shows as a whole: its tint times the mean of any texture on it
        shown = srgb.copy()
        for li, mean in mean_of_layer.items():
            sel = L == li
            if sel.any():
                shown[sel] *= mean
        rgb = shown.mean(axis=0) if len(shown) else np.array([0.7, 0.7, 0.7])
        alpha = float(o.get("alpha", blend_alpha if blend_alpha < 0.999 else 1.0))
        desc = o.get("description", "")
        parts.append(ImportedPart(name, group, "#%02x%02x%02x" % tuple(int(round(c * 255)) for c in np.clip(rgb, 0, 1)),
                                  Mesh().add(P, I, N), desc, alpha=alpha, category=o.get("category", "organ"),
                                  label=o.get("label", True), clip=True, bulk=alpha < 1.0,
                                  detail=(0.0, 0.0, 0.0, 0), uv=np.concatenate(uv).astype(np.float32),
                                  tint=tint_u8, layer=L, structures=o.get("structures", ())))

    # ---- centre and scale into the viewer's block
    lo = np.min([p.mesh.parts[0][0].min(axis=0) for p in parts], axis=0)
    hi = np.max([p.mesh.parts[0][0].max(axis=0) for p in parts], axis=0)
    centre = (lo + hi) / 2
    extent = max(float((hi - lo).max()), 1e-9)
    k = MODEL_SIZE / extent
    for p in parts:
        v, nn, ii = p.mesh.parts[0]
        p.mesh.parts[0] = (((v - centre) * k).astype(np.float32), nn, ii)
    # glTF is meant to be in metres but these files rarely are (hearts a metre wide, an abdomen 700 m), so a real
    # scale exists only when curation states the model's size; without one, measuring shows relative lengths
    metres = float(cur["size_mm"]) / 1000.0 if cur.get("size_mm") else None
    return parts, layers, metres / MODEL_SIZE if metres else 0.0


class ImportedDataset(MicroDataset):
    """The micro viewer's dataset plus what textured models need: per-vertex UVs, colour and texture layer."""

    def __init__(self, model):
        super().__init__(model)
        self.detail_shading = False
        self.textured = True
        self.texture_layers = model.layers
        uv, tint, layer = [], [], []
        for p in self.parts:
            uv.append(p.uv)
            tint.append(p.tint)
            layer.append(p.layer)
        aux = np.zeros(len(self._positions), dtype=[("uv", "<f4", 2), ("tint", "u1", 4), ("layer", "<f4")])
        aux["uv"] = np.concatenate(uv)
        aux["tint"] = np.concatenate(tint)
        aux["layer"] = np.concatenate(layer)
        self._aux = aux
        # the parts draw their own colours; the material table holds white for that, and the part's overall colour
        # for the flat 'distinct colours' mode and for cut faces
        for i, p in enumerate(self.parts):
            m = self.materials[i]
            m["distinct"] = m["color"]
            m["color"] = [1.0, 1.0, 1.0]
        self.part_centroids = np.array([p.mesh.parts[0][0].mean(axis=0) for p in self.parts])

    def aux_bytes(self):
        return self._aux.view(np.uint8).ravel()

    def vertex_bytes(self, explode=0.0):
        """Separate parts by pushing each away from the model's centre (layers of a micro model separate upwards)."""
        vbuf = np.zeros(len(self._positions), dtype=[("pos", "<f4", 3), ("nrm", "<f4", 3), ("obj", "<u2"),
                                                     ("mat", "<u2")])
        pos = self._positions.copy()
        if explode:
            centre = self.part_centroids.mean(axis=0)
            pos += (self.part_centroids[self._objs] - centre) * explode * 4.0
        vbuf["pos"] = pos
        vbuf["nrm"] = self._normals
        vbuf["obj"] = self._objs
        vbuf["mat"] = self._mats
        return vbuf.view(np.uint8).ravel()


class LocalModel:
    """A downloaded Sketchfab model, shaped like a MicroModel for the micro viewer."""

    def __init__(self, uid, info, catalog_model=None, cur=None):
        self.uid = uid
        self.id = f"sketchfab:{uid}"
        self.info = info
        self.cur = cur or {}
        cm = catalog_model
        self.name = self.cur.get("name") or (cm.name if cm else info.get("name", uid))
        self.summary = self.cur.get("summary") or (cm.summary if cm else "")
        self.scale_note = ""
        self.cutaway = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        self.cut_at = (0.0, 0.0)
        self.cut_on = False
        self.histology = list(cm.histology) if cm else []
        self.related = list(cm.micro) if cm else []
        self.clinical = [tuple(x) for x in self.cur.get("clinical", []) if isinstance(x, (list, tuple)) and len(x) == 2]
        self.structures = list(cm.structures) if cm else []
        view = self.cur.get("view") or [0.0, 8.0]
        try:
            self.home_view = (math.radians(float(view[0])), math.radians(float(view[1])))
        except (TypeError, ValueError, IndexError):
            self.home_view = (0.0, math.radians(8.0))
        self.layers = None
        self.metres_per_unit = None
        self._parts = None

    @property
    def glb(self):
        return LOCAL_DIR / self.uid / "model.glb"

    @property
    def credit_html(self):
        i = {k: html.escape(str(v), quote=True) for k, v in self.info.items()}
        who = f'<a href="{i["author_url"]}">{i["author"]}</a>' if i.get("author_url") else i.get("author", "")
        lic = f'<a href="{i["license_url"]}">{i["license"]}</a>' if i.get("license_url") else i.get("license", "")
        src = f'<a href="{i.get("source_url", "")}">Sketchfab</a>'
        return f"By {who} · {lic} · from {src}"

    def parts(self):
        if self._parts is None:
            self._parts, self.layers, self.metres_per_unit = build_parts(self.glb, self.cur)
        return self._parts

    def dataset(self):
        return ImportedDataset(self)


def local_uids():
    """uids of every model that has been downloaded."""
    if not LOCAL_DIR.exists():
        return []
    return sorted(d.name for d in LOCAL_DIR.iterdir() if (d / "model.glb").exists() and (d / "info.json").exists())


def load_local(uid, catalog_model=None, curation=None):
    d = LOCAL_DIR / uid
    try:
        info = json.loads((d / "info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cur = (curation if curation is not None else load_curation()).get(uid, {})
    return LocalModel(uid, info, catalog_model, cur)
