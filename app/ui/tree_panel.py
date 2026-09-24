from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QCursor
from PySide6.QtWidgets import QLineEdit, QMenu, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

ROLE_NODE = Qt.UserRole + 1


class TreePanel(QWidget):
    nodeActivated = Signal(str)
    nodeAction = Signal(str, str)

    def __init__(self, ds, state, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.state = state
        self._sync = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 8, 6, 6)
        lay.setSpacing(6)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter tree…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        lay.addWidget(self.filter)
        self.tree = QTreeWidget()
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
        state.visibility_changed.connect(self.sync)
        self.sync()

    def _build(self):
        muted = QBrush(QColor("#7d8796"))

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
            st = Qt.Checked if n_on == n_all else (Qt.Unchecked if n_on == 0 else Qt.PartiallyChecked)
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
        if nid is None:
            return
        it = self.items[nid]
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(it)
        self.tree.scrollToItem(it)
        self.tree.blockSignals(False)

    def _apply_filter(self, text):
        t = text.strip().lower()
        self.tree.setUpdatesEnabled(False)

        def rec(nid):
            node = self.ds.nodes[nid]
            it = self.items[nid]
            match = not t or t in node["name"].lower()
            child_match = False
            for c in node["children"]:
                child_match |= rec(c)
            show = match or child_match
            it.setHidden(not show)
            if t and child_match:
                it.setExpanded(True)
            return show

        for root in self.ds.tree_roots:
            rec(root)
        if not t:
            self.tree.collapseAll()
        self.tree.setUpdatesEnabled(True)

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

    def _expand(self, it):
        it.setExpanded(True)
        for i in range(it.childCount()):
            self._expand(it.child(i))
