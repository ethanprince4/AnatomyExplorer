"""Parity of the weighted blended OIT pass: GLSL (app/viewer/shaders.py OIT_FS through moderngl, the renderer's pass 5)
against app/gpu/oit.py + wgsl/oit.wgsl (wgpu), then through the composite on both sides.

    python tools/perf/gpu/oit_parity.py [--size 512] [--samples 4] [--adapter NVIDIA|Intel] [--cases a,b] [--json out.json]
                                        [--aniso 1] [--gl-literal]

Both sides get the same seeded triangle meshes (spheres, flat sheets, a mirrored sphere, a morphing sphere, a textured
alpha-tested sphere) and the same uniforms (produced by the renderer's own _light_uniforms / _set_look / _clip_uniforms on a
recorder, as in shade_parity.py).  GL: an opaque main pass (MAIN_FS) into MSAA colour + depth, then OIT_FS into
MSAA accum rgba16f + weight r16f (depth test "<", no depth write, blend ONE, ONE, ZERO, ONE_MINUS_SRC_ALPHA, clear
(0,0,0,1), all as renderer.py:823-837), resolved by copy_framebuffer.  wgpu: the opaque geometry is drawn depth-only through
the production vertex-pulling stage of oit.wgsl into a depth32float MSAA target; OitPass.encode draws the ghost parts from
a GpuGeometry built with geometry.build_geometry and resolves them (flipped into GL row order).  The opaque colour image
is GL's, uploaded to both composites (app/viewer COMPOSITE_FS in GL, PostPasses.run_composite in wgpu, no selection, id 0).

Reported: accum and weight (relative error, f16 values), the final 8-bit composite (1/255).  GL discards clipped
fragments BEFORE surface() in OIT_FS (undefined derivatives, see shading.wgsl item 17); like shade_parity.py the reference
moves the discard after it (--gl-literal restores the shipped shader).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import types
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import shade_parity as SP  # noqa: E402
from app.gpu import geometry as G, oit as O, post as P  # noqa: E402
from app.viewer import shaders  # noqa: E402
from app.viewer.environment import ROUGH_LAYERS  # noqa: E402
from app.viewer.model import NO_FIBRE  # noqa: E402
from app.viewer.renderer import ANIM_ATTRS, ANIM_FMT, ATTRS, FMT, _U  # noqa: E402

N_ITEMS = 10


# ---------------------------------------------------------------------------------------------------------------
# scene

def sheet(n, w, h, const_uv=False):
    u, v = np.meshgrid(np.linspace(-0.5, 0.5, n + 1), np.linspace(-0.5, 0.5, n + 1))
    pos = np.stack([u * w, v * h, np.zeros_like(u)], -1).reshape(-1, 3)
    nrm = np.tile(np.array([0.0, 0.0, 1.0]), (len(pos), 1))
    uv = np.stack([u + 0.5, v + 0.5], -1).reshape(-1, 2)
    if const_uv:
        uv = np.full_like(uv, 0.5)
    k = np.arange((n + 1) * (n + 1)).reshape(n + 1, n + 1)
    quad = np.stack([k[:-1, :-1], k[:-1, 1:], k[1:, 1:], k[1:, :-1]], -1).reshape(-1, 4)
    idx = np.concatenate([quad[:, [0, 1, 2]], quad[:, [0, 2, 3]]], 0)
    idx = SP._fix_winding(pos, nrm, idx)
    return SP.Mesh(pos, nrm, uv, idx)


def rot(axis, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    m = np.eye(4)
    i, j = {"x": (1, 2), "y": (2, 0), "z": (0, 1)}[axis]
    m[i, i], m[i, j], m[j, i], m[j, j] = c, -s, s, c
    return m


def T(x, y, z, s=1.0):
    return SP.translate(x, y, z, s, s, s)


def build_meshes(scale, seed):
    m = SP.build_meshes(scale, seed)
    m["sheet"] = sheet(int(36 * scale), 3.2, 2.2)
    m["sheetC"] = sheet(int(24 * scale), 3.0, 2.0, const_uv=True)          # every stream constant
    return m


# part spec: (mesh, matrix, look kwargs, extras); extras: oit (bool), ghost, alpha_mul, weight, batched, noclip, selected
def make_cases():
    M = T
    FAC = (0.10, 0.80, 1.5)
    return {
        "mix": dict(settings={"ao": False}, studio=0.30, ortho=False, parts=[
            ("sphA", M(-1.2, 0.4, 0.0), {"use_vcol": True}, {"noclip": True}),
            ("ribbon", M(0.0, -0.95, 0.3), {"rough": 0.7, "use_vcol": True}, {"noclip": True}),
            ("sphB", M(1.2, 0.5, 0.0), {"rough": 0.3, "f0": 0.05, "alpha": 0.45, "use_vcol": True},
             {"oit": True, "weight": 0.5}),
            ("sphA", M(0.1, 0.3, 0.5) @ SP.translate(0, 0, 0, 0.8, 0.8, 0.8), {"use_vcol": True},
             {"oit": True, "ghost": True}),
            ("sheet", M(-0.2, 0.3, 1.0) @ rot("y", 25), {"alpha": 0.30, "base": (0.9, 0.5, 0.4), "rough": 0.5},
             {"oit": True}),
            ("sheet", M(0.3, 0.1, 1.6) @ rot("x", -30), {"alpha": 1.0, "facing": FAC, "base": (0.4, 0.6, 0.9)},
             {"oit": True}),
            ("sheetC", M(-0.9, 0.5, 0.2) @ rot("y", 70), {"alpha": 0.25, "base": (0.5, 0.9, 0.5)}, {"oit": True}),
            ("mirror", SP.translate(0.2, -0.1, 1.0, -1.4, 1.4, 1.4), {"alpha": 0.6, "base": (0.7, 0.6, 0.4)},
             {"oit": True}),
            ("sphB", M(-0.2, -0.3, 0.9) @ SP.translate(0, 0, 0, 0.8, 0.8, 0.8),
             {"texture": True, "alpha": 0.7, "alpha_cut": 0.5, "rough": 0.4}, {"oit": True}),
            ("sphA", M(0.6, 0.9, 0.2) @ SP.translate(0, 0, 0, 0.5, 0.5, 0.5), {"alpha": 0.8, "use_vcol": True},
             {"oit": True, "alpha_mul": 0.5}),
        ]),
        # orthographic, two cutting planes, batched ghost / opacity items, a selected ghost, a part that is never cut
        "ortho_clip_batched": dict(
            settings={"ao": False, "light_scale": 0.9, "ghost_alpha": 0.4}, studio=0.6, ortho=True,
            clip=((0.0, 1.0, 0.0, 1.0), (-1.0, 0.3, 0.0, 1.2), (0.0, 0.0, 1.0, 0.9)), clip_on=(True, True, False),
            clip_mode=0, parts=[
            ("sphA", M(-1.2, 0.4, 0.0), {"use_vcol": True}, {"noclip": True}),
            ("sphB", M(1.2, 0.5, 0.0), {"alpha": 0.5, "use_vcol": True}, {"oit": True, "batched": True}),
            ("sheet", M(0.0, 0.2, 1.2) @ rot("y", 30), {"alpha": 0.5}, {"oit": True, "batched": True}),
            ("sheet", M(0.2, 0.0, 0.2) @ rot("x", 70), {"alpha": 0.4, "base": (0.8, 0.5, 0.9)},
             {"oit": True, "batched": True}),
            ("ribbon", M(0.0, -0.95, 0.3), {"alpha": 0.6, "use_vcol": True}, {"oit": True, "selected": True}),
            ("sphB", M(0.2, 0.9, 0.5) @ SP.translate(0, 0, 0, 0.7, 0.7, 0.7), {"use_vcol": True},
             {"oit": True, "ghost": True, "noclip": True}),
        ]),
    }


def item_table():
    """(3, N_ITEMS, 4) rgba32f: row 0 id+1, selected, highlight, x-ray; row 1 flat colour + on; row 2 highlight colour, opacity."""
    it = np.zeros((3, N_ITEMS, 4), np.float32)
    for i in range(N_ITEMS):
        it[0, i] = (i + 1, 0.0, 0.0 if i % 3 else 0.2, 1.0 if i % 2 == 1 else 0.0)
        it[1, i] = ((0.2 + 0.1 * i) % 1.0, 0.7 - 0.05 * i, 0.3 + 0.08 * i, 1.0 if i % 4 == 0 else 0.0)
        it[2, i] = (1.0 - 0.1 * i, 0.8, 0.45, 0.30 + 0.06 * i)
    return it


# ---------------------------------------------------------------------------------------------------------------
# GL

class OGL(SP.GL):
    def __init__(self, size, samples, literal=False):
        super().__init__(size, literal)
        fs = shaders.OIT_FS
        if not literal:
            a = "    if (clipped(v_wpos)) discard;\n    Surface s = surface();\n"
            assert a in fs
            fs = fs.replace(a, "    Surface s = surface();\n    if (clipped(v_wpos)) discard;\n")
        self.prog_oit = self.ctx.program(vertex_shader=shaders.GEOM_VS, fragment_shader=fs)
        self.u_oit = _U(self.prog_oit)
        self.samples = 0 if samples <= 1 else samples
        self.comp = self.ctx.program(vertex_shader=shaders.FSQ_VS, fragment_shader=shaders.COMPOSITE_FS)
        self.comp_vao = self.ctx.vertex_array(self.comp, [])

    def make_vaos(self, mesh, item):
        vbo, ibo, _, abo = self.mesh_vao(mesh)
        ivbo = self.ctx.buffer(np.full(len(mesh.pos), float(item), np.float32))
        return [self.ctx.vertex_array(p, [(vbo, FMT, *ATTRS), (ivbo, "1f", "in_item"), (abo, ANIM_FMT, *ANIM_ATTRS)],
                                      ibo, 4, skip_errors=True) for p in (self.prog, self.prog_oit)]

    def _replay(self, prog, u, vao, d):
        for k, v in d.items():
            if k == "u_sh":
                prog["u_sh"].write(np.ascontiguousarray(v, dtype=np.float32).tobytes())
            else:
                u(k, v)
        vao.render(self.mgl.TRIANGLES)

    def render(self, vaos, opaque, ghosts, items, tex):
        """opaque / ghosts: [(part index, uniform dict)].  Returns opaque (h,w,4), accum (h,w,4), weight (h,w,1) as
        float16 in GL row order, with the depth and blend setup of renderer.py:688-690, 705-837."""
        ctx, mgl, s = self.ctx, self.mgl, self.size
        sm = self.samples
        col = ctx.renderbuffer((s, s), 4, samples=sm, dtype="f2")
        dep = ctx.depth_renderbuffer((s, s), samples=sm)
        acc = ctx.renderbuffer((s, s), 4, samples=sm, dtype="f2")
        wgt = ctx.renderbuffer((s, s), 1, samples=sm, dtype="f2")
        f_main, f_oit = ctx.framebuffer([col], dep), ctx.framebuffer([acc, wgt], dep)
        t_op, t_ac, t_wg = (ctx.texture((s, s), c, dtype="f2") for c in (4, 4, 1))
        self.t_op, self.t_ac, self.t_wg = t_op, t_ac, t_wg
        ao_tex = ctx.texture((s, s), 4, np.zeros((s, s, 4), np.float16).tobytes(), dtype="f2")
        items_tex = ctx.texture((items.shape[1], items.shape[0]), 4, items.astype(np.float32).tobytes(), dtype="f4")
        items_tex.filter = (mgl.NEAREST, mgl.NEAREST)
        self.shadow.use(1), self.shadow.use(2), self.shadow.use(3)
        ao_tex.use(0)
        self.env.spec.use(4)
        self.white.use(5)
        tex.use(6)
        items_tex.use(11)
        ctx.viewport = (0, 0, s, s)
        ctx.disable(mgl.BLEND | mgl.CULL_FACE)
        ctx.enable(mgl.DEPTH_TEST)
        ctx.depth_func = "<"
        f_main.use()
        f_main.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        for pi, d in opaque:
            self._replay(self.prog, self.u, vaos[pi][0], d)
        if ghosts:
            f_oit.depth_mask = False
            f_oit.use()
            ctx.viewport = (0, 0, s, s)
            f_oit.clear(0.0, 0.0, 0.0, 1.0)
            ctx.enable(mgl.BLEND)
            ctx.blend_equation = mgl.FUNC_ADD
            ctx.blend_func = (mgl.ONE, mgl.ONE, mgl.ZERO, mgl.ONE_MINUS_SRC_ALPHA)
            for pi, d in ghosts:
                self._replay(self.prog_oit, self.u_oit, vaos[pi][1], d)
            ctx.disable(mgl.BLEND)
            f_oit.depth_mask = True
        for dst, src, t in ((t_op, col, 4), (t_ac, acc, 4), (t_wg, wgt, 1)):
            fd = ctx.framebuffer([dst])
            fs_ = ctx.framebuffer([src])
            ctx.copy_framebuffer(fd, fs_)
        out = [np.frombuffer(t.read(), np.float16).reshape(s, s, c).copy()
               for t, c in ((t_op, 4), (t_ac, 4), (t_wg, 1))]
        ao_tex.release()
        items_tex.release()
        return out

    def composite(self, uniforms):
        ctx, mgl, s = self.ctx, self.mgl, self.size
        idt = ctx.texture((s, s), 2, np.zeros((s, s, 2), np.float32).tobytes(), dtype="f4")
        idt.filter = (mgl.NEAREST, mgl.NEAREST)
        dst = ctx.texture((s, s), 4, dtype="f1")
        fbo = ctx.framebuffer([dst])
        fbo.use()
        ctx.viewport = (0, 0, s, s)
        ctx.disable(mgl.DEPTH_TEST | mgl.BLEND)
        for i, (n, t) in enumerate((("u_opaque", self.t_op), ("u_accum", self.t_ac), ("u_weight", self.t_wg),
                                    ("u_id", idt))):
            t.use(i)
            self.comp[n].value = i
        for k, v in uniforms.items():
            self.comp[k].value = v
        self.comp_vao.render(mgl.TRIANGLES, vertices=3)
        return np.frombuffer(fbo.read(components=4), np.uint8).reshape(s, s, 4).copy()


# ---------------------------------------------------------------------------------------------------------------
# wgpu

class OW:
    def __init__(self, size, samples, adapter_name=None, aniso=1, flip_y=True, depth_format="depth32float"):
        import wgpu
        self.wgpu = wgpu
        self.size, self.samples = size, samples
        ad = None
        for a in wgpu.gpu.enumerate_adapters_sync():
            if (adapter_name is None or adapter_name.lower() in a.summary.lower()) and a.info.get("backend_type") == "Vulkan":
                ad = a
                break
        if ad is None:
            raise RuntimeError(f"no wgpu Vulkan adapter {adapter_name!r}")
        self.summary = ad.summary
        feats = [f for f in ('texture-adapter-specific-format-features',) if f in ad.features]     # 8x on rgba16float
        self.dev = ad.request_device_sync(required_features=feats)
        self.up = types.SimpleNamespace(dev=self.dev, TU=wgpu.TextureUsage)
        self.flip_y = flip_y
        self.depth_format = depth_format
        self.pas = O.OitPass(self.dev, depth_format=depth_format, aniso=aniso, flip_y=flip_y)
        self.pp = P.PostPasses(self.dev)

    def build_geometry(self, parts):
        verts, idx, plist, vb, ib = [], [], [], 0, 0
        for k, p in enumerate(parts):
            blk = p.mesh.vertex_block()
            tri = p.mesh.idx.reshape(-1)
            verts.append(blk)
            idx.append(tri + np.uint32(vb))
            plist.append(types.SimpleNamespace(id=k + 1, name=f"p{k}", first=ib, count=len(tri), vertex_base=vb,
                                               vertex_count=len(blk), item=p.item, look=p.look, material_name="m"))
            vb += len(blk)
            ib += len(tri)
        model = types.SimpleNamespace(vertices=np.concatenate(verts), indices=np.concatenate(idx), parts=plist, lod=None)
        self.model = model
        self.geom = G.build_geometry(model, G.GpuSink(self.dev), G.page_limit(self.dev))
        self.pas.set_geometry(self.geom)

    def _depth_pipe(self):
        d = self.dev
        if getattr(self, "_dp", None) is None:
            empty = d.create_bind_group_layout(entries=[])
            self._dp = d.create_render_pipeline(
                layout=d.create_pipeline_layout(bind_group_layouts=[self.pas.bgl0, empty, self.pas.bgl2]),
                vertex={"module": self.pas.module, "entry_point": "vs_oit", "buffers": []},
                primitive={"topology": "triangle-list", "cull_mode": "none", "front_face": "ccw"},
                depth_stencil={"format": self.depth_format, "depth_write_enabled": True, "depth_compare": "less"},
                multisample={"count": self.samples})
            self._empty_bg = d.create_bind_group(layout=empty, entries=[])
        return self._dp

    def readback(self, tex, bpp):
        d = self.dev
        w, h = tex.size[0], tex.size[1]
        bpr = (w * bpp + 255) // 256 * 256
        buf = d.create_buffer(size=bpr * h, usage=self.wgpu.BufferUsage.COPY_DST | self.wgpu.BufferUsage.MAP_READ)
        enc = d.create_command_encoder()
        enc.copy_texture_to_buffer({"texture": tex}, {"buffer": buf, "bytes_per_row": bpr, "rows_per_image": h},
                                   (w, h, 1))
        d.queue.submit([enc.finish()])
        buf.map_sync(self.wgpu.MapMode.READ)
        raw = np.frombuffer(buf.read_mapped(), np.uint8).reshape(h, bpr)[:, :w * bpp].copy()
        buf.unmap()
        return raw

    def render(self, parts, opaque, ghosts, items, spec, levels, tex_has):
        d, wgpu, s = self.dev, self.wgpu, self.size
        TU, BU = wgpu.TextureUsage, wgpu.BufferUsage
        up = SP.WG._upload
        t_items = up(self.up, items.astype(np.float32), "rgba32float", (items.shape[1], items.shape[0]))
        t_spec = up(self.up, spec, "rgba16float", (SP.SPEC_W, SP.SPEC_H), layers=ROUGH_LAYERS)
        t_tex = up(self.up, None, "rgba8unorm-srgb", (levels[0].shape[1], levels[0].shape[0]), mips=levels)
        tex_view = t_tex.create_view()
        tg = self.pas.make_targets(s, s, self.samples)
        depth = d.create_texture(size=(s, s, 1), format=self.depth_format, sample_count=self.samples,
                                 usage=TU.RENDER_ATTACHMENT | TU.TEXTURE_BINDING)
        enc = d.create_command_encoder()
        # ---- opaque depth (the stand-in for the visibility pass): same vertex stage, no fragment stage
        odraws = [O.OitDraw(part=pi, first=self.model.parts[pi].first, count=self.model.parts[pi].count,
                            item=parts[pi].item, uniforms=u) for pi, u in opaque]
        rec = O.pack_draws(odraws, self.geom)
        b_draw = d.create_buffer_with_data(data=rec, usage=BU.STORAGE)
        b_fr = d.create_buffer_with_data(data=O.pack_frame(opaque[0][1]["u_viewproj"], (s, s), self.flip_y), usage=BU.UNIFORM)
        bg0 = d.create_bind_group(layout=self.pas.bgl0, entries=[
            {"binding": 0, "resource": {"buffer": b_fr, "offset": 0, "size": O.FRAME_BYTES}},
            {"binding": 1, "resource": {"buffer": b_draw, "offset": 0, "size": rec.nbytes}},
            {"binding": 2, "resource": {"buffer": self.pas._dummy, "offset": 0, "size": self.pas._dummy.size}}])
        rp = enc.begin_render_pass(color_attachments=[], depth_stencil_attachment={
            "view": depth.create_view(), "depth_clear_value": 1.0, "depth_load_op": "clear", "depth_store_op": "store"})
        rp.set_pipeline(self._depth_pipe())
        rp.set_bind_group(0, bg0)
        rp.set_bind_group(1, self._empty_bg)
        page = -1
        for k, dr in enumerate(odraws):
            pg = int(self.geom.page_of[dr.part])
            if pg != page:
                rp.set_bind_group(2, self.pas._page_bg[pg])
                pgo_ = self.geom.pages[pg]
                rp.set_index_buffer(pgo_.buffer, "uint32", pgo_.index_byte_offset, pgo_.index_bytes)
                page = pg
            rp.draw_indexed(dr.count, 1, dr.first, 0, k)
        rp.end()
        # ---- the module under test
        gdraws = [O.OitDraw(part=pi, first=self.model.parts[pi].first, count=self.model.parts[pi].count,
                            item=parts[pi].item, uniforms=u, texture=tex_view if u.get("u_has_tex", 0) == 1 else None)
                  for pi, u in ghosts]
        if gdraws:
            self.pas.encode(enc, gdraws, size=(s, s), samples=self.samples, depth_view=depth.create_view(),
                            targets=tg, items=t_items.create_view(), spec=t_spec.create_view(dimension="2d-array"))
        d.queue.submit([enc.finish()])
        acc = self.readback(tg["accum"], 8).view(np.float16).reshape(s, s, 4)
        wgt = self.readback(tg["weight"], 2).view(np.float16).reshape(s, s, 1)
        self.tg = tg
        return acc, wgt

    def composite(self, opaque16, uniforms_py):
        s = self.size
        op = P.make_texture(self.dev, s, s, "rgba16float", opaque16)
        idt = P.make_texture(self.dev, s, s, "rg32float", np.zeros((s, s, 2), np.float32))
        out = P.make_texture(self.dev, s, s, "rgba8unorm", extra_usage=self.wgpu.TextureUsage.RENDER_ATTACHMENT |
                             self.wgpu.TextureUsage.COPY_SRC)
        self.pp.run_composite(op, self.tg["accum"], self.tg["weight"], idt, out, **uniforms_py)
        return P.read_texture(self.dev, out, np.uint8, 4)


# ---------------------------------------------------------------------------------------------------------------
# metrics

def rel_stats(a, b, active):
    a, b = a.astype(np.float32), b.astype(np.float32)
    d = np.abs(a - b)
    sc = np.maximum(np.abs(a), np.abs(b))
    rel = np.where(sc > 0, d / np.maximum(sc, 1e-30), 0.0).max(-1)
    m = active
    if not m.any():
        return {"n": 0}
    return {"n": int(m.sum()), "max_rel": float(rel[m].max()), "mean_rel": float(rel[m].mean()),
            "n_rel_gt_1pct": int((rel[m] > 0.01).sum()), "max_abs": float(d[m].max())}


def composite_stats(g, w, edge_mask, active):
    err = np.abs(g[..., :3].astype(np.int32) - w[..., :3].astype(np.int32)).max(-1).astype(np.float32)
    res = {"max": float(err.max()), "mean": float(err.mean()), "pct_gt_1": float(100 * (err > 1).mean()),
           "n_gt_2": int((err > 2).sum())}
    if active.any():
        res["mean_active"] = float(err[active].mean())
        res["max_active"] = float(err[active].max())
        ia = active & ~edge_mask
        res["max_interior"] = float(err[ia].max()) if ia.any() else float("nan")
        res["mean_interior"] = float(err[ia].mean()) if ia.any() else float("nan")
        res["max_edge"] = float(err[active & edge_mask].max()) if (active & edge_mask).any() else float("nan")
        res["n_active"] = int(active.sum())
        res["n_edge"] = int((active & edge_mask).sum())
    return res


def edge_of(weight):
    cov = weight[..., 0] > 0
    e = np.zeros_like(cov)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            e |= np.roll(np.roll(cov, dy, 0), dx, 1) != cov
    return e


def run(size=512, samples=4, adapter=None, case_names=None, scale=1.0, seed=7, aniso=1, gl_literal=False, flip_y=True, depth_format="depth32float"):
    cases = make_cases()
    names = case_names or list(cases)
    wg = OW(size, samples, adapter, aniso, flip_y, depth_format)               # first: adapter enumeration touches the WGL current context
    gl = OGL(size, samples, gl_literal)
    rng = np.random.default_rng(seed)
    meshes = build_meshes(scale, seed)
    tex8 = SP.make_texture(rng)
    gl_tex, levels = gl.texture_chain(tex8)
    gl_tex.anisotropy = float(aniso)
    gl_tex.repeat_x = gl_tex.repeat_y = True
    items = item_table()
    out = {"gl": gl.info, "wgpu": wg.summary, "size": size, "samples": samples, "aniso": aniso, "cases": []}
    for name in names:
        case = cases[name]
        sh, spec = gl.set_env(case["studio"])
        parts = []
        for k, (mname, matrix, look_kw, extra) in enumerate(case["parts"]):
            ex = dict(extra)
            oit, ghost, amul = ex.pop("oit", False), ex.pop("ghost", False), ex.pop("alpha_mul", 1.0)
            p = SP.Part(meshes[mname], matrix, SP.make_look(look_kw, 0), k % N_ITEMS, **ex)
            p.oit, p.ghost, p.alpha_mul = oit, ghost, amul
            parts.append(p)
        frame = SP.case_uniforms(case, parts, size)
        st = frame["settings"]
        env_stub = types.SimpleNamespace(sh=sh, spec=types.SimpleNamespace(layers=ROUGH_LAYERS, use=lambda *a: None),
                                         use=lambda *a: None)
        draws = []
        for i, p in enumerate(parts):
            d = SP.part_uniforms(frame, p, env_stub, None)
            if p.oit:
                d["u_ghost_alpha"] = float(st.ghost_alpha)
                if not p.batched:
                    d["u_ghost"] = 1 if p.ghost else 0
                    d["u_alpha_mul"] = float(p.alpha_mul)
            draws.append((i, d))
        opaque = [(i, d) for i, d in draws if not parts[i].oit]
        ghosts = [(i, d) for i, d in draws if parts[i].oit]
        vaos = [gl.make_vaos(p.mesh, p.item) for p in parts]
        wg.build_geometry(parts)
        op16, ac_g, wg_g = gl.render(vaos, opaque, ghosts, items, gl_tex)
        ac_w, wg_w = wg.render(parts, opaque, ghosts, items, spec, levels, None)
        # composite (renderer.py:858-867 with no selection, id 0)
        cu = dict(u_oit_on=1, u_has_sel=0, u_hover=0.0, u_outline=tuple(st.outline), u_hover_outline=tuple(st.hover_outline),
                  u_exposure=float(st.exposure), u_tonemap=1 if st.tonemap else 0, u_texel=(1.0 / size, 1.0 / size),
                  u_outline_px=float(max(1.5, size / 540.0)))
        cg = gl.composite(cu)
        cw = wg.composite(op16, dict(oit_on=True, has_sel=False, hover=0.0, outline=st.outline,
                                     hover_outline=st.hover_outline, exposure=st.exposure, tonemap=bool(st.tonemap)))
        active = (wg_g[..., 0] > 0) | (wg_w[..., 0] > 0)
        edge = edge_of(wg_g) | edge_of(wg_w)
        res = {"case": name, "ghost_parts": len(ghosts), "tris": int(sum(p.mesh.tris for p in parts)),
               "accum": rel_stats(ac_g, ac_w, active), "weight": rel_stats(wg_g, wg_w, active),
               "composite": composite_stats(cg, cw, edge, active), "active_px": int(active.sum()),
               "weight_only_gl": int(((wg_g[..., 0] > 0) & ~(wg_w[..., 0] > 0)).sum()),
               "weight_only_wgpu": int(((wg_w[..., 0] > 0) & ~(wg_g[..., 0] > 0)).sum())}
        out["cases"].append(res)
        LAST[name] = dict(op=op16, ac_g=ac_g, ac_w=ac_w, wg_g=wg_g, wg_w=wg_w, cg=cg, cw=cw)
    return out


LAST = {}


def print_table(out):
    print(f"GL: {out['gl']} | wgpu: {out['wgpu']} | {out['size']}px x{out['samples']} | aniso {out['aniso']}")
    print(f"{'case':20s} {'ghost':>5s} {'active':>7s} | {'acc relmax':>10s} {'mean':>9s} | {'wgt relmax':>10s} {'mean':>9s} "
          f"| {'comp max':>8s} {'mean':>8s} {'meanAct':>8s} {'maxInt':>7s} {'maxEdge':>7s} {'n>2':>6s}")
    for r in out["cases"]:
        a, w, c = r["accum"], r["weight"], r["composite"]
        print(f"{r['case']:20s} {r['ghost_parts']:5d} {r['active_px']:7d} | {a['max_rel']:10.2e} {a['mean_rel']:9.2e} | "
              f"{w['max_rel']:10.2e} {w['mean_rel']:9.2e} | {c['max']:8.1f} {c['mean']:8.4f} {c.get('mean_active', 0):8.3f} "
              f"{c.get('max_interior', 0):7.1f} {c.get('max_edge', 0):7.1f} {c['n_gt_2']:6d}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--samples", type=int, default=4)
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--cases", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--aniso", type=int, default=1)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--gl-literal", action="store_true")
    ap.add_argument("--depth-format", default="depth32float", help="depth32float | depth24plus (GL's renderbuffer is 24 bit)")
    ap.add_argument("--top-first", action="store_true", help="rasterise top-first (OitPass(flip_y=False); the depth pass is top-first too; shows the MSAA sample-pattern mirror)")
    a = ap.parse_args(argv)
    out = run(a.size, a.samples, a.adapter, a.cases.split(",") if a.cases else None, a.scale, aniso=a.aniso,
              gl_literal=a.gl_literal, flip_y=not a.top_first, depth_format=a.depth_format)
    print_table(out)
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main()
