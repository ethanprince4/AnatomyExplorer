"""The radiology panel: a still radiograph, numbered where it matters, beside the live 3D model."""


from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QSplitter,
                               QTextBrowser, QVBoxLayout, QWidget)

from . import theme
from .card_list import CardList

MARKER_R = 9.0
ACCENT = theme.qc(theme.ACCENT_TEXT)
HOT = theme.qc(theme.WARNING)
MODALITY_COLOUR = {"x-ray": theme.INFO, "ct": "#6fd0bb", "mri": "#bf9cf0"}


class RadiographView(QWidget):
    """Shows one image scaled to fit, with numbered markers on it. Wheel zooms, drag pans."""

    labelHovered = Signal(int)
    labelClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = QPixmap()
        self.labels = []
        self.show_labels = True
        self.hot = -1
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._drag = None
        self._rects = []
        self.setMinimumSize(240, 240)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.CrossCursor)

    # ------------------------------------------------------------------ content
    def set_case(self, pixmap, labels):
        self.pixmap = pixmap
        self.labels = list(labels)
        self.hot = -1
        self.fit()

    def fit(self):
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()

    def set_hot(self, index):
        if index != self.hot:
            self.hot = index
            self.update()

    # ------------------------------------------------------------------ geometry
    def _base_rect(self):
        """Where the image sits at zoom 1, letterboxed inside the widget."""
        if self.pixmap.isNull():
            return QRectF(0, 0, self.width(), self.height())
        pw, ph = self.pixmap.width(), self.pixmap.height()
        scale = min(self.width() / pw, self.height() / ph)
        w, h = pw * scale, ph * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def image_rect(self):
        r = self._base_rect()
        cx, cy = r.center().x(), r.center().y()
        w, h = r.width() * self._zoom, r.height() * self._zoom
        return QRectF(cx - w / 2 + self._pan.x(), cy - h / 2 + self._pan.y(), w, h)

    def to_widget(self, x, y):
        r = self.image_rect()
        return QPointF(r.left() + x * r.width(), r.top() + y * r.height())

    # ------------------------------------------------------------------ painting
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), theme.qc(theme.CANVAS))
        if self.pixmap.isNull():
            p.setPen(theme.qc(theme.MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, "No image")
            p.end()
            return
        r = self.image_rect()
        p.drawPixmap(r, self.pixmap, QRectF(self.pixmap.rect()))
        self._rects = []
        if not self.show_labels:
            p.end()
            return
        font = QFont(self.font())
        font.setPointSizeF(max(7.5, font.pointSizeF() - 0.5))
        font.setBold(True)
        p.setFont(font)
        fm = QFontMetricsF(font)
        for i, lab in enumerate(self.labels):
            c = self.to_widget(lab.x, lab.y)
            if not self.rect().adjusted(-30, -30, 30, 30).contains(c.toPoint()):
                continue
            hot = i == self.hot
            col = HOT if hot else ACCENT
            rad = MARKER_R * (1.25 if hot else 1.0)
            p.setPen(QPen(theme.qc(theme.CANVAS, 210), 2.2))
            p.setBrush(QColor(col.red(), col.green(), col.blue(), 235 if hot else 200))
            p.drawEllipse(c, rad, rad)
            p.setPen(theme.qc(theme.ON_ACCENT))
            p.drawText(QRectF(c.x() - rad, c.y() - rad, rad * 2, rad * 2), Qt.AlignCenter, str(i + 1))
            self._rects.append((QRectF(c.x() - rad - 3, c.y() - rad - 3, rad * 2 + 6, rad * 2 + 6), i))
            if hot:
                text = lab.text
                tw = fm.horizontalAdvance(text) + 14
                th = fm.height() + 6
                bx = c.x() + rad + 8
                if bx + tw > self.width() - 4:
                    bx = c.x() - rad - 8 - tw
                box = QRectF(bx, c.y() - th / 2, tw, th)
                p.setPen(QPen(HOT, 1.2))
                p.setBrush(theme.qc(theme.OVERLAY, 240))
                p.drawRoundedRect(box, 4, 4)
                p.setPen(theme.qc(theme.TEXT_STRONG))
                p.drawText(box, Qt.AlignCenter, text)
        p.end()

    # ------------------------------------------------------------------ input
    def _marker_at(self, pos):
        for rect, i in self._rects:
            if rect.contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            delta = e.position() - self._drag
            self._drag = e.position()
            self._pan += delta
            self.update()
            return
        i = self._marker_at(e.position()) if self.show_labels else -1
        if i != self.hot:
            self.hot = i
            self.labelHovered.emit(i)
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            i = self._marker_at(e.position()) if self.show_labels else -1
            if i >= 0:
                self.labelClicked.emit(i)
                return
            self._drag = e.position()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.setCursor(Qt.CrossCursor)

    def mouseDoubleClickEvent(self, e):
        self.fit()

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if not steps:
            return
        old = self._zoom
        self._zoom = max(1.0, min(8.0, self._zoom * (1.18 ** steps)))
        if self._zoom == old:
            return
        # keep the point under the cursor still
        r = self._base_rect()
        cursor = e.position() - r.center() - self._pan
        self._pan -= cursor * (self._zoom / old - 1.0)
        if self._zoom <= 1.0:
            self._pan = QPointF(0.0, 0.0)
        self.update()

    def leaveEvent(self, e):
        if self.hot != -1:
            self.hot = -1
            self.labelHovered.emit(-1)
            self.update()


class WrapLabel(QLabel):
    """A word-wrapped label that claims the height its wrapped text needs. A plain one reports a one-line minimum,
    so in a short splitter pane the legend and notes above were laid over it."""

    def __init__(self, *args):
        super().__init__(*args)
        self.setWordWrap(True)

    def _fit(self):
        # measured with the minimum cleared, since QLabel's height-for-width never answers below its minimum
        want = 0
        if self.text():
            self.setMinimumHeight(0)
            want = self.heightForWidth(max(self.width(), 1))
        if want != self.minimumHeight():
            self.setMinimumHeight(want)

    def setText(self, text):
        super().setText(text)
        self._fit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()


class RadiologyPanel(QWidget):
    """Image, legend and notes for one case. Sits to the left of the 3D view."""

    structuresPicked = Signal(object, bool)     # [names], frame?
    sceneRequested = Signal(object)             # the case, to set the 3D view up again
    closeRequested = Signal()
    caseStepped = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.case = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 10, 8)
        outer.setSpacing(8)

        head = QHBoxLayout()
        self.title = QLabel()
        f = QFont(self.font())
        f.setPointSizeF(theme.FS_TITLE)
        f.setBold(True)
        self.title.setFont(f)
        self.title.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_TITLE, 700))
        self.title.setWordWrap(True)
        head.addWidget(self.title, 1)
        self.badge = QLabel()
        self.badge.setStyleSheet(theme.tag_css(theme.INFO))
        head.addWidget(self.badge, 0, Qt.AlignTop)
        close = QPushButton("✕")
        close.setFixedWidth(28)
        close.setStyleSheet("padding: 3px 0;")
        theme.set_variant(close, "ghost")
        close.setToolTip("Close the radiograph panel")
        close.clicked.connect(self.closeRequested.emit)
        head.addWidget(close, 0, Qt.AlignTop)
        outer.addLayout(head)

        self.view = RadiographView()
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.view)
        lower = QWidget()
        ll = QVBoxLayout(lower)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)

        row = QHBoxLayout()
        self.labels_on = QCheckBox("Labels")
        self.labels_on.setChecked(True)
        self.labels_on.toggled.connect(self._toggle_labels)
        row.addWidget(self.labels_on)
        fit = QPushButton("Fit")
        fit.setFixedWidth(46)
        fit.setStyleSheet("padding: 5px 0;")
        fit.clicked.connect(self.view.fit)
        row.addWidget(fit)
        setup = QPushButton("Match the 3D view")
        setup.clicked.connect(lambda: self.case and self.sceneRequested.emit(self.case))
        row.addWidget(setup, 1)
        prev = QPushButton("‹")
        nxt = QPushButton("›")
        for b, step in ((prev, -1), (nxt, 1)):
            b.setFixedWidth(28)
            b.setStyleSheet("padding: 5px 0;")
            b.clicked.connect(lambda _=False, s=step: self.caseStepped.emit(s))
            row.addWidget(b)
        ll.addLayout(row)

        self.legend = CardList(compact=True)
        self.legend.itemEntered.connect(lambda it: self.view.set_hot(self.legend.row(it)))
        self.legend.itemClicked.connect(self._legend_clicked)
        self.legend.setMinimumHeight(90)
        ll.addWidget(self.legend, 3)

        self.notes = QTextBrowser()
        self.notes.document().setDefaultStyleSheet(f"a {{ color:{theme.ACCENT_TEXT}; }} b {{ color:{theme.TEXT_STRONG}; }}")
        self.notes.document().setDocumentMargin(8)
        self.notes.setOpenExternalLinks(True)
        self.notes.setMinimumHeight(80)
        ll.addWidget(self.notes, 2)

        self.credit = WrapLabel()
        self.credit.setOpenExternalLinks(True)
        self.credit.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_CAPTION))
        ll.addWidget(self.credit)
        split.addWidget(lower)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 4)
        outer.addWidget(split, 1)

        self.view.labelHovered.connect(self._hover)
        self.view.labelClicked.connect(self._clicked)

    # ------------------------------------------------------------------ content
    def show_case(self, case):
        self.case = case
        self.title.setText(case.title)
        self.badge.setText(case.modality)
        self.badge.setStyleSheet(theme.tag_css(MODALITY_COLOUR.get(str(case.modality).lower(), theme.INFO)))
        pm = QPixmap(str(case.image))
        if case.crop and not pm.isNull():
            x0, y0, x1, y1 = (float(v) for v in case.crop)
            pm = pm.copy(int(x0 * pm.width()), int(y0 * pm.height()),
                         max(1, int((x1 - x0) * pm.width())), max(1, int((y1 - y0) * pm.height())))
        self.view.set_case(pm, case.labels)
        self.legend.clear()
        for i, lab in enumerate(case.labels):
            names = lab.structures
            tip = "Click to select in 3D: " + ", ".join(names) if names else "Nothing in the model for this one"
            self.legend.add_card(f"{i + 1}.  {lab.text}", lab.note or "", accent=theme.ACCENT if names else "",
                                 dim=not names, tooltip=tip)
        html = case.text or ""
        if case.reading:
            html += "<p><b>How to read it</b></p><ol>" + "".join(f"<li>{x}</li>" for x in case.reading) + "</ol>"
        self.notes.setHtml(f"<div style='line-height:150%'>{html}</div>")
        page = case.source.get("page", "")
        credit = case.credit()
        if page:
            self.credit.setText(f'Image: <a href="{page}" style="color:{theme.ACCENT_TEXT}">Wikimedia Commons</a> · {credit}')
        else:
            self.credit.setText(f"Image: {credit}")

    def _toggle_labels(self, on):
        self.view.show_labels = on
        self.view.update()

    def _hover(self, index):
        if 0 <= index < self.legend.count():
            self.legend.setCurrentRow(index)
        elif index < 0:
            self.legend.setCurrentRow(-1)

    def _names(self, index):
        if self.case is None or not (0 <= index < len(self.case.labels)):
            return []
        return self.case.labels[index].structures

    def _clicked(self, index):
        names = self._names(index)
        if names:
            self.structuresPicked.emit(names, True)

    def _legend_clicked(self, item):
        index = self.legend.row(item)
        self.view.set_hot(index)
        names = self._names(index)
        if names:
            self.structuresPicked.emit(names, True)


class RadiologyBrowser(QWidget):
    """The left-dock list of cases."""

    caseChosen = Signal(str)

    def __init__(self, cases, parent=None):
        super().__init__(parent)
        self.cases = cases
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 8)
        lay.setSpacing(8)
        intro = QLabel("A still radiograph, CT or MR slice beside the live model. Click a numbered label on the "
                       "image – or a line in its legend – and the 3D view highlights the same structure.")
        intro.setWordWrap(True)
        intro.setStyleSheet(theme.text_css(theme.TEXT_2))
        lay.addWidget(intro)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter cases…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._fill)
        lay.addWidget(self.filter)
        self.list = CardList()
        self.list.itemClicked.connect(self._chosen)
        self.list.itemActivated.connect(self._chosen)
        lay.addWidget(self.list, 1)
        self._fill()

    def _fill(self):
        needle = self.filter.text().strip().lower()
        self.list.clear()
        by_region = {}
        for case in self.cases:
            hay = f"{case.title} {case.summary} {case.region} {case.modality}".lower()
            if needle and needle not in hay:
                continue
            by_region.setdefault(case.region, []).append(case)
        for region in sorted(by_region):
            self.list.add_header(region)
            for case in by_region[region]:
                self.list.add_card(case.title, case.summary, badge=case.modality,
                                   accent=MODALITY_COLOUR.get(case.modality.lower(), ""), data=case.id,
                                   tooltip=f"{case.modality} · {len(case.labels)} labels")
        if self.list.count() == 0:
            self.list.add_note("No case matches that.")

    def _chosen(self, item):
        cid = item.data(Qt.UserRole)
        if cid:
            self.caseChosen.emit(cid)



