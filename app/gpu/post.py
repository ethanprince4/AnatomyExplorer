"""Full-screen post passes of the wgpu renderer: backdrop, SSAO, blur, composite, blit and the environment prefilter.

Ports of app/viewer/shaders.py (see wgsl/post_common.wgsl for the list of GLSL -> WGSL differences). Every texture
keeps GL's row order (row 0 = bottom); see the first difference listed there.

Each ``run_*`` takes wgpu textures (not views) and records into ``encoder`` (a GPUCommandEncoder) when given, else it
makes and submits its own. Uniform buffers and bind groups are created per call (a few dozen bytes); the pipelines
are cached per (pass, target format).

Texture formats (same precision as GL):
  nd rgba32float, id rg32float, ao / ao_tmp rgba16float, opaque / accum / prev rgba16float, weight r16float,
  composite and blit targets rgba8unorm, backdrop target rgba16float, prefiltered env array rgba16float.
Half-resolution AO/GI (``ao_scale`` / ``gi_scale`` = 2, see PostPasses): the SSAO taps are evaluated for one representative
pixel per 2x2 block and the result is upsampled with a depth- and normal-aware weight before the unchanged blur.
Binding nd / id (32-bit float) needs no feature (unfilterable-float + nearest sampler). The environment source
texture is rgba32float and needs the ``float32-filterable`` device feature for trilinear filtering; without it
``make_env_source`` falls back to rgba16float (a rounding of the source by about 5e-4 relative).
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import wgpu

WGSL_DIR = Path(__file__).with_name("wgsl")
ROUGH_LAYERS = 6
SPEC_W, SPEC_H = 256, 128

TEX_USAGE = (wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.RENDER_ATTACHMENT
             | wgpu.TextureUsage.COPY_SRC | wgpu.TextureUsage.COPY_DST)

# bind layout kinds
_U, _TF, _TU, _SL, _SN, _SR, _TI = "uniform", "tex_f", "tex_u", "samp_lin", "samp_near", "samp_env", "tex_i"

_LAYOUTS = {
    "backdrop": [_U],
    "blit": [_TF, _SL],
    "blur": [_U, _TF, _TU, _SL, _SN],
    "ssao": [_U, _TU, _TF, _SL, _SN, _TU],
    "pack": [_TU],
    "ssao_half": [_U, _TU, _TF, _SL, _SN, _TU, _TU, _TI],
    "down": [_TU],
    "upsample": [_U, _TU, _TF, _TF, _TU],
    "prefilter": [_U, _TF, _SR],
    "composite": [_U, _TF, _TF, _TF, _TU, _SL, _SN],
}
_ENTRY = {"backdrop": "fs_backdrop", "blit": "fs_blit", "blur": "fs_blur", "ssao": "fs_ssao",
          "prefilter": "fs_prefilter", "composite": "fs_composite", "pack": "fs_pack",
          "ssao_half": "fs_ssao_half", "down": "fs_down", "upsample": "fs_upsample"}
_FILE = {"ssao_half": "ssao"}      # pass name -> post_<file>.wgsl where they differ

# sizes of the packed structs (asserted in tests/gpu/test_post_parity.py against the WGSL struct layout)
UNIFORM_SIZES = {"backdrop": 32, "ssao": 48, "blur": 16, "prefilter": 16, "composite": 64, "blit": 0, "pack": 0,
                 "ssao_half": 48, "down": 0, "upsample": 16}


def _f(*v):
    return [float(x) for x in v]


def pack_backdrop(bottom, top):
    # bottom 0, top 16
    return struct.pack("<4f4f", *_f(*bottom), 0.0, *_f(*top), 0.0)


def pack_ssao(tan, ortho, samples, radius, bias, power, large, large_mix, gi_on, mode=0):
    # tan 0, ortho 8 (i32), samples 12 (i32), radius 16, bias 20, power 24, large 28, large_mix 32, gi_on 36,
    # mode 44 (i32): 0 AO + GI, 1 AO only, 2 GI only
    return struct.pack("<2f2i6f2i", *_f(*tan), int(ortho), int(samples),
                       *_f(radius, bias, power, large, large_mix, gi_on), 0, int(mode))


def pack_upsample(mode):
    # mode 0 (i32): 0 = all four channels from the half-res texture, 1 = rgb from it and alpha from the full-res one
    return struct.pack("<4i", int(mode), 0, 0, 0)


def pack_blur(dir_):
    return struct.pack("<4f", *_f(*dir_), 0.0, 0.0)


def pack_prefilter(rough, src_w):
    return struct.pack("<4f", *_f(rough, src_w), 0.0, 0.0)


def pack_composite(outline, hover, hover_outline, exposure, texel, outline_px, oit_on, has_sel, tonemap):
    # outline 0, hover 12, hover_outline 16, exposure 28, texel 32, outline_px 40, oit_on 44 (i32),
    # has_sel 48 (i32), tonemap 52 (i32), pad to 64
    return struct.pack("<3ff3ff2ff3i2i", *_f(*outline), float(hover), *_f(*hover_outline), float(exposure),
                       *_f(*texel), float(outline_px), int(oit_on), int(has_sel), int(tonemap), 0, 0)


def _wgsl(name: str) -> str:
    return (WGSL_DIR / "post_common.wgsl").read_text() + "\n" + (WGSL_DIR / f"post_{_FILE.get(name, name)}.wgsl").read_text()


def _layout_entry(i, kind):
    vis = wgpu.ShaderStage.FRAGMENT
    if kind == _U:
        return {"binding": i, "visibility": vis, "buffer": {"type": "uniform"}}
    if kind == _TI:
        return {"binding": i, "visibility": vis, "texture": {"sample_type": "uint", "view_dimension": "2d"}}
    if kind == _TF:
        return {"binding": i, "visibility": vis, "texture": {"sample_type": "float", "view_dimension": "2d"}}
    if kind == _TU:
        return {"binding": i, "visibility": vis,
                "texture": {"sample_type": "unfilterable-float", "view_dimension": "2d"}}
    if kind in (_SL, _SR):
        return {"binding": i, "visibility": vis, "sampler": {"type": "filtering"}}
    return {"binding": i, "visibility": vis, "sampler": {"type": "non-filtering"}}


def _view(t):
    return t.create_view() if hasattr(t, "create_view") else t


class PostPasses:
    """``ao_scale`` / ``gi_scale`` (1 or 2; gi_scale defaults to ao_scale) set the resolution of the SSAO pass:
    2 evaluates the taps once per 2x2 block (at the pixel of the block whose depth is closest to the mean depth of the
    block's surface pixels, see wgsl/post_down.wgsl) and upsamples with a joint-bilateral filter (wgsl/post_upsample.wgsl).
    ao_scale = 2 does AO and GI at half resolution; ao_scale = 1, gi_scale = 2 keeps AO at full resolution and does
    only the (much more expensive) GI half-way. The blur passes are unchanged. Both can be changed at any time."""

    def __init__(self, device, ao_scale=1, gi_scale=None):
        self.device = device
        self.ao_scale = int(ao_scale)
        self.gi_scale = int(self.ao_scale if gi_scale is None else gi_scale)
        assert self.ao_scale in (1, 2) and self.gi_scale in (1, 2) and self.gi_scale >= self.ao_scale, (ao_scale, gi_scale)
        self._lo = {}                   # (w, h) -> half-res scratch textures of the half-res path
        self._hi = {}                   # (w, h) -> full-res AO scratch (ao_scale 1, gi_scale 2)
        self._pipes = {}
        self._layouts = {}
        self._mods = {}
        self.pending_ts = None          # {"query_set", "beginning_of_pass_write_index" / "end_of_pass_write_index"} for the next pass
        self.s_lin = device.create_sampler(mag_filter="linear", min_filter="linear", mipmap_filter="nearest",
                                           address_mode_u="clamp-to-edge", address_mode_v="clamp-to-edge")
        self.s_near = device.create_sampler(mag_filter="nearest", min_filter="nearest", mipmap_filter="nearest",
                                            address_mode_u="clamp-to-edge", address_mode_v="clamp-to-edge")
        self.s_env = device.create_sampler(mag_filter="linear", min_filter="linear", mipmap_filter="linear",
                                           address_mode_u="repeat", address_mode_v="clamp-to-edge")
        self.float32_filterable = "float32-filterable" in device.features
        self._depth = {}                # (w, h) -> r32float copy of nd.w, the only channel the hot SSAO taps need

    # ------------------------------------------------------------------ plumbing
    def _pipeline(self, name, fmt):
        key = (name, fmt)
        if key in self._pipes:
            return self._pipes[key]
        dev = self.device
        if name not in self._mods:
            self._mods[name] = dev.create_shader_module(code=_wgsl(name))
            bgl = dev.create_bind_group_layout(entries=[_layout_entry(i, k) for i, k in enumerate(_LAYOUTS[name])])
            self._layouts[name] = (bgl, dev.create_pipeline_layout(bind_group_layouts=[bgl]))
        mod = self._mods[name]
        bgl, pl = self._layouts[name]
        pipe = dev.create_render_pipeline(
            layout=pl,
            vertex={"module": mod, "entry_point": "vs_fsq"},
            primitive={"topology": "triangle-list", "cull_mode": "none"},
            fragment={"module": mod, "entry_point": _ENTRY[name],
                      "targets": [{"format": f} for f in (fmt if isinstance(fmt, tuple) else (fmt,))]},
        )
        self._pipes[key] = (pipe, bgl)
        return self._pipes[key]

    def _run(self, name, target_view, fmt, size, uniform, resources, encoder=None):
        dev = self.device
        pipe, bgl = self._pipeline(name, fmt)
        entries = []
        res = list(resources)
        for i, kind in enumerate(_LAYOUTS[name]):
            if kind == _U:
                assert len(uniform) == UNIFORM_SIZES[name], (name, len(uniform))
                ub = dev.create_buffer_with_data(data=uniform, usage=wgpu.BufferUsage.UNIFORM)
                entries.append({"binding": i, "resource": {"buffer": ub, "offset": 0, "size": len(uniform)}})
                continue
            r = res.pop(0)
            if kind in (_TF, _TU, _TI):
                r = _view(r)
            entries.append({"binding": i, "resource": r})
        bg = dev.create_bind_group(layout=bgl, entries=entries)
        enc = dev.create_command_encoder() if encoder is None else encoder
        tw, self.pending_ts = self.pending_ts, None          # the renderer's GPU timing of the next pass (or None)
        views = target_view if isinstance(target_view, tuple) else (target_view,)
        rp = enc.begin_render_pass(color_attachments=[{
            "view": v, "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 1)} for v in views],
            **({"timestamp_writes": tw} if tw else {}))
        rp.set_pipeline(pipe)
        rp.set_bind_group(0, bg)
        rp.set_viewport(0, 0, size[0], size[1], 0.0, 1.0)
        rp.draw(3, 1, 0, 0)
        rp.end()
        if encoder is None:
            dev.queue.submit([enc.finish()])

    # ------------------------------------------------------------------ passes
    def run_backdrop(self, target, bottom, top, encoder=None, fmt="rgba16float"):
        """bottom/top: scene-linear rgb already multiplied by 2**-exposure (renderer.py L813-815)."""
        self._run("backdrop", _view(target), fmt, target.size[:2], pack_backdrop(bottom, top), [], encoder)

    def run_blit(self, src, target, encoder=None, fmt="rgba8unorm"):
        self._run("blit", _view(target), fmt, target.size[:2], b"", [src, self.s_lin], encoder)

    def run_ssao(self, nd, prev, out, *, tan, ortho, radius, power, large, large_mix, gi_on, samples=16,
                 bias=None, encoder=None):
        """Writes AO in .a and one-bounce GI colour in .rgb. ``bias`` defaults to radius * 0.03, ``power`` is
        1.6 * ao_strength, ``gi_on`` is 1.0 if bounce > 0 else 0.0 (renderer.py L766-788)."""
        bias = radius * 0.03 if bias is None else bias
        u = pack_ssao(tan, ortho, samples, radius, bias, power, large, large_mix, gi_on)
        depth = self.pack_depth(nd, encoder)
        if self.gi_scale == 1:
            self._run("ssao", _view(out), "rgba16float", out.size[:2], u, [nd, prev, self.s_lin, self.s_near, depth],
                      encoder)
            return
        if self.ao_scale == 1:                      # AO at full resolution (alpha only), GI at half resolution
            hi = self._hi_tex(nd)
            self._run("ssao", _view(hi), "rgba16float", hi.size[:2],
                      pack_ssao(tan, ortho, samples, radius, bias, power, large, large_mix, gi_on, 1),
                      [nd, prev, self.s_lin, self.s_near, depth], encoder)
        else:
            hi = None
        lo = self._lo_set(nd, encoder)
        u = pack_ssao(tan, ortho, samples, radius, bias, power, large, large_mix, gi_on, 0 if self.ao_scale == 2 else 2)
        self._run("ssao_half", _view(lo["a"]), "rgba16float", lo["a"].size[:2], u,
                  [nd, prev, self.s_lin, self.s_near, depth, lo["nd"], lo["off"]], encoder)
        self._run("upsample", _view(out), "rgba16float", out.size[:2], pack_upsample(1 if hi is not None else 0),
                  [nd, lo["a"], lo["a"] if hi is None else hi, lo["nd"]], encoder)

    def _lo_set(self, nd, encoder):
        """Half-res scratch textures (a: SSAO result; nd: normal/depth of each 2x2 block's representative pixel;
        off: which pixel of the block, dx + 2 dy), owned by this object (one set per size); fills nd / off."""
        key = tuple(nd.size[:2])
        if key not in self._lo:
            hw, hh = (key[0] + 1) // 2, (key[1] + 1) // 2
            usage = wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC

            def mk(fmt, label):
                return self.device.create_texture(size=(hw, hh, 1), format=fmt, usage=usage, label=label)
            self._lo[key] = {"a": mk("rgba16float", "ao_lo"), "nd": mk("rgba32float", "ao_lo_nd"),
                             "off": mk("r8uint", "ao_lo_off")}
        lo = self._lo[key]
        self._run("down", (lo["nd"].create_view(), lo["off"].create_view()), ("rgba32float", "r8uint"),
                  lo["nd"].size[:2], b"", [nd], encoder)
        return lo

    def _hi_tex(self, nd):
        key = tuple(nd.size[:2])
        if key not in self._hi:
            self._hi[key] = self.device.create_texture(
                size=(key[0], key[1], 1), format="rgba16float", label="ao_hi",
                usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)
        return self._hi[key]

    def pack_depth(self, nd, encoder=None):
        """Exact copy of nd.w into an r32float texture (4 B per texel instead of 16). The SSAO taps (up to 128 per pixel)
        read only this channel; the pass costs one 16 B read and one 4 B write per pixel. The texture is owned by this
        object (one per size) and rewritten by every call. The renderer may write it directly instead (follow-up)."""
        key = tuple(nd.size[:2])
        t = self._depth.get(key)
        if t is None:
            t = self._depth[key] = self.device.create_texture(
                size=(key[0], key[1], 1), format="r32float",
                usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.RENDER_ATTACHMENT
                | wgpu.TextureUsage.COPY_SRC, label="ssao_depth")
        # a pending timestamp (the renderer's begin index of ssao_ms) lands on this first pass of the chain
        self._run("pack", t.create_view(), "r32float", key, b"", [nd], encoder)
        return t

    def run_blur(self, src, nd, out, direction, encoder=None):
        """direction = (1/w, 0) for the horizontal pass, (0, 1/h) for the vertical one."""
        self._run("blur", _view(out), "rgba16float", out.size[:2], pack_blur(direction),
                  [src, nd, self.s_lin, self.s_near], encoder)

    def run_composite(self, opaque, accum, weight, idtex, out, *, oit_on, has_sel, hover, outline, hover_outline,
                      exposure, tonemap, outline_px=None, encoder=None, fmt="rgba8unorm"):
        """hover is the item id to outline (0 = none), already resolved as in renderer.py L859-861.
        texel and outline_px are derived from the target size as in renderer.py L866-867."""
        w, h = out.size[0], out.size[1]
        u = pack_composite(outline, hover, hover_outline, exposure, (1.0 / w, 1.0 / h),
                           max(1.5, h / 540.0) if outline_px is None else outline_px,
                           1 if oit_on else 0, 1 if has_sel else 0, 1 if tonemap else 0)
        self._run("composite", _view(out), fmt, (w, h), u,
                  [opaque, accum, weight, idtex, self.s_lin, self.s_near], encoder)

    # ------------------------------------------------------------------ environment
    def make_env_source(self, env_rgb: np.ndarray):
        """Equirect radiance (h, w, 3) float32 -> mipmapped texture (full chain, 2x2 box filter on the CPU, like
        glGenerateMipmap on a power-of-two image). rgba32float if float32-filterable, else rgba16float."""
        dev = self.device
        h, w, _ = env_rgb.shape
        levels = int(np.floor(np.log2(max(w, h)))) + 1
        fmt = "rgba32float" if self.float32_filterable else "rgba16float"
        tex = dev.create_texture(size=(w, h, 1), mip_level_count=levels, format=fmt,
                                 usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST
                                 | wgpu.TextureUsage.COPY_SRC)
        cur = np.concatenate([env_rgb.astype(np.float32), np.ones((h, w, 1), np.float32)], -1)
        for lv in range(levels):
            lh, lw = cur.shape[:2]
            data = np.ascontiguousarray(cur if fmt == "rgba32float" else cur.astype(np.float16))
            dev.queue.write_texture({"texture": tex, "mip_level": lv, "origin": (0, 0, 0)}, data,
                                    {"bytes_per_row": lw * 4 * data.itemsize, "rows_per_image": lh}, (lw, lh, 1))
            if lv + 1 < levels:
                a = cur
                if lh > 1:
                    nh = lh // 2
                    a = (a[0:2 * nh:2] + a[1:2 * nh:2]) * 0.5
                if lw > 1:
                    nw = lw // 2
                    a = (a[:, 0:2 * nw:2] + a[:, 1:2 * nw:2]) * 0.5
                cur = a.astype(np.float32)
        return tex

    def run_prefilter(self, src, target, rough, src_w, encoder=None, layer=None, fmt=None):
        """One roughness step into ``target`` (a texture, or with ``layer`` a layer of a 2d-array texture)."""
        w, h = target.size[0], target.size[1]
        fmt = fmt or target.format
        if layer is not None:
            view = target.create_view(dimension="2d", base_array_layer=layer, array_layer_count=1)
        else:
            view = target.create_view()
        self._run("prefilter", view, fmt, (w, h), pack_prefilter(rough, src_w), [src, self.s_env], encoder)

    def build_env_spec(self, env_rgb: np.ndarray):
        """Prefiltered specular array (SPEC_W x SPEC_H x ROUGH_LAYERS, rgba16float), layer i = roughness i/5.
        Rows run along v like GL's array. Returns (spec_texture, source_texture)."""
        dev = self.device
        src = self.make_env_source(env_rgb)
        spec = dev.create_texture(size=(SPEC_W, SPEC_H, ROUGH_LAYERS), format="rgba16float",
                                  usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.RENDER_ATTACHMENT
                                  | wgpu.TextureUsage.COPY_SRC)
        enc = dev.create_command_encoder()
        for i in range(ROUGH_LAYERS):
            self.run_prefilter(src, spec, i / (ROUGH_LAYERS - 1), float(env_rgb.shape[1]), enc, layer=i,
                               fmt="rgba16float")
        dev.queue.submit([enc.finish()])
        return spec, src


# ---------------------------------------------------------------------- helpers shared with the parity tool
def make_texture(device, w, h, fmt, data=None, extra_usage=0):
    tex = device.create_texture(size=(w, h, 1), format=fmt, usage=TEX_USAGE | extra_usage)
    if data is not None:
        data = np.ascontiguousarray(data)
        comps = data.shape[2] if data.ndim == 3 else 1
        device.queue.write_texture({"texture": tex, "mip_level": 0, "origin": (0, 0, 0)}, data,
                                   {"bytes_per_row": w * comps * data.itemsize, "rows_per_image": h}, (w, h, 1))
    return tex


def read_texture(device, tex, dtype, comps, layer=0):
    w, h = tex.size[0], tex.size[1]
    itemsize = np.dtype(dtype).itemsize
    m = device.queue.read_texture({"texture": tex, "mip_level": 0, "origin": (0, 0, layer)},
                                  {"bytes_per_row": w * comps * itemsize, "rows_per_image": h}, (w, h, 1))
    return np.frombuffer(m, dtype=dtype).reshape(h, w, comps).copy()
