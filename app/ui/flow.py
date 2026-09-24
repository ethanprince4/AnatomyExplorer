"""A layout that wraps its widgets onto another row when they run out of width, like words in a paragraph.

Used for control bars that would otherwise force a minimum window width wider than a laptop screen.
"""
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self._right = set()          # indices of items pushed to the right-hand end of their row

    # ------------------------------------------------------------------ QLayout plumbing
    def addItem(self, item):
        self._items.append(item)

    def add_right(self, widget):
        """Add a widget that sits flush right on its row (where a stretch would put it in a box layout)."""
        self.addWidget(widget)
        self._right.add(len(self._items) - 1)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        if 0 <= i < len(self._items):
            self._right = {j - (j > i) for j in self._right if j != i}
            return self._items.pop(i)
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
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    # ------------------------------------------------------------------ placement
    def _layout(self, rect, apply):
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        rows, row, x = [], [], 0
        for i, item in enumerate(self._items):
            if item.widget() is not None and item.widget().isHidden():
                continue
            w = item.sizeHint().width()
            if row and x + w > area.width():
                rows.append(row)
                row, x = [], 0
            row.append((i, item))
            x += w + self._spacing
        if row:
            rows.append(row)
        y = area.y()
        for row in rows:
            h = max(item.sizeHint().height() for _i, item in row)
            left = [(i, it) for i, it in row if i not in self._right]
            right = [(i, it) for i, it in row if i in self._right]
            x = area.x()
            for _i, item in left:
                sz = item.sizeHint()
                if apply:
                    item.setGeometry(QRect(QPoint(x, y + (h - sz.height()) // 2), sz))
                x += sz.width() + self._spacing
            x = area.right() + 1
            for _i, item in reversed(right):
                sz = item.sizeHint()
                x -= sz.width()
                if apply:
                    item.setGeometry(QRect(QPoint(x, y + (h - sz.height()) // 2), sz))
                x -= self._spacing
            y += h + self._spacing
        return y - self._spacing - rect.y() + m.bottom() if rows else m.top() + m.bottom()

