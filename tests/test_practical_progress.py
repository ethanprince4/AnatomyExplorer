"""Actual authored practice-only lesson completion agrees across library/progress UI."""
from pathlib import Path
import json
import os
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "app/main_window.py").exists())
sys.path.insert(0, str(ROOT))
from test_state_and_recovery import QAPP, MainWindow, Dataset, config
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QLabel
from app.lessons import Lesson, LessonProgress, practice_pool
from app.ui.practice import PracticeController
from app.ui.progress import LessonBars, ProgressDialog


class PracticalProgressTests(unittest.TestCase):
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
        self.lp = self.win.lessons_panel
        path = Path(config.USER_DIR) / (self._testMethodName + ".json")
        self.lp.progress = LessonProgress(path)

    def _close(self):
        self.win.close()
        self.win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def _finish_actual_practical(self, correct=True):
        practicals = [l for l in self.lp.lessons if not len(l) and l.has_practice()]
        self.assertTrue(practicals, "use an actual authored practice-only exam")
        controller = PracticeController(self.win, self.lp)
        self.lp.practice = controller
        for practical in practicals:
            pool = controller._prepare(practice_pool(practical, self.lp.lessons))
            item = next((x for x in pool if x["type"] == "mcq"), None)
            if item is not None:
                break
        self.assertIsNotNone(item, "existing exam must contain an available MCQ")
        self.assertFalse(self.lp._finished(practical))
        self.assertEqual(self.lp.progress.totals([practical]), (0, 0, 1))
        # Freeze only the random question draw to a real authored MCQ, avoiding model
        # opening/builds. Start is a new ordinary session, not the missed-item retry.
        with patch("app.ui.practice.build_session", return_value=[item]):
            controller.start(practical, n=1)
        self.assertFalse(controller.retrying)
        right = controller.cur["right"]
        answer = right if correct else (right + 1) % len(controller.cur["options"])
        controller.answer_choice(answer)
        controller.next_item()
        self.assertEqual(controller.results, [(item, correct)])
        self.assertTrue(self.lp._finished(practical), "the actual library considers the practised exam finished")
        self.assertEqual(self.lp.progress.practice(practical.id)["sessions"], 1)
        return practical

    def _record_dialog(self, dialog, practical):
        if not os.environ.get("APP_QA_PRACTICAL_EVIDENCE"):
            return
        folder = Path(os.environ["APP_QA_PRACTICAL_EVIDENCE"]).resolve()
        self.assertTrue(folder.is_relative_to(ROOT / "local-verification/app-qa-v2"))
        folder.mkdir(parents=True, exist_ok=True)
        from tests.test_figure_export import FONT
        dialog.setFont(FONT)
        dialog.resize(580, 680)
        dialog.show()
        QAPP.processEvents()
        self.assertTrue(dialog.grab().save(str(folder / "practice-exam-progress.png")))
        value = {"lesson_id": practical.id, "lesson_title": practical.title,
                 "reading_steps": len(practical), "library_finished": self.lp._finished(practical),
                 "progress_totals": self.lp.progress.totals([practical]),
                 "system_bars": dialog.findChild(LessonBars).rows,
                 "persisted": json.loads(self.lp.progress.path.read_text(encoding="utf-8")),
                 "labels": [x.text() for x in dialog.findChildren(QLabel)]}
        (folder / "practice-exam-progress.json").write_text(json.dumps(value, indent=2), encoding="utf-8")

    def test_finished_authored_practice_exam_is_in_progress_totals_after_relaunch(self):
        practical = self._finish_actual_practical()
        reloaded = LessonProgress(self.lp.progress.path)
        self.assertEqual(reloaded.practice(practical.id)["sessions"], 1)
        self.assertEqual(reloaded.totals([practical]), (1, 0, 1),
                         "a finished practice-only exam must count toward the same library total")

    def test_actual_progress_dialog_counts_finished_practice_exam_and_system_bar(self):
        practical = self._finish_actual_practical()
        dialog = ProgressDialog(self.win.quiz.stats, [practical], self.lp.progress, self.win)
        try:
            self._record_dialog(dialog, practical)
            with self.subTest(summary=True):
                self.assertIn("1 of 1 finished · 0 in progress", [x.text() for x in dialog.findChildren(QLabel)])
            with self.subTest(system_bars=True):
                bars = dialog.findChild(LessonBars)
                self.assertEqual([(done, total) for heading, done, total in bars.rows], [(1, 1)])
        finally:
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_completed_practice_exam_does_not_require_a_passing_score(self):
        practical = self._finish_actual_practical(correct=False)
        self.assertEqual(self.lp.progress.practice(practical.id)["last"], 0)
        self.assertEqual(LessonProgress(self.lp.progress.path).totals([practical]), (1, 0, 1))

    def test_practice_does_not_finish_an_unread_reading_lesson(self):
        lesson = Lesson({"id": "fixture-reading", "title": "Fixture reading", "steps": [{}, {}]})
        self.lp.progress.record_practice(lesson.id, 1, 1)
        self.assertFalse(self.lp._finished(lesson))
        self.assertEqual(self.lp.progress.totals([lesson]), (0, 0, 1))
        self.lp.progress.visit(lesson.id, 0, len(lesson))
        self.assertEqual(self.lp.progress.totals([lesson]), (0, 1, 1))
        self.lp.progress.set_done(lesson.id, len(lesson))
        self.assertEqual(self.lp.progress.totals([lesson]), (1, 0, 1))


if __name__ == "__main__":
    unittest.main()
