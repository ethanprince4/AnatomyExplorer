from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QCursor
from PySide6.QtWidgets import QLabel, QLineEdit, QMenu, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .search_panel import normalized

from . import theme

ROLE_NODE = Qt.UserRole + 1


class TreePanel(QWidget):
    nodeActivated = Signal(str)
    nodeAction = Signal(str, str)

    def __init__(self, ds, state, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.state = state
        self._sync = False
        self._filter_expanded = None
        self.setMinimumWidth(240)
        self.setAccessibleName("Anatomy hierarchy")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter names or Latin terms…")
        self.filter.setAccessibleName("Filter anatomy hierarchy")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        lay.addWidget(self.filter)
        self.info = QLabel("Check to show or hide; select a name to explore.")
        self.info.setWordWrap(True)
        self.info.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
        lay.addWidget(self.info)
        self.tree = QTreeWidget()
        self.tree.setAccessibleName("Anatomy structure tree")
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(14)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.tree)
        self.items = {}
        self._build()
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, self.tree.header().ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, self.tree.header().ResizeMode.ResizeToContents)
        self.tree.itemChanged.connect(self._changed)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemActivated.connect(lambda item, _column: self.nodeActivated.emit(item.data(0, ROLE_NODE)))
        state.visibility_changed.connect(self.sync)
        self.sync()

    def _build(self):
        muted = QBrush(theme.qc(theme.MUTED))

        def add(nid, parent_item):
            node = self.ds.nodes[nid]
            it = QTreeWidgetItem(parent_item)
            it.setText(0, node["name"])
            if node["children"]:
                it.setText(1, str(node["count"]))
                it.setForeground(1, muted)
            it.setData(0, ROLE_NODE, nid)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked)
            tip = node["name"]
            if node.get("latin"):
                tip += f"\n{node['latin']}"
            it.setToolTip(0, tip)
            it.setData(0, Qt.AccessibleTextRole, tip.replace("\n", ". "))
            if node["kind"] == "system":
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
            self.items[nid] = it
            for c in node["children"]:
                add(c, it)

        self._sync = True
        for root in self.ds.tree_roots:
            add(root, self.tree.invisibleRootItem())
        self._sync = False

    def sync(self):
        vis = self.state.visible_mask()
        self._sync = True
        self.tree.setUpdatesEnabled(False)

        def rec(nid):
            node = self.ds.nodes[nid]
            it = self.items[nid]
            if "sid" in node:
                v = bool(vis[node["sid"]])
                n_on, n_all = (1 if v else 0), 1
            else:
                n_on, n_all = 0, 0
            for c in node["children"]:
                a, b = rec(c)
                n_on += a
                n_all += b
            st = Qt.Checked if n_all and n_on == n_all else (Qt.Unchecked if n_on == 0 else Qt.PartiallyChecked)
            if it.checkState(0) != st:
                it.setCheckState(0, st)
            return n_on, n_all

        for root in self.ds.tree_roots:
            rec(root)
        self.tree.setUpdatesEnabled(True)
        self._sync = False

    def _changed(self, item, column):
        if self._sync or column != 0:
            return
        nid = item.data(0, ROLE_NODE)
        self.state.tree_toggle(nid, item.checkState(0) != Qt.Unchecked)

    def _clicked(self, item, column):
        pos = self.tree.viewport().mapFromGlobal(QCursor.pos())
        rect = self.tree.visualItemRect(item)
        if column == 0 and rect.left() <= pos.x() <= rect.left() + 22:
            return  # checkbox toggle, not a selection
        self.nodeActivated.emit(item.data(0, ROLE_NODE))

    def reveal(self, sid):
        nid = self.ds.node_of_structure.get(sid)
        if nid is None or nid not in self.items:
            return
        item = self.items[nid]
        # A route from search/3D must never scroll to an invisible filtered-out row.
        if item.isHidden():
            self.filter.clear()
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        previous = self.tree.blockSignals(True)
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)
        self.tree.blockSignals(previous)

    def _apply_filter(self, text):
        terms = normalized(text).split()
        if terms and self._filter_expanded is None:
            self._filter_expanded = {nid for nid, item in self.items.items() if item.isExpanded()}
        self.tree.setUpdatesEnabled(False)
        visible = 0

        def rec(nid, parent_match=False):
            nonlocal visible
            node = self.ds.nodes[nid]
            item = self.items[nid]
            words = normalized(f"{node['name']} {node.get('latin', '')}")
            own_match = bool(terms) and all(term in words for term in terms)
            match = not terms or parent_match or own_match
            child_match = False
            for child in node['children']:
                child_match = rec(child, parent_match or own_match) or child_match
            show = match or child_match
            item.setHidden(not show)
            if show and 'sid' in node:
                visible += 1
            if terms and child_match:
                item.setExpanded(True)
            return show

        try:
            for root in self.ds.tree_roots:
                rec(root)
            if not terms and self._filter_expanded is not None:
                for nid, item in self.items.items():
                    item.setExpanded(nid in self._filter_expanded)
                self._filter_expanded = None
        finally:
            self.tree.setUpdatesEnabled(True)
        if terms:
            self.info.setText(f"{visible:,} matching structures · Check to change visibility" if visible else
                              "No matches. Try a shorter name or a Latin term.")
        else:
            self.info.setText("Check to show or hide; select a name to explore.")

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        if not it:
            return
        nid = it.data(0, ROLE_NODE)
        m = QMenu(self)
        for label, act in (("Select && focus", "focus"), ("X-ray focus", "xray"), ("Isolate", "isolate"),
                           ("Hide", "hide"), ("Show", "show")):
            m.addAction(label, lambda a=act: self.nodeAction.emit(nid, a))
        m.addSeparator()
        m.addAction("Expand all below", lambda: self._expand(it))
        m.exec(self.tree.viewport().mapToGlobal(pos))
        m.deleteLater()

    def _expand(self, it):
        it.setExpanded(True)
        for i in range(it.childCount()):
            self._expand(it.child(i))
