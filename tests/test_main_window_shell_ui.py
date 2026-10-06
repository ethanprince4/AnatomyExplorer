"""Integrated native construction/routing without geometry, rendering or real settings.

Set ANATOMY_UI_BASE to an installed source tree and ANATOMY_UI_OVERLAY to the
combined UI layer. The window is never shown; geometry and model requests are
explicitly blocked. This is not GPU or native desktop acceptance.
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('XDG_CACHE_HOME', '/tmp/anatomy-ui-qt-cache')
HERE = Path(__file__).resolve()
BASE = Path(os.environ.get('ANATOMY_UI_BASE', HERE.parents[3] / 'integration-azure-handoff/candidate/AnatomyExplorer'))
if not (BASE / 'app').exists():
    BASE = HERE.parents[1]
OVERLAY = Path(os.environ.get('ANATOMY_UI_OVERLAY', HERE.parents[1]))
sys.path.insert(0, str(BASE))
import app
app.__path__.insert(0, str(OVERLAY / 'app'))
import app.ui
app.ui.__path__.insert(0, str(OVERLAY / 'app/ui'))
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication
QAPP = QApplication.instance() or QApplication([])
USER = tempfile.TemporaryDirectory()
import app.config as config
config.USER_DIR = Path(USER.name) / 'user'
config.USER_DIR.mkdir()
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, USER.name)
from app.ui.theme import apply_theme
apply_theme(QAPP)
from app.data import Dataset
from app.main_window import MainWindow
from app.ui.model_loading import ModelLoader


class IntegratedShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Dataset reads metadata only; load_geometry is prohibited below.
        cls.ds = Dataset(config.DATA_DIR)

    def setUp(self):
        # These are navigation metadata fixtures, not a registered/ready output
        # generation. Never read real user variant data or expose legacy models.
        from app.viewer.catalog import ModelEntry
        from app.variants.anatomy_runtime_adapters import metadata_catalog
        from app.variants.catalog import ActiveCatalog
        catalog = ActiveCatalog()
        for metadata in metadata_catalog():
            entry = ModelEntry(metadata['id'], metadata['name'], metadata['summary'],
                               metadata.get('targets'), metadata.get('histology', ()),
                               scale_note=metadata.get('scale_note', ''))
            entry.kind = metadata['kind']
            catalog[entry.id] = entry
        self.catalog_source = patch('app.viewer.catalog.load_catalog', return_value=catalog)
        self.catalog_source.start()
        self.geometry = patch.object(Dataset, 'load_geometry', side_effect=AssertionError('Geometry is out of scope'))
        self.geometry.start()
        self.model = patch.object(ModelLoader, 'request', side_effect=RuntimeError('Fixture: model files unavailable'))
        self.model.start()
        self.errors = []
        self.hook = patch('sys.excepthook', lambda _kind, error, _tb: self.errors.append(str(error)))
        self.hook.start()
        self.window = MainWindow(self.ds, restore=False)

    def tearDown(self):
        self.window.settings['restore_session'] = False
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QAPP.processEvents()
        self.model.stop(); self.geometry.stop(); self.hook.stop()
        self.catalog_source.stop()
        self.assertFalse(self.errors, self.errors)

    def test_complete_metadata_routes_construct_without_geometry(self):
        win = self.window
        from app.radiology import load_cases
        self.assertEqual({case.id for case in win.radiology_cases},
                         {case.id for case in load_cases(include_missing=True)})
        from app.lessons import load_lessons
        self.assertEqual({lesson.id for lesson in win.lessons_panel.lessons}, {lesson.id for lesson in load_lessons()})
        self.assertEqual(len(win.content.micro_models), 39)
        self.assertNotIn('heart', win.content.micro_models)
        self.assertGreaterEqual(win.center.indexOf(win.collection_workspace), 0)
        self.assertEqual(win.tabs.indexOf(win.catalog), -1)
        self.assertFalse(win._startup_notices)

    def test_navigation_clears_active_search_and_compact_layout_returns(self):
        win = self.window
        win.search.edit.setText('heart')
        win._show_catalog()
        self.assertEqual(win.search.edit.text(), '')
        self.assertIs(win.center.currentWidget(), win.collection_workspace)
        win.show_histology_tab()
        self.assertIs(win.collection_workspace.pages.currentWidget(), win.histology_panel)
        win.show_lessons()
        self.assertIs(win.collection_workspace.pages.currentWidget(), win.lessons_panel)
        win.resize(1080, 760); win._adapt_workspace()
        self.assertTrue(win._compact_layout)
        win.resize(1580, 960); win._adapt_workspace()
        self.assertFalse(win._compact_layout)

    def test_failed_model_stays_recoverable_and_callbacks_do_not_hang(self):
        win = self.window
        model_id = next(iter(win.content.micro_models))
        calls = []
        win.open_micro(model_id, on_ready=calls.append)
        pending = win._loading_models[model_id]
        self.assertIsNone(pending.serial)
        self.assertEqual(calls, [None])
        self.assertFalse(pending.retry.isHidden())
        win.open_micro(model_id, on_ready=calls.append)
        win.when_model_ready(model_id, calls.append)
        self.assertEqual(calls, [None, None, None])
        pending.retry.click()
        self.assertIsNot(win._loading_models[model_id], pending)
        self.assertEqual(win.center.count(), 3)
        win._close_center_tab(win.center.indexOf(win._loading_models[model_id]))
        self.assertEqual(win._loading_models, {})

    def test_lesson_first_open_keeps_reader_beside_atlas_and_model(self):
        from app.lessons import Lesson
        from app.ui.lessons import PAGE_RUNNER
        win = self.window
        panel = win.lessons_panel
        model_id = next(iter(win.content.micro_models))
        lesson = Lesson({'id': 'split-regression', 'title': 'Split regression',
                         'steps': [{'title': 'Atlas', 'text': 'Read beside atlas'},
                                   {'title': 'Model', 'text': 'Read beside model', 'micro': model_id},
                                   {'title': 'Atlas again', 'text': 'Keep reading'}]})
        panel.by_id[lesson.id] = lesson
        win.studio_header.navigation['lessons'].click()
        self.assertIs(win.center.currentWidget(), win.collection_workspace)
        panel.open_lesson(lesson.id)
        self.assertEqual(panel.stack.currentIndex(), PAGE_RUNNER)
        self.assertIs(win.center.currentWidget(), win.anatomy_tab)
        self.assertFalse(win.lesson_reader.isHidden())
        self.assertFalse(panel.isHidden())
        self.assertIs(panel.parentWidget(), win.lesson_card)
        self.assertTrue(win.studio_header.navigation['lessons'].isChecked())
        panel.go(1)
        self.assertIs(win.center.currentWidget(), win._loading_models[model_id])
        self.assertFalse(win.lesson_reader.isHidden())
        panel.go(2)
        self.assertIs(win.center.currentWidget(), win.anatomy_tab)
        self.assertFalse(win.lesson_reader.isHidden())
        panel._runner_back()
        self.assertIs(win.center.currentWidget(), win.collection_workspace)
        self.assertIs(win.collection_workspace.pages.currentWidget(), panel)
        self.assertTrue(win.lesson_reader.isHidden())
        panel.open_lesson(lesson.id)
        panel.close_lesson()
        self.assertIs(win.collection_workspace.pages.currentWidget(), panel)
        self.assertTrue(win.lesson_reader.isHidden())

    def test_lesson_reader_returns_after_workspace_navigation(self):
        win = self.window
        panel = win.lessons_panel
        lesson = next(item for item in panel.lessons if len(item) and not item.steps[0].get('micro')
                      and not item.steps[0].get('histology'))
        win.show_lessons(lesson.id)
        win._show_catalog()
        self.assertTrue(win.lesson_reader.isHidden())
        win.studio_header.navigation['lessons'].click()
        self.assertFalse(win.lesson_reader.isHidden())
        self.assertIs(win.center.currentWidget(), win.anatomy_tab)
        self.assertIs(panel.parentWidget(), win.lesson_card)
        win._studio_explore()
        self.assertTrue(win.lesson_reader.isHidden())
        win.show_lessons()
        self.assertFalse(win.lesson_reader.isHidden())

    def test_lab_order_and_nested_lecture_expansion(self):
        from PySide6.QtCore import Qt
        from app.ui.card_list import ROLE_KIND, ROLE_LEVEL, ROLE_GROUP_KEY
        panel = self.window.lessons_panel
        panel.show_course()
        headers = [panel.list.item(i) for i in range(panel.list.count())
                   if panel.list.item(i).data(ROLE_KIND) == 'header']
        self.assertEqual([h.data(ROLE_GROUP_KEY) for h in headers],
                         [f'lab-lab-{i}' for i in range(1, 6)] + ['lab-exam-1'] +
                         [f'lab-lab-{i}' for i in range(6, 10)] + ['lab-exam-2'])
        self.assertTrue(all(panel.by_id[panel.list.item(i).data(Qt.UserRole)].unit_key
                            for i in range(panel.list.count()) if panel.list.item(i).data(Qt.UserRole)))
        panel.show_lecture()
        exam = panel.list.item(0)
        chapter = panel.list.item(1)
        lesson = panel.list.item(2)
        self.assertEqual(exam.data(ROLE_GROUP_KEY), 'lecture-exam-2')
        self.assertEqual(chapter.data(ROLE_LEVEL), 1)
        self.assertTrue(chapter.isHidden())
        self.assertTrue(lesson.isHidden())
        panel.list._toggle_group(exam)
        self.assertFalse(chapter.isHidden())
        self.assertTrue(lesson.isHidden())
        panel.list._toggle_group(chapter)
        self.assertFalse(lesson.isHidden())
        panel.list._toggle_group(exam)
        self.assertTrue(chapter.isHidden())
        self.assertTrue(lesson.isHidden())
        panel.list._toggle_group(exam)
        self.assertFalse(lesson.isHidden())
        # Progress updates must preserve expansion using stable keys.
        panel._fill()
        self.assertFalse(panel.list.item(2).isHidden())

    def test_continue_learning_is_outside_the_library_groups(self):
        from app.ui.card_list import ROLE_KIND, ROLE_TITLE
        panel = self.window.lessons_panel
        lesson = next(item for item in panel.lessons if len(item) > 1)
        panel.progress.visit(lesson.id, 1, len(lesson))
        panel._fill()
        self.assertFalse(panel.resume_button.isHidden())
        self.assertEqual(panel._resume_id, lesson.id)
        self.assertIn(lesson.title, panel.resume_button.toolTip())
        self.assertNotIn('Continue learning', [panel.list.item(i).data(ROLE_TITLE)
                         for i in range(panel.list.count()) if panel.list.item(i).data(ROLE_KIND) == 'header'])
        panel.resume_button.click()
        self.assertEqual(panel.lesson.id, lesson.id)
        self.assertEqual(panel.index, 1)

    def test_lesson_and_radiology_restore_without_double_panels(self):
        win = self.window
        panel = win.lessons_panel
        lesson = next(item for item in panel.lessons if len(item) and not item.steps[0].get('micro')
                      and not item.steps[0].get('histology'))
        win.show_lessons(lesson.id)
        case = win.radiology_cases[0]
        with patch.object(win, 'apply_radiology_scene'):
            win.open_radiology(case.id)
            self.assertTrue(win.lesson_reader.isHidden())
            self.assertFalse(win.radiology_panel.isHidden())
            with patch.object(win, 'apply_lesson_step', wraps=win.apply_lesson_step) as apply:
                win.studio_header.navigation['lessons'].click()
                apply.assert_called_once_with(lesson.steps[panel.index])
            self.assertTrue(win.radiology_panel.isHidden())
            self.assertFalse(win.lesson_reader.isHidden())
            win.studio_header.navigation['radiology'].click()
            self.assertTrue(win.lesson_reader.isHidden())
            self.assertFalse(win.radiology_panel.isHidden())
            self.assertEqual(win.radiology_panel.case.id, case.id)

    def test_chapters_21_22_and_review_have_a_relevant_nonempty_canvas(self):
        win = self.window
        panel = win.lessons_panel
        from app.ui.diagram import renderer
        lessons = [l for l in panel.lessons if l.id.startswith(
            ('lec2-ch21-', 'lec2-ch22-', 'lec2-review-'))]
        count = 0
        with patch.object(win, 'open_micro') as model, \
             patch.object(win, 'open_histology') as histology, \
             patch.object(win, 'when_model_ready'):
            for lesson in lessons:
                if not len(lesson):
                    continue
                win.show_lessons(lesson.id)
                panel.open_lesson(lesson.id)
                for index, step in enumerate(lesson.steps):
                    with self.subTest(lesson=lesson.id, step=index + 1):
                        model.reset_mock(); histology.reset_mock()
                        panel.go(index, force=True)
                        count += 1
                        if step.get('lesson_view') == 'diagram':
                            self.assertIs(win.center.currentWidget(), win._lesson_visual)
                            self.assertEqual(win._lesson_visual.diagram.diagram_id, step['diagram'])
                            self.assertIsNotNone(renderer(step['diagram']))
                        elif step.get('lesson_view') == 'reading':
                            self.assertIs(win.center.currentWidget(), win._lesson_visual)
                            self.assertIs(win._lesson_visual.pages.currentWidget(), win._lesson_visual.reading)
                            self.assertTrue(win._lesson_visual.reading.toPlainText().strip())
                        elif step.get('micro'):
                            model.assert_called_once_with(step['micro'])
                        elif step.get('histology'):
                            histology.assert_called_once_with(step['histology'], 0)
                        else:
                            self.assertIs(win.center.currentWidget(), win.anatomy_tab)
                            self.assertTrue(win.state.visible_mask().any())
                            self.assertTrue(win.state.selected)
        self.assertEqual(count, 221)

    def test_concept_diagrams_replace_models_and_restore_anatomy(self):
        win = self.window
        panel = win.lessons_panel
        lesson = panel.by_id['lec2-ch20-16-homeostasis-ions-temp']
        win.show_lessons(lesson.id)
        panel.open_lesson(lesson.id)
        visual = win._lesson_visual
        self.assertIs(win.center.currentWidget(), visual)
        self.assertEqual(visual.diagram.diagram_id, 'lec2-baroreceptor-reflex')
        self.assertNotIn('Open full-size diagram', panel.body.toPlainText())
        panel.go(2, force=True)
        self.assertIs(win.center.currentWidget(), win.anatomy_tab)
        self.assertNotIn('micro', lesson.steps[2])
        self.assertEqual(lesson.steps[2]['focus'], ['Medulla oblongata'])
        panel.go(4, force=True)
        self.assertIs(win.center.currentWidget(), visual)
        self.assertEqual(visual.diagram.diagram_id, 'lab04-action-potentials')
        with patch('app.ui.diagram.show_large') as enlarge:
            visual.enlarge.click()
            enlarge.assert_called_once_with('lab04-action-potentials', visual)
        panel.go(6, force=True)
        self.assertIs(visual.pages.currentWidget(), visual.reading)
        self.assertTrue(visual.enlarge.isHidden())
        with patch.object(win, 'open_micro') as open_model, patch.object(win, 'when_model_ready'):
            panel.open_lesson('lec2-ch20-03-external-coronary')
            open_model.assert_called_once_with('whole_heart')

    def test_studio_navigation_keeps_scene_and_routes_live_search(self):
        win=self.window
        self.assertTrue(win.menuBar().isHidden())
        self.assertTrue(win.center.tabBar().isHidden())
        for _ in range(2):
            win.studio_header._populate_commands()
            self.assertIn('Open workspaces',[a.text() for a in win.studio_header.commands_menu.actions()])
        camera=win.viewport.camera
        win.studio_header.navigation['3d models'].click()
        self.assertIs(win.center.currentWidget(),win.collection_workspace)
        win.studio_header.navigation['explore'].click()
        self.assertIs(win.center.currentWidget(),win.anatomy_tab)
        self.assertIs(win.viewport.camera,camera)
        win._studio_search('radius')
        self.assertEqual(win.search.edit.text(),'radius')
        self.assertFalse(win.left_dock.isHidden())
        win.studio_header.navigation['3d models'].click()
        win.studio_header.navigation['lessons'].click()
        self.assertIs(win.center.currentWidget(),win.collection_workspace)
        self.assertIs(win.collection_workspace.pages.currentWidget(),win.lessons_panel)
        win._close_center_tab(win.center.indexOf(win.collection_workspace))
        self.assertGreaterEqual(win.center.indexOf(win.collection_workspace),0)

    def test_shell_shortcuts_are_distinct_and_saved_view_manager_is_reachable(self):
        win = self.window
        keys = [action.shortcut().toString() for action in win.workspace_actions]
        self.assertEqual(len(keys), len(set(keys)))
        registered = [key.toString() for action in win.cmds.actions.values() for key in action.shortcuts()]
        self.assertFalse(set(keys) & set(registered))
        win._fill_views_menu()
        self.assertIn('Manage saved views…', [a.text() for a in win.views_menu.actions()])
        from app.ui.saved_views import SavedViewsDialog
        dialog = SavedViewsDialog(win)
        dialog.deleteLater()


if __name__ == '__main__':
    unittest.main()
