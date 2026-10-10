"""Capture what a user sees in the 3D view after opening each radiology case, through the real app code path.

    python tools/capture_radiology.py [case_id ...] [--out DIR] [--size WxH] [--window] [--screen NAME]

One process builds one MainWindow (the atlas loads once) and opens each requested case with
MainWindow.show_radiology(), exactly as the Radiology browser does. Per case it writes, into DIR
(default logs/radiology_capture/):

    <id>_3d.png    the 3D widget the user is looking at (the atlas viewport, or the case's reference model)
    <id>_window.png  (only with --window) the whole app window, for diagnosing layout
    <id>_pair.png  the scan (with the case's crop) on the left, the 3D capture on the right, one header line

and merges {id: {ok, errors, status, reference_ready, seconds, ...}} into DIR/report.json. Exceptions raised in
Qt slots and timers, Qt critical messages, status-bar messages and notice-bar messages are attributed to the case
that was being captured. Settings and progress are temporary; the real ones are never read or written.
"""
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

READY_TIMEOUT = 60.0            # seconds to wait for a case's reference model
MIN_FRAMES = 3                  # frames that must have been swapped after the scene settled
SETTLE_LIMIT = 4.0              # seconds to wait for two identical consecutive grabs
PAIR_WIDTH = 1800
HEADER_H = 30


def parse_args(argv):
    ids, out, size = [], ROOT / "logs" / "radiology_capture", (1600, 1000)
    flags = {}
    it = iter(argv)
    for a in it:
        if a == "--out":
            out = Path(next(it))
        elif a.startswith("--out="):
            out = Path(a[6:])
        elif a == "--size" or a.startswith("--size="):
            text = a[7:] if a.startswith("--size=") else next(it)
            w, h = text.lower().split("x")
            size = (int(w), int(h))
        elif a == "--window":
            flags["window"] = True
        elif a == "--screen" or a.startswith("--screen="):
            flags["screen"] = a[9:] if a.startswith("--screen=") else next(it)
        elif a in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        else:
            ids.append(a)
    return ids, Path(out), size, flags


class Recorder:
    """Everything that goes wrong or is said while one case is open."""

    def __init__(self):
        self.reset(None)

    def reset(self, case_id):
        self.case_id = case_id
        self.errors, self.status, self.qt = [], [], []

    def excepthook(self, kind, exc, tb):
        text = "".join(traceback.format_exception(kind, exc, tb)).strip()
        self.errors.append(text)
        sys.__stderr__.write(f"[{self.case_id}] {text.splitlines()[-1]}\n")

    def status_message(self, text):
        if text and (not self.status or self.status[-1] != text):
            self.status.append(text)


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


def main(argv):
    ids, out, size, flags = parse_args(argv)

    # Temporary user data and settings, before anything imports the user paths.
    import app.config as config
    scratch = tempfile.TemporaryDirectory(prefix="capture_radiology_")
    config.USER_DIR = Path(scratch.name) / "user"
    config.USER_DIR.mkdir()
    from PySide6.QtCore import QSettings, QtMsgType, qInstallMessageHandler
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, scratch.name)

    from PySide6.QtGui import QImage, QPainter, QColor, QFont
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt, QRect
    from app.__main__ import configure_qt

    rec = Recorder()
    sys.excepthook = rec.excepthook

    def qt_handler(kind, context, message):
        if kind in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            rec.errors.append("Qt critical: " + message)
        elif kind == QtMsgType.QtWarningMsg:
            rec.qt.append(message)
    qInstallMessageHandler(qt_handler)

    configure_qt()
    app = QApplication(["capture_radiology"])
    from app.ui.theme import apply_theme
    apply_theme(app)
    from app.data import Dataset
    from app.main_window import MainWindow

    out.mkdir(parents=True, exist_ok=True)
    report_path = out / "report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        report = {}

    t_start = time.time()
    ds = Dataset(config.DATA_DIR)
    win = MainWindow(ds, restore=False)
    win.statusBar().messageChanged.connect(rec.status_message)
    notice = win.notice
    original_notice = notice.show_message

    def noting(text, *args, **kwargs):
        rec.status_message("notice: " + str(text))
        rec.notices = getattr(rec, "notices", 0) + 1
        return original_notice(text, *args, **kwargs)
    notice.show_message = noting

    if flags.get("screen"):
        # Open on the named monitor (its scaling decides the device pixel ratio the 3D view renders at).
        screen = next((sc for sc in app.screens() if sc.name() == flags["screen"]), None)
        if screen is None:
            raise SystemExit("no screen %r; screens: %s" % (flags["screen"], ", ".join(sc.name() for sc in app.screens())))
        geo = screen.availableGeometry()
        win.move(geo.x() + 40, geo.y() + 40)
    win.resize(*size)
    win.show()
    pump(app, 1.5)
    print(f"app ready in {time.time() - t_start:.1f} s, window {win.width()}x{win.height()}")

    cases = {c.id: c for c in win.radiology_cases}
    wanted = ids or list(cases)
    unknown = [i for i in wanted if i not in cases]
    if unknown:
        print("unknown case id(s): " + ", ".join(unknown), file=sys.stderr)
        wanted = [i for i in wanted if i in cases]

    frames = {"widget": None, "count": 0}

    def count_frame():
        frames["count"] += 1

    def watch(widget):
        """Count frames swapped by the 3D widget the user is looking at."""
        if frames["widget"] is widget:
            return
        if frames["widget"] is not None:
            try:
                frames["widget"].frameSwapped.disconnect(count_frame)
            except (RuntimeError, TypeError):
                pass
        frames["widget"] = widget
        widget.frameSwapped.connect(count_frame)

    def grab(widget):
        # QWidget.grab renders the GL picture and the child overlay that draws the 3D labels; grabFramebuffer alone
        # would leave the labels out.
        return widget.grab().toImage().convertToFormat(QImage.Format_RGB32)

    def blank(image):
        """True when the picture is one flat colour (an unrendered or cleared widget)."""
        if image.isNull() or image.width() < 8 or image.height() < 8:
            return True
        first = image.pixel(0, 0)
        for y in range(0, image.height(), max(1, image.height() // 40)):
            for x in range(0, image.width(), max(1, image.width() // 40)):
                if image.pixel(x, y) != first:
                    return False
        return True

    def scan_image(case):
        image = QImage(str(case.image))
        if image.isNull():
            return image
        if case.crop:
            x0, y0, x1, y1 = (float(v) for v in case.crop)
            image = image.copy(int(x0 * image.width()), int(y0 * image.height()),
                               max(1, int((x1 - x0) * image.width())), max(1, int((y1 - y0) * image.height())))
        return image.convertToFormat(QImage.Format_RGB32)

    def make_pair(case, scan, shot):
        a_scan = scan.width() / scan.height() if not scan.isNull() else 1.0
        a_shot = shot.width() / shot.height()
        height = max(200, int(PAIR_WIDTH / (a_scan + a_shot)))
        sw, gw = int(height * a_scan), int(height * a_shot)
        pair = QImage(sw + gw, height + HEADER_H, QImage.Format_RGB32)
        pair.fill(QColor("#10161c"))
        p = QPainter(pair)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if scan.isNull():
            p.setPen(QColor("#e08080"))
            p.drawText(QRect(0, HEADER_H, sw, height), Qt.AlignCenter, f"scan image missing\n{case.image.name}")
        else:
            p.drawImage(QRect(0, HEADER_H, sw, height), scan)
        p.drawImage(QRect(sw, HEADER_H, gw, height), shot)
        p.setPen(QColor("#ffffff"))
        font = QFont()
        font.setPixelSize(15)
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRect(8, 0, sw + gw - 16, HEADER_H), Qt.AlignVCenter | Qt.AlignLeft,
                   f"{case.id}   |   {case.modality}   |   {case.title}")
        p.end()
        return pair

    for n, case_id in enumerate(wanted, 1):
        case = cases[case_id]
        rec.reset(case_id)
        rec.notices = 0
        t0 = time.time()
        micro = bool(case.scene.get("micro") and case.scene.get("micro_focus"))
        ready = None
        timed_out = False
        try:
            win.show_radiology(case_id)
            pump(app, 0.1)
            if micro:
                ready = False
                deadline = time.time() + READY_TIMEOUT
                grace = None
                while time.time() < deadline:
                    app.processEvents()
                    view = getattr(win, "_radiology_model_view", None)
                    if view is not None and getattr(view, "_radiology_ready", False):
                        ready = True
                        break
                    if rec.errors or rec.notices:      # failed already; do not sit out the timeout
                        grace = grace or time.time() + 3.0
                        if time.time() > grace:
                            break
                    time.sleep(0.01)
                timed_out = not ready
                if timed_out and not (rec.errors or rec.notices):
                    rec.errors.append(f"reference not ready (timeout {READY_TIMEOUT:.0f} s)")
                elif timed_out:
                    rec.errors.append("reference not ready (load failed, see above)")
            widget = win.anatomy_tab.gl_widget
            watch(widget)
            pump(app, 0.3)
            # Settled: enough frames drawn since the scene was applied and two grabs in a row agree.
            start_frames = frames["count"]
            end = time.time() + SETTLE_LIMIT
            previous = None
            image = None
            while time.time() < end:
                widget.update()
                pump(app, 0.15)
                image = grab(widget)
                if frames["count"] - start_frames >= MIN_FRAMES and previous is not None and image == previous:
                    break
                previous = image
            if image is None:
                image = grab(widget)
            if not widget.isVisible():
                rec.errors.append("3D widget is not visible")
            if blank(image):
                rec.errors.append("3D capture is blank")
            image.save(str(out / f"{case_id}_3d.png"))
            if flags.get("window"):
                win.grab().save(str(out / f"{case_id}_window.png"))
            make_pair(case, scan_image(case), image).save(str(out / f"{case_id}_pair.png"))
            if not win.radiology_panel.labels_on.isChecked():
                rec.status.append("note: Labels box is off")
        except Exception:
            rec.errors.append(traceback.format_exc().strip())
        for message in rec.status:      # the app says it could not do something: that is a failure of the case
            low = message.lower()
            if any(word in low for word in ("unavailable", "could not", "failed", "cannot")):
                rec.errors.append("status message: " + message)
        seconds = time.time() - t0
        entry = {"ok": not rec.errors, "errors": list(rec.errors), "status": list(rec.status),
                 "reference_ready": ready, "seconds": round(seconds, 2)}
        if rec.qt:
            entry["qt_warnings"] = rec.qt[:20]
        report[case_id] = entry
        report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")
        flag = "ok " if entry["ok"] else "ERR"
        why = "" if entry["ok"] else "  " + entry["errors"][0].strip().splitlines()[-1][:110]
        print(f"[{n}/{len(wanted)}] {flag} {case_id:<34} {seconds:5.1f} s{why}")

    failures = [i for i in wanted if not report[i]["ok"]]
    print(f"{len(wanted)} cases in {time.time() - t_start:.1f} s, {len(failures)} with errors. Output: {out}")
    # No window.close(): tearing down GL contexts at exit crashes on some drivers, and everything is already written.
    import shutil
    shutil.rmtree(scratch.name, ignore_errors=True)
    sys.stdout.flush()
    os._exit(1 if failures else 0)     # returning would destroy the window and GL contexts, which can crash


if __name__ == "__main__":
    main(sys.argv[1:])
