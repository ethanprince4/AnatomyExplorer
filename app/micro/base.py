"""Micro-model infrastructure: parts, models and a Dataset-compatible adapter for the 3D viewport."""
from collections import OrderedDict, defaultdict

import numpy as np
from PySide6.QtGui import QColor

from .geometry import Mesh


def rgb(hex_color):
    c = QColor(hex_color)
    return [c.redF(), c.greenF(), c.blueF()]


def tone(color, ceiling=0.78):
    """Pull a colour down until the renderer's key light and tone map stop clipping it to white.

    Micro models are lit from close range with a bright key, so pale tissue (keratin, colloid, cartilage, the
    corneal stroma) blows out and loses all of its surface relief. Scaling brightness while keeping the hue keeps
    the authored colours readable and lets the shading show."""
    m = max(color)
    return color if m <= ceiling else [c * ceiling / m for c in color]


# Surface texturing for the shader's tissue mode, per material category:
# (colour mottling, cells per unit on cut faces, fraction of cells showing a nucleus, fibre axis 0 none/1 x/2 y/3 z)
DETAIL_DEFAULTS = {
    "skin": (0.10, 95.0, 0.55, 0), "mucosa": (0.12, 115.0, 0.75, 0), "gland": (0.10, 120.0, 0.85, 0),
    "muscle": (0.08, 70.0, 0.35, 1), "fascia": (0.14, 55.0, 0.18, 0), "fat": (0.06, 28.0, 0.12, 0),
    "nerve": (0.07, 65.0, 0.30, 1), "artery": (0.06, 80.0, 0.25, 0), "vein": (0.06, 80.0, 0.25, 0),
    "cartilage": (0.07, 45.0, 0.50, 0), "bone": (0.10, 40.0, 0.30, 0), "lymph": (0.10, 160.0, 0.95, 0),
    "ligament": (0.10, 60.0, 0.15, 1), "tendon": (0.08, 55.0, 0.15, 1), "serosa": (0.06, 80.0, 0.20, 0),
    "nucleus": (0.10, 140.0, 0.90, 0), "brain": (0.08, 90.0, 0.30, 0), "white_matter": (0.06, 60.0, 0.15, 0),
    "organ": (0.10, 100.0, 0.70, 0), "csf": (0.02, 0.0, 0.0, 0), "nail": (0.06, 30.0, 0.05, 0),
    "lung": (0.08, 90.0, 0.40, 0), "eye": (0.03, 0.0, 0.0, 0), "other": (0.08, 60.0, 0.30, 0),
}


class Part:
    def __init__(self, name, group, color, mesh, description, alpha=1.0, category="other", label=True, rank=0,
                 clip=False, bulk=False, detail=None):
        self.clip = clip or bulk
        self.bulk = bulk
        self.name = name
        self.group = group
        self.color = color
        self.mesh = mesh
        self.description = description
        self.alpha = alpha
        self.category = category
        self.label = label
        self.rank = rank
        self.detail = tuple(detail) if detail is not None else DETAIL_DEFAULTS.get(category, DETAIL_DEFAULTS["other"])


class MicroModel:
    def __init__(self, id, name, summary, builder, targets=None, histology=(), related=(), scale_note="",
                 cutaway=((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)), cut_at=(0.0, 0.0), clinical=()):
        self.id = id
        self.name = name
        self.summary = summary
        self.builder = builder
        self.targets = targets or {}
        self.histology = list(histology)
        self.related = list(related)
        self.scale_note = scale_note
        self.cutaway = cutaway
        self.cut_at = cut_at
        self.clinical = list(clinical)
        self._parts = None

    def parts(self):
        if self._parts is None:
            from .cache import load_parts, save_parts, source_digest
            digest = source_digest(self)
            parts = load_parts(self.id, digest)
            if parts is None:
                parts = self.build()
                try:
                    save_parts(self.id, parts, digest)
                except OSError:
                    pass
            self._parts = parts
        return self._parts

    def build(self):
        return [p for p in self.builder() if p.mesh.parts]


class MicroDataset:
    """Implements the subset of app.data.Dataset used by Viewport, Renderer and SceneState."""

    def __init__(self, model):
        self.model = model
        parts = model.parts()
        self.parts = parts
        groups = list(OrderedDict.fromkeys(p.group for p in parts))
        self.systems = []
        for g in groups:
            first = next(p for p in parts if p.group == g)
            self.systems.append({"key": g, "name": g, "default_visible": True, "color": tone(rgb(first.color)),
                                 "subsystems": []})
        self.system_index = {g: i for i, g in enumerate(groups)}
        self.subsystems = []
        self.subsystem_index = {}
        self.subsystem_default = []
        self.subsystem_system = np.zeros(0, dtype=np.int32)
        self.subsystems_by_system = [np.zeros(0, dtype=np.int64) for _ in groups]
        self.regions = []
        self.region_bit = {}
        self.landmarks = []
        self.landmarks_of = defaultdict(list)
        self.materials = []
        self.structures = []
        self.by_base = defaultdict(list)
        self.by_name = defaultdict(list)

        positions, normals, objs, mats, indices = [], [], [], [], []
        v_off = 0
        i_off = 0
        for sid, p in enumerate(parts):
            pos, nrm, idx = p.mesh.arrays()
            positions.append(pos)
            normals.append(nrm)
            objs.append(np.full(len(pos), sid, dtype=np.uint16))
            mats.append(np.full(len(pos), sid, dtype=np.uint16))
            indices.append((idx + v_off).astype(np.uint32))
            col = tone(rgb(p.color))
            det = list(p.detail)
            det[0] = min(det[0] * 1.6, 0.34)        # micro tissue needs visible colour variation, not a flat wash
            self.materials.append({"name": p.name, "category": p.category, "color": col, "alpha": p.alpha,
                                   "distinct": col, "detail": det})
            bmin, bmax = pos.min(axis=0), pos.max(axis=0)
            self.structures.append({
                "id": sid, "name": p.name, "base": p.name, "side": "", "role": None, "system": p.group,
                "subsystem": None, "i_start": i_off, "i_count": len(idx) * 3, "regions": [], "latin": None,
                "bbox": [bmin.tolist(), bmax.tolist()], "centroid": pos.mean(axis=0).tolist(), "material": sid,
            })
            self.by_base[(p.name, p.group, None)].append(sid)
            self.by_name[p.name].append(sid)
            if p.label:
                score = pos[:, 1] * 0.6 + pos[:, 2] * 1.0 + pos[:, 0] * 0.15
                anchor = pos[int(np.argmax(score))]
                self.landmarks_of[sid].append(len(self.landmarks))
                self.landmarks.append({"name": p.name, "sid": sid, "anchor": anchor.tolist(), "def": None})
            v_off += len(pos)
            i_off += len(idx) * 3
        self.n = len(parts)
        self._positions = np.concatenate(positions)
        self._normals = np.concatenate(normals)
        self._objs = np.concatenate(objs)
        self._mats = np.concatenate(mats)
        self._indices = np.concatenate(indices)
        self.part_vertex_ranges = []
        off = 0
        for p in positions:
            self.part_vertex_ranges.append((off, off + len(p)))
            off += len(p)
        self.system_of = np.array([self.system_index[p.group] for p in parts], dtype=np.int32)
        self.subsystem_of = np.full(self.n, -1, dtype=np.int32)
        self.region_mask = np.zeros(self.n, dtype=np.int64)
        self.bbox_min = np.array([s["bbox"][0] for s in self.structures])
        self.bbox_max = np.array([s["bbox"][1] for s in self.structures])
        self.centroid = np.array([s["centroid"] for s in self.structures])
        self.scene_bbox = np.array([self.bbox_min.min(axis=0), self.bbox_max.max(axis=0)])
        self.counts = {"vertices": len(self._positions), "triangles": len(self._indices)}
        self.ranks = np.array([p.rank for p in parts], dtype=np.float32)
        self.cap_depth = True            # cut faces sit on the plane, so nested parts read as sections
        self.detail_shading = True
        self.noclip_mask = np.array([not p.clip for p in parts], dtype=bool)
        self.bulk_mask = np.array([p.bulk for p in parts], dtype=bool)

    def vertex_bytes(self, explode=0.0):
        vbuf = np.zeros(len(self._positions), dtype=[("pos", "<f4", 3), ("nrm", "<f4", 3), ("obj", "<u2"),
                                                     ("mat", "<u2")])
        pos = self._positions.copy()
        if explode:
            pos[:, 1] += self.ranks[self._objs] * explode
        vbuf["pos"] = pos
        vbuf["nrm"] = self._normals
        vbuf["obj"] = self._objs
        vbuf["mat"] = self._mats
        return vbuf.view(np.uint8).ravel()

    def load_geometry(self):
        return self.vertex_bytes(), self._indices.view(np.uint8).ravel()

    def bounds_of(self, sids):
        sids = list(sids)
        if not sids:
            return None
        return self.bbox_min[sids].min(axis=0), self.bbox_max[sids].max(axis=0)

    def counterpart(self, sid):
        return []

    def structures_named(self, name):
        return list(self.by_name.get(name, ()))
