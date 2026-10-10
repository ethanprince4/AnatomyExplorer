"""Split shaded resolve: the divergence-free version of the shade pass (resolve.wgsl fs_shade).

fs_shade shades every distinct triangle of a pixel's MSAA samples in a loop, so a SIMD wave runs as many shade_tri iterations as its
worst pixel has distinct triangles. On dense meshes most pixels have one and the edge pixels 2..4, so most lanes of a wave idle through
the extra iterations. The split keeps the first triangle of every pixel in the fragment pass and shades the extras (one
(pixel, triangle) pair per thread) in a compute pass:

    clear counter
    compute pass:  cs_x_cls   per pixel: later distinct triangles of this pass -> entries (entry texture), xidx[pixel] = first entry
                   cs_x_args  dispatch size, sentinel entries up to the workgroup size
                   cs_x_shade one entry per thread: q16(shade_tri(...)) -> res texture
    render pass:   fs_shade_x same loop as fs_shade; the extras are res[xidx + j] * count, in sample order

Every (pixel, triangle) pair gets the same inputs, shade_tri, q16 and sample weights as before and the sums keep their order, so the
picture is the same up to the codegen of shade_main_ex in a compute versus a fragment shader. No float atomics and no storage
buffer beyond the table, the decode table and the pages the shade pass binds anyway (the entries live in textures), so it fits the
apple7 limits. Entries beyond the capacity (a pixel that does not fit entirely) are shaded inline by fs_shade_x.

ANATOMY_SHADE_SPLIT = 0 / off, 1 / on, auto (default: on for every GPU; the 3080 measured neutral-or-better, the UHD 770 gains 15-30% of shade time).
`ShadeSplit.mode` can be changed at run time (read every frame).
"""
from __future__ import annotations

import os

import numpy as np
import wgpu


BU, TU, SS = wgpu.BufferUsage, wgpu.TextureUsage, wgpu.ShaderStage
XW = 4096                                      # width of the entry / result textures (X_W in resolve.wgsl)
CAP_MAX_ROWS = 1024                            # entries <= 4096 x 1024: 64 per workgroup -> at most 65536 workgroups
CAP_PIXEL_FRACTION = 2                         # capacity = pixels / 2 entries (dense views reach about a quarter)
B_CNT, B_ARGS, B_ENT_W, B_XIDX_W, B_ENT_R, B_RES_W, B_XIDX_R, B_RES_R, B_CNT_W, B_CNT_R = 20, 21, 22, 23, 24, 25, 26, 27, 28, 29
REGIONS = 16                                   # X_R in resolve.wgsl: independent entry counters (one global atomic counter serialises)


def _mode(v):
    v = str(v).strip().lower()
    return {"0": "off", "off": "off", "no": "off", "1": "on", "on": "on", "yes": "on"}.get(v, "auto")


def _st(binding, vis, fmt):                    # write-only storage texture
    return {"binding": binding, "visibility": vis,
            "storage_texture": {"access": "write-only", "format": fmt, "view_dimension": "2d"}}


class ShadeSplit:
    def __init__(self, r):
        self.r = r
        self.mode = _mode(os.environ.get("ANATOMY_SHADE_SPLIT", "auto"))
        self._bgl = {}
        self._res = None
        self._bgs = {}
        self.skip = set()                       # diagnostics: stages left out (cls / shade)
        self.items = 0                          # items of the last frame that used the split (diagnostics)

    # ------------------------------------------------------------------ policy
    def enabled(self, samples, n_pages):
        r = self.r
        if samples < 2 or self.mode == "off":
            return False
        n_stor = int(r.limits.get("max_storage_buffers_per_shader_stage", r.limits.get("max-storage-buffers-per-shader-stage", 8)))
        if n_pages + 2 > n_stor:                # the compute shade binds the table, the decode table and the pages
            return False
        return True                             # on and auto: measured neutral-or-better on the RTX 3080, 15-30% on the UHD 770

    # ------------------------------------------------------------------ layouts
    def _bgls(self, samples):
        if samples in self._bgl:
            return self._bgl[samples]
        from .renderer import DEC_CRO, DEC_LAY, _entry
        d = self.r.device
        C, F = SS.COMPUTE, SS.FRAGMENT
        ms = samples > 1

        def base(vis):
            return [_entry(0, "tu", vis, ms=ms), _entry(2, "tl", vis), _entry(6, "td", vis, ms=ms), _entry(7, "tf", vis),
                    _entry(DEC_CRO, "r", vis), _entry(DEC_LAY, "u", vis)]
        mk = lambda ents: d.create_bind_group_layout(entries=ents)       # noqa: E731
        out = {
            "cls": mk(base(C) + [_entry(B_CNT, "w", C), _st(B_ENT_W, C, "rg32uint"), _st(B_XIDX_W, C, "r32uint")]),
            "args": mk([_entry(B_CNT, "w", C), _entry(B_ARGS, "w", C), _st(B_ENT_W, C, "rg32uint"), _st(B_CNT_W, C, "r32uint")]),
            "shade": mk(base(C) + [_entry(B_ENT_R, "tu", C), _st(B_RES_W, C, "rgba16float"), _entry(B_CNT_R, "tu", C)]),
            "frag": mk(base(F) + [_entry(B_XIDX_R, "tu", F), _entry(B_RES_R, "tf", F)]),
        }
        self._bgl[samples] = out
        return out

    # ------------------------------------------------------------------ resources
    def _ensure(self, w, h):
        if self._res is not None and self._res["size"] == (w, h):
            return self._res
        if self._res is not None:
            for k in ("ent", "res", "xidx", "cnt_t"):
                self._res[k].destroy()
        d = self.r.device
        rows = -(-(w * h // CAP_PIXEL_FRACTION) // XW)
        rows = int(min(CAP_MAX_ROWS, max(REGIONS, -(-rows // REGIONS) * REGIONS)))      # a multiple of the region count
        ST = TU.STORAGE_BINDING | TU.TEXTURE_BINDING | TU.COPY_SRC
        ent = d.create_texture(size=(XW, rows, 1), format="rg32uint", usage=ST, label="split_entries")
        res = d.create_texture(size=(XW, rows, 1), format="rgba16float", usage=ST, label="split_results")
        xidx = d.create_texture(size=(w, h, 1), format="r32uint", usage=ST, label="split_index")
        cnt_t = d.create_texture(size=(REGIONS, 1, 1), format="r32uint", usage=ST, label="split_counts")
        self._res = {"size": (w, h), "ent": ent, "res": res, "xidx": xidx, "ent_v": ent.create_view(), "res_v": res.create_view(),
                     "xidx_v": xidx.create_view(), "rows": rows, "cnt_t": cnt_t, "cnt_v": cnt_t.create_view(),
                     "cnt": d.create_buffer(size=4 * REGIONS, usage=BU.STORAGE | BU.COPY_DST | BU.COPY_SRC, label="split_count"),
                     "args": d.create_buffer(size=16, usage=BU.STORAGE | BU.INDIRECT, label="split_args")}
        self._bgs = {}
        return self._res

    def _group2(self, which, samples, res):
        r = self.r
        cap = r._cap_col_v if r._capon else r._cap_none
        cro, lay = r._decode_resources()
        key = (which, samples, id(r.v["vis_id"]), id(r.v["bg"]), id(r.v["vis_depth"]), id(cap), id(cro["buffer"]), id(lay["buffer"]))
        if key not in self._bgs:
            base = [{"binding": 0, "resource": r.v["vis_id"]}, {"binding": 2, "resource": r.v["bg"]},
                    {"binding": 6, "resource": r.v["vis_depth"]}, {"binding": 7, "resource": cap},
                    {"binding": 8, "resource": cro}, {"binding": 9, "resource": lay}]
            full = lambda b: {"buffer": b, "offset": 0, "size": b.size}               # noqa: E731
            ex = {"cls": base + [{"binding": B_CNT, "resource": full(res["cnt"])}, {"binding": B_ENT_W, "resource": res["ent_v"]},
                                 {"binding": B_XIDX_W, "resource": res["xidx_v"]}],
                  "args": [{"binding": B_CNT, "resource": full(res["cnt"])}, {"binding": B_ARGS, "resource": full(res["args"])},
                           {"binding": B_ENT_W, "resource": res["ent_v"]}, {"binding": B_CNT_W, "resource": res["cnt_v"]}],
                  "shade": base + [{"binding": B_ENT_R, "resource": res["ent_v"]}, {"binding": B_RES_W, "resource": res["res_v"]},
                                 {"binding": B_CNT_R, "resource": res["cnt_v"]}],
                  "frag": base + [{"binding": B_XIDX_R, "resource": res["xidx_v"]}, {"binding": B_RES_R, "resource": res["res_v"]}],
                  }[which]
            self._bgs[key] = r.device.create_bind_group(layout=self._bgls(samples)[which], entries=ex)
        return self._bgs[key]

    # ------------------------------------------------------------------ pipelines
    def _pipes(self, samples, n_pages, page0, feat):
        r = self.r
        key = ("split", samples, n_pages, page0, feat)
        if key not in r._pipes:
            from .renderer import ADD, _FEAT_NAMES, _MORPH_NAMES
            m = r._resolve_module(samples, n_pages, page0)
            b = self._bgls(samples)
            consts = {n: float(bool(feat & bit)) for n, bit in _FEAT_NAMES + _MORPH_NAMES}
            lay = r._layout
            pages = r._bgl_pages(n_pages)
            dev = r.device
            r._pipes[key] = {
                "cls": dev.create_compute_pipeline(layout=lay(r.bgl0_res, r.bgl_shade, b["cls"]),
                                                   compute={"module": m, "entry_point": "cs_x_cls"}, label="split_cls"),
                "args": dev.create_compute_pipeline(layout=lay(r.bgl_empty, r.bgl_empty, b["args"]),
                                                    compute={"module": m, "entry_point": "cs_x_args"}, label="split_args"),
                "shade": dev.create_compute_pipeline(layout=lay(r.bgl0_res, r.bgl_shade, b["shade"], pages),
                                                     compute={"module": m, "entry_point": "cs_x_shade", "constants": consts},
                                                     label=f"split_shade{n_pages}@{page0}"),
                "frag": dev.create_render_pipeline(
                    layout=lay(r.bgl0_res, r.bgl_shade, b["frag"], pages),
                    vertex={"module": m, "entry_point": "vs_fsq"},
                    fragment={"module": m, "entry_point": "fs_shade_x", "constants": consts,
                              "targets": [{"format": "rgba16float", "blend": {"color": ADD, "alpha": ADD}}]},
                    primitive={"topology": "triangle-list", "cull_mode": "none"}, label=f"shade_x{n_pages}@{page0}"),
            }
        return r._pipes[key]

    # ------------------------------------------------------------------ encoding
    def prepare(self, enc, samples, n_pages, page0, feat, bg1, pages_bg, size, ts_begin=None):
        """Encode the compute passes of one shade pass (group of pages x texture slot); returns (render pipeline, group-2 bind
        group) for the fragment pass that follows. `ts_begin` = (query set, index): timestamp at the start of the compute pass."""
        r = self.r
        w, h = size
        res = self._ensure(w, h)
        p = self._pipes(samples, n_pages, page0, feat)
        enc.clear_buffer(res["cnt"], 0, 4 * REGIONS)
        kw = {}
        if ts_begin is not None:
            kw["timestamp_writes"] = {"query_set": ts_begin[0], "beginning_of_pass_write_index": ts_begin[1]}
        cp = enc.begin_compute_pass(**kw)
        cp.set_pipeline(p["cls"])
        cp.set_bind_group(0, r._bg0_res)
        cp.set_bind_group(1, bg1)
        cp.set_bind_group(2, self._group2("cls", samples, res))
        if "cls" not in self.skip:
            cp.dispatch_workgroups((w + 7) // 8, (h + 7) // 8, 1)
        cp.set_pipeline(p["args"])
        cp.set_bind_group(0, r.bg_empty)
        cp.set_bind_group(1, r.bg_empty)
        cp.set_bind_group(2, self._group2("args", samples, res))
        cp.dispatch_workgroups(1, 1, 1)
        cp.set_pipeline(p["shade"])
        cp.set_bind_group(0, r._bg0_res)
        cp.set_bind_group(1, bg1)
        cp.set_bind_group(2, self._group2("shade", samples, res))
        cp.set_bind_group(3, pages_bg)
        if "shade" not in self.skip:
            cp.dispatch_workgroups_indirect(res["args"], 0)
        cp.end()
        self.items += 1
        return p["frag"], self._group2("frag", samples, res)
