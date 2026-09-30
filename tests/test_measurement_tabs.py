"""Measurement routing uses isolated settings and owned GLB fixtures."""
import tempfile
import unittest
from pathlib import Path
import numpy as np
from test_state_and_recovery import QAPP, FIXTURES, MainWindow, Dataset, config
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from general_fixtures import write_fixture_model
from tests.fixture_paths import fixture_root

class MeasurementTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset(config.DATA_DIR)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=FIXTURES.name)
        prefs = QSettings(QSettings.defaultFormat(), QSettings.UserScope,
                          config.ORG_NAME, config.APP_NAME)
        self.assertTrue(Path(prefs.fileName()).resolve().is_relative_to(Path(FIXTURES.name).resolve()))
        prefs.clear()
        self.win = MainWindow(self.dataset, restore=False)
        self.models = []
        for name in ("first", "second"):
            path = fixture_root(self.folder.name) / (name + ".glb")
            write_fixture_model(path)
            path.with_suffix(".viewer.json").write_text('{"um_per_bu":2500}', encoding="utf-8")
            self.win.open_model_file(str(path))
            self.models.append(self.win.active_model_view())

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        QAPP.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.folder.cleanup()

    def measured_first(self):
        first = self.models[0]
        self.win.center.setCurrentWidget(first)
        self.win.toggle_measure()
        first.gl_widget.measure_points = [np.array([0., 0., 0.]), np.array([2., 0., 0.])]
        first.gl_widget.measureChanged.emit(first.gl_widget.measure_text())
        self.assertEqual(self.win.statusBar().currentMessage(), "5.0 mm")
        return first.gl_widget

    def test_switching_tabs_restores_measure_action_and_status_preserving_points(self):
        gl = self.measured_first()
        self.win.center.setCurrentWidget(self.models[1])
        self.assertFalse(self.win.measure_action.isChecked())
        self.assertEqual(self.win.statusBar().currentMessage(), "")
        self.win.center.setCurrentIndex(0)
        self.assertFalse(self.win.measure_action.isChecked())
        self.win.center.setCurrentWidget(self.models[0])
        self.assertTrue(self.win.measure_action.isChecked())
        self.assertEqual(self.win.statusBar().currentMessage(), "5.0 mm")
        self.assertEqual(len(gl.measure_points), 2)
        self.win.toggle_measure()
        self.assertFalse(gl.measure_mode)
        self.assertEqual(gl.measure_points, [])

    def test_inactive_model_and_atlas_signals_preserve_active_measurement(self):
        active = self.models[1].gl_widget
        self.win.toggle_measure()
        active.measure_points = [np.zeros(3), np.array([0., 2., 0.])]
        active.measureChanged.emit(active.measure_text())
        self.assertEqual(self.win.statusBar().currentMessage(), "5.0 mm")
        self.models[0].gl_widget.set_measure(True)
        self.assertEqual(self.win.statusBar().currentMessage(), "5.0 mm")
        self.win.viewport.clear_measure()
        self.assertEqual(self.win.statusBar().currentMessage(), "5.0 mm")

    def test_histology_measure_controls_do_not_change_hidden_atlas(self):
        self.win.center.setCurrentIndex(0)
        self.win.toggle_measure()
        atlas = self.win.viewport
        atlas.measure_points = [np.zeros(3), np.array([0.03, 0., 0.])]
        atlas.measureChanged.emit(atlas.measure_text())
        tid = next(key for key, tissue in self.win.content.tissues.items() if tissue.get("images"))
        self.win.open_histology(tid)
        self.assertFalse(self.win.measure_action.isEnabled())
        self.assertFalse(self.win.measure_action.isChecked())
        self.assertEqual(self.win.statusBar().currentMessage(), "")
        self.win.measure_action.trigger()
        self.assertTrue(atlas.measure_mode)
        self.assertEqual(len(atlas.measure_points), 2)
        # Direct command routing must also respect the lack of a visible 3D view.
        self.win.toggle_measure()
        self.assertTrue(atlas.measure_mode)
        self.assertEqual(len(atlas.measure_points), 2)
        atlas.measureChanged.emit(atlas.measure_text())
        self.assertEqual(self.win.statusBar().currentMessage(), "")
        self.win.center.setCurrentIndex(0)
        self.assertTrue(self.win.measure_action.isEnabled())
        self.assertTrue(self.win.measure_action.isChecked())
        self.assertEqual(self.win.statusBar().currentMessage(), "30.0 mm")
