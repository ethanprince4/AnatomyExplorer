"""The studio environment, generated in code at start-up (no image files).

The environment is defined in camera space (x right, y up, +z toward the viewer), like the harness light rig
that is parented to the camera, so every view is lit the same way. It is a blend of the harness's uniform grey
ambient (what the Cycles stills see) and a soft studio: a vertical gradient plus three large soft boxes.
From it we derive 9 spherical-harmonic irradiance coefficients (CPU, numpy) and a GGX-prefiltered specular
texture array (GPU, one layer per roughness step).
"""
from __future__ import annotations

import math

import moderngl
import numpy as np

from . import shaders

SPEC_W, SPEC_H = 256, 128
ROUGH_LAYERS = 6


def _dirs(w, h):
    u = (np.arange(w) + 0.5) / w
    v = (np.arange(h) + 0.5) / h
    phi = (u - 0.5) * 2.0 * math.pi
    th = v * math.pi
    P, T = np.meshgrid(phi, th)
    d = np.stack([np.sin(T) * np.sin(P), np.cos(T), -np.sin(T) * np.cos(P)], -1)
    return d, T


def _norm(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


SOFTBOXES = (  # camera-space direction, angular radius (deg), radiance, softness
    (_norm((0.35, 0.80, 0.50)), 28.0, 0.9, 0.35),   # overhead, behind the camera: broad top sheen
    (_norm((-0.85, 0.15, 0.50)), 16.0, 0.45, 0.4),  # left fill strip
    (_norm((0.25, 0.45, -0.85)), 20.0, 0.6, 0.4),   # rim strip behind the subject
)


def make_env(w=512, h=256, studio=0.35, ambient=0.15):
    """Equirect radiance (h, w, 3) float32 in camera space."""
    d, _ = _dirs(w, h)
    y = d[..., 1]
    t = np.clip((y + 0.6) / 1.4, 0.0, 1.0)
    t = t * t * (3 - 2 * t)
    grad = 0.07 + 0.16 * t
    boxes = np.zeros_like(y)
    for c, rad_deg, L, soft in SOFTBOXES:
        ang = np.degrees(np.arccos(np.clip(d @ c, -1.0, 1.0)))
        e0, e1 = rad_deg * (1.0 - soft), rad_deg
        f = np.clip((e1 - ang) / max(e1 - e0, 1e-3), 0.0, 1.0)
        boxes += L * f * f * (3 - 2 * f)
    studio_L = grad + boxes
    L = (1.0 - studio) * ambient + studio * studio_L
    # a hint of warmth from above and coolness from below keeps greys from looking dead
    tint = np.stack([1.0 + 0.03 * y, np.ones_like(y), 1.0 - 0.03 * y], -1)
    return (L[..., None] * tint).astype(np.float32)


def sh9_irradiance(env):
    """Pre-scaled SH9 irradiance coefficients (9, 3) for the shader's polynomial."""
    h, w, _ = env.shape
    d, T = _dirs(w, h)
    dw = (2 * math.pi / w) * (math.pi / h) * np.sin(T)
    x, y, z = d[..., 0], d[..., 1], d[..., 2]
    basis = [np.full_like(x, 0.282095), 0.488603 * y, 0.488603 * z, 0.488603 * x,
             1.092548 * x * y, 1.092548 * y * z, 0.315392 * (3 * z * z - 1), 1.092548 * x * z,
             0.546274 * (x * x - y * y)]
    const = [0.282095, 0.488603, 0.488603, 0.488603, 1.092548, 1.092548, 0.315392, 1.092548, 0.546274]
    band = [math.pi] + [2 * math.pi / 3] * 3 + [math.pi / 4] * 5
    out = np.zeros((9, 3))
    for k in range(9):
        Lk = (env * (basis[k] * dw)[..., None]).sum((0, 1))
        out[k] = band[k] * const[k] * Lk
    return out.astype(np.float32)


class Environment:
    """GPU resources: the prefiltered specular texture array and the SH9 coefficients."""

    def __init__(self, ctx, studio=0.35, ambient=0.15):
        self.ctx = ctx
        self.spec = None
        self.sh = None
        self._prog = ctx.program(vertex_shader=shaders.FSQ_VS, fragment_shader=shaders.PREFILTER_FS)
        self._vao = ctx.vertex_array(self._prog, [])
        self.rebuild(studio, ambient)

    def rebuild(self, studio, ambient):
        ctx = self.ctx
        env = make_env(studio=studio, ambient=ambient)
        self.sh = sh9_irradiance(env)
        h, w, _ = env.shape
        src = ctx.texture((w, h), 3, np.ascontiguousarray(env).tobytes(), dtype="f4")
        src.repeat_x, src.repeat_y = True, False
        src.build_mipmaps()
        src.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        dst = ctx.texture((SPEC_W, SPEC_H), 4, dtype="f4")
        fbo = ctx.framebuffer(color_attachments=[dst])
        layers = []
        src.use(0)
        self._prog["u_src"].value = 0
        self._prog["u_src_w"].value = float(w)
        for i in range(ROUGH_LAYERS):
            r = i / (ROUGH_LAYERS - 1)
            fbo.use()
            ctx.viewport = (0, 0, SPEC_W, SPEC_H)
            self._prog["u_rough"].value = r
            self._vao.render(mode=moderngl.TRIANGLES, vertices=3)
            layers.append(np.frombuffer(fbo.read(components=4, dtype="f4"), dtype=np.float32)
                          .reshape(SPEC_H, SPEC_W, 4))
        arr = np.stack(layers, 0).astype(np.float16)
        if self.spec is not None:
            self.spec.release()
        self.spec = ctx.texture_array((SPEC_W, SPEC_H, ROUGH_LAYERS), 4, arr.tobytes(), dtype="f2")
        self.spec.repeat_x, self.spec.repeat_y = True, False
        fbo.release()
        dst.release()
        src.release()

