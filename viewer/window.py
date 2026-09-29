"""The viewer's main window: menus, structure panel, view and state buttons, animation bar, info panel."""
from __future__ import annotations

import datetime
import traceback
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDockWidget, QFileDialog, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QPushButton, QSlider, QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .model import Model
from .viewport import Viewport

APP = "Microanatomy Model Viewer"
MAX_RECENT = 10
FILTER = "glTF models (*.glb *.gltf);;All files (*)"

STYLE = """
QMainWindow, QWidget { background: #1b1e24; color: #d9dde4; font-size: 10pt; }
QMenuBar, QMenu { background: #20242b; color: #d9dde4; }
QMenu::item:selected, QMenuBar::item:selected { background: #34404f; }
QDockWidget::title { background: #20242b; padding: 6px; }
QTreeWidget { background: #171a1f; border: none; }
QTreeWidget::item:selected { background: #34404f; }
QPushButton, QToolButton, QComboBox { background: #2a2f38; border: 1px solid #3a414d; border-radius: 4px;
    padding: 4px 9px; }
QPushButton:hover, QToolButton:hover { background: #34404f; }
QPushButton:checked, QToolButton:checked { background: #4a5a70; border-color: #7f9cc0; }
QSlider::groove:horizontal { height: 4px; background: #3a414d; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -6px 0; background: #d9b25a; border-radius: 7px; }
QLabel#info { background: rgba(18, 20, 26, 215); border: 1px solid #3a414d; border-radius: 6px; padding: 8px 10px; }
QStatusBar { background: #171a1f; color: #9aa3b0; }
"""

CONTROLS = """<h3>Mouse</h3>
<table cellspacing=4>
<tr><td><b>Left drag</b></td><td>orbit</td></tr>
<tr><td><b>Right or middle drag</b> (or Shift + left)</td><td>pan</td></tr>
<tr><td><b>Wheel</b></td><td>zoom (toward the point under the cursor)</td></tr>
<tr><td><b>Click</b></td><td>identify a part (name, structure, label); click empty space to clear</td></tr>
<tr><td><b>Double-click</b></td><td>focus on the part</td></tr>
</table>
<h3>Keys</h3>
<table cellspacing=4>
<tr><td><b>F</b></td><td>fit the visible model</td></tr>
<tr><td><b>0 - 6</b></td><td>shared camera views V0 - V6</td></tr>
<tr><td><b>7, 8, 9</b></td><td>anchor views A1 - A3 (when the model has them)</td></tr>
<tr><td><b>1 - 9, 0</b></td><td>a model with named stage views instead: its views in order</td></tr>
<tr><td><b>5 on the keypad / P</b></td><td>toggle perspective / orthographic</td></tr>
<tr><td><b>Space</b></td><td>play / pause the contraction</td></tr>
<tr><td><b>L</b></td><td>loop on / off</td></tr>
<tr><td><b>T</b></td><td>toggle assembled / teased</td></tr>
<tr><td><b>H</b> / <b>Shift+H</b></td><td>hide the selected part / its whole structure</td></tr>
<tr><td><b>I</b> / <b>Shift+I</b></td><td>isolate the selected part / its whole structure</td></tr>
<tr><td><b>Alt+H</b></td><td>show all</td></tr>
<tr><td><b>C</b>, <b>N</b>, <b>O</b>, <b>S</b>, <b>D</b></td><td>covering, annotation, ambient occlusion, stripes, shadows</td></tr>
<tr><td><b>Esc</b></td><td>clear the selection</td></tr>
<tr><td><b>Ctrl+O</b>, <b>F12</b>, <b>Shift+F12</b></td><td>open, screenshot, screenshot at 2x</td></tr>
</table>"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP)
        self.resize(1600, 960)
        self.setStyleSheet(STYLE)
        self.setAcceptDrops(True)
        self.qs = QSettings("AnatomyExplorer", "ModelViewer")
        self.model: Model | None = None
        self.path: Path | None = None
        self._tree_lock = False

        self.view = Viewport(self)
        self.setCentralWidget(self._central())
        self._build_menus()
        self._build_tree()
        self.info = QLabel(self.view)
        self.info.setObjectName("info")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info.hide()

        self.view.partPicked.connect(self._on_pick)
        self.view.timeChanged.connect(self._on_time)
        self.view.playingChanged.connect(lambda on: self.play_btn.setText("❚❚ Pause" if on else "▶ Play"))
        self.view.stateChanged.connect(self._on_state)
        self.view.frameTimed.connect(self._on_frame)
        self.view.visibilityChanged.connect(self._sync_tree)
        self.view.glReady.connect(lambda info: self.statusBar().showMessage(info, 6000))
        self._fps = []
        self.statusBar()
        self._refresh_recent()
        self._set_enabled(False)

    # ------------------------------------------------------------------ layout
    def _central(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(8, 6, 8, 6)
        tl.addWidget(QLabel("Views"))
        self.view_bar = QHBoxLayout()
        tl.addLayout(self.view_bar)
        tl.addSpacing(18)
        tl.addWidget(QLabel("State"))
        self.btn_assembled = QPushButton("Assembled")
        self.btn_teased = QPushButton("Teased")
        for b in (self.btn_assembled, self.btn_teased):
            b.setCheckable(True)
            tl.addWidget(b)
        self.btn_assembled.clicked.connect(lambda: self.view.show_state("assembled"))
        self.btn_teased.clicked.connect(self._teased_clicked)
        tl.addSpacing(18)
        self.toggles = {}
        for key, text, tip in (("covering", "Covering", "translucent endomysium covering (C)"),
                               ("annotation", "Annotation", "caption, scale bar and ring (N)"),
                               ("ao", "AO", "ambient occlusion / contact shading (O)"),
                               ("shadows", "Shadows", "light rig shadows (D)"),
                               ("stripes", "Stripes", "procedural striations (S)")):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setChecked(True)
            b.toggled.connect(lambda on, k=key: self._toggle(k, on))
            tl.addWidget(b)
            self.toggles[key] = b
        tl.addStretch(1)
        lay.addWidget(top)
        lay.addWidget(self.view, 1)

        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(8, 6, 8, 6)
        self.anim_label = QLabel("Contraction")
        bl.addWidget(self.anim_label)
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.clicked.connect(lambda: self.view.set_playing(not self.view.playing))
        bl.addWidget(self.play_btn)
        self.loop_box = QCheckBox("Loop")
        self.loop_box.setChecked(True)
        self.loop_box.toggled.connect(lambda on: setattr(self.view, "loop", on))
        bl.addWidget(self.loop_box)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.valueChanged.connect(self._on_slider)
        bl.addWidget(self.slider, 1)
        self.time_label = QLabel("")
        self.time_label.setMinimumWidth(190)
        bl.addWidget(self.time_label)
        bl.addWidget(QLabel("Speed"))
        self.speed = QComboBox()
        for s in ("0.25x", "0.5x", "1x", "1.5x", "2x"):
            self.speed.addItem(s, float(s[:-1]))
        self.speed.setCurrentIndex(2)
        self.speed.currentIndexChanged.connect(lambda i: setattr(self.view, "speed", self.speed.itemData(i)))
        bl.addWidget(self.speed)
        lay.addWidget(bar)
        return w

    def _build_menus(self):
        mb = self.menuBar()
        fm = mb.addMenu("&File")
        a = fm.addAction("&Open…", self.open_dialog)
        a.setShortcut(QKeySequence.Open)
        self.recent_menu = fm.addMenu("Open &Recent")
        fm.addSeparator()
        a = fm.addAction("&Screenshot (window size)…", lambda: self.screenshot(1.0))
        a.setShortcut("F12")
        a = fm.addAction("Screenshot at &2x…", lambda: self.screenshot(2.0))
        a.setShortcut("Shift+F12")
        fm.addSeparator()
        a = fm.addAction("&Quit", self.close)
        a.setShortcut(QKeySequence.Quit)

        vm = mb.addMenu("&View")
        self.views_menu = vm.addMenu("Camera &views")
        a = vm.addAction("&Fit", lambda: self.view.fit())
        a.setShortcut("F")
        a = vm.addAction("&Perspective / orthographic", self._toggle_ortho)
        a.setShortcuts([QKeySequence("P"), QKeySequence(Qt.KeypadModifier | Qt.Key_5)])
        vm.addSeparator()
        for key, text, sc in (("covering", "Covering", "C"), ("annotation", "Annotation", "N"),
                              ("ao", "Ambient occlusion", "O"), ("shadows", "Shadows", "D"), ("stripes", "Stripes", "S")):
            a = vm.addAction(text, lambda k=key: self.toggles[k].toggle())
            a.setShortcut(sc)
        a = vm.addAction("Khronos PBR Neutral tone mapping", self._toggle_tonemap)
        a.setCheckable(True)
        a.setChecked(True)
        self.tonemap_action = a
        vm.addSeparator()
        lm = vm.addMenu("&Lighting")
        grp = QActionGroup(self)
        for text, val in (("Match the Cycles stills (harness ambient)", 0.0), ("Soft studio", 0.3),
                          ("Bright studio", 0.7)):
            a = lm.addAction(text, lambda v=val: self._set_studio(v))
            a.setCheckable(True)
            a.setChecked(abs(val - self.view.settings.studio) < 1e-6)
            grp.addAction(a)
        em = vm.addMenu("&Exposure")
        grp2 = QActionGroup(self)
        for ev in (-1.0, -0.5, 0.0, 0.5, 1.0):
            a = em.addAction(f"{ev:+.1f} EV", lambda v=ev: self._set_exposure(v))
            a.setCheckable(True)
            a.setChecked(ev == 0.0)
            grp2.addAction(a)

        am = mb.addMenu("&Animation")
        a = am.addAction("Play / pause", lambda: self.view.set_playing(not self.view.playing))
        a.setShortcut("Space")
        a = am.addAction("Loop", self.loop_box.toggle)
        a.setShortcut("L")
        a = am.addAction("Assembled / teased", self._toggle_state)
        a.setShortcut("T")

        sm = mb.addMenu("&Structures")
        a = sm.addAction("Hide selected part", lambda: self._hide_selected(whole=False))
        a.setShortcut("H")
        a = sm.addAction("Hide selected part's structure", lambda: self._hide_selected(whole=True))
        a.setShortcut("Shift+H")
        a = sm.addAction("Isolate selected part", lambda: self._isolate_selected(whole=False))
        a.setShortcut("I")
        a = sm.addAction("Isolate selected part's structure", lambda: self._isolate_selected(whole=True))
        a.setShortcut("Shift+I")
        a = sm.addAction("Show all", self._show_all)
        a.setShortcut("Alt+H")
        a = sm.addAction("Clear selection", lambda: self.view.select(None))
        a.setShortcut("Esc")

        hm = mb.addMenu("&Help")
        hm.addAction("&Controls", self._help)
        hm.addAction("&About", self._about)

        self._view_actions = []
        for i in range(10):          # number keys -> views
            a = QAction(self)
            a.setShortcut(str(i))
            a.triggered.connect(lambda _=False, k=i: self._view_key(k))
            self.addAction(a)

    def _build_tree(self):
        dock = QDockWidget("Structures", self)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemChanged.connect(self._tree_changed)
        self.tree.itemDoubleClicked.connect(self._tree_double)
        self.tree.currentItemChanged.connect(self._tree_current)
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        b = QPushButton("Isolate")
        b.setToolTip("show only the highlighted part or structure; a part clicked in the viewport is highlighted "
                     "(I = the selected part, Shift+I = its whole structure)")
        b.clicked.connect(self._isolate_current)
        row.addWidget(b)
        b = QPushButton("Hide")
        b.setToolTip("hide the highlighted part or structure; a part clicked in the viewport is highlighted "
                     "(H = the selected part, Shift+H = its whole structure)")
        b.clicked.connect(self._hide_current)
        row.addWidget(b)
        b = QPushButton("Show all")
        b.clicked.connect(self._show_all)
        row.addWidget(b)
        lay.addLayout(row)
        dock.setWidget(w)
        dock.setMinimumWidth(270)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

    # ------------------------------------------------------------------ files
    def open_dialog(self):
        start = self.qs.value("last_dir", str(Path(__file__).resolve().parent / "models"))
        path, _ = QFileDialog.getOpenFileName(self, "Open a model", start, FILTER)
        if path:
            self.open_path(path)

    def open_path(self, path):
        path = Path(path).resolve()
        if not path.is_file():
            QMessageBox.warning(self, APP, f"No such file:\n{path}")
            self._remove_recent(str(path))
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.statusBar().showMessage(f"Loading {path.name}…")
        QApplication.processEvents()
        try:
            model = Model(path)
            self.view.set_model(model)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, APP, f"Could not open {path.name}:\n\n{exc}\n\n{traceback.format_exc(limit=3)}")
            return
        QApplication.restoreOverrideCursor()
        self.model, self.path = model, path
        self.qs.setValue("last_dir", str(path.parent))
        self._add_recent(str(path))
        side = " + sidecar" if model.sidecar else " (no sidecar: default look)"
        self.setWindowTitle(f"{path.name} — {APP}")
        self.statusBar().showMessage(f"{path.name}: {len(model.parts)} parts, {model.triangle_count:,} triangles{side}", 8000)
        self._populate()
        self._set_enabled(True)

    def _add_recent(self, p):
        items = [x for x in (self.qs.value("recent", []) or []) if x != p]
        if isinstance(items, str):
            items = [items]
        self.qs.setValue("recent", ([p] + items)[:MAX_RECENT])
        self._refresh_recent()

    def _remove_recent(self, p):
        items = [x for x in (self.qs.value("recent", []) or []) if x != p]
        self.qs.setValue("recent", items)
        self._refresh_recent()

    def _refresh_recent(self):
        self.recent_menu.clear()
        items = self.qs.value("recent", []) or []
        if isinstance(items, str):
            items = [items]
        for p in items:
            self.recent_menu.addAction(p, lambda _=False, q=p: self.open_path(q))
        if not items:
            a = self.recent_menu.addAction("(none yet)")
            a.setEnabled(False)
        else:
            self.recent_menu.addSeparator()
            self.recent_menu.addAction("Clear list", lambda: (self.qs.setValue("recent", []), self._refresh_recent()))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith((".glb", ".gltf")) for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith((".glb", ".gltf")):
                self.open_path(p)
                break

    def screenshot(self, scale):
        if self.model is None:
            return
        stem = self.path.stem if self.path else "view"
        name = f"{stem}_{datetime.datetime.now():%Y%m%d_%H%M%S}{'_2x' if scale > 1 else ''}.png"
        start = self.qs.value("shot_dir", str(Path.home() / "Pictures"))
        path, _ = QFileDialog.getSaveFileName(self, "Save screenshot", str(Path(start) / name), "PNG image (*.png)")
        if not path:
            return
        img = self.view.grab_image(scale)
        from PIL import Image
        Image.fromarray(img).save(path)
        self.qs.setValue("shot_dir", str(Path(path).parent))
        self.statusBar().showMessage(f"Saved {path} ({img.shape[1]} x {img.shape[0]})", 8000)

    # ------------------------------------------------------------------ populate
    def _set_enabled(self, on):
        for b in (self.btn_assembled, self.btn_teased, self.play_btn, self.slider, self.loop_box, self.speed,
                  *self.toggles.values()):
            b.setEnabled(on)
        if not on:
            return
        m = self.model
        has_clip = m.clip is not None
        for b in (self.play_btn, self.slider, self.loop_box, self.speed):
            b.setEnabled(has_clip)
        self.anim_label.setText(m.clip.name if has_clip else "No animation")
        self.btn_teased.setEnabled(m.has_teased)
        self.toggles["covering"].setEnabled(any(p.role == "covering" for p in m.parts))
        self.toggles["annotation"].setEnabled(any(p.role == "annotation" for p in m.parts))
        self.toggles["stripes"].setEnabled(any(p.look.stripe for p in m.parts))

    def _populate(self):
        m = self.model
        # view buttons
        while self.view_bar.count():
            it = self.view_bar.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.views_menu.clear()
        for name in m.camera_order:
            rec = m.cameras[name]
            tip = f"{name}: {rec['type'].lower()}" + (f", {rec['state']} state" if rec.get("state") else "") + \
                  (f" ({rec['note']})" if rec.get("note") else "")
            b = QPushButton(name)
            b.setToolTip(tip)
            if len(name) <= 3:
                b.setFixedWidth(44)
            else:
                b.setMinimumWidth(44)            # a named stage view: the button fits its name
            b.clicked.connect(lambda _=False, n=name: self.view.set_view(n))
            self.view_bar.addWidget(b)
            self.views_menu.addAction(tip, lambda n=name: self.view.set_view(n))
        if not m.camera_order:
            lab = QLabel("(no shared views: F to fit)")
            self.view_bar.addWidget(lab)
            a = self.views_menu.addAction("(this file has no sidecar camera set)")
            a.setEnabled(False)
        for b in self.toggles.values():
            b.blockSignals(True)
            b.setChecked(True)
            b.blockSignals(False)
        self.view.settings.ao = self.view.settings.shadows = self.view.settings.stripes = True
        # structure tree
        self._tree_lock = True
        self.tree.clear()
        for st in m.structures:
            top = QTreeWidgetItem([f"{st.title}   · {len(st.parts)}"])
            top.setFlags(top.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            top.setCheckState(0, Qt.Checked)
            top.setData(0, Qt.UserRole, ("structure", st.key))
            for p in st.parts:
                label = p.name + (f"  — {p.label}" if p.label and len(p.label) < 40 else "")
                it = QTreeWidgetItem([label])
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Checked)
                it.setData(0, Qt.UserRole, ("part", p.id))
                top.addChild(it)
            self.tree.addTopLevelItem(top)
        self._tree_lock = False
        self._on_time(self.view.clip_t)
        self.info.hide()

    # ------------------------------------------------------------------ structures and visibility
    def _parts_of(self, item):
        kind, key = item.data(0, Qt.UserRole)
        if kind == "part":
            return [p for p in self.model.parts if p.id == key]
        st = next(s for s in self.model.structures if s.key == key)
        return list(st.parts)

    def _sync_tree(self):
        self._tree_lock = True
        vis = {p.id: p.visible for p in self.model.parts}
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                c = top.child(j)
                c.setCheckState(0, Qt.Checked if vis[c.data(0, Qt.UserRole)[1]] else Qt.Unchecked)
        self._tree_lock = False
        for role in ("covering", "annotation"):
            ps = [p for p in self.model.parts if p.role == role]
            if ps:
                b = self.toggles[role]
                b.blockSignals(True)
                b.setChecked(any(p.visible for p in ps))
                b.blockSignals(False)
        sel = self.view.settings.selected
        if sel and not vis.get(sel, True) and not any(p.visible for p in self.model.parts if p.id == sel):
            self.view.select(None)
        self.view.kick()

    def _tree_changed(self, item, col):
        if self._tree_lock or self.model is None:
            return
        on = item.checkState(0) != Qt.Unchecked
        kind, _ = item.data(0, Qt.UserRole)
        if kind == "part" or item.checkState(0) != Qt.PartiallyChecked:
            for p in self._parts_of(item):
                p.visible = on
        self._sync_tree()

    def _tree_current(self, cur, prev):
        if cur is None or self.model is None:
            return
        kind, key = cur.data(0, Qt.UserRole)
        if kind == "part":
            part = next((p for p in self.model.parts if p.id == key), None)
            if part is not None and part.visible:
                self.view.select(part)

    def _tree_double(self, item, col):
        kind, key = item.data(0, Qt.UserRole)
        parts = [p for p in self._parts_of(item) if p.visible]
        if not parts:
            return
        if kind == "part":
            self.view.select(parts[0])
            self.view.focus_part(parts[0])

    def _isolate(self, parts):
        keep = {p.id for p in parts}
        for p in self.model.parts:
            p.visible = p.id in keep
        self._sync_tree()

    def _isolate_current(self):
        it = self.tree.currentItem()
        if it is not None:
            self._isolate(self._parts_of(it))
        else:
            self._isolate_selected()

    def _hide_current(self):
        it = self.tree.currentItem()
        if it is None:
            return self._hide_selected()
        for p in self._parts_of(it):
            p.visible = False
        self._sync_tree()

    def _selected_parts(self, whole=False):
        """(parts, name): the part selected in the viewport, or with ``whole`` every part of its structure;
        ([], "") when nothing is selected."""
        sel = self.view.settings.selected
        if not sel or self.model is None:
            return [], ""
        if whole:
            st = next((s for s in self.model.structures if any(p.id == sel for p in s.parts)), None)
            return (list(st.parts), f"{st.title.strip()} ({len(st.parts)} parts)") if st else ([], "")
        parts = [p for p in self.model.parts if p.id == sel]
        return parts, parts[0].name if parts else ""

    def _hide_selected(self, whole=False):
        parts, name = self._selected_parts(whole)
        if not parts:
            self.statusBar().showMessage("Click a part in the viewport first", 3000)
            return
        for p in parts:
            p.visible = False
        self.view.select(None)
        self._sync_tree()
        self.statusBar().showMessage(f"Hid {name}", 4000)

    def _isolate_selected(self, whole=False):
        parts, name = self._selected_parts(whole)
        if not parts:
            self.statusBar().showMessage("Click a part in the viewport first", 3000)
            return
        self._isolate(parts)
        self.statusBar().showMessage(f"Isolated {name}", 4000)

    def _show_all(self):
        if self.model is None:
            return
        for p in self.model.parts:
            p.visible = True
        self._sync_tree()

    def _toggle(self, key, on):
        s = self.view.settings
        if key in ("ao", "shadows", "stripes"):
            setattr(s, key, on)
            self.view.kick()
            return
        if self.model is None:
            return
        for p in self.model.parts:
            if p.role == key:
                p.visible = on
        self._sync_tree()

    def _toggle_tonemap(self):
        self.view.settings.tonemap = self.tonemap_action.isChecked()
        self.view.kick()

    def _set_studio(self, v):
        self.view.settings.studio = v
        self.view.kick()

    def _set_exposure(self, v):
        self.view.settings.exposure = v
        self.view.kick()

    def _toggle_ortho(self):
        self.view.camera.toggle_ortho()
        self.view.kick()
        self.statusBar().showMessage("Orthographic" if self.view.camera.ortho else "Perspective", 2000)

    # ------------------------------------------------------------------ views, states, clip
    def _view_key(self, k):
        if self.model is None:
            return
        names = [f"V{k}"] if k <= 6 else [f"A{k - 6}"]
        for n in names:
            if n in self.model.cameras:
                self.view.set_view(n)
                return
        # a file with named stage views and none of V0-V6 / A1-A3: 1-9 step through its views in order, 0 is the 10th
        order = self.model.camera_order
        if not any(c in order for c in [f"V{i}" for i in range(7)] + ["A1", "A2", "A3"]):
            i = k - 1 if k >= 1 else 9
            if i < len(order):
                self.view.set_view(order[i])

    def _teased_clicked(self):
        names = [n for n, st in self.model.states.items() if st["offsets"]]
        if names:
            self.view.show_state(names[0])

    def _toggle_state(self):
        if self.model is None or not self.model.has_teased:
            return
        if self.view.reveal_target > 0.5:
            self.view.show_state("assembled")
        else:
            self._teased_clicked()

    def _on_state(self, name):
        self.btn_assembled.setChecked(name == "assembled")
        self.btn_teased.setChecked(name != "assembled")

    def _on_slider(self, v):
        if self.model is None or self.model.clip is None or self._slider_lock:
            return
        t0, t1 = self.model.clip_range
        self.view.set_playing(False)
        self.view.set_time(t0 + (t1 - t0) * v / 1000.0)

    _slider_lock = False

    def _on_time(self, t):
        if self.model is None or self.model.clip is None:
            self.time_label.setText("")
            return
        t0, t1 = self.model.clip_range
        self._slider_lock = True
        self.slider.setValue(int(round((t - t0) / max(t1 - t0, 1e-9) * 1000)))
        self._slider_lock = False
        fps = float((self.model.sidecar.get("clip") or {}).get("fps") or 24)
        w = max(self.model.node_weights.values()) if self.model.node_weights else 0.0
        self.time_label.setText(f"frame {t * fps:5.1f}   t {t:5.2f} s   weight {w:4.2f}")

    def _on_frame(self, ms):
        self._fps.append(ms)
        if len(self._fps) >= 30:
            avg = sum(self._fps) / len(self._fps)
            self._fps = []
            if self.model is not None:
                self.statusBar().showMessage(
                    f"{self.path.name}   {len(self.model.parts)} parts   {self.model.triangle_count:,} triangles   "
                    f"{avg:.1f} ms CPU per frame   {self.view.renderer.gl_info}")

    # ------------------------------------------------------------------ info
    def _on_pick(self, part):
        if part is None or self.model is None:
            self.info.hide()
            return
        text = self.model.describe(part).replace("\n", "<br>")
        first, _, rest = text.partition("<br>")
        self.info.setText(f"<b>{first}</b><br>{rest}")
        self.info.setMaximumWidth(420)
        self.info.adjustSize()
        self._place_info()
        self.info.show()
        self.info.raise_()
        # highlight the part in the tree
        self._tree_lock = True
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                c = top.child(j)
                if c.data(0, Qt.UserRole)[1] == part.id:
                    self.tree.blockSignals(True)
                    self.tree.setCurrentItem(c)
                    self.tree.blockSignals(False)
                    self.tree.scrollToItem(c)
        self._tree_lock = False

    def _place_info(self):
        self.info.move(12, max(12, self.view.height() - self.info.height() - 12))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._place_info)

    def _help(self):
        QMessageBox.information(self, "Controls", CONTROLS)

    def _about(self):
        QMessageBox.about(self, APP, f"<b>{APP}</b><br>Fully offline: PySide6 + moderngl + numpy.<br>"
                                     "Opens glTF 2.0 / GLB models at full resolution; a <i>.viewer.json</i> sidecar "
                                     "(viewer/tools/export_for_viewer.py) adds the Blender look, states and cameras.")
