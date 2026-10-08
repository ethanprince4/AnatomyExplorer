"""Regression for the macOS catalog-click QComboBox.clear accessibility crash.

Uses the actual catalog widget and metadata only; no model files or renderer.
Run with QT_QPA_PLATFORM=cocoa on Mac to exercise the native Qt backend.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.ui.search_panel import ModelCatalogPanel, ROLE_ENTRY


QAPP = QApplication.instance() or QApplication([])


def entry(mid, components=(), component="main"):
    return SimpleNamespace(id=mid, name=mid, kind="procedural", kind_name="3D model",
        order=0, summary="Catalog selection regression.", targets={}, histology=[],
        related=[], clinical=[], scale_note="", credit_html="", variant="post",
        available_variants=("post",), store=SimpleNamespace(is_local=True),
        available_components=components, component=component)


class CatalogAccessibilityTests(unittest.TestCase):
    def setUp(self):
        self.was_active = QAccessible.isActive()
        QAccessible.setActive(True)
        self.entries = [entry("A heart"), entry("B skin", ("main", "cell_inset")),
                        entry("C inset", ("cell_inset",), "cell_inset")]
        self.panel = ModelCatalogPanel(SimpleNamespace(
            micro_models={e.id: e for e in self.entries}, tissues={}))
        self.panel.resize(700, 760)
        self.panel.show()
        QTest.qWait(30)

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        QAPP.processEvents()
        QAccessible.setActive(self.was_active)

    def test_clicks_keep_accessible_dropdown_rows_alive(self):
        controls = self.panel.variant_choice
        combos = (controls.choice, controls.scene)
        removed, reset = [], []
        for combo in combos:
            combo.model().rowsRemoved.connect(lambda *args: removed.append(args))
            combo.model().modelReset.connect(lambda: reset.append(True))
        opened = []
        self.panel.activated.connect(opened.append)

        for row in (1, 2, 0, 1, 0):
            # Prime the same item-view accessibility cache that clear() invalidated.
            for widget in (self.panel.list, *(combo.view() for combo in combos)):
                iface = QAccessible.queryAccessibleInterface(widget)
                self.assertIsNotNone(iface)
                for index in range(iface.childCount()):
                    child = iface.child(index)
                    self.assertIsNotNone(child)
                    self.assertTrue(child.isValid())
            item = self.panel.list.item(row)
            self.panel.list.scrollToItem(item)
            QTest.mouseClick(self.panel.list.viewport(), Qt.LeftButton,
                            pos=self.panel.list.visualItemRect(item).center())
            QAPP.processEvents()
            selected = self.entries[row]
            self.assertEqual(self.panel.list.currentItem().data(ROLE_ENTRY).id, selected.id)
            self.assertIn(selected.id, self.panel.preview.toPlainText())
            self.assertEqual(controls.choice.currentData(), "post")
            self.assertFalse(controls.choice.model().item(0).isEnabled())
            self.assertTrue(controls.choice.model().item(1).isEnabled())
            self.assertTrue(controls.version_row.isHidden())
            for index in range(controls.scene.count()):
                available = controls.scene.itemData(index) in selected.available_components
                self.assertEqual(controls.scene.model().item(index).isEnabled(), available)
                self.assertEqual(controls.scene.view().isRowHidden(index), not available)
            self.assertEqual(controls.scene.currentData(),
                             selected.component if selected.available_components else None)

        self.panel.list.setCurrentRow(-1)
        QAPP.processEvents()
        self.assertFalse(self.panel.open_button.isEnabled())
        self.assertTrue(controls.isHidden())
        self.assertEqual(removed, [], "Catalog clicks must not remove cached combo rows")
        self.assertEqual(reset, [], "Catalog clicks must preserve the combo models")
        self.assertEqual(opened, [], "Selecting a catalog entry must not load geometry")

    def test_refresh_and_filter_keep_accessible_list_rows_alive(self):
        removed, reset = [], []
        model = self.panel.list.model()
        model.rowsRemoved.connect(lambda *args: removed.append(args))
        model.modelReset.connect(lambda: reset.append(True))
        item = self.panel.list.item(1)
        QTest.mouseClick(self.panel.list.viewport(), Qt.LeftButton,
                         pos=self.panel.list.visualItemRect(item).center())
        iface = QAccessible.queryAccessibleInterface(self.panel.list)
        for index in range(iface.childCount()):
            self.assertTrue(iface.child(index).isValid())

        self.panel._run()       # what a finished model load and each verification step do
        self.assertEqual(self.panel.list.currentItem().data(ROLE_ENTRY).id, "B skin")
        self.panel.edit.setText("inset")
        self.assertEqual(self.panel.shown, 1)
        self.assertEqual(self.panel.list.currentItem().data(ROLE_ENTRY).id, "C inset")
        self.assertTrue(self.panel.list.item(1).isHidden())
        self.panel.edit.clear()
        self.assertEqual(self.panel.shown, 3)
        self.assertFalse(any(self.panel.list.item(row).isHidden() for row in range(3)))
        self.assertEqual(removed, [], "Refreshing the catalog must not remove cached list rows")
        self.assertEqual(reset, [], "Refreshing the catalog must preserve the list model")

    def test_unavailable_scene_cannot_be_requested(self):
        controls = self.panel.variant_choice
        controls.set_entry(self.entries[2])
        requests = []
        controls.componentRequested.connect(requests.append)
        controls.scene.activated.emit(controls.scene.findData("main"))
        self.assertEqual(requests, [])
        self.assertEqual(controls.scene.currentData(), "cell_inset")


if __name__ == "__main__":
    unittest.main()
