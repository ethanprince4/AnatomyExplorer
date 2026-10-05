"""Approved palette/font/semantic integration without any rendering."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from PySide6.QtWidgets import QApplication, QWidget, QPushButton
from PySide6.QtGui import QPalette, QFontDatabase
from app.ui import theme, studio_style
APP=QApplication.instance() or QApplication([])

class StudioThemeTests(unittest.TestCase):
    def tearDown(self): theme.apply_theme(APP,mode='porcelain')
    def test_approved_palette_roles(self):
        p=studio_style.palette('porcelain')
        self.assertEqual(p['paper'],'#2D3C52')
        self.assertEqual(p['paper_text'],'#FAFBFC')
        self.assertEqual(p['accent'],'#364F99')
        theme.apply_theme(APP,mode='porcelain')
        self.assertEqual(APP.palette().color(QPalette.Highlight).name(),p['accent'].lower())
        self.assertEqual(theme.TEXT,p['text'].lower())
        for name in ['surface','selectionSurface','globalBar','globalSearch','dock']:
            self.assertIn('#'+name,APP.styleSheet())
    def test_assets_and_fonts_available(self):
        for mode in ['porcelain','slate']:
            for name in ['search','down','check']:
                self.assertFalse(studio_style.icon(name,mode).isNull())
        self.assertTrue(theme.font_family())
        from unittest.mock import patch
        with patch.object(QFontDatabase, "families", return_value=["Noto Serif", "Georgia"]):
            self.assertEqual(studio_style.display_font_family(), "Georgia")
        self.assertTrue(studio_style.display_font_family())
    def test_legacy_and_invalid_preferences_use_only_porcelain(self):
        theme.apply_theme(APP,mode='slate')
        self.assertEqual(theme.THEME_NAME,'porcelain')
        self.assertEqual(list(theme.THEMES), ['porcelain'])
        self.assertEqual(studio_style.palette()['paper'],'#2D3C52')
        theme.set_theme('removed-mode')
        self.assertEqual(theme.THEME_NAME,'porcelain')
    def test_surface_preserves_real_child_and_action(self):
        host=QWidget();child=QPushButton('Real action',host);seen=[]
        child.clicked.connect(lambda:seen.append(True))
        self.assertIs(studio_style.apply_surface(host,'selectionSurface'),host)
        theme.set_variant(child,'paperAction');child.click()
        self.assertEqual(seen,[True]);self.assertIs(child.parent(),host)
        host.deleteLater()

if __name__=='__main__':unittest.main()
