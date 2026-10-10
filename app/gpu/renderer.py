"""WgpuRenderer: the model viewer's frame on wgpu (static scenes), with compact GPU geometry and a visibility buffer.

The pass order, targets, formats and uniform values are those of the GL renderer's ``render`` (app/viewer/renderer.py):

  backdrop          full-screen gradient (GL: drawn into the MSAA colour buffer, so every uncovered sample holds it)
  visibility pass   one indexed draw per part (split every 2**prim_bits triangles) into an MSAA id target
                    (r32uint, or rgba8uint when r32uint cannot be multisampled) plus depth32float:
                    id = (draw_slot << prim_bits) | primitive_index, slot 0 = background. Rendered bottom-up with GL's
                    row order and sample pattern.
  geometry resolve  (resolve.wgsl fs_geom) GL's single-sample pre-pass: for each pixel the front-most triangle among those
                    of its samples that contains the pixel CENTRE, none: background. Writes tri (r32uint), id (rg32float:
                    item + 1, flags) and nd (rgba32float: view-space normal, linear depth).
  SSAO + blur       post.py, reading the previous frame's resolved colour (`opaque`) exactly as GL's u_prev
  shaded resolve    (resolve.wgsl fs_shade) GL's MSAA colour buffer, resolved: each distinct triangle of a pixel's samples is
                    shaded once at the pixel centre (shading.wgsl, explicit quad derivatives) and weighted by the samples it
                    covers; uncovered samples hold the backdrop; 16-bit float like GL's buffer. Written to `opaque`.
  composite         post.py (accum / weight are zero: no translucent items yet)
  final             flips the GL-ordered picture into the target and scales it to out_size.

All intermediate textures keep GL's row order (row 0 = bottom); the target and every readback array are top row first.

Cut faces (caps.py): see the cap steps in render(). Refused by set_model (NotImplementedError, the Qt view then builds the
OpenGL viewport): alpha-cut textures. Not supported: the vertex-pulling raster path for adapters without
"primitive-index".
"""
from __future__ import annotations

import logging
import math
import os
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import wgpu

from app.viewer import lod as _lod
from app.viewer.environment import make_env, sh9_irradiance
from app.viewer.renderer import (DEFAULT_RIG, DEFAULT_WORLD, FrameState, Renderer as _GL, Settings,  # noqa: F401
                                 _frustum_planes, _look_key, _transparent_pass, backdrop_linear)
from . import cutclass
from . import geometry as geo
from .caps import CapPasses
from .clusters import ClusterError
from .cull import ClipState, ClusterCuller, FrameParts
from .cull_policy import CullGovernor
from .oit import OitDraw, OitPass
from .post import PostPasses
from .shade_split import ShadeSplit
from .shading_uniforms import FIELD_BY_NAME, SIZE as SHADE_SIZE, pack_shading_uniforms

log = logging.getLogger("anatomy.gpu")
WGSL = Path(__file__).with_name("wgsl")
BU, TU, SS = wgpu.BufferUsage, wgpu.TextureUsage, wgpu.ShaderStage
FRAME_BYTES = 240
DRAW_FLOATS = 40
PTAB_STRIDE = 20
STORAGE_PER_STAGE = 6                     # at most this many storage buffers bound by any stage of any pipeline (the Metal floor is 8)
MAX_PAGES = STORAGE_PER_STAGE - 2        # the resolve binds the table buffer, the culler's decode table and up to MAX_PAGES page buffers
CULL_MIN_TRIS = 1_000_000                # drawn triangles from which the cluster culler runs (ANATOMY_CULL=auto); see docs/renderer-perf
CULL_LAY_BYTES = 80                      # CullLay (wgsl/cull_tables.wgsl): five vec4<u32>
DEC_CRO, DEC_LAY = 8, 9                  # bindings of the decode tables in the resolve's group 2
SHADE_WORDS = SHADE_SIZE // 4
TAB_ALIGN = 64                           # words (256 bytes: the storage offset alignment limit's upper bound)
GL_TO_WGPU_Z = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0.5, 0.5], [0, 0, 0, 1]], dtype=np.float64)
DRAW_NOCLIP, DRAW_MIRRORED, DRAW_SELECTED = 1, 2, 4
ID_FORMATS = ("r32uint", "rgba8uint")
ADD = {"operation": "add", "src_factor": "one", "dst_factor": "one"}

# ShadeU fields that belong to a part's look / transform (GL sets them per draw); everything else is frame-wide.
PER_PART = ("u_flip", "u_noclip", "u_weight", "u_batched", "u_base", "u_alpha", "u_rough", "u_metal", "u_f0", "u_wrap",
            "u_emis", "u_use_vcol", "u_alpha_cut", "u_has_tex", "u_stripe", "u_stripe_p", "u_shorten", "u_stripe_a",
            "u_stripe_b", "u_mottle", "u_mottle_p", "u_mottle_a", "u_mottle_b", "u_detail_on", "u_detail", "u_highlight",
            "u_highlight_col")
assert all(n in FIELD_BY_NAME for n in PER_PART)


class RendererError(RuntimeError):
    pass


class _Null:
    """Stands in for the GL textures the GL renderer's uniform code touches."""
    layers = 6

    def use(self, *a, **k):
        return None


class _Rec(dict):
    """A uniform recorder: the GL renderer's `u(name, value)` calls land in a dict."""

    def __init__(self):
        super().__init__()
        # GL's code writes the SH coefficients raw through the program member: prog.get("u_sh").write(bytes)
        self.prog = SimpleNamespace(get=lambda name, default=None: self if name == "u_sh" else default)

    def __call__(self, name, value):
        self[name] = value

    def write(self, data):
        self["u_sh"] = np.frombuffer(data, dtype=np.float32).reshape(9, 3).copy()


def _max_samples(device, fmt):
    """Largest sample count (8, 4, 2) the device can create for both `fmt` and depth32float, else 1."""
    for n in (8, 4, 2):
        try:
            for f in (fmt, "depth32float"):
                device.create_texture(size=(8, 8, 1), format=f, sample_count=n, usage=TU.RENDER_ATTACHMENT)
            return n
        except Exception:
            continue
    return 1


def _prelude_ids(id_fmt):
    """WGSL for the visibility module: the id output type."""
    if id_fmt == "r32uint":
        return "alias IdOut = u32;\nfn pack_id(id: u32) -> IdOut { return id; }"
    return ("alias IdOut = vec4<u32>;\n"
            "fn pack_id(id: u32) -> IdOut { return vec4<u32>(id & 255u, (id >> 8u) & 255u, (id >> 16u) & 255u, id >> 24u); }")


# The resolve reads ids through these: an id written by the culler (bit 31 set, cull_decode.wgsl) becomes the renderer's own
# (draw slot << bits) | primitive, so everything after the load is the same code as for plain ids.
_DECODE_IDS = """fn decode_id(raw: u32) -> u32 {
    if (cull_is_culled(raw)) {
        let d = cull_decode(raw, frame.info.x);
        return (d.x << frame.info.x) | d.y;
    }
    return raw;
}
fn load_id(p: vec2<i32>, s: i32) -> u32 { return decode_id(load_id_raw(p, s)); }
fn load_ids(p: vec2<i32>) -> array<u32, 8> {
    var ids: array<u32, 8>;
    var last_raw = 0u;
    var last = 0u;
    for (var s = 0; s < i32(SAMPLES); s++) {
        let raw = load_id_raw(p, s);
        if (raw != last_raw) {
            last_raw = raw;
            last = decode_id(raw);
        }
        ids[s] = last;
    }
    return ids;
}"""


def _decode_wgsl():
    """cull_tables.wgsl + cull_decode.wgsl with the decode group moved into group 2 of the resolve (bindings DEC_CRO, DEC_LAY)."""
    dec = _read_text("cull_decode.wgsl")
    for b, to in ((0, DEC_CRO), (1, DEC_LAY)):
        old = f"@group(__GROUP__) @binding({b})"
        assert dec.count(old) == 1
        dec = dec.replace(old, f"@group(2) @binding({to})")
    assert "__GROUP__" not in re.sub(r"//.*", "", dec)
    return _read_text("cull_tables.wgsl") + "\n" + dec


def _prelude_resolve(id_fmt, samples, n_pages, page0, compressed=False):
    """Generated WGSL for the resolve module: sample access (group 2) and the pages of one pass (group 3, geometry.geom_prelude)."""
    out = [f"const SAMPLES: u32 = {samples}u;"]
    ms = samples > 1
    ty_id = "texture_multisampled_2d<u32>" if ms else "texture_2d<u32>"
    out.append(f"@group(2) @binding(0) var vis_id: {ty_id};")
    out.append("@group(2) @binding(2) var bg_tex: texture_2d<f32>;")
    out.append(("@group(2) @binding(6) var vis_depth: texture_depth_multisampled_2d;" if ms else
                "@group(2) @binding(6) var vis_depth: texture_depth_2d;") + "\n@group(2) @binding(7) var cap_col: texture_2d<f32>;")
    out.append(f"fn load_depth(p: vec2<i32>, s: i32) -> f32 {{ return textureLoad(vis_depth, p, {'s' if ms else '0'}); }}")
    out.append("@group(1) @binding(0) var<uniform> pass_info: vec4<u32>;")
    out.append("const CAP_SAMPLE: u32 = 0xffffffffu;\n"
               "fn q24(x: f32) -> f32 { return round(clamp(x, 0.0, 1.0) * 16777215.0) / 16777215.0; }\n"
               "fn cap_covers(zp: f32, sample_depth: f32) -> bool { return zp > 0.0 && q24(zp) < q24(sample_depth); }")
    s = "s" if ms else "0"
    if id_fmt == "r32uint":
        out.append(f"fn load_id_raw(p: vec2<i32>, s: i32) -> u32 {{ return textureLoad(vis_id, p, {s}).x; }}")
    else:
        out.append(f"fn load_id_raw(p: vec2<i32>, s: i32) -> u32 {{ let v = textureLoad(vis_id, p, {s}); "
                   f"return v.x | (v.y << 8u) | (v.z << 16u) | (v.w << 24u); }}")
    out.append(_DECODE_IDS)
    out.append(f"const GROUP_PAGE0: u32 = {page0}u;\nconst GROUP_PAGES: u32 = {n_pages}u;")
    out.append(geo.geom_prelude(n_pages, 3, 0, compressed=compressed))
    return "\n".join(out)


# Surface features of a look that shading.wgsl can switch off per pipeline (its `override FEAT_*` constants).
FEAT_STRIPE, FEAT_MOTTLE, FEAT_TEX, FEAT_DETAIL = 1, 2, 4, 8
FEAT_MORPH, FEAT_ANIM = 16, 32        # morph.wgsl: some drawn item has a morph weight / procedural animation (frame level, not per look)
FEAT_ALL = 15
FEAT_FRAME_ALL = FEAT_ALL | FEAT_MORPH | FEAT_ANIM      # every switch on (nothing compiled out)
_FEAT_NAMES = (("FEAT_STRIPE", FEAT_STRIPE), ("FEAT_MOTTLE", FEAT_MOTTLE), ("FEAT_TEX", FEAT_TEX), ("FEAT_DETAIL", FEAT_DETAIL))
_MORPH_NAMES = (("FEAT_MORPH", FEAT_MORPH), ("FEAT_ANIM", FEAT_ANIM))


AO_SCALES = {"full": (1, 1), "gi": (1, 2), "half": (2, 2)}      # ANATOMY_AO_SCALE -> (ao_scale, gi_scale) of PostPasses


def ao_gi_scales():
    """(ao_scale, gi_scale) for PostPasses: ANATOMY_AO_SCALE = full (AO and GI at full resolution, the GL picture), gi
    (default: AO full, the GI term at half resolution) or half (both at half). See docs/renderer-perf/port-changes.md."""
    v = os.environ.get("ANATOMY_AO_SCALE", "gi").strip().lower() or "gi"
    if v not in AO_SCALES:
        log.warning("ANATOMY_AO_SCALE=%r is not one of %s; using 'gi'", v, "/".join(AO_SCALES))
        v = "gi"
    return AO_SCALES[v]


def _look_features(rec):
    """FEAT_* bits of a look record: the features whose per-look uniform switch is on."""
    return ((FEAT_STRIPE if int(rec.get("u_stripe", 0)) == 1 else 0) | (FEAT_MOTTLE if int(rec.get("u_mottle", 0)) == 1 else 0)
            | (FEAT_TEX if int(rec.get("u_has_tex", 0)) == 1 else 0) | (FEAT_DETAIL if int(rec.get("u_detail_on", 0)) == 1 else 0))


def _apply_look_wgsl():
    """apply_look(rec) selects the look record `rec` (a ShadeU in the `looks` section of the table buffer): it only sets the
    private word offset `cur_lb`. Each per-part field has a reader lk_<name>() that loads it from the table where it is used,
    bit-exact (floats and ints are bitcast); see _su_reads. No copy of the 624-byte ShadeU is made."""
    lines = ["fn apply_look(rec: u32) {", f"    cur_lb = tinfo.z + rec * {SHADE_WORDS}u;", "}"]
    for n in PER_PART:
        f = FIELD_BY_NAME[n]
        w = f.offset // 4
        ty = {"f32": "f32", "i32": "i32", "u32": "u32"}[f.base]
        if f.shape == ():
            lines.append(f"fn lk_{n}() -> {ty} {{ return bitcast<{ty}>(tab_w(cur_lb + {w}u)); }}")
        else:
            k = f.shape[0]
            parts = ", ".join(f"bitcast<{ty}>(tab_w(cur_lb + {w + j}u))" for j in range(k))
            lines.append(f"fn lk_{n}() -> vec{k}<{ty}> {{ return vec{k}<{ty}>({parts}); }}")
    return "\n".join(lines)


def _su_reads(src):
    """Rewrite every `su.u_x` of the resolve module: per-part fields (PER_PART) -> lk_u_x() (read from the look record of the
    shaded part), the rest -> sg.u_x (the frame-wide uniform). The values are those of the former private copy
    (`su = sg; apply_look(rec)` overwrote exactly the PER_PART fields), but the compiler loads them where they are used
    instead of holding or spilling a 624-byte copy per shaded triangle (docs/renderer-perf/port-changes.md)."""
    return re.sub(r"\bsu\.(u_\w+)", lambda m: (f"lk_{m.group(1)}()" if m.group(1) in PER_PART else f"sg.{m.group(1)}"), src)


def _read_text(name):
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
    elif kind == "tf":
        e["texture"] = {"sample_type": "unfilterable-float", "view_dimension": "2d"}
    elif kind == "tl":
        e["texture"] = {"sample_type": "float", "view_dimension": "2d"}
    elif kind == "td":
        e["texture"] = {"sample_type": "depth", "view_dimension": "2d", "multisampled": kw.get("ms", False)}
    elif kind == "ta":
        e["texture"] = {"sample_type": "float", "view_dimension": "2d-array"}
    elif kind == "s":
        e["sampler"] = {"type": "filtering"}
    return e


def _srgb_to_linear(c):
    c = c.astype(np.float32) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb8(c):
    c = np.clip(c, 0.0, 1.0)
    return np.rint(np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055) * 255.0).astype(np.uint8)


def mip_chain(rgba):
    """(h, w, 4) uint8 sRGB+alpha -> all mip levels down to 1x1, 2x2 box filtered in linear light (alpha linear), the size
    halving (rounded down) per level as GL's glGenerateMipmap."""
    levels = [rgba]
    cur = rgba
    while cur.shape[0] > 1 or cur.shape[1] > 1:
        h, w = cur.shape[:2]
        h2, w2 = max(h // 2, 1), max(w // 2, 1)
        lin = np.empty((h, w, 4), np.float32)
        lin[..., :3] = _srgb_to_linear(cur[..., :3])
        lin[..., 3] = cur[..., 3] / 255.0
        if h % 2 == 0 and w % 2 == 0:
            small = lin.reshape(h2, 2, w2, 2, 4).mean(axis=(1, 3))
        else:                                   # odd sizes: area average of each destination texel's source span
            ys = np.linspace(0, h, h2 + 1).astype(int)
            xs = np.linspace(0, w, w2 + 1).astype(int)
            small = np.empty((h2, w2, 4), np.float32)
            for j in range(h2):
                for i in range(w2):
                    small[j, i] = lin[ys[j]:max(ys[j + 1], ys[j] + 1), xs[i]:max(xs[i + 1], xs[i] + 1)].mean(axis=(0, 1))
        nxt = np.empty((h2, w2, 4), np.uint8)
        nxt[..., :3] = _linear_to_srgb8(small[..., :3])
        nxt[..., 3] = np.rint(np.clip(small[..., 3], 0, 1) * 255.0).astype(np.uint8)
        levels.append(nxt)
        cur = nxt
    return levels


def _align(n, a=256):
    return (n + a - 1) // a * a


class WgpuRenderer:
    """GL Renderer's public API on wgpu. ``gpu`` is app.gpu.device.Gpu (or anything with device, queue, features,
    limits, info, prim_index)."""

    def __init__(self, gpu, page_bytes=None, resolve_group_pages=None, prim_bits=20, profile=False, max_pages=None,
                 cull=None, cull_min_tris=None):
        self.gpu = gpu
        self.device, self.queue = gpu.device, gpu.queue
        feats = set(getattr(gpu, "features", None) or self.device.features)
        self.features = feats
        if not getattr(gpu, "prim_index", "primitive-index" in feats):
            raise RendererError("this adapter has no 'primitive-index' feature (vertex-pulling path is not built yet)")
        self.gl_info = getattr(gpu, "info", "wgpu")
        self.limits = dict(getattr(gpu, "limits", None) or self.device.limits)
        self.page_bytes = int(page_bytes) if page_bytes else geo.page_limit(self.device)
        n_stor = int(self.limits.get("max_storage_buffers_per_shader_stage",
                                     self.limits.get("max-storage-buffers-per-shader-stage", 8)))
        # Layout v2: the fragment stage of the resolve binds the table buffer, the culler's decode table and up to max_pages page
        # buffers; every other stage binds fewer. K x page_bytes is the geometry capacity (a model needing more pages raises GeometryError).
        k = max_pages if max_pages is not None else resolve_group_pages
        self.max_pages = max(1, min(int(k) if k else MAX_PAGES, MAX_PAGES, n_stor - 2))
        self.prim_bits_max = int(prim_bits)
        self.profile = bool(profile) and "timestamp-query" in feats
        self.ts_period_ns = 1.0
        # ---- id format and sample counts (r32uint has no multisampling without adapter-specific format features)
        self.sample_support = {f: _max_samples(self.device, f) for f in ID_FORMATS}
        self.id_format = "r32uint" if self.sample_support["r32uint"] >= self.sample_support["rgba8uint"] else "rgba8uint"
        self.max_samples = self.sample_support[self.id_format]
        # ---- state like the GL renderer's
        # ---- cluster culling (cull.py). cull_mode: "on" / "off" / "auto" (ANATOMY_CULL); "auto" culls the frames that draw
        # at least cull_min_tris triangles. The mode also decides, at set_model, whether the geometry is stored in cluster order
        # (static models only; "auto" only when the model's level-0 triangle total reaches cull_min_tris), so set it before.
        mode = (cull if cull is not None else os.environ.get("ANATOMY_CULL", "auto")).strip().lower()
        self.cull_mode = mode if mode in ("on", "off", "auto", "plain") else "auto"   # "plain": cluster-ordered geometry, never culled (diagnostic)
        self.cull_min_tris = int(cull_min_tris if cull_min_tris is not None else
                                 float(os.environ.get("ANATOMY_CULL_MIN_TRIS") or CULL_MIN_TRIS))
        # cut views: classify draws against the cut planes (cutclass.py); ANATOMY_CUT_CLASSIFY=0 sends every draw through the discard
        self.classify_cut = os.environ.get("ANATOMY_CUT_CLASSIFY", "1") != "0"
        self.split = ShadeSplit(self)                    # shaded resolve with the extra triangles of edge pixels in a compute pass (ANATOMY_SHADE_SPLIT)
        self._cut_cache = (None, None, None)
        self.culler = None
        self.gov = None                      # auto: per-frame choice between the culler and the plain draw (cull_policy.py)
        self.culled_frame = False            # did the last frame go through the culler
        self.cull_accept_all = False         # ... with every cluster accepted (compressed geometry below cull_min_tris)
        gc_mode = os.environ.get("ANATOMY_GEOM_COMPRESS", "auto").strip().lower()
        self.geom_compress = gc_mode if gc_mode in ("on", "off", "auto", "stage1") else "auto"      # compressed geometry (cluster-ordered models)
        self._cmp = 0                        # the current geometry's stage: 0 plain, 1 compressed indices, 2 + quantised positions (keys of every module / pipeline)
        self.cull_stats = None
        self.model = None
        self.geom = None
        self.size = None
        self.samples = None
        self.last_vp = np.eye(4)
        self.last_camera = None
        self.frame_ok = False
        self._lod = None
        self._level = {}
        self._xf = {}
        self._xf_key = None
        self._spheres = self._scales = None
        self._fs = None
        self._ids_cache = None
        self.t = {}
        self.v = {}
        self.timings = {}
        self.last_table = None               # (n + 1, 40) float32 draw table of the last frame (slot -> record)
        self.last_draws = []                 # [(slot, part index, level, first_index, index_count)] of the last frame
        self.last_prim_bits = 20
        self._pipes = {}
        self._modules = {}
        self._warned = set()
        self._frame_ub = self.device.create_buffer(size=FRAME_BYTES, usage=BU.UNIFORM | BU.COPY_DST, label="frame")
        self._sg = self.device.create_buffer(size=SHADE_SIZE, usage=BU.UNIFORM | BU.COPY_DST, label="shade_global")
        self._tab = None                     # the one table buffer (tables.wgsl)
        self._tinfo = self.device.create_buffer(size=16, usage=BU.UNIFORM | BU.COPY_DST, label="tinfo")
        self._tab_caps = (0, 0)              # (draw rows, look records) the buffer has room for
        self._tab_off = {}                   # section -> first word
        self._ptab_words = None
        self._bg0_vis = self._bg0_res = self._bg0_cmp = None
        self._dummy = self.device.create_buffer(size=16, usage=BU.STORAGE, label="dummy")
        self._look_idx, self._look_bytes, self._looks_written = {}, [], 0
        self._look_feat, self._frame_feat = [], FEAT_FRAME_ALL      # per look: FEAT_* bits it uses; OR over the frame's draws
        self._item_state = None
        self.items_tex = None
        self._anim_key = None
        self._anim_data = None
        self._tex = {}                       # image index -> (texture, view)
        self._tex_slots = []                 # image indices that get a shade-pass slot (1 + position)
        self._look_tex = {}                  # looks-table record -> image index (u_has_tex == 1)
        self._pass_ub = {}
        self._env_key = None
        self.env_spec = self.env_src = None
        self.env_sh = None
        self.rig, self.world = DEFAULT_RIG, DEFAULT_WORLD
        self.model_diag = 1.0
        self._fake = SimpleNamespace(_texture=lambda i: _Null())
        ao, gi = ao_gi_scales()
        self.post = PostPasses(self.device, ao_scale=ao, gi_scale=gi)
        self.oit = OitPass(self.device, flip_y=True, depth_format="depth32float", aniso=8)
        self.caps = CapPasses(self.device)
        self._dec_dummy = None
        self._bg_vis_none = None
        self._cap_none = self.device.create_texture(size=(1, 1, 1), format="rgba32float", usage=TU.TEXTURE_BINDING,
                                                    label="cap_none").create_view()
        self._capon = 0
        self._bg_vis_cap = None
        self._bg_vis_size = None
        self._cap_col_v = None
        self.oit_t = None
        self._oit_rec = _Rec()
        self._items_v = self._spec_v = None
        self._layouts()
        self._gather = {}
        self._qs = None
        if self.profile:
            self._qs = self.device.create_query_set(type="timestamp", count=16)
            self._qbuf = self.device.create_buffer(size=128, usage=BU.QUERY_RESOLVE | BU.COPY_SRC | BU.COPY_DST)
        d = self.device
        self._s_ao = d.create_sampler(mag_filter="linear", min_filter="linear", address_mode_u="clamp-to-edge",
                                      address_mode_v="clamp-to-edge")
        self._s_tex = d.create_sampler(mag_filter="linear", min_filter="linear", mipmap_filter="linear",
                                       address_mode_u="repeat", address_mode_v="repeat", max_anisotropy=8)
        self._s_final = d.create_sampler(mag_filter="linear", min_filter="linear", address_mode_u="clamp-to-edge",
                                         address_mode_v="clamp-to-edge")
        white = d.create_texture(size=(1, 1, 1), format="rgba8unorm", usage=TU.TEXTURE_BINDING | TU.COPY_DST)
        d.queue.write_texture({"texture": white, "mip_level": 0, "origin": (0, 0, 0)},
                              np.full((1, 1, 4), 255, np.uint8), {"bytes_per_row": 4, "rows_per_image": 1}, (1, 1, 1))
        self._white = white
        self._final_ub = d.create_buffer(size=16, usage=BU.UNIFORM | BU.COPY_DST, label="final_dims")

    # ------------------------------------------------------------------ layouts and pipelines
    def _layouts(self):
        d = self.device
        V, F, C = SS.VERTEX, SS.FRAGMENT, SS.COMPUTE
        FC = F | C                      # groups of the shaded resolve that its compute twin (shade_split.py) binds as well
        # group 0, one layout per kind of stage (a V | F entry counts against both stages): frame, table buffer, table offsets, sg
        self.bgl0_vis = d.create_bind_group_layout(entries=[_entry(0, "u", V | F), _entry(1, "r", V | F), _entry(2, "u", V | F)])
        self.bgl0_res = d.create_bind_group_layout(entries=[_entry(0, "u", FC), _entry(1, "r", FC), _entry(2, "u", FC),
                                                            _entry(4, "u", FC)])
        self.bgl0_cmp = d.create_bind_group_layout(entries=[_entry(0, "u", C)])
        self.bgl_vispage = d.create_bind_group_layout(entries=[_entry(0, "r", V), _entry(1, "u", V)])
        self.bgl_empty = d.create_bind_group_layout(entries=[])
        self.bg_empty = d.create_bind_group(layout=self.bgl_empty, entries=[])
        self.bgl_shade = d.create_bind_group_layout(entries=[
            _entry(0, "u", FC), _entry(1, "tf", FC), _entry(2, "tl", FC), _entry(3, "ta", FC), _entry(4, "tl", FC),
            _entry(5, "s", FC), _entry(6, "s", FC), _entry(7, "s", FC)])
        self.bgl_res = d.create_bind_group_layout(entries=[_entry(3, "tu", C), _entry(4, "tf", C), _entry(5, "tf", C)])
        self.bgl_gather = d.create_bind_group_layout(
            entries=[_entry(60, "u", C), _entry(61, "r", C), _entry(62, "w", C)])
        self.bgl_final = d.create_bind_group_layout(entries=[_entry(0, "u", F), _entry(1, "tl", F), _entry(2, "s", F)])
        self._bgl_cache = {}

    def _bgl_vis(self, samples):
        key = ("vis", samples > 1)
        if key not in self._bgl_cache:
            self._bgl_cache[key] = self.device.create_bind_group_layout(
                entries=[_entry(0, "tu", SS.FRAGMENT, ms=samples > 1), _entry(2, "tl", SS.FRAGMENT),
                         _entry(6, "td", SS.FRAGMENT, ms=samples > 1), _entry(7, "tf", SS.FRAGMENT),
                         _entry(DEC_CRO, "r", SS.FRAGMENT), _entry(DEC_LAY, "u", SS.FRAGMENT)])
        return self._bgl_cache[key]

    def _bgl_pages(self, n):
        key = ("pages", n)
        if key not in self._bgl_cache:
            ents = [_entry(i, "r", SS.FRAGMENT | SS.COMPUTE) for i in range(n)] + [_entry(n, "u", SS.FRAGMENT | SS.COMPUTE)]
            self._bgl_cache[key] = self.device.create_bind_group_layout(entries=ents)
        return self._bgl_cache[key]

    def _layout(self, *bgls):
        return self.device.create_pipeline_layout(bind_group_layouts=list(bgls))

    def _vis_module(self):
        key = ("vis", self.id_format)
        if key not in self._modules:
            code = ("enable primitive_index;\n" + _prelude_ids(self.id_format) + "\n" + _read_text("clip.wgsl") + "\n"
                    + _read_text("tables.wgsl") + "\n" + geo.geom_prelude(1, 1, 0, uniform_binding=1, compressed=self._cmp) + "\n"
                    + _read_text("geom.wgsl") + "\n" + _read_text("morph.wgsl") + "\n" + _read_text("visbuf.wgsl"))
            self._modules[key] = self.device.create_shader_module(code=code, label="visbuf")
        return self._modules[key]

    def _resolve_module(self, samples, n_pages, page0):
        key = ("resolve", self.id_format, samples, n_pages, page0)
        if key not in self._modules:
            clip = _read_text("clip.wgsl")
            assert "fn clipped(" in clip
            clip = clip.replace("fn clipped(", "fn clipped_draw(")          # shading.wgsl has its own `clipped`
            shading = _read_text("shading.wgsl")
            decl = "@group(1) @binding(0) var<uniform> su: ShadeU;"
            assert decl in shading
            shading = _su_reads(shading.replace(decl, "var<private> cur_lb: u32;"))   # word offset of the shaded part's look
            resolve = _read_text("resolve.wgsl")
            assert resolve.count("su = sg;") == 1
            resolve = _su_reads(resolve.replace("su = sg;", ""))          # apply_look(rec) now only sets cur_lb
            code = "\n".join([_prelude_resolve(self.id_format, samples, n_pages, page0, self._cmp), clip, shading,
                              _read_text("tables.wgsl"), _read_text("geom.wgsl"), _read_text("morph.wgsl"),
                              _decode_wgsl(), resolve, _apply_look_wgsl()])
            assert not re.search(r"\bsu\b", re.sub(r"//.*", "", code)), "a use of `su` outside su.u_* is left in the resolve module"
            self._modules[key] = self.device.create_shader_module(code=code, label=f"resolve{n_pages}@{page0}")
        return self._modules[key]

    def _vis_pipe(self, samples, clip):
        feat = self._frame_feat & (FEAT_MORPH | FEAT_ANIM)
        key = ("vis", samples, clip, feat)
        if key not in self._pipes:
            m = self._vis_module()
            consts = {n: float(bool(feat & b)) for n, b in _MORPH_NAMES}
            self._pipes[key] = self.device.create_render_pipeline(
                layout=self._layout(self.bgl0_vis, self.bgl_vispage),
                vertex={"module": m, "entry_point": "vs", "constants": consts},
                fragment={"module": m, "entry_point": "fs_clip" if clip else "fs", "targets": [{"format": self.id_format}]},
                primitive={"topology": "triangle-list", "cull_mode": "none", "front_face": "ccw"},
                depth_stencil={"format": "depth32float", "depth_write_enabled": True, "depth_compare": "less"},
                multisample={"count": samples}, label=f"vis{'_clip' if clip else ''}x{samples}")
        return self._pipes[key]

    def _geom_pipe(self, samples, n_pages, page0, fuse=False):
        feat = self._frame_feat & (FEAT_MORPH | FEAT_ANIM)
        key = ("geom", samples, n_pages, page0, feat, fuse)
        if key not in self._pipes:
            m = self._resolve_module(samples, n_pages, page0)
            self._pipes[key] = self.device.create_render_pipeline(
                layout=self._layout(self.bgl0_res, self.bgl_shade, self._bgl_vis(samples), self._bgl_pages(n_pages)),
                vertex={"module": m, "entry_point": "vs_fsq"},
                fragment={"module": m, "entry_point": "fs_geom_d" if fuse else "fs_geom",
                          "constants": {n: float(bool(feat & b)) for n, b in _MORPH_NAMES},
                          "targets": [{"format": "r32uint"}, {"format": "rg32float"}, {"format": "rgba32float"}]
                          + ([{"format": "r32float"}] if fuse else [])},
                primitive={"topology": "triangle-list", "cull_mode": "none"},
                depth_stencil={"format": "depth32float", "depth_write_enabled": True, "depth_compare": "less"},
                label=f"geom{n_pages}@{page0}")
        return self._pipes[key]

    def _shade_pipe(self, samples, n_pages, page0, feat=FEAT_FRAME_ALL):
        key = ("shade", samples, n_pages, page0, feat)
        if key not in self._pipes:
            m = self._resolve_module(samples, n_pages, page0)
            self._pipes[key] = self.device.create_render_pipeline(
                layout=self._layout(self.bgl0_res, self.bgl_shade, self._bgl_vis(samples), self._bgl_pages(n_pages)),
                vertex={"module": m, "entry_point": "vs_fsq"},
                fragment={"module": m, "entry_point": "fs_shade",
                          "constants": {n: float(bool(feat & b)) for n, b in _FEAT_NAMES + _MORPH_NAMES},
                          "targets": [{"format": "rgba16float", "blend": {"color": ADD, "alpha": ADD}}]},
                primitive={"topology": "triangle-list", "cull_mode": "none"},
                label=f"shade{n_pages}@{page0}")
        return self._pipes[key]

    def _final_pipe(self):
        if "final" not in self._pipes:
            m = self.device.create_shader_module(code=_read_text("final.wgsl"), label="final")
            self._pipes["final"] = self.device.create_render_pipeline(
                layout=self._layout(self.bgl_final), vertex={"module": m, "entry_point": "vs_fsq"},
                fragment={"module": m, "entry_point": "fs_final", "targets": [{"format": "rgba8unorm"}]},
                primitive={"topology": "triangle-list"}, label="final")
        return self._pipes["final"]

    def _gather_pipe(self, name):
        key = ("gather", name)
        if key not in self._pipes:
            m = self._resolve_module(1, 1, 0)
            self._pipes[key] = self.device.create_compute_pipeline(
                layout=self._layout(self.bgl0_cmp, self.bgl_empty, self.bgl_res, self.bgl_gather),
                compute={"module": m, "entry_point": name}, label=name)
        return self._pipes[key]

    # ------------------------------------------------------------------ model
    def set_model(self, model):
        self.release_model()
        cut = [p.id for p in model.parts if p.look.texture is not None and p.look.alpha_cut > 0.0]
        if cut:                          # the visibility pass cannot discard by texture alpha yet: OpenGL draws such models
            raise NotImplementedError(f"alpha-cut textures are not supported by the wgpu renderer yet ({len(cut)} part(s), "
                                      f"e.g. {cut[0]})")
        try:
            self.model = model
            sink = geo.GpuSink(self.device)
            order = self._wants_cluster_order(model)
            try:
                self.geom = geo.build_geometry(model, sink, self.page_bytes, max_pages=self.max_pages, cluster_order=order,
                                               compress=order and self._wants_compress(model))
                if int(self.geom.stage) != self._cmp:              # modules and pipelines are built for one of the stages
                    self._cmp = int(self.geom.stage)
                    self._pipes.clear()
                    self._modules.clear()
            except geo.GeometryError as exc:
                log.warning("wgpu renderer: model does not fit the geometry layout, the OpenGL viewport is used: %s", exc)
                raise
            levels = getattr(model, "lod", None) or {}
            parts = model.parts
            where = {p.id: i for i, p in enumerate(parts)}
            coarse = [p for p in parts if p.id in levels]
            self._lod = (np.array([where[p.id] for p in coarse]), [p.id for p in coarse],
                         np.array([levels[p.id].cells for p in coarse], dtype=np.float64)) if coarse else None
            self._look_keys = {p.id: _look_key(p.look) for p in parts}
            self._make_page_groups()
            self._make_ptab()
            self._make_culler(model)
            self.oit.set_geometry(self.geom)
            self._oit_rec = _Rec()
            side = model.sidecar.get("lights") or {}
            self.rig = side.get("rig") or DEFAULT_RIG
            self.world = side.get("world") or DEFAULT_WORLD
            diag = float(np.linalg.norm(model.bounds_max - model.bounds_min))
            self.model_diag = max(diag, 1e-3)
            n_items = max(len(model.items), 1)
            self.items_tex = self.device.create_texture(size=(n_items, 3, 1), format="rgba32float",
                                                        usage=TU.TEXTURE_BINDING | TU.COPY_DST, label="items")
            self._item_state = None
            self._look_idx, self._look_bytes, self._looks_written = {}, [], 0
            self._look_feat, self._frame_feat = [], FEAT_FRAME_ALL
            self._bg_shade = None
            self._xf_key = None
            self._anim_key = None
            self._anim_data = None
            self._tab_caps = (0, 0)
            self._look_tex = {}
            self._tex_slots = sorted({p.look.texture for p in parts if p.look.texture is not None})
            self.frame_ok = False
        except Exception:
            self.release_model()
            raise

    def _wants_cluster_order(self, model):
        """Cluster-ordered geometry (and so the culler) only for static models: no procedural animation, no morph targets (the
        culler's vertex stage moves nothing but the part matrix) and, in "auto", enough triangles for the culler to ever run.
        Below cull_min_tris the source order is kept and the cluster build is skipped (plain draws of ordered geometry were
        measured ~27 % slower on an integrated GPU for 25M-triangle parts)."""
        if self.cull_mode == "off":
            return False
        if getattr(model, "anim_vertices", None) is not None or any(p.has_morph for p in model.parts):
            return False
        if self.cull_mode in ("on", "plain"):
            return True
        return sum(int(p.count) for p in model.parts) // 3 >= self.cull_min_tris

    def _wants_compress(self, model):
        """Compressed geometry for a cluster-ordered model: stage 1 = vertex renumbering + u16 cluster-relative indices, stage 2 =
        and quantised positions (geometry.py, quant.py). ANATOMY_GEOM_COMPRESS = on (stage 2 for every cluster-ordered model) /
        stage1 / off / auto (default: the smallest stage whose pages fit the adapter's capacity max_pages x page_bytes, plain
        pages if they do; build_geometry decides). Every other model keeps the plain u32-index layout and draw path."""
        return {"on": 2, "stage1": 1, "off": False}.get(self.geom_compress, "auto")

    def _make_culler(self, model):
        """The cluster culler of an ordered geometry (None for the rest); makes the resolve's group 2 point at its decode tables."""
        self.culler = None
        if self.geom is not None and self.geom.cluster_ordered:
            culler = ClusterCuller(self.gpu, self.geom, id_format=self.id_format, profile=self.profile)
            try:
                self.cull_stats = culler.prepare(model)
            except ClusterError as exc:
                log.warning("wgpu renderer: the cluster culler is off for this model: %s", exc)
                culler.release()
            else:
                self.culler = culler
                self.gov = CullGovernor.for_adapter(getattr(self.gpu, "adapter_type", ""),
                                                    save_tris=int(float(os.environ["ANATOMY_CULL_SAVE_TRIS"])) if os.environ.get("ANATOMY_CULL_SAVE_TRIS") else None,
                                                    blind_min_tris=self.cull_min_tris)
        self._bg_vis_none = self._bg_vis_cap = None
        if self.t:
            self._bg_vis_none = self._make_bg_vis(self._cap_none)
            self._bg_vis = self._bg_vis_none

    def _make_ptab(self):
        g = self.geom
        n = len(self.model.parts)
        words = np.zeros((max(n, 1), PTAB_STRIDE), dtype=np.uint32)
        for i in range(n):
            if g.page_of[i] < 0:
                continue
            words[i, 0:5] = g.stream_base[i].astype(np.int32).view(np.uint32)
            words[i, 5] = np.uint32(g.vbase[i])
            words[i, 6:19] = np.asarray(g.const_tail[i], dtype=np.float32).view(np.uint32)
            words[i, 19] = np.int32(g.anim_base[i]).view(np.uint32)
        self._ptab_words = words

    def _make_page_groups(self):
        d = self.device
        g = self.geom
        self._page_ub = []
        self._vis_page_bg = []
        for page in g.pages:
            ub = d.create_buffer_with_data(data=page.offsets_words(), usage=BU.UNIFORM, label=f"page{page.index}.offs")
            self._page_ub.append(ub)
            self._vis_page_bg.append(d.create_bind_group(layout=self.bgl_vispage, entries=[
                {"binding": 0, "resource": {"buffer": page.buffer, "offset": 0, "size": page.buffer.size}},
                {"binding": 1, "resource": {"buffer": ub, "offset": 0, "size": ub.size}}]))
        n = len(g.pages)
        offs = g.page_offsets()
        ub = d.create_buffer_with_data(data=offs, usage=BU.UNIFORM, label="pages.offs")
        self._page_ub.append(ub)
        ents = [{"binding": i, "resource": {"buffer": pg.buffer, "offset": 0, "size": pg.buffer.size}} for i, pg in enumerate(g.pages)]
        ents.append({"binding": n, "resource": {"buffer": ub, "offset": 0, "size": ub.size}})
        # every page in one bind group (a model with more pages than max_pages never gets here: GeometryError)
        self._groups = [(0, n, d.create_bind_group(layout=self._bgl_pages(n), entries=ents))] if n else []

    def release_model(self):
        self.oit.set_geometry(None)
        self.caps.release()
        self._bg_vis_cap = self._cap_col_v = None
        self._bg_vis_none = None
        self._capon = 0
        if self.culler is not None:
            self.culler.release()
        self.culler = None
        self.culled_frame = False
        if self.geom is not None:
            self.geom.release()
        self.geom = None
        self.model = None
        self._lod = None
        self._level = {}
        self._xf = {}
        self._xf_key = None
        self._vis_page_bg, self._groups = [], []
        for ub in getattr(self, "_page_ub", []):
            ub.destroy()
        self._page_ub = []
        if self._tab is not None:
            self._tab.destroy()
            self._tab = None
        self._tab_caps, self._tab_off, self._ptab_words = (0, 0), {}, None
        self._looks_written = 0
        self._anim_data = None
        if self.items_tex is not None:
            self.items_tex.destroy()
            self.items_tex = None
        for tex, _view in self._tex.values():
            tex.destroy()
        self._tex, self._tex_slots, self._look_tex = {}, [], {}
        self._bg0_vis = self._bg0_res = self._bg0_cmp = None
        self._bg_shade = None
        self.frame_ok = False

    def release(self):
        self.release_model()
        for tex in self.t.values():
            if hasattr(tex, "destroy"):
                tex.destroy()
        self.t = {}
        self.size = self.samples = None

    # ------------------------------------------------------------------ per-frame CPU work (ported from the GL renderer)
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

    def _refresh_transforms(self, m):
        key = (id(m.node_world), len(m.node_world), m.root.tobytes(),
               tuple(sorted((n, np.asarray(o).tobytes()) for n, o in m.node_offsets.items())),
               None if m.item_offsets is None else m.item_offsets.tobytes(),
               tuple(sorted(m.node_weights.items())), bytes(bool(it.clip) for it in m.items))
        if key == self._xf_key:
            return
        self._xf_key = key
        self._xf = {}
        spheres = [m.part_sphere(p) for p in m.parts]
        self._spheres = (np.array([c for c, _r in spheres], dtype=np.float64).reshape(-1, 3),
                         np.array([r for _c, r in spheres], dtype=np.float64))
        self._scales = np.zeros(len(m.parts))
        if self._lod is not None:
            for i in self._lod[0]:
                self._scales[i] = float(np.max(np.linalg.norm(m.part_matrix(m.parts[i])[:3, :3], axis=0)))

    def _transform(self, p):
        """(model matrix, normal matrix, mirrored, morph weight, never cut, key) of a part, once per change."""
        xf = self._xf.get(p.id)
        if xf is None:
            m = self.model
            M = m.part_matrix(p)
            weight = float(m.node_weights.get(p.node, 0.0))
            flip = 1 if np.linalg.det(M[:3, :3]) < 0 else 0
            noclip = 0 if m.items[p.item].clip else 1
            xf = (M, np.linalg.inv(M[:3, :3]).T, flip, weight, noclip, (M.tobytes(), flip, weight, noclip))
            self._xf[p.id] = xf
        return xf

    def _lod_levels(self, V, halves, ortho, h):
        if self._lod is None:
            return {}
        where, ids, cells = self._lod
        centres, radii = self._spheres
        if ortho:
            pixel = np.full(len(ids), 2.0 * halves[1] / h)
        else:
            depth = -(centres[where] @ V[2, :3] + V[2, 3]) - radii[where]
            pixel = np.maximum(depth, 0.0) * (2.0 * halves[1] / h)
        level = np.sum(cells * self._scales[where][:, None] <= pixel[:, None], axis=1)
        return {pid: int(k) for pid, k in zip(ids, level) if k}

    def visible_parts(self, VP, vis, ghost, alpha, fs):
        """(opaque parts, translucent parts) of this frame, in model order: the GL renderer's culling."""
        m = self.model
        draws, oit = [], []
        planes = _frustum_planes(VP)
        centres, radii = self._spheres
        inside = np.all(planes[:, :3] @ centres.T + planes[:, 3:4] >= -radii, axis=0) if len(radii) else []
        for p, keep in zip(m.parts, inside):
            it = p.item
            if not vis[it] or not keep:
                continue
            if _transparent_pass(p, bool(ghost[it]), float(alpha[it]), fs):
                oit.append(p)
            else:
                draws.append(p)
        return draws, oit

    def _warn_once(self, key, message):
        """States this step does not render: say so once per model instead of silently drawing something else."""
        if key not in self._warned:
            self._warned.add(key)
            log.warning("wgpu renderer: %s", message)

    def _check_supported(self, m, fs, draws, oit, any_clip):
        if oit:
            pass

    # ------------------------------------------------------------------ targets
    def _pick_samples(self, msaa):
        want = max(1, int(msaa))
        for n in (8, 4, 2):
            if n <= want and n <= self.max_samples:
                return n
        return 1

    def _decode_resources(self):
        """The resolve's decode tables: the culler's (cro, lay) or one-word dummies (a culled id never reaches them)."""
        if self.culler is not None and self.culler.buf:
            cro, lay = self.culler.decode_bind_group_entries()
        else:
            if self._dec_dummy is None:
                self._dec_dummy = (self.device.create_buffer(size=16, usage=BU.STORAGE, label="dec_cro"),
                                   self.device.create_buffer(size=CULL_LAY_BYTES, usage=BU.UNIFORM, label="dec_lay"))
            cro, lay = self._dec_dummy
        return ({"buffer": cro, "offset": 0, "size": cro.size}, {"buffer": lay, "offset": 0, "size": CULL_LAY_BYTES})

    def _make_bg_vis(self, cap_col_view):
        cro, lay = self._decode_resources()
        return self.device.create_bind_group(layout=self._bgl_vis(self.samples), entries=[
            {"binding": 0, "resource": self.v["vis_id"]}, {"binding": 2, "resource": self.v["bg"]},
            {"binding": 6, "resource": self.v["vis_depth"]},
            {"binding": 7, "resource": cap_col_view}, {"binding": DEC_CRO, "resource": cro}, {"binding": DEC_LAY, "resource": lay}])

    def _ensure_targets(self, w, h, samples):
        if self.size == (w, h) and self.samples == samples and self.t:
            return
        for tex in self.t.values():
            tex.destroy()
        if self.oit_t is not None:
            OitPass.destroy_targets(self.oit_t)
        d = self.device
        RA, TB, CS, CD = TU.RENDER_ATTACHMENT, TU.TEXTURE_BINDING, TU.COPY_SRC, TU.COPY_DST
        t = {}
        t["vis_id"] = d.create_texture(size=(w, h, 1), format=self.id_format, sample_count=samples, usage=RA | TB,
                                       label="vis_id")
        t["vis_depth"] = d.create_texture(size=(w, h, 1), format="depth32float", sample_count=samples, usage=RA | TB,
                                          label="vis_depth")
        t["res_order"] = d.create_texture(size=(w, h, 1), format="depth32float", usage=RA, label="res_order")
        t["tri"] = d.create_texture(size=(w, h, 1), format="r32uint", usage=RA | TB | CS, label="tri")
        t["id"] = d.create_texture(size=(w, h, 1), format="rg32float", usage=RA | TB | CS, label="id")
        t["nd"] = d.create_texture(size=(w, h, 1), format="rgba32float", usage=RA | TB | CS, label="nd")
        t["ssao_depth"] = d.create_texture(size=(w, h, 1), format="r32float", usage=RA | TB | CS, label="ssao_depth")
        t["bg"] = d.create_texture(size=(w, h, 1), format="rgba16float", usage=RA | TB | CS | CD, label="backdrop")
        t["opaque"] = d.create_texture(size=(w, h, 1), format="rgba16float", usage=RA | TB | CS | CD, label="opaque")
        t["ao"] = d.create_texture(size=(w, h, 1), format="rgba16float", usage=RA | TB, label="ao")
        t["ao_tmp"] = d.create_texture(size=(w, h, 1), format="rgba16float", usage=RA | TB, label="ao_tmp")
        t["accum"] = d.create_texture(size=(w, h, 1), format="rgba16float", usage=RA | TB, label="accum")
        t["weight"] = d.create_texture(size=(w, h, 1), format="r16float", usage=RA | TB, label="weight")
        t["comp"] = d.create_texture(size=(w, h, 1), format="rgba8unorm", usage=RA | TB, label="composite")
        self.t = t
        self.v = {k: v.create_view() for k, v in t.items()}
        self.oit_t = self.oit.make_targets(w, h, samples)
        self.size, self.samples = (w, h), samples
        self._bg_vis_none = self._make_bg_vis(self._cap_none)
        self._bg_vis_cap = None
        self._bg_vis = self._bg_vis_none
        self._bg_res = d.create_bind_group(layout=self.bgl_res, entries=[
            {"binding": 3, "resource": self.v["tri"]}, {"binding": 4, "resource": self.v["id"]},
            {"binding": 5, "resource": self.v["nd"]}])
        self._bg_shade = None

    def _tab_layout(self, rows_cap, looks_cap):
        """Word offsets of the sections of the table buffer (tables.wgsl) and its size in words."""
        n_parts = max(len(self.model.parts), 1)
        n_items = max(len(self.model.items), 1)
        sizes = (("ptab", n_parts * PTAB_STRIDE), ("anim", n_items * 12), ("looks", looks_cap * SHADE_WORDS),
                 ("draws", rows_cap * DRAW_FLOATS))
        off, at = {}, 0
        for name, n in sizes:
            off[name] = at
            at += -(-n // TAB_ALIGN) * TAB_ALIGN
        return off, at

    def _ensure_table(self, rows, looks):
        rows_cap, looks_cap = self._tab_caps
        if self._tab is not None and rows_cap >= rows and looks_cap >= looks:
            return
        rows_cap = max(rows_cap, 64, 1 << (max(rows, 1) - 1).bit_length())
        looks_cap = max(looks_cap, 16, 1 << (max(looks, 1) - 1).bit_length())
        if self._tab is not None:
            self._tab.destroy()
        off, words = self._tab_layout(rows_cap, looks_cap)
        self._tab = self.device.create_buffer(size=words * 4, usage=BU.STORAGE | BU.COPY_DST, label="tab")
        self._tab_caps, self._tab_off = (rows_cap, looks_cap), off
        # the sections that persist between frames are written again (draws are written every frame, the anim section by
        # _upload_anim when its key changes: forget the key)
        self.queue.write_buffer(self._tab, off["ptab"] * 4, np.ascontiguousarray(self._ptab_words))
        if self._look_bytes:
            self.queue.write_buffer(self._tab, off["looks"] * 4, np.frombuffer(b"".join(self._look_bytes), dtype=np.uint8))
        self._looks_written = len(self._look_bytes)
        if self._anim_data is not None:
            self.queue.write_buffer(self._tab, off["anim"] * 4, self._anim_data)
        self.queue.write_buffer(self._tinfo, 0, np.array([off["ptab"], off["anim"], off["looks"], off["draws"]], dtype=np.uint32))
        d = self.device
        res = lambda b, o=0, n=None: {"buffer": b, "offset": o, "size": b.size - o if n is None else n}
        frame = res(self._frame_ub, 0, FRAME_BYTES)
        self._bg0_vis = d.create_bind_group(layout=self.bgl0_vis, entries=[
            {"binding": 0, "resource": frame}, {"binding": 1, "resource": res(self._tab)},
            {"binding": 2, "resource": res(self._tinfo)}])
        self._bg0_res = d.create_bind_group(layout=self.bgl0_res, entries=[
            {"binding": 0, "resource": frame}, {"binding": 1, "resource": res(self._tab)},
            {"binding": 2, "resource": res(self._tinfo)}, {"binding": 4, "resource": res(self._sg, 0, SHADE_SIZE)}])
        self._bg0_cmp = d.create_bind_group(layout=self.bgl0_cmp, entries=[{"binding": 0, "resource": frame}])

    def anim_section(self):
        """(buffer, byte offset, byte size) of the per-item animation table inside the table buffer."""
        n_items = max(len(self.model.items), 1)
        return self._tab, self._tab_off["anim"] * 4, n_items * 48

    # ------------------------------------------------------------------ shading data
    def _ambient(self):
        world = self.world or DEFAULT_WORLD
        return round(float(np.mean(world.get("ambient_colour", [0.5] * 3))) * float(world.get("ambient_strength", 0.3)), 4)

    def _auto_ao_radius(self):
        um = self.model.um_per_bu() if self.model else 0
        if um and um <= 50:
            return 4.5 / um                     # 4.5 um: the gaps between packed cells
        return self.model_diag * 0.017

    def _refresh_env(self, s):
        key = (round(s.studio, 3), self._ambient())
        if key == self._env_key:
            return
        env = make_env(studio=s.studio, ambient=self._ambient())
        self.env_sh = sh9_irradiance(env)
        spec, src = self.post.build_env_spec(env)
        if self.env_spec is not None:
            self.env_spec.destroy()
            self.env_src.destroy()
        self.env_spec, self.env_src = spec, src
        self._env_key = key
        self._bg_shade = None

    def _lights(self, V, s):
        """The camera-relative light rig as the GL renderer builds it: [(direction, radiance, size, factor)] x 3."""
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
        return lights

    def _gl_fake(self):
        return SimpleNamespace(
            t={"ao": _Null()}, shadow_maps=[(_Null(),)] * 3, _shadow_mats=[np.eye(4)] * 3, _shadow_texel=[0.01] * 3,
            _shadow_soft=[1.0] * 3, env=SimpleNamespace(spec=_Null(), sh=self.env_sh), white=_Null())

    def _oit_draws(self, parts, VP, V, campos, lights, s, size, camera, clip, fs, alpha, ghost):
        """The OitDraw list of GL's pass 5: `_draw_shaded(p_oit, ...)` replayed on a recorder that lives as long as the model
        (GL's uniform cache keeps stale values between draws too), in the draw order of the main pass."""
        geom = self.geom
        index_of = {p.id: i for i, p in enumerate(self.model.parts)}
        items = []
        for p in parts:
            pi = index_of[p.id]
            k = self._level.get(p.id, 0)
            rng = geom.ranges[pi]
            first, count = rng[k] if k < len(rng) else rng[0]
            if count < 3 or geom.page_of[pi] < 0:
                continue
            key = geom.gl_keys[pi][k] if k < len(geom.gl_keys[pi]) else geom.gl_keys[pi][0]
            items.append((key, pi, p, first, count))
        items.sort(key=lambda e: (e[0], e[1]))
        u = self._oit_rec
        u("u_viewproj", VP)
        _GL._light_uniforms(self._gl_fake(), u, V, campos, lights, s, size, camera)
        _GL._clip_uniforms(u, clip)
        u("u_ghost_alpha", float(s.ghost_alpha))
        out = []
        for key, pi, p, first, count in items:
            it = p.item
            M, nmat, flip, wgt, noclip, _key = self._transform(p)
            u("u_model", M)
            u("u_nmat", nmat)
            u("u_flip", flip)
            u("u_weight", wgt)
            u("u_noclip", noclip)
            batched = self._look_keys[p.id] is not None
            u("u_batched", 1 if batched else 0)
            _GL._set_look(self._fake, u, p, s, fs, batched)
            if not batched:
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
            tex = self._texture_view(p.look.texture) if int(u.get("u_has_tex", 0)) == 1 else None
            out.append(OitDraw(part=pi, first=int(first), count=int(count), item=int(it), uniforms=dict(u), texture=tex))
        return out

    def _global_uniforms(self, V, campos, lights, s, size, camera, clip):
        """The frame-wide ShadeU bytes: what GL's _draw_shaded sets once per pass (the same functions, on a recorder)."""
        rec = _Rec()
        fake = self._gl_fake()
        _GL._light_uniforms(fake, rec, V, campos, lights, s, size, camera)
        _GL._clip_uniforms(rec, clip)
        return pack_shading_uniforms(rec)

    def _look_index(self, p, s, fs, flip, noclip, weight):
        """Index of the ShadeU record of this part's look in the looks table (built once per distinct look state)."""
        lk = self._look_keys[p.id]
        batched = lk is not None
        it = p.item
        sig = (lk if batched else ("part", p.id), flip, noclip, round(weight, 6), bool(fs.opaque_materials),
               bool(s.stripes), round(float(s.tissue), 6))
        if not batched:
            flat = fs.override.get(it)
            if flat is None and fs.colours is not None:
                flat = tuple(float(x) for x in fs.colours[it])
            hl = 0.45 if it in fs.selected else (0.18 if (it == fs.hovered or (s.hovered and s.hovered == it + 1)) else 0.0)
            sig += (None if flat is None else tuple(flat), hl, tuple(s.highlight), tuple(s.hover_highlight))
        idx = self._look_idx.get(sig)
        if idx is not None:
            return idx
        rec = _Rec()
        _GL._set_look(self._fake, rec, p, s, fs, batched)
        rec("u_flip", flip)
        rec("u_weight", weight)
        rec("u_noclip", noclip)
        rec("u_batched", 1 if batched else 0)
        self._look_tex[len(self._look_bytes)] = p.look.texture if int(rec.get("u_has_tex", 0)) == 1 else None
        if not batched:
            if it in fs.selected:
                rec("u_highlight", 0.45)
                rec("u_highlight_col", np.array(s.highlight))
            elif it == fs.hovered or (s.hovered and s.hovered == it + 1):
                rec("u_highlight", 0.18)
                rec("u_highlight_col", np.array(s.hover_highlight))
            else:
                rec("u_highlight", 0.0)
        idx = len(self._look_bytes)
        self._look_bytes.append(pack_shading_uniforms(rec))
        self._look_feat.append(_look_features(rec))
        self._look_idx[sig] = idx
        return idx

    def _upload_item_state(self, fs, s, ghost, alpha):
        """Per item: (id + 1, selected, highlight, x-ray), (flat colour, on), (highlight colour, opacity): GL's items_tex."""
        n = len(self.model.items)
        st = np.zeros((3, max(n, 1), 4), dtype=np.float32)
        st[0, :n, 0] = np.arange(1, n + 1)
        st[0, :n, 3] = ghost
        st[2, :n, 3] = alpha
        for hovered in {fs.hovered, s.hovered - 1 if s.hovered else -1}:
            if 0 <= hovered < n and hovered not in fs.selected:
                st[0, hovered, 2] = 0.18
                st[2, hovered, :3] = s.hover_highlight
        for it in fs.selected:
            if 0 <= it < n:
                st[0, it, 1] = 1.0
                st[0, it, 2] = 0.45
                st[2, it, :3] = s.highlight
        if fs.colours is not None:
            st[1, :n, :3] = np.asarray(fs.colours, dtype=np.float32)[:n]
            st[1, :n, 3] = 1.0
        for it, colour in fs.override.items():
            if 0 <= it < n:
                st[1, it] = (*colour, 1.0)
        data = st.tobytes()
        if data != self._item_state:
            self.queue.write_texture({"texture": self.items_tex, "mip_level": 0, "origin": (0, 0, 0)}, st,
                                     {"bytes_per_row": st.shape[1] * 16, "rows_per_image": 3}, (st.shape[1], 3, 1))
            self._item_state = data

    def _upload_anim(self, fs):
        """Per item (u_aw, u_ag) and the cycle phase, for morph.wgsl; all zero (animation off) unless the model has animation
        vertices and the frame carries an animation frame, exactly GL's `_anim_uniforms` condition."""
        m = self.model
        n = len(m.items)
        on = m.anim_vertices is not None and fs.anim_frame is not None
        key = (round(float(fs.anim_t), 6), np.asarray(fs.anim_frame).tobytes()) if on else None
        if key == self._anim_key:
            return
        self._anim_key = key
        tab = np.zeros((n, 3, 4), np.float32)
        if on:
            tab[:, 0] = np.asarray(fs.anim_frame)[0, :n]
            tab[:, 1] = np.asarray(fs.anim_frame)[1, :n]
            tab[:, 2, 0] = np.float32(fs.anim_t)
            tab[:, 2, 1] = 1.0
        self._anim_data = tab
        if self._tab is not None:
            self.queue.write_buffer(self._tab, self._tab_off["anim"] * 4, tab)

    def _slot_of(self, image_index):
        return 0 if image_index is None else 1 + self._tex_slots.index(image_index)

    def _texture_view(self, image_index):
        """The albedo of glTF image `image_index`: rgba8unorm-srgb with a full mip chain (GL: GL_SRGB8_ALPHA8, build_mipmaps,
        trilinear, anisotropy 8, longest side capped at 4096); a white texel when the image cannot be read."""
        hit = self._tex.get(image_index)
        if hit is not None:
            return hit[1]
        try:
            import io
            from PIL import Image
            im = Image.open(io.BytesIO(self.model.doc.images[image_index])).convert("RGBA")
            if max(im.size) > 4096:
                k = 4096 / max(im.size)
                im = im.resize((max(1, int(im.size[0] * k)), max(1, int(im.size[1] * k))), Image.LANCZOS)
            levels = mip_chain(np.asarray(im, dtype=np.uint8))
            tex = self.device.create_texture(size=(im.size[0], im.size[1], 1), format="rgba8unorm-srgb", mip_level_count=len(levels),
                                             usage=TU.TEXTURE_BINDING | TU.COPY_DST, label=f"albedo{image_index}")
            for k, lv in enumerate(levels):
                self.queue.write_texture({"texture": tex, "mip_level": k, "origin": (0, 0, 0)}, np.ascontiguousarray(lv),
                                         {"bytes_per_row": lv.shape[1] * 4, "rows_per_image": lv.shape[0]}, (lv.shape[1], lv.shape[0], 1))
            view = tex.create_view()
        except Exception:                       # a bad image draws white, as GL falls back to its white texture
            tex, view = self._white, self._white.create_view()
        self._tex[image_index] = (tex if tex is not self._white else self.device.create_texture(
            size=(1, 1, 1), format="rgba8unorm", usage=TU.TEXTURE_BINDING), view)
        return view

    def _shade_bind_group(self, slot=0, first=0):
        """Group 1 of the resolve passes: items, AO, specular environment, the albedo of texture `slot` (0: white) and the pass
        info (slot, 1 = add the backdrop)."""
        if not self._bg_shade:
            self._items_v = self.items_tex.create_view()
            self._spec_v = self.env_spec.create_view(dimension="2d-array")
            self._bg_shade = {}
        key = (slot, first, self._capon)
        if key not in self._bg_shade:
            ub = self._pass_ub.get(key)
            if ub is None:
                ub = self.device.create_buffer_with_data(data=np.array([slot, first, self._capon, 0], np.uint32), usage=BU.UNIFORM,
                                                         label=f"pass{key}")
                self._pass_ub[key] = ub
            albedo = self._white.create_view() if slot == 0 else self._texture_view(self._tex_slots[slot - 1])
            self._bg_shade[key] = self.device.create_bind_group(layout=self.bgl_shade, entries=[
                {"binding": 0, "resource": {"buffer": ub, "offset": 0, "size": 16}},
                {"binding": 1, "resource": self._items_v},
                {"binding": 2, "resource": self.v["ao"]},
                {"binding": 3, "resource": self._spec_v},
                {"binding": 4, "resource": albedo},
                {"binding": 5, "resource": self._s_ao}, {"binding": 6, "resource": self.post.s_env},
                {"binding": 7, "resource": self._s_tex}])
        return self._bg_shade[key]

    # ------------------------------------------------------------------ the draw table
    def _build_table(self, draws, s, fs):
        """Sort the parts into the GL draw order, split long draws and fill the table. Returns (table, entries,
        prim_bits) where entries are (slot, part index, level, first_index, index_count) per draw."""
        geom = self.geom
        index_of = {p.id: i for i, p in enumerate(self.model.parts)}
        items = []
        for p in draws:
            pi = index_of[p.id]
            k = self._level.get(p.id, 0)
            rng = geom.ranges[pi]
            first, count = rng[k] if k < len(rng) else rng[0]
            if count < 3 or geom.page_of[pi] < 0:
                continue
            key = geom.gl_keys[pi][k] if k < len(geom.gl_keys[pi]) else geom.gl_keys[pi][0]
            items.append((key, pi, p, k, first, count))
        items.sort(key=lambda e: (e[0], e[1]))
        bits = self.prim_bits_max
        while True:
            cap = 1 << bits
            n_slots = sum(-(-(e[5] // 3) // cap) for e in items)
            if n_slots + 1 <= (1 << (31 - bits)):          # plain ids keep bit 31 clear: the culler's ids own it
                break
            bits -= 1
            if bits < 8:
                raise RendererError(f"{n_slots} draw slots do not fit a 32-bit visibility id")
        table = np.zeros((n_slots + 1, DRAW_FLOATS), dtype=np.float32)
        tu = table.view(np.uint32)
        entries = []
        slot = 1
        feat = 0
        anim_on = self.model.anim_vertices is not None and fs.anim_frame is not None
        for key, pi, p, k, first, count in items:
            M, nmat, flip, weight, noclip, _key = self._transform(p)
            sel = p.item in self._fs.selected
            flags = (DRAW_NOCLIP if noclip else 0) | (DRAW_MIRRORED if flip else 0) | (DRAW_SELECTED if sel else 0)
            rec = self._look_index(p, s, fs, flip, noclip, weight)
            feat |= self._look_feat[rec]
            if weight != 0.0:
                feat |= FEAT_MORPH
            if anim_on and geom.anim_base[pi] >= 0:
                feat |= FEAT_ANIM
            tris = count // 3
            page = int(geom.page_of[pi])
            for a in range(0, tris, cap):
                n = min(cap, tris - a)
                table[slot, 0:16] = np.ascontiguousarray(M.T).reshape(-1)
                table[slot, 16:19] = nmat[:, 0]
                table[slot, 20:23] = nmat[:, 1]
                table[slot, 24:27] = nmat[:, 2]
                tu[slot, 28:32] = (first + 3 * a, 0, n, page)
                tu[slot, 32:36] = (pi, p.item, flags, k)
                table[slot, 36] = weight
                tu[slot, 37] = rec
                tu[slot, 38] = self._slot_of(self._look_tex.get(rec))
                entries.append((slot, pi, k, first + 3 * a, 3 * n))
                slot += 1
        self._frame_feat = feat
        return table, entries, bits

    # ------------------------------------------------------------------ frame
    def _ts(self, qs, a, b=None, only=None):
        """timestamp_writes for a pass: begin index a, end index b (either may be None)."""
        if qs is None:
            return None
        tw = {"query_set": qs}
        if a is not None:
            tw["beginning_of_pass_write_index"] = a
        if b is not None:
            tw["end_of_pass_write_index"] = b
        return tw

    def _want_cull(self, drawn_tris, any_drawn, key=None):
        """Does this frame cull for real? "on" always, "off" / "plain" never; "auto" asks the governor (cull_policy.py), which reads the
        culler's counters of recent frames and compares what culling saves with what it costs. Compressed geometry that is not culled
        still goes through the culler, accepting every cluster (see _use_cull)."""
        if self.culler is None or not any_drawn:
            return False
        if self.cull_mode in ("off", "plain"):
            return False
        if self.cull_mode == "on":
            return True
        if self.gov is None:
            return drawn_tris >= self.cull_min_tris
        return self.gov.decide(drawn_tris, key)

    def _use_cull(self, drawn_tris, any_drawn, want=None):
        """Does this frame go through the cluster culler? (the geometry must be cluster ordered, i.e. a culler exists)"""
        if self.culler is None or not any_drawn:
            return False
        if self._cmp:                       # compressed geometry has no hardware index buffer: opaque parts always go through the culler
            return True
        return self._want_cull(drawn_tris, any_drawn) if want is None else want

    def _frame_parts(self, entries):
        """(FrameParts for the culler, model part index per row) of the frame's draw entries: one row per part, in table order,
        slot0 = the part's first draw slot (its slots are consecutive)."""
        first = {}
        for slot, pi, k, _first, _count in entries:
            if pi not in first:
                first[pi] = (slot, k)
        pis = list(first)
        parts = self.model.parts
        xf = [self._transform(parts[pi]) for pi in pis]
        fp = FrameParts(part=np.array(pis, dtype=np.int64), level=np.array([first[pi][1] for pi in pis], dtype=np.int64),
                        matrix=np.stack([x[0] for x in xf]).astype(np.float64), noclip=np.array([x[4] for x in xf], dtype=np.uint32),
                        weight=np.array([x[3] for x in xf], dtype=np.float32),
                        slot0=np.array([first[pi][0] for pi in pis], dtype=np.uint32))
        return fp, pis

    def _draw_slots(self, rp, entries):
        """One indexed draw per entry (slot, part, level, first index, index count) with the plain visibility pipeline set."""
        current = -1
        cmp = self._cmp
        for slot, pi, k_, first, count in entries:
            page = int(self.geom.page_of[pi])
            if page != current:
                rp.set_bind_group(1, self._vis_page_bg[page])
                if not cmp:
                    rp.set_index_buffer(self.geom.pages[page].buffer, "uint32", self.geom.pages[page].index_byte_offset,
                                        self.geom.pages[page].index_bytes)
                current = page
            if cmp:                      # compressed pages: vertex_index = logical index position (geom.wgsl g_vertex)
                rp.draw(count, 1, first, slot)
            else:
                rp.draw_indexed(count, 1, first, 0, slot)

    def _cut_classes(self, entries, planes, on, mode, V, Pm, height, ortho):
        """{part index: cutclass class} of the parts the frame draws (plain path of a cut view). The signed distances of the part's
        world box to the planes depend on the box, its matrix of this frame (explode and node offsets included) and the planes,
        not on the camera: they are kept until one of those changes; only the pixel margin (cutclass.pixel_margin) is per frame.
        Morphed and animated parts are never proved: STRADDLE."""
        anim_on = self.model.anim_vertices is not None and self._fs.anim_frame is not None
        pis = tuple(sorted({e[1] for e in entries}))
        key = (planes.tobytes(), tuple(on), int(mode), bool(anim_on), pis)
        xf_id, ckey, st = self._cut_cache
        if xf_id is not self._xf or ckey != key:
            parts, geom = self.model.parts, self.geom
            ps = [parts[pi] for pi in pis]
            xf = [self._transform(p) for p in ps]
            wc, A, h = cutclass.box_world(np.array([p.local_min for p in ps]), np.array([p.local_max for p in ps]),
                                          np.stack([x[0] for x in xf]))
            dlo, dhi = cutclass.plane_bounds(wc, A, h, planes, on)
            plen = [float(np.linalg.norm(planes[i][:3].astype(np.float64))) for i in range(3) if on[i]]
            straddle = np.array([x[3] != 0.0 or (anim_on and geom.anim_base[pi] >= 0) for x, pi in zip(xf, pis)])
            st = (wc, A, h, dlo, dhi, plen, straddle, np.array([bool(x[4]) for x in xf]))
            self._cut_cache = (self._xf, key, st)
        wc, A, h, dlo, dhi, plen, straddle, never = st
        tan_y = abs(1.0 / Pm[1, 1])
        res = cutclass.classes_from_bounds(dlo, dhi, plen, cutclass.pixel_margin(wc, A, h, V, tan_y, ortho, height), mode, straddle, never)
        return dict(zip(pis, (int(c) for c in res)))

    def _draw_cut(self, rp, entries, cls, samples):
        """_draw_slots of a cut view: parts wholly on the removed side are skipped, the ones wholly on the kept side take the plain
        fragment stage (early depth rejection), the rest the discard. Draw order is kept (runs of one class between pipeline sets)."""
        run, last = [], None
        for e in entries:
            c = cls[e[1]]
            if c == cutclass.REMOVED:
                continue
            if c != last and run:
                rp.set_pipeline(self._vis_pipe(samples, last == cutclass.STRADDLE))
                self._draw_slots(rp, run)
                run = []
            last = c
            run.append(e)
        if run:
            rp.set_pipeline(self._vis_pipe(samples, last == cutclass.STRADDLE))
            self._draw_slots(rp, run)

    def render(self, target, size, camera, s, fs=None, out_size=None):
        """Render one frame into ``target`` (a wgpu texture, rgba8unorm, RENDER_ATTACHMENT). ``size`` is the render
        resolution, ``out_size`` the target's when the picture is scaled on the way."""
        self.frame_ok = False
        w, h = max(int(size[0]), 2), max(int(size[1]), 2)
        ow, oh = (int(out_size[0]), int(out_size[1])) if out_size is not None else (w, h)
        self._ids_cache = None
        samples = self._pick_samples(s.msaa)
        self._ensure_targets(w, h, samples)
        self._refresh_env(s)
        aspect = w / h
        camera.aspect = aspect
        V = camera.view_matrix()
        Pm = camera.proj_matrix(aspect)
        VP = Pm @ V
        self.last_vp = VP
        campos = camera.position()
        halves = camera.ortho_halves(aspect) if camera.ortho else camera.half_tans(aspect)
        self.last_camera = (V, Pm, aspect, camera.ortho, halves, (w, h))
        near, far = camera.near_far()
        m = self.model
        have = m is not None and self.geom is not None
        fs, vis, ghost, alpha = self._state(fs) if m is not None else (fs or FrameState(), None, None, None)
        self._fs = fs
        if m is not None:
            self._refresh_transforms(m)
            self._level = self._lod_levels(V, halves, camera.ortho, h)
        clip_planes = np.array(fs.clip_planes, dtype=np.float32)
        clip_on = tuple(int(bool(x)) for x in fs.clip_on)
        any_clip = any(clip_on)
        draws, oit = [], []
        if m is not None:
            draws, oit = self.visible_parts(VP, vis, ghost, alpha, fs)
            self._check_supported(m, fs, draws, oit, any_clip)
            self._upload_item_state(fs, s, ghost, alpha)
            self._upload_anim(fs)
        lights = self._lights(V, s)
        clip = (clip_planes, clip_on, int(fs.clip_mode))
        # ---- cut faces: which items are cut and the per-part uniforms (None when nothing is cut)
        cplan = None
        if any_clip and have and draws:
            cplan = self.caps.plan(m, self.geom, draws, VP, V, (w, h), fs, s, clip, camera)
        elif not any_clip and self.caps.t:
            self.caps.release()
        self._capon = 0 if cplan is None else 1
        if self._bg_vis_none is None:
            self._bg_vis_none = self._make_bg_vis(self._cap_none)
        if cplan is None:
            self._bg_vis = self._bg_vis_none
        else:
            if self._bg_vis_cap is None or self._cap_col_v is not self.caps.v["col"] or self._bg_vis_size != (w, h, samples):
                self._cap_col_v = self.caps.v["col"]
                self._bg_vis_cap = self._make_bg_vis(self._cap_col_v)
                self._bg_vis_size = (w, h, samples)
            self._bg_vis = self._bg_vis_cap
        sg = self._global_uniforms(V, campos, lights, s, (w, h), camera, clip)
        table, entries, bits = (self._build_table(draws, s, fs) if have else
                                (np.zeros((1, DRAW_FLOATS), np.float32), [], self.prim_bits_max))
        self.last_table, self.last_draws, self.last_prim_bits = table, entries, bits
        self._ensure_table(len(table), len(self._look_bytes))
        if self._looks_written < len(self._look_bytes):
            blob = np.frombuffer(b"".join(self._look_bytes[self._looks_written:]), dtype=np.uint8)
            self.queue.write_buffer(self._tab, self._tab_off["looks"] * 4 + self._looks_written * SHADE_SIZE, blob)
            self._looks_written = len(self._look_bytes)

        f = np.zeros(60, dtype=np.float32)
        u = f.view(np.uint32)
        f[0:16] = np.ascontiguousarray((GL_TO_WGPU_Z @ VP).T, dtype=np.float32).reshape(-1)
        f[16:32] = np.ascontiguousarray(V.T, dtype=np.float32).reshape(-1)
        f[32:44] = clip_planes.reshape(-1)
        u[44:47] = clip_on
        u[47] = int(fs.clip_mode)
        f[48:52] = (w, h, ow, oh)
        f[52:56] = (halves[0], halves[1], near, far)
        u[56:60] = (bits, samples, len(entries), 1 if camera.ortho else 0)
        self.queue.write_buffer(self._frame_ub, 0, f)
        self.queue.write_buffer(self._tab, self._tab_off["draws"] * 4, np.ascontiguousarray(table))
        self.queue.write_buffer(self._sg, 0, np.frombuffer(sg, dtype=np.uint8))
        self.queue.write_buffer(self._final_ub, 0, np.array([w, h, ow, oh], dtype=np.float32))

        enc = self.device.create_command_encoder()
        qs = self._qs
        post = self.post
        T, V_ = self.t, self.v
        # ---- 0. backdrop (GL: drawn into the MSAA colour buffer after its clear)
        world = self.world or DEFAULT_WORLD
        top, bottom = s.background if s.background is not None else (world.get("top_hex", "#20242b"),
                                                                      world.get("bottom_hex", "#12141a"))
        k = 2.0 ** -float(s.exposure)          # the backdrop keeps its colour whatever the exposure
        post.pending_ts = self._ts(qs, 12, 13)
        post.run_backdrop(T["bg"], np.array(backdrop_linear(bottom, s.tonemap)) * k, np.array(backdrop_linear(top, s.tonemap)) * k,
                          encoder=enc)
        # ---- 1. visibility pass
        cut_cls = self._cut_classes(entries, clip_planes, clip_on, fs.clip_mode, V, Pm, h, bool(camera.ortho)) if (any_clip and entries and self.classify_cut) else None
        drawn_tris = sum(e[4] for e in entries) // 3
        if self.culler is not None and self.gov is not None and self.cull_mode == "auto":
            for tag, kept, pulled in self.culler.stats_poll():       # counters of earlier culled frames, never waited for
                self.gov.observe(tag, kept, pulled)
        real = self._want_cull(drawn_tris, bool(entries), bool(any_clip))
        self.culled_frame = use_cull = self._use_cull(drawn_tris, bool(entries), real)
        self.cull_accept_all = bool(use_cull and self._cmp and not real)
        if self.culler is not None:
            self.culler.stats_wanted = bool(real and self.gov is not None and self.cull_mode == "auto" and self.gov.want_counters())
        if use_cull:
            # cluster culling: the culler records both visibility passes itself (compute runs between them). Parts it cannot
            # bound come back as `unculled` and are drawn here with the plain pipeline, ids stay (slot << bits) | primitive.
            if qs:
                enc.begin_compute_pass(timestamp_writes=self._ts(qs, 0, 1)).end()      # slots 0, 1 are replaced by the culler's
            fp, pis = self._frame_parts(entries)

            def draw_plain(rp_, positions, entries=entries, pis=pis, cut_cls=cut_cls):
                want = {pis[i] for i in positions}
                rp_.set_bind_group(0, self._bg0_vis)
                if cut_cls is not None:
                    return self._draw_cut(rp_, [e for e in entries if e[1] in want], cut_cls, samples)
                rp_.set_pipeline(self._vis_pipe(samples, any_clip))
                self._draw_slots(rp_, [e for e in entries if e[1] in want])

            self.culler.encode(enc, V, Pm, (w, h), V_["vis_id"], V_["vis_depth"], samples, fp,
                               clip=ClipState(planes=clip_planes, on=clip_on, mode=int(fs.clip_mode)), ortho=bool(camera.ortho),
                               draw_unculled=draw_plain, out_size=(ow, oh), bits=bits, accept_all=self.cull_accept_all)
        else:
            rp = enc.begin_render_pass(
                color_attachments=[{"view": V_["vis_id"], "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 0)}],
                depth_stencil_attachment={"view": V_["vis_depth"], "depth_load_op": "clear", "depth_store_op": "store",
                                          "depth_clear_value": 1.0},
                **({"timestamp_writes": self._ts(qs, 0, 1)} if qs else {}))
            if entries:
                rp.set_bind_group(0, self._bg0_vis)
                if cut_cls is not None:
                    self._draw_cut(rp, entries, cut_cls, samples)
                else:
                    rp.set_pipeline(self._vis_pipe(samples, any_clip))
                    self._draw_slots(rp, entries)
            rp.end()
        groups = self._groups if have else []
        # ---- 2. geometry resolve (GL's pre-pass: ids, normals, depth), one pass per group of pages
        # nd.w is written as a fourth target (no post_pack pass) when the SSAO runs and nothing edits nd afterwards (cut faces do)
        fuse_depth = bool(s.ao and m is not None and cplan is None)
        for gi, grp in enumerate(groups or [None]):
            op = "clear" if gi == 0 else "load"
            tw = {}
            if qs and gi == 0:
                tw.update({"query_set": qs, "beginning_of_pass_write_index": 2})
            if qs and gi == max(len(groups), 1) - 1:
                tw.update({"query_set": qs, "end_of_pass_write_index": 3})
            rp = enc.begin_render_pass(
                color_attachments=[{"view": V_[n], "load_op": op, "store_op": "store", "clear_value": (0, 0, 0, 0)}
                                   for n in ("tri", "id", "nd") + (("ssao_depth",) if fuse_depth else ())],
                depth_stencil_attachment={"view": V_["res_order"], "depth_load_op": op, "depth_store_op": "store",
                                          "depth_clear_value": 1.0}, **({"timestamp_writes": tw} if tw else {}))
            if grp is not None:
                p0, n, bg = grp
                rp.set_pipeline(self._geom_pipe(samples, n, p0, fuse_depth))
                rp.set_bind_group(0, self._bg0_res)
                rp.set_bind_group(1, self._shade_bind_group())
                rp.set_bind_group(2, self._bg_vis)
                rp.set_bind_group(3, bg)
                rp.draw(3)
            rp.end()
        # ---- 2a. cut faces (GL's CAPMIX_PRE_FS): gather the innermost cut face per pixel, lay it into id / nd
        if cplan is not None:
            self.caps.encode_gather(enc, cplan, (qs, 14, 15) if qs else None)
            self.caps.encode_lay_in(enc, T["id"], T["nd"])
        # ---- 2b. translucent and x-rayed parts: weighted blended OIT into the visibility pass's depth (GL pass 5);
        # encoded after the shaded resolve (below), which still needs the visibility depth without the cut faces
        oit_draws = []
        if oit and have:
            oit_draws = self._oit_draws(oit, VP, V, campos, lights, s, (w, h), camera, clip, fs, alpha, ghost)
        # ---- 3. SSAO (reads the previous frame's resolved colour, `opaque`) and the two blur passes
        if s.ao and m is not None:
            radius = s.ao_radius or self._auto_ao_radius()
            post.pending_ts = self._ts(qs, 4, None)
            post.run_ssao(T["nd"], T["opaque"], T["ao"], tan=(halves[0], halves[1]), ortho=1 if camera.ortho else 0,
                          radius=float(radius), power=float(1.6 * s.ao_strength), large=float(s.ao_large),
                          large_mix=float(s.ao_large_mix), gi_on=1.0 if s.bounce > 0 else 0.0, samples=16, encoder=enc,
                          depth=T["ssao_depth"], depth_ready=fuse_depth)
            post.run_blur(T["ao"], T["nd"], T["ao_tmp"], (1.0 / w, 0.0), encoder=enc)
            post.pending_ts = self._ts(qs, None, 5)
            post.run_blur(T["ao_tmp"], T["nd"], T["ao"], (0.0, 1.0 / h), encoder=enc)
        # ---- 3b. shade the cut faces (after the AO, which they read)
        if cplan is not None:
            self._shade_bind_group()
            cg = self.caps.shade_bind_group(self._sg, self._items_v, self.v["ao"], self._spec_v, self._white.create_view(),
                                            self._s_ao, self.post.s_env, self._s_tex)
            self.caps.encode_colour(enc, cg)
        # ---- 4. shaded resolve into `opaque`
        if groups:
            slots = sorted({0, *(int(table[e[0], 38].view(np.uint32)) for e in entries)})
            plan = [(p0, n, bg, sl) for (p0, n, bg) in groups for sl in slots]
            for gi, (p0, n, bg, sl) in enumerate(plan):
                tw = {}
                sx = None
                if self.split.enabled(samples, n):          # the extra triangles of edge pixels in a compute pass first
                    sx = self.split.prepare(enc, samples, n, p0, self._frame_feat, self._shade_bind_group(sl, 1 if gi == 0 else 0),
                                            bg, (w, h), (qs, 6) if qs and gi == 0 else None)
                if qs and gi == 0 and sx is None:
                    tw.update({"query_set": qs, "beginning_of_pass_write_index": 6})
                if qs and gi == len(plan) - 1:
                    tw.update({"query_set": qs, "end_of_pass_write_index": 7})
                rp = enc.begin_render_pass(
                    color_attachments=[{"view": V_["opaque"], "load_op": "clear" if gi == 0 else "load", "store_op": "store",
                                        "clear_value": (0, 0, 0, 0)}], **({"timestamp_writes": tw} if tw else {}))
                rp.set_pipeline(self._shade_pipe(samples, n, p0, self._frame_feat) if sx is None else sx[0])
                rp.set_bind_group(0, self._bg0_res)
                rp.set_bind_group(1, self._shade_bind_group(sl, 1 if gi == 0 else 0))
                rp.set_bind_group(2, self._bg_vis if sx is None else sx[1])
                rp.set_bind_group(3, bg)
                rp.draw(3)
                rp.end()
        else:
            enc.copy_texture_to_texture({"texture": T["bg"], "mip_level": 0, "origin": (0, 0, 0)},
                                        {"texture": T["opaque"], "mip_level": 0, "origin": (0, 0, 0)}, (w, h, 1))
        # ---- 4b. cut faces into the visibility depth (GL: depth_ms after CAPMIX_FS), then the translucent pass tests against it
        if cplan is not None:
            self.caps.encode_depth(enc, V_["vis_depth"], samples, gl_order=True)
        if oit_draws:
            self._shade_bind_group()
            self.oit.encode(enc, oit_draws, size=(w, h), samples=samples, depth_view=V_["vis_depth"], targets=self.oit_t,
                            items=self._items_v, spec=self._spec_v, vp_wgpu=GL_TO_WGPU_Z @ VP, anim_tab=self.anim_section())
        # ---- 5. composite (no translucent items yet: accum / weight stay zero)
        hov = fs.hovered + 1 if fs.hovered >= 0 else s.hovered
        post.pending_ts = self._ts(qs, 8, 9)
        post.run_composite(T["opaque"], self.oit_t["accum"] if oit_draws else T["accum"],
                           self.oit_t["weight"] if oit_draws else T["weight"], T["id"], T["comp"], oit_on=bool(oit_draws),
                           has_sel=bool(fs.selected or s.selected),
                           hover=float(hov if s.hover_outline_on and hov not in {i + 1 for i in fs.selected} else 0),
                           outline=s.outline, hover_outline=s.hover_outline, exposure=float(s.exposure),
                           tonemap=bool(s.tonemap), encoder=enc)
        # ---- 6. into the target: flip to top-first, scale when the window is not the render size
        bgf = self.device.create_bind_group(layout=self.bgl_final, entries=[
            {"binding": 0, "resource": {"buffer": self._final_ub, "offset": 0, "size": 16}},
            {"binding": 1, "resource": V_["comp"]}, {"binding": 2, "resource": self._s_final}])
        rp = enc.begin_render_pass(
            color_attachments=[{"view": target.create_view(), "load_op": "clear", "store_op": "store",
                                "clear_value": (0, 0, 0, 1)}], **({"timestamp_writes": self._ts(qs, 10, 11)} if qs else {}))
        rp.set_pipeline(self._final_pipe())
        rp.set_bind_group(0, bgf)
        rp.draw(3)
        rp.end()
        if qs:
            if cplan is None:                                  # slots 14, 15 (the cap gather) must be written before they are resolved
                enc.begin_compute_pass(timestamp_writes=self._ts(qs, 14, 15)).end()
            enc.resolve_query_set(qs, 0, 16, self._qbuf, 0)
        self.queue.submit([enc.finish()])
        if use_cull and self.culler.stats_wanted:
            self.culler.stats_arm(self.gov.tag)
        if qs:
            ts = np.frombuffer(bytes(self.queue.read_buffer(self._qbuf, 0, 16 * 8)), dtype=np.uint64).astype(np.float64)
            kk = self.ts_period_ns * 1e-6
            d = lambda a, b: (ts[b] - ts[a]) * kk
            cull_t = self.culler.read_timings(self.ts_period_ns) if use_cull else None
            self.timings = {"backdrop_ms": d(12, 13), "vis_ms": cull_t["total_ms"] if use_cull else d(0, 1), "geom_ms": d(2, 3), "ssao_ms": d(4, 5) if s.ao else 0.0,
                            "shade_ms": d(6, 7), "composite_ms": d(8, 9), "final_ms": d(10, 11),
                            "caps_ms": d(14, 15) if cplan is not None else 0.0}
            self.timings["cull"] = cull_t                     # per stage ms of the culler (None: not culled)
            self.timings["resolve_ms"] = self.timings["geom_ms"] + self.timings["shade_ms"]
            self.timings["total_ms"] = sum(v for kx, v in self.timings.items() if kx.endswith("_ms") and kx != "resolve_ms")
        self.frame_ok = True

    # ------------------------------------------------------------------ readbacks (GL semantics)
    def _unproject(self, gx, gy, d):
        """World point at GL pixel (gx, gy) (y up) whose linear view depth is d."""
        V, Pm, aspect, ortho, halves, (w, h) = self.last_camera
        ndc = np.array([gx / w * 2 - 1, gy / h * 2 - 1])
        if ortho:
            pv = np.array([ndc[0] * halves[0], ndc[1] * halves[1], -d, 1.0])
        else:
            pv = np.array([ndc[0] * halves[0] * d, ndc[1] * halves[1] * d, -d, 1.0])
        return (np.linalg.inv(V) @ pv)[:3]

    def _gather_buffers(self, n):
        g = self._gather
        d = self.device
        if "params" not in g:
            g["params"] = d.create_buffer(size=32, usage=BU.UNIFORM | BU.COPY_DST, label="gather_params")
        if g.get("cap", 0) < n:
            cap = max(64, 1 << (n - 1).bit_length())
            for k in ("pts", "out"):
                if k in g:
                    g[k].destroy()
            g["pts"] = d.create_buffer(size=cap * 8, usage=BU.STORAGE | BU.COPY_DST, label="gather_pts")
            g["out"] = d.create_buffer(size=cap * 16, usage=BU.STORAGE | BU.COPY_SRC, label="gather_out")
            g["cap"] = cap
            g["bg"] = d.create_bind_group(layout=self.bgl_gather, entries=[
                {"binding": 60, "resource": {"buffer": g["params"], "offset": 0, "size": 32}},
                {"binding": 61, "resource": {"buffer": g["pts"], "offset": 0, "size": g["pts"].size}},
                {"binding": 62, "resource": {"buffer": g["out"], "offset": 0, "size": g["out"].size}}])
        return g

    def _gather_run(self, entry, n_out, params, pts=None):
        g = self._gather_buffers(max(n_out, 1))
        self.queue.write_buffer(g["params"], 0, np.array(params, dtype=np.uint32))
        if pts is not None and len(pts):
            self.queue.write_buffer(g["pts"], 0, np.ascontiguousarray(pts, dtype=np.int32))
        enc = self.device.create_command_encoder()
        cp = enc.begin_compute_pass()
        cp.set_pipeline(self._gather_pipe(entry))
        cp.set_bind_group(0, self._bg0_cmp)
        cp.set_bind_group(1, self.bg_empty)
        cp.set_bind_group(2, self._bg_res)
        cp.set_bind_group(3, g["bg"])
        return enc, cp, g

    def _gather_finish(self, enc, cp, g, n_out):
        cp.end()
        self.queue.submit([enc.finish()])
        raw = bytes(self.queue.read_buffer(g["out"], 0, n_out * 16))
        return np.frombuffer(raw, dtype=np.float32).reshape(n_out, 4)

    def _points(self, pts):
        """(n, 4) float32 rows (item + 1, flags, depth, triangle id bits) at pixels (x, y from the top-left)."""
        pts = np.asarray(pts, dtype=np.int32).reshape(-1, 2)
        n = len(pts)
        w, h = self.size
        enc, cp, g = self._gather_run("cs_points", n, [w, h, 0, 0, 0, n, 0, 0], pts)
        cp.dispatch_workgroups((n + 63) // 64)
        return self._gather_finish(enc, cp, g, n)

    def pick(self, x, y):
        """(item index or -1, world point or None, on a cut face) under render pixel (x, y from the top-left)."""
        if self.last_camera is None or not self.t or not self.frame_ok:
            return -1, None, False
        V, Pm, aspect, ortho, halves, (w, h) = self.last_camera
        if not (0 <= x < w and 0 <= y < h):
            return -1, None, False
        r = self._points([(int(x), int(y))])[0]
        d = float(r[2])
        if not np.isfinite(d) or d <= 0.0:
            return self._pick_centre(int(x), int(y))
        gy = h - 1 - int(y)
        return int(round(float(r[0]))) - 1, self._unproject(x + 0.5, gy + 0.5, d), (int(round(float(r[1]))) & 2) != 0

    def _pick_centre(self, x, y):
        """GL's pre-pass is ONE sample at the pixel centre, so a feature thinner than the MSAA samples can still be hit
        there. Called only when the resolved buffers hold the background at (x, y): the visibility pass is drawn again
        single-sampled with a the target a 1x1 texture and the viewport translated to the pixel. Returns (item or -1, world point or None, False)."""
        if not self.last_draws or self.id_format != "r32uint":
            return -1, None, False
        w, h = self.size
        gy = h - 1 - y
        pt = getattr(self, "_pick_t", None)
        if pt is None:
            RA = TU.RENDER_ATTACHMENT
            pt = {"id": self.device.create_texture(size=(1, 1, 1), format=self.id_format, usage=RA | TU.COPY_SRC,
                                                   label="pick_id"),
                  "depth": self.device.create_texture(size=(1, 1, 1), format="depth32float", usage=RA | TU.COPY_SRC,
                                                      label="pick_depth")}
            self._pick_t = pt
        enc = self.device.create_command_encoder()
        rp = enc.begin_render_pass(
            color_attachments=[{"view": pt["id"].create_view(), "load_op": "clear", "store_op": "store",
                                "clear_value": (0, 0, 0, 0)}],
            depth_stencil_attachment={"view": pt["depth"].create_view(), "depth_load_op": "clear",
                                      "depth_store_op": "store", "depth_clear_value": 1.0})
        rp.set_pipeline(self._vis_pipe(1, any(self._fs.clip_on)))
        rp.set_bind_group(0, self._bg0_vis)
        rp.set_viewport(-x, -gy, w, h, 0.0, 1.0)      # the full-size picture translated so pixel (x, gy) is the 1x1 target
        self._draw_slots(rp, self.last_draws)          # unculled: the plain draw of the (cluster ordered) geometry, ids = slot only
        rp.end()
        bi = self.device.create_buffer(size=256, usage=BU.COPY_DST | BU.MAP_READ)
        bd = self.device.create_buffer(size=256, usage=BU.COPY_DST | BU.MAP_READ)
        enc.copy_texture_to_buffer({"texture": pt["id"], "mip_level": 0, "origin": (0, 0, 0)},
                                   {"buffer": bi, "offset": 0, "bytes_per_row": 256, "rows_per_image": 1}, (1, 1, 1))
        enc.copy_texture_to_buffer({"texture": pt["depth"], "mip_level": 0, "origin": (0, 0, 0)},
                                   {"buffer": bd, "offset": 0, "bytes_per_row": 256, "rows_per_image": 1}, (1, 1, 1))
        self.queue.submit([enc.finish()])
        out = []
        for b, dt in ((bi, np.uint32), (bd, np.float32)):
            b.map_sync(wgpu.MapMode.READ)
            out.append(np.frombuffer(bytes(b.read_mapped())[:4], dtype=dt)[0])
            b.unmap()
            b.destroy()
        vid, z = int(out[0]), float(out[1])
        slot = vid >> self.last_prim_bits
        if slot == 0 or slot >= len(self.last_table):
            return -1, None, False
        item = int(self.last_table.view(np.uint32)[slot, 33])
        V, Pm, aspect, ortho, halves, _ = self.last_camera
        ndc = np.array([(x + 0.5) / w * 2 - 1, (gy + 0.5) / h * 2 - 1, z, 1.0])
        q = np.linalg.inv(GL_TO_WGPU_Z @ self.last_vp) @ ndc
        return item, (q[:3] / q[3]), False

    def read_label_samples(self, step):
        """(ids, flags, depth, centre ids) on a grid of cells `step` pixels wide, top row first, or None."""
        if not self.frame_ok or not self.t:
            return None
        w, h = self.size
        step = int(step)
        gw, gh = -(-w // step), -(-h // step)
        enc, cp, g = self._gather_run("cs_labels", gw * gh, [w, h, gw, gh, step, 0, 0, 0])
        cp.dispatch_workgroups((gw + 7) // 8, (gh + 7) // 8)
        v = self._gather_finish(enc, cp, g, gw * gh).reshape(gh, gw, 4)
        return (np.rint(v[..., 0]).astype(np.int32) - 1, np.rint(v[..., 1]).astype(np.int32), v[..., 2].copy(),
                np.rint(v[..., 3]).astype(np.int32) - 1)

    def _read_texture(self, tex, bytes_per_px, dtype, comps):
        w, h = self.size
        bpr = _align(w * bytes_per_px)
        buf = self.device.create_buffer(size=bpr * h, usage=BU.COPY_DST | BU.MAP_READ)
        enc = self.device.create_command_encoder()
        enc.copy_texture_to_buffer({"texture": tex, "mip_level": 0, "origin": (0, 0, 0)},
                                   {"buffer": buf, "offset": 0, "bytes_per_row": bpr, "rows_per_image": h}, (w, h, 1))
        self.queue.submit([enc.finish()])
        buf.map_sync(wgpu.MapMode.READ)
        raw = np.frombuffer(bytes(buf.read_mapped()), dtype=np.uint8)
        buf.unmap()
        buf.destroy()
        # the single-sample textures keep GL's row order (row 0 = bottom); the arrays handed out start at the top
        return np.ascontiguousarray(raw.reshape(h, bpr)[::-1, :w * bytes_per_px]).view(dtype).reshape(h, w, comps)

    def read_ids(self):
        """(h, w) item index (-1 background) and (h, w) flags of the last frame, top row first."""
        if not self.frame_ok or not self.t:
            return None, None
        if self._ids_cache is not None:
            return self._ids_cache
        a = self._read_texture(self.t["id"], 8, np.float32, 2)
        self._ids_cache = (np.rint(a[..., 0]).astype(np.int32) - 1, np.rint(a[..., 1]).astype(np.int32))
        return self._ids_cache

    def read_depth(self):
        """(h, w) linear view depth of the last frame (0 background), top row first."""
        if not self.frame_ok or not self.t:
            return None
        return self._read_texture(self.t["nd"], 16, np.float32, 4)[..., 3].copy()

    def read_normals(self):
        """(h, w, 3) view-space unit normals of the last frame (0 background), top row first."""
        if not self.frame_ok or not self.t:
            return None
        return self._read_texture(self.t["nd"], 16, np.float32, 4)[..., :3].copy()

    def read_triangles(self):
        """(h, w) uint32 packed triangle id ((slot << prim_bits) | primitive), 0 background (extra, for checks). The resolve has
        decoded culled ids already, so this is the plain id either way; for cluster-ordered geometry its primitive is the STORED
        triangle number: use triangle_info / read_model_triangles for the model's own triangle numbers."""
        if not self.frame_ok or not self.t:
            return None
        return self._read_texture(self.t["tri"], 4, np.uint32, 1)[..., 0].copy()

    def triangle_info(self, ids):
        """(part index, LOD level, ORIGINAL triangle) int64 arrays of packed triangle ids of the last frame (-1 where the id is
        the background or outside the table). The original triangle is the index in model.indices[part.first:...] (level 0) or
        model.lod[part.id].indices[level - 1] counted in triangles. Plain ids ((slot << bits) | primitive) of cluster-ordered
        parts go through geom.order (stored -> original); ids with bit 31 set are raw culled ids (culler.decode_ids)."""
        ids = np.asarray(ids, dtype=np.uint32)
        part = np.full(ids.shape, -1, dtype=np.int64)
        level = np.full(ids.shape, -1, dtype=np.int64)
        tri = np.full(ids.shape, -1, dtype=np.int64)
        if self.last_table is None or self.geom is None:
            return part, level, tri
        culled = (ids & np.uint32(0x80000000)) != 0
        if culled.any() and self.culler is not None:
            _c, cp, ct, rr = self.culler.decode_ids(ids)
            cd = self.culler.cd
            part[culled], tri[culled] = cp[culled], ct[culled]
            level[culled] = [int(np.nonzero(cd.level_range[p] == r)[0][0]) if r >= 0 else -1 for p, r in zip(cp[culled], rr[culled])]
        plain = ~culled
        slot = (ids >> np.uint32(self.last_prim_bits)).astype(np.int64)
        ok = plain & (slot > 0) & (slot < len(self.last_table))
        if ok.any():
            tu = self.last_table.view(np.uint32)
            rec = tu[slot[ok]]
            pi, k = rec[:, 32].astype(np.int64), rec[:, 35].astype(np.int64)
            stored = (rec[:, 28].astype(np.int64) - np.array([self._range_first(a, b) for a, b in zip(pi, k)], dtype=np.int64)) // 3                 + (ids[ok].astype(np.int64) & ((1 << self.last_prim_bits) - 1))
            part[ok], level[ok] = pi, k
            tri[ok] = self.geom.order.original(pi, k, stored) if self.geom.order is not None else stored
        return part, level, tri

    def _range_first(self, part, level):
        rng = self.geom.ranges[int(part)]
        return rng[int(level)][0] if level < len(rng) else rng[0][0]

    def read_model_triangles(self):
        """((h, w) part index, (h, w) original triangle number) of the last frame, -1 on the background; top row first."""
        t = self.read_triangles()
        if t is None:
            return None, None
        part, _level, tri = self.triangle_info(t)
        return part, tri

    def triangles_at(self, points):
        """[(part index, original triangle) or None, ...] at render pixels [(x, y from the top-left), ...] of the last frame."""
        if not self.frame_ok or not self.t:
            return [None] * len(points)
        w, h = self.size
        ok = [i for i, (x, y) in enumerate(points) if 0 <= x < w and 0 <= y < h]
        out = [None] * len(points)
        if ok:
            r = self._points([(int(points[i][0]), int(points[i][1])) for i in ok])
            part, _level, tri = self.triangle_info(np.ascontiguousarray(r[:, 3]).view(np.uint32))
            for j, i in enumerate(ok):
                if part[j] >= 0:
                    out[i] = (int(part[j]), int(tri[j]))
        return out

    def ids_at(self, points):
        """Item index at render pixels [(x, y from the top-left), ...] of the last frame (-1: background / outside)."""
        if not self.frame_ok or not self.t:
            return [-1] * len(points)
        w, h = self.size
        out = [-1] * len(points)
        if self._ids_cache is not None:
            for i, (x, y) in enumerate(points):
                if 0 <= x < w and 0 <= y < h:
                    out[i] = int(self._ids_cache[0][int(y), int(x)])
            return out
        ok = [i for i, (x, y) in enumerate(points) if 0 <= x < w and 0 <= y < h]
        if ok:
            r = self._points([(int(points[i][0]), int(points[i][1])) for i in ok])
            for i, row in zip(ok, r):
                out[i] = int(round(float(row[0]))) - 1
        return out

    def world_from_pixel(self, x, y, d):
        """World point at render pixel (x, y from the top-left) and linear depth d of the last frame."""
        if self.last_camera is None or not self.frame_ok:
            return None
        h = self.last_camera[5][1]
        return self._unproject(x + 0.5, h - 1 - y + 0.5, d)

    def read_final(self, target, size):
        """(h, w, 3) uint8 copy of a rendered rgba8unorm target, top row first."""
        w, h = size
        bpr = _align(w * 4)
        buf = self.device.create_buffer(size=bpr * h, usage=BU.COPY_DST | BU.MAP_READ)
        enc = self.device.create_command_encoder()
        enc.copy_texture_to_buffer({"texture": target, "mip_level": 0, "origin": (0, 0, 0)},
                                   {"buffer": buf, "offset": 0, "bytes_per_row": bpr, "rows_per_image": h}, (w, h, 1))
        self.queue.submit([enc.finish()])
        buf.map_sync(wgpu.MapMode.READ)
        raw = np.frombuffer(bytes(buf.read_mapped()), dtype=np.uint8)
        buf.unmap()
        buf.destroy()
        return np.ascontiguousarray(raw.reshape(h, bpr)[:, :w * 4].reshape(h, w, 4)[..., :3])
