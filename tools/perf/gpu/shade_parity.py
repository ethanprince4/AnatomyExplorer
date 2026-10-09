"""Parity of the model viewer's surface shading: GLSL (app/viewer/shaders.py GEOM_VS + MAIN_FS, moderngl) against the
WGSL port (app/gpu/wgsl/vertex.wgsl + shading.wgsl, wgpu), single sample, rgba32float targets.

    python tools/perf/gpu/shade_parity.py [--size 512] [--adapter NVIDIA|Intel] [--cases a,b] [--json out.json]
                                          [--deriv auto|dpdx|dpdxFine|dpdxCoarse] [--aniso 8] [--gl-literal]

Both sides draw the SAME seeded triangle mesh (spheres, a twisted ribbon seen from both sides, a mirrored sphere,
animated spheres) with the SAME uniforms: the uniform dicts are produced by calling the real Renderer methods
(_light_uniforms, _set_look, _clip_uniforms, _anim_uniforms) on a recorder, then replayed through the renderer's own
`_U` on the GL program and packed with app/gpu/shading_uniforms.py for WGSL.  Environment (SH9 + prefiltered specular),
AO image, item texture and the mip-mapped albedo texture are generated once and uploaded to both.  The AO image is
uploaded vertically flipped to wgpu (its fragment position has a top-left origin; GL's gl_FragCoord is bottom-left),
and the GL read-back is flipped for comparison.  The wgpu fragment wrapper (derivatives from dpdx/dpdy) lives here.

Metrics are taken after today's tone mapping: exp2(exposure) -> Khronos PBR Neutral -> sRGB (composite shader without
outline and dither), in 1/255 units, over pixels covered in both images.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.gpu.shading_uniforms import SIZE as SHADE_SIZE, pack_shading_uniforms  # noqa: E402
from app.viewer import shaders  # noqa: E402
from app.viewer.environment import ROUGH_LAYERS, SPEC_H, SPEC_W, Environment  # noqa: E402
from app.viewer.model import Look, NO_FIBRE  # noqa: E402
from app.viewer.renderer import (ANIM_ATTRS, ANIM_FMT, ATTRS, DEFAULT_RIG, FMT, FrameState, Renderer,  # noqa: E402
                                 Settings, _U)

WGSL_DIR = ROOT / "app" / "gpu" / "wgsl"


# ---------------------------------------------------------------------------------------------------------------
# scene

class Mesh:
    def __init__(self, pos, nrm, uv, idx, fib=None, col=None, dpos=None, dnrm=None, rng=None, anim=False):
        n = len(pos)
        self.pos = pos.astype(np.float32)
        self.nrm = nrm.astype(np.float32)
        self.uv = uv.astype(np.float32)
        self.idx = idx.astype(np.uint32)
        self.fib = (np.full(n, NO_FIBRE) if fib is None else fib).astype(np.float32)
        self.col = (np.ones((n, 4)) if col is None else col).astype(np.float32)
        self.dpos = (np.zeros((n, 3)) if dpos is None else dpos).astype(np.float32)
        self.dnrm = (np.zeros((n, 3)) if dnrm is None else dnrm).astype(np.float32)
        self.m = np.zeros((4, n, 4), np.float16)
        self.phase = np.zeros(n, np.float32)
        if anim:                    # smooth functions of position: seam duplicates must not open cracks
            for k in range(4):
                self.m[k, :, :3] = (0.15 * np.sin(3.0 * (k + 1) * self.pos + k)).astype(np.float16)
            self.phase[:] = (0.5 + 0.5 * np.sin(4.0 * self.pos[:, 0] + 3.0 * self.pos[:, 1] + 1.0)).astype(np.float32)

    @property
    def tris(self):
        return len(self.idx)

    def vertex_block(self):
        return np.concatenate([self.pos, self.nrm, self.dpos, self.dnrm, self.fib[:, None], self.col, self.uv],
                              1).astype(np.float32)

    def anim_block(self):
        out = np.zeros(len(self.pos), dtype=[("m", np.float16, (4, 4)), ("p", np.float32)])
        out["m"] = np.transpose(self.m, (1, 0, 2))
        out["p"] = self.phase
        return out


def _fix_winding(pos, nrm, idx):
    a, b, c = (pos[idx[:, k]] for k in range(3))
    face = np.cross(b - a, c - a)
    agree = np.einsum("ij,ij->i", face, nrm[idx[:, 0]] + nrm[idx[:, 1]] + nrm[idx[:, 2]]) < 0
    idx = idx.copy()
    idx[agree, 1], idx[agree, 2] = idx[agree, 2], idx[agree, 1]
    return idx


def uv_sphere(nu, nv, radius, rng, fib_scale=14.0, morph=True, anim=False, no_fib=False):
    u, v = np.meshgrid(np.linspace(0, 1, nu + 1), np.linspace(0, 1, nv + 1))
    th, ph = v * math.pi, u * 2 * math.pi
    nrm = np.stack([np.sin(th) * np.cos(ph), np.cos(th), np.sin(th) * np.sin(ph)], -1).reshape(-1, 3)
    pos = nrm * radius
    uv = np.stack([u, v], -1).reshape(-1, 2)
    k = np.arange((nu + 1) * (nv + 1)).reshape(nv + 1, nu + 1)
    quad = np.stack([k[:-1, :-1], k[:-1, 1:], k[1:, 1:], k[1:, :-1]], -1).reshape(-1, 4)
    idx = np.concatenate([quad[:, [0, 1, 2]], quad[:, [0, 2, 3]]], 0)
    idx = _fix_winding(pos, nrm, idx)
    t = 0.5 + 0.5 * np.sin(pos * 3.1 + rng.random(3) * 6)
    col = np.concatenate([0.25 + 0.75 * t, np.ones((len(pos), 1))], 1)
    fib = None if no_fib else fib_scale * (pos[:, 1] + radius) / (2 * radius) + 0.4 * np.sin(pos[:, 0] * 5)
    dpos = (0.10 * radius * nrm * np.sin(5 * ph.reshape(-1, 1)) * np.sin(th.reshape(-1, 1)) if morph else None)
    dnrm = (0.25 * np.stack([np.cos(4 * ph), np.zeros_like(ph), np.sin(4 * ph)], -1).reshape(-1, 3) if morph else None)
    return Mesh(pos, nrm, uv, idx, fib, col, dpos, dnrm, rng, anim)


def twisted_ribbon(nu, nw, length, width, turns, rng):
    u, w = np.meshgrid(np.linspace(0, 1, nu + 1), np.linspace(-1, 1, nw + 1))
    cx = length * (u - 0.5)
    cy = 0.15 * np.sin(2 * np.pi * u)
    th = 2 * np.pi * turns * u
    d = np.stack([np.zeros_like(u), np.cos(th), np.sin(th)], -1)
    c = np.stack([cx, cy, np.zeros_like(u)], -1)
    pos = (c + 0.5 * width * w[..., None] * d).reshape(-1, 3)
    dc = np.stack([np.full_like(u, length), 2 * np.pi * 0.15 * np.cos(2 * np.pi * u), np.zeros_like(u)], -1)
    nrm = np.cross(dc, d)
    nrm = (nrm / np.linalg.norm(nrm, axis=-1, keepdims=True)).reshape(-1, 3)
    uv = np.stack([u * 3.0, (w + 1) / 2], -1).reshape(-1, 2)           # repeats the texture 3x along the ribbon
    k = np.arange((nu + 1) * (nw + 1)).reshape(nw + 1, nu + 1)
    quad = np.stack([k[:-1, :-1], k[:-1, 1:], k[1:, 1:], k[1:, :-1]], -1).reshape(-1, 4)
    idx = np.concatenate([quad[:, [0, 1, 2]], quad[:, [0, 2, 3]]], 0)
    idx = _fix_winding(pos, nrm, idx)
    col = np.concatenate([0.3 + 0.7 * rng.random((len(pos), 3)) * 0.0 + 0.5 + 0.5 * np.sin(pos * 2.0 + 1.0),
                          np.ones((len(pos), 1))], 1)
    fib = 20.0 * np.hypot(pos[:, 0], pos[:, 2]) + 9.0 * (u.reshape(-1))
    return Mesh(pos, nrm, uv, idx, fib, col)


def translate(x, y, z, sx=1.0, sy=1.0, sz=1.0):
    m = np.eye(4, dtype=np.float64)
    m[:3, 3] = (x, y, z)
    m[0, 0], m[1, 1], m[2, 2] = sx, sy, sz
    return m


class Part:
    def __init__(self, mesh, matrix, look, item, weight=0.0, noclip=False, anim=None, selected=False,
                 batched=False, name=""):
        self.mesh, self.matrix, self.look, self.item = mesh, matrix, look, item
        self.weight, self.noclip, self.anim, self.selected, self.batched = weight, noclip, anim, selected, batched
        self.name = name


def build_meshes(scale, seed):
    rng = np.random.default_rng(seed)
    s = scale
    return {
        "sphA": uv_sphere(int(56 * s), int(28 * s), 0.9, rng),
        "sphB": uv_sphere(int(40 * s), int(20 * s), 0.7, rng, fib_scale=9.0),
        "ribbon": twisted_ribbon(int(80 * s), max(int(8 * s), 2), 4.2, 0.9, 1.25, rng),
        "anim1": uv_sphere(int(24 * s), int(12 * s), 0.33, rng, anim=True),
        "anim2": uv_sphere(int(24 * s), int(12 * s), 0.33, rng, anim=True),
        "mirror": uv_sphere(int(24 * s), int(12 * s), 0.4, rng, no_fib=True),
    }


# ---------------------------------------------------------------------------------------------------------------
# cases

STRIPE = {"period": 1.0, "threshold": 0.3, "edge": 0.025, "i_mix": 1.0, "shorten": 0.35,
          "a_band_colour": [0.55, 0.12, 0.10], "i_band_colour": [0.80, 0.55, 0.45]}
MOTTLE = {"scale": 6.0, "detail": 2.0, "from_min": 0.35, "from_max": 0.65,
          "colour_a": [0.40, 0.10, 0.08], "colour_b": [0.75, 0.40, 0.30]}


def make_cases():
    """name -> dict(settings, studio, ortho, ao_strength, clip, parts spec).  A part spec is
    (mesh, matrix, look-kwargs, extra-kwargs)."""
    M = translate
    default_parts = [
        ("sphA", M(-1.2, 0.4, 0.0), {}, {}),
        ("sphB", M(1.2, 0.5, 0.0), {"rough": 0.3, "f0": 0.05}, {"weight": 0.5}),
        ("ribbon", M(0.0, -0.95, 0.3), {"rough": 0.7}, {}),
        ("mirror", M(0.2, -0.1, 1.0, -1, 1, 1), {"base": (0.7, 0.6, 0.4), "rough": 0.45, "use_vcol": False}, {}),
    ]
    return {
        # Settings defaults, default looks (vertex colours), studio 0.30, AO on with the default direct share
        "default": dict(settings={}, studio=0.30, ortho=False, ao=(0.7, 0.35), parts=[
            (m, x, dict(look, use_vcol=look.get("use_vcol", True)), ex) for m, x, look, ex in default_parts]),
        # textured: albedo texture on the spheres and an alpha-tested ribbon; flat ambient environment, strong AO
        "textured": dict(settings={"bounce": 0.6, "ao_direct": 1.0}, studio=0.0, ortho=False, ao=(1.0, 1.0), parts=[
            ("sphA", M(-1.2, 0.4, 0.0), {"texture": True, "use_vcol": True}, {}),
            ("sphB", M(1.2, 0.5, 0.0), {"texture": True, "rough": 0.25, "sss": 0.2}, {"weight": 0.3}),
            ("ribbon", M(0.0, -0.95, 0.3), {"texture": True, "alpha_cut": 0.5, "rough": 0.8}, {}),
            ("mirror", M(0.2, -0.1, 1.0, -1, 1, 1), {"texture": True, "metal": 0.8, "rough": 0.35}, {})]),
        # tissue looks: stripes, mottle, procedural detail with each fibre axis; full studio, orthographic, AO off
        "tissue_ortho": dict(settings={"ao": False, "light_scale": 1.3, "tissue": 1.4}, studio=1.0, ortho=True,
                             ao=(0.3, 0.35), parts=[
            ("sphA", M(-1.2, 0.4, 0.0), {"stripe": STRIPE, "sss": 0.25, "rough": 0.55}, {"weight": 0.6}),
            ("sphB", M(1.2, 0.5, 0.0), {"mottle": MOTTLE, "sss": 0.15, "rough": 0.5}, {}),
            ("ribbon", M(0.0, -0.95, 0.3), {"detail": (0.34, 40.0, 0.5, 4.0), "use_vcol": True, "sss": 0.1}, {}),
            ("mirror", M(0.2, -0.1, 1.0, -1, 1, 1), {"detail": (0.25, 25.0, 0.5, 2.0), "base": (0.8, 0.7, 0.6)},
             {})]),
        # cut planes in both modes, batched items with flat colours and highlights, selected part, metals, AO-heavy
        "clip_batched": dict(settings={"ao_direct": 0.8, "env_diffuse": 1.2, "env_spec": 1.5, "bounce": 0.9,
                                       "light_scale": 0.8}, studio=0.6, ortho=False, ao=(0.9, 0.8),
                             clip=((0.0, 1.0, 0.0, 1.3), (-1.0, 0.3, 0.0, 1.2), (0.0, 0.0, 1.0, 0.9)),
                             clip_on=(True, True, False), clip_mode=0, parts=[
            ("sphA", M(-1.2, 0.4, 0.0), {}, {"batched": True}),
            ("sphB", M(1.2, 0.5, 0.0), {"metal": 1.0, "rough": 0.2, "base": (0.9, 0.7, 0.3)}, {"selected": True}),
            ("ribbon", M(0.0, -0.95, 0.3), {"rough": 0.9}, {"batched": True}),
            ("mirror", M(0.2, -0.1, 1.0, -1, 1, 1), {"emissive": (0.1, 0.02, 0.0)}, {"noclip": True})]),
        # the same with a corner cut (mode 1) and the procedural animation: waves (mode 2) and particles (mode 1)
        "anim_corner": dict(settings={"studio": 0.15}, studio=0.15, ortho=False, ao=(0.5, 0.35),
                            clip=((0.0, 1.0, 0.0, 0.6), (1.0, 0.0, 0.0, 0.8), (0.0, 0.0, 1.0, -0.1)),
                            clip_on=(True, True, True), clip_mode=1, anim_t=0.37, parts=[
            ("sphA", M(-1.2, 0.4, 0.0), {"use_vcol": True}, {}),
            ("sphB", M(1.2, 0.5, 0.0), {"mottle": MOTTLE}, {"weight": 0.7}),
            ("ribbon", M(0.0, -0.95, 0.3), {"stripe": STRIPE}, {}),
            ("anim1", M(-0.5, 1.35, 0.6), {"base": (0.5, 0.5, 0.8), "use_vcol": True},
             {"anim": ((0.4, -0.3, 0.8, 0.2), (2.0, 0.9, 0.25, 1.0))}),
            ("anim2", M(0.6, 1.35, 0.6), {"base": (0.8, 0.4, 0.4)},
             {"anim": ((0.5, 0.0, 0.0, 0.3), (1.0, 0.0, 0.1, 2.0))})]),
    }


# ---------------------------------------------------------------------------------------------------------------
# inputs shared by both APIs

def perspective(fov_deg, aspect, near, far):
    f = 1.0 / math.tan(math.radians(fov_deg) / 2)
    m = np.zeros((4, 4))
    m[0, 0], m[1, 1] = f / aspect, f
    m[2, 2], m[2, 3] = (far + near) / (near - far), 2 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


def ortho(half_h, aspect, near, far):
    m = np.eye(4)
    m[0, 0], m[1, 1], m[2, 2], m[2, 3] = 1 / (half_h * aspect), 1 / half_h, -2 / (far - near), -(far + near) / (far - near)
    return m


def look_at(eye, target, up=(0, 1, 0)):
    f = np.asarray(target, float) - eye
    f /= np.linalg.norm(f)
    r = np.cross(f, up)
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    m = np.eye(4)
    m[0, :3], m[1, :3], m[2, :3] = r, u, -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m


class Null:
    def use(self, *a):
        pass


class Recorder:
    """Stands in for renderer._U: records (name, value) the way the renderer sets them."""

    def __init__(self):
        self.d = {}
        self.prog = types.SimpleNamespace(get=self._get)

    def _get(self, name, default=None):
        if name == "u_sh":
            return types.SimpleNamespace(write=lambda b: self.d.__setitem__("u_sh", np.frombuffer(b, np.float32).reshape(9, 3).copy()))
        return default

    def __call__(self, name, value):
        self.d[name] = value


def smooth_noise(rng, h, w, passes=6):
    a = rng.random((h, w))
    for _ in range(passes):
        a = (a + np.roll(a, 1, 0) + np.roll(a, -1, 0) + np.roll(a, 1, 1) + np.roll(a, -1, 1)) / 5.0
    a = (a - a.min()) / max(a.max() - a.min(), 1e-6)
    return a


def make_ao(rng, size, strength):
    """(h, w, 4) float16 in GL row order: rgb = bounce GI, a = occlusion."""
    n = smooth_noise(rng, size, size)
    ao = 1.0 - strength * 0.8 * n
    gi = 0.15 * smooth_noise(rng, size, size)[..., None] * np.array([1.0, 0.8, 0.6])
    return np.concatenate([gi, ao[..., None]], -1).astype(np.float16)


def make_texture(rng, n=256):
    """sRGB8 RGBA bytes with alpha holes, and its mip chain as read back from GL (filled in by build_texture_chain)."""
    y, x = np.mgrid[0:n, 0:n] / n
    r = 0.5 + 0.5 * np.sin(14 * x + 3 * np.sin(9 * y))
    g = 0.5 + 0.5 * np.sin(11 * y + 2 * np.cos(7 * x))
    b = smooth_noise(rng, n, n, 3)
    chk = (np.floor(x * 8) + np.floor(y * 8)) % 2
    holes = np.hypot((x * 6) % 1 - 0.5, (y * 6) % 1 - 0.5) < 0.2
    rgb = np.stack([r * (0.6 + 0.4 * chk), g, b], -1)
    a = np.where(holes, 0.0, 1.0)
    return np.clip(np.concatenate([rgb, a[..., None]], -1) * 255 + 0.5, 0, 255).astype(np.uint8)


def case_uniforms(case, parts, size):
    """-> (frame info, [per-part uniform dict])  Produced by the renderer's own methods on a recorder."""
    st = Settings(**case["settings"])
    st.studio = case["studio"]
    st.shadows = False                               # viewport.py:106: shadows are always off in the model viewer
    fs = FrameState()
    clip = case.get("clip")
    fs.anim_t = case.get("anim_t", 0.0)
    if clip is not None:
        planes = np.array(clip, dtype=np.float64)
        fs.clip_planes, fs.clip_on, fs.clip_mode = tuple(map(tuple, planes)), case["clip_on"], case["clip_mode"]
    else:
        planes, fs.clip_on, fs.clip_mode = np.array(fs.clip_planes, dtype=np.float64), (False,) * 3, 0
    aspect = 1.0
    if case["ortho"]:
        eye = np.array([0.4, 0.7, 6.0])
        V = look_at(eye, (0, 0.2, 0))
        P = ortho(2.4, aspect, 0.1, 30.0)
    else:
        eye = np.array([0.3, 0.9, 5.2])
        V = look_at(eye, (0, 0.1, 0))
        P = perspective(42.0, aspect, 0.1, 30.0)
    VP = P @ V
    camera = types.SimpleNamespace(ortho=case["ortho"], basis=lambda: (None, None, (eye - np.array([0, 0.15, 0])) / np.linalg.norm(eye - np.array([0, 0.15, 0]))))
    Rinv = V[:3, :3].T
    lights = []
    for spec in DEFAULT_RIG[:3]:                     # renderer.py:708-718
        az, el = math.radians(spec["azimuth_deg"]), math.radians(spec["elevation_deg"])
        dv = np.array([math.cos(el) * math.sin(az), math.sin(el), math.cos(el) * math.cos(az)])
        L = Rinv @ dv
        E = np.array(spec.get("colour", [1, 1, 1]), float) * float(spec["energy"]) / math.pi * st.light_scale
        size_eq = float(spec.get("size_factor", 0.35)) * 0.5642
        lights.append((L / np.linalg.norm(L), E, size_eq, float(spec.get("size_factor", 0.35))))
    return dict(settings=st, fs=fs, V=V, P=P, VP=VP, eye=eye, camera=camera, lights=lights, planes=planes,
                size=(size, size))


def part_uniforms(frame, part, env_stub, texture_ids):
    st, fs = frame["settings"], frame["fs"]
    rec = Recorder()
    n_items = 8
    anim = part.anim
    fs.anim_frame = None
    if anim is not None:
        fa = np.zeros((2, n_items, 4), np.float32)
        fa[0, part.item], fa[1, part.item] = anim[0], anim[1]
        fs.anim_frame = fa
    fake = types.SimpleNamespace(
        t={"ao": Null()}, shadow_maps=[(Null(),)] * 3, _shadow_mats=[np.eye(4)] * 3, _shadow_texel=[0.01] * 3,
        _shadow_soft=[1.0] * 3, env=env_stub, white=Null(), _fs=fs, abo=object() if anim is not None else None,
        _texture=lambda i: Null())
    Renderer._light_uniforms(fake, rec, frame["V"], frame["eye"], frame["lights"], st, frame["size"], frame["camera"])
    rec("u_viewproj", frame["VP"])
    Renderer._clip_uniforms(rec, (frame["planes"], tuple(1 if x else 0 for x in fs.clip_on), fs.clip_mode))
    M = part.matrix.astype(np.float32)
    flip = 1 if np.linalg.det(M[:3, :3]) < 0 else 0
    rec("u_model", M)
    rec("u_nmat", np.linalg.inv(M[:3, :3]).T)
    rec("u_flip", flip)
    rec("u_weight", float(part.weight))
    rec("u_noclip", 1 if part.noclip else 0)
    Renderer._anim_uniforms(fake, rec, types.SimpleNamespace(item=part.item))
    rec("u_batched", 1 if part.batched else 0)
    look = part.look
    Renderer._set_look(fake, rec, types.SimpleNamespace(look=look, item=part.item), st, fs, part.batched)
    if look.texture is not None:
        rec("u_tex", 6)
    if part.selected:
        rec("u_highlight", 0.45)
        rec("u_highlight_col", np.array(st.highlight))
    else:
        rec("u_highlight", 0.0)
    rec("u_items", 11)
    return rec.d


def make_look(kw, tex_index=0):
    kw = dict(kw)
    if kw.pop("texture", False):
        kw["texture"] = tex_index
    if "stripe" in kw or "mottle" in kw:
        kw.setdefault("use_vcol", False)
    return Look(**kw)


# ---------------------------------------------------------------------------------------------------------------
# GL side

class GL:
    def __init__(self, size, literal=False):
        import moderngl
        self.mgl = moderngl
        self.size = size
        self.ctx = moderngl.create_standalone_context(require=410)
        self.info = self.ctx.info["GL_RENDERER"]
        ctx = self.ctx
        fs_src = shaders.MAIN_FS
        if not literal:
            # MAIN_FS discards clipped fragments BEFORE the stripe's fwidth(); derivatives after a discard are undefined
            # in GLSL and NVIDIA returns garbage next to a cut (error up to 55/255 on pixels beside a cut plane).
            # Discarding after surface() is the same picture with defined derivatives, which is what WGSL gives.
            a = "    if (clipped(v_wpos)) discard;\n    Surface s = surface();\n"
            assert a in fs_src
            fs_src = fs_src.replace(a, "    Surface s = surface();\n    if (clipped(v_wpos)) discard;\n")
        self.prog = ctx.program(vertex_shader=shaders.GEOM_VS, fragment_shader=fs_src)
        self.u = _U(self.prog)
        self.color = ctx.texture((size, size), 4, dtype="f4")
        self.depth = ctx.depth_texture((size, size))
        self.fbo = ctx.framebuffer([self.color], self.depth)
        self.white = ctx.texture((1, 1), 4, bytes([255, 255, 255, 255]))
        self.shadow = ctx.depth_texture((4, 4))
        self.env = None

    def set_env(self, studio):
        if self.env is not None:
            self.env.spec.release()
        self.env = Environment(self.ctx, studio=studio)
        spec = self.env.spec
        assert spec.filter == (self.mgl.LINEAR, self.mgl.LINEAR), spec.filter
        data = np.frombuffer(spec.read(), np.float16).reshape(ROUGH_LAYERS, SPEC_H, SPEC_W, 4).copy()
        return self.env.sh.copy(), data

    def texture_chain(self, rgba8):
        """Upload an sRGB texture, let GL build the mip chain and return every level's bytes as GL stored them."""
        tex = self.ctx.texture((rgba8.shape[1], rgba8.shape[0]), 4, rgba8.tobytes(), internal_format=0x8C43)
        tex.build_mipmaps()
        tex.filter = (self.mgl.LINEAR_MIPMAP_LINEAR, self.mgl.LINEAR)
        n = int(math.log2(max(rgba8.shape[:2]))) + 1
        levels = [np.frombuffer(tex.read(level=i), np.uint8).reshape(max(rgba8.shape[0] >> i, 1),
                                                                    max(rgba8.shape[1] >> i, 1), 4).copy()
                  for i in range(n)]
        return tex, levels

    def render(self, meshes_gpu, draws, ao, items, tex, spec_tex_aniso):
        """draws: [(part index, uniform dict)].  Returns (h, w, 4) float32, top row first."""
        ctx, prog, u = self.ctx, self.prog, self.u
        self.fbo.use()
        ctx.viewport = (0, 0, self.size, self.size)
        self.fbo.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        ctx.enable(self.mgl.DEPTH_TEST)
        ctx.depth_func = "<"
        ao_tex = ctx.texture((self.size, self.size), 4, ao.tobytes(), dtype="f2")
        ao_tex.repeat_x = ao_tex.repeat_y = False
        items_tex = ctx.texture((items.shape[1], items.shape[0]), 4, items.astype(np.float32).tobytes(), dtype="f4")
        items_tex.filter = (self.mgl.NEAREST, self.mgl.NEAREST)
        self.shadow.use(1), self.shadow.use(2), self.shadow.use(3)
        ao_tex.use(0)
        self.env.spec.use(4)
        self.white.use(5)
        tex.use(6)
        items_tex.use(11)
        for pi, d in draws:
            for k, v in d.items():
                if k == "u_sh":
                    prog["u_sh"].write(np.ascontiguousarray(v, dtype=np.float32).tobytes())
                else:
                    u(k, v)
            meshes_gpu[pi].render(self.mgl.TRIANGLES)
        out = np.frombuffer(self.fbo.read(components=4, dtype="f4", attachment=0), np.float32).reshape(
            self.size, self.size, 4)[::-1].copy()
        ao_tex.release()
        items_tex.release()
        return out

    def mesh_vao(self, mesh):
        ctx = self.ctx
        vbo = ctx.buffer(np.ascontiguousarray(mesh.vertex_block()))
        ibo = ctx.buffer(mesh.idx.tobytes())
        ivbo = ctx.buffer(np.full(len(mesh.pos), 0, np.float32))
        abo = ctx.buffer(np.ascontiguousarray(mesh.anim_block()).view(np.uint8))
        return vbo, ibo, ivbo, abo

    def make_vao(self, mesh, item):
        vbo, ibo, _, abo = self.mesh_vao(mesh)
        ivbo = self.ctx.buffer(np.full(len(mesh.pos), float(item), np.float32))
        return self.ctx.vertex_array(self.prog, [(vbo, FMT, *ATTRS), (ivbo, "1f", "in_item"),
                                                 (abo, ANIM_FMT, *ANIM_ATTRS)], ibo, 4, skip_errors=True)


# ---------------------------------------------------------------------------------------------------------------
# WGSL wrapper (fragment derivatives live here, not in shading.wgsl)

WRAPPER = """
struct PartU {
    model: mat4x4<f32>,
    nmat0: vec4<f32>, nmat1: vec4<f32>, nmat2: vec4<f32>,
    viewproj: mat4x4<f32>,
    aw: vec4<f32>,
    ag: vec4<f32>,
    weight: f32, anim: i32, anim_t: f32, part_id: f32,
}
@group(0) @binding(0) var<uniform> part: PartU;

struct VIn {
    @location(0) pos: vec3<f32>, @location(1) nrm: vec3<f32>, @location(2) dpos: vec3<f32>, @location(3) dnrm: vec3<f32>,
    @location(4) fib: f32, @location(5) col: vec4<f32>, @location(6) uv: vec2<f32>,
    @location(7) m0: vec4<f32>, @location(8) m1: vec4<f32>, @location(9) m2: vec4<f32>, @location(10) m3: vec4<f32>,
    @location(11) phase: f32, @location(12) item: f32,
}
struct VOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) wpos: vec3<f32>, @location(1) wnrm: vec3<f32>, @location(2) opos: vec3<f32>,
    @location(3) fib: f32, @location(4) col: vec4<f32>, @location(5) uv: vec2<f32>, @location(6) glow: f32,
    @location(7) @interpolate(flat) item: i32,
}
@vertex fn vs_main(v: VIn) -> VOut {
    var a: VtxAttr;
    a.pos = v.pos; a.nrm = v.nrm; a.dpos = v.dpos; a.dnrm = v.dnrm; a.fib = v.fib; a.col = v.col; a.uv = v.uv;
    a.m0 = v.m0; a.m1 = v.m1; a.m2 = v.m2; a.m3 = v.m3; a.phase = v.phase; a.item = v.item;
    var x: PartXf;
    x.model = part.model;
    x.nmat = mat3x3<f32>(part.nmat0.xyz, part.nmat1.xyz, part.nmat2.xyz);
    x.viewproj = part.viewproj;
    x.weight = part.weight; x.anim = part.anim; x.anim_t = part.anim_t; x.aw = part.aw; x.ag = part.ag;
    let r = vs_math(a, x);
    var o: VOut;
    o.pos = r.clip; o.wpos = r.wpos; o.wnrm = r.wnrm; o.opos = r.opos; o.fib = r.fib; o.col = r.col; o.uv = r.uv;
    o.glow = r.glow; o.item = r.item;
    return o;
}
struct FOut { @location(0) color: vec4<f32>, @location(1) diag: vec4<f32>, }
@fragment fn fs_main(i: VOut, @builtin(front_facing) ff: bool) -> FOut {
    var s: SurfaceIn;
    s.wpos = i.wpos; s.wnrm = i.wnrm; s.opos = i.opos; s.fib = i.fib; s.col = i.col; s.uv = i.uv; s.glow = i.glow;
    s.item = i.item; s.front_facing = ff; s.pixel = i.pos.xy;
    s.uv_dx = @UVDX@(i.uv); s.uv_dy = @UVDY@(i.uv);
    s.fib_dx = @DPDX@(i.fib); s.fib_dy = @DPDY@(i.fib);
    let o = shade_main_ex(s);
    if (o.kill) { discard; }
    var out: FOut;
    out.color = vec4<f32>(o.color.rgb, 1.0);
    out.diag = vec4<f32>(part.part_id, select(0.0, 1.0, ff), o.alpha, 1.0);
    return out;
}
"""


def tone_map(img):
    """exp2(exposure = 0), Khronos PBR Neutral, sRGB (COMPOSITE_FS without outlines and dither)."""
    with np.errstate(all="ignore"):
        c = np.asarray(img, np.float32).copy()
        x = c.min(-1, keepdims=True)
        off = np.where(x < 0.08, x - 6.25 * x * x, 0.04).astype(np.float32)
        c = c - off
        peak = c.max(-1, keepdims=True)
        start = np.float32(0.8 - 0.04)
        d = np.float32(1.0) - start
        newp = 1.0 - d * d / (peak + d - start)
        c2 = c * (newp / peak)
        g = 1.0 - 1.0 / (0.15 * (peak - newp) + 1.0)
        c2 = c2 + (newp - c2) * g
        c = np.where(peak < start, c, c2)
        c = np.clip(c, 0.0, 1.0)
        lin = c * 12.92
        srgb = 1.055 * np.power(c, np.float32(1 / 2.4)) - 0.055
        return np.where(c >= 0.0031308, srgb, lin).astype(np.float32)


class WG:
    def __init__(self, size, adapter_name=None, deriv="auto", aniso=8, backend="Vulkan"):
        import wgpu
        self.wgpu = wgpu
        self.size, self.aniso = size, aniso
        ad = None
        for a in wgpu.gpu.enumerate_adapters_sync():
            if (adapter_name is None or adapter_name.lower() in a.summary.lower()) and a.info.get("backend_type") == backend:
                ad = a
                break
        if ad is None:
            raise RuntimeError(f"no wgpu adapter {adapter_name!r} on {backend}")
        self.summary = ad.summary
        self.dev = ad.request_device_sync()
        d = self.dev
        # "auto" = what GL's implicit derivatives do on NVIDIA: texture LOD from coarse quad differences, dFdx/fwidth fine
        uv_d, fib_d = ("dpdxCoarse", "dpdxFine") if deriv == "auto" else (deriv, deriv)
        wgsl = (WGSL_DIR / "vertex.wgsl").read_text(encoding="utf-8") + (WGSL_DIR / "shading.wgsl").read_text(
            encoding="utf-8") + WRAPPER.replace("@DPDX@", fib_d).replace(
            "@DPDY@", fib_d.replace("dpdx", "dpdy")).replace("@UVDX@", uv_d).replace(
            "@UVDY@", uv_d.replace("dpdx", "dpdy"))
        self.module = d.create_shader_module(code=wgsl)
        TU, BU, SS = wgpu.TextureUsage, wgpu.BufferUsage, wgpu.ShaderStage
        F, VF = SS.FRAGMENT, SS.VERTEX | SS.FRAGMENT
        bgl0 = d.create_bind_group_layout(entries=[{"binding": 0, "visibility": VF, "buffer": {"type": "uniform"}}])
        tex = lambda b, st, vd="2d": {"binding": b, "visibility": F, "texture": {"sample_type": st, "view_dimension": vd}}
        smp = lambda b: {"binding": b, "visibility": F, "sampler": {"type": "filtering"}}
        bgl1 = d.create_bind_group_layout(entries=[
            {"binding": 0, "visibility": F, "buffer": {"type": "uniform"}},
            tex(1, "unfilterable-float"), tex(2, "float"), tex(3, "float", "2d-array"), tex(4, "float"),
            smp(5), smp(6), smp(7)])
        self.bgl0, self.bgl1 = bgl0, bgl1
        layout = d.create_pipeline_layout(bind_group_layouts=[bgl0, bgl1])
        fmts = [("float32x3", 0), ("float32x3", 12), ("float32x3", 24), ("float32x3", 36), ("float32", 48),
                ("float32x4", 52), ("float32x2", 68)]
        bufs = [{"array_stride": 76, "attributes": [{"format": f, "offset": o, "shader_location": i}
                                                      for i, (f, o) in enumerate(fmts)]},
                {"array_stride": 36, "attributes": [{"format": "float16x4", "offset": 8 * k, "shader_location": 7 + k}
                                                      for k in range(4)] + [
                    {"format": "float32", "offset": 32, "shader_location": 11}]},
                {"array_stride": 4, "attributes": [{"format": "float32", "offset": 0, "shader_location": 12}]}]
        self.pipe = d.create_render_pipeline(
            layout=layout,
            vertex={"module": self.module, "entry_point": "vs_main", "buffers": bufs},
            primitive={"topology": "triangle-list", "cull_mode": "none", "front_face": "ccw"},
            depth_stencil={"format": "depth32float", "depth_write_enabled": True, "depth_compare": "less"},
            fragment={"module": self.module, "entry_point": "fs_main",
                      "targets": [{"format": "rgba32float"}, {"format": "rgba32float"}]})
        self.TU, self.BU = TU, BU
        self.color = d.create_texture(size=(size, size, 1), format="rgba32float",
                                      usage=TU.RENDER_ATTACHMENT | TU.COPY_SRC)
        self.diag = d.create_texture(size=(size, size, 1), format="rgba32float",
                                     usage=TU.RENDER_ATTACHMENT | TU.COPY_SRC)
        self.depth = d.create_texture(size=(size, size, 1), format="depth32float", usage=TU.RENDER_ATTACHMENT)
        self.s_ao = d.create_sampler(address_mode_u="clamp-to-edge", address_mode_v="clamp-to-edge",
                                     mag_filter="linear", min_filter="linear")
        self.s_env = d.create_sampler(address_mode_u="repeat", address_mode_v="clamp-to-edge",
                                      mag_filter="linear", min_filter="linear")
        self.s_tex = d.create_sampler(address_mode_u="repeat", address_mode_v="repeat", mag_filter="linear",
                                      min_filter="linear", mipmap_filter="linear", max_anisotropy=aniso)

    def _upload(self, arr, fmt, size, layers=1, mips=None):
        d = self.dev
        TU = self.TU
        if mips is None:
            mips = [arr]
        t = d.create_texture(size=(size[0], size[1], layers), format=fmt, mip_level_count=len(mips),
                             dimension="2d", usage=TU.TEXTURE_BINDING | TU.COPY_DST)
        for lvl, a in enumerate(mips):
            a = np.ascontiguousarray(a)
            h, w = (a.shape[-3], a.shape[-2]) if layers > 1 else (a.shape[0], a.shape[1])
            bpp = a.dtype.itemsize * a.shape[-1]
            d.queue.write_texture({"texture": t, "mip_level": lvl, "origin": (0, 0, 0)}, a,
                                  {"offset": 0, "bytes_per_row": w * bpp, "rows_per_image": h}, (w, h, layers))
        return t

    def render(self, parts, draws, ao, items, spec, tex_levels, white_only=False):
        """draws: [(part index, dict)]; returns (color (h, w, 4), diag (h, w, 4)), top row first."""
        d, wgpu, BU = self.dev, self.wgpu, self.BU
        size = self.size
        t_items = self._upload(items.astype(np.float32), "rgba32float", (items.shape[1], items.shape[0]))
        t_ao = self._upload(np.ascontiguousarray(ao[::-1]), "rgba16float", (size, size))     # top-left row order
        t_spec = self._upload(spec, "rgba16float", (SPEC_W, SPEC_H), layers=ROUGH_LAYERS)
        t_tex = self._upload(None, "rgba8unorm-srgb", (tex_levels[0].shape[1], tex_levels[0].shape[0]),
                             mips=tex_levels)
        t_white = self._upload(np.full((1, 1, 4), 255, np.uint8), "rgba8unorm-srgb", (1, 1))
        v = lambda t, **k: t.create_view(**k)
        enc = d.create_command_encoder()
        rp = enc.begin_render_pass(
            color_attachments=[
                {"view": v(self.color), "clear_value": (0, 0, 0, 0), "load_op": "clear", "store_op": "store"},
                {"view": v(self.diag), "clear_value": (0, 0, 0, 0), "load_op": "clear", "store_op": "store"}],
            depth_stencil_attachment={"view": v(self.depth), "depth_clear_value": 1.0, "depth_load_op": "clear",
                                      "depth_store_op": "store"})
        rp.set_pipeline(self.pipe)
        keep = []
        for pi, dct in draws:
            gp = parts[pi]
            shade = pack_shading_uniforms(dct)
            b1 = d.create_buffer_with_data(data=shade, usage=BU.UNIFORM)
            b0 = d.create_buffer_with_data(data=self.part_bytes(dct, pi + 1), usage=BU.UNIFORM)
            textured = dct.get("u_has_tex", 0) == 1
            bg0 = d.create_bind_group(layout=self.bgl0, entries=[{"binding": 0, "resource": {"buffer": b0}}])
            bg1 = d.create_bind_group(layout=self.bgl1, entries=[
                {"binding": 0, "resource": {"buffer": b1}},
                {"binding": 1, "resource": v(t_items)},
                {"binding": 2, "resource": v(t_ao)},
                {"binding": 3, "resource": v(t_spec, dimension="2d-array")},
                {"binding": 4, "resource": v(t_tex if textured else t_white)},
                {"binding": 5, "resource": self.s_ao}, {"binding": 6, "resource": self.s_env},
                {"binding": 7, "resource": self.s_tex}])
            keep += [b0, b1, bg0, bg1]
            rp.set_bind_group(0, bg0)
            rp.set_bind_group(1, bg1)
            rp.set_vertex_buffer(0, gp["vbo"])
            rp.set_vertex_buffer(1, gp["abo"])
            rp.set_vertex_buffer(2, gp["ivbo"])
            rp.set_index_buffer(gp["ibo"], "uint32")
            rp.draw_indexed(gp["n"], 1, 0, 0, 0)
        rp.end()
        out = []
        bufs = []
        for t in (self.color, self.diag):
            b = d.create_buffer(size=size * size * 16, usage=BU.COPY_DST | BU.MAP_READ)
            enc.copy_texture_to_buffer({"texture": t}, {"buffer": b, "bytes_per_row": size * 16, "rows_per_image": size},
                                       (size, size, 1))
            bufs.append(b)
        d.queue.submit([enc.finish()])
        for b in bufs:
            b.map_sync(wgpu.MapMode.READ)
            out.append(np.frombuffer(b.read_mapped(), np.float32).reshape(size, size, 4).copy())
            b.unmap()
        return out

    @staticmethod
    def part_bytes(dct, part_id):
        f32 = lambda x: np.asarray(x, np.float32)
        nm = f32(dct["u_nmat"]).T                                  # columns of the normal matrix
        cols = np.zeros((3, 4), np.float32)
        cols[:, :3] = nm
        aw = f32(dct.get("u_aw", np.zeros(4)))
        ag = f32(dct.get("u_ag", np.zeros(4)))
        head = np.concatenate([f32(dct["u_model"]).T.reshape(-1), cols.reshape(-1), f32(dct["u_viewproj"]).T.reshape(-1),
                               aw, ag]).astype(np.float32)
        tail = np.array([dct.get("u_weight", 0.0), dct.get("u_anim", 0), dct.get("u_anim_t", 0.0), part_id],
                        dtype=np.float32)
        tail_b = tail.tobytes()
        tail_i = np.array([dct.get("u_anim", 0)], np.int32).tobytes()
        return head.tobytes() + tail_b[:4] + tail_i + tail_b[8:]

    def make_mesh(self, mesh, item):
        d, BU = self.dev, self.BU
        mk = lambda a, u: d.create_buffer_with_data(data=np.ascontiguousarray(a).tobytes(), usage=u)
        return {"vbo": mk(mesh.vertex_block(), BU.VERTEX), "abo": mk(mesh.anim_block().view(np.uint8), BU.VERTEX),
                "ivbo": mk(np.full(len(mesh.pos), float(item), np.float32), BU.VERTEX),
                "ibo": mk(mesh.idx, BU.INDEX), "n": mesh.idx.size}


# ---------------------------------------------------------------------------------------------------------------
# metrics

def compare(gl_img, wg_img, diag, label=""):
    """Errors in 1/255 units after tone mapping, over pixels covered in both images."""
    cov_g, cov_w = gl_img[..., 3] > 0.5, wg_img[..., 3] > 0.5
    both = cov_g & cov_w
    res = {"case": label, "covered_gl": int(cov_g.sum()), "covered_wgpu": int(cov_w.sum()),
           "only_gl": int((cov_g & ~cov_w).sum()), "only_wgpu": int((cov_w & ~cov_g).sum())}
    fin_g = np.isfinite(gl_img[..., :3]).all(-1)
    fin_w = np.isfinite(wg_img[..., :3]).all(-1)
    res["nonfinite_gl"] = int((cov_g & ~fin_g).sum())
    res["nonfinite_wgpu"] = int((cov_w & ~fin_w).sum())
    ok = both & fin_g & fin_w
    res["compared"] = int(ok.sum())
    raw = np.abs(gl_img[..., :3] - wg_img[..., :3]).max(-1)
    a, b = tone_map(gl_img[..., :3]), tone_map(wg_img[..., :3])
    err = np.abs(a - b).max(-1) * 255.0
    err = np.where(ok, err, 0.0)
    if ok.any():
        res["max_err"] = float(err[ok].max())
        res["mean_err"] = float(err[ok].mean())
        res["pct_over_1"] = float(100.0 * (err[ok] > 1.0).mean())
        res["pct_over_2"] = float(100.0 * (err[ok] > 2.0).mean())
        res["max_raw_linear"] = float(raw[ok].max())
    else:
        res.update(max_err=float("nan"), mean_err=float("nan"), pct_over_1=float("nan"), pct_over_2=float("nan"))
    # edge pixels: a neighbour in the 3x3 block is uncovered or belongs to another part
    pid = np.where(cov_w, diag[..., 0], -1)
    edge = np.zeros_like(ok)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            edge |= np.roll(np.roll(pid, dy, 0), dx, 1) != pid
    edge |= np.roll(np.roll(cov_g, 1, 0), 0, 1) != cov_g
    for e_name, m in (("edge", ok & edge), ("interior", ok & ~edge)):
        res[f"max_err_{e_name}"] = float(err[m].max()) if m.any() else float("nan")
        res[f"mean_err_{e_name}"] = float(err[m].mean()) if m.any() else float("nan")
        res[f"n_{e_name}"] = int(m.sum())
    order = np.argsort(err.reshape(-1))[::-1][:5]
    worst = []
    for o in order:
        y, x = divmod(int(o), err.shape[1])
        if err[y, x] <= 0:
            break
        worst.append({"x": x, "y": y, "err": round(float(err[y, x]), 3), "part": int(diag[y, x, 0]),
                      "front": bool(diag[y, x, 1] > 0.5), "edge": bool(edge[y, x]),
                      "gl": [round(float(c), 5) for c in gl_img[y, x, :3]],
                      "wgpu": [round(float(c), 5) for c in wg_img[y, x, :3]]})
    res["worst"] = worst
    by_part = {}
    for p in np.unique(diag[..., 0][ok]):
        m = ok & (diag[..., 0] == p)
        by_part[int(p)] = {"n": int(m.sum()), "max": round(float(err[m].max()), 3), "mean": round(float(err[m].mean()), 4)}
    res["by_part"] = by_part
    return res


def front_facing_probe(gl, wg):
    """One CCW triangle in clip space (y up), plus its mirror: do gl_FrontFacing and @builtin(front_facing) agree?"""
    ctx = gl.ctx
    prog = ctx.program(vertex_shader="#version 410 core\nin vec2 p; void main(){gl_Position=vec4(p,0.5,1.0);}",
                       fragment_shader="#version 410 core\nout vec4 o; void main(){o=vec4(gl_FrontFacing?1.0:0.0,0,0,1);}")
    tri = np.array([-0.8, -0.8, 0.8, -0.8, 0.0, 0.8, -0.8, 0.9, 0.8, 0.9, 0.0, -0.1], np.float32)   # CCW, then CW
    vao = ctx.vertex_array(prog, [(ctx.buffer(tri.tobytes()), "2f", "p")])
    gl.fbo.use()
    gl.fbo.clear(0, 0, 0, 0)
    ctx.disable(gl.mgl.DEPTH_TEST)
    vao.render(gl.mgl.TRIANGLES)
    g = np.frombuffer(gl.fbo.read(components=4, dtype="f4"), np.float32).reshape(gl.size, gl.size, 4)[::-1]
    d = wg.dev
    src = """
@vertex fn vs(@location(0) p: vec2<f32>) -> @builtin(position) vec4<f32> { return vec4<f32>(p, 0.5, 1.0); }
@fragment fn fs(@builtin(front_facing) ff: bool) -> @location(0) vec4<f32> { return vec4<f32>(select(0.0, 1.0, ff), 0.0, 0.0, 1.0); }
"""
    m = d.create_shader_module(code=src)
    pipe = d.create_render_pipeline(
        layout="auto", vertex={"module": m, "entry_point": "vs", "buffers": [
            {"array_stride": 8, "attributes": [{"format": "float32x2", "offset": 0, "shader_location": 0}]}]},
        primitive={"topology": "triangle-list", "cull_mode": "none", "front_face": "ccw"},
        fragment={"module": m, "entry_point": "fs", "targets": [{"format": "rgba32float"}]})
    vb = d.create_buffer_with_data(data=tri.tobytes(), usage=wg.BU.VERTEX)
    enc = d.create_command_encoder()
    rp = enc.begin_render_pass(color_attachments=[{"view": wg.color.create_view(), "clear_value": (0, 0, 0, 0),
                                                   "load_op": "clear", "store_op": "store"}])
    rp.set_pipeline(pipe)
    rp.set_vertex_buffer(0, vb)
    rp.draw(6)
    rp.end()
    b = d.create_buffer(size=gl.size * gl.size * 16, usage=wg.BU.COPY_DST | wg.BU.MAP_READ)
    enc.copy_texture_to_buffer({"texture": wg.color}, {"buffer": b, "bytes_per_row": gl.size * 16,
                                                       "rows_per_image": gl.size}, (gl.size, gl.size, 1))
    d.queue.submit([enc.finish()])
    b.map_sync(wg.wgpu.MapMode.READ)
    w = np.frombuffer(b.read_mapped(), np.float32).reshape(gl.size, gl.size, 4).copy()
    b.unmap()
    cov = g[..., 3] > 0.5
    covw = w[..., 3] > 0.5
    return {"gl_front_px": int((g[..., 0] > 0.5)[cov].sum()), "wgpu_front_px": int((w[..., 0] > 0.5)[covw].sum()),
            "gl_back_px": int((g[..., 0] < 0.5)[cov].sum()), "wgpu_back_px": int((w[..., 0] < 0.5)[covw].sum()),
            "mismatch_px": int(((g[..., 0] > 0.5) != (w[..., 0] > 0.5))[cov & covw].sum())}


# ---------------------------------------------------------------------------------------------------------------

LAST_IMAGES = {}                                     # case -> (gl, wgpu, diag) of the last run, for debugging


def run(size=512, adapter=None, case_names=None, scale=1.0, seed=7, deriv="auto", aniso=8, probe=True, gl_aniso=None,
        gl_literal=False):
    cases = make_cases()
    names = case_names or list(cases)
    wg = WG(size, adapter, deriv=deriv, aniso=aniso)       # first: adapter enumeration touches the WGL current context
    gl = GL(size, literal=gl_literal)
    rng = np.random.default_rng(seed)
    meshes = build_meshes(scale, seed)
    tex8 = make_texture(rng)
    gl_tex, levels = gl.texture_chain(tex8)
    gl_tex.anisotropy = float(aniso if gl_aniso is None else gl_aniso)
    gl_tex.repeat_x = gl_tex.repeat_y = True
    assert gl_tex.filter == (gl.mgl.LINEAR_MIPMAP_LINEAR, gl.mgl.LINEAR)
    results = []
    out = {"gl": gl.info, "wgpu": wg.summary, "size": size, "aniso": aniso, "derivatives": deriv,
           "triangles": {k: m.tris for k, m in meshes.items()}}
    if probe:
        out["front_facing_probe"] = front_facing_probe(gl, wg)
    items = np.zeros((3, 8, 4), np.float32)                 # row 0: id+1, selected, highlight, x-ray
    for i in range(8):
        items[0, i] = (i + 1, 0.0, 0.0 if i % 2 else 0.25, 0.0)
        items[1, i] = ((0.2 + 0.1 * i) % 1.0, 0.7 - 0.05 * i, 0.3 + 0.08 * i, 1.0 if i % 2 == 0 else 0.0)
        items[2, i] = (1.0 - 0.1 * i, 0.8, 0.45, 1.0)
    for name in names:
        case = cases[name]
        sh, spec = gl.set_env(case["studio"])
        ao = make_ao(np.random.default_rng(seed + 1), size, case["ao"][0])
        parts = []
        for k, (mname, matrix, look_kw, extra) in enumerate(case["parts"]):
            lk = make_look(look_kw, 0)
            parts.append(Part(meshes[mname], matrix, lk, k, **extra))
        frame = case_uniforms(case, parts, size)
        frame["settings"].ao_direct = case["ao"][1] if "ao_direct" not in case["settings"] else frame["settings"].ao_direct
        env_stub = types.SimpleNamespace(sh=sh, spec=types.SimpleNamespace(layers=ROUGH_LAYERS, use=lambda *a: None),
                                         use=lambda *a: None)
        draws = [(i, part_uniforms(frame, p, env_stub, None)) for i, p in enumerate(parts)]
        gl_vaos = [gl.make_vao(p.mesh, p.item) for p in parts]
        wg_meshes = [wg.make_mesh(p.mesh, p.item) for p in parts]
        gl_img = gl.render(gl_vaos, draws, ao, items, gl_tex, None)
        wg_img, diag = wg.render(wg_meshes, draws, ao, items, spec, levels)
        LAST_IMAGES[name] = (gl_img, wg_img, diag)
        res = compare(gl_img, wg_img, diag, name)
        res["triangles"] = sum(p.mesh.tris for p in parts)
        results.append(res)
    out["cases"] = results
    return out


def print_table(out):
    print(f"GL: {out['gl']} | wgpu: {out['wgpu']} | {out['size']}x{out['size']} | aniso {out['aniso']}"
          f"| {out['derivatives']}")
    if "front_facing_probe" in out:
        print("front-facing probe:", out["front_facing_probe"])
    print(f"{'case':14s} {'tris':>5s} {'cmp px':>7s} {'max':>7s} {'mean':>8s} {'%>1':>7s} {'%>2':>7s} "
          f"{'maxEdge':>8s} {'maxInt':>7s} {'onlyGL':>6s} {'onlyWG':>6s} {'nan g/w':>8s}")
    for r in out["cases"]:
        print(f"{r['case']:14s} {r['triangles']:5d} {r['compared']:7d} {r['max_err']:7.3f} {r['mean_err']:8.4f} "
              f"{r['pct_over_1']:7.3f} {r['pct_over_2']:7.3f} {r['max_err_edge']:8.3f} {r['max_err_interior']:7.3f} "
              f"{r['only_gl']:6d} {r['only_wgpu']:6d} {r['nonfinite_gl']:3d}/{r['nonfinite_wgpu']:<3d}")
        for w in r["worst"][:2]:
            print(f"    worst: {w}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--adapter", default=None, help="substring of the wgpu adapter name (NVIDIA, Intel)")
    ap.add_argument("--cases", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--deriv", default="auto", choices=["auto", "dpdx", "dpdxFine", "dpdxCoarse"],
                    help="derivative flavour in the wrapper (auto: coarse for uv, fine for the stripe coordinate)")
    ap.add_argument("--gl-literal", action="store_true", help="GL reference shader exactly as shipped (discard before fwidth)")
    ap.add_argument("--aniso", type=int, default=8)
    ap.add_argument("--gl-aniso", type=int, default=None, help="GL anisotropy if different (diagnostics)")
    ap.add_argument("--scale", type=float, default=1.0, help="mesh tessellation scale")
    a = ap.parse_args(argv)
    out = run(a.size, a.adapter, a.cases.split(",") if a.cases else None, a.scale, deriv=a.deriv, aniso=a.aniso, gl_aniso=a.gl_aniso,
              gl_literal=a.gl_literal)
    print_table(out)
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main()
