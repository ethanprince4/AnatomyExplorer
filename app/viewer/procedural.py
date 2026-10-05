"""The app's procedural microanatomy models (app/micro) as viewer models.

A micro model is built by code into named parts (app/micro/base.py: a closed mesh, a colour, an alpha, a tissue
category and texturing, a layer rank and whether the cut-away cuts it) and cached in data/micro_cache. Here each
part becomes one item drawn by the viewer's renderer, with the look the old microanatomy view gave it: its colour,
the sheen of its tissue category, the tissue texturing of its surface and cut faces, and, for the heart and the
pancreas, its animation.
"""
from __future__ import annotations

import math
import re
from copy import deepcopy

import numpy as np

from ..load_control import checkpoint
from ..config import SHADING
from ..micro.base import rgb, tone
from .model import Item, Look, Part, ViewerModel, srgb_to_linear

BLOCK_UNITS = 2.0              # every micro model is built about two units wide
DEFAULT_HOME = (-0.62, 0.42)   # yaw, pitch of the old microanatomy view's home framing


def scale_from_note(note):
    """Millimetres per model unit. Only a note that states the width of the block is trusted; everything else falls
    back to the 3 mm block the models are drawn to."""
    m = re.search(r"block\b[^.]*?(\d+(?:\.\d+)?)\s*mm", (note or "").lower())
    if not m:
        return 1.5
    return max(float(m.group(1)) / BLOCK_UNITS, 1e-4)


def look_for(category, colour_srgb, alpha, detail):
    spec, gloss, _rim = SHADING.get(category, SHADING["other"])
    # the old view's Blinn-Phong exponent as a GGX roughness, its specular strength as a reflectance
    rough = math.sqrt(math.sqrt(2.0 / (gloss + 2.0)))
    lk = Look(base=srgb_to_linear(colour_srgb), alpha=float(alpha), rough=float(np.clip(rough, 0.3, 0.8)),
              f0=0.02 + 0.06 * float(spec), sss=0.04 if category in ("bone", "tooth", "nail", "eye") else 0.15,
              translucent=alpha < 0.999)
    if detail is not None:
        det = [float(x) for x in detail]
        det[0] = min(det[0] * 1.6, 0.34)            # micro tissue needs visible colour variation, not a flat wash
        lk.detail = tuple(det[:4])
    return lk


def draft_look(look, values):
    """Explicit model-only viewing recipe; source materials stay unchanged."""
    if not values:
        return look
    if set(values) - {"alpha", "translucent", "detail"}:
        raise ValueError("Unsupported teaching Look override")
    result = deepcopy(look)
    if "alpha" in values:
        result.alpha = float(values["alpha"])
        if not 0 <= result.alpha <= 1:
            raise ValueError("Invalid teaching alpha")
    if "translucent" in values:
        result.translucent = bool(values["translucent"])
    if "detail" in values:
        detail = tuple(float(v) for v in values["detail"])
        if len(detail) != 3 or not all(math.isfinite(v) and v >= 0 for v in detail):
            raise ValueError("Teaching detail needs three nonnegative finite values")
        result.detail = detail + ((look.detail or (0, 0, 0, 0))[3],)
    return result


class ProceduralModel(ViewerModel):
    kind = "procedural"

    def __init__(self, micro_model, *, parts=None):
        super().__init__()
        self.source = micro_model
        viewing = getattr(micro_model, "viewer_look", None)
        if viewing and getattr(micro_model, "id", None) in {"heart", "whole_heart", "cardiac_muscle"}:
            raise ValueError("Protected model cannot receive a teaching Look")
        checkpoint()
        parts = micro_model.parts() if parts is None else parts
        from ..teaching_content import description as teaching_description
        verts, inds = [], []
        for i, mp in enumerate(parts):
            checkpoint()
            pos, nrm, idx = mp.mesh.arrays()
            if len(pos) == 0 or len(idx) == 0:
                continue
            col = tone(rgb(mp.color))
            look = draft_look(look_for(mp.category, col, mp.alpha, mp.detail), viewing)
            colors = None
            provider = getattr(micro_model, "viewer_vertex_colors", None)
            if callable(provider):
                colors = provider(mp.name, pos)
                if colors is not None:
                    colors = np.asarray(colors, dtype=np.float32)
                    if colors.shape != (len(pos), 3) or not np.isfinite(colors).all() or np.any((colors < 0) | (colors > 1)):
                        raise ValueError("Model vertex colors must be finite linear RGB in [0,1]")
                    look.base = (1.0, 1.0, 1.0)
                    look.use_vcol = True
            part = Part(id=len(self.parts) + 1, node=0, name=mp.name, mesh_name=mp.name, material_name=mp.category,
                        structure=mp.group, structure_id="", label="", extras={}, look=look)
            extra = None if colors is None else lambda vertex, colors=colors: vertex.__setitem__((slice(None), slice(13, 16)), colors)
            self._add_part(part, pos, nrm, idx, verts, inds, extra=extra)
            it = Item(index=len(self.items), key=mp.name, name=mp.name, group=mp.group, parts=[part],
                      description=(mp.description if getattr(micro_model, "runtime_descriptor", None) is not None
                                   else teaching_description(micro_model.id, mp.name, mp.description)),
                      category=mp.category, colour=tuple(col), label=bool(mp.label),
                      clip=bool(mp.clip), bulk=bool(mp.bulk), rank=float(mp.rank))
            part.item = it.index
            self.items.append(it)
            self._part_sources = getattr(self, "_part_sources", [])
            self._part_sources.append(mp)
        self.node_world = [np.eye(4)]
        self._finish(verts, inds)
        self._build_groups()
        anim = getattr(micro_model, "animation", None)
        if anim is not None:
            self._build_animation(anim)
        mpu = getattr(micro_model, "metres_per_unit", None)
        self.metres_per_unit = float(mpu) if mpu else scale_from_note(micro_model.scale_note) / 1000.0
        axes = getattr(micro_model, "cutaway", ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
        self.cutaway = {"axes": [tuple(axes[0]), tuple(axes[1])], "at": tuple(getattr(micro_model, "cut_at", (0.0, 0.0))),
                        "on": bool(getattr(micro_model, "cut_on", True))}
        self.home = tuple(getattr(micro_model, "home_view", DEFAULT_HOME))
        # Authored teaching presets use the same native camera/visibility controls
        # as imported models. Models without presets retain their existing home.
        self.cameras = deepcopy(getattr(micro_model, "viewer_cameras", {}))
        self.camera_order = list(self.cameras)
        start = getattr(micro_model, "start_view", None)
        if start in self.cameras:
            self.sidecar["start_view"] = start
        # the colours were chosen under the old microanatomy view's brighter tone curve
        self.look_defaults = {"exposure": 0.35, "studio": 0.45}

    def _build_animation(self, anim):
        """The per-vertex morph targets and phases (app/micro/anim.py) as a second vertex buffer."""
        n = len(self.vertices)
        buf = np.zeros(n, dtype=[("m", "<f2", (4, 4)), ("phase", "<f4")])
        for p, mp in zip(self.parts, self._part_sources):
            checkpoint()
            data = getattr(mp, "anim", None)
            if not data:
                continue
            m = np.asarray(data["morph"], np.float32)
            k = min(m.shape[1], 4)
            a, b = p.vertex_base, p.vertex_base + p.vertex_count
            buf["m"][a:b, :k, :3] = m[:b - a, :k]
            buf["phase"][a:b] = np.asarray(data["phase"], np.float32)[:b - a]
        self.anim_vertices = buf
        self.animation = anim
        self.anim_names = [it.key for it in self.items]

    def set_explode(self, amount):
        """Lift the layers apart by rank, as the old microanatomy view did."""
        if amount <= 0:
            self.item_offsets = None
            return
        off = np.zeros((len(self.items), 3))
        off[:, 1] = np.array([it.rank for it in self.items], dtype=np.float64) * amount * 0.35
        self.item_offsets = off

    def anim_frame(self, t):
        """(2, n_items, 4) weights and (mode, glow, decay, rate) at cycle phase t (0..1)."""
        return self.animation.frame(self.anim_names, t)


def cutaway_planes(cut, axis_positions=None):
    """Plane equations (n.x, n.y, n.z, d) of a micro model's corner cut-away, exactly as the old microanatomy view
    set them up: the first axis kept on its positive side, the second flipped, the quadrant where both are negative
    removed (clip mode 1)."""
    axes = [cut["axes"][0], cut["axes"][1], (0.0, 1.0, 0.0)]
    pos = list(axis_positions) if axis_positions is not None else [cut["at"][0], cut["at"][1], 0.0]
    flip = [False, True, False]
    planes = []
    for i in range(3):
        n = np.array(axes[i], dtype=np.float64)
        if flip[i]:
            n = -n
        p = np.zeros(3)
        p[[0, 2, 1][i]] = pos[i]
        planes.append((float(n[0]), float(n[1]), float(n[2]), -float(np.dot(n, p))))
    return planes
