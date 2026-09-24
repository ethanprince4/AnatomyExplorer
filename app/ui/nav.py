"""The Explore panel's page switcher.

Seven tabs do not fit across a 330-360 px side panel: a plain QTabBar scrolls them, so the first one reads "ions"
behind a pair of arrows. This keeps the QTabWidget (everything else talks to it: setCurrentIndex,
setCurrentWidget, currentChanged) but hides its bar and shows every page at once as a two-row grid of tabs
instead - finding what is in the body on the top row, the study material underneath.
"""
import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QPushButton, QSizePolicy, QTabWidget, QWidget

# which row each page goes on; anything unlisted joins the top row
STUDY_PAGES = ("Lessons", "Radiology", "Histology")


class NavTabWidget(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tabBar().hide()
        self.nav = QWidget()
        self.nav.setObjectName("exploreNav")
        self._grid = QGridLayout(self.nav)
        self._grid.setContentsMargins(10, 2, 10, 0)
        self._grid.setHorizontalSpacing(2)
        self._grid.setVerticalSpacing(0)
        self._group = QButtonGroup(self.nav)
        self._group.setExclusive(True)
        self._group.idClicked.connect(self.setCurrentIndex)
        self.currentChanged.connect(self._sync)

    # the nav lives outside the tab widget, so it has to follow it in and out of view
    def setVisible(self, visible):
        super().setVisible(visible)
        self.nav.setVisible(visible)

    def tabInserted(self, index):
        super().tabInserted(index)
        self._rebuild()

    def tabRemoved(self, index):
        super().tabRemoved(index)
        self._rebuild()

    def _rebuild(self):
        for b in self._group.buttons():
            self._group.removeButton(b)
            b.deleteLater()
        texts = [self.tabText(i) for i in range(self.count())]
        rows = [[i for i, t in enumerate(texts) if t not in STUDY_PAGES],
                [i for i, t in enumerate(texts) if t in STUDY_PAGES]]
        rows = [r for r in rows if r]
        # a common multiple of the row lengths, so every row spans the full width in equal cells
        cols = math.lcm(*(len(r) for r in rows)) if rows else 1
        for c in range(self._grid.columnCount()):
            self._grid.setColumnStretch(c, 0)
        for c in range(cols):
            self._grid.setColumnStretch(c, 1)
        for row, idxs in enumerate(rows):
            span = cols // len(idxs)
            for k, i in enumerate(idxs):
                b = QPushButton(texts[i])
                b.setObjectName("navTab")
                b.setCheckable(True)
                b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)   # equal cells, whatever the label
                b.setFocusPolicy(Qt.TabFocus)
                b.setToolTip(self.tabToolTip(i))
                self._group.addButton(b, i)
                self._grid.addWidget(b, row, k * span, 1, span)
        self._sync(self.currentIndex())

    def _sync(self, index):
        b = self._group.button(index)
        if b is not None:
            b.setChecked(True)
