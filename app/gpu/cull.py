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

Cluster-ordered geometry (M2). The geometry must be built with ``build_geometry(..., cluster_order=True)``: every cullable
(part, level) index range is stored in cluster order, so cluster c (the j-th of its range) owns the 192 index words at
(range first index + 192 * j) of the page's index section and nothing has to be copied: the survivors of a phase are written
as a list of entries (``crl``: cluster, first index word, part, triangle count; 16 B per cluster slot) and drawn by ONE non-indexed draw per page and phase
(vertex_count = clusters * 192, the vertex shader reads index and position from the page: wgsl/cull_vis.wgsl). There is no
compacted index buffer and no GPU copy of the triangle order (the order table ``perm`` stays on the CPU, memory mapped, for
picks: geometry.TriangleOrder, ClusterCuller.decode_ids).

Compact index budget (M3). Drawing every cluster by vertex pulling costs 3 vertex invocations per triangle and loses the post-transform
cache (bad on integrated GPUs, whose vertex outputs go through memory). So a bounded compact index buffer ``cidx`` (``budget_tris`` x
12 B, never proportional to the model) is filled by a gather pass (wgsl/cull_gather.wgsl, after each phase's cull) with the 192 index
words of the first list slots of each page (finalize_p* splits the budget between the pages), and ONE indexed indirect draw per
(page, phase) draws them (wgsl/cull_idx.wgsl: primitive_index gives the id). The slots over the budget are drawn by the pulled draw
of M2, in the same render pass: same ids, same picture, only slower. Both phases share ``cidx`` (phase 2's gather runs after pass 1).
``budget_tris`` comes from the constructor or the ANATOMY_CULL_BUDGET environment variable (0 = pulled draws only); DEFAULT_BUDGET_TRIS.

Storage buffers: the tables live in three buffers addressed through the ``lay`` uniform (wgsl/cull_tables.wgsl): ``cro`` (read only
tables, per-frame part matrices), ``cra`` (atomic counters, flags) and ``crw`` (draw arguments, visibility flags; bound read only
wherever it is an indirect source), plus ``crl`` (the visible-cluster lists). cull_test 4, cull_mark 3, cull_gather 4 (crl, crw, cidx, the page), cull_vis vertex 4 (cro, crw, crl, the page) /
fragment 0, cull_idx vertex 2 (cro, the page) / fragment 2 (crw, crl); the resolve's decode group (cull_decode.wgsl) 1.

Capacity. Page g has ``cap[g]`` list slots, the sum over the page's cullable parts of their largest per-level cluster count. A
cluster is drawn at most once per frame and only one level of a part is live, so the capacity can never be exceeded;
``ST_OVERFLOW`` counts any breach (always 0).
"""
from __future__ import annotations

import functools
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import wgpu

from . import cluster_cache, clusters as cl
from .geometry import geom_prelude

WGSL = Path(__file__).with_name("wgsl")
BU, TU, SS = wgpu.BufferUsage, wgpu.TextureUsage, wgpu.ShaderStage
Y_FLIP = np.diag([1.0, -1.0, 1.0, 1.0])
GL_TO_WGPU_Z = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0.5, 0.5], [0, 0, 0, 1]], dtype=np.float64)
FRAME_BYTES = 240
XF_FLOATS = 20
CLUSTER_VERTS = 192                    # vertices drawn per visible cluster (64 triangles x 3)
STAT_NAMES = ("active", "frustum", "frustum_tris", "p1", "p1_tris", "p2", "p2_tris", "overflow", "p2_tested",
              "visible", "visible_tris", "idx_slots", "pull_slots", "kept", "pulled")
DEFAULT_BUDGET_TRIS = 8 << 20          # 8,388,608 triangles = 96 MiB of compact indices (12 B per triangle); see the M3 report
BUDGET_ENV = "ANATOMY_CULL_BUDGET"
CLASSIFY_ENV = "ANATOMY_CUT_CLASSIFY"       # 0: every cluster of a cut view takes the discard path (as before the classification)
CULL_TAG = 0x80000000


@functools.lru_cache(maxsize=None)
def _read(name):
    """A shader source file, read once (the per-frame code paths ask for it on every frame)."""
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


ORDER_PAGES = 96             # pages whose list direction the camera chooses (cfg.cl.y .. cl.w, 32 bits each); later pages keep the cluster order


def order_moments(cd):
    """Per range: M = sum_i (i - mean_i) * centre_i over the clusters of the range (i the cluster index inside the range, centres in
    part space). It is the direction in which the centres drift as the cluster index grows (the clusters are Morton-sorted, so this is
    the coarse axis of the order). Memory only, derived from the cluster data: nothing is stored."""
    R, C = cd.n_ranges, cd.n_clusters
    m = np.zeros((R, 3), dtype=np.float64)
    if C == 0:
        return m
    rng = np.asarray(cd.cl_range, dtype=np.int64)
    n = np.asarray(cd.r_ccount, dtype=np.int64)
    cen = np.asarray(cd.cl_geom[:, 0:3], dtype=np.float64)
    loc = np.arange(C, dtype=np.int64) - np.asarray(cd.r_cfirst, dtype=np.int64)[rng]
    for a in range(3):
        sic = np.bincount(rng, weights=loc * cen[:, a], minlength=R)
        sc = np.bincount(rng, weights=cen[:, a], minlength=R)
        m[:, a] = sic - 0.5 * (n - 1) * sc
    return m


def order_mode(adapter_type=""):
    """ANATOMY_CULL_ORDER: auto (the camera picks the direction of each page's lists), fwd (always the cluster order), rev.
    Unset: auto on integrated GPUs (UHD 770 draw pass about -35%), fwd on discrete ones (no gain on the RTX 3080, and a little
    slower there at some views)."""
    v = os.environ.get("ANATOMY_CULL_ORDER", "").strip().lower()
    if v in ("fwd", "rev", "auto"):
        return v
    from .cull_policy import adapter_class
    return "fwd" if adapter_class(adapter_type) == "discrete" else "auto"


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
    P_ = np.asarray(proj, dtype=np.float64)
    f[52:54] = (abs(1.0 / P_[0, 0]), abs(1.0 / P_[1, 1]))      # tan(half fov) x, y (orthographic: the half extents): cull_test.wgsl pixel_margin
    u[56:60] = (bits, samples, n_draws, 1 if ortho else 0)
    return f


class ClusterCuller:
    def __init__(self, gpu, geometry, id_format="r32uint", depth_eps=4e-6, pad_px=0.5, collect_stats=False,
                 profile=False, budget_tris=None):
        self.gpu, self.device, self.queue = gpu, gpu.device, gpu.queue
        self.geom = geometry
        self.id_format = id_format
        self.depth_eps, self.pad_px = float(depth_eps), float(pad_px)
        self.collect_stats = collect_stats
        self.classify_clip = os.environ.get(CLASSIFY_ENV, "1") != "0"      # cut views: draw the clusters off the cut planes without the discard
        self.profile = bool(profile) and "timestamp-query" in gpu.features
        if budget_tris is None:
            budget_tris = int(os.environ.get(BUDGET_ENV, DEFAULT_BUDGET_TRIS))
        self.requested_budget = max(0, int(budget_tris))
        self.budget_slots = self.budget_tris = 0           # the effective budget (prepare)
        self.cd = None
        self.buf = {}
        self._pipes, self._modules, self._bgl = {}, {}, {}
        self._pl_cache, self._cull_pipes_c = {}, None
        self._sring = []                    # counter readback ring: [buffer, promise, tag]
        self.stats_wanted = False           # encode() copies the frame's counters into a free ring slot (the renderer's choice input)
        self._sslot = None
        self._size = None
        self._flip = 0
        self._xf_last = None
        self._reset_vis = True
        self.stats = {}
        self.timings = {}

    # ------------------------------------------------------------------ layouts
    def _layouts(self):
        d = self.device
        self._pl_cache.clear()                 # pipeline layouts and the pipelines made with them belong to these layouts
        self._cull_pipes_c = None
        self._pipes.clear()
        C, V, F = SS.COMPUTE, SS.VERTEX, SS.FRAGMENT
        self.bgl_cull0 = d.create_bind_group_layout(entries=[
            _entry(0, "u", C), _entry(1, "u", C), _entry(2, "r", C), _entry(3, "w", C), _entry(4, "w", C), _entry(5, "u", C),
            _entry(6, "w", C)])
        self.bgl_sel_c = d.create_bind_group_layout(entries=[_entry(0, "u", C)])
        self.bgl_hzb_read = d.create_bind_group_layout(entries=[_entry(0, "tf", C)])
        self.bgl_hzbn = d.create_bind_group_layout(entries=[_entry(0, "tf", C), _entry(1, "sw", C)])
        self.bgl_vis0 = d.create_bind_group_layout(entries=[_entry(0, "u", V | F), _entry(1, "r", V), _entry(2, "r", V),
                                                            _entry(3, "u", V), _entry(4, "r", V)])
        self.bgl_vis1 = d.create_bind_group_layout(entries=[_entry(0, "r", V), _entry(1, "u", V)])
        self.bgl_vis2 = d.create_bind_group_layout(entries=[_entry(0, "u", V | F | C)])       # dsel: also the gather's and cull_idx's
        self.bgl_idx0 = d.create_bind_group_layout(entries=[_entry(0, "u", V | F), _entry(1, "r", V), _entry(2, "r", F),
                                                            _entry(3, "u", V | F), _entry(4, "r", F)])
        self.bgl_gat0 = d.create_bind_group_layout(entries=[_entry(0, "u", C), _entry(1, "r", C), _entry(2, "r", C), _entry(3, "w", C)])
        self.bgl_gat1 = d.create_bind_group_layout(entries=[_entry(0, "r", C), _entry(1, "u", C)])

    def _pl(self, *bgls):
        key = tuple(id(b) for b in bgls)
        pl = self._pl_cache.get(key)
        if pl is None:
            pl = self._pl_cache[key] = (self.device.create_pipeline_layout(bind_group_layouts=list(bgls)), bgls)
        return pl[0]

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
        return (self._ids_prelude() + "\n" + _read("clip.wgsl") + "\n" + _read("cull_tables.wgsl")
                + "\n" + geom_prelude(1, 1, 0, uniform_binding=1, compressed=self.geom.stage) + "\n" + _read("geom.wgsl") + "\n" + _read("cull_vis.wgsl"))

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

    def idx_wgsl(self):
        nl = "\n"
        return ("enable primitive_index;" + nl + self._ids_prelude() + nl + _read("clip.wgsl") + nl + _read("cull_tables.wgsl") + nl
                + geom_prelude(1, 1, 0, uniform_binding=1, compressed=self.geom.stage) + nl + _read("geom.wgsl") + nl + _read("cull_idx.wgsl"))

    def gather_wgsl(self):
        nl = "\n"
        return geom_prelude(1, 1, 0, uniform_binding=1, compressed=self.geom.stage) + nl + _read("geom.wgsl") + nl + _read("cull_gather.wgsl")

    def _idx_pipe(self, samples, clip):
        key = ("idx", samples, clip)
        if key not in self._pipes:
            m = self._module(("idx", self.id_format), self.idx_wgsl())
            self._pipes[key] = self.device.create_render_pipeline(
                layout=self._pl(self.bgl_idx0, self.bgl_vis1, self.bgl_vis2),
                vertex={"module": m, "entry_point": "vs"},
                fragment={"module": m, "entry_point": "fs_clip" if clip else "fs", "targets": [{"format": self.id_format}]},
                primitive={"topology": "triangle-list", "cull_mode": "none", "front_face": "ccw"},
                depth_stencil={"format": "depth32float", "depth_write_enabled": True, "depth_compare": "less"},
                multisample={"count": samples}, label=f"cullidx{'_clip' if clip else ''}x{samples}")
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
        for b in getattr(self, "pgo_ub", []):
            try:
                b.destroy()
            except Exception:
                pass
        self.pgo_ub = []
        if getattr(self, "hzb", None) is not None:
            self.hzb.destroy()
            self.hzb = None
        self.cd = None
        self._order_m = None
        self.budget_slots = self.budget_tris = 0
        for s in self._sring:
            try:
                s[0].destroy()
            except Exception:
                pass
        self._sring, self._sslot = [], None

    # ------------------------------------------------------------------ prepare
    def prepare(self, model, progress=None, use_cache=True, clusters=None, n_parts=None):
        """Build or load the clusters of the model and create the static GPU buffers. Returns a stats dict.
        ``clusters`` / ``n_parts`` let a caller that already owns a ClusterData (the stress scene) skip the build."""
        t0 = time.perf_counter()
        self.release()
        geom = self.geom
        self._layouts()
        if not getattr(geom, "cluster_ordered", False):
            raise cl.ClusterError("the culler draws cluster-ordered geometry: build it with build_geometry(..., cluster_order=True)")
        cd = clusters if clusters is not None else geom.clusters
        self.cd = cd
        t_clusters = time.perf_counter() - t0
        G = len(geom.pages)
        P = int(n_parts) if n_parts is not None else len(model.parts)
        R, C = cd.n_ranges, cd.n_clusters
        self.P, self.R, self.C, self.G = P, R, C, G
        self.cap = cl.page_capacity(cd, G)
        self.slot_base = 1 + np.concatenate([[0], np.cumsum(self.cap)[:-1]]).astype(np.int64)
        self.slot_base2 = self.slot_base + int(self.cap.sum())       # the second set of lists: the straddling clusters of a cut view
        self.n_slots = int(1 + 2 * self.cap.sum())
        if C >= (1 << 25):
            raise cl.ClusterError(f"{C} clusters do not fit the 31-bit culled id (cluster << 6 | triangle)")
        if int(self.cap.max(initial=0)) * CLUSTER_VERTS >= (1 << 32):
            raise cl.ClusterError("a page draws more than 2^32 vertices")
        lim = self.gpu.limits
        max_bind = int(lim.get("max_storage_buffer_binding_size", lim.get("max-storage-buffer-binding-size", 1 << 30)))
        self.cd_page_clusters = np.diff(np.asarray(cd.page_cfirst, dtype=np.int64))
        self._page_info(P)
        self._order_m = order_moments(cd)
        sec = self._sections(cd)
        for name, nbytes in (("cro", sec["cro_words"] * 4), ("cra", sec["cra_words"] * 4), ("crw", sec["crw_words"] * 4)):
            if nbytes > max_bind:
                raise cl.ClusterError(f"{name} needs {nbytes} bytes, binding limit {max_bind}")
        ST, UN = BU.STORAGE | BU.COPY_DST, BU.UNIFORM | BU.COPY_DST
        cro = np.zeros(sec["cro_words"], dtype=np.uint32)
        lay = sec["lay"]

        def put(vec4_at, arr):
            a_ = np.ascontiguousarray(arr).reshape(-1).view(np.uint32)
            cro[vec4_at * 4:vec4_at * 4 + a_.size] = a_

        put(lay[0], np.asarray(cd.cl_geom, dtype=np.float32))
        put(lay[1], cd.cl_range.astype(np.uint32))
        put(lay[2], np.frombuffer(np.ascontiguousarray(cd.range_table()).tobytes(), dtype=np.uint32))
        pt = np.zeros((2 * G, 4), dtype=np.uint32)
        for g in range(G):
            pt[g] = (cd.page_cfirst[g], cd.page_cfirst[g + 1], self.slot_base[g], self.cap[g])
            pt[G + g] = (cd.page_cfirst[g], cd.page_cfirst[g + 1], self.slot_base2[g], self.cap[g])
        put(lay[3], pt)
        put(sec["lay_b"][2], self.pinfo)
        put(sec["lay_b"][3], np.concatenate([self.pgp, np.zeros(-len(self.pgp) % 4, np.uint32)]) if len(self.pgp) else np.zeros(4, np.uint32))
        self._upload(self._new("cro", sec["cro_words"] * 4, ST), cro)
        self._new("cra", sec["cra_words"] * 4, BU.STORAGE | BU.COPY_SRC | BU.COPY_DST)
        self._new("crw", sec["crw_words"] * 4, BU.STORAGE | BU.INDIRECT | BU.COPY_SRC | BU.COPY_DST)
        self._new("crl", self.n_slots * 16, BU.STORAGE | BU.COPY_SRC)
        if self.budget_slots:
            self._new("cidx", self.budget_slots * 192 * 4, BU.STORAGE | BU.INDEX | BU.COPY_SRC)
        self.lay_ub = []
        for f in range(2):
            lw = np.zeros(20, dtype=np.uint32)
            lw[0:4], lw[4:8], lw[8:12], lw[12:16] = sec["lay"], sec["lay_b"], sec["lay_c"], sec["lay_d"]
            lw[16], lw[17] = sec["vis"][f], sec["vis"][1 - f]
            lw[18], lw[19] = self.budget_slots, G
            b_ = self._new(f"lay{f}", 80, UN)
            self.queue.write_buffer(b_, 0, lw)
            self.lay_ub.append(b_)
        self._new("frame_ub", FRAME_BYTES, UN)
        self._new("cfg_ub", 48, UN)
        self._new("nslots_ub", 16, UN)
        self.queue.write_buffer(self.buf["nslots_ub"], 0, np.array([self.C, 0, 0, 0], dtype=np.uint32))
        # per page: small uniforms
        self.sel_ub, self.dsel_ub, self.pgo_ub = [], [], []
        for g in range(G):
            page = geom.pages[g]
            self.pgo_ub.append(self.device.create_buffer_with_data(data=page.offsets_words(), usage=UN, label=f"cullpgo{g}"))
            sels, dsels = [], []
            for ph in range(2):
                b = self.device.create_buffer(size=16, usage=UN, label=f"sel{g}.{ph}")
                self.queue.write_buffer(b, 0, np.array([g, ph, 0, 0], dtype=np.uint32))
                sels.append(b)
            self.sel_ub.append(sels)
        for v in range(2 * G):              # list v = page v % G, class v // G (0: kept side / no cut, 1: straddles the cut planes)
            g = v % G
            dsels = []
            for ph in range(2):
                b2 = self.device.create_buffer(size=16, usage=UN, label=f"dsel{v}.{ph}")
                self.queue.write_buffer(b2, 0, np.array([v * 2 + ph, self.pinfo[g, 0], self.pinfo[g, 2], 0], dtype=np.uint32))
                dsels.append(b2)
            self.dsel_ub.append(dsels)
        self._wait()
        self._make_static_groups()
        self._flip = 0
        self._reset_vis = True
        self._xf_last = None
        self._hzb_key = None
        self._size = None
        self._cull0_bgs, self._mark_bgs = {}, {}
        mem = self.memory_report()
        self.prepare_stats = dict(cd.stats, clusters_s=t_clusters, prepare_s=time.perf_counter() - t0,
                                  capacity_blocks=[int(c) for c in self.cap], memory=mem)
        return self.prepare_stats

    def _page_info(self, P):
        """Per page: bits of the page-local vertex number in a compact index word, whether the page can use the indexed draw (vertex
        bits + bits of the part ordinal fit 32), the table ordinal -> part (pgp), and each part's ordinal. Sets the effective budget."""
        geom = self.geom
        G = len(geom.pages)
        self.pinfo = np.zeros((G, 4), dtype=np.uint32)
        pgp, self.part_ord = [], np.zeros(P, dtype=np.uint32)
        self.wg_total = 0
        for g, pg in enumerate(geom.pages):
            parts = [int(x) for x in pg.parts]
            vbits = max(1, (max(int(pg.nverts), 1) - 1).bit_length())
            kbits = max(len(parts) - 1, 0).bit_length()
            ok = (vbits + kbits <= 32) and vbits <= 31 and len(parts) > 0 and bool(self.requested_budget)
            self.pinfo[g] = (vbits, 1 if ok else 0, len(pgp), self.wg_total)       # w: first workgroup of the page in wgcnt (cull_test.wgsl)
            self.wg_total += -(-int(self.cd_page_clusters[g]) // 64)
            for k, q in enumerate(parts):
                if q < P:
                    self.part_ord[q] = k
            pgp.extend(parts)
        self.pgp = np.asarray(pgp, dtype=np.uint32)
        self.idx_pages = [bool(self.pinfo[g, 1]) for g in range(G)]
        slots = self.requested_budget // 64
        if not getattr(self.gpu, "prim_index", "primitive-index" in self.gpu.features) or not any(self.idx_pages):
            slots = 0
        lim = self.gpu.limits
        cap = min(int(lim.get("max_storage_buffer_binding_size", lim.get("max-storage-buffer-binding-size", 1 << 30))),
                  int(lim.get("max_buffer_size", lim.get("max-buffer-size", 1 << 30))), (1 << 32) - 1024)
        slots = min(slots, cap // (192 * 4), ((1 << 32) - 1) // 192 - 1)
        self.budget_slots, self.budget_tris = int(slots), int(slots) * 64
        if not slots:
            self.idx_pages = [False] * G
            self.pinfo[:, 1] = 0

    def _sections(self, cd):
        """Where every table lives in cro (vec4 units), cra / crw (words); fills self._where (name -> buffer, byte offset, bytes)
        and returns the words of the ``lay`` uniform (wgsl/cull_tables.wgsl)."""
        P, R, C, G, n = self.P, self.R, self.C, self.G, self.n_slots
        q4 = lambda x: -(-int(x) // 4)
        a_x = 0
        a_y = a_x + 2 * C
        a_z = a_y + q4(C)
        a_w = a_z + 2 * R
        b_x = a_w + 2 * G                  # ptab: 2 rows per page (the lists of class 0 and class 1)
        b_y = b_x + 5 * P
        b_z = b_y + q4(R)
        b_w = b_z + G
        cro_end = b_w + q4(max(len(self.pgp), 1))
        c_x, c_y = 0, 16 * G
        c_z = c_y + 16
        cra_end = c_z + C
        d_x = 0
        d_y = d_x + 64 * G                 # args: 16 words per (list, phase), 2 lists per page
        d_z = d_y
        d_w = d_z + 8 * G                  # dinfo: 2 words per (list, phase)
        e_x = d_w
        e_y = e_x + C
        k_x = e_y + C                      # keep flag per cluster (class and rank in its workgroup, 0: not kept; rewritten every phase)
        wg_x = k_x + C                     # per workgroup and class: survivors, then (after cull_scan) the offset in the list
        crw_end = wg_x + 2 * max(self.wg_total, 1)
        w = self._where = {}
        for name, buf, at, words in (("cl_geom", "cro", a_x * 4, 8 * C), ("cl_range", "cro", a_y * 4, C), ("rng", "cro", a_z * 4, 8 * R),
                                     ("ptab", "cro", a_w * 4, 8 * G), ("part_xf", "cro", b_x * 4, 20 * P),
                                     ("range_active", "cro", b_y * 4, R), ("pinfo", "cro", b_z * 4, 4 * G), ("pgp", "cro", b_w * 4, len(self.pgp)), ("pstate", "cra", c_x, 16 * G), ("stats", "cra", c_y, 16),
                                     ("seen", "cra", c_z, C), ("args", "crw", d_x, 64 * G),
                                     ("dinfo", "crw", d_z, 8 * G), ("vis0", "crw", e_x, C),
                                     ("vis1", "crw", e_y, C), ("kflag", "crw", k_x, C), ("wgcnt", "crw", wg_x, 2 * max(self.wg_total, 1))):
            w[name] = (buf, at * 4, words * 4)
        w["slot_cluster"] = ("crl", 0, 16 * n)
        return {"cro_words": cro_end * 4, "cra_words": cra_end, "crw_words": crw_end,
                "lay": (a_x, a_y, a_z, a_w), "lay_b": (b_x, b_y, b_z, b_w), "lay_c": (c_x, c_y, c_z, 0), "lay_d": (d_x, k_x, d_z, wg_x),
                "vis": (e_x, e_y)}

    def _bg(self, layout, entries):
        ents = []
        for i, r in enumerate(entries):
            if isinstance(r, tuple):
                ents.append({"binding": r[0], "resource": r[1]})
            else:
                ents.append({"binding": i, "resource": {"buffer": r, "offset": 0, "size": r.size}})
        return self.device.create_bind_group(layout=layout, entries=ents)

    def _whole(self, name):
        buf = self.buf[name]
        return {"buffer": buf, "offset": 0, "size": buf.size}

    def _make_static_groups(self):
        b = self.buf
        self.bg_sel_c = [self._bg(self.bgl_sel_c, [self.sel_ub[g][0]]) for g in range(self.G)]
        self.bg_vis1 = [self._bg(self.bgl_vis1, [self.geom.pages[g].buffer, self.pgo_ub[g]]) for g in range(self.G)]
        self.bg_vis2 = [[self._bg(self.bgl_vis2, [self.dsel_ub[v][ph]]) for ph in range(2)] for v in range(2 * self.G)]
        self.bg_vis0 = self._bg(self.bgl_vis0, [b["frame_ub"], b["cro"], b["crw"], b["lay0"], b["crl"]])
        self.bg_idx0 = self._bg(self.bgl_idx0, [b["frame_ub"], b["cro"], b["crw"], b["lay0"], b["crl"]])
        if self.budget_slots:
            self.bg_gat0 = self._bg(self.bgl_gat0, [b["lay0"], b["crl"], b["crw"], b["cidx"]])
            self.bg_gat1 = [self._bg(self.bgl_gat1, [self.geom.pages[g].buffer, self.pgo_ub[g]]) for g in range(self.G)]

    def memory_report(self):
        cd, b = self.cd, self.buf
        tri = max(cd.n_tris, 1)
        wh = self._where
        parts = {"cl_geom": wh["cl_geom"][2], "cl_range": wh["cl_range"][2], "rng": wh["rng"][2],
                 "vis_flags": wh["vis0"][2] + wh["vis1"][2], "visible_lists": wh["slot_cluster"][2],
                 "seen(stats)": wh["seen"][2], "part_xf+range_active": wh["part_xf"][2] + wh["range_active"][2],
                 "perm": 0, "vlook": 0, "compacted": 0}          # the old index-copy design's tables: gone (kept as 0 for the tools)
        parts["compact_index(bounded)"] = int(b["cidx"].size) if "cidx" in b else 0
        parts["page_tables(pinfo,pgp)"] = wh["pinfo"][2] + wh["pgp"][2]
        total = sum(parts.values())
        hz = getattr(self, "hzb_bytes", 0)
        return {"bytes": parts, "total_bytes": total, "per_triangle": total / tri,
                "static_per_triangle": (total - parts["compact_index(bounded)"]) / tri,
                "compacted_per_triangle": parts["compact_index(bounded)"] / tri, "budget_tris": self.budget_tris,
                "budget_requested": self.requested_budget, "hzb_bytes": hz,
                "cpu_perm_bytes": int(cd.perm.nbytes), "cpu_perm_mapped": isinstance(cd.perm, np.memmap)}

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
            code = (f"const SAMPLES: u32 = {samples}u;\n@group(0) @binding(0) var vis_id: {idt};\n{ld}\n" + _read("cull_tables.wgsl")
                    + "\n" + _read("cull_mark.wgsl"))
            C = SS.COMPUTE
            self.bgl_mark = self.device.create_bind_group_layout(entries=[
                _entry(0, "tu", C, ms=ms), _entry(1, "r", C), _entry(2, "w", C), _entry(3, "w", C), _entry(4, "u", C),
                _entry(5, "u", C)])
            self.pipe_mark = self._compute(("mark", samples, self.id_format), code, "mark", self._pl(self.bgl_mark))
            self.pipe_apply = self._compute(("mark", samples, self.id_format), code, "apply", self._pl(self.bgl_mark))
            self._mark_ids = id_view
            self._view_key = vk
            self._mark_bgs = {}

    def _mark_group(self, id_view):
        b = self.buf
        key = self._flip
        bg = self._mark_bgs.get(key)
        if bg is None:
            bg = self._bg(self.bgl_mark, [(0, id_view), (1, self._whole("cro")), (2, self._whole("cra")), (3, self._whole("crw")),
                                          (4, self._whole(f"lay{self._flip}")), (5, {"buffer": b["nslots_ub"], "offset": 0, "size": 16})])
            self._mark_bgs[key] = bg
        return bg

    def _cull0_group(self):
        b = self.buf
        cache = self.__dict__.setdefault("_cull0_bgs", {})
        if self._flip not in cache:
            cache[self._flip] = self._bg(self.bgl_cull0, [b["frame_ub"], b["cfg_ub"], b["cro"], b["cra"], b["crw"],
                                                          b[f"lay{self._flip}"], b["crl"]])
        return cache[self._flip]

    def _cull_pipes(self):
        code = _read("clip.wgsl") + "\n" + _read("cull_tables.wgsl") + "\n" + _read("cull_test.wgsl")
        lay = self._pl(self.bgl_cull0, self.bgl_sel_c, self.bgl_hzb_read)
        return {n: self._compute("cull_test", code, n, lay) for n in ("cull_p1", "cull_p2", "cull_scan", "cull_fill", "finalize_p1", "finalize_p2")}

    def _gather_pass(self, cp, ph, classes=1):
        """Fill the compact index buffer with the first slots of every page's list (indirect dispatch from crw)."""
        if not self.budget_slots:
            return
        if ("cull_gather", "gather") not in self._pipes:
            self._compute("cull_gather", self.gather_wgsl(), "gather", self._pl(self.bgl_gat0, self.bgl_gat1, self.bgl_vis2))
        cp.set_pipeline(self._pipes[("cull_gather", "gather")])
        cp.set_bind_group(0, self.bg_gat0)
        for v in range(self.G * classes):
            g = v % self.G
            if not self.idx_pages[g]:
                continue
            cp.set_bind_group(1, self.bg_gat1[g])
            cp.set_bind_group(2, self.bg_vis2[v][ph])
            cp.dispatch_workgroups_indirect(self.buf["crw"], self._where["args"][1] + (v * 2 + ph) * 64 + 48)

    # ------------------------------------------------------------------ per frame
    def reset(self):
        """Forget what was visible last frame (the next frame is a cold frame: everything is tested by phase 2)."""
        self._reset_vis = True

    def decode_bind_group_entries(self):
        """Buffers the resolve's decode group (cull_decode.wgsl) binds, in binding order: cro (read only storage), lay (uniform).
        ONE storage buffer: the resolve adds it to its table buffer and its geometry pages."""
        b = self.buf
        return [b["cro"], b["lay0"]]

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
        xu[idx, 19] = self.part_ord[idx]
        active = np.zeros(R, dtype=np.uint32)
        active[lr[cullable]] = 1
        return xf, active, unculled, int(cullable.sum())

    def order_flags(self, view, parts):
        """The three cfg words (cl.y .. cl.w): bit g set = the lists of page g are written last cluster first. Drawing in index order is
        right when the index grows away from the camera (front to back: the early depth test rejects what is behind), so a page is
        reversed when the camera looks against the drift of its active ranges. Depends only on the camera and the cull inputs."""
        mode = order_mode(getattr(self.gpu, "adapter_type", ""))
        G = min(self.G, ORDER_PAGES)
        bits = [0, 0, 0]
        if mode == "fwd" or G == 0:
            return bits
        rev = np.ones(G, dtype=bool)
        if mode == "auto":
            part = np.asarray(parts.part, dtype=np.int64)
            level = np.asarray(parts.level, dtype=np.int64)
            cd = self.cd
            lr = cd.level_range[part, np.minimum(level, cl.LEVEL_COUNT - 1)]
            ok = (~cd.uncullable[part]) & (lr >= 0)
            score = np.zeros(self.G, dtype=np.float64)
            if ok.any():
                f = -np.asarray(view, dtype=np.float64)[2, :3]                     # the viewing direction in world space
                m3 = np.asarray(parts.matrix, dtype=np.float64)[ok][:, :3, :3]
                fp_ = np.einsum("nji,j->ni", m3, f)                                # ... in part space (the transpose of the part's linear map)
                r = lr[ok]
                sc = np.einsum("ni,ni->n", fp_, self._order_m[r])                  # > 0: the index grows away from the camera
                score = np.bincount(np.asarray(cd.r_page, dtype=np.int64)[r], weights=sc, minlength=self.G)
            rev = score[:G] < 0.0
        for g in np.nonzero(rev)[0]:
            bits[int(g) // 32] |= 1 << (int(g) % 32)
        return bits

    def encode(self, enc, view, proj, size, id_view, depth_view, samples, parts, clip=None, ortho=False,
               draw_unculled=None, out_size=None, bits=20, accept_all=False):
        """Record the visibility pass (both phases) into ``enc``. Returns a CullResult. accept_all: every cluster of an active
        range is drawn (no frustum or occlusion test): compressed geometry draws through the culler even where culling is off."""
        assert self.cd is not None, "prepare() first"
        w, h = int(size[0]), int(size[1])
        self._ensure_size(w, h, samples, id_view, depth_view)
        clip = clip or ClipState()
        xf, active, unculled, n_cull = self._frame_inputs(parts)
        b, q = self.buf, self.queue
        if self._xf_last is None or not np.array_equal(xf, self._xf_last):
            q.write_buffer(b["cro"], self._where["part_xf"][1], xf)
            self._xf_last = xf
        q.write_buffer(b["cro"], self._where["range_active"][1], active)
        q.write_buffer(b["frame_ub"], 0, pack_frame(view, proj, size, samples, clip, out_size, ortho, bits))
        cfg = np.zeros(12, dtype=np.float32)
        cu = cfg.view(np.uint32)
        cu[0:4] = (self.hz_levels, 1 if self.collect_stats else 0, self.hz_dims[0], self.hz_dims[1])
        cfg[4], cfg[5] = self.depth_eps, self.pad_px
        classify = clip.any and self.classify_clip
        cu[8] = 1 if classify else 0
        cu[9:12] = self.order_flags(view, parts)
        cfg[6] = 1.0 if accept_all else 0.0
        q.write_buffer(b["cfg_ub"], 0, cfg)
        if self._reset_vis:
            self._clear(enc, "vis0")
            self._clear(enc, "vis1")
            self._clear(enc, "seen")
            self._reset_vis = False
        self._clear(enc, f"vis{1 - self._flip}")
        self._clear(enc, "pstate")
        self._clear(enc, "stats")
        pipes = self._cull_pipes()
        cd = self.cd
        G = self.G
        bg0 = self._cull0_group()
        qs = self._qs() if self.profile else None

        def tw(i, last=False):
            if qs is None:
                return None
            return {"query_set": qs, "beginning_of_pass_write_index": 2 * i, "end_of_pass_write_index": 2 * i + 1}

        classes = 2 if classify else 1

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
            # the survivors of every list in cluster order: offsets of the workgroups (one scan workgroup per list), then the entries
            cp.set_pipeline(pipes["cull_scan"])
            cp.set_bind_group(1, self.bg_sel_c[0])
            cp.dispatch_workgroups(G * classes, 1, 1)
            cp.set_pipeline(pipes["cull_fill"])
            for g in range(G):
                n = int(cd.page_cfirst[g + 1] - cd.page_cfirst[g])
                if n == 0:
                    continue
                cp.set_bind_group(1, self.bg_sel_c[g])
                x, y, _ = _grid(-(-n // 64))
                cp.dispatch_workgroups(x, y, 1)
            cp.set_pipeline(pipes[fin])
            cp.set_bind_group(1, self.bg_sel_c[0])
            cp.dispatch_workgroups(1, 1, 1)
            self._gather_pass(cp, ph, classes)

        # ---- phase 1: visible last frame
        cp = enc.begin_compute_pass(timestamp_writes=tw(0))
        phase_compute(cp, "cull_p1", "finalize_p1", 0)
        cp.end()
        clip_on = clip.any
        rp = enc.begin_render_pass(
            color_attachments=[{"view": id_view, "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 0)}],
            depth_stencil_attachment={"view": depth_view, "depth_load_op": "clear", "depth_store_op": "store",
                                      "depth_clear_value": 1.0}, timestamp_writes=tw(1))
        self._draws(rp, samples, clip_on, classify, 0)
        if draw_unculled is not None and len(unculled):
            draw_unculled(rp, unculled)
        rp.end()
        # ---- depth pyramid from this frame's real depth, then phase 2
        cp = enc.begin_compute_pass(timestamp_writes=tw(2))
        cp.set_pipeline(self.pipe_hzb0)
        cp.set_bind_group(0, self.bg_hzb0)
        cp.dispatch_workgroups(-(-self.hz_dims[0] // 8), -(-self.hz_dims[1] // 8), 1)   # 8x8 texels (16x16 pixels) per group
        cp.end()
        cp = enc.begin_compute_pass(timestamp_writes=tw(3))
        pn = self._pipes.get((("hzbn",), "hzbn")) or self._compute(("hzbn",), _read("cull_hzbn.wgsl"), "hzbn", self._pl(self.bgl_hzbn))
        for l in range(1, self.hz_levels):
            dw, dh = max(1, -(-self.hz_dims[0] >> l)), max(1, -(-self.hz_dims[1] >> l))
            cp.set_pipeline(pn)
            cp.set_bind_group(0, self.bg_hzbn[l - 1])
            cp.dispatch_workgroups(-(-dw // 8), -(-dh // 8), 1)
        cp.end()
        cp = enc.begin_compute_pass(timestamp_writes=tw(4))
        phase_compute(cp, "cull_p2", "finalize_p2", 1)
        cp.end()
        rp = enc.begin_render_pass(
            color_attachments=[{"view": id_view, "load_op": "load", "store_op": "store"}],
            depth_stencil_attachment={"view": depth_view, "depth_load_op": "load", "depth_store_op": "store"},
            timestamp_writes=tw(5))
        self._draws(rp, samples, clip_on, classify, 1)
        rp.end()
        # ---- phase 2 already wrote next frame's phase-1 set (vis_next). The id image is only read to count the
        # clusters that really own a sample (statistics: the "truly visible" column); the renderer needs no such pass.
        self._marked = self.collect_stats
        if self.collect_stats:
            cp = enc.begin_compute_pass(timestamp_writes=tw(6))
            cp.set_pipeline(self.pipe_mark)
            cp.set_bind_group(0, self._mark_group(id_view))
            cp.dispatch_workgroups(-(-w // 8), -(-h // 8), 1)
            cp.set_pipeline(self.pipe_apply)
            cp.dispatch_workgroups(*_grid(-(-self.C // 64)))
            cp.end()
        if qs is not None:
            # every resolved query must have been written: the mark pass owns slots 8/9 and is skipped without statistics
            enc.resolve_query_set(qs, 0, 14 if self.collect_stats else 12, b["ts_buf"], 0)
        self._sslot = None
        if self.stats_wanted:
            slot = self._free_slot()
            if slot is not None:
                buf, at, nbytes = self._where["stats"]
                enc.copy_buffer_to_buffer(self.buf[buf], at, slot[0], 0, 64)
                self._sslot = slot
        self._flip = 1 - self._flip
        self._last_clip = clip_on
        return CullResult(unculled=unculled, clip=clip_on, n_parts=n_cull)

    def _clear(self, enc, name):
        buf, at, nbytes = self._where[name]
        enc.clear_buffer(self.buf[buf], at, nbytes)

    def _draws(self, rp, samples, clip, classify, ph):
        """Both phases' draws. With ``classify`` the lists of class 0 (clusters wholly on the kept side) are drawn with the plain
        fragment stage, only the straddling lists (class 1) with the discard; without it every list takes the discard when clip."""
        base = self._where["args"][1]
        classes = 2 if classify else 1
        if self.budget_slots:                  # the slots inside the budget: one indexed indirect draw per page
            rp.set_bind_group(0, self.bg_idx0)
            rp.set_index_buffer(self.buf["cidx"], "uint32", 0, self.buf["cidx"].size)
            for k in range(classes):
                rp.set_pipeline(self._idx_pipe(samples, bool(clip) and (k == 1 or not classify)))
                for g in range(self.G):
                    v = g + self.G * k
                    if self.cap[g] == 0 or not self.idx_pages[g]:
                        continue
                    rp.set_bind_group(1, self.bg_vis1[g])
                    rp.set_bind_group(2, self.bg_vis2[v][ph])
                    rp.draw_indexed_indirect(self.buf["crw"], base + (v * 2 + ph) * 64)
        for k in range(classes):                # the rest (or everything with budget 0): pulled, non-indexed
            rp.set_pipeline(self._vis_pipe(samples, bool(clip) and (k == 1 or not classify)))
            rp.set_bind_group(0, self.bg_vis0)
            for g in range(self.G):
                v = g + self.G * k
                if self.cap[g] == 0:
                    continue
                rp.set_bind_group(1, self.bg_vis1[g])
                rp.set_bind_group(2, self.bg_vis2[v][ph])
                rp.draw_indirect(self.buf["crw"], base + (v * 2 + ph) * 64 + 32)

    def _qs(self):
        if "ts_buf" not in self.buf:
            self._new("ts_buf", 112, BU.QUERY_RESOLVE | BU.COPY_SRC)
            self._qset = self.device.create_query_set(type="timestamp", count=14)
        return self._qset

    # ------------------------------------------------------------------ results (call after the encoder was submitted)
    def read_stats(self):
        """Counters of the last encode (needs collect_stats=True): clusters / triangles per stage."""
        data = self.read_buffer("stats", 64).view(np.uint32).copy()
        self.stats = {n: int(data[i]) for i, n in enumerate(STAT_NAMES)}
        return self.stats

    # ------------------------------------------------------------------ counters without a stall (the renderer's culler / plain choice)
    STAT_RING = 4

    def _free_slot(self):
        for s in self._sring:
            if s[1] is None and s is not self._sslot:
                return s
        if len(self._sring) < self.STAT_RING:
            s = [self.device.create_buffer(size=64, usage=BU.MAP_READ | BU.COPY_DST, label="cull_stats_rb"), None, None]
            self._sring.append(s)
            return s
        return None

    def stats_arm(self, tag):
        """After the frame's encoder was submitted: start mapping the counter copy encode() made (no wait). ``tag`` comes back
        with the counters from stats_poll()."""
        slot, self._sslot = self._sslot, None
        if slot is not None:
            slot[1], slot[2] = slot[0].map_async("READ"), tag

    def stats_poll(self):
        """[(tag, kept_clusters, pulled_clusters)] of the armed frames whose copy has finished. Never waits: a map whose callback
        has not fired yet stays for a later call (wgpu-py without the thread event is treated as not finished)."""
        out = []
        for s in [s for s in self._sring if s[1] is not None]:
            event = getattr(s[1], "_thread_event", None)
            if event is None or not event.is_set():
                continue
            promise, tag, s[1], s[2] = s[1], s[2], None, None
            try:
                promise.sync_wait()
                data = np.frombuffer(bytes(s[0].read_mapped(copy=False)), dtype=np.uint32)
                out.append((tag, int(data[13]), int(data[14])))
            finally:
                if s[0].map_state == "mapped":
                    s[0].unmap()
        return out

    def read_timings(self, period_ns):
        """GPU milliseconds of the last encode per stage (needs profile=True and a timestamp period).
        hzb0 / hzbn / cull2 are the hi-Z mip 0, the remaining hi-Z mips and the phase-2 test; hzb_cull2 is their sum."""
        ts = np.frombuffer(bytes(self.queue.read_buffer(self.buf["ts_buf"], 0, 112)), dtype=np.uint64).astype(np.float64)
        ms = (ts[1::2] - ts[0::2]) * period_ns * 1e-6
        names = ("cull1", "pass1", "hzb0", "hzbn", "cull2", "pass2", "mark")
        self.timings = {n: float(v) for n, v in zip(names, ms)}
        self.timings["hzb_cull2"] = float(ms[2:5].sum())
        if not getattr(self, "_marked", False):
            self.timings["mark"] = 0.0
            ms = ms[:6]
        self.timings["total_ms"] = float(ms.sum())
        return self.timings

    # ------------------------------------------------------------------ debugging / checks
    def read_buffer(self, name, size=None):
        """Bytes of a named table (sections of cro / cra / crw, see _sections) or of a whole buffer (perm, compactN, ...)."""
        if name in self._where:
            buf, at, nbytes = self._where[name]
            return np.frombuffer(bytes(self.queue.read_buffer(self.buf[buf], at, size or nbytes)), dtype=np.uint8)
        b = self.buf[name]
        return np.frombuffer(bytes(self.queue.read_buffer(b, 0, size or b.size)), dtype=np.uint8)

    def decode_ids(self, ids, slot_cluster=None):
        """CPU decode of culled ids -> (cluster, part, ORIGINAL triangle in the (part, level) range, range) arrays (-1 where not
        culled). id = 0x80000000 | cluster << 6 | triangle-in-cluster; the stored triangle (64 * j + triangle, j = the cluster's
        number inside its range) maps to the original one through perm. ``slot_cluster`` is accepted for old callers and unused."""
        cd = self.cd
        ids = np.asarray(ids, dtype=np.uint32)
        tagged = (ids & np.uint32(CULL_TAG)) != 0
        c = np.where(tagged, (ids & np.uint32(0x7FFFFFFF)) >> np.uint32(6), 0).astype(np.int64)
        local = (ids & np.uint32(63)).astype(np.int64)
        r = cd.cl_range[c].astype(np.int64)
        tri = np.asarray(cd.perm[cd.r_tfirst[r] + 64 * (c - cd.r_cfirst[r]) + local]).astype(np.int64)
        part = cd.r_part[r].astype(np.int64)
        return (np.where(tagged, c, -1), np.where(tagged, part, -1), np.where(tagged, tri, -1), np.where(tagged, r, -1))
