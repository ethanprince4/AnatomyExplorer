"""A self-drawn outline for the side panels: rows with expand arrows, check boxes and a muted count column.

Qt's tree widgets hand every row to the platform accessibility layer as a table cell. On macOS that bridge crashed while
a branch expanded (v4.0.4: NSRangeException in QMacAccessibilityElement, a row index of -1 read from an array). This
widget paints its rows itself and exposes no table to accessibility, so expanding, collapsing or filtering never goes
through that code. Its API is the part of QTreeWidget the panels used: items with text, data, a tooltip, a check state
and expansion, and the itemChanged / itemClicked / itemActivated / itemExpanded / itemCollapsed signals. Clicking an
arrow or a check box only expands or checks; itemClicked is for a click on the row itself. Screen readers hear the
current row through the widget's accessible description.
"""
from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractScrollArea, QToolTip

from . import theme

ARROW = 16          # width of the expand-arrow slot
BOX = 13            # check box side
GAP = 6             # space after the check box and before the count column


class OutlineItem:
    """One row. Created under a parent row, the outline itself (a top-level row) or nothing (attach later)."""

    def __init__(self, parent=None):
        self._parent = None
        self._view = None
        self._children = []
        self._text = ["", ""]
        self._data = {}
        self._tip = ""
        self._check = None             # None: no check box
        self._bold = False
        self._expanded = False
        self._hidden = False
        if isinstance(parent, Outline):
            parent = parent.invisibleRootItem()
        if parent is not None:
            parent.addChild(self)

    # tree
    def addChild(self, item):
        item._parent = self
        self._children.append(item)
        self._layout_changed()

    def child(self, index):
        return self._children[index] if 0 <= index < len(self._children) else None

    def childCount(self):
        return len(self._children)

    def indexOfChild(self, item):
        try:
            return self._children.index(item)
        except ValueError:
            return -1

    def parent(self):
        """The parent row, or None for a top-level row (as QTreeWidgetItem.parent())."""
        p = self._parent
        return None if p is None or p._view is not None else p

    def view(self):
        node = self
        while node._parent is not None:
            node = node._parent
        return node._view

    # content
    def text(self, column=0):
        return self._text[column] if 0 <= column < 2 else ""

    def setText(self, column, text):
        self._text[column] = str(text)
        self._update()

    def data(self, column, role):
        return self._data.get(role)

    def setData(self, column, role, value):
        self._data[role] = value

    def toolTip(self, column=0):
        return self._tip

    def setToolTip(self, column, text):
        self._tip = str(text or "")

    def setBold(self, on):
        self._bold = bool(on)
        self._update()

    def isBold(self):
        return self._bold

    def setCheckable(self, on):
        if on and self._check is None:
            self._check = Qt.Checked
        elif not on:
            self._check = None
        self._update()

    def isCheckable(self):
        return self._check is not None

    def checkState(self, column=0):
        return Qt.Unchecked if self._check is None else self._check

    def setCheckState(self, column, state):
        state = Qt.CheckState(state)
        if self._check == state:
            return
        self._check = state
        view = self.view()
        if view is not None:
            view.viewport().update()
            view._row_changed(self)
            if not view.signalsBlocked():
                view.itemChanged.emit(self, 0)

    def isExpanded(self):
        return self._expanded

    def setExpanded(self, on):
        on = bool(on)
        if self._expanded == on:
            return
        self._expanded = on
        view = self.view()
        self._layout_changed()
        if view is not None:
            view._row_changed(self)
            if not view.signalsBlocked():
                (view.itemExpanded if on else view.itemCollapsed).emit(self)

    def isHidden(self):
        return self._hidden

    def setHidden(self, hidden):
        hidden = bool(hidden)
        if self._hidden != hidden:
            self._hidden = hidden
            self._layout_changed()

    def has_visible_children(self):
        return any(not c._hidden for c in self._children)

    def _update(self):
        view = self.view()
        if view is not None:
            view.viewport().update()

    def _layout_changed(self):
        view = self.view()
        if view is not None:
            view._invalidate()


class Outline(QAbstractScrollArea):
    itemChanged = Signal(object, int)
    itemClicked = Signal(object, int)
    itemActivated = Signal(object, int)
    itemExpanded = Signal(object)
    itemCollapsed = Signal(object)
    currentItemChanged = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("outline", True)              # styled with the lists in theme.py
        self.setFocusPolicy(Qt.StrongFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.viewport().setMouseTracking(True)
        self._relayout_timer = QTimer(self)            # owned, so a deleted outline never runs it
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.timeout.connect(self._ensure_layout)
        self._root = OutlineItem()
        self._root._view = self
        self._rows = None              # [(item, depth)] of the rows on screen, in order
        self._index = {}               # id(item) -> row
        self._current = None
        self._selected = False
        self._hover = None
        self._pressed = None
        self._indent = 14

    # ------------------------------------------------------------------ QTreeWidget-like API
    def invisibleRootItem(self):
        return self._root

    def topLevelItem(self, index):
        return self._root.child(index)

    def topLevelItemCount(self):
        return self._root.childCount()

    def clear(self):
        previous = self._current
        for item in self._root._children:
            item._parent = None                       # detached rows no longer reach this outline
        self._root._children = []
        self._current, self._selected, self._hover, self._pressed = None, False, None, None
        self._invalidate()
        if previous is not None and not self.signalsBlocked():
            self.currentItemChanged.emit(None, previous)

    def setIndentation(self, pixels):
        self._indent = int(pixels)
        self.viewport().update()

    def indentation(self):
        return self._indent

    def currentItem(self):
        return self._current

    def setCurrentItem(self, item):
        previous = self._current
        self._current = item
        self._selected = item is not None
        self.viewport().update()
        if item is not previous:
            self._describe(item)
            if not self.signalsBlocked():
                self.currentItemChanged.emit(item, previous)

    def selectedItems(self):
        return [self._current] if self._selected and self._current is not None else []

    def clearSelection(self):
        self._selected = False
        self.viewport().update()

    def scrollToItem(self, item):
        """Open the rows above an item and scroll it into view."""
        if item is None:
            return
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self._ensure_layout()
        row = self._index.get(id(item))
        if row is None:
            return
        h, bar = self.rowHeight(), self.verticalScrollBar()
        top, bottom = row * h, (row + 1) * h
        if top < bar.value():
            bar.setValue(top)
        elif bottom > bar.value() + self.viewport().height():
            bar.setValue(bottom - self.viewport().height())

    def itemAt(self, pos):
        """The row under a point in viewport coordinates, or None."""
        self._ensure_layout()
        row = (int(pos.y()) + self.verticalScrollBar().value()) // self.rowHeight()
        return self._rows[row][0] if 0 <= row < len(self._rows) and pos.y() >= 0 else None

    def visualItemRect(self, item):
        self._ensure_layout()
        row = self._index.get(id(item))
        if row is None:
            return QRect()
        h = self.rowHeight()
        return QRect(0, row * h - self.verticalScrollBar().value(), self.viewport().width(), h)

    def rowHeight(self):
        return max(QFontMetrics(self.font()).height() + 8, BOX + 9)

    def sizeHintForRow(self, row):
        return self.rowHeight()

    def visibleRowCount(self):
        self._ensure_layout()
        return len(self._rows)

    # ------------------------------------------------------------------ layout
    def _invalidate(self):
        """Rows changed: recount them (and the scroll range) once control returns to the event loop."""
        self._rows = None
        self.viewport().update()
        if not self._relayout_timer.isActive():
            self._relayout_timer.start(0)

    def _ensure_layout(self):
        if self._rows is not None:
            return
        rows = []
        stack = [(c, 0) for c in reversed(self._root._children)]
        while stack:
            item, depth = stack.pop()
            if item._hidden:
                continue
            rows.append((item, depth))
            if item._expanded:
                stack.extend((c, depth + 1) for c in reversed(item._children))
        self._rows = rows
        self._index = {id(item): n for n, (item, _depth) in enumerate(rows)}
        self._update_scrollbar()

    def _update_scrollbar(self):
        h = self.rowHeight()
        bar = self.verticalScrollBar()
        total = len(self._rows or ()) * h
        bar.setRange(0, max(0, total - self.viewport().height()))
        bar.setPageStep(max(h, self.viewport().height()))
        bar.setSingleStep(h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._ensure_layout()
        self._update_scrollbar()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.FontChange and self._rows is not None:
            self._update_scrollbar()

    def scrollContentsBy(self, dx, dy):
        self.viewport().update()

    # ------------------------------------------------------------------ geometry of one row
    def _x0(self, depth):
        return 4 + depth * self._indent

    def _zone(self, item, depth, x):
        """'arrow', 'check' or 'row' for a click at x on an item's row."""
        x0 = self._x0(depth)
        if x0 <= x < x0 + ARROW and item.has_visible_children():
            return "arrow"
        if item._check is not None and x0 + ARROW - 2 <= x < x0 + ARROW + BOX + 4:
            return "check"
        return "row"

    def _hit(self, pos):
        self._ensure_layout()
        row = (int(pos.y()) + self.verticalScrollBar().value()) // self.rowHeight()
        if pos.y() < 0 or not 0 <= row < len(self._rows):
            return None, None
        item, depth = self._rows[row]
        return item, self._zone(item, depth, pos.x())

    # ------------------------------------------------------------------ painting
    def paintEvent(self, event):
        self._ensure_layout()
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        width = self.viewport().width()
        p.fillRect(event.rect(), theme.qc(theme.SURFACE))
        h = self.rowHeight()
        top = self.verticalScrollBar().value()
        first = max(0, (event.rect().top() + top) // h)
        last = min(len(self._rows), (event.rect().bottom() + top) // h + 1)
        base = self.font()
        bold = self.font()
        bold.setBold(True)
        fm, fm_bold = QFontMetrics(base), QFontMetrics(bold)
        for row in range(first, last):
            item, depth = self._rows[row]
            y = row * h - top
            rect = QRect(0, y, width, h)
            selected = item is self._current and self._selected
            if selected:
                p.fillRect(rect, theme.qc(theme.ACCENT_SOFT))
            elif item is self._hover:
                p.fillRect(rect, theme.qc(theme.RAISED))
            if item is self._current and self.hasFocus() and not selected:
                p.setPen(QPen(theme.qc(theme.ACCENT_BORDER), 1))
                p.setBrush(Qt.NoBrush)
                p.drawRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5))
            x = self._x0(depth)
            cy = y + h / 2
            if item.has_visible_children():
                self._paint_arrow(p, x, cy, item._expanded)
            x += ARROW
            if item._check is not None:
                self._paint_box(p, x, cy, item._check)
                x += BOX + GAP
            count = item._text[1]
            right = width - 6
            if count:
                cw = fm.horizontalAdvance(count)
                p.setFont(base)
                p.setPen(theme.qc(theme.MUTED))
                p.drawText(QRect(right - cw, y, cw, h), Qt.AlignVCenter | Qt.AlignRight, count)
                right -= cw + GAP
            metrics = fm_bold if item._bold else fm
            p.setFont(bold if item._bold else base)
            p.setPen(theme.qc(theme.TEXT_STRONG if selected else theme.TEXT))
            text = metrics.elidedText(item._text[0], Qt.ElideRight, max(0, right - x))
            p.drawText(QRect(x, y, max(0, right - x), h), Qt.AlignVCenter | Qt.AlignLeft, text)
        p.end()

    def _paint_arrow(self, p, x, cy, open_):
        s = ARROW / 16
        pen = QPen(theme.qc(theme.MUTED), 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        pts = ((4.5, 6.2), (8, 9.8), (11.5, 6.2)) if open_ else ((6.2, 4.5), (9.8, 8), (6.2, 11.5))
        path = QPainterPath(QPointF(x + pts[0][0] * s, cy - 8 * s + pts[0][1] * s))
        for px, py in pts[1:]:
            path.lineTo(QPointF(x + px * s, cy - 8 * s + py * s))
        p.drawPath(path)

    def _paint_box(self, p, x, cy, state):
        box = QRectF(x + 0.5, cy - BOX / 2 + 0.5, BOX - 1, BOX - 1)
        if state == Qt.Checked:
            fill, edge = theme.ACCENT, theme.ACCENT
        elif state == Qt.PartiallyChecked:
            fill, edge = theme.ACCENT_BORDER, theme.ACCENT_BORDER
        else:
            fill, edge = theme.SUNKEN, theme.BORDER_STRONG
        p.setPen(QPen(theme.qc(edge), 1))
        p.setBrush(theme.qc(fill))
        p.drawRoundedRect(box, 3, 3)
        if state == Qt.Unchecked:
            return
        s = BOX / 16
        pen = QPen(theme.qc(theme.ON_ACCENT), 2.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        top = cy - BOX / 2
        pts = ((3.6, 8.4), (6.5, 11.3), (12.5, 5.1)) if state == Qt.Checked else ((4, 8), (12, 8))
        path = QPainterPath(QPointF(x + pts[0][0] * s, top + pts[0][1] * s))
        for px, py in pts[1:]:
            path.lineTo(QPointF(x + px * s, top + py * s))
        p.drawPath(path)

    # ------------------------------------------------------------------ mouse
    def _toggle_check(self, item):
        item.setCheckState(0, Qt.Unchecked if item._check == Qt.Checked else Qt.Checked)

    def mousePressEvent(self, event):
        item, zone = self._hit(event.position())
        self._pressed = None
        if event.button() != Qt.LeftButton or item is None:
            super().mousePressEvent(event)
            return
        self.setFocus(Qt.MouseFocusReason)
        if zone == "arrow":
            item.setExpanded(not item._expanded)
        elif zone == "check":
            self._toggle_check(item)
        else:
            self.setCurrentItem(item)
            self._pressed = item
        event.accept()

    def mouseReleaseEvent(self, event):
        item, zone = self._hit(event.position())
        pressed, self._pressed = self._pressed, None
        if event.button() == Qt.LeftButton and item is not None and item is pressed and zone == "row":
            if not self.signalsBlocked():
                self.itemClicked.emit(item, 0)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        item, zone = self._hit(event.position())
        if event.button() != Qt.LeftButton or item is None:
            super().mouseDoubleClickEvent(event)
            return
        if zone == "arrow":
            item.setExpanded(not item._expanded)
        elif zone == "check":
            self._toggle_check(item)
        else:
            if item._children:
                item.setExpanded(not item._expanded)
            if not self.signalsBlocked():
                self.itemActivated.emit(item, 0)
        event.accept()

    def mouseMoveEvent(self, event):
        item, _zone = self._hit(event.position())
        if item is not self._hover:
            self._hover = item
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover is not None:
            self._hover = None
            self.viewport().update()
        super().leaveEvent(event)

    def viewportEvent(self, event):
        if event.type() == QEvent.ToolTip:
            item = self.itemAt(event.pos())
            if item is not None and item._tip:
                QToolTip.showText(event.globalPos(), item._tip, self.viewport())
            else:
                QToolTip.hideText()
                event.ignore()
            return True
        if event.type() == QEvent.Leave and self._hover is not None:
            self._hover = None
            self.viewport().update()
        return super().viewportEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        if self._current is None:
            self._ensure_layout()
            if self._rows:                 # a keyboard starting point, not a selection
                self._current = self._rows[0][0]
                self._describe(self._current)
        self.viewport().update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.viewport().update()

    # ------------------------------------------------------------------ keyboard
    def _move_to(self, row):
        self._ensure_layout()
        if not self._rows:
            return
        item = self._rows[max(0, min(row, len(self._rows) - 1))][0]
        self.setCurrentItem(item)
        self.scrollToItem(item)

    def keyPressEvent(self, event):
        self._ensure_layout()
        key = event.key()
        item = self._current
        row = self._index.get(id(item), -1) if item is not None else -1
        page = max(1, self.viewport().height() // self.rowHeight() - 1)
        if key == Qt.Key_Down:
            self._move_to(row + 1)
        elif key == Qt.Key_Up:
            self._move_to(max(0, row - 1))
        elif key == Qt.Key_Home:
            self._move_to(0)
        elif key == Qt.Key_End:
            self._move_to(len(self._rows) - 1)
        elif key == Qt.Key_PageDown:
            self._move_to(row + page)
        elif key == Qt.Key_PageUp:
            self._move_to(max(0, row - page))
        elif key == Qt.Key_Right and item is not None:
            if item.has_visible_children() and not item._expanded:
                item.setExpanded(True)
            elif item._expanded and item.has_visible_children():
                self._move_to(row + 1)
        elif key == Qt.Key_Left and item is not None:
            if item._expanded and item._children:
                item.setExpanded(False)
            elif item.parent() is not None:
                self.setCurrentItem(item.parent())
                self.scrollToItem(item.parent())
        elif key == Qt.Key_Space and item is not None and item._check is not None:
            self._toggle_check(item)
        elif key in (Qt.Key_Return, Qt.Key_Enter) and item is not None:
            if not self.signalsBlocked():
                self.itemActivated.emit(item, 0)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    # ------------------------------------------------------------------ accessibility
    def _row_changed(self, item):
        if item is self._current:
            self._describe(item)

    def _describe(self, item):
        """Say the current row through the widget's description: no per-row accessibility objects exist."""
        if item is None:
            self.setAccessibleDescription("")
            return
        parts = [item.data(0, Qt.AccessibleTextRole) or item._text[0]]
        if item._text[1]:
            parts.append(item._text[1])
        if item._check is not None:
            parts.append({Qt.Checked: "checked", Qt.PartiallyChecked: "partly checked"}.get(item._check,
                                                                                          "not checked"))
        if item._children:
            parts.append("expanded" if item._expanded else "collapsed")
        depth, node = 1, item.parent()
        while node is not None:
            depth, node = depth + 1, node.parent()
        parts.append(f"level {depth}")
        self.setAccessibleDescription(", ".join(str(p) for p in parts if p))
