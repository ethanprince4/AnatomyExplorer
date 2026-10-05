"""2D-only UI contract tests against the installed catalogue, without a GL context.

Run from a combined candidate, or set ANATOMY_UI_BASE to the read-only runtime
and ANATOMY_UI_OVERLAY to this code-only overlay. No dataset/model writes occur.
"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve()
DEFAULT_BASE = HERE.parents[3] / "integration-azure-handoff/candidate/AnatomyExplorer"
BASE = Path(os.environ.get("ANATOMY_UI_BASE", DEFAULT_BASE))
if not (BASE / "app").exists():
    BASE = HERE.parents[1]
sys.path.insert(0, str(BASE))
import app.ui
OVERLAY = Path(os.environ.get("ANATOMY_UI_OVERLAY", HERE.parents[1]))
app.ui.__path__.insert(0, str(OVERLAY / "app/ui"))
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.radiology import load_cases, CONTENT_DIR
from app.ui.radiology import RadiologyBrowser, RadiologyPanel, RadiographView
from app.ui.histology import HistologyBrowser, HistologyViewer, ImageView, ROLE
from app.ui.image_workspace import LocalImageLoader, matches_words

QAPP = QApplication.instance() or QApplication([])


def settle(predicate, timeout=4):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QAPP.processEvents()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("Timed out waiting for 2D image load")


def content_fixture():
    catalogue = json.loads((BASE / "data/histology/catalog.json").read_text(encoding="utf-8"))
    root = BASE / "data/histology"
    return SimpleNamespace(histology=catalogue, tissues={t["id"]: t for t in catalogue["tissues"]},
                           micro_models={}, image_path=lambda img: root / "images" / img["file"],
                           thumb_path=lambda img: root / "thumbs" / (Path(img["file"]).stem + ".jpg"))


def dataset_fixture():
    return SimpleNamespace(by_name={}, nodes={}, structures=[])


class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        authored = []
        files = sorted(CONTENT_DIR.glob("radiology*.json"))
        if not files:
            raise AssertionError("No authored radiology inventory installed")
        for path in files:
            authored.extend(json.loads(path.read_text(encoding="utf-8")))
        cls.authored_ids = [row["id"] for row in authored]
        cls.cases = load_cases(include_missing=True)
        cls.content = content_fixture()
        cls.ds = dataset_fixture()

    def setUp(self):
        self.widgets = []
        self.errors = []
        self.hook = patch("sys.excepthook", lambda _kind, value, _tb: self.errors.append(str(value)))
        self.hook.start()

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QAPP.processEvents()
        self.hook.stop()
        self.assertFalse(self.errors, self.errors)

    def own(self, widget):
        self.widgets.append(widget)
        return widget

    def browser(self):
        return self.own(RadiologyBrowser(self.cases))

    def viewer(self):
        return self.own(HistologyViewer(self.ds, self.content))

    def test_image_controls_have_opaque_readable_cards(self):
        from app.ui import theme
        from app.ui.image_workspace import CARD_TEXT
        # A dark image canvas must not inherit dark title/control text without a surface.
        histology = self.viewer()
        radiology = self.own(RadiologyPanel())
        for panel, card, label in (
            (histology, histology.header_card, histology.title),
            (histology, histology.status_card, histology.image_status),
            (radiology, radiology.header_card, radiology.title),
            (radiology, radiology.controls_card, radiology.zoom_label),
        ):
            self.assertTrue(card.testAttribute(Qt.WA_StyledBackground))
            self.assertTrue(card.isAncestorOf(label))
            self.assertIn("#f8fafb", card.styleSheet())
            card.ensurePolished()
            label.ensurePolished()
            self.assertEqual(label.palette().color(label.foregroundRole()).name(),
                             CARD_TEXT if label is not histology.image_status else "#526570")
        self.assertIn("#f8fafb", histology.caption.styleSheet())

    def test_full_authored_inventory_remains_discoverable(self):
        browser = self.browser()
        self.assertTrue(self.authored_ids)
        self.assertEqual(len(set(self.authored_ids)), len(self.authored_ids), "Duplicate authored case IDs")
        self.assertCountEqual([c.id for c in self.cases], self.authored_ids)
        self.assertEqual(set(browser.visible_case_ids()), {c.id for c in self.cases})

    def test_multiword_search_is_order_independent(self):
        browser = self.browser()
        browser.filter.setText("kidney ct")
        self.assertIn("ct_abdo_kidney", browser.visible_case_ids())
        self.assertTrue(matches_words("ct kidney", "Kidney in a CT scan"))

    def test_filters_intersect_reset_and_retain_selection(self):
        browser = self.browser()
        browser.set_current_case("ct_abdo_kidney")
        browser.filters["modality"].setCurrentText("CT")
        self.assertEqual(browser.list.currentItem().data(Qt.UserRole), "ct_abdo_kidney")
        browser.filter.setText("__no_case__")
        self.assertEqual(browser.visible_case_ids(), [])
        self.assertFalse(browser.open_case.isEnabled())
        self.assertIn("No case matches", browser.empty_state.text())
        browser.reset_filters()
        self.assertCountEqual(browser.visible_case_ids(), self.authored_ids)

    def test_empty_catalogue_has_actionable_state(self):
        browser = self.own(RadiologyBrowser([]))
        self.assertIn("No radiology cases", browser.empty_state.text())
        self.assertFalse(browser.open_case.isEnabled())

    def test_search_return_opens_existing_case(self):
        browser = self.browser()
        chosen = []
        browser.caseChosen.connect(chosen.append)
        browser.filter.setText("ct kidney")
        QTest.keyClick(browser.filter, Qt.Key_Return)
        self.assertTrue(chosen)
        self.assertIn(chosen[0], browser.visible_case_ids())

    def test_radiology_load_keeps_labels_source_and_clinical_text(self):
        panel = self.own(RadiologyPanel())
        case = next(c for c in self.cases if c.id == "ct_abdo_kidney")
        panel.show_case(case)
        settle(lambda: not panel.view.pixmap.isNull())
        self.assertEqual(panel.legend.count(), len(case.labels))
        self.assertEqual(panel.atlas_note.text(), case.atlas_note)
        self.assertIn(case.credit(), panel.credit.text())
        self.assertTrue(panel.fit_scan.isEnabled())

    def test_radiology_missing_image_is_clear_and_retryable(self):
        panel = self.own(RadiologyPanel())
        case = copy.copy(self.cases[0])
        case.image = Path("/nonexistent/radiology-workspace-missing.png")
        panel.show_case(case)
        settle(lambda: "missing" in panel.image_status.text())
        self.assertTrue(panel.view.pixmap.isNull())
        self.assertFalse(panel.fit_scan.isEnabled())
        self.assertFalse(panel.retry_image.isHidden())

    def test_radiology_zoom_keyboard_and_fit(self):
        view = self.own(RadiographView())
        pix = QPixmap(80, 40)
        pix.fill(Qt.white)
        view.set_case(pix, [])
        QTest.keyClick(view, Qt.Key_Plus)
        self.assertGreater(view._zoom, 1)
        QTest.keyClick(view, Qt.Key_Home)
        self.assertEqual(view._zoom, 1)

    def test_histology_tissue_search_keeps_its_images_visible(self):
        browser = self.own(HistologyBrowser(self.ds, self.content))
        browser.filter.setText("Simple squamous epithelium")
        root = browser.tree.invisibleRootItem()
        stack = [root]
        found = None
        while stack:
            item = stack.pop()
            if item.data(0, ROLE) == ("tissue", "simple_squamous", 0):
                found = item
                break
            stack.extend(item.child(i) for i in range(item.childCount()))
        self.assertIsNotNone(found)
        self.assertFalse(found.isHidden())
        self.assertTrue(all(not found.child(i).isHidden() for i in range(found.childCount())))

    def test_histology_no_match_and_reset(self):
        browser = self.own(HistologyBrowser(self.ds, self.content))
        browser.filter.setText("__no_tissue__")
        self.assertEqual(browser.count_label.text(), "0 topics shown")
        self.assertFalse(browser.empty_state.isHidden())
        browser._reset_filter()
        self.assertTrue(browser.empty_state.isHidden())

    def test_histology_image_selection_and_export_credit(self):
        viewer = self.viewer()
        viewer.show_tissue("simple_squamous", 1)
        settle(lambda: not viewer.view.item.pixmap().isNull())
        self.assertEqual(viewer.image_choice.currentIndex(), 1)
        self.assertEqual(viewer.strip.currentRow(), 1)
        title, _, credit = viewer.figure_caption()
        image = viewer.tissue["images"][1]
        self.assertEqual(title, image["title"])
        self.assertIn(image["license"], credit)
        self.assertIn(image["source"], credit)
        viewer.next_image.click()
        self.assertEqual(viewer.index, 2)

    def test_newer_histology_navigation_wins_over_pending_image(self):
        viewer = self.viewer()
        viewer.show_tissue("simple_squamous", 0)
        viewer.show_image(3)
        settle(lambda: not viewer.view.item.pixmap().isNull())
        expected = QImage(str(self.content.image_path(viewer.tissue["images"][3])))
        self.assertEqual(viewer.view.item.pixmap().size(), expected.size())
        self.assertEqual(viewer.index, 3)
        self.assertEqual(viewer.image_choice.currentIndex(), 3)

    def test_missing_histology_tissue_clears_previous_image(self):
        viewer = self.viewer()
        viewer.show_tissue("simple_squamous", 0)
        viewer.show_tissue("__missing__")
        QTest.qWait(80)
        self.assertIsNone(viewer.tissue)
        self.assertTrue(viewer.view.item.pixmap().isNull())
        self.assertFalse(viewer.next_image.isEnabled())
        self.assertIn("No images", viewer.view._message)

    def test_histology_zoom_is_bounded_and_fit_is_available(self):
        view = self.own(ImageView())
        pix = QPixmap(100, 50)
        pix.fill(Qt.white)
        view.set_pixmap(pix)
        for _ in range(40):
            view.zoom_by(1)
        self.assertLessEqual(view.transform().m11(), 20.0001)
        QTest.keyClick(view, Qt.Key_Home)
        self.assertTrue(view._fit)

    def test_image_loader_ignores_stale_and_cancelled_results(self):
        loader = LocalImageLoader()
        got = []
        loader.loaded.connect(lambda *_: got.append(True))
        loader._serial = 3
        loader._receive(2, QImage(), "older")
        self.assertFalse(got)
        loader.cancel()
        loader._receive(3, QImage(), "cancelled")
        self.assertFalse(got)
        loader._receive(4, QImage(), "current")
        self.assertEqual(got, [True])

    def test_full_inventory_metadata_routes_keep_authored_content(self):
        panel = self.own(RadiologyPanel())
        with patch.object(panel._scan_loader, "load"), patch.object(panel._diagram_loader, "load"):
            for case in self.cases:
                panel.show_case(case)
                self.assertIs(panel.case, case)
                self.assertEqual(panel.title.text(), case.title)
                self.assertEqual(panel.legend.count(), len(case.labels))
                self.assertEqual(panel.question_choice.count(), len(case.questions))
                self.assertEqual(panel.atlas_note.text(), case.atlas_note)
                if case.questions:
                    self.assertIn(case.questions[0]["prompt"], panel.check_notes.toPlainText())

    def test_self_check_reveal_hide_and_question_change(self):
        panel = self.own(RadiologyPanel())
        case = next(c for c in self.cases if len(c.questions) > 1)
        with patch.object(panel._scan_loader, "load"), patch.object(panel._diagram_loader, "load"):
            panel.show_case(case)
            self.assertNotIn("Answer:", panel.check_notes.toPlainText())
            panel._show_answer()
            self.assertIn("Answer:", panel.check_notes.toPlainText())
            self.assertTrue(panel.read_question.isEnabled())
            panel.question_choice.setCurrentIndex(1)
            self.assertNotIn("Answer:", panel.check_notes.toPlainText())
            self.assertIn(case.questions[1]["prompt"], panel.check_notes.toPlainText())

    def test_histology_page_keys_advance_once_from_each_focus_target(self):
        viewer = self.viewer()
        viewer.show_tissue("simple_squamous", 0)
        viewer.resize(800, 650)
        viewer.show()
        viewer.activateWindow()
        QAPP.processEvents()
        for target in (viewer, viewer.view, viewer.strip):
            viewer.show_image(0)
            target.setFocus()
            QAPP.processEvents()
            QTest.keyClick(target, Qt.Key_PageDown)
            self.assertEqual(viewer.index, 1)
            QTest.keyClick(target, Qt.Key_PageUp)
            self.assertEqual(viewer.index, 0)

    def test_missing_histology_image_keeps_caption_and_can_retry(self):
        content = content_fixture()
        good_path = content.image_path
        content.image_path = lambda _img: Path("/nonexistent/histology-workspace-missing.png")
        viewer = self.own(HistologyViewer(self.ds, content))
        viewer.show_tissue("simple_squamous", 0)
        settle(lambda: "missing" in viewer.image_status.text())
        self.assertTrue(viewer.view.item.pixmap().isNull())
        self.assertIn(viewer.tissue["images"][0]["title"], viewer.caption.toPlainText())
        self.assertFalse(viewer.retry_image.isHidden())
        content.image_path = good_path
        viewer.retry_image.click()
        settle(lambda: not viewer.view.item.pixmap().isNull())
        self.assertTrue(viewer.retry_image.isHidden())

    def test_closing_viewer_during_pending_decode_is_safe(self):
        viewer = HistologyViewer(self.ds, self.content)
        viewer.show_tissue("simple_squamous", 0)
        viewer.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QTest.qWait(80)

    def test_corrupt_image_reports_read_error(self):
        loader = LocalImageLoader()
        result = []
        loader.loaded.connect(lambda image, error: result.append((image, error)))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.png"
            path.write_text("not an image")
            loader.load(path)
            settle(lambda: bool(result))
        self.assertTrue(result[0][0].isNull())
        self.assertIn("could not be read", result[0][1])


if __name__ == "__main__":
    unittest.main()
