"""A sfmodel: link, or a sketchfab: model id, saved by an older version fails quietly (no exception, no tab).

The window is built offscreen and never shown; geometry and model requests are blocked.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication
QAPP = QApplication.instance() or QApplication([])
USER = tempfile.TemporaryDirectory()
import app.config as config
config.USER_DIR = Path(USER.name) / 'user'
config.USER_DIR.mkdir()
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, USER.name)
from app.ui.theme import apply_theme
apply_theme(QAPP)
from app.data import Dataset
from app.main_window import MainWindow
from app.ui.model_loading import ModelLoader


class OldSketchfabLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset(config.DATA_DIR)

    def setUp(self):
        self.geometry = patch.object(Dataset, 'load_geometry', side_effect=AssertionError('Geometry is out of scope'))
        self.geometry.start()
        self.model = patch.object(ModelLoader, 'request', side_effect=RuntimeError('Fixture: model files unavailable'))
        self.model.start()
        self.errors = []
        self.hook = patch('sys.excepthook', lambda _kind, error, _tb: self.errors.append(str(error)))
        self.hook.start()
        self.window = MainWindow(self.ds, restore=False)

    def tearDown(self):
        self.window.settings['restore_session'] = False
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QAPP.processEvents()
        self.model.stop(); self.geometry.stop(); self.hook.stop()
        self.assertFalse(self.errors, self.errors)

    def test_old_sfmodel_link_does_nothing(self):
        win = self.window
        before = (set(win.micro_tabs), win.center.currentWidget())
        self.assertIsNone(win.on_link('sfmodel', '0123456789abcdef0123456789abcdef'))
        self.assertIsNone(win.on_link('sfmodel', ''))
        QAPP.processEvents()
        self.assertEqual((set(win.micro_tabs), win.center.currentWidget()), before)

    def test_old_sketchfab_model_id_gives_a_status_message(self):
        win = self.window
        win.open_micro('sketchfab:0123456789abcdef0123456789abcdef')
        QAPP.processEvents()
        self.assertFalse(any(key.startswith('sketchfab:') for key in win.micro_tabs))
        self.assertIn('There is no 3D model called sketchfab:', win.statusBar().currentMessage())

    def test_the_removed_modules_are_gone(self):
        import importlib
        for name in ('app.sketchfab', 'app.viewer.imported'):
            with self.assertRaises(ImportError):
                importlib.import_module(name)
        self.assertFalse(hasattr(MainWindow, 'open_local_model'))
        from app.viewer import catalog
        self.assertFalse(hasattr(catalog, 'DownloadedEntry'))


if __name__ == '__main__':
    unittest.main()
