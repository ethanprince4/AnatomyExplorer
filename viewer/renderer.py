"""The viewer renderer (moderngl). Usable in any QOpenGLWidget or a standalone context.

    r = Renderer(ctx)
    r.set_model(model)
    r.render(target_fbo, (w, h), camera, settings, weight_state)
    part_id, world_point = r.pick(x, y)           # from the last frame's pre-pass

Frame: shadow maps (key, fill, rim; camera-relative like the harness rig) -> pre-pass (view normal, linear depth,
part id) -> SSAO + depth-aware blur -> MSAA forward (backdrop, opaque GGX/IBL/tissue term/procedural stripes)
-> MSAA weighted-blended OIT (translucent covering) -> resolve -> composite (outline, Khronos PBR Neutral, sRGB).
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

import moderngl
import numpy as np

from . import shaders
from .environment import Environment
from .model import Model, Part

FMT = "3f 3f 3f 3f 1f 4f 2f"
ATTRS = ("in_pos", "in_nrm", "in_dpos", "in_dnrm", "in_fib", "in_col", "in_uv")

DEFAULT_RIG = [  # the harness rig (trial/harness/config.json stage.lights)
    {"name": "key", "azimuth_deg": 40.0, "elevation_deg": 35.0, "size_factor": 0.35, "energy": 15.0, "colour": [1, 1, 1]},
    {"name": "fill", "azimuth_deg": -55.0, "elevation_deg": 10.0, "size_factor": 0.6, "energy": 5.0, "colour": [1, 1, 1]},
    {"name": "rim", "azimuth_deg": 165.0, "elevation_deg": 40.0, "size_factor": 0.3, "energy": 10.0, "colour": [1, 1, 1]},
]
DEFAULT_WORLD = {"top_hex": "#20242b", "bottom_hex": "#12141a", "ambient_colour": [0.5, 0.5, 0.5], "ambient_strength": 0.3}


def srgb_hex_to_linear(h):
    out = []
    for i in (1, 3, 5):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out


def backdrop_linear(h, neutral=True):
    """Scene-linear colour that Khronos PBR Neutral displays as ``h`` (the harness's toe compensation)."""
    t = srgb_hex_to_linear(h)
    if not neutral:
        return t
    lo = min(t)
    off = math.sqrt(lo / 6.25) - lo if lo < 0.04 else 0.04
    return [v + off for v in t]


@dataclass
class Settings:
    ao: bool = True
    shadows: bool = True
    stripes: bool = True
    tonemap: bool = True               # Khronos PBR Neutral (off = Standard)
    exposure: float = 0.0
    studio: float = 0.30               # 0 = the harness's uniform ambient only, 1 = full studio environment
    env_diffuse: float = 1.0
    env_spec: float = 1.0
    light_scale: float = 1.0
    tissue: float = 1.0                # strength of the wrapped (subsurface-style) diffuse term
    ao_radius: float = 0.0             # 0 = automatic
    ao_strength: float = 1.0
    ao_direct: float = 0.35            # how much AO also darkens direct light (contact shading)
    ao_large: float = 3.5              # cavity-scale AO radius, as a multiple of the contact radius
    ao_large_mix: float = 0.8
    bounce: float = 0.6                # one-bounce screen-space GI from the previous frame (stand-in for Cycles GI)
    msaa: int = 8
    shadow_soft: float = 2.0          # Cycles' area lights are large (0.3-0.6 x the light distance)
    selected: int = 0
    hovered: int = 0
    outline: tuple = (1.0, 0.86, 0.35)
    hover_outline: tuple = (0.75, 0.85, 1.0)
    highlight: tuple = (1.0, 0.85, 0.45)
    extra: dict = field(default_factory=dict)


class _U:
    """Uniform setter that skips unknown names and unchanged values."""

    def __init__(self, prog):
        self.prog = prog
        self.cache = {}

    def __call__(self, name, value):
        u = self.prog.get(name, None)
        if u is None:
            return
        if isinstance(value, np.ndarray) and value.ndim == 2:
            data = np.ascontiguousarray(value.T, dtype=np.float32).tobytes()
        elif isinstance(value, np.ndarray):
            data = np.ascontiguousarray(value, dtype=np.float32).tobytes()
        elif isinstance(value, bool):
            value = int(value)
            data = None
        else:
            data = None
        key = data if data is not None else value
        if self.cache.get(name) == key:
            return
        self.cache[name] = key
        if data is not None:
            u.write(data)
        else:
            u.value = value

    def reset(self):
        self.cache.clear()


def _frustum_planes(vp):
    m = vp
    planes = np.array([m[3] + m[0], m[3] - m[0], m[3] + m[1], m[3] - m[1], m[3] + m[2], m[3] - m[2]])
    n = np.linalg.norm(planes[:, :3], axis=1, keepdims=True)
    return planes / np.maximum(n, 1e-12)


class Renderer:
    def __init__(self, ctx: moderngl.Context):
        self.ctx = ctx
        P = lambda vs, fs: ctx.program(vertex_shader=vs, fragment_shader=fs)
        self.p_main = P(shaders.GEOM_VS, shaders.MAIN_FS)
        self.p_oit = P(shaders.GEOM_VS, shaders.OIT_FS)
        self.p_pre = P(shaders.GEOM_VS, shaders.PREPASS_FS)
        self.p_shadow = P(shaders.SHADOW_VS, shaders.SHADOW_FS)
        self.p_back = P(shaders.FSQ_VS, shaders.BACKDROP_FS)
        self.p_ssao = P(shaders.FSQ_VS, shaders.SSAO_FS)
        self.p_blur = P(shaders.FSQ_VS, shaders.BLUR_FS)
        self.p_comp = P(shaders.FSQ_VS, shaders.COMPOSITE_FS)
        self.u = {p: _U(p) for p in (self.p_main, self.p_oit, self.p_pre, self.p_shadow, self.p_back,
                                     self.p_ssao, self.p_blur, self.p_comp)}
        self.fsq = {p: ctx.vertex_array(p, []) for p in (self.p_back, self.p_ssao, self.p_blur, self.p_comp)}
        self.env = Environment(ctx, studio=Settings.studio)
        self._env_key = (Settings.studio, 0.15)
        self.white = ctx.texture((1, 1), 4, bytes([255, 255, 255, 255]))
        self.model: Model | None = None
        self.vbo = self.ibo = None
        self.vaos = {}
        self.textures = {}
        self.size = None
        self.samples = None
        self.t = {}
        self.shadow_maps = []
        self.shadow_sizes = (4096, 2048, 2048)
        self._shadow_key = None
        self._shadow_mats = [np.eye(4)] * 3
        self._shadow_texel = [0.01] * 3
        self._shadow_soft = [0.001] * 3
        self.rig = DEFAULT_RIG
        self.world = DEFAULT_WORLD
        self.last_camera = None
        self.gl_info = f"{ctx.info.get('GL_RENDERER', '?')} / OpenGL {ctx.version_code}"
        for s in self.shadow_sizes:
            tex = ctx.depth_texture((s, s))
            tex.compare_func = "<="
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            tex.repeat_x = tex.repeat_y = False
            self.shadow_maps.append((tex, ctx.framebuffer(depth_attachment=tex)))

    # ------------------------------------------------------------------ model
    def set_model(self, model: Model):
        self.release_model()
        ctx = self.ctx
        self.model = model
        self.vbo = ctx.buffer(np.ascontiguousarray(model.vertices, dtype=np.float32).tobytes())
        self.ibo = ctx.buffer(np.ascontiguousarray(model.indices, dtype=np.uint32).tobytes())
        for p in (self.p_main, self.p_oit, self.p_pre, self.p_shadow):
            self.vaos[p] = ctx.vertex_array(p, [(self.vbo, FMT, *ATTRS)], self.ibo, 4, skip_errors=True)
        side = model.sidecar.get("lights") or {}
        self.rig = side.get("rig") or DEFAULT_RIG
        self.world = side.get("world") or DEFAULT_WORLD
        self._shadow_key = None
        diag = float(np.linalg.norm(model.bounds_max - model.bounds_min))
        self.model_diag = max(diag, 1e-3)
        for u in self.u.values():
            u.reset()

    def release_model(self):
        for v in self.vaos.values():
            v.release()
        self.vaos = {}
        for b in (self.vbo, self.ibo):
            if b is not None:
                b.release()
        self.vbo = self.ibo = None
        for t in self.textures.values():
            t.release()
        self.textures = {}
        self.model = None

    def _texture(self, image_index):
        if image_index in self.textures:
            return self.textures[image_index]
        tex = self.white
        try:
            from PIL import Image
            raw = self.model.doc.images[image_index]
            im = Image.open(io.BytesIO(raw)).convert("RGBA").transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            tex = self.ctx.texture(im.size, 4, im.tobytes())
            tex.build_mipmaps()
        except Exception:
            tex = self.white
        self.textures[image_index] = tex
        return tex

    # ------------------------------------------------------------------ targets
    def _ensure_targets(self, w, h, samples):
        if self.size == (w, h) and self.samples == samples:
            return
        for obj in self.t.values():
            obj.release()
        ctx = self.ctx
        t = {}
        t["nd"] = ctx.texture((w, h), 4, dtype="f4")
        t["id"] = ctx.texture((w, h), 1, dtype="f4")
        t["pre_depth"] = ctx.depth_renderbuffer((w, h))
        for k in ("nd", "id"):
            t[k].filter = (moderngl.NEAREST, moderngl.NEAREST)
            t[k].repeat_x = t[k].repeat_y = False
        t["fbo_pre"] = ctx.framebuffer([t["nd"], t["id"]], t["pre_depth"])
        for k in ("ao", "ao_tmp"):
            t[k] = ctx.texture((w, h), 4, dtype="f2")
            t[k].repeat_x = t[k].repeat_y = False
            t["fbo_" + k] = ctx.framebuffer([t[k]])
        t["col_ms"] = ctx.renderbuffer((w, h), 4, samples=samples, dtype="f2")
        t["depth_ms"] = ctx.depth_renderbuffer((w, h), samples=samples)
        t["acc_ms"] = ctx.renderbuffer((w, h), 4, samples=samples, dtype="f2")
        t["wgt_ms"] = ctx.renderbuffer((w, h), 1, samples=samples, dtype="f2")
        t["fbo_main"] = ctx.framebuffer([t["col_ms"]], t["depth_ms"])
        t["fbo_oit"] = ctx.framebuffer([t["acc_ms"], t["wgt_ms"]], t["depth_ms"])
        t["fbo_col_src"] = ctx.framebuffer([t["col_ms"]])
        t["fbo_acc_src"] = ctx.framebuffer([t["acc_ms"]])
        t["fbo_wgt_src"] = ctx.framebuffer([t["wgt_ms"]])
        for k, comps in (("opaque", 4), ("accum", 4), ("weight", 1)):
            t[k] = ctx.texture((w, h), comps, dtype="f2")
            t[k].repeat_x = t[k].repeat_y = False
            t["fbo_" + k] = ctx.framebuffer([t[k]])
        self.t = t
        self.size = (w, h)
        self.samples = samples

    # ------------------------------------------------------------------ frame
    def render(self, target, size, camera, s: Settings):
        """Render one frame into ``target`` (a moderngl Framebuffer) of pixel ``size``."""
        ctx = self.ctx
        w, h = max(int(size[0]), 2), max(int(size[1]), 2)
        samples = max(1, min(int(s.msaa), ctx.max_samples))
        self._ensure_targets(w, h, samples)
        if self._env_key != (round(s.studio, 3), self._ambient()):
            self.env.rebuild(s.studio, self._ambient())
            self._env_key = (round(s.studio, 3), self._ambient())
        t = self.t
        aspect = w / h
        V = camera.view_matrix()
        Pm = camera.proj_matrix(aspect)
        VP = Pm @ V
        campos = camera.position()
        self.last_camera = (V, Pm, aspect, camera.ortho,
                            camera.ortho_halves(aspect) if camera.ortho else camera.half_tans(aspect), (w, h))
        m = self.model

        ctx.disable(moderngl.BLEND | moderngl.CULL_FACE)
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.depth_func = "<"

        draws, oit = [], []
        if m is not None:
            planes = _frustum_planes(VP)
            for p in m.parts:
                if not p.visible:
                    continue
                c, r = m.part_sphere(p)
                if np.any(planes[:, :3] @ c + planes[:, 3] < -r):
                    continue
                (oit if p.role == "covering" or p.look.translucent else draws).append(p)

        # light directions (camera-relative rig) and irradiance
        Rinv = V[:3, :3].T
        lights = []
        for spec in (self.rig or DEFAULT_RIG)[:3]:
            az, el = math.radians(spec["azimuth_deg"]), math.radians(spec["elevation_deg"])
            dv = np.array([math.cos(el) * math.sin(az), math.sin(el), math.cos(el) * math.cos(az)])
            L = Rinv @ dv
            E = np.array(spec.get("colour", [1, 1, 1]), float) * float(spec["energy"]) / math.pi * s.light_scale
            size_eq = float(spec.get("size_factor", 0.35)) * 0.5642          # square side -> equal-area disc radius
            lights.append((L / np.linalg.norm(L), E, size_eq, float(spec.get("size_factor", 0.35))))
        while len(lights) < 3:
            lights.append((np.array([0.0, 1.0, 0.0]), np.zeros(3), 0.1, 0.1))

        # 1. shadow maps
        if s.shadows and m is not None:
            self._render_shadows(lights, s)

        # 2. pre-pass: normals, linear depth, ids (opaque only)
        fpre = t["fbo_pre"]
        fpre.use()
        ctx.viewport = (0, 0, w, h)
        fpre.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        if m is not None:
            u = self.u[self.p_pre]
            u("u_viewproj", VP)
            u("u_view", V)
            vao = self.vaos[self.p_pre]
            for p in draws:
                M = m.part_matrix(p)
                u("u_model", M)
                u("u_nmat", np.linalg.inv(M[:3, :3]).T)
                u("u_weight", float(m.node_weights.get(p.node, 0.0)))
                u("u_id", float(p.id))
                vao.render(moderngl.TRIANGLES, vertices=p.count, first=p.first)

        # 3. SSAO
        if s.ao and m is not None:
            ctx.disable(moderngl.DEPTH_TEST)
            u = self.u[self.p_ssao]
            radius = s.ao_radius or self._auto_ao_radius()
            t["fbo_ao"].use()
            ctx.viewport = (0, 0, w, h)
            t["nd"].use(0)
            u("u_nd", 0)
            if camera.ortho:
                hx, hy = camera.ortho_halves(aspect)
                u("u_tan", np.array([hx, hy]))
                u("u_ortho", 1)
            else:
                tx, ty = camera.half_tans(aspect)
                u("u_tan", np.array([tx, ty]))
                u("u_ortho", 0)
            u("u_radius", float(radius))
            u("u_bias", float(radius * 0.03))
            u("u_power", float(1.6 * s.ao_strength))
            u("u_samples", 16)
            u("u_large", float(s.ao_large))
            u("u_large_mix", float(s.ao_large_mix))
            t["opaque"].use(1)
            u("u_prev", 1)
            u("u_gi_on", 1.0 if s.bounce > 0 else 0.0)
            self.fsq[self.p_ssao].render(moderngl.TRIANGLES, vertices=3)
            ub = self.u[self.p_blur]
            for src, dst, d in (("ao", "fbo_ao_tmp", (1.0 / w, 0.0)), ("ao_tmp", "fbo_ao", (0.0, 1.0 / h))):
                t[dst].use()
                t[src].use(0)
                t["nd"].use(1)
                ub("u_src", 0)
                ub("u_nd", 1)
                ub("u_dir", np.array(d))
                self.fsq[self.p_blur].render(moderngl.TRIANGLES, vertices=3)
            ctx.enable(moderngl.DEPTH_TEST)

        # 4. forward MSAA: backdrop, then opaque
        fm = t["fbo_main"]
        fm.use()
        ctx.viewport = (0, 0, w, h)
        fm.clear(0.0, 0.0, 0.0, 1.0, depth=1.0)
        ctx.disable(moderngl.DEPTH_TEST)
        ub = self.u[self.p_back]
        world = self.world or DEFAULT_WORLD
        ub("u_bottom", np.array(backdrop_linear(world.get("bottom_hex", "#12141a"), s.tonemap)))
        ub("u_top", np.array(backdrop_linear(world.get("top_hex", "#20242b"), s.tonemap)))
        self.fsq[self.p_back].render(moderngl.TRIANGLES, vertices=3)
        ctx.enable(moderngl.DEPTH_TEST)
        if m is not None:
            self._draw_shaded(self.p_main, draws, VP, V, campos, lights, s, (w, h))

        # 5. translucent covering: weighted blended OIT into the same MSAA depth
        oit_on = bool(oit) and m is not None
        if oit_on:
            fo = t["fbo_oit"]
            fo.depth_mask = False
            fo.use()
            ctx.viewport = (0, 0, w, h)
            fo.clear(0.0, 0.0, 0.0, 1.0)
            ctx.enable(moderngl.BLEND)
            ctx.blend_equation = moderngl.FUNC_ADD
            ctx.blend_func = (moderngl.ONE, moderngl.ONE, moderngl.ZERO, moderngl.ONE_MINUS_SRC_ALPHA)
            self._draw_shaded(self.p_oit, oit, VP, V, campos, lights, s, (w, h))
            ctx.disable(moderngl.BLEND)
            fo.depth_mask = True

        # 6. resolve and composite
        ctx.copy_framebuffer(t["fbo_opaque"], t["fbo_col_src"])
        if oit_on:
            ctx.copy_framebuffer(t["fbo_accum"], t["fbo_acc_src"])
            ctx.copy_framebuffer(t["fbo_weight"], t["fbo_wgt_src"])
        target.use()
        ctx.viewport = (0, 0, w, h)
        ctx.disable(moderngl.DEPTH_TEST | moderngl.BLEND)
        uc = self.u[self.p_comp]
        t["opaque"].use(0)
        t["accum"].use(1)
        t["weight"].use(2)
        t["id"].use(3)
        uc("u_opaque", 0)
        uc("u_accum", 1)
        uc("u_weight", 2)
        uc("u_id", 3)
        uc("u_oit_on", 1 if oit_on else 0)
        uc("u_sel", float(s.selected))
        uc("u_hover", float(s.hovered if s.hovered != s.selected else 0))
        uc("u_outline", np.array(s.outline))
        uc("u_hover_outline", np.array(s.hover_outline))
        uc("u_exposure", float(s.exposure))
        uc("u_tonemap", 1 if s.tonemap else 0)
        uc("u_texel", np.array([1.0 / w, 1.0 / h]))
        uc("u_outline_px", float(max(1.5, h / 540.0)))
        self.fsq[self.p_comp].render(moderngl.TRIANGLES, vertices=3)
        ctx.enable(moderngl.DEPTH_TEST)

    def _ambient(self):
        world = self.world or DEFAULT_WORLD
        return round(float(np.mean(world.get("ambient_colour", [0.5] * 3))) * float(world.get("ambient_strength", 0.3)), 4)

    def _auto_ao_radius(self):
        um = self.model.um_per_bu() if self.model else 0
        if um:
            return 4.5 / um                     # 4.5 um: the gaps between packed cells
        return self.model_diag * 0.017

    # ------------------------------------------------------------------ shadows
    def _render_shadows(self, lights, s):
        m = self.model
        ctx = self.ctx
        key = (tuple(np.round(np.concatenate([l[0] for l in lights]), 5)),
               tuple(round(w, 5) for w in sorted(m.node_weights.values())[-1:]),
               tuple(sorted((k, tuple(np.round(v, 4))) for k, v in m.node_offsets.items())),
               tuple(p.visible for p in m.parts), round(s.shadow_soft, 3))
        if key == self._shadow_key:
            return
        self._shadow_key = key
        lo, hi = m.world_bounds(visible_only=True)
        c = (lo + hi) / 2
        r = max(float(np.linalg.norm(hi - lo)) / 2, 1e-3) * 1.02
        u = self.u[self.p_shadow]
        vao = self.vaos[self.p_shadow]
        from .camera import look_at, orthographic
        casters = [p for p in m.parts if p.visible and not (p.role == "covering" or p.look.translucent)]
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.polygon_offset = (1.5, 2.0)
        for i, (L, E, size_eq, size_f) in enumerate(lights):
            tex, fbo = self.shadow_maps[i]
            n = self.shadow_sizes[i]
            up = (0.0, 1.0, 0.0) if abs(L[1]) < 0.95 else (1.0, 0.0, 0.0)
            Vl = look_at(c + L * r * 2.0, c, up)
            Pl = orthographic(r, r, r * 0.5, r * 3.5)
            VPl = Pl @ Vl
            self._shadow_mats[i] = VPl
            self._shadow_texel[i] = 2.0 * r / n
            soft_world = 0.0045 * self.model_diag * (size_f / 0.35) * s.shadow_soft
            self._shadow_soft[i] = max(soft_world / (2.0 * r), 0.5 / n)
            fbo.use()
            ctx.viewport = (0, 0, n, n)
            fbo.clear(depth=1.0)
            if not np.any(E > 0):
                continue
            u("u_viewproj", VPl)
            for p in casters:
                u("u_model", m.part_matrix(p))
                u("u_weight", float(m.node_weights.get(p.node, 0.0)))
                vao.render(moderngl.TRIANGLES, vertices=p.count, first=p.first)
        ctx.polygon_offset = (0.0, 0.0)

    # ------------------------------------------------------------------ shaded parts
    def _draw_shaded(self, prog, parts, VP, V, campos, lights, s, size):
        m = self.model
        u = self.u[prog]
        vao = self.vaos[prog]
        t = self.t
        u("u_viewproj", VP)
        u("u_view", V)
        u("u_campos", np.asarray(campos))
        u("u_screen", np.array(size, dtype=np.float32))
        t["ao"].use(0)
        u("u_ao", 0)
        u("u_ao_on", 1.0 if s.ao else 0.0)
        u("u_ao_direct", float(s.ao_direct))
        for i, (L, E, size_eq, _sf) in enumerate(lights):
            u(f"u_ldir{i}", L)
            u(f"u_lrad{i}", E)
            u(f"u_lsize{i}", float(size_eq))
            u(f"u_lmat{i}", self._shadow_mats[i])
            u(f"u_ltexel{i}", float(self._shadow_texel[i]))
            u(f"u_lsoft{i}", float(self._shadow_soft[i]))
            self.shadow_maps[i][0].use(1 + i)
            u(f"u_shadow{i}", 1 + i)
        u("u_shadow_on", 1.0 if s.shadows else 0.0)
        sh = self.env.sh
        prog_sh = prog.get("u_sh", None)
        if prog_sh is not None:
            prog_sh.write(np.ascontiguousarray(sh, dtype=np.float32).tobytes())
        self.env.spec.use(4)
        u("u_spec", 4)
        u("u_spec_layers", float(self.env.spec.layers))
        u("u_env_diffuse", float(s.env_diffuse))
        u("u_env_spec", float(s.env_spec))
        u("u_bounce", float(s.bounce * s.light_scale))
        u("u_highlight_col", np.array(s.highlight))
        self.white.use(5)
        u("u_tex", 5)
        order = sorted(parts, key=lambda p: (p.material_name, p.id))
        for p in order:
            M = m.part_matrix(p)
            wgt = float(m.node_weights.get(p.node, 0.0))
            u("u_model", M)
            u("u_nmat", np.linalg.inv(M[:3, :3]).T)
            u("u_weight", wgt)
            self._set_look(u, p, s)
            if p.id == s.selected:
                u("u_highlight", 0.45)
            elif p.id == s.hovered:
                u("u_highlight", 0.18)
            else:
                u("u_highlight", 0.0)
            vao.render(moderngl.TRIANGLES, vertices=p.count, first=p.first)

    def _set_look(self, u, p: Part, s: Settings):
        lk = p.look
        u("u_base", np.array(lk.base))
        u("u_alpha", float(lk.alpha))
        u("u_rough", float(lk.rough))
        u("u_metal", float(lk.metal))
        u("u_f0", float(lk.f0))
        u("u_wrap", float(min(0.5, (0.02 + 1.5 * lk.sss) * s.tissue)))
        u("u_emis", np.array(lk.emissive))
        u("u_use_vcol", 1 if lk.use_vcol else 0)
        if lk.texture is not None:
            tex = self._texture(lk.texture)
            tex.use(6)
            u("u_tex", 6)
            u("u_has_tex", 1)
        else:
            u("u_tex", 5)
            u("u_has_tex", 0)
        st = lk.stripe
        if st:
            u("u_stripe", 1 if s.stripes else 2)
            u("u_stripe_p", np.array([st["period"], st["threshold"], st.get("edge", 0.025), st.get("i_mix", 1.0)]))
            u("u_shorten", float(st.get("shorten", 0.0)))
            u("u_stripe_a", np.array(st["a_band_colour"]))
            u("u_stripe_b", np.array(st["i_band_colour"]))
        else:
            u("u_stripe", 0)
        mo = lk.mottle
        if mo:
            u("u_mottle", 1)
            u("u_mottle_p", np.array([mo["scale"], mo["from_min"], mo["from_max"], min(6.0, mo.get("detail", 2.0) + 1.0)]))
            u("u_mottle_a", np.array(mo["colour_a"]))
            u("u_mottle_b", np.array(mo["colour_b"]))
        else:
            u("u_mottle", 0)
        if lk.facing:
            u("u_facing_on", 1)
            u("u_facing", np.array(lk.facing))
        else:
            u("u_facing_on", 0)

    # ------------------------------------------------------------------ picking
    def pick(self, x, y):
        """Part id and world point under window pixel (x, y from the top-left) of the last frame."""
        if self.last_camera is None or not self.t:
            return 0, None
        V, Pm, aspect, ortho, halves, (w, h) = self.last_camera
        if not (0 <= x < w and 0 <= y < h):
            return 0, None
        gy = h - 1 - int(y)
        fpre = self.t["fbo_pre"]
        nd = np.frombuffer(fpre.read(viewport=(int(x), gy, 1, 1), components=4, attachment=0, dtype="f4"), dtype=np.float32)
        pid = np.frombuffer(fpre.read(viewport=(int(x), gy, 1, 1), components=1, attachment=1, dtype="f4"), dtype=np.float32)
        d = float(nd[3])
        if d <= 0.0:
            return 0, None
        ndc = np.array([(x + 0.5) / w * 2 - 1, (gy + 0.5) / h * 2 - 1])
        if ortho:
            pv = np.array([ndc[0] * halves[0], ndc[1] * halves[1], -d, 1.0])
        else:
            pv = np.array([ndc[0] * halves[0] * d, ndc[1] * halves[1] * d, -d, 1.0])
        pw = np.linalg.inv(V) @ pv
        return int(round(float(pid[0]))), pw[:3]

    def read_final(self, fbo, size):
        w, h = size
        data = fbo.read(viewport=(0, 0, w, h), components=3)
        return np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3)[::-1]
