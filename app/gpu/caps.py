"""Cut faces ("caps") of the model viewer on wgpu: the filled faces where a clip plane cuts a structure.

A port of the GL cut-face passes (app/viewer/renderer.py `_render_caps` / `_capmix`, app/viewer/shaders.py PARITY_FS, CAP_FS,
CAPMIX_PRE_FS, CAPMIX_FS) as a self-contained module.  The renderer calls four things per frame (details and the place of
each call in the visibility-buffer frame: INTEGRATION.md next to the handoff, summarised in the docstrings below):

    plan = caps.plan(model, geom, draws, VP, V, (w, h), fs, s, clip, camera)    # CPU: which items are cut; None: nothing
    caps.encode_gather(enc, plan)                       # parity + cap passes per cut item (cap_* targets owned here)
    caps.encode_lay_in(enc, id_tex, nd_tex)             # cut faces into the single-sample id / nd targets (before SSAO)
    caps.encode_colour(enc, shade_bg)                   # cut faces shaded into caps.t["col"] (after SSAO, before shading)
    caps.encode_mix / encode_depth                      # GL-style draws onto a colour+depth pair / depth only

Owned targets (`caps.t[...]`, all at the render size, row 0 = top like the visibility buffer): `parity` (depth32float),
`key` (depth32float), `albedo` / `normal` (rgba16float), `id` (rg32float), `zp` (r32float, window depth, 0 = no cut face).
Everything else (geometry pages, res_* textures, the colour / depth targets, the shading bind group) belongs to the renderer.

Matches GL, oddities included: the items and parts, the full-resolution mesh of each part (GL draws `_range`, never an LOD
level), the draw order (ties keep the first draw), the 24-bit cap key and pre-pass depth (quantised in the shaders),
the per-item scissor rectangle, cap darkening 0.80 (tissue look) / 0.62.  Not ported, like in the visibility pass:
morph / explode / animation displacement of the vertices (hook `cap_vertex_world` in caps_gather.wgsl).
"""
from __future__ import annotations

import os
import types
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import wgpu

from app.gpu import cutclass
from app.gpu.geometry import geom_prelude
from app.gpu.shading_uniforms import SIZE as SHADE_SIZE, pack_shading_uniforms

WGSL = Path(__file__).with_name("wgsl")
TU, BU, SS = wgpu.TextureUsage, wgpu.BufferUsage, wgpu.ShaderStage
GL_TO_WGPU_Z = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0.5, 0.5], [0, 0, 0, 1]], dtype=np.float64)

CAPS_PIXELS = 4.0                    # cutclass pixel margin of the cap passes: single-sample targets, a covered pixel centre lies in its triangle

CAPFRAME_BYTES = 336
CAPDRAW_BYTES = 112
CAPCULL_BYTES = 96                   # caps_cull.wgsl CapCull
MIN_DENSITY = 4.0                    # pixels of the item rectangle per triangle below which a part keeps the plain draw
COMPACT_MIN_CLUSTERS = 16            # parts with fewer clusters keep the plain draw: nothing worth masking
MASK_BUDGET = 96 << 20               # bytes of the three masked index copies of one frame (caps_cull.wgsl); parts beyond it draw plain
NO_STREAM = 0
COL_STREAM = 3                       # index of "col" in geometry.VARIABLE
COL_CONST = slice(7, 11)             # columns 13..16 inside const_tail (columns 6..18)

CAP_TARGETS = (("albedo", "rgba16float"), ("normal", "rgba16float"), ("id", "rg32float"), ("zp", "r32float"))


class CapsError(RuntimeError):
    pass


def _text(name):
    return (WGSL / name).read_text(encoding="utf-8")


def _align(n, a):
    return (n + a - 1) // a * a


class _Null:
    def use(self, *a):
        pass


def look_uniforms(part, fs):
    """GLSL-named look uniforms of one part exactly as the GL cap pass sets them (`Renderer._set_look(uc, p, None, fs)`)."""
    from app.viewer.renderer import Renderer
    d = {}
    fake = types.SimpleNamespace(_texture=lambda i: _Null())
    Renderer._set_look(fake, lambda name, value: d.__setitem__(name, value), part, None, fs)
    return d


@dataclass
class CapItem:
    item: int
    rect: tuple                                  # GL scissor rectangle (x0, y0, x1, y1), y from the bottom
    draws: list = field(default_factory=list)    # [cap draw index, page, first index, index count, clip test needed, mirrored, listed]
                                                 # listed >= 0: the part draws its cluster lists (MaskPlan), listed = its row in MaskPlan.table


@dataclass
class MaskPlan:
    table: np.ndarray                            # (n, 8) uint32 per listed part: draw, first cluster, clusters, first index | index count, slot, first chunk, 0
    pages: list                                  # (page, first table entry, one past, first slot, slots), page ascending
    slots: int                                   # clusters over all listed parts; a region has slots * 192 words
    chunks: int                                  # groups of 256 clusters (caps_cull.wgsl cap_class)
    bgs: tuple = ()                              # bind groups (class, offsets, fill) of the cull dispatches
    pg_off: list = field(default_factory=list)   # dynamic offsets of the page records, as pages


@dataclass
class CapPlan:
    items: list
    n_draws: int
    size: tuple
    pages: dict = field(default_factory=dict)    # page -> (bind group over positions + colours, index buffer)
    records: list = field(default_factory=list)  # packed ShadeU bytes of every cap draw (diagnostics)
    ordinals: list = field(default_factory=list)  # per record: its place among the draws GL makes (parts skipped as removed counted)
    mask: object = None                          # MaskPlan or None
    parts: list = field(default_factory=list)    # per record: the part's index in model.parts (diagnostics)


class CapPasses:
    """Cut-face passes on one wgpu device.  ``device`` is a wgpu device (app.gpu.device.Gpu.device)."""

    def __init__(self, device, limits=None):
        self.device = device
        lim = dict(limits or getattr(device, "limits", None) or {})
        self.ubo_align = int(lim.get("min-uniform-buffer-offset-alignment",
                                     lim.get("min_uniform_buffer_offset_alignment", 256)))
        self.shade_stride = _align(SHADE_SIZE, self.ubo_align)
        self.t = {}
        self.v = {}
        self.size = None
        self._modules = {}
        self._cmp = 0                  # geometry stage (0 plain, 1 / 2 compressed)  -- compressed geometry: non-indexed draws, vertex_index = logical index position
        self._pipes = {}
        self._frame_ub = device.create_buffer(size=CAPFRAME_BYTES, usage=BU.UNIFORM | BU.COPY_DST, label="cap_frame")
        self._draw_buf = self._shade_buf = None
        self._draw_cap = self._shade_cap = 0
        self._bg0 = self._bg_su = None
        self._pages = {}                         # (id(geom), page) -> (pos buffer, col buffer, bind group)
        self._dummy = device.create_buffer_with_data(data=np.zeros(4, np.float32).tobytes(), usage=BU.STORAGE,
                                                     label="cap_dummy")
        self._index_of = (None, None)
        self.classify = os.environ.get("ANATOMY_CAPS_CLASSIFY", "1") != "0"   # off: every part keeps the clip test, none is skipped
        self.last_classes = None         # (kept, straddle, removed) part counts of the last plan (diagnostics)
        self.compact = os.environ.get("ANATOMY_CAPS_COMPACT", "1") != "0"   # off: no cluster masks, parts draw their whole range
        self.compact_min = COMPACT_MIN_CLUSTERS
        self.min_density = float(os.environ.get("ANATOMY_CAPS_DENSITY", MIN_DENSITY))
        self.last_density = []
        self.mask_budget = min(MASK_BUDGET, int(lim.get("max-storage-buffer-binding-size",
                                                          lim.get("max_storage_buffer_binding_size", MASK_BUDGET))))
        self.last_mask = None            # MaskPlan of the last plan (diagnostics)
        self._cc_ub = device.create_buffer(size=CAPCULL_BYTES, usage=BU.UNIFORM | BU.COPY_DST, label="cap_cull")
        self._pg_buf = device.create_buffer(size=16 * self.ubo_align, usage=BU.UNIFORM | BU.COPY_DST, label="cap_cull_pg")
        self._clg = (None, None)         # (geom, storage buffer of the cluster boxes)
        self._mb = {}                    # cull pass buffers by name (tab, chk, info, tot, args, out), grown on demand
        self._cull_bgs = None
        self._bg_pg = None
        self._dsel_buf = None
        self._layouts()

    # ------------------------------------------------------------------ layouts, modules, pipelines
    def _layouts(self):
        d = self.device
        V, F, C = SS.VERTEX, SS.FRAGMENT, SS.COMPUTE
        tex = lambda b, st="unfilterable-float": {"binding": b, "visibility": F, "texture": {
            "sample_type": st, "view_dimension": "2d"}}
        self.bgl0 = d.create_bind_group_layout(entries=[
            {"binding": 0, "visibility": V | F | C, "buffer": {"type": "uniform"}},
            {"binding": 1, "visibility": V | F | C, "buffer": {"type": "read-only-storage"}},
            {"binding": 2, "visibility": C, "buffer": {"type": "uniform"}}])
        self.bgl_su = d.create_bind_group_layout(entries=[
            {"binding": 0, "visibility": F, "buffer": {"type": "uniform", "has_dynamic_offset": True,
                                                       "min_binding_size": SHADE_SIZE}},
            {"binding": 8, "visibility": V, "buffer": {"type": "uniform", "has_dynamic_offset": True, "min_binding_size": 16}}])
        self.bgl_page = d.create_bind_group_layout(entries=[
            {"binding": 0, "visibility": V | C, "buffer": {"type": "read-only-storage"}},
            {"binding": 1, "visibility": V | C, "buffer": {"type": "uniform"}}])
        sto = lambda b, ro: {"binding": b, "visibility": C, "buffer": {"type": "read-only-storage" if ro else "storage"}}
        # the three cull dispatches bind subsets of the buffers of caps_cull.wgsl group 1 (the storage buffer limit per stage)
        self.bgl_cc = [d.create_bind_group_layout(entries=[sto(0, True), sto(1, True), sto(2, True), sto(3, False), sto(4, False)]),
                       d.create_bind_group_layout(entries=[sto(1, True), sto(4, False), sto(5, False)]),
                       d.create_bind_group_layout(entries=[sto(1, True), sto(3, False), sto(4, False), sto(6, False)])]
        self.bgl_pg = d.create_bind_group_layout(entries=[
            {"binding": 0, "visibility": C, "buffer": {"type": "uniform", "has_dynamic_offset": True, "min_binding_size": 16}}])
        self.bgl_parity = d.create_bind_group_layout(entries=[tex(0, "depth")])
        self.bgl_lay = d.create_bind_group_layout(entries=[tex(0), tex(1), tex(2), tex(3)])
        self.bgl_mix = d.create_bind_group_layout(entries=[tex(0), tex(1), tex(2), tex(3)])
        self.shade_layout = shade_bind_group_layout(d)

    def _module(self, name):
        if name not in self._modules:
            head = _text("caps_common.wgsl")
            if name == "gather":
                code = (_text("shading.wgsl") + "\n" + head + "\n" + geom_prelude(1, 2, 0, uniform_binding=1, compressed=self._cmp) + "\n"
                        + _text("geom.wgsl") + "\n" + _text("caps_gather.wgsl"))
            elif name == "cull":
                code = (head + "\n" + geom_prelude(1, 2, 0, uniform_binding=1, compressed=self._cmp) + "\n"
                        + _text("geom.wgsl") + "\n" + _text("caps_cull.wgsl"))
            elif name == "lay":
                code = head + "\n" + _text("caps_lay.wgsl")
            elif name == "mix":
                code = _text("shading.wgsl") + "\n" + head + "\n" + _text("caps_mix.wgsl")
            else:
                raise KeyError(name)
            self._modules[name] = self.device.create_shader_module(code=code, label="caps_" + name)
        return self._modules[name]

    def _layout(self, *bgls):
        return self.device.create_pipeline_layout(bind_group_layouts=list(bgls))

    def _pipe(self, key):
        if key in self._pipes:
            return self._pipes[key]
        d = self.device
        prim = {"topology": "triangle-list", "cull_mode": "none", "front_face": "ccw"}
        kind = key[0]
        if kind == "reset":
            m = self._module("gather")
            p = d.create_render_pipeline(
                layout=self._layout(), vertex={"module": m, "entry_point": "vs_reset"}, primitive=prim,
                depth_stencil={"format": "depth32float", "depth_write_enabled": True, "depth_compare": "always"},
                label="cap_reset")
        elif kind == "parity":
            # key = ("parity", clip test needed, mirrored, masked index copy): front faces only (back faces of a mirrored part) by the cull mode
            m = self._module("gather")
            prim = dict(prim, cull_mode="front" if key[2] else "back")
            p = d.create_render_pipeline(
                layout=self._layout(self.bgl0, self.bgl_su, self.bgl_page),
                vertex={"module": m, "entry_point": "vs_cap_i" if key[3] else "vs_cap"}, primitive=prim,
                fragment={"module": m, "entry_point": "fs_parity", "targets": []} if key[1] else None,
                depth_stencil={"format": "depth32float", "depth_write_enabled": True, "depth_compare": "less"},
                label="cap_parity")
        elif kind == "cap":
            # key = ("cap", clip test needed, mirrored, masked index copy): back faces only (front faces of a mirrored part)
            m = self._module("gather")
            prim = dict(prim, cull_mode="back" if key[2] else "front")
            p = d.create_render_pipeline(
                layout=self._layout(self.bgl0, self.bgl_su, self.bgl_page, self.bgl_parity),
                vertex={"module": m, "entry_point": "vs_cap_i" if key[3] else "vs_cap"}, primitive=prim,
                fragment={"module": m, "entry_point": "fs_cap" if key[1] else "fs_cap_kept",
                          "targets": [{"format": f} for _n, f in CAP_TARGETS]},
                depth_stencil={"format": "depth32float", "depth_write_enabled": True, "depth_compare": "less"},
                label="cap_gather")
        elif kind == "cull":
            # key = ("cull", dispatch 0 class / 1 offsets / 2 fill)
            k = key[1]
            lay = d.create_pipeline_layout(bind_group_layouts=[self.bgl0, self.bgl_cc[k]] + ([self.bgl_page, self.bgl_pg] if k == 2 else []))
            p = d.create_compute_pipeline(layout=lay, compute={"module": self._module("cull"), "entry_point": (
                "cap_class", "cap_offsets", "cap_fill")[k]}, label="cap_cull%d" % k)
        elif kind == "lay":
            m = self._module("lay")
            p = d.create_render_pipeline(
                layout=self._layout(self.bgl0, self.bgl_lay), vertex={"module": m, "entry_point": "vs_fsq"},
                primitive=prim, fragment={"module": m, "entry_point": "fs_lay_gl",
                                          "targets": [{"format": "rg32float"}, {"format": "rgba32float"}]},
                label="cap_lay")
        elif kind == "depth":
            _k, dfmt, samples, gl = key
            m = self._module("lay")
            p = d.create_render_pipeline(
                layout=self._layout(self.bgl0, self.bgl_lay), vertex={"module": m, "entry_point": "vs_fsq"},
                primitive=prim, fragment={"module": m, "entry_point": "fs_depth_gl" if gl else "fs_depth", "targets": []},
                depth_stencil={"format": dfmt, "depth_write_enabled": True, "depth_compare": "less"},
                multisample={"count": samples}, label="cap_depth")
        elif kind == "col":
            m = self._module("mix")
            p = d.create_render_pipeline(
                layout=self._layout(self.bgl0, self.shade_layout, self.bgl_mix),
                vertex={"module": m, "entry_point": "vs_fsq"}, primitive=prim,
                fragment={"module": m, "entry_point": "fs_col", "targets": [{"format": "rgba32float"}]}, label="cap_col")
        elif kind == "mix":
            _k, cfmt, dfmt, samples = key
            m = self._module("mix")
            p = d.create_render_pipeline(
                layout=self._layout(self.bgl0, self.shade_layout, self.bgl_mix),
                vertex={"module": m, "entry_point": "vs_fsq"}, primitive=prim,
                fragment={"module": m, "entry_point": "fs_mix", "targets": [{"format": cfmt}]},
                depth_stencil={"format": dfmt, "depth_write_enabled": True, "depth_compare": "less"},
                multisample={"count": samples}, label="cap_mix")
        else:
            raise KeyError(key)
        self._pipes[key] = p
        return p

    # ------------------------------------------------------------------ targets
    def ensure_targets(self, w, h):
        if self.size == (w, h) and self.t:
            return
        for tex in self.t.values():
            tex.destroy()
        d = self.device
        RA, TB, CS = TU.RENDER_ATTACHMENT, TU.TEXTURE_BINDING, TU.COPY_SRC | TU.COPY_DST   # copies: parity tool readbacks and injection
        t = {"parity": d.create_texture(size=(w, h, 1), format="depth32float", usage=RA | TB, label="cap_parity"),
             "key": d.create_texture(size=(w, h, 1), format="depth32float", usage=RA | CS, label="cap_key"),
             "nd_copy": d.create_texture(size=(w, h, 1), format="rgba32float", usage=TB | TU.COPY_DST,
                                         label="cap_nd_copy"),
             "col": d.create_texture(size=(w, h, 1), format="rgba32float", usage=RA | TB | TU.COPY_SRC, label="cap_col")}
        for name, fmt in CAP_TARGETS:
            t[name] = d.create_texture(size=(w, h, 1), format=fmt, usage=RA | TB | CS, label="cap_" + name)
        self.t = t
        self.v = {k: v.create_view() for k, v in t.items()}
        self.size = (w, h)
        e = lambda i, k: {"binding": i, "resource": self.v[k]}
        self._bg_parity = d.create_bind_group(layout=self.bgl_parity, entries=[e(0, "parity")])
        self._bg_lay = d.create_bind_group(layout=self.bgl_lay, entries=[
            e(0, "normal"), e(1, "id"), e(2, "zp"), e(3, "nd_copy")])
        self._bg_mix = d.create_bind_group(layout=self.bgl_mix, entries=[
            e(0, "albedo"), e(1, "normal"), e(2, "id"), e(3, "zp")])

    def release(self):
        for tex in self.t.values():
            tex.destroy()
        self.t, self.v, self.size = {}, {}, None
        self._pages.clear()

    # ------------------------------------------------------------------ CPU planning
    def _page_group(self, geom, page):
        key = (id(geom), page)
        pg = geom.pages[page]
        hit = self._pages.get(key)
        if hit is not None and hit[0] is pg.buffer:
            return hit[1]
        ub = self.device.create_buffer_with_data(data=pg.offsets_words(), usage=BU.UNIFORM, label=f"cap.page{page}")
        ents = [{"binding": 0, "resource": {"buffer": pg.buffer, "offset": 0, "size": pg.buffer.size}},
                {"binding": 1, "resource": {"buffer": ub, "offset": 0, "size": ub.size}}]
        bg = self.device.create_bind_group(layout=self.bgl_page, entries=ents)
        self._pages[key] = (pg.buffer, bg, ub)
        return bg

    def _grow(self, n):
        d = self.device
        if self._draw_buf is None or self._draw_cap < n:
            cap = max(16, 1 << (n - 1).bit_length())
            if self._draw_buf is not None:
                self._draw_buf.destroy()
                self._shade_buf.destroy()
            self._draw_buf = d.create_buffer(size=cap * CAPDRAW_BYTES, usage=BU.STORAGE | BU.COPY_DST, label="cap_draws")
            self._shade_buf = d.create_buffer(size=cap * self.shade_stride, usage=BU.UNIFORM | BU.COPY_DST,
                                              label="cap_shade")
            self._draw_cap = cap
            self._bg0 = d.create_bind_group(layout=self.bgl0, entries=[
                {"binding": 0, "resource": {"buffer": self._frame_ub, "offset": 0, "size": CAPFRAME_BYTES}},
                {"binding": 1, "resource": {"buffer": self._draw_buf, "offset": 0, "size": self._draw_buf.size}},
                {"binding": 2, "resource": {"buffer": self._cc_ub, "offset": 0, "size": CAPCULL_BYTES}}])
            dsel = np.zeros(cap * self.ubo_align // 4, np.uint32)       # draw di reads its own index (indirect draws carry no first_instance)
            dsel[::self.ubo_align // 4] = np.arange(cap, dtype=np.uint32)
            if self._dsel_buf is not None:
                self._dsel_buf.destroy()
            self._dsel_buf = d.create_buffer_with_data(data=dsel.tobytes(), usage=BU.UNIFORM, label="cap_dsel")
            self._bg_su = d.create_bind_group(layout=self.bgl_su, entries=[
                {"binding": 0, "resource": {"buffer": self._shade_buf, "offset": 0, "size": SHADE_SIZE}},
                {"binding": 8, "resource": {"buffer": self._dsel_buf, "offset": 0, "size": 16}}])

    def _classes(self, model, parts, mats, planes, on, mode, V, VP, camera, height):
        """{part id: cutclass class} of the parts of the cut items, for the matrices the cap passes draw them with."""
        if not self.classify or not parts:
            self.last_classes = None
            return {p.id: cutclass.STRADDLE for p in parts}
        Pm = np.asarray(VP, np.float64) @ np.linalg.inv(np.asarray(V, np.float64))
        c = cutclass.classify_boxes(np.array([p.local_min for p in parts]), np.array([p.local_max for p in parts]),
                                    np.stack([mats[p.id] for p in parts]), planes, on, mode, V, abs(1.0 / Pm[1, 1]),
                                    bool(camera.ortho), height, pixels=CAPS_PIXELS)
        self.last_classes = tuple(int((c == k).sum()) for k in (cutclass.KEPT, cutclass.STRADDLE, cutclass.REMOVED))
        return {p.id: int(k) for p, k in zip(parts, c)}

    def plan(self, model, geom, draws, VP, V, size, fs, s, clip, camera, look=None, model_diag=None):
        """Select the cut items, upload the per-frame data and return a CapPlan (None when no item is cut).

        model, geom   the ViewerModel and its GpuGeometry (app/gpu/geometry.py); read-only
        draws         the frame's opaque parts in model order (WgpuRenderer.visible_parts()[0] / GL `draws`)
        VP, V         GL view-projection and view matrices (float64, as the renderer builds them)
        size          render size (w, h)
        fs, s         FrameState (clip_*, selected, hovered) and Settings (highlight, hover_highlight)
        clip          (planes (3, 4) float32, clip_on (3 ints), clip_mode)  -- the GL renderer's `clip` tuple
        camera        anything with near_far() and ortho
        look          optional callable part -> {GLSL uniform name: value}; default look_uniforms(part, fs)
        """
        from app.viewer.renderer import Renderer as GLRenderer
        if int(geom.stage) != self._cmp:          # the gather module is built for one of the two page layouts
            self._cmp = int(geom.stage)
            self._modules.pop("gather", None)
            self._modules.pop("cull", None)
            self._pipes.clear()
        w, h = int(size[0]), int(size[1])
        planes, on, _mode = clip
        by_item = {}
        for p in draws:
            if model.items[p.item].clip and not p.look.translucent:
                by_item.setdefault(p.item, []).append(p)
        cut = []
        for it, ps in by_item.items():
            box = np.concatenate([model._box(p) for p in ps], 0)
            for i in range(3):
                if on[i]:
                    dd = box @ planes[i][:3] + planes[i][3]
                    if dd.min() < 0.0 < dd.max():
                        cut.append((it, ps, box))
                        break
        if not cut:
            return None
        if self._index_of[0] is not model:
            self._index_of = (model, {p.id: i for i, p in enumerate(model.parts)})
        index_of = self._index_of[1]
        look = look or (lambda p: look_uniforms(p, fs))
        base = {}
        GLRenderer._clip_uniforms(lambda name, value: base.__setitem__(name, value), clip)
        # which side of the cut planes each part lies on (cutclass): a part wholly on the removed side has no fragment that
        # survives the clip test in either pass and is not drawn; one wholly on the kept side skips the clip test
        mats = {p.id: model.part_matrix(p) for _it, ps, _b in cut for p in ps}
        cls = self._classes(model, [p for _it, ps, _b in cut for p in ps], mats, planes, on, int(_mode), V, VP, camera, h)
        items, recs, shade, ordinals, part_idx = [], [], [], [], []
        cands = []                       # draws of straddling parts that may get cluster masks: (draw, part index)
        ordinal = 0
        for it, ps, box in cut:
            n_all = len(ps)
            for p in ps:
                if cls[p.id] == cutclass.REMOVED:
                    pi = index_of[p.id]
                    if int(geom.page_of[pi]) >= 0 and geom.ranges[pi][0][1] >= 3:
                        ordinal += 1                 # GL draws it, we do not
            ps = [p for p in ps if cls[p.id] != cutclass.REMOVED]
            if not ps:
                continue
            # the rectangle only has to hold what the remaining parts can draw
            rect = GLRenderer._screen_rect(box if len(ps) == n_all else np.concatenate([model._box(p) for p in ps], 0),
                                           VP, w, h)
            if rect is None:
                continue
            ci = CapItem(it, rect)
            for p in ps:
                pi = index_of[p.id]
                page = int(geom.page_of[pi])
                first, count = geom.ranges[pi][0]
                if page < 0 or count < 3:
                    continue
                M = mats[p.id]
                flip = 1 if np.linalg.det(M[:3, :3]) < 0 else 0
                u = dict(base)
                u.update(look(p))
                u.update({"u_noclip": 0, "u_batched": 0, "u_flip": flip, "u_weight": 0.0})
                shade.append(pack_shading_uniforms(u))
                sb = int(geom.stream_base[pi, COL_STREAM])
                has = sb >= 0 and "col" in geom.pages[page].counts
                rec = np.zeros(28, np.float32)
                ru = rec.view(np.uint32)
                rec[0:16] = np.ascontiguousarray(M.T, dtype=np.float32).reshape(-1)
                rec[16:20] = geom.const_tail[pi, COL_CONST]
                ru[20] = (sb - int(geom.vbase[pi])) & 0xFFFFFFFF if has else 0
                ru[21] = 1 if has else 0
                ru[22] = flip
                rec[24:27] = (float(it + 1), 1.0 if it in fs.selected else 0.0, 0.80 if p.look.detail is not None else 0.62)
                recs.append(rec)
                part_idx.append(pi)
                ordinals.append(ordinal)
                ordinal += 1
                ci.draws.append([len(recs) - 1, page, int(first), int(count), cls[p.id] != cutclass.KEPT, bool(flip), -1])
                if cls[p.id] == cutclass.STRADDLE:
                    cands.append((ci.draws[-1], pi, ci.rect))
            if ci.draws:
                items.append(ci)
        if not items:
            return None
        self.ensure_targets(w, h)
        n = len(recs)
        self._grow(n)
        q = self.device.queue
        q.write_buffer(self._draw_buf, 0, np.ascontiguousarray(np.stack(recs), dtype=np.float32))
        blob = bytearray(n * self.shade_stride)
        for i, b in enumerate(shade):
            blob[i * self.shade_stride:i * self.shade_stride + SHADE_SIZE] = b
        q.write_buffer(self._shade_buf, 0, bytes(blob))
        diag = model_diag if model_diag is not None else max(
            float(np.linalg.norm(np.asarray(model.bounds_max) - np.asarray(model.bounds_min))), 1e-3)
        near, far = camera.near_far()
        f = np.zeros(CAPFRAME_BYTES // 4, np.float32)
        f[0:16] = np.ascontiguousarray((GL_TO_WGPU_Z @ VP).T, dtype=np.float32).reshape(-1)
        f[16:32] = np.ascontiguousarray(np.asarray(VP).T, dtype=np.float32).reshape(-1)
        f[32:48] = np.ascontiguousarray(np.linalg.inv(VP).T, dtype=np.float32).reshape(-1)
        f[48:64] = np.ascontiguousarray(np.asarray(V).T, dtype=np.float32).reshape(-1)
        f[64:68] = (w, h, float(diag * 0.02), 0.0)
        f[68:72] = (near, far, 1.0 if camera.ortho else 0.0, 0.0)
        f[72:76] = (float(fs.hovered + 1) if fs.hovered >= 0 else -1.0, 0.0, 0.0, 0.0)
        f[76:79] = np.asarray(s.highlight, np.float32)
        f[80:83] = np.asarray(s.hover_highlight, np.float32)
        q.write_buffer(self._frame_ub, 0, f)
        pages = {}
        for ci in items:
            for d in ci.draws:
                if d[1] not in pages:
                    pages[d[1]] = (self._page_group(geom, d[1]), geom.pages[d[1]])
        mask = self._plan_masks(geom, cands, planes, on, int(_mode), VP, V, camera, w, h)
        self.last_mask = mask
        return CapPlan(items, n, (w, h), pages, shade, ordinals, mask, part_idx)

    def _mbuf(self, name, nbytes, usage):
        """Buffer of the cull pass ``name`` of at least nbytes (grown, never shrunk); the bind groups are rebuilt when one changes."""
        b = self._mb.get(name)
        if b is None or b.size < nbytes:
            if b is not None:
                b.destroy()
            self._mb[name] = self.device.create_buffer(size=max(256, (nbytes + 65535) // 65536 * 65536), usage=usage,
                                                       label="cap_" + name)
            self._cull_bgs = None
        return self._mb[name]

    def _plan_masks(self, geom, cands, planes, on, mode, VP, V, camera, w, h):
        """Give the straddling parts of a cluster-ordered geometry their cluster lists (caps_cull.wgsl): the draw's ``listed`` is
        set and the buffers of the cull dispatches are filled. None when no part qualifies."""
        cd = getattr(geom, "clusters", None)
        if not self.compact or cd is None or not cands:
            return None
        ok = []
        self.last_density = []
        for d, pi, rect in cands:
            ri = int(cd.level_range[pi, 0])
            if ri < 0 or bool(cd.uncullable[pi]):
                continue
            ncl = int(cd.r_ccount[ri])
            if (ncl < self.compact_min or int(cd.r_page[ri]) != d[1] or int(cd.r_first[ri]) != d[2]
                    or d[3] != 3 * int(cd.r_ntri[ri])):
                continue
            # fill against triangles: the lists pay for themselves (three small dispatches) when the removed clusters cost fill, not only
            # triangle setup; the screen pixels of the item's rectangle per triangle of the part measure that
            density = (rect[2] - rect[0]) * (rect[3] - rect[1]) / max(d[3] // 3, 1)
            self.last_density.append(density)
            if density < self.min_density:
                continue
            ok.append((d, ri, ncl))
        keep, total = [], 0
        for e in sorted(ok, key=lambda e: -e[2]):                    # the largest parts first while the two regions fit
            if (total + e[2]) * 192 * 8 <= self.mask_budget:
                keep.append(e)
                total += e[2]
        if not keep:
            return None
        keep.sort(key=lambda e: (e[0][1], e[0][0]))                  # page major: the slots of a page are contiguous
        tab = np.zeros((len(keep), 8), np.uint32)
        chk = []
        slot, pages = 0, []
        for t, (d, ri, ncl) in enumerate(keep):
            tab[t, 0:4] = (d[0], int(cd.r_cfirst[ri]), ncl, d[2])
            tab[t, 4:7] = (d[3], slot, len(chk))
            chk.extend((t, j0) for j0 in range(0, ncl, 256))
            d[6] = t
            if not pages or pages[-1][0] != d[1]:
                pages.append([d[1], t, t + 1, slot, ncl])
            else:
                pages[-1][2] = t + 1
                pages[-1][4] += ncl
            slot += ncl
        chk = np.asarray(chk, np.uint32).reshape(-1, 2)
        nch, nt = len(chk), len(keep)
        dev, q = self.device, self.device.queue
        if self._clg[0] is not geom:                                 # the boxes of all clusters, once per geometry
            self._clg = (geom, dev.create_buffer_with_data(
                data=np.ascontiguousarray(cd.cl_geom, dtype=np.float32), usage=BU.STORAGE, label="cap_cluster_boxes"))
            self._cull_bgs = None
        S, RW = BU.STORAGE, BU.STORAGE | BU.COPY_DST
        tab_b = self._mbuf("tab", tab.nbytes, RW)
        chk_b = self._mbuf("chk", chk.nbytes, RW)
        info_b = self._mbuf("info", slot * 4, S | BU.COPY_SRC)
        tot_b = self._mbuf("tot", nch * 8, S)
        args_b = self._mbuf("args", nt * 64, S | BU.INDIRECT | BU.COPY_SRC)
        out_b = self._mbuf("out", 2 * slot * 192 * 4, S | BU.INDEX | BU.COPY_SRC)
        if self._cull_bgs is None:
            ent = lambda i, b: {"binding": i, "resource": {"buffer": b, "offset": 0, "size": b.size}}
            clg = self._clg[1]
            mk = lambda k, es: dev.create_bind_group(layout=self.bgl_cc[k], entries=[ent(i, b) for i, b in es])
            self._cull_bgs = (mk(0, [(0, clg), (1, tab_b), (2, chk_b), (3, info_b), (4, tot_b)]),
                              mk(1, [(1, tab_b), (4, tot_b), (5, args_b)]),
                              mk(2, [(1, tab_b), (3, info_b), (4, tot_b), (6, out_b)]))
        if self._bg_pg is None:
            self._bg_pg = dev.create_bind_group(layout=self.bgl_pg, entries=[
                {"binding": 0, "resource": {"buffer": self._pg_buf, "offset": 0, "size": 16}}])
        q.write_buffer(tab_b, 0, tab.tobytes())
        q.write_buffer(chk_b, 0, chk.tobytes())
        pgb = bytearray(max(len(pages), 1) * self.ubo_align)
        for i, (_pg, t0, t1, s0, ns) in enumerate(pages):
            pgb[i * self.ubo_align:i * self.ubo_align + 16] = np.array([t0, t1, s0, ns], np.uint32).tobytes()
        if len(pgb) > self._pg_buf.size:
            self._pg_buf = dev.create_buffer(size=len(pgb), usage=BU.UNIFORM | BU.COPY_DST, label="cap_cull_pg")
            self._bg_pg = dev.create_bind_group(layout=self.bgl_pg, entries=[
                {"binding": 0, "resource": {"buffer": self._pg_buf, "offset": 0, "size": 16}}])
        q.write_buffer(self._pg_buf, 0, bytes(pgb))
        Pm = np.asarray(VP, np.float64) @ np.linalg.inv(np.asarray(V, np.float64))
        u = np.zeros(CAPCULL_BYTES // 4, np.float32)
        for i in range(3):
            u[4 * i:4 * i + 4] = np.asarray(planes[i], np.float32)
        uu = u.view(np.uint32)
        uu[12:16] = (int(on[0]), int(on[1]), int(on[2]), 1 if mode == 1 else 0)
        u[16:20] = (abs(1.0 / Pm[1, 1]), CAPS_PIXELS, float(h), 1.0 if camera.ortho else 0.0)
        uu[20:23] = (slot * 192, nch, nt)
        q.write_buffer(self._cc_ub, 0, u.tobytes())
        return MaskPlan(tab, [tuple(p) for p in pages], slot, nch, self._cull_bgs, [i * self.ubo_align for i in range(len(pages))])

    def mask_counts(self):
        """(clusters, cap list, kept, straddle) cluster counts of the last plan's lists (reads the indirect arguments back; diagnostics)."""
        mk = self.last_mask
        if mk is None:
            return None
        a = np.frombuffer(bytes(self.device.queue.read_buffer(self._mb["args"], 0, len(mk.table) * 64)), np.uint32).reshape(-1, 16)
        return (mk.slots, int(a[:, 0].sum() // 192), int(a[:, 5].sum() // 192), int(a[:, 10].sum() // 192))

    # ------------------------------------------------------------------ encoding
    def encode_gather(self, enc, plan, ts=None):
        """Parity + cap passes of every cut item (2 render passes per item) into the cap targets, after the cluster mask pass
        when the plan has masked parts.
        ts: (query set, begin index, end index) of GPU timestamps around all of the passes, or None."""
        w, h = plan.size
        v = self.v
        first = True
        npass = 2 * len(plan.items)
        k = 0
        began = False

        def stamps(last):
            nonlocal began
            tw = {}
            if ts is not None:
                tw = {"query_set": ts[0]}
                if not began:
                    tw["beginning_of_pass_write_index"] = ts[1]
                    began = True
                if last:
                    tw["end_of_pass_write_index"] = ts[2]
                tw = {"timestamp_writes": tw} if len(tw) > 1 else {}
            return tw

        mk = plan.mask
        if mk is not None:
            cp = enc.begin_compute_pass(**stamps(False))
            cp.set_bind_group(0, self._bg0)
            n = mk.chunks
            cp.set_pipeline(self._pipe(("cull", 0)))
            cp.set_bind_group(1, mk.bgs[0])
            cp.dispatch_workgroups(min(n, 32768), -(-n // 32768))
            n = len(mk.table)
            cp.set_pipeline(self._pipe(("cull", 1)))
            cp.set_bind_group(1, mk.bgs[1])
            cp.dispatch_workgroups(-(-n // 64))
            cp.set_pipeline(self._pipe(("cull", 2)))
            cp.set_bind_group(1, mk.bgs[2])
            for (page, _t0, _t1, _s0, ns), off in zip(mk.pages, mk.pg_off):
                cp.set_bind_group(2, plan.pages[page][0])
                cp.set_bind_group(3, self._bg_pg, [off])
                cp.dispatch_workgroups(min(ns, 32768), -(-ns // 32768))
            cp.end()
        for ci in plan.items:
            x0, y0, x1, y1 = ci.rect
            scissor = (x0, h - y1, x1 - x0, y1 - y0)
            for stage in ("parity", "cap"):
                tw = stamps(k == npass - 1)
                k += 1
                if stage == "parity":
                    rp = enc.begin_render_pass(color_attachments=[], depth_stencil_attachment={
                        "view": v["parity"], "depth_load_op": "load", "depth_store_op": "store"}, **tw)
                    rp.set_scissor_rect(*scissor)
                    rp.set_pipeline(self._pipe(("reset",)))
                    rp.draw(3)
                else:
                    op = "clear" if first else "load"
                    rp = enc.begin_render_pass(
                        color_attachments=[{"view": v[n], "load_op": op, "store_op": "store", "clear_value": (0, 0, 0, 0)}
                                           for n, _f in CAP_TARGETS],
                        depth_stencil_attachment={"view": v["key"], "depth_load_op": op, "depth_store_op": "store",
                                                  "depth_clear_value": 1.0}, **tw)
                    first = False
                    rp.set_scissor_rect(*scissor)
                    rp.set_bind_group(3, self._bg_parity)
                rp.set_bind_group(0, self._bg0)
                group = None                  # page bound at group 2
                ibuf = None                   # index buffer bound: a page number, or "mask"
                pipe = None
                for di, page, first_index, count, clip, flip, listed in ci.draws:
                    rp.set_bind_group(1, self._bg_su, [di * self.shade_stride, di * self.ubo_align])
                    if group != page:
                        rp.set_bind_group(2, plan.pages[page][0])
                        group = page
                    if listed >= 0:
                        # the part's clusters through their lists (caps_cull.wgsl), indirect draws: the cap pass draws the KEPT and
                        # STRADDLE clusters in order, the parity pass the KEPT clusters without a fragment stage, then the STRADDLE ones
                        if ibuf != "mask":
                            rp.set_index_buffer(self._mb["out"], "uint32", 0, 2 * mk.slots * 192 * 4)
                            ibuf = "mask"
                        for rec, test in ((0, True),) if stage == "cap" else ((1, False), (2, True)):
                            if (test, flip, True) != pipe:
                                rp.set_pipeline(self._pipe((stage, test, flip, True)))
                                pipe = (test, flip, True)
                            rp.draw_indexed_indirect(self._mb["args"], listed * 64 + rec * 20)
                        continue
                    if (clip, flip, False) != pipe:
                        rp.set_pipeline(self._pipe((stage, clip, flip, False)))
                        pipe = (clip, flip, False)
                    if self._cmp:
                        rp.draw(count, 1, first_index, di)
                    else:
                        if ibuf != page:
                            rp.set_index_buffer(plan.pages[page][1].buffer, "uint32", plan.pages[page][1].index_byte_offset,
                                                plan.pages[page][1].index_bytes)
                            ibuf = page
                        rp.draw_indexed(count, 1, first_index, 0, di)
                rp.end()

    def encode_lay_in(self, enc, id_tex, nd_tex):
        """Lay the cut faces into the single-sample id and nd targets (GL: CAPMIX_PRE_FS into the pre-pass).

        id_tex  wgpu texture rg32float (item + 1, flags), GL row order; RENDER_ATTACHMENT
        nd_tex  wgpu texture rgba32float (view-space normal, linear view depth; 0 = background), GL row order;
                RENDER_ATTACHMENT | COPY_SRC.  A cut face wins where its window depth is smaller (GL's depth test).
        """
        w, h = self.size
        enc.copy_texture_to_texture({"texture": nd_tex}, {"texture": self.t["nd_copy"]}, (w, h, 1))
        rp = enc.begin_render_pass(color_attachments=[
            {"view": id_tex.create_view(), "load_op": "load", "store_op": "store"},
            {"view": nd_tex.create_view(), "load_op": "load", "store_op": "store"}])
        rp.set_pipeline(self._pipe(("lay",)))
        rp.set_bind_group(0, self._bg0)
        rp.set_bind_group(1, self._bg_lay)
        rp.draw(3)
        rp.end()

    def encode_depth(self, enc, depth_view, samples=1, depth_format="depth32float", gl_order=False):
        """Write the cut faces' window depth into the frame's depth attachment (test less, top row first): GL's depth_ms
        after CAPMIX_FS.  Needed only by passes that test against that depth afterwards (the translucent pass).
        gl_order: the depth attachment has GL row order (row 0 = bottom, the renderer's vis_depth) instead of top first."""
        rp = enc.begin_render_pass(color_attachments=[], depth_stencil_attachment={
            "view": depth_view, "depth_load_op": "load", "depth_store_op": "store"})
        rp.set_pipeline(self._pipe(("depth", depth_format, int(samples), bool(gl_order))))
        rp.set_bind_group(0, self._bg0)
        rp.set_bind_group(1, self._bg_lay)
        rp.draw(3)
        rp.end()

    def shade_bind_group(self, shade_buffer, items_view, ao_view, spec_view, tex_view, s_ao, s_env, s_tex):
        """Bind group over `shade_layout` (shading.wgsl group 1) from the frame's own resources: the ShadeU uniform buffer
        (lights, environment scalars, ao_on ...; the look fields are not read), the item-state texture, the AO texture
        (same row order as the target that encode_colour / encode_mix write), the specular environment (2d-array view),
        the 1x1 albedo texture and the three samplers."""
        return self.device.create_bind_group(layout=self.shade_layout, entries=[
            {"binding": 0, "resource": {"buffer": shade_buffer, "offset": 0, "size": SHADE_SIZE}},
            {"binding": 1, "resource": items_view}, {"binding": 2, "resource": ao_view},
            {"binding": 3, "resource": spec_view}, {"binding": 4, "resource": tex_view},
            {"binding": 5, "resource": s_ao}, {"binding": 6, "resource": s_env}, {"binding": 7, "resource": s_tex}])

    def encode_colour(self, enc, shade_bg):
        """Shade the cut faces into `caps.t["col"]` (rgba32float, GL row order: rgb colour, a = window depth, 0 = none).
        Run after SSAO (the AO texture is read) and before the shading resolve, which applies cap_covers() per sample."""
        rp = enc.begin_render_pass(color_attachments=[{
            "view": self.v["col"], "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 0)}])
        rp.set_pipeline(self._pipe(("col",)))
        rp.set_bind_group(0, self._bg0)
        rp.set_bind_group(1, shade_bg)
        rp.set_bind_group(2, self._bg_mix)
        rp.draw(3)
        rp.end()

    def encode_mix(self, enc, shade_bg, colour_view, depth_view, samples=1, colour_format="rgba16float",
                   depth_format="depth32float", resolve_view=None):
        """Shade the cut faces and draw them full-screen at their depth (depth test less, depth write on, no blending).

        shade_bg      bind group over `caps.shade_layout` (shading.wgsl group 1: the frame's ShadeU, items, AO, env ...)
        colour_view   the frame's colour target view (load_op load); depth_view its depth view (depth_load_op load)
        resolve_view  optional single-sample view the pass resolves colour into
        """
        att = {"view": colour_view, "load_op": "load", "store_op": "store"}
        if resolve_view is not None:
            att["resolve_target"] = resolve_view
        rp = enc.begin_render_pass(color_attachments=[att], depth_stencil_attachment={
            "view": depth_view, "depth_load_op": "load", "depth_store_op": "store"})
        rp.set_pipeline(self._pipe(("mix", colour_format, depth_format, int(samples))))
        rp.set_bind_group(0, self._bg0)
        rp.set_bind_group(1, shade_bg)
        rp.set_bind_group(2, self._bg_mix)
        rp.draw(3)
        rp.end()


def shade_bind_group_layout(device):
    """Layout of shading.wgsl group 1 (ShadeU, items, AO, specular environment, albedo texture + 3 samplers)."""
    F = SS.FRAGMENT
    tex = lambda b, st, vd="2d": {"binding": b, "visibility": F, "texture": {"sample_type": st, "view_dimension": vd}}
    smp = lambda b: {"binding": b, "visibility": F, "sampler": {"type": "filtering"}}
    return device.create_bind_group_layout(entries=[
        {"binding": 0, "visibility": F, "buffer": {"type": "uniform"}},
        tex(1, "unfilterable-float"), tex(2, "float"), tex(3, "float", "2d-array"), tex(4, "float"),
        smp(5), smp(6), smp(7)])
