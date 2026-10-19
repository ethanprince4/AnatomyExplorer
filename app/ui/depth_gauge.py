"""Native, keyboard-accessible depth rule for atlas dissection."""

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QFont, QPainter, QPen
from PySide6.QtWidgets import QSlider

from . import theme


class DepthGauge(QSlider):
    """A vertical rule whose stop labels remain tied to the app's real depth values.

    It subclasses QSlider so Qt retains its native slider accessibility interface and value
    semantics. Pointer, wheel, keyboard, and accessibility changes therefore continue to use
    the same 0..1000 value consumed by ViewPanel.
    """

    def __init__(self, stops, parent=None):
        super().__init__(Qt.Vertical, parent)
        self.stops = tuple((float(level), str(name)) for level, name in stops)
        self.setRange(0, 1000)
        self.setInvertedAppearance(True)
        self.setInvertedControls(True)
        self.setSingleStep(10)
        self.setPageStep(100)
        self.setAccessibleName("Dissection depth")
        self.setAccessibleDescription("Move from intact anatomy toward deeper exposed structures.")
        self.setToolTip("Dissection depth. Use the arrow keys, Page Up and Page Down, Home or End.")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(300)
        self.setMinimumWidth(210)
        self.setMaximumWidth(280)

    def _point_y(self, level):
        top, bottom = 14.0, max(15.0, float(self.height()) - 14.0)
        return top + (bottom - top) * max(0.0, min(1.0, level))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setFont(self.font())
        left = 8.0
        right = float(self.width()) - 8.0
        line_x = right - p.fontMetrics().horizontalAdvance("100%") - 15.0
        top, bottom = 14.0, max(15.0, float(self.height()) - 14.0)
        current = self.value() / 1000.0

        p.setPen(QPen(theme.qc(theme.BORDER), 1.0))
        p.drawLine(int(line_x), int(top), int(line_x), int(bottom))
        p.setPen(QPen(theme.qc(theme.ACCENT), 3.0, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(int(line_x), int(top), int(line_x), int(self._point_y(current)))

        label_font = QFont(self.font())
        label_font.setItalic(True)
        label_font.setPointSizeF(max(theme.FS_SMALL, label_font.pointSizeF() - 0.4))
        p.setFont(label_font)
        fm = p.fontMetrics()
        for level, name in self.stops:
            y = self._point_y(level)
            major = level in (0.0, 0.16, 0.26, 0.4, 0.55, 0.7, 0.85)
            p.setPen(QPen(theme.qc(theme.MUTED if level < current else theme.TEXT_2), 1.0))
            p.drawLine(int(line_x - (6 if major else 3)), int(y), int(line_x + 2), int(y))
            p.setPen(theme.qc(theme.TEXT if abs(level - current) < 0.005 else
                              theme.TEXT_2 if level > current else theme.MUTED))
            text = fm.elidedText(name, Qt.ElideRight, max(20, int(line_x - left - 14)))
            p.drawText(QRectF(left, y-fm.height()/2, line_x-left-14, fm.height()),
                       Qt.AlignRight | Qt.AlignVCenter, text)

        knob_y = self._point_y(current)
        p.setPen(QPen(theme.qc(theme.SUNKEN), 2.0))
        p.setBrush(theme.qc(theme.ACCENT))
        p.drawEllipse(line_x - 7.5, knob_y - 7.5, 15.0, 15.0)
        p.setPen(theme.qc(theme.TEXT_STRONG))
        pct = f"{current * 100:.0f}%"
        pct_font = QFont(self.font())
        pct_font.setBold(True)
        p.setFont(pct_font)
        p.drawText(QRectF(line_x+13, knob_y-p.fontMetrics().height()/2,
                         right-line_x-10, p.fontMetrics().height()), Qt.AlignLeft | Qt.AlignVCenter, pct)

        if self.hasFocus():
            p.setPen(QPen(theme.qc(theme.TEXT), 2.0))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(line_x - 11.0, knob_y - 11.0, 22.0, 22.0)
        p.end()

    def _set_pointer_value(self, event):
        ratio = (event.position().y()-14.0) / max(1.0, self.height()-28.0)
        self.setValue(round(max(0.0, min(1.0, ratio))*1000))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setFocus(Qt.MouseFocusReason)
            self.setSliderDown(True)
            self._set_pointer_value(event)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self._set_pointer_value(event)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.isSliderDown():
            self._set_pointer_value(event)
            self.setSliderDown(False)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Down, Qt.Key_Right):
            self.setValue(min(self.maximum(), self.value() + 10))
            event.accept()
            return
        if event.key() in (Qt.Key_Up, Qt.Key_Left):
            self.setValue(max(self.minimum(), self.value() - 10))
            event.accept()
            return
        if event.key() == Qt.Key_PageDown:
            self.setValue(min(self.maximum(), self.value() + 100))
            event.accept()
            return
        if event.key() == Qt.Key_PageUp:
            self.setValue(max(self.minimum(), self.value() - 100))
            event.accept()
            return
        if event.key() == Qt.Key_Home:
            self.setValue(self.minimum())
            event.accept()
            return
        if event.key() == Qt.Key_End:
            self.setValue(self.maximum())
            event.accept()
            return
        if event.key() in (Qt.Key_BracketLeft, Qt.Key_BracketRight):
            value = self.value() / 1000.0
            levels = [level for level, _ in self.stops]
            if event.key() == Qt.Key_BracketRight:
                nxt = next((level for level in levels if level > value + 1e-4), 1.0)
            else:
                nxt = next((level for level in reversed(levels) if level < value - 1e-4), 0.0)
            self.setValue(round(nxt * 1000))
            event.accept()
            return
        super().keyPressEvent(event)
