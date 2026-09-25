"""The Explore panel's page switcher: three top-level tabs, each with a small segmented selector.

The panel holds seven or more pages, far too many for a 330-360 px wide tab bar. This keeps the QTabWidget
(everything else talks to it: setCurrentIndex, setCurrentWidget, currentChanged, and the `tab:N` script command
counts pages in the order they were added) but hides its bar and groups the pages instead:

    Browse   Systems | Regions | Tree                     what is in the body
    Study    Lab course | Lessons | Radiology | Histology  the study material
    View     (one page, no selector)

Which group a page joins, and where it sits in its selector, comes from GROUPS below and the page's tab text -
not from the order it was added - so adding a page is one line in main_window.py:

    self.tabs.addTab(course_panel, "Lab course")

Add it after the existing pages so the `tab:N` indices of the others do not move. A page whose title is not in
GROUPS gets a group of its own. An entry in ALIASES stands in for a page that does not exist yet: "Lab course"
opens the Lessons page until a real page with that title is added, at which point the alias steps aside.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QSizePolicy, QTabWidget, QVBoxLayout, QWidget

GROUPS = [
    ("Browse", ("Systems", "Regions", "Tree")),
    ("Study", ("Lab course", "Lessons", "Radiology", "Histology")),
    ("View", ("View",)),
]
# selector entry -> the page it opens while no page of its own name exists
ALIASES = {"Lab course": "Lessons"}
TIPS = {
    "Browse": "Choose what is shown: body systems, regions, or the full anatomical tree",
    "Study": "Lab course, guided lessons, radiology cases and histology",
    "View": "Colours, x-ray, cross-sections and dissection",
}


class NavTabWidget(QTabWidget):
    # the selector entry the user picked (e.g. "Lab course"), for pages that show differently per entry
    entry_picked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tabBar().hide()
        self.nav = QWidget()
        self.nav.setObjectName("exploreNav")
        lay = QVBoxLayout(self.nav)
        lay.setContentsMargins(10, 2, 10, 6)
        lay.setSpacing(4)
        self._top_row = QHBoxLayout()
        self._top_row.setSpacing(0)
        lay.addLayout(self._top_row)
        self._seg_host = QWidget()
        self._seg_row = QHBoxLayout(self._seg_host)
        self._seg_row.setContentsMargins(0, 0, 0, 0)
        self._seg_row.setSpacing(0)
        lay.addWidget(self._seg_host)
        self._top = QButtonGroup(self.nav)
        self._top.setExclusive(True)
        self._top.idClicked.connect(self._group_clicked)
        self._seg = QButtonGroup(self.nav)
        self._seg.setExclusive(True)
        self._groups = []           # [(name, [(label, page index), ...])]
        self._last = {}             # group -> the page it last showed, so Study brings you back to where you were
        self._alias_pick = None     # the alias label the user chose, so it (not its target) stays highlighted
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

    def group_of(self, index):
        """The name of the top-level tab a page belongs to."""
        for name, entries in self._groups:
            if any(i == index for _l, i in entries):
                return name
        return None

    def _rebuild(self):
        texts = {self.tabText(i): i for i in range(self.count())}
        groups = []
        placed = set()
        for name, titles in GROUPS:
            entries = []
            for t in titles:
                if t in texts:
                    entries.append((t, texts[t]))
                elif t in ALIASES and ALIASES[t] in texts:
                    entries.append((t, texts[ALIASES[t]]))
            placed.update(i for _l, i in entries)
            if entries:
                groups.append((name, entries))
        for t, i in texts.items():          # anything GROUPS does not know about still gets a tab
            if i not in placed:
                groups.append((t, [(t, i)]))
        self._groups = groups
        for b in self._top.buttons():
            self._top.removeButton(b)
            b.deleteLater()
        for gi, (name, entries) in enumerate(groups):
            b = QPushButton(name)
            b.setObjectName("navTab")
            b.setCheckable(True)
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)   # equal cells, whatever the label
            b.setFocusPolicy(Qt.TabFocus)
            b.setToolTip(TIPS.get(name, ""))
            self._top.addButton(b, gi)
            self._top_row.addWidget(b, 1)
        self._sync(self.currentIndex())

    def _group_clicked(self, gi):
        name, entries = self._groups[gi]
        self._alias_pick = None
        self.setCurrentIndex(self._last.get(name, entries[0][1]))

    def _seg_clicked(self, label, index):
        self._alias_pick = label
        self.entry_picked.emit(label)
        if index == self.currentIndex():
            self._sync(index)
        else:
            self.setCurrentIndex(index)

    def _sync(self, index):
        gi = next((k for k, (_n, entries) in enumerate(self._groups) if any(i == index for _l, i in entries)), -1)
        if gi < 0:
            return
        name, entries = self._groups[gi]
        self._last[name] = index
        b = self._top.button(gi)
        if b is not None:
            b.setChecked(True)
        # the segmented selector for this group; a group of one page needs none
        for sb in self._seg.buttons():
            self._seg.removeButton(sb)
            sb.deleteLater()
        self._seg_host.setVisible(len(entries) > 1)
        if len(entries) < 2:
            return
        labels = [l for l, i in entries if i == index]
        pick = self._alias_pick if self._alias_pick in labels else next((l for l in labels if l not in ALIASES),
                                                                         labels[0])
        for k, (label, i) in enumerate(entries):
            sb = QPushButton(label)
            sb.setObjectName("navSeg")
            sb.setProperty("pos", "first" if k == 0 else "last" if k == len(entries) - 1 else "mid")
            sb.setCheckable(True)
            sb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            sb.setFocusPolicy(Qt.TabFocus)
            sb.setToolTip(self.tabToolTip(i) or label)
            sb.clicked.connect(lambda _=False, lab=label, idx=i: self._seg_clicked(lab, idx))
            self._seg.addButton(sb)
            self._seg_row.addWidget(sb, 1)
            sb.setChecked(label == pick)
