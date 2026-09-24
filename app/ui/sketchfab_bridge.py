"""Drive Sketchfab's embedded player with the atlas's own controls.

Sketchfab's player has its own mouse handling, which is close to the atlas's but not the same and ignores
Settings. So a transparent layer sits over the player, takes every mouse and key event, runs it through the very
same OrbitCamera the atlas uses - same sensitivities, button mapping, inversion, easing, view keys and
auto-rotate - and hands the resulting camera to the player through Sketchfab's official Viewer API
(setCameraLookAt). The player only renders.

Two coordinate details make the camera maths identical rather than similar:
- Sketchfab's world is Z-up; the atlas is Y-up. Positions are rotated between the two on the way in and out.
- Models come in any size. The model is rescaled so its starting camera sits at the atlas's default distance, so
  the zoom limits and pan speed feel the same whatever units the creator worked in.

What cannot be the same: the API has no "what is under the cursor" call, so zoom goes towards the centre of the
view rather than the cursor, and clicking parts or annotation hotspots needs the player's own controls (the
"Use my controls" switch turns the bridge off).
"""
import json
import math
import time

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QWidget

from ..camera import OrbitCamera
from ..viewport import VIEWS

API_VERSION = "1.12.1"
HOST = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;height:100%;background:#0d1015;overflow:hidden}
iframe{border:0;width:100%;height:100%;display:block}</style>
<script src="https://static.sketchfab.com/api/sketchfab-viewer-%VERSION%.js"></script></head>
<body><iframe id="f" allow="autoplay; fullscreen; xr-spatial-tracking" allowfullscreen></iframe>
<script>
window.__sf = {ready: false, error: null, cam: null, stamp: 0, annotations: []};
var api = null;
function sfRead() {
  if (api) api.getCameraLookAt(function (e, c) {
    if (!e) window.__sf.cam = {position: c.position, target: c.target};
    window.__sf.stamp += 1;
  });
}
function sfSetCam(p, t) { if (api) api.setCameraLookAt(p, t, 0); }
function sfFov(f) { if (api) api.setFov(f); }
function sfGoto(i) { if (api) api.gotoAnnotation(i); }
if (typeof Sketchfab === 'undefined') {
  window.__sf.error = 'offline';
} else {
  new Sketchfab('%VERSION%', document.getElementById('f')).init('%UID%', {
    success: function (a) {
      api = a;
      api.start();
      api.addEventListener('viewerready', function () {
        api.getCameraLookAt(function (e, c) {
          if (!e) window.__sf.cam = {position: c.position, target: c.target};
          window.__sf.ready = true;
        });
        api.getAnnotationList(function (e, list) {
          if (!e && list) window.__sf.annotations = list.map(function (x) { return x.name || ''; });
        });
      });
    },
    error: function () { window.__sf.error = 'init'; },
    autostart: 1, preload: 1, ui_theme: 'dark', dnt: 1, ui_hint: 0, camera: 0
  });
}
</script></body></html>"""

# Sketchfab is Z-up, the atlas Y-up
def to_app(v):
    return np.array([v[0], v[2], -v[1]], dtype=np.float64)


def to_sf(v):
    return [float(v[0]), float(-v[2]), float(v[1])]


HOME_DISTANCE = 3.0          # the atlas's own default camera distance
SKETCHFAB_FOV = 45.0         # the player's default vertical field of view


def host_html(uid):
    return HOST.replace("%VERSION%", API_VERSION).replace("%UID%", uid)


class CameraBridge(QWidget):
    """Invisible layer over the player: atlas controls in, setCameraLookAt out."""

    BUTTONS = {"Left": Qt.LeftButton, "Right": Qt.RightButton, "Middle": Qt.MiddleButton}
    changed = Signal()

    def __init__(self, page, settings, cmds=None, parent=None):
        super().__init__(parent)
        self.page = page
        self.settings = settings
        self.cmds = cmds
        self.camera = OrbitCamera(fov=float(settings.get("fov", 32.0)))
        self.scale = 1.0              # sketchfab units -> atlas units
        self.home = None              # (target, distance, yaw, pitch)
        self.fov_matched = False
        self.active = False
        self.auto_rotate = False
        self._press = None
        self._last = None
        self._button = None
        self._moved = False
        self._sent = None
        self._t_last = time.perf_counter()
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setStyleSheet("background: transparent;")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.OpenHandCursor)
        self.timer = QTimer(self)
        self.timer.setInterval(15)
        self.timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------ syncing with the player
    def adopt(self, cam):
        """Take over from wherever the player's camera is now (on load, or after it moved by itself)."""
        pos = to_app(cam["position"])
        tgt = to_app(cam["target"])
        d = float(np.linalg.norm(pos - tgt))
        if d < 1e-9:
            return
        if self.home is None:
            self.scale = HOME_DISTANCE / d
        pos *= self.scale
        tgt *= self.scale
        back = (pos - tgt) / (d * self.scale)
        c = self.camera
        c._anim = None
        c.target = tgt
        c.distance = d * self.scale
        c.pitch = math.asin(max(-1.0, min(1.0, back[1])))
        c.yaw = math.atan2(back[0], back[2])
        if self.home is None:
            self.home = (c.target.copy(), c.distance, c.yaw, c.pitch)
        self._sent = self._state()

    def start(self):
        self.active = True
        fov = float(self.settings.get("fov", 32.0))
        if not self.fov_matched and self.home is not None:
            # the atlas's field of view, not the player's - and the camera backed off to keep the model the same
            # size on screen, so switching does not zoom the view
            k = math.tan(math.radians(SKETCHFAB_FOV) / 2) / math.tan(math.radians(fov) / 2)
            t, d, y, pch = self.home
            self.home = (t, d * k, y, pch)
            self.camera.distance *= k
            self.fov_matched = True
        self.camera.fov = fov
        self.page.runJavaScript(f"sfFov({fov:.3f})")
        self._t_last = time.perf_counter()
        self.timer.start()

    def stop(self):
        self.active = False
        self.timer.stop()

    def _state(self):
        c = self.camera
        return (tuple(np.round(c.target, 9)), round(c.distance, 9), round(c.yaw, 9), round(c.pitch, 9))

    def _tick(self):
        now = time.perf_counter()
        dt, self._t_last = now - self._t_last, now
        c = self.camera
        c.update()
        if self.auto_rotate and not c.animating and self._press is None:
            c.yaw -= math.radians(float(self.settings.get("auto_rotate_speed", 20.0)) * dt)
        state = self._state()
        if state != self._sent:
            self._sent = state
            eye = to_sf(c.eye() / self.scale)
            tgt = to_sf(c.target / self.scale)
            self.page.runJavaScript(f"sfSetCam({json.dumps(eye)},{json.dumps(tgt)})")
            self.changed.emit()

    # ------------------------------------------------------------------ the atlas's commands
    def duration(self):
        return float(self.settings.get("camera_duration", 0.55))

    def set_view(self, name):
        if self.home is None or name not in VIEWS:
            return
        yaw, pitch = VIEWS[name]
        c = self.camera
        # the atlas knows which way the body faces; for a model, "anterior" is the way its creator framed it
        c.animate_to(c.target, c.distance, self.home[2] + yaw, pitch, self.duration())

    def reset_view(self):
        if self.home is not None:
            self.camera.animate_to(*self.home, self.duration())

    def frame(self):
        if self.home is not None:
            c = self.camera
            self.camera.animate_to(self.home[0], self.home[1], c.yaw, c.pitch, self.duration())

    def key_orbit(self, dx, dy):
        step = float(self.settings.get("key_orbit_step", 15.0))
        c = self.camera
        c.animate_to(c.target, c.distance, c.yaw - math.radians(dx * step),
                     max(-math.radians(89.5), min(math.radians(89.5), c.pitch + math.radians(dy * step))),
                     min(self.duration(), 0.25))

    def key_zoom(self, direction):
        c = self.camera
        c.animate_to(c.target, max(0.005, c.distance * (0.8 ** direction)), c.yaw, c.pitch, min(self.duration(), 0.2))

    def toggle_auto_rotate(self):
        self.auto_rotate = not self.auto_rotate
        return self.auto_rotate

    # ------------------------------------------------------------------ mouse, exactly as the atlas viewport
    def mousePressEvent(self, e):
        self._press = e.position()
        self._last = e.position()
        self._button = e.button()
        self._moved = False
        self.setFocus()
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._press is None:
            return
        pos = e.position()
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
            self.camera.pan(d.x() * dpr * k, d.y() * dpr * k, self.height() * dpr)
        elif self._button == orbit_btn:
            k = float(self.settings.get("orbit_sensitivity", 0.35))
            sx = -1 if self.settings.get("invert_orbit_x") else 1
            sy = -1 if self.settings.get("invert_orbit_y") else 1
            self.camera.orbit(d.x() * k * sx, d.y() * k * sy)

    def mouseReleaseEvent(self, e):
        self._press = None
        self._moved = False
        self.setCursor(Qt.OpenHandCursor)

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if steps == 0:
            return
        if self.settings.get("invert_zoom"):
            steps = -steps
        factor = 0.87 ** (steps * float(self.settings.get("zoom_sensitivity", 1.0)))
        self.camera.dolly(factor, None)          # no picking through the API, so towards the centre

    def keyPressEvent(self, e):
        """The atlas's rebindable camera keys, matched against whatever they are currently bound to."""
        if self.cmds is not None:
            seq = QKeySequence(e.keyCombination())
            table = {"orbit_left": lambda: self.key_orbit(1, 0), "orbit_right": lambda: self.key_orbit(-1, 0),
                     "orbit_up": lambda: self.key_orbit(0, 1), "orbit_down": lambda: self.key_orbit(0, -1),
                     "zoom_in": lambda: self.key_zoom(1), "zoom_out": lambda: self.key_zoom(-1)}
            for action_id, fn in table.items():
                for s in self.cmds.shortcuts(action_id):
                    if s and QKeySequence(s).matches(seq) == QKeySequence.ExactMatch:
                        fn()
                        return
        super().keyPressEvent(e)
