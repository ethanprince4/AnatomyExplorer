"""Q2 follow-up: do the scene's own translucent widgets (breadcrumb, title, dock, card corners) blend with the 3D image,
and where does a top-level overlay window sit relative to the cards?

python chrome.py --method screen|bitmap [--overlay none|child|toolwin]
Method: grab the desktop with the chrome visible (A), hide the chrome and grab again (B, only the 3D image).
For every chrome pixel with alpha < 250 (from QWidget.grab, Qt's own rendering) predict
  A = alpha*src + (1-alpha)*B   and compare red and blue (green carries the frame counter).
With --overlay, one label rect is also placed across the parts card to see who is on top."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
ap = argparse.ArgumentParser()
ap.add_argument("--method", required=True)
ap.add_argument("--overlay", default="none")
ap.add_argument("--translucent", type=int, default=0)
args = ap.parse_args()

from PySide6.QtCore import Qt, QTimer, QRect, QPoint
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QApplication, QWidget, QTextEdit, QVBoxLayout, QLabel
app = QApplication([])
from rendercanvas.qt import QRenderWidget
from app.ui.theme import apply_theme
apply_theme(app)
from app.ui.studio_scene import StudioScene
from common import Renderer


def _hook(*a):
    sys.__excepthook__(*a)
    app.exit(3)


sys.excepthook = _hook


class Overlay(QWidget):
    def __init__(self, parent=None, flags=Qt.Widget):
        super().__init__(parent, flags)
        self.rect_ = QRect()
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect_, QColor(0, 255, 0))
        p.end()


canvas = QRenderWidget(present_method=args.method, update_mode="continuous", max_fps=240, vsync=False)
r = Renderer(canvas)
canvas.request_draw(r.draw)
parts = QTextEdit()
parts.setPlainText("Parts list placeholder " * 20)
reveal = QWidget()
QVBoxLayout(reveal).addWidget(QLabel("reveal controls"))
teaching = QWidget()
teaching.hide()
studio = StudioScene(canvas, parts, reveal, QTextEdit(), teaching)
studio.set_subject("Tooth", "spike", "3D models", 33)
studio.setWindowFlag(Qt.WindowStaysOnTopHint, True)
studio.resize(1100, 700)
studio.show()
studio.move(30, 30)
if args.translucent:
    for w in (studio.breadcrumb, studio.subject):
        w.setAttribute(Qt.WA_TranslucentBackground, True)
        w.setAttribute(Qt.WA_NoSystemBackground, True)
res = {"translucent": args.translucent, "method": args.method, "overlay": args.overlay}
chrome = {"breadcrumb": studio.breadcrumb, "subject": studio.subject, "dock": studio.dock, "parts_card": studio.cards["parts"]}
overlay = None


def shot():
    rg = QRect(studio.mapToGlobal(QPoint(0, 0)), studio.size())
    img = app.primaryScreen().grabWindow(0, rg.x(), rg.y(), rg.width(), rg.height()).toImage()
    return img, img.width() / rg.width(), img.height() / rg.height()


def px(shotv, x, y):
    img, sx, sy = shotv
    c = img.pixelColor(min(img.width() - 1, max(0, int(x * sx))), min(img.height() - 1, max(0, int(y * sy))))
    return c.red(), c.green(), c.blue()


A = {}


def phase1():
    global overlay
    studio.arrange()
    if args.overlay != "none":
        card = studio.cards["parts"].geometry()
        rc = QRect(card.x() + card.width() // 2 - 40, card.y() + 30, 80, 40)     # fully inside the card
        if args.overlay == "child":
            overlay = Overlay(studio)
            overlay.setGeometry(studio.rect())
            overlay.rect_ = rc
            overlay.stackUnder(studio.breadcrumb)
        else:
            overlay = Overlay(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput)
            overlay.setAttribute(Qt.WA_ShowWithoutActivating, True)
            overlay.setGeometry(QRect(studio.mapToGlobal(QPoint(0, 0)), studio.size()))
            overlay.rect_ = rc
        overlay.show()
        if args.overlay == "toolwin":
            overlay.raise_()
        res["overlay_rect"] = [rc.x(), rc.y(), rc.width(), rc.height()]
    QTimer.singleShot(1200, phase2)


def phase2():
    A["shot"] = shot()
    # Qt's own rendering of each chrome widget (with alpha)
    A["grabs"] = {k: (w.grab().toImage(), w.geometry()) for k, w in chrome.items()}
    if overlay is not None:
        c = studio.cards["parts"].geometry()
        rc = overlay.rect_
        A["zo"] = [px(A["shot"], rc.x() + 6, rc.y() + 6), px(A["shot"], rc.right() - 6, rc.bottom() - 6)]
    for w in chrome.values():
        w.hide()
    for w in studio.cards.values():
        w.hide()
    if overlay is not None:
        overlay.hide()
    QTimer.singleShot(600, phase3)


def phase3():
    B = shot()
    out = {}
    for k, (img, g) in A["grabs"].items():
        n_part = n_clear_alpha0 = ok = alpha0_ok = n_alpha0 = 0
        worst = 0
        usable = 0
        for j in range(0, img.height(), 1):
            for i in range(0, img.width(), 1):
                c = img.pixelColor(i, j)
                a = c.alpha()
                if a >= 250:
                    continue
                lx = g.x() + (i + 0.5) * g.width() / img.width()
                ly = g.y() + (j + 0.5) * g.height() / img.height()
                u = px(B, lx, ly)
                if not (u[0] > 240 and u[2] > 240 and u[1] <= 130):
                    continue                    # underlying is not the clear colour (mesh edge etc.): cannot predict
                usable += 1
                af = a / 255.0
                got = px(A["shot"], lx, ly)
                pred = (af * c.red() + (1 - af) * u[0], af * c.blue() + (1 - af) * u[2])
                err = max(abs(got[0] - pred[0]), abs(got[2] - pred[1]))
                if a == 0:
                    if n_alpha0 == 0:
                        res.setdefault('first_transparent_px', {})[k] = {'screen_shows': list(got), 'image_only': list(u)}
                    n_alpha0 += 1
                    alpha0_ok += err <= 6
                else:
                    n_part += 1
                    ok += err <= 14
                    worst = max(worst, err)
        out[k] = {"partial_alpha_px": n_part, "partial_ok": ok, "transparent_px": n_alpha0, "transparent_ok": alpha0_ok, "worst_partial_err": round(worst)}
    res["chrome"] = out
    if "zo" in A:
        res["label_over_card_pixels"] = A["zo"]
    print("RESULT " + json.dumps(res), flush=True)
    app.quit()


QTimer.singleShot(1500, phase1)
app.exec()
