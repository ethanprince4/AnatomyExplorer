"""An atlas (Z-Anatomy) session driven the way the app drives it: the real Viewport widget (app/viewport.py) and its
renderer (app/renderer.py) at 2560x1600 physical pixels, device pixel ratio 2, default user settings. The frame path is
Viewport.paintGL (camera update, renderer.render, landmarks, structure labels, radiology anchors)."""
from __future__ import annotations

import time

import numpy as np

from . import perfkit as pk
from .viewer_session import LOGICAL_H, LOGICAL_W


class AtlasSession:
    def __init__(self, settings_override=None):
        from app.config import DATA_DIR, DEFAULT_SETTINGS
        from app.data import Dataset
        from app.state import SceneState
        import app.viewport as vp
        self.settings = dict(DEFAULT_SETTINGS)
        self.settings.update(settings_override or {})
        t0 = time.perf_counter()
        mem0 = pk.memory()["rss_mb"]
        self.ds = Dataset(DATA_DIR)
        self.load = {"dataset_s": round(time.perf_counter() - t0, 3)}
        self.state = SceneState(self.ds, self.settings)
        # time geometry decode and GPU upload inside the widget's own initializeGL
        o_geo, o_ren = type(self.ds).load_geometry, vp.Renderer
        load = self.load

        def load_geometry(ds):
            t = time.perf_counter()
            out = o_geo(ds)
            load["load_geometry_s"] = round(time.perf_counter() - t, 3)
            return out

        def renderer(ctx, *a, **k):
            g0 = pk.gpu_used_mib()[0]
            t = time.perf_counter()
            r = o_ren(ctx, *a, **k)
            ctx.finish()
            load["upload_s"] = round(time.perf_counter() - t, 3)
            load["gpu_used_before_mib"], load["gpu_used_after_mib"] = g0, pk.gpu_used_mib()[0]
            return r

        type(self.ds).load_geometry = load_geometry
        vp.Renderer = renderer
        try:
            self.w = vp.Viewport(self.ds, self.state, self.settings)
            self.w.resize(LOGICAL_W, LOGICAL_H)
            self.w.reset_view(animate=False)
            t = time.perf_counter()
            self.w.grabFramebuffer()
            self.load["first_frame_incl_context_s"] = round(time.perf_counter() - t, 3)
        finally:
            type(self.ds).load_geometry = o_geo
            vp.Renderer = o_ren
        self.load["rss_before_mb"], self.load["rss_after_mb"] = mem0, pk.memory()["rss_mb"]
        self.ctx, self.r = self.w.ctx, self.w.renderer
        self.probe = None

    def facts(self):
        r, ds = self.r, self.ds
        nv = max(r.vbo.size // 28, 1)
        tris = r.ibo.size // 12
        return {"structures": ds.n, "triangles": int(tris), "vertices": int(nv),
                "bytes_per_vertex": round(r.vbo.size / nv, 2), "vbo_mib": round(r.vbo.size / 2**20, 1),
                "ibo_mib": round(r.ibo.size / 2**20, 1), "physical_size": list(self.w._physical_size()),
                "device_pixel_ratio": self.w.devicePixelRatioF(), "render_size": list(r.size),
                "msaa": "none (the atlas renderer has no multisampled target; it uses FXAA)"}

    def attach_probe(self):
        self.probe = pk.GlProbe(self.ctx, self.r, ("vao_",), {"_draw_caps": "caps"})
        self.probe.install()
        self.probe.fbo_names[id(self.w._fbo)] = "target"

    def detach_probe(self):
        if self.probe is not None:
            self.probe.uninstall()
            self.probe = None

    def paint(self, probe=False):
        w, ctx = self.w, self.ctx
        use = probe and self.probe is not None
        w.makeCurrent()
        if use:
            self.probe.begin_frame()
        t0 = time.perf_counter()
        w.paintGL()
        t1 = time.perf_counter()
        if use:
            self.probe.end_frame()
        ctx.finish()
        t2 = time.perf_counter()
        out = {"submit_ms": (t1 - t0) * 1000.0, "wall_ms": (t2 - t0) * 1000.0}
        if use:
            out.update(self.probe.frame_result())
        if ctx.error != "GL_NO_ERROR":
            out["gl_error"] = ctx.error
        return out

    def warm(self, n=3):
        for _ in range(n):
            self.paint()

    def orbit_run(self, frames=120, step_deg=3.0, probe=False):
        from PySide6.QtCore import QPointF
        w = self.w
        w._press = QPointF(10.0, 10.0)
        out = []
        try:
            for _ in range(frames):
                w.camera.orbit(step_deg, 0.0)
                out.append(self.paint(probe=probe))
        finally:
            w._press = None
        return out

    def pick_samples(self, n=10, probe=False):
        from PySide6.QtCore import QPointF
        out = []
        for i in range(n):
            pos = QPointF(LOGICAL_W * (0.35 + 0.03 * i), LOGICAL_H * (0.45 + 0.02 * i))
            if probe and self.probe is not None:
                self.probe.begin_frame()
            t0 = time.perf_counter()
            self.w.pick_at(pos)
            self.ctx.finish()
            row = {"wall_ms": (time.perf_counter() - t0) * 1000.0}
            if probe and self.probe is not None:
                self.probe.end_frame()
                row.update({k: v for k, v in self.probe.frame_result().items()
                            if k in ("readbacks", "readback_ms", "readback_bytes", "draws_total")})
            out.append(row)
        return out

    def grab_array(self):
        img = self.w.grabFramebuffer()
        img = img.convertToFormat(img.Format.Format_RGBA8888)
        arr = np.frombuffer(img.constBits(), dtype=np.uint8, count=img.sizeInBytes())
        arr = arr.reshape(img.height(), img.bytesPerLine() // 4, 4)
        return arr[:, :img.width(), :3].copy()

    def close(self):
        self.detach_probe()
