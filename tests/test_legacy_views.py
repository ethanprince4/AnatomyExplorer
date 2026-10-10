"""Actual saved-view manager regressions for existing duplicate-name records."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "app/main_window.py").exists())
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from test_state_and_recovery import QAPP, MainWindow, Dataset, config
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QTimer
from PySide6.QtWidgets import QDialog, QListWidget, QPushButton, QMessageBox


class LegacySavedViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset(config.DATA_DIR)

    def setUp(self):
        fixture_root = Path(config.USER_DIR).resolve().parent
        self.assertTrue(fixture_root.name.startswith("anatomy-regression-"))
        prefs = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
        self.assertTrue(Path(prefs.fileName()).resolve().is_relative_to(fixture_root))
        prefs.clear()
        self.win = MainWindow(self.dataset, restore=False)
        self.addCleanup(self._close)
        sids = [next(i for i, s in enumerate(self.dataset.structures) if s["base"] == name)
                for name in ("Frontal bone", "Parietal bone", "Temporal bone")]
        self.views = []
        for i, name in enumerate(("B", "A", "B")):
            data = self.win.capture_view()
            data["selected"] = [sids[i]]
            self.views.append({"name": name, "created": "fixture-" + str(i), "data": data,
                               "preserve-extra-metadata": {"origin": i}})
        self.win._store_views(self.views)

    def _close(self):
        self.win.close()
        self.win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def _activate(self, action, row):
        errors, observed = [], []

        def interact():
            dialog = QAPP.activeModalWidget()
            try:
                self.assertIsInstance(dialog, QDialog)
                listing = dialog.findChild(QListWidget)
                self.assertEqual([listing.item(i).text() for i in range(listing.count())], ["A", "B", "B"])
                listing.setCurrentRow(row)
                button = {"Open": dialog.open_button, "Rename": dialog.rename_button,
                          "Delete": dialog.delete_button}[action]
                with patch("app.ui.saved_views.QMessageBox.question", return_value=QMessageBox.Yes) as confirm:
                    button.click()
                    if action == "Delete":
                        confirm.assert_called_once()
                observed.append(copy.deepcopy(self.win._saved_views()))
            except Exception as exc:
                errors.append(exc)
            finally:
                dialog.accept()

        QTimer.singleShot(0, interact)
        self.win.manage_views()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(errors, errors)
        self.assertEqual(len(observed), 1)
        return observed[0]

    def test_delete_duplicate_name_removes_only_selected_record(self):
        after = self._activate("Delete", 2)  # second B: original storage index 2
        self.assertEqual(after, self.views[:2], "deleting one legacy duplicate must preserve the other complete record")
        self.win.qsettings.sync()
        persisted = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
        self.assertEqual(json.loads(persisted.value("saved_views")), self.views[:2])

    def test_rename_duplicate_name_changes_only_selected_record(self):
        with patch("app.ui.saved_views.QInputDialog.getText", return_value=("C", True)):
            after = self._activate("Rename", 2)
        expected = copy.deepcopy(self.views)
        expected[2]["name"] = "C"
        self.assertEqual(after, expected, "unique rename must affect only the selected legacy duplicate")

    def test_open_duplicate_name_applies_only_selected_scene(self):
        before_undos = len(self.win.state._undo)
        after = self._activate("Open", 1)  # first B: original storage index 0
        self.assertEqual(after, self.views, "opening a saved view does not rewrite any records")
        self.assertEqual(self.win.state.selected, self.views[0]["data"]["selected"],
                         "open must display the chosen first B, not silently replace it with the second B")
        self.assertEqual(len(self.win.state._undo), before_undos + 1, "one Open applies one scene")


if __name__ == "__main__":
    unittest.main()
