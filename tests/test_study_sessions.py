"""Interrupted/repeated study flows with isolated preferences and real controllers."""
import unittest
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QCheckBox, QWidget
from test_state_and_recovery import QAPP, config, fixture_dataset
from app.data import Dataset
from app.lessons import Lesson
from app.main_window import MainWindow
from app.state import SceneState
from app.ui.practice import PracticeController
from app.ui.quiz import QuizController, GREEN, RED
from app.ui.model_view import ModelView
from app.viewer.camera import OrbitCamera


class StudyColorTests(unittest.TestCase):
    def setUp(self):
        self.ds = fixture_dataset()
        self.ds.bounds_of = lambda sids: None
        self.state = SceneState(self.ds, dict(config.DEFAULT_SETTINGS))
        self.original = {0: (0.15, 0.3, 0.7), 2: (0.8, 0.2, 0.5)}
        self.state.custom_colors = dict(self.original)
        self.win = SimpleNamespace(ds=self.ds, state=self.state,
                                   viewport=SimpleNamespace(frame_structures=lambda *args: None))

    def test_quiz_wrong_click_flash_preserves_preexisting_colors(self):
        quiz = QuizController(self.win)
        try:
            quiz._flash_structures([0, 1], RED)
            self.assertEqual(self.state.custom_colors[0], RED)
            quiz._clear_flash()
            self.assertEqual(self.state.custom_colors, self.original)
            quiz._flash_structures([0], RED)
            quiz._flash_structures([1], RED)
            quiz._clear_flash()
            self.assertEqual(self.state.custom_colors, self.original)
        finally:
            quiz._flash_timer.stop()

    def test_quiz_answer_highlight_preserves_preexisting_colors(self):
        quiz = QuizController(self.win)
        quiz.current = {"sids": [0, 1], "base": "Fixture"}
        quiz.panel = SimpleNamespace(prompt=SimpleNamespace(setText=lambda text: None))
        quiz._show_answer(GREEN)
        self.assertEqual(self.state.custom_colors[0], GREEN)
        quiz._clear_marks()
        self.assertEqual(self.state.custom_colors, self.original)

    def test_practice_wrong_click_and_answer_restore_preexisting_colors(self):
        practice = PracticeController(self.win, SimpleNamespace())
        try:
            practice._flash_red(self.state, [0, 1])
            practice._clear_flash()
            self.assertEqual(self.state.custom_colors, self.original)
            practice._show_answer([0, 1], GREEN)
            practice._end_item()
            self.assertEqual(self.state.custom_colors, self.original)
        finally:
            practice._flash_timer.stop()


class StudyLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset(config.DATA_DIR)

    def tearDown(self):
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_interrupted_quiz_and_practice_restore_scene_and_prior_undo_history(self):
        for kind in ("quiz", "practice"):
            with self.subTest(kind=kind):
                QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
                win = MainWindow(self.dataset, restore=False)
                session = None
                try:
                    mid = ((self.dataset.scene_bbox[0] + self.dataset.scene_bbox[1]) / 2).tolist()
                    win.view_panel.set_clips([False, True, False], mid, [False, False, False])
                    win.view_panel.set_depth(0.55, True)
                    win.state.select([0])
                    win.state.set_custom_color([0], (0.2, 0.3, 0.8))
                    win.state.set_hidden([1], True)
                    before = win.capture_view()
                    undo_count = len(win.state._undo)
                    if kind == "quiz":
                        session = win.quiz
                        session.open()
                        session.panel.mode.setCurrentIndex(1)
                        session.start()
                    else:
                        session = PracticeController(win, win.lessons_panel)
                        win.lessons_panel.practice = session
                        lesson = Lesson({"id": "fixture-scene", "title": "Fixture", "steps": [], "practice": []})
                        session.start(lesson, items=[{"type": "find", "structure": self.dataset.structures[0]["base"],
                                                       "_sids": [0]}])
                    self.assertTrue(session.active)
                    session.stop()
                    after = win.capture_view()
                    self.assertEqual(after["selected"], before["selected"])
                    self.assertEqual(after["clip"][0], before["clip"][0])
                    self.assertTrue(np.allclose(after["clip"][1], before["clip"][1]))
                    self.assertEqual(after["dissection"], before["dissection"])
                    self.assertEqual(after["custom_colors"], before["custom_colors"])
                    self.assertEqual(after["camera"], before["camera"])
                    self.assertEqual(len(win.state._undo), undo_count)
                    win.undo()
                    self.assertFalse(win.state.hidden[1], "undo after study must undo the learner's preceding edit")
                finally:
                    if session is not None:
                        session.stop()
                    win.close()
                    win.deleteLater()

    def test_model_practice_restores_labels_colors_visibility_camera_and_undo(self):
        # Exercise the real ModelView controller with a tiny model-free scene;
        # the check does not build/open/alter any authored model or GPU renderer.
        view = ModelView.__new__(ModelView)
        QWidget.__init__(view)
        ds = fixture_dataset()
        view.mds = ds
        view.state = SceneState(ds, dict(config.DEFAULT_SETTINGS))
        view.click_hook = view.rclick_hook = None
        view.side = QWidget(view)
        view.side.hide()
        view.labels = QCheckBox(view)
        view.labels.setChecked(True)
        view.view_buttons = {}
        camera = OrbitCamera()
        camera.target = np.array([0.2, 0.4, 0.6])
        camera.distance, camera.yaw, camera.pitch = 1.5, 0.7, 0.2

        def reset_camera(**kwargs):
            camera.target = np.zeros(3)
            camera.distance, camera.yaw, camera.pitch = 3.0, 0.0, 0.0

        view.gl_widget = SimpleNamespace(camera=camera, reset_view=reset_camera,
                                         invalidate_labels=lambda: None, update=lambda: None,
                                         isVisible=lambda: True, frame_structures=lambda sids: None)
        view.state.set_hidden([1], True)
        view.state.select([0])
        view.state.set_ghost_focus([0])
        view.state.set_custom_color([0], (0.1, 0.2, 0.9))
        before = view.state.visible_mask().copy()
        original_camera = (camera.target.copy(), camera.distance, camera.yaw, camera.pitch)
        undo_count = len(view.state._undo)
        practice = PracticeController(SimpleNamespace(ds=ds, state=view.state), SimpleNamespace())
        try:
            view.set_practice(lambda sid: True, lambda sid: None)
            self.assertFalse(view.labels.isChecked())
            practice.cur = {"view": view, "sids": [0]}
            practice._show_micro_answer()
            practice._end_item()
            self.assertTrue(view.labels.isChecked())
            self.assertTrue(view.side.isHidden())
            self.assertEqual(view.state.custom_colors, {0: (0.1, 0.2, 0.9)})
            self.assertEqual(view.state.selected, [0])
            self.assertTrue(np.array_equal(view.state.visible_mask(), before))
            self.assertTrue(np.array_equal(view.state.ghost_focus, [True, False, False, False]))
            self.assertTrue(np.array_equal(camera.target, original_camera[0]))
            self.assertEqual((camera.distance, camera.yaw, camera.pitch), original_camera[1:])
            self.assertEqual(len(view.state._undo), undo_count)
            view.state.undo()
            self.assertFalse(view.state.hidden[1])
        finally:
            practice._flash_timer.stop()
            view.close()
            view.deleteLater()


if __name__ == "__main__":
    unittest.main()
