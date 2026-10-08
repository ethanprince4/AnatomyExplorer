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
ROLE_LEVEL = Qt.UserRole + 28
ROLE_GROUP_KEY = Qt.UserRole + 29

# Every role a row can carry; a reused row is rewritten across all of them (see CardList.clear).
ROW_ROLES = (Qt.DisplayRole, Qt.ToolTipRole, Qt.AccessibleTextRole, Qt.AccessibleDescriptionRole, Qt.UserRole,
             ROLE_KIND, ROLE_TITLE, ROLE_SUMMARY, ROLE_BADGE, ROLE_ACCENT, ROLE_DIM, ROLE_PROGRESS, ROLE_DONE,
             ROLE_LEVEL, ROLE_GROUP_KEY)
DEFAULT_FLAGS = Qt.ItemIsSelectable | Qt.ItemIsEnabled

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
        indent = max(0, (index.data(ROLE_LEVEL) or 0) - 1) * 16
        avail = max(1, self._width() - PAD_L - PAD_R - 2 * MARGIN_X - indent)
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
            text = index.data(Qt.DisplayRole) or ""
            inset = PAD_L
            if kind == "header" and self.view.collapsible:
                inset += (index.data(ROLE_LEVEL) or 0) * 16
                x, y = int(rect.left() + inset + 4), int(rect.center().y() + 4)
                expanded = index.data(ROLE_GROUP_KEY) in self.view._expanded_groups
                painter.setPen(QPen(theme.qc(theme.TEXT_2), 1.5))
                if expanded:
                    painter.drawLine(x - 3, y - 2, x, y + 1)
                    painter.drawLine(x, y + 1, x + 3, y - 2)
                else:
                    painter.drawLine(x - 2, y - 3, x + 1, y)
                    painter.drawLine(x + 1, y, x - 2, y + 3)
                inset += 16
                text = index.data(ROLE_TITLE) or text
            painter.drawText(rect.adjusted(inset, 12, -PAD_R, -4), Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap,
                             text)
        else:
            self._paint_card(painter, option, rect, index)
        painter.restore()

    def _paint_card(self, painter, option, rect, index):
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        focused = bool(option.state & QStyle.State_HasFocus)
        dim = bool(index.data(ROLE_DIM))
        indent = max(0, (index.data(ROLE_LEVEL) or 0) - 1) * 16
        card = rect.adjusted(MARGIN_X + indent, 2, -MARGIN_X, -2)
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
        self._group_path = []
        self._used = 0
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
        """Start a rebuild. Rows are hidden for reuse rather than removed: these lists are rebuilt on every filter
        keystroke and case step while on screen, and removing rows can crash Qt's macOS accessibility bridge (see
        stable_rows). Python callers see count() as the rows in use, as after a real clear."""
        self._group_header = None
        self._group_path = []
        self._used = 0
        self.selectionModel().reset()        # like a model reset: no current row, and no signals
        for row in range(super().count()):
            item = self.item(row)
            self._rewrite(item, {}, Qt.NoItemFlags)
            item.setHidden(True)
        self.scheduleDelayedItemsLayout()

    def count(self):
        return self._used

    def _row(self, values, flags=DEFAULT_FLAGS):
        """The next row of the rebuild, reused when one is spare, holding exactly these role values."""
        if self._used < super().count():
            item = self.item(self._used)
        else:
            item = QListWidgetItem()
            self.addItem(item)
        self._used += 1
        self._rewrite(item, values, flags)
        item.setHidden(False)
        return item

    @staticmethod
    def _rewrite(item, values, flags):
        # Only roles that change are written, so refilling an unchanged list notifies nobody.
        for role in ROW_ROLES:
            value = values.get(role)
            if item.data(role) != value:
                item.setData(role, value)
        if item.flags() != flags:
            item.setFlags(flags)

    def _toggle_group(self, item):
        if not self.collapsible or item.data(ROLE_KIND) != "header":
            return
        key = item.data(ROLE_GROUP_KEY)
        if key in self._expanded_groups:
            self._expanded_groups.discard(key)
        else:
            self._expanded_groups.add(key)
        self._refresh_groups()

    def _refresh_groups(self):
        ancestors = []
        for row in range(self._used):
            item = self.item(row)
            level = item.data(ROLE_LEVEL) or 0
            ancestors = ancestors[:level]
            item.setHidden(any(key not in self._expanded_groups for key in ancestors))
            if item.data(ROLE_KIND) == "header":
                key = item.data(ROLE_GROUP_KEY)
                item.setText("    " * level + ("▾ " if key in self._expanded_groups else "▸ ") + item.data(ROLE_TITLE))
                ancestors.append(key)
        self.scheduleDelayedItemsLayout()

    def add_header(self, text, level=0, key=None):
        values = {Qt.DisplayRole: text, ROLE_KIND: "header", ROLE_LEVEL: level}
        flags = Qt.NoItemFlags
        if self.collapsible:
            key = key or text
            flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            values.update({Qt.DisplayRole: "    " * level + ("▾ " if key in self._expanded_groups else "▸ ") + text,
                           ROLE_TITLE: text, ROLE_GROUP_KEY: key, Qt.ToolTipRole: "Expand or collapse this group"})
            self._group_path = self._group_path[:level] + [key]
            self._group_header = key
        item = self._row(values, flags)
        if self.collapsible:
            item.setHidden(any(k not in self._expanded_groups for k in self._group_path[:-1]))
        return item

    def add_note(self, text):
        return self._row({Qt.DisplayRole: text, ROLE_KIND: "note"}, Qt.NoItemFlags)

    def add_card(self, title, summary="", badge="", accent=None, data=None, tooltip="", dim=False,
                 progress=0.0, done=False):
        status = "Finished" if done else f"{round(progress * 100)}% read" if progress else ""
        accessible = ". ".join(str(x) for x in (title, summary, badge, status) if x)
        item = self._row({Qt.DisplayRole: title, ROLE_KIND: "card", ROLE_TITLE: title, ROLE_SUMMARY: summary,
                          ROLE_BADGE: badge, ROLE_ACCENT: accent, ROLE_DIM: dim, ROLE_DONE: done,
                          ROLE_PROGRESS: max(0.0, min(1.0, float(progress))), Qt.UserRole: data,
                          Qt.AccessibleTextRole: accessible, Qt.AccessibleDescriptionRole: tooltip or accessible,
                          Qt.ToolTipRole: tooltip or accessible})
        if self.collapsible and self._group_header is not None:
            item.setData(ROLE_LEVEL, len(self._group_path))
            item.setHidden(any(k not in self._expanded_groups for k in self._group_path))
        return item
