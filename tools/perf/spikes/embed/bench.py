"""Q1 and Q4: frame time, fps, swapchain size and Qt timer jitter for a QRenderWidget as top-level window.

python bench.py --method screen|bitmap --phys 1280x800 [--vsync 0|1] [--seconds 10]
Set QT_SCALE_FACTOR before launching to imitate Retina. Prints one JSON line."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
ap = argparse.ArgumentParser()
ap.add_argument("--method", required=True)
ap.add_argument("--phys", default="1280x800")
ap.add_argument("--vsync", type=int, default=0)
ap.add_argument("--seconds", type=float, default=10)
args = ap.parse_args()

import os
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication
app = QApplication([])
from rendercanvas.qt import QRenderWidget
import numpy as np
from common import Renderer, pct

pw, ph = (int(x) for x in args.phys.split("x"))
canvas = QRenderWidget(present_method=args.method, update_mode="continuous", max_fps=1000, vsync=bool(args.vsync))
canvas.setWindowFlag(Qt.WindowStaysOnTopHint, True)
dpr = canvas.devicePixelRatioF()
canvas.resize(round(pw / dpr), round(ph / dpr))
r = Renderer(canvas)
canvas.request_draw(r.draw)
canvas.show()
canvas.move(20, 20)

jit = []          # (perf_counter, interval ms, phase)
phase = ["start"]
last = [time.perf_counter()]
def tick():
    now = time.perf_counter()
    jit.append((now, (now - last[0]) * 1000, phase[0]))
    last[0] = now
timer = QTimer(); timer.setTimerType(Qt.PreciseTimer); timer.setInterval(1); timer.timeout.connect(tick); timer.start()

result = {}
def to_idle():
    phase[0] = "idle"
    canvas.set_update_mode("ondemand", min_fps=0, max_fps=1000)
def to_run():
    phase[0] = "warm"
    canvas.set_update_mode("continuous", max_fps=1000)
def to_measure():
    phase[0] = "measure"; result["t0"] = time.perf_counter(); result["f0"] = len(r.stamps)
def finish():
    t1 = time.perf_counter(); phase[0] = "done"
    st = np.array(r.stamps[result["f0"]:]); dt = np.diff(st) * 1000
    dm = np.array(r.draw_ms[result["f0"]:]); am = np.array(r.acq_ms[result["f0"]:])
    idle = np.array([j[1] for j in jit if j[2] == "idle"][5:])
    meas = np.array([j[1] for j in jit if j[2] == "measure"])
    # one grab to confirm real pixels reached the screen (corner pixel carries the frame counter in G)
    scr = app.primaryScreen(); g = canvas.mapToGlobal(canvas.rect().topLeft())
    px = scr.grabWindow(0, g.x() + 6, g.y() + 6, 4, 4).toImage()
    c = px.pixelColor(2, 2)
    s = canvas.size()
    client = None
    if sys.platform == "win32" and args.method == "screen":
        import ctypes
        from ctypes import wintypes
        rc = wintypes.RECT()
        ctypes.windll.user32.GetClientRect(int(canvas.winId()), ctypes.byref(rc))
        client = [rc.right - rc.left, rc.bottom - rc.top]
    result.update(
        method=args.method, vsync=args.vsync, qt_scale=os.environ.get("QT_SCALE_FACTOR", "-"), dpr=dpr,
        requested_phys=[pw, ph], widget_logical=[s.width(), s.height()],
        widget_phys_calc=[round(s.width() * dpr), round(s.height() * dpr)],
        canvas_phys=list(canvas.get_physical_size()), swapchain=list(r.last_tex_size), sizes_seen=sorted(r.sizes_seen),
        size_mismatch_frames=r.size_mismatch,
        hwnd_client_rect=client,
        present_to_screen=canvas._present_to_screen,
        frames=len(st), fps=round((len(st) - 1) / (st[-1] - st[0]), 1),
        interval_ms_p50=round(pct(dt, 50), 3), interval_ms_p95=round(pct(dt, 95), 3), interval_ms_max=round(float(dt.max()), 2),
        acquire_ms_p50=round(pct(am, 50), 3),
        draw_cb_ms_p50=round(pct(dm, 50), 3), draw_cb_ms_p95=round(pct(dm, 95), 3),
        jitter_idle_ms=[round(pct(idle, 50), 2), round(pct(idle, 95), 2), round(float(idle.max()), 1)],
        jitter_render_ms=[round(pct(meas, 50), 2), round(pct(meas, 95), 2), round(float(meas.max()), 1)],
        timer_ticks_per_s_render=round(len(meas) / (t1 - result["t0"]), 1),
        grab_corner_rgb=[c.red(), c.green(), c.blue()], tris=r.tris, parts=r.nparts, adapter=r.adapter_info.get("device"),
        backend=r.adapter_info.get("backend_type"))
    for k in ("t0", "f0"): result.pop(k)
    print("RESULT " + json.dumps(result), flush=True)
    app.quit()

T = 1000
QTimer.singleShot(1500, to_idle)
QTimer.singleShot(1500 + 3 * T, to_run)
QTimer.singleShot(1500 + 5 * T, to_measure)
QTimer.singleShot(int(1500 + 5 * T + args.seconds * 1000), finish)
app.exec()
