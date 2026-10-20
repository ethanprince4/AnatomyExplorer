"""Full anatomy canvases with floating library and case instruments."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget, QPushButton, QHBoxLayout

from app.ui.studio_scene import StudioScene
from app.ui.outline import Outline, OutlineItem


APP = QApplication.instance() or QApplication([])


def instrument(title):
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.addWidget(QLabel(title))
    return widget


class ModelStageLayoutTests(unittest.TestCase):
    def setUp(self):
        self.scene = StudioScene(QWidget(), instrument("Parts"), instrument("Reveal"),
                                 instrument("Sections"), instrument("Function"))
        self.scene.teaching.hide()
        self.scene.set_subject("Cardiac muscle")
        self.scene.set_stored_views(["Overview", "Longitudinal section"], {}, lambda name: None,
                                    "cardiac_muscle")
        self.scene.resize(1600, 1000)
        self.scene.show()
        APP.processEvents()
        self.scene.show_card("parts", True)
        self.scene.show_card("reveal", True)
        self.scene.arrange()

    def tearDown(self):
        self.scene.close()
        self.scene.deleteLater()
        APP.processEvents()

    def assert_full_canvas(self):
        self.assertEqual(self.scene.viewport.geometry(), self.scene.rect())
        self.assertTrue(self.scene.viewport.mask().isEmpty())

    def test_wide_anatomy_canvas_continues_under_floating_instruments(self):
        self.scene.set_selection("Endomysium", "Connective tissue surrounding each muscle cell.")
        self.assert_full_canvas()
        self.assertTrue(self.scene.wall_fade.testAttribute(Qt.WA_TransparentForMouseEvents))
        self.assertGreater(self.scene.viewport.label_stage_insets[0], self.scene.cards['parts'].geometry().right())
        APP.processEvents()
        image=self.scene.wall_fade._image
        self.assertIsNotNone(image)
        self.assertEqual(image.pixelColor(800,500).alpha(),0)
        # The specimen is progressively dimmed beyond the text, never cut at a box edge.
        alphas=[image.pixelColor(x,500).alpha() for x in (360,400,440,480,520,560)]
        self.assertGreater(alphas[0],alphas[-1])
        self.assertTrue(all(a>=b for a,b in zip(alphas,alphas[1:])))
        self.assertGreater(alphas[2],0)

    def test_hidden_instruments_remove_side_fades_without_resizing_model(self):
        before = self.scene.viewport.geometry()
        self.scene.show_card("parts", False)
        self.scene.show_card("reveal", False)
        self.scene.set_stored_views([], {}, lambda name: None, 'fixture')
        self.assertEqual(self.scene.viewport.geometry(),before)
        self.assertEqual(self.scene.wall_fade.zones[0],0)
        self.assertEqual(self.scene.wall_fade.zones[2],0)

    def test_labels_paint_above_anatomy_fade(self):
        overlay = QWidget(self.scene.viewport)
        overlay.setStyleSheet('background:white;')
        overlay.setGeometry(480,450,20,20)
        self.scene.viewport.overlay = overlay
        overlay.show()
        self.scene.arrange()
        self.scene.wall_fade.set_zones((1000,0,0,0))
        APP.processEvents()
        self.assertIs(self.scene.wall_fade.parentWidget(), self.scene.viewport)
        pixel = self.scene.grab().toImage().pixelColor(490,460)
        self.assertGreaterEqual(min(pixel.red(),pixel.green(),pixel.blue()),250)

    def test_lesson_canvas_has_no_model_instruments_or_fades(self):
        self.scene.set_lesson_mode(True)
        self.assert_full_canvas()
        self.assertTrue(self.scene.wall_fade.isHidden())
        self.assertTrue(self.scene.dock.isHidden())
        self.assertTrue(self.scene.stored_views.isHidden())
        self.scene.set_lesson_mode(False)
        self.assert_full_canvas()
        self.assertFalse(self.scene.wall_fade.isHidden())

    def test_compact_selection_keeps_full_canvas_and_one_instrument(self):
        self.scene.set_selection("Endomysium", "Connective tissue surrounding each muscle cell.")
        self.scene.resize(760, 800)
        APP.processEvents()
        self.assert_full_canvas()
        self.assertTrue(all(card.isHidden() for card in self.scene.cards.values()))
        self.assertFalse(self.scene.selection.geometry().intersects(self.scene.stored_views.geometry()))
        self.scene.show_card("reveal", True)
        self.assertTrue(self.scene.selection.isHidden())
        self.assert_full_canvas()
        self.assertFalse(self.scene.cards["reveal"].geometry().intersects(self.scene.stored_views.geometry()))

    def test_stored_views_use_real_names_and_skip_unnamed_numbers(self):
        self.scene.set_stored_views(['1','V2','3','Corpuscle'],
            {'V2':{'note':'Longitudinal section'},'3':{'title':'Renal vessels'}},lambda name:None,'fixture')
        self.assertNotIn('1',self.scene.view_tiles)
        self.assertEqual(self.scene.view_tiles['V2'].accessibleName(),'Longitudinal section')
        self.assertEqual(self.scene.view_tiles['3'].accessibleName(),'Renal vessels')
        self.assertEqual(self.scene.view_tiles['Corpuscle'].accessibleName(),'Corpuscle')

    def test_selected_prose_grows_before_views_with_one_outer_scroll(self):
        scene=self.scene;scene.simplify_model_controls()
        scene.set_selection('Endomysium','Connective tissue surrounding each muscle cell.')
        APP.processEvents();scene.arrange();APP.processEvents()
        short_height=scene.selection.height()
        self.assertLess(short_height,200)
        self.assertGreater(scene.selection_actions.y(),scene.selection_scroll.geometry().bottom())
        scene.resize(900,650)
        scene.set_selection('Endomysium','Connective tissue surrounding each muscle cell. '*35)
        APP.processEvents();scene.arrange();APP.processEvents()
        self.assertGreater(scene.selection.height(),short_height)
        self.assertEqual(scene.selection_scroll.verticalScrollBar().maximum(),0)
        self.assertEqual(scene.stored_views.verticalScrollBar().maximum(),0)
        self.assertGreater(scene.reading_wall.verticalScrollBar().maximum(),0)
        self.assertGreater(scene.stored_views.y(),scene.selection.geometry().bottom())
        scene.set_details_mode(True)
        self.assertTrue(scene.reading_wall.isHidden())
        self.assertEqual(scene.viewport.label_stage_insets[2],16)
        scene.set_details_mode(False)
        self.assertFalse(scene.reading_wall.isHidden())

    def test_parts_tree_keeps_available_height_when_room_shrinks(self):
        layout=self.scene.parts.layout()
        tree=Outline();tree.setRowHeight(31)
        for index in range(40):
            item=OutlineItem(tree);item.setText(0,f'Kidney structure {index}')
        layout.addWidget(tree,1)
        row=QHBoxLayout()
        for name in ('Isolate','Hide','Show all'):row.addWidget(QPushButton(name))
        layout.addLayout(row)
        lessons=QPushButton('Related lessons');layout.addWidget(lessons)
        self.scene.resize(1836,1080);APP.processEvents()
        self.scene.resize(1196,811);APP.processEvents()
        self.scene.arrange();APP.processEvents()
        self.assertGreater(tree.height(),350)
        self.assertLess(tree.geometry().bottom(),lessons.y())
        self.assertGreater(lessons.y(),self.scene.parts.height()-100)

    def test_right_captions_use_wall_below_reveal_in_wide_room(self):
        self.scene.set_annotation_mode(True)
        self.assertTrue(self.scene.cards['parts'].isHidden())
        self.assertIn(-1,self.scene.viewport.label_caption_zones)
        x,y,width,height=self.scene.viewport.label_caption_zones[1]
        reveal=self.scene.cards['reveal'].geometry()
        self.assertGreaterEqual(x,reveal.x())
        self.assertEqual(y,212)
        self.assertGreaterEqual(width,300)
        self.assertGreaterEqual(height,300)
        self.assertLessEqual(y+height,self.scene.height()-80)

    def test_small_annotation_mode_tucks_instruments_and_opens_both_caption_rails(self):
        self.scene.resize(1196,811);APP.processEvents()
        self.scene.set_selection('Renal artery','The artery supplying the kidney.')
        self.assertFalse(self.scene.cards['reveal'].isHidden())
        self.scene.set_annotation_mode(True)
        self.assertTrue(self.scene.cards['reveal'].isHidden())
        self.assertTrue(self.scene.cards['parts'].isHidden())
        self.assertTrue(self.scene.selection.isHidden())
        _,y,width,height=self.scene.viewport.label_caption_zones[1]
        self.assertEqual(y,212)
        self.assertGreaterEqual(height,450)
        self.assertGreaterEqual(width,300)
        lx,ly,lw,lh=self.scene.viewport.label_caption_zones[-1]
        self.assertLess(lx,100)
        self.assertEqual((ly,lw,lh),(y,width,height))
        self.scene.set_annotation_mode(False)
        self.assertFalse(self.scene.cards['reveal'].isHidden())
        self.assertFalse(self.scene.cards['parts'].isHidden())
        self.assertNotIn(-1,self.scene.viewport.label_caption_zones)
        self.assertFalse(self.scene.selection.isHidden())
        self.assert_full_canvas()

    def test_reference_has_one_compact_toolbar_and_expands_description(self):
        self.scene.set_reference_mode(True)
        self.scene.set_selection('Endomysium','Connective tissue surrounding each muscle cell. '*90)
        self.assert_full_canvas()
        shown={key for key,widget in self.scene.tools.items() if not widget.isHidden()}
        self.assertEqual(shown,{'labels','show_all','reset'})
        self.assertTrue(all(card.isHidden() for card in self.scene.cards.values()))
        self.assertTrue(self.scene.stored_views.isHidden())
        self.assertTrue(self.scene.selection_description.isHidden())
        collapsed=self.scene.selection.height()
        self.scene.selection_expand.setChecked(True)
        self.assertGreater(self.scene.selection.height(),collapsed)
        self.assertGreater(self.scene.selection.height(),330)
        self.assertFalse(self.scene.selection_description.isHidden())
        self.assertLessEqual(self.scene.selection.geometry().bottom(),self.scene.dock.y()-20)


if __name__ == "__main__":
    unittest.main()
