"""Headless test of the opt-in stage views (phase 11): a view record's "hidden" list, the scale-aware move
("view_transition": "zoom"), "start_view", name-sized buttons and number keys. On a file without those keys it checks
that choosing views leaves visibility alone and uses the old damped glide. Counts and numbers only; nothing rendered.

    .venv/Scripts/python.exe viewer/tests/views.py [model.glb ...]
"""
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from viewer.window import MainWindow  # noqa: E402

ASPECT = 16 / 9


def ndc(cam, point):
    """Normalised device x, y of a world point for the camera's current state (perspective)."""
    V = cam.view_matrix()
    p = V @ np.append(np.asarray(point, float), 1.0)
    tx, ty = cam.half_tans(ASPECT)
    z = -p[2]
    if z <= 1e-12:
        return 9.0, 9.0
    return p[0] / z / tx, p[1] / z / ty


def run_move(cam, dt=1 / 120):
    """Step a view move to its end; return the largest |ndc| of the kept target (the start's while zooming out,
    the goal's while zooming in) and the number of steps."""
    P = cam._path
    if P is None:
        return None, 0
    t0, t1 = P["c0"].target.copy(), P["g"].target.copy()
    worst, n = 0.0, 0
    prev = P["d0"]
    while cam.update(dt):
        n += 1
        d = cam.cur.distance
        zooming_out = d > prev + 1e-12
        prev = d
        x, y = ndc(cam, t0 if zooming_out else t1)
        worst = max(worst, abs(x), abs(y))
        if n > 20000:
            break
    return worst, n


def check_model(w, glb):
    fails = []
    w.open_path(glb)
    m = w.model
    v = w.view
    if v.renderer is None:
        # headless: there is no GL context, so the viewport never installs the model; do its non-GL part here
        # (Viewport._install minus the renderer), including the start view
        v.model = m
        lo, hi = m.world_bounds(visible_only=False)
        v.camera.scene_centre = (lo + hi) / 2
        v.camera.scene_radius = max(float(np.linalg.norm(hi - lo)) / 2, 1e-3)
        start = m.sidecar.get("start_view")
        start = start if start in m.cameras else ("V1" if "V1" in m.cameras else None)
        if start:
            v.camera.set_view(m.cameras[start], animate=False)
            v.apply_view_visibility(m.cameras[start])
    side = m.sidecar
    staged = side.get("view_transition") == "zoom" or any("hidden" in c for c in m.cameras.values())
    n = len(m.parts)
    print(f"{Path(glb).name}: {n} parts, {len(m.camera_order)} views, stage keys {'yes' if staged else 'no'}")
    buttons = {b.text(): b for b in w.findChildren(QPushButton) if b.text() in m.cameras}
    if set(buttons) != set(m.camera_order):
        fails.append("a view has no button")
    for name in m.camera_order:
        b = buttons.get(name)
        if b is not None and len(name) > 3 and b.minimumWidth() < 44:
            fails.append(f"{name}: button not sized to its name")
    start = side.get("start_view")
    if start in m.cameras and "hidden" in m.cameras[start]:
        hid = set(m.cameras[start]["hidden"])
        if any(p.visible == (p.name in hid) for p in m.parts):
            fails.append("the start view's visibility is not applied")
    cam = w.view.camera
    for name in m.camera_order:
        rec = m.cameras[name]
        w.view.select(None)
        if not staged:
            before = [p.visible for p in m.parts]
            buttons[name].click()
            if [p.visible for p in m.parts] != before:
                fails.append(f"{name}: visibility changed on a file without stage keys")
            if cam._path is not None:
                fails.append(f"{name}: a zoom path started on a file without stage keys")
            cam.snap()
            continue
        buttons[name].click()
        if "hidden" in rec:
            hid = set(rec["hidden"])
            vis = sum(p.visible for p in m.parts)
            want = sum(p.name not in hid for p in m.parts)
            bad = [p.name for p in m.parts if p.visible == (p.name in hid)]
            tree_ok = True
            for i in range(w.tree.topLevelItemCount()):
                top = w.tree.topLevelItem(i)
                for j in range(top.childCount()):
                    c = top.child(j)
                    pid = c.data(0, Qt.UserRole)[1]
                    p = next(q for q in m.parts if q.id == pid)
                    if (c.checkState(0) == Qt.Checked) != p.visible:
                        tree_ok = False
            print(f"  {name:<24} visible {vis:>4} / {n} (want {want}); tree {'in step' if tree_ok else 'OUT OF STEP'}",
                  end="")
            if bad or vis != want:
                fails.append(f"{name}: visibility wrong ({len(bad)} parts)")
            if not tree_ok:
                fails.append(f"{name}: tree out of step")
        else:
            print(f"  {name:<24} (no hidden list)", end="")
        worst, steps = run_move(cam)
        pos = cam.position()
        want_pos = np.asarray(rec["position"], float)
        err = float(np.linalg.norm(pos - want_pos) / max(np.linalg.norm(want_pos - np.asarray(rec["target"])), 1e-9))
        print(f"; move {steps} steps, kept target within {worst if worst is not None else 0:.2f} of the frame edge; "
              f"end position error {err:.1e}")
        if side.get("view_transition") == "zoom" and worst is not None and worst > 1.0:
            fails.append(f"{name}: the kept target left the frame during the move ({worst:.2f})")
        if err > 1e-6:
            fails.append(f"{name}: the move did not end on the view ({err:.1e})")
    # number keys on a file with named views only
    if staged and not any(c in m.camera_order for c in [f"V{i}" for i in range(7)]):
        first = m.camera_order[0]
        w._view_key(1)
        cam.snap() if cam._path is None else run_move(cam)
        if np.linalg.norm(cam.position() - np.asarray(m.cameras[first]["position"])) > 1e-6 * max(
                1.0, np.linalg.norm(m.cameras[first]["position"])):
            fails.append("number key 1 does not choose the first view")
    return fails


def main():
    paths = [Path(p) for p in sys.argv[1:]] or [ROOT / "viewer" / "models" / "rebuild.glb"]
    paths = [p for p in paths if p.is_file()]
    if not paths:
        print("SKIP no model to test")
        return 2
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    fails = []
    for p in paths:
        fails += [f"{p.name}: {f}" for f in check_model(w, p)]
    w.close()
    del app
    print("PASS" if not fails else "FAIL " + "; ".join(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
