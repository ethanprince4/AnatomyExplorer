"""Focused contracts for the native Practice entry page."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.practice import PracticeHome


APP = QApplication.instance() or QApplication([])


class PracticeHomeTests(unittest.TestCase):
    def setUp(self):
        self.page = PracticeHome()

    def tearDown(self):
        self.page.close()
        self.page.deleteLater()
        APP.processEvents()

    def test_start_actions_emit_existing_modes(self):
        starts = []
        self.page.startRequested.connect(starts.append)
        self.page.course.click()
        self.page.mixed.click()
        self.assertEqual(starts, ["course", "mixed"])

    def test_due_count_is_only_shown_when_supplied(self):
        self.assertEqual(self.page.review.text(), "Review what is due")
        self.assertTrue(self.page.review.isEnabled())
        self.page.set_due(0)
        self.assertEqual(self.page.review.text(), "Review what is due · 0")
        self.assertFalse(self.page.review.isEnabled())
        self.page.set_due(3)
        self.assertEqual(self.page.review.text(), "Review what is due · 3")
        self.assertTrue(self.page.review.isEnabled())

    def test_session_results_require_real_summary_fields(self):
        self.page.show_results({"right": 4, "total": 5})
        self.assertEqual(self.page.results.text(), "Last session · 4 of 5 correct")
        self.page.show_results({})
        self.assertTrue(self.page.results.isHidden())


if __name__ == "__main__":
    unittest.main()
