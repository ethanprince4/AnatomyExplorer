"""Image export regressions using raster fixtures; no OpenGL context is created."""
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from test_state_and_recovery import MainWindow, QAPP, config
from app.ui import theme

FONT = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
# Windows' offscreen platform has no automatic system-font discovery. Register
# one for readable local evidence while keeping the tests portable.
font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
if font_path.is_file():
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    families = QFontDatabase.applicationFontFamilies(font_id)
    if families:
        FONT = QFont(families[0], 10)


def capture_image(dpr):
    image = QImage(round(640 * dpr), round(360 * dpr), QImage.Format_RGB32)
    image.setDevicePixelRatio(dpr)
    image.fill(QColor("#253d4e"))
    painter = QPainter(image)
    painter.fillRect(0, 0, 640, 8, QColor("#d24b57"))
    painter.fillRect(0, 352, 640, 8, QColor("#43b985"))
    painter.setPen(QColor("#ffffff"))
    painter.setFont(FONT)
    painter.drawText(0, 0, 640, 360, Qt.AlignCenter,
                     f"Complete screenshot fixture at {dpr:g}x display scale")
    painter.end()
    return image


def stub_window(image):
    messages = []
    window = SimpleNamespace(
        _capture_widget=lambda: SimpleNamespace(grab=lambda: QPixmap.fromImage(image)),
        _figure_caption=lambda: (
            "Frontal bone",
            ["Sagittal section through: Frontal bone, Parietal bone", "20 structures visible"],
            "Anatomy Explorer · BodyParts3D / Z-Anatomy, CC BY-SA"),
        settings=dict(config.DEFAULT_SETTINGS), font=lambda: FONT,
        statusBar=lambda: SimpleNamespace(showMessage=lambda text, *args: messages.append(text)),
    )
    return window, messages


class FigureExportTests(unittest.TestCase):
    def test_caption_credit_and_entire_capture_survive_display_scaling(self):
        with tempfile.TemporaryDirectory(prefix="anatomy-export-") as folder:
            for dpr in (1.0, 1.5, 2.0):
                with self.subTest(dpr=dpr):
                    capture = capture_image(dpr)
                    window, messages = stub_window(capture)
                    path = Path(folder) / f"figure-{dpr}.png"
                    MainWindow.export_figure(window, str(path))
                    result = QImage(str(path))
                    self.assertFalse(result.isNull())
                    self.assertEqual(result.width(), capture.width())
                    # The unique top strip locates the shot; its exact physical
                    # rectangle must be copied without clipping or resampling.
                    x = result.width() // 2
                    top_color = capture.pixelColor(x, 0)
                    top = next(y for y in range(result.height()) if result.pixelColor(x, y) == top_color)
                    extracted = result.copy(0, top, capture.width(), capture.height())
                    expected = QImage(capture)
                    expected.setDevicePixelRatio(1.0)
                    self.assertEqual(extracted, expected)
                    # Both caption and credit need painted text below the shot.
                    bg = QColor(theme.CANVAS)
                    ink_rows = []
                    for y in range(top + capture.height(), result.height()):
                        if any(result.pixelColor(px, y) != bg for px in range(result.width())):
                            ink_rows.append(y)
                    groups = 0
                    last = -2
                    for y in ink_rows:
                        if y > last + 1:
                            groups += 1
                        last = y
                    self.assertGreaterEqual(groups, 2, "caption and credit must both remain visible")
                    self.assertTrue(messages[-1].startswith("Saved "))

    def test_screenshot_failure_reports_error_without_claiming_success(self):
        with tempfile.TemporaryDirectory(prefix="anatomy-export-") as folder:
            window, messages = stub_window(capture_image(1.0))
            path = Path(folder) / "missing-directory" / "screenshot.png"
            MainWindow.screenshot(window, str(path))
            self.assertFalse(path.exists())
            self.assertTrue(messages[-1].startswith("Could not save screenshot:"), messages[-1])

    def test_figure_failure_preserves_clipboard_and_reports_error(self):
        with tempfile.TemporaryDirectory(prefix="anatomy-export-") as folder:
            window, messages = stub_window(capture_image(1.0))
            path = Path(folder) / "missing-directory" / "figure.png"
            clipboard = SimpleNamespace(setImage=lambda image: self.fail("failed saves must not replace the clipboard"))
            with patch("app.main_window.QGuiApplication.clipboard", return_value=clipboard):
                MainWindow.export_figure(window, str(path))
            self.assertFalse(path.exists())
            self.assertTrue(messages[-1].startswith("Could not export figure:"), messages[-1])


if __name__ == "__main__":
    unittest.main()
