"""GPU cluster culling for the wgpu renderer: frustum + two-phase hi-Z occlusion over <=64-triangle clusters.

    culler = ClusterCuller(gpu, geometry)          # geometry: app.gpu.geometry.GpuGeometry (read only)
    culler.prepare(model)                          # clusters (cached), static buffers, pipelines
    frame = FrameParts(part, level, matrix, noclip, weight, slot0)     # the frame's opaque parts after CPU culling + LOD
    res = culler.encode(enc, view, proj, size, id_view, depth_view, samples, frame, clip=..., draw_unculled=cb)

``encode`` records the whole visibility pass (it begins both render passes itself, because compute has to run between
the phases): cull phase 1 -> pass 1 (clears id + depth) -> depth pyramid from the real MSAA depth (farthest sample)
-> cull phase 2 -> pass 2 (loads) -> visibility record for the next frame. Parts the cullers cannot bound (see
clusters.py) come back in ``res.unculled`` (positions in ``frame``); ``draw_unculled(render_pass, positions)`` is called
inside pass 1 so the renderer can draw them with its own path. See S/gpu_port/cull/INTEGRATION.md for the contract.

Capacity. Page g has ``cap[g]`` blocks of 64 triangles (768 B each) in its compacted index buffer, the sum over the
page's cullable parts of their largest per-level cluster count. A cluster is drawn at most once per frame and only one
level of a part is live, so the capacity can never be exceeded; ``ST_OVERFLOW`` counts any breach (always 0).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import wgpu

from . import cluster_cache, clusters as cl

WGSL = Path(__file__).with_name("wgsl")
BU, TU, SS = wgpu.BufferUsage, wgpu.TextureUsage, wgpu.ShaderStage
Y_FLIP = np.diag([1.0, -1.0, 1.0, 1.0])
GL_TO_WGPU_Z = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0.5, 0.5], [0, 0, 0, 1]], dtype=np.float64)
FRAME_BYTES = 240
XF_FLOATS = 20
BLOCK_BYTES = 64 * 3 * 4
STAT_NAMES = ("active", "frustum", "frustum_tris", "p1", "p1_tris", "p2", "p2_tris", "overflow", "p2_tested",
              "visible", "visible_tris")
CULL_TAG = 0x80000000


def _read(name):
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
    elif kind == "sw":
        e["storage_texture"] = {"access": "write-only", "format": "r32float", "view_dimension": "2d"}
    return e


def _grid(n_groups):
    """2D dispatch size for n workgroups (the shaders index (y * 32768 + x))."""
    n = max(int(n_groups), 0)
    return min(n, 32768), max(1, -(-n // 32768)), 1


@dataclass
class FrameParts:
    """The frame's parts, one row each (already frustum-culled and with the LOD level chosen, as the renderer does)."""
    part: np.ndarray                     # (n,) model part index
    level: np.ndarray                    # (n,) LOD level
    matrix: np.ndarray                   # (n, 4, 4) part_matrix (numpy math layout, world = M @ p)
    noclip: np.ndarray                   # (n,) bool: never cut by the clip planes
    weight: np.ndarray                   # (n,) morph weight
    slot0: np.ndarray = None             # (n,) the renderer's first draw slot of the part (cull_decode.wgsl)


@dataclass
class ClipState:
    planes: np.ndarray = field(default_factory=lambda: np.zeros((3, 4), np.float32))
    on: tuple = (0, 0, 0)
    mode: int = 0

    @property
    def any(self):
        return any(self.on)


@dataclass
class CullResult:
    unculled: np.ndarray                 # positions in FrameParts the renderer must draw itself
    clip: bool
    n_parts: int


def pack_frame(view, proj, size, samples, clip=None, out_size=None, ortho=False, bits=20, n_draws=0, flip_y=True):
    """The 240-byte Frame uniform of clip.wgsl, laid out exactly as WgpuRenderer.render does (near / far / tangents are
    not used by the culling shaders and stay 0 unless given by the caller).
    flip_y=True (the renderer's visbuf.wgsl rasterises bottom-up: clip y is negated, row 0 = bottom of the picture): the culler's own
    vertex shader and its pyramid projection use ``vp`` with y negated (Y_FLIP @ vp), which is exactly the clip position the
    renderer's pass writes, so culled and plain draws share one image, sample pattern and hi-Z."""
    w, h = int(size[0]), int(size[1])
    ow, oh = out_size if out_size is not None else (w, h)
    clip = clip or ClipState()
    f = np.zeros(60, dtype=np.float32)
    u = f.view(np.uint32)
    VP = np.asarray(proj, dtype=np.float64) @ np.asarray(view, dtype=np.float64)
    f[0:16] = np.ascontiguousarray(((Y_FLIP if flip_y else np.eye(4)) @ GL_TO_WGPU_Z @ VP).T, dtype=np.float32).reshape(-1)
    f[16:32] = np.ascontiguousarray(np.asarray(view).T, dtype=np.float32).reshape(-1)
    f[32:44] = np.asarray(clip.planes, dtype=np.float32).reshape(-1)
    u[44:47] = [int(bool(x)) for x in clip.on]
    u[47] = int(clip.mode)
    f[48:52] = (w, h, ow, oh)
    u[56:60] = (bits, samples, n_draws, 1 if ortho else 0)
    return f


class ClusterCuller:
    def __init__(self, gpu, geometry, id_format="r32uint", depth_eps=4e-6, pad_px=0.5, collect_stats=False,
                 profile=False):
        self.gpu, self.device, self.queue = gpu, gpu.device, gpu.queue
        self.geom = geometry
        self.id_format = id_format
        self.depth_eps, self.pad_px = float(depth_eps), float(pad_px)
        self.collect_stats = collect_stats
        self.profile = bool(profile) and "timestamp-query" in gpu.features
        self.cd = None
        self.buf = {}
        self._pipes, self._modules, self._bgl = {}, {}, {}
        self._size = None
        self._flip = 0
        self._xf_last = None
        self._reset_vis = True
        self.stats = {}
        self.timings = {}

    # ------------------------------------------------------------------ layouts
    def _layouts(self):
        d = self.device
        C, V, F = SS.COMPUTE, SS.VERTEX, SS.FRAGMENT
        self.bgl_cull0 = d.create_bind_group_layout(entries=(
            [_entry(0, "u", C), _entry(1, "u", C)] + [_entry(i, "r", C) for i in range(2, 9)] +
            [_entry(i, "w", C) for i in range(9, 16)]))
        self.bgl_sel_c = d.create_bind_group_layout(entries=[_entry(0, "u", C)])
        self.bgl_hzb_read = d.create_bind_group_layout(entries=[_entry(0, "tf", C)])
        self.bgl_gather0 = d.create_bind_group_layout(entries=[_entry(i, "r", C) for i in range(6)])
        self.bgl_gather1 = d.create_bind_group_layout(entries=[_entry(0, "u", C), _entry(1, "r", C), _entry(2, "w", C)])
        self.bgl_hzbn = d.create_bind_group_layout(entries=[_entry(0, "tf", C), _entry(1, "sw", C)])
        self.bgl_vis0 = d.create_bind_group_layout(entries=[_entry(0, "u", V | F), _entry(1, "r", V), _entry(2, "r", F)])
        self.bgl_vis1 = d.create_bind_group_layout(entries=[_entry(0, "r", V), _entry(1, "r", V)])
        self.bgl_vis2 = d.create_bind_group_layout(entries=[_entry(0, "u", V | F)])

    def _pl(self, *bgls):
        return self.device.create_pipeline_layout(bind_group_layouts=list(bgls))

    def _module(self, key, code):
        if key not in self._modules:
            self._modules[key] = self.device.create_shader_module(code=code, label=str(key))
        return self._modules[key]

    def _compute(self, key, code, entry, layout):
        k = (key, entry)
        if k not in self._pipes:
            m = self._module(key, code)
            self._pipes[k] = self.device.create_compute_pipeline(layout=layout, compute={"module": m, "entry_point": entry},
                                                                 label=f"{key}.{entry}")
        return self._pipes[k]

    def _ids_prelude(self):
        if self.id_format == "r32uint":
            return "alias IdOut = u32;\nfn pack_id(id: u32) -> IdOut { return id; }"
        return ("alias IdOut = vec4<u32>;\nfn pack_id(id: u32) -> IdOut { return vec4<u32>(id & 255u, (id >> 8u) & 255u, "
                "(id >> 16u) & 255u, id >> 24u); }")

    def vis_wgsl(self):
        return "enable primitive_index;\n" + self._ids_prelude() + "\n" + _read("clip.wgsl") + "\n" + _read("cull_vis.wgsl")

    def _vis_pipe(self, samples, clip):
        key = ("vis", samples, clip)
        if key not in self._pipes:
            m = self._module(("vis", self.id_format), self.vis_wgsl())
            self._pipes[key] = self.device.create_render_pipeline(
                layout=self._pl(self.bgl_vis0, self.bgl_vis1, self.bgl_vis2),
                vertex={"module": m, "entry_point": "vs"},
                fragment={"module": m, "entry_point": "fs_clip" if clip else "fs", "targets": [{"format": self.id_format}]},
                primitive={"topology": "triangle-list", "cull_mode": "none", "front_face": "ccw"},
                depth_stencil={"format": "depth32float", "depth_write_enabled": True, "depth_compare": "less"},
                multisample={"count": samples}, label=f"cullvis{'_clip' if clip else ''}x{samples}")
        return self._pipes[key]

    # ------------------------------------------------------------------ buffers
    def _new(self, name, size, usage, label=None):
        old = self.buf.get(name)
        if old is not None:
            try:
                old.destroy()
            except Exception:
                pass
        b = self.device.create_buffer(size=max(16, (int(size) + 3) & ~3), usage=usage, label=label or name)
        self.buf[name] = b
        return b

    def _upload(self, buf, arr, flush=256 << 20):
        raw = np.ascontiguousarray(arr).reshape(-1).view(np.uint8) if arr.dtype != np.uint8 else arr.reshape(-1)
        step, staged = 64 << 20, 0
        for a in range(0, raw.size, step):
            chunk = np.ascontiguousarray(raw[a:a + step])
            self.queue.write_buffer(buf, a, chunk)
            staged += chunk.nbytes
            if staged >= flush:
                self._wait()
                staged = 0
        self._wait()

    def _wait(self):
        from .device import wait_idle
        wait_idle(self.gpu)

    def release(self):
        for b in list(self.buf.values()):
            try:
                b.destroy()
            except Exception:
                pass
        self.buf = {}
        if getattr(self, "hzb", None) is not None:
            self.hzb.destroy()
            self.hzb = None
        self.cd = None

    # ------------------------------------------------------------------ prepare
    def prepare(self, model, progress=None, use_cache=True, clusters=None, n_parts=None):
        """Build or load the clusters of the model and create the static GPU buffers. Returns a stats dict.
        ``clusters`` / ``n_parts`` let a caller that already owns a ClusterData (the stress scene) skip the build."""
        t0 = time.perf_counter()
        self.release()
        geom = self.geom
        self._layouts()
        cd = clusters if clusters is not None else cluster_cache.get_clusters(model, geom, progress=progress, use_cache=use_cache)
        self.cd = cd
        t_clusters = time.perf_counter() - t0
        G = len(geom.pages)
        P = int(n_parts) if n_parts is not None else len(model.parts)
        R, C = cd.n_ranges, cd.n_clusters
        self.P, self.R, self.C, self.G = P, R, C, G
        self.cap = cl.page_capacity(cd, G)
        self.slot_base = 1 + np.concatenate([[0], np.cumsum(self.cap)[:-1]]).astype(np.int64)
        self.n_slots = int(1 + self.cap.sum())
        if self.n_slots >= (1 << 25):
            raise cl.ClusterError(f"{self.n_slots} block slots do not fit the 31-bit culled id")
        lim = self.gpu.limits
        max_bind = int(lim.get("max_storage_buffer_binding_size", lim.get("max-storage-buffer-binding-size", 1 << 30)))
        for name, nbytes in (("cl_geom", C * 32), ("perm", cd.n_tris * 4), ("slot_cluster", self.n_slots * 4)):
            if nbytes > max_bind:
                raise cl.ClusterError(f"{name} needs {nbytes} bytes, binding limit {max_bind}")
        ST, UN = BU.STORAGE | BU.COPY_DST, BU.UNIFORM | BU.COPY_DST
        self._upload(self._new("cl_geom", C * 32, ST), cd.cl_geom)
        self._upload(self._new("cl_range", C * 4, ST), cd.cl_range)
        self._upload(self._new("rng", R * 32, ST), cd.range_table())
        self._upload(self._new("perm", cd.n_tris * 4, ST), cd.perm)
        self._new("part_xf", P * XF_FLOATS * 4, ST)
        self._new("range_active", R * 4, ST)
        self._new("vis0", C * 4, ST | BU.COPY_SRC)
        self._new("vis1", C * 4, ST | BU.COPY_SRC)
        pt = np.zeros((G, 4), dtype=np.uint32)
        for g in range(G):
            pt[g] = (cd.page_cfirst[g], cd.page_cfirst[g + 1], self.slot_base[g], self.cap[g])
        self._upload(self._new("ptab", G * 16, ST), pt)
        self._new("pstate", G * 8 * 4, BU.STORAGE | BU.COPY_DST)
        self._new("slot_cluster", self.n_slots * 4, BU.STORAGE | BU.COPY_SRC | BU.COPY_DST)
        self._new("seen", self.n_slots * 4, BU.STORAGE | BU.COPY_DST)
        self._new("stats", 16 * 4, BU.STORAGE | BU.COPY_SRC | BU.COPY_DST)
        self._new("args", G * 2 * 32, BU.STORAGE | BU.INDIRECT | BU.COPY_SRC)
        self._new("disp", G * 2 * 16, BU.STORAGE | BU.INDIRECT)
        self._new("dinfo", G * 2 * 4, BU.STORAGE)
        self._new("frame_ub", FRAME_BYTES, UN)
        self._new("cfg_ub", 32, UN)
        self._new("nslots_ub", 16, UN)
        self.queue.write_buffer(self.buf["nslots_ub"], 0, np.array([self.n_slots, 0, 0, 0], dtype=np.uint32))
        self.compact = []
        for g in range(G):
            self.compact.append(self._new(f"compact{g}", max(int(self.cap[g]), 1) * BLOCK_BYTES,
                                          BU.STORAGE | BU.INDEX | BU.COPY_SRC))
        # per page: lookup table and small uniforms
        self.sel_ub, self.dsel_ub = [], []
        for g in range(G):
            page = geom.pages[g]
            plist = np.array(page.parts, dtype=np.uint32)
            pend = (geom.vbase[page.parts] + geom.vcount[page.parts]).astype(np.uint32)
            n_chunk = -(-page.nverts // 32)
            chunk = np.searchsorted(pend, np.arange(n_chunk, dtype=np.int64) * 32, side="right").astype(np.uint32)
            chunk = np.minimum(chunk, max(len(plist) - 1, 0))
            self._upload(self._new(f"vlook{g}", (n_chunk + 2 * len(plist)) * 4, ST),
                         np.concatenate([chunk, pend, plist]).astype(np.uint32))
            sels, dsels = [], []
            for ph in range(2):
                b = self.device.create_buffer(size=16, usage=UN, label=f"sel{g}.{ph}")
                self.queue.write_buffer(b, 0, np.array([g, ph, 0, 0], dtype=np.uint32))
                sels.append(b)
                b2 = self.device.create_buffer(size=16, usage=UN, label=f"dsel{g}.{ph}")
                self.queue.write_buffer(b2, 0, np.array([g * 2 + ph, n_chunk, len(plist), 0], dtype=np.uint32))
                dsels.append(b2)
            self.sel_ub.append(sels)
            self.dsel_ub.append(dsels)
        self._wait()
        self._make_static_groups()
        self._flip = 0
        self._reset_vis = True
        self._xf_last = None
        self._hzb_key = None
        self._size = None
        mem = self.memory_report()
        self.prepare_stats = dict(cd.stats, clusters_s=t_clusters, prepare_s=time.perf_counter() - t0,
                                  capacity_blocks=[int(c) for c in self.cap], memory=mem)
        return self.prepare_stats

    def _bg(self, layout, entries):
        ents = []
        for i, r in enumerate(entries):
            if isinstance(r, tuple):
                ents.append({"binding": r[0], "resource": r[1]})
            else:
                ents.append({"binding": i, "resource": {"buffer": r, "offset": 0, "size": r.size}})
        return self.device.create_bind_group(layout=layout, entries=ents)

    def _make_static_groups(self):
        b = self.buf
        self.bg_gather0 = self._bg(self.bgl_gather0, [b["slot_cluster"], b["cl_range"], b["rng"], b["perm"], b["ptab"], b["args"]])
        self.bg_gather1 = [[self._bg(self.bgl_gather1, [self.sel_ub[g][ph], self.geom.pages[g].buffers["index"],
                                                         self.compact[g]]) for ph in range(2)] for g in range(self.G)]
        self.bg_sel_c = [self._bg(self.bgl_sel_c, [self.sel_ub[g][0]]) for g in range(self.G)]
        self.bg_vis1 = [self._bg(self.bgl_vis1, [self.geom.pages[g].buffers["pos"], b[f"vlook{g}"]]) for g in range(self.G)]
        self.bg_vis2 = [[self._bg(self.bgl_vis2, [self.dsel_ub[g][ph]]) for ph in range(2)] for g in range(self.G)]
        self.bg_vis0 = self._bg(self.bgl_vis0, [b["frame_ub"], b["part_xf"], b["dinfo"]])

    def memory_report(self):
        cd, b = self.cd, self.buf
        tri = max(cd.n_tris, 1)
        parts = {"cl_geom": b["cl_geom"].size, "cl_range": b["cl_range"].size, "rng": b["rng"].size,
                 "perm": b["perm"].size, "vlook": sum(b[f"vlook{g}"].size for g in range(self.G)),
                 "vis_flags": b["vis0"].size + b["vis1"].size, "slot_cluster+seen": b["slot_cluster"].size + b["seen"].size,
                 "part_xf+range_active": b["part_xf"].size + b["range_active"].size,
                 "compacted": sum(c.size for c in self.compact)}
        total = sum(parts.values())
        hz = getattr(self, "hzb_bytes", 0)
        return {"bytes": parts, "total_bytes": total, "per_triangle": total / tri,
                "static_per_triangle": (total - parts["compacted"]) / tri, "compacted_per_triangle": parts["compacted"] / tri,
                "hzb_bytes": hz}

    # ------------------------------------------------------------------ size dependent resources
    def _ensure_size(self, w, h, samples, id_view, depth_view):
        key = (w, h, samples)
        if self._size != key:
            if getattr(self, "hzb", None) is not None:
                self.hzb.destroy()
            hw, hh = -(-w // 2), -(-h // 2)
            levels = int(np.floor(np.log2(max(hw, hh)))) + 1
            self.hz_levels, self.hz_dims = levels, (hw, hh)
            self.hzb = self.device.create_texture(size=(hw, hh, 1), format="r32float", mip_level_count=levels,
                                                  usage=TU.STORAGE_BINDING | TU.TEXTURE_BINDING, label="cull_hzb")
            self.hzb_bytes = sum(max(1, -(-hw >> l)) * max(1, -(-hh >> l)) * 4 for l in range(levels))
            self.hz_full = self.hzb.create_view(base_mip_level=0, mip_level_count=levels)
            self.hz_mips = [self.hzb.create_view(base_mip_level=l, mip_level_count=1) for l in range(levels)]
            self.bg_hzb_read = self._bg(self.bgl_hzb_read, [(0, self.hz_full)])
            self.bg_hzbn = [self._bg(self.bgl_hzbn, [(0, self.hz_mips[l - 1]), (1, self.hz_mips[l])]) for l in range(1, levels)]
            self._size = key
            self._view_key = None
        # views of the renderer's targets (they change only with the size)
        vk = (id(id_view), id(depth_view), samples)
        if self._view_key != vk:
            ms = samples > 1
            ms_prelude = ("alias DepthTex = texture_depth_multisampled_2d;\nfn load_depth(p: vec2<i32>, s: i32) -> f32 "
                          "{ return textureLoad(dsrc, p, s); }") if ms else (
                "alias DepthTex = texture_depth_2d;\nfn load_depth(p: vec2<i32>, s: i32) -> f32 { return textureLoad(dsrc, p, 0); }")
            code = f"const SAMPLES: u32 = {samples}u;\n" + ms_prelude + "\n" + _read("cull_hzb.wgsl")
            self.bgl_hzb0 = self._bgl.get(("hzb0", ms)) or self.device.create_bind_group_layout(
                entries=[_entry(0, "td", SS.COMPUTE, ms=ms), _entry(1, "sw", SS.COMPUTE)])
            self._bgl[("hzb0", ms)] = self.bgl_hzb0
            self.pipe_hzb0 = self._compute(("hzb0", samples), code, "hzb0", self._pl(self.bgl_hzb0))
            self.bg_hzb0 = self._bg(self.bgl_hzb0, [(0, depth_view), (1, self.hz_mips[0])])
            idt = ("texture_multisampled_2d<u32>" if ms else "texture_2d<u32>")
            if self.id_format == "r32uint":
                ld = f"fn load_id(p: vec2<i32>, s: i32) -> u32 {{ return textureLoad(vis_id, p, {'s' if ms else '0'}).x; }}"
            else:
                ld = (f"fn load_id(p: vec2<i32>, s: i32) -> u32 {{ let v = textureLoad(vis_id, p, {'s' if ms else '0'}); "
                      f"return v.x | (v.y << 8u) | (v.z << 16u) | (v.w << 24u); }}")
            code = (f"const SAMPLES: u32 = {samples}u;\n@group(0) @binding(0) var vis_id: {idt};\n{ld}\n" + _read("cull_mark.wgsl"))
            C = SS.COMPUTE
            self.bgl_mark = self.device.create_bind_group_layout(entries=[
                _entry(0, "tu", C, ms=ms), _entry(1, "w", C), _entry(2, "w", C), _entry(3, "r", C), _entry(4, "w", C),
                _entry(5, "r", C), _entry(6, "r", C), _entry(7, "u", C)])
            self.pipe_mark = self._compute(("mark", samples, self.id_format), code, "mark", self._pl(self.bgl_mark))
            self.pipe_apply = self._compute(("mark", samples, self.id_format), code, "apply", self._pl(self.bgl_mark))
            self._mark_ids = id_view
            self._view_key = vk
            self._mark_bgs = {}

    def _mark_group(self, id_view):
        b = self.buf
        nxt = f"vis{1 - self._flip}"
        key = nxt
        bg = self._mark_bgs.get(key)
        if bg is None:
            bg = self._bg(self.bgl_mark, [(0, id_view), (1, {"buffer": b["seen"], "offset": 0, "size": b["seen"].size}),
                                          (2, {"buffer": b[nxt], "offset": 0, "size": b[nxt].size}),
                                          (3, {"buffer": b["slot_cluster"], "offset": 0, "size": b["slot_cluster"].size}),
                                          (4, {"buffer": b["stats"], "offset": 0, "size": b["stats"].size}),
                                          (5, {"buffer": b["cl_range"], "offset": 0, "size": b["cl_range"].size}),
                                          (6, {"buffer": b["rng"], "offset": 0, "size": b["rng"].size}),
                                          (7, {"buffer": b["nslots_ub"], "offset": 0, "size": 16})])
            self._mark_bgs[key] = bg
        return bg

    def _cull0_group(self):
        b = self.buf
        prev = f"vis{self._flip}"
        key = prev
        cache = self.__dict__.setdefault("_cull0_bgs", {})
        if key not in cache:
            order = ["frame_ub", "cfg_ub", "cl_geom", "cl_range", "rng", "part_xf", "range_active", prev, "ptab", "pstate",
                     "slot_cluster", "stats", "args", "disp", "dinfo", f"vis{1 - self._flip}"]
            cache[key] = self._bg(self.bgl_cull0, [b[n] for n in order])
        return cache[key]

    def _cull_pipes(self):
        code = _read("clip.wgsl") + "\n" + _read("cull_test.wgsl")
        lay = self._pl(self.bgl_cull0, self.bgl_sel_c, self.bgl_hzb_read)
        return {n: self._compute("cull_test", code, n, lay) for n in ("cull_p1", "cull_p2", "finalize_p1", "finalize_p2")}

    def _gather_pipe(self):
        return self._compute("cull_gather", _read("cull_gather.wgsl"), "gather", self._pl(self.bgl_gather0, self.bgl_gather1))

    # ------------------------------------------------------------------ per frame
    def reset(self):
        """Forget what was visible last frame (the next frame is a cold frame: everything is tested by phase 2)."""
        self._reset_vis = True

    def decode_bind_group_entries(self):
        """Buffers the resolve's decode group (cull_decode.wgsl) binds, in binding order."""
        b = self.buf
        return [b["slot_cluster"], b["cl_range"], b["rng"], b["perm"], b["part_xf"]]

    def _frame_inputs(self, fp):
        P, R = self.P, self.R
        cd = self.cd
        part = np.asarray(fp.part, dtype=np.int64)
        level = np.asarray(fp.level, dtype=np.int64)
        lr = cd.level_range[part, np.minimum(level, cl.LEVEL_COUNT - 1)]
        cullable = (~cd.uncullable[part]) & (lr >= 0)
        unculled = np.nonzero(cd.uncullable[part])[0]
        idx = part[cullable]
        xf = np.zeros((P, XF_FLOATS), dtype=np.float32)
        xu = xf.view(np.uint32)
        m = np.asarray(fp.matrix, dtype=np.float64)[cullable]
        xf[idx, 0:16] = np.ascontiguousarray(m.transpose(0, 2, 1), dtype=np.float32).reshape(len(idx), 16)
        xf[idx, 16] = np.abs(np.asarray(fp.weight, dtype=np.float32)[cullable])
        xu[idx, 17] = np.asarray(fp.noclip, dtype=np.uint32)[cullable]
        if fp.slot0 is not None:
            xu[idx, 18] = np.asarray(fp.slot0, dtype=np.uint32)[cullable]
        active = np.zeros(R, dtype=np.uint32)
        active[lr[cullable]] = 1
        return xf, active, unculled, int(cullable.sum())

    def encode(self, enc, view, proj, size, id_view, depth_view, samples, parts, clip=None, ortho=False,
               draw_unculled=None, out_size=None, bits=20):
        """Record the visibility pass (both phases) into ``enc``. Returns a CullResult."""
        assert self.cd is not None, "prepare() first"
        w, h = int(size[0]), int(size[1])
        self._ensure_size(w, h, samples, id_view, depth_view)
        clip = clip or ClipState()
        xf, active, unculled, n_cull = self._frame_inputs(parts)
        b, q = self.buf, self.queue
        if self._xf_last is None or not np.array_equal(xf, self._xf_last):
            q.write_buffer(b["part_xf"], 0, xf)
            self._xf_last = xf
        q.write_buffer(b["range_active"], 0, active)
        q.write_buffer(b["frame_ub"], 0, pack_frame(view, proj, size, samples, clip, out_size, ortho, bits))
        cfg = np.zeros(8, dtype=np.float32)
        cu = cfg.view(np.uint32)
        cu[0:4] = (self.hz_levels, 1 if self.collect_stats else 0, self.hz_dims[0], self.hz_dims[1])
        cfg[4], cfg[5] = self.depth_eps, self.pad_px
        q.write_buffer(b["cfg_ub"], 0, cfg)
        if self._reset_vis:
            enc.clear_buffer(b["vis0"])
            enc.clear_buffer(b["vis1"])
            enc.clear_buffer(b["seen"])
            self._reset_vis = False
        enc.clear_buffer(b[f"vis{1 - self._flip}"])
        enc.clear_buffer(b["pstate"])
        enc.clear_buffer(b["stats"])
        pipes = self._cull_pipes()
        gather = self._gather_pipe()
        cd = self.cd
        G = self.G
        bg0 = self._cull0_group()
        qs = self._qs() if self.profile else None

        def tw(i, last=False):
            if qs is None:
                return None
            return {"query_set": qs, "beginning_of_pass_write_index": 2 * i, "end_of_pass_write_index": 2 * i + 1}

        def phase_compute(cp, name, fin, ph):
            cp.set_pipeline(pipes[name])
            cp.set_bind_group(0, bg0)
            cp.set_bind_group(2, self.bg_hzb_read)
            for g in range(G):
                n = int(cd.page_cfirst[g + 1] - cd.page_cfirst[g])
                if n == 0:
                    continue
                cp.set_bind_group(1, self.bg_sel_c[g])
                x, y, _ = _grid(-(-n // 64))
                cp.dispatch_workgroups(x, y, 1)
            cp.set_pipeline(pipes[fin])
            cp.set_bind_group(1, self.bg_sel_c[0])
            cp.dispatch_workgroups(G, 1, 1)
            cp.set_pipeline(gather)
            cp.set_bind_group(0, self.bg_gather0)
            for g in range(G):
                if self.cap[g] == 0:
                    continue
                cp.set_bind_group(1, self.bg_gather1[g][ph])
                cp.dispatch_workgroups_indirect(b["disp"], (g * 2 + ph) * 16)

        # ---- phase 1: visible last frame
        cp = enc.begin_compute_pass(timestamp_writes=tw(0))
        phase_compute(cp, "cull_p1", "finalize_p1", 0)
        cp.end()
        clip_on = clip.any
        rp = enc.begin_render_pass(
            color_attachments=[{"view": id_view, "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 0)}],
            depth_stencil_attachment={"view": depth_view, "depth_load_op": "clear", "depth_store_op": "store",
                                      "depth_clear_value": 1.0}, timestamp_writes=tw(1))
        self._draws(rp, samples, clip_on, 0)
        if draw_unculled is not None and len(unculled):
            draw_unculled(rp, unculled)
        rp.end()
        # ---- depth pyramid from this frame's real depth, then phase 2
        cp = enc.begin_compute_pass(timestamp_writes=tw(2))
        cp.set_pipeline(self.pipe_hzb0)
        cp.set_bind_group(0, self.bg_hzb0)
        cp.dispatch_workgroups(-(-self.hz_dims[0] // 8), -(-self.hz_dims[1] // 8), 1)
        pn = self._compute(("hzbn",), _read("cull_hzbn.wgsl"), "hzbn", self._pl(self.bgl_hzbn))
        for l in range(1, self.hz_levels):
            dw, dh = max(1, -(-self.hz_dims[0] >> l)), max(1, -(-self.hz_dims[1] >> l))
            cp.set_pipeline(pn)
            cp.set_bind_group(0, self.bg_hzbn[l - 1])
            cp.dispatch_workgroups(-(-dw // 8), -(-dh // 8), 1)
        phase_compute(cp, "cull_p2", "finalize_p2", 1)
        cp.end()
        rp = enc.begin_render_pass(
            color_attachments=[{"view": id_view, "load_op": "load", "store_op": "store"}],
            depth_stencil_attachment={"view": depth_view, "depth_load_op": "load", "depth_store_op": "store"},
            timestamp_writes=tw(3))
        self._draws(rp, samples, clip_on, 1)
        rp.end()
        # ---- phase 2 already wrote next frame's phase-1 set (vis_next). The id image is only read to count the
        # clusters that really own a sample (statistics: the "truly visible" column); the renderer needs no such pass.
        self._marked = self.collect_stats
        if self.collect_stats:
            cp = enc.begin_compute_pass(timestamp_writes=tw(4))
            cp.set_pipeline(self.pipe_mark)
            cp.set_bind_group(0, self._mark_group(id_view))
            cp.dispatch_workgroups(-(-w // 8), -(-h // 8), 1)
            cp.set_pipeline(self.pipe_apply)
            cp.dispatch_workgroups(*_grid(-(-self.n_slots // 64)))
            cp.end()
        if qs is not None:
            # every resolved query must have been written: the mark pass owns slots 8/9 and is skipped without statistics
            enc.resolve_query_set(qs, 0, 10 if self.collect_stats else 8, b["ts_buf"], 0)
        self._flip = 1 - self._flip
        self._last_clip = clip_on
        return CullResult(unculled=unculled, clip=clip_on, n_parts=n_cull)

    def _draws(self, rp, samples, clip, ph):
        rp.set_pipeline(self._vis_pipe(samples, clip))
        rp.set_bind_group(0, self.bg_vis0)
        for g in range(self.G):
            if self.cap[g] == 0:
                continue
            rp.set_bind_group(1, self.bg_vis1[g])
            rp.set_bind_group(2, self.bg_vis2[g][ph])
            rp.set_index_buffer(self.compact[g], "uint32")
            rp.draw_indexed_indirect(self.buf["args"], (g * 2 + ph) * 32)

    def _qs(self):
        if "ts_buf" not in self.buf:
            self._new("ts_buf", 80, BU.QUERY_RESOLVE | BU.COPY_SRC)
            self._qset = self.device.create_query_set(type="timestamp", count=10)
        return self._qset

    # ------------------------------------------------------------------ results (call after the encoder was submitted)
    def read_stats(self):
        """Counters of the last encode (needs collect_stats=True): clusters / triangles per stage."""
        data = np.frombuffer(bytes(self.queue.read_buffer(self.buf["stats"], 0, 64)), dtype=np.uint32).copy()
        self.stats = {n: int(data[i]) for i, n in enumerate(STAT_NAMES)}
        return self.stats

    def read_timings(self, period_ns):
        """GPU milliseconds of the last encode per stage (needs profile=True and a timestamp period)."""
        ts = np.frombuffer(bytes(self.queue.read_buffer(self.buf["ts_buf"], 0, 80)), dtype=np.uint64).astype(np.float64)
        ms = (ts[1::2] - ts[0::2]) * period_ns * 1e-6
        names = ("cull1", "pass1", "hzb_cull2", "pass2", "mark")
        self.timings = {n: float(v) for n, v in zip(names, ms)}
        if not getattr(self, "_marked", False):
            self.timings["mark"] = 0.0
            ms = ms[:4]
        self.timings["total_ms"] = float(ms.sum())
        return self.timings

    # ------------------------------------------------------------------ debugging / checks
    def read_buffer(self, name, size=None):
        b = self.buf[name]
        return np.frombuffer(bytes(self.queue.read_buffer(b, 0, size or b.size)), dtype=np.uint8)

    def decode_ids(self, ids, slot_cluster=None):
        """CPU decode of culled ids -> (cluster, part, triangle in the range, range) arrays (-1 where not culled)."""
        cd = self.cd
        ids = np.asarray(ids, dtype=np.uint32)
        tagged = (ids & np.uint32(CULL_TAG)) != 0
        sc = slot_cluster if slot_cluster is not None else self.read_buffer("slot_cluster").view(np.uint32)
        slot = ((ids & np.uint32(0x7FFFFFFF)) >> np.uint32(6)).astype(np.int64)
        local = (ids & np.uint32(63)).astype(np.int64)
        c = np.where(tagged, sc[np.minimum(slot, len(sc) - 1)], 0).astype(np.int64)
        r = cd.cl_range[c].astype(np.int64)
        tri = cd.perm[cd.r_tfirst[r] + 64 * (c - cd.r_cfirst[r]) + local].astype(np.int64)
        part = cd.r_part[r].astype(np.int64)
        return (np.where(tagged, c, -1), np.where(tagged, part, -1), np.where(tagged, tri, -1), np.where(tagged, r, -1))
