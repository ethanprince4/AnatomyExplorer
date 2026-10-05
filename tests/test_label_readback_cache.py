"""One numeric regression for stationary label readbacks; no GL context."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from app.viewer.renderer import Renderer
from app.viewer.viewport import ModelViewport


class LabelReadbackTests(unittest.TestCase):
    def test_compact_depth_keeps_exact_existing_anchor(self):
        from scipy.ndimage import distance_transform_edt
        depth = np.arange(35,dtype=np.float32).reshape(5,7)+1
        ids = np.array([[0,0,1],[0,1,1]],dtype=np.int32)
        ys=np.minimum(np.arange(0,5,3)+1,4)
        xs=np.minimum(np.arange(0,7,3)+1,6)
        compact=depth[ys[:,None],xs]
        view=SimpleNamespace(renderer=SimpleNamespace(size=(7,5),
            world_from_pixel=lambda x,y,d: (x,y,d)),_occluded={})
        for item in (0,1):
            original=ModelViewport._anchor(view,ids,item,None,3,depth,distance_transform_edt)
            sampled=ModelViewport._anchor(view,ids,item,None,3,compact,distance_transform_edt,ids)
            self.assertEqual(original,sampled)

    def test_hover_reuses_anchors_and_current_frame_ids(self):
        view = SimpleNamespace(state=SimpleNamespace(system_alpha=np.ones(2), part_alpha=None),
                               invalidate_labels=Mock(), update=Mock())
        ModelViewport._on_state(view)
        view.invalidate_labels.reset_mock()
        view.state.hovered = 1
        ModelViewport._on_state(view)
        view.invalidate_labels.assert_not_called()
        view.state.system_alpha[0] = .5
        ModelViewport._on_state(view)
        view.invalidate_labels.assert_called_once()

        renderer = Renderer.__new__(Renderer)
        renderer.frame_ok=True;renderer.t={'present':True};renderer.size=(2,2)
        renderer._read_prepass=Mock(return_value=np.array([1,0,2,0,3,0,4,0],np.float32))
        ids,_=renderer.read_ids()
        self.assertEqual(renderer.ids_at([(0,0),(1,1),(-1,0)]),[2,1,-1])
        renderer.read_ids()
        self.assertEqual(renderer._read_prepass.call_count,1)
        # Each new render clears the cache, including camera/visibility changes.
        renderer._ids_cache=None
        renderer.read_ids()
        self.assertEqual(renderer._read_prepass.call_count,2)
