"""Readable, width-aware native catalog rows with keyboard and accessible text."""
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate

from . import theme

ROLE_KIND = Qt.UserRole + 20
ROLE_TITLE = Qt.UserRole + 21
ROLE_SUMMARY = Qt.UserRole + 22
ROLE_BADGE = Qt.UserRole + 23
ROLE_ACCENT = Qt.UserRole + 24
ROLE_DIM = Qt.UserRole + 25
ROLE_PROGRESS = Qt.UserRole + 26
ROLE_DONE = Qt.UserRole + 27

MARGIN_X, PAD_L, PAD_R, PAD_T, PAD_B = 2, 12, 12, 12, 12
TEXT_L, STRIPE, GAP, MAX_LINES, TITLE_LINES = PAD_L, 0, 5, 3, 3


def _wrap(text, fm, width, max_lines=MAX_LINES):
    """Wrap prose, including long IDs/URLs, and elide only the final visible line."""
    width = max(1.0, float(width))
    lines, current = [], ""
    for word in str(text or "").split():
        trial = f"{current} {word}".strip()
        if current and fm.horizontalAdvance(trial) > width:
            lines.append(current)
            current = ""
        while word and fm.horizontalAdvance(word) > width:
            count = 1
            while count < len(word) and fm.horizontalAdvance(word[:count + 1]) <= width:
                count += 1
            lines.append(word[:count])
            word = word[count:]
        current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = fm.elidedText(lines[-1] + " …", Qt.ElideRight, int(width))
    return lines


class CardDelegate(QStyledItemDelegate):
    def __init__(self, view, compact=False):
        super().__init__(view)
        self.view, self.compact = view, compact

    def _fonts(self, option):
        base = max(theme.FS_BODY, option.font.pointSizeF())
        title, sub, badge = QFont(option.font), QFont(option.font), QFont(option.font)
        title.setBold(True)
        title.setPointSizeF(base + (0 if self.compact else 0.5))
        sub.setPointSizeF(max(theme.FS_SMALL, base - 0.5))
        badge.setPointSizeF(max(theme.FS_SMALL, base - 1.0))
        return title, sub, badge

    def _width(self):
        return max(40, self.view.viewport().width())

    def _metrics(self, option, index):
        fonts = self._fonts(option)
        avail = max(1, self._width() - PAD_L - PAD_R - 2 * MARGIN_X)
        title = _wrap(index.data(ROLE_TITLE), QFontMetricsF(fonts[0]), avail, TITLE_LINES) or [""]
        summary = _wrap(index.data(ROLE_SUMMARY), QFontMetricsF(fonts[1]), avail)
        badge = index.data(ROLE_BADGE) or ""
        status = "Finished" if index.data(ROLE_DONE) else ""
        fraction = max(0.0, min(1.0, float(index.data(ROLE_PROGRESS) or 0)))
        if not status and fraction:
            status = f"{round(fraction * 100)}% read"
        footer = " · ".join(x for x in (badge, status) if x)
        foot = _wrap(footer, QFontMetricsF(fonts[2]), avail, 2)
        return fonts, avail, title, summary, foot

    def sizeHint(self, option, index):
        width = self._width()
        kind = index.data(ROLE_KIND)
        if kind in ("header", "note"):
            fm = QFontMetricsF(option.font)
            lines = _wrap(index.data(Qt.DisplayRole), fm, width - 2 * PAD_L, 4)
            return QSize(width, int(max(1, len(lines)) * fm.lineSpacing()) + (24 if kind == "header" else 32))
        fonts, _avail, titles, summaries, footer = self._metrics(option, index)
        height = PAD_T + PAD_B + len(titles) * QFontMetricsF(fonts[0]).lineSpacing()
        for lines, font in ((summaries, fonts[1]), (footer, fonts[2])):
            if lines:
                height += GAP + len(lines) * QFontMetricsF(font).lineSpacing()
        if index.data(ROLE_DONE) or index.data(ROLE_PROGRESS):
            height += 6
        return QSize(width, int(height) + 4)

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setClipRect(option.rect)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        rect = QRectF(option.rect)
        kind = index.data(ROLE_KIND) or "card"
        if kind in ("header", "note"):
            font = QFont(option.font)
            font.setBold(kind == "header")
            painter.setFont(font)
            painter.setPen(theme.qc(theme.TEXT_2 if kind == "header" else theme.MUTED))
            painter.drawText(rect.adjusted(PAD_L, 12, -PAD_R, -4), Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap,
                             index.data(Qt.DisplayRole) or "")
        else:
            self._paint_card(painter, option, rect, index)
        painter.restore()

    def _paint_card(self, painter, option, rect, index):
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        focused = bool(option.state & QStyle.State_HasFocus)
        dim = bool(index.data(ROLE_DIM))
        card = rect.adjusted(MARGIN_X, 2, -MARGIN_X, -2)
        fill = theme.ACCENT_SOFT if selected else theme.HOVER if hover else theme.RAISED
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.qc(fill))
        painter.drawRoundedRect(card.adjusted(1, 1, -1, -1), theme.R_MD, theme.R_MD)
        fonts, avail, titles, summaries, footer = self._metrics(option, index)
        x, y = card.x() + PAD_L, card.y() + PAD_T
        for lines, font, color in ((titles, fonts[0], theme.TEXT_2 if dim else theme.TEXT_STRONG),
                                    (summaries, fonts[1], theme.TEXT_2),
                                    (footer, fonts[2], theme.ACCENT_TEXT if selected else theme.MUTED)):
            if not lines:
                continue
            painter.setFont(font)
            painter.setPen(theme.qc(color))
            line_height = QFontMetricsF(font).lineSpacing()
            for line in lines:
                painter.drawText(QRectF(x, y, avail, line_height), Qt.AlignLeft | Qt.AlignVCenter, line)
                y += line_height
            y += GAP
        done = bool(index.data(ROLE_DONE))
        fraction = 1.0 if done else max(0.0, min(1.0, float(index.data(ROLE_PROGRESS) or 0)))
        if fraction:
            track = QRectF(x, card.bottom() - 6, avail, 3)
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.qc(theme.BORDER))
            painter.drawRoundedRect(track, 1.5, 1.5)
            painter.setBrush(theme.qc(theme.SUCCESS if done else theme.ACCENT))
            painter.drawRoundedRect(QRectF(track.x(), track.y(), track.width() * fraction, track.height()), 1.5, 1.5)


class CardList(QListWidget):
    """List semantics, real selection/focus and wrapping subject rows."""

    def __init__(self, parent=None, compact=False, collapsible=False):
        super().__init__(parent)
        self.collapsible = collapsible
        self._expanded_groups = set()
        self._group_header = None
        self.itemClicked.connect(self._toggle_group)
        self.setItemDelegate(CardDelegate(self, compact=compact))
        self.setMouseTracking(True)
        self.setUniformItemSizes(False)
        self.setWordWrap(False)
        self.setSpacing(2)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setStyleSheet("QListWidget::item, QListWidget::item:hover, QListWidget::item:selected "
                           "{ background: transparent; }")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.scheduleDelayedItemsLayout()

    def keyPressEvent(self,event):
        item=self.currentItem()
        if self.collapsible and item is not None and item.data(ROLE_KIND)=="header" and event.key() in (Qt.Key_Return,Qt.Key_Enter,Qt.Key_Space):
            self._toggle_group(item)
            event.accept()
            return
        super().keyPressEvent(event)

    def clear(self):
        self._group_header = None
        super().clear()

    def _toggle_group(self, item):
        if not self.collapsible or item.data(ROLE_KIND) != "header":
            return
        title = item.data(ROLE_TITLE)
        expanded = title not in self._expanded_groups
        if expanded:self._expanded_groups.add(title)
        else:self._expanded_groups.discard(title)
        item.setText(("▾ " if expanded else "▸ ") + title)
        for row in range(self.row(item)+1,self.count()):
            child=self.item(row)
            if child.data(ROLE_KIND)=="header":break
            child.setHidden(not expanded)
        self.scheduleDelayedItemsLayout()

    def add_header(self, text):
        item = QListWidgetItem(text)
        item.setFlags(Qt.NoItemFlags)
        item.setData(ROLE_KIND, "header")
        if self.collapsible:
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            item.setData(ROLE_TITLE,text)
            item.setText(("▾ " if text in self._expanded_groups else "▸ ")+text)
            item.setToolTip("Expand or collapse this group")
            self._group_header=text
        self.addItem(item)
        return item

    def add_note(self, text):
        item = QListWidgetItem(text)
        item.setFlags(Qt.NoItemFlags)
        item.setData(ROLE_KIND, "note")
        self.addItem(item)
        return item

    def add_card(self, title, summary="", badge="", accent=None, data=None, tooltip="", dim=False,
                 progress=0.0, done=False):
        item = QListWidgetItem(title)
        for role, value in ((ROLE_KIND, "card"), (ROLE_TITLE, title), (ROLE_SUMMARY, summary),
                            (ROLE_BADGE, badge), (ROLE_ACCENT, accent), (ROLE_DIM, dim),
                            (ROLE_DONE, done), (ROLE_PROGRESS, max(0.0, min(1.0, float(progress))))):
            item.setData(role, value)
        if data is not None:
            item.setData(Qt.UserRole, data)
        status = "Finished" if done else f"{round(progress * 100)}% read" if progress else ""
        accessible = ". ".join(str(x) for x in (title, summary, badge, status) if x)
        item.setData(Qt.AccessibleTextRole, accessible)
        item.setData(Qt.AccessibleDescriptionRole, tooltip or accessible)
        item.setToolTip(tooltip or accessible)
        self.addItem(item)
        if self.collapsible and self._group_header is not None:
            item.setHidden(self._group_header not in self._expanded_groups)
        return item
