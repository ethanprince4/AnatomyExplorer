"""End-to-end check of the model viewer inside the app: opens models in their tabs and drives them the way a user
does, through the app's own actions (H, I, Shift+H, Ctrl+Z, T, PgDown...), then checks what came out.

    python tools/check_viewer.py [model_id ...]      (default: the in-house GLB models, one procedural and one
                                                      downloaded model)

First, without drawing anything, the catalogue: every model's related models and histology tissues exist, and every
in-house model's metadata (data/content/models/<id>.json) names only groups and parts the model has, with aliases
that resolve and atlas links that name real atlas structures. Then, for every model given: it draws (enough of the frame is not background), a click in the middle picks a part, hide /
isolate / show all / undo change the visible count as they should, the section and the x-ray work, labels are placed.
For a model with stored views: every view's hidden list names parts that exist, and choosing the view hides exactly
those. For a model with a teased state: T switches to it and back. Needs an OpenGL 4.1 context (on a server without a
display: xvfb-run -a python tools/check_viewer.py).
"""
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_IDS = ["whole_heart", "cardiac_muscle", "kidney_nephron", "thin_skin", "sketchfab:0ff5"]


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


def check_model(app, w, mid):
    from PySide6.QtCore import QPoint
    fails = []

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

    # ---- states
    if "teased" in (m.states or {}):
        acts["model_state"].trigger()
        ok(g.reveal_state == "teased" and g.reveal_target == 1.0, "T shows the teased state")
        acts["model_state"].trigger()
        ok(g.reveal_target == 0.0, "T again assembles it")

    acts["show_all"].trigger()
    view.reset_view(animate=False)
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

    from app.config import DATA_DIR
    from app.data import Dataset
    from app.main_window import MainWindow

    app = QApplication.instance() or QApplication(["check_viewer"])
    ds = Dataset(DATA_DIR)
    w = MainWindow(ds)
    fails = check_catalog(ds, w.content)
    w.resize(1500, 950)
    w.show()
    pump(app, 1.5)
    for mid in argv or DEFAULT_IDS:
        fails += check_model(app, w, mid)
    w.close()
    pump(app, 0.3)
    print("OK" if not fails else f"{len(fails)} problems:\n  " + "\n  ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
