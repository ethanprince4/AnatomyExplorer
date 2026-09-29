"""Headless test of hide / isolate: H and I act on the selected part, Shift+H and Shift+I on its whole structure,
the panel buttons on the highlighted row, and the structure tree shows partly hidden structures as partly checked.
Counts only; nothing is rendered.

    .venv/Scripts/python.exe viewer/tests/hide.py [model.glb ...]
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from viewer.window import MainWindow  # noqa: E402

STATE = {Qt.Checked: "checked", Qt.PartiallyChecked: "partly", Qt.Unchecked: "unchecked"}


def check_model(w, glb):
    fails = []
    w.open_path(glb)
    m = w.model
    n = len(m.parts)
    acts = {a.shortcut().toString(): a for a in w.findChildren(QAction) if not a.shortcut().isEmpty()}
    buttons = {b.text(): b for b in w.findChildren(QPushButton) if b.text() in ("Hide", "Isolate", "Show all")}
    for key in ("H", "Shift+H", "I", "Shift+I", "Alt+H"):
        if key not in acts:
            fails.append(f"no action on {key}")
    if fails:
        return fails

    # a structure with several parts: the aortic valve when the file has one, else the first multi-part structure
    multi = [s for s in m.structures if len(s.parts) >= 2]
    st = next((s for s in multi if "aortic" in s.title.lower() and "valve" in s.title.lower()), multi[0])
    part = st.parts[len(st.parts) // 2]
    tops = {w.tree.topLevelItem(i).data(0, Qt.UserRole)[1]: w.tree.topLevelItem(i)
            for i in range(w.tree.topLevelItemCount())}
    top = tops[st.key]
    print(f"{Path(glb).name}: {n} parts in {len(m.structures)} structures; testing '{part.name}' "
          f"in '{st.title.strip()}' ({len(st.parts)} parts)")

    def visible():
        return sum(p.visible for p in m.parts)

    def expect(what, n_vis, top_state, others_state=None):
        got = STATE[top.checkState(0)]
        others = {STATE[t.checkState(0)] for k, t in tops.items() if k != st.key}
        ok = visible() == n_vis and got == top_state and (others_state is None or others == {others_state})
        print(f"  {'ok  ' if ok else 'FAIL'} {what:<34} visible {visible():>4} / {n} (want {n_vis}); "
              f"structure row {got} (want {top_state}); other rows {sorted(others)}")
        if not ok:
            fails.append(what)

    def reset_and_select():
        acts["Alt+H"].trigger()
        w.view.select(part)

    expect("start", n, "checked", "checked")

    w.view.select(None)
    acts["H"].trigger()
    expect("H with nothing selected", n, "checked", "checked")

    reset_and_select()
    row = w.tree.currentItem()
    if row is None or row.data(0, Qt.UserRole) != ("part", part.id):
        fails.append("a viewport pick does not highlight the part's row")
    acts["H"].trigger()
    expect("H hides the part only", n - 1, "partly", "checked")
    if part.visible or not all(p.visible for p in st.parts if p is not part):
        fails.append("H hid the wrong parts")
    if w.view.settings.selected:
        fails.append("the hidden part stayed selected")

    reset_and_select()
    acts["Shift+H"].trigger()
    expect("Shift+H hides the structure", n - len(st.parts), "unchecked", "checked")

    reset_and_select()
    acts["I"].trigger()
    expect("I isolates the part", 1, "partly", "unchecked")
    if not part.visible:
        fails.append("I hid the selected part")

    reset_and_select()
    acts["Shift+I"].trigger()
    expect("Shift+I isolates the structure", len(st.parts), "checked", "unchecked")

    reset_and_select()
    buttons["Hide"].click()
    expect("panel Hide after a viewport pick", n - 1, "partly", "checked")

    reset_and_select()
    buttons["Isolate"].click()
    expect("panel Isolate after a viewport pick", 1, "partly", "unchecked")

    acts["Alt+H"].trigger()
    w.tree.setCurrentItem(top)
    buttons["Hide"].click()
    expect("panel Hide on a structure row", n - len(st.parts), "unchecked", "checked")

    acts["Alt+H"].trigger()
    top.child(0).setCheckState(0, Qt.Unchecked)
    expect("untick one part in the tree", n - 1, "partly", "checked")

    buttons["Show all"].click()
    expect("Show all", n, "checked", "checked")
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
