"""WgpuRenderer, core A: compact GPU geometry, the visibility-buffer raster, a debug resolve and every readback API.

Per frame the CPU work of the GL renderer (app/viewer/renderer.py) is reproduced exactly: _state, _refresh_transforms,
_transform, the LOD level choice (_lod_levels) and the frustum culling of parts. Then:

  1. visibility pass  one indexed draw per part (split every 2**prim_bits triangles) into an MSAA id target
                      (r32uint, or rgba8uint when r32uint cannot be multisampled) plus depth32float:
                      id = (draw_slot << prim_bits) | primitive_index, slot 0 = background.
  2. resolve          (resolve_debug.wgsl) for each pixel the front-most triangle that contains the pixel CENTRE among
                      the distinct ids of its samples (GL's pre-pass is single sample at the centre); none contains it:
                      the front-most sample. Writes res_tri (r32uint), res_info (rg32uint: item + 1, flags) and
                      res_depth (r32float, GL's linear view depth, 0 = background), single sample.
  3. debug colour     a flat per-item colour into the target (real shading, SSAO, OIT, cut caps, textures,
                      morph / explode / animation come in later steps; the hooks are marked in visbuf.wgsl).

Readbacks follow the GL renderer's conventions: arrays are top row first (wgpu textures already are), pixels
(x, y) count from the top-left, depth is the linear view depth (0 for background), ids are item indices (-1 for
background), flags are 1 for selected items (cap bit 2 stays 0 until cut caps exist).

Not in this step (see HANDOFF): alpha-cut textures in the id pass, cut caps, morph / explode / animation, the
vertex-pulling raster path for adapters without "primitive-index".
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import wgpu

from app.viewer import lod as _lod
from app.viewer.renderer import FrameState, Settings, _frustum_planes, _transparent_pass    # noqa: F401
from . import geometry as geo

WGSL = Path(__file__).with_name("wgsl")
BU, TU, SS = wgpu.BufferUsage, wgpu.TextureUsage, wgpu.ShaderStage
FRAME_BYTES = 240
DRAW_FLOATS = 40
GL_TO_WGPU_Z = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0.5, 0.5], [0, 0, 0, 1]], dtype=np.float64)
DRAW_NOCLIP, DRAW_MIRRORED, DRAW_SELECTED = 1, 2, 4
ID_FORMATS = ("r32uint", "rgba8uint")


class RendererError(RuntimeError):
    pass


def _max_samples(device, fmt):
    """Largest sample count (8, 4, 2) the device can create for both `fmt` and depth32float, else 1."""
    for n in (8, 4, 2):
        try:
            for f in (fmt, "depth32float"):
                device.create_texture(size=(8, 8, 1), format=f, sample_count=n, usage=TU.RENDER_ATTACHMENT)
            return n
        except Exception:
            continue
    return 1


def _prelude_ids(id_fmt):
    """WGSL for the visibility module: the id output type."""
    if id_fmt == "r32uint":
        return "alias IdOut = u32;\nfn pack_id(id: u32) -> IdOut { return id; }"
    return ("alias IdOut = vec4<u32>;\n"
            "fn pack_id(id: u32) -> IdOut { return vec4<u32>(id & 255u, (id >> 8u) & 255u, (id >> 16u) & 255u, id >> 24u); }")


def _prelude_resolve(id_fmt, samples, n_pages, page0):
    """Generated WGSL for the resolve module: sample access and the pages of one pass."""
    out = [f"const SAMPLES: u32 = {samples}u;"]
    ms = samples > 1
    ty_id = "texture_multisampled_2d<u32>" if ms else "texture_2d<u32>"
    ty_d = "texture_depth_multisampled_2d" if ms else "texture_depth_2d"
    out.append(f"@group(1) @binding(0) var vis_id: {ty_id};")
    out.append(f"@group(1) @binding(1) var vis_depth: {ty_d};")
    s = "s" if ms else "0"
    if id_fmt == "r32uint":
        out.append(f"fn load_id(p: vec2<i32>, s: i32) -> u32 {{ return textureLoad(vis_id, p, {s}).x; }}")
    else:
        out.append(f"fn load_id(p: vec2<i32>, s: i32) -> u32 {{ let v = textureLoad(vis_id, p, {s}); "
                   f"return v.x | (v.y << 8u) | (v.z << 16u) | (v.w << 24u); }}")
    out.append(f"fn load_depth(p: vec2<i32>, s: i32) -> f32 {{ return textureLoad(vis_depth, p, {s}); }}")
    out.append(f"const GROUP_PAGE0: u32 = {page0}u;\nconst GROUP_PAGES: u32 = {n_pages}u;")
    for i in range(n_pages):
        out.append(f"@group(2) @binding({2 * i}) var<storage, read> pos_{i}: array<f32>;")
        out.append(f"@group(2) @binding({2 * i + 1}) var<storage, read> idx_{i}: array<u32>;")
    out.append("fn fetch_index(lp: u32, i: u32) -> u32 {\n  switch lp {")
    for i in range(n_pages):
        out.append(f"    case {i}u: {{ return idx_{i}[i]; }}")
    out.append("    default: { return 0u; }\n  }\n}")
    out.append("fn fetch_pos(lp: u32, v: u32) -> vec3<f32> {\n  switch lp {")
    for i in range(n_pages):
        out.append(f"    case {i}u: {{ return vec3<f32>(pos_{i}[3u * v], pos_{i}[3u * v + 1u], pos_{i}[3u * v + 2u]); }}")
    out.append("    default: { return vec3<f32>(0.0); }\n  }\n}")
    return "\n".join(out)


def _read_text(name):
    return (WGSL / name).read_text(encoding="utf-8")


def _entry(binding, kind, vis, **kw):
    e = {"binding": binding, "visibility": vis}
    if kind == "u":
        e["buffer"] = {"type": "uniform"}
    elif kind == "r":
        e["buffer"] = {"type": "read-only-storage"}
    elif kind == "w":
        e["buffer"] = {"type": "storage"}
    elif kind == "tu":
        e["texture"] = {"sample_type": "uint", "view_dimension": "2d", "multisampled": kw.get("ms", False)}
    elif kind == "td":
        e["texture"] = {"sample_type": "depth", "view_dimension": "2d", "multisampled": kw.get("ms", False)}
    elif kind == "tf":
        e["texture"] = {"sample_type": "unfilterable-float", "view_dimension": "2d"}
    elif kind == "tl":
        e["texture"] = {"sample_type": "float", "view_dimension": "2d"}
    elif kind == "s":
        e["sampler"] = {"type": "filtering"}
    return e


def _align(n, a=256):
    return (n + a - 1) // a * a


class WgpuRenderer:
    """GL Renderer's public API on wgpu. ``gpu`` is app.gpu.device.Gpu (or anything with device, queue, features,
    limits, info, prim_index)."""

    def __init__(self, gpu, page_bytes=None, resolve_group_pages=None, prim_bits=20, profile=False):
        self.gpu = gpu
        self.device, self.queue = gpu.device, gpu.queue
        feats = set(getattr(gpu, "features", None) or self.device.features)
        self.features = feats
        if not getattr(gpu, "prim_index", "primitive-index" in feats):
            raise RendererError("this adapter has no 'primitive-index' feature (vertex-pulling path is not built yet)")
        self.gl_info = getattr(gpu, "info", "wgpu")
        self.limits = dict(getattr(gpu, "limits", None) or self.device.limits)
        self.page_bytes = int(page_bytes) if page_bytes else geo.page_limit(self.device)
        n_stor = int(self.limits.get("max_storage_buffers_per_shader_stage",
                                     self.limits.get("max-storage-buffers-per-shader-stage", 8)))
        self.group_pages = int(resolve_group_pages) if resolve_group_pages else max(1, min(8, (n_stor - 2) // 2))
        self.prim_bits_max = int(prim_bits)
        self.profile = bool(profile) and "timestamp-query" in feats
        self.ts_period_ns = 1.0
        # ---- id format and sample counts (r32uint has no multisampling without adapter-specific format features)
        self.sample_support = {f: _max_samples(self.device, f) for f in ID_FORMATS}
        self.id_format = "r32uint" if self.sample_support["r32uint"] >= self.sample_support["rgba8uint"] else "rgba8uint"
        self.max_samples = self.sample_support[self.id_format]
        # ---- state like the GL renderer's
        self.model = None
        self.geom = None
        self.size = None
        self.samples = None
        self.last_vp = np.eye(4)
        self.last_camera = None
        self.frame_ok = False
        self._range_lod = None
        self._lod = None
        self._level = {}
        self._xf = {}
        self._xf_key = None
        self._spheres = self._scales = None
        self._fs = None
        self._ids_cache = None
        self.t = {}
        self.timings = {}
        self.last_table = None               # (n + 1, 40) float32 draw table of the last frame (slot -> record)
        self.last_draws = []                 # [(slot, part index, level, first_index, index_count)] of the last frame
        self.last_prim_bits = 20
        self._pipes = {}
        self._modules = {}
        self._frame_ub = self.device.create_buffer(size=FRAME_BYTES, usage=BU.UNIFORM | BU.COPY_DST, label="frame")
        self._table = None
        self._table_cap = 0
        self._bg0 = None
        self._layouts()
        self._gather = {}
        self._qs = None
        if self.profile:
            self._qs = self.device.create_query_set(type="timestamp", count=8)
            self._qbuf = self.device.create_buffer(size=64, usage=BU.QUERY_RESOLVE | BU.COPY_SRC | BU.COPY_DST)
        self._sampler = self.device.create_sampler(mag_filter="linear", min_filter="linear",
                                                   address_mode_u="clamp-to-edge", address_mode_v="clamp-to-edge")

    # ------------------------------------------------------------------ layouts and pipelines
    def _layouts(self):
        d = self.device
        V, F, C = SS.VERTEX, SS.FRAGMENT, SS.COMPUTE
        self.bgl0 = d.create_bind_group_layout(entries=[_entry(0, "u", V | F | C), _entry(1, "r", V | F | C)])
        self.bgl_vispage = d.create_bind_group_layout(entries=[_entry(0, "r", V)])
        self.bgl_res = d.create_bind_group_layout(
            entries=[_entry(2, "tu", F | C), _entry(3, "tu", F | C), _entry(4, "tf", F | C)])
        self.bgl_blit = d.create_bind_group_layout(entries=[_entry(5, "tl", F), _entry(6, "s", F)])
        self.bgl_gather = d.create_bind_group_layout(
            entries=[_entry(60, "u", C), _entry(61, "r", C), _entry(62, "w", C)])
        self._bgl_cache = {}

    def _bgl_visres(self, samples):
        key = ("visres", samples > 1)
        if key not in self._bgl_cache:
            ms = samples > 1
            self._bgl_cache[key] = self.device.create_bind_group_layout(
                entries=[_entry(0, "tu", SS.FRAGMENT, ms=ms), _entry(1, "td", SS.FRAGMENT, ms=ms)])
        return self._bgl_cache[key]

    def _bgl_pages(self, n):
        key = ("pages", n)
        if key not in self._bgl_cache:
            ents = []
            for i in range(n):
                ents += [_entry(2 * i, "r", SS.FRAGMENT), _entry(2 * i + 1, "r", SS.FRAGMENT)]
            self._bgl_cache[key] = self.device.create_bind_group_layout(entries=ents)
        return self._bgl_cache[key]

    def _layout(self, *bgls):
        return self.device.create_pipeline_layout(bind_group_layouts=list(bgls))

    def _vis_module(self):
        key = ("vis", self.id_format)
        if key not in self._modules:
            code = "enable primitive_index;\n" + _prelude_ids(self.id_format) + "\n" + _read_text("clip.wgsl") + "\n" + _read_text("visbuf.wgsl")
            self._modules[key] = self.device.create_shader_module(code=code, label="visbuf")
        return self._modules[key]

    def _resolve_module(self, samples, n_pages, page0):
        key = ("resolve", self.id_format, samples, n_pages, page0)
        if key not in self._modules:
            code = (_prelude_resolve(self.id_format, samples, n_pages, page0) + "\n" + _read_text("clip.wgsl") + "\n" +
                    _read_text("resolve_debug.wgsl"))
            self._modules[key] = self.device.create_shader_module(code=code, label="resolve_debug")
        return self._modules[key]

    def _vis_pipe(self, samples, clip):
        key = ("vis", samples, clip)
        if key not in self._pipes:
            m = self._vis_module()
            self._pipes[key] = self.device.create_render_pipeline(
                layout=self._layout(self.bgl0, self.bgl_vispage),
                vertex={"module": m, "entry_point": "vs"},
                fragment={"module": m, "entry_point": "fs_clip" if clip else "fs", "targets": [{"format": self.id_format}]},
                primitive={"topology": "triangle-list", "cull_mode": "none", "front_face": "ccw"},
                depth_stencil={"format": "depth32float", "depth_write_enabled": True, "depth_compare": "less"},
                multisample={"count": samples}, label=f"vis{'_clip' if clip else ''}x{samples}")
        return self._pipes[key]

    def _resolve_pipe(self, samples, n_pages, page0):
        key = ("resolve", samples, n_pages, page0)
        if key not in self._pipes:
            m = self._resolve_module(samples, n_pages, page0)
            self._pipes[key] = self.device.create_render_pipeline(
                layout=self._layout(self.bgl0, self._bgl_visres(samples), self._bgl_pages(n_pages)),
                vertex={"module": m, "entry_point": "vs_fsq"},
                fragment={"module": m, "entry_point": "fs_resolve",
                          "targets": [{"format": "r32uint"}, {"format": "rg32uint"}, {"format": "r32float"}]},
                primitive={"topology": "triangle-list", "cull_mode": "none"},
                depth_stencil={"format": "depth32float", "depth_write_enabled": True, "depth_compare": "less"},
                label=f"resolve{n_pages}@{page0}")
        return self._pipes[key]

    def _aux_module(self):
        n = min(self.group_pages, max(1, len(self.geom.pages) if self.geom else 1))
        return self._resolve_module(self.samples or 1, n, 0)

    def _aux_pipe(self, name):
        key = ("aux", name, self.samples, self.id_format)
        if key not in self._pipes:
            m = self._aux_module()
            d = self.device
            if name == "debug":
                p = d.create_render_pipeline(
                    layout=self._layout(self.bgl0, self.bgl_res), vertex={"module": m, "entry_point": "vs_fsq"},
                    fragment={"module": m, "entry_point": "fs_debug", "targets": [{"format": "rgba8unorm"}]},
                    primitive={"topology": "triangle-list"}, label="debug")
            elif name == "blit":
                p = d.create_render_pipeline(
                    layout=self._layout(self.bgl0, self.bgl_blit), vertex={"module": m, "entry_point": "vs_fsq"},
                    fragment={"module": m, "entry_point": "fs_blit", "targets": [{"format": "rgba8unorm"}]},
                    primitive={"topology": "triangle-list"}, label="blit")
            else:
                p = d.create_compute_pipeline(
                    layout=self._layout(self.bgl0, self.bgl_res, self.bgl_gather),
                    compute={"module": m, "entry_point": name}, label=name)
            self._pipes[key] = p
        return self._pipes[key]

    # ------------------------------------------------------------------ model
    def set_model(self, model):
        self.release_model()
        try:
            self.model = model
            sink = geo.GpuSink(self.device)
            self.geom = geo.build_geometry(model, sink, self.page_bytes)
            levels = getattr(model, "lod", None) or {}
            parts = model.parts
            where = {p.id: i for i, p in enumerate(parts)}
            coarse = [p for p in parts if p.id in levels]
            self._lod = (np.array([where[p.id] for p in coarse]), [p.id for p in coarse],
                         np.array([levels[p.id].cells for p in coarse], dtype=np.float64)) if coarse else None
            self._make_page_groups()
            self._xf_key = None
            self.frame_ok = False
        except Exception:
            self.release_model()
            raise

    def _make_page_groups(self):
        d = self.device
        g = self.geom
        self._vis_page_bg = []
        for page in g.pages:
            self._vis_page_bg.append(d.create_bind_group(
                layout=self.bgl_vispage, entries=[{"binding": 0, "resource": {"buffer": page.buffers["pos"], "offset": 0,
                                                                              "size": page.buffers["pos"].size}}]))
        self._groups = []                      # (first page, n pages, bind group)
        for p0 in range(0, len(g.pages), self.group_pages):
            n = min(self.group_pages, len(g.pages) - p0)
            ents = []
            for i in range(n):
                for k, name in enumerate(("pos", "index")):
                    b = g.pages[p0 + i].buffers[name]
                    ents.append({"binding": 2 * i + k, "resource": {"buffer": b, "offset": 0, "size": b.size}})
            self._groups.append((p0, n, d.create_bind_group(layout=self._bgl_pages(n), entries=ents)))

    def release_model(self):
        if self.geom is not None:
            self.geom.release()
        self.geom = None
        self.model = None
        self._lod = None
        self._level = {}
        self._xf = {}
        self._xf_key = None
        self._vis_page_bg, self._groups = [], []
        self.frame_ok = False

    def release(self):
        self.release_model()
        for tex in self.t.values():
            if hasattr(tex, "destroy"):
                tex.destroy()
        self.t = {}
        self.size = self.samples = None

    # ------------------------------------------------------------------ per-frame CPU work (ported from the GL renderer)
    def _state(self, fs):
        m = self.model
        n = len(m.items)
        if fs is None:
            fs = FrameState()
        vis = fs.visible
        if vis is None:
            vis = np.zeros(n, dtype=bool)
            for p in m.parts:
                vis[p.item] |= p.visible
        ghost = fs.ghost if fs.ghost is not None else np.zeros(n, dtype=bool)
        alpha = fs.alpha if fs.alpha is not None else np.ones(n, dtype=np.float32)
        return fs, vis, ghost, alpha

    def _refresh_transforms(self, m):
        key = (id(m.node_world), len(m.node_world), m.root.tobytes(),
               tuple(sorted((n, np.asarray(o).tobytes()) for n, o in m.node_offsets.items())),
               None if m.item_offsets is None else m.item_offsets.tobytes(),
               tuple(sorted(m.node_weights.items())), bytes(bool(it.clip) for it in m.items))
        if key == self._xf_key:
            return
        self._xf_key = key
        self._xf = {}
        spheres = [m.part_sphere(p) for p in m.parts]
        self._spheres = (np.array([c for c, _r in spheres], dtype=np.float64).reshape(-1, 3),
                         np.array([r for _c, r in spheres], dtype=np.float64))
        self._scales = np.zeros(len(m.parts))
        if self._lod is not None:
            for i in self._lod[0]:
                self._scales[i] = float(np.max(np.linalg.norm(m.part_matrix(m.parts[i])[:3, :3], axis=0)))

    def _transform(self, p):
        """(model matrix, normal matrix, mirrored, morph weight, never cut, key) of a part, once per change."""
        xf = self._xf.get(p.id)
        if xf is None:
            m = self.model
            M = m.part_matrix(p)
            weight = float(m.node_weights.get(p.node, 0.0))
            flip = 1 if np.linalg.det(M[:3, :3]) < 0 else 0
            noclip = 0 if m.items[p.item].clip else 1
            xf = (M, np.linalg.inv(M[:3, :3]).T, flip, weight, noclip, (M.tobytes(), flip, weight, noclip))
            self._xf[p.id] = xf
        return xf

    def _lod_levels(self, V, halves, ortho, h):
        if self._lod is None:
            return {}
        where, ids, cells = self._lod
        centres, radii = self._spheres
        if ortho:
            pixel = np.full(len(ids), 2.0 * halves[1] / h)
        else:
            depth = -(centres[where] @ V[2, :3] + V[2, 3]) - radii[where]
            pixel = np.maximum(depth, 0.0) * (2.0 * halves[1] / h)
        level = np.sum(cells * self._scales[where][:, None] <= pixel[:, None], axis=1)
        return {pid: int(k) for pid, k in zip(ids, level) if k}

    def visible_parts(self, VP, vis, ghost, alpha, fs):
        """(opaque parts, translucent parts) of this frame, in model order: the GL renderer's culling."""
        m = self.model
        draws, oit = [], []
        planes = _frustum_planes(VP)
        centres, radii = self._spheres
        inside = np.all(planes[:, :3] @ centres.T + planes[:, 3:4] >= -radii, axis=0) if len(radii) else []
        for p, keep in zip(m.parts, inside):
            it = p.item
            if not vis[it] or not keep:
                continue
            if _transparent_pass(p, bool(ghost[it]), float(alpha[it]), fs):
                oit.append(p)
            else:
                draws.append(p)
        return draws, oit

    # ------------------------------------------------------------------ targets
    def _pick_samples(self, msaa):
        want = max(1, int(msaa))
        for n in (8, 4, 2):
            if n <= want and n <= self.max_samples:
                return n
        return 1

    def _ensure_targets(self, w, h, samples):
        if self.size == (w, h) and self.samples == samples and self.t:
            return
        for tex in self.t.values():
            tex.destroy()
        d = self.device
        RA, TB, CS = TU.RENDER_ATTACHMENT, TU.TEXTURE_BINDING, TU.COPY_SRC
        t = {}
        t["vis_id"] = d.create_texture(size=(w, h, 1), format=self.id_format, sample_count=samples, usage=RA | TB,
                                       label="vis_id")
        t["vis_depth"] = d.create_texture(size=(w, h, 1), format="depth32float", sample_count=samples, usage=RA | TB,
                                          label="vis_depth")
        t["res_tri"] = d.create_texture(size=(w, h, 1), format="r32uint", usage=RA | TB | CS, label="res_tri")
        t["res_info"] = d.create_texture(size=(w, h, 1), format="rg32uint", usage=RA | TB | CS, label="res_info")
        t["res_depth"] = d.create_texture(size=(w, h, 1), format="r32float", usage=RA | TB | CS, label="res_depth")
        t["res_order"] = d.create_texture(size=(w, h, 1), format="depth32float", usage=RA, label="res_order")
        t["col"] = d.create_texture(size=(w, h, 1), format="rgba8unorm", usage=RA | TB, label="col")
        self.t = t
        self.v = {k: v.create_view() for k, v in t.items()}
        self.size, self.samples = (w, h), samples
        self._bg_visres = d.create_bind_group(layout=self._bgl_visres(samples), entries=[
            {"binding": 0, "resource": self.v["vis_id"]}, {"binding": 1, "resource": self.v["vis_depth"]}])
        self._bg_res = d.create_bind_group(layout=self.bgl_res, entries=[
            {"binding": 2, "resource": self.v["res_tri"]}, {"binding": 3, "resource": self.v["res_info"]},
            {"binding": 4, "resource": self.v["res_depth"]}])
        self._bg_blit = d.create_bind_group(layout=self.bgl_blit, entries=[
            {"binding": 5, "resource": self.v["col"]}, {"binding": 6, "resource": self._sampler}])

    def _ensure_table(self, rows):
        if self._table is not None and self._table_cap >= rows:
            return
        cap = max(64, 1 << (rows - 1).bit_length())
        if self._table is not None:
            self._table.destroy()
        self._table = self.device.create_buffer(size=cap * DRAW_FLOATS * 4, usage=BU.STORAGE | BU.COPY_DST,
                                                label="draw_table")
        self._table_cap = cap
        self._bg0 = self.device.create_bind_group(layout=self.bgl0, entries=[
            {"binding": 0, "resource": {"buffer": self._frame_ub, "offset": 0, "size": FRAME_BYTES}},
            {"binding": 1, "resource": {"buffer": self._table, "offset": 0, "size": self._table.size}}])

    # ------------------------------------------------------------------ the draw table
    def _build_table(self, draws):
        """Sort the parts into the GL draw order, split long draws and fill the table. Returns (table, entries,
        prim_bits) where entries are (slot, part index, level, first_index, index_count) per draw."""
        geom = self.geom
        index_of = {p.id: i for i, p in enumerate(self.model.parts)}
        items = []
        for p in draws:
            pi = index_of[p.id]
            k = self._level.get(p.id, 0)
            rng = geom.ranges[pi]
            first, count = rng[k] if k < len(rng) else rng[0]
            if count < 3 or geom.page_of[pi] < 0:
                continue
            key = geom.gl_keys[pi][k] if k < len(geom.gl_keys[pi]) else geom.gl_keys[pi][0]
            items.append((key, pi, p, k, first, count))
        items.sort(key=lambda e: (e[0], e[1]))
        bits = self.prim_bits_max
        while True:
            cap = 1 << bits
            n_slots = sum(-(-(e[5] // 3) // cap) for e in items)
            if n_slots + 1 <= (1 << (32 - bits)):
                break
            bits -= 1
            if bits < 8:
                raise RendererError(f"{n_slots} draw slots do not fit a 32-bit visibility id")
        table = np.zeros((n_slots + 1, DRAW_FLOATS), dtype=np.float32)
        tu = table.view(np.uint32)
        entries = []
        slot = 1
        for key, pi, p, k, first, count in items:
            M, nmat, flip, weight, noclip, _key = self._transform(p)
            sel = p.item in self._fs.selected
            flags = (DRAW_NOCLIP if noclip else 0) | (DRAW_MIRRORED if flip else 0) | (DRAW_SELECTED if sel else 0)
            tris = count // 3
            page = int(geom.page_of[pi])
            for a in range(0, tris, cap):
                n = min(cap, tris - a)
                table[slot, 0:16] = np.ascontiguousarray(M.T).reshape(-1)
                table[slot, 16:19] = nmat[:, 0]
                table[slot, 20:23] = nmat[:, 1]
                table[slot, 24:27] = nmat[:, 2]
                tu[slot, 28:32] = (first + 3 * a, 0, n, page)
                tu[slot, 32:36] = (pi, p.item, flags, k)
                table[slot, 36] = weight
                entries.append((slot, pi, k, first + 3 * a, 3 * n))
                slot += 1
        return table, entries, bits

    # ------------------------------------------------------------------ frame
    def render(self, target, size, camera, s, fs=None, out_size=None):
        """Render one frame into ``target`` (a wgpu texture, rgba8unorm, RENDER_ATTACHMENT). ``size`` is the render
        resolution, ``out_size`` the target's when the picture is scaled on the way."""
        self.frame_ok = False
        w, h = max(int(size[0]), 2), max(int(size[1]), 2)
        ow, oh = (int(out_size[0]), int(out_size[1])) if out_size is not None else (w, h)
        self._ids_cache = None
        samples = self._pick_samples(s.msaa)
        self._ensure_targets(w, h, samples)
        aspect = w / h
        camera.aspect = aspect
        V = camera.view_matrix()
        Pm = camera.proj_matrix(aspect)
        VP = Pm @ V
        self.last_vp = VP
        halves = camera.ortho_halves(aspect) if camera.ortho else camera.half_tans(aspect)
        self.last_camera = (V, Pm, aspect, camera.ortho, halves, (w, h))
        near, far = camera.near_far()
        m = self.model
        fs, vis, ghost, alpha = self._state(fs) if m is not None else (fs or FrameState(), None, None, None)
        self._fs = fs
        if m is not None:
            self._refresh_transforms(m)
            self._level = self._lod_levels(V, halves, camera.ortho, h)
        clip_planes = np.array(fs.clip_planes, dtype=np.float32)
        clip_on = tuple(int(bool(x)) for x in fs.clip_on)
        any_clip = any(clip_on)
        draws = []
        if m is not None:
            draws, _oit = self.visible_parts(VP, vis, ghost, alpha, fs)
        table, entries, bits = (self._build_table(draws) if m is not None and self.geom is not None
                                else (np.zeros((1, DRAW_FLOATS), np.float32), [], self.prim_bits_max))
        self.last_table, self.last_draws, self.last_prim_bits = table, entries, bits
        self._ensure_table(len(table))

        f = np.zeros(60, dtype=np.float32)
        u = f.view(np.uint32)
        f[0:16] = np.ascontiguousarray((GL_TO_WGPU_Z @ VP).T, dtype=np.float32).reshape(-1)
        f[16:32] = np.ascontiguousarray(V.T, dtype=np.float32).reshape(-1)
        f[32:44] = clip_planes.reshape(-1)
        u[44:47] = clip_on
        u[47] = int(fs.clip_mode)
        f[48:52] = (w, h, ow, oh)
        f[52:56] = (halves[0], halves[1], near, far)
        u[56:60] = (bits, samples, len(entries), 1 if camera.ortho else 0)
        self.queue.write_buffer(self._frame_ub, 0, f)
        self.queue.write_buffer(self._table, 0, np.ascontiguousarray(table))

        enc = self.device.create_command_encoder()
        qs = self._qs
        # ---- 1. visibility pass
        tw = {"query_set": qs, "beginning_of_pass_write_index": 0, "end_of_pass_write_index": 1} if qs else None
        rp = enc.begin_render_pass(
            color_attachments=[{"view": self.v["vis_id"], "load_op": "clear", "store_op": "store",
                                "clear_value": (0, 0, 0, 0)}],
            depth_stencil_attachment={"view": self.v["vis_depth"], "depth_load_op": "clear", "depth_store_op": "store",
                                      "depth_clear_value": 1.0}, **({"timestamp_writes": tw} if tw else {}))
        if entries:
            rp.set_pipeline(self._vis_pipe(samples, any_clip))
            rp.set_bind_group(0, self._bg0)
            current = -1
            for slot, pi, k, first, count in entries:
                page = int(self.geom.page_of[pi])
                if page != current:
                    rp.set_bind_group(1, self._vis_page_bg[page])
                    rp.set_index_buffer(self.geom.pages[page].buffers["index"], "uint32")
                    current = page
                rp.draw_indexed(count, 1, first, 0, slot)
        rp.end()
        # ---- 2. resolve, one full-screen pass per group of pages (a clear-only pass when nothing was drawn)
        todo = self._groups if entries else [None]
        for gi, grp in enumerate(todo):
            first_pass = gi == 0
            tw = {}
            if qs and first_pass:
                tw.update({"query_set": qs, "beginning_of_pass_write_index": 2})
            if qs and gi == len(todo) - 1:
                tw.update({"query_set": qs, "end_of_pass_write_index": 3})
            op = "clear" if first_pass else "load"
            rp = enc.begin_render_pass(
                color_attachments=[{"view": self.v[k], "load_op": op, "store_op": "store", "clear_value": (0, 0, 0, 0)}
                                   for k in ("res_tri", "res_info", "res_depth")],
                depth_stencil_attachment={"view": self.v["res_order"], "depth_load_op": op, "depth_store_op": "store",
                                          "depth_clear_value": 1.0}, **({"timestamp_writes": tw} if tw else {}))
            if grp is not None:
                p0, n, bg = grp
                rp.set_pipeline(self._resolve_pipe(samples, n, p0))
                rp.set_bind_group(0, self._bg0)
                rp.set_bind_group(1, self._bg_visres)
                rp.set_bind_group(2, bg)
                rp.draw(3)
            rp.end()
        # ---- 3. debug colour (and the scale blit)
        scaled = (ow, oh) != (w, h)
        dest = self.v["col"] if scaled else target.create_view()
        tw = {"query_set": qs, "beginning_of_pass_write_index": 4, "end_of_pass_write_index": 5} if qs else None
        rp = enc.begin_render_pass(
            color_attachments=[{"view": dest, "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 1)}],
            **({"timestamp_writes": tw} if tw else {}))
        rp.set_pipeline(self._aux_pipe("debug"))
        rp.set_bind_group(0, self._bg0)
        rp.set_bind_group(1, self._bg_res)
        rp.draw(3)
        rp.end()
        if scaled:
            rp = enc.begin_render_pass(color_attachments=[
                {"view": target.create_view(), "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 1)}])
            rp.set_pipeline(self._aux_pipe("blit"))
            rp.set_bind_group(0, self._bg0)
            rp.set_bind_group(1, self._bg_blit)
            rp.draw(3)
            rp.end()
        if qs:
            enc.resolve_query_set(qs, 0, 6, self._qbuf, 0)
        self.queue.submit([enc.finish()])
        if qs:
            ts = np.frombuffer(bytes(self.queue.read_buffer(self._qbuf, 0, 48)), dtype=np.uint64).astype(np.float64)
            k = self.ts_period_ns * 1e-6
            self.timings = {"vis_ms": (ts[1] - ts[0]) * k, "resolve_ms": (ts[3] - ts[2]) * k,
                            "debug_ms": (ts[5] - ts[4]) * k, "total_ms": (ts[5] - ts[0]) * k}
        self.frame_ok = True

    # ------------------------------------------------------------------ readbacks (GL semantics)
    def _unproject(self, gx, gy, d):
        """World point at GL pixel (gx, gy) (y up) whose linear view depth is d."""
        V, Pm, aspect, ortho, halves, (w, h) = self.last_camera
        ndc = np.array([gx / w * 2 - 1, gy / h * 2 - 1])
        if ortho:
            pv = np.array([ndc[0] * halves[0], ndc[1] * halves[1], -d, 1.0])
        else:
            pv = np.array([ndc[0] * halves[0] * d, ndc[1] * halves[1] * d, -d, 1.0])
        return (np.linalg.inv(V) @ pv)[:3]

    def _gather_buffers(self, n):
        g = self._gather
        d = self.device
        if "params" not in g:
            g["params"] = d.create_buffer(size=32, usage=BU.UNIFORM | BU.COPY_DST, label="gather_params")
        if g.get("cap", 0) < n:
            cap = max(64, 1 << (n - 1).bit_length())
            for k in ("pts", "out"):
                if k in g:
                    g[k].destroy()
            g["pts"] = d.create_buffer(size=cap * 8, usage=BU.STORAGE | BU.COPY_DST, label="gather_pts")
            g["out"] = d.create_buffer(size=cap * 16, usage=BU.STORAGE | BU.COPY_SRC, label="gather_out")
            g["cap"] = cap
            g["bg"] = d.create_bind_group(layout=self.bgl_gather, entries=[
                {"binding": 60, "resource": {"buffer": g["params"], "offset": 0, "size": 32}},
                {"binding": 61, "resource": {"buffer": g["pts"], "offset": 0, "size": g["pts"].size}},
                {"binding": 62, "resource": {"buffer": g["out"], "offset": 0, "size": g["out"].size}}])
        return g

    def _gather_run(self, entry, n_out, params, pts=None):
        g = self._gather_buffers(max(n_out, 1))
        w, h = self.size
        self.queue.write_buffer(g["params"], 0, np.array(params, dtype=np.uint32))
        if pts is not None and len(pts):
            self.queue.write_buffer(g["pts"], 0, np.ascontiguousarray(pts, dtype=np.int32))
        enc = self.device.create_command_encoder()
        cp = enc.begin_compute_pass()
        cp.set_pipeline(self._aux_pipe(entry))
        cp.set_bind_group(0, self._bg0)
        cp.set_bind_group(1, self._bg_res)
        cp.set_bind_group(2, g["bg"])
        return enc, cp, g

    def _gather_finish(self, enc, cp, g, n_out):
        cp.end()
        self.queue.submit([enc.finish()])
        raw = bytes(self.queue.read_buffer(g["out"], 0, n_out * 16))
        return np.frombuffer(raw, dtype=np.float32).reshape(n_out, 4)

    def _points(self, pts):
        """(n, 4) float32 rows (item + 1, flags, depth, triangle id bits) at pixels (x, y from the top-left)."""
        pts = np.asarray(pts, dtype=np.int32).reshape(-1, 2)
        n = len(pts)
        w, h = self.size
        enc, cp, g = self._gather_run("cs_points", n, [w, h, 0, 0, 0, n, 0, 0], pts)
        cp.dispatch_workgroups((n + 63) // 64)
        return self._gather_finish(enc, cp, g, n)

    def pick(self, x, y):
        """(item index or -1, world point or None, on a cut face) under render pixel (x, y from the top-left)."""
        if self.last_camera is None or not self.t or not self.frame_ok:
            return -1, None, False
        V, Pm, aspect, ortho, halves, (w, h) = self.last_camera
        if not (0 <= x < w and 0 <= y < h):
            return -1, None, False
        r = self._points([(int(x), int(y))])[0]
        d = float(r[2])
        if not np.isfinite(d) or d <= 0.0:
            return -1, None, False
        gy = h - 1 - int(y)
        return int(round(float(r[0]))) - 1, self._unproject(x + 0.5, gy + 0.5, d), (int(round(float(r[1]))) & 2) != 0

    def read_label_samples(self, step):
        """(ids, flags, depth, centre ids) on a grid of cells `step` pixels wide, top row first, or None."""
        if not self.frame_ok or not self.t:
            return None
        w, h = self.size
        step = int(step)
        gw, gh = -(-w // step), -(-h // step)
        enc, cp, g = self._gather_run("cs_labels", gw * gh, [w, h, gw, gh, step, 0, 0, 0])
        cp.dispatch_workgroups((gw + 7) // 8, (gh + 7) // 8)
        v = self._gather_finish(enc, cp, g, gw * gh).reshape(gh, gw, 4)
        return (np.rint(v[..., 0]).astype(np.int32) - 1, np.rint(v[..., 1]).astype(np.int32), v[..., 2].copy(),
                np.rint(v[..., 3]).astype(np.int32) - 1)

    def _read_texture(self, tex, bytes_per_px, dtype, comps):
        w, h = self.size
        bpr = _align(w * bytes_per_px)
        buf = self.device.create_buffer(size=bpr * h, usage=BU.COPY_DST | BU.MAP_READ)
        enc = self.device.create_command_encoder()
        enc.copy_texture_to_buffer({"texture": tex, "mip_level": 0, "origin": (0, 0, 0)},
                                   {"buffer": buf, "offset": 0, "bytes_per_row": bpr, "rows_per_image": h}, (w, h, 1))
        self.queue.submit([enc.finish()])
        buf.map_sync(wgpu.MapMode.READ)
        raw = np.frombuffer(bytes(buf.read_mapped()), dtype=np.uint8)
        buf.unmap()
        buf.destroy()
        # the single-sample textures keep GL's row order (row 0 = bottom); the arrays handed out start at the top
        return np.ascontiguousarray(raw.reshape(h, bpr)[::-1, :w * bytes_per_px]).view(dtype).reshape(h, w, comps)

    def read_ids(self):
        """(h, w) item index (-1 background) and (h, w) flags of the last frame, top row first."""
        if not self.frame_ok or not self.t:
            return None, None
        if self._ids_cache is not None:
            return self._ids_cache
        a = self._read_texture(self.t["res_info"], 8, np.uint32, 2)
        self._ids_cache = (a[..., 0].astype(np.int32) - 1, a[..., 1].astype(np.int32))
        return self._ids_cache

    def read_depth(self):
        """(h, w) linear view depth of the last frame (0 background), top row first."""
        if not self.frame_ok or not self.t:
            return None
        return self._read_texture(self.t["res_depth"], 4, np.float32, 1)[..., 0].copy()

    def read_triangles(self):
        """(h, w) uint32 packed triangle id ((slot << prim_bits) | primitive), 0 background (extra, for checks)."""
        if not self.frame_ok or not self.t:
            return None
        return self._read_texture(self.t["res_tri"], 4, np.uint32, 1)[..., 0].copy()

    def ids_at(self, points):
        """Item index at render pixels [(x, y from the top-left), ...] of the last frame (-1: background / outside)."""
        if not self.frame_ok or not self.t:
            return [-1] * len(points)
        w, h = self.size
        out = [-1] * len(points)
        if self._ids_cache is not None:
            for i, (x, y) in enumerate(points):
                if 0 <= x < w and 0 <= y < h:
                    out[i] = int(self._ids_cache[0][int(y), int(x)])
            return out
        ok = [i for i, (x, y) in enumerate(points) if 0 <= x < w and 0 <= y < h]
        if ok:
            r = self._points([(int(points[i][0]), int(points[i][1])) for i in ok])
            for i, row in zip(ok, r):
                out[i] = int(round(float(row[0]))) - 1
        return out

    def world_from_pixel(self, x, y, d):
        """World point at render pixel (x, y from the top-left) and linear depth d of the last frame."""
        if self.last_camera is None or not self.frame_ok:
            return None
        h = self.last_camera[5][1]
        return self._unproject(x + 0.5, h - 1 - y + 0.5, d)

    def read_final(self, target, size):
        """(h, w, 3) uint8 copy of a rendered rgba8unorm target, top row first."""
        w, h = size
        bpr = _align(w * 4)
        buf = self.device.create_buffer(size=bpr * h, usage=BU.COPY_DST | BU.MAP_READ)
        enc = self.device.create_command_encoder()
        enc.copy_texture_to_buffer({"texture": target, "mip_level": 0, "origin": (0, 0, 0)},
                                   {"buffer": buf, "offset": 0, "bytes_per_row": bpr, "rows_per_image": h}, (w, h, 1))
        self.queue.submit([enc.finish()])
        buf.map_sync(wgpu.MapMode.READ)
        raw = np.frombuffer(bytes(buf.read_mapped()), dtype=np.uint8)
        buf.unmap()
        buf.destroy()
        return np.ascontiguousarray(raw.reshape(h, bpr)[:, :w * 4].reshape(h, w, 4)[..., :3])
