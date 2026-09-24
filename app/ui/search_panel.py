from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QLabel, QLineEdit, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate,
                               QVBoxLayout, QWidget)

ROLE_ENTRY = Qt.UserRole + 1
KIND_BADGE = {"structure": "", "group": "GROUP", "landmark": "LANDMARK", "clinical": "CLINICAL", "tissue": "HISTOLOGY",
              "micro": "3D MICRO", "lesson": "LESSON", "radiology": "RADIOLOGY",
              "sketchfab": "SKETCHFAB"}
KIND_COLOR = {"clinical": "#e0707a", "tissue": "#b48ee0", "micro": "#6cc4b0", "lesson": "#e8b45c",
              "radiology": "#7fb2f0", "sketchfab": "#1caad9"}


class ResultDelegate(QStyledItemDelegate):
    def __init__(self, ds, parent=None):
        super().__init__(parent)
        self.ds = ds

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 44)

    def paint(self, p: QPainter, option, index):
        entry = index.data(ROLE_ENTRY)
        p.save()
        r = option.rect
        if option.state & QStyle.State_Selected:
            p.fillRect(r, QColor("#1f3a4a"))
        elif option.state & QStyle.State_MouseOver:
            p.fillRect(r, QColor("#20252c"))
        if entry.kind in KIND_COLOR:
            col = QColor(KIND_COLOR[entry.kind])
        else:
            col = QColor.fromRgbF(*self.ds.systems[self.ds.system_index.get(entry.system, 0)]["color"])
        p.fillRect(QRectF(r.x() + 8, r.y() + 10, 3, r.height() - 20), col)
        title_font = QFont(option.font)
        title_font.setPointSizeF(9.6)
        title_font.setBold(entry.kind != "landmark")
        p.setFont(title_font)
        p.setPen(QColor("#e8edf3"))
        badge = KIND_BADGE[entry.kind]
        tx = r.x() + 20
        p.drawText(QRectF(tx, r.y() + 4, r.width() - 30, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(entry.title, Qt.ElideRight, r.width() - 110))
        sub_font = QFont(option.font)
        sub_font.setPointSizeF(8.2)
        p.setFont(sub_font)
        p.setPen(QColor("#8a94a3"))
        subtitle = entry.subtitle + (f"  ·  {entry.alt}" if entry.alt else "")
        p.drawText(QRectF(tx, r.y() + 22, r.width() - 30, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(subtitle, Qt.ElideRight, r.width() - 34))
        if badge:
            bf = QFont(option.font)
            bf.setPointSizeF(6.8)
            bf.setBold(True)
            p.setFont(bf)
            bw = p.fontMetrics().horizontalAdvance(badge) + 10
            br = QRectF(r.right() - bw - 8, r.y() + 7, bw, 15)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#2a3340"))
            p.drawRoundedRect(br, 4, 4)
            p.setPen(QColor("#9fb3c8"))
            p.drawText(br, Qt.AlignCenter, badge)
        p.restore()


class SearchLine(QLineEdit):
    navigate = Signal(int)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Down, Qt.Key_Up):
            self.navigate.emit(1 if e.key() == Qt.Key_Down else -1)
            return
        if e.key() == Qt.Key_Escape:
            self.clear()
            return
        super().keyPressEvent(e)


class SearchPanel(QWidget):
    activated = Signal(object)
    queryActive = Signal(bool)

    def __init__(self, ds, index, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.index = index
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 6)
        lay.setSpacing(6)
        self.edit = SearchLine()
        self.edit.setPlaceholderText(f"Search {ds.n:,} structures, landmarks, Latin…")
        self.edit.setClearButtonEnabled(True)
        lay.addWidget(self.edit)
        self.info = QLabel("")
        self.info.setStyleSheet("color:#8a94a3; font-size:8.5pt; padding-left:2px;")
        lay.addWidget(self.info)
        self.info.hide()
        self.list = QListWidget()
        self.list.setItemDelegate(ResultDelegate(ds, self.list))
        self.list.setMouseTracking(True)
        self.list.setUniformItemSizes(True)
        lay.addWidget(self.list, 1)
        self.list.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._run)
        self.edit.textChanged.connect(lambda _: self._timer.start())
        self.edit.returnPressed.connect(self._activate_current)
        self.edit.navigate.connect(self._navigate)
        self.list.itemActivated.connect(lambda it: self.activated.emit(it.data(ROLE_ENTRY)))
        self.list.itemClicked.connect(lambda it: self.activated.emit(it.data(ROLE_ENTRY)))

    def results_widget(self):
        return self.list

    def focus_search(self):
        self.edit.setFocus()
        self.edit.selectAll()

    def _run(self):
        q = self.edit.text().strip()
        self.list.clear()
        if not q:
            self.info.hide()
            self.list.hide()
            self.queryActive.emit(False)
            return
        results = self.index.search(q)
        for e in results:
            it = QListWidgetItem()
            it.setData(ROLE_ENTRY, e)
            it.setToolTip(f"{e.title}\n{e.subtitle}" + (f"\nLatin: {e.alt}" if e.alt else ""))
            self.list.addItem(it)
        self.info.setText(f"{len(results)} result{'s' if len(results) != 1 else ''}" if results else "No matches")
        self.info.show()
        self.list.show()
        if results:
            self.list.setCurrentRow(0)
        self.queryActive.emit(True)

    def _navigate(self, step):
        if self.list.count() == 0:
            return
        row = max(0, min(self.list.count() - 1, self.list.currentRow() + step))
        self.list.setCurrentRow(row)

    def _activate_current(self):
        if self._timer.isActive():
            self._timer.stop()
            self._run()
        it = self.list.currentItem() or (self.list.item(0) if self.list.count() else None)
        if it:
            self.activated.emit(it.data(ROLE_ENTRY))
