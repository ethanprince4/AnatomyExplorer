"""Lesson diagrams: the hand-drawn SVGs in data/content/diagrams, shown inside a lesson step or a practice item.

A diagram covers what the 3D atlas cannot show - an ECG trace, a spirogram, a reflex arc, the loop the blood
takes round the body. They are drawn for the dark theme (light strokes on a transparent background), so they are
painted straight onto the panel and always at the width the panel has, never a blurry fixed-size bitmap.
"""
from PySide6.QtCore import QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QDialog, QSizePolicy, QVBoxLayout, QWidget

from ..lessons import diagram_path

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
    dlg.setStyleSheet("background:#12161b;")
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
