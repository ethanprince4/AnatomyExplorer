"""Actual Escape dispatch prioritizes the focused search text over hidden/active 3D state."""
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
from general_fixtures import write_fixture_model, open_fixture_model
import numpy as np


class SearchEscapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset(config.DATA_DIR)

    def setUp(self):
        self.errors = []
        hook = patch("sys.excepthook", lambda kind, value, tb: self.errors.append(value))
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

    def _show_search(self):
        self.win.left_dock.show()
        self.win.show()
        self.win.activateWindow()
        self.win.search.edit.setText("Frontal bone")
        self.win.search.focus_search()
        QAPP.processEvents()
        self.assertIs(QAPP.activeWindow(), self.win)
        self.assertTrue(self.win.search.edit.hasFocus())
        self.assertFalse(self.win.viewport.isVisible())

    def _close(self):
        self.win.close()
        self.win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QAPP.processEvents()
        self.assertFalse(self.errors, self.errors)

    def test_search_escape_clears_text_and_preserves_hidden_atlas_measurement(self):
        self.win.viewport.set_measure(True)
        points = [np.array([0.0, 0.0, 0.0]), np.array([0.02, 0.0, 0.0])]
        self.win.viewport.measure_points = [p.copy() for p in points]
        self._show_search()
        QTest.keyClick(self.win.search.edit, Qt.Key_Escape)
        with self.subTest(query=True):
            self.assertEqual(self.win.search.edit.text(), "")
        with self.subTest(hidden_measurement=True):
            self.assertEqual(len(self.win.viewport.measure_points), 2)
            np.testing.assert_array_equal(self.win.viewport.measure_points, points)

    def test_search_escape_clears_text_and_preserves_active_model_selection(self):
        model = self._open_owned_model()
        model.state.select([0])
        self.assertEqual(list(model.state.selected), [0])
        self._show_search()
        self.assertIsNone(model.gl_widget.renderer)
        QTest.keyClick(self.win.search.edit, Qt.Key_Escape)
        with self.subTest(query=True):
            self.assertEqual(self.win.search.edit.text(), "")
        with self.subTest(model_selection=True):
            self.assertEqual(list(model.state.selected), [0])

    def _open_owned_model(self):
        path = Path(config.USER_DIR) / "search-escape-owned.glb"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_fixture_model(path)
        open_fixture_model(self.win, path)
        model = self.win.active_model_view()
        model.gl_widget.hide()  # Real model UI/selection without an OpenGL context.
        QAPP.processEvents()
        return model

    def test_empty_search_keeps_existing_model_selection_escape_behavior(self):
        model = self._open_owned_model()
        model.state.select([0])
        self._show_search()
        self.win.search.edit.clear()
        QTest.keyClick(self.win.search.edit, Qt.Key_Escape)
        self.assertEqual(list(model.state.selected), [])

    def test_search_escape_without_measurement_keeps_existing_query_behavior(self):
        self._show_search()
        QTest.keyClick(self.win.search.edit, Qt.Key_Escape)
        self.assertEqual(self.win.search.edit.text(), "")


if __name__ == "__main__":
    unittest.main()
