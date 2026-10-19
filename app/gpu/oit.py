"""Weighted blended OIT (translucent and x-rayed parts) on wgpu: the port of pass 5 of app/viewer/renderer.py.

    pas = OitPass(device, flip_y=True)         # once per device; flip_y must match the visibility pass (see __init__)
    pas.set_geometry(geom)                     # after the model's GpuGeometry is built (app/gpu/geometry.py), None to drop
    tg = pas.make_targets(w, h, samples)       # (re)create with the render size / sample count
    pas.encode(enc, draws, size=(w, h), samples=samples, depth_view=<vis_depth view>, targets=tg,
               items=<n_items x 3 rgba32float view>, spec=<2d-array rgba16float view>)
    # tg["accum"] (rgba16float) and tg["weight"] (r16float) are now the resolved textures, GL row order (row 0 = bottom),
    # the inputs of PostPasses.run_composite(..., oit_on=True).

``draws`` is a list of OitDraw in GL draw order (the order only matters at float16 rounding level: the blend is additive).
The shaders are wgsl/oit.wgsl + vertex.wgsl + shading.wgsl; see the header of oit.wgsl for what differs from OIT_FS.
Nothing here touches renderer.py: the renderer owns the depth texture and the draw list and calls encode().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import wgpu

from app.gpu.geometry import geom_prelude
from app.gpu.shading_uniforms import SIZE as SHADE_SIZE, pack_shading_uniforms

WGSL = Path(__file__).with_name("wgsl")
BU, TU, SS = wgpu.BufferUsage, wgpu.TextureUsage, wgpu.ShaderStage
ACCUM_FORMAT, WEIGHT_FORMAT = "rgba16float", "r16float"
RESOLVE_MARK = "// ---- resolve:"
DRAW_FLOATS = 60                                  # OitDraw record, 240 bytes (oit.wgsl)
FRAME_BYTES = 80


@dataclass
class OitDraw:
    """One indexed draw of a ghost / translucent part.

    part      index into model.parts (rows of GpuGeometry.vbase / stream_base / const_tail / page_of)
    first     first index in the page's index buffer (GpuGeometry.ranges[part][level][0], page local)
    count     index count
    item      the part's item (GLSL in_item)
    uniforms  the GL uniform dict exactly as renderer._draw_shaded leaves it on the p_oit program: everything of
              app/gpu/shading_uniforms.py plus u_model, u_nmat, u_viewproj, u_weight and the OIT extras u_ghost,
              u_ghost_alpha, u_alpha_mul, u_facing, u_facing_on (all draws of a frame must share u_viewproj)
    texture   albedo texture view (rgba8unorm-srgb, mips) when u_has_tex == 1, else None (a 1x1 white texture)
    """
    part: int
    first: int
    count: int
    item: int
    uniforms: dict
    texture: object = None


def _read(name):
    return (WGSL / name).read_text(encoding="utf-8")


def _align(n, a):
    return (n + a - 1) // a * a


GL_TO_WGPU_Z = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0.5, 0.5], [0, 0, 0, 1]], dtype=np.float64)   # renderer.py:39


def pack_frame(vp, size, flip_y=True, vp_wgpu=None):
    """vp: the GL view-projection (u_viewproj).  vp_wgpu: the renderer's own frame.vp (GL_TO_WGPU_Z @ VP, float64 product
    cast to float32 as renderer.py:557), taken as is when given so that the depths are those of the visibility pass."""
    f = np.zeros(20, np.float32)
    m = (GL_TO_WGPU_Z @ np.asarray(vp, np.float64)) if vp_wgpu is None else vp_wgpu
    f[0:16] = np.ascontiguousarray(np.asarray(m).T, dtype=np.float32).reshape(-1)
    f[16], f[17] = size
    f[18] = 1.0 if flip_y else 0.0
    return f.tobytes()


def pack_draws(draws, geom):
    """-> (n, 60) float32, the OitDraw records of oit.wgsl (ints stored bit-exact through a view)."""
    out = np.zeros((max(len(draws), 1), DRAW_FLOATS), np.float32)
    iv = out.view(np.int32)
    for k, d in enumerate(draws):
        u = d.uniforms
        r = out[k]
        r[0:16] = np.asarray(u["u_model"], np.float32).T.reshape(-1)
        nm = np.asarray(u["u_nmat"], np.float32)
        for j in range(3):
            r[16 + 4 * j:19 + 4 * j] = nm[:, j]
        r[28:41] = geom.const_tail[d.part]
        sb = geom.stream_base[d.part]
        iv[k, 44:48] = sb[0:4]
        iv[k, 48] = sb[4]
        iv[k, 49] = int(geom.vbase[d.part])
        iv[k, 50] = int(d.item)
        ab = getattr(geom, "anim_base", None)
        iv[k, 51] = -1 if ab is None else int(ab[d.part])
        r[52] = float(u.get("u_weight", 0.0))
        r[53] = 1.0 if int(u.get("u_ghost", 0)) else 0.0
        r[54] = float(u.get("u_ghost_alpha", 0.0))
        r[55] = float(u.get("u_alpha_mul", 1.0))
        if int(u.get("u_facing_on", 0)):
            r[56:59] = np.asarray(u["u_facing"], np.float32)
            r[59] = 1.0
    return out


class OitPass:
    def __init__(self, device, *, flip_y, depth_format="depth32float", aniso=8):
        """flip_y=True (default, the post_common.wgsl contract): rasterise bottom-up (clip y negated, front face cw), the
        rows are in GL order and the MSAA sample positions are GL's (measured: tools/perf/gpu/oit_parity.py), so the
        depth_view must be bottom-up too (the visibility pass must negate clip y as well).  flip_y=False: top-first like
        today's visibility pass (depth_view top-first), flipped by the resolve; at 4x/8x the silhouette pixels then differ
        from GL because the hardware sample pattern is mirrored."""
        self.device = device
        self.flip_y = bool(flip_y)
        self.depth_format = depth_format
        lim = getattr(device, "limits", {}) or {}
        self.ub_align = int(lim.get("min_uniform_buffer_offset_alignment",
                                    lim.get("min-uniform-buffer-offset-alignment", 256)))
        self.su_stride = _align(SHADE_SIZE, max(self.ub_align, 4))
        d = device
        V, F = SS.VERTEX, SS.FRAGMENT
        ent = lambda b, vis, **k: {"binding": b, "visibility": vis, **k}
        self.bgl0 = d.create_bind_group_layout(entries=[
            ent(0, V | F, buffer={"type": "uniform"}), ent(1, V | F, buffer={"type": "read-only-storage"}),
            ent(2, V, buffer={"type": "read-only-storage"})])
        tex = lambda b, st, vd="2d": ent(b, F, texture={"sample_type": st, "view_dimension": vd})
        smp = lambda b: ent(b, F, sampler={"type": "filtering"})
        self.bgl1 = d.create_bind_group_layout(entries=[
            ent(0, F, buffer={"type": "uniform", "has_dynamic_offset": True, "min_binding_size": SHADE_SIZE}),
            tex(1, "unfilterable-float"), tex(2, "float"), tex(3, "float", "2d-array"), tex(4, "float"),
            smp(5), smp(6), smp(7)])
        self.bgl2 = d.create_bind_group_layout(entries=[
            ent(0, V, buffer={"type": "read-only-storage"}), ent(1, V, buffer={"type": "uniform"})])
        self.layout = d.create_pipeline_layout(bind_group_layouts=[self.bgl0, self.bgl1, self.bgl2])
        self._cmp = 0                     # geometry stage (0 plain, 1 / 2 compressed)  -- compressed geometry: vertex_index = logical index position (geom.wgsl g_vertex), draws are non-indexed
        head, tail = self._code(False)
        self._resolve_src = RESOLVE_MARK + tail
        self.module = d.create_shader_module(code=head, label="oit")
        self._pipes, self._res_pipes, self._res_bgl = {}, {}, {}
        self.s_ao = d.create_sampler(address_mode_u="clamp-to-edge", address_mode_v="clamp-to-edge",
                                     mag_filter="linear", min_filter="linear")
        self.s_env = d.create_sampler(address_mode_u="repeat", address_mode_v="clamp-to-edge",
                                      mag_filter="linear", min_filter="linear")
        self.s_tex = d.create_sampler(address_mode_u="repeat", address_mode_v="repeat", mag_filter="linear",
                                      min_filter="linear", mipmap_filter="linear", max_anisotropy=int(aniso))
        # OIT never reads the AO image (OIT_FS has no occlusion): a 1x1 stand-in satisfies the shared layout
        self._ao = d.create_texture(size=(1, 1, 1), format="rgba16float", usage=TU.TEXTURE_BINDING).create_view()
        w = d.create_texture(size=(1, 1, 1), format="rgba8unorm-srgb", usage=TU.TEXTURE_BINDING | TU.COPY_DST)
        d.queue.write_texture({"texture": w}, np.full((1, 1, 4), 255, np.uint8),
                              {"offset": 0, "bytes_per_row": 4, "rows_per_image": 1}, (1, 1, 1))
        self._white = w.create_view()
        self._dummy = d.create_buffer(size=16, usage=BU.STORAGE)
        self._frame_ub = d.create_buffer(size=FRAME_BYTES, usage=BU.UNIFORM | BU.COPY_DST, label="oit.frame")
        self._draw_buf = self._su_buf = None
        self._draw_cap = self._su_cap = 0
        self._page_bg = []
        self._bg0 = None
        self._bg0_anim = None
        self._bg1 = {}
        self.geom = None
        self.last_draws = 0
        self._kept = None                 # what encode_parts keeps between frames
        self._frame_on = None             # the bytes in the frame uniform buffer

    # ------------------------------------------------------------------ resources
    @staticmethod
    def _code(cmp):
        code = (_read("vertex.wgsl") + _read("shading.wgsl") + geom_prelude(1, 2, 0, uniform_binding=1, compressed=cmp) + "\n"
                + _read("geom.wgsl") + _read("oit.wgsl"))
        return code.split(RESOLVE_MARK)

    def set_geometry(self, geom):
        """Bind groups of the geometry pages (group 2). Call again when the model changes; None releases them."""
        self.geom = geom
        self._kept = None
        if geom is not None and int(geom.stage) != self._cmp:      # the vertex module is built for one of the two layouts
            self._cmp = int(geom.stage)
            self.module = self.device.create_shader_module(code=self._code(self._cmp)[0], label="oit")
            self._pipes.clear()
        for ub in getattr(self, "_page_ub", []):
            ub.destroy()
        self._page_ub = []
        self._page_bg = []
        if geom is None:
            return
        self._page_ub = []
        for page in geom.pages:
            ub = self.device.create_buffer_with_data(data=page.offsets_words(), usage=BU.UNIFORM, label=f"oit.page{page.index}")
            self._page_ub.append(ub)
            ents = [{"binding": 0, "resource": {"buffer": page.buffer, "offset": 0, "size": page.buffer.size}},
                    {"binding": 1, "resource": {"buffer": ub, "offset": 0, "size": ub.size}}]
            self._page_bg.append(self.device.create_bind_group(layout=self.bgl2, entries=ents))

    def make_targets(self, w, h, samples):
        """The textures encode() needs (multisampled accum / weight, the resolved single-sample ones), their views and the
        resolve bind group, all created once here: recreate them (and drop the old ones) when size or samples change."""
        d = self.device
        ra = TU.RENDER_ATTACHMENT | TU.TEXTURE_BINDING
        t = {
            "acc_ms": d.create_texture(size=(w, h, 1), format=ACCUM_FORMAT, sample_count=samples, usage=ra,
                                       label="oit.acc_ms"),
            "wgt_ms": d.create_texture(size=(w, h, 1), format=WEIGHT_FORMAT, sample_count=samples, usage=ra,
                                       label="oit.wgt_ms"),
            "accum": d.create_texture(size=(w, h, 1), format=ACCUM_FORMAT, usage=ra | TU.COPY_SRC, label="oit.accum"),
            "weight": d.create_texture(size=(w, h, 1), format=WEIGHT_FORMAT, usage=ra | TU.COPY_SRC,
                                       label="oit.weight"),
        }
        t["samples"] = samples
        for k in ("acc_ms", "wgt_ms", "accum", "weight"):
            t[k + "_v"] = t[k].create_view()
        _pipe, bgl = self._resolve_pipeline(samples)
        t["res_bg"] = d.create_bind_group(layout=bgl, entries=[
            {"binding": 0, "resource": t["acc_ms_v"]}, {"binding": 1, "resource": t["wgt_ms_v"]}])
        return t

    @staticmethod
    def destroy_targets(t):
        for k in ("acc_ms", "wgt_ms", "accum", "weight"):
            t[k].destroy()

    def _grow(self, name, need, usage):
        cap = getattr(self, f"_{name[:-4]}_cap")
        if need > cap:
            cap = max(need, cap * 2, 4096)
            old = getattr(self, f"_{name}")
            if old is not None:
                old.destroy()
            setattr(self, f"_{name}", self.device.create_buffer(size=cap, usage=usage, label=f"oit.{name}"))
            setattr(self, f"_{name[:-4]}_cap", cap)
            self._bg0 = None
            self._bg1.clear()

    # ------------------------------------------------------------------ pipelines
    def pipeline(self, samples):
        key = (samples, self.depth_format)
        if key not in self._pipes:
            one = {"src_factor": "one", "dst_factor": "one", "operation": "add"}
            alpha = {"src_factor": "zero", "dst_factor": "one-minus-src-alpha", "operation": "add"}
            blend = {"color": one, "alpha": alpha}          # renderer.py:833 blend_func (ONE, ONE, ZERO, ONE_MINUS_SRC_ALPHA)
            self._pipes[key] = self.device.create_render_pipeline(
                layout=self.layout,
                vertex={"module": self.module, "entry_point": "vs_oit", "buffers": []},
                primitive={"topology": "triangle-list", "cull_mode": "none", "front_face": "cw" if self.flip_y else "ccw"},
                depth_stencil={"format": self.depth_format, "depth_write_enabled": False, "depth_compare": "less"},
                multisample={"count": samples},
                fragment={"module": self.module, "entry_point": "fs_oit", "targets": [
                    {"format": ACCUM_FORMAT, "blend": blend}, {"format": WEIGHT_FORMAT, "blend": blend}]},
                label=f"oit x{samples}")
        return self._pipes[key]

    def _resolve_pipeline(self, samples):
        if samples not in self._res_pipes:
            d = self.device
            src = self._resolve_src.replace("MS_TEX", "texture_multisampled_2d<f32>" if samples > 1 else "texture_2d<f32>")
            src = src.replace("FLIP_ROWS", "0" if self.flip_y else "1").replace("SAMPLE_COUNT", str(samples)).replace("SAMPLE_ARG", "k" if samples > 1 else "0")
            mod = d.create_shader_module(code=src, label=f"oit resolve x{samples}")
            ent = lambda b: {"binding": b, "visibility": SS.FRAGMENT,
                             "texture": {"sample_type": "unfilterable-float", "view_dimension": "2d",
                                         "multisampled": samples > 1}}
            bgl = d.create_bind_group_layout(entries=[ent(0), ent(1)])
            self._res_bgl[samples] = bgl
            self._res_pipes[samples] = d.create_render_pipeline(
                layout=d.create_pipeline_layout(bind_group_layouts=[bgl]),
                vertex={"module": mod, "entry_point": "vs_fsq"},
                primitive={"topology": "triangle-list", "cull_mode": "none"},
                fragment={"module": mod, "entry_point": "oit_resolve",
                          "targets": [{"format": ACCUM_FORMAT}, {"format": WEIGHT_FORMAT}]},
                label=f"oit resolve x{samples}")
        return self._res_pipes[samples], self._res_bgl[samples]

    # ------------------------------------------------------------------ frame
    def _group1(self, items, spec, tex):
        """Bind group 1 for (items view, spec view, albedo view); the cache keeps the resources alive and checks them by identity."""
        key = (id(items), id(spec), id(tex))
        hit = self._bg1.get(key)
        if hit is not None and hit[0] is items and hit[1] is spec and hit[2] is tex:
            return hit[3]
        if len(self._bg1) > 64:
            self._bg1.clear()
        bg = self.device.create_bind_group(layout=self.bgl1, entries=[
            {"binding": 0, "resource": {"buffer": self._su_buf, "offset": 0, "size": SHADE_SIZE}},
            {"binding": 1, "resource": items}, {"binding": 2, "resource": self._ao},
            {"binding": 3, "resource": spec}, {"binding": 4, "resource": tex if tex is not None else self._white},
            {"binding": 5, "resource": self.s_ao}, {"binding": 6, "resource": self.s_env},
            {"binding": 7, "resource": self.s_tex}])
        self._bg1[key] = (items, spec, tex, bg)
        return bg

    def encode(self, enc, draws, *, size, samples, depth_view, targets, items, spec, resolve=True, vp_wgpu=None, anim_tab=None):
        """Record the OIT pass (and the resolve) into the command encoder ``enc``. ``draws`` must not be empty (GL skips
        the pass, and the composite's oit_on is then 0). ``depth_view``: the multisampled depth of the opaque pass
        (same size and sample count as the colour targets), read only.  Rows of the multisampled targets are top-first
        like that depth; the resolved ``targets['accum'/'weight']`` are in GL row order."""
        if not draws:
            raise ValueError("OitPass.encode: no draws")
        if self.geom is None:
            raise RuntimeError("OitPass.set_geometry has not been called")
        d, q = self.device, self.device.queue
        n = len(draws)
        rec = pack_draws(draws, self.geom)
        self._grow("draw_buf", rec.nbytes, BU.STORAGE | BU.COPY_DST)
        self._grow("su_buf", n * self.su_stride, BU.UNIFORM | BU.COPY_DST)
        su = np.zeros(n * self.su_stride, np.uint8)
        for k, dr in enumerate(draws):
            b = pack_shading_uniforms(dr.uniforms)
            su[k * self.su_stride:k * self.su_stride + len(b)] = np.frombuffer(b, np.uint8)
        q.write_buffer(self._su_buf, 0, su)
        q.write_buffer(self._draw_buf, 0, rec)
        if self._kept is not None:            # encode_parts' records and blocks are no longer what the buffers hold
            self._kept.rows_on = self._kept.su_on = None
        self._frame_on = pack_frame(draws[0].uniforms["u_viewproj"], size, self.flip_y, vp_wgpu)
        q.write_buffer(self._frame_ub, 0, self._frame_on)
        self._group0(anim_tab)
        if targets["samples"] != samples:
            raise ValueError("targets were made for another sample count")
        rp = enc.begin_render_pass(
            color_attachments=[
                {"view": targets["acc_ms_v"], "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 1)},
                {"view": targets["wgt_ms_v"], "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 1)}],
            depth_stencil_attachment={"view": depth_view.create_view() if hasattr(depth_view, "create_view") else depth_view,
                                      "depth_read_only": True})
        rp.set_pipeline(self.pipeline(samples))
        rp.set_bind_group(0, self._bg0)
        page = -1
        for k, dr in enumerate(draws):
            pg = int(self.geom.page_of[dr.part])
            if pg != page:
                rp.set_bind_group(2, self._page_bg[pg])
                if not self._cmp:
                    rp.set_index_buffer(self.geom.pages[pg].buffer, "uint32", self.geom.pages[pg].index_byte_offset,
                                        self.geom.pages[pg].index_bytes)
                page = pg
            rp.set_bind_group(1, self._group1(items, spec, dr.texture), [k * self.su_stride])
            if self._cmp:
                rp.draw(dr.count, 1, dr.first, k)
            else:
                rp.draw_indexed(dr.count, 1, dr.first, 0, k)
        rp.end()
        self.last_draws = n
        if resolve:
            self._resolve(enc, samples, targets)

    def _group0(self, anim_tab):
        """Bind group 0 (frame uniform, draw records, animation table), made again when a buffer of it is another one.
        anim_tab: a buffer, or (buffer, byte offset, byte size) of a section of the renderer's table buffer."""
        anim = anim_tab if anim_tab is not None else self._dummy
        a_buf, a_off, a_size = anim if isinstance(anim, tuple) else (anim, 0, anim.size)
        if (self._bg0 is None or self._bg0_anim is None or self._bg0_anim[0] is not a_buf or self._bg0_anim[1:] != (a_off, a_size)):
            self._bg0_anim = (a_buf, a_off, a_size)
            self._bg0 = self.device.create_bind_group(layout=self.bgl0, entries=[
                {"binding": 2, "resource": {"buffer": a_buf, "offset": a_off, "size": a_size}},
                {"binding": 0, "resource": {"buffer": self._frame_ub, "offset": 0, "size": FRAME_BYTES}},
                {"binding": 1, "resource": {"buffer": self._draw_buf, "offset": 0, "size": self._draw_cap}}])
        return self._bg0

    def _resolve(self, enc, samples, targets, timestamps=None):
        pipe, _bgl = self._resolve_pipeline(samples)
        rp = enc.begin_render_pass(color_attachments=[
            {"view": targets["accum_v"], "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 1)},
            {"view": targets["weight_v"], "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 1)}],
            **({"timestamp_writes": timestamps} if timestamps else {}))
        rp.set_pipeline(pipe)
        rp.set_bind_group(0, targets["res_bg"])
        rp.draw(3)
        rp.end()

    # ------------------------------------------------------------------ frame, from per-part arrays
    def forget_parts(self):
        """Drop everything encode_parts keeps between frames (slots, records, ShadeU blocks, bundles)."""
        self._kept = None

    def _kept_state(self, n_parts, looks):
        k = self._kept
        if k is None or k.looks is not looks or len(k.slot_of) != n_parts or k.geom is not self.geom:
            k = self._kept = SimpleNamespace(
                looks=looks, geom=self.geom, slot_of=np.full(n_parts, -1, dtype=np.int64), n_slots=0,
                rows=np.zeros((0, DRAW_FLOATS), np.float32), blocks=np.zeros((0, self.su_stride), np.uint8),
                slot_look=np.zeros(0, dtype=np.int64), look_mat=np.zeros((0, SHADE_SIZE), np.uint8), glob=None,
                rows_on=None, su_on=None, epoch=None, bundles={}, bg1={}, codes=None, run=[], builds=0, uploads=[0, 0],
                part=None)
        return k

    def _slots(self, k, part):
        """The slot of every part of the list (a part keeps its slot while it stays in the kept state, so its record and its
        ShadeU block stay where they are when the list changes). Slots are handed out as parts first appear and all dropped
        when they outnumber the list four to one."""
        slot = k.slot_of[part]
        miss = slot < 0
        if miss.any():
            new = part[miss]
            if k.n_slots + len(new) > max(256, 4 * len(part)):
                k.slot_of[:] = -1
                k.n_slots = 0
                k.rows_on = k.su_on = k.epoch = None
                k.slot_look[:] = -1
                new = part
            k.slot_of[new] = np.arange(k.n_slots, k.n_slots + len(new))
            k.n_slots += len(new)
            cap = len(k.rows)
            if k.n_slots > cap:
                cap = max(k.n_slots, cap * 2, 64)
                for name, fill in (("rows", 0), ("blocks", 0), ("slot_look", -1)):
                    old = getattr(k, name)
                    grown = np.full((cap,) + old.shape[1:], fill, dtype=old.dtype)
                    grown[:len(old)] = old
                    setattr(k, name, grown)
            slot = k.slot_of[part]
        return slot

    def _bundle(self, k, pipe, samples, items, spec, part, first, count, tex, slot, texture):
        """One draw as a render bundle: everything the pass sets for it, so a frame only names the bundles it runs."""
        bg1 = k.bg1.get(tex)
        if bg1 is None:
            view = self._white if tex < 0 else texture(tex)
            bg1 = k.bg1[tex] = self.device.create_bind_group(layout=self.bgl1, entries=[
                {"binding": 0, "resource": {"buffer": self._su_buf, "offset": 0, "size": SHADE_SIZE}},
                {"binding": 1, "resource": items}, {"binding": 2, "resource": self._ao},
                {"binding": 3, "resource": spec}, {"binding": 4, "resource": view},
                {"binding": 5, "resource": self.s_ao}, {"binding": 6, "resource": self.s_env},
                {"binding": 7, "resource": self.s_tex}])
        be = self.device.create_render_bundle_encoder(color_formats=[ACCUM_FORMAT, WEIGHT_FORMAT],
                                                      depth_stencil_format=self.depth_format, sample_count=samples,
                                                      depth_read_only=True, stencil_read_only=True)
        pg = int(self.geom.page_of[part])
        be.set_pipeline(pipe)
        be.set_bind_group(0, self._bg0)
        be.set_bind_group(2, self._page_bg[pg])
        be.set_bind_group(1, bg1, [slot * self.su_stride])
        if self._cmp:
            be.draw(count, 1, first, slot)
        else:
            page = self.geom.pages[pg]
            be.set_index_buffer(page.buffer, "uint32", page.index_byte_offset, page.index_bytes)
            be.draw_indexed(count, 1, first, 0, slot)
        k.builds += 1
        return be.finish()

    def encode_parts(self, enc, *, part, level, first, count, rows, look, tex, looks, glob, glob_runs, texture, size, samples,
                     depth_view, targets, items, spec, vp_wgpu, anim_tab=None, resolve=True, timestamps=None):
        """encode() for the renderer, from arrays over the translucent draws in draw order, with nothing walked in Python on
        a frame that changes nothing:

        part, level, first, count   part index, drawn level, first index and index count of each draw (a part at most once)
        rows      (n, DRAW_FLOATS) float32 OitDraw records (drawtable.oit_rows)
        look      (n,) index into ``looks`` of each draw's ShadeU look record; tex (n,) its albedo image index, -1 none
        looks     the renderer's list of look records (ShadeU bytes with the per-look fields set): it only grows, a new
                  list means a new model
        glob      the frame-wide ShadeU bytes (lights, camera, cut planes); glob_runs the byte ranges those fields cover
        texture   image index -> albedo view

        What is kept, and what it is checked against every frame: a part's record (the bytes of ``rows``, compared), its
        ShadeU block (the look index it was made from; ``glob``, compared), the frame uniform (compared), and one render
        bundle per (part, level, texture), valid while the pipeline, the three bind groups' resources and the slots are
        the same objects. The draws run in list order, as encode() runs them."""
        n = len(part)
        if not n:
            raise ValueError("OitPass.encode_parts: no draws")
        if self.geom is None:
            raise RuntimeError("OitPass.set_geometry has not been called")
        if targets["samples"] != samples:
            raise ValueError("targets were made for another sample count")
        d, q = self.device, self.device.queue
        k = self._kept_state(len(self.geom.page_of), looks)
        slot = self._slots(k, part)
        k.part = part                        # the list of the last frame (read by tests)
        # ---- the records
        mine = k.rows[slot]
        if k.rows_on is None or not np.array_equal(mine.view(np.uint32), rows.view(np.uint32)):
            k.rows[slot] = rows
            k.rows_on = None
        self._grow("draw_buf", k.n_slots * DRAW_FLOATS * 4, BU.STORAGE | BU.COPY_DST)
        self._grow("su_buf", k.n_slots * self.su_stride, BU.UNIFORM | BU.COPY_DST)
        if k.rows_on is not self._draw_buf:
            q.write_buffer(self._draw_buf, 0, np.ascontiguousarray(k.rows[:k.n_slots]))
            k.rows_on = self._draw_buf
            k.uploads[0] += 1
        # ---- the ShadeU blocks: the look record of each slot, then the frame-wide fields over all of them
        g = np.frombuffer(glob, dtype=np.uint8)
        stale = k.slot_look[slot] != look
        if stale.any():
            if len(k.look_mat) < len(looks):
                k.look_mat = np.frombuffer(b"".join(looks), dtype=np.uint8).reshape(len(looks), SHADE_SIZE)
            sl = slot[stale]
            blk = k.look_mat[look[stale]].copy()
            for a, b in glob_runs:
                blk[:, a:b] = g[a:b]
            k.blocks[sl, :SHADE_SIZE] = blk
            k.slot_look[sl] = look[stale]
            k.su_on = None
        if k.glob != glob:
            for a, b in glob_runs:
                k.blocks[:k.n_slots, a:b] = g[a:b]
            k.glob = glob
            k.su_on = None
        if k.su_on is not self._su_buf:
            q.write_buffer(self._su_buf, 0, np.ascontiguousarray(k.blocks[:k.n_slots]))
            k.su_on = self._su_buf
            k.uploads[1] += 1
        fb = pack_frame(None, size, self.flip_y, vp_wgpu)
        if self._frame_on != fb:
            q.write_buffer(self._frame_ub, 0, fb)
            self._frame_on = fb
        self._group0(anim_tab)
        # ---- the bundles
        pipe = self.pipeline(samples)
        epoch = (pipe, self._bg0, items, spec, self._su_buf, self._draw_buf)
        if k.epoch is None or any(a is not b for a, b in zip(k.epoch, epoch)):
            k.epoch, k.bundles, k.bg1, k.codes = epoch, {}, {}, None
        codes = (part * 64 + level) * (1 << 20) + (tex + 1)
        if k.codes is None or len(codes) != len(k.codes) or not np.array_equal(codes, k.codes):
            if len(k.bundles) > 8 * k.n_slots + 4096:
                k.bundles = {}
            get = k.bundles.get
            run = [get(c) for c in codes.tolist()]
            if None in run:
                todo = [i for i, b in enumerate(run) if b is None]
                cl = codes[todo].tolist()
                args = zip(todo, cl, part[todo].tolist(), first[todo].tolist(), count[todo].tolist(), tex[todo].tolist(),
                           slot[todo].tolist())
                for i, c, pi, f0, cnt, tx, sl in args:
                    run[i] = k.bundles[c] = self._bundle(k, pipe, samples, items, spec, pi, f0, cnt, tx, sl, texture)
            k.codes, k.run = codes, run
        tw = {}
        if timestamps:                       # (query set, begin index, end index) around the pass and its resolve
            tw = {"timestamp_writes": {"query_set": timestamps[0], "beginning_of_pass_write_index": timestamps[1],
                                       **({} if resolve else {"end_of_pass_write_index": timestamps[2]})}}
        rp = enc.begin_render_pass(
            color_attachments=[
                {"view": targets["acc_ms_v"], "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 1)},
                {"view": targets["wgt_ms_v"], "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 1)}],
            depth_stencil_attachment={"view": depth_view, "depth_read_only": True}, **tw)
        rp.execute_bundles(k.run)
        rp.end()
        self.last_draws = n
        if resolve:
            self._resolve(enc, samples, targets,
                          {"query_set": timestamps[0], "end_of_pass_write_index": timestamps[2]} if timestamps else None)

    def clear_resolved(self, enc, targets):
        """Clear the resolved textures (a frame without ghost parts does not need it: the composite gets oit_on = 0)."""
        rp = enc.begin_render_pass(color_attachments=[
            {"view": targets["accum_v"], "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 1)},
            {"view": targets["weight_v"], "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 1)}])
        rp.end()
