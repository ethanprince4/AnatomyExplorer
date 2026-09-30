"""Restored borderless initialization belongs to the MainWindow QObject lifetime."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "app/main_window.py").exists())
sys.path.insert(0, str(ROOT))
from test_state_and_recovery import QAPP, MainWindow, Dataset, config
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, Qt


class StartupCloseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset(config.DATA_DIR)

    def setUp(self):
        self.errors = []
        hook = patch("sys.excepthook", lambda kind, value, tb: self.errors.append(str(value)))
        hook.start()
        self.addCleanup(hook.stop)
        fixture_root = Path(config.USER_DIR).resolve().parent
        self.assertTrue(fixture_root.name.startswith("anatomy-regression-"))
        self.prefs = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
        self.assertTrue(Path(self.prefs.fileName()).resolve().is_relative_to(fixture_root))
        self.prefs.clear()
        self.prefs.setValue("borderless", "true")
        self.prefs.sync()

    def _destroy(self, win):
        win.close()
        win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QAPP.processEvents()

    def test_immediate_window_delete_cancels_restored_borderless_callback(self):
        win = MainWindow(self.dataset, restore=True)
        self.assertIsNone(win.viewport.renderer)
        self._destroy(win)
        self.assertEqual(self.errors, [])

    def test_alive_window_still_applies_restored_borderless_preference(self):
        win = MainWindow(self.dataset, restore=True)
        try:
            self.assertFalse(win._borderless)
            QAPP.processEvents()
            self.assertTrue(win._borderless)
            self.assertTrue(win.windowFlags() & Qt.FramelessWindowHint)
            self.assertEqual(self.errors, [])
        finally:
            self._destroy(win)

    def test_no_restore_keeps_saved_borderless_preference_without_applying_it(self):
        win = MainWindow(self.dataset, restore=False)
        try:
            QAPP.processEvents()
            self.assertFalse(win._borderless)
            self.assertEqual(self.prefs.value("borderless"), "true")
            self.assertEqual(self.errors, [])
        finally:
            self._destroy(win)


if __name__ == "__main__":
    unittest.main()
