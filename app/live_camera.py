"""Opt-in live camera feed: while the app runs it keeps a small JSON file with the camera of the 3D view on screen.

Off unless the environment variable ANATOMY_CAMERA_FEED is set (see feed_path). tools/camera_now.py reads the file, so a
screenshot can carry a replayable view. Nothing here runs in the paint path: one 40 ms QTimer, and it never raises."""
import json
import logging
import math
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

log = logging.getLogger(__name__)

ENV_VAR = "ANATOMY_CAMERA_FEED"
SCHEMA = "anatomy.camera.v1"
FILE_NAME = "live_camera.json"
TICK_MS = 40
HEARTBEAT_S = 2.0


def default_path():
    """Fixed on purpose: the temp folder, from the standard library only, so the app (whatever its launcher does
    to config.USER_DIR) and tools/camera_now.py always compute the same file."""
    return Path(tempfile.gettempdir()) / f"AnatomyExplorer-{FILE_NAME}"


def feed_path(env=None):
    """Where the feed file goes, or None when the feature is off. Unset, empty or "0" is off; "1" is the default
    path; any other value is taken as the file path."""
    value = (os.environ if env is None else env).get(ENV_VAR, "").strip()
    if value in ("", "0"):
        return None
    if value == "1":
        return default_path()
    return Path(value)


def _vec(v):
    return [float(x) for x in v]


def _num(v, default=None):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _camera_block(cam):
    target = _vec(getattr(cam, "target", (0.0, 0.0, 0.0)))
    distance = _num(getattr(cam, "distance", None), 0.0)
    yaw = _num(getattr(cam, "yaw", None), 0.0)
    pitch = _num(getattr(cam, "pitch", None), 0.0)
    forward = _vec(cam.forward_dir())              # from the target towards the camera
    eye = _vec(cam.eye())
    block = {
        "target": target, "distance": distance, "yaw": yaw, "pitch": pitch,
        "yaw_deg": math.degrees(yaw), "pitch_deg": math.degrees(pitch),
        "eye": eye, "look_dir": [-x for x in forward],
        "fov_deg": _num(getattr(cam, "fov", None)),
    }
    if hasattr(cam, "ortho"):
        block["ortho"] = bool(cam.ortho)
        block["ortho_width"] = _num(getattr(cam, "ortho_width", None))
    return block, [target, distance, yaw, pitch]


def _cut_block(vp):
    cut = {}
    on = getattr(vp, "clip_on", None)
    if on is not None:
        cut["clip_on"] = [bool(x) for x in on]
        cut["clip_pos"] = [float(x) for x in getattr(vp, "clip_pos", ())]
        cut["clip_flip"] = [bool(x) for x in getattr(vp, "clip_flip", ())]
        if hasattr(vp, "radiology_slice"):
            cut["radiology_slice"] = bool(vp.radiology_slice)
    if hasattr(vp, "cut_on"):
        cut["cut_away"] = bool(vp.cut_on)
    return cut or None


def build_payload(win):
    """The camera of the view on screen as a JSON-able dict (without seq/time/pid). Raises only on a broken window."""
    cur = win.center.currentWidget()
    micro = getattr(win, "micro_tabs", {}) or {}
    model_key = next((k for k, v in micro.items() if v is cur), None)
    is_model = model_key is not None and hasattr(cur, "gl_widget")
    is_atlas = cur is getattr(win, "anatomy_tab", None)
    vp = win.active_viewport()
    shown = False
    if is_model or is_atlas:
        try:
            shown = bool(vp.isVisibleTo(win))
        except RuntimeError:
            shown = False
    page = {"class": type(cur).__name__ if cur is not None else None,
            "object_name": cur.objectName() if cur is not None else None}
    try:
        page["tab"] = win.center.tabText(win.center.currentIndex())
    except (RuntimeError, AttributeError):
        pass
    payload = {"schema": SCHEMA, "page": page, "camera_visible": shown,
               "view": "model" if is_model else "atlas", "model": None, "case": None}
    if is_model:
        entry = getattr(cur, "entry", None)
        payload["model"] = {"key": model_key, "id": getattr(entry, "id", None),
                            "name": getattr(entry, "name", None)}
        payload["named_view"] = getattr(cur, "_current_view", None)
    elif is_atlas:
        panel = getattr(win, "radiology_panel", None)
        case = getattr(panel, "case", None)
        if case is not None and panel.isVisibleTo(win):
            payload["case"] = {"id": getattr(case, "id", None), "title": getattr(case, "title", None)}
    camera, saved = _camera_block(vp.camera)
    payload["camera"] = camera
    payload["saved_view_camera"] = saved
    cut = _cut_block(vp)
    if cut:
        payload["cut"] = cut
    dpr = 1.0
    try:
        dpr = float(vp.devicePixelRatioF())
    except (AttributeError, RuntimeError, TypeError):
        pass
    payload["viewport"] = {"width": int(vp.width()), "height": int(vp.height()), "device_pixel_ratio": dpr}
    return payload


class LiveCameraFeed(QObject):
    def __init__(self, win, path):
        super().__init__(win)
        self.win = win
        self.path = Path(path)
        self.seq = 0
        self._last = None
        self._last_write = 0.0
        self._warned = False
        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def tick(self):
        try:
            payload = build_payload(self.win)
            now = time.time()
            if payload == self._last and now - self._last_write < HEARTBEAT_S:
                return
            record = dict(payload, seq=self.seq + 1, time=now,
                          time_iso=datetime.fromtimestamp(now).astimezone().isoformat(timespec="milliseconds"),
                          pid=os.getpid())
            if self._write(record):
                self.seq += 1
                self._last, self._last_write = payload, now
        except Exception as exc:                       # the feed must never disturb the app
            if not self._warned:
                self._warned = True
                log.warning("live camera feed: %s", exc)

    def _write(self, record):
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(record), encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except OSError:                                # a reader holds it, or the folder is busy: next tick
            try:
                tmp.unlink()
            except OSError:
                pass
            return False

    def stop(self):
        self.timer.stop()
        for p in (self.path, self.path.with_name(self.path.name + ".tmp")):
            try:
                p.unlink()
            except OSError:
                pass


def start(win):
    """The feed for `win` when ANATOMY_CAMERA_FEED asks for one, else None (no timer, no cost)."""
    path = feed_path()
    if path is None:
        return None
    feed = LiveCameraFeed(win, path)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(feed.stop)
    return feed
