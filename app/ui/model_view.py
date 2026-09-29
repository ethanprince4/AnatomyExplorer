"""A 3D model in a tab of its own: the model viewer.

Every model opens here - the in-house GLB models (the heart, the cardiac muscle block, the kidney with its
nephron), the procedural microanatomy models and the downloaded ones. The view is app/viewer/viewport.py; this
widget adds the parts list, the model's own views and states, the cut-away and cross-sections, labels, tissue
opacity, separated parts, the animation controls and the Details panel, and gives lessons and practice the same
hooks the old microanatomy view did (``part_ids``, ``focus_parts``, ``set_practice``).
"""
import html
import time

import numpy as np
from PySide6.QtCore import QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QSlider,
                               QSplitter, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..state import SceneState
from ..viewer.dataset import ModelDataset
from ..viewer.viewport import SECTION_NAMES, ModelViewport
from . import theme
from .flow import FlowLayout

ROLE = Qt.UserRole + 1


def esc(s):
    return html.escape(str(s or ""), quote=True)


def brief(text, limit=260):
    """A long summary cut to its first sentences for the side panel, where the parts list needs the room."""
    if len(text) <= limit:
        return text
    cut = text.rfind(". ", 0, limit)
    return text[:cut + 1] if cut > 40 else text[:limit - 1].rstrip() + "…"


def describe_view(name, rec):
    """A reader's name for a stored camera: its own note or name, else the direction it looks from."""
    if rec.get("note") and len(name) > 3:
        return name
    if len(name) > 3:
        return name
    pos, tgt = np.asarray(rec["position"], float), np.asarray(rec["target"], float)
    d = pos - tgt
    d /= max(np.linalg.norm(d), 1e-12)
    words = []
    for axis, pos_word, neg_word in ((2, "front", "back"), (1, "above", "below"), (0, "left", "right")):
        if abs(d[axis]) > 0.35:
            words.append(pos_word if d[axis] > 0 else neg_word)
    what = ", ".join(words) if words else "oblique"
    return f"{name} · from the {what}" + (" (flat projection)" if rec.get("type") == "ORTHO" else "")


class ModelView(QWidget):
    openHistology = Signal(str, int)
    openMicro = Signal(str)                    # another model
    atlasRequested = Signal(list)              # atlas structure names to show

    def __init__(self, entry, content, settings, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.model = entry                     # lessons and practice ask view.model.name
        self.content = content
        self.settings = settings
        self.info = None
        t0 = time.perf_counter()
        self.vmodel = entry.load()
        self.load_seconds = time.perf_counter() - t0
        self.mds = ModelDataset(self.vmodel)
        self.state = SceneState(self.mds, settings)
        self.gl_widget = ModelViewport(self.vmodel, self.state, settings, entry)
        self.gl_widget.home_view = self.reset_view
        self.click_hook = None        # Practice mode: callable(item) -> True when it took the click
        self.rclick_hook = None       # Practice mode: callable(item), a right click in the 3D view
        m = self.vmodel
        cut = getattr(m, "cutaway", None)
        if cut is not None:
            from ..viewer.procedural import cutaway_planes
            self.gl_widget.cut_planes = cutaway_planes(cut)
            self.gl_widget.cut_on = bool(cut["on"])
        self._view_names = list(m.camera_order)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        split = QSplitter()
        lay.addWidget(split)
        split.addWidget(self._side())
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        top = QWidget()
        top.setLayout(self._bar())
        top.setObjectName("modelBar")
        top.setStyleSheet(f"QWidget#modelBar {{ background:{theme.SURFACE}; border-bottom:1px solid {theme.BORDER_SUBTLE}; }}")
        rl.addWidget(top)
        self.section_bar = self._section_bar()
        rl.addWidget(self.section_bar)
        rl.addWidget(self.gl_widget, 1)
        split.addWidget(right)
        split.setSizes([290, 1200])

        g = self.gl_widget
        g.structureClicked.connect(self._clicked)
        g.structureDoubleClicked.connect(self._double_clicked)
        g.contextMenuRequested.connect(self._context_menu)
        g.animChanged.connect(self._anim_changed)
        g.viewChanged.connect(self._view_changed)
        self.state.visibility_changed.connect(self._sync_tree)
        self.state.selection_changed.connect(self._show_selection)
        QTimer.singleShot(0, lambda: self.reset_view(animate=False))

    # ------------------------------------------------------------------ side panel
    def _side(self):
        e, m = self.entry, self.vmodel
        side = QWidget()
        side.setMinimumWidth(250)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 12, 8, 8)
        sl.setSpacing(6)
        title = QLabel(e.name)
        title.setWordWrap(True)
        title.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_TITLE + 0.5, 700))
        sl.addWidget(title)
        summ = QLabel(brief(e.summary))
        summ.setWordWrap(True)
        if summ.text() != e.summary:
            summ.setToolTip(f"<p>{esc(e.summary)}</p>")      # the whole summary is in Details too
        summ.setStyleSheet(theme.text_css(theme.TEXT_2))
        sl.addWidget(summ)
        if e.scale_note:
            note = QLabel(e.scale_note)
            note.setWordWrap(True)
            note.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
            sl.addWidget(note)
        if e.credit_html:
            c = QLabel(e.credit_html)
            c.setWordWrap(True)
            c.setOpenExternalLinks(True)
            c.setTextInteractionFlags(Qt.TextBrowserInteraction)
            c.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
            sl.addWidget(c)
        stats = QLabel(f"{len(m.items)} parts in {len(m.groups)} groups · {m.triangle_count / 1e6:.1f} M triangles")
        stats.setStyleSheet(theme.text_css(theme.FAINT, theme.FS_CAPTION))
        sl.addWidget(stats)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter parts…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._filter_tree)
        if len(m.items) > 12:
            sl.addWidget(self.filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemClicked.connect(self._item_clicked)
        self.tree.itemDoubleClicked.connect(self._item_double_clicked)
        sl.addWidget(self.tree, 1)
        row = QHBoxLayout()
        for text, fn, tip in (("Isolate", self._isolate_current, "Show only the highlighted part or group (I)"),
                              ("Hide", self._hide_current, "Hide the highlighted part or group (H)"),
                              ("Show all", self.show_all, "Show every part again (Shift+H)")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        sl.addLayout(row)
        self._build_tree()
        self.side = side
        return side

    def _build_tree(self):
        self._sync = True
        self.part_items = {}
        self.group_items = {}
        many = len(self.vmodel.items) > 60
        for g in self.vmodel.groups:
            gi = QTreeWidgetItem(self.tree)
            gi.setText(0, f"{g.title}" + (f"   · {len(g.items)}" if len(g.items) > 1 else ""))
            f = gi.font(0)
            f.setBold(True)
            gi.setFont(0, f)
            gi.setFlags(gi.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            gi.setCheckState(0, Qt.Checked)
            gi.setData(0, ROLE, ("group", g.key))
            gi.setExpanded(not many or len(g.items) <= 6)
            self.group_items[g.key] = gi
            for i in g.items:
                it = self.vmodel.items[i]
                ti = QTreeWidgetItem(gi)
                ti.setText(0, it.name)
                if it.description:
                    ti.setToolTip(0, it.description[:300])
                ti.setFlags(ti.flags() | Qt.ItemIsUserCheckable)
                ti.setCheckState(0, Qt.Checked)
                ti.setData(0, ROLE, ("part", i))
                self.part_items[i] = ti
        self._sync = False

    def _filter_tree(self, text):
        t = text.strip().lower()
        for key, gi in self.group_items.items():
            any_shown = False
            for j in range(gi.childCount()):
                c = gi.child(j)
                show = not t or t in c.text(0).lower() or t in key.lower()
                c.setHidden(not show)
                any_shown |= show
            gi.setHidden(not any_shown)
            if t and any_shown:
                gi.setExpanded(True)

    def _sids_of(self, item):
        kind, val = item.data(0, ROLE)
        if kind == "part":
            return [val]
        g = next((g for g in self.vmodel.groups if g.key == val), None)
        return list(g.items) if g else []

    def _item_changed(self, item, col):
        if self._sync:
            return
        if item.checkState(0) == Qt.PartiallyChecked:
            return
        self.state.set_hidden(self._sids_of(item), item.checkState(0) == Qt.Unchecked)

    def _item_clicked(self, item, col):
        if self.click_hook is not None:
            return
        self.state.select(self._sids_of(item))
        self.gl_widget.update()

    def _item_double_clicked(self, item, col):
        self.gl_widget.frame_structures(self._sids_of(item))

    def _sync_tree(self):
        vis = self.state.visible_mask()
        self._sync = True
        for sid, it in self.part_items.items():
            it.setCheckState(0, Qt.Checked if vis[sid] else Qt.Unchecked)
        for key, gi in self.group_items.items():
            sids = self._sids_of(gi)
            n = int(vis[sids].sum()) if sids else 0
            gi.setCheckState(0, Qt.Checked if n == len(sids) else Qt.Unchecked if n == 0 else Qt.PartiallyChecked)
        self._sync = False

    def _current_or_selected(self):
        it = self.tree.currentItem()
        if it is not None and it.isSelected():
            return self._sids_of(it)
        return list(self.state.selected)

    def _isolate_current(self):
        sids = self._current_or_selected()
        if sids:
            self.state.isolate(sids)

    def _hide_current(self):
        sids = self._current_or_selected()
        if sids:
            self.state.set_hidden(sids, True)
            self._show_selection()

    # ------------------------------------------------------------------ top bar
    def _bar(self):
        m = self.vmodel
        g = self.gl_widget
        bar = FlowLayout(spacing=6)
        bar.setContentsMargins(8, 6, 8, 6)

        def labelled(text, widget):
            box = QWidget()
            hl = QHBoxLayout(box)
            hl.setContentsMargins(6, 0, 0, 0)
            hl.setSpacing(6)
            hl.addWidget(QLabel(text))
            hl.addWidget(widget)
            return box

        # the model's own stored views: named stage views as buttons, a camera set in a menu
        self.view_buttons = {}
        if self._view_names:
            named = all(len(n) > 3 for n in self._view_names)
            if named and len(self._view_names) <= 10:
                for n in self._view_names:
                    b = QPushButton(n)
                    b.setCheckable(True)
                    rec = m.cameras[n]
                    b.setToolTip(rec.get("note", n) + "  (Page Down / Page Up step through the views)")
                    b.clicked.connect(lambda _=False, v=n: self.set_named_view(v))
                    bar.addWidget(b)
                    self.view_buttons[n] = b
            else:
                vb = QToolButton()
                vb.setText("Views ▾")
                vb.setToolTip("The model's stored views (Page Down / Page Up step through them)")
                vb.setPopupMode(QToolButton.InstantPopup)
                menu = QMenu(vb)
                for n in self._view_names:
                    menu.addAction(describe_view(n, m.cameras[n]), lambda v=n: self.set_named_view(v))
                vb.setMenu(menu)
                bar.addWidget(vb)
        if m.has_teased:
            self.teased = QCheckBox("Teased")
            names = [n for n, st in m.states.items() if st["offsets"]]
            self.teased.setToolTip((m.states[names[0]].get("description") or "Open the model's teased state") + " (T)")
            self.teased.toggled.connect(lambda on: g.show_state(names[0] if on else "assembled"))
            bar.addWidget(self.teased)
        else:
            self.teased = None
        self.cut = None
        if g.cut_planes is not None:
            self.cut = QCheckBox("Cut-away")
            self.cut.setChecked(g.cut_on)
            self.cut.setToolTip("Cut a corner out of the model to show its inside in section")
            self.cut.toggled.connect(self._toggle_cut)
            bar.addWidget(self.cut)
        sec = QToolButton()
        sec.setText("Section ▾")
        sec.setToolTip("Sagittal, coronal and transverse cross-sections through the model (Ctrl+Alt+1/2/3)")
        sec.setPopupMode(QToolButton.InstantPopup)
        smenu = QMenu(sec)
        self.section_actions = []
        for i, name in enumerate(SECTION_NAMES):
            a = smenu.addAction(name)
            a.setCheckable(True)
            a.toggled.connect(lambda on, k=i: self.set_section(k, on))
            self.section_actions.append(a)
        smenu.addSeparator()
        smenu.addAction("Clear cross-sections", self.clear_sections)
        sec.setMenu(smenu)
        self.section_btn = sec
        bar.addWidget(sec)
        self.labels = QCheckBox("Labels")
        self.labels.setToolTip("Name every visible part (L)")
        self.labels.toggled.connect(self._toggle_labels)
        bar.addWidget(self.labels)
        self.opacity = None
        if any(it.bulk for it in m.items):
            self.opacity = QSlider(Qt.Horizontal)
            self.opacity.setRange(8, 100)
            self.opacity.setValue(100)
            self.opacity.setFixedWidth(110)
            self.opacity.valueChanged.connect(self._opacity)
            bar.addWidget(labelled("Tissue opacity", self.opacity))
        self.explode = QSlider(Qt.Horizontal)
        self.explode.setRange(0, 100)
        self.explode.setFixedWidth(120)
        self.explode.valueChanged.connect(lambda v: (g.set_explode(v / 100.0), g.update()))
        bar.addWidget(labelled("Separate layers" if m.kind == "procedural" else "Separate parts", self.explode))
        for text, fn, tip in (("X-ray others", self.toggle_xray, "Everything but the selection goes see-through (X)"),
                              ("Isolate", self.isolate_selection, "Show only the selection (I)"),
                              ("Show all", self.show_all, "Show every part (Shift+H)"),
                              ("Reset view", self.reset_view, "Back to the model's home view (Home)")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
        if g.anim_kind() is not None:
            self._anim_controls(bar, labelled)
        else:
            self.play = None
        bar.add_right(self._display_menu())
        if self.entry.histology or self.entry.related:
            more = QToolButton()
            more.setText("Related ▾")
            more.setPopupMode(QToolButton.InstantPopup)
            menu = QMenu(more)
            for tid in self.entry.histology:
                t = self.content.tissues.get(tid)
                if t and t.get("images"):
                    menu.addAction(f"Histology · {t['name']}", lambda x=tid: self.openHistology.emit(x, 0))
            for mid in self.entry.related:
                other = self.content.micro_models.get(mid)
                if other and mid != self.entry.id:
                    menu.addAction(f"Model · {other.name}", lambda x=mid: self.openMicro.emit(x))
            more.setMenu(menu)
            bar.add_right(more)
        return bar

    def _display_menu(self):
        g = self.gl_widget
        b = QToolButton()
        b.setText("Display ▾")
        b.setToolTip("Shadows, striations, lighting, exposure and projection of this view")
        b.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(b)
        rs = g.rsettings

        def toggle(text, attr, tip=""):
            a = menu.addAction(text)
            a.setCheckable(True)
            a.setChecked(bool(getattr(rs, attr)))
            a.setToolTip(tip)
            a.toggled.connect(lambda on: (setattr(rs, attr, on), g.update()))
            return a

        toggle("Shadows", "shadows")
        if any(p.look.stripe for p in self.vmodel.parts):
            toggle("Striations", "stripes")
        toggle("Tone mapping (Khronos PBR Neutral)", "tonemap")
        menu.addSeparator()
        lm = menu.addMenu("Lighting")
        grp = QActionGroup(self)
        studios = [("Even (flat ambient)", 0.0), ("Soft studio", 0.3), ("Bright studio", 0.7)]
        if all(abs(v - rs.studio) > 1e-6 for _t, v in studios):
            studios.insert(0, ("This model's default", rs.studio))
        for text, val in studios:
            a = lm.addAction(text, lambda v=val: (setattr(rs, "studio", v), g.update()))
            a.setCheckable(True)
            a.setChecked(abs(val - rs.studio) < 1e-6)
            grp.addAction(a)
        em = menu.addMenu("Exposure")
        grp2 = QActionGroup(self)
        for ev in sorted({-1.0, -0.5, 0.0, 0.5, 1.0, round(rs.exposure, 2)}):
            a = em.addAction(f"{ev:+.2g} EV" + ("  (default)" if abs(ev - rs.exposure) < 1e-6 else ""),
                             lambda v=ev: (setattr(rs, "exposure", v), g.update()))
            a.setCheckable(True)
            a.setChecked(abs(ev - rs.exposure) < 1e-6)
            grp2.addAction(a)
        menu.addSeparator()
        self.ortho_action = menu.addAction("Flat (orthographic) projection")
        self.ortho_action.setCheckable(True)
        self.ortho_action.setToolTip("P")
        self.ortho_action.toggled.connect(self._set_ortho)
        b.setMenu(menu)
        return b

    def _set_ortho(self, on):
        if self.gl_widget.camera.ortho != on:
            self.gl_widget.toggle_projection()

    def toggle_projection(self):
        self.ortho_action.setChecked(not self.gl_widget.camera.ortho)

    # ------------------------------------------------------------------ sections
    def _section_bar(self):
        w = QWidget()
        w.setObjectName("sectionBar")
        w.setStyleSheet(f"QWidget#sectionBar {{ background:{theme.SURFACE}; border-bottom:1px solid {theme.BORDER_SUBTLE}; }}")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(10, 4, 10, 4)
        self.section_rows = []
        for i, name in enumerate(SECTION_NAMES):
            box = QWidget()
            hl = QHBoxLayout(box)
            hl.setContentsMargins(0, 0, 12, 0)
            hl.addWidget(QLabel(name))
            s = QSlider(Qt.Horizontal)
            s.setRange(0, 1000)
            s.setValue(500)
            s.setMinimumWidth(120)
            s.valueChanged.connect(lambda v, k=i: self._section_moved(k))
            hl.addWidget(s, 1)
            f = QCheckBox("Flip")
            f.toggled.connect(lambda _on, k=i: self._section_moved(k))
            hl.addWidget(f)
            box.hide()
            lay.addWidget(box, 1)
            self.section_rows.append((box, s, f))
        lay.addStretch(0)
        w.hide()
        return w

    def _axis_range(self, k):
        lo, hi = self.vmodel.bounds_min, self.vmodel.bounds_max
        a = [0, 2, 1][k]
        return float(lo[a]), float(hi[a])

    def set_section(self, k, on):
        g = self.gl_widget
        box, s, f = self.section_rows[k]
        if on:
            if not f.isChecked() and k in (1, 2):
                f.blockSignals(True)
                f.setChecked(True)          # coronal from the front, transverse from above, as the atlas cuts
                f.blockSignals(False)
            lo, hi = self._axis_range(k)
            g.sections[k] = [lo + (hi - lo) * s.value() / 1000.0, f.isChecked()]
        else:
            g.sections[k] = None
        a = self.section_actions[k]
        if a.isChecked() != on:
            a.blockSignals(True)
            a.setChecked(on)
            a.blockSignals(False)
        box.setVisible(on)
        self.section_bar.setVisible(any(x is not None for x in g.sections))
        self._mark_section()
        g.invalidate_labels()

    def toggle_section(self, k):
        self.set_section(k, self.gl_widget.sections[k] is None)

    def clear_sections(self):
        for k in range(3):
            self.set_section(k, False)

    def _section_moved(self, k):
        g = self.gl_widget
        if g.sections[k] is None:
            return
        _box, s, f = self.section_rows[k]
        lo, hi = self._axis_range(k)
        g.sections[k] = [lo + (hi - lo) * s.value() / 1000.0, f.isChecked()]
        g.invalidate_labels()

    def _mark_section(self):
        on = any(x is not None for x in self.gl_widget.sections)
        b = self.section_btn
        if bool(b.property("active")) != on:
            b.setProperty("active", on)
            b.style().unpolish(b)
            b.style().polish(b)

    def _toggle_cut(self, on):
        self.gl_widget.cut_on = on
        self.gl_widget.invalidate_labels()

    # ------------------------------------------------------------------ animation
    def _anim_controls(self, bar, labelled):
        g = self.gl_widget
        kind = g.anim_kind()
        anim = getattr(self.vmodel, "animation", None)
        self.play = QPushButton("▶ Play")
        self.play.setCheckable(True)
        self.play.setToolTip(f"Play the {(anim.title if anim else self.vmodel.clip.name).lower()} (Space)")
        self.play.toggled.connect(self._play_toggled)
        bar.addWidget(self.play)
        self.speed = QComboBox()
        speeds = anim.speeds if anim is not None else (1.0, 0.5, 0.25)
        for sp in speeds:
            self.speed.addItem("real time" if sp == 1.0 else f"{sp:g}× (slowed)", sp)
        self.speed.setToolTip("Playback speed - the cycle is slowed, not the physiology")
        self.speed.currentIndexChanged.connect(lambda i: setattr(g, "speed", self.speed.itemData(i)))
        g.speed = speeds[0]
        bar.addWidget(self.speed)
        self.scrub = QSlider(Qt.Horizontal)
        self.scrub.setRange(0, 1000)
        self.scrub.setFixedWidth(150)
        self.scrub.setToolTip("Scrub through the cycle (pauses playback)")
        self.scrub.sliderMoved.connect(self._scrubbed)
        bar.addWidget(labelled("Cycle" if kind == "procedural" else "Clip", self.scrub))
        self.phase_label = QLabel("")
        self.phase_label.setMinimumWidth(190)
        self.phase_label.setStyleSheet(f"color:{theme.SUCCESS};")
        bar.addWidget(self.phase_label)
        self._anim_changed(g.anim_fraction())

    def _play_toggled(self, on):
        self.play.setText("❚❚ Pause" if on else "▶ Play")
        self.gl_widget.set_playing(on)

    def toggle_play(self):
        if self.play is not None:
            self.play.setChecked(not self.play.isChecked())

    def _scrubbed(self, value):
        if self.play.isChecked():
            self.play.setChecked(False)
        self.gl_widget.set_anim_fraction(value / 1000.0)

    def _anim_changed(self, f):
        if getattr(self, "play", None) is None:
            return
        if not self.scrub.isSliderDown():
            self.scrub.blockSignals(True)
            self.scrub.setValue(int(round(f * 1000)) % 1001)
            self.scrub.blockSignals(False)
        anim = getattr(self.vmodel, "animation", None)
        self.phase_label.setText(anim.phase_label(f) if anim is not None else "")

    def hideEvent(self, e):
        # nothing animates behind another tab
        if getattr(self, "play", None) is not None and self.play.isChecked():
            self.play.setChecked(False)
        super().hideEvent(e)

    # ------------------------------------------------------------------ views and states
    def reset_view(self, animate=True):
        self.gl_widget.reset_view(animate=animate)

    def set_named_view(self, name):
        self.gl_widget.set_named_view(name)

    def step_view(self, step):
        names = self._view_names
        if not names:
            return
        cur = getattr(self, "_current_view", None)
        i = names.index(cur) if cur in names else (-1 if step > 0 else 0)
        self.set_named_view(names[(i + step) % len(names)])

    def _view_changed(self, name):
        self._current_view = name
        for n, b in self.view_buttons.items():
            b.setChecked(n == name)

    def toggle_state(self):
        if self.teased is not None:
            self.teased.setChecked(not self.teased.isChecked())

    # ------------------------------------------------------------------ view controls (the atlas's commands)
    def _toggle_labels(self, on):
        self.gl_widget.labels_on = on
        self.gl_widget.invalidate_labels()

    def toggle_labels(self):
        self.labels.setChecked(not self.labels.isChecked())

    def _opacity(self, value):
        bulk = np.array([it.bulk for it in self.vmodel.items], dtype=bool)
        self.state.part_alpha = np.where(bulk, value / 100.0, 1.0).astype(np.float32)
        self.state.render_changed.emit()

    def toggle_xray(self):
        if self.state.ghost_focus is not None:
            self.state.clear_ghost()
        elif self.state.selected:
            self.state.set_ghost_focus(self.state.selected)
        return self.state.ghost_focus is not None

    def isolate_selection(self):
        if self.state.selected:
            self.state.isolate(self.state.selected)
            self.gl_widget.frame_structures(self.state.selected)

    def hide_selection(self):
        if self.state.selected:
            self.state.set_hidden(list(self.state.selected), True)
            self._show_selection()

    def show_all(self):
        st = self.state
        st.push_undo()
        st.hidden[:] = False
        st.forced[:] = False
        st.isolated = None
        st.ghost_focus = None
        st.system_on[:] = True
        st._vis_dirty()

    def undo(self):
        self.state.undo()

    def frame_selection(self):
        if self.state.selected:
            self.gl_widget.frame_structures(self.state.selected)
        else:
            self.gl_widget.frame_visible()

    def escape(self):
        """Esc: the measurement, then the x-ray, then the selection - as in the atlas."""
        g = self.gl_widget
        if g.measure_points:
            g.clear_measure()
            return True
        if self.state.ghost_focus is not None:
            self.state.clear_ghost()
            return True
        if self.state.selected:
            self.state.clear_selection()
            self._show_selection()
            return True
        return False

    # ------------------------------------------------------------------ selection & details
    def _clicked(self, sid, modifiers):
        if self.click_hook is not None and self.click_hook(sid):
            return
        if sid < 0:
            if self.state.clear_selection():
                self._show_selection()
            return
        self.state.select([sid], add=bool(modifiers & Qt.ControlModifier))
        it = self.part_items.get(sid)
        if it:
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(it)
            self.tree.blockSignals(False)
            self.tree.scrollToItem(it)
        if self.settings.get("click_action") == "Select and focus" and self.state.selected:
            self.gl_widget.frame_structures(self.state.selected)
        self._show_selection()

    def _double_clicked(self, sid):
        if sid < 0 or self.click_hook is not None:
            return
        action = self.settings.get("double_click_action", "Focus")
        self.state.select([sid])
        if action == "Isolate":
            self.state.isolate([sid])
        elif action == "X-ray focus":
            self.state.set_ghost_focus([sid])
        self.gl_widget.frame_structures([sid])
        self._show_selection()

    def _context_menu(self, sid, global_pos):
        if self.rclick_hook is not None:
            self.rclick_hook(sid)
            return
        m = QMenu(self)
        if sid >= 0:
            if sid not in self.state.selected:
                self._clicked(sid, Qt.NoModifier)
            it = self.vmodel.items[sid]
            title = m.addAction(it.name)
            title.setEnabled(False)
            m.addSeparator()
            m.addAction("Frame", lambda: self.gl_widget.frame_structures(self.state.selected))
            m.addAction("X-ray others", self.toggle_xray)
            m.addAction("Isolate", self.isolate_selection)
            m.addAction("Hide", self.hide_selection)
            g = self.vmodel.group_of(sid)
            if g is not None and len(g.items) > 1:
                m.addAction(f"Hide all {g.title.lower()}", lambda: self.state.set_hidden(g.items, True))
                m.addAction(f"Select all {g.title.lower()}", lambda: (self.state.select(g.items), self._show_selection()))
            if it.atlas:
                m.addAction("Show in the atlas", lambda: self.atlasRequested.emit(list(it.atlas)))
            m.addSeparator()
            from PySide6.QtGui import QGuiApplication
            m.addAction("Copy name", lambda: QGuiApplication.clipboard().setText(it.name))
        else:
            m.addAction("Show all", self.show_all)
            m.addAction("Undo visibility change", self.undo)
            m.addAction("Reset view", self.reset_view)
        m.exec(global_pos)

    def figure_caption(self):
        """(title, caption parts, credit line) for File -> Export labelled figure: what this view shows."""
        m, st, g = self.vmodel, self.state, self.gl_widget
        sel = [m.items[i].name for i in st.selected]
        title = sel[0] if len(sel) == 1 else (f"{len(sel)} parts" if sel else self.entry.name)
        bits = [self.entry.name] if sel else []
        if g.section_items:
            names = [m.items[i].name for i, _a in g.section_items]
            planes = [SECTION_NAMES[k] for k, s in enumerate(g.sections) if s is not None]
            where = (" and ".join(planes) + " section" if planes else "Cut-away") + " through: "
            bits.append(where + ", ".join(names))
        elif sel:
            bits.append(", ".join(sorted(set(sel))))
        bits.append(f"{int(st.visible_mask().sum()):,} of {len(m.items):,} parts visible")
        e = self.entry
        if e.kind == "downloaded":
            info = getattr(e, "info", {}) or {}
            source = f"{e.name} by {info.get('author', 'its creator')}, {info.get('license', '')}".rstrip(", ")
            credit = f"Anatomy Explorer · {source} (Sketchfab)"
        elif e.kind == "procedural":
            credit = "Anatomy Explorer · procedural model made for the app"
        elif e.id.startswith("file:"):
            credit = f"Anatomy Explorer · {getattr(e, 'path', e.name)}"
        else:
            credit = "Anatomy Explorer · 3D model made for the app"
        return title, bits, credit

    # ------------------------------------------------------------------ lessons & practice
    def part_ids(self, names):
        """Item indices for part names from a lesson or practice item (exact names, groups and the model's
        aliases, case-insensitive), and the names that matched nothing."""
        return self.entry.resolve(self.vmodel, names)

    def focus_parts(self, names):
        """A lesson step's "micro_focus": select these parts, x-ray the rest, label and frame them.
        Returns the names that are not parts of this model."""
        sids, missing = self.part_ids(names)
        if sids:
            self.state.set_hidden(sids, False)
            self.state.select(sids)
            self.state.set_ghost_focus(sids)
            self._show_selection()
            # after reset_view, which a freshly opened model queues for its first frame
            QTimer.singleShot(250, lambda: self.gl_widget.frame_structures(sids))
        return missing

    def set_practice(self, click=None, rclick=None):
        """Practice mode takes the clicks, and the parts list and labels are put away: they would give the answer."""
        on = click is not None
        self.click_hook, self.rclick_hook = click, rclick
        self.side.setVisible(not on)
        self.gl_widget.names_hidden = (lambda: True) if on else (lambda: False)
        if on:
            self.labels.setChecked(False)
            self.show_all()
            self.state.clear_selection()
            self.reset_view()
        self.gl_widget.invalidate_labels()

    def _refresh_labels(self):
        self.gl_widget.invalidate_labels()

    def on_activated(self, info):
        self.info = info
        self._show_selection()

    def _show_selection(self):
        self.gl_widget.invalidate_labels()
        if not self.info or self.click_hook is not None:
            return
        sel = list(self.state.selected)
        e, m = self.entry, self.vmodel
        hist = []
        for tid in e.histology:
            t = self.content.tissues.get(tid)
            if not t or not t.get("images"):
                continue
            thumbs = "".join(
                f'<td style="padding:2px"><a href="histo:{esc(tid)}|{i}"><img src="'
                f'{QUrl.fromLocalFile(str(self.content.thumb_path(img))).toString()}" width="96" height="72"></a></td>'
                for i, img in enumerate(t["images"][:3]))
            hist.append(f'<p><b><a href="histo:{esc(tid)}|0">{esc(t["name"])}</a></b></p>'
                        f'<table cellspacing="0" cellpadding="0"><tr>{thumbs}</tr></table>')
        related = " · ".join(f'<a href="micro:{esc(r)}">{esc(self.content.micro_models[r].name)}</a>'
                             for r in e.related if r in self.content.micro_models and r != e.id)
        clinical = "".join(f"<p><b>{esc(t)}</b><br>{esc(x)}</p>" for t, x in e.clinical)
        tail = ""
        if clinical:
            tail += f"<p class='overline'>CLINICAL CORRELATIONS</p>{clinical}"
        if hist:
            tail += "<p class='overline'>HISTOLOGY</p>" + "".join(hist)
        if related:
            tail += f"<p class='overline'>RELATED MODELS</p><p>{related}</p>"
        if e.credit_html:
            tail += f"<p class='muted'>{e.credit_html}</p>"
        if len(sel) == 1:
            it = m.items[sel[0]]
            g = m.group_of(it.index)
            siblings = [m.items[i].name for i in (g.items if g else []) if i != it.index]
            atlas = ""
            if it.atlas:
                atlas = (f"<p><a href=\"atlas:{esc('|'.join(it.atlas))}\">Show {esc(it.name.lower())} in the "
                         f"atlas</a></p>")
            desc = it.description
            size = ""
            if m.metres_per_unit and it.parts:
                b = m.item_bounds([it.index])
                if b is not None:
                    ext = sorted((b[1] - b[0]) * m.metres_per_unit, reverse=True)
                    size = f"<p class='muted'>About {self.gl_widget._format_length(ext[0])} across</p>"
            more = ""
            if siblings:
                shown = siblings[:24]
                extra = f" and {len(siblings) - len(shown)} more" if len(siblings) > len(shown) else ""
                more = (f"<p class='overline'>ALSO IN {esc(it.group.upper())}</p>"
                        f"<p class='muted'>{esc(' · '.join(shown))}{esc(extra)}</p>")
            body = (f"<div class='crumb'>{esc(e.name)} › {esc(it.group)}</div>"
                    f"<p class='summary'>{esc(desc)}</p>{size}{atlas}{more}{tail}")
            self.info.show_html(f"<h1>{esc(it.name)}</h1>", body)
        elif len(sel) > 1:
            names = " · ".join(esc(m.items[i].name) for i in sel[:40])
            body = (f"<div class='crumb'>{esc(e.name)}</div><p class='summary'>{len(sel)} parts selected</p>"
                    f"<p class='muted'>{names}</p>{tail}")
            self.info.show_html(f"<h1>{esc(e.name)}</h1>", body)
        else:
            groups = []
            for gr in m.groups:
                names = " · ".join(esc(m.items[i].name) for i in gr.items[:12])
                if len(gr.items) > 12:
                    names += f" · … ({len(gr.items)} in all)"
                groups.append(f"<p><b>{esc(gr.title)}</b><br><span class='muted'>{names}</span></p>")
            hint = ("Click any part in 3D or in the list to read about it. Use the cut-away, a section, "
                    "Separate parts and X-ray to see inside." if m.kind != "glb" else
                    "Click any part in 3D or in the list to read about it. Hide parts (H) or use a section to "
                    "look inside; Labels names everything in view.")
            body = (f"<p class='summary'>{esc(e.summary)}</p><p class='muted'>{hint}</p>"
                    f"<p class='overline'>PARTS</p>{''.join(groups)}{tail}")
            self.info.show_html(f"<h1>{esc(e.name)}</h1>", body)
