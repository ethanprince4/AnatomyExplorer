"""Actual window/viewer caption regressions with owned Qt settings and files."""
import json
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tests'))
from test_state_and_recovery import QAPP, FIXTURES, MainWindow, Dataset, config
from PySide6.QtCore import QCoreApplication,QEvent,QSettings


class HistologyFigureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset=Dataset(config.DATA_DIR)

    def setUp(self):
        prefs=QSettings(QSettings.defaultFormat(),QSettings.UserScope,config.ORG_NAME,config.APP_NAME)
        fixture_root=Path(config.USER_DIR).resolve().parent
        self.assertTrue(fixture_root.name.startswith('anatomy-regression-'))
        self.assertTrue(Path(prefs.fileName()).resolve().is_relative_to(fixture_root))
        prefs.clear()
        self.win=MainWindow(self.dataset,restore=False)
        self.addCleanup(self._close_window)
        sid=next(s for s,meta in enumerate(self.dataset.structures) if 'Frontal bone' in meta['name'])
        self.win.state.select([sid])
        self.atlas_caption=self.win._figure_caption()
        self.win.open_histology('simple_squamous',0)
        self.viewer=self.win.center.currentWidget()
        self.assertIs(self.win._capture_widget(),self.viewer)

    def _close_window(self):
        self.win.close()
        self.win.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)

    def test_active_histology_figure_has_current_image_title_and_tissue(self):
        image=self.viewer.tissue['images'][self.viewer.index]
        title,bits,credit=self.win._figure_caption()
        self.assertIn(image['title'],title)
        self.assertIn(self.viewer.tissue['name'],' '.join(bits))

    def test_active_histology_figure_credits_actual_image_author_license_and_source(self):
        image=self.viewer.tissue['images'][self.viewer.index]
        title,bits,credit=self.win._figure_caption()
        for field in ('author','license','source'):
            self.assertIn(image[field],credit,field+' must describe the captured micrograph')

    def test_next_image_updates_export_metadata_then_atlas_caption_restores(self):
        self.viewer.show_image(3)
        image=self.viewer.tissue['images'][3]
        title,bits,credit=self.win._figure_caption()
        self.assertIn(image['title'],title)
        self.assertIn(image['license'],credit)
        self.assertIn(image['source'],credit)
        self.win.center.setCurrentIndex(0)
        self.assertEqual(self.win._figure_caption(),self.atlas_caption)


if __name__=='__main__':
    unittest.main()
