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
        self.assertEqual(len(win.lessons_panel.lessons), 246)
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
        self.assertIs(win.tabs.currentWidget(), win.histology_panel)
        win.show_lessons()
        self.assertIs(win.tabs.currentWidget(), win.lessons_panel)
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

    def test_studio_navigation_keeps_scene_and_routes_live_search(self):
        win=self.window
        camera=win.viewport.camera
        win.studio_header.navigation['collection'].click()
        self.assertIs(win.center.currentWidget(),win.collection_workspace)
        win.studio_header.navigation['explore'].click()
        self.assertIs(win.center.currentWidget(),win.anatomy_tab)
        self.assertIs(win.viewport.camera,camera)
        win._studio_search('radius')
        self.assertEqual(win.search.edit.text(),'radius')
        self.assertFalse(win.left_dock.isHidden())
        win.studio_header.navigation['collection'].click()
        win.studio_header.navigation['learn'].click()
        self.assertIs(win.center.currentWidget(),win.anatomy_tab)
        self.assertIs(win.tabs.currentWidget(),win.lessons_panel)
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
