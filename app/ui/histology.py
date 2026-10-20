import html

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetricsF, QIcon, QPainter, QPen, QPixmap, QLinearGradient
from PySide6.QtWidgets import (QBoxLayout, QCheckBox, QComboBox, QFrame, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton, QSplitter, QTextBrowser,
                               QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from . import theme
from .outline import Outline, OutlineItem
from .stable_rows import fill_combo, fill_list
from .image_workspace import (LocalImageLoader, control, matches_words, searchable_text, image_control_card, CARD_TEXT,
                              CARD_MUTED, pinch_steps, trackpad_scroll)

ROLE = Qt.UserRole + 1
SEARCH_ROLE = Qt.UserRole + 2
GROUP_ROLE = Qt.UserRole + 3
GROUP_COUNT_ROLE = Qt.UserRole + 4


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


class HistologyCatalogue(Outline):
    """An endless, two-column catalogue of stable tissue rows, grouped across the wall."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._item_rects = {}
        self._content_height = 0
        self.setRowHeight(46)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(f'HistologyCatalogue {{background:transparent;border:0;}}'
                           f'QScrollBar:vertical {{background:transparent;width:4px;margin:0;}}'
                           f'QScrollBar::handle:vertical {{background:{theme.BORDER_STRONG};min-height:24px;'
                           f'border:0;border-radius:2px;}}'
                           f'QScrollBar::handle:vertical:hover {{background:{theme.MUTED};}}'
                           f'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}'
                           f'QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {{background:transparent;}}')

    def _ensure_layout(self):
        if self._rows is not None:
            return
        width = max(1, self.viewport().width() - 24)
        columns = 2 if width >= 460 else 1
        gap = 60 if width >= 850 else 28
        column_width = (width - gap * (columns - 1)) // columns
        self._rows, self._item_rects = [], {}
        y = 0
        for group in self._root._children:
            if group.isHidden():
                continue
            self._rows.append((group, 0))
            self._item_rects[id(group)] = QRect(0, y, width, 30)
            y += 30
            entries = []
            for tissue in group._children:
                if tissue.isHidden():
                    continue
                entries.append((tissue, 1))
                if tissue.isExpanded():
                    entries.extend((image, 2) for image in tissue._children if not image.isHidden())
            rows = (len(entries) + columns - 1) // columns
            for i, (item, depth) in enumerate(entries):
                column, row = divmod(i, max(1, rows))
                self._rows.append((item, depth))
                self._item_rects[id(item)] = QRect(column * (column_width + gap), y + row * 46, column_width, 46)
            y += rows * 46 + 34
        self._content_height = y + 120
        self._index = {id(item): n for n, (item, _depth) in enumerate(self._rows)}
        self._update_scrollbar()

    def _update_scrollbar(self):
        bar = self.verticalScrollBar()
        total = getattr(self, "_content_height", 0)
        bar.setRange(0, max(0, total - self.viewport().height()))
        bar.setPageStep(max(46, self.viewport().height()))
        bar.setSingleStep(46)

    def resizeEvent(self, event):
        self._rows = None
        super().resizeEvent(event)

    def itemAt(self, pos):
        self._ensure_layout()
        point = QPointF(pos.x(), pos.y() + self.verticalScrollBar().value()).toPoint()
        return next((item for item, _depth in self._rows if self._item_rects[id(item)].contains(point)), None)

    def _hit(self, pos):
        item = self.itemAt(pos)
        return item, "row" if item is not None else None

    def visualItemRect(self, item):
        self._ensure_layout()
        rect = self._item_rects.get(id(item), QRect())
        return rect.translated(0, -self.verticalScrollBar().value())

    def scrollToItem(self, item):
        if item is None:
            return
        self._ensure_layout()
        rect = self._item_rects.get(id(item))
        if rect is None:
            return
        bar = self.verticalScrollBar()
        if item.data(0, GROUP_ROLE) or rect.top() < bar.value():
            bar.setValue(rect.top())
        elif rect.bottom() > bar.value() + self.viewport().height():
            bar.setValue(rect.bottom() - self.viewport().height() + 1)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.position())
        if item is not None and event.button() == Qt.LeftButton:
            self.setCurrentItem(item)
            self.itemActivated.emit(item, 0)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        self._ensure_layout()
        bar = self.verticalScrollBar()
        height = self.viewport().height()
        if height < 1:
            return
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        palette = theme.palette()
        origin = self.mapTo(self.window(), self.rect().topLeft()).y()
        wall = QLinearGradient(0, -origin, 0, max(1, self.window().height()) - origin)
        wall.setColorAt(0, theme.qc(palette["stage_top"]))
        wall.setColorAt(1, theme.qc(palette["stage_bottom"]))
        p.fillRect(self.viewport().rect(), wall)
        for item, depth in self._rows:
            rect = self.visualItemRect(item)
            if not rect.intersects(self.viewport().rect()):
                continue
            if depth == 0:
                p.setFont(theme.font_for("meta", weight=600))
                p.setPen(theme.qc(theme.TEXT_2))
                p.drawText(rect.adjusted(0, 0, 0, -5), Qt.AlignVCenter, item.text(0))
                p.drawText(rect.adjusted(0, 0, 0, -5), Qt.AlignRight | Qt.AlignVCenter, "Slides")
                p.setPen(QPen(theme.qc(theme.BORDER), 1))
                p.drawLine(rect.bottomLeft(), rect.bottomRight())
                continue
            if item is self._hover:
                p.fillRect(rect, theme.qc(theme.TEXT_STRONG, 15))
            selected = item is self._current
            count_font = theme.font_for("meta")
            p.setFont(count_font)
            count = item.text(1)
            count_width = max(18, QFontMetricsF(count_font).horizontalAdvance(count))
            p.setPen(theme.qc(theme.TEXT_2))
            p.drawText(QRectF(rect.right() - count_width, rect.y(), count_width, rect.height()),
                       Qt.AlignRight | Qt.AlignVCenter, count)
            icon_rect = QRect(rect.left(), rect.y() + 5, 48, 36)
            if not item.icon().isNull():
                item.icon().paint(p, icon_rect, Qt.AlignCenter)
            elif depth == 1:
                p.setPen(QPen(theme.qc(theme.BORDER), 1))
                p.drawRect(icon_rect.adjusted(0, 0, -1, -1))
            if selected and depth == 1:
                p.setPen(QPen(theme.qc(theme.ACCENT), 2))
                p.drawRect(icon_rect.adjusted(-2, -2, 2, 2))
            p.setFont(theme.font_for("prose", size=18 if rect.width() >= 360 else 16))
            p.setPen(theme.qc(theme.TEXT_STRONG))
            title = item.text(0)
            if depth == 1 and title.lower().endswith(" epithelium"):
                title = title[:-11]
            text_rect = QRectF(rect.left() + 64, rect.y(), max(1, rect.width() - 76 - count_width), rect.height())
            p.drawText(text_rect, Qt.AlignVCenter, QFontMetricsF(p.font()).elidedText(title, Qt.ElideRight, text_rect.width()))
            p.setPen(QPen(theme.qc(theme.BORDER_SUBTLE), 1))
            p.drawLine(rect.bottomLeft(), rect.bottomRight())
            if selected:
                p.setPen(QPen(theme.qc(theme.ACCENT), 2))
                underline_width = min(text_rect.width(), QFontMetricsF(p.font()).horizontalAdvance(title))
                p.drawLine(QPointF(text_rect.left(), rect.bottom() - 4),
                           QPointF(text_rect.left() + underline_width, rect.bottom() - 4))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        if bar.value() > 0:
            gradient = QLinearGradient(0, 0, 0, 86)
            gradient.setColorAt(0.0, theme.qc(palette["stage_top"]))
            gradient.setColorAt(1.0, theme.qc(palette["stage_top"], 0))
            p.fillRect(0, 0, self.viewport().width(), 86, gradient)
        if bar.value() < bar.maximum():
            gradient = QLinearGradient(0, height - 118, 0, height)
            gradient.setColorAt(0.0, theme.qc(palette["stage_bottom"], 0))
            gradient.setColorAt(1.0, theme.qc(palette["stage_bottom"]))
            p.fillRect(0, height - 118, self.viewport().width(), 118, gradient)
        p.end()


class TissuePreview(QLabel):
    """A tissue thumbnail that remains fitted as the detail column receives its layout size."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._source_pixmap = QPixmap()

    def set_source_pixmap(self, pixmap):
        self._source_pixmap = QPixmap(pixmap)
        self._fit_source_pixmap()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setFixedHeight(round(self.width() * .75))
        self._fit_source_pixmap()

    def _fit_source_pixmap(self):
        if self._source_pixmap.isNull():
            super().setPixmap(QPixmap())
            return
        scaled = self._source_pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        super().setPixmap(scaled)


class TissueGroupDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(180, 31)

    def paint(self, painter, option, index):
        painter.save()
        enabled = bool(option.state & QStyle.State_Enabled)
        if not enabled:
            painter.setOpacity(.42)
        painter.setFont(theme.font_for("body_small"))
        painter.setPen(theme.qc(theme.TEXT_STRONG if option.state & QStyle.State_Selected else theme.TEXT_2))
        rect = option.rect.adjusted(0, 0, -2, 0)
        title = index.data(Qt.DisplayRole) or ""
        painter.drawText(rect.adjusted(0, 0, -28, 0), Qt.AlignVCenter,
                         QFontMetricsF(painter.font()).elidedText(title, Qt.ElideRight, max(1, rect.width() - 28)))
        painter.setPen(theme.qc(theme.MUTED))
        painter.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, str(index.data(GROUP_COUNT_ROLE) or ""))
        if enabled and option.state & (QStyle.State_Selected | QStyle.State_HasFocus):
            painter.setPen(QPen(theme.qc(theme.ACCENT), 2))
            painter.drawLine(rect.left(), rect.bottom() - 1,
                             rect.left() + min(rect.width() - 28, round(QFontMetricsF(painter.font()).horizontalAdvance(title))),
                             rect.bottom() - 1)
        painter.restore()


def _histology_type(label, role):
    font = theme.font_for(role)
    label.setFont(font)
    label.setStyleSheet(f'font-family:"{font.family()}";font-size:{font.pixelSize()}px;'
                       f'font-weight:{font.weight()};color:{theme.TEXT_STRONG};background:transparent;')


class HistologyBrowser(QWidget):
    """A searchable, endless catalogue of tissues with a linked group rail."""

    imageRequested = Signal(str, int)
    structuresRequested = Signal(list)

    def __init__(self, ds, content, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.content = content
        self.setObjectName("histologyEndlessLibrary")
        self.setAccessibleName("Histology tissue and image library")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        tissues = content.histology["tissues"]
        n_img = sum(len(t.get("images", [])) for t in tissues)
        title = QLabel("Histology")
        _histology_type(title, "display")
        lay.addWidget(title)
        lay.addSpacing(6)
        head = QLabel(f"{len(tissues)} tissues · {n_img} micrographs")
        head.setFont(theme.font_for("ui"))
        head.setStyleSheet(f"color:{theme.TEXT_2};font-size:15px;background:transparent;")
        lay.addWidget(head)
        lay.addSpacing(42)
        browse = self.browse_layout = QHBoxLayout()
        browse.setContentsMargins(0, 0, 0, 0)
        browse.setSpacing(60)
        self.group_column = QWidget()
        self.group_column.setFixedWidth(250)
        group_layout = QVBoxLayout(self.group_column)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(8)
        group_head = QHBoxLayout()
        for text, stretch in (("Groups", 1), ("Tissues", 0)):
            label = QLabel(text)
            label.setFont(theme.font_for("meta", weight=600))
            group_head.addWidget(label, stretch)
        group_layout.addLayout(group_head)
        self.groups = QListWidget()
        self.groups.setAccessibleName("Histology tissue groups")
        self.groups.setItemDelegate(TissueGroupDelegate(self.groups))
        self.groups.setFrameShape(QFrame.NoFrame)
        self.groups.setStyleSheet("QListWidget,QListWidget::item,QListWidget::item:selected,QListWidget::item:hover "
                                  "{background:transparent;border:0;padding:0;}")
        self.groups.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.groups.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.groups.currentItemChanged.connect(self._group_selected)
        group_layout.addWidget(self.groups)
        filter_button = QPushButton("Filter tissues")
        theme.set_variant(filter_button, "ghost")
        filter_button.setCheckable(True)
        group_layout.addWidget(filter_button, 0, Qt.AlignLeft)
        self.filter_panel = QWidget()
        filter_layout = QVBoxLayout(self.filter_panel)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(8)
        self.filter = QLineEdit()
        self.filter.setAccessibleName("Search histology tissues and images")
        self.filter.setPlaceholderText("Search tissues, images or features…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._filter)
        filter_layout.addWidget(self.filter)
        self.clear_filter = control("Clear", "Clear histology search and filter")
        self.clear_filter.clicked.connect(self._reset_filter)
        filter_layout.addWidget(self.clear_filter, 0, Qt.AlignLeft)
        self.count_label = QLabel()
        self.count_label.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_CAPTION))
        filter_layout.addWidget(self.count_label)
        self.filter_panel.hide()
        filter_button.toggled.connect(self.filter_panel.setVisible)
        self.filter.textChanged.connect(lambda text: self.filter_panel.setVisible(bool(text) or filter_button.isChecked()))
        group_layout.addWidget(self.filter_panel)
        browse.addWidget(self.group_column)
        self.tree = HistologyCatalogue()
        self.tree.setAccessibleName("Histology tissues and images")
        self.tree.setIndentation(14)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemClicked.connect(self._select_item)
        self.tree.currentItemChanged.connect(lambda current, _previous: self._select_item(current))
        self.tree.itemActivated.connect(self._open_item)
        results = QVBoxLayout()
        results.setContentsMargins(0, 0, 0, 0)
        self.empty_state = QLabel("No matching content. Clear the filters or try another search.")
        self.empty_state.setWordWrap(True)
        self.empty_state.setStyleSheet(theme.text_css(theme.TEXT_2))
        results.addWidget(self.empty_state)
        results.addWidget(self.tree, 1)
        browse.addLayout(results, 1)
        self.detail = QWidget()
        self.detail.setFixedWidth(360)
        self.detail.setAccessibleName("Selected histology tissue preview")
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(12)
        self.preview = TissuePreview("Choose a tissue to see its micrograph and summary.")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setWordWrap(True)
        self.preview.setMinimumWidth(200)
        self.preview.setFixedHeight(270)
        self.preview.setStyleSheet(f"QLabel {{ background:transparent; color:{theme.MUTED};border:0; }}")
        detail_layout.addWidget(self.preview)
        self.preview_title = QLabel("Choose a tissue")
        self.preview_title.setWordWrap(True)
        _histology_type(self.preview_title, "card_title")
        detail_layout.addWidget(self.preview_title)
        self.preview_meta = QLabel("")
        self.preview_meta.setFont(theme.font_for("meta"))
        self.preview_meta.setStyleSheet(f"color:{theme.TEXT_2};font-size:13px;background:transparent;")
        detail_layout.addWidget(self.preview_meta)
        self.preview_summary = QLabel("")
        self.preview_summary.setWordWrap(True)
        self.preview_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.preview_summary.setFont(theme.font_for("body_small"))
        self.preview_summary.setStyleSheet(f"color:{theme.TEXT_2};font-size:14px;background:transparent;"
                                           f"border-top:1px solid {theme.BORDER};padding-top:12px;")
        detail_layout.addWidget(self.preview_summary)
        self.open_slides = QPushButton("Open slides")
        self.open_slides.setAccessibleName("Open selected tissue slides")
        theme.set_variant(self.open_slides, "primary")
        self.open_slides.setStyleSheet("QPushButton {padding:8px 14px;}")
        self.open_slides.setEnabled(False)
        self.open_slides.clicked.connect(self._open_selected)
        detail_layout.addWidget(self.open_slides, 0, Qt.AlignLeft)
        detail_layout.addStretch(1)
        browse.addWidget(self.detail)
        lay.addLayout(browse, 1)
        self._build()
        self.tree.verticalScrollBar().valueChanged.connect(self._sync_group)
        self._filter("")
        self._sync_group()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 1450
        self.group_column.setFixedWidth(170 if compact else 250)
        self.detail.setFixedWidth(280 if compact else 360)
        self.browse_layout.setSpacing(24 if compact else 60)

    def _build(self):
        top_groups = {}
        for t in self.content.histology["tissues"]:
            path = t.get("path") or ["Other"]
            group_name = path[0]
            parent = top_groups.get(group_name)
            if parent is None:
                parent = OutlineItem(self.tree.invisibleRootItem())
                parent.setText(0, group_name)
                parent.setBold(True)
                parent.setData(0, GROUP_ROLE, group_name)
                parent.setToolTip(0, group_name)
                parent.setExpanded(True)
                top_groups[group_name] = parent
            it = OutlineItem(parent)
            it.setText(0, t["name"])
            it.setText(1, str(len(t.get("images", []))) if t.get("images") else "No images")
            it.setData(0, ROLE, ("tissue", t["id"], 0))
            it.setToolTip(0, t.get("summary", ""))
            it.setData(0, SEARCH_ROLE, searchable_text(t.get("summary", ""), *t.get("features", []), *t.get("path", [])))
            if len(path) > 1:
                it.setToolTip(0, f"{' · '.join(path)}\n{t.get('summary', '')}")
            if t.get("images"):
                representative = next((img for img in t["images"] if not img.get("diagram")), t["images"][0])
                thumb = self.content.thumb_path(representative)
                it.setIcon(QIcon(str(thumb)))
                it.setToolTip(0, f"{t.get('summary', '')} · {len(t['images'])} micrographs. Open to browse slides.")
            for i, img in enumerate(t.get("images", [])):
                child = OutlineItem(it)
                child.setText(0, img["title"])
                child.setData(0, ROLE, ("image", t["id"], i))
                child.setToolTip(0, img.get("description", "")[:300])
        for name, group in top_groups.items():
            count = sum(len(t.get("images", [])) for t in self.content.histology["tissues"]
                        if (t.get("path") or ["Other"])[0] == name)
            group.setText(1, str(count))
            group.setToolTip(1, f"{count} slides in {name}")
            row = QListWidgetItem(name)
            tissue_count = sum((t.get("path") or ["Other"])[0] == name for t in self.content.histology["tissues"])
            row.setData(GROUP_COUNT_ROLE, tissue_count)
            row.setData(GROUP_ROLE, group)
            row.setToolTip(f"Browse {name}")
            self.groups.addItem(row)
        self._group_by_item = {id(item): name for name, item in top_groups.items()}

    def _group_selected(self, current, _previous=None):
        group = current.data(GROUP_ROLE) if current is not None else None
        if group is not None:
            self.tree.scrollToItem(group)

    def _sync_group(self, *_):
        if not self.groups.count():
            return
        current = None
        for i in range(self.groups.count()):
            row = self.groups.item(i)
            group = row.data(GROUP_ROLE)
            if group is None or group.isHidden():
                continue
            rect = self.tree.visualItemRect(group)
            # Follow the section crossing the viewport's leading edge. A loose
            # 48px threshold selected the *next* header when two short headers
            # both fell near the top of a compact window.
            if rect.top() <= 0:
                current = row
            elif current is None:
                current = row
                break
        if current is not None and current is not self.groups.currentItem():
            self.groups.blockSignals(True)
            self.groups.setCurrentItem(current)
            self.groups.blockSignals(False)

    def _tissue_item(self, item):
        while item is not None:
            data = item.data(0, ROLE)
            if data and data[0] == "tissue":
                return item
            item = item.parent()
        return None

    def _select_item(self, item, *_):
        tissue_item = self._tissue_item(item)
        data = tissue_item.data(0, ROLE) if tissue_item is not None else None
        tissue = self.content.tissues.get(data[1]) if data else None
        if tissue is None:
            self._selected_tissue = None
            self.preview.set_source_pixmap(QPixmap())
            self.preview.setText("Choose a tissue to see its micrograph and summary.")
            self.preview_title.setText("Choose a tissue")
            self.preview_meta.clear()
            self.preview_summary.clear()
            self.open_slides.setEnabled(False)
            return
        self._selected_tissue = tissue
        images = tissue.get("images", [])
        self.preview_title.setText(tissue["name"])
        self.preview_meta.setText(" · ".join([*(tissue.get("path") or []),
                                              f"{len(images)} slides" if images else "No slides"]))
        self.preview_summary.setText(tissue.get("summary", ""))
        pixmap = QPixmap()
        if images:
            pixmap.load(str(self.content.thumb_path(images[0])))
        if not pixmap.isNull():
            self.preview.setText("")
            self.preview.set_source_pixmap(pixmap)
        else:
            self.preview.set_source_pixmap(QPixmap())
            self.preview.setText("No micrograph preview is available for this tissue.")
        self.open_slides.setEnabled(bool(images))

    def _open_selected(self):
        tissue = getattr(self, "_selected_tissue", None)
        if tissue and tissue.get("images"):
            self.imageRequested.emit(tissue["id"], 0)

    def _open_item(self, item, _col=0):
        data = item.data(0, ROLE) if item is not None else None
        if data:
            if data[0] == "image":
                self.imageRequested.emit(data[1], data[2])
            else:
                self.imageRequested.emit(data[1], 0)

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
                if item.data(0, GROUP_ROLE):
                    item.setExpanded(not q or child_match)
                else:
                    item.setExpanded(bool(q) and child_match)
            if shown and data and data[0] == "tissue":
                visible += 1
            return shown

        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            rec(root.child(i))
        self.count_label.setText(f"{visible} tissues shown")
        self.empty_state.setVisible(visible == 0)
        self.detail.setVisible(visible > 0)
        self.clear_filter.setEnabled(bool(q))
        for i in range(self.groups.count()):
            row = self.groups.item(i)
            group = row.data(GROUP_ROLE)
            row.setFlags(row.flags() | Qt.ItemIsEnabled if group and not group.isHidden() else row.flags() & ~Qt.ItemIsEnabled)
        current_item = self.tree.currentItem()
        current_tissue = self._tissue_item(current_item)
        if current_item is None or current_item.isHidden() or current_tissue is None or current_tissue.isHidden():
            first = self._first_visible_tissue(prefer_image=not q)
            self.tree.setCurrentItem(first)
            if first is not None:
                self.tree.scrollToItem(first)
                self._select_item(first)
                parent = first.parent()
                for i in range(self.groups.count()):
                    row = self.groups.item(i)
                    if row.data(GROUP_ROLE) is parent:
                        self.groups.setCurrentItem(row)
                        break
            else:
                self._select_item(None)

    def _first_visible_tissue(self, prefer_image=False):
        root = self.tree.invisibleRootItem()
        first = None
        for i in range(root.childCount()):
            group = root.child(i)
            for j in range(group.childCount()):
                tissue = group.child(j)
                data = tissue.data(0, ROLE)
                if data and data[0] == "tissue" and not tissue.isHidden():
                    first = first or tissue
                    record = self.content.tissues.get(data[1], {})
                    if not prefer_image or record.get("images"):
                        return tissue
        return first


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
        self.labels = []              # [{"x", "y", "text"}] as fractions of the image: numbered marks on the slide
        self.show_labels = True
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

    def set_labels(self, labels):
        self.labels = [lab for lab in labels or [] if isinstance(lab, dict) and lab.get("text")
                       and 0 <= float(lab.get("x", -1)) <= 1 and 0 <= float(lab.get("y", -1)) <= 1]
        self.viewport().update()

    def _paint_labels(self, painter):
        """Labels drawn like an atlas plate, at a constant size on screen whatever the zoom: a small ring on the
        structure (it does not hide it), a fine leader line, and the number and name in a dark pill placed clear of
        the point, of the other labels and of the view's edges."""
        import math
        pix = self.item.pixmap()
        font = QFont(painter.font())
        font.setPointSizeF(max(9.5, font.pointSizeF()))
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        fm = QFontMetricsF(font)
        vw, vh = float(self.viewport().width()), float(self.viewport().height())
        # fixed colours: the labels sit on the slide, so they must read the same in the light and dark themes
        accent, on_accent, ink = theme.qc(theme.ACCENT), theme.qc(theme.ON_ACCENT), theme.qc(theme.TEXT_STRONG)
        points = [QPointF(self.mapFromScene(QPointF(float(lab["x"]) * pix.width(), float(lab["y"]) * pix.height())))
                  for lab in self.labels]
        middle = QPointF(vw / 2.0, vh / 2.0)
        height = fm.height() + 8.0
        pills = []                                          # (rect, badge width, number, text, point, anchor)
        for number, (lab, p) in enumerate(zip(self.labels, points), 1):
            text = str(lab["text"])
            badge = max(height, fm.horizontalAdvance(str(number)) + 12.0)
            width = badge + fm.horizontalAdvance(text) + 14.0
            outward = math.atan2(p.y() - middle.y(), p.x() - middle.x())
            chosen = fallback = None
            for distance in (44.0, 70.0, 100.0):
                for turn in (0, 30, -30, 60, -60, 90, -90, 125, -125, 180):
                    a = outward + math.radians(turn)
                    cx, cy = p.x() + distance * math.cos(a), p.y() + distance * math.sin(a)
                    left = cx if math.cos(a) >= 0 else cx - width
                    rect = QRectF(left, cy - height / 2.0, width, height)
                    if not (rect.left() >= 6 and rect.top() >= 6 and rect.right() <= vw - 6 and rect.bottom() <= vh - 6):
                        continue
                    fallback = fallback or rect
                    if (not any(rect.adjusted(-4, -4, 4, 4).intersects(r[0]) for r in pills) and
                            not any(rect.adjusted(-6, -6, 6, 6).contains(q) for q in points)):
                        chosen = rect
                        break
                if chosen is not None:
                    break
            best = chosen or fallback
            if best is None:                                # crowded: beside the point, kept in view
                left = min(max(p.x() + 14.0, 6.0), vw - width - 6.0)
                best = QRectF(left, min(max(p.y() - height / 2.0, 6.0), vh - height - 6.0), width, height)
            anchor = QPointF(best.left() if best.center().x() >= p.x() else best.right(), best.center().y())
            pills.append((best, badge, number, text, p, anchor))
        # leader lines first, so the rings and pills sit on top of them
        for rect, _badge, _n, _t, p, anchor in pills:
            dx, dy = anchor.x() - p.x(), anchor.y() - p.y()
            length = max(math.hypot(dx, dy), 1e-6)
            start = QPointF(p.x() + dx / length * 6.5, p.y() + dy / length * 6.5)
            painter.setPen(QPen(QColor(0, 0, 0, 150), 3.2, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(start, anchor)
            painter.setPen(QPen(QColor(255, 255, 255, 235), 1.4, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(start, anchor)
        for rect, badge, number, text, p, _anchor in pills:
            painter.setPen(QPen(QColor(0, 0, 0, 160), 3.6))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(p, 5.5, 5.5)
            painter.setPen(QPen(QColor(255, 255, 255), 1.8))
            painter.drawEllipse(p, 5.5, 5.5)
            painter.setPen(Qt.NoPen)
            painter.setBrush(accent)
            painter.drawEllipse(p, 2.2, 2.2)
            radius = rect.height() / 2.0
            painter.setBrush(QColor(0, 0, 0, 70))           # a soft shadow lifts the pill off any slide
            painter.drawRoundedRect(rect.translated(0, 1.5), radius, radius)
            painter.setBrush(QColor(16, 21, 28, 228))
            painter.setPen(QPen(QColor(255, 255, 255, 46), 1.0))
            painter.drawRoundedRect(rect, radius, radius)
            disc = QRectF(rect.left() + 3.0, rect.top() + 3.0, badge - 6.0, rect.height() - 6.0)
            painter.setPen(Qt.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(disc, disc.height() / 2.0, disc.height() / 2.0)
            painter.setPen(on_accent)
            painter.drawText(disc, Qt.AlignCenter, str(number))
            painter.setPen(ink)
            painter.drawText(QRectF(rect.left() + badge + 2.0, rect.top(), rect.width() - badge - 8.0, rect.height()),
                             Qt.AlignVCenter | Qt.AlignLeft, text)

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if self.labels and self.show_labels and not self.item.pixmap().isNull():
            painter.save()
            painter.resetTransform()
            painter.setRenderHint(QPainter.Antialiasing)
            self._paint_labels(painter)
            painter.restore()
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
        lay.setContentsMargins(24, 96, 24, 10)
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
        self.labels_box = QCheckBox("Labels")
        self.labels_box.setChecked(True)
        self.labels_box.setToolTip("Show the numbered labels on this slide")
        self.labels_box.toggled.connect(self._toggle_labels)
        for widget in (self.fit_image, self.actual_image, self.zoom_out, self.zoom_label, self.zoom_in, self.labels_box):
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
        self.caption.setStyleSheet(
            f"QTextBrowser {{ background: {theme.SURFACE}; color: {CARD_TEXT}; "
            f"border: 1px solid {theme.BORDER_SUBTLE}; border-radius: {theme.R_MD}px; }}")
        self.caption.setAccessibleName("Histology image caption and credit")
        self.caption.setMinimumHeight(100)
        self.caption.document().setDefaultStyleSheet(
            f"body{{color:{CARD_TEXT};}} .muted{{color:{CARD_MUTED};}} "
            f"a{{color:{theme.ACCENT_TEXT};text-decoration:underline;}} h3{{margin:0;color:{CARD_TEXT};}}")
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
        labels = img.get("labels") or []
        self.view.set_labels([])
        self.labels_box.setVisible(bool(labels))
        if labels:
            desc += "<p class='overline'>LABELS</p><p>" + " · ".join(
                f"<b>{n}</b> {esc(lab.get('text'))}" for n, lab in enumerate(labels, 1)) + "</p>"
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
            self.view.set_labels(self.tissue["images"][self.index].get("labels"))
            title = self.tissue["images"][self.index]["title"]
            self.view.setAccessibleDescription(f"{title}. Use plus and minus to zoom, Home to fit, Page Up and Page Down to change images.")
            self.image_status.setText("Original image colours and labels · + / − to zoom · Drag to pan · Home to fit")
            self.retry_image.hide()
            self._set_controls(True)

    def _toggle_labels(self, on):
        self.view.show_labels = bool(on)
        self.view.viewport().update()

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
        return title, bits, credit or "Layered Human · Histology"
