"""The loaded model: what to draw, what can be picked and named, the clip, the reveal states and the sidecar.

Everything here is CPU-side and GL-free. A model is drawn as *parts* - one per mesh primitive, each with its own
look - and understood as *items*: the pieces a person selects, hides, labels and reads about (the heart's
interventricular septum, one podocyte, "Chordae tendineae" of a downloaded heart). An item owns one or more parts;
most own exactly one. Items are grouped (a sidecar structure, a micro model's layer), and the groups are what the
parts list, the "by group" colours and Shift+click-style group actions work on.

Three kinds of model come in:

* a glTF / GLB file with an optional ``<name>.viewer.json`` sidecar from tools/blender/export_for_viewer.py
  (:class:`Model`) - the heart, the cardiac muscle block, the kidney with its nephron;
* a downloaded model whose names come from heuristics plus a hand-written curation file (``imported.py``);
* one of the app's procedural microanatomy models (``procedural.py``).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import gltf_loader as gl

# vertex layout: pos3 nrm3 dpos3 dnrm3 fib1 col4 uv2 = 19 floats
VERTEX_FLOATS = 19
NO_FIBRE = -1.0e6


@dataclass
class Look:
    """Resolved shading parameters of a part (sidecar recipe over the glTF material)."""
    base: tuple = (0.8, 0.8, 0.8)      # linear RGB
    alpha: float = 1.0
    rough: float = 0.5
    metal: float = 0.0
    f0: float = 0.04
    sss: float = 0.0
    emissive: tuple = (0.0, 0.0, 0.0)
    use_vcol: bool = False
    texture: int | None = None
    alpha_cut: float = 0.0             # > 0: alpha-tested texture (holes), the glTF MASK mode
    stripe: dict | None = None
    mottle: dict | None = None
    facing: tuple | None = None        # (alpha min, alpha max, exponent)
    translucent: bool = False
    double_sided: bool = True
    detail: tuple | None = None        # tissue texturing (mottle, cells per unit, nucleus fraction, fibre axis)


@dataclass
class Part:
    """One draw call: a mesh primitive with its look."""
    id: int                            # 1-based draw id
    node: int
    name: str
    mesh_name: str
    material_name: str
    structure: str                     # structure slug or group name
    structure_id: str
    label: str
    extras: dict
    look: Look
    first: int = 0                     # offset into the shared index buffer (elements)
    count: int = 0
    vertex_base: int = 0
    vertex_count: int = 0
    has_morph: bool = False
    has_fibre: bool = False
    local_centre: np.ndarray = field(default_factory=lambda: np.zeros(3))
    local_radius: float = 0.0
    local_min: np.ndarray = field(default_factory=lambda: np.zeros(3))
    local_max: np.ndarray = field(default_factory=lambda: np.zeros(3))
    visible: bool = True
    role: str = ""                     # "annotation" | "covering" | ""
    item: int = 0                      # index of the item this part belongs to


@dataclass
class Item:
    """A piece that can be picked, named, hidden and labelled."""
    index: int
    key: str                           # the name lessons and practice items use (node name, part name)
    name: str                          # shown to the reader
    group: str                         # the title of its group
    parts: list = field(default_factory=list)
    description: str = ""
    atlas: list = field(default_factory=list)       # names of the matching atlas structures, for "Show in the atlas"
    category: str = "other"
    colour: tuple = (0.7, 0.7, 0.7)    # sRGB, for the parts list and the flat colour modes
    label: bool = True                 # labelled when labels are on
    clip: bool = True                  # cut by the cut-away and by cross-sections
    bulk: bool = False                 # bulk tissue: follows the tissue opacity slider
    rank: float = 0.0                  # procedural models separate their layers upward by rank
    role: str = ""


@dataclass
class Group:
    key: str
    title: str
    items: list                        # item indices
    colour: tuple = (0.7, 0.7, 0.7)    # sRGB


@dataclass
class Structure:                       # the sidecar's grouping, kept for the export's own checks
    key: str
    title: str
    parts: list


def pretty(slug: str) -> str:
    s = re.sub(r"_+", " ", slug).strip()
    s = re.sub(r"\s+(\d+)$", r" \1", s)
    return s[:1].upper() + s[1:] if s else slug


def smooth_normals(pos, idx):
    tri = idx.reshape(-1, 3)
    v0, v1, v2 = pos[tri[:, 0]], pos[tri[:, 1]], pos[tri[:, 2]]
    fn = np.cross(v1 - v0, v2 - v0)
    n = np.zeros_like(pos)
    for k in range(3):
        np.add.at(n, tri[:, k], fn)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    return n.astype(np.float32)


def blender_to_gltf(v):
    x, y, z = (float(c) for c in v)
    return np.array([x, z, -y])


def linear_to_srgb(c):
    c = np.clip(np.asarray(c, dtype=np.float64), 0.0, 1.0)
    return tuple(float(x) for x in np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055))


def srgb_to_linear(c):
    c = np.clip(np.asarray(c, dtype=np.float64), 0.0, 1.0)
    return tuple(float(x) for x in np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4))


class ViewerModel:
    """What every model offers the renderer and the viewer. Subclasses fill the arrays in their constructor."""

    kind = "model"

    def __init__(self):
        self.path = None
        self.doc = None
        self.sidecar = {}
        self.parts: list[Part] = []
        self.items: list[Item] = []
        self.groups: list[Group] = []
        self.structures: list[Structure] = []
        self.vertices = None           # (V, 19) float32
        self.indices = None            # (I,) uint32
        self.anim_vertices = None      # (V,) structured: four morph targets and a phase (procedural animation)
        self.animation = None          # app.micro.anim.Animation of a procedural model
        self.node_world = [np.eye(4)]  # rest world matrices (4x4) per node
        self.root = np.eye(4)          # applied above every node (a downloaded model's curated rotation)
        self.node_weights = {}         # node -> current morph weight
        self.node_offsets = {}         # node -> current reveal offset (glTF space)
        self.item_offsets = None       # (n_items, 3) explode offsets, or None
        self.clip = None
        self.clip_range = (0.0, 0.0)
        self.states = {}
        self.cameras = {}
        self.camera_order = []
        self.metres_per_unit = 0.0     # 0: unknown real size (measuring gives relative lengths)
        self.bounds_min = np.zeros(3)
        self.bounds_max = np.ones(3)
        self._default_weights = {}
        self._item_boxes = None
        self.look_defaults = {}        # renderer Settings this kind of model starts with (exposure, studio light)
        self._n_verts = 0
        self._n_inds = 0

    # ------------------------------------------------------------------ building helpers
    def _finish(self, verts, inds):
        if not self.parts:
            raise gl.GltfError("the file has no triangle meshes to show")
        self.vertices = np.concatenate(verts, 0)
        self.indices = np.concatenate(inds, 0)
        for p in self.parts:
            self.node_weights.setdefault(p.node, 0.0)
        pts = []
        for p in self.parts:
            M = self.node_matrix(p.node)
            for corner in np.array(np.meshgrid(*zip(p.local_min, p.local_max))).T.reshape(-1, 3):
                pts.append((M @ np.append(corner, 1.0))[:3])
        pts = np.array(pts)
        self.bounds_min, self.bounds_max = pts.min(0), pts.max(0)
        self._item_boxes = None

    def _add_part(self, part, pos, nrm, idx, verts, inds, extra=None):
        """Append one primitive's vertices: pos (n, 3), nrm (n, 3) or None; extra fills more columns."""
        n = len(pos)
        v = np.zeros((n, VERTEX_FLOATS), dtype=np.float32)
        v[:, 0:3] = pos
        v[:, 3:6] = nrm if nrm is not None else smooth_normals(pos, idx)
        v[:, 12] = NO_FIBRE
        v[:, 13:17] = 1.0
        if extra is not None:
            extra(v)
        base = self._n_verts
        lo, hi = pos.min(0), pos.max(0)
        c = (lo + hi) / 2
        part.first = self._n_inds
        part.count = int(np.asarray(idx).size)
        part.vertex_base = base
        part.vertex_count = n
        part.local_min, part.local_max, part.local_centre = lo, hi, c
        part.local_radius = float(np.linalg.norm(pos - c, axis=1).max()) if n else 0.0
        verts.append(v)
        inds.append(np.asarray(idx).astype(np.uint32).ravel() + np.uint32(base))
        self.parts.append(part)
        self._n_verts += n
        self._n_inds += part.count

    def _drop_last_part(self, verts, inds):
        p = self.parts.pop()
        verts.pop()
        inds.pop()
        self._n_verts -= p.vertex_count
        self._n_inds -= p.count

    def _build_groups(self, order=None, colours=None):
        seen = {}
        for it in self.items:
            seen.setdefault(it.group, []).append(it.index)
        keys = list(seen)
        if order is not None:
            keys.sort(key=order)
        self.groups = []
        for k in keys:
            idx = seen[k]
            col = (colours or {}).get(k) or self.items[idx[0]].colour
            self.groups.append(Group(k, k, idx, tuple(col)))

    # ------------------------------------------------------------------ queries
    @property
    def triangle_count(self):
        return int(len(self.indices) // 3)

    @property
    def has_teased(self):
        return any(st["offsets"] for st in self.states.values())

    def reveal_nodes(self):
        out = set()
        for st in self.states.values():
            out |= set(st["offsets"].keys())
        return out

    def stripe_params(self):
        for p in self.parts:
            if p.look.stripe:
                return p.look.stripe
        return None

    def um_per_bu(self):
        return float(self.sidecar.get("um_per_bu", 0) or 0)

    def group_of(self, item_index):
        name = self.items[item_index].group
        return next((g for g in self.groups if g.key == name), None)

    # ------------------------------------------------------------------ evaluation
    def evaluate(self, t, reveal_state=None, reveal_amount=0.0):
        """Morph weights at clip time ``t`` and the reveal offsets blended by ``reveal_amount``."""
        self.node_weights = dict(self._default_weights)
        clip_weight = 0.0
        if self.clip is not None:
            for ch in self.clip.channels:
                if ch.path == "weights":
                    val = gl.sample_channel(ch, t)
                    if val is not None and len(val):
                        self.node_weights[ch.node] = float(val[0])
                        clip_weight = max(clip_weight, float(val[0]))
        self.node_offsets = {}
        if reveal_state and reveal_state in self.states and reveal_amount > 0.0:
            for n, o in self.states[reveal_state]["offsets"].items():
                self.node_offsets[n] = o * reveal_amount
        return clip_weight

    def node_matrix(self, node):
        return self.root @ self.node_world[node] if node < len(self.node_world) else self.root

    def part_matrix(self, p: Part):
        M = self.node_matrix(p.node)
        off = self.node_offsets.get(p.node)
        ex = self.item_offsets[p.item] if self.item_offsets is not None else None
        if off is not None or (ex is not None and ex.any()):
            M = M.copy()
            if off is not None:
                M[:3, 3] += off
            if ex is not None:
                M[:3, 3] += ex
        return M

    def world_bounds(self, visible_only=True, visible=None):
        """Axis-aligned bounds of the (visible) parts' boxes at their current offsets (rest shape). ``visible``
        is an optional per-item mask that replaces the parts' own flags."""
        pts = []
        for p in self.parts:
            if visible is not None:
                if not visible[p.item]:
                    continue
            elif visible_only and not p.visible:
                continue
            pts.append(self._box(p))
        if not pts:
            return self.bounds_min, self.bounds_max
        pts = np.concatenate(pts, 0)
        return pts.min(0), pts.max(0)

    def _box(self, p):
        M = self.part_matrix(p)
        box = np.array([[x, y, z, 1.0] for x in (p.local_min[0], p.local_max[0])
                        for y in (p.local_min[1], p.local_max[1]) for z in (p.local_min[2], p.local_max[2])])
        return (box @ M.T)[:, :3]

    def item_bounds(self, indices):
        """World box around the given items, or None."""
        pts = [self._box(p) for i in indices for p in self.items[i].parts]
        if not pts:
            return None
        pts = np.concatenate(pts, 0)
        return pts.min(0), pts.max(0)

    def rest_item_boxes(self):
        """(n, 2, 3) rest-pose world boxes of every item (cached)."""
        if self._item_boxes is None:
            out = np.zeros((len(self.items), 2, 3))
            for it in self.items:
                b = self.item_bounds([it.index])
                if b is not None:
                    out[it.index] = b
            self._item_boxes = out
        return self._item_boxes

    def set_explode(self, amount):
        """Separate the parts by ``amount`` (0 = assembled): each item is pushed away from the middle of the model.
        A procedural model lifts its layers by rank instead (ProceduralModel)."""
        if amount <= 0:
            self.item_offsets = None
            return
        boxes = self.rest_item_boxes()
        self.item_offsets = (boxes.mean(axis=1) - (self.bounds_min + self.bounds_max) / 2) * amount * 1.6

    def part_sphere(self, p: Part):
        M = self.part_matrix(p)
        c = (M @ np.append(p.local_centre, 1.0))[:3]
        return c, p.local_radius * float(np.max(np.linalg.norm(M[:3, :3], axis=0)))

    def item_vertices(self, index, limit=20000):
        """World positions of an item's vertices at rest (subsampled to ``limit``), for label anchors."""
        out = []
        for p in self.items[index].parts:
            v = self.vertices[p.vertex_base:p.vertex_base + p.vertex_count, 0:3]
            if len(v) > limit:
                v = v[np.linspace(0, len(v) - 1, limit).astype(np.int64)]
            M = self.part_matrix(p)
            out.append(v @ M[:3, :3].T + M[:3, 3])
        return np.concatenate(out, 0) if out else np.zeros((0, 3))

    def describe(self, p: Part) -> str:
        um = self.um_per_bu()
        lines = [p.name]
        st = next((s for s in self.structures if p in s.parts), None)
        if st:
            lines.append(st.title)
        if p.label:
            lines.append(p.label)
        if um:
            size = (p.local_max - p.local_min) * um
            lines.append("extent {:.0f} x {:.0f} x {:.0f} µm".format(*sorted(size, reverse=True)))
        return "\n".join(lines)


class Model(ViewerModel):
    """A glTF / GLB file, drawn with its sidecar's look, states and cameras when it has one."""

    kind = "glb"

    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.doc = gl.load(self.path)
        self.sidecar = self._load_sidecar()
        self._build()
        um = self.um_per_bu()
        if um:
            self.metres_per_unit = um * 1e-6

    # ------------------------------------------------------------------ sidecar
    def _load_sidecar(self):
        p = self.path.with_suffix("")
        cands = [Path(str(p) + ".viewer.json"), self.path.with_name(self.path.stem + ".viewer.json")]
        for c in cands:
            if c.is_file():
                try:
                    return json.loads(c.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    return {}
        return {}

    # ------------------------------------------------------------------ build
    def _world_matrices(self):
        doc = self.doc
        n = len(doc.nodes)
        world = [None] * n

        def local(i):
            nd = doc.nodes[i]
            if nd.matrix is not None:
                return nd.matrix
            return gl.trs_matrix(nd.translation, nd.rotation, nd.scale)

        def visit(i, parent):
            world[i] = parent @ local(i)
            for c in doc.nodes[i].children:
                visit(c, world[i])

        for r in doc.scene_roots:
            visit(r, np.eye(4))
        for i in range(n):
            if world[i] is None:
                world[i] = local(i)
        return world

    def _look(self, mat: gl.Material | None, prim_has_col: bool) -> Look:
        look = Look()
        rec = {}
        if mat is not None:
            look.base = tuple(mat.base_colour[:3])
            look.alpha = float(mat.base_colour[3])
            look.rough = mat.roughness
            look.metal = mat.metallic
            ior = mat.ior if mat.ior > 1.0 else 1.5
            look.f0 = ((ior - 1) / (ior + 1)) ** 2 * mat.specular
            look.emissive = tuple(c * mat.emissive_strength for c in mat.emissive)
            look.texture = mat.base_colour_texture
            look.double_sided = mat.double_sided
            look.translucent = mat.alpha_mode == "BLEND" or mat.transmission > 0.0
            if mat.alpha_mode == "MASK" and look.texture is not None:
                look.alpha_cut = float(mat.alpha_cutoff)
            if mat.transmission > 0.0:
                look.alpha = min(look.alpha, 1.0 - 0.8 * mat.transmission)
            rec = (self.sidecar.get("materials") or {}).get(mat.name, {})
        look.use_vcol = prim_has_col
        if rec:
            if "base_colour" in rec:
                look.base = tuple(rec["base_colour"])
            look.rough = float(rec.get("roughness", look.rough))
            look.metal = float(rec.get("metallic", look.metal))
            lvl = float(rec.get("specular_ior_level", 0.5))
            ior = float(rec.get("ior", 1.5))
            look.f0 = ((ior - 1) / (ior + 1)) ** 2 * 2.0 * lvl
            look.sss = float(rec.get("subsurface_weight", 0.0))
            if rec.get("stripe"):
                look.stripe = rec["stripe"]
            if rec.get("mottle"):
                look.mottle = rec["mottle"]
            fa = rec.get("facing_alpha")
            if fa:
                b = float(fa.get("blend", 0.5))
                b = min(max(b, 0.0), 0.99999)
                expo = 2.0 * b if b < 0.5 else 0.5 / (1.0 - b)
                look.facing = (float(fa["min"]), float(fa["max"]), expo)
                look.translucent = True
            elif "alpha" in rec and rec["alpha"] < 0.999:
                look.alpha = float(rec["alpha"])
                look.translucent = True
        elif look.translucent and look.alpha >= 0.99 and look.alpha_cut <= 0.0:
            # a plain GLB loses Blender's facing-weighted alpha: use a sensible thin-membrane default
            look.facing = (0.05, 0.40, 0.7)
        if look.stripe is not None:
            look.use_vcol = False
        return look

    def item_key(self, node_index, prim_index):
        """(key, name, group key) of the item a primitive belongs to: here one item per node."""
        nd = self.doc.nodes[node_index]
        return nd.name, nd.name, None

    def keep_node(self, node_index):
        return True

    def _build(self):
        doc = self.doc
        self.node_world = self._world_matrices()
        verts, inds = [], []
        pid = 0
        roles = self.sidecar.get("roles") or {}
        ann_ids = set(roles.get("annotation", []))
        cov_ids = set(roles.get("covering", []))
        item_of = {}
        slugs = {sid: s.get("slug") for sid, s in (self.sidecar.get("structures") or {}).items()}
        for ni, nd in enumerate(doc.nodes):
            if nd.mesh is None or nd.mesh >= len(doc.meshes) or not self.keep_node(ni):
                continue
            mesh = doc.meshes[nd.mesh]
            for pi, prim in enumerate(mesh.primitives):
                a = prim.attributes
                pos = a["POSITION"][:, :3].astype(np.float32)
                if len(pos) == 0 or len(prim.indices) < 3:
                    continue
                col = a.get("COLOR_0")
                fib_key = next((k for k in a if k.lower() in ("_fiber_u", "_fibre_u")), None)
                uv = a.get(self._uv_set(prim))
                has_morph = bool(prim.targets) and "POSITION" in prim.targets[0]

                def extra(v, prim=prim, col=col, fib_key=fib_key, uv=uv):
                    if prim.targets:
                        t = prim.targets[0]
                        if "POSITION" in t:
                            v[:, 6:9] = t["POSITION"][:, :3]
                        if "NORMAL" in t:
                            v[:, 9:12] = t["NORMAL"][:, :3]
                    if fib_key:
                        v[:, 12] = prim.attributes[fib_key][:, 0]
                    if col is not None:
                        v[:, 13:13 + col.shape[1]] = col
                        if col.shape[1] == 3:
                            v[:, 16] = 1.0
                    if uv is not None:
                        v[:, 17:19] = uv[:, :2]

                mat = doc.materials[prim.material] if prim.material is not None and prim.material < len(doc.materials) else None
                look = self._look(mat, col is not None)
                if look.stripe is not None and not fib_key:
                    look.stripe = None
                    look.use_vcol = col is not None
                if uv is None:
                    look.texture = None
                    look.alpha_cut = 0.0
                ex = dict(mesh.extras)
                ex.pop("targetNames", None)
                ex.update(nd.extras)
                sid = str(ex.get("structure_id", ""))
                slug = str(ex.get("structure", ""))
                if not slug:
                    parent = doc.nodes[nd.parent].name if nd.parent is not None else ""
                    slug = parent if parent and parent not in ("Scene Collection",) else "parts"
                pid += 1
                part = Part(id=pid, node=ni, name=nd.name, mesh_name=mesh.name,
                            material_name=mat.name if mat else "", structure=slug, structure_id=sid,
                            label=str(ex.get("label", "")), extras=ex, look=look, has_morph=has_morph,
                            has_fibre=fib_key is not None)
                if sid in ann_ids or (not ann_ids and re.search(r"scale_bar|annotation|caption|label", slug)):
                    part.role = "annotation"
                elif sid in cov_ids or (not cov_ids and look.translucent):
                    part.role = "covering"
                self._add_part(part, pos, a.get("NORMAL")[:, :3] if a.get("NORMAL") is not None else None,
                               prim.indices, verts, inds, extra)
                key, name, group = self.item_key(ni, pi)
                if key is None:                             # curated away
                    self._drop_last_part(verts, inds)
                    continue
                if key not in item_of:
                    gkey = group or (slugs.get(sid) if sid else None) or slug
                    it = Item(index=len(self.items), key=key, name=name, group=gkey, role=part.role,
                              colour=linear_to_srgb(look.base))
                    item_of[key] = it.index
                    self.items.append(it)
                it = self.items[item_of[key]]
                part.item = it.index
                it.parts.append(part)
        self._finish(verts, inds)

        # sidecar structures (by structure id, else by slug) - the export's own grouping
        groups = {}
        for p in self.parts:
            groups.setdefault(p.structure_id or p.structure, []).append(p)

        def order(k):
            m = re.match(r"S(\d+)$", k or "")
            return (0, int(m.group(1)), k) if m else (1, 0, k or "")

        for key in sorted(groups, key=order):
            ps = groups[key]
            slug = slugs.get(key) or ps[0].structure
            title = pretty(slug) + (f"  ({key})" if re.match(r"S\d+$", key) else "")
            self.structures.append(Structure(key, title, ps))
        # item groups follow the same order; their titles start as the plain structure name
        for it in self.items:
            it.group = pretty(it.group) if re.match(r"^[a-z0-9_]+$", it.group or "") else it.group
        self._build_groups(order=self._group_sid)

        # animation: the named clip, else the first
        want = (self.sidecar.get("clip") or {}).get("name")
        anims = self.doc.animations
        self.clip = next((a for a in anims if a.name == want), anims[0] if anims else None)
        if self.clip is not None:
            self.clip_range = (float(self.clip.t_start), float(self.clip.t_end))
        mesh_w = {}
        for ni, nd in enumerate(doc.nodes):
            if nd.mesh is not None and nd.mesh < len(doc.meshes) and doc.meshes[nd.mesh].weights:
                mesh_w[ni] = float(doc.meshes[nd.mesh].weights[0])
        self._default_weights = mesh_w
        self.node_weights.update(mesh_w)

        # states: sidecar offsets, else the reveal extras
        by_name = {nd.name: i for i, nd in enumerate(doc.nodes)}
        for st in self.sidecar.get("states", []) or []:
            offs = {by_name[n]: np.array(o, dtype=np.float64) for n, o in st.get("offsets", {}).items() if n in by_name}
            self.states[st["name"]] = {"offsets": offs, "frame": st.get("frame"), "description": st.get("description", "")}
        if not self.states:
            offs = {}
            for i, nd in enumerate(doc.nodes):
                ex = nd.extras
                if "reveal_offset_bu" in ex and "reveal_axis" in ex:
                    offs[i] = blender_to_gltf(ex["reveal_axis"]) * float(ex["reveal_offset_bu"])
            if offs:
                self.states = {"assembled": {"offsets": {}, "frame": 0, "description": "assembled"},
                               str(next(iter(doc.nodes[i].extras.get("reveal_state", "teased") for i in offs))):
                                   {"offsets": offs, "frame": None, "description": "reveal from the part extras"}}
        self.cameras = dict(self.sidecar.get("cameras") or {})
        self.camera_order = [c for c in (self.sidecar.get("camera_order") or self.cameras.keys()) if c in self.cameras]

    def _group_sid(self, group_title):
        """Sort key of a group: its sidecar structure id (S01 < S02 ...), else its title."""
        for it in self.items:
            if it.group == group_title and it.parts:
                sid = it.parts[0].structure_id
                m = re.match(r"S(\d+)$", sid or "")
                if m:
                    return (0, int(m.group(1)), group_title)
                break
        return (1, 0, group_title)

    def _uv_set(self, prim):
        return "TEXCOORD_0"
