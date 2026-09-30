"""Regression checks for visibility controls and source-run recovery.

Run: .venv\Scripts\python.exe -B -m unittest discover -s tests -v
Qt windows stay hidden and all preference/study fixtures live in a temporary
directory, so running this suite cannot read or overwrite real study data.
"""
import json
import atexit
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
from PySide6.QtCore import QByteArray, QCoreApplication, QEvent, QSettings, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLabel

from app import config
from app.__main__ import configure_qt
from app.data import Dataset
from app.state import SceneState
from tests.fixture_paths import fixture_root

FIXTURES = tempfile.TemporaryDirectory(prefix="anatomy-regression-")
atexit.register(FIXTURES.cleanup)
FIXTURE_ROOT = fixture_root(FIXTURES.name)
config.USER_DIR = FIXTURE_ROOT / "study"
config.ORG_NAME = "AnatomyExplorerRegression"
config.APP_NAME = "Fixture"
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(FIXTURE_ROOT))
QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, str(FIXTURE_ROOT))
configure_qt()
QAPP = QApplication.instance() or QApplication([])

# Import only after redirecting user paths and preference storage above.
from app.main_window import MainWindow


def fixture_dataset():
    return SimpleNamespace(
        n=4,
        systems=[{"key": "skeletal", "default_visible": True, "color": [1, 1, 1]},
                 {"key": "muscular", "default_visible": False, "color": [1, 0, 0]}],
        regions=[],
        system_of=np.array([0, 0, 1, 1], dtype=np.int32),
        subsystem_of=np.array([0, 1, 2, 2], dtype=np.int32),
        subsystem_default=[True, True, True],
        subsystem_system=np.array([0, 0, 1], dtype=np.int32),
        subsystems_by_system=[np.array([0, 1]), np.array([2])],
        region_mask=np.zeros(4, dtype=np.int64),
    )


class VisibilityTests(unittest.TestCase):
    def setUp(self):
        self.state = SceneState(fixture_dataset(), dict(config.DEFAULT_SETTINGS))

    def test_show_all_normal_anatomy_excludes_findings_without_losing_explicit_access(self):
        ds = fixture_dataset()
        ds.systems.append({"key": "findings", "default_visible": False, "color": [1, 0.5, 0]})
        ds.n = 5
        ds.system_of = np.append(ds.system_of, 2)
        ds.subsystem_of = np.append(ds.subsystem_of, 3)
        ds.subsystem_default.append(True)
        ds.subsystem_system = np.append(ds.subsystem_system, 2)
        ds.subsystems_by_system.append(np.array([3]))
        ds.region_mask = np.zeros(5, dtype=np.int64)
        st = SceneState(ds, dict(config.DEFAULT_SETTINGS))
        st.force_show([4])
        st.isolate([4])
        before = st.visible_mask().copy()
        st.show_all()
        self.assertEqual(np.flatnonzero(st.visible_mask()).tolist(), [0, 1, 2, 3])
        st.undo()
        self.assertTrue(np.array_equal(st.visible_mask(), before))
        st.set_system(2, True)
        self.assertTrue(st.visible_mask()[4])
        st.reset_visibility()
        self.assertFalse(st.visible_mask()[4])
        st.force_show([4])
        self.assertTrue(st.visible_mask()[4])
        st.reset_visibility()
        self.assertFalse(st.visible_mask()[4])
        st.undo()
        self.assertTrue(st.visible_mask()[4])

    def test_isolation_excludes_earlier_search_reveals_and_undo_restores_them(self):
        st = self.state
        st.force_show([2])
        st.isolate([0])
        self.assertEqual(np.flatnonzero(st.visible_mask()).tolist(), [0])
        st.undo()
        self.assertEqual(np.flatnonzero(st.visible_mask()).tolist(), [0, 1, 2])

    def test_isolation_keeps_selected_search_reveal_visible_below_dissection(self):
        st = self.state
        st.depth = np.array([0.1, 0.7, 0.2, 0.8])
        st.set_depth(0.5)
        st.force_show([0, 2])
        st.isolate([2])
        self.assertEqual(np.flatnonzero(st.visible_mask()).tolist(), [2])

    def test_system_off_and_on_work_during_isolation(self):
        st = self.state
        st.isolate([0])
        st.set_system(0, False)
        self.assertFalse(st.visible_mask().any())
        st.undo()
        self.assertEqual(np.flatnonzero(st.visible_mask()).tolist(), [0])
        st.set_system(0, True)
        self.assertEqual(np.flatnonzero(st.visible_mask()).tolist(), [0, 1])

    def test_subsystem_off_and_on_work_during_isolation(self):
        st = self.state
        st.isolate([0, 1])
        st.set_subsystem(0, False)
        self.assertEqual(np.flatnonzero(st.visible_mask()).tolist(), [1])
        st.set_subsystem(0, True)
        self.assertEqual(np.flatnonzero(st.visible_mask()).tolist(), [0, 1])

    def test_reset_commands_undo_dissection_and_update_controls(self):
        for method in ("show_all", "reset_visibility"):
            with self.subTest(method=method):
                st = SceneState(fixture_dataset(), dict(config.DEFAULT_SETTINGS))
                st.set_depth(0.55, 0.13)
                display = []
                win = SimpleNamespace(state=st)

                def set_depth(cut, band):
                    display.append((cut, band))
                    MainWindow.on_depth_changed(win, cut, 0.13 if band else 0.0)

                win.view_panel = SimpleNamespace(set_depth=set_depth)
                getattr(MainWindow, method)(win)
                self.assertEqual((st.depth_cut, st.depth_band), (0.0, 0.0))
                MainWindow.undo(win)
                self.assertEqual((st.depth_cut, st.depth_band), (0.55, 0.13))
                self.assertEqual(display[-1], (0.55, True))
                self.assertEqual(len(st._undo), 0)

    def test_restored_dissection_applies_when_background_depth_arrives(self):
        st = self.state
        st.set_depth(0.5)
        self.assertEqual(np.flatnonzero(st.visible_mask()).tolist(), [0, 1])
        win = SimpleNamespace(
            state=st, depth_index=SimpleNamespace(depth=np.array([0.1, 0.7, 0.2, 0.8])),
            info=SimpleNamespace(depth=None), view_panel=SimpleNamespace(enable_depth=lambda enabled: None),
            section_index=SimpleNamespace(ready=False),
        )
        MainWindow._depth_ready(win)
        self.assertEqual(np.flatnonzero(st.visible_mask()).tolist(), [1])

    def test_failed_model_open_preserves_existing_override_cursor(self):
        entry = SimpleNamespace(name="Fixture bad model")
        status = SimpleNamespace(showMessage=lambda *args: None)
        win = SimpleNamespace(micro_tabs={}, content=SimpleNamespace(micro_models={"bad": entry}),
                              settings={}, statusBar=lambda: status)
        QApplication.setOverrideCursor(Qt.CrossCursor)
        try:
            with patch("app.ui.model_view.ModelView", side_effect=ValueError("fixture load failure")), \
                    contextlib.redirect_stderr(io.StringIO()):
                MainWindow.open_micro(win, "bad")
            cursor = QApplication.overrideCursor()
            self.assertIsNotNone(cursor)
            self.assertEqual(cursor.shape(), Qt.CrossCursor)
        finally:
            QApplication.restoreOverrideCursor()


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset(config.DATA_DIR)

    def tearDown(self):
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_saved_color_components_outside_picker_domain_reject_atomically(self):
        for rgb in ([-0.1, 0.2, 0.3], [0.1, 1.1, 0.3], [1e100, 0.2, 0.3]):
            with self.subTest(rgb=rgb):
                prefs = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
                self.assertTrue(Path(prefs.fileName()).resolve().is_relative_to(Path(FIXTURES.name).resolve()))
                prefs.clear()
                win = MainWindow(self.dataset, restore=False)
                try:
                    win.state.set_hidden([1], True)
                    win.state.set_custom_color([0], (0.2, 0.3, 0.4))
                    before, damaged = win.capture_view(), win.capture_view()
                    undos = len(win.state._undo)
                    damaged["hidden"] = []
                    damaged["custom_colors"] = {"0": rgb}
                    win.apply_view(damaged, animate=False)
                    self.assertEqual(win.capture_view(), before)
                    self.assertEqual(len(win.state._undo), undos)
                    self.assertTrue(win.statusBar().currentMessage().startswith("Could not restore view:"))
                finally:
                    win.close()
                    win.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_finite_saved_camera_rejects_unrenderable_matrices_before_mutation(self):
        for target, distance in (([1e100] * 3, 3), ([0, 0.9, 0], 1e308), ([0, 0.9, 0], 1e-308)):
            with self.subTest(target=target, distance=distance):
                prefs = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
                self.assertTrue(Path(prefs.fileName()).resolve().is_relative_to(Path(FIXTURES.name).resolve()))
                prefs.clear()
                win = MainWindow(self.dataset, restore=False)
                try:
                    win.state.set_hidden([1], True)
                    before, damaged = win.capture_view(), win.capture_view()
                    undos = len(win.state._undo)
                    damaged["hidden"] = []
                    damaged["camera"] = [target, distance, 0, 0]
                    win.apply_view(damaged, animate=False)
                    with np.errstate(all="ignore"):
                        view = win.viewport.camera.view()
                        projection = win.viewport.camera.proj(1.5)
                    print("saved camera matrices:", "finite", bool(np.isfinite(view).all() and np.isfinite(projection).all()),
                          "basis determinant", float(np.linalg.det(view[:3, :3])))
                    self.assertEqual(win.capture_view(), before)
                    self.assertEqual(len(win.state._undo), undos)
                    self.assertTrue(np.isfinite(view).all() and np.isfinite(projection).all())
                    self.assertAlmostEqual(abs(float(np.linalg.det(view[:3, :3]))), 1, places=5)
                finally:
                    win.close()
                    win.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_immediate_search_arrow_uses_latest_query_and_enter_keeps_chosen_result(self):
        from PySide6.QtTest import QTest
        from app.ui.search_panel import ROLE_ENTRY

        for old_query in ("", "lung"):
            with self.subTest(old_query=old_query):
                prefs = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
                self.assertTrue(Path(prefs.fileName()).resolve().is_relative_to(Path(FIXTURES.name).resolve()))
                prefs.clear()
                win = MainWindow(self.dataset, restore=False)
                try:
                    panel = win.search
                    panel.edit.setText(old_query)
                    panel._run()
                    expected = win.index.search("anterior")
                    self.assertGreater(len(expected), 2)
                    activated = []
                    panel.activated.connect(activated.append)
                    panel.edit.setText("anterior")
                    self.assertTrue(panel._timer.isActive())
                    QTest.keyClick(panel.edit, Qt.Key_Down)
                    self.assertEqual(panel.list.currentRow(), 1)
                    self.assertEqual(panel.list.currentItem().data(ROLE_ENTRY), expected[1])
                    QTest.keyClick(panel.edit, Qt.Key_Return)
                    self.assertEqual(activated, [expected[1]])
                finally:
                    win.close()
                    win.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_repeated_ephemeral_dialogs_release_qobjects_after_close(self):
        from PySide6.QtWidgets import QDialog

        for mode in ("views", "note", "all_notes", "progress", "quiz_progress"):
            with self.subTest(mode=mode):
                prefs = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
                self.assertTrue(Path(prefs.fileName()).resolve().is_relative_to(Path(FIXTURES.name).resolve()))
                prefs.clear()
                win = MainWindow(self.dataset, restore=False)
                original = win.findChildren(QDialog)
                seen = []

                def cancel():
                    dialog = QAPP.activeModalWidget()
                    seen.append(isinstance(dialog, QDialog))
                    if isinstance(dialog, QDialog):
                        dialog.reject()

                show = {"views": win.manage_views, "note": lambda: win.edit_note("Femur"),
                        "all_notes": win.show_all_notes, "progress": win.show_progress,
                        "quiz_progress": win.quiz.show_progress}[mode]
                try:
                    for index in range(3):
                        QTimer.singleShot(0, cancel)
                        show()
                        QAPP.processEvents()
                        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                        self.assertTrue(seen[-1], "cancel the actual modal dialog")
                        self.assertEqual(win.findChildren(QDialog), original,
                                         f"closed {mode} dialog {index + 1} must release its Qt object")
                finally:
                    win.close()
                    win.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_saved_view_rename_collision_preserves_both_views_and_delete_removes_only_selection(self):
        from PySide6.QtWidgets import QDialog, QListWidget, QPushButton

        for new_name in ("B", "C"):
            with self.subTest(new_name=new_name):
                prefs = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
                self.assertTrue(Path(prefs.fileName()).resolve().is_relative_to(Path(FIXTURES.name).resolve()))
                prefs.clear()
                win = MainWindow(self.dataset, restore=False)
                first, second = win.capture_view(), win.capture_view()
                first["selected"], second["selected"] = [0], [1]
                original = [{"name": "A", "created": "fixture-first", "data": first},
                            {"name": "B", "created": "fixture-second", "data": second}]
                win._store_views(original)
                observed, errors, warnings = [], [], []

                def interact():
                    dialog = next(d for d in win.findChildren(QDialog) if d.windowTitle() == "Saved views")
                    try:
                        listing = dialog.findChild(QListWidget)
                        listing.setCurrentRow(0)
                        buttons = {b.text(): b for b in dialog.findChildren(QPushButton)}
                        buttons["Rename"].click()
                        observed.append(win._saved_views())
                        target = "A" if new_name == "B" else "C"
                        listing.setCurrentRow(next((i for i in range(listing.count())
                                                    if listing.item(i).text() == target), 0))
                        buttons["Delete"].click()
                        observed.append(win._saved_views())
                    except Exception as exc:
                        errors.append(exc)
                    finally:
                        dialog.accept()

                try:
                    with patch("app.main_window.QInputDialog.getText", return_value=(new_name, True)), \
                            patch("app.main_window.QMessageBox.warning", side_effect=lambda *args: warnings.append(args)):
                        QTimer.singleShot(0, interact)
                        win.manage_views()
                    self.assertFalse(errors, errors)
                    expected = original if new_name == "B" else [dict(original[0], name="C"), original[1]]
                    self.assertEqual(observed[0], expected)
                    self.assertEqual(observed[1], [original[1]])
                    self.assertEqual(len(warnings), 1 if new_name == "B" else 0)
                finally:
                    win.close()
                    win.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_damaged_window_layout_types_do_not_prevent_startup_or_rewrite_on_read(self):
        for field in ("geometry", "window_state"):
            for value in ("damaged", 42, [1, 2, 3]):
                with self.subTest(field=field, value=value):
                    prefs = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
                    self.assertEqual(prefs.format(), QSettings.IniFormat)
                    self.assertTrue(Path(prefs.fileName()).resolve().is_relative_to(Path(FIXTURES.name).resolve()),
                                    "only the owned temporary INI may be cleared")
                    prefs.clear()
                    prefs.setValue(field, value)
                    win = None
                    try:
                        win = MainWindow(self.dataset, restore=True)
                        self.assertEqual(prefs.value(field), value)
                        self.assertGreater(win.width(), 100)
                        self.assertGreater(win.height(), 100)
                        self.assertIsNotNone(win._default_window_state)
                    finally:
                        if win is not None:
                            win.close()
                            win.deleteLater()
                        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_partial_quiz_history_does_not_break_weighted_questions(self):
        base = self.dataset.structures[0]["base"]
        for partial in ({}, {"seen": 7}, {"miss": 2}):
            with self.subTest(partial=partial), tempfile.TemporaryDirectory() as folder:
                path = fixture_root(folder) / "quiz_stats.json"
                original = json.dumps({base: partial})
                path.write_text(original, encoding="utf-8")
                QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
                with patch("app.ui.quiz.STATS_PATH", path):
                    win = MainWindow(self.dataset, restore=False)
                    try:
                        win.quiz.open()
                        win.quiz.panel.weak.setChecked(True)
                        self.assertGreater(win.quiz._weight(base), 0)
                        self.assertEqual(win.quiz.stats[base]["miss"], partial.get("miss", 0))
                        self.assertGreaterEqual(win.quiz.stats[base]["seen"], win.quiz.stats[base]["miss"])
                        from app import srs
                        self.assertGreaterEqual(srs.summary(win.quiz.stats)["accuracy"], 0)
                        self.assertEqual(path.read_text(encoding="utf-8"), original,
                                         "reading recoverable history must not overwrite the original")
                    finally:
                        win.quiz.stop()
                        win.close()
                        win.deleteLater()
                        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_partial_history_allows_quiz_and_practice_answers_and_backs_up_original(self):
        from app.lessons import Lesson, item_key
        from app.ui.practice import PracticeController

        for kind in ("quiz", "practice"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                item = {"type": "recall", "q": "Fixture question", "a": "Fixture answer",
                        "_lesson": "fixture-partial-history"}
                key = self.dataset.structures[0]["base"] if kind == "quiz" else item_key(item)
                path = fixture_root(folder) / "quiz_stats.json"
                original = json.dumps({key: {"seen": 7}})
                path.write_text(original, encoding="utf-8")
                QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
                with patch("app.ui.quiz.STATS_PATH", path):
                    win = MainWindow(self.dataset, restore=False)
                    session = win.quiz
                    try:
                        if kind == "quiz":
                            session.open()
                            session.panel.small.setChecked(True)
                            session.start(bases=[key])
                            self.assertEqual(session.current["base"], key)
                        else:
                            session = PracticeController(win, win.lessons_panel)
                            win.lessons_panel.practice = session
                            lesson = Lesson({"id": item["_lesson"], "title": "Fixture", "steps": [], "practice": []})
                            session.start(lesson, items=[item])
                        session._record(False)
                        stored = json.loads(path.read_text(encoding="utf-8"))[key]
                        self.assertEqual((stored["seen"], stored["miss"]), (8, 1))
                        backups = list(fixture_root(folder).glob("quiz_stats.json.recovery-*.bak"))
                        self.assertEqual(len(backups), 1)
                        self.assertEqual(backups[0].read_text(encoding="utf-8"), original)
                    finally:
                        session.stop()
                        win.close()
                        win.deleteLater()
                        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_finite_extreme_clip_coordinates_clamp_before_slider_conversion(self):
        QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
        win = MainWindow(self.dataset, restore=False)
        try:
            values = [1e308, -1e308, 1e308]
            win.view_panel.set_clips([True, False, False], values, [False, False, False])
            for index, (cb, slider, flip, low, high) in enumerate(win.view_panel.clip_widgets):
                self.assertEqual(slider.value(), 1000 if values[index] > 0 else 0)
                self.assertAlmostEqual(win.viewport.clip_pos[index], high if values[index] > 0 else low)
            self.assertEqual(win.viewport.clip_on, [True, False, False])
        finally:
            win.close()
            win.deleteLater()

    def test_malformed_clip_values_reject_saved_view_before_scene_mutation(self):
        for field in ("positions", "enabled", "flipped"):
            with self.subTest(field=field):
                QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
                win = MainWindow(self.dataset, restore=False)
                try:
                    win.state.select([0])
                    win.state.set_hidden([3], True)
                    win.state.set_custom_color([0], (0.2, 0.3, 0.8))
                    before = win.capture_view()
                    undo_count = len(win.state._undo)
                    damaged = json.loads(json.dumps(before))
                    damaged["hidden"] = []
                    damaged["custom_colors"] = {}
                    if field == "positions":
                        damaged["clip"][1] = [[0, 0], [0, 0], [0, 0]]
                    elif field == "enabled":
                        damaged["clip"][0][0] = "false"
                    else:
                        damaged["clip"][2][0] = None
                    win.apply_view(damaged, animate=False)
                    self.assertEqual(win.capture_view(), before)
                    self.assertEqual(len(win.state._undo), undo_count)
                    self.assertTrue(win.statusBar().currentMessage().startswith("Could not restore view:"))
                finally:
                    win.close()
                    win.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_status_follows_active_model_selection_visibility_and_xray(self):
        from general_fixtures import write_fixture_model
        with tempfile.TemporaryDirectory() as folder:
            QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
            win = MainWindow(self.dataset, restore=False)
            try:
                win.state.select([0, 1, 2])
                glb = fixture_root(folder) / "status_fixture.glb"
                write_fixture_model(glb)
                win.open_model_file(str(glb))
                model = win.active_model_view()
                self.assertIsNotNone(model)
                self.assertTrue(win.count_label.text().startswith("2 parts"))
                self.assertEqual(win.sel_label.text(), "")
                model.state.select([0])
                self.assertEqual(win.sel_label.text(), "1 selected")
                model.state.set_hidden([1], True)
                self.assertEqual(win.count_label.text(), "1 part · 12 triangles visible")
                model.state.set_ghost_focus([0])
                self.assertTrue(win.xray_action.isChecked())
                win.state.set_hidden([3], True)
                self.assertEqual(win.count_label.text(), "1 part · 12 triangles visible")
                self.assertTrue(win.xray_action.isChecked(), "hidden atlas updates cannot replace active model status")
                win.center.setCurrentIndex(0)
                self.assertIn("structures", win.count_label.text())
                self.assertEqual(win.sel_label.text(), "3 selected")
                self.assertFalse(win.xray_action.isChecked())
                tissue = next(t for t in win.content.tissues.values() if t.get("images"))
                win.open_histology(tissue["id"])
                self.assertEqual(win.count_label.text(), "")
                self.assertEqual(win.sel_label.text(), "")
                self.assertFalse(win.xray_action.isChecked())
            finally:
                win.close()
                win.deleteLater()

    def test_failed_note_save_keeps_editor_draft_for_retry_or_cancel(self):
        from app.ui.notes import NoteDialog
        for finish in ("retry", "cancel"):
            with self.subTest(finish=finish), tempfile.TemporaryDirectory() as folder:
                QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
                win = MainWindow(self.dataset, restore=False)
                path = fixture_root(folder) / "notes.json"
                original = '{"Femur": "Previous note"}'
                path.write_text(original, encoding="utf-8")
                win.content.notes_path = path
                win.content.notes = {"Femur": "Previous note"}
                win.content._notes_backup = False
                original_save = win.content.set_note
                attempts, observed = [], []

                def save_note(key, text):
                    attempts.append(text)
                    if len(attempts) == 1:
                        raise OSError("fixture disk full")
                    original_save(key, text)

                def make_dialog(*args, **kwargs):
                    dialog = NoteDialog(*args, **kwargs)

                    def inspect_and_finish():
                        observed.append((dialog.isVisible(), dialog.text(),
                                         any("Could not save note" in label.text()
                                             for label in dialog.findChildren(QLabel))))
                        if dialog.isVisible() and finish == "retry":
                            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Save).click()
                        else:
                            dialog.reject()

                    def first_save():
                        dialog.edit.setPlainText("Pending draft")
                        QTimer.singleShot(0, inspect_and_finish)
                        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Save).click()

                    QTimer.singleShot(0, first_save)
                    return dialog

                try:
                    with patch.object(win.content, "set_note", side_effect=save_note), \
                            patch("app.ui.notes.NoteDialog", side_effect=make_dialog):
                        win.edit_note("Femur")
                        QAPP.processEvents()
                    self.assertEqual(observed, [(True, "Pending draft", True)])
                    if finish == "retry":
                        self.assertEqual(attempts, ["Pending draft", "Pending draft"])
                        self.assertEqual(win.content.notes["Femur"], "Pending draft")
                        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["Femur"], "Pending draft")
                    else:
                        self.assertEqual(path.read_text(encoding="utf-8"), original)
                        self.assertEqual(win.content.notes["Femur"], "Previous note")
                finally:
                    win.close()
                    win.deleteLater()

    def test_failed_lesson_progress_save_reports_failure_and_preserves_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
            win = MainWindow(self.dataset, restore=False)
            progress = win.lessons_panel.progress
            progress.path = fixture_root(folder) / "lesson_progress.json"
            original = '{"fixture": {"seen": [0], "last": 0}}'
            progress.path.write_text(original, encoding="utf-8")
            progress.data = json.loads(original)
            progress._backup = False
            try:
                with patch("app.lessons.write_json", side_effect=OSError("fixture disk full")):
                    progress.visit("fixture", 1, 3)
                self.assertTrue(win.statusBar().currentMessage().startswith("Could not save lesson progress:"))
                self.assertEqual(progress.path.read_text(encoding="utf-8"), original)
                self.assertEqual(progress.seen("fixture"), {0, 1})
                self.assertTrue(progress.save())
                self.assertFalse(win.statusBar().currentMessage().startswith("Could not save lesson progress:"))
                self.assertEqual(json.loads(progress.path.read_text(encoding="utf-8"))["fixture"]["seen"], [0, 1])
            finally:
                win.close()
                win.deleteLater()

    def test_saved_view_rejects_nonpositive_camera_distance_atomically(self):
        QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
        win = MainWindow(self.dataset, restore=False)
        try:
            previous = win.capture_view()
            count = len(win.state._undo)
            for distance in (0.0, -1.0):
                with self.subTest(distance=distance):
                    damaged = json.loads(json.dumps(previous))
                    damaged["camera"][1] = distance
                    win.apply_view(damaged)
                    self.assertEqual(win.capture_view(), previous)
                    self.assertEqual(len(win.state._undo), count)
                    self.assertIsNone(win.viewport.camera._anim)
                    self.assertIn("Could not restore view", win.statusBar().currentMessage())
        finally:
            win.viewport.camera._anim = None
            win.close()
            win.deleteLater()

    def test_saved_view_restores_opacity_in_state_and_system_controls(self):
        QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
        win = MainWindow(self.dataset, restore=False)
        try:
            win.systems.sliders[0].setValue(25)
            saved = win.capture_view()
            win.systems.sliders[0].setValue(100)
            win.apply_view(saved, animate=False)
            self.assertAlmostEqual(float(win.state.system_alpha[0]), 0.25)
            self.assertEqual(win.systems.sliders[0].value(), 25)
            self.assertTrue(np.allclose(win.state.build_texture()[1, :self.dataset.n, 0][self.dataset.system_of == 0], 0.25))
        finally:
            win.close()
            win.deleteLater()

    def test_immediate_saved_view_cancels_previous_camera_transition(self):
        QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
        win = MainWindow(self.dataset, restore=False)
        try:
            saved = win.capture_view()
            camera = win.viewport.camera
            camera.animate_to([0.2, 0.5, 0.1], 0.5, 1.0, 0.2, 0.01)
            win.apply_view(saved, animate=False)
            self.assertIsNone(camera._anim)
            camera.update()
            self.assertEqual(win.capture_view()["camera"], saved["camera"])
        finally:
            win.viewport.camera._anim = None
            win.close()
            win.deleteLater()

    def test_repeated_saved_view_restore_does_not_move_cutting_planes(self):
        QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
        win = MainWindow(self.dataset, restore=False)
        try:
            mid = ((self.dataset.scene_bbox[0] + self.dataset.scene_bbox[1]) / 2).tolist()
            win.view_panel.set_clips([False, True, False], mid, [False, False, False])
            initial = np.array(win.viewport.clip_pos)
            saved = win.capture_view()
            for _ in range(5):
                win.apply_view(saved, animate=False)
                saved = win.capture_view()
            self.assertTrue(np.array_equal(win.viewport.clip_pos, initial),
                            f"restoring saved sections moved them from {initial} to {win.viewport.clip_pos}")
        finally:
            win.close()
            win.deleteLater()

    def test_returning_from_histology_to_empty_atlas_restores_welcome_details(self):
        QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
        win = MainWindow(self.dataset, restore=False)
        try:
            tissue = next(t for t in win.content.tissues.values() if t.get("images"))
            win.state.clear_selection()
            win.open_histology(tissue["id"])
            self.assertEqual(win.center.currentWidget(), win.micro_tabs["__histology__"])
            self.assertNotEqual(win.info._view, (win.info.show_welcome, ()))
            win.center.setCurrentIndex(0)
            self.assertEqual(win.info._view, (win.info.show_welcome, ()))
            self.assertEqual(win.state.selected, [])
        finally:
            win.close()
            win.deleteLater()

    def test_nonphysical_numeric_preferences_fall_back_without_rewriting_storage(self):
        from app.main_window import _validated_settings
        invalid = {"fov": 0, "render_scale": 0, "ui_scale": -1, "details_scale": 0,
                   "max_landmarks": -100, "orbit_sensitivity": -1, "zoom_sensitivity": 0,
                   "ghost_alpha": -0.2}
        self.assertEqual(_validated_settings(invalid), {})
        prefs = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
        prefs.clear()
        raw = json.dumps(invalid)
        prefs.setValue("view_settings", raw)
        win = MainWindow(self.dataset, restore=False)
        try:
            self.assertEqual(win.settings, config.DEFAULT_SETTINGS)
            self.assertTrue(np.isfinite(win.viewport.camera.proj(1.0)).all())
            self.assertEqual(prefs.value("view_settings"), raw)
        finally:
            win.close()
            win.deleteLater()

    def test_damaged_saved_view_leaves_scene_camera_and_undo_unchanged(self):
        QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
        win = MainWindow(self.dataset, restore=False)
        try:
            win.state.set_hidden([0], True)
            before = win.capture_view()
            undo_count = len(win.state._undo)
            damaged = ({"camera": [[0, 0], 3, 0, 0]},
                       {"camera": [[0, 0, 0], float("nan"), 0, 0]},
                       {"camera": [None, 3, 0, 0]}, {"camera": []},
                       {"clip": [[True], [0], [False]]}, {"dissection": [None, 0]},
                       {"selected": ["broken"]}, {"hidden": None},
                       {"custom_colors": {"0": [1, 0]}}, {"system_on": None})
            for changes in damaged:
                with self.subTest(changes=changes):
                    view = dict(before)
                    view["hidden"] = [1]
                    view.update(changes)
                    win.apply_view(view, animate=False)
                    self.assertEqual(win.capture_view(), before)
                    self.assertEqual(len(win.state._undo), undo_count)
        finally:
            win.close()
            win.deleteLater()

    def test_no_restore_ignores_layout_scene_borderless_and_preserves_preferences(self):
        settings = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
        settings.clear()
        retained = {
            "saved_views": '[{"name":"Exam view","data":{}}]',
            "keybindings": '{"frame":["G",""]}',
            "view_settings": '{"ui_scale":1.05,"color_mode":1}',
        }
        for key, value in retained.items():
            settings.setValue(key, value)
        settings.setValue("geometry", QByteArray(b"fixture-geometry"))
        settings.setValue("window_state", QByteArray(b"fixture-state"))
        settings.setValue("last_session", '{"selected":[0]}')
        settings.setValue("borderless", "1")
        settings.sync()
        with patch.object(MainWindow, "restoreGeometry", return_value=True) as geometry, \
                patch.object(MainWindow, "restoreState", return_value=True) as layout:
            win = MainWindow(self.dataset, restore=False)
        try:
            geometry.assert_not_called()
            layout.assert_not_called()
            self.assertFalse(win._restore_pending)
            self.assertFalse(win._borderless)
            self.assertEqual(win.cmds.shortcuts("frame"), ("G", ""))
            self.assertEqual(win.settings["ui_scale"], 1.05)
            self.assertEqual(win.settings["color_mode"], 1)
            self.assertEqual(win._saved_views()[0]["name"], "Exam view")
            for key, value in retained.items():
                self.assertEqual(settings.value(key), value)
        finally:
            win.close()
            win.deleteLater()

    def test_closing_during_practice_restores_temporary_settings_and_scene(self):
        from app.lessons import Lesson
        from app.ui.practice import PracticeController

        settings = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
        settings.clear()
        win = MainWindow(self.dataset, restore=False)
        try:
            st = win.state
            st.set_depth(0.55)
            practice = PracticeController(win, win.lessons_panel)
            win.lessons_panel.practice = practice
            lesson = Lesson({"id": "fixture-practice", "title": "Fixture",
                             "steps": [], "practice": []})
            sid = next(i for i in range(self.dataset.n) if st.visible_mask()[i])
            practice.start(lesson, items=[{"type": "find", "structure": self.dataset.structures[sid]["base"],
                                           "_sids": [sid]}])
            self.assertTrue(practice.active)
            self.assertFalse(win.quiz.active)
            self.assertFalse(win.settings["show_landmarks"])
            self.assertFalse(win.settings["show_hover_tooltip"])
            win.close()
            self.assertFalse(practice.active)
            persisted = json.loads(settings.value("view_settings"))
            self.assertTrue(persisted["show_landmarks"])
            self.assertTrue(persisted["show_hover_tooltip"])
            self.assertEqual(json.loads(settings.value("last_session"))["dissection"], [0.55, 0.0])
        finally:
            practice.stop()
            win.close()
            win.deleteLater()

    def test_lesson_quiz_restores_scene_from_before_starting_quiz(self):
        from app.lessons import Lesson

        QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
        win = MainWindow(self.dataset, restore=False)
        try:
            st = win.state
            st.set_depth(0.55)
            st.isolate([0])
            previous = st._snapshot()
            names = [s["base"] for s in self.dataset.structures
                     if s["system"] == "skeletal" and "_" not in s["base"]][:12]
            lesson = Lesson({"id": "fixture-quiz", "title": "Fixture",
                             "steps": [{"focus": names}], "practice": []})
            win.quiz_lesson(lesson)
            self.assertTrue(win.quiz.active)
            win.quiz.stop()
            current = st._snapshot()
            for actual, expected in zip(current, previous):
                if isinstance(expected, np.ndarray):
                    np.testing.assert_array_equal(actual, expected)
                else:
                    self.assertEqual(actual, expected)
        finally:
            win.quiz.stop()
            win.close()
            win.deleteLater()

    def test_quiz_and_practice_stop_restore_dissection_controls(self):
        from app.lessons import Lesson
        from app.ui.practice import PracticeController

        for controller in ("quiz", "practice"):
            with self.subTest(controller=controller):
                QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
                win = MainWindow(self.dataset, restore=False)
                session = win.quiz
                try:
                    win.view_panel.set_depth(0.55, True)
                    if controller == "quiz":
                        win.quiz.open()
                        win.quiz.panel.mode.setCurrentIndex(1)  # Hunt temporarily resets dissection.
                        win.quiz.start()
                    else:
                        session = PracticeController(win, win.lessons_panel)
                        win.lessons_panel.practice = session
                        lesson = Lesson({"id": "fixture-controls", "title": "Fixture",
                                         "steps": [], "practice": []})
                        session.start(lesson, items=[{"type": "find", "structure": self.dataset.structures[0]["base"],
                                                       "_sids": [0]}])
                    self.assertEqual(win.view_panel.depth_slider.value(), 0)
                    session.stop()
                    self.assertEqual((win.state.depth_cut, win.state.depth_band), (0.55, 0.13))
                    self.assertEqual(win.view_panel.depth_slider.value(), 550)
                    self.assertTrue(win.view_panel.depth_band.isChecked())
                finally:
                    session.stop()
                    win.close()
                    win.deleteLater()

    def test_quiz_progress_includes_lessons_and_has_main_window_parent(self):
        from app.ui.progress import LessonBars, ProgressDialog

        QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
        win = MainWindow(self.dataset, restore=False)
        dialogs = []

        def inspect_dialog(dialog):
            dialogs.append(dialog)
            self.assertIs(dialog.parent(), win)
            self.assertTrue(dialog.findChildren(LessonBars))
            return 0

        try:
            with patch.object(ProgressDialog, "exec", inspect_dialog):
                win.quiz.show_progress()
            self.assertEqual(len(dialogs), 1)
        finally:
            for dialog in dialogs:
                dialog.close()
                dialog.deleteLater()
            win.close()
            win.deleteLater()

    def test_saved_view_ignores_colors_for_structures_outside_current_dataset(self):
        QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
        win = MainWindow(self.dataset, restore=False)
        try:
            saved = win.capture_view()
            saved["custom_colors"] = {str(self.dataset.n + 1): [1, 0, 0], "0": [0.1, 0.2, 0.3]}
            win.apply_view(saved, animate=False)
            texture = win.state.build_texture()
            self.assertEqual(texture.shape, (2, 4096, 4))
            self.assertEqual(win.state.custom_colors, {0: (0.1, 0.2, 0.3)})
        finally:
            win.close()
            win.deleteLater()

    def test_saved_view_with_empty_selection_clears_previous_details(self):
        QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME).clear()
        win = MainWindow(self.dataset, restore=False)
        try:
            empty_view = win.capture_view()
            win.state.select([0])
            win.info.show_structures([0])
            win.apply_view(empty_view, animate=False)
            self.assertEqual(win.state.selected, [])
            self.assertEqual(win.info._view, (win.info.show_welcome, ()))
        finally:
            win.close()
            win.deleteLater()

    def test_damaged_preference_shapes_and_values_fall_back_without_startup_error(self):
        bad_settings = ([], None, 1, {"ui_scale": "invalid"}, {"ui_scale": None},
                        {"color_mode": 20}, {"details_scale": None}, {"max_landmarks": "many"},
                        {"show_landmarks": "false"}, {"ui_scale": float("nan")})
        for damaged in bad_settings:
            with self.subTest(saved=damaged):
                prefs = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
                prefs.clear()
                raw = json.dumps(damaged)
                prefs.setValue("view_settings", raw)
                win = None
                try:
                    win = MainWindow(self.dataset, restore=False)
                    self.assertEqual(win.settings, config.DEFAULT_SETTINGS)
                    self.assertEqual(prefs.value("view_settings"), raw)
                finally:
                    if win is not None:
                        win.close()
                        win.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_damaged_saved_view_shapes_do_not_crash_or_change_current_scene(self):
        prefs = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
        prefs.clear()
        win = MainWindow(self.dataset, restore=False)
        try:
            previous = win.capture_view()
            for damaged in (None, [], True, 1, "damaged"):
                with self.subTest(view=damaged):
                    win.apply_view(damaged, animate=False)
                    self.assertEqual(win.capture_view(), previous)
            for damaged in ({"name": "invalid top level"}, [None, "broken", {"name": "Missing data"}],
                            [{"name": "Keep", "data": previous}, {"name": 3, "data": previous}]):
                with self.subTest(saved_views=damaged):
                    raw = json.dumps(damaged)
                    prefs.setValue("saved_views", raw)
                    views = win._saved_views()
                    self.assertIsInstance(views, list)
                    self.assertTrue(all(isinstance(v, dict) and isinstance(v.get("name"), str)
                                        and isinstance(v.get("data"), dict) for v in views))
                    self.assertEqual(prefs.value("saved_views"), raw)
                    win._fill_views_menu()
        finally:
            win.close()
            win.deleteLater()

    def test_damaged_keybindings_do_not_block_startup_or_erase_valid_overrides(self):
        damaged_overrides = (None, [], 3, {"frame": "G"}, {"frame": ["G"]},
                             {"frame": ["G", None]}, {"frame": ["G", ""], "search": [None, ""]})
        for index, damaged in enumerate(damaged_overrides):
            with self.subTest(case=index):
                prefs = QSettings(QSettings.defaultFormat(), QSettings.UserScope, config.ORG_NAME, config.APP_NAME)
                prefs.clear()
                raw = json.dumps(damaged)
                prefs.setValue("keybindings", raw)
                win = None
                try:
                    win = MainWindow(self.dataset, restore=False)
                    default = win.cmds.defs["frame"][3:5]
                    self.assertEqual(win.cmds.shortcuts("frame"), ("G", "") if index == 6 else default)
                    self.assertEqual(prefs.value("keybindings"), raw)
                finally:
                    if win is not None:
                        win.close()
                        win.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
