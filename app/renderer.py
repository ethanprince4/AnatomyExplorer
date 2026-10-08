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
FORMAT_SIZE = {"3f": 12, "2f": 8, "1f": 4, "u2": 2, "4f1": 4, "4f2": 8}
ALBEDO_UNIT = 5
PARITY_UNIT = 6
ANIM_UNIT = 10


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
        # cap_depth: cut faces are drawn on the cutting plane in a pass of their own (_draw_caps) instead of on
        # the far wall of each part, so whatever a part encloses is hidden behind its section as in a real slice
        self.cap_depth = cap_depth
        self.p_cap = self.p_parity = self.p_capmix = None
        structs = ds.structures
        noclip = getattr(ds, "noclip_mask", np.zeros(len(structs), dtype=bool))
        self.cap_sids = np.array([i for i, st in enumerate(structs) if not noclip[i] and st["i_count"]], dtype=int)
        self.cap_parts = [(structs[i]["i_start"], structs[i]["i_count"]) for i in self.cap_sids]
        self._state_flags = np.zeros(len(structs), dtype=np.int32)
        self.last_cap_candidate_count = 0
        if cap_depth:
            opaque_fs = opaque_fs.replace("#version 410 core", "#version 410 core\n#define CAP_DEPTH 1", 1)
            self.p_cap = ctx.program(vertex_shader=shaders.GEOMETRY_VS, fragment_shader=opaque_fs.replace(
                "#version 410 core", "#version 410 core\n#define CAP_PASS 1", 1))
            self.p_parity = ctx.program(vertex_shader=shaders.GEOMETRY_VS, fragment_shader=shaders.PARITY_FS)
            self.p_capmix = ctx.program(vertex_shader=shaders.FULLSCREEN_VS, fragment_shader=shaders.CAPMIX_FS)
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
        # an animated micro model adds a third buffer: morph targets and a phase per vertex (micro/anim.py); each
        # frame then only rewrites the small per-part texture of weights and glows
        from .micro.anim import ANIM_ATTRS, ANIM_FORMAT
        self.animated = hasattr(ds, "anim_bytes")
        self.anim = ctx.buffer(ds.anim_bytes()) if self.animated else None
        self.anim_t = 0.0
        self.anim_tex = ctx.texture((max(len(ds.structures), 1), 2), 4, dtype="f4")
        self.anim_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self.set_animation(np.zeros((2, max(len(ds.structures), 1), 4), np.float32), 0.0)   # the rest pose

        def geo_vao(prog):
            buffers = [(self.vbo, self._format_for(prog), *[a for a in VERTEX_ATTRS if a in prog])]
            if self.aux is not None and any(a in prog for a in AUX_ATTRS):
                buffers.append((self.aux, self._format_for(prog, AUX_FORMAT, AUX_ATTRS),
                                *[a for a in AUX_ATTRS if a in prog]))
            if self.anim is not None and any(a in prog for a in ANIM_ATTRS):
                buffers.append((self.anim, self._format_for(prog, ANIM_FORMAT, ANIM_ATTRS),
                                *[a for a in ANIM_ATTRS if a in prog]))
            return ctx.vertex_array(prog, buffers, index_buffer=self.ibo, index_element_size=4)

        self._geo_vao = geo_vao
        self.vao_opaque = geo_vao(self.p_opaque)
        self.vao_transparent = geo_vao(self.p_transparent)
        self.vao_mask = geo_vao(self.p_mask)
        self.vao_cap = geo_vao(self.p_cap) if cap_depth else None
        self.vao_parity = geo_vao(self.p_parity) if cap_depth else None
        self.capmix_vao = ctx.vertex_array(self.p_capmix, []) if cap_depth else None
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
        self.last_slice_plane = None
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
        objs = [self.vao_opaque, self.vao_transparent, self.vao_mask, self.vao_cap, self.vao_parity, self.p_cap,
                self.p_parity, self.p_capmix, getattr(self, "capmix_vao", None), *self.fs.values(),
                self.p_opaque, self.p_transparent, self.p_mask, self.p_ssao, self.p_blur, self.p_composite,
                self.p_final, self.p_fxaa, self.vbo, self.ibo, self.aux, self.anim, self.state_tex, self.mats_tex,
                self.anim_tex, self.noise_tex, self.albedo]
        objs += [getattr(self, n, None) for n in ("gbuffer", "mask_fbo", "ao_fbo", "blur_fbo", "hdr_fbo", "ldr_fbo",
                                                  "color_tex", "normal_tex", "id_tex", "depth_tex", "mask_tex",
                                                  "mask_depth", "ao_tex", "blur_tex", "hdr_tex", "ldr_tex",
                                                  "parity_fbo", "parity_tex", "cap_fbo", "cap_color", "cap_normal",
                                                  "cap_id", "cap_zp", "cap_key")]
        for o in objs:
            if o is not None:
                try:
                    o.release()
                except Exception:           # noqa: BLE001 - already gone with its context
                    pass

    def update_state(self, tex):
        self._state_texture = np.asarray(tex, dtype=np.float32).copy()
        self._state_flags = np.asarray(tex[0, :len(self.ds.structures), 3], dtype=np.int32).copy()
        self.state_tex.write(np.ascontiguousarray(tex, dtype=np.float32).tobytes())

    _CAP_OBJECTS = ("vao_cap", "vao_parity", "capmix_vao", "p_cap", "p_parity", "p_capmix")
    _CAP_TARGETS = ("parity_fbo", "cap_fbo", "parity_tex", "cap_color", "cap_normal", "cap_id", "cap_zp", "cap_key")
    _TARGETS = ("gbuffer", "mask_fbo", "ao_fbo", "blur_fbo", "hdr_fbo", "ldr_fbo",
                "color_tex", "normal_tex", "id_tex", "depth_tex", "mask_tex", "mask_depth",
                "ao_tex", "blur_tex", "hdr_tex", "ldr_tex") + _CAP_TARGETS

    def _release_owned(self, names):
        """Retire ownership first and attempt every release, even after context loss."""
        objects = [getattr(self, name, None) for name in names]
        for name in names:
            setattr(self, name, None)
        for obj in objects:
            if obj is not None:
                try:
                    obj.release()
                except Exception:
                    pass

    def _ensure_slice_caps(self):
        """Create true-plane cap resources on demand, leaving ordinary atlas sections unchanged."""
        if self.p_cap is not None:
            return
        self.frame_ok = False
        try:
            self.p_cap = self.ctx.program(vertex_shader=shaders.GEOMETRY_VS,
                                         fragment_shader=shaders.OPAQUE_FS.replace(
                                             "#version 410 core",
                                             "#version 410 core\n#define CAP_DEPTH 1\n#define CAP_PASS 1", 1))
            self.p_parity = self.ctx.program(vertex_shader=shaders.GEOMETRY_VS, fragment_shader=shaders.PARITY_FS)
            self.p_capmix = self.ctx.program(vertex_shader=shaders.FULLSCREEN_VS, fragment_shader=shaders.CAPMIX_FS)
            self.vao_cap = self._geo_vao(self.p_cap)
            self.vao_parity = self._geo_vao(self.p_parity)
            self.capmix_vao = self.ctx.vertex_array(self.p_capmix, [])
            if min(self.size) > 0:
                self._create_cap_targets(*self.size)
        except Exception:
            self._release_owned(self._CAP_OBJECTS + self._CAP_TARGETS)
            raise

    def _create_cap_targets(self, w, h):
        ctx = self.ctx
        near = (moderngl.NEAREST, moderngl.NEAREST)
        self.parity_tex = ctx.texture((w, h), 1, dtype="f4")
        self.parity_tex.filter = near
        self.parity_fbo = ctx.framebuffer([self.parity_tex])
        self.cap_color = ctx.texture((w, h), 4, dtype="f2")
        self.cap_normal = ctx.texture((w, h), 4, dtype="f2")
        self.cap_id = ctx.texture((w, h), 1, dtype="f4")
        self.cap_zp = ctx.texture((w, h), 1, dtype="f4")
        for t in (self.cap_color, self.cap_normal, self.cap_id, self.cap_zp):
            t.filter = near
        self.cap_key = ctx.depth_texture((w, h))
        self.cap_fbo = ctx.framebuffer([self.cap_color, self.cap_normal, self.cap_id, self.cap_zp], self.cap_key)

    def _slice_candidates(self, plane):
        """Visible, clippable structures whose AABB actually intersects the section plane."""
        ids = self.cap_sids
        lo, hi = self.ds.bbox_min[ids], self.ds.bbox_max[ids]
        normal = np.asarray(plane[:3], dtype=float)
        center = (lo + hi) * 0.5
        radius = ((hi - lo) * 0.5) @ np.abs(normal)
        distance = center @ normal + float(plane[3])
        intersect = np.abs(distance) <= radius + 1e-7 * np.linalg.norm(normal)
        return intersect & ((self._state_flags[ids] & 1) != 0)

    def set_animation(self, frame, t):
        """One animation frame: the per-part texels from Animation.frame and the cycle phase t (0..1)."""
        self.anim_tex.write(np.ascontiguousarray(frame, dtype=np.float32).tobytes())
        self.anim_t = float(t) % 1.0

    # ------------------------------------------------------------------ targets
    def resize(self, w, h):
        w, h = max(int(w), 1), max(int(h), 1)
        if (w, h) == self.size:
            return
        self.frame_ok = False
        self.size = (0, 0)
        self._release_owned(self._TARGETS)
        ctx = self.ctx
        try:
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
            if self.p_cap is not None:
                self._create_cap_targets(w, h)

            self.ao_tex = ctx.texture((w, h), 1, dtype="f1")
            self.ao_fbo = ctx.framebuffer([self.ao_tex])
            self.blur_tex = ctx.texture((w, h), 1, dtype="f1")
            self.blur_fbo = ctx.framebuffer([self.blur_tex])

            self.hdr_tex = ctx.texture((w, h), 4, dtype="f1")
            self.hdr_fbo = ctx.framebuffer([self.hdr_tex], self.depth_tex)
            self.ldr_tex = ctx.texture((w, h), 4, dtype="f1")
            self.ldr_fbo = ctx.framebuffer([self.ldr_tex])
        except Exception:
            self._release_owned(self._TARGETS)
            raise
        self.size = (w, h)

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
        self._set(prog, "u_anim", int(self.animated))
        self._set(prog, "u_anim_t", self.anim_t)
        self._set(prog, "u_anim_tex", ANIM_UNIT)
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

    def _slice_cap_domains(self, parts):
        """The verified atlas stomach wall shares one outer/inner front-depth domain.

        Only true radiology sections call this helper. Hidden lining still bounds
        the hollow wall. A single visible member owns all wall cap pixels.
        Other parts and model datasets retain independent cap domains.
        """
        structs = self.ds.structures
        pair = (2158, 3235)
        expected = ("Mucosa of stomach", "Stomach")
        if len(structs) <= pair[1] or any(
                structs[sid].get("id") != sid or structs[sid].get("raw") != name
                for sid, name in zip(pair, expected)):
            return [([part], [part], ()) for part in parts]
        boundaries = [(structs[sid]["i_start"], structs[sid]["i_count"]) for sid in pair]
        visible_members = [part for part in parts if part in boundaries]
        if not visible_members:
            return [([part], [part], ()) for part in parts]
        domains = []
        grouped = False
        for part in parts:
            if part in boundaries:
                if not grouped:
                    domains.append((boundaries, visible_members, pair))
                    grouped = True
            else:
                domains.append(([part], [part], ()))
        return domains

    def _draw_caps(self, vp, view, eye, key, fill, settings, clip, slice_only=False):
        """Cut faces on the plane, part by part. First the part's nearest kept front face at each pixel; then its
        back faces that nothing of the same part hides - where the first surface of the part behind the cut is a
        back face, the plane passes through the part (unlike counting surfaces, this holds for parts whose meshes
        are not watertight). They are gathered off-screen, keyed on how far the part's far wall lies behind the
        plane so the innermost part wins where several meet, and finally laid onto the scene on the plane."""
        ctx = self.ctx
        for prog in (self.p_parity, self.p_cap):
            self._set_geometry_uniforms(prog, vp, view, eye, key, fill, settings, clip)
            # A radiology cut represents all visible tissue, including transparent tissue.
            self._set(prog, "u_pass", 3 if slice_only else 0)
        self._set(self.p_cap, "u_parity", PARITY_UNIT)
        if "u_inv_viewproj" in self.p_cap:
            self.p_cap["u_inv_viewproj"].write(_mat4_bytes(np.linalg.inv(vp)))
        self._set(self.p_cap, "u_viewport", tuple(float(x) for x in self.size))
        self._set(self.p_cap, "u_slice_only", int(slice_only))
        if slice_only:
            index = next(i for i, on in enumerate(clip[1]) if on)
            plane = np.linalg.inv(vp).T @ np.asarray(clip[0][index], dtype=float)
            plane /= max(np.max(np.abs(plane)), 1e-12)
            self._set(self.p_cap, "u_slice_ndc_plane", tuple(plane))
        self.parity_tex.use(PARITY_UNIT)
        self.cap_fbo.use()
        self.cap_fbo.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        parts = self.cap_parts
        if slice_only:
            plane = clip[0][next(i for i, on in enumerate(clip[1]) if on)]
            parts = [part for part, keep in zip(parts, self._slice_candidates(plane)) if keep]
        self.last_cap_candidate_count = len(parts)
        domains = self._slice_cap_domains(parts) if slice_only else [([part], [part], ()) for part in parts]
        for boundaries, visible_members, boundary_sids in domains:
            self.parity_fbo.use()
            self.parity_fbo.clear(1.0, 1.0, 1.0, 1.0)
            ctx.disable(moderngl.DEPTH_TEST)
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = moderngl.ONE, moderngl.ONE
            ctx.blend_equation = moderngl.MIN
            restored = []
            try:
                for sid in boundary_sids:
                    if not self._state_flags[sid] & 1:
                        original = self._state_texture[0, sid].copy()
                        temporary = original.copy()
                        temporary[3] = int(temporary[3]) | 1
                        self.state_tex.write(temporary.tobytes(), viewport=(sid, 0, 1, 1))
                        restored.append((sid, original))
                for first, count in boundaries:
                    self.vao_parity.render(moderngl.TRIANGLES, vertices=count, first=first)
            finally:
                # Restore exact flags/colours before coloured caps and all later passes.
                for sid, original in restored:
                    self.state_tex.write(original.tobytes(), viewport=(sid, 0, 1, 1))
            ctx.blend_equation = moderngl.FUNC_ADD
            ctx.disable(moderngl.BLEND)
            ctx.enable(moderngl.DEPTH_TEST)
            self.cap_fbo.use()
            cap_members = visible_members
            owner = None
            if boundary_sids and len(visible_members) == 1:
                # The hidden boundary also supplies the opposite wall exit.
                # Attribute that geometric cap to the visible anatomical layer.
                cap_members = boundaries
                owner = boundary_sids[boundaries.index(visible_members[0])]
            try:
                for first, count in cap_members:
                    hidden_geometry = owner is not None and (first, count) not in visible_members
                    self._set(self.p_cap, "u_cap_owner_plus_one", owner + 1 if hidden_geometry else 0)
                    self._set(self.p_cap, "u_cap_material_plus_one",
                              self.ds.structures[owner]["material"] + 1 if hidden_geometry else 0)
                    self.vao_cap.render(moderngl.TRIANGLES, vertices=count, first=first)
            finally:
                self._set(self.p_cap, "u_cap_owner_plus_one", 0)
                self._set(self.p_cap, "u_cap_material_plus_one", 0)
        self.gbuffer.use()
        for i, (name, tex) in enumerate((("u_cap_color", self.cap_color), ("u_cap_normal", self.cap_normal),
                                         ("u_cap_id", self.cap_id), ("u_cap_zp", self.cap_zp))):
            tex.use(PARITY_UNIT + i)
            self._set(self.p_capmix, name, PARITY_UNIT + i)
        self.capmix_vao.render(moderngl.TRIANGLES, vertices=3)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

    def render(self, target, camera, settings, clip, hover_id=-1, has_selection=False, radiology_slice=False):
        self.frame_ok = False
        ctx = self.ctx
        w, h = self.size
        if w < 2 or h < 2:
            return
        aspect = w / h
        view = camera.view()
        proj = camera.proj(aspect)
        # Keep CPU picking consistent with the matrix actually uploaded to OpenGL.
        vp = np.asarray(proj @ view, dtype=np.float32).astype(np.float64)
        self.last_vp = vp
        self.last_proj = proj
        eye = camera.eye()
        self.last_eye = np.asarray(eye, dtype=float).copy()
        self.last_slice_plane = None
        slice_only = bool(radiology_slice) and sum(bool(on) for on in clip[1]) == 1
        if slice_only:
            self._ensure_slice_caps()
            # A section has no retained side. Orient the cap calculation towards the camera
            # so either view direction/flip resolves the same physical cutting plane.
            planes = list(clip[0])
            index = next(i for i, on in enumerate(clip[1]) if on)
            plane = np.asarray(planes[index], dtype=float)
            if float(plane[:3] @ eye + plane[3]) >= 0.0:
                plane = -plane
            planes[index] = tuple(plane)
            self.last_slice_plane = plane.copy()
            clip = (planes, clip[1], 0)
        right, up, back = camera.basis()
        key = _normalize(-right * 0.55 + up * 0.75 + back * 0.80)
        fill = _normalize(right * 0.80 - up * 0.20 + back * 0.45)

        ctx.disable(moderngl.BLEND | moderngl.CULL_FACE)
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.depth_func = "<"
        self.state_tex.use(0)
        self.mats_tex.use(1)
        self.albedo.use(ALBEDO_UNIT)
        self.anim_tex.use(ANIM_UNIT)

        # 1. opaque geometry -> color / normal / id / depth
        self.gbuffer.use()
        self.gbuffer.depth_mask = True
        self.gbuffer.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        self._set_geometry_uniforms(self.p_opaque, vp, view, eye, key, fill, settings, clip)
        self._set(self.p_opaque, "u_pass", 0)
        if not slice_only:
            self.vao_opaque.render(moderngl.TRIANGLES)
        if (self.cap_depth or slice_only) and any(clip[1]):
            self._draw_caps(vp, view, eye, key, fill, settings, clip, slice_only=slice_only)

        # 2. selection mask (selected structures, depth-tested only among themselves)
        if has_selection and not slice_only:
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
        if not slice_only:
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
        self._set(p, "u_has_selection", int(has_selection and not slice_only))
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
    def _read_float(self, x, y, attachment):
        # read() allocates uninitialized bytes. A driver/context read failure
        # must never turn reused memory into a valid anatomy ID (or world point).
        # RGBA color readback also avoids single-channel readback quirks on GL
        # drivers; the ID remains in R even though the texture is single-channel.
        components = 1 if attachment == -1 else 4
        pixel = np.full(components, np.nan, dtype=np.float32)
        # Apple's FIXED_ONLY readback can clamp float IDs when the normalized
        # output target is active as ModernGL sets the clamp mode. Bind our
        # floating gbuffer first, then restore the caller's render state.
        previous_fbo = self.ctx.fbo
        previous_viewport = self.ctx.viewport
        if previous_fbo is None:
            return None  # no restorable render target; fail closed
        try:
            self.gbuffer.use()
            self.gbuffer.read_into(pixel, viewport=(int(x), int(y), 1, 1),
                                   components=components, attachment=attachment, dtype="f4")
        except moderngl.Error:
            return None
        finally:
            previous_fbo.use()
            self.ctx.viewport = previous_viewport
        value = float(pixel[0])
        return value if np.isfinite(value) else None

    def read_id_image(self, step=1):
        """Structure id + 1 at every step-th pixel of the last frame (rows bottom-up, 0 = nothing), or None."""
        if not self.frame_ok:
            return None
        w, h = self.size
        previous_fbo = self.ctx.fbo
        previous_viewport = self.ctx.viewport
        if previous_fbo is None:
            return None
        try:
            self.gbuffer.use()
            data = self.gbuffer.read(components=1, attachment=2, dtype="f4")
        except moderngl.Error:
            return None
        finally:
            previous_fbo.use()
            self.ctx.viewport = previous_viewport
        ids = np.frombuffer(data, dtype=np.float32)
        if ids.size != w * h:
            return None
        ids = np.nan_to_num(ids.reshape(h, w)[::step, ::step], nan=0.0)
        ids = np.rint(ids).astype(np.int32)
        ids[(ids < 1) | (ids > self.ds.n)] = 0
        return ids

    def pick(self, x, y):
        w, h = self.size
        if not self.frame_ok or not (0 <= x < w and 0 <= y < h):
            return -1
        value = self._read_float(x, y, 2)
        if value is None or value < 1 or value > self.ds.n or abs(value - round(value)) > 0.001:
            return -1
        return int(round(value)) - 1

    def world_at(self, x, y):
        w, h = self.size
        if not self.frame_ok or not (0 <= x < w and 0 <= y < h):
            return None
        d = self._read_float(x, y, -1)
        if d is None or not (0 <= d < 1.0):
            return None
        ndc = np.array([(x + 0.5) / w * 2 - 1, (y + 0.5) / h * 2 - 1, d * 2 - 1, 1.0])
        p = np.linalg.inv(self.last_vp) @ ndc
        point = p[:3] / p[3]
        if self.last_slice_plane is not None:
            # Every drawable pixel in this mode is a cap on this physical plane.
            # Intersect the pixel ray analytically instead of returning depth-quantization drift.
            plane = self.last_slice_plane
            ray = point - self.last_eye
            denominator = float(plane[:3] @ ray)
            if abs(denominator) < 1e-12:
                return None
            t = -float(plane[:3] @ self.last_eye + plane[3]) / denominator
            point = self.last_eye + t * ray
        return point

    def depths_at(self, points):
        """Depth buffer values at pixel positions [(x, y), ...] (GL coordinates)."""
        out = []
        w, h = self.size
        for x, y in points:
            if not self.frame_ok or not (0 <= x < w and 0 <= y < h):
                out.append(None)
                continue
            d = self._read_float(x, y, -1)
            out.append(d if d is not None and 0 <= d <= 1 else None)
        return out
