"""Native shell checks without creating/loading/rendering an anatomy/model viewport."""
import ast
import importlib
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('XDG_CACHE_HOME', '/tmp/anatomy-ui-qt-cache')
HERE = Path(__file__).resolve()
BASE = Path(os.environ.get('ANATOMY_UI_BASE', str(HERE.parents[3] / 'integration-azure-handoff/candidate/AnatomyExplorer')))
OVERLAY = Path(os.environ.get('ANATOMY_UI_OVERLAY', str(HERE.parents[1])))
sys.path.insert(0, str(BASE))
import app
app.__path__.insert(0, str(OVERLAY / 'app'))
import app.ui
app.ui.__path__.insert(0, str(OVERLAY / 'app/ui'))
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from app.ui import theme
from app.ui.nav import NavTabWidget
from app.ui.shell import CommandPalette, ElidingLabel, WorkspaceNotice
from app.ui.settings_dialog import SettingsDialog
from app.actions import ActionRegistry
from app.config import DEFAULT_SETTINGS

QAPP = QApplication.instance() or QApplication([])
theme.apply_theme(QAPP)


def contrast(a, b):
    def light(c):
        values = [int(c[i:i+2], 16) / 255 for i in (1, 3, 5)]
        values = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
        return sum(v * k for v, k in zip(values, (.2126, .7152, .0722)))
    x, y = sorted((light(a), light(b)))
    return (y + .05) / (x + .05)


class ShellTests(unittest.TestCase):
    def tearDown(self):
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QAPP.processEvents()

    def test_palette_contrast_and_light_default(self):
        theme.set_theme('porcelain')
        self.assertEqual(theme.ACCENT, '#364f99')
        for role in ('TEXT', 'TEXT_2', 'MUTED', 'ACCENT_TEXT', 'SUCCESS', 'WARNING', 'DANGER'):
            self.assertGreaterEqual(contrast(getattr(theme, role), theme.SURFACE), 4.5, role)
        self.assertGreaterEqual(contrast(theme.ON_ACCENT, theme.ACCENT), 4.5)
        self.assertGreaterEqual(contrast(theme.MUTED, theme.RAISED), 4.5)
        theme.set_theme('slate')
        self.assertGreaterEqual(contrast(theme.TEXT, theme.SURFACE), 4.5)
        self.assertGreaterEqual(contrast(theme.ON_ACCENT, theme.ACCENT), 4.5)
        theme.set_theme('unknown')
        self.assertEqual(theme.THEME_NAME, 'porcelain')

    def test_navigation_route_order_alias_and_no_layout_leak(self):
        nav = NavTabWidget()
        titles = ['Systems', 'Regions', 'Tree', 'Histology', 'Radiology', 'Lessons', 'View', 'Models']
        for name in titles:
            nav.addTab(QWidget(), name)
        picked = []
        nav.entry_picked.connect(picked.append)
        self.assertTrue(nav.choose('Lab course'))
        self.assertEqual(nav.currentIndex(), 5)
        self.assertEqual(picked[-1], 'Lab course')
        self.assertTrue(nav.choose('Models'))
        self.assertEqual(nav.currentIndex(), 7)
        self.assertEqual(nav.group_of(7), 'Browse')
        for _ in range(15):
            nav.choose('Lessons'); nav.choose('Systems')
        self.assertEqual(nav._top_row.count(), 3)
        self.assertEqual(nav._seg_row.count(), 4)
        self.assertEqual([nav.tabText(i) for i in range(nav.count())], titles)
        self.assertFalse(nav.choose('Imaginary route'))
        nav.deleteLater(); nav.nav.deleteLater()

    def test_palette_search_keyboard_and_disabled_actions(self):
        actions = [QAction('Open model library'), QAction('Start quiz'), QAction('Reset view')]
        actions[0].setShortcut(QKeySequence('Ctrl+2'))
        actions[1].setEnabled(False)
        called = []
        actions[0].triggered.connect(lambda: called.append(True))
        dialog = CommandPalette(actions)
        dialog.query.setText('model ctrl+2')
        self.assertEqual(dialog.results.count(), 1)
        QTest.keyClick(dialog.query, Qt.Key_Return)
        self.assertEqual(called, [True])
        dialog.query.setText('nonsense')
        self.assertEqual(dialog.results.count(), 0)
        self.assertIn('No matching', dialog.summary.text())
        dialog.deleteLater()

    def test_notice_recovery_and_eliding_accessibility(self):
        notice = WorkspaceNotice()
        called = []
        notice.show_message('Image unavailable', 'Retry', lambda: called.append(True))
        self.assertFalse(notice.isHidden())
        notice.action.click()
        self.assertEqual(called, [True])
        self.assertTrue(notice.isHidden())
        label = ElidingLabel('An extremely long subject title that remains readable to assistive technology')
        label.resize(100, 30)
        label._update_text()
        self.assertEqual(label.accessibleName(), label._full_text)
        self.assertEqual(label.toolTip(), label._full_text)
        # Native fallback fonts may replace the ellipsis glyph; assert fitting text.
        self.assertNotEqual(label.text(), label._full_text)
        self.assertTrue(label._full_text.startswith(label.text()[:-1]))
        self.assertLessEqual(label.fontMetrics().horizontalAdvance(label.text()), label.width())
        notice.deleteLater(); label.deleteLater()

    def test_settings_single_appearance_reset_and_labelled_controls(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / 'fixture.ini'), QSettings.IniFormat)
            host, viewport = QWidget(), QWidget()
            registry = ActionRegistry(host, viewport, settings)
            dialog = SettingsDialog(dict(DEFAULT_SETTINGS), registry)
            saved = []
            dialog.themeChanged.connect(saved.append)
            self.assertEqual(dialog.theme_picker.count(), 1)
            self.assertEqual(dialog.theme_picker.findData('slate'), -1)
            self.assertTrue(dialog.theme_picker.isHidden())
            self.assertEqual(saved, [])
            dialog.tabs.setCurrentIndex(1)
            dialog._reset_page()
            self.assertEqual(dialog.theme_picker.currentData(), 'porcelain')
            self.assertTrue(dialog.widgets['ui_scale'].slider.accessibleName())
            self.assertTrue(dialog.widgets['ui_scale'].spin.accessibleName())
            self.assertTrue(dialog.key_filter.isClearButtonEnabled())
            dialog.deleteLater(); host.deleteLater(); viewport.deleteLater()

    def test_source_contracts_no_route_loss(self):
        source = (OVERLAY / 'app/main_window.py').read_text(encoding="utf-8")
        ast.parse(source)
        for required in ('load_cases(include_missing=True)', 'visible_case_ids()', 'set_current_case(case.id)',
                         'ModelCatalogPanel(self.content)', 'pending.retryRequested.connect',
                         'view.lessonsRequested.connect', 'lessons_for_model(view.entry.id)',
                         'self.tabs.addTab(self.catalog, "Models")'):
            self.assertIn(required, source)
        self.assertLess(source.index('self.tabs.addTab(self.view_panel, "View")'),
                        source.index('self.tabs.addTab(self.catalog, "Models")'))
        self.assertIn('self._model_load_error(result.key, pending', source)


if __name__ == '__main__':
    unittest.main()
