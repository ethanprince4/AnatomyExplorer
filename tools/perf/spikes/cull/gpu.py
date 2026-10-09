"""GPU side of the culling spike (wgpu-py). See shaders.py for the WGSL."""
import time

import numpy as np
import wgpu

import shaders as SH

W_DEFAULT, H_DEFAULT = 2560, 1600
STAGES = ["cull1", "prep", "raster1", "hzb", "cull2", "raster2", "mark", "shade"]
BU = wgpu.BufferUsage
TU = wgpu.TextureUsage


def pick_adapter(kind, backend="Vulkan"):
    want = "NVIDIA" if kind == "3080" else "Intel"
    for a in wgpu.gpu.enumerate_adapters_sync():
        if want in a.summary and a.info.get("backend_type") == backend:
            return a
    raise RuntimeError(f"adapter {kind}/{backend} not found")


def entry(binding, kind, vis):
    e = {"binding": binding, "visibility": vis}
    if kind == "u":
        e["buffer"] = {"type": "uniform"}
    elif kind == "r":
        e["buffer"] = {"type": "read-only-storage"}
    elif kind == "w":
        e["buffer"] = {"type": "storage"}
    elif kind == "tu":
        e["texture"] = {"sample_type": "uint", "view_dimension": "2d"}
    elif kind == "td":
        e["texture"] = {"sample_type": "depth", "view_dimension": "2d"}
    elif kind == "tf":
        e["texture"] = {"sample_type": "unfilterable-float", "view_dimension": "2d"}
    elif kind == "sw":
        e["storage_texture"] = {"access": "write-only", "format": "r32float", "view_dimension": "2d"}
    return e


class CullRenderer:
    def __init__(self, adapter, geo, scene, W=W_DEFAULT, H=H_DEFAULT):
        self.W, self.H = W, H
        self.geo, self.scene = geo, scene
        self.adapter = adapter
        feats = ["timestamp-query"]
        self.device = adapter.request_device_sync(
            required_features=feats,
            required_limits={"max-storage-buffers-per-shader-stage": 16})
        d = self.device
        self.q = d.queue
        self.buffers = {}   # name -> bytes
        self._upload_scene()
        self._textures()
        self._pipelines()
        self._bind_groups()
        self.qs = d.create_query_set(type="timestamp", count=2 * len(STAGES))
        self.ts_buf = d.create_buffer(size=16 * len(STAGES), usage=BU.QUERY_RESOLVE | BU.COPY_SRC)
        self.rb_ts = d.create_buffer(size=16 * len(STAGES), usage=BU.MAP_READ | BU.COPY_DST)
        self.rb_cnt = d.create_buffer(size=64 + 32, usage=BU.MAP_READ | BU.COPY_DST)
        # wgpu-py returns raw ticks: NVIDIA 1.0 ns/tick, Intel 19.2 MHz = 52.083 ns/tick (checked against wall time in run.py calib)
        self.ts_period = 52.0833 if "Intel" in adapter.summary else 1.0
        self.flip = 0
        self.hidden = np.zeros(scene.n_inst, dtype=np.uint32)
        self.last = {}

    # ---------- resources ----------
    def buf(self, name, size, usage, data=None):
        size = max(16, (size + 3) & ~3)
        b = self.device.create_buffer(size=size, usage=usage | BU.COPY_DST | BU.COPY_SRC, label=name)
        if data is not None:
            raw = np.ascontiguousarray(data).tobytes() if isinstance(data, np.ndarray) else data
            if len(raw) % 4:
                raw = bytes(raw) + bytes(4 - len(raw) % 4)
            self.q.write_buffer(b, 0, raw)
        self.buffers[name] = size
        return b

    def _upload_scene(self):
        g, s = self.geo, self.scene
        st = BU.STORAGE
        self.b_ci = self.buf("ci_table", s.ci_table.nbytes, st, s.ci_table)
        self.b_clusters = self.buf("clusters", g.cluster_rec.nbytes, st, g.cluster_rec)
        self.b_inst = self.buf("instances", s.instances.nbytes, st, s.instances)
        parts = np.zeros((len(g.part_lo), 2, 4), dtype=np.float32)
        parts[:, 0, :3] = g.part_lo
        parts[:, 1, :3] = g.part_ext
        self.b_parts = self.buf("parts", parts.nbytes, st, parts)
        assert len(g.vpages) <= 4 and len(g.ipages) <= 2, (len(g.vpages), len(g.ipages))
        self.b_vp = [self.buf(f"vpage{i}", len(g.vpages[i]) if i < len(g.vpages) else 16, st,
                              g.vpages[i] if i < len(g.vpages) else None) for i in range(4)]
        self.b_ip = [self.buf(f"ipage{i}", len(g.ipages[i]) if i < len(g.ipages) else 16, st,
                              g.ipages[i] if i < len(g.ipages) else None) for i in range(2)]
        n = s.n_ci
        self.scene_buffer_names = ["ci_table", "clusters", "instances", "parts"] + [f"vpage{i}" for i in range(4)] + [f"ipage{i}" for i in range(2)]
        self.b_flags = self.buf("inst_flags", s.n_inst * 4, st, np.zeros(s.n_inst, np.uint32))
        self.b_vis = [self.buf(f"vis_bits{i}", n * 4, st) for i in range(2)]
        self.b_list1 = self.buf("list1", n * 4, st)
        self.b_list2 = self.buf("list2", n * 4, st)
        self.b_cand = self.buf("cand", n * 4, st)
        self.b_ref = self.buf("ref_list", n * 4, st)
        self.b_args = self.buf("draw_args", 32, st | BU.INDIRECT)
        self.b_disp = self.buf("dispatch_args", 16, st | BU.INDIRECT)
        self.b_cnt = self.buf("counters", 64, st)
        self.b_glob = self.buf("globals", 288, BU.UNIFORM)
        self.b_dump = self.buf("dump", self.W * self.H * 8, st)
        self.rb_dump = self.device.create_buffer(size=self.W * self.H * 8, usage=BU.MAP_READ | BU.COPY_DST)

    def _textures(self):
        d, W, H = self.device, self.W, self.H
        self.t_depth = d.create_texture(size=(W, H, 1), format="depth32float", usage=TU.RENDER_ATTACHMENT | TU.TEXTURE_BINDING)
        self.t_vis = d.create_texture(size=(W, H, 1), format="r32uint", usage=TU.RENDER_ATTACHMENT | TU.TEXTURE_BINDING)
        self.t_color = d.create_texture(size=(W, H, 1), format="rgba8unorm", usage=TU.RENDER_ATTACHMENT | TU.COPY_SRC)
        w0, h0 = (W + 1) // 2, (H + 1) // 2
        self.hzb_dims = [(w0, h0)]
        while self.hzb_dims[-1] != (1, 1):
            a, b = self.hzb_dims[-1]
            self.hzb_dims.append(((a + 1) // 2, (b + 1) // 2))
        self.hzb_levels = len(self.hzb_dims)
        # WebGPU mip sizes halve with floor; pad the base so that floor == ceil at every logical level
        m = 1 << (self.hzb_levels - 1)
        bw, bh = ((w0 + m - 1) // m) * m, ((h0 + m - 1) // m) * m
        self.hzb_phys = (bw, bh)
        self.t_hzb = d.create_texture(size=(bw, bh, 1), format="r32float", mip_level_count=self.hzb_levels,
                                      usage=TU.STORAGE_BINDING | TU.TEXTURE_BINDING | TU.COPY_SRC)
        self.v_depth = self.t_depth.create_view(aspect="depth-only")
        self.v_vis = self.t_vis.create_view()
        self.v_color = self.t_color.create_view()
        self.v_hzb = self.t_hzb.create_view()
        self.v_hzb_mip = [self.t_hzb.create_view(base_mip_level=i, mip_level_count=1) for i in range(self.hzb_levels)]
        self.tex_bytes = {"depth32": W * H * 4, "visbuf": W * H * 4, "color": W * H * 4,
                          "hzb": sum(max(1, bw >> i) * max(1, bh >> i) for i in range(self.hzb_levels)) * 4}

    def _layout(self, spec, vis):
        d = self.device
        bgl = d.create_bind_group_layout(entries=[entry(b, k, vis) for b, k in spec])
        return bgl, d.create_pipeline_layout(bind_group_layouts=[bgl])

    def _pipelines(self):
        d = self.device
        C, V, F = wgpu.ShaderStage.COMPUTE, wgpu.ShaderStage.VERTEX, wgpu.ShaderStage.FRAGMENT
        geo = [(0, "u"), (1, "r"), (2, "r"), (3, "r"), (4, "r")] + [(5 + i, "r") for i in range(6)]
        self.L = {}
        self.L["cull1"] = self._layout([(0, "u"), (1, "r"), (2, "r"), (3, "r"), (4, "r"), (5, "r"), (6, "w"), (7, "w"), (8, "w"), (9, "w")], C)
        self.L["prep"] = self._layout([(4, "w"), (7, "w"), (9, "w")], C)
        self.L["cull2"] = self._layout([(0, "u"), (1, "r"), (2, "r"), (3, "r"), (5, "r"), (6, "w"), (7, "w"), (9, "w"), (10, "tf")], C)
        self.L["raster"] = self._layout(geo + [(11, "r")], V)
        self.L["shade"] = self._layout(geo + [(11, "tu")], F)
        self.L["hzb0"] = self._layout([(0, "td"), (1, "sw"), (2, "u")], C)
        self.L["hzbn"] = self._layout([(0, "tf"), (1, "sw"), (2, "u")], C)
        self.L["mark"] = self._layout([(0, "tu"), (1, "w"), (2, "w")], C)
        self.L["dump"] = self._layout([(0, "tu"), (1, "td"), (2, "w")], C)

        def cp(name, src, lay):
            m = d.create_shader_module(code=src, label=name)
            return d.create_compute_pipeline(layout=self.L[lay][1], compute={"module": m, "entry_point": "main"}, label=name)
        self.P = {
            "cull1": cp("cull1", SH.CULL1, "cull1"), "prep": cp("prep", SH.PREP, "prep"),
            "cull2": cp("cull2", SH.CULL2, "cull2"), "hzb0": cp("hzb0", SH.HZB0, "hzb0"),
            "hzbn": cp("hzbn", SH.HZBN, "hzbn"), "mark": cp("mark", SH.MARK, "mark"), "dump": cp("dump", SH.DUMP, "dump"),
        }
        rm = d.create_shader_module(code=SH.RASTER, label="raster")
        self._raster_mod = rm

        def rp(cull):
            return d.create_render_pipeline(
                layout=self.L["raster"][1],
                vertex={"module": rm, "entry_point": "vs"},
                fragment={"module": rm, "entry_point": "fs", "targets": [{"format": "r32uint"}]},
                primitive={"topology": "triangle-list", "front_face": "ccw", "cull_mode": cull},
                depth_stencil={"format": "depth32float", "depth_write_enabled": True, "depth_compare": "greater"},
                label=f"raster_{cull}")
        self.P["raster"] = rp("back")
        self.P["raster_nocull"] = rp("none")
        sm = d.create_shader_module(code=SH.SHADE, label="shade")
        self.P["shade"] = d.create_render_pipeline(
            layout=self.L["shade"][1], vertex={"module": sm, "entry_point": "vs"},
            fragment={"module": sm, "entry_point": "fs", "targets": [{"format": "rgba8unorm"}]},
            primitive={"topology": "triangle-list"}, label="shade")

    def _bind_groups(self):
        d = self.device

        def bg(lay, items):
            ents = []
            for b, r in items:
                if isinstance(r, wgpu.GPUBuffer):
                    ents.append({"binding": b, "resource": {"buffer": r, "offset": 0, "size": r.size}})
                else:
                    ents.append({"binding": b, "resource": r})
            return d.create_bind_group(layout=self.L[lay][0], entries=ents)
        geo = [(0, self.b_glob), (1, self.b_ci), (2, self.b_clusters), (3, self.b_inst), (4, self.b_parts)] + \
              [(5 + i, self.b_vp[i]) for i in range(4)] + [(9 + i, self.b_ip[i]) for i in range(2)]
        self.bg = {}
        for f in (0, 1):
            self.bg[f"cull1_{f}"] = bg("cull1", [(0, self.b_glob), (1, self.b_ci), (2, self.b_clusters), (3, self.b_inst),
                                                  (4, self.b_flags), (5, self.b_vis[f]), (6, self.b_list1), (7, self.b_args),
                                                  (8, self.b_cand), (9, self.b_cnt)])
            self.bg[f"mark_{f}"] = bg("mark", [(0, self.v_vis), (1, self.b_vis[1 - f]), (2, self.b_cnt)])
        self.bg["prep"] = bg("prep", [(4, self.b_disp), (7, self.b_args), (9, self.b_cnt)])
        self.bg["cull2"] = bg("cull2", [(0, self.b_glob), (1, self.b_ci), (2, self.b_clusters), (3, self.b_inst),
                                         (5, self.b_cand), (6, self.b_list2), (7, self.b_args), (9, self.b_cnt), (10, self.v_hzb)])
        self.bg["raster1"] = bg("raster", geo + [(11, self.b_list1)])
        self.bg["raster2"] = bg("raster", geo + [(11, self.b_list2)])
        self.bg["rasterref"] = bg("raster", geo + [(11, self.b_ref)])
        self.bg["shade"] = bg("shade", geo + [(11, self.v_vis)])
        self.b_hzb_u = []
        for i in range(self.hzb_levels):
            sw, sh = (self.W, self.H) if i == 0 else self.hzb_dims[i - 1]
            dw, dh = self.hzb_dims[i]
            self.b_hzb_u.append(d.create_buffer_with_data(data=np.array([sw, sh, dw, dh], np.uint32).tobytes(), usage=BU.UNIFORM))
        self.bg["hzb"] = [bg("hzb0", [(0, self.v_depth), (1, self.v_hzb_mip[0]), (2, self.b_hzb_u[0])])] +                          [bg("hzbn", [(0, self.v_hzb_mip[i - 1]), (1, self.v_hzb_mip[i]), (2, self.b_hzb_u[i])]) for i in range(1, self.hzb_levels)]
        self.bg["dump"] = bg("dump", [(0, self.v_vis), (1, self.v_depth), (2, self.b_dump)])

    # ---------- memory report ----------
    def memory_report(self):
        sc = sum(self.buffers[n] for n in self.scene_buffer_names)
        fb = sum(v for k, v in self.buffers.items() if k not in self.scene_buffer_names and k not in ("dump", "ref_list"))
        tex = sum(self.tex_bytes.values())
        return {"scene_geometry_bytes": sc, "per_frame_buffer_bytes": fb, "texture_bytes": tex,
                "total_bytes": sc + fb + tex,
                "per_frame_without_debug": fb + tex}

    # ---------- per frame ----------
    def set_hidden(self, hidden):
        self.hidden = hidden.astype(np.uint32)
        self.q.write_buffer(self.b_flags, 0, self.hidden.tobytes())

    def seed_visible(self, mask_ci):
        self.q.write_buffer(self.b_vis[self.flip], 0, mask_ci.astype(np.uint32).tobytes())

    def clear_visible(self):
        self.q.write_buffer(self.b_vis[self.flip], 0, bytes(self.scene.n_ci * 4))

    def pack_globals(self, view, proj, cone=True):
        from scene import frustum_planes
        VP = proj @ view
        pl = frustum_planes(VP)
        cam = np.linalg.inv(view)[:3, 3]
        f = np.zeros(72, dtype=np.float32)
        f[0:16] = view.T.reshape(-1)
        f[16:32] = VP.T.reshape(-1)
        f[32:52] = pl.reshape(-1)
        f[52:56] = [cam[0], cam[1], cam[2], 0]
        f[56:60] = [self.W, self.H, proj[0, 0], proj[1, 1]]
        f[60:64] = [proj[2, 3], 0, 0, 0]
        u = np.array([self.scene.n_ci, self.hzb_levels, 1 if cone else 0, 0], dtype=np.uint32)
        f[64:68] = u.view(np.float32)
        ld = np.array([0.35, 0.8, 0.5])
        ld /= np.linalg.norm(ld)
        f[68:72] = [ld[0], ld[1], ld[2], 0]
        return f.tobytes()

    def _rpass(self, enc, name, stage, clear, pipeline, bgroup, draw):
        i = STAGES.index(stage)
        ca = [{"view": self.v_vis, "load_op": "clear" if clear else "load", "store_op": "store", "clear_value": (0, 0, 0, 0)}]
        ds = {"view": self.v_depth, "depth_load_op": "clear" if clear else "load", "depth_store_op": "store", "depth_clear_value": 0.0}
        rp = enc.begin_render_pass(color_attachments=ca, depth_stencil_attachment=ds,
                                   timestamp_writes={"query_set": self.qs, "beginning_of_pass_write_index": 2 * i, "end_of_pass_write_index": 2 * i + 1})
        rp.set_pipeline(pipeline)
        rp.set_bind_group(0, bgroup)
        draw(rp)
        rp.end()

    def _cpass(self, enc, stage):
        i = STAGES.index(stage)
        return enc.begin_compute_pass(timestamp_writes={"query_set": self.qs, "beginning_of_pass_write_index": 2 * i, "end_of_pass_write_index": 2 * i + 1})

    def frame(self, view, proj, readback=True, cone=True, shade=True):
        """One culled frame. Returns dict with CPU ms and (if readback) counters and per-stage GPU ms."""
        t0 = time.perf_counter()
        W, H = self.W, self.H
        f = self.flip
        self.q.write_buffer(self.b_glob, 0, self.pack_globals(view, proj, cone))
        self.q.write_buffer(self.b_cnt, 0, bytes(64))
        self.q.write_buffer(self.b_args, 0, np.array([SH.TRI_VERTS, 0, 0, 0, SH.TRI_VERTS, 0, 0, 0], np.uint32).tobytes())
        enc = self.device.create_command_encoder()
        enc.clear_buffer(self.b_vis[1 - f])
        nwg = (self.scene.n_ci + 63) // 64
        cp = self._cpass(enc, "cull1")
        cp.set_pipeline(self.P["cull1"])
        cp.set_bind_group(0, self.bg[f"cull1_{f}"])
        cp.dispatch_workgroups(min(nwg, 32768), (nwg + 32767) // 32768, 1)
        cp.end()
        cp = self._cpass(enc, "prep")
        cp.set_pipeline(self.P["prep"])
        cp.set_bind_group(0, self.bg["prep"])
        cp.dispatch_workgroups(1)
        cp.end()
        self._rpass(enc, "r1", "raster1", True, self.P["raster"], self.bg["raster1"],
                    lambda rp: rp.draw_indirect(self.b_args, 0))
        cp = self._cpass(enc, "hzb")
        for lvl in range(self.hzb_levels):
            cp.set_pipeline(self.P["hzb0" if lvl == 0 else "hzbn"])
            cp.set_bind_group(0, self.bg["hzb"][lvl])
            w, h = self.hzb_dims[lvl]
            cp.dispatch_workgroups((w + 7) // 8, (h + 7) // 8, 1)
        cp.end()
        cp = self._cpass(enc, "cull2")
        cp.set_pipeline(self.P["cull2"])
        cp.set_bind_group(0, self.bg["cull2"])
        cp.dispatch_workgroups_indirect(self.b_disp, 0)
        cp.end()
        self._rpass(enc, "r2", "raster2", False, self.P["raster"], self.bg["raster2"],
                    lambda rp: rp.draw_indirect(self.b_args, 16))
        cp = self._cpass(enc, "mark")
        cp.set_pipeline(self.P["mark"])
        cp.set_bind_group(0, self.bg[f"mark_{f}"])
        cp.dispatch_workgroups((W + 7) // 8, (H + 7) // 8, 1)
        cp.end()
        self._shade_pass(enc)
        if readback:
            enc.resolve_query_set(self.qs, 0, 2 * len(STAGES), self.ts_buf, 0)
            enc.copy_buffer_to_buffer(self.ts_buf, 0, self.rb_ts, 0, 16 * len(STAGES))
            enc.copy_buffer_to_buffer(self.b_cnt, 0, self.rb_cnt, 0, 64)
            enc.copy_buffer_to_buffer(self.b_args, 0, self.rb_cnt, 64, 32)
        self.q.submit([enc.finish()])
        t1 = time.perf_counter()
        self.flip = 1 - f
        out = {"cpu_ms": (t1 - t0) * 1e3}
        if readback:
            out.update(self._read_stats())
        return out

    def _shade_pass(self, enc):
        i = STAGES.index("shade")
        rp = enc.begin_render_pass(
            color_attachments=[{"view": self.v_color, "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 1)}],
            timestamp_writes={"query_set": self.qs, "beginning_of_pass_write_index": 2 * i, "end_of_pass_write_index": 2 * i + 1})
        rp.set_pipeline(self.P["shade"])
        rp.set_bind_group(0, self.bg["shade"])
        rp.draw(3)
        rp.end()

    def _read_stats(self):
        self.rb_ts.map_sync(wgpu.MapMode.READ)
        ts = np.frombuffer(bytes(self.rb_ts.read_mapped()), dtype=np.uint64).copy()
        self.rb_ts.unmap()
        self.rb_cnt.map_sync(wgpu.MapMode.READ)
        c = np.frombuffer(bytes(self.rb_cnt.read_mapped()), dtype=np.uint32).copy()
        self.rb_cnt.unmap()
        ms = {s: float(ts[2 * i + 1] - ts[2 * i]) * 1e-6 * self.ts_period for i, s in enumerate(STAGES)}
        ms["total_span"] = float(ts[-1] - ts[0]) * 1e-6 * self.ts_period
        cnt = c[:16]
        a = c[16:24]
        return {"ms": ms, "live": int(cnt[0]), "frustum": int(cnt[1]), "cone": int(cnt[2]), "p1": int(cnt[3]),
                "cand": int(cnt[4]), "p2": int(a[5]), "p1_tris": int(cnt[6]), "p2_tris": int(cnt[7]), "marked": int(cnt[8])}


    def wait(self):
        """Block until all submitted work is done (map a tiny buffer written at the end of the queue)."""
        if not hasattr(self, "rb_fence"):
            self.rb_fence = self.device.create_buffer(size=16, usage=BU.MAP_READ | BU.COPY_DST)
        enc = self.device.create_command_encoder()
        enc.copy_buffer_to_buffer(self.b_cnt, 0, self.rb_fence, 0, 16)
        self.q.submit([enc.finish()])
        self.rb_fence.map_sync(wgpu.MapMode.READ)
        self.rb_fence.unmap()

    # ---------- reference (brute force, same pipeline, chunked submits) ----------
    def reference(self, view, proj, cull_mode="back", chunk_tris=10_000_000, hidden=None):
        s = self.scene
        hid = self.hidden if hidden is None else hidden
        live = np.nonzero(hid[s.ci_table[:, 0]] == 0)[0].astype(np.uint32)
        self.q.write_buffer(self.b_ref, 0, live.tobytes())
        self.q.write_buffer(self.b_glob, 0, self.pack_globals(view, proj, True))
        pipe = self.P["raster"] if cull_mode == "back" else self.P["raster_nocull"]
        per = max(1, chunk_tris // 70)
        first = True
        for st in range(0, len(live), per):
            n = min(per, len(live) - st)
            enc = self.device.create_command_encoder()
            self._ref_pass(enc, first, pipe, st, n)
            self.q.submit([enc.finish()])
            self.wait()
            first = False
        if first:  # nothing to draw
            enc = self.device.create_command_encoder()
            self._ref_pass(enc, True, pipe, 0, 0)
            self.q.submit([enc.finish()])
        return self.dump()

    def _ref_pass(self, enc, clear, pipe, st, n):
        ca = [{"view": self.v_vis, "load_op": "clear" if clear else "load", "store_op": "store", "clear_value": (0, 0, 0, 0)}]
        ds = {"view": self.v_depth, "depth_load_op": "clear" if clear else "load", "depth_store_op": "store", "depth_clear_value": 0.0}
        rp = enc.begin_render_pass(color_attachments=ca, depth_stencil_attachment=ds)
        rp.set_pipeline(pipe)
        rp.set_bind_group(0, self.bg["rasterref"])
        if n:
            rp.draw(SH.TRI_VERTS, n, 0, st)
        rp.end()

    def dump(self):
        W, H = self.W, self.H
        enc = self.device.create_command_encoder()
        cp = enc.begin_compute_pass()
        cp.set_pipeline(self.P["dump"])
        cp.set_bind_group(0, self.bg["dump"])
        cp.dispatch_workgroups((W + 7) // 8, (H + 7) // 8, 1)
        cp.end()
        enc.copy_buffer_to_buffer(self.b_dump, 0, self.rb_dump, 0, W * H * 8)
        self.q.submit([enc.finish()])
        self.rb_dump.map_sync(wgpu.MapMode.READ)
        a = np.frombuffer(bytes(self.rb_dump.read_mapped()), dtype=np.uint32).reshape(H, W, 2).copy()
        self.rb_dump.unmap()
        return a[:, :, 0], a[:, :, 1].view(np.float32)

    def read_buffer(self, buf, nbytes):
        rb = self.device.create_buffer(size=nbytes, usage=BU.MAP_READ | BU.COPY_DST)
        enc = self.device.create_command_encoder()
        enc.copy_buffer_to_buffer(buf, 0, rb, 0, nbytes)
        self.q.submit([enc.finish()])
        rb.map_sync(wgpu.MapMode.READ)
        out = bytes(rb.read_mapped())
        rb.unmap()
        rb.destroy()
        return out

    def culled_dump(self):
        return self.dump()
