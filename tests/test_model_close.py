"""Actual owned imported-model tabs closed before deferred camera work finishes."""
from pathlib import Path
import sys
import traceback
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "app/main_window.py").exists())
sys.path.insert(0, str(ROOT))
from test_state_and_recovery import QAPP, MainWindow, Dataset, config
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtTest import QTest
from app.ui.model_view import ModelView
from general_fixtures import write_fixture_model


class DeferredModelCloseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset(config.DATA_DIR)

    def setUp(self):
        fixture_root = Path(config.USER_DIR).resolve().parent
        self.assertTrue(fixture_root.name.startswith("anatomy-regression-"))
        prefs = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
        self.assertTrue(Path(prefs.fileName()).resolve().is_relative_to(fixture_root))
        prefs.clear()
        self.errors = []
        hook = patch("sys.excepthook", lambda kind, value, tb:
                     self.errors.append("".join(traceback.format_exception(kind, value, tb))))
        hook.start()
        self.addCleanup(hook.stop)
        self.win = MainWindow(self.dataset, restore=False)
        self.addCleanup(self._close)
        path = Path(config.USER_DIR) / "owned-deferred-close.glb"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_fixture_model(path)
        self.win.open_model_file(str(path))
        self.view = self.win.active_model_view()
        self.assertIsInstance(self.view, ModelView)
        self.assertIsNone(getattr(self.view.gl_widget, "renderer", None))

    def _close(self):
        self.win.close()
        self.win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QAPP.processEvents()

    def _close_tab(self):
        self.win._close_center_tab(self.win.center.indexOf(self.view))
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertEqual(self.win.center.count(), 1)
        self.assertFalse(self.win.micro_tabs)
        QAPP.processEvents()

    def test_close_before_zero_delay_initial_frame_cancels_deleted_view_callback(self):
        self._close_tab()
        QAPP.processEvents()
        self.assertFalse(self.errors, "closing the actual tab must cancel its queued camera reset:\n" + "\n".join(self.errors))

    def test_close_after_part_focus_cancels_delayed_frame_callback(self):
        QAPP.processEvents()  # finish normal initialization while this tab is alive
        part = self.view.mds.parts[0].name
        self.assertEqual(self.view.focus_parts([part]), [])
        self._close_tab()
        QTest.qWait(300)  # actual 250ms focus timer must have fired or been cancelled
        self.assertFalse(self.errors, "the closed model must not receive delayed part framing:\n" + "\n".join(self.errors))

    def test_live_model_still_receives_initial_and_delayed_framing(self):
        gl = self.view.gl_widget
        with patch.object(gl, "reset_view", wraps=gl.reset_view) as reset:
            QAPP.processEvents()
            self.assertTrue(reset.called, "normal zero-delay model initialization still runs")
        part = self.view.mds.parts[0].name
        with patch.object(gl, "frame_structures", wraps=gl.frame_structures) as frame:
            self.assertEqual(self.view.focus_parts([part]), [])
            immediate_calls = frame.call_count
            self.assertEqual(immediate_calls, 0, "part framing is deliberately deferred until initialization completes")
            QTest.qWait(300)
            frame.assert_called_once_with([0])
        self.assertFalse(self.errors, self.errors)


if __name__ == "__main__":
    unittest.main()
