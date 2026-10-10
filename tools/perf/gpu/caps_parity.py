"""Parity of the model viewer's cut caps: the GL chain (prepass, parity, cap, capmix_pre, capmix of the unmodified GL
`Renderer`, standalone moderngl context) against app/gpu/caps.py (wgpu) with identical inputs.

    python tools/perf/gpu/caps_parity.py [--size 256x192] [--adapter NVIDIA|Intel] [--cases a,b] [--json out.json]

Inputs: one synthetic scene (`build_scene` below: nested spheres and boxes as separate items, an item of two parts,
a mirrored part with negative determinant, an item that is never cut, vertex-colour / stripe / mottle / tissue looks), cut by
1-3 planes in both clip modes and in an orthographic view.  The GL renderer draws the frame; wrappers capture what it feeds the
cap passes: the draw list, the uniforms of every cap draw (`_U` tee: identical look / clip / light uniforms, also compared with
what caps.plan() builds), the pre-pass id / nd / depth BEFORE the cut faces are laid in.  The wgpu side gets exactly those
pre-pass textures and the real compact geometry (geometry.build_geometry), then runs gather, lay-in, colour and mix.

Compared (all in GL row order): the cap targets (zp, albedo, normal, id, key), the id / nd textures after the lay-in, the
cap colour against GL's resolved forward colour (`t["opaque"]`) after the same tone mapping as the composite (1/255 units),
the depth after the cap mix.  Pixels where only one side has a cap are counted separately (rim pixels of the cut).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.viewer.model import Item, Look, NO_FIBRE, Part, ViewerModel  # noqa: E402
from tools.perf.gpu.shade_parity import MOTTLE, STRIPE, Mesh, translate, uv_sphere  # noqa: E402


# ---------------------------------------------------------------------------------------------------------------
# synthetic scene: closed meshes as separate items (nested spheres and boxes, a two-part item, a mirrored part with negative
# determinant, an item that is never cut, vertex-colour / stripe / mottle / tissue looks); a real ViewerModel for both renderers

def box_mesh(hx, hy, hz, rng=None):
    """Closed box, 24 vertices (flat normals), outward counter-clockwise triangles, constant vertex colour."""
    faces = [((1, 0, 0), (0, 1, 0), (0, 0, 1)), ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
             ((0, 1, 0), (0, 0, 1), (1, 0, 0)), ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
             ((0, 0, 1), (1, 0, 0), (0, 1, 0)), ((0, 0, -1), (0, 1, 0), (1, 0, 0))]
    h = np.array([hx, hy, hz], float)
    pos, nrm, uv, idx = [], [], [], []
    for n, a, b in faces:
        n, a, b = (np.array(v, float) for v in (n, a, b))
        base = len(pos)
        for sa, sb in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            pos.append((n + a * sa + b * sb) * h)
            nrm.append(n)
            uv.append(((sa + 1) / 2, (sb + 1) / 2))
        # (a x b) must point along n for counter-clockwise outward winding; flip when it does not
        tri = [(0, 1, 2), (0, 2, 3)] if np.dot(np.cross(a, b), n) > 0 else [(0, 2, 1), (0, 3, 2)]
        idx += [[base + i for i in t] for t in tri]
    return Mesh(np.array(pos), np.array(nrm), np.array(uv), np.array(idx, dtype=np.uint32), rng=rng)


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[0, 0], m[0, 2], m[2, 0], m[2, 2] = c, s, -s, c
    return m


class SynthModel(ViewerModel):
    """specs: list of dicts {mesh, matrix, look, item} (several parts may share an item); items: list of dicts
    {name, clip}."""

    kind = "synthetic"

    def __init__(self, specs, items):
        super().__init__()
        verts, inds = [], []
        self.node_world = [np.eye(4)]
        for k, sp in enumerate(specs):
            mesh = sp["mesh"]
            self.node_world.append(np.asarray(sp["matrix"], dtype=np.float64))
            part = Part(id=k + 1, node=k + 1, name=f"part{k}", mesh_name=f"mesh{k}", material_name=f"mat{k}",
                        structure="s", structure_id="s", label="", extras={}, look=sp["look"], item=sp["item"])
            blk = mesh.vertex_block()
            self._add_part(part, mesh.pos, mesh.nrm, mesh.idx, verts, inds, extra=lambda v, b=blk: v.__setitem__(slice(None), b))
        for i, it in enumerate(items):
            self.items.append(Item(index=i, key=it["name"], name=it["name"], group="g", clip=it.get("clip", True)))
        for p in self.parts:
            self.items[p.item].parts.append(p)
        self._build_groups()
        self._finish(verts, inds)
        self.look_defaults = {}


def build_scene(scale=1.0, seed=11):
    """The default test scene.  Items: 0 outer sphere, 1 inner sphere (tissue look), 2 box (stripes), 3 two small
    spheres (one item, two parts, vertex colours), 4 mirrored sphere (negative determinant, mottled), 5 never cut."""
    rng = np.random.default_rng(seed)
    n = lambda k: max(int(k * scale), 6)
    outer = uv_sphere(n(56), n(28), 1.0, rng, morph=False, no_fib=True)
    inner = uv_sphere(n(40), n(20), 0.62, rng, morph=False, no_fib=True)
    small = uv_sphere(n(24), n(12), 0.22, rng, morph=False, no_fib=True)
    mirr = uv_sphere(n(36), n(18), 0.5, rng, morph=False, no_fib=True)
    free = uv_sphere(n(28), n(14), 0.3, rng, morph=False, no_fib=True)
    for m in (outer, inner, mirr, free):
        m.col[:] = 1.0                                             # constant vertex colour (the "constant stream" path)
    box = box_mesh(0.30, 0.22, 0.26, rng)
    plain = Look(base=(0.75, 0.30, 0.25), rough=0.45, f0=0.04)
    tissue = Look(base=(0.80, 0.55, 0.45), rough=0.6, sss=0.3, detail=(0.35, 6.0, 0.4, 4))
    striped = Look(base=(0.60, 0.35, 0.30), rough=0.5, stripe=dict(STRIPE))
    vcol = Look(base=(0.9, 0.9, 0.9), rough=0.5, use_vcol=True)
    mott = Look(base=(0.5, 0.5, 0.5), rough=0.55, metal=0.0, mottle=dict(MOTTLE))
    shiny = Look(base=(0.30, 0.55, 0.70), rough=0.25, metal=0.6, f0=0.08)
    specs = [
        dict(mesh=outer, matrix=translate(0.0, 0.0, 0.0), look=plain, item=0),
        dict(mesh=inner, matrix=translate(0.05, 0.0, 0.0), look=tissue, item=1),
        dict(mesh=box, matrix=translate(0.0, 0.0, 0.0) @ rot_y(0.5), look=striped, item=2),
        dict(mesh=small, matrix=translate(0.62, 0.15, 0.0), look=vcol, item=3),
        dict(mesh=small, matrix=translate(-0.55, -0.1, 0.2), look=vcol, item=3),
        dict(mesh=mirr, matrix=translate(0.0, 0.0, 1.45, -1.0, 1.0, 1.0), look=mott, item=4),
        dict(mesh=free, matrix=translate(0.0, 0.35, -1.5), look=shiny, item=5),
    ]
    items = [dict(name=f"item{i}") for i in range(5)] + [dict(name="never-cut", clip=False)]
    return SynthModel(specs, items)


# ---------------------------------------------------------------------------------------------------------------
# cases

def _planes(*rows):
    out = [list(r) for r in rows] + [[0.0, 1.0, 0.0, 0.0]] * (3 - len(rows))
    return tuple(tuple(map(float, r)) for r in out)


CASES = {
    # name: planes, on, mode, camera yaw/pitch, ortho, selected, hovered
    "m0_1plane": dict(planes=_planes((-1, 0, 0, 0.1)), on=(1, 0, 0), mode=0, yaw=0.4, pitch=0.3),
    "m0_2planes": dict(planes=_planes((-1, 0, 0, 0.15), (0, -1, 0, 0.25)), on=(1, 1, 0), mode=0, yaw=0.5, pitch=0.45),
    "m0_3planes": dict(planes=_planes((-1, 0, 0, 0.2), (0, -1, 0, 0.3), (0, 0, -1, 0.15)), on=(1, 1, 1), mode=0,
                       yaw=0.6, pitch=0.5),
    "m1_2planes": dict(planes=_planes((-1, 0, 0, 0.1), (0, -1, 0, 0.2)), on=(1, 1, 0), mode=1, yaw=0.55, pitch=0.5),
    "m1_3planes": dict(planes=_planes((-1, 0, 0, 0.1), (0, -1, 0, 0.2), (0, 0, -1, 0.1)), on=(1, 1, 1), mode=1,
                       yaw=0.6, pitch=0.55),
    "ortho_1plane": dict(planes=_planes((-1, 0, 0, 0.05)), on=(1, 0, 0), mode=0, yaw=0.35, pitch=0.25, ortho=True),
    "tilted_sel_hover": dict(planes=_planes((-0.8, 0.5, -0.3, 0.1)), on=(1, 0, 0), mode=0, yaw=0.5, pitch=0.2,
                             selected=(1, 4), hovered=2),
}


# ---------------------------------------------------------------------------------------------------------------
# helpers

class Tee:
    """Stands in for a `_U` of the GL renderer: records every uniform set (a new record starts at u_model) and forwards."""

    def __init__(self, real):
        self.real, self.glob, self.parts, self.cur = real, {}, [], None
        self.prog = types.SimpleNamespace(get=self._get)

    def _get(self, name, default=None):
        member = self.real.prog.get(name, default)
        if member is None or name != "u_sh":
            return member

        def write(b):
            self._set("u_sh", np.frombuffer(b, np.float32).reshape(9, 3).copy())
            member.write(b)
        return types.SimpleNamespace(write=write)

    def _set(self, name, value):
        if name == "u_model":
            self.cur = dict(self.glob)
            self.parts.append(self.cur)
        (self.cur if self.cur is not None else self.glob)[name] = value.copy() if hasattr(value, "copy") else value

    def __call__(self, name, value):
        self._set(name, value)
        self.real(name, value)


def known_uniforms(d):
    from app.gpu.shading_uniforms import FIELD_BY_NAME, IGNORED
    return {k: v for k, v in d.items() if k in FIELD_BY_NAME or k in IGNORED}


def make_camera(model, w, h, yaw, pitch, ortho=False):
    from app.viewer.camera import OrbitCamera
    cam = OrbitCamera()
    cam.set_scene(model.bounds_min, model.bounds_max)
    cam.target = cam.scene_centre.copy()
    cam.distance = cam.fit_distance(cam.scene_radius, w / h)
    cam.yaw, cam.pitch = yaw, pitch
    if ortho:
        cam.ortho = True
    cam.snap()
    return cam


def tone(img):
    from tools.perf.gpu.shade_parity import tone_map
    return tone_map(np.asarray(img, np.float32)[..., :3]) * 255.0


# ---------------------------------------------------------------------------------------------------------------
# GL side

class GLSide:
    def __init__(self, model, size):
        import moderngl
        from app.viewer.renderer import Renderer
        self.mgl = moderngl
        self.size = size
        self.ctx = moderngl.create_standalone_context(require=410)
        self.info = self.ctx.info["GL_RENDERER"]
        self.model = model
        self.r = Renderer(self.ctx)
        self.r.set_model(model)
        self.col = self.ctx.texture(size, 4)
        self.fbo = self.ctx.framebuffer([self.col])
        self._dtex = self.ctx.depth_texture(size)
        self._dcol = self.ctx.texture(size, 4, dtype="f2")
        self._dfbo = self.ctx.framebuffer([self._dcol], self._dtex)
        self._stex = self.ctx.texture(size, 4, dtype="f2")
        self._sfbo = self.ctx.framebuffer([self._stex], self.ctx.depth_renderbuffer(size))

    def main_depth(self):
        """GL window depth of the main pass (blit of the frame's depth_ms resolved to a single-sample texture)."""
        self.ctx.copy_framebuffer(self._dfbo, self.r.t["fbo_main"])
        self.r.t["fbo_main"].use()
        w, h = self.size
        return np.frombuffer(self._dtex.read(), np.float32).reshape(h, w).copy()

    def main_colour(self):
        w, h = self.size
        return np.frombuffer(self._dcol.read(), np.float16).reshape(h, w, 4).astype(np.float32)

    def run(self, case, msaa):
        from app.viewer.renderer import FrameState, Settings
        r, t = self.r, None
        w, h = self.size
        cam = make_camera(self.model, w, h, case["yaw"], case["pitch"], case.get("ortho", False))
        fs = FrameState(clip_planes=case["planes"], clip_on=tuple(bool(x) for x in case["on"]), clip_mode=case["mode"],
                        selected=frozenset(case.get("selected", ())), hovered=case.get("hovered", -1))
        s = Settings(msaa=msaa, ao=False, shadows=False)
        cap = {}
        tee_cap, tee_mix = Tee(r.u[r.p_cap]), Tee(r.u[r.p_capmix])
        real = (r.u[r.p_cap], r.u[r.p_capmix])
        r.u[r.p_cap], r.u[r.p_capmix] = tee_cap, tee_mix
        orig = r._render_caps

        def render_caps(draws, VP, V, campos, camera, clip, fs_, size):
            t = r.t
            cap["draws"], cap["VP"], cap["V"], cap["clip"] = list(draws), VP.copy(), V.copy(), clip
            cap["pre_id"] = self._tex(t["id"], 2)
            cap["pre_nd"] = self._tex(t["nd"], 4)
            cap["pre_depth"] = self._depth(t["fbo_pre"])
            return orig(draws, VP, V, campos, camera, clip, fs_, size)

        orig_mix = r._capmix

        def capmix(*a, **k):
            cap["depth_before_mix"] = self.main_depth()
            cap["main_colour"] = self.main_colour()
            res = orig_mix(*a, **k)
            cap["depth_after_mix"] = self.main_depth()
            # the same draw into a cleared single-sample target: the cut-face colour without the depth competition
            self._sfbo.use()
            self._sfbo.clear(0.0, 0.0, 0.0, 1.0, depth=1.0)
            orig_mix(*a, **k)
            w, h = self.size
            cap["capmix_alone"] = np.frombuffer(self._stex.read(), np.float16).reshape(h, w, 4).astype(np.float32)
            r.t["fbo_main"].use()
            return res

        r._render_caps = render_caps
        r._capmix = capmix
        try:
            r.render(self.fbo, (w, h), cam, s, fs)
        finally:
            r._render_caps = orig
            r._capmix = orig_mix
            r.u[r.p_cap], r.u[r.p_capmix] = real
        t = r.t
        out = dict(cap)
        out.update(cam=cam, fs=fs, s=s, tee_cap=tee_cap, tee_mix=tee_mix, ok=bool(r.frame_ok))
        out["albedo"] = self._tex(t["cap_albedo"], 4, "f2")
        out["normal"] = self._tex(t["cap_normal"], 4, "f2")
        out["id_cap"] = self._tex(t["cap_id"], 2)
        out["zp"] = self._tex(t["cap_zp"], 1)
        out["key"] = self._depth(t["fbo_cap"])
        out["id"] = self._tex(t["id"], 2)
        out["nd"] = self._tex(t["nd"], 4)
        out["opaque"] = self._tex(t["opaque"], 4, "f2")
        out["depth_main"] = out.get("depth_after_mix")
        out["env_sh"] = np.asarray(r.env.sh, np.float32).copy()
        out["env_spec"] = np.frombuffer(r.env.spec.read(), np.float16).reshape(r.env.spec.layers, -1, r.env.spec.width, 4)
        out["model_diag"] = r.model_diag
        return out

    def _tex(self, tex, comps, dt="f4"):
        w, h = self.size
        a = np.frombuffer(tex.read(), np.float16 if dt == "f2" else np.float32)
        return a.reshape(h, w, comps).astype(np.float32).copy()[..., 0] if comps == 1 else \
            a.reshape(h, w, comps).astype(np.float32).copy()

    def _depth(self, fbo):
        w, h = self.size
        return np.frombuffer(fbo.read(attachment=-1, components=1, dtype="f4"), np.float32).reshape(h, w).copy()


# ---------------------------------------------------------------------------------------------------------------
# wgpu side

_FILL_WGSL = """
@group(0) @binding(0) var src: texture_2d<f32>;
@vertex fn vs(@builtin(vertex_index) vi: u32) -> @builtin(position) vec4<f32> {
    let p = vec2<f32>(f32((vi << 1u) & 2u), f32(vi & 2u));
    return vec4<f32>(p * 2.0 - 1.0, 0.0, 1.0);
}
struct O { @builtin(frag_depth) d: f32 };
@fragment fn fs(@builtin(position) pos: vec4<f32>) -> O {
    var o: O;
    o.d = textureLoad(src, vec2<i32>(i32(pos.x), i32(pos.y)), 0).x;
    return o;
}
"""


class WGSide:
    def __init__(self, gpu, model, size, page_bytes=None, order=None, compress=None):
        import wgpu
        from app.gpu import geometry as geo
        from app.gpu.caps import CapPasses
        self.wgpu, self.gpu = wgpu, gpu
        self.dev, self.q = gpu.device, gpu.queue
        self.TU, self.BU = wgpu.TextureUsage, wgpu.BufferUsage
        self.size = size
        self.model = model
        import os
        cmp = {"1": 1, "2": 2}.get(os.environ.get("ANATOMY_CAPSP_COMPRESS", "0"), 0) if compress is None else int(compress)   # compressed (1) / quantised (2) + cluster-ordered pages: caps draws pull (non-indexed)
        order = bool(cmp) or (os.environ.get("ANATOMY_CAPSP_ORDER", "0") == "1" if order is None else bool(order))   # cluster-ordered pages: cut parts get cluster masks
        self.geom = geo.build_geometry(model, geo.GpuSink(self.dev), page_bytes or geo.page_limit(self.dev),
                                       cluster_order=order, compress=cmp)
        if cmp:
            assert self.geom.compressed, "compression refused for the synthetic model"
        self.caps = CapPasses(self.dev, getattr(gpu, "limits", None))
        self._fill = None
        self._shade_res = None

    # ---- texture io
    def upload(self, arr, fmt, usage, samples=1):
        h, w = arr.shape[:2]
        c = arr.shape[2] if arr.ndim == 3 else 1
        t = self.dev.create_texture(size=(w, h, 1), format=fmt, usage=usage | self.TU.COPY_DST | self.TU.COPY_SRC,
                                    sample_count=samples)
        a = np.ascontiguousarray(arr)
        self.q.write_texture({"texture": t, "mip_level": 0, "origin": (0, 0, 0)}, a,
                             {"offset": 0, "bytes_per_row": w * c * a.dtype.itemsize, "rows_per_image": h}, (w, h, 1))
        return t

    def read(self, tex, dtype, comps):
        w, h = tex.size[:2]
        bpp = comps * np.dtype(dtype).itemsize
        bpr = (w * bpp + 255) // 256 * 256
        buf = self.dev.create_buffer(size=bpr * h, usage=self.BU.COPY_DST | self.BU.MAP_READ)
        enc = self.dev.create_command_encoder()
        enc.copy_texture_to_buffer({"texture": tex}, {"buffer": buf, "bytes_per_row": bpr, "rows_per_image": h}, (w, h, 1))
        self.q.submit([enc.finish()])
        buf.map_sync(self.wgpu.MapMode.READ)
        raw = np.frombuffer(buf.read_mapped(), np.uint8).copy()
        buf.unmap()
        buf.destroy()
        a = raw.reshape(h, bpr)[:, :w * bpp].copy().view(dtype).reshape(h, w, comps)
        return a.astype(np.float32)

    def shade_group(self, gl):
        """Bind group over caps.shade_layout from the GL renderer's own environment and the captured frame uniforms."""
        from app.gpu.shading_uniforms import pack_shading_uniforms
        wgpu, dev = self.wgpu, self.dev
        TB = self.TU.TEXTURE_BINDING
        spec = gl["env_spec"]
        layers, sh_, sw_, _c = spec.shape
        d = dict(known_uniforms(gl["tee_mix"].glob))
        d["u_sh"] = gl["env_sh"]
        buf = dev.create_buffer_with_data(data=pack_shading_uniforms(d), usage=self.BU.UNIFORM)
        t_spec = dev.create_texture(size=(sw_, sh_, layers), format="rgba16float", usage=TB | self.TU.COPY_DST)
        self.q.write_texture({"texture": t_spec, "mip_level": 0, "origin": (0, 0, 0)}, np.ascontiguousarray(spec),
                             {"offset": 0, "bytes_per_row": sw_ * 8, "rows_per_image": sh_}, (sw_, sh_, layers))
        t_items = self.upload(np.zeros((3, 8, 4), np.float32), "rgba32float", TB)
        t_ao = self.upload(np.ones((1, 1, 4), np.float16), "rgba16float", TB)
        t_tex = self.upload(np.full((1, 1, 4), 255, np.uint8), "rgba8unorm-srgb", TB)
        s_ao = dev.create_sampler(address_mode_u="clamp-to-edge", address_mode_v="clamp-to-edge", mag_filter="linear",
                                  min_filter="linear")
        s_env = dev.create_sampler(address_mode_u="repeat", address_mode_v="clamp-to-edge", mag_filter="linear",
                                   min_filter="linear")
        s_tex = dev.create_sampler(address_mode_u="repeat", address_mode_v="repeat", mag_filter="linear",
                                   min_filter="linear", mipmap_filter="linear")
        self._keep = [buf, t_spec, t_items, t_ao, t_tex]
        return self.caps.shade_bind_group(buf, t_items.create_view(), t_ao.create_view(),
                                          t_spec.create_view(dimension="2d-array"), t_tex.create_view(), s_ao, s_env, s_tex)

    def depth_from(self, depth_gl_order, samples):
        """depth32float (top row first, `samples` samples, every sample equal) filled with a GL-order depth image."""
        wgpu, dev = self.wgpu, self.dev
        w, h = self.size
        if self._fill is None:
            m = dev.create_shader_module(code=_FILL_WGSL)
            self._fill_bgl = dev.create_bind_group_layout(entries=[{
                "binding": 0, "visibility": wgpu.ShaderStage.FRAGMENT,
                "texture": {"sample_type": "unfilterable-float", "view_dimension": "2d"}}])
            self._fill_m = m
            self._fill = {}
        if samples not in self._fill:
            self._fill[samples] = dev.create_render_pipeline(
                layout=dev.create_pipeline_layout(bind_group_layouts=[self._fill_bgl]),
                vertex={"module": self._fill_m, "entry_point": "vs"}, primitive={"topology": "triangle-list"},
                fragment={"module": self._fill_m, "entry_point": "fs", "targets": []},
                depth_stencil={"format": "depth32float", "depth_write_enabled": True, "depth_compare": "always"},
                multisample={"count": samples})
        src = self.upload(np.ascontiguousarray(depth_gl_order[::-1]), "r32float", self.TU.TEXTURE_BINDING)
        dep = dev.create_texture(size=(w, h, 1), format="depth32float", sample_count=samples,
                                 usage=self.TU.RENDER_ATTACHMENT | self.TU.COPY_SRC | self.TU.TEXTURE_BINDING)
        bg = dev.create_bind_group(layout=self._fill_bgl, entries=[{"binding": 0, "resource": src.create_view()}])
        enc = dev.create_command_encoder()
        rp = enc.begin_render_pass(color_attachments=[], depth_stencil_attachment={
            "view": dep.create_view(), "depth_load_op": "clear", "depth_store_op": "store", "depth_clear_value": 1.0})
        rp.set_pipeline(self._fill[samples])
        rp.set_bind_group(0, bg)
        rp.draw(3)
        rp.end()
        self.q.submit([enc.finish()])
        return dep

    def run(self, gl, case):
        from app.gpu.caps import look_uniforms
        dev, TU = self.dev, self.TU
        w, h = self.size
        caps = self.caps
        res = {}
        plan = caps.plan(self.model, self.geom, gl["draws"], gl["VP"], gl["V"], (w, h), gl["fs"], gl["s"], gl["clip"],
                         gl["cam"])
        res["plan"] = plan
        if plan is None:
            return res
        RA, TB, CS, CD = TU.RENDER_ATTACHMENT, TU.TEXTURE_BINDING, TU.COPY_SRC, TU.COPY_DST
        id_tex = self.upload(gl["pre_id"], "rg32float", RA)
        nd_tex = self.upload(gl["pre_nd"], "rgba32float", RA)
        sg = self.shade_group(gl)
        enc = dev.create_command_encoder()
        caps.encode_gather(enc, plan)
        dev.queue.submit([enc.finish()])
        t = caps.t
        flip = lambda a: np.ascontiguousarray(a[::-1])
        res["zp"] = flip(self.read(t["zp"], np.float32, 1)[..., 0])
        res["albedo"] = flip(self.read(t["albedo"], np.float16, 4))
        res["normal"] = flip(self.read(t["normal"], np.float16, 4))
        res["id_cap"] = flip(self.read(t["id"], np.float32, 2))
        res["key"] = flip(self.read(t["key"], np.float32, 1)[..., 0])
        enc = dev.create_command_encoder()
        caps.encode_lay_in(enc, id_tex, nd_tex)
        caps.encode_colour(enc, sg)
        dev.queue.submit([enc.finish()])
        res["id"] = self.read(id_tex, np.float32, 2)
        res["nd"] = self.read(nd_tex, np.float32, 4)
        res["col"] = self.read(caps.t["col"], np.float32, 4)
        # fs_mix onto colour + depth: depth = GL's main-pass depth before the cut faces (its pre-pass depth), 1 and 4 samples
        for samples in (1, 4):
            dep = self.depth_from(gl["depth_before_mix"], samples)
            colour = dev.create_texture(size=(w, h, 1), format="rgba16float", sample_count=samples, usage=RA | TB | CS | TU.COPY_DST)
            resolved = dev.create_texture(size=(w, h, 1), format="rgba16float", usage=RA | CS)
            enc = dev.create_command_encoder()
            cv = colour.create_view()
            if samples == 1:
                self.q.write_texture({"texture": colour, "mip_level": 0, "origin": (0, 0, 0)},
                                     np.ascontiguousarray(gl["main_colour"][::-1]).astype(np.float16),
                                     {"offset": 0, "bytes_per_row": w * 8, "rows_per_image": h}, (w, h, 1))
            else:
                rp = enc.begin_render_pass(color_attachments=[
                    {"view": cv, "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 0)}])
                rp.end()
            if samples == 1:
                caps.encode_mix(enc, sg, cv, dep.create_view(), 1)
                final = colour
            else:
                caps.encode_mix(enc, sg, cv, dep.create_view(), samples, resolve_view=resolved.create_view())
                final = resolved
            caps.encode_depth(enc, dep.create_view(), samples)
            dev.queue.submit([enc.finish()])
            res[f"mix{samples}"] = flip(self.read(final, np.float16, 4))
            res[f"depth{samples}"] = flip(self.read(dep, np.float32, 1)[..., 0]) if samples == 1 else None
        return res


# ---------------------------------------------------------------------------------------------------------------
# metrics

def _flags(a):
    return (np.rint(a).astype(np.int64) & 2) != 0


def compare(gl, wg, size, msaa=1):
    out = {}
    plan = wg["plan"]
    out["plan_items"] = len(plan.items) if plan else 0
    if plan is None:
        out["no_plan"] = True
        return out
    # --- inputs: the uniforms plan() builds against the ones the GL renderer set
    from app.gpu.shading_uniforms import pack_shading_uniforms
    mism = 0
    gl_parts = gl["tee_cap"].parts
    out["cap_draws_gl"], out["cap_draws_wgpu"] = len(gl_parts), plan.n_draws
    for i, rec in enumerate(plan.records):
        o = plan.ordinals[i]                       # parts the plan skips as wholly removed are drawn (and discarded) by GL
        if o >= len(gl_parts) or rec != pack_shading_uniforms(known_uniforms(gl_parts[o])):
            mism += 1
    out["uniform_records_differ"] = mism
    # --- cap targets
    zg, zw = gl["zp"], wg["zp"]
    g, w_ = zg > 0, zw > 0
    both = g & w_
    out["cap_px_gl"], out["cap_px_wgpu"] = int(g.sum()), int(w_.sum())
    out["only_gl"], out["only_wgpu"] = int((g & ~w_).sum()), int((w_ & ~g).sum())
    if both.any():
        out["zp_max_abs"] = float(np.abs(zg - zw)[both].max())
        out["albedo_max_abs"] = float(np.abs(gl["albedo"] - wg["albedo"])[both][..., :4].max())
        out["albedo_max_rel"] = float((np.abs(gl["albedo"] - wg["albedo"])[both] /
                                       np.maximum(np.abs(gl["albedo"][both]), 1e-3)).max())
        out["normal_max_abs"] = float(np.abs(gl["normal"] - wg["normal"])[both].max())
        out["cap_id_mismatch"] = int((np.abs(gl["id_cap"] - wg["id_cap"])[both] > 0).any(-1).sum())
        out["key_max_abs"] = float(np.abs(gl["key"] - wg["key"])[both].max())
        out["key_differ_gt_1lsb"] = int((np.abs(gl["key"] - wg["key"])[both] > 1.5 / 16777215.0).sum())
    # --- after the lay-in
    fg, fw = _flags(gl["id"][..., 1]), _flags(wg["id"][..., 1])
    out["lay_px_gl"], out["lay_px_wgpu"] = int(fg.sum()), int(fw.sum())
    out["lay_only_gl"], out["lay_only_wgpu"] = int((fg & ~fw).sum()), int((fw & ~fg).sum())
    out["id_flags_differ"] = int((np.abs(gl["id"] - wg["id"]).max(-1) > 0).sum())
    lb = fg & fw
    if lb.any():
        out["lay_nd_normal_max"] = float(np.abs(gl["nd"][..., :3] - wg["nd"][..., :3])[lb].max())
        out["lay_nd_depth_max_rel"] = float((np.abs(gl["nd"][..., 3] - wg["nd"][..., 3])[lb] / gl["nd"][..., 3][lb]).max())
    out["nd_differ_outside_caps"] = int((np.abs(gl["nd"] - wg["nd"]).max(-1)[~(fg | fw)] > 0).sum())
    # classify one-sided lay-in pixels: the stored depth was within 2e-5 (relative) of the face -> a rim tie
    for tag, m in (("gl", fg & ~fw), ("wgpu", fw & ~fg)):
        if m.any():
            pre = gl["pre_nd"][..., 3][m]
            new = np.where(fg, gl["nd"][..., 3], wg["nd"][..., 3])[m]
            rim = np.abs(pre - new) <= 2e-5 * np.maximum(pre, 1e-3)
            out[f"lay_only_{tag}_rim_ties"] = int((rim | (pre <= 0)).sum() - (pre <= 0).sum() + 0)
    # --- colour against GL's resolved forward colour.  GL tests the cut face against the MAIN pass depth, which differs from
    # the pre-pass depth on a few rim pixels (GL draws the clipped surface there with another rasterisation): pixels where the
    # GL cut-face test fails are not comparable ("lose"); 2x2 quads next to them or next to a non-cap pixel run helper lanes
    # in GL's full-screen draw ("quad").  The wgpu chain has one depth for both, by construction.
    cov = fg & fw
    q24 = lambda a: np.floor(a * 16777215.0 + 0.5)
    main = gl["depth_before_mix"]
    lose = cov & ~(q24(gl["zp"]) < q24(main))
    quad = np.zeros_like(cov)
    h_, w_ = cov.shape
    for y in range(0, h_ - 1, 2):
        for x in range(0, w_ - 1, 2):
            blk = (cov & ~lose)[y:y + 2, x:x + 2]
            if not blk.all():
                quad[y:y + 2, x:x + 2] = True
    out["gl_cap_loses_to_main_depth"] = int(lose.sum())
    out["gl_main_vs_pre_depth_px"] = int((np.abs(main - gl["pre_depth"]) > 1e-6).sum())
    alone = gl["capmix_alone"]
    err = np.abs(tone(wg["col"][..., :3]) - tone(alone)).max(-1)
    for tag, mask in (("col", cov), ("col_core", cov & ~quad)):
        if mask.any():
            e = err[mask]
            out[tag + "_max"], out[tag + "_mean"] = float(e.max()), float(e.mean())
            out[tag + "_n"], out[tag + "_gt2"] = int(mask.sum()), int((e > 2).sum())
    # the whole frame, cut faces drawn over GL's main-pass colour and depth (fs_mix, 1 sample) against GL's resolved frame.
    # GL's "msaa 1" renderbuffer is really multisampled (blend fractions of exactly 1/2 on the rim pixels), so only pixels whose
    # 3x3 neighbourhood is entirely a winning cut face are comparable; the rest are counted.
    win0 = cov & ~lose
    core = win0.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            core &= np.roll(np.roll(win0, dy, 0), dx, 1)
    fkey = "mix4" if msaa > 1 else "mix1"
    if fkey in wg and core.any():
        e1 = np.abs(tone(wg[fkey]) - tone(gl["opaque"])).max(-1)[core]
        out["frame_max"], out["frame_mean"], out["frame_n"] = float(e1.max()), float(e1.mean()), int(core.sum())
        out["frame_gt2"] = int((e1 > 2).sum())
    out["rim_px_not_compared"] = int((cov & ~core).sum())
    # 4 samples (cap fully inside, whole 3x3 is cut face): shading is per pixel in both, edges resolve differently
    inner = cov & ~lose
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            inner &= np.roll(np.roll(cov & ~lose, dy, 0), dx, 1)
    if inner.any():
        e = np.abs(tone(wg["mix4"]) - tone(alone)).max(-1)[inner]
        out["mix4_interior_max"], out["mix4_interior_mean"], out["mix4_interior_n"] = float(e.max()), float(e.mean()), int(inner.sum())
    # --- depth after the cap mix: GL main depth after capmix against wgpu encode_depth, on pixels where the cap wins
    win = cov & ~lose
    if wg.get("depth1") is not None and win.any():
        out["depth_after_max_abs"] = float(np.abs(wg["depth1"] - gl["depth_after_mix"])[win].max())
        out["depth_untouched_differ"] = int((np.abs(wg["depth1"] - gl["depth_after_mix"])[~cov] > 0).sum())
    return out


def run(size=(256, 192), adapter=None, backend=None, case_names=None, scale=0.5, msaa=(1, 4)):
    from tools.perf.gpu.visbuf_check import make_gpu
    model = build_scene(scale)
    gpu = make_gpu(adapter, backend)
    glside = GLSide(model, size)
    wgside = WGSide(gpu, model, size)
    rows = []
    for name in (case_names or list(CASES)):
        case = CASES[name]
        for m in msaa:
            gl = glside.run(case, m)
            wg = wgside.run(gl, case)
            row = compare(gl, wg, size, m)
            row.update(case=name, msaa=m, gl=glside.info, wgpu=gpu.info)
            rows.append(row)
    return rows


def print_table(rows):
    keys = ("cap_px_gl", "only_gl", "only_wgpu", "zp_max_abs", "albedo_max_abs", "normal_max_abs", "cap_id_mismatch",
            "key_differ_gt_1lsb", "lay_only_gl", "lay_only_wgpu", "id_flags_differ", "gl_cap_loses_to_main_depth", "col_max", "col_mean", "col_gt2", "col_core_max", "frame_max", "frame_mean", "frame_gt2", "rim_px_not_compared", "mix4_interior_max", "mix4_interior_mean", "depth_after_max_abs")
    print("case,msaa," + ",".join(keys))
    for r in rows:
        print(r["case"] + "," + str(r["msaa"]) + "," + ",".join(
            (f"{r[k]:.4g}" if isinstance(r.get(k), float) else str(r.get(k, "-"))) for k in keys))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="256x192")
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--backend", default=None)
    ap.add_argument("--cases", default=None)
    ap.add_argument("--scale", type=float, default=0.5)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    w, h = (int(x) for x in a.size.lower().split("x"))
    rows = run((w, h), a.adapter, a.backend, a.cases.split(",") if a.cases else None, a.scale)
    print_table(rows)
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
