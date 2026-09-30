"""Actual owned imported-model tabs closed before deferred camera work finishes."""
from pathlib import Path
import sys
import time
import traceback
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "app/main_window.py").exists())
sys.path.insert(0, str(ROOT))
from test_state_and_recovery import QAPP, MainWindow, Dataset, config
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QTimer
from PySide6.QtTest import QTest
from shiboken6 import isValid
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
        self.assertFalse(isValid(self.view), "the real model QObject must be deleted, not merely hidden")
        QAPP.processEvents()

    def _wait_until(self, predicate, message, timeout=5.0):
        # Qt timer intervals are scheduling requests, not an upper bound on
        # delivery. Observe the actual callback while continuing to pump events.
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            QAPP.processEvents()
            if not predicate():
                QTest.qWait(10)
        self.assertTrue(predicate(), f"{message} (deadline {timeout:.1f}s); errors={self.errors}")

    def test_close_before_zero_delay_initial_frame_cancels_deleted_view_callback(self):
        with patch.object(self.view.gl_widget, "reset_view") as reset:
            self._close_tab()
            QAPP.processEvents()
            reset.assert_not_called()
        self.assertFalse(self.errors, "closing the actual tab must cancel its queued camera reset:\n" + "\n".join(self.errors))

    def test_close_after_part_focus_cancels_delayed_frame_callback(self):
        QAPP.processEvents()  # finish normal initialization while this tab is alive
        part = self.view.mds.parts[0].name
        with patch.object(self.view.gl_widget, "frame_structures") as frame:
            self.assertEqual(self.view.focus_parts([part]), [])
            # A later timer attached to the surviving window proves the event
            # loop has delivered delayed work beyond the focus timer's interval.
            control = []
            QTimer.singleShot(350, self.win, lambda: control.append(True))
            self._close_tab()
            self._wait_until(lambda: bool(control), "surviving control timer did not fire")
            QAPP.processEvents()
            frame.assert_not_called()
        self.assertFalse(self.errors, "the closed model must not receive delayed part framing:\n" + "\n".join(self.errors))

    def test_live_model_still_receives_initial_and_delayed_framing(self):
        gl = self.view.gl_widget
        with patch.object(gl, "reset_view", wraps=gl.reset_view) as reset:
            self._wait_until(lambda: reset.called, "normal zero-delay model initialization did not run")
            reset.assert_called_once_with(animate=False)
        part = self.view.mds.parts[0].name
        with patch.object(gl, "frame_structures", wraps=gl.frame_structures) as frame:
            self.assertEqual(self.view.focus_parts([part]), [])
            immediate_calls = frame.call_count
            self.assertEqual(immediate_calls, 0, "part framing is deliberately deferred until initialization completes")
            self._wait_until(lambda: frame.called, "live model did not receive deferred part framing")
            QAPP.processEvents()
            frame.assert_called_once_with([0])
            self.assertTrue(isValid(self.view), "the live model QObject was unexpectedly deleted")
            self.assertTrue(isValid(gl), "the live viewport QObject was unexpectedly deleted")
        self.assertFalse(self.errors, self.errors)


if __name__ == "__main__":
    unittest.main()
