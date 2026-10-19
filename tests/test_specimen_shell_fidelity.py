"""Bounded offscreen checks for the native checkpoint-3 navigation and dock."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace
import unittest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QFontInfo
from PySide6.QtWidgets import QApplication, QMenu, QToolButton, QWidget

from app.ui import theme
from app.ui.studio_shell import StudioHeader, atlas_dock
from app.ui.studio_style import icon

APP = QApplication.instance() or QApplication([])


class SpecimenShellFidelityTests(unittest.TestCase):
    def setUp(self):
        theme.apply_theme(APP, scale=1.0, mode="gallery-slate")
        self.owner = QWidget()
        self.owner.resize(1920, 1080)
        self.owner.views_menu = QMenu(self.owner)
        self.header = StudioHeader(self.owner)
        self.header.layout().removeWidget(self.header.subject)
        self.header.subject.hide()
        self.header.resize(1816, 80)
        self.owner.show()
        self.header.show()
        self.header.navigation_rail.show()
        APP.processEvents()

    def tearDown(self):
        self.header.close()
        self.owner.close()
        self.header.deleteLater()
        self.owner.deleteLater()
        theme.apply_theme(APP, scale=1.0, mode="gallery-slate")
        APP.processEvents()

    def test_rail_centers_every_hit_area_and_fits_both_font_scales(self):
        rail = self.header.navigation_rail
        for scale in (1.0, 1.6):
            theme.apply_theme(APP, scale=scale)
            for height in (800, 1080):
                with self.subTest(scale=scale, height=height):
                    rail.resize(rail.width(), height)
                    rail.fit_contents()
                    APP.processEvents()
                    APP.processEvents()
                    last_bottom = rail.mark.mapTo(rail, QPoint(0, 44)).y()
                    for button in rail.room_buttons + rail.utility_buttons:
                        point = button.mapTo(rail, QPoint(0, 0))
                        self.assertAlmostEqual(point.x() + button.width()/2, (rail.width()-1)/2, delta=.5)
                        self.assertGreaterEqual(point.y(), last_bottom)
                        self.assertLessEqual(button.fontMetrics().horizontalAdvance(button.text()), button.width()-4)
                        self.assertEqual(QFontInfo(button.font()).family(), "Fira Sans")
                        last_bottom = point.y() + button.height()
                    self.assertLessEqual(last_bottom, height-10)
                    self.assertLessEqual(rail.minimumSizeHint().height(), height)
        theme.apply_theme(APP, scale=1.0)
        rail.resize(rail.width(), 1080)
        rail.fit_contents()
        APP.processEvents()
        self.assertGreaterEqual(rail.width(), 84)
        self.assertLess(rail.width(), 104)
        self.assertEqual(rail.mark.height(), 44)
        self.assertEqual(rail.mark.y(), 18)
        self.assertEqual(rail.rooms.y(), 108)

    def test_history_keeps_its_slot_and_routes_existing_signals(self):
        seen = []
        self.header.backRequested.connect(lambda: seen.append("back"))
        self.header.forwardRequested.connect(lambda: seen.append("forward"))
        for scale in (1.0, 1.6):
            theme.apply_theme(APP, scale=scale)
            for width in (1176, 1816):
                self.header.resize(width, 80)
                self.header.set_places("Atlas", None)
                APP.processEvents()
                before = (self.header.history.width(), self.header.search.x(), self.header.trail.x())
                self.assertTrue(self.header.back_button.text().startswith("Back to Atlas"))
                self.assertGreaterEqual(self.header.back_button.sizeHint().width(),
                                        self.header.back_button.fontMetrics().horizontalAdvance(self.header.back_button.text()) + 20)
                self.header.set_places("A very long destination that must stay in the history slot", "Lessons")
                APP.processEvents()
                self.assertEqual(before, (self.header.history.width(), self.header.search.x(), self.header.trail.x()))
                self.assertTrue(self.header.brand.isHidden())
                self.assertLess(self.header.history.geometry().right(), self.header.search.x())
        self.header.back_button.click()
        self.header.forward_button.click()
        self.assertEqual(seen, ["back", "forward"])
        self.assertEqual(self.header.forward_button.accessibleName(), "Forward to Lessons")

    def test_reference_icons_are_distinct_and_follow_the_active_wall(self):
        folder = Path(__file__).resolve().parents[1] / "app/ui/resources/studio/icons/specimen"
        atlas = (folder / "atlas.svg").read_text(encoding="utf-8")
        models = (folder / "models.svg").read_text(encoding="utf-8")
        self.assertIn('<circle cx="12" cy="5.5"', atlas)
        self.assertNotEqual(atlas, models)
        glyph = icon("atlas")
        for mode in theme.SPECIMEN_PALETTES:
            theme.apply_theme(APP, mode=mode)
            image = glyph.pixmap(48, 48).toImage()
            solid = [image.pixelColor(x, y) for y in range(image.height()) for x in range(image.width())
                     if image.pixelColor(x, y).alpha() == 255]
            self.assertTrue(solid)
            self.assertEqual(solid[0].name(), theme.palette()["text_2"].lower())

    def test_dock_words_keep_action_and_labels_behavior(self):
        self.owner.section_menu = QMenu(self.owner)
        self.owner.tools_menu = QMenu(self.owner)
        self.owner.tree = QWidget(self.owner)
        seen, captions = [], {"open": False}
        self.owner.viewport = SimpleNamespace(
            set_labels_on=lambda on: seen.append(("labels", on)),
            labels_all_open=lambda: captions["open"],
            show_all_labels=lambda on: captions.update(open=on),
        )
        labels = {"xray": "X-ray", "isolate": "Isolate", "hide": "Hide", "measure": "Measure",
                  "reset_view": "Reset view", "structure_labels": "Labels"}
        actions = {key: QAction(label, self.owner) for key, label in labels.items()}
        for key, action in actions.items():
            action.triggered.connect(lambda checked=False, key=key: seen.append((key, checked)))
        actions["measure"].setCheckable(True)
        actions["structure_labels"].setCheckable(True)
        actions["structure_labels"].setChecked(True)
        self.owner.cmds = SimpleNamespace(actions=actions)
        dock = atlas_dock(self.owner)
        dock.show()
        APP.processEvents()
        buttons = {button.text(): button for button in dock.findChildren(QToolButton)}
        for text in ("X-ray", "Isolate", "Hide", "Measure", "Reset view", "Labels", "Show all"):
            self.assertEqual(buttons[text].toolButtonStyle(), Qt.ToolButtonTextOnly)
        buttons["Measure"].click()
        self.assertTrue(actions["measure"].isChecked())
        self.assertIn(("measure", True), seen)
        actions["hide"].setEnabled(False)
        self.assertFalse(buttons["Hide"].isEnabled())
        buttons["Show all"].click()
        self.assertTrue(captions["open"])
        self.assertEqual(buttons["Show all"].text(), "Hide all")
        buttons["Labels"].click()
        self.assertFalse(actions["structure_labels"].isChecked())
        self.assertTrue(buttons["Show all"].isHidden())
        self.assertIn(("labels", False), seen)
        buttons["Reset view"].click()
        self.assertIn(("reset_view", False), seen)
        for scale in (1.0, 1.6):
            theme.apply_theme(APP, scale=scale)
            APP.processEvents()
            self.assertLessEqual(dock.sizeHint().width(), 1144)


if __name__ == "__main__":
    unittest.main()
