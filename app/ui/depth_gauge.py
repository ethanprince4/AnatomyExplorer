"""The selected Specimen measuring rule, backed by Qt's accessible slider."""
from PySide6.QtCore import Qt, QRectF, QPointF, QSize, Signal
from PySide6.QtGui import QFont, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QSlider
from . import theme


class DepthGauge(QSlider):
    onlyLayerToggled = Signal(bool)

    def __init__(self, stops, parent=None):
        super().__init__(Qt.Vertical, parent)
        self.stops = tuple((float(level), str(name)) for level, name in stops)
        self.setRange(0, 1000)
        self.setInvertedAppearance(True)
        self.setInvertedControls(True)
        self.setSingleStep(10)
        self.setPageStep(100)
        self.setAccessibleName('Dissection depth')
        self.setAccessibleDescription('Reveal available anatomy from superficial to deep.')
        self.setToolTip('Arrow keys move 1%; Page Up/Down move 10%; brackets step between layers.')
        self.setFocusPolicy(Qt.StrongFocus)
        self.setObjectName('dissectionDepthGauge')
        # The generic QSlider stylesheet has a 24px minimum. The painted rule
        # needs its own minimum and size hint when embedded in a scroll layout.
        self.setStyleSheet('QSlider#dissectionDepthGauge {min-height:460px;padding:0;}')
        self.setMinimumSize(230, 460)
        self.only_layer = QCheckBox('Show only this layer', self)
        self.only_layer.setAccessibleName('Show only the current dissection layer')
        self.only_layer.toggled.connect(self.onlyLayerToggled)
        self.only_layer.toggled.connect(lambda _on:self.update())
        # QSlider invalidates only its native handle, not our rule/captions/focus ring.
        self.valueChanged.connect(self._value_changed)

    def sizeHint(self):
        return QSize(280, 520)

    def _scale(self):
        screen_scale=max(1.0,min(1.35,self.height()/820))
        return max(.8, min(1.6, self.font().pointSizeF() / theme.FS_BODY * screen_scale))

    def setValue(self, value):
        super().setValue(value)
        # Programmatic synchronization blocks signals; repaint and move the checkbox anyway.
        self._value_changed()

    def _rule(self):
        s = self._scale()
        return self.width()-56*s, 30*s, self.height()-40*s

    def _point_y(self, level):
        _, top, bottom = self._rule()
        return top + max(1, bottom-top)*max(0, min(1, level))

    def _current_stop(self):
        return next(((v,n) for v,n in reversed(self.stops) if v <= self.value()/1000+1e-6), self.stops[0])

    def _value_changed(self, _value=None):
        self._layout_checkbox()
        self.update()

    def set_only_layer(self, enabled):
        blocked = self.only_layer.blockSignals(True)
        self.only_layer.setChecked(bool(enabled))
        self.only_layer.blockSignals(blocked)
        self.update()

    def _layout_checkbox(self):
        line_x, _, _ = self._rule()
        s = self._scale()
        level, _ = self._current_stop()
        y = self._point_y(level)
        nxt = next((v for v,_ in self.stops if v > level), 1)
        compact = self._point_y(nxt)-y < 55*s
        self.only_layer.setStyleSheet(
            f'QCheckBox {{background:transparent;border:0;color:{theme.TEXT_2};'
            f'font-family:"{theme.font_family()}";font-size:{13*s}px;spacing:6px;}}'
            f'QCheckBox::indicator {{width:{12*s}px;height:{12*s}px;border-radius:0;}}')
        height = max(round(20*s),self.only_layer.sizeHint().height())
        width = min(round(line_x-22*s),self.only_layer.sizeHint().width())
        # Short windows cannot fit another line between the first two stop names.
        by = self.height()-height if compact else round(y+18*s)
        self.only_layer.setGeometry(round(line_x-24*s-width),by,width,height)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self._layout_checkbox()

    def focusInEvent(self,event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self,event):
        super().focusOutEvent(event)
        self.update()

    def paintEvent(self,event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        s = self._scale()
        x,top,bottom = self._rule()
        current = self.value()/1000
        palette = theme.palette()
        p.setPen(QPen(theme.qc(palette['leader']),1))
        p.drawLine(QPointF(x,top),QPointF(x,bottom))
        p.setPen(QPen(theme.qc(theme.MUTED,179),1))
        for percent in range(0,101,2):
            y = self._point_y(percent/100)
            length = (9 if percent%10 == 0 else 5)*s
            p.drawLine(QPointF(x-length,y),QPointF(x-3*s,y))
        p.setPen(QPen(theme.qc(theme.ACCENT),3*s))
        p.drawLine(QPointF(x,top),QPointF(x,self._point_y(current)))
        stop,_ = self._current_stop()
        for level,name in self.stops:
            y = self._point_y(level)
            p.setPen(QPen(theme.qc(palette['leader']),1))
            p.drawLine(QPointF(x-17*s,y),QPointF(x-3*s,y))
            font = theme.font_for('prose',size=20 if level==stop else 16,
                                  weight=460 if level==stop else 400,scale=s)
            font.setItalic(True)
            p.setFont(font)
            p.setPen(theme.qc(theme.TEXT if level==stop else theme.MUTED if level<stop else theme.TEXT_2))
            fm = p.fontMetrics()
            box = QRectF(0,y-fm.height()/2,x-24*s,fm.height())
            p.drawText(box,Qt.AlignRight|Qt.AlignVCenter,fm.elidedText(name,Qt.ElideRight,int(box.width())))
        font = theme.font_for('micro',size=11,weight=500,scale=s)
        font.setLetterSpacing(QFont.AbsoluteSpacing,1*s)
        p.setFont(font)
        p.setPen(theme.qc(theme.MUTED))
        for text,y in (('SUPERFICIAL',top-28*s),('DEEP',bottom+8*s)):
            p.drawText(QRectF(x-60*s,y,120*s,20*s),Qt.AlignHCenter|Qt.AlignVCenter,text)
        y = self._point_y(current)
        if self.only_layer.isChecked():
            p.setPen(QPen(theme.qc(palette['leader']),1))
            end = self._point_y(min(1,current+.13))
            p.drawLine(QPointF(x+8*s,y),QPointF(x+8*s,end))
            p.drawLine(QPointF(x+8*s,end),QPointF(x+13*s,end))
        p.setPen(Qt.NoPen)
        p.setBrush(theme.qc(theme.ACCENT))
        p.drawEllipse(QPointF(x,y),4.5*s,4.5*s)
        p.setFont(theme.font_for('meta',weight=600,scale=s))
        p.setPen(theme.qc(theme.ACCENT_TEXT))
        p.drawText(QRectF(x+13*s,y-12*s,43*s,24*s),Qt.AlignLeft|Qt.AlignVCenter,f'{current*100:.0f}%')
        if self.hasFocus():
            p.setPen(QPen(theme.qc(theme.TEXT),1.5*s))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(x,y),9*s,9*s)
        p.end()

    def _set_pointer_value(self,event):
        _,top,bottom = self._rule()
        ratio = (event.position().y()-top)/max(1,bottom-top)
        self.setValue(round(max(0,min(1,ratio))*1000))

    def mousePressEvent(self,event):
        if event.button() == Qt.LeftButton:
            self.setFocus(Qt.MouseFocusReason)
            self.setSliderDown(True)
            self._set_pointer_value(event)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self.isSliderDown():
            self._set_pointer_value(event)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton and self.isSliderDown():
            self._set_pointer_value(event)
            self.setSliderDown(False)
            self.update()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self,event):
        steps = {Qt.Key_Down:10,Qt.Key_Right:10,Qt.Key_Up:-10,Qt.Key_Left:-10,Qt.Key_PageDown:100,Qt.Key_PageUp:-100}
        if event.key() in steps:
            self.setValue(self.value()+steps[event.key()])
        elif event.key()==Qt.Key_Home:
            self.setValue(self.minimum())
        elif event.key()==Qt.Key_End:
            self.setValue(self.maximum())
        elif event.key() in (Qt.Key_BracketLeft,Qt.Key_BracketRight):
            value = self.value()/1000
            levels = [v for v,_ in self.stops]
            nxt = (next((v for v in levels if v>value+1e-4),1) if event.key()==Qt.Key_BracketRight
                   else next((v for v in reversed(levels) if v<value-1e-4),0))
            self.setValue(round(nxt*1000))
        else:
            super().keyPressEvent(event)
            return
        event.accept()
