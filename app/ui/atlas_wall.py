"""Flat, live systems and selection lettering for the Specimen atlas wall."""
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from . import theme


class AtlasWall(QWidget):
    def __init__(self, window):
        super().__init__(window.workspace)
        self.owner = window
        self.setObjectName("atlasWall")
        self.setStyleSheet("QWidget#atlasWall, QWidget#atlasWall QWidget {background:transparent;border:none;}"
                          "QWidget#atlasWall QPushButton {background:transparent;border:none;text-align:left;padding:5px 0px;}"
                          "QWidget#atlasWall QPushButton:hover {text-decoration:underline;}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        heading = QLabel("Systems")
        heading.setStyleSheet(theme.text_css(theme.TEXT_2, theme.FS_SMALL, 600))
        layout.addWidget(heading)
        counts = np.bincount(window.ds.system_of, minlength=len(window.ds.systems))
        self.checks = []
        for index, system in enumerate(window.ds.systems):
            if system["key"] in ("attachments", "reference"):
                continue
            row = QHBoxLayout()
            label = "Surface landmarks" if system["key"] == "regions" else system["name"]
            check = QCheckBox(label.replace("&", "&&"))
            check.setAccessibleName("Show " + label)
            check.toggled.connect(lambda on, i=index: window.state.set_system(i, on))
            row.addWidget(check, 1)
            count = QLabel(str(int(counts[index])))
            count.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
            row.addWidget(count)
            layout.addLayout(row)
            self.checks.append((index, check))
        layout.addSpacing(17)
        quick = QLabel("Quick views")
        quick.setStyleSheet(theme.text_css(theme.TEXT_2, theme.FS_SMALL, 600))
        layout.addWidget(quick)
        from .systems_panel import PRESETS
        for start in (0, 4):
            row = QHBoxLayout()
            for name, keys in PRESETS[start:start + 4]:
                if name in ("Attachments", "Surface"):
                    continue
                button = QPushButton(name)
                button.clicked.connect(lambda _=False, k=keys: window.systems._preset(k))
                row.addWidget(button)
            layout.addLayout(row)
        layout.addStretch(1)
        self.selection = QWidget()
        selected = QVBoxLayout(self.selection)
        selected.setContentsMargins(0, 0, 0, 0)
        self.name = QLabel()
        self.name.setWordWrap(True)
        self.name.setFont(theme.font_for("display", size=23))
        self.meta = QLabel()
        self.meta.setWordWrap(True)
        self.meta.setStyleSheet(theme.text_css(theme.TEXT_2))
        selected.addWidget(self.name)
        selected.addWidget(self.meta)
        actions = QHBoxLayout()
        for title, key in (("Isolate", "isolate"), ("Hide", "hide"), ("X-ray", "xray")):
            action = window.cmds.actions.get(key)
            if action is not None:
                button = QPushButton(title)
                button.clicked.connect(lambda _=False, a=action: a.trigger())
                actions.addWidget(button)
        more = QPushButton("Full entry ›")
        more.clicked.connect(window.right_dock.show)
        actions.addWidget(more)
        selected.addLayout(actions)
        layout.addWidget(self.selection)
        window.state.visibility_changed.connect(self.sync)
        window.state.selection_changed.connect(self.sync)
        self.sync()

    def sync(self):
        window = self.owner
        for index, check in self.checks:
            check.blockSignals(True)
            check.setChecked(bool(window.state.system_on[index]))
            check.blockSignals(False)
        chosen = list(window.state.selected)
        self.selection.setVisible(bool(chosen))
        if chosen:
            structure = window.ds.structures[int(chosen[0])]
            self.name.setText(structure["base"] if len(chosen) == 1 else f"{len(chosen)} selected structures")
            self.meta.setText(" · ".join(str(structure.get(key)) for key in ("latin", "side", "subsystem")
                                        if structure.get(key)))
