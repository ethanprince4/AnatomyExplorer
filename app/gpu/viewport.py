"""WgpuModelViewport: the model viewer's 3D view on wgpu.

All behaviour (camera, input, labels, overlay painting, animation, measuring) comes from ViewportCore, shared with the
OpenGL ModelViewport. This class only supplies the wgpu halves of the hooks: it creates the renderer from a factory,
hands the host texture to ``renderer.render`` as the frame target, and renders three frames into an offscreen texture
for ``grab_image``. Any failure (no adapter, no renderer module, a renderer or first-frame exception) is reported with
the same ``graphicsFailed`` signal and ``graphics_error`` text as the OpenGL viewport.
"""
from __future__ import annotations

import time

from ..viewer.viewport_core import ViewportCore, _smooth
from .device import GpuUnavailable, get_gpu, wait_idle
from .host import OUTPUT_FORMAT, OUTPUT_USAGE, GpuWidget


def default_renderer_factory(gpu):
    """The real renderer, imported lazily so a missing or broken app.gpu.renderer cannot stop the application."""
    from .renderer import WgpuRenderer
    return WgpuRenderer(gpu)


class WgpuModelViewport(ViewportCore, GpuWidget):
    def __init__(self, model, state, settings, entry=None, parent=None, renderer_factory=None, present_mode=None,
                 gpu=None):
        GpuWidget.__init__(self, parent, present_mode, gpu)
        self._renderer_factory = renderer_factory or default_renderer_factory
        self._drew = False
        self._init_core(model, state, settings, entry)
        self.render_callback = self._render_into

    # ------------------------------------------------------------------ the QOpenGLWidget calls other code still makes
    def makeCurrent(self):
        """Nothing to make current: kept so code written for the OpenGL viewport (main_window) runs unchanged."""

    def doneCurrent(self):
        """See makeCurrent."""

    # ------------------------------------------------------------------ backend lifecycle
    def _init_backend(self):
        started = time.perf_counter()
        self.startup_timings = {}
        self.interactive_ready = False
        self.graphics_error = ""
        self._labels_dirty = True
        self._warm_label_cache = None
        try:
            gpu = self.gpu or get_gpu()
            self.gpu = gpu
            self.ctx = gpu                           # "a context exists": lets a hidden tab be restored without a new device
            self.renderer = self._renderer_factory(gpu)
            self.renderer.set_model(self.model)
            self.gl_info = str(getattr(self.renderer, "gl_info", "") or gpu.info)
            self.startup_timings["graphics_prepare_seconds"] = time.perf_counter() - started
            self.glReady.emit()
        except Exception as exc:
            self.renderer = None
            kind = "Could not prepare graphics" if not isinstance(exc, GpuUnavailable) else "Could not prepare graphics (wgpu)"
            self.graphics_error = f"{kind}: {exc}"
            self.graphicsFailed.emit(self.graphics_error)

    def probe(self):
        """Create the device and renderer now and draw one small frame; raise if anything fails. The model view calls this
        before it wires the widget up, so it can still choose the OpenGL viewport instead."""
        if self.renderer is None:
            self._init_backend()
        if self.graphics_error or self.renderer is None:
            raise RuntimeError(self.graphics_error or "renderer was not created")
        w, h = 96, 64
        tex = self.make_output_texture(w, h)
        aspect = self.camera.aspect
        try:
            self.camera.aspect = w / h
            self._sync_settings()
            m = self.model
            if m.clip is not None and self.anim_kind() == "clip":
                m.evaluate(self.anim_t, self.reveal_state, _smooth(self.reveal_amount))
            else:
                m.evaluate(m.clip_range[0], self.reveal_state, _smooth(self.reveal_amount))
            self.renderer.render(tex, (w, h), self.camera, self.rsettings, self.frame_state())
            self.renderer.read_final(tex, (w, h))
            if not self.renderer.frame_ok:
                raise RuntimeError("the first frame did not complete")
        except Exception as exc:
            self.graphics_error = f"Could not draw this model: {exc}"
            self.release_gl()
            raise RuntimeError(self.graphics_error) from exc
        finally:
            self.camera.aspect = aspect
            tex.destroy()
            self._labels_dirty = True
            self._warm_label_cache = None

    def dispose(self):
        """Throw away a viewport that was never used (a failed probe): free the GPU side and the state connections."""
        for signal, slot in ((self.state.render_changed, self._on_state),
                             (self.state.visibility_changed, self.invalidate_labels),
                             (self.state.selection_changed, self.invalidate_labels)):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        try:
            self.release_gl()
            self.release_surface()
        finally:
            self.setParent(None)
            self.deleteLater()

    def _render_into(self, texture, w, h):
        """GpuWidget render callback: one frame through the shared paint logic."""
        if self.renderer is None and self.ctx is None and not self.graphics_error:
            self._init_backend()
        self._target = texture
        self._drew = False
        try:
            self._paint_checked()
        finally:
            self._target = None
        self._drew = self.renderer is not None and not self.graphics_error and bool(getattr(self.renderer, "frame_ok", True))
        return self._drew

    def on_present_error(self, message):
        self.graphics_error = f"Could not draw this model: {message}"
        self.interactive_ready = False
        self.graphicsFailed.emit(self.graphics_error)
        super().on_present_error(message)

    # ------------------------------------------------------------------ backend hooks
    _target = None

    def _frame_target(self):
        return self._target

    def _gpu_finish(self):
        if self.gpu is not None:
            wait_idle(self.gpu)

    def _offscreen_begin(self, w, h):
        return self.gpu.device.create_texture(size=(w, h, 1), format=OUTPUT_FORMAT, usage=OUTPUT_USAGE)

    def _offscreen_end(self, target):
        target.destroy()
