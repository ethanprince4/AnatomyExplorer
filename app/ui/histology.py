import html

from PySide6.QtCore import QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QBoxLayout, QComboBox, QFrame, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QMenu, QPushButton, QSplitter, QTextBrowser,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import theme
from .stable_rows import fill_combo, fill_list
from .image_workspace import (LocalImageLoader, control, matches_words, searchable_text, image_control_card, CARD_TEXT,
                              CARD_MUTED, pinch_steps, trackpad_scroll)

ROLE = Qt.UserRole + 1
SEARCH_ROLE = Qt.UserRole + 2


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

    def __init__(self, ds, content, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.content = content
        self.setAccessibleName("Histology tissue and image library")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 6)
        lay.setSpacing(8)
        tissues = content.histology["tissues"]
        n_img = sum(len(t.get("images", [])) for t in tissues)
        head = QLabel(f"{len([t for t in tissues if t.get('images')])} tissues · {n_img} images")
        head.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
        lay.addWidget(head)
        self.filter = QLineEdit()
        self.filter.setAccessibleName("Search histology tissues and images")
        self.filter.setPlaceholderText("Search tissues, images or features…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._filter)
        lay.addWidget(self.filter)
        filter_row = QHBoxLayout()
        self.clear_filter = control("Clear", "Clear histology search and filter")
        self.clear_filter.clicked.connect(self._reset_filter)
        filter_row.addStretch(1)
        filter_row.addWidget(self.clear_filter)
        lay.addLayout(filter_row)
        self.count_label = QLabel()
        self.count_label.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_CAPTION))
        lay.addWidget(self.count_label)
        self.tree = QTreeWidget()
        self.tree.setAccessibleName("Histology tissues and images")
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setIndentation(14)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemActivated.connect(self._clicked)
        lay.addWidget(self.tree, 1)
        self.empty_state = QLabel("No matching content. Clear the filters or try another search.")
        self.empty_state.setWordWrap(True)
        self.empty_state.setStyleSheet(theme.text_css(theme.TEXT_2))
        lay.addWidget(self.empty_state)
        self._build()
        self._filter("")
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, self.tree.header().ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, self.tree.header().ResizeMode.ResizeToContents)

    def _build(self):
        folders = {}
        muted = theme.qc(theme.MUTED)
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
            parent = folder(t["path"])
            it = QTreeWidgetItem(parent)
            it.setText(0, t["name"])
            it.setText(1, str(len(t.get("images", []))) if t.get("images") else "No images")
            it.setForeground(1, muted)
            it.setData(0, ROLE, ("tissue", t["id"], 0))
            it.setToolTip(0, t.get("summary", ""))
            it.setData(0, SEARCH_ROLE, searchable_text(t.get("summary", ""), *t.get("features", []), *t.get("path", [])))
            for i, img in enumerate(t.get("images", [])):
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
            it.setExpanded(False)

    def _clicked(self, item, _col=0):
        d = item.data(0, ROLE)
        if d:
            self.imageRequested.emit(d[1], d[2])

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        if not it or not it.data(0, ROLE):
            return
        _, tid, idx = it.data(0, ROLE)
        t = self.content.tissues[tid]
        m = QMenu(self)
        m.addAction("Open", lambda: self.imageRequested.emit(tid, idx))
        names = linked_structure_names(self.ds, t)
        if names:
            m.addAction(f"Show in 3D ({len(names)} structures)", lambda: self.structuresRequested.emit(names))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _reset_filter(self):
        self.filter.clear()
        self._filter("")
        self.filter.setFocus()

    def _filter(self, text):
        q = text.strip()
        visible = 0

        def rec(item, inherited=False):
            nonlocal visible
            data = item.data(0, ROLE)
            direct = matches_words(q, searchable_text(item.text(0), item.toolTip(0), item.data(0, SEARCH_ROLE)))
            match = not q or direct or inherited
            child_match = False
            for i in range(item.childCount()):
                child_match |= rec(item.child(i), inherited or (bool(q) and direct))
            shown = child_match or (match and bool(data))
            item.setHidden(not shown)
            if item.childCount():
                item.setExpanded(bool(q) and child_match)
            if shown and data and data[0] == "tissue":
                visible += 1
            return shown

        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            rec(root.child(i))
        self.count_label.setText(f"{visible} topics shown")
        self.empty_state.setVisible(visible == 0)
        self.clear_filter.setEnabled(bool(q))


class ImageView(QGraphicsView):
    zoomChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.scene().addItem(self.item)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(theme.qc(theme.CANVAS))
        self.setFrameShape(QFrame.NoFrame)
        self._fit = True
        self._message = "Choose a tissue image from the library."
        self.setMinimumSize(180, 150)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Histology image")

    def set_pixmap(self, pix):
        self.item.setPixmap(pix)
        self._message = "" if not pix.isNull() else "Image is unavailable."
        self.scene().setSceneRect(QRectF(pix.rect()))
        self.fit()

    def set_message(self, message):
        self.set_pixmap(QPixmap())
        self._message = message
        self.setAccessibleDescription(message)
        self.viewport().update()

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if self.item.pixmap().isNull():
            painter.save()
            painter.resetTransform()
            painter.setPen(theme.qc(theme.MUTED))
            painter.drawText(self.viewport().rect().adjusted(24, 24, -24, -24),
                             Qt.AlignCenter | Qt.TextWordWrap, self._message)
            painter.restore()

    def fit(self):
        self._fit = True
        self.resetTransform()
        if not self.item.pixmap().isNull():
            self.fitInView(self.item, Qt.KeepAspectRatio)
        self.zoomChanged.emit(self.transform().m11())

    def actual_size(self):
        self._fit = False
        self.resetTransform()
        self.zoomChanged.emit(1.0)

    def zoom_by(self, steps):
        if self.item.pixmap().isNull():
            return
        self._fit = False
        current = self.transform().m11()
        target = max(0.05, min(20, current * (1.2 ** steps)))
        self.scale(target / current, target / current)
        self.zoomChanged.emit(target)

    def wheelEvent(self, event):
        if trackpad_scroll(event):
            super().wheelEvent(event)      # a two-finger swipe scrolls the zoomed image; a pinch zooms
            return
        self.zoom_by(event.angleDelta().y() / 120.0)
        event.accept()

    def viewportEvent(self, event):
        steps = pinch_steps(event, 1.2)
        if steps is not None:
            self.zoom_by(steps)
            return True
        return super().viewportEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Plus, Qt.Key_Equal, Qt.Key_Minus):
            self.zoom_by(-1 if event.key() == Qt.Key_Minus else 1)
        elif event.key() in (Qt.Key_Home, Qt.Key_0):
            self.fit()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fit:
            self.fit()

    def mouseDoubleClickEvent(self, e):
        self.fit()


class HistologyViewer(QWidget):
    """Center tab: large zoomable micrograph with caption and thumbnail strip."""

    structuresRequested = Signal(list)
    browserRequested = Signal()
    detailsRequested = Signal()

    def __init__(self, ds, content, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.content = content
        self.tissue = None
        self.index = 0
        self.info = None
        self.names = []
        self._loader = LocalImageLoader(self)
        self._loader.loaded.connect(self._image_loaded)
        self.setAccessibleName("Histology image workspace")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        header_layout = QVBoxLayout()
        heading = QHBoxLayout()
        self.title = QLabel("Histology")
        self.title.setWordWrap(True)
        self.title.setStyleSheet(theme.text_css(CARD_TEXT, theme.FS_TITLE, 700))
        heading.addWidget(self.title, 1)
        self.counter = QLabel()
        self.counter.setStyleSheet(theme.text_css(CARD_MUTED))
        heading.addWidget(self.counter)
        self.browse_tissues = control("Browse tissues", "Browse histology tissues")
        self.browse_tissues.clicked.connect(self.browserRequested.emit)
        heading.addWidget(self.browse_tissues)
        self.show_details = control("Details", "Show histology details")
        self.show_details.clicked.connect(self.detailsRequested.emit)
        heading.addWidget(self.show_details)
        header_layout.addLayout(heading)
        choice_row = QHBoxLayout()
        self.image_choice = QComboBox()
        self.image_choice.setAccessibleName("Choose histology image")
        self.image_choice.setMinimumContentsLength(12)
        self.image_choice.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.image_choice.currentIndexChanged.connect(self._choose_image)
        choice_row.addWidget(self.image_choice, 1)
        self.previous_image = control("Previous", "Previous histology image", "Previous image (Page Up)")
        self.next_image = control("Next", "Next histology image", "Next image (Page Down)")
        self.previous_image.clicked.connect(lambda: self.step(-1))
        self.next_image.clicked.connect(lambda: self.step(1))
        choice_row.addWidget(self.previous_image)
        choice_row.addWidget(self.next_image)
        header_layout.addLayout(choice_row)
        self._tools_layout = QBoxLayout(QBoxLayout.LeftToRight)
        self._tools_layout.setContentsMargins(0, 0, 0, 0)
        image_tools = QHBoxLayout()
        self.fit_image = control("Fit", "Fit histology image", "Fit the image (Home)")
        self.fit_image.clicked.connect(lambda: self.view.fit())
        self.actual_image = control("100%", "View histology image at actual size")
        self.actual_image.clicked.connect(lambda: self.view.actual_size())
        self.zoom_out = control("−", "Zoom histology image out")
        self.zoom_out.clicked.connect(lambda: self.view.zoom_by(-1))
        self.zoom_in = control("+", "Zoom histology image in")
        self.zoom_in.clicked.connect(lambda: self.view.zoom_by(1))
        self.zoom_label = QLabel("Fit")
        self.zoom_label.setMinimumWidth(44)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        for widget in (self.fit_image, self.actual_image, self.zoom_out, self.zoom_label, self.zoom_in):
            image_tools.addWidget(widget)
        self._tools_layout.addLayout(image_tools)
        self._tools_layout.addStretch(1)
        reference_tools = QHBoxLayout()
        self.show3d = control("Show in 3D", "Show linked histology structures in 3D")
        self.show3d.clicked.connect(self._show3d)
        reference_tools.addWidget(self.show3d)
        self.source = control("Source", "Open this image's source and licence")
        self.source.clicked.connect(self._open_source)
        reference_tools.addWidget(self.source)
        self._tools_layout.addLayout(reference_tools)
        header_layout.addLayout(self._tools_layout)
        self.header_card = image_control_card(header_layout, "histologyControls")
        lay.addWidget(self.header_card)
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        self.view = ImageView()
        split.addWidget(self.view)
        self.view.zoomChanged.connect(self._zoom_changed)
        self.caption = QTextBrowser()
        self.caption.setOpenExternalLinks(True)
        self.caption.setStyleSheet("QTextBrowser { background: #f8fafb; color: #24343d; border: 1px solid #cbd5db; border-radius: 10px; }")
        self.caption.setAccessibleName("Histology image caption and credit")
        self.caption.setMinimumHeight(100)
        self.caption.document().setDefaultStyleSheet(
            f"body{{color:{CARD_TEXT};}} .muted{{color:{CARD_MUTED};}} "
            f"a{{color:#216582;text-decoration:none;}} h3{{margin:0;color:{CARD_TEXT};}}")
        self.caption.document().setDocumentMargin(10)
        split.addWidget(self.caption)
        split.setSizes([700, 160])
        lay.addWidget(split, 1)
        status_row = QHBoxLayout()
        self.image_status = QLabel("Choose a tissue image from the library.")
        self.image_status.setWordWrap(True)
        self.image_status.setStyleSheet(theme.text_css(CARD_MUTED, theme.FS_CAPTION))
        status_row.addWidget(self.image_status, 1)
        self.retry_image = control("Retry image", "Retry opening this histology image")
        self.retry_image.clicked.connect(lambda: self.tissue and self.show_image(self.index))
        self.retry_image.hide()
        status_row.addWidget(self.retry_image)
        self.status_card = image_control_card(status_row, "histologyStatus")
        lay.addWidget(self.status_card)

        self.strip = QListWidget()
        self.strip.setViewMode(QListWidget.IconMode)
        self.strip.setFlow(QListWidget.LeftToRight)
        self.strip.setWrapping(False)
        self.strip.setAccessibleName("Histology image thumbnails")
        self.strip.setIconSize(QSize(96, 66))
        self.strip.setFixedHeight(66 + self.fontMetrics().height() + 30)
        self.strip.setMovement(QListWidget.Static)
        self.strip.setSpacing(4)
        self.strip.currentRowChanged.connect(lambda r: r >= 0 and r != self.index and self.show_image(r))
        lay.addWidget(self.strip)
        from PySide6.QtGui import QKeySequence, QShortcut
        for key, direction in (("PgDown", 1), ("PgUp", -1)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda direction=direction: self.step(direction))
        self._set_controls(False)

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
            self._loader.cancel()
            self.tissue, self.names, self.index = None, [], 0
            self.title.setText(t.get("name", "Histology") if t else "Histology")
            self.view.set_message("No images are available for this tissue. Choose another tissue from the library.")
            self.image_status.setText(self.view._message)
            self.caption.clear()
            self._fill_images([])
            self.counter.clear()
            self._set_controls(False)
            self.retry_image.hide()
            return
        if self.tissue is not t:
            self.tissue = t
            self._fill_images(t["images"])
            self.names = linked_structure_names(self.ds, t)
            self.show3d.setText("Show in 3D" if self.names else "No 3D link")
            self.show3d.setToolTip(f"Show {len(self.names)} linked structures. Images are not spatially registered to the 3D reference."
                                   if self.names else "This tissue has no authored structures in the installed atlas.")
        self.show_image(max(0, min(index, len(t["images"]) - 1)))
        self._update_info()

    def _fill_images(self, images):
        """Thumbnails and the image picker for a tissue. A tissue change comes from a click in the library with
        both views alive, so their rows are rewritten rather than removed (see stable_rows)."""
        def fill(item, numbered):
            row, img = numbered
            item.setIcon(QIcon(str(self.content.thumb_path(img))))
            item.setText(str(row + 1))
            item.setToolTip(img["title"])
            item.setData(Qt.AccessibleTextRole, img["title"])

        self.strip.blockSignals(True)
        self.image_choice.blockSignals(True)
        fill_list(self.strip, list(enumerate(images)), fill)
        fill_combo(self.image_choice, [(img["title"], row) for row, img in enumerate(images)])
        if not images:
            self.strip.setCurrentRow(-1)
            self.image_choice.setCurrentIndex(-1)
        self.strip.blockSignals(False)
        self.image_choice.blockSignals(False)

    def _choose_image(self, index):
        if self.tissue and index >= 0 and index != self.index:
            self.show_image(index)

    def step(self, d):
        if self.tissue and self.tissue.get("images"):
            n = len(self.tissue["images"])
            self.show_image((self.index + d) % n)

    def show_image(self, index):
        t = self.tissue
        if not t or not 0 <= index < len(t.get("images", [])):
            return
        img = t["images"][index]
        self.index = index
        self.view.set_message("Loading image…")
        self.image_status.setText("Loading local image…")
        self.retry_image.hide()
        self._set_controls(False)
        self._loader.load(self.content.image_path(img))
        self.title.setText(t['name'])
        self.image_choice.blockSignals(True)
        self.image_choice.setCurrentIndex(index)
        self.image_choice.setToolTip(img['title'])
        self.image_choice.blockSignals(False)
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

    def _set_controls(self, image_available):
        for button in (self.fit_image, self.actual_image, self.zoom_out, self.zoom_in):
            button.setEnabled(image_available)
        images = self.tissue.get("images", []) if self.tissue else []
        self.image_choice.setEnabled(bool(images))
        self.previous_image.setEnabled(len(images) > 1)
        self.next_image.setEnabled(len(images) > 1)
        self.show3d.setEnabled(bool(self.names))
        source = images[self.index].get("source", "") if images else ""
        self.source.setEnabled(QUrl(source).scheme() in ("https", "http"))

    def _image_loaded(self, image, error):
        if self.tissue is None:
            return
        if error:
            self.view.set_message(error)
            self.image_status.setText(error)
            self.retry_image.show()
            self._set_controls(False)
        else:
            self.view.set_pixmap(QPixmap.fromImage(image))
            title = self.tissue["images"][self.index]["title"]
            self.view.setAccessibleDescription(f"{title}. Use plus and minus to zoom, Home to fit, Page Up and Page Down to change images.")
            self.image_status.setText("Original image colours and labels · + / − to zoom · Drag to pan · Home to fit")
            self.retry_image.hide()
            self._set_controls(True)

    def _zoom_changed(self, scale):
        self.zoom_label.setText("Fit" if self.view._fit else f"{round(scale * 100)}%")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._tools_layout.setDirection(QBoxLayout.TopToBottom if self.width() < 590 else QBoxLayout.LeftToRight)

    def _open_source(self):
        if self.tissue:
            url = QUrl(self.tissue["images"][self.index].get("source", ""))
            if url.scheme() in ("https", "http"):
                QDesktopServices.openUrl(url)

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
            struct_links = f"<p class='overline'>FOUND IN (3D)</p><p>{' · '.join(items)}{more}</p>"
        siblings = [x for x in self.content.histology["tissues"] if x["path"] == t["path"] and x is not t
                    and x.get("images")]
        sib = " · ".join(f'<a href="histo:{esc(x["id"])}|0">{esc(x["name"])}</a>' for x in siblings)
        imgs = " · ".join(f'<a href="histo:{esc(t["id"])}|{i}">{i + 1}</a>' for i in range(len(t["images"])))
        body = (f"<div class='crumb'>{esc(' › '.join(t['path']))}</div>"
                f"<p class='summary'>{esc(t.get('summary'))}</p>"
                f"<p class='overline'>KEY FEATURES</p><ul>{feats}</ul>{struct_links}"
                f"<p class='overline'>IMAGES</p><p>{imgs}</p>"
                + (f"<p class='overline'>RELATED TISSUES</p><p>{sib}</p>" if sib else "")
                + "<p class='muted'>Images from Wikimedia Commons; see each image caption for author and licence.</p>")
        self.info.show_html(f"<h1>{esc(t['name'])}</h1>", body)

    def figure_caption(self):
        """Metadata for the actual image shown in this viewer."""
        tissue = self.tissue or {}
        images = tissue.get("images", [])
        image = images[self.index] if 0 <= self.index < len(images) else {}
        title = image.get("title") or tissue.get("name") or "Histology figure"
        bits = [name for name in (tissue.get("name"), "Diagram" if image.get("diagram") else "Micrograph") if name]
        credit = " · ".join(str(image[field]) for field in ("author", "license", "source") if image.get(field))
        return title, bits, credit or "Anatomy Explorer · Histology"
