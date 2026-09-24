"""Draws the application icon (app/resources/icon.png + icon.ico)."""
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPen, QBrush

app = QGuiApplication(sys.argv)
out = Path(__file__).resolve().parents[1] / "app" / "resources"
S = 256
img = QImage(S, S, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
g = QLinearGradient(0, 0, 0, S)
g.setColorAt(0, QColor("#1e2630"))
g.setColorAt(1, QColor("#0c0f13"))
p.setBrush(QBrush(g))
p.setPen(Qt.NoPen)
p.drawRoundedRect(QRectF(8, 8, S - 16, S - 16), 52, 52)
p.setPen(QPen(QColor("#4fc3f7"), 10))
p.setBrush(Qt.NoBrush)
p.drawEllipse(QRectF(40, 40, S - 80, S - 80))
p.setPen(Qt.NoPen)
for i in range(7):
    w = 58 - abs(i - 2.5) * 6
    y = 62 + i * 19
    p.setBrush(QColor("#e8dcc6") if i % 2 == 0 else QColor("#d7c9b0"))
    p.drawRoundedRect(QRectF(S / 2 - w / 2, y, w, 14), 6, 6)
p.setBrush(QColor("#b4433a"))
p.drawEllipse(QRectF(S / 2 - 64, 110, 26, 40))
p.drawEllipse(QRectF(S / 2 + 38, 110, 26, 40))
p.end()
img.save(str(out / "icon.png"))
ok = img.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(out / "icon.ico"))
print("ico saved:", ok)
