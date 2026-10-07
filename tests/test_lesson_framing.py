"""Sectioned lesson framing must not retain the previous organ's target."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from app.main_window import MainWindow

class LessonFramingTests(unittest.TestCase):
    def test_named_model_lesson_keeps_camera_and_hidden_covers(self):
        from app.ui.model_view import ModelView
        host = SimpleNamespace(state=Mock(), gl_widget=Mock(),
            vmodel=SimpleNamespace(cameras={'Inside': {}}),
            _fully_visible=Mock(), part_ids=Mock(return_value=([2, 4], [])),
            _show_selection=Mock(), focus_parts=Mock())
        self.assertEqual(ModelView.show_lesson_parts(host, ['Valve'], view_name='Inside'), [])
        host.gl_widget.set_named_view.assert_called_once_with('Inside', animate=False)
        host.state.select.assert_called_once_with([2, 4])
        host.state.set_hidden.assert_not_called()
        host.focus_parts.assert_not_called()

    def scene(self,anchors=()):
        state=Mock();state.visible_mask.return_value=[False,True,True]
        vp=Mock();vp.section_anchors=anchors;vp.clip_on=[False,True,False]
        resolver=Mock();resolver.resolve_all.side_effect=lambda names: [10,11] if 'Cranium' in names else []
        resolver.resolve.return_value=[10,11]
        host=SimpleNamespace(state=state,viewport=vp,lesson_resolver=resolver,
            ds=SimpleNamespace(systems=[{'key':'skeletal'}],regions=[{'key':'head'}]),
            view_panel=Mock(),info=Mock(),center=Mock(),_update_counts=Mock())
        host.center.currentIndex.return_value=0
        lessons=json.loads((Path(__file__).parents[1]/'data/content/lessons_skeletal.json').read_text(encoding='utf-8'))
        step=next(step for lesson in lessons for step in lesson['steps'] if step['title']=='Three steps down')
        return host,vp,step
    def test_authored_skull_step_frames_focus_before_section_index_ready(self):
        host,vp,step=self.scene()
        MainWindow.apply_scene(host,step)
        vp.frame_structures.assert_called_once_with([10,11],view='superior')
        vp.set_view.assert_not_called()
    def test_available_section_anchors_remain_preferred(self):
        host,vp,step=self.scene([(12,None,1)])
        MainWindow.apply_scene(host,step)
        vp.frame_structures.assert_called_once_with([10,11,12],view='superior')
    def test_legacy_axial_commands_use_height_and_keep_the_exposed_side(self):
        from app.data import Dataset
        from app.config import DATA_DIR
        ds=Dataset(DATA_DIR)
        expected={'lessons_skeletal.json':4,'lessons_neuro_brain.json':2,'lessons_cardio_vessels.json':1}
        for name,count in expected.items():
            lessons=json.loads((Path(__file__).parents[1]/'data/content'/name).read_text(encoding='utf-8'))
            axial=[s for l in lessons for s in l['steps'] if s.get('clip') and s.get('view') in ('superior','inferior')]
            self.assertEqual(len(axial),count)
            for step in axial:
                clip=step['clip'];self.assertEqual(clip[0],2)
                self.assertEqual(bool(clip[2]) if len(clip)>2 else False,step['view']=='superior')
        host,vp,step=self.scene()
        from app.lessons import Resolver
        lo,hi=ds.bounds_of(Resolver(ds).resolve_all(step['focus']))
        height=ds.scene_bbox[0,1]+step['clip'][1]*(ds.scene_bbox[1,1]-ds.scene_bbox[0,1])
        self.assertLess(lo[1],height)
        self.assertGreater(hi[1],height)
        # The retained negative half-space contains the skull base, not empty Z space.
        self.assertTrue(step['clip'][2])

    def test_explicit_frame_off_is_preserved(self):
        host,vp,step=self.scene();step['frame']=False
        MainWindow.apply_scene(host,step)
        vp.frame_structures.assert_not_called()
        vp.set_view.assert_called_once_with('superior')

if __name__=='__main__':unittest.main()
