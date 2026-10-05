"""The model viewer's renderer (moderngl). Usable in any QOpenGLWidget or a standalone context.

    r = Renderer(ctx)
    r.set_model(model)
    r.render(target_fbo, (w, h), camera, settings, frame_state)
    item, world_point, on_cut_face = r.pick(x, y)      # from the last frame's pre-pass

Frame: shadow maps (key, fill, rim; camera-relative like the harness rig) -> pre-pass (view normal, linear depth,
item id and flags) -> cut faces (per cut item: parity and cap, then laid into the pre-pass) -> SSAO + depth-aware
blur -> MSAA forward (backdrop, opaque GGX/IBL/tissue term/procedural stripes, cut faces) -> MSAA weighted-blended
OIT (translucent and x-rayed parts) -> resolve -> composite (outlines, Khronos PBR Neutral, sRGB) [-> scaled blit].

What the viewer shows - which items are visible, x-rayed, selected, hovered or recoloured, the cut-away and the
cross-sections, the separated layers and the animation - comes in a FrameState each frame, so the model itself
is never modified for it.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

import moderngl
import numpy as np

from . import shaders
from .environment import Environment
from .model import NO_FIBRE, Part, ViewerModel

FMT = "3f 3f 3f 3f 1f 4f 2f"
ATTRS = ("in_pos", "in_nrm", "in_dpos", "in_dnrm", "in_fib", "in_col", "in_uv")
ANIM_FMT = "4f2 4f2 4f2 4f2 1f"
ANIM_ATTRS = ("in_m0", "in_m1", "in_m2", "in_m3", "in_phase")


STATIC_FMT = "3f 3f"
STATIC_ATTRS = ("in_pos", "in_nrm")
_STATIC_TAIL = np.array([0.0] * 6 + [NO_FIBRE] + [1.0] * 4 + [0.0] * 2, dtype=np.float32)
_STATIC_TAIL_BITS = _STATIC_TAIL.view(np.uint32)


def _can_compact_vertices(model):
    """Only compact static procedural inputs whose omitted columns match shader constants bit for bit."""
    if getattr(model, "kind", None) != "procedural":
        return False
    source = getattr(model, "source", None)
    if getattr(source, "id", None) in {"heart", "whole_heart", "cardiac_muscle"}:
        return False
    if (model.anim_vertices is not None or getattr(model, "animation", None) is not None
            or getattr(source, "animation", None) is not None or getattr(model, "clip", None) is not None):
        return False
    if any(p.has_morph for p in model.parts):
        return False
    vertices = model.vertices
    if (not isinstance(vertices, np.ndarray) or vertices.dtype != np.float32
            or vertices.ndim != 2 or vertices.shape[1] != 19 or len(vertices) == 0):
        return False
    # Bound temporary comparisons; a large model does not need another full-sized boolean array.
    for start in range(0, len(vertices), 131072):
        if not np.all(vertices[start:start + 131072, 6:].view(np.uint32) == _STATIC_TAIL_BITS):
            return False
    return True


def _static_geometry_shader():
    """Specialize a private source copy; full programs and the shared shader module retain their inputs."""
    source = shaders.GEOM_VS
    constants = (
        ("in vec3 in_dpos;", "const vec3 in_dpos = vec3(0.0);"),
        ("in vec3 in_dnrm;", "const vec3 in_dnrm = vec3(0.0);"),
        ("in float in_fib;", f"const float in_fib = {float(_STATIC_TAIL[6])!r};"),
        ("in vec4 in_col;", "const vec4 in_col = vec4(1.0);"),
        ("in vec2 in_uv;", "const vec2 in_uv = vec2(0.0);"),
    )
    for declaration, constant in constants:
        if source.count(declaration) != 1:
            raise ValueError("Unsupported geometry shader input declaration: " + declaration)
        source = source.replace(declaration, constant)
    return source


DEFAULT_RIG = [  # the harness rig (trial/harness/config.json stage.lights)
    {"name": "key", "azimuth_deg": 40.0, "elevation_deg": 35.0, "size_factor": 0.35, "energy": 15.0, "colour": [1, 1, 1]},
    {"name": "fill", "azimuth_deg": -55.0, "elevation_deg": 10.0, "size_factor": 0.6, "energy": 5.0, "colour": [1, 1, 1]},
    {"name": "rim", "azimuth_deg": 165.0, "elevation_deg": 40.0, "size_factor": 0.3, "energy": 10.0, "colour": [1, 1, 1]},
]
DEFAULT_WORLD = {"top_hex": "#20242b", "bottom_hex": "#12141a", "ambient_colour": [0.5, 0.5, 0.5], "ambient_strength": 0.3}


def srgb_hex_to_linear(h):
    return [srgb_to_linear_1(int(h[i:i + 2], 16) / 255.0) for i in (1, 3, 5)]


def srgb_to_linear_1(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def backdrop_linear(colour, neutral=True):
    """Scene-linear colour that Khronos PBR Neutral displays as ``colour`` (a hex string or an sRGB triple) - the
    harness's toe compensation."""
    t = srgb_hex_to_linear(colour) if isinstance(colour, str) else [srgb_to_linear_1(float(c)) for c in colour]
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
    shadow_soft: float = 2.0           # Cycles' area lights are large (0.3-0.6 x the light distance)
    outline: tuple = (1.0, 0.86, 0.35)          # selection outline (sRGB)
    hover_outline: tuple = (0.75, 0.85, 1.0)
    highlight: tuple = (1.0, 0.85, 0.45)        # selection tint (linear)
    hover_highlight: tuple = (0.75, 0.85, 1.0)
    hover_outline_on: bool = True
    ghost_alpha: float = 0.10
    background: tuple | None = None    # ((top sRGB), (bottom sRGB)); None: the model's own backdrop
    selected: int = 0                  # an item id + 1 (the standalone tools select one part this way)
    hovered: int = 0
    extra: dict = field(default_factory=dict)


@dataclass
class FrameState:
    """What the viewer shows this frame, per item (arrays are indexed by item)."""
    visible: np.ndarray | None = None
    ghost: np.ndarray | None = None
    alpha: np.ndarray | None = None               # opacity multiplier (the tissue opacity slider)
    selected: frozenset = frozenset()
    hovered: int = -1
    override: dict = field(default_factory=dict)  # item -> linear RGB (practice marks, custom colours)
    colours: np.ndarray | None = None             # (n, 3) linear flat colours of a colour mode, or None
    clip_planes: tuple = ((0.0, 1.0, 0.0, 0.0),) * 3
    clip_on: tuple = (False, False, False)
    clip_mode: int = 0
    opaque_materials: bool = False             # display override; authored Looks stay unchanged
    anim_t: float = 0.0
    anim_frame: np.ndarray | None = None          # (2, n, 4): morph weights, (mode, glow, decay, rate)


def _transparent_pass(part, ghost, alpha, frame):
    return ghost or alpha < 0.999 or (not frame.opaque_materials and
        (part.role == "covering" or part.look.translucent))


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
        if data is not None:
            u.write(data)
        else:
            u.value = value
        self.cache[name] = key             # only a successful upload is reusable

    def reset(self):
        self.cache.clear()


def _frustum_planes(vp):
    m = vp
    planes = np.array([m[3] + m[0], m[3] - m[0], m[3] + m[1], m[3] - m[1], m[3] + m[2], m[3] - m[2]])
    n = np.linalg.norm(planes[:, :3], axis=1, keepdims=True)
    return planes / np.maximum(n, 1e-12)


class Renderer:
    GEOM_PROGRAMS = ("main", "oit", "pre", "shadow", "parity", "cap")

    def __init__(self, ctx: moderngl.Context):
        self.ctx = ctx
        P = lambda vs, fs: ctx.program(vertex_shader=vs, fragment_shader=fs)
        self.p_main = P(shaders.GEOM_VS, shaders.MAIN_FS)
        self.p_oit = P(shaders.GEOM_VS, shaders.OIT_FS)
        self.p_pre = P(shaders.GEOM_VS, shaders.PREPASS_FS)
        self.p_shadow = P(shaders.GEOM_VS, shaders.SHADOW_FS)
        self.p_parity = P(shaders.GEOM_VS, shaders.PARITY_FS)
        self.p_cap = P(shaders.GEOM_VS, shaders.CAP_FS)
        self.p_back = P(shaders.FSQ_VS, shaders.BACKDROP_FS)
        self.p_ssao = P(shaders.FSQ_VS, shaders.SSAO_FS)
        self.p_blur = P(shaders.FSQ_VS, shaders.BLUR_FS)
        self.p_comp = P(shaders.FSQ_VS, shaders.COMPOSITE_FS)
        self.p_capmix_pre = P(shaders.FSQ_VS, shaders.CAPMIX_PRE_FS)
        self.p_capmix = P(shaders.FSQ_VS, shaders.CAPMIX_FS)
        self.p_blit = P(shaders.FSQ_VS, shaders.BLIT_FS)
        self.geom = {"main": self.p_main, "oit": self.p_oit, "pre": self.p_pre, "shadow": self.p_shadow,
                     "parity": self.p_parity, "cap": self.p_cap}
        self._full_geom = self.geom.copy()
        self._compact_geom = None
        self._compact_unavailable = False
        self._compact_vertices = False
        self.programs = list(self.geom.values()) + [self.p_back, self.p_ssao, self.p_blur, self.p_comp,
                                                    self.p_capmix_pre, self.p_capmix, self.p_blit]
        self.u = {p: _U(p) for p in self.programs}
        self.fsq = {p: ctx.vertex_array(p, []) for p in (self.p_back, self.p_ssao, self.p_blur, self.p_comp,
                                                         self.p_capmix_pre, self.p_capmix, self.p_blit)}
        self.env = Environment(ctx, studio=Settings.studio)
        self._env_key = (Settings.studio, 0.15)
        self.white = ctx.texture((1, 1), 4, bytes([255, 255, 255, 255]))
        self.model: ViewerModel | None = None
        self.vbo = self.ibo = self.abo = None
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
        self.last_vp = np.eye(4)
        self.frame_ok = False
        self._released = False
        self.gl_info = f"{ctx.info.get('GL_RENDERER', '?')} / OpenGL {ctx.version_code}"
        for s in self.shadow_sizes:
            tex = ctx.depth_texture((s, s))
            tex.compare_func = "<="
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            tex.repeat_x = tex.repeat_y = False
            self.shadow_maps.append((tex, ctx.framebuffer(depth_attachment=tex)))

    # ------------------------------------------------------------------ model
    def _use_geometry_layout(self, compact):
        if compact and self._compact_geom is None and not self._compact_unavailable:
            programs = {}
            try:
                vertex_source = _static_geometry_shader()
                fragments = {"main": shaders.MAIN_FS, "oit": shaders.OIT_FS, "pre": shaders.PREPASS_FS,
                             "shadow": shaders.SHADOW_FS, "parity": shaders.PARITY_FS, "cap": shaders.CAP_FS}
                for name, fragment_source in fragments.items():
                    programs[name] = self.ctx.program(vertex_shader=vertex_source, fragment_shader=fragment_source)
            except Exception:              # an unsupported specialization must retain the established full path
                for program in programs.values():
                    program.release()
                self._compact_unavailable = True
            else:
                self._compact_geom = programs
                self.programs.extend(programs.values())
                self.u.update({program: _U(program) for program in programs.values()})
        self._compact_vertices = bool(compact and self._compact_geom is not None)
        self.geom = self._compact_geom if self._compact_vertices else self._full_geom
        for name, program in self.geom.items():
            setattr(self, "p_" + name, program)
        return self._compact_vertices

    def set_model(self, model: ViewerModel):
        self.release_model()
        try:
            ctx = self.ctx
            self.model = model
            compact = self._use_geometry_layout(_can_compact_vertices(model))
            vertices = model.vertices[:, :6] if compact else model.vertices
            fmt, attrs = (STATIC_FMT, STATIC_ATTRS) if compact else (FMT, ATTRS)
            # ModernGL accepts contiguous buffer objects directly. Avoid a
            # second full-model bytes allocation on the GUI thread at upload.
            self.vbo = ctx.buffer(np.ascontiguousarray(vertices, dtype=np.float32))
            self.ibo = ctx.buffer(np.ascontiguousarray(model.indices, dtype=np.uint32))
            if model.anim_vertices is not None:
                self.abo = ctx.buffer(np.ascontiguousarray(model.anim_vertices).view(np.uint8))
            for name, p in self.geom.items():
                buffers = [(self.vbo, fmt, *attrs)]
                if self.abo is not None:
                    buffers.append((self.abo, ANIM_FMT, *ANIM_ATTRS))
                self.vaos[name] = ctx.vertex_array(p, buffers, self.ibo, 4, skip_errors=True)
            side = model.sidecar.get("lights") or {}
            self.rig = side.get("rig") or DEFAULT_RIG
            self.world = side.get("world") or DEFAULT_WORLD
            self._shadow_key = None
            diag = float(np.linalg.norm(model.bounds_max - model.bounds_min))
            self.model_diag = max(diag, 1e-3)
            self.frame_ok = False
            for u in self.u.values():
                u.reset()
        except Exception:
            self.release_model()
            raise

    def release_model(self):
        # Retire ownership before releasing. A context-lost object must not leave
        # the renderer partly live or prevent the remaining objects being freed.
        objects = list(self.vaos.values()) + [self.vbo, self.ibo, self.abo]
        objects += [texture for texture in self.textures.values() if texture is not self.white]
        self.vaos = {}
        self.vbo = self.ibo = self.abo = None
        self.textures = {}
        self.model = None
        self.frame_ok = False
        self._compact_vertices = False
        for obj in objects:
            if obj is not None:
                try:
                    obj.release()
                except Exception:           # already gone with its context; continue cleanup
                    pass

    def release(self):
        """Free every GPU object. Contexts are shared, so nothing goes away with the widget by itself."""
        if self._released:
            return
        self._released = True
        self.release_model()
        objs = list(self.t.values()) + list(self.fsq.values()) + self.programs + [self.white]
        objs += list(getattr(self, "_label_gpu", {}).values())
        for tex, fbo in self.shadow_maps:
            objs += [fbo, tex]
        env = self.env
        objs += [getattr(env, "spec", None), getattr(env, "_vao", None), getattr(env, "_prog", None)]
        for o in objs:
            if o is not None:
                try:
                    o.release()
                except Exception:           # noqa: BLE001 - already gone with its context
                    pass
        self.t = {}

    def _texture(self, image_index):
        if image_index in self.textures:
            return self.textures[image_index]
        tex = self.white
        try:
            from PIL import Image
            raw = self.model.doc.images[image_index]
            # glTF UV(0, 0) refers to the source image's upper-left corner.
            im = Image.open(io.BytesIO(raw)).convert("RGBA")
            limit = 4096
            if max(im.size) > limit:
                k = limit / max(im.size)
                im = im.resize((max(1, int(im.size[0] * k)), max(1, int(im.size[1] * k))), Image.LANCZOS)
            # glTF base-color RGB is sRGB; alpha is linear. Hardware decoding
            # happens before filtering and mipmap sampling, as the spec requires.
            tex = self.ctx.texture(im.size, 4, im.tobytes(), internal_format=0x8C43)  # GL_SRGB8_ALPHA8
            tex.build_mipmaps()
            tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
            tex.anisotropy = 8.0
        except Exception:                   # noqa: BLE001 - a bad image draws untextured rather than failing
            if tex is not self.white:
                tex.release()               # upload succeeded but mipmaps/filter setup failed
            tex = self.white
        self.textures[image_index] = tex
        return tex

    # ------------------------------------------------------------------ targets
    def _ensure_targets(self, w, h, samples):
        if self.size == (w, h) and self.samples == samples:
            return
        # Retire the old set first, keeping peak VRAM bounded during resize.
        # On failure the renderer owns no targets, so the next frame may retry.
        previous, self.t = self.t, {}
        self.size = self.samples = None
        self.frame_ok = False
        for obj in reversed(list(previous.values())):
            obj.release()
        ctx = self.ctx
        near = (moderngl.NEAREST, moderngl.NEAREST)
        t = {}
        try:
            t["nd"] = ctx.texture((w, h), 4, dtype="f4")
            t["id"] = ctx.texture((w, h), 2, dtype="f4")
            t["pre_depth"] = ctx.depth_renderbuffer((w, h))
            for k in ("nd", "id"):
                t[k].filter = near
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
            # cut faces
            t["parity"] = ctx.texture((w, h), 1, dtype="f4")
            t["cap_albedo"] = ctx.texture((w, h), 4, dtype="f2")
            t["cap_normal"] = ctx.texture((w, h), 4, dtype="f2")
            t["cap_id"] = ctx.texture((w, h), 2, dtype="f4")
            t["cap_zp"] = ctx.texture((w, h), 1, dtype="f4")
            for k in ("parity", "cap_albedo", "cap_normal", "cap_id", "cap_zp"):
                t[k].filter = near
            t["cap_key"] = ctx.depth_texture((w, h))
            t["fbo_parity"] = ctx.framebuffer([t["parity"]])
            t["fbo_cap"] = ctx.framebuffer([t["cap_albedo"], t["cap_normal"], t["cap_id"], t["cap_zp"]], t["cap_key"])
            # the final picture at render size, for a scaled blit to the window
            t["final"] = ctx.texture((w, h), 4)
            t["final"].filter = (moderngl.LINEAR, moderngl.LINEAR)
            t["fbo_final"] = ctx.framebuffer([t["final"]])
        except Exception:
            for obj in reversed(list(t.values())):
                obj.release()
            raise
        self.t = t
        self.size = (w, h)
        self.samples = samples

    # ------------------------------------------------------------------ per-item state
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

    # ------------------------------------------------------------------ frame
    def render(self, target, size, camera, s: Settings, fs: FrameState | None = None, out_size=None):
        """Render one frame into ``target`` (a moderngl Framebuffer). ``size`` is the render resolution;
        ``out_size`` the target's, when the picture is scaled up or down on the way (Settings -> render scale)."""
        # Any failed pass may leave the pre-pass and camera out of sync. Only
        # the completed frame below can re-enable picking and depth queries.
        self.frame_ok = False
        ctx = self.ctx
        w, h = max(int(size[0]), 2), max(int(size[1]), 2)
        self._ids_cache = None
        samples = max(1, min(int(s.msaa), ctx.max_samples))
        self._ensure_targets(w, h, samples)
        if self._env_key != (round(s.studio, 3), self._ambient()):
            self.env.rebuild(s.studio, self._ambient())
            self._env_key = (round(s.studio, 3), self._ambient())
        t = self.t
        aspect = w / h
        camera.aspect = aspect
        V = camera.view_matrix()
        Pm = camera.proj_matrix(aspect)
        VP = Pm @ V
        self.last_vp = VP
        campos = camera.position()
        self.last_camera = (V, Pm, aspect, camera.ortho,
                            camera.ortho_halves(aspect) if camera.ortho else camera.half_tans(aspect), (w, h))
        m = self.model
        fs, vis, ghost, alpha = self._state(fs) if m is not None else (fs or FrameState(), None, None, None)
        self._fs = fs
        clip = (np.array(fs.clip_planes, dtype=np.float32), tuple(int(bool(x)) for x in fs.clip_on), int(fs.clip_mode))
        any_clip = any(clip[1])

        ctx.disable(moderngl.BLEND | moderngl.CULL_FACE)
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.depth_func = "<"

        draws, oit = [], []
        if m is not None:
            planes = _frustum_planes(VP)
            for p in m.parts:
                it = p.item
                if not vis[it]:
                    continue
                c, r = m.part_sphere(p)
                if np.any(planes[:, :3] @ c + planes[:, 3] < -r):
                    continue
                if _transparent_pass(p, bool(ghost[it]), float(alpha[it]), fs):
                    oit.append(p)
                else:
                    draws.append(p)

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
            self._render_shadows(lights, s, draws, clip)

        # 2. pre-pass: normals, linear depth, ids (opaque only)
        fpre = t["fbo_pre"]
        fpre.use()
        ctx.viewport = (0, 0, w, h)
        fpre.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        if m is not None:
            u = self.u[self.p_pre]
            u("u_viewproj", VP)
            u("u_view", V)
            self._clip_uniforms(u, clip)
            vao = self.vaos["pre"]
            for p in draws:
                M = m.part_matrix(p)
                u("u_model", M)
                u("u_nmat", np.linalg.inv(M[:3, :3]).T)
                u("u_flip", 1 if np.linalg.det(M[:3, :3]) < 0 else 0)
                u("u_weight", float(m.node_weights.get(p.node, 0.0)))
                u("u_id", float(p.item + 1))
                u("u_flags", 1.0 if p.item in fs.selected else 0.0)
                u("u_noclip", 0 if m.items[p.item].clip else 1)
                self._anim_uniforms(u, p)
                lk = p.look
                if lk.texture is not None and lk.alpha_cut > 0.0:
                    self._texture(lk.texture).use(6)
                    u("u_tex", 6)
                    u("u_has_tex", 1)
                    u("u_alpha_cut", float(lk.alpha_cut))
                else:
                    u("u_has_tex", 0)
                    u("u_alpha_cut", 0.0)
                vao.render(moderngl.TRIANGLES, vertices=p.count, first=p.first)

        # 2b. cut faces: gathered per item, then laid into the pre-pass
        caps = False
        if any_clip and m is not None and draws:
            caps = self._render_caps(draws, VP, V, campos, camera, clip, fs, (w, h))

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

        # 4. forward MSAA: backdrop, then opaque, then the cut faces on their planes
        fm = t["fbo_main"]
        fm.use()
        ctx.viewport = (0, 0, w, h)
        fm.clear(0.0, 0.0, 0.0, 1.0, depth=1.0)
        ctx.disable(moderngl.DEPTH_TEST)
        ub = self.u[self.p_back]
        world = self.world or DEFAULT_WORLD
        if s.background is not None:
            top, bottom = s.background
        else:
            top, bottom = world.get("top_hex", "#20242b"), world.get("bottom_hex", "#12141a")
        k = 2.0 ** -float(s.exposure)          # the backdrop keeps its colour whatever the exposure
        ub("u_bottom", np.array(backdrop_linear(bottom, s.tonemap)) * k)
        ub("u_top", np.array(backdrop_linear(top, s.tonemap)) * k)
        self.fsq[self.p_back].render(moderngl.TRIANGLES, vertices=3)
        ctx.enable(moderngl.DEPTH_TEST)
        if m is not None:
            self._draw_shaded(self.p_main, "main", draws, VP, V, campos, lights, s, (w, h), camera, clip, fs, alpha)
            if caps:
                self._capmix(VP, V, campos, lights, s, (w, h), camera, fs)

        # 5. translucent and x-rayed parts: weighted blended OIT into the same MSAA depth
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
            self._draw_shaded(self.p_oit, "oit", oit, VP, V, campos, lights, s, (w, h), camera, clip, fs, alpha,
                              ghost=ghost)
            ctx.disable(moderngl.BLEND)
            fo.depth_mask = True

        # 6. resolve and composite
        ctx.copy_framebuffer(t["fbo_opaque"], t["fbo_col_src"])
        if oit_on:
            ctx.copy_framebuffer(t["fbo_accum"], t["fbo_acc_src"])
            ctx.copy_framebuffer(t["fbo_weight"], t["fbo_wgt_src"])
        scaled = out_size is not None and (int(out_size[0]), int(out_size[1])) != (w, h)
        dest = t["fbo_final"] if scaled else target
        dest.use()
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
        uc("u_has_sel", 1 if (fs.selected or s.selected) else 0)
        hov = fs.hovered + 1 if fs.hovered >= 0 else s.hovered
        uc("u_hover", float(hov if s.hover_outline_on and hov not in {i + 1 for i in fs.selected} else 0))
        uc("u_outline", np.array(s.outline))
        uc("u_hover_outline", np.array(s.hover_outline))
        uc("u_exposure", float(s.exposure))
        uc("u_tonemap", 1 if s.tonemap else 0)
        uc("u_texel", np.array([1.0 / w, 1.0 / h]))
        uc("u_outline_px", float(max(1.5, h / 540.0)))
        self.fsq[self.p_comp].render(moderngl.TRIANGLES, vertices=3)
        if scaled:
            ow, oh = int(out_size[0]), int(out_size[1])
            target.use()
            ctx.viewport = (0, 0, ow, oh)
            t["final"].use(0)
            self.u[self.p_blit]("u_src", 0)
            self.fsq[self.p_blit].render(moderngl.TRIANGLES, vertices=3)
        ctx.enable(moderngl.DEPTH_TEST)
        self.frame_ok = True

    def _ambient(self):
        world = self.world or DEFAULT_WORLD
        return round(float(np.mean(world.get("ambient_colour", [0.5] * 3))) * float(world.get("ambient_strength", 0.3)), 4)

    def _auto_ao_radius(self):
        um = self.model.um_per_bu() if self.model else 0
        if um and um <= 50:
            return 4.5 / um                     # 4.5 um: the gaps between packed cells
        return self.model_diag * 0.017

    @staticmethod
    def _clip_uniforms(u, clip):
        planes, on, mode = clip
        for i in range(3):
            u(f"u_clip{i}", planes[i])
        u("u_clip_on", tuple(on))
        u("u_clip_mode", mode)

    def _anim_uniforms(self, u, p: Part):
        fs = self._fs
        if self.abo is None or fs.anim_frame is None:
            u("u_anim", 0)
            return
        u("u_anim", 1)
        u("u_anim_t", float(fs.anim_t))
        u("u_aw", fs.anim_frame[0, p.item])
        u("u_ag", fs.anim_frame[1, p.item])

    # ------------------------------------------------------------------ shadows
    def _render_shadows(self, lights, s, draws, clip):
        m = self.model
        ctx = self.ctx
        casters = draws
        key = (tuple(np.round(np.concatenate([l[0] for l in lights]), 5)),
               tuple(sorted((node, round(weight, 5)) for node, weight in m.node_weights.items())),
               tuple(sorted((k, tuple(np.round(v, 4))) for k, v in m.node_offsets.items())),
               tuple(p.id for p in casters), round(s.shadow_soft, 3),
               clip[0].round(5).tobytes(), clip[1], clip[2],
               None if m.item_offsets is None else m.item_offsets.round(5).tobytes(),
               None if self._fs.anim_frame is None else (round(self._fs.anim_t, 4), self._fs.anim_frame.tobytes()))
        if key == self._shadow_key:
            return
        # fitted to everything shown, so the shadows do not jump as parts are hidden one by one
        lo, hi = m.world_bounds(visible_only=False, visible=self._visible_items())
        c = (lo + hi) / 2
        r = max(float(np.linalg.norm(hi - lo)) / 2, 1e-3) * 1.02
        u = self.u[self.p_shadow]
        vao = self.vaos["shadow"]
        from .camera import look_at, orthographic
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.polygon_offset = (1.5, 2.0)
        try:
            self._clip_uniforms(u, clip)
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
                    u("u_noclip", 0 if m.items[p.item].clip else 1)
                    self._anim_uniforms(u, p)
                    vao.render(moderngl.TRIANGLES, vertices=p.count, first=p.first)
        finally:
            ctx.polygon_offset = (0.0, 0.0)
        self._shadow_key = key             # a failed pass must be rendered again

    def _visible_items(self):
        fs = self._fs
        if fs is not None and fs.visible is not None:
            return fs.visible
        vis = np.zeros(len(self.model.items), dtype=bool)
        for p in self.model.parts:
            vis[p.item] |= p.visible
        return vis

    # ------------------------------------------------------------------ cut faces
    def _render_caps(self, draws, VP, V, campos, camera, clip, fs, size):
        """Gather the cut faces of every item the planes pass through (see the module docstring of shaders.py).
        Returns True when anything was cut."""
        ctx = self.ctx
        m = self.model
        t = self.t
        w, h = size
        planes, on, _mode = clip
        by_item = {}
        for p in draws:
            if m.items[p.item].clip and not p.look.translucent:
                by_item.setdefault(p.item, []).append(p)
        cut = []
        for it, ps in by_item.items():
            box = np.concatenate([m._box(p) for p in ps], 0)
            for i in range(3):
                if on[i]:
                    d = box @ planes[i][:3] + planes[i][3]
                    if d.min() < 0.0 < d.max():
                        cut.append((it, ps, box))
                        break
        if not cut:
            return False
        t["fbo_cap"].use()
        ctx.viewport = (0, 0, w, h)
        t["fbo_cap"].clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        inv = np.linalg.inv(VP)
        up = self.u[self.p_parity]
        uc = self.u[self.p_cap]
        up("u_viewproj", VP)
        self._clip_uniforms(up, clip)
        uc("u_viewproj", VP)
        uc("u_inv_viewproj", inv)
        uc("u_viewport", np.array([w, h], dtype=np.float32))
        uc("u_key_scale", float(self.model_diag * 0.02))
        self._clip_uniforms(uc, clip)
        t["parity"].use(7)
        uc("u_parity", 7)
        vp_par, vp_cap = self.vaos["parity"], self.vaos["cap"]
        any_drawn = False
        for it, ps, box in cut:
            rect = self._screen_rect(box, VP, w, h)
            if rect is None:
                continue
            x0, y0, x1, y1 = rect
            ctx.scissor = (x0, y0, x1 - x0, y1 - y0)
            # nearest kept front face of this item
            t["fbo_parity"].use()
            ctx.viewport = (0, 0, w, h)
            t["fbo_parity"].clear(1.0, 1.0, 1.0, 1.0)
            ctx.disable(moderngl.DEPTH_TEST)
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = moderngl.ONE, moderngl.ONE
            ctx.blend_equation = moderngl.MIN
            for p in ps:
                M = m.part_matrix(p)
                up("u_model", M)
                up("u_flip", 1 if np.linalg.det(M[:3, :3]) < 0 else 0)
                up("u_weight", float(m.node_weights.get(p.node, 0.0)))
                up("u_noclip", 0)
                self._anim_uniforms(up, p)
                vp_par.render(moderngl.TRIANGLES, vertices=p.count, first=p.first)
            ctx.blend_equation = moderngl.FUNC_ADD
            ctx.disable(moderngl.BLEND)
            # its back faces seen through the cut
            t["fbo_cap"].use()
            ctx.viewport = (0, 0, w, h)
            ctx.enable(moderngl.DEPTH_TEST)
            item = m.items[it]
            for p in ps:
                M = m.part_matrix(p)
                uc("u_model", M)
                uc("u_nmat", np.linalg.inv(M[:3, :3]).T)
                uc("u_flip", 1 if np.linalg.det(M[:3, :3]) < 0 else 0)
                uc("u_weight", float(m.node_weights.get(p.node, 0.0)))
                uc("u_noclip", 0)
                uc("u_id", float(it + 1))
                uc("u_flags", 1.0 if it in fs.selected else 0.0)
                self._anim_uniforms(uc, p)
                self._set_look(uc, p, None, fs)
                uc("u_cap_dark", 0.80 if p.look.detail is not None else 0.62)
                vp_cap.render(moderngl.TRIANGLES, vertices=p.count, first=p.first)
                any_drawn = True
            del item
        ctx.scissor = None
        if not any_drawn:
            return False
        # lay the winners into the pre-pass at their depth on the plane
        t["fbo_pre"].use()
        ctx.viewport = (0, 0, w, h)
        ctx.enable(moderngl.DEPTH_TEST)
        u = self.u[self.p_capmix_pre]
        t["cap_normal"].use(0)
        t["cap_id"].use(1)
        t["cap_zp"].use(2)
        u("u_cap_normal", 0)
        u("u_cap_id", 1)
        u("u_cap_zp", 2)
        u("u_inv_viewproj", inv)
        u("u_view", V)
        self.fsq[self.p_capmix_pre].render(moderngl.TRIANGLES, vertices=3)
        return True

    @staticmethod
    def _screen_rect(box, VP, w, h):
        pts = np.concatenate([box, np.ones((len(box), 1))], 1) @ VP.T
        if np.any(pts[:, 3] <= 1e-6):
            return 0, 0, w, h
        ndc = pts[:, :2] / pts[:, 3:4]
        x0 = int(np.floor((ndc[:, 0].min() * 0.5 + 0.5) * w)) - 2
        x1 = int(np.ceil((ndc[:, 0].max() * 0.5 + 0.5) * w)) + 2
        y0 = int(np.floor((ndc[:, 1].min() * 0.5 + 0.5) * h)) - 2
        y1 = int(np.ceil((ndc[:, 1].max() * 0.5 + 0.5) * h)) + 2
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
        if x1 <= x0 or y1 <= y0:
            return None
        return x0, y0, x1, y1

    def _capmix(self, VP, V, campos, lights, s, size, camera, fs):
        ctx = self.ctx
        t = self.t
        u = self.u[self.p_capmix]
        self._light_uniforms(u, V, campos, lights, s, size, camera)
        t["cap_albedo"].use(7)
        t["cap_normal"].use(8)
        t["cap_id"].use(9)
        t["cap_zp"].use(10)
        u("u_cap_albedo", 7)
        u("u_cap_normal", 8)
        u("u_cap_id", 9)
        u("u_cap_zp", 10)
        u("u_inv_viewproj", np.linalg.inv(VP))
        u("u_hover_id", float(fs.hovered + 1) if fs.hovered >= 0 else -1.0)
        u("u_sel_col", np.array(s.highlight))
        u("u_hover_col", np.array(s.hover_highlight))
        ctx.enable(moderngl.DEPTH_TEST)
        self.fsq[self.p_capmix].render(moderngl.TRIANGLES, vertices=3)

    # ------------------------------------------------------------------ shaded parts
    def _light_uniforms(self, u, V, campos, lights, s, size, camera):
        t = self.t
        u("u_view", V)
        u("u_campos", np.asarray(campos))
        u("u_ortho", 1 if camera.ortho else 0)
        u("u_viewdir", np.asarray(camera.basis()[2]))
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
        prog_sh = u.prog.get("u_sh", None)
        if prog_sh is not None:
            prog_sh.write(np.ascontiguousarray(self.env.sh, dtype=np.float32).tobytes())
        self.env.spec.use(4)
        u("u_spec", 4)
        u("u_spec_layers", float(self.env.spec.layers))
        u("u_env_diffuse", float(s.env_diffuse))
        u("u_env_spec", float(s.env_spec))
        u("u_bounce", float(s.bounce * s.light_scale))
        self.white.use(5)
        u("u_tex", 5)

    def _draw_shaded(self, prog, vao_name, parts, VP, V, campos, lights, s, size, camera, clip, fs, alpha,
                     ghost=None):
        m = self.model
        u = self.u[prog]
        vao = self.vaos[vao_name]
        u("u_viewproj", VP)
        self._light_uniforms(u, V, campos, lights, s, size, camera)
        self._clip_uniforms(u, clip)
        u("u_ghost_alpha", float(s.ghost_alpha))
        order = sorted(parts, key=lambda p: (p.material_name, p.id))
        for p in order:
            it = p.item
            M = m.part_matrix(p)
            wgt = float(m.node_weights.get(p.node, 0.0))
            u("u_model", M)
            u("u_nmat", np.linalg.inv(M[:3, :3]).T)
            u("u_flip", 1 if np.linalg.det(M[:3, :3]) < 0 else 0)
            u("u_weight", wgt)
            u("u_noclip", 0 if m.items[it].clip else 1)
            self._anim_uniforms(u, p)
            self._set_look(u, p, s, fs)
            if ghost is not None:
                u("u_ghost", 1 if ghost[it] else 0)
                u("u_alpha_mul", float(alpha[it]))
            if it in fs.selected:
                u("u_highlight", 0.45)
                u("u_highlight_col", np.array(s.highlight))
            elif it == fs.hovered or (s.hovered and s.hovered == it + 1):
                u("u_highlight", 0.18)
                u("u_highlight_col", np.array(s.hover_highlight))
            else:
                u("u_highlight", 0.0)
            vao.render(moderngl.TRIANGLES, vertices=p.count, first=p.first)

    def _set_look(self, u, p: Part, s: Settings | None, fs: FrameState):
        lk = p.look
        it = p.item
        flat = fs.override.get(it)
        if flat is None and fs.colours is not None:
            flat = fs.colours[it]
        u("u_base", np.array(flat if flat is not None else lk.base))
        u("u_alpha", 1.0 if fs.opaque_materials else float(lk.alpha))
        u("u_rough", float(lk.rough))
        u("u_metal", float(lk.metal))
        u("u_f0", float(lk.f0))
        u("u_wrap", float(min(0.5, (0.02 + 1.5 * lk.sss) * (s.tissue if s is not None else 1.0))))
        u("u_emis", np.array(lk.emissive))
        u("u_use_vcol", 1 if lk.use_vcol and flat is None else 0)
        u("u_alpha_cut", float(lk.alpha_cut))
        if lk.texture is not None and (flat is None or lk.alpha_cut > 0.0):
            tex = self._texture(lk.texture)
            tex.use(6)
            u("u_tex", 6)
            u("u_has_tex", 1 if flat is None else 0)
            if flat is not None:        # a flat colour still keeps the holes of an alpha-tested texture
                u("u_has_tex", 1)
                u("u_base", np.array(flat))
        else:
            u("u_tex", 5)
            u("u_has_tex", 0)
        st = lk.stripe
        if st and flat is None:
            u("u_stripe", 1 if (s is None or s.stripes) else 2)
            u("u_stripe_p", np.array([st["period"], st["threshold"], st.get("edge", 0.025), st.get("i_mix", 1.0)]))
            u("u_shorten", float(st.get("shorten", 0.0)))
            u("u_stripe_a", np.array(st["a_band_colour"]))
            u("u_stripe_b", np.array(st["i_band_colour"]))
        else:
            u("u_stripe", 0)
        mo = lk.mottle
        if mo and flat is None:
            u("u_mottle", 1)
            u("u_mottle_p", np.array([mo["scale"], mo["from_min"], mo["from_max"], min(6.0, mo.get("detail", 2.0) + 1.0)]))
            u("u_mottle_a", np.array(mo["colour_a"]))
            u("u_mottle_b", np.array(mo["colour_b"]))
        else:
            u("u_mottle", 0)
        if lk.detail is not None:
            u("u_detail_on", 1)
            u("u_detail", np.array(lk.detail, dtype=np.float32))
        else:
            u("u_detail_on", 0)
        if lk.facing and not fs.opaque_materials:
            u("u_facing_on", 1)
            u("u_facing", np.array(lk.facing))
        else:
            u("u_facing_on", 0)

    # ------------------------------------------------------------------ queries
    def _read_prepass(self, components, attachment, viewport=None):
        """Read floating IDs/depth with a floating DRAW target, restoring state."""
        previous_fbo, previous_viewport = self.ctx.fbo, self.ctx.viewport
        if previous_fbo is None:
            return None
        w, h = self.size if viewport is None else viewport[2:]
        values = np.full(int(w) * int(h) * components, np.nan, dtype=np.float32)
        options = {"components": components, "attachment": attachment, "dtype": "f4"}
        if viewport is not None:
            options["viewport"] = viewport
        try:
            fpre = self.t["fbo_pre"]
            fpre.use()
            fpre.read_into(values, **options)
        except moderngl.Error:
            return None
        finally:
            previous_fbo.use()
            self.ctx.viewport = previous_viewport
        return values if np.isfinite(values).all() else None

    def pick(self, x, y):
        """(item index or -1, world point or None, on a cut face) under render pixel (x, y from the top-left) of
        the last frame."""
        if self.last_camera is None or not self.t or not self.frame_ok:
            return -1, None, False
        V, Pm, aspect, ortho, halves, (w, h) = self.last_camera
        if not (0 <= x < w and 0 <= y < h):
            return -1, None, False
        gy = h - 1 - int(y)
        nd = self._read_prepass(4, 0, (int(x), gy, 1, 1))
        idf = self._read_prepass(2, 1, (int(x), gy, 1, 1))
        if nd is None or idf is None:
            return -1, None, False
        d = float(nd[3])
        if d <= 0.0:
            return -1, None, False
        return int(round(float(idf[0]))) - 1, self._unproject(x + 0.5, gy + 0.5, d), (int(round(float(idf[1]))) & 2) != 0

    def _unproject(self, gx, gy, d):
        """World point at GL pixel (gx, gy) whose linear view depth is d."""
        V, Pm, aspect, ortho, halves, (w, h) = self.last_camera
        ndc = np.array([gx / w * 2 - 1, gy / h * 2 - 1])
        if ortho:
            pv = np.array([ndc[0] * halves[0], ndc[1] * halves[1], -d, 1.0])
        else:
            pv = np.array([ndc[0] * halves[0] * d, ndc[1] * halves[1] * d, -d, 1.0])
        return (np.linalg.inv(V) @ pv)[:3]

    def read_label_samples(self, step):
        """Exactly the existing strided IDs and cell-centre depth, sampled on GPU.

        Label placement already uses this grid; this avoids transferring the
        full-resolution buffers only to discard their unused pixels on CPU.
        """
        if not self.frame_ok or not self.t:
            return None
        ctx = self.ctx
        previous, viewport = ctx.fbo, ctx.viewport
        if previous is None:
            return None
        w, h = self.size
        grid = ((w + step - 1) // step, (h + step - 1) // step)
        gpu = getattr(self, "_label_gpu", {})
        try:
            if not gpu:
                program = ctx.program(vertex_shader=shaders.FSQ_VS, fragment_shader='''#version 410 core
uniform sampler2D ids;
uniform sampler2D depth_normal;
uniform ivec2 full_size;
uniform ivec2 grid_size;
uniform int step;
out vec4 result;
void main() {
    ivec2 cell = ivec2(gl_FragCoord.xy);
    cell.y = grid_size.y - 1 - cell.y;
    ivec2 origin = cell * step;
    ivec2 center = min(origin + ivec2(step / 2), full_size - 1);
    origin.y = full_size.y - 1 - origin.y;
    center.y = full_size.y - 1 - center.y;
    vec2 sample_ids = texelFetch(ids, origin, 0).xy;
    result = vec4(sample_ids, texelFetch(depth_normal, center, 0).w,
                  texelFetch(ids, center, 0).x);
}''')
                gpu = {"program": program, "vao": ctx.vertex_array(program, [])}
                self._label_gpu = gpu
            if getattr(self, "_label_grid_size", None) != grid:
                for name in ("fbo", "texture"):
                    if name in gpu: gpu.pop(name).release()
                gpu["texture"] = ctx.texture(grid, 4, dtype="f4")
                gpu["fbo"] = ctx.framebuffer([gpu["texture"]])
                self._label_grid_size = grid
            program = gpu["program"]
            program["ids"].value = 0; program["depth_normal"].value = 1
            program["full_size"].value = (w,h); program["grid_size"].value = grid
            program["step"].value = step
            self.t["id"].use(0); self.t["nd"].use(1)
            gpu["fbo"].use(); ctx.viewport = (0,0,*grid)
            ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
            gpu["vao"].render(moderngl.TRIANGLES, vertices=3)
            values = np.frombuffer(gpu["fbo"].read(components=4,dtype="f4"),np.float32).reshape(grid[1],grid[0],4)[::-1]
            return (np.rint(values[...,0]).astype(np.int32)-1,
                    np.rint(values[...,1]).astype(np.int32), values[...,2],
                    np.rint(values[...,3]).astype(np.int32)-1)
        except (moderngl.Error, KeyError):
            return None  # retain the established readback path on unsupported contexts
        finally:
            previous.use(); ctx.viewport = viewport

    def read_ids(self):
        """(h, w) item index (-1 for background) and (h, w) flags of the last frame's pre-pass, top row first."""
        if not self.frame_ok or not self.t:
            return None, None
        if getattr(self, "_ids_cache", None) is not None:
            return self._ids_cache
        w, h = self.size
        raw = self._read_prepass(2, 1)
        if raw is None:
            return None, None
        a = raw.reshape(h, w, 2)[::-1]
        self._ids_cache = (np.rint(a[..., 0]).astype(np.int32) - 1,
                           np.rint(a[..., 1]).astype(np.int32))
        return self._ids_cache

    def read_depth(self):
        """(h, w) linear view depth of the last frame (0 for background), top row first."""
        if not self.frame_ok or not self.t:
            return None
        w, h = self.size
        raw = self._read_prepass(4, 0)
        if raw is None:
            return None
        return raw.reshape(h, w, 4)[::-1, :, 3].copy()

    def ids_at(self, points):
        """Item index at render pixels [(x, y) from the top-left, ...] of the last frame (-1: background/outside)."""
        out = []
        if not self.frame_ok or not self.t:
            return [-1] * len(points)
        w, h = self.size
        cached = getattr(self, "_ids_cache", None)
        for x, y in points:
            if not (0 <= x < w and 0 <= y < h):
                out.append(-1)
                continue
            if cached is not None:
                out.append(int(cached[0][int(y), int(x)]))
                continue
            raw = self._read_prepass(2, 1, (int(x), h - 1 - int(y), 1, 1))
            out.append(-1 if raw is None else int(round(float(raw[0]))) - 1)
        return out

    def world_from_pixel(self, x, y, d):
        """World point at render pixel (x, y from the top-left) and linear depth d of the last frame."""
        if self.last_camera is None or not self.frame_ok:
            return None
        h = self.last_camera[5][1]
        return self._unproject(x + 0.5, h - 1 - y + 0.5, d)

    def read_final(self, fbo, size):
        w, h = size
        data = fbo.read(viewport=(0, 0, w, h), components=3)
        return np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3)[::-1]
