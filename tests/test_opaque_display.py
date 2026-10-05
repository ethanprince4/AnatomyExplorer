"""Display-state opacity checks; no GL context or model assets."""
import unittest
from types import SimpleNamespace
from app.viewer.renderer import Renderer,FrameState,_transparent_pass
from app.viewer.model import Look

class OpaqueDisplayTests(unittest.TestCase):
    def test_opaque_override_preserves_authored_look(self):
        look=Look(alpha=.22,translucent=True,facing=(.15,.7,2.0))
        part=SimpleNamespace(item=0,look=look,role='covering')
        frame=FrameState(opaque_materials=True)
        uniforms={}
        Renderer._set_look(SimpleNamespace(),lambda key,value:uniforms.__setitem__(key,value),part,None,frame)
        self.assertEqual(uniforms['u_alpha'],1.0)
        self.assertEqual(uniforms['u_facing_on'],0)
        self.assertFalse(_transparent_pass(part,False,1.,frame))
        self.assertTrue(_transparent_pass(part,False,.5,frame))
        self.assertTrue(_transparent_pass(part,True,1.,frame))
        self.assertEqual(look.alpha,.22)
        self.assertEqual(look.facing,(.15,.7,2.0))
        frame.opaque_materials=False
        Renderer._set_look(SimpleNamespace(),lambda key,value:uniforms.__setitem__(key,value),part,None,frame)
        self.assertEqual(uniforms['u_alpha'],.22)
        self.assertEqual(uniforms['u_facing_on'],1)
        self.assertTrue(_transparent_pass(part,False,1.,frame))
