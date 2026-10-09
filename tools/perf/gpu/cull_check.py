"""Cluster culling check (app/gpu/cull.py) against an unculled render with the same vertex math.

  python tools/perf/gpu/cull_check.py correct [--models pancreas eyeball] [--adapter "RTX 3080"] [--size 1280 800]
  python tools/perf/gpu/cull_check.py numbers [--models pancreas colon_wall] [--adapter UHD] [--lod on|off|both]

correct: for every scenario and frame the culled picture (ClusterCuller.encode: frustum, phase 1, depth pyramid, phase 2)
and the unculled picture (every triangle of the same parts and LOD levels, one indexed draw per part, the same
`world_of` vertex function and part matrices) are rendered at 4x MSAA into two id + depth targets and compared per
SAMPLE (not per pixel). Ids are decoded to (part, triangle of the index range). Per sample:
  false cull   culled depth is farther than the reference depth (a nearer triangle is missing)  -> must be 0
  nearer       culled depth is nearer than the reference (impossible: culled is a subset)       -> must be 0
  tie          equal depth (within 4 depth ulps) but another triangle won: draw order, not a culling error
Scenarios (every one without a warm-up frame unless it says so): cold, warm static, warm orbit, cold orbit, outer 20 %
and 50 % hidden, re-shown, cut plane, LOD levels changing, exploded, exploded + moving.

numbers: per model in its reference view: clusters / triangles total, frustum survivors, phase 1 and phase 2 drawn,
truly visible; GPU time of cull + both passes (culler) against the unculled pass with the same shader, median of N frames
(run under S/tools/gpu_lock.py). LOD forced to level 0 ("culling alone") and with the renderer's LOD choice.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REF_BITS = 18
TOL = 2.4e-7                    # four ulps of a depth near 1


# ------------------------------------------------------------------------------------------------ WGSL of the reference
REF_WGSL = """
@group(2) @binding(1) var<storage, read> ref_part: array<u32>;
struct VOutR {
    @builtin(position) clip: vec4<f32>,
    @location(0) wpos: vec3<f32>,
    @location(1) @interpolate(flat) noclip: u32,
    @location(2) @interpolate(flat) slot: u32,
};
@vertex
fn vs_ref(@builtin(vertex_index) vi: u32, @builtin(instance_index) slot: u32) -> VOutR {
    let part = ref_part[slot];
    let w = world_of(part_matrix(part), g_vertex(0u, vi));
    var o: VOutR;
    o.clip = frame.vp * vec4<f32>(w, 1.0);
    o.wpos = w;
    o.noclip = part_flags(part) & 1u;
    o.slot = slot;
    return o;
}
@fragment
fn fs_ref(in: VOutR, @builtin(primitive_index) prim: u32) -> @location(0) IdOut {
    return pack_id(((in.slot + 1u) << REF_BITS) | prim);
}
@fragment
fn fs_ref_clip(in: VOutR, @builtin(primitive_index) prim: u32) -> @location(0) IdOut {
    if (clipped(frame.clip, in.wpos, in.noclip != 0u)) {
        discard;
    }
    return pack_id(((in.slot + 1u) << REF_BITS) | prim);
}
""".replace("REF_BITS", f"{REF_BITS}u")


def dump_wgsl(samples, id_format):
    ms = samples > 1
    idt = "texture_multisampled_2d<u32>" if ms else "texture_2d<u32>"
    dt = "texture_depth_multisampled_2d" if ms else "texture_depth_2d"
    s = "s" if ms else "0"
    if id_format == "r32uint":
        ld = f"textureLoad(ids, p, {s}).x"
    else:
        ld = f"(textureLoad(ids, p, {s}).x | (textureLoad(ids, p, {s}).y << 8u) | (textureLoad(ids, p, {s}).z << 16u) | (textureLoad(ids, p, {s}).w << 24u))"
    return f"""
@group(0) @binding(0) var ids: {idt};
@group(0) @binding(1) var dep: {dt};
@group(0) @binding(2) var<storage, read_write> outb: array<u32>;
@compute @workgroup_size(8, 8)
fn dump(@builtin(global_invocation_id) gid: vec3<u32>) {{
    let d = textureDimensions(ids);
    if (gid.x >= d.x || gid.y >= d.y) {{ return; }}
    let p = vec2<i32>(gid.xy);
    for (var k = 0; k < {samples}; k = k + 1) {{
        let s = k;
        let o = ((gid.y * d.x + gid.x) * {samples}u + u32(k)) * 2u;
        outb[o] = {ld};
        outb[o + 1u] = bitcast<u32>(textureLoad(dep, p, {s}));
    }}
}}
"""


# ------------------------------------------------------------------------------------------------ harness
class Harness:
    def __init__(self, model_id, adapter=None, size=(1280, 800), samples=4, page_mib=None, profile=False, stats=True,
                 session=True, budget=None):
        import wgpu
        from tools.perf.gpu import visbuf_check as vc
        from app.gpu.renderer import WgpuRenderer
        from app.gpu.cull import ClusterCuller
        self.wgpu = wgpu
        self.gpu = vc.make_gpu(adapter)
        self.vc = vc
        self.sess = vc.new_session(model_id)
        self.model = self.sess.model
        self.samples = samples
        self.size = (int(size[0]), int(size[1])) if size else tuple(self.sess.render_size)
        page = None if not page_mib else int(page_mib) << 20
        self.R = WgpuRenderer(self.gpu, page_bytes=page)
        self.R.set_model(self.model)
        # the culler draws cluster-ordered geometry: replace the renderer's pages by our own cluster-ordered ones
        from app.gpu import geometry as G
        page_bytes = self.R.geom.page_bytes
        compressed = bool(self.R.geom.compressed)             # what the renderer decided for this model (ANATOMY_GEOM_COMPRESS)
        self.R.geom.release()
        self.geom = G.build_geometry(self.model, G.GpuSink(self.gpu.device), page_bytes, cluster_order=True, compress=compressed)
        self.order = self.geom.order
        self.id_format = self.R.id_format
        self.budget = budget                       # compact index budget in triangles (None: ANATOMY_CULL_BUDGET / the default)
        kw = {} if budget is None else {"budget_tris": int(budget)}
        self.cu = ClusterCuller(self.gpu, self.geom, id_format=self.id_format, collect_stats=stats, profile=profile, **kw)
        self.prep = self.cu.prepare(self.model)
        self.d, self.q = self.gpu.device, self.gpu.queue
        self.period_ns = None
        self._targets()
        self._ref_pipes()
        self.lod_on = True

    # ---- targets
    def _targets(self):
        wgpu = self.wgpu
        TU = wgpu.TextureUsage
        w, h = self.size
        self.tex = {}
        for nm in ("c", "r"):
            idt = self.d.create_texture(size=(w, h, 1), format=self.id_format, sample_count=self.samples,
                                        usage=TU.RENDER_ATTACHMENT | TU.TEXTURE_BINDING | TU.COPY_SRC)
            dpt = self.d.create_texture(size=(w, h, 1), format="depth32float", sample_count=self.samples,
                                        usage=TU.RENDER_ATTACHMENT | TU.TEXTURE_BINDING | TU.COPY_SRC)
            self.tex[nm] = (idt, dpt, idt.create_view(), dpt.create_view())
        BU = wgpu.BufferUsage
        self.dump_buf = self.d.create_buffer(size=w * h * self.samples * 8, usage=BU.STORAGE | BU.COPY_SRC)
        self.dump_buf2 = self.d.create_buffer(size=w * h * self.samples * 8, usage=BU.STORAGE | BU.COPY_SRC)
        SS = wgpu.ShaderStage
        ms = self.samples > 1
        self.bgl_dump = self.d.create_bind_group_layout(entries=[
            {"binding": 0, "visibility": SS.COMPUTE, "texture": {"sample_type": "uint", "view_dimension": "2d", "multisampled": ms}},
            {"binding": 1, "visibility": SS.COMPUTE, "texture": {"sample_type": "depth", "view_dimension": "2d", "multisampled": ms}},
            {"binding": 2, "visibility": SS.COMPUTE, "buffer": {"type": "storage"}}])
        mod = self.d.create_shader_module(code=dump_wgsl(self.samples, self.id_format))
        self.pipe_dump = self.d.create_compute_pipeline(
            layout=self.d.create_pipeline_layout(bind_group_layouts=[self.bgl_dump]),
            compute={"module": mod, "entry_point": "dump"})
        self.bg_dump = {}
        for nm, buf in (("c", self.dump_buf), ("r", self.dump_buf2)):
            self.bg_dump[nm] = self.d.create_bind_group(layout=self.bgl_dump, entries=[
                {"binding": 0, "resource": self.tex[nm][2]}, {"binding": 1, "resource": self.tex[nm][3]},
                {"binding": 2, "resource": {"buffer": buf, "offset": 0, "size": buf.size}}])
        self._qs = self.d.create_query_set(type="timestamp", count=2) if "timestamp-query" in self.gpu.features else None
        self._qbuf = self.d.create_buffer(size=16, usage=BU.QUERY_RESOLVE | BU.COPY_SRC)

    # ---- the unculled reference
    def _ref_pipes(self):
        d, wgpu = self.d, self.wgpu
        cu = self.cu
        SS = wgpu.ShaderStage
        self.bgl_ref2 = d.create_bind_group_layout(entries=[
            {"binding": 1, "visibility": SS.VERTEX, "buffer": {"type": "read-only-storage"}}])
        mod = d.create_shader_module(code="enable primitive_index;\n" + cu.vis_wgsl() + REF_WGSL)
        self.ref_pipe = {}
        for clip in (False, True):
            self.ref_pipe[clip] = d.create_render_pipeline(
                layout=d.create_pipeline_layout(bind_group_layouts=[cu.bgl_vis0, cu.bgl_vis1, self.bgl_ref2]),
                vertex={"module": mod, "entry_point": "vs_ref"},
                fragment={"module": mod, "entry_point": "fs_ref_clip" if clip else "fs_ref", "targets": [{"format": self.id_format}]},
                primitive={"topology": "triangle-list", "cull_mode": "none", "front_face": "ccw"},
                depth_stencil={"format": "depth32float", "depth_write_enabled": True, "depth_compare": "less"},
                multisample={"count": self.samples})
        self.ref_part_buf = None

    def _ref_draws(self, fp):
        """[(page, first_index, count, slot)], ref_part table, per slot first-triangle offset."""
        geom = self.geom
        out, part_of, off, lev = [], [], [], []
        for pi, k in zip(fp.part, fp.level):
            rr = geom.ranges[int(pi)]
            first, count = rr[int(k)] if k < len(rr) else rr[0]
            if count < 3 or geom.page_of[int(pi)] < 0:
                continue
            tris = count // 3
            cap = 1 << REF_BITS
            for a in range(0, tris, cap):
                n = min(cap, tris - a)
                out.append((int(geom.page_of[int(pi)]), first + 3 * a, 3 * n, len(part_of)))
                part_of.append(int(pi))
                off.append(a)
                lev.append(int(k))
        self._ref_level = np.array(lev, dtype=np.int64)
        return out, np.array(part_of, dtype=np.uint32), np.array(off, dtype=np.int64)

    # ---- CPU side of one frame (what WgpuRenderer.render does before its passes)
    def frame_parts(self, camera, fs):
        from app.gpu.cull import FrameParts
        R, m = self.R, self.model
        w, h = self.size
        aspect = w / h
        camera.aspect = aspect
        V = camera.view_matrix()
        Pm = camera.proj_matrix(aspect)
        VP = Pm @ V
        halves = camera.ortho_halves(aspect) if camera.ortho else camera.half_tans(aspect)
        fs, vis, ghost, alpha = R._state(fs)
        R._fs = fs
        R._refresh_transforms(m)
        R._level = R._lod_levels(V, halves, camera.ortho, h) if self.lod_on else {}
        draws, _oit = R.visible_parts(VP, vis, ghost, alpha, fs)
        index_of = {p.id: i for i, p in enumerate(m.parts)}
        part, level, mats, noclip, weight = [], [], [], [], []
        for p in draws:
            pi = index_of[p.id]
            M, _nm, _flip, wt, nc, _key = R._transform(p)
            part.append(pi)
            level.append(R._level.get(p.id, 0))
            mats.append(M)
            noclip.append(nc)
            weight.append(wt)
        fp = FrameParts(part=np.array(part, dtype=np.int64), level=np.array(level, dtype=np.int64),
                        matrix=np.array(mats, dtype=np.float64).reshape(-1, 4, 4), noclip=np.array(noclip, dtype=bool),
                        weight=np.array(weight, dtype=np.float64), slot0=np.zeros(len(part), dtype=np.uint32))
        return fp, V, Pm, camera.ortho

    def clip_state(self, fs):
        from app.gpu.cull import ClipState
        return ClipState(planes=np.array(fs.clip_planes, dtype=np.float32), on=tuple(int(bool(x)) for x in fs.clip_on),
                         mode=int(fs.clip_mode))

    # ---- one frame: culled + reference, compared
    def run_frame(self, camera, fs, compare=True, timing=False, frame=None):
        """``frame`` = (FrameParts, view, proj, ortho, ClipState) replaces the CPU side (the stress scene)."""
        cu, d, q = self.cu, self.d, self.q
        if frame is not None:
            fp, V, Pm, ortho, clip = frame
        else:
            fp, V, Pm, ortho = self.frame_parts(camera, fs)
            clip = self.clip_state(fs)
        enc = d.create_command_encoder()
        res = cu.encode(enc, V, Pm, self.size, self.tex["c"][2], self.tex["c"][3], self.samples, fp, clip=clip, ortho=ortho)
        assert len(res.unculled) == 0, "unexpected unculled parts"
        # reference pass: same frame uniform / part table, every triangle of the parts
        draws, part_of, _off = self._ref_draws(fp)
        self._ref_off = _off
        self._ref_part_of = part_of
        need = max(len(part_of), 4) * 4
        if self.ref_part_buf is None or self.ref_part_buf.size < need:
            self.ref_part_buf = d.create_buffer(size=max(need * 2, 1024), usage=self.wgpu.BufferUsage.STORAGE | self.wgpu.BufferUsage.COPY_DST)
            self.bg_ref2 = d.create_bind_group(layout=self.bgl_ref2, entries=[
                {"binding": 1, "resource": {"buffer": self.ref_part_buf, "offset": 0, "size": self.ref_part_buf.size}}])
        if len(part_of):
            q.write_buffer(self.ref_part_buf, 0, part_of)
        tw = {"query_set": self._qs, "beginning_of_pass_write_index": 0, "end_of_pass_write_index": 1} if (timing and self._qs) else None
        rp = enc.begin_render_pass(
            color_attachments=[{"view": self.tex["r"][2], "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 0)}],
            depth_stencil_attachment={"view": self.tex["r"][3], "depth_load_op": "clear", "depth_store_op": "store",
                                      "depth_clear_value": 1.0}, **({"timestamp_writes": tw} if tw else {}))
        rp.set_pipeline(self.ref_pipe[clip.any])
        rp.set_bind_group(0, cu.bg_vis0)
        rp.set_bind_group(2, self.bg_ref2)
        cur = -1
        for page, first, count, slot in draws:
            if page != cur:
                rp.set_bind_group(1, cu.bg_vis1[page])
                pg_ = self.geom.pages[page]
                if not self.geom.compressed:
                    rp.set_index_buffer(pg_.buffer, "uint32", pg_.index_byte_offset, pg_.index_bytes)
                cur = page
            if self.geom.compressed:       # no hardware index buffer: vertex_index = logical index position (g_vertex)
                rp.draw(count, 1, first, slot)
            else:
                rp.draw_indexed(count, 1, first, 0, slot)
        rp.end()
        if tw:
            enc.resolve_query_set(self._qs, 0, 2, self._qbuf, 0)
        w, h = self.size
        if compare:
            for nm in ("c", "r"):
                cp = enc.begin_compute_pass()
                cp.set_pipeline(self.pipe_dump)
                cp.set_bind_group(0, self.bg_dump[nm])
                cp.dispatch_workgroups(-(-w // 8), -(-h // 8), 1)
                cp.end()
        q.submit([enc.finish()])
        out = {"parts": len(fp.part), "unculled": len(res.unculled)}
        if cu.collect_stats:
            out["stats"] = cu.read_stats()
        if timing and self._qs:
            ts = np.frombuffer(bytes(q.read_buffer(self._qbuf, 0, 16)), dtype=np.uint64).astype(np.float64)
            out["ref_ms"] = float((ts[1] - ts[0]) * self.period_ns * 1e-6)
        if compare:
            out.update(self.compare())
        return out

    def _read(self, buf):
        n = self.size[0] * self.size[1] * self.samples
        raw = np.frombuffer(bytes(self.q.read_buffer(buf, 0, n * 8)), dtype=np.uint32).reshape(n, 2)
        return raw[:, 0].copy(), raw[:, 1].copy().view(np.float32)

    def compare(self):
        cu = self.cu
        ic, dc = self._read(self.dump_buf)
        ir, dr = self._read(self.dump_buf2)
        n = len(ic)
        cl, part_c, tri_c, _r = cu.decode_ids(ic)
        bg_c, bg_r = ic == 0, ir == 0
        slot = (ir >> np.uint32(REF_BITS)).astype(np.int64)
        prim = (ir & np.uint32((1 << REF_BITS) - 1)).astype(np.int64)
        okr = slot > 0
        sl = np.where(okr, slot - 1, 0)
        part_r = np.where(okr, self._ref_part_of[np.minimum(sl, max(len(self._ref_part_of) - 1, 0))].astype(np.int64), -1) if len(self._ref_part_of) else np.full(n, -1)
        if len(self._ref_off):
            k_ = np.minimum(sl, len(self._ref_off) - 1)
            # the reference draws the stored (cluster-ordered) index range: map its triangle back to the original one
            tri_r = np.where(okr, self.order.original(part_r, self._ref_level[k_], self._ref_off[k_] + prim), -1)
        else:
            tri_r = np.full(n, -1)
        diff = dc.astype(np.float64) - dr
        false_cull = diff > TOL
        nearer = diff < -TOL
        same_id = (part_c == part_r) & (tri_c == tri_r) & (bg_c == bg_r)
        tie = ~same_id & ~false_cull & ~nearer
        npx = self.size[0] * self.size[1]
        fc_px = false_cull.reshape(npx, self.samples).any(axis=1)
        fg = ~bg_r
        # the culled ids may only carry the culling tag (renderer's own ids are never mixed in)
        stray = (~bg_c) & (cl < 0)
        return {"samples": n, "ref_fg_samples": int(fg.sum()), "false_cull_samples": int(false_cull.sum()),
                "false_cull_pixels": int(fc_px.sum()), "nearer_samples": int(nearer.sum()), "tie_samples": int(tie.sum()),
                "stray_ids": int(stray.sum()),
                "max_false_cull_depth": float(diff[false_cull].max()) if false_cull.any() else 0.0}

    # ---- states
    def base_state(self):
        w = self.sess.w
        fs = w.frame_state()
        return copy.copy(fs)

    def reset_view(self):
        w = self.sess.w
        st = self.sess.state
        st.hidden[:] = False
        st._vis_dirty()
        self.model.set_explode(0.0)
        w.reset_view(animate=False)
        w.camera.snap()
        return w.camera

    def item_order_outer(self):
        """Visible items, most enclosing (outermost) first."""
        m = self.model
        n = len(m.items)
        boxes = [m.item_bounds([i]) for i in range(n)]
        cnt = []
        for i in range(n):
            lo, hi = boxes[i]
            pad = 0.02 * float(np.linalg.norm(hi - lo))
            c = sum(1 for j in range(n) if j != i and np.all(boxes[j][0] >= lo - pad) and np.all(boxes[j][1] <= hi + pad))
            cnt.append((-c, -float(np.linalg.norm(hi - lo)), i))
        return [i for *_k, i in sorted(cnt)]


def fmt(r):
    keys = ("parts", "false_cull_samples", "false_cull_pixels", "nearer_samples", "tie_samples", "stray_ids", "ref_fg_samples")
    s = " ".join(f"{k}={r[k]}" for k in keys if k in r)
    st = r.get("stats")
    if st:
        s += (f" | active={st['active']} frustum={st['frustum']} p1={st['p1']} p2={st['p2']} vis={st['visible']} ovf={st['overflow']}"
              f" idx={st.get('idx_slots', 'n/a')} pull={st.get('pull_slots', 'n/a')}")
    return s


def run_correct(args):
    results = []
    bad = 0
    for model_id in args.models:
        H = Harness(model_id, args.adapter, size=args.size, page_mib=args.page_mib, budget=args.budget)
        print(f"== {model_id} budget={getattr(H.cu, 'budget_tris', 'n/a')} on {H.gpu.info}: clusters={H.prep['clusters']} tris={H.prep['triangles']} "
              f"cap={sum(H.prep['capacity_blocks'])} pages={len(H.geom.pages)} build={H.prep['clusters_s']:.2f}s "
              f"cached={H.prep.get('cached')}", flush=True)
        if args.mutate is not None:
            H.cu.depth_eps = args.mutate
        cam = H.reset_view()
        fs0 = H.base_state()
        order = H.item_order_outer()

        def hide(fs, frac):
            f = copy.copy(fs)
            f.visible = (fs.visible.copy() if fs.visible is not None else np.ones(len(H.model.items), bool))
            k = max(1, int(round(frac * len(order))))
            for i in order[:k]:
                f.visible[i] = False
            return f

        def frame(label, fs, **kw):
            r = H.run_frame(cam, fs, **kw)
            r["scenario"] = label
            r["model"] = model_id
            r["adapter"] = H.gpu.info
            results.append(r)
            nonlocal bad
            if r["false_cull_samples"] or r["nearer_samples"] or r["stray_ids"]:
                bad += 1
            print(f"  {label:34s} {fmt(r)}", flush=True)

        def warm(n=2):
            for _ in range(n):
                H.run_frame(cam, fs0, compare=False)

        # cold: no history at all
        H.cu.reset()
        frame("cold default", fs0)
        frame("warm static #1", fs0)
        frame("warm static #2", fs0)
        for i in range(args.orbit):
            cam.orbit(args.step, 2.0 if i % 3 == 0 else 0.0)
            cam.snap()
            frame(f"warm orbit {i + 1}", fs0)
        cam = H.reset_view()
        H.cu.reset()
        for i in range(3):
            cam.orbit(25.0, 5.0)
            cam.snap()
            frame(f"cold orbit {i + 1} (big steps)", fs0)
        for frac in (0.2, 0.5):
            cam = H.reset_view()
            H.cu.reset()
            warm(3)
            frame(f"hide outer {int(frac * 100)}% (no warm-up)", hide(fs0, frac))
            frame(f"hide outer {int(frac * 100)}% second frame", hide(fs0, frac))
            frame(f"re-show all after hide {int(frac * 100)}%", fs0)
        # cut plane
        cam = H.reset_view()
        H.cu.reset()
        warm(3)
        m = H.model
        lo, hi = np.asarray(m.bounds_min, float), np.asarray(m.bounds_max, float)
        fsc = copy.copy(fs0)
        fsc.clip_planes = ((1.0, 0.0, 0.0, -float((lo[0] + hi[0]) / 2)), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0))
        fsc.clip_on = (True, False, False)
        frame("cut plane on (no warm-up)", fsc)
        frame("cut plane on, second frame", fsc)
        fsc2 = copy.copy(fsc)
        fsc2.clip_planes = ((1.0, 0.0, 0.0, -float(lo[0] + (hi[0] - lo[0]) * 0.3)), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0))
        frame("cut plane moved", fsc2)
        frame("cut plane off again", fs0)
        # LOD levels changing
        cam = H.reset_view()
        H.cu.reset()
        warm(3)
        d0 = cam.distance
        for f in (2.0, 4.0, 8.0, 3.0, 1.0):
            cam.distance = d0 * f
            cam.snap()
            frame(f"LOD: distance x{f:g}", fs0)
        # explode
        cam = H.reset_view()
        H.cu.reset()
        warm(3)
        for amt in (0.3, 0.6, 0.6, 0.0):
            H.model.set_explode(amt)
            frame(f"explode {amt:g}", fs0)
        H.model.set_explode(0.0)
        # LOD off (level 0 everywhere) once
        H.lod_on = False
        cam = H.reset_view()
        H.cu.reset()
        frame("no LOD: cold", fs0)
        cam.orbit(10.0, 0.0)
        cam.snap()
        frame("no LOD: warm orbit", fs0)
        H.release()
    Path(args.out).write_text(json.dumps(results, indent=1))
    tot = {k: sum(r[k] for r in results) for k in ("false_cull_samples", "nearer_samples", "stray_ids", "tie_samples")}
    print("TOTAL frames", len(results), tot, "frames with a problem:", bad)
    return 1 if bad else 0


def Harness_release(self):
    self.cu.release()
    self.R.release()
    self.sess.close()


Harness.release = Harness_release


def run_numbers(args):
    from tools.perf.gpu import visbuf_check as vc
    rows = []
    for model_id in args.models:
        H = Harness(model_id, args.adapter, size=args.size if args.size else None, profile=True, stats=False, budget=args.budget)
        period, wall = vc.calibrate_period_ns(H.gpu)
        H.period_ns = period
        print(f"== {model_id} on {H.gpu.info}, {H.size}, timestamp period {period:.3f} ns", flush=True)
        for lod in ((True, False) if args.lod == "both" else ((args.lod == "on",))):
            H.lod_on = lod
            cam = H.reset_view()
            fs0 = H.base_state()
            H.cu.reset()
            H.cu.collect_stats = True
            for _ in range(4):
                H.run_frame(cam, fs0, compare=False)
            r = H.run_frame(cam, fs0, compare=False, timing=True)
            st = dict(r["stats"])
            H.cu.collect_stats = False
            cull_ms, ref_ms = [], []
            for _ in range(args.frames):
                r = H.run_frame(cam, fs0, compare=False, timing=True)
                t = H.cu.read_timings(period)
                cull_ms.append(t)
                ref_ms.append(r["ref_ms"])
            tot = {k: float(np.median([t[k] for t in cull_ms])) for k in cull_ms[0]}
            row = {"model": model_id, "adapter": H.gpu.info, "size": list(H.size), "lod": lod,
                   "clusters": H.prep["clusters"], "triangles": H.prep["triangles"],
                   "frustum_clusters": st["frustum"], "frustum_tris": st["frustum_tris"],
                   "p1_clusters": st["p1"], "p1_tris": st["p1_tris"], "p2_clusters": st["p2"], "p2_tris": st["p2_tris"],
                   "visible_clusters": st["visible"], "visible_tris": st["visible_tris"], "active_clusters": st["active"],
                   "cull_total_ms": tot["total_ms"], "stage_ms": {k: v for k, v in tot.items() if k != "total_ms"},
                   "idx_slots": st.get("idx_slots"), "pull_slots": st.get("pull_slots"), "budget_tris": getattr(H.cu, "budget_tris", None),
                   "unculled_pass_ms": float(np.median(ref_ms)), "memory": H.prep["memory"]}
            rows.append(row)
            print(json.dumps(row), flush=True)
        H.release()
    Path(args.out).write_text(json.dumps(rows, indent=1))
    return 0


# ------------------------------------------------------------------------------------------------ stress scene
def tile_geometry(geom, K):
    """K logical copies of the geometry that share the same GPU buffers (the culler reads the position and index sections)."""
    from types import SimpleNamespace
    P0, G0 = len(geom.vbase), len(geom.pages)
    pages = []
    for k in range(K):
        for pg in geom.pages:
            pages.append(SimpleNamespace(index=len(pages), buffer=pg.buffer, offsets_words=pg.offsets_words,
                                         index_byte_offset=None if pg.compressed else pg.index_byte_offset, index_bytes=None if pg.compressed else pg.index_bytes, parts=[p + k * P0 for p in pg.parts],
                                         v0=pg.v0, v1=pg.v1, nverts=pg.nverts, nindices=pg.nindices,
                                         nlogical=pg.nlogical, compressed=pg.compressed, offs=pg.offs, counts=pg.counts))
    page_of = np.concatenate([np.where(geom.page_of >= 0, geom.page_of + k * G0, -1) for k in range(K)]).astype(np.int32)
    return SimpleNamespace(pages=pages, page_of=page_of, vbase=np.tile(geom.vbase, K), vcount=np.tile(geom.vcount, K),
                           ranges=list(geom.ranges) * K, page_bytes=geom.page_bytes, sink=geom.sink, cluster_ordered=True,
                           compressed=geom.compressed)


def tile_clusters(cd, K, P0, G0):
    import dataclasses
    R0, C0, T0 = cd.n_ranges, cd.n_clusters, cd.n_tris
    ks = range(K)
    cat = np.concatenate
    lr = cd.level_range
    return dataclasses.replace(
        cd,
        r_part=cat([cd.r_part + k * P0 for k in ks]).astype(cd.r_part.dtype),
        r_page=cat([cd.r_page + k * G0 for k in ks]).astype(cd.r_page.dtype),
        r_first=np.tile(cd.r_first, K), r_ntri=np.tile(cd.r_ntri, K),
        r_cfirst=cat([cd.r_cfirst + k * C0 for k in ks]), r_tfirst=cat([cd.r_tfirst + k * T0 for k in ks]),
        r_ccount=np.tile(cd.r_ccount, K),
        level_range=cat([np.where(lr >= 0, lr + k * R0, -1) for k in ks]).astype(lr.dtype),
        uncullable=np.tile(cd.uncullable, K),
        page_cfirst=cat([cat([cd.page_cfirst[:-1] + k * C0 for k in ks]), [K * C0]]).astype(cd.page_cfirst.dtype),
        cl_geom=np.tile(cd.cl_geom, (K, 1)),
        cl_range=cat([cd.cl_range + np.uint32(k * R0) for k in ks]).astype(cd.cl_range.dtype),
        perm=np.tile(cd.perm, K),
        cl_base=None if cd.cl_base is None else np.tile(cd.cl_base, K),
        r_level=None if cd.r_level is None else np.tile(cd.r_level, K),
        r_slot=None if cd.r_slot is None else np.tile(cd.r_slot, K))


def look_at(eye, target, up=(0.0, 1.0, 0.0)):
    eye, target, up = (np.asarray(v, dtype=np.float64) for v in (eye, target, up))
    f = target - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    M = np.eye(4)
    M[0, :3], M[1, :3], M[2, :3] = s, u, -f
    M[:3, 3] = -M[:3, :3] @ eye
    return M


def proj_gl(fov_deg, aspect, near, far):
    f = 1.0 / np.tan(np.radians(fov_deg) / 2)
    P = np.zeros((4, 4))
    P[0, 0], P[1, 1] = f / aspect, f
    P[2, 2], P[2, 3] = (far + near) / (near - far), 2 * far * near / (near - far)
    P[3, 2] = -1.0
    return P


class Stress:
    """Lattice of normalised copies of one model; one ClusterCuller over all of them."""

    def __init__(self, H, dims, pitch_gap=0.12, seed=1):
        import math
        from app.gpu.cull import ClusterCuller
        self.H, self.dims, self.pitch = H, tuple(dims), 1.0 + pitch_gap
        K = int(np.prod(dims))
        self.K = K
        P0, G0 = len(H.geom.vbase), len(H.geom.pages)
        self.P0 = P0
        cd0 = H.cu.cd
        self.base_tris, self.base_clusters = cd0.n_tris, cd0.n_clusters
        self.geom_bytes = 0
        for pg in H.geom.pages:
            self.geom_bytes += int(pg.buffer.size)
        pos = H.model.vertices[:, 0:3]
        lo, hi = pos.min(0).astype(np.float64), pos.max(0).astype(np.float64)
        s = 1.0 / float((hi - lo).max())
        cen = (lo + hi) * 0.5
        rng = np.random.default_rng(seed)
        nx, ny, nz = dims
        mats = []
        for cell, (iz, iy, ix) in enumerate(np.ndindex(nz, ny, nx)):
            kq = int(rng.integers(0, 4))
            ca, sa = math.cos(kq * math.pi / 2), math.sin(kq * math.pi / 2)
            A = s * np.array([[ca, 0, sa], [0, 1, 0], [-sa, 0, ca]])
            c = (np.array([ix, iy, iz]) - (np.array(dims) - 1) / 2.0) * self.pitch
            M = np.eye(4)
            M[:3, :3] = A
            M[:3, 3] = c - A @ cen
            mats.append(M)
        self.cell_mats = mats
        H.cu.release()
        H.geom = tile_geometry(H.geom, K)
        cd_t = tile_clusters(cd0, K, P0, G0)
        from app.gpu.geometry import TriangleOrder
        H.order = TriangleOrder(cd_t)
        kw = {} if H.budget is None else {"budget_tris": int(H.budget)}
        self.cu = ClusterCuller(H.gpu, H.geom, id_format=H.id_format, collect_stats=False, profile=True, **kw)
        self.prep = self.cu.prepare(H.model, clusters=cd_t, n_parts=K * P0)
        H.cu = self.cu
        H._ref_pipes()
        half = (np.array(dims) * self.pitch) / 2.0
        self.half, self.radius = half, float(np.linalg.norm(half))
        self.total_tris = K * self.base_tris

    def lod_levels(self, V, aspect, h):
        """LOD level of every part of every copy, chosen by the renderer's own code (WgpuRenderer._lod_levels, the `numbers` path).
        Copy k is the model scaled by s and moved by M_k, so its view is V @ M_k with the depth row divided by s: the renderer then
        compares model-unit pixel sizes with the model-unit cells and sphere radii, as for the model at scale 1."""
        R = self.H.R
        if R._spheres is None:
            R._refresh_transforms(self.H.model)
        t = np.tan(np.radians(55.0) / 2.0)
        halves = (t * aspect, t)
        index_of = {p.id: i for i, p in enumerate(self.H.model.parts)}
        lev = np.zeros(self.K * self.P0, dtype=np.int64)
        for k, M in enumerate(self.cell_mats):
            Vc = np.asarray(V, dtype=np.float64) @ M
            Vc[2] /= float(np.linalg.norm(M[:3, 0]))
            for pid, l in R._lod_levels(Vc, halves, False, h).items():
                lev[k * self.P0 + index_of[pid]] = l
        return lev

    def submitted_tris(self, fp):
        """Triangles of the frame's parts at their LOD levels (before any culling)."""
        cd = self.cu.cd
        lr = cd.level_range[np.asarray(fp.part), np.minimum(np.asarray(fp.level), cd.level_range.shape[1] - 1)]
        return int(cd.r_ntri[lr[lr >= 0]].sum())

    def frame(self, V=None, lod=False):
        from app.gpu.cull import FrameParts
        K, P0 = self.K, self.P0
        n = K * P0
        mats = np.repeat(np.array(self.cell_mats), P0, axis=0)
        level = self.lod_levels(V, self.H.size[0] / self.H.size[1], self.H.size[1]) if lod else np.zeros(n, dtype=np.int64)
        return FrameParts(part=np.arange(n, dtype=np.int64), level=level, matrix=mats,
                          noclip=np.zeros(n, dtype=bool), weight=np.zeros(n, dtype=np.float64),
                          slot0=np.zeros(n, dtype=np.uint32))

    def views(self):
        R = self.radius
        fov = 55.0
        d_far = R / np.sin(np.radians(fov) / 2) * 0.98
        dirn = np.array([0.55, 0.35, 0.76])
        dirn /= np.linalg.norm(dirn)
        j = np.zeros(3)
        for a in range(3):
            j[a] = (self.dims[a] // 2 - (self.dims[a] - 1) / 2.0 - 0.5) * self.pitch
        return {"outside": (dirn * d_far, np.zeros(3)), "near": (dirn * float(np.max(self.half)) * 1.35, np.zeros(3)),
                "inside": (j, j + np.array([1.0, 0.18, 0.55]))}

    def pose(self, name, step):
        eye, tgt = (np.array(v, dtype=np.float64) for v in self.views()[name])
        if name == "inside":
            d = tgt - eye
            a = np.radians(1.0 * step)
            c, s = np.cos(a), np.sin(a)
            d = np.array([c * d[0] + s * d[2], d[1], -s * d[0] + c * d[2]])
            return look_at(eye, eye + d)
        a = np.radians(0.6 * step)
        c, s = np.cos(a), np.sin(a)
        rel = eye - tgt
        rel = np.array([c * rel[0] + s * rel[2], rel[1], -s * rel[0] + c * rel[2]])
        return look_at(tgt + rel, tgt)


def run_stress(args):
    """Lattice of copies, one view at a time. --lod off: every copy at level 0 (culling alone); on: every copy at the level the renderer's
    LOD picks for it in that view (WgpuRenderer._lod_levels); both: both, rows carry a "lod" field."""
    from app.gpu.cull import ClipState
    H = Harness(args.models[0], args.adapter, size=args.size if args.size else (2560, 1600), profile=True, stats=False,
                budget=args.budget)
    period, _wall = H.vc.calibrate_period_ns(H.gpu)
    H.period_ns = period
    t0 = time.time()
    S = Stress(H, args.dims)
    w, h = H.size
    print(f"== stress {args.models[0]} x{S.K} dims={S.dims} tris={S.total_tris/1e6:.1f}M clusters={S.prep['clusters']} on {H.gpu.info} "
          f"{H.size} budget={getattr(S.cu, 'budget_tris', 'n/a')} build={time.time()-t0:.1f}s", flush=True)
    mem = S.prep["memory"]
    proj = proj_gl(55.0, w / h, 0.01, 50.0)
    clip = ClipState()
    rows = []
    lods = {"off": (False,), "on": (True,), "both": (False, True)}[args.lod]
    for lod in lods:
        for vname in args.views:
            cu = S.cu
            cu.reset()
            cu.collect_stats = False
            recs = []
            for k in range(args.frames):
                V = S.pose(vname, k)
                fp = S.frame(V, lod)
                do_cmp = bool(args.compare) and k in (0, 1, args.frames - 1)
                r = H.run_frame(None, None, compare=do_cmp, timing=True, frame=(fp, V, proj, False, clip))
                t = cu.read_timings(period)
                rec = {"k": k, "cull_ms": t["total_ms"], "stages": {a: round(b, 3) for a, b in t.items() if a != "total_ms"},
                       "ref_ms": r.get("ref_ms")}
                if do_cmp:
                    rec.update({a: r[a] for a in ("false_cull_samples", "false_cull_pixels", "nearer_samples", "tie_samples",
                                                  "stray_ids", "ref_fg_samples")})
                recs.append(rec)
            V = S.pose(vname, args.frames)
            fp = S.frame(V, lod)
            st_ms = []
            for i in range(4):
                cu.collect_stats = (i == 3)
                r = H.run_frame(None, None, compare=False, timing=True, frame=(fp, V, proj, False, clip))
                if i < 3:
                    st_ms.append(cu.read_timings(period)["total_ms"])
            stats = dict(r["stats"])
            cu.collect_stats = False
            row = {"view": vname, "lod": lod, "submitted_tris": S.submitted_tris(fp),
                   "cold_ms": recs[0]["cull_ms"], "cold_ref_ms": recs[0]["ref_ms"],
                   "moving_ms": float(np.median([x["cull_ms"] for x in recs[3:]])),
                   "static_ms": float(np.median(st_ms)), "ref_ms": float(np.median([x["ref_ms"] for x in recs[1:]])),
                   "stages_last": recs[-1]["stages"], "stats": stats, "checks": [x for x in recs if "false_cull_samples" in x]}
            rows.append(row)
            print(json.dumps(row), flush=True)
    out = {"adapter": H.gpu.info, "size": list(H.size), "dims": list(S.dims), "copies": S.K, "triangles": S.total_tris,
           "clusters": S.prep["clusters"], "memory": mem, "hzb_bytes": getattr(S.cu, "hzb_bytes", 0),
           "budget_tris": getattr(S.cu, "budget_tris", None),
           "geometry_bytes_all_streams_one_copy": S.geom_bytes, "geometry_bytes_per_tri": S.geom_bytes / S.base_tris,
           "capacity_blocks": sum(S.prep["capacity_blocks"]), "rows": rows}
    Path(args.out).write_text(json.dumps(out, indent=1))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("correct", "numbers", "stress"))
    ap.add_argument("--models", nargs="+", default=["pancreas", "eyeball"])
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--size", nargs=2, type=int, default=None)
    ap.add_argument("--page-mib", type=int, default=None)
    ap.add_argument("--orbit", type=int, default=6)
    ap.add_argument("--step", type=float, default=7.0)
    ap.add_argument("--frames", type=int, default=20)
    ap.add_argument("--lod", choices=("on", "off", "both"), default="both")
    ap.add_argument("--mutate", type=float, default=None, help="depth margin override (negative = deliberately wrong, must show false culls)")
    ap.add_argument("--dims", nargs=3, type=int, default=[2, 2, 2], help="stress: lattice of model copies")
    ap.add_argument("--views", nargs="+", default=["outside", "near", "inside"])
    ap.add_argument("--budget", type=int, default=None, help="compact index budget in triangles (default: ANATOMY_CULL_BUDGET / the culler's default; 0 = pulled draws only)")
    ap.add_argument("--compare", action="store_true", help="stress: compare culled and unculled ids on 3 frames per view")
    ap.add_argument("--out", default="cull_check.json")
    args = ap.parse_args()
    if args.mode == "correct" and args.size is None:
        args.size = [1280, 800]
    return {"correct": run_correct, "numbers": run_numbers, "stress": run_stress}[args.mode](args)


if __name__ == "__main__":
    sys.exit(main())
