"""Offscreen rendering with a standalone moderngl context (no window).

    python -m viewer --render V1 --out v1.png [--size 1920x1080] [--state teased] [--time 2.37] model.glb
"""
from __future__ import annotations

import time
from pathlib import Path

import moderngl
import numpy as np

from .camera import OrbitCamera
from .model import Model
from .renderer import Renderer, Settings


def setup_camera(model: Model, cam: OrbitCamera, view: str | None, aspect: float):
    lo, hi = model.world_bounds(visible_only=False)
    cam.scene_centre = (lo + hi) / 2
    cam.scene_radius = max(float(np.linalg.norm(hi - lo)) / 2, 1e-3)
    rec = model.cameras.get(view) if view else None
    if rec:
        cam.set_view(rec, animate=False)
        return rec
    cam.fit(lo, hi, aspect, animate=False)
    return None


def render_to_png(glb, out, view=None, size=(1920, 1080), state=None, t=None, settings: Settings | None = None,
                  ctx=None, model=None, renderer=None, verbose=True):
    t0 = time.perf_counter()
    own_ctx = ctx is None
    if ctx is None:
        ctx = moderngl.create_standalone_context(require=410)
    model = model or Model(glb)
    t_load = time.perf_counter() - t0
    r = renderer or Renderer(ctx)
    if renderer is None:
        r.set_model(model)
    cam = OrbitCamera()
    w, h = size
    rec = setup_camera(model, cam, view, w / h)
    if state is None and rec:
        state = rec.get("state")
    clip_t = model.clip_range[0] if t is None else float(t)
    model.evaluate(clip_t, state if state and state != "assembled" else None, 1.0)
    fbo = ctx.framebuffer([ctx.renderbuffer((w, h), 4)])
    s = settings or Settings()
    t1 = time.perf_counter()
    for _ in range(3):                 # the screen-space bounce reads the previous frame: let it settle
        r.render(fbo, (w, h), cam, s)
    img = r.read_final(fbo, (w, h))
    ctx.finish()
    t_render = time.perf_counter() - t1
    from PIL import Image
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(out)
    fbo.release()
    if verbose:
        print(f"rendered {view or 'fit'} ({state or 'assembled'}, t={clip_t:.3f}) {w}x{h} -> {out}  "
              f"load {t_load:.2f} s, render {t_render:.2f} s")
    if own_ctx and renderer is None:
        r.release_model()
    return img
