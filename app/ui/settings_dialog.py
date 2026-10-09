from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QHBoxLayout, QHeaderView, QKeySequenceEdit, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSlider, QTableWidget, QTabWidget, QVBoxLayout, QWidget)

from ..actions import ACTION_DEFS, SELECT_MODIFIER, WORKSPACE_MODIFIER, key_text
from ..config import DEFAULT_SETTINGS
from . import theme


class SliderRow(QWidget):
    valueChanged = Signal(float)

    def __init__(self, lo, hi, value, step=0.05, suffix="", decimals=2, parent=None):
        super().__init__(parent)
        self.lo, self.step = lo, step
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, round((hi - lo) / step))
        self.spin = QDoubleSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setSingleStep(step)
        self.spin.setDecimals(decimals)
        self.spin.setSuffix(suffix)
        self.spin.setFixedWidth(84)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin)
        self.set_value(value)
        self.slider.valueChanged.connect(lambda v: self._from_slider(v))
        self.spin.valueChanged.connect(self._from_spin)

    def set_value(self, v):
        self.slider.blockSignals(True)
        self.spin.blockSignals(True)
        self.slider.setValue(round((v - self.lo) / self.step))
        self.spin.setValue(v)
        self.slider.blockSignals(False)
        self.spin.blockSignals(False)

    def _from_slider(self, v):
        val = self.lo + v * self.step
        self.spin.blockSignals(True)
        self.spin.setValue(val)
        self.spin.blockSignals(False)
        self.valueChanged.emit(val)

    def _from_spin(self, val):
        self.slider.blockSignals(True)
        self.slider.setValue(round((val - self.lo) / self.step))
        self.slider.blockSignals(False)
        self.valueChanged.emit(val)


class ColorButton(QPushButton):
    colorChanged = Signal(str)

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self.setFixedWidth(84)
        self.set_color(color)
        self.clicked.connect(self._pick)

    def set_color(self, color):
        self.color = color
        self.setStyleSheet(f"background:{color}; border:1px solid {theme.BORDER_STRONG}; border-radius:{theme.R_MD}px;"
                           f" min-height:20px;")

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.color), self, "Choose color")
        if c.isValid():
            self.set_color(c.name())
            self.colorChanged.emit(c.name())


class SettingsDialog(QDialog):
    settingChanged = Signal(str, object)
    themeChanged = Signal(str)

    def __init__(self, settings, actions, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(840, 640)
        self.setMinimumSize(540, 420)
        self.setAccessibleName("Anatomy Explorer settings")
        self.settings = settings
        self.registry = actions
        self.widgets = {}
        lay = QVBoxLayout(self)
        title = QLabel("Settings")
        title.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_H2, 600))
        lay.addWidget(title)
        hint = QLabel("Changes take effect immediately, except interface appearance. Your study content stays unchanged.")
        hint.setWordWrap(True)
        hint.setStyleSheet(theme.text_css(theme.MUTED))
        lay.addWidget(hint)
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("Settings categories")
        lay.addWidget(self.tabs)
        self.tabs.addTab(self._mouse_page(), "Mouse && Camera")
        self.tabs.addTab(self._display_page(), "Display")
        self.tabs.addTab(self._behavior_page(), "Behavior")
        self.tabs.addTab(self._keys_page(), "Keyboard")
        bottom = QHBoxLayout()
        reset = QPushButton("Reset this page")
        reset.clicked.connect(self._reset_page)
        bottom.addWidget(reset)
        bottom.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.close)
        bottom.addWidget(box)
        lay.addLayout(bottom)

    # ------------------------------------------------------------------ helpers
    def _page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setContentsMargins(16, 16, 16, 16)
        scroll.setWidget(body)
        scroll._keys = []
        return scroll, form

    def _emit(self, key, value):
        self.settings[key] = value
        self.settingChanged.emit(key, value)

    def _slider(self, page, form, key, label, lo, hi, step, suffix="", decimals=2, tip=None):
        w = SliderRow(lo, hi, float(self.settings[key]), step, suffix, decimals)
        w.setAccessibleName(label)
        w.slider.setAccessibleName(label)
        w.spin.setAccessibleName(label + " value")
        w.valueChanged.connect(lambda v, k=key: self._emit(k, v))
        if tip:
            w.setToolTip(tip)
        form.addRow(label, w)
        self.widgets[key] = w
        page._keys.append(key)

    def _check(self, page, form, key, label, tip=None):
        w = QCheckBox(label)
        w.setAccessibleName(label)
        w.setChecked(bool(self.settings[key]))
        w.toggled.connect(lambda v, k=key: self._emit(k, v))
        if tip:
            w.setToolTip(tip)
        form.addRow("", w)
        self.widgets[key] = w
        page._keys.append(key)

    def _combo(self, page, form, key, label, options, tip=None):
        w = QComboBox()
        w.setAccessibleName(label)
        w.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        w.setMinimumContentsLength(14)
        w.addItems(options)
        w.setCurrentText(str(self.settings[key]))
        w.currentTextChanged.connect(lambda v, k=key: self._emit(k, v))
        if tip:
            w.setToolTip(tip)
        form.addRow(label, w)
        self.widgets[key] = w
        page._keys.append(key)

    def _color(self, page, form, key, label):
        w = ColorButton(self.settings[key])
        w.setAccessibleName(label)
        w.setToolTip(label + ": " + str(self.settings[key]))
        w.colorChanged.connect(lambda v, k=key: self._emit(k, v))
        form.addRow(label, w)
        self.widgets[key] = w
        page._keys.append(key)

    def _header(self, form, text):
        lab = QLabel(text.capitalize())
        lab.setStyleSheet(theme.overline_css(theme.ACCENT_TEXT) + " margin-top:12px;")
        form.addRow(lab)

    # ------------------------------------------------------------------ pages
    def _mouse_page(self):
        page, f = self._page()
        self._header(f, "MOUSE")
        self._slider(page, f, "orbit_sensitivity", "Rotate sensitivity", 0.05, 1.5, 0.05)
        self._slider(page, f, "pan_sensitivity", "Pan sensitivity", 0.2, 3.0, 0.1)
        self._slider(page, f, "zoom_sensitivity", "Zoom sensitivity", 0.2, 3.0, 0.1)
        self._combo(page, f, "orbit_button", "Rotate with", ["Left", "Right", "Middle"])
        self._combo(page, f, "pan_button", "Pan with", ["Right", "Middle", "Left"])
        hint = QLabel(f"Shift + rotate button always pans. {SELECT_MODIFIER} + left-click adds to the selection.")
        hint.setStyleSheet(theme.text_css(theme.MUTED))
        f.addRow("", hint)
        self._check(page, f, "invert_orbit_x", "Invert horizontal rotation")
        self._check(page, f, "invert_orbit_y", "Invert vertical rotation")
        self._check(page, f, "invert_zoom", "Invert scroll-wheel zoom")
        self._check(page, f, "zoom_to_cursor", "Zoom toward the point under the cursor")
        self._check(page, f, "orbit_around_cursor", "Rotate around the point under the cursor",
                    tip="When you start dragging on a structure, the camera pivots around that point.")
        self._header(f, "TRACKPAD")
        self._combo(page, f, "trackpad_mode", "Scrolling comes from", ["Auto", "Mouse", "Trackpad"],
                    tip="Auto tells a laptop trackpad from a mouse wheel by the events it sends. If a smooth-scrolling "
                        "mouse wheel turns the model instead of zooming, choose Mouse; if trackpad swipes zoom, "
                        "choose Trackpad.")
        self._combo(page, f, "trackpad_swipe", "Two-finger swipe", ["Orbit", "Pan"])
        self._slider(page, f, "trackpad_swipe_sensitivity", "Swipe sensitivity", 0.2, 3.0, 0.1)
        self._slider(page, f, "trackpad_pinch_sensitivity", "Pinch sensitivity", 0.2, 3.0, 0.1)
        self._check(page, f, "trackpad_invert", "Invert swipe direction")
        hint = QLabel("Pinch zooms, Shift + swipe does the other of orbit / pan, click-drag rotates like a mouse. "
                      "On a Mac: twist two fingers to turn the model, double-tap with two fingers to frame the "
                      "selection.")
        hint.setWordWrap(True)
        hint.setStyleSheet(theme.text_css(theme.MUTED))
        f.addRow("", hint)
        self._header(f, "CAMERA")
        self._slider(page, f, "fov", "Field of view", 15, 70, 1, "°", 0)
        self._slider(page, f, "camera_duration", "Transition duration", 0.0, 1.5, 0.05, " s")
        self._slider(page, f, "key_orbit_step", "Keyboard rotate step", 1, 45, 1, "°", 0)
        self._slider(page, f, "auto_rotate_speed", "Auto-rotate speed", 2, 90, 1, "°/s", 0)
        return page

    def _display_page(self):
        page, f = self._page()
        self._header(f, "INTERFACE")
        self.theme_picker = QComboBox()
        self.theme_picker.setAccessibleName("Interface appearance for next launch")
        for key, label in theme.THEMES.items():
            self.theme_picker.addItem(label, key)
        saved_theme = (str(self.parent().qsettings.value("ui_theme", theme.THEME_NAME))
                       if self.parent() is not None and hasattr(self.parent(), "qsettings") else theme.THEME_NAME)
        self.theme_picker.setCurrentIndex(max(0, self.theme_picker.findData(saved_theme)))
        self.theme_picker.currentIndexChanged.connect(
            lambda _index: self.themeChanged.emit(self.theme_picker.currentData()))
        self.theme_picker.hide()  # Study-02 Porcelain is the single approved appearance.
        appearance_hint = QLabel("Study-02 Porcelain. Educational images and model materials keep their original colours.")
        appearance_hint.setWordWrap(True)
        appearance_hint.setStyleSheet(theme.text_css(theme.MUTED))
        f.addRow("", appearance_hint)
        self._slider(page, f, "ui_scale", "Interface text size", 0.8, 1.6, 0.05)
        self._slider(page, f, "details_scale", "Details text size", 0.8, 1.8, 0.05)
        self._slider(page, f, "label_size", "3D label size", 6, 16, 0.2, " pt", 1)
        self._slider(page, f, "max_landmarks", "Max landmark labels", 5, 150, 5, "", 0)
        self._check(page, f, "show_hover_tooltip", "Show name tooltip when hovering")
        self._check(page, f, "hover_outline", "Outline structure under the cursor")
        self._check(page, f, "show_gizmo", "Orientation gizmo")
        self._check(page, f, "show_status_bar", "Show bottom status bar")
        self._check(page, f, "show_perf", "Show rendering time in status bar")
        self._header(f, "RENDERING")
        self._slider(page, f, "render_scale", "Render resolution", 0.5, 2.0, 0.05,
                     tip="Above 1.0 supersamples for sharper edges; below 1.0 is faster.")
        self._check(page, f, "fast_renderer", "Fast renderer for models (new)",
                    tip="A faster 3D renderer for the model library (Metal on a Mac). Applies to models opened after "
                        "the change. If it cannot start, the standard renderer is used.")
        self._check(page, f, "fxaa", "Anti-aliasing")
        self._check(page, f, "ssao", "Ambient occlusion")
        self._slider(page, f, "ssao_strength", "Ambient occlusion strength", 0.0, 1.5, 0.05)
        self._slider(page, f, "ghost_alpha", "X-ray opacity", 0.02, 0.5, 0.01)
        self._header(f, "COLORS")
        self._check(page, f, "dark_background", "Dark background")
        self._check(page, f, "custom_background", "Use custom background colors")
        self._color(page, f, "bg_top", "Background top")
        self._color(page, f, "bg_bottom", "Background bottom")
        self._color(page, f, "selection_color", "Selection highlight")
        self._color(page, f, "hover_color", "Hover highlight")
        return page

    def _behavior_page(self):
        page, f = self._page()
        self._header(f, "SELECTION")
        self._combo(page, f, "click_action", "Single click", ["Select", "Select and focus"])
        self._combo(page, f, "double_click_action", "Double click", ["Focus", "Isolate", "X-ray focus"])
        self._check(page, f, "select_both_sides", "Clicking a paired structure selects both sides")
        self._check(page, f, "xray_on_search", "X-ray everything else when opening a search result")
        self._check(page, f, "show_landmarks", "Show landmark labels on the selection")
        self._header(f, "SESSION")
        self._check(page, f, "restore_session", "Restore camera, visibility and selection on startup")
        return page

    def _keys_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        top = QHBoxLayout()
        self.key_filter = QLineEdit()
        self.key_filter.setPlaceholderText("Filter commands…")
        self.key_filter.setAccessibleName("Filter keyboard commands")
        self.key_filter.setClearButtonEnabled(True)
        self.key_filter.textChanged.connect(self._filter_keys)
        top.addWidget(self.key_filter, 1)
        reset_all = QPushButton("Reset all shortcuts")
        reset_all.clicked.connect(self._reset_keys)
        top.addWidget(reset_all)
        lay.addLayout(top)
        self.conflict = QLabel("")
        self.conflict.setWordWrap(True)
        self.conflict.setAccessibleName("Keyboard shortcut conflicts")
        self.conflict.setStyleSheet(theme.text_css(theme.DANGER))
        lay.addWidget(self.conflict)
        self.table = QTableWidget(len(ACTION_DEFS), 5)
        self.table.setAccessibleName("Customizable keyboard shortcuts")
        self.table.setHorizontalHeaderLabels(["Command", "Category", "Shortcut", "Alternate", ""])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3, 4):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.key_edits = {}
        for r, d in enumerate(ACTION_DEFS):
            aid = d[0]
            self.table.setCellWidget(r, 0, QLabel("  " + d[1]))
            cat = QLabel(d[2] + ("  (3D view)" if d[5] else ""))
            cat.setStyleSheet(theme.text_css(theme.MUTED) + " padding: 0 8px;")
            self.table.setCellWidget(r, 1, cat)
            p, s = self.registry.shortcuts(aid)
            ep, es = QKeySequenceEdit(QKeySequence(p)), QKeySequenceEdit(QKeySequence(s))
            ep.setAccessibleName(d[1] + " primary shortcut")
            es.setAccessibleName(d[1] + " alternate shortcut")
            for e in (ep, es):
                e.setMaximumSequenceLength(1)
                e.setMinimumWidth(130)
                e.editingFinished.connect(lambda a=aid: self._key_changed(a))
            self.table.setCellWidget(r, 2, ep)
            self.table.setCellWidget(r, 3, es)
            b = QPushButton("Default")
            b.clicked.connect(lambda _=False, a=aid: self._key_default(a))
            self.table.setCellWidget(r, 4, b)
            self.key_edits[aid] = (ep, es, r)
        self.table.resizeRowsToContents()
        lay.addWidget(self.table, 1)
        tip = QLabel("Click a shortcut cell and press the new key combination. Press Backspace then click away to clear.")
        tip.setStyleSheet(theme.text_css(theme.MUTED))
        tip.setWordWrap(True)
        lay.addWidget(tip)
        names = ("Anatomy", "Models", "Lessons", "Radiology", "Histology")
        shell_keys = QLabel("Workspace shortcuts: " + " · ".join(
            f"{key_text(WORKSPACE_MODIFIER + str(n))} {name}" for n, name in enumerate(names, 1))
            + f" · {key_text('Ctrl+Shift+P')} Commands")
        shell_keys.setWordWrap(True)
        shell_keys.setStyleSheet(theme.text_css(theme.MUTED))
        lay.addWidget(shell_keys)
        self._check_conflicts()
        return w

    # ------------------------------------------------------------------ keyboard logic
    def _key_changed(self, aid):
        ep, es, _ = self.key_edits[aid]
        p = ep.keySequence().toString(QKeySequence.PortableText)
        s = es.keySequence().toString(QKeySequence.PortableText)
        self.registry.set_shortcuts(aid, p, s)
        self._check_conflicts()

    def _key_default(self, aid):
        d = self.registry.defs[aid]
        ep, es, _ = self.key_edits[aid]
        ep.setKeySequence(QKeySequence(d[3]))
        es.setKeySequence(QKeySequence(d[4]))
        self.registry.set_shortcuts(aid, d[3], d[4])
        self._check_conflicts()

    def _reset_keys(self):
        self.registry.reset_all()
        for aid, (ep, es, _) in self.key_edits.items():
            p, s = self.registry.shortcuts(aid)
            ep.setKeySequence(QKeySequence(p))
            es.setKeySequence(QKeySequence(s))
        self._check_conflicts()

    def _check_conflicts(self):
        seen = {}
        conflicts = []
        reserved = {action.shortcut().toString(): action.text()
                    for action in getattr(self.parent(), "workspace_actions", []) if not action.shortcut().isEmpty()}
        for aid, (ep, es, _) in self.key_edits.items():
            for e in (ep, es):
                k = e.keySequence().toString(QKeySequence.PortableText)
                if not k:
                    continue
                if k in reserved:
                    conflicts.append(f"{k}: {reserved[k]} / {self.registry.defs[aid][1]}")
                if k in seen and seen[k] != aid:
                    conflicts.append(f"{k}: {self.registry.defs[seen[k]][1]} / {self.registry.defs[aid][1]}")
                seen.setdefault(k, aid)
        self.conflict.setText(("Conflicting shortcuts — " + "; ".join(conflicts)) if conflicts else "")

    def _filter_keys(self, text):
        t = text.lower()
        for aid, (ep, es, r) in self.key_edits.items():
            d = self.registry.defs[aid]
            self.table.setRowHidden(r, bool(t) and t not in d[1].lower() and t not in d[2].lower())

    # ------------------------------------------------------------------ reset
    def _reset_page(self):
        page = self.tabs.currentWidget()
        if not hasattr(page, "_keys"):
            self._reset_keys()
            return
        if page is self.tabs.widget(1):
            self.theme_picker.setCurrentIndex(self.theme_picker.findData("porcelain"))
        for key in page._keys:
            v = DEFAULT_SETTINGS[key]
            w = self.widgets[key]
            if isinstance(w, SliderRow):
                w.set_value(float(v))
            elif isinstance(w, QCheckBox):
                w.blockSignals(True)
                w.setChecked(bool(v))
                w.blockSignals(False)
            elif isinstance(w, QComboBox):
                w.blockSignals(True)
                w.setCurrentText(str(v))
                w.blockSignals(False)
            elif isinstance(w, ColorButton):
                w.set_color(v)
            self._emit(key, v)
