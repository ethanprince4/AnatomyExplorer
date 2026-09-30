"""Isolated real-atlas GPU/input checks for source and --pick-diagnostics.

Only reads the bundled atlas, without saved settings, study data or caches.
"""
import argparse
import json
import math
import sys
import tempfile
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

import numpy as np


def pump(app, seconds=0.15):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.01)


def run_checks():
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent, QNativeGestureEvent, QPointingDevice, QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .__main__ import configure_qt
    from .config import DATA_DIR, DEFAULT_SETTINGS
    from .data import Dataset
    from .state import SceneState
    from .viewport import Viewport

    if QApplication.instance() is None:
        configure_qt()
    app = QApplication.instance() or QApplication([])
    ds = Dataset(DATA_DIR)
    settings = dict(DEFAULT_SETTINGS)
    state = SceneState(ds, settings)
    view = Viewport(ds, state, settings)
    view.setWindowTitle("Isolated atlas picking diagnostics")
    view.setAttribute(Qt.WA_ShowWithoutActivating)
    view.resize(640, 480)
    report = {"platform": sys.platform, "checks": [], "macos_gpu_run": sys.platform == "darwin",
              "physical_trackpad_verified": False}
    qt_errors = []
    old_hook = sys.excepthook
    sys.excepthook = lambda *args: qt_errors.append("".join(traceback.format_exception(*args)))

    def check(condition, name):
        report["checks"].append({"name": name, "passed": bool(condition)})
        if not condition:
            raise AssertionError(name)

    def gl_error():
        view.makeCurrent()
        try:
            return view.ctx.error
        finally:
            view.doneCurrent()

    def raw_ids():
        view.makeCurrent()
        try:
            w, h = view.renderer.size
            pixels = np.full((h, w, 4), np.nan, np.float32)
            view.renderer.gbuffer.read_into(pixels, components=4, attachment=2, dtype="f4")
            err = view.ctx.error
            check(err == "GL_NO_ERROR", "RGBA ID buffer read succeeds: " + err)
            check(np.isfinite(pixels[..., 0]).all(), "ID buffer read returns initialized finite pixels")
            return np.rint(pixels[..., 0]).astype(np.int32) - 1
        finally:
            view.doneCurrent()

    def candidates():
        # Interior pixels avoid boundary differences from logical click rounding.
        out = {}
        raw = raw_ids()
        for y in range(8, view.height() - 8, 8):
            for x in range(8, view.width() - 8, 8):
                gx, gy = view._gl_xy(QPoint(x, y))
                sid = int(raw[gy, gx])
                if sid not in out and (raw[max(0, gy-2):gy+3, max(0, gx-2):gx+3] == sid).all():
                    out[sid] = QPoint(x, y)
        check(-1 in out and len(out) >= 4, "Real atlas has background and at least three visible targets")
        return out

    try:
        view.show()
        pump(app, 0.6)
        check(view.renderer is not None, "OpenGL atlas initializes")
        report.update(gpu=view.ctx.info["GL_RENDERER"], gl_version=view.ctx.info["GL_VERSION"],
                      dpr=view.devicePixelRatioF(), logical_size=[view.width(), view.height()],
                      buffer_size=view.renderer.size, after_paint_gl_error=gl_error())
        points = candidates()
        real_ids = [sid for sid in points if sid >= 0]
        report["targets"] = [{"id": sid, "name": ds.structures[sid]["name"],
                              "logical_xy": [points[sid].x(), points[sid].y()]} for sid in real_ids]
        for sid in [-1] + real_ids[:6]:
            check(view.pick_at(points[sid]) == sid, f"Pointer selects expected atlas ID {sid}")
        check(gl_error() == "GL_NO_ERROR", "Single-pixel RGBA reads have no GL errors")

        clicked, contexts = [], []
        view.structureClicked.connect(lambda sid, mods: (clicked.append(sid), state.select([sid]) if sid >= 0 else state.clear_selection()))
        view.contextMenuRequested.connect(lambda sid, pos: contexts.append(sid))
        for sid in real_ids[:3]:
            QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, points[sid])
            check(clicked[-1] == sid, f"Normal mouse click selects structure {sid}")
            view._last_hover_pick = 0
            pos = QPointF(points[sid])
            event = QMouseEvent(QEvent.MouseMove, pos, pos, Qt.NoButton, Qt.NoButton, Qt.NoModifier)
            QApplication.sendEvent(view, event)
            check(state.hovered == sid, f"No-button pointer move refreshes hover to {sid}")

        target = real_ids[1]
        QTest.mouseClick(view, Qt.RightButton, Qt.NoModifier, points[target])
        check(contexts[-1] == target, "Right-click captures pointer target instead of previous selection")
        # Execute the real atlas context-menu and Hide handlers with a minimal
        # isolated window harness. Substitute only the blocking popup surface;
        # no MainWindow settings, caches or study widgets are initialized.
        from PySide6.QtGui import QAction
        from . import main_window
        from .main_window import MainWindow
        actions = {key: QAction(key) for key in ("frame", "xray", "isolate", "hide", "both_sides", "note")}
        harness = SimpleNamespace(quiz=None, cmds=SimpleNamespace(actions=actions), state=state, ds=ds,
                                  viewport=view, info=SimpleNamespace(show_welcome=lambda: None),
                                  content=SimpleNamespace(micro_for_structures=lambda ids: [],
                                                          histology_for_structures=lambda ids: []),
                                  on_structure_clicked=lambda sid, mods: state.select([sid]),
                                  pick_color=lambda: None)
        actions["hide"].triggered.connect(lambda: MainWindow.hide_selection(harness))

        class Popup:
            def __init__(self, parent):
                self.items = []

            def addAction(self, action, callback=None):
                action = QAction(action) if isinstance(action, str) else action
                self.items.append(action)
                return action

            def addSeparator(self):
                pass

            def exec(self, pos):
                check(actions["hide"] in self.items, "Real context menu offers Hide for pointer target")
                actions["hide"].trigger()

        old_menu = main_window.QMenu
        main_window.QMenu = Popup
        try:
            MainWindow.on_context_menu(harness, contexts[-1], QPoint())
        finally:
            main_window.QMenu = old_menu
        check(not state.visible_mask()[target], "Context target Hide changes visibility")
        check(view.pick_at(points[target]) != target, "Immediate pick after Hide cannot return stale hidden target")
        state.set_hidden([target], False)
        check(view.pick_at(points[target]) == target, "Immediate Show restores correct target before queued paint")

        settings["trackpad_mode"] = "Trackpad"
        center = QPointF(view.width()/2, view.height()/2)
        for mods, pixel, angle, label in (
            (Qt.NoModifier, QPoint(24, 8), QPoint(), "trackpad orbit"),
            (Qt.ShiftModifier, QPoint(12, 4), QPoint(), "trackpad pan"),
            (Qt.ControlModifier, QPoint(), QPoint(0, 30), "Windows precision pinch"),
        ):
            event = QWheelEvent(center, center, pixel, angle, Qt.NoButton, mods, Qt.ScrollUpdate, False)
            before = view.camera.view().copy()
            QApplication.sendEvent(view, event)
            view.pick_at(center)
            check(not np.array_equal(before, view.camera.view()), label + " changes camera")
            expected = view.camera.proj(view.renderer.size[0]/view.renderer.size[1]) @ view.camera.view()
            check(np.allclose(view.renderer.last_vp, expected), label + " pick uses current camera frame")

        for gesture, value, label in ((Qt.ZoomNativeGesture, 0.08, "macOS native pinch"),
                                      (Qt.RotateNativeGesture, 7.0, "macOS native rotate")):
            event = QNativeGestureEvent(gesture, QPointingDevice.primaryPointingDevice(), 2,
                                        center, center, center, value, QPointF())
            before = view.camera.view().copy()
            QApplication.sendEvent(view, event)
            view.pick_at(center)
            check(not np.array_equal(before, view.camera.view()), label + " changes camera")
            expected = view.camera.proj(view.renderer.size[0]/view.renderer.size[1]) @ view.camera.view()
            check(np.allclose(view.renderer.last_vp, expected), label + " pick uses current camera frame")

        for width, height, scale in ((641, 479, 0.67), (791, 533, 1.0), (640, 480, 0.5)):
            view.resize(width, height)
            settings["render_scale"] = scale
            view.reset_view(animate=False)
            view.pick_at(QPoint(0, 0))
            w, h = view.renderer.size
            check(view._gl_xy(QPointF(0, 0)) == (0, h-1), f"Top-left maps to top ID pixel at scale {scale}")
            check(view._gl_xy(QPointF(view.width()-0.01, view.height()-0.01)) == (w-1, 0),
                  f"Bottom-right maps to bottom ID pixel at scale {scale}")
            check(view.pick_at(QPointF(-0.1, 0)) == -1 and view.pick_at(QPointF(view.width(), 0)) == -1,
                  f"Outside viewport never selects at scale {scale}")
            pump(app)
            fresh = candidates()
            for sid in [k for k in fresh if k >= 0][:3]:
                check(view.pick_at(fresh[sid]) == sid, f"Fresh selection after resize/scale {scale}, ID {sid}")

        renderer = view.renderer
        real_fbo = renderer.gbuffer
        for value, label in ((None, "unwritten failed read"), (np.nan, "NaN"),
                             (np.inf, "infinity"), (2.5, "fractional ID"), (ds.n+1, "out-of-range ID")):
            def bad_read(buffer, value=value, **kwargs):
                if value is not None:
                    buffer[0] = value
            renderer.gbuffer = SimpleNamespace(read_into=bad_read)
            check(renderer.pick(10, 10) == -1, label + " cannot select an arbitrary structure")
            if value is None or not math.isfinite(value) or value > 1:
                check(renderer.world_at(10, 10) is None, label + " cannot yield a bogus world point")
        renderer.gbuffer = real_fbo
        check(not qt_errors, "Qt input/render callbacks raised no exceptions")
        report["passed"] = True
    except Exception:
        report.update(passed=False, error=traceback.format_exc())
    finally:
        if view.renderer is not None:
            if "real_fbo" in locals():
                view.renderer.gbuffer = real_fbo
            view.makeCurrent()
            view.renderer.release()
            view.doneCurrent()
        view.close()
        sys.excepthook = old_hook
        if qt_errors:
            report["qt_errors"] = qt_errors
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pick-diagnostics", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--report", type=Path, help="JSON report path (otherwise a new temp file)")
    args = parser.parse_args(argv)
    report = run_checks()
    if args.report:
        path = args.report
    else:
        with tempfile.NamedTemporaryFile(prefix="anatomy-picking-", suffix=".json", delete=False) as f:
            path = Path(f.name)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]),
                      "gpu": report.get("gpu"), "dpr": report.get("dpr"),
                      "error": report.get("error")}, indent=2))
    print("Picking diagnostics report:", path)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
