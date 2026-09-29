"""The loaded model: parts to draw, structures, the contraction clip, the reveal states and the sidecar.

Everything here is CPU-side and GL-free, so the app can reuse it with its own renderer.
"""
from __future__ import annotations

import json
import math
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
    base: tuple = (0.8, 0.8, 0.8)
    alpha: float = 1.0
    rough: float = 0.5
    metal: float = 0.0
    f0: float = 0.04
    sss: float = 0.0
    emissive: tuple = (0.0, 0.0, 0.0)
    use_vcol: bool = False
    texture: int | None = None
    stripe: dict | None = None
    mottle: dict | None = None
    facing: tuple | None = None        # (alpha min, alpha max, exponent)
    translucent: bool = False
    double_sided: bool = True


@dataclass
class Part:
    id: int                            # 1-based draw id (0 = background in the id buffer)
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


@dataclass
class Structure:
    key: str                           # structure id (S01) or group name
    title: str
    parts: list


def pretty(slug: str) -> str:
    s = re.sub(r"_+", " ", slug).strip()
    return s[:1].upper() + s[1:] if s else slug


def _smooth_normals(pos, idx):
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


class Model:
    def __init__(self, path):
        self.path = Path(path)
        self.doc = gl.load(self.path)
        self.sidecar = self._load_sidecar()
        self.parts: list[Part] = []
        self.vertices = None           # (V, 19) float32
        self.indices = None            # (I,) uint32
        self.node_world = []           # rest world matrices (4x4) per node
        self.node_weights = {}         # node -> current morph weight
        self.node_offsets = {}         # node -> current reveal offset (glTF space)
        self.clip = None
        self.clip_range = (0.0, 0.0)
        self.states = {}
        self.cameras = {}
        self.camera_order = []
        self.structures: list[Structure] = []
        self._build()

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
        elif look.translucent and look.alpha >= 0.99:
            # a plain GLB loses Blender's facing-weighted alpha: use a sensible thin-membrane default
            look.facing = (0.05, 0.40, 0.7)
        if look.stripe is not None:
            look.use_vcol = False
        return look

    def _build(self):
        doc = self.doc
        self.node_world = self._world_matrices()
        verts, inds = [], []
        vbase = ibase = 0
        pid = 0
        roles = self.sidecar.get("roles") or {}
        ann_ids = set(roles.get("annotation", []))
        cov_ids = set(roles.get("covering", []))
        for ni, nd in enumerate(doc.nodes):
            if nd.mesh is None or nd.mesh >= len(doc.meshes):
                continue
            mesh = doc.meshes[nd.mesh]
            for prim in mesh.primitives:
                a = prim.attributes
                pos = a["POSITION"][:, :3].astype(np.float32)
                n = len(pos)
                if n == 0 or len(prim.indices) < 3:
                    continue
                v = np.zeros((n, VERTEX_FLOATS), dtype=np.float32)
                v[:, 0:3] = pos
                nrm = a.get("NORMAL")
                v[:, 3:6] = nrm[:, :3] if nrm is not None else _smooth_normals(pos, prim.indices)
                has_morph = False
                if prim.targets:
                    t = prim.targets[0]
                    if "POSITION" in t:
                        v[:, 6:9] = t["POSITION"][:, :3]
                        has_morph = True
                    if "NORMAL" in t:
                        v[:, 9:12] = t["NORMAL"][:, :3]
                fib_key = next((k for k in a if k.lower() in ("_fiber_u", "_fibre_u")), None)
                v[:, 12] = a[fib_key][:, 0] if fib_key else NO_FIBRE
                col = a.get("COLOR_0")
                if col is not None:
                    v[:, 13:13 + col.shape[1]] = col
                    if col.shape[1] == 3:
                        v[:, 16] = 1.0
                else:
                    v[:, 13:17] = 1.0
                uv = a.get("TEXCOORD_0")
                if uv is not None:
                    v[:, 17:19] = uv[:, :2]
                mat = doc.materials[prim.material] if prim.material is not None and prim.material < len(doc.materials) else None
                look = self._look(mat, col is not None)
                if look.stripe is not None and not fib_key:
                    look.stripe = None
                    look.use_vcol = col is not None
                ex = dict(mesh.extras)
                ex.pop("targetNames", None)
                ex.update(nd.extras)
                sid = str(ex.get("structure_id", ""))
                slug = str(ex.get("structure", ""))
                if not slug:
                    parent = doc.nodes[nd.parent].name if nd.parent is not None else ""
                    slug = parent if parent and parent not in ("Scene Collection",) else "parts"
                pid += 1
                lo, hi = pos.min(0), pos.max(0)
                c = (lo + hi) / 2
                part = Part(
                    id=pid, node=ni, name=nd.name, mesh_name=mesh.name, material_name=mat.name if mat else "",
                    structure=slug, structure_id=sid, label=str(ex.get("label", "")), extras=ex, look=look,
                    first=ibase, count=len(prim.indices), vertex_base=vbase, vertex_count=n,
                    has_morph=has_morph, has_fibre=fib_key is not None,
                    local_centre=c, local_radius=float(np.linalg.norm(pos - c, axis=1).max()),
                    local_min=lo, local_max=hi)
                if sid in ann_ids or (not ann_ids and re.search(r"scale_bar|annotation|caption|label", slug)):
                    part.role = "annotation"
                elif sid in cov_ids or (not cov_ids and look.translucent):
                    part.role = "covering"
                self.parts.append(part)
                verts.append(v)
                inds.append(prim.indices.astype(np.uint32) + np.uint32(vbase))
                vbase += n
                ibase += len(prim.indices)
        if not self.parts:
            raise gl.GltfError("the file has no triangle meshes to show")
        self.vertices = np.concatenate(verts, 0)
        self.indices = np.concatenate(inds, 0)

        # structures (tree): by structure id, else by slug
        groups = {}
        for p in self.parts:
            key = p.structure_id or p.structure
            groups.setdefault(key, []).append(p)
        slugs = {sid: s.get("slug") for sid, s in (self.sidecar.get("structures") or {}).items()}

        def order(k):
            m = re.match(r"S(\d+)$", k)
            return (0, int(m.group(1)), k) if m else (1, 0, k)

        for key in sorted(groups, key=order):
            ps = groups[key]
            slug = slugs.get(key) or ps[0].structure
            title = pretty(slug) + (f"  ({key})" if re.match(r"S\d+$", key) else "")
            self.structures.append(Structure(key, title, ps))

        # animation: the named clip, else the first
        want = (self.sidecar.get("clip") or {}).get("name")
        anims = self.doc.animations
        self.clip = next((a for a in anims if a.name == want), anims[0] if anims else None)
        if self.clip is not None:
            self.clip_range = (float(self.clip.t_start), float(self.clip.t_end))
        for p in self.parts:
            self.node_weights.setdefault(p.node, 0.0)
        mesh_w = {}
        for ni, nd in enumerate(doc.nodes):
            if nd.mesh is not None and doc.meshes[nd.mesh].weights:
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

        # bounds of the rest pose (world)
        pts = []
        for p in self.parts:
            M = self.node_world[p.node]
            for corner in np.array(np.meshgrid(*zip(p.local_min, p.local_max))).T.reshape(-1, 3):
                pts.append((M @ np.append(corner, 1.0))[:3])
        pts = np.array(pts)
        self.bounds_min, self.bounds_max = pts.min(0), pts.max(0)

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

    def part_matrix(self, p: Part):
        M = self.node_world[p.node]
        off = self.node_offsets.get(p.node)
        if off is not None:
            M = M.copy()
            M[:3, 3] += off
        return M

    def world_bounds(self, visible_only=True):
        """Axis-aligned bounds of the (visible) parts' boxes at their current offsets (rest shape)."""
        pts = []
        for p in self.parts:
            if visible_only and not p.visible:
                continue
            M = self.part_matrix(p)
            box = np.array([[x, y, z, 1.0] for x in (p.local_min[0], p.local_max[0])
                            for y in (p.local_min[1], p.local_max[1]) for z in (p.local_min[2], p.local_max[2])])
            pts.append((box @ M.T)[:, :3])
        if not pts:
            return self.bounds_min, self.bounds_max
        pts = np.concatenate(pts, 0)
        return pts.min(0), pts.max(0)

    def part_sphere(self, p: Part):
        M = self.part_matrix(p)
        c = (M @ np.append(p.local_centre, 1.0))[:3]
        return c, p.local_radius * float(np.max(np.linalg.norm(M[:3, :3], axis=0)))

    def describe(self, p: Part) -> str:
        um = self.um_per_bu()
        lines = [p.name]
        st = next((s for s in self.structures if p in s.parts), None)
        if st:
            lines.append(st.title)
        if p.label:
            lines.append(p.label)
        if p.extras.get("reveal_role"):
            lines.append(str(p.extras["reveal_role"]))
        if p.extras.get("text"):
            lines.append("“" + str(p.extras["text"]) + "”")
        if um:
            size = (p.local_max - p.local_min) * um
            lines.append("extent {:.0f} x {:.0f} x {:.0f} µm".format(*sorted(size, reverse=True)))
        return "\n".join(lines)
