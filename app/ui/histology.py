import html

from PySide6.QtCore import QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton, QSplitter, QTextBrowser,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

ROLE = Qt.UserRole + 1


def esc(s):
    return html.escape(str(s or ""), quote=True)


def linked_structure_names(ds, tissue):
    names = set(n for n in tissue.get("structures", []) if n in ds.by_name)
    lower = {g.lower() for g in tissue.get("groups", [])}
    if lower:
        for nid, node in ds.nodes.items():
            if node["kind"] == "group" and node["name"].lower() in lower:
                for sid in ds.node_structures(nid):
                    names.add(ds.structures[sid]["base"])
    for sub in tissue.get("contains", []):
        sub = sub.lower()
        for base in ds.by_name:
            if sub in base.lower():
                names.add(base)
    return sorted(names)


class HistologyBrowser(QWidget):
    """Left-panel tab: tree of histology topics."""

    imageRequested = Signal(str, int)
    structuresRequested = Signal(list)
    microRequested = Signal(str)

    def __init__(self, ds, content, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.content = content
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 8, 6, 6)
        lay.setSpacing(6)
        tissues = content.histology["tissues"]
        n_img = sum(len(t.get("images", [])) for t in tissues)
        head = QLabel(f"{len(content.micro_models)} 3D models · {len([t for t in tissues if t.get('images')])} "
                      f"tissues · {n_img} images")
        head.setStyleSheet("color:#8a94a3; padding-left:4px;")
        lay.addWidget(head)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter tissues and images…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._filter)
        lay.addWidget(self.filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setIndentation(14)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemActivated.connect(self._clicked)
        lay.addWidget(self.tree, 1)
        self._build()
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, self.tree.header().ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, self.tree.header().ResizeMode.ResizeToContents)

    def _build(self):
        folders = {}
        muted = QColor("#7d8796")
        micro_root = QTreeWidgetItem(self.tree.invisibleRootItem())
        micro_root.setText(0, "3D microanatomy models")
        micro_root.setText(1, str(len(self.content.micro_models)))
        micro_root.setForeground(1, muted)
        f = micro_root.font(0)
        f.setBold(True)
        micro_root.setFont(0, f)
        micro_root.setExpanded(True)
        for m in sorted(self.content.micro_models.values(), key=lambda m: m.name.lower()):
            it = QTreeWidgetItem(micro_root)
            it.setText(0, m.name)
            it.setToolTip(0, m.summary)
            it.setData(0, ROLE, ("micro", m.id, 0))

        def folder(path):
            key = tuple(path)
            if key in folders:
                return folders[key]
            parent = folder(path[:-1]) if len(path) > 1 else self.tree.invisibleRootItem()
            it = QTreeWidgetItem(parent)
            it.setText(0, path[-1])
            f = it.font(0)
            f.setBold(len(path) == 1)
            it.setFont(0, f)
            folders[key] = it
            return it

        for t in self.content.histology["tissues"]:
            if not t.get("images"):
                continue
            parent = folder(t["path"])
            it = QTreeWidgetItem(parent)
            it.setText(0, t["name"])
            it.setText(1, str(len(t["images"])))
            it.setForeground(1, muted)
            it.setData(0, ROLE, ("tissue", t["id"], 0))
            it.setToolTip(0, t.get("summary", ""))
            for i, img in enumerate(t["images"]):
                child = QTreeWidgetItem(it)
                child.setText(0, img["title"])
                child.setData(0, ROLE, ("image", t["id"], i))
                child.setToolTip(0, img.get("description", "")[:300])
        for key, it in folders.items():
            count = 0
            stack = [it]
            while stack:
                x = stack.pop()
                for i in range(x.childCount()):
                    c = x.child(i)
                    d = c.data(0, ROLE)
                    if d and d[0] == "tissue":
                        count += 1
                    elif not d:
                        stack.append(c)
            it.setText(1, str(count))
            it.setForeground(1, muted)
            if len(key) == 1:
                it.setExpanded(True)

    def _clicked(self, item, _col=0):
        d = item.data(0, ROLE)
        if d and d[0] == "micro":
            self.microRequested.emit(d[1])
        elif d:
            self.imageRequested.emit(d[1], d[2])

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        if not it or not it.data(0, ROLE) or it.data(0, ROLE)[0] == "micro":
            return
        _, tid, idx = it.data(0, ROLE)
        t = self.content.tissues[tid]
        m = QMenu(self)
        m.addAction("Open", lambda: self.imageRequested.emit(tid, idx))
        names = linked_structure_names(self.ds, t)
        if names:
            m.addAction(f"Show in 3D ({len(names)} structures)", lambda: self.structuresRequested.emit(names))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _filter(self, text):
        q = text.strip().lower()

        def rec(item):
            match = not q or q in item.text(0).lower()
            child_match = False
            for i in range(item.childCount()):
                child_match |= rec(item.child(i))
            item.setHidden(not (match or child_match))
            if q and child_match:
                item.setExpanded(True)
            return match or child_match

        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            rec(root.child(i))


class ImageView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.scene().addItem(self.item)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#0e1013"))
        self.setFrameShape(QFrame.NoFrame)
        self._fit = True

    def set_pixmap(self, pix):
        self.item.setPixmap(pix)
        self.scene().setSceneRect(QRectF(pix.rect()))
        self.fit()

    def fit(self):
        self._fit = True
        self.resetTransform()
        if not self.item.pixmap().isNull():
            self.fitInView(self.item, Qt.KeepAspectRatio)

    def actual_size(self):
        self._fit = False
        self.resetTransform()

    def wheelEvent(self, e):
        self._fit = False
        factor = 1.2 ** (e.angleDelta().y() / 120.0)
        cur = self.transform().m11()
        if 0.05 < cur * factor < 20:
            self.scale(factor, factor)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fit:
            self.fit()

    def mouseDoubleClickEvent(self, e):
        self.fit()


class HistologyViewer(QWidget):
    """Center tab: large zoomable micrograph with caption and thumbnail strip."""

    structuresRequested = Signal(list)

    def __init__(self, ds, content, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.content = content
        self.tissue = None
        self.index = 0
        self.info = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        bar = QHBoxLayout()
        bar.setContentsMargins(12, 8, 12, 8)
        self.title = QLabel()
        self.title.setStyleSheet("font-size:13pt; font-weight:600; color:#eef3f8;")
        bar.addWidget(self.title, 1)
        self.counter = QLabel()
        self.counter.setStyleSheet("color:#8a94a3; padding: 0 10px;")
        bar.addWidget(self.counter)
        for text, fn in (("◀ Prev", lambda: self.step(-1)), ("Next ▶", lambda: self.step(1)),
                         ("Fit", lambda: self.view.fit()), ("100%", lambda: self.view.actual_size())):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.show3d = QPushButton("Show in 3D")
        self.show3d.clicked.connect(self._show3d)
        bar.addWidget(self.show3d)
        self.source = QPushButton("Source")
        self.source.clicked.connect(self._open_source)
        bar.addWidget(self.source)
        top = QWidget()
        top.setLayout(bar)
        top.setStyleSheet("background:#14171c;")
        lay.addWidget(top)

        split = QSplitter(Qt.Vertical)
        self.view = ImageView()
        split.addWidget(self.view)
        self.caption = QTextBrowser()
        self.caption.setOpenExternalLinks(True)
        self.caption.document().setDefaultStyleSheet(
            "body{color:#d9dee6;} .muted{color:#8a94a3;} a{color:#6fd0fa;text-decoration:none;} "
            "h3{margin:0;color:#eef3f8;}")
        self.caption.document().setDocumentMargin(10)
        split.addWidget(self.caption)
        split.setSizes([700, 160])
        lay.addWidget(split, 1)

        self.strip = QListWidget()
        self.strip.setViewMode(QListWidget.IconMode)
        self.strip.setFlow(QListWidget.LeftToRight)
        self.strip.setWrapping(False)
        self.strip.setIconSize(QSize(120, 90))
        self.strip.setFixedHeight(122)
        self.strip.setMovement(QListWidget.Static)
        self.strip.setSpacing(4)
        self.strip.currentRowChanged.connect(lambda r: r >= 0 and r != self.index and self.show_image(r))
        lay.addWidget(self.strip)

    def on_activated(self, info):
        self.info = info
        self._update_info()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Right, Qt.Key_PageDown):
            self.step(1)
        elif e.key() in (Qt.Key_Left, Qt.Key_PageUp):
            self.step(-1)
        else:
            super().keyPressEvent(e)

    def show_tissue(self, tissue_id, index=0):
        t = self.content.tissues.get(tissue_id)
        if not t or not t.get("images"):
            return
        if self.tissue is not t:
            self.tissue = t
            self.strip.blockSignals(True)
            self.strip.clear()
            for img in t["images"]:
                it = QListWidgetItem(QIcon(str(self.content.thumb_path(img))), "")
                it.setToolTip(img["title"])
                self.strip.addItem(it)
            self.strip.blockSignals(False)
            self.names = linked_structure_names(self.ds, t)
            self.show3d.setEnabled(bool(self.names))
            self.show3d.setText(f"Show in 3D ({len(self.names)})" if self.names else "No 3D link")
        self.show_image(max(0, min(index, len(t["images"]) - 1)))
        self._update_info()

    def step(self, d):
        if self.tissue:
            n = len(self.tissue["images"])
            self.show_image((self.index + d) % n)

    def show_image(self, index):
        t = self.tissue
        img = t["images"][index]
        self.index = index
        pix = QPixmap(str(self.content.image_path(img)))
        self.view.set_pixmap(pix)
        self.title.setText(f"{t['name']}  —  {img['title']}")
        self.counter.setText(f"{index + 1} / {len(t['images'])}")
        self.strip.blockSignals(True)
        self.strip.setCurrentRow(index)
        self.strip.blockSignals(False)
        desc = esc(img.get("description") or "No description provided.").replace("\n", "<br>")
        kind = "Diagram" if img.get("diagram") else "Micrograph"
        credit = " · ".join(x for x in (esc(img.get("author")), esc(img.get("license"))) if x)
        self.caption.setHtml(
            f"<h3>{esc(img['title'])}</h3><p class='muted'>{kind} · {credit} · "
            f"<a href='{esc(img.get('source'))}'>Wikimedia Commons</a></p><p>{desc}</p>")

    def _open_source(self):
        if self.tissue:
            QDesktopServices.openUrl(QUrl(self.tissue["images"][self.index].get("source", "")))

    def _show3d(self):
        if self.names:
            self.structuresRequested.emit(self.names)

    def _update_info(self):
        if not self.info or not self.tissue:
            return
        t = self.tissue
        feats = "".join(f"<li>{esc(f)}</li>" for f in t.get("features", []))
        struct_links = ""
        if self.names:
            items = []
            for n in self.names[:40]:
                sids = ",".join(str(s) for s in self.ds.structures_named(n))
                items.append(f'<a href="sids:{sids}">{esc(n)}</a>')
            more = f" <span class='muted'>(+{len(self.names) - 40})</span>" if len(self.names) > 40 else ""
            struct_links = f"<h3>FOUND IN (3D)</h3><p>{' · '.join(items)}{more}</p>"
        siblings = [x for x in self.content.histology["tissues"] if x["path"] == t["path"] and x is not t
                    and x.get("images")]
        sib = " · ".join(f'<a href="histo:{esc(x["id"])}|0">{esc(x["name"])}</a>' for x in siblings)
        imgs = " · ".join(f'<a href="histo:{esc(t["id"])}|{i}">{i + 1}</a>' for i in range(len(t["images"])))
        body = (f"<div class='crumb'>{esc(' › '.join(t['path']))}</div>"
                f"<p class='summary'>{esc(t.get('summary'))}</p>"
                f"<h3>KEY FEATURES</h3><ul>{feats}</ul>{struct_links}"
                f"<h3>IMAGES</h3><p>{imgs}</p>"
                + (f"<h3>RELATED TISSUES</h3><p>{sib}</p>" if sib else "")
                + "<p class='muted'>Images from Wikimedia Commons; see each image caption for author and licence.</p>")
        self.info.show_html(f"<h1>{esc(t['name'])}</h1>", body)
