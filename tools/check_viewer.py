"""End-to-end check of the model viewer inside the app: opens models in their tabs and drives them the way a user
does, through the app's own actions (H, I, Shift+H, Ctrl+Z, T, PgDown...), then checks what came out.

    python tools/check_viewer.py [model_id ...]      (default: the in-house GLB models, one procedural and one
                                                      downloaded model)
    python tools/check_viewer.py --all               (every model in the catalogue)

The app is started the way app/__main__.py starts it (the same OpenGL context and theme). First, without drawing
anything, the catalogue: every model's related models and histology tissues exist, and every in-house model's
metadata (data/content/models/<id>.json) names only groups and parts the model has, with aliases that resolve and
atlas links that name real atlas structures. Then, for every model given: it draws (enough of the frame is not
background), a click in the middle picks a part, labels are placed, hide / isolate / show all / undo change the
visible count as they should, the x-ray, a section, separated parts, the projection switch, the arrow keys and the
1/3/7 views work, two clicks in measuring mode measure, the view survives a resize, the screenshot and the labelled
figure are written (the figure titled with the selected part), and closing the tab releases the model. For a model
with stored views: every view's hidden list names parts that exist, and choosing the view hides exactly those. For a
model with a teased state: T switches to it and back; for an animated one Space plays and pauses it. Any exception
raised while a model is being driven (in drawing, input handling or the app's slots) is a failure. Needs an OpenGL
4.1 context (on a server without a display: xvfb-run -a python tools/check_viewer.py).
"""
import math
import sys
import tempfile
import time
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_IDS = ["whole_heart", "cardiac_muscle", "kidney_nephron", "thin_skin"]


def pump(app, seconds=0.3):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.01)


def settle(app, view, limit=6.0):
    """Let the camera finish moving and the labels be placed."""
    g = view.gl_widget
    end = time.perf_counter() + limit
    while time.perf_counter() < end:
        g.update()
        pump(app, 0.05)
        if not g.camera.animating and not g._labels_dirty:
            break
    pump(app, 0.2)


ERRORS = []                      # tracebacks of exceptions raised inside Qt callbacks while the check runs


def check_model(app, w, mid):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from app.viewer.viewport import VIEWS
    fails = []
    errors_before = len(ERRORS)

    def ok(cond, what):
        print(f"  {'ok  ' if cond else 'FAIL'} {what}")
        if not cond:
            fails.append(what)

    cat = w.content.micro_models
    if mid not in cat:
        hits = [k for k in cat if k.startswith(mid)]
        if len(hits) != 1:
            return [f"no model {mid!r}"]
        mid = hits[0]
    t0 = time.perf_counter()
    w.open_micro(mid)
    view = w.micro_tabs.get(mid)
    if view is None:
        return [f"{mid}: did not open"]
    w.center.setCurrentWidget(view)
    g = view.gl_widget
    pump(app, 0.5)
    for _ in range(100):
        if g.renderer is not None:
            break
        pump(app, 0.1)
    if g.renderer is None:
        return [f"{mid}: no OpenGL context"]
    settle(app, view)
    m, st = view.vmodel, view.state
    n = len(m.items)
    print(f"{mid}: {n} parts in {len(m.groups)} groups, {m.triangle_count:,} triangles, "
          f"open {time.perf_counter() - t0:.1f} s")
    acts = w.cmds.actions

    def visible():
        return int(st.visible_mask().sum())

    # ---- it draws, and a click in the middle finds a part
    img = g.grab_image()
    corner = img[2, 2].astype(int)
    drawn = float((np.abs(img.astype(int) - corner).sum(axis=2) > 30).mean())
    ok(drawn > 0.04, f"draws the model ({drawn:.0%} of the frame)")
    hit = -1
    for fx, fy in ((0.5, 0.5), (0.45, 0.55), (0.55, 0.45), (0.5, 0.6), (0.4, 0.4), (0.6, 0.6)):
        hit = g.pick_at(QPoint(int(g.width() * fx), int(g.height() * fy)))
        if hit >= 0:
            break
    ok(hit >= 0, f"a click in the middle picks a part ({m.items[hit].name if hit >= 0 else 'nothing'})")
    if hit < 0:
        hit = next(i for i in range(n) if st.visible_mask()[i])

    # ---- labels: the selection is labelled; Labels names every labelled part in view
    st.select([hit])
    settle(app, view)
    ok(any(i == hit for i, *_ in g.label_items), f"the selected part is labelled ({m.items[hit].name})")
    view.toggle_labels()
    settle(app, view)
    ok(len(g.label_items) > 1 or sum(it.label for it in m.items) <= 1, f"Labels names the parts ({len(g.label_items)})")
    view.toggle_labels()
    st.clear_selection()

    # ---- hide, isolate, show all, undo through the app's actions
    acts["show_all"].trigger()
    base = visible()
    st.select([hit])
    acts["hide"].trigger()
    ok(visible() == base - 1 and not st.visible_mask()[hit], f"H hides the selected part ({visible()} of {base})")
    acts["undo"].trigger()
    ok(visible() == base, f"Ctrl+Z brings it back ({visible()})")
    st.select([hit])
    acts["isolate"].trigger()
    ok(visible() == 1 and st.visible_mask()[hit], f"I isolates it ({visible()} visible)")
    acts["show_all"].trigger()
    ok(visible() == n, f"Shift+H shows all ({visible()} of {n})")
    st.select([hit])
    acts["xray"].trigger()
    ok(st.ghost_focus is not None and bool(st.ghost_focus[hit]), "X x-rays everything but the selection")
    acts["escape"].trigger()
    ok(st.ghost_focus is None, "Esc clears the x-ray")
    acts["escape"].trigger()
    ok(not st.selected, "Esc again clears the selection")

    # ---- a section
    view.set_section(1, True)
    settle(app, view, 2.0)
    ok(g.any_cut(), "the coronal section cuts")
    view.clear_sections()

    # ---- stored views and their hidden lists
    keys = {it.key for it in m.items}
    for name in m.camera_order:
        rec = m.cameras[name]
        if "hidden" not in rec:
            continue
        want = set(rec.get("hidden") or ())
        missing = sorted(want - keys)
        ok(not missing, f"view {name!r}: every hidden part exists" + (f" (missing {missing[:3]})" if missing else ""))
        view.set_named_view(name)
        got = {m.items[i].key for i in range(n) if not st.visible_mask()[i]}
        ok(got == want & keys, f"view {name!r} hides its {len(want)} parts (hid {len(got)})")
    if m.camera_order:
        before = g.camera.target.copy(), g.camera.distance
        acts["model_next_view"].trigger()
        settle(app, view)
        moved = not (np.allclose(before[0], g.camera.target) and abs(before[1] - g.camera.distance) < 1e-6)
        ok(moved, "PgDown moves to the next stored view")

    # ---- states and animation
    if "teased" in (m.states or {}):
        acts["model_state"].trigger()
        ok(g.reveal_state == "teased" and g.reveal_target == 1.0, "T shows the teased state")
        acts["model_state"].trigger()
        ok(g.reveal_target == 0.0, "T again assembles it")
    if g.anim_kind() is not None:
        t0 = g.anim_t
        acts["model_play"].trigger()
        for _ in range(8):
            g.update()
            pump(app, 0.25)
        ok(g.playing and g.anim_t != t0, f"Space plays the animation (t {t0:.2f} -> {g.anim_t:.2f})")
        acts["model_play"].trigger()
        ok(not g.playing, "Space again pauses it")

    acts["show_all"].trigger()
    view.reset_view(animate=False)
    settle(app, view)

    # ---- the atlas's camera keys and views, the projection switch, separated parts
    yaw0 = g.camera.yaw
    acts["orbit_left"].trigger()
    settle(app, view, 2.0)
    ok(abs(g.camera.yaw - yaw0) > 1e-4, "the arrow keys turn the model")
    for name, key in (("anterior", "view_anterior"), ("superior", "view_superior")):
        acts[key].trigger()
        settle(app, view)
        want_yaw, want_pitch = VIEWS[name]
        dyaw = abs((g.camera.yaw - want_yaw + math.pi) % (2 * math.pi) - math.pi)
        ok(dyaw < 1e-3 and abs(g.camera.pitch - want_pitch) < 1e-3, f"the {name} view key turns the camera")
    was = g.camera.ortho
    acts["model_projection"].trigger()
    ok(g.camera.ortho != was, "P switches the projection")
    acts["model_projection"].trigger()
    ok(g.camera.ortho == was, "P again switches it back")
    view.reset_view(animate=False)
    settle(app, view)
    g.set_explode(0.6)
    settle(app, view)
    img = g.grab_image()
    corner = img[2, 2].astype(int)
    drawn = float((np.abs(img.astype(int) - corner).sum(axis=2) > 30).mean())
    ok(m.item_offsets is not None and drawn > 0.02, f"separated parts draw ({drawn:.0%} of the frame)")
    g.set_explode(0.0)
    settle(app, view)

    # ---- measuring: two clicks on the model
    acts["measure"].trigger()
    ok(g.measure_mode, "M starts measuring")
    spots = []
    for fx, fy in ((0.5, 0.5), (0.45, 0.55), (0.55, 0.45), (0.5, 0.6), (0.4, 0.4), (0.6, 0.6), (0.5, 0.4)):
        pt = QPoint(int(g.width() * fx), int(g.height() * fy))
        if g.world_at(pt) is not None:
            spots.append(pt)
    if len(spots) >= 2:
        QTest.mouseClick(g, Qt.LeftButton, Qt.NoModifier, spots[0])
        QTest.mouseClick(g, Qt.LeftButton, Qt.NoModifier, spots[-1])
        pump(app, 0.2)
        text = g.measure_text()
        ok(len(g.measure_points) == 2 and bool(text), f"two clicks measure ({text})")
        acts["escape"].trigger()
        ok(not g.measure_points, "Esc clears the measurement")
    acts["measure"].trigger()
    ok(not g.measure_mode, "M again stops measuring")

    # ---- a resize, the screenshot and the labelled figure
    size = w.size()
    w.resize(1100, 760)
    pump(app, 0.3)
    settle(app, view)
    hit2 = g.pick_at(QPoint(g.width() // 2, g.height() // 2))
    img = g.grab_image()
    ok(img is not None and img.shape[1] == int(round(g.width() * g.devicePixelRatioF())), "the view follows a resize")
    w.resize(size)
    pump(app, 0.3)
    st.select([hit2 if hit2 >= 0 else hit])
    settle(app, view)
    out = Path(tempfile.mkdtemp(prefix="check_viewer_"))
    w.screenshot(str(out / "shot.png"))
    ok((out / "shot.png").is_file() and (out / "shot.png").stat().st_size > 5000, "F12 saves a screenshot")
    title, bits, credit = w._figure_caption()
    sel_name = m.items[st.selected[0]].name
    ok(title == sel_name and "Z-Anatomy" not in credit, f"the figure is titled with the selection ({title!r})")
    w.export_figure(str(out / "figure.png"))
    ok((out / "figure.png").is_file() and (out / "figure.png").stat().st_size > 5000, "Ctrl+Shift+S saves a figure")
    st.clear_selection()

    # ---- no exception anywhere, then closing the tab releases the model
    new_errors = ERRORS[errors_before:]
    ok(not new_errors, "no exception while driving the model"
       + (f" ({len(new_errors)}: {new_errors[-1].strip().splitlines()[-1]})" if new_errors else ""))
    w._close_center_tab(w.center.indexOf(view))
    ok(mid not in w.micro_tabs and g.renderer is None, "closing the tab releases the model")
    pump(app, 0.3)
    return [f"{mid}: {f}" for f in fails]


def check_catalog(ds, content):
    """The catalogue's cross-links and the in-house models' metadata."""
    from app.lessons import Resolver
    from app.viewer.catalog import GlbEntry

    res = Resolver(ds)
    cat = content.micro_models
    fails = []
    for e in cat.values():
        for r in e.related:
            if r not in cat:
                fails.append(f"{e.id}: related model {r!r} is not in the catalogue")
        for t in e.histology:
            if t not in content.tissues:
                fails.append(f"{e.id}: histology tissue {t!r} does not exist")
    for e in cat.values():
        if not isinstance(e, GlbEntry):
            continue
        m = e.load()
        meta = e.meta
        sids = {p.structure_id for it in m.items for p in it.parts}
        keys = {it.key for it in m.items}
        for g in meta.get("groups") or {}:
            if g not in sids:
                fails.append(f"{e.id}: metadata group {g!r} is not in the model")
        for k in meta.get("parts") or {}:
            if k not in keys:
                fails.append(f"{e.id}: metadata part {k!r} is not in the model")
        for name, targets in (meta.get("aliases") or {}).items():
            got, _missing = e.resolve(m, [name])
            if not got:
                fails.append(f"{e.id}: alias {name!r} -> {targets} finds no part")
        for it in m.items:
            for a in it.atlas:
                if not res.resolve(a):
                    fails.append(f"{e.id}: part {it.key!r} links to {a!r}, which is not an atlas structure")
        for n in (meta.get("targets") or {}).get("structures", []):
            if not res.resolve(n):
                fails.append(f"{e.id}: target structure {n!r} is not an atlas structure")
        print(f"{e.id}: metadata for {len(meta.get('groups') or {})} groups, {len(meta.get('parts') or {})} parts, "
              f"{len(meta.get('aliases') or {})} aliases")
    print(f"catalogue: {len(cat)} models, " + ("OK" if not fails else f"{len(fails)} problems"))
    for f in fails:
        print("  FAIL", f)
    return fails


def main(argv):
    from PySide6.QtWidgets import QApplication

    from app.__main__ import configure_qt
    from app.config import DATA_DIR
    from app.data import Dataset
    from app.main_window import MainWindow
    from app.ui.theme import apply_theme

    def hook(exc_type, exc, tb):
        ERRORS.append("".join(traceback.format_exception(exc_type, exc, tb)))
        sys.__stderr__.write(ERRORS[-1])

    sys.excepthook = hook
    app = QApplication.instance()
    if app is None:
        configure_qt()
        app = QApplication(["check_viewer"])
        apply_theme(app)
    ds = Dataset(DATA_DIR)
    w = MainWindow(ds)
    fails = check_catalog(ds, w.content)
    w.resize(1500, 950)
    w.show()
    pump(app, 1.5)
    ids = list(w.content.micro_models) if "--all" in argv else [a for a in argv if not a.startswith("--")] or DEFAULT_IDS
    for mid in ids:
        fails += check_model(app, w, mid)
    w.close()
    pump(app, 0.3)
    print("OK" if not fails else f"{len(fails)} problems:\n  " + "\n  ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
