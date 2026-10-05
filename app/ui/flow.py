"""Width-aware native controls shared by study toolbars and answer lists."""
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (QCheckBox, QLayout, QPushButton, QSizePolicy, QStyle,
                               QStyleOptionButton, QStylePainter)


class FlowLayout(QLayout):
    """Wrap visible controls without allowing a long control to widen its host."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self._spacing = max(0, spacing)
        self._right = set()
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)
        self.invalidate()

    def add_right(self, widget):
        self.addWidget(widget)
        self._right.add(len(self._items) - 1)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        if 0 <= i < len(self._items):
            self._right = {j - (j > i) for j in self._right if j != i}
            item = self._items.pop(i)
            self.invalidate()
            return item
        return None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize(0, 0)
        for item in self._items:
            if item.widget() is not None and item.widget().isHidden():
                continue
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect, apply):
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        width = max(0, area.width())
        rows, row, used = [], [], 0
        for i, item in enumerate(self._items):
            if item.widget() is not None and item.widget().isHidden():
                continue
            w = max(0, min(item.sizeHint().width(), width))
            h = item.heightForWidth(w) if item.hasHeightForWidth() else item.sizeHint().height()
            h = max(0, h, item.minimumSize().height())
            if row and used + self._spacing + w > width:
                rows.append(row)
                row, used = [], 0
            if row:
                used += self._spacing
            row.append((i, item, QSize(w, h)))
            used += w
        if row:
            rows.append(row)
        y = area.y()
        for row in rows:
            h = max(sz.height() for _i, _item, sz in row)
            left = [entry for entry in row if entry[0] not in self._right]
            right = [entry for entry in row if entry[0] in self._right]
            x = area.x()
            for _i, item, sz in left:
                if apply:
                    item.setGeometry(QRect(QPoint(x, y + (h - sz.height()) // 2), sz))
                x += sz.width() + self._spacing
            x = area.x() + width
            for _i, item, sz in reversed(right):
                x -= sz.width()
                if apply:
                    item.setGeometry(QRect(QPoint(x, y + (h - sz.height()) // 2), sz))
                x -= self._spacing
            y += h + self._spacing
        return y - self._spacing - rect.y() + m.bottom() if rows else m.top() + m.bottom()


class WrapButton(QPushButton):
    """A real keyboard/screen-reader button whose full answer wraps at any width."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        metrics = QFontMetrics(self.font())
        bounds = metrics.boundingRect(QRect(0, 0, max(20, width - 28), 10000),
                                      Qt.TextWordWrap | Qt.AlignLeft, self.text())
        return max(self.minimumHeight(), 40, bounds.height() + 20)

    def sizeHint(self):
        metrics = QFontMetrics(self.font())
        # A single word cannot wrap at spaces. Account for the custom painter's
        # horizontal padding even when the native style caches a narrower hint.
        longest = max((metrics.horizontalAdvance(word) for word in self.text().split()), default=0)
        width = min(320, max(100, super().sizeHint().width(), longest + 28))
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self):
        return QSize(80, max(40, self.minimumHeight()))

    def setText(self, text):
        super().setText(text)
        self.setAccessibleName(text)
        self.updateGeometry()

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        painter = QStylePainter(self)
        painter.drawControl(QStyle.CE_PushButton, option)
        area = self.rect().adjusted(14, 8, -14, -8)
        self.style().drawItemText(painter, area, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap,
                                  option.palette, self.isEnabled(), self.text(),
                                  self.foregroundRole())


class WrapCheckBox(QCheckBox):
    """Native checkbox state and hit testing, with an untruncated multiline label."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        metrics = QFontMetrics(self.font())
        bounds = metrics.boundingRect(QRect(0, 0, max(20, width - 32), 10000),
                                      Qt.TextWordWrap | Qt.AlignLeft, self.text())
        return max(28, bounds.height() + 8)

    def sizeHint(self):
        width = min(320, max(100, super().sizeHint().width()))
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self):
        return QSize(80, 28)

    def hitButton(self, position):
        return self.rect().contains(position)

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        painter = QStylePainter(self)
        painter.drawControl(QStyle.CE_CheckBox, option)
        area = self.style().subElementRect(QStyle.SE_CheckBoxContents, option, self).adjusted(2, 3, -2, -3)
        self.style().drawItemText(painter, area, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap,
                                  option.palette, self.isEnabled(), self.text(), self.foregroundRole())
