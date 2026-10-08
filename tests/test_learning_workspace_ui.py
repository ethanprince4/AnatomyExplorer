"""Model-free Qt regression tests. All user files/preferences are temporary.

Overlay invocation: ANATOMY_UI_BASE=<read-only app> python -B this_file.py
An integrated checkout needs no environment variable. No MainWindow, datasets,
model builders, assets, or OpenGL widgets are imported or created.
"""
import atexit
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parents[1]
BASE = Path(os.environ.get("ANATOMY_UI_BASE", HERE))
sys.path.insert(0, str(BASE))
import app
from app import config
import app.ui
if BASE != HERE:
    app.ui.__path__.insert(0, str(HERE / "app/ui"))
    theme_overlay = HERE.parent / "lead/app/ui"
    if theme_overlay.is_dir():
        app.ui.__path__.append(str(theme_overlay))
        # Select the lead's tokens without preferring its other UI modules.
        import importlib.util
        spec = importlib.util.spec_from_file_location("app.ui.theme", theme_overlay / "theme.py")
        theme_module = importlib.util.module_from_spec(spec)
        sys.modules["app.ui.theme"] = theme_module
        spec.loader.exec_module(theme_module)

FIXTURE = tempfile.TemporaryDirectory(prefix="anatomy-learning-ui-")
atexit.register(FIXTURE.cleanup)
config.USER_DIR = Path(FIXTURE.name) / "user"
config.USER_DIR.mkdir()
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, Qt
from PySide6.QtGui import QFont, QFontMetricsF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, FIXTURE.name)
QAPP = QApplication.instance() or QApplication([])
from app.ui import theme
theme.apply_theme(QAPP)
from app.lessons import Lesson, LessonProgress, load_lessons
from app.ui.card_list import CardList, _wrap
from app.ui.lessons import LessonsPanel, PAGE_COVER, PAGE_LIBRARY, PAGE_RUNNER, StepBar
from app.ui.notes import AllNotesDialog, NoteDialog
from app.ui.practice import PracticeController, PracticePanel
from app.ui.quiz import QuizPanel, QuizController
from app.ui.progress import ProgressDialog
from app.ui.diagram import DiagramView, render_image, DIAGRAM_BACKGROUND
from app.ui.flow import FlowLayout, WrapButton, WrapCheckBox


def fixture_lessons():
    return [Lesson({"id": "nerve", "title": "Nerve lesson", "summary": "Existing nerve teaching",
                    "system": "nervous", "steps": [{"title": "Nerve step", "micro": "nerve",
                    "text": "<p>Authored teaching.</p>", "check": {"q": "Authored question?", "a": "Authored answer."}}],
                    "see_also": {"micro": ["nerve", "missing"], "histology": ["nerve_slide"],
                                 "radiology": ["missing_case"]}}),
            Lesson({"id": "skin", "title": "Skin lesson", "system": "integumentary",
                    "steps": [{"title": "Skin step", "micro": "skin", "text": "<p>Skin text.</p>"}]}),
            Lesson({"id": "exam", "title": "Practice only", "steps": [],
                    "see_also": {"lessons": ["skin"], "micro": ["skin"]},
                    "practice": [{"type": "recall", "q": "A question?", "a": "An answer."}]})]


class Callbacks:
    def __init__(self):
        self.win = SimpleNamespace(qsettings=QSettings(str(Path(FIXTURE.name) / "quiz.ini"), QSettings.IniFormat))
        self.ds = SimpleNamespace(systems=[{"key": "nervous", "name": "Nervous"}])
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class LearningWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.widgets = []
    def keep(self, widget):
        self.widgets.append(widget)
        return widget
    def tearDown(self):
        for widget in self.widgets:
            widget.hide()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QAPP.processEvents()
    def panel(self):
        panel = self.keep(LessonsPanel(fixture_lessons()))
        panel.progress = LessonProgress(Path(FIXTURE.name) / f"progress-{id(panel)}.json",
                                        on_save_error=panel.saveFailed.emit, on_saved=panel.saveSucceeded.emit)
        panel.set_reference_titles(micro={"nerve": "Nerve", "skin": "Skin"}, histo={"nerve_slide": "Nerve slide"}, rad={})
        return panel

    def test_authored_model_links_filter_catalog_without_title_guessing(self):
        panel = self.panel()
        self.assertEqual([lesson.id for lesson in panel.lessons_for_model("skin")], ["skin", "exam"])
        self.assertEqual(panel.lessons_for_model("Nerve"), [])
        panel.show_model_lessons("skin")
        self.assertEqual(panel.stack.currentIndex(), PAGE_LIBRARY)
        ids = [panel.list.item(i).data(Qt.UserRole) for i in range(panel.list.count())]
        self.assertIn("skin", ids)
        self.assertNotIn("nerve", ids)
        panel.clear_model_filter()
        self.assertIsNone(panel._model_filter)

    def test_reference_links_require_installed_registry_even_for_practice_only(self):
        panel = self.panel()
        panel.open_cover("nerve")
        markup = panel.cover_body.toHtml()
        self.assertIn('href="micro:nerve"', markup)
        self.assertNotIn('href="micro:missing"', markup)
        self.assertNotIn('href="rad:missing_case"', markup)
        self.assertIn("not available in this library", panel.cover_body.toPlainText())
        panel.open_cover("exam")
        self.assertIn('href="lesson:skin"', panel.cover_body.toHtml())
        self.assertIn('href="micro:skin"', panel.cover_body.toHtml())

    def test_reading_recall_uses_one_scroll_and_resets_between_lessons(self):
        panel = self.panel()
        panel.open_lesson("nerve")
        self.assertEqual(panel.stack.currentIndex(), PAGE_RUNNER)
        self.assertIn("Authored question?", panel.body.toPlainText())
        self.assertNotIn("Authored answer.", panel.body.toPlainText())
        panel._reveal()
        self.assertIn("Authored answer.", panel.body.toPlainText())
        panel._reveal()
        self.assertNotIn("Authored answer.", panel.body.toPlainText())
        panel.open_lesson("skin")
        panel._reveal()
        self.assertFalse(panel.answer_shown)
        self.assertNotIn("Authored answer.", panel.body.toPlainText())
        panel._runner_back()
        self.assertEqual(panel.stack.currentIndex(), PAGE_COVER)

    def test_progress_save_failure_is_retained_and_retryable(self):
        panel = self.panel()
        with patch("app.lessons.write_json", side_effect=OSError("fixture disk full")):
            panel.open_lesson("nerve")
        self.assertFalse(panel.save_notice.isHidden())
        self.assertIn("fixture disk full", panel.save_status.text())
        self.assertEqual(panel.progress.seen("nerve"), {0})
        self.assertTrue(panel.progress.save())
        self.assertTrue(panel.save_notice.isHidden())

    def test_all_existing_lessons_open_without_models_or_missing_method_calls(self):
        lessons = load_lessons()
        self.assertGreater(len(lessons), 200)
        panel = self.keep(LessonsPanel(lessons))
        panel.progress = LessonProgress(Path(FIXTURE.name) / "all-content.json")
        # Nominal widget/content check only. stepRequested is not connected to a renderer.
        with patch.object(panel, "_micro_focus"):
            for lesson in lessons:
                panel.open_cover(lesson.id)
                self.assertEqual(panel.cover_title.text(), lesson.title)
                if len(lesson):
                    panel.open_lesson(lesson.id)
                    self.assertEqual(panel.steps_shown, len(lesson))
                    self.assertEqual(panel.lesson.id, lesson.id)
                    for index in range(len(lesson)):
                        panel.go(index, force=True)
                        self.assertEqual(panel.index, index)

    def test_empty_and_multiword_search_and_keyboard_open(self):
        panel = self.panel()
        panel.filter.setText("nerve teaching")
        panel._open_selected()
        self.assertEqual(panel.lesson.id, "nerve")
        panel.close_lesson()
        panel.filter.setText("unmatched")
        self.assertIn("No lessons match", panel.list.item(0).text())
        empty = self.keep(LessonsPanel([]))
        self.assertIn("No lesson content", empty.list.item(0).text())

    def test_native_step_bar_keyboard_and_many_steps_fit_width(self):
        bar = self.keep(StepBar())
        bar.resize(100, 28)
        bar.set_state(80, 4, {0, 1})
        self.assertLessEqual(max(rect.right() for rect in bar._rects()), bar.width() + 0.01)
        values = []
        bar.stepClicked.connect(values.append)
        QTest.keyClick(bar, Qt.Key_End)
        self.assertEqual(values[-1], 79)
        QTest.keyClick(bar, Qt.Key_Home)
        self.assertEqual(values[-1], 0)

    def test_long_choices_and_unbroken_catalog_words_wrap(self):
        button = self.keep(WrapButton("A long authored answer that must wrap across several lines without truncating " * 3))
        self.assertGreater(button.heightForWidth(240), button.heightForWidth(420))
        lines = _wrap("x" * 150, QFontMetricsF(QFont()), 80, 3)
        self.assertEqual(len(lines), 3)
        self.assertLessEqual(QFontMetricsF(QFont()).horizontalAdvance(lines[-1]), 81)
        catalog = self.keep(CardList())
        item = catalog.add_card("Long title", "Summary", badge="3 steps", done=True, data="x")
        self.assertIn("Finished", item.data(Qt.AccessibleTextRole))
        self.assertEqual(item.text(), "Long title")

    def test_note_search_covers_body_and_save_error_keeps_text(self):
        content = SimpleNamespace(notes={"Nerve": "Remember myelin", "Skin": "Layers"})
        dialog = self.keep(AllNotesDialog(content))
        dialog.search.setText("myelin")
        self.assertEqual(dialog.list.count(), 1)
        self.assertEqual(dialog.note_title.text(), "Nerve")
        dialog.search.setText("no match")
        self.assertFalse(dialog.open_button.isEnabled())
        def failing(_text):
            raise OSError("fixture read-only")
        note = self.keep(NoteDialog("<subject>", "Original", save=failing))
        note.edit.setPlainText("Unsaved changes")
        note.accept()
        self.assertIn("Unsaved changes", note.text())
        self.assertFalse(note.save_error.isHidden())

    def test_practice_validation_rejects_unusable_items_without_exception(self):
        controller = PracticeController(SimpleNamespace(ds=SimpleNamespace(), state=SimpleNamespace(),
                                       content=SimpleNamespace(micro_models={})), SimpleNamespace())
        pool = [None, {"type": "unknown"}, {"type": "mcq", "choices": ["a", "b"], "answer": "bad"},
                {"type": "order", "items": "not rows"}, {"type": "recall", "q": "Missing answer"},
                {"type": "recall", "q": "Valid question", "a": "Valid answer"}]
        self.assertEqual(controller._prepare(pool), [pool[-1]])
        controller._flash_timer.stop()

    def test_quiz_practice_and_progress_construct_at_narrow_width_without_gl(self):
        for kind in (PracticePanel, QuizPanel):
            panel = self.keep(kind(Callbacks()))
            panel.resize(320, 640)
            panel.show()
            QAPP.processEvents()
            self.assertEqual(panel.width(), 320)
            self.assertTrue(hasattr(panel, "question_scroll"))
            self.assertTrue(all(isinstance(button, WrapButton) for button in panel.choice_buttons))
            if isinstance(panel, QuizPanel):
                theme.apply_theme(QAPP, scale=1.5)
                QAPP.processEvents()
                scroll = panel.stack.widget(0)
                self.assertLessEqual(scroll.widget().width(), scroll.viewport().width())
                theme.apply_theme(QAPP)
        progress = self.keep(ProgressDialog({}, fixture_lessons(), self.panel().progress))
        progress.resize(420, 540)
        progress.show()
        QAPP.processEvents()
        self.assertEqual(progress.width(), 420)
        self.assertTrue(any(label.text() == "—" for label in progress.findChildren(QLabel)))

    def test_replace_library_discards_stale_route_and_model_filter(self):
        panel = self.panel()
        panel.show_model_lessons("nerve")
        panel.open_lesson("nerve")
        panel.set_lessons([fixture_lessons()[1]])
        self.assertIsNone(panel.lesson)
        self.assertIsNone(panel._model_filter)
        self.assertEqual(panel.stack.currentIndex(), PAGE_LIBRARY)
        self.assertEqual(set(panel.by_id), {"skin"})

    def test_checkbox_wrap_keeps_native_toggle_hit_area(self):
        checkbox = self.keep(WrapCheckBox("A long checkbox label that must be readable across a narrow study dock " * 2))
        self.assertGreater(checkbox.heightForWidth(220), checkbox.heightForWidth(420))
        checkbox.resize(220, checkbox.heightForWidth(220))
        self.assertTrue(checkbox.hitButton(checkbox.rect().bottomRight()))
        QTest.keyClick(checkbox, Qt.Key_Space)
        self.assertTrue(checkbox.isChecked())

    def test_quiz_due_button_excludes_non_atlas_practice_keys(self):
        quiz = QuizController(SimpleNamespace(ds=SimpleNamespace(structures=[{"base": "Nerve"}]), state=SimpleNamespace()))
        quiz.stats = {"Nerve": {"due": "2000-01-01", "seen": 2, "miss": 1},
                      "practice:recall": {"due": "2000-01-01", "seen": 3, "miss": 1}}
        self.assertEqual(quiz.due_count(), 1)
        quiz.current = {"done": False, "options": ["Nerve", "Skin"]}
        quiz.answer_choice(8)
        quiz.answer_choice(-1)
        self.assertFalse(quiz.current["done"])
        quiz._advance.stop()
        quiz._flash_timer.stop()

    def test_quiz_skip_records_one_miss_and_repeated_next_does_not_duplicate(self):
        quiz = QuizController(SimpleNamespace(ds=SimpleNamespace(structures=[{"base": "Nerve"}]), state=SimpleNamespace()))
        quiz.panel = self.keep(QuizPanel(Callbacks()))
        quiz.current = {"done": False, "base": "Nerve", "wrong": 0, "helped": False}
        quiz.stats = {}
        quiz.asked = 1
        quiz.correct = quiz.streak = quiz.best_streak = 0
        quiz.missed = []
        quiz.queue = []
        quiz.endless = False
        with patch.object(quiz, "finish") as finish:
            quiz.next_question()
            quiz.next_question()
        self.assertEqual(quiz.stats["Nerve"]["seen"], 1)
        self.assertEqual(quiz.stats["Nerve"]["miss"], 1)
        self.assertEqual(quiz.missed, ["Nerve"])
        self.assertTrue(finish.called)
        quiz._advance.stop()
        quiz._flash_timer.stop()

    def test_flow_respects_small_width_and_hidden_controls(self):
        host = self.keep(QWidget())
        layout = FlowLayout(host)
        long = WrapButton("A long control that wraps instead of forcing the window wider")
        layout.addWidget(long)
        hidden = WrapButton("Hidden control")
        layout.addWidget(hidden)
        hidden.hide()
        host.resize(160, 400)
        host.show()
        QAPP.processEvents()
        self.assertLessEqual(long.geometry().right(), host.width())
        self.assertGreater(long.height(), 40)

    def test_unavailable_diagram_is_explicit(self):
        view = self.keep(DiagramView())
        view.set_diagram("does-not-exist-fixture")
        self.assertFalse(view.isHidden())
        self.assertEqual(view.heightForWidth(300), 72)
        self.assertIsNone(render_image("does-not-exist-fixture", 300))


if __name__ == "__main__":
    unittest.main(verbosity=2)
