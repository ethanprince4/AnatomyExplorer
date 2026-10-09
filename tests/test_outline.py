"""The self-drawn outline that replaced Qt's tree widgets, and the parts tree's structure families.

Run with QT_QPA_PLATFORM=offscreen and python -B -m unittest.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.config import DEFAULT_SETTINGS
from app.ui.model_view import ModelView, family_title, structure_families
from app.ui.outline import ARROW, Outline, OutlineItem
from test_catalog_viewer_ui import FakeModelViewport, Widgets, dataset, entry

QAPP = QApplication.instance() or QApplication([])


class OutlineTests(Widgets):
    def outline(self):
        tree = self.keep(Outline())
        tree.resize(300, 400)
        self.top = OutlineItem(tree)
        self.top.setText(0, "Bones")
        self.top.setText(1, "2")
        self.top.setCheckable(True)
        self.a = OutlineItem(self.top)
        self.a.setText(0, "Radius")
        self.a.setCheckable(True)
        self.b = OutlineItem(self.top)
        self.b.setText(0, "Ulna")
        self.b.setCheckable(True)
        self.other = OutlineItem(tree.invisibleRootItem())
        self.other.setText(0, "Muscles")
        tree.show()
        QAPP.processEvents()
        return tree

    def row_point(self, tree, item, x=None):
        rect = tree.visualItemRect(item)
        return QPoint(rect.left() + 120 if x is None else x, rect.center().y())

    def test_rows_follow_expansion_and_hiding(self):
        tree = self.outline()
        self.assertEqual(tree.visibleRowCount(), 2)
        self.assertIsNone(self.top.parent())
        self.assertIs(self.a.parent(), self.top)
        self.top.setExpanded(True)
        self.assertEqual(tree.visibleRowCount(), 4)
        self.a.setHidden(True)
        self.assertEqual(tree.visibleRowCount(), 3)
        self.assertIs(tree.itemAt(self.row_point(tree, self.b)), self.b)
        self.assertEqual(tree.topLevelItemCount(), 2)
        tree.clear()
        self.assertEqual(tree.visibleRowCount(), 0)
        self.assertIsNone(tree.currentItem())

    def test_arrow_and_check_box_clicks_do_not_click_the_row(self):
        tree = self.outline()
        clicked, changed, expanded = [], [], []
        tree.itemClicked.connect(lambda item, col: clicked.append(item))
        tree.itemChanged.connect(lambda item, col: changed.append((item, item.checkState(0))))
        tree.itemExpanded.connect(expanded.append)
        x0 = 4
        QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, self.row_point(tree, self.top, x0 + 6))
        self.assertTrue(self.top.isExpanded())
        self.assertEqual(expanded, [self.top])
        QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, self.row_point(tree, self.top, x0 + ARROW + 5))
        self.assertEqual(changed, [(self.top, Qt.Unchecked)])
        self.assertEqual(clicked, [])
        self.assertEqual(tree.selectedItems(), [])
        QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, self.row_point(tree, self.a))
        self.assertEqual(clicked, [self.a])
        self.assertIs(tree.currentItem(), self.a)
        self.assertEqual(tree.selectedItems(), [self.a])
        tree.clearSelection()
        self.assertEqual(tree.selectedItems(), [])

    def test_double_click_activates_and_opens(self):
        tree = self.outline()
        activated = []
        tree.itemActivated.connect(lambda item, col: activated.append(item))
        QTest.mouseDClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, self.row_point(tree, self.top))
        self.assertEqual(activated, [self.top])
        self.assertTrue(self.top.isExpanded())

    def test_keyboard_moves_opens_checks_and_activates(self):
        tree = self.outline()
        activated = []
        tree.itemActivated.connect(lambda item, col: activated.append(item))
        tree.setFocus()
        tree.setCurrentItem(self.top)
        QTest.keyClick(tree, Qt.Key_Right)
        self.assertTrue(self.top.isExpanded())
        QTest.keyClick(tree, Qt.Key_Right)
        self.assertIs(tree.currentItem(), self.a)
        QTest.keyClick(tree, Qt.Key_Space)
        self.assertEqual(self.a.checkState(0), Qt.Unchecked)
        QTest.keyClick(tree, Qt.Key_Down)
        self.assertIs(tree.currentItem(), self.b)
        QTest.keyClick(tree, Qt.Key_Return)
        self.assertEqual(activated, [self.b])
        QTest.keyClick(tree, Qt.Key_Left)
        self.assertIs(tree.currentItem(), self.top)
        QTest.keyClick(tree, Qt.Key_Left)
        self.assertFalse(self.top.isExpanded())
        QTest.keyClick(tree, Qt.Key_End)
        self.assertIs(tree.currentItem(), self.other)
        self.assertIn("Muscles", tree.accessibleDescription())

    def test_scroll_to_item_opens_its_parents(self):
        tree = self.outline()
        tree.setCurrentItem(self.b)
        tree.scrollToItem(self.b)
        self.assertTrue(self.top.isExpanded())
        self.assertTrue(tree.visualItemRect(self.b).isValid())
        self.assertIn("Ulna", tree.accessibleDescription())
        self.assertIn("level 2", tree.accessibleDescription())

    def test_accessibility_never_sees_a_table_or_tree(self):
        """The macOS crash came from table cells of a tree view; the outline must expose none."""
        tree = self.outline()
        self.top.setExpanded(True)
        QAPP.processEvents()
        banned = {QAccessible.Tree, QAccessible.TreeItem, QAccessible.Table, QAccessible.Cell, QAccessible.Row,
                  QAccessible.Column, QAccessible.List, QAccessible.ListItem}
        stack = [QAccessible.queryAccessibleInterface(tree)]
        seen = 0
        while stack:
            iface = stack.pop()
            if iface is None:
                continue
            seen += 1
            self.assertNotIn(iface.role(), banned)
            self.assertIsNone(iface.tableCellInterface())
            stack.extend(iface.child(i) for i in range(iface.childCount()))
        self.assertGreater(seen, 0)

    def test_many_rows_scroll(self):
        tree = self.keep(Outline())
        tree.resize(200, 120)
        rows = [OutlineItem(tree) for _ in range(200)]
        for n, row in enumerate(rows):
            row.setText(0, f"Row {n}")
        tree.show()
        QAPP.processEvents()
        self.assertGreater(tree.verticalScrollBar().maximum(), 0)
        tree.scrollToItem(rows[150])
        self.assertTrue(tree.viewport().rect().intersects(tree.visualItemRect(rows[150])))
        tree.grab()                                           # paints without error


class FamilyTests(Widgets):
    def test_numbered_copies_share_a_row_and_few_stay_separate(self):
        names = ([f"Lining cell {n}" for n in range(8)] + [f"Lining cell {n} nucleus" for n in range(8)] +
                 ["Liver acinus – zone 1", "Liver acinus – zone 2", "Liver acinus – zone 3", "Serosa", "Capsule",
                  "Capsule"])
        rows = structure_families(names)
        self.assertEqual(rows[0], ("Lining cells", list(range(8)), True))
        self.assertEqual(rows[1], ("Lining cell nuclei", list(range(8, 16)), True))
        self.assertEqual([title for title, _, _ in rows[2:6]], [None, None, None, None])
        self.assertEqual(rows[6], ("Capsule", [20, 21], False))
        self.assertEqual(len(rows), 7)
        self.assertEqual(family_title("mitral_anterolateral_chorda_#"), "Mitral anterolateral chordae")
        self.assertEqual(family_title("Umbrella cell # (surface)"), "Umbrella cell (surface)")

    def view(self):
        names = ([f"Lining cell {n}" for n in range(7)] + [f"Lining cell {n} nucleus" for n in range(7)] +
                 ["Basement membrane", "Basement membrane"])          # the second is its cut-face cover
        items = [SimpleNamespace(index=i, key=f"Cell{i}", name=name, description="", group="Cells", bulk=False,
                                 atlas=[], parts=[]) for i, name in enumerate(names)]
        items.append(SimpleNamespace(index=len(names), key="radius", name="Radius", description="", group="Bones",
                                     bulk=False, atlas=[], parts=[]))
        m = SimpleNamespace(items=items,
            groups=[SimpleNamespace(key="Cells", title="Cells", items=list(range(len(names)))),
                    SimpleNamespace(key="Bones", title="Bones", items=[len(names)])],
            camera_order=[], cameras={}, has_teased=False, parts=[], states={}, triangle_count=0, kind="procedural",
            bounds_min=np.zeros(3), bounds_max=np.ones(3), sidecar={}, metres_per_unit=None)
        m.group_of = lambda sid: m.groups[0] if sid < len(names) else m.groups[1]
        content = SimpleNamespace(tissues={}, micro_models={})
        ds = dataset()
        n = len(items)
        ds.n, ds.system_of, ds.subsystem_of = n, np.zeros(n, int), np.zeros(n, int)
        ds.region_mask = np.ones(n, int)
        with patch('app.ui.model_view.ModelDataset', return_value=ds), \
             patch('app.ui.model_view.ModelViewport', FakeModelViewport):
            return self.keep(ModelView(entry("fixture"), content, dict(DEFAULT_SETTINGS),
                                       prepared=SimpleNamespace(model=m, seconds=0)))

    def test_parts_tree_lists_kinds_not_copies(self):
        view = self.view()
        group = view.group_items["Cells"]
        self.assertEqual([group.child(i).text(0) for i in range(group.childCount())],
                         ["Lining cells", "Lining cell nuclei", "Basement membrane"])
        self.assertEqual(group.child(0).text(1), "7")
        nuclei = group.child(1)
        nuclei.setCheckState(0, Qt.Unchecked)
        self.assertTrue(all(view.state.hidden[i] for i in range(7, 14)))
        self.assertFalse(view.state.hidden[0])
        self.assertEqual(group.checkState(0), Qt.PartiallyChecked)
        view._clicked(9, Qt.NoModifier)                       # one nucleus picked in 3D
        self.assertIs(view.tree.currentItem(), nuclei)
        self.assertTrue(group.isExpanded())
        view.tree.itemClicked.emit(nuclei, 0)
        self.assertEqual(sorted(view.state.selected), list(range(7, 14)))
        self.assertEqual(view.selection_status.text(), "Lining cell nuclei")
        view.filter.setText("nucleus 3")
        self.assertFalse(nuclei.isHidden())
        self.assertTrue(group.child(0).isHidden())
        view.filter.clear()
        membrane = group.child(2)
        self.assertEqual(membrane.text(1), "")                # one structure: no count
        view._clicked(15, Qt.NoModifier)                      # the cover picked in 3D picks the structure
        self.assertEqual(sorted(view.state.selected), [14, 15])
        self.assertIs(view.tree.currentItem(), membrane)
        self.assertEqual(view.selection_status.text(), "Basement membrane")


if __name__ == "__main__":
    unittest.main()
