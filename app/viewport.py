import math
import sys
import time

import moderngl
import numpy as np
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QInputDevice, QPainter, QPainterPath, QPen
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget

from .camera import OrbitCamera
from .renderer import Renderer
from .ui import theme

VIEWS = {
    "anterior": (0.0, 0.0),
    "posterior": (math.pi, 0.0),
    "right": (-math.pi / 2, 0.0),
    "left": (math.pi / 2, 0.0),
    "superior": (0.0, math.radians(89.0)),
    "inferior": (0.0, -math.radians(89.0)),
}


class TrackpadInput:
    """Wheel events and touchpad gestures, shared by the atlas viewport and the model viewer.

    A notched mouse wheel zooms, exactly as it always has. A laptop trackpad is told apart from it and mapped the
    way 3D apps usually do: two-finger swipe orbits (or pans - Settings), Shift + swipe does the other one, pinch
    zooms toward the cursor, the macOS rotate gesture turns the model about the vertical axis and smart zoom (a
    two-finger double tap) frames the selection, then goes home on the next one.

    How each platform reports a trackpad:
    - macOS: every trackpad scroll carries a phase (begin / update / end / momentum); a mouse wheel never does.
      Pinch, rotate and smart zoom arrive as QNativeGestureEvents.
    - Linux (X11, Wayland): trackpad scrolls come with a pixelDelta, wheels without; pinch is a native gesture.
    - Windows precision touchpads: small angleDelta steps that are not multiples of the wheel's 120, and a pinch
      becomes Ctrl + wheel. A high-resolution wheel mouse can look the same, hence the Mouse / Trackpad override.

    The owner provides camera, settings, update(), devicePixelRatioF() and height(), and may define
    gesture_zoom_point(pos) -> world point or None and gesture_home()."""

    LATCH = 0.3          # s: an event this soon after a trackpad one belongs to the same gesture
    PIVOT_HOLD = 0.3     # s: a pinch keeps zooming toward the point it started on

    def __init__(self, owner):
        self.owner = owner
        self._last_pad = -1.0
        self._pivot = None
        self._pivot_time = -1.0
        self.framed = False          # smart zoom toggles between the framed selection and home

    # ------------------------------------------------------------------ classification
    def is_trackpad(self, e):
        mode = str(self.owner.settings.get("trackpad_mode", "Auto"))
        if mode == "Mouse":
            return False
        if mode == "Trackpad":
            return True
        now = time.perf_counter()
        pad = self._looks_like_trackpad(e)
        if not pad and now - self._last_pad < self.LATCH:
            pad = True                   # a precision touchpad can send an exact 120 in mid-swipe
        if pad:
            self._last_pad = now
        return pad

    @staticmethod
    def _looks_like_trackpad(e):
        if e.phase() != Qt.NoScrollPhase:
            return True                  # macOS trackpads (and Magic Mouse), Wayland touchpads
        dev = e.device()
        if dev is not None and dev.type() == QInputDevice.DeviceType.TouchPad:
            return True
        if sys.platform == "darwin":
            return False                 # macOS gives a plain wheel a pixelDelta too
        if not e.pixelDelta().isNull():
            return True
        if sys.platform == "win32":
            a = e.angleDelta()
            return a.x() % 120 != 0 or a.y() % 120 != 0
        return False

    # ------------------------------------------------------------------ wheel
    def wheel(self, e):
        s = self.owner.settings
        if not self.is_trackpad(e):
            self._mouse_wheel(e)
            return
        if e.phase() == Qt.ScrollMomentum:
            # the glide after the fingers lift: nice for scrolling a page, but in a 3D view it keeps turning the
            # model after you stopped, which makes it hard to stop on the view you wanted
            return
        if e.modifiers() & Qt.ControlModifier:
            self._pinch_wheel(e)             # Windows turns a pinch into Ctrl + wheel
            return
        d = e.pixelDelta()
        if d.isNull():
            a = e.angleDelta()
            d = QPointF(a.x() * 0.5, a.y() * 0.5)      # 120 = one wheel notch, about 60 px of scrolling
        else:
            d = QPointF(d)
        if d.x() == 0 and d.y() == 0:
            return
        k = float(s.get("trackpad_swipe_sensitivity", 1.0))
        if s.get("trackpad_invert"):
            k = -k
        pan = str(s.get("trackpad_swipe", "Orbit")) == "Pan"
        if e.modifiers() & Qt.ShiftModifier:
            pan = not pan
        c = self.owner.camera
        if pan:
            dpr = self.owner.devicePixelRatioF()
            kp = float(s.get("pan_sensitivity", 1.0)) * k
            c.pan(d.x() * dpr * kp, d.y() * dpr * kp, self.owner.height() * dpr)
        else:
            ko = float(s.get("orbit_sensitivity", 0.35)) * k
            c.orbit(d.x() * ko, d.y() * ko)
        self.framed = False
        self.owner.update()

    def _mouse_wheel(self, e):
        s = self.owner.settings
        steps = e.angleDelta().y() / 120.0
        if steps == 0:
            return
        if s.get("invert_zoom"):
            steps = -steps
        factor = 0.87 ** (steps * float(s.get("zoom_sensitivity", 1.0)))
        point = self._zoom_point(e.position(), hold=False)
        self.owner.camera.dolly(factor, point)
        self.framed = False
        self.owner.update()

    def _pinch_wheel(self, e):
        a = e.angleDelta()
        steps = (a.y() or a.x()) / 120.0
        if steps:
            self.zoom(0.87 ** (steps * float(self.owner.settings.get("trackpad_pinch_sensitivity", 1.0))),
                      e.position())

    # ------------------------------------------------------------------ gestures
    def zoom(self, factor, pos):
        self.owner.camera.dolly(factor, self._zoom_point(pos, hold=True))
        self.framed = False
        self.owner.update()

    def _zoom_point(self, pos, hold):
        if not self.owner.settings.get("zoom_to_cursor", True):
            return None
        fn = getattr(self.owner, "gesture_zoom_point", None)
        if fn is None:
            return None
        if not hold:
            return fn(pos)
        now = time.perf_counter()
        if now - self._pivot_time > self.PIVOT_HOLD:
            self._pivot = fn(pos)            # one pick per pinch, not one per frame
        self._pivot_time = now
        return self._pivot

    def native(self, e):
        """Handle a QNativeGestureEvent; returns True when it was used."""
        g = e.gestureType()
        s = self.owner.settings
        if g == Qt.ZoomNativeGesture:
            # value is the change in magnification since the last event: +0.01 is 1 % bigger
            v = float(e.value()) * float(s.get("trackpad_pinch_sensitivity", 1.0))
            if v:
                self.zoom(math.exp(-v), e.position())
            return True
        if g == Qt.RotateNativeGesture:
            v = float(e.value())               # degrees, anticlockwise positive
            if v:
                self.owner.camera.orbit(-v * float(s.get("trackpad_swipe_sensitivity", 1.0)), 0.0)
                self.framed = False
                self.owner.update()
            return True
        if g == Qt.SmartZoomNativeGesture:
            fn = getattr(self.owner, "gesture_home", None)
            if fn is not None:
                fn(self)
            return True
        if g in (Qt.BeginNativeGesture, Qt.EndNativeGesture):
            self._pivot_time = -1.0
            return True
        return False


class Overlay(QWidget):
    def __init__(self, viewport):
        super().__init__(viewport)
        self.vp = viewport
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        try:
            self.vp.paint_overlay(p)
        finally:
            p.end()


class Viewport(QOpenGLWidget):
    structureClicked = Signal(int, object)
    structureDoubleClicked = Signal(int)
    hoverChanged = Signal(int)
    contextMenuRequested = Signal(int, QPoint)
    frameTimed = Signal(float)
    glReady = Signal()
    historyRequested = Signal(int)
    measureChanged = Signal(str)

    def __init__(self, ds, state, settings, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.state = state
        self.settings = settings
        self.camera = OrbitCamera(settings.get("fov", 32.0))
        self.renderer = None
        self.ctx = None
        self._fbo = None
        self._fbo_id = None
        self._state_dirty = True
        self.clip_on = [False, False, False]
        self.clip_pos = [0.0, 0.0, 0.9]
        self.clip_flip = [False, False, False]
        self.clip_mode = 0
        self.clip_axes = [(1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)]
        self._press = None
        self._last = None
        self._button = None
        self._moved = False
        self._pivot_pending = False
        self._last_hover_pick = 0.0
        self.hover_pos = None
        self.landmark_hosts = []
        self.focus_landmark = None
        self._lm_cache = []
        self.section = None            # SectionIndex, attached by the main window
        self.section_anchors = []      # [(sid, anchor_xyz, weight)] on the current cut face
        self._section_rects = []       # screen rectangles of the drawn labels, for clicking
        self.measure_mode = False
        self.measure_scale = 1.0       # metres per model unit (micro models set their own)
        self.measure_points = []       # world points of the current measurement chain
        self.sectionChanged = None     # callback(list) so a panel can list what the cut passes through
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(320, 240)
        self.overlay = Overlay(self)
        self.auto_rotate = False
        self.touch = TrackpadInput(self)
        self.home_view = None          # what "home" means when it is not reset_view (a micro model's framing)
        self._last_frame_time = time.perf_counter()
        state.render_changed.connect(self._on_state)
        self.reset_view(animate=False)

    # ------------------------------------------------------------------ GL lifecycle
    def initializeGL(self):
        self.ctx = moderngl.create_context()
        vertices, indices = self.ds.load_geometry()
        self.renderer = Renderer(self.ctx, self.ds, vertices, indices, cap_depth=getattr(self.ds, "cap_depth", False))
        self.gl_info = f"{self.ctx.info['GL_RENDERER']} · OpenGL {self.ctx.info['GL_VERSION'].split(' ')[0]}"
        self.glReady.emit()

    def _physical_size(self):
        dpr = self.devicePixelRatioF()
        return int(self.width() * dpr), int(self.height() * dpr)

    def paintGL(self):
        if self.renderer is None:
            return
        t0 = time.perf_counter()
        dt = min(t0 - self._last_frame_time, 0.1)
        self._last_frame_time = t0
        animating = self.camera.update()
        if self.auto_rotate and self._press is None:
            self.camera.yaw += math.radians(float(self.settings.get("auto_rotate_speed", 20.0))) * dt
            animating = True
        w, h = self._physical_size()
        scale = float(self.settings.get("render_scale", 1.0))
        self.renderer.resize(max(int(w * scale), 2), max(int(h * scale), 2))
        self.renderer.screen_size = (w, h)
        if self._state_dirty:
            self.renderer.update_state(self.state.build_texture())
            self._state_dirty = False
        fbo_id = self.defaultFramebufferObject()
        if self._fbo is None or fbo_id != self._fbo_id:
            self._fbo = self.ctx.detect_framebuffer(fbo_id)
            self._fbo_id = fbo_id
        self.renderer.render(self._fbo, self.camera, self.settings, self.clip_uniforms(),
                             hover_id=self.state.hovered, has_selection=bool(self.state.selected))
        self._update_landmarks()
        self.frameTimed.emit((time.perf_counter() - t0) * 1000.0)
        self.overlay.update()
        if animating:
            self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.overlay.setGeometry(self.rect())

    def _on_state(self):
        self._state_dirty = True
        self.update()

    # ------------------------------------------------------------------ clipping
    def scene_bounds(self):
        return self.ds.scene_bbox[0], self.ds.scene_bbox[1]

    def clip_uniforms(self):
        planes = []
        normals = self.clip_axes
        for i, n in enumerate(normals):
            n = np.array(n)
            if self.clip_flip[i]:
                n = -n
            d = -float(np.dot(n, self._clip_point(i)))
            planes.append((float(n[0]), float(n[1]), float(n[2]), d))
        return planes, self.clip_on, self.clip_mode

    def _clip_point(self, i):
        p = np.zeros(3)
        p[[0, 2, 1][i]] = self.clip_pos[i]
        return p

    # ------------------------------------------------------------------ camera helpers
    def aspect(self):
        return max(self.width(), 1) / max(self.height(), 1)

    def duration(self):
        return float(self.settings.get("camera_duration", 0.55))

    def reset_view(self, animate=True):
        bmin, bmax = self.scene_bounds()
        center = (bmin + bmax) / 2
        radius = float(np.linalg.norm(bmax - bmin) / 2)
        dist = self.camera.fit_distance(radius * 0.92, self.aspect() if self.width() > 10 else 1.6)
        if animate:
            self.camera.animate_to(center, dist, 0.0, 0.0, self.duration())
        else:
            self.camera.target, self.camera.distance, self.camera.yaw, self.camera.pitch = center, dist, 0.0, 0.0
        self.update()

    def set_view(self, name):
        yaw, pitch = VIEWS[name]
        self.camera.animate_to(self.camera.target, self.camera.distance, yaw, pitch, self.duration())
        self.update()

    def frame_structures(self, sids, duration=None, view=None):
        """Frame a set of structures, optionally swinging to a named view in the same move."""
        b = self.ds.bounds_of(sids)
        if b is None:
            return
        yaw, pitch = VIEWS[view] if view in VIEWS else (None, None)
        self.camera.frame_bounds(b[0], b[1], self.aspect(), yaw=yaw, pitch=pitch,
                                 duration=self.duration() if duration is None else duration)
        self.update()

    def frame_point(self, point, radius):
        self.camera.animate_to(np.asarray(point), self.camera.fit_distance(radius, self.aspect()),
                               self.camera.yaw, self.camera.pitch, self.duration())
        self.update()

    def key_orbit(self, dx, dy):
        step = float(self.settings.get("key_orbit_step", 15.0))
        c = self.camera
        c.animate_to(c.target, c.distance, c.yaw - math.radians(dx * step),
                     max(-math.radians(89.5), min(math.radians(89.5), c.pitch + math.radians(dy * step))),
                     min(self.duration(), 0.25))
        self.update()

    def key_zoom(self, direction):
        c = self.camera
        c.animate_to(c.target, max(0.005, c.distance * (0.8 ** direction)), c.yaw, c.pitch, min(self.duration(), 0.2))
        self.update()

    def toggle_auto_rotate(self):
        self.auto_rotate = not self.auto_rotate
        self._last_frame_time = time.perf_counter()
        self.update()
        return self.auto_rotate

    # ------------------------------------------------------------------ picking
    def _gl_xy(self, pos):
        dpr = self.devicePixelRatioF()
        w, h = self._physical_size()
        scale = (self.renderer.size[0] / w) if self.renderer and self.renderer.size[0] and w else 1.0
        return int(pos.x() * dpr * scale), int((h - 1 - pos.y() * dpr) * scale)

    def pick_at(self, pos):
        if self.renderer is None:
            return -1
        self.makeCurrent()
        try:
            x, y = self._gl_xy(pos)
            sid = self.renderer.pick(x, y)
        finally:
            self.doneCurrent()
        return sid if 0 <= sid < self.ds.n else -1

    def world_at(self, pos):
        if self.renderer is None:
            return None
        self.makeCurrent()
        try:
            x, y = self._gl_xy(pos)
            return self.renderer.world_at(x, y)
        finally:
            self.doneCurrent()

    # ------------------------------------------------------------------ input
    BUTTONS = {"Left": Qt.LeftButton, "Right": Qt.RightButton, "Middle": Qt.MiddleButton}

    def section_label_at(self, pos):
        for rect, sid in self._section_rects:
            if rect.contains(pos):
                return sid
        return None

    def mousePressEvent(self, e):
        if e.button() in (Qt.BackButton, Qt.ForwardButton):
            self.historyRequested.emit(-1 if e.button() == Qt.BackButton else 1)
            return
        if e.button() == Qt.LeftButton:
            sid = self.section_label_at(e.position())
            if sid is not None:                       # clicking a section label picks that structure
                self.structureClicked.emit(int(sid), e.modifiers())
                return
            if self.measure_mode:
                hit = self.world_at(e.position())
                if hit is not None:
                    if len(self.measure_points) >= 2 and e.modifiers() & Qt.ShiftModifier:
                        pass                          # Shift keeps adding to the chain
                    elif len(self.measure_points) >= 2:
                        self.measure_points = []
                    self.measure_points.append(np.asarray(hit, dtype=np.float64))
                    self.measureChanged.emit(self.measure_text())
                    self.update()
                return
        self._press = e.position()
        self._last = e.position()
        self._button = e.button()
        self._moved = False
        self._pivot_pending = bool(self.settings.get("orbit_around_cursor")) and \
            self._button == self.BUTTONS.get(self.settings.get("orbit_button", "Left"))
        self.setFocus()

    def _repivot(self, pos):
        hit = self.world_at(pos)
        if hit is None:
            return
        c = self.camera
        c.update()
        eye = c.eye()
        offset = eye - hit
        dist = float(np.linalg.norm(offset))
        if dist < 1e-4:
            return
        c._anim = None
        c.target = hit
        c.distance = dist
        c.pitch = math.asin(max(-1.0, min(1.0, offset[1] / dist)))
        c.yaw = math.atan2(offset[0], offset[2])

    def mouseMoveEvent(self, e):
        pos = e.position()
        self.hover_pos = pos
        if self._press is not None:
            d = pos - self._last
            self._last = pos
            if (pos - self._press).manhattanLength() > 3:
                self._moved = True
            if not self._moved:
                return
            orbit_btn = self.BUTTONS.get(self.settings.get("orbit_button", "Left"), Qt.LeftButton)
            pan_btn = self.BUTTONS.get(self.settings.get("pan_button", "Right"), Qt.RightButton)
            shift = bool(e.modifiers() & Qt.ShiftModifier)
            if self._button == pan_btn or (shift and self._button == orbit_btn) or \
                    (self._button == Qt.MiddleButton and orbit_btn != Qt.MiddleButton):
                dpr = self.devicePixelRatioF()
                k = float(self.settings.get("pan_sensitivity", 1.0))
                self.camera.pan(d.x() * dpr * k, d.y() * dpr * k, self._physical_size()[1])
            elif self._button == orbit_btn:
                if self._pivot_pending:
                    self._pivot_pending = False
                    self._repivot(self._press)
                k = float(self.settings.get("orbit_sensitivity", 0.35))
                sx = -1 if self.settings.get("invert_orbit_x") else 1
                sy = -1 if self.settings.get("invert_orbit_y") else 1
                self.camera.orbit(d.x() * k * sx, d.y() * k * sy)
            if self.state.hovered != -1:
                self.state.set_hovered(-1)
                self.hoverChanged.emit(-1)
            self.update()
            return
        now = time.perf_counter()
        if now - self._last_hover_pick > 0.03:
            self._last_hover_pick = now
            sid = self.pick_at(pos)
            if sid != self.state.hovered:
                self.state.set_hovered(sid)
                self.hoverChanged.emit(sid)
        self.overlay.update()

    def mouseReleaseEvent(self, e):
        if self._press is not None and not self._moved:
            sid = self.pick_at(e.position())
            if self._button == Qt.LeftButton:
                self.structureClicked.emit(sid, e.modifiers())
            elif self._button == Qt.RightButton:
                self.contextMenuRequested.emit(sid, e.globalPosition().toPoint())
        self._press = None
        self._moved = False
        self.update()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.structureDoubleClicked.emit(self.pick_at(e.position()))

    def wheelEvent(self, e):
        self.touch.wheel(e)

    def event(self, e):
        if e.type() == QEvent.NativeGesture and self.touch.native(e):
            e.accept()
            return True
        return super().event(e)

    def gesture_zoom_point(self, pos):
        return self.world_at(pos)

    def gesture_home(self, touch):
        """Smart zoom: frame the selection, and go home on the next one (or straight home with nothing selected)."""
        if self.state.selected and not touch.framed:
            self.frame_structures(list(self.state.selected))
            touch.framed = True
        else:
            (self.home_view or self.reset_view)()
            touch.framed = False

    def leaveEvent(self, e):
        self.hover_pos = None
        if self.state.hovered != -1:
            self.state.set_hovered(-1)
            self.hoverChanged.emit(-1)

    # ------------------------------------------------------------------ overlay
    def project(self, world):
        if self.renderer is None:
            return None
        clip = self.renderer.last_vp @ np.array([world[0], world[1], world[2], 1.0])
        if clip[3] <= 1e-6:
            return None
        ndc = clip[:3] / clip[3]
        return ((ndc[0] * 0.5 + 0.5) * self.width(), (1 - (ndc[1] * 0.5 + 0.5)) * self.height(), ndc[2] * 0.5 + 0.5)

    def _update_landmarks(self):
        items = []
        if self.settings.get("show_landmarks", True):
            idxs = []
            for sid in self.landmark_hosts:
                idxs.extend(self.ds.landmarks_of.get(sid, ()))
            if self.focus_landmark is not None and self.focus_landmark not in idxs:
                idxs.append(self.focus_landmark)
            idxs = idxs[:int(self.settings.get('max_landmarks', 60))]
            vis = self.state.visible_mask()
            dpr = self.devicePixelRatioF()
            h_phys = self._physical_size()[1]
            near, far = self.camera.near_far()
            probes = []
            for i in idxs:
                lm = self.ds.landmarks[i]
                if not vis[lm["sid"]]:
                    continue
                pr = self.project(lm["anchor"])
                if pr is None or not (0 <= pr[0] < self.width() and 0 <= pr[1] < self.height()):
                    continue
                probes.append((i, pr))
            depths = []
            if probes and self._press is None:
                depths = self.renderer.depths_at([(int(pr[0] * dpr), h_phys - 1 - int(pr[1] * dpr)) for _, pr in probes])

            def lin(d):
                z = d * 2 - 1
                return 2 * near * far / (far + near - z * (far - near))

            prev = {i: occ for i, _, occ in self._lm_cache}
            for k, (i, pr) in enumerate(probes):
                if depths:
                    sd = depths[k]
                    occluded = sd is not None and sd < 1.0 and lin(pr[2]) - lin(sd) > 0.004 + 0.012 * self.camera.distance
                else:
                    occluded = prev.get(i, False)
                items.append((i, pr, occluded))
        self._lm_cache = items

    # ------------------------------------------------------------------ labelled cross-section
    CLIP_AXIS = (0, 2, 1)              # sagittal -> x, coronal -> z, transverse -> y

    def active_section(self):
        """(clip index, world axis, position) of the plane to label, or None."""
        for i in range(3):
            if self.clip_on[i]:
                return i, self.CLIP_AXIS[i], float(self.clip_pos[i])
        return None

    def refresh_section(self):
        """Recompute what the active cross-section cuts through. Cheap enough to follow the slider."""
        plane = self.active_section()
        if plane is None or self.section is None or not self.settings.get("section_labels", True):
            changed = bool(self.section_anchors)
            self.section_anchors = []
            if changed and self.sectionChanged:
                self.sectionChanged([])
            return
        if not self.section.ready:
            self.section.start()
            return
        _, axis, value = plane
        limit = int(self.settings.get("max_section_labels", 22))
        self.section_anchors = self.section.cut(axis, value, self.state.visible_mask(), limit=limit)
        if self.sectionChanged:
            self.sectionChanged(self.section_anchors)

    def _paint_section_labels(self, p, dark):
        """Lay the names out in two columns with leader lines, the way an atlas plate is labelled."""
        if not self.section_anchors:
            return
        font = QFont(self.font())
        font.setPointSizeF(float(self.settings.get("label_size", 8.6)))
        p.setFont(font)
        fm = QFontMetricsF(font)
        w, h = float(self.width()), float(self.height())
        line_h = fm.height() + 7
        margin = 12.0
        self._section_rects = []
        columns = {-1: [], 1: []}
        for sid, anchor, _weight in self.section_anchors:
            pr = self.project(anchor)
            if pr is None or not (0 <= pr[0] <= w and 0 <= pr[1] <= h):
                continue
            columns[-1 if pr[0] < w * 0.5 else 1].append((sid, pr))
        for side, items in columns.items():
            if not items:
                continue
            items.sort(key=lambda t: t[1][1])
            ys = [float(pr[1]) for _, pr in items]
            for k in range(1, len(ys)):                       # push apart downwards, then pull back on screen
                ys[k] = max(ys[k], ys[k - 1] + line_h)
            # the left column stops above the orientation gizmo in the bottom-left corner
            bottom = h - 108.0 if side < 0 and self.settings.get("show_gizmo", True) else h
            over = ys[-1] - (bottom - line_h)
            if over > 0:
                ys = [y - over for y in ys]
                for k in range(len(ys) - 2, -1, -1):
                    ys[k] = min(ys[k], ys[k + 1] - line_h)
            for (sid, pr), ly in zip(items, ys):
                ly = max(line_h * 0.6, min(bottom - line_h * 0.6, ly))
                text = self.ds.structures[sid]["name"]
                tw = min(fm.horizontalAdvance(text) + 12, w * 0.28)
                x0 = margin if side < 0 else w - margin - tw
                rect = QRectF(x0, ly - line_h / 2 + 2, tw, fm.height() + 4)
                join_x = rect.right() if side < 0 else rect.left()
                elbow_x = join_x + 16 * -side
                if (side < 0 and pr[0] < elbow_x) or (side > 0 and pr[0] > elbow_x):
                    elbow_x = pr[0]                            # anchor is already past the column
                accent = QColor(255, 214, 92) if sid in self.state.selected else QColor(120, 205, 255)
                faded = QColor(accent.red(), accent.green(), accent.blue(), 150)
                p.setPen(QPen(faded, 1.1))
                p.drawLine(QPointF(pr[0], pr[1]), QPointF(elbow_x, ly))
                p.drawLine(QPointF(elbow_x, ly), QPointF(join_x, ly))
                p.setBrush(accent)
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(pr[0], pr[1]), 2.6, 2.6)
                p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 170), 1.0))
                p.setBrush(theme.qc(theme.OVERLAY, 220) if dark else QColor(255, 255, 255, 228))
                p.drawRoundedRect(rect, 4, 4)
                p.setPen(QColor(235, 240, 245) if dark else QColor(20, 25, 30))
                p.drawText(rect, Qt.AlignCenter, fm.elidedText(text, Qt.ElideRight, tw - 10))
                self._section_rects.append((QRectF(rect), sid))

    # ------------------------------------------------------------------ measuring
    def set_measure(self, on):
        self.measure_mode = bool(on)
        if not on:
            self.measure_points = []
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)
        self.measureChanged.emit(self.measure_text())
        self.update()

    def clear_measure(self):
        self.measure_points = []
        self.measureChanged.emit(self.measure_text())
        self.update()

    def _length_text(self, units):
        if not self.measure_scale:                  # a model with no known real size: relative lengths only
            return f"{units * 50:.1f} % of the model's width"
        mm = units * self.measure_scale * 1000.0
        if mm < 1.0:
            return f"{mm * 1000:.0f} µm"
        return f"{mm:.1f} mm" if mm < 100 else f"{mm / 10:.1f} cm"

    def measure_text(self):
        pts = self.measure_points
        if not self.measure_mode:
            return ""
        if len(pts) < 2:
            return "Measuring: click two points on the model. Shift+click adds another leg; Esc clears."
        total = sum(float(np.linalg.norm(pts[i + 1] - pts[i])) for i in range(len(pts) - 1))
        direct = float(np.linalg.norm(pts[-1] - pts[0]))
        out = f"{self._length_text(total)}"
        if len(pts) > 2:
            out += f" along {len(pts) - 1} legs · {self._length_text(direct)} straight line"
            a, b, c = pts[-3], pts[-2], pts[-1]
            v1, v2 = a - b, c - b
            n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
            if n1 > 1e-9 and n2 > 1e-9:
                ang = math.degrees(math.acos(float(np.clip(np.dot(v1, v2) / (n1 * n2), -1, 1))))
                out += f" · angle {ang:.0f}°"
        return out

    def _paint_measure(self, p, dark):
        pts = self.measure_points
        if not pts:
            return
        screen = [self.project(q) for q in pts]
        if any(s is None for s in screen):
            return
        accent = QColor(255, 196, 84)
        p.setPen(QPen(accent, 1.6))
        for i in range(len(screen) - 1):
            a, b = screen[i], screen[i + 1]
            p.drawLine(QPointF(a[0], a[1]), QPointF(b[0], b[1]))
        p.setBrush(accent)
        p.setPen(Qt.NoPen)
        for sc in screen:
            p.drawEllipse(QPointF(sc[0], sc[1]), 4.0, 4.0)
        font = QFont(self.font())
        font.setPointSizeF(float(self.settings.get("label_size", 8.6)) + 0.6)
        font.setBold(True)
        p.setFont(font)
        fm = QFontMetricsF(font)
        for i in range(len(screen) - 1):
            a, b = screen[i], screen[i + 1]
            text = self._length_text(float(np.linalg.norm(pts[i + 1] - pts[i])))
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            rect = QRectF(mx - fm.horizontalAdvance(text) / 2 - 6, my - fm.height() / 2 - 12,
                          fm.horizontalAdvance(text) + 12, fm.height() + 4)
            p.setPen(QPen(accent, 1.0))
            p.setBrush(QColor(20, 16, 10, 220) if dark else QColor(255, 252, 240, 235))
            p.drawRoundedRect(rect, 4, 4)
            p.setPen(QColor(255, 226, 160) if dark else QColor(60, 40, 10))
            p.drawText(rect, Qt.AlignCenter, text)

    def paint_overlay(self, p: QPainter):
        dark = self.settings.get("dark_background", True)
        self._paint_section_labels(p, dark)
        self._paint_landmarks(p, dark)
        self._paint_measure(p, dark)
        if self.settings.get("show_gizmo", True):
            self._paint_gizmo(p, dark)
        self._paint_hover(p)

    def _paint_landmarks(self, p, dark):
        if not self._lm_cache:
            return
        font = QFont(self.font())
        font.setPointSizeF(float(self.settings.get('label_size', 8.6)))
        p.setFont(font)
        fm = QFontMetricsF(font)
        placed = []
        centers = {}
        for i, pr, occluded in sorted(self._lm_cache, key=lambda t: (t[2], t[0] != self.focus_landmark)):
            lm = self.ds.landmarks[i]
            sid = lm["sid"]
            if sid not in centers:
                c = self.project(self.ds.centroid[sid])
                centers[sid] = c
            c = centers[sid]
            ax, ay = pr[0], pr[1]
            dx, dy = (ax - c[0], ay - c[1]) if c else (1.0, -1.0)
            ln = math.hypot(dx, dy) or 1.0
            dx, dy = dx / ln, dy / ln
            focus = i == self.focus_landmark
            lx, ly = ax + dx * 46, ay + dy * 46
            text = lm["name"]
            tw = fm.horizontalAdvance(text) + 12
            th = fm.height() + 4
            rx = lx if dx >= 0 else lx - tw
            rect = QRectF(rx, ly - th / 2, tw, th)
            if focus:
                occluded = False
            alpha = 90 if occluded else 235
            dot = QColor(79, 195, 247, alpha) if not focus else QColor(255, 214, 92, 255)
            p.setPen(QPen(dot, 1.3))
            p.drawLine(QPointF(ax, ay), QPointF(lx, ly))
            p.setBrush(dot if not occluded else Qt.NoBrush)
            p.drawEllipse(QPointF(ax, ay), 3.2 if not focus else 4.5, 3.2 if not focus else 4.5)
            if any(rect.intersects(r) for r in placed) and not focus:
                continue
            placed.append(rect.adjusted(-2, -2, 2, 2))
            bg = theme.qc(theme.OVERLAY, 210 if not occluded else 110) if dark else QColor(255, 255, 255, 215 if not occluded else 120)
            p.setPen(QPen(dot, 1.0))
            p.setBrush(bg)
            p.drawRoundedRect(rect, 5, 5)
            p.setPen(QColor(235, 240, 245, alpha) if dark else QColor(20, 25, 30, alpha))
            p.drawText(rect, Qt.AlignCenter, text)

    def _paint_gizmo(self, p, dark):
        right, up, back = self.camera.basis()
        cx, cy, r = 52.0, self.height() - 52.0, 32.0
        axes = [((1, 0, 0), "L", QColor(232, 93, 93)), ((-1, 0, 0), "R", QColor(232, 93, 93)),
                ((0, 1, 0), "S", QColor(120, 200, 110)), ((0, -1, 0), "I", QColor(120, 200, 110)),
                ((0, 0, 1), "A", QColor(90, 160, 240)), ((0, 0, -1), "P", QColor(90, 160, 240))]
        items = []
        for v, label, col in axes:
            v = np.array(v, dtype=float)
            sx, sy, sz = np.dot(v, right), np.dot(v, up), np.dot(v, back)
            items.append((sz, cx + sx * r, cy - sy * r, label, col, v.sum() > 0))
        items.sort(key=lambda t: t[0])
        p.setPen(QPen(theme.qc(theme.BORDER, 90), 1.0) if dark else Qt.NoPen)
        p.setBrush(theme.qc(theme.CANVAS, 110) if dark else QColor(255, 255, 255, 110))
        p.drawEllipse(QPointF(cx, cy), r + 14, r + 14)
        font = QFont(self.font())
        font.setPointSizeF(8.0)
        font.setBold(True)
        p.setFont(font)
        for sz, x, y, label, col, positive in items:
            c = QColor(col)
            c.setAlpha(255 if sz > -0.2 else 130)
            p.setPen(QPen(c, 2.0))
            p.drawLine(QPointF(cx, cy), QPointF(x, y))
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            rad = 9.0
            p.drawEllipse(QPointF(x, y), rad, rad)
            p.setPen(QColor(15, 15, 15))
            p.drawText(QRectF(x - rad, y - rad, rad * 2, rad * 2), Qt.AlignCenter, label)

    def _paint_hover(self, p):
        sid = self.state.hovered
        if (sid < 0 or self.hover_pos is None or self._press is not None
                or not self.settings.get("show_hover_tooltip", True)):
            return
        s = self.ds.structures[sid]
        text = s["name"] + (f" ({s['side'].lower()})" if s["side"] else "")
        sub = self.ds.systems[self.ds.system_of[sid]]["name"]
        font = QFont(self.font())
        font.setPointSizeF(9.5)
        font.setBold(True)
        small = QFont(self.font())
        small.setPointSizeF(8.0)
        fm, fm2 = QFontMetricsF(font), QFontMetricsF(small)
        w = max(fm.horizontalAdvance(text), fm2.horizontalAdvance(sub)) + 22
        h = fm.height() + fm2.height() + 10
        x = self.hover_pos.x() + 16
        y = self.hover_pos.y() + 18
        if x + w > self.width() - 4:
            x = self.hover_pos.x() - w - 12
        if y + h > self.height() - 4:
            y = self.hover_pos.y() - h - 12
        rect = QRectF(x, y, w, h)
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        p.fillPath(path, theme.qc(theme.OVERLAY, 238))
        p.setPen(QPen(theme.qc(theme.BORDER_STRONG), 1.0))
        p.drawPath(path)
        col = self.ds.systems[self.ds.system_of[sid]]["color"]
        p.fillRect(QRectF(x, y + 5, 3, h - 10), QColor.fromRgbF(*col))
        p.setPen(theme.qc(theme.TEXT_STRONG))
        p.setFont(font)
        p.drawText(QRectF(x + 11, y + 4, w, fm.height()), Qt.AlignLeft | Qt.AlignVCenter, text)
        p.setPen(theme.qc(theme.MUTED))
        p.setFont(small)
        p.drawText(QRectF(x + 11, y + 5 + fm.height(), w, fm2.height()), Qt.AlignLeft | Qt.AlignVCenter, sub)
