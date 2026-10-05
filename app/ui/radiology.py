"""The radiology panel: a still radiograph, numbered where it matters, beside the live 3D model."""


from html import escape

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QSplitter,
                               QScrollArea, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from . import theme
from .card_list import CardList
from .image_workspace import LocalImageLoader, control, matches_words

MARKER_R = 9.0
ACCENT = theme.qc(theme.ACCENT_TEXT)
HOT = theme.qc(theme.ACCENT)
# Text badges supply modality semantics; cobalt stays the single action accent.
MODALITY_COLOUR = {name: theme.ACCENT for name in
                   ("x-ray", "ct", "mri", "ultrasound", "fluoroscopy", "angiography",
                    "mammography", "nuclear medicine", "pet/ct")}



class RadiographView(QWidget):
    """Shows one image scaled to fit, with numbered markers on it. Wheel zooms, drag pans."""

    labelHovered = Signal(int)
    labelClicked = Signal(int)
    zoomChanged = Signal(float)

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
        self._message = "Choose a case to view its scan."
        self.setMinimumSize(180, 150)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Radiology image")
        self.setAccessibleDescription("Use plus and minus to zoom, arrow keys to pan, and Home to fit.")
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.CrossCursor)

    # ------------------------------------------------------------------ content
    def set_case(self, pixmap, labels):
        self.pixmap = pixmap
        self._message = "" if not pixmap.isNull() else "Image is unavailable."
        self.labels = list(labels)
        self.hot = -1
        self._rects = []
        self.fit()

    def set_message(self, message):
        self.set_case(QPixmap(), [])
        self._message = message
        self.setAccessibleDescription(message)
        self.update()

    def zoom_by(self, steps):
        if self.pixmap.isNull():
            return
        self._zoom = max(1.0, min(8.0, self._zoom * (1.18 ** steps)))
        if self._zoom <= 1:
            self._pan = QPointF()
        self.zoomChanged.emit(self._zoom)
        self.update()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Plus, Qt.Key_Equal, Qt.Key_Minus):
            self.zoom_by(-1 if key == Qt.Key_Minus else 1)
        elif key in (Qt.Key_Home, Qt.Key_0):
            self.fit()
        elif key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and not self.pixmap.isNull():
            dx = 40 if key == Qt.Key_Left else -40 if key == Qt.Key_Right else 0
            dy = 40 if key == Qt.Key_Up else -40 if key == Qt.Key_Down else 0
            self._pan += QPointF(dx, dy)
            self.update()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def fit(self):
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.zoomChanged.emit(self._zoom)
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
            p.drawText(self.rect().adjusted(24, 24, -24, -24), Qt.AlignCenter | Qt.TextWordWrap, self._message)
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
        if self.pixmap.isNull():
            e.ignore()
            return
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
        self.zoomChanged.emit(self._zoom)
        self.update()
        e.accept()

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

    structuresPicked = Signal(object, bool, str)  # [names], frame?, explicit image-label side
    sceneRequested = Signal(object)             # the case, to set the 3D view up again
    closeRequested = Signal()
    caseStepped = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.case = None
        self.setMinimumWidth(280)
        self.setAccessibleName("Radiology study workspace")
        self._scan_loader = LocalImageLoader(self)
        self._diagram_loader = LocalImageLoader(self)
        self._scan_loader.loaded.connect(self._scan_loaded)
        self._diagram_loader.loaded.connect(self._diagram_loaded)
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
        close = control("Close", "Close radiology workspace")
        theme.set_variant(close, "ghost")
        close.setToolTip("Close the scan panel")
        close.clicked.connect(self.closeRequested.emit)
        head.addWidget(close, 0, Qt.AlignTop)
        outer.addLayout(head)
        self.metadata = QLabel()
        self.metadata.setWordWrap(True)
        self.metadata.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
        outer.addWidget(self.metadata)

        self.view = RadiographView()
        self.illustration_view = RadiographView()
        self.illustration_view.show_labels = False
        self.image_tabs = QTabWidget()
        self.image_tabs.addTab(self.view, "Scan")
        self.image_tabs.addTab(self.illustration_view, "Teaching view")
        self.image_tabs.currentChanged.connect(self._image_tab_changed)
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        image_area = QWidget()
        image_layout = QVBoxLayout(image_area)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(6)
        image_layout.addWidget(self.image_tabs, 1)
        row = QGridLayout()
        self._image_controls_layout = row
        self._compact_image_controls = None
        self.labels_on = QCheckBox("Labels")
        self.labels_on.setAccessibleName("Show numbered scan labels")
        self.labels_on.setChecked(True)
        self.labels_on.toggled.connect(self._toggle_labels)
        row.addWidget(self.labels_on, 0, 0, 1, 2)
        self.zoom_out = control("−", "Zoom image out", "Zoom out (−)")
        self.zoom_in = control("+", "Zoom image in", "Zoom in (+)")
        self.zoom_out.clicked.connect(lambda: self._active_view().zoom_by(-1))
        self.zoom_in.clicked.connect(lambda: self._active_view().zoom_by(1))
        row.addWidget(self.zoom_out, 1, 0)
        self.zoom_label = QLabel("Fit")
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_label.setMinimumWidth(42)
        self.zoom_label.setAccessibleName("Image zoom relative to fit")
        row.addWidget(self.zoom_label, 1, 1)
        row.addWidget(self.zoom_in, 1, 2)
        self.fit_scan = control("Fit scan", "Fit image", "Fit the image (Home); the 3D reference is unchanged")
        self.fit_scan.clicked.connect(lambda: self._active_view().fit())
        row.addWidget(self.fit_scan, 0, 2)
        image_layout.addLayout(row)
        self.image_status = QLabel("Choose a case to begin.")
        self.image_status.setWordWrap(True)
        self.image_status.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_CAPTION))
        image_layout.addWidget(self.image_status)
        self.retry_image = control("Retry image", "Retry opening the current local image")
        self.retry_image.clicked.connect(self._reload_images)
        self.retry_image.hide()
        image_layout.addWidget(self.retry_image)
        split.addWidget(image_area)
        lower = QWidget()
        ll = QVBoxLayout(lower)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)
        self.study_tabs = QTabWidget()
        self.study_tabs.setAccessibleName("Case study material")
        notes_page = QWidget()
        notes_layout = QVBoxLayout(notes_page)
        notes_layout.setContentsMargins(0, 0, 0, 0)
        self.study_tabs.addTab(notes_page, "Study notes")
        ll.addWidget(self.study_tabs, 1)

        self.legend = CardList(compact=True)
        self.legend.itemEntered.connect(lambda it: self.view.set_hot(self.legend.row(it)))
        self.legend.itemClicked.connect(self._legend_clicked)
        self.legend.setMinimumHeight(80)
        self.legend.setAccessibleName("Numbered image labels")
        self.legend.itemActivated.connect(self._legend_clicked)
        self.study_tabs.addTab(self.legend, "Image labels")

        self.notes = QTextBrowser()
        self.notes.document().setDefaultStyleSheet(f"a {{ color:{theme.ACCENT_TEXT}; }} b {{ color:{theme.TEXT_STRONG}; }}")
        self.notes.document().setDocumentMargin(8)
        self.notes.setOpenExternalLinks(True)
        self.notes.setMinimumHeight(80)
        self.notes.setAccessibleName("Case notes and self-check")
        notes_layout.addWidget(self.notes, 1)

        self.question_page = QWidget()
        self.question_layout = QVBoxLayout(self.question_page)
        self.question_layout.setContentsMargins(0, 0, 0, 0)
        self.check_notes = QTextBrowser()
        self.check_notes.setAccessibleName("Radiology self-check question and answer")
        self.check_notes.document().setDocumentMargin(8)
        self.check_notes.setMinimumHeight(80)
        self.question_layout.addWidget(self.check_notes, 1)
        self.study_tabs.addTab(self.question_page, "Self-check")
        question_row = QVBoxLayout()
        question_row.setContentsMargins(0, 0, 0, 0)
        self.question_choice = QComboBox()
        self.question_choice.setAccessibleName("Teaching question")
        self.question_choice.setMinimumContentsLength(10)
        self.question_choice.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.question_choice.currentIndexChanged.connect(self._question_changed)
        question_row.addWidget(self.question_choice, 1)
        question_actions = QHBoxLayout()
        self.read_question = QPushButton("Hide answer")
        self.read_question.clicked.connect(self._question_changed)
        question_actions.addWidget(self.read_question)
        self.reveal_answer = QPushButton("Show answer")
        self.reveal_answer.clicked.connect(self._show_answer)
        question_actions.addWidget(self.reveal_answer)
        question_row.addLayout(question_actions)
        self.question_controls = QWidget()
        self.question_controls.setLayout(question_row)
        self.question_layout.addWidget(self.question_controls)

        self.atlas_note = WrapLabel()
        self.atlas_note.setStyleSheet(theme.text_css(theme.TEXT_2, theme.FS_CAPTION))


        self.credit = WrapLabel()
        self.credit.setOpenExternalLinks(True)
        self.credit.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_CAPTION))
        footer_body = QWidget()
        footer_layout = QVBoxLayout(footer_body)
        footer_layout.setContentsMargins(2, 2, 2, 2)
        footer_layout.setSpacing(4)
        footer_layout.addWidget(self.atlas_note)
        footer_layout.addWidget(self.credit)
        self.reference_footer = QScrollArea()
        self.reference_footer.setWidgetResizable(True)
        self.reference_footer.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.reference_footer.setMinimumHeight(52)
        self.reference_footer.setMaximumHeight(88)
        self.reference_footer.setWidget(footer_body)
        ll.addWidget(self.reference_footer)
        split.addWidget(lower)
        split.setStretchFactor(0, 6)
        split.setStretchFactor(1, 4)
        split.setSizes([460, 270])
        outer.addWidget(split, 1)
        navigation = QHBoxLayout()
        self.previous_case = control("Previous", "Previous radiology case")
        self.next_case = control("Next", "Next radiology case")
        self.previous_case.clicked.connect(lambda: self.caseStepped.emit(-1))
        self.next_case.clicked.connect(lambda: self.caseStepped.emit(1))
        self.reset_reference = control("Reset 3D", "Reset this case's 3D reference")
        self.reset_reference.clicked.connect(lambda: self.case and self.sceneRequested.emit(self.case))
        navigation.addWidget(self.previous_case)
        navigation.addWidget(self.next_case)
        navigation.addStretch(1)
        navigation.addWidget(self.reset_reference)
        outer.addLayout(navigation)
        self.view.zoomChanged.connect(self._zoom_changed)
        self.illustration_view.zoomChanged.connect(self._zoom_changed)
        self._set_image_controls(False)

        self.view.labelHovered.connect(self._hover)
        self.view.labelClicked.connect(self._clicked)

    # ------------------------------------------------------------------ content
    def show_case(self, case):
        self.case = case
        self.title.setText(case.title)
        self.badge.setText(case.modality)
        self.badge.setStyleSheet(theme.tag_css(theme.ACCENT, theme.ON_ACCENT))
        self.metadata.setText(" · ".join(str(x) for x in (case.modality, case.region, case.plane, case.finding) if x))
        self.metadata.setToolTip(self.metadata.text())
        self.image_tabs.setCurrentIndex(0)
        self._reload_images()
        self.view.show_labels = self.labels_on.isChecked()
        self.legend.clear()
        for i, lab in enumerate(case.labels):
            names = lab.structures
            tip = "Click to select in 3D: " + ", ".join(names) if names else "Source-image finding or landmark; no registered 3D match"
            self.legend.add_card(f"{i + 1}.  {lab.text}", lab.note or "", accent=theme.ACCENT,
                                 dim=False, tooltip=tip)
        self.atlas_note.setText(case.atlas_note)
        self.question_choice.blockSignals(True)
        self.legend.setMaximumHeight(16777215)
        self.question_choice.clear()
        for index, question in enumerate(case.questions):
            self.question_choice.addItem(f"Question {index + 1} of {len(case.questions)}", index)
        self.question_choice.blockSignals(False)
        self.question_controls.setVisible(bool(case.questions))
        self.study_tabs.setTabVisible(self.study_tabs.indexOf(self.question_page), bool(case.questions))
        self._render_notes(False)
        page = case.source.get("page", "")
        credit = escape(case.credit())
        if page:
            self.credit.setText(f'Image: <a href="{escape(page, quote=True)}" style="color:{theme.ACCENT_TEXT}">Source and licence</a> · {credit}')
        else:
            self.credit.setText(f"Image: {credit}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "fit_scan"):
            return
        controls = (self.labels_on, self.zoom_out, self.zoom_label, self.zoom_in, self.fit_scan)
        compact = self.width() < sum(w.sizeHint().width() for w in controls) + 64
        if compact == self._compact_image_controls:
            return
        self._compact_image_controls = compact
        row = self._image_controls_layout
        for widget in controls:
            row.removeWidget(widget)
        for column in range(5):
            row.setColumnStretch(column, 0)
        if compact:
            row.addWidget(self.labels_on, 0, 0, 1, 2)
            row.addWidget(self.fit_scan, 0, 2)
            row.addWidget(self.zoom_out, 1, 0)
            row.addWidget(self.zoom_label, 1, 1)
            row.addWidget(self.zoom_in, 1, 2)
        else:
            for column, widget in enumerate(controls):
                row.addWidget(widget, 0, column)
            row.setColumnStretch(0, 1)
        for button in (self.zoom_out, self.zoom_in, self.fit_scan):
            button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def _active_view(self):
        return self.view if self.image_tabs.currentIndex() == 0 else self.illustration_view

    def _set_image_controls(self, available):
        for button in (self.zoom_out, self.zoom_in, self.fit_scan):
            button.setEnabled(available)
        self.labels_on.setEnabled(available and self.image_tabs.currentIndex() == 0)

    def _zoom_changed(self, *_):
        zoom = self._active_view()._zoom
        self.zoom_label.setText("Fit" if zoom <= 1 else f"{zoom:.1f}×")

    def _reload_images(self):
        if self.case is None:
            return
        self._set_image_controls(False)
        self.retry_image.hide()
        self.view.set_message("Loading scan…")
        self.image_status.setText("Loading local scan…")
        self._scan_loader.load(self.case.image)
        diagram = getattr(self.case, "illustration_path", None)
        authored = bool(getattr(self.case, "illustration", {}))
        self.image_tabs.setTabVisible(1, authored or bool(diagram and diagram.is_file()))
        self.illustration_view.set_message("Loading teaching view…")
        self._diagram_loader.cancel()
        if self.image_tabs.isTabVisible(1):
            self._diagram_loader.load(diagram or "")

    def _scan_loaded(self, image, error):
        if self.case is None:
            return
        pm = QPixmap.fromImage(image)
        if self.case.crop and not pm.isNull():
            x0, y0, x1, y1 = (float(v) for v in self.case.crop)
            pm = pm.copy(int(x0 * pm.width()), int(y0 * pm.height()),
                         max(1, int((x1 - x0) * pm.width())), max(1, int((y1 - y0) * pm.height())))
        self.view.set_case(pm, self.case.labels)
        if error:
            self.view.set_message(error)
        else:
            self.view.setAccessibleDescription(f"{self.case.title}. Use plus and minus to zoom, arrows to pan, Home to fit.")
        self._image_tab_changed(self.image_tabs.currentIndex())

    def _diagram_loaded(self, image, error):
        self.illustration_view.set_case(QPixmap.fromImage(image), [])
        if error:
            self.illustration_view.set_message(error)
        self._image_tab_changed(self.image_tabs.currentIndex())

    def _question_changed(self, *_):
        self._render_notes(False)
        self.study_tabs.setCurrentWidget(self.question_page)
        self.check_notes.scrollToAnchor("self-check")

    def _image_tab_changed(self, index):
        if not hasattr(self, "fit_scan"):
            return
        self.fit_scan.setText("Fit scan" if index == 0 else "Fit diagram")
        view = self._active_view()
        available = not view.pixmap.isNull()
        self._set_image_controls(available)
        message = view._message
        self.retry_image.setVisible(not available and "Loading" not in message)
        self.image_status.setText("Scroll or use + / − to zoom · Drag or use arrows to pan · Home to fit"
                                  if available else message)
        self._zoom_changed()

    def _show_answer(self):
        self._render_notes(True)
        self.study_tabs.setCurrentWidget(self.question_page)
        self.check_notes.scrollToAnchor("self-check")

    def _render_notes(self, show_answer):
        case = self.case
        if case is None:
            return
        html = case.text or ""
        if case.reading:
            html += "<p><b>How to read it</b></p><ol>" + "".join(f"<li>{x}</li>" for x in case.reading) + "</ol>"
        question_html = ""
        index = self.question_choice.currentIndex()
        if 0 <= index < len(case.questions):
            question = case.questions[index]
            question_html += f"<p><a name='self-check'></a><b>Self-check</b><br>{escape(question['prompt'])}</p>"
            options = question.get("options", [])
            if options:
                question_html += "<ol>" + "".join(f"<li>{escape(option)}</li>" for option in options) + "</ol>"
            if show_answer:
                answer = question["answer"]
                answer = options[answer] if isinstance(answer, int) else answer
                question_html += f"<p><b>Answer: {escape(str(answer))}</b><br>{escape(question['explanation'])}</p>"
        if case.references:
            html += "<p><b>Teaching sources</b></p><ul>"
            for reference in case.references:
                html += (f'<li><a href="{escape(reference["url"], quote=True)}">'
                         f'{escape(reference["title"])}</a></li>')
            html += "</ul>"
        self.notes.setHtml(f"<div style='line-height:150%'>{html}</div>")
        self.check_notes.setHtml(f"<div style='line-height:150%'>{question_html}</div>")
        self.reveal_answer.setEnabled(bool(case.questions) and not show_answer)
        self.read_question.setEnabled(bool(case.questions) and show_answer)

    def _toggle_labels(self, on):
        self.view.show_labels = on
        self.view._rects = []
        self.view.set_hot(-1)
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
        if self.case is not None and 0 <= index < self.legend.count():
            self.legend.setCurrentRow(index)
            self.view.set_hot(index)
        names = self._names(index)
        if names:
            self.structuresPicked.emit(names, True, self.case.labels[index].side)

    def _legend_clicked(self, item):
        index = self.legend.row(item)
        self.view.set_hot(index)
        names = self._names(index)
        if names:
            self.structuresPicked.emit(names, True, self.case.labels[index].side)


class RadiologyBrowser(QWidget):
    """Search the installed cases without hiding unavailable source images."""

    caseChosen = Signal(str)

    def __init__(self, cases, parent=None):
        super().__init__(parent)
        self.cases = list(cases)
        self._current_case_id = None
        self._visible_ids = []
        self.setAccessibleName("Radiology case library")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(8)
        heading = QLabel("Radiology library")
        heading.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_TITLE, 700))
        lay.addWidget(heading)
        intro = QLabel("Open an existing case and study its image alongside the authored 3D reference. "
                       "The reference is not registered to the scan.")
        intro.setWordWrap(True)
        intro.setStyleSheet(theme.text_css(theme.TEXT_2, theme.FS_SMALL))
        lay.addWidget(intro)
        self.filter = QLineEdit()
        self.filter.setAccessibleName("Search radiology cases")
        self.filter.setPlaceholderText("Search anatomy, finding or scan…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._fill)
        self.filter.installEventFilter(self)
        lay.addWidget(self.filter)
        self.refine = control("Hide filters", "Show or hide radiology filters")
        self.refine.setCheckable(True)
        self.refine.setChecked(True)
        theme.set_variant(self.refine, "ghost")
        lay.addWidget(self.refine)
        self.filter_panel = QWidget()
        filters_layout = QVBoxLayout(self.filter_panel)
        filters_layout.setContentsMargins(0, 0, 0, 0)
        filters_layout.setSpacing(6)
        self.filters = {}
        for field, label in (("modality", "All modalities"), ("region", "All regions"),
                             ("plane", "All planes / projections"), ("finding", "All findings")):
            combo = QComboBox()
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(10)
            combo.setMinimumWidth(0)
            combo.setAccessibleName(label)
            combo.addItem(label, None)
            for value in sorted({str(getattr(case, field, "")) for case in self.cases}):
                if value:
                    combo.addItem(value, value)
            combo.currentIndexChanged.connect(self._fill)
            self.filters[field] = combo
            filters_layout.addWidget(combo)
        lay.addWidget(self.filter_panel)
        self.refine.toggled.connect(self._toggle_filters)
        summary = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_CAPTION))
        summary.addWidget(self.count_label, 1)
        self.clear_filters = control("Clear", "Clear all radiology filters")
        self.clear_filters.clicked.connect(self.reset_filters)
        theme.set_variant(self.clear_filters, "ghost")
        summary.addWidget(self.clear_filters)
        lay.addLayout(summary)
        self.list = CardList()
        self.list.setAccessibleName("Radiology cases")
        self.list.itemClicked.connect(self._chosen)
        self.list.itemActivated.connect(self._chosen)
        lay.addWidget(self.list, 1)
        self.empty_state = QLabel()
        self.empty_state.setWordWrap(True)
        self.empty_state.setStyleSheet(theme.text_css(theme.TEXT_2))
        lay.addWidget(self.empty_state)
        self.open_case = control("Open selected case", "Open selected radiology case")
        theme.set_variant(self.open_case, "primary")
        self.open_case.clicked.connect(lambda: self._chosen(self.list.currentItem()))
        self.list.currentItemChanged.connect(lambda *_: self.open_case.setEnabled(
            bool(self.list.currentItem() and self.list.currentItem().data(Qt.UserRole))))
        lay.addWidget(self.open_case)
        self._fill()

    def _toggle_filters(self, visible):
        self.filter_panel.setVisible(visible)
        self.refine.setText("Hide filters" if visible else "Show filters")

    def reset_filters(self):
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.blockSignals(False)
        for combo in self.filters.values():
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self._fill()
        self.filter.setFocus()

    def visible_case_ids(self):
        return list(self._visible_ids)

    def set_current_case(self, case_id):
        self._current_case_id = case_id
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(Qt.UserRole) == case_id:
                self.list.setCurrentItem(item)
                self.list.scrollToItem(item)
                return

    def _fill(self, *_):
        needle = self.filter.text()
        selected = self.list.currentItem()
        selected_id = selected.data(Qt.UserRole) if selected else self._current_case_id
        self.list.clear()
        by_region = {}
        for case in self.cases:
            if not matches_words(needle, case.search_text):
                continue
            if any(combo.currentData() is not None and getattr(case, field) != combo.currentData()
                   for field, combo in self.filters.items()):
                continue
            by_region.setdefault(case.region, []).append(case)
        self._visible_ids = []
        for region in sorted(by_region):
            self.list.add_header(region)
            for case in by_region[region]:
                self._visible_ids.append(case.id)
                available = bool(getattr(case, "has_image", True))
                summary = case.summary + ("  Image file is missing." if not available else "")
                item = self.list.add_card(case.title, summary, badge=case.modality,
                                         accent=theme.ACCENT, data=case.id,
                                         tooltip=f"{case.modality} · {case.plane} · {case.finding} · {len(case.labels)} labels")
                item.setData(Qt.AccessibleTextRole, f"{case.title}. {case.modality}. {summary}")
                if case.id == selected_id:
                    self.list.setCurrentItem(item)
        matched = len(self._visible_ids)
        self.count_label.setText(f"{matched} of {len(self.cases)} cases")
        self.empty_state.setVisible(matched == 0)
        self.empty_state.setText("No case matches these filters. Clear the filters or try another search."
                                 if self.cases else "No radiology cases are installed. Restore the case catalogue and image files, then reopen the app.")
        self.clear_filters.setEnabled(bool(needle.strip()) or any(c.currentIndex() for c in self.filters.values()))
        self.open_case.setEnabled(bool(self.list.currentItem()))

    def eventFilter(self, watched, event):
        if watched is self.filter and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Down:
                for row in range(self.list.count()):
                    if self.list.item(row).data(Qt.UserRole):
                        self.list.setCurrentRow(row)
                        self.list.setFocus()
                        return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                item = self.list.currentItem()
                if item is None:
                    item = next((self.list.item(row) for row in range(self.list.count())
                                 if self.list.item(row).data(Qt.UserRole)), None)
                self._chosen(item)
                return True
        return super().eventFilter(watched, event)

    def _chosen(self, item):
        cid = item.data(Qt.UserRole) if item is not None else None
        if cid:
            self._current_case_id = cid
            self.caseChosen.emit(cid)
