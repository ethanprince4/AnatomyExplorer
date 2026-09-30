"""Real Qt key dispatch over current 2D histology; no GL renderer/model assets."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "app/main_window.py").exists())
sys.path.insert(0, str(ROOT))
from test_state_and_recovery import QAPP, MainWindow, Dataset, config
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from app.ui.model_view import ModelView
from general_fixtures import write_fixture_model


class HistologyKeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset(config.DATA_DIR)

    def setUp(self):
        self.callback_errors = []
        hook = patch("sys.excepthook", lambda kind, value, tb: self.callback_errors.append(value))
        hook.start()
        self.addCleanup(hook.stop)
        fixture_root = Path(config.USER_DIR).resolve().parent
        self.assertTrue(fixture_root.name.startswith("anatomy-regression-"))
        prefs = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
        self.assertTrue(Path(prefs.fileName()).resolve().is_relative_to(fixture_root))
        prefs.clear()
        self.win = MainWindow(self.dataset, restore=False)
        self.addCleanup(self._close)
        self.win.open_histology("simple_squamous", 0)
        self.viewer = self.win.center.currentWidget()
        # The current center page is 2D before show: the atlas GL widget stays hidden.
        self.win.show()
        self.win.activateWindow()
        # Native Cocoa window activation arrives asynchronously after show.
        # Wait for the actual condition; retain the active-window assertion.
        self.assertTrue(QTest.qWaitForWindowActive(self.win, 3000))
        self.assertIs(QAPP.activeWindow(), self.win)
        self.assertFalse(self.win.viewport.isVisible())

    def _close(self):
        self.win.close()
        self.win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QAPP.processEvents()
        self.assertFalse(self.callback_errors, self.callback_errors)

    def _key_pair(self, target):
        self.viewer.show_image(0)
        target.setFocus()
        QAPP.processEvents()
        QTest.keyClick(target, Qt.Key_PageDown)
        self.assertEqual(self.viewer.index, 1, "PageDown must advance exactly one actual image")
        QTest.keyClick(target, Qt.Key_PageUp)
        self.assertEqual(self.viewer.index, 0, "PageUp must return exactly one actual image")

    def test_page_keys_navigate_from_viewer_focus(self):
        self._key_pair(self.viewer)

    def test_page_keys_navigate_from_image_child_focus(self):
        self._key_pair(self.viewer.view)

    def test_page_keys_navigate_from_thumbnail_focus(self):
        self._key_pair(self.viewer.strip)

    def test_model_page_commands_follow_active_tab_without_changing_bindings(self):
        actions = [self.win.cmds.actions[k] for k in ("model_next_view", "model_prev_view")]
        bindings = [self.win.cmds.shortcuts(k) for k in ("model_next_view", "model_prev_view")]
        histology_enabled = [a.isEnabled() for a in actions]
        self.win.hide()
        path = Path(config.USER_DIR) / "owned-page-routing.glb"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_fixture_model(path)
        self.win.open_model_file(str(path))
        # Complete the model's zero-delay initialization while it is alive;
        # rapid-close pending-timer cancellation is a separate lifecycle check.
        QAPP.processEvents()
        model = self.win.active_model_view()
        self.assertIsInstance(model, ModelView)
        self.assertTrue(all(a.isEnabled() for a in actions), "model page commands restore on an actual owned model tab")
        self.assertIsNone(getattr(model.gl_widget, "renderer", None), "the hidden owned fixture requires no GPU")
        self.win.center.setCurrentWidget(self.viewer)
        self.assertFalse(any(a.isEnabled() for a in actions))
        self.win.center.setCurrentIndex(0)
        self.assertFalse(any(a.isEnabled() for a in actions))
        self.assertEqual([self.win.cmds.shortcuts(k) for k in ("model_next_view", "model_prev_view")], bindings)
        self.assertEqual(histology_enabled, [False, False], "inactive model page commands must not consume 2D input")


if __name__ == "__main__":
    unittest.main()
