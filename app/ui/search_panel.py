from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QLabel, QLineEdit, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate,
                               QVBoxLayout, QWidget)

from . import theme

ROLE_ENTRY = Qt.UserRole + 1
KIND_BADGE = {"structure": "", "group": "GROUP", "landmark": "LANDMARK", "clinical": "CLINICAL", "tissue": "HISTOLOGY",
              "micro": "3D MODEL", "lesson": "LESSON", "radiology": "RADIOLOGY"}
KIND_COLOR = {"clinical": "#ee8a92", "tissue": "#bf9cf0", "micro": "#6fd0bb", "lesson": theme.WARNING,
              "radiology": theme.INFO}


def shown_alt(entry):
    """The part of an entry's alternative text worth showing. For structures it is the Latin name; for a radiology
    case it is a keyword blob that starts with the modality the subtitle already gives."""
    alt = entry.alt or ""
    if entry.kind == "radiology":
        parts = entry.subtitle.split(" · ")
        modality = parts[1] if len(parts) > 1 else ""
        if modality and alt.startswith(modality + " "):
            alt = alt[len(modality) + 1:]
    return alt


class ResultDelegate(QStyledItemDelegate):
    def __init__(self, ds, parent=None):
        super().__init__(parent)
        self.ds = ds

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 48)

    def paint(self, p: QPainter, option, index):
        entry = index.data(ROLE_ENTRY)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = option.rect
        card = QRectF(r.x() + 2, r.y() + 2, r.width() - 4, r.height() - 4)
        if option.state & QStyle.State_Selected:
            p.setPen(theme.qc(theme.ACCENT_BORDER))
            p.setBrush(theme.qc(theme.ACCENT_SOFT))
            p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), theme.R_LG, theme.R_LG)
        elif option.state & QStyle.State_MouseOver:
            p.setPen(Qt.NoPen)
            p.setBrush(theme.qc(theme.RAISED))
            p.drawRoundedRect(card, theme.R_LG, theme.R_LG)
        if entry.kind in KIND_COLOR:
            col = QColor(KIND_COLOR[entry.kind])
        else:
            col = QColor.fromRgbF(*self.ds.systems[self.ds.system_index.get(entry.system, 0)]["color"])
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(r.x() + 9, r.y() + 12, 3, r.height() - 24), 1.5, 1.5)
        title_font = QFont(option.font)
        title_font.setPointSizeF(theme.FS_BODY)
        title_font.setBold(entry.kind != "landmark")
        p.setFont(title_font)
        p.setPen(theme.qc(theme.TEXT_STRONG))
        badge = KIND_BADGE[entry.kind]
        tx = r.x() + 21
        p.drawText(QRectF(tx, r.y() + 6, r.width() - 30, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(entry.title, Qt.ElideRight, r.width() - 110))
        sub_font = QFont(option.font)
        sub_font.setPointSizeF(theme.FS_SMALL - 0.3)
        p.setFont(sub_font)
        p.setPen(theme.qc(theme.MUTED))
        alt = shown_alt(entry)
        subtitle = entry.subtitle + (f"  ·  {alt}" if alt else "")
        p.drawText(QRectF(tx, r.y() + 25, r.width() - 30, 17), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(subtitle, Qt.ElideRight, r.width() - 34))
        if badge:
            bf = QFont(option.font)
            bf.setPointSizeF(6.8)
            bf.setBold(True)
            p.setFont(bf)
            bw = p.fontMetrics().horizontalAdvance(badge) + 12
            br = QRectF(r.right() - bw - 9, r.y() + 8, bw, 16)
            tint = QColor(KIND_COLOR.get(entry.kind, theme.TEXT_2))
            bg = QColor(tint)
            bg.setAlpha(38)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(br, theme.R_SM, theme.R_SM)
            p.setPen(tint.lighter(115) if entry.kind in KIND_COLOR else theme.qc(theme.TEXT_2))
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
        lay.setContentsMargins(12, 12, 12, 6)
        lay.setSpacing(6)
        self.edit = SearchLine()
        self.edit.setPlaceholderText(f"Search {ds.n:,} structures, landmarks, Latin…")
        self.edit.setClearButtonEnabled(True)
        lay.addWidget(self.edit)
        self.info = QLabel("")
        self.info.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL) + " padding-left:2px;")
        lay.addWidget(self.info)
        self.info.hide()
        self.list = QListWidget()
        self.list.setItemDelegate(ResultDelegate(ds, self.list))
        self.list.setMouseTracking(True)
        self.list.setUniformItemSizes(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)   # every row elides to the width
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
            latin = e.alt if e.kind in ("structure", "group", "landmark") else ""   # others carry search keywords
            it.setToolTip(f"{e.title}\n{e.subtitle}" + (f"\nLatin: {latin}" if latin else ""))
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
