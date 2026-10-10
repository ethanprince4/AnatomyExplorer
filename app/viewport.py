import math
import sys
import time

import moderngl
import numpy as np
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, Signal
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
        self._pick_frame_key = None
        self.clip_on = [False, False, False]
        self.clip_pos = [0.0, 0.0, 0.9]
        self.clip_flip = [False, False, False]
        self.clip_mode = 0
        self.radiology_slice = False
        self._radiology_label_groups = None
        self._section_label_names = {}
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
        self._structure_labels = []
        self.section = None            # SectionIndex, attached by the main window
        self.section_anchors = []      # [(sid, anchor_xyz, weight)] on the current cut face
        self._reference_anchors = []   # the same for a radiology case's labels on an uncut (projection) view
        self._reference_key = None
        self._section_geometry = None
        self.last_section_frame = None
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
        self._section_geometry = (vertices, indices)      # kept: sections and label anchors reuse it
        self.renderer = Renderer(self.ctx, self.ds, vertices, indices, cap_depth=getattr(self.ds, "cap_depth", False))
        self.gl_info = f"{self.ctx.info['GL_RENDERER']} · OpenGL {self.ctx.info['GL_VERSION'].split(' ')[0]}"
        self.glReady.emit()

    def _physical_size(self):
        dpr = self.devicePixelRatioF()
        return round(self.width() * dpr), round(self.height() * dpr)

    def _frame_key(self):
        """Inputs to the ID/depth buffers, including changes awaiting Qt's next paint."""
        w, h = self._physical_size()
        scale = float(self.settings.get("render_scale", 1.0))
        size = max(int(w * scale), 2), max(int(h * scale), 2)
        vp = self.camera.proj(size[0] / size[1]) @ self.camera.view()
        return (size, vp.tobytes(), repr(self.clip_uniforms()),
                repr(sorted(self.settings.items())))

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
        # detect_framebuffer records the widget size at that moment (it is a small one on the first paint), so it is
        # detected again when the size changes.
        if self._fbo is None or (fbo_id, w, h) != self._fbo_id:
            self._fbo = self.ctx.detect_framebuffer(fbo_id)
            self._fbo_id = (fbo_id, w, h)
        self.renderer.render(self._fbo, self.camera, self.settings, self.clip_uniforms(),
                             hover_id=self.state.hovered, has_selection=bool(self.state.selected),
                             radiology_slice=self.radiology_slice)
        self._pick_frame_key = self._frame_key()
        self._update_landmarks()
        self._update_structure_labels()
        self._update_reference_anchors()
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
    def set_radiology_section_labels(self, groups=None):
        """Temporary authored names/IDs for this case; never alter preferences.

        Each group is (display_text, structure_ids, surface_anchor[, at]). One physically intersecting,
        visible representative anchors each name; a group with ``at`` (a point on its structures) is drawn there
        when that point is visible, so several groups can name places on one structure. Rendering remains
        independent.
        None restores ordinary atlas labels; an empty list deliberately hides them.
        """
        self._radiology_label_groups = groups
        self._section_label_names = {}
        self.refresh_section()
        self.update()

    def set_radiology_slice(self, enabled: bool) -> None:
        """Render a single section plane without anatomy surfaces behind it."""
        self.radiology_slice = bool(enabled)
        if not enabled:
            had_labels = self._radiology_label_groups is not None
            self._radiology_label_groups = None
            self._section_label_names = {}
            if had_labels:
                self.refresh_section()
        self.update()

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

    def frame_section(self, view=None):
        """Frame actual cut intersections rather than the full lengths of their meshes."""
        if not self.radiology_slice or sum(self.clip_on) != 1:
            return False
        from .section import plane_bounds
        if self._section_geometry is None:
            self._section_geometry = self.ds.load_geometry()
        plane = self.clip_uniforms()[0][self.clip_on.index(True)]
        started = time.perf_counter()
        bounds = plane_bounds(self.ds, *self._section_geometry, self.state.visible_mask(), plane)
        if bounds is None:
            self.last_section_frame = {"contributors": [], "seconds": time.perf_counter() - started}
            return False
        lo, hi, contributors = bounds
        self.last_section_frame = {"bounds": [lo.tolist(), hi.tolist()], "contributors": contributors,
                                   "seconds": time.perf_counter() - started}
        yaw, pitch = VIEWS[view] if view in VIEWS else (None, None)
        self.camera.frame_plane_bounds(lo, hi, self.aspect(), yaw, pitch, self.duration())
        self.update()
        return True

    def radiology_reference_ids(self, sids):
        """Visible reference surfaces that actually meet this physical section.

        Projection views retain their visible anatomical links. Section links
        use indexed triangles, never only whole-structure bounding boxes or
        approximate sample points. This does not imply patient registration.
        """
        visible = self.state.visible_mask()
        ids = list(dict.fromkeys(int(s) for s in sids if 0 <= int(s) < len(visible) and visible[int(s)]))
        if not self.radiology_slice or sum(self.clip_on) != 1 or not ids:
            return ids
        from .section import plane_bounds
        if self._section_geometry is None:
            self._section_geometry = self.ds.load_geometry()
        # Match the float32 plane actually uploaded to GLSL, including a
        # coplanar float32 surface; do not silently move the requested section.
        plane = tuple(np.asarray(self.clip_uniforms()[0][self.clip_on.index(True)],
                                 dtype=np.float32).astype(np.float64))
        key = (id(self._section_geometry), plane)
        if getattr(self, '_radiology_reference_key', None) != key:
            self._radiology_reference_key = key
            self._radiology_reference_members = {}
        membership = self._radiology_reference_members
        missing = [s for s in ids if s not in membership]
        if missing:
            mask = np.zeros(len(visible), dtype=bool)
            mask[missing] = True
            result = plane_bounds(self.ds, *self._section_geometry, mask, plane)
            contributors = set(result[2]) if result is not None else set()
            membership.update({s: s in contributors for s in missing})
        return [s for s in ids if membership[s]]

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
        # Qt events use logical, top-left coordinates; the ID buffer uses its
        # actual (possibly reduced/fractional-DPI) dimensions and bottom-left.
        # Scale each axis independently and flip AFTER choosing the pixel row.
        w, h = self.renderer.size if self.renderer else self._physical_size()
        return (math.floor(pos.x() * w / max(self.width(), 1)),
                h - 1 - math.floor(pos.y() * h / max(self.height(), 1)))

    def _ensure_pick_frame(self):
        # A click/pinch may arrive before a queued repaint after an orbit,
        # hide, resize or scale change. Never read those previous ID/depth pixels.
        if self._state_dirty or self._pick_frame_key != self._frame_key():
            self.paintGL()

    def pick_at(self, pos):
        if self.renderer is None:
            return -1
        self.makeCurrent()
        try:
            self._ensure_pick_frame()
            x, y = self._gl_xy(pos)
            sid = self.renderer.pick(x, y)
        finally:
            self.doneCurrent()
        return sid if 0 <= sid < self.ds.n and self.state.visible_mask()[sid] else -1

    def world_at(self, pos):
        if self.renderer is None:
            return None
        self.makeCurrent()
        try:
            self._ensure_pick_frame()
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
                depths = self.renderer.depths_at([self._gl_xy(QPointF(pr[0], pr[1])) for _, pr in probes])

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

    def _update_structure_labels(self):
        self._structure_labels = []
        if not self.settings.get("show_structure_labels", False):
            return
        visible = np.flatnonzero(self.state.visible_mask())
        if not len(visible):return
        # Project in one batch; label only structures actually present at the anchor pixel.
        points = np.column_stack((self.ds.centroid[visible], np.ones(len(visible))))
        clip = points @ self.renderer.last_vp.T
        front = clip[:,3] > 1e-6
        ndc = clip[:,:3] / np.maximum(clip[:,3:4],1e-6)
        sizes = np.linalg.norm(self.ds.bbox_max[visible]-self.ds.bbox_min[visible],axis=1)
        # selected first, then largest first; ties keep structure order (stable sort)
        picked = np.isin(visible, np.asarray(self.state.selected, dtype=np.int64))
        order = np.lexsort((-sizes, ~picked))
        on_screen = front & np.all(np.abs(ndc) <= 1, axis=1)
        limit = int(self.settings.get("max_landmarks",60))
        # The first limit*3 on-screen anchors are the only ones that can ever be probed, so read
        # their ids back together in one batch, then apply the same stop rules in the same order.
        candidates = []
        w, h = self.width(), self.height()
        for i in order[on_screen[order]][:limit*3]:
            x=(ndc[i,0]*.5+.5)*w
            y=(1-(ndc[i,1]*.5+.5))*h
            candidates.append((int(visible[i]),x,y))
        found = self.renderer.pick_many([self._gl_xy(QPointF(x,y)) for _,x,y in candidates])
        for (sid,x,y),hit in zip(candidates,found):
            if hit == sid:
                self._structure_labels.append((sid,x,y))
            if len(self._structure_labels)>=limit:break

    def _paint_structure_labels(self,p):
        if not self.settings.get("show_structure_labels",False):return
        font=QFont(self.font());font.setPointSizeF(float(self.settings.get("label_size",8.6)))
        p.setFont(font);fm=QFontMetricsF(font);placed=[]
        for sid,x,y in self._structure_labels:
            text=self.ds.structures[sid]["name"]
            tw=fm.horizontalAdvance(text)+16;th=fm.height()+10
            for dy in (-th-14,14,-2*th-20,th+20):
                rect=QRectF(max(4,min(self.width()-tw-4,x-tw/2)),max(4,min(self.height()-th-4,y+dy)),tw,th)
                if not any(rect.adjusted(-4,-3,4,3).intersects(r) for r in placed):break
            else:continue
            placed.append(rect)
            p.setPen(QPen(QColor("#8096a5"),1))
            p.drawLine(QPointF(x,y),rect.center())
            p.setBrush(QColor("#f2f6f8"));p.drawRoundedRect(rect,8,8)
            p.setPen(QColor("#263b47"));p.drawText(rect,Qt.AlignCenter,text)

    # ------------------------------------------------------------------ labelled cross-section
    CLIP_AXIS = (0, 2, 1)              # sagittal -> x, coronal -> z, transverse -> y

    def active_section(self):
        """(clip index, world axis, position) of the plane to label, or None."""
        for i in range(3):
            if self.clip_on[i]:
                return i, self.CLIP_AXIS[i], float(self.clip_pos[i])
        return None

    def _radiology_surface_anchor(self, sid, axis, value, fallback):
        """Put a wall label on an exact triangle/plane intersection, not its lumen."""
        if self._section_geometry is None:
            self._section_geometry = self.ds.load_geometry()
        key = (id(self._section_geometry), axis, value)
        if getattr(self, "_radiology_anchor_key", None) != key:
            self._radiology_anchor_key = key
            self._radiology_anchors = {}
        if sid not in self._radiology_anchors:
            vertices, indices = self._section_geometry
            dtype = np.dtype([("pos", "<f4", 3), ("nrm", "<f4", 3),
                              ("obj", "<u2"), ("mat", "<u2")])
            positions = np.frombuffer(vertices, dtype=dtype)["pos"]
            triangles = np.frombuffer(indices, dtype="<u4")
            part = self.ds.structures[sid]
            points = positions[triangles[part["i_start"]:part["i_start"] + part["i_count"]].reshape(-1, 3)].astype(np.float64)
            distance = points[:, :, axis] - value
            intersections = []
            for a, b in ((0, 1), (1, 2), (2, 0)):
                da, db = distance[:, a], distance[:, b]
                crossed = ((da < 0) & (db > 0)) | ((da > 0) & (db < 0))
                if crossed.any():
                    t = da[crossed] / (da[crossed] - db[crossed])
                    intersections.append(points[crossed, a] + t[:, None] * (points[crossed, b] - points[crossed, a]))
            anchor = np.asarray(fallback, dtype=float)
            if intersections:
                cut = np.concatenate(intersections)
                anchor = cut[np.argmin(np.sum((cut - cut.mean(axis=0)) ** 2, axis=1))]
                anchor[axis] = value
            self._radiology_anchors[sid] = anchor
        return self._radiology_anchors[sid]

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
        self._section_label_names = {}
        self._section_texts = []          # a radiology case's name per anchor (pinned labels can share a structure)
        if self._radiology_label_groups is None:
            self.section_anchors = self.section.cut(axis, value, self.state.visible_mask(), limit=limit)
        else:
            visible = self.state.visible_mask()
            groups = [(g[0], self.radiology_reference_ids(g[1]), g[2], g[3] if len(g) > 3 else None)
                      for g in self._radiology_label_groups]
            mask = np.zeros(self.ds.n, dtype=bool)
            for _text, ids, _surface, _at in groups:
                mask[ids] = True
            anchors = self.section.cut(axis, value, visible & mask, limit=self.ds.n)
            by_sid = {sid: (sid, anchor, weight) for sid, anchor, weight in anchors}
            self.section_anchors = []
            for text, ids, surface, at in groups:
                candidates = [by_sid[sid] for sid in ids if sid in by_sid]
                if candidates:
                    item = max(candidates, key=lambda x: x[2])
                    if at is not None:                 # pinned: its point, laid onto this cut
                        point = np.asarray(at, dtype=float).copy()
                        point[axis] = value
                        self.section_anchors.append((item[0], point, item[2]))
                        self._section_texts.append(text)
                        self._section_label_names.setdefault(item[0], text)
                        continue
                    if surface:
                        item = (item[0], self._radiology_surface_anchor(item[0], axis, value, item[1]), item[2])
                    if item[0] not in self._section_label_names:
                        self.section_anchors.append(item)
                        self._section_texts.append(text)
                        self._section_label_names[item[0]] = text
        if self.sectionChanged:
            self.sectionChanged(self.section_anchors)

    def _update_reference_anchors(self):
        """A radiology case's labels on an uncut view: each name points at the pixel deepest inside the largest
        visible patch of its structures, so a label never points at anatomy that is hidden or behind another."""
        groups = self._radiology_label_groups
        if not groups or self.active_section() is not None:
            if self._reference_anchors:
                self._reference_anchors = []
            self._reference_key = None
            return
        key = (self.renderer.last_vp.tobytes(), tuple(self.renderer.size), self.state.visible_mask().tobytes(),
               id(groups), tuple(self.state.selected))
        if key == self._reference_key:
            return
        # Reading the id buffer every frame would stall an orbit: wait until the view has held still briefly.
        now = time.perf_counter()
        if key != getattr(self, "_reference_pending", None):
            self._reference_pending, self._reference_pending_at = key, now
            QTimer.singleShot(170, self, self.update)
            return
        if now - self._reference_pending_at < 0.15:
            QTimer.singleShot(170, self, self.update)
            return
        self._reference_key = key
        rw, rh = self.renderer.size
        step = max(1, int(round(min(rw, rh) / 480)))
        ids = self.renderer.read_id_image(step)
        anchors, names = [], {}
        if ids is not None:
            from scipy.ndimage import distance_transform_edt, label
            for group in groups:
                text, sids = group[0], group[1]
                if len(group) > 3:
                    # pinned: drawn at its point when one of its structures is what shows there; a covered point
                    # falls back to the structure's largest visible patch below, like an unpinned label
                    sid = self._visible_pin(group[3], sids, ids, step)
                    if sid is not None:
                        anchors.append((sid, np.asarray(group[3], dtype=float), 1.0, text))
                        names.setdefault(sid, text)
                        continue
                members = np.asarray([s + 1 for s in sids if s not in names], dtype=np.int32)
                if not len(members):
                    continue
                mask = np.isin(ids, members)
                if not mask.any():
                    continue
                parts, count = label(mask)
                if count > 1:
                    mask = parts == (np.argmax(np.bincount(parts.ravel())[1:]) + 1)
                depth = distance_transform_edt(mask)
                y, x = np.unravel_index(int(np.argmax(depth)), depth.shape)
                sid = int(ids[y, x]) - 1
                point = self.renderer.world_at(x * step + step // 2, y * step + step // 2)
                if point is None or sid in names:
                    continue
                anchors.append((sid, np.asarray(point, dtype=float), float(mask.sum()), text))
                names[sid] = text
        self._reference_anchors = anchors
        self._reference_names = names

    def _visible_pin(self, at, sids, ids, step):
        """The structure of ``sids`` seen at the pixel of point ``at`` (or right beside it) in the id image whose
        rows run bottom-up, or None when the point is off screen or something else covers it."""
        clip = self.renderer.last_vp @ np.array([at[0], at[1], at[2], 1.0])
        if clip[3] <= 1e-6:
            return None
        rw, rh = self.renderer.size
        col = int((clip[0] / clip[3] * 0.5 + 0.5) * rw) // step
        row = int((clip[1] / clip[3] * 0.5 + 0.5) * rh) // step
        if not (0 <= row < ids.shape[0] and 0 <= col < ids.shape[1]):
            return None
        near = ids[max(row - 1, 0):row + 2, max(col - 1, 0):col + 2].ravel()
        wanted = set(int(s) + 1 for s in sids)
        hits = [int(v) for v in near if int(v) in wanted]
        if not hits:
            return None
        here = int(ids[row, col])
        return (here if here in wanted else hits[0]) - 1

    def _paint_section_labels(self, p, dark):
        """Lay the names out in two columns with leader lines, the way an atlas plate is labelled."""
        anchors, label_names = self.section_anchors, self._section_label_names
        texts = getattr(self, "_section_texts", [])
        if not anchors and self._reference_anchors and self.active_section() is None:
            anchors, label_names = self._reference_anchors, getattr(self, "_reference_names", {})
            texts = [a[3] for a in anchors]
        if not anchors:
            return
        if len(texts) != len(anchors):
            texts = [None] * len(anchors)
        font = QFont(self.font())
        font.setPointSizeF(float(self.settings.get("label_size", 8.6)))
        p.setFont(font)
        fm = QFontMetricsF(font)
        w, h = float(self.width()), float(self.height())
        line_h = fm.height() + 7
        margin = 12.0
        self._section_rects = []
        columns = {-1: [], 1: []}
        for (sid, anchor, *_rest), text in zip(anchors, texts):
            pr = self.project(anchor)
            if pr is None or not (0 <= pr[0] <= w and 0 <= pr[1] <= h):
                continue
            columns[-1 if pr[0] < w * 0.5 else 1].append((sid, pr, text))
        anchors=[item[1][0] for items in columns.values() for item in items]
        model_left=min(anchors) if anchors else w*.5
        model_right=max(anchors) if anchors else w*.5
        for side, items in columns.items():
            if not items:
                continue
            items.sort(key=lambda t: t[1][1])
            ys = [float(item[1][1]) for item in items]
            for k in range(1, len(ys)):                       # push apart downwards, then pull back on screen
                ys[k] = max(ys[k], ys[k - 1] + line_h)
            # the left column stops above the orientation gizmo in the bottom-left corner
            bottom = h - 108.0 if side < 0 and self.settings.get("show_gizmo", False) else h
            over = ys[-1] - (bottom - line_h)
            if over > 0:
                ys = [y - over for y in ys]
                for k in range(len(ys) - 2, -1, -1):
                    ys[k] = min(ys[k], ys[k + 1] - line_h)
            for (sid, pr, own), ly in zip(items, ys):
                ly = max(line_h * 0.6, min(bottom - line_h * 0.6, ly))
                text = own or label_names.get(sid, self.ds.structures[sid]["name"])
                tw = min(fm.horizontalAdvance(text) + 12, w * 0.28)
                x0 = max(margin,model_left-32-tw) if side < 0 else min(w-margin-tw,model_right+32)
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
                p.setPen(QPen(QColor("#8096a5"), 1.0))
                p.setBrush(QColor("#f2f6f8"))
                p.drawRoundedRect(rect, 8, 8)
                p.setPen(QColor("#263b47"))
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
            p.setBrush(QColor("#f2f6f8"))
            p.drawRoundedRect(rect, 8, 8)
            p.setPen(QColor("#263b47"))
            p.drawText(rect, Qt.AlignCenter, text)

    def paint_overlay(self, p: QPainter):
        dark = self.settings.get("dark_background", True)
        self._paint_section_labels(p, dark)
        self._paint_landmarks(p, dark)
        self._paint_structure_labels(p)
        self._paint_measure(p, dark)
        if self.settings.get("show_gizmo", False):
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
            bg = QColor("#f2f6f8")
            p.setPen(QPen(QColor("#8096a5"), 1.0))
            p.setBrush(bg)
            p.drawRoundedRect(rect, 8, 8)
            p.setPen(QColor("#526570") if occluded else QColor("#263b47"))
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
        p.setBrush(QColor(11, 16, 22, 180) if dark else QColor(255, 255, 255, 180))
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
        path.addRoundedRect(rect, 8, 8)
        p.save()
        p.setBrush(Qt.NoBrush)
        p.fillPath(path, QColor("#f2f6f8"))
        p.setPen(QPen(QColor("#8096a5"), 1.0))
        p.drawPath(path)
        col = self.ds.systems[self.ds.system_of[sid]]["color"]
        p.fillRect(QRectF(x, y + 5, 3, h - 10), QColor.fromRgbF(*col))
        p.setPen(QColor("#263b47"))
        p.setFont(font)
        p.drawText(QRectF(x + 11, y + 4, w, fm.height()), Qt.AlignLeft | Qt.AlignVCenter, text)
        p.setPen(QColor("#526570"))
        p.setFont(small)
        p.drawText(QRectF(x + 11, y + 5 + fm.height(), w, fm2.height()), Qt.AlignLeft | Qt.AlignVCenter, sub)
        p.restore()
