"""Native structural tests only: no GL rendering, screenshots, or model builds."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication,QWidget,QLabel,QVBoxLayout
from app.ui.studio_scene import StudioScene

class StudioSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def scene(self):
        teaching=QWidget();teaching.hide()
        reveal=QWidget();QVBoxLayout(reveal).addWidget(QLabel('Reveal controls'))
        result=StudioScene(QWidget(),QWidget(),reveal,QWidget(),teaching)
        result.resize(1400,850);result.arrange();self.addCleanup(result.deleteLater);return result
    def test_sibling_cards_and_canvas_recovery(self):
        scene=self.scene()
        self.assertIs(scene.viewport.parentWidget(),scene)
        self.assertIs(scene.cards['parts'].parentWidget(),scene)
        width=scene.viewport.width();scene.tools['parts'].setChecked(False)
        self.assertEqual(scene.viewport.width(),width)
        self.assertEqual(scene.viewport.geometry(),scene.rect())
        self.assertTrue(scene.cards['parts'].isHidden())
        scene.tools['reveal'].setChecked(True)
        self.assertFalse(scene.cards['reveal'].isHidden())
        self.assertTrue(scene.viewport.geometry().contains(scene.cards['reveal'].geometry()))
    def test_compact_card_and_dock_bounds(self):
        scene=self.scene();scene.resize(430,650)
        scene.show_card('reveal',True);scene.arrange()
        self.assertTrue(scene.cards['parts'].isHidden())
        self.assertEqual(scene.dock_layout.rowCount(),2)
        self.assertGreater(scene.viewport.height(),100)
        self.assertTrue(scene.rect().contains(scene.cards['reveal'].geometry()))
        self.assertTrue(scene.rect().contains(scene.dock.geometry()))
        self.assertTrue(scene.viewport.geometry().contains(scene.cards['reveal'].geometry()))
    def test_lesson_canvas_hides_model_chrome_and_restores_library(self):
        scene=self.scene()
        scene.set_subject('Heart')
        scene.set_selection('Left ventricle','A selected chamber')
        overlays=[scene.subject,scene.dock,scene.selection,scene.teaching,*scene.cards.values()]
        before=[not widget.isHidden() for widget in overlays]
        scene.set_lesson_mode(True)
        scene.set_selection('Right atrium','A later lesson step')
        scene.show_card('reveal',True)
        scene.resize(700,500);scene.arrange()
        self.assertTrue(all(widget.isHidden() for widget in overlays))
        self.assertEqual(scene.viewport.geometry(),scene.rect())
        scene.set_lesson_mode(False)
        self.assertEqual([not widget.isHidden() for widget in overlays],before)
        scene.show_card('reveal',True)
        self.assertFalse(scene.cards['reveal'].isHidden())

    def test_practice_does_not_offer_answer_controls(self):
        scene=self.scene();scene.set_practice(True)
        self.assertTrue(scene.cards['parts'].isHidden())
        self.assertFalse(scene.tools['parts'].isEnabled());self.assertFalse(scene.labels.isEnabled())
        scene.show_card('parts',True);self.assertTrue(scene.cards['parts'].isHidden())

class ModelStudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_existing_native_controls_are_live(self):
        from tests.test_local_runtime import LocalRuntimeTests
        from app.variants.local_runtime import prepare_local_model
        from app.ui.model_view import ModelView
        from app.config import DEFAULT_SETTINGS
        fixture=LocalRuntimeTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        entry=fixture.entry(fixture.fixture());entry.histology=[];entry.related=[];entry.clinical=[];entry.targets={};entry.aliases={};entry.credit_html='';entry.store=SimpleNamespace(is_local=True)
        model=prepare_local_model(entry)
        content=SimpleNamespace(tissues={},micro_models={})
        view=ModelView(entry,content,dict(DEFAULT_SETTINGS),prepared=SimpleNamespace(model=model,seconds=0))
        self.addCleanup(view.deleteLater)
        self.assertTrue(view.state.visible_mask().all())
        self.assertTrue((view.state.part_alpha == 1.0).all())
        self.assertFalse(view.gl_widget.cut_on)
        self.assertFalse(view.studio.loading_cover.isHidden())
        view.gl_widget.interactiveReady.emit()
        self.assertTrue(view.studio.loading_cover.isHidden())
        view.gl_widget.graphicsFailed.emit('Synthetic graphics failure')
        self.assertFalse(view.studio.loading_cover.isHidden())
        self.assertIn('Synthetic graphics failure',view.studio.loading_note.text())
        view.gl_widget.interactiveReady.emit()
        self.assertIs(view.gl_widget.parentWidget(),view.studio)
        self.assertIs(view.tree.parentWidget(),view.side)
        view.studio.labels.setChecked(True);self.assertTrue(view.gl_widget.labels_on)
        view.studio.measure.setChecked(True);self.assertTrue(view.gl_widget.measure_mode)
        view.set_section(0,True);view.set_section(1,True)
        self.assertIsNotNone(view.gl_widget.sections[0]);self.assertIsNotNone(view.gl_widget.sections[1])
        self.assertFalse(view.studio.cards['section'].isHidden())
        view.explode.setValue(25)
        self.assertEqual(view.explode.value(),25)
        self.assertTrue(view.section_btn.menu().actions())
        self.assertEqual(view.tree.topLevelItemCount(),1)
        view.state.select([0])
        self.assertFalse(view.studio.selection.isHidden())
        self.assertEqual(view.studio.selection_title.text(),'Wall')
        view.state.clear_selection()
        self.assertTrue(view.studio.selection.isHidden())

if __name__=='__main__':unittest.main()
