"""Lecture delivery checks without touching user progress or opening a GPU view."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtCore import QUrl
from app.lessons import LessonProgress, load_lessons, lecture_units, course_units, practice_pool
from app.ui.lessons import LessonsPanel, PAGE_RUNNER, PAGE_COVER
from app.ui.diagram import render_image

APP = QApplication.instance() or QApplication([])
if not QFontDatabase.families():
    # Windows' offscreen Qt platform does not discover system fonts itself.
    for filename in ('segoeui.ttf', 'segoeuib.ttf', 'arial.ttf'):
        font = Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts'/filename
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    APP.setFont(QFont('Segoe UI', 10))
ROOT = Path(__file__).resolve().parents[1]


class LectureExam2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lessons = [l for l in load_lessons() if l.lecture_key and l.lecture_key[0] == 2]

    def test_complete_chapter_groups_and_cross_chapter_practice(self):
        raw = [l for p in (ROOT/'data/content').glob('lessons_lecture_exam2*.json')
               for l in json.loads(p.read_text(encoding='utf-8'))]
        ids = [l['id'] for l in raw]
        self.assertEqual(len(ids), len(set(ids)))
        groups = {key: group for _, key, group in lecture_units(self.lessons)}
        self.assertEqual({key: len(group) for key, group in groups.items()},
                         {(2,20):17, (2,21):17, (2,22):20, (2,0):3})
        for chapter in (20,21,22):
            orders = [l.lecture['order'] for l in groups[(2,chapter)]]
            self.assertEqual(orders, list(range(1,len(orders)+1)))
        exam = next(l for l in self.lessons if l.id.endswith('03-practice-exam'))
        pool = practice_pool(exam, self.lessons)
        self.assertGreater(len(pool), 40)
        for chapter in (20,21,22):
            self.assertTrue(any(i['_lesson'].startswith(f'lec2-ch{chapter}-') for i in pool))

    def test_every_lecture_step_opens_with_reading_and_recall(self):
        with tempfile.TemporaryDirectory() as folder:
            progress = LessonProgress(Path(folder)/'progress.json')
            with patch('app.ui.lessons.LessonProgress', return_value=progress):
                panel = LessonsPanel(self.lessons)
            try:
                panel.show_lecture()
                self.assertEqual(panel.group_by, 'lecture')
                for lesson in self.lessons:
                    panel.open_cover(lesson.id)
                    if not len(lesson):
                        continue
                    panel.open_lesson(lesson.id)
                    self.assertEqual(panel.stack.currentIndex(), PAGE_RUNNER)
                    for index, step in enumerate(lesson.steps):
                        panel.go(index, force=True)
                        with self.subTest(lesson=lesson.id, step=index):
                            self.assertTrue(step['text'].strip())
                            self.assertTrue(panel.body.toPlainText().strip())
                            self.assertTrue(step['check']['q'])
                            self.assertTrue(step['check']['a'])
                            if step.get('diagram'):
                                self.assertIsNotNone(panel._diagram_shown)
            finally:
                panel.close()
                panel.deleteLater()

    def test_full_size_diagram_action_and_no_obsolete_panel_buttons(self):
        with tempfile.TemporaryDirectory() as folder:
            progress = LessonProgress(Path(folder)/'progress.json')
            with patch('app.ui.lessons.LessonProgress', return_value=progress):
                panel = LessonsPanel(self.lessons)
            try:
                lesson = next(l for l in self.lessons if any(s.get('diagram') and s.get('lesson_view') != 'diagram' for s in l.steps))
                panel.open_lesson(lesson.id)
                index = next(i for i,s in enumerate(lesson.steps) if s.get('diagram') and s.get('lesson_view') != 'diagram')
                panel.go(index, force=True)
                self.assertFalse(hasattr(panel, 'diagram_button'))
                diagram = lesson.steps[index]['diagram']
                self.assertIn('Open full-size diagram', panel.body.toPlainText())
                with patch('app.ui.diagram.show_large') as open_large:
                    panel._anchor(QUrl('diagram:' + diagram))
                    open_large.assert_called_once_with(diagram, panel)
                self.assertFalse(hasattr(panel, 'parts_btn'))
                self.assertFalse(hasattr(panel, 'details_btn'))
            finally:
                panel.close()
                panel.deleteLater()

    def test_finish_and_next_opens_following_overview_and_marks_done(self):
        lessons = load_lessons()
        labs = {key: group for _,key,group in course_units(lessons)}
        chapters = {key: group for _,key,group in lecture_units(lessons)}
        transitions = [(chapters[(2,20)][0], chapters[(2,20)][1]),
                       (chapters[(2,20)][-1], chapters[(2,21)][0]),
                       (labs[('lab',5)][-1], labs[('exam',1)][0])]
        with tempfile.TemporaryDirectory() as folder:
            progress = LessonProgress(Path(folder)/'progress.json')
            with patch('app.ui.lessons.LessonProgress', return_value=progress):
                panel = LessonsPanel(lessons)
            try:
                for current, following in transitions:
                    with self.subTest(lesson=current.id):
                        panel.open_lesson(current.id)
                        panel.go(len(current)-1, force=True)
                        self.assertEqual(panel.next_btn.text(), 'Finish + Next')
                        panel.next_btn.click()
                        self.assertTrue(progress.is_done(current.id))
                        self.assertEqual(panel.lesson.id, following.id)
                        self.assertEqual(panel.stack.currentIndex(), PAGE_COVER)
                        self.assertFalse(progress.is_done(following.id))
            finally:
                panel.close()
                panel.deleteLater()

    def test_recall_wraps_with_normal_line_spacing(self):
        from PySide6.QtGui import QTextDocument
        from app.ui.lessons import LESSON_CSS
        panel = LessonsPanel(self.lessons)
        try:
            lesson = next(l for l in self.lessons if len(l))
            panel.open_lesson(lesson.id)
            step = lesson.steps[0]
            panel._check = {'q': 'Where do pulmonary vessels start and where do they finish?', 'a': 'Two endpoints.'}
            doc = QTextDocument()
            doc.setDefaultFont(APP.font())
            doc.setDefaultStyleSheet(LESSON_CSS)
            doc.setTextWidth(220)
            doc.setHtml(panel._html(step, 0, len(lesson)))
            doc.size()  # Force layout before inspecting wrapped lines.
            block = doc.begin()
            while block.isValid():
                if block.text() == panel._check['q']:
                    layout = block.layout()
                    self.assertGreater(layout.lineCount(), 1)
                    first, second = layout.lineAt(0), layout.lineAt(1)
                    self.assertLessEqual(second.y() - first.y(), first.height() * 1.1)
                    break
                block = block.next()
            else:
                self.fail('Recall question was not rendered')
        finally:
            panel.close()
            panel.deleteLater()

    def test_all_lecture_diagrams_render_at_reading_width(self):
        diagrams = {s['diagram'] for l in self.lessons for s in l.steps if s.get('diagram')}
        for diagram in diagrams:
            with self.subTest(diagram=diagram):
                image = render_image(diagram, 400, max_height=460)
                self.assertIsNotNone(image)
                self.assertFalse(image.isNull())
                self.assertLessEqual(image.width(), 400)


if __name__ == '__main__':
    unittest.main()
