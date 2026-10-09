"""A model-viewer session driven the way the app drives it: the real ModelViewport widget (app/viewer/viewport.py),
its own frame path (_paint_frame: camera, animation, frame_state, evaluate, renderer.render, label recompute), at
2560x1600 physical pixels with device pixel ratio 2 and default user settings.

The model is prepared through the app's own chain (app.viewer.model_loading.prepare_model: decode_local_npz, the
model build, lod.build). Decode and lod.build are timed by wrapping those two module functions at run time.
"""
from __future__ import annotations

import math
import time

import numpy as np

from . import perfkit as pk

LOGICAL_W, LOGICAL_H = pk.PHYS_W // pk.DPR, pk.PHYS_H // pk.DPR


def library_ids():
    from app.viewer.catalog import load_catalog
    return list(load_catalog())


def timed_prepare(model_id):
    """(entry, model, timings) with the app's prepare chain. Times in seconds."""
    from app.load_control import LoadToken
    from app.viewer.catalog import load_catalog
    from app.viewer.model_loading import prepare_model
    import app.variants.local_runtime as lr
    import app.viewer.lod as lodmod
    entry = load_catalog()[model_id]
    t = {"decode_s": 0.0, "lod_build_s": 0.0}
    o_dec, o_lod = lr.decode_local_npz, lodmod.build

    def dec(*a, **k):
        t0 = time.perf_counter()
        try:
            return o_dec(*a, **k)
        finally:
            t["decode_s"] += time.perf_counter() - t0

    def lod_build(*a, **k):
        t0 = time.perf_counter()
        try:
            return o_lod(*a, **k)
        finally:
            t["lod_build_s"] += time.perf_counter() - t0

    lr.decode_local_npz, lodmod.build = dec, lod_build
    mem0 = pk.memory()
    t0 = time.perf_counter()
    try:
        model = prepare_model(entry, LoadToken())
    finally:
        lr.decode_local_npz, lodmod.build = o_dec, o_lod
    t["prepare_total_s"] = time.perf_counter() - t0
    t["prepare_other_s"] = t["prepare_total_s"] - t["decode_s"] - t["lod_build_s"]
    t["rss_before_mb"] = mem0["rss_mb"]
    t["rss_after_prepare_mb"] = pk.memory()["rss_mb"]
    return entry, model, {k: round(v, 3) for k, v in t.items()}


def model_stats(model):
    lod = getattr(model, "lod", None) or {}
    levels = [len({id(a): 1 for a in l.indices}) for l in lod.values()]      # distinct level arrays per part
    lod_tris = sum(len(a) // 3 for l in lod.values() for a in l.indices)
    return {
        "triangles": int(model.triangle_count), "vertices": int(len(model.vertices)), "parts": len(model.parts),
        "items": len(model.items), "kind": getattr(model, "kind", None),
        "animated": bool(model.anim_vertices is not None or getattr(model, "animation", None) is not None
                         or model.clip is not None),
        "lod_parts": len(lod), "lod_levels_per_part": (max(levels) if levels else 0),
        "lod_extra_index_triangles": int(lod_tris),
        "vertex_array_bytes_cpu": int(model.vertices.nbytes), "index_array_bytes_cpu": int(model.indices.nbytes),
    }


class ViewerSession:
    """Open `model` in a real ModelViewport and expose paint / probe helpers."""

    def __init__(self, entry, model, settings=None, backend="opengl", renderer_factory=None):
        self.backend = backend
        if backend == "wgpu":
            return self._init_wgpu(entry, model, settings, renderer_factory)
        if backend != "opengl":
            raise ValueError(f"backend must be opengl or wgpu, not {backend!r}")
        from app.config import DEFAULT_SETTINGS
        from app.state import SceneState
        from app.viewer.dataset import ModelDataset
        from app.viewer.renderer import Renderer
        from app.viewer.viewport import ModelViewport
        self.entry, self.model = entry, model
        self.settings = dict(DEFAULT_SETTINGS if settings is None else settings)
        self.upload = {}
        # time the GPU upload (set_model + finish): wrap Renderer.set_model for this session only
        orig = Renderer.set_model
        up = self.upload

        def set_model(r, m):
            g0 = pk.gpu_used_mib()[0]
            t0 = time.perf_counter()
            orig(r, m)
            r.ctx.finish()
            up["upload_s"] = round(time.perf_counter() - t0, 3)
            up["gpu_used_before_mib"], up["gpu_used_after_mib"] = g0, pk.gpu_used_mib()[0]
        Renderer.set_model = set_model
        try:
            self.state = SceneState(ModelDataset(model), self.settings)
            self.w = ModelViewport(model, self.state, self.settings, entry)
            # what ModelView does when it opens a model (app/ui/model_view.py: __init__, _fully_visible)
            cut = getattr(model, "cutaway", None)
            if cut is not None:
                from app.viewer.procedural import cutaway_planes
                self.w.cut_planes = cutaway_planes(cut)
                self.w.cut_on = False
            self.state.opaque_materials = model.kind == "procedural"
            self.state.part_alpha = np.ones(len(model.items), dtype=np.float32)
            self.w.resize(LOGICAL_W, LOGICAL_H)
            self.w.reset_view(animate=False)
            t0 = time.perf_counter()
            self.w.grabFramebuffer()                     # creates the GL context, uploads the model, first frame
            self.first_grab_s = time.perf_counter() - t0
        finally:
            Renderer.set_model = orig
        w = self.w
        self.error = w.graphics_error
        self.ctx = w.ctx
        self.r = w.renderer
        self.dpr = w.devicePixelRatioF()
        self.physical = w._physical_size()
        self.render_size = w._render_size()
        self.probe = None
        self.lights_log = []

    def _init_wgpu(self, entry, model, settings, renderer_factory=None):
        """The same widget logic on the wgpu backend: WgpuModelViewport, painted into a physical-size texture."""
        from app.config import DEFAULT_SETTINGS
        from app.state import SceneState
        from app.viewer.dataset import ModelDataset
        from app.gpu.viewport import WgpuModelViewport
        from app.gpu.device import get_gpu
        self.entry, self.model = entry, model
        self.settings = dict(DEFAULT_SETTINGS if settings is None else settings)
        self.upload = {}
        self.gpu = get_gpu()
        self.state = SceneState(ModelDataset(model), self.settings)
        self.w = WgpuModelViewport(model, self.state, self.settings, entry, gpu=self.gpu,
                                  renderer_factory=renderer_factory)
        cut = getattr(model, "cutaway", None)
        if cut is not None:
            from app.viewer.procedural import cutaway_planes
            self.w.cut_planes = cutaway_planes(cut)
            self.w.cut_on = False
        self.state.opaque_materials = model.kind == "procedural"
        self.state.part_alpha = np.ones(len(model.items), dtype=np.float32)
        self.w.resize(LOGICAL_W, LOGICAL_H)
        self.w.reset_view(animate=False)
        t0 = time.perf_counter()
        self.w._init_backend()                       # creates the device objects and uploads the model
        self.first_grab_s = self.upload["upload_s"] = time.perf_counter() - t0
        w = self.w
        self.error = w.graphics_error
        self.ctx = w.ctx
        self.r = w.renderer
        self.dpr = w.devicePixelRatioF()
        self.physical = w._physical_size()
        self.render_size = w._render_size()
        self.probe = None
        self.lights_log = []
        self.gl_renderer = str(self.gpu.info)
        self._target = None if self.error else w._offscreen_begin(*self.physical)

    # ------------------------------------------------------------------ facts about the buffers
    def buffer_facts(self):
        r, m = self.r, self.model
        n = max(len(m.vertices), 1)
        return {
            "bytes_per_vertex": round(r.vbo.size / n, 2), "vbo_mib": round(r.vbo.size / 2**20, 1),
            "ibo_mib": round(r.ibo.size / 2**20, 1), "item_vbo_mib": round(r.item_vbo.size / 2**20, 1),
            "anim_vbo_mib": round(r.abo.size / 2**20, 1) if r.abo is not None else 0.0,
            "msaa_samples_used": int(self.w.rsettings.msaa), "render_size": list(self.render_size),
            "device_pixel_ratio": self.dpr, "physical_size": list(self.physical),
            "target_mib": self.target_mib(),
        }

    def target_mib(self):
        # moderngl textures/renderbuffers expose width/height/components/samples; estimate bytes from them
        total = 0
        for v in self.r.t.values():
            comp = getattr(v, "components", None)
            size = getattr(v, "size", None)
            if comp is None or not isinstance(size, tuple):
                continue
            dtype = getattr(v, "dtype", "f1")
            bpc = {"f1": 1, "f2": 2, "f4": 4, "u1": 1, "u2": 2, "u4": 4, "i1": 1, "i2": 2, "i4": 4}.get(dtype, 4)
            samples = max(1, getattr(v, "samples", 1) or 1)
            total += size[0] * size[1] * comp * bpc * samples
        return round(total / 2**20, 1)

    # ------------------------------------------------------------------ probe
    def attach_probe(self):
        from .perfkit import GlProbe
        scopes = {"_render_shadows": "shadow", "_render_caps": "caps", "_capmix": "capmix"}
        self.probe = GlProbe(self.ctx, self.r, ("vaos.",), scopes)
        self.probe.install()
        if self.w._fbo is not None:
            self.probe.fbo_names[id(self.w._fbo)] = "target"
        self._names = sorted(set(self.probe.vao_names.values()))
        # world-space light directions the renderer used (camera-relative rig?)
        orig = type(self.r)._light_uniforms
        log = self.lights_log
        probe = self.probe

        def light_uniforms(r, u, V, campos, lights, s, size, camera):
            if len(log) < 400:
                log.append((float(camera.yaw), [np.asarray(l[0]).copy() for l in lights]))
            return orig(r, u, V, campos, lights, s, size, camera)
        type(self.r)._light_uniforms = light_uniforms
        self._orig_light = orig

    def detach_probe(self):
        if self.probe is not None:
            self.probe.uninstall()
            self.probe = None
            type(self.r)._light_uniforms = self._orig_light

    # ------------------------------------------------------------------ frames
    def paint(self, probe=False):
        """One frame through the widget's own _paint_frame, then ctx.finish(). Returns a dict (ms, and the probe's
        counters when probe=True and a probe is attached)."""
        if self.backend == "wgpu":
            return self._paint_wgpu()
        w, ctx = self.w, self.ctx
        use_probe = probe and self.probe is not None
        w.makeCurrent()                          # Qt does this before paintGL; pick_at leaves the context released
        if use_probe:
            self.probe.begin_frame()
        t0 = time.perf_counter()
        w._paint_frame()
        t1 = time.perf_counter()
        if use_probe:
            self.probe.end_frame()
        ctx.finish()
        t2 = time.perf_counter()
        out = {"submit_ms": (t1 - t0) * 1000.0, "wall_ms": (t2 - t0) * 1000.0}
        if use_probe:
            out.update(self.probe.frame_result())
        if ctx.error != "GL_NO_ERROR":
            out["gl_error"] = ctx.error
        return out

    def _paint_wgpu(self):
        """One frame through the widget's own _paint_frame into the physical-size texture, then wait for the GPU."""
        from app.gpu.device import wait_idle
        w = self.w
        t0 = time.perf_counter()
        w._target = self._target
        try:
            w._paint_frame()
        finally:
            w._target = None
        t1 = time.perf_counter()
        wait_idle(self.gpu)
        t2 = time.perf_counter()
        return {"submit_ms": (t1 - t0) * 1000.0, "wall_ms": (t2 - t0) * 1000.0}

    def make_current(self):
        self.w.makeCurrent()

    def done_current(self):
        self.w.doneCurrent()

    def warm(self, n=3):
        for _ in range(n):
            self.paint()

    def orbit_run(self, frames=120, step_deg=3.0, probe=False):
        """A user dragging: the camera turns step_deg per frame about the vertical axis, _press held (so labels stay
        dirty and no hover pick runs), one repaint per step."""
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

    def settle(self, probe=False):
        """The first frame after the drag ends (the label anchors are recomputed here), then an idle repaint."""
        a = self.paint(probe=probe)
        b = self.paint(probe=probe)
        return a, b

    def pick_samples(self, n=10, probe=False):
        from PySide6.QtCore import QPointF
        w = self.w
        out = []
        for i in range(n):
            pos = QPointF(LOGICAL_W * (0.35 + 0.03 * i), LOGICAL_H * (0.45 + 0.02 * i))
            if probe and self.probe is not None:
                self.probe.begin_frame()
            t0 = time.perf_counter()
            w.pick_at(pos)
            self.ctx.finish()
            row = {"wall_ms": (time.perf_counter() - t0) * 1000.0}
            if probe and self.probe is not None:
                self.probe.end_frame()
                row.update({k: v for k, v in self.probe.frame_result().items() if k in ("readbacks", "readback_ms",
                                                                                         "readback_bytes", "draws_total")})
            out.append(row)
        return out

    def light_follow_report(self):
        """Do the world-space light directions change when the camera turns? (camera-relative rig = they do)"""
        if len(self.lights_log) < 2:
            return None
        ys, first = None, None
        by = {}
        for yaw, ls in self.lights_log:
            by.setdefault(round(yaw, 3), ls)
        keys = sorted(by)
        a, b = by[keys[0]], by[keys[len(keys) // 2]]
        d0 = np.degrees(np.arccos(np.clip(np.dot(a[0], b[0]), -1, 1)))
        return {"yaw_a_rad": keys[0], "yaw_b_rad": keys[len(keys) // 2],
                "key_light_world_dir_a": [round(float(x), 4) for x in a[0]],
                "key_light_world_dir_b": [round(float(x), 4) for x in b[0]],
                "key_light_angle_between_deg": round(float(d0), 2),
                "yaw_change_deg": round(math.degrees(keys[len(keys) // 2] - keys[0]), 2),
                "lights_follow_camera": bool(d0 > 1.0)}

    def grab_array(self):
        """The widget's GL framebuffer as an RGB uint8 array (rows top to bottom) - the picture shown. On wgpu: one
        more frame into the physical-size texture, read back top row first."""
        if self.backend == "wgpu":
            self._paint_wgpu()
            return self.r.read_final(self._target, self.physical)
        img = self.w.grabFramebuffer()
        img = img.convertToFormat(img.Format.Format_RGBA8888)
        ptr = img.constBits()
        arr = np.frombuffer(ptr, dtype=np.uint8, count=img.sizeInBytes()).reshape(img.height(), img.bytesPerLine() // 4, 4)
        return arr[:, :img.width(), :3].copy()

    def close(self):
        if self.backend == "wgpu":
            try:
                self.w.release_gl()
                if self._target is not None:
                    self._target.destroy()
            except Exception:
                pass
            return
        self.detach_probe()
        try:
            self.w.release_gl()
        except Exception:
            pass
