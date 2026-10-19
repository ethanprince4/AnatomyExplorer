"""Actual Qt painting across nested workspace boundaries, not stylesheet strings."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PySide6.QtWidgets import QApplication, QWidget, QTabWidget, QVBoxLayout, QPushButton
from app.ui import theme
from app.ui.wall_background import viewport_background

APP = QApplication.instance() or QApplication([])


class GalleryWallTests(unittest.TestCase):
    def setUp(self):
        theme.apply_theme(APP, mode='gallery-slate')
        self.root = QWidget()
        self.root.setObjectName('studioShell')
        self.root.resize(600, 600)
        layout = QVBoxLayout(self.root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QWidget()
        header.setObjectName('studioHeader')
        header.setFixedHeight(80)
        layout.addWidget(header)
        tabs = QTabWidget()
        tabs.setObjectName('studioWorkspaces')
        tabs.tabBar().hide()
        layout.addWidget(tabs)
        page = QWidget()
        tabs.addTab(page, 'Model')
        self.scene = QWidget(page)
        self.scene.setObjectName('studioScene')
        inner = QVBoxLayout(page)
        inner.addWidget(self.scene)
        self.button = QPushButton('Learn', self.scene)
        theme.set_variant(self.button, 'primary')
        self.button.setGeometry(100, 120, 120, 40)
        self.root.show()
        APP.processEvents()

    def tearDown(self):
        self.root.close()
        self.root.deleteLater()
        APP.processEvents()

    def test_nested_pages_inherit_one_wall_without_panel_seams(self):
        image = self.root.grab().toImage()
        palette = theme.palette()
        for y in (5, 79, 81, 300, 590):
            probe = QWidget(self.root)
            probe.setGeometry(0, y, 10, 1)
            sample = viewport_background(probe, {'custom_background': True,
                'bg_top': palette['stage_top'], 'bg_bottom': palette['stage_bottom']})
            from PySide6.QtGui import QColor
            actual = image.pixelColor(5, y)
            expected = QColor(sample['bg_top'])
            self.assertLessEqual(max(abs(a-b) for a, b in zip(actual.getRgb(), expected.getRgb())), 1)

    def test_primary_action_keeps_fill_and_white_text_in_nested_workspace(self):
        image = self.button.grab().toImage()
        self.assertEqual(image.pixelColor(8, 8).name(), '#765b33')
        pixels = [image.pixelColor(x, y).name() for x in range(35, 85) for y in range(10, 30)]
        self.assertIn('#ffffff', pixels)

    def test_parts_outline_does_not_paint_a_solid_empty_rectangle(self):
        from app.ui.outline import Outline
        from PySide6.QtCore import QPoint
        tree = Outline(self.scene)
        tree.setProperty('wallLettering', True)
        tree.viewport().setAutoFillBackground(False)
        tree.setStyleSheet('Outline, Outline QWidget {background:transparent;border:0;}')
        tree.setGeometry(250, 50, 180, 300)
        tree.show()
        APP.processEvents()
        image = self.root.grab().toImage()
        point = tree.viewport().mapTo(self.root, QPoint(10, 200))
        self.assertEqual(image.pixelColor(point), image.pixelColor(5, point.y()))


if __name__ == '__main__':
    unittest.main()
