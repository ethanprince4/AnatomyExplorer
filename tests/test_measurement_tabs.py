"""Measurement routing uses isolated settings and owned GLB fixtures."""
import tempfile
import time
import unittest
from pathlib import Path
import numpy as np
from test_state_and_recovery import QAPP, FIXTURES, MainWindow, Dataset, config
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from general_fixtures import write_fixture_model, open_fixture_model
from tests.fixture_paths import fixture_root

class MeasurementTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset(config.DATA_DIR)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=FIXTURES.name)
        # Other modules also redirect QSettings at import; point it at this module's fixtures.
        # (restored afterwards so other modules keep their own redirect).
        old_format = QSettings.defaultFormat()
        old_root = Path(QSettings(old_format, QSettings.UserScope, config.ORG_NAME,
                                  config.APP_NAME).fileName()).parent.parent
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(fixture_root(FIXTURES.name)))
        self.addCleanup(QSettings.setDefaultFormat, old_format)
        self.addCleanup(QSettings.setPath, QSettings.IniFormat, QSettings.UserScope, str(old_root))
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
            self.open_installed(path)
            self.models.append(self.win.active_model_view())

    def open_installed(self, path):
        # Readiness callbacks wait for a first GPU draw that an off-screen run never
        # makes; the CPU-complete tab is installed without it.
        from app.viewer.catalog import FileEntry
        model_id = FileEntry(path).id
        self.win.open_model_file(str(path))
        deadline = time.monotonic() + 30
        while model_id not in self.win.micro_tabs and time.monotonic() < deadline:
            QAPP.processEvents()
            time.sleep(0.01)  # QTest.qWait holds the GIL and starves the load thread
        self.assertIn(model_id, self.win.micro_tabs)

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
