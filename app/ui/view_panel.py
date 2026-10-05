from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget)

from . import theme

CLIP_NAMES = ["Sagittal (left / right)", "Coronal (front / back)", "Transverse (top / bottom)"]


def slider(lo, hi, value):
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


# Landmarks along the dissection, used by the Deeper / Shallower steps and shown under the slider.
DISSECTION_STOPS = [
    (0.00, "Skin surface"),
    (0.08, "Superficial fascia"),
    (0.16, "Deep fascia"),
    (0.26, "Superficial muscles"),
    (0.40, "Deep muscles"),
    (0.55, "Skeleton & joints"),
    (0.70, "Body cavities"),
    (0.85, "Deepest structures"),
]


class ViewPanel(QWidget):
    """Quick view controls. Everything else lives in the Settings dialog."""

    settingChanged = Signal(str, object)
    clipChanged = Signal()
    settingsRequested = Signal()
    depthChanged = Signal(float, float)
    sectionPicked = Signal(int)

    def __init__(self, settings, viewport, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.vp = viewport
        self._sync = False
        self.setMinimumWidth(240)
        self.setAccessibleName("Atlas view controls")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(10, 6, 10, 10)
        lay.setSpacing(8)

        g = QGroupBox("Quick settings")
        gl = QGridLayout(g)
        gl.addWidget(QLabel("Colors"), 0, 0)
        self.color_mode = QComboBox()
        self.color_mode.setAccessibleName("Atlas color mode")
        self.color_mode.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.color_mode.setMinimumContentsLength(10)
        self.color_mode.addItems(["Realistic", "Distinct segments", "By body system"])
        self.color_mode.currentIndexChanged.connect(lambda i: self._set("color_mode", i))
        gl.addWidget(self.color_mode, 0, 1)
        gl.addWidget(QLabel("X-ray opacity"), 1, 0)
        self.ghost = slider(2, 50, 10)
        self.ghost.setAccessibleName("X-ray opacity percent")
        self.ghost.setToolTip("Opacity of the anatomy around your selection")
        self.ghost.valueChanged.connect(lambda v: self._set("ghost_alpha", v / 100.0))
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self.ghost, 1)
        self.ghost_value = QLabel("10%")
        self.ghost.valueChanged.connect(lambda value: self.ghost_value.setText(f"{value}%"))
        opacity_row.addWidget(self.ghost_value)
        gl.addLayout(opacity_row, 1, 1)
        self.xray = QCheckBox("X-ray everything else when searching")
        self.xray.toggled.connect(lambda v: self._set("xray_on_search", v))
        gl.addWidget(self.xray, 2, 0, 1, 2)
        self.lm = QCheckBox("Landmark labels on selection")
        self.lm.toggled.connect(lambda v: self._set("show_landmarks", v))
        gl.addWidget(self.lm, 3, 0, 1, 2)
        self.dark = QCheckBox("Dark 3D background")
        self.dark.setToolTip("Changes the atlas background, independently of the app theme")
        self.dark.toggled.connect(lambda v: self._set("dark_background", v))
        gl.addWidget(self.dark, 4, 0, 1, 2)
        self.ssao = QCheckBox("Ambient occlusion")
        self.ssao.toggled.connect(lambda v: self._set("ssao", v))
        gl.addWidget(self.ssao, 5, 0, 1, 2)
        more = QPushButton("All settings, mouse && key bindings…")
        more.clicked.connect(self.settingsRequested.emit)
        gl.addWidget(more, 6, 0, 1, 2)
        lay.addWidget(g)

        g = QGroupBox("Dissection")
        dl = QVBoxLayout(g)
        blurb = QLabel("Peel the body apart from the skin inwards. Depth is measured as a fraction of how thick "
                       "the body is at each point, so the hand and the thigh are uncovered together.")
        blurb.setWordWrap(True)
        blurb.setStyleSheet(theme.text_css(theme.TEXT_2))
        dl.addWidget(blurb)
        self.depth_slider = slider(0, 1000, 0)
        self.depth_slider.setAccessibleName("Dissection depth")
        self.depth_slider.setToolTip("0 is intact; 1000 is the deepest dissection")
        self.depth_slider.setEnabled(False)
        self.depth_slider.valueChanged.connect(lambda _=0: self._depth())
        dl.addWidget(self.depth_slider)
        row = QHBoxLayout()
        self.depth_out = QPushButton("Shallower")
        self.depth_in = QPushButton("Deeper")
        self.depth_out.clicked.connect(lambda: self.step_depth(-1))
        self.depth_in.clicked.connect(lambda: self.step_depth(1))
        row.addWidget(self.depth_out)
        row.addWidget(self.depth_in)
        dl.addLayout(row)
        self.depth_band = QCheckBox("Show only this layer")
        self.depth_band.toggled.connect(lambda _=False: self._depth())
        dl.addWidget(self.depth_band)
        self.depth_label = QLabel("Preparing dissection depth…")
        self.depth_label.setWordWrap(True)
        dl.addWidget(self.depth_label)
        reset_d = QPushButton("Reset dissection")
        self.depth_reset = reset_d
        reset_d.clicked.connect(lambda: self.set_depth(0.0, False))
        dl.addWidget(reset_d)
        lay.addWidget(g)

        g = QGroupBox("Cross-section")
        cl = QVBoxLayout(g)
        bmin, bmax = viewport.scene_bounds()
        ranges = [(bmin[0], bmax[0]), (bmin[2], bmax[2]), (bmin[1], bmax[1])]
        self.clip_widgets = []
        for i, name in enumerate(CLIP_NAMES):
            row = QHBoxLayout()
            cb = QCheckBox(name)
            flip = QPushButton("Flip")
            flip.setCheckable(True)
            flip.setMinimumWidth(52)
            flip.setAccessibleName(f"Flip {name} cut direction")
            flip.setEnabled(False)
            flip.setStyleSheet("padding: 5px 0;")
            row.addWidget(cb, 1)
            row.addWidget(flip)
            cl.addLayout(row)
            lo, hi = ranges[i]
            sl = slider(0, 1000, 500)
            sl.setAccessibleName(f"{name} position")
            sl.setEnabled(False)
            cl.addWidget(sl)
            self.clip_widgets.append((cb, sl, flip, lo, hi))
            cb.toggled.connect(lambda _=False, idx=i: self._clip(idx))
            sl.valueChanged.connect(lambda _=0, idx=i: self._clip(idx))
            flip.toggled.connect(lambda _=False, idx=i: self._clip(idx))
        self.section_labels = QCheckBox("Label the cut face")
        self.section_labels.toggled.connect(lambda v: self._set("section_labels", v))
        cl.addWidget(self.section_labels)
        self.section_list = QListWidget()
        self.section_list.setMaximumHeight(190)
        self.section_list.setFixedHeight(48)
        self.section_list.setAccessibleName("Structures intersected by cross-section")
        self.section_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.section_list.setToolTip("Structures the section passes through, biggest first. Click one to select it.")
        self.section_list.itemClicked.connect(self._pick_section)
        self.section_list.itemActivated.connect(self._pick_section)
        cl.addWidget(self.section_list)
        reset = QPushButton("Reset cross-sections")
        reset.clicked.connect(self.reset_clips)
        cl.addWidget(reset)
        lay.addWidget(g)

        g = QGroupBox("Mouse && keys")
        hl = QVBoxLayout(g)
        self.help_text = QLabel()
        self.help_text.setWordWrap(True)
        self.help_text.setStyleSheet(theme.text_css(theme.TEXT_2))
        hl.addWidget(self.help_text)
        lay.addWidget(g)
        lay.addStretch(1)
        self.enable_depth(False)
        self.show_section([], None)
        self.sync_from_settings()

    def sync_from_settings(self):
        s = self.settings
        widgets = (self.color_mode, self.ghost, self.xray, self.lm, self.dark, self.ssao)
        for w in widgets:
            w.blockSignals(True)
        self.color_mode.setCurrentIndex(int(s["color_mode"]))
        self.ghost.setValue(int(round(float(s["ghost_alpha"]) * 100)))
        self.ghost_value.setText(f"{self.ghost.value()}%")
        self.xray.setChecked(bool(s["xray_on_search"]))
        self.section_labels.blockSignals(True)
        self.section_labels.setChecked(bool(s.get("section_labels", True)))
        self.section_labels.blockSignals(False)
        self.lm.setChecked(bool(s["show_landmarks"]))
        self.dark.setChecked(bool(s["dark_background"]))
        self.ssao.setChecked(bool(s["ssao"]))
        for w in widgets:
            w.blockSignals(False)
        self.help_text.setText(
            f"<b>{s['orbit_button']}-drag</b> rotate · <b>{s['pan_button']}-drag</b> or <b>Shift+drag</b> pan · "
            "<b>Wheel</b> zoom<br><b>Click</b> select · <b>Ctrl+click</b> multi-select · "
            f"<b>Double-click</b> {s['double_click_action'].lower()} · <b>Right-click</b> menu · "
            "<b>Mouse back/forward</b> history<br>Every shortcut can be changed in Settings → Keyboard.")

    def show_section(self, items, ds):
        """Fill the list of structures the active cross-section passes through."""
        self.section_list.clear()
        self.section_list.setFixedHeight(min(190,max(48,len(items)*(self.section_list.fontMetrics().height()+10)+8)))
        for sid, _anchor, weight in items:
            s = ds.structures[sid]
            name = s["name"] + (f"  ({s['side'].lower()})" if s["side"] else "")
            it = QListWidgetItem(name)
            it.setData(Qt.UserRole, sid)
            it.setToolTip(name)
            self.section_list.addItem(it)
        if not items:
            active = any(cb.isChecked() for cb, *_ in self.clip_widgets)
            message = ("No visible structures at this cut. Move the section or show more anatomy." if active else
                       "Enable a cross-section to see the structures it intersects.")
            placeholder = QListWidgetItem(message)
            placeholder.setFlags(Qt.NoItemFlags)
            placeholder.setToolTip(message)
            self.section_list.addItem(placeholder)

    def _pick_section(self, item):
        sid = item.data(Qt.UserRole)
        if sid is not None:
            self.sectionPicked.emit(int(sid))

    # ------------------------------------------------------------------ dissection
    def enable_depth(self, on=True):
        for widget in (self.depth_slider, self.depth_out, self.depth_in, self.depth_band, self.depth_reset):
            widget.setEnabled(on)
        self._depth_text()

    def _depth(self):
        cut = self.depth_slider.value() / 1000.0
        band = 0.13 if self.depth_band.isChecked() else 0.0
        self._depth_text()
        self.depthChanged.emit(cut, band)

    def _depth_text(self):
        cut = self.depth_slider.value() / 1000.0
        name = DISSECTION_STOPS[0][1]
        for level, label in DISSECTION_STOPS:
            if cut >= level - 1e-6:
                name = label
        if not self.depth_slider.isEnabled():
            self.depth_label.setText("Dissection depth is preparing or unavailable. Other view controls remain available.")
        elif cut <= 0.0:
            self.depth_label.setText("Intact – nothing removed yet.")
        else:
            self.depth_label.setText(f"<b>{cut * 100:.0f}%</b> deep · about the level of the <b>{name.lower()}</b>")

    def set_depth(self, cut, band=None):
        self.depth_slider.blockSignals(True)
        self.depth_slider.setValue(int(round(max(0.0, min(1.0, cut)) * 1000)))
        self.depth_slider.blockSignals(False)
        if band is not None:
            self.depth_band.blockSignals(True)
            self.depth_band.setChecked(bool(band))
            self.depth_band.blockSignals(False)
        self._depth()

    def step_depth(self, direction):
        """Jump to the next landmark along the dissection rather than nudging the slider."""
        cut = self.depth_slider.value() / 1000.0
        levels = [lv for lv, _ in DISSECTION_STOPS]
        if direction > 0:
            nxt = next((lv for lv in levels if lv > cut + 1e-4), min(1.0, cut + 0.1))
        else:
            nxt = next((lv for lv in reversed(levels) if lv < cut - 1e-4), 0.0)
        self.set_depth(nxt)

    def _set(self, key, value):
        self.settings[key] = value
        self.settingChanged.emit(key, value)

    def _clip(self, idx):
        cb, sl, flip, lo, hi = self.clip_widgets[idx]
        sl.setEnabled(cb.isChecked())
        flip.setEnabled(cb.isChecked())
        if cb.isChecked() != self.vp.clip_on[idx] or flip.isChecked() != self.vp.clip_flip[idx]:
            self.vp.set_radiology_slice(False)
        self.vp.clip_on[idx] = cb.isChecked()
        self.vp.clip_pos[idx] = lo + (hi - lo) * sl.value() / 1000.0
        self.vp.clip_flip[idx] = flip.isChecked()
        self.clipChanged.emit()

    def set_clip(self, idx, on, fraction=None, flipped=None):
        cb, sl, flip, lo, hi = self.clip_widgets[idx]
        for w in (cb, sl, flip):
            w.blockSignals(True)
        cb.setChecked(on)
        if fraction is not None:
            sl.setValue(round(fraction * 1000))
        if flipped is not None:
            flip.setChecked(flipped)
        for w in (cb, sl, flip):
            w.blockSignals(False)
        self._clip(idx)

    def set_clips(self, on, positions, flips):
        for i, (cb, sl, flip, lo, hi) in enumerate(self.clip_widgets):
            frac = (positions[i] - lo) / (hi - lo) if hi > lo else 0.5
            self.set_clip(i, bool(on[i]), max(0.0, min(1.0, frac)), bool(flips[i]))

    def reset_clips(self):
        self.vp.set_radiology_slice(False)
        for i in range(3):
            self.set_clip(i, False, 0.5, False)

    def toggle_clip(self, idx):
        self.vp.set_radiology_slice(False)
        self.set_clip(idx, not self.clip_widgets[idx][0].isChecked())
