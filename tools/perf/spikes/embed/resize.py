"""Q3: resize and move a StudioScene hosting the wgpu canvas 20 times (then 20 rapid-fire), checking every step by
grabbing the desktop and sampling pixels.

python resize.py --method screen|bitmap
Per step: swapchain == canvas physical size, frame counter in the clear colour is fresh, no black pixels at the edges,
the mesh is at the centre, the card is still painted. Python/wgpu/rendercanvas log records are counted."""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
ap = argparse.ArgumentParser()
ap.add_argument("--method", required=True)
args = ap.parse_args()

from PySide6.QtCore import Qt, QTimer, QRect, QPoint
from PySide6.QtWidgets import QApplication, QWidget, QTextEdit, QVBoxLayout, QLabel
app = QApplication([])


def _hook(*a):
    sys.__excepthook__(*a)
    app.exit(3)


sys.excepthook = _hook
from rendercanvas.qt import QRenderWidget
from app.ui.theme import apply_theme
apply_theme(app)
from app.ui.studio_scene import StudioScene
from common import Renderer


class Collect(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.records = []

    def emit(self, rec):
        self.records.append(f"{rec.name}:{rec.levelname}:{rec.getMessage()[:160]}")


collect = Collect()
logging.getLogger().addHandler(collect)
logging.getLogger().setLevel(logging.WARNING)

canvas = QRenderWidget(present_method=args.method, update_mode="continuous", max_fps=240, vsync=False)
r = Renderer(canvas)
canvas.request_draw(r.draw)
try:
    r.device._device_lost_callback = None
except Exception:
    pass
parts = QTextEdit()
parts.setPlainText("Parts list placeholder " * 20)
reveal = QWidget()
QVBoxLayout(reveal).addWidget(QLabel("reveal controls"))
sections = QTextEdit()
teaching = QWidget()
teaching.hide()
studio = StudioScene(canvas, parts, reveal, sections, teaching)
studio.setWindowFlag(Qt.WindowStaysOnTopHint, True)
studio.resize(1100, 700)
studio.show()
studio.move(30, 30)

SIZES = [(1100, 700), (700, 500), (1700, 1000), (900, 600), (1400, 900), (640, 480), (1200, 1100), (800, 800), (1600, 700), (1000, 650)]
MOVES = [(30, 30), (200, 100), (60, 250), (400, 40), (10, 10)]
steps = [(SIZES[i % len(SIZES)][0] + (i * 7) % 40, SIZES[i % len(SIZES)][1] + (i * 11) % 30, *MOVES[i % len(MOVES)]) for i in range(20)]
results = []
state = {"i": 0}


def grab_check(label, expect_wh):
    rg = QRect(studio.mapToGlobal(QPoint(0, 0)), studio.size())
    img = app.primaryScreen().grabWindow(0, rg.x(), rg.y(), rg.width(), rg.height()).toImage()
    sx, sy = img.width() / rg.width(), img.height() / rg.height()

    def at(x, y):
        c = img.pixelColor(min(img.width() - 1, max(0, int(x * sx))), min(img.height() - 1, max(0, int(y * sy))))
        return (c.red(), c.green(), c.blue())
    vg = canvas.geometry()
    blockers = [wd.geometry() for wd in studio.findChildren(QWidget) if wd.parent() is studio and wd.isVisible() and wd is not canvas]
    other = mag = mesh = 0
    ctr = None
    for i in range(40):
        for j in range(26):
            x = vg.x() + 3 + (vg.width() - 7) * i / 39
            y = vg.y() + 3 + (vg.height() - 7) * j / 25
            if any(b.contains(int(x), int(y)) for b in blockers):
                continue
            c = at(x, y)
            if c[0] > 240 and c[2] > 240 and c[1] <= 130:
                mag += 1
                ctr = c[1] if ctr is None else ctr
            elif c[0] > c[2] + 20 and c[0] >= c[1]:
                mesh += 1
            else:
                other += 1
    cx, cy = vg.center().x(), vg.center().y()
    centre_covered = any(b.contains(cx, cy) for b in blockers)
    centre = at(cx, cy)
    card = studio.cards["parts"]
    cimg = card.grab().toImage()
    cg = card.geometry()
    ok = tot = 0
    if not card.isHidden():
        for i in range(10):
            for j in range(10):
                lx, ly = 6 + (cg.width() - 12) * i / 9, 6 + (cg.height() - 12) * j / 9
                ex = cimg.pixelColor(int(lx * cimg.width() / cg.width()), int(ly * cimg.height() / cg.height()))
                got = at(cg.x() + lx, cg.y() + ly)
                tot += 1
                ok += all(abs(a - b) <= 10 for a, b in zip(got, (ex.red(), ex.green(), ex.blue())))
    latest = (r.frame - 1) % 128
    age = None if ctr is None else (latest - ctr) % 128
    phys = tuple(canvas.get_physical_size())
    return {"label": label, "logical": [studio.width(), studio.height()], "canvas_phys": list(phys), "swapchain": list(r.last_tex_size),
            "swap_ok": tuple(r.last_tex_size) == phys, "frame_age": age, "other_px": other, "clear_px": mag, "mesh_px": mesh,
            "centre_is_mesh": None if centre_covered else bool(centre[0] > centre[2] + 20), "card_match": f"{ok}/{tot}"}


def next_step():
    i = state["i"]
    if i >= len(steps):
        return phase_b()
    w, h, x, y = steps[i]
    n0 = len(r.stamps)
    t0 = time.perf_counter()
    studio.resize(w, h)
    studio.move(x, y)
    state["t0"], state["n0"] = t0, n0
    state["i"] += 1
    QTimer.singleShot(60, lambda: wait_frames(n0))


def wait_frames(n0):
    if len(r.stamps) - n0 < 8:
        return QTimer.singleShot(30, lambda: wait_frames(n0))
    QTimer.singleShot(120, lambda: do_check("A%d" % state["i"]))


def do_check(label):
    d = grab_check(label, None)
    # frames needed until a frame at the new swapchain size appeared
    results.append(d)
    next_step()


def phase_b():
    # 20 rapid resizes, 8 ms apart, no waiting for frames
    state["j"] = 0
    state["botherr0"] = len(collect.records)
    rapid()


def rapid():
    j = state["j"]
    if j >= 20:
        return QTimer.singleShot(600, finish)
    w, h = 700 + (j * 53) % 900, 450 + (j * 37) % 550
    studio.resize(w, h)
    studio.move(20 + (j * 13) % 200, 20 + (j * 9) % 100)
    state["j"] += 1
    QTimer.singleShot(8, rapid)


def finish():
    d = grab_check("rapid_end", None)
    results.append(d)
    bad = [x for x in results if not x["swap_ok"] or x["other_px"] or (x["frame_age"] is None or x["frame_age"] > 12) or x["centre_is_mesh"] is False]
    out = {"method": args.method, "steps": len(results), "bad_steps": [(b["label"], b) for b in bad][:6], "n_bad": len(bad),
           "log_records": collect.records[:10], "n_log_records": len(collect.records), "size_mismatch_frames": r.size_mismatch,
           "distinct_swapchain_sizes": len(r.sizes_seen), "last_frame": r.frame,
           "max_frame_age": max((x["frame_age"] or 0) for x in results), "centre_checks": sum(1 for x in results if x["centre_is_mesh"] is not None),
           "card_full_match_steps": sum(1 for x in results if x["card_match"].split("/")[0] == x["card_match"].split("/")[1] or int(x["card_match"].split("/")[0]) >= 0.9 * max(1, int(x["card_match"].split("/")[1])))}
    print("RESULT " + json.dumps(out), flush=True)
    for x in results:
        print("STEP " + json.dumps(x), flush=True)
    app.quit()


QTimer.singleShot(1500, next_step)
app.exec()
