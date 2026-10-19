import logging
import re
import threading

import moderngl
import numpy as np

from . import shaders
from .draw_ranges import BOX_FLOOR, CHUNK_TRIANGLES, Chunks, DrawRanges
from PySide6.QtGui import QColor

from .config import BACKGROUND_DARK, BACKGROUND_LIGHT, SHADING
from .state import STATE_TEX_WIDTH, srgb_to_linear, state_rows, state_texel

VERTEX_FORMAT = "3f 3f u2 u2"
VERTEX_ATTRS = ("in_pos", "in_nrm", "in_obj", "in_mat")
# imported models add a second buffer: texture coordinates, a vertex colour (sRGB bytes) and a texture layer
AUX_FORMAT = "2f 4f1 1f"
AUX_ATTRS = ("in_uv", "in_tint", "in_layer")
FORMAT_SIZE = {"3f": 12, "2f": 8, "1f": 4, "u2": 2, "4f1": 4, "4f2": 8}
ALBEDO_UNIT = 5
PARITY_UNIT = 6
ANIM_UNIT = 10

log = logging.getLogger("anatomy.renderer")


# The covered test (Renderer._draw_opaque_covered). Needs OpenGL 4.3 (a buffer a fragment shader can write to);
# below that, or if these do not compile, the renderer draws its lists without the test.
#
# BOX: the box of every piece of a structure is drawn against the reduced depth of the likely front surfaces; a box
# that gets one pixel through marks its piece as seen.
BOX_VS = """
#version 430 core
in vec3 in_center;
in vec3 in_half;
in float in_on;
uniform mat4 u_viewproj;
uniform vec4 u_wrow;         // last row of the view-projection matrix: clip w of a point
uniform float u_pad;         // world distance of the padding in pixels at clip w = 1
uniform float u_floor;
uniform vec2 u_fit;          // the reduced target is rounded up to whole pixels: keep its blocks on the frame's
flat out int v_piece;
const int CORNER[36] = int[36](0, 1, 3, 0, 3, 2, 4, 6, 7, 4, 7, 5, 0, 4, 5, 0, 5, 1,
                               2, 3, 7, 2, 7, 6, 0, 2, 6, 0, 6, 4, 1, 5, 7, 1, 7, 3);
void main() {
    v_piece = gl_InstanceID;
    if (in_on < 0.5) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }
    int k = CORNER[gl_VertexID];
    vec3 s = vec3(float(k & 1), float((k >> 1) & 1), float((k >> 2) & 1)) * 2.0 - 1.0;
    // grown on screen and as much towards the eye (Chunks.padding is the same sum)
    float far = dot(u_wrow.xyz, in_center) + u_wrow.w + dot(abs(u_wrow.xyz), in_half);
    float grow = u_pad * max(far, 0.0) + u_floor;
    vec4 p = u_viewproj * vec4(in_center + s * (in_half + grow), 1.0);
    gl_Position = vec4((p.xy + p.w) * u_fit - p.w, p.zw);
}
"""
BOX_FS = """
#version 430 core
layout(early_fragment_tests) in;
layout(std430, binding = 0) buffer Seen { uint seen[]; };
flat in int v_piece;
void main() { seen[v_piece] = 1u; }
"""
# REDUCE: the farthest depth of each block of u_scale x u_scale pixels, so a box tested against it at the reduced
# size can only pass more often than against the frame's own depth.
REDUCE_FS = """
#version 430 core
uniform sampler2D u_depth;
uniform int u_scale;
void main() {
    ivec2 last = textureSize(u_depth, 0) - 1;
    ivec2 base = ivec2(gl_FragCoord.xy) * u_scale;
    float d = 0.0;
    for (int y = 0; y < u_scale; ++y)
        for (int x = 0; x < u_scale; ++x)
            d = max(d, texelFetch(u_depth, min(base + ivec2(x, y), last), 0).r);
    gl_FragDepth = d;
}
"""
_DEPTH_ANCHOR = "    if (cutobj && clipped(v_wpos)) discard;\n"


def depth_only_fs():
    """OPAQUE_FS stopped after its discards: the same fragments, no shading. None if that cannot be shown."""
    src = shaders.OPAQUE_FS
    if src.count(_DEPTH_ANCHOR) != 1:
        return None
    head, tail = src.split(_DEPTH_ANCHOR)
    if "discard" in re.sub(r"#ifdef CAP_PASS.*?#endif", "", tail, flags=re.S):
        return None             # a later discard would be skipped: the first draw would hide too much
    return head + _DEPTH_ANCHOR + "    o_color = vec4(0.0); o_normal = vec4(0.0); o_id = 0.0; return;\n" + tail


def _normalize(v):
    return v / np.linalg.norm(v)


def _mat4_bytes(m):
    return np.asarray(m, dtype="f4").T.tobytes()


class Renderer:
    GATHER_MAX = 256       # points per batched id/depth readback (matches u_pts in shaders.GATHER_FS)
    PASSES = ("opaque", "transparent", "mask")
    LOOP_DRAWS = 64        # without glMultiDrawElementsIndirect (below OpenGL 4.3): at most this many draws a pass
    RANGES_INLINE_BYTES = 32 << 20     # larger index buffers are examined on a thread, so loading waits for nothing
    CHUNK_TRIANGLES = CHUNK_TRIANGLES  # size of the pieces the covered test works on
    OCC_SCALE = 4                      # the covered test runs at 1/OCC_SCALE of the frame's width and height
    OCC_OVERHEAD_TRIANGLES = 4_000_000  # what a test costs besides its triangles, counted in triangles
    OCC_LOOSE_TRIANGLES = 1_000_000    # a first draw this much (and a quarter) short of what passed had holes
    OCC_MIN_TRIANGLES = 8_000_000      # opaque lists shorter than this are drawn as they are: nothing to gain

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
        self.p_gather = ctx.program(vertex_shader=shaders.FULLSCREEN_VS, fragment_shader=shaders.GATHER_FS)
        self.gather_vao = ctx.vertex_array(self.p_gather, [])
        self.gather_tex = ctx.texture((self.GATHER_MAX, 1), 4, dtype="f4")
        self.gather_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self.gather_fbo = ctx.framebuffer([self.gather_tex])

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

        # two rows per block of STATE_TEX_WIDTH structures, one block under the other
        self.state_blocks = state_rows(len(ds.structures))
        self.state_tex = ctx.texture((STATE_TEX_WIDTH, 2 * self.state_blocks), 4, dtype="f4")
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

        # Draw lists (app/draw_ranges.py): each pass is given only the structures that can show in it. Until the
        # dataset's layout has been examined, and whenever it cannot be proved, the whole buffer is drawn.
        self.use_ranges = True
        self.ranges = None
        self.last_stats = {}                    # triangles and draws submitted by the last frame, per pass
        self._state_opacity = np.ones(len(structs), dtype=np.float32)
        self._state_version = 0
        self._lists_key = None
        self._lists = None
        self._cmd_buf = {}
        self._cmd_data = {}
        self._indirect = ctx.version_code >= 430
        self._ranges_ready = threading.Event()
        self._ranges_result = None
        # Covered pieces (_draw_opaque_covered): what lies wholly behind other opaque surfaces is not submitted.
        self.use_occlusion = True
        self.chunks = None
        self._chunks_ready = threading.Event()
        self._chunks_result = None
        self._occ = None                        # GL objects of the test; False: cannot run here, or it failed
        self._occ_seen = None                   # per piece: got a pixel of its box through when last tested
        self._occ_need = self._occ_key = None   # the pieces that passed, and the view and state they passed for
        self._occ_final = False                 # that answer came from a test against all that shows in that view
        self._occ_total = (0, 0)                # triangles and pieces on the list that answer was made for
        self._occ_hint = None                   # (state, list length, test does not pay) of the last final answer
        self.occ_fbo = self.occ_small = self.occ_small_tex = None
        self._start_ranges(vertices, indices)

        self.size = (0, 0)
        self.screen_size = None
        self.last_vp = np.identity(4)
        self.last_slice_plane = None
        self.frame_ok = False

    @staticmethod
    def _format_for(prog, fmt=VERTEX_FORMAT, attrs=VERTEX_ATTRS):
        """The buffer's layout for one program: attributes the program does not use become padding."""
        return " ".join(f if a in prog else f"{FORMAT_SIZE[f]}x" for f, a in zip(fmt.split(), attrs))

    # ------------------------------------------------------------------ draw lists
    def _start_ranges(self, vertices, indices):
        structures, materials = self.ds.structures, self.ds.materials

        def work():
            ranges = None
            try:
                ranges = self._ranges_result = DrawRanges.build(structures, materials, vertices, indices)
            finally:
                self._ranges_ready.set()
            try:
                # an animated model moves its vertices, so boxes of its pieces would say nothing
                if ranges is not None and self._indirect and not self.animated:
                    self._chunks_result = Chunks.build(ranges, vertices, indices, self.CHUNK_TRIANGLES)
            finally:
                self._chunks_ready.set()

        if len(indices) <= self.RANGES_INLINE_BYTES:
            work()
        else:
            threading.Thread(target=work, name="draw-ranges", daemon=True).start()

    def wait_ranges(self, timeout=None):
        """Block until the dataset's layout has been examined (tests and measurements); True when lists are in use."""
        self._ranges_ready.wait(timeout)
        self._chunks_ready.wait(timeout)
        return self._adopt_ranges() is not None

    def _adopt_ranges(self):
        if self.ranges is None and self._ranges_ready.is_set() and self._ranges_result is not None:
            self.ranges, self._ranges_result = self._ranges_result, None
        if (self.chunks is None and self.ranges is not None and self._chunks_ready.is_set()
                and self._chunks_result is not None):
            self.chunks, self._chunks_result = self._chunks_result, None
        return self.ranges

    def _frame_lists(self, vp, clip, settings):
        """{pass: (first index, index count) arrays} for this frame, or None: draw the whole buffer."""
        r = self._adopt_ranges()
        if r is None or not self.use_ranges or self._state_version == 0 or len(self._state_flags) != r.n:
            return None
        ghost = np.float32(settings.get("ghost_alpha", 0.1))
        planes = np.asarray(clip[0], dtype=np.float32)
        on = tuple(int(x) for x in clip[1])
        mode = int(clip[2]) if len(clip) > 2 else 0
        ch = self.chunks if (self.use_occlusion and self._indirect and not self.animated
                             and self._occ is not False) else None
        key = (self._state_version, float(ghost), np.asarray(vp).tobytes(), planes.tobytes(), on, mode,
               self._indirect, ch is not None)
        if key == self._lists_key:
            return self._lists
        # an animated model moves its vertices, so its boxes say nothing about where it is drawn
        where = (None, None) if self.animated else (vp, (planes, on, mode))
        masks = r.passes(self._state_flags, self._state_opacity, ghost, *where)
        lists = {}
        for name, mask in zip(self.PASSES, masks):
            first, count = r.runs(mask)
            if not self._indirect:
                first, count = r.bridge(first, count, self.LOOP_DRAWS)
            lists[name] = (first, count, int(count.sum()) // 3)
            if self._indirect and len(first):
                data = r.commands(first, count).tobytes()
                if data != self._cmd_data.get(name):
                    buf = self._cmd_buf.get(name)
                    if buf is None:
                        buf = self._cmd_buf[name] = self.ctx.buffer(reserve=max(len(r.order), 1) * 20, dynamic=True)
                    buf.orphan()
                    buf.write(data)
                    self._cmd_data[name] = data
                    buf.extra = {"draws": len(first), "triangles": lists[name][2]}
        if ch is not None and lists["opaque"][2] >= self.OCC_MIN_TRIANGLES:
            # All that decides where opaque surfaces are: per structure shown / ghosted / not cut (flag bits 1, 2,
            # 64) and opacity, the sections, and the view. Selection, hover and colours are not in it.
            state = (float(ghost), (self._state_flags & 67).tobytes(), self._state_opacity.tobytes(), key[3:6])
            lists["occ"] = {"state": state, "key": (state, key[2]), "ghost": ghost, "clip": (planes, on, mode),
                            "vp": np.array(vp, dtype=np.float64)}
        self._lists_key, self._lists = key, lists
        return lists

    # ------------------------------------------------------------------ covered pieces
    def _occlusion(self):
        """The GL objects of the covered test, or None where this context cannot run it."""
        if self._occ is None:
            made = {}
            try:
                ctx, ch = self.ctx, self.chunks
                made["depth_prog"] = ctx.program(vertex_shader=shaders.GEOMETRY_VS, fragment_shader=depth_only_fs())
                made["depth_vao"] = self._geo_vao(made["depth_prog"])
                made["reduce_prog"] = ctx.program(vertex_shader=shaders.FULLSCREEN_VS, fragment_shader=REDUCE_FS)
                made["reduce_vao"] = ctx.vertex_array(made["reduce_prog"], [])
                made["prog"] = ctx.program(vertex_shader=BOX_VS, fragment_shader=BOX_FS)
                made["boxes"] = ctx.buffer(np.hstack((ch.center, ch.half)).astype("f4").tobytes())
                made["on"] = ctx.buffer(reserve=ch.n, dynamic=True)
                made["seen"] = ctx.buffer(reserve=4 * ch.n, dynamic=True)
                made["vao"] = ctx.vertex_array(made["prog"], [(made["boxes"], "3f 3f/i", "in_center", "in_half"),
                                                              (made["on"], "1f1/i", "in_on")])
                made["cmd"] = ctx.buffer(reserve=20 * ch.n, dynamic=True)
                made.update(on_key=None, cmd_key=None, zeros=bytes(4 * ch.n))
                self._occ = made
            except Exception:           # noqa: BLE001 - no test on this context: the lists are drawn as before
                self._occ = made
                self._release_occlusion()
                self._occ = False
        if self._occ and self.occ_fbo is None:
            try:
                w, h = self.size
                s = max(int(self.OCC_SCALE), 1)
                self.occ_fbo = self.ctx.framebuffer((), self.depth_tex)
                self.occ_small_tex = self.ctx.depth_texture((-(-w // s), -(-h // s)))
                self.occ_small_tex.compare_func = ""
                self.occ_small = self.ctx.framebuffer((), self.occ_small_tex)
                self._occ["scale"] = s
            except Exception:           # noqa: BLE001
                self._release_occlusion()
                self._occ = False
        return self._occ or None

    def _release_occlusion(self):
        occ, self._occ = self._occ, None
        self._release_owned(("occ_fbo", "occ_small", "occ_small_tex"))
        for o in (occ.values() if isinstance(occ, dict) else ()):
            if hasattr(o, "release"):
                try:
                    o.release()
                except Exception:       # noqa: BLE001 - already gone with its context
                    pass

    def _draw_pieces(self, vao, mask):
        """Draws the pieces in mask in buffer order with one call; returns (triangles, draws)."""
        occ, ch = self._occ, self.chunks
        first, count = ch.runs(mask)
        triangles = int(count.sum()) // 3
        if len(first):
            key = mask.tobytes()
            if key != occ["cmd_key"]:
                occ["cmd"].orphan()
                occ["cmd"].write(DrawRanges.commands(first, count).tobytes())
                occ["cmd_key"] = key
            occ["cmd"].extra = {"draws": len(first), "triangles": triangles}
            vao.render_indirect(occ["cmd"], moderngl.TRIANGLES, count=len(first))
        return triangles, len(first)

    def _test_boxes(self, test, vp, pad):
        """True for the pieces in `test` whose grown box has a pixel at or in front of the depth in depth_tex."""
        occ, ch, ctx = self._occ, self.chunks, self.ctx
        key = test.tobytes()
        if key != occ["on_key"]:
            occ["on"].write((test.astype(np.uint8) * 255).tobytes())
            occ["on_key"] = key
        occ["seen"].write(occ["zeros"])
        w, h = self.size
        s = occ["scale"]
        small = self.occ_small
        try:
            small.depth_mask = True                     # the farthest depth of each block, written as depth
            small.use()
            ctx.depth_func = "1"
            self.depth_tex.use(0)
            occ["reduce_prog"]["u_depth"].value = 0
            occ["reduce_prog"]["u_scale"].value = s
            occ["reduce_vao"].render(moderngl.TRIANGLES, vertices=3)
            small.depth_mask = False                    # the boxes are tested against it and leave it as it is
            small.use()
            ctx.depth_func = "<="
            prog = occ["prog"]
            prog["u_viewproj"].write(_mat4_bytes(vp))
            prog["u_wrow"].value = tuple(float(x) for x in np.asarray(vp)[3])
            prog["u_pad"].value = float(pad)
            prog["u_floor"].value = float(BOX_FLOOR * (ch.extent[:3].max() + 1.0))
            prog["u_fit"].value = (w / (s * small.width), h / (s * small.height))
            occ["seen"].bind_to_storage_buffer(0)
            occ["vao"].render(moderngl.TRIANGLES, vertices=36, instances=ch.n)
            ctx.memory_barrier()
            return np.frombuffer(occ["seen"].read(), dtype="<u4") != 0
        finally:
            ctx.depth_func = "<"
            self.state_tex.use(0)

    def box_padding(self, proj):
        """World distance per unit of clip w by which a tested box is grown (see Chunks.padding).

        A box is tested at the centres of blocks of OCC_SCALE pixels, a surface shows at the centre of one pixel:
        the two lie less than 0.7072 * OCC_SCALE pixels apart on screen. The block's ray therefore passes, at the
        depth of the surface point, within that distance of it: inside the box once it is grown by as much, so
        the box is met at that depth or nearer. One more pixel covers rounding and the steps of the depth buffer.
        """
        w, h = self.size
        s = max(int(self.OCC_SCALE), 1)
        px, py = abs(float(proj[0, 0])), abs(float(proj[1, 1]))
        pixels = (0.7072 * s if s > 1 else 0.0) + 1.0
        return pixels * 2.0 / max(min(px * w, py * h), 1e-12)

    def _pieces(self, lists):
        """The opaque list again, piece by piece (the same tests on smaller boxes), made when first asked for."""
        o = lists["occ"]
        if "pieces" not in o:
            r, ch = self.ranges, self.chunks
            live, opaque = r.classify(self._state_flags, self._state_opacity, o["ghost"])[:2]
            o["shown"] = (live & opaque)[ch.struct] & ~ch.cut_away(o["clip"], self._state_flags)
            o["pieces"] = o["shown"] & ~ch.outside_view(o["vp"], ~r.inside_view(o["vp"]))
        return o["pieces"]

    def _draw_opaque_covered(self, lists, vp, proj, uniforms):
        """The opaque pass without the pieces that lie wholly behind other opaque surfaces. False: not done here.

        A view and state whose answer is final are drawn from it without a test. Otherwise:
        1. Depth only: the pieces that passed the last test (and those too near the eye to be tested), with the
           opaque shader stopped after its discards, so see-through and ghosted structures are not in that depth
           and a cut structure is there only with what the section leaves of it.
        2. The box of every piece on the opaque list is tested against that depth. A piece that owns a pixel of
           the whole-list picture lies, at that pixel, at or in front of everything drawn in step 1, so its box
           passes: nothing that shows can fail, whatever step 1 drew.
        3. The depth is cleared and the pieces that passed are drawn with the opaque shader, in buffer order: the
           frame holds what the whole list would put there, and equal depths fall the same way.
        4. If far more passed than step 1 drew (a jump of the camera, a system switched on, the first frame),
           the boxes are tested once more, against the depth step 3 left: that depth is the frame's own, so the
           answer is final and the next frame starts from it. Nothing is drawn for it.
        The first test of a view starts from what passed in the view before, so more passes than must (the depth
        has holes where new surfaces come into sight). When the view rests, the next frame starts from that
        answer, which holds all that shows: its depth is the frame's own and its answer is final.

        A frame of a moving view is not tested when that would send more triangles than the whole list holds
        (few systems shown, small datasets): False is returned, the whole list is drawn, and the test runs when
        the view rests. That is judged from the last final answer for this state at a similar list length, with
        no work per piece, or else from what passed before for this frame's pieces.

        An error raised in any of these steps (a driver that fails in a draw, in the test or in its read-back)
        ends the test for the session: the frame is put back as it was (_occlusion_failed), False is returned and
        the whole list is drawn, in this frame and in every later one.
        """
        occ = self._occlusion()
        if occ is None:
            return False
        try:
            return self._covered_frame(occ, lists, vp, proj, uniforms)
        except Exception as exc:        # noqa: BLE001 - whatever fails in the test must not cost the picture
            self._occlusion_failed(exc, uniforms)
            return False

    def _occlusion_failed(self, exc, uniforms):
        """An error in a frame of the covered test: the test is off for the rest of the session, and the frame is
        put back to where the opaque pass began, so that the whole list drawn next gives the frame it gives with
        use_occlusion False. The steps of the test may have left their own framebuffer bound, depth from the
        depth-only draw in the frame's depth texture, some shaded pieces in the frame, the depth comparison
        changed and the depth texture on unit 0."""
        ctx = self.ctx
        errors = []
        for _ in range(8):              # the error flags a driver set are read out, or later checks would meet them
            code = ctx.error
            if code == "GL_NO_ERROR":
                break
            errors.append(code)
        log.warning("covered test: off for this session, the whole lists are drawn instead: %r%s", exc,
                    f" ({', '.join(errors)})" if errors else "")
        self._occ_seen = self._occ_need = self._occ_key = self._occ_hint = None
        self._occ_final = False
        self.last_stats.pop("covered", None)
        self.last_stats.pop("opaque", None)
        try:
            self.gbuffer.use()          # the test's framebuffers are deleted next: none of them may stay bound
        finally:
            self._release_occlusion()
            self._occ = False           # _frame_lists makes no piece lists from the next frame on
        ctx.disable(moderngl.BLEND | moderngl.CULL_FACE)
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.depth_func = "<"
        self.state_tex.use(0)
        self.mats_tex.use(1)
        self.albedo.use(ALBEDO_UNIT)
        self.anim_tex.use(ANIM_UNIT)
        self.gbuffer.depth_mask = True
        self.gbuffer.use()              # binds it with its own viewport, scissor, colour masks and depth mask
        self.gbuffer.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        uniforms(self.p_opaque)

    def _covered_frame(self, occ, lists, vp, proj, uniforms):
        """The steps of _draw_opaque_covered for one frame (an error raised here is caught there)."""
        ch, o = self.chunks, lists["occ"]
        key = (o["key"], self.size, self.OCC_SCALE)
        again = key == self._occ_key                # same view and state as the last frame
        if again and self._occ_final:
            tri, n = self._draw_pieces(self.vao_opaque, self._occ_need)
            self.last_stats["opaque"] = (tri, n)
            self.last_stats["covered"] = (self._occ_total[0], 0, tri, self._occ_total[1], int(self._occ_need.sum()))
            return True
        listed, hint = lists["opaque"][2], self._occ_hint
        if (not again and hint is not None and hint[2] and hint[0] == o["state"]
                and 0.7 * hint[1] <= listed <= 1.3 * hint[1]):
            self._occ_key, self._occ_need, self._occ_final = key, None, False
            return False
        cand = self._pieces(lists)
        total = int(ch.count[cand].sum()) // 3
        refine = again and self._occ_need is not None
        pad = self.box_padding(proj)
        near = ch.at_near(vp, pad)
        seen = self._occ_seen
        if seen is None or len(seen) != ch.n:
            seen = np.zeros(ch.n, dtype=bool)
        start, test = (self._occ_need if refine else cand & (seen | near)), cand & ~near
        # a moving frame sends about what passes twice over (steps 1 and 3) and pays for the test itself
        if not again and 2 * (int(ch.count[start].sum()) // 3) + self.OCC_OVERHEAD_TRIANGLES >= total:
            self._occ_key, self._occ_need, self._occ_final = key, None, False
            return False
        passed = np.zeros(ch.n, dtype=bool)
        tri0 = n0 = 0
        if test.any():
            self._occ_key = None                        # an error below must not leave a half-made answer
            fbo = self.occ_fbo
            fbo.use()
            uniforms(occ["depth_prog"])
            tri0, n0 = self._draw_pieces(occ["depth_vao"], start)
            passed = self._test_boxes(test, vp, pad)
            fbo.clear(depth=1.0)
            self.gbuffer.use()
        need = cand & (passed | near)
        tri1, n1 = self._draw_pieces(self.vao_opaque, need)
        final = refine or not test.any()
        if not final and tri1 > 1.25 * tri0 + self.OCC_LOOSE_TRIANGLES:
            need = cand & (self._test_boxes(test, vp, pad) | near)
            self.gbuffer.use()
            final = True
        # what passed is remembered for the next view; a piece outside this view keeps its last answer, one
        # that is switched off or cut away loses it (answers from other states would only pile up)
        self._occ_seen = np.where(cand, need, seen & o["shown"])
        self._occ_need, self._occ_key, self._occ_final = need, key, final
        self._occ_total = (total, int(cand.sum()))
        if final:
            kept = int(ch.count[need].sum()) // 3
            self._occ_hint = (o["state"], listed, 2 * kept + self.OCC_OVERHEAD_TRIANGLES >= total)
        self.last_stats["opaque"] = (tri0 + tri1, n0 + n1)
        self.last_stats["covered"] = (total, tri0, tri1, int(cand.sum()), int(need.sum()))
        return True

    def _draw_pass(self, vao, name, lists):
        """One geometry pass: the structures on its list, in buffer order (the whole buffer when there is no list)."""
        if lists is None:
            vao.render(moderngl.TRIANGLES)
            self.last_stats[name] = (self.index_count // 3, 1)
            return
        first, count, triangles = lists[name]
        self.last_stats[name] = (triangles, len(first))
        if not len(first):
            return
        if self._indirect:
            vao.render_indirect(self._cmd_buf[name], moderngl.TRIANGLES, count=len(first))
            return
        for f, c in zip(first.tolist(), count.tolist()):
            vao.render(moderngl.TRIANGLES, vertices=c, first=f)

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
                self.p_final, self.p_fxaa, self.p_gather, self.gather_vao, self.gather_fbo, self.gather_tex, self.vbo, self.ibo, self.aux, self.anim, self.state_tex, self.mats_tex,
                self.anim_tex, self.noise_tex, self.albedo, *self._cmd_buf.values()]
        self._release_occlusion()
        self._occ = False
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
        self._state_opacity = np.asarray(tex[1, :len(self.ds.structures), 0], dtype=np.float32).copy()
        self._state_version = getattr(self, "_state_version", 0) + 1     # a new state means new draw lists
        # (2, blocks * WIDTH, 4) -> (blocks * 2, WIDTH, 4): row 2*b + k holds row k of block b
        blocks = self.state_blocks
        full = np.zeros((2, blocks * STATE_TEX_WIDTH, 4), dtype=np.float32)
        m = min(full.shape[1], tex.shape[1])
        full[:, :m] = tex[:, :m]
        packed = full.reshape(2, blocks, STATE_TEX_WIDTH, 4).transpose(1, 0, 2, 3).reshape(blocks * 2, STATE_TEX_WIDTH, 4)
        self.state_tex.write(np.ascontiguousarray(packed).tobytes())

    _CAP_OBJECTS = ("vao_cap", "vao_parity", "capmix_vao", "p_cap", "p_parity", "p_capmix")
    _CAP_TARGETS = ("parity_fbo", "cap_fbo", "parity_tex", "cap_color", "cap_normal", "cap_id", "cap_zp", "cap_key")
    _TARGETS = ("gbuffer", "mask_fbo", "ao_fbo", "blur_fbo", "hdr_fbo", "ldr_fbo",
                "color_tex", "normal_tex", "id_tex", "depth_tex", "mask_tex", "mask_depth",
                "ao_tex", "blur_tex", "hdr_tex", "ldr_tex", "occ_fbo", "occ_small", "occ_small_tex") + _CAP_TARGETS

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
                        self.state_tex.write(temporary.tobytes(), viewport=(*state_texel(sid), 1, 1))
                        restored.append((sid, original))
                for first, count in boundaries:
                    self.vao_parity.render(moderngl.TRIANGLES, vertices=count, first=first)
            finally:
                # Restore exact flags/colours before coloured caps and all later passes.
                for sid, original in restored:
                    self.state_tex.write(original.tobytes(), viewport=(*state_texel(sid), 1, 1))
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
        self.last_stats = {}
        lists = None if slice_only else self._frame_lists(vp, clip, settings)
        if not slice_only:
            def uniforms(prog):
                self._set_geometry_uniforms(prog, vp, view, eye, key, fill, settings, clip)
                self._set(prog, "u_pass", 0)

            if lists is None or "occ" not in lists or not self._draw_opaque_covered(lists, vp, proj, uniforms):
                self._draw_pass(self.vao_opaque, "opaque", lists)
        if (self.cap_depth or slice_only) and any(clip[1]):
            self._draw_caps(vp, view, eye, key, fill, settings, clip, slice_only=slice_only)

        # 2. selection mask (selected structures, depth-tested only among themselves)
        if has_selection and not slice_only:
            self.mask_fbo.use()
            self.mask_fbo.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
            self._set_geometry_uniforms(self.p_mask, vp, view, eye, key, fill, settings, clip)
            self._set(self.p_mask, "u_pass", 2)
            self._draw_pass(self.vao_mask, "mask", lists)

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
        self._set(p, "u_bg_spot", self._rgb(settings, "bg_spot", "#303539"))
        self._set(p, "u_bg_spot_strength", float(settings.get("bg_spot_strength", 0.0)))
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
            self._draw_pass(self.vao_transparent, "transparent", lists)
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
        target.scissor = None       # the pass must cover the whole window whatever an earlier pass left behind
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

    def _gather(self, points):
        """(id + 1, depth) at each GL pixel in points with one readback per GATHER_MAX points.

        Returns an (N, 2) float32 array (NaN where the point is outside the frame or a read failed).
        Sampling the same gbuffer textures the single-pixel reads use gives the same values.
        """
        out = np.full((len(points), 2), np.nan, dtype=np.float32)
        w, h = self.size
        if not self.frame_ok or not len(points):
            return out
        previous_fbo = self.ctx.fbo
        previous_viewport = self.ctx.viewport
        if previous_fbo is None:
            return out
        pts = np.asarray(points, dtype=np.int64).reshape(-1, 2)
        inside = (pts[:, 0] >= 0) & (pts[:, 0] < w) & (pts[:, 1] >= 0) & (pts[:, 1] < h)
        idx = np.flatnonzero(inside)
        try:
            # No scissor save/restore: Framebuffer.use() applies each framebuffer's own scissor state, and the
            # scissor getter reports the box even when the test is off, so writing it back would switch the
            # test ON for the caller's framebuffer (the window) with whatever size that box had.
            self.id_tex.use(0)
            self.depth_tex.use(1)
            self._set(self.p_gather, "u_id", 0)
            self._set(self.p_gather, "u_depth", 1)
            for start in range(0, len(idx), self.GATHER_MAX):
                chunk = idx[start:start + self.GATHER_MAX]
                buf = np.zeros((self.GATHER_MAX, 2), dtype=np.int32)
                buf[:len(chunk)] = pts[chunk]
                self.p_gather["u_pts"].write(buf.tobytes())
                self.gather_fbo.use()
                self.gather_fbo.viewport = (0, 0, self.GATHER_MAX, 1)
                self.gather_vao.render(vertices=3)
                data = np.frombuffer(self.gather_fbo.read(components=4, dtype="f4"), dtype=np.float32)
                out[chunk] = data.reshape(self.GATHER_MAX, 4)[:len(chunk), :2]
        except moderngl.Error:
            out[:] = np.nan
        finally:
            previous_fbo.use()
            self.ctx.viewport = previous_viewport
        return out

    def pick_many(self, points):
        """Structure ids (-1 for none) at several GL pixels, read back together. Same rules as pick()."""
        values = self._gather(points)[:, 0] if len(points) else np.zeros(0, dtype=np.float32)
        ids = []
        for value in values:
            ok = np.isfinite(value) and 1 <= value <= self.ds.n and abs(value - round(float(value))) <= 0.001
            ids.append(int(round(float(value))) - 1 if ok else -1)
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
        """Depth buffer values at pixel positions [(x, y), ...] (GL coordinates), read back together."""
        values = self._gather(points)[:, 1] if len(points) else []
        return [float(d) if np.isfinite(d) and 0 <= d <= 1 else None for d in values]
