"""The review-shot key (app/main_window.py save_review_shot): one PNG per press, camera stored in the PNG text chunk.

Qt windows stay hidden (offscreen) and all preference fixtures live in a temporary directory."""
import atexit
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLineEdit

from app import config, live_camera
from app.__main__ import configure_qt
from app.actions import ACTION_DEFS
from app.data import Dataset
from tests.fixture_paths import fixture_root

FIXTURES = tempfile.TemporaryDirectory(prefix="anatomy-reviewshot-")
atexit.register(FIXTURES.cleanup)
FIXTURE_ROOT = fixture_root(FIXTURES.name)
config.USER_DIR = FIXTURE_ROOT / "study"
config.ORG_NAME = "AnatomyExplorerRegression"
config.APP_NAME = "FixtureReviewShot"
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(FIXTURE_ROOT))
QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, str(FIXTURE_ROOT))
configure_qt()
QAPP = QApplication.instance() or QApplication([])

from app.main_window import MainWindow

KEY = "AnatomyExplorer-camera"


def pngs(folder):
    return sorted(Path(folder).glob("*.png"))


class ReviewShotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset(config.DATA_DIR)

    def make_window(self):
        env = dict(os.environ)
        env.pop(live_camera.ENV_VAR, None)
        with patch.dict(os.environ, env, clear=True):
            return MainWindow(self.dataset, restore=False)

    def test_action_is_defined_and_distinct_from_save_view(self):
        defs = {d[0]: d for d in ACTION_DEFS}
        self.assertEqual(defs["review_shot"][3], "F9")
        self.assertNotEqual(defs["review_shot"][3], defs["save_view"][3])

    def test_each_press_writes_one_new_png_with_the_camera_inside(self):
        with tempfile.TemporaryDirectory(prefix="reviewshot-") as tmp:
            win = self.make_window()
            try:
                self.assertEqual(pngs(tmp), [])
                first = win.save_review_shot(folder=tmp)
                self.assertEqual(len(pngs(tmp)), 1)
                self.assertEqual(Path(first), pngs(tmp)[0])
                data = json.loads(QImage(str(first)).text(KEY))
                self.assertIn("camera", data)
                self.assertTrue(data["time_iso"])
                self.assertIn("Saved review shot", win.statusBar().currentMessage())
                self.assertIn(str(first), win.statusBar().currentMessage())

                second = win.save_review_shot(folder=tmp)
                self.assertEqual(len(pngs(tmp)), 2)
                self.assertNotEqual(first, second)
                self.assertTrue(Path(first).exists())
            finally:
                win.close()
                win.deleteLater()
                QAPP.processEvents()

    def test_registered_action_uses_the_folder_setting(self):
        with tempfile.TemporaryDirectory(prefix="reviewshot-") as tmp:
            win = self.make_window()
            try:
                win.settings["review_shot_folder"] = str(Path(tmp) / "sub")
                win.cmds.actions["review_shot"].trigger()
                files = pngs(Path(tmp) / "sub")
                self.assertEqual(len(files), 1)
                self.assertIn("camera", json.loads(QImage(str(files[0])).text(KEY)))
            finally:
                win.close()
                win.deleteLater()
                QAPP.processEvents()

    def test_settings_behavior_page_shows_the_folder(self):
        with tempfile.TemporaryDirectory(prefix="reviewshot-") as tmp:
            win = self.make_window()
            try:
                win.settings["review_shot_folder"] = tmp
                win.open_settings()
                dlg = win.settings_dialog
                edit = dlg.widgets["review_shot_folder"]
                self.assertIsInstance(edit, QLineEdit)
                self.assertEqual(edit.text(), tmp)
                self.assertTrue(dlg.review_shot_browse.isVisibleTo(dlg) or dlg.review_shot_browse.parent() is not None)
                other = str(Path(tmp) / "other")
                edit.setText(other)
                edit.editingFinished.emit()
                self.assertEqual(win.settings["review_shot_folder"], other)
                dlg.close()
            finally:
                win.close()
                win.deleteLater()
                QAPP.processEvents()


if __name__ == "__main__":
    unittest.main()
