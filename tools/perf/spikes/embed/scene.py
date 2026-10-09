"""Q2: a QRenderWidget inside the real StudioScene, with a native card and a transparent painted overlay on top.

python scene.py --method screen|bitmap [--overlay child|toolwin] [--when before|after]
  --when before: the canvas is handed to StudioScene before the first show (what the app does)
  --when after : the canvas already renders as its own window and is reparented afterwards
Grabs the desktop with QScreen.grabWindow and samples pixels. Prints one JSON line."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
ap = argparse.ArgumentParser()
ap.add_argument("--method", required=True)
ap.add_argument("--overlay", default="child")
ap.add_argument("--when", default="before")
args = ap.parse_args()

from PySide6.QtCore import Qt, QTimer, QRect, QPoint
from PySide6.QtGui import QPainter, QColor, QFont
from PySide6.QtWidgets import QApplication, QWidget, QTextEdit, QVBoxLayout, QLabel
app = QApplication([])
from rendercanvas.qt import QRenderWidget
from app.ui.theme import apply_theme
apply_theme(app)
from app.ui.studio_scene import StudioScene
from common import Renderer

LABELS = [("Alpha", QColor(255, 255, 0)), ("Beta", QColor(0, 255, 255)), ("Gamma", QColor(0, 255, 0)), ("Delta", QColor(0, 0, 255, 128))]


class Overlay(QWidget):
    """Transparent, input-transparent label layer painted with QPainter (what ModelViewport does on its GL widget)."""

    def __init__(self, parent=None, flags=Qt.Widget):
        super().__init__(parent, flags)
        self.rects = []
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setFont(QFont("Segoe UI", 11))
        for rc, (name, col) in zip(self.rects, LABELS):
            p.fillRect(rc, col)
            p.setPen(Qt.black)
            p.drawText(rc, Qt.AlignCenter, name)
        p.end()


canvas = QRenderWidget(present_method=args.method, update_mode="continuous", max_fps=240, vsync=False)
canvas.setObjectName("spikeCanvas")
r = Renderer(canvas)
canvas.request_draw(r.draw)
if args.when == "after":
    canvas.resize(400, 300)
    canvas.show()


def mk(text):
    w = QTextEdit()
    w.setPlainText(text)
    w.setReadOnly(True)
    return w


def build():
    global studio, overlay
    parts = mk("Parts list placeholder " * 20)
    reveal = QWidget()
    QVBoxLayout(reveal).addWidget(QLabel("reveal controls"))
    teaching = QWidget()
    teaching.hide()
    studio = StudioScene(canvas, parts, reveal, mk("sections"), teaching)
    studio.set_subject("Tooth", "spike", "3D models", 33)
    studio.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    studio.resize(1100, 700)
    studio.show()
    studio.move(30, 30)
    if args.overlay == "child":
        overlay = Overlay(studio)
    else:
        overlay = Overlay(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput)
        overlay.setAttribute(Qt.WA_ShowWithoutActivating, True)



res = {"method": args.method, "overlay": args.overlay, "when": args.when, "dpr": canvas.devicePixelRatioF()}


def layout_overlay():
    studio.arrange()
    vg = canvas.geometry()
    blockers = [w.geometry() for w in studio.findChildren(QWidget)
                if w.parent() is studio and w.isVisible() and w is not canvas and w is not overlay]
    cx, cy = vg.center().x(), vg.center().y()
    cands = [QRect(cx - 70, cy + 20, 140, 36)]  # over the mesh
    for dx in range(0, max(1, vg.width() - 160), 40):
        for dy in range(0, max(1, vg.height() - 40), 30):
            rc = QRect(vg.x() + dx, vg.y() + dy, 120, 32)
            if len(cands) < 4 and not any(rc.intersects(b) for b in blockers) and not any(rc.intersects(c) for c in cands):
                cands.append(rc)
    while len(cands) < 4:
        cands.append(QRect(cx + 120, cy - 60 - 40 * len(cands), 100, 30))
    overlay.rects = [QRect(c.x() - vg.x(), c.y() - vg.y(), c.width(), c.height()) for c in cands[:4]]
    if args.overlay == "child":
        overlay.setGeometry(vg)
        overlay.stackUnder(studio.breadcrumb)
    else:
        overlay.setGeometry(QRect(canvas.mapToGlobal(QPoint(0, 0)), vg.size()))
    overlay.show()
    if args.overlay != "child":
        overlay.raise_()
    overlay.update()


def shot(rect_global):
    return app.primaryScreen().grabWindow(0, rect_global.x(), rect_global.y(), rect_global.width(), rect_global.height()).toImage()


def sampler(img, rect_global):
    sx = img.width() / rect_global.width()
    sy = img.height() / rect_global.height()

    def at(lx, ly):
        c = img.pixelColor(min(img.width() - 1, int(lx * sx)), min(img.height() - 1, int(ly * sy)))
        return (c.red(), c.green(), c.blue())
    return at


def near(a, b, t=8):
    return all(abs(x - y) <= t for x, y in zip(a, b))


def step1():
    if args.method == "screen":
        res["winid_at_first_show"] = int(canvas.winId())
    layout_overlay()
    QTimer.singleShot(1500, step2)


def step2():
    layout_overlay()
    QTimer.singleShot(800, measure)


def measure():
    studio.arrange()
    vg = canvas.geometry()
    origin = studio.mapToGlobal(QPoint(0, 0))
    rg = QRect(origin, studio.size())
    f_a = r.frame
    img = shot(rg)
    at = sampler(img, rg)

    def nat(w):
        wid = w.internalWinId()
        return {"native_attr": bool(w.testAttribute(Qt.WA_NativeWindow)), "winid": int(wid) if wid else 0}
    parts_card = studio.cards["parts"]
    res["native"] = {"canvas": nat(canvas), "card": nat(parts_card), "overlay": nat(overlay), "studio": nat(studio)}
    if args.method == "screen":
        res["winid_now"] = int(canvas.winId())
    res["canvas_geom"] = [vg.x(), vg.y(), vg.width(), vg.height()]
    res["swapchain"] = list(r.last_tex_size)
    res["canvas_phys"] = list(canvas.get_physical_size())
    res["card_visible_flag"] = parts_card.isVisible()
    res["card_geom"] = [parts_card.x(), parts_card.y(), parts_card.width(), parts_card.height()]
    cimg = parts_card.grab().toImage()
    cg = parts_card.geometry()
    ok = bad_clear = tot = alphas = 0
    for i in range(24):
        for j in range(24):
            lx = 6 + (cg.width() - 12) * i / 23
            ly = 6 + (cg.height() - 12) * j / 23
            ex = cimg.pixelColor(int(lx * cimg.width() / cg.width()), int(ly * cimg.height() / cg.height()))
            if ex.alpha() < 255:
                alphas += 1
                continue
            got = at(cg.x() + lx, cg.y() + ly)
            tot += 1
            ok += near(got, (ex.red(), ex.green(), ex.blue()), 10)
            bad_clear += (got[0] > 240 and got[2] > 240 and got[1] <= 130)
    res["card"] = {"samples": tot, "match_qt_render": ok, "magenta_clear_showing": bad_clear, "translucent_skipped": alphas}
    lab = []
    for rc, (name, col) in zip(overlay.rects, LABELS):
        pts = [(rc.x() + 4, rc.y() + 4), (rc.right() - 4, rc.bottom() - 4), (rc.x() + 4, rc.bottom() - 4)]
        got = [at(vg.x() + x, vg.y() + y) for x, y in pts]
        want = (col.red(), col.green(), col.blue())
        if col.alpha() < 255:       # half-transparent blue over the magenta clear colour: R ~ 128, B 255
            want = (128, got[0][1] // 2, 255)
        lab.append({"name": name, "expected": list(want), "got": got, "ok": all(near(g, want, 6 if col.alpha() == 255 else 12) if col.alpha() == 255 else (112 <= g[0] <= 144 and g[2] > 235) for g in got)})
    res["labels"] = lab
    blockers = [w.geometry() for w in studio.findChildren(QWidget) if w.parent() is studio and w.isVisible() and w is not canvas and w is not overlay]
    blockers += [QRect(vg.x() + o.x() - 4, vg.y() + o.y() - 4, o.width() + 8, o.height() + 8) for o in overlay.rects]
    mag = mesh = other = 0
    counters = []
    for i in range(30):
        for j in range(20):
            x = vg.x() + 4 + (vg.width() - 8) * i / 29
            y = vg.y() + 4 + (vg.height() - 8) * j / 19
            if any(b.contains(int(x), int(y)) for b in blockers):
                continue
            c = at(x, y)
            if c[0] > 240 and c[2] > 240 and c[1] <= 130:
                mag += 1
                counters.append(c[1])
            elif c[0] > c[2] + 20 and c[0] >= c[1]:
                mesh += 1
            else:
                other += 1
    res["viewport_scan"] = {"clear_magenta": mag, "mesh_yellow": mesh, "other": other}
    res["frame_counter_samples"] = counters[:3]
    QTimer.singleShot(400, stale)


def stale():
    vg = canvas.geometry()
    rg = QRect(studio.mapToGlobal(QPoint(0, 0)), studio.size())
    at = sampler(shot(rg), rg)
    res["corner_after"] = list(at(vg.x() + 6, vg.y() + 6))
    res["last_frame"] = r.frame
    res["size_mismatch_frames"] = r.size_mismatch
    print("RESULT " + json.dumps(res), flush=True)
    app.quit()


def start():
    build()
    res["frames_before_reparent"] = r.frame
    QTimer.singleShot(1500, step1)


if args.when == "after":
    QTimer.singleShot(1500, start)      # the canvas has been rendering as its own window for 1.5 s
else:
    build()
    QTimer.singleShot(1500, step1)
app.exec()
