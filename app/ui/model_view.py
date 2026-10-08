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
                               QScrollArea, QSplitter, QGridLayout, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..actions import key_text
from ..state import SceneState
from ..viewer.dataset import ModelDataset
from ..viewer.part_guide import load_part_guide
from ..viewer.viewport import SECTION_NAMES, ModelViewport
from . import theme
from .flow import FlowLayout
from .search_panel import normalized

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
    lessonsRequested = Signal(str)             # explicitly authored lessons for this model
    atlasRequested = Signal(list)              # atlas structure names to show
    variantRequested = Signal(str)             # one independently selected version
    componentRequested = Signal(str)           # separate space in the same selected version

    def __init__(self, entry, content, settings, parent=None, *, prepared=None):
        super().__init__(parent)
        self.entry = entry
        self.setAccessibleName(f"3D model: {entry.name}")
        self._filter_expanded = None
        self.model = entry                     # lessons and practice ask view.model.name
        self.content = content
        if getattr(getattr(entry, "micro", None), "labels_on_open", False):
            settings = dict(settings, show_landmarks=True,
                            max_landmarks=max(60, int(settings.get("max_landmarks", 60))))
        self.settings = settings
        self.info = None
        t0 = time.perf_counter()
        self.vmodel = entry.load() if prepared is None else prepared.model
        self.vmodel.label_by_family = entry.id == "cardiac_muscle"
        self.load_seconds = time.perf_counter() - t0 if prepared is None else prepared.seconds
        self.mds = ModelDataset(self.vmodel)
        self.state = SceneState(self.mds, settings)
        self.gl_widget = ModelViewport(self.vmodel, self.state, settings, entry, parent=self)
        self.gl_widget.home_view = self.reset_view
        self.click_hook = None        # Practice mode: callable(item) -> True when it took the click
        self.rclick_hook = None       # Practice mode: callable(item), a right click in the 3D view
        m = self.vmodel
        cut = getattr(m, "cutaway", None)
        if cut is not None:
            from ..viewer.procedural import cutaway_planes
            self.gl_widget.cut_planes = cutaway_planes(cut)
            self.gl_widget.cut_on = False
        self._view_names = list(m.camera_order)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        side = self._side()
        reveal = QWidget()
        reveal.setObjectName("studioRevealControls")
        reveal.setLayout(self._bar())
        self.section_bar = self._section_bar()
        sections = QWidget()
        section_layout = QVBoxLayout(sections)
        section_layout.setContentsMargins(0, 0, 0, 0)
        for action in self.section_actions:
            toggle = QCheckBox(action.text())
            toggle.setChecked(action.isChecked())
            toggle.toggled.connect(action.setChecked)
            action.toggled.connect(toggle.setChecked)
            section_layout.addWidget(toggle)
        section_layout.addWidget(self.section_bar)
        clear = QPushButton("Clear sections")
        clear.clicked.connect(self.clear_sections)
        section_layout.addWidget(clear)
        section_layout.addStretch()
        from .model_teaching import ModelTeachingControls
        self.teaching_controls = ModelTeachingControls(self)
        from .studio_scene import StudioScene
        self.studio = StudioScene(self.gl_widget, side, self._compact_reveal(reveal), sections, self.teaching_controls, self)
        self.studio.set_subject(entry.name, brief(entry.summary,150), getattr(entry,"kind_name","3D models"),len(self.vmodel.items))
        self.splitter = self.studio  # Retain the public layout owner; renderer stays unchanged.
        lay.addWidget(self.studio)
        self.studio.select.clicked.connect(lambda: self.gl_widget.set_measure(False))
        self.studio.measure.toggled.connect(self.gl_widget.set_measure)
        self.studio.measure.toggled.connect(lambda on:self.studio.select.setChecked(not on))
        self.studio.isolateRequested.connect(self.isolate_selection)
        self.studio.detailsRequested.connect(self._open_selected_details)
        self.gl_widget.measureChanged.connect(self._studio_measure_changed)
        self.studio.labels.setChecked(self.labels.isChecked())
        self.studio.labels.toggled.connect(self.labels.setChecked)
        self.labels.toggled.connect(self.studio.labels.setChecked)
        self.studio.show_all.clicked.connect(self.show_all)
        self.studio.reset.clicked.connect(self.reset_view)

        g = self.gl_widget
        g.structureClicked.connect(self._clicked)
        g.structureDoubleClicked.connect(self._double_clicked)
        g.contextMenuRequested.connect(self._context_menu)
        g.animChanged.connect(self._anim_changed)
        g.viewChanged.connect(self._view_changed)
        self.state.visibility_changed.connect(self._sync_tree)
        self.state.selection_changed.connect(self._show_selection)
        self._sync_tree()
        self.reset_view(animate=False)
        self.runtime_session = None
        self.runtime_opening_done = True
        self.runtime_opening_error = ""
        if getattr(entry, "descriptor", None) is not None:
            from ..variants.anatomy_runtime_adapters import bind_view
            local = bool(getattr(getattr(entry, "store", None), "is_local", False))
            try:
                if not local or getattr(self.vmodel, "runtime_hooks_available", True):
                    self.runtime_session = bind_view(self)
                    self.teaching_controls.set_session(self.runtime_session)
                    self.runtime_opening_done = False
                    # Home reset, then authored opening, then lesson/practice on_ready.
                    self._runtime_opening()
            except Exception as exc:
                if not local:
                    raise
                self.runtime_session = None
                self.teaching_controls.setToolTip('Some teaching controls are unavailable for this saved model: '+str(exc))
                self.vmodel.runtime_warnings = list(getattr(self.vmodel, 'runtime_warnings', []))+[str(exc)]

        self.state.clear_selection()
        self._show_selection()

        # The GL widget stays visible beneath a sibling cover while it uploads
        # geometry and warms its first frame. Never publish a half-ready view.
        if hasattr(g,'interactiveReady'):
            g.interactiveReady.connect(self._graphics_ready)
            g.graphicsFailed.connect(self._graphics_failed)
            self.studio.set_loading(not getattr(g,'interactive_ready',False),getattr(g,'graphics_error',''))

    def _graphics_ready(self):
        self.studio.set_loading(False)

    def _graphics_failed(self,message):
        self.studio.set_loading(True,error=message)

    def _fully_visible(self):
        state=self.state
        # Procedural tissue opacity is a viewer control; imported GLBs already
        # carry authored material colours and alpha that should survive opening.
        state.opaque_materials=self.vmodel.kind == "procedural"
        state.hidden[:]=False;state.forced[:]=False;state.isolated=None;state.ghost_focus=None
        state.system_on[:]=True;state.subsystem_on[:]=True;state.region_on[:]=True
        state.system_alpha[:]=1.0;state.part_alpha=np.ones(len(self.vmodel.items),dtype=np.float32)
        state.depth_cut=0.0;state.depth_band=0.0
        self.gl_widget.cut_on=False
        if getattr(self,'cut',None) is not None:self.cut.setChecked(False)
        if getattr(self,'opacity',None) is not None:self.opacity.setValue(100)
        self.clear_sections()
        state._vis_dirty()

    def _compact_reveal(self, advanced):
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        sliders = QGridLayout()
        sliders.setContentsMargins(0, 4, 0, 4)
        sliders.setVerticalSpacing(8)
        for column, (title, original) in enumerate((("Tissue opacity", self.opacity), ("Separate layers", self.explode))):
            label = QLabel(title)
            sliders.addWidget(label, 0, column)
            slider = QSlider(Qt.Horizontal)
            slider.setAccessibleName(title)
            slider.setMinimumHeight(28)
            if original is not None:
                slider.setRange(original.minimum(), original.maximum())
                slider.setValue(original.value())
                slider.valueChanged.connect(original.setValue)
                original.valueChanged.connect(slider.setValue)
            else:
                slider.setEnabled(False)
                slider.setToolTip("This model has no tissue-opacity layers.")
            sliders.addWidget(slider, 1, column)
        layout.addLayout(sliders)
        row = QHBoxLayout()
        cut = QCheckBox("Cut-away")
        cut.setEnabled(self.cut is not None)
        if self.cut is not None:
            cut.setChecked(self.cut.isChecked())
            cut.toggled.connect(self.cut.setChecked)
            self.cut.toggled.connect(cut.setChecked)
        row.addWidget(cut)
        if self.teased is not None:
            teased = QCheckBox("Teased")
            teased.setToolTip(self.teased.toolTip())
            teased.setChecked(self.teased.isChecked())
            teased.toggled.connect(self.teased.setChecked)
            self.teased.toggled.connect(teased.setChecked)
            self.teased.hide()
            row.addWidget(teased)
        reset = QPushButton("Reset")
        def reset_reveal():
            if self.opacity is not None:self.opacity.setValue(100)
            self.explode.setValue(0)
            if self.cut is not None:self.cut.setChecked(False)
        reset.clicked.connect(reset_reveal)
        row.addWidget(reset)
        more = QPushButton("More controls")
        more.setCheckable(True)
        row.addWidget(more)
        layout.addLayout(row)
        advanced.hide()
        layout.addWidget(advanced)
        def expanded(on):
            advanced.setVisible(on);body.setProperty('expanded',on)
            layout.invalidate()
            body.updateGeometry()
            if hasattr(self,'studio'):self.studio.arrange()
        more.toggled.connect(expanded)
        return body

    def _open_selected_details(self):
        self._show_selection()
        for key in ('reveal', 'section'):
            self.studio.tools[key].setChecked(False)
        dock = getattr(self.window(), 'right_dock', None)
        if dock is not None:dock.show();dock.raise_()
        elif self.info is not None:self.info.show();self.info.raise_()

    def _studio_measure_changed(self, text):
        button = self.studio.measure
        button.blockSignals(True)
        button.setChecked(self.gl_widget.measure_mode)
        button.blockSignals(False)
        self.studio.select.setChecked(not self.gl_widget.measure_mode)
        button.setToolTip(text or "Click two points to measure. Shift-click adds another leg.")

    def _runtime_opening(self):
        try:
            self.runtime_session.opening()
        except Exception as exc:
            self.runtime_opening_error = str(exc)
        finally:
            self._fully_visible()
            self.state.clear_selection()
            self._show_selection()
            self.runtime_opening_done = True

    # ------------------------------------------------------------------ side panel
    def _side(self):
        e, m = self.entry, self.vmodel
        side = QWidget()
        side.setMinimumWidth(0)
        side.setAccessibleName("Model overview and parts")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(4, 2, 4, 4)
        sl.setSpacing(6)
        intro_body = QWidget()
        intro_layout = QVBoxLayout(intro_body)
        intro_layout.setContentsMargins(0, 0, 0, 0)
        intro_layout.setSpacing(2)
        intro_layout.setAlignment(Qt.AlignTop)
        intro_scroll = QScrollArea()
        intro_scroll.setWidgetResizable(True)
        intro_scroll.setFrameShape(QScrollArea.NoFrame)
        intro_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        intro_scroll.setMinimumHeight(0)
        intro_scroll.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        intro_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        intro_scroll.setAccessibleName("Model description")
        intro_scroll.setWidget(intro_body)
        from .variant_choice import VariantChoice
        self.variant_choice = VariantChoice(self)
        self.variant_choice.set_entry(e)
        self.variant_choice.requested.connect(self.variantRequested)
        self.variant_choice.componentRequested.connect(self.componentRequested)
        summ = QLabel(e.summary.strip())
        summ.setTextFormat(Qt.PlainText)
        summ.setWordWrap(True)
        summ.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        if summ.text() != e.summary:
            summ.setToolTip(f"<p>{esc(e.summary)}</p>")      # the whole summary is in Details too
        summ.setStyleSheet(theme.text_css(theme.TEXT_2))
        intro_layout.addWidget(summ)
        if e.scale_note:
            note = QLabel(e.scale_note.strip())
            note.setTextFormat(Qt.PlainText)
            note.setWordWrap(True)
            note.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            note.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
            intro_layout.addWidget(note)
        if e.credit_html:
            c = QLabel(e.credit_html)
            c.setWordWrap(True)
            c.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            c.setOpenExternalLinks(True)
            c.setTextInteractionFlags(Qt.TextBrowserInteraction)
            c.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
            intro_layout.addWidget(c)
        sl.addWidget(intro_scroll)
        sl.addWidget(self.variant_choice)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter parts or groups…")
        self.filter.setAccessibleName("Filter model parts")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._filter_tree)
        sl.addWidget(self.filter)
        self.parts_status = QLabel()
        self.parts_status.setWordWrap(True)
        self.parts_status.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
        sl.addWidget(self.parts_status)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAccessibleName("Model parts and visibility")
        self.tree.setMinimumHeight(0)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(14)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemClicked.connect(self._item_clicked)
        self.tree.itemActivated.connect(self._item_activated)
        self.tree.itemExpanded.connect(self._parts_layout_changed)
        self.tree.itemCollapsed.connect(self._parts_layout_changed)
        sl.addWidget(self.tree, 1)
        self.selection_status = QLabel("Select a part to read its details.")
        self.selection_status.setWordWrap(True)
        self.selection_status.setStyleSheet(theme.text_css(theme.TEXT_2, theme.FS_SMALL))
        sl.addWidget(self.selection_status)
        row = FlowLayout(spacing=6)
        self.selection_buttons = []
        for text, fn, tip in (("Isolate", self._isolate_current, "Show only the highlighted part or group (I)"),
                              ("Hide", self._hide_current, "Hide the highlighted part or group (H)"),
                              ("Show all", self.show_all, "Show every part again (Shift+H)")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
            if text != "Show all":
                b.setEnabled(False)
                self.selection_buttons.append(b)
        sl.addLayout(row)
        self.lessons_button = QPushButton("Related lessons")
        self.lessons_button.setAccessibleName("Browse authored lessons for this model")
        self.lessons_button.clicked.connect(lambda: self.lessonsRequested.emit(self.entry.id))
        self.lessons_button.hide()
        sl.addWidget(self.lessons_button)
        self._build_tree()
        self._filter_tree("")
        self.side = side
        return side

    def _parts_layout_changed(self, *_):
        if hasattr(self, "studio"):
            self.studio.arrange()

    def _build_tree(self):
        """Parts under plain categories (the model's guide, else its group keys' own "A / B" paths). A group of one
        part is that part's row; a larger group is a row of its parts. Top-level categories start open."""
        self._sync = True
        self.part_items = {}
        self.group_items = {}
        self.category_items = []
        self.family_rows = set()
        self.guide = load_part_guide(self.entry.id, set(getattr(self.content, "tissues", {}) or {}))
        self.flat_parts = (len(self.vmodel.groups) == 1 and
                           self.vmodel.groups[0].title.casefold() == "parts")
        categories = {}

        def checkable(row, title, tip=""):
            row.setText(0, title)
            row.setData(0, Qt.AccessibleTextRole, title)
            if tip:
                row.setToolTip(0, tip[:300])
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(0, Qt.Checked)
            return row

        def heading(row, title, role):
            checkable(row, title, title)
            f = row.font(0)
            f.setBold(True)
            row.setFont(0, f)
            row.setFlags(row.flags() | Qt.ItemIsAutoTristate)
            row.setData(0, ROLE, role)
            row.setExpanded(False)
            return row

        def category(path):
            if not path:
                return self.tree.invisibleRootItem()
            if path not in categories:
                row = heading(QTreeWidgetItem(category(path[:-1])), path[-1], ("category", path))
                row.setExpanded(len(path) == 1)
                categories[path] = row
                self.category_items.append(row)
            return categories[path]

        def part_row(parent, i, path=()):
            part = self.vmodel.items[i]
            name = part.name
            # "Source section / Renal fascia" under the Source section category reads as "Renal fascia"
            while " / " in name and name.split(" / ", 1)[0].casefold() in {p.casefold() for p in path}:
                name = name.split(" / ", 1)[1]
            row = checkable(QTreeWidgetItem(parent), name, self._part_description(part))
            row.setData(0, ROLE, ("part", i))
            self.part_items[i] = row

        rank = {key: n for n, key in enumerate(self.guide.order)}
        for g in sorted(self.vmodel.groups, key=lambda g: rank.get(g.key, len(rank))):
            if self.flat_parts:
                for i in g.items:
                    part_row(self.tree, i)
                continue
            path, title = self.guide.path(g.key, g.title)
            parent = category(path)
            if self.entry.id == "cardiac_muscle":
                # Repeated fibres, nuclei and connective tissue are one named
                # structure family in the UI, while retaining every mesh.
                gi = heading(QTreeWidgetItem(parent), title, ("group", g.key))
                gi.setFlags(gi.flags() & ~Qt.ItemIsAutoTristate)
                self.family_rows.add(g.key)
                self.group_items[g.key] = gi
                for i in g.items:
                    self.part_items[i] = gi
            elif len(g.items) == 1:
                part_row(parent, g.items[0], path)
            else:
                gi = heading(QTreeWidgetItem(parent), title, ("group", g.key))
                self.group_items[g.key] = gi
                for i in g.items:
                    part_row(gi, i, path)
        self._sync = False

    def _part_description(self, part):
        return self.guide.description(part)

    def _structure_name(self, part):
        """Where a part sits, for the Details crumb: its categories and its structure's title."""
        path, title = self.guide.path(part.group, part.group)
        return " › ".join([*path, title])

    def set_lessons_available(self, count):
        count = max(0, int(count))
        self.lessons_button.setText(f"Related lessons ({count})")
        self.lessons_button.setVisible(count > 0)

    def _filter_tree(self, text):
        terms = normalized(text).split()
        rows = [*self.category_items, *self.group_items.values()]
        if terms and self._filter_expanded is None:
            self._filter_expanded = {id(row) for row in rows if row.isExpanded()}

        def visit(row, context):
            """Show the rows matching every term (a part also matches by its group and categories); returns how
            many parts stay listed."""
            kind, val = row.data(0, ROLE)
            if kind == "part":
                part = self.vmodel.items[val]
                show = all(term in normalized(f"{part.name} {part.key} {context}") for term in terms)
                row.setHidden(not show)
                return int(show)
            label = f"{context} {val if kind == 'group' else ''} {row.text(0)}"
            if val in self.family_rows:
                sids = self._sids_of(row)
                searchable = normalized(label + " " + " ".join(self.vmodel.items[i].name for i in sids))
                show = all(term in searchable for term in terms)
                row.setHidden(not show)
                return len(sids) if show else 0
            shown = sum(visit(row.child(index), label) for index in range(row.childCount()))
            row.setHidden(not shown)
            if terms and shown:
                row.setExpanded(True)
            return shown

        root = self.tree.invisibleRootItem()
        matches = sum(visit(root.child(index), "") for index in range(root.childCount()))
        if not terms and self._filter_expanded is not None:
            for row in rows:
                row.setExpanded(id(row) in self._filter_expanded)
            self._filter_expanded = None
        self.parts_status.setText("Check to show or hide" if matches else
                                  "No matching parts. Clear the filter to see the full model.")
        self._parts_layout_changed()

    def _sids_of(self, item):
        kind, val = item.data(0, ROLE)
        if kind == "part":
            return [val]
        if kind == "group":
            g = next((g for g in self.vmodel.groups if g.key == val), None)
            return list(g.items) if g else []
        return [sid for index in range(item.childCount()) for sid in self._sids_of(item.child(index))]

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
        if self.click_hook is None:
            self.gl_widget.frame_structures(self._sids_of(item))

    def _item_activated(self, item, col):
        if self.click_hook is None:
            self.state.select(self._sids_of(item))
            self._item_double_clicked(item, col)

    def _sync_tree(self):
        vis = self.state.visible_mask()
        self._sync = True
        for sid, it in self.part_items.items():
            if it.data(0, ROLE)[0] == "part":      # not a structure family's shared row
                it.setCheckState(0, Qt.Checked if vis[sid] else Qt.Unchecked)
        for gi in [*self.group_items.values(), *self.category_items]:
            sids = self._sids_of(gi)
            n = int(vis[sids].sum()) if sids else 0
            gi.setCheckState(0, Qt.Checked if n == len(sids) else Qt.Unchecked if n == 0 else Qt.PartiallyChecked)
        self._sync = False
        self._update_selection_controls()

    def _update_selection_controls(self):
        selected = list(self.state.selected)
        family = self._selected_family(selected)
        label = (family if family else self.vmodel.items[selected[0]].name if len(selected) == 1 else
                 f"{len(selected)} parts selected" if selected else "No part selected")
        self.selection_status.setText(label if selected else "Select a structure to read its details.")
        for button in self.selection_buttons:
            button.setEnabled(bool(selected) and self.click_hook is None)
        if not selected:
            self.tree.clearSelection()
        else:
            current = self.tree.currentItem()
            if current is None or set(self._sids_of(current)) != set(selected):
                item = self.part_items.get(selected[0])
                if item is not None:
                    previous = self.tree.blockSignals(True)
                    self.tree.setCurrentItem(item)
                    self.tree.blockSignals(previous)

    def _current_or_selected(self):
        if self.state.selected:
            return list(self.state.selected)
        return []

    def _selected_family(self, selected):
        if self.entry.id != "cardiac_muscle" or not selected:
            return None
        groups = {self.vmodel.items[i].group for i in selected}
        return next(iter(groups)) if len(groups) == 1 else None

    def _selection_sids(self, sid):
        group = self.vmodel.group_of(sid)
        if self.entry.id == "cardiac_muscle" and group is not None:
            return list(group.items)
        return [sid]

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
            label = QLabel(text)
            label.setBuddy(widget)
            widget.setAccessibleName(text)
            hl.addWidget(label)
            hl.addWidget(widget)
            return box

        # the model's own stored views: named stage views as buttons, a camera set in a menu
        self.view_buttons = {}
        self.view_choice = None
        if self._view_names:
            named = all(len(n) > 3 for n in self._view_names)
            if named and len(self._view_names) <= 3 and all(len(n) <= 22 for n in self._view_names):
                for n in self._view_names:
                    b = QPushButton(n)
                    b.setCheckable(True)
                    rec = m.cameras[n]
                    b.setToolTip(rec.get("note", n) + "  (Page Down / Page Up step through the views)")
                    b.clicked.connect(lambda _=False, v=n: self.set_named_view(v))
                    bar.addWidget(b)
                    self.view_buttons[n] = b
            else:
                self.view_choice = QComboBox()
                self.view_choice.setAccessibleName("Stored model view")
                self.view_choice.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
                self.view_choice.setMinimumContentsLength(16)
                self.view_choice.addItem("Choose a stored view", None)
                for name in self._view_names:
                    self.view_choice.addItem(describe_view(name, m.cameras[name]), name)
                    self.view_choice.setItemData(self.view_choice.count() - 1,
                                                 m.cameras[name].get("note", name), Qt.ToolTipRole)
                self.view_choice.activated.connect(lambda index: self.set_named_view(self.view_choice.itemData(index))
                                                   if self.view_choice.itemData(index) is not None else None)
                bar.addWidget(labelled("View", self.view_choice))
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
        sec.setText("Section")
        sec.setToolTip(f"Sagittal, coronal and transverse cross-sections through the model ({key_text('Ctrl+Alt+1')}/2/3)")
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
        self.labels.setChecked(bool(getattr(getattr(self.entry, "micro", None), "labels_on_open", False)))
        bar.addWidget(self.labels)
        self.opacity = None
        if any(it.bulk for it in m.items):
            self.opacity = QSlider(Qt.Horizontal)
            self.opacity.setRange(8, 100)
            self.opacity.setFixedWidth(110)
            self.opacity.valueChanged.connect(self._opacity)
            # Apply the default to tissue layers before the first frame.
            self.opacity.setValue(100)
            self.opacity.setToolTip("All parts start fully opaque. This slider adjusts tissue layers.")
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
            more.setText("Related")
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
        b.setText("Display")
        b.setToolTip("Orientation axes, shadows, striations, lighting, exposure and projection of this view")
        b.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(b)
        rs = g.rsettings

        def toggle(text, attr, tip="", target=rs):
            a = menu.addAction(text)
            a.setCheckable(True)
            a.setChecked(bool(getattr(target, attr)))
            a.setToolTip(tip)
            a.toggled.connect(lambda on: (setattr(target, attr, on), g.update()))
            return a

        toggle("Shadows", "shadows", "Off when a model opens; enable for this view if wanted.")
        toggle("Orientation axes", "orientation_axes_on",
               "Show axes in the lower-left corner: X red, Y green, Z blue. "
               "Anatomically oriented models show L/R, S/I and A/P instead.", target=g)
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
        lay = FlowLayout(w, spacing=8)
        lay.setContentsMargins(10, 6, 10, 6)
        self.section_rows = []
        for i, name in enumerate(SECTION_NAMES):
            box = QWidget()
            hl = QHBoxLayout(box)
            hl.setContentsMargins(0, 0, 12, 0)
            hl.addWidget(QLabel(name))
            s = QSlider(Qt.Horizontal)
            s.setRange(0, 1000)
            s.setValue(500)
            s.setMinimumWidth(90)
            s.setMaximumWidth(150)
            s.setAccessibleName(f"{name} cross-section position")
            s.valueChanged.connect(lambda v, k=i: self._section_moved(k))
            hl.addWidget(s, 1)
            f = QCheckBox("Flip")
            f.setAccessibleName(f"Flip {name} cut direction")
            f.toggled.connect(lambda _on, k=i: self._section_moved(k))
            hl.addWidget(f)
            box.hide()
            lay.addWidget(box)
            self.section_rows.append((box, s, f))
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
        if hasattr(self, "studio"):
            if on:self.studio.show_card("section", True)
            self.studio.arrange()
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
        self.play = QPushButton("Play")
        self.play.setCheckable(True)
        self.play.setToolTip(f"Play the {(anim.title if anim else self.vmodel.clip.name).lower()} (Space)")
        self.play.toggled.connect(self._play_toggled)
        bar.addWidget(self.play)
        self.speed = QComboBox()
        self.speed.setAccessibleName("Animation playback speed")
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
        self.scrub.valueChanged.connect(self._scrubbed)
        bar.addWidget(labelled("Cycle" if kind == "procedural" else "Clip", self.scrub))
        self.phase_label = QLabel("")
        self.phase_label.setMinimumWidth(190)
        self.phase_label.setStyleSheet(f"color:{theme.SUCCESS};")
        bar.addWidget(self.phase_label)
        self._anim_changed(g.anim_fraction())

    def _play_toggled(self, on):
        self.play.setText("Pause" if on else "Play")
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
        self._fully_visible()

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
        choice = getattr(self, "view_choice", None)
        if choice is not None:
            choice.setCurrentIndex(max(0, choice.findData(name)))
            choice.setToolTip(choice.currentText())
        for n, b in self.view_buttons.items():
            b.setChecked(n == name)
        if "cut_on" in self.vmodel.cameras.get(name, {}):
            if self.cut is not None:
                previous = self.cut.blockSignals(True)
                self.cut.setChecked(self.gl_widget.cut_on)
                self.cut.blockSignals(previous)
            for k, section in enumerate(self.gl_widget.sections):
                self.set_section(k, section is not None)

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
        self.state.select(self._selection_sids(sid), add=bool(modifiers & Qt.ControlModifier))
        it = self.part_items.get(sid)
        if it:
            if it.isHidden():
                self.filter.clear()
            parent = it.parent()
            while parent is not None:          # every level above it, so the row can be seen
                parent.setExpanded(True)
                parent = parent.parent()
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
        sids = self._selection_sids(sid)
        self.state.select(sids)
        if action == "Isolate":
            self.state.isolate(sids)
        elif action == "X-ray focus":
            self.state.set_ghost_focus(sids)
        self.gl_widget.frame_structures(sids)
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

    def show_lesson_parts(self, names, *, view_name=None):
        """Reset a lesson step, then retain an authored view's camera and cover masks."""
        self._lesson_view_serial = getattr(self, "_lesson_view_serial", 0) + 1
        self.state.clear_selection()
        self._fully_visible()
        if view_name:
            if view_name not in self.vmodel.cameras:
                return [f"view '{view_name}'"]
            self.gl_widget.set_named_view(view_name, animate=False)
            sids, missing = self.part_ids(names)
            if sids:
                # A named view already exposes the subject. Selecting a chamber
                # must not restore its deliberately hidden anterior wall.
                self.state.select(sids)
                self.state.set_ghost_focus(sids)
            self._show_selection()
            return missing
        if not names:
            self.reset_view()
            return []
        if self.entry.id == "cardiac_muscle":
            # A selected cell family should not make the remaining tissue disappear
            # or zoom the lesson into one tiny junction.
            sids, missing = self.part_ids(names)
            self.reset_view()
            self.state.select(sids)
            self._show_selection()
            return missing
        return self.focus_parts(names)

    def focus_parts(self, names):
        """A lesson step's "micro_focus": select these parts, x-ray the rest, label and frame them.
        Returns the names that are not parts of this model."""
        sids, missing = self.part_ids(names)
        if sids:
            self.state.opaque_materials=False
            self.state.set_hidden(sids, False)
            self.state.select(sids)
            self.state.set_ghost_focus(sids)
            self._show_selection()
            # after reset_view, which a freshly opened model queues for its first frame
            serial = getattr(self, "_lesson_view_serial", 0)
            QTimer.singleShot(250, self, lambda: self.gl_widget.frame_structures(sids)
                              if serial == getattr(self, "_lesson_view_serial", 0) else None)
        return missing

    def set_practice(self, click=None, rclick=None):
        """Practice mode takes the clicks, and the parts list and labels are put away: they would give the answer."""
        on = click is not None
        self._lesson_view_serial = getattr(self, "_lesson_view_serial", 0) + 1
        if on and self.click_hook is None:
            camera = self.gl_widget.camera
            self._practice_restore = {
                "state": self.state._snapshot(), "selected": list(self.state.selected),
                "colors": dict(self.state.custom_colors), "undo": list(self.state._undo),
                "labels": self.labels.isChecked(), "side": not self.side.isHidden(),
                "camera": {key: getattr(camera, key).copy() if isinstance(getattr(camera, key), np.ndarray)
                           else getattr(camera, key)
                           for key in ("target", "distance", "yaw", "pitch", "fov", "ortho", "ortho_width")},
                "view": getattr(self, "_current_view", None),
            }
        self.click_hook, self.rclick_hook = click, rclick
        self.studio._practice = on
        self.side.setVisible(not on)
        self.gl_widget.names_hidden = (lambda: True) if on else (lambda: False)
        if on:
            self.labels.setChecked(False)
            self.show_all()
            self.state.clear_selection()
            self.reset_view()
        elif getattr(self, "_practice_restore", None) is not None:
            saved = self._practice_restore
            self._practice_restore = None
            self.state.custom_colors = saved["colors"]
            self.state.restore(saved["state"])
            self.state.select(saved["selected"])
            self.state._undo = saved["undo"]
            self.labels.setChecked(saved["labels"])
            self.side.setVisible(saved["side"])
            camera = self.gl_widget.camera
            camera._anim = None
            for key, value in saved["camera"].items():
                setattr(camera, key, value)
            self._view_changed(saved["view"])
            self.gl_widget.update()
        self.studio.set_practice(on)
        self.gl_widget.invalidate_labels()

    def _refresh_labels(self):
        self.gl_widget.invalidate_labels()

    def on_activated(self, info):
        self.info = info
        self._show_selection()

    def _notes_html(self, clinical, tissues):
        """Clinical notes and histology thumbnails, as Details shows them."""
        html_out = ""
        clinical = "".join(f"<p><b>{esc(t)}</b><br>{esc(x)}</p>" for t, x in dict.fromkeys(map(tuple, clinical)))
        if clinical:
            html_out += f"<p class='overline'>CLINICAL CORRELATIONS</p>{clinical}"
        hist = []
        for tid in dict.fromkeys(tissues):
            t = self.content.tissues.get(tid)
            if not t or not t.get("images"):
                continue
            thumbs = "".join(
                f'<td style="padding:2px"><a href="histo:{esc(tid)}|{i}"><img src="'
                f'{QUrl.fromLocalFile(str(self.content.thumb_path(img))).toString()}" width="96" height="72"></a></td>'
                for i, img in enumerate(t["images"][:3]))
            hist.append(f'<p><b><a href="histo:{esc(tid)}|0">{esc(t["name"])}</a></b></p>'
                        f'<table cellspacing="0" cellpadding="0"><tr>{thumbs}</tr></table>')
        if hist:
            html_out += "<p class='overline'>HISTOLOGY</p>" + "".join(hist)
        return html_out

    def _structure_notes(self, groups):
        """The clinical notes and tissues the part guide gives these structures, and nothing of the whole model's."""
        guides = [self.guide.group(key) for key in sorted(groups)]
        return self._notes_html([note for g in guides for note in g.clinical],
                                [tissue for g in guides for tissue in g.histology])

    def _show_selection(self):
        if hasattr(self, "selection_status"):
            self._update_selection_controls()
        self.gl_widget.invalidate_labels()
        if hasattr(self,"studio"):
            selected = list(self.state.selected)
            if self.click_hook is not None or not selected:self.studio.set_selection("")
            elif self._selected_family(selected):
                item=self.vmodel.items[selected[0]]
                self.studio.set_selection(self._selected_family(selected),self._part_description(item) or "Selected model structure")
            elif len(selected)==1:
                item=self.vmodel.items[selected[0]]
                self.studio.set_selection(item.name,self._part_description(item) or "Selected model structure")
            else:self.studio.set_selection(f"{len(selected)} parts selected", "Isolate these structures or open their details.")
        if not self.info or self.click_hook is not None:
            return
        sel = list(self.state.selected)
        e, m = self.entry, self.vmodel
        related = " · ".join(f'<a href="micro:{esc(r)}">{esc(self.content.micro_models[r].name)}</a>'
                             for r in e.related if r in self.content.micro_models and r != e.id)
        # The whole model's clinical notes and tissues belong to its overview. A selected structure shows only its
        # own (from the model's part guide), so the adrenal capsule of the kidney never reads about nephritis.
        tail = self._notes_html(e.clinical, e.histology)
        if related:
            tail += f"<p class='overline'>RELATED MODELS</p><p>{related}</p>"
        if e.credit_html:
            tail += f"<p class='muted'>{e.credit_html}</p>"
        overview = (f"<p class='overline'>THE WHOLE MODEL</p><p><a href=\"modeloverview:{esc(e.id)}\">About the "
                    f"{esc(e.name)} model</a> – its overview, clinical notes and histology.</p>")
        family = self._selected_family(sel)
        if family:
            descriptions = list(dict.fromkeys(self._part_description(m.items[i]) for i in sel
                                              if self._part_description(m.items[i])))
            description = descriptions[0] if descriptions else "No written description is included for this structure."
            notes = self._structure_notes({m.items[i].group for i in sel})
            body = (f"<div class='crumb'>{esc(e.name)} › {esc(family)}</div>"
                    f"<p class='summary'>{esc(description)}</p>{notes}{overview}")
            self.info.show_html(f"<h1>{esc(family)}</h1>", body)
        elif len(sel) == 1:
            it = m.items[sel[0]]
            g = m.group_of(it.index)
            siblings = [m.items[i].name for i in (g.items if g else []) if i != it.index]
            atlas = ""
            if it.atlas:
                atlas = (f"<p><a href=\"atlas:{esc('|'.join(it.atlas))}\">Show {esc(it.name.lower())} in the "
                         f"atlas</a></p>")
            desc = self._part_description(it) or "No written description is included for this part."
            size = ""
            if m.metres_per_unit and it.parts and not m.sidecar.get("mixed_schematic_scale"):
                b = m.item_bounds([it.index])
                if b is not None:
                    ext = sorted((b[1] - b[0]) * m.metres_per_unit, reverse=True)
                    size = f"<p class='muted'>About {self.gl_widget._format_length(ext[0])} across</p>"
            more = ""
            if siblings:
                shown = siblings[:24]
                extra = f" and {len(siblings) - len(shown)} more" if len(siblings) > len(shown) else ""
                more = (f"<p class='overline'>ALSO IN {esc(self.guide.path(it.group, it.group)[1].upper())}</p>"
                        f"<p class='muted'>{esc(' · '.join(shown))}{esc(extra)}</p>")
            body = (f"<div class='crumb'>{esc(e.name)} › {esc(self._structure_name(it))}</div>"
                    f"<p class='summary'>{esc(desc)}</p>{size}{atlas}{self._structure_notes({it.group})}{more}"
                    f"{overview}")
            self.info.show_html(f"<h1>{esc(it.name)}</h1>", body)
        elif len(sel) > 1:
            rows=[]
            for index in sel:
                item=m.items[index]
                href=QUrl('modelpart:'+e.id+'|'+str(index)).toString()
                description=self._part_description(item) or 'No written description is included for this part.'
                rows.append(f'<p><a href="{esc(href)}"><b>{esc(item.name)}</b></a><br>{esc(brief(description,320))}</p>')
            body=(f"<div class='crumb'>{esc(e.name)}</div>"
                  "<p class='summary'>Choose a part below to open its individual details.</p>"+''.join(rows)+overview)
            self.info.show_html(f"<h1>{len(sel)} selected parts</h1>",body)
        else:
            groups = []
            for gr in m.groups:
                if e.id == "cardiac_muscle":
                    groups.append(f"<p><b>{esc(gr.title)}</b></p>")
                    continue
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
