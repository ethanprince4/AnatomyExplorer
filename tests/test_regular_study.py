"""Actual study entry-point regressions; only temporary Qt preferences/user files."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "app/main_window.py").exists())
sys.path.insert(0, str(ROOT))
from test_state_and_recovery import QAPP, MainWindow, Dataset, config
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QLabel, QWidget
from app.lessons import Lesson
from app.ui.practice import PracticeController
from app.ui.progress import ProgressDialog
import app.ui.quiz as quiz_module


class RegularStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset(config.DATA_DIR)

    def setUp(self):
        fixture_root = Path(config.USER_DIR).resolve().parent
        self.assertTrue(fixture_root.name.startswith("anatomy-regression-"))
        prefs = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
        self.assertTrue(Path(prefs.fileName()).resolve().is_relative_to(fixture_root))
        prefs.clear()
        self.path = Path(config.USER_DIR) / "quiz_stats.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.original = '{"Frontal bone":{"seen":1,"miss":0}}'
        self.path.write_text(self.original, encoding="utf-8")
        self.path_patch = patch.object(quiz_module, "STATS_PATH", self.path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.win = MainWindow(self.dataset, restore=False)
        self.addCleanup(self._close)

    def _close(self):
        self.win.close()
        self.win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def _record(self, label, value):
        if not os.environ.get("APP_QA_EVIDENCE"):
            return
        folder = Path(os.environ["APP_QA_EVIDENCE"]).resolve()
        self.assertTrue(folder.is_relative_to(ROOT / "local-verification/app-qa-v2"))
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (label + ".json")).write_text(json.dumps(value, indent=2,
                                                         default=lambda x: x.tolist()), encoding="utf-8")

    def _progress_answers(self, entry, label):
        values = []

        def inspect_dialog(dialog):
            for tile in dialog.findChildren(QWidget, "statTile"):
                labels = [w.text() for w in tile.findChildren(QLabel)]
                if "Questions answered" in labels:
                    values.append(int(labels[0].replace(",", "")))
            if os.environ.get("APP_QA_CAPTURE"):
                folder = Path(os.environ["APP_QA_CAPTURE"]).resolve()
                self.assertTrue(folder.is_relative_to(ROOT / "local-verification/app-qa-v2"))
                folder.mkdir(parents=True, exist_ok=True)
                from tests.test_figure_export import FONT
                dialog.setFont(FONT)
                dialog.resize(580, 680)
                self.assertTrue(dialog.grab().save(str(folder / (label + ".png"))))
            dialog.deleteLater()
            return 0

        with patch.object(ProgressDialog, "exec", inspect_dialog):
            entry()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertEqual(len(values), 1)
        return values[0]

    def _assert_pending_progress(self, kind):
        if kind == "quiz":
            controller = self.win.quiz
            controller.open()
            controller.panel.mode.setCurrentIndex(controller.panel.mode.findData("typed"))
            controller.panel.small.setChecked(True)
            controller.start(bases=["Frontal bone"])
            controller.panel.typed.setText("incorrect fixture answer")
            answer = controller.answer_typed
        else:
            controller = PracticeController(self.win, self.win.lessons_panel)
            self.win.lessons_panel.practice = controller
            lesson = Lesson({"id": "fixture-progress", "title": "Fixture", "steps": [], "practice": []})
            controller.start(lesson, items=[{"type": "recall", "q": "Fixture question", "a": "Fixture answer"}])
            controller.reveal_recall()
            answer = lambda: controller.grade_recall(False)
        with patch.object(quiz_module, "write_json", side_effect=OSError("fixture disk full")):
            answer()
        self.assertIn("Could not save study results:", self.win.statusBar().currentMessage())
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.original)
        pending_menu = self._progress_answers(self.win.show_progress, kind + "-menu-before")
        pending_quiz = self._progress_answers(self.win.quiz.show_progress, kind + "-quiz")
        self.assertEqual(pending_quiz, 2, "the actual grade must remain in the shared session store")
        self.assertTrue(self.win.quiz.save_stats())
        persisted_menu = self._progress_answers(self.win.show_progress, kind + "-menu-after-retry")
        self.assertEqual(persisted_menu, 2, "ordinary persisted progress remains correct")
        self._record(kind + "-progress", {"pending_main_menu": pending_menu, "pending_quiz_menu": pending_quiz,
                                          "persisted_main_menu_after_retry": persisted_menu,
                                          "original_file": self.original, "fixture_settings": self.win.qsettings.fileName()})
        self.assertEqual(pending_menu, 2, "the main menu must show the current grade even before save retry")

    def test_main_progress_uses_pending_quiz_result_when_save_fails(self):
        self._assert_pending_progress("quiz")

    def test_main_progress_uses_pending_practice_result_when_save_fails(self):
        self._assert_pending_progress("practice")

    def test_main_progress_without_quiz_controller_reads_persisted_history(self):
        controller = self.win.quiz
        self.win.quiz = None
        try:
            self.assertEqual(self._progress_answers(self.win.show_progress, "fallback"), 1)
            self.path.write_text("{invalid saved fixture", encoding="utf-8")
            self.assertEqual(self._progress_answers(self.win.show_progress, "fallback-damaged"), 0)
            self.assertEqual(self.path.read_text(encoding="utf-8"), "{invalid saved fixture")
        finally:
            self.win.quiz = controller

    def test_repeated_section_quiz_restores_initial_scene_and_name_preferences(self):
        win = self.win
        names = ["Frontal bone", "Parietal bone", "Temporal bone", "Mandible"]
        sids = [next(i for i, meta in enumerate(self.dataset.structures) if meta["base"] == name) for name in names]
        mid = (self.dataset.scene_bbox[0] + self.dataset.scene_bbox[1]) / 2
        win.view_panel.set_clips([False, True, False], mid.tolist(), [False, False, False])
        win.state.select([sids[0]])
        win.state.set_hidden([sids[1]], True)
        win.state.set_custom_color([sids[0]], (0.2, 0.3, 0.8))
        win.settings["show_landmarks"] = True
        win.settings["show_hover_tooltip"] = True
        before = copy.deepcopy(win.capture_view())
        undo_count = len(win.state._undo)
        # Freeze the section-anchor producer output. This exercises the real menu/controller
        # route without requiring a renderer or modifying any authored model/atlas asset.
        win.viewport.section_anchors = [(sid, mid.copy(), 1.0) for sid in sids]
        win.quiz_section()
        self.assertTrue(win.quiz.active)
        self.assertIsNotNone(win.quiz.current)
        self.assertFalse(win.settings["show_landmarks"])
        first_snapshot = copy.deepcopy(win.quiz._vis_snapshot["view"])
        self.assertEqual(first_snapshot, before)
        self.assertTrue(win.quiz.handle_right_click(sids[2]))
        self.assertTrue(win.state.hidden[sids[2]], "the learner can peel a structure during the first quiz")
        win.viewport.camera.orbit(15, 10)
        win.quiz_section()
        self.assertTrue(win.quiz.active)
        self.assertIsNotNone(win.quiz.current)
        win.quiz.stop()
        after = win.capture_view()
        self._record("repeated-section", {"before": before, "after": after,
                                          "undo_before": undo_count, "undo_after": len(win.state._undo),
                                          "landmarks_after": win.settings["show_landmarks"],
                                          "hover_names_after": win.settings["show_hover_tooltip"]})
        self.assertEqual(after, before, "a replacement section quiz must still restore the pre-study scene")
        self.assertEqual(len(win.state._undo), undo_count)
        self.assertTrue(win.settings["show_landmarks"])
        self.assertTrue(win.settings["show_hover_tooltip"])
        win.undo()
        self.assertFalse(win.state.hidden[sids[1]], "pre-study undo history must survive replacement")


if __name__ == "__main__":
    unittest.main()
