"""The model viewer's 3D view: the new renderer, driven exactly like the atlas.

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

import colorsys
import math
import time

import moderngl
import numpy as np
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtOpenGLWidgets import QOpenGLWidget


def _annotation_plate(dark, alpha):
    """Painter label background follows the viewport, independently of UI chrome."""
    return QColor(24, 34, 45, alpha) if dark else QColor(255, 255, 255, alpha)


from ..ui import theme
from ..viewport import VIEWS, Overlay, TrackpadInput
from .camera import OrbitCamera
from .model import srgb_to_linear
from .renderer import FrameState, Renderer, Settings

SECTION_AXES = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0))     # sagittal, coronal, transverse
SECTION_NAMES = ("Sagittal", "Coronal", "Transverse")


def _smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def _hex_rgb(h, default=(0.3, 0.78, 1.0)):
    c = QColor(h)
    return (c.redF(), c.greenF(), c.blueF()) if c.isValid() else default


def distinct_colours(n):
    """n well-separated colours (golden-angle hues, alternating lightness), linear RGB."""
    out = np.zeros((max(n, 1), 3), dtype=np.float32)
    for i in range(n):
        h = (i * 0.618033988749895) % 1.0
        r, g, b = colorsys.hls_to_rgb(h, 0.55 if i % 2 == 0 else 0.42, 0.55)
        out[i] = srgb_to_linear((r, g, b))
    return out


class ModelViewport(QOpenGLWidget):
    structureClicked = Signal(int, object)
    structureDoubleClicked = Signal(int)
    hoverChanged = Signal(int)
    contextMenuRequested = Signal(int, QPoint)
    frameTimed = Signal(float)
    glReady = Signal()
    historyRequested = Signal(int)
    measureChanged = Signal(str)
    animChanged = Signal(float)          # cycle / clip position, 0..1
    viewChanged = Signal(str)            # a named view was chosen

    BUTTONS = {"Left": Qt.LeftButton, "Right": Qt.RightButton, "Middle": Qt.MiddleButton}

    def __init__(self, model, state, settings, entry=None, parent=None):
        super().__init__(parent)
        self.model = model
        self.state = state
        self.settings = settings
        self.entry = entry
        self.ds = state.ds
        self.camera = OrbitCamera(fov=39.597753)
        lo, hi = model.world_bounds(visible_only=False)
        self.camera.set_scene(lo, hi)
        self.renderer = None
        self.ctx = None
        self.gl_info = ""
        self.rsettings = Settings()
        for k, v in getattr(model, "look_defaults", {}).items():
            setattr(self.rsettings, k, v)
        self.orientation_axes_on = bool(settings.get("show_gizmo", True)
                                        and getattr(entry, "oriented", False))
        self._fbo = None
        self._fbo_id = None
        # cutting: the micro model's own corner cut-away, or cross-sections (any plane cuts)
        self.cut_planes = None               # [(n, d) x3] of the cut-away, or None
        self.cut_on = False
        self.sections = [None, None, None]   # per axis: [position, flip] while that section is on
        # layers, states and animation
        self.explode = 0.0
        self.reveal_state = None
        self.reveal_amount = 0.0
        self.reveal_target = 0.0
        self.anim_t = 0.0                    # procedural: cycle phase 0..1; clip: seconds
        self.playing = False
        self.loop = True
        self.speed = 1.0
        # interaction
        self._press = None
        self._last = None
        self._button = None
        self._moved = False
        self._pivot_pending = False
        self._last_hover_pick = 0.0
        self.hover_pos = None
        self.auto_rotate = False
        self.touch = TrackpadInput(self)
        self.home_view = None
        self._last_frame_time = time.perf_counter()
        self.click_hook = None
        # labels
        self.labels_on = False
        self.names_hidden = lambda: False    # practice: nothing on screen may name a structure
        self.label_items = []                # [(item, anchor world, area px, text, priority)]
        self.section_items = []              # [(item, anchor world)]
        self._label_rects = []
        self._labels_dirty = True
        self._occluded = {}
        self._moving_prev = False
        # measuring (the atlas's tool, in the model's real units)
        self.measure_mode = False
        self.measure_points = []
        self.overlay = Overlay(self)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(320, 240)
        state.render_changed.connect(self._on_state)
        state.visibility_changed.connect(self.invalidate_labels)
        state.selection_changed.connect(self.invalidate_labels)
        self._distinct = distinct_colours(len(model.items))
        self._group_colours = np.array([srgb_to_linear(self.model.group_of(i).colour) if self.model.group_of(i)
                                        else (0.5, 0.5, 0.5) for i in range(len(model.items))], dtype=np.float32)

    # ------------------------------------------------------------------ GL lifecycle
    def initializeGL(self):
        self.ctx = moderngl.create_context()
        self.renderer = Renderer(self.ctx)
        self.renderer.set_model(self.model)
        self.gl_info = f"{self.ctx.info['GL_RENDERER']} · OpenGL {self.ctx.info['GL_VERSION'].split(' ')[0]}"
        self.glReady.emit()

    def release_gl(self):
        if self.renderer is None:
            return
        self.makeCurrent()
        try:
            self.renderer.release()
        finally:
            self.renderer = None
            self.doneCurrent()

    def _physical_size(self):
        dpr = self.devicePixelRatioF()
        return max(int(self.width() * dpr), 2), max(int(self.height() * dpr), 2)

    def _render_scale(self):
        return float(np.clip(float(self.settings.get("render_scale", 1.0)), 0.25, 2.0))

    def _render_size(self):
        w, h = self._physical_size()
        s = self._render_scale()
        return max(int(w * s), 2), max(int(h * s), 2)

    def _sync_settings(self):
        s = self.rsettings
        st = self.settings
        s.ao = bool(st.get("ssao", True))
        s.ao_strength = float(st.get("ssao_strength", 1.0))
        s.msaa = 8 if st.get("fxaa", True) else 1
        s.ghost_alpha = float(st.get("ghost_alpha", 0.10))
        sel = _hex_rgb(st.get("selection_color", "#4dc7ff"))
        hov = _hex_rgb(st.get("hover_color", "#ffd966"), (1.0, 0.85, 0.4))
        s.outline, s.hover_outline = sel, hov
        s.highlight, s.hover_highlight = srgb_to_linear(sel), srgb_to_linear(hov)
        s.hover_outline_on = bool(st.get("hover_outline", True))
        if st.get("custom_background"):
            s.background = (_hex_rgb(st.get("bg_top", "#1d2127")), _hex_rgb(st.get("bg_bottom", "#090a0d")))
        else:
            from ..config import BACKGROUND_DARK, BACKGROUND_LIGHT
            s.background = BACKGROUND_DARK if st.get("dark_background", True) else BACKGROUND_LIGHT

    def paintGL(self):
        if self.renderer is None:
            return
        t0 = time.perf_counter()
        dt = min(t0 - self._last_frame_time, 0.1)
        self._last_frame_time = t0
        moving = self.camera.update()
        if self.auto_rotate and self._press is None:
            self.camera.yaw += math.radians(float(self.settings.get("auto_rotate_speed", 20.0))) * dt
            moving = True
        animating = self._advance(dt)
        rw, rh = self._render_size()
        w, h = self._physical_size()
        self.camera.aspect = rw / rh
        fid = self.defaultFramebufferObject()
        if self._fbo is None or fid != self._fbo_id:
            self._fbo = self.ctx.detect_framebuffer(fid)
            self._fbo_id = fid
        self._sync_settings()
        m = self.model
        if m.clip is not None and self.anim_kind() == "clip":
            m.evaluate(self.anim_t, self.reveal_state, _smooth(self.reveal_amount))
        else:
            m.evaluate(m.clip_range[0], self.reveal_state, _smooth(self.reveal_amount))
        self.renderer.render(self._fbo, (rw, rh), self.camera, self.rsettings, self.frame_state(), out_size=(w, h))
        busy = moving or animating or self._press is not None
        if busy:
            self._labels_dirty = True
        elif self._labels_dirty or self._moving_prev:
            self._compute_labels()
        self._moving_prev = busy
        self.frameTimed.emit((time.perf_counter() - t0) * 1000.0)
        self.overlay.update()
        if moving or animating:
            self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.overlay.setGeometry(self.rect())
        self.invalidate_labels()

    def _on_state(self):
        # Hover/colour changes alter shading, not label anchors. Visibility and
        # selection already invalidate through their own signals; opacity can
        # change the frontmost surface and also needs fresh anchors.
        signature = tuple(None if getattr(self.state, name, None) is None else
                          np.asarray(getattr(self.state, name)).tobytes()
                          for name in ("part_alpha", "system_alpha"))
        if signature != getattr(self, "_label_opacity_signature", None):
            self._label_opacity_signature = signature
            self.invalidate_labels()
        self.update()

    def invalidate_labels(self):
        self._labels_dirty = True
        self.update()

    # ------------------------------------------------------------------ what is drawn
    def frame_state(self):
        st = self.state
        n = len(self.model.items)
        vis = st.visible_mask().copy()
        ghost = np.zeros(n, dtype=bool)
        if st.ghost_focus is not None:
            ghost = vis & ~st.ghost_focus
        sel = frozenset(int(s) for s in st.selected)
        for s in sel:
            ghost[s] = False
        alpha = getattr(st, "part_alpha", None)
        override = {int(s): srgb_to_linear(rgb) for s, rgb in st.custom_colors.items()}
        mode = int(self.settings.get("color_mode", 0))
        colours = self._distinct if mode == 1 else (self._group_colours if mode == 2 else None)
        planes, on, cmode = self.clip_config()
        fs = FrameState(visible=vis, ghost=ghost, alpha=alpha, selected=sel, hovered=int(st.hovered),
                        override=override, colours=colours, clip_planes=planes, clip_on=on, clip_mode=cmode)
        if self.anim_kind() == "procedural":
            fs.anim_t = self.anim_t
            fs.anim_frame = self.model.anim_frame(self.anim_t)
        return fs

    def clip_config(self):
        """(planes, on, mode): the cross-sections when any is on (any plane cuts), else the cut-away (a corner)."""
        if any(s is not None for s in self.sections):
            planes, on = [], []
            for i, s in enumerate(self.sections):
                n = np.array(SECTION_AXES[i])
                if s is None:
                    planes.append((0.0, 1.0, 0.0, 0.0))
                    on.append(False)
                    continue
                pos, flip = s
                if flip:
                    n = -n
                p = np.zeros(3)
                p[[0, 2, 1][i]] = pos
                planes.append((float(n[0]), float(n[1]), float(n[2]), -float(np.dot(n, p))))
                on.append(True)
            return tuple(planes), tuple(on), 0
        if self.cut_on and self.cut_planes is not None:
            return tuple(self.cut_planes), (True, True, False), 1
        return ((0.0, 1.0, 0.0, 0.0),) * 3, (False, False, False), 0

    def any_cut(self):
        return any(self.clip_config()[1])

    def set_explode(self, amount):
        """Separate the parts: a procedural model lifts its layers by rank (as the old microanatomy view did);
        any other model pushes each item away from the middle."""
        self.explode = float(amount)
        self.model.set_explode(self.explode)
        self.invalidate_labels()

    # ------------------------------------------------------------------ animation and states
    def anim_kind(self):
        if getattr(self.model, "animation", None) is not None:
            return "procedural"
        if self.model.clip is not None:
            return "clip"
        return None

    def anim_period(self):
        k = self.anim_kind()
        if k == "procedural":
            return self.model.animation.period
        if k == "clip":
            t0, t1 = self.model.clip_range
            return max(t1 - t0, 1e-6)
        return 1.0

    def anim_fraction(self):
        if self.anim_kind() == "clip":
            t0, _t1 = self.model.clip_range
            return (self.anim_t - t0) / self.anim_period()
        return self.anim_t

    def set_anim_fraction(self, f):
        f = min(max(float(f), 0.0), 1.0)
        if self.anim_kind() == "clip":
            self.anim_t = self.model.clip_range[0] + f * self.anim_period()
        else:
            self.anim_t = f % 1.0
        self.animChanged.emit(self.anim_fraction())
        self.update()

    def set_playing(self, on):
        self.playing = bool(on) and self.anim_kind() is not None
        self._last_frame_time = time.perf_counter()
        self.update()

    def _advance(self, dt):
        busy = False
        k = self.anim_kind()
        if self.playing and k is not None:
            if k == "procedural":
                self.anim_t = (self.anim_t + dt * self.speed / self.model.animation.period) % 1.0
            else:
                t0, t1 = self.model.clip_range
                t = self.anim_t + dt * self.speed
                if t > t1:
                    if self.loop:
                        t = t0 + (t - t1) % max(t1 - t0, 1e-6)
                    else:
                        t = t1
                        self.playing = False
                self.anim_t = t
            self.animChanged.emit(self.anim_fraction())
            busy = True
        if abs(self.reveal_amount - self.reveal_target) > 1e-4:
            step = dt / 0.9
            self.reveal_amount += max(-step, min(step, self.reveal_target - self.reveal_amount))
            if self.reveal_target == 0.0 and self.reveal_amount <= 1e-4:
                self.reveal_amount = 0.0
                self.reveal_state = None
            busy = True
        return busy

    def show_state(self, name):
        m = self.model
        if name == "assembled" or name not in m.states or not m.states[name]["offsets"]:
            self.reveal_target = 0.0
        else:
            if self.reveal_state != name and self.reveal_amount > 0:
                self.reveal_amount = 0.0
            self.reveal_state = name
            self.reveal_target = 1.0
        self._last_frame_time = time.perf_counter()
        self.update()

    # ------------------------------------------------------------------ camera helpers (the atlas's)
    def aspect(self):
        return max(self.width(), 1) / max(self.height(), 1)

    def duration(self):
        return float(self.settings.get("camera_duration", 0.55))

    def scene_bounds(self):
        return self.model.world_bounds(visible_only=False, visible=self.state.visible_mask())

    def reset_view(self, animate=True):
        """Home: the model's start view when its file names one, else its home direction, framed."""
        m = self.model
        start = m.sidecar.get("start_view")
        if not start and "V1" in m.cameras:
            start = "V1"
        dur = self.duration() if animate else 0.0
        if start and start in m.cameras:
            self.set_named_view(start, animate=animate, visibility=True)
            return
        yaw, pitch = getattr(m, "home", (math.radians(35.0), math.radians(24.0)))
        self.camera.ortho = False
        lo, hi = m.world_bounds(visible_only=False)
        radius = float(np.linalg.norm(hi - lo) / 2)
        self.camera.animate_to((lo + hi) / 2, self.camera.fit_distance(radius * 0.95, self.aspect()), yaw, pitch, dur)
        self.update()

    def set_view(self, name):
        """The atlas's anatomical views (1, 3, 7 and their opposites): the model faces +Z like the body does."""
        yaw, pitch = VIEWS[name]
        c = self.camera
        c.animate_to(c.target, c.distance, yaw, pitch, self.duration())
        self.update()

    def set_named_view(self, name, animate=True, visibility=True):
        m = self.model
        rec = m.cameras.get(name)
        if rec is None:
            return
        self.camera.set_record(rec, duration=self.duration() if animate else 0.0,
                               zoom_path=m.sidecar.get("view_transition") == "zoom",
                               fit=(m.bounds_min, m.bounds_max, self.aspect()))
        if visibility and "hidden" in rec:
            hide = set(rec.get("hidden") or [])
            by_key = {it.key: it.index for it in m.items}
            ids = [by_key[k] for k in hide if k in by_key]
            st = self.state
            st.push_undo()
            st.hidden[:] = False
            st.forced[:] = False
            st.isolated = None
            if ids:
                st.hidden[ids] = True
            st._vis_dirty()
        want = rec.get("state")
        self.show_state(want if want else "assembled")
        if visibility and "cut_on" in rec:
            self.cut_on = bool(rec["cut_on"])
            self.sections = [None, None, None]
            self.invalidate_labels()
        self.viewChanged.emit(name)
        self.update()

    def frame_structures(self, sids, duration=None, view=None):
        b = self.model.item_bounds(list(sids))
        if b is None:
            return
        yaw, pitch = VIEWS[view] if view in VIEWS else (None, None)
        self.camera.frame_bounds(b[0], b[1], self.aspect(), yaw=yaw, pitch=pitch,
                                 duration=self.duration() if duration is None else duration)
        self.update()

    def frame_visible(self):
        lo, hi = self.scene_bounds()
        self.camera.frame_bounds(lo, hi, self.aspect(), duration=self.duration())
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
        c.animate_to(c.target, c.distance * (0.8 ** direction), c.yaw, c.pitch, min(self.duration(), 0.2),
                     ortho_width=c.ortho_width * (0.8 ** direction))
        self.update()

    def toggle_auto_rotate(self):
        self.auto_rotate = not self.auto_rotate
        self._last_frame_time = time.perf_counter()
        self.update()
        return self.auto_rotate

    def toggle_projection(self):
        on = self.camera.toggle_ortho()
        self.update()
        return on

    # ------------------------------------------------------------------ picking
    def _render_xy(self, pos):
        dpr = self.devicePixelRatioF() * self._render_scale()
        return pos.x() * dpr, pos.y() * dpr

    def pick_full(self, pos):
        if self.renderer is None:
            return -1, None, False
        self.makeCurrent()
        try:
            x, y = self._render_xy(pos)
            item, point, cap = self.renderer.pick(x, y)
        finally:
            self.doneCurrent()
        return (item if 0 <= item < self.ds.n else -1), point, cap

    def pick_at(self, pos):
        return self.pick_full(pos)[0]

    def world_at(self, pos):
        return self.pick_full(pos)[1]

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

    # ------------------------------------------------------------------ input (the atlas's)
    def label_at(self, pos):
        for rect, item in reversed(self._label_rects):
            if rect.contains(pos):
                return item
        return None

    def mousePressEvent(self, e):
        if e.button() in (Qt.BackButton, Qt.ForwardButton):
            self.historyRequested.emit(-1 if e.button() == Qt.BackButton else 1)
            return
        if e.button() == Qt.LeftButton:
            item = self.label_at(e.position())
            if item is not None:                          # clicking a label picks that structure
                self.structureClicked.emit(int(item), e.modifiers())
                return
            if self.measure_mode:
                hit = self.world_at(e.position())
                if hit is not None:
                    if len(self.measure_points) >= 2 and e.modifiers() & Qt.ShiftModifier:
                        pass                              # Shift keeps adding to the chain
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
        c.snap()
        eye = c.eye()
        offset = eye - hit
        dist = float(np.linalg.norm(offset))
        if dist < 1e-6:
            return
        c.target = np.asarray(hit, dtype=np.float64)
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
                self.setCursor(Qt.CrossCursor if self.measure_mode else
                               (Qt.PointingHandCursor if sid >= 0 else Qt.ArrowCursor))
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

    def leaveEvent(self, e):
        self.hover_pos = None
        if self.state.hovered != -1:
            self.state.set_hovered(-1)
            self.hoverChanged.emit(-1)

    # ------------------------------------------------------------------ labels
    def label_hosts(self):
        """(items to label individually, whether whole groups may be labelled once)."""
        if self.names_hidden() or not self.settings.get("show_landmarks", True):
            return [], False
        sel = [int(s) for s in self.state.selected]
        if self.labels_on:
            vis = self.state.visible_mask()
            ghost = self.state.ghost_focus
            items = [it.index for it in self.model.items if vis[it.index] and it.label
                     and (ghost is None or ghost[it.index])]
            return sel + [i for i in items if i not in sel], True
        return sel, False

    def _compute_labels(self):
        """Anchors for the labels, from the frame just drawn: each labelled item's dot goes where it is most
        clearly visible - the pixel deepest inside its visible region."""
        self._labels_dirty = False
        self.label_items, self.section_items = [], []
        self._occluded = {}
        hosts, grouping = self.label_hosts()
        want_sections = self.any_cut() and self.settings.get("section_labels", True) and not self.names_hidden() \
            and self.settings.get("show_landmarks", True)
        if not hosts and not want_sections:
            return
        rw, rh = self.renderer.size
        k = max(1, int(round(min(rw, rh) / 420)))
        center_ids = None
        try:
            sampler = getattr(self.renderer, "read_label_samples", None)
            compact = sampler(k) if sampler is not None else None
            if compact is not None:
                ids_s, flags_s, depth, center_ids = compact
            else:
                ids, flags = self.renderer.read_ids()
                depth = self.renderer.read_depth()
                if ids is None or depth is None:
                    return
                ids_s, flags_s = ids[::k, ::k], flags[::k, ::k]
        except Exception:                      # noqa: BLE001 - a lost context just means no labels this frame
            return
        valid = ids_s >= 0
        n = len(self.model.items)
        counts = np.bincount(ids_s[valid], minlength=n)[:n]
        cap_counts = np.bincount(ids_s[valid & ((flags_s & 2) != 0)], minlength=n)[:n]
        min_px = max(6, int(40 / (k * k)))
        limit = int(self.settings.get("max_landmarks", 60))
        sel = set(int(s) for s in self.state.selected)

        # which to label: the selection always, one at a time; with labels on, everything visible, biggest first,
        # a crowded group (numbered copies, many small pieces) named once where it shows most
        chosen = []
        seen_groups = {}
        cands = [i for i in hosts if counts[i] >= min_px or i in sel]
        crowded = grouping and len([i for i in cands if i not in sel]) > limit * 0.6
        group_size = {}
        for i in cands:
            group_size[self.model.items[i].group] = group_size.get(self.model.items[i].group, 0) + 1
        for i in sorted(cands, key=lambda i: (i not in sel, -counts[i])):
            it = self.model.items[i]
            if i not in sel and crowded and group_size.get(it.group, 0) >= 4:
                if it.group in seen_groups:
                    continue
                seen_groups[it.group] = i
                chosen.append((i, it.group))
            else:
                chosen.append((i, it.name))
            if len(chosen) >= limit:
                break
        from scipy.ndimage import distance_transform_edt
        out = []
        for i, text in chosen:
            anchor = self._anchor(ids_s, i, None, k, depth, distance_transform_edt, center_ids)
            if anchor is not None:
                out.append((i, anchor, int(counts[i]), text, 0 if i in sel else 1))
        self.label_items = out
        if want_sections:
            secs = [i for i in np.nonzero(cap_counts >= min_px)[0]]
            secs.sort(key=lambda i: -cap_counts[i])
            secs = secs[:int(self.settings.get("max_section_labels", 22))]
            res = []
            for i in secs:
                anchor = self._anchor(ids_s, int(i), flags_s, k, depth, distance_transform_edt, center_ids)
                if anchor is not None:
                    res.append((int(i), anchor))
            self.section_items = res
        if center_ids is None and (self.label_items or self.section_items):
            self._check_occlusion()

    def _anchor(self, ids_s, item, flags_s, k, depth, edt, center_ids=None):
        mask = ids_s == item
        if flags_s is not None:
            mask &= (flags_s & 2) != 0
        ys, xs = np.nonzero(mask)
        if len(ys) == 0:
            return None
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        crop = np.pad(mask[y0:y1, x0:x1], 1)
        dist = edt(crop)
        iy, ix = np.unravel_index(int(np.argmax(dist)), dist.shape)
        py, px = (y0 + iy - 1) * k + k // 2, (x0 + ix - 1) * k + k // 2
        if center_ids is None:
            py = min(max(py, 0), depth.shape[0] - 1)
            px = min(max(px, 0), depth.shape[1] - 1)
            d = float(depth[py, px])
        else:
            gy, gx = y0 + iy - 1, x0 + ix - 1
            py = min(max(py, 0), self.renderer.size[1] - 1)
            px = min(max(px, 0), self.renderer.size[0] - 1)
            d = float(depth[gy, gx])
            self._occluded[item] = int(center_ids[gy, gx]) != item
        if d <= 0.0:
            return None
        return self.renderer.world_from_pixel(px, py, d)

    def _check_occlusion(self):
        """Once the view is still, whether each anchor is still the front-most thing at its pixel."""
        items = [(i, a) for i, a, *_ in self.label_items] + list(self.section_items)
        if not items or self.renderer is None:
            return
        pts, keys = [], []
        dpr = self.devicePixelRatioF() * self._render_scale()
        for i, a in items:
            pr = self.project(a)
            if pr is None:
                continue
            pts.append((pr[0] * dpr, pr[1] * dpr))
            keys.append(i)
        hits = self.renderer.ids_at(pts)
        self._occluded = {i: (hit != i) for i, hit in zip(keys, hits)}

    def project(self, world):
        if self.renderer is None:
            return None
        clip = self.renderer.last_vp @ np.array([world[0], world[1], world[2], 1.0])
        if clip[3] <= 1e-9:
            return None
        ndc = clip[:3] / clip[3]
        return ((ndc[0] * 0.5 + 0.5) * self.width(), (1 - (ndc[1] * 0.5 + 0.5)) * self.height(), ndc[2] * 0.5 + 0.5)

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
        if self.model.sidecar.get("mixed_schematic_scale"):
            return f"{units:.1f} model units (mixed schematic scale)"
        mpu = self.model.metres_per_unit
        if not mpu:                             # a model with no known real size: relative lengths only
            lo, hi = self.model.bounds_min, self.model.bounds_max
            return f"{units / max(float((hi - lo).max()), 1e-9) * 100:.1f} % of the model's width"
        return self._format_length(units * mpu)

    @staticmethod
    def _format_length(metres):
        mm = metres * 1000.0
        if mm < 0.001:
            return f"{mm * 1e6:.0f} nm"
        if mm < 1.0:
            um = mm * 1000
            return f"{um:.1f} µm" if um < 10 else f"{um:.0f} µm"
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
            if n1 > 1e-12 and n2 > 1e-12:
                ang = math.degrees(math.acos(float(np.clip(np.dot(v1, v2) / (n1 * n2), -1, 1))))
                out += f" · angle {ang:.0f}°"
        return out

    # ------------------------------------------------------------------ overlay
    def paint_overlay(self, p: QPainter):
        dark = self.settings.get("dark_background", True)
        self._label_rects = []
        self._paint_section_labels(p, dark)
        self._paint_labels(p, dark)
        self._paint_measure(p, dark)
        if self.orientation_axes_on:
            self._paint_gizmo(p, dark)
        self._paint_scale_bar(p, dark)
        self._paint_hover(p)

    def _font(self, delta=0.0, bold=False):
        f = QFont(self.font())
        f.setPointSizeF(float(self.settings.get("label_size", 8.6)) + delta)
        f.setBold(bold)
        return f

    def _paint_labels(self, p, dark):
        """Radial cards: each name sits out from its dot, away from the middle of what is shown, on a leader line;
        a card that would cover another tries a few nearby places before it gives way."""
        if not self.label_items:
            return
        font = self._font()
        p.setFont(font)
        fm = QFontMetricsF(font)
        w, h = float(self.width()), float(self.height())
        proj = []
        for i, a, area, text, prio in self.label_items:
            pr = self.project(a)
            if pr is None or not (0 <= pr[0] < w and 0 <= pr[1] < h) or pr[2] >= 1.0:
                continue
            proj.append((i, pr, area, text, prio))
        if not proj:
            return
        cx = sum(pr[0] for _i, pr, *_ in proj) / len(proj)
        cy = sum(pr[1] for _i, pr, *_ in proj) / len(proj)
        placed = [r for r, _ in self._label_rects]
        sel = set(int(s) for s in self.state.selected)
        order = sorted(proj, key=lambda t: (self._occluded.get(t[0], False), t[4], -t[2]))
        for i, pr, _area, text, prio in order:
            ax, ay = pr[0], pr[1]
            dx, dy = ax - cx, ay - cy
            ln = math.hypot(dx, dy)
            base = math.atan2(dy, dx) if ln > 4 else -math.pi / 4
            occluded = self._occluded.get(i, False) and i not in sel
            focus = i in sel
            tw = min(fm.horizontalAdvance(text) + 12, w * 0.4)
            th = fm.height() + 4
            rect = None
            # a selected part is always named, so it may look further round (the far side included) for room
            dists = (46.0, 70.0, 96.0, 124.0, 156.0) if focus else (46.0, 70.0, 96.0)
            dangs = (0.0, 0.45, -0.45, 0.9, -0.9, 1.35, -1.35, math.pi) if focus else (0.0, 0.45, -0.45, 0.9, -0.9)
            for dist in dists:
                for dang in dangs:
                    ang = base + dang
                    lx, ly = ax + math.cos(ang) * dist, ay + math.sin(ang) * dist
                    rx = lx if math.cos(ang) >= 0 else lx - tw
                    cand = QRectF(rx, ly - th / 2, tw, th)
                    if cand.left() < 2 or cand.right() > w - 2 or cand.top() < 2 or cand.bottom() > h - 2:
                        continue
                    if any(cand.intersects(r) for r in placed):
                        continue
                    rect = cand
                    break
                if rect is not None:
                    break
            if rect is None and not focus:
                continue
            if rect is None:                    # nowhere free: overlap, but stay inside the view
                right = ax >= cx
                rx = ax + 46 if right else ax - 46 - tw
                rx = min(max(rx, 2.0), w - 2 - tw)
                ry = min(max(ay - 46 - th / 2, 2.0), h - 2 - th)
                rect = QRectF(rx, ry, tw, th)
            alpha = 90 if occluded else 235
            dot = QColor(79, 195, 247, alpha) if not focus else QColor(255, 214, 92, 255)
            p.setPen(QPen(dot, 1.3))
            join = QPointF(rect.left() if rect.center().x() >= ax else rect.right(), rect.center().y())
            p.drawLine(QPointF(ax, ay), join)
            p.setBrush(dot if not occluded else Qt.NoBrush)
            r = 3.2 if not focus else 4.5
            p.drawEllipse(QPointF(ax, ay), r, r)
            placed.append(rect.adjusted(-2, -2, 2, 2))
            bg = _annotation_plate(dark, (210 if not occluded else 110) if dark else (215 if not occluded else 120))
            p.setPen(QPen(dot, 1.0))
            p.setBrush(bg)
            p.drawRoundedRect(rect, 5, 5)
            p.setPen(QColor(235, 240, 245, alpha) if dark else QColor(20, 25, 30, alpha))
            p.drawText(rect, Qt.AlignCenter, fm.elidedText(text, Qt.ElideRight, tw - 10))
            self._label_rects.append((QRectF(rect), i))

    def _paint_section_labels(self, p, dark):
        """Everything a cut face shows, named in two columns down the sides like an atlas plate."""
        if not self.section_items:
            return
        font = self._font()
        p.setFont(font)
        fm = QFontMetricsF(font)
        w, h = float(self.width()), float(self.height())
        line_h = fm.height() + 7
        margin = 12.0
        columns = {-1: [], 1: []}
        for i, anchor in self.section_items:
            pr = self.project(anchor)
            if pr is None or not (0 <= pr[0] <= w and 0 <= pr[1] <= h):
                continue
            columns[-1 if pr[0] < w * 0.5 else 1].append((i, pr))
        sel = set(int(s) for s in self.state.selected)
        for side, items in columns.items():
            if not items:
                continue
            items.sort(key=lambda t: t[1][1])
            ys = [float(pr[1]) for _, pr in items]
            for k in range(1, len(ys)):
                ys[k] = max(ys[k], ys[k - 1] + line_h)
            bottom = h - 108.0 if side < 0 and self.orientation_axes_on else h - 34.0
            over = ys[-1] - (bottom - line_h)
            if over > 0:
                ys = [y - over for y in ys]
                for k in range(len(ys) - 2, -1, -1):
                    ys[k] = min(ys[k], ys[k + 1] - line_h)
            for (i, pr), ly in zip(items, ys):
                ly = max(line_h * 0.6, min(bottom - line_h * 0.6, ly))
                text = self.model.items[i].name
                tw = min(fm.horizontalAdvance(text) + 12, w * 0.28)
                x0 = margin if side < 0 else w - margin - tw
                rect = QRectF(x0, ly - line_h / 2 + 2, tw, fm.height() + 4)
                join_x = rect.right() if side < 0 else rect.left()
                elbow_x = join_x + 16 * -side
                if (side < 0 and pr[0] < elbow_x) or (side > 0 and pr[0] > elbow_x):
                    elbow_x = pr[0]
                accent = QColor(255, 214, 92) if i in sel else QColor(120, 205, 255)
                faded = QColor(accent.red(), accent.green(), accent.blue(), 150)
                p.setPen(QPen(faded, 1.1))
                p.drawLine(QPointF(pr[0], pr[1]), QPointF(elbow_x, ly))
                p.drawLine(QPointF(elbow_x, ly), QPointF(join_x, ly))
                p.setBrush(accent)
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(pr[0], pr[1]), 2.6, 2.6)
                p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 170), 1.0))
                p.setBrush(_annotation_plate(dark, 220 if dark else 228))
                p.drawRoundedRect(rect, 4, 4)
                p.setPen(QColor(235, 240, 245) if dark else QColor(20, 25, 30))
                p.drawText(rect, Qt.AlignCenter, fm.elidedText(text, Qt.ElideRight, tw - 10))
                self._label_rects.append((QRectF(rect), i))

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
        font = self._font(0.6, True)
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

    def _paint_gizmo(self, p, dark):
        right, up, back = self.camera.basis()
        cx, cy, r = 52.0, self.height() - 52.0, 32.0
        # Tissue blocks use model coordinates, not presumed anatomical directions.
        labels = ("L", "R", "S", "I", "A", "P") if getattr(self.entry, "oriented", False) else (
            "+X", "-X", "+Y", "-Y", "+Z", "-Z")
        axes = [((1, 0, 0), labels[0], QColor(232, 93, 93)), ((-1, 0, 0), labels[1], QColor(232, 93, 93)),
                ((0, 1, 0), labels[2], QColor(120, 200, 110)), ((0, -1, 0), labels[3], QColor(120, 200, 110)),
                ((0, 0, 1), labels[4], QColor(90, 160, 240)), ((0, 0, -1), labels[5], QColor(90, 160, 240))]
        items = []
        for v, label, col in axes:
            v = np.array(v, dtype=float)
            items.append((np.dot(v, back), cx + np.dot(v, right) * r, cy - np.dot(v, up) * r, label, col))
        items.sort(key=lambda t: t[0])
        p.setPen(QPen(theme.qc(theme.BORDER, 90), 1.0) if dark else Qt.NoPen)
        p.setBrush(QColor(11, 16, 22, 110) if dark else QColor(255, 255, 255, 110))
        p.drawEllipse(QPointF(cx, cy), r + 14, r + 14)
        font = QFont(self.font())
        font.setPointSizeF(8.0)
        font.setBold(True)
        p.setFont(font)
        for sz, x, y, label, col in items:
            c = QColor(col)
            c.setAlpha(255 if sz > -0.2 else 130)
            p.setPen(QPen(c, 2.0))
            p.drawLine(QPointF(cx, cy), QPointF(x, y))
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(x, y), 9.0, 9.0)
            p.setPen(QColor(15, 15, 15))
            p.drawText(QRectF(x - 9, y - 9, 18, 18), Qt.AlignCenter, label)

    def _paint_scale_bar(self, p, dark):
        """A scale bar in the corner for a model of known size: the kidney goes from 20 cm to half a micron."""
        # Gross anatomy and the separately magnified nephron have no common
        # clinical calibration. The two-click ruler identifies model units.
        if self.model.sidecar.get("mixed_schematic_scale"):
            return
        mpu = self.model.metres_per_unit
        if not mpu or self.renderer is None:
            return
        per_px = self.camera.world_per_pixel(self.height(), self.aspect()) * mpu     # metres per screen pixel
        if per_px <= 0:
            return
        want = per_px * 110.0
        e = math.floor(math.log10(want))
        nice = min((1, 2, 5, 10), key=lambda k: abs(k * 10 ** e - want)) * 10 ** e
        px = nice / per_px
        x1, y = self.width() - 18.0, self.height() - 18.0
        x0 = x1 - px
        col = QColor(230, 236, 242) if dark else QColor(25, 30, 36)
        p.setPen(QPen(col, 2.0))
        p.drawLine(QPointF(x0, y), QPointF(x1, y))
        p.drawLine(QPointF(x0, y - 5), QPointF(x0, y + 1))
        p.drawLine(QPointF(x1, y - 5), QPointF(x1, y + 1))
        font = self._font(-0.4, True)
        p.setFont(font)
        p.drawText(QRectF(x0 - 40, y - 22, px + 80, 16), Qt.AlignCenter, self._format_length(nice))

    def _paint_hover(self, p):
        sid = self.state.hovered
        if (sid < 0 or self.hover_pos is None or self._press is not None or self.names_hidden()
                or not self.settings.get("show_hover_tooltip", True)):
            return
        it = self.model.items[sid]
        text = it.name
        sub = it.group if it.group != it.name else ""
        font = QFont(self.font())
        font.setPointSizeF(9.5)
        font.setBold(True)
        small = QFont(self.font())
        small.setPointSizeF(8.0)
        fm, fm2 = QFontMetricsF(font), QFontMetricsF(small)
        w = max(fm.horizontalAdvance(text), fm2.horizontalAdvance(sub)) + 22
        h = fm.height() + (fm2.height() if sub else 0) + 10
        x = self.hover_pos.x() + 16
        y = self.hover_pos.y() + 18
        if x + w > self.width() - 4:
            x = self.hover_pos.x() - w - 12
        if y + h > self.height() - 4:
            y = self.hover_pos.y() - h - 12
        rect = QRectF(x, y, w, h)
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        # Isolate the tooltip from brushes left by labels or other overlays.
        # drawPath otherwise fills it again with the previous label's brush.
        p.save()
        p.setBrush(Qt.NoBrush)
        p.fillPath(path, QColor('#263544'))
        p.setPen(QPen(QColor('#82949f'), 1.0))
        p.drawPath(path)
        g = self.model.group_of(sid)
        col = g.colour if g is not None else it.colour
        p.fillRect(QRectF(x, y + 5, 3, h - 10), QColor.fromRgbF(*[float(c) for c in col]))
        p.setPen(QColor('#f3f6f9'))
        p.setFont(font)
        p.drawText(QRectF(x + 11, y + 4, w, fm.height()), Qt.AlignLeft | Qt.AlignVCenter, text)
        if sub:
            p.setPen(QColor('#c7d5df'))
            p.setFont(small)
            p.drawText(QRectF(x + 11, y + 5 + fm.height(), w, fm2.height()), Qt.AlignLeft | Qt.AlignVCenter, sub)
        p.restore()

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
            for _ in range(3):
                self.renderer.render(fbo, (w, h), self.camera, self.rsettings, self.frame_state())
            img = self.renderer.read_final(fbo, (w, h)).copy()
            fbo.release()
            rb.release()
        finally:
            self.doneCurrent()
        self.invalidate_labels()
        return img
