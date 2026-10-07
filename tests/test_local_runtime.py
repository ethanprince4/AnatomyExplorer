"""Local buffer compatibility and graceful optional controls; no renders/builds."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
import numpy as np
from app.variants.local_runtime import decode_local_npz, prepare_local_model

class LocalRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.v=np.array([[0,0,0],[1,0,0],[0,1,0]],dtype=np.float32)
        self.row=dict(name='Wall',group='Tissue',color='#bb7777',description='Saved description',clip=False,bulk=True)
    def fixture(self, quantized=False, **arrays):
        meta={'parts':[self.row], 'metres_per_unit':.002, 'cut_on':True}
        p=self.root/'mesh.npz'
        payload=dict(meta=np.frombuffer(json.dumps(meta).encode(),dtype=np.uint8),p0=self.v,
                     n0=np.tile([0.,0.,1.],(3,1)).astype(np.float32), i0=np.array([0,1,1],dtype=np.int32))
        if quantized:
            payload.update(p0=(self.v*65535).astype(np.uint16),b0=np.array([[0,0,0],[1,1,1]]),n0=np.tile([0,0,127],(3,1)).astype(np.int8))
        payload.update(arrays);np.savez(p,**payload);return p
    def entry(self,path,**extra):
        d=SimpleNamespace(primary=SimpleNamespace(path=path),root=self.root,companions={},**extra)
        return SimpleNamespace(id='local_fixture',name='Local fixture',variant='pre',label='Before',descriptor=d,summary='',scale_note='')
    def test_local_component_uses_separate_scene_not_parent_geometry(self):
        main=self.fixture();child=self.root/'inset.npz'
        with np.load(main,allow_pickle=False) as archive:payload={key:archive[key].copy() for key in archive.files}
        meta=json.loads(payload['meta'].tobytes());meta['parts'][0]['name']='Cell / nucleus'
        payload['meta']=np.frombuffer(json.dumps(meta).encode(),dtype=np.uint8)
        payload['p0']=payload['p0']+5;np.savez(child,**payload)
        e=self.entry(main);e.component='cell_inset';e.descriptor.components={'cell_inset':{'path':'inset.npz'}}
        model=prepare_local_model(e)
        self.assertEqual(model.items[0].name,'Cell / nucleus')
        self.assertEqual(model.runtime_component_id,'cell_inset')
        self.assertEqual(model.metres_per_unit,0.)
        self.assertEqual(model.camera_order,['V1','V2'])
        self.assertEqual(model.cameras['V1']['hidden'],['Cell / nucleus'])
        self.assertEqual(e.descriptor.primary.path,main)
        self.assertTrue(model.sidecar['mixed_schematic_scale'])

    def test_component_companion_and_missing_optional_fallback(self):
        main=self.fixture();e=self.entry(main);e.component='cell_inset'
        e.descriptor.companions={'cell_inset':'mesh.npz'}
        self.assertEqual(prepare_local_model(e).runtime_component_id,'cell_inset')
        e.descriptor.companions={'cell_inset':'missing.npz'}
        model=prepare_local_model(e)
        self.assertEqual(e.component,'main')
        self.assertFalse(hasattr(model,'runtime_component_id'))
        self.assertEqual(model.items[0].name,'Wall')
        self.assertTrue(any('Showing the main model' in warning for warning in model.runtime_warnings))

    def test_quantized_and_delta_indices(self):
        meta,rows=decode_local_npz(self.fixture(True))
        np.testing.assert_allclose(rows[0][1],self.v)
        np.testing.assert_array_equal(rows[0][3],[[0,1,2]])
        np.testing.assert_allclose(rows[0][2],[[0,0,1]]*3)
    def test_native_metadata_colors_and_camera_fallback(self):
        c=np.array([[.1,.2,.3]]*3,np.float32)
        model=prepare_local_model(self.entry(self.fixture(c0=c)))
        self.assertEqual(model.source._parts[0].clip,False)
        self.assertEqual(model.source._parts[0].bulk,True)
        self.assertEqual(model.metres_per_unit,.002)
        self.assertIsNone(model.source.viewer_vertex_colors)
        with self.assertRaisesRegex(RuntimeError, 'retired'):
            model.source.parts()
        self.assertTrue(model.parts[0].look.use_vcol)
        self.assertEqual(model.camera_order,['Home'])
        self.assertEqual(model.items[0].description,'Saved description')

    def test_final_recipe_replaces_legacy_controls_and_preserves_linear_color(self):
        from unittest.mock import patch
        self.row['color_linear'] = [.1, .2, .3]
        e = self.entry(self.fixture(), record={'static_recipe': True})
        e.id = 'thyroid_parathyroid_review_v2'
        e.descriptor.companions = {'teaching_recipe': {
            'home_view': 'Final', 'start_view': 'Final', 'metres_per_unit': .001,
            'viewer_cameras': {'Final': {'position': [2, 2, 2], 'target': [0, 0, 0], 'hidden': []}}},
            'catalog': {'parts': {'Wall': {'name': 'Readable wall'}}}}
        with patch('app.variants.anatomy_runtime_adapters.runtime._prepare_hooks') as old_hook:
            model = prepare_local_model(e)
        old_hook.assert_not_called()
        self.assertFalse(model.runtime_hooks_available)
        self.assertEqual(model.camera_order, ['Final'])
        self.assertEqual(model.items[0].key, 'Wall')
        self.assertEqual(model.items[0].name, 'Readable wall')
        self.assertEqual(model.metres_per_unit, .001)
        self.assertTrue(model.parts[0].look.use_vcol)
        np.testing.assert_allclose(model.vertices[:, 13:16], [[.1, .2, .3]] * 3)

    def test_named_thyroid_color_arrays(self):
        np.savez(self.root/'colors.npz', Wall=np.array([[.3, .4, .5]] * 3, np.float32))
        e = self.entry(self.fixture(), record={'static_recipe': True})
        e.descriptor.companions = {'colors': 'colors.npz',
            'color_contract': {'parts': [{'name': 'Wall', 'array_key': 'Wall'}]}}
        model = prepare_local_model(e)
        np.testing.assert_allclose(model.vertices[:, 13:16], [[.3, .4, .5]] * 3)
    def test_stale_animation_does_not_block_geometry(self):
        path=self.fixture();np.savez(self.root/'anim.npz',m0=np.zeros((7,2,3)),f0=np.zeros(7))
        e=self.entry(path);e.descriptor.companions={'animation':'anim.npz'}
        model=prepare_local_model(e)
        self.assertTrue(any('stale vertex animation' in w for w in model.runtime_warnings))
        self.assertEqual(len(model.items),1)
    def test_missing_parts_and_optional_sidecars_warn_only(self):
        e=self.entry(self.fixture(),runtime_controls={'native':{'viewer_cameras':{'Side':{'position':[2,2,2],'target':[0,0,0],'hidden':['Wall','Removed']}}}})
        e.descriptor.companions={'viewer':'missing.viewer.json'}
        model=prepare_local_model(e)
        self.assertEqual(model.cameras['Side']['hidden'],['Wall'])
        self.assertTrue(any('removed-part' in w for w in model.runtime_warnings))
        self.assertTrue(any('unavailable' in w for w in model.runtime_warnings))
    def test_invalid_normals_recover_and_cancel_propagates(self):
        warnings=[];_,rows=decode_local_npz(self.fixture(n0=np.zeros((3,3))),warnings=warnings)
        self.assertTrue(warnings);self.assertTrue(np.isfinite(rows[0][2]).all())
        class Cancel:
            def check(self): raise RuntimeError('cancelled')
        with self.assertRaisesRegex(RuntimeError,'cancelled'):prepare_local_model(self.entry(self.fixture()),Cancel())
    def test_native_widget_constructor_without_render(self):
        from PySide6.QtWidgets import QApplication
        from app.ui.model_view import ModelView
        from app.config import DEFAULT_SETTINGS
        app=QApplication.instance() or QApplication([])
        e=self.entry(self.fixture())
        e.kind='procedural';e.kind_name='3D microanatomy model';e.histology=[];e.related=[]
        e.clinical=[];e.credit_html='';e.targets={};e.components=()
        m=prepare_local_model(e)
        view=ModelView(e,SimpleNamespace(micro_models={e.id:e},tissues={}),DEFAULT_SETTINGS,
                       prepared=SimpleNamespace(model=m,seconds=0))
        self.assertIs(view.vmodel,m)
        self.assertFalse(view.isVisible())
        view.deleteLater();app.processEvents()

    def test_glb_native_loader(self):
        import struct
        path=self.root/'simple.glb'
        data=self.v.tobytes()+np.array([0,1,2],dtype=np.uint32).tobytes()
        doc={"asset":{"version":"2.0"},"buffers":[{"byteLength":len(data)}],
             "bufferViews":[{"buffer":0,"byteOffset":0,"byteLength":36},{"buffer":0,"byteOffset":36,"byteLength":12}],
             "accessors":[{"bufferView":0,"componentType":5126,"count":3,"type":"VEC3","min":[0,0,0],"max":[1,1,0]},
                          {"bufferView":1,"componentType":5125,"count":3,"type":"SCALAR"}],
             "meshes":[{"primitives":[{"attributes":{"POSITION":0},"indices":1}]}],
             "nodes":[{"mesh":0,"name":"Wall"}],"scenes":[{"nodes":[0]}],"scene":0}
        raw=json.dumps(doc).encode();raw+=b' '*((-len(raw))%4)
        path.write_bytes(struct.pack('<III',0x46546c67,2,12+8+len(raw)+8+len(data))+struct.pack('<II',len(raw),0x4e4f534a)+raw+struct.pack('<II',len(data),0x004e4942)+data)
        model=prepare_local_model(self.entry(path))
        self.assertEqual(len(model.items),1)
        self.assertEqual(model.camera_order,['Home'])
        self.assertEqual(model.runtime_descriptor.primary.format,'glb')

if __name__=='__main__':unittest.main()
