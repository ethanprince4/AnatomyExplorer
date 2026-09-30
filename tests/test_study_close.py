"""Closing a real study dock then its window must cancel pending QObject callbacks."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "app/main_window.py").exists())
sys.path.insert(0, str(ROOT))
from test_state_and_recovery import QAPP, MainWindow, Dataset, config
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from app.lessons import practice_pool
from app.ui.practice import PracticeController


class StudyCloseTests(unittest.TestCase):
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
        prefs = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
        self.assertTrue(Path(prefs.fileName()).resolve().is_relative_to(fixture_root))
        prefs.clear()
        self.win = MainWindow(self.dataset, restore=False)
        self.addCleanup(self._close)
        self.win.viewport.hide()  # Actual dock/window lifecycle without an OpenGL context.
        self.win.open_histology("simple_squamous", 0)
        self.win.show()
        QAPP.processEvents()

    def _close(self):
        if self.win is not None:
            self._destroy_window()

    def _destroy_window(self):
        win, self.win = self.win, None
        win.close()
        win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QAPP.processEvents()

    def _controller(self, kind):
        if kind == "quiz":
            controller = self.win.quiz
            controller.open()
        else:
            panel = self.win.lessons_panel
            controller = PracticeController(self.win, panel)
            panel.practice = controller
            selected = None
            for lesson in panel.lessons:
                pool = controller._prepare(practice_pool(lesson, panel.lessons))
                item = next((x for x in pool if x["type"] == "mcq"), None)
                if item is not None:
                    selected = lesson, item
                    break
            self.assertIsNotNone(selected)
            lesson, item = selected
            with patch("app.ui.practice.build_session", return_value=[item]):
                controller.start(lesson, n=1)
        QAPP.processEvents()
        self.assertTrue(controller.active)
        self.assertTrue(controller.dock.isVisible())
        self.assertFalse(self.win.viewport.isVisible())
        self.assertIsNone(self.win.viewport.renderer)
        return controller

    def test_quiz_dock_close_followed_immediately_by_window_delete_has_no_callback_exception(self):
        controller = self._controller("quiz")
        controller.dock.close()
        self.assertFalse(controller.dock.isVisible())
        self._destroy_window()
        self.assertEqual(self.errors, [])

    def test_practice_dock_close_followed_immediately_by_window_delete_has_no_callback_exception(self):
        controller = self._controller("practice")
        controller.dock.close()
        self.assertFalse(controller.dock.isVisible())
        self._destroy_window()
        self.assertEqual(self.errors, [])

    def test_alive_study_dock_close_still_stops_and_restores_names(self):
        for kind in ("quiz", "practice"):
            with self.subTest(kind=kind):
                self.win.settings["show_landmarks"] = True
                self.win.settings["show_hover_tooltip"] = True
                controller = self._controller(kind)
                controller._hide_names(True) if kind == "quiz" else controller._hide_names()
                self.assertFalse(self.win.settings["show_landmarks"])
                controller.dock.close()
                QAPP.processEvents()
                self.assertFalse(controller.active)
                self.assertTrue(self.win.settings["show_landmarks"])
                self.assertTrue(self.win.settings["show_hover_tooltip"])
                self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
