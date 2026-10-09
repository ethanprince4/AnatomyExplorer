"""Numerical parity of the wgpu post passes (app/gpu/post.py + app/gpu/wgsl/post_*.wgsl) against the GLSL originals
in app/viewer/shaders.py, run through moderngl on a standalone GL context.

    python tools/perf/gpu/post_parity.py [--adapter "RTX 3080"] [--quick] [--out log.json]

Inputs are built once per (size, scene) in GL row order (row 0 = bottom) from a fixed seed and uploaded unflipped
to both APIs. Every pass is compared in isolation (identical input textures) and the ssao -> blur chain is compared
end to end. A deliberately flipped comparison is the negative control showing the metric is orientation sensitive.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import wgpu  # noqa: E402

from app.gpu import post as P  # noqa: E402

# --------------------------------------------------------------------------------------------- adapters


def pick_adapter(name: str | None):
    """Adapter by (case-insensitive) device-name substring; Vulkan preferred, then D3D12."""
    adapters = wgpu.gpu.enumerate_adapters_sync()
    pref = {"Vulkan": 0, "D3D12": 1}
    cand = [a for a in adapters if name is None or name.lower() in a.info["device"].lower()]
    cand = [a for a in cand if a.info["adapter_type"] != "CPU"]
    if not cand:
        return None
    cand.sort(key=lambda a: pref.get(a.info["backend_type"], 9))
    return cand[0]


def make_device(adapter):
    feats = [f for f in ("float32-filterable",) if f in adapter.features]
    limits = {k: adapter.limits[k] for k in ("max_texture_dimension_2d", "max_texture_array_layers") if k in adapter.limits}
    return adapter.request_device_sync(required_features=feats)


# --------------------------------------------------------------------------------------------- scene


def ray_scene(w, h, ortho, seed):
    """nd (h,w,4) f32, idt (h,w,2) f32 and shading helpers; GL row order (row 0 = bottom). Returns dict."""
    rng = np.random.default_rng(seed)
    aspect = w / h
    if ortho:
        hy = 3.0
        tan = (hy * aspect, hy)
    else:
        ty = float(np.tan(np.radians(35.0) / 2))
        tan = (ty * aspect, ty)
    xs = (np.arange(w) + 0.5) / w * 2 - 1
    ys = (np.arange(h) + 0.5) / h * 2 - 1
    ndcx, ndcy = np.meshgrid(xs, ys)
    if ortho:
        O = np.stack([ndcx * tan[0], ndcy * tan[1], np.zeros_like(ndcx)], -1)
        D = np.broadcast_to(np.array([0, 0, -1.0]), O.shape).copy()
    else:
        O = np.zeros(ndcx.shape + (3,))
        D = np.stack([ndcx * tan[0], ndcy * tan[1], -np.ones_like(ndcx)], -1)
    best = np.full(ndcx.shape, np.inf)
    nrm = np.zeros(ndcx.shape + (3,))
    oid = np.zeros(ndcx.shape)
    flag = np.zeros(ndcx.shape)
    spheres = [((-1.2, 0.3, -5.0), 1.0, 1), ((1.1, -0.2, -4.0), 0.7, 2), ((0.1, 0.9, -7.0), 1.3, 3)]
    if ortho:
        spheres = [((-1.6, 0.2, -5.0), 1.1, 1), ((1.5, -0.3, -4.0), 0.8, 2), ((0.1, 1.4, -7.0), 1.3, 3)]
    for c, r, i in spheres:
        c = np.array(c)
        oc = O - c
        a = (D * D).sum(-1)
        b = (oc * D).sum(-1)
        cc = (oc * oc).sum(-1) - r * r
        disc = b * b - a * cc
        ok = disc > 0
        t = (-b - np.sqrt(np.where(ok, disc, 0))) / a
        hit = ok & (t > 0) & (t < best)
        P_ = O + t[..., None] * D
        n = (P_ - c) / r
        best = np.where(hit, t, best)
        nrm = np.where(hit[..., None], n, nrm)
        oid = np.where(hit, i, oid)
        flag = np.where(hit, 1.0 if i in (2, 3) else 0.0, flag)
    pn = np.array([0.08, 1.0, 0.04])
    pn /= np.linalg.norm(pn)
    k = float(pn @ np.array([0.0, -1.4, 0.0]))
    den = (D * pn).sum(-1)
    t = (k - (O * pn).sum(-1)) / np.where(np.abs(den) < 1e-9, 1e-9, den)
    hit = (t > 0) & (t < best) & (t < 16.0)
    P_ = O + t[..., None] * D
    best = np.where(hit, t, best)
    nrm = np.where(hit[..., None], pn, nrm)
    oid = np.where(hit, 4, oid)
    capband = (np.abs(P_[..., 0] - 0.5) < 0.6) & (P_[..., 2] < -2.5)
    flag = np.where(hit, np.where(capband, 2.0, 0.0), flag)
    wall = (D[..., 2] < 0) & (np.abs(D[..., 2]) > 1e-6)
    tw = (-12.0 - O[..., 2]) / np.where(wall, D[..., 2], -1.0)
    pw = O + tw[..., None] * D
    hit = wall & (tw > 0) & (tw < best) & (pw[..., 0] < 1.0)
    best = np.where(hit, tw, best)
    nrm = np.where(hit[..., None], np.array([0.0, 0.0, 1.0]), nrm)
    oid = np.where(hit, 5, oid)
    flag = np.where(hit, 0.0, flag)
    cover = np.isfinite(best)
    depth = np.where(cover, best, 0.0) * (1.0 + 1e-3 * rng.standard_normal(best.shape))
    depth = np.where(cover, depth, 0.0)
    nd = np.concatenate([np.where(cover[..., None], nrm, 0.0), depth[..., None]], -1).astype(np.float32)
    idt = np.stack([oid, flag], -1).astype(np.float32)
    # opaque shading (HDR), previous frame, ghost accumulation
    L = np.array([0.4, 0.7, 0.6])
    L /= np.linalg.norm(L)
    albedo = np.array([[0.05, 0.05, 0.06], [0.8, 0.3, 0.25], [0.3, 0.7, 0.35], [0.4, 0.4, 0.9],
                       [0.7, 0.7, 0.65], [0.5, 0.45, 0.4]])[oid.astype(int)]
    lam = np.clip((nrm * L).sum(-1), 0, None)[..., None]
    base = np.where(cover[..., None], albedo * (0.25 + 2.2 * lam), 0.08 + 0.25 * (ys[:, None, None] * 0.5 + 0.5))
    base = base + 0.05 * rng.standard_normal(base.shape)
    base[(cover) & (oid == 1)] *= 2.0
    opaque = np.clip(np.concatenate([base, np.ones(base.shape[:2] + (1,))], -1), 0, None).astype(np.float16)
    prev = np.roll(opaque.astype(np.float32), 7, axis=1) * 1.5
    prev[..., :3] += 6.0 * np.exp(-(((ndcx - 0.2) / 0.15) ** 2 + ((ndcy + 0.1) / 0.2) ** 2))[..., None]
    prev = prev.astype(np.float16)
    gx, gy = ndcx + 0.35, ndcy - 0.15
    rr = np.sqrt((gx / 0.45) ** 2 + (gy / 0.35) ** 2)
    mask = np.clip((1.0 - rr) * 8.0, 0, 1)
    weight = (mask * (0.2 + 1.4 * np.clip(1 - rr, 0, 1))).astype(np.float16)
    rgb = np.stack([0.9 * np.ones_like(rr), 0.5 + 0.4 * np.sin(6 * gx), 0.2 + 0.3 * np.cos(5 * gy)], -1)
    accum = np.concatenate([rgb * weight.astype(np.float32)[..., None],
                            (1.0 - 0.6 * mask * np.clip(1.2 - rr, 0, 1))[..., None]], -1).astype(np.float16)
    return dict(w=w, h=h, ortho=ortho, tan=tan, nd=nd, id=idt, opaque=opaque, prev=prev, accum=accum, weight=weight[..., None])


# --------------------------------------------------------------------------------------------- GL side


class GL:
    def __init__(self):
        import moderngl
        self.mgl = moderngl
        self.ctx = moderngl.create_standalone_context()
        from app.viewer import shaders
        self.sh = shaders
        self.info = self.ctx.info["GL_RENDERER"]
        self.progs = {}

    def prog(self, name, fs):
        if name not in self.progs:
            p = self.ctx.program(vertex_shader=self.sh.FSQ_VS, fragment_shader=fs)
            self.progs[name] = (p, self.ctx.vertex_array(p, []))
        return self.progs[name]

    def tex(self, arr, near=False):
        h, w, c = arr.shape
        dt = {"float32": "f4", "float16": "f2", "uint8": "f1"}[arr.dtype.name]
        t = self.ctx.texture((w, h), c, np.ascontiguousarray(arr).tobytes(), dtype=dt)
        t.repeat_x = t.repeat_y = False
        if near:
            t.filter = (self.mgl.NEAREST, self.mgl.NEAREST)
        return t

    def run(self, name, fs, w, h, comps, dtype, uniforms, textures):
        p, vao = self.prog(name, fs)
        dst = self.ctx.texture((w, h), comps, dtype=dtype)
        fbo = self.ctx.framebuffer([dst])
        fbo.use()
        self.ctx.viewport = (0, 0, w, h)
        self.ctx.disable(self.mgl.DEPTH_TEST | self.mgl.BLEND)
        for i, (n, t) in enumerate(textures):
            t.use(i)
            p[n].value = i
        for k, v in uniforms.items():
            p[k].value = v
        vao.render(self.mgl.TRIANGLES, vertices=3)
        npdt = {"f4": np.float32, "f2": np.float16, "f1": np.uint8}[dtype]
        raw = fbo.read(components=comps, dtype=dtype)
        out = np.frombuffer(raw, dtype=npdt).reshape(h, w, comps).copy()
        fbo.release()
        dst.release()
        return out


# --------------------------------------------------------------------------------------------- compare helpers


def stats(a, b, unit):
    d = np.abs(a.astype(np.float64) - b.astype(np.float64)) / unit
    pix = d.max(-1) if d.ndim == 3 else d
    return dict(max=float(d.max()), mean=float(d.mean()), p999=float(np.quantile(pix, 0.999)),
                pct_over1=float((pix > 1.0).mean() * 100.0), pct_any=float((pix > 0.0).mean() * 100.0))


def fmt(s):
    return f"max {s['max']:8.3f}  mean {s['mean']:8.5f}  p99.9 {s['p999']:7.3f}  >1u {s['pct_over1']:7.4f}%"


# --------------------------------------------------------------------------------------------- run


COMBOS = [
    dict(name="A persp 720 bounce dark oit sel+hover", size=(1280, 720), ortho=False, ao=True, strength=1.0,
         bounce=True, bg=("#20242b", "#12141a"), tonemap=True, exposure=0.0, oit=True, hover=1, sel=True,
         outline=(1.0, 0.86, 0.35), hover_outline=(0.75, 0.85, 1.0), radius=0.35),
    dict(name="B ortho 1080 nobounce light notonemap exp+0.7 nooit sel", size=(1920, 1080), ortho=True, ao=True,
         strength=1.5, bounce=False, bg=("#f4f5f8", "#d8dce4"), tonemap=False, exposure=0.7, oit=False, hover=0,
         sel=True, outline=(0.1, 0.2, 0.9), hover_outline=(0.75, 0.85, 1.0), radius=0.5),
    dict(name="C persp 720 str0.5 custom bg exp-0.5 hover only", size=(1280, 720), ortho=False, ao=True,
         strength=0.5, bounce=True, bg=("#1d9a8b", "#6b2d5c"), tonemap=True, exposure=-0.5, oit=True, hover=3,
         sel=False, outline=(0.9, 0.1, 0.1), hover_outline=(0.2, 1.0, 0.3), radius=0.25),
    dict(name="D persp 540 ao off dark exp+1 oit sel+hover", size=(960, 540), ortho=False, ao=False, strength=1.0,
         bounce=True, bg=("#20242b", "#12141a"), tonemap=True, exposure=1.0, oit=True, hover=4, sel=True,
         outline=(1.0, 0.86, 0.35), hover_outline=(0.75, 0.85, 1.0), radius=0.35),
    dict(name="E persp 1080 px2.0 bounce light notonemap oit sel+hover", size=(1920, 1080), ortho=False, ao=True,
         strength=1.0, bounce=True, bg=("#f4f5f8", "#d8dce4"), tonemap=False, exposure=0.0, oit=True, hover=2,
         sel=True, outline=(1.0, 0.86, 0.35), hover_outline=(0.75, 0.85, 1.0), radius=0.35),
    dict(name="F persp 720 outline_px 1.37 (no texel-boundary ties) sel+hover", size=(1280, 720), ortho=False,
         ao=False, strength=1.0, bounce=True, bg=("#20242b", "#12141a"), tonemap=True, exposure=0.0, oit=True,
         hover=1, sel=True, outline=(1.0, 0.86, 0.35), hover_outline=(0.75, 0.85, 1.0), radius=0.35, outline_px=1.37),
]


def to_gpu_bg(c, tonemap, exposure):
    from app.viewer.renderer import backdrop_linear
    top, bottom = c
    k = 2.0 ** -float(exposure)
    return (np.array(backdrop_linear(bottom, tonemap)) * k, np.array(backdrop_linear(top, tonemap)) * k)


def run_combo(gl, dev, pp, cmb, scenes, rows, log):
    import wgpu  # noqa
    w, h = cmb["size"]
    key = (w, h, cmb["ortho"])
    if key not in scenes:
        scenes[key] = ray_scene(w, h, cmb["ortho"], seed=1234 + w + int(cmb["ortho"]))
    sc = scenes[key]
    sh = gl.sh
    name = cmb["name"]

    def rec(pass_, stat, extra=""):
        rows.append(dict(combo=name, pass_=pass_, **stat))
        log(f"  {pass_:<28} {fmt(stat)} {extra}")

    log(f"[{name}]  {w}x{h}")
    # ---- wgpu input textures (same arrays)
    nd_w = P.make_texture(dev, w, h, "rgba32float", sc["nd"])
    id_w = P.make_texture(dev, w, h, "rg32float", sc["id"])
    op_w = P.make_texture(dev, w, h, "rgba16float", sc["opaque"])
    pv_w = P.make_texture(dev, w, h, "rgba16float", sc["prev"])
    ac_w = P.make_texture(dev, w, h, "rgba16float", sc["accum"])
    wg_w = P.make_texture(dev, w, h, "r16float", sc["weight"])
    nd_g = gl.tex(sc["nd"], near=True)
    id_g = gl.tex(sc["id"], near=True)
    op_g = gl.tex(sc["opaque"])
    pv_g = gl.tex(sc["prev"])
    ac_g = gl.tex(sc["accum"])
    wg_g = gl.tex(sc["weight"])

    # ---- backdrop
    bot, top = to_gpu_bg(cmb["bg"], cmb["tonemap"], cmb["exposure"])
    g = gl.run("backdrop", sh.BACKDROP_FS, w, h, 4, "f2", {"u_bottom": tuple(bot), "u_top": tuple(top)}, [])
    t = P.make_texture(dev, w, h, "rgba16float")
    pp.run_backdrop(t, bot, top)
    wv = P.read_texture(dev, t, np.float16, 4)
    rec("backdrop (f16)", stats(g, wv, 1 / 255))

    # ---- ssao -> blur chain
    if cmb["ao"]:
        tan = sc["tan"]
        rad = cmb["radius"]
        un = {"u_tan": tuple(tan), "u_ortho": int(cmb["ortho"]), "u_radius": float(rad), "u_bias": float(rad * 0.03),
              "u_power": float(1.6 * cmb["strength"]), "u_samples": 16, "u_large": 3.5, "u_large_mix": 0.8,
              "u_gi_on": 1.0 if cmb["bounce"] else 0.0}
        g_ssao = gl.run("ssao", sh.SSAO_FS, w, h, 4, "f2", un, [("u_nd", nd_g), ("u_prev", pv_g)])
        o_ssao = P.make_texture(dev, w, h, "rgba16float")
        pp.run_ssao(nd_w, pv_w, o_ssao, tan=tan, ortho=int(cmb["ortho"]), radius=rad, power=1.6 * cmb["strength"],
                    large=3.5, large_mix=0.8, gi_on=un["u_gi_on"], samples=16)
        w_ssao = P.read_texture(dev, o_ssao, np.float16, 4)
        s_ao = stats(g_ssao[..., 3], w_ssao[..., 3], 1 / 255)
        rec("ssao AO (a)", s_ao)
        rec("ssao GI (rgb)", stats(g_ssao[..., :3], w_ssao[..., :3], 1 / 255))
        rec("ssao AO flipped (neg.ctl)", stats(g_ssao[..., 3], w_ssao[::-1, ..., 3], 1 / 255))
        # blur isolated: both sides read the GL ssao result
        in_g = gl.tex(g_ssao)
        in_w = P.make_texture(dev, w, h, "rgba16float", g_ssao)
        bh_g = gl.run("blur", sh.BLUR_FS, w, h, 4, "f2", {"u_dir": (1.0 / w, 0.0)}, [("u_src", in_g), ("u_nd", nd_g)])
        bh_w = P.make_texture(dev, w, h, "rgba16float")
        pp.run_blur(in_w, nd_w, bh_w, (1.0 / w, 0.0))
        rec("blur H isolated (all ch)", stats(bh_g, P.read_texture(dev, bh_w, np.float16, 4), 1 / 255))
        bh_g_t = gl.tex(bh_g)
        bv_g = gl.run("blur", sh.BLUR_FS, w, h, 4, "f2", {"u_dir": (0.0, 1.0 / h)}, [("u_src", bh_g_t), ("u_nd", nd_g)])
        bh_w2 = P.make_texture(dev, w, h, "rgba16float", bh_g)
        bv_w = P.make_texture(dev, w, h, "rgba16float")
        pp.run_blur(bh_w2, nd_w, bv_w, (0.0, 1.0 / h))
        rec("blur V isolated (all ch)", stats(bv_g, P.read_texture(dev, bv_w, np.float16, 4), 1 / 255))
        # chain: wgpu ssao -> blur H -> blur V on the wgpu side only
        c1 = P.make_texture(dev, w, h, "rgba16float")
        c2 = P.make_texture(dev, w, h, "rgba16float")
        pp.run_blur(o_ssao, nd_w, c1, (1.0 / w, 0.0))
        pp.run_blur(c1, nd_w, c2, (0.0, 1.0 / h))
        wchain = P.read_texture(dev, c2, np.float16, 4)
        rec("CHAIN ssao>blur>blur AO(a)", stats(_chain_gl(gl, sh, w, h, g_ssao, nd_g)[..., 3], wchain[..., 3], 1 / 255))
        in_g.release()
        bh_g_t.release()
    else:
        log("  (ssao off: ssao/blur skipped)")

    # ---- composite
    un = {"u_oit_on": 1 if cmb["oit"] else 0, "u_has_sel": 1 if cmb["sel"] else 0, "u_hover": float(cmb["hover"]),
          "u_outline": tuple(cmb["outline"]), "u_hover_outline": tuple(cmb["hover_outline"]),
          "u_exposure": float(cmb["exposure"]), "u_tonemap": 1 if cmb["tonemap"] else 0,
          "u_texel": (1.0 / w, 1.0 / h), "u_outline_px": float(cmb.get("outline_px", max(1.5, h / 540.0)))}
    gtex = [("u_opaque", op_g), ("u_accum", ac_g), ("u_weight", wg_g), ("u_id", id_g)]
    g_c = gl.run("comp", sh.COMPOSITE_FS, w, h, 4, "f1", un, gtex)
    out_w = P.make_texture(dev, w, h, "rgba8unorm")
    pp.run_composite(op_w, ac_w, wg_w, id_w, out_w, oit_on=cmb["oit"], has_sel=cmb["sel"], hover=cmb["hover"],
                     outline=cmb["outline"], hover_outline=cmb["hover_outline"], exposure=cmb["exposure"],
                     tonemap=cmb["tonemap"], outline_px=cmb.get("outline_px"))
    w_c = P.read_texture(dev, out_w, np.uint8, 4)
    s = stats(g_c[..., :3], w_c[..., :3], 1.0)
    rec("COMPOSITE final 8-bit", s, "(units: 1/255 levels)")
    s2 = stats(g_c[..., :3], w_c[::-1, ..., :3], 1.0)
    rec("composite flipped (neg.ctl)", s2)
    # outline-only: pixels near ids with selection (errors concentrated on the outline?)
    diff = np.abs(g_c[..., :3].astype(int) - w_c[..., :3].astype(int)).max(-1)
    rows[-2]["n_over2"] = int((diff > 2).sum())
    # blit (scaled): composite output -> 3/4 size, linear
    ow, oh = (w * 3) // 4, (h * 3) // 4
    fin_g = gl.tex(g_c)
    fin_g.filter = (gl.mgl.LINEAR, gl.mgl.LINEAR)
    g_b = gl.run("blit", sh.BLIT_FS, ow, oh, 4, "f1", {}, [("u_src", fin_g)])
    src_w = P.make_texture(dev, w, h, "rgba8unorm", g_c)
    out_b = P.make_texture(dev, ow, oh, "rgba8unorm")
    pp.run_blit(src_w, out_b)
    rec("blit 3/4 scale 8-bit", stats(g_b[..., :3], P.read_texture(dev, out_b, np.uint8, 4)[..., :3], 1.0))
    for t_ in (nd_g, id_g, op_g, pv_g, ac_g, wg_g, fin_g):
        t_.release()
    return s


_chain_cache = {}


def _chain_gl(gl, sh, w, h, g_ssao, nd_g):
    a = gl.tex(g_ssao)
    h1 = gl.run("blur", sh.BLUR_FS, w, h, 4, "f2", {"u_dir": (1.0 / w, 0.0)}, [("u_src", a), ("u_nd", nd_g)])
    b = gl.tex(h1)
    out = gl.run("blur", sh.BLUR_FS, w, h, 4, "f2", {"u_dir": (0.0, 1.0 / h)}, [("u_src", b), ("u_nd", nd_g)])
    a.release()
    b.release()
    return out


def run_env(gl, dev, pp, rows, log):
    """Prefiltered environment array, level (layer) by level, plus the mip chain of the source."""
    from app.viewer import environment as E
    mgl = gl.mgl
    env = E.make_env(studio=0.35, ambient=0.15)
    h, w, _ = env.shape
    src_g = gl.ctx.texture((w, h), 3, np.ascontiguousarray(env).tobytes(), dtype="f4")
    src_g.repeat_x, src_g.repeat_y = True, False
    src_g.build_mipmaps()
    src_g.filter = (mgl.LINEAR_MIPMAP_LINEAR, mgl.LINEAR)
    src_w = pp.make_env_source(env)
    # mip chain check (GL read per level)
    try:
        worst = 0.0
        lv = 0
        cur = np.concatenate([env, np.ones((h, w, 1), np.float32)], -1)
        for lv in range(1, int(np.log2(max(w, h))) + 1):
            lh, lw = max(h >> lv, 1), max(w >> lv, 1)
            gm = np.frombuffer(src_g.read(level=lv), dtype=np.float32).reshape(lh, lw, 3)
            data = P.read_texture(dev, _copy_level(dev, src_w, lv), np.float32 if pp.float32_filterable else np.float16, 4)
            worst = max(worst, float(np.abs(gm - data[..., :3]).max()))
        log(f"  env mip chain: max abs diff GL glGenerateMipmap vs CPU box filter = {worst:.3e}")
        rows.append(dict(combo="env", pass_="mip chain", max=worst, mean=0, p999=0, pct_over1=0, pct_any=0))
    except Exception as ex:  # moderngl without read(level=)
        log(f"  env mip chain compare skipped: {ex}")
    SW, SH = E.SPEC_W, E.SPEC_H
    prog = gl.ctx.program(vertex_shader=gl.sh.FSQ_VS, fragment_shader=gl.sh.PREFILTER_FS)
    vao = gl.ctx.vertex_array(prog, [])
    dst = gl.ctx.texture((SW, SH), 4, dtype="f4")
    fbo = gl.ctx.framebuffer(color_attachments=[dst])
    src_g.use(0)
    prog["u_src"].value = 0
    prog["u_src_w"].value = float(w)
    glayers = []
    for i in range(E.ROUGH_LAYERS):
        fbo.use()
        gl.ctx.viewport = (0, 0, SW, SH)
        prog["u_rough"].value = i / (E.ROUGH_LAYERS - 1)
        vao.render(mgl.TRIANGLES, vertices=3)
        glayers.append(np.frombuffer(fbo.read(components=4, dtype="f4"), dtype=np.float32).reshape(SH, SW, 4))
    # f32 per-layer
    for i in range(E.ROUGH_LAYERS):
        t = P.make_texture(dev, SW, SH, "rgba32float")
        pp.run_prefilter(src_w, t, i / (E.ROUGH_LAYERS - 1), float(w), fmt="rgba32float")
        wv = P.read_texture(dev, t, np.float32, 4)
        s = stats(glayers[i][..., :3], wv[..., :3], 1e-3 * 1.0)  # unit: 1e-3 absolute radiance
        rows.append(dict(combo="env", pass_=f"prefilter f32 layer {i} (rough {i/5:.1f})", **s))
        rel = float((np.abs(glayers[i][..., :3] - wv[..., :3]) / np.maximum(glayers[i][..., :3], 1e-3)).max())
        log(f"  prefilter f32 layer {i}: {fmt(s)}  (unit 1e-3; max rel {rel:.2e})")
    # f16 array: real Environment class vs wgpu array
    genv = E.Environment(gl.ctx)
    g_arr = np.frombuffer(genv.spec.read(), dtype=np.float16).reshape(E.ROUGH_LAYERS, SH, SW, 4)
    spec, _ = pp.build_env_spec(env)
    for i in range(E.ROUGH_LAYERS):
        wv = P.read_texture(dev, spec, np.float16, 4, layer=i)
        s = stats(g_arr[i][..., :3], wv[..., :3], 1e-3)
        rows.append(dict(combo="env", pass_=f"Environment.spec f16 layer {i}", **s))
        log(f"  spec array f16 layer {i}: {fmt(s)}  (unit 1e-3)")


def _copy_level(dev, tex, lv):
    """Copy one mip level of tex into a plain 2d texture so read_texture can read it."""
    import wgpu
    w, h = max(tex.size[0] >> lv, 1), max(tex.size[1] >> lv, 1)
    out = dev.create_texture(size=(w, h, 1), format=tex.format, usage=wgpu.TextureUsage.COPY_DST | wgpu.TextureUsage.COPY_SRC)
    enc = dev.create_command_encoder()
    enc.copy_texture_to_texture({"texture": tex, "mip_level": lv, "origin": (0, 0, 0)},
                                {"texture": out, "mip_level": 0, "origin": (0, 0, 0)}, (w, h, 1))
    dev.queue.submit([enc.finish()])
    return out


def run(adapter_name=None, quick=False, log=print):
    ad = pick_adapter(adapter_name)
    if ad is None:
        raise RuntimeError(f"no adapter matching {adapter_name!r}")
    dev = make_device(ad)
    pp = P.PostPasses(dev)
    gl = GL()
    log(f"GL_RENDERER: {gl.info}")
    log(f"wgpu adapter: {ad.info['device']}  backend {ad.info['backend_type']}  float32-filterable "
        f"{pp.float32_filterable}")
    rows = []
    scenes = {}
    combos = COMBOS[:1] if quick else COMBOS
    worst = dict(max=0.0, mean=0.0)
    results = []
    for c in combos:
        s = run_combo(gl, dev, pp, c, scenes, rows, log)
        results.append((c["name"], s))
    if not quick:
        log("[environment]")
        run_env(gl, dev, pp, rows, log)
    log("")
    log("FINAL 8-bit composite (acceptance: max <= 2, mean <= 0.2 levels):")
    ok = True
    for n, s in results:
        good = s["max"] <= 2.0 and s["mean"] <= 0.2
        ok &= good
        log(f"  {'PASS' if good else 'FAIL'}  {n:<62} max {s['max']:.0f}  mean {s['mean']:.5f}  >1lvl {s['pct_over1']:.4f}%")
    return dict(gl=gl.info, adapter=ad.info["device"], backend=ad.info["backend_type"], ok=ok, rows=rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    res = run(a.adapter, a.quick)
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1))
    sys.exit(0 if res["ok"] else 1)
