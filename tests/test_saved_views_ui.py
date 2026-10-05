"""2D-only saved-view UI checks with in-memory storage, never QSettings."""
import copy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/anatomy-ui-qt-cache")
HERE = Path(__file__).resolve()
BASE = Path(os.environ.get("ANATOMY_UI_BASE", str(HERE.parents[3] /
            "integration-azure-handoff/candidate/AnatomyExplorer")))
if not (BASE / "app").exists():
    BASE = HERE.parents[1]
OVERLAY = Path(os.environ.get("ANATOMY_UI_OVERLAY", str(HERE.parents[1])))
sys.path.insert(0, str(BASE))
import app.ui
THEME_OVERLAY = Path(os.environ.get("ANATOMY_UI_THEME_OVERLAY", str(OVERLAY.parent / "lead")))
if (THEME_OVERLAY / "app/ui/theme.py").exists():
    app.ui.__path__.insert(0, str(THEME_OVERLAY / "app/ui"))
app.ui.__path__.insert(0, str(OVERLAY / "app/ui"))

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget
from app.ui import theme
from app.ui.saved_views import SavedViewsDialog

QAPP = QApplication.instance() or QApplication([])
theme.apply_theme(QAPP)


def view(name="Thorax overview", **extra):
    return {"name": name, "created": "2026-10-03T19:42",
            "data": {"camera": [[0, 0, 0], 10, 20, 30], "selected": [3, 7],
                     "hidden": [8], "isolated": None,
                     "clip": [[True, False, False], [0, 0, 0], [False] * 3],
                     "radiology_slice": False}, **extra}


class Host(QWidget):
    def __init__(self, views):
        super().__init__()
        self.views = copy.deepcopy(views)
        self.stores = []
        self.opened = []
        self.save_calls = 0
        self.next_save = None

    def _saved_views(self):
        return copy.deepcopy(self.views)

    def _store_views(self, views):
        self.stores.append(copy.deepcopy(views))
        self.views = copy.deepcopy(views)

    def apply_view(self, data):
        self.opened.append(copy.deepcopy(data))

    def save_view_dialog(self):
        self.save_calls += 1
        if self.next_save:
            self.views.append(copy.deepcopy(self.next_save))


class SavedViewTests(unittest.TestCase):
    def setUp(self):
        self.widgets = []
        self.errors = []
        self.exception_hook = patch("sys.excepthook", lambda kind, value, trace: self.errors.append(str(value)))
        self.exception_hook.start()

    def tearDown(self):
        for widget in reversed(self.widgets):
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QAPP.processEvents()
        self.exception_hook.stop()
        self.assertFalse(self.errors)

    def dialog(self, views):
        host = Host(views)
        dialog = SavedViewsDialog(host)
        self.widgets.extend([host, dialog])
        return host, dialog

    def test_empty_state_explains_saving_and_disables_record_actions(self):
        host, dialog = self.dialog([])
        self.assertEqual(dialog.body.currentIndex(), 1)
        self.assertIn("Save current view", dialog.empty_message.text())
        self.assertEqual(dialog.summary.text(), "0 saved views")
        for button in (dialog.open_button, dialog.rename_button, dialog.delete_button):
            self.assertFalse(button.isEnabled())
        self.assertTrue(dialog.save_button.isEnabled())
        QTest.keyClick(dialog.search, Qt.Key_Return)
        self.assertFalse(host.opened)
        self.assertFalse(host.stores)

    def test_sorted_multiword_search_and_date_search_preserve_original_data(self):
        host, dialog = self.dialog([view("Zygomatic overview"), view("Thorax anterior"), view("Abdomen")])
        self.assertEqual(dialog.list.item(0).text(), "Abdomen")
        dialog.search.setText("ANT thor")
        self.assertEqual(dialog.list.count(), 1)
        self.assertEqual(dialog.preview_title.text(), "Thorax anterior")
        dialog.search.setText("03 Oct 2026")
        self.assertEqual(dialog.list.count(), 3)
        dialog.search.setText("no-such-view")
        self.assertEqual(dialog.body.currentIndex(), 1)
        self.assertIn("No matching", dialog.empty_title.text())
        self.assertFalse(dialog.open_button.isEnabled())
        self.assertFalse(dialog.rename_button.isEnabled())
        self.assertFalse(dialog.delete_button.isEnabled())
        dialog.clear_button.click()
        self.assertEqual(dialog.list.count(), 3)
        self.assertFalse(host.stores)

    def test_metadata_uses_existing_record_and_plain_text_names(self):
        host, dialog = self.dialog([view("<b>Atlas & vessels</b>")])
        self.assertEqual(dialog.preview_title.textFormat(), Qt.PlainText)
        self.assertEqual(dialog.metadata_labels["Selection"].text(), "2 structures")
        self.assertEqual(dialog.metadata_labels["Hidden"].text(), "1 structure")
        self.assertEqual(dialog.metadata_labels["Cutting planes"].text(), "1")
        self.assertEqual(dialog.metadata_labels["Saved"].text(), "03 Oct 2026, 19:42")
        host.views = [{"name": "Legacy", "data": {}, "created": "malformed"}]
        dialog.refresh()
        self.assertEqual(dialog.metadata_labels["Saved"].text(), "Not recorded")
        self.assertEqual(dialog.metadata_labels["Isolation"].text(), "Off")
        self.assertFalse(host.stores)

    def test_keyboard_navigation_opens_filtered_record_without_writing(self):
        host, dialog = self.dialog([view("Zulu"), view("Alpha"), view("Beta")])
        QTest.keyClick(dialog.search, Qt.Key_Down)
        self.assertEqual(dialog.preview_title.text(), "Beta")
        QTest.keyClick(dialog.search, Qt.Key_Return)
        self.assertEqual(host.opened, [host.views[2]["data"]])
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertFalse(host.stores)

    def test_escape_closes_without_restoring_or_changing_storage(self):
        host, dialog = self.dialog([view()])
        dialog.show()
        QTest.keyClick(dialog.search, Qt.Key_Escape)
        self.assertFalse(dialog.isVisible())
        self.assertFalse(host.opened)
        self.assertFalse(host.stores)

    def test_rename_preserves_data_created_and_unknown_fields(self):
        original = view("Zulu", future_metadata={"author": "fixture"})
        host, dialog = self.dialog([original, view("Alpha")])
        dialog.list.setCurrentRow(1)
        with patch("app.ui.saved_views.QInputDialog.getText", return_value=("  Beta  ", True)):
            dialog.rename_button.click()
        expected = copy.deepcopy(original)
        expected["name"] = "Beta"
        self.assertEqual(host.views[0], expected)
        self.assertEqual(dialog.preview_title.text(), "Beta")
        self.assertEqual(dialog.list.currentRow(), 1)
        self.assertEqual(len(host.stores), 1)

    def test_duplicate_rename_guard_cancel_blank_and_unchanged_do_not_write(self):
        host, dialog = self.dialog([view("Alpha"), view("Beta")])
        with patch("app.ui.saved_views.QInputDialog.getText", return_value=("Beta", True)), \
             patch("app.ui.saved_views.QMessageBox.warning") as warning:
            dialog.rename_button.click()
        warning.assert_called_once()
        for result in (("Unused", False), ("   ", True), ("Alpha", True)):
            with patch("app.ui.saved_views.QInputDialog.getText", return_value=result):
                dialog.rename_button.click()
        self.assertEqual(host.views[0]["name"], "Alpha")
        self.assertFalse(host.stores)

    def test_rename_keeps_result_visible_when_old_search_no_longer_matches(self):
        host, dialog = self.dialog([view("Alpha"), view("Zulu")])
        dialog.search.setText("Alpha")
        with patch("app.ui.saved_views.QInputDialog.getText", return_value=("Beta", True)):
            dialog.rename_button.click()
        self.assertEqual(dialog.search.text(), "")
        self.assertEqual(dialog.preview_title.text(), "Beta")
        self.assertEqual(host.views[0]["name"], "Beta")

    def test_delete_cancel_then_confirm_correct_filtered_view(self):
        host, dialog = self.dialog([view("Zulu"), view("Alpha"), view("Beta")])
        dialog.search.setText("Zulu")
        with patch("app.ui.saved_views.QMessageBox.question", return_value=QMessageBox.Cancel):
            dialog.delete_button.click()
        self.assertFalse(host.stores)
        with patch("app.ui.saved_views.QMessageBox.question", return_value=QMessageBox.Yes):
            dialog.delete_button.click()
        self.assertEqual([v["name"] for v in host.views], ["Alpha", "Beta"])
        self.assertEqual(dialog.list.count(), 0)
        self.assertFalse(dialog.open_button.isEnabled())
        self.assertFalse(host.opened)

    def test_delete_last_record_returns_meaningful_empty_state(self):
        host, dialog = self.dialog([view()])
        with patch("app.ui.saved_views.QMessageBox.question", return_value=QMessageBox.Yes):
            dialog.delete_button.click()
            dialog._delete_selected()
        self.assertEqual(host.views, [])
        self.assertEqual(len(host.stores), 1)
        self.assertIn("Keep a useful view", dialog.empty_title.text())

    def test_delete_keeps_nearest_remaining_record_selected(self):
        host, dialog = self.dialog([view("Alpha"), view("Beta"), view("Gamma")])
        dialog.list.setCurrentRow(1)
        with patch("app.ui.saved_views.QMessageBox.question", return_value=QMessageBox.Yes):
            dialog.delete_button.click()
        self.assertEqual(dialog.preview_title.text(), "Gamma")
        self.assertTrue(dialog.open_button.isEnabled())

    def test_save_current_refreshes_new_record_and_cancel_retains_search(self):
        host, dialog = self.dialog([view("Alpha")])
        dialog.search.setText("Alpha")
        dialog.save_button.click()
        self.assertEqual(dialog.search.text(), "Alpha")
        host.next_save = view("Beta")
        dialog.save_button.click()
        self.assertEqual(dialog.list.count(), 2)
        self.assertEqual(dialog.search.text(), "")
        self.assertEqual(dialog.preview_title.text(), "Beta")
        self.assertEqual(host.save_calls, 2)

    def test_fresh_storage_resolves_reordered_record_and_rejects_changed_record(self):
        host, dialog = self.dialog([view("Alpha"), view("Beta")])
        host.views.reverse()
        dialog.open_button.click()
        self.assertEqual(host.opened, [host.views[1]["data"]])
        host.opened.clear()
        host.views[1]["name"] = "Changed elsewhere"
        with patch("app.ui.saved_views.QMessageBox.information") as info:
            dialog.open_button.click()
        info.assert_called_once()
        self.assertFalse(host.opened)
        self.assertFalse(host.stores)

    def test_rename_rechecks_duplicate_after_prompt_and_delete_rechecks_target(self):
        host, dialog = self.dialog([view("Alpha")])
        def concurrent_rename(*_args, **_kwargs):
            host.views.append(view("Beta"))
            return "Beta", True
        with patch("app.ui.saved_views.QInputDialog.getText", side_effect=concurrent_rename), \
             patch("app.ui.saved_views.QMessageBox.warning"):
            dialog.rename_button.click()
        self.assertFalse(host.stores)
        def concurrent_delete(*_args, **_kwargs):
            host.views.pop(0)
            return QMessageBox.Yes
        with patch("app.ui.saved_views.QMessageBox.question", side_effect=concurrent_delete), \
             patch("app.ui.saved_views.QMessageBox.information"):
            dialog.delete_button.click()
        self.assertEqual([v["name"] for v in host.views], ["Beta"])
        self.assertFalse(host.stores)

    def test_store_failure_keeps_source_and_preview_unchanged(self):
        host, dialog = self.dialog([view("Alpha")])
        with patch.object(host, "_store_views", side_effect=OSError("Fixture storage unavailable")), \
             patch("app.ui.saved_views.QInputDialog.getText", return_value=("Beta", True)), \
             patch("app.ui.saved_views.QMessageBox.warning") as warning:
            dialog.rename_button.click()
        warning.assert_called_once()
        self.assertEqual(host.views[0]["name"], "Alpha")
        self.assertEqual(dialog.preview_title.text(), "Alpha")

    def test_long_name_compact_layout_keeps_actions_visible(self):
        host, dialog = self.dialog([view("A long saved atlas view of the thorax and surrounding vessels " * 5)])
        dialog.resize(600, 420)
        dialog.show()
        QAPP.processEvents()
        self.assertEqual(dialog.size().width(), 600)
        self.assertEqual(dialog.preview_title.text(), host.views[0]["name"])
        for button in (dialog.save_button, dialog.close_button, dialog.open_button,
                       dialog.rename_button, dialog.delete_button):
            self.assertTrue(button.isVisible())
            self.assertTrue(dialog.rect().contains(button.mapTo(dialog, button.rect().bottomRight())))
        self.assertTrue(dialog.search.accessibleName())
        self.assertTrue(dialog.list.accessibleName())

    def test_large_text_compact_layout_preserves_actions_and_scrollable_details(self):
        theme.apply_theme(QAPP, scale=1.5)
        try:
            host, dialog = self.dialog([view("A long saved atlas view of the thorax and surrounding vessels")])
            dialog.resize(600, 420)
            dialog.show()
            QAPP.processEvents()
            self.assertEqual(dialog.width(), 600)
            self.assertEqual(dialog.preview_scroll.horizontalScrollBar().maximum(), 0)
            self.assertGreater(dialog.preview_scroll.verticalScrollBar().maximum(), 0)
            for button in (dialog.save_button, dialog.close_button, dialog.open_button,
                           dialog.rename_button, dialog.delete_button):
                self.assertTrue(dialog.rect().contains(button.mapTo(dialog, button.rect().bottomRight())))
        finally:
            theme.apply_theme(QAPP)


if __name__ == "__main__":
    unittest.main()
