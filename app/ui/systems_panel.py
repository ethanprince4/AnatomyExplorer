import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSlider, QToolButton, QVBoxLayout, QWidget)

PRESETS = [
    ("Default", None),
    ("Skeleton", {"skeletal", "joints"}),
    ("Muscles", {"skeletal", "joints", "muscular"}),
    ("Attachments", {"skeletal", "attachments"}),
    ("Vessels", {"skeletal", "cardiovascular"}),
    ("Nerves", {"skeletal", "nervous"}),
    ("Organs", {"skeletal", "visceral", "lymphatic", "cardiovascular"}),
    ("Surface", {"regions"}),
]


def swatch(rgb):
    lab = QLabel()
    lab.setFixedSize(12, 12)
    c = QColor.fromRgbF(*rgb)
    lab.setStyleSheet(f"background:{c.name()}; border-radius:3px;")
    return lab


class SystemsPanel(QWidget):
    def __init__(self, ds, state, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.state = state
        self._sync = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(4)

        grid = QGridLayout()
        grid.setSpacing(5)
        for i, (name, keys) in enumerate(PRESETS):
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, k=keys: self._preset(k))
            grid.addWidget(b, i // 4, i % 4)
        lay.addLayout(grid)
        lay.addSpacing(6)

        counts = np.bincount(ds.system_of, minlength=len(ds.systems))
        sub_counts = np.bincount(ds.subsystem_of[ds.subsystem_of >= 0], minlength=len(ds.subsystems))
        self.sys_checks = []
        self.sub_checks = {}
        self.sliders = []
        for i, s in enumerate(ds.systems):
            row = QFrame()
            row.setStyleSheet("QFrame { background: #20252c; border-radius: 7px; }")
            rl = QVBoxLayout(row)
            rl.setContentsMargins(8, 6, 8, 6)
            rl.setSpacing(3)
            head = QHBoxLayout()
            head.setSpacing(6)
            exp = QToolButton()
            exp.setObjectName("expander")
            exp.setText("▸")
            exp.setFixedWidth(14)
            head.addWidget(exp)
            head.addWidget(swatch(s["color"]))
            cb = QCheckBox(s["name"].replace("&", "&&"))
            cb.setStyleSheet("font-weight:600;")
            cb.toggled.connect(lambda on, idx=i: self._sys_toggled(idx, on))
            head.addWidget(cb, 1)
            cnt = QLabel(str(counts[i]))
            cnt.setStyleSheet("color:#8a94a3; font-size:8.5pt;")
            head.addWidget(cnt)
            rl.addLayout(head)
            detail = QWidget()
            dl = QVBoxLayout(detail)
            dl.setContentsMargins(22, 2, 0, 2)
            dl.setSpacing(2)
            op = QHBoxLayout()
            ol = QLabel("Opacity")
            ol.setStyleSheet("color:#8a94a3; font-size:8.5pt;")
            op.addWidget(ol)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(5, 100)
            sl.setValue(100)
            sl.valueChanged.connect(lambda v, idx=i: self.state.set_system_alpha(idx, v / 100.0))
            op.addWidget(sl, 1)
            dl.addLayout(op)
            self.sliders.append(sl)
            for sub in s["subsystems"]:
                key = (s["key"], sub["name"])
                if key not in ds.subsystem_index:
                    continue
                sidx = ds.subsystem_index[key]
                scb = QCheckBox(f"{sub['name'].replace('&', '&&')}  ({sub_counts[sidx]})")
                scb.toggled.connect(lambda on, idx=sidx: self._sub_toggled(idx, on))
                dl.addWidget(scb)
                self.sub_checks[sidx] = scb
            detail.hide()
            rl.addWidget(detail)
            exp.clicked.connect(lambda _=False, d=detail, b=exp: (d.setVisible(not d.isVisible()),
                                                                  b.setText("▾" if d.isVisible() else "▸")))
            lay.addWidget(row)
            self.sys_checks.append(cb)
        lay.addStretch(1)
        state.visibility_changed.connect(self.sync)
        self.sync()

    def sync(self):
        self._sync = True
        for i, cb in enumerate(self.sys_checks):
            cb.setChecked(bool(self.state.system_on[i]))
        for sidx, cb in self.sub_checks.items():
            sys_idx = self.ds.subsystem_system[sidx]
            cb.setChecked(bool(self.state.system_on[sys_idx] and self.state.subsystem_on[sidx]))
        self._sync = False

    def _sys_toggled(self, idx, on):
        if not self._sync:
            self.state.set_system(idx, on)

    def _sub_toggled(self, idx, on):
        if not self._sync:
            self.state.set_subsystem(idx, on)

    def _preset(self, keys):
        if keys is None:
            self.state.reset_visibility()
            for sl in self.sliders:
                sl.setValue(100)
            return
        self.state.set_systems([s["key"] in keys for s in self.ds.systems])


class RegionsPanel(QWidget):
    def __init__(self, ds, state, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.state = state
        self._sync = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(6)
        tip = QLabel("Show only structures in the checked body regions.")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#8a94a3;")
        lay.addWidget(tip)
        btns = QHBoxLayout()
        for label, fn in (("All", lambda: self._set_all(True)), ("None", lambda: self._set_all(False)),
                          ("Left side", lambda: self._side("_l")), ("Right side", lambda: self._side("_r"))):
            b = QPushButton(label)
            b.clicked.connect(fn)
            btns.addWidget(b)
        lay.addLayout(btns)
        self.checks = []
        for i, r in enumerate(ds.regions):
            cb = QCheckBox(r["name"])
            cb.toggled.connect(lambda on, idx=i: (not self._sync) and self.state.set_region(idx, on))
            lay.addWidget(cb)
            self.checks.append(cb)
        lay.addStretch(1)
        state.visibility_changed.connect(self.sync)
        self.sync()

    def sync(self):
        self._sync = True
        for i, cb in enumerate(self.checks):
            cb.setChecked(bool(self.state.region_on[i]))
        self._sync = False

    def _set_all(self, on):
        self.state.set_regions([on] * len(self.ds.regions))

    def _side(self, suffix):
        other = "_r" if suffix == "_l" else "_l"
        self.state.set_regions([not r["key"].endswith(other) for r in self.ds.regions])
