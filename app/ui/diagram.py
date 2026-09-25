"""Lesson diagrams: the hand-drawn SVGs in data/content/diagrams, shown inside a lesson step or a practice item.

A diagram covers what the 3D atlas cannot show - an ECG trace, a spirogram, a reflex arc, the loop the blood
takes round the body. They are drawn for the dark theme (light strokes on a transparent background), so they are
painted straight onto the panel and always at the width the panel has, never a blurry fixed-size bitmap.
"""
from PySide6.QtCore import QEvent, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout,
                               QWidget)

from ..lessons import diagram_path
from . import theme

_RENDERERS = {}


def renderer(diagram_id):
    """A cached QSvgRenderer for a diagram id, or None when there is no such file or it will not parse."""
    if diagram_id in _RENDERERS:
        return _RENDERERS[diagram_id]
    path = diagram_path(diagram_id)
    r = QSvgRenderer(str(path)) if path is not None else None
    if r is not None and not r.isValid():
        r = None
    _RENDERERS[diagram_id] = r
    return r


def aspect(r):
    """Height over width of a diagram, from its viewBox when it has one."""
    box = r.viewBoxF()
    size = box.size() if box.isValid() and not box.isEmpty() else QSizeF(r.defaultSize())
    if size.width() <= 0:
        return 0.6
    return size.height() / size.width()


def render_image(diagram_id, width, dpr=1.0, max_height=None):
    """The diagram painted into a transparent QImage `width` logical pixels wide (less if max_height caps it)."""
    r = renderer(diagram_id)
    if r is None or width < 20:
        return None
    ratio = aspect(r)
    w = float(width)
    if max_height and w * ratio > max_height:
        w = max_height / ratio
    h = w * ratio
    img = QImage(max(1, int(w * dpr)), max(1, int(h * dpr)), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, img.width(), img.height()))
    p.end()
    img.setDevicePixelRatio(dpr)
    return img


class DiagramView(QWidget):
    """A diagram that fills the width it is given and keeps its proportions."""

    def __init__(self, parent=None, max_height=320, zoomable=True):
        super().__init__(parent)
        self.diagram_id = None
        self.max_height = max_height
        self.zoomable = zoomable
        if zoomable:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Click to enlarge")
        sp = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    def set_diagram(self, diagram_id):
        self.diagram_id = diagram_id if diagram_id and renderer(diagram_id) is not None else None
        self.setVisible(self.diagram_id is not None)
        self.updateGeometry()
        self.update()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        r = renderer(self.diagram_id) if self.diagram_id else None
        if r is None:
            return 0
        return int(min(self.max_height, w * aspect(r)))

    def sizeHint(self):
        w = max(200, self.width())
        return QSize(w, self.heightForWidth(w))

    def paintEvent(self, event):
        r = renderer(self.diagram_id) if self.diagram_id else None
        if r is None:
            return
        ratio = aspect(r)
        w = min(float(self.width()), self.height() / ratio if ratio else self.width())
        h = w * ratio
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r.render(p, QRectF((self.width() - w) / 2, 0, w, h))
        p.end()

    def mousePressEvent(self, e):
        if self.zoomable and self.diagram_id and e.button() == Qt.LeftButton:
            show_large(self.diagram_id, self)


def show_large(diagram_id, parent=None):
    """The diagram in a window of its own, as large as the screen allows - small print in a narrow panel is
    not much use."""
    if renderer(diagram_id) is None:
        return
    dlg = QDialog(parent)
    dlg.setWindowTitle("Diagram")
    dlg.setStyleSheet(f"background:{theme.SUNKEN};")
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(16, 16, 16, 16)
    view = DiagramView(dlg, max_height=10000, zoomable=False)
    view.set_diagram(diagram_id)
    lay.addWidget(view)
    screen = (parent.screen() if parent is not None else None)
    avail = screen.availableGeometry() if screen is not None else None
    w = int(avail.width() * 0.7) if avail is not None else 1000
    h = min(int(w * aspect(renderer(diagram_id))) + 32, int(avail.height() * 0.85) if avail is not None else 800)
    dlg.resize(w, h)
    dlg.exec()


class DiagramOverlay(QFrame):
    """A lesson step's diagram as a card over the 3D view.

    The lesson panel is ~330 px wide and the diagrams are drawn at ~900 with 12 px text, so squeezed into the
    panel their labels are unreadable. The card sits in the top-right corner of the centre area at up to about
    half its width (never larger than the diagram's own size), can be collapsed to a small tab so it never
    hides the model for long, and opens full size in a window of its own."""

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.diagram_id = None
        self.collapsed = False
        self.setObjectName("diagramOverlay")
        o = theme.qc(theme.OVERLAY)
        self.setStyleSheet(f"#diagramOverlay {{ background: rgba({o.red()}, {o.green()}, {o.blue()}, 242);"
                           f" border: 1px solid {theme.BORDER_STRONG}; border-radius: {theme.R_XL}px; }}"
                           f" QLabel {{ color: {theme.TEXT_STRONG}; font-weight: 700; background: transparent; }}"
                           f" QToolButton {{ color: {theme.TEXT_2}; background: transparent; border: 1px solid transparent;"
                           f" padding: 2px 8px; border-radius: {theme.R_MD}px; font-weight: 600; }}"
                           f" QToolButton:hover {{ color: {theme.TEXT_STRONG}; background: {theme.HOVER}; }}"
                           f" QToolButton:focus {{ border-color: {theme.ACCENT}; }}"
                           f" DiagramView {{ background: transparent; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 10, 12)
        lay.setSpacing(6)
        top = QHBoxLayout()
        self.title = QLabel("Diagram")
        top.addWidget(self.title, 1)
        self.big_btn = QToolButton()
        self.big_btn.setText("⤢")
        self.big_btn.setToolTip("Open full size")
        self.big_btn.clicked.connect(lambda: show_large(self.diagram_id, self.window()) if self.diagram_id else None)
        self.fold_btn = QToolButton()
        self.fold_btn.clicked.connect(lambda: self.set_collapsed(not self.collapsed))
        top.addWidget(self.big_btn)
        top.addWidget(self.fold_btn)
        lay.addLayout(top)
        self.view = DiagramView(self, max_height=10000)
        lay.addWidget(self.view, 1)
        host.installEventFilter(self)
        self.hide()

    def set_diagram(self, diagram_id):
        r = renderer(diagram_id) if diagram_id else None
        self.diagram_id = diagram_id if r is not None else None
        if self.diagram_id is None:
            self.hide()
            return
        self.view.set_diagram(self.diagram_id)
        path = diagram_path(self.diagram_id)
        title = "Diagram"
        try:
            import re
            m = re.search(r"<title>(.*?)</title>", path.read_text(encoding="utf-8"), re.S)
            title = m.group(1).strip() if m else title
        except OSError:
            pass
        self.title.setText(title)
        self.set_collapsed(False)
        self.show()
        self.raise_()

    def set_collapsed(self, on):
        self.collapsed = on
        self.view.setVisible(not on)
        self.big_btn.setVisible(not on)
        self.fold_btn.setText("Show diagram ▾" if on else "–")
        self.fold_btn.setToolTip("Show the diagram" if on else "Tuck the diagram away")
        self._place()

    def eventFilter(self, obj, event):
        if obj is self.host and event.type() == QEvent.Resize:
            self._place()
        return False

    def _place(self):
        if self.diagram_id is None:
            return
        hw, hh = self.host.width(), self.host.height()
        if self.collapsed:
            self.adjustSize()
            sw = self.sizeHint().width()
            self.setGeometry(hw - sw - 12, 12, sw, self.sizeHint().height())
            return
        r = renderer(self.diagram_id)
        box = r.viewBoxF()
        natural = box.width() if box.isValid() and not box.isEmpty() else r.defaultSize().width()
        w = int(min(max(hw * 0.52, min(460, hw - 24)), natural + 20, hw - 24))
        h = int(w * aspect(r)) + 44
        if h > hh * 0.75:
            h = int(hh * 0.75)
            w = int((h - 44) / aspect(r)) + 20
        w, h = max(200, w), max(120, h)
        self.setGeometry(hw - w - 12, 12, w, h)      # top-right: clear of a micro model's side panel
        self.raise_()
