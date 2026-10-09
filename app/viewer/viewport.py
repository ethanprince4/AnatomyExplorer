"""The model viewer's 3D view on OpenGL: the new renderer, driven exactly like the atlas.

The backend independent behaviour lives in ViewportCore (viewport_core.py); this file only holds the QOpenGLWidget parts.
The wgpu twin is app/gpu/viewport.py.


Mouse, trackpad and keyboard work as they do in the atlas viewport (app/viewport.py) and read the same Settings:
which button orbits and which pans, the sensitivities and inversions, zoom toward the cursor, orbit around the
cursor, the trackpad gestures (TrackpadInput is shared), click / Ctrl+click / double-click / right-click, the
back and forward mouse buttons, and the camera commands the main window routes here (views 1/3/7, F, Home, arrow
keys, zoom keys, auto-rotate, measure).

Labels follow the atlas's method as well - a name on a card, a leader line to a dot on the structure, cards that
never overlap, names whose anchor is hidden behind something drawn faded, a cut face labelled around the edge of
the view like an atlas plate - with one refinement for models: every anchor is placed on the part of the structure
that is actually visible from where you are looking (the pixel deepest inside its visible region, found from the
renderer's id buffer once the camera comes to rest), so a label never points at the back of a structure or at
something in front of it.
"""
from __future__ import annotations

import time

import moderngl
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from ..viewport import VIEWS, Overlay, TrackpadInput          # noqa: F401  (re-exported: callers import them from here)
from .renderer import FrameState, Renderer, Settings          # noqa: F401
from .viewport_core import (SECTION_AXES, SECTION_NAMES, ViewportCore, _annotation_plate, _hex_rgb,   # noqa: F401
                            _smooth, distinct_colours, msaa_samples)


class ModelViewport(ViewportCore, QOpenGLWidget):
    def __init__(self, model, state, settings, entry=None, parent=None):
        QOpenGLWidget.__init__(self, parent)
        self._fbo = None
        self._fbo_id = None
        self._init_core(model, state, settings, entry)

    # ------------------------------------------------------------------ GL lifecycle
    def initializeGL(self):
        self._init_backend()

    def _init_backend(self):
        started = time.perf_counter()
        self.startup_timings = {}
        self.interactive_ready = False
        self.graphics_error = ""
        self._labels_dirty = True
        self._warm_label_cache = None
        self._fbo = self._fbo_id = None
        try:
            self.ctx = moderngl.create_context()
            self.renderer = Renderer(self.ctx)
            self.renderer.set_model(self.model)
            self.gl_info = f"{self.ctx.info['GL_RENDERER']} · OpenGL {self.ctx.info['GL_VERSION'].split(' ')[0]}"
            self.startup_timings["graphics_prepare_seconds"] = time.perf_counter() - started
            self.glReady.emit()
        except Exception as exc:
            self.graphics_error = f"Could not prepare graphics: {exc}"
            self.graphicsFailed.emit(self.graphics_error)

    def paintGL(self):
        self._paint_checked()

    # ------------------------------------------------------------------ backend hooks (the GL halves)
    def _frame_target(self):
        fid = self.defaultFramebufferObject()
        if self._fbo is None or fid != self._fbo_id:
            self._fbo = self.ctx.detect_framebuffer(fid)
            self._fbo_id = fid
        return self._fbo

    def _gpu_finish(self):
        self.ctx.finish()

    def _on_renderer_released(self):
        self._fbo = self._fbo_id = None

    def _make_current(self):
        self.makeCurrent()

    def _done_current(self):
        self.doneCurrent()

    def _offscreen_begin(self, w, h):
        self._grab_rb = self.ctx.renderbuffer((w, h), 4)
        return self.ctx.framebuffer([self._grab_rb])

    def _offscreen_end(self, target):
        target.release()
        self._grab_rb.release()
        self._grab_rb = None
