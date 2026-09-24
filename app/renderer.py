import struct

import moderngl
import numpy as np

from . import shaders
from PySide6.QtGui import QColor

from .config import BACKGROUND_DARK, BACKGROUND_LIGHT, SHADING
from .state import STATE_TEX_WIDTH, srgb_to_linear

VERTEX_FORMAT = "3f 3f u2 u2"
VERTEX_ATTRS = ("in_pos", "in_nrm", "in_obj", "in_mat")
# imported models add a second buffer: texture coordinates, a vertex colour (sRGB bytes) and a texture layer
AUX_FORMAT = "2f 4f1 1f"
AUX_ATTRS = ("in_uv", "in_tint", "in_layer")
FORMAT_SIZE = {"3f": 12, "2f": 8, "1f": 4, "u2": 2, "4f1": 4}
ALBEDO_UNIT = 5


def _normalize(v):
    return v / np.linalg.norm(v)


def _mat4_bytes(m):
    return np.asarray(m, dtype="f4").T.tobytes()


class Renderer:
    def __init__(self, ctx: moderngl.Context, ds, vertices, indices, cap_depth=False):
        self.ctx = ctx
        self.ds = ds
        self.index_count = len(indices) // 4

        opaque_fs = shaders.OPAQUE_FS
        if cap_depth:
            opaque_fs = opaque_fs.replace("#version 410 core", "#version 410 core\n#define CAP_DEPTH 1", 1)
        self.p_opaque = ctx.program(vertex_shader=shaders.GEOMETRY_VS, fragment_shader=opaque_fs)
        self.p_transparent = ctx.program(vertex_shader=shaders.GEOMETRY_VS, fragment_shader=shaders.TRANSPARENT_FS)
        self.p_mask = ctx.program(vertex_shader=shaders.GEOMETRY_VS, fragment_shader=shaders.MASK_FS)
        self.p_ssao = ctx.program(vertex_shader=shaders.FULLSCREEN_VS, fragment_shader=shaders.SSAO_FS)
        self.p_blur = ctx.program(vertex_shader=shaders.FULLSCREEN_VS, fragment_shader=shaders.BLUR_FS)
        self.p_composite = ctx.program(vertex_shader=shaders.FULLSCREEN_VS, fragment_shader=shaders.COMPOSITE_FS)
        self.p_final = ctx.program(vertex_shader=shaders.FULLSCREEN_VS, fragment_shader=shaders.FINAL_FS)
        self.p_fxaa = ctx.program(vertex_shader=shaders.FULLSCREEN_VS, fragment_shader=shaders.FXAA_FS)

        self.vbo = ctx.buffer(vertices)
        self.ibo = ctx.buffer(indices)
        self.textured = bool(getattr(ds, "textured", False))
        self.aux = ctx.buffer(ds.aux_bytes()) if self.textured else None

        def geo_vao(prog):
            buffers = [(self.vbo, self._format_for(prog), *[a for a in VERTEX_ATTRS if a in prog])]
            if self.aux is not None and any(a in prog for a in AUX_ATTRS):
                buffers.append((self.aux, self._format_for(prog, AUX_FORMAT, AUX_ATTRS),
                                *[a for a in AUX_ATTRS if a in prog]))
            return ctx.vertex_array(prog, buffers, index_buffer=self.ibo, index_element_size=4)

        self.vao_opaque = geo_vao(self.p_opaque)
        self.vao_transparent = geo_vao(self.p_transparent)
        self.vao_mask = geo_vao(self.p_mask)
        self.fs = {name: ctx.vertex_array(p, []) for name, p in (
            ("ssao", self.p_ssao), ("blur", self.p_blur), ("composite", self.p_composite),
            ("final", self.p_final), ("fxaa", self.p_fxaa))}

        self.state_tex = ctx.texture((STATE_TEX_WIDTH, 2), 4, dtype="f4")
        self.state_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self.mats_tex = ctx.texture((1024, 4), 4, dtype="f4")
        self.detail = 1 if getattr(ds, "detail_shading", False) else 0
        self.mats_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self._upload_materials()
        layers = getattr(ds, "texture_layers", None) if self.textured else None
        self.albedo = None
        if layers is not None and len(layers):
            n, h, w = layers.shape[:3]
            try:
                self.albedo = ctx.texture_array((w, h, n), 4, np.ascontiguousarray(layers, dtype=np.uint8).tobytes())
                self.albedo.build_mipmaps()
                self.albedo.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
                self.albedo.anisotropy = 8.0
            except moderngl.Error:              # out of video memory or too many layers: draw without textures
                self.albedo = None
        if self.albedo is None:                 # the sampler still needs something bound
            self.albedo = ctx.texture_array((1, 1, 1), 4, bytes([255, 255, 255, 255]))

        rng = np.random.default_rng(7)
        noise = np.zeros((4, 4, 4), dtype=np.float32)
        noise[..., :2] = rng.uniform(0, 1, (4, 4, 2))
        noise[..., 2] = 0.5
        noise[..., 3] = 1
        self.noise_tex = ctx.texture((4, 4), 4, noise.tobytes(), dtype="f4")
        self.noise_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        kernel = []
        for i in range(16):
            v = rng.uniform([-1, -1, 0.05], [1, 1, 1])
            v = _normalize(v) * rng.uniform(0.2, 1.0)
            scale = i / 16.0
            v *= 0.1 + 0.9 * scale * scale
            kernel.append(v)
        self.kernel = np.array(kernel, dtype="f4")

        self.size = (0, 0)
        self.screen_size = None
        self.last_vp = np.identity(4)
        self.frame_ok = False

    @staticmethod
    def _format_for(prog, fmt=VERTEX_FORMAT, attrs=VERTEX_ATTRS):
        """The buffer's layout for one program: attributes the program does not use become padding."""
        return " ".join(f if a in prog else f"{FORMAT_SIZE[f]}x" for f, a in zip(fmt.split(), attrs))

    def _upload_materials(self):
        data = np.zeros((4, 1024, 4), dtype=np.float32)
        for i, m in enumerate(self.ds.materials):
            data[0, i, :3] = srgb_to_linear(m["color"])
            data[0, i, 3] = m["alpha"]
            data[1, i, :3] = srgb_to_linear(m["distinct"])
            data[1, i, 3] = m["alpha"]
            spec, gloss, rim = SHADING.get(m["category"], SHADING["other"])
            data[2, i, :3] = (spec, gloss, rim)
            if m.get("detail"):
                data[3, i, :4] = m["detail"][:4]
        self.mats_tex.write(data.tobytes())

    def release(self):
        """Free every GPU object. Contexts are shared, so nothing goes away with the widget by itself."""
        if getattr(self, "_released", False):
            return
        self._released = True
        objs = [self.vao_opaque, self.vao_transparent, self.vao_mask, *self.fs.values(),
                self.p_opaque, self.p_transparent, self.p_mask, self.p_ssao, self.p_blur, self.p_composite,
                self.p_final, self.p_fxaa, self.vbo, self.ibo, self.aux, self.state_tex, self.mats_tex,
                self.noise_tex, self.albedo]
        objs += [getattr(self, n, None) for n in ("gbuffer", "mask_fbo", "ao_fbo", "blur_fbo", "hdr_fbo", "ldr_fbo",
                                                  "color_tex", "normal_tex", "id_tex", "depth_tex", "mask_tex",
                                                  "mask_depth", "ao_tex", "blur_tex", "hdr_tex", "ldr_tex")]
        for o in objs:
            if o is not None:
                try:
                    o.release()
                except Exception:           # noqa: BLE001 - already gone with its context
                    pass

    def update_state(self, tex):
        self.state_tex.write(np.ascontiguousarray(tex, dtype=np.float32).tobytes())

    # ------------------------------------------------------------------ targets
    def resize(self, w, h):
        w, h = max(int(w), 1), max(int(h), 1)
        if (w, h) == self.size:
            return
        self.size = (w, h)
        ctx = self.ctx
        for name in ("gbuffer", "mask_fbo", "ao_fbo", "blur_fbo", "hdr_fbo", "ldr_fbo"):
            fbo = getattr(self, name, None)
            if fbo is not None:
                fbo.release()
        for name in ("color_tex", "normal_tex", "id_tex", "depth_tex", "mask_tex", "mask_depth", "ao_tex",
                     "blur_tex", "hdr_tex", "ldr_tex"):
            t = getattr(self, name, None)
            if t is not None:
                t.release()
        near = (moderngl.NEAREST, moderngl.NEAREST)
        self.color_tex = ctx.texture((w, h), 4, dtype="f2")
        self.normal_tex = ctx.texture((w, h), 4, dtype="f2")
        self.normal_tex.filter = near
        self.id_tex = ctx.texture((w, h), 1, dtype="f4")
        self.id_tex.filter = near
        self.depth_tex = ctx.depth_texture((w, h))
        self.depth_tex.compare_func = ""
        self.depth_tex.filter = near
        self.gbuffer = ctx.framebuffer([self.color_tex, self.normal_tex, self.id_tex], self.depth_tex)

        self.mask_tex = ctx.texture((w, h), 1, dtype="f1")
        self.mask_tex.filter = near
        self.mask_depth = ctx.depth_texture((w, h))
        self.mask_depth.compare_func = ""
        self.mask_depth.filter = near
        self.mask_fbo = ctx.framebuffer([self.mask_tex], self.mask_depth)

        self.ao_tex = ctx.texture((w, h), 1, dtype="f1")
        self.ao_fbo = ctx.framebuffer([self.ao_tex])
        self.blur_tex = ctx.texture((w, h), 1, dtype="f1")
        self.blur_fbo = ctx.framebuffer([self.blur_tex])

        self.hdr_tex = ctx.texture((w, h), 4, dtype="f1")
        self.hdr_fbo = ctx.framebuffer([self.hdr_tex], self.depth_tex)
        self.ldr_tex = ctx.texture((w, h), 4, dtype="f1")
        self.ldr_fbo = ctx.framebuffer([self.ldr_tex])
        self.frame_ok = False

    # ------------------------------------------------------------------ frame
    @staticmethod
    def _set(prog, name, value):
        if name in prog:
            prog[name].value = value

    @staticmethod
    def _rgb(settings, key, default):
        c = QColor(settings.get(key, default))
        return (c.redF(), c.greenF(), c.blueF())

    def _set_geometry_uniforms(self, prog, vp, view, eye, key, fill, settings, clip):
        if "u_viewproj" in prog:
            prog["u_viewproj"].write(_mat4_bytes(vp))
        if "u_view3" in prog:
            prog["u_view3"].write(np.asarray(view[:3, :3], dtype="f4").T.tobytes())
        self._set(prog, "u_state", 0)
        self._set(prog, "u_mats", 1)
        self._set(prog, "u_detail", self.detail)
        self._set(prog, "u_textured", int(self.textured))
        self._set(prog, "u_albedo", ALBEDO_UNIT)
        self._set(prog, "u_color_row", 1 if settings.get("color_mode") == 1 else 0)
        self._set(prog, "u_ghost_alpha", float(settings.get("ghost_alpha", 0.1)))
        self._set(prog, "u_eye", tuple(eye))
        self._set(prog, "u_light_key", tuple(key))
        self._set(prog, "u_light_fill", tuple(fill))
        self._set(prog, "u_sel_color", tuple(float(x) for x in srgb_to_linear(self._rgb(settings, "selection_color", "#4dc7ff"))))
        self._set(prog, "u_hover_color", tuple(float(x) for x in srgb_to_linear(self._rgb(settings, "hover_color", "#ffd966"))))
        planes, on = clip[0], clip[1]
        for i in range(3):
            self._set(prog, f"u_clip{i}", tuple(planes[i]))
        self._set(prog, "u_clip_on", tuple(int(x) for x in on))
        self._set(prog, "u_clip_mode", int(clip[2]) if len(clip) > 2 else 0)

    def render(self, target, camera, settings, clip, hover_id=-1, has_selection=False):
        ctx = self.ctx
        w, h = self.size
        if w < 2 or h < 2:
            return
        aspect = w / h
        view = camera.view()
        proj = camera.proj(aspect)
        vp = proj @ view
        self.last_vp = vp
        self.last_proj = proj
        eye = camera.eye()
        right, up, back = camera.basis()
        key = _normalize(-right * 0.55 + up * 0.75 + back * 0.80)
        fill = _normalize(right * 0.80 - up * 0.20 + back * 0.45)

        ctx.disable(moderngl.BLEND | moderngl.CULL_FACE)
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.depth_func = "<"
        self.state_tex.use(0)
        self.mats_tex.use(1)
        self.albedo.use(ALBEDO_UNIT)

        # 1. opaque geometry -> color / normal / id / depth
        self.gbuffer.use()
        self.gbuffer.depth_mask = True
        self.gbuffer.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        self._set_geometry_uniforms(self.p_opaque, vp, view, eye, key, fill, settings, clip)
        self._set(self.p_opaque, "u_pass", 0)
        self.vao_opaque.render(moderngl.TRIANGLES)

        # 2. selection mask (selected structures, depth-tested only among themselves)
        if has_selection:
            self.mask_fbo.use()
            self.mask_fbo.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
            self._set_geometry_uniforms(self.p_mask, vp, view, eye, key, fill, settings, clip)
            self._set(self.p_mask, "u_pass", 2)
            self.vao_mask.render(moderngl.TRIANGLES)

        ctx.disable(moderngl.DEPTH_TEST)

        # 3. ambient occlusion
        ao_on = bool(settings.get("ssao", True))
        if ao_on:
            self.ao_fbo.use()
            self.depth_tex.use(0)
            self.normal_tex.use(1)
            self.noise_tex.use(2)
            p = self.p_ssao
            self._set(p, "u_depth", 0)
            self._set(p, "u_normal", 1)
            self._set(p, "u_noise", 2)
            p["u_proj"].write(_mat4_bytes(proj))
            p["u_inv_proj"].write(_mat4_bytes(np.linalg.inv(proj)))
            p["u_kernel"].write(self.kernel.tobytes())
            # microanatomy models are the same size on screen as a whole body but their features are a
            # hundred times finer, so the sampling radius has to shrink with them or the relief reads flat
            k = 0.010 if self.detail else 0.035
            self._set(p, "u_radius", float(np.clip(camera.distance * k, 0.0015, 0.06)))
            self._set(p, "u_noise_scale", (w / 4.0, h / 4.0))
            self.fs["ssao"].render(vertices=3)
            self.blur_fbo.use()
            self.ao_tex.use(0)
            self._set(self.p_blur, "u_src", 0)
            self._set(self.p_blur, "u_texel", (1.0 / w, 1.0 / h))
            self.fs["blur"].render(vertices=3)

        # 4. composite opaque + AO + background into display space
        dark = settings.get("dark_background", True)
        top, bottom = BACKGROUND_DARK if dark else BACKGROUND_LIGHT
        if settings.get("custom_background"):
            top, bottom = self._rgb(settings, "bg_top", "#1d2127"), self._rgb(settings, "bg_bottom", "#090a0d")
        self.hdr_fbo.use()
        self.color_tex.use(0)
        self.blur_tex.use(1)
        self.depth_tex.use(2)
        p = self.p_composite
        self._set(p, "u_color", 0)
        self._set(p, "u_ao", 1)
        self._set(p, "u_depth", 2)
        self._set(p, "u_bg_top", top)
        self._set(p, "u_bg_bottom", bottom)
        self._set(p, "u_ao_strength", float(settings.get("ssao_strength", 1.0)))
        self._set(p, "u_ao_on", int(ao_on))
        self.fs["composite"].render(vertices=3)

        # 5. transparent / ghosted geometry blended on top, depth-tested against opaque
        ctx.enable(moderngl.DEPTH_TEST | moderngl.BLEND | moderngl.CULL_FACE)
        ctx.cull_face = "back"
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.hdr_fbo.depth_mask = False
        self.state_tex.use(0)
        self.mats_tex.use(1)
        self.albedo.use(ALBEDO_UNIT)
        self._set_geometry_uniforms(self.p_transparent, vp, view, eye, key, fill, settings, clip)
        self._set(self.p_transparent, "u_pass", 1)
        self.vao_transparent.render(moderngl.TRIANGLES)
        self.hdr_fbo.depth_mask = True
        ctx.disable(moderngl.DEPTH_TEST | moderngl.BLEND | moderngl.CULL_FACE)

        # 6. outlines
        self.ldr_fbo.use()
        self.hdr_tex.use(0)
        self.mask_tex.use(1)
        self.mask_depth.use(2)
        self.depth_tex.use(3)
        self.id_tex.use(4)
        p = self.p_final
        for name, unit in (("u_hdr", 0), ("u_mask", 1), ("u_mask_depth", 2), ("u_depth", 3), ("u_id", 4)):
            self._set(p, name, unit)
        self._set(p, "u_texel", (1.0 / w, 1.0 / h))
        show_hover = hover_id >= 0 and settings.get("hover_outline", True)
        self._set(p, "u_hover_id", float(hover_id + 1) if show_hover else 0.0)
        self._set(p, "u_sel_color", self._rgb(settings, "selection_color", "#4dc7ff"))
        self._set(p, "u_hover_color", self._rgb(settings, "hover_color", "#ffd966"))
        self._set(p, "u_has_selection", int(has_selection))
        self.fs["final"].render(vertices=3)

        # 7. FXAA to the window
        target.use()
        sw, sh = self.screen_size or (w, h)
        target.viewport = (0, 0, sw, sh)
        self.ldr_tex.use(0)
        self._set(self.p_fxaa, "u_src", 0)
        self._set(self.p_fxaa, "u_texel", (1.0 / w, 1.0 / h))
        self._set(self.p_fxaa, "u_enabled", int(settings.get("fxaa", True)))
        self.fs["fxaa"].render(vertices=3)
        self.frame_ok = True

    # ------------------------------------------------------------------ queries
    def pick(self, x, y):
        w, h = self.size
        if not self.frame_ok or not (0 <= x < w and 0 <= y < h):
            return -1
        data = self.gbuffer.read(viewport=(x, y, 1, 1), components=1, attachment=2, dtype="f4")
        return int(round(struct.unpack("f", data)[0])) - 1

    def world_at(self, x, y):
        w, h = self.size
        if not self.frame_ok or not (0 <= x < w and 0 <= y < h):
            return None
        data = self.gbuffer.read(viewport=(x, y, 1, 1), components=1, attachment=-1, dtype="f4")
        d = struct.unpack("f", data)[0]
        if d >= 1.0:
            return None
        ndc = np.array([(x + 0.5) / w * 2 - 1, (y + 0.5) / h * 2 - 1, d * 2 - 1, 1.0])
        p = np.linalg.inv(self.last_vp) @ ndc
        return p[:3] / p[3]

    def depths_at(self, points):
        """Depth buffer values at pixel positions [(x, y), ...] (GL coordinates)."""
        out = []
        w, h = self.size
        for x, y in points:
            if not self.frame_ok or not (0 <= x < w and 0 <= y < h):
                out.append(None)
                continue
            data = self.gbuffer.read(viewport=(int(x), int(y), 1, 1), components=1, attachment=-1, dtype="f4")
            out.append(struct.unpack("f", data)[0])
        return out
