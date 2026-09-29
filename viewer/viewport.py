"""The 3D viewport widget: a QOpenGLWidget that drives the Renderer, the orbit camera and the clip."""
from __future__ import annotations

import math
import time

import moderngl
import numpy as np
from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from .camera import OrbitCamera
from .model import Model
from .renderer import Renderer, Settings


def smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


class Viewport(QOpenGLWidget):
    partPicked = Signal(object)          # Part or None
    timeChanged = Signal(float)          # clip time
    playingChanged = Signal(bool)
    stateChanged = Signal(str)
    frameTimed = Signal(float)           # ms per frame
    glReady = Signal(str)
    visibilityChanged = Signal()         # a view record changed which parts are shown

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(320, 200)
        self.ctx = None
        self.renderer: Renderer | None = None
        self.model: Model | None = None
        self._pending_model = None
        self.camera = OrbitCamera()
        self.settings = Settings()
        self._fbo = None
        self._fbo_id = None
        # clip and states
        self.clip_t = 0.0
        self.playing = False
        self.loop = True
        self.speed = 1.0
        self.reveal_state = None         # name of the non-assembled state being shown
        self.reveal_amount = 0.0
        self.reveal_target = 0.0
        # interaction
        self._press = None
        self._press_pos = None
        self._last_pos = None
        self._moved = False
        self._settle = 0
        self._last_t = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.setInterval(8)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    # ------------------------------------------------------------------ GL
    def initializeGL(self):
        self.ctx = moderngl.create_context()
        self.renderer = Renderer(self.ctx)
        self.glReady.emit(self.renderer.gl_info)
        if self._pending_model is not None:
            m, self._pending_model = self._pending_model, None
            self._install(m)

    def paintGL(self):
        if self.renderer is None:
            return
        t0 = time.perf_counter()
        w, h = self._physical_size()
        fid = self.defaultFramebufferObject()
        if self._fbo is None or fid != self._fbo_id:
            self._fbo = self.ctx.detect_framebuffer(fid)
            self._fbo_id = fid
        if self.model is not None:
            self.model.evaluate(self.clip_t, self.reveal_state, smooth(self.reveal_amount))
        self.renderer.render(self._fbo, (w, h), self.camera, self.settings)
        self.frameTimed.emit((time.perf_counter() - t0) * 1000.0)

    def _physical_size(self):
        dpr = self.devicePixelRatioF()
        return max(int(self.width() * dpr), 2), max(int(self.height() * dpr), 2)

    def aspect(self):
        w, h = self._physical_size()
        return w / h

    # ------------------------------------------------------------------ model
    def set_model(self, model: Model):
        if self.renderer is None:
            self._pending_model = model
            return
        self._install(model)

    def _install(self, model: Model):
        self.makeCurrent()
        try:
            self.renderer.set_model(model)
        finally:
            self.doneCurrent()
        self.model = model
        self.settings.selected = self.settings.hovered = 0
        lo, hi = model.world_bounds(visible_only=False)
        self.camera.scene_centre = (lo + hi) / 2
        self.camera.scene_radius = max(float(np.linalg.norm(hi - lo)) / 2, 1e-3)
        self.clip_t = model.clip_range[0]
        self.playing = False
        self.reveal_state, self.reveal_amount, self.reveal_target = None, 0.0, 0.0
        start = model.sidecar.get("start_view")
        start = start if start in model.cameras else ("V1" if "V1" in model.cameras else None)
        if start:
            self.camera.set_view(model.cameras[start], animate=False)
            self.apply_view_visibility(model.cameras[start])
        else:
            self.camera.fov_deg = 39.597753
            self.camera.ortho = False
            self.camera.goal.yaw, self.camera.goal.pitch = math.radians(145.0), math.radians(28.0)
            self.camera.fit(lo, hi, self.aspect(), animate=False)
        self.timeChanged.emit(self.clip_t)
        self.playingChanged.emit(False)
        self.stateChanged.emit("assembled")
        self.kick()

    def kick(self, frames=3):
        self._settle = max(self._settle, frames)
        self.update()

    # ------------------------------------------------------------------ clip and states
    def set_playing(self, on):
        if self.model is None or self.model.clip is None:
            on = False
        if on and self.clip_t >= self.model.clip_range[1] - 1e-6:
            self.clip_t = self.model.clip_range[0]
        self.playing = bool(on)
        self.playingChanged.emit(self.playing)
        self.kick()

    def set_time(self, t):
        if self.model is None:
            return
        t0, t1 = self.model.clip_range
        self.clip_t = min(max(float(t), t0), t1)
        self.timeChanged.emit(self.clip_t)
        self.kick()

    def show_state(self, name):
        if self.model is None:
            return
        if name == "assembled" or name not in self.model.states or not self.model.states[name]["offsets"]:
            self.reveal_target = 0.0
        else:
            if self.reveal_state != name and self.reveal_amount > 0:
                self.reveal_amount = 0.0
            self.reveal_state = name
            self.reveal_target = 1.0
        self.stateChanged.emit(name)
        self.kick()

    def _tick(self):
        now = time.perf_counter()
        dt = min(now - self._last_t, 0.1)
        self._last_t = now
        busy = False
        if self.camera.update(dt):
            busy = True
            self._settle = 3
        if self.playing and self.model is not None and self.model.clip is not None:
            t0, t1 = self.model.clip_range
            t = self.clip_t + dt * self.speed
            if t > t1:
                if self.loop:
                    t = t0 + (t - t1) % max(t1 - t0, 1e-6)
                else:
                    t = t1
                    self.playing = False
                    self.playingChanged.emit(False)
            self.clip_t = t
            self.timeChanged.emit(t)
            busy = True
            self._settle = 3
        if abs(self.reveal_amount - self.reveal_target) > 1e-4:
            step = dt / 0.9
            self.reveal_amount += max(-step, min(step, self.reveal_target - self.reveal_amount))
            if self.reveal_target == 0.0 and self.reveal_amount <= 1e-4:
                self.reveal_amount = 0.0
                self.reveal_state = None
            busy = True
            self._settle = 3
        if busy or self._settle > 0:
            if not busy:
                self._settle -= 1
            self.update()

    # ------------------------------------------------------------------ picking
    def pick(self, pos: QPoint):
        if self.renderer is None or self.model is None:
            return None, None
        dpr = self.devicePixelRatioF()
        self.makeCurrent()
        try:
            pid, point = self.renderer.pick(pos.x() * dpr, pos.y() * dpr)
        finally:
            self.doneCurrent()
        part = next((p for p in self.model.parts if p.id == pid), None) if pid else None
        return part, point

    def select(self, part):
        self.settings.selected = part.id if part is not None else 0
        self.partPicked.emit(part)
        self.kick()

    def focus_part(self, part, point=None):
        c, r = self.model.part_sphere(part)
        r = min(r, self.camera.scene_radius * 0.25)
        self.camera.focus(point if point is not None else c, max(r, 0.3), self.aspect())
        self.kick()

    def fit(self):
        if self.model is None:
            return
        lo, hi = self.model.world_bounds(visible_only=True)
        self.camera.fit(lo, hi, self.aspect())
        self.kick()

    def set_view(self, name):
        if self.model is None or name not in self.model.cameras:
            return
        rec = self.model.cameras[name]
        self.camera.set_view(rec, zoom_path=self.model.sidecar.get("view_transition") == "zoom")
        self.apply_view_visibility(rec)
        want = rec.get("state")
        self.show_state(want if want else "assembled")
        self.kick()

    def apply_view_visibility(self, rec):
        """Opt-in: a view record that lists parts to hide ("hidden": node names) shows every other part. A record
        without the key leaves visibility as it is."""
        if self.model is None or "hidden" not in rec:
            return
        hide = set(rec.get("hidden") or [])
        for p in self.model.parts:
            p.visible = p.name not in hide
        self.visibilityChanged.emit()
        self.kick()

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, e):
        self._press = e.button()
        self._press_pos = e.position().toPoint()
        self._last_pos = e.position().toPoint()
        self._moved = False
        self.setFocus()

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self._press is None:
            part, _ = self.pick(pos)
            hid = part.id if part is not None else 0
            if hid != self.settings.hovered:
                self.settings.hovered = hid
                self.setCursor(Qt.PointingHandCursor if hid else Qt.ArrowCursor)
                self.kick(1)
            return
        d = pos - self._last_pos
        self._last_pos = pos
        if (pos - self._press_pos).manhattanLength() > 3:
            self._moved = True
        if self._press == Qt.LeftButton and not (e.modifiers() & Qt.ShiftModifier):
            self.camera.orbit(d.x(), d.y())
        else:
            w, h = self._physical_size()
            dpr = self.devicePixelRatioF()
            self.camera.pan(d.x() * dpr, d.y() * dpr, h, w / h)
        self.kick()

    def mouseReleaseEvent(self, e):
        if self._press == Qt.LeftButton and not self._moved:
            part, _ = self.pick(e.position().toPoint())
            self.select(part)
        self._press = None

    def mouseDoubleClickEvent(self, e):
        part, point = self.pick(e.position().toPoint())
        if part is not None:
            self.select(part)
            self.focus_part(part, point)

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        _, point = self.pick(e.position().toPoint())
        self.camera.zoom(steps, toward=point if steps > 0 else None)
        self.kick()

    def leaveEvent(self, e):
        if self.settings.hovered:
            self.settings.hovered = 0
            self.kick(1)

    # ------------------------------------------------------------------ screenshot
    def grab_image(self, scale=1.0):
        """Render the current view offscreen at ``scale`` x the widget size; returns an (h, w, 3) uint8 array."""
        if self.renderer is None:
            return None
        w, h = self._physical_size()
        w, h = int(w * scale), int(h * scale)
        self.makeCurrent()
        try:
            rb = self.ctx.renderbuffer((w, h), 4)
            fbo = self.ctx.framebuffer([rb])
            if self.model is not None:
                self.model.evaluate(self.clip_t, self.reveal_state, smooth(self.reveal_amount))
            hov = self.settings.hovered
            self.settings.hovered = 0
            for _ in range(3):
                self.renderer.render(fbo, (w, h), self.camera, self.settings)
            self.settings.hovered = hov
            img = self.renderer.read_final(fbo, (w, h)).copy()
            fbo.release()
            rb.release()
        finally:
            self.doneCurrent()
        self.kick()
        return img
